# The `tasks` window: a live, graphical view of the lead's task list

Idea (2026-11-04 11:24): "improve claudes native task tool" — the user: "make it more useful, more engaging,
maybe give it its own window with fun formatting and colors and shapes".

## Context

On 2026-10-29 the old `plan` window (a plain ✓/✗ list from `bin/tmux-plan`) was retired
(`docs/superpowers/specs/2026-10-29-retire-plan-window-design.md`) because it repeated the chat's task list
and drew blocked tasks as ✗. This window must earn its place with what the chat cannot show: a dependency
graph, live owner state, timing and tier, and some delight. The user chose a tmux window (not a board panel
or popup) and all four extras.

## Decisions (user, 2026-11-04)

- A tmux window `tasks` in the dev session, right after `claude`.
- Includes: dependency graph with critical path, live owner state, progress + timing + tier, celebration.
- Stdlib Python only (`python3 -I`, no pip dependency), ANSI rendering, not curses.

## Design

### 1. Data (`board/planview.py`)

- `_norm` adds `tier` (from the description's ```` ```json:metadata ```` fence, key `modelTier`, else `""`;
  a malformed fence gives `""`) and keeps `blockedBy`. `_finish` passes `blockedBy` and `tier` through.
  Existing keys and their values are unchanged; `board/overview.py` and other `view()` consumers ignore
  the new keys. `board/tests/test_planview.py` cases must still pass unchanged.
- Data source stays `view()`: the lead's live list (`~/.claude/tasks/session-<id8>/`), falling back to the
  plan's `.md.tasks.json`; owner state from `owner_states()` (`working`, `waiting`, `ready`, `gone`).

### 2. Timing state

Task JSON has no timestamps. The watcher keeps `$STATE/taskwin/<session>.json`
(`STATE` from `tc_env`, as other board modules resolve it): per task id, `{"status": s, "since": epoch,
"started": epoch|null, "done": epoch|null}`. On each poll, a status change updates `since` (and sets
`started` on first `in_progress`, `done` on `completed`). The plan's start is the earliest `started`. A
write failure is ignored (timing shows `—`). The file is reset when the lead session id changes.

### 3. Renderer (`board/taskwin.py`, new)

A pure function `render(view, timing, width, height, now, frame, color) -> str`, plus `watch()`, a loop
that polls once a second, redraws with cursor-home + clear-to-end (no flicker), hides the cursor, restores
it on exit, and re-reads the size each frame (`shutil.get_terminal_size`).

- **Header**: plan name (or "Tasks"), a gradient progress bar (green over grey), `done/total`, and elapsed
  time since the plan's start.
- **Graph (width ≥ 80)**: tasks laid out in columns by dependency depth (depth = longest `blockedBy` chain
  to a root; unknown blocker ids are ignored). Each task is a card with rounded borders (`╭╮╰╯`), joined by
  box-drawing arrows from blocker to dependent. If the graph is taller than the window, completed columns
  collapse to a one-line `● 1–4 done` summary first.
- **Critical path**: the longest chain of unfinished tasks; its cards get a bold accent (magenta) border.
- **Narrow (width < 80)**: a vertical list, one line per task, with `⇠ 2,3` blocker hints.
- **Status glyphs and colours** (no ✗ anywhere):

  | Status | Glyph | Colour |
  | --- | --- | --- |
  | completed | ● | green |
  | in_progress | ◐◓◑◒ (cycles with `frame`) | amber |
  | pending | ○ | grey |
  | blocked | ◌ + 🔒 | dim |

- **Card content**: id and subject (truncated with `…`), tier badge (`haiku` cyan, `sonnet` blue, `fable`
  violet, other/empty: none), owner `✦ <name>` with a state dot (working: pulsing amber; waiting: red
  "needs you"; ready: grey "idle"; gone: dim "gone"), and time in the current status (`12m`).
- **Colour**: truecolor when `COLORTERM` is `truecolor`/`24bit`, else 256-colour; `NO_COLOR` set (any value)
  gives plain text with the same glyphs and layout.
- **Empty**: no tasks gives a friendly idle screen naming the session ("No tasks yet — the lead's list shows
  up here").

### 4. Celebration

- A task that turns `completed` while watched: its card flashes (inverse) and a sparkle line
  `✦ Task <id> done ✦` shows under the header for ~2 s. Fires once per transition (tracked in the timing
  state, so a restart does not replay it).
- All tasks completed: a confetti banner animates for ~5 s, then a calm `Plan done ✓` banner stays.

### 5. Window and layout

- `bin/tmux-dev-layout` creates `tasks` right after `claude`, running
  `python3 -I <repo>/board/taskwin.py watch --session <s>`. It is skipped when `TC_TASKS_WINDOW=0`.
  Idempotent: an existing `tasks` window is left alone. The retired-`plan` cleanup stays.
- `bin/tmux-teammate-window` places `✦` windows after `tasks` when it exists (today: after `claude` and the
  existing teammate windows), so teammates never land between `claude` and `tasks`.
- Docs: add the window to `claude/orchestrator.md`'s windows table, both `tmux-orchestrator` SKILL.md copies,
  `docs/ARCHITECTURE.md`, `docs/CUSTOMIZATION.md` (`TC_TASKS_WINDOW`), and the `bin/dev` /
  `tmux-dev-layout` header comments.

`claude/orchestrator.md` has an uncommitted user change in the live checkout; work happens in a worktree,
and integration must keep that working-tree change intact.

### 6. Tests

- `board/tests/test_taskwin.py`: render at 120 and 60 columns with `NO_COLOR` (stable snapshots); column
  layering for a diamond graph; critical path picks the longest unfinished chain; collapse when too tall;
  tier parsing incl. malformed fence; timing persistence across two polls and a restart; celebration fires
  exactly once per transition; empty view.
- `board/tests/test_planview.py`: new cases for `tier` and `blockedBy`; existing cases untouched.
- `tools/tests/test_layout.zsh`: `tasks` exists right after `claude`; absent with `TC_TASKS_WINDOW=0`; a
  second layout run does not duplicate it.
- `tools/tests/` teammate-window test: a `✦` window lands after `tasks`.
- One e2e run on a scratch tmux server (`-f /dev/null`) with a real copied task directory, capturing the
  pane (`capture-pane -e`) at 120 columns as evidence.

## Out of scope

- Editing tasks from the window (read-only view).
- A board panel or popup variant.
- Changes to Claude Code's own task tools.
