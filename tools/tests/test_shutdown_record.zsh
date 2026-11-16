source "${0:A:h}/lib.zsh"
# shutdown-record.sh (PostToolUse, matcher SendMessage): a shutdown_request adds its recipient to
# <TC_STATE>/shutdown-pending/<session_id>, which lead-stop-guard.sh reads (spec 2026-11-10-queue-reliability §3).
# The tool_input shapes below were copied from real lead transcripts on 2026-11-16: {to, message:{type,reason}} (the
# call as sent), the same with type/recipient/recipient_kind/content added (as recorded), and message as a JSON string.
H="${TC_SHUTDOWN_RECORD:-$TT_REPO/claude/plugin/scripts/shutdown-record.sh}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/sdr.XXXXXX")"; tmp="${tmp:A}"
trap 'rm -rf "$tmp"; tt_teardown' EXIT INT TERM
export TC_STATE="$tmp/state"
SID=11111111-2222-3333-4444-555555555555
PF="$TC_STATE/shutdown-pending/$SID"
# payload <to> <form: obj|rec|str|plain|resp> [tool] [session_id] -> PostToolUse JSON
payload() { python3 -c 'import json,sys
to, form, tool, sid = sys.argv[1:5]
req = {"type": "shutdown_request", "reason": "Done, thanks. To approve: first load the SendMessage schema."}
ti = {"to": to, "message": req}
if form == "rec": ti.update({"type": "shutdown_request", "recipient": to, "recipient_kind": "name", "content": "Done, thanks…"})
if form == "str": ti["message"] = json.dumps(req)
if form == "plain": ti = {"to": to, "summary": "note", "message": "please look at the shutdown_request handling"}
if form == "resp": ti["message"] = {"type": "shutdown_response", "request_id": "r1", "approve": True}
d = {"session_id": sid, "hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti, "tool_response": {"success": True}}
if not sid: del d["session_id"]
print(json.dumps(d))' "$1" "$2" "${3:-SendMessage}" "${4-$SID}"; }
run_hook() { payload "$@" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; }
quiet() { [[ $rc == 0 && ! -s "$tmp/o" && ! -s "$tmp/e" ]] }

run_hook alpha obj
check "object form: recipient recorded"            test "$(<$PF)" = alpha
check "object form: exit 0, prints nothing"        quiet
run_hook alpha rec
check "same name again (recorded shape): deduped"  test "$(<$PF)" = alpha
run_hook beta str
check "string form: recipient appended"            test "$(<$PF)" = $'alpha\nbeta'
check "string form: exit 0, prints nothing"        quiet
run_hook gamma plain
check "plain message: ignored"                     test "$(<$PF)" = $'alpha\nbeta'
run_hook gamma resp
check "shutdown_response: ignored"                 test "$(<$PF)" = $'alpha\nbeta'
run_hook gamma obj Bash
check "another tool: ignored"                      test "$(<$PF)" = $'alpha\nbeta'
rm -rf "$TC_STATE"
run_hook gamma plain
check "plain message alone: no file, no directory" test ! -e "$TC_STATE/shutdown-pending"
check "plain message: exit 0, prints nothing"      quiet
print -r -- 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed json: silent exit 0"              quiet
print -r -- '{"session_id":"'$SID'","tool_name":"SendMessage"}' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "no tool_input: silent exit 0"               quiet
run_hook alpha obj SendMessage ''
check "no session_id: silent, nothing written"     zsh -c '[[ ! -e $1/shutdown-pending ]]' _ "$TC_STATE" && quiet
run_hook alpha obj SendMessage '../../escape'
check "session_id that is not a plain id: nothing written"  test ! -e "$tmp/escape" -a ! -e "$TC_STATE/shutdown-pending"
run_hook $'two\nlines' obj
check "recipient with a newline: nothing written"  test ! -e "$PF"
# unwritable state dir: fail-open
: > "$tmp/file"; payload alpha obj | TC_STATE="$tmp/file/x" "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "unwritable state dir: silent exit 0"        quiet
# delivery: 20 hooks at once (a lead sends its shutdown_requests in one message), each name exactly once
for i in {1..20}; do payload "mate-$i" obj | "$H" & done; wait
check "20 concurrent records: 20 names"            test "$(wc -l < "$PF" | tr -d ' ')" = 20
check "20 concurrent records: none repeated or lost"  test "$(sort -u "$PF" | wc -l | tr -d ' ')" = 20
for i in {1..20}; do payload "mate-$i" obj | "$H" & done; wait
check "the same 20 again (redelivery): still 20"   test "$(wc -l < "$PF" | tr -d ' ')" = 20
check "script is executable"                       test -x "$H"
tt_done
