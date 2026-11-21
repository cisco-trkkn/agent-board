# Interactive tasks window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The `tasks` window takes keys: a queue overview of the `Plan & run:` items, the plan view with a cursor, filters and a done-collapse, and a history view built from a new per-project journal plus past ledgers and queue reports. The view state survives a lead change and a window restart.

**Architecture:** Three new pure modules. `board/taskwin_ui.py` decodes keys and holds `handle_key`. `board/taskwin_views.py` builds the rows of each view, so the renderer and the key handler agree on what a cursor index means. `board/taskwin_hist.py` holds the mtime-cached readers for spec titles, the journal, ledgers and reports. `board/taskwin_state.py` gains the journal writer and keeps `ui` across a lead change. `board/planview.py` passes three metadata fields through. `board/taskwin.py` gains a `ui`/`ctx` render path; `ui=None` is today's render, byte for byte. `watch` reads keys from the TTY in cbreak mode through `select`.

**Tech Stack:** Python 3.9+ stdlib (`termios`, `tty`, `select`, `json`, `re`), `unittest`, zsh + scratch tmux (`tools/tests/lib.zsh`) for the e2e script.

**Spec:** docs/superpowers/specs/2026-11-10-interactive-tasks-window-design.md

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-10-interactive-tasks-window-design.md",
 "base": "878263ef370347c6be0e8911c42ef5a69911b9ff",
 "depends_on": [],
 "writes": [{"path": "board/planview.py", "mode": "modify"},
            {"path": "board/tests/test_planview.py", "mode": "append"},
            {"path": "board/taskwin_state.py", "mode": "modify"},
            {"path": "board/tests/test_taskwin_state.py", "mode": "append"},
            {"path": "board/taskwin_ui.py", "mode": "create"},
            {"path": "board/taskwin_views.py", "mode": "create"},
            {"path": "board/tests/test_taskwin_ui.py", "mode": "create"},
            {"path": "board/taskwin_hist.py", "mode": "create"},
            {"path": "board/tests/test_taskwin_hist.py", "mode": "create"},
            {"path": "board/taskwin.py", "mode": "modify"},
            {"path": "board/tests/test_taskwin_screens.py", "mode": "create"},
            {"path": "board/tests/test_taskwin_cli.py", "mode": "modify"},
            {"path": "tools/tests/e2e-tasks-window.zsh", "mode": "modify"},
            {"path": "docs/ARCHITECTURE.md", "mode": "modify"}],
 "reads": ["docs/superpowers/ledgers/2026-11-09-remote-access/progress.md", "docs/superpowers/reports/2026-11-05-queue.md",
           "docs/superpowers/specs/2026-11-10-interactive-tasks-window-design.md", "board/tests/test_taskwin.py",
           "board/tests/fixtures/planview/README.md", "tools/tests/lib.zsh", "bin/tmux-dev-layout", "bin/tmux-session-closed"],
 "produces": ["taskwin history journal <TC_STATE>/taskwin/<project>.history.jsonl",
              "planview.view task fields outcome, answeredAt, planPath", "taskwin.render ui/ctx keywords"],
 "consumes": ["planview.view", "planview.project_of", "lead task metadata.outcome, metadata.queue.answeredAt, metadata.plan"],
 "tests": ["board/tests/test_planview.py", "board/tests/test_taskwin_state.py", "board/tests/test_taskwin_ui.py",
           "board/tests/test_taskwin_hist.py", "board/tests/test_taskwin_screens.py", "board/tests/test_taskwin_cli.py",
           "board/tests/test_taskwin.py", "tools/tests/e2e-tasks-window.zsh"]}
```

## Global Constraints

- **Read-only window:** the window never writes tasks, never runs git, and reads only the task list, its state file, the journal, spec files (for titles) and `docs/superpowers/{ledgers,reports}` under `--root`. Its only writes are the state file `<TC_STATE>/taskwin/<session>.json` and the journal.
- **`render` compatibility:** `taskwin.render(..., ui=None, ctx=None)` with `ui=None` returns exactly what it returns today. Every existing test in `board/tests/test_taskwin.py` passes unchanged. The `render` CLI subcommand passes no `ui`.
- **Queue item:** a task whose subject starts with `Plan & run: ` (`taskwin_views.QUEUE_PREFIX`). Its spec is the first word after the prefix, `#part` kept (`taskwin_state.spec_of`). The spec file is that word with the `#…` dropped.
- **Row keys** (one definition, used by renderer and key handler): queue `q:<id>`; plan `p:done` (the collapsed done line) and `p:<id>`; history `h:<entry key>`, where an entry key is `plan:<plan stem>` or `spec:<spec path>`. History rows start collapsed; every other row starts expanded (`taskwin_ui.is_collapsed`).
- **Filter `active`** = status `in_progress` or `blocked` (planview's name for pending with an open blocker). Ready pending tasks are hidden (see assumption A1).
- **Journal:** `<TC_STATE>/taskwin/<project>.history.jsonl`, where `<project>` is `planview.project_of(session, tmux)` (the session group, else the session name). Lines: `{"kind":"task_done","at","plan","id","subject","owner","tier"}` and `{"kind":"queue_outcome","at","spec","outcome"[,"plan"]}`. Dedupe on (`kind`, `plan` for task_done or `spec` for queue_outcome, `id`, `subject`) against the last 500 lines. Cap 5000 lines (`.tmp` + `os.replace`). I/O errors are ignored.
- **Cursor marks:** queue and history rows have a two-cell gutter, `▸ ` on the cursor row and two spaces otherwise, and in colour the cursor row is also inverse. A plan list row: inverse, and in `color == "none"` a `>` before the id (before the critical-path `*`). A plan graph card: heavy corners `┏ ┓ ┗ ┛`.
- **Header tabs:** line 0 in `ui` mode starts `[1 queue] 2 plan 3 history` (active tab bold and bracketed, the others grey), then two spaces, then the view's name. The counts stay right-aligned.
- **Times** are local (`taskwin_hist.hm` = `%H:%M`, `taskwin_hist.day_of` = `%Y-%m-%d` of `time.localtime`). Tests build timestamps with `time.mktime` at local noon or 09:30, so they pass in any TZ.
- **Never raises:** a bad key, a malformed journal line, ledger or report, or a missing docs folder never kills the window. The per-tick `except Exception` in `watch` stays. The terminal mode is restored in `finally`, which the SIGTERM/SIGHUP handler also reaches (it calls `sys.exit`).
- **Tests never touch the developer's terminal:** every test that calls `taskwin.watch` passes `stdin=` (a pty, a pipe or `io.StringIO()`).
- **Zsh gotchas** (CLAUDE.md): never name a variable `path`; quote `=name` tmux targets; brace variables before `:`; `grep` with an empty file list reads stdin, so guard it with `(( n > 0 ))` and `</dev/null`.
- **Commits:** conventional commits with scope (`feat(taskwin): …`, `feat(planview): …`, `test(taskwin): …`, `docs(architecture): …`). End each commit message with the attribution trailer your harness specifies. Stage only your own paths (`git add <paths>`).

**User decisions (already made):** from the spec's Decisions section: a Queue overview, Filter / collapse, and History (a journal from now on, plus past ledgers and queue reports). No per-task detail pane. The window stays read-only.

**Assumptions made while planning (no lead ruling yet; each is cheap to change):**
- A1: the spec defines `active` twice: §1 says "in_progress + blocked pending" and §3 says "pending tasks whose blockers are open". Both name pending tasks with an unfinished blocker, so `active` = `in_progress` + `blocked`. Cost if wrong: one line in `taskwin_views.filter_tasks`.
- A2: `queue_outcome` lines also carry `"plan": <plan stem>` when the queue task has `metadata.plan` (26 of 200 real queue tasks have it). Without it, a journal-only plan could not be tied to its queue outcome. The spec's dedupe key ignores the extra field.
- A3: real ledgers vary on line 2 (11 of 47 have `Preflight scan:` or prose there), so the parser requires only line 1 (`# SDD ledger — plan: <path>`) and a `YYYY-MM-DD` folder prefix, and takes `Spec: <path>.md` and `branch <b>` from any of lines 2-6. All 47 real ledgers parse.
- A4: a history plan row shows `· 1 task` / `· <n> tasks` only when n > 0. With no journal lines it shows no count (not "0 tasks").
- A5: in the queue view, Enter on a finished or pending row does nothing. These rows have no detail to expand, and `c` has no finished rows to fold there.
- A6: a queue task's `metadata.outcome` is read when it turns completed. If the lead writes the outcome in a later update, the journal line keeps `""` and the history falls back to the report row.
- A7: when the graph layout auto-collapses all-done columns (today's behaviour) and the cursor's task is in one of them, no card is highlighted. In `ui` mode the list layout does not auto-summarise done rows; the user's `c` does that.

---

### Task 1: planview carries outcome, answeredAt, plan path

**Goal:** Each task in `planview.view()["tasks"]` gains string fields `outcome` (`metadata.outcome`), `answeredAt` (`metadata.queue.answeredAt`) and `planPath` (`metadata.plan`), each `""` when missing or not a string.

**Files:**
- Modify: `board/planview.py` (`_norm`, `_finish`, module docstring)
- Test: `board/tests/test_planview.py` (append class `QueueFieldsTest`)

**Acceptance Criteria:**
- [ ] `_finish([_norm(d)])[0]` has `outcome`, `answeredAt` and `planPath` equal to the metadata strings.
- [ ] Metadata that is missing, not a dict, or holds non-string values gives `""` for all three.
- [ ] The rest of `test_planview.py` passes unchanged.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_planview.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing test.** Append at the very end of `board/tests/test_planview.py` (after the existing last class; unittest discover finds it there):

```python
class QueueFieldsTest(unittest.TestCase):
    """_norm/_finish carry metadata.outcome, metadata.queue.answeredAt and metadata.plan as strings, else ""."""

    def test_queue_fields_from_metadata(self):
        d = {"id": "4", "subject": "Plan & run: docs/superpowers/specs/x-design.md", "status": "completed",
             "metadata": {"outcome": "merged abc1234", "plan": "docs/superpowers/plans/x.md",
                          "queue": {"batch": "b", "answeredAt": "2026-11-12T06:27:47Z"}}}
        t = planview._finish([planview._norm(d)])[0]
        self.assertEqual((t["outcome"], t["answeredAt"], t["planPath"]),
                         ("merged abc1234", "2026-11-12T06:27:47Z", "docs/superpowers/plans/x.md"))

    def test_missing_or_malformed_metadata_gives_empty_strings(self):
        for meta in (None, 3, {}, {"outcome": 5, "queue": "x", "plan": ["p"]}, {"queue": {"answeredAt": 1}}):
            d = {"id": "1", "subject": "s", "status": "pending", "metadata": meta}
            t = planview._finish([planview._norm(d)])[0]
            self.assertEqual((t["outcome"], t["answeredAt"], t["planPath"]), ("", "", ""), meta)
```

Mutation: drop `"outcome": t.get("outcome", "")` from `_finish` → `test_queue_fields_from_metadata` fails with KeyError.

- [ ] **Step 2: Run it.** `python3 -m unittest discover -s board/tests -p 'test_planview.py'` → 2 errors, `KeyError: 'outcome'`.

- [ ] **Step 3: Implement.** In `board/planview.py`, replace `_norm` with:

```python
def _str(d, k):
    v = d.get(k) if isinstance(d, dict) else None
    return v if isinstance(v, str) else ""


def _norm(t):
    meta = t.get("metadata") if isinstance(t.get("metadata"), dict) else {}
    return {"id": str(t.get("id", "")), "subject": str(t.get("subject", "")), "status": str(t.get("status", "pending")),
            "owner": str(t.get("owner") or ""), "blockedBy": [str(b) for b in (t.get("blockedBy") or [])],
            "tier": _tier(t), "outcome": _str(meta, "outcome"), "answeredAt": _str(meta.get("queue"), "answeredAt"),
            "planPath": _str(meta, "plan")}
```

In `_finish`, replace the `out.append(...)` with:

```python
        out.append({"id": t["id"], "subject": t["subject"], "status": st, "owner": t["owner"], "state": "",
                    "tier": t["tier"], "blockedBy": t["blockedBy"], "outcome": t.get("outcome", ""),
                    "answeredAt": t.get("answeredAt", ""), "planPath": t.get("planPath", "")})
```

In the module docstring, replace the `view(...)` line with:

```
view(session, root, home, state_dir, tmux) -> {"name", "active", "tasks": [{"id","subject","status","owner","state","tier","blockedBy",
  "outcome","answeredAt","planPath"}]}  (the last three: metadata.outcome, metadata.queue.answeredAt, metadata.plan, else "")
```

- [ ] **Step 4: Run it.** Same command → `Ran 45 tests … OK`.

- [ ] **Step 5: Commit.** `git add board/planview.py board/tests/test_planview.py && git commit -m "feat(planview): tasks carry outcome, answeredAt and plan path"` (with your harness's trailer).

```json:metadata
{"files": ["board/planview.py", "board/tests/test_planview.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_planview.py'", "acceptanceCriteria": ["outcome/answeredAt/planPath equal the metadata strings", "missing or malformed metadata gives empty strings", "rest of test_planview passes unchanged"], "modelTier": "mechanical"}
```

---

### Task 2: taskwin_state keeps `ui`, writes the journal

**Goal:** `taskwin_state.update` keeps `st["ui"]` across a lead change. With `journal=<path>` it appends a `task_done` or `queue_outcome` line for each task that turns completed while watched, deduped and capped.

**Files:**
- Modify: `board/taskwin_state.py`
- Test: `board/tests/test_taskwin_state.py` (append)

**Acceptance Criteria:**
- [ ] After a lead change, `st["ui"]` is the same dict and the timing is reset (`since` is the new tick).
- [ ] A task completed at first sight is not journaled. A pending → completed transition writes exactly one line with the Global Constraints shape.
- [ ] A queue item writes `queue_outcome` with `spec` = the first word after `Plan & run: ` (`#part` kept), its `outcome`, and `plan` = the stem of `planPath` when set.
- [ ] The same completion seen again under a second lead is not appended again (dedupe against the last 500 lines).
- [ ] At 5000 lines plus one append, the file holds the newest 5000 and no `.tmp` is left.
- [ ] An unwritable journal path and malformed journal lines raise nothing.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin_state.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to `board/tests/test_taskwin_state.py`, before its `if __name__` block if it has one, else at the end:

```python
def Q(i, s, subject="Plan & run: docs/superpowers/specs/a-design.md", outcome="", plan=""):
    return {"id": str(i), "status": s, "subject": subject, "outcome": outcome, "planPath": plan, "owner": "", "tier": ""}


def P(i, s, subject="Task 1: x", owner="ann", tier="mechanical"):
    return {"id": str(i), "status": s, "subject": subject, "owner": owner, "tier": tier}


class UiKeptTest(unittest.TestCase):
    def test_ui_kept_across_lead_change(self):
        st = ts.update({}, "L1", [T(1, "pending")], 100.0)
        st["ui"] = {"view": "history", "filter": "active"}
        st = ts.update(st, "L2", [T(1, "pending")], 101.0)
        self.assertEqual(st["lead"], "L2")
        self.assertEqual(st["ui"], {"view": "history", "filter": "active"})
        self.assertEqual(list(st["tasks"]), ["1"])     # the rest was reset: task 1 seen fresh at 101
        self.assertEqual(st["tasks"]["1"]["since"], 101.0)


class JournalTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.state = Path(td.name)
        self.j = ts.journal_path(self.state, "grp")

    def lines(self):
        return [json.loads(l) for l in self.j.read_text().splitlines()] if self.j.exists() else []

    def test_journal_path_uses_project_key(self):
        self.assertEqual(ts.journal_path("/s", "agent board"), Path("/s/taskwin/agent_board.history.jsonl"))

    def test_task_done_on_transition_only(self):
        st = ts.update({}, "L", [P(1, "in_progress"), P(2, "completed")], 100.0, journal=self.j, plan="2026-11-21-x")
        self.assertEqual(self.lines(), [])              # 2 was already completed at first sight: no back-fill
        ts.update(st, "L", [P(1, "completed"), P(2, "completed")], 160.0, journal=self.j, plan="2026-11-21-x")
        self.assertEqual(self.lines(), [{"kind": "task_done", "at": 160.0, "plan": "2026-11-21-x", "id": "1",
                                         "subject": "Task 1: x", "owner": "ann", "tier": "mechanical"}])

    def test_queue_outcome_line(self):
        st = ts.update({}, "L", [Q(1, "in_progress")], 100.0, journal=self.j)
        ts.update(st, "L", [Q(1, "completed", subject="Plan & run: docs/superpowers/specs/a-design.md#part-1 (x)",
                              outcome="merged abc1234", plan="docs/superpowers/plans/2026-11-21-a.md")],
                  160.0, journal=self.j)
        self.assertEqual(self.lines(), [{"kind": "queue_outcome", "at": 160.0,
                                         "spec": "docs/superpowers/specs/a-design.md#part-1",
                                         "outcome": "merged abc1234", "plan": "2026-11-21-a"}])

    def test_dedupe_against_recent_lines(self):
        # a relay re-reads the same list under a new lead: the same completion is journaled once
        for lead in ("L1", "L2"):
            st = ts.update({}, lead, [P(1, "in_progress")], 100.0, journal=self.j, plan="p")
            ts.update(st, lead, [P(1, "completed")], 160.0, journal=self.j, plan="p")
        self.assertEqual(len(self.lines()), 1)

    def test_cap_keeps_newest_lines(self):
        self.j.parent.mkdir(parents=True)
        self.j.write_text("".join(json.dumps({"kind": "task_done", "plan": "old", "id": str(i), "subject": "s"}) + "\n"
                                  for i in range(ts.JOURNAL_CAP)))
        ts.append_journal(self.j, [{"kind": "task_done", "plan": "new", "id": "1", "subject": "s"}])
        got = self.lines()
        self.assertEqual(len(got), ts.JOURNAL_CAP)
        self.assertEqual((got[0]["id"], got[-1]["plan"]), ("1", "new"))   # line 0 of the old file dropped
        self.assertFalse(self.j.with_name(self.j.name + ".tmp").exists())

    def test_io_error_is_ignored(self):
        bad = self.state / "file"
        bad.write_text("x")
        ts.append_journal(bad / "sub" / "j.jsonl", [{"kind": "task_done", "id": "1"}])   # parent is a file: no raise

    def test_malformed_lines_skipped(self):
        self.j.parent.mkdir(parents=True)
        self.j.write_text("{not json\n[1]\n")
        ts.append_journal(self.j, [{"kind": "task_done", "plan": "p", "id": "1", "subject": "s"}])
        self.assertEqual(len(self.j.read_text().splitlines()), 3)
```

Mutations: delete the `ui` save/restore in `update` → `test_ui_kept_across_lead_change` fails. Skip the `seen` check → `test_dedupe_against_recent_lines` fails (2 lines). Drop the `len(lines) + len(new) > JOURNAL_CAP` rewrite → `test_cap_keeps_newest_lines` fails (5001 lines).

- [ ] **Step 2: Run them.** Verify command → errors: `AttributeError: module 'taskwin_state' has no attribute 'journal_path'` and `TypeError: update() got an unexpected keyword argument 'journal'`.

- [ ] **Step 3: Implement.** Replace `board/taskwin_state.py` with:

```python
#!/usr/bin/env python3
"""taskwin_state: per-session timing and celebration state for the tasks window (board/taskwin.py).

State (JSON at path_for(state_dir, session)):
  {"lead": <lead session id>, "tasks": {id: {"status", "since", "started", "done"}},
   "events": [{"kind": "done", "id", "at"} | {"kind": "plan_done", "at"}], "all_done": bool | None}
   "ui": {...} (taskwin_ui; kept across a lead change)}
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
            except (ValueError, AttributeError):
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
```

- [ ] **Step 4: Run them.** Verify command → `OK`. Also run `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'` → `OK` (taskwin's callers pass no journal yet).

- [ ] **Step 5: Commit.** `git add board/taskwin_state.py board/tests/test_taskwin_state.py && git commit -m "feat(taskwin): history journal and ui kept across a lead change"`.

```json:metadata
{"files": ["board/taskwin_state.py", "board/tests/test_taskwin_state.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin_state.py'", "acceptanceCriteria": ["ui kept across a lead change, timing reset", "journal on transition only, not first sight", "queue_outcome with spec, outcome, plan stem", "dedupe against last 500 lines", "cap 5000 newest, no .tmp left", "I/O errors and malformed lines ignored"], "modelTier": "mechanical"}
```

---

### Task 3: `taskwin_ui` keys and `taskwin_views` rows

**Goal:** Two pure modules. `taskwin_ui` decodes terminal input into keys and has `handle_key(ui, key, model) -> ui` for every key in the spec's table. `taskwin_views` builds each view's rows (`model`), applies the plan filter and the done collapse, and builds queue labels.

**Files:**
- Create: `board/taskwin_ui.py`
- Create: `board/taskwin_views.py`
- Test: `board/tests/test_taskwin_ui.py`

**Acceptance Criteria:**
- [ ] `decode` maps `ESC [ A`/`ESC [ B` (and SS3 `ESC O A/B`) to `up`/`down`, Tab to `tab`, CR/LF to `enter`, and drops a lone ESC and every other escape sequence.
- [ ] Default view: `queue` when any subject starts with `Plan & run:`, else `plan`. `normalize` repairs every invalid field.
- [ ] Tab cycles queue → plan → history → queue. `1` `2` `3` pick a view. `q` goes to the queue view. `j`/`down` and `k`/`up` move the current view's cursor, clamped to its rows.
- [ ] Enter on the running queue item switches to plan. Enter on a completed plan task or on `p:done` toggles `p:done`. Enter on a history row toggles that row. Enter elsewhere changes nothing.
- [ ] `f` cycles all → hide_done → active → all. `c` collapses all of the view's finished rows, or expands them all when every one is collapsed. `?` toggles help.
- [ ] `handle_key` never mutates its argument. An unknown key changes nothing.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin_ui.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** as `board/tests/test_taskwin_ui.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskwin_ui as tu  # noqa: E402
import taskwin_views as tv  # noqa: E402


def task(i, subject, status):
    return {"id": str(i), "subject": subject, "status": status, "owner": "", "tier": "", "blockedBy": []}


QUEUE = [task(1, "Plan & run: docs/superpowers/specs/a-design.md", "completed"),
         task(2, "Plan & run: docs/superpowers/specs/b-design.md", "in_progress"),
         task(3, "Task 1: one", "completed"), task(4, "Task 2: two", "completed"),
         task(5, "Task 3: three", "in_progress"), task(6, "Task 4: four", "blocked"), task(7, "Task 5: five", "pending")]
HIST = [{"key": "plan:x"}, {"key": "plan:y"}]


def press(keys, tasks=QUEUE, ui=None, history=HIST):
    ui = tu.normalize(ui, tasks)
    for k in keys:
        ui = tu.handle_key(ui, k, tv.model(tasks, ui, history))
    return ui


class DecodeTest(unittest.TestCase):
    def test_keys_and_arrows(self):
        self.assertEqual(tu.decode("3j\x1b[Bk\x1b[A\t\r\nfc?q"),
                         ["3", "j", "down", "k", "up", "tab", "enter", "enter", "f", "c", "?", "q"])

    def test_lone_esc_and_other_sequences_ignored(self):
        self.assertEqual(tu.decode("\x1b"), [])
        self.assertEqual(tu.decode("\x1bj"), ["j"])                  # ESC then j: the ESC alone is dropped
        self.assertEqual(tu.decode("\x1b[C\x1b[1;5A\x1bOB2"), ["down", "2"])   # right, ctrl-up dropped; SS3 down kept


class DefaultTest(unittest.TestCase):
    def test_default_view_queue_with_plan_and_run(self):
        self.assertEqual(tu.default_ui(QUEUE)["view"], "queue")

    def test_default_view_plan_without(self):
        self.assertEqual(tu.default_ui([task(1, "Task 1: x", "pending")])["view"], "plan")
        self.assertEqual(tu.default_ui([])["view"], "plan")

    def test_normalize_repairs_bad_fields(self):
        ui = tu.normalize({"view": "nope", "cursor": {"plan": -3, "queue": "x"}, "filter": 7,
                           "collapsed": {"a": True, "b": "yes"}, "help": 1}, QUEUE)
        self.assertEqual(ui, {"view": "queue", "cursor": {"queue": 0, "plan": 0, "history": 0}, "filter": "all",
                              "collapsed": {"a": True}, "help": False})


class KeyTest(unittest.TestCase):
    def test_tab_cycles_views(self):
        self.assertEqual([press(["tab"] * n)["view"] for n in range(4)], ["queue", "plan", "history", "queue"])

    def test_digits_and_q(self):
        self.assertEqual(press(["3"])["view"], "history")
        self.assertEqual(press(["2"])["view"], "plan")
        self.assertEqual(press(["3", "1"])["view"], "queue")
        self.assertEqual(press(["3", "q"])["view"], "queue")

    def test_cursor_clamped_to_rows(self):
        self.assertEqual(press(["j"] * 5)["cursor"]["queue"], 1)            # 2 queue rows
        self.assertEqual(press(["j", "down", "k", "up", "k"])["cursor"]["queue"], 0)
        self.assertEqual(press(["2"] + ["j"] * 9)["cursor"]["plan"], 4)     # 5 plan tasks

    def test_cursor_per_view(self):
        ui = press(["j", "2", "j", "j"])
        self.assertEqual((ui["cursor"]["queue"], ui["cursor"]["plan"]), (1, 2))

    def test_enter_on_running_queue_item_opens_plan(self):
        self.assertEqual(press(["j", "enter"])["view"], "plan")
        self.assertEqual(press(["enter"])["view"], "queue")                 # row 0 is finished: nothing to open

    def test_enter_on_done_task_collapses_done(self):
        ui = press(["2", "enter"])                                          # row 0 = task 3, completed
        self.assertTrue(ui["collapsed"][tv.DONE_KEY])
        self.assertEqual(tv.model(QUEUE, ui)["rows"]["plan"], ["p:done", "p:5", "p:6", "p:7"])
        ui = press(["enter"], ui=ui)                                        # row 0 = the done line: expand
        self.assertFalse(ui["collapsed"][tv.DONE_KEY])

    def test_enter_on_open_task_does_nothing(self):
        ui = press(["2", "j", "j", "enter"])                                # task 5, in progress
        self.assertEqual(ui["collapsed"], {})

    def test_enter_toggles_history_row(self):
        ui = press(["3", "enter"])
        self.assertFalse(tu.is_collapsed(ui, "h:plan:x"))                   # history rows start collapsed
        self.assertTrue(tu.is_collapsed(ui, "h:plan:y"))

    def test_filter_cycle(self):
        self.assertEqual([press(["f"] * n)["filter"] for n in range(4)], ["all", "hide_done", "active", "all"])

    def test_filter_rows(self):
        self.assertEqual(tv.model(QUEUE, press(["f"]))["rows"]["plan"], ["p:5", "p:6", "p:7"])
        self.assertEqual(tv.model(QUEUE, press(["f", "f"]))["rows"]["plan"], ["p:5", "p:6"])

    def test_collapse_all_toggle(self):
        ui = press(["3", "c"])                                              # history: all collapsed -> expand all
        self.assertEqual([tu.is_collapsed(ui, k) for k in ("h:plan:x", "h:plan:y")], [False, False])
        ui = press(["c"], ui=ui)
        self.assertEqual([tu.is_collapsed(ui, k) for k in ("h:plan:x", "h:plan:y")], [True, True])
        ui = press(["enter", "c"], ui=ui)                                   # one open, one closed -> collapse all
        self.assertEqual([tu.is_collapsed(ui, k) for k in ("h:plan:x", "h:plan:y")], [True, True])
        ui = press(["2", "c"], ui=ui)
        self.assertTrue(tu.is_collapsed(ui, tv.DONE_KEY))
        self.assertFalse(tu.is_collapsed(press(["c"], ui=ui), tv.DONE_KEY))

    def test_help_toggle(self):
        self.assertEqual([press(["?"] * n)["help"] for n in range(3)], [False, True, False])

    def test_unknown_key_changes_nothing(self):
        ui = tu.normalize(None, QUEUE)
        self.assertEqual(press(["x", "\x00", "enter"], tasks=[], ui=ui, history=[]), ui)

    def test_argument_not_mutated(self):
        ui = tu.normalize(None, QUEUE)
        before = repr(ui)
        tu.handle_key(ui, "j", tv.model(QUEUE, ui))
        self.assertEqual(repr(ui), before)


class QueueLabelTest(unittest.TestCase):
    def test_title_fragment_note_and_fallback(self):
        t = {"docs/s/a-design.md": "Alpha", "docs/s/b-design.md#part-1": "Beta"}
        self.assertEqual(tv.queue_label("Plan & run: docs/s/a-design.md", t), "Alpha")
        self.assertEqual(tv.queue_label("Plan & run: docs/s/b-design.md#part-1", t), "Beta #part-1")
        self.assertEqual(tv.queue_label("Plan & run: docs/s/c-design.md (§4-5 only)", t), "docs/s/c-design.md (§4-5 only)")
        self.assertEqual(tv.queue_label("Plan & run: docs/s/a-design.md  (x)", t), "Alpha (x)")


if __name__ == "__main__":
    unittest.main()
```

Mutations: make `is_collapsed` default to `False` for `h:` keys → `test_enter_toggles_history_row` fails. Remove the `fold = not all(...)` check (always fold) → `test_collapse_all_toggle` fails. Remove `clamp` from `handle_key` → `test_cursor_clamped_to_rows` fails.

- [ ] **Step 2: Run them.** Verify command → `ModuleNotFoundError: No module named 'taskwin_ui'`.

- [ ] **Step 3: Implement** `board/taskwin_ui.py`:

```python
#!/usr/bin/env python3
"""taskwin_ui: key handling for the tasks window (board/taskwin.py watch). Pure: no I/O.

ui = {"view": "queue"|"plan"|"history", "cursor": {view: int}, "filter": "all"|"hide_done"|"active",
      "collapsed": {row key: bool}, "help": bool}
model = taskwin_views.model(...): {"rows": {view: [row key]}, "toggle": {view: {row key: collapse key | OPEN_PLAN}},
         "finished": {view: [collapse key]}}
decode(text) -> [key]; handle_key(ui, key, model) -> new ui (the argument is not changed).
"""
import copy

VIEWS = ("queue", "plan", "history")
FILTERS = ("all", "hide_done", "active")
QUEUE_PREFIX = "Plan & run: "
OPEN_PLAN = "@plan"                      # toggle target of the running queue row: Enter switches to the plan view
_ARROWS = {"A": "up", "B": "down"}


def decode(text):
    """Keys from one read of the terminal: ESC [ A/B -> up/down, any other ESC sequence and a lone ESC dropped,
    Tab -> "tab", CR/LF -> "enter", every other character as itself."""
    keys, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\x1b":
            if text[i + 1:i + 2] in ("[", "O"):
                j = i + 2
                while j < len(text) and not ("@" <= text[j] <= "~"):
                    j += 1                   # parameter bytes up to the final byte
                if j < len(text) and text[j] in _ARROWS and j == i + 2:
                    keys.append(_ARROWS[text[j]])
                i = j + 1
            else:
                i += 1
            continue
        keys.append("tab" if c == "\t" else "enter" if c in "\r\n" else c)
        i += 1
    return keys


def is_collapsed(ui, key):
    """History rows start collapsed; every other row starts expanded."""
    v = (ui.get("collapsed") or {}).get(key)
    return v if isinstance(v, bool) else key.startswith("h:")


def default_ui(tasks):
    queue = any(str(t.get("subject", "")).startswith(QUEUE_PREFIX) for t in tasks or [])
    return {"view": "queue" if queue else "plan", "cursor": {v: 0 for v in VIEWS}, "filter": "all",
            "collapsed": {}, "help": False}


def normalize(ui, tasks):
    """A copy of `ui` with every missing or invalid field taken from default_ui(tasks)."""
    d = default_ui(tasks)
    if not isinstance(ui, dict):
        return d
    out = copy.deepcopy(ui)
    if out.get("view") not in VIEWS:
        out["view"] = d["view"]
    if out.get("filter") not in FILTERS:
        out["filter"] = "all"
    cur = out.get("cursor") if isinstance(out.get("cursor"), dict) else {}
    out["cursor"] = {v: cur[v] if isinstance(cur.get(v), int) and cur[v] >= 0 else 0 for v in VIEWS}
    col = out.get("collapsed") if isinstance(out.get("collapsed"), dict) else {}
    out["collapsed"] = {str(k): v for k, v in col.items() if isinstance(v, bool)}
    out["help"] = out.get("help") is True
    return out


def clamp(ui, model):
    """Each view's cursor within its rows (0 when it has none)."""
    for v in VIEWS:
        n = len(((model or {}).get("rows") or {}).get(v) or [])
        ui["cursor"][v] = max(0, min(ui["cursor"].get(v, 0), n - 1))
    return ui


def handle_key(ui, key, model):
    ui = normalize(ui, [])
    v = ui["view"]
    rows = ((model or {}).get("rows") or {}).get(v) or []
    cur = ui["cursor"][v]
    if key == "tab":
        ui["view"] = VIEWS[(VIEWS.index(v) + 1) % len(VIEWS)]
    elif key in ("1", "2", "3"):
        ui["view"] = VIEWS[int(key) - 1]
    elif key == "q":
        ui["view"] = "queue"
    elif key in ("j", "down"):
        ui["cursor"][v] = cur + 1
    elif key in ("k", "up"):
        ui["cursor"][v] = cur - 1
    elif key == "enter" and rows:
        target = (((model or {}).get("toggle") or {}).get(v) or {}).get(rows[min(cur, len(rows) - 1)])
        if target == OPEN_PLAN:
            ui["view"] = "plan"
        elif target:
            ui["collapsed"][target] = not is_collapsed(ui, target)
    elif key == "f":
        ui["filter"] = FILTERS[(FILTERS.index(ui["filter"]) + 1) % len(FILTERS)]
    elif key == "c":
        keys = ((model or {}).get("finished") or {}).get(v) or []
        if keys:
            fold = not all(is_collapsed(ui, k) for k in keys)
            for k in keys:
                ui["collapsed"][k] = fold
    elif key == "?":
        ui["help"] = not ui["help"]
    return clamp(ui, model)
```

and `board/taskwin_views.py` (`queue_label` is used by the queue screen in Task 5):

```python
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
```

- [ ] **Step 4: Run them.** Verify command → `Ran 20 tests … OK`.

- [ ] **Step 5: Commit.** `git add board/taskwin_ui.py board/taskwin_views.py board/tests/test_taskwin_ui.py && git commit -m "feat(taskwin): key handling and per-view rows"`.

```json:metadata
{"files": ["board/taskwin_ui.py", "board/taskwin_views.py", "board/tests/test_taskwin_ui.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin_ui.py'", "acceptanceCriteria": ["decode arrows, tab, enter; lone ESC and other sequences dropped", "default view queue with Plan & run else plan; normalize repairs fields", "tab/1/2/3/q views; j/k/arrows clamp per view", "enter: running queue item opens plan; done rows toggle p:done; history rows toggle", "f cycles filters; c folds or unfolds finished rows; ? toggles help", "handle_key pure; unknown key no-op"], "modelTier": "mechanical"}
```

---

### Task 4: `taskwin_hist`: titles, journal, ledgers, reports

**Goal:** One module reads everything the window shows besides the task list. It parses with an mtime cache, skips unparseable files, and merges journal, ledger and report sources into history entries, newest day first.

**Files:**
- Create: `board/taskwin_hist.py`
- Test: `board/tests/test_taskwin_hist.py`

**Acceptance Criteria:**
- [ ] Against the real `docs/superpowers/ledgers/2026-11-09-remote-access/progress.md`: plan, stem, spec, branch `feat/remote-access`, day `2026-11-09`, dir.
- [ ] Every real ledger whose line 1 is `# SDD ledger — plan: …` parses (≥ 40, count equal).
- [ ] Against the real `docs/superpowers/reports/2026-11-05-queue.md`: ≥ 11 outcome rows. The first is `queue-followups`, `merged 5a90ba9`, with its ledger folder. One row starts `failed`. Rows outside `## Outcomes` are ignored.
- [ ] A report row links to its ledger's entry: `plan:2026-11-05-queue-followups` has day `2026-11-05` and outcome `merged 5a90ba9`.
- [ ] Entries merge the sources: journal tasks group by plan, a `queue_outcome` attaches by `plan` then by spec, and spec-only entries come from reports and outcomes with no plan. The order is newest day first, then newest activity.
- [ ] Malformed journal lines are skipped. A missing root or journal gives `[]`. A changed file is re-read (cache keyed by mtime).
- [ ] `queue_report` names `docs/superpowers/reports/<earliest answeredAt date>-queue.md` only when it exists.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin_hist.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** as `board/tests/test_taskwin_hist.py`:

```python
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskwin_hist as th  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


class RealFilesTest(unittest.TestCase):
    """Parsers against the real ledgers and queue report of this repo (read-only)."""

    def test_real_ledger(self):
        led = next(l for l in th.ledgers(REPO) if l["stem"] == "2026-11-09-remote-access")
        self.assertEqual(led, {"plan": "docs/superpowers/plans/2026-11-09-remote-access.md",
                               "stem": "2026-11-09-remote-access",
                               "spec": "docs/superpowers/specs/2026-11-09-remote-access-design.md",
                               "branch": "feat/remote-access", "day": "2026-11-09",
                               "dir": "docs/superpowers/ledgers/2026-11-09-remote-access/"})

    def test_every_real_ledger_with_a_plan_line_parses(self):
        files = sorted((REPO / th.LEDGERS).glob("*/progress.md"))
        want = [f for f in files if f.read_text(encoding="utf-8").startswith("# SDD ledger — plan: ")]
        self.assertGreaterEqual(len(want), 40)
        self.assertEqual(len(th.ledgers(REPO)), len(want))

    def test_real_report_outcomes(self):
        rows = [r for r in th.report_rows(REPO) if r["day"] == "2026-11-05"]
        self.assertGreaterEqual(len(rows), 11)
        self.assertEqual(rows[0], {"spec": "docs/superpowers/specs/2026-11-05-queue-followups-design.md",
                                   "outcome": "merged 5a90ba9",
                                   "ledger": "docs/superpowers/ledgers/2026-11-05-queue-followups/",
                                   "day": "2026-11-05"})
        self.assertTrue(any(r["outcome"].startswith("failed") for r in rows))

    def test_real_entries_link_report_to_ledger(self):
        e = next(x for x in th.entries(REPO, None) if x["key"] == "plan:2026-11-05-queue-followups")
        self.assertEqual((e["day"], e["outcome"]), ("2026-11-05", "merged 5a90ba9"))

    def test_real_spec_title(self):
        self.assertEqual(th.spec_title(REPO, "docs/superpowers/specs/2026-11-10-interactive-tasks-window-design.md#part-1"),
                         "Interactive tasks window: queue overview, filters, history")


class FakeRootTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        (self.root / th.LEDGERS / "2026-11-20-a").mkdir(parents=True)
        (self.root / th.LEDGERS / "2026-11-20-a" / "progress.md").write_text(
            "# SDD ledger — plan: docs/superpowers/plans/2026-11-20-a.md\nPreflight scan:\nSpec: docs/superpowers/specs/a-design.md\n")
        (self.root / th.LEDGERS / "2026-11-19-bad").mkdir(parents=True)
        (self.root / th.LEDGERS / "2026-11-19-bad" / "progress.md").write_text("# something else\n")
        (self.root / th.REPORTS).mkdir(parents=True)
        (self.root / th.REPORTS / "2026-11-20-queue.md").write_text(
            "# r\n## Outcomes\n\n| # | Spec | Outcome | Ledger |\n| --- | --- | --- | --- |\n"
            "| 1 | `docs/superpowers/specs/a-design.md` | merged `aaa1111` | `docs/superpowers/ledgers/2026-11-20-a/` |\n"
            "| 2 | `docs/superpowers/specs/c-design.md` (note) | failed — x | |\n| garbage |\n## Next\n| 9 | x | y | z |\n")
        self.j = self.root / "j.jsonl"
        self.t1 = time.mktime((2026, 11, 20, 12, 0, 0, 0, 0, -1))   # local noon: the same day in every TZ
        self.t2 = time.mktime((2026, 11, 21, 12, 0, 0, 0, 0, -1))
        self.j.write_text("\n".join([
            json.dumps({"kind": "task_done", "at": self.t1, "plan": "2026-11-20-a", "id": "1", "subject": "A1",
                        "owner": "o", "tier": "mechanical"}),
            "{bad", json.dumps([1]), json.dumps({"kind": "task_done", "plan": "x"}),       # skipped
            json.dumps({"kind": "task_done", "at": self.t2, "plan": "2026-11-21-b", "id": "2", "subject": "B2",
                        "owner": "", "tier": ""}),
            json.dumps({"kind": "queue_outcome", "at": self.t2, "spec": "docs/superpowers/specs/b-design.md",
                        "outcome": "kept spec-b", "plan": "2026-11-21-b"}),
        ]) + "\n")

    def test_bad_ledger_skipped_and_spec_from_any_head_line(self):
        self.assertEqual([(l["stem"], l["spec"]) for l in th.ledgers(self.root)],
                         [("2026-11-20-a", "docs/superpowers/specs/a-design.md")])

    def test_report_rows_only_from_outcomes_table(self):
        self.assertEqual([(r["spec"], r["outcome"], r["ledger"]) for r in th.report_rows(self.root)],
                         [("docs/superpowers/specs/a-design.md", "merged aaa1111", "docs/superpowers/ledgers/2026-11-20-a/"),
                          ("docs/superpowers/specs/c-design.md", "failed — x", "")])

    def test_entries_merge_sources_newest_first(self):
        es = th.entries(self.root, self.j)
        self.assertEqual([e["key"] for e in es],
                         ["plan:2026-11-21-b", "plan:2026-11-20-a", "spec:docs/superpowers/specs/c-design.md"])
        b = next(e for e in es if e["key"] == "plan:2026-11-21-b")
        self.assertEqual((b["day"], b["outcome"], [t["id"] for t in b["tasks"]]), ("2026-11-21", "kept spec-b", ["2"]))
        a = next(e for e in es if e["key"] == "plan:2026-11-20-a")
        self.assertEqual((a["outcome"], a["ledger"], len(a["tasks"])), ("merged aaa1111", "docs/superpowers/ledgers/2026-11-20-a/", 1))
        c = next(e for e in es if e["key"].startswith("spec:"))
        self.assertEqual((c["day"], c["outcome"], c["tasks"]), ("2026-11-20", "failed — x", []))
        days = [e["day"] for e in es]
        self.assertEqual(days, sorted(days, reverse=True))

    def test_missing_root_and_journal(self):
        self.assertEqual(th.entries(self.root / "nope", self.root / "nope.jsonl"), [])
        self.assertEqual(th.read_journal(None), [])

    def test_cache_rereads_after_change(self):
        self.assertEqual(len(th.read_journal(self.j)), 3)
        with open(self.j, "a") as f:
            f.write(json.dumps({"kind": "task_done", "at": self.t2 + 1, "plan": "p", "id": "9", "subject": "s"}) + "\n")
        st = self.j.stat()
        os.utime(self.j, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        self.assertEqual(len(th.read_journal(self.j)), 4)

    def test_queue_report(self):
        q = [{"answeredAt": "2026-11-21T01:00:00Z"}, {"answeredAt": "2026-11-20T23:00:00Z"}, {"answeredAt": ""}]
        self.assertEqual(th.queue_report(self.root, q), "docs/superpowers/reports/2026-11-20-queue.md")
        self.assertEqual(th.queue_report(self.root, q[:1]), "")
        self.assertEqual(th.queue_report(self.root, []), "")


if __name__ == "__main__":
    unittest.main()
```

Mutations: drop the `if hit and hit[0] == m` mtime comparison (always return the cached value) → `test_cache_rereads_after_change` fails. Remove the `inside = line.strip() == "## Outcomes"` reset → `test_report_rows_only_from_outcomes_table` fails (row `9` from `## Next`).

- [ ] **Step 2: Run them.** Verify command → `ModuleNotFoundError: No module named 'taskwin_hist'`.

- [ ] **Step 3: Implement** `board/taskwin_hist.py`:

```python
#!/usr/bin/env python3
"""taskwin_hist: what the tasks window reads besides the task list: spec titles, the queue's morning report, the
history journal (taskwin_state.append_journal), past SDD ledgers and queue reports. Every parse is cached by
(path, mtime); unreadable or unparseable files are skipped. Never raises on I/O.

entries(root, journal) -> [{"key", "day", "name", "spec", "outcome", "tasks": [task_done lines], "ledger"}],
newest day first; within a day, newest activity first.
"""
import json
import re
import time
from pathlib import Path

LEDGERS = Path("docs/superpowers/ledgers")
REPORTS = Path("docs/superpowers/reports")
_PLAN = re.compile(r"^# SDD ledger — plan: (\S+)")
_SPEC = re.compile(r"\bSpec: (\S+?\.md)\b")
_BRANCH = re.compile(r"\bbranch (\S+)")
_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_TICK = re.compile(r"`([^`]+)`")
_cache = {}


def _cached(path, parse):
    try:
        m = Path(path).stat().st_mtime_ns
    except OSError:
        return None
    hit = _cache.get((str(path), parse.__name__))
    if hit and hit[0] == m:
        return hit[1]
    try:
        v = parse(Path(path))
    except (OSError, ValueError, UnicodeDecodeError):
        v = None
    _cache[(str(path), parse.__name__)] = (m, v)
    return v


def day_of(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def hm(ts):
    return time.strftime("%H:%M", time.localtime(ts))


def _title(p):
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if line.startswith("# "):
                return line[2:].strip()
            if i > 40:
                break
    return None


def spec_title(root, spec):
    """First `# ` heading of the spec file (`#part` dropped), else None."""
    return _cached(Path(root) / spec.split("#")[0], _title) if spec else None


def _ledger(p):
    with open(p, encoding="utf-8") as f:
        head = [f.readline() for _ in range(6)]
    m = _PLAN.match(head[0])
    day = _DAY.match(p.parent.name)
    if not m or not day:
        return None
    rest = " ".join(head[1:])
    spec, branch = _SPEC.search(rest), _BRANCH.search(rest)
    plan = m.group(1)
    stem = Path(plan).name[:-3] if plan.endswith(".md") else Path(plan).name
    return {"plan": plan, "stem": stem, "spec": spec.group(1) if spec else "",
            "branch": branch.group(1) if branch else "", "day": day.group(1),
            "dir": str(LEDGERS / p.parent.name) + "/"}


def ledgers(root):
    out = []
    for p in sorted((Path(root) / LEDGERS).glob("*/progress.md")):
        v = _cached(p, _ledger)
        if v:
            out.append(v)
    return out


def _report(p):
    day = _DAY.match(p.name)
    rows, inside = [], False
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Outcomes"
            continue
        if not inside or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("#", "") or set(cells[0]) <= set("-: "):
            continue
        spec = _TICK.search(cells[1])
        led = _TICK.search(cells[3])
        rows.append({"spec": spec.group(1) if spec else (cells[1].split() or [""])[0],
                     "outcome": cells[2].replace("`", ""), "ledger": led.group(1).rstrip("/") + "/" if led else "",
                     "day": day.group(1) if day else ""})
    return rows


def report_rows(root):
    out = []
    for p in sorted((Path(root) / REPORTS).glob("*-queue.md")):
        out.extend(_cached(p, _report) or [])
    return out


def queue_report(root, queue_tasks):
    """docs/superpowers/reports/<first answeredAt date>-queue.md when it exists, else ''."""
    days = sorted(t["answeredAt"][:10] for t in queue_tasks if _DAY.match(t.get("answeredAt") or ""))
    if not days:
        return ""
    rel = REPORTS / f"{days[0]}-queue.md"
    return str(rel) if (Path(root) / rel).is_file() else ""


def _journal(p):
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("kind") in ("task_done", "queue_outcome") \
                and isinstance(e.get("at"), (int, float)):
            out.append(e)
    return out


def read_journal(path):
    return (_cached(path, _journal) or []) if path else []


def entries(root, journal):
    """History rows from the journal, ledgers and queue reports (see the module docstring)."""
    lines = read_journal(journal)
    by_key, order = {}, []

    def get(key, name):
        if key not in by_key:
            by_key[key] = {"key": key, "day": "", "name": name, "spec": "", "outcome": "", "tasks": [],
                           "ledger": "", "_at": 0}
            order.append(key)
        return by_key[key]

    for led in ledgers(root):
        e = get("plan:" + led["stem"], led["stem"])
        e.update(spec=led["spec"], ledger=led["dir"], day=led["day"])
    for j in lines:
        if j["kind"] == "task_done":
            e = get("plan:" + (j.get("plan") or ""), j.get("plan") or "(no plan)")
            e["tasks"].append(j)
            if j["at"] >= e["_at"]:
                e["_at"], e["day"] = j["at"], day_of(j["at"])
    for j in lines:
        if j["kind"] != "queue_outcome":
            continue
        e = by_key.get("plan:" + j["plan"]) if j.get("plan") else None
        e = e or next((x for x in by_key.values() if x["spec"] and x["spec"] == j.get("spec")), None)
        if e is None:
            e = get("spec:" + str(j.get("spec")), str(j.get("spec")))
            e["spec"] = str(j.get("spec"))
        if j.get("outcome"):
            e["outcome"] = j["outcome"]
        if not e["day"]:
            e["day"], e["_at"] = day_of(j["at"]), j["at"]
    for r in report_rows(root):
        e = next((x for x in by_key.values() if (r["ledger"] and x["ledger"] == r["ledger"])
                  or (r["spec"] and x["spec"] == r["spec"])), None)
        if e is None:
            e = get("spec:" + r["spec"], r["spec"])
            e.update(spec=r["spec"], day=r["day"])
        if not e["outcome"]:
            e["outcome"] = r["outcome"]
    out = [by_key[k] for k in order]
    for e in out:
        e["tasks"].sort(key=lambda j: j["at"])
    out.sort(key=lambda e: (e["day"], e["_at"], e["name"]), reverse=True)
    for e in out:
        e.pop("_at", None)
    return out
```

- [ ] **Step 4: Run them.** Run the verify command, then `TZ=Pacific/Kiritimati` and `TZ=Pacific/Pago_Pago` with the same command → `OK` all three times.

- [ ] **Step 5: Commit.** `git add board/taskwin_hist.py board/tests/test_taskwin_hist.py && git commit -m "feat(taskwin): history sources: journal, ledgers, queue reports"`.

```json:metadata
{"files": ["board/taskwin_hist.py", "board/tests/test_taskwin_hist.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin_hist.py'", "acceptanceCriteria": ["real remote-access ledger parsed: plan, spec, branch, day, dir", "every real ledger with a plan line parses (>=40)", "real 2026-11-05 report: >=11 rows, first merged 5a90ba9, one failed", "report row links to ledger entry", "entries merge journal, ledgers, reports newest first", "malformed lines skipped; missing root gives []; mtime cache rereads", "queue_report only when the file exists"], "modelTier": "mechanical"}
```

---

### Task 5: `ui` render path: tabs, help line, queue view

**Goal:** `taskwin.render` gains `ui=None, ctx=None`. With `ui`, it draws the tab header, the chosen view and an optional help line at the bottom. This task builds the queue screen. The plan and history screens follow in Tasks 6 and 7; until then their branches draw the plan view through today's body code and the history view as an empty body.

**Files:**
- Modify: `board/taskwin.py` (render, `_header`, new `_render_ui`, `_tabs`, `_queue_screen`, `_scroll`, `HELP`, module docstring)
- Create: `board/tests/test_taskwin_screens.py`

**Acceptance Criteria:**
- [ ] `ui=None` output is unchanged: `python3 -m unittest discover -s board/tests -p 'test_taskwin.py'` passes without edits.
- [ ] Line 0 starts `[1 queue] 2 plan 3 history  Queue · <ctx report>` (report part only when `ctx["report"]`), and the active tab is bold in colour.
- [ ] Each queue row shows the status glyph, the title (`ctx["titles"][spec]`, `#part` appended when the spec has one, else the spec path, plus any note after the spec word), `HH:MM → HH:MM` (`→ …` while running, `—` with no start), and the outcome verbatim, red when it starts with `failed`.
- [ ] Below the running item when it is not collapsed: `<done>/<total> · <n> running · <n> blocked` over the non-queue tasks, then one `#id subject · owner · duration` line per running non-queue task, each indented four cells (owner segment omitted when empty).
- [ ] No queue items: `no queue` and the hint `2: plan`.
- [ ] The cursor row has the `▸ ` gutter (inverse in colour). The view scrolls to keep the cursor visible.
- [ ] `ui["help"]`: exactly `height` lines, the last one `taskwin.HELP`. Every line stays within `width` cells and the output within `height` lines at 40/80/120 × 5/12/40.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** as `board/tests/test_taskwin_screens.py` (Tasks 6 and 7 add classes to it):

```python
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskwin  # noqa: E402
import taskwin_hist as th  # noqa: E402
import taskwin_ui as tu  # noqa: E402

NOW = time.mktime((2026, 11, 21, 12, 0, 0, 0, 0, -1))
RED256 = "38;5;167"


def task(i, subject, status, blocked_by=(), owner="", tier="", outcome="", answered=""):
    return {"id": str(i), "subject": subject, "status": status, "owner": owner, "state": "", "tier": tier,
            "blockedBy": [str(b) for b in blocked_by], "outcome": outcome, "answeredAt": answered, "planPath": ""}


SA = "docs/superpowers/specs/a-design.md"
QTASKS = [
    task(1, "Plan & run: " + SA, "completed", outcome="merged abc1234", answered="2026-11-21T01:00:00Z"),
    task(2, "Plan & run: docs/superpowers/specs/b-design.md#part-1", "completed", outcome="mr https://gl/x/-/merge_requests/7"),
    task(3, "Plan & run: docs/superpowers/specs/c-design.md (§4-5 only)", "completed", outcome="kept spec-c"),
    task(4, "Plan & run: docs/superpowers/specs/d-design.md", "completed", outcome="failed — residual N1"),
    task(5, "Plan & run: docs/superpowers/specs/e-design.md", "in_progress"),
    task(6, "Plan & run: docs/superpowers/specs/f-design.md", "pending"),
    task(10, "Task 1: one", "completed", owner="ann", tier="mechanical"),
    task(11, "Task 2: two", "in_progress", [10], owner="bob", tier="standard"),
    task(12, "Task 3: three", "blocked", [11]),
    task(13, "Task 4: four", "pending", [10]),
]
QTIMING = {"lead": "L", "events": [], "all_done": False, "tasks": {
    "1": {"status": "completed", "since": NOW - 7200, "started": NOW - 9000, "done": NOW - 7200},
    "5": {"status": "in_progress", "since": NOW - 600, "started": NOW - 600, "done": None},
    "11": {"status": "in_progress", "since": NOW - 720, "started": NOW - 720, "done": None}}}
CTX = {"titles": {SA: "Alpha spec", "docs/superpowers/specs/b-design.md#part-1": "Beta spec"},
       "report": "docs/superpowers/reports/2026-11-21-queue.md", "history": []}


def ui(tasks=QTASKS, **kw):
    return tu.normalize(kw, tasks)


def render(tasks=QTASKS, timing=None, width=120, height=40, color="none", u=None, ctx=None):
    return taskwin.render({"name": "2026-11-21-plan", "active": True, "tasks": tasks},
                          QTIMING if timing is None else timing, width, height, NOW, 0, color,
                          ui=ui(tasks) if u is None else u, ctx=CTX if ctx is None else ctx)


def line_with(out, text):
    return next(l for l in out.split("\n") if text in taskwin.strip(l))


class QueueScreenTest(unittest.TestCase):
    def test_tabs_name_report_in_header(self):
        first = render().split("\n")[0]
        self.assertTrue(first.startswith("[1 queue] 2 plan 3 history  Queue · docs/superpowers/reports/2026-11-21-queue.md"), first)
        self.assertTrue(render(u=ui(view="plan")).split("\n")[0].startswith("1 queue [2 plan] 3 history  2026-11-21-plan"))

    def test_active_tab_bold_in_colour(self):
        self.assertIn("\x1b[1m[1 queue]", render(color="256").split("\n")[0])

    def test_rows_title_times_outcome(self):
        out = render()
        a = line_with(out, "Alpha spec")
        self.assertIn("● Alpha spec", a)
        self.assertIn(f"{th.hm(NOW - 9000)} → {th.hm(NOW - 7200)}", a)
        self.assertIn("merged abc1234", a)
        self.assertIn("Beta spec #part-1", line_with(out, "Beta spec"))
        self.assertIn("mr https://gl/x/-/merge_requests/7", out)
        self.assertIn("docs/superpowers/specs/c-design.md (§4-5 only)", line_with(out, "kept spec-c"))  # no title: path
        self.assertIn(f"{th.hm(NOW - 600)} → …", line_with(out, "e-design.md"))
        self.assertIn("—", line_with(out, "f-design.md"))
        self.assertNotIn("Task 1: one", out.split("e-design.md")[0])   # plan tasks only under the running item

    def test_failed_outcome_red(self):
        self.assertIn(RED256, line_with(render(color="256"), "failed — residual N1"))
        self.assertNotIn(RED256, line_with(render(color="256"), "merged abc1234"))

    def test_running_item_expanded(self):
        lines = [taskwin.strip(l) for l in render().split("\n")]
        i = next(n for n, l in enumerate(lines) if "e-design.md" in l)
        self.assertEqual(lines[i + 1].strip(), "1/4 · 1 running · 1 blocked")
        self.assertEqual(lines[i + 2].strip(), "#11 Task 2: two · bob · 12m")
        self.assertIn("f-design.md", lines[i + 3])

    def test_running_item_collapsed_hides_detail(self):
        out = render(u=ui(collapsed={"q:5": True}))
        self.assertNotIn("1 running", out)

    def test_cursor_gutter(self):
        out = render(u=ui(cursor={"queue": 1}))
        self.assertTrue(taskwin.strip(line_with(out, "Beta spec")).startswith("▸ "))
        self.assertTrue(taskwin.strip(line_with(out, "Alpha spec")).startswith("  "))
        self.assertIn("\x1b[7", line_with(render(color="256", u=ui(cursor={"queue": 1})), "Beta spec"))

    def test_no_queue_hint(self):
        tasks = [t for t in QTASKS if not t["subject"].startswith("Plan & run")]
        out = render(tasks=tasks, u=ui(tasks, view="queue"))
        self.assertIn("no queue", out)
        self.assertIn("2: plan", out)

    def test_cursor_scrolls_into_view(self):
        tasks = [task(i, f"Plan & run: docs/superpowers/specs/s{i}-design.md", "pending") for i in range(1, 41)]
        out = render(tasks=tasks, height=12, u=ui(tasks, cursor={"queue": 35}))
        self.assertIn("s36-design.md", out)
        self.assertLessEqual(len(out.split("\n")), 12)

    def test_help_line_at_bottom(self):
        lines = render(height=40, u=ui(help=True)).split("\n")
        self.assertEqual(len(lines), 40)
        self.assertEqual(lines[-1], taskwin.HELP)

    def test_width_and_height_kept(self):
        for w in (40, 80, 120):
            for h in (5, 12, 40):
                lines = render(width=w, height=h).split("\n")
                self.assertLessEqual(len(lines), h)
                self.assertTrue(all(taskwin.cells(l) <= w for l in lines), (w, h))

    def test_ui_none_is_todays_render(self):
        v = {"name": "p", "active": True, "tasks": QTASKS}
        self.assertNotIn("[1 queue]", taskwin.render(v, QTIMING, 120, 40, NOW, 0, "none"))


if __name__ == "__main__":
    unittest.main()
```

Mutation: render outcomes without the `red` style → `test_failed_outcome_red` fails. Drop the scroll offset → `test_cursor_scrolls_into_view` fails.

- [ ] **Step 2: Run them.** Verify command → 11 errors `TypeError: render() got an unexpected keyword argument 'ui'` (checked against the current code).

- [ ] **Step 3: Implement** in `board/taskwin.py`. Import `taskwin_ui`, `taskwin_views` and `taskwin_hist` at module top, after the `sys.path.insert` line. They are pure, so `python3 -I` import tests keep passing.

```python
HELP = "Tab/1 2 3 view · j/k move · Enter open/fold · f filter · c fold done · ? help · q queue"
FILTER_NOTE = {"hide_done": "filter: hide done", "active": "filter: active"}


def _tabs(active):
    segs = []
    for i, v in enumerate(taskwin_ui.VIEWS, 1):
        if segs:
            segs.append((" ", ()))
        segs.append((f"[{i} {v}]", ("bold",)) if v == active else (f"{i} {v}", ("grey",)))
    return segs


def _scroll(lines, at, avail):
    """The `avail` lines of `lines` that keep line `at` visible (top-anchored until it would fall off)."""
    if avail <= 0:
        return []
    start = 0 if at < avail else min(at - avail + 1, max(0, len(lines) - avail))
    return lines[start:start + avail]
```

`_header` gains `tabs=None, name=None`. When `tabs` is given, draw them with `cv.put_segs(0, 0, tabs, width)` and start the name two cells after them, using `name` instead of `view["name"]`. The right-aligned counts and the room check work as today, measured from the end of the tabs. With `tabs=None` it draws exactly what it draws today.

`render(view, timing, width, height, now, frame, color, session="", tier_model=None, ui=None, ctx=None)`: when `ui is not None`, return `"\n".join(_render_ui(...))`. Otherwise run today's code unchanged. `_render_ui`:

```python
def _render_ui(view, timing, width, height, now, frame, color, session, tier_model, ui, ctx):
    tasks = list(view.get("tasks") or [])
    ui = taskwin_ui.normalize(ui, tasks)
    model = taskwin_views.model(tasks, ui, ctx.get("history") or [])
    ui = taskwin_ui.clamp(ui, model)
    body_h = height - 1 if ui["help"] and height > 1 else height
    v = ui["view"]
    if v == "queue":
        lines = _queue_screen(tasks, timing, width, body_h, now, frame, color, ui, ctx)
    elif v == "plan":
        lines = _plan_screen(view, tasks, timing, width, body_h, now, frame, color, session, tier_model, ui, model)
    else:
        lines = _history_screen(tasks, timing, width, body_h, now, frame, color, ui, ctx)
    lines = _trim(lines, body_h)
    if body_h < height:
        lines += [""] * (body_h - len(lines)) + [truncate(HELP, width)]
    return lines
```

`_queue_screen` puts the header in a `Canvas(width, HEADER_ROWS)` (`_header` over the queue items, `tabs=_tabs("queue")`, name `Queue` + ` · <report>`). It builds the body as a list of one-line strings (each line its own `Canvas(width, 1).lines(color)[0]`) and remembers the cursor row's line index. It then appends `_scroll(body, cursor_line, height - HEADER_ROWS)` to the header lines. The row label is `taskwin_views.queue_label(t["subject"], ctx.get("titles") or {})`. The start and end times come from `timing["tasks"][id]["started"]` and `["done"]`, formatted by `taskwin_hist.hm`. Give the label the room left after the gutter, glyph and right part, truncated by `truncate`. Then place times and outcome after it with `put_segs`, so a long outcome is cut with `…` before anything leaves the line. Running-task durations are `fmt_dur(now - started)`. For the queue screen only, `_plan_screen` and `_history_screen` can be stubs that return the header with `_tabs` and no body; Tasks 6 and 7 replace them. Update the module docstring with the new keywords and the three views.

- [ ] **Step 4: Run them.** Verify command → `OK` (the existing `test_taskwin.py` included).

- [ ] **Step 5: Commit.** `git add board/taskwin.py board/tests/test_taskwin_screens.py && git commit -m "feat(taskwin): view tabs, help line and the queue view"`.

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin_screens.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'", "acceptanceCriteria": ["ui=None output unchanged (test_taskwin.py unedited passes)", "tab header with Queue and report name, active tab bold", "queue rows: glyph, title or path, times, outcome; failed red", "running item expanded: summary and running-task lines", "no queue + 2: plan hint", "cursor gutter and scroll", "help line at bottom; width/height kept"], "modelTier": "standard"}
```

---

### Task 6: plan view: cursor, filter, collapse

**Goal:** The plan view draws only the non-queue tasks, after the filter and the done collapse, with a cursor in both the list and the graph layout.

**Files:**
- Modify: `board/taskwin.py` (`_plan_screen`, `_list_lines`, `_list_line`, `_graph_lines`)
- Modify: `board/tests/test_taskwin_screens.py` (add `PlanScreenTest`)

**Acceptance Criteria:**
- [ ] No `Plan & run:` subject appears in the plan view. The header counts are over the non-queue tasks (`1/4 done` in the fixture).
- [ ] `hide_done` drops completed tasks. `active` keeps only `in_progress` and `blocked`. The header carries `filter: hide done` / `filter: active` after the plan name, and nothing for `all`. When the filter leaves no tasks, the body says `no tasks match <filter note>`.
- [ ] With `p:done` collapsed, the first body line is `✓ <n> done` and no completed task is drawn, in both layouts.
- [ ] List layout (width < 80): the cursor row is inverse, and in `none` colour it has `>` before the id. The list scrolls to keep the cursor visible and does not auto-summarise done rows in `ui` mode.
- [ ] Graph layout: exactly one card has heavy corners `┏ ┓ ┗ ┛`, the cursor's. They are applied after `_draw_edges`.
- [ ] No non-queue tasks: today's idle screen, with line 0 replaced by the tabs and name.
- [ ] Every test in `test_taskwin.py` still passes unedited.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Add the failing tests**: insert this class into `board/tests/test_taskwin_screens.py` before the `if __name__` block:

```python


class PlanScreenTest(unittest.TestCase):
    def test_queue_items_not_in_plan_view(self):
        out = render(u=ui(view="plan"))
        self.assertNotIn("Plan & run", out)
        self.assertIn("Task 2: two", out)

    def test_header_counts_plan_tasks_only(self):
        self.assertIn("1/4 done", render(u=ui(view="plan")).split("\n")[0])

    def test_filter_hide_done(self):
        for w in (60, 120):
            out = render(width=w, u=ui(view="plan", filter="hide_done"))
            self.assertIn("filter: hide done", out.split("\n")[0])
            self.assertNotIn("Task 1: one", out)
            self.assertIn("Task 4: four", out)

    def test_filter_active(self):
        out = render(width=60, u=ui(view="plan", filter="active"))
        self.assertIn("filter: active", out.split("\n")[0])
        self.assertIn("Task 2: two", out)
        self.assertIn("Task 3: three", out)
        self.assertNotIn("Task 4: four", out)
        self.assertNotIn("Task 1: one", out)

    def test_no_filter_note_for_all(self):
        self.assertNotIn("filter:", render(u=ui(view="plan")))

    def test_collapsed_done_line(self):
        for w in (60, 120):
            lines = [taskwin.strip(l) for l in render(width=w, u=ui(view="plan", collapsed={"p:done": True})).split("\n")]
            self.assertEqual(lines[3].strip(), "✓ 1 done")
            self.assertFalse(any("Task 1: one" in l for l in lines))

    def test_list_cursor(self):
        out = render(width=60, u=ui(view="plan", cursor={"plan": 1}))
        self.assertRegex(taskwin.strip(line_with(out, "Task 2: two")), r"^\S >\*?11 ")
        self.assertIn("\x1b[7", line_with(render(width=60, color="256", u=ui(view="plan", cursor={"plan": 1})), "Task 2: two"))

    def test_graph_cursor_heavy_corners(self):
        out = render(width=120, u=ui(view="plan", cursor={"plan": 1}))
        self.assertEqual(out.count("┏"), 1)
        self.assertRegex(line_with(out, "┏"), r" \*?11 ")

    def test_list_scrolls_to_cursor(self):
        tasks = [task(i, f"t{i}", "pending") for i in range(1, 31)]
        out = render(tasks=tasks, width=60, height=12, u=ui(tasks, view="plan", cursor={"plan": 25}))
        self.assertRegex(out, r"(?m)^\S >\*?26 ")
        self.assertLessEqual(len(out.split("\n")), 12)

    def test_plan_view_idle_without_plan_tasks(self):
        tasks = [t for t in QTASKS if t["subject"].startswith("Plan & run")]
        out = render(tasks=tasks, u=ui(tasks, view="plan"))
        self.assertIn(taskwin.IDLE_LINE, out)
        self.assertIn("[2 plan]", out.split("\n")[0])
```

Mutation: apply the filter after layout instead of before (draw `split(tasks)[1]`) → `test_filter_hide_done` fails.

- [ ] **Step 2: Run them.** Verify command → the new class fails (stub `_plan_screen`).

- [ ] **Step 3: Implement.** `_plan_screen(view, tasks, timing, width, height, now, frame, color, session, tier_model, ui, model)`:
  - `ndone, shown = taskwin_views.plan_tasks(tasks, ui)`; `plan = taskwin_views.split(tasks)[1]`; `sel = model["rows"]["plan"][ui["cursor"]["plan"]]` when the rows are not empty.
  - Header over `plan`, `tabs=_tabs("plan")`, name `(view["name"] or "Tasks")` + ` · <FILTER_NOTE>` when the filter is not `all`.
  - When `ndone`: one line `✓ <n> done` (green; when `sel == "p:done"`, inverse, and `> ` before it in `none` colour), then `avail -= 1`.
  - Body: `_graph_lines(shown, …, sel=<id or None>)` when width ≥ 80, else (or when it returns `None`) `_list_lines(shown, …, sel=<id>, summarize=False)`.
  - `_list_line` gains `sel=False, sel_mark=False`. `sel` adds `("inverse",)` to `extra`; `sel_mark` puts `>` before the `*`/id (`" " + (">" if sel_mark else "") + ("*" if mark else "") + id`). `_list_lines` gains `sel=None, summarize=True`. With `summarize=False` it skips the done-summary branch, and it starts the shown window so the cursor row is visible (the same offset rule as `_scroll`, keeping the `+N more` line at the bottom when rows follow).
  - `_graph_lines` gains `sel=None`. After `_draw_edges`, when `sel in pos`, write `┏`, `┓`, `┗`, `┛` at the card's four corners (`x = c * (cw + GUTTER)`, `y = r * (card_h + GAP)`, corners `(x, y)`, `(x + cw - 1, y)`, `(x, y + card_h - 1)`, `(x + cw - 1, y + card_h - 1)`), keeping each cell's style plus `bold`.
  - All new parameters default to today's behaviour, so the `ui=None` path is unchanged.

- [ ] **Step 4: Run them.** Verify command → `OK`.

- [ ] **Step 5: Commit.** `git add board/taskwin.py board/tests/test_taskwin_screens.py && git commit -m "feat(taskwin): plan view cursor, filter and done collapse"`.

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin_screens.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'", "acceptanceCriteria": ["no Plan & run in plan view; counts over plan tasks", "hide_done/active filters before layout; header note; empty-filter line", "collapsed done line in both layouts", "list cursor inverse + > in none colour; scrolls; no auto summary in ui mode", "graph cursor heavy corners on one card", "idle screen with tabs when no plan tasks", "test_taskwin.py unedited passes"], "modelTier": "standard"}
```

---

### Task 7: history view

**Goal:** The history view draws `ctx["history"]` grouped by day (newest first), one collapsible row per plan or spec, with the journaled tasks or the ledger folder under an expanded row.

**Files:**
- Modify: `board/taskwin.py` (`_history_screen`)
- Modify: `board/tests/test_taskwin_screens.py` (add `HistoryScreenTest`)

**Acceptance Criteria:**
- [ ] Header line 0 starts `1 queue 2 plan [3 history]  History`.
- [ ] Body: a bold day line `YYYY-MM-DD` before each day's rows. Rows read `<gutter><name>[ · 1 task| · <n> tasks] · <outcome or —>`, and an outcome starting with `failed` is red.
- [ ] An expanded row shows `    ✓ #id subject · owner · tier · HH:MM` per journaled task, oldest first, with empty owner/tier segments omitted. With no journal lines it shows `    <ledger folder>`, else `    <spec>`.
- [ ] The filter does not change the history view. An empty history shows `no history yet`. The view works when the task list is empty.
- [ ] The cursor moves over entry rows only (`h:<key>`; day lines are not rows). The view scrolls to keep the cursor visible.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Add the failing tests**: insert into `board/tests/test_taskwin_screens.py` before the `if __name__` block:

```python


T1 = time.mktime((2026, 11, 21, 9, 30, 0, 0, 0, -1))
HISTORY = [
    {"key": "plan:2026-11-21-b", "day": "2026-11-21", "name": "2026-11-21-b", "spec": "", "outcome": "kept spec-b",
     "ledger": "", "tasks": [{"kind": "task_done", "at": T1, "plan": "2026-11-21-b", "id": "2", "subject": "B two",
                              "owner": "ann", "tier": "standard"}]},
    {"key": "plan:2026-11-20-a", "day": "2026-11-20", "name": "2026-11-20-a", "spec": "docs/superpowers/specs/a-design.md",
     "outcome": "merged aaa1111", "ledger": "docs/superpowers/ledgers/2026-11-20-a/", "tasks": []},
    {"key": "spec:docs/superpowers/specs/c-design.md", "day": "2026-11-20", "name": "docs/superpowers/specs/c-design.md",
     "spec": "docs/superpowers/specs/c-design.md", "outcome": "", "ledger": "", "tasks": []},
]
HCTX = {"titles": {}, "report": "", "history": HISTORY}


class HistoryScreenTest(unittest.TestCase):
    def lines(self, **kw):
        out = render(ctx=HCTX, u=ui(view="history", **kw))
        return [taskwin.strip(l) for l in out.split("\n")]

    def test_grouped_by_day_newest_first(self):
        ls = self.lines()
        self.assertTrue(ls[0].startswith("1 queue 2 plan [3 history]  History"))
        body = [l for l in ls[3:] if l.strip()]
        self.assertEqual(body, ["2026-11-21",
                                "▸ 2026-11-21-b · 1 task · kept spec-b",
                                "2026-11-20",
                                "  2026-11-20-a · merged aaa1111",
                                "  docs/superpowers/specs/c-design.md · —"])

    def test_expand_shows_journaled_tasks(self):
        ls = self.lines(collapsed={"h:plan:2026-11-21-b": False})
        self.assertIn(f"    ✓ #2 B two · ann · standard · {th.hm(T1)}", ls)

    def test_expand_without_journal_shows_ledger(self):
        ls = self.lines(collapsed={"h:plan:2026-11-20-a": False}, cursor={"history": 1})
        self.assertIn("    docs/superpowers/ledgers/2026-11-20-a/", ls)
        self.assertIn("▸ 2026-11-20-a · merged aaa1111", ls)

    def test_filter_does_not_apply(self):
        self.assertEqual(self.lines(filter="active")[3:], self.lines()[3:])

    def test_failed_outcome_red(self):
        h = [dict(HISTORY[1], outcome="failed — x")]
        out = render(color="256", ctx={"titles": {}, "report": "", "history": h}, u=ui(view="history"))
        self.assertIn(RED256, line_with(out, "failed — x"))

    def test_empty_history(self):
        out = render(ctx={"titles": {}, "report": "", "history": []}, u=ui(view="history"))
        self.assertIn("no history yet", out)

    def test_history_without_tasks(self):
        out = render(tasks=[], ctx=HCTX, u=ui([], view="history"))
        self.assertIn("2026-11-21-b", out)
```

Mutation: default history rows to expanded → `test_grouped_by_day_newest_first` fails (child lines appear).

- [ ] **Step 2: Run them.** Verify command → `HistoryScreenTest` fails (stub).

- [ ] **Step 3: Implement** `_history_screen(tasks, timing, width, height, now, frame, color, ui, ctx)`. The header is over the plan tasks with `tabs=_tabs("history")` and name `History`. The body is one-line strings as in `_queue_screen`. For each entry in `ctx["history"]`, emit a day line whenever the day changes, then the entry row (gutter `▸ ` when `"h:" + key` is the cursor row), and its children when `not taskwin_ui.is_collapsed(ui, "h:" + key)`. Task times use `taskwin_hist.hm(at)`. Finish with `_scroll(body, cursor_line, height - HEADER_ROWS)`.

- [ ] **Step 4: Run them.** Verify command → `OK`.

- [ ] **Step 5: Commit.** `git add board/taskwin.py board/tests/test_taskwin_screens.py && git commit -m "feat(taskwin): history view"`.

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin_screens.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'", "acceptanceCriteria": ["history tab header", "day lines, rows with count and outcome, failed red", "expanded rows: journaled tasks or ledger folder", "filter ignored; empty history message; works with no tasks", "cursor over entry rows, scrolls"], "modelTier": "standard"}
```

---

### Task 8: `watch` reads keys, keeps `ui`, writes journal

**Goal:** `taskwin.watch` puts a TTY stdin in cbreak mode and waits for keys with `select` instead of `sleep`, so a key redraws at once. It stores `ui` in the state file, passes the journal and plan name to `taskwin_state.update`, and builds `ctx` for `render`. Its terminal mode is restored on every exit. Not a TTY → today's sleep loop.

**Files:**
- Modify: `board/taskwin.py` (`watch`, `_fetch`, `main`, new `_ctx`)
- Modify: `board/tests/test_taskwin_cli.py` (existing `run_watch` passes `stdin=io.StringIO()`; add `TestWatchKeys`)
- Modify: `docs/ARCHITECTURE.md` (the **Tasks window** paragraph)

**Acceptance Criteria:**
- [ ] A `3` written to a pty used as stdin → the state file's `ui.view` is `history` and a frame shows `[3 history]`. After `watch` returns, the pty has `ICANON` and `ECHO` set again.
- [ ] With `interval=30, frames=2` and a key pending, `watch` returns in under 5 s.
- [ ] `2` then `ESC [ B` → `ui.cursor.plan == 1`.
- [ ] A stdin that hits EOF (closed pipe reporting `isatty`) does not spin: the loop falls back to `time.sleep`.
- [ ] A non-TTY stdin never calls `tty.setcbreak`, and sleeps `frames - 1` times.
- [ ] A task that goes in_progress → completed between two ticks writes one `task_done` line to `journal_path(TC_STATE, "proj")` with `plan` = the view name.
- [ ] `ctx["history"]` is read only while the view is `history` (the cached reader keeps the frame cost low). Spec titles and the report name come from `taskwin_hist`.
- [ ] `docs/ARCHITECTURE.md` names the keys, the three views, the journal path and the `ui` key in the state file.
- [ ] Every existing test in `test_taskwin_cli.py` still passes.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** In `board/tests/test_taskwin_cli.py`, add `import contextlib` and `import time` to the imports. Change both `taskwin.watch(...)` calls in `TestWatch.run_watch` and the one in `test_sigterm_handler_restores_cursor` to pass `stdin=io.StringIO()`. Then add before the `TestTierModel` class:

```python


class TestWatchKeys(Base):
    """watch reads keys from a TTY in cbreak mode, redraws at once, keeps `ui` in the state file and restores the
    terminal on exit."""

    def pty(self):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        f = os.fdopen(slave, "r")
        self.addCleanup(f.close)
        return master, f

    def watch(self, frames, stdin, interval=0.05, view=None):
        out = io.StringIO()
        with contextlib.ExitStack() as es:
            es.enter_context(redirect_stdout(out))
            es.enter_context(mock.patch("paneclass.tmux_runner", return_value=fake_tmux()))
            if view:
                es.enter_context(mock.patch("planview.view", side_effect=view))
            taskwin.watch("proj", self.repo, self.home, interval=interval, frames=frames, stdin=stdin)
        return out.getvalue()

    def state(self):
        return taskwin_state.load(taskwin_state.path_for(self.state, "proj"))

    def test_key_switches_view_and_is_kept(self):
        import termios
        master, f = self.pty()
        os.write(master, b"3")
        out = self.watch(3, f)
        self.assertEqual(self.state()["ui"]["view"], "history")
        self.assertIn("[3 history]", taskwin.strip(out))
        lflag = termios.tcgetattr(f.fileno())[3]
        self.assertTrue(lflag & termios.ICANON and lflag & termios.ECHO, "terminal mode restored")

    def test_key_redraws_at_once(self):
        # remove the select wake-up (sleep the whole interval) -> this takes 30 s and fails
        master, f = self.pty()
        os.write(master, b"3")
        t0 = time.monotonic()
        self.watch(2, f, interval=30)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(self.state()["ui"]["view"], "history")

    def test_arrow_moves_cursor(self):
        master, f = self.pty()
        os.write(master, b"2\x1b[B")
        self.watch(3, f)
        self.assertEqual(self.state()["ui"]["cursor"]["plan"], 1)

    def test_eof_on_stdin_does_not_spin(self):
        r, w = os.pipe()
        os.close(w)                                  # a closed pipe: select says readable, read returns b""
        rf = os.fdopen(r, "r")
        self.addCleanup(rf.close)
        with mock.patch.object(rf, "isatty", return_value=True), mock.patch("termios.tcgetattr", return_value=[0] * 7), \
                mock.patch("termios.tcsetattr"), mock.patch("tty.setcbreak"), mock.patch("time.sleep") as sl:
            self.watch(4, rf)
        self.assertGreaterEqual(sl.call_count, 2, "after EOF the loop sleeps instead of selecting on stdin")

    def test_not_a_tty_sleeps_and_reads_no_keys(self):
        with mock.patch("time.sleep") as sl, mock.patch("tty.setcbreak") as cb:
            self.watch(2, io.StringIO())
        self.assertEqual(sl.call_count, 1)
        cb.assert_not_called()

    def test_journal_written_under_project_key(self):
        seq = iter(["in_progress", "completed"])

        def view(*a, **k):
            return {"name": "2026-11-21-x", "active": True, "tasks": [
                {"id": "1", "subject": "Task 1: x", "status": next(seq), "owner": "ann", "state": "", "tier": "mechanical",
                 "blockedBy": [], "outcome": "", "answeredAt": "", "planPath": ""}]}
        with mock.patch("time.sleep"):
            self.watch(2, io.StringIO(), view=view)
        j = taskwin_state.journal_path(self.state, "proj")
        lines = [json.loads(l) for l in j.read_text().splitlines()]
        self.assertEqual([(l["kind"], l["plan"], l["id"]) for l in lines], [("task_done", "2026-11-21-x", "1")])
```

Mutation: wait with `time.sleep(interval)` even when a key is pending → `test_key_redraws_at_once` takes 30 s and fails. Drop the `tcsetattr` in `finally` → `test_key_switches_view_and_is_kept` fails on the `ICANON` check.

- [ ] **Step 2: Run them.** Verify command → 6 errors `TypeError: watch() got an unexpected keyword argument 'stdin'` (checked against the current code).

- [ ] **Step 3: Implement.**

`_fetch` returns `(view, lead, project)`, with `planview.project_of(session, tmux)` as the third value. `main`'s `render` branch unpacks three values and still passes no `ui`.

```python
def _ctx(root, view, ui, journal):
    queue, _ = taskwin_views.split(view.get("tasks") or [])
    titles = {}
    for t in queue:
        spec = taskwin_state.spec_of(t["subject"])
        title = taskwin_hist.spec_title(root, spec)
        if title:
            titles[spec] = title
    return {"titles": titles, "report": taskwin_hist.queue_report(root, queue),
            "history": taskwin_hist.entries(root, journal) if ui["view"] == "history" else []}
```

(Import `taskwin_state` at module top next to the other pure modules; `watch`'s own local import of it can go.)

The `watch` loop shape (keep today's signal handlers, `HIDE`/`SHOW`, tier-model cache, error line and `KeyboardInterrupt`):

```python
def watch(session, root, home, interval=1.0, frames=None, stdin=None):
    import select
    import termios
    import tty
    import tc_env
    stdin = sys.stdin if stdin is None else stdin
    try:
        tty_fd = stdin.fileno() if stdin.isatty() else None
    except (AttributeError, ValueError, OSError):
        tty_fd = None
    read_fd, saved = tty_fd, None
    view, tasks, ctx, ui, journal = {}, [], {"titles": {}, "report": "", "history": []}, None, None
    # ... today's setup (spath, st, last, n, tick, tm, signal handlers, HIDE) ...
    try:
        if tty_fd is not None:
            saved = termios.tcgetattr(tty_fd)
            tty.setcbreak(tty_fd)
        while frames is None or n < frames:
            n += 1
            try:
                view, lead, project = _fetch(session, root, home)
                tasks = view.get("tasks") or []
                journal = taskwin_state.journal_path(tc_env.state_dir(), project)
                # tier model as today; then:
                taskwin_state.update(st, lead, tasks, now, journal=journal, plan=view.get("name") or "")
                ui = taskwin_ui.normalize(st.get("ui"), tasks)
                if tasks or "ui" in st:
                    st["ui"] = ui
                # save when changed, as today
                ctx = _ctx(root, view, ui, journal)
                last = render(view, st, cols, rows - 1 if rows > 1 else rows, now, tick, color_mode(os.environ),
                              session, tm, ui=ui, ctx=ctx)
                tick += 1
                _draw(last)
            except Exception as e:  # one bad tick must not kill the window
                _draw(last, "taskwin: " + (str(e).splitlines() or [type(e).__name__])[0][:200])
            if frames is not None and n >= frames:
                break
            if read_fd is None:
                time.sleep(interval)
                continue
            if not select.select([read_fd], [], [], interval)[0]:
                continue
            data = os.read(read_fd, 64)
            if not data:          # EOF: stop reading, keep the terminal mode to restore
                read_fd = None
                continue
            ui = ui or taskwin_ui.normalize(st.get("ui"), tasks)
            for k in taskwin_ui.decode(data.decode("utf-8", "replace")):
                new = taskwin_ui.handle_key(ui, k, taskwin_views.model(tasks, ui, ctx.get("history") or []))
                if new["view"] != ui["view"]:
                    ctx = _ctx(root, view, new, journal)   # history rows for the next key
                ui = new
            st["ui"] = ui
            taskwin_state.save(spath, st)
    except KeyboardInterrupt:
        pass
    finally:
        if saved is not None:
            termios.tcsetattr(tty_fd, termios.TCSADRAIN, saved)
        # today's SHOW + signal restore
```

`journal` is the last successful tick's journal path (`None` before the first one). Compare only `ICANON`/`ECHO` in tests: on macOS the kernel's `PENDIN` bit in `lflag` can differ after a restore (probe on 2026-11-21: `tcsetattr(TCSADRAIN)` after cbreak left `lflag` 536872395 against 1483 before, the difference being `PENDIN` only, with `ICANON` and `ECHO` both back).

Update the **Tasks window** paragraph of `docs/ARCHITECTURE.md`. Name the three views and their keys (Tab/1-3, j/k/arrows, Enter, f, c, ?, q), the `ui` key in `$TC_STATE/taskwin/<session>.json` (kept across a lead change), the journal `$TC_STATE/taskwin/<project>.history.jsonl` (5000 lines), and the ledger/report sources under `--root`.

- [ ] **Step 4: Run them.** Verify command → `OK`. Then run the board suite: `tmux-ctl run -t 900 tests "python3 -m unittest discover -s board/tests; echo rc=\$?"` → `OK`, `rc=0`.

- [ ] **Step 5: Commit.** `git add board/taskwin.py board/tests/test_taskwin_cli.py docs/ARCHITECTURE.md && git commit -m "feat(taskwin): watch reads keys, keeps the view, writes the journal"`.

```json:metadata
{"files": ["board/taskwin.py", "board/tests/test_taskwin_cli.py", "docs/ARCHITECTURE.md"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_taskwin*.py'", "acceptanceCriteria": ["pty key 3 -> ui.view history, frame shows tab, ICANON/ECHO restored", "pending key redraws at once (<5 s with interval 30)", "arrow down moves the plan cursor", "EOF on stdin falls back to sleep", "non-TTY: no setcbreak, sleeps frames-1 times", "task_done line in journal_path(TC_STATE, proj) with plan = view name", "history read only in history view", "ARCHITECTURE.md names keys, views, ui key, journal", "existing test_taskwin_cli passes"], "modelTier": "standard"}
```

---

### Task 9: e2e: keys, views, kept state on real lists

**Goal:** `tools/tests/e2e-tasks-window.zsh` drives the real window with keys on a scratch tmux server. It uses read-only copies of two real `~/.claude/tasks` lists (a plan-only list and a queue list) and this checkout's real ledgers and reports. It shows each view, keeps view and filter across a window restart and a lead change, and ends `ALL PASS`.

**Files:**
- Modify: `tools/tests/e2e-tasks-window.zsh`

**Acceptance Criteria:**
- [ ] The default view of a plan-only real list is `[2 plan]` with cards drawn (`╭`) and a status glyph.
- [ ] `3` shows `[3 history]` and the newest real ledger's plan stem. `Enter` expands it to a `docs/superpowers/ledgers/` folder.
- [ ] `Tab` wraps to `[1 queue]` with `no queue`. `2` then `f` shows `filter: hide done`. `?` shows the help line.
- [ ] After `kill-window` and a restart: `[2 plan]` and `filter: hide done` are kept.
- [ ] After the lead moves to the real queue list: still `[2 plan]`. Then `1` shows `[1 queue]` with rows (no `no queue`), and the state file's `ui.view` is `queue`.
- [ ] Nothing is written under `~/.claude` or this checkout's `docs/` (`git status --porcelain docs/` empty after the run).

**Verify:** `zsh tools/tests/e2e-tasks-window.zsh; echo rc=$?` → last check line, then `ALL PASS` and `rc=0`

**Steps:**

- [ ] **Step 1: Replace** `tools/tests/e2e-tasks-window.zsh` with:

```zsh
#!/usr/bin/env zsh
# e2e-tasks-window.zsh — the tasks window, end to end on a scratch tmux server (lib.zsh, `-L tctest-… -f /dev/null`).
# A fake home holds read-only copies of two real ~/.claude/tasks dirs: the newest with 5-13 tasks and no `Plan & run:`
# item (more than ~10 independent tasks fall back to the list layout at 50 rows, which draws no cards), and the newest
# with 3-60 tasks and at least one `Plan & run:` item. sessions/x.json points the scratch `claude` pane at the first;
# `taskwin.py watch --root <this checkout>` runs in a second window and reads this checkout's real ledgers and queue
# reports read-only. Keys go in with send-keys; the window is killed and restarted to show the view and filter are
# kept, then the lead changes to the queue list.
# Not a test_*.zsh: run-all does not pick it up. Run it from the worktree: zsh tools/tests/e2e-tasks-window.zsh
R="${${(%):-%x}:A:h:h:h}"
source "$R/tools/tests/lib.zsh"
tt_setup claude
src=""; qsrc=""
for d in ${(f)"$(ls -dt ~/.claude/tasks/session-*(/N))"}; do
  files=($d/*.json(N)); n=${#files}
  (( n > 0 )) || continue                 # grep with no file names would read stdin
  hasq=$(grep -l '"subject": "Plan & run: ' $files </dev/null | wc -l | tr -d ' ')
  if [[ -z "$src" ]] && (( n >= 5 && n <= 13 && hasq == 0 )); then src="$d"; fi
  if [[ -z "$qsrc" ]] && (( n >= 3 && n <= 60 && hasq >= 1 )); then qsrc="$d"; fi
  if [[ -n "$src" && -n "$qsrc" ]]; then break; fi
done
[[ -n "$src" && -n "$qsrc" ]] || { print "no real task dirs (plan: 5-13 tasks, no queue; queue: 3-60 tasks)"; exit 1 }
print -r -- "copied real task dirs: plan $src, queue $qsrc"
sid="11111111-0000-0000-0000-000000000000"; sid2="22222222-0000-0000-0000-000000000000"
home="$TT_DIR/home"; mkdir -p "$home/sessions" "$home/tasks"
cp -R "$src" "$home/tasks/session-${sid[1,8]}"
cp -R "$qsrc" "$home/tasks/session-${sid2[1,8]}"
pane="$(tt display -p -t '=tt:claude' '#{window_id}.#{pane_id}')"
lead() { print -r -- "{\"pid\":1,\"sessionId\":\"$1\",\"cwd\":\"$TT_DIR\",\"startedAt\":1,\"tmux\":\"tt:$pane\"}" > "$home/sessions/x.json" }
lead "$sid"
start() {
  tt new-window -d -t '=tt:' -n tasks -c "$TT_DIR" "python3 -I $TT_REPO/board/taskwin.py watch --session tt --root $TT_REPO --home $home"
  tt resize-window -t '=tt:tasks' -x 120 -y 50
  sleep 3
}
key() { tt send-keys -t '=tt:tasks' "$@"; sleep 1.5 }
cap() { tt capture-pane -p -t '=tt:tasks' }
has() { [[ "$1" == *"$2"* ]] }
start
c="$(tt capture-pane -e -p -t '=tt:tasks')"
print -r -- "$c"
check "default view is plan: [2 plan] tab" has "$c" "[2 plan]"
check "card border ╭ drawn" has "$c" "╭"
check "status glyph ● or ○ drawn" zsh -c '[[ $1 == *●* || $1 == *○* ]]' _ "$c"
check "state file written under scratch TC_STATE" test -s "$TC_STATE/taskwin/tt.json"
key 3; c="$(cap)"; print -r -- "$c"
newest="$(ls "$TT_REPO/docs/superpowers/ledgers" | sort | tail -1)"
stem="$(sed -n '1s/^# SDD ledger — plan: //p' "$TT_REPO/docs/superpowers/ledgers/$newest/progress.md")"; stem="${${stem:t}%.md}"
check "3 shows the history tab" has "$c" "[3 history]"
check "history lists the newest real ledger's plan ($stem)" has "$c" "$stem"
key Enter; c="$(cap)"
check "Enter expands the first history row to its ledger folder" has "$c" "docs/superpowers/ledgers/"
key Tab; c="$(cap)"
check "Tab wraps to the queue tab" has "$c" "[1 queue]"
check "queue view says no queue for a plan-only list" has "$c" "no queue"
key 2; key f; c="$(cap)"
check "f in the plan view shows the filter" has "$c" "filter: hide done"
key '?'; c="$(cap)"
check "? shows the key help" has "$c" "Tab/1 2 3 view"
key '?'
tt kill-window -t '=tt:tasks'
start; c="$(cap)"; print -r -- "$c"
check "restart keeps the plan view" has "$c" "[2 plan]"
check "restart keeps the filter" has "$c" "filter: hide done"
lead "$sid2"; sleep 3; c="$(cap)"
check "lead change keeps the view" has "$c" "[2 plan]"
key 1; c="$(cap)"; print -r -- "$c"
check "1 shows the queue tab" has "$c" "[1 queue]"
check "real queue list has rows (no 'no queue')" zsh -c '[[ $1 != *"no queue"* ]]' _ "$c"
check "ui saved with view queue" python3 -c 'import json,sys; sys.exit(json.load(open(sys.argv[1]))["ui"]["view"] != "queue")' "$TC_STATE/taskwin/tt.json"
tt_done
```

The real-dir selection loop was run once on 2026-11-21 and picked `session-5ac05829` (plan-only) and `session-b94397a7` (queue). Without the `(( n > 0 ))` guard it hung on an empty task dir, because `grep` read stdin.

- [ ] **Step 2: Run it** through `tmux-ctl run -t 300 tests "zsh tools/tests/e2e-tasks-window.zsh; echo rc=\$?"`. On a failing check, read the printed capture, fix in the owning task's file (re-run that task's Verify), and re-run this script.

- [ ] **Step 3: Check nothing real was written:** `git status --porcelain docs/` → empty.

- [ ] **Step 4: Commit.** `git add tools/tests/e2e-tasks-window.zsh && git commit -m "test(taskwin): e2e keys, views and kept state on real lists"`.

```json:metadata
{"files": ["tools/tests/e2e-tasks-window.zsh"], "verifyCommand": "zsh tools/tests/e2e-tasks-window.zsh; echo rc=$?", "acceptanceCriteria": ["plan-only real list: [2 plan], cards, glyph", "3: history with newest real ledger stem; Enter shows ledger folder", "Tab: queue tab, no queue; 2 f: filter note; ?: help", "restart keeps view and filter", "lead change keeps view; 1 shows real queue rows; ui.view queue saved", "nothing written under ~/.claude or docs/"], "modelTier": "standard"}
```

---

### Task 10: Full suite and read-only real-state checks

**Goal:** Every suite passes, and the new readers behave on the real repository and the real task lists, read-only.

**Files:**
- Test only (no file changes; fixes go back to the owning task's files)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh; echo rc=$?` → `ALL PASS` with rc 0 or 4 (4 = over the time budget, accepted on this machine).
- [ ] `zsh tools/tests/e2e-tasks-window.zsh; echo rc=$?` → `ALL PASS`, `rc=0`.
- [ ] Real repo, read-only: `python3 -I -c 'import sys,time; sys.path.insert(0,"board"); import taskwin_hist as th; th.entries(".",None); t=time.perf_counter(); e=th.entries(".",None); print(len(e), sum(1 for x in e if x["outcome"]), round((time.perf_counter()-t)*1000,1))'` prints ≥ 47 entries, ≥ 12 with an outcome, and a warm time under 20 ms (measured 0.7 ms on 2026-11-21 at load 2.4; log the load average with `uptime`).
- [ ] Real live list, read-only: `python3 -I board/taskwin.py render --session agent-board --root . --width 120 --height 40` exits 0 with no `[1 queue]` tab (the CLI render stays `ui=None`), and writes no `taskwin/` file (`ls $TMPDIR/tmux-ctl-$UID/taskwin/ 2>/dev/null` lists the same files before and after).
- [ ] `git -C /Users/francisco.ruiz/agent-board status --porcelain docs/superpowers/ledgers docs/superpowers/reports` is empty after all of the above.

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → the runner's verdict line `ALL PASS …` and `rc=0` or `rc=4`

**Steps:**

- [ ] Run each criterion's command (the suites through `tmux-ctl run -t 1200 tests "<cmd>"`) and capture the output in the ledger. On any failure: `superpowers-extended-cc:systematic-debugging`, fix in the owning file, re-run that task's Verify, then this one.

```json:metadata
{"files": [], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["all.zsh ALL PASS rc 0 or 4", "e2e-tasks-window ALL PASS rc 0", "real repo history: >=47 entries, >=12 outcomes, warm <20 ms", "render CLI on the real live list: rc 0, no tabs, no state file", "real ledgers/reports untouched"], "modelTier": "standard"}
```

---

### Task 11: User gate: the window on a live queue

**Goal:** After this branch merges and the live `tasks` window restarts, the user uses its keys during a real queue run. Each view shows real data, and finished tasks are journaled.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Test only

**Acceptance Criteria:**
- [ ] The live window is restarted on merged `main` (`tmux respawn-pane -k -t '=agent-board:tasks'`, which re-runs its start command) and its capture shows `[1 queue] 2 plan 3 history` with the queue view's `Plan & run:` rows (default view while a queue is running).
- [ ] After at least one plan task completes in the running queue, `$TMPDIR/tmux-ctl-$UID/taskwin/agent-board.history.jsonl` has ≥ 1 `task_done` line, and the history view (`3`) shows today's date with that plan's row.
- [ ] The user confirms in their own words that the queue overview, filter (`f`) and collapse (`c`) work for them.

**Verify:** `tail -n 3 $TMPDIR/tmux-ctl-$UID/taskwin/agent-board.history.jsonl; tmux capture-pane -p -t '=agent-board:tasks' | head -3` → journal lines and the tab header captured as evidence

```json:metadata
{"files": [], "verifyCommand": "tail -n 3 $TMPDIR/tmux-ctl-$UID/taskwin/agent-board.history.jsonl; tmux capture-pane -p -t '=agent-board:tasks' | head -3", "acceptanceCriteria": ["live window restarted on main shows tabs and queue rows", "journal has a task_done line and history shows today's plan", "user confirms queue overview, filter and collapse"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```

---

## Execution handoff

Run this plan with `superpowers-extended-cc:subagent-driven-development` (with `subagent-driven-development-extras`), task by task in order. Tasks 1-4 are independent of each other; 5 needs 1, 3 and 4; 6 needs 5; 7 needs 6; 8 needs 2 and 7; 9 needs 8; 10 needs 9; 11 needs 10 and the merge.
