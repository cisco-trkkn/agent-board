# agent-board

The tmux `dev` toolkit (`bin/`), the Agent Board (`board/`), its tests (`tools/tests/`, `board/tests/`), and the lead and worker rules (`claude/`). See README.md for how repo paths map to live paths.

## Commands

    python3 -m unittest discover -s board/tests     # board (server, artifacts, ideas, relay…)
    python3 -m unittest discover -s tools/tests -p 'test_*.py'   # install_lib (the install.sh --migrate helpers)
    zsh tools/tests/run-all.zsh                     # tmux-ctl, dev layout, hooks (scratch tmux server)

## Rules

- The live install is symlinked to this checkout: whatever branch is checked out here runs for every tmux session. Keep `main` working; switch back to `main` when a branch is done.
- Specs and plans go in `docs/superpowers/`; ideas for this project go in `~/.claude/ideas/agent-board.md`.
- Conventional commits with scope: `feat(board): …`, `fix(tmux-ctl): …`, `docs(plan): …`.
