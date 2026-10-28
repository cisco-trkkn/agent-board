# Less fix back-and-forth, same quality

Date: 2026-10-28 · Source: ideas inbox (`francisco_ruiz`), 2026-10-21 14:13 "teammates and orchestrators seem to spend a lot of time going back and forth correcting bugs uncovered by tests… checking and rechecking work adds a lot of overhead" · Group C, idea 2 of 3 (1: [plans run without the execution prompt](2026-10-28-plan-handoff-no-prompt-design.md), 3: regroup command).

## Problem

`superpowers-extended-cc:subagent-driven-development` runs every task through the same steps: implementer → task review (spec + quality) → fix loop of up to 5 rounds, each round being a fix dispatch plus a scoped re-review. The user named three time sinks (2026-10-28):

1. **Tests fail after "done".** An implementer reports done and the review (or tester) finds red or unrun tests. A whole review round is spent finding out something a command would have shown.
2. **A re-review for every tiny fix.** A one-line fix costs a fix dispatch plus a fresh standard-tier reviewer.
3. **The same ceremony for trivial tasks.** A `mechanical` task gets the same per-task review as a risky one.

Not a time sink (user): the lead relaying messages between teammates.

## Decisions (user, 2026-10-28)

- Approach A: all three levers, in a new local skill `subagent-driven-development-extras`. It is loaded alongside the base skill, the same way as `writing-plans-extras`, `requesting-code-review-extras` and `test-driven-development-extras`.
- Rejected: B (lever 1 only), because it leaves time sinks 2 and 3. C (reviewers patch trivial findings themselves), because the reviewer would grade its own fix, which the base skill forbids.
- Thresholds: a small fix is ≤20 changed lines in ≤2 files; a batch is at most 5 tasks; at most 2 bounces.

## Constraints found during design

- The plugin's model-routing gate (`hooks/pre-agent-model-routing`) allows a dispatch only on the in-progress task's tier or the reviewer tier (`standard`), and checks effort the same way. So a Haiku/low re-review is allowed only while a `mechanical` task is in progress. The design stays inside the gate. It does not loosen the gate and does not use `SUPERPOWERS_ROUTING_GUARD=0`.
- The base skill's rule "the fix was small, skip the re-review" is listed as a rationalization. Lever 2 changes who re-reviews, never whether.

## Design

### Lever 1: green before review

- The implementer brief (in the extras skill's addendum to the dispatch) requires the report to include, for the task's `verifyCommand`, the exact command, its output, and its exit code. Where the repo has `.agent-ci.yml`, it also requires `agent-ci check` output for the task's diff, as `claude/orchestrator.md` rule 4 already demands of teammates.
- Before dispatching any task reviewer, the lead checks the report: both results are present and both exited 0. This is a mechanical read of the report file, with no judgement.
- A missing or red result is a **bounce**: the report goes back to the same implementer with the missing or failing item quoted. A bounce is not a fix round and does not count toward the 5-round cap. Ledger line: `Task <N>: bounced <k>/2 (<what was missing or red>)`.
- A third bounce makes the task `BLOCKED`, handled by the base skill's escalation (a fresh implementer on a higher tier).

### Lever 2: small-fix re-review on the task's tier

- A fix diff (FIX_BASE..HEAD) is **small** when all of these hold: ≤20 changed lines, ≤2 files, no added files, no deleted or skipped tests, and the fix report shows the covering tests green.
- A small fix on a `mechanical` task gets its scoped re-review (base skill's `re-review-prompt.md`, unchanged) dispatched on the mechanical tier: `model: haiku`, an effort-low agent type.
- Every other fix (not small, or on a `standard`/`frontier` task) keeps the base path: a standard-tier re-reviewer.
- The re-review always happens. Ledger line: `Task <N>: fix round <R>/5 (small, mechanical re-review) …`.

### Lever 3: batched review for consecutive mechanical tasks

- Consecutive `mechanical` tasks whose reports passed lever 1 form a batch. It closes at 5 tasks, at the next non-mechanical task, or at the end of the plan.
- Never batched, whatever the tier: a task whose files or brief touch security (auth, IAM, secrets), migrations, CI configuration or shared config. Such a task gets the base per-task review.
- The batch gets one task reviewer at the standard tier, with one review package `scripts/review-package PLAN_FILE <batch base> <batch head>`, each task's brief and report path, and the global constraints. The reviewer returns spec and quality verdicts **per task**.
- Each task's findings enter that task's normal fix loop (with lever 2 applying). A task is marked complete only when its own verdicts pass.
- A batched task stays `in_progress` until its batch is reviewed. Because the routing gate reads the in-progress task's tier, the batch reviewer is dispatched at `standard`, which the gate always allows.
- The final whole-branch review is unchanged.

### Wiring

- `claude/skills/subagent-driven-development-extras/SKILL.md`: the three levers, written as overrides of named base-skill sections ("Review the task", "The fix loop"), plus a self-check list. Written with `superpowers-extended-cc:writing-skills` and `writing-for-agents`.
- `~/.claude/skills/subagent-driven-development-extras`: a symlink to it (the install pattern of the other extras skills; check `docs/INSTALL.md` / `install.sh` for how links are made).
- `~/.claude/CLAUDE.md`, "Plan and review companions": one entry, "Whenever `superpowers-extended-cc:subagent-driven-development` runs, also load `subagent-driven-development-extras` (green before review, small-fix re-review tier, batched mechanical review)". This file is not under git: back it up first (`CLAUDE.md.bak-YYYYMMDD`).
- `claude/orchestrator.md`, workflow table, row "Carrying out a plan": name the extras skill.

## Acceptance

- A recorded run of a small scratch plan (≥3 `mechanical` tasks, 1 `standard` task, with one planted red verify and one planted small finding) shows in its ledger: a `bounced` line, a `small, mechanical re-review` round, and one batch review covering the mechanical tasks with a verdict per task.
- In that run, no dispatch was blocked by the routing gate, and `SUPERPOWERS_ROUTING_GUARD` was not set.
- The `standard` task got the base per-task review.
- A `mechanical` task touching CI configuration was reviewed on its own, not in the batch.

## Out of scope

- Changing the plugin's skills or hooks.
- Lead relaying between teammates (not a time sink, per the user).
- Idea 3 (regroup command): separate spec.
