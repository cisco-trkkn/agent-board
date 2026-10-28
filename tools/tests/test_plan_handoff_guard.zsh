source "${0:A:h}/lib.zsh"
# Feeds PreToolUse JSON on stdin. The AskUserQuestion tool_input shape ({"questions":[{question,header,multiSelect,
# options}]}) was copied from a real session transcript on 2026-10-28.
H="${TC_PLANGUARD:-$TT_REPO/claude/plugin/scripts/plan-handoff-guard.sh}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/phg.XXXXXX")"
trap 'rm -rf "$tmp"; tt_teardown' EXIT INT TERM

# payload <header> <question> [tool] -> PreToolUse JSON
payload() { python3 -c 'import json,sys; print(json.dumps({"tool_name":sys.argv[3],"tool_input":{"questions":[{"question":sys.argv[2],"header":sys.argv[1],"multiSelect":False,"options":[{"label":"A","description":"a"},{"label":"B","description":"b"}]}]}}))' "$1" "$2" "${3:-AskUserQuestion}"; }
run_hook() { payload "$@" | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
denied()  { run_hook "$@"; [[ $rc == 2 && "$err" == *"superpowers-extended-cc:subagent-driven-development"* ]]; }
allowed() { run_hook "$@"; [[ $rc == 0 && -z "$out" && -z "$err" ]]; }
HANDOFF="Plan complete and saved to docs/superpowers/plans/x.md. How would you like to execute it?"

check "handoff question (header Execution) denied"        denied Execution "$HANDOFF"
check "header Execution with other text denied"          denied Execution "Plan complete and saved to x.md. Run it now?"
check "handoff text under another header denied"          denied "Run it" "How would you like to execute the plan?"
check "unrelated question allowed"                        allowed "Design 1" "Does this design look right?"
check "non-AskUserQuestion tool ignored"                  allowed Execution "$HANDOFF" Bash
check "deny reason says not to ask in any form"           zsh -c '[[ $1 == *"Do not call AskUserQuestion for the execution choice in any form"* ]]' _ "$(run_hook Execution "$HANDOFF"; print -r -- $err)"
echo 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed json: silent exit 0"                     test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Execution "$HANDOFF" | PLAN_HANDOFF_GUARD=0 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "PLAN_HANDOFF_GUARD=0 lets the handoff through"     test $rc -eq 0 -a ! -s "$tmp/e"
payload Execution "$HANDOFF" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?
check "--scoped registration denies the same way"         test $rc -eq 2
tt_done
