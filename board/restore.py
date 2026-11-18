"""Reboot auto-restore, part 1: the snapshot of the agent-board tmux server, the boot time and the guarded save
(spec 2026-11-18-reboot-auto-restore-design.md §1). Every external read goes through run(cmd) -> (rc, stdout)."""
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import paneclass  # noqa: E402
import tc_env  # noqa: E402

DISCORD_PLUGIN = "plugin:discord@claude-plugins-official"
BOOT_RE = re.compile(r"\bsec\s*=\s*(\d+)")
BRIDGE_RE = re.compile(r"(?:^|\s)node\s+\S*discord-bridge/bridge\.js\b")
SKIP_NAMES = {"overseer"}


def _run(cmd):
    """Run cmd; (returncode, stdout). (1, "") when it cannot start or takes over 10 s."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def restore_dir():
    """Where snapshot.json lives: tc_env.agent_base()/restore (survives a reboot, unlike tc_env.state_dir())."""
    return tc_env.agent_base() / "restore"


def boot_time(run=_run):
    """Seconds since the epoch of the last boot, from `sysctl -n kern.boottime`; None when unreadable."""
    try:
        rc, out = run(["sysctl", "-n", "kern.boottime"])
    except Exception:
        return None
    m = BOOT_RE.search(out or "") if rc == 0 else None
    return int(m.group(1)) if m else None


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False
    return True


def _rows(run, cmd):
    """Non-empty stdout lines of cmd; None when it failed."""
    rc, out = run(cmd)
    return None if rc != 0 else [ln for ln in (out or "").splitlines() if ln.strip()]


def _procs(run):
    """pid -> (ppid, args) from one `ps -A` listing; {} when it failed."""
    procs = {}
    for ln in _rows(run, ["ps", "-A", "-o", "pid=,ppid=,args="]) or []:
        parts = ln.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
    return procs


def _claude_in(procs, root):
    """(pid, args) of the claude process that is pid root or one of its descendants, else None."""
    kids = {}
    for pid, (ppid, _) in procs.items():
        kids.setdefault(ppid, []).append(pid)
    todo, seen = [root], set()
    while todo:
        pid = todo.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        if pid in procs:
            argv = procs[pid][1].split()
            if argv and os.path.basename(argv[0]) == "claude":
                return pid, procs[pid][1]
        todo.extend(sorted(kids.get(pid, [])))
    return None


def _ancestors(procs, pid):
    """pid and its ancestors, nearest first (the chain ends at a pid ps did not list)."""
    out = []
    while pid not in out:
        out.append(pid)
        if pid not in procs:
            break
        pid = procs[pid][0]
    return out


def _model(args):
    try:
        w = shlex.split(args)
    except ValueError:
        w = args.split()
    for i, a in enumerate(w):
        if a == "--model" and i + 1 < len(w):
            return w[i + 1]
        if a.startswith("--model="):
            return a[8:] or None
    return None


def _discord(args):
    return DISCORD_PLUGIN in args and "--channels" in args


def _awake(awake_file, leads, pid_alive):
    """The live keep-awake hold as {lid, queue, project}; None when absent, unreadable or its caffeinate is dead.
    A queue hold names the first lead's project; a pid hold carries the watched pid as "pid" (the caller maps it)."""
    try:
        rec = json.loads(Path(awake_file).read_text())
        cp = rec.get("caffeinatePid")
        if not cp or not pid_alive(cp):
            return None
        queue = bool(rec.get("queue"))
        return {"lid": bool(rec.get("lid")), "queue": queue, "project": leads[0][0] if queue and leads else None,
                "pid": rec.get("pid")}
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def snapshot(run=_run, tmux=None, status_dir=None, awake_file=None, now=None, pid_alive=None):
    """The spec §1 snapshot dict for the tmux server; None when tmux cannot list sessions. Never raises: a failing
    ps or status read leaves that field null/false."""
    try:
        return _snapshot(run, tmux, status_dir, awake_file, now, pid_alive or _pid_alive)
    except Exception:
        return None


def _snapshot(run, tmux, status_dir, awake_file, now, pid_alive):
    now = time.time() if now is None else now
    tmux = list(paneclass.tmux_cmd() if tmux is None else tmux)
    sessions = _rows(run, tmux + ["list-sessions", "-F", "#{session_name}\t#{session_group}\t#{session_path}\t#{@tc_bg}"])
    if sessions is None:
        return None
    pane_rows = _rows(run, tmux + ["list-panes", "-a", "-F", "#{session_name}\t#{window_name}\t#{pane_id}\t#{pane_pid}"]) or []
    panes = []
    for ln in pane_rows:
        p = ln.split("\t")
        if len(p) >= 4:
            panes.append(p[:4])
    procs = _procs(run)
    try:
        recs = paneclass.mod_records(now, status_dir)
    except Exception:
        recs = {}

    def window_panes(session, window):
        return [(pid, ppid) for s, w, pid, ppid in panes if s == session and w == window]

    projects, seen, claude_pids = [], set(), {}
    for ln in sessions:
        f = ln.split("\t")
        f += [""] * (4 - len(f))
        name, group, path, bg = f[0], f[1], f[2], f[3]
        proj = group or name
        if (name.endswith("-bg") or proj.endswith("-bg") or bg.strip() not in ("", "0") or name.startswith("_web-")
                or proj.startswith("_web-") or name in SKIP_NAMES or proj in SKIP_NAMES or proj in seen):
            continue
        cw = window_panes(name, "claude")
        if not cw:
            continue
        seen.add(proj)
        lead = None
        for pane_id, pane_pid in cw:
            try:
                found = _claude_in(procs, int(pane_pid))
            except ValueError:
                found = None
            if found:
                cpid, args = found
                claude_pids[proj] = cpid
                rec = recs.get(pane_id) or {}
                sid = rec.get("session_id")
                lead = {"session_id": sid if isinstance(sid, str) else None, "model": _model(args), "discord": _discord(args)}
                break
        bridge = False
        for _, pane_pid in window_panes(f"{proj}-bg", "discord"):
            try:
                bridge = any(BRIDGE_RE.search(a) for pid, (_, a) in procs.items()
                             if int(pane_pid) in _ancestors(procs, pid))
            except ValueError:
                pass
        projects.append({"name": proj, "path": path, "lead": lead, "bridge": bridge})

    leads = [(p["name"], claude_pids[p["name"]]) for p in projects if p["lead"] and p["name"] in claude_pids]
    if awake_file is None:
        awake_file = tc_env.state_dir() / "awake.json"
    awake = _awake(awake_file, leads, pid_alive)
    if awake is not None:
        watched = awake.pop("pid")
        if not awake["queue"]:
            awake["project"] = next((n for n, cpid in leads if watched in _ancestors(procs, cpid)), None)
    return {"boot": boot_time(run), "saved_at": now, "restored": False, "awake": awake, "projects": projects}


def load(dir):
    """The snapshot dict saved in dir (snapshot.json); None when absent or unreadable."""
    try:
        d = json.loads((Path(dir) / "snapshot.json").read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def save(dir, snap):
    """Write snap to dir/snapshot.json through .next + rename; True when written. Refuses (False) a missing snapshot
    or boot, a zero-project snapshot over an existing one, and any replacement of an earlier boot's snapshot whose
    restored is false."""
    if not snap or snap.get("boot") is None:
        return False
    old = load(dir)
    if old is not None:
        if not snap.get("projects"):
            return False
        ob = old.get("boot")
        if isinstance(ob, int) and ob < snap["boot"] and not old.get("restored"):
            return False
    try:
        d = Path(dir)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "snapshot.json.next"
        tmp.write_text(json.dumps(snap, indent=1))
        os.replace(tmp, d / "snapshot.json")
        return True
    except OSError:
        return False
