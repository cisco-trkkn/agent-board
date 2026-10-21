source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude
$C run tests true >/dev/null
log="$TC_STATE/feed-tt-tests.log"; printf 'a\nb\nc\nd\n' > "$log"
fp="$(tt split-window -d -v -l 35% -t '=tt-bg:tests' -P -F '#{pane_id}' "tail -n 30 -F $log")"
tt set-option -p -t "$fp" @tc_role feed
tt select-pane -t "$fp"                                  # feed pane active: worst case
tt_wait 3 test "$(tt display -p -t "$fp" '#{pane_current_command}')" = tail
check "run uses main pane"      test "$($C run tests 'echo hi' | head -1)" = hi
$C run tests false >/dev/null; check "exit code kept" test $? -eq 1
# match the output line, not the typed command: the bg window is 80 cols, so the echoed
# "printf …; echo hi ; …" line wraps (unjoined) at a cwd/pid-length-dependent column
check "read main"               tt_wait 3 sh -c "$C read tests 5 | grep -qx hi"
check "read feed"               sh -c "$C read tests feed 5 | grep -q '^d$'"
check "feed cmd"                test "$($C feed tests 3 | tr '\n' ' ')" = "b c d "
tt new-window -d -t '=tt-bg:' -n 'tests·x'; tt set-option -w -t '=tt-bg:tests·x' @tc_lane 1
check "list shows lane"         sh -c "$C list | grep -q 'tests·x.*(lane).*(bg)'"
check "list tests idle"         sh -c "$C list | grep -q ' tests  \[idle\]'"
tt_done
