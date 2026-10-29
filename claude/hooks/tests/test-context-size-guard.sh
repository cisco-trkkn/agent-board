#!/bin/bash
# Test for claude/hooks/context-size-guard.sh: events, once-per-50K-band, state file.
# Fixture context-transcript.jsonl is hand-built (the capture of a real transcript was refused); its last
# main-thread usage is copied from session 48822fd2's real last main-thread assistant line (sum 352042,
# band 7), plus an earlier smaller line and a sidechain line with a larger usage that must be ignored.
set -u
H="${HOOK:-$(cd "$(dirname "$0")/.." && pwd)/context-size-guard.sh}"
FX="$(cd "$(dirname "$0")" && pwd)/fixtures/context-transcript.jsonl"
REAL=$(ls "$HOME"/.claude/projects/*/48822fd2*.jsonl 2>/dev/null | head -1)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
pass=0; fail=0
RS="$HOME/.local/state/agent-board/context-guard"
rs_before=$(ls -A "$RS" 2>/dev/null | wc -l | tr -d ' ')
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
run() { # event sid transcript -> hook output
  jq -n --arg t "$3" --arg s "$2" --arg e "$1" \
    '{transcript_path:$t, hook_event_name:$e} + (if $s=="" then {} else {session_id:$s} end)' \
    | CLAUDE_CONTEXT_GUARD_STATE="${STATE:-$T/state}" "$H" 2>>"$T/err"
}
sm() { printf '%s' "$1" | jq -r "$2" 2>/dev/null; }

o=$(run UserPromptSubmit s1 "$FX")
check "UPS: systemMessage mentions 352K" "$(sm "$o" '.systemMessage' | grep -c '352K')" "1"
check "UPS: hookEventName" "$(sm "$o" '.hookSpecificOutput.hookEventName')" "UserPromptSubmit"
check "UPS: additionalContext has /handoff" "$(sm "$o" '.hookSpecificOutput.additionalContext' | grep -c '/handoff')" "1"
check "UPS: no teammate sentence" "$(printf '%s' "$o" | grep -c 'If you are a teammate')" "0"
check "band file holds 7" "$(cat "$T/state/s1.band")" "7"
check "same band twice -> one warning" "$(run UserPromptSubmit s1 "$FX" | wc -c | tr -d ' ')" "0"
check "same band, other event, still silent" "$(run Stop s1 "$FX" | wc -c | tr -d ' ')" "0"

o=$(run Stop s2 "$FX")
check "Stop: systemMessage present" "$(sm "$o" '.systemMessage | length > 0')" "true"
check "Stop: no hookSpecificOutput" "$(sm "$o" 'has("hookSpecificOutput")')" "false"
check "Stop: teammate sentence" "$(printf '%s' "$o" | grep -c 'If you are a teammate, tell the lead in your next message.')" "1"

o=$(run PostToolUse s3 "$FX")
check "PostToolUse: hookEventName" "$(sm "$o" '.hookSpecificOutput.hookEventName')" "PostToolUse"
check "PostToolUse: systemMessage present" "$(sm "$o" '.systemMessage | length > 0')" "true"
check "PostToolUse: teammate sentence" "$(sm "$o" '.hookSpecificOutput.additionalContext' | grep -c 'If you are a teammate, tell the lead in your next message.')" "1"

o=$(CLAUDE_CONTEXT_WARN_TOKENS=900000 run UserPromptSubmit s4 "$FX")
check "threshold above tokens -> silent" "$(printf '%s' "$o" | wc -c | tr -d ' ')" "0"
check "threshold above tokens -> no band file" "$([ -e "$T/state/s4.band" ] && echo yes || echo no)" "no"

a=$(run UserPromptSubmit "" "$FX" | wc -c | tr -d ' '); b=$(run UserPromptSubmit "" "$FX" | wc -c | tr -d ' ')
check "no session_id: warns first time" "$([ "$a" -gt 0 ] && echo yes)" "yes"
check "no session_id: warns again" "$([ "$b" -gt 0 ] && echo yes)" "yes"

# higher stored band is not re-warned; lower stored band is
mkdir -p "$T/state"; echo 3 > "$T/state/s5.band"
check "lower stored band -> warns" "$(run PostToolUse s5 "$FX" | wc -c | awk '{print ($1>0)}')" "1"
check "lower stored band -> updated to 7" "$(cat "$T/state/s5.band")" "7"

# after /compact (run below threshold) the band file is dropped and the next crossing warns again
a=$(run PostToolUse s6 "$FX" | wc -c | awk '{print ($1>0)}')
CLAUDE_CONTEXT_WARN_TOKENS=900000 run PostToolUse s6 "$FX" >/dev/null
check "compact: band file removed below threshold" "$([ -e "$T/state/s6.band" ] && echo yes || echo no)" "no"
b=$(run PostToolUse s6 "$FX" | wc -c | awk '{print ($1>0)}')
check "compact: warns, below, warns again" "$a$b" "11"

# unwritable state dir: silent on stderr, warns as without session_id
: > "$T/afile"; : > "$T/err"
u1=$(STATE="$T/afile/sub" run PostToolUse s7 "$FX" | wc -c | awk '{print ($1>0)}')
u2=$(STATE="$T/afile/sub" run PostToolUse s7 "$FX" | wc -c | awk '{print ($1>0)}')
check "unwritable state: warns every time" "$u1$u2" "11"
check "unwritable state: stderr empty" "$(wc -c < "$T/err" | tr -d ' ')" "0"

# Stop's systemMessage never reaches the model: Stop warns but must not use up the band
o=$(run Stop s8 "$FX")
check "Stop first: systemMessage present" "$(sm "$o" '.systemMessage | length > 0')" "true"
check "Stop first: no band file written" "$([ -e "$T/state/s8.band" ] && echo yes || echo no)" "no"
o=$(run UserPromptSubmit s8 "$FX")
check "Stop then UPS: UPS still emits additionalContext" "$(sm "$o" '.hookSpecificOutput.additionalContext' | grep -c '/handoff')" "1"
check "Stop then UPS: band recorded by UPS" "$(cat "$T/state/s8.band")" "7"
check "UPS repeated in same band: silent" "$(run UserPromptSubmit s8 "$FX" | wc -c | tr -d ' ')" "0"
echo 3 > "$T/state/s9.band"; run Stop s9 "$FX" >/dev/null
check "Stop leaves an existing band file alone" "$(cat "$T/state/s9.band")" "3"

# real-state replay of session 48822fd2 (read-only)
if [ -n "$REAL" ] && [ -f "$REAL" ]; then
  o=$(run PostToolUse real48822fd2 "$REAL")
  check "real 48822fd2 replay: PostToolUse" "$(sm "$o" '.hookSpecificOutput.hookEventName')" "PostToolUse"
  check "real 48822fd2 replay: 352K" "$(sm "$o" '.systemMessage' | grep -c '352K')" "1"
  check "real 48822fd2 replay: band 7" "$(cat "$T/state/real48822fd2.band")" "7"
else
  echo "SKIP real 48822fd2 replay: transcript not found"
fi

check "no leak under real state root (file count unchanged)" "$(ls -A "$RS" 2>/dev/null | wc -l | tr -d ' ')" "$rs_before"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
