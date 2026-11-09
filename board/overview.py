#!/usr/bin/env python3
"""overview: one digest record per project, from state the board already has. No LLM.

build(sessions, live, now, *, home, state_dir, tmux, th, spend, activity) -> {"generated", "projects": [record]}
Every input is a parameter: `sessions` is server.build_state()["sessions"], `live` the usage indexer snapshot,
`spend(repo) -> USD or None` today's spend, `activity` {session: {window: epoch}} from `list-windows -a`.
Record fields are fixed (the notifier and the page read them): see RECORD_KEYS. Never raises per project: a failing
piece leaves its field empty (plan with total 0, last_run None, lead missing).

CLI: overview.py [--project NAME] [--json]  prints the live board's /api/overview (token from
${TMUX_DASH_STATE:-~/.local/state/tmux-dash}/token, port TMUX_DASH_PORT); without a board, a local build without
usage data ("source": "local"). `tmux-ctl overview` calls this.
"""
import argparse
import json
import os
import re
import shlex
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import activity as activity_mod  # noqa: E402
import artifacts, planview, usage  # noqa: E402

RECORD_KEYS = ("project", "path", "attached", "plan", "needs_you", "last_run", "lead", "artifacts", "epoch", "alerts", "spend_today", "agents")
ERRORS = (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError)


def plan_digest(view):
    tasks = view.get("tasks") or []
    done = sum(1 for t in tasks if t.get("status") == "completed")
    return {"name": view.get("name") or "", "active": bool(view.get("active")), "done": done, "total": len(tasks),
            "in_progress": [{"id": t["id"], "subject": t["subject"], "owner": t.get("owner") or "", "state": t.get("state") or ""}
                            for t in tasks if t.get("status") == "in_progress"]}


def _secs(now, t):
    return int(max(0, now - t)) if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def agents(s, mods, now):
    """One entry per claude pane in window order; state_s / turn_s / tool come from the pane's fresh agent-status record, else None."""
    out = []
    for w in s.get("windows") or []:
        for p in w.get("panes") or []:
            if p.get("kind") != "claude":
                continue
            rec = (mods or {}).get(p["id"])
            t = (rec or {}).get("tool")
            tool = (f"{t['name']}: {t['arg']}" if t.get("arg") else t.get("name")) if isinstance(t, dict) and t.get("name") else None
            out.append({"window": w["name"], "pane": p["id"], "state": p.get("status"),
                        "state_s": _secs(now, rec.get("since")) if rec else None,
                        "turn_s": _secs(now, rec.get("turnStartedAt")) if rec else None, "tool": tool})
    return out


def _reason(rec):
    w = (rec or {}).get("waiting")
    if isinstance(w, dict) and w.get("kind") in ("question", "permission") and w.get("detail"):
        return f"{w['kind']}: {w['detail']}"
    return None


def needs_you(s, mods=None):
    return [{"window": w["name"], "pane": p["id"], "kind": p["kind"], "reason": _reason((mods or {}).get(p["id"]))}
            for w in s.get("windows") or [] for p in w.get("panes") or [] if p.get("status") == "waiting"]


def lead_state(s, win_activity, now, mods=None):
    """status working|waiting|ready from the claude window's first pane, missing without one; last_active from tmux.
    A lead at its prompt counts as working while any other claude pane of the project is working (teammates running)."""
    w = next((w for w in s.get("windows") or [] if w.get("name") == "claude" and w.get("panes")), None)
    if w is None:
        return {"status": "missing", "last_active": None, "idle_s": None}
    p = w["panes"][0]
    status = p.get("status") if p.get("kind") == "claude" else "missing"
    if status == "ready" and any(q.get("kind") == "claude" and q.get("status") == "working"
                                 for x in s.get("windows") or [] for q in x.get("panes") or [] if q is not p):
        status = "working"
    last = (win_activity or {}).get("claude")
    idle = int(max(0, now - last)) if last else None
    rec = (mods or {}).get(p["id"])
    if rec and rec.get("state") == "ready" and _secs(now, rec.get("since")) is not None:   # the mod's own clock beats window activity
        idle = _secs(now, rec["since"])
    return {"status": status or "missing", "last_active": last, "idle_s": idle}


def run_label(cmd):
    """A short name for a run's command, never a path: the first script's basename without its extension,
    else the module after -m, else the first word. Leading `cd ...` and VAR=value words are skipped."""
    for seg in re.split(r"&&|\|\||;|\|", cmd or ""):
        try:
            toks = shlex.split(seg, comments=False)
        except ValueError:
            toks = seg.split()
        words, skip = [], False
        for t in toks:   # drop redirects and their target word (`> file`, `2>&1`), and VAR=value words
            if skip:
                skip = False
            elif re.fullmatch(r"\d*(>>?|<)", t):
                skip = True
            elif not re.match(r"^\d*[<>]", t) and not re.match(r"^[A-Za-z_]\w*=", t):
                words.append(t)
        toks = words
        if toks and toks[0].rsplit("/", 1)[-1] == "env":
            toks = toks[1:]
        if not toks or toks[0] == "cd":
            continue
        for i, t in enumerate(toks):
            if t == "-m" and i + 1 < len(toks):
                return toks[i + 1]
            if "/" in t and not t.startswith("-"):
                name = t.rstrip("/").rsplit("/", 1)[-1]
                return name.rsplit(".", 1)[0] if "." in name.lstrip(".") else name
        return toks[0].rsplit("/", 1)[-1]
    return ""


def last_run(project, now):
    try:
        rs = activity_mod.runs(project, limit=1)
    except ERRORS:
        return None
    if not rs:
        return None
    r = rs[0]
    return {"id": r.get("id"), "cmd": r.get("cmd") or "", "exit": r.get("exit"), "ts": r.get("ts"),
            "age_s": int(now - (r.get("ts") or now)), "summary": r.get("summary") or "",
            "label": run_label(r.get("cmd") or "")}


def recent_artifacts(project, n=3):
    try:
        items = artifacts.summary(project)
    except ERRORS:
        return [], 0
    out = [{"path": i["path"] or i["url"], "kind": i["kind"], "title": i.get("title") or "", "ts": i["latest"].get("ts"),
            "agent": i["latest"].get("agent") or ""} for i in items["items"] if not i.get("dismissed")][:n]
    return out, items["epoch"]


def project_alerts(s, live, spend, th):
    repo = s.get("path") or ""
    mine = [e for e in live if repo and usage.in_project(e.get("cwd"), repo)]
    who = lambda e: "lead" if e.get("role") == "lead" and e["name"] == (e.get("session_id") or "")[:8] else e["name"]   # an unnamed lead is "lead", not its id prefix
    out = [dict(a, session=who(e), context_pct=e.get("context_pct")) for e in mine for a in e.get("alerts") or []]
    day = usage.day_alert(spend, th)
    if day:
        out.append(dict(day, session=None, context_pct=None))
    return out


def agent_alerts(s, mods, now, th):
    """failing (a streak of failed tool calls) and stuck (a long turn with no tool call for a while) per agent with a fresh file."""
    out = []
    for w in s.get("windows") or []:
        for p in w.get("panes") or []:
            rec = (mods or {}).get(p["id"]) if p.get("kind") == "claude" else None
            if not rec:
                continue
            fs = rec.get("failStreak")
            if isinstance(fs, int) and not isinstance(fs, bool) and fs >= th["failing_streak"]:
                out.append({"kind": "failing", "label": f"failing ×{fs}", "session": w["name"], "fail_streak": fs, "context_pct": None,
                            "detail": f"{w['name']} has had {fs} tool calls fail in a row (alert at {th['failing_streak']})."})
            turn = _secs(now, rec.get("turnStartedAt"))
            if rec.get("state") != "busy" or turn is None or turn < th["stuck_turn_s"]:
                continue
            last, began = rec.get("lastToolAt"), rec["turnStartedAt"]
            since = last if isinstance(last, (int, float)) and last >= began else began
            if now - since >= th["stuck_quiet_s"]:
                out.append({"kind": "stuck", "label": f"stuck {turn // 60}m", "session": w["name"], "turn_s": turn, "context_pct": None,
                            "detail": f"{w['name']} has been on one turn for {turn // 60} min and made no tool call for {int(now - since) // 60} min."})
    return out


def record(s, live, now, *, home, state_dir, tmux, th, spend, activity, mods=None):
    name = s["name"]
    root = s.get("path")
    try:
        view = planview.view(name, root or ".", home, state_dir, tmux)
    except Exception:   # noqa: BLE001 - a failing plan view leaves the plan empty
        view = dict(planview.EMPTY)
    try:
        spent = spend(root) if (spend and root) else None
    except Exception:   # noqa: BLE001
        spent = None
    arts, epoch = recent_artifacts(name)
    return {"project": name, "path": s.get("path"), "attached": bool(s.get("attached")),
            "plan": plan_digest(view), "needs_you": needs_you(s, mods), "last_run": last_run(name, now),
            "lead": lead_state(s, (activity or {}).get(name), now, mods), "artifacts": arts, "epoch": epoch,
            "alerts": project_alerts(s, live, spent, th) + agent_alerts(s, mods, now, th), "spend_today": spent,
            "agents": agents(s, mods, now)}


def build(sessions, live, now, *, home, state_dir, tmux, th=None, spend=None, activity=None, mods=None):
    th = th if th is not None else usage.DEFAULT_ALERTS
    projects = [record(s, live or [], now, home=home, state_dir=state_dir, tmux=tmux, th=th, spend=spend, activity=activity, mods=mods)
                for s in sessions if not s["name"].startswith("_web-") and s["name"] != "overseer"]
    return {"generated": now, "projects": projects}


# ---------------------------------------------------------------- CLI

def line(r):
    """One compact line per project for `tmux-ctl overview`."""
    plan = r["plan"]
    parts = [r["project"].ljust(18)]
    parts.append(f"plan {plan['name'] or '-'} {plan['done']}/{plan['total']}" + ("" if plan["active"] else " (idle)"))
    if plan["in_progress"]:
        parts.append("▶ " + ", ".join(f"{t['subject'][:30]}→{t['owner'] or '?'}" for t in plan["in_progress"]))
    if r["needs_you"]:
        parts.append("NEEDS YOU: " + ", ".join(n["window"] for n in r["needs_you"]))
    lead = r["lead"]
    idle = f" {lead['idle_s'] // 60}m" if lead.get("idle_s") is not None and lead["status"] == "ready" else ""
    parts.append(f"lead {lead['status']}{idle}")
    run = r["last_run"]
    if run:
        ex = "running" if run["exit"] is None else f"exit {run['exit']}"
        parts.append(f"run {ex} {run['age_s'] // 60}m ago")
    if r["spend_today"] is not None:
        parts.append(f"${r['spend_today']:.2f} today")
    if r["alerts"]:
        parts.append("alerts " + ", ".join(a["label"] for a in r["alerts"]))
    return " · ".join(parts)


def board_overview(timeout=5):
    """The running board's /api/overview, or None when there is no board (no token file, connection refused)."""
    state = Path(os.environ.get("TMUX_DASH_STATE") or Path.home() / ".local" / "state" / "tmux-dash")
    try:
        tok = (state / "token").read_text().strip()
    except OSError:
        return None
    port = os.environ.get("TMUX_DASH_PORT", "7700")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/{tok}/api/overview", timeout=timeout) as r:
            d = json.load(r)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and "projects" in d else None


def local_overview():
    """A build from this process (no board): pane state from server.py's build, no usage data."""
    os.environ.setdefault("TMUX_DASH_TOKEN", "local")
    import server  # noqa: PLC0415 - heavy; only without a board
    now = time.time()
    st = server.build_state()
    ov = build(st["sessions"], [], now, home=Path.home() / ".claude", state_dir=artifacts.state_dir(), tmux=server.tmux,
               th=usage.thresholds()[0], spend=None, activity=server.window_activity())
    return {**ov, "events": [], "source": "local"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="overview")
    ap.add_argument("--project")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ov = board_overview() or local_overview()
    if a.project:
        ov = {**ov, "projects": [p for p in ov["projects"] if p["project"] == a.project]}
        if not ov["projects"]:
            print(f"overview: no open project named {a.project}", file=sys.stderr)
            return 1
    if a.json:
        print(json.dumps(ov, ensure_ascii=False))
    elif not ov["projects"]:
        print(f"overview: {ov['error']}" if ov.get("error") else "no open projects")
    else:
        for p in ov["projects"]:
            print(line(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
