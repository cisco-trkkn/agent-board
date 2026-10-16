source "${0:A:h}/lib.zsh"
live_tt() { "$TT_BIN" ls -F '#{session_name}' 2>/dev/null | grep -E '^tt(-|$)' }   # only names the harness could create
live_before="$(live_tt)"
tt_setup
check "session tt exists"        tt has-session -t '=tt'
check "three windows"            test "$(tt list-windows -t '=tt' -F '#{window_name}' | tr '\n' ' ')" = "claude shell tests "
check "TMUX_PANE is claude pane" test "$(tt display -p -t "$TMUX_PANE" '#{window_name}')" = claude
check "pane shell sees TC_STATE" test "$(tt show-environment -g TC_STATE 2>/dev/null)" = "TC_STATE=$TC_STATE"
# teardown: a child shell sets up a server, reports its socket/dir and whether it is up, then exits (EXIT trap)
probe="$(zsh -c 'source "$1"; tt_setup; up=no; "$TT_BIN" -L "$TT_SOCK_NAME" ls >/dev/null 2>&1 && up=yes; print -r -- "$TT_SOCK_NAME $TT_DIR $up"' zsh "${0:A:h}/lib.zsh")"
read -r probe_sock probe_dir probe_up <<< "$probe"
check "probe server up before exit" test "$probe_up" = yes
check "probe server killed on exit" test -z "$("$TT_BIN" -L "$probe_sock" ls 2>/dev/null)"
check "probe temp dir removed"   test ! -e "$probe_dir"
unset TMUX TMUX_PANE
check "live server untouched"    test "$(live_tt)" = "$live_before"
tt_done
