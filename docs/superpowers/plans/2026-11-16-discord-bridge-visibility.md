# Discord bridge visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-project Discord bridge posts a pinned status card, a thread per spec, and tiered alerts into the project's home channel, all decided by the board and sent by a small node program through a file spool.

**Architecture:** The board (python, new `board/discord_feed.py`) derives feed events from task lists, ledgers and notifier events, appends them to `<base>/feed/<project>.jsonl`, and turns them into outbox ops in `<dir>/outbox/`. The bridge (`tools/discord-bridge/`, node + discord.js 14) sends the outbox in name order and records ids in `<dir>/bridge-state.json`. `tmux-ctl discord channel|bridge|audit` configures and starts it; the board's poll loop keeps it running.

**Tech Stack:** python 3 (board, unittest), zsh (tmux-ctl, lib.zsh tests), node 22 + discord.js 14 (`node --test`), jq.

**Spec:** `docs/superpowers/specs/2026-11-11-discord-bridge-visibility-design.md` (all sections 1–11; §8 replaces §6's mention rule).

## Global Constraints

Paths and names:
- `<base>` = `${TC_STATE:-$HOME/.local/state/agent-board}` (the same base `tools/lib/discord.zsh` `_dc_root` uses; NOT `tc_env.state_dir()`, whose default is a tmp dir). `<dir>` = `<base>/discord/<project>`. Feed file: `<base>/feed/<project>.jsonl`. Python helper: `tc_env.agent_base()` returns `<base>`, `tc_env.discord_dir(project)` returns `<dir>`.
- `<project>` is the discord key: tmux session group, else session name, `-bg` stripped (same as tmux-ctl `FEEDKEY`). The board maps an overview record to it by name; a record whose session belongs to a group uses the group name.
- Spool (spec §1): `<dir>/outbox/<ts>-<id>.json` written via `.tmp` + rename; `<ts>` = 13-digit epoch ms, `<id>` = 8 hex chars; name order = send order. `<dir>/outbox/failed/<name>` + `<name>.err`. `<dir>/bridge-state.json` (bridge-owned) `{"card_message_id", "threads": {"<key>": "<thread id>"}, "guild_id", "connected": bool, "ts"}`. `<dir>/events/<ts>-<id>.json` (bridge-written). `<dir>/feed-state.json` (board-owned dedupe + card throttle). `<dir>/bridge.pid`, `<dir>/bridge.log`, `<dir>/audit.jsonl`.
- Outbox ops (exact keys): `{"op":"post","thread_key"?: str,"text": str,"tier": "critical"|"decision"|"progress","mention_user": bool,"link_thread_key"?: str,"files"?: [abs paths]}` (no `thread_key` = home channel); `{"op":"card","text": str}`; `{"op":"thread","key": str,"title": str}`; `{"op":"archive","key": str}`. `routine` never becomes a post.
- Feed event (spec §11, exact keys): `{"ts": float, "project", "spec", "kind", "tier", "text", "refs": {"task"?, "thread_key"?, "run"?, "file"?}}`. Kinds this plan emits: `spec_started`, `plan_written`, `task_done`, `review`, `spec_outcome`, `report_written`, and notify kinds `needs_you`, `test_failed`, `failing`, `stuck`, `plan_done`, `lead_idle`, `context`, `usage`.
- Tiers (spec §8): `needs_you` → decision; `test_failed`, `failing`, `stuck`, `spec_outcome` with `failed — …` → critical; `plan_done`, `task_done`, `plan_written`, `review`, `spec_outcome` merged/mr/kept, `spec_started`, `report_written` → progress; `lead_idle`, `context`, `usage` → routine. critical and decision set `mention_user: true` and go to the home channel with `link_thread_key` = the running spec's thread key when one exists; progress goes to the spec's thread (`thread_key`), no mention.
- Card (spec §4): one code block, total text ≤ 1900 characters, overflow cut with `… <n> more`; written only when the text changed and at most every 30 s. Lines: `queue: running <spec basename> (k/n)` | `queue: paused` | `queue: idle`; running plan's tasks `✓`/`▶`/`·` + subject, owner, tier; teammates name busy/idle; `waiting on you:` lines (window name) or none; `updated HH:MM`.
- Outbox cap 200 files per project: drop oldest `card` ops first, then oldest non-mention ops; never drop a post with `mention_user: true`.
- Kill switches: `TC_DISCORD_BRIDGE=0` (no bridge start), `TC_DISCORD_ALERTS=0` (no notifier → discord sink), `TC_NOTIFY=0` keeps meaning banners only.
- Bridge: token read only from `<dir>/.env` line `DISCORD_BOT_TOKEN=<token>`, never argv/env; log never contains the token or a message body beyond 80 characters; ignores every message and every component whose `customId` does not start with `ab:`; intents Guilds, GuildMessages, GuildMessageReactions, DirectMessages, DirectMessageReactions; exits on SIGTERM; at most one card edit per 30 s; 4xx → `outbox/failed/`, 5xx/network → retry with backoff, order kept; deletes an outbox file only after Discord accepted it.
- Delivery semantics of the outbox consumer: one bridge per `<dir>` (pid file); in-order, at-least-once (a crash between send and delete resends one post); `card` and `thread` ops are idempotent (edit in place; one thread per key via `bridge-state.json`).
- `tmux-ctl discord channel <id>` writes `access.json` `groups[<id>] = {"requireMention": false, "allowFrom": <every allowFrom id>}` and `bridge.json` `{"channel": "<id>", "user": "<first allowFrom id>"}`, keeps every other key, and is a byte-level no-op (file mtime unchanged) when both already hold exactly those values.
- Lead-rule edits to `claude/orchestrator.md` are applied as a generated, `patch --dry-run`-checked patch.
- Commits: conventional with scope (`feat(discord): …`, `feat(board): …`, `docs(…): …`), ending with the attribution trailer your harness specifies.

**User decisions (already made):** the 2026-11-11 and 2026-11-12 decisions in the spec ("Decisions" and "Additions"): bridge per project, one bot per project, everything in the project channel, pushed status and alerts, tiers, deep links, audit log, feed event contract. Queue answer for this spec: merge locally, no push.

**Lead rulings (plan time):**
- P1: the feed file uses `<base>` (persistent), not `tc_env.state_dir()`; spec §11 writes `${TC_STATE}` without a default, and the feed must survive a reboot. Cost if wrong: a path rename.
- P2: the bridge window is started by a new `tmux-ctl discord bridge start --project P` that creates window `discord` in `P-bg` directly (ensure_bg with `BG=P-bg`), not via `is_bg_win` (which would turn `discord` into a run/send lane). Cost if wrong: the window is not reachable through `tmux-ctl run`.
- P3: the plan file of a `Plan & run:` task is named by a new `metadata.plan` the lead sets after writing-plans (lead rule added in Task 6); without it the feed posts no "plan written" line. Cost if wrong: one missing post per spec.
- P4: the morning report trigger posts the one-line summary only; the file attachment waits for the files spec. Cost if wrong: none (spec says "with the files spec").
- P5: review verdict lines are ledger lines matching `^(Final (re-)?review|Final fix wave|Task [0-9]+: (complete|re-review|fix round)|Batch [0-9-]+: review)` (real ledgers have no fixed verdict token). Cost if wrong: some verdicts are missed or extra lines posted.
- P6: §10 audit: this plan ships the writer `discord_feed.audit_append`, `tmux-ctl discord audit [--since <ISO>]`, and the events-dir reader stub (which logs every inbound event as `result: "ignored"` until the controls spec handles them). Cost if wrong: none; controls extends it.

---

### Task 1: tmux-ctl discord channel, bridge and audit subcommands

**Goal:** `tmux-ctl discord channel|bridge install|bridge start|bridge stop|audit` exist and `status` shows the channel and bridge lines.

**Files:**
- Modify: `tools/lib/discord.zsh`
- Modify: `bin/tmux-ctl` (usage comment only, line ~43)
- Create: `tools/tests/test_ctl_discord_channel.zsh`

**Acceptance Criteria:**
- [ ] `channel <id>` writes `groups[<id>]` and `bridge.json` exactly as Global Constraints say, keeps other keys (`dmPolicy`, `pending`, other groups, `ackReaction`), modes 600.
- [ ] `channel <id>` with identical existing entries leaves both files byte-identical and their mtimes unchanged, prints `channel: <id> (unchanged)`, exit 0.
- [ ] `channel` with no allowFrom ids exits 1 with `discord: pair or allow a user first`; a non-numeric id exits 2 (usage).
- [ ] `status` prints `channel: <id>|none` and `bridge: running (pid N)|stopped|no channel|deps missing` after the existing lines (the `bridge:` value tested for `no channel`, `deps missing`, `stopped`, and `running` with a live fake pid whose cmdline contains `bridge.js`).
- [ ] `bridge start --project P`: no-op printing `bridge: running (pid N)` when `<dir>/bridge.pid` names a live process whose command contains `bridge.js`; otherwise refuses with a one-line reason when token, channel or `tools/discord-bridge/node_modules` is missing; else creates window `discord` in session `P-bg` (creating `P-bg` with its `tests`/`shell` windows and `@tc_bg` if absent) running `node <repo>/tools/discord-bridge/bridge.js <dir>`, after killing a stale `discord` window. Tested on the scratch tmux server with a fake `node` on PATH.
- [ ] `bridge stop` sends TERM to the live pid and removes a stale pid file; `bridge install` runs `npm ci --omit=dev` in `tools/discord-bridge` (tested with a fake `npm` recording argv and cwd).
- [ ] `audit [--since <ISO>]` prints `<dir>/audit.jsonl` lines as `<ts> <user> <action> <target> <result>`, filtered by ts ≥ since; missing file prints `audit: none`.
- [ ] `bin/tmux-ctl discord` usage lists the new subcommands.

**Verify:** `zsh tools/tests/test_ctl_discord_channel.zsh && zsh tools/tests/test_ctl_discord.zsh`

**Steps:**

- [ ] **Step 1: Write the failing test file** `tools/tests/test_ctl_discord_channel.zsh`, with the same header and helpers as `tools/tests/test_ctl_discord.zsh` (copy its setup block: `source "${0:A:h}/lib.zsh"`, `tt_setup claude`, scratch `HOME`/`CLAUDE_CONFIG_DIR`, `D="$TC_STATE/discord"`, project `tt`, the `run` helper, the cleanup trap). Differences from that file: none in setup; it adds a fake `node` and fake `npm` on PATH (`print -r -- "$PWD $*" >> $S/npm.log`) and checks mtimes with `zstat +mtime` (zsh/stat) or `stat -f %m` fallback. One `check` per acceptance criterion. The idempotence check: seed access.json and bridge.json with the exact target values, record mtime, sleep 1, run `channel`, assert mtime equal and output `channel: <id> (unchanged)`. Mutation: remove the equality short-circuit → the mtime check fails.
- [ ] **Step 2: Run it and see it fail** for "unknown subcommand" (usage, exit 2).
- [ ] **Step 3: Implement in `tools/lib/discord.zsh`.** Add `channel|bridge|audit` to the `case` at :44-58 (`channel` and `bridge` need an arg). `_dc_channel <dir> <id>`: compute the target with jq, compare with `jq -S` of the current files, return early when equal; otherwise `_dc_write "$dir" '.groups[$c] = {"requireMention": false, "allowFrom": (.allowFrom // [])}' --arg c "$id"` and write `bridge.json` via `.next` + `mv -f`, chmod 600. `_dc_bridge <dir> <project> start|stop|install`: outside tmux `BG` is unset, so set `BG="${project}-bg"` before calling `ensure_bg` (defined in `bin/tmux-ctl` before the discord dispatch). Start command for the window: `t new-window -d -t "=${BG}:" -n discord -c "$repo" "exec node $repo/tools/discord-bridge/bridge.js $dir"` where `repo` is `${0:A:h:h}` of tmux-ctl (use the existing repo-root variable in tmux-ctl if one exists). Liveness: `kill -0 $pid && ps -o command= -p $pid | grep -q bridge.js`. `_dc_status` gains the two lines after its existing lines.
- [ ] **Step 4: Run Verify; both files ALL PASS.**
- [ ] **Step 5: Commit** `feat(discord): channel, bridge and audit subcommands`.

```json:metadata
{"files": ["tools/lib/discord.zsh", "bin/tmux-ctl", "tools/tests/test_ctl_discord_channel.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_discord_channel.zsh && zsh tools/tests/test_ctl_discord.zsh", "acceptanceCriteria": ["channel writes groups and bridge.json, keeps other keys, 600", "identical channel is a byte-level no-op with unchanged mtime", "channel refuses with no allowFrom / bad id", "status channel and bridge lines (4 states)", "bridge start/stop/install behaviours on scratch tmux", "audit prints and filters", "usage lists new subs"], "modelTier": "standard"}
```

### Task 2: The node bridge

**Goal:** `tools/discord-bridge/` sends the outbox in order, keeps the pinned card and threads, writes `bridge-state.json`, filters components, and is fully tested with an injected fake client.

**Files:**
- Create: `tools/discord-bridge/package.json`, `tools/discord-bridge/package-lock.json`, `tools/discord-bridge/bridge.js`, `tools/discord-bridge/lib/outbox.js`, `tools/discord-bridge/lib/state.js`, `tools/discord-bridge/README.md`
- Create: `tools/discord-bridge/test/outbox.test.js`, `tools/discord-bridge/test/bridge.test.js`, `tools/discord-bridge/test/fake-client.js`
- Modify: `.gitignore` (add `tools/discord-bridge/node_modules/`)

**Acceptance Criteria:**
- [ ] `package.json` pins `discord.js` to an exact 14.x version, `"type": "commonjs"`, `"scripts": {"test": "node --test test/"}`; `package-lock.json` committed; `node_modules` ignored.
- [ ] `bridge.js` exports `createBridge({dir, client, log, now, sleep})` and runs `main()` only when executed directly; `main` reads the token from `<dir>/.env` `DISCORD_BOT_TOKEN=` line, writes `<dir>/bridge.pid`, removes it on SIGTERM/exit, logs to `<dir>/bridge.log`.
- [ ] Outbox: sends files in name order; deletes each only after the fake client resolves; a 4xx error moves the file to `outbox/failed/` with `<name>.err` holding the status and message; a 5xx/network error retries with backoff (injected `sleep`) and does not send later files first; an unparsable file goes to `failed/`.
- [ ] Card: first `card` op creates a message in the home channel, pins it, records `card_message_id`; later ops edit it; if the edit fails with Unknown Message (10008) it creates and pins a new one; two card ops within 30 s of injected time send one edit (the later text).
- [ ] Threads: `thread {key,title}` creates one public thread per key (second op with same key is a no-op), recorded in `threads`; `post` with `thread_key` posts in that thread; unknown key posts in the home channel with a `(thread <key> missing)` suffix; `archive` archives it.
- [ ] Posts: `mention_user: true` prefixes `<@user>` from `bridge.json` and sets `allowedMentions` to that user only; `false` sets `allowedMentions: {parse: []}`; `link_thread_key` appends `https://discord.com/channels/<guild>/<thread id>`; `files` attach.
- [ ] `bridge-state.json` is written via `.tmp` + rename with `connected` true on ready, false on disconnect, and `guild_id`.
- [ ] Interactions: a component whose `customId` starts with `ab:` is written to `<dir>/events/<ts>-<id>.json` as `{ts, user, custom_id, message_id, channel_id}` and acknowledged (`deferUpdate`); any other customId is ignored (no file, no reply); messages are ignored.
- [ ] Log hygiene test: after a run that posts a 200-character body with the token present in `.env`, `bridge.log` contains neither the token nor more than 80 characters of the body.

**Verify:** `cd tools/discord-bridge && npm ci --omit=dev && npm test`

**Steps:**

- [ ] **Step 1: Scaffold.** `npm init -y` in `tools/discord-bridge`, set fields above, `npm install --save-exact discord.js@14` (records the exact version; requires network), commit the lock. Add the `.gitignore` line.
- [ ] **Step 2: Write `test/fake-client.js`**: an EventEmitter with `channels.fetch(id)` returning a fake channel `{id, guildId, send(payload), messages: {fetch(id)}, threads: {create({name})}}`, fake messages with `edit`, `pin`, threads with `send`, `setArchived(true)`; each call is recorded in `calls[]`; failure injection by `failNext(method, {status, code})`.
- [ ] **Step 3: Write the failing tests** (one `test()` per acceptance bullet above) using a temp dir (`fs.mkdtempSync`). Mutations to name in each test comment: delete-before-send → "deleted only after success" fails; drop the `ab:` prefix check → "other customId ignored" fails; remove the 30 s throttle → "one edit" fails.
- [ ] **Step 4: Implement** `lib/outbox.js` (list/sort/read/move-to-failed), `lib/state.js` (atomic JSON write), `bridge.js` (`createBridge` with `tick()` processing the outbox, `onInteraction`, `onReady`/`onDisconnect`; `main` builds the real `Client` with the five intents from the Global Constraints and calls `tick` every 2 s). Log lines go through one `log(msg)` that truncates bodies to 80 characters and replaces the token string with `***`.
- [ ] **Step 5: Run Verify; all tests pass.** Write `README.md` (what it does, the spool contract pointing at the spec, `npm test`).
- [ ] **Step 6: Commit** `feat(discord): bridge program with outbox, card, threads`.

```json:metadata
{"files": ["tools/discord-bridge/package.json", "tools/discord-bridge/package-lock.json", "tools/discord-bridge/bridge.js", "tools/discord-bridge/lib/outbox.js", "tools/discord-bridge/lib/state.js", "tools/discord-bridge/README.md", "tools/discord-bridge/test/outbox.test.js", "tools/discord-bridge/test/bridge.test.js", "tools/discord-bridge/test/fake-client.js", ".gitignore"], "verifyCommand": "cd tools/discord-bridge && npm ci --omit=dev && npm test", "acceptanceCriteria": ["exact discord.js 14 pin, lock committed, node_modules ignored", "createBridge export and main token/pid/log", "outbox order, delete after success, 4xx failed/, 5xx retry in order, unparsable failed/", "card create/pin/edit/recreate and 30s throttle", "threads once per key, posts by key, archive", "mentions, deep links, files", "bridge-state atomic with connected and guild_id", "ab: interactions to events/, others ignored", "log never holds token or >80 chars of body"], "modelTier": "standard"}
```

### Task 3: Feed core: paths, outbox writer, feed file, card

**Goal:** `board/discord_feed.py` has the spool writer with the 200 cap, the feed-event file reader/writer, the card renderer and its throttle, and `tc_env` has the base/dir helpers.

**Files:**
- Modify: `board/tc_env.py` (add `agent_base()`, `discord_dir(project)`, `feed_path(project)`)
- Create: `board/discord_feed.py`
- Create: `board/tests/test_discord_feed.py`

**Acceptance Criteria:**
- [ ] `tc_env.agent_base()` is `$TC_STATE` when set, else `~/.local/state/agent-board`; `discord_dir(p)` = `<base>/discord/<p>`; `feed_path(p)` = `<base>/feed/<p>.jsonl`.
- [ ] `outbox_write(dir, op)` validates the op shape from Global Constraints (raises `ValueError` on unknown op/keys or a `routine` tier post), writes `<13-digit ms>-<8 hex>.json` via `.tmp` + `os.replace`, names sort in write order within one process even in the same millisecond, and enforces the 200 cap (oldest card ops dropped first, then oldest non-mention ops; mention posts never dropped). Tests: 205 writes mixing kinds → 200 files, all mention posts present.
- [ ] `append_event(project, ev)` appends one JSON line with exactly the spec §11 keys (missing `refs` → `{}`); `read_events(project, offset)` returns `(events, new_offset)` and skips a torn last line until it is complete.
- [ ] `render_card(record, lead_tasks, now)` returns the card text per Global Constraints from fixture overview records (`overview.record` shape: `plan`, `needs_you`, `agents`) and raw lead task dicts; tests: queue running (k/n) / paused / idle, task marks and owner/tier, teammates busy/idle, needs-you lines, `updated HH:MM`, a 60-task plan cut to ≤ 1900 characters ending `… <n> more`.
- [ ] `card_op_due(state, text, now)` returns an op only when text differs from `state["card_text"]` and `now - state["card_ts"] >= 30`; tests at 29 s and 30 s (boundary), unchanged text at 300 s.
- [ ] `audit_append(dir, user, action, target, result)` appends `{ts, user, action, target, result}` with `target` truncated to 80 characters.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_feed.py'`

**Steps:**

- [ ] **Step 1: Write the failing tests** in `board/tests/test_discord_feed.py` (a `TC_STATE` temp dir per test via `unittest.mock.patch.dict(os.environ, …)`; fixtures from a real overview record shape: build them by calling `overview.record` if it is pure, else copy the key set from `board/overview.py` `RECORD_KEYS`). Mutation per guard: remove the mention-post exemption → "all mention posts present" fails; remove the 30 s check → the 29 s test fails.
- [ ] **Step 2: Run, see them fail** on `ModuleNotFoundError: discord_feed`.
- [ ] **Step 3: Implement** the helpers in `board/tc_env.py` and the functions above in `board/discord_feed.py` (pure functions plus file I/O; no tmux, no network). Keep imports lazy so `python3 -I` works like the other board modules.
- [ ] **Step 4: Run Verify.**
- [ ] **Step 5: Commit** `feat(board): discord feed spool, feed file and status card`.

```json:metadata
{"files": ["board/tc_env.py", "board/discord_feed.py", "board/tests/test_discord_feed.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_feed.py'", "acceptanceCriteria": ["tc_env base/dir/feed paths", "outbox_write validation, atomic names in order, 200 cap rules", "append_event/read_events with torn-line safety", "render_card content and 1900 cap", "card_op_due change-only and 30s boundary", "audit_append shape and truncation"], "modelTier": "standard"}
```

### Task 4: Feed derivation: spec threads, task lines, reviews, outcomes

**Goal:** `discord_feed.derive(...)` turns the lead's task list, the plan tasks and the ledger into feed events once each (deduped across restarts), and `ops_for_events(...)` turns feed events into outbox ops by tier.

**Files:**
- Modify: `board/discord_feed.py`
- Modify: `board/planview.py` (add `raw_live_tasks(home, sid, pid, started)` returning the unnormalised task dicts from the same directory `live_tasks` resolves; `live_tasks` unchanged)
- Modify: `board/tests/test_discord_feed.py`
- Create: `board/tests/fixtures/discord_feed/` (task dirs and ledgers)

**Acceptance Criteria:**
- [ ] Triggers (spec §5): a `Plan & run:` task newly `in_progress` → `spec_started` with `refs.thread_key` = task id and a `thread` op titled with the spec basename (`#part-N` kept); `metadata.plan` present and the file exists under the repo root or a `.claude/worktrees/*/` checkout → one `plan_written: <n> tasks` (n = `### Task ` headings); a non-`Plan & run:` task newly `completed` while a `Plan & run:` is in progress → `task_done` `✓ <subject>`; a new ledger line matching ruling P5's regex in `<root>/.claude/worktrees/*/.superpowers/sdd/<plan basename>/progress.md` or `<root>/.superpowers/sdd/<plan basename>/progress.md` → `review: <line>` (≤ 300 chars); the `Plan & run:` task `completed` → `spec_outcome` with `metadata.outcome`, then an `archive` op; a new `docs/superpowers/reports/*-queue.md` → `report_written` one-line summary to the home channel.
- [ ] Dedupe: every emitted event has a key stored in `<dir>/feed-state.json` (`seen` list capped at 2000, oldest dropped); a second `derive` over the same inputs emits nothing; a fresh process reading the same `feed-state.json` emits nothing (restart test).
- [ ] Delivery: events from an out-of-order poll (a task seen `completed` before ever seen `in_progress`) still emit `task_done` once; repeated polls emit nothing; two concurrent ticks are prevented by an `fcntl.flock` on `<dir>/feed-state.lock` (test: a held lock makes `tick` return without writing).
- [ ] `ops_for_events(events, state)` follows the tier table in Global Constraints: progress → `post` with `thread_key`; critical/decision → home `post` with `mention_user: true` and `link_thread_key` of the running spec; routine → no op (card only); `spec_outcome` with `failed — …` → critical with mention.
- [ ] Fixtures are copies of real shapes: one real lead task JSON (`Plan & run:` with `metadata.queue`), one real plan task JSON with a `json:metadata` fence, and verbatim real ledger lines from `docs/superpowers/ledgers/2026-11-16-execution-analytics-part-1/progress.md` and `docs/superpowers/ledgers/2026-11-16-discord-replaces-telegram/progress.md`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_feed.py' && python3 -m unittest discover -s board/tests -p 'test_planview*.py'`

**Steps:**

- [ ] **Step 1: Copy fixtures** from real files (task JSON from `~/.claude/tasks/<this lead's dir>/`: anonymise nothing but session ids; ledger lines verbatim).
- [ ] **Step 2: Write failing tests**, one per acceptance bullet; the dedupe-restart test creates two `derive` calls with a fresh module state in between (re-import or pass state explicitly). Mutation: skip saving `seen` → restart test fails.
- [ ] **Step 3: Implement** `derive(project, root, lead_tasks, state, now)` → `(events, state)`, `ops_for_events`, and `tick(project, record, root, home, now)` which: locks, loads state, derives, appends events to the feed file, reads new feed events since `state["feed_offset"]` (so events appended by others, e.g. the notifier sink or PCEE later, flow through the same path), writes ops via `outbox_write`, writes the card op when due, saves state.
- [ ] **Step 4: Run Verify.**
- [ ] **Step 5: Commit** `feat(board): discord feed derives spec threads, task lines, reviews`.

```json:metadata
{"files": ["board/discord_feed.py", "board/planview.py", "board/tests/test_discord_feed.py", "board/tests/fixtures/discord_feed/"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_feed.py' && python3 -m unittest discover -s board/tests -p 'test_planview*.py'", "acceptanceCriteria": ["six triggers emit the right events/ops", "dedupe across polls and restart via feed-state.json", "out-of-order, repeat and concurrent tick semantics", "ops_for_events tier routing", "fixtures copied from real task JSON and ledger lines"], "modelTier": "standard"}
```

### Task 5: Board wiring: alert sink, bridge keeper, feed tick, events stub

**Goal:** The board's poll loop runs the feed tick and keeps bridges running, and the notifier writes tiered alerts into the feed.

**Files:**
- Modify: `board/notify.py`
- Modify: `board/server.py` (next to `ensure_overseer`, `overview_payload`)
- Modify: `board/discord_feed.py` (`read_inbound(dir)` stub)
- Modify: `board/tests/test_notify.py`
- Create: `board/tests/test_discord_wiring.py`

**Acceptance Criteria:**
- [ ] `Notifier` gains a `sinks` list (default: `[discord_sink]` unless `TC_DISCORD_ALERTS=0`); `TC_NOTIFY=0` disables only the banner, events and the discord sink still run; same latch and `RATE_S` as banners (one test per: first overview seeds without sending, rate limit holds a second event of the same kind, `TC_DISCORD_ALERTS=0` sends nothing, `TC_NOTIFY=0` still sends to discord).
- [ ] `discord_sink(ev)` appends a feed event (kind = notify kind, tier per Global Constraints, `refs.thread_key` = the project's running spec thread key from feed-state when known) only when the project's `<dir>/bridge.json` has a channel; it never raises (errors logged as `notify: discord sink failed: …`).
- [ ] `ensure_discord_bridges(records)` runs `tmux-ctl discord bridge start --project <p>` for each project with a token file and a `bridge.json` channel, at most once per 60 s per project, never when `TC_DISCORD_BRIDGE=0`, outside the overview lock (like `ensure_overseer`); tested with a fake runner and clock.
- [ ] `overview_payload()` calls, after `ensure_overseer()`, `ensure_discord_bridges` and `discord_feed.tick` for each record with a configured channel; a feed exception is caught and logged, never breaking the overview.
- [ ] `read_inbound(dir)` reads `<dir>/events/*.json` in name order, appends one audit line per event with `result: "ignored"` (unknown/unauthorized users per `access.json` `allowFrom` get `result: "rejected"`), deletes each after logging.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_notify.py' && python3 -m unittest discover -s board/tests -p 'test_discord_wiring.py' && python3 -m unittest discover -s board/tests -p 'test_server*.py'`

**Steps:**

- [ ] **Step 1: Write failing tests** (fake runner records argv; `TC_STATE` temp dir with `discord/p/.env`, `bridge.json`). Mutations: remove the 60 s gate → "once per 60 s" fails; let `TC_NOTIFY=0` return early → "still sends to discord" fails.
- [ ] **Step 2: Implement** in `notify.py` (restructure `observe`: compute events, record them, `if self.enabled: banner`, then each sink in a try/except), `server.py` (`ensure_discord_bridges` shaped like `ensure_overseer` at :435: module-level `_discord_checked = {}` and `DISCORD_RECHECK_S = 60`, `run_script([str(BIN / "tmux-ctl"), "discord", "bridge", "start", "--project", p], timeout=20)`), `discord_feed.read_inbound`.
- [ ] **Step 3: Run Verify, then the whole board suite** `python3 -m unittest discover -s board/tests`.
- [ ] **Step 4: Commit** `feat(board): discord alert sink, bridge keeper and feed tick`.

```json:metadata
{"files": ["board/notify.py", "board/server.py", "board/discord_feed.py", "board/tests/test_notify.py", "board/tests/test_discord_wiring.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_notify.py' && python3 -m unittest discover -s board/tests -p 'test_discord_wiring.py' && python3 -m unittest discover -s board/tests -p 'test_server*.py'", "acceptanceCriteria": ["Notifier sinks with seed, rate limit, TC_DISCORD_ALERTS, TC_NOTIFY split", "discord_sink tier, thread ref, only with channel, never raises", "ensure_discord_bridges gating and 60s rate", "overview_payload wiring isolates feed errors", "read_inbound audits ignored/rejected and deletes"], "modelTier": "standard"}
```

### Task 6: Docs, lead rules and install step

**Goal:** The lead rule, install script and docs describe the bridge; the lead sets `metadata.plan`.

**Files:**
- Modify: `claude/orchestrator.md` (§ Remote: Discord, lines ~241-283; Queue mode step 2, line ~79)
- Modify: `install.sh`
- Modify: `docs/INSTALL.md` (§ Remote access, ~185-243)
- Modify: `docs/ARCHITECTURE.md` (new `## Feed events` section before `## State files`; add the new state files to `## State files`)

**Acceptance Criteria:**
- [ ] `claude/orchestrator.md` § Remote: Discord gains, as its first bullet under "While remote:", exactly: `- The conversation lives in the project's home channel. Do not post status, progress or alerts yourself: the bridge posts the status card, the spec threads and the alerts. Reply to what the user wrote.` Queue mode step 2 gains, after "`superpowers-extended-cc:writing-plans`,": ` then set the task's `metadata.plan` to the plan path (TaskUpdate),`. Applied as a generated patch that passed `patch --dry-run`.
- [ ] `install.sh` gains, after `check_deps`, a step that runs `npm ci --omit=dev` in `tools/discord-bridge` when `command -v npm` succeeds, and prints `skip discord bridge deps (npm missing)` otherwise; `check_deps` reports node as optional (`ok <path>` / `optional: node missing`).
- [ ] `docs/INSTALL.md` lists the eight channel permissions from spec §2 verbatim, `tmux-ctl discord channel <id>`, `tmux-ctl discord bridge install|start|stop`, the two new `status` lines and the kill switches `TC_DISCORD_BRIDGE=0`, `TC_DISCORD_ALERTS=0`.
- [ ] `docs/ARCHITECTURE.md` `## Feed events` documents the feed file path, the spec §11 schema with every key, the kinds and tiers table, and that PCEE appends to the same file.

**Verify:** `grep -c 'The conversation lives in the project' claude/orchestrator.md && grep -c 'metadata.plan' claude/orchestrator.md && grep -c '^## Feed events' docs/ARCHITECTURE.md && grep -c 'Create Public Threads' docs/INSTALL.md && zsh -n install.sh`

**Steps:**

- [ ] **Step 1:** Copy `claude/orchestrator.md` to a scratch file, edit the copy with the two insertions above, `diff -u live copy > p.diff`, `patch --dry-run claude/orchestrator.md < p.diff`, then apply.
- [ ] **Step 2:** Edit `install.sh` (check whether it is bash or zsh from its shebang and use `bash -n`/`zsh -n` accordingly in Verify output), `docs/INSTALL.md`, `docs/ARCHITECTURE.md`.
- [ ] **Step 3:** Run Verify: every grep prints ≥ 1 and the syntax check exits 0.
- [ ] **Step 4: Commit** `docs(discord): bridge setup, feed events, lead rule`.

```json:metadata
{"files": ["claude/orchestrator.md", "install.sh", "docs/INSTALL.md", "docs/ARCHITECTURE.md"], "verifyCommand": "grep -c 'The conversation lives in the project' claude/orchestrator.md && grep -c 'metadata.plan' claude/orchestrator.md && grep -c '^## Feed events' docs/ARCHITECTURE.md && grep -c 'Create Public Threads' docs/INSTALL.md && zsh -n install.sh", "acceptanceCriteria": ["orchestrator Remote: Discord bullet and metadata.plan rule via dry-run-checked patch", "install.sh npm ci step and optional node check", "INSTALL.md permissions, commands, status lines, kill switches", "ARCHITECTURE.md Feed events section with schema, kinds/tiers, PCEE note"], "modelTier": "mechanical"}
```

### Task 7: Real-state end-to-end (scratch outputs)

**Goal:** Every piece runs once against the user's real long-lived state, writing only to scratch, and the results are recorded in a note.

**Files:**
- Create: `docs/superpowers/notes/2026-11-16-discord-bridge-visibility-e2e.md`

**Acceptance Criteria:**
- [ ] `tmux-ctl discord channel 1570102051466125332 --project agent-board` against a scratch `TC_STATE` holding a copy of the real `discord/agent-board/` dir (without `.env`) prints `channel: … (unchanged)` and both files' checksums are identical before/after (the real dir already holds the hand-written entries).
- [ ] `discord_feed.tick` run read-only against the real `agent-board` overview record, the real lead task list and the real ledgers (archived ledgers count as real state spanning several days) with a scratch `TC_STATE`: the note pastes the rendered card, the count of outbox ops by op/tier, and the first 10 feed events; a second tick writes 0 new ops (dedupe on real data).
- [ ] The node bridge with the fake client processes that scratch outbox: all files sent in order, 0 in `failed/` (or each failure explained), `bridge.log` grep count of the token = 0 (token taken from a scratch fake `.env`).
- [ ] The real `~/.local/state/agent-board/discord/agent-board/` and `feed/` dirs are untouched: a checksum listing (`find … -type f -exec md5 -q {} +`, with the file count printed) before and after is identical.

**Verify:** `test -s docs/superpowers/notes/2026-11-16-discord-bridge-visibility-e2e.md && grep -c 'unchanged' docs/superpowers/notes/2026-11-16-discord-bridge-visibility-e2e.md`

**Steps:**

- [ ] **Step 1:** Record the before-checksums of the real dirs (count printed).
- [ ] **Step 2:** Run the three checks above with scratch `TC_STATE` (a dry harness script in the scratchpad that imports `board/discord_feed.py` and `board/overview.py`; never the live board on :7700).
- [ ] **Step 3:** Record the after-checksums; write the note with each output pasted (fences: use ```` for any block that contains ```).
- [ ] **Step 4: Commit** `docs(notes): discord bridge visibility real-state e2e`.

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-16-discord-bridge-visibility-e2e.md"], "verifyCommand": "test -s docs/superpowers/notes/2026-11-16-discord-bridge-visibility-e2e.md && grep -c 'unchanged' docs/superpowers/notes/2026-11-16-discord-bridge-visibility-e2e.md", "acceptanceCriteria": ["channel no-op on a copy of the real dir", "feed tick on real task list and ledgers, second tick 0 ops", "bridge with fake client drains the scratch outbox, token count 0", "real discord and feed dirs unchanged by checksum with file count"], "modelTier": "standard"}
```

### Task 8: User gate: one real run with the agent-board bot

**Goal:** The user sees the card, a spec thread with task lines, and a needs-you ping in the real `#agent-board` channel.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none

**Acceptance Criteria:**
- [ ] After merge, `tmux-ctl discord bridge install` and `tmux-ctl discord status --project agent-board` show `channel: 1570102051466125332` and `bridge: running (pid N)`.
- [ ] The user confirms in Discord: the pinned card updates, the next spec's thread shows task lines, and a needs-you alert @mentions them.

**Verify:** see verifyCommand (expects `bridge: running`), plus the user's Discord confirmation.

```json:metadata
{"files": [], "verifyCommand": "tmux-ctl discord status --project agent-board", "acceptanceCriteria": ["status shows channel and bridge running", "user confirms card, thread lines and needs-you ping"], "modelTier": "mechanical", "userGate": true, "tags": ["user-gate"]}
```
