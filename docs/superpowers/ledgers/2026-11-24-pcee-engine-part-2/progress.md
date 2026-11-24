# SDD ledger — plan: docs/superpowers/plans/2026-11-24-pcee-engine-part-2.md
Spec: docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-2 (reachable). Base 08c8601. Native task id = plan id + 8.
Ruling: native tasks carry Goal + Verify + metadata only, not the full task text (Task 15 full) — implementers get the full text from task-brief; saves lead context — costs if wrong: a TaskGet reader sees only the goal.
Ruling: plan assumptions A1-A9 accepted as written; section 14 (schedules) not built (spec moved it to stage 7) — costs if wrong: rework of the named piece.
Ruling: Task 15 (real run, user gate) is not run in this queue; listed open in the PR — the spec itself gates it after merge — costs if wrong: none, it stays open.
Ruling: pre-flight conflict scan delegated to a standard-tier read-only scanner (lead rules on its table) — saves lead context on a 99 KB plan — costs if wrong: a missed conflict reaches task review.
Task 1: dispatched impl1 (standard/sonnet), BASE 83daf99
Pre-flight scan: preflight-scan.md (pair table, per-task rows; 24 findings). All Verify == verifyCommand.
Ruling: pre-flight findings 1-24 ruled as R1-R24 in preflight-rulings.md (accept the scan's fix except R2 compare on id before '#', R3 keep park table, R6 parked record = unchecked step kind, last run line wins, R13 --project = feed key, R14 keep ratio of medians) — each dispatch carries its task's R-lines — costs if wrong: per-ruling rework in the named task.
Task 1: green check passed (verify 111/111 rc=0, npm test 329/329); review dispatched rev1, package review-83daf99..8f46426.diff
Task 2: dispatched impl2 (standard/sonnet) parallel to Task 1 review, files disjoint, BASE 8f46426
Task 6: dispatched impl6 (standard/sonnet) parallel, files disjoint, BASE 8f46426
Task 1: review rev1 spec ❌ (1 Important: R9 uncommitted, commit_report unguarded; 4 Minor) — fix round 1 sent to impl1, FIX_BASE 8f46426
Task 1: minor (deferred): NEVER_PARK comment stale
Task 1: minor (deferred): a not_done row of a kind other than metrics_start (e.g. metrics_record) stays at intent; done-spec resume keeps printing reconciled N until Task 9's rerun
Task 1: minor (deferred): metricsStart passes the string "null" as --worktree when the spec has no worktree
Task 1: minor (deferred): load-flaky engine_resume signal test (122 s timeout under load) not run on base commit
Task 1: fix round 1/5 (1 addressed, 0 open — R9 commit_report guarded; commits 8f46426..eb6534e)
Task 1: minor (deferred): engine_cli resume test try/catch swallows every error (ends at 20 s assert); put last error in the message
Task 1: complete (commits 83daf99..eb6534e, review clean)
Task 3: dispatched impl3 (standard/sonnet), parallel with Tasks 2, 6 (files disjoint)
Task 2: green check passed (verify 28/28 rc=0; npm test 332/335 reds in core kill/resume, not its files — checking on clean tree); review dispatched rev1
Task 2: review rev1 spec ✅ quality Approved (0/0/4); ⚠️ clean-tree npm test pending
Task 2: minor (deferred, final review should triage — real risk): limit regex not line-anchored; a ready pane quoting the sentence fires false model_limit + Opus rerun
Task 2: minor (deferred): fixtures from transcript jsonl, not a real pane capture — check in Task 15 real run
Task 2: minor (deferred): capture on every poll for ready non-limit handles; fixed wall-clock waits in tests
Task 2: minor (deferred): tests written with code, guards shown by mutation not RED-first
Task 2: ⚠️ resolved — clean committed tree at 7d8874c npm test 335/335 rc=0 (load 6.9); the 3 reds were the shared tree's uncommitted edits or load
Task 2: complete (commits eb6534e..7d8874c, review clean)
Task 3: green check passed (verify 60/60 rc=0); npm test 335/342 — 7 reds in Task 4's files (kindless waits, park without recommend, policy v2 hash), which the brief (step l.24) assigns to Task 4
Ruling: branch stays red on those 7 tests between Task 3 and Task 4; Task 4's acceptance adds "npm test fully green incl. engine_cli 56/57, engine_core 92/107-109, engine_resume 198" — the plan scripts this split — costs if wrong: a red window of one task.
Task 3: review dispatched rev1
Task 3: review rev1 spec ✅ quality Approved (0/0/4); the 7 reds all follow from Task 3's criteria (3 groups)
Task 3: minor (deferred): migrate runs on every db.open; two processes opening a part 1 db at once can race on ALTER (duplicate column)
Task 3: minor (deferred): policy hash covers JSON.stringify(ASK_DEFAULTS) — a key reorder re-parks every running spec
Task 3: minor (deferred → R11 in Task 4): core.park hard-codes approve default; throws if options lack approve
Task 3: minor (deferred): waitProblem accepts object recommendation that putRaw rejects at binding; report mis-describes
Task 3: complete (commits 7d8874c..d307d54, review clean)
Task 4: dispatched impl4 (standard/sonnet), carries R3 R11 R24 + the 7 reds
Task 6: green check passed (verify 403 OK); ask-line contract consistent with Task 4 (engine kind=wait kind → stored ask_kind); review dispatched rev1
Task 6: review rev1 spec ✅ quality Approved (0/0/4, 3 ⚠️)
Task 6: ⚠️ resolved — live runs.jsonl diff holds only the lead's part-2 metrics start line; impl6's error lines gone
Ruling: Task 6's test_metrics_report.py assertion edit stands (report ends with asks:, plan defect in "suites unchanged") — costs if wrong: the asks lines move above STATUS LINE
Ruling: K2 real-state check becomes a post-merge gate: on main run python3 -I board/metrics.py gate K2 --log docs/superpowers/metrics/runs.jsonl → "gate K2: too early" rc 3; listed in the PR — metrics.py reads the main checkout — costs if wrong: a K2 gate misread found after merge
Task 6: minor (deferred): ask line with no batch key never reported; --budget/--engine-jobs values not shape-checked; control_share target adds no permutation p; engine CLI path not exercised
Task 6: complete (commits d307d54..4358be8, review clean)
Task 11: dispatched impl11 (standard/sonnet) parallel with Task 4 (board files, disjoint)
Task 11: green check passed (verify 115 OK rc=0); review dispatched rev1
Task 11: review rev1 spec ✅ quality Needs fixes (0/2/5) — fix round 1 sent to impl11, FIX_BASE b11e367
Ruling: Task 11 engine-run mark is per spec, latest engine line wins: handed_to_lead / lead_turn clear it, any other engine line sets it — a lead-run spec keeps its derived Discord posts — costs if wrong: duplicate or missing posts for a split spec
Task 11: minor (deferred): server.py wiring has no unit test (one smoke test cheap)
Task 11: minor (deferred): real-state "lines with src" check vacuous until an engine runs — Task 15 gate (command in rev1-task-11-review.md)
Task 11: minor (deferred): feed fixture uses #part-2 where real lines have no #; two read_events per tick; base match can silence a lead-run #part-1 while #part-2 is engine-run
Task 11: fix round 1/5 (2 addressed, 0 open — _flat reuse, latest-engine-line mark; commits b11e367..2cbace2)
Task 11: minor (deferred): derive marks a suppressed event's key seen, so a handed-over spec's spec_started/plan_written don't repost after the handoff
Task 11: complete (commits 4358be8..2cbace2, review clean)
Task 4: green check passed (verify 177/177 rc=0; npm test 364/364); review dispatched rev4 (fresh)
Task 4: review rev4 spec ✅ quality Approved (0/0/4); site:"tests_red" via policy.SITE_RECS and db.event detailKind accepted
Task 4: minor (deferred): unknown site falls back silently to deny; metrics append ask never run once for real; no test that deny is dropped on approve|fail; replay test lacks a core: signal
Task 4: minor (deferred): engine_resume kill matrix slow (98 s alone) and load-flaky; ask_recorded adds work — re-check in Task 14
Task 4: complete (commits 2cbace2..6265c65, review clean)
Task 5: dispatched impl5 (standard/sonnet), carries R8 R19 R22 R11-test
Task 5: full suite hung 6h25m in engine_core.test.js (PID 25017 killed 14:57Z); impl5 sent to debug with per-test timeouts
Task 5: DONE_WITH_CONCERNS c4ca9fd; bounce check green (verify 97/97 rc=0, lead run); hang = test wrappers lacked usage (fixed, test-only)
Task 5: minor (deferred, final fix wave): fake usage 0 for unknown handle; fix_wave not counted; misnamed last-three test; lower-bound predicate dup cli.js:274/integrate.js:586; dead kill-stub branch; helper assert that every backend wrapper has usage (hang guard)
Task 5: gate note for Task 15: real job session_id must resolve its transcript ($CLAUDE_CONFIG_DIR/projects) — one job_done with integer tokens, else every job parks cost unknown
Task 5: complete (c4ca9fd, review clean: spec ✅, quality approved, 6 minors deferred)
Task 7: dispatched impl7 (frontier/fable), base c4ca9fd, carries R7 R12 R17 + usage-wrapper and 15-min run cap
Task 7: DONE_WITH_CONCERNS 840d72a; bounce check green (verify 105/105 rc=0, lead run; full 405/405 per impl7)
Ruling: R5's lock-held exit 4 lives in engine cmdStart (Task 7 owns it), the window-exists half in Task 10's wrapper — R5 says engine start exits 4 — costs a one-line move if Task 10 wanted it
Ruling: gate-failure metrics record passing the full "failed — gate …" outcome is fine — metrics.py build_record_static keeps only the first word (l.535) — none
Task 7: review spec ✅ quality approved, Important 2 (lead cursor replays history; unfinished hole after last done) Minor 5
Ruling: I2 (unfinished predicate) fixed in Task 7, not Task 8 — impl7 owns queue.js and Tasks 8/9/12 build on it — costs a small Task 8 rework if its plan text assumed otherwise
Task 7: fix round 1/5 → impl7 (I1, I2, R5 exit 4, minors 1 and 5); minors 2,3 deferred; minor 4 = Task 15 gate (real metrics gate + record for a gate-failed spec)
Task 7: fix round 1 2ece83b; bounce green (verify 107/107 lead run); full red only engine_resume kill matrix under load, alone 26/26
Ruling: I1 floor persisted in <engineDir>/<project>.lead.start, not MAX(seq) per start — per-start floor loses a lead_turn killed before publish — costs one extra state file
Ruling: Task 12 also waits on Task 8 (queue_finished) — unfinished stays true until Task 8 writes it — none
Task 7: re-review approved (2ece83b); minors deferred: floorOf not tmp+rename, floor survives deleted lead file, publish-failure stderr not rate-limited; Task 8 writes queue_finished before 10/12 rely on --unfinished
Task 7: complete (840d72a..2ece83b, review clean after fix round 1)
Ruling: Tasks 8 (impl7) and 10 (impl5) run in parallel — disjoint files (engine/* vs bin/tmux-ctl + zsh test), both depend only on Task 7, a night already lost — costs a re-run if one's in-progress edits redden the other's suite
Ruling: Task 12 also blocked by Task 8 (queue_finished) — rev4 + impl7 — none
Task 8: dispatched impl7 (frontier/fable), base 2ece83b, R6 R15 R18 R22 + queue_finished + preflight exit 4
Task 10: dispatched impl5 (standard/sonnet), base 2ece83b, R5 exit 4
Task 10: DONE 8da00b4; bounce green (lead run: engine_start ALL PASS, ctl_registry ALL PASS, engine_cli 27/27, rc=0); TDD order slip, RED recorded after (18 FAIL against old tmux-ctl)
Task 10: review spec ✅ quality approved, Minor 4; fix round 1/5 → impl5 (liveness+exit rc in log, cwd check without $TMUX, -bg caller session, quoting test)
Task 10: gate note for Task 15: an unstubbed second tmux-ctl engine start against a running engine exits 4
Task 10: fix round 1 c974cf8; bounce green (lead run: both zsh suites ALL PASS rc=0)
Task 10: re-review 1: Important 1 (cwd guard passes for $HOME git repo) Minor 3; fix round 2/5 → impl5 (session-path comparison + flake); minors deferred: fish default-shell (sh -c), rc line order
Task 10: fix round 2 ac7e456; bounce green (lead run, both zsh suites rc=0)
Task 10: re-review 2 approved (ac7e456); minors deferred: guard uses first window toplevel (worktree refused), missing session says "no git pane path"
Task 10: complete (8da00b4..ac7e456, review clean after fix round 2)
Ruling: Task 8 may edit db.js open() (busy_timeout before journal_mode=WAL) — "database is locked" at engine start under a concurrent status/signal; likely cause of kill-matrix reds — none, two-line reorder
Task 8: DONE_WITH_CONCERNS f323a12; bounce green (lead run: verify files + engine_cli 144/144 rc=0, load 5.1); full red only engine_resume kill matrix, alone 26/26
Ruling: start order keeps adopting running jobs before due timers/inbox drain (not section 9's literal order) — a deadline that fell due while down would fail a job before adoption re-arms it — costs a guard in evaluate if the spec order is required
Task 8: review spec ✅ quality approved, Important 1 (report hook unguarded, not a step: failure halts, kill repeats) Minor 4
Task 8: fix round 1/5 → fix8 (fresh, standard/sonnet; impl7 out of context): I1 + minor 1 (parked record per wait) + minor 2 (answered parked-failed counts unfinished); minor 3 → Task 14 run-alone list; minor 4 → Task 13 docs
Task 8: fix round 1 1b1db27 (fix8); bounce green (lead run verify 121/121 rc=0; full 422/422 per fix8)
Task 8: minor (deferred): engine run guard in cli.js (~l.216) has its own SQL that ignores answered parked-failed specs
Ruling: Task 9's report hook passes opts.reportPath(ctx) and is idempotent — the queue_report check needs the expected path before the hook runs — none
Task 8: re-review approved (rev5, 1b1db27); minors deferred: test for second queue's own queue_report key (with Task 9); engine run guard reuse queue.unfinished (final wave)
Task 8: complete (f323a12..1b1db27, review clean after fix round 1)
Ruling: Tasks 9 (impl5) and 12 (fix8) run in parallel — disjoint files (engine queue_report/queue.js vs board/restore.py + test) — costs a re-run if one reddens the other
Ruling: report name is deterministic via one shared picker used by reportPath and write; an existing file is this queue's only with the trailing marker <!-- engine-queue: <project> <first spec_added seq> --> — keeps the queue_report check sound after a kill — costs one hidden line in each report
Task 9: dispatched impl5 (standard/sonnet), base 1b1db27, R1 R22 + hook contract + name ruling
Task 12: dispatched fix8 (standard/sonnet), base 1b1db27, R5 R12 R13 + Task 10 wrapper rules
Task 12: DONE_WITH_CONCERNS ec4e665; bounce green (lead run: 92 OK python3, 12 OK /usr/bin/python3, rc=0); one-line edit in test_restore_tick.py accepted (recorder answers --unfinished rc 1)
Task 12: review spec ✅ quality approved, Minor 5; fix round 1/5 → fix8 (engine-only bg session in snapshot, awake fallback when _restore_awake fails, stray line, comment); minor 3 left
Task 9: DONE_WITH_CONCERNS de9e121; bounce green (lead run verify 43/43 rc=0); full: 3 load flakes outside files, rerun alone 61/61; one-line cli.js edit (startCore spreads queue.reportHooks) accepted
Task 12: fix round 1 e7e6614; bounce green (lead run 96 OK + 16 OK, rc=0); fix8 hit a 12-min hang (sleep override) and killed it
Task 9: review spec ✅ (except kill gap), quality needs fix: Important 1 (file-exists check skips commit, artifact, awake off after a kill) Minor 4
Ruling: drop reportPath from queue.reportHooks (rev5) instead of a commit-aware check — the idempotent hook reruns after any kill, every outside call is a keyed step — costs one extra render on restart; supersedes the earlier reportPath ruling
Task 9: fix round 1/5 → impl5 (I1 + resume tests; minors: queued-only, busy git check, one report_uncommitted, marker anywhere)
Task 12: re-review approved (rev5, e7e6614); minor deferred: engine-only project with finished queue gets a spare empty session (open it only when --unfinished is 0)
Task 12: complete (ec4e665..e7e6614, review clean after fix round 1)
Session resumed 2026-11-24 12:30 local (handoff 2026-11-24-queue-part2-b); impl5 respawned for Task 9 fix round 1 (uncommitted edits)
Ruling: Task 13 (fix8) runs in parallel with Task 9 fix round 1 — disjoint files (rules/docs/zsh test vs engine queue_report); ARCHITECTURE report paragraph reads the fixed code after impl5 commits — costs a one-paragraph docs touch-up if the fix changes behaviour described
Task 13: dispatched fix8 (standard/sonnet), base e7e6614, + Task 9 minor 4 and Task 8 minor 4 notes
Task 13: DONE_WITH_CONCERNS 67b55a5; bounce green (3 rule suites ALL PASS rc=0 per report); concern: report paragraph written before impl5's commit — check at review
Task 13: review dispatched rev5 (fresh, standard/sonnet)
Task 13: review rev5 spec ✅ quality approved (0/0/2); report paragraph matches impl5's uncommitted Task 9 fix — re-check at final review
Task 13: minor (deferred): ARCHITECTURE Engine first line unwrapped (~l.281); report-step order (artifact, awake off, then queue_finished) not traced against core
Task 13: minor (deferred): handoff SKILL boundary "keeps …" line extended beyond brief (fix8)
Task 13: complete (e7e6614..67b55a5, review clean)
Task 9: fix round 1 00cb186 (impl5); bounce green (report: verify 49/49 rc=0, npm test 438/438 rc=0); parking file needs 300 s test-timeout under load
Task 9: re-review dispatched rev5 (scoped 67b55a5..00cb186)
Task 9: fix round 1/5 (5 addressed, 0 open; commits 67b55a5..00cb186)
Task 9: minor (deferred, final fix wave): after a kill between commit and awake off, write re-renders and may leave the tracked report modified (test 12 asserts no clean git status); minor-2 test not mutation-checked; test 12 kill simulated by step rows
Task 9: complete (1b1db27..00cb186, review clean after fix round 1)
Task 14: dispatched suites (mechanical/haiku); run-alone list: engine_resume and engine_queue_parking kill matrices; parking needs --test-timeout 300000
Final review: dispatched final-rev (frontier/fable) on review-08c8601..00cb186.diff, in parallel with Task 14 (read-only)
Task 14: BLOCKED (suites): all.zsh FAIL 2/220 — test_restore_e2e.zsh 2/19 (ctl log: send -m for A; nothing for B) and engine (engine_resume kill matrix 3, alone 26/26 = known flake); npm test alone not run
Ruling: restore_e2e red is treated as a Task 12 regression until shown otherwise (its stub tmux-ctl answers rc 0 to the new engine status --unfinished call) — impl5 debugs it (systematic-debugging) before the final fix wave — costs one debugging round if it is a load flake
Final review: ready after fixes — Critical 0, Important 5, Minor 12 (final-review.md); no ruling wrong
Ruling: I3 — engine skips awake off when the queue holds a lead-run or keep/ask spec; the lead's queue-finished bullet ends with tmux-ctl awake off — a lid-closed Mac would otherwise sleep before ask merge requests post — costs a longer awake hold if the lead never reacts
Ruling: I4 (limit regex) fixed in the final wave, not after merge — it costs tokens in the runs K2 measures — costs one more item in the wave
Ruling: I2 fixed by dropping enqueue rows of a stale batch in onEnqueue (event "stale batch"), no new command — needs no rule change — costs a re-enqueue if a user meant to merge two batches
Ruling: the rest of this queue (items 2–8) runs under TC_ENGINE=0 until the user starts a first real engine queue themselves — the engine-c1 rule switches on when the PR is merged and Task 15 is a supervised gate — costs Task 15 waiting for that queue
Final fix wave: brief final-fix-brief.md (I1–I4, minors 2,4,5,6,7, usage-wrapper assert) → impl5 after the restore e2e fix
Task 14: restore e2e red = test stub answered rc 0 to engine status --unfinished (not red on main); fixed f264b1d (impl5, test only) ALL PASS rc=0, restore_tick 51 OK; reviewed with the final wave
Final fix wave: dispatched impl5 (standard/sonnet), base f264b1d
User (Discord 18:03Z): the next queue item runs in the engine — supersedes the TC_ENGINE=0 ruling for the rest of the queue
Ruling: the engine queue starts only after the user merges the part-2 PR — the live install and the board (which types [Engine] lines) run main — costs the queue idling until the merge
User (Discord 18:04Z): the lead merges the part-2 PR itself (gh pr merge) once review and suites are green
Final fix wave: DONE 3050971 7b433cf 4ed7cc3 (impl5); report: npm test 445/445 rc=0, 3 rule suites ALL PASS; I3 used the fallback (no ask marker on enqueue rows)
Final fix wave: scoped re-review dispatched rev5 (00cb186..4ed7cc3, incl. f264b1d); Task 14 re-run dispatched suites
Final fix wave: re-review rev5 — 10/10 ADDRESSED, f264b1d ok, no new Critical/Important, 2 Minor (see rev5-final-rereview.md; listed in the PR)
Final: parked — ARCHITECTURE.md:366 says awake off always runs — Ruling: docs-only, no second fix wave; listed in the PR as a follow-up
Final: parked — I4 anchor may miss a glyph-prefixed limit line — Ruling: unverified against a real pane; added to Task 15 gate list in the PR
Task 14: run 2 — all.zsh FAIL 1/220 engine (engine_resume kill matrix 3); npm test alone 445/445 rc=0; engine_resume alone 24/26 (concurrent with rev5 test runs, load ~7), lead re-run alone at load 2.5: 26/26 rc=0
Ruling: Task 14 passes — the only red is the engine_resume kill matrix, green alone at low load in 2 of 3 runs and red only under concurrent load (timeouts waiting 120 s for an event) — costs a real resume bug hidden as a flake; listed in the PR
Task 14: complete (no commits)
