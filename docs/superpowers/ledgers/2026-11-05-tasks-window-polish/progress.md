# SDD ledger — plan: docs/superpowers/plans/2026-11-05-tasks-window-polish.md
Spec: docs/superpowers/specs/2026-11-05-tasks-window-polish-design.md
Preflight:
| pair/task | produces → consumes | found |
| T1–T2 (taskwin.py) | T1 tier_model kw threaded through render/_graph_lines/_list_lines → T2 adds flash_ids/crit/color args to same funcs | ok: T2 must keep tier_model param |
| T2–T3 (taskwin.py, wide.txt) | T2 regenerates wide.txt with * → T3 regenerates again with lanes | ok: T3 diff must keep * |
| T3–T4 (taskwin.py) | T3 lane/arrow _draw_edges with +1 rows → T4 parametrises edge row by card_h | ok |
| T2–T4 | T2 * marker in _draw_card → T4 compact top row also needs it | ok, T4 AC says so |
| T1–T5, T4–T5 | load_tier_model + all layouts → T5 renders | ok |
| T1 self | tests vs code: _badge merge {**TIER_MODEL, **tier_model}; raw 'opus' stays None | ok |
| T2 self | +N math checked by probe (+14, +15); crit of SIX = 3,4,6 | ok |
| T3 self | tests carry <hand-derived> placeholders the implementer fills before RED | ok (intentional, standard tier) |
| T4 self | roots_plan(9)@120x40 and (12)@120x50 = LIST on main, (9)@120x200 = GRAPH (probed) | ok |
| T5 self | newest plan by filename = this plan's tasks.json | ok |
Ruling: spec's 9-root@120x50 premise does not reproduce (44 rows fit); tests use 9 roots@120x40 and 12 roots@120x50 — the spec's example size was off — threshold the user saw may differ, behaviour same.
Ruling: compact bottom drops badge, then owner, duration last — spec's "duration last to go" — owner may hide before a duration on narrow compact cards.
Ruling: header keeps naming one done task; only card/list flash is a set — spec scopes the change to flash_ids — header shows one of several completions.
Ruling: routing re-read when view name changes — "once per plan change" — a routing edit mid-plan shows after the next plan switch or window restart.
Task 10: dispatched polish (sonnet) base b4b632e
Task 10: bounce check green; review dispatched to rev (sonnet) b4b632e..bf1c92b
Task 10(T1): minor (deferred): reload follows plan-name changes only (ruled)
Task 10(T1): minor (deferred): render CLI subcommand's load_tier_model arg untested
Task 10(T1): minor (deferred): empty-string mapped value gives no badge
Task 10(T1): complete (commits b4b632e..bf1c92b, review clean)
Task 11(T2): dispatched polish base bf1c92b
Task 11(T2): bounce check green; review dispatched (rev) bf1c92b..990eb57
Task 11(T2): minor (deferred): _no_marks in ColourTest no longer checks alignment
Task 11(T2): minor (deferred): height 4 — done summary can take the only body row, unfinished hidden with no +N more
Task 11(T2): minor (deferred): done_ev unused in render; crit=None fallbacks dead; one ~130-char line in _list_line
Task 11(T2): complete (commits bf1c92b..990eb57, review clean)
Task 12(T3): dispatched polish base 990eb57
Task 12(T3): bounce check green; review dispatched (rev) 990eb57..9f92daa
Task 12(T3): minor (deferred): old ┤ branch in _draw_edges dead; five-blocker test checks border on row 0 only; spanning test doesn't pin blocker 2's gutter-1 lane; straight edge still takes a lane
Task 12(T3): complete (commits 990eb57..9f92daa, review clean)
Task 13(T4): dispatched polish base 9f92daa
Task 13(T4): bounce check green; review dispatched (rev) 9f92daa..ce6a7bf
Task 13(T4): minor (deferred): drawer chosen inside loop in _graph_lines + mis-indented continuation; _draw_compact duplicates top-row logic; no compact flash test; ┤ branch still dead
Task 13(T4): complete (commits 9f92daa..ce6a7bf, review clean)
Task 14(T5): dispatched polish base ce6a7bf
Task 14(T5): bounce check green; review dispatched (rev) ce6a7bf..a4da84c
Task 14(T5): minor (deferred): notes say plan ids 0-based but handoff-relay plan runs 1-14; block 1 '0/5 done' needs a note; newest-plan five-way date tie, alphabetically last used
Task 14(T5): complete (commits ce6a7bf..a4da84c, review clean)
Final review: dispatched finalrev5 (session level) d90ef37..a4da84c
Final review: ready to merge; 1 Important — exit and entry share a row, so one blocker's exit joins another's entry (wide.txt line 7 reads 2→5)
Ruling: full cards leave at +1 and enter at +2 (fix now); compact cards keep +0 for both as the spec fixes — spec §1's goal is who-blocks-whom; compact has no spare row the spec allows — compact graphs keep the ambiguity in that shape
Ruling: no deferred minor blocks merge (final reviewer triage); notes line 3 wording fixed in the same wave
Final fix: commits a4da84c..6dd292a, bounce check green; scoped re-review dispatched (rev)
Final re-review: finding 1 ADDRESSED, finding 2 ADDRESSED; new Important (doc): real-render notes predate the edge-row change
Ruling: regenerate the notes' four renders (Task 5 method) and have the lead byte-compare blocks 1-3 to in-process renders instead of a second review wave — the skill allows one fix wave; the notes are morning-report evidence — a wrong findings line in the live-list block would go unreviewed
Final: notes regenerated 8b57a03; lead byte-compared blocks 1-3 to fresh renders (3/3 equal), id/session grep 0
Ruling: block 4 of the notes renders this lead's own team list (the dir used in Task 5) rather than another session's now-newer dir — keeps the Task 5 source stable — the live block shows this queue's tasks, not an unrelated plan
