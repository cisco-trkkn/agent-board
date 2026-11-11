# /tasks from Discord

Date: 2026-11-11 · Ideas: 117, 123 in `~/.local/state/agent-board/ideas/agent-board.md`
Supersedes: `docs/superpowers/specs/2026-11-10-telegram-one-lead-tasks-design.md` (queued #10, never run). Its §1
(second-lead guard) and §3 (receipt reaction) moved to `2026-11-11-discord-replaces-telegram-design.md`; this spec is
its §2, retargeted to Discord.
Needs merged: `2026-11-11-discord-replaces-telegram-design.md` and
`docs/superpowers/specs/2026-11-10-interactive-tasks-window-design.md` (queued #7, adds the queue view).
Code: `bin/tmux-ctl`, `board/taskwin.py`, `claude/orchestrator.md`.

## Problem

The user wants to see what a project's lead is doing from the phone (idea 123: "if I could see the new interactive
task window that would probably be all I would need"). Decision (user, 2026-11-10, kept): status reaches the phone
**on demand, through the lead**: the user sends `/tasks`, the lead replies with the queue view. No pushes from the
board.

## Design

### 1. `tmux-ctl tasks [--discord] [--width N]`

- Renders the queue view for the calling lead's session id (`CLAUDE_CODE_SESSION_ID`) through `taskwin.py render`,
  with the project's git toplevel as `--root`.
- `render` gains `--view queue|plan|history` (default: today's behaviour) and `--plain` (no ANSI colour, the same as
  `color_mode` off). If #7 already added either flag, reuse it.
- `--discord`:
  - implies `--plain` and a 44-column width unless `--width` is given (phone width);
  - wraps the output in one fenced code block (a line of three backticks, the rows, a line of three backticks); a row
    containing three backticks has them replaced by `'''`;
  - caps the whole message, fences included, at 1900 characters (Discord's limit is 2000; the plugin splits longer
    text, which would break the fence). Whole rows are cut from the end and replaced by `… <n> more rows`.
- Outside a lead session (no session id): exit 2 with `tasks: no lead session id`.
- Help line in `bin/tmux-ctl`.

### 2. Lead rule

`claude/orchestrator.md` § Remote: Discord gains one bullet, applied to the live file as a dry-run-checked patch:

> A Discord message that is `/tasks` or `tasks` from an allowlisted sender: run `tmux-ctl tasks --discord` and reply
> with its stdout verbatim. Nothing else in the reply. It works whether or not the user is remote.

The plugin registers no Discord slash commands, so `/tasks` arrives as plain message text; both spellings are matched
after trimming whitespace, case-insensitive.

## Testing

- `render --view queue --plain` on a fixture task dir: no ESC bytes, expected rows.
- `tmux-ctl tasks --discord`: output starts and ends with a fence line; width 44; a fixture with many tasks is cut to
  at most 1900 characters with a correct `… <n> more rows` line and an intact closing fence; a row with three
  backticks is escaped.
- No session id → exit 2 and the message.
- One real run (user gate): the user sends `/tasks` to the agent-board bot and gets the queue view in one message.

## Out of scope

- Pushing status to Discord without a request.
- Slash-command registration with Discord's API.
