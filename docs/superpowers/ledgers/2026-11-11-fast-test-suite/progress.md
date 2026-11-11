# SDD ledger — plan: docs/superpowers/plans/2026-11-11-fast-test-suite.md
Spec: docs/superpowers/specs/2026-11-10-fast-test-suite-design.md
## Preflight scan
| pair / task | shared file or interface | finding |
| T1–T2 | none (board test files disjoint) | ok, parallel-safe |
| T3→T4,T5,T6,T7 | all.zsh job names/--list consumed by T6 audit, T7 runs | ok: names fixed in Global Constraints |
| T5–T6 | tools/tests/*.zsh: T6 may flag T5's files | ok: T6 runs after T5 |
| T4–T6 | board worktree tests | ok: T6 after T4 |
| T2–T6 | env-at-import pattern | ok: T6 audit repeats T2's check for all modules |
| T1 self | tests vs launch_line | ok |
| T2 self | debugging task; files may grow to code | ok, AC requires ledger justification |
| T3 self | creates all.zsh + test | ok |
| T4/T5 self | counts before==after | ok |
| T6 self | Verify grep count needs header+sep rows | ok |
| T7 self | mechanical, runs + docs | ok |
Ruling: run T1/T2 (fts-fix) in parallel with T3 (fts-impl) — disjoint files, no blockedBy link — cost if wrong: a merge conflict in one test file, cheap to redo.
Task 1: dispatched fts-fix (sonnet/standard), base 9a6233c
Task 3: dispatched fts-impl (sonnet/standard), base 9a6233c
Task 1: green check ok (Ran 20 OK, exit 0)
Task 1: review dispatched fts-rev (sonnet/standard), package review-9a6233c..a68a254.diff
Task 2: dispatched fts-fix, base a68a254
Task 1: review spec ❌ quality needs fixes (2 Important: launch_line outside env patch; launcher-path assertion lost) — fix round 1 sent to fts-fix, FIX_BASE a68a254
Task 2: green check ok (Ran 26 OK + ALL PASS, exit 0); review dispatched fts-rev
Task 1: fix round 1/5 committed 0e47e1f..4605892 (13+/11-, 2 files); re-review queued to fts-rev
Ruling: start Task 4 on fts-fix before Task 3 lands — T4 only needs the board test files, not the runner; the plan's T3 dependency was ordering only — cost if wrong: none beyond a re-run under all.zsh in T6. Task 4: dispatched fts-fix, base 4605892
Task 2: root cause session tests: server.py:47 reads TMUX_DASH_TOKEN at import; discover order supplied it; fix setdefault in test (pattern of ~8 modules)
Task 2: root cause test_prompt_argv.zsh: ab_path (bin/_ab_claude.zsh:4) keeps PATH when <repo>/bin already on it; test now scrubs <repo>/bin; code judged correct
Task 2: review spec ✅ quality Approved; ⚠️ root causes→ledger resolved (above); ⚠️ full board discover → lead runs it
Task 2: minor (deferred): prompt_argv scrub removes only exact $R/bin spelling
Task 2: minor (deferred): no check covers ab_path "already on PATH" branch (pre-existing gap)
Task 2: minor (deferred): module-level setdefault makes token process-global (matches existing pattern)
Task 1: fix round 1/5 (4 addressed, 1 open — Minor 3 report-only mutation note; commits 0e47e1f..4605892)
Task 1: minor (deferred): mutation 1 only partly demonstrates AC (report note)
Task 1: complete (commits 9a6233c..4605892, review clean)
Task 1: minor (deferred): test_manual_hint_names_the_absolute_launcher pops AGENT_BOARD_REPO without a patch (pre-existing)
Task 3: green check ok (test_all_runner ALL PASS 38 ok, rc 0; 13 mutations fail named checks); review dispatched fts-rev, package review-4605892..18cc4e8.diff
Task 3: note for Task 6 — test_all_runner.zsh takes ~40 s and has sleep-timed concurrency checks (flake risk under load)
Task 5: dispatched fts-impl, base 18cc4e8
Task 3: review spec ✅ quality needs fixes (Important: TERM trap orphans job processes) — fix round 1 sent to fts-impl with M1,M2,M5,M6; FIX_BASE 18cc4e8
Task 3: minor (deferred to Task 6): M3 -j 2 overlap check can flake under load
Task 3: minor (deferred to Task 6): M4 env check covers only zsh/sh stubs
Task 2: full board discover: Ran 1027, 1 failure — test_worktree_board StopWaitsForExit.test_no_wait_when_everything_is_already_gone 3.37s !< 3 (timing under load, concurrent Task 4/5 work; not Task 2) → passed to Task 4
Task 2: complete (commits a68a254..0e47e1f, review clean)
Ruling: Task 4 splits test_worktree_safety.py (and test_worktree_board.py if still >30 s) into class-group files sharing one fixture module, plus a template repo; count rule = sum of Ran N and identical class.method set — spec permits any change that keeps coverage; <30 s unreachable by fixtures alone (~70 s is code-under-test git calls) — cost if wrong: more test files to maintain, revertible by concatenation.
Task 4: green check ok (7 parts OK, max 22.0 s; discover test_worktree* Ran 152 OK); review dispatched fts-rev, package review-18cc4e8..f00812f.diff
Ruling: Task 6 starts now on fts-fix for the non-zsh jobs (board, tools py, skills, statusline, hooks); zsh rows and the parallel/serial acceptance runs wait for Tasks 3 fix + 5 — splits the audit by file ownership — cost if wrong: a second pass over zsh rows.
Task 4: minor (deferred): 1. **test_worktree_board_remove.py (last test): the assertion is blind to a wait that does not use `time.sleep`.** A busy-wait or an `Event.wait` loop would sti
Task 4: minor (deferred): 2. **board/tests/worktree_fixtures.py:1: the docstring is stale.** It says "shared by test_worktree_safety_*.py and test_worktree_board.py", but `worktree_board
Task 4: minor (deferred): 3. **The speedup comes from the split, not the fixtures.** Total serial CPU is unchanged (the report says the template saves about 2 git calls per test). Under 
Task 4: minor (deferred): 4. **Old plan docs still name `test_worktree_safety.py`** (the report notes this as historical). Nothing to do.
Task 4: complete (commits 18cc4e8..f00812f, review clean)
Task 5: report DONE_WITH_CONCERNS e0641be — approve 119.6→19-21 s (72 ok), teammate_window 57.2→5.6-7 s (10 ok), test_bg 44.6→34-45 s (55 ok, AC open)
Ruling: test_bg.zsh splits by section into test_bg_<section>.zsh (sum ok 55, same check names), not tmux-ctl poll changes — same rule as Task 4, spec allows any coverage-keeping change — cost if wrong: more files.
Task 3: fix round 1 still not committed at Task 5 report; re-requested from fts-impl
Task 3: fix round 1/5 committed a4a18d4 (42 ok; Important + M1,M2,M5,M6); re-review dispatched fts-rev
Task 6: fts-fix commit ad973bd touches Task 4's no-wait test (counts only the server's sleeps) — goes to the Task 6 review
Task 3: fix round 1/5 (5 addressed, 0 open; commits ad973bd..a4a18d4)
Task 3: minor (deferred, final review should fix): killjobs signals process groups of finished jobs — recycled pid could hit an unrelated group; skip indexes whose .res exists
Task 3: minor (deferred): 3 more fix-diff minors in task-3-rereview-1.md
Task 3: complete (commits 4605892..a4a18d4 own commits 18cc4e8,a4a18d4; review clean)
Task 5: round-2 split 9121568 (test_bg → 4 files + bg_common.zsh, 17+30+2+6=55 ok, each <30 s at load 11-20); green check ok
Ruling: accept Task 5's solo runs from background Bash instead of tmux-ctl run tests — the tmux-ctl requirement guarded PATH dependence fixed in Task 2; Task 7 runs once in the live tests window — cost if wrong: a PATH-only failure found at Task 7.
Task 5: review dispatched fts-rev, package review-task5-e0641be+9121568.diff
Task 5: review spec ❌ quality needs fixes (3 Important: stuck-records scope narrowed; approve read loop misses a sent key; dead concurrent segment silent) — fix round 1 sent to fts-impl (+ got budget back to 5 s); FIX_BASE 9121568
Task 5: minor (deferred): fwait and swap-seam poll give up silently on timeout (next check fails, no false pass)
Task 5: minor (deferred): isolation of the 7 approve segments checked by reading only
Task 5: minor (deferred): test_bg_lock sleep 1 before TERM kept (race intent)
Task 5: minor (deferred): solo runs not via tmux-ctl run tests (see ruling)
Task 6: part A DONE_WITH_CONCERNS (audit doc 119 rows; 65/65 non-zsh alone pass; parallel non-zsh ALL PASS ×2 at 5m35s/6m57s, rc 4 over budget); review deferred to whole Task 6
Ruling: add Task 4b (native #17) — board metrics test files (added after the baseline) are now the long pole >30 s; spec Decisions cover "every file over 30 s" — cost if wrong: extra split files.
Task 4b: dispatched fts-fix, base HEAD
Task 6: open from part A — hooks/test-context-size-guard.sh counts files in real ~/.local/state/agent-board/context-guard (left as is); must be isolated or # serial — assigned to fts-fix after 4b
Task 5: round 3 split 6bdbb59 (approve → 4 files + approve_common.zsh, 23+16+16+17=72 ok; solo 9-11 s via tmux-ctl run) resolves I3; I1, I2, got budget re-requested
Task 5: fix round 1/5 committed 6bdbb59+451725b (I1 no_stuck helper, I2 drain read, I3 moot by split, budget 5 s; also fixed vacuous swap cases); re-review dispatched fts-rev
Task 4b: DONE_WITH_CONCERNS b0b257d — all metrics files <30 s solo except test_metrics_backfill_privacy 46-51 s under load (one test re-running 6 sibling files, now in parallel); sums/name sets unchanged; privacy counts 14/509 unchanged
Ruling: accept test_metrics_backfill_privacy over 30 s as inherent — one test, cannot split without changing the class.method set, its cost is the sibling files' code-under-test git calls; slowest-first scheduling starts it first — cost if wrong: the 300 s budget fails in Task 7 and this test needs a redesign.
Task 4b: review queued to fts-rev, package review-task4b.diff
Task 5: fix round 1/5 (4 addressed, 0 open; commits 9121568..451725b)
Task 5: minor (deferred): stale "read -t 3" header comment in approve_common.zsh
Task 5: complete (commits e0641be,9121568,6bdbb59,451725b; review clean)
Task 6: context-size-guard test isolated 288bb52 (HOME=fakehome per hook run; hook env override already existed; passed=36 before/after); audit row updated
Ruling: Task 7 (mechanical) docs part goes to idle fts-fix (sonnet) instead of a new haiku teammate — reuse saves a cold start; acceptance runs wait for Task 6 — cost if wrong: slightly higher token price for a small edit.
Task 7: docs part 8e6294f (CLAUDE.md, README.md, ARCHITECTURE.md Tests table row); acceptance runs pending Task 6 part B
Task 4b: minor (deferred): 1. **board/tests/test_metrics_backfill_privacy.py (sweep loop): a failing sibling leaves the others running.** On the first nonzero return the `assert
Task 4b: minor (deferred): 2. **Same loop: `lines += sink.read_text().splitlines() if sink.exists() else []`.** A sibling that exits 0 without ever creating its sink contributes
Task 4b: minor (deferred): 3. **Template timestamps.** Commits in the shared templates are dated when the first test in the process built them, not at each test's `setUp`. Tests
Task 4b: minor (deferred): 4. **Six sibling processes now run concurrently.** The siblings use their own scratch dirs (5 of 6 mention TC_STATE or tempfile; `test_metrics_fixwave
Task 4b: complete (commit b0b257d, review clean; timings load-dependent per reviewer)
Task 6 part B: f248e1a..a95b9ba — zsh suite ALL PASS 57 jobs ×2 (4m19s, 4m28s); full acceptance (2 parallel + 1 serial) dispatched to fts-impl; backfill_privacy audit row to fts-fix
Task 6: audit row 640ccfd — rows 125 = --list 123 + 2
Task 6: acceptance run 1 ALL PASS 123 jobs 6m35s rc=4 (SLOW; load 7.5→14, other sessions' agents running); flake fixes 826bf9c (tmux output truncation retries, root cause unproven)
Ruling: Task 6 passes on ALL PASS with budget-only rc=4; the <300 s budget is judged in Task 7 — Task 6's criteria are correctness/parallel-safety, the budget is the spec's whole-suite acceptance — if wrong, Task 7 fails the budget and the metrics-job speedups land late
Task 6: run 2 FAIL test_run_long_line (busy sleep 60 expired) → fcd3c33; pair of parallel runs restarted after it
Ruling: Task 4c added (fts-fix) — cut CPU of 5 metrics board jobs (193–238 s each under load) — the budget is at risk without it; costs one more review if the gain is small
Task 4c: 8fd9234 — decide CPU 9.0→3.1 s, record_usage 10.0→8.4 s, backfill/record_git unchanged (remaining spawns are in metrics.py); review dispatched to fts-rev
Task 6: full acceptance — parallel ALL PASS 123 ×2 after fcd3c33 (6m30s, 7m34s, rc=4 SLOW, load 8–10), --serial ALL PASS 123 16m45s; review dispatched to fts-rev (review-task6.diff)
Note: thycotic acsd endpoint agent ~74% CPU + Jamf ~20% at idle (exec scanning) — raises spawn cost for every job; 12 cores
Task 4c: complete (spec ✅, Approved, 3 Minor → final review)
Task 6: review ❌/Needs fixes — I1 poll_efficiency retry weakens next-build property; Missing 1 test totals not shown equal (logs deleted on pass); Minor: worktree_lock flake deferred, tt_free_port race comment, +3 minors → final
Ruling: Missing 1 is fixed by all.zsh printing a test total (sum of Ran N + ok lines) above the slowest-jobs list; equality proven by Task 7's runs vs --serial — the spec's verdict line stays exactly as specified — costs one runner change if the parse misses a format
Task 6: fix round 1/5 dispatched to fts-fix (I1, Missing 1, worktree_lock flake, tt_free_port comment); FIX_BASE=8fd9234
Task 6: fix round 1 → ba6628e ca6953a cb0c398 de9ec41 (worktree_lock root cause: "w1" substring of tmp path); re-review to fts-rev
Task 6: complete (re-review 4/4 addressed; Minors 3–5 → final)
Note: interiors project Blender render ~900% CPU (load 32) at 12:44Z — Task 7 parallel runs gated on load1 < 6 (max 45 min wait)
Final review dispatched to fts-final (session model, 0fc467c...HEAD) in parallel with Task 7 serial run
Final review: With fixes — load-bearing I1 killjobs signals finished jobs (pid wrap), I2 bare -j spins; not load-bearing I3 TERM→KILL gap, M1 tests: counts nested logs, M2 raw listing in retry failures, M3 audit 65→66; other deferred minors ruled harmless (final-review.md)
Final fix wave: dispatched to fts-wave (I1, I2, I3, M1, M2, M3)
Final fix wave: 449ed83 dd54209 (test_all_runner ALL PASS 52 ok; M2 files green solo); scoped re-review to fts-final
Task 7: serial run (pre-fix-wave) ALL PASS 123 jobs tests: 2693 23m46s rc=4 (load 34→22); reference serial to re-run on final tip after the parallel runs
Final re-review: 5/6 addressed, I3 partial (INT step is a no-op: & jobs inherit SIGINT ignored); nothing load-bearing
Ruling: I3 residual parked as an idea (drop the INT step or reset SIGINT in the perl launcher, fix the comment) — one fix wave is the cap and orphans self-exit within 10 min — costs a misleading comment in all.zsh until the follow-up
PAUSED 2026-11-11T13:19Z by the user (laptop closing). Resume: Task 7 runs on tip dd54209 — 3 parallel (load gate <6, max 45 min) then 1 --serial; parallel tests: must equal that serial; brief task-7-runs-brief.md, partial task-7-report.md. Then: archive ledger, commit tasks.json, finishing (merge, no push; main was 827c833), metrics record, spec #3.
RESUMED 2026-11-11T15:00Z; user: pause after spec #2 completes (do not start spec #3)
Task 7: parallel run 1 (interiors paused, load 4→10) FAIL 1/123 test_all_runner "KILLed … under 5 s" (timing under load); tests: 2697; 5m37s; longest jobs backfill 206 s, worktree_safety_recent 180 s
Ruling (user's choice): widen the interrupt bound to 8 s; accept the 300 s budget overshoot (rc=4 SLOW-only counts as pass) — the suite's own load stretches the longest jobs ~5x on this machine (endpoint agent taxes each exec) — costs: spec acceptance "<5 min" not met on this machine; recorded for the morning report
Task 7: cf1b340 widens the interrupt bound to 8 s; small re-review → fts-rr (haiku); runs (3 parallel + serial, rc=4 SLOW accepted) → fts-acc
Task 7: fix cf1b340 re-review Approved (2 Minor: diagnostic only on elapsed; stale ">5 s total" comment :296)
RELAYED 2026-11-11T15:50Z to a new lead; fts-acc respawned to record the detached acc.zsh runs (par1 started 10:46:29 local)
Task 7: acceptance on cf1b340 — par1 6m29s, par2 5m57s, par3 6m0s, --serial 18m32s: ALL PASS 123 jobs, tests: 2698 in all four, rc=4 SLOW-only (accepted), 0 FAIL (task-7-report.md)
Task 7: complete (commits 8e6294f,cf1b340; re-review Approved, acceptance passed)
