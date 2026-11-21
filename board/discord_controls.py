"""discord_controls: the board side of the discord buttons and reactions.

step(project, record, now, run, add_line) consumes the bridge's react/click/reply/slash events from <dir>/events (dialog taps and
replies go to discord_dialogs, which presses through `tmux-ctl dialog`; a leftover `perm` event is audited `unknown`) and saves <dir>/controls-state.json under flock. `run(argv) -> str` raises
RuntimeError(output) on a non-zero exit (server.run_script); `add_line(sess, text)` is COMMENTS.add_line. Test: tests/test_discord_controls.py."""
import fcntl
import json
import os
import shutil
import sys
import time
from pathlib import Path

import analytics_post
import discord_dialogs
import discord_feed
import discord_ideas
import discover_post
import dream_discord
import scout_post
import tc_env

BIN = Path(__file__).resolve().parent.parent / "bin"
EMOJI_LINES = {
    "✅": '[Discord] ✅ yes to your message "{}"',
    "❌": '[Discord] ❌ no to your message "{}"',
    "🛑": "[Discord] 🛑 pause the queue",
    "▶": "[Discord] ▶️ resume the queue",
    "⏭": "[Discord] ⏭️ skip the running spec",
}


def _load(p):
    try:
        v = json.loads(Path(p).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _allow(d):
    a = _load(d / "access.json").get("allowFrom")
    return {str(x) for x in a} if isinstance(a, list) else set()


def _ops(fn, *args):
    """Call discord_ops.<fn> (a no-op there when the ops bot is not configured); a failure never breaks the controls step."""
    try:
        import discord_ops
        return getattr(discord_ops, fn)(*args)
    except Exception as e:  # noqa: BLE001
        print(f"discord_controls: ops {fn} failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def _cross_denied(own, ev, user):
    """An event naming a project other than this bot's own needs the user in the ops bot's allowlist too (missing file: nobody)."""
    target = ev.get("project")
    if not target or target == own:
        return False
    return user not in _allow(tc_env.ops_dir())


def _scout(project, ev, allow, add_line):
    """(audit action, target, result) for an `ab:scout:` click or reply (checked before the dialog consumer, which takes every reply), else None."""
    user, kind = str(ev.get("user") or ""), str(ev.get("type") or "")
    cid, key = str(ev.get("custom_id") or ""), str(ev.get("key") or "")
    if kind == "click" and cid.startswith("ab:scout:"):
        return "click", cid, scout_post.click(user, cid, time.time(), add_line=lambda t: add_line(project, t)) if user in allow else "rejected"
    if kind == "reply" and key.startswith("ab:scout:"):
        return "scout-reply", key, scout_post.reply(user, key, ev.get("text"), time.time()) if user in allow else "rejected"
    return None


def consume_events(d, project, state, run, add_line, lead_run=None, spawn=None):
    ev_dir = d / "events"
    allow = _allow(d)
    for f in sorted(ev_dir.glob("*.json")):
        try:
            ev = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(ev, dict):
                raise ValueError("not an object")
        except (OSError, ValueError):
            (ev_dir / "failed").mkdir(exist_ok=True)
            shutil.move(str(f), str(ev_dir / "failed" / f.name))
            continue
        user, kind = str(ev.get("user") or ""), str(ev.get("type") or "")
        try:
            dlg = _scout(project, ev, allow, add_line) or discord_dialogs.consume_event(d, ev, allow, run, time.time(), add_line=add_line)
            if dlg:
                discord_feed.audit_append(d, user, *dlg)
            elif kind == "perm":   # the old prompt buttons are gone: a leftover event is only audited
                discord_feed.audit_append(d, user, "perm", str(ev.get("key") or ""), "unknown" if user in allow else "rejected")
            elif kind == "react":
                emoji = str(ev.get("emoji") or "").replace("️", "")
                tpl = EMOJI_LINES.get(emoji)
                if user not in allow:
                    result = "rejected"
                elif tpl is None:
                    result = "ignored"
                else:
                    add_line(project, tpl.format(" ".join(str(ev.get("excerpt") or "").split())))
                    result = "queued"
                discord_feed.audit_append(d, user, "react", str(ev.get("emoji") or ""), result)
            elif kind in ("slash", "modal", "read", "rejected") and _cross_denied(project, ev, user):
                discord_feed.audit_append(d, user, kind, f"{ev.get('project')}:{ev.get('command') or ev.get('form') or ev.get('what') or ''}", "rejected")
            elif kind in ("slash", "modal", "read", "rejected"):
                _ops("handle_event_locked", project, d, ev, add_line, allow, lead_run or run, spawn)
            elif kind == "click" and str(ev.get("custom_id") or "").startswith("ab:dream:"):
                cid = str(ev.get("custom_id"))
                discord_feed.audit_append(d, user, "click", cid, dream_discord.click(project, user, cid, time.time()) if user in allow else "rejected")
            elif kind == "click" and str(ev.get("custom_id") or "").startswith("ab:ideas:"):
                cid = str(ev.get("custom_id"))
                discord_feed.audit_append(d, user, "click", cid, discord_ideas.click(user, cid, add_line, time.time()) if user in allow else "rejected")
            elif kind == "click" and str(ev.get("custom_id") or "").startswith("ab:discover:"):
                cid = str(ev.get("custom_id"))
                discord_feed.audit_append(d, user, "click", cid, discover_post.click(project, user, cid, time.time()) if user in allow else "rejected")
            elif kind == "click" and str(ev.get("custom_id") or "").startswith("ab:analytics:"):
                cid = str(ev.get("custom_id"))
                discord_feed.audit_append(d, user, "click", cid, analytics_post.click(d, user, cid, time.time()) if user in allow else "rejected")
            else:
                discord_feed.audit_append(d, user, "click", str(ev.get("custom_id") or ""), "ignored" if user in allow else "rejected")
        finally:
            try:
                f.unlink()
            except OSError:
                pass


SCOUT_RETRY_EVERY = 600


def _scout_retry(project, st, now, add_line):
    """Retry the scout's waiting approvals at most every SCOUT_RETRY_EVERY seconds (last call kept in st["scout_retry_at"])."""
    last = st.get("scout_retry_at")
    if isinstance(last, (int, float)) and 0 <= now - last < SCOUT_RETRY_EVERY:
        return
    st["scout_retry_at"] = now
    try:
        import dream
        import scout_decisions
        scout_decisions.retry_copies(dream.resolve_root(project, {"root": str(scout_post.REPO)}, None), now, lambda t: add_line(project, t))
    except Exception as e:  # noqa: BLE001 -- a failed retry never breaks the controls step
        print(f"discord_controls: scout retry failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def step(project, record, now, run, add_line, lead_run=None, spawn=None):
    d = tc_env.discord_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "controls-state.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sp = d / "controls-state.json"
        st = _load(sp)
        try:
            consume_events(d, project, st, run, add_line, lead_run=lead_run, spawn=spawn)
            if project == scout_post.PROJECT:
                _scout_retry(project, st, now, add_line)
        finally:
            tmp = sp.with_name(sp.name + ".tmp")
            tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, sp)
