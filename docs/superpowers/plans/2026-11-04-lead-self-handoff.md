# Lead self-handoff and teammate respawn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The lead can start `agent-board:handoff` itself (relaying without asking) and can replace one teammate with `handoff teammate <name>`.

**Architecture:** Prose changes to the handoff skill and the lead rules, plus a wording change in the context guard hook. Tests are grep checks in `tools/tests/test_plugin.zsh` and the existing bash test of the guard.

**Tech Stack:** Markdown skills, bash hook, zsh test harness (`tools/tests/lib.zsh`).

**Spec:** `docs/superpowers/specs/2026-11-04-lead-self-handoff-design.md`

## Global Constraints

- Work in the worktree `.claude/worktrees/lead-self-handoff` on branch `feat/lead-self-handoff` off `main` (the live checkout is the install). Never edit the live checkout.
- `claude/worker.md` is not changed: teammates never hand off on their own.
- `board/relay.py` and `tmux-ctl relay` are not changed. Relay refusal from non-lead windows is already tested in `tools/tests/test_ctl_relay.zsh:20-31`, so the spec's proposed `test_relay_refuse.zsh` is not written (spec §5 third bullet is satisfied by the existing test).
- The live checkout has an uncommitted user change to `claude/orchestrator.md`; the branch never includes it, and integration must keep it intact (lead's concern at finishing).
- Commits: conventional with scope (`feat(handoff): …`, `fix(hooks): …`, `docs(lead): …`), ending with the attribution trailer your harness specifies.
- Editing skills: use the `writing-for-agents` skill's rules for SKILL.md text.

**User decisions (already made):**
- "leads judgement, no ask": the lead hands its own session off on its own judgment and relays without asking.
- Teammate handoff = "Checkpoint + respawn": no doc, no user question.
- One skill with two modes (approach A).

---

### Task 1: Handoff skill — model-invocable, self-started relay, teammate mode

**Goal:** `claude/plugin/skills/handoff/SKILL.md` can be invoked by the model, skips the switch question when self-started, and has a `teammate <name>` mode.

**Files:**
- Modify: `claude/plugin/skills/handoff/SKILL.md`
- Test: `tools/tests/test_plugin.zsh`

**Acceptance Criteria:**
- [ ] Frontmatter has no `disable-model-invocation` line; `description` names both uses (lead hands its session to a fresh orchestrator; `teammate <name>` replaces one teammate) so the model knows when to pick it.
- [ ] Step 4 defines self-started as "the user did not type `/handoff` in the message that started this turn"; self-started skips AskUserQuestion, prints `Handing off to a fresh orchestrator: <doc>` and takes step 5's On Yes path; user-started asks as today.
- [ ] The sentence "Never run the relay without a Yes from this question." is replaced by "When the user started the handoff, never run the relay without a Yes from this question."
- [ ] Outside tmux, self-started still ends with the outside-tmux fallback.
- [ ] A section `## Teammate mode` placed before `## 1.` covers spec §2 steps 1–6: same checkpoint message, 2-minute wait with `tmux-ctl read "✦ <name>" 40` fallback, shutdown_request with the step-3 `reason` suffix and wait for termination, respawn with same name/role/tier (orchestrator.md tier map) with teammate rules 1–5 then the checkpoint note (or captured output + "re-check the state of your files before continuing"), pane-alive check and respawn if dead, one-line report `respawned <name> from checkpoint` / `from captured output`, brief before re-setting the task `owner`, no doc, no AskUserQuestion; and says the rest of the skill does not run.
- [ ] Four new checks in `tools/tests/test_plugin.zsh` pass, and each fails against today's SKILL.md (RED run recorded).

**Verify:** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`

**Steps:**

- [ ] **Step 1: Add the failing checks** after line 65 (`handoff skill merges Context learned …`) in `tools/tests/test_plugin.zsh`:

```zsh
H="$P/skills/handoff/SKILL.md"
check "handoff skill is model-invocable (no disable-model-invocation)" zsh -c '! sed -n "1,/^---$/{/^---$/!p;}" "$1" | grep -q "^disable-model-invocation"' _ "$H"
check "handoff skill has a Teammate mode section with teammate <name>" zsh -c 'grep -q "^## Teammate mode" "$1" && grep -qF "teammate <name>" "$1"' _ "$H"
check "handoff self-started relay prints its line" grep -qF 'Handing off to a fresh orchestrator: <doc>' "$H"
check "handoff asks only when the user started it" grep -qF 'When the user started the handoff, never run the relay without a Yes from this question.' "$H"
```

Mutations: restoring `disable-model-invocation: true` fails check 1; deleting the `## Teammate mode` heading fails check 2; the other two fail on today's text.

- [ ] **Step 2: RED.** Run `zsh tools/tests/test_plugin.zsh 2>&1 | grep -E '^(FAIL|ALL|[0-9]+ FAILED)'` → the four new checks print `FAIL - …`.
- [ ] **Step 3: Edit SKILL.md** to meet every acceptance criterion. Keep existing steps 1–3 and 5 intact apart from the sentences named above.
- [ ] **Step 4: GREEN.** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`.
- [ ] **Step 5: Commit** `git add claude/plugin/skills/handoff/SKILL.md tools/tests/test_plugin.zsh` then `git commit -m "feat(handoff): the lead may start the handoff itself and replace one teammate"` with your harness's trailer.

```json:metadata
{"files": ["claude/plugin/skills/handoff/SKILL.md", "tools/tests/test_plugin.zsh"], "verifyCommand": "zsh tools/tests/test_plugin.zsh; echo rc=$?", "acceptanceCriteria": ["no disable-model-invocation in frontmatter; description names both uses", "self-started skips the question, prints the line, takes On Yes", "Yes-sentence scoped to user-started", "outside tmux fallback kept", "Teammate mode section covers spec 2 steps 1-6", "four new test_plugin checks pass and failed RED"], "modelTier": "standard"}
```

---

### Task 2: Context guard tells the lead to hand off itself

**Goal:** The guard's model-facing text tells an agent-board lead to run the handoff skill itself; others still get the `/handoff` recommendation.

**Files:**
- Modify: `claude/hooks/context-size-guard.sh:45-46`
- Test: `claude/hooks/tests/test-context-size-guard.sh`

**Acceptance Criteria:**
- [ ] `additionalContext` (UserPromptSubmit and PostToolUse) contains `run the agent-board:handoff skill yourself`.
- [ ] `systemMessage` contains `(The lead may hand off on its own.)`.
- [ ] The teammate sentence is unchanged on non-UserPromptSubmit events; the `/handoff` recommendation stays in `additionalContext`.
- [ ] The test passes with `failed=0`, including the existing real-transcript replay (`PASS real 48822fd2 replay`, real long-lived state).

**Verify:** `bash claude/hooks/tests/test-context-size-guard.sh 2>&1 | tail -1` → `passed=36 failed=0`

**Steps:**

- [ ] **Step 1: Add failing checks** to `claude/hooks/tests/test-context-size-guard.sh`. After the line `check "UPS: no teammate sentence" …` add:

```bash
check "UPS: lead told to hand off itself" "$(sm "$o" '.hookSpecificOutput.additionalContext' | grep -c 'run the agent-board:handoff skill yourself')" "1"
check "UPS: systemMessage says the lead may hand off" "$(sm "$o" '.systemMessage' | grep -cF '(The lead may hand off on its own.)')" "1"
```

After the line `check "PostToolUse: teammate sentence" …` add:

```bash
check "PostToolUse: lead told to hand off itself" "$(sm "$o" '.hookSpecificOutput.additionalContext' | grep -c 'run the agent-board:handoff skill yourself')" "1"
```

Mutation: reverting the hook's `ctx` line fails both "lead told" checks (probe run by the plan author on today's code: count `0`).

- [ ] **Step 2: RED.** `bash claude/hooks/tests/test-context-size-guard.sh 2>&1 | grep -E '^FAIL|passed='` → three FAIL lines, `passed=33 failed=3`.
- [ ] **Step 3: Replace lines 45-46** of `claude/hooks/context-size-guard.sh` with:

```bash
msg="🛑 CONTEXT AT ${k}K TOKENS (limit ${THRESHOLD}). Run /handoff: it checkpoints the team, writes a handoff doc and asks before switching this window to a fresh orchestrator. Or /compact to stay here. (The lead may hand off on its own.)"
ctx="IMPORTANT: This session's context is ${k}K tokens, past the user's ${THRESHOLD}-token budget. If you are the agent-board lead (the orchestrator in a tmux dev session's claude window), run the agent-board:handoff skill yourself at the next safe point, with a one-line argument naming the next session's focus. Otherwise begin your reply with one short, prominent line strongly recommending the user run /handoff (it checkpoints the team, writes the doc, and asks before relaying to a fresh orchestrator in this window). Suggest a one-line /handoff argument describing what the next session should focus on. Then answer their message normally."
```

- [ ] **Step 4: GREEN.** `bash claude/hooks/tests/test-context-size-guard.sh 2>&1 | tail -1` → `passed=36 failed=0`.
- [ ] **Step 5: Commit** `git add claude/hooks/context-size-guard.sh claude/hooks/tests/test-context-size-guard.sh` then `git commit -m "fix(hooks): context guard tells the lead to run the handoff itself"` with your harness's trailer.

```json:metadata
{"files": ["claude/hooks/context-size-guard.sh", "claude/hooks/tests/test-context-size-guard.sh"], "verifyCommand": "bash claude/hooks/tests/test-context-size-guard.sh 2>&1 | tail -1", "acceptanceCriteria": ["additionalContext has the lead sentence on UPS and PostToolUse", "systemMessage has the lead-may-hand-off note", "teammate sentence and /handoff recommendation kept", "passed=36 failed=0 incl. real 48822fd2 replay"], "modelTier": "mechanical"}
```

---

### Task 3: Lead rules — when to hand off on your own

**Goal:** `claude/orchestrator.md` has a section "Handing off on your own" covering spec §3.

**Files:**
- Modify: `claude/orchestrator.md` (new section after "## Starting from a handoff")
- Test: `tools/tests/test_plugin.zsh`

**Acceptance Criteria:**
- [ ] New section `## Handing off on your own` states: own session on the lead's judgment (context guard warning, or heavy context at a natural boundary: a task's review passed, between plan tasks, after a merge); never while an AskUserQuestion answer is pending, mid merge/rebase or other git operation, or between a teammate's dispatch and its brief; once per session, nothing else after the relay is scheduled; teammate: when it reports the guard or the lead judges its context heavy, run the skill with `teammate <name>`; the relay stays lead-only.
- [ ] The windows-table line `tmux-ctl relay <doc>: used only by agent-board:handoff` is unchanged.
- [ ] One new check in `tools/tests/test_plugin.zsh` passes and failed RED.
- [ ] Only the new section is added; `git diff main -- claude/orchestrator.md` shows additions only in that section.

**Verify:** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`

**Steps:**

- [ ] **Step 1: Add the failing check** after Task 1's checks in `tools/tests/test_plugin.zsh`:

```zsh
check "lead rules: Handing off on your own, with teammate <name>" zsh -c 'awk "/^## Handing off on your own/{f=1;next} /^## /{f=0} f" "$1" | grep -qF "teammate <name>"' _ "$R/claude/orchestrator.md"
```

Mutation: removing the section (or its `teammate <name>` mention) fails it.

- [ ] **Step 2: RED.** `zsh tools/tests/test_plugin.zsh 2>&1 | grep -E '^FAIL'` → the new check fails.
- [ ] **Step 3: Write the section** meeting the acceptance criteria, in the file's style (short bullets).
- [ ] **Step 4: GREEN.** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`.
- [ ] **Step 5: Commit** `git add claude/orchestrator.md tools/tests/test_plugin.zsh` then `git commit -m "docs(lead): when the lead hands off on its own or replaces a teammate"` with your harness's trailer.

```json:metadata
{"files": ["claude/orchestrator.md", "tools/tests/test_plugin.zsh"], "verifyCommand": "zsh tools/tests/test_plugin.zsh; echo rc=$?", "acceptanceCriteria": ["section Handing off on your own covers spec 3", "relay table line unchanged", "new test_plugin check passes and failed RED", "diff adds only that section"], "modelTier": "standard"}
```
