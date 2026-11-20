# SDD ledger — plan: docs/superpowers/plans/2026-11-19-teammate-requests-messages-dream.md
Spec: docs/superpowers/specs/2026-11-19-teammate-requests-messages-dream-design.md · base 130ce6f (main daba97e) · native tasks #33-#42 (plan T1-T10)

## Pre-flight scan
| Pair / task | Produces → consumes | Found |
|---|---|---|
| T1→T2,T3 | fixtures team-request.txt / team-waiting.txt + README name format | ok: T2/T3 blocked by T1 |
| T1→T5 | notes: teammate marker, name, lead sid, Probe B event | ok: T5 blocked by T1 |
| T2→T4 | `from` field in show (text + json) | ok: T4 blocked by T2 |
| T3↔T4 | both edit board/discord_dialogs.py + its test | serialized: T4 blocked by T3 |
| T5→T6 | status file path/JSON (Global Constraints) | ok: T6 blocked by T5 |
| T9 | runbook file only; suite over all | ok |
| T7, T8 | disjoint files from all others | parallel-safe with T1 |
| each task self-consistency | T8 RED run by plan author: fails for the stated reason | ok |
Ruling: T3's "client file mapping classes to labels" is left for the implementer to locate by grep — the plan names the search — cost if wrong: a label shown in the wrong place, caught in review.
Ruling: T7 and T8 (mechanical, disjoint, complete code) go in one haiku dispatch, in parallel with T1 (frontier) — files disjoint, no blockedBy link — cost if wrong: a re-run of one small task.
Task 1: dispatched g1-t1 (fable, frontier) base 130ce6f
Task 7+8: dispatched g1-t78 (haiku, mechanical) base 130ce6f
Task 8: report green (1347af0, test_dream 41 OK rc 0) · Task 7: report green (2c6f766, rc 0)
Batch 7-8: review dispatched g1-rev78 (sonnet) package review-130ce6f..2c6f766.diff
Batch 7-8: reviewed together (2 tasks) — T7 spec ✅ Approved, T8 spec ✅ Approved (review-t78.g1-rev78.md)
Task 7: minor (deferred): orchestrator bullet names `tmux-ctl teammates` — confirm Task 6 ships that exact name
Task 8: minor (deferred, final review should fix): _empty_core catches only OSError; invalid UTF-8 core aborts the whole --all run (was a per-project failed) — except (OSError, ValueError)
Task 8: minor (deferred): no test for a non-bullet text line in an otherwise empty core
Task 7: complete (commits 130ce6f..2c6f766, review clean)
Task 8: complete (commits 130ce6f..1347af0, review clean)
Ruling: T1 fixtures turn test_ctl_dialog_show.zsh (fixture count 7→9, no oracles) and fixtures/dialogs/check.py red until T2/T3 — accepted; T2 adds the team-request oracle and count, T3 exempts team-waiting.txt (no dialog) in the show loop and check.py — cost if wrong: branch red between T1 and T3, never merged red (T9 runs all.zsh).
Task 1: report green (e08b92f, verify rc 0) DONE_WITH_CONCERNS — check.py rc 1 + show loop red (ruled above); Probe B: UserPromptSubmit does not fire in the lead for teammate messages
Ruling: T2 owns both new fixtures in the show loop and check.py (oracle for team-request; team-waiting exempt as a non-dialog), T3 does not touch T2's files — so T2/T3 run in parallel on disjoint files — cost if wrong: T3's waiting-on-lead tests miss a check.py case, caught at T9.
Ruling: T5 lead reminder fires on the lead's Stop (once per status ts: decision block with the reminder as reason) and on PostToolUse (additionalContext, <=1/min); "last message from <name>" = timestamp of the last `<teammate-message teammate_id="<name>"` entry in the lead transcript (transcript_path), replacing the hook-touched .seen file — spec's UserPromptSubmit/.seen design has no event and no sender field (Probe B) — cost if wrong: a Stop block loops or a reminder never fires; tested both ways.
Ruling: teammate marker = `ps -o args= -p "$CLAUDE_PID"` holds --agent-name <name> and --parent-session-id <lead sid> (Probe A); lead = AGENT_BOARD_LEAD=1 without --agent-name; worker = neither; hooks never log the args line (holds --lead-verify-key) — cost if wrong: a hook silent where it should act, caught by the gate.
Task 1: review dispatched g1-rev1 (sonnet) package review-2c6f766..e08b92f.diff
Ruling: spec C gate item 3 failed live — Claude Code 2.1.329 draws a session-name rule `──…── <session name> ─` below the dialog footer, and `dialog show` reports none (capture probe-fruit-2.1.329.txt) — g1-t2 adds it to Task 2 (same file dialog.zsh): fixture + accept that trailing rule — cost if wrong: dialog posts stay unparsed on 2.1.329 until group 1 merges.
Task 1: review g1-rev1 spec ✅ Approved, 2 Important (Probe A ps marker read outside a hook; lead negative case has no raw line) → fix round 1 to fresh g1-t1b (sonnet; g1-t1 shut down)
Task 1: minor (deferred): README.md:33 blank line splits the Files table; sed left odd wrap points; fixtures 49 rows vs 50; raw hook dump gone
Task 5: report green (bf2ba79, test_teammate_hooks 37 ok ALL PASS rc 0, 6 mutations) — ignores idle_notification teammate-messages
Task 5: review dispatched g1-rev5 (sonnet) package review-e08b92f..bf2ba79.diff; g1-t5 shut down (team cap)
Task 5: review g1-rev5 spec ✅ Changes needed, 2 Important (I1 reminder fires after every normal report: the done message precedes Stop by ~1 s; I2 PostToolUse parses the whole transcript + ps on every tool call ~110 ms, rate file only on emit; plain Stop pays ~110 ms)
Ruling: I1 — a teammate-message from <name> whose transcript time is >= status ts - 30 s counts as "messaged since the stop" (grace window); the reminder targets a stop whose report has not reached the lead — cost if wrong: a stop with a message sent >30 s before it still reminds once.
Task 5: minor (deferred): idle filter skips whole transcript lines; Task 10's gate should cover an in-process teammate
Task 5: fix round 1 → fresh g1-t5b (sonnet; g1-t5 shut down)
Task 1: fix round 1 committed by g1-t1b (report § Fix round 1); re-review pending (team cap); g1-t1b shut down
Live bug (spec C): one permission prompt in ✦ g1-t1b posted 15× with a new key every ~12 s (00:17:19-00:19:08Z), user taps 'already answered' — g1-dbg (sonnet, read-only) finding root cause
Task 1: fix round 1 commit 591f57d (in-hook ps lines teammate + lead negative case; README nit) — re-review pending
Task 2: report green (320dd0e: show/press ALL PASS, check.py 9/0, test_discord_dialogs 99 OK, approve ALL PASS); 2.1.329 session-rule extra scope still in progress
Task 2: extra scope committed 3ca76ae (2.1.329 session-name rule) — review of 130ce6f..3ca76ae Task 2 range pending
Task 3: committed dd6d27e — report task-3-report.md, bounce check + review pending
Task 5: fix round 1 committed 8546f97 (g1-t5b) — bounce check + scoped re-review pending (findings I1+I2 verbatim in dispatch-t5b.md)
Live bug root cause (g1-dbg, debug-repost.g1-dbg.md): the auto-mode countdown row "⚠ Claude Code will automatically block this request in M:SS, …" wraps at 80 cols, so _dlg_parse emit (dialog.zsh:64) masks M:SS only on unwrapped rows (regex anchored on "unattended session$") → key changes every tick; nobody answered, prompt timed out at 120 s. Fix: drop the end anchor; test = two wrapped screens 1:47 / 1:35 give one key.
Ruling: the countdown-row fix goes to the dialog.zsh owner as an extra commit in group 1 (Task 2 area) — cost if wrong: phone taps on auto-mode prompts in narrow ✦ panes keep missing until merged.
Lead relay (session 24ab84a0): bounce checks green for T1 fix, T2 (+3ca76ae), T3, T5 fix
Task 1: re-review dispatched g1-rr1 (sonnet) package review-bf2ba79..591f57d.diff
Task 2: review dispatched g1-rev2 (sonnet) packages review-591f57d..320dd0e.diff + review-dd6d27e..3ca76ae.diff
Task 3: review dispatched g1-rev3 (sonnet) package review-320dd0e..dd6d27e.diff
Task 5: re-review dispatched g1-rr5 (sonnet) package review-3ca76ae..8546f97.diff
Task 1: fix round 1/5 (2 addressed, 0 open — in-hook ps line, lead negative raw line; commits bf2ba79..591f57d) — rereview-t1.g1-rr1.md
Task 1: complete (commits 2c6f766..591f57d, review clean)
Task 5: fix round 1/5 (2 addressed, 0 open — 30 s grace, cheap early exits; commits 3ca76ae..8546f97) — rereview-t5.g1-rr5.md
Task 5: minor (deferred): a Stop input holding both "hook_event_name" and "PostToolUse" strings is rate-limited like PostToolUse
Task 5: minor (deferred): a malformed status JSON stays due forever (perf only)
Task 5: minor (deferred): "second check within a minute is silent" test passes without the .last-remind write
Task 5: complete (commits e08b92f..8546f97, review clean)
Task 3: review g1-rev3 spec ✅ Approved, 0 Important (review-t3.g1-rev3.md)
Task 3: minor (deferred): paneclass.py:187 scans the last 20 rows, so a stale waiting box above a real dialog hides the dialog (no post); untested
Task 3: minor (deferred): split-pane mode pill says "(claude window)" for a pane in that same window
Task 3: minor (deferred): no test of build_state's label_waiting_on_lead call
Task 3: complete (commits 320dd0e..dd6d27e, review clean)
Task 6: dispatched g1-t6 (sonnet, standard) base 8546f97
Task 2: review g1-rev2 spec ✅ Changes needed, 1 Important (I1 session-rule regex takes only an ASCII last word: dialog.zsh:250) (review-t2.g1-rev2.md)
Task 2: minor (deferred): M1 tall team request (mr) has no from — Task 4 consumer must say so; M2 team-queued is a sed variant; M3 same_as python strip heavy; M4 nested-quote eval; M5 check.py accepts from in any oracle
Ruling: Task 2 fix round 1 (I1 + Minor 6 negative rows) and the countdown-wrap fix go to one fresh implementer g1-t2b (sonnet) as two commits — same file dialog.zsh, g1-t2 gone — cost if wrong: one larger re-review.
Task 2: fix round 1 → fresh g1-t2b (sonnet), FIX_BASE 8546f97
Task 6: report green (8b301e8, test_ctl_teammates 8 ok ALL PASS rc 0) — busy/idle via pane_idle (what list uses)
Ruling: T6 busy/idle = tmux-ctl's pane_idle, the helper `list` uses; the brief's "board/paneclass.py via the existing helper tmux-ctl uses for list" names that helper, and list does not import paneclass — cost if wrong: idle/busy disagrees with the board's pill for an edge pane.
Task 6: review dispatched g1-rev6 (sonnet) package review-8546f97..8b301e8.diff
Task 6: review g1-rev6 spec ✅ Approved, 0 Important (review-t6.g1-rev6.md)
Task 6: minor (deferred): no test of unset-TC_STATE branch; none with a real-hook status file; none with a same-named ✦ window in a second session; window-only name with a space breaks the 5-field row; leading-dot names skipped
Task 6: complete (commits 8546f97..8b301e8, review clean)
Ruling: T4 runs in parallel with g1-t2b — files disjoint (discord_dialogs.py vs dialog.zsh); T4's dependency on T2 is the `from` field, already in 320dd0e — cost if wrong: a fixture-count assertion goes red mid-run, reported not edited.
Ruling: T4 queue — once a name is confirmed gone (two scans >=30 s apart) later requests from that name in the same lead pane and tick are pressed without a fresh 30 s wait (re-show after each press, cap 10) — the spec's "three stale requests get three presses in one tick" needs it — cost if wrong: a newly-queued request from a gone teammate is denied without its own 30 s.
Ruling: a tall teammate request (no `from`, T2 Minor 1) is an ordinary post, never stale-Denied — cost if wrong: a gone teammate's tall request waits for the 120 s timeout.
Task 4: dispatched g1-t4 (sonnet, standard) base 8b301e8
Task 4: report green (0f07bf4, test_discord_dialogs 111 OK rc 0, test_discord* 434 OK; 4 mutations fail) DONE_WITH_CONCERNS
Ruling: T4 header "wants to …" is the request text placeholder (like the existing `· <window>: <question>`), not a literal ellipsis — sent back to g1-t4 before review with a feed-kind rendering check — cost if wrong: one extra commit.
Task 4: follow-up 125aae7 (header carries the question; stale_deny feed line tested via ops_for_events) — 111 OK rc 0
Task 4: review dispatched g1-rev4 (sonnet) package review-f2a9f17..125aae7.diff
Task 4: review g1-rev4 spec ❌ Changes needed, 1 Important (I1 gone record survives an answered request → next request from that name pressed on its first scan; :277-278) (review-t4.g1-rev4.md)
Task 4: minor (deferred): M1 the request after a stale press that is live/unconfirmed or past the cap is posted one tick late; M2 ❓ header with from says "wants to"; M3 up to 10 sequential show calls per tick
Task 4: fix round 1 → resume g1-t4, FIX_BASE 125aae7
Task 2: fix round 1 committed f2a9f17 (any session name; 5 names, 3 negative rows) + countdown wrap 617eb0f (synthetic wrapped fixture) — show/press ALL PASS rc 0, check.py 10/0, approve ALL PASS, test_discord_dialogs 111 OK
Task 2: re-review (f2a9f17) + countdown review (617eb0f) dispatched g1-rr2 (sonnet)
Gate note for T9/T10: real 80-column auto-mode countdown capture (617eb0f's fixture is synthetic)
Task 4: fix round 1 committed 78f9ead (prune gone keys not in seen; 2 tests RED→green, 113 OK rc 0) — re-review g1-rr4 (sonnet)
Task 4: fix round 1/5 (1 addressed, 0 open — gone record pruned when not seen; commits 617eb0f..78f9ead) — rereview-t4.g1-rr4.md
Task 4: minor (deferred): a transient show ERROR / flap out of waiting prunes the record and restarts the 30 s clock (delays a deny, never a false one)
Task 4: complete (commits f2a9f17..78f9ead, review clean)
Task 2: fix round 1/5 (1 addressed + Minor 6, 0 open — any session name, negative rows; commits 8b301e8..f2a9f17) — rereview-t2.g1-rr2.md
Task 2: countdown wrap 617eb0f reviewed g1-rr2 spec ✅ Approved (mask anchored at row start; break point irrelevant, probed 4 variants)
Task 2: minor (deferred): negative test comment names a nonexistent "footer test" mutation; generic() drops any ──── … ─ last row from lines (harmless); wrapped countdown test pins neither kind nor options
Task 2: complete (commits 591f57d..617eb0f, review clean)
Task 9: dispatched g1-t9 (haiku, mechanical) base 78f9ead
Task 9: all.zsh FAIL 9/172 rc 1 — all help-range tests; root cause (lead): T6 added 2 header lines but the help printer bin/tmux-ctl:692 stays `sed -n '2,68p'` (block now ends at 70)
Task 6: fix round 1/5 (help range 2,68→2,70) → g1-t9 (haiku), re-review after
Task 6: fix committed d2e3869 (help range 2,70p); the 9 suites alone rc 0
Task 9: report green (6a3c4de runbook; all.zsh ALL PASS 172 jobs in 7m27s, rc 4 = time budget only)
Task 6 fix + Task 9: review dispatched g1-rev9 (sonnet) package review-78f9ead..6a3c4de.diff
Task 6: fix round 1/5 (1 addressed, 0 open — help range 2,70p; commits 78f9ead..d2e3869) — review-t9.g1-rev9.md
Task 9: review g1-rev9 spec ✅ Approved, 0 Important
Task 9: minor (deferred): G1 "denied by project settings" precondition not derived from the repo; G3 omits the 60 s reminder limit; G5 saves the fixture under /tmp
Task 9: complete (commits d2e3869..6a3c4de, review clean)
Final review: dispatched g1-final (session level) package daba97e..6a3c4de
Final review g1-final: NEEDS FIXES — C1 stale Deny passes `--option No`, press takes only a number (never presses; stub pinned the wrong argv; plan:77,117); I1 teammate-remind reads all input byte by byte before the lead check; M1 _empty_core OSError only; M2 runbook G1 needs an ask rule; M3 non-[A-Za-z0-9_-] names never get a ✦ window → live requests stale-denied; M4 subagent prompt header unverified; M5 T6 ruling contradicts spec §3 (review-final.g1-final.md)
Ruling: fix wave = C1 + M3 guard, I1 + event regex, M1, docs (M2, gate items for M4 and the T3 20-row minor, spec §3 revised to the T5/30 s/T6 rulings) — one fresh implementer g1-fix (sonnet) — cost if wrong: one more re-review.
Ruling: M5 left — teammates prints busy/idle from pane_idle; waiting-on-lead not shown yet; spec §3 revised to say so — cost if wrong: a waiting teammate reads busy in `tmux-ctl teammates`.
Final fix: dispatched g1-fix (sonnet) FIX_BASE 6a3c4de
Final fix: committed 8b596c0 (C1+M3), bc4c752 (I1+regex), 8e4ca86 (M1), 86ebde8 (docs) — all.zsh ALL PASS 172 jobs in 7m30s rc 4 (time budget), grep -c FAIL 0
Final fix: scoped re-review dispatched g1-rrf (sonnet) package review-6a3c4de..86ebde8.diff
Final fix re-review g1-rrf: C1, I1, M1-M4, T5 minor, spec §3 ADDRESSED; new Important: 1 MB `< 0.15 s` timing test flakes under load (0.22-0.27 s measured) (rereview-final.g1-rrf.md)
Final: minor (deferred): no unit test for the "No, and tell Claude…" label or the prose-PostToolUse case
Ruling: residual flaky timing test → smallest change, endless-stdin rc check instead of a time bound, + spec §2 `--option No` text, by g1-fix; verified by the lead running the hook suite, no further review wave — cost if wrong: an unreviewed test-only commit.
Final: residual d1efc63 (endless-stdin test; spec §2) — lead ran test_teammate_hooks: ALL PASS rc 0
Final review: clean after one fix wave (6a3c4de..d1efc63)
