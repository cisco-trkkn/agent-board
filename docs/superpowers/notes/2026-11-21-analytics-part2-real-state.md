# Execution analytics part 2: full suite and real-state checks

Run 2026-11-21 from the worktree `.claude/worktrees/execution-analytics-part2` (branch `spec-execution-analytics-part2`, head b1f0fe9).

## Suite

- `zsh tools/tests/all.zsh; echo rc=$?` via `tmux-ctl run -t 1500`: verdict line `ALL PASS 181 jobs in 8m29s`, then `SLOW: 8m29s over the 5 min budget`, `rc=4` (4 = over the budget, accepted on this machine). `tests: 4834`; slowest job zsh/test_ctl_dialog_press.zsh 254s.
- Bridge: `cd tools/discord-bridge && npm ci && npm test` (via `tmux-ctl run`): `# tests 189`, `# pass 189`, `# fail 0`.

## Real-state ops

Command (worktree, `env -u TC_STATE`): `python3 -I board/metrics.py --repo . weekly --dry-run --json --since 30d > ops.jsonl`. `--repo .` was accepted; exit 0, stderr empty.

- Destination: the ops dir `~/.local/state/agent-board/discord/_ops` (`discord_ops.configured()` is true, so one multi-project destination; flag lines carry a `[agent-board]` prefix). No project-by-project destinations.
- Ops: 2 lines. Both pass `discord_feed._check`. Texts 1784 and 1726 chars (max 1784, limit 1900). Buttons: 0 on post A, 2 on post B (limit 5). Post B has `files` (stats.json) and 2 of 3 recommendations passed the evidence check.
- Links: 0 `<https://discord.com/channels/` lines in the posts. Cause, checked against the real feed: the 9 flag lines that fit under the 1900 cap are all for specs dated 2026-11-05 and 2026-11-10 (costly_steps for fast-test-suite and mod-shell-hooks, then handoffs for the 11-05 specs). The real feed `~/.local/state/agent-board/feed/agent-board.jsonl` holds `spec_started` events (with `refs.thread_key`) only for 15 specs from 2026-11-11 on, so `thread_link` returns None for them: the missing piece is the feed's `spec_started` for those specs (they predate the feed). The resolver itself works on real state: of the 33 flag rows in the full stats, 12 resolve to a thread (bridge-state.json has the guild id and 34 threads), but flag order puts the older specs first and the 24 rows after the cap ("… and 24 more flags in stats.json") are the ones that would carry links. Concern for the lead: on this data the weekly post shows no link at all.
- Cost of the one real `claude -p` call: $0.0808 (recommend.json `usage`: input 4, output 2116, cache_read 11233, cache_write 14637 tokens). `--dry-run` itself does not print it.
- Side files: the dry-run wrote stats.json and recommend.json under `$TMPDIR/tmux-ctl-503/analytics/` (the state dir, outside git); nothing else.

## Leak check

Files in each outbox before and after the dry-run (the suite ran in scratch dirs, not these):

| outbox | before | after |
| --- | --- | --- |
| discord/_ops | 4 | 4 |
| discord/agent-board | 4 | 4 |
| discord/interiors | 10 | 10 |

The sorted file lists are identical (`diff` empty), so no bridge consumed or added files meanwhile.

`git -C /Users/francisco.ruiz/agent-board status --short docs/superpowers/metrics` printed ` M docs/superpowers/metrics/runs.jsonl` both before and after. That change is not from this run: the file's mtime is 01:45:35 and its one added line is a `kind: start` record `at 2026-11-21T06:45:34Z` (batch 2026-11-11-1), all before the dry-run; no `kind: error` or `analytics` line was added by it.

## Part-1 minors

Ledger `docs/superpowers/ledgers/2026-11-16-execution-analytics-part-1/progress.md`:

| line | minor | closed by |
| --- | --- | --- |
| 38 | `mr` runs not in a trend row | Task 1 (8bdf469): `specs_mr` trend; the post shows `specs_mr 0 / 0` |
| 39 | failed analyze appends `kind:error` to the tracked runs.jsonl (matters for the weekly job) | Task 4 (57a8542): `board/metrics.py` main skips `_log_error` when `sub == "weekly"` (the job reports to stderr only) |
| 69 | `--dry-run` refusal appends `kind:error` (same) | Task 4 (57a8542), same skip |
| 70 | model strings unescaped for Discord; stats line carries an absolute path | Task 2 (5305391): `analytics_post.escape` on model strings and subjects (post B text shows `mechanical\|sonnet`, `escalation\_rate`); the post text says "more flags in stats.json" and the absolute path appears only in `files` |
| 78 | flags barely discriminate (costly always 10 rows); underpowered/rec 1 rest on 2 tasks (no min n) | costly: Task 2 (5305391) `_flag_rows` shows `costly_steps[:3]` (3 rows in the real post). No min n: already fixed in part 1 by a4d6f8c: `board/metrics_analyze.py` lines 172 and 174, `if n >= UNDER_MIN_TASKS and ...` (`UNDER_MIN_TASKS = 5`, line 20) guard both the fix-rounds and the escalation branches |

The handoffs flag still lists many specs (5 of 9 shown rows; the real stats hold more): part 1's "handoffs 13/18 specs" half of line 78 is not closed by any part-2 task.
