# New project from the phone: `/new-project`

Status: approved by the user on Discord, 2026-11-23 (sections 1-3). Source idea: ideas inbox, 2026-11-23 14:46,
"Streamlined new-project setup: start a new project and its own Discord bot in one flow, doable remotely".

## Goal

From the phone alone, with the Mac unattended, the user starts a new agent-board project and its own Discord bot in one
flow: a folder on disk, a dev session with a lead, and a home channel in which that lead says hello. Today the same
result needs a terminal for the token pipe (`tmux-ctl discord token`), the pairing (`tmux-ctl discord pair`), the
channel id and the bridge start (docs/INSTALL.md, "Remote access").

## Decisions (user, Discord, 2026-11-23)

1. **One bot per project**, as today. The flow guides the Developer Portal steps; nothing replaces them.
2. **Everything is done on the phone**, remote from the Mac.
3. **Any source**, chosen in the form: a new empty repo (`git init`), a clone of a git URL, or an existing folder.
4. **Entry point:** a `/new-project` slash command on the ops bot, which posts a setup card in the command center.
5. **Home channel:** the ops bot creates `#<name>` and grants the new bot its permissions there.
6. Defaults (stated, not objected to): new and cloned repos go to `~/<name>`; a clone uses the Mac's existing git
   credentials; at the end the dev session and its lead start, and the lead says hello in `#<name>`.

## Hard limit

Discord has no API that creates a bot application. Creating the application, adding the bot, turning on **Message
Content Intent** and copying (resetting) the token stay manual, in the Developer Portal, which works in a phone browser.
The flow links each step and checks the result; it does not automate the portal.

## 1. The flow

`/new-project` (ops bot, command center only, allowlisted users only) opens a form: `name`, `source` (`new` | `clone` |
`folder`), `url or path` (required for `clone` and `folder`). The ops bot posts one **setup card** and edits it as each
step finishes (⏳ running, ✅ done, ❌ failed with a one-line reason and a **Retry** button):

1. **Project on disk.** `new`: `mkdir ~/<name>` and `git init -b main`. `clone`: `git clone <url> ~/<name>`.
   `folder`: the path exists, is a directory and is a git work tree.
2. **Bot.** The card lists the three portal steps with links (New Application → Bot → turn on Message Content Intent →
   Reset Token) and a **Paste token** button that opens a private form with one field.
3. **Check.** The token is checked against Discord (`GET /users/@me` with it). The bot's user id (= application id)
   comes from that answer. The application's flags (`GET /applications/@me`) must show the message content intent
   (`GATEWAY_MESSAGE_CONTENT` or `GATEWAY_MESSAGE_CONTENT_LIMITED`); if not, the card says "turn on Message Content
   Intent, then Retry", before anything else runs (a bot without it exits at login: `Used disallowed intents`). The card
   then shows an **Invite** link: `https://discord.com/oauth2/authorize?client_id=<id>&scope=bot&permissions=<int>&guild_id=<guild>&disable_guild_select=true`,
   where `<int>` is exactly the eight home-channel permissions of docs/INSTALL.md (View, Send Messages, Send Messages in
   Threads, Create Public Threads, Pin Messages, Read Message History, Add Reactions, Attach Files) and `<guild>` is the
   command center's server.
4. **Joined.** The board polls the new bot's own guild list (`GET /users/@me/guilds` with the new token) every 10 s until
   `<guild>` is in it; after 30 minutes the step fails `invite not accepted` (Retry polls again).
5. **Channel.** The ops bot creates the text channel `#<name>` in `<guild>` and adds a permission overwrite for the new
   bot's user id allowing the same eight permissions. The ops bot needs **Manage Channels** in that server once (a setup
   note in docs/INSTALL.md); without it the step fails `ops bot lacks Manage Channels`.
6. **Access.** The new project's `access.json` gets the user's id allowlisted (`tmux-ctl discord allow <id> --project
   <name>`, the id of the user who ran `/new-project`) and `policy allowlist`; no pairing code. Then `tmux-ctl discord
   channel <channel id> --project <name>`.
7. **Start.** `tmux-ctl discord bridge start --project <name>`, the dev session for `~/<name>` with its lead (which has
   the token, so it starts with the Discord channel), and the lead posts `hello from <name>` in `#<name>`. The card ends
   with a link to the channel.

Each step is idempotent and its state is kept, so Retry reruns only the failed step and a second run of a done step
changes nothing. `/new-project <name>` for a name whose setup is unfinished resumes the same card (a new card message
that replaces the old one's buttons) instead of starting over.

**Access rule change.** Today access changes are "yours, typed in a terminal: the lead never runs them"
(docs/INSTALL.md). Here the user's own allowlisted `/new-project` interaction on the ops bot is that action, and it is
limited: only the new project's `access.json`, only the id of the user who ran the command, only during this flow. The
lead still never runs access commands, and no Discord message text (as opposed to the slash-command interaction) can
trigger them. docs/INSTALL.md and claude/orchestrator.md say so.

## 2. Parts

- **Ops bridge** (`tools/discord-bridge/lib/commands.js`, `bridge.js`): registers `/new-project` (ops only) and its
  form (`ab:modal:new-project`), the card's buttons (`ab:np:token:<name>`, `ab:np:retry:<name>:<step>`), the token form
  (`ab:modal:np-token:<name>`), and two outbox actions: `create_channel {guild, name}` → channel id, and
  `channel_overwrite {channel, user, allow}`. Card posts and edits use the existing outbox. Every interaction goes
  through the existing allowlist check; refused interactions are audited as today.
- **Board** (new `board/newproject.py`, dispatched from `board/discord_ops.py` like `gauth`): the step machine. State in
  `~/.local/state/agent-board/newproject/<name>.json` (mode 600): name, source, url/path, guild, channel id, bot id,
  user id, each step's state and last error, card message id. **Never the token.** Mac-side steps run `tmux-ctl`; the
  two Discord-side steps are outbox actions on the ops bridge, whose results come back as events.
- **tmux-ctl**: new `tmux-ctl project new <name> --init | --clone URL | --dir PATH` (step 1, prints the folder) and
  `tmux-ctl project start <name>` (step 7's dev session and lead, reusing the session start the `dev` command uses). The
  rest reuses `discord token | allow | policy | channel | bridge start` with `--project <name>`. A new usage line goes in
  the help header, so the pinned `sed -n '2,84p'` range and its 9 suites move with it.

**Token path.** Token form submit → the bridge writes the token to a mode-600 one-shot file under the ops state dir
(never into the events file) and an event naming that file → the board pipes the file's content into
`tmux-ctl discord token --project <name>` on stdin, then checks it (step 3) and deletes the file whether the pipe
worked or not. No Claude session sees the token: the bridge and the board are code. Audit lines and the board log name
the step, never the token.

**Refusals up front** (the card is not posted; the form answers with one line): a name not matching
`^[A-Za-z0-9][A-Za-z0-9._-]*$` (today's project-name rule); an existing project state dir, tmux session or (for `new`
and `clone`) folder `~/<name>`; `folder` with a path that is not a git work tree; a command used outside the command
center.

**Failures in a step**: a clone that fails (❌ with git's last stderr line), token rejected (401: "token rejected",
**Paste token** again), intent off, invite not accepted after 30 minutes, missing Manage Channels, a bridge that does
not start (its `bridge start` line). Each keeps the earlier steps' results; Retry reruns that step only.

## 3. Testing

- **Unit (board/tests)**: the step machine against a fake Discord REST and a fake `tmux-ctl` (argv recorded): each
  step's success and failure, Retry of only the failed step, a re-run of a done step is a no-op, resume via
  `/new-project <name>`, the refusals. A leak test: after a full fake run and after a failed token step, the token
  string is absent from the state file, the audit log, the board log, every card text and the events file, and the
  one-shot file is gone.
- **Bridge (tools/discord-bridge, `npm test`)**: `/new-project` registration (ops only), the forms, `create_channel`
  and `channel_overwrite` against a fake REST client, and every new interaction refused for a non-allowlisted user.
- **tmux-ctl (tools/tests)**: `project new` with `--init`, `--clone` (a local bare repo) and `--dir` on a scratch tmux
  server (`-f /dev/null`), and each refusal; `project start` starts the session on the scratch server.
- **Real run (user gate, on the phone)**: `/new-project scratch-np` (source `new`) with a throwaway bot, through to the
  lead's hello in `#scratch-np`. Cleanup: `tmux-ctl discord forget --project scratch-np`, delete the channel, the bot
  application, the folder and the state dir.

## Out of scope

Automating the Developer Portal; a shared bot for several projects; removing a project from the phone; GitHub/GitLab
repo creation for `new` (the repo is local until the user adds a remote).
