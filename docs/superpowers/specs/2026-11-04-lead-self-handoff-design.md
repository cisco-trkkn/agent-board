# Lead self-handoff and teammate respawn

Idea (2026-11-04 13:35): "the lead should be allowed to run handoff by itself for itself or a teammate".

## Problem

`claude/plugin/skills/handoff/SKILL.md` sets `disable-model-invocation: true`, so only the user can start a
handoff by typing `/handoff`. When the context guard fires, the lead can only recommend it. A teammate whose
context is heavy has no defined replacement flow; `claude/worker.md:94` tells it to report to the lead, and
the lead has no procedure for what to do next.

## Decisions (user, 2026-11-04)

- The lead hands its own session off on its own judgment, and relays **without asking**.
- A teammate handoff is checkpoint + shutdown + respawn under the same name; no doc, no user question.
- One skill with two modes (not a second skill).

## Design

### 1. Skill gate (`claude/plugin/skills/handoff/SKILL.md`)

- Remove `disable-model-invocation: true` from the frontmatter. Update the `description` so the model knows
  when to pick it: lead hands its session to a fresh orchestrator, or (`teammate <name>`) replaces one teammate.
- Step 4 ("Ask before switching") gains a branch: **self-started** means the user did not type `/handoff`
  in the message that started this turn. Self-started: skip the AskUserQuestion, print one line
  `Handing off to a fresh orchestrator: <doc>` and go straight to step 5's **On Yes** path. User-started:
  ask exactly as today. The sentence "Never run the relay without a Yes from this question" becomes
  "When the user started the handoff, never run the relay without a Yes from this question."
- Outside tmux, self-started still ends with the existing outside-tmux fallback (no relay is possible).

### 2. Teammate mode (same file, new section before step 1)

Arguments starting with `teammate <name>` select this mode; the rest of the skill does not run.

1. Send that teammate the step-1 checkpoint message (same text).
2. Wait up to 2 minutes. No reply: record `no checkpoint` plus `tmux-ctl read "✦ <name>" 40`
   (or `tmux-ctl read <name> 40` without the ✦ prefix).
3. Send a `shutdown_request` (same `reason` suffix as step 3) and wait for the termination notice. Idle at
   its prompt is not gone.
4. Respawn with the same `name`, role and tier (same `subagent_type`/`model` as the tier map in
   `claude/orchestrator.md`). The prompt is the usual teammate rules (orchestrator.md rules 1–5), then the
   checkpoint note (task, files owned, progress, next step, assumptions, risks); for `no checkpoint`, the
   captured output and "re-check the state of your files before continuing".
5. Check the new pane is alive (`tmux list-panes -a -F '#{window_name} #{pane_dead}'`), respawn if dead.
6. Report one line to the user: `respawned <name> from checkpoint` (or `from captured output`).

No doc, no AskUserQuestion. Re-set the teammate's task `owner` only after the new brief is sent
(orchestrator.md rule: brief before owner).

### 3. When the lead uses it (`claude/orchestrator.md`, new section "Handing off on your own")

- Own session: on the lead's judgment. Typical triggers: the context guard warning, or heavy context at a
  natural boundary (a task's review passed, between plan tasks, after a merge).
- Never while an AskUserQuestion answer is pending, or in the middle of a merge, rebase or other git
  operation, or between a teammate's dispatch and its brief.
- Once per session: after `tmux-ctl relay` is scheduled, do nothing else in the turn.
- Teammate: when a teammate reports the guard, or the lead judges its context heavy, run the skill with
  `teammate <name>`.
- Update the windows-table line `tmux-ctl relay <doc>: used only by agent-board:handoff` only if wording
  needs it; the relay stays lead-only.

`claude/orchestrator.md` has an uncommitted user change in the live checkout. Work happens in a worktree off
`main`; the implementer edits only the new section there and the merge must keep the user's working-tree
change intact (it is not part of this branch).

### 4. Guard message (`claude/hooks/context-size-guard.sh`)

The hook runs for every Claude session, not only agent-board leads, so the text covers both:

- `ctx` (model-facing): "If you are the agent-board lead (orchestrator) inside tmux, run the
  agent-board:handoff skill yourself at the next safe point, with a one-line argument naming the next
  session's focus. Otherwise begin your reply with one short line recommending the user run /handoff…"
  (rest as today).
- The teammate sentence on non-UserPromptSubmit events stays: "If you are a teammate, tell the lead in your
  next message."
- `msg` (user-facing systemMessage) keeps recommending `/handoff` or `/compact`, and adds "(the lead may
  hand off on its own)".

`claude/worker.md:94` is unchanged: teammates never hand off on their own.

### 5. Tests

- `claude/hooks/tests/test-context-size-guard.sh`: assert the new lead sentence is in `additionalContext`
  for UserPromptSubmit and PostToolUse, and the teammate sentence is still present on PostToolUse.
- New check (shell or Python, in the matching suite): `claude/plugin/skills/handoff/SKILL.md` frontmatter has
  no `disable-model-invocation`, and the file contains a `teammate <name>` section.
- New zsh test `tools/tests/test_relay_refuse.zsh`: on the scratch tmux server, `tmux-ctl relay <doc>` from a
  window other than `claude` exits non-zero, prints `relay refused`, and schedules nothing (no
  `relay-*.log` written). None exists today (`grep -l 'relay refused' tools/tests/*.zsh` is empty).

## Out of scope

- Teammates handing themselves off.
- Any change to `board/relay.py` or the relay mechanics.
- A handoff doc for teammate respawns.
