# PCEE stage 3: execution state, scheduler and worker pool at concurrency 1

Date: 2026-11-10 · Stage 3 of `docs/superpowers/specs/2026-11-10-pcee-decomposition.md` · Gate: K2
Entry gate: K1
Related: `docs/superpowers/specs/2026-11-10-queue-metrics-design.md` (run log, decision rule, gates),
`docs/superpowers/specs/2026-11-10-pcee-registry-design.md` (manifests, up-front plans, entry gates),
`claude/orchestrator.md` (Queue mode), `claude/worker.md`, `claude/skills/subagent-driven-development-extras/SKILL.md`

## Problem

One Opus lead session runs the whole queue. On the 12 baseline specs it is 48 to 74% of each spec's cost, nearly
all cache reads of its own long context, and every task waits on one of its turns. The weekly limit stopped the
last queue after 7 specs. Most of what the lead does per task is routine: dispatch, check that a command is
green, hand a report to a reviewer, count fix rounds, merge.

This stage moves the routine into code. An engine process owns the queue's state and schedules disposable
workers, one job at a time. A strong model is called only for the fixed cases code cannot decide.

The strongest case against it: this rebuilds in code the judgment loop the lead performs, and the lead's reading
of reports produced real catches (a task added mid-plan from a root cause; minors promoted to Important). An
architect job sees less than the lead did. Gate K2 therefore watches quality as well as tokens.

## Decisions

- **Engine process with SQLite state**; jobs as **disposable, visible workers**; today's review policy as **code**;
  an **architect job** for a fixed list of escalation cases.
- **Split queues** until K2 is decided: half the specs under the lead, half under the engine, assigned by code,
  one spec at a time.
- **One spec, two plans in sequence:** part 1 `engine run <spec>` (one spec end to end), part 2 the queue runner.
- **Control tokens** (the lead plus architect jobs) are counted together, so judgment moved into a job does not
  flatter the lead share.
- Concurrency stays 1. No locks, no merge queue, no change packages (stages 4 and 5).

## How Queue mode runs this spec

- **Entry gate.** The header line `Entry gate: K1` is the registry spec's entry gate: this spec is not planned up
  front. At its turn the lead runs `tmux-ctl registry report <batch>` for the batch of specs that ran with manifests,
  then `tmux-ctl metrics gate K1` (append-aware parallelism on verified appends, recall on existing files,
  manifest tokens, at least 4 specs). Exit 0: go on. Any other exit: nothing is planned;
  both tasks below are completed with `failed — gate K1: <the command's output line>` and recorded with
  `tmux-ctl metrics record … --outcome failed`.
- **Two tasks.** The spec is queued as two tasks, the second blocked by the first:
  `Plan & run: docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-1` and `…#part-2`. Each gets its own
  `writing-plans` run covering only that part of this document (the sections below are marked Part 1 and Part 2;
  everything else applies to both), its own branch, plan file (`…-pcee-engine-part-1.md`, `…-part-2.md`, whose
  `Spec:` line carries the `#part-N` suffix), execution and finishing step.
- **Part 2 depends on part 1.** If part 1's outcome is not `merged`, part 2 is not planned; its task is completed
  with `failed — part 1: <part 1's outcome>`.
- The gate is checked once, at part 1's turn.
- Metrics records use the spec path with its `#part-N` suffix as the spec id, so the two runs do not supersede
  each other.
- Both parts are built by the lead as today (the engine does not exist yet). After part 2 merges, the lead hands
  off to a fresh lead, as the two earlier stage specs require, so the new Queue mode rules are in force.

## Design

### Part 1: `engine run <spec>`

#### 1. State

- One SQLite database per project: `~/.local/state/agent-board/engine/<project>.sqlite` (`TC_ENGINE_DIR`
  overrides the directory; tests use it). Not the temporary directory. WAL mode; every state change is one
  transaction that also appends its event.
- Tables:
  - `specs`: spec id, queue position, runner (`lead` or `engine`), integration answer and push consent, batch id,
    state, outcome, worktree, branch, plan path.
  - `jobs`: id, spec, kind, task number, tier, model, effort, state, attempt, brief path, report path, window and
    pane, base and head commits, start and end times.
  - `events`: append-only: time, spec, job, kind, detail. This is the ledger; `Ruling:` lines are events of kind
    `ruling`.
- Spec states: `queued`, `planning`, `running`, `final_review`, `integrating`, `done`. Job states: `pending`,
  `running`, `done`, `failed`, `escalated`.
- Briefs, reports and review packages are files under the spec's git-ignored workspace
  (`<worktree>/.superpowers/engine/`), as SDD's are today.

#### 2. Workers

- One job is one fresh Claude in its own tmux window in the project's session, in the spec's worktree, started
  from a brief file on the model and effort its tier maps to (`docs/superpowers/model-routing.json`), with
  `claude/worker.md` as its rules. Nothing runs hidden.
- `tmux-ctl agent` gains `--dir <worktree>`: start the worker in an existing worktree instead of creating its own.
  Window name: `<spec slug>·<job kind><task number>`.
- **Report contract.** The brief names the report file. The report's last fenced block is tagged `json:status`:
  - implementer, fixer, refresher: `{"status": "done" | "blocked", "commits": ["…"], "concerns": ["…"]}`
  - reviewer: `{"verdict": "pass" | "findings", "findings": [{"severity": "critical" | "important" | "minor",
    "task": n, "text": "…"}]}`
  - architect: `{"decision": "proceed" | "retry_higher_tier" | "park" | "fail_spec", "ruling": "…",
    "cost_if_wrong": "…"}`
- **Finish detection.** The engine reads the agent-status file whose `pane` is the worker's pane (the mod
  already writes it). State `ready` with a valid report: the job is done and the engine kills that window by the
  pane id it started. `ready` with no valid report: one line typed with `tmux-ctl tell` naming the report path;
  a second `ready` without it fails the attempt. A window that is gone without a report fails the attempt.
- **Waiting on the user.** A worker in `needs-you` is left alone (the board shows it). After 10 minutes the spec
  fails with `blocked on a permission prompt in <window>`, as Queue mode says today.
- A failed attempt is run once more with a fresh worker; a second failure goes to an architect job.

#### 3. The job graph and its policy

`engine run <spec>` takes a spec whose plan and manifest exist (stage 2) and compiles the plan's `.tasks.json`
into jobs. Policy is code; it mirrors `subagent-driven-development` with the extras:

1. **Stale check** by `tmux-ctl registry stale`; a `refresh` job when stale.
2. **Per task, in the plan's order:** an `implement` job on the task's tier, its brief built from the task's text
   and the report contract. Consecutive small same-shape tasks are not merged into one job in this stage.
3. **Green check by the engine, not by an agent:** it runs the task's `verifyCommand` in the worktree (and
   `agent-ci check` where `.agent-ci.yml` exists). Red: the output goes back to the implementer as a bounce, at
   most two; the third red is an escalation.
4. **Review:** a `review` job at the standard tier with a review package for the task's commit range and the
   task's brief and report. Consecutive green `mechanical` tasks are reviewed as one batch (up to 5; never a task
   whose files touch security, migrations, CI or shared configuration), with a verdict per task.
5. **Fix loop:** `critical` and `important` findings become a `fix` job. Fix rounds 1 to 3 resume the
   implementer's own session (`claude --resume`) when it can be resumed, else a fresh worker gets the brief,
   the report and the findings. Each fix is green-checked and re-reviewed (a small fix on a mechanical task by
   the mechanical tier's model, as the extras define small). At most 5 rounds, then an escalation. `minor`
   findings are logged as deferred.
6. **Final review** of the whole branch on the frontier tier, pointed at the deferred and parked events; one
   `fix wave` job for all its findings; one `re-review`. Residual findings are an escalation.
7. **Integrate:** the project's test command (`docs/superpowers/engine.json`, `{"test": "<command>"}`; in this
   repo `zsh tools/tests/all.zsh`; without the file, every task's `verifyCommand` in order) before the merge, the stored integration answer (`merge`, `mr`, `keep`),
   the tests after it on the merged result, the ledger archive (`docs/superpowers/ledgers/<plan-basename>/progress.md`
   rendered from the events, same line forms as today so `metrics record` reads it), `metrics record`, worktree
   cleanup. The live-checkout checks of Queue mode apply: no merge while another session is mid-change there.
   The engine never pushes without stored consent and never to `main` or `master`.

#### 4. The architect job

- A fresh session on the frontier tier, given a case file only: the task or finding text, the relevant report
  and review, the spec's Decisions section, and the spec's events so far.
- Cases, and nothing else: fix rounds exhausted; an implementer reporting `blocked`; a verify command red after
  two bounces; residual findings after the re-review; tests red after the merge; a job that failed twice.
- Decisions: `proceed` (go on as if passed, with the finding parked), `retry_higher_tier` (re-run the job one
  tier up, once per job), `park`, `fail_spec`. Each is stored as a `ruling` event with what it costs if wrong.
- Not an architect case: anything destructive, a push to a shared branch, a security-sensitive action, a side
  effect outside the worktree. Those fail the spec with the reason, as SDD's four stop classes do in Queue mode.
- Tests red after the merge with `fail_spec`: the engine reverts its own merge commit on `main` (a revert commit,
  never a reset) and keeps the branch.

#### 5. Commands (part 1)

| Command | Does |
| --- | --- |
| `tmux-ctl engine run <spec> --integration merge\|mr\|keep [--push] [--batch <id>]` | Runs one planned spec to its outcome in the foreground of the engine's window; prints one line per event. |
| `tmux-ctl engine status [<spec>]` | Specs and their states; with a spec, its jobs and last events. |
| `tmux-ctl engine events <spec>` | The spec's event log. |
| `tmux-ctl engine resume` | Continues every unfinished spec from the database (section 9). |

Part 1 is done when `engine run` takes one small real spec from a committed plan to a merged result on a scratch
clone, with no lead turn in between.

### Part 2: the queue runner

#### 6. Enqueue, split and run

- Queue mode, after the up-front answers and stage 2's up-front planning: the lead runs
  `tmux-ctl metrics batch start --config upfront-seq --config engine-c1 <specs>` (the metrics spec's assignment
  by hash, gated specs left out), then `tmux-ctl engine enqueue <spec> --runner lead|engine --integration … [--push]
  --batch <id>` for every spec in queue order, then `tmux-ctl engine start`.
- `engine start` runs the engine as a long-lived process in a window `engine` of the hidden `<project>-bg`
  session. It takes the specs in queue order, one at a time:
  - runner `engine`: `engine run` as in part 1;
  - runner `lead`: it types one line into the lead's window, `[Engine] your turn: <spec>`, and waits for
    `tmux-ctl engine done <spec> --outcome <outcome>`, which the lead runs after its usual finishing step.
- A spec with an entry gate is enqueued with `--gate <id>`; the engine runs `metrics gate` at its turn and, on
  any exit but 0, completes it as `failed — gate <id>: …`. Gated specs run under the lead.
- The lead ends its turn after `engine start`. Lines the engine types into the lead's window:
  `[Engine] your turn: <spec>`, `[Engine] queue finished: <report path>`, `[Engine] stopped: <reason>`. A lead
  rule says what each means; none asks the lead to judge a task.

#### 7. Morning report and metrics

- The engine writes `docs/superpowers/reports/YYYY-MM-DD-queue.md` itself when the last spec is done: per spec the
  outcome, branch or merge commit or MR URL, every ruling with its cost if wrong, permission prompts seen, user
  gates waiting; then the Metrics section and the `PCEE:` line (`metrics report`, `registry report`,
  `metrics status`); then the Sleep section and `tmux-ctl awake off`, as Queue mode step 5 does today. It commits
  the report on `main` path-scoped (or leaves it uncommitted when the live checkout is mid-change) and runs
  `tmux-ctl artifact`.
- The lead's part of the report: its own specs' rulings, which it appends when the engine's line arrives, and
  the Status table update.
- The engine stamps `metrics start` and `metrics record` for its specs. Records gain `control_tokens`: the
  lead's attributed tokens plus the spec's architect jobs (found by window name), and `control_share`.
- `docs/superpowers/metrics/configs/engine-c1.md`: `{"id": "engine-c1", "baseline": false, "targets":
  [{"metric": "tokens_per_task", "max": 1.0}, {"metric": "control_share", "max": 0.5}]}`. For a baseline record
  `control_share` is its `lead_share`.
- `docs/superpowers/metrics/gates/K2.md`: `{"id": "K2", "compare": "engine-c1"}`. By the decision rule K2 needs
  at least 8 engine specs over at least 2 batches, so it is judged after two or three queues.
- The comparison baseline is every configuration flagged `"baseline": true`. If the user adopts `upfront-seq`
  after K1, they flip its flag; this spec does not.

#### 8. Lead rules

Queue mode in `claude/orchestrator.md` (carrying the user's uncommitted edit as its own rule says): enqueue and
start (section 6); what the three `[Engine]` lines mean; `engine done` after a lead-run spec; the lead no longer
writes the morning report when an engine runs the queue. With `TC_ENGINE=0`, or when `engine start` fails, Queue
mode runs as before this stage.

### Both parts

#### 9. Recovery

- A restarted engine (`engine resume`, or `engine start` finding unfinished specs) continues from the database.
  A job marked `running` whose window still exists is watched again; one whose window is gone is finished from
  its report when that is valid, else run again as a new attempt.
- The engine process holds a lock file with its pid; a second `engine start` for the same project refuses.
- Handoffs of the lead do not touch the engine: it is not the lead's child. The handoff doc's State of the work
  says `Engine: running` and lists `engine status`.
- The awake hold of Queue mode stays armed by the lead at queue start; the engine turns it off after the report.

## Error handling

- On an internal error (an exception, a database it cannot write, a git command failing outside a job) the
  engine stops dispatching, records an `engine_error` event, types `[Engine] stopped: <reason>` into the lead's
  window, and leaves the database, worktrees and windows as they are. `engine resume` continues.
- A report with a missing or malformed status block counts as no report (section 2).
- A plan without a `.tasks.json`, or a task without a `verifyCommand`: the spec is not run by the engine; it is
  handed to the lead (`[Engine] your turn: <spec>`) and recorded as lead-run.
- A model limit error in a worker's pane (the Fable limit): the job is run again on Opus, once, with an event
  saying so.
- A usage limit reached (a worker's pane shows the limit message, or the status-line tap reads 100% for the
  5-hour or 7-day window): the engine stops dispatching, types `[Engine] stopped: usage limit`, and continues on
  `engine resume`. Pacing against the limit is stage 6.
- Nothing in the engine answers a permission prompt.

## Testing

- **Compiler and transitions:** unit tests with a fake worker (a script that writes a report and status block
  and exits) for every edge of section 3: bounce, third red, review pass, findings and fix rounds, round 5
  exhausted, batch review, final review with and without findings, each architect decision, each integration
  answer, tests red after the merge with the revert.
- **Finish detection:** fixture agent-status files for `ready` with and without a report, `needs-you` past
  10 minutes, a vanished window.
- **Crash and resume:** the engine killed (by pid) at each transition of a fake-worker run resumes to the same
  final state and event sequence, with no job run twice when its report was valid.
- **Isolation:** every test uses `TC_ENGINE_DIR` in a temporary directory and a scratch tmux server started with
  `-f /dev/null`; a leak check confirms the real engine directory and the real tmux server are untouched.
- **Queue runner (part 2):** a queue of three fixture specs (engine, lead, gated) with fake workers and a fake
  lead window: order, the three `[Engine]` lines, `engine done`, the gate failure, the report file's sections.
- **Real run, part 1:** one small real spec with a committed plan on a scratch clone of this repo, real workers,
  `--integration keep`: a merged-quality branch with every job's window opened and closed, and the event log,
  as the plan's e2e record.
- **Real run, part 2:** a user gate: the next real queue is split, and its morning report is the one the engine
  wrote.
- **Suites:** no new failures on the project's suites.

## Out of scope

- Concurrency above 1; locks and clusters; the merge queue and change packages; adaptive concurrency.
- The board as a view of engine state beyond `tmux-ctl engine status` (the tasks window keeps showing the
  lead's task list; the lead mirrors the queue's `Plan & run:` tasks from the `[Engine]` lines).
- Engine-run planning: plans and the cross-plan pass stay with stage 2's planners under the lead.
- Batching several small tasks into one implement job.
