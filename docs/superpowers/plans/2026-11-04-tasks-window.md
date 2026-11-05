# Tasks window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `tasks` tmux window, right after `claude`, that draws the lead's live task list as a colourful dependency graph with owner state, tier, timing and small celebrations.

**Architecture:** `board/planview.py` (existing data source) gains `tier` and `blockedBy` per task. `board/taskwin_state.py` (new) keeps per-session timing and celebration events. `board/taskwin.py` (new) is a pure renderer `render(...) -> str` plus a `watch` loop and CLI. `bin/tmux-dev-layout` opens the window; `bin/tmux-teammate-window` places `✦` windows after it.

**Tech Stack:** Python 3 stdlib only (`python3 -I`), ANSI escapes, zsh, tmux 3.8.

**Spec:** `docs/superpowers/specs/2026-11-04-tasks-window-design.md`

## Global Constraints

- Work in the worktree `.claude/worktrees/tasks-window`, branch `feat/tasks-window` off `main`. Never edit the live checkout `/Users/francisco.ruiz/agent-board` (it is the install, and holds the user's uncommitted `claude/orchestrator.md` edit, which this branch must never include).
- Stdlib only; every Python entry point runs under `python3 -I` (the script adds its own dir to `sys.path`, as `planview.py` does).
- No ✗ glyph anywhere in the window's output. Status glyphs: completed `●`, in_progress `◐◓◑◒` cycling with `frame`, pending `○`, blocked `◌` plus `🔒`.
- `NO_COLOR` set (any value) ⇒ no escape sequences in `render` output; `COLORTERM` in (`truecolor`, `24bit`) ⇒ 24-bit colour; else 256-colour.
- Tier badge colours: `haiku` cyan, `sonnet` blue, `fable` violet; any other or empty tier ⇒ no badge.
- Narrow layout below 80 columns; graph layout at 80 and above.
- State file: `<tc_env.state_dir()>/taskwin/<session, unsafe chars → _>.json`.
- `TC_TASKS_WINDOW=0` ⇒ no `tasks` window. The test harness (`tools/tests/lib.zsh`) exports `TC_TASKS_WINDOW=0` beside `TC_OVERSEER=0`; only the tasks-window test unsets it.
- `planview.view()`'s top-level keys stay exactly `name`, `active`, `tasks` (board tests compare whole views).
- Commits: conventional with scope (`feat(board): …`, `feat(dev): …`, `docs: …`), ending with the attribution trailer your harness specifies.

**User decisions (already made):**
- "tmux window again" — a `tasks` window in the dev session, not a board panel or popup.
- Extras, all four: "Dependency graph, Live owner state, Progress + timing, Celebration".
- Approach A: stdlib Python ANSI renderer (no Textual/Rich, no curses).
- Teammate `✦` windows open after `tasks`, not between `claude` and `tasks`.

---

### Task 1: planview carries tier and blockedBy per task

**Goal:** Every task dict from `planview.view()` has `tier` (from the task's `metadata.modelTier` or its description's `json:metadata` fence) and `blockedBy`.

**Files:**
- Modify: `board/planview.py` (`_norm`, `_finish`, new `_tier`)
- Test: `board/tests/test_planview.py`

**Acceptance Criteria:**
- [ ] Task dicts carry `tier` (string, `""` when absent or malformed) and `blockedBy` (list of id strings); all other keys and values unchanged.
- [ ] `metadata.modelTier` (a dict key in the task JSON) wins over the description fence.
- [ ] Every existing `test_planview.py` case passes unchanged.
- [ ] New tests fail before the change (RED recorded).

**Verify:** `python3 -m unittest board.tests.test_planview -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to `board/tests/test_planview.py` (new class at the end, before any `if __name__` block):

```python
class TierAndBlockersTest(unittest.TestCase):
    def test_tier_from_description_fence(self):
        d = {"id": "1", "subject": "s", "status": "pending",
             "description": "**Goal:** x\n\n```json:metadata\n{\"modelTier\": \"mechanical\"}\n```"}
        self.assertEqual(planview._finish([planview._norm(d)])[0]["tier"], "mechanical")

    def test_tier_from_metadata_wins(self):
        d = {"id": "1", "subject": "s", "status": "pending", "metadata": {"modelTier": "frontier"},
             "description": "```json:metadata\n{\"modelTier\": \"mechanical\"}\n```"}
        self.assertEqual(planview._finish([planview._norm(d)])[0]["tier"], "frontier")

    def test_tier_missing_or_malformed_is_empty(self):
        for desc in ("", "no fence", "```json:metadata\n{not json\n```", "```json:metadata\n[1]\n```"):
            d = {"id": "1", "subject": "s", "status": "pending", "description": desc}
            self.assertEqual(planview._finish([planview._norm(d)])[0]["tier"], "", desc)

    def test_blocked_by_passes_through(self):
        a = {"id": "1", "subject": "a", "status": "pending"}
        b = {"id": "2", "subject": "b", "status": "pending", "blockedBy": ["1"]}
        out = planview._finish([planview._norm(a), planview._norm(b)])
        self.assertEqual([t["blockedBy"] for t in out], [[], ["1"]])
        self.assertEqual(out[1]["status"], "blocked")
```

Mutations: drop `tier` from `_finish`'s output dict → all three tier tests fail (KeyError); drop the metadata branch → `test_tier_from_metadata_wins` fails; drop `blockedBy` from the output → `test_blocked_by_passes_through` fails.

- [ ] **Step 2: RED.** `python3 -m unittest board.tests.test_planview -v 2>&1 | tail -3` → `FAILED (errors=4)` (KeyError `'tier'` / `'blockedBy'`).
- [ ] **Step 3: Implement.** In `board/planview.py` add `import re` to the imports, then add above `_norm`:

```python
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
```

Replace `_norm` with:

```python
def _norm(t):
    return {"id": str(t.get("id", "")), "subject": str(t.get("subject", "")), "status": str(t.get("status", "pending")),
            "owner": str(t.get("owner") or ""), "blockedBy": [str(b) for b in (t.get("blockedBy") or [])],
            "tier": _tier(t)}
```

In `_finish`, change the `out.append(...)` line to:

```python
        out.append({"id": t["id"], "subject": t["subject"], "status": st, "owner": t["owner"], "state": "",
                    "tier": t["tier"], "blockedBy": t["blockedBy"]})
```

Update the module docstring's `view(...)` line to list `"tier","blockedBy"` in the task keys.

- [ ] **Step 4: GREEN.** `python3 -m unittest board.tests.test_planview -v 2>&1 | tail -3` → `OK`. Also `python3 -m unittest board.tests.test_overview_api 2>&1 | tail -1` → `OK` (a `view()` consumer).
- [ ] **Step 5: Commit** `git add board/planview.py board/tests/test_planview.py` then `git commit -m "feat(board): planview tasks carry tier and blockedBy"` with your harness's trailer.

```json:metadata
{"files": ["board/planview.py", "board/tests/test_planview.py"], "verifyCommand": "python3 -m unittest board.tests.test_planview -v 2>&1 | tail -3", "acceptanceCriteria": ["task dicts carry tier and blockedBy, other keys unchanged", "metadata.modelTier wins over the fence", "existing planview tests pass unchanged", "new tests failed RED"], "modelTier": "mechanical"}
```

---

### Task 2: Timing and celebration state

**Goal:** `board/taskwin_state.py` records when each task entered its status and emits one celebration event per real completion, persisted across restarts.

**Files:**
- Create: `board/taskwin_state.py`
- Test: `board/tests/test_taskwin_state.py`

**Acceptance Criteria:**
- [ ] `path_for(state_dir, session)`, `load(path)`, `save(path, st)`, `update(st, lead, tasks, now)` exist with the behaviour below; `load` of a missing/corrupt file returns `{}`; `save` never raises.
- [ ] A `done` event fires exactly once when a known task changes to `completed`; never for a task first seen as completed; never after a restart (load → update).
- [ ] A `plan_done` event fires once when the list goes from not-all-done to all-done; not on a first poll that is already all done.
- [ ] Events older than 10 s are dropped on each update.
- [ ] A different `lead` resets the state.
- [ ] Tests fail RED first; `save` writes atomically (temp file + `os.replace`).

**Verify:** `python3 -m unittest board.tests.test_taskwin_state -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** in `board/tests/test_taskwin_state.py`:

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskwin_state as ts  # noqa: E402


def T(i, s):
    return {"id": str(i), "status": s}


class UpdateTest(unittest.TestCase):
    def test_first_sight_records_since_and_no_event(self):
        st = ts.update({}, "L", [T(1, "in_progress"), T(2, "completed")], 100.0)
        self.assertEqual(st["tasks"]["1"], {"status": "in_progress", "since": 100.0, "started": 100.0, "done": None})
        self.assertEqual(st["tasks"]["2"]["done"], 100.0)
        self.assertEqual(st["events"], [])

    def test_done_event_once_per_transition(self):
        st = ts.update({}, "L", [T(1, "in_progress"), T(2, "pending")], 100.0)
        st = ts.update(st, "L", [T(1, "completed"), T(2, "pending")], 160.0)
        self.assertEqual(st["events"], [{"kind": "done", "id": "1", "at": 160.0}])
        self.assertEqual(st["tasks"]["1"]["since"], 160.0)
        st = ts.update(st, "L", [T(1, "completed"), T(2, "pending")], 161.0)
        self.assertEqual([e for e in st["events"] if e["kind"] == "done"], [{"kind": "done", "id": "1", "at": 160.0}])

    def test_events_expire_after_ten_seconds(self):
        st = ts.update({}, "L", [T(1, "in_progress"), T(2, "pending")], 100.0)
        st = ts.update(st, "L", [T(1, "completed"), T(2, "pending")], 160.0)
        st = ts.update(st, "L", [T(1, "completed"), T(2, "pending")], 171.0)
        self.assertEqual(st["events"], [])

    def test_plan_done_once_and_not_on_first_poll(self):
        st = ts.update({}, "L", [T(1, "completed")], 100.0)
        self.assertEqual(st["events"], [])
        st = ts.update({}, "L", [T(1, "in_progress")], 100.0)
        st = ts.update(st, "L", [T(1, "completed")], 120.0)
        self.assertIn({"kind": "plan_done", "at": 120.0}, st["events"])
        st = ts.update(st, "L", [T(1, "completed")], 121.0)
        self.assertEqual(sum(e["kind"] == "plan_done" for e in st["events"]), 1)

    def test_restart_does_not_replay(self):
        with tempfile.TemporaryDirectory() as d:
            p = ts.path_for(d, "dev/x:1")
            self.assertEqual(p, Path(d) / "taskwin" / "dev_x_1.json")
            st = ts.update({}, "L", [T(1, "in_progress")], 100.0)
            st = ts.update(st, "L", [T(1, "completed")], 120.0)
            ts.save(p, st)
            st2 = ts.update(ts.load(p), "L", [T(1, "completed")], 200.0)
            self.assertEqual(st2["events"], [])
            self.assertEqual(st2["tasks"]["1"]["done"], 120.0)

    def test_new_lead_resets(self):
        st = ts.update({}, "L", [T(1, "in_progress")], 100.0)
        st = ts.update(st, "M", [T(1, "in_progress")], 200.0)
        self.assertEqual(st["lead"], "M")
        self.assertEqual(st["tasks"]["1"]["since"], 200.0)

    def test_load_missing_or_corrupt_and_save_unwritable(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ts.load(Path(d) / "nope.json"), {})
            (Path(d) / "bad.json").write_text("{nope")
            self.assertEqual(ts.load(Path(d) / "bad.json"), {})
            (Path(d) / "list.json").write_text(json.dumps([1]))
            self.assertEqual(ts.load(Path(d) / "list.json"), {})
            f = Path(d) / "file"
            f.write_text("x")
            ts.save(f / "sub" / "s.json", {"a": 1})   # parent is a file: must not raise


if __name__ == "__main__":
    unittest.main()
```

Mutations: emit `done` for first-seen completed tasks → `test_first_sight_records_since_and_no_event` fails; drop the expiry filter → `test_events_expire_after_ten_seconds` fails; treat `all_done is None` like `False` → `test_plan_done_once_and_not_on_first_poll` fails; drop the lead check → `test_new_lead_resets` fails.

- [ ] **Step 2: RED.** `python3 -m unittest board.tests.test_taskwin_state -v 2>&1 | tail -3` → `FAILED (errors=1)` (ModuleNotFoundError `taskwin_state`).
- [ ] **Step 3: Implement** `board/taskwin_state.py`:

```python
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
```

- [ ] **Step 4: GREEN.** `python3 -m unittest board.tests.test_taskwin_state -v 2>&1 | tail -3` → `OK`.
- [ ] **Step 5: Commit** `git add board/taskwin_state.py board/tests/test_taskwin_state.py` then `git commit -m "feat(board): taskwin_state keeps task timing and celebration events"` with your harness's trailer.

```json:metadata
{"files": ["board/taskwin_state.py", "board/tests/test_taskwin_state.py"], "verifyCommand": "python3 -m unittest board.tests.test_taskwin_state -v 2>&1 | tail -3", "acceptanceCriteria": ["path_for/load/save/update behave as specified; load {} on missing/corrupt; save never raises", "done event once per real completion, never first-seen or after restart", "plan_done once on not-all to all, not on first poll", "events older than 10s dropped", "new lead resets", "RED first; atomic save"], "modelTier": "standard"}
```

---

### Task 3: The renderer

**Goal:** `board/taskwin.py` exposes a pure `render(view, timing, width, height, now, frame, color) -> str` and `color_mode(env) -> str` that draw the task list as the spec's graph (§3) with celebrations (§4).

**Constraints:**
- Inputs: `view` is `planview.view()` output (tasks: `id, subject, status ∈ {completed, in_progress, pending, blocked}, owner, state ∈ {working, waiting, ready, gone, ""}, tier, blockedBy`); `timing` is `taskwin_state` state (may be `{}`); `color ∈ {"truecolor", "256", "none"}`; `color_mode` returns `"none"` when `NO_COLOR` is set, `"truecolor"` for `COLORTERM` truecolor/24bit, else `"256"`.
- Pure: no I/O, no clock, no tmux; output is lines joined by `\n`, at most `height` lines, each at most `width` display cells (count East Asian Wide/Fullwidth and emoji such as `🔒` as 2 cells).
- Header: plan name (or `Tasks`), a progress bar (green over grey in colour), `done/total`, elapsed since the earliest `started` in timing (`—` when unknown).
- Width ≥ 80: cards with rounded borders (`╭╮╰╯`), columns by depth (longest `blockedBy` chain to a root; unknown blocker ids ignored; cycles must not hang), box-drawing connectors from blocker to dependent; critical path (longest chain of unfinished tasks) drawn with a bold accent (magenta) border; when too tall, completed columns collapse first into a one-line `● <first>–<last> done` summary. Width < 80: one line per task with `⇠ 2,3` blocker hints.
- Card: id + subject (truncated with `…`), tier badge per Global Constraints, owner `✦ <name>` with state (working: amber pulsing with `frame`; waiting: red `needs you`; ready: grey `idle`; gone: dim `gone`), time in current status from `timing["tasks"][id]["since"]` (`12m`, `3h`, `2d` style).
- Celebration: a `done` event younger than 2 s ⇒ that card drawn inverse and a `✦ Task <id> done ✦` line under the header; a `plan_done` event younger than 5 s ⇒ an animated confetti banner (varies with `frame`); all tasks completed otherwise ⇒ a calm `Plan done ✓` banner.
- Empty task list ⇒ idle screen naming the session (`view` has no session; take it from a `session` keyword argument, default `""`): `No tasks yet — the lead's list shows up here`.
- No ✗ anywhere; glyphs exactly as Global Constraints.
- Use the frontend-design skill for the visual direction; keep it legible on dark and light terminals.

**Files:**
- Create: `board/taskwin.py` (render, color_mode and helpers only; `watch` and the CLI are Task 4)
- Test: `board/tests/test_taskwin.py`

**Acceptance Criteria:**
- [ ] `render` with `color="none"` at 120×40 and 60×40 on a 6-task fixture (two roots, a diamond, one blocked, one with owner waiting, mixed tiers) matches committed snapshots `board/tests/fixtures/taskwin/wide.txt` and `narrow.txt`; no line exceeds the width in display cells; output contains no `\x1b` and no `✗`.
- [ ] Diamond graph (1→2, 1→3, 2→4, 3→4) puts 1, {2,3}, 4 in depths 0, 1, 2; a cycle (1→2→1) renders without hanging.
- [ ] Critical path test: in a graph with a 3-long and a 2-long unfinished chain, only the 3-long chain's cards carry the accent marker (assert via the colour output's magenta escape on those cards, or a helper `critical_path(tasks) -> list[id]` tested directly).
- [ ] Collapse test: 30 tasks at height 20 keep every unfinished task visible and show the `● … done` summary.
- [ ] Celebration tests: `done` event at `now-1` ⇒ sparkle line present; at `now-3` ⇒ absent; `plan_done` at `now-1` ⇒ confetti differs between `frame=0` and `frame=1`; all completed without events ⇒ `Plan done ✓`.
- [ ] Colour tests: `"truecolor"` output uses `38;2;` sequences, `"256"` uses `38;5;` and no `38;2;`; `color_mode({"NO_COLOR": ""})` is `"none"`.
- [ ] Empty view ⇒ the idle line with the session name.
- [ ] Tests written first and seen failing (RED recorded in the report).

**Verify:** `python3 -m unittest board.tests.test_taskwin -v 2>&1 | tail -3` → `OK`

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin.py", "board/tests/fixtures/taskwin/wide.txt", "board/tests/fixtures/taskwin/narrow.txt"], "verifyCommand": "python3 -m unittest board.tests.test_taskwin -v 2>&1 | tail -3", "acceptanceCriteria": ["snapshots at 120 and 60 cols, width respected in display cells, no escapes and no ✗ with color none", "diamond depths 0/1/2, cycle does not hang", "critical path marks only the longest unfinished chain", "collapse keeps unfinished visible with done summary", "celebration timing for done and plan_done, calm Plan done banner", "truecolor/256/none colour modes", "empty view idle line", "RED first"], "modelTier": "frontier"}
```

---

### Task 4: watch loop, CLI and a real run

**Goal:** `python3 -I board/taskwin.py watch --session S --root R` redraws the window once a second; `render` prints one frame; both are proven on a scratch tmux server with a real task directory and read-only against the user's live state.

**Files:**
- Modify: `board/taskwin.py` (add `watch`, `main`, `if __name__ == "__main__"`)
- Test: `board/tests/test_taskwin_cli.py`
- Create: `tools/tests/e2e-tasks-window.zsh` (e2e, not in run-all: name does not start with `test_`)

**Acceptance Criteria:**
- [ ] CLI: `taskwin.py watch --session S [--root R] [--home H] [--interval SEC]` and `taskwin.py render --session S [--root R] [--home H] [--width W] [--height H]`; `--home` defaults to `~/.claude`, `--root` to `.`.
- [ ] `render` prints one frame (colour per `color_mode(os.environ)`), never writes the timing state file, exits 0.
- [ ] `watch` each tick: `planview.view(session, root, home, tc_env.state_dir(), paneclass.tmux_runner())`, `planview.lead_session(...)` for the lead id, `taskwin_state.update`, `taskwin_state.save` (only when the state changed), then `render` at `shutil.get_terminal_size()`; draws with cursor-home, each line followed by `\x1b[K`, then `\x1b[J`; hides the cursor (`\x1b[?25l`) at start and restores it (`\x1b[?25h`) on exit, KeyboardInterrupt, SIGTERM and SIGHUP; an exception in one tick shows the last good frame plus a one-line error and the loop continues.
- [ ] `watch(..., frames=N)` seam stops after N ticks (used by the unit test with a fake tmux and a temp home).
- [ ] Unit tests (`board/tests/test_taskwin_cli.py`): `render` subcommand on a temp home with one `sessions/*.json` + `tasks/session-<id8>/*.json` prints the subjects and leaves no `taskwin/` dir under `TC_STATE`; `watch(frames=2)` writes the state file and its output starts with `\x1b[?25l` and ends with `\x1b[?25h`; a view that raises on tick 2 still ends with the cursor restored and an error line. Tests set `TC_STATE` to a temp dir.
- [ ] e2e on a scratch server (`~/.local/bin/tmux -L <sock> -f /dev/null`, 120 columns): a fake home whose `tasks/session-<id8>/` is a copy of a real task directory from `~/.claude/tasks/` (pick the newest with ≥ 5 tasks; name it in the report), a `sessions/x.json` pointing at the scratch `claude` pane; `taskwin.py watch` in a second window; `capture-pane -e -p` after 3 s contains `●` or `○` and a card border `╭`; the capture is saved in the report.
- [ ] Real long-lived state, read-only: `NO_COLOR=1 python3 -I board/taskwin.py render --session agent-board --root ~/agent-board --width 120 --height 40` exits 0 against the user's live board and prints a header line; output saved in the report.

**Verify:** `python3 -m unittest board.tests.test_taskwin_cli -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing unit tests** in `board/tests/test_taskwin_cli.py` for every unit-test criterion above. Build the temp home like `board/tests/test_planview.py` does (look at its fixture helpers and `fake_tmux`), and run the CLI with `subprocess.run([sys.executable, "-I", str(TASKWIN), "render", ...], env={**os.environ, "TC_STATE": tmp, "NO_COLOR": "1"})`. Mutation: remove the `finally` that writes `\x1b[?25h` → the raising-view test fails.
- [ ] **Step 2: RED.** `python3 -m unittest board.tests.test_taskwin_cli -v 2>&1 | tail -3` → `FAILED`.
- [ ] **Step 3: Implement** `watch` and `main` in `board/taskwin.py` to meet the criteria. Signal handling: `signal.signal(signal.SIGTERM, ...)` and `SIGHUP` raise `SystemExit`, so the `try/finally` restores the cursor.
- [ ] **Step 4: GREEN.** `python3 -m unittest board.tests.test_taskwin_cli -v 2>&1 | tail -3` → `OK`; also `python3 -m unittest board.tests.test_taskwin board.tests.test_taskwin_state board.tests.test_planview 2>&1 | tail -1` → `OK`.
- [ ] **Step 5: e2e.** Write `tools/tests/e2e-tasks-window.zsh` (source `tools/tests/lib.zsh`, `tt_setup claude`, build the fake home under `$TT_DIR`, start `tt new-window -d -t '=tt:' -n tasks "python3 -I $TT_REPO/board/taskwin.py watch --session tt --home $TT_DIR/home"`, `sleep 3`, capture with `tt capture-pane -e -p -t '=tt:tasks'`, `check` for `╭` and `●|○`, `tt_done`). Run `zsh tools/tests/e2e-tasks-window.zsh; echo rc=$?` → `ALL PASS`, `rc=0`. Then run the read-only real-state command from the criteria. Put both outputs in the report.
- [ ] **Step 6: Commit** `git add board/taskwin.py board/tests/test_taskwin_cli.py tools/tests/e2e-tasks-window.zsh` then `git commit -m "feat(board): taskwin watch loop and CLI"` with your harness's trailer.

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin_cli.py", "tools/tests/e2e-tasks-window.zsh"], "verifyCommand": "python3 -m unittest board.tests.test_taskwin_cli -v 2>&1 | tail -3", "acceptanceCriteria": ["watch and render subcommands with --session/--root/--home/--width/--height/--interval", "render prints one frame, writes no state, exits 0", "watch tick: view, lead, update, save on change, redraw with K/J, cursor hidden and restored on exit/INT/TERM/HUP, tick errors shown and survived", "frames=N seam", "unit tests for render, watch frames=2, raising view", "e2e on scratch tmux with a copied real task dir, capture saved", "read-only render against the live board exits 0"], "modelTier": "standard"}
```

---

### Task 5: Layout opens the window; teammates land after it

**Goal:** `bin/tmux-dev-layout` opens `tasks` right after `claude` (unless `TC_TASKS_WINDOW=0`), and `bin/tmux-teammate-window` places `✦` windows after it.

**Files:**
- Modify: `bin/tmux-dev-layout` (after the retired-plan block)
- Modify: `bin/tmux-teammate-window` (the placement loop)
- Modify: `tools/tests/lib.zsh` (`tt_setup` exports `TC_TASKS_WINDOW=0`)
- Create: `tools/tests/test_tasks_window.zsh`

**Acceptance Criteria:**
- [ ] After a layout run, `tasks` is at `claude`'s index + 1, flagged `@tc_tasks 1`, with automatic-rename off, and its pane start command contains `board/taskwin.py watch --session <sess>`.
- [ ] A second layout run leaves exactly one `tasks` window; `TC_TASKS_WINDOW=0` gives none.
- [ ] A teammate split from `claude` lands at `tasks`'s index + 1; a second teammate after the first.
- [ ] Every other zsh test still passes: `zsh tools/tests/run-all.zsh; echo rc=$?` → `rc=0` (run once, in the background, by the tester; read the file's `rc=` line).
- [ ] New test failed RED before the layout change.

**Verify:** `zsh tools/tests/test_tasks_window.zsh; echo rc=$?` → `ALL PASS`, `rc=0`

**Steps:**

- [ ] **Step 1: Harness default.** In `tools/tests/lib.zsh`, on the line after `export TC_OVERSEER=0 …`, add:

```zsh
  export TC_TASKS_WINDOW=0   # the dev layout would open the tasks window (a python watch loop) in every scratch session; test_tasks_window.zsh turns it on
```

- [ ] **Step 2: Failing test** `tools/tests/test_tasks_window.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
L="${TC_LAYOUT:-$TT_REPO/bin/tmux-dev-layout}"
H="$TT_REPO/bin/tmux-teammate-window"
tt_setup claude
unset TC_TASKS_WINDOW
idx() { tt list-windows -t "=$1" -F '#{window_index} #{window_name}' | awk -v n="$2" '{i=$1; $1=""; sub(/^ /,""); if ($0==n) print i}' }
"$L" tt "$TT_DIR"
ci="$(idx tt claude)"
check "tasks after claude"        test "$(idx tt tasks)" = $(( ci + 1 ))
check "tasks flagged"             test "$(tt show-options -wqv -t '=tt:tasks' @tc_tasks)" = 1
check "tasks runs taskwin watch"  zsh -c 'print -r -- "$1" | grep -qF "board/taskwin.py watch --session tt"' _ "$(tt display -p -t '=tt:tasks' '#{pane_start_command}')"
check "tasks keeps its name"      test "$(tt show-options -wqv -t '=tt:tasks' automatic-rename)" = off
"$L" tt "$TT_DIR"
check "idempotent"                test "$(tt list-windows -t '=tt' -F '#{window_name}' | grep -cx tasks)" = 1
tt new-session -d -s off -n claude -c "$TT_DIR"
TC_TASKS_WINDOW=0 "$L" off "$TT_DIR"
check "TC_TASKS_WINDOW=0: none"   test -z "$(idx off tasks)"
# teammates land after tasks (same direct shape as test_teammate_window.zsh, copied from Claude Code 2.1.301)
tt set-hook -g after-split-window "run-shell -b '$H --hook #{pane_id}'"
tt split-window -d -t '=tt:claude' "cd /tmp && env CLAUDECODE=1 sh -c 'sleep 60; :' --agent-id probe-a@tt --agent-name probe-a --team-name tt"
tt_wait 12 test -n "$(idx tt '✦ probe-a')"
check "teammate after tasks"      test "$(idx tt '✦ probe-a')" = $(( ci + 2 ))
tt split-window -d -t '=tt:claude' "cd /tmp && env CLAUDECODE=1 sh -c 'sleep 60; :' --agent-id probe-b@tt --agent-name probe-b --team-name tt"
tt_wait 12 test -n "$(idx tt '✦ probe-b')"
check "second teammate after"     test "$(idx tt '✦ probe-b')" = $(( ci + 3 ))
tt_done
```

Mutations: remove the layout block → the first four checks fail; drop the `@tc_tasks` term from the teammate-window format → "teammate after tasks" fails (it lands at `ci + 1`).

- [ ] **Step 3: RED.** `zsh tools/tests/test_tasks_window.zsh 2>&1 | grep -E '^(FAIL|ALL|[0-9]+ FAILED)'` → FAIL lines for the tasks checks.
- [ ] **Step 4: Layout.** In `bin/tmux-dev-layout`, after the retired-plan block (`# the retired plan window …` / `fi`), add:

```zsh
# the tasks window (2026-11-04): a live view of the lead's task list, right after claude; TC_TASKS_WINDOW=0 turns it off
if [[ "${TC_TASKS_WINDOW:-1}" != 0 ]] && has_win "$sess" claude && ! has_win "$sess" tasks; then
  repo="${${(%):-%x}:A:h:h}"
  if t new-window -d -a -t "=${sess}:claude" -n tasks -c "$root" \
       "python3 -I ${(q)repo}/board/taskwin.py watch --session ${(q)sess} --root ${(q)root}"; then
    t set-option -w -t "=${sess}:tasks" @tc_tasks 1
    t set-option -w -t "=${sess}:tasks" automatic-rename off
  fi
fi
```

Probe (plan author, tmux 3.8, scratch server `-f /dev/null`): `new-window -d -a -t '=p:claude' -n tasks` placed `tasks` at index 1 after `claude` at 0.

- [ ] **Step 5: Teammate placement.** In `bin/tmux-teammate-window`, change the placement loop's `list-windows` format from `'#{window_index} #{@tc_teammate}'` to `'#{window_index} #{?#{@tc_teammate},1,#{?#{@tc_tasks},1,0}}'` and update the comment above it to "insert after the lead's window, behind the tasks window and teammate windows that already follow it". Probe (plan author, tmux 3.8): that format printed `0 0 claude`, `1 1 tasks`, `2 0 other`.
- [ ] **Step 6: GREEN.** `zsh tools/tests/test_tasks_window.zsh; echo rc=$?` → `ALL PASS`, `rc=0`; `zsh tools/tests/test_layout.zsh; echo rc=$?` and `zsh tools/tests/test_teammate_window.zsh; echo rc=$?` → `rc=0`.
- [ ] **Step 7: Commit** `git add bin/tmux-dev-layout bin/tmux-teammate-window tools/tests/lib.zsh tools/tests/test_tasks_window.zsh` then `git commit -m "feat(dev): tasks window after claude; teammates open after it"` with your harness's trailer.

```json:metadata
{"files": ["bin/tmux-dev-layout", "bin/tmux-teammate-window", "tools/tests/lib.zsh", "tools/tests/test_tasks_window.zsh"], "verifyCommand": "zsh tools/tests/test_tasks_window.zsh; echo rc=$?", "acceptanceCriteria": ["tasks at claude+1, flagged, rename off, runs taskwin watch --session", "idempotent; TC_TASKS_WINDOW=0 gives none", "teammates land after tasks", "run-all rc=0", "RED first"], "modelTier": "standard"}
```

---

### Task 6: Docs name the window

**Goal:** The lead rules, both tmux-orchestrator skills, the architecture doc, the customization table and the `bin/dev` header describe the `tasks` window.

**Files:**
- Modify: `claude/orchestrator.md` (windows table, after the `claude` row)
- Modify: `claude/skills/tmux-orchestrator/SKILL.md:15-16`, `claude/plugin/skills/tmux-orchestrator/SKILL.md:15-16`
- Modify: `docs/ARCHITECTURE.md:126` (Teammates paragraph)
- Modify: `docs/CUSTOMIZATION.md` (row after `TC_TERMINAL_SESSION`)
- Modify: `bin/dev:3`

**Acceptance Criteria:**
- [ ] Each file carries the exact text given in the steps.
- [ ] `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0` (it rejects a backticked `ns:name` skill that is not shipped, and a backticked /handoff or tmux-orchestrator without agent-board: on the line; the new rows have neither).
- [ ] `bin/dev --help` prints the updated line 3.

**Verify:** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`

**Steps:**

- [ ] **Step 1:** In `claude/orchestrator.md`'s windows table, after the line `| \`claude\` | you, the team lead |`, insert:

```markdown
| `tasks` | a live graph of your task list: status, owners, tiers, timing (`TC_TASKS_WINDOW=0` turns it off) |
```

- [ ] **Step 2:** In both `tmux-orchestrator` SKILL.md files, after the line `| \`claude\` | the team lead |`, insert:

```markdown
| `tasks` | a live graph of the lead's task list (read-only) |
```

- [ ] **Step 3:** In `docs/ARCHITECTURE.md`, in the Teammates paragraph, replace `placed after the lead and any teammate windows already there.` with `placed after the lead, the \`tasks\` window and any teammate windows already there.` Then add a new paragraph right after it:

```markdown
**Tasks window.** `tmux-dev-layout` opens a `tasks` window right after `claude`, running `board/taskwin.py watch`. It reads the lead's live task list through `planview.view()`, keeps per-task timing in `$TC_STATE/taskwin/<session>.json` (`board/taskwin_state.py`), and redraws once a second: a dependency graph of cards with status glyphs, tier badges, owner state and a progress header. `TC_TASKS_WINDOW=0` turns it off.
```

- [ ] **Step 4:** In `docs/CUSTOMIZATION.md`, after the `TC_TERMINAL_SESSION` row, insert:

```markdown
| `TC_TASKS_WINDOW` | unset (on) | `bin/tmux-dev-layout` | `0` does not open the `tasks` window (the test harness sets it). An existing window stays until you close it. |
```

- [ ] **Step 5:** Replace `bin/dev` line 3 with:

```zsh
# Windows: 1 claude, 2 tasks (a live graph of the lead's task list; TC_TASKS_WINDOW=0 turns it off). A throwaway shell is prefix S. Agent windows live in the hidden session <name>-bg.  Run it again and it just reattaches.
```

- [ ] **Step 6: Verify.** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`; `bin/dev --help | sed -n 2p | grep -c tasks` → `1`.
- [ ] **Step 7: Commit** `git add claude/orchestrator.md claude/skills/tmux-orchestrator/SKILL.md claude/plugin/skills/tmux-orchestrator/SKILL.md docs/ARCHITECTURE.md docs/CUSTOMIZATION.md bin/dev` then `git commit -m "docs: the tasks window"` with your harness's trailer.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/skills/tmux-orchestrator/SKILL.md", "claude/plugin/skills/tmux-orchestrator/SKILL.md", "docs/ARCHITECTURE.md", "docs/CUSTOMIZATION.md", "bin/dev"], "verifyCommand": "zsh tools/tests/test_plugin.zsh; echo rc=$?", "acceptanceCriteria": ["each file carries the exact text from the steps", "test_plugin ALL PASS rc=0", "bin/dev --help shows the tasks line"], "modelTier": "mechanical"}
```
