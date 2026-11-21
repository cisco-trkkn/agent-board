#!/usr/bin/env python3
"""LaunchAgents for the trend scout: `scout poll` daily 06:00, `scout weekly` Sunday 07:00 and
`scout weekly --retry` Monday 07:00 (three plists serve the spec's two jobs). No run at load.

Same structure as discover_schedule.py. install(), uninstall() and status() return lists of lines.
Off macOS each raises MacOnly (message "macOS only", .code == 2); main(cmd) prints it and returns 2.
Seams: HOME (plists), TC_SCOUT_DIR (state dir, pinned into the env when set), AS_LAUNCHCTL, AS_BIN_DIR.
"""
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scout_sources  # noqa: E402

TIMEOUT = 30
# (name shown by status, label, calendar interval, arguments after the cli, launchd log, scout log)
JOBS = [
    ("poll", "com.user.agent-board-scout-poll", {"Hour": 6, "Minute": 0},
     ["scout", "poll"], "launchd-poll.log", "poll.log", "scout poll daily at 06:00"),
    ("weekly", "com.user.agent-board-scout-weekly", {"Weekday": 0, "Hour": 7, "Minute": 0},
     ["scout", "weekly"], "launchd-weekly.log", "weekly.log", "scout weekly on Sunday at 07:00"),
    ("weekly (Monday retry)", "com.user.agent-board-scout-weekly-retry", {"Weekday": 1, "Hour": 7, "Minute": 0},
     ["scout", "weekly", "--retry"], "launchd-weekly.log", "weekly.log", "scout weekly --retry on Monday at 07:00"),
]


class MacOnly(RuntimeError):
    code = 2


def _check_platform():
    if sys.platform != "darwin":
        raise MacOnly("macOS only")


def _home():
    return Path(os.environ.get("HOME") or Path.home())


def _plist_path(label, home=None):
    return Path(home or _home()) / "Library" / "LaunchAgents" / f"{label}.plist"


def _executable(p):
    return p.is_file() and os.access(p, os.X_OK)


def _cli_path(home):
    """~/.local/bin/tmux-ctl when executable, else the one beside this checkout; RuntimeError otherwise."""
    beside = Path(os.environ.get("AS_BIN_DIR") or Path(__file__).resolve().parent.parent / "bin")
    cands = [Path(home) / ".local" / "bin" / "tmux-ctl", beside / "tmux-ctl"]
    for c in cands:
        if _executable(c):
            return c
    raise RuntimeError("no executable tmux-ctl to schedule; checked " + ", ".join(str(c) for c in cands))


def plist_text(cli_path, home, job, log):
    _name, label, interval, args = job[:4]
    env = {"PATH": f"{home}/.local/bin:/opt/homebrew/bin:{home}/.bun/bin:/usr/bin:/bin",
           "LANG": os.environ.get("LANG") or "en_US.UTF-8"}
    # The 85% weekly-usage guard finds the statusline tap under the state dir: pin it for launchd.
    if os.environ.get("TC_STATE"):
        env["TC_STATE"] = os.environ["TC_STATE"]
    elif os.environ.get("TMPDIR"):
        env["TMPDIR"] = os.environ["TMPDIR"]
    if os.environ.get("TC_SCOUT_DIR"):
        env["TC_SCOUT_DIR"] = os.environ["TC_SCOUT_DIR"]
    root = str(Path(__file__).resolve().parent.parent)
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": [str(cli_path), *args],
        "StartCalendarInterval": dict(interval),
        "WorkingDirectory": root,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        "EnvironmentVariables": env,
    })


def _launchctl(*args):
    cmd = shlex.split(os.environ.get("AS_LAUNCHCTL") or "launchctl")
    try:
        return subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 127, "", str(e))


def install():
    _check_platform()
    home = _home()
    target = _cli_path(home)   # before anything is written
    sdir = scout_sources.scout_dir()
    sdir.mkdir(parents=True, exist_ok=True)
    uid = os.getuid()
    lines = []
    for job in JOBS:
        label = job[1]
        plist = _plist_path(label, home)
        plist.parent.mkdir(parents=True, exist_ok=True)
        if plist.exists():
            bak = plist.with_name(f"{plist.name}.bak-{datetime.now():%Y%m%d}")
            shutil.copy2(plist, bak)
            lines.append(f"backed up the old plist to {bak}")
        plist.write_bytes(plist_text(target, home, job, sdir / job[4]))
        _launchctl("bootout", f"gui/{uid}/{label}")   # not loaded yet is fine
        r = _launchctl("bootstrap", f"gui/{uid}", str(plist))
        if r.returncode != 0:
            raise RuntimeError(f"launchctl bootstrap failed for {label}: {(r.stderr or r.stdout).strip()}")
        lines.append(f"installed {plist}: {job[6]}")
    return lines


def uninstall():
    _check_platform()
    lines = []
    for job in JOBS:
        plist = _plist_path(job[1])
        _launchctl("bootout", f"gui/{os.getuid()}/{job[1]}")
        if plist.exists():
            plist.unlink()
            lines.append(f"removed {plist}")
    return lines or ["not installed"]


def _last_line(name):
    try:
        lines = [l for l in (scout_sources.scout_dir() / name).read_text().splitlines() if l.strip()]
    except OSError:
        lines = []
    return lines[-1] if lines else "none"


def status():
    _check_platform()
    lines = []
    for job in JOBS:
        r = _launchctl("print", f"gui/{os.getuid()}/{job[1]}")
        lines.append(f"{job[0]}: {'loaded' if r.returncode == 0 else 'not loaded'}")
    if os.environ.get("TC_SCOUT") == "0":
        lines.append("off: TC_SCOUT=0")
    if (scout_sources.scout_dir() / "off").exists():
        lines.append("off: off file")
    lines.append(f"last poll: {_last_line('poll.log')}")
    lines.append(f"last weekly: {_last_line('weekly.log')}")
    return lines


def main(cmd):
    """Run one subcommand, print its lines, return the exit code (2 off macOS, 1 on failure, else 0)."""
    fn = {"install": install, "uninstall": uninstall, "status": status}.get(cmd)
    if fn is None:
        print("usage: scout schedule install|status|uninstall", file=sys.stderr)
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
