# Discord files: real-state end-to-end (2026-11-17)

Branch `queue/discord-files` (base fc62fc7, Tasks 1–4 = dff0137, 361abef, cbd3557, 5542198). Everything ran against real state through scratch copies: scratch `TC_STATE` and `HOME`, a scratch board on port 7712 with a scratch token, the bridge on `tools/discord-bridge/test/fake-client.js`. The live board on :7700, the real bot token and the real state dirs were never written. Harness scripts live in the agent's scratchpad (`ab.py`, `wr.py`, `bridge-run.js`).

## 1. Failed-run pick on a copy of the real run log

`$TMPDIR/tmux-ctl-503/runs-agent-board.jsonl` (189 lines, 95 distinct run ids) was copied into the scratch `TC_STATE`; `_failed_run_log("agent-board", now)` ran with that `TC_STATE`, so the attachments write went to scratch.

```
failed_run_log = {"log_file": ".../scratchpad/state/discord/agent-board/attachments/16864-11933.log", "log_cmd": "zsh tools/tests/test_ctl_relay.zsh", "log_exit": 1}
written log: .../attachments/16864-11933.log lines = 47 (<=200: True )
records: 95 nonzero-exit: 15 within 24h: 3 in worktrees: 13
  nonzero: 8032-21147 1 1794845963 .../worktrees/queue-reliability True
  nonzero: 9801-12319 1 1794845992 .../worktrees/queue-reliability True
  nonzero: 16864-11933 1 1794846099 .../worktrees/queue-reliability True
```

Pick: id `16864-11933`, cmd `zsh tools/tests/test_ctl_relay.zsh`, exit 1: the newest of the three failing worktree runs in the last 24 h (P2). The written log has 47 lines (≤ 200). That run's log is shorter than 200 lines, so this check does not exercise the tail cut; the Task 2 unit test does.

## 2. Real report through `derive` + `ops_for_events`

Newest `*-queue.md` in the main checkout (read-only): `/Users/francisco.ruiz/agent-board/docs/superpowers/reports/2026-11-05-queue.md` (the only report there). With `state={"primed": True, "seen": []}` and scratch `TC_STATE`:

```
report events: 1
OP: {"op": "post", "text": "queue report: Overnight queue report — 2026-11-05", "tier": "progress", "mention_user": false, "files": ["/Users/francisco.ruiz/agent-board/docs/superpowers/reports/2026-11-05-queue.md"]}
```

`files` is that file's absolute path (the script asserts equality).

## 3. Real Chrome `snap` against a scratch board

Board: `TMUX_DASH_PORT=7712 TMUX_DASH_TOKEN=<scratch> python3 board/server.py` from this worktree, scratch HOME (token file holds the scratch token) and scratch `TC_STATE`; it answered 200 (105 904 bytes) on `/<token>/`.

Run, inside `perl -e 'alarm 60; exec @ARGV'`, with the user's normal Chrome open (19 Chrome processes) and load average 3.54:

```
$ HOME=<scratch> TC_STATE=<scratch> TMUX_DASH_PORT=7712 perl -e 'alarm 60; exec @ARGV' bin/tmux-ctl discord snap agent-board
snap: 1 post, 1 file
rc=0      real 3.594 s (user 1.55 s, sys 1.32 s)
```

**Chrome alongside the user's Chrome:** headless Chrome with the default profile worked: 3.6 s, no hang, rc 0. The `--user-data-dir` retry was therefore not needed and not run. One run only; it does not prove a hang cannot happen.

PNG: `.../state/discord/agent-board/tmp/snap-1794875743-99349.png`, **62 131 bytes** (≥ 20 KB). Read with the Read tool: the board is visible, not blank. The Overview shows the header (Agent Board, tabs Overview / agent-board / interiors / signal-hub-gcp, "live"), the PROJECTS list with agent-board "Working" and its teammates (df-rev, gate-tap, ap-fix, df-e2e), interiors and signal-hub-gcp "Idle", "$0.00 today" per project, and the NOTIFICATIONS block. The right-hand Overseer panel shows a bare **404** because the scratch board has no ttyd behind it; that is a property of the scratch board, not of `snap`.

Op written (no URL, no token):

```
{"op": "post", "text": "board snapshot 19:35", "tier": "progress", "mention_user": false, "files": [".../discord/agent-board/tmp/snap-1794875743-99349.png"], "delete_files": true}
```

Token check after the whole run (bridge included), over the scratch discord dir: `grep -rc <scratch token>` summed to **0**, and `grep -rl` lists 0 files.

Scratch board stopped by PID (98608): `pid 98608 gone`, `lsof -nP -iTCP:7712 -sTCP:LISTEN` printed nothing (rc 1), `curl http://127.0.0.1:7712/` gives `000`. Port 7712 is free.

## 4. Node bridge on the fake client drains the scratch outbox

`createBridge({dir: <scratch discord dir>, client: FakeClient, …})`, three ticks; outbox held the snap op, the report op (written with `outbox_write` from section 2) and the 26 MB `send` op (section 5):

```
before tick: tmp = [ 'snap-1794875743-99349.png 62131B' ]
SEND content="board snapshot 19:35" files=[".../tmp/snap-1794875743-99349.png"]
SEND content="queue report: Overnight queue report — 2026-11-05" files=["/Users/francisco.ruiz/agent-board/docs/superpowers/reports/2026-11-05-queue.md"]
SEND content="26 MB sparse test\nhuge.bin too large (26.0 MB)" files=undefined
outbox json left = []
failed/ = (absent)
tmp/ after = []
bridge log lines:
  post home board snapshot 19:35
  post home queue report: Overnight queue report — 2026-11-05
  post home 26 MB sparse test
```

The report post and the snap post went with their files; the snap PNG was deleted after the send (`tmp/ after = []`); `failed/` does not exist (empty). The real report file was not deleted (no `delete_files` on its op; it still exists).

## 5. `send` of a 26 MB sparse file

`mkfile -n 26m huge.bin` (27 262 976 bytes apparent, 32 blocks on disk), then:

```
$ HOME=<scratch> TC_STATE=<scratch> bin/tmux-ctl discord send .../big/huge.bin -m "26 MB sparse test"
send: 1 post, 1 file        rc=0
```

Through the bridge (section 4) it posted without a file and with the line:

```
huge.bin too large (26.0 MB)
```

## 6. Real `~/.local/state/agent-board/discord/agent-board/` untouched by this run

`find . -type f | sort | xargs md5 -q | md5 -q`, 10 files before and after (2026-11-17T00:35:16Z and 00:36:15Z). Per-file md5, before → after:

```
cc09841986bb793f92e4058fc744164a → same   .env
6f6167fa8c4787aa170136c6505ad29b → same   access.json
e967708a80b76d42e5ddb5cb7ff0126e → same   bridge-state.json
108ca1d9aec07ffaaca1b2ebd90aaf90 → same   bridge.json
843f9afbde97f9a1cf4a72eae7037c13 → same   bridge.log (5128 B)
3d83928195214890a0ce1771cf20920c → same   bridge.pid
24c17a19087f90e57160f323d6d586ff → same   controls-state.json
d41d8cd98f00b204e9800998ecf8427e → same   controls-state.lock
5c625f328285ea731e1223a34aef1097 → 7d7dd668653d1e7e0eaed5474be0de3b   feed-state.json (4563 B → 4564 B)
d41d8cd98f00b204e9800998ecf8427e → same   feed-state.lock
total: 4eef4ecc40aa8bcaf1d42f8b35a9ed6a → 948f20a7f56debf10243ddad0e9ebc4f
```

The only difference is `feed-state.json`, written by the **live** feed, not by this run. Evidence: its mtime is 19:36:10 while no command of this run pointed at it (all used the scratch `TC_STATE`); the file holds the live queue card (`card_text` "… ▶ DF Task 5: Real-state end-to-end …, updated 19:36", `card_ts` 1794875770) which the live feed rewrites on each tick; the card carries a changing "updated HH:MM" and the teammate list. `bridge.log` and the outbox are unchanged, so the live bridge posted nothing meanwhile. I kept md5 and sizes only, not a copy of the earlier content, so I cannot show the exact 1-byte difference.

## Result

All six checks hold. One observation for the lead: headless Chrome with the default profile worked next to the user's open Chrome (3.6 s); a code fix for `--user-data-dir` is not indicated by this run.

## 7. Bridge suite

```
$ cd tools/discord-bridge && node --test
# tests 69   # suites 0   # pass 69   # fail 0   # cancelled 0   # skipped 0   # todo 0
rc=0
```
