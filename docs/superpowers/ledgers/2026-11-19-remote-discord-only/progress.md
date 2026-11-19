# SDD ledger — plan: docs/superpowers/plans/2026-11-19-remote-discord-only.md
Preflight: dispatched c-preflight (sonnet) — conflict scan + native tasks
Preflight c-preflight: 14 findings (F1-F14); table in preflight.c-preflight.md. Native tasks: plan T1..T11 = #20..#30.
Ruling: F1 — the runbook's plain-claude window (T10, T11) starts with REMOTE_ASK_GUARD=0 and Task 11's Verify prints which window the guard ran in — spec's peer rule stands, the gate needs a window where dialogs can appear — cost: none.
Ruling: F2 — T9 adds a read-only `dialog <win> rows [--count n]` in dialog.zsh; the board takes both the posted body and --expect from it, never from server.preview — one definition of the compared rows — cost: one small CLI verb.
Ruling: F3 — a raw item is keyed p<pane>-<sha1 of the rows() text>; its Reply goes to `type`, which for a raw item re-checks the rows (no idle-input requirement) and types text+Enter; replies route by record kind (raw/idle → type, parsed → press --text); T9 tests a raw case — spec Error handling keeps a Reply on raw items — cost: a reply typed into an unknown dialog might not be what it expects.
Ruling: F4/F5 — #28 (T9) also blocked by #23 (T4) and #27 (T8); marker path is tc_env.state_dir()/remote — two writers on dialog.zsh otherwise — cost: T9 starts later.
Ruling: F6 — T10 AC 3 greps `scan_prompts|_perm\(|mirror_prompt|"prompt"` in non-test board/*.py and requires 0 — the old check could not fail — cost: none.
Ruling: F7 — the single orchestrator.md line (spec §3 "one line each") also says a reply to a ❓/🔐 post was already typed into the dialog and is not answered again — spec count wins, the promise kept — cost: one longer line.
Ruling: F8 — T1 must capture the plan-approval dialog (Shift+Tab plan mode) and attempt resume; login expiry is not producible and goes the generic unknown/Reply path; T1 reports each missing kind to the lead as a spec gap; user asked on Discord to OK login (and any other uncapturable kind) as a deviation — cost: a real login screen may parse as unknown.
Ruling: F9 — T10 Verify compares the count to 8 with test; T8 verifyCommand and Verify both add `claude plugin validate claude/plugin`; T11 Verify is evidence-only, accepted for a gate — cost: none.
Ruling: F10 — T4 deletes approve.zsh's countdown mask and calls dialog.zsh's one function; the custom-id grammar has one Python definition, and the bridge test asserts the same sample ids — no cross-language sharing possible — cost: none.
Ruling: F11 — in a multi-select, permanent options get no toggle and a `… <label>: answer at the terminal` line; a refused submit edits the message to `⚠️ not pressed: needs the terminal` — spec Q4 confirm step cannot apply inside a multi-select submit — cost: those rows need the terminal.
Ruling: F12 — covered by F2/F3 (raw body = rows()).
Ruling: F13 — T8 implements the transcript-only branch now, remote-marker.sh written and tested but not registered; the UserPromptSubmit probe moves to Task 11 item 1 after the merge (a follow-up registers it if the hook fires with the channel tag) — plan forbids touching a lead before merge; my own transcript was inconclusive — cost: marker refreshed only on a dialog attempt until then.
Ruling: F14 — accept Assumption 8 (teammate-message, task-notification, cross-session prompts keep the marker) as a deliberate deviation from §3's letter — a teammate report would otherwise clear it — cost: a user typing only via cross-session messages stays "remote".
Tasks 1, 5, 8: BASE 5de77af; dispatched c-t1, c-t5, c-t8 (sonnet) in parallel (disjoint files)
Task 5: c-t5 done 4dfc844 (bridge pass 147 fail 0, py 86 OK); review dispatched c-rev5
Ruling: Task 5's one-line edit to tools/discord-bridge/test/outbox.test.js (state defaults) is accepted outside its file list — the defaults it asserts changed with this task — cost: none. Reply event message_id = the dialog message id (Task 7 keys by it) — cost: none.
Task 1: c-t1 done f67f6dd (check.py 7 checked 0 problems rc=0; claude 2.1.328); concerns 1-8 in task-1-report.md.
Ruling: the permanent-row list gains `use auto mode` (plan dialog "Yes, and use auto mode") — spec Q4 treats a switch to auto mode as permanent, whatever the wording — cost: one extra confirm tap on that plan option. T1 fixes its oracle to permanent:true before review; T2 adds the substring to the module list.
Ruling: login expiry uncaptured (user OK pending on Discord); resume rows numbered 1,2 in the oracle is accepted as the parser's contract — cost: a resume press may need arrow keys (T3 checks with the real key probes).
Note for T2/T3: review screen after multi-select/two-question (1 Submit answers / 2 Cancel), digit toggles in multi, trust cursor starts on "No, exit" (Down+Enter), Other = digit, text, Enter — task-1-report.md concerns 3-5.
Task 5: review c-rev5 — spec ✅, quality needs fixes (0C, 1I: grammar test asserts a local regex copy, not DLG_RE; 7M). Fix round 1 sent to c-t5.
Ruling: Task 5 minors M1 (permanent check fails open when i.component missing), M3 (regex accepts t<n>:confirm), M5 (reply disarmed before event write) promoted into fix round 1 — spec Q4 confirm step and reply loss — cost: a slightly larger fix.
Task 5: minor (deferred): rowsOf [] strips every button when i.message.components is missing (bridge.js:363-369).
Task 5: minor (deferred): reply_armed entries never cleared when the dialog is edited/answered at the terminal (bridge.js:354-361,404-408) — Task 7 should disarm.
Task 5: minor (deferred): _check_rows accepts empty row, empty label, style outside 1-5 (discord_feed.py:33-40).
Task 5: minor (deferred): README "this needs MessageContent" ambiguous (README.md:191-192).
Task 1: side effect — trust entry for a deleted scratch path in ~/.claude.json and scratch transcripts under ~/.claude/projects/ (harmless; report to user).
Task 1: fix (ruling use-auto-mode) 5d684a1, check.py 7 checked 0 problems rc=0.
Task 8: c-t8 done 5303c21 (marker 14 ok, guard 22 ok ALL PASS, test_plugin ALL PASS, plugin validate ok w/ warnings; 3 mutations fail); remote-marker.sh unregistered per F13.
Task 5: fix round 1 eadef7f (DLG_RE exported, 6+4 ids, t3 click; pass 148).
Tasks 1+8: review dispatched c-rev18 (one reviewer, per-task verdicts).
Task 5: fix round 1 second commit 564a2d2 (M1/M3/M5; pass 150); re-review queued to c-rev18 after its 1+8 review
Tasks 1+8: review c-rev18 — T1 spec ❌ (1I: Other-row free-text probes inferred, not sent; 3M), T8 spec ❌ quality needs fixes (1C: real teammate rows start "Another Claude session sent a message:\n<teammate-message", no origin → treated as typed, marker deleted; 1I: env probe not from a hook process; 4M). Fix round 1 sent to c-t1 and c-t8.
Ruling: T1 minors 1 (plan option key never sent) and 3 (plan option 3 free text, other:false) promoted into T1 fix round 1 — T2/T3 build on them — cost: one more capture.
Task 1: minor (deferred): check.py label test is a whitespace-normalised substring over any line; n never compared.
Task 8: minor (deferred): state-dir/access-base/prefix-list logic duplicated across remote-marker.sh, remote-ask-guard.sh, tc-env.zsh, tc_env.py.
Task 8: minor (deferred): test_remote_marker.zsh `silent; r1=$?` dead assignment asserts nothing.
Task 8: minor (deferred): worker.md tells a tmux-ctl agent worker to "ask the lead with SendMessage" though it has no team (spec deny text says the same).
Task 5: fix round 1/5 (4 addressed, 0 open — grammar test vs DLG_RE, M1 fail-closed, M3, M5; commits eadef7f, 564a2d2); re-review c-rev18 clean.
Task 5: minor (deferred): duplicate reply event if save() throws after the event write.
Task 5: minor (deferred): misleading confirm text if a message's rows were missing.
Task 5: note for Task 7: the consumer must ignore unknown ab:dlg click ids (t<n>:confirm takes the generic path).
Task 5: complete (commits 4dfc844..564a2d2, review clean)
Task 1: fix round 1 commit 2b6b24b (README key probes for both Other rows, actually sent; check.py 7/0 rc=0); addendum (plan opt 3 other:true, plan key probe) status pending checkpoint
Task 8: fix round 1 commit df5a144 (positive-evidence classification: channel sets, origin.kind human clears; real hook-process env probe); re-review pending
Lead relay 2026-11-19: task list restored from session 78659598; c-t1 dispatched for the T1 addendum (task-1-addendum.md); c-rev8 dispatched for T8 re-review 5303c21..df5a144.
Task 8: fix round 1/5 (2 addressed, 0 open — teammate rows by evidence, real hook-process env probe; commits 5303c21..df5a144); re-review c-rev8 clean.
Task 8: minor (deferred): guard header says "17 of 17" teammate rows; the transcript now has 26.
Task 8: minor (deferred): a typed row with no origin (older Claude) never clears the marker (fails safe; marker lapses after 12 h).
Task 8: complete (commits 5de77af..df5a144, review clean)
Task 8: note for Task 11: the teammate-in-hook env (CLAUDE_PID/$PPID/TMUX_PANE seen by a hook inside a teammate) is unprobed; add it as a Task 11 check item.
Task 1: addendum a195aef (plan opt 3 other:true; digit moves cursor only, typed text + Enter answers, Esc leaves; check.py 7/0 rc=0); re-review c-rev1 dispatched 5d684a1..a195aef.
Task 1: fix round 1/5 (3 addressed, 0 open — Other-row probes sent, plan key sent, plan opt 3 other:true; commits 2b6b24b, a195aef); re-review c-rev1 clean.
Task 1: minor (deferred): README.md:56 still says the plan key was not sent (stale after a195aef).
Task 1: complete (commits 5de77af..a195aef, review clean)
Task 2: BASE a0ccad7; dispatched c-t2 (fable, frontier) with task-2-dispatch.md
Task 1: note for Task 3: multi-select Other row: digit then typing goes nowhere; keys are Down xN onto the row, type, Down to Submit, Enter, then 1 on the review screen; two-question: digit, text, Enter, then 1 on review (README Key probes).
Ruling: login expiry (and resume if uncapturable) goes the generic unknown/Reply path — user accepted on Discord 13:10Z — cost: none.
Task 2: c-t2 stopped (stuck 7h on a lead-routed permission dialog; user chose restart); 9827c09 + uncommitted bin/tmux-ctl help fix; c-t2b dispatched (fable).
Task 2: c-t2b stopped (queued behind c-t2's stale lead-side request); user OK'd allow rules git add/commit in .claude/settings.local.json; c-t2c dispatched (fable).
Task 2: c-t2c done 9827c09+14764a3 (show ALL PASS 82 ok, REAL CHECK PASS 5 panes, run-all rc=0, 13 mutations fail); review c-rev2 dispatched.
Task 2: review c-rev2 — spec ✅, quality approved (0C, 1I: real lead permission prompt with `↑ N more lines` + task list below the footer parses as unknown/all-permanent and its lines key changes with the task list; 4M).
Ruling: Task 2 I1 + M2 enter Task 2 fix round 1 now (new real capture of a lead-style prompt with a task list and a `↑ N more lines` row; `lines` stop at the key-hint footer) — Task 6 keys posts by sha1(lines) and would re-post every tick; c-t2c holds the context — cost: one more capture run before Task 3.
Task 2: minor (deferred → Task 3 brief): `_dlg_screen` drops empty rows and control chars; press --expect and Task 9 rows must read through `_dlg_screen`; usage string gains `press`.
Task 2: minor (deferred): wrapped-question gutter case has no captured fixture (capture it with the fix-round capture if it appears).
Task 2: note for Task 10/11: check_real_dialog_show.zsh is not in run-all/all.zsh; add a gate line.
Task 2: note for Task 4: approve.zsh's own parse needs the same `↑ N more lines` / task-list handling.
Task 2: fix round 1 commit 6ae245a (c-t2c, real lead-prompt capture); re-review pending; lead handoff 2026-11-19-spec-c-task2-fix.md
Lead relay 2026-11-19 (session 2df51895): task list restored; Task 2 fix round 1 bounce check green (verify ALL PASS, check_real PASS, run-all rc=0); c-rev2b dispatched 14764a3..6ae245a.
Ruling: Task 3 press stops at Enter on a multi-select Submit / a two-question answer; the "Review your answers" screen is a new dialog pressed separately (digit 1) — press never sends a key to a screen it has not matched — cost: one extra Discord tap per multi/two-question answer.
Ruling: Task 3 keys for unprobed rows: plan option n = digit+Enter; resume/login = Down x(n-1)+Enter; unknown = digit — README did not probe them — cost: wrong key on those dialogs until Task 11 checks them live.
Task 2: fix round 1/5 (2 addressed, 0 open — tall lead prompt with task list reads permission, lines stop at footer; commits 14764a3..6ae245a); re-review c-rev2b clean.
Task 2: minor (deferred): runend()/addrun() join any row indented to the label column under an option into its label (no real screen shows it; a hint row could reach the permanent-substring match).
Task 2: minor (deferred): wrapped-question gutter case still has no captured fixture (c-rev2 M4).
Task 2: complete (commits a0ccad7..6ae245a, review clean)
Task 3: BASE 6ae245a; dispatching c-t3 (sonnet, standard) with task-3-dispatch.md
Task 3: c-t3 done 67fbdf8 (press ALL PASS 37 ok, show ALL PASS, run-all rc=0, 4 mutations fail); bounce check green.
Ruling: Task 3 trust keys follow the fixture (option 1 "No, exit" under the cursor = Enter; option 2 Yes = Down, Enter), superseding the dispatch's swapped mapping — fixture is the captured truth — cost: none.
Task 3: review c-rev3 dispatched 6ae245a..67fbdf8.
Task 3: minor (deferred): bin/tmux-ctl help prints a hard-coded sed range (now 2,65p); every new header line breaks the help tests.
Task 3: review c-rev3 — spec ❌, quality needs fixes (0C, 3I: trust/resume/login keys ignore the read cursor row; multi-select toggles blindly instead of reaching the picks set; unprobed keys; 4M).
Ruling: Task 3 I1 + I2 enter fix round 1 (navigation relative to the cursor row of the matched read, cursor not found = rc 1 nothing sent; multi --option is the final set: toggle only rows whose checked state differs, duplicates collapse) — Task 7 passes picks as the final set — cost: none.
Ruling: Task 3 I3 (unprobed keys) is not a code fix: Task 11's checklist names plan digits 1/2, resume, login and multi Submit Down-count — cost: a wrong key there until the phone gate.
Task 3: minor (deferred): TC_DIALOG_BEFORE_SEND is eval'ed in production code (as approve does).
Task 3: minor (deferred → Task 7 brief): --text passes newline/ESC through unfiltered; the consumer must reject control chars.
Task 3: minor (deferred): c-rev3 style and test-hygiene nits (see task-3-review.c-rev3.md).
Task 3: fix round 1 commit c6a24c1 (press 50 ok, show ALL PASS, run-all rc=0, M5/M6 fail); re-review c-rev3b dispatched 67fbdf8..c6a24c1.
Ruling: Task 4 criterion 1 (no approve test/fixture change) is checked over Task 4's own range, not main.. — Task 2 legitimately added approve/lead-tasklist-more-lines.txt — cost: none.
Task 3: fix round 1/5 (2 addressed, 0 open — keys from the read cursor row, multi --option is the final set; commits 67fbdf8..c6a24c1); re-review c-rev3b clean.
Task 3: minor (deferred): no-cursor rc 1 is checked before option validation (bad --option on a cursorless screen gives rc 1, not 2; nothing sent).
Task 3: note for Task 11: check live — plan digits 1/2, resume, login, multi Submit Down-count, cursor on Submit / on Chat about this, a pre-checked box (all tested only on sed variants and the byte recorder).
Task 3: complete (commits 6ae245a..c6a24c1, review clean)
Task 4: BASE c6a24c1; dispatching c-t3 (sonnet, standard, reused: holds dialog.zsh context) with task-4-dispatch.md
Task 4: c-t3 done eb4c450 (Verify ok=241 fail=0 same as baseline, run-all rc=0, criterion-1 diff empty, capture-pane 0); bounce check green.
Ruling: Task 4 approve on a tall prompt (command top off screen) refuses with "no expect lines" instead of "no permission prompt" — a partly visible command must not match --expect; Task 7's dialog path handles tall prompts — cost: a tall lead prompt still cannot be answered through approve.
Task 4: review c-rev4 dispatched c6a24c1..eb4c450.
Task 6: BASE eb4c450; dispatched c-t6 (fable, frontier) with task-6-dispatch.md, in parallel with Task 4's review (disjoint files).
Task 4: review c-rev4 — spec ✅, quality approved (0C, 0I, 3M: tall-prompt refusal holds only by screen layout — a synthetic tall screen gave approve a partial P: line; stale comments dialog.zsh:4/:71; approve show has no copy-mode check, pre-existing).
Ruling: Task 4 M1 enters a fix round (approve refuses any tall prompt, tagged in _dlg_parse's tall branch, with a test) together with M2 stale comments — the "no partial command matches --expect" ruling must hold in code, not by layout — cost: one small fix round.
Task 4: minor (deferred): approve show has no copy-mode check (pre-existing).
Task 6: c-t6 done cb05123 (verify OK 105 tests rc=0, board suite 1811 OK rc=0, 11 mutations fail); bounce check green. c-t6 set #25 completed itself; reset to in_progress.
Ruling: Task 6 concern 1 — the free-text row (Type something. / Tell Claude what to change) gets no option button when other is true; Reply covers it — pressing it only focuses the row and would re-post — cost: none.
Ruling: Task 6 concern 4 — a permission prompt with a task list longer than the paneclass 12-row tail must classify waiting (lead's own prompts, Q1); fix in Task 6's fix round, paneclass.py joins Task 6's files — cost: one more file in the task.
Task 6: minor (deferred): a pane answered between build_state and show gets one "(dialog not parsed)" post with a mention, corrected next tick (two-tick raw rule not built).
Task 6: minor (deferred): TC_PROMPT_RE gained "Enter to select|Enter to resume|Tab to amend"; tmux-ctl tell refuses a worker whose last 25 rows quote one.
Task 6: review c-rev6 dispatched eb4c450..cb05123.
Task 6: review c-rev6 — spec ❌, quality needs fixes (0C, 2I: multi-select posts a dead `Chat about this` toggle that dialog.zsh refuses; a permission prompt with 8+ task-list rows still classifies ready; 6M).
Ruling: Task 6 fix round 1 = I1 (multi-select: no toggle for a row press cannot toggle — Chat about this and the free-text row) + I2 (paneclass.py skips a trailing task list before its 12-row tail) + M (a show result without kind is a show error; the 20-button cap and "more options" count run on the filtered list; absence tests carry their # mutation: comment) — cost: none.
Task 6: minor (deferred): scan holds state.lock across every show call; Task 7's consumer can wait on a slow scan.
Task 6: minor (deferred): the PERM test fixture's options are hand-written.
Task 4: fix round 1 commit 5e3781f (U:tall tag, approve refuses tall prompts; Verify ok=247 fail=0, run-all rc=0, mutation fails 3); re-review c-rev4b dispatched cb05123..5e3781f.
Ruling: Task 7 adds tools/discord-bridge/bridge.js + its test to clear reply_armed when an edit removes a dialog's buttons (Task 5 deferred minor) — otherwise a late reply to an answered dialog reaches the consumer — cost: one more file in Task 7.
Ruling: Task 7 press answers a tall permission prompt (dialog path); only approve refuses it — the Discord post shows exactly the rows the terminal shows — cost: the user may approve a command whose top neither view shows.
Task 4: fix round 1/5 (2 addressed, 0 open — approve refuses tall prompts by U:tall tag; stale comments; commit 5e3781f); re-review c-rev4b clean.
Task 4: complete (commits c6a24c1..eb4c450, 5e3781f; review clean)
Task 7: user answer "1" (allow Discord taps on tall permission prompts) relayed by interiors-e2 from its Discord channel 20:28:58Z; matches the existing ruling, nothing changes.
Task 6: fix round 1 commit c32dcf6 (verify 113 OK, board 1820 OK, run-all rc=0, 11 mutations fail); re-review c-rev6b dispatched 5e3781f..c32dcf6.
Task 6: minor (deferred → Task 11 check): the board captures 40 rows per pane; a task list of ~28+ rows pushes the prompt out of the capture and it reads ready.
Task 6: minor (deferred): `Chat about this` matched by exact label (show does not expose the checkbox count).
Task 6: fix round 1/5 (5 addressed, 0 open — buttons only for pressable rows, paneclass skips a trailing task list, show without kind = error, cap on filtered list, mutation comments; commit c32dcf6); re-review c-rev6b clean, 2 new minors.
Ruling: Task 6 re-review minor (paneclass _above_tasklist does not first strip a trailing teammate status divider, so a teammate prompt above a task list reads ready) enters fix round 2 together with the cursor/divider checks of dialog.zsh tasklist() — teammate prompts are the main mirrored case and the fix is small — cost: one more small round.
Task 6: fix round 2 commit 8810552 (teammate divider stripped first, cursor/divider rows refuse a list; verify 116 OK, board 1823 OK; 3 mutations fail).
Ruling: paneclass mirrors dialog.zsh's divider length rule (isdiv: ten rule characters); c-rev6b's four-character probe row is not a divider on either side — one rule in both parsers — cost: none known (real dividers are long).
Task 6: re-review c-rev6c dispatched c32dcf6..8810552.
Task 6: fix round 2/5 (2 addressed, 0 open — teammate divider stripped first, cursor/divider rows refuse a list; commit 8810552); re-review c-rev6c clean.
Task 6: complete (commits eb4c450..cb05123, c32dcf6, 8810552; review clean)
Task 7: BASE 8810552; dispatching c-t7 (sonnet, standard) with task-7-dispatch.md
Task 6: minor (deferred): paneclass's task-list rule is a Python copy of dialog.zsh tasklist(); no test runs the two together.
Task 7: c-t7 done 4ced39d (verify 184 OK, board 1833 OK, bridge 151/151, run-all rc=0, 5 mutations fail); bounce check green.
Task 7: minor (deferred): no message id is stored in the dialog state, so the reply message_id cross-check is inert (reply keyed by key).
Task 7: minor (deferred): the bridge clears reply_armed on any edit of the key, including edits that keep buttons (Reply must be clicked again).
Task 7: review c-rev7 dispatched 8810552..4ced39d.
Task 7: review c-rev7 — spec ✅, quality needs fixes (0C, 1I: the ops-route allowFrom check on reply/click has no stranger test — dropping it keeps tests green; 9M).
Ruling: Task 7 fix round 1 = I1 (stranger click + stranger reply on the ops route, rejected, 0 presses, mutation named) + M1/M2 (one record guard; one discord_dialogs.consume_event used by both consumers, so the allowFrom check cannot drift) + M6 (bridge opEdit saves only when reply_armed changed) — cost: none.
Task 7: minor (deferred → Task 9): a reply to a raw record presses --text with preview rows as --expect and almost always reads "changed"; Task 9 routes raw replies to `type`.
Task 7: minor (deferred): click/_finish dead params; TimeoutExpired edit says "not pressed" though keys may have gone; stale _COVERED comment and ControlsHooks fixture; ops lock held across a press.
Task 7: note for Task 11: one real `press` run through the consumer with its expected output.
Task 7: fix round 1 commit e48531e (one consume_event router with the allowFrom check, stranger tests both routes, _record helper, opEdit save guard; verify 185 OK, board 1834 OK, bridge 151/151; allowFrom mutation on consume_event fails both stranger tests); re-review c-rev7b dispatched 4ced39d..e48531e.
Task 7: fix round 1/5 (4 addressed, 0 open — stranger tests both routes, one consume_event router, _record helper, opEdit save guard; commit e48531e); re-review c-rev7b clean.
Task 7: minor (deferred): no bridge test pins "opEdit does not save when nothing cleared"; a missing blank line before the new test.
Task 7: complete (commits 8810552..4ced39d, e48531e; review clean)
Task 9: BASE e48531e; dispatching c-t7 (sonnet, standard, reused: holds the discord_dialogs context) with task-9-dispatch.md
Ruling: Task 10 runbook gains a precondition (check_real_dialog_show.zsh before restarts) and items 9-12 (user gate, typed-answer wait, keys/screens seen only on recordings, hook inside a teammate); criterion 1 becomes 12 items — the plan's runbook predates Task 9 and the ledgered Task 11 checks — cost: a longer phone session.
Task 10: user OK'd the 12-item runbook ("ok", relayed by interiors-e2 from its Discord channel 21:39:48Z).
Task 9: respawned c-t7 (sonnet, standard) after handoff, BASE e48531e, uncommitted edits intact
Task 9: c-t7 done 32ce1f6 (verify OK/ALL PASS rc 0/0, board 1868 OK, run-all rc=0 0 FAIL, 3 mutations fail); bounce check green
Task 9: review c-rev9 dispatched e48531e..32ce1f6
Task 9: review c-rev9 — spec ✅, quality needs fixes (0C, 1I: a changed-screen reply to an idle item edits "re-sent below" but re-sends nothing and the pane never re-posts; 4M).
Ruling: Task 9 fix round 1 = I1 (idle/raw item on a changed screen re-posts with the current rows, as dialogs do, test) + M1 (test the second-read content check in _dlg_type) + M3 (a failed idle post does not consume the working→ready transition) + M4 (empty --text / --expect refused, tested) — cost: none.
Task 9: minor (deferred): no parity test between dialog.zsh's input_has_text copy and paneclass.input_has_text (blank-row-stripped screen, the 30-row window can differ).
Task 9: note for Task 11: the idle item is tested only against a stubbed runner; one real claude pane going working→ready while remote, its preview rows and a Reply typed into it.
Task 9: fix round 1 commit e829cfd (verify OK/ALL PASS rc 0, wiring 38 OK; mutations fail for each fix); re-review c-rev9b dispatched 32ce1f6..e829cfd.
Task 9: fix round 1/5 (4 addressed, 0 open — idle re-post on a changed screen, second-read test, failed idle post retried, empty type args refused; commit e829cfd); re-review c-rev9b clean.
Task 9: minor (deferred → final review): `rows` prints while the input box holds typed text, so a reply "changed" only by the user's typing re-posts under the key just deleted: an edit and a new dialog op share one key, untested; check how the feed/bridge handle the pair.
Task 9: complete (commits e48531e..32ce1f6, e829cfd; review clean)
Task 10: BASE e829cfd; dispatching c-t10 (haiku, mechanical) with task-10-dispatch.md
Task 10: c-t10 done c7ac726 (runbook 12 items; all.zsh "ALL PASS 170 jobs in 7m25s" + SLOW line, rc 4; ab:perm grep all :0; README unchanged); bounce check green.
Ruling: Task 10 criterion 2 met on all.zsh's verdict line "ALL PASS 170 jobs" — rc 4 is all.zsh's time-budget exit (SLOW: 7m25s over 5 min, load average ~6 with other sessions running), not a failure — cost: a real slowdown on this branch would hide behind load; the final review compares against main.
Task 10: review c-rev10 dispatched e829cfd..c7ac726
Task 10: review c-rev10 — spec ❌ (runbook expectations vs branch), quality needs fixes (0C, 3I: precondition 6 expects remote-marker.sh in /hooks though F13 left it unregistered; item 1 expects a marker after "ping" alone though only the guard's AskUserQuestion branch writes it; items 3/5/6/7 use AskUserQuestion in a plain claude, which the guard denies while any marker is fresh; 3M no change).
Ruling: Task 10 fix round 1 = the runbook follows F13 and the guard as built: precondition 6 checks remote-ask-guard.sh only; item 1 has the lead try AskUserQuestion once to write the marker; a step before item 3 clears the markers; a step before item 10 re-creates one (repeat item 1) — the brief's runbook predates F13 — cost: none (text only).
Task 10: fix round 1 commit 5222867 (runbook only, 12 items rc 0); small fix on a mechanical task: re-review c-rev10b (haiku) dispatched c7ac726..5222867
Task 10: fix round 1/5 (small, mechanical re-review) (3 addressed, 0 open — precondition 6, item 1 marker, marker clear/re-create steps; commit 5222867); re-review c-rev10b clean.
Task 10: note for Task 11: /hooks listing of plugin hooks and the F13 channel-origin premise are checked only on the phone.
Task 10: complete (commits e829cfd..c7ac726, 5222867; review clean)
Final review: c-final (session level) dispatched 550f934..5222867
Final review c-final: ready after fixes (0C, 3I, 7M): I1 run_script .strip() drops the first row's indent, so idle/raw Reply never types and re-posts in a loop (fails closed); I2 both bridges now request MessageContent but INSTALL.md:263/README.md:36 say the ops bot needs no intent (a bot without it exits at login); I3 remote-marker.sh unregistered (F13) leaves the peer deny and idle items mostly inert, and a stale marker outlives the user's return by 12 h.
Ruling: final fix wave = I1 (rows pass unstripped, a real test through run_script) + I2 (INSTALL.md and README.md say every bridge needs Message Content Intent; merge-gate note) + M1 (multi-select Submit with a permanent row edits "⚠️ not pressed: needs the terminal" instead of a silent ignore) + M4 (the "dialog changed" text on a same-key re-post says what happened) — one wave, c-t7 (standard) — cost: none.
Ruling: I3 is not fixed on this branch: registering remote-marker.sh needs the F13 probe (does UserPromptSubmit fire with the channel tag); it becomes Task 11 item 1's probe plus the first follow-up, and the stale-marker 12 h window is recorded for the morning report — cost: until then, idle items and the peer deny fire only after a remote lead tries AskUserQuestion.
Final fix wave: c-t7 7741adc (I1), a53b239 (I2), 0fbef93 (M1, M4); covering 224 OK, press ALL PASS, board 1873 OK; mutations fail; re-review c-final2 dispatched 5222867..0fbef93
Final fix wave: re-review c-final2 clean (I1, I2, M1, M4 addressed; no refusal weakened; 224 OK, dialog show/press + 6 approve suites ALL PASS).
Final review: minor (deferred): run_script picks raw output by a positional argv match on `dialog <pane> rows`.
Final review: complete (550f934..0fbef93)
