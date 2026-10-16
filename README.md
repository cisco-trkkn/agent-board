# agent-board

The tmux `dev` orchestration toolkit and the Agent Board web UI.

| Repo path | Live path (symlink into this repo) |
| --- | --- |
| `board/` | `~/.local/share/tmux-dash` |
| `tools/` | `~/.local/share/tmux-tools` |
| `bin/<script>` | `~/.local/bin/<script>` |
| `claude/orchestrator.md`, `claude/worker.md` | `~/.claude/orchestrator.md`, `~/.claude/worker.md` |
| `claude/hooks/<hook>` | `~/.claude/hooks/<hook>` |

The checked-out branch is what runs. Restart the board after server changes: `tmux-dash stop && tmux-dash start`.
