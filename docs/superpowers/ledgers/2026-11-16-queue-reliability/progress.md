# SDD ledger — plan: docs/superpowers/plans/2026-11-16-queue-reliability.md
Spec: docs/superpowers/specs/2026-11-10-queue-reliability-design.md (read via plan; planner replayed every task byte-identical to its prototype)
Preflight scan:
| pair/task | produces → consumes | found |
| T1↔T3 bin/tmux-ctl | T1 wait-gone + help N=45 → T3 handoff-mark, N=47 | sequential (T3 blockedBy T1); replay byte-identical: ok |
| T3↔T6 bin/tmux-ctl | T3 relay mark removal → T6 awake (tmux-ctl awake dispatch) | sequential; ok |
| T6↔T7 awake.zsh/tmux-ctl/test_ctl_awake | T6 on --queue/status → T7 sleeps | sequential; ok |
| T2,T4↔T5 hooks.json | scripts → registration with --scoped, not async | T5 blockedBy 2,4; ok |
| T5↔T8 test_plugin.zsh | T5 hook checks → T8 rules checks | sequential; ok |
| T1,T3↔T8 rules | wait-gone/handoff-mark names → orchestrator.md/SKILL.md | T8 after 5,6 (and 1,3 transitively); ok |
| T9 | all → real check + note | last; ok |
| each task self-consistency | tests vs code vs files | replayed RED/GREEN/mutations by planner; ok |
Ruling: run T1, T2, T4 in parallel (disjoint files, no deps) — saves two serial rounds — cost if wrong: one rebase of a teammate's commit.
Ruling: A1–A11 accepted as written — spec silent on each, planner prototyped all — cost if wrong: a follow-up edit to rules or awake.
Task 1: dispatched qr-wait (haiku, BASE c02bf42)
Task 2: dispatched qr-record (haiku, BASE c02bf42)
Task 4: dispatched qr-guard (haiku, BASE c02bf42)
Tasks 1,2,4: green check passed (verify output + exit 0 in each report)
Task 3: dispatched qr-wait (haiku, BASE c63f97a)
Task 5: dispatched qr-guard (haiku, BASE c63f97a)
Ruling: Task 5 (hooks.json) reviewed on its own, not batched — plugin hook registration is shared config — cost if wrong: one extra reviewer seat.
Batch 1-2-4: reviewed together (3 tasks) — all Spec ✅ Approved; 0 crit/0 imp
Ruling: Task 1 minor "list-windows error read as no windows → all gone" is a Global Constraints breach (a tmux error is never read as "no windows") — enters fix loop: on a tmux error keep polling; still erroring at the timeout → `wait-gone: could not kill <name>` per name, exit 3 — cost if wrong: one more line of tmux-ctl behaviour to revert.
Task 1: minor (deferred): no test for the could-not-kill line / default 300 s timeout
Task 2: complete (commits c02bf42..e1fc216, review clean)
Task 2: minor (deferred): test always sets TC_STATE, TMPDIR fallback path unexercised
Task 2: minor (deferred): recipient stored untrimmed after strip() check
Task 4: complete (commits e1fc216..c63f97a, review clean)
Task 4: minor (deferred): loop-cap log write lost silently if state dir absent
Task 4: minor (deferred): empty TMUX_PANE → guard fails open for good; Task 9 must confirm TMUX_PANE in the real hook env
Task 4: minor (deferred): hand-built Stop stdin and AGENT_BOARD_LEAD set by the test itself
Task 5: green check passed; dispatched review qr-review5 (sonnet) on c63f97a..25fc7ad
Task 3: green check passed (5fcbfa6; relay ALL PASS rc 0)
Task 1: fix round 1/5 dispatched to qr-wait (tmux error read as gone)
Task 5: complete (commits c63f97a..25fc7ad, review clean)
Task 5: minor (deferred): RED run's two failing check names not captured (count only)
Task 5: minor (deferred): Stop check matcher/timeout assertions note, no action
Task 1: fix commit e174413 (green: wait_gone ALL PASS rc 0, relay ALL PASS rc 0)
Task 3 review + Task 1 scoped re-review dispatched to qr-review5 (sonnet)
Task 6: dispatched qr-awake (sonnet, standard, BASE e174413)
Task 1: fix round 1/5 (1 addressed, 0 open — tmux error read as gone; commits 5fcbfa6..e174413)
Task 1: minor (deferred): no test for a listing that fails once then recovers
Task 1: complete (commits c02bf42..e174413, review clean after fix round 1)
Task 3: complete (commits 25fc7ad..5fcbfa6, review clean)
Task 3: minor (deferred): traversal test's "nothing written" checks only $TC_STATE/x
Task 3: minor (deferred): relay removes the mark when scheduled, not on success (as spec/A2) — a failing relay.py leaves no guard
Task 3: minor (deferred): stray `tmux-ctl run -h` by implementer; reviewer sees no state change
Task 6: green check passed (7190603; awake ALL PASS rc 0); review dispatched to qr-review5
Task 7: dispatched qr-awake (sonnet at standard-tier effort, reusing Task 6's context, BASE 7190603)
Task 8: dispatched qr-wait (haiku, BASE 7190603)
Ruling: Task 7 (mechanical) runs on qr-awake (sonnet/medium) instead of a fresh haiku — it already holds awake.zsh context from Task 6, saving a cold start; the routing gate allows standard — cost if wrong: a few cents more per turn.
Task 6: review Spec ✅, Needs fixes (0 crit, 1 imp: non-numeric --pid kills the live hold); fix round 1/5 queued to qr-awake after Task 7
Task 6: minor (deferred): on --queue with no tmux server prints no-server before already-on(queue)
Task 6: minor (deferred): "follows the re-pointed pid" check uses a fixed 2.5 s sleep, proves nothing if no tick happened
Task 6: minor (deferred): report lacks pasted output / ok count
Lead note: pre-existing awake bug (dead caffeinate + lid → next on drops lid/watchdogPid) for the final review / morning report
Task 8: green check passed (6e17a9a; plugin ALL PASS rc 0, 72 ok); review dispatched to qr-review5
Task 8: review Spec ✅, Needs fixes (0 crit, 1 imp plan-mandated, 4 minor) — task-8-review.md
Ruling: Task 8 Important (orchestrator.md:306 sends a stalled *subagent* to wait-gone, which only sees ✦ windows and says "all gone" at once) — the A8 rewording overreached: keep wait-gone for teammates, and for a subagent (no ✦ window) keep waiting for its termination notice; fix round 1/5 to an implementer next session, plus a test_plugin check — cost if wrong: one sentence of rules text.
Task 8: out-of-scope note: restart-recovery and pcee-engine specs still say `awake on --lid` (queue holds now use --queue) — for their planners
Task 8: minor (deferred): handoff SKILL.md:17/:68 same gap for a teammate window without ✦ prefix
Task 8: minor (deferred): no rule says what to do after wait-gone exits 3 (killed windows)
Task 8: minor (deferred): Queue mode step 1 "plain hold" fallback ambiguous next to --queue
Task 8: minor (deferred): orchestrator.md:263 vs :345 wording 'the shutdown_requests' vs 'shutdown_requests'
Task 7: green check passed (4d3ce9e; awake ALL PASS rc 0, 161 ok); review not yet dispatched
Session 3 (lead relay): resumed from ledger; Tasks 1-5 complete
Task 6: fix round 1/5 dispatched to qr-awake (sonnet, FIX_BASE 4d3ce9e) — task-6-fix1-brief.md
Task 8: fix round 1/5 dispatched to qr-wait2 (haiku, FIX_BASE 4d3ce9e) — task-8-fix1-brief.md
Task 7: review dispatched to qr-review5 (sonnet) on 6e17a9a..4d3ce9e
Task 7: complete (commits 6e17a9a..4d3ce9e, review clean)
Task 7: minor (deferred): fixture Wake lines use rare `Wake from Deep Idle` text, not the usual `DarkWake to FullWake from Deep Idle`
Task 7: minor (deferred): a sleep starting before <since> and ending after it is left out (as spec)
Task 7: minor (deferred): only the deny-list mutation was run
Task 8: fix commit afa8505 (green: plugin ALL PASS rc 0, 73 ok); small fix, scoped re-review to qr-review5 (sonnet, reused for its Task 8 context instead of a cold haiku)
Task 8: fix round 1/5 (1 addressed, 0 open — stalled-subagent wait-gone gap; commits 4d3ce9e..afa8505)
Task 8: minor (deferred): new test_plugin check greps the whole file, not scoped to the stalled-replacement bullet
Task 8: complete (commits 7190603..afa8505, review clean after fix round 1)
Task 6: fix commit fa725c8 (green: awake ALL PASS rc 0, 164 ok); scoped re-review to qr-review5 (sonnet)
Task 6: fix round 1/5 (2 addressed, 0 open — non-numeric --pid; jq interpolation; commits afa8505..fa725c8)
Task 6: complete (commits e174413..fa725c8, review clean after fix round 1)
Task 9: dispatched qr-awake (sonnet, standard, BASE fa725c8) — task-9-dispatch.md
Ruling: Task 9 also records whether TMUX_PANE reached the live hook and whether a real PostToolUse stdin carries session_id/tool_input (review ⚠️ items, Task 2/4); if the plan's script cannot show it, it goes under "Not verified" and the lead checks it live at the first post-merge shutdown — cost if wrong: the guard fails open (no block), never a false block.
Task 9: green check passed (fb05b3b; REAL CHECK PASS rc 0, 4 sections); review dispatched to qr-review5
Task 9: complete (commits fa725c8..fb05b3b, review clean)
Task 9: minor (deferred): note does not name that lead-stop-guard.sh:24 itself needs TMUX_PANE (fail-open if unset) — one Not-verified bullet
Task 9: minor (deferred): wording; awk count not independent by design; window-snapshot race in the check
Final review: dispatched qr-final (general-purpose, session model) on 9f27f55..fb05b3b — final-review-brief.md
all.zsh on fb05b3b: ALL PASS 126 jobs in 5m55s (rc 4 = SLOW over the 5 min budget, not a failure)
Final review: Ready after fixes (0 crit, 2 imp, 5 minor) — final-review.md
Ruling: final I-2 (hand-built PostToolUse envelope in shutdown-record tests) — no code fix; merge gate = the lead's first post-merge shutdown_request must leave a shutdown-pending file — cost if wrong: the guard never sees pending teammates (fails open, no false block).
Ruling: final M-2..M-5 parked as follow-ups (duplicate-name ids, killed line lists failed kills, queue hold has no owner-death release by spec, _relay_failed never re-invokes the lead) — cost if wrong: misleading text / an idle lead after a failed relay.
Final fix wave: I-1 (wait-gone clears pending names) + M-1 (guard needs non-empty TMUX_PANE) dispatched to qr-awake, FIX_BASE fb05b3b
Final fix wave: commit b7ab9c5 (green: wait_gone, stop_guard, shutdown_record, relay ALL PASS rc 0); scoped re-review to qr-review5
Final fix wave: re-review clean (I-1, M-1 addressed; commits fb05b3b..b7ab9c5)
Ruling: fix-wave residual minors parked (last-name unlink under lock can strand a waiting appender on a dead inode; truncate-then-write not atomic; TMUX_PANE check now gates the handoff-mark block too) — all fail open, and no hook overlaps the lead's own wait-gone in the documented flow — cost if wrong: one missed block of a stop, never a false block.
