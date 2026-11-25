# SDD ledger — plan: docs/superpowers/plans/2026-11-24-pcee-engine-part-3.md
Spec: docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-3 (sections 12-14). Branch pcee-engine-part-3, plan rebased onto main 01bfb7a -> 854be6a.

## Pre-flight scan
| pair / task | produces -> consumes | found |
| T1-T3 | hold.decide, holds table, bin/hold.js -> core park/approve test runs bin/hold.js | consistent (pass bound to spec, used_at by hook) |
| T2-T3 | ENGINE_* env, backend.resume(h,text,job), fake resume_fails -> core resume dispatch | consistent (A6) |
| T2-T1 | engine-hold.sh execs bin/hold.js | consistent |
| T3-T7 | core.handler source approval -> T7 adds source schedule beside it | consistent, same file sequential |
| T5-T6 | schedule.js add/list/rm, inbox.moveDueTimers filter -> moveDue, drain {source} | consistent |
| T6-T7 | handleRow/runIntents/finishRuns, takeLock, CHECKS.schedule_run -> core tick, run-now uses wake.run | consistent |
| T6-T8 | steps.js CHECKS (schedule_run) -> CHECKS.plist_remove; cli wake -> wake install/status/uninstall | consistent |
| T3/T7/T8 core.js | NEVER_PARK gains schedule_run (T7), plist_remove (T8) | consistent, sequential |
| T5/T6/T7/T8 cli.js | SUBS schedule, wake, run-now, migrate | consistent, sequential |
| T9 | cites file:line of T1,T5-T8 | must run after T8 |
| T1 self | 36 cases incl git_clean -n held (false positive by design, A4) | agrees |
| T2 self | bin/tmux-ctl line 594 "at base" 1d6d988; base moved to 01bfb7a | implementer locates by text, not line |
| T3 self | frontier tier; tests + code in one file pair | agrees |
| T4 self | complete code given, DST expectations author-run | agrees |
| T6 self | verify includes engine_steps.test.js, not in files list | ruling below |
| T10/T11 | full suites; real Haiku worker on scratch server + local bare remote | no shared state touched |
Ruling: T6 may add a schedule_run check case to engine/test/engine_steps.test.js (manifest lists it as modify; files list omits it) — manifest is the plan's own write list — costs nothing if wrong (one extra test file edited).
Ruling: T2 locates the tmux-ctl agent) launch line by its text (AGENT_BOARD_REPO=${(q)AB_REPO} $cmd), not by line 594 — base moved since planning — costs a wrong-location edit caught by test_agent_dir.zsh.
Stale check: stale (bin/tmux-ctl, docs/ARCHITECTURE.md, docs/INSTALL.md, tools/tests/test_plugin.zsh); refresh dispatched refresh-pcee-engine-part-3 (refresh, opus)
Task 1: dispatched impl1 (standard, sonnet), BASE 904efda
Task 1: review dispatched rev1 (standard, sonnet) on review-904efda..9a98a9a.diff
Task 1: review ❌ I1 (bad config regex disables every hold, incl. defaults); cannot-verify db.tx lock resolved (BEGIN IMMEDIATE, busy_timeout 5000)
Ruling: I1 fix keeps rulesFor throwing "bad hold rule <i>" (plan AC) and makes decide catch it and use DEFAULT_HOLDS alone (fail closed on the defaults) — a broken engine.json must never unguard a worker — costs: a bad config rule is ignored silently except for stderr
Task 1: minor (deferred): M1 leak check only p.sqlite*, not full listing+mtimes
Task 1: minor (deferred): M2 unset ENGINE_DIR becomes "undefined" in TC_ENGINE_DIR
Task 1: minor (deferred): M3 part-2 db fixture is current SCHEMA minus holds, not base schema
Task 1: minor (deferred): M4 36-case count treats "echo x | gh pr merge --squash" as one case
Task 1: minor (deferred): M5 sqlite-not-loaded only tested on ENGINE_JOB-unset path
Task 1: re-review dispatched rev1 (standard, sonnet) on review-9a98a9a..2a0751c.diff
Task 1: fix round 1/5 (1 addressed, 0 open; commits 9a98a9a..2a0751c)
Ruling: unset ENGINE_DIR with ENGINE_JOB set returns none (fail open), kept from fix round 1 — only tmux-ctl agent (Task 2) sets ENGINE_JOB and it sets all four together — costs: a hand-started worker with ENGINE_JOB only runs unheld; final review to weigh
Task 1: complete (commits 904efda..2a0751c, review clean)
Task 2: dispatched impl2 (standard, sonnet), BASE 2a0751c
Task 2: review dispatched rev2 (standard, sonnet) on review-2a0751c..e52df5f.diff
Task 2: review ✅ approved; ⚠️ golden line resolved (existing test_agent_dir golden check ran ALL PASS at e52df5f)
Task 2: minor (deferred): test-engine-hold.sh:104-106 unused nonode/NODE_DIR; missing-node case SKIPs when node is in /usr/bin
Task 2: minor (deferred): new test_agent_dir/test_plugin checks never ran RED
Task 2: minor (deferred): fake.js resume returns a handle with the old job id even when a new job is passed (Task 3 must not rely on handle.job)
Task 2: minor (deferred): nested tmux-ctl agent from a worker inherits ENGINE_* vars
Task 2: complete (commits 2a0751c..e52df5f, review clean)
Task 3: dispatched impl3 (frontier, fable), BASE 178a716
Ruling: Task 3 deny returns the spec to prev_state inside the signal event (writeSignal), not in the resume command — the brief's way lets a crash between signal and resume start a second spec on the turn — costs: a few lines to move back if the final review disagrees
Task 3: review dispatched rev3 (standard, sonnet) on review-178a716..75dc635.diff
Task 3: minor (deferred): resumed session is told only the exact approval/deny text, so it reports to the old job path until the report nudge names the new one (claude_tmux.js) — check in Task 11 real run
Task 3: minor (deferred): a hold_skipped job stays unmarked, so its blocked report takes the normal retry/architect path
Task 3: minor (deferred): crash cases simulated in-process, not a killed process
Task 3: review ✅ approved (deny deviation endorsed)
Task 3: minor (deferred): architectBrief review query includes 'escalated', so a held review job could be read as the latest review
Task 3: minor (deferred): A7 hold_skipped worker still told to report blocked; mention in docs (Task 9)
Task 3: minor (deferred): feed decision text cut at 300 chars; hookAt test seam rebuilds output itself
Task 3: complete (commits 178a716..75dc635, review clean)
Task 4: dispatched impl4 (mechanical, haiku), BASE d90f933
Task 4: review dispatched rev4 (standard, sonnet) on review-d90f933..48c1ee3.diff
Task 4: review ✅ approved
Task 4: minor (deferred): parseRule trims input; Task 5's A9 same-rule check should compare trimmed text
Task 4: complete (commits d90f933..48c1ee3, review clean)
Task 5: dispatched impl5 (standard, sonnet), BASE b4ad414
Task 5: review dispatched rev5 (standard, sonnet) on review-b4ad414..7173a68.diff
Task 5: review ✅ approved
Task 5: minor (deferred): re-add with same rule+command but other skip/cwd/env prints unchanged and keeps old values (A9), no hint
Task 5: minor (deferred): dead code / odd ok2 helper in engine_schedule.test.js; no CLI tests for extra-argument usage errors
Task 5: minor (deferred): schedule_added/removed carry no {cause, idx} (direct tx, correct) — Tasks 6/7 must not copy this into core.apply
Task 5: complete (commits b4ad414..7173a68, review clean)
Task 6: dispatched impl6 (standard, sonnet), BASE 87b7f37
Ruling: Task 6 lists wake in SUBS and updates the pinned usage in engine_cli.test.js (impl6 may edit it) — a hidden subcommand is worse than a one-line test edit — costs nothing if wrong
Task 6: review dispatched rev6 (standard, sonnet) on review-87b7f37..83cf3d1.diff
Task 6: review spec ✅ quality needs fixes: I1 leak check misses the real engine dir listing+mtimes; I2 run-line env path untested, trailing # comment swallows the closing paren
Ruling: Task 6 run line puts a newline before the closing paren ("( <env> <command>\n) 2>&1 | tee …") — a trailing # comment in a command must not eat the ")"; same semantics otherwise — costs: the Global Constraints' one-line shape differs by one newline
Task 6: minor (deferred): TMUX set to "" not removed (as steps.js); failed new-window invisible in wake output, untested; tmux runs inside the drain tx; timeout_min never stored by schedule add
Task 6: re-review dispatched rev6 (standard, sonnet) on review-83cf3d1..0d6fd3d.diff
Task 6: fix round 1/5 (2 addressed, 0 open; commits 83cf3d1..0d6fd3d)
Task 6: minor (deferred): leak check can flake if another project's engine adds/removes a non-agent-board.* file in the real engine dir
Task 6: complete (commits 87b7f37..0d6fd3d, review clean)
Task 7: dispatched impl7 (standard, sonnet), BASE f3590c7
Ruling: Task 7 may edit wake.js (one-line optional project filter for run-now) — the plan's run-now "runs wake.run for that project only" needs it — costs nothing if wrong
Task 7: review dispatched rev7 (standard, sonnet) on review-f3590c7..d8eb557.diff
Task 7: review ✅ approved
Task 7: minor (deferred): engine_schedule_core test 3 relies on wall-clock sleep 3 outlasting the fake spec run (may flake at load ~11)
Task 7: minor (deferred): "window open is done by the check" test asserts only the ghost row
Task 7: minor (deferred): mutation 1 substituted (open step moved before the drain); same observable failure
Task 7: minor (deferred): two run-now within one second share source_id, second silently ignored
Task 7: minor (deferred): run-now without an engine also runs the project's other due schedules (wake.run moveDue)
Task 7: complete (commits f3590c7..d8eb557, review clean)
--- session resumed from handoff 2026-11-25-part3-task7
Task 8: dispatched impl8 (standard, sonnet), BASE 2b5358d
Task 8: review dispatched rev8 (standard, sonnet) on review-2b5358d..8667c7b.diff
Task 8: review spec ❌ quality needs fixes: I1 core.resume never reruns an open plist_remove (only the test calls rerunPlistRemove); I2 steps.run reuses a done plist_remove, so a reinstalled plist stays installed with "already migrated"
Task 8: minor (deferred): removeAct ignores a failed bootout and unlinks, step recorded done while the job may still be loaded
Task 8: minor (deferred): wake status opens every project DB via dbm.open (may not be read-only)
Task 8: minor (deferred): wake install with failed bootstrap leaves the new plist, backup untested; dry-run says "would migrated", ignores --project; kill test relies on kill -9 $PPID
Task 8: re-review dispatched rev8 (standard, sonnet) on review-8667c7b..052d442.diff
Task 8: fix round 1/5 (2 addressed, 0 open; commits 8667c7b..052d442)
Task 8: minor (deferred): two reinstalls within one second reuse the suffixed plist_remove key; resume's rerunPlistRemove call has no try of its own
Task 8: complete (commits 2b5358d..052d442, review clean)
Task 9: dispatched impl9 (mechanical, haiku), BASE ec228c8
Task 9: implemented b0a552e (Verify 2/1/3 rc 0), held for batch review with Task 10
Task 10: dispatched impl9 (mechanical, haiku), BASE b0a552e
Task 10: impl9 DONE_WITH_CONCERNS: all.zsh rc=1 twice (FAIL 1/234 engine: schedule_core test 3 both runs; resume kill points); engine suite alone 602/602 rc 0; resume alone 1 fail then 26/26
Ruling: Task 10 escalated to standard (fix10, sonnet): make engine_schedule_core test 3 wait on an event instead of sleep 3 (part 3's own flake, Task 7); measure engine_resume kill points on main vs branch, debug if the branch is slower, else raise the until() cap — CI must be green to merge — costs: two test-file edits outside Task 10's empty files list
Task 10: dispatched fix10 (standard, sonnet), BASE b0a552e
Task 10: fix10 e2d7679 schedule_core test 3 waits on a release file (mutation-checked)
Ruling: Task 10 fixes the engine_resume flake in production db.js migrate() (ALTER ADD COLUMN race between two concurrent db.open on a fresh DB kills the engine child: "duplicate column name"; pre-existing since part 2 d307d54) by ignoring only duplicate-column errors — not a timing issue, a longer until() cap cannot help — costs: a production edit inside Task 10, review must cover it
Task 10: fix10 3728c67 db.js migrate race fix; all.zsh ALL PASS 234 rc=4, engine 603/603 rc 0
Batch 9-10: review dispatched rev9 (standard, sonnet) on review-ec228c8..3728c67.diff
Batch 9-10: reviewed together (2 tasks)
Task 10: review ✅ approved (db.js race fix incl. 37ba2ce read-then-write close; new test fails on 3728c67^ db.js)
Task 10: minor (deferred): schedule test 3 shell loop leaks if an assert throws before the release file is written (try/finally)
Task 10: complete (commits b0a552e..37ba2ce, review clean)
Task 9: review spec ❌ quality needs fixes: I1 INSTALL says migrate --dry-run prints the plists that would be removed; code prints only would-migrated lines
Ruling: Task 9 fix also corrects the note's "loop Task 11 extends DEFAULT_HOLDS" claim (not in the loop plan) and its "as of" sha — false text in the same file, one edit — costs nothing if wrong
Task 10: minor (deferred): all.zsh rerun after 37ba2ce: engine_backend 'claude-tmux: weekly and session sentences are usage limits' failed at load 8-10, alone 38/38 twice (load flake, not part 3's change)
Task 9: re-review dispatched rev9 (standard, sonnet) on review-37ba2ce..c19b666.diff
Task 9: fix round 1/5 (small, 3 addressed, 0 open; commits 37ba2ce..c19b666)
Task 9: complete (commits ec228c8..c19b666, review clean)
Task 11: dispatched real11 (standard, sonnet), BASE 6aeffdc
Ruling: Task 11 scratch clone moves under /Users/francisco.ruiz/agent-board/.claude/worktrees/p3real-clone (trusted parent) instead of pressing the folder-trust dialog for /tmp — a trust answer is the user's — costs: a scratch dir inside the live checkout's untracked .claude/ until cleanup
Task 10: all.zsh run 3 after 37ba2ce: FAIL 1/234 board/test_scout_isolation (a live Discord outbox post during its run; alone OK x2); engine 603/603 rc 0
Ruling: Task 10 accepts the 37ba2ce suites as green (run after 3728c67 ALL PASS rc=4; later two runs each one different live-state/load flake, each passing alone; engine 603/603) without a fourth full run — GitHub CI re-runs the suite before merge — costs: a real regression masked as a flake would surface in CI
Ruling: Task 11 uses a git worktree of agent-board (branch p3real-work, trusted like other .claude/worktrees) instead of a clone, and the worker pushes to the bare repo by absolute path, not origin (origin = GitHub in a worktree; no remote/config edits) — parent trust not inherited by a separate clone — costs: the brief's 'git push origin HEAD' text differs; a scratch branch in the live repo until cleanup
Task 11: real11 a4de165 note (Verify 1/2/2 rc 0); hold, approve, single push, wake, dry-run pass; cleanup verified (worktree + branch gone)
Task 11: real run FAIL on Task 3 deferred minor: resumed worker reports to the old job path (implement1_1.md), engine waits on implement1_2.md -> heartbeat_timeout, retry, architect escalation
Ruling: Task 3 deferred minor is load-bearing (every approved hold ends in heartbeat_timeout): fix in Task 11 scope — resume text carries the new job's report path (core.js/claude_tmux.js, TDD), then real11 reruns the hold part once and updates the note — costs: one more real Haiku run
Task 11: dispatched fixres (standard, sonnet), BASE a4de165
Task 11: fixres 86695f3 hold resume text carries the new job's report section (RED 7 fail, GREEN 137/137, engine 603/603 rc 0)
Task 11: review dispatched revres (standard, sonnet) on review-a4de165..86695f3.diff; real11 hold rerun in parallel
Task 11: fix review ✅ approved (revres; RED verified on pre-fix engine, 27/7)
Task 11: minor (deferred): a held architect/reviewer job gets the worker status shape in its hold resume (core.js ~1164 reviewer-kind list duplicated); no test covers reviewer or architect hold resumes
Task 11: real11 1690ff8 hold rerun at 86695f3 PASS (resumed worker wrote implement1_2.md, job done, outcome kept, rebuild --check 0); first rerun attempt failed from a scratch-env setup error (TC_STATE not in scratch tmux global env), not the engine
Task 11: review dispatched rev11 (standard, sonnet) on review-6aeffdc..1690ff8.diff
Task 11: review ✅ approved (rev11)
Task 11: minor (deferred): note says the scratch TC_STATE bug "also explains" the first run's timeouts (unevidenced; "may explain"); note omits that other stale agent-status files may remain in the real dir; LaunchAgents ls/diff in prose not verbatim
Task 11: complete (commits 6aeffdc..1690ff8, review clean)
Final: review dispatched finalrev (frontier, fable) on review-01bfb7a..fc0e59c.diff
Ruling: lead trusted ~/second-brain in ~/.claude.json by hand (atomic one-key write, read back; backup ~/.claude.json.bak-20261125) — user chose option 1 on Discord 15:43Z; trust spec queued after second-brain — costs nothing if wrong (remove the key)
Final: review ready after fixes: C1 plist PATH has no node (wake install prints installed, migrate would orphan five jobs); I1 launchd wake uses default tmux socket; I2 failed bootout recorded done; I3 rm-outside misses $HOME/quoted/split-flag forms; I4 no real launchd gate (G1-G4); I5 finishRuns rescans every tick
Ruling: final fix wave also flips ENGINE_DIR-unset-with-ENGINE_JOB to fail closed (finalrev disagreed with the fail-open resting state) and fixes the two note minors — costs: a hand-started worker with ENGINE_JOB only is denied
Final: fix wave dispatched finalfix (standard, sonnet), BASE fc0e59c
Final: fix wave finalfix fc0e59c..1835b00 (engine 610/610 rc 0; all.zsh ALL PASS 234 rc=4); re-review dispatched finalrev (frontier, fable)
Final: re-review all ADDRESSED, ready to merge (finalrev)
Final: minor (deferred): N1 "cannot migrate <label>: still loaded" leaves the row added (two runners until manual bootout + rerun); N3 schedule rows in a running engine still use the old tmux rule (cli.js:108); N4 a manual engine wake/run-now from a pane satisfies the migrate guard; N5 rm -r with any $ word held even in the worktree (decided trade)
Ruling: N2 (INSTALL node-precondition command lacks --project) fixed as a one-line docs edit checked by running it, without a second review wave — a wrong operator command is worse than an unreviewed one-liner — costs: one docs line unreviewed
Final: N2 fixed d5609ec (ran under env -i, rc 0); Plan complete
