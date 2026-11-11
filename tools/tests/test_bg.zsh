source "${0:A:h}/lib.zsh"
zmodload zsh/datetime
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude shell
# Four independent sections run as concurrent subshells, each on its own scratch tmux server and TC_STATE (tmux-ctl run
# itself polls every 0.5 s, so a section is mostly waiting on it). Section output is kept and printed in order, FAIL lines
# are counted into TT_FAILS, and each section leaves a copy of its run records for the final "no stuck records" check.
SEC="$(mktemp -d "${TMPDIR:-/tmp}/ttbg.XXXXXX")"; SEC="${SEC:A}"
trap 'rm -rf "$SEC"; tt_teardown' EXIT INT TERM
sec() { local _sn=$1 own=$2; shift 2; ( trap - EXIT INT TERM; RANDOM=$(( _sn * 4099 + $$ % 4099 )); (( own )) && tt_setup claude shell; "$@"; cp "$TC_STATE/runs-tt.jsonl" "$SEC/rec-$_sn.jsonl" 2>/dev/null; (( own )) && tt_teardown ) > $SEC/out-$_sn 2>&1 & }   # _sn: the sections use n as a loop counter (dynamic scope)
sec1() {
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
}
sec 1 0 sec1
sec2() {
r="$TC_STATE/runs-tt.jsonl"
# interrupted run: record must not stay at exit:null
# waits are on conditions with a 30 s cap (one loaded iteration of this file takes ~60-100 s in all, so
# no single step needs more); a timeout fails the step under its own name
cap=30
# the run happens in the hidden session tt-bg (tt_all_idle only looks at tt): idle = a shell in tt-bg:tests
bg_idle() { tt list-panes -t '=tt-bg:tests' -F '#{pane_current_command}' | grep -qxE -e '-?(zsh|bash|sh)' }
touch "$r"   # this section starts on a fresh state dir: the polls below read $r before the first run creates it
sleep30() { jq -sr "[.[]|select(.cmd==\"sleep 30\")]|$1" "$r" }
$C run tests 'sleep 30' >/dev/null 2>&1 &
rp=$!
check "interrupt: start record"  tt_wait $cap sh -c "jq -sr '[.[]|select(.cmd==\"sleep 30\")]|length' $r | grep -qx 1"
check "interrupt: sleep running" tt_wait $cap sh -c "$TT_BIN list-panes -t '=tt-bg:tests' -F '#{pane_current_command}' | grep -qx sleep"
kill -TERM "$rp"                            # the PID we started
check "interrupt: exit 143 written" tt_wait $cap sh -c "jq -sr '[.[]|select(.cmd==\"sleep 30\")]|last|.exit' $r | grep -qx 143"
check "interrupted exit 143"   test "$(sleep30 'last|.exit')" = 143
check "interrupted summary"    test "$(sleep30 'last|.summary')" = interrupted
tt send-keys -t '=tt-bg:tests' C-c
check "interrupt: pane idle again" tt_wait $cap bg_idle
# TERM the instant the start record lands (no wait for the run to settle): the record must still end at 143.
# The window is a race, so 6 trials; each one is its own command text.
for i in 1 2 3 4 5 6; do
  $C run tests "sleep 3$i" >/dev/null 2>&1 &
  rp=$!
  n=0; until grep -q "\"sleep 3$i\"" "$r" 2>/dev/null; do (( n++ >= cap * 100 )) && break; sleep 0.01; done   # tight poll (the race), bounded
  check "early TERM $i: start record" grep -q "\"sleep 3$i\"" "$r"
  kill -TERM "$rp"; wait "$rp" 2>/dev/null
  check "early TERM $i: exit 143 written" tt_wait $cap sh -c "jq -sr '[.[]|select(.cmd==\"sleep 3$i\")]|last|.exit' $r | grep -qx 143"
  check "early TERM $i: summary"    test "$(jq -sr "[.[]|select(.cmd==\"sleep 3$i\")]|last|.summary" "$r")" = interrupted
  tt send-keys -t '=tt-bg:tests' C-c
  check "early TERM $i: pane idle again" tt_wait $cap bg_idle
done
}
sec 2 1 sec2
# pairs <first> <last> <section>: concurrent run pairs on one idle window; the count of bad iterations goes to $SEC/bad-<section>
pairs() {
  tt_wait 5 tt_all_idle
  local i bad=0
  for i in {$1..$2}; do
    $C run tests 'echo A' >"$TT_DIR/oa" 2>&1 & $C run tests 'echo B' >"$TT_DIR/ob" 2>&1 & wait
    grep -qE 'bad math|jq:|printf\]' "$TT_DIR/oa" "$TT_DIR/ob" && (( bad++ ))
    grep -qx A "$TT_DIR/oa" && grep -qx B "$TT_DIR/ob" || (( bad++ ))
  done
  print -r -- $bad > $SEC/bad-$3
}
sec5() { pairs 5 8 5 }
sec3() {
r="$TC_STATE/runs-tt.jsonl"
# race: two parallel first-uses create exactly one shell window
tt kill-session -t '=tt-bg' 2>/dev/null
$C run tests true >/dev/null & $C run tests true >/dev/null & wait
check "one shell window"       test "$(tt list-windows -t '=tt-bg' -F '#{window_name}' | grep -cx shell)" = 1
# concurrent runs on one idle window must not interleave their typed lines (iterations 1-4 here, 5-8 in section 5)
pairs 1 4 3
}
sec 3 1 sec3
sec4() {
r="$TC_STATE/runs-tt.jsonl"
# a killed waiter must not delete the live holder's lock
sleep 60 & holder=$!
ld="$TC_STATE/lock-tt-tests"; mkdir "$ld"; print -r -- "$holder" > "$ld/pid"
$C run tests true >/dev/null 2>&1 &
waiter=$!
sleep 1; kill -TERM "$waiter"; wait "$waiter" 2>/dev/null
check "holder lock survives killed waiter" test "$(cat "$ld/pid" 2>/dev/null)" = "$holder"
kill "$holder"; wait "$holder" 2>/dev/null
check "stale lock then reclaimed"          test "$($C run tests 'echo after' | head -1)" = after
# output is cut at an end marker, not by dropping the last line (two-line prompt, no trailing newline)
# (set through send: run wraps its command in a subshell, where a PS1 assignment would not stick)
$C send tests "PS1=\$'top\\nbot> '; PROMPT=\$PS1" >/dev/null; sleep 1
check "two-line prompt: only the output" test "$($C run tests 'echo x')" = $'x\n[exit 0]'
check "no trailing newline kept"         test "$($C run tests 'printf y')" = $'y\n[exit 0]'
}
sec 4 1 sec4
sec 5 1 sec5
wait
for n in 1 2 3 4 5; do cat $SEC/out-$n; (( TT_FAILS += $(grep -c '^FAIL' $SEC/out-$n) )); done
# the latency bound runs here, after every section has finished, on section 1's server: with the sections' polls
# running beside it a send took 1.3-2.8 s instead of 0.6 s
# send of an instant command must not hold the lock for seconds
s0=$EPOCHREALTIME
$C send shell 'echo x' >/dev/null
check "send returns fast"                  test $(( (EPOCHREALTIME - s0) < 2 )) = 1
check "parallel runs stay clean" test $(( $(<$SEC/bad-3) + $(<$SEC/bad-5) )) -eq 0
check "no stuck records"         test "$(cat $SEC/rec-*.jsonl | jq -sr '[group_by(.id)[]|select(last.exit==null)]|length')" = 0
tt_done
