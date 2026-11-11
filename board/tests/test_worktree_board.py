"""The board's worktree poll, the last sweep, and stop_agent (fixtures in worktree_board_fixtures.py)."""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree_board_fixtures import (  # noqa: E402
    BoardBase, Fake, add_worktree, server, git)


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

    def test_dirty_follows_classify_for_links(self):
        link_only = add_worktree(self.repo, "linkonly")
        os.symlink(self.tmp, link_only / ".venv")
        regular = add_worktree(self.repo, "regular")
        (regular / "x").write_text("x")
        self.assertEqual((self.item("linkonly")["state"], self.item("linkonly")["dirty"]), ("safe", False))
        self.assertEqual((self.item("regular")["state"], self.item("regular")["dirty"]), ("dirty", True))


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


if __name__ == "__main__":
    unittest.main()
