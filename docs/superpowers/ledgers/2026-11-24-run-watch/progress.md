# SDD ledger — plan: docs/superpowers/plans/2026-11-24-run-watch.md
Spec: docs/superpowers/specs/2026-11-24-run-watch-design.md. Branch run-watch, base main ec8b209, plan 1e13ecf (refreshed; refresher applied all 6 diff blocks to a main copy, every plan test passed).
Preflight scan:
| pair/task | produces → consumes | found |
| T2→T3 | handoff-arm.sh created → registered in hooks.json, tested by test_plugin | consistent (T3 blockedBy T2) |
| T3/T7 | both edit tools/tests/test_plugin.zsh | different anchors (before lead-stop-guard check / after [Watch] check); sequential, no clash |
| T4→T5 | Watch(tell,kill,caps_file), build(...,ps=) → server WATCH(tell=), build_overview passes ps | consistent (T5 blockedBy T4) |
| T4,T5→T6 | overview runs + watch runs + server wiring → e2e | consistent |
| T2,T5→T7 | features → docs/rule text | consistent |
| T1 | one-line scrub; verify both env ways | self-consistent |
| T2 | create script + test; verify the test | self-consistent |
| T3 | hooks.json + SKILL.md + test_plugin; verify uses env -u | self-consistent |
| T4 | 6 files, RECORD_KEYS [-6:] edits in both pinned tests (refresh fix) | self-consistent |
| T5 | server.py only; verify 3 suites | self-consistent |
| T6 | creates e2e only | self-consistent |
| T7 | orchestrator continuation lines (test_plugin/test_queue_ask_rule match ' N. ' one line: plan adds continuation lines) | self-consistent |
Preflight: no conflicts.
Task 1: dispatched rw-impl12 (mechanical, haiku), BASE 1e13ecf (with Task 2, one dispatch)
Task 2: dispatched rw-impl12 (mechanical, haiku), BASE 1e13ecf
Task 1: green check ok (verify ALL PASS x2, rc=0)
Task 2: green check ok (ALL PASS rc=0)
Batch 1-2: review dispatched rw-rev12 (standard, sonnet) on review-1e13ecf..3bc0cf0.diff
Batch 1-2: reviewed together (2 tasks): T1 spec ✅ quality ok; T2 spec ✅ quality ok
Task 2: minor (deferred): real `ps -o args= -p $CLAUDE_PID` branch (handoff-arm.sh:26-28) untested; only the TC_TEAMMATE_ARGS_FILE seam
Task 2: minor (deferred): CLAUDE_PID unset + no seam: a teammate with inherited AGENT_BOARD_LEAD=1 arms the mark (same as teammate-remind.sh)
Task 2: minor (deferred): leak check saw 0 real marks (weak, disclosed)
Task 2: ⚠ hooks.json registration resolved: plan Task 3 registers it
Task 1: complete (commits 1e13ecf..b63885b, review clean)
Task 2: complete (commits b63885b..3bc0cf0, review clean)
Task 3: dispatched rw-impl12 (mechanical, haiku), BASE 3bc0cf0
Task 4: dispatched rw-impl4 (standard, sonnet), BASE 3bc0cf0 (parallel with Task 3: disjoint files)
Task 3: green check ok (test_plugin ALL PASS rc=0, test_handoff_arm ALL PASS rc=0)
Task 3: review dispatched rw-rev3 (standard, sonnet) on review-3bc0cf0..10b8040.diff
Task 3: ⚠ resolved: a mark armed outside tmux never blocks (lead-stop-guard.sh:11 exits without $TMUX/$TMUX_PANE)
Task 3: minor (deferred): SKILL.md says "in the handoffs dir"; handoff-arm.sh:21 also accepts the older ~/.claude/handoffs
Task 3: complete (commits 3bc0cf0..10b8040, review clean)
Task 4: bounced 1/2 (Step 5 mutation runs skipped; verify green rc=0)
Task 4: green check ok (verify 4x OK rc=0; 7/7 mutations caught)
Task 4: review dispatched rw-rev4 (standard, sonnet) on review-10b8040..5c273dc.diff
Task 4: review rw-rev4: spec ❌ (1 Critical, 3 Important, minors)
Task 4: Ruling: KILL escalation only to pids in this overview's sample with the TERM-time cmd; none when ps unavailable or killed_at > 60 s old — spec says kill by PID only and never the wrong process; A4's kill(pid,0) probe alone is insufficient — cost if wrong: a hung run survives TERM unkilled (logged), never a wrong kill
Task 4: Ruling: the pane root (pane_pid) is never a run, whatever its argv — refines A3 (argv0-only claude test) — cost if wrong: a pane whose root is not claude never has its root watched
Task 4: Ruling: progress = subtree CPU rose OR subtree pid set changed — the spec's "CPU strictly greater" read with exiting workers counted as activity — cost if wrong: a hung run that churns children survives longer
Task 4: Ruling: a watch.json entry whose cmd differs from the current run starts fresh; EPERM at TERM drops the entry with one log line — cost if wrong: a reused pid's run is watched from zero
Task 4: fix round 1/5 dispatched to rw-impl4 (standard, sonnet), FIX_BASE 5c273dc, findings task-4-findings-r1.md
Task 4: Ruling: killed entries are pruned once settled or 1 h after killed_at — reviewer minor, cheap to fix inside the same round — cost if wrong: none (state only)
Task 4: Ruling: a settled killed entry whose run is still in the sample is kept until 1 h after the kill (implementer's choice, accepted) — pruning sooner would re-alert and re-TERM the same unkillable process each overview — cost if wrong: one stale entry per kill for up to 1 h
Task 4: re-review dispatched rw-rev4 (standard, sonnet) on review-5c273dc..<head>.diff
Task 4: fix round 1/5 (6 addressed, 0 open — pid+cmd KILL, pane root, pid-set progress, fresh entry on cmd change, EPERM drop, prune; commits 5c273dc..9b5da6a)
Task 4: minor (deferred): after EPERM the entry is dropped but the run stays sampled → possible re-alert ~every overview (tombstone would stop it)
Task 4: minor (deferred): ps failed at escalation still sets escalated → KILL never retried (safe side)
Task 4: minor (deferred): pane_pid a login shell with claude as only child → no runs followed there (lost coverage)
Task 4: minor (deferred): a process forking a new child every overview counts as progress, never killed
Task 4: complete (commits 10b8040..9b5da6a, review clean after 1 fix round)
Task 5: dispatched rw-impl12 (mechanical, haiku), BASE 9b5da6a
Task 5: green check ok (verify 52+11+42 OK rc=0; busy-check mutation caught)
Task 5: review dispatched rw-rev5 (standard, sonnet) on review-9b5da6a..7a10e3b.diff
Task 6: dispatched rw-impl6 (standard, sonnet), BASE 7a10e3b (parallel with Task 5 review; creates one new file)
Task 5: review rw-rev5: spec ✅ quality ok; minors
Task 5: Ruling: reviewer minor 2 (PsSampleTest sets no TC_STATE temp dir) enters the fix loop — it breaks the plan's Isolation global constraint — cost if wrong: one small extra commit
Task 5: minor (deferred): send_line types text and Enter as two send-keys; a failed Enter leaves a half line and holds later tells
Task 5: minor (deferred): tell_pane tested only with mocks; Task 6 e2e must show the line arrive and be held (carried to rw-impl6)
Task 5: fix round 1/5 dispatched to rw-impl12 (mechanical, haiku), FIX_BASE 7a10e3b
Task 6: green check ok (9 ok, ALL PASS rc=0; FLAT_KILL=99 mutation fails 4)
Task 5: fix round 1/5 green (wiring 3 OK, chain 52/11/42 OK rc=0; tmux shim 0 calls); transient 9 FAILs explained by Task 6's FLAT_KILL mutation on watch.py at the same minute
Task 5: re-review dispatched rw-rev5 (standard, sonnet) on review-b86a6ac..5106cd1.diff
Task 6: review dispatched rw-rev6 (standard, sonnet) on review-7a10e3b..b86a6ac.diff
Task 5: fix round 1/5 (1 addressed, 0 open — wiring test isolated; commits b86a6ac..5106cd1)
Task 5: complete (commits 9b5da6a..5106cd1, review clean after 1 fix round)
Task 6: e2e extended with a tell_pane hold check on real panes (685b949); added to rw-rev6's review
Task 6: minor (deferred): the hold case is a direct tell_pane call, not the Watch's retry after a hold inside the overview chain
Task 7: dispatched rw-impl12 (mechanical, haiku), BASE 685b949
Task 6: review rw-rev6: spec ✅ quality ok (b86a6ac + 685b949)
Task 6: minor (deferred): hold-check input frame and status JSON hand-written (no real Claude frame capture shown); _input_busy has unit tests
Task 6: minor (deferred): SIGKILL escalation not exercised e2e (perl dies on TERM)
Task 6: minor (deferred): leak check passes reading 0 files; REAL_HOME unused; fixed sleep 1 instead of tt_wait
Task 6: complete (commits 7a10e3b..685b949, review clean)
Task 7: green check ok (test_plugin ALL PASS, test_queue_ask_rule ALL PASS, greps; rc=0)
Task 7: review dispatched rw-rev7 (standard, sonnet) on review-685b949..f222671.diff
Task 6: minor (deferred): hold-check frame has no dimmed suggested-prompt text, so paneclass input_has_text dim branch is untested through a real pane
Task 7: review rw-rev7: spec ✅, quality needs fixes (2 Important wording, minors)
Task 7: merge-gate settled: tc-env.zsh TC_STATE_DIR == tc_env.state_dir() (/var/folders/…/T/tmux-ctl-503)
Task 7: minor (deferred): engine path writes its own morning report with no Seen (and no Sleep) section — final review
Task 7: fix round 1/5 dispatched to rw-impl12 (mechanical, haiku), FIX_BASE f222671
Task 7: fix round 1 committed abec500 (green rc=0); re-review pending (next session)
Task 7: re-review dispatched rw-rev7b (mechanical, haiku) on review-f222671..abec500.diff (small fix: 15 lines, 2 files)
Task 7: fix round 1/5 (small, mechanical re-review) (4 addressed, 1 residual — finding 2 placement done as ruled; commits f222671..abec500)
Task 7: Ruling: finding 2 residual (step 5 names the commit before the Metrics/Seen/Sleep sections) is pre-existing step-5 structure the round-1 ruling scoped out; read step 5 as the report's contents, deferred to final review — costs a morning report committed before its later sections, fixed by one follow-up commit
Task 7: minor (deferred): board/watch.py:23 module comment still says "CPU time unchanged on FLAT_KILL overviews"
Task 7: minor (deferred): KILL cutoff (watch.py:323, KILL_GRACE_S*6 = 60 s) not in the docs
Task 7: complete (commits 685b949..abec500, review clean after ruling)
Final: review dispatched rw-final (frontier, fable) on review-ec8b209..abec500.diff
Final: review rw-final: With fixes (0 Critical, 3 Important, 8 Minor)
Final: Ruling: I1 — keep the spec's 2 flat overviews and add a wall-time floor: kill only when flat for >= 120 s (FLAT_KILL_S) — stricter than the spec's letter, matches its intent (progress check before a kill) — costs a hung run living ~2 min longer
Final: Ruling: I2 — under a claude process only shells with the Bash tool's shape (-c … shell-snapshots) are followed as runs — costs a run started some other way under claude going unwatched
Final: Ruling: I3 (tmux-ctl run in <project>-bg unwatched) out of spec scope — doc sentence now, idea filed at queue end — costs hung suites in tests windows staying uncaught
Final: Ruling: M2-M5 deferred to ideas/morning report; M1 + watch.py:23 comment + 60 s KILL cutoff doc taken in the fix wave; M6: engine report has Sleep, lacks only Seen
Final: fix wave dispatched rw-fix (standard, sonnet), FIX_BASE 94a533e
Final: rw-fix asked to edit tools/tests/test_run_watch_e2e.zsh (I1/I2 break its fake run shape) — approved: snapshot-shaped argv, clock past FLAT_KILL_S
Final: fix wave committed 398577b (green: 68 unit OK, e2e/plugin/ask-rule ALL PASS rc=0)
Final: Ruling: e2e sets watch.FLAT_KILL_S = 3 (fake clock cannot drive the floor: a jump reads as a new process under M1) — costs the 120 s value itself being pinned only by unit tests
Final: re-review dispatched rw-rev-final (standard, sonnet) on review-94a533e..398577b.diff
Final: re-review rw-rev-final: all addressed (I1, I2, M1, M8, docs), no new breakage; final review clean
