"""test_worktree_safety, part "recent": SweepRecent, MissingDir, Remove, CliSweep (the fixtures are in worktree_fixtures.py)."""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree_fixtures import (  # noqa: E402
    CLI,
    NOW,
    StateBase,
    WITH_START,
    add_worktree,
    git,
    tmux_stub,
    write_stub,
    ws)


class SweepRecent(StateBase):
    def other_repo(self, name):
        d = Path(self.tmp) / name
        d.mkdir()
        git("init", "-b", "main", cwd=d)
        git("commit", "--allow-empty", "-m", "init", cwd=d)
        return d.resolve()

    def test_recent_file_plus_sessions_deduped_and_skips_non_repos(self):
        r2 = self.other_repo("r2")
        add_worktree(self.repo, "m1")
        add_worktree(r2, "m2")
        notrepo = Path(self.tmp) / "plain"
        notrepo.mkdir()
        self.state.mkdir()
        (self.state / "recent-projects.json").write_text(json.dumps([str(self.repo), str(notrepo)]))
        sess = write_stub(self.bin / "tmuxs", f'[ "$1" = list-sessions ] && {{ printf "%s\\n" "{r2}" "{self.repo}"; exit 0; }}\nexit 0\n')
        self.set_env(AW_TMUX=sess)
        lines = ws.sweep_recent()
        self.assertEqual(sum(1 for l in lines if l == "removed m1"), 1, lines)
        self.assertIn("removed m2", lines)
        self.assertIn(f"skip {notrepo} (not a repo)", lines)
        self.assertEqual(len([l for l in lines if l.startswith("skip")]), 1)

    def _no_state_dir_env(self, **extra):
        home = Path(self.tmp) / "home"
        home.mkdir(exist_ok=True)
        p = mock.patch.dict(os.environ, {"HOME": str(home), **extra})
        p.start()
        self.addCleanup(p.stop)
        for k in ("AW_STATE_DIR", "TC_STATE", "TMPDIR"):
            if k not in extra:
                os.environ.pop(k, None)
        return home

    def test_recent_file_read_from_tc_state_when_aw_state_dir_unset(self):
        add_worktree(self.repo, "m1")
        tc = Path(self.tmp) / "tc"
        tc.mkdir()
        (tc / "recent-projects.json").write_text(json.dumps([str(self.repo)]))
        self._no_state_dir_env(TC_STATE=str(tc))
        self.assertEqual(ws.sweep_recent(), ["removed m1"])

    def test_recent_file_read_from_tmpdir_when_tc_state_unset(self):
        add_worktree(self.repo, "m1")
        tmpdir = Path(self.tmp) / "T"
        (tmpdir / f"tmux-ctl-{os.getuid()}").mkdir(parents=True)
        (tmpdir / f"tmux-ctl-{os.getuid()}" / "recent-projects.json").write_text(json.dumps([str(self.repo)]))
        self._no_state_dir_env(TMPDIR=str(tmpdir) + "/")
        self.assertEqual(ws.sweep_recent(), ["removed m1"])

    @unittest.skipUnless(sys.platform == "darwin", "recent_dir() consults the confstr fallback on macOS only")
    def test_recent_file_falls_back_to_darwin_user_temp_dir(self):
        add_worktree(self.repo, "m1")
        tmpdir = Path(self.tmp) / "dt"
        (tmpdir / f"tmux-ctl-{os.getuid()}").mkdir(parents=True)
        (tmpdir / f"tmux-ctl-{os.getuid()}" / "recent-projects.json").write_text(json.dumps([str(self.repo)]))
        self._no_state_dir_env()
        with mock.patch.object(os, "confstr", return_value=str(tmpdir) + "/") as cs:
            self.assertEqual(ws.sweep_recent(), ["removed m1"])
        cs.assert_called_with(65537)   # _CS_DARWIN_USER_TEMP_DIR: Python has no name for it in os.confstr_names

    @unittest.skipUnless(sys.platform == "darwin", "the per-user temp dir is a macOS confstr value")
    def test_darwin_fallback_with_the_real_confstr(self):
        # found by the e2e run: the patched test above hid that os.confstr('CS_DARWIN_USER_TEMP_DIR') raises ValueError
        self._no_state_dir_env()
        real = os.confstr(65537)
        self.assertEqual(ws.recent_dir(), Path(real.rstrip("/")) / f"tmux-ctl-{os.getuid()}")

    def test_lock_and_log_stay_under_home_state_dir_when_unset(self):
        home = self._no_state_dir_env()
        self.assertEqual(ws.state_dir(), home / ".local" / "state" / "agent-board")

    def test_missing_recent_file_is_empty(self):
        self.set_env(AW_TMUX=tmux_stub(self.bin / "t3"))
        self.assertEqual(ws.sweep_recent(), [])

    def test_corrupt_recent_file_raises(self):
        self.state.mkdir()
        (self.state / "recent-projects.json").write_text("{not json")
        with self.assertRaises(ws.StateError):
            ws.sweep_recent()


class MissingDir(StateBase):
    """An agent worktree whose directory was deleted: git lists it `prunable`, and any git call with it as cwd raises."""

    def gone(self, name):
        wt = add_worktree(self.repo, name)
        shutil.rmtree(wt)
        return wt

    def test_classify_lists_it_kept_and_does_not_raise(self):
        self.gone("ghost")
        add_worktree(self.repo, "merged")
        res = ws.classify(str(self.repo), fetch=False, now=NOW)
        by = {i["name"]: i for i in res["items"]}
        self.assertEqual((by["ghost"]["state"], by["ghost"]["reason"]), ("kept", "directory missing (prunable)"))
        self.assertEqual(by["merged"]["state"], "safe")

    def test_no_git_call_runs_inside_the_missing_directory(self):
        wt = self.gone("ghost")
        real = ws.subprocess.run
        cwds = []

        def spy(cmd, *a, **k):
            cwds.append(k.get("cwd"))
            return real(cmd, *a, **k)
        with mock.patch.object(ws.subprocess, "run", spy):
            ws.classify(str(self.repo), fetch=False, now=NOW)
        self.assertNotIn(str(wt), [str(c) for c in cwds])

    def test_any_other_oserror_in_one_item_keeps_it_and_continues(self):
        add_worktree(self.repo, "a")
        add_worktree(self.repo, "b")
        real = ws._classify_one

        def flaky(ctx, wt):
            if Path(wt["path"]).name == "a":
                raise PermissionError("denied")
            return real(ctx, wt)
        with mock.patch.object(ws, "_classify_one", flaky):
            by = {i["name"]: i for i in ws.classify(str(self.repo), fetch=False, now=NOW)["items"]}
        self.assertEqual(by["a"]["state"], "kept")
        self.assertIn("denied", by["a"]["reason"])
        self.assertEqual(by["b"]["state"], "safe")

    def test_sweep_still_removes_a_merged_sibling_and_keeps_the_ghost(self):
        self.gone("ghost")
        add_worktree(self.repo, "merged")
        lines = ws.sweep(str(self.repo))
        self.assertIn("removed merged", lines)
        self.assertIn("kept ghost (directory missing (prunable))", lines)
        self.assertIn("ghost", git("worktree", "list", cwd=self.repo).stdout)   # never pruned by us

    def test_remove_on_a_missing_dir_raises_a_clear_error(self):
        wt = self.gone("ghost")
        with self.assertRaisesRegex(RuntimeError, "directory missing"):
            ws.remove(str(self.repo), str(wt))

    def test_recent_continues_to_the_next_repo(self):
        self.gone("ghost")
        other = Path(self.tmp) / "r2"
        other.mkdir()
        git("init", "-b", "main", cwd=other)
        git("commit", "--allow-empty", "-m", "init", cwd=other)
        add_worktree(other.resolve(), "m2")
        self.state.mkdir(exist_ok=True)
        (self.state / "recent-projects.json").write_text(json.dumps([str(self.repo), str(other.resolve())]))
        lines = ws.sweep_recent()
        self.assertIn("removed m2", lines)

    def test_cli_sweep_exits_zero_with_a_ghost(self):
        self.gone("ghost")
        env = {**os.environ, "AW_TMUX": self.tmux, "AW_STATE_DIR": str(self.state)}
        r = subprocess.run([sys.executable, str(CLI), "sweep", str(self.repo)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kept ghost", r.stdout)


class Remove(StateBase):
    def test_clean_merged_worktree_removed_with_branch(self):
        wt = add_worktree(self.repo, "w1")
        msg = ws.remove(str(self.repo), str(wt))
        self.assertEqual(msg, "removed worktree w1; deleted branch w1")
        self.assertFalse(self.listed("w1"))
        self.assertNotIn("w1", self.branches())

    def test_unmerged_branch_is_kept_not_force_deleted(self):
        wt = add_worktree(self.repo, "w1", commits=1, age_days=1)
        msg = ws.remove(str(self.repo), str(wt))
        self.assertEqual(msg, "removed worktree w1; kept branch w1 (not merged)")
        self.assertIn("w1", self.branches())

    def test_dirty_is_refused_without_force(self):
        wt = add_worktree(self.repo, "w1")
        (wt / "x.txt").write_text("x")
        with self.assertRaisesRegex(RuntimeError, "uncommitted"):
            ws.remove(str(self.repo), str(wt))
        self.assertTrue(wt.exists())

    def test_outside_agent_dir_is_refused(self):
        other = Path(self.tmp) / "elsewhere"
        git("worktree", "add", str(other), "-b", "other", cwd=self.repo)
        with self.assertRaisesRegex(RuntimeError, "not an agent worktree"):
            ws.remove(str(self.repo), str(other))
        self.assertTrue(other.exists())

    def test_live_claude_lock_is_refused(self):
        wt = add_worktree(self.repo, "w1")
        reason = WITH_START.format(n="w1", pid=self.sleeper())
        self.lock(wt, reason)
        with mock.patch.object(ws, "proc_args", return_value="/usr/bin/claude -w w1"):
            with self.assertRaisesRegex(RuntimeError, "in use"):
                ws.remove(str(self.repo), str(wt))
        self.assertTrue(wt.exists())

    def test_manual_lock_is_refused(self):
        wt = add_worktree(self.repo, "w1")
        self.lock(wt, "manual hold")
        with self.assertRaisesRegex(RuntimeError, "locked by something other than Claude"):
            ws.remove(str(self.repo), str(wt))

    def test_stale_lock_is_unlocked_then_removed(self):
        wt = add_worktree(self.repo, "w1")
        self.lock(wt, WITH_START.format(n="w1", pid=self.dead_pid()))
        msg = ws.remove(str(self.repo), str(wt))
        self.assertIn("unlocked stale lock", msg)
        self.assertFalse(self.listed("w1"))

    def test_lock_put_back_when_git_refuses(self):
        wt = add_worktree(self.repo, "w1")
        reason = WITH_START.format(n="w1", pid=self.dead_pid())
        self.lock(wt, reason)
        real = ws._git

        def refuse(cwd, *args):
            if args[:2] == ("worktree", "remove"):
                return subprocess.CompletedProcess(args, 1, "", "fatal: refused")
            return real(cwd, *args)
        with mock.patch.object(ws, "_git", refuse):
            with self.assertRaisesRegex(RuntimeError, "refused"):
                ws.remove(str(self.repo), str(wt))
        self.assertIn(reason, git("worktree", "list", "--porcelain", cwd=self.repo).stdout)

    def test_never_passes_force(self):
        wt = add_worktree(self.repo, "w1")
        real = ws._git
        seen = []

        def spy(cwd, *args):
            seen.append(args)
            return real(cwd, *args)
        with mock.patch.object(ws, "_git", spy):
            ws.remove(str(self.repo), str(wt))
        self.assertTrue([a for a in seen if a[:2] == ("worktree", "remove")])
        self.assertFalse([a for a in seen if "--force" in a or "-f" in a or "-D" in a])
        self.assertFalse([a for a in seen if a[:2] == ("worktree", "prune")], "remove() must not prune repo-wide")

    def test_prunable_worktree_outside_agent_dir_survives_a_removal(self):
        # the scratchpad `frozen` entry of the e2e run: directory gone, metadata left, outside .claude/worktrees/
        outside = Path(self.tmp) / "outside"
        git("worktree", "add", "--detach", str(outside), cwd=self.repo)
        shutil.rmtree(outside)
        before = git("worktree", "list", cwd=self.repo).stdout
        self.assertIn("prunable", before)
        wt = add_worktree(self.repo, "w1")
        ws.remove(str(self.repo), str(wt))
        after = git("worktree", "list", cwd=self.repo).stdout
        self.assertIn("outside", after)
        self.assertIn("prunable", after)
        self.assertFalse(self.listed("w1"))


class CliSweep(StateBase):
    def run_cli(self, *args):
        env = {**os.environ, "AW_TMUX": self.tmux, "AW_STATE_DIR": str(self.state)}
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env)

    def test_sweep_prints_lines_exit_zero(self):
        add_worktree(self.repo, "merged")
        r = self.run_cli("sweep", str(self.repo))
        self.assertEqual((r.returncode, r.stdout.splitlines()), (0, ["removed merged"]), r.stderr)

    def test_sweep_dry_run(self):
        add_worktree(self.repo, "merged")
        r = self.run_cli("sweep", str(self.repo), "--dry-run")
        self.assertEqual(r.stdout.splitlines(), ["would-remove merged"])
        self.assertTrue(self.listed("merged"))

    def test_sweep_not_a_repo_exits_2(self):
        self.assertEqual(self.run_cli("sweep", self.tmp).returncode, 2)

    def test_sweep_busy_exits_zero(self):
        add_worktree(self.repo, "merged")
        lockdir = ws.sweep_lockdir(str(self.repo)) if False else None
        env = {**os.environ, "AW_STATE_DIR": str(self.state)}
        with mock.patch.dict(os.environ, env):
            lockdir = ws.sweep_lockdir(str(self.repo))
        lockdir.mkdir(parents=True)
        (lockdir / "pid").write_text(str(self.sleeper()))
        r = self.run_cli("sweep", str(self.repo))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "sweep already running"))

    def test_sweep_only_and_dir_conflict_with_recent_exit_2(self):
        self.assertEqual(self.run_cli("sweep", "--recent", self.tmp).returncode, 2)

    def test_sweep_recent_cli(self):
        add_worktree(self.repo, "merged")
        self.state.mkdir()
        (self.state / "recent-projects.json").write_text(json.dumps([str(self.repo)]))
        r = self.run_cli("sweep", "--recent")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("removed merged", r.stdout)

    def test_remove_cli(self):
        wt = add_worktree(self.repo, "w1")
        r = self.run_cli("remove", str(wt))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "removed worktree w1; deleted branch w1"), r.stderr)

    def test_remove_cli_refusal_exits_1(self):
        wt = add_worktree(self.repo, "w1")
        (wt / "x").write_text("x")
        r = self.run_cli("remove", str(wt))
        self.assertEqual(r.returncode, 1)
        self.assertIn("uncommitted", r.stderr)

    def test_remove_cli_bad_path_exits_2(self):
        self.assertEqual(self.run_cli("remove", self.tmp).returncode, 2)


if __name__ == "__main__":
    unittest.main()
