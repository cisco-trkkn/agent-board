source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude shell
$C run tests true >/dev/null                       # creates the bg session tt-bg with its tests window
check "idle shell is idle"        sh -c "$C list | grep -q '  tests  \[idle\]'"
# a zsh script in the pane: #{pane_current_command} stays "zsh", but the pane's shell has a child
tt send-keys -t '=tt-bg:tests' "zsh -c 'sleep 90; :'" Enter
tt_wait 20 sh -c "pgrep -P \$($TT_BIN display -p -t '=tt-bg:tests' '#{pane_pid}') >/dev/null"
check "script shows as zsh"       test "$(tt display -p -t '=tt-bg:tests' '#{pane_current_command}')" = zsh   # precondition: the bug's shape
check "script pane is busy"       sh -c "$C list | grep -q '  tests  \[busy'"
out="$($C run -t 60 tests 'echo lane-ok' 2>&1)"
check "run goes to a lane"        zsh -c "print -r -- ${(q)out} | grep -q 'using lane tests·claude'"
check "lane ran the command"      zsh -c "print -r -- ${(q)out} | grep -qx lane-ok"
tt send-keys -t '=tt-bg:tests' C-c   # the script sleeps 90 s so it is still running however slow the machine is; end it now
tt_wait 20 sh -c "$C list | grep -q '  tests  \[idle\]'"
check "idle again after the script" sh -c "$C list | grep -q '  tests  \[idle\]'"
tt_done
