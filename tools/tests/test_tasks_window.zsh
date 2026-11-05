source "${0:A:h}/lib.zsh"
L="${TC_LAYOUT:-$TT_REPO/bin/tmux-dev-layout}"
H="$TT_REPO/bin/tmux-teammate-window"
tt_setup claude
unset TC_TASKS_WINDOW
idx() { tt list-windows -t "=$1" -F '#{window_index} #{window_name}' | awk -v n="$2" '{i=$1; $1=""; sub(/^ /,""); if ($0==n) print i}' }
"$L" tt "$TT_DIR"
ci="$(idx tt claude)"
check "tasks after claude"        test "$(idx tt tasks)" = $(( ci + 1 ))
check "tasks flagged"             test "$(tt show-options -wqv -t '=tt:tasks' @tc_tasks)" = 1
check "tasks runs taskwin watch"  zsh -c 'print -r -- "$1" | grep -qF "board/taskwin.py watch --session tt"' _ "$(tt display -p -t '=tt:tasks' '#{pane_start_command}')"
check "tasks keeps its name"      test "$(tt show-options -wqv -t '=tt:tasks' automatic-rename)" = off
"$L" tt "$TT_DIR"
check "idempotent"                test "$(tt list-windows -t '=tt' -F '#{window_name}' | grep -cx tasks)" = 1
tt new-session -d -s off -n claude -c "$TT_DIR"
TC_TASKS_WINDOW=0 "$L" off "$TT_DIR"
check "TC_TASKS_WINDOW=0: none"   test -z "$(idx off tasks)"
# teammates land after tasks (same direct shape as test_teammate_window.zsh, copied from Claude Code 2.1.301)
tt set-hook -g after-split-window "run-shell -b '$H --hook #{pane_id}'"
tt split-window -d -t '=tt:claude' "cd /tmp && env CLAUDECODE=1 sh -c 'sleep 60; :' --agent-id probe-a@tt --agent-name probe-a --team-name tt"
tt_wait 12 test -n "$(idx tt '✦ probe-a')"
check "teammate after tasks"      test "$(idx tt '✦ probe-a')" = $(( ci + 2 ))
tt split-window -d -t '=tt:claude' "cd /tmp && env CLAUDECODE=1 sh -c 'sleep 60; :' --agent-id probe-b@tt --agent-name probe-b --team-name tt"
tt_wait 12 test -n "$(idx tt '✦ probe-b')"
check "second teammate after"     test "$(idx tt '✦ probe-b')" = $(( ci + 3 ))
tt_done
