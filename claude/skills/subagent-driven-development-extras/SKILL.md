---
name: "subagent-driven-development-extras"
description: Local additions to superpowers-extended-cc:subagent-driven-development. Use together with subagent-driven-development, every time it runs, before dispatching the first implementer. It overrides the base "Review the task" and "The fix loop" sections in three places. A report without a green verify goes back to the implementer before any reviewer is dispatched. A small fix on a mechanical task is re-reviewed on the mechanical tier. Consecutive mechanical tasks share one batched review with a verdict per task.
---

# subagent-driven-development extras

Load alongside `superpowers-extended-cc:subagent-driven-development`. Where this file and the base skill disagree, this file wins; everything else in the base skill stands. The levers cut review rounds, never review: every task still gets a spec verdict and a quality verdict, and every fix still gets a re-review.

The plugin's routing gate allows a dispatch model only from the in-progress task's tier or `standard`. Each lever stays inside that limit. Leave `SUPERPOWERS_ROUTING_GUARD` unset; if a dispatch is blocked, change the dispatch to a model the gate allows.

## 1. Green before review

Overrides: base "3. Review the task", which dispatches the reviewer once a report exists.

Add to every implementer brief: the report must carry the task's `verifyCommand` as the exact command, its output, and its exit code. Where the repo has `.agent-ci.yml`, it must also carry `agent-ci check` output for the task's diff.

Before any reviewer dispatch, read the report file. Both results present and both exit 0: dispatch the reviewer. Either one missing or red: **bounce**. Send the report back to the same implementer with the missing or failing item quoted.

- A bounce is not a fix round and does not count toward the 5-round cap.
- Ledger: `Task <N>: bounced <k>/2 (<what was missing or red>)`.
- A third bounce makes the task `BLOCKED`, handled by the base escalation (a fresh implementer on a higher tier).

Why: a reviewer spends a whole round finding what one command already shows.

Example: a report that says "tests pass" with no command output is bounced, not reviewed: `Task 4: bounced 1/2 (no verifyCommand output in report)`.

## 2. Small-fix re-review on the task's tier

Overrides: base "4. The fix loop", where every scoped re-review is a standard-tier dispatch.

A fix is **small** when FIX_BASE..HEAD has ≤20 changed lines, ≤2 files, no added files, no deleted or skipped tests, and the fix report shows the covering tests green.

- Small fix on a `mechanical` task: dispatch the scoped re-review with `model: haiku` and an effort-low agent type, using the base `re-review-prompt.md` unchanged.
- Every other fix (larger, or on a `standard` or `frontier` task): the base standard-tier re-review.
- The re-review always happens. Only the reviewer's tier changes.
- Ledger: `Task <N>: fix round <R>/5 (small, mechanical re-review) …`.

Why: a one-line fix on a mechanical task does not need a standard-tier reviewer, and the gate allows Haiku while a mechanical task is in progress. On any other task the gate refuses it, so those keep `standard`.

Example: a 6-line fix in one file on a mechanical task, covering test green in the fix report, goes to a Haiku re-review. The same 6 lines on a `standard` task go to the standard re-reviewer.

## 3. Batched review for consecutive mechanical tasks

Overrides: base "3. Review the task", which reviews each task on its own.

Consecutive `mechanical` tasks that passed the lever 1 check form a batch. It closes at 5 tasks, at the next non-mechanical task, or at the plan's end.

- Never batched, whatever the tier: a task whose files or brief touch security (auth, IAM, secrets), migrations, CI configuration or shared config. It gets the base per-task review.
- A batched task stays `in_progress` until its batch is reviewed. The gate reads the in-progress task's tier, and the batch reviewer runs at `standard`, which it always allows.
- One standard-tier reviewer gets `scripts/review-package PLAN_FILE <batch base> <batch head>`, each task's brief and report paths, and the global constraints. It returns spec and quality verdicts **per task**.
- Each task's findings enter that task's own fix loop (lever 2 applies). A task is marked complete only when its own verdicts pass.
- The final whole-branch review is unchanged.
- Ledger: `Batch <first>-<last>: reviewed together (<n> tasks)`.

Why: five trivial tasks cost five reviewer cold starts; one reviewer reads them together.

Example: tasks 2, 3 and 4 are mechanical and green; task 5 edits `.gitlab-ci.yml`. Tasks 2-4 are reviewed as one batch; task 5 gets its own review.

## Before you finish

Walk the progress ledger and confirm:

- [ ] Every reviewer dispatch was preceded by a green bounce check (command, output, exit 0 in the report).
- [ ] Every Haiku re-review was on a `mechanical` task with a small fix.
- [ ] No batch held a security, migration, CI or shared-config task.
- [ ] Every batched task got its own spec and quality verdicts.
- [ ] No routing-gate block occurred, and `SUPERPOWERS_ROUTING_GUARD` is unset.
