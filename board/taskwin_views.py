#!/usr/bin/env python3
"""taskwin_views: the rows of each tasks-window view, shared by the renderer (board/taskwin.py) and the key handler
(board/taskwin_ui.py) so a cursor index means the same row in both. Pure: no I/O.

Row keys: queue `q:<id>`; plan `p:done` (the collapsed done line) and `p:<id>`; history `h:<entry key>`.
"""
import taskwin_ui as ui_mod

QUEUE_PREFIX = ui_mod.QUEUE_PREFIX
DONE_KEY = "p:done"


def is_queue(t):
    return str(t.get("subject", "")).startswith(QUEUE_PREFIX)


def split(tasks):
    """(queue items, plan tasks): `Plan & run:` subjects and the rest, order kept."""
    tasks = list(tasks or [])
    return [t for t in tasks if is_queue(t)], [t for t in tasks if not is_queue(t)]


def filter_tasks(tasks, f):
    if f == "hide_done":
        return [t for t in tasks if t["status"] != "completed"]
    if f == "active":
        return [t for t in tasks if t["status"] in ("in_progress", "blocked")]
    return list(tasks)


def plan_tasks(tasks, ui):
    """(done line shown?, tasks drawn): the plan view after the filter and the done collapse."""
    shown = filter_tasks(split(tasks)[1], ui["filter"])
    done = [t for t in shown if t["status"] == "completed"]
    if done and ui_mod.is_collapsed(ui, DONE_KEY):
        return len(done), [t for t in shown if t["status"] != "completed"]
    return 0, shown


def model(tasks, ui, history=()):
    queue, _ = split(tasks)
    ndone, shown = plan_tasks(tasks, ui)
    q_rows = ["q:" + t["id"] for t in queue]
    q_toggle = {"q:" + t["id"]: ui_mod.OPEN_PLAN for t in queue if t["status"] == "in_progress"}
    p_rows = ([DONE_KEY] if ndone else []) + ["p:" + t["id"] for t in shown]
    p_toggle = {DONE_KEY: DONE_KEY} if ndone else {}
    p_toggle.update({"p:" + t["id"]: DONE_KEY for t in shown if t["status"] == "completed"})
    any_done = bool(ndone) or any(t["status"] == "completed" for t in shown)
    h_rows = ["h:" + e["key"] for e in history]
    return {"rows": {"queue": q_rows, "plan": p_rows, "history": h_rows},
            "toggle": {"queue": q_toggle, "plan": p_toggle, "history": {k: k for k in h_rows}},
            "finished": {"queue": [], "plan": [DONE_KEY] if any_done else [], "history": list(h_rows)}}


def queue_label(subject, titles):
    """Queue row text: the spec's title (`#part` appended) or its path, then any note after the spec word."""
    rest = str(subject)[len(QUEUE_PREFIX):].strip() if is_queue({"subject": subject}) else str(subject)
    spec, _, note = rest.partition(" ")
    title = (titles or {}).get(spec)
    frag = spec.partition("#")[2]
    label = (title + (f" #{frag}" if frag else "")) if title else spec
    return label + (f" {note.strip()}" if note.strip() else "")
