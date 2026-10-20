#!/bin/bash
# Fixture test for task-observer-session-start.sh: the single task-observer mandate. Runs against temp workspaces.
set -u
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
for s in 'Before the first tool call' 'before writing or proposing a plan' 'Session Start Protocol' 'storage check, frontmatter scan, review trigger' 'no Skill arguments' 'teammate or subagent' 'final report for the lead to log' "Workspace root (pinned" "$empty/skill-observations/" "$empty/skill-updates/" 'new-observation.sh' 'skill-creator' 'cross-cutting-principles.md' 'com.user.task-observer-review' 'com.user.claude-md-monthly-report' '7+ days old'; do
  check "mandate text has: $s" "$(printf '%s' "$out" | grep -cF -- "$s")" "1"
done
check "empty workspace: no open count" "$(printf '%s' "$out" | grep -c 'open observations')" "0"
check "overdue: open count and date" "$(text "$overdue" | grep -c '1 open observations; last review: 2026-01-01. Offer the review.')" "1"
check "fresh: no review offer" "$(text "$fresh" | grep -c 'Offer the review')" "0"
check "fresh: open count" "$(text "$fresh" | grep -c '1 open observations')" "1"
check "never reviewed: offer" "$(text "$never" | grep -c 'last review: never. Offer the review.')" "1"
check "quote in workspace path: still valid JSON" "$(text "$quoted" | grep -cF 'with "quote"')" "1"

rm -rf "$T"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
