# Execution analytics: per-task records, weekly findings with recommendations

Date: 2026-11-12 · Decided with the user over Discord, 2026-11-12 (near-term item 1 of the "intelligence layer"
review: observe → understand → optimize)
Builds on: `docs/superpowers/specs/2026-11-10-queue-metrics-design.md` (merged: `board/metrics.py`,
`docs/superpowers/metrics/runs.jsonl`, `tmux-ctl metrics …`).
**Runs in two parts** (user, 2026-11-12), so per-task records start as early as possible and every later spec,
including the PCEE baseline runs, is recorded in full:
- **Part 1** (`#part-1`): §1 per-task records, §2 `metrics analyze`, §3 `metrics recommend`, plus
  `tmux-ctl metrics weekly --dry-run` printing the report to stdout. No Discord dependency; runs right after the
  spinner-rule spec.
- **Part 2** (`#part-2`): §4 the scheduled weekly Discord post and its buttons. Needs merged:
  `2026-11-11-discord-bridge-visibility-design.md` (outbox `post`, tiers), `2026-11-11-discord-controls-design.md`
  (buttons, audit) and `2026-11-12-discord-ops-bot-design.md` (#command-center).

## Problem

`runs.jsonl` holds rich per-spec records (tokens and $ by model and role, lead share, fix rounds, rulings, questions,
handoffs, bounces, manifest precision/recall, active minutes, usage limits), but:

- they reach the user only as one per-batch table in the morning report; nobody looks across weeks;
- there is nothing per task, so questions like "does Haiku need more fix rounds than Sonnet on mechanical tasks?" or
  "is Fable wasted on reviews of complete specs?" cannot be answered from data (the memory note
  `fable-routing-worth-it` was reached by hand from one run);
- nothing turns the numbers into a change to try.

## Decisions (user, 2026-11-12)

- **A weekly findings post** with trends, flags and **three concrete recommendations**, each with its evidence and a
  "file as idea" button. No board page in this spec.
- **Numbers by code, words by a model.** The model sees only the computed stats and every number it cites is
  checked against them.

## Design

### 1. Per-task records

`tmux-ctl metrics record <spec> …` also appends one line per plan task to
`docs/superpowers/metrics/tasks.jsonl` (committed with `runs.jsonl`, same rules):

`{spec, batch, task_id, subject, tier, model_mapped, model_used, escalated: bool, owner, started_at, ended_at,
active_s, tokens, usd, fix_rounds, findings: {critical, important, minor}, review_rounds, outcome}`

- `tier`, `model_mapped`: from the task's `json:metadata` and `docs/superpowers/model-routing.json`.
- `model_used`, `tokens`, `usd`: usage-index rows whose `agent_name` is the task's owner (and the owner's
  replacements, from the spawn records) between the task's `in_progress` and `completed` times; reviewers' rows for
  that task are counted separately as `review_tokens`, `review_usd`.
- `fix_rounds`, `findings`, `review_rounds`: from the ledger lines for that task (`progress.md`), the same parsing
  `metrics record` already does for the spec totals.
- `escalated`: the task's `modelTier` changed during the run (task metadata history in the ledger) or `model_used`
  differs from `model_mapped`.
- **Backfill:** `tmux-ctl metrics backfill-tasks` fills `tasks.jsonl` for past runs from their archived ledgers and
  whatever usage rows still exist; a task without usage rows gets `tokens: null` and `partial: true`.

### 2. `tmux-ctl metrics analyze [--since 7d|30d|<ISO>] [--json]`

Pure code over `runs.jsonl` and `tasks.jsonl` (all projects that have them: the repos listed by
`tmux-ctl overview --json`). Output `stats.json`:

- `trends`: this window vs the previous window of the same length: specs run, merged, failed; median and p90 $ per
  spec; median lead share; median fix rounds per spec; median elapsed and active time; questions and rulings per spec.
- `by_tier_model`: per (tier, model_used): tasks, median $ and tokens, median fix rounds, findings per task by
  severity, escalation rate, failure rate.
- `flags` (each with the rows that triggered it):
  - `overpowered`: a frontier-tier model on a task whose spec section had code in its steps (the plan step text
    contains a fenced code block) and which finished with 0 fix rounds;
  - `underpowered`: a (tier, model) with median fix rounds ≥ 2 over ≥ 5 tasks, or escalation rate ≥ 30%;
  - `costly_steps`: the 10 tasks with the highest $, with spec and subject;
  - `handoffs`: specs with handoffs and the $ in the hour around each relay vs the spec median per hour;
  - `forecast`: median manifest precision and recall, and the specs below 0.5 recall.
- Every number in `stats.json` has a stable key path (`trends.median_usd_per_spec.current`); the recommendation check
  uses these.

### 3. Recommendations

- `tmux-ctl metrics recommend [--since 7d]`: runs `claude -p --model sonnet --effort medium` with
  `claude/analytics.md` as the prompt, `stats.json` as the only input (Read on that one file; no other tools), and asks
  for exactly three items `{title, change, expected_effect, evidence: [{key, value}], risk}` in `recommend.json`.
- The script checks each item: every `evidence.key` exists in `stats.json` and its `value` equals the stats value
  (numbers compared after rounding to the stats' precision). An item that fails is dropped and logged; fewer than three
  survivors are posted as they are, with `(n of 3 passed the evidence check)`.
- `claude/analytics.md` tells the model: recommend changes to routing, plan granularity, review setup, team shape or
  workflow rules; each must be a small, testable change; never recommend editing the orchestrator or its own prompt
  (the self-modification guard idea); prefer changes whose effect the next week's numbers can show.

### 4. The weekly post

- launchd `com.user.agent-board-analytics`, Mondays 09:00 local; `tmux-ctl metrics weekly [--dry-run]` runs
  `analyze --since 7d`, `recommend`, and writes one outbox `post` (tier `progress`, no ping):
  - a code block table of `trends` (metric, last week, this week, change);
  - the flags, one line each with a deep link where the spec has a thread;
  - the recommendations, each with its evidence values and a button `File as idea`
    (`ab:analytics:idea:<week>:<n>`; files `tmux-ctl idea "<title>: <change> (evidence: …)"` once, audited);
  - `stats.json` attached.
- Destination: #command-center when the ops bridge is configured; else each project's home channel gets the same post
  restricted to its own rows.
- No runs in the window: nothing is posted; the log says so.
- The weekly run is recorded with `tmux-ctl metrics` as kind `analytics` (its tokens and $).
- `TC_ANALYTICS=0` or `analytics.off` in the state dir turns the schedule off.

## Error handling

- Missing usage index (rebooted TMPDIR): tokens and $ come out `null`; stats skip null values and report
  `coverage: <n>/<m> tasks with cost data`.
- Model run fails or times out (10 min): the post goes out with trends and flags only and the line
  `recommendations unavailable: <reason>`.

## Testing

- `tasks.jsonl` lines from a fixture ledger plus fixture usage rows: owner matching, replacement owners, reviewer
  split, escalation detection, partial rows.
- `analyze` on fixture runs/tasks: each trend, each flag's trigger and non-trigger, stable key paths, coverage line.
- Recommendation check: valid item kept; unknown key dropped; wrong value dropped; count line.
- Weekly: `--dry-run` op shape, per-project restriction, no-runs path, button filing once.
- The model step is a fake `claude` in tests; one real `metrics weekly --dry-run` on this repo's real metrics is the
  user-gate check.

## Out of scope

- A board page with charts.
- Applying recommendations automatically (experiments framework idea, after the engine).
