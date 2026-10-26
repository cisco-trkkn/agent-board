"""Safety engine for agent worktrees (.claude/worktrees/*): says which are safe to remove.

classify() reads state and changes nothing. It fails closed: a check that cannot run makes that
worktree `kept` with the reason.
"""
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_env  # noqa: E402
from paneclass import tmux_cmd  # noqa: E402

TIMEOUT = 20          # seconds, for every subprocess
STALE_DAYS = 7        # unmerged and clean, last commit this old: stale
AGENT_DIR = "/.claude/worktrees/"
DARWIN_USER_TEMP_DIR = 65537   # _CS_DARWIN_USER_TEMP_DIR in <unistd.h>
STATES = ("safe", "stale", "in_use", "dirty", "kept")


class NotARepo(Exception):
    pass


class StateError(Exception):
    """The engine's own state (recent-projects list) is unreadable."""


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


def _servers():
    """tmux commands to query: AW_TMUX (one server, word-split) or agent-board's own server plus the default one."""
    one = os.environ.get("AW_TMUX")
    return [shlex.split(one)] if one else [list(tmux_cmd()), ["tmux"]]


def _panes(servers_env=None):
    """(paths, error): the cwd of every tmux pane on every server, or the reason we could not read them."""
    servers = _servers()
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
            # no server yet: "no server running on …", or "error connecting to … (No such file or directory)"
            if "no server running" in msg or (msg.startswith("error connecting to") and msg.endswith("(No such file or directory)")):
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
    glab = shlex.split(os.environ.get("AW_GLAB") or "glab")
    try:
        r = _run([*glab, "mr", "list", "--merged", "--source-branch", branch, "--output", "json"], repo)
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


def _worktrees(repo):
    """(main checkout path, all worktree blocks) of the repo containing `repo`. Raises NotARepo."""
    try:
        r = _git(repo, "worktree", "list", "--porcelain")
    except (OSError, subprocess.TimeoutExpired) as e:
        raise NotARepo(f"{repo}: {e}")
    if r.returncode != 0:
        raise NotARepo((r.stderr or r.stdout).strip() or str(repo))
    blocks = _parse_worktrees(r.stdout)
    if not blocks:
        raise NotARepo(str(repo))
    return blocks[0]["path"], blocks


def _agent_root(main):
    return os.path.realpath(main) + AGENT_DIR


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


def classify(repo, fetch=True, now=None, only=None, skip_fetch=False):
    """State of each agent worktree of the repo containing `repo`. Never changes anything but remote-tracking refs.
    only: classify just the worktree at that path. skip_fetch: online (glab allowed) but no `git fetch` (a re-check)."""
    now = now or datetime.now(timezone.utc)
    main, blocks = _worktrees(repo)
    fetch_err = None
    if fetch and not skip_fetch and _git(main, "remote").stdout.strip():
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
    agent_root = _agent_root(main)
    want = os.path.realpath(only) if only else None
    items = []
    for wt in blocks[1:]:
        if not wt["path"].startswith(agent_root):
            continue
        if want and os.path.realpath(wt["path"]) != want:
            continue
        try:
            items.append(_classify_one(ctx, wt))
        except subprocess.TimeoutExpired as e:
            items.append({"path": wt["path"], "name": Path(wt["path"]).name, "branch": wt.get("branch"),
                          "head": wt.get("head", ""), "state": "kept", "age_days": None, "squash": False,
                          "reason": f"timed out: {' '.join(map(str, e.cmd))[:80]}"})
    return {"repo": main, "base": base, "current": current, "items": items}


# ---- remove ----

def remove(repo, path, force_branch=False, proc_args_fn=None):
    """Remove one agent worktree the user (or a sweep) chose. Needs only: under .claude/worktrees/, clean, no live
    Claude lock. A stale lock is lifted and put back if git refuses. Never `--force`. Returns the message the board shows;
    raises RuntimeError on refusal (and NotARepo). force_branch: `branch -D` instead of `-d` (verified squash only).
    proc_args_fn: the `ps` reader for the lock check (the board passes its own so its tests can patch it)."""
    main, blocks = _worktrees(repo)
    want = os.path.realpath(path)
    wt = next((b for b in blocks[1:] if os.path.realpath(b["path"]) == want and b["path"].startswith(_agent_root(main))), None)
    if wt is None:
        raise RuntimeError(f"not an agent worktree under .claude/worktrees/: {path}")
    wpath, reason, branch, name, note = wt["path"], wt.get("locked"), wt.get("branch"), Path(wt["path"]).name, ""
    st = _git(wpath, "status", "--porcelain")
    if st.returncode != 0:
        raise RuntimeError(f"can't read status of {name}: {st.stderr.strip()[:120]}")
    if st.stdout.strip():
        raise RuntimeError(f"{name} has uncommitted or untracked files")
    if reason:
        pid = claude_lock_owner(reason)
        if pid is None:
            raise RuntimeError(f"locked by something other than Claude ({reason}); unlock it yourself")
        if not lock_is_stale(pid, proc_args_fn):
            raise RuntimeError(f"in use by a running Claude session (pid {pid})")
        _git(main, "worktree", "unlock", wpath)
        note = f"unlocked stale lock (pid {pid}); "
    r = _git(main, "worktree", "remove", wpath)
    if r.returncode != 0:
        if reason:
            _git(main, "worktree", "lock", "--reason", reason, wpath)
        raise RuntimeError((r.stderr or r.stdout).strip() or "git refused (uncommitted changes?)")
    msg = f"{note}removed worktree {name}"
    if branch:
        d = _git(main, "branch", "-D" if force_branch else "-d", branch)
        msg += f"; deleted branch {branch}" if d.returncode == 0 else f"; kept branch {branch} (not merged)"
    _git(main, "worktree", "prune")
    return msg


# ---- sweep ----

def state_dir():
    return Path(os.environ.get("AW_STATE_DIR") or Path.home() / ".local" / "state" / "agent-board")


def recent_dir():
    """Where board/dirs.py keeps recent-projects.json: AW_STATE_DIR (test seam), else tc_env.state_dir()
    ($TC_STATE, else ${TMPDIR}/tmux-ctl-<uid>). Without TMPDIR (launchd), the per-user temp dir stands in for it."""
    if os.environ.get("AW_STATE_DIR"):
        return Path(os.environ["AW_STATE_DIR"])
    if not (os.environ.get("TC_STATE") or os.environ.get("TMPDIR")):
        try:   # _CS_DARWIN_USER_TEMP_DIR: Python lists no name for it, but os.confstr takes the number
            user_tmp = os.confstr(DARWIN_USER_TEMP_DIR) if sys.platform == "darwin" else ""
        except (AttributeError, ValueError, OSError):
            user_tmp = ""
        if user_tmp:
            return Path(f"{user_tmp.rstrip('/')}/tmux-ctl-{os.getuid()}")
    return tc_env.state_dir()


def sweep_lockdir(repo):
    return state_dir() / ("sweep-" + hashlib.sha1(os.path.realpath(repo).encode()).hexdigest()[:12] + ".lock")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _take_lock(lockdir):
    """True when this process now holds the lockdir. A lockdir whose pid is dead is taken over."""
    lockdir.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            os.mkdir(lockdir)
        except FileExistsError:
            try:
                pid = int((lockdir / "pid").read_text().strip())
            except (OSError, ValueError):
                try:   # no pid yet: its owner may be between mkdir and write
                    if time.time() - lockdir.stat().st_mtime < 30:
                        return False
                except OSError:
                    continue
                pid = None
            if pid is not None and _pid_alive(pid):
                return False
            shutil.rmtree(lockdir, ignore_errors=True)
            continue
        (lockdir / "pid").write_text(str(os.getpid()))
        return True
    return False


def _log(main, action, name, reason=""):
    """Append `<ISO time>\t<repo>\t<action>\t<name>\t<reason>` to the sweep log. A failure only warns."""
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        clean = lambda t: str(t).replace("\t", " ").replace("\n", " ")
        with open(state_dir() / "worktree-sweep.log", "a") as f:
            f.write("\t".join([stamp, main, action, clean(name), clean(reason)]) + "\n")
    except OSError as e:
        print(f"agent-worktrees: can't write the sweep log: {e}", file=sys.stderr)


def sweep(repo, only=None, dry_run=False, now=None):
    """Remove the safe agent worktrees of the repo. Returns report lines (also appended to the sweep log):
    `removed X` / `would-remove X` / `kept X (reason)` / `stale X (Nd)`. Each removal re-checks that one worktree first."""
    main, _ = _worktrees(repo)
    lockdir = sweep_lockdir(main)
    if not _take_lock(lockdir):
        return ["sweep already running"]
    try:
        lines = []

        def note(action, name, reason="", shown=None):
            lines.append(shown or f"{action} {name}")
            _log(main, action, name, reason)

        for item in classify(main, fetch=True, now=now, only=only)["items"]:
            name, state = item["name"], item["state"]
            if state == "safe":
                if dry_run:
                    note("would-remove", name)
                    continue
                again = classify(main, fetch=True, now=now, only=item["path"], skip_fetch=True)["items"]
                cur = again[0] if again else None
                if cur is None or cur["state"] != "safe":
                    why = f"{cur['reason'] if cur else 'gone'}; changed since the first check"
                    note("kept", name, why, f"kept {name} ({why})")
                    continue
                try:
                    remove(main, cur["path"], force_branch=cur["squash"])
                    note("removed", name)
                except RuntimeError as e:
                    note("kept", name, str(e), f"kept {name} ({e})")
            elif state == "stale":
                note("stale", name, f"{item['age_days']}d", f"stale {name} ({item['age_days']}d)")
            else:
                note("kept", name, item["reason"], f"kept {name} ({item['reason']})")
        return lines
    finally:
        shutil.rmtree(lockdir, ignore_errors=True)


def _recent_paths():
    f = recent_dir() / "recent-projects.json"
    try:
        text = f.read_text()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise StateError(f"{f}: {e}")
    try:
        v = json.loads(text)
    except ValueError as e:
        raise StateError(f"{f}: {e}")
    if not isinstance(v, list):
        raise StateError(f"{f}: not a list")
    return [p for p in v if isinstance(p, str)]


def _session_paths():
    out = []
    for cmd in _servers():
        try:
            r = subprocess.run([*cmd, "list-sessions", "-F", "#{session_path}"], capture_output=True, text=True,
                               timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            out += [l for l in r.stdout.splitlines() if l.strip()]
    return out


def sweep_recent(dry_run=False, now=None):
    """Sweep every repo in recent-projects.json and the open tmux sessions' paths, each once."""
    lines, seen_repos, seen_paths = [], set(), set()
    for path in _recent_paths() + _session_paths():
        if path in seen_paths:
            continue
        seen_paths.add(path)
        try:
            main, _ = _worktrees(path)
        except NotARepo:
            lines.append(f"skip {path} (not a repo)")
            continue
        key = os.path.realpath(main)
        if key in seen_repos:
            continue
        seen_repos.add(key)
        lines += sweep(main, dry_run=dry_run, now=now)
    return lines


# ---- daily schedule (launchd) ----

LABEL = "com.user.agent-worktree-sweep"


def _home():
    return Path(os.environ.get("AW_HOME") or Path.home())


def _plist_path(home=None):
    return Path(home or _home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_text(cli_path, home):
    """The LaunchAgent plist (bytes) that runs `<cli_path> worktrees sweep --recent` every day at 04:00."""
    log = f"{home}/.local/state/agent-board/worktree-sweep.launchd.log"
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(cli_path), "worktrees", "sweep", "--recent"],
        "StartCalendarInterval": {"Hour": 4, "Minute": 0},
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": {"PATH": f"{home}/.local/bin:/opt/homebrew/bin:/usr/bin:/bin"},
    })


def _launchctl(*args):
    cmd = shlex.split(os.environ.get("AW_LAUNCHCTL") or "launchctl")
    try:
        return subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 127, "", str(e))


def _executable(path):
    return path.is_file() and os.access(path, os.X_OK)


def agent_board_candidates(home=None):
    """Where the scheduled job's `agent-board` may live, best first: the user's ~/.local/bin link, then the one
    beside this CLI (AW_BIN_DIR is the test seam for that directory)."""
    beside = Path(os.environ.get("AW_BIN_DIR") or Path(os.path.realpath(__file__)).parent.parent / "bin")
    return [Path(home or _home()) / ".local" / "bin" / "agent-board", beside / "agent-board"]


def agent_board_path(home=None):
    """The first executable candidate, or raises RuntimeError naming every path checked."""
    cands = agent_board_candidates(home)
    for c in cands:
        if _executable(c):
            return c
    raise RuntimeError("no executable agent-board to schedule; checked " + ", ".join(str(c) for c in cands))


def schedule_install():
    home = _home()
    target = agent_board_path(home)   # before anything is written
    plist = _plist_path(home)
    plist.parent.mkdir(parents=True, exist_ok=True)
    (home / ".local" / "state" / "agent-board").mkdir(parents=True, exist_ok=True)
    lines = []
    if plist.exists():
        bak = plist.with_name(f"{plist.name}.bak-{datetime.now():%Y%m%d}")
        shutil.copy2(plist, bak)
        lines.append(f"backed up the old plist to {bak}")
    plist.write_bytes(plist_text(target, str(home)))
    uid = os.getuid()
    _launchctl("bootout", f"gui/{uid}/{LABEL}")   # not loaded yet is fine
    r = _launchctl("bootstrap", f"gui/{uid}", str(plist))
    if r.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {(r.stderr or r.stdout).strip()}")
    return lines + [f"installed {plist}: sweep --recent every day at 04:00"]


def schedule_uninstall():
    plist = _plist_path()
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if plist.exists():
        plist.unlink()
        return [f"removed {plist}"]
    return ["not installed"]


def schedule_status():
    r = _launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    if r.returncode != 0:
        return ["not installed"]
    # the service's own keys sit one tab deep; nested blocks (event triggers, endpoints) are deeper
    keep = [l.strip() for l in r.stdout.splitlines()
            if re.match(r"^\t(state|last exit code) = ", l)]
    keep = keep or ["installed"]
    try:
        target = Path(plistlib.loads(_plist_path().read_bytes())["ProgramArguments"][0])
    except (OSError, ValueError, KeyError, IndexError):
        return keep
    return keep + ([] if _executable(target) else [f"target missing: {target}"])
