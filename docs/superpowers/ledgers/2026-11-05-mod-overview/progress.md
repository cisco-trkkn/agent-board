# SDD ledger — plan: docs/superpowers/plans/2026-11-05-mod-overview.md
Preflight scan:
| pair/task | produces → consumes | found |
| T1→T2 | status file fields tool{name,arg,startedAt}, turnStartedAt, waiting{kind,detail}, failStreak, lastToolAt → overview agents/reason/alerts | ok; names fixed in Global Constraints |
| T1→T4 | real status file with new fields → fixture | ok |
| T2→T3 | agents[], needs_you[].reason, alert kinds failing/stuck with label/detail → ovRow, notify.conditions | ok; label/detail ruled in plan |
| T2→T4 | server passes mod_records → live API diff | ok |
| T2,T4 test_overview.py | both edit it, sequential | ok |
| T1 self | tests vs code: flat tool.call args (probe) | ok |
| T2 self | old-file fixture reads null/0; mods=None keeps old behaviour | ok |
| T3 self | alertColor amber for new kinds stated | ok |
| T4 self | e2e needs T1-T3 in the worktree plugin/board | ok |
Ruling: plan's five lead rulings (state words busy/needs you/idle; alert label/detail; latest tool wins with parallel calls; mods kwarg; notify kinds keyed by window) stand as written in the plan header — each costs a small UI/API change if wrong.
Ruling: denied/refused calls count toward failStreak (they resolve isError: true; spec counts "reports an error") — if wrong, a run of user denials raises a failing alert.
Task 1: dispatched status8 (standard/sonnet) base f48e421
Task 1: green (215/0, validate ok; touched artifact-register.test.ts runs assertion); review dispatched rev8 f48e421..8f02522
Task 2: dispatched status8 base 8f02522 (parallel with Task 1 review; T2 files disjoint from T1)
Task 1: review spec ok, quality approved
Task 1: minor (deferred): m1 permission/question detail cut to 80 whole, not just the arg
Task 1: minor (deferred): m2 two flushes per tool call (one awaited before next())
Task 1: minor (deferred): m3 parallel calls: tool null when the latest call ends first while an older one runs (plan ruling)
Task 1: minor (deferred): m4 pre-existing: AskUserQuestion next() throwing leaves needs-you and waiting stale
Task 1: minor (deferred): m5 test gaps: Write/MultiEdit args, detail >80, parallel clear, e.tool undefined
Task 1: minor (deferred): m6 failStreak test never starts a turn
Task 1: complete (commits f48e421..8f02522, review clean)
Task 2: green (OK rc 0); review dispatched rev8 8f02522..5befde7; Task 3: dispatched status8 base 5befde7 (files disjoint)
Task 2: review spec ok, quality approved
Task 2: Ruling: stuck counts quiet from lastToolAt even while a tool runs (spec §2 literal) — a single call over 10 min in a 20+ min turn is worth one notice; costs one false "stuck" notice per long test run if wrong.
Task 2: Ruling: failing stays while the file is fresh until a success resets failStreak, also after the turn ends (spec literal) — the last turn ending on 3+ failures is worth showing; costs a lingering badge if wrong.
Task 2: minor (deferred): m1 stale mutation comment test_overview.py:485 (equivalent mutant under defaults)
Task 2: minor (deferred): m2 -Infinity in since/turnStartedAt raises OverflowError (unguarded)
Task 2: minor (deferred): m3 claude-pane loop repeated 3 times in overview.py
Task 2: minor (deferred): m4 cosmetic blank line test_usage.py
Task 2: minor (deferred): m5 second status-dir listing per overview refresh (build_state + build_overview)
Task 2: complete (commits 8f02522..5befde7, review clean)
Task 3: green (38 OK rc 0); review dispatched rev8 5befde7..05de9ff; Task 4: dispatched status8 base 05de9ff (parallel; page check re-run if T3 fix touches the page)
Task 3: review spec ok, quality approved
Task 3: minor (deferred): m1 ovAgentLine dangling "window · " when state and duration both empty (unreachable)
Task 3: minor (deferred): m2 ticking duration replaces the row via syncRows ~1/min (10 s under a minute); hovered tooltip drops (last-run age already did)
Task 3: minor (deferred): m3 ovRow wiring source-asserted only; rendered page is Task 4
Task 3: minor (deferred): m4 a waiting agent shows twice (needs-you line + agent line), per constraints
Task 3: minor (deferred): m5 needs-you notification text lacks the reason
Task 3: complete (commits 5befde7..05de9ff, review clean)
Task 1: reopened — Task 4 real run: AskUserQuestion also fires classic.PermissionRequest, which overwrites waiting with {permission, "AskUserQuestion: "}; reason reads "permission: …" not "question: Color"
Task 1: fix round 1 dispatched to status8 (original implementer) base HEAD
Task 1: fix round 1 committed 45258e3 (218/0, validate ok); re-review dispatched rev8 05de9ff..45258e3
Task 4: green (test_overview OK rc 0); real run: tool line in API and page, "question: Color" after the T1 fix; :7711 vs :7700 diff 53 paths, 2 projects, only agents… added; processes killed
Task 4: Ruling: no separate task review; the session-level final review covers it (record + fixture + one test) — if wrong, a Task 4 defect is found one step later.
Task 4: minor (deferred → final review): page rendered with a node DOM shim over the real ovRow (no jsdom)
Task 4: minor (deferred → final review): reason / fail_streak / turn_s paths absent from real state at diff time
Task 1: fix round 1/5 (1 addressed, 0 open; commits 05de9ff..45258e3)
Task 1: minor (deferred): r1-m1 dialogOpen keep-guard (question kept when new detail empty) untested; mutation survives
Task 1: complete (commits f48e421..45258e3, review clean after 1 fix round)
Task 4: complete (commits 45258e3..0237e04, covered by final review)
Final review: dispatched final8 (session level) 67a5e26..0237e04
Final review: ready with fixes — M1 stuck wording says 'no tool call' while a tool runs; M2 e2e helpers uncommitted; M3 fixture README wrong; 19 deferred minors triaged leave
Final fix: dispatched status8 (standard) base 0237e04
Final fix: committed 95dc637 (218/0, OK); re-review dispatched rev8 0237e04..95dc637
Final fix: re-review rev8 — M1, M2, M3 ADDRESSED; no new Critical/Important
Final: parked — notification banner now carries the running command's first line — Ruling: keep; the card already shows the same text and banners stay on this Mac — costs a command (possibly with an inline secret) shown in a macOS banner if wrong.
Final: minor (deferred): stale comment diffpaths.py:20; one notify test method holds two cases
