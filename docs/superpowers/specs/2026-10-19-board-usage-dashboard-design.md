# Board usage dashboard — design

Date: 2026-10-19 · Ideas group B (from `~/.claude/ideas/agent-board.md`): a usage/cost dashboard
that replaces the board's Activity drawer.

## Goal

From the Agent Board, the user sees what each project's agents cost (as an API-equivalent
estimate), which live agents need attention (context nearly full, burning fast, expensive, or an
expensive model on cheap work), and where the spend went: over time, by role, by model and by
branch.

## Decisions

- **Cost unit:** API-equivalent dollars, always labelled "API-equivalent estimate", never presented
  as the user's bill.
- **Alerts:** context nearly full, burn rate, session total, expensive model on cheap work.
- **Breakdowns:** over time, by agent role, by model, by plan/branch.
- **Drawer:** Usage first, Runs as a second tab. The command feed is dropped.
- **Approach:** an incremental transcript indexer into SQLite (not cost-state records only, not
  Claude Code's OTel export).

## Data source

Transcripts: `~/.claude/projects/<cwd-slug>/*.jsonl` plus subagent files
`~/.claude/projects/<cwd-slug>/<sessionId>/subagents/agent-*.jsonl` (≈340 files, ≈730 MB today).

- An assistant line carries `message.model`, `message.usage` (`input_tokens`, `output_tokens`,
  `cache_read_input_tokens`, `cache_creation_input_tokens`, and
  `cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`), `requestId`,
  `timestamp`, `cwd`, `sessionId`, `gitBranch`, `effort`, `isSidechain`. Teammate lines also carry
  `agentName` and `teamName`.
- `type: "cost-state"` records carry `totalCostUSD` and `modelUsage{model: {…, costUSD}}`,
  cumulative per session, plus `hasUnknownModelCost`. They are authoritative where present.

## Section 1 — Indexer and cost model: `board/usage.py`, `board/prices.json`

**Store.** `$TC_STATE/usage.sqlite` (stdlib `sqlite3`, WAL mode). Tables:

| Table | Columns |
| --- | --- |
| `calls` | `request_id` PK, `session_id`, `ts` (epoch s), `model`, `effort`, `agent_name`, `team_name`, `git_branch`, `cwd`, `sidechain` (0/1), `subagent_file` (0/1), `input`, `output`, `cache_read`, `cache_write_5m`, `cache_write_1h` |
| `cost_state` | `session_id` PK, `ts`, `total_usd`, `model_usage` (JSON), `unknown_model` (0/1) — latest record per session wins |
| `files` | `path` PK, `inode`, `size`, `offset`, `bad_lines` |

A usage line without `requestId` is keyed `<sessionId>:<line offset>`. When
`cache_creation` has no 5m/1h split, the whole `cache_creation_input_tokens` counts as 5m.

**Prices.** `board/prices.json`: per model id, `input`, `output`, `cache_read`, `cache_write_5m`,
`cache_write_1h` ($/MTok) and `context` (tokens). Seed values from the claude-api skill (cached
2026-10-06):

| Model | Input | Output | Cache read | Context |
| --- | --- | --- | --- | --- |
| Fable 5.1 / 5 | 10 | 50 | 0.25 | 1M |
| Opus 5.5 | 4 | 20 | 0.20 | 1M |
| Opus 5 / 4.8 / 4.7 / 4.6 | 5 | 25 | 0.25 (family ratio) | 1M |
| Sonnet 5.5 | 2 | 10 | 0.10 (fitted, 67 sessions) | 1M |
| Sonnet 5 | 2 | 10 | 0.10 (family ratio) | 1M |
| Sonnet 4.6 | 3 | 15 | 0.15 (family ratio) | 1M |
| Haiku 5.5 | 0.10 | 0.50 | 0.01 (fitted) | 1M |
| Haiku 4.5 | 1 | 5 | 0.10 (family ratio) | 200K |

Cache rates are **not assumed**. Rows marked "fitted" were fitted
during implementation against captured cost-state records (sum of `calls` per session and model
vs. `modelUsage[model].costUSD`). The test keeps them within 1%. Model ids are matched exactly,
after stripping a trailing `[1m]` and a date suffix.
Models with no fixture of their own take their family's fitted ratios (cache read 0.05x input for opus and sonnet, 0.1x for haiku; 1h write 2x input; 5m write 1.25x input, unfitted) and carry `_calibrated: false` in `prices.json`.

**Cost.** `cost(row) = Σ tokens × rate / 1e6`. An unknown model is **unpriced**: cost `null`,
shown as "unpriced", never $0. Aggregates report `unpriced_calls` alongside the dollar sum.
A session's **headline total** is its `cost_state.total_usd` when one exists (it includes models we
cannot price), else the sum of its calls. Time-bucketed figures (today, burn rate, the daily chart)
always use per-call costs, because cost-state is cumulative and has no per-call times.

**Project membership.** A row belongs to project P (a board session) when its `cwd` is P's repo
path or lies under `<repo>/.claude/worktrees/`. Repo path = the session `path` from `/api/state`.

**Role.**
- **teammate:** `agent_name` is set;
- **subagent:** `sidechain` or `subagent_file`;
- **worker:** `cwd` is under `.claude/worktrees/` and no `agent_name`;
- **lead:** everything else.

**Context per call** = `input + cache_read + cache_write_5m + cache_write_1h`. The window size comes from
`prices.json`, or 200K for an unpriced model.

## Section 2 — Alerts

Alerts are computed per **live session**, meaning a `session_id` whose newest call is less than 30 minutes old.
Thresholds are in `~/.claude/usage-alerts.json`. A missing file means defaults, and an unreadable file means defaults plus a
one-line warning in the Usage tab.

| Alert | Fires when (default) |
| --- | --- |
| `context` | the newest call's context ≥ 80% of the model's window |
| `burn` | per-call cost over the last 15 min, scaled to an hour, > $15/h |
| `total` | headline total > $25 |
| `model_mismatch` | newest call has `effort` low or medium, model is Opus or Fable, and `agent_name` is set |

There is no ack state: an alert clears as soon as its condition stops holding.

**Mapping live sessions to board cards.** In order:
1. A teammate window `✦ <name>` matches the live session whose newest call has `agent_name == <name>`.
2. A worker window (`@tc_agent`) matches the live session whose `cwd` equals that pane's path.
3. The `claude` window matches the newest live session with no `agent_name` whose `cwd` is the repo path.

Unmatched live sessions still appear in the Usage tab, just without a card badge.

## Section 3 — UI: `board/index.html`

- The drawer becomes **Usage | Runs**, defaulting to Usage. The tab choice is remembered in localStorage.
  Runs keeps today's runs list and log viewer. The feed and its agent filter are removed.
- When the drawer is closed, its toggle shows "N alerts" whenever the current project has alerts.
- Each agent card with an alert gets a badge: a short label per alert, with the detail in the title.
- **Usage tab** for the current project, top to bottom:
  1. **Headline:** today, 7 days and 30 days in $, labelled "API-equivalent estimate", plus
     "N unpriced calls" when non-zero.
  2. **Alerts** list.
  3. **Live sessions** table: name (agent name, window, or short session id), role, model,
     effort, a context % bar, $ in the last hour, and $ total.
  4. **30-day chart:** daily bars stacked by model.
  5. **Breakdowns:** three sortable tables over 30 days.
     - By role: $ and calls.
     - By model: $, calls, and cache share (the share of input-side tokens that were cache reads).
     - By branch/worktree: $ and calls, keyed by `git_branch`, falling back to the worktree dir name.
- Charts are hand-built inline SVG using the board's colour tokens, and work in both themes. Load the
  `dataviz` skill before writing chart code.
- While backfill runs, the tab shows "indexing… N%", with the figures computed so far.

## Section 4 — Indexing, API, errors, testing

**Indexer thread.** It starts with the server. The first pass walks all transcript files
newest-mtime first and reports progress as bytes done over bytes total. After that it re-scans every 5s:

- a file whose `(inode, size)` matches its stored entry is skipped;
- a grown file is read from `offset`;
- a shrunk file or one with a new inode is re-read from 0 (its rows are upserted, so nothing is
  duplicated);
- only complete lines (ending in `\n`) are consumed.

Corrupt JSON lines are skipped and counted in `files.bad_lines`. An indexer exception is logged.
The thread then keeps running, and the error is reported in `api/usage` as `index_error`.

**API.**
- `GET api/usage?session=<p>` returns
  `{indexing: {done, total}, headline: {today, week, month, unpriced_calls}, alerts: [...],
  live: [...], daily: [{date, by_model: {...}}], by_role, by_model, by_branch, index_error?}`.
  Days are local-time.
- `api/state` gains, per board session, `usage_alerts: {<pane id>: [alert, ...]}` for matched cards,
  plus `usage_alert_count`. These come from an in-memory snapshot the indexer refreshes after each
  pass, so `api/state` never queries sqlite on its request path.
- `api/feed` is removed.

**Testing** (`board/tests/test_usage.py`):
- **Fixtures** are real excerpts captured from this machine's transcripts: a lead turn, a teammate
  turn with `agentName`, a sidechain or subagent-file turn, and a `cost-state` record. They are
  trimmed and anonymised (message content dropped, usage kept). Each fixture file records the source
  path it was captured from.
- **Price calibration:** for each captured cost-state session in the fixtures, the per-model sum of
  priced calls matches `modelUsage[model].costUSD` within 1%.
- **Indexer:**
  - an incremental append is read from its offset;
  - a truncated or replaced file is re-read without duplicates;
  - a duplicate `requestId` is stored once;
  - a partial trailing line waits for its newline;
  - a corrupt line is counted.
- **Role and project rules:** one test each. **Alerts:** one rule test per alert, covering both
  firing and clearing.
- **Unknown model:** the cost is null and is counted in `unpriced_calls`.
- **Live read-only check** (the e2e task):
  - The board runs against the real `~/.claude/projects` (read-only) with a scratch `TC_STATE`.
  - The Usage tab's 30-day agent-board total must equal an independent sum computed by a separate
    script straight from the jsonl files.
  - Each probe in that check must be able to fail.

## Out of scope

Budgets with hard stops, acknowledging alerts, per-message drill-down, and export.
