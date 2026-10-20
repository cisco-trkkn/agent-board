#!/usr/bin/env python3
"""paneclass: what a tmux pane is doing (claude working/waiting/ready, a shell, a program).

Shared by tmux-dash (server.py) and the handoff relay (relay.py), so both read panes the same way.
CLI: paneclass.py status <pane-id>   -> prints "<kind> <status>"
"""
import os
import re
import shutil
import shlex
import subprocess
import sys
from pathlib import Path

SHELLS = {"zsh", "bash", "sh", "fish", "-zsh", "-bash"}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+")
WAITING_RE = re.compile(
    r"Do you want to|Would you like to|\(y/n\)|❯\s*1\.\s*Yes|Allow this|Press Enter to continue|Enter to confirm",
    re.I,
)
WORKING_RE = re.compile(r"esc to interrupt", re.I)
SEP = "~|~"   # printable: tmux 3.4 on Linux prints control characters as octal escapes (\037) in list output


INPUT_RE = re.compile(r"^\s*[│|]?\s*[>❯]\s?(.*?)\s*[│|]?\s*$")
RULE_RE = re.compile(r"^\s*[─━]{10,}")
MENU_RE = re.compile(r"^\d+\.\s")


def input_has_text(rows):
    """True when Claude's input line holds text the user typed.

    Claude Code 2.1.x draws `❯ <text>` on the line right after a full-width `─` rule (an agent list may sit
    below); older versions draw `│ > <text> │` in a box. Scans the last ~30 rows for the lowest such line.
    """
    tail = rows[-30:]
    for n in range(len(tail) - 1, -1, -1):
        m = INPUT_RE.match(tail[n])
        if not m:
            continue
        boxed = tail[n].lstrip()[:1] in ("│", "|")
        if not boxed and not (n > 0 and RULE_RE.match(tail[n - 1])):
            continue
        txt = m.group(1)
        if MENU_RE.match(txt):   # a numbered permission menu, not typing
            continue
        return bool(txt) and not txt.startswith('Try "')   # the greyed placeholder is not input
    return False


def classify(cmd, rows, bell):
    """kind: claude | shell | program ; status: waiting | working | ready | idle | running"""
    is_claude = bool(VERSION_RE.match(cmd)) or "claude" in cmd.lower()
    # Claude draws its prompts and spinner at the bottom; older scrollback may quote prompt text.
    tail = "\n".join(rows[-12:])
    if cmd in SHELLS:
        return "shell", "idle"
    if is_claude:
        if WORKING_RE.search(tail):  # no spinner while a prompt is open
            return "claude", "working"
        if WAITING_RE.search(tail):
            return "claude", "waiting"
        # Claude also rings the bell when it finishes; a real prompt is caught by WAITING_RE above.
        return "claude", "ready"
    return "program", "waiting" if bell else "running"


RESOLVER = Path(__file__).resolve().parent.parent / "bin" / "_tc_bins.zsh"


def tmux_bin():
    """The tmux binary, in the order bin/_tc_bins.zsh uses: $TC_TMUX, ~/.local/bin/tmux if executable, tmux on PATH."""
    if os.environ.get("TC_TMUX"):
        return os.environ["TC_TMUX"]
    own = Path.home() / ".local" / "bin" / "tmux"
    if os.access(own, os.X_OK) and own.is_file():
        return str(own)
    return shutil.which("tmux") or str(own)


def tmux_cmd(extra=()):
    """The tmux command every agent-board caller runs, as bin/_tc_bins.zsh resolves it (the one place that decides:
    TC_TMUX for the binary; TMUX_DASH_TMUX_ARGS, else the server of $TMUX, else agent-board's own server).
    Without zsh or the resolver (a copied board/): ~/.local/bin/tmux plus TMUX_DASH_TMUX_ARGS. extra args (e.g.
    -S socket) go after; tmux lets the last -S/-L win."""
    try:
        r = subprocess.run(["zsh", "-f", "-c", 'source "$1" && print -rN -- "${TC_TMUX_CMD[@]}"', "_", str(RESOLVER)],
                           capture_output=True, text=True, timeout=10)
        words = [w for w in r.stdout.split("\0") if w]
        if r.returncode == 0 and words:
            return words + list(extra)
    except (OSError, subprocess.SubprocessError):
        pass
    base = [tmux_bin()]
    return base + shlex.split(os.environ.get("TMUX_DASH_TMUX_ARGS", "")) + list(extra)


def tmux_runner(extra=()):
    """A tmux(*args, check=False) -> stdout callable; extra args (e.g. -S socket) go before the command."""
    base = tmux_cmd(extra)

    def run(*args, check=False):
        r = subprocess.run(base + list(args), capture_output=True, text=True)
        if check and r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"tmux {args[0]} failed")
        return r.stdout

    return run


def pane_status(tmux, pane, lines=40):
    info = tmux("display", "-p", "-t", pane, f"#{{pane_current_command}}{SEP}#{{window_bell_flag}}", check=True).strip()
    cmd, _, bell = info.partition(SEP)
    rows = [l.rstrip() for l in tmux("capture-pane", "-p", "-J", "-t", pane, "-S", f"-{lines}").splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    return classify(cmd, rows, bell == "1")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "status":
        print(*pane_status(tmux_runner(), sys.argv[2]))
    else:
        print("usage: paneclass.py status <pane-id>", file=sys.stderr)
        sys.exit(2)
