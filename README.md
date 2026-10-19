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

## Quick start (macOS)

```zsh
brew install tmux ttyd fzf jq
git clone https://github.com/cisco-trkkn/agent-board.git ~/agent-board
# then follow docs/INSTALL.md §1–5 (symlinks, ~/.tmux.conf block, ~/.claude/settings.json hooks)
dev ~/code/my-repo     # project session with the lead
tmux-dash              # the board in your browser
```

## Repo path → live path

The live install is a set of symlinks into this checkout:

| Repo path | Live path |
| --- | --- |
| `board/` | `~/.local/share/tmux-dash` |
| `tools/` | `~/.local/share/tmux-tools` |
| `bin/<script>` | `~/.local/bin/<script>` |
| `claude/orchestrator.md`, `claude/worker.md` | `~/.claude/orchestrator.md`, `~/.claude/worker.md` |
| `claude/hooks/<hook>` | `~/.claude/hooks/<hook>` |

The checked-out branch is what runs. Restart the board after server changes: `tmux-dash stop && tmux-dash start`.

## Tests

```zsh
python3 -m unittest discover -s board/tests     # board
zsh tools/tests/run-all.zsh                     # tmux-ctl, layout, hooks (private tmux server)
```
