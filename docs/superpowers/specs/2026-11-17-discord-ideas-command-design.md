# Discord /ideas: grouped open ideas with buttons

Status: approved on Discord 2026-11-17. Depends on `2026-11-12-discord-ops-bot-design.md` (slash commands, ops bridge, chat with the overseer). Queued after `2026-11-17-discord-ticker-design.md`.

## Goal

From the phone, the user sees the open ideas grouped by theme and acts on each group with one tap: brainstorm it next, park it, or drop it.

## User decisions (made on Discord, 2026-11-17)

- Claude does the grouping (the overseer), not stored tags.
- `/ideas` covers every project and `/ideas <project>` covers one. The answer goes in the channel where the command was typed.
- Each group carries the buttons Brainstorm next / Park / Drop.

## Flow

1. **Slash.** `/ideas [project]` is registered by both bridge modes, next to the ops bot's commands (`lib/commands.js`). The bridge answers in an ephemeral reply, `asked the overseer, about 1 min`, and writes the `slash` event (`name: "ideas"`, `project` optional, `channel`).
2. **Ask.** The board (`discord_ops.handle_event`) checks the project (when one is given, it must be known, as with `/status`). It writes a request file `<_ops>/ideas/req-<id>.json` `{id, project|null, channel, ts}` and sends the overseer the line `[Discord] /ideas <id>: group the open ideas of <project|all projects>, write the groups file and run tmux-ctl discord ideas-post <file>`. It goes through the same path the ops spec uses for overseer chat.
3. **Group.** The overseer reads the ideas files (`${TC_IDEAS_DIR:-~/.local/state/agent-board/ideas}/<project>.md`, open lines `- [ ]`). It writes `{"request": "<id>", "groups": [{"title", "emoji", "project", "ideas": ["<idea id>", …]}]}` and runs `tmux-ctl discord ideas-post <file>`.
   - An **idea id** is `sha1(project + "\0" + <the idea line without its checkbox>)[:10]`. `tmux-ctl discord ideas-list [<project>]` prints `<id>\t<project>\t<text>` for every open idea, so the overseer never computes hashes itself.
   - The overseer's instructions (the overseer prompt, `bin/claude-overseer`) say: group by theme, 3–8 groups, every open idea in exactly one group, and no idea text written by hand.
4. **Post.** `board/discord_ideas.py post(file)`:
   - Validates the file: the request must be known and unanswered, and must be under 10 min old.
   - Drops unknown or closed ids and lists them under "skipped".
   - Assigns each idea only once.
   - Saves the post state `<_ops>/ideas/post-<id>.json` (groups with their ids and line texts).
   - Writes one outbox op per group to the bridge of the request's channel: the ops bridge for #command-center, or a project bridge for a project channel. The op is a `post` with buttons, of this form:
     - text: `<emoji> **<title>** · <project> · <n>`, then one `• <idea text cut to 120>` per idea
     - buttons: `ab:ideas:next:<req>:<g>`, `ab:ideas:park:<req>:<g>`, `ab:ideas:drop:<req>:<g>`
   - The whole answer is at most 10 groups. Text is cut to 1900 characters per group, with `… n more`.
   - A request with no open ideas posts `no open ideas` instead.
5. **Buttons.** The bridge forwards each click as a `click` event, and the board handles the following.
   - **Brainstorm next**: adds the line `regroup: <group title> — ideas: <id>, …` to that project's lead (`COMMENTS.add_line(project, …)`), then edits the post to `→ sent to <project>'s lead to brainstorm`.
   - **Park**: edits the post to `parked`. No file changes.
   - **Drop**: rewrites each listed idea's line from `- [ ]` to `- [-]` in the project's ideas file, matching the exact line by its id. A line that has changed or is already closed is left alone and counted. It writes under a lock, using a temp file and rename, then edits the post to `dropped <n>` (plus `, <m> already changed` when m > 0).
   - **Once only**: a group's action is recorded in the post state. A second tap is audited `unknown` and gets the ephemeral reply `already done`.
   - Only allowlisted users can press, as with every ops button. Every press is audited.
6. **Time-out.** A request still unanswered after 3 min gets `overseer didn't answer /ideas` in its channel and is closed. A late `ideas-post` for it is refused with rc 1.

## Delivery semantics

- **Repeated click**: once only, through the post state, as described above.
- **Out of order**: a click for an unknown or closed request is audited `unknown`, and nothing changes.
- **Concurrent**: drop takes the ideas-file lock that `tmux-ctl idea` uses (`fcntl` on `<ideas>.lock`); post state is written under the ops state lock.

## Testing

- `board/tests/test_discord_ideas.py`:
  - Id computation matches `ideas-list`.
  - The validator drops unknown ids, rejects a closed or expired request, and handles duplicates.
  - Group text and the 1900-character cut.
  - Next writes the regroup line.
  - Park changes no file.
  - Drop marks exactly the listed lines and leaves a changed line alone.
  - A second tap gets `unknown`.
  - Time-out.
- `tools/tests`: `tmux-ctl discord ideas-list` and `ideas-post` argv and exit codes.
- Bridge: `/ideas` registration in both modes, and the ephemeral ack.
- Real-state check (read-only): `ideas-list` on the live ideas file prints all 26 (or the current count of) open ideas. A fixture groups file built from them passes validation without writing any outbox op (`--dry-run`).
- User gate: the user runs `/ideas` on the phone, sees the groups, and presses Brainstorm next, Park and Drop once each on test groups. Next reaches the lead as a `regroup:` line, Park changes nothing, and Drop marks the lines `- [-]`.
