# Execution analytics part 1: real-state e2e (2026-11-16)

Task 6 of `docs/superpowers/plans/2026-11-16-execution-analytics-part-1.md`. Run from the part-1 worktree (branch
`queue/execution-analytics-part-1`, code of commit 07f3084) against this repo's real ledgers, real usage index and real
`runs.jsonl`. Scratch files and state were in a `mktemp -d` directory, written `<scratch>` below; `TC_STATE=<scratch>/state`.

## Baseline and end state of the real logs

The main checkout's `runs.jsonl` already carried one uncommitted line before this run (the lead's `kind:start` line for this spec).
Pass condition: the same before and after, and no `tasks.jsonl` in the main checkout.

| | before | after backfill | after analyze | after the model runs |
|---|---|---|---|---|
| `git diff docs/superpowers/metrics/ \| shasum` | `093ae6e3c8ac9fc822f3036c2f0d3b1acceff08e` | same | same | same |
| `git status --short docs/superpowers/metrics/` | ` M docs/superpowers/metrics/runs.jsonl` | same | same | same |

`ls docs/superpowers/metrics/` in the main checkout: `configs roadmap runs.jsonl`; `tasks.jsonl` does not exist there. **Pass.**
No command failed, so no `kind:error` line was appended.

## 1. backfill-tasks on the real ledgers

```
python3 -I board/metrics.py --repo <main checkout> backfill-tasks --log <scratch>/tasks.jsonl --usage-db <real usage.sqlite> --no-ingest
backfilled tasks for 18 specs (90 tasks, 47 partial)
```
rc=0, empty stderr, about 1 min 51 s. `--no-ingest` so the real usage index was only read, not written; its newest rows are from 14:44 local, so
the newest specs may miss usage rows (see the counts below).

- Lines: 90 (18 specs). `partial: true`: 47. `usd` null: 47, not null: 43.
- Privacy: `grep -c /Users/ <scratch>/tasks.jsonl` = **0**; UUID-shaped hits 0; absolute-path values 0.

Per spec, tasks with `usd` null vs not null:

| spec | tasks | usd null | usd set |
|---|---|---|---|
| 2026-11-05-overnight-queue-design.md | 2 | 0 | 2 |
| 2026-11-05-mod-agent-status-design.md | 4 | 4 | 0 |
| 2026-11-05-mod-team-band-design.md | 2 | 2 | 0 |
| 2026-11-05-mod-usage-gauges-design.md | 3 | 1 | 2 |
| 2026-11-05-tasks-window-polish-design.md | 5 | 5 | 0 |
| 2026-11-05-artifact-session-id-design.md | 2 | 2 | 0 |
| 2026-11-05-mod-shell-hooks-design.md | 6 | 3 | 3 |
| 2026-11-05-mod-overview-design.md | 4 | 2 | 2 |
| 2026-11-05-queue-keep-awake-design.md | 4 | 0 | 4 |
| 2026-11-09-lead-named-agents-design.md | 5 | 5 | 0 |
| 2026-11-09-relay-launch-check-design.md | 5 | 5 | 0 |
| 2026-11-09-remote-access-design.md | 7 | 1 | 6 |
| 2026-11-10-queue-metrics-design.md | 7 | 2 | 5 |
| 2026-11-10-fast-test-suite-design.md | 7 | 3 | 4 |
| 2026-11-11-all-zsh-interrupt-sweep-design.md | 2 | 2 | 0 |
| 2026-11-11-turn-start-spinner-rule-design.md | 5 | 2 | 3 |
| 2026-11-10-queue-reliability-design.md | 9 | 1 | 8 |
| 2026-11-11-discord-replaces-telegram-design.md | 11 | 7 | 4 |

Three sample lines (a full one, a partial one, one with a fix round):

```
{"active_s": 1140, "batch": "backfill", "code_in_steps": false, "ended_at": "2026-11-11T05:56:20Z", "escalated": false, "findings": {"critical": 0, "important": 0, "minor": 5}, "fix_rounds": 2, "model_mapped": "sonnet", "model_used": "claude-sonnet-5-5", "outcome": "complete", "owner": "qm-impl", "partial": false, "review_rounds": 3, "review_tokens": 1177683, "review_usd": 0.425963, "spec": "docs/superpowers/specs/2026-11-10-queue-metrics-design.md", "started_at": "2026-11-11T05:30:49Z", "subject": "Task 2: `record` \u2014 identity, size, manifest, stale base, ledger", "task_id": 2, "tier": "standard", "tokens": 5741050, "usd": 1.459714}
{"active_s": 0, "batch": "2026-11-11-1", "code_in_steps": false, "ended_at": null, "escalated": false, "findings": {"critical": 0, "important": 0, "minor": 1}, "fix_rounds": 0, "model_mapped": "sonnet", "model_used": null, "outcome": "complete", "owner": "dc-launch", "partial": true, "review_rounds": 1, "review_tokens": null, "review_usd": null, "spec": "docs/superpowers/specs/2026-11-11-discord-replaces-telegram-design.md", "started_at": null, "subject": "Task 2: `tmux-ctl discord` access commands and status", "task_id": 2, "tier": "standard", "tokens": null, "usd": null}
{"active_s": 3420, "batch": "2026-11-11-1", "code_in_steps": false, "ended_at": "2026-11-11T12:42:05Z", "escalated": false, "findings": {"critical": 0, "important": 0, "minor": 0}, "fix_rounds": 1, "model_mapped": "sonnet", "model_used": "claude-sonnet-5-5", "outcome": "complete", "owner": "fts-fix", "partial": false, "review_rounds": 3, "review_tokens": null, "review_usd": null, "spec": "docs/superpowers/specs/2026-11-10-fast-test-suite-design.md", "started_at": "2026-11-11T08:15:23Z", "subject": "Task 6: Parallel-safety audit and fixes", "task_id": 6, "tier": "standard", "tokens": 32438947, "usd": 5.919926}
```

**Shared-owner check (Task 2 minor).** Every `commit_end` sha in the repo's ledgers resolves in this repo (127 of 127), so no owner's rows
collapse onto its first task for lack of an end time. Shared owners' rows do split across their tasks (for example `hooks`: tasks 1, 2, 3 got 975 392, 2 796 070 and 24 612 036 tokens; `qr-awake`: tasks 6, 7, 9).
What does show is the other side: some tasks of a shared owner get no rows at all (`qm-impl` tasks 3 and 5, `dc-launch` tasks 2, 5, 10, `dc-badge` 6, 7, 8,
`fts-fix` task 2): the owner's rows fall to the neighbouring task whose end time comes first. Those lines are `partial: true`.

## 2. analyze on the real runs.jsonl

```
python3 -I board/metrics.py --repo <main checkout> analyze --since 30d --out <scratch>/stats.json --tasks-log <scratch>/tasks.jsonl
analyzed 18 specs, 90 tasks across 3 projects → <scratch>/stats.json
```
No `--projects`: the project list came through the real `overview.py --json`: `projects_source` = **overview**, projects = ['agent-board', 'interiors', 'signal-hub-gcp'].
The scratch tasks log replaces the current repo's `tasks.jsonl` (the repo is listed first). `grep -c /Users/ stats.json` = 0.

- Coverage: `{"with_cost": 43, "tasks": 90}`, so 43/90 tasks with cost data.
- Window: 2026-10-17T20:23:57Z to 2026-11-16T20:23:57Z; 18 specs in the current window, 0 in the previous (the log starts 2026-11-05), so every change is `–` or equals the current value.
- Flag row counts:
- overpowered: 0 rows
- underpowered: 1 rows
- costly_steps: 10 rows
- handoffs: 13 rows
- forecast: median precision 1.0, median recall 0.866, 4 specs below 0.5 recall.
- `overpowered` is 0 because no task line has `code_in_steps: true` (0 of 90): the older plans' task descriptions carry no code fences. `escalated` is true for 2 tasks.

## 3. weekly --dry-run with the real claude (the one real model run)

```
bin/tmux-ctl metrics weekly --dry-run --since 30d --tasks-log <scratch>/tasks.jsonl
```
Through the zsh exec path of `bin/tmux-ctl` (covers what the unit tests could not). rc=0, empty stderr, 14 s wall time, real `claude`
(`claude` from the user's local bin on PATH, no `TC_CLAUDE_BIN`). **2 of 3 items passed the evidence check.** Full output:

```
Execution analytics, 2026-10-17 → 2026-11-16

```
metric                     | last week | this week | change
specs_run                  | 0         | 18        | +18
specs_merged               | 0         | 18        | +18
specs_failed               | 0         | 0         | 0
median_usd_per_spec        | –         | 11.73     | –
p90_usd_per_spec           | –         | 42.46     | –
median_lead_share          | –         | 0.5982    | –
median_fix_rounds_per_spec | –         | 3.5       | –
median_elapsed_s           | –         | 4274.0    | –
median_active_min          | –         | 39.0      | –
questions_per_spec         | –         | 0.0       | –
rulings_per_spec           | –         | 7.5       | –
```
Flags:
- underpowered: mechanical|sonnet: escalation rate 1.0
- costly_steps: 2026-11-10-fast-test-suite-design.md task 5 Task 5: Speed up the three slow zsh files $6.82
- costly_steps: 2026-11-10-fast-test-suite-design.md task 6 Task 6: Parallel-safety audit and fixes $5.92
- costly_steps: 2026-11-05-mod-shell-hooks-design.md task 3 Task 3: kill-guard mod $4.41
- costly_steps: 2026-11-10-fast-test-suite-design.md task 3 Task 3: `tools/tests/all.zsh` runner with its own test $3.21
- costly_steps: 2026-11-09-remote-access-design.md task 6 Task 6: Lead rules, INSTALL docs, user-gate checklist $2.76
- costly_steps: 2026-11-10-queue-metrics-design.md task 6 Task 6: `backfill`, the real-state check and privacy sweep $2.36
- costly_steps: 2026-11-05-mod-overview-design.md task 1 Task 1: agent-status mod writes the new fields $2.25
- costly_steps: 2026-11-10-queue-metrics-design.md task 4 Task 4: `report` and the batch numbers $1.81
- costly_steps: 2026-11-10-queue-metrics-design.md task 2 Task 2: `record` — identity, size, manifest, stale base, ledger $1.46
- costly_steps: 2026-11-05-mod-overview-design.md task 2 Task 2: overview record carries agents, reasons, durations and alerts $1.4
- handoffs: 2026-11-05-overnight-queue-design.md 1 handoffs, $18.59/h vs median $17.82/h
- handoffs: 2026-11-05-mod-agent-status-design.md 2 handoffs, $23.16/h vs median $17.82/h
- handoffs: 2026-11-05-mod-team-band-design.md 1 handoffs, $19.41/h vs median $17.82/h
- handoffs: 2026-11-05-tasks-window-polish-design.md 1 handoffs, $21.47/h vs median $17.82/h
- handoffs: 2026-11-05-mod-shell-hooks-design.md 1 handoffs, $21.65/h vs median $17.82/h
- handoffs: 2026-11-05-queue-keep-awake-design.md 1 handoffs, $24.1/h vs median $17.82/h
- handoffs: 2026-11-09-lead-named-agents-design.md 1 handoffs, $22.21/h vs median $17.82/h
- handoffs: 2026-11-09-remote-access-design.md 2 handoffs, $15.26/h vs median $17.82/h
- handoffs: 2026-11-10-queue-metrics-design.md 1 handoffs, $14.89/h vs median $17.82/h
- handoffs: 2026-11-10-fast-test-suite-design.md 1 handoffs, $14.55/h vs median $17.82/h
- handoffs: 2026-11-11-turn-start-spinner-rule-design.md 1 handoffs, $9.29/h vs median $17.82/h
- handoffs: 2026-11-10-queue-reliability-design.md 2 handoffs, $17.54/h vs median $17.82/h
- handoffs: 2026-11-11-discord-replaces-telegram-design.md 1 handoffs, $10.4/h vs median $17.82/h
- forecast: 2026-11-05-queue-keep-awake-design.md recall 0.3333 (below 0.5; medians: precision 1.0, recall 0.866)
- forecast: 2026-11-09-remote-access-design.md recall 0.4483 (below 0.5; medians: precision 1.0, recall 0.866)
- forecast: 2026-11-10-fast-test-suite-design.md recall 0.2679 (below 0.5; medians: precision 1.0, recall 0.866)
- forecast: 2026-11-11-discord-replaces-telegram-design.md recall 0.3827 (below 0.5; medians: precision 1.0, recall 0.866)
Recommendations:
1. Route mechanical tasks to haiku only, not sonnet
   change: Stop dispatching mechanical-tier tasks to sonnet. Pin the mechanical tier to haiku in the routing map, and when a mechanical task needs more than haiku, re-tier it to standard in the plan instead of letting it escalate on the fly.
   expected: The escalation rate for mechanical|sonnet should fall from 1.0 toward 0.0, because no mechanical tasks will run on sonnet. The comparison is haiku, which had 0.0 escalation across 8 tasks.
   risk: Only 2 mechanical|sonnet tasks are the basis, so this is thin evidence. Only 43 of 90 tasks have cost data (coverage), so cost effects are hard to confirm. The change itself needs no cost data, since escalation_rate is not cost-based.
   evidence: by_tier_model.mechanical|sonnet.escalation_rate = 1.0; by_tier_model.mechanical|sonnet.tasks = 2; by_tier_model.mechanical|haiku.escalation_rate = 0.0; by_tier_model.mechanical|haiku.tasks = 8; flags.underpowered.0.tier_model = mechanical|sonnet
2. Split the largest test-suite plan tasks into smaller steps
   change: In plans for test-infrastructure work, split any task that touches many files or audits many files at once, such as the 'Speed up the three slow zsh files' and 'Parallel-safety audit and fixes' tasks, into one task per file or per audit target. Give each its own modelTier, with a mechanical tier where the spec is complete.
   expected: Costly steps like these should drop below the top of the costly_steps list next week, and p90 USD per spec should fall from 42.46.
   risk: Cost data covers only 43 of 90 tasks (coverage), so p90 may move because of which tasks carry cost data and not because of the split. There is no previous-window value (previous is null) to compare against. Smaller tasks add dispatch overhead and could raise lead share.
   evidence: flags.costly_steps.0.usd = 6.82; flags.costly_steps.0.subject = Task 5: Speed up the three slow zsh files; flags.costly_steps.1.usd = 5.92; flags.costly_steps.1.subject = Task 6: Parallel-safety audit and fixes; trends.p90_usd_per_spec.current = 42.46
(2 of 3 passed the evidence check)
coverage: 43/90 tasks with cost data
stats: <scratch>/state/analytics/stats.json
```

`recommend.json`, `dropped` list: `[{"title": "Add a files-to-touch list to plans for specs with low forecast recall", "reason": "uncited number 4 in expected_effect"}]`.

**Was the drop a false drop?** The dropped item's text is not kept in recommend.json (only title and reason), so this run's drop can not be judged.
Its title, "Add a files-to-touch list to plans for specs with low forecast recall", fits a count the stats hold only as a list of 4 rows (`flags.forecast.below_half`, with no key for its length): a derived count, not a sign, date or `1,000` case.
The second model run below (same prompt, same stats) produced the same three themes and one drop that **is** a false drop:

- "Split the largest plan tasks so no single task is a costly step" was dropped with `uncited number 5 in change`. Its `change` quotes the subjects
  `'Task 5: Speed up the three slow zsh files'` and `'Task 6: Parallel-safety audit and fixes'`; the item cites both subjects as string evidence
  (`flags.costly_steps.0.subject`, `.1.subject`), so the `5` and `6` are part of a cited string. The check reads them as bare numbers. In the first run the same kind of item
  kept its quote without the `Task N:` prefix and passed. A fix would blank out any substring equal to a cited string value (or a quoted span) before scanning the prose.

## 4. What the model actually read

`claude -p … --output-format stream-json --verbose` (the same argv, `--output-format` swapped), cwd = the stats directory, prompt = `claude/analytics.md` + `Stats file: <scratch>/state/analytics/stats.json`:

```
tool_use calls (all of them): 1
  Read {"file_path": "<scratch>/state/analytics/stats.json"}
```
Only `stats.json` was read; 10 stream events, rc=0. (Read is not path-scoped by the flags, so this is what one run did, not a guarantee.)

## 5. Real logs untouched

See the table at the top: checksum and status identical before and after every step; no `tasks.jsonl` in the main checkout; no error line appended.

## Findings for the lead

1. False drop in the prose-number check: numbers inside a quoted string that is also cited as string evidence (`Task 5: …`). See section 3.
2. 47 of 90 backfilled tasks are partial: 35 have no owner (the older ledgers name no teammate for them, so no row can be attributed) and 12 have an owner but no usage row
   fell to them (cause not checked per task: the shared-owner split, or rows missing from the index, whose file was last written 14:44). All 35 owner-less lines are partial; no line without an owner has cost data.
3. `code_in_steps` is false for every backfilled task, so `overpowered` can not fire on history; it only fires on plans written from now on.
4. `by_tier_model` keys with `unknown` (no `model_used`) hold 47 of 90 tasks.
