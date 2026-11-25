# SDD ledger — plan: docs/superpowers/plans/2026-11-21-supervised-improvement-loop.md
Spec: docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md
Rebased onto main c273b84 (head 5abaf28).
Preflight: dispatched preflight (standard, sonnet), output preflight.preflight.md
Task 1: dispatched impl1 (standard, sonnet), BASE 5abaf28
Stale check: stale (13 paths, incl. engine-hold.sh, hold.js, core.js, cli.js, db.js, steps.js; part 3 merged). Refresh waits for Task 1 note + preflight, then one refresh agent (Opus).
Task 1: report DONE_WITH_CONCERNS, commit 38ba133; verify prints 12 / 0 (rc 1 is grep -c on zero matches). Ruling: verify green on its printed output 12/0, rc 1 inherent to grep -c — the plan's Verify names the output, not the rc — cost if wrong: none, the note is read by eye in review.
Task 1: review dispatched rev1 (standard, sonnet) on review-5abaf28..38ba133.diff
Preflight: complete (preflight.preflight.md: 10 conflicts, 5 gaps, 6 (c), 12 (d)). Rulings: preflight-rulings.md (default accept all proposals; A12, A16, C6, A18, A11 and the stale refresh ruled explicitly).
Ruling: preflight proposals accepted as written by default — the scan cites main file:line for each — cost if wrong: a refresh patch that a task review catches.
Ruling: C6 protected set grows by improve.js, hold.js x2, engine-hold.sh x2, improve-rank.md — spec §6 protects the loop's own code and the hold enforces the set — cost if wrong: user must promote later hold.js changes.
Ruling: A16 improve merge = one ff-only commit with Proposal and Engine-Step trailers — spec §5 one commit — cost if wrong: one function.
Ruling: A18 tick verdict shows in the next report and improve list; T11 adds an Improve section — tick runs after the report — cost if wrong: verdict one report late.
Ruling: A12 compare_to_baseline for guardrail breach and O1, compare_halves for trials — spec judges O1 against baseline — cost if wrong: one function to drop.
Refresh: dispatched refresh (frontier pin opus, Reason: refresh), task #7; routing gate needed task 6 set pending for the dispatch, restored after
Task 1: minor (deferred): rebuild.js line cites off by one (tablesOf :9, PRAGMA :11)
Task 1: ⚠ Tasks 5/10 file needs resolved by lead: preflight A10/A16 and the refresh cover them (ledger.js read in A10)
Task 1: complete (commits 5abaf28..38ba133, review clean)
Refresh: complete, commit 93214ab (registry validate rc 0); plan now based on c273b84, preflight rulings applied (report refresh-report.md)
Task 2: dispatched impl2 (mechanical, haiku), BASE 93214ab
Task 2: report DONE_WITH_CONCERNS, commit 5eafa5c; verify 8 tests OK rc 0 (green check passed)
Task 2: review dispatched rev2 (standard, sonnet) on review-93214ab..5eafa5c.diff (batch of 1: Task 3 is standard)
Task 2: review rev2: spec ❌, 2 Important (frontmatter below line 1 / new-file frontmatter read as prose; fence state not tracked against the target file)
Ruling: Task 2 prose_only/derive take an optional target_text; with it, fence and leading-frontmatter state at each hunk start come from the target file; without it, a hunk not starting at line 1 is never prose-only (class rises to high) — Global Constraints say "tracked over the hunk context and the target file", and a false low is the unsafe direction — cost if wrong: some real prose patches without target text get high and need the user's promote.
Task 2: minor (deferred): bin/tmux-ctl#improve protects nothing until an improve) case exists; range end = first ;;; ~~~ fences not recognised; missing tests (blank context, removed ---, fence across hunks, indented code)
Task 2: fix round 1/5 commit fac4fe2 (12 tests OK rc 0); re-review sent to rev2 on review-5eafa5c..fac4fe2.diff (not small: standard)
Task 2: fix round 1/5 (2 addressed, 0 open; commits 5eafa5c..fac4fe2)
Task 2: minor (deferred): -U0 insertion hunk line off by one (rereview rev2)
Task 2: complete (commits 93214ab..fac4fe2, review clean)
Handoff: lead context full; next lead resumes at Task 3 (doc 2026-11-25-sil-task2-desk-specs.md)
Resume: new lead (handoff 2026-11-25-sil-task2-desk-specs.md)
Task 3: dispatched impl3 (standard, sonnet), BASE b4c570d
Task 3: report DONE, commit ead435e; verify 19 unittest OK + zsh ALL PASS rc 0 (green check passed)
Task 3: review dispatched rev3 (standard, sonnet) on review-b4c570d..ead435e.diff
Task 3: review rev3: spec ❌, 1 Important (I1 improve) case does not export TC_PROJECT=$FEEDKEY like engine), can open the wrong DB inside tmux)
Task 3: minor (deferred): M1 tick-less retire cap ignores tick inserts; M2 patch file written before COMMIT; M3 dedupe before R1; M4 mixed error prefix; M5 test_outcome_status reads live O1.json; M6 RebuildTest leaks dir on assert; M7 target joined to REPO unchecked
Task 3: fix round 1 commit 1c7ea93 (verify 19 OK + ALL PASS rc 0); re-review sent to rev3 on review-ead435e..1c7ea93.diff (standard)
Task 3: fix round 1/5 (1 addressed, 0 open; commits ead435e..1c7ea93)
Task 3: minor (deferred): inherited stale TC_PROJECT beats the session key; new zsh test needs the sqlite3 binary (rereview rev3)
Task 3: complete (commits b4c570d..1c7ea93, review clean)
Task 4: dispatched impl4 (standard, sonnet), BASE 0858551
Task 4: report DONE_WITH_CONCERNS, commit 59af1bd; verify 11 tests OK rc 0 (green check passed)
Task 4: review dispatched rev4 (standard, sonnet) on review-0858551..59af1bd.diff
Task 4: review rev4: spec ❌, 2 Important (observer rule target not normalised from +++ line, protected rules classed high; dream title read from nonexistent title, real field text)
Ruling: discovery adapter stays as written (reads path/spec_path) and is a no-op on today's data — board/findings.py and discover_post.py store no drafted spec path, spec §2 names only findings "with a drafted spec" — cost if wrong: discovery feeds no proposals until discovery drafts specs.
Ruling: an absent source (no dream run, no scout/discover file, no observer workspace or PENDING.md) is "not configured", writes no event; an unreadable or unparsable one writes one improve_adapter_error — brief's "missing" read as broken, not absent, to stop an error event every tick — cost if wrong: a deleted workspace goes unnoticed.
Task 4: minor (deferred): run_all store=/only= extras; _error uses Store private members; insert event detail reason is "insert", not the row reason
Task 4: fix round 1 commit d4dbd84 (verify 15 OK rc 0); re-review sent to rev4 on review-59af1bd..d4dbd84.diff (standard)
Task 4: fix round 1/5 (2 addressed, 0 open; commits 59af1bd..d4dbd84)
Task 4: complete (commits 0858551..d4dbd84, review clean)
Task 4: minor (deferred): ambiguous bare observer target stays bare -> high, fail-open for a protected file; Skip class unused (rereview rev4)
Task 5: dispatched impl5 (standard, sonnet), BASE 633d394
Task 5: report DONE, commit 17de8c1; verify unittest OK + node fail 0 rc 0 (green check passed)
Task 5: review dispatched rev5 (standard, sonnet) on review-633d394..17de8c1.diff
Task 5: review rev5: spec ✅, quality approved, 0 Critical/Important, minors below; 2 ⚠ resolved by lead rulings
Ruling: count guardrails (failed_specs, red_after_merge, final_review_crit_imp) return only worse/equal, never too early; too early only when a half has 0 specs — Metric definitions give counts only worse/equal, and a breach must be able to fire on a small trial — cost if wrong: a 1-3 spec trial can be reverted on one red merge (the +1 slack still applies).
Ruling: a record that is engine-run and of a baseline config counts as challenger only, not reference — double counting pulls the verdict toward equal — cost if wrong: a smaller reference set.
Ruling: the Final review ledger line counts the final_review job only, not the re_review after the fix wave — the guardrail measures what reached the final review, before its fixes — cost if wrong: the count overstates residual findings.
Task 5: minor (deferred): _EPS 0.05 undocumented (no verdict change for eps 0.001-1); defects arg of compare_halves unused
Task 5: fix round 1/5 dispatched to impl5 (2 rulings)
Task 5: minor (deferred): control half with no merged specs gives equal for a merging trial; list form of configs untested (rev5)
Task 5: fix round 1 commit f48fee4 (verify 52 OK + node fail 0 rc 0); re-review sent to rev5 on review-17de8c1..f48fee4.diff (standard)
Task 5: fix round 1/5 (2 addressed, 0 open; commits 17de8c1..f48fee4)
Task 5: minor (deferred): compare_to_baseline docstring stale after the challenger-only fix; engine-run-baseline mutation not run (rereview rev5)
Task 5: complete (commits 633d394..f48fee4, review clean)
Task 6: dispatched impl6 (standard, sonnet), BASE 46f8bb5
Task 6: report DONE_WITH_CONCERNS, commit 116b786; verify 10 tests OK rc 0 (green check passed)
Ruling: trial→rejected added to the store transitions — spec line 210 sends a stale patch to rejected and it is found in trial; the spec outranks the plan's transition table — cost if wrong: one transition to remove (Task 3 file, change by impl6).
Task 6: review dispatched rev6 (standard, sonnet) on review-46f8bb5..116b786.diff
Task 6: review rev6: spec ✅, quality needs fixes, 2 Important (git apply --unsafe-paths + Path(d)/rel let a ../ patch write outside the temp dir; bad routing JSON, patch-created target, skill target without skills part crash instead of stale path)
Task 6: minor (deferred): _section docstring stale; import shutil in finally; _code_mode tier check loose; _first_change skips '-- ' lines and ignores file of hunk; CLI non-empty output untested
Task 6: fix round 1 commit cf4574d (verify 15 OK rc 0); re-review sent to rev6 on review-116b786..cf4574d.diff (standard)
Task 6: fix round 1/5 (2 addressed, 1 new open — header parse treats content lines starting "-- "/"++ " as ---/+++ headers: IndexError crash and false unsafe path; commits 116b786..cf4574d)
Task 6: fix round 2 commit 2298c5b (verify 19 OK rc 0); re-review sent to rev6 on review-cf4574d..2298c5b.diff (standard)
Task 6: fix round 2/5 (1 addressed, 0 open; commits cf4574d..2298c5b)
Task 6: complete (commits 46f8bb5..2298c5b, review clean)
Task 7: dispatched impl7 (frontier, fable), BASE c25ab4d
Task 6: minor (deferred): a hunk header lying about its line count slips a ../ header past the pre-check; git apply refuses it as corrupt (rereview rev6 round 2)
Ruling: Task 7 extends backend/claude_tmux.js and bin/tmux-ctl agent with --env K=V forwarding so the Code Mode env reaches a real worker — a trial whose env stays on the fake backend measures nothing (spec E5) — cost if wrong: two small file changes outside the brief's list to revert.
Ruling: Task 7 impl7 assumptions accepted: variants stored in one improve_variants event (no column); a failed skill copy drops that variant (listed as dropped); later routing variant wins; trial brief block points at the challenger SKILL.md path, task text not rewritten — cost if wrong: brief wording changes.
Task 7: report DONE_WITH_CONCERNS, commit 8dca620; verify 16 pass 0 fail rc 0; report crossed the env ruling: impl7 sent back to add the forwarding
Ruling: improve variants exit 0 with non-JSON output → no variants and no event — older engine tests stub tmux-ctl with "fresh" exit 0 and pin event sequences — cost if wrong: a garbled variants answer goes unrecorded.
Task 5: regression found by impl7: engine_integrate.test.js:228 pins ledger_fields without red_after_merge/final_review_crit_imp; fix assigned to impl7 as its own commit
Task 7: follow-up commits e8e43d2 (agent --env, backend forwards job.env) and 15bced7 (Task 5 test expectation); verify 16/16 rc 0, engine_integrate 21/21 (green check passed)
Task 7: review dispatched rev7 (standard, sonnet) on review-c25ab4d..15bced7.diff
Task 7: review rev7: spec ✅, quality approved, 0 Critical/Important, 5 minors
Ruling: a skill variant for a spec with no worktree of its own (wtOf falls back to repo) is dropped (listed in dropped, reason no worktree) — brief: challenger copies only in that spec's worktree — cost if wrong: such a spec loses its skill trial.
Ruling: routing variant replaces the map whole (rev7 minor 2) — Task 6 returns the full patched model-routing.json, so effort keys present in the file survive — cost if wrong: one merge to add.
Task 7: minor (deferred): --env reserved-name guard beyond the brief (accepted); variantsOf SELECT per call; fix job on a resumed implement session gets no Code Mode env (by design)
Task 7: fix round 1/5 dispatched to impl7 (ruling: skill variant needs own worktree)
Task 7: fix round 1 commit 20476ca (verify 17/17 rc 0); re-review sent to rev7 on review-15bced7..20476ca.diff (standard)
Task 7: fix round 1/5 (1 addressed, 0 open; commits 15bced7..20476ca)
Task 7: minor (deferred): overlong comment line on improve.apply (rereview rev7); post-fix engine run 140/140 (improve, engine_core, engine_integrate, engine_backend)
Task 7: complete (commits c25ab4d..20476ca, review clean)
Task 8: dispatched impl8 (standard, sonnet), BASE 536774a
Task 8: report DONE_WITH_CONCERNS, commit 52397a8; verify 32 OK rc 0 (green check passed)
Ruling: tick hook names are improve_apply.apply, improve_pick.pick, improve_discord.card and improve_discord.digest — the plan puts cards and the digest in improve_discord.py (Task 12); Tasks 9, 10, 12 briefs carry these names — cost if wrong: a rename in HOOK_MODULES.
Ruling: impl8 assumptions accepted: tick id = seq of a start improve_step event written before the adapters; blame read from ruling/finding events of trial specs matching "Trial <P>"; spend cap checked from the first trial spec; O1 achieved needs signal better as well as index <= 0.75 — cost if wrong: each is a small eval change.
Task 8: hook-name fix commit 4236d15 (verify 32 OK rc 0)
Task 8: review dispatched rev8 (standard, sonnet) on review-536774a..4236d15.diff
Task 8: review rev8: spec ✅, quality approved, 0 Critical/Important, 5 minors; 2 ⚠ resolved by lead (hook names carried to Tasks 9/10/12 briefs; compare_halves count rule reviewed in Task 5)
Task 8: minor (deferred): hook exceptions uncontained, achieved event written before the card call so a failing card is never retried (carry to Task 12 brief); cmd_tick CLI untested; None batch counts toward min_queues; no mutation for outcome status / R3 docstring tests; transaction per transition, not per step
Task 8: complete (commits 536774a..4236d15, review clean)
Task 9: dispatched impl9 (standard, sonnet), BASE eec26a2
Task 9: report DONE, commit 27cc0db; verify 16 OK rc 0 (green check passed)
Ruling: impl9 changes accepted: tick maps pick's returned id list to {"started": n} (improve_eval.py, outside the file list); pick(outcomes=) optional, else repo outcomes read-only; reply without integer usage.output_tokens is a failure — cost if wrong: small eval/pick edits.
Task 9: review dispatched rev9 (standard, sonnet) on review-eec26a2..27cc0db.diff
Task 9: review rev9: spec ✅, quality approved, 0 Critical/Important
Task 9: minor (deferred): no test for missing/non-int usage.output_tokens; no test for duplicate ids in the reply (rev9)
Task 9: complete (commits eec26a2..27cc0db, review clean)
Task 10: dispatched impl10 (frontier, fable), BASE eef6b4f
Ruling: Task 10 stale patch at apply goes to rejected / stale patch from every state; kept→rejected and promoted→rejected added to the store (impl10 may edit improve_store.py for it) — spec sends stale patches to rejected and reverted means a landed commit was undone — cost if wrong: two transitions to remove.
Ruling: Task 10 improve tick sweeps around the eval: apply kept/promoted rows with no commit_sha before (retries a waited commit), draft proposed protected rows after; both idempotent — improve_eval calls apply only on the kept transition and has no draft hook — cost if wrong: the sweep moves into improve_eval.
Ruling: Task 10 retire into a gitignored .superpowers/ destination: the commit deletes the target and the copy is written to the ignored dir after the merge; tracked rename otherwise; revert is git revert — a tracked move into an ignored dir is impossible here — cost if wrong: the retired copy lives outside git.
Task 10: report DONE_WITH_CONCERNS, commits 710eec1 2a7b8b4; verify 25 OK + node 12 pass 0 fail rc 0 (green); report crossed the stale-patch ruling, impl10 applying it
Ruling: Task 10 engine_cli.test.js usage-line change accepted (outside the brief; pins the new merge-branch subcommand) — cost if wrong: one line.
Task 10: stale-patch ruling resent to impl10 (first message not received)
Task 10: rulings commit 4783687 (verify 26 OK + node 0 fail rc 0; store/eval 115 OK)
Task 10: review dispatched rev10 (standard, sonnet) on review-eef6b4f..4783687.diff
Task 10: review rev10: spec ✅, quality needs fixes, 1 Important (apply can raise ApplyError/UnicodeDecodeError into the tick after kept, aborting the tick; sweep_apply misses UnicodeDecodeError/OSError)
Task 10: minor (deferred): refused/waiting events repeat every tick without dedupe; section retire breaks on "-->" and keeps \r; _record uses private store._append_event/_conn (rev10)
Task 10: fix round 1/5 dispatched to impl10 (apply never raises; undecodable retire target is stale)
Task 10: fix round 1 commit c7d0f27 (verify 31 OK + node 0 fail rc 0); re-review sent to rev10 on review-4783687..c7d0f27.diff (standard; range also holds lead plan-doc commit 3f1db8d)
Task 10: fix round 1/5 (1 addressed, 0 open; commits 4783687..c7d0f27)
Task 10: complete (commits eef6b4f..c7d0f27, review clean)
Task 10: minor (deferred): a persistent refusal writes one improve_refused event per sweep; Task 12's digest must count transitions, not these events (rereview rev10)
Task 11: dispatched impl11 (frontier, fable), BASE 24c63d2
Task 11: report DONE_WITH_CONCERNS, commit 85bdce9; verify holds 15/15 # fail 0, grep 0, stop_hook_active 1, rc 0 (green); touched-module engine 224/224
Task 11: leak found by impl11: engine_queue_report restart test drained the new schedule row and started a default tmux server (one idle demo-bg session, no claude); impl11 killed it; lead confirmed no server on /tmp/tmux-503/default
Ruling: Task 11 impl11 changes accepted: TC_IMPROVE_TICK=0 skips the post-report row and engine_helpers.tmpEnv sets it (stops engine tests draining a real tick); engine_queue_report.test.js heading list gains ## Improve; trial n counts specs with an improve_variants event (specs started); hold.match also tries the symlink-resolved worktree-relative path (can only add holds) — cost if wrong: small test-seam and count changes.
Ruling: Task 11 post-report improve row is drained by the next engine wake/start in that process's cwd (payload has no cwd), untested through a real wake — carried to the Task 14 real-state checks and the Task 15 gate — cost if wrong: the tick runs against another repo or not at all.
Task 11: review dispatched rev11 (standard, sonnet) on review-24c63d2..85bdce9.diff
Task 11: review rev11: spec ✅, quality approved, 0 Critical/Important, 6 minors; ⚠ post-report row has no cwd (already a lead ruling, carried to Tasks 14/15)
Task 11: minor (deferred): realpathDeep per rule in hold.match (hoist out of the loop); post-report payload lacks cwd (add cwd: ctx.repo or confirm improve tick is cwd-independent); same-day second queue writes no row (README sentence, Task 13); improve_holds.test.js:658 assert hard to read; cmd_schedule no Python test; reportWorld deletes TC_IMPROVE_TICK until test.after
Task 11: complete (commits 24c63d2..85bdce9, review clean)
Task 12: dispatched impl12 (standard, sonnet), BASE 3c67572
Task 12: report DONE_WITH_CONCERNS, commit 4da9195; verify 54 OK rc 0 (green)
Ruling: Task 12 impl12 choices accepted: card project from payload, then TC_PROJECT, then git checkout name (none → logged failure, no post); awaiting_you card shows the tick's reason string after "trial" (the payload carries only that); digest once-per-week recorded as an improve_digest event; sweep_drafts posts the drafted card — cost if wrong: a card format change; a tick run from a worktree would name the worktree as the project.
Task 12: review dispatched rev12 (standard, sonnet) on review-3c67572..4da9195.diff
Task 12: review rev12: spec ✅, quality approved, 0 Critical/Important, 5 minors; ⚠ full leak check is Task 14's
Task 12: minor (deferred): drafted-card import inside sweep_drafts' try miscounts a good draft as error; promote/approve result post uses ✅ even for waiting/stale/refused; revert/approve ApplyError audited but no channel post; card project from env not the tick's --project; Reject on a draft leaves branch improve/<id>
Task 12: complete (commits 3c67572..4da9195, review clean)
Task 13: dispatched impl13 (mechanical, haiku), BASE 09b9041
Task 12: rev12 ran improve_discord._o1() unpatched with temp TC_STATE: "O1 n/a vs 0.75", no stderr (the O1 digest path the tests patch runs)
Task 13: report DONE, commit 773ea88; verify counts 1, 9, 1, HelpTest OK rc 0 (green)
Task 13: review dispatched rev13 (standard, sonnet) on review-09b9041..773ea88.diff (batch of one: Task 14 is standard)
Ruling: Task 13 README keeps the brief's capitalised "Learning is cheap…" (the acceptance line quotes it lowercase mid-sentence) — the brief gives the exact text and no test greps it case-sensitively — cost if wrong: one letter.
Task 13: review rev13: spec ✅, quality approved, 0 Critical/Important, 1 minor
Ruling: Task 13 README and help command list `improve outcome status|list|show|propose|revert|tick` (brief text) reads as outcome subcommands and omits variants, click and schedule install; it is corrected in the final review fix wave to the real subcommands — docs must match the code; the spec outranks the brief's wording — cost if wrong: two doc lines.
Task 13: complete (commits 09b9041..773ea88, review clean)
Task 14: dispatched impl14 (standard, sonnet), BASE f55099f
Task 13: minor (deferred): README does not say `improve schedule install` sets up the weekly tick (fold into the final-wave command-list fix) (rev13)
Task 14: report DONE_WITH_CONCERNS, commit aff88b3; all.zsh "ALL PASS 249 jobs in 8m14s" rc=4 (green, over budget accepted); first run failed zsh/test_run_watch_e2e.zsh 1/249 rc=1, passes alone and on the clean rerun
Task 14: real-state read-only: outcome status O1 -> "O1 too early"; observer adapters --dry-run read 15 items; dream --dry-run "dream: 0 item(s) read"; variants for the SIL spec -> "variants": []; leak check "3 item(s) checked across 8 module(s)", engine dir skipped (engine running)
Task 14: improve tick resolves the repo from the script path (cwd-independent); the project comes from TC_PROJECT/--project else git rev-parse in the cwd (board/improve.py:32-38); the post-report row runs in the engine's cwd (schedule.js:147)
Task 14: review dispatched rev14 (standard, sonnet) on review-f55099f..aff88b3.diff
Task 14: review rev14: spec ❌, quality needs fixes, 1 Important (dream dry-run prints a bare count, not kinds / no report; real newest run 20261125-0330 has proposals [])
Task 14: minor (deferred): isolation ">= 3 items" guard trivially true (assert runs.jsonl and main not absent); engine-running decided separately before and after (decide once); count printed after the modules run; PENDING.md edits by a live observer could flake it; cmd_adapters drops insert's return value (rev14)
Task 14: fix round 1/5 dispatched to impl14 (dream dry-run output)
Task 14: fix round 1 commit cf18dd3 (adapters+isolation 25 OK; real dream dry-run "dream 20261125-0330: no proposals" rc 0); re-review sent to rev14 on review-aff88b3..cf18dd3.diff (standard)
Task 14: fix round 1/5 (1 addressed, 0 open; commits aff88b3..cf18dd3)
Task 14: minor (deferred): DryRunDream inherits and re-runs the DryRun tests; `unreadable report` branch untested (rereview rev14)
Task 14: complete (commits f55099f..cf18dd3, review clean)
Ruling: Task 15 (user gate: a real queue with O1 active and one low proposal) needs the loop merged and a later real engine queue, so it runs after merge and is not closed by this plan's finish; the morning report lists it as owed — cost if wrong: the gate's evidence arrives one queue later.
Final review: dispatched final-rev (session level, general-purpose) on review-c273b84..69c7e60.diff with final-review-inputs.md
Final review: final-rev: with fixes, 0 Critical, 4 Important (I1 loop not scoped to agent-board: any project's report schedules a tick and gets variants; I2 observer patches keep absolute headers and bare skill targets so they can never be trialled or applied; I3 hold freezes all of bin/tmux-ctl, spec protects only its improve section; I4 ranking call never run for real, runs with all tools and a saved session)
Ruling: final I1 fixed by one loop-project helper (Python and JS) gating the report row (cwd: ctx.repo in the payload), loadVariants and every improve CLI entry — spec puts outcomes beyond agent-board out of scope — cost if wrong: other projects get no loop until a later spec.
Ruling: final I3 protectedHolds skips #section lines (the merge entry guards the improve) hunk); the holds on the rest of the protected set apply to all engine workers as spec §6 says, so queued specs editing orchestrator.md or plugin hooks park on approval holds — cost if wrong: overnight specs wait for an approval.
Ruling: final I4 ranking call restricted like dream's (no tools, --no-session-persistence) and one real restricted run made by the fixer — the deciding external command must run once for real — cost if wrong: one model call's tokens.
Final review: fix wave dispatched to fix-final (frontier, fable): I1-I4, README/help command list, must-fix minors
Final review: fix wave commits 1a40939..e937600 (I1-I4 + README/help); touched files 181 py + 71 node OK, HelpTest OK; all.zsh FAIL 1/249 engine (engine_backend.test.js cleanup ENOTEMPTY under load, 39/39 alone); real restricted ranking run is_error False, ["P1","P2"], 11 output tokens
Ruling: fix-final edits accepted: tools/tests/test_ctl_improve.zsh exports TC_IMPROVE_PROJECT (the real CLI now refuses other projects); the loop project is matched by the main checkout's directory name — cost if wrong: a session under another key is refused.
Final review: re-review final-rev: I1-I4, README/help and must-fix minors ADDRESSED, no new Critical/Important; Task 15 acceptance line added by lead (0322c3a)
Final review: minor (deferred): observer adapter finds staged skills only under claude/skills/<s>/, so plugin skills arrive only via _target-files; loop-project gate by directory name turns the loop off for a session under another key (fails safe)
Final review: suite on e937600 ALL PASS 249 jobs in 8m17s rc=4; final review clean
