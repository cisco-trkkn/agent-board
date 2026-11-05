#!/usr/bin/env python3
"""paneclass: what a tmux pane is doing (claude working/waiting/ready, a shell, a program).

Shared by tmux-dash (server.py) and the handoff relay (relay.py), so both read panes the same way.
CLI: paneclass.py status <pane-id>   -> prints "<kind> <status>"
"""
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import tc_env  # noqa: E402

SHELLS = tc_env.SHELLS
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+")
WAITING_RE = re.compile(tc_env.PROMPT_PATTERN, re.I)
WORKING_RE = re.compile(r"esc to interrupt", re.I)   # Claude Code before 2.1.316
# 2.1.316+: `<glyph> <Word>… (<elapsed> · ↓ <n> tokens)`; the whole line, so prose quoting one does not match
SPINNER_RE = re.compile(r"^\s*\S\s+[\w-]+…\s*\(\d+\s*[hms]\b[^)]*\)?\s*$")
SPINNER_FIRST_RE = re.compile(r"^\s*\S\s+[\w-]+…\s*$")   # first frame of a turn, before the "(elapsed" part appears
SEP = "~|~"   # printable: tmux 3.4 on Linux prints control characters as octal escapes (\037) in list output


INPUT_RE = re.compile(r"^\s*[│|]?\s*[>❯]\s?(.*?)\s*[│|]?\s*$")
RULE_RE = re.compile(r"^\s*[─━]{10,}")
MENU_RE = re.compile(r"^\d+\.\s")
STATUS_TTL = 45   # seconds: an agent-status file older than this is ignored (the mod's heartbeat is 15 s)
MOD_STATES = {"busy": "working", "needs-you": "waiting", "ready": "ready"}


def status_dir():
    """Where claude/plugin/mods/agent-status.js writes one <session_id>.json per session."""
    return tc_env.state_dir() / "agent-status"


def mod_states(now=None, d=None):
    """pane id -> board status from fresh agent-status files: one directory listing per call."""
    now = time.time() if now is None else now
    d = status_dir() if d is None else Path(d)
    best = {}
    try:
        names = os.listdir(d)
    except OSError:
        return {}
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            rec = json.loads((d / name).read_text())
            pane, state, upd = rec["pane"], rec["state"], float(rec["updatedAt"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not isinstance(pane, str) or state not in MOD_STATES or not -5 < now - upd < STATUS_TTL:
            continue
        if pane not in best or upd > best[pane][1]:
            best[pane] = (MOD_STATES[state], upd)
    return {p: s for p, (s, _) in best.items()}


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


def spinner_live(rows):
    """True when the lowest spinner line is in the live area above the input box's rule.

    Rows between the spinner and the rule may be blank or indented (a tip, its wrapped line, a task list); a row at
    column 0 (a finished line, `⏺` output, an open prompt) means the spinner is transcript. The first-frame form
    (`✢ Thinking…`, no parenthesis) is only live with nothing but blank rows before the rule."""
    for n in range(len(rows) - 1, -1, -1):
        first = bool(SPINNER_FIRST_RE.match(rows[n]))
        if not (first or SPINNER_RE.match(rows[n])):
            continue
        for below in rows[n + 1:]:
            if RULE_RE.match(below):
                return True
            if below.strip() and (first or not below[0].isspace()):
                return False
        return not any(r.strip() for r in rows[n + 1:])   # no rule in view (a short capture): spinner at the bottom
    return False


def is_claude_cmd(cmd):
    return bool(VERSION_RE.match(cmd)) or "claude" in cmd.lower()


def classify(cmd, rows, bell, mod=None):
    """kind: claude | shell | program ; status: waiting | working | ready | idle | running.
    mod: the pane's fresh agent-status state (mod_states()), preferred over pane text for a claude pane."""
    is_claude = is_claude_cmd(cmd)
    # Claude draws its prompts and spinner at the bottom; older scrollback may quote prompt text.
    tail = "\n".join(rows[-12:])
    if cmd in SHELLS:
        return "shell", "idle"
    if is_claude:
        if mod:
            # a dialog the mod cannot see (subagent, sandbox network prompt) only shows in the pane: raise to waiting
            if mod != "waiting" and WAITING_RE.search(tail):
                return "claude", "waiting"
            return "claude", mod
        if WORKING_RE.search(tail) or spinner_live(rows[-30:]):  # no spinner while a prompt is open
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
    return classify(cmd, rows, bell == "1", mod_states().get(pane))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "status":
        print(*pane_status(tmux_runner(), sys.argv[2]))
    else:
        print("usage: paneclass.py status <pane-id>", file=sys.stderr)
        sys.exit(2)
