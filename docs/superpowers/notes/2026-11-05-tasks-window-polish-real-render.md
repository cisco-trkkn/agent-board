# tasks-window polish: real-plan renders

Colour-none renders from the finished code (`taskwin.render(view, {}, W, H, time.time(), 0, "none", tier_model=load_tier_model("."))`, so the routing file badges apply and no timing state is passed: durations and `elapsed` show as empty). Task ids come from each file as written (this plan's file is 0-based, the handoff-relay plan's is 1-based).

## 1. This plan (`2026-11-05-tasks-window-polish.md.tasks.json`) at 120x50

```
tasks-window-polish                                                                                 0/5 done   elapsed —
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

╭─ ○ *0 ───────────╮    ╭─ ◌ 🔒 *1 ────────╮    ╭─ ◌ 🔒 *2 ────────╮    ╭─ ◌ 🔒 *3 ────────╮    ╭─ ◌ 🔒 *4 ────────╮
│ Task 1: Tier ba… ├╮   │ Task 2: Every c… ├╮   │ Task 3: Per-blo… ├╮   │ Task 4: Compact… ├╮   │ Task 5: Real-st… │
│ sonnet           │╰──▸│ sonnet           │╰──▸│ sonnet           │╰──▸│ sonnet           │╰──▸│ sonnet           │
╰──────────────────╯    ╰──────────────────╯    ╰──────────────────╯    ╰──────────────────╯    ╰──────────────────╯
```

Findings: full cards; every unfinished task id (0-4) visible; each edge leaves on the subject row (`├╮`) and enters the next card on its badge row (`╰──▸`), the `▸` is never on a border and the exit row carries no `▸`; no overlapping lanes or cut cards.

## 2. The same plan at 200x60

```
tasks-window-polish                                                                                                                                                                 0/5 done   elapsed —
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

╭─ ○ *0 ───────────────────────╮    ╭─ ◌ 🔒 *1 ────────────────────╮    ╭─ ◌ 🔒 *2 ────────────────────╮    ╭─ ◌ 🔒 *3 ────────────────────╮    ╭─ ◌ 🔒 *4 ────────────────────╮
│ Task 1: Tier badges from th… ├╮   │ Task 2: Every completion fl… ├╮   │ Task 3: Per-blocker connect… ├╮   │ Task 4: Compact cards for t… ├╮   │ Task 5: Real-state render c… │
│ sonnet                       │╰──▸│ sonnet                       │╰──▸│ sonnet                       │╰──▸│ sonnet                       │╰──▸│ sonnet                       │
╰──────────────────────────────╯    ╰──────────────────────────────╯    ╰──────────────────────────────╯    ╰──────────────────────────────╯    ╰──────────────────────────────╯
```

Findings: full cards with longer subjects; every unfinished task id (0-4) visible; same exit/entry glyphs as block 1, no `▸` on a border, no glyph problem.

## 3. `2026-10-16-handoff-relay-artifacts-panel.md.tasks.json` (14 tasks) at 120x50

```
handoff-relay-artifacts-panel                                                                     14/14 done   elapsed —
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                                                      Plan done ✓
╭─ ● 1 ────────╮    ╭─ ● 4 ────────╮    ╭─ ● 5 ────────╮    ╭─ ● 10 ───────╮    ╭─ ● 11 ───────╮    ╭─ ● 14 ───────╮
│ Task 1: Sha… ├╮   │ Task 4: Two… ├──╮ │ Task 5: `tm… ├──╮ │ Task 10: Bo… ├╮   │ Task 11: Bo… ├──╮ │ Task 14: Li… │
│ haiku        ││ ╭▸│ sonnet       │╭┬┼▸│ haiku        │ ╭┼▸│ sonnet       │├──▸│ sonnet       │╭┬┼▸│ sonnet       │
╰──────────────╯│ │ ╰──────────────╯│││ ╰──────────────╯ ││ ╰──────────────╯│   ╰──────────────╯│││ ╰──────────────╯
                ├┬┼─────────────────┴┼┼──────────────────┴┼─────────────────┴┬┬─────────────────┴┴╯
╭─ ● 2 ────────╮│││ ╭─ ● 6 ────────╮ ││ ╭─ ● 9 ────────╮  │ ╭─ ● 12 ───────╮ ││
│ Task 2: Art… ├┼┤│ │ Task 6: `re… ├─┼┤ │ Task 9: Ide… ├──┤ │ Task 12: Ha… ├─╯│
│ sonnet       │├┼┼▸│ sonnet       │ ╰┼▸│ sonnet       │  ├▸│ fable        │  │
╰──────────────╯│││ ╰──────────────╯  │ ╰──────────────╯  │ ╰──────────────╯  │
                │││                   ├─────────────────╮ │                   │
╭─ ● 3 ────────╮│││ ╭─ ● 8 ────────╮  │                 │ │ ╭─ ● 13 ───────╮  │
│ Task 3: Hid… ├┼┼┤ │ Task 8: Art… ├──╯                 │ │ │ Task 13: Pr… ├──╯
│ sonnet       │╰┴┼▸│ sonnet       │                    ╰─┴▸│ sonnet       │
╰──────────────╯  │ ╰──────────────╯                        ╰──────────────╯
                  │
╭─ ● 7 ────────╮  │
│ Task 7: `id… ├──╯
│ haiku        │
╰──────────────╯
```

Findings: full cards; all 14 ids visible (plan complete, so no unfinished task); every `▸` sits at the cell left of a `│` border on a badge row and no exit row carries one; lanes past the third in a gutter share the last lane by design (crossings draw `┼`); I checked these invariants, not each of the plan's edges one by one; no cut or overlapping cards.

## 4. A live task list from `~/.claude/tasks/<session>/` (14 tasks, read-only) at 120x50

```
live list                                                                                          9/14 done   elapsed —
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━───────────────────────────────────────────

╭─ ● 1 ────────────╮    ╭─ ◌ 🔒 *6 ────────╮    ╭─ ◌ 🔒 *7 ────────╮    ╭─ ◌ 🔒 *8 ────────╮    ╭─ ◌ 🔒 *9 ────────╮
│ Plan & run: doc… │    │ Plan & run: doc… ├╮   │ Plan & run: doc… ├╮   │ Plan & run: doc… ├╮   │ Plan & run: doc… │
│                  │╭──▸│                  │╰──▸│                  │╰──▸│                  │╰──▸│                  │
╰──────────────────╯│   ╰──────────────────╯    ╰──────────────────╯    ╰──────────────────╯    ╰──────────────────╯
                    │
╭─ ● 2 ────────────╮│   ╭─ ● 11 ───────────╮    ╭─ ● 12 ───────────╮    ╭─ ● 13 ───────────╮    ╭─ ● 14 ───────────╮
│ Plan & run: doc… ││   │ Task 2: Flash a… ├─╮  │ Task 3: Per-blo… ├─╮  │ Task 4: Compact… ├─╮  │ Task 5: Real-st… │
│                  ││╭─▸│ ✦ polish         │ ╰─▸│ ✦ polish         │ ╰─▸│ ✦ polish         │ ╰─▸│ ✦ polish         │
╰──────────────────╯││  ╰──────────────────╯    ╰──────────────────╯    ╰──────────────────╯    ╰──────────────────╯
                    ││
╭─ ● 3 ────────────╮││
│ Plan & run: doc… │││
│                  │││
╰──────────────────╯││
                    ││
╭─ ● 4 ────────────╮││
│ Plan & run: doc… │││
│                  │││
╰──────────────────╯││
                    ││
╭─ ◐ *5 ───────────╮││
│ Plan & run: doc… ├╯│
│                  │ │
╰──────────────────╯ │
                     │
╭─ ● 10 ───────────╮ │
│ Task 1: Tier ba… ├─╯
│ ✦ polish         │
╰──────────────────╯
```

Findings: full cards; all 5 unfinished ids (5, 6, 7, 8, 9) visible with the critical path 5-9 starred; owner names kept; the edges from tasks 5 and 10 climb their own lanes (`├╯`, `├─╯`) to the badge-row entries of 6 and 11, no `▸` on a border, no glyph problem.
