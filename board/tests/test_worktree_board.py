import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_worktree_safety import (GIT_ENV, WITH_START, add_worktree, git, glab_stub, head, make_repo,  # noqa: E402
                                  tmux_stub, write_stub)

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server_wtboard", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
SEP = server.SEP


class BoardBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = make_repo(self.tmp)
        self.bin = Path(self.tmp) / "stubs"
        self.bin.mkdir()
        self.state = Path(self.tmp) / "state"
        self.marker = Path(self.tmp) / "glab-called"
        patcher = mock.patch.dict(os.environ, {
            "AW_TMUX": tmux_stub(self.bin / "tmux"), "AW_STATE_DIR": str(self.state),
            "AW_GLAB": glab_stub(self.bin / "glab", "0" * 40, marker=self.marker)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.procs = []
        server.forget_worktrees()

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def listed(self, name):
        return name in git("worktree", "list", cwd=self.repo).stdout

    def item(self, name):
        return next(i for i in server.worktrees(str(self.repo))["items"] if i["name"] == name)


class Poll(BoardBase):
    def test_poll_is_offline_and_keeps_existing_keys(self):
        origin = Path(self.tmp) / "origin.git"
        git("init", "--bare", "-b", "main", str(origin), cwd=self.tmp)
        git("remote", "add", "origin", str(origin), cwd=self.repo)
        git("push", "-u", "origin", "main", cwd=self.repo)
        wt = add_worktree(self.repo, "w1", commits=1, age_days=1)
        git("push", "-u", "origin", "w1", cwd=wt)
        git("push", "origin", "--delete", "w1", cwd=self.repo)
        git("fetch", "--prune", cwd=self.repo)
        real, seen = subprocess.run, []

        def spy(cmd, *a, **k):
            seen.append(list(cmd))
            return real(cmd, *a, **k)
        with mock.patch.object(subprocess, "run", spy):
            res = server.worktrees(str(self.repo))
        self.assertFalse(self.marker.exists(), "glab was called by the poll")
        self.assertFalse([c for c in seen if "fetch" in c], "git fetch ran in the poll")
        it = res["items"][0]
        for k in ("path", "name", "branch", "dirty", "merged", "age", "locked", "state", "reason", "age_days"):
            self.assertIn(k, it)
        self.assertEqual(it["state"], "kept")
        self.assertIn("offline", it["reason"])

    def test_states_reach_the_items(self):
        add_worktree(self.repo, "merged")
        add_worktree(self.repo, "old", commits=1, age_days=9)
        dirty = add_worktree(self.repo, "dirty")
        (dirty / "x").write_text("x")
        self.assertEqual(self.item("merged")["state"], "safe")
        self.assertTrue(self.item("merged")["merged"])
        old = self.item("old")
        self.assertEqual((old["state"], old["age_days"]), ("stale", 9))
        self.assertEqual((self.item("dirty")["state"], self.item("dirty")["dirty"]), ("dirty", True))


class RemoveActions(BoardBase):
    def act(self, **body):
        with mock.patch.object(server, "project_repo", return_value=str(self.repo)), \
                mock.patch.object(server, "session_path", return_value=str(self.repo)):
            return server._act({"session": "proj", **body})

    def test_remove_safe_removes_merged_keeps_unmerged(self):
        add_worktree(self.repo, "merged")
        add_worktree(self.repo, "fresh", commits=1, age_days=1)
        msg = self.act(action="remove_safe_worktrees")
        self.assertIn("removed", msg)
        self.assertIn("kept", msg)
        self.assertIn("merged", msg)
        self.assertFalse(self.listed("merged"))
        self.assertTrue(self.listed("fresh"))

    def test_remove_safe_clears_the_board_cache(self):
        add_worktree(self.repo, "merged")
        server.cached_worktrees(str(self.repo))
        self.act(action="remove_safe_worktrees")
        self.assertEqual(server.cached_worktrees(str(self.repo))["items"], [])

    def test_row_remove_dirty_raises(self):
        wt = add_worktree(self.repo, "w1")
        (wt / "x").write_text("x")
        with self.assertRaises(RuntimeError):
            self.act(action="remove_worktree", path=str(wt))
        self.assertTrue(wt.exists())

    def test_row_remove_stale_locked_merged_unlocks_and_removes(self):
        wt = add_worktree(self.repo, "w1")
        p = subprocess.Popen(["true"])
        p.wait()
        git("worktree", "lock", "--reason", WITH_START.format(n="w1", pid=p.pid), str(wt), cwd=self.repo)
        msg = self.act(action="remove_worktree", path=str(wt))
        self.assertIn("unlocked stale lock", msg)
        self.assertIn("removed worktree w1", msg)
        self.assertFalse(self.listed("w1"))

    def test_row_remove_uses_the_server_proc_args_reader(self):
        # test_worktree_lock.py patches server.proc_args; the engine must honour that
        wt = add_worktree(self.repo, "w1")
        p = subprocess.Popen(["sleep", "30"])
        self.procs.append(p)
        git("worktree", "lock", "--reason", WITH_START.format(n="w1", pid=p.pid), str(wt), cwd=self.repo)
        with mock.patch.object(server, "proc_args", return_value="/usr/bin/claude -w w1"):
            with self.assertRaisesRegex(RuntimeError, "in use"):
                self.act(action="remove_worktree", path=str(wt))


class Fake:
    def __init__(self, wt_path, pane_pids=(), on_kill=None):
        self.wt_path, self.calls, self.pane_pids, self.on_kill = wt_path, [], pane_pids, on_kill

    def tmux(self, *args, check=False):
        self.calls.append(args)
        if args[0] == "list-windows":
            return f"@4{SEP}fix-login{SEP}1{SEP}\n"
        if args[0] == "display-message":
            return self.wt_path + "\n"
        if args[0] == "list-panes":
            return "".join(f"{p}\n" for p in self.pane_pids)
        if args[0] == "kill-window" and self.on_kill:
            self.on_kill()
        return ""


class StopAgent(BoardBase):
    def stop(self, wt_path):
        fake = Fake(str(wt_path))
        with mock.patch.object(server, "tmux", fake.tmux):
            msg = server._act({"action": "stop_agent", "session": "proj", "window": "fix-login"})
        return msg, fake

    def test_merged_clean_worker_worktree_is_removed(self):
        wt = add_worktree(self.repo, "w1")
        msg, fake = self.stop(wt / "sub")
        self.assertIn("shut down worker fix-login", msg)
        self.assertIn("removed", msg)
        self.assertFalse(self.listed("w1"))
        kill = next(i for i, c in enumerate(fake.calls) if c[0] == "kill-window")
        path_q = next(i for i, c in enumerate(fake.calls) if c[0] == "display-message")
        self.assertLess(path_q, kill, "the window's path must be read before it is killed")

    def test_unmerged_worker_worktree_stays_and_message_says_kept(self):
        wt = add_worktree(self.repo, "w1", commits=1, age_days=1)
        msg, _ = self.stop(wt)
        self.assertIn("kept", msg)
        self.assertTrue(self.listed("w1"))

    def test_only_that_worktree_is_swept(self):
        wt = add_worktree(self.repo, "w1")
        add_worktree(self.repo, "other")
        self.stop(wt)
        self.assertFalse(self.listed("w1"))
        self.assertTrue(self.listed("other"))

    def test_worker_outside_agent_worktrees_is_not_swept(self):
        add_worktree(self.repo, "w1")
        msg, _ = self.stop(self.repo)
        self.assertEqual(msg, "shut down worker fix-login; its worktree and branch are still in Worktrees")
        self.assertTrue(self.listed("w1"))


class StopWaitsForExit(BoardBase):
    """tmux-ctl send-keys `claude -w` into the pane's shell: #{pane_pid} is that shell and the worktree lock's pid is
    Claude, a different process that can outlive kill-window. The sweep waits for both."""

    def setUp(self):
        super().setUp()
        self.wt = add_worktree(self.repo, "w1")
        self.shell = subprocess.Popen(["sleep", "30"])     # stands in for the pane's shell
        self.claude = subprocess.Popen(["sleep", "30"])    # holds the lock
        self.procs += [self.shell, self.claude]
        git("worktree", "lock", "--reason", WITH_START.format(n="w1", pid=self.claude.pid), str(self.wt), cwd=self.repo)
        p = mock.patch.object(server.worktree_safety, "proc_args", return_value="/usr/bin/claude -w w1")
        p.start()
        self.addCleanup(p.stop)

    def stop(self, on_kill):
        fake = Fake(str(self.wt), pane_pids=[self.shell.pid], on_kill=on_kill)
        with mock.patch.object(server, "tmux", fake.tmux):
            return server._act({"action": "stop_agent", "session": "proj", "window": "fix-login"})

    @staticmethod
    def die(proc):
        proc.kill()
        proc.wait()

    def test_shell_dies_at_the_kill_claude_a_moment_later_then_removed(self):
        def on_kill():
            self.die(self.shell)
            threading.Timer(0.6, self.die, args=(self.claude,)).start()
        msg = self.stop(on_kill)
        self.assertEqual(msg, "shut down worker fix-login; removed its worktree")
        self.assertFalse(self.listed("w1"))

    def test_lock_owner_outlives_the_deadline_is_kept_and_says_so(self):
        with mock.patch.object(server, "WORKER_EXIT_WAIT", 0.5):
            msg = self.stop(lambda: self.die(self.shell))
        self.assertIn("kept", msg)
        self.assertIn("still running", msg)
        self.assertTrue(self.listed("w1"))

    def test_still_running_pane_pid_with_a_dead_lock_owner_still_sweeps_without_a_note(self):
        self.die(self.claude)
        # the pane shell outlives the deadline, but the worktree is clean and merged, and its lock owner is gone
        with mock.patch.object(server, "WORKER_EXIT_WAIT", 0.5):
            msg = self.stop(lambda: None)
        self.assertEqual(msg, "shut down worker fix-login; removed its worktree")
        self.assertFalse(self.listed("w1"))

    def test_no_wait_when_everything_is_already_gone(self):
        self.die(self.shell)
        self.die(self.claude)
        t = time.monotonic()
        with mock.patch.object(server, "WORKER_EXIT_WAIT", 5):
            self.stop(lambda: None)
        self.assertLess(time.monotonic() - t, 3)


class LastSweep(BoardBase):
    def write_log(self, rows):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "worktree-sweep.log").write_text("".join("\t".join(r) + "\n" for r in rows))

    def test_none_without_a_log(self):
        self.assertIsNone(server.last_sweep())

    def test_counts_of_the_latest_run_only(self):
        r = str(self.repo)
        self.write_log([
            ("2026-10-25T04:00:01+00:00", r, "removed", "old1", ""),
            ("2026-10-26T04:00:01+00:00", r, "removed", "a", ""),
            ("2026-10-26T04:00:02+00:00", r, "removed", "b", ""),
            ("2026-10-26T04:00:03+00:00", r, "stale", "c", "9d"),
            ("2026-10-26T04:00:03+00:00", r, "kept", "d", "not merged"),
        ])
        ls = server.last_sweep()
        self.assertEqual((ls["removed"], ls["stale"]), (2, 1))
        self.assertEqual(ls["at"], "04:00")

    def test_dry_run_lines_are_ignored(self):
        self.write_log([("2026-10-26T04:00:01+00:00", str(self.repo), "would-remove", "a", "")])
        self.assertIsNone(server.last_sweep())


if __name__ == "__main__":
    unittest.main()
