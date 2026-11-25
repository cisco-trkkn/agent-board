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
# a teammate's own pane while its permission request sits with the lead: a boxed `✽ Waiting for team lead approval` title
WAITING_ON_LEAD_RE = re.compile(r"^\s*[│|]\s*\S?\s*Waiting for team lead approval\s*[│|]?\s*$", re.M)
WAITING_ON_LEAD = "waiting-on-lead"
WORKING_RE = re.compile(r"esc to interrupt", re.I)   # Claude Code before 2.1.316
# 2.1.316+: `<glyph> <Word>… (<elapsed> · ↓ <n> tokens)`; the whole line, so prose quoting one does not match
SPINNER_RE = re.compile(r"^[·✢✳✶✻✽*]\s+\S.*…\s*\((?:[^()]*·\s*)?\d+\s*[hms]\b[^)]*\)?\s*$")   # the bracket may start with hook text: `(running Stop hooks… 0/4 · 2s`
WRAP_TAIL_STOP_RE = re.compile(r"^(?:[·✢✳✶✻✽*⏺⎿│╭╰─━]|\s)")   # a row starting with these (or blank/indented) is not the rest of a wrapped spinner row
SPINNER_GLYPHS = "·✢✳✶✻✽*"
SPINNER_FIRST_RE = re.compile(r"^[·✢✳✶✻✽*]\s+\S.*…\s*$")   # first frame of a turn, before the "(elapsed" part appears
TIP_RE = re.compile(r"^\s*⎿\s+Tip:")   # the tip row a turn starts with, under a first-frame spinner
TASKLIST_RE = re.compile(r"^\s+(?:⎿\s*\xa0?\s*[◼◻✔☐☒]|[◼◻✔☐☒]|…\s+\+\d)")   # task-list rows under a task-label spinner: `  ⎿  ◼ …`, `     ◻ …`, `      … +13 pending`
TEAM_ROW_RE = re.compile(r"^busy \d+ · ready \d+")   # the teammate status row, at column 0, above the input rule
SEP = "~|~"   # printable: tmux 3.4 on Linux prints control characters as octal escapes (\037) in list output


INPUT_RE = re.compile(r"^\s*[│|]?\s*[>❯]\s?(.*?)\s*[│|]?\s*$")
RULE_RE = re.compile(r"^\s*[─━]{10,}")
MENU_RE = re.compile(r"^\d+\.\s")
STATUS_TTL = 45   # seconds: an agent-status file older than this is ignored (the mod's heartbeat is 15 s)
MOD_STATES = {"busy": "working", "needs-you": "waiting", "ready": "ready"}


def status_dir():
    """Where claude/plugin/mods/agent-status.js writes one <session_id>.json per session."""
    return tc_env.state_dir() / "agent-status"


def mod_records(now=None, d=None):
    """pane id -> the parsed agent-status file (a dict), fresh files only, the newest per pane: one directory listing per call."""
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
            best[pane] = (rec, upd)
    return {p: r for p, (r, _) in best.items()}


def mod_states(now=None, d=None):
    """pane id -> board status from fresh agent-status files."""
    return {p: MOD_STATES[r["state"]] for p, r in mod_records(now, d).items()}


SGR_RE = re.compile(r"\x1b\[([0-9;:]*)m")
ANSI_RE = re.compile(r"\x1b\[[0-9;:?]*[ -/]*[@-~]")


def _plain_and_dim(row):
    """(row without escape sequences, per-character 'drawn dim' flags). Dim is SGR 2, cleared by 0 or 22."""
    plain, dim, on, pos = [], [], False, 0
    for m in ANSI_RE.finditer(row):
        for ch in row[pos:m.start()]:
            plain.append(ch)
            dim.append(on)
        pos = m.end()
        sgr = SGR_RE.fullmatch(m.group())
        if sgr:
            params, i = sgr.group(1).split(";"), 0
            while i < len(params):
                head = params[i].split(":")[0]
                i += 1
                code = int(head) if head.isdigit() else 0
                if code in (38, 48, 58):   # extended colour: its parameters are not SGR codes
                    if ":" not in params[i - 1] and i < len(params):   # `;` form: 5;n or 2;r;g;b follow
                        i += 2 if params[i] == "5" else 4
                elif code in (0, 22):
                    on = False
                elif code == 2:
                    on = True
    for ch in row[pos:]:
        plain.append(ch)
        dim.append(on)
    return "".join(plain), dim


def input_has_text(rows):
    """True when Claude's input line holds text the user typed.

    Claude Code 2.1.x draws `❯ <text>` on the line right after a full-width `─` rule (an agent list may sit
    below); older versions draw `│ > <text> │` in a box. Scans the last ~30 rows for the lowest such line.
    Rows may carry escape sequences (capture-pane -e): text drawn entirely dim is Claude's suggested prompt, not input.
    """
    tail = [_plain_and_dim(r) for r in rows[-30:]]
    dims = [d for _, d in tail]
    tail = [t for t, _ in tail]
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
        if txt and all(dims[n][i] for i in range(m.start(1), m.end(1)) if not tail[n][i].isspace()):
            return False   # a dimmed suggested prompt (Claude Code 2.1.330)
        return bool(txt) and not txt.startswith('Try "')   # the greyed placeholder is not input
    return False


def spinner_live(rows):
    """True when the lowest spinner line is in the live area above the input box's rule.

    Rows between the spinner and the rule may be blank or indented (a tip, its wrapped line, a task list); a row at
    column 0 (a finished line, `⏺` output, an open prompt) means the spinner is transcript. The first-frame form
    (`✢ Thinking…`, no parenthesis) is live only when the rows before the rule are blank, `⎿ Tip:` rows, a tip's
    indented continuation lines directly after it, or task-list rows; the `busy N · ready N` teammate row is skipped for both forms; any other indented row means it is transcript."""
    for n in range(len(rows) - 1, -1, -1):
        row, skip = rows[n], 1
        if row[:1] in SPINNER_GLYPHS and (row.count("(") > row.count(")") or not (SPINNER_FIRST_RE.match(row) or SPINNER_RE.match(row))) \
                and n + 1 < len(rows) and rows[n + 1] and not WRAP_TAIL_STOP_RE.match(rows[n + 1]):
            for joined in (row + " " + rows[n + 1], row + rows[n + 1]):   # a spinner row wrapped by the pane width, at any break
                if SPINNER_FIRST_RE.match(joined) or SPINNER_RE.match(joined):
                    row, skip = joined, 2
                    break
        first = bool(SPINNER_FIRST_RE.match(row))
        if not (first or SPINNER_RE.match(row)):
            continue
        in_tip = False   # the previous non-blank row was a tip row or its wrapped continuation
        for below in rows[n + skip:]:
            if RULE_RE.match(below):
                return True
            if not below.strip():
                in_tip = False
                continue
            if TEAM_ROW_RE.match(below):
                continue
            if first:
                tip = bool(TIP_RE.match(below))
                if tip or TASKLIST_RE.match(below):
                    in_tip = tip
                    continue
                if in_tip and below[0].isspace():
                    continue
                return False
            if not below[0].isspace():
                return False
        return not any(r.strip() for r in rows[n + skip:])   # no rule in view (a short capture): spinner at the bottom
    return False


def is_claude_cmd(cmd):
    return bool(VERSION_RE.match(cmd)) or "claude" in cmd.lower()


TASKS_HEAD_RE = re.compile(r"^ +\d+/\d+ tasks done")
TASKS_ROW_RE = re.compile(r"^  +\S")
DIVIDER = "─" * 10   # isdiv() in tools/lib/dialog.zsh: a row that starts with ten rule characters
TEAM_DIVIDER_RE = re.compile(r" @[A-Za-z0-9_.-]+ ─$")   # the teammate status divider, the last row of a pane with teammates
CURSOR_RE = re.compile(r"^\s*❯")


def _task_row(row):
    return bool(TASKS_ROW_RE.match(row)) and not CURSOR_RE.match(row) and not row.lstrip().startswith(DIVIDER)


def _above_tasklist(rows):
    """rows without a task list drawn as the last rows: a `N/M tasks done` row followed only by rows indented by two or more,
    none of them a cursor row or a divider, after a teammate status divider as the very last row is set aside (the rules of
    tasklist() and its caller in tools/lib/dialog.zsh). A session with tasks draws the list under an open prompt's footer, so
    the prompt can sit any number of rows above the bottom; above an input box the list is not the last rows and stays."""
    body = rows
    if rows and rows[-1].startswith(DIVIDER) and TEAM_DIVIDER_RE.search(rows[-1]):
        body = rows[:-1]
    for n in range(len(body) - 1, -1, -1):
        if TASKS_HEAD_RE.match(body[n]):
            if not all(_task_row(r) for r in body[n + 1:]):
                return rows
            n -= 1
            while n >= 0 and not rows[n].strip():
                n -= 1
            return rows[:n + 1]
    return rows


_WRAP_BREAK_RE = re.compile(r"^\s*(?:[─━╌│╭╰┌└]|$)")   # a blank row or a rule/box row never joins its neighbour


def _wrap_joined(rows):
    """rows plus each pair of adjacent text rows joined with one space: a key-hint footer that wraps at a narrow pane splits
    a phrase (`Enter to` / `resume`) across two rows. Pairs only; a blank row, a rule or a box row never joins."""
    out = list(rows)
    for a, b in zip(rows, rows[1:]):
        if not _WRAP_BREAK_RE.match(a) and not _WRAP_BREAK_RE.match(b):
            out.append(a.rstrip() + " " + b.lstrip())
    return out


def _waiting(tail_rows):
    return bool(WAITING_RE.search("\n".join(tail_rows)) or WAITING_RE.search("\n".join(_wrap_joined(tail_rows))))


def classify(cmd, rows, bell, mod=None):
    """kind: claude | shell | program ; status: waiting | working | ready | idle | running.
    mod: the pane's fresh agent-status state (mod_states()), preferred over pane text for a claude pane."""
    is_claude = is_claude_cmd(cmd)
    # Claude draws its prompts and spinner at the bottom; older scrollback may quote prompt text.
    tail_rows = _above_tasklist(rows)[-12:]
    tail = "\n".join(tail_rows)
    if cmd in SHELLS:
        return "shell", "idle"
    if is_claude:
        # the box is ~14 rows tall with the input box under it; it answers nothing here, the lead's own pane carries the dialog
        if WAITING_ON_LEAD_RE.search("\n".join(_above_tasklist(rows)[-20:])):
            return "claude", WAITING_ON_LEAD
        if mod:
            # a dialog the mod cannot see (subagent, sandbox network prompt) only shows in the pane: raise to waiting
            if mod != "waiting" and _waiting(tail_rows):
                return "claude", "waiting"
            return "claude", mod
        if WORKING_RE.search(tail) or spinner_live(rows[-30:]):  # no spinner while a prompt is open
            return "claude", "working"
        if _waiting(tail_rows):
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
