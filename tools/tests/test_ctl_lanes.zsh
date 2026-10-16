source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup
(cd "$TT_DIR" && $C run tests true >/dev/null)
tt send-keys -t '=tt-bg:tests' 'sleep 30' Enter
tt_wait 3 test "$(tt display -p -t '=tt-bg:tests' '#{pane_current_command}')" = sleep
out="$($C run tests 'echo lane' 2>"$TT_DIR/err")"
check "lane output"     test "$(print -r -- "$out" | head -1)" = lane
check "lane notice"     grep -q 'using lane tests·claude' "$TT_DIR/err"
check "lane tagged"     test "$(tt show-options -wqv -t '=tt-bg:tests·claude' @tc_lane)" = 1
n1="$(tt list-windows -t '=tt-bg' | wc -l)"; $C run tests 'true' 2>/dev/null
check "lane reused"     test "$(tt list-windows -t '=tt-bg' | wc -l)" = "$n1"
tt send-keys -t '=tt-bg:tests·claude' 'sleep 30' Enter
tt_wait 3 test "$(tt display -p -t '=tt-bg:tests·claude' '#{pane_current_command}')" = sleep
$C run tests true 2>/dev/null; check "both busy -> exit 2" test $? -eq 2
tt send-keys -t '=tt-bg:tests·claude' C-c
tt_wait 3 test "$(tt display -p -t '=tt-bg:tests·claude' '#{pane_current_command}')" = zsh
zmodload zsh/datetime; tt set-option -w -t '=tt-bg:tests·claude' @tc_lane_used $(( EPOCHSECONDS - 1000 ))
$C list >/dev/null
check "stale lane reaped" sh -c "! $TT_BIN list-windows -t '=tt-bg' -F '#{window_name}' | grep -qx 'tests·claude'"
tt new-window -d -t '=tt-bg:' -n 'tests·keep' -c "$TT_DIR"
tt set-option -w -t '=tt-bg:tests·keep' @tc_lane 1
tt set-option -w -t '=tt-bg:tests·keep' @tc_lane_used $(( EPOCHSECONDS - 10 ))
tt_wait 3 test "$(tt display -p -t '=tt-bg:tests·keep' '#{pane_current_command}')" = zsh
$C list >/dev/null
check "recent lane kept" sh -c "$TT_BIN list-windows -t '=tt-bg' -F '#{window_name}' | grep -qx 'tests·keep'"
tt send-keys -t '=tt-bg:tests' C-c
mkdir -p "$TT_DIR/b"
check "-C dir"          test "$($C run -C "$TT_DIR/b" tests pwd | head -1)" = "$TT_DIR/b"
check "-t and -C order" test "$($C run -C "$TT_DIR/b" -t 5 tests pwd | head -1)" = "$TT_DIR/b"
check "-t then -C"      test "$($C run -t 5 -C "$TT_DIR/b" tests pwd | head -1)" = "$TT_DIR/b"
check "pane cwd kept"   test "$(tt display -p -t '=tt-bg:tests' '#{pane_current_path}')" = "$TT_DIR"
git -C "$TT_DIR/b" init -q
check "default -C = caller git root" test "$(cd "$TT_DIR/b" && $C run tests pwd | head -1)" = "$TT_DIR/b"
# long run in a lane whose stamp is backdated mid-run must survive its own _done
tt send-keys -t '=tt-bg:tests' 'sleep 30' Enter
tt_wait 3 test "$(tt display -p -t '=tt-bg:tests' '#{pane_current_command}')" = sleep
( sleep 1.5; tt set-option -w -t '=tt-bg:tests·claude' @tc_lane_used $(( EPOCHSECONDS - 2000 )) ) &
out="$($C run tests 'sleep 3; echo survived' 2>/dev/null)"; rc=$?
check "reap spares finishing run" test "$(print -r -- "$out" | tr '\n' ' ')" = "survived [exit 0] " -a $rc -eq 0
check "lane kept after run"       sh -c "$TT_BIN list-windows -t '=tt-bg' -F '#{window_name}' | grep -qx 'tests·claude'"
wait
tt send-keys -t '=tt-bg:tests' C-c
tt_wait 3 test "$(tt display -p -t '=tt-bg:tests' '#{pane_current_command}')" = zsh
# narrow pane + deep -C dir: output must be exactly command output + exit line
deep="$TT_DIR/$(printf 'deepdirectory%.0s/' 1 2 3 4 5 6)x"; mkdir -p "$deep"
tt resize-window -t '=tt-bg:tests' -x 60
out="$($C run -C "$deep" tests 'echo one; false' 2>&1)"
check "wrapped command, clean output" test "$out" = "one
[exit 1]"
check "cd failure -> exit 2, cmd not run" sh -c "$C run -C $TT_DIR/nonexistent tests 'echo SHOULDNOTRUN' | grep -qv SHOULDNOTRUN"
$C feed nolog >/dev/null; check "feed missing log -> exit 0" test $? -eq 0
tt_done
