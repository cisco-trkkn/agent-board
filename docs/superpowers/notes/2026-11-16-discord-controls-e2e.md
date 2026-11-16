# Discord controls: real-state end-to-end (Task 6)

Run on 2026-11-16 from the worktree `queue/discord-controls` at base `36e67ad`, by the teammate dc-e2e. Harness scripts live in the agent scratchpad and are not committed (`check2.py`, `check34.py`, `e2e34.zsh`, `drive.js`, `fake_pane.js`).

Seams, so nothing real was touched:

- Board code is imported from the worktree (`board/server.py`, `board/discord_controls.py`) and called the way `server.feed_tick` does. The live board on :7700 was never started, hit or restarted.
- `TC_STATE` is a scratch dir in every run, so `tc_env.discord_dir()` points into scratch. Both harnesses assert that before writing.
- Real windows get `show` only. In check 2 the runner wrapper raises on any `once`/`deny`.
- Scratch tmux servers use the approve tests' `tt_setup` (`-L <sock> -f /dev/null`).
- The bridge is the real `createBridge` with the Task 2 `FakeClient` (`tools/discord-bridge/test/fake-client.js`), on a scratch dir with a dummy `.env`. No real token was read or used.

## Check 0: real discord dir, before and after

Before (10 files, `find … -type f | sort | xargs md5 -q | md5`): `a75fa51e3b024b9752a4d1c82a525bed`.
After the whole run (10 files): `4dfec913cd1bf0f5a07160008a5feca6`.

**The checksums differ, and every difference was written by the live bridge or the live board, not by this harness.** The dispatch expected this (the live bridge may write there).

| File | Change | Writer |
| --- | --- | --- |
| `bridge.pid` | 95257 (at dispatch) → 35881 | The live bridge was restarted by the lead (23:10Z and 23:22Z, for the pin-permission fix): `bridge.log` has three `connected` lines at 23:10:32Z, and `ps -p 35881` shows it started 18:10:31 local, running `tools/discord-bridge/bridge.js` on the real dir. |
| `bridge.log`, `bridge-state.json` | appended / rewritten at 23:10–23:11Z | That bridge: three `connected` lines at 23:10:32Z and one `failed … 403` line at 23:11:12Z were appended after the before-checksum. |
| `feed-state.json`, `feed-state.lock` | mtime moves every ~40 s | The live board's feed tick. |
| `outbox/failed/1794867357783-7f56f087.json` (+`.err`) replaced by `1794870670993-18e894ac.json` (+`.err`) | a `card` op failed with `status 403: Missing Permissions` | The live board's card op. Its text is `queue: running 2026-11-11-discord-controls-design (1/13)`, `teammates: claude busy, ✦ dc-e2e busy`, `updated 18:11`: the real queue's card, not any scratch window name (`✦ e2e`). It is the same 403 that the older failed op carries; the bridge's account lacks a permission on the card channel. |

Same file list in both runs (`diff before.list after.list` shows only the two renamed failed files). `access.json`, `bridge.json` and `.env` are byte-identical. The harness wrote only under scratch `TC_STATE` (the scratch dir held its own `outbox/`, `events/`, `audit.jsonl`, `controls-state.json`).

## Check 1: `show` on every real window (nothing pressed)

`TC_SESSION=agent-board bin/tmux-ctl approve <window> show`; session `agent-board` had three windows:

```text
window=[claude] rc=1 first=[approve: no permission prompt in claude]
window=[tasks] rc=1 first=[approve: no permission prompt in tasks]
window=[✦ dc-e2e] rc=1 first=[approve: no permission prompt in ✦ dc-e2e]
```

All three exit 1 with `no permission prompt`. No `once`/`deny` was run on a real window.

## Check 2: `step` on the real `agent-board` overview record

The record comes from `server.build_overview()` (1.8–2.0 s to build) with a scratch `TC_STATE`, project `agent-board`. At run time its `needs_you` was `[]`, so there was no prompt to post.

```text
overview build seconds: 1.963 | needs_you: []
step #1: ops written = 0; files: []
step #2: ops written = 0; files: []
runner refused once/deny calls: 0 | add_line calls: []
```

The ops written are none, and the second `step` writes 0 ops. The refusal wrapper was never hit (0 refused calls). The real record had no teammate prompt at that moment, so this check shows the wiring reads a real record without side effects, not a post; checks 3 and 4 cover the post.

## Check 3: scratch server, fake TUI, real `approve` press

The window `✦ e2e` runs a pane process named `claude` (a copy of the `node` binary named `claude`; a `zsh` symlink or copy still shows as `zsh` on macOS, and `zsh` is killed when copied). It draws a real captured prompt from `tools/tests/fixtures/approve/*.txt` and records the first key it receives. `fake_claude_tui.zsh` is a discord-watchdog stand-in with no permission prompt, so the approve tests' fixtures are the fake here. The overview record is built by `server.build_overview()` against the scratch server (`TMUX` points at it).

```text
overview record needs_you: [{"window": "✦ e2e", "pane": "%1", "kind": "claude", "reason": null}]
step#1 ops: [{"op": "prompt", "key": "%1:3bdb8d31cc2758faea1fadaf2598becafc5904af", "window": "✦ e2e", "tool": "Bash command", "lines": ["git config user.name probe-user"], "tier": "decision", "mention_user": true}]
```

`step` posts exactly one prompt op. After the bridge posted it, a `perm` allow event was written by the bridge's own `onInteraction` (a fake interaction by allowlisted `U1`):

```text
click: {'ok': 'click', 'deferred': 1, 'replies': []}
event file: {"type":"perm","key":"%1:3bdb8d31cc2758faea1fadaf2598becafc5904af","choice":"allow","user":"U1","message_id":"m1","ts":1794870847102}
step#2 ops: [{"op": "edit", "key": "%1:3bdb…", "text": "🔐 ✦ e2e wants to run Bash command: ✅ allowed by you"}]
presses: [['once', '--expect', 'git config user.name probe-user']] | fake TUI got key: GOT:1
audit: {"ts": "2026-11-16T23:14:07Z", "user": "U1", "action": "perm", "target": "%1:3bdb…", "result": "allowed"}
events left: [] controls-state: {"prompts": {}}
```

The real `tmux-ctl approve once` pressed `1`, the fake TUI recorded `GOT:1`, and the edit op reads `✅ allowed by you`.

Changed prompt. A second prompt (`touch made-by-test`) was posted. Before the click, the pane was swapped to a different prompt (`git config user.name probe-user`):

```text
step#3 ops: [{"op": "prompt", "key": "%1:ade1bd05…", …, "lines": ["touch made-by-test"], …}]
click: {'ok': 'click', 'deferred': 1, 'replies': []}
step#4 ops: [{"op": "edit", "key": "%1:ade1bd05…", "text": "🔐 ✦ e2e wants to run Bash command: ⚠️ not pressed: approve: the prompt in ✦ e2e changed"}]
swaps: ['bash-git.txt'] | fake TUI got key: NOKEY
audit: {"ts": "2026-11-16T23:14:09Z", "user": "U1", "action": "perm", "target": "%1:ade1bd05…", "result": "not pressed"}
```

The edit reads `⚠️ not pressed: approve: the prompt in ✦ e2e changed` and the new pane received no key.

How the change was timed: `step` scans (`show` per window) before it consumes events, and the scan drops a key whose prompt changed as `answered elsewhere` (ruling P3). A change before the step would therefore never reach the press. The harness runner swaps the pane right before it runs the real `approve once` call, which is the window the check names (after the post, before the press). The real `tmux-ctl approve` ran unpatched in both cases.

## Check 4: node bridge on the fake client, scratch outbox

The bridge drained the same scratch outbox the board wrote. The first tick (the prompt op):

```text
fetchChannel
send {"content": "<@U1> 🔐 ✦ e2e wants to run Bash command\n```\ngit config user.name probe-user\n```", "allowedMentions": {"users": ["U1"]}, "components": [{"type": 1, "components": [{"type": 2, "style": 3, "label": "Allow once", "custom_id": "ab:perm:%1:3bdb…:allow"}, {"type": 2, "style": 4, "label": "Deny", "custom_id": "ab:perm:%1:3bdb…:deny"}]}]}
outbox left: [] failed: []
```

The tick after the press (the edit op):

```text
fetchChannel
fetchMessage
edit {"content": "🔐 ✦ e2e wants to run Bash command: ✅ allowed by you", "components": []}
```

The second pair (prompt, then edit `⚠️ not pressed: …`) went the same way. At the end:

```text
outbox/failed: (absent) | events/failed: (absent) | outbox left: []
```

Each prompt was sent with two buttons, each edit edited the right message and cleared the buttons, and `failed/` is empty (absent in both the outbox and events).

## Carry-in 1: `step` duration, and overlap with the overview build

Against the real record (`needs_you` empty), 7 runs of `discord_controls.step`: min 0.000 s, median 0.000 s, max 0.001 s. With nothing to show, it is a file read plus the state save.

The cost scales with the `show` calls. To bound it, the real record was given a synthetic `needs_you` of five windows (the real `tasks` and `✦ dc-e2e`, plus three that do not exist), so each `step` ran five real `tmux-ctl approve <w> show`. 5 runs: min 1.044 s, median 1.045 s, max 1.082 s, about 0.2 s per `show`. Real prompts cost the same `show` once per `needs_you` window, plus one per tracked key.

Overlap: `OVERVIEW_EVERY = 10` (`board/server.py:228`). `overview_loop` runs `overview_payload` (build, then `feed_tick`, which calls `step`) and only then sleeps 10 s, so the loop never starts a build while its own `step` runs. A browser request to `/api/overview` can start a second `feed_tick` when the cache is older than 10 s, because `feed_tick` runs after the lock is released. Two `step`s are serialised by the `controls-state.lock` flock, so they queue and never run side by side on the same state. A `step` only exceeds 10 s when about 50 `show` calls pile up, or on timeouts (`timeout=20` per hung `show`; two hung windows already exceed it). In that case the next build still waits for the loop, not for the step.

## Carry-in 2: the full text of a cut prompt

A scratch `✦ e2e` prompt with a 25-line command (a real `bash-multiline` capture with the command widened to 25 lines of 64 characters; 1674 characters joined):

````text
prompt op: 25 lines, joined length 1674
Discord post content (1574 chars):
…
│ echo line21 xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
… (3 more lines)
```
Open on the board to see all of it.
buttons: ['Deny']
````

The Discord post carries 22 of the 25 lines, `… (3 more lines)` and `Open on the board to see all of it.`, with only a `Deny` button. The full text is kept in:

- `controls-state.json` `prompts[key].lines`: 25 lines, the last `│ echo line24 xxxx…`.
- The `prompt` op's `lines` in the outbox: 25 lines.
- The window's pane itself, which the board shows as a live terminal: 38 non-empty rows.

It is not in the overview record: its `needs_you` items carry only `window`, `pane`, `kind` and `reason`. The board's pane preview (`paneclass`/`server.preview`) keeps only the last 10 non-empty rows, so on the board the full command is read in the window, not in a card or API field.

## Cleanup

The scratch server was killed by the harness trap, and the check afterwards:

```text
$ ~/.local/bin/tmux -L tctest-44024-15740 ls
error connecting to /private/tmp/tmux-503/tctest-44024-15740 (No such file or directory)   (rc=1)
```

No `drive.js` / `fake_pane.js` process remains (`pgrep -fl` count 0), and every scratch dir of this run was removed. Nine older `tctest-*` sockets from 2026-11-10 to 12:55 on 2026-11-16 in `/private/tmp/tmux-503/` predate this run and are not touched.

## What this does not show

- No real Discord API call happened: the client is fake, so button rendering, 403s on the real channel and the phone tap are Task 7's gate.
- Check 2 ran against a record with no waiting teammate; the post path ran only on the scratch server.
