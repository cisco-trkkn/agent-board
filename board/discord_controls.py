"""discord_controls: the board side of the discord buttons and reactions.

step(project, record, now, run, add_line) scans teammate permission prompts (one `prompt` op per distinct key), consumes the
bridge's perm/react/click events from <dir>/events, and saves <dir>/controls-state.json under flock. `run(argv) -> str` raises
RuntimeError(output) on a non-zero exit (server.run_script); `add_line(sess, text)` is COMMENTS.add_line. Test: tests/test_discord_controls.py."""
import fcntl
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import discord_feed
import discord_ideas
import dream_discord
import tc_env

BIN = Path(__file__).resolve().parent.parent / "bin"
LEAD = "claude"
EMOJI_LINES = {
    "✅": '[Discord] ✅ yes to your message "{}"',
    "❌": '[Discord] ❌ no to your message "{}"',
    "🛑": "[Discord] 🛑 pause the queue",
    "▶": "[Discord] ▶️ resume the queue",
    "⏭": "[Discord] ⏭️ skip the running spec",
}
_NO_PROMPT = "approve: no permission prompt"


def _load(p):
    try:
        v = json.loads(Path(p).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _allow(d):
    a = _load(d / "access.json").get("allowFrom")
    return {str(x) for x in a} if isinstance(a, list) else set()


def _key(pane, lines):
    return f"{pane}:{hashlib.sha1(chr(10).join(lines).encode('utf-8')).hexdigest()}"


def _show(run, window):
    """(tool, lines) of the prompt showing in window; None when it shows none; 'error' for any other failure (ambiguous, gone,
    timed out: run_script raises subprocess.TimeoutExpired, which is not a RuntimeError)."""
    try:
        out = run([str(BIN / "tmux-ctl"), "approve", window, "show"])
    except Exception as e:  # noqa: BLE001 -- any failure of show is 'error', so one window never aborts the scan
        return None if str(e).startswith(_NO_PROMPT) else "error"
    tool, lines = "", []
    for l in out.split("\n"):
        if l.startswith("T:"):
            tool = l[2:]
        elif l.startswith("P:"):
            lines.append(l[2:])
    return (tool, lines) if lines else "error"


def _ops(fn, *args):
    """Call discord_ops.<fn> (a no-op there when the ops bot is not configured); a failure never breaks the controls step."""
    try:
        import discord_ops
        return getattr(discord_ops, fn)(*args)
    except Exception as e:  # noqa: BLE001
        print(f"discord_controls: ops {fn} failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def _edit(d, key, rec, outcome):
    text = f"🔐 {rec['window']} wants to run {rec['tool']}: {outcome}"
    discord_feed.outbox_write(d, {"op": "edit", "key": key, "text": text})
    _ops("resolve", d.name, key, text)


def scan_prompts(d, record, state, now, run):
    prompts = state["prompts"]
    cache = {}

    def show(window):
        if window not in cache:
            cache[window] = _show(run, window)
        return cache[window]

    wins = {}
    for it in record.get("needs_you") or []:
        w = it.get("window")
        if w and w != LEAD and w not in wins:
            wins[w] = it.get("pane") or ""
    for w, pane in wins.items():
        got = show(w)
        if isinstance(got, tuple):
            tool, lines = got
            key = _key(pane, lines)
            if key not in prompts:
                discord_feed.outbox_write(d, {"op": "prompt", "key": key, "window": w, "tool": tool, "lines": lines,
                                              "tier": "decision", "mention_user": True})
                prompts[key] = {"window": w, "pane": pane, "tool": tool, "lines": lines, "ts": now}
                _ops("mirror_prompt", d.name, key, w, tool, lines)
    for key, rec in list(prompts.items()):
        got = show(rec["window"])
        if got == "error":
            continue
        if isinstance(got, tuple) and _key(rec.get("pane", ""), got[1]) == key:
            continue
        _edit(d, key, rec, "answered elsewhere")
        del prompts[key]


def _perm(d, ev, state, run, user):
    key, prompts = str(ev.get("key") or ""), state["prompts"]
    rec = prompts.get(key)
    if rec is None:
        return "unknown"  # already answered (double tap): no edit, the final outcome text stays
    act = {"allow": "once", "deny": "deny"}.get(ev.get("choice"))
    if act is None:
        return "ignored"
    try:
        run([str(BIN / "tmux-ctl"), "approve", rec["window"], act, "--expect", "\n".join(rec["lines"])])
        result, outcome = ("allowed", "✅ allowed by you") if act == "once" else ("denied", "⛔ denied")
    except Exception as e:  # noqa: BLE001 -- a failed press is reported on the post, never retried
        first = (str(e).splitlines() or [""])[0] or "exit error"
        result, outcome = "not pressed", f"⚠️ not pressed: {first}"
    _edit(d, key, rec, outcome)
    del prompts[key]
    return result


def consume_events(d, project, state, run, add_line):
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
            if kind == "perm":
                key = str(ev.get("key") or "")
                discord_feed.audit_append(d, user, "perm", key, _perm(d, ev, state, run, user) if user in allow else "rejected")
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
            elif kind in ("slash", "modal", "read", "rejected"):
                _ops("handle_event", project, d, ev, add_line, allow)
            elif kind == "click" and str(ev.get("custom_id") or "").startswith("ab:dream:"):
                cid = str(ev.get("custom_id"))
                discord_feed.audit_append(d, user, "click", cid, dream_discord.click(project, user, cid, time.time()) if user in allow else "rejected")
            elif kind == "click" and str(ev.get("custom_id") or "").startswith("ab:ideas:"):
                cid = str(ev.get("custom_id"))
                discord_feed.audit_append(d, user, "click", cid, discord_ideas.click(user, cid, add_line, time.time()) if user in allow else "rejected")
            else:
                discord_feed.audit_append(d, user, "click", str(ev.get("custom_id") or ""), "ignored" if user in allow else "rejected")
        finally:
            try:
                f.unlink()
            except OSError:
                pass


def step(project, record, now, run, add_line):
    d = tc_env.discord_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "controls-state.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sp = d / "controls-state.json"
        st = _load(sp)
        if not isinstance(st.get("prompts"), dict):
            st["prompts"] = {}
        try:
            try:
                scan_prompts(d, record, st, now, run)
            except Exception as e:  # noqa: BLE001 -- a failed scan must not skip the queued clicks and reactions
                print(f"discord_controls: scan failed ({project}): {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            consume_events(d, project, st, run, add_line)
        finally:
            tmp = sp.with_name(sp.name + ".tmp")
            tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, sp)
