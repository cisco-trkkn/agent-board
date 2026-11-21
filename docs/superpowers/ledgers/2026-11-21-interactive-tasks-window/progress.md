# SDD ledger — plan: docs/superpowers/plans/2026-11-21-interactive-tasks-window.md
Spec: docs/superpowers/specs/2026-11-10-interactive-tasks-window-design.md · branch interactive-tasks-window · base 403f675
Preflight scan (stale check: fresh after rebase onto 403f675):
| pair/task | produces → consumes | found |
| 1→5,8 | planview task fields outcome/answeredAt/planPath → queue rows, ctx | consistent |
| 2→8 | taskwin_state.update(journal,plan), journal_path, spec_of, load/save → watch | consistent |
| 3→5,6,7,8 | taskwin_views.model/split/plan_tasks/queue_label, taskwin_ui.normalize/clamp/is_collapsed/decode/handle_key → render, watch | consistent |
| 4→5,7,8 | taskwin_hist.hm/entries/queue_report/spec_title → render, watch | consistent |
| 5,6,7,8 | all modify board/taskwin.py + test_taskwin_screens.py | sequential by blockedBy, no parallel writers |
| 9→10→11 | e2e → full suite → user gate | consistent |
| each task 1-11 | tests vs code, files created vs touched | self-consistent (Task 4 docstring names append_journal only, no import) |
Ruling: accept plan assumptions A1-A7 as written — each matches the spec's intent and the plan prices each as a one-line change — cost if wrong: small UI rework in taskwin_views/taskwin.
Ruling: run Tasks 1-4 in parallel (disjoint files, no blockedBy), review as one mechanical batch — cost if wrong: one task re-review.
Batch 1-4 base: e77c510
Task 1: dispatched impl-t1 (mechanical, haiku)
Task 2: dispatched impl-t2 (mechanical, haiku)
Task 3: dispatched impl-t3 (mechanical, haiku)
Task 4: dispatched impl-t4 (mechanical, haiku)
Task 1: green check ok (verify rc 0) — b4a2663
Task 2: green check ok (verify rc 0) — b0dde8d
Task 3: green check ok (verify rc 0) — 1d2da77
Task 4: green check ok (verify rc 0) — 9b9245f
Batch 1-4: review dispatched rev-b1 (standard) on e77c510..a877289
Batch 1-4: reviewed together (4 tasks) — T1-T3 spec ✅ approved; T4 spec ❌ 2 Important
Task 1: complete (commits e77c510..b4a2663, review clean)
Task 2: minor (deferred): journal append glues onto a partial last line after a crash (taskwin_state.py:83)
Task 2: minor (deferred): queue_outcome dedupe (kind,spec) drops a re-run's second outcome within 500 lines (spec's key)
Task 2: minor (deferred): QUEUE_PREFIX defined in taskwin_state and taskwin_ui
Task 2: complete (commits b4a2663..b0dde8d, review clean)
Task 3: minor (deferred): handle_key normalizes with [] tasks → invalid view repairs to plan
Task 3: minor (deferred): ui.collapsed keeps stale keys forever
Task 3: minor (deferred): no test for filter+collapse together or ESC O A; renderer must clamp cursor itself (check in T5/T6)
Task 3: complete (commits b0dde8d..1d2da77, review clean)
Task 4: Ruling: fix plan-mandated Important 1 (type-invalid journal lines raise) and 2 (report row attaches by spec before ledger) plus #part spec-match minor — spec's never-raises rule and correct outcomes outrank the plan's verbatim code — cost if wrong: ~15 lines and 3 tests
Task 4: minor (deferred): plan-keyed queue_outcome without entry creates spec: key (collapse state lost later); oldest report wins; queue_report str coercion; ledger branch loose parse; spec_title absolute/.. path; test gaps
Task 4: fix round 1 dispatched (82+/5-, standard re-review rerev-t4) a877289..ad89922
Task 4: fix round 1/5 (3 addressed, 0 open; commits a877289..ad89922)
Task 4: complete (commits 1d2da77..ad89922, review clean)
Task 5: dispatched impl-t5 (standard, sonnet), base ad89922
Task 5: green check ok (136 OK rc 0) — 2ce9968; review dispatched rev-t5 (standard)
Task 5: minor (deferred): test gaps — size sweep only queue/help off; no renderer stale-cursor test; owner-omitted and long-outcome cut untested
Task 5: minor (deferred): queue header reuses _header, so a plan task done banner shows on the queue screen
Task 5: Ruling: queue/history cursor row is inverse across the whole row, not only the gutter — plan constraint "in colour the cursor row is also inverse" — carried into Task 6 dispatch with a test — cost if wrong: one style span
Task 5: complete (commits ad89922..2ce9968, review clean, 4 minor)
Task 6: dispatched impl-t6 (standard, sonnet), base 2ce9968
Task 6: green check ok (150 OK rc 0) — e0ecb8d
Task 6: Ruling: brief's test_collapsed_done_line (default cursor on p:done expecting bare "✓ 1 done") contradicts its own none-colour "> " cursor criterion; implementer moved that test's cursor to row 1 and added a marker test — the criterion is the requirement, the test was the plan's slip — cost if wrong: one test line
Task 6: minor (deferred): graph auto-summarises done cards in ui mode, cursor card may fold away (plan A7)
Task 6: minor (deferred): invert_row conditional needs parens; sel/sel_mark redundant in _list_line; no tests for narrow-header filter note or graph done-line cursor
Task 6: complete (commits 2ce9968..e0ecb8d, review clean, 4 minor)
Task 7: dispatched impl-t7 (standard, sonnet), base e0ecb8d
Task 7: green check ok (158 OK rc 0) — 1d3739c
Task 7: review rev-t7 — spec ❌ 1 Important (history children index t['id']/t['subject'] → KeyError)
Task 7: minor (deferred): blank bold day line for empty day; cursor row's day line can scroll off; only failed outcomes coloured (brief)
Task 7: fix round 1 dispatched to impl-t7 (+ colour inverse test)
Task 7: fix round 1 done df32e8c (12+/1-), re-review rev-t7 (standard)
Task 7: fix round 1/5 (1 addressed, 0 open; commits 1d3739c..df32e8c)
Task 7: complete (commits e0ecb8d..df32e8c, review clean, 3 minor)
Task 8: dispatched impl-t8 (standard, sonnet), base df32e8c
Task 8: green check ok (166 OK rc 0) — f940325, c85e925
Task 8: Ruling: cbreak set and restore use TCSANOW instead of setcbreak's TCSAFLUSH / TCSADRAIN — both hang on a macOS pty with a pending key and TCSAFLUSH drops the key (implementer's 5 s probe) — cost if wrong: unflushed typeahead on start
Task 8: review rev-t8 — spec ❌ 1 Important (key block outside per-tick except: a raising key kills watch)
Task 8: minor (deferred): no direct test for ctx history gating or terminal restore on exception/SIGTERM; ui saved on every read; key sequence split across reads decodes as separate keys
Task 8: fix round 1 dispatched to impl-t8 (+ tcgetattr guard minor)
Task 8: fix round 1 done 54abcf0 (48+/16-), re-review rev-t8 (standard)
Task 8: fix round 1/5 (2 addressed, 0 open; commits c85e925..54abcf0)
Task 8: minor (deferred): unguarded tcsetattr in the new handler; an OSError from _ctx disables keys for good; dropped-key error line overwritten at once
Task 8: complete (commits df32e8c..54abcf0, review clean)
Task 9: dispatched impl-t9 (standard, sonnet), base 54abcf0
Task 9: green check ok (ALL PASS rc 0, 17 checks) — 33107dd
Task 9: minor (deferred): empty ledger stem passes has vacuously; lead-change check only sleeps 3 s; queue rows checked only by absence of "no queue"; fixed sleeps; spec's j key never sent; nothing-written check not asserted in script
Task 9: complete (commits 54abcf0..33107dd, review clean, 6 minor)
Task 10: dispatched impl-t10 (standard, sonnet), base 33107dd
Task 10: complete (no code change; all.zsh ALL PASS 212 jobs rc=4, e2e ALL PASS, history 48/12 0.7 ms, render CLI no tabs, ledgers/reports untouched)
Final review: dispatched rev-final (session level) on 403f675..33107dd
Final review: ready after fixes — 0 Critical, 1 Important (I1 journal writer TypeError on list/dict line), 6 Minor; ledger triage: none must-fix
Final: Ruling: fix M1 (ui=None not byte-identical at heights 4-5) in the same wave — it breaks the plan's render-compatibility constraint — cost if wrong: one line
Final: minor (parked): M2 spec names morning report by earliest answeredAt, orchestrator names it by run start — spec change for the user; M3 history shows — for most plans (only one report exists); M4 history/queue headers count/banner the wrong task set; M5 two windows in one group can race journal dedupe; M6 late task_done attributed to the current plan name
Final: fix wave dispatched fix-final (standard)
Final: fix wave done c247a39; scoped re-review dispatched rerev-final (standard)
Final: re-review — I1 ADDRESSED, M1 ADDRESSED (7920/7920 base-compat cases); commits 33107dd..c247a39
Final: minor (parked): M1 test errors instead of skipping when no git binary; new test class after unittest.main() so direct-run skips it (discover runs it)
