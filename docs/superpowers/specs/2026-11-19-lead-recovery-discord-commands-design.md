# Lead recovery without a terminal, and the /lead, /tasks and /gauth commands (regroup group 2)

Date: 2026-11-19 · Decided with the user over Discord, 2026-11-19 (regroup "Discord commands and lead recovery"; ideas fa71b998c3, 69bbe21a1a, 48ef9c9194, 4e7725d575, 12d638431a, cac3c06f90)

Background: `~/.local/state/agent-board/notes/2026-11-19-reconnect-stuck-lead.md` (how a stuck agent-board lead was reconnected by hand from the interiors lead on 2026-11-19 21:52).

## Problem

1. `tmux-ctl relay` failed three times on 2026-11-19 (from 11:28) with "the lead is still busy after the wait" while the lead sat idle at its prompt. `board/relay.py` `wait_turn_end` reads `paneclass.pane_status`, which misread the idle lead. A self-started handoff never switched, and the next lead had to be started by hand.
2. That hand-started lead ran in a window named `claude-next`. `relay` refuses any window not named `claude` ("only the lead, from the session's claude window, can relay"), so the lead could not hand off.
3. A lead started while the previous lead still holds the project's Discord bot drops the channel (`bin/claude-orchestrator:53`, "this lead starts without it") and never gets it back. After the old lead exits, nobody holds the bot: the bridge keeps posting, but the user's messages reach no session. `tools/discord_watch.py` repairs only leads started with `--channels` whose discord server is missing, not a lead started without the channel.
4. From the phone, the user cannot restart, hand off or inspect a lead. A lead asked in words through another project's lead was blocked by the auto-mode classifier from restarting the agent-board lead.
5. From the phone, the user cannot see a plan's task list. `/queue` shows only the queue.
6. Google re-auth (`invalid_rapt`, missing credentials) needs the terminal. On 2026-11-19 it was done by hand for signal-hub.

## Decisions (user, Discord, 2026-11-19)

- D1. One spec for all six ideas (Q-B answer "2").
- D2. `/gauth` runs a fixed command from the project's config file. Nothing from Discord text becomes a flag, and the code is taken only from an allowlisted reply (Q-C answer "1").
- D3. `/lead status` answers at once. `restart` and `handoff` first show what they will do, with a Confirm button (Q-D answer "1").
- D4. A new lead waits up to 60 s for the old holder of the bot. Otherwise discord-watch restarts a bot-less lead with `--resume` once nobody holds the bot and the lead is idle at its prompt, never mid-turn (Q-E answer "1").
- D5. The design below was approved as sent ("Ok", 22:51Z).

## Design

### 1. Relay (`board/relay.py`, `bin/tmux-ctl`)

- **Busy bug: reproduce first.** Capture an idle lead pane in the state that failed (a lead with a task list under its input box, and with the status rows below it) as `board/tests/fixtures/relay/idle-lead-*.txt`. Run `paneclass.pane_status`'s classification on it, find the misread, and fix it in `paneclass` (shared with the board) or in `wait_turn_end`, whichever owns the bug. Spec C's task-list skip in `paneclass` may already cover it. If the capture already reads as ended on spec C's code, the task records that and adds the fixture as a regression test.
- **Window name.** `tmux-ctl relay` accepts the calling lead's own pane (`$TMUX_PANE`, when the pane runs the session's lead) whatever its window is named. It renames that window to `claude` before relaying. `claude_pane` keeps its lookup by name for callers outside the lead.

### 2. `tmux-ctl lead-restart <project> [--resume | --doc <handoff>]` (`bin/tmux-ctl`, `board/relay.py`)

1. Find the project's lead pane: the window named `claude`, else one named `claude-next`, else the pane of the project's lead mark. None found: exit 1, `lead-restart: no lead pane for <project>`.
2. Rename its window to `claude`.
3. The command:
   - `--resume`: `claude-orchestrator --resume <the pane's current session id>`. The session id is read from the lineage or agent-status files; with none, exit 1 and change nothing.
   - `--doc <path>`, or no flag: `claude-orchestrator 'Read <doc> and continue from where the previous session left off.'`, where the doc is the newest handoff whose `Project:` line equals the project's root. With none: exit 1.
4. `respawn-pane -k -t <pane> -c <root> "<command>"`: the command is the pane's command, never typed into it (the notes' "typed line queued" gotcha).
5. Wait up to 60 s for the Claude prompt (`relay.wait_started`), then check that `tmux-ctl discord status` for the project names the new pid as holder when the project has a bot. Print `lead-restart: <project> restarted (<how>); bot: held by the new lead | not held | no bot`. Exit 0 when the lead started, even if the bot is not held (the next part retries that).
- **Allow rule.** `Bash(tmux-ctl lead-restart:*)` is added to the `permissions.allow` list in `claude/settings.json` (the installed user settings, so leads and the overseer get it), so a lead asked in words can run it without the classifier blocking.

### 3. Bot handover (`bin/claude-orchestrator`, `tools/discord_watch.py`)

- **Wait at start.** When the holder is a different pane, and that pane runs a lead of the same project (window `claude` or `claude-next`, or the old window of an in-place relay), `claude-orchestrator` polls `dc_holder` every 2 s for up to 60 s. Once nobody holds the bot, it takes it as today. A holder in another project or another process is never waited on: today's message is kept, and the lead starts without the bot.
- **Watch repair.** On every run (launchd, 60 s), for each project with a bot token: if nobody holds the bot, and a lead pane of that project runs a Claude without `--channels plugin:discord…` in its command line, and that pane is idle at its prompt on two runs in a row, discord-watch runs `tmux-ctl lead-restart <project> --resume`. After a success, it posts `<project> lead reconnected to Discord` through the bridge. At most one restart per project per 15 min. A failure is logged and bannered, as discord-watch does today.

### 4. `/lead status|restart|handoff <project>` (`tools/discord-bridge/lib/commands.js`, `tools/discord-bridge/bridge.js`, `board/discord_ops.py`)

- A bridge slash command. Only `allowFrom` users. It never goes through a model: the bridge writes a slash event, and `discord_ops` runs fixed code.
- `status`: lead window and pane, pid, busy/idle (pane class), whether it holds the bot, context % (from the statusLine tap), the newest handoff doc and its age. Replied privately.
- `restart` and `handoff`: a preview of what will happen ("restart the agent-board lead in window claude with --resume <id>; it is busy right now" / "start a fresh lead from <doc>, written 12 min ago"), with Confirm and Cancel buttons. Confirm runs `tmux-ctl lead-restart <project> --resume` or `--doc <newest>`, and edits the message with its printed result. Cancel edits it to `cancelled`. A preview older than 5 min refuses Confirm (`expired; run /lead again`).

### 5. `/tasks [project]` (`tools/discord-bridge/lib/commands.js`, `board/discord_ops.py`)

- With a project: a private reply listing that lead's current plan tasks (the `Task N:` tasks of the running `Plan & run:` task): id, status, owner, tier, subject cut to 60 characters, in a fenced block, the same way `/queue` is shown.
- Without a project: one message with a dropdown of the projects whose lead has a task list. Picking one gives the same reply.

### 6. `/gauth <project>` (`board/gauth.py` new, `bin/tmux-ctl`, `tools/discord-bridge/lib/commands.js`, `board/discord_ops.py`, `claude/worker.md`, `claude/orchestrator.md`)

- **Config.** `<state>/gauth/<project>.json`: `{"adc": true|false, "impersonate": "<service account email>"|null, "account": "<email>"|null}`, written by the user at the terminal (`tmux-ctl gauth config <project> …`). Discord never writes it. No config file: `/gauth` replies `no gauth config for <project>; set it at the terminal: tmux-ctl gauth config …`.
- **Run.** The command is built from the config only: `gcloud auth application-default login --no-launch-browser` (adc) or `gcloud auth login --no-launch-browser`, plus `--impersonate-service-account=<sa>` when set. It runs in a bg window `gauth-<project>` (in `<project>-bg`). The board reads the sign-in URL from the window and posts it privately to the user who ran `/gauth`, with "reply to this message with the code within 10 min".
- **Code.** Only a reply to that message, from that same allowlisted user, within 10 min, is taken. It is typed into the window with `send-keys -l` and Enter. The reply message is deleted right after, whatever the outcome. Any other message is ignored.
- **Result.** The window's "Credentials saved" line (or the error) is posted. Then a token check: `gcloud auth [application-default] print-access-token > /dev/null`, which reports only `token ok` or the error, never the token. The window is closed afterwards. One `/gauth` per project at a time: a second one replies `a /gauth for <project> is already waiting for its code`.
- **Agents.** `claude/worker.md`: on `invalid_rapt`, `Reauthentication failed` or missing credentials, stop that step and message the lead. `claude/orchestrator.md`: the lead posts `🔑 <project> needs Google re-auth: run /gauth <project>` and does not ask for the terminal while the user is remote.

## Error handling

- `lead-restart` changes nothing before it has a pane and a command: a missing pane, session id or doc exits 1 before the rename and the respawn.
- The watch repair never restarts a busy lead, never one whose bot is held, and never more than once in 15 min.
- `/gauth` with no config, a second concurrent `/gauth`, a timed-out code, a reply from another user: each is refused or ignored with a message, and the window is closed on timeout.
- Every Discord command checks `allowFrom` first and writes an audit line, as the other ops commands do.

## Testing

- `board/tests/test_relay.py`: the captured idle-lead fixture reads as ended; a working fixture does not; relay from the lead's own pane in a window named `claude-next` renames the window and proceeds, while a non-lead caller in such a window is refused.
- `tools/tests/test_ctl_lead_restart.zsh` (scratch tmux server, `-f /dev/null`, fake `claude-orchestrator` that records its argv): `--resume` passes the pane's session id; no flag picks the newest matching handoff and ignores another project's newer doc; the command is the respawn command, with nothing typed; `claude-next` is renamed; a missing pane exits 1 with nothing changed.
- `tools/tests/test_claude_orchestrator_dc.zsh`: a holder that is the same project's lead in another pane and releases within 60 s is waited on, and the bot is taken; a holder that never releases leads to a start without the bot after 60 s (fake clock); a holder in another project is not waited on.
- `tools/tests/test_discord_watch.py`: a bot-less idle lead with the bot unheld is restarted with `--resume` on the second run, not the first; a busy lead is not restarted; a held bot is not; the 15-minute cap holds.
- `tools/discord-bridge/test/*.test.js` and `board/tests/test_discord_ops.py`: `/lead`, `/tasks` and `/gauth` from a stranger are refused; `restart` without Confirm does nothing; an expired preview refuses; `/tasks` renders a task list and the dropdown; `/gauth` with no config gives the config hint; the code reply from another user is ignored; the code message is deleted on success and on failure.
- `board/tests/test_gauth.py`: the command is built from the config only (fake `gcloud` on PATH records its argv); extra text after `/gauth <project>` is not passed on; the token check output never contains the token.
- One real check after the merge (user gate): `/lead status` on the phone; a real `/lead restart` of an idle lead, and it holds the bot afterwards; `/tasks`; one real `/gauth` for signal-hub-gcp.

## Out of scope

- Restarting a busy lead from the watch (only `/lead restart` with Confirm can do that).
- Discord text as gcloud flags (Q-C option 2).
- Re-auth for other providers than gcloud.
