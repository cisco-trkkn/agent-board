# Runtime Phase 1 — before/after measurement (Task 13)

Measured 2026-10-28 (evening, EDT) on toolkit SHA 45781bb. The live config was swapped 2026-10-28 ~21:15 EDT (= 2026-10-29T01:15:00Z).

**Sources.** *Before* = `docs/superpowers/reports/runtime-audit/report.md` (the 2026-10-25 audit). That report stands in for the deleted 2026-10-25 `injection_costs.json`, per lead ruling. *After* = `bash tools/audit/run_baseline.sh 1` run from this worktree, outputs in `audit-out/2026-10-28/` (gitignored): `injection_costs.json`, `session_metrics.json`, `manifest.json` (324 files in window, 64 in scope).

**After-window filter.** The 1-day JSON mixes sessions from before and after the install and has no per-session start time. After-window cells therefore come from a one-off `python3 -I` read that reuses `tools/audit/transcripts.py:iter_events` and `tools/audit/injection_costs.py:costs`. It keeps only sessions whose first transcript timestamp is at or after 2026-10-29T01:15:00Z. Two sessions qualify: `5387f433-21f0-439e-bfc7-af27d19afb55` (lead, started 01:30:34Z) and `2708ad7d-a79d-45ef-9c71-d299f67bbad5` (this teammate, started 01:32:16Z). The fourth column is a second, labelled figure: for the first three rows, the unfiltered 1-day figures (63 sessions in scope, mostly before the install); for the Stop rows, all user sessions started at or after 01:15Z (test-harness transcripts excluded, see below).

**Scope of every verdict: sessions started after the install only. skill_listing, first-request and SessionStart cells rest on n=2 sessions (n per cell is in the cell). Stop cells rest on one session (the lead, n=5 events) and, as the second figure, 3 user sessions (n=7 events). All are n<5 sessions or a handful of events, so no change is called significant. The week-scale check is the 2026-11-04 follow-up below.**

| Metric | Before (2026-10-25) | After (sessions started ≥ 01:15Z) | Second figure (scope in each cell) | Verdict |
|---|---|---|---|---|
| skill_listing chars, median per session | 31,218 (`runtime-audit/report.md` line 174) | 21,213 (n=1 session, `2708ad7d…`, helper read over `audit-out/2026-10-28/` events); direct read of the lead's attachment in `~/.claude/projects/-Users-francisco-ruiz/5387f433-21f0-439e-bfc7-af27d19afb55.jsonl`: 17,873 chars (`content` of the `skill_listing` attachment, 2026-10-29T01:30:35.985Z) | Unfiltered 1-day: 26,618 (n=60 sessions, `audit-out/2026-10-28/injection_costs.json` → `sources["attachment:skill_listing"].median_chars_per_session`) | Lower in both after-window readings (21,213 and 17,873 vs 31,218). n=1 and n=1, direction only. |
| first-request tokens, median `first_request_prompt_tokens` | 34,016 (all, line 172); lead median 52,300; teammate median 33,802 | 38,723.5 over n=2 (lead `main` 52,932; teammate `team:measurer` 24,515) | Unfiltered 1-day: 27,110 (n=62 non-null sessions, `injection_costs.json` → `first_request_prompt_tokens`) | Lead 52,932 vs 52,300 before: flat. Teammate 24,515 vs 33,802 before: lower. The n=2 pooled median mixes the two kinds and is not comparable with the pooled before. n=1 per kind. |
| SessionStart chars | 1,378 (`runtime-audit/report.md` line 103) | 564 | not applicable (a script run, not a session window) | 564 vs 1,378: down 59%. Deterministic, so n does not matter. Command: `env -u TASK_OBSERVER_WORKSPACE bash ~/.claude/hooks/task-observer-session-start.sh </dev/null`, `additionalContext` length counted with `python3 -I`. |
| Stop durationMs: `stop-revalidate-user-gates` | median 1,064 ms (line 182) | 420 ms (median of n=5 Stop events, lead session `5387f433…`, cutoff 2026-10-29T01:37:40Z) | 420 ms (n=7 events, 3 user sessions started ≥ 01:15Z, same cutoff) | Lower than 1,064 ms in both figures (420 ms both). n=5 events in one session; n=7 in 3 sessions. |
| Stop durationMs: `stop-wait-guard` | median 1,038 ms (line 182) | 1,116 ms (n=5, same session and cutoff) | 998 ms (n=7 events, 3 user sessions) | Lead session: 1,116 ms vs 1,038 ms before (8% higher). All three user sessions: 998 ms (4% lower). The two figures sit on either side of the before value, so no change is claimed. n=5 events in one session; n=7 in 3 sessions. |
| Stop durationMs: `context-size-guard.sh` (new) | none (hook did not exist) | 577 ms (n=5, same session and cutoff) | 577 ms (n=7 events, 3 user sessions) | New cost of about 0.58 s per Stop (577 ms in both figures). n=5 events in one session; n=7 in 3 sessions. |
| Stop durationMs: `revise-claude-md-nudge.py` (not in Phase 1) | median 115 ms (line 182; 1,991 runs) | 240 ms (n=5, same session and cutoff) | 240 ms (n=7 events, 3 user sessions) | Higher than 115 ms (240 ms in both figures). The hook was not changed in Phase 1; cause not measured. n=5 events in one session; n=7 in 3 sessions. |

Stop-hook source: every `stop_hook_summary` event in `/Users/francisco.ruiz/.claude/projects/-Users-francisco-ruiz/5387f433-21f0-439e-bfc7-af27d19afb55.jsonl` up to the cutoff 2026-10-29T01:37:40Z (latest event used: 01:37:37.944Z), n=5 events, `hookInfos[].durationMs` per command, median per command. The second figure is the same snippet over all user sessions whose first transcript timestamp is ≥ 01:15Z: 3 sessions (the lead, and two agent-board worktree sessions), n=7 events, same cutoff. Test-harness transcripts are excluded by default: an earlier run counted 35 sessions, 32 of which were test-harness transcripts (project folders under `/private/var/folders` or `/tmp`, the large majority `tctest` scratch directories from tmux test runs; the 32 is 35 minus the 3 user sessions), so it is not used; `--include-tests` reproduces it. Teammate session `2708ad7d…` had no Stop events. Both figures come from the snippet in the follow-up section (item 2), run as:

    python3 -I stopmed.py 2026-10-29T01:15:00Z 2026-10-29T01:37:40Z 5387f433-21f0-439e-bfc7-af27d19afb55   # lead session only
    python3 -I stopmed.py 2026-10-29T01:15:00Z 2026-10-29T01:37:40Z                                       # all user sessions

Cause of the differences between the lead session and the before medians: not measured (machine load at the time was not recorded). Stop medians still need the week-scale check.

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
2. **Stop medians over the week.** Compare against 1,064 / 1,038 / 115 ms before (`revise-claude-md-nudge` 115 ms) and the new `context-size-guard.sh` row. Save the snippet below as `stopmed.py` (it reads transcripts directly, so any working directory works) and run it for the whole week, with and without a session id (test-harness transcripts are skipped; `--include-tests` keeps them):

       python3 -I stopmed.py 2026-10-29T01:15:00Z 2026-11-04T23:59:59Z
       python3 -I stopmed.py 2026-10-29T01:15:00Z 2026-11-04T23:59:59Z <lead-session-id>

   It prints the session count, the latest event used, and `n` and the median `durationMs` per hook command; quote both in the verdict. The skill_listing and first-request medians for the week come from `bash tools/audit/run_baseline.sh 7`, which needs the repo root as the current directory (it locates the repo with `git rev-parse` from its own path and writes `audit-out/<date>/` there).

```python
# usage: python3 -I stopmed.py [--include-tests] FROM_UTC UNTIL_UTC|- [SESSION_ID ...]
# Median stop_hook_summary durationMs per hook command, over sessions whose first
# transcript timestamp is >= FROM_UTC, counting events up to UNTIL_UTC ("-" = no cutoff).
# Test-harness transcripts (project folder under /private/var/folders, /tmp or /private/tmp, or tctest) are
# skipped unless --include-tests is given.
import sys,json,glob,os,statistics,collections
from datetime import datetime,timezone
def ts(v):
    try: return datetime.fromisoformat(v.replace("Z","+00:00")).timestamp()
    except Exception: return None
args=[a for a in sys.argv[1:] if a!="--include-tests"]; tests="--include-tests" in sys.argv
cut=ts(args[0]); until=ts(args[1]) if args[1]!="-" else None; want=set(args[2:])
HARNESS=("-private-var-folders","-var-folders","-private-tmp","-tmp")
def harness(f):
    d=os.path.basename(os.path.dirname(f))
    return d.startswith(HARNESS) or "tctest" in d
by=collections.defaultdict(list); last=None; sessions=set()
for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
    sid=os.path.basename(f)[:-6]
    if want and sid not in want: continue
    if harness(f) and not tests: continue
    first=None; ev=[]
    for l in open(f,"rb"):
        try: d=json.loads(l)
        except ValueError: continue
        if not isinstance(d,dict): continue
        t=ts(d.get("timestamp"))
        if t and first is None: first=t
        if d.get("type")=="system" and d.get("subtype")=="stop_hook_summary" and t and (until is None or t<=until): ev.append((t,d))
    if first is None or first<cut or not ev: continue
    sessions.add(sid)
    for t,d in ev:
        last=max(last or t,t)
        for h in d.get("hookInfos",[]): by[h["command"]].append(h["durationMs"])
print("sessions",len(sessions),"latest event",datetime.fromtimestamp(last,timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ") if last else None)
for c,v in by.items(): print("n=%d median=%s ms  %s"%(len(v),statistics.median(v),c))
```

3. **Observations per week roughly hold.** Workspace `/Users/francisco.ruiz/.task-observer`; the observation log has 41 files on 2026-10-28:
   `ls /Users/francisco.ruiz/.task-observer/skill-observations/observation-log | wc -l` (then compare the increase over 7 days with earlier weeks by file mtime: `find /Users/francisco.ruiz/.task-observer/skill-observations/observation-log -type f -newermt 2026-10-29 | wc -l`).
4. **Review job marker and cost.** Marker file: `cat /Users/francisco.ruiz/.task-observer/skill-observations/review-started.txt` should read `completed <date>` (on 2026-10-28 it read `completed 2026-10-28`) or carry a `limit-hit` / `budget-hit` marker; a marker is not a failure of the job but must be explained. Cost check (ruling R7: default `REVIEW_BUDGET_USD=25`, assumed Opus list prices $5/$25/$6.25/$0.50 per MTok): `tail -40 /Users/francisco.ruiz/.task-observer/skill-observations/scheduled-review.log` and compare one real run's cost with $25; the script comments a normal run at about $8.3. `budget-hit` on a normal run means the cap is too low.
