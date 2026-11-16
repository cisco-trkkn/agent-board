"""discord_feed: the board side of the discord bridge. Pure functions plus file I/O, no tmux, no network.

Spool writer (outbox, 200 cap), feed-event file (spec §11), status card renderer and throttle, audit log.
Paths come from tc_env (agent_base, discord_dir, feed_path). Test: tests/test_discord_feed.py."""
import json
import os
import re
import secrets
import time
from pathlib import Path

CAP = 200
CARD_MAX = 1900
CARD_EVERY = 30
TIERS = ("critical", "decision", "progress")
EVENT_KEYS = ("ts", "project", "spec", "kind", "tier", "text", "refs")
_POST_OPT = {"thread_key": str, "link_thread_key": str, "files": list}
_last_ms = 0


def _check(op):
    if not isinstance(op, dict):
        raise ValueError("op must be a dict")
    kind = op.get("op")
    shapes = {"post": ({"op", "text", "tier", "mention_user"}, set(_POST_OPT)),
              "card": ({"op", "text"}, set()),
              "thread": ({"op", "key", "title"}, set()),
              "archive": ({"op", "key"}, set())}
    if kind not in shapes:
        raise ValueError(f"unknown op {kind!r}")
    need, opt = shapes[kind]
    keys = set(op)
    if not need <= keys or keys - need - opt:
        raise ValueError(f"bad keys for {kind}: {sorted(keys)}")
    for k in keys - {"op", "mention_user", "files"}:
        if k != "tier" and not isinstance(op[k], str):
            raise ValueError(f"{k} must be a string")
    if kind == "post":
        if op["tier"] not in TIERS:
            raise ValueError(f"tier {op['tier']!r} never becomes a post")
        if not isinstance(op["mention_user"], bool):
            raise ValueError("mention_user must be a bool")
        if "files" in op and not (isinstance(op["files"], list) and all(isinstance(f, str) and f.startswith("/") for f in op["files"])):
            raise ValueError("files must be absolute paths")


def _next_ms():
    """Strictly increasing epoch ms within the process, so names sort in write order."""
    global _last_ms
    ms = int(time.time() * 1000)
    if ms <= _last_ms:
        ms = _last_ms + 1
    _last_ms = ms
    return ms


def _enforce_cap(box):
    files = sorted(box.glob("*.json"))
    over = len(files) - CAP
    if over <= 0:
        return
    infos = []
    for f in files:
        try:
            op = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            op = {}
        infos.append((f, op))
    for victim in ([f for f, o in infos if o.get("op") == "card"]
                   + [f for f, o in infos if o.get("op") != "card" and not (o.get("op") == "post" and o.get("mention_user") is True)]):
        if over <= 0:
            break
        try:
            victim.unlink()
        except OSError:
            continue
        over -= 1


def outbox_write(dir, op):
    """Validate op and write <dir>/outbox/<13-digit ms>-<8 hex>.json atomically; keep at most CAP files. Returns the path."""
    _check(op)
    box = Path(dir) / "outbox"
    box.mkdir(parents=True, exist_ok=True)
    name = f"{_next_ms():013d}-{secrets.token_hex(4)}.json"
    tmp = box / (name + ".tmp")
    tmp.write_text(json.dumps(op, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, box / name)
    _enforce_cap(box)
    return box / name


def _feed_path(project):
    import tc_env
    return tc_env.feed_path(project)


def append_event(project, ev):
    """Append one spec §11 line; refs defaults to {}. Extra keys are dropped, a missing key raises ValueError."""
    missing = [k for k in EVENT_KEYS if k != "refs" and k not in ev]
    if missing:
        raise ValueError(f"missing keys {missing}")
    line = {k: ev.get(k, {} if k == "refs" else None) for k in EVENT_KEYS}
    p = _feed_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "ab") as f:
        f.write((json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))


def read_events(project, offset=0):
    """(events, new_offset) from byte offset; a last line without its newline is left for the next call."""
    p = _feed_path(project)
    try:
        with open(p, "rb") as f:
            f.seek(offset)
            data = f.read()
    except OSError:
        return [], offset
    end = data.rfind(b"\n") + 1
    out = []
    for raw in data[:end].splitlines():
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out, offset + end


_PLAN_RUN = "Plan & run:"


def _tier(t):
    meta = t.get("metadata")
    if isinstance(meta, dict) and isinstance(meta.get("modelTier"), str):
        return meta["modelTier"]
    m = re.search(r"```json:metadata\s*\n(.*?)\n```", str(t.get("description") or ""), re.S)
    if m:
        try:
            v = json.loads(m.group(1))
            if isinstance(v, dict) and isinstance(v.get("modelTier"), str):
                return v["modelTier"]
        except ValueError:
            pass
    return ""


def _tid(t):
    s = str(t.get("id", ""))
    return (0, int(s), s) if s.isdigit() else (1, 0, s)


def _queue(lead_tasks):
    runs = sorted((t for t in lead_tasks if str(t.get("subject", "")).startswith(_PLAN_RUN)), key=_tid)
    for k, t in enumerate(runs, 1):
        if t.get("status") == "in_progress":
            spec = os.path.basename(str(t["subject"])[len(_PLAN_RUN):].strip()).removesuffix(".md")
            return f"queue: running {spec} ({k}/{len(runs)})"
    if any(t.get("status") == "pending" for t in runs):
        return "queue: paused"
    return "queue: idle"


def render_card(record, lead_tasks, now):
    """The status card: one code block, at most CARD_MAX characters, overflow cut with '… <n> more'."""
    lead_tasks = [t for t in (lead_tasks or []) if isinstance(t, dict)]
    head = [_queue(lead_tasks)]
    body = []
    for t in sorted((t for t in lead_tasks if not str(t.get("subject", "")).startswith(_PLAN_RUN)), key=_tid):
        mark = {"completed": "✓", "in_progress": "▶"}.get(t.get("status"), "·")
        extra = " ".join(x for x in (t.get("owner") or "", _tier(t)) if x)
        body.append(f"{mark} {t.get('subject', '')}" + (f"  ({extra})" if extra else ""))
    tail = []
    agents = [f"{a.get('window', '?')} {'busy' if a.get('state') == 'working' else 'idle'}" for a in (record.get("agents") or [])]
    if agents:
        tail.append("teammates: " + ", ".join(agents))
    waits = [str(n.get("window", "?")) for n in (record.get("needs_you") or [])]
    tail.append("waiting on you: " + (", ".join(waits) if waits else "none"))
    tail.append("updated " + time.strftime("%H:%M", time.localtime(now)))

    def build(lines):
        return "```\n" + "\n".join(lines) + "\n```"

    keep = len(body)
    while True:
        shown = body[:keep]
        more = [f"… {len(body) - keep} more"] if keep < len(body) else []
        text = build(head + shown + more + tail)
        if len(text) <= CARD_MAX or keep == 0:
            return text[:CARD_MAX - 4] + "\n```" if len(text) > CARD_MAX else text
        keep -= 1


def card_op_due(state, text, now):
    """A card op when text changed and at least CARD_EVERY seconds passed since state['card_ts'], else None."""
    if text == state.get("card_text"):
        return None
    if now - state.get("card_ts", 0) < CARD_EVERY:
        return None
    return {"op": "card", "text": text}


def audit_append(dir, user, action, target, result):
    d = Path(dir)
    d.mkdir(parents=True, exist_ok=True)
    line = {"ts": time.time(), "user": user, "action": action, "target": str(target)[:80], "result": result}
    with open(d / "audit.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
