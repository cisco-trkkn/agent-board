# Plan Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dev session's idle user `shell` window (slot 2) with a live `plan` window showing the active plan's tasks, their owners and whether an owner needs the user, and move the on-demand shell to a `` prefix ` `` popup.

**Architecture:** A pure Python module `board/planview.py` builds a view dict from files (`~/.claude/sessions`, `~/.claude/tasks`, the artifacts manifest, `<plan>.md.tasks.json`) and tmux (lead pane lookup, owner pane state through `board/paneclass.py`), renders it to lines, and has a `watch` loop. `bin/tmux-plan` execs that loop; `bin/dev` and `bin/tmux-dev-layout` put it in window 2; `config/tmux.conf` binds the popup.

**Tech Stack:** Python 3 stdlib (unittest), zsh, tmux 3.8.

**Spec:** `docs/superpowers/specs/2026-10-28-plan-window-design.md`

## Global Constraints

- Work in a worktree under `.claude/worktrees/`; never edit `/Users/francisco.ruiz/agent-board` itself (it is the live install).
- Window name is exactly `plan`; teammate windows are `✦ <owner>`; the lead window is `claude`.
- Glyphs: `✓` completed, `▶` in_progress, `·` pending, `✗` blocked. Header `<plan name> · <done>/<total> done`. Inactive line `no active plan`. Empty view `no plans yet · prefix ` for a shell` (with a literal backtick).
- Refresh every 2 s, redraw only when the rendered lines changed.
- `planview` never raises on missing/unreadable files or a missing tmux target: it returns an empty or partial view.
- Tests never read the real HOME or the real state dir: paths are parameters; tmux is an injected callable (`tmux(*args, check=False) -> stdout`, the shape `paneclass.tmux_runner()` returns).
- Scratch tmux only via `tools/tests/lib.zsh` (`-f /dev/null`).
- Fixtures under `board/tests/fixtures/planview/` are captured from real files, scrubbed, with a `README.md` stating origin.
- Commits: conventional with scope (`feat(board): …`, `feat(dev): …`, `docs(rules): …`), ending with the attribution trailer your harness specifies.
- `tools/tests/run-all.zsh` prints no aggregate: judge it only by `zsh tools/tests/run-all.zsh > F; echo rc=$?` and `grep -c '^FAIL' F`.

**User decisions (already made):**
- "Pinned plan/tasks view" replaces the shell window.
- Contents: "Plan + owners" — tasks with status, in-progress rows tagged with teammate and its state.
- Idle state: "Last plan, dimmed".
- Approach A: standalone renderer over a shared Python module, no board-server dependency; popup shell on a key.
- Active plan: "Lead's task list" is the live source; plan name from the newest plan this lead registered in the artifacts manifest.

**Facts probed at plan time (2026-10-28):**
- `~/.claude/sessions/<pid>.json` has `sessionId` and `tmux` like `_web-60589:@80.%82` (`<prefix>:<window_id>.<pane_id>`), plus `updatedAt` (ms).
- Tasks: `~/.claude/tasks/session-<first 8 chars of sessionId>/<id>.json` with `id`, `subject`, `status` (`pending|in_progress|completed`), `blockedBy` (list of ids), `owner` (teammate name, e.g. `"parse"`; absent when unowned). Completed tasks persist while any task is open; the whole list is cleared once all are completed.
- Manifest `$TC_STATE/artifacts-<project>.jsonl` lines: `{"ts", "path", "kind", "session_id", ...}`; mark lines have no `kind`. `<plan>.md.tasks.json` is `{"planPath", "tasks": [{"id","subject","status","blockedBy"?...}], "lastUpdated"}`.
- `tmux bind '`' display-popup -E -w 80% -h 80% -d "#{pane_current_path}" -T " shell " zsh` is accepted by tmux 3.8 and listed by `list-keys -T prefix`.

---

### Task 1: planview data model

**Goal:** `board/planview.py` `view()` returns the active plan's tasks with owner state, with both fallbacks, from injected paths and tmux.

**Files:**
- Create: `board/planview.py`
- Create: `board/tests/test_planview.py`
- Create: `board/tests/fixtures/planview/` (captured `sessions/`, `tasks/session-xxxxxxxx/`, `artifacts-proj.jsonl`, `repo/docs/superpowers/plans/*.md.tasks.json`, `README.md`)

**Acceptance Criteria:**
- [ ] `view(session, root, home, state_dir, tmux)` returns `{"name": str, "active": bool, "tasks": [{"id","subject","status","owner","state"}]}`; `status` ∈ `completed|in_progress|pending|blocked`; `state` ∈ `working|waiting|ready|gone|""`.
- [ ] Lead = the sessions entry whose `tmux` field ends with `<window_id>.<pane_id>` of `=<session>:claude` (newest `updatedAt` on ties).
- [ ] Tasks sorted by numeric id; `blocked` = pending with any `blockedBy` id not completed.
- [ ] Owner state from `paneclass.pane_status` on window `✦ <owner>`: claude/working→`working`, claude/waiting→`waiting`, other→`ready`, no window→`gone`.
- [ ] Name = basename without `.md` of the newest manifest line with `kind == "plan"` and this lead's `session_id`.
- [ ] Live list empty → tasks from that plan's `.md.tasks.json`, `active: false`; no plan line → newest `root/docs/superpowers/plans/*.md.tasks.json`, `active: false`; nothing → `{"name": "", "active": false, "tasks": []}`.
- [ ] Missing dirs/files, bad JSON, and a tmux callable that raises or returns empty all give an empty/partial view, no exception.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_planview.py' -v` → all OK

**Steps:**

- [ ] **Step 1: Capture fixtures.** Copy one real `~/.claude/sessions/*.json`, three real task files from a `~/.claude/tasks/session-*` dir that has an `owner` (e.g. `session-201273be`), two real manifest lines and one real `docs/superpowers/plans/*.md.tasks.json`. Scrub: replace sessionIds with `11111111-…`/`22222222-…`, names/paths with `proj`, descriptions with `x`. Keep every key. Write `README.md` naming each source file and the scrub. Add a second sessions entry for a different pane (the decoy for the lead-match test).

- [ ] **Step 2: Write failing tests** in `board/tests/test_planview.py` (unittest, fixtures copied to a `tempfile.TemporaryDirectory` per test so tests can mutate them). A fake tmux:

```python
def fake_tmux(claude_pane="@80.%82", windows=(("claude", "%82"), ("✦ parse", "%90")), status=None):
    status = status or {}
    def run(*args, check=False):
        if args[0] == "display" and "#{window_id}.#{pane_id}" in args[-1]:
            return claude_pane + "\n"
        if args[0] == "list-windows":
            return "".join(f"{n}\t{p}\n" for n, p in windows)
        raise AssertionError(args)
    run.status = status
    return run
```

Owner state is read through `planview.pane_state(tmux, pane)`, a thin wrapper over `paneclass.pane_status` that tests patch (`unittest.mock.patch("planview.pane_state", side_effect=...)`) so no `capture-pane` is faked. Tests, each with the mutation that must fail it:
  - `test_lead_matched_by_claude_pane` — two sessions entries, only the second matches → its tasks shown. Mutation: take the first entry → fails.
  - `test_tasks_sorted_numerically` — ids `2, 10, 1` → `1, 2, 10`. Mutation: string sort → fails.
  - `test_pending_with_open_blocker_is_blocked` and `test_pending_with_done_blocker_is_pending`. Mutation: drop the blockedBy check → first fails.
  - `test_owner_state_mapping` — working/waiting/ready and a missing `✦` window → `gone`. Mutation: map waiting→ready → fails.
  - `test_name_from_newest_plan_line_of_this_lead` — another session's newer plan line is ignored; mark lines (no `kind`) skipped.
  - `test_empty_live_list_falls_back_to_tasks_json` → `active False`, tasks from the plan's `.tasks.json`. Mutation: remove fallback → fails.
  - `test_no_plan_line_falls_back_to_newest_repo_tasks_json`.
  - `test_nothing_gives_empty_view`, `test_missing_home_and_bad_json_do_not_raise`, `test_tmux_raising_gives_empty_view`.

- [ ] **Step 3: Run RED.** `python3 -m unittest discover -s board/tests -p 'test_planview.py' -v` → errors on `import planview` (module missing). Then add a stub `view()` returning the empty view and confirm the tests FAIL on assertions, not import.

- [ ] **Step 4: Implement** `board/planview.py`. Module header like `board/paneclass.py` (docstring, `sys.path.insert(0, …)` so `python3 -I` works, `import paneclass, tc_env`). Functions: `lead_session(session, home, tmux) -> str`, `live_tasks(home, sid) -> list`, `plan_entry(state_dir, project, sid) -> Path|None`, `file_tasks(path) -> list`, `pane_state(tmux, pane) -> str`, `owner_states(session, tasks, tmux)`, `view(...)`. The tmux calls are `tmux("display", "-p", "-t", f"={session}:claude", "#{window_id}.#{pane_id}")` and `tmux("list-windows", "-t", f"={session}", "-F", "#{window_name}\t#{pane_id}")`. Project for the manifest = `session`. Wrap every file and tmux step in `try/except (OSError, ValueError, RuntimeError, subprocess.SubprocessError)`.

- [ ] **Step 5: Run GREEN**, then run each named mutation once and record that its test fails; revert.

- [ ] **Step 6: Commit** `feat(board): planview data model for the plan window`.

```json:metadata
{"files": ["board/planview.py", "board/tests/test_planview.py", "board/tests/fixtures/planview/"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_planview.py' -v", "acceptanceCriteria": ["view() returns name/active/tasks with status and state enums", "lead matched by claude pane window_id.pane_id", "numeric sort and derived blocked", "owner state mapping incl. gone", "plan name from newest plan line of this lead", "both fallbacks set active false; nothing gives empty view", "no exception on missing files, bad JSON or failing tmux"], "modelTier": "standard"}
```

### Task 2: render, watch loop and bin/tmux-plan

**Goal:** `planview.render(view, width, color)` produces the window's lines, `planview.py watch` redraws on change every 2 s, and `bin/tmux-plan <session> <root>` runs it.

**Files:**
- Modify: `board/planview.py` (add `render`, `main` with `view` and `watch` subcommands)
- Create: `bin/tmux-plan`
- Modify: `board/tests/test_planview.py` (render and CLI tests)

**Acceptance Criteria:**
- [ ] Header `<name> · <done>/<total> done`; rows `<glyph> <subject>` with glyphs from Global Constraints; in-progress rows with an owner end ` → <owner> (<state>)`.
- [ ] Every line ≤ `width` display columns; a long subject is cut with `…`, the owner suffix kept whole.
- [ ] `color=True`: a `waiting` suffix in bold red (`\033[1;31m…\033[0m`); `active False` rows dim (`\033[2m…\033[0m`) and a `no active plan` line after the header. `color=False` emits no escape bytes.
- [ ] Empty view → exactly one line `no plans yet · prefix ` for a shell`.
- [ ] `python3 board/planview.py view <session> --root <dir> [--json]` prints the rendered lines (or the view as JSON); `watch` loops: compute, render at the terminal width, clear and print only when lines changed, sleep 2 s; exits 0 on SIGINT without a traceback.
- [ ] `bin/tmux-plan` is executable zsh: `exec python3 -I "${0:A:h:h}/board/planview.py" watch "$@"`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_planview.py' -v` → all OK

**Steps:**

- [ ] **Step 1: Failing tests** (snapshot, `color=False`, width 40): a 3-task active view; truncation of a 60-char subject with an owner suffix (assert `len(line) <= 40`, ends with `→ parse (working))`, contains `…`); inactive view (`no active plan` second line); empty view; `color=True` waiting row contains `\033[1;31m` and an inactive row starts with `\033[2m`; `color=False` output contains no `\033`. CLI test: `subprocess.run([sys.executable, "-I", "board/planview.py", "view", "nosuch", "--root", tmp], env={..., "HOME": tmp, "TC_STATE": tmp, "TC_TMUX": "/nonexistent"})` → rc 0, stdout `no plans yet · prefix ` for a shell`. Mutation: drop the width cut → truncation test fails.
- [ ] **Step 2: RED** run, failing on missing `render`.
- [ ] **Step 3: Implement.** Width with `shutil.get_terminal_size((80, 24)).columns`; clear with `\033[H\033[2J`; tmux from `paneclass.tmux_runner()`, home `Path.home()`, state dir `tc_env.state_dir()`. Catch `KeyboardInterrupt` in `main` and return 0.
- [ ] **Step 4: GREEN**, run the mutation once, revert.
- [ ] **Step 5: Manual check** on a scratch server: `~/.local/bin/tmux -L pw-$$ -f /dev/null new-session -d -s pw "bin/tmux-plan pw $PWD"`, then `capture-pane -p -t '=pw:'` shows `no plans yet…`; kill the server with `kill-server` on that socket. Paste the capture in the report.
- [ ] **Step 6: Commit** `feat(board): plan window renderer and tmux-plan`.

```json:metadata
{"files": ["board/planview.py", "bin/tmux-plan", "board/tests/test_planview.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_planview.py' -v", "acceptanceCriteria": ["header and glyph rows with owner suffix", "lines fit width, subject cut with ellipsis, suffix kept", "color: waiting bold red, inactive dim, no escapes without color", "empty view single line", "view/watch CLI, redraw on change, clean SIGINT", "bin/tmux-plan execs watch"], "modelTier": "standard"}
```

### Task 3: dev layout, migration and popup key

**Goal:** New dev sessions get `claude` + `plan`; the layout migrates an idle `shell` window to `plan`, keeps a busy one; `` prefix ` `` opens a popup shell.

**Files:**
- Modify: `bin/dev` (line 3 comment: `1 claude · 2 plan (the active plan's tasks; prefix ` for a shell)`; line 22 window creation)
- Modify: `bin/tmux-dev-layout` (header comment lines 2-3; replace the final `has_win "$sess" shell || … -n shell` line)
- Modify: `config/tmux.conf` (line 32 comment for `D`; new binding after `W`)
- Modify: `tools/tests/test_layout.zsh`, `tools/tests/test_dedicated_server.zsh`

**Acceptance Criteria:**
- [ ] `bin/dev` creates window `plan` running `<repo>/bin/tmux-plan <name> <root>` (quoted with `${(q)…}`), no `shell` window.
- [ ] `tmux-dev-layout`: a `shell` window whose pane runs a shell (`== ${~TC_SHELLS}`) is killed and `plan` created; a busy `shell` stays with stderr `tmux-dev-layout: '<sess>:shell' is busy; left in place (run again when it is idle)`; with neither, `plan` is created; with `plan` present nothing changes (idempotent). The `-bg` session's `shell` window is untouched.
- [ ] `config/tmux.conf` has ``bind '`' display-popup -E -w 80% -h 80% -d "#{pane_current_path}" -T " shell " zsh`` with a comment line `` # ` : a throwaway shell in a popup, in the current pane's folder ``.
- [ ] Tests: test_layout "user windows"/"idempotent"/"dev windows" expect `claude plan `; new checks "busy shell kept", "busy shell note", "plan window runs tmux-plan" (`#{pane_start_command}` contains `tmux-plan`), "popup key bound" (source `config/tmux.conf` into the scratch server with `AGENT_BOARD_REPO=$TT_REPO`, then `list-keys -T prefix` has `display-popup` with ` shell `). test_dedicated_server line 80 expects `claude plan `; its `send-keys -t '=proj:shell'` steps (lines 144, 153) target a window the test creates first (`B new-window -d -t '=proj:' -n scratch -c "$TT_DIR"`, wait for its shell like line 139 does).
- [ ] `zsh tools/tests/run-all.zsh > F; echo rc=$?` → rc=0 and `grep -c '^FAIL' F` → 0.

**Verify:** `zsh tools/tests/run-all.zsh > /tmp/pw-runall.txt 2>&1; echo rc=$? fails=$(grep -c '^FAIL' /tmp/pw-runall.txt)` → `rc=0 fails=0`

**Steps:**

- [ ] **Step 1: Failing tests** — edit test_layout.zsh and test_dedicated_server.zsh as in the criteria. Busy case: `tt new-session -d -s busy -n claude -c "$TT_DIR"; tt new-window -d -t '=busy:' -n shell -c "$TT_DIR" 'sleep 600'`, run `$L busy "$TT_DIR"`, assert `shell` still listed and the note on stderr.
- [ ] **Step 2: RED** — `zsh tools/tests/test_layout.zsh; echo rc=$?` → FAIL on `user windows` (still `claude shell `). Mutation for "busy shell kept": drop the `TC_SHELLS` idle check → it fails.
- [ ] **Step 3: Implement.** In `bin/dev` replace line 22 with
  `tc_tmux new-window -d -t "=$name:" -n plan -c "$root" "${(q)${0:A:h}}/tmux-plan ${(q)name} ${(q)root}"`.
  In `tmux-dev-layout` replace the last `has_win … shell` line with:

```zsh
plan_cmd="${(q)${0:A:h}}/tmux-plan ${(q)sess} ${(q)root}"
if has_win "$sess" shell; then
  if [[ "$(t display -p -t "=${sess}:shell" '#{pane_current_command}')" == ${~TC_SHELLS} ]]; then
    t kill-window -t "=${sess}:shell"
  else
    print -u2 "tmux-dev-layout: '${sess}:shell' is busy; left in place (run again when it is idle)"
  fi
fi
has_win "$sess" plan || t new-window -d -t "=${sess}:" -n plan -c "$root" "$plan_cmd"
```

  Check the old-layout loop at the top (`for win in shell tests`) still runs before this so role panes are dropped first.
- [ ] **Step 4: GREEN** on both files, then the full run-all as in Verify.
- [ ] **Step 5: Commit** `feat(dev): plan window replaces the user shell window`.

```json:metadata
{"files": ["bin/dev", "bin/tmux-dev-layout", "config/tmux.conf", "tools/tests/test_layout.zsh", "tools/tests/test_dedicated_server.zsh"], "verifyCommand": "zsh tools/tests/run-all.zsh > /tmp/pw-runall.txt 2>&1; echo rc=$? fails=$(grep -c '^FAIL' /tmp/pw-runall.txt)", "acceptanceCriteria": ["dev creates claude + plan running tmux-plan", "idle shell migrated, busy shell kept with note, idempotent, -bg untouched", "popup binding in config/tmux.conf", "layout and dedicated-server tests updated and passing", "run-all rc=0 and 0 FAIL"], "modelTier": "standard"}
```

### Task 4: rules and docs text

**Goal:** Every user-facing description of the `shell` window describes `plan` and the popup instead.

**Files:**
- Modify: `claude/orchestrator.md:142,163`, `claude/worker.md:39`, `claude/plugin/skills/tmux-orchestrator/SKILL.md:3,17,44`, `claude/skills/tmux-orchestrator/SKILL.md` (same lines; the two copies differ elsewhere, edit each in place), `docs/ARCHITECTURE.md:15,49`, `bin/tmux-ctl:61` (comment), `board/index.html:386`

**Acceptance Criteria:**
- [ ] Windows tables: the `shell` row becomes `` | `plan` | the active plan's tasks and owners, read-only. The user's shell is a popup (`` prefix ` ``). Never type into it | ``.
- [ ] "Never type into the user's own `shell` window" becomes "Never type into the user's windows (`claude`, `plan`)".
- [ ] Skill description: "a `dev` session with claude/shell/tests windows" → "a `dev` session (claude and plan windows; the agents' tests/shell windows in `<project>-bg`)"; "reading the \"shell\" window" stays (it is the agents' `-bg` shell).
- [ ] ARCHITECTURE diagram node `2 shell (yours)` → `2 plan (tasks)`; line 49 "never type into the user's `shell`" → "never type into the user's windows".
- [ ] `board/index.html:386`: "claude (orchestrator), shell and tests windows" → "claude (orchestrator) and plan windows, with the agents' tests and shell windows in a hidden session".
- [ ] Check counts below print 0 and 3 (orchestrator.md and both SKILL.md copies carry the windows table). Measured before the change: 7 and 0. Runs after Task 3, which rewrites `bin/dev:3`.

**Verify:** `git grep -c -E "2 shell \(yours\)|user's own .shell. window|claude/shell/tests windows|orchestrator\), shell and tests|^ *.shell. window\. The reason" -- claude bin board docs/ARCHITECTURE.md | wc -l; git grep -l -F '| `plan` |' -- claude | wc -l` → `0` then `3`

**Steps:**

- [ ] **Step 1:** Run the Verify command first and record the counts (the RED: with Task 3 merged in this branch, expect 6 and 0).
- [ ] **Step 2:** Make each edit in the criteria, exactly as worded.
- [ ] **Step 3:** Re-run Verify → `0` and `3`.
- [ ] **Step 4: Commit** `docs(rules): describe the plan window and popup shell`.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/worker.md", "claude/plugin/skills/tmux-orchestrator/SKILL.md", "claude/skills/tmux-orchestrator/SKILL.md", "docs/ARCHITECTURE.md", "bin/tmux-ctl", "board/index.html"], "verifyCommand": "git grep -c -E \"2 shell \\(yours\\)|user's own .shell. window|claude/shell/tests windows|orchestrator\\), shell and tests|^ *.shell. window\\. The reason\" -- claude bin board docs/ARCHITECTURE.md | wc -l; git grep -l -F '| `plan` |' -- claude | wc -l", "acceptanceCriteria": ["windows tables show plan row", "never-type rule names claude and plan", "skill description updated, -bg shell wording kept", "ARCHITECTURE diagram and -bg row updated", "board new-session help text updated", "stale-wording count 0"], "modelTier": "mechanical"}
```

### Task 5: real-state e2e

**Goal:** Prove the plan window against the user's real, long-lived state and an aged multi-owner fixture.

**Files:**
- Create: `docs/superpowers/plans/2026-10-28-plan-window-e2e-report.md`

**Acceptance Criteria:**
- [ ] Read-only real-state run from the worktree, while this plan executes: `python3 -I board/planview.py view agent-board --root /Users/francisco.ruiz/agent-board --json` → `name` is `2026-10-28-plan-window`, `active` true, ≥5 tasks, at least one `in_progress` task with a non-empty `owner` and a `state` in `working|waiting|ready`. The same command without `--json` printed in the report.
- [ ] Aged fixture on a scratch server (`lib.zsh`): a sessions entry pointing at the scratch `claude` pane, a task dir with 6 tasks whose files are dated yesterday (`touch -t`), three owners with `✦` windows (one running `sleep`, i.e. `ready`; one whose pane prints `Do you want to proceed?` then sleeps, i.e. `waiting`; one with no window, `gone`), the `plan` window from `bin/dev`; `capture-pane` of `plan` shows the header, all glyph kinds and the three states; after marking one task completed in its file, the next capture (≤ 5 s) shows the updated count.
- [ ] Report lists each command, its output, and the load average.

**Verify:** `grep -c -E '^## (Real state|Aged fixture|Load)' docs/superpowers/plans/2026-10-28-plan-window-e2e-report.md` → `3`

```json:metadata
{"files": ["docs/superpowers/plans/2026-10-28-plan-window-e2e-report.md"], "verifyCommand": "grep -c -E '^## (Real state|Aged fixture|Load)' docs/superpowers/plans/2026-10-28-plan-window-e2e-report.md", "acceptanceCriteria": ["real-state planview JSON shows this plan active with an owned in-progress task", "aged multi-owner scratch session renders all glyphs and states and updates within 5s", "report has Real state, Aged fixture and Load sections with commands and output"], "modelTier": "standard"}
```

## Post-merge user gate

In a real dev session, run `agent-board dev` once (the layout migrates window 2), then during the next plan confirm window 2 shows the plan, a teammate's row turns red when it asks for permission, and `` prefix ` `` opens a shell in the repo.
