#!/usr/bin/env python3
"""LaunchAgent for `tmux-ctl metrics weekly`: runs Mondays at 09:00 local time (no run at load).

install(), uninstall() and status() return lists of lines. Off macOS each raises MacOnly (message
"macOS only", .code == 2); main(cmd) catches it, prints the message and returns the exit code 2.
Seams: HOME (plist), TC_STATE (agent base), AS_LAUNCHCTL
(launchctl command), AS_BIN_DIR (the dir holding the tmux-ctl beside this checkout).
"""
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_env  # noqa: E402

LABEL = "com.user.agent-board-analytics"
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
    return tc_env.agent_base() / "analytics.launchd.log"


def _runs_path():
    """runs.jsonl of the checkout beside this file (the one launchd runs); no git calls."""
    return Path(__file__).resolve().parent.parent / "docs" / "superpowers" / "metrics" / "runs.jsonl"


def _last_run():
    last = None
    try:
        for line in _runs_path().read_text().splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("kind") == "analytics":
                last = d
    except OSError:
        pass
    return f"last run: {last.get('at')} {last.get('outcome')}" if last else "last run: none"


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


def plist_text(cli_path, home, log):
    env = {"PATH": f"{home}/.local/bin:/opt/homebrew/bin:{home}/.bun/bin:/usr/bin:/bin",
           "LANG": os.environ.get("LANG") or "en_US.UTF-8"}
    # The 85% weekly-usage guard finds the statusline tap under the state dir: pin it for launchd.
    if os.environ.get("TC_STATE"):
        env["TC_STATE"] = os.environ["TC_STATE"]
    elif os.environ.get("TMPDIR"):
        env["TMPDIR"] = os.environ["TMPDIR"]
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(cli_path), "metrics", "weekly"],
        "StartCalendarInterval": {"Weekday": 1, "Hour": 9, "Minute": 0},
        "WorkingDirectory": str(home),
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
    return lines + [f"installed {plist}: metrics weekly on Mondays at 09:00"]


def uninstall():
    _check_platform()
    plist = _plist_path()
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if plist.exists():
        plist.unlink()
        return [f"removed {plist}"]
    return ["not installed"]


def status():
    _check_platform()
    r = _launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    lines = ["loaded" if r.returncode == 0 else "not loaded"]
    if os.environ.get("TC_ANALYTICS") == "0":
        lines.append("off: TC_ANALYTICS=0")
    if (tc_env.agent_base() / "analytics.off").exists():
        lines.append("off: analytics.off")
    lines.append(_last_run())
    return lines


def main(cmd):
    """Run one subcommand, print its lines, return the exit code (2 off macOS, 1 on failure, else 0)."""
    fn = {"install": install, "uninstall": uninstall, "status": status}.get(cmd)
    if fn is None:
        print("usage: metrics schedule install|status|uninstall", file=sys.stderr)
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
