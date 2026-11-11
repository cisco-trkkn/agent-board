"""Fixtures shared by test_worktree_safety_*.py and test_worktree_board.py: scratch repos, worktrees, stubs, Base."""
import atexit
import os
import re
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


_TEMPLATE = {}


def _template_repo():
    """One `git init` + initial commit per process; make_repo copies it. The repo has no worktrees yet, so it holds no
    absolute paths and a copy is independent of the template and of every other copy."""
    if "dir" not in _TEMPLATE:
        d = tempfile.mkdtemp(prefix="wt-template-")
        atexit.register(shutil.rmtree, d, ignore_errors=True)
        repo = Path(d).resolve() / "repo"
        repo.mkdir()
        git("init", "-b", "main", cwd=repo)
        git("commit", "--allow-empty", "-m", "init", cwd=repo)
        _TEMPLATE["dir"] = repo
    return _TEMPLATE["dir"]


def make_repo(tmp):
    """A repo with one commit on main (a copy of the process-wide template). Returns its resolved path."""
    repo = Path(tmp).resolve() / "repo"
    shutil.copytree(_template_repo(), repo, symlinks=True)
    return repo


def add_worktree(repo, name, commits=0, age_days=0, now=NOW, created_hours_ago=None):
    """Add .claude/worktrees/<name> on branch <name>, with `commits` empty commits dated now - age_days.
    The branch's creation (its first reflog entry) is dated `created_hours_ago` before `now`, default 2 days, so a
    fixture is past the "brand new" grace period unless a test asks for a young one."""
    wt = repo / ".claude" / "worktrees" / name
    created = now - (timedelta(hours=created_hours_ago) if created_hours_ago is not None else timedelta(days=2))
    git("worktree", "add", str(wt), "-b", name, cwd=repo)
    # a reflog entry is stamped with the wall clock whatever GIT_COMMITTER_DATE says, so back-date it in the file
    log = repo / ".git" / "logs" / "refs" / "heads" / name
    log.write_text(re.sub(r"> \d+ ", f"> {int(created.timestamp())} ", log.read_text(), count=1))
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


class StateBase(Base):
    def setUp(self):
        super().setUp()
        self.state = Path(self.tmp) / "state"
        self.set_env(AW_STATE_DIR=str(self.state))

    def log_lines(self):
        f = self.state / "worktree-sweep.log"
        return f.read_text().splitlines() if f.exists() else []

    def listed(self, name):
        # match worktree dir names, not the whole output: a random temp dir in the repo path can contain `name`
        out = git("worktree", "list", "--porcelain", cwd=self.repo).stdout
        return name in {Path(l[len("worktree "):]).name for l in out.splitlines() if l.startswith("worktree ")}

    def branches(self):
        return git("branch", "--format=%(refname:short)", cwd=self.repo).stdout.split()
