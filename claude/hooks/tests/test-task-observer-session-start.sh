#!/bin/bash
# Fixture test for task-observer-session-start.sh: the single task-observer mandate. Runs against temp workspaces;
# the README check reads the real workspace (TASK_OBSERVER_WORKSPACE or ~/.task-observer).
set -u
unset TC_ROLE   # the lead's mandate is under test; a worker's environment would hide it
H="${HOOK:-$HOME/.claude/hooks/task-observer-session-start.sh}"
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

out=$(text "$empty"); check "empty workspace: valid JSON" "$?" "0"
for s in 'Before the first tool call' 'before writing or proposing a plan' 'Session Start Protocol' 'storage check, frontmatter scan, review trigger' 'no Skill arguments' 'teammate or subagent' 'final report for the lead to log' "Workspace root (pinned, never the cwd or a worktree under .claude/worktrees/): $empty." 'new-observation.sh' '7+ days old' "Details (paths, scheduled jobs, skill-creator rule): $empty/README.md."; do
  check "mandate text has: $s" "$(printf '%s' "$out" | grep -cF -- "$s")" "1"
done
for s in 'build it with the skill-creator skill' 'cross-cutting-principles.md' 'com.user.task-observer-review' 'com.user.claude-md-monthly-report' 'skill-updates/' 'skill-observations/'; do
  check "mandate text no longer has: $s" "$(printf '%s' "$out" | grep -cF -- "$s")" "0"
done
R="${TASK_OBSERVER_WORKSPACE:-$HOME/.task-observer}/README.md"
check "README exists" "$([ -f "$R" ] && echo yes)" "yes"
for s in 'skill-observations/' 'skill-updates/' 'cross-cutting-principles.md' 'skill-creator' 'com.user.task-observer-review' 'scheduled-review.log' 'com.user.claude-md-monthly-report' 'claude-md-reports/' '7+ days old' '.claude/worktrees/'; do
  check "README has: $s" "$(grep -cF -- "$s" "$R" | awk '{print ($1>0)}')" "1"
done
check "empty workspace: no open count" "$(printf '%s' "$out" | grep -c 'open observations')" "0"
check "overdue: open count and date" "$(text "$overdue" | grep -c '1 open observations; last review: 2026-01-01. Offer the review.')" "1"
check "fresh: no review offer" "$(text "$fresh" | grep -c 'Offer the review')" "0"
check "fresh: open count" "$(text "$fresh" | grep -c '1 open observations')" "1"
check "never reviewed: offer" "$(text "$never" | grep -c 'last review: never. Offer the review.')" "1"
check "quote in workspace path: still valid JSON" "$(text "$quoted" | grep -cF 'with "quote"')" "1"
wout=$(TC_ROLE=worker TASK_OBSERVER_WORKSPACE="$overdue" sh "$H" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])')
check "worker: valid JSON" "$?" "0"
check "worker: exemption text" "$(printf '%s' "$wout" | grep -cF 'do not invoke task-observer')" "1"
check "worker: no mandate" "$(printf '%s' "$wout" | grep -cF 'Before the first tool call')" "0"
check "worker: no review offer" "$(printf '%s' "$wout" | grep -c 'Offer the review')" "0"
check "TC_ROLE=other: mandate kept" "$(TC_ROLE=lead TASK_OBSERVER_WORKSPACE="$empty" sh "$H" | grep -cF 'Before the first tool call')" "1"

rm -rf "$T"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
