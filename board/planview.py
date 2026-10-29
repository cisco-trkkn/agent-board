#!/usr/bin/env python3
"""planview: the active plan's tasks with their owners' pane state, for board consumers (`view()`).

view(session, root, home, state_dir, tmux) -> {"name", "active", "tasks": [{"id","subject","status","owner","state"}]}
`home` is the Claude config dir (~/.claude): it holds sessions/ and tasks/.
Reads the lead's live task list (<home>/tasks/session-<id8>/), falls back to the plan's .md.tasks.json.
Never raises: missing files, bad JSON and a failing tmux give an empty or partial view.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import paneclass, tc_env  # noqa: E402,F401

ERRORS = (OSError, ValueError, RuntimeError, subprocess.SubprocessError)
STATUSES = ("completed", "in_progress", "pending")
EMPTY = {"name": "", "active": False, "tasks": []}


def _id_key(i):
    s = str(i)
    return (0, int(s), s) if s.isdigit() else (1, 0, s)


def lead_session(session, home, tmux):
    """sessionId of the claude in `=<session>:claude`: the sessions entry whose tmux ends with <window_id>.<pane_id>."""
    try:
        pane = tmux("display", "-p", "-t", f"={session}:claude", "#{window_id}.#{pane_id}").strip()
    except ERRORS:
        return ""
    if not pane:
        return ""
    best = (-1, "")
    for f in sorted((Path(home) / "sessions").glob("*.json")):
        try:
            e = json.loads(f.read_text())
            if str(e.get("tmux", "")).endswith(pane) and e.get("sessionId"):
                upd = e.get("updatedAt") or 0
                if upd > best[0]:
                    best = (upd, str(e["sessionId"]))
        except (ERRORS + (AttributeError, TypeError)):
            continue
    return best[1]


def _norm(t):
    return {"id": str(t.get("id", "")), "subject": str(t.get("subject", "")), "status": str(t.get("status", "pending")),
            "owner": str(t.get("owner") or ""), "blockedBy": [str(b) for b in (t.get("blockedBy") or [])]}


def _finish(tasks):
    tasks = sorted(tasks, key=lambda t: _id_key(t["id"]))
    done = {t["id"] for t in tasks if t["status"] == "completed"}
    out = []
    for t in tasks:
        st = t["status"] if t["status"] in STATUSES else "pending"
        if st == "pending" and any(b not in done for b in t["blockedBy"]):
            st = "blocked"
        out.append({"id": t["id"], "subject": t["subject"], "status": st, "owner": t["owner"], "state": ""})
    return out


def live_tasks(home, sid):
    if not sid:
        return []
    tasks = []
    for f in (Path(home) / "tasks" / f"session-{sid[:8]}").glob("*.json"):
        try:
            d = json.loads(f.read_text())
            if isinstance(d, dict):
                tasks.append(_norm(d))
        except (ERRORS + (AttributeError, TypeError)):
            continue
    return _finish(tasks)


def plan_entry(state_dir, project, sid):
    """Path of the newest `kind == "plan"` manifest line of this session, or None."""
    best = None
    try:
        lines = (Path(state_dir) / f"artifacts-{project}.jsonl").read_text().splitlines()
    except ERRORS:
        return None
    for l in lines:
        try:
            m = json.loads(l)
            if m.get("kind") == "plan" and sid and m.get("session_id") == sid and m.get("path"):
                if best is None or (m.get("ts") or 0) >= best[0]:
                    best = (m.get("ts") or 0, m["path"])
        except (ERRORS + (AttributeError, TypeError)):
            continue
    return Path(best[1]) if best else None


def file_tasks(path):
    try:
        d = json.loads(Path(path).read_text())
        tasks = []
        for t in d["tasks"]:
            try:
                tasks.append(_norm(t))
            except (AttributeError, TypeError, ValueError):
                continue
        return _finish(tasks)
    except (ERRORS + (KeyError, TypeError)):
        return []


def pane_state(tmux, pane):
    try:
        kind, status = paneclass.pane_status(tmux, pane)
    except ERRORS:
        return "ready"
    if kind == "claude" and status in ("working", "waiting"):
        return status
    return "ready"


def owner_states(session, tasks, tmux):
    try:
        wins = {}
        for line in tmux("list-windows", "-t", f"={session}", "-F", "#{window_name}\t#{pane_id}").splitlines():
            name, _, pane = line.partition("\t")
            wins[name] = pane
    except ERRORS:
        wins = {}
    cache = {}
    for t in tasks:
        if not t["owner"]:
            continue
        pane = wins.get(f"✦ {t['owner']}")
        if not pane:
            t["state"] = "gone"
        else:
            if pane not in cache:
                cache[pane] = pane_state(tmux, pane)
            t["state"] = cache[pane]
    return tasks


def _newest_repo_tasks_json(root):
    try:
        files = list((Path(root) / "docs" / "superpowers" / "plans").glob("*.md.tasks.json"))
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    except ERRORS:
        return None


def project_of(session, tmux):
    """Manifest key: the session group (else the session name) with a trailing -bg dropped; `session` if tmux fails."""
    try:
        p = tmux("display", "-p", "-t", f"={session}:", "#{?session_group,#{session_group},#{session_name}}").strip()
    except ERRORS:
        p = ""
    if p.endswith("-bg"):
        p = p[:-3]
    return p or session


def _idle_view(root, plan, tmux, session):
    """No live list: the plan's own .md.tasks.json (next to its manifest path, else under root), else the newest in
    the repo; active is False and the name is that of the file shown."""
    tj = None
    if plan:
        own = Path(str(plan) + ".tasks.json")
        under_root = Path(root) / "docs" / "superpowers" / "plans" / f"{plan.name}.tasks.json"
        tj = next((c for c in (own, under_root) if c.is_file()), None)
    tj = tj or _newest_repo_tasks_json(root)
    if tj is None:
        return {"name": _plan_name(plan), "active": False, "tasks": []}
    name = tj.name[:-len(".md.tasks.json")] if tj.name.endswith(".md.tasks.json") else tj.name
    return {"name": name, "active": False, "tasks": owner_states(session, file_tasks(tj), tmux)}


def _plan_name(plan):
    return plan.name[:-3] if plan and plan.name.endswith(".md") else (plan.name if plan else "")


def view(session, root, home, state_dir, tmux):
    sid = lead_session(session, home, tmux)
    plan = plan_entry(state_dir, project_of(session, tmux), sid)
    tasks = live_tasks(home, sid)
    if tasks:
        return {"name": _plan_name(plan), "active": True, "tasks": owner_states(session, tasks, tmux)}
    return _idle_view(root, plan, tmux, session)


NO_PLANS = "no plans yet \u00b7 prefix S for a shell"


def _snapshot(session, root, tmux=None):
    return view(session, root, Path.home() / ".claude", tc_env.state_dir(), tmux or paneclass.tmux_runner())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="planview")
    ap.add_argument("cmd", choices=("view",))
    ap.add_argument("session")
    ap.add_argument("--root")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root or ".")
    try:
        v = _snapshot(a.session, root)
        if a.json or v.get("name") or v.get("tasks"):
            print(json.dumps(v, ensure_ascii=False))
        else:
            print(NO_PLANS)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
