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

# 4/5: revalidate reads the transcript's TaskCreate/TaskUpdate lines, not the task dir (Claude Code empties it).
# gate-taskcreate-line.jsonl has the structure of a real TaskCreate tool_use line with the text replaced.
tin() { sed "s#__TRANSCRIPT__#$T/$1#" "$FIX" > "$T/$1.in"; }
cp "$HERE/fixtures/gate-taskcreate-line.jsonl" "$T/gate.jsonl"; tin gate.jsonl
sed 's/"name":"TaskCreate"/"name":"TaskUpdate"/' "$T/gate.jsonl" > "$T/gateupd.jsonl"; tin gateupd.jsonl
cp "$HERE/fixtures/skill-listing-line.jsonl" "$T/listing.jsonl"; tin listing.jsonl
run c4 stop-revalidate-user-gates.sh "$T/gate.jsonl.in"
check "gate TaskCreate in transcript, no task dir: revalidate runs" "$(grep -c '| enter' "$T/c4/gate.log")" "1"
mkdir -p "$T/c5/tasks/session-$SID8"
run c5 stop-revalidate-user-gates.sh "$T/gate.jsonl.in"
check "gate TaskCreate in transcript, empty task dir: revalidate runs" "$(grep -c '| enter' "$T/c5/gate.log")" "1"
run c5b stop-revalidate-user-gates.sh "$T/gateupd.jsonl.in"
check "gate TaskUpdate line in transcript: revalidate runs" "$(grep -c '| enter' "$T/c5b/gate.log")" "1"
run c5c stop-revalidate-user-gates.sh "$T/listing.jsonl.in"
check "gate words only in a skill-listing line: revalidate skipped" "$(lines "$T/c5c/gate.log")" "0"
mkdir -p "$T/c5d"; task c5d '{"description":"USER-ORDERED GATE","status":"pending"}'
run c5d stop-revalidate-user-gates.sh "$T/listing.jsonl.in"
check "gate words only in a task-dir file: revalidate skipped" "$(lines "$T/c5d/gate.log")" "0"
sed "s#__TRANSCRIPT__#$T/missing.jsonl#" "$FIX" > "$T/missing.in"
run c5e stop-revalidate-user-gates.sh "$T/missing.in"
check "missing transcript: revalidate passes through to the guard" "$(lines "$T/c5e/gate.log")" "1"

# 6: empty session_id passes through
run c6w stop-wait-guard.sh "$T/input-nosid.json"
run c6r stop-revalidate-user-gates.sh "$T/input-nosid.json"
check "empty session_id: wait-guard runs" "$(lines "$T/c6w/wait.log")" "1"
check "empty session_id: revalidate (transcript with no gate line) skipped" "$(lines "$T/c6r/gate.log")" "0"
jq 'del(.session_id)' "$T/input.json" > "$T/input-nokey.json"
run c6k stop-wait-guard.sh "$T/input-nokey.json"
check "missing session_id key: wait-guard runs" "$(lines "$T/c6k/wait.log")" "1"

# 7: post-task-complete is never short-circuited. Its guard logs "skip | tool=" because the Stop payload
# has no tool_name: that trace line proves the real script ran.
run c7 post-task-complete-revalidate.sh "$T/input.json"
check "post-task-complete: real script runs" "$(grep -c 'post-complete' "$T/c7/gate.log")" "1"

# stdin identity: a recorder plugin root captures the bytes each guard receives
R="$T/plugin"; mkdir -p "$R/hooks/examples" "$R/.claude-plugin"
echo '{"name": "superpowers-extended-cc"}' > "$R/.claude-plugin/plugin.json"
for g in stop-wait-guard.sh stop-revalidate-user-gates.sh; do
  printf '#!/bin/bash\ncat > "%s/stdin.%s.rec"\n' "$T" "$g" > "$R/hooks/examples/$g"
done
mkdir -p "$T/c8/tasks"; task c8 '{"status": "in_progress"}'
SUPERPOWERS_PLUGIN_ROOT="$R" SUPERPOWERS_TASKS_DIR="$T/c8/tasks" bash "$H" stop-wait-guard.sh < "$T/input.json"
check "wait-guard gets identical stdin" "$(cmp -s "$T/input.json" "$T/stdin.stop-wait-guard.sh.rec" && echo same)" "same"
SUPERPOWERS_PLUGIN_ROOT="$R" SUPERPOWERS_TASKS_DIR="$T/c8/tasks" bash "$H" stop-revalidate-user-gates.sh < "$T/gate.jsonl.in"
check "revalidate gets identical stdin" "$(cmp -s "$T/gate.jsonl.in" "$T/stdin.stop-revalidate-user-gates.sh.rec" && echo same)" "same"

echo "passed=$pass failed=$fail"
[ "$fail" = 0 ]
