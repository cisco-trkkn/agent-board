# PCEE stage 3: execution state, scheduler and worker pool at concurrency 1

Date: 2026-11-10 · Stage 3 of `docs/superpowers/specs/2026-11-10-pcee-decomposition.md` · Gate: K2
Entry gate: K1
Related: `docs/superpowers/specs/2026-11-10-queue-metrics-design.md` (run log, decision rule, gates),
`docs/superpowers/specs/2026-11-10-pcee-registry-design.md` (manifests, up-front plans, entry gates),
`claude/orchestrator.md` (Queue mode), `claude/worker.md`, `claude/skills/subagent-driven-development-extras/SKILL.md`;
`engine/` layout, install and the `metrics append|has` commands: registry spec section 8

## Revised 2026-11-19

The user decided on Discord, 2026-11-19 (this block and the sections it names are the only changes to this spec; text
marked "moved to stage 7" stays in place as the design to carry):

1. "Metrics: the built Python metrics stays in agent-board; porting to Node comes later." Stage 1 is built and merged.
2. "The engine is Node.js in a new `engine/` folder of this repo, next to `tools/discord-bridge/`." Telegram is gone.
3. Spec order: this revision, then "remote means Discord-only", then phone escalation.
4. "One engine process per queue, started in the project's `-bg` window when a queue starts. A localhost API comes
   later, when Discord needs it."
5. "Stage 3 scope: the core plus durable execution, the inbox and parking (sections 10-12). Approval holds (13) and
   schedules (14) move to stage 7."
6. "Strategy = a pure function `(state, event) -> [commands]` that holds no state. Backend = an event source with
   `start / close / resume`; tmux windows of agent-board first, the Agent SDK later. Tests use a fake backend."
7. Planning stays with the lead; the engine takes it at stage 5.
8. "The spec-driven strategy covers the job graph. Integrate (merge, revert, ledger, `metrics record`), the architect
   pass, budgets and state are engine core, shared by every strategy."
9. "`tmux-ctl registry …` and `tmux-ctl engine …` wrap Node the way `tmux-ctl metrics` wraps Python."
10. "runs.jsonl has one writer": `board/metrics.py`, with a file lock (registry spec section 8). The engine never
    opens the file: it calls `tmux-ctl metrics append|has|start|record|gate`.
11. "SQLite: Node's built-in `node:sqlite`, `engines: node >= 22.13`."
12. "`engine/` has its own `package.json` and `node --test` suite; `install.sh` runs `npm ci` for it, and Node becomes a
    required dependency" (the registry spec's section 8 ships the package, the install step and the INSTALL.md wording).
13. "Discord in stage 3 goes only through the existing file contracts (feed JSONL out, inbox rows in, written by the
    board's Python controls)." The "remote means Discord-only" spec redesigns that next.
14. "The engine-hold hook calls `node engine/bin/hold.js`. It moves with holds to stage 7."

## Revised 2026-11-19 (2): the second backend is the Claude Agent SDK

The user decided on Discord, 2026-11-19 ("Amend the spec", after "Should pcee use claude sdk and not implement claude
headless"):

15. The backend after `claude-tmux` is the **Claude Agent SDK (TypeScript)**, run in the engine's Node process. The engine
    does not drive `claude -p` (headless CLI) itself, and no backend parses `--output-format stream-json`. Reasons:
    the SDK's `canUseTool` callback hands every permission request and question to the engine, which can route it
    to Discord and wait, where `-p` has only static allow/deny rules; typed messages (tool calls, results, cost,
    session id) replace pane and agent-status parsing; resume, interrupt, max turns and budgets are first-class.
16. Stage 3 is unchanged: it ships `claude-tmux` and the `fake` backend. The `claude-sdk` backend is decomposition stage 8,
    planned after stage 3 passes K2. It implements the same `start / close / resume` interface and event types
    (`started`, `status`, `report`, `gone`), so the engine core and strategies do not change.
17. Stage 8 starts with a spike whose results gate the build: (a) whether SDK runs bill against the user's Claude
    subscription like the CLI or need an API key; (b) that a job loads the same setup as a CLI worker (settings,
    plugins, the superpowers and extras skills, the agent-board mods and hooks, the model-routing gates); (c) that
    `canUseTool` reaches Discord and returns an answer, including AskUserQuestion. If (a) or (b) fails, the user
    decides before the build continues.
18. With the SDK backend, approval holds (section 13, stage 7) answer through `canUseTool` instead of a deny and a
    later retry under a one-time pass; the hook design stays for `claude-tmux` jobs.
19. (Same day, third revision.) A project owner sits above the engine (decomposition stage 10); the engine and the
    architect pass do not change in this stage. Until stage 10 the lead plays the owner: an architect decision that
    would need a push, a protected path or spend far over the estimate is an `escalate`, never a ruling.

## Revised 2026-11-20: efficiency (E2-E4; user, Discord 15:04Z)

Source: `docs/superpowers/notes/2026-11-20-efficiency-learnings-for-pcee.md`; the reader and probes are built by
`2026-11-20-efficiency-now-design.md`. Each change is made in place and marked `(E<n>, 2026-11-20)`.

- **E2.** The bounce text is short and measured (section 3, step 3).
- **E3.** A job's end event carries its final context size and the limits reading (section 1, `jobs`).
- **E4.** Applied (docs/superpowers/notes/2026-11-20-worker-context-probe.md): each job kind has a tools/mcp list, allow-all by default (section 3, step 2).

## Revised 2026-11-23: typed ask and per-spec budget (F1, F2; user, Discord 21:39Z)

Source: the ideas regroup, group F (from the Archon study, `docs/superpowers/notes/2026-11-20-archon-insights-for-pcee.md`).
Both are Part 2 work, specified in sections 8a and 8b; section 10.3's `waits` row gains the two columns of 8a.

- **F1.** Every parked question is typed and carries a recommendation; metrics count how often the user follows it (8a).
- **F2.** Each spec has an attempts and tokens budget in the engine core; unmeasurable cost parks the spec (8b).

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
  an **architect job** for a fixed list of escalation cases. (Revised 2026-11-19) The engine is a Node.js program in
  `engine/`, **one process per queue**, built behind two interfaces from the start: the **strategy** (a pure function
  `(state, event) -> [commands]`, holding no state; today's review policy is the `spec-driven` strategy) and the
  **backend** (an event source with `start`, `close`, `resume`; tmux windows of agent-board first, the Agent SDK later).
  State, integrate, the architect pass and budgets are **engine core**, shared by every strategy. SQLite is
  `node:sqlite` (`engines: node >= 22.13`).
- **Split queues** until K2 is decided: half the specs under the lead, half under the engine, assigned by code,
  one spec at a time.
- **One spec, two plans in sequence:** part 1 `engine run <spec>` (one spec end to end), part 2 the queue runner.
- **Durable execution, Temporal-shaped, in our own code** (user, 2026-11-13; sections 10 and 11): heartbeat and
  progress timeouts, retry policies as data, durable waits (`awaiting_you` parking, signals, timers), an
  intent/result journal for every side effect, a policy version per spec, and a replay check of the event log. No
  Temporal server or SDK: the same SQLite file, Node's standard library only (`node:sqlite`), Temporal's names and shapes so a later move
  to Temporal (stage 4 or 5) is a mapping, not a redesign.
- **Park, don't fail** (user, 2026-11-13): a case the engine may not decide alone parks the spec as `awaiting_you`
  and the queue moves on; an answered parked spec resumes before the next queued spec; still unanswered at the end
  of the queue, it fails as before.
- **Control tokens** (the lead plus architect jobs) are counted together, so judgment moved into a job does not
  flatter the lead share.
- Concurrency stays 1. No locks, no merge queue, no change packages (stages 4 and 5).
- **Always-on shape** (user, 2026-11-16, from Anthropic's "Building always-on agents"; sections 12 to 14): one
  durable **inbox** that every wake-up source writes to and only the engine drains; **approval holds** that deny a
  stop-class tool call in a worker, park the spec, and resume the worker's session with a one-time pass when the
  user approves; **schedules** as rows in `timers`, fired by one launchd heartbeat (`engine wake`). The engine stays
  a queue runner, not a process that runs all the time. (Revised 2026-11-19) Of these, the inbox (section 12) is in
  this stage; **approval holds (13) and schedules (14) are moved to stage 7** and are not built or tested here.

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
  transaction that also appends its event. Opened with `node:sqlite` (`DatabaseSync`). The engine writes no other
  durable file of its own: it never opens `runs.jsonl` (it calls `tmux-ctl metrics …`, registry spec section 8).
- Tables:
  - `specs`: spec id, queue position, runner (`lead` or `engine`), integration answer and push consent, batch id,
    state, outcome, worktree, branch, plan path, `strategy` (default `spec-driven`) and `backend` (default
    `claude-tmux`). Of the common contract's six fields (intent, strategy, constraints, ownership, verification,
    lifecycle) these columns and the existing ones carry: intent = the spec and plan path, strategy, constraints =
    integration answer, push consent and limits, ownership = runner, verification = the tasks' `verifyCommand`s,
    lifecycle = state.
  - `jobs`: id, spec, kind, task number, tier, model, effort, state, attempt, brief path, report path, window and
    pane, base and head commits, start and end times.
    (E3, 2026-11-20) The job's end event writes in its `detail` `context_tokens` (the job's final context, from the
    shared reader `board/ctxsize.py` that `2026-11-20-efficiency-now-design.md` §2 builds) and the limits reading
    when one exists. Without one, the field is null with a missing reason naming the cause, the rule of that
    spec's §3.
  - `events`: append-only: time, spec, job, kind, detail. This is the ledger; `Ruling:` lines are events of kind
    `ruling`.
  - `steps`, `timers`, `waits`, `retry_policies`: section 10; `inbox`: section 12; `holds`: section 13 (moved to
    stage 7; no table in this stage).
  - `specs` also stores `policy_version` and `policy_hash` (section 10.5).
- Spec states: `queued`, `planning`, `running`, `final_review`, `integrating`, `awaiting_you`, `done`. Job states:
  `pending`, `running`, `backoff`, `done`, `failed`, `escalated`.
- Every event that changes a row carries that row's new values in `detail` (JSON), so the tables can be rebuilt from
  the events alone (section 10.6).
- Briefs, reports and review packages are files under the spec's git-ignored workspace
  (`<worktree>/.superpowers/engine/`), as SDD's are today.

#### 2. Workers

- **Backend interface (revised 2026-11-19).** The engine talks to workers only through a backend: an object with
  `start(job) -> handle`, `close(handle)` and `resume(handle, text)`, and an event source that emits
  `{handle, type}` events: `started`, `status` (a state change such as `busy`, `ready`, `needs-you`, with its
  timestamps), `report` (a report file appeared) and `gone` (the window or process ended). The engine never reads
  tmux, agent-status files or panes itself. This stage ships the `claude-tmux` backend, described by the rest of this
  section; a `fake` backend (scripted events, no process) serves the tests. The Agent SDK backend (`claude-sdk`,
  stage 8, revision decisions 15-18) and a second tool backend come later and need an adapter only.
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
- **Finish detection.** The `claude-tmux` backend reads the agent-status file whose `pane` is the worker's pane (the
  mod already writes it) and emits it as `status` events. State `ready` with a valid report: the job is done and the engine kills that window by the
  pane id it started. `ready` with no valid report: one line typed with `tmux-ctl tell` naming the report path;
  a second `ready` without it fails the attempt. A window that is gone without a report fails the attempt.
- **Waiting on the user.** A worker in `needs-you` is left alone (the board shows it) and every timeout clock of
  its job stops. After 10 minutes the spec parks as `awaiting_you` (section 10.3) with the question
  `permission prompt in <window>`; the window stays open, and a worker that goes busy again (the user answered the
  prompt in the window) un-parks the spec without a signal.
- A failed attempt is retried by its job kind's retry policy (section 10.2); the default is one retry with a fresh
  worker, then an architect job.
- **Liveness and progress** of a running job are watched through the same agent-status file (section 10.1).

#### 3. The job graph and its policy

`engine run <spec>` takes a spec whose plan and manifest exist (stage 2) and compiles the plan's `.tasks.json`
into jobs. Policy is code; it mirrors `subagent-driven-development` with the extras.

**Revised 2026-11-19: this policy is the `spec-driven` strategy.** A strategy is a pure function
`(state, event) -> [commands]` that holds no state: `state` is a snapshot of one spec's rows, `event` one row of
`events` (a job `done`, a green check result, a review verdict, a timer), and the commands are `start_job`,
`run_check`, `record_ruling`, `park`, `escalate(case)`, `set_state` and `request_integrate`. The engine core applies
the commands in one transaction with their events. Steps 1 to 6 below are the strategy. Step 7 (integrate), the
architect pass of section 4, retry policies (10.2) and budgets are **engine core**, shared by every strategy: a strategy
asks for them (`request_integrate`, `escalate`) and receives their results as events. Other strategies (stage 9) plug in
the same way; this stage ships only `spec-driven`. Strategy tests feed events and compare commands; no process runs.

The steps:

1. **Stale check** by `tmux-ctl registry stale`; a `refresh` job when stale.
2. **Per task, in the plan's order:** an `implement` job on the task's tier, its brief built from the task's text
   and the report contract. Consecutive small same-shape tasks are not merged into one job in this stage.
   (E4, 2026-11-20) The job table has a per-kind `tools`/`mcp` column, allow-all by default. The probe found MCP tool
   schemas are 24.3% of one fresh Sonnet teammate's used context (7.9k of 32.5k tokens), above the 5% line; this uses
   the plan's reading of the denominator (used context), and the 1M-window reading (0.8%) would make it a no-go
   (`docs/superpowers/notes/2026-11-20-worker-context-probe.md`).
3. **Green check by the engine, not by an agent:** it runs the task's `verifyCommand` in the worktree (and
   `agent-ci check` where `.agent-ci.yml` exists). Red: the output goes back to the implementer as a bounce, at
   most two; the third red is an escalation. (E2, 2026-11-20) The bounce text is the failing test names, their error
   lines and the runner's summary line, plus the path of the full log, not the whole output. A cap in lines comes
   from a constant in the strategy file. The bounce event's `detail` gains `bounce_bytes` (the size of the text sent),
   so the cap can be measured.
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
7. **Integrate (engine core, requested by the strategy):** the project's test command (`docs/superpowers/engine.json`, `{"test": "<command>"}`; in this
   repo `zsh tools/tests/all.zsh`; without the file, every task's `verifyCommand` in order) before the merge, the stored integration answer (`merge`, `mr`, `keep`),
   the tests after it on the merged result, the ledger archive (`docs/superpowers/ledgers/<plan-basename>/progress.md`
   rendered from the events, same line forms as today so `metrics record` reads it), `metrics record`, worktree
   cleanup. `metrics start` and `metrics record` run as `tmux-ctl metrics …` (Python). The live-checkout checks of
   Queue mode apply: no merge while another session is mid-change there. The engine never pushes without stored
   consent and never to `main` or `master`.

#### 4. The architect job

- Engine core (revised 2026-11-19): a strategy returns `escalate(case)`; the engine runs the architect job and feeds
  its decision back as an event, whatever the strategy.
- A fresh session on the frontier tier, given a case file only: the task or finding text, the relevant report
  and review, the spec's Decisions section, and the spec's events so far.
- Cases, and nothing else: fix rounds exhausted; an implementer reporting `blocked`; a verify command red after
  two bounces; residual findings after the re-review; tests red after the merge; a job that failed twice.
- Decisions: `proceed` (go on as if passed, with the finding parked), `retry_higher_tier` (re-run the job one
  tier up, once per job), `park` (the spec goes to `awaiting_you` with the architect's ruling as the question),
  `fail_spec`. Each is stored as a `ruling` event with what it costs if wrong.
- Not an architect case: anything destructive, a push to a shared branch, a security-sensitive action, a side
  effect outside the worktree. Those park the spec as `awaiting_you` (section 10.3) with the reason as the
  question, instead of failing it; unanswered at the end of the queue, they fail as SDD's four stop classes do in
  Queue mode today.
- Tests red after the merge with `fail_spec`: the engine reverts its own merge commit on `main` (a revert commit,
  never a reset) and keeps the branch.

#### 5. Commands (part 1)

`tmux-ctl engine <sub>` is a zsh case in `bin/tmux-ctl` that runs `node engine/bin/engine.js "$@"`, as `metrics)` runs
`python3 -I board/metrics.py` (revised 2026-11-19). Exit codes are the ones stated here.

| Command | Does |
| --- | --- |
| `tmux-ctl engine run <spec> --integration merge\|mr\|keep [--push] [--batch <id>]` | Runs one planned spec to its outcome in the foreground of the engine's window; prints one line per event. |
| `tmux-ctl engine status [<spec>]` | Specs and their states; with a spec, its jobs and last events. |
| `tmux-ctl engine events <spec>` | The spec's event log. |
| `tmux-ctl engine resume` | Continues every unfinished spec from the database (section 9). |
| `tmux-ctl engine status --waiting` | Specs in `awaiting_you`: question, options, asked at, and the command to answer. |
| `tmux-ctl engine signal <spec> approve\|deny\|fail [--note "<text>"]` | Answers a parked spec (section 10.3). |
| `tmux-ctl engine rebuild --check\|--apply` | Replays the events into a scratch database and diffs it with the live tables; `--apply` repairs the tables from the events (section 10.6). |

Part 1 is done when `engine run` takes one small real spec from a committed plan to a merged result on a scratch
clone, with no lead turn in between.

### Part 2: the queue runner

#### 6. Enqueue, split and run

- Queue mode, after the up-front answers and stage 2's up-front planning: the lead runs
  `tmux-ctl metrics batch start --config upfront-seq --config engine-c1 <specs>` (the metrics spec's assignment
  by hash, gated specs left out), then `tmux-ctl engine enqueue <spec> --runner lead|engine --integration … [--push]
  --batch <id>` for every spec in queue order, then `tmux-ctl engine start`.
- `engine start` runs the engine as one Node process per queue, in a window `engine` of the hidden `<project>-bg`
  session; it exits after the morning report, and `engine start` is how the next queue starts it again. It has no
  network listener in this stage: a localhost API comes later, when Discord needs it (revised 2026-11-19). It takes
  the specs in queue order, one at a time:
  - runner `engine`: `engine run` as in part 1;
  - runner `lead`: it types one line into the lead's window, `[Engine] your turn: <spec>`, and waits for
    `tmux-ctl engine done <spec> --outcome <outcome>`, which the lead runs after its usual finishing step.
- A spec with an entry gate is enqueued with `--gate <id>`; the engine runs `metrics gate` at its turn and, on
  any exit but 0, completes it as `failed — gate <id>: …`. Gated specs run under the lead.
- The lead ends its turn after `engine start`. Lines the engine types into the lead's window:
  `[Engine] your turn: <spec>`, `[Engine] queue finished: <report path>`, `[Engine] stopped: <reason>`,
  `[Engine] paused: usage limit until <time>`, `[Engine] awaiting you: <spec>: <question>` (section 10.3; the lead
  relays it to the user when remote and never answers it itself). A lead rule says what each means; none asks the
  lead to judge a task.

#### 7. Morning report and metrics

- The engine writes `docs/superpowers/reports/YYYY-MM-DD-queue.md` itself when the last spec is done: per spec the
  outcome, branch or merge commit or MR URL, every ruling with its cost if wrong, permission prompts seen, user
  gates waiting; then the Metrics section and the `PCEE:` line (`metrics report`, `registry report`,
  `metrics status`); then the Sleep section and `tmux-ctl awake off`, as Queue mode step 5 does today. It commits
  the report on `main` path-scoped (or leaves it uncommitted when the live checkout is mid-change) and runs
  `tmux-ctl artifact`.
- The lead's part of the report: its own specs' rulings, which it appends when the engine's line arrives, and
  the Status table update.
- The engine stamps `metrics start` and `metrics record` for its specs by running `tmux-ctl metrics start|record`.
  Records gain `control_tokens`: the lead's attributed tokens plus the spec's architect jobs (found by window name),
  and `control_share`; `metrics record` (Python) computes both from the usage index (revised 2026-11-19).
- `docs/superpowers/metrics/configs/engine-c1.md`: `{"id": "engine-c1", "baseline": false, "targets":
  [{"metric": "tokens_per_task", "max": 1.0}, {"metric": "control_share", "max": 0.5}]}`. For a baseline record
  `control_share` is its `lead_share`.
- `docs/superpowers/metrics/gates/K2.md`: `{"id": "K2", "compare": "engine-c1"}`. By the decision rule K2 needs
  at least 8 engine specs over at least 2 batches, so it is judged after two or three queues.
- The comparison baseline is every configuration flagged `"baseline": true`. If the user adopts `upfront-seq`
  after K1, they flip its flag; this spec does not.

#### 8. Lead rules

Queue mode in `claude/orchestrator.md` (carrying the user's uncommitted edit as its own rule says): enqueue and
start (section 6); what the five `[Engine]` lines mean; `engine done` after a lead-run spec; the lead no longer
writes the morning report when an engine runs the queue. With `TC_ENGINE=0`, or when `engine start` fails, Queue
mode runs as before this stage.

#### 8a. Typed ask (Part 2; F1, 2026-11-23)

- `waits` gains `kind` and `recommendation`. `kind` is one of `stop_class`, `needs_you`, `architect_park`,
  `policy_change`, `cannot_tell`, `user_gate`, `budget` (the parking causes of 10.3, plus 8b).
  `recommendation` is JSON `{"option": <one of the wait's options>, "why": <one line>, "confidence": "low|medium|high"}`.
  Writing a wait without both is an error: `db.put` of a `waits` row checks them.
- Source: the architect job's `park` decision carries the recommendation (its report's `json:status` gains
  `recommend`, same shape; a report without it fails parse like any malformed report). Every other kind takes a fixed
  default from `policy.js` `ASK_DEFAULTS`: `cannot_tell` → approve, "the check cannot see the side effect; it most
  likely ran", low; `policy_change` → approve, "the new policy was set by the user", medium; `needs_you` → approve,
  "the worker is waiting on a prompt it raised", low; `stop_class` → deny, "an irreversible step needs your yes", medium;
  `user_gate` → approve, "the plan marks this task as yours to check", low; `budget` → see 8b. The defaults are
  part of the policy hash (10.5).
- Shown first: `engine status --waiting`, the `decision` feed line and the Discord post lead with
  `I recommend: <option> (<confidence>): <why>`, then the question and the signal commands.
- On an answer the `ruling` event records `kind`, `recommended`, `answer` and `followed` (answer == recommended
  option). The engine appends one `ask` record per answer through `tmux-ctl metrics append ask --json …`
  (`{spec, batch, kind, recommended, confidence, answer, followed, asked_at, answered_at}`; `board/metrics.py` gains
  the `ask` kind). The morning report's Metrics section gains `asks: <n>, followed <k> (<pct>%)` overall and per kind.

#### 8b. Per-spec budget (Part 2; F2, 2026-11-23)

- Budget per spec: `attempts` (job attempts of every kind, default 60) and `tokens` (default 5000000), from
  `docs/superpowers/engine.json` `"budget": {"attempts": N, "tokens": N}`, overridden per spec by
  `engine run|enqueue --budget-attempts N --budget-tokens N`. Stored on the `specs` row (`budget_attempts`,
  `budget_tokens`) with the spend counters `spent_attempts`, `spent_tokens`.
- Before each dispatch the core writes a `budget_reserve` event (intent: job id, attempt) in the same transaction
  that increments `spent_attempts`, then dispatches. At job end it reads the job's tokens (input + output + cache
  creation, from the worker transcript's usage rows for that job; the claude-tmux backend reports them, the fake
  backend takes them from its script) and adds them to `spent_tokens` in the transaction that records the job's end.
- A finished job whose tokens cannot be measured (no transcript, no usage rows) parks the spec: kind `budget`,
  question `cost unknown for job <id>`, recommendation approve / "count it as unknown and go on" / low. On approve
  the job's tokens are recorded as `null` and the spec's report marks its spend as a lower bound.
- Reaching either cap before a dispatch parks the spec: kind `budget`, question
  `budget reached: <attempts a/A, tokens t/T>`, options `approve|fail`, recommendation approve / "extend by 50%" /
  medium when the spec's last three tasks completed without a fix round, else fail / "the spec is looping" / medium.
  Approve raises the reached cap(s) by 50% and dispatches.
- `engine status <spec>` shows `attempts a/A · tokens t/T`. `metrics record` stores both in the record.
- Resume (section 9): a `budget_reserve` with no matching dispatch is reconciled like any intent step (10.4): the
  job is dispatched (the attempt stays counted), never counted twice.

#### Testing additions (8a, 8b)

Each parking site writes a kind and a recommendation (a missing one is a thrown error, tested); the architect
report without `recommend` is malformed; `followed` true and false recorded and the `ask` metrics line written;
a fake backend with fixed token counts reaches the token cap and parks with the right recommendation; approve
extends by 50%; unmeasurable usage parks; a kill between `budget_reserve` and dispatch resumes to one dispatch and one
counted attempt.

### Both parts

#### 9. Recovery

- A restarted engine (`engine resume`, or `engine start` finding unfinished specs) continues from the database.
  In order: every `steps` row left at `intent` is reconciled by its check (section 10.4); timers already due fire
  once each, oldest first; the inbox is drained (section 12); each spec's policy version is compared (section 10.5).
  Then a job marked `running` whose window still exists is watched again; one whose window is gone is finished
  from its report when that is valid, else run again as a new attempt under its retry policy.
- The engine process holds a lock file with its pid; a second `engine start` for the same project refuses.
- Handoffs of the lead do not touch the engine: it is not the lead's child. The handoff doc's State of the work
  says `Engine: running` and lists `engine status`.
- The awake hold of Queue mode stays armed by the lead at queue start; the engine turns it off after the report.

#### 10. Durable execution (Part 1)

Added 2026-11-13 from a brainstorm on Temporal's ideas (the user chose: amend this spec before it runs; a small
layer in our own code, not a Temporal server). Names follow Temporal's: a job is an activity, a spec run is a
workflow, a user answer is a signal.

The engine loop, one tick every 5 seconds: move due timers and worker status changes into the inbox → drain
the inbox (section 12) → check running jobs'
heartbeats and timeouts → advance each spec's state → dispatch the next job. Every step of the tick is one
transaction with its event, as section 1 requires.

##### 10.1 Heartbeat and progress timeouts

The heartbeat is the backend's `status` events; for `claude-tmux` they come from the worker pane's agent-status file
(the mod writes `updatedAt` every few seconds while the process lives, and `state`, `tool`, `lastToolAt`,
`turnStartedAt`), and the fields below are read from the latest event (revised 2026-11-19). Per running job, each tick:

| Timeout | Fires when | Then |
| --- | --- | --- |
| heartbeat (2 min) | `updatedAt` older than 2 min, or no status file for the pane 2 min after start | the attempt fails (`heartbeat_timeout`) |
| no progress (15 min) | `state` busy, `tool` null, and `max(lastToolAt, turnStartedAt)` older than 15 min | one `tmux-ctl tell` nudge naming the report path; still true 5 min later: the attempt fails (`no_progress`) |
| tool (limit + 5 min) | one tool running longer than its own limit plus 5 min (Bash: 10 min, so 15 min; other tools: 15 min) | the attempt fails (`tool_timeout`) |
| job (per kind) | the job's wall time exceeds its policy's `timeout_min` | the attempt fails (`job_timeout`) |

- A job in `needs-you` stops every clock above (its time there is subtracted); after 10 minutes it parks (section 2).
- Deadlines are rows in `timers` (kind `deadline`), so a restart keeps them; a deadline that passed while the engine
  was down fires once on resume, after the heartbeat is re-read (a live, progressing worker cancels it).
- A failed attempt's window is closed by the pane id the engine started (a `steps` row, kind `close_window`); the
  pane's last 200 lines are saved to `<workspace>/logs/<job>-<attempt>.log` first.

##### 10.2 Retry policies

`retry_policies` has one row per job kind: `kind`, `max_attempts`, `backoff_s` (a list, one per retry), `timeout_min`,
`no_retry_on` (a list of failure reasons), `on_exhausted` (`architect`, `park` or `fail_spec`). Loaded at engine
start from `docs/superpowers/engine.json` key `retry` (`{"<kind>": {…}}`), each key overriding the defaults:

| kind | max_attempts | backoff_s | timeout_min | no_retry_on | on_exhausted |
| --- | --- | --- | --- | --- | --- |
| implement, fix, refresh | 2 | 30 | 90 | blocked, usage_limit | architect |
| review | 2 | 30 | 45 | usage_limit | architect |
| final_review | 2 | 60 | 90 | usage_limit | architect |
| architect | 2 | 60 | 30 | usage_limit | park |
| bounce (red verifyCommand) | 3 | 0 | — | — | architect |
| fix_round | 5 | 0 | — | — | architect |

- The two-bounce and five-round rules of section 3 are the `bounce` and `fix_round` rows: a red verifyCommand is a
  failed `bounce` attempt; the third red exhausts it. Section 3's numbers are the defaults; the table is the source.
- `blocked` (an implementer's report) skips retries and goes straight to `on_exhausted`.
- `usage_limit` skips retries and sets a `usage_reset` timer (section 10.3).
- `model_limit` (the Fable limit in a pane) is retried once on Opus outside the count, as an event `model_fallback`.
- Between attempts the job sits in `backoff` with a `timers` row (kind `retry`).

##### 10.3 Durable waits: parking, signals, timers

- **`waits`:** `spec`, `step` (the state and job to resume at), `question`, `options` (default
  `approve|deny|fail`), `asked_at`, `answered_at`, `answer`, `note`. One open wait per spec.
- **Parking** sets the spec to `awaiting_you` and writes the wait, on: a stop-class case (section 4), a worker in
  `needs-you` for 10 minutes (section 2), an architect `park`, a policy-version change (10.5), a step check that
  cannot tell (10.4), and a plan task marked as a user gate. Under `engine run` (one spec) the engine waits for the
  answer; under the queue runner the queue moves on (section 11).
- **Signals:** `tmux-ctl engine signal <spec> approve|deny|fail [--note …]` writes an `inbox` row (source `user`, section 12) and exits; it
  refuses (exit 2, `no open wait for <spec>`) when the spec is not `awaiting_you`. The engine applies it on its
  next tick: `approve` resumes at the stored step (a stop-class step then runs); `deny` skips that step and goes on
  when the policy has a path without it (a skipped push, a skipped side effect), else fails the spec with
  `denied: <question>`; `fail` fails the spec with the note. Each answer is a `ruling` event (`by: user`).
- **Feed:** entering `awaiting_you` appends a `decision`-tier feed line (Addition below) with the question and the
  exact signal command; the answer appends a `progress` line.
- **`timers`:** `id`, `spec`, `job`, `kind` (`deadline`, `retry`, `usage_reset`), `due_at`, `payload`, `fired_at`.
  `usage_reset` is due at the reset time the status-line tap reports for the window that hit 100% (5-hour or
  7-day), else in one hour; when it fires the engine dispatches again. A usage limit no longer stops the engine
  (Error handling).

##### 10.4 Side effects: intent, result, check

Every action outside the database is a `steps` row: `key` (unique, e.g. `merge:<branch>@<base sha>`), `spec`,
`kind`, `state` (`intent`, `done`, `failed`), `result`, times. The engine writes `intent` (and commits), acts, then
writes `done` with the result. Kinds and their checks, run on resume for every row left at `intent`:

| kind | check: already done when |
| --- | --- |
| `start_worker` | a window named for the job exists in the session (then its pane id is adopted) |
| `close_window` | the pane is gone |
| `merge` | the branch head is an ancestor of the integration target |
| `revert`, `commit_report`, `commit_ledger` | a commit on the target carries the trailer `Engine-Step: <key>` |
| `metrics_start`, `metrics_record` | `tmux-ctl metrics has start --spec <id> --batch <id>` (or `has run`) exits 0 (the engine never opens `runs.jsonl`) |
| `push` | the remote ref equals the recorded local sha (`git ls-remote`) |
| `worktree_remove` | the worktree path is gone from `git worktree list` |

- Done: mark `done`, continue. Not done: run the action again. Check fails or is ambiguous (a remote unreachable):
  park with the question `could not tell whether <key> ran`.
- Every commit the engine makes carries `Engine-Step: <key>` as a trailer.

##### 10.5 Policy version

- `engine/lib/policy.js` holds `POLICY_VERSION` (an integer, raised whenever section 3's or 10's behaviour changes); `policy_hash`
  is the sha256 of the loaded `engine.json` (or of `{}` without the file). Both are stored on the spec when it
  starts running.
- On resume, a spec whose stored version or hash differs from the current one parks with the question
  `engine rules changed (<old>→<new>): continue under the new rules?` `approve` re-stamps it and continues; `deny`
  or `fail` fails it with `policy changed`.

##### 10.6 Replay check

- `engine rebuild --check` creates a scratch database, replays every event's `detail` into fresh tables in event
  order, and diffs every table except `events` with the live one; differences are printed and exit 1.
- `engine rebuild --apply` stops if the engine's lock is held, then replaces the live tables with the rebuilt ones
  (the old database is kept as `<project>.sqlite.bak-<epoch>`).

#### 11. Durable execution across the queue (Part 2)

- **Parked specs don't stop the queue.** The runner takes the next queued spec when the current one parks. After
  each spec reaches `done` (or parks), any parked spec whose wait has an answer resumes first, oldest answer first,
  before the next queued spec starts. Concurrency stays 1: one spec runs at a time.
- **End of queue:** a spec still `awaiting_you` when nothing else is runnable is completed as
  `failed — awaiting you: <question>`, but its wait, worktree and state are kept: `engine signal` on it later
  resumes it (`engine resume` picks it up), and its outcome is re-recorded then.
- **Morning report:** a section "Awaiting you" lists every such spec with its question and the exact signal
  command; the engine waits to write the report until no spec is runnable.
- **After a Mac restart** (adds to `docs/superpowers/specs/2026-11-10-restart-recovery-design.md`, queued before
  this spec): the board's restore action runs `tmux-ctl engine resume` for a restored project whose engine
  database has unfinished specs. When the board starts at login (that spec's opt-in LaunchAgent) and a project's
  engine database has unfinished specs from a queue that was running (`specs` not `done`, and the engine's last
  event is not `queue_finished`), the board creates the project's `<project>-bg` session if needed and runs
  `engine resume` there without restoring the lead or waiting for a click, then re-arms the awake hold
  (`tmux-ctl awake on --lid`) and shows it in the restore banner as `engine resumed`. This needs a logged-in user
  session, as any LaunchAgent does (FileVault). Where restart-recovery has not merged, this item is skipped and
  recorded as a `Ruling:`.

#### 12. The inbox (Part 1)

Added 2026-11-16 (Decisions, "Always-on shape"). Every wake-up reaches the engine as a row in one durable table; the
engine is its only reader. This replaces the `signals` table.

- **`inbox`:** `id`, `source` (`user`, `timer`, `worker`, `approval`, `schedule`), `source_id`, `spec`, `job`, `kind`,
  `payload` (JSON), `received_at`, `state` (`new`, `done`, `dropped`), `handled_at`. `(source, source_id)` is unique;
  writers use `INSERT OR IGNORE`, so a repeated event is one row.
- **Writers** insert one row and exit; none calls the engine or writes another table:
  - `user`: `tmux-ctl engine signal …` (`source_id` a fresh uuid) and the Discord controls' buttons (`source_id` the
    interaction id, so a double tap counts once). In stage 3 Discord reaches the engine only through the existing file
    contracts: the board's Python controls (`board/discord_controls.py`) run `tmux-ctl engine signal` for a button
    and never write the database (revised 2026-11-19; the "remote means Discord-only" spec redesigns this). Section 10.3's signal rules are unchanged; they now apply when the
    row is drained.
  - `timer`: the tick moves each due `timers` row in, `source_id` `<timer id>@<due_at>`.
  - `worker`: the tick reads each running job's agent-status file and inserts one row per change of `state`, or when
    the file goes stale or the window goes away, `source_id` `<pane>:<state>:<updatedAt>`. Sections 2 and 10.1 act on
    these rows instead of reading the files themselves.
  - `approval`: the hold hook (section 13; moved to stage 7, no writer in this stage).
  - `schedule`: `engine wake` (section 14; moved to stage 7, no writer in this stage).
- **Drain:** each tick, after the timer and worker rows are in, every `new` row is handled oldest first, each in one
  transaction that sets it `done` (or `dropped`, with the reason, when it no longer applies: an answer for a spec that
  is not waiting, a status change for a job already finished) and appends its event. Rows that arrive during a job wait
  for the next tick and are handled together; nothing interrupts a running job.
- Rows are written to `events` when drained (with their payload), so `rebuild --check` covers them; `new` rows survive a
  restart and are drained on resume.

#### 13. Approval holds (Part 1)

**Moved to stage 7 (revised 2026-11-19): not built or tested in this stage; the text below stays as the design to
carry.** The hook runs as `node engine/bin/hold.js`, not as a shell script.

Added 2026-11-16. Claude Code's `defer` decision for `PreToolUse` only works in `claude -p` with one tool call per turn
(hooks reference), and engine workers are visible interactive windows, so a held call is denied and later retried
under a one-time pass.

- **Hook:** `claude/hooks/engine-hold.sh` (a thin shell entry that runs `node engine/bin/hold.js`), a `PreToolUse` hook that does nothing unless `ENGINE_JOB` is set (the engine
  sets it, with `ENGINE_DIR`, for every worker it starts). It matches the call against `engine.json` key `holds`, a list
  of `{"tool": "<name>", "pattern": "<regex on the command or path>", "outside_worktree": true|false}`. Defaults: Bash
  `git push`; Bash `git reset --hard`, `git branch -D`, `git clean`; Bash `rm -r…` on a path outside the worktree;
  Write or Edit on a path outside the worktree; Bash `glab mr merge` / `gh pr merge`.
- **No pass:** the hook inserts an `approval` inbox row (`source_id` the hold id, a fresh uuid; payload: tool name,
  input, the job, the worker's session id from its agent-status file) and returns `deny` with the reason
  `held for approval <hold id>: report status blocked with the concern "awaiting approval <hold id>", then stop`.
- **Engine:** drains the row, closes the window once the report is written (or on the next `ready`), sets the job to
  `escalated`, and parks the spec (section 10.3) with the exact call as the question and options `approve|deny|fail`.
  The feed's `decision` line carries the call, so the Discord card shows exactly what will run.
- **Approve:** the engine writes a `holds` row (`hold_id`, `job`, `call_hash` = sha256 of the tool name and its
  canonical JSON input, `expires_at` = now + 1 h, `used_at`), then resumes the worker's session with
  `claude --resume <session id>` in a new window for the job, typing `approval <hold id> granted: retry the held call
  exactly as before`. The hook finds an unused, unexpired pass whose hash matches, sets `used_at` and returns `allow`.
  Any other call, or the same call a second time, is held again.
- **Deny:** the session is resumed with `denied: <note>. Continue without it, or report blocked.`; `fail` fails the
  spec as section 10.3 says.
- **Session not resumable** (no session id, or `--resume` exits): a fresh worker gets the brief, the report and the
  answer (for `approve` the pass still applies, as it is bound to the call, not the session).
- Prompts the hook does not catch keep section 2's rule: a worker in `needs-you` for 10 minutes parks the spec.
- The hook never answers a permission prompt and never allows a call it did not hold.

#### 14. Schedules (Part 2)

**Moved to stage 7 (revised 2026-11-19): not built or tested in this stage; the text below stays as the design to
carry.**

Added 2026-11-16. Recurring jobs live in the engine's `timers` table and are fired by one launchd heartbeat; the
engine still runs only for a queue or a short pass.

- **Rows:** `timers` kind `schedule`, payload `{"name", "command", "rule", "skip_if_weekly_usage"}`. Rules:
  `daily HH:MM`, `weekly <Mon…Sun> HH:MM`, `every <n>m` (local time). `skip_if_weekly_usage` (default 85) skips the run
  when the weekly usage the status-line tap reports is at or over it, logged as a `schedule_skipped` event.
- **Commands:** `tmux-ctl engine schedule add <name> --rule "<rule>" -- <command…>`, `schedule list`,
  `schedule rm <name>`, `schedule run-now <name>`.
- **Heartbeat:** launchd `com.user.agent-board-engine-wake` runs `tmux-ctl engine wake` every 15 minutes
  (`StartInterval` 900) and at load (after sleep or login). For every project with an engine database: each due
  schedule row is moved to its next future occurrence (missed occurrences collapse into one run) and an inbox row is
  inserted (`source` `schedule`, `source_id` `<name>@<due_at>`). A timer never runs a job by itself.
- **Who runs it:** when the engine's lock is held (a queue is running), the running engine drains the row on its tick.
  Otherwise `engine wake` runs a short pass: it takes the lock, drains only `schedule` rows, runs each command in a
  window `sched·<name>` of `<project>-bg` (creating the session if needed), records `schedule_ran` with its exit code,
  releases the lock and exits. Scheduled jobs do not count toward the queue's concurrency of 1.
- **Migration:** `tmux-ctl engine schedule migrate` turns the launchd jobs added by the specs that ran before this one
  (memory consolidation's nightly run, opportunity discovery's `discover nightly`, trend scout's `scout poll` and
  `scout weekly`, the ops bot's daily digest), where installed, into schedule rows with the same times and commands,
  then unloads and removes their plists (each removal a `steps` row, kind `plist_remove`, check: the plist is gone and
  `launchctl list` does not show the label). Part 2's finishing step runs it once; the stored Queue mode answer is the
  user's approval. Specs that add a recurring job after this one add a schedule row instead of a plist.

## Error handling

- On an internal error (an exception, a database it cannot write, a git command failing outside a job) the
  engine stops dispatching, records an `engine_error` event, types `[Engine] stopped: <reason>` into the lead's
  window, and leaves the database, worktrees and windows as they are. `engine resume` continues.
- A report with a missing or malformed status block counts as no report (section 2).
- A plan without a `.tasks.json`, or a task without a `verifyCommand`: the spec is not run by the engine; it is
  handed to the lead (`[Engine] your turn: <spec>`) and recorded as lead-run.
- A model limit error in a worker's pane (the Fable limit): the job is run again on Opus, once, with an event
  saying so (`model_limit`, section 10.2).
- A usage limit reached (a worker's pane shows the limit message, or the status-line tap reads 100% for the
  5-hour or 7-day window): the engine stops dispatching, sets a `usage_reset` timer (section 10.3), types
  `[Engine] paused: usage limit until <time>` into the lead's window, and dispatches again when the timer fires.
  Pacing against the limit is stage 6.
- Nothing in the engine answers a permission prompt.

## Testing

- **Runner (revised 2026-11-19):** `node --test` files under `engine/test/`, one job in `tools/tests/all.zsh`; the
  Python additions (`metrics append`, `metrics has`, the lock) are tested in `board/tests`. Tests use the `fake` backend
  (scripted events), not a process, except the real runs below.
- **Strategy:** table tests of `(state, event) -> [commands]` for every edge of section 3, no database and no backend.
- **Backend conformance:** one suite run against `fake` and `claude-tmux` (scratch tmux server): `start`, `close`,
  `resume`, and each event type.
- **Compiler and transitions:** unit tests with a fake worker (a script that writes a report and status block
  and exits) for every edge of section 3: bounce, third red, review pass, findings and fix rounds, round 5
  exhausted, batch review, final review with and without findings, each architect decision, each integration
  answer, tests red after the merge with the revert.
- **Finish detection:** fixture agent-status files for `ready` with and without a report, `needs-you` past
  10 minutes, a vanished window.
- **Crash and resume:** the engine killed (by pid) at each transition of a fake-worker run resumes to the same
  final state and event sequence, with no job run twice when its report was valid. After every resume,
  `engine rebuild --check` exits 0.
- **Durability (section 10):** a fake worker that hangs with a fresh heartbeat and no tool (no-progress: nudge,
  then fail), one that stops writing its status file (heartbeat timeout), one with a tool running past its limit;
  retry policies from a fixture `engine.json` overriding a default (attempts, backoff timer, `no_retry_on`,
  `on_exhausted` each path); the engine killed between `intent` and `done` for every `steps` kind, the action
  observed as done or not done, resuming without running it twice (one merge commit, one record line) and parking
  when the check cannot tell; a signal written before and after a restart; a signal for a spec that is not
  waiting (exit 2); a `deadline` and a `usage_reset` timer due while the engine was down, each firing once; a
  policy-version change parking the spec, `approve` and `deny` paths; `rebuild --apply` refusing while the lock
  is held.
- **Parking across the queue (section 11):** a three-spec queue whose first spec parks: the second runs, an
  answer arriving during it resumes the first before the third; an unanswered wait at the end fails the spec, and a
  later signal plus `engine resume` completes it and re-records the outcome; the report's "Awaiting you" section.
- **Restart (section 11):** the board's restore action and its login start, against a fixture engine database
  with and without unfinished specs, on a scratch tmux server: `engine resume` started in `<project>-bg` only when
  unfinished, never a lead.
- **Isolation:** every test uses `TC_ENGINE_DIR` in a temporary directory and a scratch tmux server started with
  `-f /dev/null`; a leak check confirms the real engine directory and the real tmux server are untouched.
- **Queue runner (part 2):** a queue of three fixture specs (engine, lead, gated) with fake workers and a fake
  lead window: order, the five `[Engine]` lines, `engine done`, the gate failure, the report file's sections.
- **Real run, part 1:** one small real spec with a committed plan on a scratch clone of this repo, real workers,
  `--integration keep`: a merged-quality branch with every job's window opened and closed, and the event log,
  as the plan's e2e record.
- **Real run, part 2:** a user gate: the next real queue is split, and its morning report is the one the engine
  wrote.
- **Inbox (section 12):** the same source id inserted twice is one row; rows from every source drained oldest
  first in one tick; three user answers arriving during a job handled together on the next tick; an inbox writer
  (`engine signal`) never writing any table but `inbox`; the engine killed mid-drain resumes without handling a row
  twice; `rebuild --check` exits 0 after a drain.
- **Holds (section 13; moved to stage 7, not run in this stage):** a fake worker making each default hold pattern's call is denied with the hold id and the
  spec parks with the exact call as its question; a call inside the worktree is not held; `approve` resumes the
  session (a fake `claude --resume` records its arguments) and the hook allows exactly that call once, then denies a
  second identical call; a pass older than 1 h is refused; `deny` resumes with the note; an unresumable session gets
  a fresh worker with the answer; the hook does nothing outside an engine worker (`ENGINE_JOB` unset).
- **Schedules (section 14; moved to stage 7, not run in this stage):** each rule form's next occurrence (including across a DST change); a wake after a missed
  day fires once and moves to the next future occurrence; `skip_if_weekly_usage` skips and logs; a wake while the
  engine lock is held only inserts the inbox row; a wake with no lock runs the job in a scratch `<project>-bg` and
  exits; `schedule migrate` against fixture plists in a temporary `LaunchAgents` directory (never the real one).
- **Suites:** no new failures on the project's suites.

## Out of scope

- Concurrency above 1; locks and clusters; the merge queue and change packages; adaptive concurrency.
- Approval holds and schedules (sections 13 and 14: stage 7); a second backend, other strategies, strategy switching,
  the localhost API and any Discord path beyond the file contracts (stages 7 to 10); porting `board/metrics.py` to Node.
- The board as a view of engine state beyond `tmux-ctl engine status` (the tasks window keeps showing the
  lead's task list; the lead mirrors the queue's `Plan & run:` tasks from the `[Engine]` lines).
- Engine-run planning: plans and the cross-plan pass stay with stage 2's planners under the lead.
- Batching several small tasks into one implement job.
- A Temporal server or SDK, its web UI, child workflows, and full event sourcing (tables derived only from events);
  section 10 keeps Temporal's shapes so a later stage can move to it.

## Addition (user, 2026-11-12): publish to the feed

Every event the engine appends to its `events` table is also appended, in the same transaction's aftermath (after
commit, best effort, never failing the job), as one line of `${TC_STATE}/feed/<project>.jsonl` in the feed schema of
`docs/superpowers/specs/2026-11-11-discord-bridge-visibility-design.md` §11 (the engine's Node code writes the file; the
board's Python `board/discord_feed.py` reads it), with `tier` from this map: `fail_spec`,
`engine_error` → critical; a job or ruling that needs the user → decision; job done, review verdict, merge → progress;
everything else → routine. When the engine runs a spec, the board stops deriving that spec's progress events from task
lists (the engine is the source), so nothing is posted twice.
