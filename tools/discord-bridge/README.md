# discord-bridge

Node program that connects one project's Discord bot to the Agent Board. It runs as
`node tools/discord-bridge/bridge.js <dir>`, where `<dir>` is `<base>/discord/<project>`
(started by `tmux-ctl discord bridge start`).

What it does:

- Sends `<dir>/outbox/<ts>-<id>.json` files in name order and deletes each only after Discord accepted it.
  4xx errors move the file to `outbox/failed/` with a `<name>.err`; 5xx and network errors retry with
  backoff (1 s doubling to 60 s) without sending later files first.
- Keeps the pinned status card (`card` op, at most one edit per 30 s), one public thread per key
  (`thread`, `archive`), and posts (`post`, with optional mention, deep link and files).
- Writes `<dir>/bridge-state.json` atomically (`card_message_id`, `threads`, `guild_id`, `connected`, `ts`).
- Turns component clicks whose `customId` starts with `ab:` into `<dir>/events/<ts>-<id>.json` and
  acknowledges them. Every other component and every message is ignored.
- Token comes only from `<dir>/.env` (`DISCORD_BOT_TOKEN=`). The log (`<dir>/bridge.log`) never holds it
  nor more than 80 characters of a message body. `<dir>/bridge.pid` exists while it runs; SIGTERM exits.

`<dir>/bridge.json` holds `{"channel": "<id>", "user": "<id>"}`. The spool contract (op shapes, paths)
is in `docs/superpowers/specs/2026-11-11-discord-bridge-visibility-design.md`.

## Tests

    npm ci --omit=dev   # installs discord.js
    npm test            # node --test, injected fake client, no network, no token

Tests inject `test/fake-client.js` through `createBridge({client})`.
