#!/usr/bin/env python3
"""improve_discord: the supervised improvement loop's only Discord poster (plan Task 12). Protected (docs/superpowers/improve/protected.txt).

Five card kinds and nothing else (spec §5, Global Constraints "Discord"): `awaiting_you`, `drafted` (class protected, not an adapter
draft), a guardrail `breach`, `achieved`, and the weekly digest line. The tick's hooks call `card(kind, payload)` and
`digest(store, tick_id)` (improve_eval.HOOK_MODULES); `improve_apply.sweep_drafts` calls `card("drafted", ...)`. Both hooks catch
everything, log to stderr and return False, because the tick writes the `achieved` event before it calls `card`.
Button custom ids are `ab:improve:<act>:<project>:<id>`, act in promote|reject|extend|approve|revert; `click` handles them
(routed from discord_controls, and by hand through `tmux-ctl improve click <act> <id>`).
Differences from dream_discord: the cards carry no files, a click acts on the proposals table (its state is the guard: a
second click on the same card is `stale`), and the project comes from the payload, TC_PROJECT or the git checkout name.
Test: tests/test_improve_discord.py."""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord_feed  # noqa: E402
import improve_apply  # noqa: E402
import improve_store  # noqa: E402
import tc_env  # noqa: E402

CID_RE = re.compile(r"^ab:improve:(promote|reject|extend|approve|revert):([A-Za-z0-9][A-Za-z0-9._-]*):(P\d+)$")
TEXT_MAX = 1900
CID_MAX = 100
BUTTONS_MAX = 5
ALLOWED = {"promote": {"awaiting_you"}, "reject": {"awaiting_you", "drafted"}, "extend": {"awaiting_you"},
           "approve": {"drafted"}, "revert": {"kept", "promoted"}}
PRIMARY, SECONDARY, DANGER = 1, 2, 4   # discord button styles, as dream_discord uses them
EXTEND_BY = 5
WEEK = 7 * 86400


def _log(what, e):
    print(f"improve_discord: {what} failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def _project(payload=None):
    import os
    p = (payload or {}).get("project") or os.environ.get("TC_PROJECT")
    if p:
        return p
    import improve
    return improve.project_name()


def _store(project):
    return improve_store.Store(project)


def _has_channel(project):
    return bool(discord_feed.channel_of(project))


def _write(project, op):
    discord_feed.outbox_write(tc_env.discord_dir(project), op)


def _post(text, tier, key, buttons=None, cmds=()):
    """A post op. Buttons are used only when every custom id fits; otherwise the text ends with the CLI commands."""
    if buttons and any(len(i) > CID_MAX for _, _, i in buttons):
        buttons = None
    tail = ("\n" + "\n".join(cmds)) if cmds and not buttons else ""
    op = {"op": "post", "text": text[:TEXT_MAX - len(tail)] + tail, "tier": tier, "mention_user": tier == "decision", "key": key}
    if buttons:
        op["buttons"] = [{"label": l, "style": s, "custom_id": i} for l, s, i in buttons]
    return op


def _cid(act, project, pid):
    return f"ab:improve:{act}:{project}:{pid}"


def _cli(act, pid):
    return f"tmux-ctl improve click {act} {pid}"


def _fmt(v):
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def _target(oid):
    """The outcome's target on the signal index (1 + completion.change), as text; '?' when its file is not found."""
    import improve
    for o in improve.load_outcomes():
        if o["id"] == oid:
            ch = (o.get("completion") or {}).get("change")
            return f"{1 + (ch if ch is not None else -0.25):.2f}"
    return "?"


def _o1():
    """`O1 <value> vs <target>` for the weekly digest; `O1 n/a vs target` when it cannot be worked out."""
    try:
        import improve
        import improve_eval
        import metrics
        o = next(x for x in improve.load_outcomes() if x["id"] == "O1")
        st = improve_eval.outcome_status(improve._runs(), o, improve.load_configs(), improve_eval.first_commit(o["_path"]))
        idx = st["signal"].get("index")
        return f"O1 {_fmt(idx) if idx is not None else 'n/a'} vs {_target('O1')}"
    except Exception as e:  # noqa: BLE001
        _log("o1", e)
        return "O1 n/a vs target"


# ---- cards ---------------------------------------------------------------------------------------------------------

def _awaiting(project, store, payload):
    pid = payload["id"]
    row = store.get(pid)
    if not row:
        return None
    text = f"🧪 {pid} {row['kind']} {row['target']}: trial {payload.get('reason') or row['reason'] or ''}"
    btn = [("Promote", PRIMARY, _cid("promote", project, pid)), ("Reject", DANGER, _cid("reject", project, pid)),
           (f"Extend trial by {EXTEND_BY}", SECONDARY, _cid("extend", project, pid))]
    return _post(text, "decision", f"improve-awaiting-{project}-{pid}", btn, [_cli(a, pid) for a in ("promote", "reject", "extend")])


def _drafted(project, store, payload):
    pid = payload["id"]
    row = store.get(pid)
    if not row or row["state"] != "drafted" or row["class"] != "protected" or row["reason"] == improve_apply.ADAPTER_DRAFT:
        return None
    text = f"🧪 {pid} {row['kind']} {row['target']}: protected, drafted as a spec. Approve merges the draft only."
    btn = [("Approve", PRIMARY, _cid("approve", project, pid)), ("Reject", DANGER, _cid("reject", project, pid))]
    return _post(text, "decision", f"improve-drafted-{project}-{pid}", btn, [_cli("approve", pid), _cli("reject", pid)])


def _breach(project, store, payload):
    kept = [k for k in (payload.get("kept") or []) if CID_RE.match(_cid("revert", "x", str(k)))]
    lines = [f"⚠️ guardrail breach: {payload.get('numbers') or payload.get('metric')}; trials reverted"]
    for pid in kept:
        row = store.get(pid)
        lines.append(f"↩️ {pid} {row['kind']} {row['target']}" if row else f"↩️ {pid}")
    btn = [(f"Revert {pid}", DANGER, _cid("revert", project, pid)) for pid in kept[:BUTTONS_MAX]]
    cmds = [_cli("revert", pid) for pid in kept]
    text = "\n".join(lines)
    if len(kept) > BUTTONS_MAX:   # a card holds five buttons: the rest are reverted from the CLI
        text += "\n" + "\n".join(_cli("revert", pid) for pid in kept[BUTTONS_MAX:])
    return _post(text, "decision", f"improve-breach-{project}-{int(store.now())}", btn or None, cmds)


def _achieved(project, store, payload):
    idx = payload.get("index")
    text = f"🎯 {payload['id']} achieved: {_fmt(idx) if idx is not None else 'n/a'} vs {_target(payload['id'])}"
    return _post(text, "progress", f"improve-achieved-{project}-{payload['id']}")


KINDS = {"awaiting_you": _awaiting, "drafted": _drafted, "breach": _breach, "achieved": _achieved}


def card(kind, payload):
    """Write one card. True when it was written; never raises (a failure is logged and returns False)."""
    try:
        build = KINDS.get(kind)
        if not build or not isinstance(payload, dict):
            return False
        project = _project(payload)
        if not _has_channel(project):
            return False
        op = build(project, _store(project), payload)
        if not op:
            return False
        _write(project, op)
        return True
    except Exception as e:  # noqa: BLE001 -- the tick already recorded the transition; a card must never end it
        _log(f"card {kind}", e)
        return False


# ---- the weekly digest -----------------------------------------------------------------------------------------------

def _events(store, kind, since):
    import json
    c = store._conn()
    try:
        return [json.loads(d) for (d,) in c.execute("SELECT detail FROM events WHERE kind = ? AND ts > ?", (kind, since))]
    finally:
        c.close()


def digest(store, tick_id):
    """The Sunday tick's one line, once per ISO week. Counts this week's state transitions (`improve` events with from and
    to), never the `improve_refused` or `improve_waiting` events a sweep repeats. Returns a counts dict; never raises."""
    try:
        now = store.now()
        lt = time.localtime(now)
        if lt.tm_wday != 6:
            return {"posted": 0}
        week = time.strftime("%G-W%V", lt)
        if any(d.get("week") == week for d in _events(store, "improve_digest", 0)):
            return {"posted": 0}
        project = store.project
        if not _has_channel(project):
            return {"posted": 0}
        moves = [d for d in _events(store, "improve", now - WEEK) if d.get("from") and d.get("to")]

        def ids(to):
            return {d["proposal"] for d in moves if d["to"] == to}
        n, k, r = len(ids("trial")), len(ids("kept")), len(ids("reverted"))
        a = len(store.list("awaiting_you"))
        text = f"🧪 improve: {n} trials, {k} kept, {r} reverted, {a} awaiting you; {_o1()}"
        _write(project, _post(text, "progress", f"improve-digest-{project}-{week}"))
        c = store._conn()
        try:
            import json
            c.execute("INSERT INTO events(ts, spec, job, kind, detail) VALUES (?, NULL, NULL, 'improve_digest', ?)",
                      (now, json.dumps({"week": week, "tick": tick_id})))
        finally:
            c.close()
        return {"posted": 1, "trials": n, "kept": k, "reverted": r, "awaiting_you": a}
    except Exception as e:  # noqa: BLE001
        _log("digest", e)
        return {"posted": 0, "error": 1}


# ---- clicks ----------------------------------------------------------------------------------------------------------

def _note(project, text, pid, act):
    if _has_channel(project):
        _write(project, _post(text, "progress", f"improve-{act}-{project}-{pid}-{int(time.time() * 1000)}"))


def click(project, user, cid, now, add_line=None):
    """The audit result of one `ab:improve:` click: promoted | rejected | extended | approved | waiting | reverted (each acting
    click also writes one result post), ignored (another project), unknown (not an id of ours), stale (the proposal no
    longer allows the action: no change), or `error: <Type>`. Never raises."""
    m = CID_RE.match(cid or "")
    if not m:
        return "unknown"
    act, p, pid = m.groups()
    if p != project:
        return "ignored"
    A = improve_apply
    try:
        store = _store(p)
        row = store.get(pid)
        if not row or row["state"] not in ALLOWED[act]:
            return "stale"
        if act == "approve" and (row["class"] != "protected" or row["reason"] == A.ADAPTER_DRAFT):
            return "stale"
        try:
            if act == "promote":
                if A.reject_if_stale(store, pid):
                    return "stale"
                store.transition(pid, "promoted", f"promoted by {user}")
                res = A.apply(store, pid)
                _note(p, f"✅ {pid} promoted: {res}", pid, act)
                return "promoted"
            if act == "reject":
                store.transition(pid, "rejected", f"rejected by {user}")
                _note(p, f"🚫 {pid} rejected", pid, act)
                return "rejected"
            if act == "extend":
                store.transition(pid, "trial", f"trial extended by {user}", trial_len=(row["trial_len"] or 5) + EXTEND_BY)
                _note(p, f"⏩ {pid} back in trial, {EXTEND_BY} more specs", pid, act)
                return "extended"
            if act == "approve":
                res = A.approve_draft(store, pid, add_line=add_line)
                _note(p, f"✅ {pid} draft approved" if res == "approved" else f"⏳ {pid} approval waits for a clean checkout", pid, act)
                return res
            A.revert(store, pid, reason=f"reverted by {user}")
            _note(p, f"↩️ {pid} reverted", pid, act)
            return "reverted"
        except improve_store.ImproveError:   # the state moved between the check and the transition: a second click
            return "stale"
    except Exception as e:  # noqa: BLE001 -- one bad click is audited, never raised into the controls loop
        _log("click", e)
        return f"error: {type(e).__name__}"
