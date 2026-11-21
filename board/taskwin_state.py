#!/usr/bin/env python3
"""taskwin_state: per-session timing and celebration state for the tasks window (board/taskwin.py).

State (JSON at path_for(state_dir, session)):
  {"lead": <lead session id>, "tasks": {id: {"status", "since", "started", "done"}},
   "events": [{"kind": "done", "id", "at"} | {"kind": "plan_done", "at"}], "all_done": bool | None}
   "ui": {...} (taskwin_ui; kept across a lead change)
update() mutates and returns the state; events live EVENT_TTL seconds. With `journal` (journal_path) it also appends
one history line per task that turns completed while watched: task_done for plan tasks, queue_outcome for
`Plan & run:` items. Never raises on I/O.
"""
import json
import os
import re
from pathlib import Path

EVENT_TTL = 10.0
QUEUE_PREFIX = "Plan & run: "
JOURNAL_CAP, DEDUPE_WINDOW = 5000, 500


def _safe(name):
    return re.sub(r'[^A-Za-z0-9._-]', '_', name) or '_'


def path_for(state_dir, session):
    return Path(state_dir) / "taskwin" / f"{_safe(session)}.json"


def journal_path(state_dir, project):
    """History journal of a project (the session group, else the session name: planview.project_of)."""
    return Path(state_dir) / "taskwin" / f"{_safe(project)}.history.jsonl"


def spec_of(subject):
    """`Plan & run: <spec> [note]` -> <spec> (first word, `#part` kept); '' for any other subject."""
    if not str(subject).startswith(QUEUE_PREFIX):
        return ""
    rest = str(subject)[len(QUEUE_PREFIX):].split()
    return rest[0] if rest else ""


def _plan_stem(path):
    name = Path(path).name if path else ""
    return name[:-3] if name.endswith(".md") else name


def journal_entry(t, now, plan):
    """The history line for task `t` turning completed at `now`."""
    if str(t.get("subject", "")).startswith(QUEUE_PREFIX):
        e = {"kind": "queue_outcome", "at": now, "spec": spec_of(t["subject"]), "outcome": t.get("outcome") or ""}
        if t.get("planPath"):
            e["plan"] = _plan_stem(t["planPath"])
        return e
    return {"kind": "task_done", "at": now, "plan": plan or "", "id": str(t.get("id", "")),
            "subject": str(t.get("subject", "")), "owner": t.get("owner") or "", "tier": t.get("tier") or ""}


def _dedupe_key(e):
    return (e.get("kind"), e.get("plan") if e.get("kind") == "task_done" else e.get("spec"), e.get("id"), e.get("subject"))


def append_journal(path, entries):
    """Append `entries` not already among the last DEDUPE_WINDOW lines; keep the newest JOURNAL_CAP lines."""
    if not entries:
        return
    try:
        p = Path(path)
        try:
            lines = p.read_text().splitlines()
        except FileNotFoundError:
            lines = []
        seen = set()
        for l in lines[-DEDUPE_WINDOW:]:
            try:
                seen.add(_dedupe_key(json.loads(l)))
            except (ValueError, AttributeError, TypeError):
                continue
        new = []
        for e in entries:
            k = _dedupe_key(e)
            if k not in seen:
                seen.add(k)
                new.append(json.dumps(e))
        if not new:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        if len(lines) + len(new) > JOURNAL_CAP:
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text("\n".join((lines + new)[-JOURNAL_CAP:]) + "\n")
            os.replace(tmp, p)
        else:
            with open(p, "a") as f:
                f.write("".join(l + "\n" for l in new))
    except OSError:
        pass


def load(path):
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def save(path, st):
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(st))
        os.replace(tmp, p)
    except OSError:
        pass


def update(st, lead, tasks, now, journal=None, plan=""):
    old = st.get("lead")
    if not isinstance(st.get("tasks"), dict) or (old and lead and old != lead):
        ui = st.get("ui")
        st.clear()
        st.update({"lead": lead, "tasks": {}, "events": [], "all_done": None})
        if isinstance(ui, dict):
            st["ui"] = ui
    elif lead:  # a blank lead (tmux or sessions json unreadable for a tick) keeps the state and the stored id
        st["lead"] = lead
    known = st["tasks"]
    events = [e for e in st.get("events") or [] if isinstance(e, dict) and now - e.get("at", 0) < EVENT_TTL]
    done_now = []
    for t in tasks:
        s, k = t["status"], known.get(t["id"])
        if k is None:
            known[t["id"]] = {"status": s, "since": now, "started": now if s == "in_progress" else None,
                              "done": now if s == "completed" else None}
            continue
        if k.get("status") != s:
            k["status"], k["since"] = s, now
            if s == "in_progress" and not k.get("started"):
                k["started"] = now
            if s == "completed":
                k["done"] = now
                events.append({"kind": "done", "id": t["id"], "at": now})
                done_now.append(journal_entry(t, now, plan))
    all_done = bool(tasks) and all(t["status"] == "completed" for t in tasks)
    if all_done and st.get("all_done") is False:
        events.append({"kind": "plan_done", "at": now})
    st["all_done"], st["events"] = all_done, events
    if journal is not None:
        append_journal(journal, done_now)
    return st
