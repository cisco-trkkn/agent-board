source "${0:A:h}/lib.zsh"
# teammate-stop.sh (a teammate's Stop writes <state>/teammates/<lead sid>/<name>.json) and teammate-remind.sh (the lead's
# Stop / PostToolUse remind once per teammate stop). Marker, name and lead session id: docs/superpowers/notes/2026-11-19-teammate-probes.md
# Probe A (`ps -o args= -p $CLAUDE_PID`: --agent-name, --parent-session-id); lead messages: Probe B (transcript <teammate-message> tags).
# Seam: TC_TEAMMATE_ARGS_FILE replaces the `ps` read with a file holding the args line; TC_NOW fixes the clock.
# The real `ps` path is run once, at the end, with a real process whose argv carries the flags.
HS="${TC_TEAMMATE_STOP:-$TT_REPO/claude/plugin/scripts/teammate-stop.sh}"
HR="${TC_TEAMMATE_REMIND:-$TT_REPO/claude/plugin/scripts/teammate-remind.sh}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/tmh.XXXXXX")"; tmp="${tmp:A}"
trap 'rm -rf "$tmp"; tt_teardown' EXIT INT TERM
export TC_STATE="$tmp/state"
LEAD=7bb5ac65-ad5f-4b3e-892a-d38d9a8fa8e9
SECRET=KEY-DO-NOT-LEAK-12345
D="$TC_STATE/teammates/$LEAD"
T0=1795133000
print -r -- "/x/claude --agent-id prober@t --agent-name prober --team-name t --agent-color blue --parent-session-id $LEAD --lead-verify-key $SECRET --agent-type general-purpose" > "$tmp/args-mate"
print -r -- "/x/claude --permission-mode default" > "$tmp/args-lead"
print -r -- "/x/claude --permission-mode default" > "$tmp/args-worker"

# stop_in <text>: a teammate's Stop input
stop_in() { python3 -c 'import json,sys
print(json.dumps({"session_id":"mate-own","hook_event_name":"Stop","stop_hook_active":False,"last_assistant_message":sys.argv[1]}))' "$1"; }
# run_stop <argsfile> <text> [lead flag]
run_stop() { stop_in "$2" | env TC_TEAMMATE_ARGS_FILE="$1" ${3:+AGENT_BOARD_LEAD=1} TC_NOW=$T0 "$HS" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; }
quiet() { [[ $rc == 0 && ! -s "$tmp/o" && ! -s "$tmp/e" ]] }
tmps() { [[ -z "$(find "$D" -name '*.tmp*' -o -name '.*tmp*' 2>/dev/null)" ]] }
field() { python3 -c 'import json,sys; v=json.load(open(sys.argv[1]))[sys.argv[2]]; print(v if not isinstance(v,str) else len(v) if sys.argv[3:]==["len"] else v)' "$@"; }

# ---- teammate Stop hook
run_stop "$tmp/args-mate" $'All done.\nSecond line'
check "stop: teammate writes <lead>/<name>.json"        test -f "$D/prober.json"
check "stop: json parses, name and first line"          test "$(python3 -c 'import json;d=json.load(open("'$D'/prober.json"));print(d["name"],"|",d["first_line"])')" = "prober | All done."
check "stop: ts is the clock"                           test "$(field "$D/prober.json" ts)" = $T0
check "stop: no temp file remains"                      tmps
check "stop: exit 0 and silent"                         quiet
check "stop: the lead-verify-key is nowhere in the state dir" zsh -c '! grep -rq "$1" "$2"' _ "$SECRET" "$TC_STATE"
run_stop "$tmp/args-mate" "$(python3 -c 'print("x"*5000)')"
check "stop: text capped at 2000"                       test "$(field "$D/prober.json" text len)" = 2000
rm -rf "$TC_STATE"
run_stop "$tmp/args-lead" "hi" 1
check "stop: lead writes nothing"                       test ! -e "$TC_STATE/teammates"
run_stop "$tmp/args-worker" "hi"
check "stop: worker writes nothing"                     test ! -e "$TC_STATE/teammates"
: > "$tmp/file"; stop_in hi | TC_STATE="$tmp/file/x" TC_TEAMMATE_ARGS_FILE="$tmp/args-mate" "$HS" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "stop: unwritable state dir: silent exit 0"       quiet
print -r -- 'not json' | TC_TEAMMATE_ARGS_FILE="$tmp/args-mate" "$HS" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "stop: malformed input: silent exit 0, no file"   zsh -c '[[ $1 == 0 && ! -e $2/teammates ]]' _ $rc "$TC_STATE"

# ---- lead reminder
# mk_tr <file> [name:epoch[:kind]...]: lead transcript, kind idle = automatic idle notification
mk_tr() { local f="$1"; shift; python3 -c 'import json,sys,datetime
out=[{"type":"user","timestamp":"2026-01-01T00:00:00.000Z","message":{"content":"typed prompt"}}]
for a in sys.argv[2:]:
    p=a.split(":"); n,t=p[0],int(p[1]); kind=p[2] if len(p)>2 else "msg"
    body="{\"type\":\"idle_notification\",\"from\":\"%s\"}"%n if kind=="idle" else "probe done"
    ts=datetime.datetime.fromtimestamp(t,datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    out.append({"type":"user","timestamp":ts,"message":{"content":"Another Claude session sent a message:\n<teammate-message teammate_id=\"%s\" color=\"blue\">\n%s\n</teammate-message>"%(n,body)}})
print("\n".join(json.dumps(o) for o in out))' x "$@" > "$f"; }
# rem <event> <argsfile> <now> [lead flag=1] [stop_hook_active]
rem() { python3 -c 'import json,sys
print(json.dumps({"session_id":sys.argv[1],"hook_event_name":sys.argv[2],"transcript_path":sys.argv[3],"stop_hook_active":sys.argv[4]=="1"}))' "$LEAD" "$1" "$tmp/tr" "${5:-0}" |
  env TC_TEAMMATE_ARGS_FILE="$2" ${4:+AGENT_BOARD_LEAD=1} TC_NOW="$3" "$HR" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; }
status() { mkdir -p "$D"; print -r -- '{"ts": '$1', "name": "'${2:-prober}'", "first_line": "'${3:-Report written}'", "text": "t"}' > "$D/${2:-prober}.json"; }
blocked() { grep -q '"decision": *"block"' "$tmp/o" }
HHMM=$(date -r $((T0+10)) +%H:%M 2>/dev/null || date -d @$((T0+10)) +%H:%M)

rm -rf "$TC_STATE"; mk_tr "$tmp/tr"; status $((T0+10))
rem Stop "$tmp/args-lead" $((T0+20)) 1
check "lead Stop: a stop with no later message blocks"  blocked
check "lead Stop: reason has name, HH:MM, first line"   grep -q "prober stopped at $HHMM: Report written — read its report file." "$tmp/o"
check "lead Stop: output is valid JSON"                 python3 -c 'import json;json.load(open("'$tmp/o'"))'
rem Stop "$tmp/args-lead" $((T0+30)) 1
check "lead Stop: second Stop, same ts: no block"       quiet
status $((T0+100))
rem Stop "$tmp/args-lead" $((T0+110)) 1
check "lead Stop: a newer stop blocks again"            blocked
rem Stop "$tmp/args-lead" $((T0+120)) 1
check "lead Stop: ... and once only"                    quiet

rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr" prober:$((T0+50))
rem Stop "$tmp/args-lead" $((T0+60)) 1
check "lead Stop: message newer than the stop: no reminder" quiet
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr" prober:$((T0-21))
rem Stop "$tmp/args-lead" $((T0+60)) 1
check "lead Stop: message 31 s before the stop, none after: reminder" blocked
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr" prober:$((T0+9))
rem Stop "$tmp/args-lead" $((T0+60)) 1
check "lead Stop: message 1 s before the stop (its report): no reminder" quiet
check "lead Stop: ... and the stop is recorded as handled" test "$(cat "$D/prober.reminded")" = $((T0+10))
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr" prober:$((T0-20))
rem Stop "$tmp/args-lead" $((T0+60)) 1
check "lead Stop: message exactly 30 s before the stop: no reminder" quiet
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr"
rem Stop "$tmp/args-lead" $((T0+60)) 1
check "lead Stop: no message at all: reminder"          blocked
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr" prober:$((T0-21))
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr" other:$((T0+50))
rem Stop "$tmp/args-lead" $((T0+60)) 1
check "lead Stop: another teammate's message does not count" blocked
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr" prober:$((T0+11)):idle
rem Stop "$tmp/args-lead" $((T0+60)) 1
check "lead Stop: the automatic idle notification does not count as a message" blocked
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr"
rem Stop "$tmp/args-lead" $((T0+60)) 1 1
check "lead Stop: stop_hook_active: no block"           quiet
rem Stop "$tmp/args-mate" $((T0+60)) 1
check "teammate: reminder hook silent"                  quiet
rem Stop "$tmp/args-worker" $((T0+60))
check "worker: reminder hook silent"                    quiet
rem Stop "$tmp/args-mate" $((T0+60))
check "teammate without lead flag: silent"              quiet
rem Stop "$tmp/args-lead" $((T0+60))
check "no lead flag: silent"                            quiet
check "silent runs recorded nothing"                    test ! -e "$D/prober.reminded"
rm -rf "$TC_STATE"
rem Stop "$tmp/args-lead" $((T0+60)) 1
check "lead Stop: no status files: silent exit 0"       quiet
print -r -- 'not json' | AGENT_BOARD_LEAD=1 TC_TEAMMATE_ARGS_FILE="$tmp/args-lead" "$HR" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed input: silent exit 0"                  quiet

# a non-lead pays nothing for a big tool response: the lead check comes before the input is read (bash 3.2 reads a pipe a byte at a time)
# mutation: move the AGENT_BOARD_LEAD check back below `read` -> 1 MB takes ~0.5 s here and the bound fails
python3 -c 'import sys; sys.stdout.write("{\"session_id\":\"s\",\"x\":\"" + "a"*1000000 + "\"}")' >"$tmp/big"
zmodload zsh/datetime; t0=$EPOCHREALTIME
env -u AGENT_BOARD_LEAD TC_TEAMMATE_ARGS_FILE="$tmp/args-lead" "$HR" <"$tmp/big" >"$tmp/o" 2>"$tmp/e"; rc=$?
big_s=$(( EPOCHREALTIME - t0 ))
print "  1 MB input, no lead: ${big_s}s"
check "1 MB input, no lead: silent exit 0"              quiet
check "1 MB input, no lead: under 0.15 s"               zsh -c '(( $1 < 0.15 ))' _ $big_s

# PostToolUse: additionalContext, at most once a minute
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr"
rem PostToolUse "$tmp/args-lead" $((T0+20)) 1
check "PostToolUse: additionalContext carries the reminder" python3 -c 'import json;d=json.load(open("'$tmp/o'"))["hookSpecificOutput"];assert d["hookEventName"]=="PostToolUse" and "prober stopped at" in d["additionalContext"]'
status $((T0+30)); status $((T0+30)) other "Other done"
rem PostToolUse "$tmp/args-lead" $((T0+40)) 1
check "PostToolUse: within a minute: silent"            quiet
rem PostToolUse "$tmp/args-lead" $((T0+81)) 1
check "PostToolUse: after a minute: reminds again"      grep -q 'prober stopped at' "$tmp/o"
check "PostToolUse: ... for each due teammate"          grep -q 'other stopped at' "$tmp/o"
rem PostToolUse "$tmp/args-lead" $((T0+200)) 1
check "PostToolUse: same ts again: silent"              quiet

# cheap early exits: a stub python3 first on PATH marks every `python3 -I` start (the hooks' own; the test helpers do not use -I)
mkdir -p "$tmp/shim"; print -r -- '#!/bin/sh
[ "$1" = -I ] && : > "$PYMARK"
exec '"$(command -v python3)"' "$@"' > "$tmp/shim/python3"; chmod +x "$tmp/shim/python3"
export PYMARK="$tmp/pystart"
rem_py() { rm -f "$PYMARK"; PATH="$tmp/shim:$PATH" rem "$@"; }
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr"
touch -t 202001010000 "$D/prober.json"   # -nt compares whole seconds: back-date the status so .reminded is strictly newer
rem_py PostToolUse "$tmp/args-lead" $((T0+20)) 1
check "early: a due stop starts python (shim works)"    test -e "$PYMARK"
rem_py PostToolUse "$tmp/args-lead" $((T0+300)) 1
check "early: nothing newer than its .reminded: no python" test ! -e "$PYMARK"
check "early: ... and the quiet run left no .last-remind update" test "$(cat "$D/.last-remind")" = $((T0+20))
touch -t 202001010000 "$D/prober.json"
rem_py Stop "$tmp/args-lead" $((T0+300)) 1
check "early: Stop, .reminded newer than the status: no python" test ! -e "$PYMARK"
rm -rf "$TC_STATE"
rem_py PostToolUse "$tmp/args-lead" $((T0+20)) 1
check "early: no teammates dir: no python"              test ! -e "$PYMARK"
status $((T0+10)); rem_py PostToolUse "$tmp/args-lead" $((T0+20)) ""
check "early: not a lead: no python"                    test ! -e "$PYMARK"
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr" prober:$((T0+9))
rem PostToolUse "$tmp/args-lead" $((T0+20)) 1
check "PostToolUse: a check that reaches the transcript and emits nothing"  quiet
check "PostToolUse: ... still writes .last-remind"      test "$(cat "$D/.last-remind")" = $((T0+20))
status $((T0+30))
rem PostToolUse "$tmp/args-lead" $((T0+40)) 1
check "PostToolUse: ... so a second check within a minute is silent" quiet
rm -rf "$TC_STATE"; status $((T0+10)); mk_tr "$tmp/tr"
rm -f "$PYMARK"; stop_in hi | PATH="$tmp/shim:$PATH" env TC_TEAMMATE_ARGS_FILE="$tmp/args-worker" "$HS" >/dev/null 2>&1
check "early: stop of a non-teammate: no python"        test ! -e "$PYMARK"
rm -f "$PYMARK"; stop_in hi | PATH="$tmp/shim:$PATH" env TC_TEAMMATE_ARGS_FILE="$tmp/args-mate" "$HS" >/dev/null 2>&1
check "early: stop of a teammate starts python"         test -e "$PYMARK"

# the real ps path, once: a real process whose argv carries the flags
sh -c 'while :; do sleep 1; done' claude --agent-name realmate --parent-session-id "$LEAD" --lead-verify-key $SECRET & rp=$!
sleep 0.3
rm -rf "$TC_STATE"
stop_in "real run" | env -u TC_TEAMMATE_ARGS_FILE CLAUDE_PID=$rp TC_NOW=$T0 "$HS" >"$tmp/o" 2>"$tmp/e"; rc=$?
kill $rp 2>/dev/null; wait $rp 2>/dev/null
check "real ps: name and lead id read from a real process" test "$(field "$D/realmate.json" text)" = "real run"
check "real ps: key not stored"                         zsh -c '! grep -rq "$1" "$2"' _ "$SECRET" "$TC_STATE"
sleep 1.5
check "leak: no stray process"                          zsh -c '! pgrep -f -- "--agent-name realmate" >/dev/null' _

tt_done
