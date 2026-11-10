# PCEE stage 2: plan registry, manifests and graphs (analysis only)

Date: 2026-11-10 · Stage 2 of `docs/superpowers/specs/2026-11-10-pcee-decomposition.md` · Gate: K1
Related: `docs/superpowers/specs/2026-11-10-queue-metrics-design.md` (run log, `metrics gate`),
`claude/orchestrator.md` (Queue mode), `claude/skills/writing-plans-extras/SKILL.md`

## Problem

PCEE schedules plans from their manifests: what each plan depends on, writes and reads. Three of its premises are
untested in this pipeline, and stage 3 onward is built on them:

1. **Plans are written just in time.** Each plan is written against the `main` the previous spec merged into.
   Concurrent execution needs every plan before the run, and then a plan can go stale when another merges first.
   What that costs is unknown.
2. **File sets are forecasts.** On the 12 baseline specs the plans' `files` lists cover a median 0.89 of the
   files really touched, and three specs are at 0.33, 0.45 and 0.60. Most misses are new files (fixtures) and
   final-review fixes.
3. **Overlap may leave little to run in parallel.** By declared files, 13 past plans colour into 7 waves under
   exclusive file locks.

This stage produces manifests, the two graphs and the predicted waves on real queues, and measures them against
what happened. Execution order and concurrency of implementation do not change.

## Decisions

- **All plans up front, in parallel**, by planner agents on **Opus** (the model that writes plans today, so a
  difference against baseline is not a model change).
- **A stale check before each spec runs**, with one refresh pass when a manifest file changed on `main`.
- **Graphs by code, plus one cross-plan model pass** that reads only manifests and the specs' titles and
  decisions.
- **Waves under three lock policies**; K1 reads the strict one.
- **K1's recall is measured on files that existed when the plan was written** (modified and appended). Recall on
  created files is reported, not gated.
- **Queue order of 2026-11-10:** this spec runs third (after queue-metrics and fast-test-suite). The four specs
  after it run with up-front plans and manifests; `pcee-engine` (stage 3) runs last, if K1 passes.

## Design

### 1. The manifest

Every plan carries one fenced block tagged `json:manifest` after its header:

    {"spec": "docs/superpowers/specs/2026-11-10-x-design.md",
     "base": "<commit of main the plan was written against>",
     "depends_on": [{"spec": "docs/superpowers/specs/…-y-design.md", "kind": "hard"},
                    {"spec": "…-z-design.md", "kind": "soft", "interface": "tmux-ctl wait-gone exit codes"}],
     "writes": [{"path": "bin/tmux-ctl", "mode": "modify"},
                {"path": "tools/tests/test_plugin.zsh", "mode": "append"},
                {"path": "tools/lib/wait.zsh", "mode": "create"}],
     "reads": ["board/relay.py"],
     "produces": ["tmux-ctl wait-gone"],
     "consumes": ["tc_tmux"],
     "tests": ["tools/tests/test_ctl_wait.zsh"]}

- `mode`: `create` (the path does not exist at `base`), `modify`, or `append` (the plan only adds lines or
  entries and changes none: a registry, a test list, a rules file).
- `depends_on.kind`: `hard` (cannot start before the other is merged) or `soft` (can start against the stated
  interface).
- `reads`: files whose content the plan's code or tests rely on and does not change.
- **Rule for plan writers**, added to `claude/skills/writing-plans-extras/SKILL.md` as a new numbered section, so
  every plan gets a manifest, up front or just in time: the block's fields; every path in any task's `files` is
  in `writes` or `reads`; fixtures and docs the tasks will create are listed as `create`; when unsure between
  `modify` and `append`, write `modify`.
- **Validation:** `tmux-ctl registry validate <plan>` checks the JSON, the modes against `base` (`create` paths
  absent, the others present), and that the tasks' `files` are covered. Exit 0, or 1 with one line per defect.

### 2. Up-front planning

One rule replaces "plan each spec when its turn comes" in Queue mode:

> Before running the next spec, if any pending `Plan & run:` spec that has no entry gate (section 6) has no
> plan yet, plan all of them up front.

So "at batch start" is the first spec boundary at which the rule is in force. When this stage itself merges in the
middle of a queue, the next boundary plans every remaining spec; queue-metrics and fast-test-suite have merged
by then and are not touched.

Up-front planning, in order:

1. `tmux-ctl metrics batch start --config upfront-seq <the pending specs without an entry gate>`: a new batch,
   because the configuration changes. Its id replaces `metadata.queue.batch` on those tasks.
2. Per spec, a planner agent, at most four at a time, each named `plan-<spec slug>` and started on Opus with
   a `Reason: up-front planner` line (it leaves the tier map). The lead runs `tmux-ctl metrics start` for the
   spec when it dispatches the planner. The planner:
   - creates the spec's branch and worktree off `main` as Queue mode does today;
   - runs `writing-plans` with the extras, and writes the plan file and its `.tasks.json` only. It creates no
     native tasks: a second plan's tasks would mix with the running plan's in the one task list. The lead creates
     them from the `.tasks.json` when the spec's run begins;
   - runs `registry validate` until it passes, commits the plan on the branch, and reports the path.
3. `tmux-ctl registry analyse <batch>` (section 4).
4. One cross-plan agent named `crossplan-<batch>`, frontier tier, given the batch's manifests and each spec's
   title and Decisions section, not the plans. It writes `relations.json`: a list of
   `{"a": <spec>, "b": <spec>, "kind": "conflict" | "order" | "interface", "why": "<one line>"}` for relations the
   manifests do not show. Then `tmux-ctl registry analyse <batch> --relations <file>` again.
5. The lead shuts the planners down and runs the queue in its existing order.

A spec whose planner fails, or whose plan never validates after one retry, is planned just in time when its turn
comes, as today; its record has `manifest` fields missing. Up-front planning never fails a spec.

### 3. Stale check and refresh

Before a spec runs (its turn in the queue), in its own worktree:

1. The lead rebases the spec's branch, which holds only its plan commits, onto `main`.
2. `tmux-ctl registry stale <spec>` lists the manifest's `modify`, `append` and `reads` paths that changed between
   the manifest's `base` and `main`, and `create` paths that now exist. It prints `fresh` (exit 0) or `stale` with
   the paths (exit 1).
3. `fresh`: the plan runs as written. `stale`: one refresh agent named `refresh-<spec slug>`, on Opus, gets the
   plan path and `git diff <base> main -- <stale paths>`, patches the plan, its `.tasks.json` and the manifest
   (new `base`), re-validates and commits. One refresh per spec; the plan then runs.
4. `writing-plans` is not run again. `subagent-driven-development` starts from the committed plan; its preflight
   scan still runs.

### 4. Registry, graphs and waves

`board/registry.py`, run through `tmux-ctl registry <sub>` as `tmux-ctl overview` runs its module. The registry
is the set of manifests of a batch's plans, read from the plan files on their branches. Nothing is stored in a
database in this stage.

- **Dependency graph:** an edge per `depends_on` entry, and per relation of kind `order`.
- **Conflict graph**, per lock policy:
  - `strict`: two plans conflict when one writes a path the other writes or reads.
  - `append`: as strict, except that two plans that both only `append` to a path do not conflict on it.
  - `writes_only`: two plans conflict only when both write a path.
  - A relation of kind `conflict` or `interface` is a conflict edge under every policy.
- **Clusters:** connected components of the plans joined by `hard` dependencies or by `strict` conflicts on
  a path that is not append-only for both.
- **Waves:** a greedy colouring of the conflict graph, most-conflicting plan first, in which a plan's wave is
  after the waves of its `hard` dependencies. Computed per policy. `parallelism` is specs divided by `strict`
  waves.
- **Output of `registry analyse <batch>`:**
  - `docs/superpowers/metrics/analysis/<batch>.md`: the manifest table, the two graphs as edge lists (relations
    from the cross-plan pass marked as such, with their `why`), clusters, waves per policy, hot files (written
    by three or more plans);
  - one `analysis` line in the run log:
    `{"kind": "analysis", "batch": …, "specs": n, "waves": {"strict": n, "append": n, "writes_only": n},
    "parallelism": x, "clusters": n, "relations": n}`. A later line for the same batch supersedes an earlier
    one.

### 5. What each run record gains, and prediction against outcome

`metrics record` fills these when the spec's plan has a manifest:

- `manifest` is computed from the manifest's `writes` instead of the tasks' `files`, and gains
  `recall_existing` (of the touched files that existed at the spec's base, the share listed as `modify` or
  `append`) and `recall_created` (of the touched files that did not exist, the share listed as `create`).
- `refreshes` (0 or 1) and `stale_paths` (a count).
- `manifest_tokens`: the tokens of the spec's `refresh-…` agent plus an even share of the batch's `crossplan-…`
  agent, found in the usage index by agent name and batch window. Writing the manifest block itself is part of
  planning and cannot be separated; whether up-front planning costs more than just-in-time planning shows in
  `metrics compare upfront-seq` (tokens per task against `seq-sdd`).

`tmux-ctl registry report <batch>`, run for the morning report, appends **Prediction against outcome** to the
analysis document:

- per spec: `recall_existing`, `recall_created`, `precision`, refreshes, the files missed;
- per pair of specs: predicted conflict under each policy against the real textual result (the parallel-buildable
  pairs of the metrics spec), totalled as predicted and clean, predicted and conflicting, not predicted and
  conflicting, not predicted and clean;
- the sentence that textual results do not show semantic conflicts.

### 6. Gate K1 and entry gates

- **Gate file** `docs/superpowers/metrics/gates/K1.md`, with the checkpoint in prose and:

      {"id": "K1", "min_specs": 4, "where": {"has": "refreshes"}, "conditions": [
        {"metric": "manifest.recall_existing", "agg": "median", "min": 0.9},
        {"metric": "analysis.parallelism", "agg": "last", "min": 1.5},
        {"metric": "manifest_tokens/tokens.total", "agg": "ratio_of_sums", "max": 0.10}]}

  `tmux-ctl metrics gate K1` prints each value against its threshold and `pass`, `fail` or `too early`.
- **Configuration file** `docs/superpowers/metrics/configs/upfront-seq.md`:
  `{"id": "upfront-seq", "baseline": false, "targets": [{"metric": "tokens_per_task", "max": 1.0}]}`.
- **Entry gates**, a Queue mode rule added here because up-front planning must skip gated specs: a spec whose
  header has a line `Entry gate: <id>` is not planned up front. When its turn comes the lead runs
  `tmux-ctl metrics gate <id>`. Exit 0: the spec is planned and run. Any other exit: the spec is not planned; its
  task is completed with `failed — gate <id>: <the command's output line>` and it is recorded with
  `metrics record … --outcome failed`.
- **If K1 fails,** the analysis document already shows the waves under `append` and `writes_only` and the
  pair table; the user adjusts the lock policy or the threshold in the gate file. Nothing in the queue decides
  that.
- With the minimum of four specs, `parallelism` can only be 4, 2, 1.33 or 1: K1 passes on waves only when the
  four specs fit in two strict waves. The gate prints the wave count beside the ratio.

### 7. Lead rules and taking effect mid-queue

Changes to Queue mode in `claude/orchestrator.md` (carrying the user's uncommitted edit as Queue mode's own rule
says): the boundary rule and the up-front procedure (section 2), the stale check (section 3), entry gates
(section 6), and in the morning report the analysis document's path after the Metrics section, with
`registry report` run before it.

A running lead keeps the rules it started with. So the plan's last task states, as a step the lead performs
after the merge: hand off to a fresh lead (`agent-board:handoff`; in Queue mode it relays without asking). The
new lead starts with the new rules and applies the boundary rule before the next spec.

## Error handling

- Analysis never blocks the queue: a `registry` command that fails prints one line (`registry: <sub>: <reason>`),
  exits non-zero, and the lead continues as today for the affected spec (plan just in time, no stale check).
- A plan without a valid manifest is left out of the graphs and named in the analysis document.
- `registry stale` on a plan without a manifest prints `no manifest` and exits 3; the plan runs as written.
- A refresh that fails or does not validate: the spec's old plan is discarded and the spec is planned just in
  time, as today.
- A missing or malformed `relations.json` is ignored with a line in the analysis document.

## Testing

- **Manifest:** parsing, each validation defect (bad JSON, a `create` path that exists, a `modify` path that does
  not, a task file not covered), on fixture plans.
- **Graphs and waves:** unit tests per policy on small fixtures (append-only pairs, write against read, a hard
  dependency forcing a later wave, a relation edge). One fixture built from the 13 real past plans' `files` lists
  as `modify` writes pins the strict wave count (7 in the 2026-11-10 measurement; ties between equally
  conflicting plans are broken by spec path, and the plan pins the count that rule gives).
- **Stale check:** a scratch repository where `main` moves a manifest path, a path outside the manifest, and
  creates a path the manifest lists as `create`.
- **Record fields:** `recall_existing` and `recall_created` on a scratch repository; `manifest_tokens` from a
  fixture usage database with `refresh-…` and `crossplan-…` agent rows.
- **Gate:** the K1 file through `metrics gate` for pass, fail on each condition, and too early.
- **Suites:** no new failures beyond those known on `main` when this runs.
- **First live use:** the four specs after this one. Evidence, as a user gate in the morning report: four plans
  with valid manifests committed before the first of them ran, the analysis document with Prediction against
  outcome, and the `PCEE:` status line showing K1's values.

## Out of scope

- Any change to the order or concurrency of implementation; locks; the scheduler; SQLite; the worker pool
  (stage 3 onward).
- Read and write sets finer than files (modules, interfaces as lock targets): `produces` and `consumes` are
  recorded and shown, not used in the graphs, except through the cross-plan pass.
- Semantic-conflict detection.
