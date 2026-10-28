#!/bin/bash
# Test for spawn-record.sh. Fixture tool_input key set (name, subagent_type, model, prompt, description)
# copied from a real Agent tool_use in session b4eb2c48-f5e7-4c7b-aab3-0e30c923339b; prompt text replaced.
# Isolation: AGENT_BOARD_SPAWNS and cwd point into a temp dir; nothing under $HOME is written.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
H="${HOOK:-$HERE/../spawn-record.sh}"
FX="$HERE/fixtures/agent-posttooluse.json"
ROOT="$(cd "$HERE/../../.." && pwd)"
T=$(mktemp -d)
mkdir -p "$T/repo/docs/superpowers"; cp "$ROOT/docs/superpowers/model-routing.json" "$T/repo/docs/superpowers/"
mkdir -p "$T/bare"
export AGENT_BOARD_SPAWNS="$T/state/sub/spawns.jsonl"   # directory absent: hook must create it
pass=0; fail=0
REAL_EXISTED=0; [ -e "$HOME/.local/state/agent-board/spawns.jsonl" ] && REAL_EXISTED=1
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
mk() { python3 -I - "$FX" "$1" "$2" "$3" "$4" <<'PY'
import json, sys
fx, cwd, model, prompt, tool = sys.argv[1:6]
d = json.load(open(fx)); d["cwd"] = cwd; d["tool_name"] = tool
if model == "-": d["tool_input"].pop("model", None)
else: d["tool_input"]["model"] = model
d["tool_input"]["prompt"] = prompt
print(json.dumps(d))
PY
}
last() { tail -n 1 "$AGENT_BOARD_SPAWNS" | python3 -I -c "import json,sys; print(json.load(sys.stdin).get('$1'))"; }
lines() { [ -f "$AGENT_BOARD_SPAWNS" ] && wc -l < "$AGENT_BOARD_SPAWNS" | tr -d ' ' || echo 0; }
run() { out=$(printf '%s' "$1" | bash "$H" 2>&1); rc=$?; }

run "$(mk "$T/repo" sonnet $'Do it.\nReason: fable-limit \nthanks' Agent)"
check "exit 0" "$rc" "0"; check "no output" "$out" ""
check "dir created, one line" "$(lines)" "1"
check "tier standard" "$(last tier)" "standard"
check "reason captured" "$(last reason)" "fable-limit"
check "model kept" "$(last model)" "sonnet"
check "lead_session" "$(last lead_session)" "lead-session-1"
check "name" "$(last name)" "trace"
check "subagent_type" "$(last subagent_type)" "effort-medium"
check "ts epoch" "$(last ts | grep -Ec '^[0-9]{10}$')" "1"
check "seven fields" "$(tail -n 1 "$AGENT_BOARD_SPAWNS" | python3 -I -c 'import json,sys; print(len(json.load(sys.stdin)))')" "7"

run "$(mk "$T/repo" - 'No reason here.' Agent)"
check "no model: inherit" "$(last model)" "inherit"
check "no model: tier null" "$(last tier)" "None"
check "no Reason line: null" "$(last reason)" "None"
run "$(mk "$T/repo" opus 'x' Agent)"
check "opus: tier null" "$(last tier)" "None"
run "$(mk "$T/repo" haiku 'x' Agent)"
check "haiku: mechanical" "$(last tier)" "mechanical"
run "$(mk "$T/repo" fable 'x' Agent)"
check "fable: frontier" "$(last tier)" "frontier"
run "$(mk "$T/bare" sonnet 'x' Agent)"
check "no routing file: tier null" "$(last tier)" "None"
check "six lines so far" "$(lines)" "6"

n=$(lines)
run "$(mk "$T/repo" sonnet 'x' Bash)"
check "Bash: exit 0" "$rc" "0"; check "Bash: no output" "$out" ""; check "Bash: no line" "$(lines)" "$n"
run "not json"
check "malformed: exit 0" "$rc" "0"; check "malformed: no output" "$out" ""; check "malformed: no line" "$(lines)" "$n"
run ""
check "empty: exit 0" "$rc" "0"; check "empty: no line" "$(lines)" "$n"

# leak check: the real spawns file must not have been created or touched by this run
REAL="$HOME/.local/state/agent-board/spawns.jsonl"
check "no leak to real spawns file" "$([ "${REAL_EXISTED:-0}" = 1 ] && echo skip || { [ -e "$REAL" ] && echo leaked || echo ok; })" "$([ "${REAL_EXISTED:-0}" = 1 ] && echo skip || echo ok)"
rm -rf "$T"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
