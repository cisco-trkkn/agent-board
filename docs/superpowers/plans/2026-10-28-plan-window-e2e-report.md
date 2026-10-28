# Plan window: real-state e2e report (2026-10-28)

Run from the worktree `feat/plan-window` while this plan executes, by `impl`. Everything is read-only against real state; the aged fixture runs on a scratch tmux server (`tools/tests/lib.zsh`, `-L tctest-… -f /dev/null`), which tt_teardown killed on exit.

## Real state

Commands (run from the worktree):

```
python3 -I board/planview.py view agent-board --root /Users/francisco.ruiz/agent-board --json
python3 -I board/planview.py view agent-board --root /Users/francisco.ruiz/agent-board
```

JSON output:

```json
{"name": "2026-10-28-plan-window", "active": true, "tasks": [{"id": "6", "subject": "Task 1: planview data model", "status": "completed", "owner": "impl", "state": "working"}, {"id": "7", "subject": "Task 2: render, watch loop and bin/tmux-plan", "status": "completed", "owner": "impl", "state": "working"}, {"id": "8", "subject": "Task 3: plan window in the dev layout", "status": "completed", "owner": "impl", "state": "working"}, {"id": "9", "subject": "Task 4: rules and docs text", "status": "completed", "owner": "impl", "state": "working"}, {"id": "10", "subject": "Task 5: real-state e2e", "status": "in_progress", "owner": "impl", "state": "working"}]}
```

Rendered output (not a tty, so no colour):

```
2026-10-28-plan-window · 4/5 done
✓ Task 1: planview data model
✓ Task 2: render, watch loop and bin/tmux-plan
✓ Task 3: plan window in the dev layout
✓ Task 4: rules and docs text
▶ Task 5: real-state e2e → impl (working)
```

Result: `name` = `2026-10-28-plan-window`, `active` true, 5 tasks, one `in_progress` task (Task 5) owned by `impl` with state `working`. ✔

**Bug found by this run.** The first real-state run printed `active: false`, ids 0-4, all pending/blocked: the lead was not found. `_snapshot` passed `Path.home()` as `home`, but sessions and task lists live under `~/.claude` (the unit fixtures used a flat `home/sessions`, which hid it). Fixed test-first in 1364a79 (`test_snapshot_reads_sessions_and_tasks_under_dot_claude` failed, then passed); the output above is after the fix; a CLI regression test with a `TC_TMUX` shim (`test_cli_default_home_reads_dot_claude_with_a_tmux_shim`) now pins the real default (mutation `.claude` → `.config` fails it and `test_snapshot_reads_sessions_and_tasks_under_dot_claude`). Task 2's earlier "manual check" had shown the fallback for the same reason.

## Aged fixture

Re-runnable from the worktree: `tools/tests/e2e-plan-window.zsh` (a scratch server through `tools/tests/lib.zsh`, so `-L tctest-… -f /dev/null`; it kills the server and removes its dirs on exit; named `e2e-…`, not `test_…`, so run-all does not pick it up). It needs a terminal and `cc`.

Commands (the script builds the C stand-in itself with `cc -o $TT_DIR/bin/claude $TT_DIR/claude.c`):

```
ls /private/tmp/tmux-$UID > before.lst                                                   # before the run
tmux-ctl run -t 300 -C <worktree> tests "zsh tools/tests/e2e-plan-window.zsh > out.txt 2>&1; echo rc=$?"   # rc=0
ls /private/tmp/tmux-$UID > after.lst
diff before.lst after.lst                                                                # empty
```

What it sets up: a scratch server whose `HOME` is a scratch dir with `.claude/sessions/{1,2}.json` (the lead entry points at the `claude` pane of session `proj`; a decoy points at `other:@1.%9` with a newer `updatedAt`), a task dir `session-aaaaaaaa` with 6 task files `touch -t`'d to yesterday, an `artifacts-proj.jsonl` plan line for this lead, and the session made by the real `bin/dev` (DEV_NO_ATTACH=1), so the `plan` window is the one `bin/dev` creates. Owners: `rdy` has a `✦ rdy` window running `sleep` (→ ready); `wait` has a `✦ wait` window that prints `Do you want to proceed?` and then execs a program named `claude` (→ waiting: `paneclass.classify` treats a pane as claude when `pane_current_command` contains `claude`; a copied `/bin/sleep` is killed by SIP and a symlink shows as `sleep`, hence the C program); `ghost` has no window (→ gone).

Full script:

```zsh
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
```

C stand-in source (written by the script to `$TT_DIR/claude.c`):

```c
#include <unistd.h>
int main(void) { sleep(900); return 0; }
```

Output of the run (the last of 3 runs; the earlier two gave the same captures):

```
--- sockets before (ls /private/tmp/tmux-503 | wc -l):
      96
scratch socket: tctest-80856-33
dev: session 'proj' ready
lead pane: @3.%3
--- files (mtime):
Oct 27 16:56 1.json
Oct 27 16:56 2.json
Oct 27 16:56 3.json
Oct 27 16:56 4.json
Oct 27 16:56 5.json
Oct 27 16:56 6.json
--- windows:
0 claude [zsh]
1 plan [Python]
2 ✦ rdy [sleep]
3 ✦ wait [claude]
--- capture-pane plan (first):
2026-01-01-aged · 1/6 done
✓ Parse the input files
▶ Build the index → rdy (ready)
▶ Write the long-named report section that needs a permission → wait (waiting)
· Ship it
✗ Announce
▶ Clean up the temp data → ghost (gone)
--- capture-pane -e of the waiting row (raw escapes shown with cat -v):
�M-^V� Write the long-named report section that needs a permission ^[[1m^[[31m�M-^FM-^R wait (waiting)^[[0m
updated within 5 s (poll 5 of 0.5 s)
--- capture-pane plan (after marking task 2 completed):
2026-01-01-aged · 2/6 done
✓ Parse the input files
✓ Build the index
▶ Write the long-named report section that needs a permission → wait (waiting)
· Ship it
✗ Announce
▶ Clean up the temp data → ghost (gone)
--- plan pane alive:
pane_dead=0 cmd=Python pid=81061
--- capture-pane plan (6+ s later, task 3 completed too, which unblocks 5):
2026-01-01-aged · 3/6 done
✓ Parse the input files
✓ Build the index
✓ Write the long-named report section that needs a permission
· Ship it
· Announce
▶ Clean up the temp data → ghost (gone)
pane_dead=0 cmd=Python pid=81061
--- sockets after (ls /private/tmp/tmux-503 | wc -l), and my socket tctest-80856-33:
      96
entries named like my socket: 0
servers on my socket: 0
```

Reading the output:
- Header, all four glyphs (✓ ▶ · ✗) and the three states (ready, waiting, gone) show. After task 2 was rewritten as completed the capture showed `2/6 done` within the 5 s window (poll 5 of 0.5 s, so under 3 s).
- The `plan` pane (`bin/tmux-plan`, a Python loop) was alive at captures 6+ s apart: `pane_dead=0`, same pid `81061`, content moved from `2/6` to `3/6` (and `✗ Announce` became `· Announce` when its blocker completed).
- Colour: `capture-pane -e` of the waiting row ends with `^[[1m^[[31m… wait (waiting)^[[0m`: tmux re-encodes our `\033[1;31m` as bold (`1m`) then red (`31m`) for the suffix `→ wait (waiting)`; the other rows carry no colour. (`cat -v` mangles the multi-byte `▶` and `→`, shown as replacement characters.)

Leak check. Listing of `/private/tmp/tmux-$UID` before the run (96 entries; my scratch socket does not exist yet, `tt_setup` creates it):

```
abprobe-41505
abprobe2-45731
abprobe3-90212
abprobe4-90260
abspike
belltest
bi14961
bi362
bi5796
bi81970
bi8358
bi83721
bi91668
bi93330
bo14961
bo362
bo5796
bo81970
bo8358
bo83721
bo91668
bo93330
bpass
cfgtest
dbg
default
fix-e2e
frv
gc
hkprobe
ideas-e2e
ifx
nsreal46570
pi4367
pi5364
pi7141
pi73536
pi78219
pi79212
pi85248
pi86108
pi87378
pi89546
pi96223
pi97521
poll-17197
poll-17986
poll-19404
poll-35205
poll-36516
poll-38695
poll-48895
poll-49935
poll-50881
poll-52119
poll-54610
poll-55065
poll-55837
poll-56056
poll-59109
poll-59176
poll-61671
poll-66045
poll-72195
poll-72263
poll-75894
poll-84560
poll-85155
poll-91431
poll-95557
pr4367
pr5364
pr7141
pr73536
pr78219
pr79212
pr85248
pr86108
pr87378
pr89546
pr96223
pr97521
probe-pw
relaydemo
relayfix68730
relayfix70020
rv6
rvw-62157
rvw-62325
tcconf
tctest-11394-18895
tctest-15759-15789
tctest-16370-14960
tctest-64637-18670
tctest-68768-6877
ub
```

After the run: 96 entries again, `diff before.lst after.lst` prints nothing, no entry is named like the scratch socket (`tctest-80856-33`), and `ps` shows 0 servers on it. (Earlier I removed two stale socket files of mine, `pw-52449` and `tctest-96052-25836`, whose servers were already dead; the remaining `tctest-*` and `poll-*` sockets and 8 `tctest.*` dirs in $TMPDIR dated Oct 15-26 are older leftovers of other runs, not mine.)

## Load

Load averages (1/5/15 min) when the report was written: 6.52 37.44 98.58
(The machine was heavily loaded earlier in the session: 33.02 66.84 122.57 at the start of Task 5.) All timings above are on this loaded host.
