#!/bin/bash
# Fixture test for task-observer-session-start.sh: the observer stub (summary line + load-on-demand rule). Runs against temp
# workspaces; the README check and the size check read the real workspace (TASK_OBSERVER_WORKSPACE or ~/.task-observer), read-only.
set -u
unset TC_ROLE   # the lead's text is under test; a worker's environment would hide it
HERE="$(cd "$(dirname "$0")" && pwd)"
H="${HOOK:-$HERE/../task-observer-session-start.sh}"
T=$(mktemp -d)
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
text() { TASK_OBSERVER_WORKSPACE="$1" sh "$H" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])'; }
ws() { mkdir -p "$1/skill-observations/observation-log"; }

empty="$T/empty"; ws "$empty"
overdue="$T/overdue"; ws "$overdue"; printf 'status: open\n' > "$overdue/skill-observations/observation-log/0001.md"; echo 2026-01-01 > "$overdue/skill-observations/last-review-date.txt"
fresh="$T/fresh"; ws "$fresh"; printf 'status: open\n' > "$fresh/skill-observations/observation-log/0001.md"; date +%F > "$fresh/skill-observations/last-review-date.txt"
quoted="$T/with \"quote\""; ws "$quoted"
never="$T/never"; ws "$never"; printf 'status: open\n' > "$never/skill-observations/observation-log/0001.md"
completed="$T/completed"; ws "$completed"; date +%F > "$completed/skill-observations/last-review-date.txt"; echo "completed $(date +%F)" > "$completed/skill-observations/review-started.txt"
limit="$T/limit"; ws "$limit"; date +%F > "$limit/skill-observations/last-review-date.txt"; echo "limit-hit 2026-10-30" > "$limit/skill-observations/review-started.txt"
staged="$T/staged"; ws "$staged"; date +%F > "$staged/skill-observations/last-review-date.txt"
mkdir -p "$staged/skill-updates/2026-10-26" "$staged/skill-updates/2026-10-28" "$staged/skill-updates/.live-mirror"
printf '# Pending\n\n## 2026-10-28 (scheduled review): installed\n\nx\n\n## 2026-10-26 (scheduled review): awaiting install\n\ny\n' > "$staged/skill-updates/PENDING.md"
nopend="$T/nopend"; ws "$nopend"; date +%F > "$nopend/skill-observations/last-review-date.txt"
mkdir -p "$nopend/skill-updates/2026-10-26" "$nopend/skill-updates/2026-10-28" "$nopend/skill-updates/.live-mirror"
missing="$T/missing"   # no directory at all

out=$(text "$empty"); check "empty workspace: valid JSON" "$?" "0"
for s in 'Task observer: workspace ok · 0 open · last review never (due) · 0 staged updates.' 'no Skill arguments' 'only to write an observation, to run a review the user opted into, or to reconcile staged updates' 'scripts/new-observation.sh' 'Re-read this summary before writing or proposing a plan' 'Teammates and subagents never load it and report findings to the lead' "$empty" "Details: $empty/README.md."; do
  check "stub text has: $s" "$(printf '%s' "$out" | grep -cF -- "$s")" "1"
done
for s in 'Before the first tool call' 'Session Start Protocol' 'Any turn that will involve a tool call' 'build it with the skill-creator skill' 'cross-cutting-principles.md' 'com.user.task-observer-review' 'com.user.claude-md-monthly-report'; do
  check "stub text no longer has: $s" "$(printf '%s' "$out" | grep -cF -- "$s")" "0"
done
R="${TASK_OBSERVER_WORKSPACE:-$HOME/.task-observer}/README.md"
check "README exists" "$([ -f "$R" ] && echo yes)" "yes"
for s in 'skill-observations/' 'skill-updates/' 'cross-cutting-principles.md' 'skill-creator' 'com.user.task-observer-review' 'scheduled-review.log' 'com.user.claude-md-monthly-report' 'claude-md-reports/' '7+ days old' '.claude/worktrees/'; do
  check "README has: $s" "$(grep -cF -- "$s" "$R" | awk '{print ($1>0)}')" "1"
done
check "overdue: summary" "$(text "$overdue" | grep -cF 'workspace ok · 1 open · last review 2026-01-01 (due) · 0 staged updates.')" "1"
check "fresh: not due" "$(text "$fresh" | grep -cF 'last review '"$(date +%F)"' ·')" "1"
check "fresh: no (due)" "$(text "$fresh" | grep -cF '(due)')" "0"
check "fresh: open count" "$(text "$fresh" | grep -cF '1 open')" "1"
check "never reviewed: due" "$(text "$never" | grep -cF 'last review never (due)')" "1"
check "quote in workspace path: still valid JSON" "$(text "$quoted" | grep -cF 'with "quote"')" "1"
check "completed review-started: no fired part" "$(text "$completed" | grep -cF 'fired')" "0"
check "completed review-started: not due" "$(text "$completed" | grep -cF '(due)')" "0"
check "limit-hit review-started: fired part" "$(text "$limit" | grep -cF '· fired limit-hit 2026-10-30, no review recorded ·')" "1"
check "limit-hit review-started: due despite fresh date" "$(text "$limit" | grep -cF 'last review '"$(date +%F)"' (due) · fired')" "1"
check "staged: one awaiting install round" "$(text "$staged" | grep -cF '· 1 staged updates.')" "1"
check "no PENDING.md: counts directories, not dot-entries" "$(text "$nopend" | grep -cF '· 2 staged updates.')" "1"
check "missing workspace: MISSING" "$(text "$missing" | grep -cF 'workspace MISSING')" "1"
check "missing workspace: full protocol" "$(text "$missing" | grep -cF 'Run the full protocol: load the task-observer skill')" "1"
check "missing workspace: no summary counts" "$(text "$missing" | grep -cF 'staged updates')" "0"
real=$(TASK_OBSERVER_WORKSPACE="${TASK_OBSERVER_WORKSPACE:-$HOME/.task-observer}" sh "$H" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])')
echo "real workspace output (${#real} chars): $real"
check "real workspace: additionalContext <= 900 chars" "$([ "${#real}" -le 900 ] && echo yes)" "yes"
wout=$(TC_ROLE=worker TASK_OBSERVER_WORKSPACE="$overdue" sh "$H" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])')
check "worker: valid JSON" "$?" "0"
check "worker: output unchanged" "$wout" "Worker session (TC_ROLE=worker): do not invoke task-observer or write to its log; put any skill findings in your final report."
check "worker: no review offer" "$(printf '%s' "$wout" | grep -c 'due')" "0"
check "TC_ROLE=other: stub kept" "$(TC_ROLE=lead TASK_OBSERVER_WORKSPACE="$empty" sh "$H" | grep -cF 'Task observer: workspace ok')" "1"

rm -rf "$T"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
