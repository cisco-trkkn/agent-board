# Plan window replaces the user's shell window — design

Date: 2026-10-28 · Status: approved in brainstorming · Idea: "the shell window really has no purpose and is
taking up valuable real estate. What could replace it?"

## Problem

`dev` opens two windows, `1 claude` and `2 shell`. The agents' own `tests` and `shell` windows already
live in the hidden session `<project>-bg`, so window 2 is an idle zsh in the repo root. The user named
three costs: a tmux tab never used, a `›_` card on the Agent Board, and window slot 2 (`prefix 2`).

## Decision

Window 2 becomes `plan`: a live, read-only view of the active plan's tasks with the teammate on each one
and whether that teammate needs the user. The on-demand shell is main's `prefix S` popup (see section 1).

Rejected: a client of a new board endpoint (blank whenever the board is not running) and a `watch` over
`.tasks.json` (cannot show owners or "needs you").

## 1. Layout

**Revised 2026-10-28.** While this spec was planned, main gained feat/no-user-shell (29ffb48..bd4d215): the
user `shell` window is gone (an idle one is removed by `tmux-dev-layout`, a busy one kept with a note) and
`prefix S` opens a popup shell in `#{session_path}`. The user chose to build on it, so this design no longer
adds a `` prefix ` `` key or migrates `shell` itself.

- `bin/dev` adds window 2 `plan`, running `bin/tmux-plan <session> <root>`, after `claude`; `claude` stays
  selected. Header comment and `dev --help`: `1 claude · 2 plan`.
- `bin/tmux-dev-layout` creates `plan` when it is missing (existing sessions get it on the next run);
  idempotent; main's `shell` handling and the `-bg` windows are unchanged.
- `config/tmux.conf`: only the `D` comment changes to name `plan`.
- The windows tables in `claude/orchestrator.md` and both tmux-orchestrator skill copies, `docs/ARCHITECTURE.md`,
  `docs/INSTALL.md` and the board's new-session help text name `plan`.
- `claude/plugin/scripts/worktree-sweep.sh` detects a dev session by its `-bg` session; unchanged.

## 2. Data — `board/planview.py`

A pure module, importable by the board later. `view(session, home, state_dir) -> dict`; CLI
`python3 board/planview.py <session> --json` for debugging. Paths are parameters so tests never read the
real HOME.

- **Lead session.** The `~/.claude/sessions/<pid>.json` entry whose `tmux` field (`<srv>:@<win>.%<pane>`)
  names the pane of `<session>:claude`; its `sessionId` is the lead.
- **Tasks.** `~/.claude/tasks/session-<first 8 of sessionId>/*.json`: `id`, `subject`, `status`,
  `blockedBy`, `owner`. Sorted by numeric id.
- **Plan name.** The newest `kind: plan` line with that `session_id` in
  `<state_dir>/artifacts-<project>.jsonl`, shown as its file's basename without `.md`.
- **Fallback.** When the live task list is empty, the tasks come from that plan's `<plan>.md.tasks.json`
  and the view is marked `active: false` (rendered dimmed). With no plan line either: the newest
  `docs/superpowers/plans/*.tasks.json` in the session's root, also `active: false`.
- **Owner state.** For each task with an `owner`, the pane of window `✦ <owner>` in the session is
  classified with `board/paneclass.py`: `working`, `waiting` (needs the user) or `ready`. No such window:
  `gone`.
- **Blocked** is derived: `pending` with any `blockedBy` id not `completed`.
- Missing or unreadable files at any step yield an empty or partial view, never an exception.

**Task persistence (probed 2026-10-28).** Completed tasks stay in `session-<id8>/` while any task of the
list is still open (a real dir held 9 completed + 3 pending). Claude Code clears the whole list once every
task is completed (a lone task's file vanished seconds after completion). So the live list carries the done
rows while a plan runs, and the `.tasks.json` fallback gives the dimmed last-plan view after it ends.
`owner` holds the teammate name (`"owner": "parse"` ↔ window `✦ parse`).

## 3. Rendering — `bin/tmux-plan`

- A loop: every 2 s compute the view; redraw (clear + print) only when it changed. Exits on SIGINT;
  respawned by `tmux-dev-layout` if the window's pane died.
- `render(view, width) -> lines` is pure. Header `<plan name> · <done>/<total> done`. Rows:
  `✓` completed, `▶` in progress, `·` pending, `✗` blocked, then the subject cut to the width.
  In-progress rows end `→ <owner> (<state>)`; `waiting` is shown red and bold.
- `active: false`: rows dimmed, header followed by `no active plan`.
- Empty view: `no plans yet · prefix S for a shell`.

## 4. Testing

- `board/tests/test_planview.py` on fixture trees captured from real `~/.claude/sessions`,
  `~/.claude/tasks` and manifest files (scrubbed, origin noted in a fixture README): lead lookup, task
  sort, blocked derivation, owner state, both fallbacks, missing-file cases.
- `render` snapshot tests at a fixed width, including truncation and the three empty/inactive states.
- A zsh test on the scratch tmux server (`lib.zsh`): a new `dev` session has `claude` and `plan` and no
  `shell`; an existing session gains `plan` on the next layout run;
  the plan window's pane runs `tmux-plan`.
- Post-merge user gate: start a plan in a dev session and watch window 2 update as teammates finish tasks.
