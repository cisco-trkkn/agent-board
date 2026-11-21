#!/usr/bin/env zsh
# e2e-tasks-window.zsh — the tasks window, end to end on a scratch tmux server (lib.zsh, `-L tctest-… -f /dev/null`).
# A fake home holds read-only copies of two real ~/.claude/tasks dirs: the newest with 5-13 tasks and no `Plan & run:`
# item (more than ~10 independent tasks fall back to the list layout at 50 rows, which draws no cards), and the newest
# with 3-60 tasks and at least one `Plan & run:` item. sessions/x.json points the scratch `claude` pane at the first;
# `taskwin.py watch --root <this checkout>` runs in a second window and reads this checkout's real ledgers and queue
# reports read-only. Keys go in with send-keys; the window is killed and restarted to show the view and filter are
# kept, then the lead changes to the queue list.
# Not a test_*.zsh: run-all does not pick it up. Run it from the worktree: zsh tools/tests/e2e-tasks-window.zsh
R="${${(%):-%x}:A:h:h:h}"
source "$R/tools/tests/lib.zsh"
tt_setup claude
src=""; qsrc=""
for d in ${(f)"$(ls -dt ~/.claude/tasks/session-*(/N))"}; do
  files=($d/*.json(N)); n=${#files}
  (( n > 0 )) || continue                 # grep with no file names would read stdin
  hasq=$(grep -l '"subject": "Plan & run: ' $files </dev/null | wc -l | tr -d ' ')
  if [[ -z "$src" ]] && (( n >= 5 && n <= 13 && hasq == 0 )); then src="$d"; fi
  if [[ -z "$qsrc" ]] && (( n >= 3 && n <= 60 && hasq >= 1 )); then qsrc="$d"; fi
  if [[ -n "$src" && -n "$qsrc" ]]; then break; fi
done
[[ -n "$src" && -n "$qsrc" ]] || { print "no real task dirs (plan: 5-13 tasks, no queue; queue: 3-60 tasks)"; exit 1 }
print -r -- "copied real task dirs: plan $src, queue $qsrc"
sid="11111111-0000-0000-0000-000000000000"; sid2="22222222-0000-0000-0000-000000000000"
home="$TT_DIR/home"; mkdir -p "$home/sessions" "$home/tasks"
cp -R "$src" "$home/tasks/session-${sid[1,8]}"
cp -R "$qsrc" "$home/tasks/session-${sid2[1,8]}"
pane="$(tt display -p -t '=tt:claude' '#{window_id}.#{pane_id}')"
lead() { print -r -- "{\"pid\":1,\"sessionId\":\"$1\",\"cwd\":\"$TT_DIR\",\"startedAt\":1,\"tmux\":\"tt:$pane\"}" > "$home/sessions/x.json" }
lead "$sid"
start() {
  tt new-window -d -t '=tt:' -n tasks -c "$TT_DIR" "python3 -I $TT_REPO/board/taskwin.py watch --session tt --root $TT_REPO --home $home"
  tt resize-window -t '=tt:tasks' -x 120 -y 50
  sleep 3
}
key() { tt send-keys -t '=tt:tasks' "$@"; sleep 1.5 }
cap() { tt capture-pane -p -t '=tt:tasks' }
has() { [[ "$1" == *"$2"* ]] }
start
c="$(tt capture-pane -e -p -t '=tt:tasks')"
print -r -- "$c"
check "default view is plan: [2 plan] tab" has "$c" "[2 plan]"
check "card border ╭ drawn" has "$c" "╭"
check "status glyph ● or ○ drawn" zsh -c '[[ $1 == *●* || $1 == *○* ]]' _ "$c"
check "state file written under scratch TC_STATE" test -s "$TC_STATE/taskwin/tt.json"
key 3; c="$(cap)"; print -r -- "$c"
newest="$(ls "$TT_REPO/docs/superpowers/ledgers" | sort | tail -1)"
stem="$(sed -n '1s/^# SDD ledger — plan: //p' "$TT_REPO/docs/superpowers/ledgers/$newest/progress.md")"; stem="${${stem:t}%.md}"
check "3 shows the history tab" has "$c" "[3 history]"
check "history lists the newest real ledger's plan ($stem)" has "$c" "$stem"
key Enter; c="$(cap)"
check "Enter expands the first history row to its ledger folder" has "$c" "docs/superpowers/ledgers/"
key Tab; c="$(cap)"
check "Tab wraps to the queue tab" has "$c" "[1 queue]"
check "queue view says no queue for a plan-only list" has "$c" "no queue"
key 2; key f; c="$(cap)"
check "f in the plan view shows the filter" has "$c" "filter: hide done"
key '?'; c="$(cap)"
check "? shows the key help" has "$c" "Tab/1 2 3 view"
key '?'
tt kill-window -t '=tt:tasks'
start; c="$(cap)"; print -r -- "$c"
check "restart keeps the plan view" has "$c" "[2 plan]"
check "restart keeps the filter" has "$c" "filter: hide done"
lead "$sid2"; sleep 3; c="$(cap)"
check "lead change keeps the view" has "$c" "[2 plan]"
key 1; c="$(cap)"; print -r -- "$c"
check "1 shows the queue tab" has "$c" "[1 queue]"
check "real queue list has rows (no 'no queue')" zsh -c '[[ $1 != *"no queue"* ]]' _ "$c"
check "ui saved with view queue" python3 -c 'import json,sys; sys.exit(json.load(open(sys.argv[1]))["ui"]["view"] != "queue")' "$TC_STATE/taskwin/tt.json"
tt_done
