source "${0:A:h}/lib.zsh"
zmodload zsh/datetime
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup claude shell
check "run goes to bg"       test "$($C run tests 'echo hi' | head -1)" = hi
check "bg session exists"    tt has-session -t '=tt-bg'
check "bg flagged"           test "$(tt show-options -qv -t '=tt-bg:' @tc_bg)" = 1
check "bg windows"           test "$(tt list-windows -t '=tt-bg' -F '#{window_name}' | sort | tr '\n' ' ')" = "shell tests "
check "user shell untouched" sh -c "! $TT_BIN capture-pane -p -t '=tt:shell' | grep -q 'echo hi'"
r="$TC_STATE/runs-tt.jsonl"
check "start record"         test "$(jq -sr '[.[]|select(.cmd=="echo hi")]|first|.exit' "$r")" = null
check "final record"         test "$(jq -sr '[.[]|select(.cmd=="echo hi")]|last|.exit' "$r")" = 0
check "same id"              test "$(jq -sr '[.[]|select(.cmd=="echo hi")|.id]|unique|length' "$r")" = 1
lg="$(jq -sr 'last|.log' "$r")"
check "log written"          grep -qx hi "$lg"
check "session recorded"     test "$(jq -sr 'last|.session' "$r")" = tt-bg
$C run tests 'print "3 passed, 1 failed"; false' >/dev/null
check "summary parsed"       test "$(jq -sr 'last|.summary' "$r")" = "3 passed, 1 failed"
check "exit recorded"        test "$(jq -sr 'last|.exit' "$r")" = 1
check "agent recorded"       test "$(jq -sr 'last|.agent' "$r")" = claude
$C run tests 'print ALL PASS' >/dev/null
check "zsh summary"          test "$(jq -sr 'last|.summary' "$r")" = "ALL PASS"
check "list shows bg"        sh -c "$C list | grep -q 'tests .*(bg)'"
check "read bg"              sh -c "$C read tests 40 | grep -qx hi"
check "send to bg shell"     sh -c "$C send shell 'echo via-send' && sleep 1 && $TT_BIN capture-pane -p -t '=tt-bg:shell' | grep -q via-send"
# interrupted run: record must not stay at exit:null
$C run tests 'sleep 30' >/dev/null 2>&1 &
rp=$!
tt_wait 5 sh -c "jq -sr '[.[]|select(.cmd==\"sleep 30\")]|length' $r | grep -qx 1"
kill -TERM "$rp"                            # the PID we started
tt_wait 5 sh -c "jq -sr '[.[]|select(.cmd==\"sleep 30\")]|last|.exit' $r | grep -qx 143"
check "interrupted exit 143"   test "$(jq -sr '[.[]|select(.cmd=="sleep 30")]|last|.exit' "$r")" = 143
check "interrupted summary"    test "$(jq -sr '[.[]|select(.cmd=="sleep 30")]|last|.summary' "$r")" = interrupted
tt send-keys -t '=tt-bg:tests' C-c
# race: two parallel first-uses create exactly one shell window
tt kill-session -t '=tt-bg'
$C run tests true >/dev/null & $C run tests true >/dev/null & wait
check "one shell window"       test "$(tt list-windows -t '=tt-bg' -F '#{window_name}' | grep -cx shell)" = 1
# concurrent runs on one idle window must not interleave their typed lines
tt_wait 5 tt_all_idle
bad=0
for i in 1 2 3 4 5 6 7 8; do
  $C run tests 'echo A' >"$TT_DIR/oa" 2>&1 & $C run tests 'echo B' >"$TT_DIR/ob" 2>&1 & wait
  grep -qE 'bad math|jq:|printf\]' "$TT_DIR/oa" "$TT_DIR/ob" && (( bad++ ))
  grep -qx A "$TT_DIR/oa" && grep -qx B "$TT_DIR/ob" || (( bad++ ))
done
check "parallel runs stay clean" test $bad -eq 0
check "no stuck records"         test "$(jq -sr '[group_by(.id)[]|select(last.exit==null)]|length' "$r")" = 0
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
tt_done
