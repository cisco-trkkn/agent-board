# Metrics: a model on every task record, and a fast `successor()`

Status: approved by the user on Discord, 2026-11-23 (G-Q1 1, design "Ok"). Source: the regroup of the ideas inbox,
group G (ideas 2026-11-23 14:04, 2026-11-20 19:31). Parked from the group: the controlled before/after test of the
efficiency-now method (2026-11-20 19:21), until the engine's K2 comparison has produced comparable specs.

## Goal

Every per-task metrics record names the model the task ran on, so a failure rate is never hidden under "unknown"
(today 56 standard-tier records have no model and fail at 46%, against 0% for standard+sonnet), and the lead-lineage
lookup stops costing 1.6 s per call (a whole-lineage backfill took 116 s).

## a. A model on every task record

Today `board/metrics_tasks.py` sets `model_used` only from the usage rows attributed to the task's owner (the model
with the most tokens). When no rows are attributed (an owner whose transcript is not matched, a fixer or a renamed
teammate) the model is `None` and the analysis groups it as `unknown` (`metrics_tasks.py` ~150). Two sources written
at dispatch time are unused or misread:

- `~/.local/state/agent-board/spawns.jsonl` (the spawn-record hook): `{ts, lead_session, name, subagent_type, model,
  tier, reason}` per Agent dispatch.
- The SDD ledger line `Task N: dispatched <name> (<tier>, <model>) …`. The `DISPATCH` regex (`metrics_tasks.py:12`)
  only accepts a model as the first word in the parentheses, so `(standard, sonnet)` yields no model.

Changes:

1. `DISPATCH` accepts both `(<model> …)` and `(<tier>, <model> …)`; `REVIEW` and the fix-round forms likewise keep
   their current matches.
2. Resolution order for `model_used`, first hit wins, recorded as `model_source`:
   `usage` (today's rule) → `spawn` (the newest `spawns.jsonl` row whose `name` equals the task's last owner and whose
   `ts` is not after the task's first activity, preferring rows of the spec's lead sessions from `metrics_lead`'s lineage)
   → `ledger` (the last dispatch line's model for that task) → `none`. `model_used` stays a full model id when the
   source is `usage`; for `spawn` and `ledger` it is the alias given (`sonnet`, `haiku`, `opus`, `fable`), which
   `family()` already maps.
3. `KEYS` gains `model_source`. Readers that take the last line per (batch, spec, task_id) are unchanged.
4. `metrics report` adds one line when any task of the batch has `model_source == "none"`:
   `tasks without a model: <k> (<task ids>)`. The analysis (`metrics_analyze.py`, `by_tier_model`) groups `none` as
   `nomodel`, not `unknown`, and the weekly analytics text says "no model recorded" for it.
5. `backfill-tasks` re-derives existing records with the new resolution (append-only, as today), so the 56 records
   are re-checked.
6. `~/.claude/skills/subagent-driven-development-extras` (the user's skill, a symlink into this repo if it is one;
   check with `ls -l` first and edit the real file): one line in its ledger guidance: every dispatch line names the
   tier and the model, `dispatched <name> (<tier>, <model>)`.

## b. A fast `successor()`

`board/metrics_lead.successor(tdir, line)` globs every transcript in `tdir`, reads each head (`HEAD_LINES`), parses
JSON and looks for the handoff phrase and the doc basename. It is called (2k+1) times for a record with k handoffs.

- A module-level cache: per `tdir`, a map from transcript path to its pre-filtered head, built once per process and
  refreshed for files whose mtime changed. Pre-filter: keep only head lines whose raw text contains `PHRASE`, before
  any `json.loads`.
- `successor()` then looks up `(tdir, doc basename, old_session_id)` in a result cache.
- Behaviour is unchanged: the same path or `None` for every input.
- Target: the whole-lineage backfill under 15 s on this machine (measured once in the run and noted in the final
  report, not asserted in a test).

## Testing

- `board/tests/test_metrics_tasks.py`: the `(tier, model)` dispatch form parsed; each resolution step and its
  `model_source` from fixture usage rows, a temp `spawns.jsonl` and a fixture ledger; `none` when all three miss;
  the report line; `by_tier_model` groups `none` as `nomodel`; `backfill-tasks` on a fixture batch rewrites the model.
- `board/tests/test_metrics_lead.py`: `successor()` returns the same results with the cache as a cache-free reference
  over a fixture transcript dir (including a changed mtime); each transcript file is opened once across repeated
  calls (counting `open` through a seam); lines without `PHRASE` are never JSON-parsed.
- Every test sets `TC_STATE` to a temp dir and never reads the real `spawns.jsonl`.

## Out of scope

The efficiency-now before/after experiment (parked); changing tier routing; per-model pricing.
