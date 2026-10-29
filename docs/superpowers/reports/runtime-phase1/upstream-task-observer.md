# Upstream feedback draft: task-observer skill size and session-start cost

Target: maintainers of the `task-observer` skill (plugin `task-observer:task-observer`).
Scope: a cost problem in how the skill loads, and a proposed split. No code is included.

## Problem

The skill's `SKILL.md` is large, and it is loaded in full whenever the skill is invoked, even when the session only needs the session-start check.

- `SKILL.md`: 44,715 chars. At the usual ~4 chars/token estimate that is about 11,179 tokens per load (estimate from file size, not from a tokenizer).
- Measured use: the `Skill` tool was called for `task-observer` 29 times, across 28 of 65 lead sessions in the audit window (30 days). So a full load happens in roughly 43% of lead sessions in the window.

The skill's Session Start Protocol needs only a few facts: whether the workspace storage is usable, how many observations are open, whether a review is due, and how many staged updates are waiting. None of those needs the full procedure text.

## Proposal

1. **Ship a cheap session-start stub.** A small script that prints the four session-start facts as a SessionStart `additionalContext` string. It is run by a harness hook, so the session gets the status without loading the skill.
2. **Load the full `SKILL.md` on demand only**, when the session has to:
   - write an observation (through `scripts/new-observation.sh`, which the skill already requires),
   - run a review the user opted into, or
   - reconcile staged updates.

The stub stays in the hook, so the "check before the first tool call" rule is still enforced without the full file in context.

## Measured example: the stub's output

Real output of `sh claude/hooks/task-observer-session-start.sh` in the current workspace. The `additionalContext` string is 564 chars. The absolute workspace path in the output has been replaced with `~/.task-observer`; nothing else was changed.

```json
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Task observer: workspace ok · 29 open · last review 2026-10-28 · 0 staged updates. Load the task-observer skill (no Skill arguments) only to write an observation, to run a review the user opted into, or to reconcile staged updates. Observations are created only by scripts/new-observation.sh. Re-read this summary before writing or proposing a plan. Teammates and subagents never load it and report findings to the lead. Workspace (pinned, never the cwd or a worktree): ~/.task-observer. Details: ~/.task-observer/README.md."}}
```

Expected effect: the session-start context drops from a 44,715-char file (about 11,179 tokens, estimated) to the 564-char summary, and the full procedure is paid for only in the sessions that write, review or reconcile.

## Open questions for maintainers

- Whether "re-read this summary before writing or proposing a plan" should stay in the stub, or move into the skill body.
- Whether the teammate and subagent exception (they never load the skill and report findings to the lead) should be enforced by the stub's wording alone, or also by the hook's matcher.

Status: draft, not submitted.
