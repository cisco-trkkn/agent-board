"""discord_ops: the board side of the ops bot (command center + approvals).

tick() renders the command-center card, writes <_ops>/views.json, mirrors each project's decision events into #approvals
and critical ones into #command-center, and keeps one approval per lead question. consume() reads the ops bridge's events
(<_ops>/events) and handle_event() serves both those and the slash/modal/read/rejected events a project's controls forward.
mirror_prompt()/resolve() copy a project's permission prompt into #approvals and edit it when answered.
Discord is never the source of truth: every action is checked against <_ops>/access.json and audited.
State lives in <_ops>/ops-state.json under flock(<_ops>/ops-state.lock). Test: tests/test_discord_ops.py."""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path

import discord_feed
import ideas
import tc_env

CARD_MAX = 1900
QUEUE_MAX = 1800
MIRRORED_KEEP = 2000
CONFIRM_S = 60
PROMPT_LINES = 15
FIELD_MAX = 300
DETAIL_MAX = 4000
OPEN_KEEP = 200        # newest `other`/`merge` approvals kept in the state
OPEN_TTL = 7 * 86400   # older ones leave views.json
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PAUSE_LINE = "[Discord] 🛑 pause the queue"
RESUME_LINE = "[Discord] ▶️ resume the queue"
# decision-tier kinds that are already covered by the perm mirror and the lead-question approval
_COVERED = ("needs_you",)


def _load(p):
    try:
        v = json.loads(Path(p).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(p, obj):
    p = Path(p)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def configured():
    b = _load(tc_env.ops_dir() / "bridge.json")
    return bool(b.get("command_center") and b.get("approvals"))


def _allow(d):
    a = _load(Path(d) / "access.json").get("allowFrom")
    return {str(x) for x in a} if isinstance(a, list) else set()


def _okey(project, src_key):
    return hashlib.sha1(f"{project}\0{src_key}".encode("utf-8")).hexdigest()[:12]


@contextlib.contextmanager
def _state(block):
    """Yield the ops state dict under flock, saved atomically on exit; None when block is False and the lock is held."""
    d = tc_env.ops_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "ops-state.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if block else fcntl.LOCK_NB))
        except OSError:
            yield None
            return
        st = _load(d / "ops-state.json")
        for k in ("offsets", "approvals", "questions", "queues"):
            if not isinstance(st.get(k), dict):
                st[k] = {}
        if not isinstance(st.get("mirrored"), list):
            st["mirrored"] = []
        try:
            yield st
        finally:
            _write_json(d / "ops-state.json", st)


# ---- rendering ----
def _pct(v):
    if isinstance(v, dict):
        v = v.get("used_percentage", v.get("utilization"))
    return f"{round(v)}%" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def queue_text(lead_tasks):
    """The /queue view: the queue line, then one line per `Plan & run:` task in id order."""
    tasks = [t for t in (lead_tasks or []) if isinstance(t, dict)]
    out = [discord_feed._queue(tasks)]
    runs = sorted((t for t in tasks if str(t.get("subject", "")).startswith(discord_feed._PLAN_RUN)), key=discord_feed._tid)
    for t in runs:
        mark = {"completed": "✓", "in_progress": "▶"}.get(t.get("status"), "·")
        meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        out.append(f"{mark} {discord_feed._spec_name(t['subject'])}" + (f" — {meta['outcome']}" if meta.get("outcome") else ""))
    return "\n".join(out)[:QUEUE_MAX]


def _project_line(record, tasks, link):
    p = record.get("project", "?")
    plan = record.get("plan") if isinstance(record.get("plan"), dict) else {}
    blockers = ", ".join(str(a.get("label", a.get("kind", "?"))) for a in record.get("alerts") or []) or "none"
    line = (f"**{p}** · {discord_feed._queue([t for t in (tasks or []) if isinstance(t, dict)])} · "
            f"{plan.get('done', 0)}/{plan.get('total', 0)} · blockers: {blockers} · "
            f"waiting on you: {len(record.get('needs_you') or [])}")
    return line + (f" · <{link}>" if link else "")


def _usage_line(records, limits):
    limits = limits or {}
    spends = [r["spend_today"] for r in records if isinstance(r.get("spend_today"), (int, float))]
    return f"usage: 5h {_pct(limits.get('five_hour'))} · week {_pct(limits.get('seven_day'))} · today ${sum(spends):.2f}" if spends \
        else f"usage: 5h {_pct(limits.get('five_hour'))} · week {_pct(limits.get('seven_day'))} · today $—"


def render_card(records, tasks_by_project, links, limits, now):
    """Plain text (no code block, so links render), at most CARD_MAX characters; overflow cut with '… <n> more'."""
    head = _usage_line(records, limits)
    body = [_project_line(r, (tasks_by_project or {}).get(r.get("project")), (links or {}).get(r.get("project"))) for r in records]
    tail = "updated " + time.strftime("%H:%M", time.localtime(now))
    keep = len(body)
    while True:
        more = [f"… {len(body) - keep} more"] if keep < len(body) else []
        text = "\n".join([head] + body[:keep] + more + [tail])
        if len(text) <= CARD_MAX or keep == 0:
            return text[:CARD_MAX]
        keep -= 1


def _link(project):
    """https://discord.com/channels/<guild>/<channel> for the project, '' when either is unknown."""
    d = tc_env.discord_dir(project)
    channel, guild = _load(d / "bridge.json").get("channel"), _load(d / "bridge-state.json").get("guild_id")
    return f"https://discord.com/channels/{guild}/{channel}" if channel and guild else ""


# ---- approvals ----
def _approve(d, st, project, src_key, kind, text, link="", title="", spec="", now=None):
    key = _okey(project, src_key)
    op = {"op": "approval", "key": key, "kind": kind, "text": text[:2000], "mention_user": True, "project": project}
    if link:
        op["link"] = link
    discord_feed.outbox_write(d, op)
    st["approvals"][key] = {"project": project, "kind": kind, "src_key": src_key, "title": title or text[:100], "link": link,
                            "spec": spec, "ts": now if now is not None else time.time()}
    return key


def _edit_ops(d, key, text):
    discord_feed.outbox_write(d, {"op": "edit", "key": key, "text": text[:2000]})


def _trim_open(st):
    """Keep the newest OPEN_KEEP `other`/`merge` approvals (nothing else resolves them when the decision is made elsewhere)."""
    old = sorted(((v.get("ts") or 0, k) for k, v in st["approvals"].items() if v.get("kind") in ("other", "merge")), reverse=True)
    for _, k in old[OPEN_KEEP:]:
        del st["approvals"][k]


def _approvals_view(st, now=None):
    now = time.time() if now is None else now
    return [{"key": k, "project": v.get("project"), "kind": v.get("kind"), "title": v.get("title"), "link": v.get("link")}
            for k, v in st["approvals"].items()
            if not (v.get("kind") in ("other", "merge") and now - (v.get("ts") or 0) > OPEN_TTL)]


def mirror_prompt(project, src_key, window, tool, lines):
    """Copy a teammate's permission prompt into #approvals (kind perm). No-op when ops is not configured."""
    if not configured():
        return
    with _state(True) as st:
        if _okey(project, src_key) in st["approvals"]:
            return
        body = "\n".join(str(l) for l in lines[:PROMPT_LINES])
        text = f"🔐 {project} · {window} wants to run {tool}\n```\n{body}\n```"
        _approve(tc_env.ops_dir(), st, project, src_key, "perm", text, title=f"{window} {tool}")


def resolve(project, src_key, text):
    """Edit the ops copy of an answered approval and drop it from views.json. No-op when ops is not configured or the key was never mirrored."""
    if not configured():
        return
    with _state(True) as st:
        key = _okey(project, src_key)
        if st["approvals"].pop(key, None) is None:
            return
        _edit_ops(tc_env.ops_dir(), key, f"{project}: {text}")
        vp = tc_env.ops_dir() / "views.json"
        v = _load(vp)
        if v:
            v["approvals"] = _approvals_view(st)
            _write_json(vp, v)


# ---- tick ----
def _event_key(project, ev):
    refs = ev.get("refs") or {}
    if ev.get("kind") == "merge_approval" and refs.get("task"):
        return f"merge:{refs['task']}"
    return ("crit:" if ev.get("tier") == "critical" else "dec:") + hashlib.sha1(f"{ev.get('ts')}|{ev.get('text')}".encode()).hexdigest()[:12]


def _mirror_events(d, st, project, link, now):
    fp = tc_env.feed_path(project)
    if project not in st["offsets"]:
        st["offsets"][project] = fp.stat().st_size if fp.exists() else 0   # first sight: no replay
        return
    events, st["offsets"][project] = discord_feed.read_events(project, st["offsets"][project])
    for ev in events:
        try:
            tier, kind = ev.get("tier"), ev.get("kind")
            if tier not in ("decision", "critical") or (tier == "decision" and kind in _COVERED):
                continue
            src = _event_key(project, ev)
            key = _okey(project, src)
            if key in st["mirrored"]:
                continue
            text = f"{project}: {ev.get('text', '')}"
            if tier == "decision":
                _approve(d, st, project, src, "merge" if kind == "merge_approval" else "other", text, link=link,
                         title=str(ev.get("text", ""))[:100], spec=str(ev.get("spec") or ""), now=now)
            else:
                discord_feed.outbox_write(d, {"op": "post", "text": text[:2000], "tier": "critical", "mention_user": True})
            st["mirrored"].append(key)
        except Exception as e:   # noqa: BLE001 -- one malformed event is skipped, the offset has moved past it
            print(f"discord_ops: skipped bad feed event ({project}): {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    st["mirrored"] = st["mirrored"][-MIRRORED_KEEP:]


def _lead_question(d, st, record, link, now):
    p = record["project"]
    waiting = any(n.get("window") == "claude" for n in record.get("needs_you") or [])
    key = st["questions"].get(p)
    if waiting and not key:
        st["questions"][p] = _approve(d, st, p, f"question:{p}:{int(now)}", "question", f"{p}: the lead is waiting on you", link=link, now=now)
    elif not waiting and key:
        del st["questions"][p]
        st["approvals"].pop(key, None)
        _edit_ops(d, key, f"{p}: answered")


def tick(records, tasks_by_project, limits, now, add_line):
    """One ops pass. None when ops is not configured or another tick holds the lock."""
    if not configured():
        return None
    d = tc_env.ops_dir()
    with _state(False) as st:
        if st is None:
            return None
        records = [r for r in records if isinstance(r, dict) and r.get("project")]
        links = {r["project"]: _link(r["project"]) for r in records}
        tasks_by_project = tasks_by_project or {}
        st["projects"] = sorted(r["project"] for r in records)
        st["queues"] = {r["project"]: discord_feed._queue(tasks_by_project.get(r["project"]) or []) for r in records}
        for r in records:
            _lead_question(d, st, r, links[r["project"]], now)
            _mirror_events(d, st, r["project"], links[r["project"]], now)
        _trim_open(st)
        text = render_card(records, tasks_by_project, links, limits, now)
        card = discord_feed.card_op_due(st, text, now)
        if card:
            discord_feed.outbox_write(d, card)
            st["card_text"], st["card_ts"] = text, now
        st["queue_ts"] = now
        status = {"_all": text}
        status.update({r["project"]: _project_line(r, tasks_by_project.get(r["project"]), links[r["project"]]) for r in records})
        _write_json(d / "views.json", {"ts": now, "projects": sorted(links), "status": status,
                                       "queue": {r["project"]: queue_text(tasks_by_project.get(r["project"])) for r in records},
                                       "approvals": _approvals_view(st, now), "evidence": {}})
        return {"approvals": len(st["approvals"])}


# ---- events ----
def _known(project):
    """A project of the last tick's records, or one with a discord dir."""
    if not project or PROJECT_RE.match(str(project)) is None:
        return False
    return project in (_load(tc_env.ops_dir() / "ops-state.json").get("projects") or []) or tc_env.discord_dir(project).is_dir()


def _collapse(v, n=FIELD_MAX):
    return " ".join(str(v or "").split())[:n]


def _write_event(project, ev):
    d = tc_env.discord_dir(project) / "events"
    d.mkdir(parents=True, exist_ok=True)
    name = f"{discord_feed._next_ms():013d}-{secrets.token_hex(4)}"
    _write_json(d / f"{name}.tmp", ev)
    os.replace(d / f"{name}.tmp", d / f"{name}.json")


def handle_event(project, d, ev, add_line, allow):
    """slash / modal / read / rejected: act, audit in <d>/audit.jsonl, return the audit result. `project` is the default
    when the event names none (events forwarded from a project's controls)."""
    user, kind = str(ev.get("user") or ""), str(ev.get("type") or "")
    project = ev.get("project") or project
    target = str(ev.get("command") or ev.get("form") or ev.get("what") or "")
    if kind == "rejected" or user not in allow:
        result = "rejected"
    elif kind == "read":
        result = "answered"
    elif not _known(project):
        result = "unknown project"
    elif kind == "slash":
        line = {"pause": PAUSE_LINE, "resume": RESUME_LINE}.get(ev.get("command"))
        if line:
            add_line(project, line)
        result = "queued" if line else "ignored"
    elif kind == "modal":
        f = ev.get("fields") if isinstance(ev.get("fields"), dict) else {}
        if ev.get("form") == "idea":
            title = _collapse(f.get("title"))
            try:
                ideas.add(project, title, detail=str(f.get("text") or "")[:DETAIL_MAX])
                result = "idea added"
            except ValueError:
                result = "invalid"
        elif ev.get("form") == "new-spec":
            what, why = _collapse(f.get("what")), _collapse(f.get("why"))
            if what:
                add_line(project, f"[Discord] new spec request: {what} — {why}")
            result = "queued" if what else "invalid"
        else:
            result = "ignored"
    else:
        result = "ignored"
    discord_feed.audit_append(d, user, kind, f"{project}:{target}" if target else str(project or ""), result)
    return result


def _default_merge(project, src_key, rec, add_line, now):
    import discord_merge   # Task 5; imported here so this module loads without it
    return discord_merge.on_merge(project, src_key, rec, add_line, now)


def _edit_both(project, ops_key, src_key, text):
    """Edit the ops copy (`<project>: <text>`) and the project channel's copy (key = the source key)."""
    _edit_ops(tc_env.ops_dir(), ops_key, f"{project}: {text}")
    discord_feed.outbox_write(tc_env.discord_dir(project), {"op": "edit", "key": src_key, "text": text[:2000]})


def _line_all(st, prefix, line, add_line):
    names = [p for p, q in sorted(st["queues"].items()) if str(q).startswith(prefix)]
    for p in names:
        add_line(p, line)
    return len(names)


def _click(d, user, cid, st, add_line, now, on_merge):
    parts = cid.split(":")
    if parts[:2] != ["ab", "ops"] or len(parts) < 3:
        return "ignored"
    act, k = parts[2], ":".join(parts[3:])
    if act in ("allow", "deny"):
        rec = st["approvals"].get(k)
        if not rec or rec.get("kind") != "perm":
            return "unknown"
        _write_event(rec["project"], {"type": "perm", "key": rec["src_key"], "choice": act, "user": user, "ts": now})
        return "forwarded"
    if act == "pause-all-confirm":
        try:
            ms = int(k)
        except ValueError:
            return "ignored"
        if now - ms / 1000 > CONFIRM_S:
            return "expired"
        return f"queued {_line_all(st, 'queue: running', PAUSE_LINE, add_line)}"
    if act == "resume-all":
        return f"queued {_line_all(st, 'queue: paused', RESUME_LINE, add_line)}"
    if act in ("merge", "keep"):
        rec = st["approvals"].get(k)
        if not rec or rec.get("kind") != "merge":
            return "unknown"
        if act == "merge":
            r = (on_merge or _default_merge)(rec["project"], rec["src_key"], dict(rec), add_line, now)
            result, text = str(r["result"]), str(r["text"])
        else:
            add_line(rec["project"], f"[Discord] keep branch for {rec.get('spec') or rec.get('title')}")
            result, text = "queued", "kept"
        _edit_both(rec["project"], k, rec["src_key"], text)
        st["approvals"].pop(k, None)   # only after the action went through: a failure leaves the record and the button live
        return result
    return "ignored"


def consume(add_line, run, now, on_merge=None):
    """Process <_ops>/events in filename order; each file once, audited in <_ops>/audit.jsonl. None when not configured."""
    if not configured():
        return None
    d = tc_env.ops_dir()
    ev_dir = d / "events"
    if not any(ev_dir.glob("*.json")):
        return None
    done = 0
    with _state(True) as st:
        for f in sorted(ev_dir.glob("*.json")):
            try:
                ev = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(ev, dict):
                    raise ValueError("not an object")
            except (OSError, ValueError):
                (ev_dir / "failed").mkdir(exist_ok=True)
                os.replace(f, ev_dir / "failed" / f.name)
                continue
            try:
                user, kind = str(ev.get("user") or ""), str(ev.get("type") or "")
                allow = _allow(d)
                if kind == "click":
                    cid = str(ev.get("custom_id") or "")
                    result = _click(d, user, cid, st, add_line, now, on_merge) if user in allow else "rejected"
                    discord_feed.audit_append(d, user, "click", cid, result)
                else:
                    handle_event(None, d, ev, add_line, allow)
                done += 1
            except Exception as e:   # noqa: BLE001 -- one bad event never blocks the rest
                print(f"discord_ops: event {f.name} failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                first = (str(e).splitlines() or [type(e).__name__])[0]
                discord_feed.audit_append(d, str(ev.get("user") or ""), str(ev.get("type") or ""), str(ev.get("custom_id") or ev.get("what") or ""),
                                          f"error: {first}"[:200])
            finally:
                try:
                    f.unlink()
                except OSError:
                    pass
    return {"events": done}
