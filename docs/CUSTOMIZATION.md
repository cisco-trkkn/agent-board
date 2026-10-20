# Customizing agent-board

Every customization point, from least to most invasive. Read [ARCHITECTURE.md](ARCHITECTURE.md) first if you plan to change code.

**Keep it scoped.** Everything below should apply only to agent-board sessions. Put Claude Code settings in `~/.config/agent-board/claude-settings.json` (loaded with `--settings` by the `claude-orchestrator` wrapper), never in `~/.claude/settings.json`. Put tmux settings in `~/.config/agent-board/tmux.conf`. Don't install agent-board skills or agents into `~/.claude/skills` or `~/.claude/agents`. See [INSTALL.md](INSTALL.md#what-this-install-changes-on-your-machine).

## 0. The agent-board settings file

`~/.config/agent-board/claude-settings.json` is an ordinary Claude Code settings file that only agent-board leads load. Anything you want only for agent-board sessions goes here. It is additive: your user, project and local settings still apply underneath it.

```json
{
  "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1", "AGENT_BOARD": "1" },
  "teammateMode": "auto",
  "permissions": { "allow": ["Bash(tmux-ctl:*)"] },
  "hooks": { "…": "the three agent-board hooks from INSTALL.md §4, plus your own" }
}
```

Examples: allow `tmux-ctl` without prompts in agent-board sessions only (above); add a hook that only makes sense for agent teams. To use another file for one project, start that project's lead with it: `DEV_CLAUDE_CMD="$HOME/agent-board/bin/claude-orchestrator --settings ~/my/other.json" dev ~/code/proj`.

## 1. Environment variables

| Variable | Default | Read by | Effect |
| --- | --- | --- | --- |
| `DEV_CLAUDE_CMD` | `claude-orchestrator` | `dev` | Command typed into the `claude` window of a **new** session, e.g. `DEV_CLAUDE_CMD=claude dev .` for a plain Claude, or `"claude-orchestrator --continue"`. Ignored (with a warning) when the session already exists. |
| `DEV_NO_ATTACH` | unset | `dev` | Create the session but don't attach (the board uses this). |
| `DEV_CLIENT` | unset | `dev` | Switch this tmux client instead of the current one (`Ctrl-a D` uses it). |
| `TC_TMUX` | `~/.local/bin/tmux` | every script, hook and the board, through `bin/_tc_bins.zsh` | tmux binary to use. |
| `AGENT_BOARD_TMUX_SOCKET` | `agent-board` | `bin/_tc_bins.zsh` | Name of agent-board's own tmux server (`tmux -L <name>`), the one `dev` and `tmux-dash` use. An unmigrated install (agent-board hook lines still in `~/.tmux.conf`, no such server running) keeps using the user's own server until `install.sh --migrate`. The test harness points it at its private socket. |
| `TC_STATE` | `${TMPDIR:-/tmp}/tmux-ctl-$UID` | `tmux-ctl`, hooks, board, `relay.py`, `tmux-session-closed` | Runtime state directory. Must be the same for every process of one tmux server; set it in your shell profile if you change it. |
| `TC_SESSION` | caller's session | `tmux-ctl` | Target a different session (the board sets it for actions). |
| `TC_LAYOUT` | `~/.local/bin/tmux-dev-layout` | `dev` | Replace the layout step with your own script (called as `<script> <session> <root>`). |
| `TC_IDEAS_DIR` | `~/.claude/ideas` | `ideas.py` (board, `tmux-ctl idea`) | Where idea files live. |
| `TC_AGENT_DRYRUN` | unset | `tmux-ctl agent` | Test seam: print the task and stop before creating a window. |
| `TMUX_DASH_PORT` | `7700` | `tmux-dash`, `server.py` | Board HTTP port. |
| `TMUX_DASH_TTYD_PORT` | `7701` | `tmux-dash`, `server.py` | ttyd port. |
| `TMUX_DASH_TMUX_ARGS` | empty | every script and the board, through `bin/_tc_bins.zsh` | Which tmux server to talk to, e.g. `-L default` to keep the board and `dev` on your own server. Overrides the resolver's choice (`$TMUX`'s server inside tmux, else `-L agent-board`); `tmux-dash` sets it for `server.py` and the ttyd terminals so both read the same server. |
| `TMUX_DASH_PAGE` | `index.html` | `server.py` | Serve another HTML file from `board/` (a fork of the UI, an experiment). |
| `TMUX_DASH_DEBUG` | unset | `server.py` | Log every request to stderr, which `tmux-dash` sends to `~/.local/state/tmux-dash/server.log`. |
| `FZF_BIN` | `~/.local/bin/fzf` | `tmux-agent-cleanup` | fzf binary. |
| `USAGE_ROOT` | `~/.claude/projects` | `board/usage.py` | Where the Usage tab reads Claude Code transcripts (read-only). |
| `SUPERPOWERS_PLUGIN_ROOT` | auto-discovered | `superpowers-hook.sh` | Pin which superpowers-extended-cc install the optional hooks run. |

`TMUX_DASH_TOKEN` is set by `tmux-dash` itself; don't set it by hand. Rotate it with `tmux-dash rotate`.

## 2. Per-project files

### `.dev/windows`: watch panes

Put a file at `<repo>/.dev/windows` to give the agents' hidden `tests` or `shell` window a second pane running a watcher. One line per window, `#` comments allowed:

```
# .dev/windows
tests: npm run test:watch
shell: tail -F logs/app.log
```

`tmux-dev-layout` splits the window and runs the command with `zsh -lc` in the repo root. The pane is tagged `@tc_role=watch`, so `tmux-ctl` never types into it; read it with `tmux-ctl read tests watch`. It is created once; re-run `dev` after editing the file to add a missing one.

### `docs/superpowers/model-routing.json`: model per task tier

Maps plan-task tiers to models, and optionally effort. This repo's copy:

```json
{ "mechanical": "haiku", "standard": "sonnet", "frontier": "fable", "enforceEffort": true }
```

Add `"effort": {"mechanical": "low", "standard": "medium", "frontier": "inherit"}` to override the per-tier effort. The lead falls back to the mapping above when a repo has no file. Enforcement is done by the superpowers-extended-cc plugin, not by this repo.

### Project `CLAUDE.md`

The lead and workers read the repo's `CLAUDE.md` like any Claude Code session. Put test commands there (the agents will run them through `tmux-ctl run tests "<cmd>"`), plus any rules about where specs and plans go.

## 3. Lead and worker behaviour

`claude/orchestrator.md` and `claude/worker.md` are plain Markdown appended to the system prompt. Edit them to change:

- **Team defaults**: team size (2–3, max 4), when to skip a team, the roles.
- **The skill table**: which skill runs for which situation. Remove `task-observer` and `gitlab-ci-loop` if you don't have them; add your own.
- **Model tiers**: the default tier-to-model map and how to start each tier (`subagent_type` and `model`).
- **Guard rails**: never answer permission prompts, never push or merge unasked, never `pkill` by pattern.
- **Worker finish**: what a worker reports and whether it may push.

Changes apply to the next Claude started; restart a lead from the board (Restart orchestrator) or with `claude-orchestrator` in its window.

To use different rules for one project without editing the shared files, start the lead yourself:

```zsh
DEV_CLAUDE_CMD="claude --settings ~/.config/agent-board/claude-settings.json --append-system-prompt-file ~/my-rules/lead.md" dev ~/code/proj
```

Keep the `--settings` flag when you bypass `claude-orchestrator`, or the lead loses agent teams and the hooks. `DEV_CLAUDE_CMD` applies only when `dev` creates the session; Restart orchestrator and `/handoff` always start `claude-orchestrator`.

`claude-orchestrator` defaults to `--model opus` and `--name orchestrator`. Pass `--model`/`--name` to override, e.g. `DEV_CLAUDE_CMD="claude-orchestrator --model sonnet"`. The extra arguments go through the wrapper too.

## 4. tmux key bindings and hooks

Bindings and hooks go in `~/.config/agent-board/tmux.conf`, which your `~/.tmux.conf` sources (see [INSTALL.md §5](INSTALL.md#5-tmux)). tmux bindings and hooks are server-wide, so choose keys you don't already use. The scripts you can bind:

| Script | Bind it to… |
| --- | --- |
| `dev '#{pane_current_path}'` with `DEV_CLIENT` | open the project for the current folder |
| `tmux-jump '#{client_name}'` in a popup | fuzzy window switcher |
| `tmux-agent-cleanup` in a popup with `-d '#{pane_current_path}'` | worktree cleanup picker |
| `tmux-dash` | open the board |

The two hooks (`after-split-window`, `session-closed`) are required; without the first, teammates stay as split panes, and without the second, per-project state accumulates in `TC_STATE` until reboot.

## 5. The Agent Board

### Ports, server and token

```zsh
TMUX_DASH_PORT=8800 TMUX_DASH_TTYD_PORT=8801 tmux-dash start
tmux-dash rotate        # new token; old URLs stop working
tmux-dash url           # print the current URL
```

Ports are read at start time, so `stop` then `start` with the new values. The server only ever binds 127.0.0.1. To reach it from another machine, use an SSH tunnel (`ssh -L 7700:127.0.0.1:7700 -L 7701:127.0.0.1:7701 host`), never a public bind; the `Host` header check accepts only `127.0.0.1`/`localhost`.

### Terminal look

ttyd options are in `bin/tmux-dash` (`-t fontSize=13`, `fontFamily`, the Catppuccin `theme` JSON). Change them there and restart the board.

### The UI

`board/index.html` is self-contained (inline CSS/JS, no build). Colours are CSS custom properties at the top of the file. To experiment without touching the default page, copy it and serve the copy:

```zsh
cp board/index.html board/mine.html
tmux-dash stop && TMUX_DASH_PAGE=mine.html tmux-dash start
```

The page polls everything in one loop every 2 s (the `poll()` function at the end of the script); server-side caching is `STATE_TTL` (1.5 s) and `WT_TTL` (30 s) at the top of `board/server.py`.

### Pane status detection

When a Claude Code release changes its screen, the board may show the wrong status. The patterns are in `board/paneclass.py`:

- `WORKING_RE` (`esc to interrupt`) → working
- `WAITING_RE` (permission prompts, `(y/n)`, `❯ 1. Yes`, …) → waiting
- `INPUT_RE`, `RULE_RE`, `MENU_RE` → whether the user is typing into the input line

`tmux-ctl tell` has its own copy of the waiting patterns (`bin/tmux-ctl`, the `tell` case); keep them in sync. Add a case to `board/tests/test_paneclass.py` with captured screen text for any change.

### Usage tab: alerts and prices

Alert thresholds: create `~/.claude/usage-alerts.json` with any of these keys (the defaults are in [ARCHITECTURE.md → Usage tracking](ARCHITECTURE.md#usage-tracking)):

```json
{ "context_pct": 85, "burn_per_hour": 30, "session_total": 50, "mismatch_models": ["opus"] }
```

Only the board reads this file. A malformed file or value falls back to the defaults and shows a warning in the Usage tab. Changes apply on the next poll; no restart is needed. (The plan moves this file to `~/.config/agent-board/` in Task 6.)

Prices: `board/prices.json` holds $/Mtok and context size per model. Add an entry for a new model, or calls on it show as *unpriced*. Cross-check totals after editing with `python3 tools/usage-sum.py --repo <path>`.

### New board actions

1. Add a branch in `_act()` in `board/server.py`. Validate the session with `_check_project`, prefer calling an existing script (`tmux-ctl`, `dev`) over new tmux logic, and raise `RuntimeError` with a user-facing message on failure.
2. Call it from the page with the existing `POST api/action` helper (it already sends `X-Dash-Token`).
3. Add a test under `board/tests/` (see `test_agent_controls.py` for the fake-tmux pattern).

## 6. Hooks

### Which commands count as "tests"

The feed is read with `tmux-ctl feed`; the board no longer displays it. `bash-mirror.sh` sends a command to the `tests` feed when its `TOOL` regex matches (pytest, tox, nox, jest, vitest, make, ruff, mypy, eslint, tsc, tflint, shellcheck, bats, agent-ci, gradle, mvn, `npm|pnpm|yarn test|build|lint`, `go test|build|vet`, `cargo test|build|clippy`, `terraform plan|validate|fmt`), also behind wrappers like `uv run`, `poetry run`, `npx`, `env VAR=…`, `time`. Everything else goes to the `shell` feed. Extend `TOOL` or `WRAP` in the hook and add a fixture case to `tools/tests/test_mirror.zsh`.

Feed size: the log is trimmed to its last 1 MB when it passes 2 MB; the tail kept per entry is 12 lines. Both are literals in the hook.

### Which files are artifacts

`artifact-register.sh`'s `kind_of()` decides by path. Add a rule there to pick up more files automatically (e.g. ADRs under `docs/adr/`), and a case to `tools/tests/test_artifact_hook.zsh`. For one-off files, register by hand: `tmux-ctl artifact <path> --kind report`.

### Kill guard

`kill-guard.sh` blocks only `pkill`/`killall` whose pattern matches a Claude process. To protect other processes the same way, extend `is_claude()`. It fails open: a parse error lets the command through.

## 7. Worktrees and workers

- Worker worktrees are created by Claude Code's `-w <name>` under `.claude/worktrees/<name>`. Add `.claude/worktrees/` to the repo's `.gitignore`.
- `tmux-ctl agent` refuses briefs under 8 words; the threshold is in the `agent` case of `bin/tmux-ctl`. `--brief FILE` sends a file verbatim, `--force` skips both checks.
- Lanes close after 900 s idle (`reap_lanes` in `bin/tmux-ctl`).
- `tmux-agent-cleanup` and the board treat a branch as safe to delete when it is merged into the current branch or `origin/HEAD` (fallback `main`).

## 8. Tunable constants

Values that are literals in the code today. Change them in place, and add or adjust a test.

| Value | Default | Where |
| --- | --- | --- |
| `tmux-ctl run` timeout | 600 s (`-t secs` per call) | `parse_opts` in `bin/tmux-ctl` |
| Lane idle reap | 900 s | `reap_lanes` in `bin/tmux-ctl` |
| Minimum brief length | 8 words | `agent` case in `bin/tmux-ctl` |
| Teammate name wait | ~10 s (40 × 0.25 s) | `bin/tmux-teammate-window` |
| State cache / worktree cache | 1.5 s / 30 s | `STATE_TTL`, `WT_TTL` in `board/server.py` |
| Capture thread pool | 12 | `POOL` in `board/server.py` |
| Runs shown / log bytes served | 100 / 512 KB | `runs()`, `log_text()` in `board/activity.py` |
| Usage indexer scan interval | 5 s | `Indexer.start()` in `board/usage.py` |
| Recent projects kept | 10 | `RECENT_MAX` in `board/dirs.py` |
| Folder listing cap | 500 | `CAP` in `board/dirs.py` |
| Relay wait | 2 s poll, 120 s cap | `wait_turn_end()` in `board/relay.py` |
| Feed log size | trim at 2 MB to the last 1 MB; 12 output lines per entry | `claude/hooks/bash-mirror.sh` |
| Project names | `[A-Za-z0-9_-][A-Za-z0-9._-]*` | `NAME_RE` in `board/server.py`, `board/ideas.py` |

## 9. Theme

The fzf colours in `tmux-jump` and `tmux-agent-cleanup` and the ttyd terminal theme in `tmux-dash` use Catppuccin Mocha as literal values in each file. The board page has its own palette as CSS custom properties (`--bg`, `--panel`, `--accent`, …) at the top of `board/index.html`: a light set, and a dark set under `prefers-color-scheme: dark`. There is no shared theme file.
