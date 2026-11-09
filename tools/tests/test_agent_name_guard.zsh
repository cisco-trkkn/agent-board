source "${0:A:h}/lib.zsh"
# agent-name-guard: PreToolUse(Agent) hook that, in a dev lead (AGENT_BOARD_LEAD=1), denies an Agent call with no name
# or a fork. Payloads are synthetic hook JSON in the PreToolUse shape.
H="${TC_AGENTNAMEGUARD:-$TT_REPO/claude/plugin/scripts/agent-name-guard.sh}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ang.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT INT TERM

# payload <tool_name> <tool_input-json> -> PreToolUse JSON
payload() { python3 -c 'import json,sys; print(json.dumps({"tool_name":sys.argv[1],"transcript_path":"/nonexistent","cwd":"/tmp","tool_input":json.loads(sys.argv[2])}))' "$1" "$2"; }
# run_lead <tool_name> <tool_input-json>: run the hook as a dev lead
run_lead() { payload "$1" "$2" | AGENT_BOARD_LEAD=1 AGENT_NAME_GUARD= "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
denied()  { run_lead "$@"; [[ $rc == 2 && -z "$out" && "$err" == *"Give this agent a name"* && "$err" == *"never fall back to an unnamed agent"* && "$err" == *"AGENT_NAME_GUARD=0"* ]]; }
allowed() { run_lead "$@"; [[ $rc == 0 && -z "$out" && -z "$err" ]]; }

NAMED='{"description":"x","prompt":"y","subagent_type":"Explore","name":"scout"}'
check "lead, named Explore: allowed"                 allowed Agent "$NAMED"
check "lead, name missing: denied"                    denied Agent '{"description":"x","prompt":"y","subagent_type":"Explore"}'
check "lead, name empty: denied"                      denied Agent '{"description":"x","prompt":"y","name":""}'
check "lead, name blank: denied"                      denied Agent '{"description":"x","prompt":"y","name":"  "}'
check "lead, name not a string: denied"               denied Agent '{"description":"x","prompt":"y","name":7}'
check "lead, name null: denied"                       denied Agent '{"description":"x","prompt":"y","name":null}'
check "lead, named fork: denied"                      denied Agent '{"description":"x","prompt":"y","subagent_type":"fork","name":"f"}'
check "lead, non-Agent tool without name: allowed"    allowed Bash '{"command":"ls"}'
check "lead, tool_input not an object: allowed"       allowed Agent '"oops"'
print -r -- 'not json' | AGENT_BOARD_LEAD=1 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "lead, malformed JSON: silent exit 0"           test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Agent '{"description":"x","prompt":"y"}' | env -u AGENT_BOARD_LEAD "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "marker unset, unnamed: allowed"                test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Agent '{"description":"x","prompt":"y"}' | AGENT_BOARD_LEAD=0 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "marker 0, unnamed: allowed"                    test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Agent '{"description":"x","prompt":"y"}' | AGENT_BOARD_LEAD=1 AGENT_NAME_GUARD=0 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "kill switch AGENT_NAME_GUARD=0: allowed"       test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Agent '{"description":"x","prompt":"y"}' | AGENT_BOARD_LEAD=1 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "without --scoped denies the same way"          test $rc -eq 2
tt_done
