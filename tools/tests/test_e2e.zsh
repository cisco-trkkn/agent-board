source "${0:A:h}/lib.zsh"
F="${0:A:h}/fixtures"; C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup
"${TC_LAYOUT:-$HOME/.local/bin/tmux-dev-layout}" tt "$TT_DIR"
"${TC_MIRROR:-$HOME/.claude/hooks/bash-mirror.sh}" < "$F/ok.json"
(cd "$TT_DIR" && $C run tests true >/dev/null)      # creates the hidden tt-bg session
mp="$(tt list-panes -t '=tt-bg:tests' -F '#{pane_id} #{@tc_role}' | awk '$2==""{print $1}')"
check "hook entry in feed log"  grep -qxF '$ pytest -q tests/unit' "$TC_STATE/feed-tt-tests.log"
tt send-keys -t "$mp" 'sleep 30' Enter
tt_wait 3 test "$(tt display -p -t "$mp" '#{pane_current_command}')" = sleep
out="$($C run tests 'echo e2e' 2>/dev/null)"
check "lane run output"         test "$(print -r -- "$out" | head -1)" = e2e
check "lane window created"     sh -c "$TT_BIN list-windows -t '=tt-bg' -F '#{window_name}' | grep -qx 'tests·claude'"
check "busy main pane untouched" test "$(tt display -p -t "$mp" '#{pane_current_command}')" = sleep
check "feed cmd has entry"      sh -c "$C feed tests 50 | grep -qF 'pytest -q tests/unit'"
tt_done
