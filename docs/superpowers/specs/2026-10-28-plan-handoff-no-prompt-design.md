# Plans run without the execution prompt

Date: 2026-10-28 · Source: ideas inbox (`francisco_ruiz`), 2026-10-16 15:21 "plans should always be run with subagent driven execution instead of prompting me for input" · Group C, idea 1 of 3 (2: faster iteration, 3: regroup command — separate specs).

## Problem

After `superpowers-extended-cc:writing-plans` saves a plan, its Execution Handoff is a HARD-GATE `AskUserQuestion` ("How would you like to execute it?": Subagent-Driven vs Parallel Session). The user always picks Subagent-Driven, so the question is a pure interruption. `writing-plans-extras` §3 already skips it, but only "when nobody is watching".

Execution itself already runs unattended: `subagent-driven-development` has "Continuous execution" and "Rulings, not stalls", and stops only for four things. The handoff question is the one remaining stop between a written plan and `finishing-a-development-branch`.

## Decisions (user, 2026-10-28)

- Scope: everything until finish. The only routine question is `finishing-a-development-branch`'s integration choice.
- The four safety stops of `subagent-driven-development` stay: an irreversible or destructive operation, a security-sensitive action, a side effect outside the worktree (merge, push to a shared branch, publish), and a plan so broken that every path is a guess.
- Approach B: a text override plus a structural hook. Text alone (approach A) loses to the base skill's "MUST call AskUserQuestion". Patching the plugin (approach C) is lost on update.

## Behaviour

1. When a plan is complete, the session invokes `superpowers-extended-cc:subagent-driven-development` directly. No question. In `dev` orchestrator mode, teammates take the tasks, as `claude/orchestrator.md` already says.
2. Exception: if the session's context is nearly exhausted, it prints the base skill's Parallel Session kickoff prompt in a fenced block (exactly as §3 does today for autonomous sessions) and ends the turn. It still does not ask.
3. Every other `AskUserQuestion` is unaffected, including the safety stops, the escalations in `subagent-driven-development`, and `finishing-a-development-branch`.

## Components

### 1. `claude/skills/writing-plans-extras/SKILL.md` §3

Retitle "Execution handoff: never ask". Body: in every session, skip the Execution Handoff `AskUserQuestion` and invoke `superpowers-extended-cc:subagent-driven-development` with the Skill tool. Keep the existing autonomous-session text as the nearly-exhausted-context exception (print the kickoff prompt, name the plan path, end the turn). Update the frontmatter `description` ("In autonomous sessions the execution handoff is a printed kickoff prompt instead of AskUserQuestion") and the closing self-check line ("an autonomous session ends with a printed prompt, not a question") to match.

`~/.claude/skills/writing-plans-extras` is a symlink to this file, so the change goes live on merge.

### 2. `claude/orchestrator.md`

In the workflow table row "Carrying out a plan", state that execution starts without asking the user to choose a method. One line; no other edits.

### 3. Hook `plan-handoff-guard.sh`

- Event: `PreToolUse`, matcher `AskUserQuestion`.
- Denies when any question in `tool_input.questions` has `header == "Execution"` or `question` matches `(?i)how would you like to execute`. Output: `hookSpecificOutput.permissionDecision = "deny"` with a reason telling the model to invoke `superpowers-extended-cc:subagent-driven-development` now, or to print the Parallel Session kickoff prompt if context is nearly exhausted, and not to re-ask.
- Passes (exit 0, no output) for every other question.
- Fails open: unreadable stdin, malformed JSON, or a missing field means exit 0.
- Kill switch: `PLAN_HANDOFF_GUARD=0` means exit 0.
- Lives in `claude/hooks/`, follows `kill-guard.sh`'s shape (bash wrapper, `python3 -I`, `--scoped` dedupe), and is registered both ways `kill-guard.sh` is: `claude/plugin/hooks/hooks.json` (scoped, through `claude/plugin/scripts/`) and `claude/settings.json` (global, through `~/.claude/hooks/`).

### 4. Tests: `claude/hooks/tests/test-plan-handoff-guard.sh`

Feed the script real `PreToolUse` JSON on stdin, in the style of the existing tests in that directory. Cases:
- the handoff question (header `Execution`) is denied, and the reason names `subagent-driven-development`;
- the same question with a different header but the "How would you like to execute it?" text is denied;
- an unrelated question passes with no output;
- malformed JSON passes (fail open);
- `PLAN_HANDOFF_GUARD=0` passes the handoff question.

## Acceptance

- The five test cases pass.
- In a fresh Claude session, completing a small plan through `writing-plans` goes straight into `subagent-driven-development` with no execution prompt. Verified once by hand in a scratch repo, with the hook's deny visible in the transcript if the model tried to ask.
- Other `AskUserQuestion` calls in the same session still reach the user.

## Out of scope

- Brainstorming's spec-review gate and the plan-writing questions. Those happen before a plan exists.
- Idea 2 (less fix back-and-forth) and idea 3 (regroup command): separate specs.
