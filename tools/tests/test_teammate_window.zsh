source "${0:A:h}/lib.zsh"
H="${TC_TEAMMATE_HOOK:-${0:A:h:h:h}/bin/tmux-teammate-window}"
tt_setup claude shell
tt set-hook -g after-split-window "run-shell -b '$H'"
lead="$(tt display -p -t '=tt:claude' '#{window_index}')"
win_of() { tt list-windows -t '=tt' -F '#{window_index} #{window_name}' | awk -v n="✦ $1" '$0 ~ n {print $1}' }
# direct shape: the start command itself carries --agent-name. Copied from the real pane_start_command
# of a teammate under Claude Code 2.1.301 (2026-10-16): cd <dir> && env CLAUDECODE=1 … <binary> --agent-id …
# --agent-name <name> --team-name …; the binary is swapped for a harmless sleeper that keeps the args.
tt split-window -d -t '=tt:claude' "cd /tmp && env CLAUDECODE=1 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 sh -c 'sleep 60; :' --agent-id probe-a@tt --agent-name probe-a --team-name tt --agent-color green --parent-session-id 00000000-0000-0000-0000-000000000000 --agent-type general-purpose --permission-mode auto --model sonnet"
tt_wait 12 test -n "$(win_of probe-a)"
check "direct shape gets a window"   test -n "$(win_of probe-a)"
check "placed after the lead"        test "$(win_of probe-a)" = $(( lead + 1 ))
check "flagged teammate"             test "$(tt show-options -wqv -t "=tt:✦ probe-a" @tc_teammate)" = 1
# cat shape: started as cat, then respawned into the teammate command (older Claude)
p="$(tt split-window -d -P -F '#{pane_id}' -t '=tt:claude' cat)"
tt respawn-pane -k -t "$p" "exec sh -c 'sleep 60; :' teammate --agent-name probe-b"
tt_wait 12 test -n "$(win_of probe-b)"
check "cat shape gets a window"      test -n "$(win_of probe-b)"
check "second teammate after first"  test "$(win_of probe-b)" = $(( lead + 2 ))
# a plain split must stay where it is
before="$(tt list-panes -t '=tt:claude' | wc -l | tr -d ' ')"
tt split-window -d -t '=tt:claude'
sleep 2
check "plain split stays"            test "$(tt list-panes -t '=tt:claude' | wc -l | tr -d ' ')" = $(( before + 1 ))
tt_done
