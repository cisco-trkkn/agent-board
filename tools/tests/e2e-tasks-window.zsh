#!/usr/bin/env zsh
# e2e-tasks-window.zsh — the tasks window, end to end on a scratch tmux server (lib.zsh, `-L tctest-… -f /dev/null`):
# a fake home whose tasks/session-<id8>/ is a read-only copy of the newest real ~/.claude/tasks dir with 5-13 tasks (more tasks than ~10 independent ones fall back
# to the list layout at 50 rows, which draws no cards),
# a sessions/x.json pointing at the scratch `claude` pane, and `taskwin.py watch` running in a second window.
# Not a test_*.zsh: run-all does not pick it up. Run it from the worktree: zsh tools/tests/e2e-tasks-window.zsh
R="${${(%):-%x}:A:h:h:h}"
source "$R/tools/tests/lib.zsh"
tt_setup claude
src=""
for d in ${(f)"$(ls -dt ~/.claude/tasks/session-*(/N))"}; do
  files=($d/*.json(N)); n=${#files}; (( n >= 5 && n <= 13 )) && { src="$d"; break; }
done
[[ -n "$src" ]] || { print "no real task dir with 5-13 tasks"; exit 1 }
print -r -- "copied real task dir: $src"
sid="${${src:t}#session-}00000000-0000-0000-0000-000000000000"; sid="${sid[1,8]}-0000-0000-0000-000000000000"
home="$TT_DIR/home"; mkdir -p "$home/sessions" "$home/tasks"
cp -R "$src" "$home/tasks/session-${sid[1,8]}"
pane="$(tt display -p -t '=tt:claude' '#{window_id}.#{pane_id}')"
print -r -- "{\"pid\":1,\"sessionId\":\"$sid\",\"cwd\":\"$TT_DIR\",\"startedAt\":1,\"tmux\":\"tt:$pane\"}" > "$home/sessions/x.json"
tt new-window -d -t '=tt:' -n tasks -c "$TT_DIR" "python3 -I $TT_REPO/board/taskwin.py watch --session tt --root $TT_DIR --home $home"
tt resize-window -t '=tt:tasks' -x 120 -y 50
sleep 3
cap="$(tt capture-pane -e -p -t '=tt:tasks')"
print -r -- "$cap"
check "card border ╭ drawn" zsh -c '[[ $1 == *╭* ]]' _ "$cap"
check "status glyph ● or ○ drawn" zsh -c '[[ $1 == *●* || $1 == *○* ]]' _ "$cap"
check "state file written under scratch TC_STATE" test -s "$TC_STATE/taskwin/tt.json"
tt_done
