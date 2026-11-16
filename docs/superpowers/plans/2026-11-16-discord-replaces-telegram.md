# Discord Replaces Telegram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Discord the lead's only remote channel: auto-add, no-token stub, env scrub, second-lead guard, access commands, watchdog, board badge and docs. Delete Telegram.

**Architecture:** This is a port of each Telegram piece to a Discord-specific twin, with no generic channel layer. `bin/claude-orchestrator` opts a lead in when `${TC_STATE:-~/.local/state/agent-board}/discord/<project>/.env` holds a token and no other live lead holds that bot. It merges the caller's `--channels` entries into one list (idea 132). Then the Telegram files, tests and branches are deleted.

**Tech Stack:** zsh (bin/, tools/lib/, tests via `tools/tests/lib.zsh`), Python 3 (watchdog, cache, board), Node/Bun (MCP stub), jq, launchd.

**Spec:** `docs/superpowers/specs/2026-11-11-discord-replaces-telegram-design.md`. Every executor reads it; section numbers (§n) below refer to it.

## Global Constraints

- `<project>` = the pane's session group, else its session name; a `-bg` session (`@tc_bg` set) maps to its project by dropping `-bg`. This is today's `TG_PROJECT` rule in `bin/claude-orchestrator`.
- `<dir>` = `${TC_STATE:-$HOME/.local/state/agent-board}/discord/<project>`. "Has a token" means `<dir>/.env` holds a line `DISCORD_BOT_TOKEN=<non-empty>`. Exactly one definition: `discord-mcp-launch --has-token <dir>`.
- Channel value: `plugin:discord@claude-plugins-official`. MCP server name: `plugin:discord:discord`. Probe: this session's tools are named `mcp__plugin_discord_discord__reply`, and the Telegram key followed the same pattern, `plugin:telegram:telegram`.
- The stock server command (probe: `~/.claude/plugins/cache/claude-plugins-official/discord/0.0.4/.mcp.json`) is `bun run --cwd ${CLAUDE_PLUGIN_ROOT} --shell=bun --silent start`, and `package.json` `start` = `bun install --no-summary && bun server.ts`. The real server runs on bun. There is no node switch.
- Nothing may stop a lead from launching. The launcher heal, cache clear, guard and migrate each print at most one line and go on.
- Tokens are never printed, never taken from argv, and never written to a log. Secret checks use `[ -n "$T" ]` only.
- Tests run against a scratch `CLAUDE_CONFIG_DIR`, `TC_STATE` and `HOME` (`tt_setup` in `tools/tests/lib.zsh`), never the real ones. `launchctl` and `claude` are fakes on PATH wherever a test reaches them. Each zsh test keeps the real-LaunchAgents leak check (`ls ~/Library/LaunchAgents | grep -c agent-board-discord-watch`, before = after).
- Teammates share one worktree. Each one stages only its own paths (`git add <paths>`) and runs no whole-tree git command.
- Conventional commits with scope (`feat(discord): …`, `test(discord): …`, `chore(telegram): …`). End each commit with the attribution trailer your harness specifies.
- **Ruling (idea 132 parse):** the caller's `--channels` entries are the arguments that follow it and match `(plugin|server):*`. They end at the first argument that does not match. Claude Code rejects untagged entries ("--channels entries must be tagged"), so a trailing positional prompt is never taken as an entry. This is stricter than the spec's "until the next argument starting with `-`", which would swallow `agent-board lead --channels plugin:x "fix it"`.
- **Ruling (holder probe):** `ps -E -o command= -p <pid>` shows the environment on this macOS. The probe was run on 2026-11-16 against the real discord server pid of this lead and printed `DISCORD_STATE_DIR=/Users/…/discord/agent-board` and `TMUX_PANE=%8`. So the guard reads the environment, and needs no `lead.pid` fallback.

**User decisions (already made):** delete Telegram outright, with no opt-in path; one Discord bot per project; Discord-specific code, no generic layer; Telegram token dirs are user data and code never deletes them; finishing runs `tmux-ctl discord migrate` once on this machine (approved); queue integration is merge to `main`, with no push.

---

### Task 1: Discord launcher, stub and failure-cache clear

**Goal:** Port the Telegram launcher trio and cache helper so a session without a token connects to a stub instead of failing (spec §3 and the §2 cache clear).

**Files:**
- Create: `claude/plugin/scripts/discord-mcp-launch`, `claude/plugin/scripts/discord-mcp-stub.js`, `tools/lib/discord-launch.zsh`, `tools/discord_cache.py`
- Test: `tools/tests/test_discord_launcher.zsh` (port of `test_telegram_launcher.zsh`), `tools/tests/test_discord_cache.zsh` (port of part 2a of `test_telegram_always_on.zsh`, the helper checks)

**Acceptance Criteria:**
- [ ] `discord-mcp-launch --has-token <dir>` exits 0 only when `<dir>/.env` has `DISCORD_BOT_TOKEN=<non-empty>`. Mutation: drop the `.` from the grep pattern, and the "empty token value" case fails.
- [ ] `discord-mcp-launch <root>` with a token (env `DISCORD_BOT_TOKEN`, or the `.env` in `${DISCORD_STATE_DIR:-${CLAUDE_CONFIG_DIR:-~/.claude}/channels/discord}`) execs `bun run --cwd <root> --shell=bun --silent start`. Without a token it execs `node <root>/discord-mcp-stub.js`, and `bun` when node is missing. Tests use a fake `bun`/`node` on PATH that records argv.
- [ ] The stub answers `initialize` (serverInfo name `discord-stub`), lists no tools and exits when stdin closes.
- [ ] `dc_ensure_launcher` gives every `<config>/plugins/cache/claude-plugins-official/discord/<version>/` the same contract as `tg_ensure_launcher`. Its `.mcp.json` server key is `discord`, and the backup goes to `<config>/plugin-backups/discord/<version>/.mcp.json.bak-YYYYMMDD`. It is idempotent (a second run prints nothing) and heals a new version dir. `TC_DISCORD_LAUNCHER=0` turns it off. Every error prints one line and returns 0.
- [ ] `python3 tools/discord_cache.py clear` removes only the key `plugin:discord:discord` and keeps other keys byte-identical. It leaves no temp file and exits 0 on a missing file or bad JSON.

**Verify:** `zsh tools/tests/test_discord_launcher.zsh && zsh tools/tests/test_discord_cache.zsh` → each ends `ALL PASS`

**Steps:**
- [ ] Port each file from its Telegram twin (`telegram-mcp-launch`, `telegram-mcp-stub.js`, `tools/lib/telegram-launch.zsh`, `tools/telegram_cache.py`). The differences that change behaviour are these, and the list is complete: env and var names `TELEGRAM_*` → `DISCORD_*`; function prefix `tg_`/`_tgl_` → `dc_`/`_dcl_`; with a token the launcher always runs the stock bun command (drop the node `server.ts` branch); cache `KEY = "plugin:discord:discord"`; messages say `discord:`.
- [ ] Port the tests case for case, RED first (scripts missing), then GREEN. Commit: `feat(discord): no-token stub launcher and failure-cache clear`.

```json:metadata
{"files": ["claude/plugin/scripts/discord-mcp-launch", "claude/plugin/scripts/discord-mcp-stub.js", "tools/lib/discord-launch.zsh", "tools/discord_cache.py", "tools/tests/test_discord_launcher.zsh", "tools/tests/test_discord_cache.zsh"], "verifyCommand": "zsh tools/tests/test_discord_launcher.zsh && zsh tools/tests/test_discord_cache.zsh", "acceptanceCriteria": ["--has-token exits 0 only for a non-empty DISCORD_BOT_TOKEN line", "token -> stock bun start; no token -> node stub, bun fallback", "stub answers initialize, lists no tools, exits on stdin close", "dc_ensure_launcher: tg contract, discord key, backup path, idempotent, heals new version, TC_DISCORD_LAUNCHER=0, fail-open", "discord_cache.py clear removes only plugin:discord:discord"], "modelTier": "standard"}
```

### Task 2: `tmux-ctl discord` access commands and status

**Goal:** Add `tools/lib/discord.zsh` with `token`, `pair`, `deny`, `policy`, `allow`, `remove`, `forget` and `status`, and wire `tmux-ctl discord …` into `bin/tmux-ctl` so it works outside tmux with `--project` (spec §6).

**Files:**
- Create: `tools/lib/discord.zsh`
- Modify: `bin/tmux-ctl` (help lines next to the telegram ones; the not-in-tmux exemption at line 84 also accepts `discord`; a dispatch block like lines 279-281 that sources `tools/lib/discord.zsh` and calls `discord_cmd`). Leave the telegram lines alone: Task 9 removes them.
- Test: `tools/tests/test_ctl_discord.zsh` (port of `test_ctl_telegram.zsh`, plus one case per new row)

**Acceptance Criteria:**
- [ ] `token`: reads stdin only (`read -rs` when it is a tty), requires a non-empty single-line value, writes `<dir>/.env` mode 600 through `.env.next` (dir mode 700), and never prints the token. It sets `ackReaction: "👀"` in `access.json` only when the key is absent (an existing `""` is kept), and creates the default file `{"dmPolicy":"pairing","allowFrom":[],"groups":{},"pending":{}}` when missing. Last line: `discord: token saved for <project> (restart its lead: agent-board lead --continue, or Restart orchestrator on the board)`. Test: output and stderr do not contain the token string.
- [ ] `pair <code>`: a code missing from `pending`, or with `expiresAt < now(ms)`, exits 1. Otherwise it adds `senderId` to `allowFrom` (dedupe), deletes `pending[code]`, and writes `<dir>/approved/<senderId>` containing `chatId`. `deny <code>` deletes it, and an unknown code exits 1.
- [ ] `policy pairing|allowlist|disabled`, and any other value prints usage and exits 2. `allow <id>` / `remove <id>` edit `allowFrom`. `forget` deletes `.env` and keeps `access.json`.
- [ ] Every write reads the live file, changes it with `jq`, writes `access.json.next` (mode 600, 2-space indent) and `mv`s it over. Keys it does not touch are kept: a test seeds an extra key `"groups":{"g":{"x":1}}` and checks it survives each write command.
- [ ] Missing `jq` → exit 1 with `discord: jq not found`. Unreadable/invalid `access.json` → exit 1, file unchanged (byte-compare).
- [ ] An argument that looks like a token, or more than one positional, is refused without echoing it. A project name that does not match `^[A-Za-z0-9][A-Za-z0-9._-]*$` exits 2 without echoing it.
- [ ] `status` prints these lines in order: `token: set|missing`, `paired: <n> allowlisted|none`, `policy: <mode>`, `ack reaction: 👀|off`, `held by: nobody` (Task 3 fills the real value), `plugin: ok|missing` (from `${CLAUDE_CONFIG_DIR:-~/.claude}/plugins/installed_plugins.json` `.plugins` has `discord@claude-plugins-official`), `launcher: ok|drift` (every installed version's `.mcp.json` server is the launcher), `watch: loaded|not loaded` (fake `launchctl print` exit code).
- [ ] `tmux-ctl discord status --project p` works with `TMUX` unset.

**Verify:** `zsh tools/tests/test_ctl_discord.zsh` → `ALL PASS`

**Steps:**
- [ ] Port `tools/lib/telegram.zsh` → `tools/lib/discord.zsh` (`discord_cmd`, `_dc_*`). Differences: the token regex is now any non-empty single line without spaces (Discord tokens are `<base64>.<…>.<…>`); the token-shaped-argument test refuses any positional that holds a `.` and is 50 or more characters, since Discord tokens are around 70; the new rows and the access writes are new code, using `jq` as in the snippet below; `status` replaces `poller`/`bun` with the rows above; there is no `~/.claude/channels/telegram/.env` warning, and a `~/.claude/channels/discord/.env` warning takes its place (same wording, discord paths).
- [ ] Shape of an access write (non-obvious pattern):

```zsh
_dc_write() {   # _dc_write <dir> <jq filter> [jq args…]: read live, transform, .next (600), mv
  local dir="$1" f="$2"; shift 2
  local live="$dir/access.json"
  [[ -e "$live" ]] || { umask 077; print -r -- '{"dmPolicy":"pairing","allowFrom":[],"groups":{},"pending":{}}' > "$live" }
  jq -e . "$live" >/dev/null 2>&1 || { print -u2 "discord: $live is not readable JSON; left as is"; return 1 }
  ( umask 077; jq --indent 2 "$@" "$f" "$live" > "$live.next" ) && chmod 600 "$live.next" && mv -f "$live.next" "$live" \
    || { rm -f "$live.next"; print -u2 "discord: could not write $live"; return 1 }
}
# pair: _dc_write "$dir" '.allowFrom = ((.allowFrom // []) + [$s] | unique) | del(.pending[$c])' --arg s "$sid" --arg c "$code"
```

- [ ] RED, then GREEN. Commit `feat(discord): tmux-ctl discord access commands and status`.

```json:metadata
{"files": ["tools/lib/discord.zsh", "bin/tmux-ctl", "tools/tests/test_ctl_discord.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_discord.zsh", "acceptanceCriteria": ["token from stdin, .env 600 via .next, ackReaction set only when absent, default access.json, never printed", "pair/deny with expiry and approved/<senderId>", "policy/allow/remove/forget", "atomic jq writes keep other keys", "jq missing and bad access.json exit 1 unchanged", "token-shaped args and bad project names refused without echo", "status lines in order", "works outside tmux with --project"], "modelTier": "standard"}
```

### Task 3: Second-lead guard helper and `tmux-ctl discord migrate`

**Goal:** Add `dc_holder <dir>` (spec §4) and `discord migrate` (spec §1 machine cleanup) to `tools/lib/discord.zsh`, and make `status` print the real `held by:` line.

**Files:**
- Modify: `tools/lib/discord.zsh`
- Test: `tools/tests/test_discord_holder.zsh`, `tools/tests/test_discord_migrate.zsh`

**Acceptance Criteria:**
- [ ] `dc_holder <dir>` prints `<claude pid> <pane id>` for a **live** holder and prints nothing otherwise. A holder process is one whose command is the discord server (the args contain `/discord/` and match `bun run --cwd … start`, or `bun server.ts` with cwd under a `discord/<version>` dir, or `discord-mcp-launch`) and whose `ps -E` environment has `DISCORD_STATE_DIR=<dir>`, compared exactly with no prefix match (`…/discord/p` is not held by `…/discord/p2`). The holder is live when its parent chain reaches a process named `claude` whose parent is not 1. The pane id is that claude's `TMUX_PANE` from `ps -E`, or `-` when absent.
- [ ] Tests build real process trees (a fake `claude` script in a scratch dir that starts a child via `env DISCORD_STATE_DIR=<dir> TMUX_PANE=%99 <fake server command>`). They cover these cases: live holder → `<pid> %99`; orphaned holder (claude parent killed, so the child is re-parented to 1) → nothing; other dir → nothing; no holder → nothing. Every spawned pid is killed in a `trap` and checked gone with `ps` at the end. Mutation: drop the parent-is-not-1 check, and the orphan case fails.
- [ ] `status` prints `held by: <session>:<window> pid <n>`, resolving the pane through tmux `display -p -t <pane> '#{session_name}:#{window_name}'`. It prints `held by: another process pid <n>` when no pane matches, and `held by: nobody` when there is no holder.
- [ ] `migrate` uses fake `launchctl` and `claude` on PATH and a scratch HOME. It runs `launchctl bootout gui/$UID/com.user.agent-board-telegram-watch` and deletes `$HOME/Library/LaunchAgents/com.user.agent-board-telegram-watch.plist`. It runs `claude plugin disable telegram@claude-plugins-official`, and prints `telegram: token dirs kept in <path> (delete them by hand when done)` when `${TC_STATE:-~/.local/state/agent-board}/telegram` exists. It prints one line per action, exits 0 when every piece is already gone, and a second run is idempotent (exit 0, no error lines).

**Verify:** `zsh tools/tests/test_discord_holder.zsh && zsh tools/tests/test_discord_migrate.zsh` → each `ALL PASS`

**Steps:**
- [ ] Implement `dc_holder` with one `ps -A -o pid=,ppid=,args=` table, plus `ps -E -o command= -p <pid>` only for candidate pids. Walk the ppid chain using the table.
- [ ] Implement `_dc_migrate` and wire `migrate` into `discord_cmd`. It needs no project.
- [ ] RED, then GREEN. Commit `feat(discord): second-lead guard helper and migrate`.

```json:metadata
{"files": ["tools/lib/discord.zsh", "tools/tests/test_discord_holder.zsh", "tools/tests/test_discord_migrate.zsh"], "verifyCommand": "zsh tools/tests/test_discord_holder.zsh && zsh tools/tests/test_discord_migrate.zsh", "acceptanceCriteria": ["dc_holder prints '<claude pid> <pane>' only for a live holder with exact DISCORD_STATE_DIR", "real process-tree tests: live, orphan, other dir, none; pids reaped", "status held by line", "migrate: bootout, plist delete, plugin disable, token-dir notice, idempotent, exit 0"], "modelTier": "standard"}
```

### Task 4: Discord env scrub hook

**Goal:** Replace `telegram-env-scrub.sh` with `discord-env-scrub.sh`, so a lead's Bash shells never see `DISCORD_STATE_DIR` or `DISCORD_BOT_TOKEN` (spec §5).

**Files:**
- Create: `claude/plugin/scripts/discord-env-scrub.sh`
- Modify: `claude/plugin/hooks/hooks.json:8` (the telegram entry becomes the discord one)
- Test: `claude/hooks/tests/test-discord-env-scrub.sh` (port of `test-telegram-env-scrub.sh`)

**Acceptance Criteria:**
- [ ] With `AGENT_BOARD_LEAD=1`, `DISCORD_STATE_DIR` set and `CLAUDE_ENV_FILE` set, it appends exactly one line `unset DISCORD_STATE_DIR DISCORD_BOT_TOKEN`. A second run adds nothing. Mutation: remove the `grep -qxF` guard, and the "once" case fails.
- [ ] Without the lead marker or without `DISCORD_STATE_DIR` it writes nothing. It prints nothing and exits 0 always.
- [ ] `hooks.json` is valid JSON (`jq . claude/plugin/hooks/hooks.json`). No `telegram-env-scrub` entry remains in it.

**Verify:** `bash claude/hooks/tests/test-discord-env-scrub.sh && jq -e '[..|.command? // empty|select(test("discord-env-scrub"))]|length==1' claude/plugin/hooks/hooks.json` → test passes and jq prints `true`

**Steps:**
- [ ] Write the script:

```bash
#!/usr/bin/env bash
# SessionStart: in a dev lead that has a Discord state dir, make the lead's Bash-tool shells forget DISCORD_STATE_DIR and
# DISCORD_BOT_TOKEN. bin/claude-orchestrator exports the state dir in the lead's own process so the plugin's MCP server finds
# the bot; without this, a `claude` started from the lead's shell would open a second gateway session on the same bot.
# Claude Code sources $CLAUDE_ENV_FILE before each Bash command, so an appended `unset` reaches those shells only.
# --scoped (the plugin registration) is accepted and changes nothing. Appends once. Prints nothing. Fail-open.
cat >/dev/null 2>&1
[[ "$AGENT_BOARD_LEAD" == 1 && -n "$DISCORD_STATE_DIR" && -n "$CLAUDE_ENV_FILE" ]] || exit 0
line='unset DISCORD_STATE_DIR DISCORD_BOT_TOKEN'
grep -qxF "$line" "$CLAUDE_ENV_FILE" 2>/dev/null && exit 0
printf '%s\n' "$line" >> "$CLAUDE_ENV_FILE" 2>/dev/null
exit 0
```

- [ ] `chmod 755`. In `hooks.json` replace `telegram-env-scrub.sh` with `discord-env-scrub.sh` on that one line.
- [ ] Port the test (rename the variables and expected line), RED (script absent) then GREEN. Commit `feat(discord): env scrub hook replaces the telegram one`.

```json:metadata
{"files": ["claude/plugin/scripts/discord-env-scrub.sh", "claude/plugin/hooks/hooks.json", "claude/hooks/tests/test-discord-env-scrub.sh"], "verifyCommand": "bash claude/hooks/tests/test-discord-env-scrub.sh && jq -e '[..|.command? // empty|select(test(\"discord-env-scrub\"))]|length==1' claude/plugin/hooks/hooks.json", "acceptanceCriteria": ["appends 'unset DISCORD_STATE_DIR DISCORD_BOT_TOKEN' once in a lead with a state dir", "writes nothing otherwise, prints nothing, exit 0", "hooks.json valid, discord entry, no telegram entry"], "modelTier": "mechanical"}
```

### Task 5: Lead launch with Discord, `--channels` merge and `agent-board lead`

**Goal:** Replace the Telegram block in `bin/claude-orchestrator` with the Discord opt-in, the second-lead guard, the cache clear, `dc_ensure_launcher` and the idea-132 `--channels` merge. Add `agent-board lead` (spec §2).

**Files:**
- Modify: `bin/claude-orchestrator`, `bin/agent-board`
- Test: `tools/tests/test_claude_orchestrator_dc.zsh` (port of `test_claude_orchestrator_tg.zsh`), `tools/tests/test_discord_always_on.zsh` (port of the launcher/cache-on-launch parts of `test_telegram_always_on.zsh`)

**Acceptance Criteria:**
- [ ] `unset DISCORD_STATE_DIR TELEGRAM_STATE_DIR` always runs. With `TC_DISCORD` not `0`, `$TMUX`/`$TMUX_PANE` set, a resolvable `<project>`, `--has-token <dir>` passing and `dc_holder <dir>` printing nothing (or printing this `$TMUX_PANE`, which marks a stale holder), the script exports `DISCORD_STATE_DIR=<dir>` (in this process only, not in the tmux session env) and the channel list includes `plugin:discord@claude-plugins-official`.
- [ ] With a live holder in another pane, there is no channel and no state dir, and exactly one stderr line: `discord: <project>'s bot is held by the lead in <session>:<window> (pid <claude pid>); this lead starts without it`, or `… held by another process (pid <n>) …` when no pane matches. The test uses a real fake-holder process tree like Task 3's.
- [ ] Idea 132: the caller's `--channels a b` / `--channels=a` entries (Ruling: tagged `(plugin|server):*` only) are taken out of `"$@"` and merged with the auto entry, deduped. Exactly one `--channels` is passed, right before `AB_ARGS`. Tests: `--channels plugin:x "do it"` → argv has one `--channels`, `plugin:x` and the discord entry follow it, and `do it` is the last argv element; `--channels plugin:discord@claude-plugins-official` with a token → the entry appears once; `--channels=plugin:x --continue` → `--continue` is kept, one `--channels`. Mutation: put the channel args after `"$@"`, and the trailing-prompt case fails.
- [ ] Not in tmux with `TC_DISCORD` not `0`: one stderr line `agent-board lead: not in tmux, so no Discord channel`, and no channel.
- [ ] `TC_DISCORD=0`, no token, `.env` with an empty value, and an inherited `DISCORD_STATE_DIR`: each gives no channel and the state dir unset. A `-bg` session maps to its project.
- [ ] `python3 tools/discord_cache.py clear` runs only when the discord channel was added. `dc_ensure_launcher` runs on every start. A failing helper (a stub that exits 3) still execs claude.
- [ ] `~/.bun/bin` is still prepended to PATH (comment now says the Discord plugin).
- [ ] `agent-board lead --continue` execs `claude-orchestrator --continue`, and `agent-board help` lists `agent-board lead [args]  start a dev lead (claude-orchestrator) in this pane`.

**Verify:** `zsh tools/tests/test_claude_orchestrator_dc.zsh && zsh tools/tests/test_discord_always_on.zsh` → each `ALL PASS`

**Steps:**
- [ ] The `--channels` extraction (non-obvious; script top level, so no `local`):

```zsh
CH=() REST=()
while (( $# )); do
  case "$1" in
    --channels=*) CH+=("${1#--channels=}"); shift ;;
    --channels) shift; while (( $# )) && [[ "$1" == (plugin|server):* ]]; do CH+=("$1"); shift; done ;;
    *) REST+=("$1"); shift ;;
  esac
done
set -- "${REST[@]}"
# … auto-add: CH+=(plugin:discord@claude-plugins-official) when opted in …
CH=("${(@u)CH}")
CH_ARGS=(); (( ${#CH} )) && CH_ARGS=(--channels "${CH[@]}")
# exec claude "${MODEL_ARGS[@]}" "${CH_ARGS[@]}" "${AB_ARGS[@]}" --append-system-prompt-file "$PROMPT_FILE" "$@"
```

- [ ] The guard calls `dc_holder` from `tools/lib/discord.zsh` (sourced, wrapped so a failure is "no holder").
- [ ] Port the tests, RED then GREEN. Commit `feat(discord): lead opts into Discord; one --channels list; agent-board lead`.

```json:metadata
{"files": ["bin/claude-orchestrator", "bin/agent-board", "tools/tests/test_claude_orchestrator_dc.zsh", "tools/tests/test_discord_always_on.zsh"], "verifyCommand": "zsh tools/tests/test_claude_orchestrator_dc.zsh && zsh tools/tests/test_discord_always_on.zsh", "acceptanceCriteria": ["opt-in exports DISCORD_STATE_DIR in-process and adds the channel", "live holder elsewhere: no channel, one stderr line", "idea 132: one --channels list before AB_ARGS, tagged entries only, deduped, trailing prompt last", "not in tmux: one stderr line", "TC_DISCORD=0 / no token / empty token / inherited dir / -bg cases", "cache clear only on opt-in, ensure_launcher always, failures never block exec", "bun PATH kept", "agent-board lead + help line"], "modelTier": "standard"}
```

### Task 6: Discord watchdog

**Goal:** Port `tools/telegram_watch.py` (as on `main` at ef73bd8, which includes the spinner-rule changes) to `tools/discord_watch.py` with its fixtures and tests (spec §7), and wire `tmux-ctl discord watch …`.

**Files:**
- Create: `tools/discord_watch.py`, `tools/tests/test_discord_watch.py`
- Move: `git mv tools/tests/fixtures/telegram-watch tools/tests/fixtures/discord-watch`
- Modify: `tools/tests/fixtures/fake_claude_tui.zsh`, `fake_claude_tui_broken.zsh` (discord names), `board/tests/test_paneclass.py:136,143` (fixture path), `tools/lib/discord.zsh` (a `watch` branch like telegram.zsh's, calling `discord_watch.py`, shared with Tasks 2-3; this task runs after them)

**Acceptance Criteria:**
- [ ] `CHANNEL = "plugin:discord@claude-plugins-official"`, `COMMAND = "/mcp reconnect plugin:discord:discord"`. The server-present check matches Task 3's discord server commands, and `BUN_START` is dropped. State/log go to `${TC_STATE}/discord-watch.{json,log}`. It is off with `TC_DISCORD_WATCH=0` or `discord-watch.off`. The env knobs are renamed `TC_DISCORD_WATCH_QUIET` and `TC_DISCORD_WATCH_GRACE`. The launchd label is `com.user.agent-board-discord-watch`, ProgramArguments `[cli, "discord", "watch", "--once"]`, every 60 s. Banners say Discord.
- [ ] `test_discord_watch.py` keeps every case of `test_telegram_watch.py`. Each test method name maps one to one, checked by `diff <(grep -o 'def test_[a-z0-9_]*' tools/tests/test_telegram_watch.py | sort) <(grep -o 'def test_[a-z0-9_]*' tools/tests/test_discord_watch.py | sort)` printing nothing (method names that contain `telegram` are renamed to `discord`; the diff runs after `sed s/telegram/discord/` on the left side).
- [ ] Fixtures that show the Telegram server name in `/mcp` text are edited to `plugin:discord:discord`. The fixtures README lists which files were edited rather than re-captured.
- [ ] `python3 -m unittest board.tests.test_paneclass` passes with the moved fixture path.
- [ ] `tmux-ctl discord watch --once` runs the watchdog once.

**Verify:** `python3 -m unittest discover -s tools/tests -p 'test_discord_watch.py' && python3 -m unittest board.tests.test_paneclass` → `OK` twice

**Steps:**
- [ ] `git mv` the fixtures first. Copy the watcher and test, then apply the renames above. `grep -ni telegram tools/discord_watch.py tools/tests/test_discord_watch.py tools/tests/fixtures/discord-watch` must print nothing.
- [ ] Run the ported tests, fix, commit `feat(discord): reconnect watchdog`.

```json:metadata
{"files": ["tools/discord_watch.py", "tools/tests/test_discord_watch.py", "tools/tests/fixtures/discord-watch/", "tools/tests/fixtures/fake_claude_tui.zsh", "tools/tests/fixtures/fake_claude_tui_broken.zsh", "board/tests/test_paneclass.py", "tools/lib/discord.zsh"], "verifyCommand": "python3 -m unittest discover -s tools/tests -p 'test_discord_watch.py' && python3 -m unittest board.tests.test_paneclass", "acceptanceCriteria": ["discord channel/command/server match/state/label/knobs", "every telegram watch test ported (name diff empty)", "fixtures moved and edited, README says which", "paneclass test passes with moved fixtures", "tmux-ctl discord watch --once"], "modelTier": "standard"}
```

### Task 7: Board `dc` badge

**Goal:** The board marks a lead running the Discord channel (spec §8).

**Files:**
- Modify: `board/server.py:288-371` (`TG_FLAG` → `DC_FLAG`, `telegram_leads` → `discord_leads`, pane key `telegram` → `discord`), `board/index.html:573`
- Test: `board/tests/test_discord_badge.py` (port of `test_telegram_badge.py`, plus one case)

**Acceptance Criteria:**
- [ ] A pane whose process tree has a claude whose argv contains `plugin:discord@claude-plugins-official` as any entry of a `--channels` list gets `"discord": true`. This includes `--channels plugin:x plugin:discord@claude-plugins-official` and `--channels=plugin:discord@…`. Every other pane gets `"discord": false`. Mutation: match only `--channels plugin:discord` as a substring, and the two-entry case fails.
- [ ] `index.html` shows badge text `dc`, class `alert-badge dc`, title `Discord channel on (delivery not checked by the board)`. `grep -c telegram board/server.py board/index.html` → 0 each.

**Verify:** `python3 -m unittest board.tests.test_discord_badge` → `OK`

**Steps:**
- [ ] Matching rule: split the args on whitespace, and set the flag when a token equals `plugin:discord@claude-plugins-official` or `--channels=plugin:discord@claude-plugins-official` and a `--channels` token appears before it. Port the test. Commit `feat(board): dc badge for the Discord channel`.

```json:metadata
{"files": ["board/server.py", "board/index.html", "board/tests/test_discord_badge.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_badge", "acceptanceCriteria": ["discord flag for any channel-list position", "dc badge text/class/title", "no telegram left in server.py/index.html"], "modelTier": "standard"}
```

### Task 8: Lead rules and docs move to Discord

**Goal:** Rewrite the remote-channel rules and docs for Discord (spec §9).

**Files:**
- Modify: `claude/orchestrator.md` (§ "Remote: Telegram" → "Remote: Discord", and every other Telegram mention), `docs/INSTALL.md` (§ Remote access), `tools/tests/e2e-remote-access.md`, `README.md`, `tools/tests/lib.zsh:19` (comment only)

**Acceptance Criteria:**
- [ ] `orchestrator.md`: the channel tag is `<channel source="discord" …>`, the `reply` tool is the Discord plugin's, and the approval protocol is unchanged in substance (same steps 1–5, `tmux-ctl approve … --expect`). New lines: replies over 2000 characters are split by the plugin (`textChunkLimit`), so keep replies short; a lead never runs `tmux-ctl discord pair|deny|policy|allow|remove` or `/discord:access`, because access changes are the user's, typed in a terminal.
- [ ] `INSTALL.md` § Remote access covers these steps for Discord: create the app and bot; Message Content Intent; invite to a private server; `tmux-ctl discord token`; DM the bot; `tmux-ctl discord pair <code>`; `tmux-ctl discord policy allowlist`; the `status` lines exactly as Task 2/3 print them; the watchdog (`discord watch install|status|uninstall`, knobs `TC_DISCORD_WATCH*`); the failure cache (`plugin:discord:discord`) and stub launcher notes; one live lead per project (the guard); `tmux-ctl discord migrate` for a machine that ran Telegram; `TC_DISCORD=0`.
- [ ] `e2e-remote-access.md` holds the same manual steps for Discord. README and the lib.zsh comment say Discord.
- [ ] `grep -ni telegram claude/orchestrator.md docs/INSTALL.md tools/tests/e2e-remote-access.md README.md tools/tests/lib.zsh` prints only `docs/INSTALL.md` lines, all of them inside the migrate paragraph, which names Telegram as the thing being removed.

**Verify:** `grep -ci telegram claude/orchestrator.md README.md tools/tests/e2e-remote-access.md tools/tests/lib.zsh docs/INSTALL.md` → `0` for each file except `docs/INSTALL.md` (its count = the migrate paragraph's lines that mention Telegram)

**Steps:**
- [ ] Read the spec §6–§9 and Tasks 2, 3, 5 and 6 as merged in the worktree (`git log`), so each documented command and line matches the code. Commit `docs(discord): lead rules, install and e2e steps for Discord`.

```json:metadata
{"files": ["claude/orchestrator.md", "docs/INSTALL.md", "tools/tests/e2e-remote-access.md", "README.md", "tools/tests/lib.zsh"], "verifyCommand": "grep -ci telegram claude/orchestrator.md README.md tools/tests/e2e-remote-access.md tools/tests/lib.zsh docs/INSTALL.md", "acceptanceCriteria": ["orchestrator.md Remote: Discord with the two new rules", "INSTALL.md remote access rewritten for Discord", "e2e steps, README, lib.zsh comment", "no telegram except the migrate line"], "modelTier": "standard"}
```

### Task 9: Delete Telegram

**Goal:** Remove every Telegram file, branch and test (spec §1). Mark the old Telegram specs and plans superseded.

**Files:**
- Delete (`git rm`): `tools/lib/telegram.zsh`, `tools/lib/telegram-launch.zsh`, `tools/telegram_watch.py`, `tools/telegram_cache.py`, `claude/plugin/scripts/telegram-mcp-launch`, `claude/plugin/scripts/telegram-mcp-stub.js`, `claude/plugin/scripts/telegram-env-scrub.sh`, `tools/tests/test_ctl_telegram.zsh`, `tools/tests/test_telegram_always_on.zsh`, `tools/tests/test_telegram_launcher.zsh`, `tools/tests/test_claude_orchestrator_tg.zsh`, `tools/tests/test_telegram_watch.py`, `claude/hooks/tests/test-telegram-env-scrub.sh`, `board/tests/test_telegram_badge.py`
- Modify: `bin/tmux-ctl` (telegram help lines, the `telegram` exemption, the dispatch block), `tools/tests/test_ctl_approve_misc.zsh:56` (the check becomes `help: discord line kept` grepping `tmux-ctl discord`)
- Modify (one line added at the top of each): `docs/superpowers/specs/2026-11-09-remote-access-design.md`, `docs/superpowers/specs/2026-11-10-telegram-fixes-design.md`, `docs/superpowers/specs/2026-11-10-telegram-one-lead-tasks-design.md`, `docs/superpowers/plans/2026-11-09-remote-access.md`: `Superseded by 2026-11-11-discord-replaces-telegram-design.md`

**Acceptance Criteria:**
- [ ] The listed files are gone, and `board/tests/fixtures/metrics/remote-access-*` is untouched (`git diff --stat main -- board/tests/fixtures/metrics` is empty).
- [ ] `grep -rnil telegram . --exclude-dir=.git | grep -v '^./docs/superpowers/' | grep -v '^./board/tests/fixtures/metrics/' | sort` prints exactly the allowed set and nothing else. The allowed set names Telegram only as the thing being removed: `./bin/claude-orchestrator` (the `unset … TELEGRAM_STATE_DIR`), `./docs/INSTALL.md` (the migrate paragraph), `./tools/lib/discord.zsh` (migrate), `./tools/tests/test_claude_orchestrator_dc.zsh` (the inherited-`TELEGRAM_STATE_DIR` case, if present) and `./tools/tests/test_discord_migrate.zsh`. **Ruling:** the spec's "returns nothing" cannot hold while `migrate` exists, so the set names those files. The command first prints the count of files it scanned (`git ls-files | wc -l`), so an empty grep cannot pass on an empty tree.
- [ ] `zsh tools/tests/test_ctl_approve_misc.zsh` passes.

**Verify:** `zsh tools/tests/test_ctl_approve_misc.zsh && git ls-files | wc -l && grep -rnil telegram . --exclude-dir=.git | grep -v '^./docs/superpowers/' | grep -v '^./board/tests/fixtures/metrics/' | sort` → `ALL PASS`, a file count above 300, then only paths from the allowed set

**Steps:**
- [ ] `git rm` the list. Edit `bin/tmux-ctl`: delete the two telegram help lines (43-44), change line 84 to `[[ -n "$TMUX" || "$1" == discord ]] || die "not inside tmux"   # discord works outside tmux with --project`, and delete the telegram dispatch block (279-281).
- [ ] Edit `test_ctl_approve_misc.zsh:56` to `check "help: discord line kept"  test -n "$(print -r -- "$h" | grep 'tmux-ctl discord')"`.
- [ ] Add the superseded line to the four docs. Run Verify. Commit `chore(telegram): delete Telegram; Discord is the only remote channel`.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_approve_misc.zsh", "docs/superpowers/specs/2026-11-09-remote-access-design.md", "docs/superpowers/specs/2026-11-10-telegram-fixes-design.md", "docs/superpowers/specs/2026-11-10-telegram-one-lead-tasks-design.md", "docs/superpowers/plans/2026-11-09-remote-access.md"], "verifyCommand": "zsh tools/tests/test_ctl_approve_misc.zsh && git ls-files | wc -l && grep -rnil telegram . --exclude-dir=.git | grep -v '^./docs/superpowers/' | grep -v '^./board/tests/fixtures/metrics/' | sort", "acceptanceCriteria": ["telegram files deleted, metrics fixtures untouched", "telegram grep outside docs/superpowers and metrics fixtures shows only the allowed set", "approve_misc help check passes on discord"], "modelTier": "mechanical"}
```

### Task 10: Real-state check and full suite

**Goal:** Prove the branch against this machine's real Discord state (read-only) and the whole suite.

**Files:**
- Create: `docs/superpowers/notes/2026-11-16-discord-real-check.md`

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh; echo rc=$?` prints `ALL PASS <n> jobs`. An rc of 4 for `SLOW` alone is recorded as such; any `FAIL` blocks.
- [ ] Read-only against real state, run from the worktree: `tmux-ctl discord status --project agent-board` (with the worktree's `bin` first on PATH) prints `token: set`, `policy: allowlist`, and `held by: <session>:claude pid <n>`, where `<n>` is the live agent-board lead's claude pid (cross-check with `ps -E -o command= -p <server pid>` showing `DISCORD_STATE_DIR=…/discord/agent-board`). `status --project interiors` prints its own holder, or `nobody`.
- [ ] `claude-orchestrator` from the worktree runs once inside a real pane of this session with a fake `claude` first on PATH that records argv, `TC_DISCORD_LAUNCHER=0` and the real `TC_STATE`. Because the live lead holds the agent-board bot, the recorded argv has no `--channels` and stderr has the `held by the lead in …` line. The note records the argv and the stderr line.
- [ ] The note lists each command, its output (tokens never shown) and a final line `REAL CHECK PASS` or `REAL CHECK FAIL: <why>`.

**Verify:** `grep -c 'REAL CHECK PASS' docs/superpowers/notes/2026-11-16-discord-real-check.md` → `1`

**Steps:**
- [ ] Run each check. Write the note. Commit `test(discord): real-state check`.

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-16-discord-real-check.md"], "verifyCommand": "grep -c 'REAL CHECK PASS' docs/superpowers/notes/2026-11-16-discord-real-check.md", "acceptanceCriteria": ["all.zsh ALL PASS (SLOW-only rc 4 recorded)", "real status shows token set, allowlist, held by the live lead", "real-pane orchestrator run with fake claude: no --channels, held-by stderr line", "note ends REAL CHECK PASS"], "modelTier": "standard"}
```

### Task 11: After the merge: migrate, restart and a real DM (user gate)

**Goal:** On this machine after the merge, run `tmux-ctl discord migrate` once (finishing step, approved), then restart the agent-board lead with `agent-board lead --continue` and check that a DM from the user gets 👀 and a reply.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none (machine state)

**Acceptance Criteria:**
- [ ] `tmux-ctl discord migrate` output captured: the telegram watch job is booted out or was absent, the telegram plugin is disabled, and the token-dir notice is printed.
- [ ] After `agent-board lead --continue`, the board shows `dc` on the agent-board lead, and `tmux-ctl discord status --project agent-board` shows `held by: <session>:claude pid <new lead pid>`.
- [ ] The user's DM in `#agent-board` gets the 👀 reaction and a reply from the restarted lead.

**Verify:** `tmux-ctl discord status --project agent-board` → `held by:` names the restarted lead; the user confirms 👀 and the reply

```json:metadata
{"files": [], "verifyCommand": "tmux-ctl discord status --project agent-board", "acceptanceCriteria": ["migrate output captured", "dc badge and held by the restarted lead", "user DM gets 👀 and a reply"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```
