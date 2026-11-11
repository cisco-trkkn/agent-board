source "${0:A:h}/bg_common.zsh"
# test_bg_lock.zsh — parallel first uses create one shell window; the run lock (a killed waiter, a stale lock), send latency, and output cut with a two-line prompt.
# race: two parallel first-uses create exactly one shell window
tt kill-session -t '=tt-bg' 2>/dev/null
$C run tests true >/dev/null & $C run tests true >/dev/null & wait
check "one shell window"       test "$(tt list-windows -t '=tt-bg' -F '#{window_name}' | grep -cx shell)" = 1
# a killed waiter must not delete the live holder's lock
sleep 60 & holder=$!
ld="$TC_STATE/lock-tt-tests"; mkdir "$ld"; print -r -- "$holder" > "$ld/pid"
$C run tests true >/dev/null 2>&1 &
waiter=$!
sleep 1; kill -TERM "$waiter"; wait "$waiter" 2>/dev/null
check "holder lock survives killed waiter" test "$(cat "$ld/pid" 2>/dev/null)" = "$holder"
kill "$holder"; wait "$holder" 2>/dev/null
check "stale lock then reclaimed"          test "$($C run tests 'echo after' | head -1)" = after
# send of an instant command must not hold the lock for seconds
s0=$EPOCHREALTIME
$C send shell 'echo x' >/dev/null
check "send returns fast"                  test $(( (EPOCHREALTIME - s0) < 2 )) = 1
# output is cut at an end marker, not by dropping the last line (two-line prompt, no trailing newline)
# (set through send: run wraps its command in a subshell, where a PS1 assignment would not stick)
$C send tests "PS1=\$'top\\nbot> '; PROMPT=\$PS1" >/dev/null; sleep 1
check "two-line prompt: only the output" test "$($C run tests 'echo x')" = $'x\n[exit 0]'
check "no trailing newline kept"         test "$($C run tests 'printf y')" = $'y\n[exit 0]'
no_stuck
tt_done
