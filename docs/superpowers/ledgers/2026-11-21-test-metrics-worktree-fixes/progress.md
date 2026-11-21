# SDD ledger — plan: docs/superpowers/plans/2026-11-21-test-metrics-worktree-fixes.md
Spec: docs/superpowers/specs/2026-11-19-test-metrics-worktree-fixes-design.md · base 76273a2
Preflight scan:
| pair/task | shared | finding |
| T1–T5 pairwise | no shared file (files lists disjoint) | parallel-safe |
| T6 vs T1–T5 | consumes all; read-only | runs last |
| T1 self | tests vs code agree; forced-failure step not kept | ok |
| T2 self | decoy matches old constant; current check already scoped (703d27c) | ok, R1 |
| T3 self | tests (a),(d) RED on old code; snippet run on scratch repo (sp False, ff True) | ok, R2 |
| T4 self | exit 2 vs main's uniform 1 | R3 |
| T5 self | root from derive; tests build cwd from self.root | ok |
Ruling: R1 spec §2 leak check already scoped by 703d27c; remaining work is per-run path + decoy — cost if wrong: one redundant test change
Ruling: R2 reset entries carry the ref string, so test the entry %H against ctx.refs — cost if wrong: resets to non-ancestors could be graced (they are not merged anyway)
Ruling: R3 UsageError code 2, message keeps 'metrics: start:' prefix — cost if wrong: a one-word stderr difference from the spec text
Ruling: parallel dispatch T1+T2 (one mechanical teammate, sequential, batched review), T3, T4; T5 after T3 — files disjoint — cost if wrong: git index.lock retries
Task 1+2: dispatched impl-t1 (haiku, mechanical, batch) base 76273a2
Task 3: dispatched impl-t3 (sonnet) base 76273a2
Task 4: dispatched impl-t4 (sonnet) base 76273a2
Task 3: impl-t3 DONE 569518e (36 OK); green check passed
Task 5: dispatched impl-t3 (sonnet) base 569518e
Task 1: impl-t1 DONE 5da3d94; Task 2: DONE 83ce452; green checks passed
Ruling: T1 forced-failure AC met (0 left) but tt_teardown's kill-server already reaps stub+server, so the trap's effect is not shown by the forced runs — accept as defence in depth plus the new no-leftover check — cost if wrong: the historic hour-long leak path stays unexplained
Task 3: review dispatched to rev (review-83ce452..569518e.diff)
Task 3: review spec ✅ quality ✅; minor (deferred): ': Fast-forward' unanchored also matches a commit message (spec says contains; only extends grace)
Task 3: minor (deferred): test (c) bare assertNotEqual
Task 3: bounced 1/2 (group run claim wrong: 5 files match test_worktree_safety*.py)
Task 5: impl-t3 DONE 856225c; bounced 1/2 (no Verify output in report)
Batch 1-2: reviewed together (2 tasks)
Task 1: ⚠️ dc_reap not exercised — resolved by the earlier T1 ruling (defence in depth)
Task 1: minor (deferred): INT/TERM trap returns 0 so the script continues after the handler (same as lib.zsh:49)
Task 2: minor (deferred): decoy PID not covered by the trap (self-expires after 30 s)
Task 1: complete (commits 76273a2..5da3d94, review clean)
Task 2: complete (commits 5da3d94..83ce452, review clean)
Task 3: group run 130 OK; complete (commits 83ce452..569518e, review clean)
Task 5: green check passed; review dispatched to rev
Task 4: impl-t4 DONE_WITH_CONCERNS b1611d5 (43 OK; metrics* 319 OK); green check passed
Ruling: a bad --worktree still appends the module's usual kind:error line (no start record) — every metrics failure logs one via _log_error; "writes nothing" read as no start record — cost if wrong: one error line per typo in runs.jsonl
Task 4: review dispatched to rev
Task 5: review spec ✅ quality ✅; ⚠️ cwd path form — resolved: real runs-agent-board.jsonl cwds are /Users/francisco.ruiz/agent-board[/.claude/worktrees/…] (26 under worktrees), same form as the repo root; Task 6 re-checks on real data
Task 5: minor (deferred): falsy root with worktree set falls back to the unnarrowed pick (derive always passes root)
Task 5: complete (commits 569518e..856225c, review clean)
Task 4: review spec ✅ quality ✅; ⚠️ other copies of the old sentence — resolved: wide grep hits only historical plans/specs
Task 4: minor (deferred): rel_worktree records a subdir (.claude/worktrees/w1/board) as given; record then counts only that subdir — maybe normalise to parts[:3]
Task 4: minor (deferred): '..' check dead after normpath; dead 'before = before + added' in test; once-only test has no mutation
Task 4: complete (commits 856225c..b1611d5, review clean)
Ruling: Task 6 brief names ~/.local/state/agent-board/runs-agent-board.jsonl; the real file is tc_env.state_dir() = $TMPDIR/tmux-ctl-503/runs-agent-board.jsonl — corrected in the dispatch — cost if wrong: none
Task 6: dispatched impl-t3 (sonnet) base b1611d5
Final review: dispatched final-rev (session level) on 54f660a..b1611d5
Task 6: ALL PASS 178 jobs rc=4 (over budget); reflog 4 branches 0 graced; metrics 9.87M→70.12M, md5 unchanged; failed-run log narrowed None vs unnarrowed awake-outside-tmux run
Task 6: audit: 484 added rows all under worktrees/discord-ops-fixes and in window (0 outside); 209 lead rows (sessions 68f302b9, b6baabff = #18's leads) + 275 teammate rows, all git_branch=main
Task 6: complete (no code; evidence in real-state.md)
Final review: ready to merge, 0 Critical/Important; 5 optional minors (unanchored ': Fast-forward', bare assertNotEqual, rel_worktree subdir, no tmux-ctl pass-through test, decoy outside trap); all rulings non-blocking
