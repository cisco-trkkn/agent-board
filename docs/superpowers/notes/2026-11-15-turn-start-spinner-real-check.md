# Turn-start spinner: real-state check (spec #2 Task 3)

Finding: on the real lead pane, the first frames of a turn classify as `ready` with this branch's `paneclass` and with `main`'s. The board showed `working` only because a mod state drove it.

## Method

- Target: the lead's pane `%8` (tmux session `agent-board`, window `claude`, command `2.1.325`), read-only (`tmux capture-pane -p -t %8`, HTTP GETs). Nothing was typed into any pane.
- Loop: `loop.zsh <outdir> 45` in the scratch dir, one `capture-pane` plus one `GET /<token>/api/state` on an ephemeral board per pass, each saved as `<epoch>.pane` and `<epoch>.board`. Board: `TMUX_DASH_TOKEN=<random> TMUX_DASH_PORT=7710 python3 board/server.py` from the worktree (PID 44566, stopped afterwards; `ps` says gone, port 7710 free).
- Run1: 92 captures from epoch 1794710781.110 to 1794710825.572 (44.5 s). Median gap 0.28 s, mean 0.49 s, max 2.56 s (the board poll in each pass). The gap is above the 0.25 s target; the turn-start frames themselves are 0.23 to 0.5 s apart.
- Trigger: a SendMessage to the lead at about 1794710786; the lead was idle before it. Run once; no repeat was needed.
- Captures are in the scratch dir `.../scratchpad/caps/run1/`; three are copied as fixtures (below).

## Earliest first frame

- Last `ready` capture: 1794710786.286 (fixture `idle-with-teammates.txt`). First `working` per `/api/state`: 1794710786.616 (fixture `turn-start-task-label.txt`).
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

- `/api/state` for `%8` read `ready` up to 1794710786.286 and `working` from 1794710786.616 on, through the turn.
- A mod state drove it: the board prefers a fresh agent-status state over pane text, and the offline pane-text result above is `ready` at the same epochs. So the live board hid the gap, and `mod_states()` read afterwards gave `%8: ready`.

## Fixtures

- `turn-start-task-label.txt`, `turn-start-task-label-elapsed.txt` and `idle-with-teammates.txt` are verbatim copies of run1 captures 1794710786.616, 1794710788.519 and 1794710786.286, each with a line in the fixtures README. They differ in shape from `working.txt` (task list and teammate row instead of a tip), so they are added.

## After Task 4

