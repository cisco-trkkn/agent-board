source "${0:A:h}/lib.zsh"
# lead-stop-guard.sh (Stop): a lead may not end its turn while a teammate it asked to shut down still has its
# `✦ <name>` window, or while a self-started handoff has not relayed (spec 2026-11-10-queue-reliability §3).
# Stop stdin fields (session_id, hook_event_name, stop_hook_active, last_assistant_message, …) and the block output
# {"decision":"block","reason":…} were probed with a real `claude -p` Stop hook on 2026-11-16 (Claude Code 2.1.x).
H="${TC_STOP_GUARD:-$TT_REPO/claude/plugin/scripts/lead-stop-guard.sh}"
tt_setup claude
tmp="$TT_DIR/sg"; mkdir -p "$tmp"
SID=11111111-2222-3333-4444-555555555555
PD="$TC_STATE/shutdown-pending"; PF="$PD/$SID"; MF="$TC_STATE/handoff-pending/$SID"; CF="$TC_STATE/stop-guard/$SID"; LOG="$TC_STATE/stop-guard.log"
export AGENT_BOARD_LEAD=1
stdin() { print -r -- '{"session_id":"'"${1-$SID}"'","transcript_path":"/x.jsonl","cwd":"/x","hook_event_name":"Stop","stop_hook_active":false,"last_assistant_message":"I will relay once they confirm."}' }
run_hook() { stdin "$@" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; }
allowed() { [[ $rc == 0 && ! -s "$tmp/o" && ! -s "$tmp/e" ]] }
blocked() { [[ $rc == 0 && ! -s "$tmp/e" && "$(jq -r .decision "$tmp/o" 2>/dev/null)" == block && "$(jq -r .reason "$tmp/o")" == "$1" && "$(wc -l < "$tmp/o" | tr -d ' ')" == 1 ]] }
pend() { mkdir -p "$PD"; print -rl -- "$@" > "$PF" }
mk() { tt new-window -d -t '=tt:' -n "$1" 'sleep 300' }
kw() { tt kill-window -t "$(tt list-windows -t '=tt' -F '#{window_id} #{window_name}' | awk -v n="$1" '{ id=$1; sub(/^[^ ]+ /, "") } $0==n { print id }')" }
reset() { rm -rf "$PD" "$TC_STATE/handoff-pending" "$TC_STATE/stop-guard" "$LOG" }
RA="teammate(s) alpha still shutting down: run tmux-ctl wait-gone alpha, then continue"
RH="a self-started handoff has not relayed: run tmux-ctl relay <doc> --old-session $SID (handoff skill step 5)"

# nothing pending
run_hook
check "nothing pending: allow, prints nothing"       allowed

# a pending teammate whose window is still there
mk '✦ alpha'; pend alpha
run_hook
check "pending name with a window: block text"        blocked "$RA"
check "block: the pending file keeps the name"        test "$(<$PF)" = alpha
check "block: counter is <hash> 1"                    zsh -c '[[ "$(<$1)" == <->" 1" ]]' _ "$CF"

# only a lead inside tmux is guarded
AGENT_BOARD_LEAD= run_hook
check "not a lead: allow"                             allowed
check "not a lead: pending file untouched"            test "$(<$PF)" = alpha
( unset TMUX; run_hook; allowed ); check "no \$TMUX: allow"  test $? -eq 0

# two names, one window gone: the file is rewritten, the block names only the one left
pend alpha beta alpha
run_hook
check "one of two gone: block names only alpha"       blocked "$RA"
check "one of two gone: file rewritten to alpha"      test "$(<$PF)" = alpha
mk '✦ beta'; pend alpha beta
run_hook
check "two left: both named, in file order"           blocked "teammate(s) alpha beta still shutting down: run tmux-ctl wait-gone alpha beta, then continue"
kw '✦ beta'

# names match exactly: `✦ alpha-2` is not `✦ alpha`; another session's window does not count
kw '✦ alpha'; mk '✦ alpha-2'; tt new-session -d -s other -n '✦ alpha' -c "$TT_DIR" 'sleep 300'
pend alpha
run_hook
check "window gone (a longer name and another session's window remain): allow"  allowed
check "window gone: pending file deleted"             test ! -e "$PF"
check "window gone: counter deleted"                  test ! -e "$CF"
kw '✦ alpha-2'

# handoff marker
reset; mkdir -p "${MF:h}"; : > "$MF"
run_hook
check "handoff marker: block text"                    blocked "$RH"
mk '✦ alpha'; pend alpha
run_hook
check "teammate and handoff: both reasons"            blocked "$RA; $RH"
check "a changed reason restarts the count at 1"      zsh -c '[[ "$(<$1)" == <->" 1" ]]' _ "$CF"
rm -f "$MF"

# loop cap: the same reason blocks three times, the 4th is allowed and logged, then the count starts again
reset; pend alpha
for i in 1 2 3; do run_hook; check "loop cap: stop $i blocks"  blocked "$RA"; done
check "loop cap: counter says 3"                      zsh -c '[[ "$(<$1)" == <->" 3" ]]' _ "$CF"
run_hook
check "loop cap: 4th identical stop is allowed, prints nothing"  allowed
check "loop cap: one log line"                        test "$(wc -l < "$LOG" | tr -d ' ')" = 1
check "loop cap: log line = UTC time, session id, pending reason"  zsh -c '[[ "$(<$1)" == [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z" $2 allowed after 3 blocks: $3" ]]' _ "$LOG" "$SID" "$RA"
check "loop cap: counter reset"                       test ! -e "$CF"
check "loop cap: pending file kept"                   test "$(<$PF)" = alpha
run_hook
check "loop cap: the next stop blocks again"          blocked "$RA"

# another session's pending file is not this session's
reset; pend alpha
run_hook 99999999-2222-3333-4444-555555555555
check "another session id: allow"                     allowed
check "another session id: this file untouched"       test "$(<$PF)" = alpha

# fail-open
print -r -- 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed stdin: silent exit 0"                allowed
print -r -- '{"hook_event_name":"Stop"}' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "no session_id: silent exit 0"                  allowed
run_hook '../shutdown-pending/'"$SID"
check "session_id that is not a plain id: allow"      allowed
check "session_id that is not a plain id: file untouched"  test "$(<$PF)" = alpha
TMUX="$TT_DIR/no-such-socket,1,0" run_hook
check "tmux unreachable: silent exit 0"               allowed
check "tmux unreachable: pending file kept"           test "$(<$PF)" = alpha
kw '✦ alpha'
check "script is executable"                          test -x "$H"
tt_done
