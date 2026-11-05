#!/usr/bin/env python3
"""planview: the active plan's tasks with their owners' pane state, for board consumers (`view()`).

view(session, root, home, state_dir, tmux) -> {"name", "active", "tasks": [{"id","subject","status","owner","state","tier","blockedBy"}]}
`home` is the Claude config dir (~/.claude): it holds sessions/ and tasks/.
Reads the lead's live task list (<home>/tasks/session-<id8>/, else its team's <home>/tasks/<team>/), falls back to the plan's .md.tasks.json.
Never raises: missing files, bad JSON and a failing tmux give an empty or partial view.
"""
import argparse
import json
import re
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
    return lead_entry(session, home, tmux)[0]


def lead_entry(session, home, tmux):
    """(sessionId, pid, startedAt ms) of that sessions entry; ("", 0, 0) when there is none."""
    try:
        pane = tmux("display", "-p", "-t", f"={session}:claude", "#{window_id}.#{pane_id}").strip()
    except ERRORS:
        return "", 0, 0
    if not pane:
        return "", 0, 0
    best = (-1, "", 0, 0)
    for f in sorted((Path(home) / "sessions").glob("*.json")):
        try:
            e = json.loads(f.read_text())
            if str(e.get("tmux", "")).endswith(pane) and e.get("sessionId"):
                upd = e.get("updatedAt") or 0
                if upd > best[0]:
                    best = (upd, str(e["sessionId"]), e.get("pid") if isinstance(e.get("pid"), int) else 0,
                            e.get("startedAt") if isinstance(e.get("startedAt"), (int, float)) else 0)
        except (ERRORS + (AttributeError, TypeError)):
            continue
    return best[1], best[2], best[3]


_FENCE = re.compile(r"```json:metadata\s*\n(.*?)\n```", re.S)


def _tier(t):
    """modelTier from the task's metadata dict, else from its description's json:metadata fence, else ''."""
    meta = t.get("metadata")
    if isinstance(meta, dict) and isinstance(meta.get("modelTier"), str):
        return meta["modelTier"]
    m = _FENCE.search(str(t.get("description") or ""))
    if not m:
        return ""
    try:
        v = json.loads(m.group(1))
    except ValueError:
        return ""
    return v.get("modelTier", "") if isinstance(v, dict) and isinstance(v.get("modelTier", ""), str) else ""


def _norm(t):
    return {"id": str(t.get("id", "")), "subject": str(t.get("subject", "")), "status": str(t.get("status", "pending")),
            "owner": str(t.get("owner") or ""), "blockedBy": [str(b) for b in (t.get("blockedBy") or [])],
            "tier": _tier(t)}


def _finish(tasks):
    tasks = sorted(tasks, key=lambda t: _id_key(t["id"]))
    done = {t["id"] for t in tasks if t["status"] == "completed"}
    out = []
    for t in tasks:
        st = t["status"] if t["status"] in STATUSES else "pending"
        if st == "pending" and any(b not in done for b in t["blockedBy"]):
            st = "blocked"
        out.append({"id": t["id"], "subject": t["subject"], "status": st, "owner": t["owner"], "state": "",
                    "tier": t["tier"], "blockedBy": t["blockedBy"]})
    return out


PID_SLACK_MS = 60_000


def team_name(home, sid, pid, started=0):
    """Name of the agent team this lead leads. A teams/*/config.json whose leadSessionId is `sid` wins. Else the
    team whose leadProcess.pid is `pid` (the team keeps the session id it was created under, the pid survives a
    new session), guarded against pid reuse: its claimedAt must be no earlier than the session's startedAt minus
    a minute; of several, the newest claim wins."""
    best = (-1, "")
    for f in sorted((Path(home) / "teams").glob("*/config.json")):
        try:
            c = json.loads(f.read_text())
            name = str(c.get("name") or f.parent.name)
            if sid and c.get("leadSessionId") == sid:
                return name
            lp = c.get("leadProcess")
            if pid and isinstance(lp, dict) and lp.get("pid") == pid:
                claimed = lp.get("claimedAt")
                if isinstance(claimed, (int, float)) and claimed >= started - PID_SLACK_MS and claimed > best[0]:
                    best = (claimed, name)
        except (ERRORS + (AttributeError, TypeError)):
            continue
    return best[1]


def live_tasks(home, sid, pid=0, started=0):
    """The lead's own tasks/session-<id8>/ list; when that is empty and the lead leads a team, tasks/<team>/."""
    if not sid:
        return []
    tasks = _read_dir(Path(home) / "tasks" / f"session-{sid[:8]}")
    if not tasks:
        team = team_name(home, sid, pid, started)
        if team:
            tasks = _read_dir(Path(home) / "tasks" / team)
    return _finish(tasks)


def _read_dir(d):
    tasks = []
    for f in d.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            if isinstance(d, dict):
                tasks.append(_norm(d))
        except (ERRORS + (AttributeError, TypeError)):
            continue
    return tasks


def plan_entry(state_dir, project, sid):
    """Path of the newest `kind == "plan"` manifest line of this session, or None. A line with a blank session_id
    (`tmux-ctl artifact` of a worktree copy) counts when it names a file this session registered itself. Blank ids
    come from lines written before manual registrations recorded $CLAUDE_CODE_SESSION_ID, and from `tmux-ctl
    artifact` run in a plain shell; a non-blank id is matched only by that id."""
    try:
        lines = (Path(state_dir) / f"artifacts-{project}.jsonl").read_text().splitlines()
    except ERRORS:
        return None
    plans = []
    for l in lines:
        try:
            m = json.loads(l)
            if m.get("kind") == "plan" and m.get("path"):
                plans.append((m.get("ts") or 0, m.get("session_id") or "", str(m["path"])))
        except (ERRORS + (AttributeError, TypeError)):
            continue
    if not sid:
        return None
    mine = {Path(p).name for _, s, p in plans if s == sid}
    best = None
    for ts, s, p in plans:
        if (s == sid or (not s and Path(p).name in mine)) and (best is None or ts >= best[0]):
            best = (ts, p)
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
    sid, pid, started = lead_entry(session, home, tmux)
    plan = plan_entry(state_dir, project_of(session, tmux), sid)
    tasks = live_tasks(home, sid, pid, started)
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
