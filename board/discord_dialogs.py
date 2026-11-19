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
import re
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
_CHANGED = "dialog: the dialog in"   # stderr start of `press` when the screen no longer matches --expect (tools/lib/dialog.zsh)
REPLY_MAX = 1000
_N = re.compile(r"[1-9][0-9]?")
_C0 = re.compile(r"[\x00-\x1f\x7f]")


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
    if not (isinstance(d, dict) and isinstance(d.get("kind"), str) and isinstance(d.get("lines"), list) and d["lines"] and all(isinstance(l, str) for l in d["lines"])
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


FREE_TEXT = ("Type something.", "Type something", "Tell Claude what to change")   # the free-text rows, as tools/lib/dialog.zsh names them
CHAT = "Chat about this"   # in a multi-select it is not a checkbox: `dialog press` refuses to toggle it


def _buttonable(show):
    """The options that get a button: not the free-text row when the dialog takes text (Reply covers it), and in a multi-select
    not the `Chat about this` row either, so no button is one `tmux-ctl dialog … press` would refuse."""
    multi, other = bool(show.get("multi")), bool(show.get("other"))
    return [o for o in show.get("options") or []
            if not (other and o.get("label") in FREE_TEXT) and not (multi and o.get("label") == CHAT)]


def message(key, head, show):
    """(text, rows) of the dialog message: the header, the dialog's lines in a code block, one button per buttonable option (a
    toggle for a multi-select, red for a permanent row), then Submit for a multi-select and Reply when the dialog takes free text."""
    opts = _buttonable(show)
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
        if _record(dialogs, key, need_show=False) is None:   # a damaged record: no message to edit
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


def _record(dialogs, key, need_show=True):
    """dialogs[key] when it is a usable record (a message to edit, and for a press its pane and the `show` lines), else None."""
    rec = dialogs.get(key)
    if not (isinstance(rec, dict) and rec.get("dir") and rec.get("header")):
        return None
    if need_show and not (rec.get("pane") and isinstance((rec.get("show") or {}).get("lines"), list)):
        return None
    return rec


def _opt(rec, n):
    return next((o for o in (rec.get("show") or {}).get("options") or [] if isinstance(o, dict) and o.get("n") == n), None)


def _label(o):
    return _one_line(o.get("label", ""), LABEL_MAX)


def _finish(rec, key, dialogs, run, args, label, now):
    """Press through `tmux-ctl dialog <pane> press --expect <lines> <args>`, edit the message to the outcome, drop the key (every
    outcome: a press is never retried); returns the audit result."""
    argv = [str(BIN / "tmux-ctl"), "dialog", rec["pane"], "press", "--expect", "\n".join(rec["show"]["lines"]), *args]
    try:
        run(argv)
        result, text = f"pressed: {label}", f"→ {label} (from Discord)"
    except Exception as e:  # noqa: BLE001 -- any failure, TimeoutExpired included, is an outcome, never a retry
        first = (str(e).splitlines() or [""])[0] or "exit error"
        if first.startswith(_CHANGED):
            result, text = "changed", "the dialog changed; re-sent below"
        else:
            result, text = f"not pressed: {first}"[:200], f"⚠️ not pressed: {first}"[:300]
    try:
        discord_feed.outbox_write(Path(rec["dir"]), {"op": "edit", "key": key, "text": f"{rec['header']}\n{text}"})
    except Exception as e:  # noqa: BLE001 -- the press happened: the key still goes
        _warn(f"edit failed ({key})", e)
    del dialogs[key]
    return result


def click(d, user, cid, ev, run, now):
    """The audit result of one `ab:dlg:<key>:<suffix>` click event: presses (or refuses) under the state lock. Shapes: `<n>`,
    `<n>:confirm`, `submit` (with ev["picks"]); anything else is `ignored`. The caller has checked allowFrom."""
    parts = str(cid).split(":")
    if parts[:2] != ["ab", "dlg"] or not 4 <= len(parts) <= 5:
        return "ignored"
    key, suffix = parts[2], parts[3:]
    if suffix == ["submit"]:
        kind, n = "submit", None
    elif _N.fullmatch(suffix[0]) and suffix[1:] in ([], ["confirm"]):
        kind, n = "confirm" if len(suffix) == 2 else "tap", int(suffix[0])
    else:
        return "ignored"
    with _locked() as dialogs:
        rec = _record(dialogs, key)
        if rec is None:
            return "already answered"
        show = rec["show"]
        ok = {o["n"]: o for o in _buttonable(show) if isinstance(o.get("n"), int)}
        multi = bool(show.get("multi"))
        if kind == "submit":
            picks = ev.get("picks")
            if not (multi and isinstance(picks, list) and picks and len(set(picks)) == len(picks)
                    and all(type(p) is int and p in ok and not ok[p].get("permanent") for p in picks)):
                return "ignored"
            return _finish(rec, key, dialogs, run, [x for p in picks for x in ("--option", str(p))],
                           ", ".join(_label(ok[p]) for p in picks), now)
        o = ok.get(n)
        if o is None or multi:
            return "ignored"
        if kind == "tap" and o.get("permanent", True):
            return "needs confirm"
        if kind == "confirm" and not o.get("permanent", True):
            return "ignored"
        return _finish(rec, key, dialogs, run, ["--option", str(n)], _label(o), now)


def reply(d, user, ev, run, now):
    """The audit result of one `reply` event (the user's text answering the dialog `ev["key"]`); presses `--text`. The caller has
    checked allowFrom."""
    key = str(ev.get("key") or "")
    text = _C0.sub(" ", str(ev.get("text") or ""))[:REPLY_MAX]
    with _locked() as dialogs:
        rec = _record(dialogs, key)
        if rec is None:
            return "already answered"
        mid = ev.get("message_id")
        if mid is not None and rec.get("message_id") is not None and str(mid) != str(rec["message_id"]):
            return "ignored"
        if not rec["show"].get("other") or not text.strip():
            return "ignored"
        return _finish(rec, key, dialogs, run, ["--text", text], _one_line(text, LABEL_MAX), now)


def consume_event(d, ev, allow, run, now):
    """(audit action, audit target, result) for a dialog event of an events dir, or None when `ev` is not one (a `reply`, or a
    click on an `ab:dlg:` id). The one place that checks allowFrom for dialog events: a user outside `allow` gets `rejected`."""
    user, kind = str(ev.get("user") or ""), str(ev.get("type") or "")
    cid = str(ev.get("custom_id") or "")
    if kind == "reply":
        action, target = "dialog-reply", str(ev.get("key") or "")
        go = lambda: reply(d, user, ev, run, now)  # noqa: E731
    elif kind == "click" and cid.startswith("ab:dlg:"):
        action, target = "dialog", cid
        go = lambda: click(d, user, cid, ev, run, now)  # noqa: E731
    else:
        return None
    return action, target, go() if user in allow else "rejected"
