# Night watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While a queue runs overnight, the board notices a stalled queue (a dead or silent teammate, an idle lead, a dropped awake hold, a weekly usage pace that will not last), tells the user on Discord, nudges the lead once, restarts a dropped awake hold, re-alerts after 15 min, and the Discord bridge says when the board itself is down.

**Architecture:** `board/overview.py` adds four record fields (`queue`, `owned`, `awake`, `pace`); `board/notify.py` turns them into four new event kinds with the existing latch, in queue mode only. A new `board/watch.py` takes the notifier's events on every overview and, per stall, queues one `[Watch]` line for the lead (the board's existing `[Board]` line path, `COMMENTS`), runs `tmux-ctl awake on --queue --lid` for a dropped hold, posts the re-alert, keeps `watch.json` and writes a heartbeat. `board/server.py` calls it after the notifier. The Discord bridge (`tools/discord-bridge/lib/watch.js`) reads the heartbeat each minute and posts "board down" / "board back".

**Tech Stack:** Python 3 standard library (`board/`, `unittest`), Node >= 22 (`node:test`, discord.js already a dependency), zsh test harness `tools/tests/lib.zsh` on a scratch tmux 3.8 server.

**Spec:** docs/superpowers/specs/2026-11-23-night-watch-design.md

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-23-night-watch-design.md",
 "base": "0af42b5b388826b46ecd25063192c9d2f558f87d",
 "depends_on": [],
 "writes": [
  {"path": "board/planview.py", "mode": "modify"},
  {"path": "board/overview.py", "mode": "modify"},
  {"path": "board/notify.py", "mode": "modify"},
  {"path": "board/discord_feed.py", "mode": "modify"},
  {"path": "board/watch.py", "mode": "create"},
  {"path": "board/server.py", "mode": "modify"},
  {"path": "board/tests/test_overview_watch.py", "mode": "create"},
  {"path": "board/tests/test_notify_watch.py", "mode": "create"},
  {"path": "board/tests/test_watch.py", "mode": "create"},
  {"path": "board/tests/test_watch_wiring.py", "mode": "create"},
  {"path": "tools/tests/test_night_watch_e2e.zsh", "mode": "create"},
  {"path": "tools/discord-bridge/lib/watch.js", "mode": "create"},
  {"path": "tools/discord-bridge/bridge.js", "mode": "modify"},
  {"path": "tools/discord-bridge/test/watch.test.js", "mode": "create"},
  {"path": "claude/orchestrator.md", "mode": "modify"},
  {"path": "tools/tests/test_plugin.zsh", "mode": "modify"},
  {"path": "docs/ARCHITECTURE.md", "mode": "modify"}
 ],
 "reads": ["docs/superpowers/specs/2026-11-23-night-watch-design.md", "board/tc_env.py", "board/usage.py", "board/paneclass.py",
           "board/artifacts.py", "board/restore.py", "board/tests/test_overview.py", "board/tests/test_notify.py",
           "board/tests/test_overview_api.py", "board/tests/test_discord_wiring.py", "board/tests/test_discord_feed.py",
           "board/tests/test_planview.py", "tools/tests/lib.zsh", "tools/tests/all.zsh", "tools/tests/run-all.zsh",
           "tools/tests/test_queue_ask_rule.zsh", "tools/lib/awake.zsh", "tools/lib/tc-env.zsh", "bin/tmux-ctl",
           "tools/discord-bridge/lib/state.js", "tools/discord-bridge/test/fake-client.js", "tools/discord-bridge/test/bridge.test.js",
           "tools/discord-bridge/package.json"],
 "produces": ["overview record fields queue/owned/awake/pace", "notify kinds teammate_gone/teammate_silent/awake_dropped/weekly_pace",
              "$TC_STATE_DIR/watch.json", "$TC_STATE_DIR/watch/heartbeat", "[Watch] lead lines"],
 "consumes": ["usage.plan_limits", "$TC_STATE_DIR/awake.json", "agent-status records (paneclass.mod_records)", "artifacts.CommentQueue.add_line"],
 "tests": ["board/tests/test_overview_watch.py", "board/tests/test_notify_watch.py", "board/tests/test_watch.py",
           "board/tests/test_watch_wiring.py", "tools/tests/test_night_watch_e2e.zsh", "tools/discord-bridge/test/watch.test.js",
           "tools/tests/test_plugin.zsh"]}
```

## Global Constraints

- **Queue mode** (spec §1) = the lead's *live* task list (`planview.view(...)["active"]` is True) holds a task whose subject starts `Plan & run:`, whose status is `pending`, `blocked` (planview's name for a pending task with an open blocker) or `in_progress`, and whose metadata has a `queue` key. Outside queue mode no new kind fires and the watch does nothing: the notifier behaves exactly as today.
- **Constants (exact):** `notify.SILENT_S = 1800`, `notify.PACE_MARGIN = 15` (strictly greater than), `watch.REALERT_S = 900`; the bridge's `STALE_MS = 5 * 60 * 1000` (strictly older than) and `CHECK_MS = 60 * 1000`. The existing `notify.RATE_S` latch rules apply to the new kinds unchanged.
- **Kinds and keys:** `teammate_gone` (key = owner), `teammate_silent` (key = owner), `awake_dropped` (key `awake`), `weekly_pace` (key `seven_day`). Stall kinds (alert + one nudge + one re-alert) are `teammate_gone`, `teammate_silent`, `lead_idle`, `awake_dropped`; `weekly_pace` is alert only.
- **Lead lines (exact text, spec §3):**
  - `[Watch] teammate <owner> window is gone (task #<id> in progress): respawn it.`
  - `[Watch] teammate <owner> has been idle <n> min with task #<id> in progress: check its report or nudge it.`
  - `[Watch] you have been idle <n> min with <k> open tasks: continue the queue.`
  - `[Watch] the awake hold dropped and I restarted it: <ok | failed: <one line>>.`
- **Re-alert text:** title `<project>`, text `<the condition's text> — lead did not react (15 min)`; the feed line reads `<project>: <text> — lead did not react (15 min)`.
- **Board-down posts (exact):** `⚠️ <project>: board down, night watch off (last heartbeat <at as written in the heartbeat>)` and `<project>: board back, night watch on`.
- **Files:** `$TC_STATE_DIR/watch.json` = `{"stalls": {"<project>\t<kind>\t<key>": {"first_at", "nudged_at", "fixed_at", "realerted_at", "fix"?}}}`; `$TC_STATE_DIR/watch/heartbeat` = `{"at": "<YYYY-MM-DDTHH:MM:SSZ>", "queue": [<sorted project names in queue mode>]}`. `$TC_STATE_DIR` is `tc_env.state_dir()` in Python and the same rule in node (`TC_STATE`, else `${TMPDIR:-/tmp}/tmux-ctl-<uid>`).
- **Isolation:** every test sets `TC_STATE` to a temp dir (or passes a temp `state_dir`/`heartbeat`); no test writes the real `~/.local/state/agent-board/watch*` or `${TMPDIR}/tmux-ctl-<uid>/watch*`.
- **No new process, no LLM, no timer in the board:** the watch runs inside the overview the board already builds (the notifier thread, every `OVERVIEW_EVERY` s).
- Commits: conventional with scope (`feat(board): …`, `feat(discord-bridge): …`, `docs(architecture): …`, `test(board): …`), path-scoped (`git commit -- <paths>`), ending with the attribution trailer your harness specifies.

**User decisions (already made):**
- Night watch only; spend watch, per-component watchers and architecture scanning are out of scope (spec Decision 1).
- On a stall: alert + one nudge + safe fixes + re-alert (Decision 2).
- Extend the notifier: code in the board, deterministic, no LLM, no new process; the Discord bridge watches the board's heartbeat (Decision 3).

**Planner assumptions (made without the user; the lead may override):**
- A1. The nudge goes through the board's existing lead-line queue (`COMMENTS.add_line`, delivered by `deliver_comments` with `send-keys`, the path `[Board]` lines use), not `tmux-ctl tell`: `tell` refuses any window that is not a worker agent (`is_agent`, bin/tmux-ctl line ~613), so it cannot type into the lead's `claude` window. The watch decides "lead ready" itself from the lead pane's own state (`agents[]` entry of window `claude`, state `ready`), not `lead.status`, which reads `working` while any teammate works. The queue's delivery adds the existing guards (never while a prompt shows, never onto typed input).
- A2. `lead_idle` keeps its `routine` feed tier (card only) outside queue mode; in queue mode the watch posts it itself as a `watch` feed event (tier `critical`) when the stall opens, so the user is told. The four new kinds map to `critical` in `discord_feed.NOTIFY_TIERS`.
- A3. The awake fix's result is reported in a follow-up `watch` alert (`<project>: awake hold restarted: ok|failed: …`) right after the notifier's `awake_dropped` alert, and in the nudge; the notifier's alert itself is sent before the watch runs.
- A4. An owner named `team-lead` is never a teammate (no `✦` window): `overview.NOT_TEAMMATES`.
- A5. A stall opens only on a notifier event (that is when the first alert was sent); after a board restart the notifier seeds without events and the watch keeps the stalls read from `watch.json` while their condition holds.
- A6. `TC_WATCH=0` turns the watch off (tests, emergencies); `TC_DISCORD_ALERTS=0` turns its Discord alerts off as it does the notifier's.
- A7. The bridge mentions the user on the down post (as `critical` feed posts do) and not on the back post; it keeps its state in `<bridge dir>/watch-state.json` so a restarted bridge neither repeats nor forgets a down post. The project name is the bridge dir's basename (`tc_env.discord_dir(project)`).

**Cross-spec note:** `docs/superpowers/specs/2026-11-23-remote-lead-liveness-design.md` (another plan in this batch) also edits `board/overview.py` and `tools/discord-bridge/bridge.js`. There is no interface dependency (`depends_on` is empty); whichever runs second rebases its edits onto the other. All new logic here lives in new files (`board/watch.py`, `tools/discord-bridge/lib/watch.js`) and the edits to shared files are small and additive.

---

### Task 1: Overview fields for the night watch

**Goal:** Every overview record carries `queue` (queue mode), `owned` (owned in-progress tasks with window, dead pane and ready time), `awake` (live keep-awake hold) and `pace` (weekly used % vs elapsed %), the inputs of the four new notifier kinds.

**Files:**
- Modify: `board/planview.py` (`_norm`, `_finish`: a `queue` flag per task)
- Modify: `board/overview.py` (`RECORD_KEYS`, `queue_mode`, `owned_tasks`, `awake_live`, `weekly_pace`, `record`, `build`)
- Test: `board/tests/test_overview_watch.py` (create)

**Acceptance Criteria:**
- [ ] `overview.RECORD_KEYS` ends with `queue`, `owned`, `awake`, `pace`, `agents`, and every built record has exactly those keys in that order
- [ ] `queue_mode` is True only for an active view with an open (`pending`/`blocked`/`in_progress`) `Plan & run:` task whose metadata has `queue`
- [ ] `owned_tasks` reports window present/absent, dead first pane and `ready_s` from the agent-status record, skips owner `team-lead`, and returns [] (not 'gone') when tmux fails
- [ ] `awake_live` is True only when `<state_dir>/awake.json` names a live `caffeinatePid`
- [ ] `weekly_pace` returns `{used, elapsed}` percent of the 7-day window, None without a tap, a reset time, or with the window past
- [ ] the existing overview, planview and overview API tests still pass

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_*view*.py'`

**modelTier:** standard

**Steps:**

- [ ] **Step 1: Write the failing test** — create `board/tests/test_overview_watch.py`:

```python
"""overview: the night watch fields (queue, owned, awake, pace). Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §2, §6."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import overview  # noqa: E402

NOW = 1_800_000_000.0


def task(i, subject, status, owner="", queue=False):
    return {"id": str(i), "subject": subject, "status": status, "owner": owner, "queue": queue}


def view(*tasks, active=True):
    return {"name": "p", "active": active, "tasks": list(tasks)}


def panes(*rows):
    """A tmux runner answering list-panes -s with rows (window, pane, dead, index); anything else is an error."""
    def run(*args, check=False):
        if args[0] == "list-panes" and "-s" in args:
            return "".join(f"{w}\t{p}\t{d}\t{i}\n" for w, p, d, i in rows)
        raise AssertionError(args)
    return run


class QueueModeTest(unittest.TestCase):
    def test_open_plan_and_run_with_queue_metadata_is_queue_mode(self):
        for st in ("pending", "blocked", "in_progress"):
            self.assertTrue(overview.queue_mode(view(task(1, "Plan & run: docs/s.md", st, queue=True))), st)

    def test_without_queue_metadata_completed_or_idle_view_it_is_off(self):
        # mutation: drop the `t.get("queue")` check -> the first assertion fails
        self.assertFalse(overview.queue_mode(view(task(1, "Plan & run: docs/s.md", "pending"))))
        self.assertFalse(overview.queue_mode(view(task(1, "Plan & run: docs/s.md", "completed", queue=True))))
        self.assertFalse(overview.queue_mode(view(task(1, "Task 1: x", "pending", queue=True))))
        # mutation: drop the view["active"] check -> this fails (an idle .tasks.json view is not the lead's list)
        self.assertFalse(overview.queue_mode(view(task(1, "Plan & run: docs/s.md", "pending", queue=True), active=False)))


class OwnedTest(unittest.TestCase):
    V = view(task(1, "Plan & run: docs/s.md", "in_progress", queue=True), task(2, "Task 2: x", "in_progress", owner="fake"),
             task(3, "Task 3: y", "pending", owner="other"), task(4, "Task 4: z", "in_progress", owner="team-lead"))

    def test_window_present_alive_and_ready_since(self):
        mods = {"%9": {"state": "ready", "since": NOW - 1900}}
        got = overview.owned_tasks("p", self.V, panes(("claude", "%1", "0", "0"), ("✦ fake", "%9", "0", "0")), mods, NOW)
        self.assertEqual(got, [{"owner": "fake", "task": "2", "window": True, "dead": False, "ready_s": 1900}])

    def test_window_gone(self):
        got = overview.owned_tasks("p", self.V, panes(("claude", "%1", "0", "0")), {}, NOW)
        self.assertEqual(got, [{"owner": "fake", "task": "2", "window": False, "dead": False, "ready_s": None}])

    def test_dead_pane_and_busy_agent(self):
        # mutation: read pane_dead from the wrong column -> dead stays False and this fails
        got = overview.owned_tasks("p", self.V, panes(("✦ fake", "%9", "1", "0")), {"%9": {"state": "busy", "since": NOW - 5000}}, NOW)
        self.assertEqual(got, [{"owner": "fake", "task": "2", "window": True, "dead": True, "ready_s": None}])

    def test_first_pane_of_the_window_decides(self):
        got = overview.owned_tasks("p", self.V, panes(("✦ fake", "%8", "0", "1"), ("✦ fake", "%9", "1", "0")), {}, NOW)
        self.assertTrue(got[0]["dead"])

    def test_failing_tmux_is_unknown_not_gone(self):
        # mutation: return entries with window False on a tmux error -> this fails
        def boom(*a, check=False):
            raise RuntimeError("no server")
        self.assertEqual(overview.owned_tasks("p", self.V, boom, {}, NOW), [])


class AwakeTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup)
        self.d = Path(self.td.name)

    def test_missing_file_is_not_live(self):
        self.assertFalse(overview.awake_live(self.d, lambda pid: True))

    def test_live_and_dead_caffeinate(self):
        (self.d / "awake.json").write_text(json.dumps({"caffeinatePid": 4242, "queue": True}))
        self.assertTrue(overview.awake_live(self.d, lambda pid: pid == 4242))
        # mutation: skip the pid_alive call -> this fails
        self.assertFalse(overview.awake_live(self.d, lambda pid: False))

    def test_real_pid_check(self):
        (self.d / "awake.json").write_text(json.dumps({"caffeinatePid": os.getpid()}))
        self.assertTrue(overview.awake_live(self.d))


class PaceTest(unittest.TestCase):
    def test_used_and_elapsed_percent(self):
        lim = {"seven_day": {"used_percentage": 60, "resets_at": NOW + 3.5 * 86400}}
        self.assertEqual(overview.weekly_pace(lim, NOW), {"used": 60, "elapsed": 50.0})

    def test_unknown_or_past_window_is_none(self):
        self.assertIsNone(overview.weekly_pace(None, NOW))
        self.assertIsNone(overview.weekly_pace({"seven_day": {"used_percentage": 60}}, NOW))
        self.assertIsNone(overview.weekly_pace({"seven_day": {"used_percentage": 60, "resets_at": NOW - 1}}, NOW))


class RecordKeysTest(unittest.TestCase):
    def test_new_keys_sit_before_agents(self):
        self.assertEqual(overview.RECORD_KEYS[-5:], ("queue", "owned", "awake", "pace", "agents"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s board/tests -p 'test_overview_watch.py'`
Expected: errors `AttributeError: module 'overview' has no attribute 'queue_mode'` (and `owned_tasks`, `awake_live`, `weekly_pace`), and the `RECORD_KEYS` test fails.

- [ ] **Step 3: Implement** — make exactly these edits (shown as a diff against `main` at the plan's base; if another plan moved the context, make the same change by hand). In `board/planview.py`, each normalised task carries `queue` (its metadata has a `queue` key):

```diff
--- a/board/planview.py
+++ b/board/planview.py
@@ -82,7 +82,7 @@
     return {"id": str(t.get("id", "")), "subject": str(t.get("subject", "")), "status": str(t.get("status", "pending")),
             "owner": str(t.get("owner") or ""), "blockedBy": [str(b) for b in (t.get("blockedBy") or [])],
             "tier": _tier(t), "outcome": _str(meta, "outcome"), "answeredAt": _str(meta.get("queue"), "answeredAt"),
-            "batch": _str(meta.get("queue"), "batch"), "planPath": _str(meta, "plan")}
+            "batch": _str(meta.get("queue"), "batch"), "planPath": _str(meta, "plan"), "queue": "queue" in meta}
 
 
 def _finish(tasks):
@@ -96,7 +96,7 @@
         out.append({"id": t["id"], "subject": t["subject"], "status": st, "owner": t["owner"], "state": "",
                     "tier": t["tier"], "blockedBy": t["blockedBy"], "outcome": t.get("outcome", ""),
                     "answeredAt": t.get("answeredAt", ""), "batch": t.get("batch", ""),
-                    "planPath": t.get("planPath", "")})
+                    "planPath": t.get("planPath", ""), "queue": bool(t.get("queue"))})
     return out
```

In `board/overview.py`: four record keys before `agents`, the four helpers, and `limits` / `pid_alive` parameters on `record()` and `build()` (both default so every existing caller still works):

```diff
--- a/board/overview.py
+++ b/board/overview.py
@@ -25,7 +25,11 @@
 import activity as activity_mod  # noqa: E402
 import artifacts, planview, usage  # noqa: E402
 
-RECORD_KEYS = ("project", "path", "attached", "plan", "needs_you", "last_run", "lead", "artifacts", "epoch", "alerts", "spend_today", "agents")
+RECORD_KEYS = ("project", "path", "attached", "plan", "needs_you", "last_run", "lead", "artifacts", "epoch", "alerts", "spend_today",
+               "queue", "owned", "awake", "pace", "agents")
+PLAN_RUN = "Plan & run:"
+WEEK_S = 7 * 86400
+NOT_TEAMMATES = ("team-lead",)   # an owner the lead gives itself has no ✦ window
 ERRORS = (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError)
 
 
@@ -183,7 +187,72 @@
     return out
 
 
-def record(s, live, now, *, home, state_dir, tmux, th, spend, activity, mods=None):
+def queue_mode(view):
+    """True when the lead's live list holds an open `Plan & run:` task whose metadata carries `queue` (night watch spec §1)."""
+    return bool(view.get("active")) and any(
+        t.get("subject", "").startswith(PLAN_RUN) and t.get("status") in ("pending", "blocked", "in_progress") and t.get("queue")
+        for t in view.get("tasks") or [])
+
+
+def owned_tasks(name, view, tmux, mods, now):
+    """One entry per owned in-progress task: {owner, task, window, dead, ready_s}. window: a `✦ <owner>` window exists;
+    dead: its first pane is dead; ready_s: seconds its agent-status record has been `ready`, else None.
+    [] when the pane listing fails (unknown is never read as gone)."""
+    mine = [t for t in view.get("tasks") or [] if t.get("status") == "in_progress" and t.get("owner") and t["owner"] not in NOT_TEAMMATES]
+    if not mine:
+        return []
+    try:
+        rows = tmux("list-panes", "-s", "-t", f"={name}", "-F", "#{window_name}\t#{pane_id}\t#{pane_dead}\t#{pane_index}")
+    except Exception:   # noqa: BLE001 - a failing or unexpected tmux leaves the field empty
+        return []
+    first = {}
+    for line in str(rows).splitlines():
+        f = line.split("\t")
+        if len(f) == 4 and f[3].isdigit() and (f[0] not in first or int(f[3]) < first[f[0]][2]):
+            first[f[0]] = (f[1], f[2] == "1", int(f[3]))
+    out = []
+    for t in mine:
+        w = first.get(f"✦ {t['owner']}")
+        rec = (mods or {}).get(w[0]) if w else None
+        ready = _secs(now, rec.get("since")) if rec and rec.get("state") == "ready" else None
+        out.append({"owner": t["owner"], "task": t["id"], "window": w is not None, "dead": bool(w and w[1]), "ready_s": ready})
+    return out
+
+
+def _pid_alive(pid):
+    try:
+        os.kill(int(pid), 0)
+    except ProcessLookupError:
+        return False
+    except PermissionError:
+        return True
+    except (OSError, ValueError, TypeError):
+        return False
+    return True
+
+
+def awake_live(state_dir, pid_alive=_pid_alive):
+    """True when <state_dir>/awake.json names a live caffeinatePid (the keep-awake hold)."""
+    try:
+        cp = json.loads((Path(state_dir) / "awake.json").read_text()).get("caffeinatePid")
+    except (OSError, ValueError, AttributeError):
+        return False
+    return bool(cp) and bool(pid_alive(cp))
+
+
+def weekly_pace(limits, now):
+    """{used, elapsed} in percent of the 7-day window from usage.plan_limits(), or None (no tap, no reset time, window past)."""
+    sd = (limits or {}).get("seven_day") if isinstance(limits, dict) else None
+    used = sd.get("used_percentage") if isinstance(sd, dict) else None
+    resets = sd.get("resets_at") if isinstance(sd, dict) else None
+    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
+    if not num(used) or not num(resets) or resets <= now:
+        return None
+    elapsed = max(0.0, min(100.0, 100 * (1 - (resets - now) / WEEK_S)))
+    return {"used": round(used, 1), "elapsed": round(elapsed, 1)}
+
+
+def record(s, live, now, *, home, state_dir, tmux, th, spend, activity, mods=None, limits=None, pid_alive=_pid_alive):
     name = s["name"]
     root = s.get("path")
     try:
@@ -199,12 +268,14 @@
             "plan": plan_digest(view), "needs_you": needs_you(s, mods), "last_run": last_run(name, now),
             "lead": lead_state(s, (activity or {}).get(name), now, mods), "artifacts": arts, "epoch": epoch,
             "alerts": project_alerts(s, live, spent, th) + agent_alerts(s, mods, now, th), "spend_today": spent,
-            "agents": agents(s, mods, now)}
+            "queue": queue_mode(view), "owned": owned_tasks(name, view, tmux, mods, now),
+            "awake": awake_live(state_dir, pid_alive), "pace": weekly_pace(limits, now), "agents": agents(s, mods, now)}
 
 
-def build(sessions, live, now, *, home, state_dir, tmux, th=None, spend=None, activity=None, mods=None):
+def build(sessions, live, now, *, home, state_dir, tmux, th=None, spend=None, activity=None, mods=None, limits=None, pid_alive=_pid_alive):
     th = th if th is not None else usage.DEFAULT_ALERTS
-    projects = [record(s, live or [], now, home=home, state_dir=state_dir, tmux=tmux, th=th, spend=spend, activity=activity, mods=mods)
+    projects = [record(s, live or [], now, home=home, state_dir=state_dir, tmux=tmux, th=th, spend=spend, activity=activity, mods=mods,
+                       limits=limits, pid_alive=pid_alive)
                 for s in sessions if not s["name"].startswith("_web-") and s["name"] != "overseer"]
     return {"generated": now, "projects": projects}
```

The `-F` format's `\t` is a Python escape (a tab): `#{window_name}<TAB>#{pane_id}<TAB>#{pane_dead}<TAB>#{pane_index}`, and each row is split on a tab. Probe (tmux 3.8, scratch server with `-f /dev/null`, `remain-on-exit on`, a window whose command had exited): that `list-panes -s -t '=proj'` printed `claude %0 0 0` and `✦ fake %1 1 0` (tab-separated).

- [ ] **Step 4: Run the mutations named in the test comments** — each must make the named test fail; revert each after:
  drop `and t.get("queue")` in `queue_mode`; drop `bool(view.get("active")) and`; read `f[1] == "1"` instead of `f[2] == "1"`; return `[{..., "window": False}]` on a tmux error; skip `pid_alive(cp)` in `awake_live`.

- [ ] **Step 5: Run the task's tests to verify they pass**

Run: `python3 -m unittest discover -s board/tests -p 'test_*view*.py'`
Expected: `OK` (this also runs `test_overview.py`, `test_overview_api.py`, `test_overview_home_ui.py` and `test_planview.py`: the existing record-keys tests still pass because the new keys sit before `agents`, and the existing fake tmux, which raises on `list-panes`, leaves `owned` empty instead of breaking the record).

- [ ] **Step 6: Commit**

```bash
git add board/planview.py board/overview.py board/tests/test_overview_watch.py
git commit -m "feat(board): overview fields for the night watch (queue, owned, awake, pace)" -- board/planview.py board/overview.py board/tests/test_overview_watch.py
```
(End the message with the attribution trailer your harness specifies.)

### Task 2: Notifier kinds for the night watch

**Goal:** `board/notify.py` emits `teammate_gone`, `teammate_silent`, `awake_dropped` and `weekly_pace` for projects in queue mode, with the existing latch, and the Discord feed posts them (and the watch's own `watch` events) as `critical`.

**Files:**
- Modify: `board/notify.py` (`KINDS`, `SILENT_S`, `PACE_MARGIN`, `_watch_conditions`, `conditions`)
- Modify: `board/discord_feed.py` (`NOTIFY_TIERS`)
- Test: `board/tests/test_notify_watch.py` (create)

**Acceptance Criteria:**
- [ ] `teammate_gone` fires for an owned in-progress task whose window is missing or whose pane is dead, key = owner, text names the task id
- [ ] `teammate_silent` fires at `ready_s >= 1800`, not at 1799
- [ ] `awake_dropped` (key `awake`) fires when `awake` is False; `weekly_pace` (key `seven_day`) when used - elapsed > 15
- [ ] none of the four fires when `queue` is False or the record lacks the new fields
- [ ] the four kinds and `watch` map to tier `critical` in `discord_feed.NOTIFY_TIERS`; `lead_idle` stays `routine`
- [ ] the latch holds: one event when the condition appears, none while it holds, one again after it clears and returns

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_notify*.py' && python3 -m unittest discover -s board/tests -p 'test_discord_feed.py'`

**Blocked by:** Task 1

**modelTier:** mechanical

**Steps:**

- [ ] **Step 1: Write the failing test** — create `board/tests/test_notify_watch.py`:

```python
"""notify: the night watch kinds (teammate_gone, teammate_silent, awake_dropped, weekly_pace), queue mode only.
Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §2. Records are shape-exact overview records (RECORD_KEYS)."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_feed, notify  # noqa: E402


def project(name="p", **kw):
    rec = {"project": name, "path": f"/{name}", "needs_you": [], "last_run": None, "alerts": [],
           "plan": {"name": "plan-a", "active": True, "done": 1, "total": 3, "in_progress": []},
           "lead": {"status": "working", "last_active": 100.0, "idle_s": 0}, "artifacts": [], "epoch": 0, "spend_today": 0.0,
           "queue": True, "owned": [], "awake": True, "pace": None, "agents": []}
    rec.update(kw)
    return rec


def ov(*projects):
    return {"generated": 0, "projects": list(projects)}


def owned(**kw):
    o = {"owner": "fake", "task": "2", "window": True, "dead": False, "ready_s": None}
    o.update(kw)
    return o


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def kinds(rec):
    return [(c["kind"], c["key"]) for c in notify.conditions(ov(rec))]


class ConditionsTest(unittest.TestCase):
    def test_teammate_gone_window_missing_or_pane_dead(self):
        self.assertEqual(kinds(project(owned=[owned(window=False)])), [("teammate_gone", "fake")])
        c = notify.conditions(ov(project(owned=[owned(dead=True)])))[0]
        self.assertEqual((c["kind"], c["title"]), ("teammate_gone", "p: teammate gone"))
        self.assertIn("pane is dead", c["text"]); self.assertIn("#2", c["text"])

    def test_teammate_silent_at_30_min_not_before(self):
        # mutation: compare with > instead of >= -> the 1800 case fails
        self.assertEqual(kinds(project(owned=[owned(ready_s=1799)])), [])
        self.assertEqual(kinds(project(owned=[owned(ready_s=1800)])), [("teammate_silent", "fake")])
        self.assertIn("idle 30 min", notify.conditions(ov(project(owned=[owned(ready_s=1800)])))[0]["text"])

    def test_awake_dropped(self):
        self.assertEqual(kinds(project(awake=False)), [("awake_dropped", "awake")])

    def test_weekly_pace_over_15_points(self):
        self.assertEqual(kinds(project(pace={"used": 65, "elapsed": 50.0})), [])
        self.assertEqual(kinds(project(pace={"used": 65.1, "elapsed": 50.0})), [("weekly_pace", "seven_day")])

    def test_queue_mode_off_gives_none_of_them(self):
        # mutation: drop the `if p.get("queue")` gate -> this fails
        rec = project(queue=False, owned=[owned(window=False)], awake=False, pace={"used": 90, "elapsed": 10})
        self.assertEqual(kinds(rec), [])

    def test_records_without_the_new_fields_are_quiet(self):
        rec = project(); [rec.pop(k) for k in ("queue", "owned", "awake", "pace")]
        self.assertEqual(kinds(rec), [])

    def test_kinds_and_feed_tiers(self):
        for k in ("teammate_gone", "teammate_silent", "awake_dropped", "weekly_pace"):
            self.assertIn(k, notify.KINDS)
            self.assertEqual(discord_feed.NOTIFY_TIERS[k], "critical")
        self.assertEqual(discord_feed.NOTIFY_TIERS["watch"], "critical")


class LatchTest(unittest.TestCase):
    def test_fires_once_while_it_holds_again_after_it_clears(self):
        clock = Clock()
        n = notify.Notifier(runner=lambda a: None, enabled=False, now=clock, sinks=[])
        n.observe(ov(project()))
        self.assertEqual([e["kind"] for e in n.observe(ov(project(awake=False)))], ["awake_dropped"])
        clock.t += 60
        self.assertEqual(n.observe(ov(project(awake=False))), [])
        n.observe(ov(project()))
        clock.t += notify.RATE_S
        self.assertEqual([e["kind"] for e in n.observe(ov(project(awake=False)))], ["awake_dropped"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s board/tests -p 'test_notify_watch.py'`
Expected: FAIL — no condition is produced for the new kinds (`[] != [('teammate_gone', 'fake')]`) and `KeyError: 'teammate_gone'` in the tiers test.

- [ ] **Step 3: Implement** — make exactly these edits (a diff against `main` at the plan's base):

```diff
--- a/board/notify.py
+++ b/board/notify.py
@@ -11,10 +11,13 @@
 import time
 from collections import deque
 
-KINDS = ("needs_you", "plan_done", "test_failed", "lead_idle", "context", "usage", "failing", "stuck")
+KINDS = ("needs_you", "plan_done", "test_failed", "lead_idle", "context", "usage", "failing", "stuck",
+         "teammate_gone", "teammate_silent", "awake_dropped", "weekly_pace")
 RATE_S = 300      # at most one event of a kind per project in this window
 IDLE_S = 900      # a lead idle this long with open tasks is event 4
 USAGE_KINDS = ("burn", "total", "day_total")
+SILENT_S = 1800   # a teammate at its prompt this long with its task in progress (night watch, queue mode only)
+PACE_MARGIN = 15  # weekly usage this many points above the elapsed share of the week (night watch, queue mode only)
 
 
 def conditions(ov):
@@ -39,6 +42,8 @@
         idle = lead.get("idle_s")
         if lead.get("status") == "ready" and idle is not None and idle >= IDLE_S and total and done < total:
             add(name, "lead_idle", "lead", f"{name}: lead idle", f"idle {idle // 60} min with {total - done} open task{'s' if total - done != 1 else ''}")
+        if p.get("queue"):
+            _watch_conditions(p, add)
         for a in p.get("alerts") or []:
             who = a.get("session") or name
             if a.get("kind") == "context":
@@ -54,6 +59,25 @@
     return out
 
 
+def _watch_conditions(p, add):
+    """The night watch kinds for a project in queue mode (spec 2026-11-23-night-watch-design.md §2)."""
+    name = p["project"]
+    for o in p.get("owned") or []:
+        owner, tid = o["owner"], o["task"]
+        if not o.get("window") or o.get("dead"):
+            why = "window is gone" if not o.get("window") else "pane is dead"
+            add(name, "teammate_gone", owner, f"{name}: teammate gone", f"teammate {owner} {why} (task #{tid} in progress)")
+        elif o.get("ready_s") is not None and o["ready_s"] >= SILENT_S:
+            add(name, "teammate_silent", owner, f"{name}: teammate silent",
+                f"teammate {owner} has been idle {o['ready_s'] // 60} min with task #{tid} in progress")
+    if not p.get("awake"):
+        add(name, "awake_dropped", "awake", f"{name}: awake hold dropped", "the queue runs with no live keep-awake hold")
+    pace = p.get("pace")
+    if pace and pace["used"] - pace["elapsed"] > PACE_MARGIN:
+        add(name, "weekly_pace", "seven_day", f"{name}: weekly usage ahead of pace",
+            f"weekly usage {pace['used']:g}% with {pace['elapsed']:g}% of the week gone")
+
+
 def _esc(s):
     return str(s).replace("\\", "\\\\").replace('"', '\\"')
```

```diff
--- a/board/discord_feed.py
+++ b/board/discord_feed.py
@@ -669,7 +669,9 @@
 
 # ---- board wiring: the notifier's sink, the channel check ----
 NOTIFY_TIERS = {"needs_you": "decision", "test_failed": "critical", "failing": "critical", "stuck": "critical",
-                "plan_done": "progress", "lead_idle": "routine", "context": "routine", "usage": "routine"}
+                "plan_done": "progress", "lead_idle": "routine", "context": "routine", "usage": "routine",
+                "teammate_gone": "critical", "teammate_silent": "critical", "awake_dropped": "critical", "weekly_pace": "critical",
+                "watch": "critical"}
 
 
 def channel_of(project):
```

`watch` is the feed kind `board/watch.py` (Task 3) uses for its own alerts (the re-alert, the awake fix result, `lead_idle` in queue mode).

- [ ] **Step 4: Run the mutations named in the test comments** — `>=` to `>` for `SILENT_S`; remove the `if p.get("queue"):` gate (call `_watch_conditions` always). Each must fail its named test; revert.

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m unittest discover -s board/tests -p 'test_notify*.py' && python3 -m unittest discover -s board/tests -p 'test_discord_feed.py'`
Expected: `OK` for both (the existing notifier and feed tests are unchanged: records without the new fields are quiet).

- [ ] **Step 6: Commit**

```bash
git add board/notify.py board/discord_feed.py board/tests/test_notify_watch.py
git commit -m "feat(board): notifier kinds teammate_gone, teammate_silent, awake_dropped, weekly_pace" -- board/notify.py board/discord_feed.py board/tests/test_notify_watch.py
```
(End the message with the attribution trailer your harness specifies.)

### Task 3: board/watch.py, the night watch

**Goal:** `board/watch.py` turns the notifier's events for queue-mode projects into one `[Watch]` nudge per stall to a ready lead, one `tmux-ctl awake on --queue --lid` per dropped hold, one re-alert after 15 min, keeps `watch.json` across restarts and writes the heartbeat on every overview.

**Files:**
- Create: `board/watch.py`
- Test: `board/tests/test_watch.py` (create)

**Acceptance Criteria:**
- [ ] a `teammate_gone` stall gets exactly one nudge with the exact spec line, only while the lead's own pane (agents[] window `claude`) is `ready`; a busy lead is nudged on the first later overview where it is ready
- [ ] `teammate_silent`, `lead_idle` and `awake_dropped` nudge lines match the Global Constraints text exactly; `lead_idle` is also posted as a `watch` alert
- [ ] `awake_dropped` runs `["awake", "on", "--queue", "--lid"]` once per stall and reports `ok` or `failed: <first line>` in an alert and the nudge; no other kind runs a fix
- [ ] the re-alert fires once at 900 s after the stall opened (not at 899), never for `weekly_pace`, which gets no nudge either
- [ ] queue mode off: no action and no `watch.json`
- [ ] a cleared stall is removed from `watch.json`; a restarted Watch (fresh notifier, file kept) sends no second nudge and keeps `first_at`
- [ ] every observe writes `watch/heartbeat` = `{"at": <UTC ISO, seconds, Z>, "queue": [sorted queue-mode projects]}`

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_watch.py'`

**Blocked by:** Task 2

**modelTier:** standard

**Steps:**

- [ ] **Step 1: Write the failing test** — create `board/tests/test_watch.py`:

```python
"""watch: the night watch's actions on fixed overview records and a fake clock. Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §3, §5, §7.
Every test runs in a temp state dir (TC_STATE too); the runner, nudge and alert sinks are recorders."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import notify, watch  # noqa: E402


def project(name="p", lead_ready=True, **kw):
    rec = {"project": name, "path": f"/{name}", "needs_you": [], "last_run": None, "alerts": [],
           "plan": {"name": "plan-a", "active": True, "done": 1, "total": 3, "in_progress": []},
           "lead": {"status": "working", "last_active": 100.0, "idle_s": 0}, "artifacts": [], "epoch": 0, "spend_today": 0.0,
           "queue": True, "owned": [], "awake": True, "pace": None,
           "agents": [{"window": "claude", "pane": "%1", "state": "ready" if lead_ready else "working", "state_s": None,
                       "turn_s": None, "tool": None}]}
    rec.update(kw)
    return rec


GONE = [{"owner": "fake", "task": "7", "window": False, "dead": False, "ready_s": None}]


def ov(*projects):
    return {"generated": 0, "projects": list(projects)}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup)
        self.dir = Path(self.td.name)
        os.environ["TC_STATE"] = str(self.dir); self.addCleanup(os.environ.pop, "TC_STATE", None)
        self.clock = Clock()
        self.runs, self.nudges, self.alerts = [], [], []
        self.run_result = "ok"
        self.n = notify.Notifier(runner=lambda a: None, enabled=False, now=self.clock, sinks=[])
        self.w = self.watch()
        self.step(project())   # seed the notifier: a quiet project

    def watch(self):
        def run(argv):
            self.runs.append(argv)
            if self.run_result != "ok":
                raise RuntimeError(self.run_result)
            return "awake: on"
        return watch.Watch(now=self.clock, run=run, nudge=lambda p, line: self.nudges.append((p, line)),
                           alert=self.alerts.append, state_dir=self.dir)

    def step(self, *recs):
        o = ov(*recs)
        return self.w.observe(o, self.n.observe(o))


class StallTest(Base):
    def test_teammate_gone_one_nudge_to_a_ready_lead(self):
        self.step(project(owned=GONE))
        self.assertEqual(self.nudges, [("p", "[Watch] teammate fake window is gone (task #7 in progress): respawn it.")])
        self.clock.t += 60
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 1)   # mutation: drop the nudged_at check -> a second nudge, this fails

    def test_busy_lead_is_not_typed_at_until_it_is_ready(self):
        self.step(project(owned=GONE, lead_ready=False))
        self.assertEqual(self.nudges, [])   # mutation: drop _lead_ready -> this fails
        self.clock.t += 60
        self.step(project(owned=GONE, lead_ready=False))
        self.assertEqual(self.nudges, [])
        self.clock.t += 60
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 1)

    def test_teammate_silent_and_lead_idle_lines(self):
        silent = [{"owner": "fake", "task": "7", "window": True, "dead": False, "ready_s": 1860}]
        self.step(project(owned=silent))
        self.assertEqual(self.nudges[-1][1], "[Watch] teammate fake has been idle 31 min with task #7 in progress: check its report or nudge it.")
        self.step(project(owned=silent, lead={"status": "ready", "last_active": 1.0, "idle_s": 960}))
        self.assertEqual(self.nudges[-1][1], "[Watch] you have been idle 16 min with 2 open tasks: continue the queue.")
        self.assertEqual([a["text"] for a in self.alerts], ["idle 16 min with 2 open tasks"])   # lead_idle is posted by the watch
        self.assertEqual(self.alerts[0]["kind"], "watch")

    def test_queue_mode_off_no_action_no_state(self):
        # mutation: drop the p.get("queue") filter in observe -> nudges, this fails
        self.step(project(queue=False, owned=GONE, awake=False))
        self.assertEqual((self.nudges, self.runs, self.alerts), ([], [], []))
        self.assertFalse((self.dir / "watch.json").exists())

    def test_cleared_stall_is_removed_and_a_new_one_nudges_again(self):
        self.step(project(owned=GONE))
        self.step(project())
        self.assertEqual(json.loads((self.dir / "watch.json").read_text())["stalls"], {})
        self.clock.t += notify.RATE_S
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 2)


class AwakeFixTest(Base):
    def test_fix_runs_once_and_reports_ok(self):
        self.step(project(awake=False))
        self.assertEqual(self.runs, [["awake", "on", "--queue", "--lid"]])
        self.assertEqual(self.nudges, [("p", "[Watch] the awake hold dropped and I restarted it: ok.")])
        self.assertEqual([a["text"] for a in self.alerts], ["awake hold restarted: ok"])
        self.clock.t += 60
        self.step(project(awake=False))
        self.assertEqual(len(self.runs), 1)   # mutation: drop the fixed_at check -> a second run, this fails

    def test_fix_failure_is_one_line(self):
        self.run_result = "awake: no tmux server\nmore detail"
        self.step(project(awake=False))
        self.assertEqual(self.nudges[0][1], "[Watch] the awake hold dropped and I restarted it: failed: awake: no tmux server.")

    def test_no_other_kind_runs_a_fix(self):
        self.step(project(owned=GONE, lead={"status": "ready", "last_active": 1.0, "idle_s": 960}))
        self.assertEqual(self.runs, [])


class RealertTest(Base):
    def test_once_at_15_min_then_nothing(self):
        self.step(project(owned=GONE))
        self.clock.t += watch.REALERT_S - 1
        self.step(project(owned=GONE))
        self.assertEqual(self.alerts, [])   # mutation: REALERT_S check off by the minute -> this fails
        self.clock.t += 1
        self.step(project(owned=GONE))
        self.assertEqual([a["text"] for a in self.alerts],
                         ["teammate fake window is gone (task #7 in progress) — lead did not react (15 min)"])
        self.assertEqual(self.alerts[0]["title"], "p")
        self.clock.t += 3600
        self.step(project(owned=GONE))
        self.assertEqual(len(self.alerts), 1)

    def test_weekly_pace_alert_only(self):
        # mutation: put weekly_pace in STALL_KINDS -> a nudge and a re-alert, this fails
        hot = project(pace={"used": 80, "elapsed": 40.0})
        self.step(hot)
        self.clock.t += watch.REALERT_S * 2
        self.step(hot)
        self.assertEqual((self.nudges, self.alerts, self.runs), ([], [], []))


class RestartTest(Base):
    def test_watch_json_survives_a_restart_without_a_second_nudge(self):
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 1)
        d = json.loads((self.dir / "watch.json").read_text())["stalls"]
        self.assertEqual(list(d), ["p\tteammate_gone\tfake"])
        self.assertEqual(set(d["p\tteammate_gone\tfake"]), {"first_at", "nudged_at", "fixed_at", "realerted_at"})
        # a board restart: a fresh notifier (seeds, no events) and a fresh watch reading the file
        self.n = notify.Notifier(runner=lambda a: None, enabled=False, now=self.clock, sinks=[])
        self.w = self.watch()
        self.clock.t += 60
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 1)
        # mutation: start with no stalls instead of reading watch.json in __init__ -> the seeded notifier gives no event, no re-alert, this fails
        self.clock.t += watch.REALERT_S
        self.step(project(owned=GONE))
        self.assertEqual(len(self.alerts), 1)   # the stall kept its first_at across the restart


class HeartbeatTest(Base):
    def test_every_overview_writes_at_and_queue_projects(self):
        self.step(project("a"), project("b", queue=False))
        hb = json.loads((self.dir / "watch" / "heartbeat").read_text())
        self.assertEqual(hb, {"at": watch.iso(self.clock.t), "queue": ["a"]})
        self.assertRegex(hb["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_default_state_dir_is_tc_state(self):
        w = watch.Watch(now=self.clock)
        self.assertEqual(w.file, self.dir / "watch.json")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s board/tests -p 'test_watch.py'`
Expected: `ModuleNotFoundError: No module named 'watch'`.

- [ ] **Step 3: Implement** — create `board/watch.py`:

```python
"""watch: the night watch. Acts on the notifier's events for projects in queue mode: one nudge to the lead per stall,
the awake fix, one re-alert after REALERT_S, a heartbeat on every overview. Spec docs/superpowers/specs/2026-11-23-night-watch-design.md.

Deterministic, no LLM, no thread of its own: server.py calls Watch.observe(ov, events) after Notifier.observe on each
overview. Clock, tmux-ctl runner, nudge and alert sinks are injected. State: <state_dir>/watch.json (open stalls),
<state_dir>/watch/heartbeat ({"at", "queue"}). Never raises from observe: a failing piece is logged to stderr.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import notify, tc_env  # noqa: E402

STALL_KINDS = ("teammate_gone", "teammate_silent", "lead_idle", "awake_dropped")   # alert + nudge + re-alert
WATCH_KINDS = STALL_KINDS + ("weekly_pace",)                                       # weekly_pace: alert only
REALERT_S = 900
AWAKE_ARGV = ("awake", "on", "--queue", "--lid")


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _key(project, kind, key):
    return f"{project}\t{kind}\t{key}"


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True))
    os.replace(tmp, path)


def _lead_ready(rec):
    """The lead's own pane (window `claude`) is at its prompt. Not lead.status: that reads `working` while a teammate works."""
    return any(a.get("window") == "claude" and a.get("state") == "ready" for a in rec.get("agents") or [])


def _owned(rec, owner):
    return next((o for o in rec.get("owned") or [] if o.get("owner") == owner), {})


def nudge_line(kind, key, rec, stall):
    if kind == "teammate_gone":
        return f"[Watch] teammate {key} window is gone (task #{_owned(rec, key).get('task', '?')} in progress): respawn it."
    if kind == "teammate_silent":
        o = _owned(rec, key)
        return (f"[Watch] teammate {key} has been idle {(o.get('ready_s') or 0) // 60} min with task #{o.get('task', '?')} in progress: "
                "check its report or nudge it.")
    if kind == "lead_idle":
        plan, lead = rec.get("plan") or {}, rec.get("lead") or {}
        k = (plan.get("total") or 0) - (plan.get("done") or 0)
        return f"[Watch] you have been idle {(lead.get('idle_s') or 0) // 60} min with {k} open tasks: continue the queue."
    if kind == "awake_dropped":
        return f"[Watch] the awake hold dropped and I restarted it: {stall.get('fix') or 'failed: not run'}."
    return None


class Watch:
    def __init__(self, now=time.time, run=None, nudge=None, alert=None, state_dir=None):
        """run(argv) -> output, raises on failure (argv starts with "awake"; the caller prefixes tmux-ctl).
        nudge(project, line) queues one line for the lead's pane. alert(event) posts one Discord line (notify.discord_sink)."""
        self.now = now
        self.run = run or (lambda argv: (_ for _ in ()).throw(RuntimeError("no runner")))
        self.nudge = nudge or (lambda project, line: None)
        self.alert = alert or (lambda ev: None)
        self._dir = state_dir
        self.stalls = None   # read from watch.json on the first observe

    @property
    def dir(self):
        """state_dir as given, else tc_env.state_dir() at call time ($TC_STATE_DIR: a test's TC_STATE set after import counts)."""
        return Path(self._dir) if self._dir else tc_env.state_dir()

    @property
    def file(self):
        return self.dir / "watch.json"

    @property
    def heartbeat(self):
        return self.dir / "watch" / "heartbeat"

    def _load(self):
        try:
            d = json.loads(self.file.read_text())
            return {k: v for k, v in (d.get("stalls") or {}).items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save(self):
        try:
            _write_json(self.file, {"stalls": self.stalls})
        except OSError as e:
            print(f"watch: save failed: {e}", file=sys.stderr, flush=True)

    def _alert(self, project, text):
        try:
            self.alert({"project": project, "kind": "watch", "key": "", "title": project, "text": text, "ts": self.now()})
        except Exception as e:   # noqa: BLE001
            print(f"watch: alert failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)

    def observe(self, ov, events):
        """Act on one overview and the notifier's events for it. Returns the actions taken, for tests:
        [("nudge"|"fix"|"alert"|"realert", project, kind, key, text)]."""
        now = self.now()
        if self.stalls is None:
            self.stalls = self._load()
        recs = {p["project"]: p for p in ov.get("projects") or [] if p.get("queue")}
        try:
            _write_json(self.heartbeat, {"at": iso(now), "queue": sorted(recs)})
        except OSError as e:
            print(f"watch: heartbeat failed: {e}", file=sys.stderr, flush=True)
        cur = {_key(c["project"], c["kind"], c["key"]): c for c in notify.conditions(ov)
               if c["project"] in recs and c["kind"] in WATCH_KINDS}
        acts, changed = [], False
        for ev in events or []:
            k = _key(ev.get("project"), ev.get("kind"), ev.get("key"))
            if k in cur and k not in self.stalls:
                self.stalls[k] = {"first_at": now, "nudged_at": None, "fixed_at": None, "realerted_at": None}
                changed = True
                if ev["kind"] == "lead_idle":   # the notifier's lead_idle is card-only (routine tier): post it in queue mode
                    text = f"{ev['text']}"
                    self._alert(ev["project"], text)
                    acts.append(("alert", ev["project"], ev["kind"], ev["key"], text))
        for k in [k for k in self.stalls if k not in cur]:
            del self.stalls[k]
            changed = True
        for k, st in self.stalls.items():
            c = cur[k]
            project, kind, key, rec = c["project"], c["kind"], c["key"], recs[c["project"]]
            if kind == "awake_dropped" and st.get("fixed_at") is None:
                try:
                    self.run(list(AWAKE_ARGV))
                    st["fix"] = "ok"
                except Exception as e:   # noqa: BLE001
                    first = (str(e).strip().splitlines() or [type(e).__name__])[0]
                    st["fix"] = f"failed: {first[:200]}"
                st["fixed_at"] = now
                changed = True
                text = f"awake hold restarted: {st['fix']}"
                self._alert(project, text)
                acts.append(("fix", project, kind, key, text))
            if kind in STALL_KINDS and st.get("nudged_at") is None and _lead_ready(rec):
                line = nudge_line(kind, key, rec, st)
                try:
                    self.nudge(project, line)
                    st["nudged_at"] = now
                    changed = True
                    acts.append(("nudge", project, kind, key, line))
                except Exception as e:   # noqa: BLE001 - try again on the next overview
                    print(f"watch: nudge failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            if kind in STALL_KINDS and st.get("realerted_at") is None and now - st["first_at"] >= REALERT_S:
                text = f"{c['text']} — lead did not react (15 min)"
                self._alert(project, text)
                st["realerted_at"] = now
                changed = True
                acts.append(("realert", project, kind, key, text))
        if changed:
            self._save()
        return acts
```

Notes: the state dir is resolved at call time (`tc_env.state_dir()` unless `state_dir` was given), and `watch.json` is read on the first `observe`, so the module-level `WATCH` the server builds at import (Task 4) follows a test's `TC_STATE`. The alert event has `title = project`, so the feed line (`discord_feed.sink_event` writes `<title>: <text>`) reads `<project>: <text>`.

- [ ] **Step 4: Run the mutations named in the test comments** (each must fail its named test; revert): drop `st.get("nudged_at") is None and`; drop `and _lead_ready(rec)`; drop the `if p.get("queue")` filter when building `recs`; drop the `fixed_at` check; set `STALL_KINDS = WATCH_KINDS`; start with `self.stalls = {}` instead of reading `watch.json`. (Run by the planner on the plan's code: the nudged_at, load and STALL_KINDS mutations each failed their named test.)

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m unittest discover -s board/tests -p 'test_watch.py'`
Expected: `OK` (13 tests).

- [ ] **Step 6: Commit**

```bash
git add board/watch.py board/tests/test_watch.py
git commit -m "feat(board): night watch: one nudge per stall, awake fix, re-alert, heartbeat" -- board/watch.py board/tests/test_watch.py
```
(End the message with the attribution trailer your harness specifies.)

### Task 4: Server calls the watch after the notifier

**Goal:** `board/server.py` runs `WATCH.observe(ov, events)` after `NOTIFIER.observe` on every overview build, with the board's tmux-ctl runner, the `[Board]` line queue as the nudge and the Discord feed as the alert sink.

**Files:**
- Modify: `board/server.py` (import `watch`, `WATCH`, `observe_overview`, `build_overview` passes `limits`, `overview_payload` calls `observe_overview`)
- Test: `board/tests/test_watch_wiring.py` (create)

**Acceptance Criteria:**
- [ ] `observe_overview(ov)` calls the notifier, passes its returned events to `WATCH.observe`, and returns them
- [ ] `TC_WATCH=0` skips the watch; a raising watch is logged and `observe_overview` still returns the events
- [ ] the module-level `WATCH` runs `[TMUX_CTL, "awake", "on", "--queue", "--lid"]` through `run_script` and queues nudges with `COMMENTS.add_line(project, line)`
- [ ] `overview_payload` uses `observe_overview`; `build_overview` passes `limits` to `overview.build`
- [ ] `test_overview_api.py` and `test_discord_wiring.py` still pass

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_watch*.py' && python3 -m unittest discover -s board/tests -p 'test_overview_api.py' && python3 -m unittest discover -s board/tests -p 'test_discord_wiring.py'`

**Blocked by:** Task 3

**modelTier:** standard

**Steps:**

- [ ] **Step 1: Write the failing test** — create `board/tests/test_watch_wiring.py`:

```python
"""server.observe_overview: the notifier, then the night watch on its events; TC_WATCH=0 and a failing watch.
Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §6. TC_STATE is a temp dir; run_script is never called for real."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server_watch", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class Recorder:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def observe(self, ov, events=None):
        self.calls.append((ov, events))
        if self.fail:
            raise RuntimeError("boom")
        return ["ev"]


class ObserveOverviewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        for p in (mock.patch.dict(os.environ, {"TC_STATE": tmp}), mock.patch.object(server, "run_script")):
            p.start(); self.addCleanup(p.stop)
        self.n, self.w = Recorder(), Recorder()
        for p in (mock.patch.object(server, "NOTIFIER", self.n), mock.patch.object(server, "WATCH", self.w)):
            p.start(); self.addCleanup(p.stop)

    def test_watch_gets_the_notifiers_events(self):
        ov = {"generated": 1, "projects": []}
        self.assertEqual(server.observe_overview(ov), ["ev"])
        self.assertEqual(self.w.calls, [(ov, ["ev"])])   # mutation: call WATCH.observe(ov, []) -> this fails

    def test_tc_watch_0_turns_the_watch_off(self):
        with mock.patch.dict(os.environ, {"TC_WATCH": "0"}):
            server.observe_overview({"generated": 1, "projects": []})
        self.assertEqual((len(self.n.calls), self.w.calls), (1, []))

    def test_a_failing_watch_never_breaks_the_overview(self):
        server.WATCH.fail = True
        self.assertEqual(server.observe_overview({"generated": 1, "projects": []}), ["ev"])



class RealWatchWiringTest(unittest.TestCase):
    """The module-level WATCH: its runner prefixes tmux-ctl, its nudge queues a line for the lead (COMMENTS, the [Board] path)."""
    def test_runner_and_nudge(self):
        with mock.patch.object(server, "run_script", return_value="awake: on") as rs:
            server.WATCH.run(["awake", "on", "--queue", "--lid"])
        self.assertEqual(rs.call_args.args[0], [server.TMUX_CTL, "awake", "on", "--queue", "--lid"])
        server.WATCH.nudge("proj-w", "[Watch] teammate fake window is gone (task #7 in progress): respawn it.")
        self.addCleanup(server.COMMENTS._items.pop, "proj-w", None)
        self.assertEqual([c["text"] for c in server.COMMENTS.pending("proj-w")],
                         ["[Watch] teammate fake window is gone (task #7 in progress): respawn it."])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s board/tests -p 'test_watch_wiring.py'`
Expected: errors — `server` has no attribute `WATCH` / `observe_overview`.

- [ ] **Step 3: Implement** — make exactly these edits to `board/server.py` (a diff against `main` at the plan's base):

```diff
--- a/board/server.py
+++ b/board/server.py
@@ -32,7 +32,7 @@
 import tc_env  # noqa: E402
 from paneclass import SHELLS, VERSION_RE, WAITING_RE, WORKING_RE, classify, input_has_text, is_claude_cmd, mod_records, mod_states, tmux_cmd  # noqa: E402,F401
 TMUX = tmux_cmd()   # which tmux server the board shows: bin/_tc_bins.zsh decides (tmux-dash passes TMUX_DASH_TMUX_ARGS)
-import activity, artifacts, dirs, discord_controls, discord_dialogs, discord_digest, discord_feed, engine_lines, discord_ideas, discord_merge, discord_ops, gitlab_sync, ideas, notify, overview, planview, relay, restore, usage, worktree_safety  # noqa: E402
+import activity, artifacts, dirs, discord_controls, discord_dialogs, discord_digest, discord_feed, engine_lines, discord_ideas, discord_merge, discord_ops, gitlab_sync, ideas, notify, overview, planview, relay, restore, usage, watch, worktree_safety  # noqa: E402
 from worktree_safety import claude_lock_owner  # noqa: E402,F401
 discord_controls.BIN = BIN   # the controls step runs bin/tmux-ctl (discord_controls.py)
 from urllib.parse import parse_qs, urlsplit  # noqa: E402
@@ -226,6 +226,9 @@
 ENGINE_LINE_STATE = {}   # project -> engine_lines in-flight state (memory only: the cursor file is the durable part)
 INDEXER = None   # usage.Indexer, set only when run as a script (see __main__)
 NOTIFIER = notify.Notifier()   # TC_NOTIFY=0 turns banners and the events list off
+WATCH = watch.Watch(run=lambda argv: run_script([TMUX_CTL, *argv], timeout=30),   # the night watch; TC_WATCH=0 turns it off
+                    nudge=lambda project, line: COMMENTS.add_line(project, line),
+                    alert=None if os.environ.get("TC_DISCORD_ALERTS") == "0" else notify.discord_sink)
 OVERSEER_SESSION = "overseer"   # the read-only overseer's tmux session: never a project card
 TERMINAL_SESSION = os.environ.get("TC_TERMINAL_SESSION", "main")   # the session new terminals attach to: no card unless Claude runs in it; "" shows it always
 OVERVIEW_EVERY = 10   # seconds between overview builds (the notifier thread) and the cache life of /api/overview
@@ -656,8 +659,23 @@
     st = state()
     live = INDEXER.snapshot() if INDEXER else []
     th, _ = usage.thresholds()
+    try:
+        limits = usage.plan_limits(usage.tap_entries(now, 10 ** 9))
+    except Exception:   # noqa: BLE001 - no tap: no weekly pace
+        limits = None
     return overview.build(st["sessions"], live, now, home=HOME / ".claude", state_dir=tc_env.state_dir(), tmux=tmux, th=th,
-                          spend=lambda repo: spend_today(repo, now), activity=window_activity(), mods=mod_records(now))
+                          spend=lambda repo: spend_today(repo, now), activity=window_activity(), mods=mod_records(now), limits=limits)
+
+
+def observe_overview(ov):
+    """The notifier, then the night watch on its events. A failing watch is logged and never breaks the overview."""
+    events = NOTIFIER.observe(ov)
+    if os.environ.get("TC_WATCH") != "0":
+        try:
+            WATCH.observe(ov, events)
+        except Exception as e:   # noqa: BLE001
+            print(f"tmux-dash: watch failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
+    return events
 
 
 def overview_payload():
@@ -666,7 +684,7 @@
         if _overview_cache["value"] is not None and time.monotonic() - _overview_cache["at"] < OVERVIEW_EVERY:
             return _overview_cache["value"]
         ov = build_overview()
-        NOTIFIER.observe(ov)
+        observe_overview(ov)
         value = {**ov, "events": NOTIFIER.recent(), "overseer": overseer_info()}
         _overview_cache.update(at=time.monotonic(), value=value)
     ensure_overseer()   # once per fresh build, outside the lock: its run_script can take up to 20 s and must not stall /api/overview
```

Differences from the notifier wiring this copies: the watch gets the notifier's *returned events* (not `NOTIFIER.recent()`), is wrapped so a failure is logged and never breaks `/api/overview`, and has its own switch `TC_WATCH=0`. `build_overview` now passes `limits` (the same `usage.plan_limits(usage.tap_entries(now, 10 ** 9))` call `feed_tick` already makes) so `pace` is filled.

- [ ] **Step 4: Run the mutation named in the test** — call `WATCH.observe(ov, [])` in `observe_overview`: `test_watch_gets_the_notifiers_events` must fail; revert.

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m unittest discover -s board/tests -p 'test_watch*.py' && python3 -m unittest discover -s board/tests -p 'test_overview_api.py' && python3 -m unittest discover -s board/tests -p 'test_discord_wiring.py'`
Expected: `OK` for each (the overview API and Discord wiring tests set `TC_STATE` to a temp dir, so the real watch writes only there).

- [ ] **Step 6: Commit**

```bash
git add board/server.py board/tests/test_watch_wiring.py
git commit -m "feat(board): run the night watch after the notifier on every overview" -- board/server.py board/tests/test_watch_wiring.py
```
(End the message with the attribution trailer your harness specifies.)

### Task 5: Night watch e2e on a scratch tmux server

**Goal:** One zsh e2e proves the chain on a real (scratch) tmux server: a killed `✦ fake` teammate gives a `teammate_gone` Discord feed line, one `[Watch]` line typed into the lead pane, and the re-alert 15 min later; plus a read-only check against the user's real task lists and a leak check.

**Files:**
- Create: `tools/tests/test_night_watch_e2e.zsh`

**Acceptance Criteria:**
- [ ] the scratch server starts with `-f /dev/null` (via `tools/tests/lib.zsh` `tt_setup`), `TC_STATE` is the test's temp dir
- [ ] after the teammate pane is killed: exactly one `teammate_gone` event, a `critical` feed line containing `teammate fake window is gone (task #2 in progress)`
- [ ] the lead pane shows `[Watch] teammate fake window is gone (task #2 in progress): respawn it.` exactly once
- [ ] with the clock moved 15 min the feed holds exactly one `… — lead did not react (15 min)` line; no awake fix ran; the heartbeat lists the project
- [ ] real state (read-only): `queue_mode` agrees with an independent count over every list in `~/.claude/tasks` (prints the count checked; skip only where the folder is absent)
- [ ] no real watch file (`${TMPDIR}/tmux-ctl-<uid>/watch*`, `~/.local/state/agent-board/watch*`) names the test project before or after; the check prints how many files it read

**Verify:** `env -u AGENT_BOARD_LEAD zsh tools/tests/test_night_watch_e2e.zsh`

**Blocked by:** Task 4

**modelTier:** standard

**Steps:**

- [ ] **Step 1: Create the e2e test** `tools/tests/test_night_watch_e2e.zsh` (picked up by `run-all.zsh` and `all.zsh` as a `test_*.zsh`):

```zsh
#!/usr/bin/env zsh
# test_night_watch_e2e.zsh — the night watch end to end on a scratch tmux server (lib.zsh, -f /dev/null): a stand-in lead
# (a binary named claude at its prompt: an agent-status file says ready) and a `✦ fake` teammate window owning task #2 of a
# temp task list that also holds a pending `Plan & run:` task with queue metadata. The board's own build_overview and
# observe_overview run in-process with a clock seam; the teammate pane is killed; the Discord feed line, the [Watch] line
# typed into the lead pane, and (clock moved 15 min) the re-alert are checked. Plus a read-only check of the real task
# lists (queue_mode against an independent count) and a leak check of the real watch files.
# Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §7.
R="${${(%):-%x}:A:h:h:h}"
source "$R/tools/tests/lib.zsh"
REAL_TC="${TMPDIR:-/tmp}"; REAL_TC="${REAL_TC%/}/tmux-ctl-$(id -u)"
REAL_AB="$HOME/.local/state/agent-board"
# leak check: after the live board runs this code it rewrites the real watch files every overview, so compare content, not
# mtimes: no real watch file may name this test's project (e2e-nw). Prints how many real files it read.
leak() { local f n=0 hit=0; for f in "$REAL_TC"/watch*(N) "$REAL_TC"/watch/*(N) "$REAL_AB"/watch*(N); do [[ -f $f ]] || continue; (( n++ )); grep -qF e2e-nw "$f" && (( hit++ )); done
  print -r -- "leak check: read $n real watch files, $hit name e2e-nw"; (( hit == 0 )) }
check "no real watch file names e2e-nw before the run" leak
REAL_HOME="$HOME"
tt_setup claude
E="$TT_DIR/e2e"; mkdir -p "$E/home/.claude/sessions" "$E/fake" "$TC_STATE/discord/e2e-nw" "$TC_STATE/agent-status"
print -r -- '{"channel": "C1"}' > "$TC_STATE/discord/e2e-nw/bridge.json"
printf '#include <unistd.h>\nint main(void){sleep(900);return 0;}\n' > "$E/c.c"
cc -o "$E/fake/claude" "$E/c.c" || { print "FAIL - cc"; exit 1 }   # pane_current_command must read `claude` (a symlink reads as its target)
tt new-session -d -s e2e-nw -n claude -c "$E" "$E/fake/claude"
tt new-window -d -t '=e2e-nw:' -n '✦ fake' -c "$E" "$E/fake/claude"
LEAD="$(tt display -p -t '=e2e-nw:claude' '#{window_id}.#{pane_id}')"
SID=e2e0aaaa-0000-4000-8000-000000000001
print -r -- "{\"sessionId\": \"$SID\", \"tmux\": \"$LEAD\", \"updatedAt\": 1, \"pid\": 0, \"startedAt\": 0}" > "$E/home/.claude/sessions/1.json"
T="$E/home/.claude/tasks/session-${SID[1,8]}"; mkdir -p "$T"
print -r -- '{"id": "1", "subject": "Plan & run: docs/superpowers/specs/x.md", "status": "pending", "blockedBy": [], "metadata": {"queue": {"integration": "merge", "push": false, "answeredAt": "2026-11-24T00:00:00Z"}}}' > "$T/1.json"
print -r -- '{"id": "2", "subject": "Task 2: x", "status": "in_progress", "owner": "fake", "blockedBy": []}' > "$T/2.json"
print -r -- '{"id": "3", "subject": "Task 3: y", "status": "pending", "blockedBy": ["2"]}' > "$T/3.json"
cat > "$E/drive.py" <<'EOP'
import json, os, sys, time
board, lead_pane = sys.argv[1], sys.argv[2]
sys.path.insert(0, board)
import server, watch, notify, tc_env  # noqa: E402
clock = [time.time()]
runs = []
def fresh_status():   # the lead at its prompt, per agent-status (the mod the board prefers over pane text)
    t = time.time()
    (tc_env.state_dir() / "agent-status" / "lead.json").write_text(json.dumps(
        {"pane": lead_pane, "state": "ready", "since": t - 60, "updatedAt": t}))
(tc_env.state_dir() / "awake.json").write_text(json.dumps({"caffeinatePid": os.getpid(), "queue": True}))   # a live hold: only the teammate stalls
server.NOTIFIER = notify.Notifier(runner=lambda a: None, enabled=False, now=lambda: clock[0])   # default sinks: the discord feed
server.WATCH = watch.Watch(now=lambda: clock[0], run=lambda argv: runs.append(argv) or "ok",
                           nudge=lambda p, line: server.COMMENTS.add_line(p, line), alert=notify.discord_sink)
def step():
    fresh_status()
    server._state_cache["value"] = None
    ov = server.build_overview(clock[0])
    return ov, server.observe_overview(ov)
ov, _ = step()
p = next(x for x in ov["projects"] if x["project"] == "e2e-nw")
print("seed", json.dumps({"queue": p["queue"], "owned": p["owned"], "awake": p["awake"]}))
server.tmux("kill-pane", "-t", "=e2e-nw:✦ fake")
clock[0] += 30
ov, ev = step()
print("events", " ".join(e["kind"] for e in ev))
clock[0] += 30
step(); time.sleep(1)   # this build delivers the queued line into the lead pane
clock[0] += watch.REALERT_S
step()
print("runs", len(runs))
EOP
export TMUX_DASH_TOKEN=e2e TMUX_DASH_TMUX_ARGS="-L $TT_SOCK_NAME" TC_DISCORD_ALERTS=1
OUT="$(HOME="$E/home" python3 -B "$E/drive.py" "$R/board" "$(tt display -p -t '=e2e-nw:claude' '#{pane_id}')" 2>"$E/drive.err")"
print -r -- "$OUT"
check "seed: queue mode on, teammate window present, hold live" grep -qF 'seed {"queue": true, "owned": [{"owner": "fake", "task": "2", "window": true, "dead": false, "ready_s": null}], "awake": true}' <<< "$OUT"
check "kill: one teammate_gone event" grep -qx 'events teammate_gone' <<< "$OUT"
FEED="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import tc_env; print(tc_env.feed_path("e2e-nw"))' "$R/board")"
check "discord feed: the teammate_gone alert, critical" python3 -c '
import json, sys
ls = [json.loads(l) for l in open(sys.argv[1])]
sys.exit(0 if any(l["kind"] == "teammate_gone" and l["tier"] == "critical" and "teammate fake window is gone (task #2 in progress)" in l["text"] for l in ls) else 1)' "$FEED"
check "lead pane: the [Watch] line was typed" tt_wait 5 zsh -c 'tmux_bin="$1"; shift; "$tmux_bin" -L "$1" capture-pane -p -J -t "=e2e-nw:claude" | grep -qF "[Watch] teammate fake window is gone (task #2 in progress): respawn it."' _ "$TT_BIN" "$TT_SOCK_NAME"
check "lead pane: typed once" test "$(tt capture-pane -p -J -t '=e2e-nw:claude' | grep -cF '[Watch] teammate fake window is gone')" -eq 1
check "discord feed: one re-alert after 15 min" test "$(grep -cF 'teammate fake window is gone (task #2 in progress) — lead did not react (15 min)' "$FEED")" -eq 1
check "no awake fix ran (the hold was live)" grep -qx 'runs 0' <<< "$OUT"
check "heartbeat lists e2e-nw" python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))["queue"] == ["e2e-nw"] else 1)' "$TC_STATE/watch/heartbeat"
[[ -s "$E/drive.err" ]] && { print -r -- "--- driver stderr:"; cat "$E/drive.err" }

# read-only, real state (skipped where there is no ~/.claude/tasks, e.g. CI): queue_mode over every real task list agrees with an independent count of open Plan & run tasks with queue metadata
check "real task lists: queue_mode agrees with the raw files" python3 -B -c '
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1]); import overview, planview
root = Path(sys.argv[2]) / ".claude" / "tasks"
if not root.is_dir():   # a CI runner has no real task lists: say so, never a silent pass on mac
    print(f"skip: no {root}"); sys.exit(0)
n = on = bad = 0
for d in sorted(p for p in root.glob("*") if p.is_dir()):
    raw = []
    for f in d.glob("*.json"):
        try: raw.append(json.loads(f.read_text()))
        except (OSError, ValueError): pass
    raw = [t for t in raw if isinstance(t, dict)]
    want = any(str(t.get("subject", "")).startswith("Plan & run:") and t.get("status") in ("pending", "in_progress")
               and isinstance(t.get("metadata"), dict) and "queue" in t["metadata"] for t in raw)
    got = overview.queue_mode({"active": True, "tasks": planview._finish([planview._norm(t) for t in raw])})
    n += 1; on += got; bad += got != want
print(f"checked {n} real task lists, {on} in queue mode, {bad} disagree")
sys.exit(0 if n > 0 and bad == 0 else 1)' "$R/board" "$REAL_HOME"
check "no leak into the real watch files" leak
tt_done
```

How it works, for a reader of a failure: the lead is a compiled binary named `claude` (a symlink to `sleep` shows as `sleep` in `#{pane_current_command}`, checked by the planner), so `paneclass.classify` sees a claude pane, and a fresh agent-status file says it is `ready`. The driver runs the board's own `build_overview` and `observe_overview` in-process against the scratch server (`TMUX_DASH_TMUX_ARGS=-L <sock>`), with `HOME` set to the scratch home (planview reads `~/.claude/sessions` and `tasks`), a live `awake.json` (the driver's own pid) so only the teammate stalls, and a clock seam moved 15 min for the re-alert. The `[Watch]` line is queued by the watch's overview and typed by the next build (`deliver_comments`). The real-state check is read-only: it runs `queue_mode` over every real list in `~/.claude/tasks` and compares with an independent count from the raw files (skipped, with a `skip:` line, where the folder does not exist, e.g. CI). The leak check reads the real watch files' contents, not their mtimes: once the live board runs this code it rewrites them every overview.

- [ ] **Step 2: Run it**

Run: `env -u AGENT_BOARD_LEAD zsh tools/tests/test_night_watch_e2e.zsh`
Expected: every line `ok   - …` and a final `ALL PASS` (the planner's run of this exact script on the plan's code: 11 checks passed, `checked 295 real task lists, 99 in queue mode, 0 disagree`, `leak check: read 0 real watch files, 0 name e2e-nw`).

- [ ] **Step 3: Mutation** — comment out `self.nudge(project, line)` in `board/watch.py`: the `lead pane: the [Watch] line was typed` check must FAIL. Revert, and run Step 2 again.

- [ ] **Step 4: Commit**

```bash
git add tools/tests/test_night_watch_e2e.zsh
git commit -m "test(board): night watch end to end on a scratch tmux server" -- tools/tests/test_night_watch_e2e.zsh
```
(End the message with the attribution trailer your harness specifies.)

### Task 6: Discord bridge board-down check

**Goal:** Each project's Discord bridge reads `$TC_STATE_DIR/watch/heartbeat` every minute and, while its project was in queue mode in the last heartbeat read, posts once `⚠️ <project>: board down, night watch off (last heartbeat <at>)` when it is more than 5 min old and once `<project>: board back, night watch on` when it is fresh again.

**Files:**
- Create: `tools/discord-bridge/lib/watch.js`
- Modify: `tools/discord-bridge/bridge.js` (require, `heartbeat` option, `watchTick`, interval in `main`)
- Test: `tools/discord-bridge/test/watch.test.js` (create)

**Acceptance Criteria:**
- [ ] a heartbeat exactly 5 min old posts nothing; older than 5 min while armed posts one down post (user mentioned) in the home channel; repeated stale ticks post nothing more
- [ ] a fresh heartbeat after a down post gives exactly one `<project>: board back, night watch on`
- [ ] a project not in the last heartbeat's `queue` gets nothing however old the heartbeat; the ops bridge never checks
- [ ] a restarted bridge (same dir) does not repeat the down post: state in `<dir>/watch-state.json`
- [ ] `stateDir` follows `TC_STATE`, else `${TMPDIR:-/tmp}/tmux-ctl-<uid>` (same rule as `board/tc_env.py`)
- [ ] the whole bridge suite (`npm test`) passes

**Verify:** `cd tools/discord-bridge && { [ -d node_modules ] || npm ci; } && npm test`

**modelTier:** standard

**Steps:**

- [ ] **Step 0: Dependencies** — a fresh worktree has no `tools/discord-bridge/node_modules`: run `cd tools/discord-bridge && npm ci` once. Run the bridge tests with `npm test` (a bare `node --test test/` fails with `not ok 1`).

- [ ] **Step 1: Write the failing test** — create `tools/discord-bridge/test/watch.test.js`:

```js
'use strict';
// Night watch, board down (spec docs/superpowers/specs/2026-11-23-night-watch-design.md §5): lib/watch.js and the
// bridge's watchTick on a fake client. Every heartbeat lives in a temp dir; nothing reads the real state dir.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const watch = require('../lib/watch');
const { createBridge } = require('../bridge');
const { FakeClient } = require('./fake-client');

const T0 = Date.parse('2026-11-24T01:00:00Z');
const MIN = 60 * 1000;

function setup({ project = 'proj' } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dbw-'));
  const dir = path.join(root, 'discord', project);
  fs.mkdirSync(path.join(dir, 'outbox'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'bridge.json'), JSON.stringify({ channel: 'C1', user: 'U1' }));
  fs.writeFileSync(path.join(dir, '.env'), 'DISCORD_BOT_TOKEN=TESTTOKEN.abc.SECRET\n');
  const hbFile = path.join(root, 'state', 'watch', 'heartbeat');
  fs.mkdirSync(path.dirname(hbFile), { recursive: true });
  const client = new FakeClient({ guildId: 'G1' });
  const clock = { t: T0 };
  const bridge = createBridge({ dir, client, log: () => {}, now: () => clock.t, sleep: async () => {}, heartbeat: hbFile });
  const beat = (atMs, queue) => fs.writeFileSync(hbFile, JSON.stringify({ at: new Date(atMs).toISOString().replace(/\.\d{3}Z$/, 'Z'), queue }));
  const sent = () => client.callsOf('send').map((c) => c.payload.content);
  return { dir, client, clock, bridge, beat, sent, hbFile };
}

test('decide: stale heartbeat while armed posts down once, fresh again posts back once', () => {
  const hb = (atMs, queue) => ({ at: atMs, atText: new Date(atMs).toISOString(), queue });
  let r = watch.decide(null, hb(T0, ['proj']), 'proj', T0 + MIN);
  assert.strictEqual(r.text, null);
  // mutation: compare with >= STALE_MS instead of > -> the 5-minute case posts, this fails
  r = watch.decide(r.next, hb(T0, ['proj']), 'proj', T0 + watch.STALE_MS);
  assert.strictEqual(r.text, null);
  r = watch.decide(r.next, hb(T0, ['proj']), 'proj', T0 + watch.STALE_MS + 1);
  assert.match(r.text, /^⚠️ proj: board down, night watch off \(last heartbeat 2026-11-24T01:00:00.000Z\)$/);
  // mutation: drop the !st.down check -> a second down post, this fails
  r = watch.decide(r.next, hb(T0, ['proj']), 'proj', T0 + 20 * MIN);
  assert.strictEqual(r.text, null);
  r = watch.decide(r.next, hb(T0 + 21 * MIN, ['proj']), 'proj', T0 + 21 * MIN);
  assert.strictEqual(r.text, 'proj: board back, night watch on');
  r = watch.decide(r.next, hb(T0 + 22 * MIN, ['proj']), 'proj', T0 + 22 * MIN);
  assert.strictEqual(r.text, null);
});

test('decide: a project not in queue mode in the last heartbeat gets nothing', () => {
  // mutation: drop the st.armed check -> a down post, this fails
  const r = watch.decide(null, { at: T0, atText: 'x', queue: ['other'] }, 'proj', T0 + 60 * MIN);
  assert.strictEqual(r.text, null);
});

test('decide: a heartbeat file that disappears after one was read counts as stale', () => {
  let r = watch.decide(null, { at: T0, atText: '2026-11-24T01:00:00Z', queue: ['proj'] }, 'proj', T0);
  r = watch.decide(r.next, null, 'proj', T0 + 10 * MIN);
  assert.match(r.text, /board down, night watch off \(last heartbeat 2026-11-24T01:00:00Z\)/);
});

test('stateDir follows TC_STATE, else TMPDIR/tmux-ctl-<uid>', () => {
  assert.strictEqual(watch.stateDir({ TC_STATE: '/x/s' }), '/x/s');
  assert.strictEqual(watch.stateDir({ TMPDIR: '/var/t/' }), `/var/t/tmux-ctl-${os.userInfo().uid}`);
  assert.strictEqual(watch.heartbeatFile({ TC_STATE: '/x/s' }), '/x/s/watch/heartbeat');
});

test('watchTick: stale heartbeat in queue mode -> one down post in the home channel; fresh -> one back post', async () => {
  const s = setup();
  s.beat(T0, ['proj']);
  assert.strictEqual(await s.bridge.watchTick(), null);
  s.clock.t = T0 + 6 * MIN;
  await s.bridge.watchTick();
  s.clock.t = T0 + 7 * MIN;
  await s.bridge.watchTick();
  assert.deepStrictEqual(s.sent(), ['<@U1> ⚠️ proj: board down, night watch off (last heartbeat 2026-11-24T01:00:00Z)']);
  assert.strictEqual(s.client.callsOf('send')[0].target, 'C1');
  s.beat(s.clock.t, ['proj']);
  await s.bridge.watchTick();
  await s.bridge.watchTick();
  assert.deepStrictEqual(s.sent().slice(1), ['proj: board back, night watch on']);
});

test('watchTick: queue mode off -> nothing, however old the heartbeat', async () => {
  const s = setup();
  s.beat(T0, []);
  s.clock.t = T0 + 60 * MIN;
  await s.bridge.watchTick();
  assert.deepStrictEqual(s.sent(), []);
});

test('watchTick: a restarted bridge does not repeat the down post', async () => {
  const s = setup();
  s.beat(T0, ['proj']);
  await s.bridge.watchTick();
  s.clock.t = T0 + 6 * MIN;
  await s.bridge.watchTick();
  // mutation: keep the state in memory only -> the second bridge posts again, this fails
  const again = createBridge({ dir: s.dir, client: s.client, log: () => {}, now: () => s.clock.t, sleep: async () => {}, heartbeat: s.hbFile });
  await again.watchTick();
  assert.strictEqual(s.sent().length, 1);
});

test('watchTick: an ops bridge never checks', async () => {
  const s = setup();
  const ops = createBridge({ dir: s.dir, client: s.client, ops: true, log: () => {}, now: () => T0 + 60 * MIN, heartbeat: s.hbFile });
  s.beat(T0, ['proj']);
  assert.strictEqual(await ops.watchTick(), null);
  assert.deepStrictEqual(s.sent(), []);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tools/discord-bridge && node --test test/watch.test.js`
Expected: `Cannot find module '../lib/watch'`.

- [ ] **Step 3: Implement** — create `tools/discord-bridge/lib/watch.js`:

```js
'use strict';
// Night watch, board side down: the board writes <state>/watch/heartbeat {"at": ISO, "queue": [projects]} on every
// overview (board/watch.py). While this bridge's project was in queue mode in the last heartbeat read, a heartbeat older
// than STALE_MS gets one "board down" post, and the next fresh one one "board back" post.
// Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §5.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const STALE_MS = 5 * 60 * 1000;
const CHECK_MS = 60 * 1000;

// Same rule as board/tc_env.py state_dir() and tc_state_dir in tools/lib/tc-env.zsh.
function stateDir(env = process.env) {
  if (env.TC_STATE) return env.TC_STATE;
  return `${String(env.TMPDIR || '/tmp').replace(/\/+$/, '')}/tmux-ctl-${os.userInfo().uid}`;
}

const heartbeatFile = (env = process.env) => path.join(stateDir(env), 'watch', 'heartbeat');

function readHeartbeat(file) {
  try {
    const hb = JSON.parse(fs.readFileSync(file, 'utf8'));
    const at = Date.parse(hb?.at);
    if (!Number.isFinite(at)) return null;
    return { at, atText: String(hb.at), queue: Array.isArray(hb.queue) ? hb.queue.map(String) : [] };
  } catch { return null; }
}

// decide(prev, hb, project, nowMs) -> { next, text }. prev/next: { armed, down, last }.
// armed: the project was in queue mode in the last heartbeat read; down: the down post was made; last: that heartbeat's at text.
// A missing or unreadable file reads as "no new heartbeat": stale once armed.
function decide(prev, hb, project, nowMs) {
  const st = { armed: false, down: false, last: null, ...(prev || {}) };
  if (hb) { st.armed = hb.queue.includes(project); st.last = hb.atText; }
  const fresh = hb && nowMs - hb.at <= STALE_MS;
  if (fresh && st.down) return { next: { ...st, down: false }, text: `${project}: board back, night watch on` };
  if (!fresh && st.armed && !st.down) {
    return { next: { ...st, down: true }, text: `⚠️ ${project}: board down, night watch off (last heartbeat ${st.last || 'unknown'})` };
  }
  return { next: st, text: null };
}

module.exports = { STALE_MS, CHECK_MS, stateDir, heartbeatFile, readHeartbeat, decide };
```

and wire it into `tools/discord-bridge/bridge.js` (a diff against `main` at the plan's base): a `heartbeat` option on `createBridge` (default `watch.heartbeatFile()`), a `watchTick()` that is a no-op for the ops bridge, posts through the home channel with the existing `withRetry`, and keeps `<dir>/watch-state.json` (written `.tmp` + rename), and a second interval in `main()`:

```diff
--- a/tools/discord-bridge/bridge.js
+++ b/tools/discord-bridge/bridge.js
@@ -7,6 +7,7 @@
 const outbox = require('./lib/outbox');
 const stateLib = require('./lib/state');
 const commands = require('./lib/commands');
+const watch = require('./lib/watch');
 
 const CARD_MIN_MS = 30000;
 const BACKOFF_START = 1000;
@@ -48,7 +49,7 @@
   return /socket hang up|fetch failed|network|timed? ?out/i.test(String(e?.message));
 }
 
-function createBridge({ dir, client, ops = false, log = () => {}, now = Date.now, sleep = (ms) => new Promise((r) => setTimeout(r, ms)) }) {
+function createBridge({ dir, client, ops = false, log = () => {}, now = Date.now, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), heartbeat = watch.heartbeatFile() }) {
   const token = readToken(dir);
   let st = stateLib.read(dir);
   let pendingCard = null; // {text} held back by the 30 s throttle
@@ -426,6 +427,24 @@
         }
       }
     } finally { busy = false; }
+  }
+
+  // Night watch (spec 2026-11-23-night-watch-design.md §5): project mode only, called every watch.CHECK_MS by main().
+  // State in <dir>/watch-state.json, so a bridge restart neither repeats a down post nor forgets one.
+  async function watchTick() {
+    if (ops || closed) return null;
+    const file = path.join(dir, 'watch-state.json');
+    const { next, text } = watch.decide(readJson(file, null), watch.readHeartbeat(heartbeat), path.basename(dir), now());
+    if (text) {
+      const c = cfg();
+      const down = text.startsWith('⚠️');
+      const content = down && c.user ? `<@${c.user}> ${text}` : text;
+      await withRetry(async () => (await home()).send({ content, allowedMentions: down && c.user ? { users: [String(c.user)] } : { parse: [] } }));
+      say(`watch ${snip(text)}`);
+    }
+    fs.writeFileSync(`${file}.tmp`, JSON.stringify(next));
+    fs.renameSync(`${file}.tmp`, file);
+    return text;
   }
 
   // Slash commands: once per connection, in the guild of the home channel. Failure is logged only.
@@ -685,7 +704,7 @@
   function close() { closed = true; }
 
   const ctx = { dir, ops, homeChannel: () => (ops ? null : cfg().channel), opsAllow, views, allowFrom, writeEvent, now, say, snip, answer, fence, keep, NO_MENTIONS };
-  return { ctx, tick, onInteraction, onReaction, onMessage, onReady, onDisconnect, attach, close, TICK_MS };
+  return { ctx, tick, watchTick, onInteraction, onReaction, onMessage, onReady, onDisconnect, attach, close, TICK_MS };
 }
 
 function main() {
@@ -716,6 +735,7 @@
   bridge = createBridge({ dir, client, ops: process.argv.includes('--ops'), log });
   bridge.attach();
   timer = setInterval(() => { bridge.tick().catch((e) => log(`tick error: ${scrub(e?.message)}`)); }, TICK_MS);
+  setInterval(() => { bridge.watchTick().catch((e) => log(`watch error: ${scrub(e?.message)}`)); }, watch.CHECK_MS);
   client.login(token).catch((e) => { log(`login failed: ${scrub(e?.message)}`); process.exit(1); });
 }
```

Delivery semantics (the heartbeat is the only input, read once a minute): two ticks cannot run the same transition twice because each tick writes `down` before the next reads it (one process, one interval; `watchTick` is awaited before its state is written); an out-of-order or repeated read of the same heartbeat changes nothing (the decision depends only on the file's `at` and the stored `down`); a restarted bridge reads `watch-state.json` and does not repeat a down post (tested).

- [ ] **Step 4: Run the mutations named in the test comments** (each must fail its named test; revert): `>=` instead of `>` for `STALE_MS`; drop `!st.down`; drop `st.armed`; keep the state in memory instead of `watch-state.json`.

- [ ] **Step 5: Run the whole bridge suite**

Run: `cd tools/discord-bridge && { [ -d node_modules ] || npm ci; } && npm test`
Expected: `# fail 0` (the planner's run on the plan's code: `# pass 206`, `# fail 0`).

- [ ] **Step 6: Commit**

```bash
git add tools/discord-bridge/lib/watch.js tools/discord-bridge/bridge.js tools/discord-bridge/test/watch.test.js
git commit -m "feat(discord-bridge): board down / back posts from the night watch heartbeat" -- tools/discord-bridge/lib/watch.js tools/discord-bridge/bridge.js tools/discord-bridge/test/watch.test.js
```
(End the message with the attribution trailer your harness specifies.)

### Task 7: Lead rule and architecture doc

**Goal:** The lead knows a `[Watch]` line comes from the board's night watch and what to do with each one, and `docs/ARCHITECTURE.md` describes the night watch and its state files.

**Files:**
- Modify: `claude/orchestrator.md` (one bullet after the `[Board] Please shut down teammate` bullet)
- Modify: `tools/tests/test_plugin.zsh` (one check)
- Modify: `docs/ARCHITECTURE.md` (a `## Night watch` section, three State files rows)

**Acceptance Criteria:**
- [ ] `claude/orchestrator.md` has the `[Watch]` bullet, saying the line is not from the user, is not replied to, and what to do per line kind
- [ ] `tools/tests/test_plugin.zsh` checks that bullet; `test_plugin.zsh` and `test_queue_ask_rule.zsh` print ALL PASS
- [ ] `docs/ARCHITECTURE.md` has exactly one `## Night watch` section and State files rows for `watch.json`, `watch/heartbeat` and the bridge's `watch-state.json`

**Verify:** `env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_queue_ask_rule.zsh && test "$(grep -c '^## Night watch$' docs/ARCHITECTURE.md)" -eq 1 && grep -qF '| `watch/heartbeat` |' docs/ARCHITECTURE.md && grep -qF 'watch-state.json' docs/ARCHITECTURE.md`

**modelTier:** mechanical

**Steps:**

- [ ] **Step 1: Add the failing check** — in `tools/tests/test_plugin.zsh`, replace

```zsh
check "lead rules: Queue mode bullet" grep -qF -- '- **Queue mode.**' "$O"
```

with

```zsh
check "lead rules: Queue mode bullet" grep -qF -- '- **Queue mode.**' "$O"
check "lead rules: [Watch] lines come from the night watch, not the user" grep -qF -- '- A line starting `[Watch]` is the night watch of the Agent Board (queue mode only), not the user' "$O"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh | grep -F '[Watch]'`
Expected: `FAIL - lead rules: [Watch] lines come from the night watch, not the user`.

- [ ] **Step 3: The lead rule** — in `claude/orchestrator.md` (section "Controlling other agents in the project"), replace

```markdown
  teammate a `shutdown_request` (same `reason` note as above), run `tmux-ctl wait-gone <name>`, and confirm in one line.
```

with

```markdown
  teammate a `shutdown_request` (same `reason` note as above), run `tmux-ctl wait-gone <name>`, and confirm in one line.
- A line starting `[Watch]` is the night watch of the Agent Board (queue mode only), not the user: act on it and do not
  reply to it. `teammate <name> window is gone`: replace that teammate as "Replacing a stalled teammate" (Rules) says;
  `teammate <name> has been idle`: read its report, then nudge it with SendMessage if the task is not done;
  `you have been idle`: continue the queue; `the awake hold dropped`: nothing to do when it ends `ok`, else put the
  line in the morning report.
```

This is a bullet of that section, not a Queue mode step, so the one-line-per-step rule of `test_plugin.zsh` / `test_queue_ask_rule.zsh` is not affected; it does not repeat the literal `tmux-ctl awake on --queue --lid` (test_plugin pins its count at 3).

- [ ] **Step 4: The architecture doc** — in `docs/ARCHITECTURE.md` insert this section right before the line `## Handoff relay`:

````markdown
## Night watch

While a queue runs (queue mode: the lead's live task list holds an open `Plan & run:` task whose metadata has `queue`), the board watches for a stalled queue (`docs/superpowers/specs/2026-11-23-night-watch-design.md`). No LLM and no process of its own: it runs on every overview build.

- **Conditions.** `board/overview.py` adds `queue`, `owned` (each in-progress task with an owner: whether its `✦ <owner>` window exists, whether that window's first pane is dead, how long its agent has been `ready`), `awake` (a live `caffeinatePid` in `awake.json`) and `pace` (7-day usage and the elapsed share of the week, from `usage.plan_limits`). `board/notify.py` turns them into four more kinds, in queue mode only, with the usual latch: `teammate_gone`, `teammate_silent` (ready 30 min with its task in progress), `awake_dropped` and `weekly_pace` (more than 15 points above the elapsed share). They reach the Discord feed as `critical`.
- **Actions.** `board/watch.py`, called by `server.observe_overview` after the notifier. Per stall (those kinds except `weekly_pace`, plus `lead_idle`): one `[Watch] …` line for the lead, queued like `[Board]` lines and typed only while the lead's own pane is ready; for `awake_dropped`, one `tmux-ctl awake on --queue --lid`, its result posted and put in the line; one re-alert `… — lead did not react (15 min)` when the stall still holds 15 min after it opened. `weekly_pace` is alert only. Open stalls live in `watch.json`, so a board restart does not nudge twice. `TC_WATCH=0` turns the watch off.
- **Board down.** Every overview writes `watch/heartbeat` (`{"at", "queue"}`). Each project's Discord bridge (`tools/discord-bridge/lib/watch.js`) reads it every minute. While its project was in queue mode in the last heartbeat read, a heartbeat older than 5 min gets one `⚠️ <project>: board down, night watch off (last heartbeat <at>)` post, and the next fresh one gets `<project>: board back, night watch on`.
````

In the "State files" table, insert these two rows right after the `recent-projects.json` row:

```markdown
| `watch.json` | board night watch (`board/watch.py`) | board night watch. Open stalls: `{"stalls": {"<project>\t<kind>\t<key>": {"first_at", "nudged_at", "fixed_at", "realerted_at"}}}`; a cleared stall is removed |
| `watch/heartbeat` | board night watch, every overview | Discord bridge (`lib/watch.js`). `{"at": "<UTC ISO>", "queue": [<projects in queue mode>]}` |
```

and this row right after the row that starts `| \`~/.local/state/agent-board/discord/<p>/bridge.json\``:

```markdown
| `~/.local/state/agent-board/discord/<p>/watch-state.json` | bridge (`watchTick`) | bridge. `{"armed", "down", "last"}`: whether the project was in queue mode in the last heartbeat read and whether the down post was made |
```

- [ ] **Step 5: Run to verify it passes**

Run: `env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_queue_ask_rule.zsh && test "$(grep -c '^## Night watch$' docs/ARCHITECTURE.md)" -eq 1 && grep -qF '| `watch/heartbeat` |' docs/ARCHITECTURE.md && grep -qF 'watch-state.json' docs/ARCHITECTURE.md`
Expected: both suites print `ALL PASS`, and the grep checks exit 0.

- [ ] **Step 6: Commit**

```bash
git add claude/orchestrator.md tools/tests/test_plugin.zsh docs/ARCHITECTURE.md
git commit -m "docs(architecture): night watch; lead rule for [Watch] lines" -- claude/orchestrator.md tools/tests/test_plugin.zsh docs/ARCHITECTURE.md
```
(End the message with the attribution trailer your harness specifies.)

