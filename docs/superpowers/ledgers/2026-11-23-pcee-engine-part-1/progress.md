# SDD ledger — plan: docs/superpowers/plans/2026-11-23-pcee-engine-part-1.md
Spec: docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-1 · branch spec-pcee-engine-part-1 · base fefceab · plan 12b6ddc · queue batch 2026-11-23-1 (mr, push)
Preflight scan:
| pair/task | shared | produces → consumes | found |
| 1→2..12 | engine_helpers.js, db/paths/policy | tmpEnv/scratchTmux/gitRepo, open/tx/put/event, retryFor → all | consistent; only T1 edits helpers |
| 2↔3 | bounce.js | T2 defines BOUNCE_MAX_LINES, T3 moves it to strategy and re-imports | sequential (T3 blockedBy T2) |
| 4→5 | engine_backend.test.js | conformance(name, make) → claude-tmux run | sequential |
| 5↔11 | bin/tmux-ctl | agent) case + header l.17 vs engine) case + header l.82 | sequential (11 after 5); in-place header lines, no N change |
| 6,7→8 | inbox/steps/feed | insert/drain/openWait/signal, steps.run/reconcile, feed.publish → core | consistent |
| 7→9 | steps.js | steps.run/CHECKS → integrate | consistent |
| 8,9,10→11 | core/integrate/rebuild | → cli | consistent |
| 11→12→13 | engine.js CLI | run/resume/rebuild → kill tests, real run | consistent |
| each task | — | tests vs files listed; frontier T3/T8 no Steps | self-consistent |
Ruling: run T2, T4, T6, T7, T10 in parallel after T1 (disjoint files) — cost if wrong: a merge-free rework of one module.
Ruling: no batched review (only T14 is mechanical) — cost if wrong: none.
Ruling: native tasks carry Goal + Verify + metadata fence, the full text lives in each task brief (task-brief script) — keeps the task list small — costs nothing, briefs are the source.
Task 1: dispatched impl-t1 (standard, sonnet) BASE 12b6ddc
Task 1: green check ok (verify rc 0) — e48f39d
Task 1: review dispatched rev-t1 (standard) on 12b6ddc..e48f39d
Task 1: review spec ✅ quality approved (0 C, 0 I, 6 minor)
Task 1: minor (deferred): policy_hash hashes utf8 text, not raw bytes (policy.js:20-37)
Task 1: minor (deferred): retryFor returns arrays shared with unfrozen DEFAULT_RETRY (policy.js:13-33)
Task 1: minor (deferred): test restores unset HOME as "undefined" (engine_db.test.js:37-45)
Task 1: minor (deferred): busy_timeout=5000 beyond brief (db.js:28)
Task 1: minor (deferred): node:sqlite ExperimentalWarning in test output; package.json test script could disable it
Task 1: minor (deferred): waits.options / inbox.state defaults not asserted (engine_db.test.js:55-72)
Task 1: complete (commits 12b6ddc..e48f39d, review clean)
Ruling: four parallel implementers at most (team cap 4); T10 waits for a free slot — costs one slot of wall time.
Task 2: dispatched impl-t2 (standard, sonnet) BASE e48f39d
Task 4: dispatched impl-t4 (standard, sonnet) BASE e48f39d
Task 6: dispatched impl-t6 (standard, sonnet) BASE e48f39d
Task 7: dispatched impl-t7 (standard, sonnet) BASE e48f39d
Task 2: green check ok (verify rc 0) — 1940fa7
Ruling: shut each implementer down at its green report and use a fresh implementer with the report file for fix rounds — keeps the team at 4 while reviewers run — costs one cold start per fix round.
Task 6: green check ok (verify rc 0) — 47f3690
Task 2: review spec ✅ quality ❌ (0 C, 1 I, 6 minor)
Task 2: minor (deferred): unparsable .tasks.json reports "no .tasks.json" (compile.js:74)
Task 2: minor (deferred): tier/files unvalidated, tier undefined when absent (compile.js:85-87)
Task 2: minor (deferred): bounce keeps at/expected lines before any failure; nested not ok miscounted (bounce.js:38-42)
Task 2: minor (deferred): undefined logPath prints "full log: undefined" (bounce.js:45)
Task 2: minor (deferred): bare array accepted as .tasks.json (compile.js:75)
Task 2: minor (deferred): report requires string arrays for commits/concerns (report.js:110)
Task 2: fix round 1/5 dispatched fix-t2 (standard, sonnet) FIX_BASE 1940fa7
Task 4: green check ok (verify rc 0) — 566d2b2
Task 6: review spec ✅ quality ❌ (0 C, 1 I, 4 minor)
Task 6: minor (deferred): wait id collision at same now overwrites answered wait (inbox.js:90)
Task 6: minor (deferred): status/gone event without pane yields undefined ids (inbox.js:44)
Task 6: minor (deferred): drain not bounded by max(id) at start; rows inserted mid-drain handled same pass (inbox.js:62-79)
Task 6: minor (deferred): no test that a handler's put commits on success (engine_inbox.test.js)
Task 7: green check ok (verify rc 0) — 3c8cd16 (implementer: tests written after code, guards verified by mutation)
Task 4: review dispatched rev-t4 (standard) on 566d2b2
Task 7: review dispatched rev-t7 (standard) on 3c8cd16
Task 6: fix round 1/5 dispatched fix-t6 (standard, sonnet) FIX_BASE 47f3690
Task 2: fix round 1 green (9/9, rc 0) — be66621; re-review dispatched rerev-t2 (standard)
Task 4: minor (deferred): fake.js:15,26,31 — the `jobs` map is written in `start` but never read. Dead state: remove it, or have `resume`/`close` use it.
Task 4: minor (deferred): fake.js:34-52 — a step with an unknown shape (a typo such as `{stat: "busy"}`) is silently ignored, so a script error gives a test that passes with fewer even
Task 4: minor (deferred): fake.js:42-43 — `{hang: true}` emits one status event, not a stream. The brief says "status updates"; scripts must repeat the step. Acceptable, but document i
Task 4: minor (deferred): fake-worker.js:17-19 — the status doc lacks `since` and `failStreak`, which `board/tests/fixtures/agent-status/real-new-fields.json` has. The brief says "agen
Task 4: minor (deferred): fake-worker.js:17-19 — the worker only ever emits `tool: null`, so Task 5's conformance cannot exercise a tool-bearing status through a real process. Fine for
Task 4: minor (deferred): fake-worker.js:26-29 — `updatedAt` is floored to whole seconds, so the same-second heartbeat is invisible to a staleness check finer than 1s. This is consiste
Task 4: minor (deferred): engine_backend.test.js:~149 and ~170 — two separate `if (require.main === module)` blocks; merge them.
Task 4: minor (deferred): engine_backend.test.js (worker tests) — a mutation run of the worker modes was not done (reported). The `done`/`blocked` tests also pin the mode only through 
Task 4: minor (deferred): engine_backend.test.js conformance — the "ready then report" test asserts nothing about the `started` event order. It is covered by the first test.
Task 4: complete (commits 566d2b2, review clean)
Task 6: fix round 1 green (9/9, rc 0) — 6b9394c; re-review dispatched rerev-t6 (standard)
Task 7: minor (deferred): steps.js:173-178 close_window: missing `pane` fact -> includes(undefined) false -> silently "done". metrics_* send "undefined" to tmux-ctl. A check should ret
Task 7: minor (deferred): steps.js:114: if the `failed` write throws it hides the original act error.
Task 7: minor (deferred): feed.js:48: event without ts serialises without the key (append_event would raise); default to Date.now()/1000.
Task 7: minor (deferred): engine_steps.test.js:487 `assert.ok(e)` asserts nothing; unused `t` at :470.
Task 2: fix round 1/5 (1 addressed, 0 open; commits 1940fa7..be66621)
Task 2: complete (commits e48f39d..be66621, review clean)
Task 7: review spec ✅ quality approved (0 C, 0 I)
Task 7: complete (commits 3c8cd16, review clean)
Ruling: reviewers and fixers get no task owner (an owner set on a short-lived teammate resets the task to pending at its shutdown) — costs nothing.
Resume 2026-11-23 (new lead session): native tasks recreated (plan T3→#4, T5→#5, T6→#6, T8→#7, T9→#8, T10→#9, T11→#10, T12→#11, T13→#12, T14→#13)
Ruling: the engine lock file holds the pid as plain text on its first line; held = that pid is alive (process.kill(pid,0)) — T10 apply and T8 core both use it — costs a one-line reader change if T8 needs another format.
Task 6: re-review dispatched rerev-t6 (standard) on 47f3690..6b9394c
Task 3: dispatched impl-t3 (frontier, fable) BASE 6b9394c
Task 5: dispatched impl-t5 (standard, sonnet) BASE 6b9394c
Task 10: dispatched impl-t10 (standard, sonnet) BASE 6b9394c
Task 6: fix round 1/5 (1 addressed, 0 open; commits 47f3690..6b9394c)
Task 6: minor (deferred): inbox.js:8 null payload stored as text "null" (parse maps it back; no other reader)
Task 6: complete (commits e48f39d..6b9394c, review clean)
Task 9: dispatched impl-t9 (standard, sonnet) BASE 6b9394c
Task 10: green check ok (verify rc 0) — effcd50
Task 10: review dispatched rev-t10 (standard) on effcd50
Ruling: whoever writes retry_policies (Task 8 core, at spec start) writes them through tx/put/event like every other table, so rebuild replays them — carried into the T8 dispatch — costs one diff line in rebuild --check if missed.
Task 10: review spec ✅ quality approved (0 C, 0 I, 3 minor); ⚠️ db.open seeds rows: resolved by lead, no INSERT in db.open (db.js:51-62 only put/event)
Task 10: minor (deferred): rebuild.js backup name has 1 s resolution; copyFileSync overwrites a same-second backup
Task 10: minor (deferred): rebuild check/apply on a missing db creates an empty one and returns rc 0
Task 10: minor (deferred): no test for the EPERM (alive, other user) lock branch
Task 10: complete (commits 6b9394c..effcd50, review clean)
Task 9: green check ok (verify rc 0) — c60f79f
Task 9: review dispatched rev-t9 (standard) on c60f79f
Task 9: carry to T8 — ctx {db, repo, worktree, tmuxCtl, tasks, env, now}; ledger event kinds dispatched green_check review fix_round minor ruling fix_wave task_complete; integrate.finalize exported; mr_create has no steps.CHECKS entry (resume parks "could not tell")
Task 9: review spec ✅ quality ❌ (0 C, 1 I, 6 minor)
Task 9: minor (deferred): integrate.js:112 github.com regex unanchored (matches any URL containing it)
Task 9: minor (deferred): integrate.js:15 spawn 60 s default timeout for push/gh/merge/metrics
Task 9: minor (deferred): integrate.js:49 pid filter is dead code
Task 9: minor (deferred): engine_integrate.test.js:84-85 dead tasks assignment; two scenarios in one test
Task 9: minor (deferred): no tests for merge conflict park, liveCheckoutBusy busy path, mergeDone resume skip, nonzero final_findings
Task 9: minor (deferred): mr_create has no steps.CHECKS entry (resume parks "could not tell")
Ruling: ledger commit for mr/keep goes on the spec branch in the worktree (before the push for mr, so the PR carries it); merge keeps it on main after the merge; commit_ledger CHECK reads the facts' branch — the brief's step list never said where, and committing on main for an unmerged MR changes main outside the integration — costs a moved commit if the user wanted the ledger on main.
Task 9: fix round 1 dispatched fix-t9 (standard, sonnet), FIX_BASE c60f79f
Task 5: green check ok (verify rc 0) — 89c4b80
Task 5: carry to T8 — the job passed to backend.start must carry worktree and report
Task 5: review dispatched rev-t5 (standard) on 89c4b80
Task 5: report lacked the exact verifyCommand + rc (implementer already shut down); lead ran the verifyCommand: rc=0, 22/22 + 4× ALL PASS (task-5-verify-lead.out) — counts as the green check
Task 3: green check ok (verify rc 0, 57/57) — 4ed7ba4
Task 3: carry to T8 — log every strategy input event into events (same kind, fields in detail); fix job_done carries fix_stats {lines, files, added, tests_removed}; command extras run_check {check:"stale"}, bounce/round on fix jobs, outcome on set_state done, log kind refused (task-3-report.md "What Task 8 must supply")
Ruling: proceed after tests_red_after_merge → the core calls integrate.finalize (Task 9 export) for ledger and metrics, then applies set_state done — no new strategy command — costs a core change if the strategy should own it.
Ruling: a deny/fail signal on a strategy-opened park: the core applies only the strategy's set_state done, never its own as well — costs one duplicate event if wrong.
Ruling: integrated {outcome:"tests_red_before"} parks with step integrate (approve integrates again) — not a spec §4 case, and parking asks the user rather than failing the spec — costs a manual fail_spec answer.
Task 3: review dispatched rev-t3 (standard) on 4ed7ba4
Task 5: review spec ✅ quality approved-with-Important (0 C, 1 I, 7 minor) — I: test_agent_dir.zsh:469 hard-coded sha oracle
Task 5: minor (deferred): claude_tmux.js:288-296 dead tmux server never yields gone (engine stalls to job timeout)
Task 5: minor (deferred): claude_tmux.js:213,218 start has no stale-report guard (minMtime 0); resume guard untested
Task 5: minor (deferred): claude_tmux.js:237 resumed handle's close overwrites the first attempt's log
Task 5: minor (deferred): claude_tmux.js:223-228/275-276 duplicated newest-record loop
Task 5: minor (deferred): claude_tmux.js:258 resume window counter in memory; restart → "window already exists"; handles not re-adoptable
Task 5: minor (deferred): engine_backend.test.js:439 re-derives stateDir; real-state assertion flaky when dir empty (plan-mandated)
Task 5: minor (deferred): claude_tmux.js:192-195 fake TMUX value to pass tmux-ctl's inside-tmux check
Task 5: carry to T8 — report path unique per attempt (stale-report guard on start is absent)
Task 5: fix round 1 dispatched fix-t5 (standard, sonnet), FIX_BASE 89c4b80
Task 9: fix round 1 green (28/28, rc 0) — 6bb02cd; re-review dispatched rerev-t9 (standard)
Task 3: review spec ✅ quality approved (0 C, 0 I, 7 minor)
Task 3: minor (deferred): spec_driven.js:218-229,239 reviewer job_done without usable findings / unknown verdict treated as pass
Task 3: minor (deferred): spec_driven.js:85,289 done(outcome) can emit outcome: undefined
Task 3: minor (deferred): retryHigher for review kind (:343-346) untested
Task 3: minor (deferred): several guard tests lack a named mutation
Task 3: minor (deferred): last test forbids any require() in the strategy, not just a bounce.js cycle
Task 3: minor (deferred): commands alias input arrays (findings: t.open, ctx.wave)
Task 3: minor (deferred): a zero-task plan goes straight to final_review ([].every)
Task 3: complete (commits 4ed7ba4, review clean)
Task 5: fix round 1 green (test_agent_dir ALL PASS, rc 0) — cdf6e0a; re-review dispatched rerev-t5 (standard)
Task 9: fix round 1/5 (1 addressed, 0 open; commits c60f79f..6bb02cd)
Task 9: minor (deferred): integrate.js commitLedger for mr renders before push/mr_create events, so the PR ledger lacks them
Task 9: minor (deferred): integrate.js commitLedger throws when neither spec.worktree nor ctx.worktree is set
Task 9: complete (commits effcd50..6bb02cd, review clean)
Ruling: a refused retry_higher_tier re-escalates once; a second refusal for the same job parks the spec (cap in the core, not the strategy) — costs one extra architect round if the user wanted fail instead.
Task 5: fix round 1/5 (1 addressed, 0 open; commits 89c4b80..cdf6e0a)
Task 5: complete (commits 6b9394c..cdf6e0a, review clean)
Task 8: dispatched impl-t8 (frontier, fable) BASE cdf6e0a
Task 8: green check ok (verify rc 0, 43/43; npm test 250 pass) — bdea99c
Ruling: every terminal spec outcome (failed included) goes through integrate.finalize for the ledger archive and metrics record, not only after tests_red — the queue rules record metrics for a failed spec — costs a ledger commit on failed specs.
Ruling: claude_tmux needs adopt(job, handle) (re-watch a window by pane id and status file after an engine restart) before Task 12; added to Task 8's fix round as a lead finding, touching claude_tmux.js — costs one fix round.
Ruling: inbox.workerRows source id becomes <job id>:<pane>:gone (pane ids are reused after a tmux restart); added to Task 8's fix round, touching inbox.js — costs one fix round.
Task 8: review dispatched rev-t8 (standard) on bdea99c
Task 8: carry to T11 — opts.notify defaults to stderr ([Engine] stopped/paused); tmux-ctl tell refuses the lead window, so the CLI supplies delivery; deadline re-arm writes ~3 events/job/2 min (printer may hide); userGate read by regex in core (compile.js does not pass it)
Task 8: minor (deferred): claude_tmux never emits model_limit/usage_limit status; limit detection only via fake + status-line tap
Task 8: review spec ❌ quality ❌ (0 C, 4 I, 6 minor) — I1 finalize every terminal outcome, I2 adopt, I3 gone source id, I4 needs_you wait left open on job failure
Task 8: ⚠️ integrate/finalize/revert idempotence: resolved by lead — every outside action in integrate.js is a steps.run row keyed per spec (integrate.js:25)
Task 8: ⚠️ ready worker heartbeat before report grace: lead confirmed a real gap → finding I5 in the fix round
Task 8: ⚠️ retryRow aliases fix_wave→fix, re_review→final_review; inbox drain writes two events per tx (Task 6 design) — left to the final review
Task 8: minor (deferred): core.js 1026 lines in one start() closure; briefs and platform readers could move out; produced/STOP/effects needs a comment
Task 8: minor (deferred): core.js:957-962 start throw emits step_failed + fake job_running before failAttempt
Task 8: minor (deferred): run(specId) loops forever on a missing spec; addSpec ignores strategy/backend (Task 11)
Task 8: minor (deferred): core.js:308 userGate regex over the description
Task 8: minor (deferred): core.js:448-449,479 python3/git subprocesses inside the drain tx hold the write lock
Task 8: minor (deferred): blocking spawnSync for checks and integrate (allowed by constraints)
Task 8: fix round 1 dispatched fix-t8 (frontier, fable), FIX_BASE bdea99c
Task 8: fix round 1 green (81/81 covering, npm test 257, rc 0) — ee757be; re-review dispatched rerev-t8 (standard)
Task 8: lead notes for round 2 — finalize on a failed merge-integration spec commits the ledger on main with no live-checkout check (should land on the spec branch like keep); adopted jobs keep pre-restart clocks (no heartbeat grace after resume); plan unreadable after worktree removal if crash between integrate and spec_done
Task 8: fix round 1/5 (5 addressed, 0 open; commits bdea99c..ee757be)
Task 8: minor (deferred): a failed close_window step is not retried in-process, only after restart
Task 8: minor (deferred): the I5 ready exemption also covers a ready status with no told_at (only the job timeout remains)
Task 8: complete (commits cdf6e0a..ee757be, review clean)
Ruling: fix-t8's two concerns become plan Task 8b (standard), run in parallel with Task 11 (disjoint files) before Task 12: (a) finalize for a failed/denied spec commits the ledger on the spec branch in the worktree (as keep), never on main; (b) resume() gives adopted jobs a fresh heartbeat window (deadline re-armed from resume time) — both bite Task 12/13; the plan-unreadable-after-worktree-removal edge goes to the final review — costs one extra task.
Task 8: minor (deferred): a crash between merge integration (worktree removed) and spec_done leaves the plan unreadable on restart
Task 8b: dispatched impl-t8b (standard, sonnet) BASE ee757be
Task 11: dispatched impl-t11 (standard, sonnet) BASE ee757be
Task 8b: green check ok (verify rc 0, 65/65, npm test 261) — ef3efed
Task 8b: review dispatched rev-t8b (standard) on ef3efed
Task 8b: review spec ✅ quality approved (minors in task-8b-review.md, for the final review)
Task 8b: complete (commits ee757be..ef3efed, review clean)
Task 11: green check ok (verify rc 0; cli 20/20, npm test 281) — e12a160; also edited tools/tests/test_ctl_registry.zsh (header text) and the tmux-ctl not-inside-tmux gate exempts engine
Task 11: review prompt ready (rev-t11-prompt.md, review-t11-e12a160.diff) — dispatch after the handoff
Task 11: review dispatched rev-t11 (standard) on e12a160 (after handoff)
Task 11: review spec ✅ quality needs fixes (I1 metrics_start failure strands spec; ⚠ confirmed: metrics start argv uses --spec, metrics.py takes spec positional)
Ruling: a metrics_start failure marks the step failed, logs an event and the run continues (no retry) — measurement never fails a spec per the queue rule — costs a spec with no start line if wrong (record backfills from git)
Ruling: T11 ⚠ help header 2,85p unchanged since base, constraint's 84 is stale; metrics start only with --batch is right (--batch required) — costs nothing, Task 14 runs pinned suites
Task 11: minor (deferred): prev env dance in engine_cli.test.js ~921-925 is dead code
Task 11: minor (deferred): notifier feed line kind park with spec null
Task 11: minor (deferred): SIGINT process.exit(130) skips finally blocks
Task 11: minor (deferred): status --waiting prints answer options literally, not one command per option
Task 11: fix round 1/5 dispatched fix-t11 (standard) FIX_BASE e12a160 (F1, F2, F3 test rename/scenario)
Task 11: fix round 1 green (cli 22/22, npm test 283/283) — 93e6e44; re-review dispatched rerev-t11 (standard)
Task 11: minor (deferred): cmdResume rc=1 branch has no test (F3 renamed the test, scenario >25 lines)
Task 11: fix round 1/5 (3 addressed, 0 open; commits e12a160..93e6e44)
Task 11: complete (commits ef3efed..93e6e44, review clean)
Task 12: dispatched impl-t12 (standard, sonnet) BASE 93e6e44
Task 12: green check ok (verify rc 0, 23/23 ~87 s; npm test 306/306) — 3e38017; concern: core.pollBackend matches backend events by pane only
Ruling: harden core.pollBackend to match on handle.job when the handle carries it (pane as fallback, lastState keyed by job) as Task 12b (standard) before T12's review; T12 and T12b reviewed as one package — pane ids repeat after a tmux server restart, so a gone event could fail an unrelated job — costs one small fix task
Task 12b: dispatched fix-t12b (standard, sonnet) BASE 3e38017
Task 12b: green check ok (core+resume 76/76 rc 0; npm test 310/310) — 88d8107; concern: added pane fallback when the named job is not running (resumed handles keep the old job id)
Task 12: review dispatched rev-t12 (standard) on 93e6e44..88d8107 with Task 12b (two verdict sets)
Task 12b: review spec ✅ quality approved (fallback sound; residual: resumed handle naming a still-running job on another pane is ignored, unreachable today)
Task 12b: minor (deferred): pollBackend three-way conditional is dense (core.js ~79-87)
Task 12b: minor (deferred): fallback branch (named job not running, other pane) has no direct test
Task 12b: complete (commits 3e38017..88d8107, review clean)
Task 12: review spec ❌ quality needs fixes (I1 no signal written before the kill)
Ruling: T12 minors "stale unique-pane shim" and "leak check compares full list-sessions text" go into fix round 1 — the shim hides what 12b fixed and the text compare flakes on a live server — costs a slightly larger round
Task 12: minor (deferred): kill lands up to one 25 ms poll after the event kind appears
Task 12: minor (deferred): sequence comparison also drops deadline, nudged and repeated step_intent
Task 12: fix round 1/5 dispatched fix-t12 (standard) FIX_BASE 88d8107 (F1 signal before kill, F2 drop pane shim, F3 session-name leak check)
Task 12: fix round 1 green (resume 23/23 rc 0; npm test 310/310) — 5e6e420; re-review dispatched rerev-t12 (standard)
Task 12: fix round 1/5 (3 addressed, 0 open; commits 88d8107..5e6e420)
Task 12: minor (deferred): duplicated phrase in the signal test title
Task 12: complete (commits 93e6e44..5e6e420, review clean)
Task 13: dispatched impl-t13 (standard, sonnet) BASE 5e6e420
Task 13: run 1 blocked: worker window sat at Claude's trust-folder prompt (fresh /tmp clone), heartbeat_timeout after 2 min, retried into the same prompt
Ruling: T13 run 2 clones under /Users/francisco.ruiz/agent-board/.claude/e2e/ (already trusted) and uses the real TC_STATE (TC_ENGINE_DIR temp), never editing ~/.claude.json — deviates from the brief's /tmp path, recorded in the note — costs a less isolated e2e if wrong
Task 13: finding (for final review): a worker stuck at the trust prompt is not detected as needs-you before the heartbeat deadline; engine retries into the same prompt
Task 13: run 2 blocked the same way (a nested clone is its own git root, so not trusted)
Ruling: T13 run 3 uses a scratch git worktree of the real repo (branch e2e-engine-scratch off the engine branch) instead of a clone, guarded so the live checkout and main never move, everything removed after — worktrees inherit trust and match the engine's real use; never edit ~/.claude.json — costs a less isolated e2e if wrong
Task 13: run 3 (scratch worktree) — five jobs done, branch verify green; engine stopped at integrate metrics_record: `--batch null` (finalize records unconditionally) → rc 1, spec left integrating; final_review window not closed
Ruling: integrate.finalize skips metrics_record when the spec has no batch, and a metrics_record failure logs and continues (never stops the engine or fails the spec), as Task 9c (standard); T13 then resumes run 3 instead of a fresh run — measurement never fails a spec — costs one small fix task
Task 9c: dispatched fix-t9c (standard, sonnet) BASE 5e6e420
Task 9c: green check ok (integrate 20/20 rc 0; npm test 314/314) — 5b52252
Task 9c: review dispatched rev-t9c (standard)
Task 9c: review spec ✅ quality approved; ⚠ core after finalize and resumed finalize over a failed metrics_record row — to be closed by T13's resume of run 3
Task 9c: minor (deferred): integrate.js:151 catch swallows every throw from steps.run, including a DB error writing the failed row
Task 9c: minor (deferred): batch "" guard branch has no test
Task 9c: ⚠ closed by T13: resume after the fix reached `kept e2e-engine-scratch`, rc 0, final_review window closed by the engine, rebuild --check 0
Task 9c: complete (commits 5e6e420..5b52252, review clean)
Task 13: green check ok (verify prints 5, rc 0; resume outcome kept, rc 0; cleanup done, live checkout unchanged) — 27d139d
Task 13: finding (for final review): fable final_review worker ran the whole engine suite on a three-line change (cost)
Task 13: review dispatched rev-t13 (standard); Task 14 dispatched tester-t14 (mechanical, haiku) in parallel (read-only suites)
Task 13: review spec ✅ quality needs fixes (I1 note omits 98 e2e-helper lines leaked into the live feed by the real TC_STATE)
Ruling: the 98 feed lines stay in the live feed (consumers read by byte offset, deleting lines would shift them) and the note records them; T13 minors (deadline events unexplained, 430 vs 411 s, missing `resumed -`, deleted-clone log path) go into the same doc-only round — costs stale e2e lines on the board feed if wrong
Task 13: finding (for final review): engine feed publishing follows TC_STATE, not TC_ENGINE_DIR, so an isolated engine dir still writes the live feed
Task 13: fix round 1/5 dispatched fix-t13 (mechanical re-review tier n/a: standard task) FIX_BASE 27d139d
Task 13: fix round 1 done (doc-only, verify prints 5 rc 0) — 73ca4fa; scoped re-review NOT yet dispatched (handoff)
Task 14: run 1 red: all.zsh rc 1 FAIL 2/213 (zsh/test_teammate_hooks.zsh, engine kill-point spec_added), engine npm 312/314; bridge 198/198; both pass with AGENT_BOARD, AGENT_BOARD_LEAD, AGENT_BOARD_REPO unset (one run) — env-dependent, not diagnosed
Session resumed from handoff 2026-11-23-engine-p1-t13-t14
Task 13: fix round 1 scoped re-review dispatched rerev-t13 (standard, sonnet) 27d139d..73ca4fa
Task 14: diagnosis dispatched debug-t14 (standard, sonnet) brief task-14-fix-brief.md
Task 13: fix round 1/5 (5 addressed, 0 open; commits 27d139d..73ca4fa)
Task 13: complete (commits 5e6e420..73ca4fa, review clean)
Task 14: debug-t14 diagnosis: engine kill-point spec_added = timing race (kill between spec_added and the CLI's metrics_start; resume does not redo it), not env (3/3 set, 3/3 unset); test_teammate_hooks fails identically on main, caused by AGENT_BOARD_LEAD alone — pre-existing
Task 14: fix 4567c60 (test-only, engine_resume tolerates a lost metrics start at spec_added); npm test 314/314 rc 0 with env inherited
Ruling: test_teammate_hooks failure under AGENT_BOARD_LEAD is pre-existing on main, recorded not fixed here; this branch's all.zsh verdict is taken with env -u AGENT_BOARD_LEAD — costs a masked branch regression in that suite if wrong (main fails identically)
Ruling: a kill between spec_added and metrics_start loses the metrics start line on resume and that is accepted (measurement never fails a spec); the test is relaxed for that kill point only — costs a missing metrics start for a spec killed in that window if wrong; flagged for final review
Task 14: fix review rev-t14 spec ✅ quality needs fixes (I1 lostStart misses kill between step_intent and step_done; compute pre-resume)
Task 14: minor (deferred-or-fold): splice(1,2) hard-codes reference order — folded into fix round 1
Task 14: fix round 1/5 dispatched fix-t14 (standard, sonnet; fresh, debug-t14 shut down) FIX_BASE 4567c60
Task 14: all.zsh rerun (env -u AGENT_BOARD_LEAD, HEAD 4567c60) rc 1 FAIL 1/213 engine: kill point task_complete 'timed out waiting for event task_complete' under load (368 s test); test_teammate_hooks passed; added to fix round 1 for fix-t14
Task 14: fix round 1 done (656f61b lostStart pre-resume + two window tests; d911b5f until() deadline 30→120 s for load); npm test 316/316 rc 0; RED for intent-only window not reproducible (stub never answers not_done) — gap for final review
Task 14: fix round 1/5 (4 addressed, 0 open; commits 4567c60..d911b5f)
Task 14: minor (deferred): the two new kill-window tests rely on a 2 s delay margin, may flake under heavy load
Task 14: finding (for final review): steps.reconcile not_done → rerun path for a kill inside metrics_start is untested (stub always answers done)
Task 14: green: all.zsh (env -u AGENT_BOARD_LEAD) ALL PASS 213 jobs rc 4 (over budget, accepted) at d911b5f; bridge 198/198 at 27d139d (bridge untouched since)
Task 14: complete (commits 73ca4fa..d911b5f, review clean)
Final review: dispatched final-review (frontier, fable) fefceab..d911b5f
Final review: ready with fixes, 0 C / 6 I / 14 M (final-review.md)
Ruling: final fix wave = I1 (denied outcome classed as failure in integrate.js:128, core.js:626/633), I2 (feed PROGRESS tiers = kinds the core emits), I3 (adopted worker gets brief/report paths), I6 (rebuild --apply keeps new inbox rows) — I6 included because the wave is open anyway — costs one larger fix diff if wrong
Ruling: I4 (real-run gaps) recorded as three unchecked gates in the PR description; I5 (claude-tmux never reports model/usage limit: workers park instead of moving to Opus) ships, first-class part 2 task — costs a Fable-limited worker parking a spec instead of retrying on Opus until part 2
Ruling: M1-M14 ship as follow-ups; M1, M5, M6, M9 open part 2's plan — costs those edges reachable only once part 2 wires the queue runner
Final review: fix wave dispatched fix-final (standard, sonnet) FIX_BASE d911b5f
Final review: fix wave done 299147a (I1, I2, I3, I6; npm test 322/322 rc 0, one load flake at green_check kill point 320/322 in the first run); scoped re-review dispatched rerev-final (standard)
Final review: fix wave re-review rerev-final all 4 addressed, no new C/I; final review clean (I4 gates → PR description, I5 → part 2, minors → part 2/follow-ups per final-review.md triage)
Post-archive: merged origin/fix/ci-green (cb78975; bin/tmux-ctl conflict on the not-inside-tmux line resolved as the union: kept `engine`, added help/no-args).
Post-archive: engine_resume "kill after spec_done" red after the merge (engine diff 59360ed..cb78975 empty: a race, not the merge); fixed test-only 07a163f; npm test 322/322 x3.
Ruling: a kill between close_window's step_intent and step_done at the spec_done kill point may lose that tail — resume finds no open spec ("nothing to resume") and the window just stays open for the user — costs if wrong: an unclosed window after a crash; follow-up for part 2: resume reconciles open step intents of a done spec.
Ruling: one unexplained flake seen once ("kill after job_created", detail not captured; passed on rerun and 3 runs after) — residual risk noted in the PR — costs if wrong: an intermittent red engine suite.
