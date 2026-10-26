import json
import os
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
        own = tmux_stub(self.bin / "own", [(1, str(wt))])
        plain = tmux_stub(self.bin / "tmux", [])
        env = {k: v for k, v in os.environ.items() if k != "AW_TMUX"}
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(ws, "tmux_cmd", return_value=[own]):
            self.assertEqual(self.one()["state"], "in_use")
        self.assertTrue(plain)

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


if __name__ == "__main__":
    unittest.main()
