# agent-board

The tmux `dev` orchestration toolkit and the Agent Board web UI, for running teams of Claude Code agents per project.

- **`dev <repo>`** opens a tmux session for a project: a `claude` window running the lead (an orchestrator that splits work across an agent team by default) and your own `shell`. The agents' `tests`/`shell` windows live in a hidden `<project>-bg` session.
- **`tmux-ctl`** lets agents run tests in those windows safely (locking, busy-window lanes, output capture, run records), start worker Claudes in their own git worktrees, and talk to them.
- **The Agent Board** (`tmux-dash`) is a localhost web UI with every project, agent status ("Needs you"), live terminals, test runs and command feed, plans and specs (with inline edit and comments to the lead), ideas, and worktrees.
- **Claude rules and hooks** make the lead orchestrate and workers act alone, mirror agent commands to the board, register artifacts, and block `pkill` patterns that would kill Claude itself.

## Documentation

| Doc | For |
| --- | --- |
| [docs/INSTALL.md](docs/INSTALL.md) | installing on a new machine: prerequisites, symlinks, tmux and Claude Code config, verification, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | how it works: sessions, `tmux-ctl`, teams and workers, hooks, the board's API and security model, state files, tests |
| [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md) | every knob: environment variables, `.dev/windows`, model routing, lead/worker rules, key bindings, board UI, hook rules |
| [docs/superpowers/](docs/superpowers/) | design specs and implementation plans for each feature, including the [planned installability refactors](docs/superpowers/plans/2026-10-19-installability-refactors.md) |

## Doesn't touch your existing Claude Code setup

The install in [docs/INSTALL.md](docs/INSTALL.md) is scoped to agent-board:
- **Claude Code:** it never edits `~/.claude/settings.json` and installs no global skills or agents. agent-board's settings and hooks live in `~/.config/agent-board/claude-settings.json`, which only agent-board leads load (`claude --settings`).
- **tmux:** the one tmux-wide change is two hooks, sourced from `~/.config/agent-board/tmux.conf`.

The remaining gaps (worker hooks, teammate inheritance, shipping the skills, a dedicated tmux server) are listed in INSTALL.md and planned in the [installability plan](docs/superpowers/plans/2026-10-19-installability-refactors.md). That plan has not been applied.

## Quick start (macOS)

```zsh
brew install tmux ttyd fzf jq
gh auth login          # the repo is private
git clone https://github.com/cisco-trkkn/agent-board.git ~/agent-board
# then follow docs/INSTALL.md steps 2–6
dev ~/code/my-repo     # project session with the lead
tmux-dash              # the board in your browser
```

## Repo path → live path

The install is a set of symlinks into this checkout:

| Repo path | Live path |
| --- | --- |
| `board/` | `~/.local/share/tmux-dash` |
| `tools/` | `~/.local/share/tmux-tools` |
| `bin/<script>` | `~/.local/bin/<script>` (`claude-orchestrator` is a wrapper that adds `--settings`) |
| `claude/orchestrator.md`, `claude/worker.md` | `~/.claude/orchestrator.md`, `~/.claude/worker.md` (read only by agent-board's launchers) |
| `claude/hooks/<hook>` | `~/.claude/hooks/<hook>` (registered only in the agent-board settings file) |

The checked-out branch is what runs. Restart the board after server changes: `tmux-dash stop && tmux-dash start`.

## Tests

```zsh
python3 -m unittest discover -s board/tests     # board
zsh tools/tests/run-all.zsh                     # tmux-ctl, layout, hooks (private tmux server)
```
