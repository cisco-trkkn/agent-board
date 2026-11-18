"""LaunchAgent for `agent-board restore tick`: runs at load and every 60 s (spec §4).

install(), uninstall() and status() return lists of lines. Off macOS each raises MacOnly (message
"macOS only", .code == 2); main(cmd) catches it, prints the message and returns the exit code 2.
Seams: HOME (plist and state dir), TC_STATE (state dir), RS_LAUNCHCTL (launchctl command).
"""
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import tc_env

LABEL = "com.user.agent-board-restore"
TIMEOUT = 30


class MacOnly(RuntimeError):
    code = 2


def _check_platform():
    if sys.platform != "darwin":
        raise MacOnly("macOS only")


def _home():
    return Path(os.environ.get("HOME") or Path.home())


def _plist_path(home=None):
    return Path(home or _home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _log_path():
    return tc_env.agent_base() / "restore" / "launchd.log"


def _cli_path(home):
    """~/.local/bin/agent-board when executable, else the one beside this checkout (never a bare worktree
    path blindly: worktree_safety raises RuntimeError when neither is executable)."""
    import worktree_safety
    return worktree_safety.agent_board_path(home)


def plist_text(cli_path, home, log):
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(cli_path), "restore", "tick"],
        "RunAtLoad": True,
        "StartInterval": 60,
        "AbandonProcessGroup": True,   # else launchd kills the board, ttyd and caffeinate the tick started
        "WorkingDirectory": str(home),
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        "EnvironmentVariables": {
            "PATH": f"{home}/.local/bin:/opt/homebrew/bin:{home}/.bun/bin:/usr/bin:/bin",
            "LANG": os.environ.get("LANG") or "en_US.UTF-8"},   # the tmux server started under launchd gives every pane this
    })


def _launchctl(*args):
    cmd = shlex.split(os.environ.get("RS_LAUNCHCTL") or "launchctl")
    try:
        return subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 127, "", str(e))


def install():
    _check_platform()
    home = _home()
    target = _cli_path(home)   # before anything is written
    plist = _plist_path(home)
    log = _log_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if plist.exists():
        bak = plist.with_name(f"{plist.name}.bak-{datetime.now():%Y%m%d}")
        shutil.copy2(plist, bak)
        lines.append(f"backed up the old plist to {bak}")
    plist.write_bytes(plist_text(target, home, log))
    uid = os.getuid()
    _launchctl("bootout", f"gui/{uid}/{LABEL}")   # not loaded yet is fine
    r = _launchctl("bootstrap", f"gui/{uid}", str(plist))
    if r.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {(r.stderr or r.stdout).strip()}")
    return lines + [f"installed {plist}: restore tick at load and every 60 s"]


def uninstall():
    _check_platform()
    plist = _plist_path()
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    lines = []
    if plist.exists():
        plist.unlink()
        lines.append(f"removed {plist}")
    if _mark_restored():
        lines.append("marked the snapshot restored, so a later install does not replay it")
    return lines or ["not installed"]


def _mark_restored():
    """Mark an existing, unrestored snapshot restored; True when it changed."""
    import restore
    d = restore.restore_dir()
    snap = restore.load(d)
    if not snap or snap.get("restored"):
        return False
    snap["restored"] = True
    return restore._write(d, snap)


def _age(sec):
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    return f"{sec // 3600}h{sec % 3600 // 60:02d}m"


def status():
    _check_platform()
    r = _launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    lines = ["loaded" if r.returncode == 0 else "not loaded"]
    import restore
    snap = restore.load(restore.restore_dir())
    if not snap:
        return lines + ["no snapshot"]
    names = ", ".join(p.get("name", "?") for p in snap.get("projects", [])) or "none"
    saved = snap.get("saved_at")
    age = _age(time.time() - saved) if isinstance(saved, (int, float)) else "unknown"
    return lines + [f"snapshot age {age}, boot {snap.get('boot')}, projects: {names}"]


def main(cmd):
    """Run one subcommand, print its lines, return the exit code (2 off macOS, 1 on failure, else 0)."""
    fn = {"install": install, "uninstall": uninstall, "status": status}.get(cmd)
    if fn is None:
        print("usage: restore schedule install|status|uninstall", file=sys.stderr)
        return 2
    try:
        print("\n".join(fn()))
    except MacOnly as e:
        print(e)
        return e.code
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    return 0
