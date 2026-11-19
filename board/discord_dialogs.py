"""discord_dialogs: every Claude Code dialog on the tmux server, mirrored to Discord as buttons.

scan(sessions, now, run) reads each waiting `claude` pane with `tmux-ctl dialog <pane id> show`, writes one `dialog` op per distinct
dialog (key: pane number plus a hash of the dialog's lines) to the project's outbox, or to the ops dir when the session has no channel,
and edits a message to `answered at the terminal` when its dialog left the screen. State: <agent_base>/dialogs/state.json under its own
flock (state.lock); never the ops-state lock. `run(argv) -> str` raises on a non-zero exit (server.run_script).
Test: tests/test_discord_dialogs.py."""
import contextlib
import fcntl
import hashlib
import json
import os
import sys
from pathlib import Path

import discord_feed
import tc_env

BIN = Path(__file__).resolve().parent.parent / "bin"
BODY_MAX = 1500      # PROMPT_MAX in tools/discord-bridge/bridge.js
TEXT_MAX = 2000      # a Discord message; the bridge slices at this, which would cut the closing code fence
LABEL_MAX = 80
OPTIONS_MAX = 20     # 4 rows of 5; the fifth row holds Submit and Reply
QUESTION_MAX = 300
ANSWERED = "answered at the terminal"
NOT_PARSED = "(dialog not parsed)"
_NONE = "dialog: none in"   # stderr of `tmux-ctl dialog <win> show` when the pane shows no dialog (tools/lib/dialog.zsh)
ERROR = "error"


def key_of(pane, lines):
    """p<pane number>-<first 16 hex of sha1 of the lines joined by newlines>; pane `%12` -> `p12-…`."""
    return f"p{pane.lstrip('%')}-{hashlib.sha1(chr(10).join(lines).encode('utf-8')).hexdigest()[:16]}"


def _show(run, pane):
    """The parsed JSON of the dialog showing in the pane; None when it shows none; ERROR for any other failure (copy mode, a pane
    that is gone, a timeout, output that is not a dialog object), so one pane never aborts the scan."""
    try:
        out = run([str(BIN / "tmux-ctl"), "dialog", pane, "show"])
    except Exception as e:  # noqa: BLE001 -- run_script raises RuntimeError or subprocess.TimeoutExpired
        return None if str(e).startswith(_NONE) else ERROR
    try:
        d = json.loads(out)
    except ValueError:
        return ERROR
    if not (isinstance(d, dict) and isinstance(d.get("lines"), list) and d["lines"] and all(isinstance(l, str) for l in d["lines"])
            and isinstance(d.get("options", []), list) and all(isinstance(o, dict) and "n" in o for o in d.get("options", []))):
        return ERROR
    return d


def _one_line(s, n):
    return " ".join(str(s).split())[:n]


def header(project, window, show):
    icon = "🔐" if show.get("kind") == "permission" else "❓"
    return f"{icon} {project} · {window}: {_one_line(show.get('question') or '', QUESTION_MAX)}"


def _body(lines, limit):
    """The lines for the code block: whole lines up to `limit` characters, then `… (<n> more lines)`; a first line longer than
    the limit is cut inside the line. A run of three backticks is broken so it cannot close the block (as bridge.js does)."""
    lines = [l.replace("```", "`​`​`") for l in lines]
    if len("\n".join(lines)) <= limit:
        return "\n".join(lines)
    n = total = 0
    for l in lines:
        nxt = total + (1 if n else 0) + len(l)
        if nxt > limit:
            break
        total, n = nxt, n + 1
    if n == 0:
        return lines[0][:limit] + (f"\n… ({len(lines) - 1} more lines)" if len(lines) > 1 else "")
    return "\n".join(lines[:n] + [f"… ({len(lines) - n} more lines)"])


def _button(key, suffix, label, style):
    return {"label": label[:LABEL_MAX], "style": style, "custom_id": f"ab:dlg:{key}:{suffix}"}


def message(key, head, show):
    """(text, rows) of the dialog message: the header, the dialog's lines in a code block, one button per option (a toggle for a
    multi-select, red for a permanent row), then Submit for a multi-select and Reply when the dialog takes free text."""
    opts = show.get("options") or []
    multi = bool(show.get("multi"))
    buttons = [_button(key, f"t{o['n']}" if multi else str(o["n"]), f"{o['n']}. {o.get('label', '')}",
                       4 if o.get("permanent", True) and not multi else 2) for o in opts[:OPTIONS_MAX]]
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    tail = ([_button(key, "submit", "Submit", 1)] if multi else []) + ([_button(key, "reply", "Reply", 1)] if show.get("other") else [])
    if tail:
        rows.append(tail)
    more = f"\n… {len(opts) - OPTIONS_MAX} more options: answer at the terminal" if len(opts) > OPTIONS_MAX else ""
    frame = len(head) + len("\n```\n") + len("\n```") + len(more)
    return f"{head}\n```\n{_body(show['lines'], min(BODY_MAX, TEXT_MAX - frame - 30))}\n```{more}", rows


def target_dir(project):
    """Where a dialog of this session is posted: the project's own outbox dir when it has a channel, else the ops dir when the
    ops bot is configured (its bridge sends `dialog` ops to #approvals), else None."""
    if discord_feed.channel_of(project):
        return tc_env.discord_dir(project)
    import discord_ops   # here, not at the top: discord_ops imports discord_controls, which will import this module
    return tc_env.ops_dir() if discord_ops.configured() else None


def _warn(what, e):
    print(f"discord_dialogs: {what}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def _panes(sessions):
    """(pane id, project, window name, pane) of every pane; `sessions` is build_state()["sessions"]."""
    for s in sessions or []:
        for w in s.get("windows") or []:
            for p in w.get("panes") or []:
                if p.get("id"):
                    yield p["id"], s.get("name") or "", w.get("name") or "", p


def _waiting(pane):
    return pane.get("kind") == "claude" and pane.get("status") == "waiting"


def _post(dialogs, key, pane, project, window, show, now):
    if key in dialogs:
        return
    d = target_dir(project)
    if d is None:
        return
    head = header(project, window, show)
    text, rows = message(key, head, show)
    discord_feed.outbox_write(d, {"op": "dialog", "key": key, "text": text, "rows": rows, "mention_user": True})
    dialogs[key] = {"pane": pane, "window": window, "project": project, "dir": str(d), "kind": show["kind"], "show": show,
                    "header": head, "ts": now}


def _raw(pane):
    """The stand-in `show` result of a waiting pane whose dialog does not parse: its preview rows, free text only."""
    lines = [r for r in pane.get("preview") or [] if isinstance(r, str)]
    return {"kind": "raw", "question": NOT_PARSED, "options": [], "multi": False, "other": True, "lines": lines} if lines else None


def _scan(dialogs, sessions, now, run):
    cache, live, panes = {}, {}, {}   # pane id -> show result; pane id -> the key on its screen now, or ERROR; pane id -> pane

    def show(pid):
        if pid not in cache:
            cache[pid] = _show(run, pid)
        return cache[pid]

    found = []
    for pid, project, window, pane in _panes(sessions):
        panes[pid] = pane
        if not _waiting(pane):
            continue
        got = show(pid)
        if got is ERROR:
            live[pid] = ERROR
            continue
        got = got if got is not None else _raw(pane)
        if got is None:
            continue
        live[pid] = key_of(pid, got["lines"])
        found.append((live[pid], pid, project, window, got))
    _sweep(dialogs, live, panes, show)   # before the posts: a changed dialog's old message is closed above its new one
    for key, pid, project, window, got in found:
        try:
            _post(dialogs, key, pid, project, window, got, now)
        except Exception as e:  # noqa: BLE001 -- one pane's failed post never stops the others; it is retried next tick
            _warn(f"post failed ({project} {window} {pid})", e)


def _sweep(dialogs, live, panes, show):
    """Edit and drop every known dialog that is no longer on its pane's screen. A pane whose `show` failed keeps its keys this
    tick; a pane that no longer classifies as waiting is shown once more, so a dialog the classifier missed is not called answered."""
    for key, rec in list(dialogs.items()):
        if not (isinstance(rec, dict) and rec.get("dir") and rec.get("header")):   # a damaged record: no message to edit
            del dialogs[key]
            continue
        pid = rec.get("pane")
        if pid in panes and pid not in live and rec.get("kind") != "raw":
            got = show(pid)
            live[pid] = ERROR if got is ERROR else key_of(pid, got["lines"]) if got else None
        if live.get(pid) in (ERROR, key):
            continue
        try:
            discord_feed.outbox_write(Path(rec["dir"]), {"op": "edit", "key": key, "text": f"{rec['header']}\n{ANSWERED}"})
        except Exception as e:  # noqa: BLE001
            _warn(f"edit failed ({key})", e)
            continue
        del dialogs[key]


def state_path():
    return tc_env.agent_base() / "dialogs" / "state.json"


@contextlib.contextmanager
def _locked():
    """The dialog state (key -> record) under flock on state.lock; saved with a temp file and os.replace on the way out."""
    sp = state_path()
    sp.parent.mkdir(parents=True, exist_ok=True)
    with open(sp.with_name("state.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            st = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        dialogs = st.get("dialogs") if isinstance(st, dict) else None
        dialogs = dialogs if isinstance(dialogs, dict) else {}
        try:
            yield dialogs
        finally:
            tmp = sp.with_name(sp.name + ".tmp")
            tmp.write_text(json.dumps({"dialogs": dialogs}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, sp)


def scan(sessions, now, run):
    """One pass over every waiting claude pane of `sessions` (build_state()["sessions"]): post new dialogs, retire answered ones."""
    with _locked() as dialogs:
        _scan(dialogs, sessions, now, run)
