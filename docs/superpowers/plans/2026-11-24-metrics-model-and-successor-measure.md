# Metrics model and successor: real-state measurement

One run on this machine, 2026-11-24, read-only against real state: the usage index opened with `--no-ingest`, the tasks log a scratch copy (`/tmp/claude-503/t6.bn77Uj/tasks.jsonl`), nothing under `~/.local/state`, `~/.claude/projects` or `docs/superpowers/metrics/` changed.

Code under test: branch `metrics-model-and-successor` at `01e3fa4` (the timings and the backfill both started from it, before the fix wave `d02908a` landed; that wave only changed `read_spawns` to tolerate invalid bytes, the review-dispatch sentence in the SDD extras skill and two tests, so it does not affect these numbers).

## Lineage timing

Base code is the main checkout's `board/` (`git diff --quiet 0af42b5 -- board/metrics_lead.py` printed `same`). Real state: lineage `~/.local/state/agent-board/lineage/agent-board.jsonl`, transcripts `~/.claude/projects/-Users-francisco-ruiz-agent-board`.

- Base: `successor()` took 2.46 s per call (mean of the last 5 lineage lines), load average 4.02 5.12 4.59 (1, 5, 15 min) before and 3.86 5.03 4.57 after. Extrapolated over 146 calls: about 359 s.
- One whole-lineage `lead_fields` makes 146 `successor()` calls (2 per lineage line); it reported 73 handoffs.
- Branch: whole-lineage `lead_fields` took 4.98 s, load average 3.86 5.11 4.60 (1, 5, 15 min; 4.35 after).
- Transcripts: 730. Lineage lines: 73.
- Command: `perl -e 'alarm 900; exec @ARGV' python3 - "$PWD/board"` with the brief's script; exit 0 for both runs.

## Model resolution on real records

Before (last line per batch, spec, task over a scratch copy of the committed `docs/superpowers/metrics/tasks.jsonl`): 343 records, 130 without a model, 86 of them standard-tier.

Command: `perl -e 'alarm 3600; exec @ARGV' python3 board/metrics.py --repo . backfill-tasks --log /tmp/claude-503/t6.bn77Uj/tasks.jsonl --no-ingest`. Wall time 34 min 33 s (20:38:21 to 21:12:54), exit code `rc=0`, load average 3.78 4.05 4.58 at the end. Output:

    backfilled tasks for 2 specs (29 tasks, 19 partial)
    re-derived models for 44 specs (343 tasks)

After, over the 343 re-derived records: `usage` 219, `spawn` 16, `ledger` 0, `none` 108; standard-tier `none` 68. Models resolved: 130 to 108 without a model (22 more records got one: 16 from spawn rows, and the other 6 counted by difference, not traced).

The 29 records of the 2 newly built specs: `usage` 10, `ledger` 18, `none` 1. So the ledger path works on real ledgers, but gave 0 hits on the re-derived old records.

Why no ledger hit on the old records: the 68 standard-tier `none` records are mostly in 3 specs; sampled `2026-11-19-remote-discord-only` (8 records, owner `None`, partial). Its archived ledger (`docs/superpowers/ledgers/2026-11-19-remote-discord-only/progress.md`) names dispatches in a form the regex does not read: `Tasks 1, 5, 8: BASE 5de77af; dispatched c-t1, c-t5, c-t8 (sonnet) in parallel` and `Task 5: c-t5 done 4dfc844`, with no `Task N: dispatched <name> (...)` line, so the task has no owner and no dispatch model. For `2026-11-16-supervised-improvement-loop` (10 records) and `2026-11-12-memory-consolidation` (8) there is no archived ledger in `docs/superpowers/ledgers/`. Finding for the lead, not fixed here: a multi-task `Tasks a, b: dispatched x, y (model)` form exists in real ledgers.

## Verdict

Pass against the 15 s target: 4.98 s for the whole lineage on the branch, against an extrapolated 359 s on the base. Scope: this machine, load average about 4 (1 minute), one run, a warm file cache not controlled. The model fallback cut records without a model from 130 to 108 of 343; the rest are old runs with no spawn rows and a ledger form or no ledger the parser cannot read.
