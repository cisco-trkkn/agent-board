# agent-board

The tmux `dev` orchestration toolkit and the Agent Board web UI, for running teams of Claude Code agents per project.

- **`agent-board dev <repo>`** opens a tmux session for a project: a `claude` window running the lead (an orchestrator that splits work across an agent team by default) and nothing else (`prefix S` opens a throwaway shell popup). The agents' `tests`/`shell` windows live in a hidden `<project>-bg` session.
- **`tmux-ctl`** lets agents run tests in those windows safely (locking, busy-window lanes, output capture, run records), start worker Claudes in their own git worktrees, and talk to them.
- **The Agent Board** (`agent-board dash`) is a localhost web UI with every project, agent status ("Needs you"), live terminals, API-equivalent cost and usage alerts per project, test runs, plans and specs (with inline edit and comments to the lead), ideas, and worktrees.
- **Claude rules and a session plugin** make the lead orchestrate and workers act alone, mirror agent commands to the board, register artifacts, and block `pkill` patterns that would kill Claude itself.

## Documentation

| Doc | For |
| --- | --- |
| [docs/INSTALL.md](docs/INSTALL.md) | installing on a new machine: prerequisites, `install.sh`, verification, migrating, uninstalling, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | how it works: sessions, `tmux-ctl`, teams and workers, hooks, the board's API and security model, state files, tests |
| [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md) | every knob: environment variables, `.dev/windows`, model routing, lead/worker rules, key bindings, board UI, hook rules |
| [docs/superpowers/](docs/superpowers/) | design specs and implementation plans for each feature |

## Doesn't touch your existing Claude Code setup

`./install.sh` links one file, `~/.local/bin/agent-board`, and nothing else:
- **Claude Code:** it never edits `~/.claude`. agent-board's settings, hooks, skills and agent types come from `claude/session-settings.json` and `claude/plugin/` in this checkout, loaded with `--settings` and `--plugin-dir` only by the Claude sessions agent-board starts.
- **tmux:** agent-board runs its own tmux server (`tmux -L agent-board`) with `config/tmux.conf`. Your tmux server and configuration are not touched.

## Quick start (macOS)

```zsh
brew install tmux ttyd fzf jq
gh auth login          # the repo is private
git clone https://github.com/cisco-trkkn/agent-board.git ~/agent-board
cd ~/agent-board
./install.sh --check   # lists anything missing
./install.sh           # links ~/.local/bin/agent-board
agent-board dev ~/code/my-repo     # project session with the lead
agent-board dash                   # the board in your browser
```

Coming from the author's earlier global setup? `./install.sh --migrate` (see [docs/INSTALL.md](docs/INSTALL.md#migrating-from-the-global-setup)). Remove with `./install.sh --uninstall`.

## Commands

`agent-board dev [dir]`, `ctl <cmd>` (tmux-ctl), `dash [cmd]`, `jump`, `cleanup`, `help`. The same scripts are in `bin/`; the lead and workers find them on `PATH` (`tmux-ctl`, …) in agent-board sessions.

## Layout

| Repo path | Role |
| --- | --- |
| `install.sh` | installs the one link; `--check`, `--uninstall`, `--migrate` |
| `bin/` | the commands; `bin/agent-board` is the single entry point |
| `board/` | the Agent Board server and page |
| `claude/orchestrator.md`, `claude/worker.md`, `claude/session-settings.json` | lead and worker rules, settings for agent teams |
| `claude/plugin/` | the session plugin: hooks, `tmux-orchestrator` and `handoff` skills, `effort-*` agents |
| `claude/CLAUDE.md`, `claude/settings.json`, `claude/agents/`, `claude/skills/`, `claude/hooks/` | the author's own global `~/.claude` config (mirror; `bin/claude-config-link` / `claude-config-sync`). Not used by agent-board sessions or `install.sh`; the session settings and hooks come from `claude/session-settings.json` and `claude/plugin/` |
| `config/tmux.conf` | agent-board's tmux server configuration |

The checked-out branch is what runs. Restart the board after server changes: `agent-board dash stop && agent-board dash start`.

## Tests

```zsh
python3 -m unittest discover -s board/tests                  # board
python3 -m unittest discover -s tools/tests -p 'test_*.py'   # install.sh helpers
zsh tools/tests/run-all.zsh                                  # tmux-ctl, layout, plugin, hooks (private tmux server)
```
