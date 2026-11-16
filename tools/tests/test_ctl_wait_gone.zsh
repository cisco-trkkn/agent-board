source "${0:A:h}/lib.zsh"
# tmux-ctl wait-gone <name>... [--timeout <s>]: after shutdown_requests the lead waits, in the same turn, until every
# `✦ <name>` window of its session is gone; at the timeout it kills the ones left (spec 2026-11-10-queue-reliability §1).
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude
mk() { tt new-window -d -t "=${1}:" -n "$2" 'sleep 300' }
wid() { tt list-windows -t "=$1" -F '#{window_id} #{window_name}' | awk -v n="$2" '{ id=$1; sub(/^[^ ]+ /, "") } $0==n { print id }' }
has() { [[ -n "$(wid "$1" "$2")" ]] }
gone() { ! has "$@" }
zmodload zsh/datetime

# all gone: two windows that close after 1 s
mk tt '✦ a'; mk tt '✦ b'
ia="$(wid tt '✦ a')"; ib="$(wid tt '✦ b')"
( sleep 1; tt kill-window -t "$ia"; tt kill-window -t "$ib" ) &
t0=$EPOCHSECONDS
out="$($C wait-gone a b --timeout 20 2>&1)"; rc=$?
check "closed after 1 s: exit 0"                  test $rc -eq 0
check "closed after 1 s: prints all gone"         test "$out" = "wait-gone: all gone"
check "closed after 1 s: returns well before the timeout"  test $(( EPOCHSECONDS - t0 )) -lt 10
wait

# one stays: killed at the timeout
mk tt '✦ stay'
t0=$EPOCHSECONDS
out="$($C wait-gone stay --timeout 3 2>&1)"; rc=$?
check "stays: exit 3"                             test $rc -eq 3
check "stays: prints killed <name> after <s>s"    test "$out" = "wait-gone: killed stay after 3s"
check "stays: the window was killed"              gone tt '✦ stay'
check "stays: waited for the timeout"             test $(( EPOCHSECONDS - t0 )) -ge 3

# names match exactly: `✦ stay-2` is not `✦ stay`
mk tt '✦ stay-2'
out="$($C wait-gone stay --timeout 3 2>&1)"; rc=$?
check "exact match: a longer name does not count" test $rc -eq 0 -a "$out" = "wait-gone: all gone"
check "exact match: the longer-named window is left alone"  has tt '✦ stay-2'

# one gone, one left: only the one left is named and killed; the `✦ ` prefix in an argument is stripped
mk tt '✦ x'
out="$($C wait-gone '✦ x' nobody --timeout 2 2>&1)"; rc=$?
check "prefix stripped, mixed: exit 3"            test $rc -eq 3
check "prefix stripped, mixed: names only x"      test "$out" = "wait-gone: killed x after 2s"
check "mixed: bystander still alive"              has tt '✦ stay-2'

# only the caller's session counts
tt new-session -d -s other -n '✦ a' -c "$TT_DIR" 'sleep 300'
out="$($C wait-gone a --timeout 2 2>&1)"; rc=$?
check "other session: its window does not count"  test $rc -eq 0 -a "$out" = "wait-gone: all gone"
check "other session: its window is left alone"   has other '✦ a'

# a tmux error is never read as "no windows": the listing fails (no session `nosuch`), so the name is not gone
t0=$EPOCHSECONDS
out="$(TC_SESSION=nosuch $C wait-gone a --timeout 2 2>&1)"; rc=$?
check "listing fails: exit 3, not all gone"        test $rc -eq 3 -a "$out" != "wait-gone: all gone"
check "listing fails: prints could not kill"       test "$out" = "wait-gone: could not kill a"
check "listing fails: waited for the timeout"      test $(( EPOCHSECONDS - t0 )) -ge 2

# wait-gone clears the names it saw go from the lead's shutdown-pending file, so a teammate respawned under the same name
# is not reported "still shutting down" by the Stop guard (final review I-1)
G="$TT_REPO/claude/plugin/scripts/lead-stop-guard.sh"
SID=aaaaaaaa-1111-2222-3333-444444444444
PD="$TC_STATE/shutdown-pending"; PF="$PD/$SID"; CF="$TC_STATE/stop-guard/$SID"
guard() { print -r -- '{"session_id":"'"$SID"'","hook_event_name":"Stop","stop_hook_active":false}' | AGENT_BOARD_LEAD=1 TMUX="$TMUX" TMUX_PANE="$TMUX_PANE" "$G" --scoped; }
mkdir -p "$PD" "${CF:h}"; print -rl -- alpha beta > "$PF"; print -r -- "1 1" > "$CF"
mk tt '✦ beta'
out="$(CLAUDE_CODE_SESSION_ID=$SID $C wait-gone alpha --timeout 2 2>&1)"; rc=$?
check "pending: a gone name prints all gone, exit 0"  test $rc -eq 0 -a "$out" = "wait-gone: all gone"
check "pending: only the gone name was removed"      test "$(<$PF)" = beta
out="$(CLAUDE_CODE_SESSION_ID=$SID $C wait-gone beta --timeout 2 2>&1)"; rc=$?
check "pending: a name killed at the timeout: unchanged output and exit"  test $rc -eq 3 -a "$out" = "wait-gone: killed beta after 2s"
check "pending: the last name gone: file and counter deleted"  test ! -e "$PF" -a ! -e "$CF"
print -rl -- alpha > "$PF"; mk tt '✦ alpha'
out="$(CLAUDE_CODE_SESSION_ID=$SID $C wait-gone alpha --timeout 2 2>&1)"
mk tt '✦ alpha'
check "respawned same name after wait-gone: the guard allows, prints nothing"  test -z "$(guard)"
kw() { tt kill-window -t "$(wid tt "$1")" }
kw '✦ alpha'
print -rl -- alpha beta > "$PF"
out="$($C wait-gone alpha --timeout 2 2>&1)"; rc=$?
check "no CLAUDE_CODE_SESSION_ID: pending file untouched"  test "$(<$PF)" = "$(print -rl -- alpha beta)"
out="$(CLAUDE_CODE_SESSION_ID='../x' $C wait-gone alpha --timeout 2 2>&1)"
check "odd session id: pending file untouched"       test "$(<$PF)" = "$(print -rl -- alpha beta)"
rm -f "$PF"
out="$(CLAUDE_CODE_SESSION_ID=$SID $C wait-gone alpha --timeout 2 2>&1)"; rc=$?
check "no pending file: nothing created, exit 0"     test $rc -eq 0 -a ! -e "$PF"

# usage
out="$(env -u TMUX -u TMUX_PANE $C wait-gone a 2>&1)"; rc=$?
check "outside tmux: exit 2"                      test $rc -eq 2
U="tmux-ctl: usage: tmux-ctl wait-gone <name>... [--timeout <s>]"
out="$($C wait-gone 2>&1)"; rc=$?
check "no name: usage, exit 2"                    test $rc -eq 2 -a "$out" = "$U"
out="$($C wait-gone a --timeout 2>&1)"; rc=$?
check "--timeout without a value: usage, exit 2"  test $rc -eq 2 -a "$out" = "$U"
out="$($C wait-gone a --timeout soon 2>&1)"; rc=$?
check "--timeout not a number: usage, exit 2"     test $rc -eq 2 -a "$out" = "$U"
check "help lists wait-gone"                      sh -c "$C help | grep -q 'tmux-ctl wait-gone'"
check "help still ends at the blank line"         test "$($C help | tail -1)" = ""
tt_done
