# Project-wide concurrent execution engine (PCEE): decomposition and checkpoints

Date: 2026-11-10 · Source: the user's ChatGPT conversation "Compare Agent Architectures" (2026-11-09), brainstormed
with the user through the lead on 2026-11-10.
Related: `docs/superpowers/specs/2026-11-10-queue-metrics-design.md` (sub-project 1, the only spec written so far),
`claude/orchestrator.md` (Queue mode), `docs/superpowers/reports/2026-11-05-queue.md`.

This is not a spec to implement. It fixes the target, the order of the sub-projects and the checkpoints at which
the build is adjusted or stopped. Each sub-project gets its own brainstorm, spec, plan and run.

## Target

The user chose the full PCEE as the target architecture for running many specs of one project:

- a plan registry with a manifest per plan (dependencies, read and write sets, interfaces, tests, tier),
- a dependency graph and a resource-conflict graph, with tightly coupled plans grouped into clusters,
- locks above git (exclusive and shared, on files, modules and interfaces),
- a pool of disposable workers in worktrees instead of teams,
- a deterministic, event-driven scheduler in code, with the lead as architect and exception handler only,
- an integration coordinator with a merge queue and change packages,
- execution state in SQLite, with the board as a view of that state.

Decided with it:

- **Hard ceiling:** the weekly usage limit. Tokens per plan come down first (the lead's share above all); plans
  then run in parallel inside that budget, paced against the limit.
- **Scope:** every project run with agent-board. Nothing project-specific in the engine; per-project facts such as
  hot files are data.
- **Input:** approved specs, as in today's queue. Plans may all be written up front; a plan going stale when
  another merges first must be handled.
- **Measurement:** on real work only. No frozen replays and no dedicated benchmark runs; real queues are run
  under named configurations and compared (sub-project 1).

## Measured starting point (queue of 2026-11-05, 12 specs, this repo)

From the usage index, git and the ledgers; method and per-spec table in the queue-metrics spec.

- $199 priced for 12 specs; 599 active minutes; 49 tasks. About 50 active minutes, 49M tokens and $11.73
  (median) per spec. Fable 5.2 calls are unpriced and count as $0.
- The Opus lead is 48 to 74% of each spec's cost, almost all of it cache reads of its own context.
- The queue stopped at 96% of the weekly limit after 7 specs and waited four days for the reset.
- Two or more agents were active in 25% and 10% of the minutes of two measured stretches; none in 24% and 46%.
- 36 of 78 plan pairs share a declared file. Three registry-style files cause most of it
  (`tools/tests/test_plugin.zsh` in 7 plans, `claude/plugin/.claude-plugin/plugin.json` in 5,
  `claude/orchestrator.md` in 5).

## Risks carried into the build

The architect recommended a thinner engine and the user chose PCEE. These measured risks are not reargued here;
each one is tied to a checkpoint below.

| Risk | Evidence | Checkpoint |
| --- | --- | --- |
| Exclusive file locks give little parallelism | A greedy colouring of the 13 real plans by declared files gives 7 waves: under 2x | K1, K4 |
| Clusters collapse into serial execution | The cluster rule would put the five mod plans in one cluster | K1 |
| File sets are forecasts, not contracts | Tasks were added mid-plan (relay-launch-check Task 5); declared and actual file counts differ (queue-keep-awake 6 declared, 15 touched) | K1 |
| More tokens per plan | Manifests, a cross-plan analysis pass and change packages are new work, and tokens stopped the last queue | K1, K2, K3 |
| Semantic conflicts pass locks and text merges | Only tests and review on the merged result catch them; the full suite takes 885 s today | K3, K4 |
| Parallel runs reach the limit sooner | The weekly limit, not the clock, bounded the last queue | K4, sub-project 6 |

## Sub-projects, in order

### 1. Measurement on real work

Spec: `docs/superpowers/specs/2026-11-10-queue-metrics-design.md`. A run log per project, per-spec and per-batch
metrics, the baseline from the queue already run, and the decision rule every checkpoint below uses.

### 2. Plan registry, manifests and graphs: analysis only

All queued specs are planned up front. Each plan gets a manifest. The dependency and conflict graphs, the clusters
and the predicted waves are computed and reported. The queue still runs as it does today, so this sub-project
tests PCEE's premises before any engine exists.

**Checkpoint K1** (adjust before building further if missed):

- Manifest accuracy: median `manifest.recall` at least 0.9 (the share of files a plan really touched that its
  write set declared).
- Predicted parallelism: specs divided by predicted waves under the lock policy at least 1.5.
- Cost: manifest and analysis tokens at most 10% of the plans' tokens.

If predicted parallelism misses, the lock policy changes first (for example an append lock class for registry
files) rather than the engine being built on it.

### 3. Execution state, scheduler and worker pool at concurrency 1

SQLite execution state, the deterministic scheduler and disposable workers. The engine replaces the lead as the
queue runner, in today's order, one spec at a time.

**Checkpoint K2:** tokens-per-task index at most 1.0 against baseline, and the lead share below the baseline's
range (48 to 74%). If tokens per task rise, the engine is reworked or stopped.

### 4. Merge queue and change packages at concurrency 1

Workers stop merging. Integration goes through the merge queue; failures are repaired at change-set level.
Prerequisite: `docs/superpowers/specs/2026-11-10-fast-test-suite-design.md` has run.

**Checkpoint K3:** integration tokens and minutes (from "work finished" to "merged") no higher than today's
finishing step; failed share inside the quality veto of the decision rule.

### 5. Locks, clusters and worktree workers at concurrency above 1

**Checkpoint K4** (the main one):

- Accepted tasks per active hour at least 1.5 times baseline in every challenger batch.
- Tokens-per-task index at most 1.0.
- Lock wait under 30% of a spec's elapsed time (median).
- Repair runs per spec no higher than the baseline's fix-wave rate.

If missed: adjust the lock policy or the cluster rule once and measure again. If missed again, stop at
sub-project 4's sequential engine.

### 6. Adaptive concurrency and optimisation

Concurrency paced against the weekly limit, model optimisation, selective ensemble review, the board as a view
of engine state.

## The five specs queued on 2026-11-10

| Spec | Relation |
| --- | --- |
| `2026-11-10-fast-test-suite-design.md` | Independent. Prerequisite of sub-project 4. |
| `2026-11-10-telegram-fixes-design.md` | Independent. |
| `2026-11-10-queue-reliability-design.md` | Patches the lead-run queue. Still worth running: that queue is the measured baseline and stays in use until K2 passes. Sub-project 3 replaces what it patches. |
| `2026-11-10-restart-recovery-design.md` | Same as queue-reliability. |
| `2026-11-10-interactive-tasks-window-design.md` | Displays the lead's task list and queue. Sub-project 3 changes its data source. |

## Considered and not chosen

- **Lean lead:** keep the lead and teams, shorten the lead's context, parallel lanes. Smallest change; the lead
  stays the serial thread and the top cost.
- **Thin engine with optimistic integration** (the architect's recommendation): a scheduler in code and a merge
  queue, no locks or manifests, the style of executing one plan replaceable and chosen by measurement. Pays for
  conflicts after the work is done.
- **Solo plan agent:** one agent per spec, no team and no per-task reviews, one adversarial review at the end.
  Attacks tokens per plan directly; risks one large late fix wave.
- **Merge the specs before execution:** one combined plan and branch. Removes overlap by construction; all or
  nothing.

If K1 or K4 fails after its one adjustment, the thin engine and the solo plan agent are the first alternatives
to measure, with the same run log.
