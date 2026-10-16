# agent-board

The tmux `dev` orchestration toolkit and the Agent Board web UI.

| Repo path | Live path (symlink into this repo) |
| --- | --- |
| `board/` | `~/.local/share/tmux-dash` |
| `tools/` | `~/.local/share/tmux-tools` |
| `bin/<script>` | `~/.local/bin/<script>` |
| `claude/orchestrator.md`, `claude/worker.md` | `~/.claude/orchestrator.md`, `~/.claude/worker.md` |
| `claude/hooks/<hook>` | `~/.claude/hooks/<hook>` |
| `claude/CLAUDE.md` | `~/.claude/CLAUDE.md` |
| `claude/agents/<file>` | `~/.claude/agents/<file>` |
| `claude/skills/<skill>/` | `~/.claude/skills/<skill>` (own skills only; `synced/` and `handoff` are not tracked) |
| `claude/settings.json` | **not linked**: Claude Code rewrites it, so it stays a regular file; `bin/claude-config-sync` copies live → repo |

`bin/claude-config-link [--dry-run]` creates the `~/.claude` links above (backs up an existing file as `F.bak-YYYYMMDD`, refuses a link that points elsewhere). Run it from the main checkout once the branch is merged.

The checked-out branch is what runs. Restart the board after server changes: `tmux-dash stop && tmux-dash start`.
