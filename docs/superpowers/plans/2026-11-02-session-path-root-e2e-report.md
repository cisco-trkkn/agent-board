# Session path root: real-state check (2026-11-02)

## Setup

A second board ran from the worktree `usage-scope` (branch `feat/usage-scope`, which holds Task 1's commit 9b0a605) with `TMUX_DASH_PORT=7710 python3 board/server.py`, no `TC_STATE` override, so it read the real state dir and the live tmux server. Its URL was `http://127.0.0.1:7710/<token>/`. Port 7700 was never queried.

This is also the end-to-end proof the Task 1 review asked for: the 7710 board read the live server's real `#{session_path}` through `build_state` and the real `relay.root_for` on real repos and worktrees.

Sessions checked: 4 (the live server has 10; excluded are `_web-89235` and the five `-bg` sessions `agent-board-bg`, `francisco_ruiz-bg`, `interiors-bg`, `master-gcp-repo-bg`, `x-dev-notgit-bg`). `francisco_ruiz` was started in `~` and maps to `~`, like the others.

The API (`/api/state`, `/api/usage?session=<name>`) and an in-process `usage.report(conn, <state path>, prices, thresholds, now)` (the call the `api/usage` handler makes) were read in the same script run, a second or so apart. No count differed, so no re-read was needed.

## Usage per project

| Session | `#{session_path}` | Window 1 `#{pane_current_path}` | `/api/state` `path` | Rows from `/api/usage` | Rows from in-process `report()` |
|---|---|---|---|---|---|
| agent-board | /Users/francisco.ruiz/agent-board | /Users/francisco.ruiz | /Users/francisco.ruiz/agent-board | 6 | 6 |
| francisco_ruiz | /Users/francisco.ruiz | /Users/francisco.ruiz | /Users/francisco.ruiz | 0 | 0 |
| interiors | /Users/francisco.ruiz/interiors | /Users/francisco.ruiz | /Users/francisco.ruiz/interiors | 2 | 2 |
| master-gcp-repo | /Users/francisco.ruiz/master-gcp-repo | /Users/francisco.ruiz | /Users/francisco.ruiz/master-gcp-repo | 0 | 0 |

Row `cwd`s (`live` array; every row has source `tap`; every one passed `usage.in_project(cwd, root)`):

- agent-board (6): `.../agent-board/.claude/worktrees/usage-scope` ×4, `.../agent-board/.claude/worktrees/overseer` ×2.
- francisco_ruiz: no rows.
- interiors (2): `/Users/francisco.ruiz/interiors` ×2.
- master-gcp-repo: no rows (no live session under it at the time).

`agent-board` and `interiors` have window 1 in `~`, which differs from their root, and still return their own project's rows (and none of another project's). `master-gcp-repo` also has window 1 in `~` and its card path is its root; it has no live rows, so it shows the correct card path but no row evidence. Zero violations of the "root or under `<root>/.claude/worktrees/`" rule.

## Cards

`/api/state` `worktrees.items` per card (all under `<root>/.claude/worktrees/`):

- agent-board (repo main): `overseer`, `runtime-phase1`, `usage-scope` under `/Users/francisco.ruiz/agent-board/.claude/worktrees/`. Under root: yes.
- francisco_ruiz (current branch `dev`): none.
- interiors (main): none.
- master-gcp-repo (current `dev3`): `connector-framework`, `ga4-connector-refit`, `mougii-analysis` under `/Users/francisco.ruiz/master-gcp-repo/.claude/worktrees/`. Under root: yes.

## Commands run

Against the live tmux server (read-only): `tmux list-sessions -F '#{session_name}'`; for each of the four sessions `tmux display -p -t "=<s>:" '#{session_path}'` and `tmux display -p -t "=<s>:1" '#{pane_current_path}'`.

The board (`/api/state` calls `list-panes` and git on the live server's behalf, read-only): `TMUX_DASH_PORT=7710 python3 board/server.py` in the background (PID 8760).

A scratch script (outside the repo) fetched `/api/state` and `/api/usage?session=<name>` from 7710 and ran `usage.report()` in-process, then compared. The server was stopped with `kill 8760`; afterwards `ps -p 8760` finds no process. The only `board/server.py` left in `ps aux` is PID 97207, the live 7700 board started Thursday, which was not touched.

Nothing in `board/` was edited.
