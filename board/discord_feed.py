"""discord_feed: the board side of the discord bridge. Pure functions plus file I/O, no tmux, no network.

Spool writer (outbox, 200 cap), feed-event file (spec §11), status card renderer and throttle, audit log.
Paths come from tc_env (agent_base, discord_dir, feed_path). Test: tests/test_discord_feed.py."""
import copy
import fcntl
import glob
import hashlib
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


def _spec_name(subject):
    """`Plan & run: docs/superpowers/specs/<name>.md#part-1` -> `<name>#part-1`."""
    path, hashsep, frag = str(subject)[len(_PLAN_RUN):].strip().partition("#")
    return os.path.basename(path).removesuffix(".md") + hashsep + frag


def _queue(lead_tasks):
    runs = sorted((t for t in lead_tasks if str(t.get("subject", "")).startswith(_PLAN_RUN)), key=_tid)
    for k, t in enumerate(runs, 1):
        if t.get("status") == "in_progress":
            return f"queue: running {_spec_name(t['subject'])} ({k}/{len(runs)})"
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


# ---- derivation: lead tasks, plan file, ledger, reports -> feed events -> outbox ops ----
SEEN_CAP = 2000
REVIEW_RE = re.compile(r"^(Final (re-)?review|Final fix wave|Task [0-9]+: (complete|re-review|fix round)|Batch [0-9-]+: review)")
TEXT_MAX = 300


def _glob_root(root, rel):
    """root/<rel> and root/.claude/worktrees/*/<rel>, in that order."""
    root = str(root)
    return [Path(p) for p in [os.path.join(root, rel)] + sorted(glob.glob(os.path.join(glob.escape(root), ".claude", "worktrees", "*", rel)))]


def _cut(text):
    return text if len(text) <= TEXT_MAX else text[:TEXT_MAX]


def _ev(project, spec, kind, tier, text, now, **refs):
    return {"ts": now, "project": project, "spec": spec, "kind": kind, "tier": tier, "text": _cut(text),
            "refs": {k: v for k, v in refs.items() if v}}


def _plan_task_count(root, plan):
    for p in _glob_root(root, plan):
        try:
            return sum(1 for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("### Task "))
        except OSError:
            continue
    return None


def _ledger_lines(root, plan_base):
    for p in _glob_root(root, f".superpowers/sdd/{plan_base}/progress.md"):
        try:
            return [l.rstrip() for l in p.read_text(encoding="utf-8").splitlines() if REVIEW_RE.match(l)]
        except OSError:
            continue
    return []


def _report_summary(path):
    try:
        for l in path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                return l.lstrip("# ").strip()
    except OSError:
        pass
    return path.name


def derive(project, root, lead_tasks, state, now):
    """(events, new_state). Each event is emitted once: its key goes into state["seen"] (newest 2000 kept).
    The first call on a fresh state (no "primed") records the history already there (completed tasks, ledger lines,
    outcomes, reports) as seen without emitting, so an old ledger is not replayed; spec_started and plan_written
    of a run already in progress are still emitted. Does not mutate `state`."""
    st = copy.deepcopy(state or {})
    first = not st.get("primed")
    seen = list(st.get("seen") or [])
    have = set(seen)
    out = []

    def emit(key, ev, history=False):
        if key in have:
            return
        have.add(key)
        seen.append(key)
        if not (first and history):
            out.append(ev)

    tasks = [t for t in (lead_tasks or []) if isinstance(t, dict)]
    runs = sorted((t for t in tasks if str(t.get("subject", "")).startswith(_PLAN_RUN)), key=_tid)
    running = next((t for t in runs if t.get("status") == "in_progress"), None)
    st["running_thread_key"] = str(running["id"]) if running else ""
    if running:
        rid, spec = str(running["id"]), _spec_name(running["subject"])
        emit(f"started:{rid}", _ev(project, spec, "spec_started", "progress", f"spec started: {spec}", now, thread_key=rid))
        meta = running.get("metadata") if isinstance(running.get("metadata"), dict) else {}
        plan = meta.get("plan")
        if isinstance(plan, str) and plan:
            if f"plan:{rid}" not in have:
                n = _plan_task_count(root, plan)
                if n is not None:
                    emit(f"plan:{rid}", _ev(project, spec, "plan_written", "progress", f"plan written: {n} tasks", now, thread_key=rid))
            base = os.path.basename(plan).removesuffix(".md")
            for line in _ledger_lines(root, base):
                emit(f"rev:{base}:{hashlib.sha1(line.encode()).hexdigest()[:12]}",
                     _ev(project, spec, "review", "progress", "review: " + line, now, thread_key=rid), history=True)
    for t in sorted((t for t in tasks if t not in runs), key=_tid):
        if t.get("status") == "completed":
            if running:
                emit(f"done:{t.get('id')}", _ev(project, _spec_name(running["subject"]), "task_done", "progress",
                                                f"✓ {t.get('subject', '')}", now, task=str(t.get("id")), thread_key=str(running["id"])), history=True)
            elif f"done:{t.get('id')}" not in have:
                have.add(f"done:{t.get('id')}")   # finished with no spec running: history, never replayed later
                seen.append(f"done:{t.get('id')}")
    for t in runs:
        if t.get("status") == "completed":
            meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
            outcome = str(meta.get("outcome") or "completed")
            tier = "critical" if outcome.startswith("failed") else "progress"
            rid = str(t["id"])
            emit(f"outcome:{rid}", _ev(project, _spec_name(t["subject"]), "spec_outcome", tier, outcome, now, thread_key=rid), history=True)
    for p in sorted(glob.glob(os.path.join(glob.escape(str(root)), "docs", "superpowers", "reports", "*-queue.md"))):
        name = os.path.basename(p)
        emit(f"report:{name}", _ev(project, "", "report_written", "progress", f"queue report: {_report_summary(Path(p))}", now, file=name), history=True)
    st["primed"] = True
    st["seen"] = seen[-SEEN_CAP:]
    return out, st


def ops_for_events(events, state):
    """Outbox ops by tier: progress -> post in the spec thread (home for a report or when no spec runs); critical and
    decision -> home post with mention_user and a link to the running spec's thread; routine -> nothing (card only)."""
    running = (state or {}).get("running_thread_key") or ""
    ops = []
    for ev in events:
        kind, tier, refs = ev.get("kind"), ev.get("tier"), ev.get("refs") or {}
        thread = refs.get("thread_key") or running
        if kind == "spec_outcome" and str(ev.get("text", "")).startswith("failed"):
            tier = "critical"
        if tier == "routine":
            continue
        if kind == "spec_started" and refs.get("thread_key"):
            ops.append({"op": "thread", "key": refs["thread_key"], "title": ev.get("spec") or refs["thread_key"]})
        if tier in ("critical", "decision"):
            op = {"op": "post", "text": ev["text"], "tier": tier, "mention_user": True}
            if thread:
                op["link_thread_key"] = thread
        else:
            op = {"op": "post", "text": ev["text"], "tier": "progress", "mention_user": False}
            if thread and kind != "report_written":
                op["thread_key"] = thread
        ops.append(op)
        if kind == "spec_outcome" and refs.get("thread_key"):
            ops.append({"op": "archive", "key": refs["thread_key"]})
    return ops


def _load(p):
    try:
        v = json.loads(Path(p).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def tick(project, record, root, home, now, lead_tasks=None):
    """One feed pass for a project under flock(<dir>/feed-state.lock); None when another tick holds it.
    derive -> append events to the feed file -> read every feed event since state["feed_offset"] (so events appended by
    other writers flow through too) -> outbox ops -> the card op when due -> feed-state.json.
    `lead_tasks` are the raw lead task dicts (planview.raw_live_tasks); `home` is kept for the caller's session lookup."""
    import tc_env
    d = tc_env.discord_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "feed-state.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        sp = d / "feed-state.json"
        st = _load(sp)
        if "feed_offset" not in st:
            fp = tc_env.feed_path(project)
            st["feed_offset"] = fp.stat().st_size if fp.exists() and not st.get("primed") else 0
        events, st = derive(project, root, lead_tasks or [], st, now)
        for ev in events:
            append_event(project, ev)
        flow, st["feed_offset"] = read_events(project, st["feed_offset"])
        ops = ops_for_events(flow, st)
        text = render_card(record, lead_tasks or [], now)
        card = card_op_due(st, text, now)
        if card:
            ops.append(card)
        for op in ops:
            outbox_write(d, op)
        if card:
            st["card_text"], st["card_ts"] = text, now
        tmp = sp.with_name(sp.name + ".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, sp)
        return {"events": len(flow), "ops": len(ops)}
