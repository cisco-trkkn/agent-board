# Discord replaces Telegram as the lead's remote channel

Date: 2026-11-11 · Ideas: 130, 131, 132 in `~/.local/state/agent-board/ideas/agent-board.md`
Supersedes: `docs/superpowers/specs/2026-11-10-telegram-fixes-design.md` (queued #4, never run). Its Telegram-only
parts (node launcher, bun block) are dropped; its access commands, `agent-board lead` and docs parts are carried over
to Discord below.
Takes from: `docs/superpowers/specs/2026-11-10-telegram-one-lead-tasks-design.md` §1 (second-lead guard) and §3
(receipt reaction). Its §2 (`/tasks`) moves to `2026-11-11-discord-tasks-design.md`.
Runs after: `docs/superpowers/specs/2026-11-11-turn-start-spinner-rule-design.md` (queued 2b), whose changes to
`tools/telegram_watch.py` are carried into `tools/discord_watch.py` here.

## Problem

- Telegram is blocked on the office network: Netskope blocks bun's HTTPS to `api.telegram.org`, and on the office
  Wi-Fi Telegram as a whole. The user has retired it (2026-11-11) and paired a Discord bot for agent-board by hand:
  app "agent-board", private server "agent-board", token in `~/.local/state/agent-board/discord/agent-board/.env`,
  `access.json` with `dmPolicy: allowlist` and one sender.
- Today only Telegram is wired: `bin/claude-orchestrator` auto-adds `--channels plugin:telegram@…` when a token is
  saved; Discord has to be passed by hand, and then (idea 132) a prompt placed after the user's `--channels` is
  swallowed as a channel (`--channels entries must be tagged`).
- The Discord plugin (0.0.4) is enabled in `~/.claude/settings.json`, so its MCP server starts in every session. With
  no token, `server.ts:53-62` exits 1, and Claude Code caches that failure for 15 minutes machine-wide: the same trap
  the Telegram stub launcher fixed.
- `DISCORD_STATE_DIR` is visible in the lead's Bash shells, so a `claude` started from the lead's shell would open a
  second gateway connection on the same bot (the trap `telegram-env-scrub.sh` fixed for Telegram).
- `/discord:access` writes `~/.claude/channels/discord/`, not the project's state dir (the 2026-11-11 pairing was
  done by hand in the right dir).

## Decisions (user, 2026-11-11)

- **Delete Telegram outright.** No opt-in path kept. The interiors project (its own Telegram bot, a live lead on it
  today) loses its remote channel at its lead's next restart, until the user saves a Discord token for it.
- **One Discord bot per project** (same model as Telegram): state dir `${TC_STATE:-~/.local/state/agent-board}/discord/<project>/`.
- **Carry over:** auto-add, no-token stub, env scrub, remote approval rules, reconnect watchdog, access commands,
  second-lead guard, receipt reaction, board badge. `/tasks` is a separate spec.
- **Discord-specific code**, no generic "channel" layer.
- Telegram token dirs under `~/.local/state/agent-board/telegram/` are user data: not deleted by code.

## Design

`<project>` everywhere is the pane's session group, else its session name, with a `-bg` session mapped to its project
(today's `TG_PROJECT` rule in `bin/claude-orchestrator:23-25`). `<dir>` is `${TC_STATE:-$HOME/.local/state/agent-board}/discord/<project>`.
"Has a token" means `<dir>/.env` holds a line `DISCORD_BOT_TOKEN=<non-empty>`.

### 1. Remove Telegram

Delete:

- `tools/lib/telegram.zsh`, `tools/lib/telegram-launch.zsh`, `tools/telegram_watch.py`, `tools/telegram_cache.py`
- `claude/plugin/scripts/telegram-mcp-launch`, `telegram-mcp-stub.js`, `telegram-env-scrub.sh`, and its hooks.json entry
- tests: `tools/tests/test_ctl_telegram.zsh`, `test_telegram_always_on.zsh`, `test_telegram_launcher.zsh`,
  `test_claude_orchestrator_tg.zsh`, `test_telegram_watch.py`, `claude/hooks/tests/test-telegram-env-scrub.sh`,
  `board/tests/test_telegram_badge.py`; fixtures `tools/tests/fixtures/telegram-watch/` are moved (§6), not deleted
- the `telegram` branches in `bin/tmux-ctl` (help lines 39-40, the `telegram` exemption at line 57, the dispatch at
  252-254), `board/server.py` (`TG_FLAG`, `telegram_leads`, the `telegram` pane key), `board/index.html:573`, and the
  `tmux-ctl telegram` help check in `tools/tests/test_ctl_approve_misc.zsh:56`

Kept as history, untouched: `board/tests/fixtures/metrics/remote-access-*` (metrics fixtures), the 2026-11-09/10
Telegram specs and plans (each gets one line at the top: `Superseded by 2026-11-11-discord-replaces-telegram-design.md`).

**Machine cleanup**, a new `tmux-ctl discord migrate` (idempotent, prints one line per action, never fails on a
missing piece), which the plan's finishing step runs once on this machine:

- `launchctl bootout gui/$UID/com.user.agent-board-telegram-watch` and delete its plist in `~/Library/LaunchAgents/`.
- `claude plugin disable telegram@claude-plugins-official` (user scope). Its patched `.mcp.json` points at a copied
  launcher inside the plugin dir; disabling stops it starting at all.
- Print `telegram: token dirs kept in <path> (delete them by hand when done)` when that dir exists.

### 2. Lead launch (`bin/claude-orchestrator`)

Replace the Telegram block (lines 18-38) with the Discord one:

- `unset DISCORD_STATE_DIR TELEGRAM_STATE_DIR`. When `TC_DISCORD` is not `0`, `$TMUX` and `$TMUX_PANE` are set,
  `<project>` resolves, and `discord-mcp-launch --has-token <dir>` passes, and the second-lead guard (§4) finds no live
  holder: `export DISCORD_STATE_DIR=<dir>` and add `--channels plugin:discord@claude-plugins-official`.
- **Idea 132.** The user's own `--channels <entries…>` (or `--channels=<entry>`) is taken out of `"$@"`, its entries
  merged with the auto-added one (deduped), and passed as one `--channels` list right before `AB_ARGS` (which starts
  with `--settings` and so ends the variadic list). The positional prompt then always follows a non-variadic flag.
  Entries run until the next argument starting with `-`.
- Not in tmux and `TC_DISCORD` not `0`: one stderr line `agent-board lead: not in tmux, so no Discord channel`.
- Every start runs `dc_ensure_launcher` (§3), never blocking the launch.
- `bin/agent-board`: `lead) shift; exec "$here/claude-orchestrator" "$@" ;;` plus a help line (from the superseded
  spec §3).

The 15-minute failure-cache clear (`telegram_cache.py clear`) is ported as `tools/discord_cache.py clear`, run when the
channel is added. The cache key is the one Claude Code writes for the discord plugin's server; the implementer reads
it from a real `~/.claude/mcp-needs-auth-cache.json` entry (one real run, test-driven-development-extras) and pins it in
a test fixture.

### 3. No-token stub (`claude/plugin/scripts/discord-mcp-launch`, `discord-mcp-stub.js`, `tools/lib/discord-launch.zsh`)

Port of the Telegram trio, with the runtime unchanged: the Discord server runs on bun here (checked 2026-11-11), so no
node switch.

- `discord-mcp-launch <plugin root>`: token from `DISCORD_BOT_TOKEN` or `${DISCORD_STATE_DIR:-${CLAUDE_CONFIG_DIR:-~/.claude}/channels/discord}/.env`
  → `exec bun run --cwd <root> --shell=bun --silent start` (the stock command); else
  `exec node <root>/discord-mcp-stub.js`, falling back to `bun` when node is missing.
- `discord-mcp-launch --has-token <dir>`: the one definition used by the orchestrator and `tmux-ctl discord status`.
- `discord-mcp-stub.js`: a minimal MCP server over stdio that answers `initialize` and lists no tools.
- `dc_ensure_launcher`: for each `<config>/plugins/cache/claude-plugins-official/discord/<version>/`, same contract as
  `tg_ensure_launcher` (copy both files in, back up `.mcp.json` to
  `<config>/plugin-backups/discord/<version>/.mcp.json.bak-YYYYMMDD`, write through `.mcp.json.next`, idempotent, one
  line on install, `TC_DISCORD_LAUNCHER=0` off, every error one line and return 0).

### 4. Second-lead guard

A second lead in the same project starts without Discord. Discord does not evict an older connection the way the
Telegram poller did: two gateway sessions on one token both receive every DM, so two leads would both answer.

- The discord server writes no pid file, so the holder is found from processes: a live process whose command is the
  discord server (the stock `bun run --cwd …/discord/<v> … start`, its `bun` child, or `discord-mcp-launch` with a
  token) and whose environment has `DISCORD_STATE_DIR=<dir>`. On macOS, read the environment with `ps -E -o command= -p
  <pid>` (the implementer verifies this flag on one real process before relying on it; if it is not available, the
  guard writes `<dir>/lead.pid` with the lead claude's pid at launch and checks that instead, and says which in the
  ledger).
- **Live** holder: its parent chain reaches a `claude` process whose parent is not 1. A holder whose claude parent runs
  in `$TMUX_PANE` is being replaced in place: stale.
- Live holder: no channel, no state dir. One stderr line:
  `discord: <project>'s bot is held by the lead in <session>:<window> (pid <claude pid>); this lead starts without it`
  (`another process` when no pane matches).
- Helper `dc_holder <dir>` in `tools/lib/discord.zsh` prints `<claude pid> <pane id>` or nothing; used by the
  orchestrator and by `status`.
- Known race (two leads starting in the same second): accepted, as in the Telegram spec.

### 5. Env scrub (`claude/plugin/scripts/discord-env-scrub.sh`)

Port of `telegram-env-scrub.sh`: SessionStart, in a lead (`AGENT_BOARD_LEAD=1`) with `DISCORD_STATE_DIR` set, append
`unset DISCORD_STATE_DIR DISCORD_BOT_TOKEN` once to `$CLAUDE_ENV_FILE`. Registered in `claude/plugin/hooks/hooks.json`
in place of the Telegram entry. Prints nothing, fail-open.

### 6. Access commands and status (`tools/lib/discord.zsh`, `tmux-ctl discord …`)

`bin/tmux-ctl discord <cmd>` works outside tmux with `--project <name>` (same exemption as today's telegram).

| Command | Effect |
| --- | --- |
| `token` | Read the token from stdin (never an argument, never printed), write `<dir>/.env` mode 600 through `.env.next`. Then set `ackReaction: "👀"` in `access.json` unless the key exists (even empty = user turned it off); create the default file (below) when missing. Ends with `discord: token saved for <project> (restart its lead: agent-board lead --continue, or Restart orchestrator on the board)`. |
| `pair <code>` | `pending[code]` missing or `expiresAt < now(ms)` → error, exit 1. Else add `senderId` to `allowFrom` (dedupe), delete `pending[code]`, write; then write `<dir>/approved/<senderId>` containing `chatId`. |
| `deny <code>` | Delete `pending[code]`; unknown → exit 1. |
| `policy <mode>` | `pairing`, `allowlist` or `disabled`, else usage exit 2. |
| `allow <id>` / `remove <id>` | Add to / remove from `allowFrom`. |
| `forget` | Delete `<dir>/.env`; `access.json` stays. |
| `status` | `token: set|missing`, `paired: <n> allowlisted`, `policy: <mode>`, `ack reaction: 👀|off`, `held by: <session>:<window> pid <n>|nobody`, `plugin: ok|missing` (from `installed_plugins.json`), `launcher: ok|drift`, `watch: loaded|not loaded`. |
| `watch --once|install|status|uninstall` | §7. |
| `migrate` | §1 machine cleanup. |

- Default `access.json`: `{"dmPolicy":"pairing","allowFrom":[],"groups":{},"pending":{}}`.
- Every write: read the live file, change it with `jq`, write `access.json.next` (mode 600, 2-space indent), `mv` over.
  Keys not touched are kept.
- A token-shaped argument is refused (never echo it). One positional value per command plus optional `--project`.
- A project name must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`.

### 7. Watchdog (`tools/discord_watch.py`)

Port of `tools/telegram_watch.py` as it stands on `main` when this spec's branch is cut: after 2b if 2b merged (its
`paneclass` spinner rule and module-level `remove()`), else today's file, with 2b's two fixes left to 2b:

- `CHANNEL = "plugin:discord@claude-plugins-official"`; the server-present check matches the discord server
  commands of §4; the bun-launcher special case (`BUN_START`) is dropped; reconnect target in `/mcp` is the discord
  server.
- State and log `${TC_STATE}/discord-watch.{json,log}`; off with `TC_DISCORD_WATCH=0` or `discord-watch.off`.
- launchd label `com.user.agent-board-discord-watch`, every 60 s, installed by `tmux-ctl discord watch install`.
- Fixtures `tools/tests/fixtures/telegram-watch/` move to `tools/tests/fixtures/discord-watch/` (`git mv`); fixtures
  that show the Telegram server name in `/mcp` text are re-captured or edited to the discord name, and the README there
  says which.
- `tools/tests/test_discord_watch.py` is `test_telegram_watch.py` ported, every case kept.

### 8. Board badge

`board/server.py`: `DC_FLAG = "--channels plugin:discord"` matched anywhere in the claude process's argument list
(not only the first `--channels` entry, since §2 merges lists); pane key `discord`; `board/index.html` badge text `dc`,
title `Discord channel on (delivery not checked by the board)`. `board/tests/test_discord_badge.py` ports the Telegram
badge test plus one case with two channel entries.

### 9. Lead rules and docs

- `claude/orchestrator.md`: "Remote: Telegram" becomes "Remote: Discord". Every Telegram mention moves to Discord
  (channel tag `<channel source="discord" …>`, the plugin's `reply` tool, the approval protocol unchanged in
  substance). Additions: replies over 2000 characters are split by the plugin (`textChunkLimit`), so keep a reply
  short; a lead never runs `tmux-ctl discord pair|deny|policy|allow|remove` or `/discord:access` (access changes are
  the user's, typed in a terminal). The live file may carry an uncommitted user edit: apply as a dry-run-checked patch.
- `docs/INSTALL.md` § Remote access: rewritten for Discord (create the app and bot, Message Content Intent, invite to a
  private server, `tmux-ctl discord token`, DM the bot, `tmux-ctl discord pair <code>`, `tmux-ctl discord policy
  allowlist`, `status` lines, the watchdog, the cache and stub notes, `tmux-ctl discord migrate` for a machine that ran
  Telegram).
- `tools/tests/e2e-remote-access.md`: the same steps for Discord.
- `README.md` and `tools/tests/lib.zsh:19` comment: Telegram → Discord.
- After the merge, `grep -rni telegram` over the tree outside `docs/superpowers/` and the metrics fixtures returns
  nothing.

## Error handling

- Nothing in this spec may stop a lead from launching: launcher, cache clear, guard and migrate print one line and go
  on.
- Access commands: missing `jq` → exit 1 with `discord: jq not found`; unreadable `access.json` → exit 1, file left
  as is.

## Testing

- Port every Telegram test to Discord, case for case: orchestrator (auto-add, opt-out `TC_DISCORD=0`, no token, not in
  tmux, user `--channels` merge with a trailing prompt, the idea-132 regression), launcher (stub vs real, idempotent,
  backup, plugin update heal), env scrub, access commands (each row of §6, atomic write keeps other keys, token never
  printed), status, watchdog, badge, guard (live holder, stale orphan, same-pane, no holder).
- All tests run against a scratch `CLAUDE_CONFIG_DIR` and `TC_STATE`, never the real ones (lib.zsh already does this).
- `migrate` runs against fakes of `launchctl` and `claude` on PATH in tests; the real run is the finishing step's.
- One real run: on this machine after the merge, restart the agent-board lead with `agent-board lead --continue`; the
  board shows the `dc` badge, `tmux-ctl discord status` shows `held by:` that lead, and a DM from the user gets 👀 and a
  reply. This is a user-gate task (the user sends the DM).

## Out of scope

- `/tasks` from Discord (`2026-11-11-discord-tasks-design.md`).
- A Discord bot for interiors (the user saves its token after the merge).
- Group channels / guild routing (`groups` in `access.json` stays as the plugin defines it).
