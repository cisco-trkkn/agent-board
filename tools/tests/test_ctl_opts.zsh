source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup
(cd "$TT_DIR" && $C run tests true >/dev/null)            # create the bg session
mark="$(tt capture-pane -p -t '=tt-bg:tests' | grep -c .)"
$C run tests -C "$TT_DIR" 'echo nope' >"$TT_DIR/o" 2>&1; rc=$?
check "run: option after window -> exit 2"   test $rc -eq 2
check "run: says why"                        grep -q 'options go before the window' "$TT_DIR/o"
check "run: nothing typed"                   test "$(tt capture-pane -p -t '=tt-bg:tests' | grep -c .)" = "$mark"
$C run tests -t 5 'echo nope' >/dev/null 2>&1; check "run -t after window -> exit 2" test $? -eq 2
$C send shell -C "$TT_DIR" 'echo nope' >/dev/null 2>&1; check "send: option after window -> exit 2" test $? -eq 2
check "run -C before window still works"     test "$($C run -C "$TT_DIR" tests pwd | head -1)" = "$TT_DIR"
$C run tests false >/dev/null 2>&1; check "failing command -> status 1" test $? -eq 1
tt_done
