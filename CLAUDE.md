# agent-board

The tmux `dev` toolkit (`bin/`), the Agent Board (`board/`), its tests (`tools/tests/`, `board/tests/`), and the lead and worker rules (`claude/`). See README.md for the layout and docs/INSTALL.md for the install.

## Commands

    python3 -m unittest discover -s board/tests     # board (server, artifacts, ideas, relay…)
    python3 -m unittest discover -s tools/tests -p 'test_*.py'   # install_lib (the install.sh --migrate helpers)
    zsh tools/tests/run-all.zsh                     # tmux-ctl, dev layout, hooks (scratch tmux server)
    python3 -m unittest discover -s claude/skills/docs-architecture/tests   # docs-architecture inventory
    python3 -m unittest discover -s claude/skills/docs-compose/tests        # docs-compose Sources check
    python3 -m unittest discover -s claude/skills/docs-report/tests         # docs-report cloud gate

## Rules

- The live install (`~/.local/bin/agent-board`) links into this checkout: whatever branch is checked out here runs for every tmux session. Keep `main` working; switch back to `main` when a branch is done.
- Specs and plans go in `docs/superpowers/`; ideas for this project go in `~/.local/state/agent-board/ideas/agent-board.md` (the old `~/.claude/ideas/` file is still read).
- Conventional commits with scope: `feat(board): …`, `fix(tmux-ctl): …`, `docs(plan): …`.
