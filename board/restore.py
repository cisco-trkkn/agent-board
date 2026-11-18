"""Reboot auto-restore, part 1: the snapshot of the agent-board tmux server, the boot time and the guarded save
(spec 2026-11-18-reboot-auto-restore-design.md §1). Every external read goes through run(cmd) -> (rc, stdout)."""
import argparse
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import paneclass  # noqa: E402
import tc_env  # noqa: E402

DISCORD_PLUGIN = "plugin:discord@claude-plugins-official"
BOOT_RE = re.compile(r"\bsec\s*=\s*(\d+)")
BRIDGE_RE = re.compile(r"(?:^|\s)node\s+\S*discord-bridge/bridge\.js\b")
SKIP_NAMES = {"overseer"}
SYSCTL, ROUTE = "/usr/sbin/sysctl", "/sbin/route"   # not on the LaunchAgent PATH (~/.local/bin:/opt/homebrew/bin:~/.bun/bin:/usr/bin:/bin)


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
        rc, out = run([SYSCTL, "-n", "kern.boottime"])
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


def snapshot(run=_run, tmux=None, status_dir=None, awake_file=None, now=None, pid_alive=None, on_error=None):
    """The spec §1 snapshot dict for the tmux server; None when tmux cannot list sessions. Never raises: a failing
    ps or status read leaves that field null/false. An unexpected exception is passed to on_error(exc), if given."""
    try:
        return _snapshot(run, tmux, status_dir, awake_file, now, pid_alive or _pid_alive)
    except Exception as e:
        if on_error:
            on_error(e)
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


def load_file(dir, name):
    """The JSON dict in dir/name; None when absent or unreadable."""
    try:
        d = json.loads((Path(dir) / name).read_text())
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def load(dir):
    """The snapshot dict saved in dir (snapshot.json); None when absent or unreadable."""
    return load_file(dir, "snapshot.json")


BOOT_SLACK = 60   # kern.boottime shifts by a few seconds when the clock is stepped: a boot is new only beyond this


def _newer_boot(old, new):
    """True when boot time new is a later boot than old (more than BOOT_SLACK seconds later)."""
    return isinstance(old, int) and isinstance(new, int) and new - old > BOOT_SLACK


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
        if _newer_boot(ob, snap["boot"]) and not old.get("restored"):
            return False
    return _write(dir, snap)


def _write(dir, snap):
    """Write snap to dir/snapshot.json through .next + rename, with no guards; True when written."""
    try:
        d = Path(dir)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "snapshot.json.next"
        tmp.write_text(json.dumps(snap, indent=1))
        os.replace(tmp, d / "snapshot.json")
        return True
    except OSError:
        return False


# ---- tick and restore (spec §2-3) ----

REPO = Path(__file__).resolve().parent.parent
RESUME_PROMPT = ("The Mac was rebooted (forced macOS update) and every teammate and worker is gone. Check TaskList, git "
                 "status and git worktree list; respawn the team for unfinished tasks and continue the plan. If a Plan & "
                 "run task carries metadata.queue, queue mode is on: the keep-awake hold has already been restored, "
                 "check it with tmux-ctl awake status.")
NET_WAIT, NET_POLL = 300, 5
PID_WAIT, PID_POLL = 60, 2
BRIDGE_WAIT, BRIDGE_POLL = 120, 2


def _sh(cmd, env=None, cwd=None):
    """Run cmd with an optional env and cwd; (returncode, stdout+stderr). (1, reason) when it cannot start or hangs."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env, cwd=cwd)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


@dataclass
class Cfg:
    """Every external seam of tick/restore. sh(cmd, env, cwd) -> (rc, out); ctl/dash_ctl are command-word lists
    (tmux-ctl, agent-board); orch/dev are paths; sleep(s), clock() -> seconds, now() -> epoch for the log and marks."""
    sh: Callable = _sh
    tmux: list = None
    ctl: list = None
    dash_ctl: list = None
    orch: str = ""
    dev: str = ""
    sleep: Callable = time.sleep
    clock: Callable = time.monotonic
    home: str = ""
    pid_alive: Callable = _pid_alive
    now: Callable = time.time


def default_cfg():
    """The live Cfg: TC_RESTORE_CTL / TC_RESTORE_ORCH / TC_RESTORE_DEV replace the repo's bin/ files (tests)."""
    ctl_env = os.environ.get("TC_RESTORE_CTL")
    return Cfg(tmux=paneclass.tmux_cmd(),
               ctl=shlex.split(ctl_env) if ctl_env else [str(REPO / "bin" / "tmux-ctl")],
               dash_ctl=shlex.split(ctl_env) if ctl_env else [str(REPO / "bin" / "agent-board")],
               orch=os.environ.get("TC_RESTORE_ORCH") or str(REPO / "bin" / "claude-orchestrator"),
               dev=os.environ.get("TC_RESTORE_DEV") or str(REPO / "bin" / "dev"),
               home=os.environ.get("HOME") or str(Path.home()))


def _hhmm(t):
    return datetime.fromtimestamp(t).strftime("%H:%M")


def _log(dir, cfg, msg):
    try:
        Path(dir).mkdir(parents=True, exist_ok=True)
        with open(Path(dir) / "restore.log", "a") as f:
            f.write(f"{datetime.fromtimestamp(cfg.now()).isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass


def _lead_pid(cfg, session):
    """pid of the claude process in session's claude window, else None."""
    rows = _rows(cfg.sh, list(cfg.tmux) + ["list-panes", "-a", "-F", "#{session_name}\t#{window_name}\t#{pane_id}\t#{pane_pid}"])
    procs = _procs(cfg.sh)
    for ln in rows or []:
        f = ln.split("\t")
        if len(f) >= 4 and f[0] == session and f[1] == "claude" and f[3].isdigit():
            found = _claude_in(procs, int(f[3]))
            if found:
                return found[0]
    return None


def _lead_cmd(cfg, lead):
    parts = [cfg.orch]
    if lead.get("model"):
        parts += ["--model", lead["model"]]
    if lead.get("discord"):
        parts += ["--channels", DISCORD_PLUGIN]
    parts += ["--resume", lead["session_id"]] if lead.get("session_id") else ["--continue"]
    return " ".join(shlex.quote(p) for p in parts + [RESUME_PROMPT])


def _poll(cfg, wait, every, probe):
    """Call probe() until it returns something truthy or wait seconds pass; its last value."""
    start = cfg.clock()
    while True:
        v = probe()
        if v or cfg.clock() - start >= wait:
            return v
        cfg.sleep(every)


def _step(dir, cfg, name, step, failures, rc_out):
    """Log one step's (rc, out) and record a failure when rc != 0."""
    rc, out = rc_out
    msg = (out or "").strip().splitlines()[-1:] or [f"rc {rc}"]
    if rc != 0:
        failures.append((step, msg[0]))
    _log(dir, cfg, f"{name}: {step} " + ("ok" if rc == 0 else f"failed: {msg[0]}"))


def do_restore(dir, snap, cfg):
    """Replay snap on a freshly booted Mac (spec §3), one logged step at a time; a failing project never stops the
    others. Marks the snapshot restored (with restored_at and results) even after failures; returns the results
    {project: {"status", "failures", "error"?}}."""
    _log(dir, cfg, f"restore: boot {snap.get('boot')}, {len(snap.get('projects') or [])} projects")
    ok = _poll(cfg, NET_WAIT, NET_POLL, lambda: cfg.sh([os.environ.get("TC_RESTORE_ROUTE") or ROUTE, "-n", "get", "default"])[0] == 0)
    _log(dir, cfg, "network: up" if ok else "network: not up after 300 s, carrying on")
    shared = []
    _step(dir, cfg, "board", "dash start", shared, _safe(cfg.sh, list(cfg.dash_ctl) + ["dash", "start"], cwd=cfg.home))
    results, opened = {}, {}
    for p in snap.get("projects") or []:
        name, path = p.get("name", "?"), p.get("path") or ""
        res = results[name] = {"status": "failed", "failures": []}
        fails = res["failures"]
        try:
            _restore_project(dir, cfg, p, name, path, res, fails, opened)
        except Exception as e:
            fails.append(("project", f"{type(e).__name__}: {e}"))
            _log(dir, cfg, f"{name}: project failed: {e}")
    awake = snap.get("awake")
    if awake:
        try:
            _restore_awake(dir, cfg, awake, snap, opened, shared)
        except Exception as e:
            shared.append(("awake", f"{type(e).__name__}: {e}"))
    for p in snap.get("projects") or []:
        name = p.get("name", "?")
        res = results[name]
        if p.get("bridge") and res["status"] == "restored":
            try:
                _report(dir, cfg, snap, p, res, shared)
            except Exception as e:
                res["failures"].append(("report", f"{type(e).__name__}: {e}"))
        if res["failures"]:
            res["error"] = "; ".join(f"{a}: {b}" for a, b in res["failures"])
    snap["restored"] = True
    snap["restored_at"] = cfg.now()
    snap["results"] = {n: {k: v for k, v in r.items() if k != "failures"} for n, r in results.items()}
    _write(dir, snap)
    try:
        (Path(dir) / "last-restore.json").write_text(json.dumps(snap, indent=1))   # what `again` replays
    except OSError:
        pass
    _log(dir, cfg, "restore: done")
    return results


def _safe(sh, cmd, env=None, cwd=None):
    try:
        return sh(cmd, env=env, cwd=cwd)
    except Exception as e:
        return 1, str(e)


def _restore_project(dir, cfg, p, name, path, res, fails, opened):
    if not path or not os.path.isdir(path):
        fails.append(("open", f"folder {path} is gone"))
        _log(dir, cfg, f"{name}: folder {path} is gone")
        return
    session = name   # the snapshot name is the session (or group) to find; bin/dev is given the path only
    if cfg.sh(list(cfg.tmux) + ["has-session", "-t", f"={session}"])[0] == 0:
        res["status"] = "already open"
        opened[name] = session
        _log(dir, cfg, f"{name}: already open")
        return
    env = {k: v for k, v in os.environ.items()
           if k not in ("TMUX", "TMUX_PANE", "DISCORD_STATE_DIR", "DEV_NO_LEAD", "DEV_CLAUDE_CMD", "DEV_NO_ATTACH")}
    env["DEV_NO_ATTACH"] = "1"
    lead = p.get("lead")
    if lead:
        env["DEV_CLAUDE_CMD"] = _lead_cmd(cfg, lead)
    else:
        env["DEV_NO_LEAD"] = "1"
    _step(dir, cfg, name, "open", fails, _safe(cfg.sh, [cfg.dev, path], env=env, cwd=cfg.home))
    if fails:
        return
    if cfg.sh(list(cfg.tmux) + ["has-session", "-t", f"={session}"])[0] != 0:
        fails.append(("session name", f"dev did not create {session}"))
        _log(dir, cfg, f"{name}: session name: dev did not create {session}")
        return
    res["status"] = "restored"
    opened[name] = session
    if p.get("bridge"):
        _step(dir, cfg, name, "bridge start", fails,
              _safe(cfg.sh, list(cfg.ctl) + ["discord", "bridge", "start", "--project", name], cwd=cfg.home))


def _restore_awake(dir, cfg, awake, snap, opened, shared):
    args = list(cfg.ctl) + ["awake", "on"]
    if awake.get("queue"):
        args.append("--queue")
    else:
        session = opened.get(awake.get("project"))
        pid = _poll(cfg, PID_WAIT, PID_POLL, lambda: _lead_pid(cfg, session)) if session else None
        if not pid:
            shared.append(("awake", "no lead pid to watch"))
            _log(dir, cfg, "awake: no lead pid to watch")
            return
        args += ["--pid", str(pid)]
    if awake.get("lid"):
        args.append("--lid")
    _step(dir, cfg, "keep-awake", "awake on", shared, _safe(cfg.sh, args, cwd=cfg.home))


def _report(dir, cfg, snap, p, res, shared):
    name = p["name"]
    pidfile = tc_env.discord_dir(name) / "bridge.pid"

    def up():
        try:
            return cfg.pid_alive(int(pidfile.read_text().strip()))
        except (OSError, ValueError):
            return False
    if not _poll(cfg, BRIDGE_WAIT, BRIDGE_POLL, up):
        res["failures"].append(("bridge up", "bridge.pid not alive after 120 s"))
    lead = p.get("lead")
    awake = snap.get("awake") or {}
    mode = "none" if awake.get("project") != name and not awake.get("queue") else ("lid" if awake.get("lid") else "plain")
    parts = ["lead resumed (" + lead["session_id"][:8] + ")" if lead and lead.get("session_id")
             else "lead continued" if lead else "no lead"]
    parts += ["bridge", f"keep-awake {mode}"]
    text = f"Mac restarted at {_hhmm(snap.get('boot') or 0)} (boot), restored at {_hhmm(cfg.now())}: " + " · ".join(parts)
    text += "".join(f"\nfailed: {a}: {b}" for a, b in res["failures"] + shared)
    _step(dir, cfg, name, "discord send", res["failures"],
          _safe(cfg.sh, list(cfg.ctl) + ["discord", "send", "--project", name, "-m", text], cwd=cfg.home))


def _carry_session_ids(old, snap):
    """Same boot: a lead whose session_id could not be read this time keeps the one the previous snapshot had."""
    if not old or old.get("boot") != snap.get("boot"):
        return
    prev = {p.get("name"): (p.get("lead") or {}).get("session_id") for p in old.get("projects") or []}
    for p in snap.get("projects") or []:
        lead = p.get("lead")
        if lead and not lead.get("session_id") and prev.get(p.get("name")):
            lead["session_id"] = prev[p["name"]]


def _log_hourly(dir, cfg, marker, msg):
    """Log msg at most once an hour (the marker file in dir holds the time of the last one)."""
    mark = Path(dir) / marker
    try:
        if cfg.now() - float(mark.read_text()) < 3600:
            return
    except (OSError, ValueError):
        pass
    _log(dir, cfg, msg)
    try:
        mark.write_text(str(cfg.now()))
    except OSError:
        pass


ZERO_WAIT = 50   # seconds between the two ticks that must both see a running server with no projects


def _zero_projects(dir, cfg, old):
    """A running server shows no projects. The old snapshot is replaced (True) only when an earlier tick at least
    ZERO_WAIT seconds ago saw the same: a shutdown, with its sessions dying one by one, never spans two ticks."""
    mark = Path(dir) / "zero_since"
    now = cfg.now()
    try:
        first = float(mark.read_text())
    except (OSError, ValueError):
        first = None
    if first is None or now < first:
        try:
            mark.write_text(str(now))
        except OSError:
            pass
        return False
    return now - first >= ZERO_WAIT


def tick(dir, cfg=None, run=_run):
    """One LaunchAgent tick: restore when a newer boot found an unrestored snapshot, else snapshot. Always 0."""
    cfg = cfg or default_cfg()
    if os.environ.get("TC_RESTORE") == "0" or (Path(dir) / "restore.off").exists():
        return 0
    try:
        Path(dir).mkdir(parents=True, exist_ok=True)
        lock = open(Path(dir) / "tick.lock", "a+")
    except OSError:
        return 0
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
        try:
            boot = boot_time(run)
            if boot is None:
                _log_hourly(dir, cfg, "boot-warn", "boot time unreadable")
                return 0
            old = load(dir)
            if old and _newer_boot(old.get("boot"), boot) and not old.get("restored"):
                do_restore(dir, old, cfg)
                return 0
            snap = snapshot(run=run, tmux=cfg.tmux, now=cfg.now(),
                            on_error=lambda e: _log_hourly(dir, cfg, "snapshot-warn", f"snapshot error: {type(e).__name__}: {e}"))
            zero = Path(dir) / "zero_since"
            if not snap:   # the server is down (or the read failed): the old snapshot stays, and the zero clock restarts
                zero.unlink(missing_ok=True)
                return 0
            _carry_session_ids(old, snap)
            names = lambda s: sorted(p.get("name") for p in (s or {}).get("projects") or [])
            if not snap["projects"] and old and old.get("projects"):
                if not _zero_projects(dir, cfg, old):
                    return 0
                saved = _write(dir, snap)   # the user closed everything: the empty state replaces it
            else:
                zero.unlink(missing_ok=True)
                saved = save(dir, snap)
            if saved and names(snap) != names(old):
                _log(dir, cfg, f"snapshot {len(snap['projects'])} projects")
        except Exception as e:   # a tick never raises into launchd
            _log(dir, cfg, f"tick error: {type(e).__name__}: {e}")
    return 0


def _status_lines(dir):
    import restore_schedule
    snap = load(dir)
    if not snap:
        return ["no snapshot"]
    names = ", ".join(p.get("name", "?") for p in snap.get("projects") or []) or "none"
    saved = snap.get("saved_at")
    age = restore_schedule._age(time.time() - saved) if isinstance(saved, (int, float)) else "unknown"
    return [f"snapshot age {age}, boot {snap.get('boot')}, restored {bool(snap.get('restored'))}, projects: {names}"]


def main(argv, **seams):
    """CLI: tick | snapshot [--print] | again | status | schedule install|status|uninstall. Returns the exit code."""
    ap = argparse.ArgumentParser(prog="agent-board restore", description="Snapshot the agent-board tmux server and restore it after a reboot.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick", help="snapshot, or restore after a newer boot (the LaunchAgent runs this every 60 s)")
    sp = sub.add_parser("snapshot", help="take a snapshot now and save it")
    sp.add_argument("--print", action="store_true", dest="print_only", help="print the snapshot JSON, do not save")
    sub.add_parser("again", help="clear 'restored' so the next tick restores again")
    sub.add_parser("status", help="print the snapshot's age, boot and projects")
    sc = sub.add_parser("schedule", help="manage the LaunchAgent")
    sc.add_argument("action", choices=["install", "status", "uninstall"])
    a = ap.parse_args(argv)
    d = restore_dir()
    if a.cmd == "tick":
        return tick(d, **seams)
    if a.cmd == "snapshot":
        snap = snapshot()
        if snap is None:
            print("no snapshot: tmux server not running", file=sys.stderr)
            return 1
        if a.print_only:
            print(json.dumps(snap, indent=1))
            return 0
        print(f"saved {len(snap['projects'])} projects" if save(d, snap) else "not saved (a guard kept the old snapshot)")
        return 0
    if a.cmd == "again":
        last = load_file(d, "last-restore.json")
        boot = boot_time(seams.get("run", _run))
        snap = last if last is not None and boot is not None else load(d)
        if not snap:
            print("no snapshot", file=sys.stderr)
            return 1
        snap["restored"] = False
        if snap is last:   # replay the last restore: make its boot older than this one so the next tick restores it
            snap["boot"] = min(snap.get("boot") or boot, boot - BOOT_SLACK - 1)
        print("will restore on the next tick" if _write(d, snap) else "could not write the snapshot")
        return 0
    if a.cmd == "status":
        print("\n".join(_status_lines(d)))
        return 0
    import restore_schedule
    return restore_schedule.main(a.action)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
