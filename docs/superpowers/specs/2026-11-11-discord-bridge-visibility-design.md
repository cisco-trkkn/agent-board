# Discord bridge and project channel: status card, spec threads, alerts

Date: 2026-11-11 · Decided with the user over Discord, 2026-11-11 (ideas 2, 3, 4, 5 of the Discord round)
Needs merged: `docs/superpowers/specs/2026-11-11-discord-replaces-telegram-design.md` (per-project bot, state dir
`<dir>` = `${TC_STATE:-~/.local/state/agent-board}/discord/<project>`, `tmux-ctl discord …`, `lib/discord.zsh`).
Supersedes: `docs/superpowers/specs/2026-11-11-discord-tasks-design.md` (the status card replaces `/tasks`; never run).
Followed by: `2026-11-11-discord-controls-design.md` (buttons, reactions) and `2026-11-11-discord-files-design.md`.

## Problem

The Discord plugin gives only the lead tools (reply, react, edit, fetch, download). Everything the user wants to see
from the phone without asking (queue progress, who is waiting, failures) would cost the lead's tokens and stop while
the lead is busy. The plugin also ignores everything but messages and its own permission buttons.

## Decisions (user, 2026-11-11)

- **A bridge program per project** next to the plugin, same bot token. It posts and listens for our own components;
  the lead keeps the conversation through the plugin.
- **One bot per project**, each with a **home channel** in the user's private server. With one shared token, every
  lead's plugin would receive every button click and could answer the wrong one.
- **Everything happens in the project channel**: chat with the lead (no @mention), a pinned status card, a thread per
  spec, alerts. Anything that needs the user @mentions them; routine posts do not.
- Status and alerts are **pushed** (this reverses the 2026-11-10 "on demand only" decision, by the user).

## Design

### 1. Split of work

- **Board (python) decides what to post.** It already has the data: task lists (`board/taskwin_state.py`), events
  (`board/notify.py` `conditions` / `Notifier`), metrics. New module `board/discord_feed.py`.
- **Bridge (node) does Discord I/O only.** New `tools/discord-bridge/` (`package.json` pinning `discord.js` 14,
  `bridge.js`, `README.md`). It knows nothing about tasks.
- **Interface: a spool per project**, files only, so each side is tested alone:
  - `<dir>/outbox/<ts>-<id>.json`, written by the board through `.tmp` + rename; the bridge sends each in name order
    and deletes it after Discord accepts it (on a 4xx it moves it to `outbox/failed/` with the error in
    `<name>.err`; on 5xx or network errors it retries with backoff and keeps order).
  - `<dir>/bridge-state.json`, written only by the bridge: `{"card_message_id", "threads": {"<key>": "<thread id>"},
    "connected": bool, "ts"}`.
  - `<dir>/events/<ts>-<id>.json`, written by the bridge for inbound events the board must act on (used by the
    controls spec; this spec creates the directory and the reader stub).
- Outbox operations (JSON `{"op": …}`): `post {channel|thread_key, text, mention_user: bool, files?: [abs paths]}`,
  `card {text}` (create-or-edit the pinned card), `thread {key, title}` (create a public thread under the home
  channel once per key; later posts address it by key), `archive {key}`.

### 2. Configuration

- `tmux-ctl discord channel <channel id>` sets the home channel: in `<dir>/access.json`
  `groups[<id>] = {"requireMention": false, "allowFrom": [<every allowFrom id>]}` (the plugin then delivers channel
  messages to the lead without a mention) and `<dir>/bridge.json` `{"channel": "<id>", "user": "<first allowFrom id>"}`.
  `status` gains `channel: <id>|none` and `bridge: running (pid N)|stopped|no channel`.
- The bot needs, in that channel: View, Send Messages, Send Messages in Threads, Create Public Threads, Manage Messages
  (pin), Read Message History, Add Reactions, Attach Files. `docs/INSTALL.md` lists them; `status` cannot check them.
- DMs keep working as before (`dmPolicy` unchanged).

### 3. Bridge lifecycle

- The board's poll loop gets `ensure_discord_bridges()`, shaped like `ensure_overseer()` (`board/server.py:424`): for
  each project with a token and a `bridge.json` channel, start `node tools/discord-bridge/bridge.js <dir>` in the
  project's `-bg` session window `discord` through `tmux-ctl` when no live bridge holds `<dir>/bridge.pid`; at most one
  check per 60 s per project. `TC_DISCORD_BRIDGE=0` turns it off.
- Dependencies: `tools/discord-bridge/node_modules` installed by `install.sh` (`npm ci --omit=dev`) and by
  `tmux-ctl discord bridge install`; missing → `status` says `bridge: deps missing`, the board does not start it.
- The bridge reads the token from `<dir>/.env` itself (never from argv or env passed by the board), logs to
  `<dir>/bridge.log` (no token, no message bodies beyond 80 characters), exits on SIGTERM.
- Gateway intents: Guilds, GuildMessages, GuildMessageReactions, DirectMessages, DirectMessageReactions. It ignores
  every message (the plugin owns conversation) and every component whose `customId` does not start with `ab:`.

### 4. Status card

- One message in the home channel, pinned on creation, edited in place. `board/discord_feed.py` renders it from the
  project's overview record and task lists; it writes a `card` op only when the text changed and at most every 30 s.
- Content (plain text in one code block, ≤ 1900 characters, cut with `… <n> more`):
  - queue line: `queue: running <spec title> (k/n)` / `paused` / `idle`;
  - the running plan's tasks: `✓`/`▶`/`·` + subject, owner, tier;
  - teammates: name, busy/idle;
  - `waiting on you:` lines for every needs-you pane (window name), else none;
  - `updated HH:MM`.
- If the card message was deleted, the bridge creates and pins a new one and records its id.

### 5. A thread per spec

`board/discord_feed.py` follows the lead's task list for `Plan & run:` tasks and the plan's tasks:

| Trigger | Op |
| --- | --- |
| a `Plan & run:` task goes `in_progress` | `thread {key: <task id>, title: <spec basename>}` |
| the plan file appears (`docs/superpowers/plans/…` named in the task's metadata or the ledger) | post `plan written: <n> tasks` |
| a plan task completes | post `✓ <subject>` |
| a review verdict line lands in the ledger | post `review: <verdict>` |
| the `Plan & run:` task completes | post `metadata.outcome`; `failed — …` sets `mention_user: true`; then `archive` |
| the morning report is written | post it to the channel as a file (with the files spec) plus a one-line summary |

Keys are deduplicated in `<dir>/feed-state.json` (board-owned), so a board restart does not repost.

### 6. Alerts

`Notifier` gets a second sink next to the macOS banner: `discord_sink(event)` writes a `post` op to the event's
project when that project has a bridge channel. Same latch and rate limits as banners (`RATE_S`). `needs_you`,
`test_failed`, `failing` and `stuck` set `mention_user: true`; `plan_done`, `lead_idle`, `context`, `usage` do not.
`TC_DISCORD_ALERTS=0` turns only this sink off.

### 7. Lead rules

`claude/orchestrator.md` § Remote: Discord: the lead's conversation is in the project channel; do not post status,
progress or alerts yourself (the bridge does); reply to what the user wrote. Apply as a dry-run-checked patch.

## Error handling

- Bridge down or not configured: the board keeps writing the outbox, capped at 200 files per project (oldest card ops
  dropped first, never `post`s with `mention_user`); `status` shows the backlog.
- Discord rate limits: discord.js queues; the bridge never sends more than one card edit per 30 s.
- A spool file that does not parse goes to `outbox/failed/`.

## Testing

- `board/tests/test_discord_feed.py`: card rendering from fixture overviews (length cap, needs-you lines), change-only
  and 30 s throttle, thread triggers from a fixture task dir across two polls, dedupe across a restart, alert sink
  mention rules and rate limit, outbox atomic writes and the 200 cap.
- `tools/discord-bridge/test/`: `node --test` with a fake discord.js client injected: outbox order, deletion only after
  success, 4xx → failed/, retry on 5xx, card create/pin/edit/recreate, thread create once per key, `ab:` filter,
  token never in the log.
- `tools/tests/test_ctl_discord_channel.zsh`: `channel` writes `groups` and `bridge.json`, keeps other keys.
- One real run (user gate): with the agent-board bot, set the channel, start a small plan; the card updates, a thread
  appears with task lines, a needs-you pings the user.

## Out of scope

- Buttons and reactions (controls spec), files (files spec), voice.
- A shared bot across projects.
