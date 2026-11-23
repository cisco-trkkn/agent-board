# PCEE engine part 1 (`engine run <spec>`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Node engine in `engine/` that runs one planned spec end to end (`tmux-ctl engine run <spec>`): SQLite state, the `spec-driven` strategy, `fake` and `claude-tmux` backends, durable execution (timeouts, retries, waits, side-effect journal, policy version, replay check), the inbox, integrate, and the CLI.

**Architecture:** One `node:sqlite` database per project holds specs, jobs, an append-only event log and the durable tables; every state change is one transaction that also appends its event, with the changed rows in `detail` so `rebuild` can replay them. A pure strategy function turns `(state, event)` into commands; the engine core applies them, runs the architect pass, retries, timeouts and integrate, and talks to workers only through a backend (`start/close/resume` + `started|status|report|gone` events). A 5-second tick moves timers and worker status changes into the inbox, drains it, checks deadlines, advances the spec and dispatches.

**Tech Stack:** Node >= 22.13 (`node:sqlite` `DatabaseSync`, `node:test`, `node:child_process`), no npm dependencies; zsh (`bin/tmux-ctl`), tmux, git, `gh`.

**Spec:** `docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-1` (sections 1-5, 9, 10, 12, the feed Addition; sections 6-8, 11 and 13-14 are not in this plan)

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-1",
 "base": "fefceabfe16c63bb051d8061b9d05a621af44b7c",
 "depends_on": [{"spec": "docs/superpowers/specs/2026-11-10-pcee-registry-design.md", "kind": "hard"}],
 "writes": [
  {"path": "engine/lib/engine/db.js", "mode": "create"},
  {"path": "engine/lib/engine/policy.js", "mode": "create"},
  {"path": "engine/lib/engine/paths.js", "mode": "create"},
  {"path": "engine/lib/engine/report.js", "mode": "create"},
  {"path": "engine/lib/engine/compile.js", "mode": "create"},
  {"path": "engine/lib/engine/bounce.js", "mode": "create"},
  {"path": "engine/lib/engine/strategy/spec_driven.js", "mode": "create"},
  {"path": "engine/lib/engine/backend/fake.js", "mode": "create"},
  {"path": "engine/lib/engine/backend/claude_tmux.js", "mode": "create"},
  {"path": "engine/lib/engine/inbox.js", "mode": "create"},
  {"path": "engine/lib/engine/steps.js", "mode": "create"},
  {"path": "engine/lib/engine/feed.js", "mode": "create"},
  {"path": "engine/lib/engine/core.js", "mode": "create"},
  {"path": "engine/lib/engine/architect.js", "mode": "create"},
  {"path": "engine/lib/engine/integrate.js", "mode": "create"},
  {"path": "engine/lib/engine/ledger.js", "mode": "create"},
  {"path": "engine/lib/engine/rebuild.js", "mode": "create"},
  {"path": "engine/lib/engine/cli.js", "mode": "create"},
  {"path": "engine/bin/engine.js", "mode": "create"},
  {"path": "engine/test/engine_helpers.js", "mode": "create"},
  {"path": "engine/test/engine_db.test.js", "mode": "create"},
  {"path": "engine/test/engine_compile.test.js", "mode": "create"},
  {"path": "engine/test/engine_strategy.test.js", "mode": "create"},
  {"path": "engine/test/engine_backend.test.js", "mode": "create"},
  {"path": "engine/test/engine_inbox.test.js", "mode": "create"},
  {"path": "engine/test/engine_steps.test.js", "mode": "create"},
  {"path": "engine/test/engine_core.test.js", "mode": "create"},
  {"path": "engine/test/engine_integrate.test.js", "mode": "create"},
  {"path": "engine/test/engine_rebuild.test.js", "mode": "create"},
  {"path": "engine/test/engine_cli.test.js", "mode": "create"},
  {"path": "engine/test/engine_resume.test.js", "mode": "create"},
  {"path": "engine/test/fixtures/engine/fake-worker.js", "mode": "create"},
  {"path": "engine/package.json", "mode": "modify"},
  {"path": "bin/tmux-ctl", "mode": "modify"},
  {"path": "tools/tests/test_agent_dir.zsh", "mode": "create"},
  {"path": "docs/superpowers/engine.json", "mode": "create"},
  {"path": "docs/ARCHITECTURE.md", "mode": "modify"},
  {"path": "docs/superpowers/notes/2026-11-23-engine-part-1-e2e.md", "mode": "create"}
 ],
 "reads": ["docs/superpowers/specs/2026-11-10-pcee-engine-design.md", "engine/bin/registry.js", "engine/lib/registry/git.js",
           "engine/test/helpers.js", "board/paneclass.py", "board/tc_env.py", "board/ctxsize.py", "board/metrics.py",
           "board/discord_feed.py", "claude/worker.md", "claude/skills/subagent-driven-development-extras/SKILL.md",
           "docs/superpowers/model-routing.json", "tools/tests/all.zsh", "tools/tests/lib.zsh",
           "board/tests/fixtures/agent-status/real-new-fields.json"],
 "produces": ["tmux-ctl engine", "tmux-ctl agent --dir", "engine.sqlite schema", "spec-driven strategy", "backend interface"],
 "consumes": ["tmux-ctl registry stale", "tmux-ctl metrics start|record|has", "agent-status files", "feed jsonl"],
 "tests": ["engine/test/engine_db.test.js", "engine/test/engine_compile.test.js", "engine/test/engine_strategy.test.js",
           "engine/test/engine_backend.test.js", "engine/test/engine_inbox.test.js", "engine/test/engine_steps.test.js",
           "engine/test/engine_core.test.js", "engine/test/engine_integrate.test.js", "engine/test/engine_rebuild.test.js",
           "engine/test/engine_cli.test.js", "engine/test/engine_resume.test.js", "tools/tests/test_agent_dir.zsh"]}
```

## Global Constraints

Every task respects these. Reviewers check against them and against the spec sections each task cites.

- **Language and layout.** CommonJS, `"use strict"`, Node standard library only, no new npm dependency. Engine code lives in `engine/lib/engine/`, the entry in `engine/bin/engine.js` (shaped like `engine/bin/registry.js`: a `main(argv, io)` returning an exit code, `module.exports = { main }`, `process.exitCode = main(...)` under `require.main`). Tests are `engine/test/engine_*.test.js` with `node:test` and `node:assert/strict`; `cd engine && npm test` runs them, and `tools/tests/all.zsh` already runs that as its `engine` job.
- **Isolation (spec Testing, Isolation).** Every test sets `TC_ENGINE_DIR`, `TC_STATE` and `HOME`-independent paths to a fresh `fs.mkdtempSync` directory and never opens `~/.local/state/agent-board/engine/`. A test needing tmux starts a scratch server `tmux -L <unique short socket> -f /dev/null` with `TMUX_TMPDIR` under `/tmp` (a short path; long paths fail with "File name too long") and kills it in `after`. `engine/test/engine_helpers.js` (Task 1) provides `tmpEnv()`, `scratchTmux()`, `gitRepo()`; other tasks import it and do not edit it (a task that needs a new helper puts it in its own test file).
- **Paths (`engine/lib/engine/paths.js`, Task 1).** `engineDir()` = `$TC_ENGINE_DIR` else `$HOME/.local/state/agent-board/engine`; `dbPath(project)` = `<engineDir>/<project>.sqlite`; `lockPath(project)` = `<engineDir>/<project>.lock`; `stateDir()` = `$TC_STATE` else `${TMPDIR:-/tmp}` (trailing `/` stripped) + `/tmux-ctl-<uid>` (same rule as `board/tc_env.py` `state_dir`); `statusDir()` = `<stateDir>/agent-status`; `feedPath(project)` = (`$TC_STATE` else `$HOME/.local/state/agent-board`) + `/feed/<project>.jsonl` (same rule as `tc_env.feed_path`); `workspace(worktree)` = `<worktree>/.superpowers/engine`. The project key comes from `--project`, else `$TC_PROJECT`; `tmux-ctl engine` sets `TC_PROJECT="$FEEDKEY"`.
- **State rules (spec §1).** WAL mode. One state change = one `tx(db, fn)` that writes the rows and appends exactly one event. An event's `detail` is JSON with key `rows`: a list of `{"table": "<name>", "row": {<every column of the new row>}}` for every row the transaction inserted or updated (no deletes anywhere), plus any event-specific keys. `rebuild` (Task 10) replays only `rows`.
- **Schema (Task 1 creates it; later tasks only use it).**
  - `specs(id TEXT PK, position INT, runner TEXT, integration TEXT, push INT, batch TEXT, state TEXT, outcome TEXT, worktree TEXT, branch TEXT, plan TEXT, strategy TEXT DEFAULT 'spec-driven', backend TEXT DEFAULT 'claude-tmux', policy_version INT, policy_hash TEXT, base TEXT, created_at REAL, updated_at REAL)`
  - `jobs(id TEXT PK, spec TEXT, kind TEXT, task INT, tier TEXT, model TEXT, effort TEXT, state TEXT, attempt INT, brief TEXT, report TEXT, window TEXT, pane TEXT, session_id TEXT, base TEXT, head TEXT, tools TEXT DEFAULT 'all', mcp TEXT DEFAULT 'all', started_at REAL, ended_at REAL, needs_you_since REAL, needs_you_total REAL DEFAULT 0, detail TEXT)`
  - `events(seq INTEGER PK AUTOINCREMENT, ts REAL, spec TEXT, job TEXT, kind TEXT, detail TEXT)`
  - `steps(key TEXT PK, spec TEXT, kind TEXT, state TEXT, result TEXT, created_at REAL, updated_at REAL)`
  - `timers(id TEXT PK, spec TEXT, job TEXT, kind TEXT, due_at REAL, payload TEXT, fired_at REAL)`
  - `waits(id TEXT PK, spec TEXT, step TEXT, question TEXT, options TEXT DEFAULT 'approve|deny|fail', asked_at REAL, answered_at REAL, answer TEXT, note TEXT)`
  - `retry_policies(kind TEXT PK, max_attempts INT, backoff_s TEXT, timeout_min REAL, no_retry_on TEXT, on_exhausted TEXT)`
  - `inbox(id INTEGER PK AUTOINCREMENT, source TEXT, source_id TEXT, spec TEXT, job TEXT, kind TEXT, payload TEXT, received_at REAL, state TEXT DEFAULT 'new', handled_at REAL, reason TEXT, UNIQUE(source, source_id))`
  - Times are float epoch seconds. Spec states: `queued planning running final_review integrating awaiting_you done`. Job states: `pending running backoff done failed escalated`. Job ids: `<spec slug>:<kind><task or ''>:<attempt>`; `<spec slug>` = the spec file name minus `.md`, a leading `YYYY-MM-DD-` and a trailing `-design`, plus `-p<N>` for a `#part-N` suffix.
- **Strategy contract (spec §3, Task 3).** `decide(state, event) -> command[]`, pure: no I/O, no clock, no module state. `state = {spec: <specs row>, tasks: [{n, subject, tier, files, verifyCommand}], jobs: [<jobs rows>], events: [<events rows, detail parsed>]}`. Input event kinds: `spec_started`, `stale_result {stale}`, `job_done {job, kind, task, status}` (status = the parsed `json:status` object), `job_failed {job, kind, task, reason}`, `check_result {task, ok, text, round}`, `architect_decision {case, job, task, decision, ruling, cost_if_wrong}`, `integrated {outcome}`, `signal {answer, note, step}`. Commands: `{type:"start_job", kind, task?, tier, resume_of?, findings?, tasks?}`, `{type:"run_check", task}`, `{type:"record_ruling", text, cost_if_wrong, by}`, `{type:"park", question, options?, step}`, `{type:"escalate", case, job?, task?}`, `{type:"set_state", state}`, `{type:"request_integrate"}`, `{type:"log", kind, text, task?}` (kind `deferred` for minors). Job kinds: `refresh implement review fix final_review fix_wave re_review architect`. Escalation cases (spec §4, exactly these): `fix_rounds_exhausted blocked verify_red residual_findings tests_red_after_merge failed_twice`.
- **Backend contract (spec §2, Task 4).** `createBackend(opts)` returns `{start(job) -> Promise<handle>, close(handle) -> Promise<void>, resume(handle, text) -> Promise<handle>, poll() -> event[]}` where `handle = {job, window, pane, session_id?}` and each event is `{handle, type, ...}` with `type` one of `started`, `status` (`state` in `busy|ready|needs-you`, `updatedAt`, `tool`, `lastToolAt`, `turnStartedAt`), `report` (`path`), `gone`. The engine never reads tmux, panes or agent-status files itself.
- **Report contract (spec §2).** The report's last fenced block tagged `json:status`; shapes per job kind exactly as spec §2 lists. Missing or malformed = no report.
- **Retry defaults (spec §10.2)** are the table in spec §10.2, verbatim; `docs/superpowers/engine.json` key `retry` overrides per kind. `POLICY_VERSION = 1`. `policy_hash` = sha256 hex of the `engine.json` bytes, or of `{}` without the file.
- **Batch review exclusion (spec §3 step 4).** A task is never batch-reviewed when any of its files matches `/(^|\/)(\.gitlab-ci|\.github\/|\.agent-ci|ci\/|migrations?\/|security|auth|settings(\.local)?\.json|config\/|\.env)/i`.
- **Bounce text (E2).** Failing test names, their error lines and the runner's summary line, then `full log: <path>`; capped at `BOUNCE_MAX_LINES = 60` (a constant in `strategy/spec_driven.js`, imported by `bounce.js`); the event detail carries `bounce_bytes`.
- **Integration.** Target branch `main`. `merge`: `git merge --no-ff` in the main checkout only after the live-checkout check (`git -C <main> status --porcelain` empty apart from `.claude/` and `docs/superpowers/metrics/` lines, and no other `git` process with that cwd); else park `live checkout is mid-change`. `mr`: push (only with `--push`, never to `main` or `master`) then `gh pr create --base main --head <branch> --fill` when `origin` is a github.com URL, else `glab mr create --target-branch main --source-branch <branch> --fill --yes`. `keep`: nothing. Every engine commit ends with the trailer line `Engine-Step: <key>`. Project test command: `docs/superpowers/engine.json` `test` (with `test_ok`, a list of passing exit codes, default `[0]`); without it, every task's `verifyCommand` in order.
- **External commands.** The engine shells out with `spawnSync`/`spawn` and an argv array (no shell string) except `verifyCommand`s and the `test` command, which run as `zsh -c <command>` in the worktree with a 30-minute timeout. `tmux-ctl` is invoked as `<repo>/bin/tmux-ctl` (env `TC_TMUX_CTL` overrides, for tests).
- **Never.** The engine answers no permission prompt, never pushes without stored consent or to `main`/`master`, never resets (reverts are commits), never opens `docs/superpowers/metrics/runs.jsonl` (it calls `tmux-ctl metrics start|record|has`).
- **Commits.** Conventional commits with scope `engine` (`feat(engine): …`, `test(engine): …`, `docs(engine): …`); end every commit message with the attribution trailer your harness specifies. Stage only your own paths (`git add <paths>`).

**User decisions (already made):**
- "The engine is Node.js in a new `engine/` folder", `node:sqlite`, `engines: node >= 22.13` (spec revision 2026-11-19, items 2, 11, 12).
- "Stage 3 scope: the core plus durable execution, the inbox and parking (sections 10-12). Approval holds (13) and schedules (14) move to stage 7." (item 5)
- "Strategy = a pure function `(state, event) -> [commands]`… Backend = an event source with `start / close / resume`… Tests use a fake backend." (item 6)
- "runs.jsonl has one writer": the engine calls `tmux-ctl metrics append|has|start|record|gate` (item 10).
- Queue answer 2026-11-23: integration `mr`, push yes; the remote is GitHub, so the PR goes through `gh`.
- K1 is not relaxed (user, 2026-11-23); it passes.

**Assumptions (plan author's; each costs one small change if wrong):**
- A1. The board's feed dedupe ("the board stops deriving that spec's progress events", spec Addition, last sentence) needs the queue runner to know a spec is engine-run; it is built in part 2. Part 1 only appends feed lines.
- A2. `tmux-ctl agent --dir <worktree>` starts the worker without `-w` (no new worktree), with window name given by `--name`-less positional `<name>` as today; the engine passes `<spec slug>·<kind><task>`.
- A3. Resume of an implementer's session for fix rounds uses `claude --resume <session_id>` typed via a new window started by `tmux-ctl agent --dir … --resume <session_id>`; when the job has no `session_id` (the agent-status file's `session_id`), a fresh worker gets brief + report + findings.
- A4. `docs/superpowers/engine.json` for this repo: `{"test": "zsh tools/tests/all.zsh", "test_ok": [0, 4]}` (all.zsh exits 4 when every job passed but over its time budget, accepted on this machine).

---

### Task 1: Engine state: paths, database, schema, transactions, policy

**Goal:** `paths.js`, `db.js` and `policy.js` give every later task one way to locate, open and change engine state, and the retry and policy defaults.

**Files:**
- Create: `engine/lib/engine/paths.js`, `engine/lib/engine/db.js`, `engine/lib/engine/policy.js`, `engine/test/engine_helpers.js`, `engine/test/engine_db.test.js`

**Acceptance Criteria:**
- [ ] `paths.js` exports `engineDir, dbPath, lockPath, stateDir, statusDir, feedPath, workspace, specSlug` with the rules in Global Constraints; `specSlug("docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-1") === "pcee-engine-p1"`.
- [ ] `db.js` exports `open(project) -> db` (creates the directory and the schema of Global Constraints, WAL on, `PRAGMA journal_mode` reads `wal`), `tx(db, fn)` (BEGIN IMMEDIATE / COMMIT, ROLLBACK and rethrow on error), `put(db, table, row)` (INSERT OR REPLACE of a full row, returns the row) and `event(db, {spec, job, kind, rows, ...extra})` (appends one event with `detail = {rows, ...extra}`); a test shows a `tx` that throws leaves no row and no event.
- [ ] `policy.js` exports `POLICY_VERSION = 1`, `DEFAULT_RETRY` (the spec §10.2 table, every row and column), `loadConfig(repo) -> {test, test_ok, retry, raw}` (reads `docs/superpowers/engine.json` if present), `retryFor(config, kind)` (defaults overridden per key) and `policyHash(config)` (sha256 hex of the raw bytes, or of `{}`).
- [ ] `engine_helpers.js` exports `tmpEnv()` (sets and returns a temp `TC_ENGINE_DIR`, `TC_STATE`, restoring the old env on `restore()`), `scratchTmux()` (`{socket, run(args), kill()}` with `-f /dev/null`), `gitRepo()` (a temp repo with one commit on `main`).

**Verify:** `cd engine && node --test test/engine_db.test.js` → all tests pass

**Steps:**
- [ ] Write `engine_db.test.js` covering each criterion (schema columns via `PRAGMA table_info`, WAL, rollback, `put` + `event` detail shape, `retryFor` override from a fixture `engine.json` in a `gitRepo()`, `policyHash` of no file equals sha256 of `{}`). Mutation for the rollback test: replace ROLLBACK with COMMIT → the "no row and no event" test fails.
- [ ] Run it: fails (modules missing).
- [ ] Implement the three modules and the helpers; `DatabaseSync` from `node:sqlite`.
- [ ] Run it: passes. Commit `feat(engine): state database, schema and retry policy`.

```json:metadata
{"files": ["engine/lib/engine/paths.js", "engine/lib/engine/db.js", "engine/lib/engine/policy.js", "engine/test/engine_helpers.js", "engine/test/engine_db.test.js"], "verifyCommand": "cd engine && node --test test/engine_db.test.js", "acceptanceCriteria": ["paths.js exports and specSlug rule", "db.js open/tx/put/event with rollback test", "policy.js defaults, override, hash", "engine_helpers tmpEnv/scratchTmux/gitRepo"], "modelTier": "standard"}
```

---

### Task 2: Report parser, plan compiler, bounce text

**Goal:** Parse a worker's `json:status` block, compile a plan's `.tasks.json` into the strategy's task list, and build the short bounce text from a red check's output.

**Files:**
- Create: `engine/lib/engine/report.js`, `engine/lib/engine/compile.js`, `engine/lib/engine/bounce.js`, `engine/test/engine_compile.test.js`

**Acceptance Criteria:**
- [ ] `report.parse(text, kind) -> object|null`: takes the LAST fenced block whose info string is `json:status`; returns null when absent, not JSON, or not the kind's shape (spec §2: implement/fix/refresh `status` ∈ done|blocked with `commits`, `concerns` arrays; review `verdict` ∈ pass|findings with `findings[]` of `{severity ∈ critical|important|minor, task, text}`; architect `decision` ∈ proceed|retry_higher_tier|park|fail_spec with `ruling`, `cost_if_wrong` strings). A report with two status blocks uses the second.
- [ ] `compile.compile(tasksJsonText) -> {tasks}|{error}`: each task → `{n, subject, tier, files, verifyCommand}` from its `json:metadata` fence (n = position + 1, in file order); `{error: "no verifyCommand: task <n>"}` when any task lacks one, `{error: "no .tasks.json"}` for null input (spec Error handling: such a spec is handed to the lead).
- [ ] `bounce.text(output, logPath) -> {text, bytes}`: keeps lines matching failing-test names and error lines (`/^(not ok|FAIL|ERROR|✗|AssertionError|Error:)/`, `/^\s+(at |expected|actual)/` up to 3 per failure) and the last summary line (`/^(# (pass|fail)|Ran \d+|FAILED|OK|ALL PASS|\d+ (passing|failing))/`), then `full log: <logPath>`; at most `BOUNCE_MAX_LINES` lines (imported from `strategy/spec_driven.js`; until Task 3 lands, define it in `bounce.js` and have Task 3 re-export it — the test imports it from `bounce.js`).
- [ ] Tests use a real `.tasks.json` from this repo (`docs/superpowers/plans/2026-11-21-interactive-tasks-window.md.tasks.json`, read-only) and real red outputs: one from `node --test` and one from `python3 -m unittest` (generated in the test by running a tiny failing test in a temp dir).

**Verify:** `cd engine && node --test test/engine_compile.test.js` → all tests pass

**Steps:**
- [ ] Write the tests (mutation: drop the "last block" rule and take the first → the two-blocks test fails).
- [ ] Run: fails. Implement. Run: passes. Commit `feat(engine): report parser, plan compiler, bounce text`.

```json:metadata
{"files": ["engine/lib/engine/report.js", "engine/lib/engine/compile.js", "engine/lib/engine/bounce.js", "engine/test/engine_compile.test.js"], "verifyCommand": "cd engine && node --test test/engine_compile.test.js", "acceptanceCriteria": ["report.parse last json:status block, per-kind shapes", "compile tasks and verifyCommand error", "bounce text capped with full log path and bytes", "real tasks.json and real red outputs"], "modelTier": "standard"}
```

---

### Task 3: The `spec-driven` strategy

**Goal:** `strategy/spec_driven.js` exports `decide(state, event)` implementing spec §3 steps 1-6 and the strategy side of §4 and §10.2 (bounce and fix_round counts), pure.

**Constraints:** The contract in Global Constraints (input events, commands, job kinds, escalation cases) is fixed; counters (bounces per task, fix rounds per task, retry_higher_tier used per job) are derived from `state.jobs` and `state.events`, never stored in the module. Defaults come from `state.retry` (the loaded `retryFor` rows passed in the snapshot as `state.retry[kind]`), not literals. Small-fix rule: as `claude/skills/subagent-driven-development-extras/SKILL.md` defines "small"; a small fix on a mechanical task is re-reviewed at the mechanical tier. Batch review: consecutive green mechanical tasks, up to 5, excluding the Global Constraints file regex. Exports `BOUNCE_MAX_LINES = 60`.

**Files:**
- Create: `engine/lib/engine/strategy/spec_driven.js`, `engine/test/engine_strategy.test.js`
- Modify: `engine/lib/engine/bounce.js` (import `BOUNCE_MAX_LINES` from the strategy instead of defining it)

**Acceptance Criteria:**
- [ ] Table tests (no database, no backend) for every edge: `spec_started` → stale check request (`start_job refresh` only after `stale_result {stale:true}`; `stale:false` → first `implement`); implement done → `run_check`; check red #1, #2 → `start_job fix` with the bounce (resume_of the implementer); red #3 → `escalate verify_red`; green → `review` (or held for a batch when mechanical and the next task is mechanical and not excluded); batch of up to 5 → one `review` with `tasks: [..]`; review pass → next task; findings critical/important → `fix` round n (n ≤ 5), minors → `log deferred`; round 5's findings → `escalate fix_rounds_exhausted`; implementer `blocked` → `escalate blocked`; `job_failed` → nothing (retries are core's), and a second failure of the same job kind and task → `escalate failed_twice`; last task done → `set_state final_review` + `start_job final_review` (frontier); final findings → one `fix_wave` then one `re_review`; residual → `escalate residual_findings`; clean → `set_state integrating` + `request_integrate`; `integrated {outcome:"tests_red"}` → `escalate tests_red_after_merge`; each `architect_decision`: proceed (park the finding as deferred, continue), retry_higher_tier (re-run one tier up, refused → escalate again if already used for that job), park (`park` with the ruling as question), fail_spec (`set_state done` with outcome `failed — <ruling>`), each also `record_ruling` with cost_if_wrong.
- [ ] A purity test: `decide` called twice on deep-frozen copies of the same input returns deep-equal output and throws on no frozen object.
- [ ] Each guard test names its mutation in a comment (e.g. "change `>= 3` to `> 3` → `third red escalates` fails").

**Verify:** `cd engine && node --test test/engine_strategy.test.js test/engine_compile.test.js` → all tests pass

```json:metadata
{"files": ["engine/lib/engine/strategy/spec_driven.js", "engine/lib/engine/bounce.js", "engine/test/engine_strategy.test.js"], "verifyCommand": "cd engine && node --test test/engine_strategy.test.js test/engine_compile.test.js", "acceptanceCriteria": ["table tests for every section 3 edge and each architect decision", "purity test on frozen inputs", "mutations named"], "modelTier": "frontier"}
```

---

### Task 4: Backend interface and the `fake` backend

**Goal:** The backend contract as code, a `fake` backend driven by a script, and a conformance suite any backend runs.

**Files:**
- Create: `engine/lib/engine/backend/fake.js`, `engine/test/fixtures/engine/fake-worker.js`, `engine/test/engine_backend.test.js`

**Acceptance Criteria:**
- [ ] `fake.createBackend({script})`: `script[jobKindAndTask]` is a list of steps (`{status: "busy"|"ready"|"needs-you", tool?, at}`, `{report: "<text>"}` written to the job's report path, `{gone: true}`, `{hang: true}` = status updates with no tool); `start` returns a handle and queues `started`; `poll()` returns events due by the fake clock (`opts.now()`); `close` emits `gone`; `resume(handle, text)` records the text and returns a new handle; `calls` exposes every call for assertions.
- [ ] `fake-worker.js` is a script a real process can run (`node fake-worker.js <report path> <status json path> <mode>` writing an agent-status-shaped file every second and a report, modes `done`, `blocked`, `hang`, `silent`, `noreport`), used by Task 5's conformance run and Task 12.
- [ ] `engine_backend.test.js` exports `conformance(name, makeBackend)` and runs it for `fake`: start → `started`; a `ready` + report → `status ready` then `report`; `close` → `gone`; `resume` → a new handle and the text recorded; each event carries `handle.job`.

**Verify:** `cd engine && node --test test/engine_backend.test.js` → all tests pass

**Steps:**
- [ ] Write the conformance suite and its fake run. Run: fails. Implement. Run: passes. Commit `feat(engine): backend contract and fake backend`.

```json:metadata
{"files": ["engine/lib/engine/backend/fake.js", "engine/test/fixtures/engine/fake-worker.js", "engine/test/engine_backend.test.js"], "verifyCommand": "cd engine && node --test test/engine_backend.test.js", "acceptanceCriteria": ["fake backend scripted events and calls", "fake-worker.js real process modes", "conformance suite run for fake"], "modelTier": "standard"}
```

---

### Task 5: `claude-tmux` backend and `tmux-ctl agent --dir`

**Goal:** Real workers: `tmux-ctl agent` starts a worker in an existing worktree, and the `claude-tmux` backend starts, watches, closes and resumes them through tmux and agent-status files.

**Files:**
- Create: `engine/lib/engine/backend/claude_tmux.js`, `tools/tests/test_agent_dir.zsh`
- Modify: `bin/tmux-ctl` (the `agent)` case and its usage line, header line 17, in place: no new header line), `engine/test/engine_backend.test.js` (add the `claude-tmux` conformance run only)

**Acceptance Criteria:**
- [ ] `tmux-ctl agent <name> --dir <worktree> [--resume <session id>] [--model M] [--effort E] --brief FILE`: with `--dir`, the launch line `cd`s into `<worktree>` (must be a directory inside a git worktree, else `die`) and drops `-w <name>`; with `--resume`, it runs `claude --resume <id>` and the brief text is the first message; without `--dir` behaviour is byte-identical to today (`TC_AGENT_DRYRUN` line compared before/after in `test_agent_dir.zsh`). The header's line 17 becomes `#   tmux-ctl agent <name> [--force] [--dir WT [--resume ID]] [--model M] [--effort E] <task> | --brief FILE` (one line, so the `sed -n '2,84p'` range stays right).
- [ ] `claude_tmux.createBackend({session, tmuxCtl, statusDir, tmuxArgs})`: `start(job)` runs `tmux-ctl agent <window> --dir <worktree> --model <m> --effort <e> --brief <brief>` with window `<spec slug>·<kind><task>` (A2) and reads back the window's pane id; `poll()` reads `statusDir` for the record whose `pane` is a running handle's pane (newest `updatedAt`), emitting `status` on each change of `state` or `updatedAt`, `report` when the job's report file exists and parses (`report.parse`), `gone` when the pane is gone; `close(handle)` saves the pane's last 200 lines to `<workspace>/logs/<job>-<attempt>.log` then kills the pane by id; `resume(handle, text)` starts a new window with `--resume <session_id>`.
- [ ] Conformance suite (Task 4) passes for `claude-tmux` on a scratch tmux server (`-f /dev/null`), with `fake-worker.js` standing in for `claude` (the agent launch is pointed at it through `TC_AGENT_CMD`, a test seam this task adds to the `agent)` case: when set, it replaces `claude …` in the launch line) and `TC_STATE` in a temp dir.
- [ ] Real-state check (read-only): a test parses every file currently in the real `statusDir()` with the same reader and asserts each is either a record with `pane` and `state` or skipped; it prints how many it read (and passes with 0 only when the directory is absent).
- [ ] `zsh tools/tests/test_agent_dir.zsh` passes; the existing `tmux-ctl agent` suites still pass (`test_agent_launch.zsh`, `test_agent_model.zsh`, `test_agent_env.zsh`).

**Verify:** `cd engine && node --test test/engine_backend.test.js && cd .. && zsh tools/tests/test_agent_dir.zsh && zsh tools/tests/test_agent_launch.zsh && zsh tools/tests/test_agent_model.zsh && zsh tools/tests/test_agent_env.zsh`

```json:metadata
{"files": ["engine/lib/engine/backend/claude_tmux.js", "tools/tests/test_agent_dir.zsh", "bin/tmux-ctl", "engine/test/engine_backend.test.js"], "verifyCommand": "cd engine && node --test test/engine_backend.test.js && cd .. && zsh tools/tests/test_agent_dir.zsh && zsh tools/tests/test_agent_launch.zsh && zsh tools/tests/test_agent_model.zsh && zsh tools/tests/test_agent_env.zsh", "acceptanceCriteria": ["agent --dir and --resume, unchanged without --dir", "claude-tmux start/poll/close/resume", "conformance on scratch tmux with fake-worker", "read-only check of the real agent-status dir", "agent suites pass"], "modelTier": "standard"}
```

---

### Task 6: Inbox, timers, waits and `engine signal`

**Goal:** The durable wake-up path of spec §10.3 and §12: writers insert one inbox row; the drain hands rows to the core oldest first; timers move in when due; waits hold one open question per spec.

**Files:**
- Create: `engine/lib/engine/inbox.js`, `engine/test/engine_inbox.test.js`

**Acceptance Criteria:**
- [ ] `inbox.insert(db, {source, source_id, spec, job, kind, payload})` is `INSERT OR IGNORE` and touches no other table (a test diffs every other table's row count before and after); the same `(source, source_id)` twice is one row.
- [ ] `inbox.moveDueTimers(db, now)` inserts one row per due, unfired timer (`source` `timer`, `source_id` `<id>@<due_at>`) and sets `fired_at`, in one `tx` per timer with its event; a timer due while the engine was down fires once.
- [ ] `inbox.workerRows(db, events)` turns backend `status`/`gone` events into rows with `source_id` `<pane>:<state>:<updatedAt>` (or `<pane>:gone`).
- [ ] `inbox.drain(db, handle)` reads `new` rows by `id`, calls `handle(row)` for each inside one `tx` that sets `done` (or `dropped` with `reason` when `handle` returns `{drop: "<reason>"}`) and appends a `inbox_<source>` event with the payload; a thrown handler rolls back that row only and stops the drain (the row stays `new`).
- [ ] `inbox.openWait(db, {spec, step, question, options})`, `inbox.answerWait(db, spec, answer, note)`, `inbox.openWaitFor(db, spec)`; a second open wait for the same spec throws.
- [ ] `inbox.signal(db, spec, answer, note)` (the `engine signal` writer): exit-code semantics as a return: `{rc: 2, msg: "no open wait for <spec>"}` when the spec is not `awaiting_you`, else inserts a `user` row with a fresh uuid `source_id` and returns `{rc: 0}`.
- [ ] Tests: three user rows inserted between two drains are handled together, oldest first; a drain killed mid-way (handler throws on row 2) leaves row 1 `done` and rows 2-3 `new`, and the next drain does not handle row 1 again.

**Verify:** `cd engine && node --test test/engine_inbox.test.js` → all tests pass

```json:metadata
{"files": ["engine/lib/engine/inbox.js", "engine/test/engine_inbox.test.js"], "verifyCommand": "cd engine && node --test test/engine_inbox.test.js", "acceptanceCriteria": ["insert OR IGNORE, writes only inbox", "due timers fire once", "worker rows source ids", "drain oldest first, done/dropped, rollback on throw", "one open wait per spec", "signal rc 2 when not waiting"], "modelTier": "standard"}
```

---

### Task 7: Side-effect journal and feed publishing

**Goal:** Every action outside the database goes through `steps.run(key, kind, act, check)` (spec §10.4), and every event is mirrored best effort to the feed file (spec Addition).

**Files:**
- Create: `engine/lib/engine/steps.js`, `engine/lib/engine/feed.js`, `engine/test/engine_steps.test.js`

**Acceptance Criteria:**
- [ ] `steps.run(db, {key, spec, kind}, act)`: writes `intent` in its own committed `tx` before `act()`, then `done` with the result (or `failed` with the error) in a second `tx`; a key already `done` returns the stored result without acting.
- [ ] `steps.CHECKS[kind](ctx, row) -> "done"|"not_done"|"unknown"` for every kind of spec §10.4: `start_worker` (a window with the job's name exists; adopt its pane id), `close_window` (pane gone), `merge` (branch head is an ancestor of the target), `revert`/`commit_report`/`commit_ledger` (a commit on the target carries `Engine-Step: <key>`), `metrics_start`/`metrics_record` (`tmux-ctl metrics has start|run --spec <id> --batch <id>` exits 0), `push` (`git ls-remote` ref equals the recorded sha; unreachable → `unknown`), `worktree_remove` (path gone from `git worktree list`).
- [ ] `steps.reconcile(db, ctx)`: for every `intent` row, runs its check; `done` → marks done; `not_done` → returns it for re-run; `unknown` → returns a park request `could not tell whether <key> ran`.
- [ ] Tests, one per kind, against a `gitRepo()` and a fake `tmux-ctl` script (`TC_TMUX_CTL`): the engine "killed" between intent and done (simulate by writing intent and not calling done), with the action observed done and not done; resuming runs it at most once (one merge commit, one `metrics record` call counted by the fake script).
- [ ] `feed.publish(project, event)`: appends one line `{ts, project, spec (basename without .md and #part), kind, tier, text, refs}` to `paths.feedPath(project)`, tier by the spec Addition's map (`fail_spec`, `engine_error` → critical; `park`/`awaiting_you` and rulings needing the user → decision; `job_done`, review verdict, `merge` → progress; else routine), text one line cut at 300 chars; never throws (a test with an unwritable path returns without error); the line parses with `board/discord_feed.py` `read_events` (the test runs `python3 -I -c` importing it from the repo).

**Verify:** `cd engine && node --test test/engine_steps.test.js` → all tests pass

```json:metadata
{"files": ["engine/lib/engine/steps.js", "engine/lib/engine/feed.js", "engine/test/engine_steps.test.js"], "verifyCommand": "cd engine && node --test test/engine_steps.test.js", "acceptanceCriteria": ["intent/done journal, done key not re-run", "a check per section 10.4 kind", "reconcile done/not_done/unknown->park", "kill between intent and done per kind, at most once", "feed line readable by discord_feed.read_events, never throws"], "modelTier": "standard"}
```

---

### Task 8: Engine core: tick, commands, architect, durability, recovery

**Goal:** `core.js` and `architect.js` run one spec: the 5-second tick of spec §10 (timers and worker status into the inbox, drain, timeouts, advance, dispatch), applying strategy commands in one transaction each, with the architect pass (§4), timeouts (§10.1), retries (§10.2), parking and signals (§10.3), policy version (§10.5), usage and model limits (Error handling), the lock file and resume (§9).

**Constraints:** Uses only Tasks 1-7's modules and the backend contract; the clock (`now()`) and the backend are injected so tests drive `tick()` directly with the fake backend. Integrate is called through an injected `integrate(spec)` (Task 9 supplies the real one). Timeouts and deadlines are `timers` rows (kind `deadline`), so a restart keeps them; a job in `needs-you` stops its clocks (`needs_you_since`, `needs_you_total`) and parks the spec after 10 minutes with `permission prompt in <window>`, un-parking without a signal when the worker goes busy again. Briefs and reports are files in `paths.workspace(worktree)`; the architect's case file holds exactly what spec §4 lists. `model_limit` reruns once on Opus outside the count (`model_fallback` event); `usage_limit` sets a `usage_reset` timer (reset time from the status-line tap file `<TC_STATE>/statusline/` when present, else one hour) and pauses dispatch. On an internal error: stop dispatching, `engine_error` event, leave everything as is. The lock file holds the pid; a second engine for the project refuses. Job end events carry `context_tokens` (via `python3 -I board/ctxsize.py last <transcript>`, transcript found from the job's `session_id`) or null with `context_missing: "<reason>"` (E3). The `tools`/`mcp` job columns stay `all` (E4). Every event is passed to `feed.publish` after commit.

**Files:**
- Create: `engine/lib/engine/core.js`, `engine/lib/engine/architect.js`, `engine/test/engine_core.test.js`

**Acceptance Criteria:**
- [ ] With the fake backend and a fake `integrate`, a three-task plan runs from `spec_started` to `done` with outcome from `integrate`, every job's window started and closed, and the event sequence asserted.
- [ ] Each spec §2 finish rule: `ready` + valid report → done and close; `ready` without report → one `tell` naming the report path, a second → failed attempt; `gone` without report → failed attempt.
- [ ] Each §10.1 timeout fires with its reason (`heartbeat_timeout` at 2 min with no status, `no_progress` nudge then fail 5 min later, `tool_timeout` Bash at 15 min, `job_timeout` from `timeout_min`), and none fires while `needs-you`.
- [ ] Retry policy paths from a fixture `engine.json`: attempts and `backoff` timer (job state `backoff`), `no_retry_on` (`blocked` straight to `on_exhausted`), each `on_exhausted` (`architect`, `park`, `fail_spec`).
- [ ] Architect: each case of §4 starts one frontier `architect` job with a case file; each decision is fed back as `architect_decision` and recorded as a `ruling` event with `cost_if_wrong`.
- [ ] Parking: a stop-class case and a user-gate task park the spec (`awaiting_you`, one open wait, a `decision` feed line with the exact `tmux-ctl engine signal …` command); `approve` resumes at the stored step, `deny` skips or fails with `denied: <question>`, `fail` fails with the note; each answer is a `ruling` event `by: user`; under `engine run` the engine keeps ticking until answered.
- [ ] Policy version: a spec stamped with version 0 or another hash parks with `engine rules changed (<old>→<new>): continue under the new rules?`; approve re-stamps.
- [ ] Usage limit pauses dispatch and fires once at the reset time; `model_limit` reruns once on Opus.
- [ ] Lock: a second `core.start` for the same project throws `engine already running (pid <n>)`.
- [ ] Mutations named next to the timeout and lock tests.

**Verify:** `cd engine && node --test test/engine_core.test.js` → all tests pass

```json:metadata
{"files": ["engine/lib/engine/core.js", "engine/lib/engine/architect.js", "engine/test/engine_core.test.js"], "verifyCommand": "cd engine && node --test test/engine_core.test.js", "acceptanceCriteria": ["fake three-task run to done", "finish rules", "four timeouts, paused in needs-you", "retry policy paths", "architect cases and rulings", "parking and signals", "policy version park", "usage and model limits", "lock refuses second engine"], "modelTier": "frontier"}
```

---

### Task 9: Integrate and the ledger archive

**Goal:** `integrate.js` is the engine-core step 7 of spec §3 and the revert of §4; `ledger.js` renders the archive from the events in today's line forms.

**Files:**
- Create: `engine/lib/engine/integrate.js`, `engine/lib/engine/ledger.js`, `engine/test/engine_integrate.test.js`

**Acceptance Criteria:**
- [ ] `integrate.run(ctx, spec) -> {outcome}`: project test command before (red → `{outcome: "tests_red_before"}` and nothing merged); then by the stored answer: `merge` (live-checkout check per Global Constraints, else park; `git merge --no-ff` with `Engine-Step: merge:<branch>@<base sha>`), `mr` (push only when `push` is 1 and the branch is not `main`/`master`; `gh pr create` for github.com, `glab mr create` otherwise; outcome `mr <url>`), `keep` (`kept <branch>`); tests after the merge on the merged result (red → `{outcome: "tests_red"}`); then `commit_ledger`, `metrics_record` (`tmux-ctl metrics record <spec> --batch <id> --outcome <outcome>`), `worktree_remove` for `merge`; each a `steps.run` row.
- [ ] `integrate.revert(ctx, spec)`: `git revert -m 1 --no-edit <merge sha>` with trailer `Engine-Step: revert:<sha>`, never a reset, branch kept.
- [ ] `ledger.render(events) -> text` writes the lines `metrics.py` `ledger_fields` counts, in today's forms: `Task <n>: dispatched <window> (<tier>, <model>)`, `Task <n>: green check ok (verify rc 0) — <sha>`, `Task <n>: review … ❌ …` for findings, `Task <n>: fix round <k>`, `Task <n>: minor (deferred): <text>`, `Ruling: <text> — <cost if wrong>`, `Final review: fix wave`, `Task <n>: complete (commits <a>..<b>, review clean)`; a test runs `python3 -I -c` with `board/metrics.py` `ledger_fields` on the rendered text and checks every counter.
- [ ] Tests on a `gitRepo()` with a bare remote: each answer (`merge`, `mr` with a fake `gh` on PATH recording its argv, `keep`), push refused without consent and to `main`, live checkout dirty → park, tests red after merge → revert commit present and branch kept, each `steps` key written once.

**Verify:** `cd engine && node --test test/engine_integrate.test.js` → all tests pass

```json:metadata
{"files": ["engine/lib/engine/integrate.js", "engine/lib/engine/ledger.js", "engine/test/engine_integrate.test.js"], "verifyCommand": "cd engine && node --test test/engine_integrate.test.js", "acceptanceCriteria": ["tests before and after, merge/mr/keep", "push consent and never main", "live-checkout park", "revert commit, branch kept", "ledger lines counted by metrics.ledger_fields"], "modelTier": "standard"}
```

---

### Task 10: Replay check (`rebuild --check|--apply`)

**Goal:** `rebuild.js` replays every event's `rows` into a scratch database and diffs it with the live tables (spec §10.6).

**Files:**
- Create: `engine/lib/engine/rebuild.js`, `engine/test/engine_rebuild.test.js`

**Acceptance Criteria:**
- [ ] `rebuild.check(project) -> {rc, diffs}`: rc 0 when every table except `events` matches row for row (all columns), else rc 1 with one line per difference (`<table> <pk>: <column> live=<v> replay=<v>`, or a missing row).
- [ ] `rebuild.apply(project)`: refuses (`{rc: 2, msg: "engine lock held"}`) while the lock file names a live pid; else copies the database to `<project>.sqlite.bak-<epoch>` and replaces the live tables with the replayed ones.
- [ ] Tests: a run of `tx`/`put`/`event` calls → check rc 0; a row changed behind the log (direct `UPDATE`) → rc 1 naming it; apply repairs it and keeps the backup; apply with a live lock → rc 2. Mutation: skip one table in the diff → the behind-the-log test fails.

**Verify:** `cd engine && node --test test/engine_rebuild.test.js` → all tests pass

```json:metadata
{"files": ["engine/lib/engine/rebuild.js", "engine/test/engine_rebuild.test.js"], "verifyCommand": "cd engine && node --test test/engine_rebuild.test.js", "acceptanceCriteria": ["check rc 0 / rc 1 with diffs", "apply refuses with lock, keeps backup", "mutation named"], "modelTier": "standard"}
```

---

### Task 11: CLI, `tmux-ctl engine`, engine.json and docs

**Goal:** `tmux-ctl engine run|status|events|resume|signal|rebuild` works from any project pane (spec §5).

**Files:**
- Create: `engine/lib/engine/cli.js`, `engine/bin/engine.js`, `engine/test/engine_cli.test.js`, `docs/superpowers/engine.json`
- Modify: `bin/tmux-ctl` (an `engine)` case next to `registry)`, and header line 82 in place: `#   tmux-ctl registry|engine <sub> …       plan manifests, graphs, waves; the PCEE engine (engine/, node)`), `engine/package.json` (description), `docs/ARCHITECTURE.md` (an "Engine" section: state file, tables, the two interfaces, commands, exit codes)

**Acceptance Criteria:**
- [ ] `engine run <spec> --integration merge|mr|keep [--push] [--batch <id>] [--project P] [--backend claude-tmux|fake]`: finds the plan (`**Spec:**` line, as `engine/lib/registry/git.js` `findPlan`), compiles it (a compile error prints `[Engine] your turn: <spec>` and exits 3), inserts the spec, runs `tmux-ctl metrics start` as a `metrics_start` step, runs the core in the foreground printing one line per event (`<HH:MM:SS> <kind> <job or -> <short text>`), exits 0 on a `merged`/`mr`/`kept` outcome, 1 on `failed — …`.
- [ ] `engine status [<spec>]`, `status --waiting` (question, options, asked at, the exact `tmux-ctl engine signal <spec> approve|deny|fail` command), `events <spec>`, `resume` (spec §9 order: reconcile intent steps → due timers oldest first → drain inbox → policy check → re-watch or re-run running jobs), `signal <spec> approve|deny|fail [--note …]` (exit 2 `no open wait for <spec>`), `rebuild --check|--apply` (exit codes of Task 10); a bad subcommand exits 2 with a usage line.
- [ ] `tmux-ctl engine …` execs `node "${0:A:h:h}/engine/bin/engine.js" "$@"` with `TC_PROJECT="$FEEDKEY"` exported, dying `engine: node >= 22.13 is required` without node, exactly as `registry)` does; `tmux-ctl help` still prints the same number of header lines.
- [ ] `docs/superpowers/engine.json` is `{"test": "zsh tools/tests/all.zsh", "test_ok": [0, 4]}` (A4).
- [ ] CLI tests run `engine.js` as a child process with `TC_ENGINE_DIR` temp and `--backend fake` with a script file, covering each subcommand's exit code.

**Verify:** `cd engine && node --test test/engine_cli.test.js && cd .. && zsh bin/tmux-ctl engine bogus; test $? -eq 2`

```json:metadata
{"files": ["engine/lib/engine/cli.js", "engine/bin/engine.js", "engine/test/engine_cli.test.js", "docs/superpowers/engine.json", "bin/tmux-ctl", "engine/package.json", "docs/ARCHITECTURE.md"], "verifyCommand": "cd engine && node --test test/engine_cli.test.js && cd .. && zsh bin/tmux-ctl engine bogus; test $? -eq 2", "acceptanceCriteria": ["run with plan lookup, compile error exit 3, outcome exit codes", "status/waiting/events/resume/signal/rebuild", "tmux-ctl engine case with TC_PROJECT", "engine.json", "CLI tests per subcommand"], "modelTier": "standard"}
```

---

### Task 12: Crash, resume and isolation tests

**Goal:** Prove spec Testing's "Crash and resume", the durability kill points and the isolation leak check on real processes.

**Files:**
- Create: `engine/test/engine_resume.test.js`

**Acceptance Criteria:**
- [ ] A fake-backend run is killed (child process `engine.js run`, `SIGKILL` by pid) after each distinct event kind of the run in turn (one run per kill point, kill points read from a full uninterrupted run's event list); each `engine resume` reaches the same final state and the same event-kind sequence as the uninterrupted run (resume-only events such as `resumed` excluded), no job with a valid report runs twice, and `engine rebuild --check` exits 0 after every resume.
- [ ] A signal written before a kill and one written after are each applied once.
- [ ] A `deadline` and a `usage_reset` timer due while the engine was down fire once each on resume.
- [ ] Leak check: the test records `fs.readdirSync` of the real `~/.local/state/agent-board/engine` (or its absence) and `tmux -L agent-board list-sessions` before and after; both unchanged.
- [ ] Each kill-point iteration appends `<kill point> <ok|FAIL> <ms>` to a tally under the test's temp dir and prints it on failure.

**Verify:** `cd engine && node --test test/engine_resume.test.js` → all tests pass

```json:metadata
{"files": ["engine/test/engine_resume.test.js"], "verifyCommand": "cd engine && node --test test/engine_resume.test.js", "acceptanceCriteria": ["kill at each event kind resumes to same final state, no double job, rebuild check 0", "signals before and after a kill applied once", "timers due while down fire once", "leak check on real engine dir and tmux server", "per-iteration tally"], "modelTier": "standard"}
```

---

### Task 13: Real run on a scratch clone (part 1 done criterion)

**Goal:** `engine run` takes one small real spec from a committed plan to a merged-quality branch on a scratch clone of this repo with real workers and no lead turn in between (spec §5 last paragraph, Testing "Real run, part 1"), recorded as `docs/superpowers/notes/2026-11-23-engine-part-1-e2e.md`.

**Constraints:** Scratch clone under `/tmp/engine-e2e-<epoch>` (`git clone` of this branch's checkout, so it carries the real history); a tiny spec and two-task plan with `.tasks.json` committed there (one mechanical task, one standard; e.g. a pure helper and its test in a new file); `TC_ENGINE_DIR` and `TC_STATE` temp; workers run in the live tmux server's `agent-board-bg` session (visible, as the spec requires), closed by the engine; `--integration keep`. The run costs real tokens: it runs once; a failure is debugged with `superpowers-extended-cc:systematic-debugging` and fixed in the task that owns the module, then run again. Remove the scratch clone and its worktrees after recording.

**Files:**
- Create: `docs/superpowers/notes/2026-11-23-engine-part-1-e2e.md`

**Acceptance Criteria:**
- [ ] The note has sections `## Setup` (commands), `## Event log` (the full `tmux-ctl engine events <spec>` output), `## Windows` (each job's window name, opened and closed times from the events), `## Result` (branch head, `git log --oneline main..<branch>`, the plan's verify commands green on it, outcome `kept <branch>`), `## Rebuild` (`engine rebuild --check` rc 0).
- [ ] Every job window that opened was closed by the engine (no `<slug>·` window left: `tmux list-windows -a -F '#{window_name}' | grep -c '·'` before and after recorded).
- [ ] Real-state check: `tmux-ctl engine status` with the real `TC_ENGINE_DIR` unset prints no specs and creates nothing beyond an empty database (or the note records why it did).

**Verify:** `grep -c '^## ' docs/superpowers/notes/2026-11-23-engine-part-1-e2e.md` → `5`

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-23-engine-part-1-e2e.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/notes/2026-11-23-engine-part-1-e2e.md", "acceptanceCriteria": ["note with Setup, Event log, Windows, Result, Rebuild", "every job window closed", "real-state status check"], "modelTier": "standard"}
```

---

### Task 14: Full suites

**Goal:** No new failures on the project's suites (spec Testing, Suites).

**Files:**
- Test only.

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh` verdict line reports every job passing (rc 0 or 4), read from its own summary line.
- [ ] `cd engine && npm test` passes (its own summary `# fail 0`).

**Verify:** `zsh tools/tests/all.zsh > /tmp/engine-p1-all.out 2>&1; echo rc=$?; tail -3 /tmp/engine-p1-all.out`

**Steps:**
- [ ] Run the Verify command through `tmux-ctl run -t 1200 tests "…"` writing to the file; read `rc=` and the summary line; on a failure, report the failing job names to the lead (do not fix).

```json:metadata
{"files": [], "verifyCommand": "zsh tools/tests/all.zsh > /tmp/engine-p1-all.out 2>&1; echo rc=$?; tail -3 /tmp/engine-p1-all.out", "acceptanceCriteria": ["all.zsh rc 0 or 4 with every job passing", "engine npm test fail 0"], "modelTier": "mechanical"}
```

---

## Dependencies

Task 1 → 2, 4, 6, 7, 10. Task 2 → 3. Task 4 → 5. Tasks 3, 5, 6, 7 → 8. Task 7 → 9. Tasks 8, 9, 10 → 11. Task 11 → 12 → 13 → 14. Parallel-safe sets (disjoint files): {2, 4, 6, 7, 10} after 1; {3, 5} after 2 and 4; {9} beside 8. Tasks 5 and 11 both modify `bin/tmux-ctl` (different cases and header lines): 11 runs after 5.

## Execution handoff

Run with `superpowers-extended-cc:subagent-driven-development` together with `subagent-driven-development-extras`; the lead calls the Skill tool for it when this plan starts and asks nothing about the execution method.
