#!/bin/bash
# Test for claude/plugin/scripts/telegram-env-scrub.sh (SessionStart): a Telegram lead keeps TELEGRAM_STATE_DIR in its own
# process (the plugin's MCP server needs it) but its Bash-tool shells get `unset TELEGRAM_STATE_DIR` from CLAUDE_ENV_FILE,
# so a `claude` started from the lead never polls (and SIGTERMs) the lead's bot. Isolation: CLAUDE_ENV_FILE is a temp file; no real state is touched.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
H="${HOOK:-$HERE/../../plugin/scripts/telegram-env-scrub.sh}"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
DIR="$T/telegram/proj-secret-dir"
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
# run <lead:1|0|-> <dir or -> <envfile or -> : stdout+stderr in $out, exit in $rc
run() {
  local -a e=(env -u AGENT_BOARD_LEAD -u TELEGRAM_STATE_DIR -u CLAUDE_ENV_FILE)
  [ "$1" != - ] && e+=("AGENT_BOARD_LEAD=$1")
  [ "$2" != - ] && e+=("TELEGRAM_STATE_DIR=$2")
  [ "$3" != - ] && e+=("CLAUDE_ENV_FILE=$3")
  out=$(printf '{"hook_event_name":"SessionStart"}' | "${e[@]}" bash "$H" --scoped 2>&1); rc=$?
}
n() { grep -cxF 'unset TELEGRAM_STATE_DIR' "$1" 2>/dev/null || true; }

F="$T/env1"; printf 'export OTHER=1\n' > "$F"
run 1 "$DIR" "$F"
# mutation: drop the append → no unset line
check "lead with the dir: appends one unset line"  "$(n "$F")" 1
check "lead: exit 0"                                "$rc" 0
check "lead: existing lines kept"                   "$(head -1 "$F")" 'export OTHER=1'
# mutation: print the dir → this fails
check "never prints the dir"                        "$(printf '%s' "$out" | grep -c "proj-secret-dir")" 0
run 1 "$DIR" "$F"; run 1 "$DIR" "$F"
# mutation: drop the duplicate check → 3 lines
check "idempotent (resume/clear/startup again)"     "$(n "$F")" 1
F2="$T/env2"; : > "$F2"
run 0 "$DIR" "$F2"
# mutation: drop the AGENT_BOARD_LEAD gate → a non-lead gets the unset line
check "not a lead (AGENT_BOARD_LEAD=0): nothing"    "$(n "$F2")" 0
run - "$DIR" "$F2"
check "no lead marker: nothing"                     "$(n "$F2")" 0
run 1 - "$F2"
check "no TELEGRAM_STATE_DIR: nothing"              "$(n "$F2")" 0
run 1 "$DIR" -
check "no CLAUDE_ENV_FILE: exit 0, nothing printed" "$rc:$out" "0:"
# real unpatched shell: what a Bash-tool command does with the file (sourced before each command)
F3="$T/env3"; : > "$F3"; run 1 "$DIR" "$F3"
seen=$(TELEGRAM_STATE_DIR="$DIR" bash -c '. "$1"; echo "${TELEGRAM_STATE_DIR-unset}"' _ "$F3")
check "a shell sourcing the file sees the var unset" "$seen" unset
echo "pass=$pass fail=$fail"; [ "$fail" = 0 ]
