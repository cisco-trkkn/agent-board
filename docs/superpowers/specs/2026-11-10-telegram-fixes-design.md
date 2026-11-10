# Telegram remote-access fixes (spec 11 follow-up)

Date: 2026-11-10 · Ideas: 113, 114, 115, 116 in `~/.local/state/agent-board/ideas/agent-board.md`
Builds on: `docs/superpowers/specs/2026-11-09-remote-access-design.md` (spec 11)

## Problem

Spec 11 shipped one Telegram bot per project, but four gaps showed up in the first real use (2026-11-10):

1. **Bun is blocked.** Netskope returns a 403 block page to bun's HTTPS requests to `api.telegram.org`; curl and node
   pass. The plugin's MCP server is launched by `bun run … start`, so the bot never polls. The stopgap is a hand edit
   of `~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7/.mcp.json` to
   `node --experimental-strip-types --no-warnings ${CLAUDE_PLUGIN_ROOT}/server.ts` (backup in
   `~/.claude/plugin-backups/telegram/.mcp.json.bak-20261110`). A plugin update installs a new version directory
   with the bun launcher again.
2. **`tmux-ctl telegram status` checks the wrong runtime.** It prints `bun: ok|missing` (`tools/lib/telegram.zsh`),
   which says nothing about whether the server can run.
3. **`/telegram:access` writes to the wrong bot in a lead.** The skill resolves its folder with
   `echo "${TELEGRAM_STATE_DIR:-…/channels/telegram}"` in a Bash command; `claude/plugin/scripts/telegram-env-scrub.sh`
   unsets `TELEGRAM_STATE_DIR` in the lead's Bash shells (on purpose, so a `claude` started from Bash never polls the
   lead's bot). The skill therefore reads and writes `~/.claude/channels/telegram`: the wrong bot, and a folder the
   rules say must not hold a token.
4. **The restart command is not on PATH.** Docs say `claude-orchestrator --continue`; only `agent-board` and
   `tmux-ctl` are linked into `~/.local/bin`. A lead restarted with plain `claude --resume` has no Telegram channel.
   Also undocumented: right after a token is first saved, Claude Code may keep the telegram MCP failure cached for
   about 15 minutes; `/mcp` → Reconnect clears it.

## Decisions

- Node launcher: **self-heal at lead launch** (not a PATH shim, not a warning only).
- Pairing and policy: **`tmux-ctl telegram` subcommands** run by the user in a terminal; `/telegram:access` is not used
  in a lead. No `AB_TELEGRAM_DIR` variable.
- Restart: **`agent-board lead [claude args]`**, a subcommand that execs `bin/claude-orchestrator`.

## Design

### 1. Self-healing node launcher

New file `tools/lib/telegram-launch.zsh`, function `tg_ensure_node_launcher [--dry-run]`.

- Called by `bin/claude-orchestrator` only when the lead gets the channel (the branch that exports
  `TELEGRAM_STATE_DIR` and sets `TG_ARGS`), before `exec claude`. Skipped when `TC_TELEGRAM_RUNTIME=bun`.
- Finds the plugin with `jq` from `~/.claude/plugins/installed_plugins.json`:
  `.plugins["telegram@claude-plugins-official"][0].installPath` (the live file has top-level `plugins` and `version`
  keys, checked 2026-11-10). If the file, the entry or the path is missing:
  print `telegram: plugin not found; run claude plugin install telegram@claude-plugins-official` to stderr, return 0.
- Desired `.mcp.json`:

  ```json
  {
    "mcpServers": {
      "telegram": {
        "command": "node",
        "args": ["--experimental-strip-types", "--no-warnings", "${CLAUDE_PLUGIN_ROOT}/server.ts"]
      }
    }
  }
  ```

  Compared with `jq -S .mcpServers.telegram`; equal means no-op (prints nothing).
- Otherwise: copy the current file to `~/.claude/plugin-backups/telegram/<version>/.mcp.json.bak-YYYYMMDD` (version =
  basename of installPath; never overwrite an existing backup of that day), write the desired JSON to
  `.mcp.json.next` in the plugin folder and `mv` it over `.mcp.json`. Print one line:
  `telegram: plugin launcher switched to node (<version>)`.
- If `<installPath>/node_modules` is missing: `npm install --omit=dev --no-audit --no-fund` in installPath, output to
  `${TC_STATE}/telegram/npm-install.log`. On failure print `telegram: npm install failed, see <log>`.
- `node` not on PATH: print `telegram: node not found; the Telegram server cannot start`, change nothing.
- `--dry-run`: print what it would do (`ok: node launcher`, `would switch launcher`, `would npm install`), change
  nothing.
- Never fails the launch: every error path prints one line and returns 0.

### 2. `tmux-ctl telegram` access commands and status

In `tools/lib/telegram.zsh`, alongside `token|status|forget`:

| Command | Effect on `<dir>/access.json` |
| --- | --- |
| `pair <code>` | Look up `pending[code]`; missing or `expiresAt < now(ms)` → error, exit 1. Else add its `senderId` to `allowFrom` (dedupe), delete `pending[code]`, write; then `mkdir -p <dir>/approved` and write `<dir>/approved/<senderId>` containing `chatId`. Print `telegram: approved <senderId>`. |
| `deny <code>` | Delete `pending[code]`; unknown code → error, exit 1. |
| `policy <mode>` | `mode` ∈ `pairing`, `allowlist`, `disabled`, else usage error exit 2; set `dmPolicy`. |
| `allow <senderId>` | Add to `allowFrom` (dedupe). |
| `remove <senderId>` | Remove from `allowFrom`. |

- Missing file = `{"dmPolicy":"pairing","allowFrom":[],"groups":{},"pending":{}}`.
- Every write: read the current file, change it with `jq`, write `access.json.next` (mode 600, 2-space indent),
  `mv` it over `access.json`. Keys the command does not touch are kept as they are.
- The token guard in `telegram_cmd` stays: the existing `<->:*` check still refuses a token-shaped argument. The
  argument count rule changes: these commands take one positional value (`code`, `mode`, `senderId`), plus an optional
  project via `--project`. A code, mode or sender ID is never treated as the project.
- `status` replaces the `bun:` line with:
  - `runtime: node` when the installed `.mcp.json` matches the desired launcher, `runtime: bun` when it is the bun
    launcher and `TC_TELEGRAM_RUNTIME=bun`, else `runtime: drift (the plugin launcher is not node; restart the lead)`;
  - `node: ok|missing` (`command -v node`);
  - `deps: ok|missing` (`<installPath>/node_modules`).
  Status shares the plugin lookup with `telegram-launch.zsh`.
- `token` ends with: `telegram: token saved for <project> (restart its lead: agent-board lead --continue in the
  project's claude window, or Restart orchestrator on the board)`.
- Usage text lists the new commands.

### 3. `agent-board lead`

`bin/agent-board`: `lead) shift; exec "$here/claude-orchestrator" "$@" ;;` and a help line. In
`bin/claude-orchestrator`, when `$TMUX` is empty and `TC_TELEGRAM` is not `0`, print
`agent-board lead: not in tmux, so no Telegram channel` to stderr (once, before exec). The project is the pane's
session group, else its session name (unchanged), so the command works in any project's session.

### 4. Lead rules and docs

- `claude/orchestrator.md`, Remote: Telegram: a lead never runs `tmux-ctl telegram pair|deny|policy|allow|remove`
  (access changes are the user's, typed in a terminal), and never runs `/telegram:access`.
- `docs/INSTALL.md` § Remote access: restart with `agent-board lead --continue` or Restart orchestrator; pair with
  `tmux-ctl telegram pair <code>` then `tmux-ctl telegram policy allowlist`; do not use `/telegram:access` in a lead
  (why); Netskope blocks bun and the launcher switches the plugin to node itself (`TC_TELEGRAM_RUNTIME=bun` to opt
  out); status lines `runtime`, `node`, `deps` replace `bun`; after the first token save, if `/mcp` shows telegram
  failed, `/mcp` → Reconnect.
- `tools/tests/e2e-remote-access.md`: the same command changes in its steps and expected status lines.
- `docs/superpowers/specs/2026-11-09-remote-access-design.md` is not edited (history).

## Error handling

The launcher never blocks a lead from starting. Access commands exit 1 with one line on a bad code and 2 on a usage
error; they never print a token. A malformed `access.json` (jq parse error) → `telegram: access.json is not valid
JSON; fix or delete it`, exit 1, file untouched.

## Testing

zsh tests in `tools/tests/` (picked up by `run-all.zsh`), each under a temp `HOME` and `TC_STATE`, never touching the
real plugin:

- launcher: fake `installed_plugins.json` + fake plugin folder with the bun `.mcp.json` → rewritten to node, backup
  present, one line printed; second run prints nothing; `TC_TELEGRAM_RUNTIME=bun` → untouched; missing plugin entry →
  one line, rc 0; missing `node_modules` with a stub `npm` on PATH → stub called with the flags; `--dry-run` → no
  change; `node` absent from PATH → one line, untouched.
- access: `pair` valid code (allowFrom, pending removed, `approved/<id>` = chatId, other keys kept, mode 600),
  expired, unknown; `deny`; `policy` valid and invalid; `allow` dedupe; `remove`; missing file → defaults; malformed
  JSON → exit 1 and untouched; token-shaped argument refused.
- status: `runtime: node`, `runtime: drift`, `runtime: bun` with the opt-out; `node:`, `deps:` lines; no `bun:` line.
- `agent-board lead --x` execs claude-orchestrator with `--x` (stub on a temp PATH); the not-in-tmux line.

One real run: `tg_ensure_node_launcher --dry-run` against the live install prints `ok: node launcher`; `tmux-ctl
telegram status` in the agent-board session prints `runtime: node`, `node: ok`, `deps: ok`.

## Out of scope

An IT allow rule for bun; replacing the plugin; group (`group add|rm`) and `set` access commands (add later if
needed); Remote Control.
