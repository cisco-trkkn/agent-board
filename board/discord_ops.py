"""discord_ops: the board side of the ops bot (command center + approvals).

tick() renders the command-center card, writes <_ops>/views.json, mirrors each project's decision events into #approvals
and critical ones into #command-center, and keeps one approval per lead question. consume() reads the ops bridge's events
(<_ops>/events) and handle_event() serves both those and the slash/modal/read/rejected events a project's controls forward.
consume() also routes `ab:dlg:` dialog clicks and `reply` events to discord_dialogs (dialogs of sessions without a channel).
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
import threading
import time
from pathlib import Path

import analytics_post
import discord_dialogs
import discord_feed
import discord_ideas
import gauth
import ideas
import newproject
import relay
import tc_env
import usage

CARD_MAX = 1900
QUEUE_MAX = 1800
MIRRORED_KEEP = 2000
CONFIRM_S = 60
FIELD_MAX = 300
DETAIL_MAX = 4000
OPEN_KEEP = 200        # newest `other`/`merge` approvals kept in the state
OPEN_TTL = 7 * 86400   # older ones leave views.json
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PAUSE_LINE = "[Discord] 🛑 pause the queue"
RESUME_LINE = "[Discord] ▶️ resume the queue"
GAUTH_WINDOW_S = 600   # the code is accepted this long after the URL was sent
GAUTH_URL_WAIT_S = 30
GAUTH_RESULT_WAIT_S = 60
_clock, _sleep = time.time, time.sleep   # seams: tests drive the URL poll and the result wait without waiting
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
        for k in ("offsets", "approvals", "questions", "queues", "paused_by_ops"):
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


def queue_text(lead_tasks, floor=None):
    """The /queue view: the queue line, then one line per `Plan & run:` task in id order."""
    tasks = [t for t in (lead_tasks or []) if isinstance(t, dict)]
    out = [discord_feed._queue(tasks, floor)]
    runs = sorted((t for t in tasks if str(t.get("subject", "")).startswith(discord_feed._PLAN_RUN)), key=discord_feed._tid)
    for t in runs:
        mark = {"completed": "✓", "in_progress": "▶"}.get(t.get("status"), "·")
        meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
        out.append(f"{mark} {discord_feed._spec_name(t['subject'])}" + (f" — {meta['outcome']}" if meta.get("outcome") else ""))
    return "\n".join(out)[:QUEUE_MAX]


def tasks_text(lead_tasks, floor):
    """The /tasks view: the running Plan & run task's own tasks, `#id status owner tier subject[:60]`, at most QUEUE_MAX chars.
    '' when the floor is unknown or the spec has no tasks."""
    if floor is None:
        return ""
    own = [t for t in (lead_tasks or []) if isinstance(t, dict) and not str(t.get("subject", "")).startswith(discord_feed._PLAN_RUN)
           and (discord_feed._num(t.get("id")) or 0) > floor]
    own.sort(key=discord_feed._tid)
    lines = [f"#{t.get('id')} {t.get('status') or '-'} {t.get('owner') or '-'} {discord_feed._tier(t) or '-'} {str(t.get('subject') or '')[:60]}"
             for t in own]
    return "\n".join(lines)[:QUEUE_MAX]


SPEC_MAX, PROBLEM_MAX, LABEL_MAX = 1900, 600, 100
_SPEC_CACHE = {}   # (resolved path, mtime) -> (title, problem); status and branch change without the file, so they are not cached
_STATUS_WORDS = {"pending": "pending", "in_progress": "in progress", "completed": "completed"}


def _spec_path(task):
    """(path text, `#part-n` suffix or '') from a `Plan & run:` subject; the trailing ` (…)` is dropped."""
    subj = (task or {}).get("subject") if isinstance(task, dict) else None
    subj = subj if isinstance(subj, str) else ""
    if not subj.startswith(discord_feed._PLAN_RUN):
        return "", ""
    rest = re.sub(r"\s+\([^()]*\)\s*$", "", subj[len(discord_feed._PLAN_RUN):].strip())
    path, _, frag = rest.partition("#")
    return path.strip(), ("#" + frag if frag else "")


def _spec_parts(root, path):
    """(title, problem) of the spec file, cached per (resolved path, mtime); None when it cannot be read."""
    if not root or not path:
        return None
    try:
        base = Path(root).resolve()
        f = (base / path).resolve()
        f.relative_to(base)   # ValueError: outside the repo root
        key = (str(f), f.stat().st_mtime)
        if key not in _SPEC_CACHE:
            text = f.read_text(errors="replace")
            title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), "")
            m = re.search(r"^## Problem[ \t]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
            problem = " ".join(m.group(1).split()) if m else ""
            if len(problem) > PROBLEM_MAX:
                problem = problem[:PROBLEM_MAX - 1].rsplit(" ", 1)[0].rstrip() + "…"
            if len(_SPEC_CACHE) > 200:
                _SPEC_CACHE.clear()
            _SPEC_CACHE[key] = (title, problem)
        return _SPEC_CACHE[key]
    except (OSError, ValueError, RuntimeError):
        return None


def spec_label(task):
    path, part = _spec_path(task)
    name = os.path.basename(path)
    if not name:
        return f"task {task.get('id') if isinstance(task, dict) else ''}".strip()[:LABEL_MAX]
    return (name + part)[:LABEL_MAX]


def spec_summary(root, task):
    """The /queue spec summary of one `Plan & run:` task: title, Problem excerpt, status, branch. Never raises."""
    try:
        return _spec_summary(root, task)
    except Exception:   # noqa: BLE001 -- one odd task dict must not abort the ops tick
        return f"**{spec_label(task)}**\n(spec file not found)\nStatus: pending\nBranch: not started"[:SPEC_MAX]


def _spec_summary(root, task):
    task = task if isinstance(task, dict) else {}
    path, _ = _spec_path(task)
    parts = _spec_parts(root, path)
    name = os.path.basename(path) or spec_label(task)
    if parts:
        head = [f"**{parts[0] or name}**"] + ([parts[1]] if parts[1] else [])
    else:
        head = [f"**{name}**", "(spec file not found)"]
    meta = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    st = task.get("status")
    status = _STATUS_WORDS.get(st, str(st)) if isinstance(st, str) and st else "pending"
    if meta.get("outcome"):
        status += f" — {meta['outcome']}"
    if meta.get("branch"):
        branch = f"Branch: {meta['branch']}" + (f" · worktree {meta['worktree']}" if meta.get("worktree") else "")
    else:
        branch = "Branch: not started"
    tail = f"\nStatus: {status}\n{branch}"
    return ("\n".join(head)[:max(0, SPEC_MAX - len(tail))] + tail)[:SPEC_MAX]


def specs_view(root, lead_tasks):
    runs = sorted((t for t in (lead_tasks or []) if isinstance(t, dict) and str(t.get("subject", "")).startswith(discord_feed._PLAN_RUN)),
                  key=discord_feed._tid)
    return [{"key": str(t.get("id")), "label": spec_label(t), "summary": spec_summary(root, t)} for t in runs]


def lead_view(info, holders, tap, handoffs, now):
    """One project's views.json `leads` entry; every missing value is null."""
    sid = info.get("session_id") or None
    pct = usage._get(tap.get(sid), "context_window", "used_percentage") if sid else None
    doc = age = None
    if info.get("root"):
        doc = relay.newest_handoff(info["root"], handoffs)
        if doc:
            try:
                age = max(0, int(now - os.path.getmtime(doc)))
            except OSError:
                doc = None
    return {"window": info.get("window") or None, "pane": info.get("pane") or None, "pid": info.get("pid") or None,
            "state": info.get("state") or None, "holds_bot": info.get("pane") in holders,
            "context_pct": pct if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None,
            "session_id": sid, "doc": doc, "doc_age_s": age}


BLOCKING = ("failing", "stuck")


def _project_line(record, tasks, link, floor=None):
    p = record.get("project", "?")
    al = [a for a in record.get("alerts") or [] if isinstance(a, dict)]
    label = lambda a: str(a.get("label", a.get("kind", "?")))
    blockers = ", ".join(label(a) for a in al if a.get("kind") in BLOCKING) or "none"
    others = ", ".join(label(a) for a in al if a.get("kind") not in BLOCKING)
    queue = discord_feed._queue([t for t in (tasks or []) if isinstance(t, dict)], floor)
    line = (f"**{p}** · {queue} · blockers: {blockers}" + (f" · alerts: {others}" if others else "")
            + f" · waiting on you: {len(record.get('needs_you') or [])}")
    return line + (f" · <{link}>" if link else "")


def _usage_line(records, limits):
    limits = limits or {}
    spends = [r["spend_today"] for r in records if isinstance(r.get("spend_today"), (int, float))]
    return f"usage: 5h {_pct(limits.get('five_hour'))} · week {_pct(limits.get('seven_day'))} · today ${sum(spends):.2f}" if spends \
        else f"usage: 5h {_pct(limits.get('five_hour'))} · week {_pct(limits.get('seven_day'))} · today $—"


def render_card(records, tasks_by_project, links, limits, now, floors=None):
    """Plain text (no code block, so links render), at most CARD_MAX characters; overflow cut with '… <n> more'."""
    head = _usage_line(records, limits)
    body = [_project_line(r, (tasks_by_project or {}).get(r.get("project")), (links or {}).get(r.get("project")),
                           (floors or {}).get(r.get("project"))) for r in records]
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
def _approve(d, st, project, src_key, kind, text, link="", title="", spec="", now=None, branch=""):
    key = _okey(project, src_key)
    op = {"op": "approval", "key": key, "kind": kind, "text": text[:2000], "mention_user": True, "project": project}
    if link:
        op["link"] = link
    discord_feed.outbox_write(d, op)
    st["approvals"][key] = {"project": project, "kind": kind, "src_key": src_key, "title": ((title or text).splitlines() or [""])[0][:100], "link": link,
                            "spec": spec, "ts": now if now is not None else time.time()}
    if branch:
        st["approvals"][key]["branch"] = branch   # the keep edit names it
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


def _evidence_view(st):
    """views.json `evidence`: per open merge approval (keyed by its ops key) the files and diffs `discord merge-request` stored."""
    out = {}
    for k, v in st["approvals"].items():
        m = re.match(r"^merge:([A-Za-z0-9._-]+)(?::([0-9a-f]{8}))?$", str(v.get("src_key") or ""))
        if v.get("kind") != "merge" or not m or not PROJECT_RE.match(str(v.get("project"))):
            continue
        ev = _load(tc_env.ops_dir() / "evidence" / f"{v['project']}-{m.group(1)}.json")
        if ev.get("sha") and (not m.group(2) or str(ev["sha"])[:8] == m.group(2)):
            out[k] = {"files": ev.get("files") or [], "diffs": ev.get("diffs") or {}}
    return out


# ---- tick ----
def _event_key(project, ev):
    refs = ev.get("refs") or {}
    if ev.get("kind") == "merge_approval" and refs.get("task"):
        return discord_feed.merge_key(refs)
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
                         title=str(ev.get("text", ""))[:100], spec=str(ev.get("spec") or ""), now=now,
                         branch=str((ev.get("refs") or {}).get("branch") or ""))
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


def tick(records, tasks_by_project, limits, now, add_line, live=None, lead_sids=None, lead_info=None, holder_panes=None, handoffs=None):
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
        floors = {r["project"]: discord_feed.spec_floor(r["project"]) for r in records}
        st["projects"] = sorted(r["project"] for r in records)
        st["queues"] = {r["project"]: discord_feed._queue(tasks_by_project.get(r["project"]) or [], floors[r["project"]]) for r in records}
        for r in records:
            _lead_question(d, st, r, links[r["project"]], now)
            _mirror_events(d, st, r["project"], links[r["project"]], now)
        _trim_open(st)
        try:
            gauth_sweep(d, now)
        except Exception as e:   # noqa: BLE001 -- a bad pending record never stops the card
            print(f"discord_ops: gauth sweep skipped: {type(e).__name__}", file=sys.stderr, flush=True)
        try:
            newproject.tick(d, now)
        except Exception as e:   # noqa: BLE001 -- a bad setup record never stops the card
            print(f"discord_ops: newproject tick skipped: {type(e).__name__}", file=sys.stderr, flush=True)
        text = render_card(records, tasks_by_project, links, limits, now, floors)
        card = discord_feed.card_op_due(st, text, now)
        if card:
            discord_feed.outbox_write(d, card)
            st["card_text"], st["card_ts"] = text, now
        if live is not None:   # the ops bot's custom status; a bad line or op is logged and never stops the views
            try:
                import ticker
                pline = ticker.ops_line(records, live, limits, tasks_by_project, now, floors=floors, lead_sids=lead_sids or {})
                pres = discord_feed.presence_op_due(st, pline, now, _load(d / "bridge-state.json"))
                if pres:
                    discord_feed.outbox_write(d, pres)
                    st["presence_text"], st["presence_ts"] = pline, now
            except Exception as e:   # noqa: BLE001 -- ValueError from _check, or anything ticker raised
                print(f"discord_ops: presence skipped: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        st["queue_ts"] = now
        status = {"_all": text}
        status.update({r["project"]: _project_line(r, tasks_by_project.get(r["project"]), links[r["project"]], floors[r["project"]]) for r in records})
        tasks_view = {}
        for r in records:
            tt = tasks_text(tasks_by_project.get(r["project"]), floors[r["project"]])
            if tt:
                tasks_view[r["project"]] = tt
        leads_view = {}
        lead_info = {p: i for p, i in (lead_info or {}).items() if isinstance(i, dict)}
        if lead_info:
            try:   # one holder lookup for every lead; a failure leaves the leads without the bot
                holders = holder_panes([(i.get("pane"), i.get("pane_pid")) for i in lead_info.values()]) if holder_panes else set()
            except Exception as e:   # noqa: BLE001
                print(f"discord_ops: holder lookup skipped: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                holders = set()
            try:
                tap = usage.tap_entries(now, 3600)
            except Exception:   # noqa: BLE001 -- no taps: context unknown
                tap = {}
            hd = handoffs or str(tc_env.agent_base() / "handoffs")
            for p, i in lead_info.items():
                leads_view[p] = lead_view(i, holders, tap, hd, now)
        specs = {r["project"]: specs_view((lead_info.get(r["project"]) or {}).get("root"), tasks_by_project.get(r["project"])) for r in records}
        _write_json(d / "views.json", {"tasks": tasks_view, "leads": leads_view, "specs": specs, "ts": now, "projects": sorted(links), "status": status,
                                       "queue": {r["project"]: queue_text(tasks_by_project.get(r["project"]), floors[r["project"]]) for r in records},
                                       "approvals": _approvals_view(st, now), "evidence": _evidence_view(st)})
        return {"approvals": len(st["approvals"])}


# ---- events ----
def _known(project):
    """A project of the last tick's records, or one with a discord dir."""
    if not project or PROJECT_RE.match(str(project)) is None:
        return False
    return project in (_load(tc_env.ops_dir() / "ops-state.json").get("projects") or []) or tc_env.discord_dir(project).is_dir()


def _collapse(v, n=FIELD_MAX):
    return " ".join(str(v or "").split())[:n]


# ---- /lead and /gauth ----
# The slow steps (lead-restart's wait, the URL poll, the result wait) run in a worker started through `spawn`, so consume (called
# under the ops-state lock from the board's refresh) returns at once. The worker audits its own final result.
_PEND_LOCK = threading.Lock()   # the worker and consume/tick both read-modify-write gauth-pending.json


def _spawn_thread(fn):
    threading.Thread(target=fn, daemon=True).start()


def _ireply(d, iid, content, **kw):
    if iid:
        discord_feed.outbox_write(d, {"op": "ireply", "iid": str(iid), "content": str(content)[:1900], **kw})


def _pending_path():
    return tc_env.ops_dir() / "gauth-pending.json"


def _pending_load():
    return {k: v for k, v in _load(_pending_path()).items() if isinstance(v, dict)}


def _pending_save(pend):
    _write_json(_pending_path(), pend)


def _pending_update(project, fn):
    """Read-modify-write one project's record under the lock; fn(rec_or_None) returns the new record or None to delete it."""
    with _PEND_LOCK:
        pend = _pending_load()
        new = fn(pend.get(project))
        if new is None:
            pend.pop(project, None)
        else:
            pend[project] = new
        _pending_save(pend)


def _worker(d, user, kind, target, iid, fn):
    """Run fn() -> (result, reply_or_None, reply_kw); any exception becomes a failed result. Audits and replies once."""
    try:
        result, reply, kw = fn()
    except Exception as e:   # noqa: BLE001 -- the text can echo the code: only the class leaves the worker
        result, reply, kw = "failed", f"failed ({type(e).__name__})", {}
    try:
        if reply:
            _ireply(d, iid, reply, **kw)
    finally:
        discord_feed.audit_append(d, user, kind, target, result)


def _lead_event(d, project, user, ev, run, spawn):
    action, iid = ev.get("action"), ev.get("iid")
    if action not in ("restart", "handoff"):
        return "ignored"
    if run is None:
        _ireply(d, iid, "not available here")
        return "ignored"
    argv = [str(discord_dialogs.BIN / "tmux-ctl"), "lead-restart", project]
    if action == "restart":
        argv.append("--resume")
    else:
        doc = ((_load(tc_env.ops_dir() / "views.json").get("leads") or {}).get(project) or {}).get("doc")
        if not doc:
            _ireply(d, iid, f"no handoff doc for {project}")
            return "no handoff doc"
        argv += ["--doc", str(doc)]

    def go():
        try:
            out = str(run(argv) or "").strip()
        except Exception as e:   # noqa: BLE001 -- the tool's own error text goes back to the user
            return "failed", f"lead-restart failed: {_collapse(e, 500) or type(e).__name__}", {}
        return "restarted", out.splitlines()[-1] if out else f"restarted {project}", {}
    spawn(lambda: _worker(d, user, "slash", f"{project}:lead:{action}", iid, go))
    return "started"


def _gauth_close(project):
    try:
        gauth.close(project)
    except Exception as e:   # noqa: BLE001
        print(f"discord_ops: gauth close failed ({project}): {type(e).__name__}", file=sys.stderr, flush=True)
    _pending_update(project, lambda r: None)


def _gauth_slash(d, project, user, ev, spawn):
    iid = ev.get("iid")
    try:
        gauth.load_config(project)
    except gauth.GauthError as e:
        _ireply(d, iid, str(e), private=True)
        return "no config"
    except Exception as e:   # noqa: BLE001
        _ireply(d, iid, f"gauth failed ({type(e).__name__})", private=True)
        return "failed"
    try:
        busy = gauth.status(project) == "waiting" or project in _pending_load()
    except Exception as e:   # noqa: BLE001
        _ireply(d, iid, f"gauth failed ({type(e).__name__})", private=True)
        return "failed"
    if busy:
        _ireply(d, iid, f"a /gauth for {project} is already waiting for its code", private=True)
        return "busy"
    # the record exists before the worker runs: a worker that dies leaves it for the tick sweep to close
    _pending_update(project, lambda r: {"project": project, "user": user, "iid": str(iid or ""), "url_ts": _clock()})

    def go():
        try:
            gauth.start(project)
            url, end = None, _clock() + GAUTH_URL_WAIT_S
            while True:
                url = gauth.read_url(project, timeout=0)
                if url or _clock() >= end:
                    break
                _sleep(1)
        except gauth.GauthError as e:
            _gauth_close(project)
            return "failed", str(e), {"private": True}
        except Exception as e:   # noqa: BLE001
            _gauth_close(project)
            return "failed", f"gauth failed ({type(e).__name__}); closed", {"private": True}
        if not url:
            _gauth_close(project)
            return "failed", f"no sign-in URL appeared within {GAUTH_URL_WAIT_S} s; closed", {"private": True}
        _pending_update(project, lambda r: {**(r or {"project": project, "user": user, "iid": str(iid or "")}), "url_ts": _clock()})
        return ("url sent",
                f"Open this URL, sign in with Google, then press Enter code and paste the code (valid 10 min):\n{url}",
                {"components": [[{"label": "Enter code", "style": 1, "custom_id": f"ab:gauth:code:{project}"}]], "private": True})
    spawn(lambda: _worker(d, user, "slash", f"{project}:gauth", iid, go))
    return "started"


def _gauth_modal(d, project, user, ev, spawn):
    with _PEND_LOCK:
        pend = _pending_load()
        rec = pend.get(project)
        if not rec or rec.get("user") != user or rec.get("sending"):
            return "ignored"
        late = _clock() - (rec.get("url_ts") or 0) > GAUTH_WINDOW_S
        if not late:
            rec["sending"] = True
            _pending_save(pend)
    iid = rec.get("iid")
    if late:
        _gauth_close(project)
        _ireply(d, iid, f"gauth for {project} timed out; run /gauth again", private=True)
        return "timed out"
    code = str(ev.get("text") or "").strip()

    def go():
        try:
            cfg = gauth.load_config(project)
            gauth.send_code(project, code)
            res, end = None, _clock() + GAUTH_RESULT_WAIT_S
            while True:
                res = gauth.result(project)
                if res or _clock() >= end:
                    break
                _sleep(1)
            if res and res[0] == "ok":
                outcome, result = f"authenticated: {gauth.token_check(cfg)}", "authenticated"
            else:
                outcome, result = "auth failed: " + (str(res[1]) if res else f"no result in {GAUTH_RESULT_WAIT_S} s"), "auth failed"
            outcome = outcome.replace(code, "***") if code else outcome
        except Exception as e:   # noqa: BLE001 -- the text can echo the code: only the class leaves this function
            outcome, result = f"auth failed ({type(e).__name__}); run /gauth again", "auth failed"
        _gauth_close(project)
        return result, outcome, {"private": True}
    spawn(lambda: _worker(d, user, "modal", f"{project}:gauth", iid, go))
    return "started"


def gauth_sweep(d, now):
    """tick: close every waiting gauth whose code window has passed, tell its interaction, audit it."""
    with _PEND_LOCK:
        pend = _pending_load()
    for project, rec in list(pend.items()):
        if now - (rec.get("url_ts") or 0) > GAUTH_WINDOW_S:
            _gauth_close(project)
            _ireply(d, rec.get("iid"), f"gauth for {project} timed out; run /gauth again", private=True)
            discord_feed.audit_append(d, str(rec.get("user") or ""), "gauth", f"{project}:gauth", "timed out")


def _queue_cards(d):
    """/queue with no project: one post per project with a lead, its queue block and a select of its specs (first 25)."""
    views = _load(Path(d) / "views.json")
    queue = views.get("queue") if isinstance(views.get("queue"), dict) else {}
    specs = views.get("specs") if isinstance(views.get("specs"), dict) else {}
    leads = views.get("leads") if isinstance(views.get("leads"), dict) else {}
    queue = {p: t for p, t in queue.items() if p in leads}
    for p, text in queue.items():
        sp = specs.get(p) if isinstance(specs.get(p), list) else []
        op = {"op": "post", "text": str(text), "tier": "progress", "mention_user": False}
        if len(sp) > 25:
            op["text"] = (op["text"] + f"\n\u2026 {len(sp) - 25} more")
        op["text"] = op["text"][:2000]
        if sp:
            op["select"] = {"custom_id": f"ab:ops:spec:{p}", "placeholder": "Pick a spec",
                            "options": [{"label": str(x["label"]), "value": str(x["key"])} for x in sp[:25]]}
        discord_feed.outbox_write(d, op)
    return f"posted {len(queue)}"


def handle_event(project, d, ev, add_line, allow, run=None, spawn=None, st=None):
    """slash / modal / read / rejected: act, audit in <d>/audit.jsonl, return the audit result. `project` is the default
    when the event names none (events forwarded from a project's controls)."""
    user, kind = str(ev.get("user") or ""), str(ev.get("type") or "")
    ideas_slash = kind == "slash" and ev.get("command") == "ideas"
    if ideas_slash:   # /ideas never defaults to the channel's project: a null project means every project
        project = ev.get("project")
    else:
        project = ev.get("project") or project
    target = str(ev.get("command") or ev.get("form") or ev.get("what") or "")
    spawn = spawn or _spawn_thread
    if kind == "np_token" or (kind == "modal" and ev.get("form") == "new-project") or (kind == "slash" and ev.get("command") == "new-project"):
        return _new_project(d, ev, user, kind, allow)
    if kind == "rejected" or user not in allow:
        result = "rejected"
    elif kind == "read":
        result = "answered"
    elif ideas_slash:
        bridge = str(ev.get("bridge") or "_ops")   # the ops bot's /ideas posts in #command-center; a project bot's in its own channel
        if bridge == "_ops":
            result = discord_ideas.request(ev.get("project"), "_ops", add_line, time.time())
        elif ev.get("project") and ev.get("project") != bridge:
            result = "refused: other project"
        else:
            result = discord_ideas.request(bridge, bridge, add_line, time.time())
        discord_feed.audit_append(d, user, kind, f"ideas:{ev.get('project') or 'all'}", result)
        return result
    elif kind == "slash" and ev.get("command") == "queue" and not project:
        result = _queue_cards(d)
        discord_feed.audit_append(d, user, kind, "queue:cards", result)
        return result
    elif not _known(project):
        result = "unknown project"
        if kind == "slash" and ev.get("command") in ("lead", "gauth"):
            _ireply(d, ev.get("iid"), "unknown project")
    elif kind == "slash" and ev.get("command") == "lead":
        result = _lead_event(d, project, user, ev, run, spawn)
        target = f"lead:{ev.get('action')}"
    elif kind == "slash" and ev.get("command") == "gauth":
        result = _gauth_slash(d, project, user, ev, spawn)
        target = "gauth"
    elif kind == "modal" and ev.get("form") == "gauth":
        result = _gauth_modal(d, project, user, ev, spawn)
        target = "gauth"
    elif kind == "slash":
        line = {"pause": PAUSE_LINE, "resume": RESUME_LINE}.get(ev.get("command"))
        if line:
            if st is not None:   # remember who paused: the lead line leaves the task list reading running
                pb = st.setdefault("paused_by_ops", {})
                if ev.get("command") == "pause":
                    pb[project] = time.time()
                else:
                    pb.pop(project, None)
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
    if result == "started":   # a worker audits the final result itself
        return result
    discord_feed.audit_append(d, user, kind, f"{project}:{target}" if target else str(project or ""), result)
    return result


def _new_project(d, ev, user, kind, allow):
    """/new-project's form, its resume and its pasted token (board/newproject.py). Audited here, never with the token."""
    f = ev.get("fields") if isinstance(ev.get("fields"), dict) else {}
    name = str(ev.get("name") or f.get("name") or "")[:60]
    if user not in allow:
        if kind == "np_token":
            newproject.drop_token_file(ev)
        result = "rejected"
    elif kind == "np_token":
        result = newproject.on_token(d, ev)
    elif kind == "slash":
        result = newproject.on_slash(d, ev)
    else:
        result = newproject.on_modal(d, ev)
    discord_feed.audit_append(d, user, kind, f"{name}:new-project", result)
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
    return names


def _pause_all(st, add_line, now):
    """Pause every running queue and remember it: the pause is a lead line, so the task list still reads running."""
    names = _line_all(st, "queue: running", PAUSE_LINE, add_line)
    for p in names:
        st["paused_by_ops"][p] = now
    return len(names)


def _resume_all(st, add_line):
    """Resume every project whose queue reads paused or that this bot paused; clear the paused_by_ops entries."""
    names = {p for p, q in st["queues"].items() if str(q).startswith("queue: paused")} | set(st["paused_by_ops"])
    for p in sorted(names):
        add_line(p, RESUME_LINE)
        st["paused_by_ops"].pop(p, None)
    return len(names)


def _click(d, user, cid, st, add_line, now, on_merge):
    parts = cid.split(":")
    if parts[:2] == ["ab", "ideas"]:
        return discord_ideas.click(user, cid, add_line, now)
    if parts[:2] == ["ab", "analytics"]:
        return analytics_post.click(d, user, cid, now)
    if parts[:2] == ["ab", "np"]:
        return newproject.on_click(d, user, cid)
    if parts[:2] != ["ab", "ops"] or len(parts) < 3:
        return "ignored"
    act, k = parts[2], ":".join(parts[3:])
    if act == "pause-all-confirm":
        try:
            ms = int(k)
        except ValueError:
            return "ignored"
        if now - ms / 1000 > CONFIRM_S:
            return "expired"
        return f"queued {_pause_all(st, add_line, now)}"
    if act == "resume-all":
        return f"queued {_resume_all(st, add_line)}"
    if act in ("merge", "keep"):
        rec = st["approvals"].get(k)
        if not rec or rec.get("kind") != "merge":
            return "unknown"
        if act == "merge":
            r = (on_merge or _default_merge)(rec["project"], rec["src_key"], dict(rec), add_line, now)
            result, text = str(r["result"]), str(r["text"])
        else:
            add_line(rec["project"], f"[Discord] keep branch for {rec.get('spec') or rec.get('title')}")
            result, text = "queued", f"kept: {rec['branch']}" if rec.get("branch") else "kept"
        _edit_both(rec["project"], k, rec["src_key"], text)
        st["approvals"].pop(k, None)   # only after the action went through: a failure leaves the record and the button live
        return result
    return "ignored"


def handle_event_locked(project, d, ev, add_line, allow, run=None, spawn=None):
    """handle_event for events a project's controls forward: under the ops state lock (the one consume holds), so
    /pause and /resume reach paused_by_ops. Not configured: no state, as before."""
    if not configured():
        return handle_event(project, d, ev, add_line, allow, run=run, spawn=spawn)
    with _state(True) as st:
        return handle_event(project, d, ev, add_line, allow, run=run, spawn=spawn, st=st)


def consume(add_line, run, now, on_merge=None, lead_run=None, spawn=None):
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
                dlg = discord_dialogs.consume_event(d, ev, allow, run, now, add_line=add_line)
                if dlg:
                    discord_feed.audit_append(d, user, *dlg)
                elif kind == "np_result":   # the ops bridge's own answer to a create_channel / channel_overwrite op: no user
                    discord_feed.audit_append(d, "", "np_result", f"{str(ev.get('name') or '')[:60]}:{ev.get('action')}", newproject.on_result(d, ev))
                elif kind == "click":
                    cid = str(ev.get("custom_id") or "")
                    result = _click(d, user, cid, st, add_line, now, on_merge) if user in allow else "rejected"
                    discord_feed.audit_append(d, user, "click", cid, result)
                else:
                    handle_event(None, d, ev, add_line, allow, run=lead_run or run, spawn=spawn, st=st)
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
