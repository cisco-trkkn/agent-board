# SDD ledger — plan: docs/superpowers/plans/2026-11-05-queue-keep-awake.md
Preflight scan:
| pair/task | produces → consumes | found |
| T1→T2 | awake case, awake.json, stubs/harness in test_ctl_awake.zsh → lid mode extends both | ok; sequential, same files |
| T1,T2→T4 | working awake → real run | ok |
| T3 | rules text only; independent files | ok; parallel with T1/T2 |
| T1 self | fixtures captured vs AC fixture derivation stated | ok |
| T2 self | sudo -l rc-0 probe vs rule check by stdout | ok (ruling) |
| T3 self | verify counts vs 4 edits | ok |
| T4 self | real run on Privilege Manager Mac: lid falls back | ok |
Ruling: plan rulings stand (sudoers check reads stdout; sleeps excludes Wake Requests, reasons per probe) — costs a missed lid hold / odd reason text if wrong.
Task 1: dispatched awake9 (standard/sonnet) base eaf781b
Task 3: dispatched rules9 (mechanical/haiku) base eaf781b (parallel, disjoint files)
Task 3: re-dispatched rules9 at standard/sonnet (routing gate blocked haiku while T1 standard in progress)
Task 3: green (grep 3/1 rc 0; only 2 files); commit 45973e8; review not yet dispatched (handoff)
Task 1: green (ALL PASS 52 ok, rc 0, 0 FAIL; RED 39 FAIL; 5 mutations); commit 90d45f0; review not yet dispatched (handoff)
Handoff: lead relayed 2026-11-09 ~19:25Z; teammates awake9, rules9, rcguide shut down; next lead dispatches T1 and T3 reviews, then T2 to a fresh implementer
Resume: lead 2026-11-09 19:25Z; caffeinate 2241; T1+T3 one review package eaf781b..90d45f0, verdicts per task (standard)
Task 1: minor (deferred): --pid not validated; a dead pid prints on while caffeinate exits at once
Task 1: minor (deferred): pipefail/grep -q SIGPIPE in _aw_on_battery
Task 1: minor (deferred): no setsid/nohup on the hold; T4 real run must show it survives a Bash-tool call
Task 1: minor (deferred): mutations named only in the report, not the test file
Task 3: minor (deferred): step 5 Sleep section placed after the commit/artifact sentence
Task 3: minor (deferred): "first" vs "before anything else" in Starting from a handoff; splits Team paragraphs
Task 3: minor (deferred): SKILL.md no instruction when awake status is off/unsupported
Task 1: complete (commits eaf781b..90d45f0, review clean)
Task 3: complete (commits eaf781b..45973e8, review clean)
Task 2: dispatched awake9 (standard/sonnet) base 90d45f0
Task 2: green (ALL PASS 102 ok rc 0, 0 FAIL; RED 36; 6 mutations; leak 0); commit d42a4eb
Task 2: review dispatched review9b (standard) 90d45f0..d42a4eb
Task 2: review spec ok, quality needs fixes (1 Important: _aw_release swallows failed sudo disablesleep 0)
Task 2: minor (deferred): watchdog loop busy-spins if zsh/zselect fails to load (awake.zsh:127-129)
Task 2: minor (deferred): watchdog identity check not scoped to state dir (awake.zsh:22)
Task 2: minor (deferred): leak-check pgrep machine-wide; a live real watchdog fails the suite (test:280)
Task 2: minor (deferred): sudo-l-privmgr.txt holds the real login name
Task 2: minor (deferred): check-then-act window in watchdog file edit
Task 2: fix 476e08d green (117 ok rc 0, 0 FAIL; RED 8); re-review dispatched rereview9 (standard)
Task 2: fix round 1/5 (1 addressed, 0 open; commits d42a4eb..476e08d)
Task 2: minor (deferred): on over a lid record left by failed off drops lid fields; old watchdog keeps running
Task 2: minor (deferred): watchdog repeats failure log line every tick while sudo fails
Task 2: complete (commits 90d45f0..476e08d, review clean)
Task 4: dispatched awake9 (standard/sonnet) base 476e08d
Task 4: green (verify 1, rc 0); commit e42685f
Task 4: minor (deferred): e2e-awake.md:84 gate item number says 1, should be 2
Task 4: minor (deferred): e2e-awake.md:5 "Never run" wording
Task 4: minor (deferred): survival proof thin (assertion 4 s old) e2e-awake.md:26-31
Task 4: minor (deferred): lid-mode awake.json in prose, not pasted cat
Task 4: complete (commits 476e08d..e42685f, review clean)
Final review: dispatched final9 (session level) 56c1ea5..e42685f
Final review: fixes first (I1 ancestor lookup misses versions/<ver> comm; I2 leak check machine-wide = T2-c promoted); 17 deferred minors stay; new M1-M5
Final fix wave: dispatched awake9 (I1, I2, M1, M2, gate disablesleep 0) base e42685f
Final fix wave: 7fc9718 green (119 ok rc 0, 0 FAIL, decoy alive); re-review dispatched
Final fix wave: re-review all ADDRESSED, 0 new breakage
Final: minor (deferred): e2e-awake.md:87 gate says within 60 s; tick is 60 s, allow ~70 s
Final review: clean after one fix wave (commits e42685f..7fc9718)
