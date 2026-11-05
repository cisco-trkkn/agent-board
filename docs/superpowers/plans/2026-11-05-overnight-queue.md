# Overnight Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With two or more `Plan & run:` specs queued, the lead asks every integration question in one up-front batch, then plans, runs, integrates and reports each spec with no further input.

**Architecture:** Rules only: a `Queue mode` bullet in `claude/orchestrator.md`'s "Ideas inbox" section, pointers from the places that would otherwise ask (finishing row, Next steps round, `regroup` step 4), one line in the handoff skill, and text checks in `tools/tests/test_plugin.zsh`. Answers live in the `Plan & run:` tasks' metadata. A real dry run proves it.

**Tech Stack:** Markdown rules, zsh tests (`tools/tests/lib.zsh` `check`), Claude Code CLI for the dry run.

**Spec:** `docs/superpowers/specs/2026-11-05-overnight-queue-design.md`

## Global Constraints

- Work in the worktree `.claude/worktrees/overnight-queue`, branch `feat/overnight-queue` off `main`. Never edit the live checkout `/Users/francisco.ruiz/agent-board`: it is the install, and it holds the user's uncommitted `claude/orchestrator.md` edit (the "Carrying out a plan" table row), which this branch must never include.
- `claude/orchestrator.md` style: one bullet per rule, plain words, no new top-level `##` section (the queue rules sit inside "Ideas inbox"). Backticked skill names follow the existing `test_plugin.zsh` rules (superpowers names with their `superpowers-extended-cc:` prefix; agent-board skills with `agent-board:`; non-shipped skills only on a line that says "If installed").
- The up-front batch is at most two AskUserQuestion calls (three only when more than four specs are excepted). No other question while the queue runs.
- Answers: `metadata.queue = {"integration": "merge" | "mr" | "keep", "push": true | false, "answeredAt": "<ISO>"}` on each `Plan & run:` task; outcome: `metadata.outcome` = `merged <sha>` / `mr <url>` / `kept <branch>` / `failed — <one line>`.
- Morning report path: `docs/superpowers/reports/YYYY-MM-DD-queue.md`.
- Commits: conventional with scope, ending with the attribution trailer your harness specifies.

**User decisions (already made):**
- Trigger: "≥2 Plan & run tasks".
- Integration answers: "One answer, per-spec override".
- On failure: "Keep branch, go on" — leave it unmerged, note it, next spec off `main` as it stands.
- Approach A: rules in `claude/orchestrator.md` only, answers in task metadata, no new command or state file.

---

### Task 1: Queue mode rules and their checks

**Goal:** `claude/orchestrator.md` carries the Queue mode rules and the three pointers, the handoff skill records `Queue mode: on`, and `test_plugin.zsh` pins all of it.

**Files:**
- Modify: `claude/orchestrator.md` (Ideas inbox section: `regroup` step 4 at line 64, Next steps round at line 66, new Queue mode bullet after it; Workflow table row "Finishing a branch" at line 101)
- Modify: `claude/plugin/skills/handoff/SKILL.md` (the **State of the work** bullet, line 44)
- Test: `tools/tests/test_plugin.zsh` (six new `check` lines before `tt_done`)

**Acceptance Criteria:**
- [ ] The six new checks fail before the text change (RED, each for its missing phrase) and pass after it.
- [ ] `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`, `grep -c FAIL` on its output = 0.
- [ ] The diff to `claude/orchestrator.md` adds only the Queue mode bullet and the three pointer edits (no other line changes), and does not include the user's uncommitted "Carrying out a plan" row edit.

**Verify:** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS` and `rc=0`

**Steps:**

- [ ] **Step 1: Add the failing checks** to `tools/tests/test_plugin.zsh`, just before the final `tt_done`:

```zsh
O="$R/claude/orchestrator.md"
check "lead rules: Queue mode bullet" grep -qF -- '- **Queue mode.**' "$O"
check "lead rules: queue answers in metadata.queue" grep -qF 'metadata.queue' "$O"
check "lead rules: queue starts at two or more Plan & run tasks" grep -qF 'two or more pending `Plan & run:` tasks' "$O"
check "lead rules: morning report path" grep -qF 'docs/superpowers/reports/YYYY-MM-DD-queue.md' "$O"
check "lead rules: finishing row points at Queue mode" zsh -c 'grep "^| Finishing a branch" "$1" | grep -qF "Queue mode"' _ "$O"
check "handoff doc records Queue mode: on" grep -qF 'Queue mode: on' "$P/skills/handoff/SKILL.md"
```

Mutations (each was run by the plan author against the current text and exits 1): drop the bullet → check 1 fails; drop `metadata.queue` → 2; reword the trigger → 3; drop the report path → 4; leave the finishing row as is → 5; drop the handoff line → 6.

- [ ] **Step 2: RED.** `zsh tools/tests/test_plugin.zsh 2>&1 | grep -c '^FAIL'` → `6` (exactly the six new checks; the rest pass). Record the output in the report.

- [ ] **Step 3: Edit `claude/orchestrator.md`.**

a) `regroup` step 4 (line 64): append to the end of the line: ` Then apply Queue mode below.`

b) Next steps round (line 66): after "then mark the task completed." insert: ` In Queue mode (below) the ideas steps 1–4 wait until the queue is empty.`

c) Insert this bullet directly after the Next steps round's four numbered sub-steps (after line 70, before the blank line that ends the section), exactly:

```markdown
- **Queue mode.** Queued specs run overnight without the user. Check when a Next steps round starts and right after `regroup` step 4 creates a `Plan & run:` task: two or more pending `Plan & run:` tasks, and none has `metadata.queue` yet, start queue mode. A queue whose tasks already carry `metadata.queue` (a resumed or handed-off session) is not asked again.
  1. **Ask once, up front**, before running anything, with at most two AskUserQuestion calls; every question names the specs by title and stands on its own. Call 1: the default integration for every queued spec (merge to `main` locally / push and open an MR / keep the branch); which specs differ from it (multiSelect, with a None option); and, only when the default is the MR, consent to push those branches and run `gitlab-ci-loop` on them (If installed). Call 2, only when call 1 named exceptions: each excepted spec's option (more than four exceptions need a third call), plus the push consent if an exception chose the MR and call 1 did not ask it. A push yes is the user's "asked to push" for those branches only, never `main` or `master`; a no turns them into "keep the branch". Write each answer to its task with TaskUpdate: `metadata.queue = {"integration": "merge" | "mr" | "keep", "push": true | false, "answeredAt": "<ISO>"}`. A spec queued after the batch gets one question when it is queued, with the queue default recommended.
  2. **Run each spec in order:** branch off `main` as it stands now, in a worktree under `.claude/worktrees/`; `superpowers-extended-cc:writing-plans`, then a fresh Skill call to `superpowers-extended-cc:subagent-driven-development`; then `superpowers-extended-cc:finishing-a-development-branch` with the stored option instead of its menu (its tests before and after, the live-checkout checks and the worktree cleanup still run; an uncommitted user edit crosses the merge as a dry-run-checked patch). Mark the task completed with `metadata.outcome`: `merged <sha>` / `mr <url>` / `kept <branch>` / `failed — <one line>`.
  3. **A spec that fails is skipped, not asked about:** where `superpowers-extended-cc:subagent-driven-development` would stop for one of its four stop classes, or the merged result goes red, the final review leaves load-bearing findings, or the user's patch won't apply, keep the branch unmerged, record `failed — <why>`, and go on with the next spec. A spec that builds on a failed one is still attempted. User-gate tasks are not run; they wait for the morning. A teammate permission prompt waiting more than 10 minutes is recorded, and if the spec cannot progress it fails with `blocked on a permission prompt in ✦ <name>`.
  4. **Handoffs** during the queue relay without asking; the doc's State of the work says `Queue mode: on`.
  5. **Morning report**, when the last `Plan & run:` task is completed: write `docs/superpowers/reports/YYYY-MM-DD-queue.md` (the run's start date) and commit it on `main` (leave it uncommitted if the live checkout is mid-change), then `tmux-ctl artifact <path>`. Per spec: title and spec path, outcome, branch or merge commit or MR URL, every `Ruling:` from its ledger with what it costs if wrong, user-gate checks waiting, permission prompts seen. Then leave queue mode and run the ideas steps.
```

d) Workflow table, row "Finishing a branch" (line 101): change `it asks the user how to integrate` to `it asks the user how to integrate (in Queue mode, use the stored answer: see Queue mode)`.

- [ ] **Step 4: Edit `claude/plugin/skills/handoff/SKILL.md`** line 44 (the **State of the work** bullet): append to the end of the bullet: ` In queue mode, add the line \`Queue mode: on\`; the answers live in the \`Plan & run:\` tasks' metadata.`

- [ ] **Step 5: GREEN.** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`; then `zsh tools/tests/test_plugin.zsh 2>&1 | grep -c FAIL` → `0`. Also `git diff main -- claude/orchestrator.md | grep -c '^[-+][^-+]'` and confirm by reading the diff that only steps 3a–3d changed.

- [ ] **Step 6: Commit** `claude/orchestrator.md`, `claude/plugin/skills/handoff/SKILL.md`, `tools/tests/test_plugin.zsh` (stage these paths only): `feat(lead): queue mode runs queued specs without asking`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/plugin/skills/handoff/SKILL.md", "tools/tests/test_plugin.zsh"], "verifyCommand": "zsh tools/tests/test_plugin.zsh; echo rc=$?", "acceptanceCriteria": ["six new checks RED then GREEN", "test_plugin ALL PASS rc=0, FAIL count 0", "orchestrator diff is only the Queue mode bullet and three pointers, no user edit"], "modelTier": "standard"}
```

---

### Task 2: Real dry run of a two-spec queue

**Goal:** A real lead, started with the branch's `claude/orchestrator.md`, given two queued tiny specs in a scratch repo, asks exactly one up-front AskUserQuestion call, merges both specs, and writes the morning report.

**Files:**
- Create: `tools/tests/e2e-overnight-queue.md` (the run's procedure and result: not a test script, since a real Claude run is not repeatable in CI; name keeps it out of run-all)

**Acceptance Criteria:**
- [ ] Scratch setup: a temp git repo `Q` with one commit containing `README.md` and two specs `docs/superpowers/specs/2026-11-05-a-design.md` ("add a line `alpha` to README.md") and `…-b-design.md` ("add a line `beta` to README.md"), plus a copy of this repo's `docs/superpowers/model-routing.json`. A scratch tmux server `~/.local/bin/tmux -L oq-$$ -f /dev/null`; `TC_STATE`, `TC_IDEAS_DIR` and `TC_CONTEXT_DIR` point at temp dirs, so no real board state or ideas file is touched.
- [ ] Real long-lived state: the lead runs with the user's real `~/.claude` config and installed plugins (the setup every real overnight run uses), only its system prompt file is the branch's: `claude --model opus --append-system-prompt-file <worktree>/claude/orchestrator.md` in a pane of the scratch server, cwd `Q`.
- [ ] First prompt, typed by the tester: ``Create two pending tasks, `Plan & run: docs/superpowers/specs/2026-11-05-a-design.md` and `Plan & run: docs/superpowers/specs/2026-11-05-b-design.md` (b blocked by a), then run the Next steps round.`` The tester answers the one batch with: default "merge to main locally", exceptions None. The tester answers permission prompts in the scratch panes only for commands inside `Q` or the temp dirs, and records each one.
- [ ] Results, all read from real artefacts: the lead's session transcript (`~/.claude/projects/<Q-slug>/<id>.jsonl`) has exactly 1 `AskUserQuestion` tool_use before the report is written (count printed with the transcript path); `git -C Q log --oneline main` shows both specs' commits; `README.md` on `main` has `alpha` and `beta`; `Q/docs/superpowers/reports/2026-11-05-queue.md` (or the run's date) exists with one section per spec, each naming its outcome `merged <sha>`.
- [ ] Clean-up: the scratch server is killed, no `✦` or `claude` process from the run survives (`ps` check, by PID), and the live checkout `git status` is unchanged.
- [ ] Time cap 60 minutes. If the lead asks a second question or stalls, stop, save the capture and transcript excerpt in the doc, and report BLOCKED with that evidence rather than retrying.

**Verify:** `grep -c '^## ' tools/tests/e2e-overnight-queue.md` → `4` (sections: Setup, Run, Results, Clean-up)

**Steps:**

- [ ] **Step 1:** Write `tools/tests/e2e-overnight-queue.md` with the four sections, Setup first (the exact commands you will run, using the values above).
- [ ] **Step 2:** Run it. Watch with `capture-pane -p` on the scratch server; never type into the user's real windows.
- [ ] **Step 3:** Fill Results with the counts, paths and command outputs from the acceptance criteria, and Clean-up with the `ps` and `git status` evidence.
- [ ] **Step 4:** Commit `tools/tests/e2e-overnight-queue.md` only: `test(lead): dry run of a two-spec overnight queue`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["tools/tests/e2e-overnight-queue.md"], "verifyCommand": "grep -c '^## ' tools/tests/e2e-overnight-queue.md", "acceptanceCriteria": ["scratch repo with two tiny specs, scratch tmux -f /dev/null, temp TC_STATE/TC_IDEAS_DIR/TC_CONTEXT_DIR", "real ~/.claude config with the branch orchestrator.md", "one AskUserQuestion tool_use before the report in the transcript", "both specs merged to Q main, README has alpha and beta", "morning report with one section per spec naming merged <sha>", "scratch server and processes gone, live checkout unchanged", "60 min cap, BLOCKED with evidence on a second question"], "modelTier": "standard"}
```
