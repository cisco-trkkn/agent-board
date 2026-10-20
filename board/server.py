#!/usr/bin/env python3
"""tmux-dash: a localhost dashboard for tmux sessions, Claude agent teams and worker agents.

Serves one HTML page plus a small JSON API on 127.0.0.1. Live terminals are served by a
separate ttyd instance (see tmux-dash launcher); this server only tells the page where it is.

Security: binds 127.0.0.1 only; every request must carry the secret token in its path;
the Host header must be 127.0.0.1/localhost (blocks DNS rebinding); state-changing calls
need the token in an X-Dash-Token header too (blocks cross-site form posts).
Actions go through the same tested scripts as the tmux shortcuts (tmux-ctl, git).
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOME = Path.home()
BIN = HOME / ".local" / "bin"
TMUX_CTL = str(BIN / "tmux-ctl")
DEV = str(BIN / "dev")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from paneclass import SHELLS, VERSION_RE, WAITING_RE, WORKING_RE, classify, input_has_text, tmux_cmd  # noqa: E402,F401
TMUX = tmux_cmd()   # which tmux server the board shows: bin/_tc_bins.zsh decides (tmux-dash passes TMUX_DASH_TMUX_ARGS)
import activity, artifacts, dirs, ideas, relay, usage  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

TOKEN = os.environ["TMUX_DASH_TOKEN"]
PORT = int(os.environ.get("TMUX_DASH_PORT", "7700"))
TTYD_PORT = int(os.environ.get("TMUX_DASH_TTYD_PORT", "7701"))
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

SEP = "\x1f"

# Every process spawn costs ~0.5s on this Mac (endpoint security scans each exec), so
# subprocesses run in parallel, worktree info is cached, and concurrent polls share one result.
POOL = ThreadPoolExecutor(max_workers=12)
STATE_TTL = 1.5   # seconds a computed /api/state is reused
WT_TTL = 30       # seconds worktree info is fresh; older is served while a refresh runs


def tmux(*args, check=False):
    r = subprocess.run(TMUX + list(args), capture_output=True, text=True, timeout=10)
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "tmux failed")
    return r.stdout


def tmux_env():
    """Environment for tmux-ctl / dev: point $TMUX at the same server we read."""
    env = dict(os.environ)
    sock = tmux("display", "-p", "#{socket_path}").strip()
    if sock:
        env["TMUX"] = f"{sock},0,0"
    env.pop("TMUX_PANE", None)
    return env


def run_script(args, cwd=None, extra_env=None, timeout=30):
    env = tmux_env()
    env.update(extra_env or {})
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise RuntimeError(out or f"exit {r.returncode}")
    return out


def pane_text(target, lines=40):
    txt = tmux("capture-pane", "-p", "-J", "-t", target, "-S", f"-{lines}")
    rows = [l.rstrip() for l in txt.splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    return rows


def preview(rows, n=10):
    keep = [r for r in rows if r.strip() and not set(r.strip()) <= set("─━═-│ ")]
    return keep[-n:]


_state_lock = threading.Lock()
_state_cache = {"at": 0.0, "value": None}


def state():
    """Shared, briefly cached build_state(): a slow build never stacks up behind polling."""
    with _state_lock:
        if _state_cache["value"] is not None and time.monotonic() - _state_cache["at"] < STATE_TTL:
            return _state_cache["value"]
        value = build_state()
        _state_cache.update(at=time.monotonic(), value=value)
        return value


VENDOR = {"marked.min.js", "purify.min.js"}


def vendor_file(name):
    return HERE / "vendor" / name if name in VENDOR else None


COMMENTS = artifacts.CommentQueue()
INDEXER = None   # usage.Indexer, set only when run as a script (see __main__)
NAME_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")   # the same rule as ideas.py


def project_arg(q):
    sess = (q.get("session") or [""])[0]
    if not NAME_RE.fullmatch(sess):
        raise ValueError("bad session")
    return sess


def send_line(pane, text):
    tmux("send-keys", "-t", pane, "-l", "--", text, check=True)
    time.sleep(0.2)
    tmux("send-keys", "-t", pane, "Enter", check=True)


def _input_busy(pane):
    try:
        return input_has_text(pane_text(pane, 40))
    except Exception:
        return True   # cannot tell: hold the comment


def deliver_comments(sessions):
    for s in sessions:
        if not COMMENTS.pending(s["name"]):
            continue
        for w in s["windows"]:
            if w["name"] == "claude" and w["panes"]:
                p = w["panes"][0]
                COMMENTS.deliver(s["name"], p["id"], p["kind"], p["status"], send_line,
                                 input_has_text=lambda pane: _input_busy(pane))


def build_state():
    fmt = SEP.join([
        "#{session_name}", "#{session_attached}", "#{window_index}", "#{window_name}",
        "#{window_bell_flag}", "#{@tc_agent}", "#{pane_index}", "#{pane_id}", "#{pane_title}",
        "#{pane_current_command}", "#{pane_current_path}", "#{pane_active}", "#{window_active}",
        "#{@tc_teammate}", "#{@tc_bg}",
    ])
    panes = [f for f in (l.split(SEP) for l in tmux("list-panes", "-a", "-F", fmt).splitlines())
             if len(f) == 15 and not f[0].startswith("_web-") and f[14] != "1"]
    captures = POOL.map(lambda f: pane_text(f[7]), panes)
    sessions = {}
    for f, rows in zip(panes, captures):
        sess, attached, widx, wname, bell, agent, pidx, pid, title, cmd, path, pact, wact, mate = f[:14]
        s = sessions.setdefault(sess, {"name": sess, "attached": attached != "0", "windows": {}, "path": None})
        w = s["windows"].setdefault(widx, {
            "index": int(widx), "name": wname, "bell": bell == "1",
            "worker": agent == "1", "teammate": mate == "1", "active": wact == "1", "panes": [],
        })
        kind, status = classify(cmd, rows, bell == "1")
        w["panes"].append({
            "id": pid, "index": int(pidx), "title": title, "command": cmd, "path": path,
            "active": pact == "1", "kind": kind, "status": status, "preview": preview(rows),
        })
        if s["path"] is None or widx == "1":
            s["path"] = path
    out = list(sessions.values())
    for s in out:  # not on POOL: worktrees() itself waits on POOL jobs
        s["windows"] = sorted(s["windows"].values(), key=lambda w: w["index"])
        s["worktrees"] = cached_worktrees(s["path"])
    out.sort(key=lambda s: (not s["attached"], s["name"]))
    deliver_comments(out)
    snap = INDEXER.snapshot() if INDEXER else []
    usage.card_alerts(out, snap)
    usage.card_labels(out, snap)
    return {"sessions": out, "ttyd": {"port": TTYD_PORT, "base": f"/{TOKEN}-tty"}}



def label_targets(run=None):
    """Sessions shaped like build_state's, with each window's current @tc_label; one list-panes, no captures."""
    fmt = SEP.join(["#{session_name}", "#{window_index}", "#{window_name}", "#{@tc_agent}", "#{@tc_teammate}",
                    "#{@tc_bg}", "#{pane_id}", "#{pane_current_path}", "#{@tc_label}"])
    sessions = {}
    for f in ((run or tmux)("list-panes", "-a", "-F", fmt).splitlines()):
        f = f.split(SEP)
        if len(f) != 9 or f[0].startswith("_web-") or f[5] == "1":
            continue
        sess, widx, wname, agent, mate, _, pid, path, label = f
        s = sessions.setdefault(sess, {"name": sess, "path": None, "windows": {}})
        w = s["windows"].setdefault(widx, {"name": wname, "worker": agent == "1", "teammate": mate == "1",
                                           "label": label, "panes": []})
        w["panes"].append({"id": pid, "path": path})
        if s["path"] is None or widx == "1":
            s["path"] = path
    for s in sessions.values():
        s["windows"] = [s["windows"][k] for k in sorted(s["windows"], key=int)]
    return list(sessions.values())


def sync_labels(live, run=None):
    """Keep each agent window's @tc_label equal to its usage label; unset it when no live session matches.

    Runs in the indexer thread (Indexer on_snapshot), never on the api/state path. Writes only on change.
    """
    run = run or tmux
    sessions = label_targets(run)
    current = {p["id"]: w["label"] for s in sessions for w in s["windows"] for p in w["panes"]}
    for pane, e in usage.card_labels(sessions, live).items():
        want = e["label"] if e else ""
        if want == current.get(pane, ""):
            continue
        if want:
            run("set-option", "-w", "-t", pane, "@tc_label", want)
        else:
            run("set-option", "-wu", "-t", pane, "@tc_label")


def git(path, *args):
    return subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, timeout=10)


def worktrees(path):
    if not path:
        return None
    r = git(path, "worktree", "list", "--porcelain")
    if r.returncode != 0:
        return None
    blocks, cur = [], {}
    for line in r.stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("branch refs/heads/"):
            cur["branch"] = line[18:]
        elif line.startswith("locked"):
            cur["locked"] = line[7:] or "locked"
        elif not line and cur:
            blocks.append(cur)
            cur = {}
    if not blocks:
        return None
    main = blocks[0]["path"]
    agents = [b for b in blocks[1:] if "/.claude/worktrees/" in b["path"]]
    current_f = POOL.submit(lambda: git(main, "branch", "--show-current").stdout.strip())
    base_f = POOL.submit(lambda: git(main, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").stdout.strip() or "main")
    ages_f = POOL.submit(git, main, "for-each-ref", "--format=%(refname:short)%09%(committerdate:relative)", "refs/heads/")
    dirty_f = [POOL.submit(git, b["path"], "status", "--porcelain") for b in agents]
    current, base = current_f.result(), base_f.result()
    merged_f = [POOL.submit(git, main, "for-each-ref", "--format=%(refname:short)", f"--merged={ref}", "refs/heads/")
                for ref in {current, base} if ref]
    merged_set = {l for f in merged_f for l in f.result().stdout.splitlines()}
    ages = dict(l.split("\t", 1) for l in ages_f.result().stdout.splitlines() if "\t" in l)
    items = []
    for b, d in zip(agents, dirty_f):
        br = b.get("branch")
        age = ages.get(br) if br else git(b["path"], "log", "-1", "--format=%cr").stdout.strip()
        items.append({"path": b["path"], "name": Path(b["path"]).name, "branch": br,
                      "dirty": bool(d.result().stdout.strip()), "merged": bool(br) and br in merged_set,
                      "age": age or "", "locked": b.get("locked")})
    return {"repo": main, "current": current, "base": base, "items": items}


_wt_lock = threading.Lock()
_wt_cache = {}  # path -> {"at": monotonic, "value": ..., "busy": bool}


def _wt_refresh(path):
    try:
        value = worktrees(path)
    except Exception:
        value = None
    with _wt_lock:
        _wt_cache[path] = {"at": time.monotonic(), "value": value, "busy": False}
    return value


def cached_worktrees(path):
    """worktrees(path), fresh for WT_TTL seconds; after that the old value is returned
    while one background thread recomputes it."""
    if not path:
        return None
    with _wt_lock:
        e = _wt_cache.get(path)
        if e and (e["busy"] or time.monotonic() - e["at"] < WT_TTL):
            return e["value"]
        if e:
            e["busy"] = True
    if e:
        threading.Thread(target=_wt_refresh, args=(path,), daemon=True).start()
        return e["value"]
    return _wt_refresh(path)


def forget_worktrees():
    with _wt_lock:
        _wt_cache.clear()


# ---------------------------------------------------------------- actions

def session_path(sess):
    p = tmux("display", "-p", "-t", f"={sess}:", "#{pane_current_path}").strip()
    if not p:
        raise RuntimeError(f"no session '{sess}'")
    return p


def project_repo(sess):
    """The project's main checkout, even when its lead pane sits in a worktree."""
    path = next((x.get("path") for x in state()["sessions"] if x["name"] == sess), None)  # as /api/state computes it
    if not path:
        raise RuntimeError(f"no session '{sess}'")
    r = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if r.returncode != 0:
        raise RuntimeError(f"{sess} is not in a git repo")
    return str(Path(r.stdout.strip()).parent)


def open_projects():
    return [s["name"] for s in state()["sessions"] if not s["name"].startswith("_web-")]


def _check_target(sess, target):
    _check_project(target)
    if target == sess or target not in open_projects():
        raise RuntimeError(f"{target} is not open on the board")


STOPWORDS = set("""a an the to of in on for and or with from into at by as is are be it its this that
these those please can could would you we i my our me us let lets make sure just some all any""".split())


def agent_name(sess, task):
    """A free name from the task's first few words, e.g. "Fix the auth token refresh bug" -> fix-auth-token-refresh."""
    words = [w for w in re.findall(r"[a-z0-9]+", task.lower()) if w not in STOPWORDS]
    base = ""
    for w in words[:4]:
        if len(base) + len(w) + 1 > 30:
            break
        base = f"{base}-{w}" if base else w
    base = base or "agent"
    taken = set(tmux("list-windows", "-t", f"={sess}", "-F", "#{window_name}").split())
    path = session_path(sess)
    top = git(path, "rev-parse", "--show-toplevel").stdout.strip()
    if top:
        taken |= {b.strip().removeprefix("* ").removeprefix("+ ").removeprefix("claude/")
                  for b in git(top, "branch", "--list", "claude/*").stdout.splitlines()}
        wt = Path(top) / ".claude" / "worktrees"
        if wt.is_dir():
            taken |= {p.name for p in wt.iterdir()}
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


def act(body):
    try:
        return _act(body)
    finally:  # the next poll should show the effect right away
        forget_worktrees()
        with _state_lock:
            _state_cache["value"] = None


def _act(body):
    a = body.get("action")
    sess = body.get("session", "")
    if a == "agent":
        name, task = body.get("name", "").strip(), body["task"].strip()
        if not task:
            raise RuntimeError("give the agent a task")
        if not name:
            name = agent_name(sess, task)
        elif not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name):
            raise RuntimeError("agent name: letters, digits, . _ - only")
        return run_script([TMUX_CTL, "agent", name, task], cwd=session_path(sess), extra_env={"TC_SESSION": sess})
    if a == "tell":
        return run_script([TMUX_CTL, "tell", body["window"], body["text"]], extra_env={"TC_SESSION": sess}) or "sent"
    if a == "send":
        return run_script([TMUX_CTL, "send", body["window"], body["text"]], extra_env={"TC_SESSION": sess}) or "sent"
    if a == "remove_worktree":
        wt = session_worktree(sess, body["path"])
        return remove_agent_worktree(wt["repo"], wt["item"])
    if a == "dev":
        path = os.path.expanduser(body["path"].strip())
        if not os.path.isdir(path):
            raise RuntimeError(f"not a folder: {path}")
        msg = run_script([DEV, path], extra_env={"DEV_NO_ATTACH": "1"})
        try:  # best-effort: the session already started, so a failed record must not report failure
            dirs.record_recent(path)
        except OSError:
            pass
        return msg or "session ready"
    if a == "close_session":
        if not sess:
            raise RuntimeError("no session given")
        if sess.startswith("_web-"):
            raise RuntimeError("that is a browser view, not a project")
        tmux("has-session", "-t", f"={sess}", check=True)
        # browser views are grouped sessions; they would keep the project's windows alive
        group = tmux("display", "-p", "-t", f"={sess}:", "#{session_group}").strip()
        for line in tmux("list-sessions", "-F", f"#{{session_name}}{SEP}#{{session_group}}").splitlines():
            name, _, grp = line.partition(SEP)
            if group and grp == group and name.startswith("_web-"):
                tmux("kill-session", "-t", f"={name}")
        tmux("kill-session", "-t", f"={sess}", check=True)
        bg = f"={sess}-bg"   # the hidden agents' session: only ours (tagged @tc_bg), never a user session that merely ends in -bg
        try:
            if tmux("show-options", "-qv", "-t", f"{bg}:", "@tc_bg").strip():
                tmux("kill-session", "-t", bg)
        except RuntimeError:
            pass
        return f"closed project {sess}; its worktrees and branches are still on disk"
    if a == "restart_orchestrator":
        return restart_orchestrator(sess, bool(body.get("confirm")))
    if a == "stop_agent":
        return stop_agent(sess, str(body.get("window") or ""))
    if a == "ask_shutdown":
        return ask_shutdown(sess, str(body.get("window") or ""))
    if a in ("idea_edit", "idea_status", "idea_move", "artifact_move"):
        _check_project(sess)
        key = str(body.get("key") or "")
        if a == "idea_edit":
            ideas.edit(sess, key, body.get("text", ""), body.get("detail", ""))
            return "idea updated"
        if a == "idea_status":
            status = str(body.get("status") or "")
            ideas.set_status(sess, key, status)
            return "idea restored" if status == "open" else "idea dropped"
        target = str(body.get("target") or "")
        _check_target(sess, target)
        if a == "idea_move":
            ideas.move(sess, key, target)
            return f"idea moved to {target}"
        return artifacts.move(sess, str(body.get("path") or ""), target, project_repo(sess), project_repo(target))
    if a in ("save", "comment", "idea") and not NAME_RE.fullmatch(sess):
        raise RuntimeError("bad session")
    if a == "idea":
        return ideas.add(sess, body.get("text", ""), body.get("detail", ""))
    if a == "save":
        return artifacts.save(sess, body["path"], body["base_hash"], body["text"])
    if a == "comment":
        COMMENTS.add(sess, body["path"], body.get("anchor", ""), body.get("quote", ""), body.get("note", ""))
        return "comment queued for the lead"
    raise RuntimeError(f"unknown action {a!r}")


def _check_project(sess):
    if not NAME_RE.fullmatch(sess or "") or sess.startswith("_web-"):
        raise RuntimeError("bad session")


def _windows_named(sess, name):
    """Windows named exactly `name` in the project session and its tagged -bg session."""
    found = []
    targets = [sess]
    if tmux("show-options", "-qv", "-t", f"={sess}-bg:", "@tc_bg").strip():
        targets.append(f"{sess}-bg")
    for t in targets:
        out = tmux("list-windows", "-t", f"={t}", "-F",
                   f"#{{window_id}}{SEP}#{{window_name}}{SEP}#{{@tc_agent}}{SEP}#{{@tc_teammate}}")
        for line in out.splitlines():
            f = line.split(SEP)
            if len(f) == 4 and f[1] == name:
                found.append({"session": t, "id": f[0], "agent": f[2] == "1", "teammate": f[3] == "1"})
    return found


def stop_agent(sess, name):
    """Close one worker window (tagged @tc_agent by tmux-ctl agent), by window id. Its worktree stays."""
    _check_project(sess)
    hits = _windows_named(sess, name) if name else []
    if not hits:
        raise RuntimeError(f"no worker window named {name}")
    if len(hits) > 1:
        raise RuntimeError(f"more than one window named {name}; close it from its terminal")
    if not hits[0]["agent"]:
        raise RuntimeError(f"{name} is not a worker")
    tmux("kill-window", "-t", hits[0]["id"], check=True)
    return f"shut down worker {name}; its worktree and branch are still in Worktrees"


def ask_shutdown(sess, name):
    """Ask the lead (through the comment queue) to shut a teammate down; the lead owns its team."""
    _check_project(sess)
    hits = [h for h in _windows_named(sess, name) if h["session"] == sess] if name else []
    if len(hits) > 1:
        raise RuntimeError(f"more than one window named {name}; close it from its terminal")
    if not hits or not hits[0]["teammate"]:
        raise RuntimeError(f"{name} is not a teammate")
    mate = re.sub(r"^✦\s*", "", name).strip()
    COMMENTS.add_line(sess, f"[Board] Please shut down teammate {mate}.")
    return f"asked the lead to shut down {mate}"


def restart_orchestrator(sess, confirm):
    """Restart (or start) the claude-orchestrator in the session's "claude" window, in place."""
    if not sess:
        raise RuntimeError("no session given")
    if sess.startswith("_web-"):
        raise RuntimeError("that is a browser view, not a project")
    tmux("has-session", "-t", f"={sess}", check=True)
    path = session_path(sess)
    g = git(path, "rev-parse", "--show-toplevel")
    root = g.stdout.strip() if g.returncode == 0 and g.stdout.strip() else path
    wins = []
    for line in tmux("list-windows", "-t", f"={sess}", "-F",
                     f"#{{window_index}}{SEP}#{{window_name}}{SEP}#{{@tc_teammate}}").splitlines():
        f = line.split(SEP)
        if len(f) == 3:
            wins.append((f[0], f[1], f[2] == "1"))
    mates = sum(1 for _, _, t in wins if t)
    claude = next((idx for idx, name, _ in wins if name == "claude"), None)
    if claude is not None:
        line = tmux("list-panes", "-t", f"={sess}:{claude}", "-F",
                    f"#{{pane_id}}{SEP}#{{pane_current_command}}{SEP}#{{window_bell_flag}}", check=True).splitlines()[0]
        pane, cmd, bell = line.split(SEP)
        kind, status = classify(cmd, pane_text(pane), bell == "1")
        if kind == "claude" and status in ("working", "waiting") and not confirm:
            why = "working" if status == "working" else "waiting on you"
            raise RuntimeError(f"the orchestrator is busy ({why}); confirm to restart it anyway")
        relay.respawn(tmux, pane, root)
        verb = "restarted the"
    else:
        pane = tmux("new-window", "-d", "-P", "-F", "#{pane_id}", "-t", f"={sess}:", "-n", "claude",
                    "-c", root, check=True).strip()
        if not any(idx == "1" for idx, _, _ in wins):  # best effort; keys always go to the pane id
            tmux("move-window", "-s", f"={sess}:claude", "-t", f"={sess}:1")
        relay.respawn(tmux, pane, root)
        verb = "started an"
    msg = f"{verb} orchestrator in {sess}:claude"
    if mates:
        msg += f", {mates} teammate window{'s' if mates != 1 else ''} from the old one {'are' if mates != 1 else 'is'} still open"
    return msg


CLAUDE_LOCK = re.compile(r"^claude \S+ .+ \(pid (\d+)( start .+)?\)$")


def claude_lock_owner(reason):
    m = CLAUDE_LOCK.match(reason or "")
    return int(m.group(1)) if m else None


def proc_args(pid):
    r = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip()


def lock_is_stale(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass   # alive, owned by someone else
    return "claude" not in proc_args(pid).lower()   # alive but not Claude: the pid was reused


def remove_agent_worktree(repo, item):
    path, reason, note = item["path"], item.get("locked"), ""
    if reason:
        pid = claude_lock_owner(reason)
        if pid is None:
            raise RuntimeError(f"locked by something other than Claude ({reason}); unlock it yourself")
        if not lock_is_stale(pid):
            raise RuntimeError(f"in use by a running Claude session (pid {pid})")
        git(repo, "worktree", "unlock", path)
        forget_worktrees()
        note = f"unlocked stale lock (pid {pid}); "
    r = git(repo, "worktree", "remove", path)
    if r.returncode != 0:
        if reason:
            git(repo, "worktree", "lock", "--reason", reason, path)
        raise RuntimeError((r.stderr or r.stdout).strip() or "git refused (uncommitted changes?)")
    msg = f"{note}removed worktree {item['name']}"
    br = item.get("branch")
    if br:
        d = git(repo, "branch", "-d", br)
        msg += f"; deleted branch {br}" if d.returncode == 0 else f"; kept branch {br} (not merged)"
    git(repo, "worktree", "prune")
    forget_worktrees()
    return msg


def session_worktree(sess, path):
    wt = worktrees(session_path(sess))
    if not wt:
        raise RuntimeError("not a git repo")
    for item in wt["items"]:
        if item["path"] == path:
            return {"repo": wt["repo"], "item": item}
    raise RuntimeError("unknown worktree")


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    server_version = "tmux-dash"

    def log_message(self, fmt, *args):
        if os.environ.get("TMUX_DASH_DEBUG"):
            sys.stderr.write("%s\n" % (fmt % args))

    def _guard(self):
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self._send(421, b"bad host", "text/plain")
            return None
        prefix = f"/{TOKEN}/"
        if not self.path.startswith(prefix):
            self._send(404, b"not found", "text/plain")
            return None
        return self.path[len(prefix):].split("?", 1)[0]

    def _send(self, code, data, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if "Cache-Control" not in (extra or {}):
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        sub = self._guard()
        if sub is None:
            return
        q = parse_qs(urlsplit(self.path).query)
        if sub == "":
            html = (HERE / os.environ.get("TMUX_DASH_PAGE", "index.html")).read_text()
            csp = (f"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                   f"frame-src http://127.0.0.1:{TTYD_PORT} http://localhost:{TTYD_PORT}; frame-ancestors 'none'")
            self._send(200, html.encode(), "text/html; charset=utf-8",
                       {"Content-Security-Policy": csp, "X-Frame-Options": "DENY"})
        elif sub == "api/state":
            try:
                self._json(200, state())
            except Exception as e:  # tmux server not running, etc.
                self._json(200, {"sessions": [], "error": str(e), "ttyd": {"port": TTYD_PORT, "base": f"/{TOKEN}-tty"}})
        elif sub == "api/artifacts":
            try:
                sess = project_arg(q)
                self._json(200, {**artifacts.summary(sess), "comments": COMMENTS.pending(sess)})
            except ValueError as e:
                self._json(400, {"error": str(e)})
        elif sub.startswith("vendor/"):
            f = vendor_file(sub[len("vendor/"):])
            if f is None or not f.exists():
                self._send(404, b"not found", "text/plain")
            else:
                self._send(200, f.read_bytes(), "application/javascript; charset=utf-8", {"Cache-Control": "max-age=86400"})
        elif sub == "api/ideas":
            try:
                sess = project_arg(q)
                self._json(200, {"ideas": ideas.load(sess), "open": ideas.open_count(sess)})
            except ValueError as e:
                self._json(400, {"error": str(e)})
        elif sub == "api/runs":
            try:
                sess = project_arg(q)
                rs = activity.runs(sess)
                idx = {}
                for r in rs:
                    if r.get("exit") is None and r.get("session"):
                        if r["session"] not in idx:
                            idx[r["session"]] = dict(l.split(SEP, 1) for l in tmux(
                                "list-windows", "-t", f"={r['session']}", "-F", f"#{{window_name}}{SEP}#{{window_index}}").splitlines() if SEP in l)
                        r["window_index"] = idx[r["session"]].get(r.get("win"))
                self._json(200, {"runs": rs})
            except ValueError as e:
                self._json(400, {"error": str(e)})
        elif sub == "api/log":
            try:
                txt = activity.log_text(project_arg(q), (q.get("id") or [""])[0])
                self._send(200, txt.encode(), "text/plain; charset=utf-8")
            except (FileNotFoundError, ValueError):
                self._json(404, {"error": "no log (still running?)"})
        elif sub == "api/usage":
            try:
                sess = project_arg(q)
            except ValueError as e:
                self._json(400, {"error": str(e)})
                return
            try:
                path = next((x["path"] for x in state().get("sessions", []) if x["name"] == sess and x.get("path")), None)
            except Exception:  # tmux not running: no sessions
                path = None
            if path is None:
                self._json(404, {"error": "no such session"})
                return
            conn = None   # per request: the indexer's connection belongs to its thread
            try:
                conn = usage.connect(usage.db_path())
                th, warn = usage.thresholds()
                r = usage.report(conn, path, usage.load_prices(), th, time.time())
            except Exception as e:  # sqlite locked or corrupt, bad prices.json: say so instead of dropping the connection
                self._json(500, {"error": str(e) or type(e).__name__})
                return
            finally:
                if conn is not None:
                    conn.close()
            self._json(200, {**r, "warning": warn, "indexing": INDEXER.progress() if INDEXER else None,
                             "index_error": INDEXER.error if INDEXER else None})
        elif sub == "api/artifact":
            try:
                self._json(200, artifacts.read(project_arg(q), (q.get("path") or [""])[0]))
            except (FileNotFoundError, ValueError):
                self._json(404, {"error": "not an artifact of this session"})
        elif sub == "api/dirs":
            path = (q.get("path") or [""])[0]
            try:
                self._json(200, dirs.list_dirs(path, (q.get("prefix") or [""])[0], (q.get("hidden") or ["1"])[0] != "0"))
            except NotADirectoryError as e:
                self._json(400, {"error": str(e)})
            except ValueError:  # embedded null byte: realpath refuses it
                self._json(400, {"error": f"not a folder: {path}"})
            except PermissionError:
                self._json(403, {"error": f"can't read {path or '~'}: permission denied"})
        elif sub == "api/dirs/recent":
            try:
                open_paths = [os.path.realpath(s["path"]) for s in state().get("sessions", []) if s.get("path")]
            except Exception:  # tmux not running: the stored list still helps
                open_paths = []
            self._json(200, {"recent": dirs.recent(open_paths)})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        sub = self._guard()
        if sub is None:
            return
        if sub != "api/action" or self.headers.get("X-Dash-Token") != TOKEN:
            self._send(403, b"forbidden", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(n, 2_097_152)) or b"{}")
            self._json(200, {"ok": True, "message": act(body)})
        except artifacts.Conflict as e:
            self._json(409, {"ok": False, "message": str(e), "current": e.current})
        except ideas.Stale as e:
            self._json(409, {"ok": False, "message": str(e)})
        except Exception as e:
            self._json(400, {"ok": False, "message": str(e)})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    INDEXER = usage.Indexer(usage.root(), usage.db_path(), on_snapshot=sync_labels)
    INDEXER.start()
    print(f"tmux-dash on http://127.0.0.1:{PORT}/{TOKEN}/", flush=True)
    srv.serve_forever()
