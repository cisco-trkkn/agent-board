"""The board's remove actions and stop_agent's wait for the worker's processes (fixtures in worktree_board_fixtures.py)."""
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree_board_fixtures import (  # noqa: E402
    BoardBase, Fake, WITH_START, add_worktree, server, git)


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
        # the wait polls with time.sleep(0.2) between looks; "no wait" means it never slept, whatever the load did to
        # the wall clock of the rest of stop_agent (git calls in the sweep)
        with mock.patch.object(server, "WORKER_EXIT_WAIT", 5), \
                mock.patch.object(server.time, "sleep", wraps=time.sleep) as slept:
            self.stop(lambda: None)
        slept.assert_not_called()


if __name__ == "__main__":
    unittest.main()
