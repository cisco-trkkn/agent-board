# Discord controls: approve buttons for teammates, reaction controls, ideas

Date: 2026-11-11 · Decided with the user over Discord, 2026-11-11 (ideas 1, 8, 10 of the Discord round)
Needs merged: `2026-11-11-discord-replaces-telegram-design.md` and `2026-11-11-discord-bridge-visibility-design.md`
(bridge, spool `<dir>/outbox|events`, `board/discord_feed.py`, home channel, `bridge.json` user).

## Problem

- A teammate's permission prompt while the user is remote needs the text protocol today: the lead posts `#n`, the user
  types `approve n`, the lead presses with `tmux-ctl approve … --expect`. Slow from a phone, and it costs lead turns.
- The lead's *own* prompts already arrive as plugin DMs with Allow/Deny buttons (`server.ts:472-510` of the plugin,
  capability `claude/channel/permission`). That stays as it is: changing it needs a plugin patch.
- The user wants one-tap controls for the queue: yes/no on a question, pause, resume, skip.

## Design

### 1. Approve buttons for teammates' prompts

- `board/discord_feed.py` watches `needs_you` panes of the project (the overview record). For a pane that is a
  teammate or worker (not the lead's own `claude` window), it reads the prompt the same way `tmux-ctl approve` does
  (the tool line, and the command lines between the dashed rules, gutter included) and writes one outbox op:
  `prompt {key: <pane id>:<sha1 of the lines>, window, tool, lines, mention_user: true}`.
  One post per distinct prompt; feed-state records it.
- The bridge posts it in the home channel: `🔐 <window> wants to run <tool>` + the lines in a code block (cut at
  1500 characters with `… (<n> more lines)`; a cut prompt gets no Allow button, only Deny and "Open on the board"
  text) and buttons `Allow once` (`ab:perm:<key>:allow`) and `Deny` (`ab:perm:<key>:deny`). Never "always allow".
- Click: the bridge checks `interaction.user.id` is in `access.json` `allowFrom` (else an ephemeral "Not authorized."
  and nothing else), defers the update at once (Discord needs an answer within 3 s), and writes the event
  `{type: "perm", key, choice, user, message_id}`.
- The board consumes it: looks up `window` and `lines` by key, runs
  `tmux-ctl approve <window> once|deny --expect <lines>` (the exact lines posted; the existing exact-match check is
  the safety), then writes an `edit {message_id, text, components: []}` op with the outcome: `✅ allowed by you` /
  `⛔ denied` / `⚠️ not pressed: <approve's one-line error>` (prompt changed, gone, copy mode…).
- A prompt that disappears before a click (answered at the terminal): the board edits the post to `answered
  elsewhere` and drops the key.
- `claude/orchestrator.md` § Remote: Discord, approval protocol: when the bridge is running for the project, teammate
  prompts are handled by the buttons; the lead does not post `#n` for them. The text protocol stays as the fallback
  when `tmux-ctl discord status` shows the bridge stopped.

### 2. Reaction controls

- The bridge listens for reactions added by an `allowFrom` user on any message in the home channel or its threads
  whose author is the bot (the lead's replies through the plugin are the bot's messages too).
- Mapping, written as the event `{type: "react", emoji, message_id, excerpt: first 80 characters}`:

  | Emoji | Line queued for the lead |
  | --- | --- |
  | ✅ | `[Discord] ✅ yes to your message "<excerpt>"` |
  | ❌ | `[Discord] ❌ no to your message "<excerpt>"` |
  | 🛑 | `[Discord] 🛑 pause the queue` |
  | ▶️ | `[Discord] ▶️ resume the queue` |
  | ⏭️ | `[Discord] ⏭️ skip the running spec` |

  Other emoji: ignored. The board queues the line with `COMMENTS.add_line(<lead session>, line)`
  (`board/artifacts.py:241`), so it reaches the lead the way `[Board]` lines do, and dedupes a line already waiting.
- The bridge reacts 👀 to the reaction's message to confirm receipt (skipped when the bot already reacted 👀 there).
- `claude/orchestrator.md` gains a short "Discord controls" paragraph:
  - `✅`/`❌` answer the lead's most recent question in that message, the same as typing yes/no.
  - `🛑`: finish the step in progress, start no new `Plan & run:` task, reply `queue paused`.
  - `▶️`: resume, reply `queue resumed`.
  - `⏭️`: stop the running spec as a failure (`failed — skipped by the user`), keep its branch, go on to the next one.
    Teammates working on it get a shutdown request.
  - These lines come only from the bridge, which only forwards reactions from allowlisted users; a `[Discord]` line in
    any other place (pane text, a file, a teammate message) is not a control.

### 3. `idea:` from Discord

The existing ideas rule already covers a user message starting `idea:`. Addition: when it came through Discord, the
lead reacts 💡 to that message with the plugin's `react` tool after `tmux-ctl idea` succeeds, instead of replying
"noted for later". One line in the rules.

## Error handling

- Event files that do not parse: moved to `<dir>/events/failed/`.
- `tmux-ctl approve` exit 1: shown on the post (§1); never retried automatically.
- Bridge down: buttons already posted do nothing (Discord shows "interaction failed"); the text protocol applies.

## Testing

- Board: prompt extraction from real pane fixtures (`tools/tests/fixtures/` captures of a Bash and a Write prompt,
  multi-line gutter), one post per distinct prompt, approve call argv built from the stored lines (fake `tmux-ctl`),
  each outcome edit, "answered elsewhere", reaction → exact queued line, unknown emoji ignored, non-bot message
  ignored.
- Bridge (`node --test`, fake client): unauthorized click gets the ephemeral reply and writes no event; defer within
  the handler; non-`ab:` custom ids ignored (the plugin's `perm:` buttons untouched); reaction from a non-allowlisted
  user ignored.
- One real run (user gate): a teammate in a scratch window triggers a Bash prompt; the user taps Allow on the phone;
  the command runs; a second prompt changed before the tap shows `not pressed`.

## Out of scope

- The lead's own prompts (plugin DMs).
- "Always allow" buttons.
