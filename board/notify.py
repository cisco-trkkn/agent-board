"""notify: code-driven events from successive overviews (board/overview.py records), delivered as macOS banners.

Rules (spec 2026-10-28-overseer-design.md): an event fires once when its condition first appears, not again while it
holds, again after it clears and comes back; at most one event of a kind per project every RATE_S seconds; the first
overview, and a project's first appearance, only seed the latch (nothing "appears" at startup). TC_NOTIFY=0 turns
delivery off. The osascript call goes through an injected runner. Pure except for the runner and the clock.
"""
import os
import subprocess
import sys
import time
from collections import deque

KINDS = ("needs_you", "plan_done", "test_failed", "lead_idle", "context", "usage", "failing", "stuck")
RATE_S = 300      # at most one event of a kind per project in this window
IDLE_S = 900      # a lead idle this long with open tasks is event 4
USAGE_KINDS = ("burn", "total", "day_total")


def conditions(ov):
    """Every condition true in one overview: [{project, kind, key, title, text}]. Deterministic order."""
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


def _esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def banner_argv(title, text):
    return ["osascript", "-e", f'display notification "{_esc(text)}" with title "{_esc(title)}"']


def osascript_runner(argv):
    subprocess.run(argv, capture_output=True, text=True, timeout=10, check=True)


class Notifier:
    def __init__(self, runner=None, enabled=None, now=time.time, rate_s=RATE_S, keep=100):
        self.runner = runner or osascript_runner
        self.enabled = (os.environ.get("TC_NOTIFY") != "0") if enabled is None else enabled
        self.now, self.rate_s = now, rate_s
        self.events = deque(maxlen=keep)
        self._active = set()        # (project, kind, key) true in the last overview
        self._projects = None       # projects seen in the last overview; None before the first
        self._last = {}             # (project, kind) -> ts of the last event emitted
        self._seq = 0

    def observe(self, ov):
        """Compare one overview with the previous; return the events emitted (also appended to .events)."""
        now = self.now()
        cur = {(c["project"], c["kind"], c["key"]): c for c in conditions(ov)}
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
        if not self.enabled:
            return []
        for ev in events:
            self.events.append(ev)
            self.banner(ev)
        return events

    def banner(self, ev):
        try:
            self.runner(banner_argv(ev["title"], ev["text"]))
        except Exception as e:   # noqa: BLE001 - a failed banner is logged and nothing else happens
            print(f"notify: banner failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def recent(self):
        return list(self.events)
