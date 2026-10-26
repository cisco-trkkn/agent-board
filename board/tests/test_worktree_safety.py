import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import worktree_safety as ws  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
CLI = ROOT / "bin" / "agent-worktrees"
WITH_START = "claude session {n} (pid {pid} start Fri Oct 16 19:12:53 2026)"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


def git(*args, cwd, date=None, check=True):
    env = {**os.environ, **GIT_ENV}
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date.isoformat()
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True, env=env)


def make_repo(tmp):
    """A repo with one commit on main. Returns its resolved path."""
    repo = Path(tmp).resolve() / "repo"
    repo.mkdir()
    git("init", "-b", "main", cwd=repo)
    git("commit", "--allow-empty", "-m", "init", cwd=repo)
    return repo


def add_worktree(repo, name, commits=0, age_days=0, now=NOW):
    """Add .claude/worktrees/<name> on branch <name>, with `commits` empty commits dated now - age_days."""
    wt = repo / ".claude" / "worktrees" / name
    git("worktree", "add", str(wt), "-b", name, cwd=repo)
    for i in range(commits):
        git("commit", "--allow-empty", "-m", f"{name} {i}", cwd=wt, date=now - timedelta(days=age_days))
    return wt


def head(wt):
    return git("rev-parse", "HEAD", cwd=wt).stdout.strip()


def write_stub(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)


def glab_stub(path, sha, marker=None, exit_code=0):
    mark = f'echo called >> "{marker}"\n' if marker else ""
    if exit_code:
        return write_stub(path, mark + "echo boom >&2\nexit %d\n" % exit_code)
    return write_stub(path, mark + "echo '[{\"iid\":1,\"sha\":\"%s\",\"state\":\"merged\"}]'\n" % sha)


def tmux_stub(path, lines=(), fail=None):
    if fail:
        return write_stub(path, f'echo "{fail}" >&2\nexit 1\n')
    return write_stub(path, "".join(f"printf '%s\\t%s\\n' {pid} '{p}'\n" for pid, p in lines))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = make_repo(self.tmp)
        self.bin = Path(self.tmp) / "stubs"
        self.bin.mkdir()
        self.procs = []
        self.tmux = tmux_stub(self.bin / "tmux")   # no panes, by default
        self.env = {"AW_TMUX": self.tmux}
        p = mock.patch.dict(os.environ, self.env)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_env(self, **kw):
        p = mock.patch.dict(os.environ, kw)
        p.start()
        self.addCleanup(p.stop)

    def sleeper(self):
        p = subprocess.Popen(["sleep", "30"])
        self.procs.append(p)
        return p.pid

    def dead_pid(self):
        p = subprocess.Popen(["true"])
        p.wait()
        return p.pid

    def lock(self, wt, reason):
        git("worktree", "lock", "--reason", reason, str(wt), cwd=self.repo)

    def one(self, fetch=False, name=None):
        res = ws.classify(str(self.repo), fetch=fetch, now=NOW)
        items = [i for i in res["items"] if name in (None, i["name"])]
        self.assertEqual(len(items), 1, res)
        return items[0]


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


class Squash(Base):
    """Upstream gone + a merged MR whose sha is the worktree HEAD."""

    def setUp(self):
        super().setUp()
        self.origin = Path(self.tmp) / "origin.git"
        git("init", "--bare", "-b", "main", str(self.origin), cwd=self.tmp)
        git("remote", "add", "origin", str(self.origin), cwd=self.repo)
        git("push", "-u", "origin", "main", cwd=self.repo)
        self.wt = add_worktree(self.repo, "w1", commits=1, age_days=1)
        git("push", "-u", "origin", "w1", cwd=self.wt)
        git("push", "origin", "--delete", "w1", cwd=self.repo)
        git("fetch", "--prune", cwd=self.repo)
        self.marker = Path(self.tmp) / "glab-called"

    def test_gone_upstream_is_really_gone(self):
        out = git("for-each-ref", "--format=%(upstream:track)", "refs/heads/w1", cwd=self.repo).stdout
        self.assertEqual(out.strip(), "[gone]")

    def test_equal_sha_is_safe_squash(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", head(self.wt)))
        item = self.one(fetch=True)
        self.assertEqual((item["state"], item["squash"]), ("safe", True))

    def test_aw_glab_is_word_split(self):
        sha = head(self.wt)
        stub = write_stub(self.bin / "glabargs", '[ "$1" = "--flag" ] || exit 1\nshift\n'
                          'echo \'[{"iid":1,"sha":"%s","state":"merged"}]\'\n' % sha)
        self.set_env(AW_GLAB=f"{stub} --flag")
        self.assertEqual(self.one(fetch=True)["squash"], True)

    def test_other_sha_is_kept(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", "0" * 40))
        item = self.one(fetch=True)
        self.assertEqual(item["state"], "kept")
        self.assertFalse(item["squash"])

    def test_glab_failure_is_kept_cant_verify(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", "x", exit_code=1))
        item = self.one(fetch=True)
        self.assertEqual(item["state"], "kept")
        self.assertIn("can't verify MR", item["reason"])

    def test_glab_missing_is_kept_cant_verify(self):
        self.set_env(AW_GLAB=str(self.bin / "nope"))
        item = self.one(fetch=True)
        self.assertEqual(item["state"], "kept")
        self.assertIn("can't verify MR", item["reason"])

    def test_offline_never_calls_glab_or_fetch(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", head(self.wt), marker=self.marker))
        real = subprocess.run
        calls = []

        def spy(cmd, *a, **k):
            calls.append(list(cmd))
            return real(cmd, *a, **k)
        with mock.patch.object(ws.subprocess, "run", spy):
            item = self.one(fetch=False)
        self.assertEqual(item["state"], "kept")
        self.assertIn("offline", item["reason"])
        self.assertFalse(self.marker.exists())
        self.assertFalse([c for c in calls if "fetch" in c])

    def test_fetch_true_fetches(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", head(self.wt)))
        real = subprocess.run
        calls = []

        def spy(cmd, *a, **k):
            calls.append(list(cmd))
            return real(cmd, *a, **k)
        with mock.patch.object(ws.subprocess, "run", spy):
            self.one(fetch=True)
        self.assertTrue([c for c in calls if c[:2] == ["git", "fetch"]])


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


class StateBase(Base):
    def setUp(self):
        super().setUp()
        self.state = Path(self.tmp) / "state"
        self.set_env(AW_STATE_DIR=str(self.state))

    def log_lines(self):
        f = self.state / "worktree-sweep.log"
        return f.read_text().splitlines() if f.exists() else []

    def listed(self, name):
        return name in git("worktree", "list", cwd=self.repo).stdout

    def branches(self):
        return git("branch", "--format=%(refname:short)", cwd=self.repo).stdout.split()


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
        self.assertTrue([a for a in seen if a[:2] == ("worktree", "prune")])


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

    def test_recent_file_falls_back_to_darwin_user_temp_dir(self):
        add_worktree(self.repo, "m1")
        tmpdir = Path(self.tmp) / "dt"
        (tmpdir / f"tmux-ctl-{os.getuid()}").mkdir(parents=True)
        (tmpdir / f"tmux-ctl-{os.getuid()}" / "recent-projects.json").write_text(json.dumps([str(self.repo)]))
        self._no_state_dir_env()
        with mock.patch.object(os, "confstr", return_value=str(tmpdir) + "/") as cs:
            self.assertEqual(ws.sweep_recent(), ["removed m1"])
        cs.assert_called_with("CS_DARWIN_USER_TEMP_DIR")

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


# Captured from `launchctl print gui/$UID/com.apple.Finder` (macOS 26.0, 2026-10-26): top-level keys have one
# leading tab, nested blocks two or more; nested blocks also carry `state = active`.
LAUNCHCTL_PRINT = ("gui/503/com.apple.Finder = {\n\tactive count = 5\n\tstate = running\n\n\tprogram = /System/x\n"
                   "\tpid = 5388\n\tlast exit code = (never exited)\n\n\tevent triggers = {\n"
                   "\t\tcom.apple.x => {\n\t\t\tstate = active\n\t\t}\n\t}\n}\n")


class Schedule(Base):
    def setUp(self):
        super().setUp()
        self.home = Path(self.tmp) / "home"
        self.home.mkdir()
        self.calls = Path(self.tmp) / "launchctl-calls"
        self.stub = write_stub(self.bin / "launchctl", f'echo "$@" >> "{self.calls}"\n'
                               f'case "$1" in print) [ -f "{self.tmp}/loaded" ] && {{ printf "%b" \'{LAUNCHCTL_PRINT.replace(chr(10), "\\n").replace(chr(9), "\\t")}\'; exit 0; }}; echo "Could not find service" >&2; exit 113;; '
                               f'bootout) exit 3;; bootstrap) touch "{self.tmp}/loaded"; exit 0;; esac\n')
        self.set_env(AW_LAUNCHCTL=self.stub, AW_HOME=str(self.home))
        self.plist = self.home / "Library" / "LaunchAgents" / "com.user.agent-worktree-sweep.plist"

    def called(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_plist_fields(self):
        cli = str(self.home / ".local" / "bin" / "agent-board")
        d = plistlib.loads(ws.plist_text(cli, str(self.home)))
        self.assertEqual(d["Label"], "com.user.agent-worktree-sweep")
        self.assertEqual(d["ProgramArguments"], [cli, "worktrees", "sweep", "--recent"])
        self.assertEqual(d["StartCalendarInterval"], {"Hour": 4, "Minute": 0})
        log = str(self.home / ".local" / "state" / "agent-board" / "worktree-sweep.launchd.log")
        self.assertEqual((d["StandardOutPath"], d["StandardErrorPath"]), (log, log))
        path = d["EnvironmentVariables"]["PATH"]
        self.assertIn(f"{self.home}/.local/bin:/opt/homebrew/bin:/usr/bin:/bin", path)

    @unittest.skipUnless(shutil.which("plutil"), "plutil is macOS only")
    def test_plist_passes_plutil_lint(self):
        f = Path(self.tmp) / "x.plist"
        f.write_bytes(ws.plist_text(str(self.home / ".local/bin/agent-board"), str(self.home)))
        r = subprocess.run(["plutil", "-lint", str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_install_writes_plist_and_runs_bootout_then_bootstrap(self):
        lines = ws.schedule_install()
        d = plistlib.loads(self.plist.read_bytes())
        self.assertEqual(d["ProgramArguments"][0], str(self.home / ".local" / "bin" / "agent-board"))
        uid = os.getuid()
        self.assertEqual(self.called(), [f"bootout gui/{uid}/com.user.agent-worktree-sweep",
                                         f"bootstrap gui/{uid} {self.plist}"])
        self.assertTrue((self.home / ".local" / "state" / "agent-board").is_dir())
        self.assertTrue(lines)

    def test_install_backs_up_an_existing_plist(self):
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text("old")
        ws.schedule_install()
        baks = list(self.plist.parent.glob(self.plist.name + ".bak-*"))
        self.assertEqual(len(baks), 1)
        self.assertRegex(baks[0].name, r"\.bak-\d{8}$")
        self.assertEqual(baks[0].read_text(), "old")
        self.assertNotEqual(self.plist.read_text(), "old")

    def test_install_bootstrap_failure_raises(self):
        write_stub(self.bin / "launchctl", 'case "$1" in bootstrap) echo "Bootstrap failed: 5" >&2; exit 5;; esac\n')
        with self.assertRaisesRegex(RuntimeError, "Bootstrap failed"):
            ws.schedule_install()

    def test_uninstall_boots_out_and_removes_the_file(self):
        ws.schedule_install()
        self.calls.unlink()
        ws.schedule_uninstall()
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.called(), [f"bootout gui/{os.getuid()}/com.user.agent-worktree-sweep"])

    def test_uninstall_when_not_installed_is_fine(self):
        self.assertTrue(ws.schedule_uninstall())

    def test_status_not_installed(self):
        self.assertEqual(ws.schedule_status(), ["not installed"])

    def test_status_prints_only_the_service_state_and_exit_code(self):
        ws.schedule_install()
        self.assertEqual(ws.schedule_status(), ["state = running", "last exit code = (never exited)"])

    def test_launchctl_is_word_split(self):
        stub = write_stub(self.bin / "lcargs", '[ "$1" = "--flag" ] || exit 9\nexit 0\n')
        self.set_env(AW_LAUNCHCTL=f"{stub} --flag")
        with mock.patch.object(ws.subprocess, "run", wraps=subprocess.run) as run:
            ws.schedule_install()
        self.assertTrue(all(c.args[0][1] == "--flag" for c in run.call_args_list if c.args[0][0] == stub))

    def test_cli_schedule_install_status_uninstall(self):
        env = {**os.environ, "AW_LAUNCHCTL": self.stub, "AW_HOME": str(self.home)}
        run = lambda *a: subprocess.run([sys.executable, str(CLI), "schedule", *a], capture_output=True, text=True, env=env)
        r = run("install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.plist.exists())
        self.assertIn("state = running", run("status").stdout)
        self.assertEqual(run("uninstall").returncode, 0)
        self.assertFalse(self.plist.exists())


if __name__ == "__main__":
    unittest.main()
