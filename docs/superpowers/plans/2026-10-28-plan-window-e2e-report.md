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

Output:

```
dev: session 'proj' ready
lead pane: @3.%3
--- files (mtime):
Oct 27 16:53 1.json
Oct 27 16:53 2.json
Oct 27 16:53 3.json
Oct 27 16:53 4.json
Oct 27 16:53 5.json
Oct 27 16:53 6.json
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
updated within 5 s (poll 4)
--- capture-pane plan (after marking task 2 completed):
2026-01-01-aged · 2/6 done
✓ Parse the input files
✓ Build the index
▶ Write the long-named report section that needs a permission → wait (waiting)
· Ship it
✗ Announce
▶ Clean up the temp data → ghost (gone)
--- leak check inside scratch: sockets
proj
proj-bg
tt
```

Result: header, all four glyphs (✓ ▶ · ✗) and the three states (ready, waiting, gone) show; after task 2 was rewritten as completed the capture showed `2/6 done` within the 5 s window (found on poll 4 of 0.5 s, i.e. ≤ 2 s). ✔
Not covered: the red colour of `waiting` (capture-pane drops escapes; colour is unit-tested) and the permission prompt text being matched on a real Claude pane (the stand-in prints the prompt text only).
Leak check afterwards: no `tmux -L tctest` server is running (`ps`), and none of my scratch dirs remain. `$TMPDIR` holds 8 older `tctest.*` dirs dated Oct 15-26, left by earlier runs and not created here; I left them. (One `ps` count taken right after the run showed 2 servers, probably another session's test run; a later `ps` showed none.)

## Load

Load averages (1/5/15 min) when the report was written: 6.52 37.44 98.58
(The machine was heavily loaded earlier in the session: 33.02 66.84 122.57 at the start of Task 5.) All timings above are on this loaded host.
