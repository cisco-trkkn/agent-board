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
- `post` `files` (absolute paths): at most 10 per post and 25 MB each. A missing file is dropped and the text gains
  `<name> not found`; a bigger one gains `<name> too large (<size>)`; beyond 10, `<k> more files not sent (10 max)`
  (the post still goes). `delete_files: true` unlinks, after a successful send only, each listed file that resolves
  inside `<dir>/tmp/`; any other path is kept and logged. A failed send keeps the files.
- Writes `<dir>/bridge-state.json` atomically (`card_message_id`, `threads`, `guild_id`, `connected`, `ts`).
- Ops added for the controls: `prompt` `{key, window, tool, lines, mention_user}` posts
  `<@user> 🔐 <window> wants to run <tool>` with the lines in a code block and `Allow once` / `Deny` buttons
  (`ab:perm:<key>:allow|deny`; over 1500 characters the text is cut and only `Deny` stays) and keeps
  `bridge-state.json` `prompts[key] = message id` (newest 200). `edit` `{key, text}` rewrites that post and
  removes its buttons; an unknown key or a deleted message is dropped with a log line, not failed.
- `dialog` `{key, text, rows, mention_user}` posts `text` (with `<@user> ` in front when `mention_user`) with up to 5 rows
  of up to 5 buttons `{label, style, custom_id}` to the home channel (ops mode: `#approvals`) and keeps
  `bridge-state.json` `dialogs[key] = message id` (newest 200). `edit` also finds a `dialogs` key; with `rows` it sets
  those buttons, without it removes them.
- Dialog ids, key `p<digits>-<16 hex>`: `ab:dlg:<key>:<n>` (an option), `…:<n>:confirm|cancel`, `…:t<n>` (toggle),
  `…:submit`, `…:reply`. A click on an option whose style is 4 (a permanent choice) gets an ephemeral
  `this allows <label> from now on` with `Confirm` / `Cancel` and writes no event; `Confirm` becomes `Sent.` and writes
  the click event, `Cancel` becomes `Cancelled.`. A toggle flips that button between styles 2 and 3 in place and
  writes nothing; `submit` writes a click event with `picks` (numbers of the style-3 toggles, ascending). `reply` answers
  `Reply to that message with your answer.` and arms the message (`reply_armed[message id] = key`); the next message
  from an allowlisted user that replies to it writes `{type:"reply", key, text, user, message_id, ts}` (text trimmed,
  at most 1000 characters, `message_id` = the dialog message) and disarms it. `ab:dlg:` and `ab:gate:` clicks are
  events in project and in ops mode; this needs the `MessageContent` intent: every bot whose bridge runs (project and
  ops) must have **Message Content Intent** switched on in the Developer Portal, and a bot without it exits at login.
- Turns component clicks whose `customId` starts with `ab:` into `<dir>/events/<ts>-<id>.json`. The user must be in
  `<dir>/access.json` `allowFrom` (re-read on every click; missing file = nobody); otherwise the reply is an
  ephemeral `Not authorized.` and nothing is written. Allowed clicks are deferred first, then written:
  `{type:"perm", key, choice, user, message_id, ts}` for `ab:perm:`, else
  `{type:"click", custom_id, user, message_id, channel_id, ts}`. Other components are ignored.
- Reactions (`messageReactionAdd`, partials enabled) from an allowlisted non-bot user on a bot message in the home
  channel or one of its threads, with `✅ ❌ 🛑 ▶️ ⏭️`, write `{type:"react", emoji, message_id, excerpt, user, ts}`
  (excerpt = first 80 characters) and the bot adds 👀 once. Messages are ignored except replies to an armed dialog.
- Token comes only from `<dir>/.env` (`DISCORD_BOT_TOKEN=`). The log (`<dir>/bridge.log`) never holds it
  nor more than 80 characters of a message body. `<dir>/bridge.pid` exists while it runs; SIGTERM exits.

`<dir>/bridge.json` holds `{"channel": "<id>", "user": "<id>"}`. The spool contract (op shapes, paths)
is in `docs/superpowers/specs/2026-11-11-discord-bridge-visibility-design.md`.

## Tests

    npm ci --omit=dev   # installs discord.js
    npm test            # node --test, injected fake client, no network, no token

Tests inject `test/fake-client.js` through `createBridge({client})`.
