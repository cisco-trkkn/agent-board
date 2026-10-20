#!/bin/bash
# Fixture test for revise-claude-md-nudge.py. Runs against a temp HOME.
set -u
H="$HOME/.claude/hooks/revise-claude-md-nudge.py"
T=$(mktemp -d)
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
run() { printf '%s' "$1" | HOME="$T" ${2:-} python3 "$H"; }

short="$T/short.jsonl"; long="$T/long.jsonl"; done_t="$T/done.jsonl"
for i in $(seq 5); do echo '{"type": "tool_use"}'; done > "$short"
for i in $(seq 45); do echo '{"type": "tool_use"}'; done > "$long"
cp "$long" "$done_t"; echo '{"skill": "claude-md-management:revise-claude-md"}' >> "$done_t"

check "short session silent" "$(run "{\"session_id\":\"s1\",\"transcript_path\":\"$short\"}")" ""
out=$(run "{\"session_id\":\"s2\",\"transcript_path\":\"$long\"}")
check "long session blocks" "$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["decision"])')" "block"
check "second stop silent (once per session)" "$(run "{\"session_id\":\"s2\",\"transcript_path\":\"$long\"}")" ""
check "stop_hook_active silent" "$(run "{\"session_id\":\"s3\",\"transcript_path\":\"$long\",\"stop_hook_active\":true}")" ""
check "disabled via env" "$(run "{\"session_id\":\"s4\",\"transcript_path\":\"$long\"}" "env CLAUDE_MD_REVISE_HOOK=0")" ""
check "already run by hand silent" "$(run "{\"session_id\":\"s5\",\"transcript_path\":\"$done_t\"}")" ""
check "bad stdin silent" "$(run "not json")" ""
check "lower threshold fires" "$(run "{\"session_id\":\"s6\",\"transcript_path\":\"$short\"}" "env CLAUDE_MD_REVISE_MIN_TOOL_USES=3" | grep -c block)" "1"

rm -rf "$T"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
