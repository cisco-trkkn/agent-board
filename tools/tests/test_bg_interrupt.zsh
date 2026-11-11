source "${0:A:h}/bg_common.zsh"
# test_bg_interrupt.zsh — an interrupted tmux-ctl run still ends its record at exit 143 (TERM mid-run and right after the start record).
touch "$r"   # a fresh state dir: the polls below read $r before the first run creates it
# interrupted run: record must not stay at exit:null
# waits are on conditions with a 30 s cap (one loaded iteration of this file takes ~60-100 s in all, so
# no single step needs more); a timeout fails the step under its own name
cap=30
# the run happens in the hidden session tt-bg (tt_all_idle only looks at tt): idle = a shell in tt-bg:tests
bg_idle() { tt list-panes -t '=tt-bg:tests' -F '#{pane_current_command}' | grep -qxE -e '-?(zsh|bash|sh)' }
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
tt_done
