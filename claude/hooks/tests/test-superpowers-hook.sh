#!/bin/bash
# Test for superpowers-hook.sh's Stop-guard short-circuit. Runs the installed plugin's real guard scripts
# (no SUPERPOWERS_PLUGIN_ROOT override); trace logs and the tasks root are temp paths, so nothing outside
# the temp dir is written. The fixture's shape (session_id, transcript_path, stop_hook_active) is what
# stop-wait-guard.sh reads at its INPUT=$(cat) block (plugin hooks/examples/stop-wait-guard.sh).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
H="${HOOK:-$HERE/../superpowers-hook.sh}"
FIX="$HERE/fixtures/stop-input.json"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }

: > "$T/transcript.jsonl"
sed "s#__TRANSCRIPT__#$T/transcript.jsonl#" "$FIX" > "$T/input.json"
jq '.session_id=""' "$T/input.json" > "$T/input-nosid.json"
SID8=abcdef12

# run <case> <hook> <input>: fresh tasks dir at $T/<case>/tasks, trace logs $T/<case>/{wait,gate}.log
run() {
  mkdir -p "$T/$1/tasks"
  SUPERPOWERS_TASKS_DIR="$T/$1/tasks" SUPERPOWERS_WAIT_GUARD_TRACE="$T/$1/wait.log" \
    SUPERPOWERS_USERGATE_TRACE_LOG="$T/$1/gate.log" bash "$H" "$2" < "$3" > "$T/$1/out" 2>&1
  echo $? > "$T/$1/rc"
}
lines() { [ -f "$1" ] && wc -l < "$1" | tr -d ' ' || echo 0; }
task() { mkdir -p "$T/$1/tasks/session-$SID8"; printf '%s' "$2" > "$T/$1/tasks/session-$SID8/1.json"; }

# 1: no task dir
run c1w stop-wait-guard.sh "$T/input.json"
run c1r stop-revalidate-user-gates.sh "$T/input.json"
check "no marker: wait-guard not run" "$(lines "$T/c1w/wait.log")" "0"
check "no marker: wait-guard exit 0" "$(cat "$T/c1w/rc")" "0"
check "no marker: revalidate not run" "$(lines "$T/c1r/gate.log")" "0"
check "no marker: revalidate exit 0" "$(cat "$T/c1r/rc")" "0"

# 2: only completed
mkdir -p "$T/c2w"; task c2w '{"id":"1","status": "completed"}'
run c2w stop-wait-guard.sh "$T/input.json"
check "completed only: wait-guard not run" "$(lines "$T/c2w/wait.log")" "0"

# 3: in_progress (compact and spaced)
mkdir -p "$T/c3w"; task c3w '{"id":"1","status": "in_progress"}'
run c3w stop-wait-guard.sh "$T/input.json"
check "in_progress: wait-guard runs" "$(lines "$T/c3w/wait.log")" "1"
mkdir -p "$T/c3b"; task c3b '{"id":"1","status":"in_progress"}'
run c3b stop-wait-guard.sh "$T/input.json"
check "in_progress (no space): wait-guard runs" "$(lines "$T/c3b/wait.log")" "1"
check "in_progress marker does not wake revalidate" "$(run c3w stop-revalidate-user-gates.sh "$T/input.json"; lines "$T/c3w/gate.log")" "0"

# 4/5: gate markers
mkdir -p "$T/c4"; task c4 '{"id":"1","description":"a USER-ORDERED GATE here","status":"pending"}'
run c4 stop-revalidate-user-gates.sh "$T/input.json"
check "user-ordered gate text: revalidate runs" "$(grep -c '| enter' "$T/c4/gate.log")" "1"
mkdir -p "$T/c5"; task c5 '{"id":"1","tags":["user-gate"],"status":"pending"}'
run c5 stop-revalidate-user-gates.sh "$T/input.json"
check "user-gate tag: revalidate runs" "$(grep -c '| enter' "$T/c5/gate.log")" "1"
mkdir -p "$T/c5b"; task c5b '{"id":"1","userGate":true,"status":"pending"}'
run c5b stop-revalidate-user-gates.sh "$T/input.json"
check "userGate field: revalidate runs" "$(grep -c '| enter' "$T/c5b/gate.log")" "1"

# 6: empty session_id passes through
run c6w stop-wait-guard.sh "$T/input-nosid.json"
run c6r stop-revalidate-user-gates.sh "$T/input-nosid.json"
check "empty session_id: wait-guard runs" "$(lines "$T/c6w/wait.log")" "1"
check "empty session_id: revalidate runs" "$(grep -c '| enter' "$T/c6r/gate.log")" "1"
jq 'del(.session_id)' "$T/input.json" > "$T/input-nokey.json"
run c6k stop-wait-guard.sh "$T/input-nokey.json"
check "missing session_id key: wait-guard runs" "$(lines "$T/c6k/wait.log")" "1"

# 7: post-task-complete is never short-circuited. Its guard logs "skip | tool=" because the Stop payload
# has no tool_name: that trace line proves the real script ran.
run c7 post-task-complete-revalidate.sh "$T/input.json"
check "post-task-complete: real script runs" "$(grep -c 'post-complete' "$T/c7/gate.log")" "1"

# stdin identity: a recorder plugin root captures the bytes the guard receives
R="$T/plugin"; mkdir -p "$R/hooks/examples" "$R/.claude-plugin"
echo '{"name": "superpowers-extended-cc"}' > "$R/.claude-plugin/plugin.json"
printf '#!/bin/bash\ncat > "%s/stdin.rec"\n' "$T" > "$R/hooks/examples/stop-wait-guard.sh"
mkdir -p "$T/c8/tasks"; task c8 '{"status": "in_progress"}'
SUPERPOWERS_PLUGIN_ROOT="$R" SUPERPOWERS_TASKS_DIR="$T/c8/tasks" bash "$H" stop-wait-guard.sh < "$T/input.json"
check "marker present: guard gets identical stdin" "$(cmp -s "$T/input.json" "$T/stdin.rec" && echo same)" "same"

echo "passed=$pass failed=$fail"
[ "$fail" = 0 ]
