# Queue reliability: real-state check

2026-11-16, commit fa725c8, `zsh tools/tests/check_real_queue_reliability.zsh` run from a pane of the real tmux server (exit 0, last line `REAL CHECK PASS`). Afterwards no `qrel-check-` session and no `qrel.*` temp dir were left.

## wait-gone and Stop guard on the real tmux server

```
server: /private/tmp/tmux-503/agent-board, pid 12354, 21 windows outside the scratch session
guard: {"decision":"block","reason":"teammate(s) qrel-probe still shutting down: run tmux-ctl wait-gone qrel-probe, then continue"}
ok   - guard blocks while the real window exists
wait-gone: wait-gone: killed qrel-probe after 4s (exit 3)
ok   - wait-gone kills the window at the timeout, exit 3
ok   - the longer-named window and the base window are left
ok   - guard allows once the window is gone, pending file deleted
ok   - no real window changed (21 compared)
```

- The guard blocked while the real `✦ qrel-probe` window existed (`guard:` line), `wait-gone` killed it at the 4 s timeout with exit 3, `✦ qrel-probe-2` and the base window were left, and the guard then allowed and deleted the pending file (the five `ok` lines above).
- The list of real windows (session, id, name) was identical before and after: 21 compared (last `ok` line).

## awake sleeps on the real pmset log

```
2026-11-10 00:18:25 – 2026-11-10 00:34:31 Idle Sleep
2026-11-10 20:31:19 – 2026-11-10 21:03:13 Idle Sleep
2026-11-10 22:24:25 – 2026-11-10 22:26:13 Idle Sleep
2026-11-10 22:44:25 – 2026-11-10 22:50:07 Idle Sleep
2026-11-11 08:46:33 – 2026-11-11 09:42:10 Clamshell Sleep
real periods: 5; --all lines: 300
ok   - the real log has Sleep/Wake lines to filter (300)
ok   - default output = the independent count of real periods (5)
ok   - every line is '<start> – <end or …> <reason>'
ok   - no noise reason in the default output
```

- The default output held 5 real periods, equal to an independent awk count of 5; `--all` printed 300 lines (the counts line). Every period line has the `<start> – <end> <reason>` shape and none names a noise reason (the last two `ok` lines).

## Stop guard in a live Claude session

```
log: 2026-11-16T16:44:15Z <session id> allowed after 3 blocks: a self-started handoff has not relayed: run tmux-ctl relay <doc> --old-session <session id> (handoff skill step 5)
ok   - the live session's stop was blocked three times, then allowed and logged once
ok   - the counter was reset
```

- In a live `claude -p --model haiku` session with this checkout's plugin, the stop was blocked three times and then allowed: one `allowed after 3 blocks` log line for that session id, and the counter file was gone (the two `ok` lines).
- `TMUX_PANE`: the live run inherited this shell's environment, and this shell is a pane of the real server, so it had `TMUX_PANE` set. The check therefore shows the guard works when the hook environment carries it, not that a lead started by `dev` has it in its hook environment. Other hooks of this repo already depend on that (`bash-mirror.sh` and `context-inject.sh` exit unless `TMUX_PANE` is set), but this run did not observe a `dev`-started lead.

## Not verified

- That `shutdown-record.sh` runs in a live lead when it sends a real `shutdown_request`. The evidence so far is 48 hook records named `PostToolUse:SendMessage` in this project's transcripts, which show PostToolUse hooks fire for that tool. A transcript record carries the hook's output, not its stdin, so it does not show that the real payload carries `session_id` and `tool_input` with a `to` field. The first live proof is a file under `<state>/shutdown-pending/` after the lead's next shutdown_request.
- A hold that survives a real relay: `awake on --queue` was run only against stubs and a scratch server; `awake on` and `off` were never run against the real hold.
