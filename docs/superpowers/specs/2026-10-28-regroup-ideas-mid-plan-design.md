# `regroup`: pull an idea forward mid-plan

Date: 2026-10-28 · Source: ideas inbox (`francisco_ruiz`), 2026-10-17 03:56 "sometimes after a group of tasks has been completed I want to refresh the remaining task groupings bc an idea I had should get worked on sooner. I want a command to quickly indicate that intention to the agent" · Group C, idea 3 of 3 (1: [plans run without the execution prompt](2026-10-28-plan-handoff-no-prompt-design.md), 2: [faster fix loop](2026-10-28-faster-fix-loop-design.md)).

## Problem

`claude/orchestrator.md` reads the ideas inbox only at the **Next steps round**, after every plan task is complete and `finishing-a-development-branch` has run. It also forbids reading the ideas file while a plan is in progress. An idea that becomes urgent mid-plan has no path forward except interrupting the lead in free text.

## Decisions (user, 2026-10-28)

- "Task groupings" means the **ideas inbox**, regrouped mid-plan. The running plan's own tasks are not reordered.
- Trigger: a chat prefix, like `idea:`. No board button and no `tmux-ctl` subcommand.
- The running plan **keeps running**. A chosen idea is brainstormed now and queued to run next, after the current plan finishes and before the normal Next steps round.

## Behaviour

**Trigger.** A user message to the lead starting with `regroup` (case-insensitive), optionally `regroup: <hint>`, where the hint names an idea in the user's words.

**With a plan running:**
1. The lead confirms in one line that the plan continues and that teammates are not interrupted. It keeps answering teammates' messages between the steps below.
2. It reads the open ideas (`- [ ]`) of `~/.local/state/agent-board/ideas/<project>.md`, and of the older `~/.claude/ideas/<project>.md` if present. It groups related ideas as in the Next steps round. The group matching the hint is listed first and marked as the user's pick.
3. It asks with `AskUserQuestion`, one question per group: **work on next** / park / drop.
4. It takes each "work on next" group through `superpowers-extended-cc:brainstorming`, one at a time, up to a written spec the user has approved. It stops there: no `writing-plans`, because a second plan's tasks in the session's one task list would mix with the running plan's tasks.
5. For each approved spec, in the order chosen, it creates a pending task `Plan & run: <spec path>`, `blockedBy` every task of the current plan that is not completed, and also by the previous queue task, so queued specs run in order. The task list survives compaction and handoff, and the `plan` window (2026-10-28-plan-window-design.md) shows it.
6. It marks ideas taken up `- [x] … → <spec path>` and dropped ones `- [-] …`. Parked ideas stay `- [ ]`. No idea is deleted.

**When the current plan finishes:** `finishing-a-development-branch` runs as today. Then each queue task in order: `superpowers-extended-cc:writing-plans` for its spec, execution, which starts with no prompt once spec 1 lands, then `finishing-a-development-branch`. After the queue is empty comes the normal Next steps round.

**With no plan running:** `regroup` runs the Next steps round immediately; `regroup: <hint>` puts the hinted group first.

## Changes

Only `claude/orchestrator.md`:
- **Ideas inbox:** a bullet for the `regroup` prefix, with steps 1–6 above, stated as the one exception to "Don't read the ideas file while a plan is in progress".
- **Next steps round:** before step 1, "run any `Plan & run:` queue tasks first, in order".

`claude/orchestrator.md` is the lead's system prompt for `dev` sessions, so the change applies to new `dev` sessions once merged to `main`.

## Acceptance

Manual check in a scratch `dev` session on a scratch repo with a 3-task plan running and two open ideas:
- `regroup: <second idea>` lists that idea's group first; teammates keep working (their windows show progress during the brainstorm).
- After the spec is approved, `TaskList` shows `Plan & run: <spec>` pending, blocked by the open plan tasks; the ideas file shows the idea as `- [x] … → <spec>`.
- After the plan finishes and `finishing-a-development-branch` runs, the lead starts `writing-plans` for the queued spec before reading the inbox for the Next steps round.
- With no plan running, `regroup` runs the Next steps round at once.

## Out of scope

- Reordering the running plan's own tasks.
- A board button or `tmux-ctl` subcommand for `regroup`.
- Pausing the running plan for an idea.
