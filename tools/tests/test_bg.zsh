source "${0:A:h}/bg_common.zsh"
# test_bg.zsh — tmux-ctl run/send in the bg session: records, summaries, list/read/send. Siblings: test_bg_interrupt, test_bg_parallel, test_bg_lock.
check "run goes to bg"       test "$($C run tests 'echo hi' | head -1)" = hi
check "bg session exists"    tt has-session -t '=tt-bg'
check "bg flagged"           test "$(tt show-options -qv -t '=tt-bg:' @tc_bg)" = 1
check "bg windows"           test "$(tt list-windows -t '=tt-bg' -F '#{window_name}' | sort | tr '\n' ' ')" = "shell tests "
check "user shell untouched" sh -c "! $TT_BIN capture-pane -p -t '=tt:shell' | grep -q 'echo hi'"
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
no_stuck
tt_done
