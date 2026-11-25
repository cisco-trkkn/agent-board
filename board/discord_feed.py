"""discord_feed: the board side of the discord bridge. Pure functions plus file I/O, no tmux, no network.

Spool writer (outbox, 200 cap), feed-event file (spec §11), status card renderer and throttle, audit log.
Paths come from tc_env (agent_base, discord_dir, feed_path). Test: tests/test_discord_feed.py."""
import copy
import datetime
import fcntl
import glob
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path

CAP = 200
CARD_MAX = 1900
PRESENCE_MAX = 128
CARD_EVERY = 30
PRESENCE_EVERY = 60
TIERS = ("critical", "decision", "progress")
EVENT_KEYS = ("ts", "project", "spec", "kind", "tier", "text", "refs")
APPROVAL_KINDS = ("perm", "question", "merge", "other")
_POST_OPT = {"select": dict, "key": str, "thread_key": str, "link_thread_key": str, "files": list, "delete_files": bool, "buttons": list, "rows": list}
_last_ms = 0
_ms_lock = threading.Lock()   # the overview thread and the notifier sink both write


def _check_rows(rows):
    """At most 5 rows of at most 5 {label, style, custom_id}; custom_id at most 100 characters."""
    if not (isinstance(rows, list) and len(rows) <= 5 and all(
            isinstance(r, list) and len(r) <= 5 and all(
                isinstance(b, dict) and set(b) == {"label", "style", "custom_id"} and isinstance(b["label"], str)
                and isinstance(b["custom_id"], str) and len(b["custom_id"]) <= 100 and type(b["style"]) is int
                for b in r) for r in rows)):
        raise ValueError("rows must be at most 5 lists of at most 5 {label, style, custom_id}")


def _check_select(sel):
    """One select: custom_id, placeholder, at most 25 {label, value}; every string at most 100 characters (placeholder 150)."""
    def ok(v):
        return isinstance(v, str) and 0 < len(v) <= 100
    if not (isinstance(sel, dict) and set(sel) <= {"custom_id", "placeholder", "options"} and ok(sel.get("custom_id"))
            and isinstance(sel.get("placeholder", ""), str) and len(sel.get("placeholder", "")) <= 150
            and isinstance(sel.get("options"), list) and 0 < len(sel["options"]) <= 25
            and all(isinstance(o, dict) and set(o) == {"label", "value"} and ok(o["label"]) and ok(o["value"]) for o in sel["options"])):
        raise ValueError("select must be {custom_id, placeholder, options: 1..25 of {label, value}} with strings of at most 100 chars")


def _check(op):
    if not isinstance(op, dict):
        raise ValueError("op must be a dict")
    kind = op.get("op")
    shapes = {"post": ({"op", "text", "tier", "mention_user"}, set(_POST_OPT)),
              "card": ({"op", "text"}, set()),
              "thread": ({"op", "key", "title"}, set()),
              "archive": ({"op", "key"}, set()),
              "prompt": ({"op", "key", "window", "tool", "lines", "tier", "mention_user"}, set()),
              "edit": ({"op", "key", "text"}, {"rows", "reply"}),
              "dialog": ({"op", "key", "text", "rows", "mention_user"}, set()),
              "presence": ({"op", "text"}, set()),
              "ireply": ({"op", "iid", "content"}, {"components", "private"}),
              "approval": ({"op", "key", "kind", "text", "mention_user"}, {"link", "project"}),
              # /new-project (board/newproject.py): the ops bridge creates #<name> and grants the new bot its overwrite
              "create_channel": ({"op", "guild", "name", "req"}, set()),
              "channel_overwrite": ({"op", "channel", "user", "allow", "name", "req"}, set())}
    if kind not in shapes:
        raise ValueError(f"unknown op {kind!r}")
    need, opt = shapes[kind]
    keys = set(op)
    if not need <= keys or keys - need - opt:
        raise ValueError(f"bad keys for {kind}: {sorted(keys)}")
    for k in keys - {"op", "mention_user", "files", "lines", "delete_files", "buttons", "select", "rows", "components", "private"}:
        if k != "tier" and not isinstance(op[k], str):
            raise ValueError(f"{k} must be a string")
    if "private" in op and not isinstance(op["private"], bool):
        raise ValueError("private must be a bool")
    if "reply" in op and not (isinstance(op["reply"], str) and 0 < len(op["reply"]) <= 2000):
        raise ValueError("reply must be a non-empty string of at most 2000 chars")
    if kind == "presence" and (not op["text"] or len(op["text"]) > PRESENCE_MAX):
        raise ValueError("presence text must be 1..128 chars")
    if kind == "prompt":
        if op["tier"] not in TIERS:
            raise ValueError(f"tier {op['tier']!r} is not a tier")
        if not isinstance(op["mention_user"], bool):
            raise ValueError("mention_user must be a bool")
        if not (isinstance(op["lines"], list) and all(isinstance(l, str) for l in op["lines"])):
            raise ValueError("lines must be a list of strings")
    if "select" in op:
        _check_select(op["select"])
    if "rows" in op:
        _check_rows(op["rows"])
    if "components" in op:
        _check_rows(op["components"])
    if kind == "dialog" and not isinstance(op["mention_user"], bool):
        raise ValueError("mention_user must be a bool")
    if kind == "approval":
        if op["kind"] not in APPROVAL_KINDS:
            raise ValueError(f"kind {op['kind']!r} is not an approval kind")
        if not isinstance(op["mention_user"], bool):
            raise ValueError("mention_user must be a bool")
    if kind == "post":
        if op["tier"] not in TIERS:
            raise ValueError(f"tier {op['tier']!r} never becomes a post")
        if not isinstance(op["mention_user"], bool):
            raise ValueError("mention_user must be a bool")
        if "files" in op and not (isinstance(op["files"], list) and all(isinstance(f, str) and f.startswith("/") for f in op["files"])):
            raise ValueError("files must be absolute paths")
        if "delete_files" in op and not isinstance(op["delete_files"], bool):
            raise ValueError("delete_files must be a bool")
        if "buttons" in op:
            b = op["buttons"]
            if not (isinstance(b, list) and len(b) <= 5 and all(
                    isinstance(x, dict) and set(x) == {"label", "style", "custom_id"} and isinstance(x["label"], str)
                    and isinstance(x["custom_id"], str) and type(x["style"]) is int for x in b)):
                raise ValueError("buttons must be a list of at most 5 {label, style, custom_id}")
        if "rows" in op:
            _check_rows(op["rows"])
        if "buttons" in op and "rows" in op:
            raise ValueError("post takes buttons or rows, not both")


def _next_ms():
    """Strictly increasing epoch ms within the process, so names sort in write order."""
    global _last_ms
    with _ms_lock:
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
                   + [f for f, o in infos if o.get("op") not in ("card", "thread", "archive", "prompt", "edit", "approval", "dialog", "ireply") and not (o.get("op") == "post" and o.get("mention_user") is True)]):
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


def spec_progress(lead_tasks, floor):
    """(done, total) of the running spec's own tasks: not `Plan & run:`, numeric id above floor. None when floor is None."""
    if floor is None:
        return None
    own = [t for t in lead_tasks if isinstance(t, dict) and not str(t.get("subject", "")).startswith(_PLAN_RUN)
           and (_num(t.get("id")) or 0) > floor]
    return sum(t.get("status") == "completed" for t in own), len(own)


def spec_floor(project):
    """The running spec's floor from the project's feed-state.json, None when unknown."""
    import tc_env
    st = _load(tc_env.discord_dir(project) / "feed-state.json")
    v = (st.get("spec_floor") or {}).get(st.get("running_thread_key") or "")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _queue(lead_tasks, floor=None):
    runs = sorted((t for t in lead_tasks if str(t.get("subject", "")).startswith(_PLAN_RUN)), key=_tid)
    for k, t in enumerate(runs, 1):
        if t.get("status") == "in_progress":
            prog = spec_progress(lead_tasks, floor)
            tasks = f"tasks {prog[0]}/{prog[1]} · " if prog else ""
            return f"queue: running {_spec_name(t['subject'])} ({tasks}spec {k} of {len(runs)})"
    if any(t.get("status") == "pending" for t in runs):
        return "queue: paused"
    return "queue: idle"


def _num(i):
    s = str(i)
    return int(s) if s.isdigit() else None


def render_card(record, lead_tasks, now, floor=None):
    """The status card: one code block, at most CARD_MAX characters, overflow cut with '… <n> more'.
    Task lines are the running spec's: tasks with a numeric id above `floor` (the highest task id when the spec started);
    with no floor known, only tasks that are not completed."""
    lead_tasks = [t for t in (lead_tasks or []) if isinstance(t, dict)]
    head = [_queue(lead_tasks, floor)]
    body = []
    def of_spec(t):
        n = _num(t.get("id"))
        return n > floor if floor is not None and n is not None else t.get("status") != "completed"

    for t in sorted((t for t in lead_tasks if not str(t.get("subject", "")).startswith(_PLAN_RUN) and of_spec(t)), key=_tid):
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


def presence_op_due(state, text, now, bridge_state=None):
    """A presence op when the text changed, or the bridge's own state lost it, and PRESENCE_EVERY seconds passed since state['presence_ts']; else None."""
    if now - state.get("presence_ts", 0) < PRESENCE_EVERY:
        return None
    if text != state.get("presence_text") or (bridge_state or {}).get("presence") != text:
        return {"op": "presence", "text": text}
    return None


def audit_append(dir, user, action, target, result):
    d = Path(dir)
    d.mkdir(parents=True, exist_ok=True)
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "user": user, "action": action, "target": str(target)[:80], "result": result}
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


LOG_LINES = 200
ATTACH_KEEP = 20


def _failed_run_log(project, now, worktree=None, root=None):
    """The newest failing run record (exit not null/0, cwd in a worktree, ts within 24 h before now, log file present);
    its last LOG_LINES lines go to <discord dir>/attachments/<id>.log (newest ATTACH_KEEP files kept).
    With `worktree` and `root`, only runs under <root>/<worktree> are candidates; none of them -> None (another
    worktree's log is never posted).
    {"log_file", "log_cmd", "log_exit"} or None."""
    import tc_env
    recs = {}
    f = tc_env.state_dir() / f"runs-{project}.jsonl"
    try:
        lines = f.read_text(errors="replace").splitlines() if f.is_file() else []
    except OSError:
        lines = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("id"):
            recs[str(r["id"])] = r   # each id appears twice (start, final): the last one wins
    ok = [r for r in recs.values()
          if r.get("exit") not in (None, 0) and "/.claude/worktrees/" in str(r.get("cwd", ""))
          and isinstance(r.get("ts"), (int, float)) and now - 86400 <= r["ts"] <= now
          and os.path.isfile(str(r.get("log", "")))]
    if worktree and root:
        base = os.path.join(str(root), str(worktree)).rstrip("/")
        ok = [r for r in ok if str(r.get("cwd", "")) == base or str(r.get("cwd", "")).startswith(base + "/")]
    if not ok:
        return None
    r = max(ok, key=lambda r: r["ts"])
    try:
        with open(r["log"], encoding="utf-8", errors="replace") as fh:
            tail = fh.read().splitlines()[-LOG_LINES:]
        d = tc_env.discord_dir(project) / "attachments"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / (re.sub(r"[^\w.-]", "_", str(r["id"])) + ".log")
        dest.write_text("\n".join(tail) + "\n", encoding="utf-8")
        old = sorted((p for p in d.iterdir() if p.is_file()), key=lambda p: (p.stat().st_mtime, p.name))
        for p in old[:-ATTACH_KEEP]:
            p.unlink()
    except OSError:
        return None
    m = re.search(r"/\.claude/worktrees/([^/]+)", str(r.get("cwd", "")))
    where = m.group(1) if m else os.path.basename(str(r.get("cwd", "")).rstrip("/"))
    cmd = " ".join(str(r.get("cmd", "")).split())
    cmd = (cmd[:200] + "…") if len(cmd) > 200 else cmd
    at = datetime.datetime.fromtimestamp(r["ts"]).strftime("%H:%M")
    return {"log_file": str(dest), "log_cmd": cmd or str(r["id"]), "log_exit": r["exit"], "log_where": where, "log_at": at}


LEAD_KINDS = ("handed_to_lead", "lead_turn")


def note_engine_specs(state, events):
    """state with state["engine_specs"] (spec names before `#`, newest 200) updated from feed lines carrying src "engine".
    The latest engine line of a spec wins: a handed_to_lead or lead_turn line clears its mark (the lead runs it now), any other sets it."""
    have = list(state.get("engine_specs") or [])
    for e in events:
        if not (isinstance(e, dict) and e.get("src") == "engine" and isinstance(e.get("spec"), str) and e["spec"]):
            continue
        n = e["spec"].partition("#")[0]
        if n in have:
            have.remove(n)
        if e.get("kind") not in LEAD_KINDS:
            have.append(n)
    state = dict(state)
    state["engine_specs"] = have[-200:]
    return state


def derive(project, root, lead_tasks, state, now, list_id=""):
    """(events, new_state). Each event is emitted once: its key goes into state["seen"] (newest 2000 kept).
    The first call on a fresh state (no "primed") records the history already there (completed tasks, ledger lines,
    outcomes, reports) as seen without emitting, so an old ledger is not replayed; spec_started and plan_written
    of a run already in progress are still emitted. Priming is per task list (state["primed_lists"]): a list id not seen before (a relay's new list, or the list name flipping
    between the session dir and the team fallback) baselines its history instead of replaying it. An empty task list does not prime (the lead's task directory may not
    be resolved yet at board start). Task ids restart at 1 in a new lead session, so dedupe keys and thread keys are
    `<list_id>:<task id>` (list_id = the task-list directory name) when list_id is given. Does not mutate `state`."""
    st = copy.deepcopy(state or {})
    primed_lists = list(st.get("primed_lists") or [])
    first = (list_id not in primed_lists) if list_id else not st.get("primed")   # priming is per task list
    seen = list(st.get("seen") or [])
    have = set(seen)
    out = []

    engine_specs = set(st.get("engine_specs") or [])

    def emit(key, ev, history=False):
        if key in have:
            return
        have.add(key)
        seen.append(key)
        if ev.get("spec", "").partition("#")[0] in engine_specs:
            return   # the engine posts its own lines for a spec it runs
        if not (first and history):
            out.append(ev)

    def tk(i):
        return f"{list_id}:{i}" if list_id else str(i)

    tasks = [t for t in (lead_tasks or []) if isinstance(t, dict)]
    runs = sorted((t for t in tasks if str(t.get("subject", "")).startswith(_PLAN_RUN)), key=_tid)
    running = next((t for t in runs if t.get("status") == "in_progress"), None)
    st["running_thread_key"] = tk(running["id"]) if running else ""
    floors = dict(st.get("spec_floor") or {})
    if running and st["running_thread_key"] not in floors:
        # the card shows only the running spec's tasks. Seen as it starts: everything after the highest id now. Seen
        # already running (first poll of this list): its tasks exist, so take the plan's task count n and the n highest
        # ids; no readable plan -> None (the card then shows only tasks that are not completed).
        ids = sorted(n for n in (_num(t.get("id")) for t in tasks if t not in runs) if n is not None)
        if not first:
            floors[st["running_thread_key"]] = max([_num(t.get("id")) or 0 for t in tasks] or [0])
        else:
            plan = (running.get("metadata") or {}).get("plan") if isinstance(running.get("metadata"), dict) else None
            n = _plan_task_count(root, plan) if isinstance(plan, str) and plan else None
            floors[st["running_thread_key"]] = (ids[-n:][0] - 1 if ids[-n:] else 0) if n else None
    st["spec_floor"] = dict(list(floors.items())[-50:])
    if running:
        rid, spec = tk(running["id"]), _spec_name(running["subject"])
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
                emit(f"done:{tk(t.get('id'))}", _ev(project, _spec_name(running["subject"]), "task_done", "progress",
                                                     f"✓ {t.get('subject', '')}", now, task=str(t.get("id")), thread_key=tk(running["id"])), history=True)
            elif f"done:{tk(t.get('id'))}" not in have:
                have.add(f"done:{tk(t.get('id'))}")   # finished with no spec running: history, never replayed later
                seen.append(f"done:{tk(t.get('id'))}")
    for t in runs:
        if t.get("status") == "completed":
            meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
            outcome = str(meta.get("outcome") or "completed")
            tier = "critical" if outcome.startswith("failed") else "progress"
            rid = tk(t["id"])
            extra = {}
            if outcome.startswith("failed") and f"outcome:{rid}" not in have and not first:
                wt = meta.get("worktree") if isinstance(meta.get("worktree"), str) and meta.get("worktree") else None
                extra = _failed_run_log(project, now, wt, root) or {"no_run_log": True}
            emit(f"outcome:{rid}", _ev(project, _spec_name(t["subject"]), "spec_outcome", tier, outcome, now, thread_key=rid, **extra), history=True)
    for p in sorted(glob.glob(os.path.join(glob.escape(str(root)), "docs", "superpowers", "reports", "*-queue.md"))):
        name = os.path.basename(p)
        emit(f"report:{name}", _ev(project, "", "report_written", "progress", f"queue report: {_report_summary(Path(p))}", now, file=name, path=os.path.abspath(p)), history=True)
    if tasks:
        st["primed"] = True
        if list_id and list_id not in primed_lists:
            primed_lists.append(list_id)
    st["primed_lists"] = primed_lists[-50:]
    st["seen"] = seen[-SEEN_CAP:]
    return out, st


def merge_key(refs):
    """The source key of a merge approval: merge:<task>:<sha[:8]> (task ids restart per session, a moved branch is a new post)."""
    refs = refs or {}
    if not refs.get("task"):
        return ""
    sha = str(refs.get("sha") or "")[:8]
    return f"merge:{refs['task']}:{sha}" if sha else f"merge:{refs['task']}"


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
            if tier == "decision":
                op["key"] = merge_key(refs) if kind == "merge_approval" and refs.get("task") else \
                    "dec:" + hashlib.sha1(f"{ev.get('ts')}|{ev.get('text')}".encode()).hexdigest()[:12]
            if thread:
                op["link_thread_key"] = thread
        else:
            op = {"op": "post", "text": ev["text"], "tier": "progress", "mention_user": False}
            if thread and kind != "report_written":
                op["thread_key"] = thread
            if kind == "report_written" and refs.get("path"):
                op["files"] = [refs["path"]]
        ops.append(op)
        if kind == "spec_outcome" and refs.get("thread_key"):
            if str(ev.get("text", "")).startswith("failed"):
                if refs.get("log_file"):
                    ops.append({"op": "post", "text": f"failed run log: {refs.get('log_cmd', '')} (exit {refs.get('log_exit')}) · {refs.get('log_where', '')} · {refs.get('log_at', '')}",
                                "tier": "progress", "mention_user": False, "thread_key": refs["thread_key"], "files": [refs["log_file"]]})
                elif refs.get("no_run_log"):
                    ops.append({"op": "post", "text": "failed — no failing test run recorded", "tier": "progress",
                                "mention_user": False, "thread_key": refs["thread_key"]})
            ops.append({"op": "archive", "key": refs["thread_key"]})
    return ops


def _load(p):
    try:
        v = json.loads(Path(p).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def tick(project, record, root, now, lead_tasks=None, list_id="", live=None, limits=None, lead_sid=""):
    """One feed pass for a project under flock(<dir>/feed-state.lock); None when another tick holds it.
    derive -> append events to the feed file -> read every feed event since state["feed_offset"] (so events appended by
    other writers flow through too) -> outbox ops -> the card op when due -> feed-state.json.
    `lead_tasks` are the raw lead task dicts and `list_id` their task-list directory name (planview.raw_live_list).
    `live` (the indexer rows; None = no presence op), `limits` and `lead_sid` feed the ticker line of the throttled presence op."""
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
        pre, _ = read_events(project, st["feed_offset"])   # engine lines not yet consumed mark their spec before derive
        st = note_engine_specs(st, pre)
        events, st = derive(project, root, lead_tasks or [], st, now, list_id)
        for ev in events:
            append_event(project, ev)
        flow, st["feed_offset"] = read_events(project, st["feed_offset"])
        st = note_engine_specs(st, flow)
        ops = []
        for ev in flow:   # one malformed foreign event is logged and skipped; the offset still moves past it
            try:
                ops.extend(ops_for_events([ev], st))
            except Exception as e:   # noqa: BLE001
                print(f"discord_feed: skipped bad feed event ({project}): {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        text = render_card(record, lead_tasks or [], now, st.get("spec_floor", {}).get(st.get("running_thread_key")))
        card = card_op_due(st, text, now)
        if card:
            ops.append(card)
        pres, pline = None, ""
        if live is not None:
            try:
                import ticker
                pline = ticker.project_line(record, live, limits, lead_tasks or [], now,
                                            floor=st.get("spec_floor", {}).get(st.get("running_thread_key")), lead_sid=lead_sid)
                pres = presence_op_due(st, pline, now, _load(d / "bridge-state.json"))
            except Exception as e:   # noqa: BLE001 -- a bad line never stops the card or the other ops
                print(f"discord_feed: presence line failed ({project}): {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            if pres:
                ops.append(pres)
        written = 0
        pres_written = False
        for op in ops:
            try:
                outbox_write(d, op)
                written += 1
                if op is pres:
                    pres_written = True
            except ValueError as e:
                print(f"discord_feed: skipped bad op ({project}): {e}", file=sys.stderr, flush=True)
        if card:
            st["card_text"], st["card_ts"] = text, now
        if pres_written:
            st["presence_text"], st["presence_ts"] = pline, now
        tmp = sp.with_name(sp.name + ".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, sp)
        return {"events": len(flow), "ops": written}


# ---- board wiring: the notifier's sink, the channel check ----
NOTIFY_TIERS = {"needs_you": "decision", "test_failed": "critical", "failing": "critical", "stuck": "critical",
                "plan_done": "progress", "lead_idle": "routine", "context": "routine", "usage": "routine",
                "teammate_gone": "critical", "teammate_silent": "critical", "awake_dropped": "critical", "weekly_pace": "critical",
                "watch": "critical", "run_overdue": "critical"}


def channel_of(project):
    """The project's home channel id from <dir>/bridge.json, or ''."""
    import tc_env
    v = _load(tc_env.discord_dir(project) / "bridge.json").get("channel")
    return str(v) if v else ""


def sink_event(ev):
    """Notifier event -> one feed line. Quiet when the project has no channel. Raises on I/O errors (notify.discord_sink logs)."""
    import tc_env
    project = ev["project"]
    if not channel_of(project):
        return
    thread = _load(tc_env.discord_dir(project) / "feed-state.json").get("running_thread_key") or ""
    append_event(project, {"ts": ev.get("ts") or time.time(), "project": project, "spec": "", "kind": ev["kind"],
                           "tier": NOTIFY_TIERS.get(ev["kind"], "routine"), "text": f"{ev.get('title', '')}: {ev.get('text', '')}".strip(": "),
                           "refs": {"thread_key": thread} if thread else {}})
