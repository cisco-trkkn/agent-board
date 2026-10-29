# Runtime Optimization Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship roadmap Phase 1 of the runtime audit: less loaded per session (skill listing, observer mandate, Stop-hook time) and less lost (lineage, ledgers, spawns, late context warnings).

**Architecture:** Repo changes on branch `feat/runtime-phase1` (worktree `.claude/worktrees/runtime-phase1`), grouped by file ownership so tasks touch disjoint files. User-config changes (`~/.claude/settings.json`, the handoff skill link, `~/.claude/handoffs/`, lineage migration) are lead-only tasks in the main session. One before/after measurement against the 2026-10-25 baseline closes the plan.

**Tech Stack:** POSIX sh / bash / zsh hooks, Python 3 (board, audit toolkit), jq, Claude Code hook JSON.

**Spec:** `docs/superpowers/specs/2026-10-28-runtime-phase1-design.md`

## Global Constraints

- No edit to any third-party or plugin file: task-observer, superpowers-extended-cc, anthropic-skills. Their changes go upstream as drafts (Task 12).
- Repo hook scripts live in `claude/hooks/`; `~/.claude/hooks/<name>` are links into the main checkout. Tests run the repo script by path relative to the test file (`"$(dirname "$0")/../<name>"`), overridable by `HOOK=`, never a copy.
- Every hook fails open: any error exits 0 with no output, never blocks a tool call or a Stop.
- Persistent state root: `~/.local/state/agent-board/` (`${XDG_STATE_HOME:-$HOME/.local/state}/agent-board`). Every test points state at a temp dir through an env override; a leak check after each test run shows nothing new under the real root (`find ~/.local/state/agent-board -newer <stamp>` prints 0 lines, count printed).
- Hook fixtures come from real data: hook payload shapes are cut from real transcripts with `tools/audit/capture_fixture.py` or copied from a real line, and `tools/audit/redact_check.sh` passes on every new fixture file.
- Commits: conventional with scope (`feat(hooks): …`, `fix(board): …`, `docs(rules): …`), ending with the attribution trailer your harness specifies.
- Teammates sharing this worktree stage only their own paths (`git add <paths>`), and run no `stash`, `reset`, `checkout`, `clean` or `rebase`.
- User config (`~/.claude/…`, links, LaunchAgents) is touched only in lead tasks (Tasks 1, 11), with `F.bak-20261028` backups, generated `F.next` copies and `patch --dry-run` before each swap (CLAUDE.md).
- Shell for agents' Bash calls is zsh: quote words starting with `=`, no unquoted `$VAR` word-splitting.

**Metric definitions (shared by Tasks 10 and 13):**
- `skill_listing chars`: median of `attachment:skill_listing` chars per session in `injection_costs.json`.
- `first-request tokens`: median `first_request_prompt_tokens` in `injection_costs.json` (non-null rows).
- `SessionStart chars`: chars of `task-observer-session-start.sh` additionalContext, measured by running the hook on the real workspace.
- `Skill calls per skill`: count of `tool_use` blocks with `name == "Skill"` grouped by `input.skill`, main thread and sidechains, from `session_metrics.json` (or a `transcripts.py` read if the JSON lacks it; the task states which).
- `Stop durationMs per guard`: `stop_hook_summary.durationMs` per hook command in a transcript.

**User decisions (already made):**
- Scope: roadmap Phase 1, items 1.1–1.11 except 1.7 (done in c24ce6b).
- 1.2: hook-side stub; plugin untouched; restructure goes upstream as a feedback draft.
- Structure: one spec, one plan, tasks by file ownership (approach A).
- The 2026-10-28 task-observer staged round is installed by the user before execution (Task 1 gate); the plan's description and orchestrator.md edits build on the installed text.
- 1.5b: the repo copy `claude/plugin/skills/handoff` is canonical; `~/.claude/handoffs` becomes a link to `~/.local/state/agent-board/handoffs/`.

---

### Task 1: Lead — install gate and branch refresh

**Goal:** The 2026-10-28 staged round is installed and committed on `main`, and `feat/runtime-phase1` contains it.

**Files:**
- Modify: none in the branch except the merge commit

**Acceptance Criteria:**
- [ ] `~/.task-observer/skill-updates/PENDING.md` marks the 2026-10-28 round installed (or the user said to drop it; record which).
- [ ] `git -C ~/agent-board status --short` is empty after the user's install commit.
- [ ] `git merge-base --is-ancestor main HEAD` exits 0 in the worktree.
- [ ] Ledger has a line recording the main SHA merged.

**Verify:** `git -C ~/agent-board/.claude/worktrees/runtime-phase1 merge-base --is-ancestor main HEAD && echo merged` → `merged`

**Steps:**

- [ ] **Step 1:** Ask the user (the only question of this plan; already decided — this is the go signal) to run `bash ~/.task-observer/skill-updates/2026-10-28/install-2026-10-28.sh`, then `--apply`, then commit the `~/agent-board` diff. The installer refuses the stale `orchestrator.md.patch`; that refusal is expected (its #93 change is folded into Task 8).
- [ ] **Step 2:** In the worktree: `git merge --no-edit main`. Run `python3 -m unittest discover -s board/tests 2>&1 | tail -3`.
- [ ] **Step 3:** Append to the ledger: `Task 1: complete — main <sha> merged; 10-28 round <installed|dropped>; orchestrator.md patch refused (folded into Task 8)`.

```json:metadata
{"files": [], "verifyCommand": "git -C ~/agent-board/.claude/worktrees/runtime-phase1 merge-base --is-ancestor main HEAD && echo merged", "acceptanceCriteria": ["10-28 round installed or dropped, recorded", "main checkout clean", "main merged into branch", "ledger line"], "modelTier": "mechanical", "owner": "lead"}
```

---

### Task 2: Stop-hook short-circuit (1.3)

**Goal:** `superpowers-hook.sh` skips the two Stop guards when the session's native task directory shows they cannot act, and otherwise runs them with the same stdin.

**Files:**
- Modify: `claude/hooks/superpowers-hook.sh`
- Create: `claude/hooks/tests/test-superpowers-hook.sh`
- Create: `claude/hooks/tests/fixtures/stop-input.json` (cut from a real Stop payload shape; see Step 1)

**Acceptance Criteria:**
- [ ] `stop-wait-guard.sh`: exits 0 without running the plugin script when no `~/.claude/tasks/session-<sid8>/*.json` contains `"status": "in_progress"` (any spacing after the colon).
- [ ] `stop-revalidate-user-gates.sh`: exits 0 without running the plugin script when no such file matches `usergate|user-gate|user-ordered gate` case-insensitively.
- [ ] With a marker present, the real plugin script runs and receives the identical stdin bytes (test: its trace log, pointed at a temp file with `SUPERPOWERS_WAIT_GUARD_TRACE` / `SUPERPOWERS_USERGATE_TRACE_LOG`, gains a line).
- [ ] Empty or missing `session_id`: the real script runs (pass-through).
- [ ] `post-task-complete-revalidate.sh` is never short-circuited.
- [ ] The tasks root is overridable for tests: `SUPERPOWERS_TASKS_DIR` (default `$HOME/.claude/tasks`).
- [ ] Mutation named and run in RED: delete the short-circuit block → the "no marker: plugin not run" checks fail.
- [ ] Timing: on this machine a skipped run takes < 100 ms (`/usr/bin/time -p`), printed in the report.

**Verify:** `bash claude/hooks/tests/test-superpowers-hook.sh` → last line `passed=N failed=0`

**Steps:**

- [ ] **Step 1: Fixture.** Stop payload keys are what the plugin guards read: `session_id`, `transcript_path`, `stop_hook_active` (`stop-wait-guard.sh:77-84` in the installed plugin). Write `fixtures/stop-input.json` with exactly those keys, `session_id` `"abcdef12-0000-0000-0000-000000000000"` and `transcript_path` pointing at a temp file the test creates. Note in the file's first test comment where the shape came from.
- [ ] **Step 2: Write the test** (bash, same `check` helper style as `test-task-observer-session-start.sh`). Cases, each with a fresh temp `SUPERPOWERS_TASKS_DIR`:
  1. no task dir → wait-guard skipped, revalidate skipped (assert trace files absent);
  2. task dir with `{"status": "completed"}` only → wait-guard skipped;
  3. task dir with `{"status": "in_progress"}` → wait-guard runs (trace line);
  4. task file whose description holds `USER-ORDERED GATE` → revalidate runs (trace line);
  5. task file with `"tags": ["user-gate"]` → revalidate runs;
  6. `session_id` empty → both run;
  7. `post-task-complete-revalidate.sh` with no task dir → runs (resolves the plugin script; assert it was exec'd by checking its trace log or exit path).
  Real plugin resolution: the test uses the installed plugin (no `SUPERPOWERS_PLUGIN_ROOT` override), so cases 3–7 exercise the real guard scripts.
- [ ] **Step 3: RED.** Run the test against the unmodified script → cases 1, 2 fail. Report the output.
- [ ] **Step 4: Implement.** After the `case "$name"` validation, add:

```bash
input="$(cat)"
sid="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
tasks="${SUPERPOWERS_TASKS_DIR:-$HOME/.claude/tasks}/session-${sid:0:8}"
if [ -n "$sid" ]; then
  case "$name" in
    stop-wait-guard.sh)
      grep -qE '"status": *"in_progress"' "$tasks"/*.json 2>/dev/null || exit 0 ;;
    stop-revalidate-user-gates.sh)
      grep -qiE 'usergate|user-gate|user-ordered gate' "$tasks"/*.json 2>/dev/null || exit 0 ;;
  esac
fi
```

  and replace the final `exec bash "$script"` with `printf '%s' "$input" | exec bash "$script"` (the pipe feeds the buffered stdin). Update the header comment with one sentence on the short-circuit and the probe (199 of 200 transcripts carry the words in the skill listing, so the task dir is the marker).
- [ ] **Step 5: GREEN**, then time a skipped run: `/usr/bin/time -p bash claude/hooks/superpowers-hook.sh stop-wait-guard.sh < fixtures/stop-input.json`.
- [ ] **Step 6: Commit** `feat(hooks): short-circuit the Stop guards when the session has no task state`.

```json:metadata
{"files": ["claude/hooks/superpowers-hook.sh", "claude/hooks/tests/test-superpowers-hook.sh", "claude/hooks/tests/fixtures/stop-input.json"], "verifyCommand": "bash claude/hooks/tests/test-superpowers-hook.sh", "acceptanceCriteria": ["wait-guard skipped without in_progress task", "revalidate skipped without gate marker", "marker present: real script runs with same stdin", "empty session_id passes through", "post-task-complete never skipped", "SUPERPOWERS_TASKS_DIR override", "mutation named and run", "skipped run < 100 ms"], "modelTier": "standard"}
```

---

### Task 3: Context guard on more events, once per band (1.9)

**Goal:** `context-size-guard.sh` handles `UserPromptSubmit`, `Stop` and `PostToolUse` input, and warns at most once per 50K band per session.

**Files:**
- Modify: `claude/hooks/context-size-guard.sh`
- Create: `claude/hooks/tests/test-context-size-guard.sh`
- Create: `claude/hooks/tests/fixtures/context-transcript.jsonl` (via `capture_fixture.py`)

**Acceptance Criteria:**
- [ ] Event read from `.hook_event_name`. `UserPromptSubmit` and `PostToolUse`: `systemMessage` plus `hookSpecificOutput.additionalContext` with `hookEventName` set to the event. `Stop`: `systemMessage` only.
- [ ] Band = `tokens / 50000`. The hook warns only when tokens ≥ threshold and band > the stored band; it then stores the band in `${CLAUDE_CONTEXT_GUARD_STATE:-$HOME/.local/state/agent-board/context-guard}/<session_id>.band`. Same band again → no output.
- [ ] Missing `session_id` → behaves as today (warns, stores nothing).
- [ ] The existing UserPromptSubmit text (the /handoff advice) is unchanged for the lead. For `PostToolUse` and `Stop` the text adds: "If you are a teammate, tell the lead in your next message."
- [ ] Real-state check: replaying session `48822fd2` (its transcript under `~/.claude/projects/`, read-only) as `PostToolUse` input gives output (skipped with a printed SKIP if the transcript is gone).
- [ ] Mutation named and run in RED: remove the band comparison → "same band twice → one warning" fails.

**Verify:** `bash claude/hooks/tests/test-context-size-guard.sh` → last line `passed=N failed=0`

**Steps:**

- [ ] **Step 1: Fixture.** `python3 tools/audit/capture_fixture.py <a real transcript whose last main-thread usage ≥ 300K> claude/hooks/tests/fixtures/context-transcript.jsonl --max-lines 400`, then `bash tools/audit/redact_check.sh claude/hooks/tests/fixtures/`. Pick the source with `session_metrics.json`'s max-context column or by scanning usage; record the source session id (8 chars) in the test header.
- [ ] **Step 2: Test.** Cases with temp `CLAUDE_CONTEXT_GUARD_STATE`, input JSON built with `jq -n` (`transcript_path`, `session_id`, `hook_event_name`): UserPromptSubmit warns with additionalContext; repeat → silent; Stop → systemMessage, no hookSpecificOutput; PostToolUse → both, hookEventName PostToolUse; threshold above the fixture's tokens (`CLAUDE_CONTEXT_WARN_TOKENS=900000`) → silent; band file holds the integer band; no session_id → warns twice in a row; real-state replay of `48822fd2`.
- [ ] **Step 3: RED** against the current script; report.
- [ ] **Step 4: Implement** (keep `#!/usr/bin/env bash` and the token computation):

```bash
input=$(cat)
transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
sid=$(printf '%s' "$input" | jq -r '.session_id // empty')
event=$(printf '%s' "$input" | jq -r '.hook_event_name // "UserPromptSubmit"')
# … existing tokens computation …
band=$((tokens / 50000))
if [ -n "$sid" ]; then
  sdir="${CLAUDE_CONTEXT_GUARD_STATE:-$HOME/.local/state/agent-board/context-guard}"
  last=$(cat "$sdir/$sid.band" 2>/dev/null || echo -1)
  [ "$band" -gt "$last" ] || exit 0
  mkdir -p "$sdir" && printf '%s\n' "$band" > "$sdir/$sid.band"
fi
```

  Output per event with `jq -n`, as in the acceptance criteria. Update the header comment: events, band rule, state path.
- [ ] **Step 5: GREEN**, leak check (no file under the real state root), commit `feat(hooks): context guard on Stop and PostToolUse, once per 50K band`.

```json:metadata
{"files": ["claude/hooks/context-size-guard.sh", "claude/hooks/tests/test-context-size-guard.sh", "claude/hooks/tests/fixtures/context-transcript.jsonl"], "verifyCommand": "bash claude/hooks/tests/test-context-size-guard.sh", "acceptanceCriteria": ["per-event output shapes", "once per 50K band via band file", "no session_id keeps old behaviour", "lead text unchanged; teammate sentence on PostToolUse/Stop", "real-state replay of 48822fd2", "mutation named and run"], "modelTier": "standard"}
```

---

### Task 4: Spawn record hook (1.10)

**Goal:** A new async PostToolUse `Agent` hook appends one JSON line per spawn to `spawns.jsonl`.

**Files:**
- Create: `claude/hooks/spawn-record.sh`
- Create: `claude/hooks/tests/test-spawn-record.sh`
- Create: `claude/hooks/tests/fixtures/agent-posttooluse.json`

**Acceptance Criteria:**
- [ ] Line fields: `ts` (epoch seconds), `lead_session` (`.session_id`), `name`, `subagent_type`, `model` (`"inherit"` when absent), `tier`, `reason`.
- [ ] `tier`: the model mapped through `docs/superpowers/model-routing.json` of the hook's cwd repo if present (value → key, so `haiku` → `mechanical`, `sonnet` → `standard`, `fable` → `frontier`), else `null`.
- [ ] `reason`: the rest of the first prompt line starting with `Reason:` (trimmed), else `null`.
- [ ] Output file `${AGENT_BOARD_SPAWNS:-$HOME/.local/state/agent-board/spawns.jsonl}`; directory created if missing.
- [ ] Malformed or non-Agent input: exit 0, no line, no output.
- [ ] Fixture `tool_input` key set copied from a real Agent `tool_use` in a transcript (`name`, `subagent_type`, `model`, `prompt`, `description`), with the prompt text replaced; source session id in the test header.
- [ ] Mutation named and run in RED: drop the `Reason:` extraction → "reason captured" fails.

**Verify:** `bash claude/hooks/tests/test-spawn-record.sh` → last line `passed=N failed=0`

**Steps:**

- [ ] **Step 1: Probe and fixture.** Find a real Agent call: `grep -m1 -o '"name":"Agent","input":{[^}]*' <transcript>`; record the key set. Build `fixtures/agent-posttooluse.json` as a PostToolUse payload (`session_id`, `cwd`, `hook_event_name: "PostToolUse"`, `tool_name: "Agent"`, `tool_input`, `tool_response: {}`).
- [ ] **Step 2: Test** with temp `AGENT_BOARD_SPAWNS` and `cwd` pointing at a temp repo holding a copy of `model-routing.json`: sonnet + `Reason: fable-limit` line → tier standard, reason `fable-limit`; no model → `inherit`, tier null; opus → tier null; no Reason line → null; `tool_name: "Bash"` → no line; `not json` → exit 0, no line.
- [ ] **Step 3: RED** (script missing → every check fails; then with the mutation once implemented).
- [ ] **Step 4: Implement** with one `python3 -I -c` reading stdin (as `artifact-register.sh` does), wrapped so any exception exits 0:

```bash
#!/usr/bin/env bash
# PostToolUse(Agent) hook, async: one line per teammate/subagent spawn in spawns.jsonl
# {ts, lead_session, name, subagent_type, model, tier, reason}. Fails open.
out="${AGENT_BOARD_SPAWNS:-$HOME/.local/state/agent-board/spawns.jsonl}"
payload=$(cat)
src=$(cat <<'PY'
import json, os, re, sys, time
try:
    d = json.loads(sys.stdin.read())
    if d.get("tool_name") != "Agent":
        sys.exit(0)
    i = d.get("tool_input") or {}
    model = i.get("model") or "inherit"
    tier = None
    try:
        with open(os.path.join(d.get("cwd") or ".", "docs/superpowers/model-routing.json")) as f:
            rm = json.load(f)
        tier = next((k for k, v in rm.items() if v == model), None)
    except Exception:
        pass
    m = re.search(r"^Reason:\s*(.+)$", i.get("prompt") or "", re.M)
    rec = {"ts": int(time.time()), "lead_session": d.get("session_id"), "name": i.get("name"),
           "subagent_type": i.get("subagent_type"), "model": model, "tier": tier,
           "reason": m.group(1).strip() if m else None}
    os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
    with open(sys.argv[1], "a") as f:
        f.write(json.dumps(rec) + "\n")
except Exception:
    pass
PY
)
printf '%s' "$payload" | python3 -I -c "$src" "$out" 2>/dev/null
exit 0
```

- [ ] **Step 5: GREEN**, leak check, commit `feat(hooks): spawn record for every Agent call`.

```json:metadata
{"files": ["claude/hooks/spawn-record.sh", "claude/hooks/tests/test-spawn-record.sh", "claude/hooks/tests/fixtures/agent-posttooluse.json"], "verifyCommand": "bash claude/hooks/tests/test-spawn-record.sh", "acceptanceCriteria": ["seven fields per line", "tier from model-routing.json reverse map", "reason from Reason: line", "AGENT_BOARD_SPAWNS override", "fail open on malformed/non-Agent", "fixture key set from a real Agent call", "mutation named and run"], "modelTier": "standard"}
```

---

### Task 5: Observer session-start stub (1.2)

**Goal:** `task-observer-session-start.sh` runs the cheap protocol checks itself and emits a short summary plus the load-on-demand rule.

**Files:**
- Modify: `claude/hooks/task-observer-session-start.sh`
- Modify: `claude/hooks/tests/test-task-observer-session-start.sh`

**Acceptance Criteria:**
- [ ] Output (lead): one line `Task observer: workspace <ok|MISSING> · <N> open · last review <date|never>[ (due)] [· fired <date>, no review recorded] · <K> staged updates.` then the rule: load the task-observer skill (no Skill arguments) only to write an observation, to run a review the user opted into, or to reconcile staged updates; observations are created only by `scripts/new-observation.sh`; re-read this summary before writing or proposing a plan; teammates and subagents never load it and report findings to the lead. Plus the workspace path and README pointer.
- [ ] `K` = entries in `skill-updates/` excluding `PENDING.md` and dot-entries, counting only rounds `PENDING.md` lists as `awaiting install` (grep `awaiting install` headings); if `PENDING.md` is absent, count directories.
- [ ] `review-started.txt` not starting with `completed` → the `fired …, no review recorded` part (value printed as found, e.g. `limit-hit 2026-10-30`), and the review counts as due.
- [ ] Missing workspace dir → `workspace MISSING` and the rule to run the full protocol (load the skill).
- [ ] `TC_ROLE=worker` output unchanged.
- [ ] additionalContext ≤ 900 chars on the real workspace (printed by the test).
- [ ] The test's old mandate-text checks (`Before the first tool call`, `before writing or proposing a plan`, `Session Start Protocol`) are replaced by checks for the new text; README checks stay.
- [ ] Mutation named and run in RED: hard-code `K=0` → the staged-count check fails.

**Verify:** `HOOK=claude/hooks/task-observer-session-start.sh bash claude/hooks/tests/test-task-observer-session-start.sh` → last line `passed=N failed=0`

**Steps:**

- [ ] **Step 1:** Update the test first: new temp workspaces for `review-started.txt` = `limit-hit 2026-10-30`, a `skill-updates/` with `PENDING.md` naming one round `awaiting install` plus one installed round, a missing workspace, and a size check on the real workspace (`${TASK_OBSERVER_WORKSPACE:-$HOME/.task-observer}`, read-only). Change `H=` default to the repo script beside the test.
- [ ] **Step 2: RED**; report.
- [ ] **Step 3:** Implement in POSIX sh (the file is `#!/bin/sh` and registered as `sh …`). Keep the JSON escaping line and the worker branch.
- [ ] **Step 4: GREEN**; print the real-workspace output and its length in the report.
- [ ] **Step 5: Commit** `feat(hooks): observer session-start stub; full skill on demand`.

```json:metadata
{"files": ["claude/hooks/task-observer-session-start.sh", "claude/hooks/tests/test-task-observer-session-start.sh"], "verifyCommand": "HOOK=claude/hooks/task-observer-session-start.sh bash claude/hooks/tests/test-task-observer-session-start.sh", "acceptanceCriteria": ["summary line format", "staged count from PENDING.md awaiting install", "non-completed review-started reported and due", "missing workspace -> full protocol", "worker output unchanged", "<= 900 chars on real workspace", "old mandate checks replaced", "mutation named and run"], "modelTier": "standard"}
```

---

### Task 6: Review job budget and limit markers (1.4)

**Goal:** The scheduled review runs with a spending cap and a fallback model, and records `limit-hit` / `budget-hit` instead of failing silently.

**Files:**
- Modify: `claude/hooks/task-observer-review.sh`
- Create: `claude/hooks/tests/test-task-observer-review.sh`
- Create: `claude/hooks/tests/fixtures/review-out-limit.txt`, `review-out-budget.txt`, `review-out-ok.txt`

**Acceptance Criteria:**
- [ ] `claude -p` gains `--max-budget-usd "$REVIEW_BUDGET_USD"` (default set at the top of the script, `REVIEW_BUDGET_USD=${REVIEW_BUDGET_USD:-5}`) and `--fallback-model sonnet`.
- [ ] A function `classify_run <output-file> <exit-code>` prints `limit-hit`, `budget-hit` or `ok`; after the run, `limit-hit`/`budget-hit` write `<marker> <YYYY-MM-DD>` to `review-started.txt` and a log line; `ok` leaves the existing behaviour.
- [ ] The script can be sourced for tests without running the review (`[ "${TO_REVIEW_SOURCE_ONLY:-0}" = 1 ] && return 0` before the main body).
- [ ] Fixtures: `review-out-limit.txt` copies the real line from `~/.task-observer/skill-observations/scheduled-review.log` (2026-10-23 run, "You've hit your weekly limit"); `review-out-budget.txt` is the real output of one probe run `claude -p --max-budget-usd 0.01 "Reply with the word ok."` (or, if that run completes under budget, a second probe with a prompt that needs more than one turn; the probe command and output are in the report); `review-out-ok.txt` is the tail of a real successful run from the same log.
- [ ] Mutation named and run in RED: swap the two `grep` patterns → limit and budget cases fail.

**Verify:** `bash claude/hooks/tests/test-task-observer-review.sh` → last line `passed=N failed=0`

**Steps:**

- [ ] **Step 1: Probes.** Run the budget probe once, save its stdout+stderr as the budget fixture, note the exact phrase to match. Copy the limit and ok fixtures from the log.
- [ ] **Step 2: Test** sources the script with `TO_REVIEW_SOURCE_ONLY=1` and checks `classify_run` on the three fixtures with exit codes 1, 1, 0.
- [ ] **Step 3: RED**, implement, **GREEN**. The output of `claude -p` is already captured to the log; tee it to a temp file for `classify_run`.
- [ ] **Step 4: Commit** `feat(observer): review job budget cap, fallback model, limit markers`.

```json:metadata
{"files": ["claude/hooks/task-observer-review.sh", "claude/hooks/tests/test-task-observer-review.sh", "claude/hooks/tests/fixtures/review-out-limit.txt", "claude/hooks/tests/fixtures/review-out-budget.txt", "claude/hooks/tests/fixtures/review-out-ok.txt"], "verifyCommand": "bash claude/hooks/tests/test-task-observer-review.sh", "acceptanceCriteria": ["budget and fallback flags", "classify_run limit/budget/ok and marker write", "source-only seam", "fixtures from real log and one real probe", "mutation named and run"], "modelTier": "standard"}
```

---

### Task 7: Lineage in persistent state (1.5a)

**Goal:** Handoff lineage is written to and read from `~/.local/state/agent-board/lineage/<project>.jsonl` and survives a project close.

**Files:**
- Modify: `tools/lib/tc-env.zsh` (new `TC_LINEAGE_DIR`), `board/tc_env.py` (new `lineage_dir()`), `board/relay.py:96-106`, `board/artifacts.py:47`, `claude/plugin/scripts/artifact-register.sh:43`, `bin/tmux-session-closed:18`, `docs/ARCHITECTURE.md:52,233,250`
- Modify tests: `tools/tests/lib.zsh` (export `TC_LINEAGE="$TC_STATE/lineage"`), `tools/tests/test_ctl_relay.zsh`, `tools/tests/test_artifact_hook.zsh`, `tools/tests/test_session_closed.zsh`, `board/tests/test_relay.py`, `board/tests/test_artifacts.py`, `board/tests/test_tc_env.py`

**Acceptance Criteria:**
- [ ] `tc-env.zsh`: `TC_LINEAGE_DIR="${TC_LINEAGE:-${XDG_STATE_HOME:-$HOME/.local/state}/agent-board/lineage}"`; `tc_env.lineage_dir()` parses the same rule (test in `test_tc_env.py` with and without `TC_LINEAGE`).
- [ ] `relay()` appends to `lineage_dir()/<sess>.jsonl` (creates the dir); its `state_dir` parameter no longer decides the lineage path.
- [ ] `artifacts.py` and `artifact-register.sh` read the epoch from the new file.
- [ ] `tmux-session-closed` no longer deletes lineage; `test_session_closed.zsh` asserts the lineage file survives a close while the other state files go.
- [ ] Every test that writes lineage sets `TC_LINEAGE` to a temp dir; leak check: no new file under `~/.local/state/agent-board/lineage` after the suites (count printed).
- [ ] `docs/ARCHITECTURE.md` names the new path in all three places.
- [ ] Real-state check (read-only): `ls $TMPDIR/tmux-ctl-$UID/lineage-*.jsonl | wc -l` and line counts recorded in the report for Task 11's migration.

**Verify:** `python3 -m unittest discover -s board/tests 2>&1 | tail -1 && zsh tools/tests/test_ctl_relay.zsh && zsh tools/tests/test_artifact_hook.zsh && zsh tools/tests/test_session_closed.zsh` → `OK` and each zsh test exits 0

**Steps:**

- [ ] **Step 1:** Update tests to the new path first (RED: they fail on the old code for the stated reason — file not at the new path).
- [ ] **Step 2:** Implement the helper in `tc-env.zsh` and the parser in `tc_env.py` (same parse-not-copy pattern as `state_dir`), then the four call sites.
- [ ] **Step 3:** GREEN; run the full `zsh tools/tests/run-all.zsh` through `tmux-ctl run -t 1800 tests` in the background (`run_in_background`) and report its exit code and FAIL count (`grep -c '^FAIL'`).
- [ ] **Step 4: Commit** `fix(board): keep handoff lineage in persistent state`.

```json:metadata
{"files": ["tools/lib/tc-env.zsh", "board/tc_env.py", "board/relay.py", "board/artifacts.py", "claude/plugin/scripts/artifact-register.sh", "bin/tmux-session-closed", "docs/ARCHITECTURE.md", "tools/tests/lib.zsh", "tools/tests/test_ctl_relay.zsh", "tools/tests/test_artifact_hook.zsh", "tools/tests/test_session_closed.zsh", "board/tests/test_relay.py", "board/tests/test_artifacts.py", "board/tests/test_tc_env.py"], "verifyCommand": "python3 -m unittest discover -s board/tests 2>&1 | tail -1 && zsh tools/tests/test_ctl_relay.zsh && zsh tools/tests/test_artifact_hook.zsh && zsh tools/tests/test_session_closed.zsh", "acceptanceCriteria": ["TC_LINEAGE_DIR and lineage_dir() same rule", "relay writes new path", "readers use new path", "close keeps lineage", "tests isolated, leak check", "ARCHITECTURE.md updated", "real lineage counts recorded"], "modelTier": "standard"}
```

---

### Task 8: Agent rules — dedupe, answers up front, new rules (1.6, 1.9, 1.10, 1.11)

**Goal:** `worker.md` holds the rules common to every agent the lead starts plus a teammate section; `orchestrator.md` keeps only brief-specific teammate rules and gains the new lead rules.

**Constraints:**
- Worker behaviour unchanged: every rule a worker follows today is still in `worker.md`, outside the teammate section.
- Teammate behaviour unchanged except the additions listed here; rule 3's gate carve-outs (failed acceptance criterion, gate, shared-state or removing step, skill-named user confirm) are kept word for word.
- Fold in the staged-but-refused 2026-10-28 `orchestrator.md.patch` change (#93: rule 3's exception names a spec constraint; the shared-preamble note) by reading `~/.task-observer/skill-updates/2026-10-28/_target-files/orchestrator.md.patch` and applying its intent to the new text.
- Open observation #104 (rule 5 vs the Bash 120 s cap) is not in scope; move rule 5's text unchanged.

**Files:**
- Modify: `claude/orchestrator.md` (teammate list at "Teammates and workers don't talk to the user", "Models and effort", "Rules")
- Modify: `claude/worker.md`

**Acceptance Criteria:**
- [ ] Each of these appears in exactly one of the two files (`grep -c` across both = 1, printed): the `tmux-ctl run` rule's "120s" sentence, the pkill rule's "Never stop processes with", the task-observer exemption, the `agent-ci check` sentence, the shutdown_response JSON.
- [ ] `orchestrator.md` teammate list ends with an instruction to read `~/agent-board/claude/worker.md` (its common rules and teammate section apply).
- [ ] `worker.md` has a section headed `## If you are a teammate` with: ask the lead (not "decide, don't ask"), rule-3 gates, "send the question and end your turn" when an answer is needed before a gated step, the context-guard rule (past the threshold, tell the lead in your next message), the shutdown_response schema.
- [ ] `orchestrator.md` adds: a "Decided" block in every teammate brief (foreseeable choices with answers); send the brief before setting a task's `owner` (setting `owner` dispatches); a spawn that leaves its tier's model carries a `Reason:` line; on a Fable limit error, re-dispatch on Opus with `Reason: fable-limit`.
- [ ] `wc -c claude/orchestrator.md` falls by at least 1,500 bytes net (printed before and after).
- [ ] An independent read-through (the task reviewer) lists every rule in the old teammate list 1–8 and old `worker.md`, and where it now lives.

**Verify:** `zsh docs/superpowers/plans/2026-10-28-runtime-phase1.checks/rules.zsh` → `rules ok`

```json:metadata
{"files": ["claude/orchestrator.md", "claude/worker.md", "docs/superpowers/plans/2026-10-28-runtime-phase1.checks/rules.zsh"], "verifyCommand": "zsh docs/superpowers/plans/2026-10-28-runtime-phase1.checks/rules.zsh", "acceptanceCriteria": ["five rules each in exactly one file", "orchestrator teammate list points to worker.md", "worker.md teammate section with five items", "four new lead rules", "orchestrator.md -1500 bytes net", "rule-by-rule location table in the report"], "modelTier": "frontier"}
```

The check script (create it in this task; it is the Verify):

```zsh
#!/usr/bin/env zsh
# rules.zsh — structural checks for Task 8; prints 'rules ok' or the failing check.
emulate -L zsh
cd "${0:A:h}/../../../.." || exit 2
o=claude/orchestrator.md; w=claude/worker.md; bad=0
one() { local n=$(( $(grep -cF -- "$1" $o) + $(grep -cF -- "$1" $w) )); print -r -- "$n  $1"; (( n == 1 )) || bad=1 }
one '120s'; one 'Never stop processes with'; one 'shutdown_response'; one 'agent-ci check'; one 'write to its log'
grep -q '^## If you are a teammate' $w || { print 'no teammate section'; bad=1 }
grep -qF 'claude/worker.md' $o || { print 'orchestrator does not point to worker.md'; bad=1 }
for s in 'Decided' 'Reason: fable-limit' 'end your turn' ; do grep -qF -- "$s" $o $w || { print "missing: $s"; bad=1 }; done
grep -qiE 'before (you )?set(ting)? .*owner' $o || { print 'owner-after-brief rule missing'; bad=1 }
(( bad == 0 )) && print 'rules ok'
exit $bad
```

---

### Task 9: Skill text — ledger archive, shorter descriptions, docs-report path (1.8, 1.1 repo half, 1.5b doc)

**Goal:** `subagent-driven-development-extras` archives the ledger at Finish; every repo skill description is ≤ 300 chars; `docs-report` names the new handoff path.

**Files:**
- Modify: `claude/skills/subagent-driven-development-extras/SKILL.md`
- Modify: `SKILL.md` frontmatter `description` of every repo skill over 300 chars (`claude/skills/*/SKILL.md`, `claude/plugin/skills/*/SKILL.md`; list them in Step 1)
- Modify: `claude/skills/docs-report/SKILL.md:55`
- Note: `tmux-orchestrator` exists in both `claude/skills/` and `claude/plugin/skills/` (open #70); give both the same new description.
- Create: `docs/superpowers/plans/2026-10-28-runtime-phase1.checks/descriptions.py`

**Acceptance Criteria:**
- [ ] SDD-extras has a Finish step, before the workspace is deleted: copy `<workspace>/progress.md` to `docs/superpowers/ledgers/<plan-basename>/progress.md`, commit `docs(ledger): <plan-basename>`, and check the plan's `.tasks.json` sits beside the plan.
- [ ] Every repo skill description ≤ 300 chars; the `-extras` descriptions still contain "Use together with" and the base skill's full name, and "every time it runs".
- [ ] Rule summaries cut from descriptions are present in the body (the task report lists each moved phrase and its new line).
- [ ] `docs-report` line 55 names `~/.local/state/agent-board/handoffs/` (and `~/.claude/handoffs/` as the older location).
- [ ] The repo's own skill tests pass: the three suites in `CLAUDE.md`.

**Verify:** `python3 docs/superpowers/plans/2026-10-28-runtime-phase1.checks/descriptions.py` → `descriptions ok (N checked)` with N ≥ 10

**Steps:**

- [ ] **Step 1:** List lengths: run the check script below before editing; it prints each over-limit skill and fails.
- [ ] **Step 2:** Shorten each; keep the trigger sentence first. Move removed rule summaries into the body's opening paragraph if not already there.
- [ ] **Step 3:** Add the SDD-extras Finish step; fix docs-report line 55.
- [ ] **Step 4:** Run the check and the three skill suites; commit `docs(skills): shorter descriptions; ledger archive at finish`.

```python
#!/usr/bin/env python3
"""descriptions.py — every repo skill description <= 300 chars; -extras keep their trigger."""
import pathlib, re, sys
root = pathlib.Path(__file__).resolve().parents[4]
files = sorted(root.glob("claude/skills/*/SKILL.md")) + sorted(root.glob("claude/plugin/skills/*/SKILL.md"))
bad = 0
for f in files:
    fm = f.read_text().split("---")[1]
    m = re.search(r"^description:\s*(.*?)(?=^\w[\w-]*:|\Z)", fm, re.M | re.S)
    d = " ".join((m.group(1) if m else "").split()).strip("\"'")
    if len(d) > 300:
        print(f"{len(d)} {f.relative_to(root)}"); bad = 1
    if f.parent.name.endswith("-extras") and not ("Use together with" in d and "every time it runs" in d):
        print(f"trigger lost: {f.relative_to(root)}"); bad = 1
print(f"descriptions {'ok' if not bad else 'FAIL'} ({len(files)} checked)")
sys.exit(bad)
```

```json:metadata
{"files": ["claude/skills/subagent-driven-development-extras/SKILL.md", "claude/skills/docs-report/SKILL.md", "docs/superpowers/plans/2026-10-28-runtime-phase1.checks/descriptions.py"], "verifyCommand": "python3 docs/superpowers/plans/2026-10-28-runtime-phase1.checks/descriptions.py", "acceptanceCriteria": ["ledger archive Finish step", "descriptions <= 300 chars, extras triggers kept", "moved phrases listed", "docs-report new handoff path", "three skill suites pass"], "modelTier": "standard"}
```

---

### Task 10: Audit — skillOverrides list from call counts (1.1 plugin half)

**Goal:** A table of every listed skill not owned by the repo, with its Skill-call count over the audit window and description length, and the override each one gets by the spec's rule.

**Files:**
- Create: `docs/superpowers/reports/runtime-phase1/overrides.md`
- Create: `docs/superpowers/reports/runtime-phase1/overrides.json` (the proposed `skillOverrides` additions only)

**Acceptance Criteria:**
- [ ] Table columns: skill, owner (plugin name), Skill calls (window), description chars, current override, proposed override, reason.
- [ ] Every skill in the current skill listing appears (source: the latest `attachment:skill_listing` in a real lead transcript from today; count of rows equals the count of listed skills, both printed).
- [ ] Rule (spec 1.1): `name-only` when calls = 0 and chars > 300; `off` only with a stated out-of-scope reason; existing overrides kept; repo-owned skills marked "shortened in Task 9".
- [ ] The metric for calls follows Global Constraints "Skill calls per skill", and the report says which source it used.
- [ ] `overrides.json` is valid JSON and contains no skill already in `~/.claude/settings.json` `skillOverrides`.

**Verify:** `python3 -c "import json;json.load(open('docs/superpowers/reports/runtime-phase1/overrides.json'))" && grep -c '^| ' docs/superpowers/reports/runtime-phase1/overrides.md` → a count equal to listed skills + 2 (header and rule rows)

```json:metadata
{"files": ["docs/superpowers/reports/runtime-phase1/overrides.md", "docs/superpowers/reports/runtime-phase1/overrides.json"], "verifyCommand": "python3 -c \"import json;json.load(open('docs/superpowers/reports/runtime-phase1/overrides.json'))\" && grep -c '^| ' docs/superpowers/reports/runtime-phase1/overrides.md", "acceptanceCriteria": ["table columns", "every listed skill, counts printed", "spec rule applied", "metric source stated", "overrides.json valid, no existing keys"], "modelTier": "standard"}
```

---

### Task 11: Lead — user-config install

**Goal:** Live config carries the new overrides and hook registrations; the handoff skill and directory are unified; existing lineage is migrated.

**Files:**
- Modify (repo, branch): `claude/settings.json`
- Live (main session only): `~/.claude/settings.json`, `~/.claude/skills/handoff` (link), `~/.claude/handoffs` → link, `~/.local/state/agent-board/lineage/`

**Acceptance Criteria:**
- [ ] `~/.claude/settings.json.bak-20261028` exists and equals the pre-change file (`cmp`).
- [ ] Live and repo settings both gain, with command strings byte-identical between them: `skillOverrides` entries from `overrides.json`; `Stop` → `~/.claude/hooks/context-size-guard.sh` (timeout 10); `PostToolUse` matcher `SendMessage|Agent` → `~/.claude/hooks/context-size-guard.sh` (timeout 10); `PostToolUse` matcher `Agent` → `~/.claude/hooks/spawn-record.sh` (timeout 5, async).
- [ ] `~/.claude/hooks/spawn-record.sh` is a link to `~/agent-board/claude/hooks/spawn-record.sh` (created after the branch merges, or pointed at the main checkout path, which resolves once merged; the step order below makes it resolve before the settings swap).
- [ ] The swap was a generated `settings.json.next` (`jq` edit of a copy), `jq . ` valid, diffed against live, then `mv`.
- [ ] `readlink ~/.claude/skills/handoff` → the repo `claude/plugin/skills/handoff`; old target recorded in the ledger.
- [ ] All docs from `~/.claude/handoffs/` are in `~/.local/state/agent-board/handoffs/` (count before = count after, printed); `~/.claude/handoffs` is a link to it.
- [ ] Lineage migration: every line of `$TMPDIR/tmux-ctl-$UID/lineage-<p>.jsonl` appended to `~/.local/state/agent-board/lineage/<p>.jsonl` (line counts before/after printed); old files left in place.
- [ ] `tools/tests/test_install.zsh` passes (fixtures updated if the repo settings change affects them).

**Verify:** `jq -e '.hooks.Stop[].hooks[].command' ~/.claude/settings.json | grep -c context-size-guard && readlink ~/.claude/handoffs` → `1` and the new handoffs path

**Steps:**

- [ ] **Step 1:** This task runs after the branch merges to `main` at finish, so every link target exists. Back up: `cp -p ~/.claude/settings.json ~/.claude/settings.json.bak-20261028`.
- [ ] **Step 2:** Generate `~/.claude/settings.json.next` with `jq` from the live file plus `overrides.json` and the three registrations; `jq . settings.json.next >/dev/null`; `diff -u ~/.claude/settings.json ~/.claude/settings.json.next` reviewed; `ln -s ~/agent-board/claude/hooks/spawn-record.sh ~/.claude/hooks/spawn-record.sh`; `mv` the `.next` over the regular file (it is not a link: `ls -l` first).
- [ ] **Step 3:** Same keys into repo `claude/settings.json` on `main` with identical strings; run `zsh tools/tests/test_install.zsh`; commit `chore(settings): context guard and spawn record registrations; skill overrides`.
- [ ] **Step 4:** Handoff: record `readlink ~/.claude/skills/handoff`; `ln -sfn ~/agent-board/claude/plugin/skills/handoff ~/.claude/skills/handoff`; `mkdir -p ~/.local/state/agent-board/handoffs`; `mv -n ~/.claude/handoffs/* ~/.local/state/agent-board/handoffs/`; check counts and that `~/.claude/handoffs` is empty; `rmdir ~/.claude/handoffs && ln -s ~/.local/state/agent-board/handoffs ~/.claude/handoffs`.
- [ ] **Step 5:** Lineage migration loop (zsh, one file at a time, counts printed).
- [ ] **Step 6:** Start one fresh `claude -p "ok"` in a scratch dir and check it runs (settings parse); ledger line.

```json:metadata
{"files": ["claude/settings.json"], "verifyCommand": "jq -e '.hooks.Stop[].hooks[].command' ~/.claude/settings.json | grep -c context-size-guard && readlink ~/.claude/handoffs", "acceptanceCriteria": ["backup equals pre-change", "live and repo settings identical new entries", "spawn-record link", "generated .next swap", "handoff link repointed, old target recorded", "handoff docs moved, counts equal, link left", "lineage migrated, counts printed", "test_install passes"], "modelTier": "standard", "owner": "lead"}
```

---

### Task 12: Upstream drafts and repo command list

**Goal:** Feedback drafts for the two plugin changes this plan works around, and the repo's command list names the hook tests.

**Files:**
- Create: `docs/superpowers/reports/runtime-phase1/upstream-task-observer.md`
- Create: `docs/superpowers/reports/runtime-phase1/upstream-superpowers-stop-hooks.md`
- Modify: `CLAUDE.md` (Commands: one line running every `claude/hooks/tests/test-*.sh`)

**Acceptance Criteria:**
- [ ] task-observer draft: the split (a cheap session-start stub; full `SKILL.md` on demand), the measured sizes (SKILL.md 44,715 chars; Skill calls 29 in 28 of 65 lead sessions; est. 11,179 tokens per load), and the stub's output as the example. No user, client or path names beyond `~/.task-observer`.
- [ ] superpowers draft: both Stop guards check the session task dir before parsing the transcript; probe numbers (122 task dirs, 4 gate-marked, 12 in progress of 1,348 sessions; 199/200 transcripts contain the words via the skill listing).
- [ ] Neither draft is sent; the lead asks the user before any submission (outward-facing).
- [ ] `CLAUDE.md` line runs: `for t in claude/hooks/tests/test-*.sh; do bash "$t" || echo "FAIL $t"; done`.

**Verify:** `grep -c 'claude/hooks/tests/test-' CLAUDE.md && ls docs/superpowers/reports/runtime-phase1/upstream-*.md | wc -l` → `1` and `2`

```json:metadata
{"files": ["docs/superpowers/reports/runtime-phase1/upstream-task-observer.md", "docs/superpowers/reports/runtime-phase1/upstream-superpowers-stop-hooks.md", "CLAUDE.md"], "verifyCommand": "grep -c 'claude/hooks/tests/test-' CLAUDE.md && ls docs/superpowers/reports/runtime-phase1/upstream-*.md | wc -l", "acceptanceCriteria": ["task-observer draft with measured sizes", "superpowers draft with probe numbers", "nothing sent", "CLAUDE.md hook-test line"], "modelTier": "mechanical"}
```

---

### Task 13: Measurement and dated follow-up

**Goal:** Before/after numbers against the 2026-10-25 baseline, recorded with their sources, plus the 2026-11-04 follow-up list.

**Files:**
- Create: `docs/superpowers/reports/runtime-phase1/measurement.md`

**Acceptance Criteria:**
- [ ] Runs after Task 11. `bash tools/audit/run_baseline.sh 1` for the after-window; the 2026-10-25 `audit-out/` JSON for before (path cited).
- [ ] Table rows (metrics as defined in Global Constraints): `skill_listing chars`, `first-request tokens`, `SessionStart chars`, `Stop durationMs per guard` (from one live session started after Task 11, transcript id cited). Each cell cites its JSON path or command.
- [ ] Each verdict states its metric's scope (e.g. "after-window n=…, sessions started after the install only").
- [ ] Follow-up section dated 2026-11-04: spawns with a non-tier model have a reason; Stop medians over the week; observations per week; review job marker.
- [ ] The lead adds the follow-up as an idea (`tmux-ctl idea`) and reports the numbers to the user.

**Verify:** `grep -c '^| ' docs/superpowers/reports/runtime-phase1/measurement.md` → ≥ 6

```json:metadata
{"files": ["docs/superpowers/reports/runtime-phase1/measurement.md"], "verifyCommand": "grep -c '^| ' docs/superpowers/reports/runtime-phase1/measurement.md", "acceptanceCriteria": ["after Task 11; before = 2026-10-25 JSON", "four metric rows with sources", "scope stated per verdict", "2026-11-04 follow-up", "idea filed"], "modelTier": "standard"}
```

---

## Order and parallelism

- Task 1 first (gate). Tasks 2–7 touch disjoint files and may run as parallel teammates; Task 8 and Task 9 likewise (prose files vs skill files). Task 10 is read-only and can run beside them.
- Task 12 after 2–6 (it cites their numbers). Final whole-branch review, merge to `main` (user's choice at finish), then Task 11 (lead, live config), then Task 13.
