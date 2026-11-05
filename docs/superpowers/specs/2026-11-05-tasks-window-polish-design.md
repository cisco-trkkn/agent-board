# Tasks window polish

Date: 2026-11-05 · Status: approved design, awaiting spec review
Group 3 of the ideas (ideas file, four 2026-11-05 00:04 "tasks window: …" entries).
Builds on the tasks window (`board/taskwin.py`, plan ledger `docs/superpowers/ledgers/2026-11-04-tasks-window/`).

`render()` stays pure (no I/O, no clock, no tmux); everything new it needs arrives as an argument.

## 1. Per-edge connectors with arrowheads

Today every edge into a column shares one bus (`_draw_edges`: `bus_a = xs + 2`), so with several blockers
feeding several dependents the vertical lines merge and who-blocks-whom is lost.

- Each distinct blocker feeding a gutter gets its own vertical lane: lane `k` (0-based, in blocker order:
  column, then row) at `xs + 1 + k`, for `k < GUTTER - 1` (3 lanes in the 4-cell gutter). The k-th lane is
  used for both the adjacent-column case and the spanning case (`bus_a`); the spanning case's second bus
  (`bus_b`) gets lanes the same way within the destination's gutter.
- More distinct blockers than lanes in one gutter: the extra ones share the last lane (today's behaviour,
  limited to the overflow).
- Every edge ends with `▸` in the cell just left of the dependent card's left border (replacing the `─`
  there). Where two edges enter the same card at the same row, one `▸`.
- Junction glyphs keep using `_LINE`; crossings of two lanes draw `┼`.

## 2. Tier badges from the routing file

`TIER_MODEL` is hard-coded (`mechanical → haiku`, …). The repo's `docs/superpowers/model-routing.json`
maps tiers to models and may differ.

- `render()` takes an optional `tier_model` mapping (default `TIER_MODEL`), used by `_badge`.
- `watch()` reads `<root>/docs/superpowers/model-routing.json` (root = the plan's repo root it already
  resolves) once per plan change, takes its `mechanical` / `standard` / `frontier` string values, and
  passes them; a missing, unreadable or malformed file, or a non-string value, falls back to `TIER_MODEL`
  for that tier. `"inherit"` shows no badge.
- Badge colours: `TIER_STYLE` by model name as now; an unknown model name renders in the default style.

## 3. Small items

- **Sparkle every completion in the window.** `render` today flashes only the first `done` event inside
  `DONE_TTL` (`flash_id`). It flashes every task whose `done` event is within `DONE_TTL` of `now`
  (`flash_ids`, a set), in both layouts.
- **`+N more` in the list layout.** When unfinished tasks exceed the rows available, the last row shows
  `+N more` (N = unfinished tasks not shown), grey. Completed tasks are dropped before unfinished ones, as
  the list does now; `+N more` counts only unfinished ones.
- **NO_COLOR critical-path marker.** With `color == "none"`, a critical-path card shows `*` right before its
  id in the top border (`╭─ ◐ *3 ───╮`), and a list-layout line shows `*` before the id. Colour modes are
  unchanged (accent colour only).

## 4. Compact cards for tall graphs

A 14-task plan with 9 root tasks falls back to the list at 120x50. User decision (2026-11-05): compact cards,
not a wrapped column.

- `_plan_graph` tries, in order: full cards (today); full cards with done columns collapsed (today);
  **compact cards** (new) with the same collapse; then the list.
- A compact card is 2 rows: top `╭─ ◐ 3 subject… ─╮`, bottom `╰─ sonnet · ✦ owner · 12m ─╯` (the badge,
  owner and duration segments as on a full card's rows 3–4, dropped right-to-left when they do not fit:
  duration last to go, after badge). `CARD_H` becomes a parameter of the layout (4 or 2); `GAP` stays 1.
- Edge entry and exit rows for compact cards are the top row (`+0`) instead of `+1`.
- Mixed sizes are not used: the whole graph is either full or compact.

## Files

- Modify: `board/taskwin.py` (`_draw_edges`, `_draw_card`, `_plan_graph`, `_graph_lines`, `_list_lines`,
  `_list_line`, `render`, `watch`, `_badge`).
- Tests: `board/tests/test_taskwin.py` (render cases), `board/tests/test_taskwin_cli.py` (routing-file
  read in `watch`).

## Testing

- Render tests, each seen failing first:
  - two blockers feeding two dependents in the next column: distinct lanes and a `▸` at each entry
    (exact glyph rows asserted);
  - five blockers into one gutter: lanes 0–1 distinct, the rest share lane 2;
  - `tier_model={"standard": "opus"}` badges `opus`; `inherit` shows none;
  - two `done` events within `DONE_TTL`: both cards inverse;
  - list layout with more unfinished tasks than rows ends in `+N more` with the right N;
  - `color="none"`: `*` before critical-path ids, none elsewhere;
  - a 14-task, 9-root plan at 120x50 renders compact cards (not the list); at 120x200 renders full cards.
- `watch` reads a temp repo's routing file and falls back on a malformed one.
- A real-state check: render the newest real plan's tasks (copied from a real
  `docs/superpowers/plans/*.md.tasks.json`) at 120x50 and 200x60 and paste both into the report.
- Targeted runs only: `python3 -m unittest board.tests.test_taskwin board.tests.test_taskwin_cli`
  (from the repo root, with `-s board/tests` discovery if module paths need it); not the full board suite.

## Not in scope

Board (browser) plan view; the tasks-window e2e (`tools/tests/e2e-tasks-window.zsh`) is not changed.
