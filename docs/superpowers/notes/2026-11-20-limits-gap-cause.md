# Limits gap cause and the tap's context figure

Read from `docs/superpowers/metrics/runs.jsonl` on 2026-11-20 and from the code on `feat/efficiency-now`.

## Counts

`kind == "run"` records, one row per combination of limits shape, `backfilled`, `window` and whether `limits` is in `missing`. "start/record" says whether the `limits.start` and `limits.record` values are set or null; on all 13 null rows `limits` is the object `{"start": null, "record": null}`, never a bare `null`.

| limits.start | limits.record | backfilled | window | `limits` in missing | count |
|---|---|---|---|---|---|
| set | set | false | stamped | no | 17 |
| null | null | true | derived | yes | 13 |

Total run records: **30** (17 + 13 = 30). All 13 limits-null records are in batch `backfill`.

`kind == "start"` records: 17 in total; `limits` set on 17, `limits` null on 0.

## Code path

- `board/metrics.py:705-708` (`build_record`, the `if backfilled:` branch): writes `limits = {"start": None, "record": None}` and appends `limits`, `ready_at`, `wait_s` to `missing`, by design, because a tap reading today says nothing about a run that ended days ago. Produced all 13 null records. The branch is reached from the backfill command at `board/metrics.py:1572` (`backfilled=True`).
- `board/metrics.py:713-714` (`build_record`, the else branch): `limits.record` is null and `limits` goes into `missing` when `usage.plan_limits(...)` finds no tap with `rate_limits`. Produced 0 records.
- `board/metrics.py:207-208` (`cmd_start`): `limits = None` and `missing = ["limits"]` when `plan_limits` finds no tap with `rate_limits`. Produced 0 records (no start record has null limits).
- `board/usage.py:247-248` (`plan_limits`) returns `None` when no tap has a `rate_limits` with `five_hour` or `seven_day`; it is the input of the two cases above.

## Cause

All 13 limits-null run records are backfilled records (`backfilled: true`, `window: derived`, batch `backfill`), and `build_record` sets their limits to null on purpose (`board/metrics.py:705-708`) because no tap reading exists for a window that ended before the record was written. The cause is inside our code, deliberate and not a defect, and the 17 non-backfilled run records and all 17 start records have limits. Every limits-null record is explained by a cited code path; none is left over. (The brief's context said 29 run records; the file holds 30 today, the extra one is non-backfilled with limits set.)

## Tap context figure

Key paths under `context_window` in one live tap payload (key names and number types only):

- `context_window.total_input_tokens` (number)
- `context_window.total_output_tokens` (number)
- `context_window.context_window_size` (number)
- `context_window.current_usage.input_tokens` (number)
- `context_window.current_usage.output_tokens` (number)
- `context_window.current_usage.cache_creation_input_tokens` (number)
- `context_window.current_usage.cache_read_input_tokens` (number)
- `context_window.used_percentage` (number)
- `context_window.remaining_percentage` (number)

Tap files: one per session (22 files on this machine, each named `<session id>.json`), overwritten on every refresh; the payload carries `received_at` and no history. The tap therefore holds only the current context of a session, not the figure at the end of an earlier task. A4 is confirmed: the task `context_tokens` comes from the usage index rows (per-turn transcript usage, which keeps history), and a tap serves only as the live figure of a still-running session.

## What the fix records

The one cause found (backfilled run) maps to the fixed string `backfilled run: no tap reading exists for a past window`. The other two fixed strings, `no statusline tap with rate_limits at record time` (`board/metrics.py:713-714`) and `no statusline tap with rate_limits at start` (`board/metrics.py:207-208`), cover code paths that produced no record so far; they apply to future records only. No new reason string is proposed.
