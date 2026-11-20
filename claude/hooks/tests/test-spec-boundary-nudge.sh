#!/bin/bash
# Test for claude/hooks/spec-boundary-nudge.sh (a link to claude/plugin/scripts/spec-boundary-nudge.sh).
# fixtures/taskupdate-posttooluse.json is a real PostToolUse payload of a TaskUpdate call (fixtures/README.md says how it
# was captured); each case swaps in its own session_id, taskId and status with jq and points the hook at a temp task folder.
set -u
H="${HOOK:-$(cd "$(dirname "$0")/.." && pwd)/spec-boundary-nudge.sh}"
FX="$(cd "$(dirname "$0")" && pwd)/fixtures/taskupdate-posttooluse.json"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
SID="abcdef12-0000-4000-8000-000000000000"; D="$T/tasks/session-abcdef12"; mkdir -p "$D"
MSG="Spec boundary: hand off now (agent-board:handoff) before the next Plan & run task."
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
mk() { jq -n --arg i "$1" --arg s "$2" --arg st "$3" '{id:$i, subject:$s, status:$st, blocks:[], blockedBy:[]}' > "$D/$1.json"; }
run() { # taskId status [tasks root] -> hook stdout
  jq --arg s "$SID" --arg i "$1" --arg st "$2" '.session_id=$s | .tool_input.taskId=$i | .tool_input.status=$st' "$FX" \
    | SPEC_NUDGE_TASKS_DIR="${3:-$T/tasks}" "$H" --scoped 2>>"$T/err"
}
before=$(ls -A "$D" | wc -l | tr -d ' ')

check "fixture is a TaskUpdate PostToolUse payload" "$(jq -r '.hook_event_name + " " + .tool_name' "$FX")" "PostToolUse TaskUpdate"
mk 55 "Plan & run: docs/superpowers/specs/a.md" completed
mk 18 "Plan & run: docs/superpowers/specs/b.md" pending
mk 60 "Task 1: something else" completed
o=$(run 55 completed)
check "completed Plan & run, another pending: message" "$(printf '%s' "$o" | jq -r '.hookSpecificOutput.additionalContext')" "$MSG"
check "completed Plan & run, another pending: event name" "$(printf '%s' "$o" | jq -r '.hookSpecificOutput.hookEventName')" "PostToolUse"
check "completed Plan & run, another pending: never blocks" "$(printf '%s' "$o" | jq -r 'has("decision")')" "false"
check "completed other task: nothing" "$(run 60 completed | wc -c | tr -d ' ')" "0"
check "Plan & run set to in_progress: nothing" "$(run 55 in_progress | wc -c | tr -d ' ')" "0"
mk 61 "Task 2: pending but not a spec" pending
mk 18 "Plan & run: docs/superpowers/specs/b.md" in_progress
check "completed Plan & run, none pending: nothing" "$(run 55 completed | wc -c | tr -d ' ')" "0"
mk 18 "Plan & run: docs/superpowers/specs/b.md" pending
check "the completed task itself still pending on disk does not count" "$(mk 55 'Plan & run: docs/superpowers/specs/a.md' pending; mk 18 'Plan & run: docs/superpowers/specs/b.md' completed; run 55 completed | wc -c | tr -d ' ')" "0"
o=$(printf 'not json' | SPEC_NUDGE_TASKS_DIR="$T/tasks" "$H" --scoped 2>>"$T/err"); rc=$?
check "malformed input: nothing" "$(printf '%s' "$o" | wc -c | tr -d ' ')" "0"
check "malformed input: rc 0" "$rc" "0"
o=$(run 55 completed "$T/no-such-root"); rc=$?
check "missing task folder: nothing, rc 0" "$(printf '%s' "$o" | wc -c | tr -d ' ') $rc" "0 0"
printf '{broken' > "$D/99.json"
mk 55 "Plan & run: docs/superpowers/specs/a.md" completed; mk 18 "Plan & run: docs/superpowers/specs/b.md" pending
check "a broken task file is skipped, message still sent" "$(run 55 completed | jq -r '.hookSpecificOutput.additionalContext')" "$MSG"
rm -f "$D/99.json"
check "read-only: task folder file count unchanged" "$(ls -A "$D" | wc -l | tr -d ' ')" "$((before + 4))"
check "stderr empty" "$(wc -c < "$T/err" | tr -d ' ')" "0"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
