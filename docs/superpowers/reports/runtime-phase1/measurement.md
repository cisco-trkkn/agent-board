# Runtime Phase 1 — before/after measurement (Task 13)

Measured 2026-10-28 (evening, EDT) on toolkit SHA 45781bb. The live config was swapped 2026-10-28 ~21:15 EDT (= 2026-10-29T01:15:00Z).

**Sources.** *Before* = `docs/superpowers/reports/runtime-audit/report.md` (the 2026-10-25 audit). That report stands in for the deleted 2026-10-25 `injection_costs.json`, per lead ruling. *After* = `bash tools/audit/run_baseline.sh 1` run from this worktree, outputs in `audit-out/2026-10-28/` (gitignored): `injection_costs.json`, `session_metrics.json`, `manifest.json` (324 files in window, 64 in scope).

**After-window filter.** The 1-day JSON mixes sessions from before and after the install and has no per-session start time. After-window cells therefore come from a one-off `python3 -I` read that reuses `tools/audit/transcripts.py:iter_events` and `tools/audit/injection_costs.py:costs`. It keeps only sessions whose first transcript timestamp is at or after 2026-10-29T01:15:00Z. Two sessions qualify: `5387f433-21f0-439e-bfc7-af27d19afb55` (lead, started 01:30:34Z) and `2708ad7d-a79d-45ef-9c71-d299f67bbad5` (this teammate, started 01:32:16Z). The unfiltered 1-day figures (63 sessions, mostly before the install) are the second figure in each row.

**Scope of every verdict: after-window n=2 sessions started after the install only (n<5, so no change is called significant). The week-scale check is the 2026-11-04 follow-up below.**

| Metric | Before (2026-10-25) | After (sessions started ≥ 01:15Z) | Unfiltered 1-day (all of 2026-10-28) | Verdict |
|---|---|---|---|---|
| skill_listing chars, median per session | 31,218 (`runtime-audit/report.md` line 174) | 21,213 (n=1 session, `2708ad7d…`, helper read over `audit-out/2026-10-28/` events); direct read of the lead's attachment in `~/.claude/projects/-Users-francisco-ruiz/5387f433-21f0-439e-bfc7-af27d19afb55.jsonl`: 17,873 chars (`content` of the `skill_listing` attachment, 2026-10-29T01:30:35.985Z) | 26,618 (n=60, `audit-out/2026-10-28/injection_costs.json` → `sources["attachment:skill_listing"].median_chars_per_session`) | Lower in both after-window readings (21,213 and 17,873 vs 31,218). n=1 and n=1, direction only. |
| first-request tokens, median `first_request_prompt_tokens` | 34,016 (all, line 172); lead median 52,300; teammate median 33,802 | 38,723.5 over n=2 (lead `main` 52,932; teammate `team:measurer` 24,515) | 27,110 (n=62 non-null, `injection_costs.json` → `first_request_prompt_tokens`) | Lead 52,932 vs 52,300 before: flat. Teammate 24,515 vs 33,802 before: lower. The n=2 pooled median mixes the two kinds and is not comparable with the pooled before. n=1 per kind. |
| SessionStart chars | 1,378 (`runtime-audit/report.md` line 103) | 564 | not applicable (a script run, not a window) | 564 vs 1,378: down 59%. Deterministic, so n does not matter. Command: `env -u TASK_OBSERVER_WORKSPACE bash ~/.claude/hooks/task-observer-session-start.sh </dev/null`, `additionalContext` length counted with `python3 -I`. |
| Stop durationMs: `stop-revalidate-user-gates` | median 1,064 ms (line 182) | 323 ms (1 Stop event, lead session `5387f433…`, 2026-10-29T01:32:20.532Z) | not collected | Lower; one run only. |
| Stop durationMs: `stop-wait-guard` | median 1,038 ms (line 182) | 906 ms (same event) | not collected | About the same; one run only. |
| Stop durationMs: `context-size-guard.sh` (new) | none (hook did not exist) | 386 ms (same event) | not collected | New cost of 386 ms per Stop; one run only. |
| Stop durationMs: `revise-claude-md-nudge.py` (not in Phase 1) | not listed in report.md | 180 ms (same event) | not collected | Context only. |

Stop-hook source: the `stop_hook_summary` line in `/Users/francisco.ruiz/.claude/projects/-Users-francisco-ruiz/5387f433-21f0-439e-bfc7-af27d19afb55.jsonl` (uuid `ac0744b1-54eb-4f4a-b175-052fc922c09c`), the session's only Stop event so far; `hookInfos[].durationMs` per command. Teammate session `2708ad7d…` had no Stop events.

## M4 check: name-only skill entries

In the lead's `skill_listing` attachment (same transcript, 2026-10-29T01:30:35.985Z; `content` is 17,873 chars), each of these appears as a bare list line with no description:

| Skill | Line in the listing | Name-only? |
|---|---|---|
| code-review | `- code-review` | yes |
| loop | `- loop` | yes |
| run | `- run` | yes |
| schedule | `- schedule` | yes |
| interior-design-expert | `- interior-design-expert` | yes |
| anthropic-skills:pdf | `- anthropic-skills:pdf` | yes |

Contrast, same listing: `- simplify: Review the changed code for reuse, simplification, efficiency…` and `- init: Initialize a new CLAUDE.md file with codebase documentation` keep their descriptions. The same bare lines are in this teammate's own skill list. n=2 sessions started after the install.

## Findings worth the lead's attention

- `claude/hooks/task-observer-session-start.sh` is mode `-rw-r--r--` (not executable) in `~/agent-board/claude/hooks/` and in this worktree; `~/.claude/hooks/task-observer-session-start.sh` is a link to it. Running it directly gives `Permission denied` (rc=126). `~/.claude/settings.json` line 74 invokes it as `sh ~/.claude/hooks/task-observer-session-start.sh`, which does not need the execute bit, so the hook works live. The mode only matters for direct runs. Not changed here.
- The session `5387f433…` transcript sits under `-Users-francisco-ruiz` (cwd was `~` at start), so `run_baseline.sh` scope filtering drops its early events (its `skill_listing` is missing from the helper count; hence the direct read above).

## Follow-up 2026-11-04

Run each command on that date. Week window = 2026-10-29 through 2026-11-04.

1. **Spawns with a non-tier model have a reason.** File: `~/.local/state/agent-board/spawns.jsonl` (one JSON object per line: `ts`, `lead_session`, `name`, `subagent_type`, `model`, `tier`, `reason`). Expected: no line printed.
   `python3 -I -c "import json,os;p=os.path.expanduser('~/.local/state/agent-board/spawns.jsonl');m={'mechanical':'haiku','standard':'sonnet','frontier':'fable'};[print(l.strip()) for l in open(p) if (d:=json.loads(l)) and m.get(d['tier'],d['model'])!=d['model'] and not d['reason']]"`
   (On 2026-10-28 the file had 1 line: `measurer`, tier standard, model sonnet, reason null — a match, so no reason needed.)
2. **Stop medians over the week.** Compare against 1,064 / 1,038 ms before, and the new `context-size-guard.sh` row:
   `bash tools/audit/run_baseline.sh 7`, then read Stop durations per command from `stop_hook_summary.hookInfos[].durationMs` with `tools/audit/transcripts.py` helpers (`system` events with `subtype == "stop_hook_summary"`), medians per command, sessions started ≥ 2026-10-29T01:15:00Z. Report n. The same run gives skill_listing and first-request medians for the week.
3. **Observations per week roughly hold.** Workspace `/Users/francisco.ruiz/.task-observer`; the observation log has 41 files on 2026-10-28:
   `ls /Users/francisco.ruiz/.task-observer/skill-observations/observation-log | wc -l` (then compare the increase over 7 days with earlier weeks by file mtime: `find /Users/francisco.ruiz/.task-observer/skill-observations/observation-log -type f -newermt 2026-10-29 | wc -l`).
4. **Review job marker and cost.** Marker file: `cat /Users/francisco.ruiz/.task-observer/skill-observations/review-started.txt` should read `completed <date>` (on 2026-10-28 it read `completed 2026-10-28`) or carry a `limit-hit` / `budget-hit` marker; a marker is not a failure of the job but must be explained. Cost check (ruling R7: default `REVIEW_BUDGET_USD=25`, assumed Opus list prices $5/$25/$6.25/$0.50 per MTok): `tail -40 /Users/francisco.ruiz/.task-observer/skill-observations/scheduled-review.log` and compare one real run's cost with $25; the script comments a normal run at about $8.3. `budget-hit` on a normal run means the cap is too low.
