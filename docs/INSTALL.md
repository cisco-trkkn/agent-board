# Installing agent-board

agent-board installs from a clone of this repo with one script, `install.sh`, and **does not change how your existing Claude Code and tmux setup behaves**. Your own `claude` sessions, their user settings, skills and agents, and your tmux setup stay as they are. agent-board's hooks, skills and agent types are loaded only into the Claude sessions agent-board starts, and its tmux hooks and key bindings live on its own tmux server. Expect about 5 minutes.

> **Shell:** every snippet is zsh (the macOS default shell). Run them in zsh, not bash.
>
> **Platform:** developed and tested on macOS. For Linux, see [Linux notes](#linux-notes).

## What the install changes on your machine

| Location | Change | Effect on your other Claude Code / tmux use |
| --- | --- | --- |
| `~/.local/bin/agent-board` | **one symlink** to `bin/agent-board` in your clone: the only thing `install.sh` installs | none: it is a new command name |
| `~/.claude/` (user settings, skills, agents, hooks) | **none** | none |
| your tmux setup | **none** | none: agent-board's tmux server loads the config in `config/` from the clone instead |
| your running tmux server | **none** | none: agent-board runs its own server, `tmux -L agent-board` |
| `~/.local/state/agent-board/` | created on first use: ideas, handoffs, context | none |
| `~/.local/state/tmux-dash/` | created by `agent-board dash`: board token, pids, logs | none |
| `${TMPDIR:-/tmp}/tmux-ctl-$UID/` | runtime state (runs, logs, artifacts, usage index) | none |
| `~/.config/agent-board/` | **not created**; optional overrides you write yourself ([CUSTOMIZATION](CUSTOMIZATION.md)) | none |
| `~/.claude/projects/` (your transcripts) | **read only**, by the board's Usage tab | none: nothing is written there |

How the rest reaches Claude without touching `~/.claude`: every Claude that agent-board starts gets `--settings` with the settings file in `<clone>/claude/` (agent teams, `teammateMode`, the `AGENT_BOARD=1` marker) and `--plugin-dir <clone>/claude/plugin` (the `bash-mirror`, `artifact-register`, `kill-guard` and `worktree-sweep` hooks, `plan-handoff-guard` (refuses writing-plans' execution-choice question; `PLAN_HANDOFF_GUARD=0` disables it), `sdd-call-guard` (denies an Agent dispatch while a plan has no `subagent-driven-development` Skill call, which would make superpowers' handoff guard refuse later questions; `SDD_CALL_GUARD=0` disables it), `agent-name-guard` (in the lead only, marked `AGENT_BOARD_LEAD=1` by `claude-orchestrator`: denies an Agent call with no `name`, or a fork, so every agent opens in a `✦` window; `AGENT_NAME_GUARD=0` disables it), `context-inject` (a SessionStart hook that injects the project's shared context file, `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`, capped at 8 KB; `TC_CONTEXT=0` disables it), the `tmux-orchestrator` and `handoff` skills, the `effort-low`/`-medium`/`-high` agent types). That covers the lead, the workers started by `tmux-ctl agent`, and the teammates, which Claude Code starts with the lead's own `--settings` and `--plugin-dir` flags. Plain `claude` outside agent-board loads none of it.

> **Used the author's earlier global setup, or an earlier version of this guide?** Run `./install.sh --migrate` (see [Migrating](#migrating-from-the-global-setup)). Otherwise the old global hooks run next to the new ones.

## 1. Prerequisites

Versions are the ones tested. Older versions may work, but only Python 3.9 has been checked.

| Tool | Tested | Used by | Notes |
| --- | --- | --- | --- |
| zsh | 5.9 | every `bin/` script, `install.sh` | on `PATH` |
| tmux | 3.8 | everything | found as `TC_TMUX` if set, else `~/.local/bin/tmux` if executable, else `tmux` on `PATH` |
| ttyd | 1.7.7 | the board's live terminals | on `PATH`, or set `TTYD_BIN` |
| fzf | 0.74 | `agent-board jump`, `agent-board cleanup` | on `PATH`, or set `FZF_BIN` |
| python3 | 3.9.6, 3.14 | board server, hooks, `install.sh` | 3.9 or newer, standard library only |
| jq | 1.7.1 | `tmux-ctl run` (run records) | on `PATH`; recent macOS ships `/usr/bin/jq` |
| git | 2.4x | worktrees, board | needs `rev-parse --path-format` (git 2.31+) |
| Claude Code | 2.1.303 | lead, teammates, workers | `claude` on `PATH`, logged in; needs `--settings`, `--plugin-dir` and agent teams |
| superpowers-extended-cc plugin | 6.5.3 | the skills the rules invoke | optional; without it the lead still runs, but the skill names in its rules point at nothing |

```zsh
brew install tmux ttyd fzf jq
```

## 2. Clone

The repo is private. Authenticate first (`gh auth login`, or use the SSH URL `git@github.com:cisco-trkkn/agent-board.git`).

```zsh
git clone https://github.com/cisco-trkkn/agent-board.git ~/agent-board
cd ~/agent-board
```

Any path works. **The checked-out branch is what runs**: the link points into this clone, so keep it on `main` and do your own changes in a worktree.

## 3. Check the dependencies

```zsh
./install.sh --check
```

It prints `ok <path>` for each dependency it finds and `MISSING <name>` for each it doesn't, and exits 1 if anything is missing. It checks zsh, tmux, ttyd, fzf, python3 (3.9+), jq, git and `claude` (2.1.303+ with `--settings` and `--plugin-dir`). Install what is missing and re-run until nothing says `MISSING`.

## 4. Install

```zsh
./install.sh
```

This links `~/.local/bin/agent-board` to `bin/agent-board` in your clone, and nothing else. Run it again whenever you like: it prints `unchanged` when the link is already right. If `~/.local/bin` isn't on your `PATH` it says so; add it yourself (`export PATH="$HOME/.local/bin:$PATH"` in `~/.zshrc`) and open a new shell.

Safe variants:

| Command | Effect |
| --- | --- |
| `./install.sh --dry-run` | print what would happen, change nothing |
| `./install.sh --force-relink` | repoint the link when it currently points into another checkout (without it, `install.sh` refuses and exits 1) |

If `~/.local/bin/agent-board` exists and is not a link, `install.sh` leaves it alone and exits 1.

## 5. Verify

**agent-board works:**

```zsh
python3 -m unittest discover -s board/tests                  # board
python3 -m unittest discover -s tools/tests -p 'test_*.py'   # the install.sh helpers
zsh tools/tests/run-all.zsh                                  # tmux-ctl, dev layout, hooks
```

All three are safe next to live sessions. The zsh tests start their own tmux server on a private socket with `-f /dev/null` and a temporary state directory.

```zsh
agent-board dev ~/some/git/repo    # session "repo": window claude (the lead), on tmux -L agent-board
agent-board dash                   # starts the board, opens http://127.0.0.1:7700/<token>/
```

The first project session also starts the `overseer` session (a read-only haiku Claude that answers "what is each project doing?"; the board's home page shows it). `TC_OVERSEER=0` in your shell profile turns it off.

On first start in a folder, Claude may ask you to trust it; accept it in the `claude` window. The overseer asks the same once, in its own `overseer:claude` window (its start folder is `~/.local/state/agent-board/overseer`): switch there (`prefix f`, or the board's home page) and accept. The default answer is "No, exit", which leaves the window at a shell; the board retypes the command within a minute, so the dialog returns until you accept it. Teammates spawned in an untrusted folder die silently at that prompt.

Detach with the usual `Ctrl-b d`. agent-board's tmux server uses tmux's default prefix `Ctrl-b`, and your own tmux setup doesn't apply to it. Its key bindings, all after the prefix: `D` opens the project for the current folder, `f` jumps to any window, `W` cleans up agent worktrees, `S` opens a throwaway shell in a popup. For your own prefix, colours or bindings on this server see [CUSTOMIZATION §4](CUSTOMIZATION.md#4-tmux-key-bindings-and-hooks).

**Your own setup is untouched:**

Nothing under `~/.claude` was written by `./install.sh`. In a plain `claude` session started outside agent-board, `/hooks` lists none of the agent-board hooks. In the agent-board lead, `/hooks` lists them.

### Things to know

- **The session `PATH`.** `claude-orchestrator` puts the clone's `bin/` first on `PATH` and also sets it as the `PATH` of the agent-board tmux session (`tmux set-environment`). Workers started by `tmux-ctl agent` get the same `PATH` on their command line. Every window opened in that session afterwards, yours included, finds `tmux-ctl` and the other agent-board commands without a path, and sees the clone's `bin/` ahead of the rest of your `PATH` there. It reaches no other session or server.
- **Teammates.** They get the lead's `--settings` and `--plugin-dir` flags from Claude Code. The tmux session environment carries only `PATH` and `AGENT_BOARD_REPO`, which is why they are set on the session.

### Daily worktree cleanup (optional)

Merged agent worktrees are removed automatically after a merge or pull and when you stop a worker. To also sweep every recent project once a day at 04:00, install the LaunchAgent:

```zsh
cd ~/agent-board                          # the main checkout, not a worktree
agent-board worktrees schedule install    # writes ~/Library/LaunchAgents/com.user.agent-worktree-sweep.plist and loads it
agent-board worktrees schedule status     # state and last exit code, or "not installed"
agent-board worktrees schedule uninstall
```

Run it from `~/agent-board` (the main checkout), not from a worktree: the plist points at the `agent-board` beside the CLI you ran (or at `~/.local/bin/agent-board` when that link exists), and a worktree is the kind of directory the sweep removes. `install` refuses, and writes nothing, when neither is executable. `agent-board worktrees classify` and `sweep --dry-run` show what a sweep would do without removing anything.

### Usage tab statusLine (optional)

The Activity drawer's Usage tab reads context %, model, effort and the 5-hour and weekly plan-limit figures from Claude Code itself when a session runs the agent-board statusLine. Without it the tab falls back to figures re-derived from transcripts. The statusLine is a user-global setting, so the install does not write it; add it to `~/.claude/settings.json` yourself (back the file up first):

```json
"statusLine": {"type": "command", "command": "/Users/<you>/agent-board/claude/statusline/agent-board-statusline", "refreshInterval": 60}
```

Each session's status bar then shows a line like `Haiku 5.5 · ctx 4% · 5h 63%`, and the script stores Claude Code's payload per session in `<state_dir>/statusline/<session_id>.json` (`$TC_STATE`, else `${TMPDIR:-/tmp}/tmux-ctl-<uid>`). It never fails Claude Code: on any error it prints `agent-board` and exits 0. To remove it, delete the `statusLine` key; the stored files are scratch and can be deleted.

`refreshInterval` re-runs the script every 60 s while a session is idle, which keeps the stored payload fresh for the usage-gauges row under the prompt (cleared when the file is older than 5 minutes).

## Migrating from the global setup

Only for a machine that has the author's earlier install: agent-board hooks in `~/.claude/settings.json`, agent-board lines in `~/.tmux.conf`, and links in `~/.local/bin` and `~/.claude`. It is not needed for a fresh machine.

```zsh
./install.sh --migrate --dry-run     # read the plan first; nothing is written
./install.sh --migrate
```

`--migrate` runs the install, then retires the old setup. It changes only what it recognises as agent-board's:

| What | What `--migrate` does |
| --- | --- |
| the four agent-board hooks (`kill-guard.sh`, `bash-mirror.sh`, `artifact-register.sh`, `worktree-sweep.sh`) in `~/.claude/settings.json` | removes those entries, **only if the file round-trips exactly through JSON re-serialisation**. Otherwise it leaves `settings.json` untouched, prints the entries to remove by hand, and exits 1. When it does change the file, it first keeps a backup `settings.json.bak-YYYYMMDD`. Your own hooks, such as `superpowers-hook.sh` registrations, are left alone. |
| agent-board lines in `~/.tmux.conf` | strips the two hooks and the bindings `W`, `f` and `D` (which called tools in `~/.local/bin` that no longer exist). Backup `.tmux.conf.bak-YYYYMMDD` is kept. The rest of your file is left alone. |
| your **running** tmux server | not touched. `--migrate` prints the commands to run, `tmux set-hook -gu after-split-window; tmux set-hook -gu session-closed; tmux unbind W; tmux unbind f; tmux unbind D`, or you can restart tmux. |
| links in `~/.local/bin` (`claude-orchestrator`, `dev`, `tmux-*`, 10 in all) and `~/.claude` (`hooks/{bash-mirror,artifact-register,kill-guard,worktree-sweep}.sh`, `orchestrator.md`, `worker.md`) that point into this clone | removes them. A link that points elsewhere is kept. A link that `settings.json` or `~/.tmux.conf` still names, because that file could not be updated, is kept too. |
| `~/.claude/skills/tmux-orchestrator`, `~/.claude/skills/handoff`, `~/.claude/agents/effort-{low,medium,high}.md` | moves them (never deletes) to `~/.local/state/agent-board/migrated-YYYYMMDD/`, because the agent-board plugin now ships them. A `handoff` that is a real directory rather than a link is kept, with a note. `--keep-agents` leaves the `effort-*` agents in `~/.claude/agents/`. |

Moving the `effort-*` agents means plain `claude` sessions outside agent-board no longer have them; use `--keep-agents` if you rely on them there.

More options: `--migrate-team-settings` also drops `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` and `teammateMode` from `~/.claude/settings.json` (agent-board sets them itself, per session). `--repo DIR` treats `DIR` as the checkout.

**Until you migrate**, the tools keep using your own default tmux server instead of the dedicated `-L agent-board` server: `agent-board dev` and `agent-board dash` do so when `~/.tmux.conf` still contains agent-board's hook lines (`tmux-teammate-window` or `tmux-session-closed`) and no agent-board server is running. Which server that is: with `$TMUX` set (typed inside a tmux pane) they use the server that command was typed in; without it, tmux's default server. After `--migrate` has removed those lines, the next `agent-board dev` starts the dedicated server. Sessions left on your default server stay there; close and reopen them with `agent-board dev`.

## Upgrading

```zsh
cd ~/agent-board && git pull
agent-board dash stop && agent-board dash start     # only needed when board/ changed
```

Scripts, rules and the plugin take effect on their next run. Nothing needs re-linking: a new command in `bin/` is reached through `agent-board <command>` or the `PATH` the session sets.

## Uninstalling

```zsh
agent-board dash stop
./install.sh --uninstall
```

`--uninstall` removes `~/.local/bin/agent-board` if it links into this clone (a link into another checkout, or a plain file, is left alone and reported). Nothing else was installed, so nothing else needs undoing. The dedicated tmux server keeps running until its sessions are closed or you run `tmux -L agent-board kill-server`.

State you may want to delete: `~/.local/state/agent-board/` (ideas and handoffs: keep it if you want them), `~/.local/state/tmux-dash/` (board token, pids, logs) and `${TMPDIR:-/tmp}/tmux-ctl-$UID/` (runtime state).

## Remote access

Reach a dev lead from your phone through a Telegram bot. One bot per project; only leads started by `claude-orchestrator` get the channel.

**Once.** Install Bun (`curl -fsSL https://bun.sh/install | bash`, which puts it at `~/.bun/bin/bun`) and the plugin: `claude plugin install telegram@claude-plugins-official`. Check both with `tmux-ctl telegram status` (`plugin: ok`, `bun: ok`).

**Per project.**

1. Create a bot with BotFather and copy its token.
2. In the project's tmux session, pipe the token in; it is read from stdin, never from an argument, and never printed:

   ```zsh
   print -r -- "<token>" | tmux-ctl telegram token          # inside the project's session
   print -r -- "<token>" | tmux-ctl telegram token --project <name>   # outside tmux
   ```

   It is stored as `~/.local/state/agent-board/telegram/<project>/.env` (mode 600). A project name must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`: a tmux session whose name starts with `_` or holds a space, `:` or non-ASCII characters never opts in (`tmux-ctl telegram` refuses it).
3. Restart the lead (`claude-orchestrator --continue`). A lead with a token starts with `--channels plugin:telegram@claude-plugins-official`; the board shows `tg` on it.
4. DM the bot; it answers with a pairing code. In that lead run `/telegram:access pair <code>`, then `/telegram:access policy allowlist`.
5. `tmux-ctl telegram status` shows `token: set`, `paired: <n> allowlisted`, `policy: allowlist`, `poller: running (pid N)`, `plugin: ok`, `bun: ok`. It never shows the token.

`tmux-ctl telegram forget` removes the project's token (the pairing in `access.json` stays). `TC_TELEGRAM=0` in the environment of `claude-orchestrator` turns the channel off.

**Rules.**

- Never run `/telegram:configure` and never put a token in `~/.claude/channels/telegram/.env`: every session would then poll that bot. `tmux-ctl telegram status` warns when that file exists; delete it.
- One live lead per project. A second lead for the same bot stops the first one's poller, and the first stops receiving. The lead's own Bash commands do not see `TELEGRAM_STATE_DIR` (a plugin hook unsets it for them), so a `claude` started from the lead's Bash tool never polls that lead's bot (hooks and other non-Bash children of the lead still inherit it; none of this repo's hooks starts `claude` from the lead); still, never start a second lead for the same project.
- Sessions without a token connect to a stub (see the launcher below), so `/mcp` shows telegram connected with no tools. On a machine that has not run `claude-orchestrator` since the install they still print `plugin:telegram:telegram … Connection closed`: the stock server exits at once without a token.
- A failed telegram start is cached by Claude Code for 15 minutes, for the whole machine (`~/.claude/mcp-needs-auth-cache.json`, key `plugin:telegram:telegram`). The plugin is enabled in user settings for every session, so a session without a token (a teammate, a worktree, another project) fails and re-arms the cache, and a lead that starts inside the window skips Telegram and stays disconnected. Two things heal it: `claude-orchestrator` removes that one key before it starts a lead that has a token, and the watchdog below reconnects a lead that is already running. A lead whose plugin is "not connected" can always be fixed by hand with `/mcp` → `plugin:telegram:telegram` → Reconnect.
- The plugin cannot be limited to leads: a second `--settings` replaces the first instead of merging, and a lead's `--settings` is copied onto its teammates' command lines. Instead no session fails. `claude-orchestrator` points every installed version of the plugin (`~/.claude/plugins/cache/claude-plugins-official/telegram/<version>/.mcp.json`) at `telegram-mcp-launch`, a copy of `claude/plugin/scripts/telegram-mcp-launch` that runs the real server when a token exists (`TELEGRAM_BOT_TOKEN` in the environment, or in `$TELEGRAM_STATE_DIR/.env`) and `telegram-mcp-stub.js` otherwise: an MCP server that connects, offers no tools and exits when stdin closes. Nothing fails, so nothing is cached. The original `.mcp.json` is saved to `~/.claude/plugin-backups/telegram/<version>/.mcp.json.bak-YYYYMMDD`; a plugin update (a new version directory with the stock launcher) is healed at the next lead start. It runs the real server under node (22.6 or newer, for `--experimental-strip-types`) when node exists, else bun; the helper needs `jq`. `TC_TELEGRAM_LAUNCHER=0` turns the healing off. To heal now without starting a lead: `zsh -c 'source tools/lib/telegram-launch.zsh && tg_ensure_launcher'` from the checkout.

**Watchdog.** `tmux-ctl telegram watch --once` looks at every running `claude` started with `--channels plugin:telegram@claude-plugins-official` and checks that it has a telegram server process (`server.ts`) among its children. When one is missing and the lead's pane is idle at its prompt, it types `/mcp reconnect plugin:telegram:telegram` and Enter (the command Claude Code itself offers; no menu is driven). It types nothing when the pane is busy or in tmux copy mode, when the input line has text, when the input box is not quiet (it takes two captures 3 seconds apart, `TC_TELEGRAM_WATCH_QUIET` seconds, and both must show the lead idle with an empty input line and the same box, so someone typing between them stops it; output elsewhere on the screen, such as a redrawn status line, does not), or when the input line no longer reads back exactly the command just before Enter (then it clears the line and sends no Enter). A reconnect that does not bring the server back is retried after 60 s, 2, 4, 8 ... up to 30 minutes, and the lead gets one macOS banner when that backoff starts; seeing a live server resets it. When it could not type (busy, copy mode, no pane) the banner is limited to one per lead per 15 minutes. It needs neither the board nor `$TMUX`: it finds the lead's pane through the agent-board tmux server and never touches another one. One line per action goes to `~/.local/state/agent-board/telegram-watch.log`.

    tmux-ctl telegram watch install      # writes ~/Library/LaunchAgents/com.user.agent-board-telegram-watch.plist (every 60 s) and loads it
    tmux-ctl telegram watch status       # launchd's state and last exit code
    tmux-ctl telegram watch uninstall

`TC_TELEGRAM_WATCH=0` in the job's environment, or an empty file `~/.local/state/agent-board/telegram-watch.off`, turns it off without unloading it. Leads younger than 45 s are skipped (`TC_TELEGRAM_WATCH_GRACE` seconds), `TC_NOTIFY=0` silences the banner.
- The lead's own permission prompts reach the phone as buttons; the first answer, phone or terminal, wins.
- AskUserQuestion is not relayed: while you are remote, the lead asks as a numbered list in Telegram.
- A teammate's or worker's prompt is approved only on your Telegram reply `approve n` / `deny n`, through `tmux-ctl approve` (the one-time `Yes` or `No` only). Peer sessions are not covered.

**At the office.** Keep the lid open and the Mac on mains power, and run `tmux-ctl awake on`.

**Remote Control** (Claude Code's own phone link) is not an alternative here for now: it is blocked until IT exempts `api.anthropic.com/v1/code/sessions/*` and `bridge.claudeusercontent.com` from the proxy.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `./install.sh --check` prints `MISSING …` | install that tool (see §1) and re-run. For `claude`, upgrade Claude Code to 2.1.303 or newer. |
| `would repoint ~/.local/bin/agent-board … (another checkout; run with --force-relink)` | the link points into a different clone. Re-run with `--force-relink` if you mean to switch. |
| `agent-board: command not found` after install | `~/.local/bin` is not on your `PATH`; add it and open a new shell. |
| `agent-board dash` says `failed to start — see ~/.local/state/tmux-dash/*.log` | `ttyd` is missing (on `PATH`, or `TTYD_BIN`), or port 7700/7701 is taken. Read `ttyd.log` / `server.log`; change ports with `TMUX_DASH_PORT` / `TMUX_DASH_TTYD_PORT`. |
| Board loads but terminals are blank | ttyd not running (`agent-board dash status`), or the board and ttyd look at different tmux servers. `TMUX_DASH_TMUX_ARGS` must be the same for both; `agent-board dash` passes it to both. |
| `tmux-ctl: not inside tmux` | `tmux-ctl` only works from a pane inside tmux. |
| `tmux-ctl run` fails with `jq: command not found` | install jq. |
| Teammates open as split panes, not `✦ name` windows | the `after-split-window` hook is not loaded: you are on a server that doesn't load the config in `config/` (for instance your own default server, see [Migrating](#migrating-from-the-global-setup)). `tmux -L agent-board show-hooks -g` lists it on the right server. |
| A teammate window dies right after it spawns | the folder isn't trusted yet. Run `claude` there once and accept the trust prompt. |
| The lead has no agent team, or `/hooks` shows no agent-board hooks | the Claude was not started by `claude-orchestrator` (or by `tmux-ctl agent`), so it lacks `--settings` and `--plugin-dir`. Restart the lead from the board (Restart orchestrator). |
| `tmux-ctl feed` is empty | the commands came from a Claude that was not started by agent-board. |
| Usage tab says it is indexing, or shows $0 | the first pass over `~/.claude/projects` takes a while on a large history; costs appear as it proceeds. A model missing from `board/prices.json` shows as *unpriced*. |
| `claude-orchestrator: … missing, starting plain claude` | the rules file `claude/orchestrator.md` is missing from the clone (or a `~/.config/agent-board/orchestrator.md` override is unreadable). |

## Linux notes

Untested. Known differences:

- `agent-board dash` with no argument calls macOS `open`. Run `agent-board dash start` and open the printed URL.
- `${TMPDIR}` is usually unset on Linux, so runtime state goes to `/tmp/tmux-ctl-$UID/`.
