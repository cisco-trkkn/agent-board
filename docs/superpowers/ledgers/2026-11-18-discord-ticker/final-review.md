# Final whole-branch review: feat/discord-ticker

Range d927393..af6b1d5 (HEAD of the worktree is af6b1d5; the only uncommitted change is the plan's `.tasks.json`). Reviewer: tk-final. Read-only: no file in the range was changed, and this file is the only thing written. The diff was reviewed in one pass, with the surrounding code read where a seam needed it.

## What I ran (this session)

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -s board/tests -p 'test_ticker.py'` | 25 tests, OK |
| `node --test test/bridge.test.js` in the worktree's `tools/discord-bridge` | 71 tests, 71 pass, 0 fail |
| discord.js 14.28.1's real `client.presence._parse` on the bridge's payload (offline, no login) | `{"activities":[{"type":4,"name":"custom","state":"wk 1% ▲0.6× · 5h 33%"}],"afk":false,"since":null,"status":"online"}`: type 4 and `state` survive |
| One real `usage.plan_limits(usage.tap_entries(now, 10**9))` on this Mac's taps | 37 tap files, 1.9 ms; real shape is `five_hour`/`seven_day` with `used_percentage` and `resets_at` in epoch seconds, as the fixtures assume |
| Real taps whose 5 h or 7 d window was already over when the tap was received | 0 of 37 (uncapped count) |
| Edge probes of `ticker.project_line` / `ops_line` (pace 1.24, expired windows, w=0, NaN spend, 120-char project name) | outputs quoted in the findings below |

Not re-run, taken from the brief: the board suite (1551 OK), `npm test` (127/127), `all.zsh` (ALL PASS 152, rc=4 from the time budget).

## Strengths

- The line builders are pure and small (`board/ticker.py:10-123`), every ⚠ input is checked for "known" before it is compared (`ticker.py:72`), and stale or missing limits can't warn (`ticker.py:19-28`). The 39/40, 79/80 and 1.2 boundaries each have a test.
- One source for the count. The card, the ops card, the views and both ticker lines all go through `discord_feed.spec_progress` (`discord_feed.py:190-196`). The project tick takes the floor from the state it just derived (`discord_feed.py:557`, `:566`), and the ops tick reads the same key from `feed-state.json` after the project ticks ran (`discord_ops.py:287`, `server.py:523`). The real run printed `4/6`, matching the lead's own list.
- Presence state is saved only for an op that reached the outbox, on both paths: `pres_written` in the project tick (`discord_feed.py:572-585`) and write-then-set in the ops tick (`discord_ops.py:303-306`). Both have a test with a rejected op.
- Lock scope is right. The new `presence_text` / `presence_ts` keys are written inside the existing feed-state flock and inside `discord_ops._state` (`discord_ops.py:70-89`). `derive` deep-copies the state, so the keys survive it. No other code writes either state file (grep over `board/`, `bin/`, `tools/`: the only writers are `discord_feed.tick` and `discord_ops._state`).
- A presence failure can't take the card or the views down (`discord_feed.py:562-569`, `discord_ops.py:299-308`), and both have tests.
- The bridge side is safe against a disconnected gateway. I read `@discordjs/ws` 's shard `send`: after the first connect it waits for `ready` instead of rejecting, and before the first connect `client.user` is null, so `applyPresence` returns early. There is no unhandled-rejection path from `setPresence`. A fresh IDENTIFY drops the status, and `shardReady` → `onReady` → `applyPresence` puts it back (`bridge.js:369`, `:502`).
- The restart ruling is implemented cleanly: `st.presence` is read once at start (`bridge.js:296`), `st` is never re-read, and the SIGTERM handler spreads the stored state, so the text survives.

## Issues

### Critical (Must Fix)

None.

### Important (Should Fix)

1. **Outside the diff, FIXED by the lead during the review (cause unconfirmed): the main checkout's bridge dependencies were gone.**
   - Status: the lead ran `tmux-ctl discord bridge install` in the main checkout. I re-checked afterwards: `node_modules` holds 15 entries and `require('discord.js').version` prints `14.28.1`. This is no longer an open merge gate. The text below records what was found.
   - Where: `/Users/francisco.ruiz/agent-board/tools/discord-bridge/node_modules` is an empty directory (only `.` and `..`, mtime Nov 18 19:08:59, birth Nov 16). The worktree's `tools/discord-bridge/node_modules` is a real directory, not the symlink plan Task 4 Step 0 asked for, born at the same 19:08:59 and filled at 19:15:33.
   - Cause: not confirmed. The timing points at the Task 4 fix round (an install or a remove that went through the link).
   - Why it matters: the three live bridges (pids 85243, 80834, 40180, all started before 19:08) still run from memory. Any restart fails with `Cannot find module 'discord.js'`, because `tools/lib/discord.zsh:164` and `:316` only test that the directory exists. That covers Task 6's `tmux-ctl discord bridge restart`, and the board keeper's restart after a crash, for every project's bot.
   - Fix: `tmux-ctl discord bridge install` (it runs `npm ci --omit=dev` in the main checkout's `tools/discord-bridge`). Check with `ls /Users/francisco.ruiz/agent-board/tools/discord-bridge/node_modules/discord.js/package.json`. Do it before the merge and before Task 6. The lead was told by message during the review.
   - Follow-up, not for this branch: the `-d node_modules` checks could test for `node_modules/discord.js` instead.

### Minor (Nice to Have)

1. **Queued presence ops are not superseded** (`board/discord_feed.py:101-102`). Only the newest presence matters, as with `card`, but `_enforce_cap` evicts only cards first. Presence ops sit in the second group with routine posts. With a bridge that stays dead while work continues (one op per minute), stale presence ops fill the 200-file cap alongside progress posts, and a restarted bridge then sends each one in turn. It needs a bridge down for about 3 hours that the keeper doesn't restart, so it is rare. Fix: put `presence` in the first victim group, or drop older queued presence files in `outbox_write`.
2. **⚠ can show beside `▲1.2×`** (`board/ticker.py:72` against `:68`). The warning compares the unrounded pace and the line shows one decimal. Probe: w=62 at half the week prints `⚠ wk 62% ▲1.2× …` (pace 1.24). The spec says "pace > 1.2", so the behaviour follows it, but the user sees a ⚠ with no field over its limit. Fix if wanted: compare `round(pace, 1) > 1.2`.
3. **The bridge logs `presence <text>` when nothing was applied** (`tools/discord-bridge/bridge.js:298`, `:305`). `applyPresence` returns silently while `client.user` is not there yet, and the success line is still written. The text is applied later by `onReady`, so the status is right in the end. Task 6's `grep presence` also matches `presence failed:`. The log line alone doesn't prove the status was set; the user's look at the phone does.
4. **An expired 5 h window still shows and can warn** (`board/ticker.py:19-28`). `five_hour.resets_at` is never read. Probe: a fresh tap with `used_percentage` 95 and a reset one hour ago prints `⚠ … 5h 95%`. None of the 37 real taps is in that state, so I could not show it happens. Fix if wanted: treat `f` as unknown when its `resets_at` is in the past.
5. **`$nan` is possible** (`board/ticker.py:10`, `:87`). `_num` accepts NaN and infinity. Probe: `spend_today = nan` prints `$nan`. The overview's spend is a sum of floats, so this is unlikely.
6. **Docs.** `tools/discord-bridge/README.md:12-13` lists the bridge's ops without `presence`. `board/ticker.py:1` still says "pure builders, no I/O" although `main()` (`:132`) now reads tmux, the taps and the usage index.
7. **`feed_tick` scans the taps on every pass, also when no project has a channel and ops is off** (`board/server.py:495-498`), and `ops_tick` scans a second time when the first result was `None` (`:532-535`). Measured: 1.9 ms for 37 tap files (load average 3.5). With ops on, which is this install, the number of scans per pass is the same as before the branch. No action needed; the cost question the ledger left for Task 5 is settled by this number.
8. **A record without `path` matches a live row whose `cwd` is the empty string** (`board/ticker.py:41-52` with `usage.in_project`). Probe printed `ctx 77%` for such a row. Overview records always carry a path, so this needs two malformed inputs at once.

## Seams the brief asked about

- **Floor and count agree between card, ops card and ticker:** yes, see Strengths. A project without its own channel has no `feed-state.json`, so its ops line reads `(spec p of N)` and it still counts in `<r> running` (R3, tested by `test_running_with_unknown_floor_counts`). When a project tick is skipped by its lock, the ops card uses the floor from the pass before: one tick late at most.
- **Presence state saved only when written:** yes, on both paths.
- **Lock scope around the ops-state keys:** inside `_state(False)`; no writer outside the lock.
- **Overview loop cost:** 1.9 ms per pass measured, plus one small file read per project for `spec_floor`.
- **Misleading status:**
  - Bridge restart: the stored text is re-applied on ready, and any op still in the outbox follows in name order, so the newest line wins.
  - Reconnect: resume keeps the status; a new IDENTIFY loses it and `onReady` re-applies it.
  - Stale tap: after 10 minutes `w`, pace and `f` become `?`, the text changes, and an op goes out.
  - What remains is by design in the spec: when the board itself stops, or a project's session ends, the bot keeps its last line until the board ticks again. The spec accepts this by leaving the clock out of the line. A possible follow-up is clearing the status when the project leaves the overview.
  - If a presence op lands in `failed/` (a disk error in `save()`, `bridge.js:304`), the board believes the line was sent and the bot shows the older one until the text next changes. With spend in the line, that is usually a minute.

## Rulings R1-R6 and the restart ruling

- R1 holds. `failing` and `stuck` are the real kinds (`board/overview.py:170`, `:179`); context, burn, total, model_mismatch and day_total come from `board/usage.py` and now read under `alerts:`.
- R2 holds. The sid row wins, including a lead inside a worktree (`test_lead_in_worktree_by_sid`). A sid row with no numeric `context_pct` falls back to the role-lead rows of the repo.
- R3 and R4 hold. The `queue: running` prefix is unchanged, and its only consumers match by prefix (`board/discord_ops.py:389`, `:397`, `:405`).
- R5 holds. `live=None` writes no presence op, tested on both ticks.
- R6 holds. The extra keyword arguments are what the wiring passes.
- Restart ruling holds. It is tested with a second bridge on the same directory.

## Evidence checks

Fixture origin:
- `test_ticker.py` limits, live rows and tasks: hand-written. The shape was checked against the real system three ways: the lead's `resets_at` probe in the ledger, the Task 5 real run, and my read of the 37 live taps. No finding.
- `test_discord_feed.py` and `test_discord_ops.py` additions: hand-written task lists and alert dicts. The alert kinds match the ones `overview.py` and `usage.py` emit. No finding.
- `fake-client.js` `setPresence`: a hand-written recorder. No test in the repo runs discord.js's own presence code. I ran the real `_parse` once (table above), and Task 6 is the named gate for the real gateway. No finding beyond Minor 3.

Artefact under test:
- The Python tests import the real `ticker`, `discord_feed`, `discord_ops` and `server`. The tick tests drive the real `tick` functions against a temporary `TC_STATE` and read the real outbox files.
- The bridge tests call the real `createBridge`.
- `test_discord_wiring.py` stubs `discord_feed.tick` and `ops_tick`, so it proves the arguments only. The real ticks are covered in their own files.
- `ticker.main`: its test patches `_tmux`, `usage.connect` and `planview`. The unpatched run is the Task 5 real run (`python3 board/ticker.py agent-board`, quoted in the brief). The `tmux display -p -t "=<name>:" '#{session_path}'` argv is exercised only there.

User-experienced check:
- Nothing in the diff measures what Discord shows. That is Task 6, a user gate, still open.

State:
- Every test runs on fresh temporary state (`TC_STATE` temp dirs, `os.tmpdir()` for the bridge). No test hard-codes a path under HOME.
- The one real-state run is read-only on this Mac.
- Long-lived conditions no test or run met: the weekly reset rolling over, spend across midnight, a bridge that was down for hours with ops queued (Minor 1), and two leads in one repo.

Universal claims:
- "`main` writes nothing" rests on an uncapped `rglob` of the test's `TC_STATE`, with `usage.connect` mocked. The real `connect` runs a WAL pragma and the schema script, so "Reads only" in the docstring overstates (already a deferred minor).
- "No other writer of the state files" rests on a full grep, listed under Strengths.
- No test asserts over a whole environment mapping.

Inputs agents cannot read: none in this branch besides the phone, which is Task 6.

Runbook preconditions: the plan's Task 6 says "both bridges restarted". That step needs `tools/discord-bridge/node_modules` to hold discord.js in the main checkout, which was false during the review and is true again after the lead's `tmux-ctl discord bridge install` (Important 1).

Endpoint trust: not applicable.

## Triage of the ledger's deferred minors

None of them has to be fixed before the merge.

| Deferred minor | Verdict |
| --- | --- |
| T4: the 128-cut test checks length only | Leave. The board validates 1..128 before the bridge sees the text. |
| T4: `presenceText` kept after a failed apply | Leave. It is the wanted behaviour: `onReady` retries it. |
| T4: `onReady` re-apply failure path untested | Leave. One `try`/`catch` with a log line. |
| T4: `save()` outside the inner `try` | Leave. A disk error moves the op to `failed/`; effect described under "Misleading status". |
| T1: non-numeric task id excluded from the count but shown on the card | Leave. Task ids are numeric in practice. |
| T1: id 0 and non-numeric id treated alike | Leave. |
| T2: missing `received_at` treated as stale | Leave. `plan_limits` always sets it. |
| T2: ops whole-line cut can drop spend and running | Leave. It needs a project name near 90 characters (my probe used 120). |
| T2: no test for a record without `path` | Leave. See Minor 8. |
| T3: limits computed on every pass | Closed by measurement: 1.9 ms (Minor 7). |
| T3: duplicate `plan_limits` fallback in `ops_tick` | Leave. Cosmetic; a follow-up can drop it. |
| T3: ops presence swallows `OSError`, the card write propagates | Leave. The safer of the two behaviours for a status line. |
| T3: no RED evidence for the "save although the write raised" mutation | Leave. The assertion exists (`assertNotIn("presence_text", st)`) and reading the code confirms it guards the branch. I did not run the mutation, because that would change a file. |
| T5: `main` uses the raw `#{session_path}`, the server uses `relay.root_for` | Leave. It affects the check tool only, for a session started inside a worktree. |
| T5: "reads only" overstates | Fold into the docstring fix of Minor 6 when someone next touches the file. |

## Recommendations

- The bridge dependencies are restored, so Task 6's bridge restarts can go ahead.
- Minor 1 is the one I would pick up first in a follow-up: a two-line change that makes "newest wins" hold in the outbox as well.
- Add the `presence` op to the bridge README with that follow-up.

## Assessment

**Ready to merge: yes.**

**Reasoning:** The code in the range meets the spec and the plan, the seams between the tasks hold, and I found no Critical or Important defect in the diff. The one Important item was outside the diff (the main checkout's bridge dependencies) and the lead fixed it during the review; I confirmed discord.js 14.28.1 loads there again. The 8 minors can all wait. Task 6, the user gate on the phone, is still open.

Counts: Critical 0, Important 1 (outside the diff, fixed by the lead, cause unconfirmed), Minor 8. Deferred minors that must be fixed before merge: 0 of 15.

Context learned:
- `Gotchas`: `tools/discord-bridge/node_modules` in a worktree must never be a link that an `npm ci` or a remove can reach through; the main checkout's copy was emptied on 2026-11-18 while live bridges kept running from memory, and `discord.zsh` only checks that the directory exists (files: tools/lib/discord.zsh, tools/discord-bridge/package.json)
- `Map`: discord.js 14.28.1 `client.user.setPresence` is synchronous and never rejects on a disconnected shard; the ws shard queues the packet until `ready`, and a fresh IDENTIFY drops the status, so it must be re-applied on `shardReady` (files: tools/discord-bridge/bridge.js)
- `Map`: `discord_feed._enforce_cap` evicts `card` ops first, then every op that is not card/thread/archive/prompt/edit/approval or a mention post; `presence` is in that second group (files: board/discord_feed.py)
