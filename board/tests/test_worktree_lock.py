import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server_lock", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

# WITH_START was captured from a real lock: Claude Code 2.1.301, 2026-10-16, via
# `claude -w lockprobe -p "reply ok"` in a temp repo; `git worktree list --porcelain` showed
#   locked claude session lockprobe (pid 99047 start Fri Oct 16 19:12:53 2026)
# (pid and name substituted below). Note `start` is a date string, not an epoch.
# NO_START is not captured: it is the binary-derived form without a start time
# (flake-and-locks.md, Issue B); the live lock above always carried a start.
WITH_START = "claude session {n} (pid {pid} start Fri Oct 16 19:12:53 2026)"
NO_START = "claude session {n} (pid {pid})"

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **GIT_ENV})


class LockCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        run("git", "init", "-b", "main", cwd=self.repo)
        run("git", "commit", "--allow-empty", "-m", "init", cwd=self.repo)
        self.wt = self.repo / ".claude" / "worktrees" / "w1"
        run("git", "worktree", "add", str(self.wt), "-b", "w1", cwd=self.repo)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dead_pid(self):
        p = subprocess.Popen(["true"])
        p.wait()
        return p.pid

    def sleeper(self):
        p = subprocess.Popen(["sleep", "30"])
        self.procs.append(p)
        return p.pid

    def lock(self, reason):
        run("git", "worktree", "lock", "--reason", reason, str(self.wt), cwd=self.repo)

    def item(self):
        return server.worktrees(str(self.repo))["items"][0]

    def remove(self):
        return server.remove_agent_worktree(str(self.repo), self.item())

    def listed(self):
        return "w1" in subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True).stdout

    def reason(self):
        return self.item()["locked"]

    def test_owner_parses_both_formats(self):
        self.assertEqual(server.claude_lock_owner(WITH_START.format(n="a b", pid=123)), 123)
        self.assertEqual(server.claude_lock_owner(NO_START.format(n="w1", pid=45)), 45)
        self.assertIsNone(server.claude_lock_owner("manual hold"))
        self.assertIsNone(server.claude_lock_owner("claude"))
        self.assertIsNone(server.claude_lock_owner(None))

    def test_dead_pid_clean_tree_is_removed(self):
        self.lock(NO_START.format(n="w1", pid=self.dead_pid()))
        msg = self.remove()
        self.assertIn("unlocked stale lock", msg)
        self.assertFalse(self.listed())

    def test_live_claude_pid_is_refused(self):
        reason = WITH_START.format(n="w1", pid=self.sleeper())
        self.lock(reason)
        pid = server.claude_lock_owner(reason)
        with mock.patch.object(server, "proc_args", return_value="/usr/bin/claude -w w1"):
            with self.assertRaisesRegex(RuntimeError, "in use"):
                self.remove()
        self.assertEqual(self.reason(), reason)
        self.assertTrue(self.listed())
        self.assertTrue(pid)

    def test_live_non_claude_pid_is_stale(self):
        self.lock(NO_START.format(n="w1", pid=self.sleeper()))
        self.remove()
        self.assertFalse(self.listed())

    def test_non_claude_reason_is_refused(self):
        self.lock("manual hold")
        with self.assertRaisesRegex(RuntimeError, "manual hold"):
            self.remove()
        self.assertEqual(self.reason(), "manual hold")

    def test_dirty_tree_is_refused_and_relocked(self):
        reason = NO_START.format(n="w1", pid=self.dead_pid())
        self.lock(reason)
        (self.wt / "keep.txt").write_text("mine")
        with self.assertRaises(RuntimeError):
            self.remove()
        self.assertEqual(self.reason(), reason)
        self.assertEqual((self.wt / "keep.txt").read_text(), "mine")

    def test_worktrees_reports_lock(self):
        self.assertIsNone(self.item()["locked"])
        self.lock("manual hold")
        self.assertEqual(self.item()["locked"], "manual hold")


if __name__ == "__main__":
    unittest.main()
