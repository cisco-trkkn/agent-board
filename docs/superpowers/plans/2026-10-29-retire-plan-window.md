# Retire the `plan` window: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dev sessions no longer get a `plan` window. An existing one is closed when the layout runs again, the renderer code goes, and the docs and lead rules stop mentioning it.

**Architecture:**
- `bin/dev` and `bin/tmux-dev-layout` stop creating `plan`. The layout closes a `plan` window only when its pane's `#{pane_start_command}` contains `tmux-plan`.
- `bin/tmux-plan` and the `render`/`watch` half of `board/planview.py` are deleted. `view()` stays, because the queued overseer and night-mode plans read it.
- Docs and rules lose the window, and the queued teams plan drops its per-team `plan` window.

**Tech Stack:** zsh (bin/, tools/tests), Python 3 unittest (board/), Markdown.

**Spec:** `docs/superpowers/specs/2026-10-29-retire-plan-window-design.md`

## Global Constraints

- A `plan` window is closed only when its pane's `#{pane_start_command}` contains `tmux-plan`. Any other window named `plan` is never touched.
  - Probe, 2026-10-29, tmux 3.8, on the live server (`tmux list-panes -a -F '#{session_name}:#{window_name} | #{pane_start_command} | #{pane_current_command}'`): all 14 live `plan` windows show `"/Users/francisco.ruiz/agent-board/bin/tmux-plan <session> <root>"` as the start command and `Python` as the current command.
  - So match on the start command; the current command is useless for this.
  - The existing `test_layout.zsh` check "plan window runs tmux-plan" already reads `#{pane_start_command}` on a scratch server.
- `board/planview.py` `view()`, its `view` CLI subcommand, and every `view()` test stay byte-identical in behaviour.
- Historical specs, plans, reports and ledgers dated before 2026-10-29 are not edited, except the teams plan amendment in Task 3.
- Scratch tmux servers start with `-f /dev/null`; `tools/tests/lib.zsh` already does this.
- Suite verdicts:
  - `run-all.zsh` has no summary line, so read its exit code alone (`zsh tools/tests/run-all.zsh; echo rc=$?`, nothing chained after it) plus an uncapped `grep -c FAIL` of its output;
  - the board suite's verdict is its own `Ran N tests … OK` line.
- Commits: conventional with scope (`feat(dev): …`, `refactor(board): …`, `docs(rules): …`), ending with the attribution trailer your harness specifies.
- Work in the worktree `/Users/francisco.ruiz/agent-board/.claude/worktrees/retire-plan-window` on branch `feat/retire-plan-window`. The live checkout `~/agent-board` stays on `main`.

**User decisions (already made):**
- "Remove the window": not opt-in, not kept with fixes.
- `board/planview.py` `view()` stays.
- The queued teams plan's per-team `plan` window and its `bin/tmux-plan` edit are dropped.

---

### Task 1: Layout stops creating `plan` and closes an old one

**Goal:** `dev` and `tmux-dev-layout` create no `plan` window; a re-layout closes one whose pane started `tmux-plan` and leaves any other `plan` window alone; `bin/tmux-plan` and `tools/tests/e2e-plan-window.zsh` are deleted.

**Files:**
- Modify: `bin/tmux-dev-layout` (header comment lines 2-3; line 56, the `has_win "$sess" plan || t new-window … tmux-plan …` line)
- Modify: `bin/dev` (header line 3; line 22, the `tc_tmux new-window … -n plan … tmux-plan …` line)
- Modify: `config/tmux.conf:32` (comment: "the claude and plan windows" → "the claude window")
- Modify: `docs/INSTALL.md:96` (comment: "windows claude (the lead) and plan" → "window claude (the lead)")
- Delete: `bin/tmux-plan`
- Delete: `tools/tests/e2e-plan-window.zsh`
- Test: `tools/tests/test_layout.zsh`

**Acceptance Criteria:**
- [ ] A fresh `dev` session has exactly the user window `claude`: `wins proj` = `"claude "`.
- [ ] A re-layout of a session with a `plan` window whose pane start command contains `tmux-plan` closes it. `claude` keeps its index.
- [ ] A re-layout of a session with a user window named `plan` running `sleep 600` leaves it in place.
- [ ] Every other existing `test_layout.zsh` check still passes. The `plan`-specific checks are replaced:
  - "user windows", "idempotent", "busy gains plan" and "dev windows" now expect no `plan`;
  - "plan window runs tmux-plan" and "plan right after claude" are removed.
- [ ] `bin/tmux-plan` and `tools/tests/e2e-plan-window.zsh` no longer exist.
- [ ] `zsh tools/tests/run-all.zsh` exits 0.

**Verify:** `zsh tools/tests/test_layout.zsh` → every line `ok`, no `FAIL`, exit 0

**Steps:**

- [ ] **Step 1: Write the failing tests.** In `tools/tests/test_layout.zsh`:
  - change the expectations `"claude plan "` → `"claude "` (the "user windows" check at line 10, and "dev windows" at line 48);
  - change `"claude plan |shell tests "` → `"claude |shell tests "` ("idempotent", line 17);
  - change `"claude plan shell "` → `"claude shell "` ("busy gains plan", line 35; rename the check to "busy has no plan");
  - delete the "plan window runs tmux-plan" check (line 12) and the whole "plan right after claude" block (lines 36-41, the `ord` session).

  Then add, after the `busy` checks:

```zsh
# an old plan window (it started tmux-plan) is closed on re-layout; a user window named plan is not
tt new-session -d -s oldplan -n claude -c "$TT_DIR"
tt new-window -d -a -t '=oldplan:claude' -n plan -c "$TT_DIR" "sleep 600 # $TT_REPO/bin/tmux-plan oldplan $TT_DIR"
ci="$(tt list-windows -t '=oldplan' -F '#{window_name} #{window_index}' | awk '$1=="claude"{print $2}')"
"$L" oldplan "$TT_DIR"
check "old plan closed"   test "$(wins oldplan)" = "claude "
check "claude index kept" test "$(tt list-windows -t '=oldplan' -F '#{window_name} #{window_index}' | awk '$1=="claude"{print $2}')" = "$ci"
tt new-session -d -s userplan -n claude -c "$TT_DIR"; tt new-window -d -t '=userplan:' -n plan -c "$TT_DIR" 'sleep 600'
"$L" userplan "$TT_DIR"
check "user plan kept"    test "$(wins userplan)" = "claude plan "
```

  The `oldplan` window's start command contains the literal `tmux-plan` path, as on the live server, but runs `sleep 600`, so the test never starts a real renderer. Probe, 2026-10-29, tmux 3.8, scratch server: start command `"sleep 600 # /x/bin/tmux-plan oldplan /tmp"`, current command `sleep`, and the `*tmux-plan*` match fires. Killing the window in the real session also removed it from a grouped session (`new-session -t`). Mutations:
  - remove the close logic → "old plan closed" fails;
  - match on `pane_current_command` instead → "old plan closed" fails, because the current command is `sleep`;
  - drop the `tmux-plan` match and close any `plan` window → "user plan kept" fails.

- [ ] **Step 2: Run to see RED.** Run: `zsh tools/tests/test_layout.zsh`. Expected: `FAIL - user windows`, `FAIL - idempotent`, `FAIL - busy has no plan`, `FAIL - dev windows` and `FAIL - old plan closed` (the layout still adds `plan` and never closes one). "user plan kept" passes already.

- [ ] **Step 3: Implement.** In `bin/tmux-dev-layout`, replace line 56 with:

```zsh
# the retired plan window (2026-10-29): close it only if its pane started tmux-plan; a user window named plan stays
if has_win "$sess" plan && [[ "$(t display -p -t "=${sess}:plan" '#{pane_start_command}')" == *tmux-plan* ]]; then
  t kill-window -t "=${sess}:plan"
fi
```

  In the header, line 2, change "The user keeps `claude` and `plan` (a throwaway shell is prefix S)" to "The user keeps `claude` (a throwaway shell is prefix S)". In `bin/dev`:
  - delete line 22, the `tc_tmux new-window … -n plan …` line;
  - change header line 3 to `# Windows: 1 claude (a throwaway shell is prefix S). Agent windows live in the hidden session <name>-bg.  Run it again and it just reattaches.`

  Keep the rest of line 3 exactly; `dev --help` prints lines 2-3. Edit `config/tmux.conf:32` and `docs/INSTALL.md:96` as listed under Files. Then `git rm bin/tmux-plan tools/tests/e2e-plan-window.zsh`.

- [ ] **Step 4: Run to see GREEN.** Run: `zsh tools/tests/test_layout.zsh; echo rc=$?`. Expected: no `FAIL` line, `rc=0`. Then run the whole tools suite with `tmux-ctl run -t 900 tests "zsh tools/tests/run-all.zsh > <scratch>/runall.out 2>&1; echo rc=\$?"`. Report `rc=` and `grep -c FAIL <scratch>/runall.out` (uncapped). If `test_bg.zsh` alone fails on `interrupted exit 143`, `interrupted summary` or `no stuck records`, that is the known load flake (spec `2026-10-29-board-bugs-design.md` §d): re-run `zsh tools/tests/test_bg.zsh` alone, on an idle machine, and report both runs.

- [ ] **Step 5: Commit.**

```bash
git add bin/dev bin/tmux-dev-layout config/tmux.conf docs/INSTALL.md tools/tests/test_layout.zsh
git commit -m "feat(dev): retire the plan window; re-layout closes an old one"
```

  The two `git rm` deletions are already staged. End the message with your harness's attribution trailer.

```json:metadata
{"files": ["bin/dev", "bin/tmux-dev-layout", "bin/tmux-plan", "config/tmux.conf", "docs/INSTALL.md", "tools/tests/test_layout.zsh", "tools/tests/e2e-plan-window.zsh"], "verifyCommand": "zsh tools/tests/test_layout.zsh", "acceptanceCriteria": ["fresh dev session windows = 'claude '", "re-layout closes a plan window whose pane_start_command contains tmux-plan; claude index unchanged", "a user window named plan running sleep 600 is left alone", "other test_layout checks pass; plan-specific checks replaced as listed", "bin/tmux-plan and tools/tests/e2e-plan-window.zsh deleted", "run-all.zsh exits 0"], "modelTier": "standard"}
```

### Task 2: `planview.py` keeps `view()` only

**Goal:** `board/planview.py` loses the tmux-window renderer (`render`, `watch`, `GLYPHS`, and the helpers only they use) and the `watch` CLI choice. `view()`, `_snapshot()` and the `view` subcommand behave exactly as before.

**Files:**
- Modify: `board/planview.py` (docstring lines 2-7; `GLYPHS` at line 194; `display_width`, `clip` and `render` at 199-243; `watch` at 248-262; `main()` choices at 266 and the `watch` branch at 273-274)
- Modify: `board/tests/test_planview.py`:
  - delete `class TestRender` (line 228 on);
  - in `TestCli`, delete `test_watch_draws_once_and_exits_zero_on_sigint`, `test_watch_redraws_only_when_lines_change`, `test_watch_survives_an_iteration_that_raises_and_builds_the_runner_once` and `test_tmux_plan_script_runs_watch`;
  - keep `test_snapshot_reads_sessions_and_tasks_under_dot_claude` and every `TestPlanview`, `TestPaneState` and `view` CLI test.
- Modify: `board/tests/fixtures/planview/README.md`, only if it mentions the `plan` window or `watch`.

**Acceptance Criteria:**
- [ ] `grep -nE 'def (render|watch|display_width|clip)\b|GLYPHS|"watch"' board/planview.py` prints nothing, and `grep -c 'def ' board/planview.py` is printed beside it, so the empty result is not an empty file. `display_width` and `clip` are deleted only if no remaining function calls them; check with `grep -n 'display_width\|clip(' board/planview.py`.
- [ ] `python3 board/planview.py watch x --root .` exits non-zero with argparse's "invalid choice". `python3 board/planview.py view nosuch --root .` still prints the empty view, as `test_view_without_tmux_prints_empty_line` asserts.
- [ ] Every remaining test in `board/tests/test_planview.py` passes, and no `view()` test was edited. Check with `git diff main -- board/tests/test_planview.py`, which shows only deletions.
- [ ] The docstring no longer says "for the tmux `plan` window". It says the module reads the active plan's tasks and their owners' pane state for board consumers (`view()`).

**Verify:** `python3 -m unittest board.tests.test_planview` → `OK`

**Steps:**
- [ ] **Step 1:** Delete the four tests and `TestRender` from `board/tests/test_planview.py`. Run `python3 -m unittest board.tests.test_planview` and note the count; it is green, because nothing new is asserted yet.
- [ ] **Step 2:** Add one CLI test to `TestCli`. Mutation: leave `"watch"` in the choices → this test fails.

```python
    def test_watch_subcommand_is_gone(self):
        r = subprocess.run([sys.executable, "-I", str(HERE / "planview.py"), "watch", "x", "--root", "."],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invalid choice", r.stderr)
```

  Use the module's existing `HERE`/`subprocess`/`sys` imports; check how the other `TestCli` tests reference `planview.py` and match them. Run it and see RED: `watch` is still a valid choice, so the assertion on the exit code fails.
- [ ] **Step 3:** Remove `GLYPHS`, `render`, `watch`, the `watch` choice and branch in `main()`, and `display_width`/`clip` if nothing else calls them. Fix the docstring. Drop imports that only the removed code used (`shutil`, `time`, `unicodedata`). Check each one with `grep -n` before removing it.
- [ ] **Step 4:** `python3 -m unittest board.tests.test_planview` → `OK`. Then run the board suite: `tmux-ctl run -t 600 tests "python3 -m unittest discover -s board/tests"` → `Ran N tests … OK`. Quote both summary lines.
- [ ] **Step 5:** Commit: `git add board/planview.py board/tests/test_planview.py` (plus the fixtures README if changed), message `refactor(board): planview keeps view() only; the plan window renderer is gone`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["board/planview.py", "board/tests/test_planview.py", "board/tests/fixtures/planview/README.md"], "verifyCommand": "python3 -m unittest board.tests.test_planview", "acceptanceCriteria": ["no render/watch/GLYPHS/watch choice left in planview.py (grep empty, def count printed)", "watch subcommand fails with invalid choice; view subcommand unchanged", "remaining test_planview tests pass; diff vs main on the test file is deletions plus the one new CLI test", "docstring no longer mentions the tmux plan window"], "modelTier": "standard"}
```

### Task 3: Docs, lead rules and the queued teams plan

**Goal:** Nothing outside dated history still describes a `plan` window. The queued teams plan no longer adds per-team `plan` windows or edits `bin/tmux-plan`.

**Files:**
- Modify: `claude/orchestrator.md:160` (delete the `plan` row of "The session's windows" table; then search the file for any other `plan` *window* mention)
- Modify: `claude/skills/tmux-orchestrator/SKILL.md:16` and `claude/plugin/skills/tmux-orchestrator/SKILL.md:16` (delete the same row)
- Modify: `docs/ARCHITECTURE.md`:
  - line 15: drop `plan (tasks)<br/>` from the mermaid node;
  - lines 49, 67 and 68: remove the `plan` window from each prose description;
  - anywhere else in the file that describes the window.
- Modify: `docs/superpowers/plans/2026-10-28-teams-in-one-project.md`:
  - Task 5: drop the `bin/tmux-dev-layout` "(ensure `<t>·plan` next to each `<t>·claude`)" part and the whole `bin/tmux-plan` Files line;
  - drop every acceptance criterion and step about `<t>·plan` or `tmux-plan`, and fix that task's `json:metadata` `files` list;
  - add one line under the plan header: `> 2026-10-29: the plan window was retired (docs/superpowers/specs/2026-10-29-retire-plan-window-design.md); Task 5 no longer adds a per-team plan window.`
- Modify: `docs/superpowers/plans/2026-10-28-teams-in-one-project.md.tasks.json`: apply the same Task 5 change to that task's `description` and its embedded metadata; leave `status` as it is.

**Acceptance Criteria:**
- [ ] Run `grep -rn 'tmux-plan\|plan window\|`plan`' bin claude board tools config docs/ARCHITECTURE.md docs/INSTALL.md docs/CUSTOMIZATION.md README.md`. The only hits left are:
  - `board/planview.py` text that refers to plan *files*;
  - lines that mean a plan file or a plan run, not the window.
  Print the full hit list in the report, uncapped, with its count.
- [ ] Two greps on the teams plan, `grep -n 'tmux-plan\|·plan' docs/superpowers/plans/2026-10-28-teams-in-one-project.md` and `grep -c 'tmux-plan\|·plan' docs/superpowers/plans/2026-10-28-teams-in-one-project.md.tasks.json`, find nothing except the new header note.
- [ ] `python3 -c "import json;json.load(open('docs/superpowers/plans/2026-10-28-teams-in-one-project.md.tasks.json'))"` exits 0.
- [ ] `zsh tools/tests/test_plugin.zsh` passes. It checks the plugin's skill files, so it covers the edited plugin `SKILL.md`.

**Verify:** `zsh tools/tests/test_plugin.zsh` → no `FAIL`, exit 0

**Steps:**
- [ ] **Step 1:** Make the edits listed under Files. Keep the surrounding Markdown tables well-formed: same column count, no empty row.
- [ ] **Step 2:** Run the three grep checks and the JSON check from the acceptance criteria; fix any remaining hit that describes the window.
- [ ] **Step 3:** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `rc=0`.
- [ ] **Step 4:** Commit:
  - `git add` the files listed above, by path;
  - message `docs(rules): drop the plan window from the lead rules, skills, architecture and the teams plan`;
  - end the message with your harness's attribution trailer.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/skills/tmux-orchestrator/SKILL.md", "claude/plugin/skills/tmux-orchestrator/SKILL.md", "docs/ARCHITECTURE.md", "docs/superpowers/plans/2026-10-28-teams-in-one-project.md", "docs/superpowers/plans/2026-10-28-teams-in-one-project.md.tasks.json"], "verifyCommand": "zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["window mentions gone outside dated history; full grep hit list with count in the report", "teams plan and its tasks.json carry no tmux-plan / ·plan except the header note", "teams tasks.json parses", "test_plugin.zsh exits 0"], "modelTier": "standard"}
```

### Task 4: Real-state check of the re-layout

**Goal:** Prove, read-only, that the new close condition matches every real `plan` window on the live tmux server and nothing else. The layout is never run against a live session.

**Files:**
- Create: `docs/superpowers/plans/2026-10-29-retire-plan-window-e2e-report.md`

**Acceptance Criteria:**
- [ ] The report holds the output of this, run on the live server (the user's default socket, `$TMUX`, NOT `-L agent-board`, which has 0 windows) at the time of the check:

  `tmux list-panes -a -F '#{session_name}:#{window_name} | #{pane_start_command}'`

  It also records three counts, each from an uncapped `grep -c`:
  1. windows named `plan`;
  2. of those, the ones whose start command contains `tmux-plan`;
  3. windows NOT named `plan` whose start command contains `tmux-plan`, which must be 0.
- [ ] The report states which sessions a `dev` re-run would clean: the real sessions, not their `_web-*` group views. A group view shares the window, so killing it in the real session removes it from the group too. Back this with one probe on a scratch server (`-f /dev/null`): create a session, a grouped session, and a `plan` window started with `tmux-plan` in its command. Run the new `bin/tmux-dev-layout` on the real session, then show `list-windows` for both. The window must be gone from both.
- [ ] Nothing was run against the live server except `list-panes`/`list-windows`/`display`. The report says so and lists the commands.

**Verify:** `grep -c '^## ' docs/superpowers/plans/2026-10-29-retire-plan-window-e2e-report.md` → `4` (Live windows, Counts, Group-view probe, Commands run)

```json:metadata
{"files": ["docs/superpowers/plans/2026-10-29-retire-plan-window-e2e-report.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/plans/2026-10-29-retire-plan-window-e2e-report.md", "acceptanceCriteria": ["live list-panes output with three uncapped counts (plan windows; of those with tmux-plan; non-plan windows with tmux-plan = 0)", "scratch-server probe: grouped session loses the plan window when the layout runs on the real session", "only read-only tmux commands against the live server, listed"], "modelTier": "standard"}
```

## Task order

- Tasks 1, 2 and 3 touch disjoint files.
- Task 4 needs Task 1's layout.
- The plan's executor may run Tasks 1-3 in parallel.
