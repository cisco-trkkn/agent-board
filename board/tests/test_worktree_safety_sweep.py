"""test_worktree_safety, part "sweep": Sweep, SweepSquash (the fixtures are in worktree_fixtures.py)."""
import io
import shutil
import sys
import unittest
from pathlib import Path
from datetime import datetime
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree_fixtures import (  # noqa: E402
    NOW,
    StateBase,
    add_worktree,
    git,
    glab_stub,
    head,
    write_stub,
    ws)


class Sweep(StateBase):
    def sweep(self, **kw):
        return ws.sweep(str(self.repo), **kw)

    def test_safe_removed_others_kept(self):
        add_worktree(self.repo, "merged")
        add_worktree(self.repo, "fresh", commits=1, age_days=2)
        add_worktree(self.repo, "old", commits=1, age_days=9)
        dirty = add_worktree(self.repo, "dirty")
        (dirty / "x").write_text("x")
        lines = self.sweep(now=NOW)
        self.assertIn("removed merged", lines)
        self.assertIn("kept fresh (not merged)", lines)
        self.assertIn("stale old (9d)", lines)
        self.assertTrue(any(l.startswith("kept dirty (") for l in lines))
        self.assertFalse(self.listed("merged"))
        for n in ("fresh", "old", "dirty"):
            self.assertTrue(self.listed(n), n)
        self.assertNotIn("merged", self.branches())

    def test_log_lines_are_five_tab_separated_fields(self):
        add_worktree(self.repo, "merged")
        add_worktree(self.repo, "fresh", commits=1, age_days=2)
        add_worktree(self.repo, "old", commits=1, age_days=9)
        self.sweep(now=NOW)
        rows = {}
        for l in self.log_lines():
            f = l.split("\t")
            self.assertEqual(len(f), 5, l)
            rows[f[3]] = f
        self.assertEqual(set(rows), {"merged", "fresh", "old"})
        datetime.fromisoformat(rows["merged"][0])
        for f in rows.values():
            self.assertEqual(f[1], str(self.repo))
        self.assertEqual(rows["merged"][2:], ["removed", "merged", ""])
        self.assertEqual(rows["fresh"][2:], ["kept", "fresh", "not merged"])
        self.assertEqual(rows["old"][2:], ["stale", "old", "9d"])

    def test_log_line_written_as_each_item_is_decided(self):
        add_worktree(self.repo, "a")
        add_worktree(self.repo, "b")
        real = ws.remove
        n = []

        def boom(*args, **kw):
            n.append(1)
            if len(n) == 2:
                raise ValueError("boom")
            return real(*args, **kw)
        with mock.patch.object(ws, "remove", boom):
            with self.assertRaises(ValueError):
                self.sweep()
        log = [l.split("\t") for l in self.log_lines()]
        self.assertEqual(len(log), 1, log)
        self.assertEqual(log[0][2], "removed")

    def test_log_write_failure_does_not_fail_the_sweep(self):
        add_worktree(self.repo, "merged")
        (self.state / "worktree-sweep.log").mkdir(parents=True)   # opening it for append raises OSError
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            lines = self.sweep()
        self.assertEqual(lines, ["removed merged"])
        self.assertFalse(self.listed("merged"))
        self.assertIn("log", err.getvalue())

    def test_dry_run_removes_nothing(self):
        add_worktree(self.repo, "merged")
        lines = self.sweep(dry_run=True)
        self.assertEqual(lines, ["would-remove merged"])
        self.assertTrue(self.listed("merged"))
        self.assertEqual(self.log_lines()[0].split("\t")[2:], ["would-remove", "merged", ""])

    def test_pane_appearing_between_checks_keeps_it(self):
        wt = add_worktree(self.repo, "merged")
        panes = Path(self.tmp) / "panes"
        panes.write_text("")
        self.set_env(AW_TMUX=write_stub(self.bin / "tmuxf", f'cat "{panes}"\n'))
        real = ws.classify
        calls = []

        def wrapped(*a, **k):
            r = real(*a, **k)
            calls.append(k)
            if len(calls) == 1:
                panes.write_text(f"1\t{wt}\n")
            return r
        with mock.patch.object(ws, "classify", wrapped):
            lines = self.sweep()
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.listed("merged"))
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("kept merged ("), lines)

    def test_ancestor_safe_uses_branch_d_squash_uses_D(self):
        add_worktree(self.repo, "merged")
        real = ws._git
        seen = []

        def spy(cwd, *a):
            seen.append(a)
            return real(cwd, *a)
        with mock.patch.object(ws, "_git", spy):
            self.sweep()
        self.assertTrue([a for a in seen if a[:3] == ("branch", "-d", "merged")])
        self.assertFalse([a for a in seen if "-D" in a])

    def test_sweep_leaves_a_prunable_outside_worktree_listed(self):
        outside = Path(self.tmp) / "outside"
        git("worktree", "add", "--detach", str(outside), cwd=self.repo)
        shutil.rmtree(outside)
        add_worktree(self.repo, "merged")
        self.assertEqual(self.sweep(), ["removed merged"])
        self.assertIn("outside", git("worktree", "list", cwd=self.repo).stdout)

    def test_stale_never_removed_even_with_old_age(self):
        add_worktree(self.repo, "old", commits=1, age_days=30)
        self.sweep(now=NOW)
        self.assertTrue(self.listed("old"))

    def test_only_sweeps_just_that_worktree(self):
        a = add_worktree(self.repo, "a")
        add_worktree(self.repo, "b")
        lines = self.sweep(only=str(a))
        self.assertEqual(lines, ["removed a"])
        self.assertTrue(self.listed("b"))

    def test_lock_held_by_live_pid_prints_already_running(self):
        add_worktree(self.repo, "merged")
        lockdir = ws.sweep_lockdir(str(self.repo))
        lockdir.mkdir(parents=True)
        (lockdir / "pid").write_text(str(self.sleeper()))
        self.assertEqual(self.sweep(), ["sweep already running"])
        self.assertTrue(self.listed("merged"))

    def test_lock_with_dead_pid_is_taken_over_and_released(self):
        add_worktree(self.repo, "merged")
        lockdir = ws.sweep_lockdir(str(self.repo))
        lockdir.mkdir(parents=True)
        (lockdir / "pid").write_text(str(self.dead_pid()))
        self.assertEqual(self.sweep(), ["removed merged"])
        self.assertFalse(lockdir.exists())

    def test_lock_released_after_error(self):
        with mock.patch.object(ws, "classify", side_effect=ws.NotARepo("x")):
            with self.assertRaises(ws.NotARepo):
                self.sweep()
        self.assertFalse(ws.sweep_lockdir(str(self.repo)).exists())


class SweepSquash(StateBase):
    def test_squash_safe_removed_with_branch_D(self):
        origin = Path(self.tmp) / "origin.git"
        git("init", "--bare", "-b", "main", str(origin), cwd=self.tmp)
        git("remote", "add", "origin", str(origin), cwd=self.repo)
        git("push", "-u", "origin", "main", cwd=self.repo)
        wt = add_worktree(self.repo, "w1", commits=1, age_days=1)
        git("push", "-u", "origin", "w1", cwd=wt)
        git("push", "origin", "--delete", "w1", cwd=self.repo)
        git("fetch", "--prune", cwd=self.repo)
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", head(wt)))
        lines = ws.sweep(str(self.repo))
        self.assertEqual(lines, ["removed w1"])
        self.assertNotIn("w1", self.branches())


if __name__ == "__main__":
    unittest.main()
