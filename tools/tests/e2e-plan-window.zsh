#!/usr/bin/env zsh
# e2e-plan-window.zsh — aged, multi-owner fixture for the `plan` window on a scratch tmux server (lib.zsh).
# Not a test_*.zsh: run-all does not pick it up. Run it in a terminal:  zsh tools/tests/e2e-plan-window.zsh
R="${${(%):-%x}:A:h:h:h}"
source "$R/tools/tests/lib.zsh"
print -r -- "--- sockets before (ls /private/tmp/tmux-$UID | wc -l):"; ls "/private/tmp/tmux-$UID" | wc -l
tt_setup
print -r -- "scratch socket: $TT_SOCK_NAME"
H="$TT_DIR/home"; mkdir -p "$H/.claude/sessions" "$H/.claude/tasks/session-aaaaaaaa" "$TT_DIR/bin" "$TT_DIR/proj"
# stand-in for a Claude process: pane_current_command must be `claude` (paneclass.classify); a copied /bin/sleep is killed by SIP
cat > "$TT_DIR/claude.c" <<'EOC'
#include <unistd.h>
int main(void) { sleep(900); return 0; }
EOC
cc -o "$TT_DIR/bin/claude" "$TT_DIR/claude.c" || { print -r -- "cc failed"; exit 1 }
tt set-environment -g HOME "$H"            # planview (in the plan window) reads $HOME/.claude
out="$(DEV_NO_ATTACH=1 DEV_CLAUDE_CMD='sleep 900' "$R/bin/dev" "$TT_DIR/proj")"; print -r -- "dev: $out"
sess=proj
pane="$(tt display -p -t "=${sess}:claude" '#{window_id}.#{pane_id}')"; print -r -- "lead pane: $pane"
now=$(( $(date +%s) * 1000 ))
print -r -- "{\"pid\":1,\"sessionId\":\"aaaaaaaa-0000-0000-0000-000000000000\",\"tmux\":\"${sess}:$pane\",\"updatedAt\":$now}" > "$H/.claude/sessions/1.json"
print -r -- "{\"pid\":2,\"sessionId\":\"bbbbbbbb-0000-0000-0000-000000000000\",\"tmux\":\"other:@1.%9\",\"updatedAt\":$((now+5000))}" > "$H/.claude/sessions/2.json"
printf '{"ts":1,"path":"%s/docs/superpowers/plans/2026-01-01-aged.md","kind":"plan","session_id":"aaaaaaaa-0000-0000-0000-000000000000"}\n' "$TT_DIR" > "$TC_STATE/artifacts-${sess}.jsonl"
T="$H/.claude/tasks/session-aaaaaaaa"
yesterday() { touch -t "$(date -v-1d +%Y%m%d%H%M)" "$@" }
mk() { print -r -- "{\"id\":\"$1\",\"subject\":\"$2\",\"status\":\"$3\",\"owner\":\"$4\",\"blockedBy\":[$5]}" > "$T/$1.json" }
mk 1 "Parse the input files" completed alpha ""
mk 2 "Build the index" in_progress rdy ""
mk 3 "Write the long-named report section that needs a permission" in_progress wait ""
mk 4 "Ship it" pending "" ""
mk 5 "Announce" pending "" '"3"'
mk 6 "Clean up the temp data" in_progress ghost ""
yesterday "$T"/*.json
tt new-window -d -t "=${sess}:" -n "✦ rdy" "sleep 900"
tt new-window -d -t "=${sess}:" -n "✦ wait" "sh -c 'echo \"Do you want to proceed?\"; echo \"❯ 1. Yes\"; exec $TT_DIR/bin/claude'"
print -r -- "--- files (mtime):"; ls -l "$T" | tail -n +2 | awk '{print $6,$7,$8,$9}'
print -r -- "--- windows:"; tt list-windows -t "=${sess}" -F '#{window_index} #{window_name} [#{pane_current_command}]'
sleep 4
print -r -- "--- capture-pane plan (first):"; tt capture-pane -p -t "=${sess}:plan" | sed '/^$/d'
print -r -- "--- capture-pane -e of the waiting row (raw escapes shown with cat -v):"
tt capture-pane -p -e -t "=${sess}:plan" | grep 'wait (waiting)\|(waiting)' | cat -v
mk 2 "Build the index" completed rdy ""; yesterday "$T/2.json"
for i in 1 2 3 4 5 6 7 8 9 10; do sleep 0.5; tt capture-pane -p -t "=${sess}:plan" | grep -q '2/6 done' && { print -r -- "updated within 5 s (poll $i of 0.5 s)"; break }; done
print -r -- "--- capture-pane plan (after marking task 2 completed):"; tt capture-pane -p -t "=${sess}:plan" | sed '/^$/d'
print -r -- "--- plan pane alive:"; tt display -p -t "=${sess}:plan" 'pane_dead=#{pane_dead} cmd=#{pane_current_command} pid=#{pane_pid}'
sleep 6
mk 3 "Write the long-named report section that needs a permission" completed wait ""; yesterday "$T/3.json"
sleep 3
print -r -- "--- capture-pane plan (6+ s later, task 3 completed too, which unblocks 5):"; tt capture-pane -p -t "=${sess}:plan" | sed '/^$/d'
tt display -p -t "=${sess}:plan" 'pane_dead=#{pane_dead} cmd=#{pane_current_command} pid=#{pane_pid}'
SOCK="$TT_SOCK_NAME"
tt_teardown
print -r -- "--- sockets after (ls /private/tmp/tmux-$UID | wc -l), and my socket $SOCK:"; ls "/private/tmp/tmux-$UID" | wc -l
ls "/private/tmp/tmux-$UID" | grep -cx -- "$SOCK" | sed 's/^/entries named like my socket: /'
ps -ax -o command | grep -c "[t]mux -L $SOCK" | sed 's/^/servers on my socket: /'
