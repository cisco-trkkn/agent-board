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

**Bug found by this run.** The first real-state run printed `active: false`, ids 0-4, all pending/blocked: the lead was not found. `_snapshot` passed `Path.home()` as `home`, but sessions and task lists live under `~/.claude` (the unit fixtures used a flat `home/sessions`, which hid it). Fixed test-first in 1364a79 (`test_snapshot_reads_sessions_and_tasks_under_dot_claude` failed, then passed); the output above is after the fix. Task 2's earlier "manual check" had shown the fallback for the same reason.

## Aged fixture

Script: scratchpad `aged.zsh` (run through `tmux-ctl run … tests`, so it has a tty). Setup: scratch server from `lib.zsh`; `HOME` of the server set to a scratch dir with `.claude/sessions/{1,2}.json` (the lead entry points at the `claude` pane of the session `proj`, a decoy points at `other:@1.%9` with a newer `updatedAt`), a task dir `session-aaaaaaaa` with 6 task files `touch -t`'d to yesterday, an `artifacts-proj.jsonl` plan line for this lead, and the session made by the real `bin/dev` (DEV_NO_ATTACH=1), so the `plan` window is the one `bin/dev` creates. Windows: `✦ rdy` runs `sleep` (→ ready); `✦ wait` prints `Do you want to proceed?` then execs a binary named `claude` (a tiny C program that sleeps, so `pane_current_command` is `claude`) (→ waiting); owner `ghost` has no window (→ gone).

Output (second run, which adds the aliveness check and a capture 6+ s later):

```
dev: session 'proj' ready
lead pane: @3.%3
--- files (mtime):
Oct 27 16:54 1.json
Oct 27 16:54 2.json
Oct 27 16:54 3.json
Oct 27 16:54 4.json
Oct 27 16:54 5.json
Oct 27 16:54 6.json
--- windows:
0 claude [sleep]
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
updated within 5 s (poll 4)
--- capture-pane plan (after marking task 2 completed):
2026-01-01-aged · 2/6 done
✓ Parse the input files
✓ Build the index
▶ Write the long-named report section that needs a permission → wait (waiting)
· Ship it
✗ Announce
▶ Clean up the temp data → ghost (gone)
--- plan pane still alive:
pane_dead=0 cmd=Python pid=73263
--- capture-pane plan (>= 6 s later, task 3 completed too; unblocks 5):
2026-01-01-aged · 3/6 done
✓ Parse the input files
✓ Build the index
✓ Write the long-named report section that needs a permission
· Ship it
· Announce
▶ Clean up the temp data → ghost (gone)
pane_dead=0 cmd=Python pid=73263
--- sessions in scratch server:
proj
proj-bg
tt
SOCKET=tctest-73155-21656
```

Result: header, all four glyphs (✓ ▶ · ✗) and the three states (ready, waiting, gone) show; after task 2 was rewritten as completed the capture showed `2/6 done` within the 5 s window (found on poll 4 of 0.5 s, i.e. ≤ 2 s). ✔
Not covered: the red colour of `waiting` (capture-pane drops escapes; colour is unit-tested) and the permission prompt text being matched on a real Claude pane (the stand-in prints the prompt text only).
The `plan` pane (`bin/tmux-plan`, a Python loop) was still alive at two captures more than 6 s apart: `pane_dead=0`, same pid 73263, and its content moved from `2/6 done` to `3/6 done` (task 3 completed, task 5 unblocked: `✗ Announce` became `· Announce`). ✔

Leak check. The scratch server's socket was `tctest-73155-21656`: it is in neither the before listing (taken before `tt_setup`) nor the after listing of `/private/tmp/tmux-503`, and `ps` shows 0 `tmux -L tctest` servers. Two stale socket files of mine from earlier in the plan (`pw-52449` from the Task 2 manual check, `tctest-96052-25836` from the run-all I killed in Task 3) were in the before listing; both servers were already dead (`no server running`), and I removed the two files afterwards. The only other difference between the before and after listings: `poll-72684-92bcf193`, created meanwhile by another session. The remaining `tctest-*` sockets (11394, 15759, 16370, 64637, 68768) and 8 old `tctest.*` dirs in $TMPDIR (Oct 15-26) are older leftovers, not mine.

Sockets before (`ls /private/tmp/tmux-503`):

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
pw-52449
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
tctest-96052-25836
ub
```

Sockets after: the same list plus `poll-72684-92bcf193` (before my two removals).

Choice for `waiting`: `paneclass.classify` treats a pane as claude when `pane_current_command` matches a version number or contains `claude`. The `✦ wait` window runs `sh -c 'echo "Do you want to proceed?"; echo "❯ 1. Yes"; exec <scratch>/bin/claude'`, where `claude` is a small C program (`cc`, `sleep(900)`): a copied `/bin/sleep` is killed (SIP) and a symlink shows as `sleep`.

## Load

Load averages (1/5/15 min) when the report was written: 6.52 37.44 98.58
(The machine was heavily loaded earlier in the session: 33.02 66.84 122.57 at the start of Task 5.) All timings above are on this loaded host.
