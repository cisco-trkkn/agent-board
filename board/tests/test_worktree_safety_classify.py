"""test_worktree_safety, part "classify": ClassifyStates, Timeout, Cli (the fixtures are in worktree_fixtures.py)."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from datetime import timedelta
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree_fixtures import (  # noqa: E402
    Base,
    CLI,
    NOW,
    WITH_START,
    add_worktree,
    git,
    head,
    tmux_stub,
    write_stub,
    ws)


class ClassifyStates(Base):
    def test_shape(self):
        add_worktree(self.repo, "w1")
        res = ws.classify(str(self.repo), fetch=False, now=NOW)
        self.assertEqual(set(res), {"repo", "base", "current", "items"})
        self.assertEqual(res["base"], "main")
        self.assertEqual(res["current"], "main")
        self.assertEqual(set(res["items"][0]),
                         {"path", "name", "branch", "head", "state", "reason", "age_days", "squash"})

    def test_merged_into_base_is_safe(self):
        add_worktree(self.repo, "w1")
        self.assertEqual(self.one()["state"], "safe")

    def test_merged_only_into_current_branch_is_safe(self):
        wt = add_worktree(self.repo, "w1", commits=1, age_days=1)
        git("checkout", "-b", "feature", cwd=self.repo)
        git("merge", "--no-ff", "-m", "m", "w1", cwd=self.repo)
        git("checkout", "main", cwd=self.repo)
        git("checkout", "feature", cwd=self.repo)   # current = feature, base main lacks w1
        item = self.one()
        self.assertEqual((item["state"], head(wt)), ("safe", item["head"]))

    def test_brand_new_worktree_without_commits_is_kept(self):
        add_worktree(self.repo, "w1", created_hours_ago=1)
        item = self.one()
        self.assertEqual((item["state"], item["reason"]), ("kept", "new, no commits yet"))

    def test_the_grace_ends_after_24_hours(self):
        add_worktree(self.repo, "w1", created_hours_ago=25)
        self.assertEqual(self.one()["state"], "safe")

    def test_a_young_worktree_with_a_merged_commit_is_safe(self):
        wt = add_worktree(self.repo, "w1", commits=1, age_days=0, created_hours_ago=1)
        git("merge", "--ff-only", "w1", cwd=self.repo)   # the commit is now on main too
        self.assertEqual((self.one()["state"], head(wt) == self.one()["head"]), ("safe", True))

    def test_creation_dated_after_now_is_still_new(self):
        add_worktree(self.repo, "w1", created_hours_ago=-1)   # "created" an hour after `now`
        self.assertEqual(self.one()["state"], "kept")

    def test_detached_worktree_gets_no_grace(self):
        wt = self.repo / ".claude" / "worktrees" / "d1"
        git("worktree", "add", "--detach", str(wt), cwd=self.repo, date=NOW - timedelta(hours=1))
        item = self.one(name="d1")
        self.assertEqual(item["state"], "safe")

    def test_unreadable_reflog_means_no_grace(self):
        add_worktree(self.repo, "w1", created_hours_ago=1)
        real = ws._git

        def broken(cwd, *args):
            if args[:2] == ("reflog", "show"):
                return subprocess.CompletedProcess(args, 128, "", "fatal: bad")
            return real(cwd, *args)
        with mock.patch.object(ws, "_git", broken):
            self.assertEqual(self.one()["state"], "safe")

    def test_unmerged_recent_is_kept_not_merged(self):
        add_worktree(self.repo, "w1", commits=1, age_days=2)
        item = self.one()
        self.assertEqual(item["state"], "kept")
        self.assertEqual(item["reason"], "not merged")
        self.assertEqual(item["age_days"], 2)

    def test_unmerged_old_is_stale(self):
        add_worktree(self.repo, "w1", commits=1, age_days=9)
        self.assertEqual(self.one()["state"], "stale")

    def test_modified_file_is_dirty(self):
        wt = add_worktree(self.repo, "w1")
        (self.repo / "f.txt").write_text("a")
        git("add", "f.txt", cwd=self.repo)
        git("commit", "-m", "f", cwd=self.repo)
        git("merge", "main", cwd=wt)
        (wt / "f.txt").write_text("changed")
        self.assertEqual(self.one()["state"], "dirty")

    def test_untracked_file_alone_is_dirty(self):
        wt = add_worktree(self.repo, "w1")
        (wt / "new.txt").write_text("x")
        self.assertEqual(self.one()["state"], "dirty")

    def test_live_claude_lock_is_in_use(self):
        wt = add_worktree(self.repo, "w1")
        self.lock(wt, WITH_START.format(n="w1", pid=self.sleeper()))
        with mock.patch.object(ws, "proc_args", return_value="/usr/bin/claude -w w1"):
            self.assertEqual(self.one()["state"], "in_use")

    def test_dead_pid_lock_and_merged_is_safe(self):
        wt = add_worktree(self.repo, "w1")
        self.lock(wt, WITH_START.format(n="w1", pid=self.dead_pid()))
        self.assertEqual(self.one()["state"], "safe")

    def test_manual_hold_lock_is_kept(self):
        wt = add_worktree(self.repo, "w1")
        self.lock(wt, "manual hold")
        item = self.one()
        self.assertEqual(item["state"], "kept")
        self.assertIn("manual hold", item["reason"])

    def test_pane_cwd_inside_worktree_is_in_use(self):
        wt = add_worktree(self.repo, "w1")
        self.set_env(AW_TMUX=tmux_stub(self.bin / "tmux2", [(4242, str(wt / "sub"))]))
        self.assertEqual(self.one()["state"], "in_use")

    def test_pane_with_sibling_prefix_path_is_not_a_match(self):
        wt = add_worktree(self.repo, "w1")
        self.set_env(AW_TMUX=tmux_stub(self.bin / "tmux2", [(4242, str(wt) + "-other")]))
        self.assertEqual(self.one()["state"], "safe")

    def test_tmux_failure_fails_closed(self):
        add_worktree(self.repo, "w1")
        self.set_env(AW_TMUX=tmux_stub(self.bin / "tmux2", fail="protocol version mismatch"))
        item = self.one()
        self.assertEqual(item["state"], "kept")
        self.assertIn("can't check tmux panes", item["reason"])

    def test_no_server_running_means_no_panes(self):
        add_worktree(self.repo, "w1")
        self.set_env(AW_TMUX=tmux_stub(self.bin / "tmux2", fail="no server running on /tmp/x"))
        self.assertEqual(self.one()["state"], "safe")

    def test_default_servers_are_both_checked(self):
        wt = add_worktree(self.repo, "w1")
        log = Path(self.tmp) / "queried"
        own = write_stub(self.bin / "own", f'echo own >> "{log}"\n')
        plain = write_stub(self.bin / "tmux", f'echo plain >> "{log}"\nprintf \'1\\t%s\\n\' \'{wt}\'\n')
        env = {k: v for k, v in os.environ.items() if k != "AW_TMUX"}
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(ws, "tmux_cmd", return_value=[own]):
            self.assertEqual(self.one()["state"], "in_use")
        self.assertEqual(sorted(log.read_text().split()), ["own", "plain"])

    def test_aw_tmux_is_word_split(self):
        add_worktree(self.repo, "w1")
        stub = write_stub(self.bin / "tmuxargs", '[ "$1" = "-L" ] && [ "$2" = "sock" ] || { echo bad args >&2; exit 1; }\n')
        self.set_env(AW_TMUX=f"{stub} -L sock")
        self.assertEqual(self.one()["state"], "safe")

    def test_missing_socket_error_means_no_panes(self):
        add_worktree(self.repo, "w1")
        # real text from `~/.local/bin/tmux -L aw-nosock-91091 -f /dev/null list-panes -a` (rc 1), 2026-10-26
        msg = "error connecting to /private/tmp/tmux-503/aw-nosock-91091 (No such file or directory)"
        self.set_env(AW_TMUX=tmux_stub(self.bin / "tmux2", fail=msg))
        self.assertEqual(self.one()["state"], "safe")

    def test_other_connect_error_still_fails_closed(self):
        add_worktree(self.repo, "w1")
        msg = "error connecting to /tmp/tmux-503/default (Permission denied)"
        self.set_env(AW_TMUX=tmux_stub(self.bin / "tmux2", fail=msg))
        self.assertEqual(self.one()["state"], "kept")

    def test_agent_dir_segment_elsewhere_not_listed(self):
        add_worktree(self.repo, "w1")
        far = Path(self.tmp) / "other" / ".claude" / "worktrees" / "far"
        git("worktree", "add", str(far), "-b", "far", cwd=self.repo)
        res = ws.classify(str(self.repo), fetch=False, now=NOW)
        self.assertEqual([i["name"] for i in res["items"]], ["w1"])

    def test_worktree_outside_claude_worktrees_not_listed(self):
        other = Path(self.tmp) / "elsewhere"
        git("worktree", "add", str(other), "-b", "other", cwd=self.repo)
        add_worktree(self.repo, "w1")
        res = ws.classify(str(self.repo), fetch=False, now=NOW)
        self.assertEqual([i["name"] for i in res["items"]], ["w1"])

    def test_not_a_repo_raises(self):
        with self.assertRaises(ws.NotARepo):
            ws.classify(self.tmp, fetch=False, now=NOW)


class Timeout(Base):
    def test_timeout_gives_kept(self):
        add_worktree(self.repo, "w1")
        real = subprocess.run

        def slow(cmd, *a, **k):
            if cmd[:3] == ["git", "status", "--porcelain"]:
                raise subprocess.TimeoutExpired(cmd, 20)
            return real(cmd, *a, **k)
        with mock.patch.object(ws.subprocess, "run", slow):
            item = self.one()
        self.assertEqual(item["state"], "kept")
        self.assertIn("timed out", item["reason"])


class Cli(Base):
    def run_cli(self, *args):
        env = {**os.environ, "AW_TMUX": self.tmux}
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env)

    def test_plain_output_and_exit_zero(self):
        add_worktree(self.repo, "w1")
        r = self.run_cli("classify", str(self.repo), "--offline")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["w1\tsafe\tmerged"])

    def test_json_output(self):
        add_worktree(self.repo, "w1")
        r = self.run_cli("classify", str(self.repo), "--offline", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["items"][0]["name"], "w1")
        self.assertEqual(r.stdout.strip(), json.dumps(data))

    def test_not_a_repo_exits_2(self):
        r = self.run_cli("classify", self.tmp, "--offline")
        self.assertEqual(r.returncode, 2)

    def test_runs_through_symlink(self):
        link = Path(self.tmp) / "link-aw"
        link.symlink_to(CLI)
        add_worktree(self.repo, "w1")
        r = subprocess.run([sys.executable, str(link), "classify", str(self.repo), "--offline"],
                           capture_output=True, text=True, env={**os.environ, "AW_TMUX": self.tmux})
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
