# Queue mode follow-ups

Date: 2026-11-05 · Status: approved design, awaiting spec review
Builds on: `docs/superpowers/specs/2026-11-05-overnight-queue-design.md` (merged in `791cf52`).
Source: the two findings parked by the overnight-queue final re-review (ledger
`docs/superpowers/ledgers/2026-11-05-overnight-queue/progress.md`, the `Final fix: parked` lines).

## Problem

1. **Ideas re-asked after the queue.** In the Next steps round (`claude/orchestrator.md`), when two or
   more groups are chosen, step 3 queues their specs and starts Queue mode, and "the ideas steps 1–4 wait
   until the queue is empty". Step 4 (mark ideas `- [x] … → <spec>` / `- [-] …`) therefore has not run
   when the queue finishes, so the next round reads those ideas as still open (`- [ ]`) and asks about
   groups whose specs already ran.
2. **The running plan's integration answer is underspecified.** The overnight-queue spec says the running
   plan (Queue mode started from `regroup` while a plan runs) gets its own question "counted in call 1's
   question cap"; `orchestrator.md` instead gives it the queue default and leaves it out of the "which specs
   differ" multiSelect. The shape of `metadata.queue.current` is not stated, so push consent for that
   plan's branch when the default is the MR is undefined.

## Design

### 1. Mark ideas at queue time

In the Next steps round step 3, when two or more groups are chosen: after the approved specs are queued as
`Plan & run:` tasks and before Queue mode starts, mark the ideas as step 4 says (`- [x] … → <spec path>` for
each queued group, `- [-] …` for each dropped one). Step 4 then has nothing left to do for those ideas. The
round that runs after the queue reads only `- [ ]` ideas, so it never offers a group that was queued.
One group chosen: unchanged (step 4 runs after brainstorming, as now).

`regroup` step 5 already marks its ideas when it queues; no change there.

### 2. The running plan is an item in the exceptions list

User decision (2026-11-05): no separate question.

- The running plan takes the queue's default integration.
- The "which differ from the default" multiSelect lists the running plan first, by its plan title
  (`Running plan: <title>`), then the queued specs. It counts as one item toward the 3-items-per-question
  limit. If it is picked, call 2 asks its option like any excepted spec.
- The MR push consent covers the running plan's branch when its integration is the MR, the same as the
  specs' branches; still never `main` or `master`.
- Storage: the first `Plan & run:` task carries
  `metadata.queue.current = {"plan": "<plan path>", "integration": "merge" | "mr" | "keep", "push": true | false, "answeredAt": "<ISO>"}`,
  `answeredAt` read from `date -u +%Y-%m-%dT%H:%M:%SZ`. The running plan's `finishing-a-development-branch`
  uses it instead of its menu. The handoff doc lists it as it does now.

### 3. Spec alignment

Update `docs/superpowers/specs/2026-11-05-overnight-queue-design.md` (the "running plan" paragraph near
line 67) to section 2: drop "counted in call 1's question cap", say the plan is the first item of the
exceptions multiSelect, and give the `metadata.queue.current` shape.

## Files

- `claude/orchestrator.md`: Next steps round step 3 (mark at queue time); Queue mode step 1 (running plan
  as the first exceptions item, `metadata.queue.current` shape, push consent covers its branch). Keep the
  Queue mode bullet as short as it is now or shorter.
- `docs/superpowers/specs/2026-11-05-overnight-queue-design.md`: section 3 alignment.
- `tools/tests/test_plugin.zsh`: checks, each seen failing first:
  - the Next steps round says ideas are marked when queued (an exact phrase chosen at implementation);
  - Queue mode names `Running plan:` as an exceptions item;
  - Queue mode gives the `metadata.queue.current` shape with `"plan"`.

The user's uncommitted edit to the "Carrying out a plan" row of `claude/orchestrator.md` is never committed;
it crosses the merge as a dry-run-checked patch.

## Testing

`zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, rc=0, `grep -c FAIL` = 0. No dry run: the
change is rule text, and the overnight-queue e2e (`tools/tests/e2e-overnight-queue.md`) already lists the
regroup-built queue under `## Not covered`.

## Not in scope

M3, M4 and the other minors the overnight-queue final review left (see that ledger).
