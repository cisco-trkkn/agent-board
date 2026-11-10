# Interactive tasks window: queue overview, filters, history

Date: 2026-11-10 · Idea: 98 in `~/.local/state/agent-board/ideas/agent-board.md`
Builds on: `docs/superpowers/specs/2026-11-05-tasks-window-polish-design.md`; code `board/taskwin.py`,
`board/taskwin_state.py`, `board/planview.py`

## Problem

On a long overnight queue the user loses track of what has been done, what is running and what is coming. The
`tasks` window (`board/taskwin.py watch`) is a 1 s render loop with no input: it draws the current task list as a
graph or a list, and its state (`taskwin_state`) is cleared whenever the lead's session id changes (relay, restart,
`/clear`), so finished work disappears.

## Decisions

The user chose: a **Queue overview**, **Filter / collapse**, and **History** (journal from now on plus past ledgers and
queue reports). A per-task detail pane was not chosen. The window stays read-only.

## Design

### 1. Input and view state

- `watch` puts stdin in cbreak mode (`termios`/`tty.setcbreak`, restored in `finally` and on SIGTERM/SIGHUP) when
  `sys.stdin.isatty()`, and waits for keys with `select.select([stdin], [], [], interval)` instead of `time.sleep`.
  A key redraws at once. Not a TTY → today's behaviour (sleep, no keys). `render` (the CLI subcommand) is unchanged.
- Escape sequences: arrow keys (`ESC [ A/B`) decode to up/down; a lone ESC is ignored.
- Pure function `handle_key(ui, key, model) -> ui` in a new module `board/taskwin_ui.py`; `ui` =
  `{"view": "queue"|"plan"|"history", "cursor": {view: int}, "filter": "all"|"hide_done"|"active",
  "collapsed": {key: bool}, "help": bool}`. Keys:

  | Key | Effect |
  | --- | --- |
  | `Tab` | next view (queue → plan → history → queue) |
  | `1` `2` `3` | queue / plan / history |
  | `j`, `↓` / `k`, `↑` | cursor down / up (clamped to the rows of the current view) |
  | `Enter` | toggle collapse of the row under the cursor; on the running queue item: switch to plan view |
  | `f` | filter: all → hide_done → active (in_progress + blocked pending) → all |
  | `c` | collapse all finished rows, or expand all when they are all collapsed |
  | `?` | toggle a one-line key help at the bottom |
  | `q` | queue view |

- `ui` is stored in the existing taskwin state file under key `"ui"` and is **kept across a lead change** (today
  `update` clears the whole dict; it must keep `ui`).
- Default view at first start: `queue` when any task subject starts with `Plan & run:`, else `plan`.

### 2. Queue view

Rows: every task whose subject starts with `Plan & run:`, in id order. Each row: status glyph (same glyphs as cards),
spec title (the spec file's first `# ` heading if readable from `--root`, else the path), start → end time (from
taskwin_state timing), outcome (`metadata.outcome` verbatim: `merged <sha>`, `mr <url>`, `kept <branch>`,
`failed — <why>`; `failed` in red).

The `in_progress` item is expanded by default: one summary line for the non-`Plan & run:` tasks of the list
(`<done>/<total> · <n> running · <n> blocked`) and one line per running task (`#id subject · owner · duration`).
When the list has no `Plan & run:` tasks the view shows `no queue` and a hint `2: plan`. The morning report, when
`docs/superpowers/reports/<date>-queue.md` exists for the queue's first `answeredAt` date, is named in the header.

### 3. Plan view

Today's graph/list rendering of the non-`Plan & run:` tasks, plus:

- a cursor (reverse-video row in list mode, highlighted card border in graph mode);
- the filter applied before layout (`hide_done` drops completed tasks; `active` keeps in_progress and pending tasks
  whose blockers are open);
- collapse: with finished rows collapsed, completed tasks are replaced by one line `✓ <n> done` at the top. The
  header shows the filter when it is not `all` (`filter: hide done`).

### 4. History

- Journal: `<TC_STATE>/taskwin/<project>.history.jsonl`, `<project>` = the session group, else the session name
  (the ideas key). `taskwin_state.update` gets the project and the plan name (`view["name"]`) and appends:
  - `{"kind":"task_done","at","plan","id","subject","owner","tier"}` when a non-`Plan & run:` task turns completed;
  - `{"kind":"queue_outcome","at","spec","outcome"}` when a `Plan & run:` task turns completed (`spec` = the path
    after `Plan & run: `, `outcome` = `metadata.outcome` or `""`).
  Dedupe on (`kind`, `plan` or `spec`, `id`, `subject`) against the last 500 lines. Cap 5000 lines: when an append
  makes the file longer, rewrite it with the newest 5000 (`.tmp` + `os.replace`). I/O errors are ignored, as today.
  Appends use the transition already detected for the `done` event, so a task already completed when the window
  first sees it is not journaled (no back-fill from a cold start).
- Past plans: `docs/superpowers/ledgers/*/progress.md` under `--root`: line 1 `# SDD ledger — plan: <path>`, line 2
  `Spec: <path> · branch <b> · base <sha>`; date = the folder name's `YYYY-MM-DD` prefix. Queue outcomes:
  `docs/superpowers/reports/*-queue.md`, the `## Outcomes` table rows (`| # | Spec | Outcome | Ledger |`). Parsed
  results are cached by (path, mtime). Unparseable files are skipped.
- View: newest first, grouped by day, then by plan. A plan row: `<plan name> · <n> tasks · <outcome>` (n from the
  journal; outcome from a journal `queue_outcome` or a report row matching the spec; `—` when unknown). Collapsed by
  default; Enter expands to its journaled tasks (`✓ #id subject · owner · tier · HH:MM`), or, for a plan with no
  journal lines, its ledger folder path. The filter does not apply to history.

### 5. Layout and limits

The view tabs are drawn in the header line (`[1 queue] 2 plan 3 history`, active one bold). Each view scrolls to keep
the cursor visible. The window never writes tasks, never runs git, and reads only the task list, its state file,
the journal, and the two docs folders. Render stays within the existing frame budget: history parsing is cached and
the journal is read only when the history view is shown or on append.

## Error handling

A bad key, a malformed journal line or ledger, or a missing `--root` docs folder never kills the window (skipped;
the existing per-tick error line catches the rest). Terminal mode is always restored on exit.

## Testing

- `board/tests/test_taskwin_ui.py`: `handle_key` for every key, cursor clamping, filter cycle, collapse-all toggle,
  default view with and without `Plan & run:` tasks; arrow escape decoding.
- Rendering at fixed sizes (in-process `taskwin.render` as in `test_taskwin`): queue rows with each outcome kind and
  the expanded running item; plan view with each filter and with collapse; history grouping with journal + ledger +
  report sources; header tabs.
- `taskwin_state`: `ui` kept across a lead change; journal append on transition only, dedupe, 5000 cap, project
  key from a session group.
- Parsers against the real files in this repo (`docs/superpowers/ledgers/2026-11-09-remote-access/progress.md`,
  `docs/superpowers/reports/2026-11-05-queue.md`): plan, spec, branch, and 11+ outcome rows.
- `tools/tests/e2e-tasks-window.zsh` (scratch tmux): send `3`, `j`, Enter, `f`, `Tab` to the window and assert the
  captured pane shows each view; after killing and restarting the window, the view and filter are kept.

## Out of scope

A task detail pane; editing or reordering tasks from the window; mouse input; history from before this ships beyond
what ledgers and reports record.
