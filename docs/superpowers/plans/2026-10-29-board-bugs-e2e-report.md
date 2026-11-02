# Board-bugs: real-state check of the Usage tab (Task 8)

Run on 2026-10-29 against the real state dir `/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmux-ctl-503` (`board/tc_env.py` `state_dir()`, `TC_STATE` unset), from branch `feat/board-bugs` at 04af3ab.

## Setup

- Second board: `TMUX_DASH_PORT=7710 python3 board/server.py` from the worktree, in the background, PID 52361. It printed `tmux-dash on http://127.0.0.1:7710/<token>/`. Port 7700 was never queried or touched.
- Stopped at the end: `kill 52361`, then `ps -p 52361` printed nothing and `ps ax | grep '[s]erver.py' | grep -c 7710` printed `0`.
- Real tmux sessions with a project path (`/api/state` of 7710): `agent-board`, `francisco_ruiz`, `interiors`, `master-gcp-repo`. The board takes a session's project path from its window 1 pane. The `claude` window of each of these four sessions runs in `/Users/francisco.ruiz`, so all four resolve to that path, and `/api/usage` keeps only sessions whose cwd is exactly that path or sits under `<path>/.claude/worktrees/`.
- **Finding (not a Task 7 defect, existing scoping):** for these four session names the API therefore returns the same one live row (the home-directory lead `3936d130`), not the 15 agent-board sessions. To cover every real session, the comparison below is also run in-process: `usage.report(conn, <repo>, ...)` is the function the API calls, with the real state dir and the real index, for the project paths `/Users/francisco.ruiz/agent-board`, `/interiors`, `/master-gcp-repo` (the tmux panes' real project dirs, from `list-sessions -F '#{session_path}'`). Both are shown; the in-process one is labelled.
- Plan limits (`plan_limits` in the API response): `{session_id: e85f367a-f6cf-4db4-bb2d-4d1fa8b4b47a, received_at: 1793287406.87, five_hour: {used_percentage: 14, resets_at: 1793303400}, seven_day: {used_percentage: 98, resets_at: 1793469600}}`. It is the freshest tap with `rate_limits`. Later polls returned it as non-null as well.
- Counts: 21 tap files in `<state_dir>/statusline/` at the first read and at the last; all 21 were fresh (`received_at` within 1800 s) at the first read.

## Comparison

**API, port 7710** (`/api/usage?session=<name>` for each of the four sessions, tap files read in the same script, at epoch 1793287434): each of the four returned one live row, identical:

| session id | role | source | board ctx % | tap ctx % | model board / tap | effort board / tap |
|---|---|---|---|---|---|---|
| 3936d130 | lead | tap | 0 | null | claude-opus-5-5 / claude-opus-5-5 | medium / medium |

The tap's `used_percentage` is `null` (payload before the first API call, `total_input_tokens` 0, tap age 1513 s), so there is no tap figure to compare; the board shows 0 (the tap-only default). Model and Effort match; `model_name` is `Opus 5.5`. 4 of 4 API rows are this same row.

**In-process, all project paths** (same `report()` code, epoch 1793287459, tap files read in the same script). 21 live rows, 21 tap files, 21 `source: tap`, 21 within ±1 on Context %, 21 Model matches, 21 Effort matches. The home-directory row is the one above; the other 20:

| session | role | board ctx % | tap ctx % | model | effort | tap age s |
|---|---|---|---|---|---|---|
| e85f367a | teammate | 8 | 8 | sonnet-5-5 | medium | 1 |
| edef79d7 | worker | 12 | 12 | opus-5-5 | medium | 75 |
| ca163340 | teammate | 7 | 7 | sonnet-5-5 | medium | 114 |
| 7e9f2488 | teammate | 9 | 9 | sonnet-5-5 | medium | 128 |
| e29aa8d3 | teammate | 6 | 6 | sonnet-5-5 | medium | 90 |
| bc42289d | teammate | 37 | 37 | sonnet-5-5 | medium | 305 |
| 515fe2c8 | worker | 37 | 37 | opus-5-5 | medium | 633 |
| df851d5f | worker | 33 | 33 | opus-5-5 | medium | 758 |
| d9b4c8c1 | teammate | 10 | 10 | sonnet-5-5 | medium | 766 |
| b06aa728 | teammate | 11 | 11 | sonnet-5-5 | medium | 885 |
| 3b7c3be8 | teammate | 12 | 12 | sonnet-5-5 | medium | 865 |
| 86e88607 | teammate | 9 | 9 | haiku-5-5 | medium | 1398 |
| 0c871149 | teammate | 7 | 7 | sonnet-5-5 | medium | 1370 |
| 2c1daad1 | lead (agent-board) | 0 | null | opus-5-5 | medium | 1537 |
| 9f9765f2 | teammate | 24 | 24 | sonnet-5-5 | medium | 1537 |
| 9d293697 | lead (interiors) | 23 | 23 | opus-5-5 | medium | 464 |
| 44ae3edd | teammate | 13 | 13 | sonnet-5-5 | medium | 467 |
| a960821d | teammate | 23 | 23 | sonnet-5-5 | medium | 465 |
| 8844abce | lead (master-gcp-repo) | 0 | 0 | opus-5-5 | medium | 1537 |
| d3173393 | worker | 30 | 30 | opus-5-5 | medium | 1537 |

(`2c1daad1` and `3936d130` have tap `used_percentage: null`; the board shows 0. They count as within ±1 because the tap holds no number, so this is "no figure to compare", not a measured match: 19 rows of 21 compare two numbers, all equal.) No row was off by more than 1, so no re-read was needed; every difference is 0.

Last re-run at epoch 1793287871 (idle sessions had aged past 30 min): 15 live rows, 15 `source: tap`, 15 with ±1 on Context %, Model and Effort all matching; the other 6 tap files had gone stale and, with no recent transcript calls, those sessions were no longer live, as designed.

## Transcript fallback

No session had a stale or missing tap file and also recent transcript calls: the idle sessions whose taps went stale also had no call in the last 30 min, so they left the live list (live rows 15 → 13 → 12 over the wait). So, as the Decided block allows, one tap file was renamed aside for one poll and restored in the same command chain (with a `trap`):

- File: `515fe2c8-8aea-4e39-b8cf-8e8e5b78261c.json` (an idle overseer worker, tap age 1024 s, 288 indexed calls). cksum before and after: `1075630686 2003` both times.
- Poll at epoch 1793287861 (in-process `report()` for `/Users/francisco.ruiz/agent-board`): the row came back as `{"session_id": "515fe2c8-8aea-4e39-b8cf-8e8e5b78261c", "role": "worker", "cwd": ".../worktrees/overseer", "model": "claude-opus-5-5", "model_name": null, "effort": "medium", "context": 370851, "context_pct": 37, "source": "transcript"}`. `model_name` is null, which only a tap carries. Its Context % (37) equals the tap's 37 from before the rename.
- Restored: `ls -l` shows the file back (2003 bytes), 21 tap files, 0 files ending in `e2e-aside`.
- Not done through the API: the API's session-to-project mapping (see Setup) cannot select the agent-board worktree sessions, so this poll is in-process, not port 7710.

## Commands run

Live tmux server, read-only: `~/.local/bin/tmux list-sessions`; `~/.local/bin/tmux list-windows -a -F '#{session_name} #{window_name}'`; `~/.local/bin/tmux list-sessions -F '#{session_name} #{session_path}'`; `~/.local/bin/tmux list-panes -a -F '#{session_name}:#{window_name} #{pane_current_path}'`.

Board and files:
- `TMUX_DASH_PORT=7710 nohup python3 board/server.py` (background, PID 52361), then `kill 52361`, `ps -p 52361`, `ps ax | grep '[s]erver.py' | grep -c 7710`.
- `curl -s "http://127.0.0.1:7710/<token>/api/usage?session=agent-board"` and `.../api/state` (port 7710 only).
- `python3 -c 'import tc_env; print(tc_env.state_dir())'`; `ls -l <state_dir>/statusline`; `python3 -m json.tool <tap file>`; `date +%s`.
- Scratch scripts in the session scratchpad: `cmp.py` (API rows for the four sessions vs tap files), `inproc.py` (in-process `usage.report()` per project path vs tap files), two polling loops and a tap-age/call-age listing (read-only on the index).
- The rename: `mv <515fe2c8>.json <515fe2c8>.json.e2e-aside`, one in-process poll, then `mv <515fe2c8>.json.e2e-aside <515fe2c8>.json` through a `trap`, then `ls -l`, `ls | grep -c aside`, `cksum`.
- `grep -n` / `sed -n` reads of `board/usage.py`, `board/server.py` and `docs/superpowers/plans/2026-10-29-statusline-probe.md`; no file in `board/` was edited.
