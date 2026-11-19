source "${0:A:h}/lib.zsh"
# PreToolUse(AskUserQuestion) guard by role. The transcript fixture holds rows in the shape of a real lead transcript
# (78659598, 2026-11-19), ids and text replaced; its last user row has origin {kind: channel, server: plugin:discord:discord}.
H="${TC_REMOTE_GUARD:-$TT_REPO/claude/plugin/scripts/remote-ask-guard.sh}"
FIX="$TT_REPO/tools/tests/fixtures/remote/transcript-channel.jsonl"
tt_setup shell
tmp="$(mktemp -d "${TMPDIR:-/tmp}/rag.XXXXXX")"
trap 'rm -rf "$tmp"; tt_teardown' EXIT INT TERM
# the hook process of this test run may itself sit in a teammate: never let the real environment decide a role
unset CLAUDE_PID TC_ROLE AGENT_BOARD_LEAD REMOTE_ASK_GUARD
export REMOTE_GUARD_ARGS="claude --some-flag"
SID=sess-9; M="$TC_STATE/remote/$SID"; mkdir -p "$TC_STATE/remote"
TM='ask the lead with SendMessage; the user is not at your window'
LEAD='the user is remote: ask in Discord as a numbered list with the reply tool'
PEER='the user is remote: write the question as plain text and end your turn; it reaches Discord as a Needs you item'

# run <extra json keys as python dict literal> [tool]; env prefix via the variables set by the caller
payload() { python3 -c 'import json,sys; d={"session_id":"sess-9","hook_event_name":"PreToolUse","tool_name":sys.argv[2],"tool_input":{"questions":[{"question":"q?","header":"h","multiSelect":False,"options":[{"label":"A","description":"a"},{"label":"B","description":"b"}]}]}}; d.update(eval(sys.argv[1])); print(json.dumps(d))' "$1" "${2:-AskUserQuestion}"; }
run() { payload "$@" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
denies() { [[ $rc == 2 && -z "$out" && "$err" == "$1" ]]; }   # $(...) drops the trailing newline: exact text
silent() { [[ $rc == 0 && -z "$out" && -z "$err" ]]; }
setmark() { mkdir -p "$TC_STATE/remote"; : > "$M"; }
clr() { rm -f "$M"; }
# transcript with the fixture plus one extra last user row (text)
mk_tr() { python3 -c 'import json,sys; rows=[json.loads(l) for l in open(sys.argv[1])][:4]; rows.append({"type":"user","isSidechain":False,"uuid":"x","message":{"role":"user","content":sys.argv[3]}}); open(sys.argv[2],"w").write("".join(json.dumps(r)+"\n" for r in rows))' "$FIX" "$1" "$2"; }

clr; export TC_ROLE=worker; run '{}'
check "worker, no marker: teammate/worker text"          denies "$TM"
setmark; run '{}'
check "worker, marker: same text"                         denies "$TM"
unset TC_ROLE; clr; run '{"agent_id":"a1"}'
check "payload agent_id: same text"                       denies "$TM"
REMOTE_GUARD_ARGS="x --agent-id a@b" run '{}'
check "teammate argv (--agent-id): same text"             denies "$TM"
export AGENT_BOARD_LEAD=1; clr; run '{"agent_id":"a1"}'
check "lead without marker + agent_id: teammate text (order)"   denies "$TM"   # mutation: lead branch before agent_id -> this fails
setmark; run '{}'
check "lead + marker: remote-lead text"                   denies "$LEAD"
clr; run '{}'
check "lead without marker: rc 0 silent"                  silent
clr; run "{\"transcript_path\":\"$FIX\"}"
check "lead, channel transcript: remote-lead text"        denies "$LEAD"
check "  ... and the marker is now written"               test -f "$M"
setmark; mk_tr "$tmp/typed.jsonl" "do it now"; run "{\"transcript_path\":\"$tmp/typed.jsonl\"}"
check "lead, marker, last row typed: allowed"             silent
check "  ... and the marker is removed"                   test ! -e "$M"
setmark; mk_tr "$tmp/tm.jsonl" '<teammate-message teammate_id="x">r</teammate-message>'; run "{\"transcript_path\":\"$tmp/tm.jsonl\"}"
check "lead, marker, last row teammate-message: remote text" denies "$LEAD"
check "  ... marker kept"                                 test -f "$M"
setmark; run '{"transcript_path":"/nonexistent/t.jsonl"}'
check "lead, marker, missing transcript: marker decides"  denies "$LEAD"
unset AGENT_BOARD_LEAD
setmark; touch -t "$(date -v-1H +%Y%m%d%H%M 2>/dev/null || date -d '-1 hour' +%Y%m%d%H%M)" "$M"; run '{}'
check "peer, marker 1 h old: peer text"                   denies "$PEER"
touch -t "$(date -v-13H +%Y%m%d%H%M 2>/dev/null || date -d '-13 hours' +%Y%m%d%H%M)" "$M"; run '{}'
check "peer, marker 13 h old: allowed"                    silent   # mutation: drop the age test -> fails
clr; run '{}'
check "peer, no marker: allowed"                          silent
setmark; run '{}' Bash
check "other tool: allowed"                               silent
REMOTE_ASK_GUARD=0 run '{}'
check "REMOTE_ASK_GUARD=0 allows"                         silent
export TC_ROLE=worker; REMOTE_ASK_GUARD=0 run '{}'
check "REMOTE_ASK_GUARD=0 allows a worker too"            silent
unset TC_ROLE
# one real unpatched `ps -o args=` run: a live process whose argv holds --agent-id, named by CLAUDE_PID (no REMOTE_GUARD_ARGS seam)
clr; zsh -c "sleep 30; :" _ --agent-id real@probe & spid=$!; sleep 0.3
payload '{}' | env -u REMOTE_GUARD_ARGS CLAUDE_PID=$spid "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"
kill $spid 2>/dev/null
check "real ps of CLAUDE_PID with --agent-id in argv: teammate text"  denies "$TM"
echo 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed json: rc 0, no output"                   test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
tt_done
