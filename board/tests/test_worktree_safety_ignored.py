"""test_worktree_safety, part "ignored": IgnoredFiles, Symlinks (the fixtures are in worktree_fixtures.py)."""
import os
import sys
import unittest
import subprocess
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree_fixtures import (  # noqa: E402
    NOW,
    StateBase,
    WITH_START,
    add_worktree,
    git,
    glab_stub,
    head,
    ws)


class IgnoredFiles(StateBase):
    """A worktree that would be safe is kept when it holds git-ignored files other than caches: removal deletes them."""
    IGNORE = ".superpowers/\n.agent-ci/\nnotes/\nscratch*/\n__pycache__/\n.pytest_cache/\n.DS_Store\n*.pyc\n"

    def setUp(self):
        super().setUp()
        (self.repo / ".gitignore").write_text(self.IGNORE)
        git("add", ".gitignore", cwd=self.repo)
        git("commit", "-m", "ignore", cwd=self.repo)

    def put(self, wt, rel, text="x"):
        f = wt / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    def test_only_caches_is_still_safe(self):
        wt = add_worktree(self.repo, "w1")
        for rel in ("__pycache__/x.pyc", ".pytest_cache/v/cache", "sub/dir/__pycache__/y.cpython-312.pyc", ".DS_Store"):
            self.put(wt, rel)
        item = self.one(name="w1")
        self.assertEqual((item["state"], item["reason"]), ("safe", "merged"))

    def test_sdd_workspace_keeps_it(self):
        wt = add_worktree(self.repo, "w1")
        self.put(wt, ".superpowers/sdd/p/progress.md")
        item = self.one(name="w1")
        self.assertEqual(item["state"], "kept")
        self.assertTrue(item["reason"].startswith("ignored files:"), item["reason"])
        self.assertIn(".superpowers/", item["reason"])

    def test_more_than_three_lists_three_then_ellipsis(self):
        wt = add_worktree(self.repo, "w1")
        for d in ("scratch1", "scratch2", "scratch3", "scratch4", "scratch5"):
            self.put(wt, f"{d}/f")
        reason = self.one(name="w1")["reason"]
        self.assertRegex(reason, r"^ignored files: [^,]+, [^,]+, [^,]+, …$")

    def test_exactly_three_has_no_ellipsis(self):
        wt = add_worktree(self.repo, "w1")
        for d in ("scratch1", "scratch2", "scratch3"):
            self.put(wt, f"{d}/f")
        self.assertNotIn("…", self.one(name="w1")["reason"])

    def test_cache_beside_real_file_still_keeps(self):
        wt = add_worktree(self.repo, "w1")
        self.put(wt, "__pycache__/x.pyc")
        self.put(wt, "notes/a.txt")
        reason = self.one(name="w1")["reason"]
        self.assertIn("notes/", reason)
        self.assertNotIn("__pycache__", reason)

    def test_ignored_listing_failure_fails_closed(self):
        wt = add_worktree(self.repo, "w1")
        real = ws._git

        def fake(cwd, *args):
            if "--ignored" in args:
                return subprocess.CompletedProcess(args, 128, "", "fatal: boom")
            return real(cwd, *args)
        with mock.patch.object(ws, "_git", fake):
            item = self.one(name="w1")
        self.assertEqual(item["state"], "kept")
        self.assertEqual(item["reason"], "can't list ignored files: fatal: boom")

    def test_squash_verified_with_ignored_file_is_kept(self):
        origin = Path(self.tmp) / "origin.git"
        git("init", "--bare", "-b", "main", str(origin), cwd=self.tmp)
        git("remote", "add", "origin", str(origin), cwd=self.repo)
        git("push", "-u", "origin", "main", cwd=self.repo)
        wt = add_worktree(self.repo, "w1", commits=1, age_days=1)
        git("push", "-u", "origin", "w1", cwd=wt)
        git("push", "origin", "--delete", "w1", cwd=self.repo)
        git("fetch", "--prune", cwd=self.repo)
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", head(wt)))
        self.put(wt, ".agent-ci/state")
        item = self.one(fetch=True, name="w1")
        self.assertEqual(item["state"], "kept")
        self.assertTrue(item["reason"].startswith("ignored files:"), item["reason"])

    def test_sweep_keeps_it_and_the_file_survives(self):
        wt = add_worktree(self.repo, "w1")
        self.put(wt, ".agent-ci/state")
        lines = ws.sweep(str(self.repo), now=NOW)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("kept w1 (ignored files:"), lines)
        self.assertTrue(self.listed("w1"))
        self.assertTrue((wt / ".agent-ci" / "state").exists())

    def test_remove_by_the_user_still_removes_it(self):
        wt = add_worktree(self.repo, "w1")
        self.put(wt, ".agent-ci/state")
        msg = ws.remove(str(self.repo), str(wt))
        self.assertEqual(msg, "removed worktree w1; deleted branch w1")
        self.assertFalse(self.listed("w1"))


class Symlinks(StateBase):
    """A symlink that is untracked or ignored holds no data: it never blocks classify, the sweep or remove,
    and removing it never touches its target."""

    def setUp(self):
        super().setUp()
        self.target = Path(self.tmp) / "outside_venv"
        self.target.mkdir()
        (self.target / "keep.txt").write_text("keep")

    def link(self, wt, name=".venv"):
        os.symlink(self.target, wt / name)

    def ignore(self, line):
        (self.repo / ".gitignore").write_text(line + "\n")
        git("add", ".gitignore", cwd=self.repo)
        git("commit", "-m", "ignore", cwd=self.repo)

    def assert_target_intact(self):
        self.assertEqual((self.target / "keep.txt").read_text(), "keep")

    def check_safe_and_removed(self, wt):
        item = self.one(name="w1")
        self.assertEqual((item["state"], item["reason"]), ("safe", "merged"))
        ws.remove(str(self.repo), str(wt))
        self.assertFalse(self.listed("w1"))
        self.assertFalse(wt.exists())
        self.assert_target_intact()

    def test_untracked_symlink_is_safe_and_removable(self):
        wt = add_worktree(self.repo, "w1")
        self.link(wt)
        self.check_safe_and_removed(wt)

    def test_ignored_symlink_is_safe_and_removable(self):
        self.ignore(".venv")
        wt = add_worktree(self.repo, "w1")
        self.link(wt)
        self.assertIn("!! .venv", git("status", "--porcelain", "--ignored", cwd=wt).stdout)
        self.check_safe_and_removed(wt)

    def test_symlink_to_dir_under_a_dir_only_pattern_is_safe_and_removable(self):
        self.ignore(".venv/")   # matches directories only, so the link shows as `?? .venv`
        wt = add_worktree(self.repo, "w1")
        self.link(wt)
        self.assertIn("?? .venv", git("status", "--porcelain", cwd=wt).stdout)
        self.check_safe_and_removed(wt)

    def test_sweep_removes_it(self):
        wt = add_worktree(self.repo, "w1")
        self.link(wt)
        ws.sweep(str(self.repo), now=NOW)
        self.assertFalse(self.listed("w1"))
        self.assert_target_intact()

    def test_untracked_regular_file_still_dirty_and_refused(self):
        wt = add_worktree(self.repo, "w1")
        self.link(wt)
        (wt / "x.txt").write_text("x")
        self.assertEqual(self.one(name="w1")["state"], "dirty")
        with self.assertRaisesRegex(RuntimeError, "uncommitted"):
            ws.remove(str(self.repo), str(wt))
        self.assertTrue(wt.exists())
        self.assertTrue((wt / ".venv").is_symlink())   # a refusal leaves the link alone

    def test_ignored_regular_dir_with_a_file_still_kept(self):
        self.ignore("notes/")
        wt = add_worktree(self.repo, "w1")
        (wt / "notes").mkdir()
        (wt / "notes" / "a.txt").write_text("a")
        self.link(wt)
        item = self.one(name="w1")
        self.assertEqual(item["state"], "kept")
        self.assertIn("notes/", item["reason"])
        self.assertNotIn(".venv", item["reason"])

    def test_tracked_symlink_change_is_still_dirty(self):
        wt = add_worktree(self.repo, "w1")
        self.link(wt, "lnk")
        git("add", "lnk", cwd=wt)
        git("commit", "-m", "link", cwd=wt)
        git("merge", "w1", cwd=self.repo)
        (wt / "lnk").unlink()
        os.symlink(self.tmp, wt / "lnk")
        self.assertEqual(self.one(name="w1")["state"], "dirty")


    # -- review fixes: the re-check before unlinking, unlink errors, the git-refusal path, rename parsing --

    def stale_locked(self, wt):
        reason = WITH_START.format(n="w1", pid=self.dead_pid())
        self.lock(wt, reason)
        return reason

    def is_locked(self, reason):
        return reason in git("worktree", "list", "--porcelain", cwd=self.repo).stdout

    def test_link_replaced_by_a_file_before_unlinking_is_not_deleted(self):
        wt = add_worktree(self.repo, "w1")
        self.link(wt)
        reason = self.stale_locked(wt)

        def swap(pid, fn=None):   # the stale-lock check runs between the status snapshot and the unlink
            os.unlink(wt / ".venv")
            (wt / ".venv").write_text("real work")
            return True
        with mock.patch.object(ws, "lock_is_stale", swap):
            with self.assertRaisesRegex(RuntimeError, r"\.venv is no longer a symlink"):
                ws.remove(str(self.repo), str(wt))
        self.assertEqual((wt / ".venv").read_text(), "real work")
        self.assertTrue(self.listed("w1"))
        self.assertTrue(self.is_locked(reason))

    def failing_unlink(self):
        real = os.unlink

        def fail(p, *a, **k):
            if str(p).endswith(".venv"):
                raise PermissionError(1, "Operation not permitted", str(p))
            return real(p, *a, **k)
        return mock.patch.object(ws.os, "unlink", fail)

    def test_unlink_error_is_a_runtime_error_and_restores_the_lock(self):
        wt = add_worktree(self.repo, "w1")
        self.link(wt)
        reason = self.stale_locked(wt)
        with self.failing_unlink():
            with self.assertRaisesRegex(RuntimeError, r"can't remove link \.venv"):
                ws.remove(str(self.repo), str(wt))
        self.assertTrue(self.listed("w1"))
        self.assertTrue(self.is_locked(reason))

    def test_sweep_goes_on_after_an_unlink_error(self):
        w1 = add_worktree(self.repo, "w1")
        add_worktree(self.repo, "w2")
        self.link(w1)
        with self.failing_unlink():
            lines = ws.sweep(str(self.repo), now=NOW)
        self.assertTrue(self.listed("w1"))
        self.assertFalse(self.listed("w2"), lines)

    def test_late_file_makes_git_refuse_and_nothing_is_lost(self):
        wt = add_worktree(self.repo, "w1")
        self.link(wt)
        reason = self.stale_locked(wt)
        real = ws._git

        def late(cwd, *args):
            if args[:2] == ("worktree", "remove"):
                (wt / "late.txt").write_text("appeared after the status")
            return real(cwd, *args)
        with mock.patch.object(ws, "_git", late):
            with self.assertRaises(RuntimeError):
                ws.remove(str(self.repo), str(wt))
        self.assertTrue(self.listed("w1"))
        self.assertTrue((wt / "late.txt").exists())
        self.assertTrue(self.is_locked(reason))
        self.assert_target_intact()

    def test_rename_with_an_R_in_the_source_path_parses_to_one_entry(self):
        wt = add_worktree(self.repo, "w1")
        (wt / "README.md").write_text("same content " * 20)
        git("add", "README.md", cwd=wt)
        git("commit", "-m", "r", cwd=wt)
        os.rename(wt / "README.md", wt / "moved_elsewhere.md")
        git("add", "-N", "moved_elsewhere.md", cwd=wt)
        raw = git("status", "--porcelain", "-z", cwd=wt).stdout
        self.assertEqual(raw[:2], " R", raw)   # the status letter is in the second column
        entries, err = ws._status(str(wt))
        self.assertIsNone(err)
        self.assertEqual(entries, [(" R", "moved_elsewhere.md")])


if __name__ == "__main__":
    unittest.main()
