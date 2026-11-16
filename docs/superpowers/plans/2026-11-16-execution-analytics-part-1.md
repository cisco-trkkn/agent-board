# Execution analytics, part 1: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record one line per plan task in `tasks.jsonl`, and add `tmux-ctl metrics backfill-tasks`, `analyze`, `recommend` and `weekly --dry-run`, so that cross-week findings and three evidence-checked recommendations can be printed from the run logs.

**Architecture:** Three new pure-ish modules sit next to `board/metrics.py`:
- `board/metrics_tasks.py` turns a plan's ledger, `.tasks.json`, routing file and usage rows into task lines.
- `board/metrics_analyze.py` turns `runs.jsonl` and `tasks.jsonl` from every project into `stats.json`.
- `board/metrics_recommend.py` runs `claude -p` over `stats.json`, checks the evidence, and renders the weekly text.

`metrics.py` keeps the CLI and wires the new subcommands in. `tmux-ctl metrics` already passes every argument through (`bin/tmux-ctl:632`), so `bin/tmux-ctl` changes only in its help comment.

**Tech Stack:** Python 3 stdlib (unittest), sqlite usage index (`board/usage.py`), `claude -p`.

**Spec:** `docs/superpowers/specs/2026-11-12-execution-analytics-design.md#part-1`. This covers §1, §2, §3 and `weekly --dry-run` only. §4's launchd job, outbox post and buttons are part 2.

## Global Constraints

- **Logs.** `tasks.jsonl` lives beside `runs.jsonl` in `metrics.mdir(repo)` (the main checkout's `docs/superpowers/metrics/`). The rules are the same as for `runs.jsonl`:
  - append-only;
  - one JSON object per line;
  - readers take the last line per `(batch, spec, task_id)`;
  - a malformed line is skipped and counted;
  - no session ids, no prompts, no absolute paths.
  - `owner` (a teammate name) is allowed: the spec lists it.
- **Failures.** A failing new subcommand prints the single line `metrics: <sub>: <reason>` to stderr and exits 1, through `metrics.main`'s existing handler. No traceback.
- **Tests and existing code.** Tests never read the real usage index, the real `~/.claude`, or the real state dir. Every test sets `TC_STATE`, `HOME` and `TC_LINEAGE` to temp dirs, or passes explicit paths, as `board/tests/test_metrics_record_usage.py` does. The 9 existing `board/tests/test_metrics_*.py` files must keep passing.
- **Line endings.** Commit messages are conventional with a scope (`feat(metrics): …`). End each one with the attribution trailer your harness specifies.

### Metric definitions (every task cites these and does not restate them)

- **M-run:** the last `kind:"run"` line per `(batch, spec)` (`metrics.last_runs`). A run is in a window when its `ended_at` falls inside it.
- **M-task:** the last `tasks.jsonl` line per `(batch, spec, task_id)`. A task is in a window when its run (same batch and spec) is in the window.
- **M-window:** `--since 7d|30d|<ISO date or datetime>`. The current window is `[since, now]`. The previous window is `[since - (now - since), since)`. The default is `7d`.
- **M-failed:** run `outcome == "failed"`; task `outcome != "complete"`.
- **M-median:** `statistics.median` over the non-null values. With no values it is `null`. p90 is the nearest-rank value at `ceil(0.9·n)`.
- **M-change:** `current - previous` when both are non-null, else `null`.
- **M-coverage:** in-window tasks with non-null `usd`, out of all in-window tasks. Written as `coverage: {"with_cost": n, "tasks": m}`; the text line reads `coverage: n/m tasks with cost data`.
- **M-rounding:** usd to 2 decimals; ratios and rates (lead share, precision, recall, escalation and failure rates) to 4; medians of counts and seconds to 1. Each value is rounded once, when stats.json is written. The evidence check compares a cited number after rounding it to the number of decimals the stats value has in stats.json.
- **M-frontier-model:** a `model_used` whose family is `fable` or `opus`. Family = the first of `haiku|sonnet|opus|fable` found in the model string.

### Rulings (lead, recorded for the morning report)

- **R1, task windows.** The spec says "between the task's `in_progress` and `completed` times", but nothing stores those times durably. The tasks-window state lives in `$TC_STATE/taskwin/<project>.json` and is rewritten on every session. So rows go to tasks by owner and ledger order instead. A usage row whose `agent_name` is one of a task's owners belongs to the first of that owner's tasks (in ledger order of their `complete` lines) whose end ≥ the row's time. Rows after the owner's last end go to its last task.
  - A task's end is the committer time of the last sha in its last `commits A..B` range. Without one, the end is the run's `ended_at`.
  - `started_at` and `ended_at` are the first and last attributed row times.
  - Replacement owners use the same name (the handoff skill respawns a teammate under its own name), so they need no spawns lookup.
  - Cost if wrong: a teammate that worked two tasks at once has its rows split by commit time and not by task.
- **R2, handoffs flag.** The "$ in the hour around each relay" figure needs usage rows, which `analyze` does not read (it is pure code over the two logs). Instead, the flag lists specs with `handoffs > 0`, giving `usd / (active_min/60)` against the window median of the same figure. Cost if wrong: a coarser flag. Part 2 can refine it.
- **R3, overpowered flag.** "The spec section had code in its steps" is read as: the task's `.tasks.json` description has a fenced code block other than the `json:metadata` fence. This is stored per task as `code_in_steps`.
- **R4, project list.** The project list comes from `python3 -I board/overview.py --json` (`projects[].path`), with a 30 s timeout. If it fails, `analyze` uses the current repo alone and sets `projects_source: "repo-only"`. Tests pass `--projects DIR…`.
- **R5, stats.json location.** `analyze` writes `$TC_STATE/analytics/stats.json`, or `--out PATH`. `recommend` reads that file, or `--stats PATH`, and writes `recommend.json` beside it.

**User decisions (already made):**
- "A weekly findings post … three concrete recommendations, each with its evidence" (spec, Decisions).
- "Numbers by code, words by a model. The model sees only the computed stats and every number it cites is checked against them."
- Queue answer: integration merge, no push.

---

### Task 1: Per-task lines from ledger, plan tasks and usage rows

**Goal:** `board/metrics_tasks.py` builds the spec's per-task line from a ledger text, a `.tasks.json` text, the routing map and a list of usage rows.

**Files:**
- Create: `board/metrics_tasks.py`
- Test: `board/tests/test_metrics_tasks.py`

**Acceptance Criteria:**
- [ ] `parse_ledger(progress)` returns, per task number: `owners` (in order); `dispatch_models` (model names from `dispatched <name> (<model>, …)`); `fix_rounds` (the highest N in `fix round N`); `findings {critical, important, minor}`; `review_rounds`; `complete` (bool); `commit_end` (the last sha of the last `commits A..B`).
- [ ] `build_task_lines(spec, batch, tasks_text, progress, routing, rows, commit_time, run_end)` returns one dict per plan task. Each dict has exactly these keys: `spec, batch, task_id, subject, tier, model_mapped, model_used, escalated, owner, started_at, ended_at, active_s, tokens, usd, review_tokens, review_usd, fix_rounds, findings, review_rounds, outcome, code_in_steps, partial`.
- [ ] Rows go to tasks by rule R1. Rows of an agent named in a task's `review dispatched` line go to that task's `review_tokens`/`review_usd` and never to `tokens`.
- [ ] A task with no attributed rows has `tokens: null, usd: null, model_used: null, partial: true`.
- [ ] `escalated` is true when any dispatch model's family or `model_used`'s family differs from `model_mapped`'s family.
- [ ] The test fixture is built from real ledger lines copied from `docs/superpowers/ledgers/2026-11-16-discord-replaces-telegram/progress.md` and `docs/superpowers/ledgers/2026-11-11-queue-metrics/progress.md` (named in a comment). It is not invented.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_tasks.py' -v`. Every test below must come back OK.

**Steps:**

- [ ] **Step 1: Read the real ledgers.** Read the two named `progress.md` files and record every line shape that names a task. The shapes seen across `docs/superpowers/ledgers/*/progress.md` (counts from `grep`) are:
  - `Task N: dispatched <name> (<model>, base <sha>)`
  - `Task N: fix round K/5 dispatched (Important: …)`
  - `Task N: fix round K/5 — commits A..B; …`
  - `Task N: review dispatched <name> (A..B)` and `review dispatched to <name>`
  - `Task N: re-review …`
  - `Task N: minor (deferred): …`
  - `Task N: Important: …` / `Critical: …`
  - `Task N: complete (commits A..B, review clean)`

- [ ] **Step 2: Write failing tests** in `board/tests/test_metrics_tasks.py`. Use a fixture ledger of real lines covering two tasks done by one owner (`dc-launch` did Tasks 1 and 2 in the discord ledger) and one task with a fix round. Use fixture rows shaped like `usage` rows: dicts with `ts, model, agent_name, input, output, cache_read, cache_write_5m, cache_write_1h`, priced through `usage.call_cost` with a fixture price map. Cases, each with the mutation that must make it fail:
  - `test_shared_owner_rows_split_by_commit_end`: removing the end-time comparison sends every row to Task 1, and this fails.
  - `test_reviewer_rows_not_in_task_tokens`: dropping the reviewer filter makes `tokens` include review rows, and this fails.
  - `test_no_rows_partial`: forcing `partial` to False fails.
  - `test_escalated_by_dispatch_model`: a mechanical task dispatched to `sonnet`. Comparing only `model_used` fails.
  - `test_fix_rounds_max_not_count`: `fix round 1/5 dispatched` plus `fix round 1/5 — commits` gives 1. Counting lines gives 2 and fails.
  - `test_findings_counts`: two `minor (deferred)`, one `Important:` line and one fix-round dispatch with `(Important: …)` give `{critical:0, important:2, minor:2}`.
  - `test_code_in_steps`: a description with a `python` fence is true. One with only the `json:metadata` fence is false.
  - `test_keys_exact`: the line's key set equals the AC's list.

- [ ] **Step 3: Run them to see RED.** the Verify command fails with `ModuleNotFoundError: No module named 'metrics_tasks'`.

- [ ] **Step 4: Implement `board/metrics_tasks.py`.** The parsing is the non-obvious part; use these patterns:

```python
TASK = re.compile(r"^Task (\d+): (.*)$")
DISPATCH = re.compile(r"^(?:fix round \d+(?:/\d+)? )?dispatched (?:to )?([A-Za-z0-9_-]+)(?: \((haiku|sonnet|opus|fable|inherit)\b)?")
REVIEW = re.compile(r"review dispatched (?:to )?([A-Za-z0-9_-]+)")
FIX = re.compile(r"fix round (\d+)")
COMMITS = re.compile(r"commits ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})")
FAMILIES = ("haiku", "sonnet", "opus", "fable")

def family(model):
    m = (model or "").lower()
    return next((f for f in FAMILIES if f in m), None)
```

  - **Findings:** `minor (deferred)` adds 1 to minor. A rest-of-line starting `Critical:` or `Important:` adds 1 to that severity. A `fix round … dispatched (Important: …)` line adds 1 important.
  - **Review rounds:** `review_rounds` counts `review dispatched` plus `re-review` lines.
  - **Task ids** come from each plan task's `subject` prefix `Task N:`. A subject without one uses its 0-based `id` + 1.
  - **`tier`** is the task's `json:metadata` `modelTier` (reuse `metrics._fence`). `model_mapped` is `routing[tier]`.
  - **`model_used`** is the model with the most tokens among the task's rows.
  - **`active_s`** is 60 × the number of distinct minutes among the task's rows.
  - **`outcome`** is `complete` when the ledger has a `complete` line, else the tasks.json `status`.
  - **`owner`** is the last owner named. Times are ISO UTC (`metrics.utc`).

- [ ] **Step 5: GREEN.** Run the Verify command and see every test OK.

- [ ] **Step 6: Commit.**
  `git add board/metrics_tasks.py board/tests/test_metrics_tasks.py && git commit -m "feat(metrics): per-task lines from ledger and usage rows"`

```json:metadata
{"files": ["board/metrics_tasks.py", "board/tests/test_metrics_tasks.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_tasks.py' -v", "acceptanceCriteria": ["parse_ledger fields per task", "exact key set", "R1 row attribution with reviewer split", "partial when no rows", "escalated by family", "fixture from real ledger lines"], "modelTier": "standard"}
```

### Task 2: `record` writes tasks.jsonl; `backfill-tasks`

**Goal:** `tmux-ctl metrics record` appends the spec's task lines to `tasks.jsonl`, and `tmux-ctl metrics backfill-tasks` fills them for past runs.

**Files:**
- Modify: `board/metrics.py` (`cmd_record`, `_parser`, `main`'s dispatch dict, `SUBS`, the module docstring; new `tasks_path`, `read_tasks`, `task_lines_for_run`, `cmd_backfill_tasks`)
- Test: `board/tests/test_metrics_tasks_log.py`

**Acceptance Criteria:**
- [ ] After `record`, `tasks.jsonl` holds one line per plan task, built by `metrics_tasks.build_task_lines`, with rows from the same usage connection `record` uses (agent rows in the spec's window with `agent_name` set) and `routing` from the repo's `docs/superpowers/model-routing.json`. A missing routing file means `model_mapped: null`.
- [ ] If building the task lines raises, `record` still writes the run line, prints `metrics: record: task lines skipped: <reason>` to stderr and exits 0. The task half never fails the run record.
- [ ] `backfill-tasks [--log PATH] [--usage-db PATH] [--no-ingest]` writes task lines for every run line in `runs.jsonl` whose `(batch, spec)` has none yet. It finds the plan with `find_plan`, the ledger under `docs/superpowers/ledgers/<plan basename>/progress.md`, the window from the run's `started_at`/`ended_at`, and commit times from `git show -s --format=%ct`. It prints `backfilled tasks for N specs (M tasks, P partial)`. A second run adds nothing.
- [ ] `--log PATH` redirects `tasks.jsonl` (`TASKS_OVERRIDE`) the same way `backfill --log` redirects the run log. The tests never write the real file.
- [ ] Every line passes the privacy checks of `board/tests/test_metrics_backfill_privacy.py`: no `/Users/`, no home path, no UUID, no absolute path value.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_tasks_log.py' -v && python3 -m unittest discover -s board/tests -p 'test_metrics_*.py'`. All OK.

**Steps:**

- [ ] **Step 1: Write failing tests** with the temp-repo fixture pattern of `board/tests/test_metrics_record_usage.py`: a git repo with a plan, `.tasks.json`, a ledger `progress.md` and a usage sqlite built with `usage.connect`. Cases and their mutations:
  - `test_record_appends_task_lines`
  - `test_record_survives_task_error`: patch `metrics_tasks.build_task_lines` to raise. The run line still exists and rc is 0. Letting the exception through fails.
  - `test_backfill_tasks_idempotent`: removing the already-have check doubles the lines and fails.
  - `test_backfill_tasks_log_override`
  - `test_privacy`: reuse the regexes from the privacy test.
- [ ] **Step 2: RED.** The Verify command fails on the unknown subcommand and the missing `tasks.jsonl`.
- [ ] **Step 3: Implement** the changes listed under Files. `tasks_path(repo)` is `Path(TASKS_OVERRIDE) if TASKS_OVERRIDE else mdir(repo) / "tasks.jsonl"`. `read_tasks` mirrors `read_log`. Rows for the task half come from `usage._rows(conn, "select * from calls where ts>=? and ts<=? and agent_name is not null", (lo, hi))`, filtered to rows whose `cwd` is under the spec's worktree dirs or the main root (reuse `worktree_dirs`, `main_root`).
- [ ] **Step 4: GREEN.** Run Verify.
- [ ] **Step 5: Commit.**
  `git add board/metrics.py board/tests/test_metrics_tasks_log.py && git commit -m "feat(metrics): record writes tasks.jsonl; backfill-tasks"`

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_tasks_log.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_tasks_log.py' -v && python3 -m unittest discover -s board/tests -p 'test_metrics_*.py'", "acceptanceCriteria": ["record appends task lines", "task-half failure never fails record", "backfill-tasks idempotent with summary line", "--log override", "privacy checks pass"], "modelTier": "standard"}
```

### Task 3: `metrics analyze` → stats.json

**Goal:** `tmux-ctl metrics analyze [--since 7d|30d|<ISO>] [--json] [--out PATH] [--projects DIR…] [--tasks-log PATH]` computes trends, by_tier_model, flags and coverage over every project's logs and writes `stats.json`.

**Files:**
- Create: `board/metrics_analyze.py`
- Modify: `board/metrics.py` (`_parser`, dispatch, `SUBS`)
- Test: `board/tests/test_metrics_analyze.py`

**Acceptance Criteria:**
- [ ] `stats.json` has top-level keys `window {since, until, previous_since}`, `projects`, `projects_source`, `trends`, `by_tier_model`, `flags`, `coverage`. All numbers follow M-rounding.
- [ ] `trends` has these keys, each `{current, previous, change}` (M-change), computed per M-run, M-window, M-median and M-failed:
  - `specs_run`, `specs_merged`, `specs_failed`
  - `median_usd_per_spec`, `p90_usd_per_spec`
  - `median_lead_share`, `median_fix_rounds_per_spec`
  - `median_elapsed_s`, `median_active_min`
  - `questions_per_spec`, `rulings_per_spec` (medians)
- [ ] `by_tier_model` is keyed `"<tier>|<model_used family or 'unknown'>"`. Each entry has: `tasks`, `median_usd`, `median_tokens`, `median_fix_rounds`, `findings_per_task {critical, important, minor}`, `escalation_rate`, `failure_rate`.
- [ ] `flags` holds the five keys from spec §2 (with R2 for `handoffs` and R3 for `overpowered`). Each is a list of rows carrying the triggering values. `underpowered` triggers at median fix rounds ≥ 2 over ≥ 5 tasks, or escalation rate ≥ 0.30. `costly_steps` is the top 10 by usd. `forecast` holds `{median_precision, median_recall, below_half: [...]}`.
- [ ] Each flag has one trigger test and one non-trigger test at the boundary: 4 tasks with median 2 does not trigger, 5 does; an escalation rate of 0.29 does not trigger, 0.30 does. Each test names its mutation in a comment (for example, `>=` → `>` fails the 5-task case).
- [ ] `metrics_analyze.lookup(stats, "trends.median_usd_per_spec.current")` resolves every key path. `by_tier_model` keys contain `|`, never `.`, so dotted paths stay unambiguous.
- [ ] `--tasks-log PATH` replaces the current repo's `tasks.jsonl` (for scratch runs); a test covers it.
- [ ] With no runs in either window, the output is still valid with `specs_run.current == 0`. `--json` prints the stats; without it, one summary line: `analyzed <n> specs, <m> tasks across <p> projects → <path>`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_analyze.py' -v`, which must be OK.

**Steps:**

- [ ] **Step 1: Write failing tests.** Use fixture `runs.jsonl` and `tasks.jsonl` written into two temp project dirs under `docs/superpowers/metrics/`, passed by `--projects`, with `ended_at` values placed in the current and previous 7-day windows relative to a fixed `now` (`analyze(..., now=...)`). Cover each trend key, each flag's trigger and non-trigger, `lookup` on every leaf (walk the dict), the coverage numbers, and the empty case.
- [ ] **Step 2: RED.** Run the Verify command.
- [ ] **Step 3: Implement.** Write the pure `analyze(projects, since_ts, now) -> dict`, plus a CLI wrapper that resolves the projects (R4) and the output path (R5). Reuse `metrics.last_runs` and `metrics._epoch`. Read each project's logs from `<dir>/docs/superpowers/metrics/`.
- [ ] **Step 4: GREEN.** Run the Verify command.
- [ ] **Step 5: Commit.** Run `git add board/metrics_analyze.py board/metrics.py board/tests/test_metrics_analyze.py` and commit with `feat(metrics): analyze`.

```json:metadata
{"files": ["board/metrics_analyze.py", "board/metrics.py", "board/tests/test_metrics_analyze.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_analyze.py' -v", "acceptanceCriteria": ["stats.json top-level keys", "every trend key current/previous/change", "by_tier_model fields", "five flags with boundary trigger/non-trigger tests", "lookup resolves every leaf", "empty-window output"], "modelTier": "standard"}
```

### Task 4: `metrics recommend` with the evidence check

**Goal:** `tmux-ctl metrics recommend [--since 7d] [--stats PATH]` asks `claude -p` for exactly three recommendations over `stats.json` alone, and keeps only the items whose evidence matches stats.json.

**Files:**
- Create: `claude/analytics.md` (the prompt), `board/metrics_recommend.py`
- Modify: `board/metrics.py` (parser and dispatch)
- Test: `board/tests/test_metrics_recommend.py`, `board/tests/fixtures/fake_claude_recommend.sh`

**Acceptance Criteria:**
- [ ] When `--stats` is not given, the command runs `analyze --since <since>` first. It then runs this command, with cwd set to the stats file's directory, a 600 s timeout, and the prompt on stdin:

  ```
  claude -p --model sonnet --effort medium --tools Read --allowedTools Read --permission-mode dontAsk --no-session-persistence --strict-mcp-config --output-format json
  ```

  The prompt is `claude/analytics.md` plus the stats path. These flags were probed with `claude --help` on 2026-11-16: `--effort`, `--tools`, `--allowedTools`, `--no-session-persistence`, `--strict-mcp-config` and `--output-format` all exist. The `claude` binary comes from `$TC_CLAUDE_BIN`, else `claude`.
- [ ] The model's answer is parsed from the JSON result's `result` text: the first JSON array or the `{"items": [...]}` object in it. Each item must have `{title, change, expected_effect, evidence: [{key, value}], risk}`. The parsed items are written to `recommend.json` beside stats.json as `{items, dropped: [{title, reason}], passed, asked: 3}`.
- [ ] The evidence check: an item is kept only if every `evidence.key` resolves with `metrics_analyze.lookup`, and its `value` equals the stats value after rounding to the stats value's decimals (M-rounding). A string value compares exactly. Each failing item is dropped with its reason, and the reason is printed to stderr as `metrics: recommend: dropped "<title>": <reason>`.
- [ ] stdout ends with `(n of 3 passed the evidence check)`.
- [ ] If the model run fails or times out, rc is 0 and `recommend.json` is `{items: [], unavailable: "<reason>"}`.
- [ ] `claude/analytics.md` says all of the following, each checked by a `grep` in the test:
  - recommend changes to routing, plan granularity, review setup, team shape or workflow rules;
  - each recommendation is small and testable;
  - never recommend editing the orchestrator or its own prompt;
  - prefer changes that next week's numbers can show;
  - cite only key paths that exist in stats.json, with their exact values;
  - return exactly three items in the schema above.
- [ ] Tests use the fake `claude` (`TC_CLAUDE_BIN`). It prints a canned JSON result chosen by an env var, so that one test has 3 valid items, one has an unknown key, one has a wrong value (and one a value correct only after rounding, which is kept), and one fails with exit 1.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_recommend.py' -v`. Expect OK.

**Steps:**

- [ ] **Step 1: Write the failing tests and the fake.** Write `board/tests/fixtures/fake_claude_recommend.sh` (`#!/bin/sh`; it echoes `$FAKE_RECOMMEND_OUT`'s file contents and exits `${FAKE_RECOMMEND_RC:-0}`). Each test has a mutation that must make it fail:
  - `test_three_valid_kept`
  - `test_unknown_key_dropped`: skip the lookup and this fails.
  - `test_wrong_value_dropped`
  - `test_rounded_value_kept`: compare unrounded and this fails.
  - `test_count_line`
  - `test_model_failure_unavailable`
  - `test_argv_flags`: the fake also writes its argv to `$FAKE_ARGV`; assert every flag listed above.
  - `test_prompt_rules`: the greps listed above.
- [ ] **Step 2: Watch them go RED.**
- [ ] **Step 3: Implement it, and write `claude/analytics.md`.**
- [ ] **Step 4: Run the Verify command and confirm GREEN.**
- [ ] **Step 5: Commit** with `git add claude/analytics.md board/metrics_recommend.py board/metrics.py board/tests/test_metrics_recommend.py board/tests/fixtures/fake_claude_recommend.sh` and the message `feat(metrics): recommend with evidence check`.

```json:metadata
{"files": ["claude/analytics.md", "board/metrics_recommend.py", "board/metrics.py", "board/tests/test_metrics_recommend.py", "board/tests/fixtures/fake_claude_recommend.sh"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_recommend.py' -v", "acceptanceCriteria": ["claude -p argv as probed", "recommend.json shape", "evidence check keeps/drops with rounding", "count line", "failure → unavailable, rc 0", "prompt rules grep"], "modelTier": "standard"}
```

### Task 5: `metrics weekly --dry-run` report text and docs

**Goal:** `tmux-ctl metrics weekly --dry-run [--since 7d]` runs analyze and recommend and prints the weekly report to stdout. The help and docs name the new subcommands.

**Files:**
- Modify: `board/metrics_recommend.py` (adds `weekly_text(stats, rec)`), `board/metrics.py` (`weekly` subcommand), `bin/tmux-ctl` (help comment under `metrics`), `docs/superpowers/metrics/README.md` if it exists, else the metrics section of `README.md`
- Test: `board/tests/test_metrics_weekly.py`

**Acceptance Criteria:**
- [ ] The text has these parts, in order:
  - a header `Execution analytics, <since date> → <until date>`;
  - a fenced code block table with columns `metric | last week | this week | change`, one row per `trends` key;
  - `Flags:`, one line per flag row (`- overpowered: <spec> task <id> <subject> (<model>, 0 fix rounds)` and so on), or `Flags: none`;
  - `Recommendations:`, each item numbered with its title, change, expected effect, risk, and an evidence list of `key = value`;
  - then `(n of 3 passed the evidence check)`, or `recommendations unavailable: <reason>`;
  - the coverage line and the stats path last.
- [ ] With no runs in the current window, it prints `no runs in the window; nothing to post` and does not run the model. The test asserts the fake claude was not called.
- [ ] `weekly` without `--dry-run` exits 1 with `metrics: weekly: posting needs part 2 (discord bridge); use --dry-run`.
- [ ] `bin/tmux-ctl`'s help comment lists `backfill-tasks`, `analyze`, `recommend` and `weekly --dry-run`. `SUBS` in metrics.py lists them too.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_weekly.py' -v && python3 -m unittest discover -s board/tests` → OK

**Steps:**

- [ ] **Step 1: Write the failing tests** with the fixtures from Tasks 3 and 4. Cases and their mutations:
  - `test_sections_in_order`
  - `test_no_runs_skips_model`: calling recommend unconditionally fails this test.
  - `test_unavailable_line`
  - `test_without_dry_run_refuses`
  - `test_help_lists_subs`: grep `bin/tmux-ctl` and `metrics.SUBS`.
- [ ] **Step 2: Run them and see RED.**
- [ ] **Step 3: Implement the subcommand and update the docs.**
- [ ] **Step 4: Run Verify and see GREEN.**
- [ ] **Step 5: Commit** with `feat(metrics): weekly --dry-run report`.

```json:metadata
{"files": ["board/metrics_recommend.py", "board/metrics.py", "bin/tmux-ctl", "board/tests/test_metrics_weekly.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_weekly.py' -v && python3 -m unittest discover -s board/tests", "acceptanceCriteria": ["section order", "no-runs path skips model", "unavailable line", "non-dry-run refuses", "help and SUBS list new subs"], "modelTier": "standard"}
```

### Task 6: Real-state e2e on this repo's metrics

**Goal:** Run backfill-tasks, analyze and weekly --dry-run once against this repo's real ledgers, real usage index and real `runs.jsonl`, without writing the real `tasks.jsonl`. Record the evidence.

**Files:**
- Create: `docs/superpowers/notes/2026-11-16-execution-analytics-e2e.md`

**Acceptance Criteria:**
- [ ] `tmux-ctl metrics backfill-tasks --log <scratch>/tasks.jsonl` runs on the real repo with the real usage index. The note quotes its summary line, gives the count of lines with `partial: true`, and quotes three sample lines (privacy checked: run `grep -c /Users/` on the file and give the count, which must be 0).
- [ ] `tmux-ctl metrics analyze --since 30d --out <scratch>/stats.json --tasks-log <scratch>/tasks.jsonl` runs against the real `runs.jsonl` plus the scratch `tasks.jsonl`. The note quotes the summary line, the coverage numbers and every flag's row count.
- [ ] `tmux-ctl metrics weekly --dry-run --since 30d` runs once with the real `claude`. This is the one real model run. The note pastes the whole output and says how many of 3 items passed.
- [ ] Afterwards, `git -C <main checkout> status --short docs/superpowers/metrics/` is empty: the real logs were not touched.

**Verify:** `test -s docs/superpowers/notes/2026-11-16-execution-analytics-e2e.md && grep -c 'passed the evidence check\|recommendations unavailable' docs/superpowers/notes/2026-11-16-execution-analytics-e2e.md`. The count must be at least 1.

**Steps:**

- [ ] **Step 1:** Make a scratch dir with `mktemp -d`.
- [ ] **Step 2:** Run the three commands from the Acceptance Criteria.
- [ ] **Step 3:** Write the note.
- [ ] **Step 4:** Check the real logs are untouched.
- [ ] **Step 5:** Commit: `docs(metrics): execution analytics real-state e2e`.

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-16-execution-analytics-e2e.md"], "verifyCommand": "test -s docs/superpowers/notes/2026-11-16-execution-analytics-e2e.md && grep -c 'passed the evidence check\\|recommendations unavailable' docs/superpowers/notes/2026-11-16-execution-analytics-e2e.md", "acceptanceCriteria": ["backfill-tasks on real ledgers into scratch log, privacy count 0", "analyze on real runs.jsonl, coverage and flag counts quoted", "one real weekly --dry-run pasted", "real metrics files untouched"], "modelTier": "standard"}
```

### Task 7: User gate: read the real weekly report

**Goal:** You read the real `weekly --dry-run` output in the e2e note and judge whether the findings and recommendations are useful.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the spec ("one real `metrics weekly --dry-run` on this repo's real metrics is the user-gate check"). It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Read: `docs/superpowers/notes/2026-11-16-execution-analytics-e2e.md`

**Acceptance Criteria:**
- [ ] You have read the pasted weekly output and replied "useful", or listed what to change.

**Verify:** your reply in the conversation (in queue mode this waits for the morning report).

```json:metadata
{"files": [], "verifyCommand": "user reply on the e2e note's weekly output", "acceptanceCriteria": ["user read the real weekly --dry-run output and answered useful or listed changes"], "modelTier": "mechanical", "userGate": true, "tags": ["user-gate"]}
```
