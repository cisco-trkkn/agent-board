# Telegram: one lead per bot, /tasks from the phone, and a receipt reaction

Date: 2026-11-10 · Ideas: 117, 123 and 124 in `~/.local/state/agent-board/ideas/agent-board.md`
Builds on: `docs/superpowers/specs/2026-11-10-telegram-fixes-design.md` (queued #4) and
`docs/superpowers/specs/2026-11-10-interactive-tasks-window-design.md` (queued #7). Both land before this spec runs.
Code: `bin/claude-orchestrator`, `tools/lib/telegram.zsh`, `bin/tmux-ctl`, `board/taskwin.py`, `claude/orchestrator.md`.

## Problem

1. **Idea 117: will side sessions break the polling?** Checked on 2026-11-10 against the live processes:
   - A plain `claude` started in another window or from a shell gets no `TELEGRAM_STATE_DIR`.
     `bin/claude-orchestrator` exports it in the lead's own process only, never in the tmux env, and
     `claude/plugin/scripts/telegram-env-scrub.sh` unsets it in the lead's Bash shells. So that session runs the
     plugin with the default folder, which holds no token, and does not poll.
   - Teammates are the same: after two teammates ran, `bot.pid` still named the lead's own poller.
   - **A second lead in the same project is the gap.** A lead started with `dev`, `claude-orchestrator` or a board
     restart while a lead is live gets the same state dir. Its telegram server SIGTERMs the poller named in
     `bot.pid` and takes the bot. The first lead loses Telegram with no message on either side.
2. **Idea 123: what is going on, from the phone.** Each project has its own bot, but nothing answers "where is the
   queue?" The interactive tasks window (#7) has a queue view. It is drawn only in the `tasks` tmux window.

## Decisions (user, 2026-11-10)

- A second lead **does not take the channel** when a live lead already holds the bot. It starts without Telegram
  and says which lead holds it.
- Status reaches the phone **on demand, through the lead**: the user sends `/tasks`, the lead replies with the queue
  view. No pushes from the board.

## Design

### 1. Second-lead guard (`bin/claude-orchestrator`)

Inside the block that sets `TG_DIR`, before `export TELEGRAM_STATE_DIR`:

- Read `$TG_DIR/bot.pid`. The holder is **live** when all of these hold:
  - the pid is alive (`kill -0`);
  - its command is the telegram server (`ps -o command=` contains `telegram/` and `server.ts`);
  - its parent pid is not 1 and the parent's command starts with `claude`.
- An orphaned poller (parent 1), left by a relay's or restart's `respawn-pane -k`, is **stale**. The guard ignores it,
  and the new server's own SIGTERM clears it, as today.
- Live holder: skip the channel. Don't export the state dir and leave `TG_ARGS` empty. Print one line to stderr:
  `telegram: <project>'s bot is held by the lead in <session>:<window> (pid <claude pid>); this lead starts without it`.
  `<session>:<window>` comes from the tmux pane whose `#{pane_pid}` is the holder's parent claude. When no pane
  matches, print `another process` instead.
- A missing `bot.pid`, or any other case: today's behaviour.
- Same-pane exception: when the holder's parent claude runs in `$TMUX_PANE`, it is about to be replaced (an `exec`
  in place). Treat it as stale.
- Put the check in a helper sourced by both callers, `tg_holder <dir>` in `tools/lib/telegram.zsh`. It prints
  `<claude pid> <pane id>` for a live holder, or nothing.

`tmux-ctl telegram status [<project>]` gains one line from the same helper:
`held by: <session>:<window> pid <n>` or `held by: nobody`.

Known race: two leads starting within the same second can both see no holder. The last server to start wins, as
today. Accepted: leads are started by hand.

### 2. `/tasks` from Telegram

- The plugin already uses the bot command `/status` for its pairing check, and that command never reaches the lead.
  The command is `/tasks`; the bare word `tasks` works too.
- New `tmux-ctl tasks [--telegram] [--width N]`:
  - Renders the queue view for the calling lead's session id (`CLAUDE_CODE_SESSION_ID`) through `taskwin.py render`,
    with the project's git toplevel as `--root`.
  - `render` gains `--view queue|plan|history`, default today's behaviour. It also gains `--plain`: no ANSI colour,
    the same as `color_mode` off.
  - `--telegram`:
    - implies `--plain` and a 44-column width unless `--width` is given;
    - wraps the output in one MarkdownV2 pre block, with `\` and backtick escaped inside it;
    - caps the whole message at 3900 characters. Whole rows are cut from the end and replaced by `… <n> more rows`,
      so the plugin never splits the pre block across messages.
  - Outside a lead session (no session id): exit 2 with `tasks: no lead session id`.
- `claude/orchestrator.md` § Remote: Telegram gains one bullet. Write it into the live file as a dry-run-checked
  patch so the user's uncommitted edit survives:
  > A Telegram message that is `/tasks` or `tasks` from an allowlisted sender: run `tmux-ctl tasks --telegram` and
  > reply with its stdout verbatim, `format: markdownv2`. Nothing else in the reply. It works whether or not the user
  > is remote.

### 3. Receipt reaction (idea 124)

The user wants every Telegram message confirmed, so they know the bot is working. The plugin already supports this
itself:
- `ackReaction` in the bot's `access.json` (`server.ts:118`, applied at `server.ts:958`) makes the telegram server
  react to each delivered message on receipt.
- No LLM is involved, so it works while the lead is busy.
- `access.json` is read per message, so a change applies without a restart.

On 2026-11-10 the user's two bots (agent-board, interiors) were set to `👀` by hand, with backups in
`~/.claude/plugin-backups/telegram/`. This spec makes that the default:

- `tmux-ctl telegram token` sets `ackReaction` to `👀` in `<dir>/access.json` after saving the token:
  - when the file is missing, it creates `{"dmPolicy": "pairing", "allowFrom": [], "groups": {}, "pending": {}}` plus
    `ackReaction`, mode 600;
  - when the file has no `ackReaction` key, it adds the key;
  - when the key exists, even empty (empty means the user turned it off), it leaves the file alone.
  - The write is atomic (temp file, then rename) and every other key is kept.
- `tmux-ctl telegram status` prints `ack reaction: 👀` or `ack reaction: off`.
- Tests:
  - token on a new dir creates `access.json` with `ackReaction`;
  - token on an existing file without the key adds it and keeps every other key byte-for-byte equal as parsed JSON;
  - an existing empty `ackReaction` is left alone;
  - the `status` line, for both cases.

### 4. Tests

- `tools/tests/test_telegram_guard.zsh` (scratch tmux server, `-f /dev/null`). The fake poller is a script named
  `server.ts` under a `telegram/` dir; its parent is a fake `claude`, a symlinked shell script. Cases:
  - live holder in another pane: no channel, and the message names that pane;
  - orphaned holder (parent 1): channel taken;
  - holder in the same pane: channel taken;
  - no `bot.pid`: channel taken;
  - pid alive but not the telegram server: channel taken.
  Assert on the `claude` argv that `claude-orchestrator` execs (stub `claude` on PATH), and on the stderr line.
- `tmux-ctl telegram status`: the `held by:` line, for a live holder and for nobody.
- `board/tests/test_taskwin.py`:
  - `render --view queue --plain` has no escape bytes;
  - the `--telegram` wrapper escapes `\` and backtick;
  - the cap keeps output ≤ 3900 characters and ends with `… <n> more rows`, from a fixture task list of 60
    `Plan & run:` items.
- User gate: from the phone, send `/tasks` to the project's bot while a queue is listed. The reply is one monospace
  block whose rows match the `tasks` window's queue view.

## Out of scope

- Pushing status to Telegram without being asked.
- Any change to the telegram plugin itself.
- Showing the plan or history views over Telegram: the flag exists, but the lead rule asks for the queue view only.
