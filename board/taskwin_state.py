#!/usr/bin/env python3
"""taskwin_state: per-session timing and celebration state for the tasks window (board/taskwin.py).

State (JSON at path_for(state_dir, session)):
  {"lead": <lead session id>, "tasks": {id: {"status", "since", "started", "done"}},
   "events": [{"kind": "done", "id", "at"} | {"kind": "plan_done", "at"}], "all_done": bool | None}
update() mutates and returns the state; events live EVENT_TTL seconds. Never raises on I/O.
"""
import json
import os
import re
from pathlib import Path

EVENT_TTL = 10.0


def path_for(state_dir, session):
    return Path(state_dir) / "taskwin" / f"{re.sub(r'[^A-Za-z0-9._-]', '_', session) or '_'}.json"


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


def update(st, lead, tasks, now):
    if st.get("lead") != lead or not isinstance(st.get("tasks"), dict):
        st.clear()
        st.update({"lead": lead, "tasks": {}, "events": [], "all_done": None})
    known = st["tasks"]
    events = [e for e in st.get("events") or [] if isinstance(e, dict) and now - e.get("at", 0) < EVENT_TTL]
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
    all_done = bool(tasks) and all(t["status"] == "completed" for t in tasks)
    if all_done and st.get("all_done") is False:
        events.append({"kind": "plan_done", "at": now})
    st["all_done"], st["events"] = all_done, events
    return st
