"""notify: code-driven events from successive overviews (board/overview.py records), delivered as macOS banners.

Rules (spec 2026-10-28-overseer-design.md): an event fires once when its condition first appears, not again while it
holds, again after it clears and comes back; at most one event of a kind per project every RATE_S seconds; the first
overview, and a project's first appearance, only seed the latch (nothing "appears" at startup). TC_NOTIFY=0 turns
banners off only; the events list and the sinks (the discord feed, TC_DISCORD_ALERTS=0 turns it off) still run. The osascript call goes through an injected runner. Pure except for the runner and the clock.
"""
import os
import subprocess
import sys
import time
from collections import deque

KINDS = ("needs_you", "plan_done", "test_failed", "lead_idle", "context", "usage", "failing", "stuck",
         "teammate_gone", "teammate_silent", "awake_dropped", "weekly_pace", "run_overdue")
RATE_S = 300      # at most one event of a kind per project in this window
IDLE_S = 900      # a lead idle this long with open tasks is event 4
USAGE_KINDS = ("burn", "total", "day_total")
SILENT_S = 1800   # a teammate at its prompt this long with its task in progress (night watch, queue mode only)
PACE_MARGIN = 15  # weekly usage this many points above the elapsed share of the week (night watch, queue mode only)


def conditions(ov, queue_before=frozenset()):
    """Every condition true in one overview: [{project, kind, key, title, text}]. Deterministic order.
    queue_before: the project names in queue mode in the previous overview (awake_dropped needs it: one-overview grace)."""
    out = []

    def add(project, kind, key, title, text):
        out.append({"project": project, "kind": kind, "key": str(key), "title": title, "text": text})

    for p in ov.get("projects") or []:
        name = p["project"]
        for n in p.get("needs_you") or []:
            add(name, "needs_you", n["pane"], f"{name}: needs you", f"{n['window']} is waiting for you")
        plan = p.get("plan") or {}
        total, done = plan.get("total") or 0, plan.get("done") or 0
        if total and done == total:
            add(name, "plan_done", plan.get("name") or "", f"{name}: plan finished", f"{plan.get('name') or 'plan'} · {done}/{total} done")
        r = p.get("last_run")
        if r and r.get("exit") not in (None, 0):
            add(name, "test_failed", r["id"], f"{name}: test run failed", f"exit {r['exit']} · {(r.get('cmd') or '')[:80]}")
        lead = p.get("lead") or {}
        idle = lead.get("idle_s")
        if lead.get("status") == "ready" and idle is not None and idle >= IDLE_S and total and done < total:
            add(name, "lead_idle", "lead", f"{name}: lead idle", f"idle {idle // 60} min with {total - done} open task{'s' if total - done != 1 else ''}")
        if p.get("queue"):
            _watch_conditions(p, add, name in queue_before)
        for a in p.get("alerts") or []:
            who = a.get("session") or name
            if a.get("kind") == "context":
                add(name, "context", who, f"{name}: high context", f"{who} context at {a.get('context_pct')}%")
            elif a.get("kind") == "failing":
                add(name, "failing", who, f"{name}: agent failing", f"{who} failed {a.get('fail_streak')} tool calls in a row")
            elif a.get("kind") == "stuck":
                run = f" (running {a['tool']})" if a.get("tool") else ""
                add(name, "stuck", who, f"{name}: agent stuck",
                    f"{who} has been on one turn for {(a.get('turn_s') or 0) // 60} min and no tool call has finished for {(a.get('quiet_s') or 0) // 60} min{run}")
            elif a.get("kind") in USAGE_KINDS:
                add(name, "usage", f"{a['kind']}:{who}", f"{name}: high usage", f"{who} {a.get('label', '')}".strip())
    return out


def _watch_conditions(p, add, queue_before):
    """The night watch kinds for a project in queue mode (spec 2026-11-23-night-watch-design.md §2)."""
    name = p["project"]
    for o in p.get("owned") or []:
        owner, tid = o["owner"], o["task"]
        if not o.get("window") or o.get("dead"):
            why = "window is gone" if not o.get("window") else "pane is dead"
            add(name, "teammate_gone", owner, f"{name}: teammate gone", f"teammate {owner} {why} (task #{tid} in progress)")
        elif o.get("ready_s") is not None and o["ready_s"] >= SILENT_S:
            add(name, "teammate_silent", owner, f"{name}: teammate silent",
                f"teammate {owner} has been idle {o['ready_s'] // 60} min with task #{tid} in progress")
    if not p.get("awake") and queue_before:
        add(name, "awake_dropped", "awake", f"{name}: awake hold dropped", "the queue runs with no live keep-awake hold")
    pace = p.get("pace")
    if pace and pace["used"] - pace["elapsed"] > PACE_MARGIN:
        add(name, "weekly_pace", "seven_day", f"{name}: weekly usage ahead of pace",
            f"weekly usage {pace['used']:g}% with {pace['elapsed']:g}% of the week gone")


def run_overdue_text(name, cmd, elapsed_s, cap_s):
    """The run watch's first alert text (spec 2026-11-24-run-watch-design.md §b); board/watch.py sends it itself, with
    title = project, so the feed line reads `<project>: <name> run past cap: …`. Not a condition: the notifier's
    one-event-per-kind-per-RATE_S rule would drop a second overdue run of the same project."""
    return f"{name} run past cap: {flat_cmd(cmd, 80)} ({int(elapsed_s) // 60} min, cap {int(cap_s) // 60} min)"


def flat_cmd(cmd, n):
    """A command line on one line (whitespace runs collapsed), cut to n characters."""
    return " ".join(str(cmd).split())[:n]


def _esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def banner_argv(title, text):
    return ["osascript", "-e", f'display notification "{_esc(text)}" with title "{_esc(title)}"']


def osascript_runner(argv):
    subprocess.run(argv, capture_output=True, text=True, timeout=10, check=True)


def discord_sink(ev):
    """Append the event to the project's discord feed (tier per kind, the running spec's thread when known), only when the
    project has a bridge.json channel. Never raises."""
    try:
        import discord_feed
        discord_feed.sink_event(ev)
    except Exception as e:   # noqa: BLE001
        print(f"notify: discord sink failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


class Notifier:
    def __init__(self, runner=None, enabled=None, now=time.time, rate_s=RATE_S, keep=100, sinks=None):
        self.runner = runner or osascript_runner
        self.sinks = ([] if os.environ.get("TC_DISCORD_ALERTS") == "0" else [discord_sink]) if sinks is None else list(sinks)
        self.enabled = (os.environ.get("TC_NOTIFY") != "0") if enabled is None else enabled
        self.now, self.rate_s = now, rate_s
        self.events = deque(maxlen=keep)
        self._active = set()        # (project, kind, key) true in the last overview
        self._projects = None       # projects seen in the last overview; None before the first
        self._queue = frozenset()   # projects in queue mode in the last overview (awake_dropped grace)
        self._last = {}             # (project, kind) -> ts of the last event emitted
        self._seq = 0

    def observe(self, ov):
        """Compare one overview with the previous; return the events emitted (also appended to .events)."""
        now = self.now()
        cur = {(c["project"], c["kind"], c["key"]): c for c in conditions(ov, self._queue)}
        events = []
        for k in sorted(set(cur) - self._active):
            c = cur[k]
            if self._projects is None or c["project"] not in self._projects:
                continue   # first overview, or a project that just appeared: seed only
            last = self._last.get((c["project"], c["kind"]))
            if last is not None and now - last < self.rate_s:
                continue
            self._last[(c["project"], c["kind"])] = now
            self._seq += 1
            events.append({"id": self._seq, "ts": now, **c})
        self._active = set(cur)
        self._projects = {p["project"] for p in ov.get("projects") or []}
        self._queue = frozenset(p["project"] for p in ov.get("projects") or [] if p.get("queue"))
        for ev in events:
            self.events.append(ev)
            if self.enabled:
                self.banner(ev)
            for sink in self.sinks:
                try:
                    sink(ev)
                except Exception as e:   # noqa: BLE001 - one failing sink never blocks the next or the banner
                    print(f"notify: sink failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return events

    def banner(self, ev):
        try:
            self.runner(banner_argv(ev["title"], ev["text"]))
        except Exception as e:   # noqa: BLE001 - a failed banner is logged and nothing else happens
            print(f"notify: banner failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def recent(self):
        return list(self.events)
