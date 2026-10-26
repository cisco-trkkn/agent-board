"""Safety engine for agent worktrees (.claude/worktrees/*): says which are safe to remove.

classify() reads state and changes nothing. It fails closed: a check that cannot run makes that
worktree `kept` with the reason.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paneclass import tmux_cmd  # noqa: E402

TIMEOUT = 20          # seconds, for every subprocess
STALE_DAYS = 7        # unmerged and clean, last commit this old: stale
AGENT_DIR = "/.claude/worktrees/"
STATES = ("safe", "stale", "in_use", "dirty", "kept")


class NotARepo(Exception):
    pass


# ---- Claude session locks (moved from server.py) ----

CLAUDE_LOCK = re.compile(r"^claude \S+ .+ \(pid (\d+)( start .+)?\)$")


def claude_lock_owner(reason):
    m = CLAUDE_LOCK.match(reason or "")
    return int(m.group(1)) if m else None


def proc_args(pid):
    r = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, timeout=TIMEOUT)
    return r.stdout.strip()


def lock_is_stale(pid, proc_args_fn=None):
    """True when the lock's pid is dead, or alive but not Claude (the pid was reused).
    proc_args_fn lets a caller supply its own `ps` reader; default is this module's proc_args."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass   # alive, owned by someone else
    return "claude" not in (proc_args_fn or proc_args)(pid).lower()


# ---- helpers ----

def _run(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, env=env)


def _git(cwd, *args):
    return _run(["git", *args], cwd)


def _parse_worktrees(text):
    blocks, cur = [], {}
    for line in text.splitlines() + [""]:
        if line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch refs/heads/"):
            cur["branch"] = line[18:]
        elif line.startswith("locked"):
            cur["locked"] = line[7:] or "locked"
        elif not line and cur:
            blocks.append(cur)
            cur = {}
    return blocks


def _is_ancestor(repo, sha, ref):
    return _git(repo, "merge-base", "--is-ancestor", sha, ref).returncode == 0


def _ref_exists(repo, ref):
    return _git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}").returncode == 0


def _panes(servers_env=None):
    """(paths, error): the cwd of every tmux pane on every server, or the reason we could not read them."""
    one = os.environ.get("AW_TMUX")
    servers = [[one]] if one else [list(tmux_cmd()), ["tmux"]]
    paths = []
    for cmd in servers:
        try:
            r = subprocess.run([*cmd, "list-panes", "-a", "-F", "#{pane_pid}\t#{pane_current_path}"],
                               capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return paths, "can't check tmux panes: timed out"
        except OSError as e:
            return paths, f"can't check tmux panes: {e}"
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip()
            if "no server running" in msg:
                continue
            return paths, f"can't check tmux panes: {msg or 'exit %d' % r.returncode}"
        for line in r.stdout.splitlines():
            if "\t" in line:
                paths.append(line.split("\t", 1)[1])
    return paths, None


def _inside(pane, wt):
    wts = {wt, os.path.realpath(wt)}
    panes = {pane, os.path.realpath(pane)}
    return any(p == w or p.startswith(w + "/") for p in panes for w in wts)


def _squash_mr(repo, branch, sha):
    """(mr iid or None, error). Is there a merged MR from `branch` whose head sha equals `sha`?"""
    glab = os.environ.get("AW_GLAB") or "glab"
    try:
        r = _run([glab, "mr", "list", "--merged", "--source-branch", branch, "--output", "json"], repo)
    except subprocess.TimeoutExpired:
        return None, "can't verify MR: glab timed out"
    except OSError as e:
        return None, f"can't verify MR: {e}"
    if r.returncode != 0:
        return None, f"can't verify MR: glab exited {r.returncode}: {(r.stderr or '').strip()[:120]}"
    try:
        mrs = json.loads(r.stdout or "[]")
    except ValueError:
        return None, "can't verify MR: unreadable glab output"
    for mr in mrs if isinstance(mrs, list) else []:
        if isinstance(mr, dict) and mr.get("sha") == sha:
            return mr.get("iid"), None
    return None, None


class _Ctx:
    """Per-classify state shared by the items."""

    def __init__(self, repo, base, current, fetch, fetch_err, now):
        self.repo, self.base, self.current = repo, base, current
        self.fetch, self.fetch_err, self.now = fetch, fetch_err, now
        self.refs = [r for r in (base, "origin/" + base, current) if r and _ref_exists(repo, r)]
        self._panes = None

    def panes(self):
        if self._panes is None:
            self._panes = _panes()
        return self._panes


def _classify_one(ctx, wt):
    path, sha, branch = wt["path"], wt.get("head", ""), wt.get("branch")
    ct = _git(path, "log", "-1", "--format=%ct").stdout.strip()
    age = max(0, int((ctx.now - datetime.fromtimestamp(int(ct), timezone.utc)).total_seconds() // 86400)) if ct else None
    out = {"path": path, "name": Path(path).name, "branch": branch, "head": sha,
           "state": "kept", "reason": "", "age_days": age, "squash": False}

    def done(state, reason):
        out["state"], out["reason"] = state, reason
        return out

    st = _git(path, "status", "--porcelain")
    if st.returncode != 0:
        return done("kept", f"can't read status: {st.stderr.strip()[:120]}")
    if st.stdout.strip():
        return done("dirty", "uncommitted or untracked files")

    lock = wt.get("locked")
    if lock:
        pid = claude_lock_owner(lock)
        if pid is None:
            return done("kept", f"locked: {lock}")
        if not lock_is_stale(pid):
            return done("in_use", f"live Claude session (pid {pid})")
    panes, err = ctx.panes()
    if any(_inside(p, path) for p in panes):
        return done("in_use", "tmux pane inside")
    if err:
        return done("kept", err)

    if any(_is_ancestor(ctx.repo, sha, r) for r in ctx.refs):
        return done("safe", "merged")

    if branch:
        track = _git(ctx.repo, "for-each-ref", "--format=%(upstream:track)", f"refs/heads/{branch}").stdout.strip()
        if track == "[gone]":
            if not ctx.fetch:
                return done("kept", "offline: upstream gone, can't verify squash merge")
            if ctx.fetch_err:
                return done("kept", f"can't verify MR: {ctx.fetch_err}")
            iid, merr = _squash_mr(ctx.repo, branch, sha)
            if merr:
                return done("kept", merr)
            if iid is not None:
                out["squash"] = True
                return done("safe", f"squash-merged (MR !{iid})")
            return done("kept", "upstream gone, no merged MR at this commit")

    if age is not None and age >= STALE_DAYS:
        return done("stale", f"not merged, last commit {age}d ago")
    return done("kept", "not merged")


def classify(repo, fetch=True, now=None):
    """State of each agent worktree of the repo containing `repo`. Never changes anything but remote-tracking refs."""
    now = now or datetime.now(timezone.utc)
    try:
        r = _git(repo, "worktree", "list", "--porcelain")
    except (OSError, subprocess.TimeoutExpired) as e:
        raise NotARepo(f"{repo}: {e}")
    if r.returncode != 0:
        raise NotARepo((r.stderr or r.stdout).strip() or str(repo))
    blocks = _parse_worktrees(r.stdout)
    if not blocks:
        raise NotARepo(str(repo))
    main = blocks[0]["path"]
    fetch_err = None
    if fetch and _git(main, "remote").stdout.strip():
        try:
            f = _git(main, "fetch", "--prune")
            if f.returncode != 0:
                fetch_err = f"fetch failed: {(f.stderr or '').strip()[:120]}"
        except subprocess.TimeoutExpired:
            fetch_err = "fetch timed out"
    current = _git(main, "branch", "--show-current").stdout.strip()
    base = _git(main, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").stdout.strip()
    base = base[len("origin/"):] if base.startswith("origin/") else (base or "main")
    ctx = _Ctx(main, base, current, fetch, fetch_err, now)
    items = []
    for wt in blocks[1:]:
        if AGENT_DIR not in wt["path"]:
            continue
        try:
            items.append(_classify_one(ctx, wt))
        except subprocess.TimeoutExpired as e:
            items.append({"path": wt["path"], "name": Path(wt["path"]).name, "branch": wt.get("branch"),
                          "head": wt.get("head", ""), "state": "kept", "age_days": None, "squash": False,
                          "reason": f"timed out: {' '.join(map(str, e.cmd))[:80]}"})
    return {"repo": main, "base": base, "current": current, "items": items}
