# Turn-start spinner: real-state check (spec #2 Task 3)

Finding: on the real lead pane, the first frames of a turn classify as `ready` with this branch's `paneclass` and with `main`'s. The board showed `working` only because a mod state drove it.

## Method

- Target: the lead's pane `%8` (tmux session `agent-board`, window `claude`, command `2.1.325`), read-only (`tmux capture-pane -p -t %8`, HTTP GETs). Nothing was typed into any pane.
- Loop: `loop.zsh <outdir> 45` in the scratch dir, one `capture-pane` plus one `GET /<token>/api/state` on an ephemeral board per pass, each saved as `<epoch>.pane` and `<epoch>.board`. Board: `TMUX_DASH_TOKEN=<random> TMUX_DASH_PORT=7710 python3 board/server.py` from the worktree (PID 44566, stopped afterwards; `ps` says gone, port 7710 free).
- Run1: 92 captures from epoch 1794710781.110 to 1794710825.572 (44.5 s). Median gap 0.28 s, mean 0.49 s, max 2.56 s (the board poll in each pass). The gap is above the 0.25 s target; the turn-start frames themselves are 0.23 to 0.5 s apart.
- Trigger: a SendMessage to the lead at about 1794710786; the lead was idle before it. Run once; no repeat was needed.
- Captures are in the scratch dir `.../scratchpad/caps/run1/`; three are copied as fixtures (below).

## Earliest first frame

- Last idle capture: 1794710785.280 (fixture `idle-with-teammates.txt`): no spinner line, `busy/ready` row present. The turn's first spinner frame is 1794710785.559 (the `› Message from @spin-check` row and an animated spinner, `✢` then `✶` then `✽`), about 1.06 s before the board's mod-driven `working` at 1794710786.616. First `working` per `/api/state`: 1794710786.616 (fixture `turn-start-task-label.txt`); the board still read `ready` at 785.559 and 786.286 because the mod state lagged.
- That capture is not the `✢ Thinking…` shape `SPINNER_FIRST_RE` expects. Rows from the spinner to the input rule, verbatim:

```
✶ Plan & run: docs/superpowers/specs/2026-11-11-turn-start-spinner-rule-design.md…
  ⎿  ◼ Plan & run: docs/superpowers/specs/2026-11-11-turn-start-spinner-rule-design.md › blocked by #23
     ◼ S2 Task 3: real-state turn-start check
     ◻ Plan & run: docs/superpowers/specs/2026-11-12-execution-analytics-design.md#part-1 › blocked by #2
     ◻ Plan & run: docs/superpowers/specs/2026-11-11-discord-replaces-telegram-design.md › blocked by #3
     ◻ Plan & run: docs/superpowers/specs/2026-11-11-discord-bridge-visibility-design.md › blocked by #4
      … +13 pending, 5 completed
busy 1 · ready 1                                                                                           [-]

───────────────────────────────────────────────────────────────────────────────────────────────────────────────
```

- The label is the in-progress task's subject (spaces, a colon, slashes), the rows below are the task list (no tip row), and a column-0 `busy N · ready N … [-]` teammate row sits before the rule.
- Later frames (1794710788.519, fixture `turn-start-task-label-elapsed.txt`) add `(2s · ↓ 7 tokens)` after the label; the label is still multi-word.

## Classification (mod None)

- `classify("2.1.325", rows, False, None)` with this worktree's `board/paneclass.py` on 1794710786.286, 786.616, 787.075, 788.279, 788.519, 790.019, 792.395, 792.908: `('claude', 'ready')` for every one; `spinner_live` is False for every one.
- The same eight captures through `main`'s paneclass (`git show main:board/paneclass.py`, scratch copy): `('claude', 'ready')` for every one.
- Cause: `SPINNER_RE` and `SPINNER_FIRST_RE` match one word before `…` (`[\w-]+…`), and `spinner_live` also rejects any column-0 row between the spinner and the rule, which the `busy/ready` row is.

## Board

- `/api/state` for `%8` read `ready` up to 1794710786.286 (a spinner was already on screen from 785.559) and `working` from 1794710786.616 on, through the turn.
- A mod state drove it: the board prefers a fresh agent-status state over pane text, and the offline pane-text result above is `ready` at the same epochs. So the live board hid the gap, and `mod_states()` read afterwards gave `%8: ready`.

## Fixtures

- `turn-start-task-label.txt`, `turn-start-task-label-elapsed.txt` and `idle-with-teammates.txt` are verbatim copies of run1 captures 1794710786.616, 1794710788.519 and 1794710785.280, each with a line in the fixtures README. They differ in shape from `working.txt` (task list and teammate row instead of a tip), so they are added.

## After Task 4

Run2 on commit e76e40c (Task 4), same pane `%8`, mod=None classification with this worktree's `board/paneclass.py`.

- Method: a capture loop (`capture-pane -p -t %8`, 0.1 s sleep) and a separate board poll loop (`/api/state`, same ephemeral 7710 board method, token from `TMUX_DASH_TOKEN`), 60 s, 281 captures from 1794711222.323 to 1794711280.865: median gap 0.19 s, max 0.92 s. Trigger: the probe message to the lead, which arrived at about 1794711227.5. The board (PID 61991) was stopped afterwards: `ps` says gone, port 7710 has no listener. Nothing was typed into any pane.
- Last pre-turn frame, 1794711227.210: `classify` gives `('claude', 'ready')` (expected); the board read `ready`.
- First spinner frame, 1794711227.740 (the `› Message from @spin-check` row and `✶ Plan & run…`): `classify` gives `('claude', 'working')` (expected). The board still read `ready` (poll at 1794711227.233); it read `working` from 1794711227.843. So the pane-text rule is about 0.1 s ahead of the mod state here.
- Elapsed frame, 1794711230.704 (`✳ Plan & run: docs/superpowers/specs/2026-11-11-turn-start-spinner-rule-design.md… (3s · ↓ 4 tokens)`): `classify` gives `('claude', 'working')`; the board read `working` (a mod state drove it: it prefers a fresh mod state over pane text).
- Rows of the first frame, spinner to input rule, verbatim (capture 1794711227.740; the later frame 1794711227.988 is identical with `✽`):

```
✶ Plan & run: docs/superpowers/specs/2026-11-11-turn-start-spinner-rule-design.md…
  ⎿  ◼ Plan & run: docs/superpowers/specs/2026-11-11-turn-start-spinner-rule-design.md › blocked by #23, #24
     ◼ S2 Task 3: real-state turn-start check › blocked by #24
     ◼ S2 Task 4: task-label spinners + teammate row
     ◻ Plan & run: docs/superpowers/specs/2026-11-12-execution-analytics-design.md#part-1 › blocked by #2
     ◻ Plan & run: docs/superpowers/specs/2026-11-11-discord-replaces-telegram-design.md › blocked by #3
      … +14 pending, 5 completed
busy 2 · ready 1                                                                                           [-]

───────────────────────────────────────────────────────────────────────────────────────────────────────────────
```

- Result: the three expected outcomes hold (ready, working, working). Over all 146 run2 frames that have a task-label spinner, the 130 single-row ones all classify `working`.
- Gap found: the 16 other frames (11% of them) classify `ready` while the board said `working`. They are frames where the spinner line wraps onto two rows, e.g. `✢ Plan & run: …design.md… (running PostToolUse hook ·` then `4s · ↓ 9 tokens)` at column 0 (captures 1794711231.512, 1794711234.491, 1794711266.287, 1794711270.990). The wrapped `running Stop hooks… N/4` and `running PostToolUse hook` suffixes make the line longer than the 111-column pane. The glyph row does not end with `…` or `)`, so neither spinner regex matches it, and the column-0 continuation row would also be rejected. Mid-turn the board's mod state hides it; for a pane-text-only reader (the watchdog) it is a false `ready`.

