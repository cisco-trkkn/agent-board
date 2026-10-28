source "${0:A:h}/lib.zsh"
L="${TC_LAYOUT:-$TT_REPO/bin/tmux-dev-layout}"
D="${TC_DEV:-$TT_REPO/bin/dev}"
tt_setup                                     # old layout: claude shell tests
wins() { tt list-windows -t "=$1" -F '#{window_name}' | sort | tr '\n' ' ' }
fp="$(tt split-window -d -v -t '=tt:tests' -P -F '#{pane_id}' 'sleep 600')"; tt set-option -p -t "$fp" @tc_role feed
sp="$(tt split-window -d -v -t '=tt:shell' -P -F '#{pane_id}' 'sleep 600')"; tt set-option -p -t "$sp" @tc_role feed
tt set-option -w -t '=tt:shell' @tc_label x
"$L" tt "$TT_DIR"
check "user windows"     test "$(wins tt)" = "claude plan "   # the idle user shell is removed; plan is added
check "bg windows"       test "$(wins tt-bg)" = "shell tests "
check "plan window runs tmux-plan" sh -c "$TT_BIN display -p -t '=tt:plan' '#{pane_start_command}' | grep -q tmux-plan"
check "bg flagged"       test "$(tt show-options -qv -t '=tt-bg:' @tc_bg)" = 1
check "no role panes"    test -z "$(tt list-panes -s -t '=tt' -F '#{@tc_role}' | tr -d '\n')"
check "moved tests bare" test "$(tt list-panes -t '=tt-bg:tests' | wc -l | tr -d ' ')" = 1
"$L" tt "$TT_DIR"
check "idempotent"       test "$(wins tt)|$(wins tt-bg)" = "claude plan |shell tests "
mkdir -p "$TT_DIR/.dev"; printf '# c\ntests: while :; do echo W; sleep 1; done\n' > "$TT_DIR/.dev/windows"
"$L" tt "$TT_DIR"
wp="$(tt list-panes -t '=tt-bg:tests' -F '#{pane_id} #{@tc_role}' | awk '$2=="watch"{print $1}')"
check "watch in bg"      test -n "$wp"
check "watch runs"       tt_wait 3 sh -c "$TT_BIN capture-pane -p -t $wp | grep -qx W"
"$L" tt "$TT_DIR"
check "one watch"        test "$(tt list-panes -t '=tt-bg:tests' -F '#{@tc_role}' | grep -c watch)" = 1
# busy tests window in an unmigrated session stays put
tt new-session -d -s old -n claude -c "$TT_DIR"; tt new-window -d -t '=old:' -n tests -c "$TT_DIR" 'sleep 600'
err="$("$L" old "$TT_DIR" 2>&1 >/dev/null)"
check "busy tests kept"  sh -c "$TT_BIN list-windows -t '=old' -F '#{window_name}' | grep -qx tests"
check "busy note"        zsh -c 'print -r -- "$1" | grep -q busy' x "$err"
# busy user shell in an existing session stays put, with a note; the idle one goes
tt new-session -d -s busy -n claude -c "$TT_DIR"; tt new-window -d -t '=busy:' -n shell -c "$TT_DIR" 'sleep 30'
err="$("$L" busy "$TT_DIR" 2>&1 >/dev/null)"
check "busy shell kept"  sh -c "$TT_BIN list-windows -t '=busy' -F '#{window_name}' | grep -qx shell"
check "busy shell note"  zsh -c 'print -r -- "$1" | grep -q "busy"' x "$err"
check "busy gains plan"  test "$(wins busy)" = "claude plan shell "
check "busy bg intact"   test "$(wins busy-bg)" = "shell tests "
# the popup shell binding
check "S popup bound"    zsh -c 'grep -qE "^bind S display-popup .*-d \"#\{session_path\}\"" "$1"' x "$TT_REPO/config/tmux.conf"
mkdir -p "$TT_DIR/proj"
out="$(DEV_NO_ATTACH=1 DEV_CLAUDE_CMD=true TC_LAYOUT="$L" "$D" "$TT_DIR/proj")"
check "dev ready"        zsh -c 'print -r -- "$1" | grep -q ready' x "$out"
check "dev windows"      test "$(wins proj)" = "claude plan "
check "dev bg"           test "$(wins proj-bg)" = "shell tests "
# race: layout migration and tmux-ctl's ensure_bg on a fresh session must not duplicate windows
CT="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt new-session -d -s race -n claude -c "$TT_DIR"; tt new-window -d -t '=race:' -n tests -c "$TT_DIR"
tt_wait 3 test "$(tt display -p -t '=race:tests' '#{pane_current_command}')" = zsh
"$L" race "$TT_DIR" & TC_SESSION=race "$CT" run tests true >/dev/null & wait
check "race: one tests"  test "$(tt list-windows -t '=race-bg' -F '#{window_name}' | grep -cx tests)" = 1
check "race: one shell"  test "$(tt list-windows -t '=race-bg' -F '#{window_name}' | grep -cx shell)" = 1
tt_done
