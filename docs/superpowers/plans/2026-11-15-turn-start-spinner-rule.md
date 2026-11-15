# Turn-start spinner rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One spinner rule for the board and the Telegram watchdog (a `⎿ Tip:` row keeps a first-frame spinner live), and the watchdog's `remove()` moved to module level so tests run the real function.

**Architecture:** `board/paneclass.py` `spinner_live` learns tip rows; `tools/telegram_watch.py` drops its private `_spinner_above_input` and calls `paneclass.spinner_live`; the nested `remove` in `_do_reconnect` becomes module-level `send_remove(t, pane, back, count)`. A last task checks a real turn start on the live `dev` session, read-only.

**Tech Stack:** Python 3 unittest, tmux 3.8 (scratch `-L` server with `-f /dev/null`).

**Spec:** `docs/superpowers/specs/2026-11-11-turn-start-spinner-rule-design.md`

## Global Constraints

- `TIP_RE = re.compile(r"^\s*⎿\s+Tip:")` in `board/paneclass.py`.
- First-frame spinner (`SPINNER_FIRST_RE`) is live when the rows between it and the input rule are tip rows, a tip's wrapped continuation lines (indented, directly after a tip row or another continuation), or blank rows. A blank row ends a tip's continuation. Any other indented row after a first-frame spinner means transcript: `["✢ Thinking…", "  some indented output", RULE]` stays `ready`.
- The elapsed-form spinner rule (`SPINNER_RE`) is unchanged.
- `_spinner_above_input` is removed; `idle_at_prompt` calls `paneclass.spinner_live(rows[-30:])` directly (kept on top of `classify`, because a fresh mod state can say `ready` over a live spinner).
- `send_remove(t, pane, back, count)` sends `["End"] + ["Left"] * back + ["BSpace"] * count` with `t("send-keys", "-t", pane, *keys)`; `_do_reconnect` passes `remove=lambda back, count: send_remove(t, pane, back, count)`. It raises whatever `t` raises.
- Every existing watchdog fixture keeps its verdict. If one flips, the fix goes in paneclass, never in the watchdog.
- Scratch tmux servers: `-L <unique name>` and `-f /dev/null`, killed in a `finally`.
- Commit messages: conventional with scope; end with the attribution trailer your harness specifies.

**User decisions (already made):** Queue item, integration `merge`, no push (metadata.queue on the lead's task).

---

### Task 1: paneclass — a tip row keeps a first-frame spinner live

**Goal:** `classify` returns `("claude", "working")` for the real turn-start capture `tools/tests/fixtures/telegram-watch/working.txt`.

**Files:**
- Modify: `board/paneclass.py` (`SPINNER_FIRST_RE` line ~26, `spinner_live` ~92-108)
- Test: `board/tests/test_paneclass.py` (class `SpinnerLayoutsTest`, after `test_first_frame_shaped_line_in_transcript_is_not_working` ~128)

**Acceptance Criteria:**
- [ ] New test `test_real_turn_start_with_tip_row_is_working` loads `working.txt` and asserts `("claude", "working")`; RED on the current code (it returns `ready`).
- [ ] Mutation: delete the `if TIP_RE.match(below): in_tip = True; continue` branch → that test fails.
- [ ] New test `test_tip_then_column0_output_is_ready`: `["✢ Thinking…", "  ⎿  Tip: x", "⏺ done", RULE] + INPUT` → `ready`.
- [ ] `test_first_frame_shaped_line_in_transcript_is_not_working` passes unchanged.
- [ ] All paneclass tests pass.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_paneclass*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** — add to `SpinnerLayoutsTest` in `board/tests/test_paneclass.py`, right after `test_first_frame_shaped_line_in_transcript_is_not_working`:

```python
    def test_real_turn_start_with_tip_row_is_working(self):
        # real Claude Code 2.1.322 capture: `✽ Actioning…` then `  ⎿  Tip: …` then a right-aligned `Ctrl+Y …` row
        fx = HERE.parent / "tools" / "tests" / "fixtures" / "telegram-watch" / "working.txt"
        rows = fx.read_text().splitlines()
        while rows and not rows[-1].strip():
            rows.pop()
        self.assertEqual(paneclass.classify("2.1.322", rows, False), ("claude", "working"))

    def test_tip_then_column0_output_is_ready(self):
        rows = ["✢ Thinking…", "  ⎿  Tip: x", "⏺ done", self.RULE] + self.INPUT
        self.assertEqual(self.cls(rows), ("claude", "ready"))
```

(`HERE` is the module's `board/` dir, already defined at the top of the test file.)

- [ ] **Step 2: Run to verify RED**

Run: `python3 -m unittest discover -s board/tests -p 'test_paneclass*.py'`
Expected: 1 failure, `test_real_turn_start_with_tip_row_is_working`: `('claude', 'ready') != ('claude', 'working')`. (`test_tip_then_column0_output_is_ready` already passes: it guards the new branch.)

- [ ] **Step 3: Implement** — in `board/paneclass.py`, after the `SPINNER_FIRST_RE` line add:

```python
TIP_RE = re.compile(r"^\s*⎿\s+Tip:")   # the tip row a turn starts with, under a first-frame spinner
```

Replace `spinner_live` with:

```python
def spinner_live(rows):
    """True when the lowest spinner line is in the live area above the input box's rule.

    Rows between the spinner and the rule may be blank or indented (a tip, its wrapped line, a task list); a row at
    column 0 (a finished line, `⏺` output, an open prompt) means the spinner is transcript. The first-frame form
    (`✢ Thinking…`, no parenthesis) is live only when the rows before the rule are blank, `⎿ Tip:` rows, or a tip's
    indented continuation lines directly after it; any other indented row means it is transcript."""
    for n in range(len(rows) - 1, -1, -1):
        first = bool(SPINNER_FIRST_RE.match(rows[n]))
        if not (first or SPINNER_RE.match(rows[n])):
            continue
        in_tip = False   # the previous non-blank row was a tip row or its wrapped continuation
        for below in rows[n + 1:]:
            if RULE_RE.match(below):
                return True
            if not below.strip():
                in_tip = False
                continue
            if first:
                if TIP_RE.match(below):
                    in_tip = True
                    continue
                if in_tip and below[0].isspace():
                    continue
                return False
            if not below[0].isspace():
                return False
        return not any(r.strip() for r in rows[n + 1:])   # no rule in view (a short capture): spinner at the bottom
    return False
```

- [ ] **Step 4: Run to verify GREEN, then the mutation**

Run: `python3 -m unittest discover -s board/tests -p 'test_paneclass*.py'` → `OK`.
Mutation: delete the three `if TIP_RE.match(below): … continue` lines, re-run → `test_real_turn_start_with_tip_row_is_working` fails; restore them, re-run → `OK`. Record both runs in the report.

- [ ] **Step 5: Commit**

```bash
git add board/paneclass.py board/tests/test_paneclass.py
git commit -m "fix(board): a tip row keeps a first-frame spinner live"   # plus your harness's attribution trailer
```

```json:metadata
{"files": ["board/paneclass.py", "board/tests/test_paneclass.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_paneclass*.py'", "acceptanceCriteria": ["test_real_turn_start_with_tip_row_is_working loads working.txt and asserts working; RED before the change", "mutation: deleting the TIP_RE branch fails that test", "test_tip_then_column0_output_is_ready: tip then ⏺ done at column 0 is ready", "test_first_frame_shaped_line_in_transcript_is_not_working unchanged and passing", "all paneclass tests pass"], "modelTier": "mechanical"}
```

---

### Task 2: watchdog — shared spinner rule and module-level send_remove

**Goal:** `tools/telegram_watch.py` reads spinners only through `paneclass.spinner_live`, and the key sequence that deletes typed text is a module-level `send_remove` tested by argv and against a real scratch pane.

**Files:**
- Modify: `tools/telegram_watch.py` (`_spinner_above_input` ~173-181 removed, `idle_at_prompt` ~184-188, `_do_reconnect` ~448-477)
- Test: `tools/tests/test_telegram_watch.py` (new classes before `class Safe`)

**Acceptance Criteria:**
- [ ] `_spinner_above_input` no longer exists (`grep -c _spinner_above_input tools/telegram_watch.py` → 0).
- [ ] Every existing watchdog test passes unchanged (60 before this task).
- [ ] `SharedSpinnerRule.test_watchdog_never_idle_where_the_board_sees_a_live_spinner` checks every `.txt` fixture (≥ 10) and finds ≥ 1 with a live spinner; mutation: drop `and not paneclass.spinner_live(rows[-30:])` from `idle_at_prompt` → it fails on `working`.
- [ ] `SendRemove.test_argv` asserts `("send-keys", "-t", "%7", "End", "Left", "Left", "BSpace", "BSpace", "BSpace")` for `(back=2, count=3)`.
- [ ] `SendRemove.test_real_pane`: `abcXYZdef` typed into a scratch `bash --norc --noprofile` pane, `send_remove(t, pane, 3, 3)`, last line reads `$ abcdef`; no `tw-remove-*` tmux server left afterwards (`pgrep -f tw-remove- | wc -l` → 0).
- [ ] `_do_reconnect` passes `remove=lambda back, count: send_remove(t, pane, back, count)`.

**Verify:** `python3 -m unittest discover -s tools/tests -p 'test_telegram_watch.py'` → `OK` (64 tests)

**Steps:**

- [ ] **Step 1: Write the failing tests** — in `tools/tests/test_telegram_watch.py` add `import time` after `import tempfile` (keep the import list sorted), and insert these classes immediately before `class Safe(unittest.TestCase):`:

```python
class SharedSpinnerRule(unittest.TestCase):
    """The watchdog and the board read a spinner with one rule (paneclass.spinner_live)."""

    def test_watchdog_never_idle_where_the_board_sees_a_live_spinner(self):
        names = sorted(p.stem for p in FX.glob("*.txt"))
        self.assertGreaterEqual(len(names), 10)   # every .txt capture in the fixture dir is checked
        live = 0
        for name in names:
            rows = screen(name)
            with self.subTest(name):
                if tw.paneclass.spinner_live(rows[-30:]):
                    live += 1
                    self.assertFalse(tw.idle_at_prompt("claude", rows, None))
                    self.assertFalse(tw.idle_at_prompt("claude", rows, "ready"))   # a fresh mod state that says ready
        self.assertGreaterEqual(live, 1)   # working.txt at least


class SendRemove(unittest.TestCase):
    def test_argv(self):
        calls = []
        tw.send_remove(lambda *a: calls.append(a), "%7", 2, 3)
        self.assertEqual(calls, [("send-keys", "-t", "%7", "End", "Left", "Left", "BSpace", "BSpace", "BSpace")])

    def test_argv_nothing_after(self):
        calls = []
        tw.send_remove(lambda *a: calls.append(a), "%7", 0, 2)
        self.assertEqual(calls, [("send-keys", "-t", "%7", "End", "BSpace", "BSpace")])

    def test_real_pane(self):
        """send_remove against a scratch tmux server: a bash --norc line editor honours End/Left/BSpace (cat does not)."""
        tmux = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
        sock = f"tw-remove-{os.getpid()}"

        def t(*args):
            return subprocess.run([tmux, "-L", sock, "-f", "/dev/null", *args], capture_output=True, text=True, check=True).stdout

        try:
            t("new-session", "-d", "-x", "80", "-y", "6", "env PS1='$ ' /bin/bash --norc --noprofile")
            pane = t("display", "-p", "-t", "0", "#{pane_id}").strip()
            time.sleep(0.5)
            t("send-keys", "-t", pane, "-l", "abcXYZdef")
            time.sleep(0.2)
            tw.send_remove(t, pane, 3, 3)
            deadline = time.time() + 3
            while time.time() < deadline:
                line = [r for r in t("capture-pane", "-p", "-t", pane).splitlines() if r.strip()][-1]
                if line.endswith("abcdef"):
                    break
                time.sleep(0.1)
            self.assertEqual(line, "$ abcdef")
        finally:
            subprocess.run([tmux, "-L", sock, "-f", "/dev/null", "kill-server"], capture_output=True)
```

Probe behind `bash --norc`: on tmux 3.8, `End Left×3 BSpace×3` after typing `abcXYZdef` leaves `abcdef` in `bash --norc --noprofile`, `abcXef~` in `zsh -f` and raw `^[[4~^[[D` in `cat` (run 2026-11-15 by the plan author).

- [ ] **Step 2: Run to verify RED**

Run: `python3 -m unittest discover -s tools/tests -p 'test_telegram_watch.py'`
Expected: the three `SendRemove` tests error with `AttributeError: module 'telegram_watch' has no attribute 'send_remove'`. `SharedSpinnerRule` passes already (Task 1 made `working.txt` live; the old `_spinner_above_input` also blocks it) — it guards the change in Step 3 via the mutation in Step 4.

- [ ] **Step 3: Implement** in `tools/telegram_watch.py`:

1. Delete the whole `def _spinner_above_input(rows, span=8):` function (docstring and body).
2. In `idle_at_prompt`, replace the return line with:

```python
    return not paneclass.input_has_text(rows) and not paneclass.spinner_live(rows[-30:])   # a fresh mod state can say ready over a live spinner
```

3. Insert directly above `def _do_reconnect(pane):`:

```python
def send_remove(t, pane, back, count):
    """Delete `count` characters that end `back` characters before the end of the input line: End, Left×back, BSpace×count."""
    keys = ["End"] + ["Left"] * back + ["BSpace"] * count
    t("send-keys", "-t", pane, *keys)


```

4. In `_do_reconnect`, delete the nested `def remove(back, count): …` (3 lines and the blank line after), and change the `PaneCtl(...)` call's last line to:

```python
                  check, lambda: _pane_idle(pane),
                  remove=lambda back, count: send_remove(t, pane, back, count))
```

- [ ] **Step 4: Run to verify GREEN, then the mutation**

Run: `python3 -m unittest discover -s tools/tests -p 'test_telegram_watch.py'` → `Ran 64 tests … OK`.
Mutation: remove ` and not paneclass.spinner_live(rows[-30:])` from `idle_at_prompt`, re-run → `FAIL: test_watchdog_never_idle_where_the_board_sees_a_live_spinner … [working]`; restore, re-run → `OK`. Then `grep -c _spinner_above_input tools/telegram_watch.py` → `0` and `pgrep -f tw-remove- | wc -l` → `0`. Record all in the report.

- [ ] **Step 5: Commit**

```bash
git add tools/telegram_watch.py tools/tests/test_telegram_watch.py
git commit -m "fix(telegram-watch): shared spinner rule and module-level send_remove"   # plus your harness's attribution trailer
```

```json:metadata
{"files": ["tools/telegram_watch.py", "tools/tests/test_telegram_watch.py"], "verifyCommand": "python3 -m unittest discover -s tools/tests -p 'test_telegram_watch.py'", "acceptanceCriteria": ["_spinner_above_input removed (grep -c → 0)", "every existing watchdog test passes unchanged", "agreement test checks every .txt fixture (>=10), >=1 live; mutation dropping spinner_live from idle_at_prompt fails it on working", "test_argv asserts End Left Left BSpace BSpace BSpace for (2,3)", "test_real_pane leaves '$ abcdef' and no tw-remove- server", "_do_reconnect passes remove=lambda back, count: send_remove(t, pane, back, count)"], "modelTier": "mechanical"}
```

---

### Task 3: real-state check of a turn start on the live dev session

**Goal:** Show, read-only, that a real lead pane in the first second of a turn classifies as `working` with this branch's `paneclass`, and record what the board's `/api/state` showed.

**Files:**
- Create: `docs/superpowers/notes/2026-11-15-turn-start-spinner-real-check.md`
- Maybe: `tools/tests/fixtures/telegram-watch/turn-start-live.txt` (only if the first-frame capture differs in shape from `working.txt`), plus a line for it in that dir's `README.md`

**Acceptance Criteria:**
- [ ] A capture loop (every ≤ 0.25 s, ≥ 20 s, each capture saved with its epoch) ran on the lead's pane (`claude` window of the `agent-board` tmux session) while the lead started a turn; the turn is started by a message the executor sends the lead.
- [ ] The note names the earliest capture showing a first-frame spinner (`SPINNER_FIRST_RE`) and quotes its rows from the spinner to the input rule verbatim.
- [ ] That capture, classified with this worktree's `paneclass.classify(<pane cmd>, rows, False, None)` (no mod state), gives `("claude", "working")`; the note records the command and output. The same capture through `main`'s paneclass (`git show main:board/paneclass.py` to a scratch file) is also recorded.
- [ ] An ephemeral board from the worktree (`TMUX_DASH_PORT=7710 python3 board/server.py`) was polled in the same loop; the note records the lead pane's status from `/api/state` at the capture's epoch, and says whether a mod state drove it (the board prefers a fresh mod state over pane text).
- [ ] If the capture's shape differs from `working.txt` (other rows between spinner and rule), it is added as a fixture and the Task 2 agreement test still passes; otherwise the note says it matches.
- [ ] Nothing is typed into any pane; the ephemeral board is stopped afterwards and its PID checked gone.

**Verify:** see verifyCommand → first line ≥ 6, then `OK`

**Constraints:** read-only against the live session (capture-pane, list-panes, GET requests only). Sending the lead a message through SendMessage is the only trigger. The lead answers with a one-line reply; the capture loop must already be running when the message is sent.

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-15-turn-start-spinner-real-check.md", "tools/tests/fixtures/telegram-watch/turn-start-live.txt", "tools/tests/fixtures/telegram-watch/README.md"], "verifyCommand": "grep -c '^- ' docs/superpowers/notes/2026-11-15-turn-start-spinner-real-check.md && python3 -m unittest discover -s tools/tests -p 'test_telegram_watch.py'", "acceptanceCriteria": ["capture loop <=0.25 s for >=20 s on the lead pane during a turn the executor triggered by message", "earliest first-frame capture named and quoted", "worktree paneclass classify (mod None) gives working; main's result recorded", "ephemeral 7710 board /api/state status recorded with mod-state note", "fixture added only if shape differs; agreement test passes", "nothing typed; board stopped and PID gone"], "modelTier": "standard"}
```

---

### Task 4: paneclass — task-label spinners, task-list rows and the teammate status row

Added 2026-11-15 after Task 3's live run: on Claude Code 2.1.325, a lead with an in-progress task shows that task's subject as the spinner label (`✶ Plan & run: docs/…/x.md…`, later `… (2s · ↓ 7 tokens)`), the task list under it (`  ⎿  ◼ …`, `     ◻ …`, `      … +13 pending, 5 completed`), and, with teammates, a column-0 row `busy 1 · ready 1   …   [-]` right above the input rule. Both `main` and Tasks 1–2 classify those frames `ready`.

**Goal:** `classify` returns `("claude", "working")` for the real fixtures `turn-start-task-label.txt` and `turn-start-task-label-elapsed.txt`, and `("claude", "ready")` for `idle-with-teammates.txt`, with every earlier verdict unchanged.

**Files:**
- Modify: `board/paneclass.py` (`SPINNER_RE`, `SPINNER_FIRST_RE`, `spinner_live`; new `TASKLIST_RE`, `TEAM_ROW_RE`)
- Test: `board/tests/test_paneclass.py`, `tools/tests/test_telegram_watch.py`

**Constraints:**
- Spinner label: any text, may contain spaces, ending in `…`, after a leading spinner glyph from the set `·✢✳✶✻✽*` (the glyphs used in this repo's tests and real fixtures). `⏺`, `⎿` and box characters never start a spinner, so `⏺ Let me check…` in transcript is never a spinner. The elapsed form keeps `\(\d+\s*[hms]\b[^)]*\)?` after the `…`.
- Under a first-frame spinner, task-list rows count like tip rows: an indented row whose first non-space characters are `⎿` followed by a task glyph (`◼`, `◻`, `✔`, `☐`, `☒`), an indented row starting with a task glyph, and an indented `… +N …` summary row.
- The teammate status row (`^busy \d+ · ready \d+`, column 0, as captured) is skipped wherever it sits between a spinner and the rule, for both forms. Write the regex from the fixture bytes; no other column-0 row is skipped.
- Everything Tasks 1–2 pinned stays: `["✢ Thinking…", "  some indented output", RULE]` → `ready`; tip then `⏺ done` → `ready`; `working.txt` → `working`; every watchdog fixture keeps its verdict (`idle-with-teammates` joins the idle list in `Screens.test_idle_screens_are_idle`).

**Acceptance Criteria:**
- [ ] New paneclass tests over the three real fixtures give `working`, `working`, `ready`; RED on the code before this task for the two `working` cases.
- [ ] New synthetic tests: `["⏺ Let me check…", "", RULE]` → `ready`; `["✶ Plan & run: x.md…", "  ⎿  ◼ Plan & run: x.md", "     ◻ Task 2", "", RULE]` → `working`; the same with a column-0 `"⏺ done"` before the rule → `ready`; `["✻ Thinking… (3s · ↓ 1 tokens)", "busy 1 · ready 1   [-]", RULE]` → `working`.
- [ ] Mutations, each run once and recorded: (1) drop the team-row skip → the elapsed fixture test fails; (2) restrict the label back to `[\w-]+` → the first-frame fixture test fails; (3) drop the task-list branch → the first-frame fixture test fails.
- [ ] `idle-with-teammates` is idle in the watchdog; the agreement test passes and now counts ≥ 3 live fixtures (raise its `live >= 1` to `live >= 3`).
- [ ] Both suites pass.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_paneclass*.py' && python3 -m unittest discover -s tools/tests -p 'test_telegram_watch.py'`

```json:metadata
{"files": ["board/paneclass.py", "board/tests/test_paneclass.py", "tools/tests/test_telegram_watch.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_paneclass*.py' && python3 -m unittest discover -s tools/tests -p 'test_telegram_watch.py'", "acceptanceCriteria": ["real fixtures: task-label working, task-label-elapsed working, idle-with-teammates ready; RED before for the two working", "synthetic: ⏺ Let me check… ready; task label + task rows working; + column-0 ⏺ done ready; elapsed + busy row working", "three mutations each fail the named test", "idle-with-teammates idle in watchdog; agreement test live >= 3", "both suites pass"], "modelTier": "standard"}
```
