# SDD ledger — plan: docs/superpowers/plans/2026-11-24-night-watch.md
Spec: docs/superpowers/specs/2026-11-23-night-watch-design.md. Queue batch 2026-11-24-1, lead-run, mr+push. Branch night-watch base 1d6d988.
Preflight: table in .superpowers/sdd/2026-11-24-night-watch/preflight.preflight-nw.md (preflight-nw, 13 findings)
Ruling: F1 dismissed — .tasks.json descriptions carry json:metadata fences (engine compile ok 7) — costs if wrong: routing gate blocks a dispatch, visible at once.
Ruling: F2 accepted, Task 1 — owned_tasks treats a failed or empty tmux listing as unknown (no owned rows), never gone; test with a fake returning "" — spec §2 key is a real dead window — costs if wrong: a false teammate_gone nudge.
Ruling: F3 accepted, Task 3 — Watch keeps its own latch per (project, kind, key) from the record fields, not only from notifier events — spec §3 is per stall — costs if wrong: a second dead teammate unseen for 5 min.
Ruling: F4 accepted — nudge via the COMMENTS queue (tmux-ctl tell refuses the lead window); nudged_at at queue time; a board restart may drop one queued nudge — costs if wrong: one missed nudge, the re-alert still fires.
Ruling: F5 accepted, Task 3 — add a test that lead_idle outside queue mode triggers no watch action.
Ruling: F6 accepted, Task 1 — unit test for the planview queue flag.
Ruling: F7 accepted, Task 1 — owned_tasks runs only when queue mode is on; reuse one tap_entries/plan_limits read in build_overview — costs if wrong: an extra tmux exec per overview.
Ruling: F8 accepted, Task 2 — awake_dropped needs queue mode seen on the previous overview too (one-overview grace) — costs if wrong: an awake drop reported ~1 min late.
Ruling: F9-F11 plan stands (separate awake-fix alert; user mention on the down post); leak check compares before and after.
Ruling: F12 accepted, Task 5 — e2e stamps status files with the seam clock.
Ruling: F13 nits to the implementer of each task; an owner with no ✦ window that never had one is not reported gone only if the plan already says so, else deferred minor.
Task 1: dispatch nw-impl1 (standard, sonnet), base 00d5a33
Task 1: implemented 3d328f3 (green: verifyCommand 135 tests OK rc=0); review dispatch nw-rev1 (standard)
Task 1: fix round 1/5 dispatched to nw-impl1 (1 open — third copy of the tap read; feed_tick re-reads); review base 3d328f3
Task 1: minor (deferred): tmux-error-returns-window-False mutation not run separately (empty-listing test covers it)
Task 1: fix 549e3a1 green (135 + 255 + 11 tests rc=0); scoped re-review nw-rerev1 (standard)
Task 1: fix round 1/5 (1 addressed, 0 open; commits 3d328f3..549e3a1)
Task 1: minor (deferred): no test asserts build_overview receives the shared limits (code at server.py:675 does)
Task 1: complete (commits 00d5a33..549e3a1, review clean)
Task 2: dispatch nw-impl2 (mechanical, haiku), base 549e3a1
Task 2: redispatch nw-impl2 after handoff (mechanical, haiku), base 549e3a1
Task 2: implemented 2f4ad85 (green: verifyCommand 34+100 tests OK rc=0); review dispatch nw-rev2 (standard)
Task 2: minor (deferred): _watch_conditions third param is a bool named queue_before
Task 2: minor (deferred): no test for a project leaving and re-entering queue mode
Task 2: complete (commits 549e3a1..2f4ad85, review clean)
Task 3: dispatch nw-impl3 (standard, sonnet), base 2f4ad85
Task 3: implemented 8ab8ae3 (green: verifyCommand 15 tests OK rc=0); review dispatch nw-rev3 (standard)
Task 3: minor (deferred): watch.py docstring and unused events param still describe event-driven stalls
Task 3: minor (deferred): a project missing from one overview drops its stalls
Task 3: minor (deferred): stray double blank line in test_watch.py
Task 3: fix round 1/5 dispatched to nw-impl3 (1 open — restart re-opens awake_dropped: _queue not seeded); review base 8ab8ae3
Task 3: fix ef9ee48 green (16 tests OK rc=0); scoped re-review nw-rerev3 (standard)
Task 3: fix round 1/5 (1 addressed, 0 open; commits 8ab8ae3..ef9ee48)
Task 3: complete (commits 2f4ad85..ef9ee48, review clean)
Task 4: dispatch nw-impl4 (standard, sonnet), base ef9ee48
Task 6: dispatch nw-impl6 (standard, sonnet) in parallel with Task 4 (disjoint files, no blockedBy), base ef9ee48
Task 4: implemented 5d869bb (green: verifyCommand 20+11+42 tests OK rc=0); review dispatch nw-rev4 (standard)
Task 6: implemented 5bfa862 (green: npm test 206/206 rc=0); review dispatch nw-rev6 (standard)
Task 4: minor (deferred): failing-watch test prints to stderr; no test asserts the log line
Task 4: minor (deferred): real-wiring test skips the alert sink; cleanup registered after add_line
Task 4: minor (deferred): observe_overview runs inside _overview_lock, an awake fix (30 s run_script) can hold /api/overview up to 30 s (brief's placement)
Task 4: complete (commits 5bfa862..5d869bb, review clean)
Task 5: dispatch nw-impl5 (standard, sonnet), base 5d869bb
Task 7: dispatch nw-impl7 (mechanical, haiku) in parallel (disjoint files), base 5d869bb
Task 6: minor (deferred): watch interval timer in main() not stored or cleared
Task 6: minor (deferred): bridge TC_STATE must equal the board's or the heartbeat is missing (no alert, no false post)
Task 6: fix round 1/5 dispatched to nw-impl6 (1 open — watchTick no re-entrancy guard, duplicate down posts under Discord retry); review base 5bfa862
Task 6: fix 4adfcdb green (npm test 207/207 rc=0); scoped re-review nw-rerev6 (standard)
Task 5: implemented e9ebbc0 (green: e2e ALL PASS rc=0); review dispatch nw-rev5 (standard)
Task 6: fix round 1/5 (1 addressed, 0 open; commits 5bfa862..4adfcdb)
Task 6: complete (commits ef9ee48..4adfcdb, review clean; 4adfcdb fix on top of Task 4's 5d869bb)
Task 7: implemented 5dbb150 (green: both suites ALL PASS, greps rc=0); review dispatch nw-rev7 (standard)
Task 5: minor (deferred): leak check reads 0 real watch files on this machine (vacuous until the live board runs the code)
Task 5: minor (deferred): seed check pins the whole owned JSON string incl. ready_s null
Task 5: minor (deferred): mutation evidence covers only the nudge, not re-alert or feed
Task 5: complete (commits 5dbb150..e9ebbc0, review clean)
Task 7: minor (deferred): orchestrator.md:269 says "ends `ok`", the real line ends `: ok.` / `failed: <msg>.`
Task 7: minor (deferred): ARCHITECTURE.md:251 omits that lead_idle is also posted as a watch alert and the separate awake-fix alert
Task 7: minor (deferred): ARCHITECTURE.md Notifier bullet still says six kinds, no pointer to the four more
Task 7: minor (deferred): [Watch] test pins only the bullet's first line
Task 7: complete (commits 4adfcdb..5dbb150, review clean)
Final: review dispatch nw-final (session level), range 1d6d988..HEAD
Final: review with fixes (2 Important: real awake run untested; no whole-suite verdict). Fix wave nw-fix (standard) for Important 1 + ARCHITECTURE six-kinds line; Important 2 = lead runs all.zsh + npm test
Final: all.zsh rc=1, FAIL 1/225 engine (engine_resume kill matrix timeout, load 10.8; branch has no engine/ diff); rerun alone 26 pass 0 fail rc=0
Final: fix wave 788a44d..347a17f green (21 tests OK rc=0); scoped re-review nw-refinal (standard)
Final: re-review clean (2 addressed, 0 open; commits e9ebbc0..347a17f)
