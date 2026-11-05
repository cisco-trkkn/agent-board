# SDD ledger — plan: docs/superpowers/plans/2026-11-05-mod-agent-status.md
Preflight table:
| T1×T2 | agent-status.js, hooks.json: T1 spike body, T2 replaces it; T2 consumes T1 notes (API facts) | ok, T2 blocked by T1 |
| T2×T4 | T4 runs T2's mod for real | ok, T4 blocked by T2 |
| T3×T4 | T4 reads /api/state via T3's mod_states | ok, T4 blocked by T3 |
| T1×T3, T2×T3 | no shared files (plugin vs board) | parallel-safe |
| T1 self | Verify counts 5 rows '| (' matches AC contexts a-e | ok |
| T2 self | AC transitions = Global Constraints list | ok |
| T3 self | 7 tests = 7 test methods in Step 1; code ran once in scratch copy GREEN (31 tests OK) | ok |
| T4 self | Verify >=4 sections matches AC | ok |
Ruling: state dir follows tc_env.state_dir() ($TMPDIR/tmux-ctl-<uid> fallback), not spec's ~/.local/state/agent-board — spec also says "as tc_env.state_dir() resolves it" and board must read where mod writes — costs a moved dir if user meant XDG path
T1: dispatch spike (sonnet) base ccf6b0c; T3: dispatch board (haiku) base ccf6b0c (parallel, disjoint files)
T3: DONE 0fbc0e7 green; review dispatched (rev3, sonnet)
T3: minor (deferred): M1 newest-wins test depends on listdir order
T3: minor (deferred): M2 pane ids per tmux server — another server's status file could colour this board's %N (record socket in file?)
T3: minor (deferred): M3 no test for future-dated (-5) / non-numeric updatedAt
T3: minor (deferred): M4 pane_status lists dir per call (relay loop cost unchecked); fixtures hand-written, not from real mod
Task 3: complete (commits ccf6b0c..0fbc0e7, review clean)
T1: DONE_WITH_CONCERNS 0420ce9 green (5 rows); mods load in a-e
Ruling: permission transition = needs-you when tool.check resolves ask; busy when that tool.call's await next(e) returns; ready at turn.complete (spec said busy at tool.call start) — spike probe shows tool.call enters ~150ms before tool.check and next() returns after the answer — costs a wrong state window if the probe misread the order
Ruling: AskUserQuestion = needs-you from tool.call start (and its tool.check ask) until next() returns, then busy — same probe — costs nothing extra if wrong (ask path covers it)
Ruling: tmp+rename via $.process.run(['mv',…]); session.end delete via $.process.run(['rm','-f',…]); $.fs.write makes parents — $.fs has no rename/delete — costs a subprocess per write (heartbeat 15s) if a cheaper way exists
Ruling: modules path "../mods/agent-status.js" (relative to hooks/hooks.json), not the plan's "./mods/…"; test_plugin check matches that — spike probe — none
Ruling: gitignore claude/plugin/tsconfig.json and claude/plugin/.claude-plugin/types/ in Task 2 — written by plugin loading — none
T1: review dispatched (rev1, sonnet); T2: dispatch modimpl (sonnet) base 0420ce9
T1: review spec ✅ Approved, 2 Important (notes: in-process teammate agentId; unsourced 5s test limit), 5 minor
T1: minor (deferred): spike probe handlers copy-pasted (validator-forced; replaced by T2); dead e.tool suffix on turn/session events; rm -f untested; live-dir cleanup disclosed; one indented code block
Ruling: mod skips every event carrying e.agentId (in-process teammate events reach the lead's mod per reference.md:66) — status file describes the session's main agent only — costs in-process teammates not appearing on the board (they never had their own pane anyway)
T1: fix round 1/5 dispatched to spike (I1, I2), base 0420ce9
T1: fix round 1/5 (2 addressed, 0 open; commits 0420ce9..f3c2eba)
Task 1: complete (commits 0fbc0e7..f3c2eba, review clean)
T2: DONE_WITH_CONCERNS 326600b; claude plugin test claude/plugin 15/15 rc=0; test_plugin ALL PASS
Ruling: T2/T4 verifyCommand is `claude plugin test claude/plugin; echo rc=$?` (plan said claude/plugin/mods, which has no hooks.json and exits 1) — the tool takes the plugin dir — none
T2: bounced 1/2 (agentId-skip ruling not implemented)
T2: bounce fix c9adcf7 green (lead ran claude plugin test claude/plugin: 16/16 rc=0); review dispatched to rev1
T2: review spec ❌, 2 Important (session.end on /clear|/resume|/branch kills the mod; write block x7), 5 minor
T2: minor (deferred): tool_use_id pairing branch untested; empty-TC_STATE vs tc_env.state_dir() unchecked; unused `asked` in test (fixed in round 1)
T4 carry: check $.clock.now() unit (since vs date +%s); real rm -f, $.clock.every, mv via $.process.run; stale file after 1.5s SessionEnd budget expires by 45s age on the board
T2: fix round 1/5 dispatched (I1, I2), base c9adcf7
T2: fix round 1 commit 1308321, 20/20 rc=0; re-review to rev1
T2: fix round 1/5 (2 addressed, 1 new open — flush awaits session.id before enqueue, no ended re-check: stale file after session.end; commits c9adcf7..1308321)
T2: minor (deferred): dead `branch` reason (docs: /branch reports resume)
T2: fix round 2/5 dispatched (ended re-check + rm-in-queue + id-change test + notes update), base 1308321
T2: fix round 2 commit 45232c8, 22/22 rc=0; re-review to rev1
T2: fix round 2/5 (1 addressed + 2 minors addressed, 0 open; commits 1308321..45232c8)
T2: minor (deferred): notes:68 finding 5 still says "no helpers taking $"; in-job ended check untested; flush lost `if (!st.file) return` (fs.write(null) after clear when session.id throws, swallowed)
Task 2: complete (commits f3c2eba..45232c8, review clean)
T4: dispatch e2e (sonnet) base 45232c8
Session resumed from handoff 2026-11-05-queue-run-spec2-e2e; T4: dispatched e2e (sonnet) base 45232c8
T4: DONE_WITH_CONCERNS 12c7a67 green (grep -c 6 rc=0); all transitions captured; cleanup evidenced
T4: BUG (Task 2 code): auto mode — tool.check next() resolves ask before the auto classifier runs (docs events.md:195), so an auto-approved Bash call holds needs-you for the whole tool run
Ruling: auto-mode needs-you bug is load-bearing (leads run in auto mode) and goes into the final-review fix wave as a known Important finding, fixed by a frontier fix agent that probes a real signal (candidates: classic.PermissionRequest/Notification, SessionMode render, ToolProgress) and re-runs the e2e auto-mode case — the mod would mark every auto lead needs-you on each Bash call — costs one more frontier dispatch if a cheaper fix existed
T4: minor (deferred): after /clear no status file until next heartbeat (~15-25 s); board falls back to pane text
T4: review spec ❌, 4 Important (no raw file/api captures; not reproducible; clock claim unbacked; cleanup unevidenced), 3 minor
T4: minor (deferred): table rows not chronological; /clear id truncated, exit shows post-state only; title version 2.1.318 unevidenced
Ruling: order = reopen Task 2 for the auto-mode fix (frontier, real probe) first, then Task 4 fix round 1 as one fresh re-run against the fixed mod that recaptures raw output (also a default-mode session with a real permission dialog), then rev4 re-review, then final review — a re-run before the fix would be thrown away — costs one extra review cycle if the final review forces another re-run
T2: reopened — fix round 3/5 (auto-mode needs-you) dispatched fresh (frontier, fable) base 12c7a67
T2: fix round 3 DONE_WITH_CONCERNS 1345f3c green (claude plugin test 31/31 rc=0; test_plugin ALL PASS)
Ruling: needs-you comes from classic.PermissionRequest (probed: fires only when a dialog shows, ~40 ms after tool.check ask; never in auto mode), paired to the tool.call by tool+input, busy when that tool.call's next() returns; replaces the earlier "needs-you when tool.check resolves ask" ruling — the probe showed tool.check ask precedes the auto classifier — costs guarded (Team/Enterprise) sessions relying on the settings.defaultMode fallback, which is wrong when the runtime mode differs
Ruling: guarded-session fallback (no classic.SessionStart/PreToolUse seen → ask is needs-you unless settings defaultMode is auto/bypassPermissions/dontAsk) accepted unprobed — no guarded account available overnight — costs a wrong needs-you or busy in guarded sessions whose runtime mode differs from settings
T2: minor (deferred): auto-classifier denials unprobed (PermissionRequest may fire on auto-deny → brief needs-you flash); stale st.asks entry if a tool.call never returns
T2: fix round 3/5 (5 addressed, 0 open; commits 12c7a67..1345f3c)
T2: minor (deferred): stale st.asks if tool.call next() rejects/never returns (clear asks at turn.start/complete, cleanup in finally); askFor oldest-same-tool fallback can flip a visible dialog busy early; guarded test calls tool.check before tool.call; some notes facts prose-only (raw probe log not kept); flush-guard test green before guard
Task 2: complete again (commits 12c7a67..1345f3c, review clean)
T4: fix round 1/5 dispatched fresh (e2e2, sonnet) — re-run against 1345f3c with raw captures, base 1345f3c
T4: fix round 1 DONE f152e85 green (grep -c 6 rc=0); re-review to rev4 over 12c7a67..f152e85 (doc diff only)
T4: minor (deferred): board /api/state showed waiting 1 s after the file said busy (state cache), next snapshot agreed
T4: fix round 1/5 (3 addressed, 1 open — snap's /api/state reader is a placeholder at e2e-agent-status.md:29; commits 1345f3c..f152e85)
T4: minor (deferred): clock gap bound says 0-12 s but 14 s shown; ps grep doesn't match claude lines; /clear block pastes 'bad option' errors; live-after 0 stated as prose
T4: fix round 2/5 dispatched (resume e2e2), base f152e85
T4: fix round 2 DONE 4110df3 green (grep -c 6 rc=0); re-review to rev4
T4: fix round 2/5 (1 addressed, 0 open; commits f152e85..4110df3)
T4: minor (deferred): '<-' annotations inside pasted 'bad option' output lines (no longer verbatim)
Task 4: complete (commits 45232c8..4110df3, review clean)
Final: dispatch finalrev (session level) over 5a90ba9..4110df3
Final: review WITH FIXES — I1 board lets fresh busy file hide dialogs the mod can't see (subagent dialog, sandbox network prompt) — regression vs WAITING_RE; M1 stale st.asks; M2 classic.PermissionRequest handler lacks agent_id skip; M3 (leave) flush across /clear; M4 notes overclaim "never fires in auto mode"; M5 e2e Session A auto-mode precondition unstated
Ruling: fix wave = I1, M1, M2, M4, M5 in one dispatch (standard, sonnet); M3 left as is — reviewer triaged it fine-to-leave — costs one stale heartbeat write after /clear
Final: fix wave dispatched (wavefix, sonnet) base 4110df3
Final: fix wave DONE e0bb6e9..0d30469 green (plugin 33/33 rc=0; test_paneclass 32 OK; test_plugin ALL PASS); scoped re-review to finalrev
Final: fix wave re-review — 5 addressed, 0 open; 1 new minor; Ready to merge: Yes
Final: parked — I1 guard skips the spinner check (prompt-like prose in the last 12 rows during a live turn reads waiting) — Ruling: left for a follow-up; false alarm only, never hides a blocked agent; one-line fix `not spinner_live(rows[-30:])` noted — costs occasional false needs-you on the board
Correction: the auto-mode PermissionRequest ruling rests on one probed call; hooks.md also fires it on the auto-deny of a call that cannot prompt (handled by the agent_id skip) — context Map line reworded
Merge gate (user, after merge): restart the dev lead; its status file appears under $TMPDIR/tmux-ctl-$(id -u)/agent-status/ and paneclass.mod_states() shows its pane
