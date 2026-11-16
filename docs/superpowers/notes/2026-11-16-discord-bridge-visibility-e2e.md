# Discord bridge visibility: real-state end-to-end (2026-11-16)

Every piece ran once against the user's real long-lived state with a scratch `TC_STATE`. Code under test: this worktree (branch `queue/discord-bridge-visibility`, HEAD `8807793`). The live board on :7700 was not touched; `board/server.py` was imported as a module (`deliver_comments` patched out, no indexer) only to build the real overview record from the real tmux state, read-only. Harness scripts: `harness.py`, `fill.py`, `drain.js` in the scratchpad `e2e/` folder.

## 1. Real dirs, before (file count printed)

Listing = `find <dir> -type f | sort`, one `md5 -q` per file, hashed again; `.env` is included in the count and listing but never read or printed.

```
discord: files=6 listing-md5=cc1fb7879dc0baa7c6afe241d6f01d8e
feed: files=0 listing-md5=d41d8cd98f00b204e9800998ecf8427e
```

`~/.local/state/agent-board/feed/` does not exist yet (0 files; the md5 above is the hash of empty input). The 6 files of `discord/` are 3 for `agent-board` (`.env`, `access.json`, `bridge.json`; `approved/` is an empty dir) and 3 for `interiors` (the same three names).

## 2. `tmux-ctl discord channel` on a copy of the real dir

Scratch `TC_STATE` holds `discord/agent-board/` copied from the real one without `.env` (`access.json`, `bridge.json`, `approved/`).

```
$ TC_STATE=<scratch>/state bin/tmux-ctl discord channel 1570102051466125332 --project agent-board
channel: 1570102051466125332 (unchanged)
rc=0
checksums identical          # md5 of access.json and bridge.json, before vs after
mtimes identical             # stat -f %m of both files, 1 s sleep between
6f6167fa8c4787aa170136c6505ad29b   access.json
108ca1d9aec07ffaaca1b2ebd90aaf90   bridge.json
```

The command reported `unchanged` and left both files byte- and mtime-identical.

## 3. `discord_feed.tick` on the real record, real lead task list, real ledgers

The record is the real `agent-board` entry of `build_overview()` (keys: `agents alerts artifacts attached epoch last_run lead needs_you path plan project spend_today`; path `/Users/francisco.ruiz/agent-board`). The lead task list is the one the board resolves through `planview.lead_entry` + `raw_live_list`: list `session-0d19924a`, 24 tasks, including the `Plan & run:` tasks; task #3 is in progress and carries `metadata.plan`.

````
tick1: {'events': 2, 'ops': 4} ops by (op,tier): {('card', '-'): 1, ('post', 'progress'): 2, ('thread', '-'): 1}
CARD-BEGIN
```
queue: running 2026-11-11-discord-bridge-visibility-design (2/15)
✓ EA part 1: final-review fix wave  (standard)
▶ BV Task 1: discord channel/bridge/audit subs  (bv-zsh)
✓ BV Task 2: node bridge  (bv-node)
✓ BV Task 3: feed core (spool, feed file, card)  (bv-py)
✓ BV Task 4: feed derivation  (bv-py)
✓ BV Task 5: board wiring (sink, keeper, tick)  (bv-py)
✓ BV Task 6: docs, lead rules, install step  (bv-zsh)
▶ BV Task 7: real-state e2e note  (bv-py standard)
· BV Task 8: USER GATE real run with the bot  (mechanical)
teammates: claude idle, ✦ bv-zsh busy, ✦ bv-py busy, ✦ bv-rev idle
waiting on you: none
updated 16:39
```
CARD-END 630
feed events: 2
{"ts": 1794865166.962927, "project": "agent-board", "spec": "2026-11-11-discord-bridge-visibility-design", "kind": "spec_started", "tier": "progress", "text": "spec started: 2026-11-11-discord-bridge-visibility-design", "refs": {"thread_key": "session-0d19924a:3"}}
{"ts": 1794865166.962927, "project": "agent-board", "spec": "2026-11-11-discord-bridge-visibility-design", "kind": "plan_written", "tier": "progress", "text": "plan written: 8 tasks", "refs": {"thread_key": "session-0d19924a:3"}}
tick2: {'events': 0, 'ops': 0} new outbox files: 0 new feed events: 0
````

The first tick baselines the history (the live ledger `.superpowers/sdd/2026-11-16-discord-bridge-visibility/progress.md` and the completed tasks) and announces only the running spec: 2 feed events (all there are, so "the first 10" is these 2), 4 ops: 1 thread, 2 progress posts, 1 card. The second tick wrote 0 ops and 0 events (dedupe on real data).

### Archived and live ledgers (30 real ledgers spanning 2026-10-28 to 2026-11-16)

The first tick baselines history, so to exercise the review lines each of the 30 real ledger dirs (`docs/superpowers/ledgers/*` plus this branch's live `.superpowers/sdd/*`, symlinked read-only into a scratch root) was derived as the ledger of a synthetic in-progress run on a primed state:

```
archived/live ledgers: 30 review events total: 407 longest text: 300 second derive per ledger: 0 events
```

Per ledger the counts run from 3 to 40 review lines (`2026-10-28-overseer` 40, `2026-10-29-retire-plan-window` 4, `2026-11-16-discord-bridge-visibility` 21, `2026-11-16-queue-reliability` 21). No text exceeded the 300-character cap, and a second derive over each ledger emitted 0 events.

### Findings on real data (not fixed here)

1. The card's task lines are "every lead task that is not a `Plan & run:` task". The real list also holds `#2 EA part 1: final-review fix wave`, so the card shows `✓ EA part 1: final-review fix wave` as if it belonged to the running spec. A card spans only the running spec's tasks in intent; the lead list has no field saying which tasks belong to which spec.
2. Flood behaviour of the 200 cap on real volume (see section 4): when 407 review posts were written on top of the 4 ops above, the cap dropped the card first, then the oldest non-mention ops, which here were the `thread` op and the two spec-started and plan-written posts. Only the newest 200 posts survived. Real runs emit far fewer than 200 ops between bridge drains, so this matters only if the bridge is down for a long time.

## 4. Node bridge with the fake client on the scratch outbox

The 407 review ops were written with `ops_for_events` + `outbox_write` into the same scratch outbox as the tick (`discord_feed.outbox_write`), the scratch dir got a fake `.env` (`DISCORD_BOT_TOKEN=FAKE.e2e-token.NOTAREALTOKEN123`), and `createBridge` from `tools/discord-bridge/bridge.js` drained it with `FakeClient` from `test/fake-client.js` (a controllable clock, no network).

```
outbox files before: 4 ops written: 407 files after (cap 200): 200
outbox files at start: 200 | remaining: 0 | failed/: 0
calls: {"send":200,"edit":0,"pin":0,"startThread":0,"createThread":0} all methods: fetchChannel,send
post sends: 200 | sent in outbox name order (subsequence check): true
log lines: 200
token occurrences in bridge.log: 0
```

All 200 files were sent in name order, none went to `failed/`, nothing was left, and the fake token appears 0 times in `bridge.log` (`grep -c`).

## 5. Real dirs, after

```
discord: files=6 listing-md5=cc1fb7879dc0baa7c6afe241d6f01d8e
feed: files=0 listing-md5=d41d8cd98f00b204e9800998ecf8427e
```

`diff before after`: identical. Both real dirs are unchanged, `interiors` included (6 files and 0 files; `feed/` still does not exist).
