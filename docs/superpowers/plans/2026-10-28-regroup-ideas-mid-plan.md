# `regroup` Mid-Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `regroup` / `regroup: <hint>` message makes the lead regroup the ideas inbox mid-plan without stopping teammates, brainstorm the chosen ideas up to approved specs, and queue each spec to run after the current plan.

**Architecture:** A rules-only change to the lead's system prompt, `claude/orchestrator.md`: one new bullet in "Ideas inbox", an exception added to the "don't read the ideas file" bullet, and a queue step at the start of the "Next steps round". The queue is native tasks (`Plan & run: <spec path>`), which survive compaction and show in the `plan` window.

**Tech Stack:** Markdown.

**Spec:** `docs/superpowers/specs/2026-10-28-regroup-ideas-mid-plan-design.md`

## Global Constraints

- Trigger: a user message starting with `regroup` (any case), optionally `regroup: <hint>`.
- The running plan keeps running; teammates are not interrupted.
- Choices per group: **work on next** / park / drop.
- Brainstorming stops at an approved spec: no `writing-plans` while a plan runs.
- Queue task subject: `Plan & run: <spec path>`. It is blocked by every open task of the current plan and by the previous `Plan & run:` task.
- Idea marks: taken up `- [x] … → <spec path>`, dropped `- [-] …`, parked stays `- [ ]`. No idea is deleted.
- Work happens in the worktree `~/agent-board/.claude/worktrees/execution-flow` (branch `feat/execution-flow`).

**User decisions (already made):**
- "Task groupings" means the ideas inbox, regrouped mid-plan; the running plan's tasks are not reordered.
- Trigger is a chat prefix only (no board button, no `tmux-ctl` subcommand).
- A chosen idea is queued next; the running plan is not paused.

---

### Task 4: `regroup` rules in orchestrator.md

**Goal:** `claude/orchestrator.md` defines the `regroup` prefix and makes the Next steps round run queued specs first.

**Files:**
- Modify: `claude/orchestrator.md` (section "## Ideas inbox")

**Acceptance Criteria:**
- [ ] The "Don't read the ideas file" bullet reads: `- Don't read the ideas file while a plan is in progress, except for \`regroup\` below, and never mention it to teammates.`
- [ ] A `**\`regroup\`.**` bullet follows it, with the no-plan case and the five numbered running-plan steps from Step 2.
- [ ] The Next steps round's opening runs the `Plan & run:` tasks before reading the open ideas.
- [ ] `zsh tools/tests/test_prompt_argv.zsh` and `zsh tools/tests/test_plugin.zsh` still print `ALL PASS`.

**Verify:** `f=claude/orchestrator.md; grep -c 'except for `regroup` below' $f; grep -c '^- \*\*`regroup`\.\*\*' $f; grep -c 'Plan & run: <spec path>' $f; grep -c 'first take any pending `Plan & run:` tasks' $f; zsh tools/tests/test_prompt_argv.zsh | tail -1; zsh tools/tests/test_plugin.zsh | tail -1` → `1`, `1`, `1`, `1`, `ALL PASS`, `ALL PASS`

**Steps:**

- [ ] **Step 1: Add the exception.** Replace the line

```
- Don't read the ideas file while a plan is in progress, and never mention it to teammates.
```

with

```
- Don't read the ideas file while a plan is in progress, except for `regroup` below, and never mention it to teammates.
```

- [ ] **Step 2: Add the `regroup` bullet** directly after that line:

```
- **`regroup`.** A user message starting with `regroup` (any case), optionally `regroup: <hint>`, asks to pull an idea forward now.
  - No plan running: run the Next steps round now, with the group matching the hint first.
  - A plan running: it keeps running. Say so in one line, don't interrupt teammates, and keep answering their messages between these steps:
    1. Read the open ideas and group them as in the Next steps round. The group matching the hint goes first, marked as the user's pick.
    2. Ask with AskUserQuestion, per group: work on next / park / drop.
    3. Take each "work on next" group through `brainstorming`, one at a time, up to a written spec the user approved. Stop there: no `writing-plans` yet, because a second plan's tasks would mix with the running plan's in the one task list.
    4. For each approved spec, in the order chosen, create a pending task `Plan & run: <spec path>`, blocked by every open task of the current plan and by the previous `Plan & run:` task.
    5. Mark ideas as in step 4 of the Next steps round; parked ones stay `- [ ]`.
```

- [ ] **Step 3: Queue first in the Next steps round.** Replace

```
- **Next steps round.** When every plan task is complete and `finishing-a-development-branch` has run, read the open ideas (`- [ ]`):
```

with

```
- **Next steps round.** When every plan task is complete and `finishing-a-development-branch` has run, first take any pending `Plan & run:` tasks in order: `writing-plans` for the spec, execution, `finishing-a-development-branch`, then mark the task completed. Then read the open ideas (`- [ ]`):
```

- [ ] **Step 4: Run the Verify command** and check the six values.

- [ ] **Step 5: Commit.**

```bash
git add claude/orchestrator.md
git commit -m "docs(orchestrator): regroup pulls an idea forward mid-plan"
```
End the message with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/orchestrator.md"], "verifyCommand": "f=claude/orchestrator.md; grep -c 'except for `regroup` below' $f; grep -c '^- \\*\\*`regroup`\\.\\*\\*' $f; grep -c 'Plan & run: <spec path>' $f; grep -c 'first take any pending `Plan & run:` tasks' $f; zsh tools/tests/test_prompt_argv.zsh | tail -1; zsh tools/tests/test_plugin.zsh | tail -1", "acceptanceCriteria": ["exception wording on the don't-read bullet", "regroup bullet with no-plan case and five steps", "Next steps round runs Plan & run tasks first", "test_prompt_argv.zsh and test_plugin.zsh print ALL PASS"], "modelTier": "mechanical"}
```

---

## After merge (lead, at the integration step)

`claude/orchestrator.md` is read when a `dev` session starts, so this runs after the merge, in a new `dev` session.

1. **Real-state check (read-only):** `grep -c 'regroup' ~/agent-board/claude/orchestrator.md` = 2 on `main` (the exception line and the bullet). The real inbox `~/.local/state/agent-board/ideas/francisco_ruiz.md` has open ideas (Groups A and B were parked), so `regroup` has real input.
2. **End-to-end (scratch `dev` session, scratch repo, a 3-task plan running):** `regroup: <one open idea>` lists that idea's group first and teammates keep working. After a spec is approved, `TaskList` shows `Plan & run: <spec>` blocked by the open plan tasks. After the plan finishes, the lead runs `writing-plans` for the queued spec before reading the inbox. With no plan running, `regroup` runs the Next steps round at once. Use a copy of the ideas file in the scratch project, not the real one.
