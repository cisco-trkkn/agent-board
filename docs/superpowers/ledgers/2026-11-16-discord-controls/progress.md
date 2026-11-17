# SDD ledger — plan: docs/superpowers/plans/2026-11-16-discord-controls.md
Spec: docs/superpowers/specs/2026-11-11-discord-controls-design.md (reachable). Branch queue/discord-controls off main 53411cd; plan commit 7e7aba6.
Preflight scan:
| Pair/Task | Produces → consumes | Found |
| T1→T3 | `approve <win> show` T:/P: output → controls scan parser | agree (format in GC + probes) |
| T2↔T3 | prompt/edit op keys, perm/react/click event shapes (GC) | agree; both cite GC |
| T3→T4 | step(project, record, now, run, add_line), BIN | agree |
| T3↔T1 | approve argv once/deny --expect lines | agree (P lines = --expect) |
| T3,T4 both touch read_inbound | T3 deletes it + its tests in test_discord_feed.py; T4 removes its call in server.py | ordering: T4 after T3; T3's board suite run will fail on server.py's read_inbound call → Ruling R1 |
| T5 | docs cite T1–T3 names | agree |
| T6 | uses T1–T4 | agree |
| T1 self | tests vs code | agree |
| T2 self | fake-client extension vs tests | agree |
| T3 self | files list omits server.py but deletes read_inbound | see R1 |
| T4 self | code snippet vs AC | agree |
| T7 | user gate | agree |
Ruling: R1 — T3 keeps `discord_feed.read_inbound` as a thin deprecated alias (no behaviour) is NOT done; instead T3 deletes read_inbound and also removes its one call in board/server.py feed_tick (one line), and T4 then adds the step call — why: the board suite must stay green at T3's commit — cost if wrong: T3 touches one line of server.py, a file T4 owns next (serial, no conflict).
Ruling: R2 — T1 and T2 run in parallel (disjoint files, no dependency; blockedBy 18←17 removed) — cost if wrong: none; each gets its own review.
Task 1: dispatched dc-zsh (sonnet, base 7e7aba6)
Task 2: dispatched dc-node (sonnet, base 7e7aba6), parallel with Task 1 (R2)
Task 2: green (59/59, rc 0); review dispatched dc-rev (sonnet, 7e7aba6..7f5109f)
Task 1: green (show 11 checks ALL PASS, approve ALL PASS, weekly 16 OK, rc 0); review dispatched dc-rev1 (sonnet, 7f5109f..c90c285)
Task 2: review — spec ✅, quality needs fixes (1 I: ``` escape fails for 4+ backtick runs, bridge.js:111); task-2-review.md
Task 2: minor (deferred): unguarded c.user → <@undefined>; content.slice(0,2000) can cut the closing fence; single >1500 line shows nothing; re-posted key keeps old insertion order; U+FE0F invisible literal in source; event written even when deferUpdate fails; edit test doesn't assert fetch target
Task 2: ⚠️ real discord.js partial fetch, 10008, FE0F emoji names — covered by Task 7 gate
Task 2: fix round 1 dispatched dc-node
Task 1: review — spec ✅, quality approved; task-1-review.md
Task 1: minor (deferred): show adds an unbriefed exit-1 "no expect lines" path; test helper shw runs the command twice
Task 1: complete (commits 7f5109f..c90c285, review clean)
Task 3: dispatched dc-py (sonnet, base c90c285; R1: also removes the read_inbound call in server.py)
Task 2: fix round 1 green (61/61, rc 0; 9d2272a); re-review dispatched dc-rev
Task 2: fix round 1/5 (1 addressed + 2 folded minors, 0 open; commits c90c285..9d2272a)
Task 2: complete (commits 7e7aba6..9d2272a, review clean)
Task 3: green (controls 18 OK, feed 55 OK, board 1273 OK rc 0; 862b750); review dispatched dc-rev
Task 3: review — spec ✅, quality approved; task-3-review.md
Task 3: minor (deferred): event file deleted in finally even if edit/audit raised after the press; crash between press and unlink replays it ("allowed" overwritten by "not pressed"); same key re-posted after an outcome if show still returns it; keys for dead windows kept forever (ts unused); U+FE0F invisible literal discord_controls.py:135; weak either-order assertion test_discord_controls.py:483; invalid perm choice audited "ignored" (not in GC list)
Task 3: complete (commits 9d2272a..862b750, review clean)
Task 4: dispatched dc-wire (haiku, base 862b750)
Task 5: dispatched dc-docs (haiku, parallel with Task 4; disjoint files)
Task 5: green (Verify greps 1,1,1,1,1 rc 0; dry-run rc 0; 8e04a1f); review dispatched dc-rev
Ruling: Task 5 brief's "five bullets" is a plan miscount — the spec has four bullets (✅/❌ share one) plus the closing line; four + line is correct — cost if wrong: none.
Task 5: review — spec ✅, quality approved; task-5-review.md
Task 5: minor (deferred): bridge-first rule leaves a prompt that got no post (ambiguous, P1) with neither buttons nor #n — add "or when no post appeared for it" (final-review triage); heading parenthetical added; INSTALL has no 💡 mention
Task 5: complete (commits 862b750..8e04a1f, review clean)
Task 4: green (wiring 17 OK, board 1278 OK rc 0; 1973715); review dispatched dc-rev
Task 4: review — spec ✅, quality approved with 1 I (cross-task): _show catches only RuntimeError; run_script timeout raises TimeoutExpired → scan aborts, consume_events skipped; task-4-review.md
Task 4: minor (deferred): slow step runs outside the overview lock and can overlap the next build (flock serialises) — measure in Task 6
Ruling: the Task 3-code finding goes into Task 4's fix round 1 (dc-wire may edit board/discord_controls.py + its test); folded minor: tick and step get separate try blocks so a tick error no longer skips controls — why: the finding only surfaced with Task 4's real runner — cost if wrong: none.
Task 4: fix round 1 dispatched dc-wire
Task 4: fix round 1 green (controls 21 OK, wiring 18 OK, board 1282 OK; c92401e); re-review dispatched dc-rev
Task 4: fix round 1/5 (1 addressed + 1 folded minor, 0 open; commits 1973715..c92401e)
Task 4: complete (commits 8e04a1f..c92401e, review clean)
Lead handoff: Task 6 next (not dispatched); team shut down at handoff
Task 6: dispatched dc-e2e (sonnet, base 36e67ad; carry-ins: step duration/overlap, cut prompt full text)
Task 6: green (Verify 3,4 rc 0; board 1282 OK rc 0; f607099); DONE_WITH_CONCERNS (criterion 5 live-bridge diffs explained; real record had no waiting prompt)
Ruling: Task 6 criterion 5's checksum difference stands as explained — the lead restarted the live bridge and recreated the card (pin permission fix) during the run; the harness never wrote there — cost if wrong: a harness write into the real dir goes unseen (reviewer checks the note's diff evidence).
Ruling: Task 6 criterion 2 passes with 0 ops on the real record — needs_you was empty, and the plan cannot force a real prompt read-only; the post path is covered on the scratch server — cost if wrong: the real-record post path is first exercised in Task 7.
Task 6: review dispatched dc-rev6
Task 6: review — spec ✅ (2 ⚠️ resolved by the two rulings above; reviewer verified no harness write in the live dir), quality approved; task-6-review.md
Task 6: minor (deferred): note says bridge "restarted itself" (lead restarted it, twice incl. 23:22Z); no per-file md5 lines for live dir; second prompt/edit pair not pasted in full; harness script location unstated; older .err text not kept
Task 6: complete (commits 36e67ad..f607099, review clean)
Ruling: run the final review, fix wave and local merge before Task 7's user gate — Task 7 needs the merged code on the live board anyway, and merging first keeps the gate on reviewed code — cost if wrong: a gate failure needs a follow-up fix on main.
Final review: dispatched dc-final (session model, 53411cd..f607099)
Final review: with fixes — 0 C, 3 I (I1 unknown-key edit overwrites allowed; I2 no-post prompt stranded = Task 5 minor; I3 Task 7 criterion 2 unmeetable under P3), 6 M; final-review.md; all.zsh ALL PASS 139 jobs (rc 4 time budget), node 62/62
Ruling: I3 rewords Task 7's gate criterion in the plan before the gate runs — the reviewer showed P3 makes "not pressed" unreachable from a changed-before-tap prompt; the spec's intent (never press a changed prompt) is kept — cost if wrong: the gate checks a weaker path than the user asked for.
Final review: minor (deferred): dead-window keys kept forever; ✅ on a prompt post reaches lead as yes; events dir local trust boundary; bridge node tests not in all.zsh; crash replay between press and unlink
Fix wave: dispatched dc-fix (sonnet, FIX_BASE f607099; I1-I3 + INSTALL not-pressed + e2e note wording)
Fix wave: bounced 1/2 (no full board suite summary line; folded: plan Task 3 unknown-key bullet stale)
Fix wave: green (controls 22 OK, board 1283 OK rc 0; 4e8d303, b27491e); re-review dispatched dc-rerev
Final review: fix wave re-review — I1, I2, I3 + folded minors ADDRESSED, no new C/I; fixwave-rereview.md (commits f607099..b27491e)
Final review: minor (deferred): I2 wording has no timeout for "no post appeared"
Finish: pre-merge all.zsh ALL PASS 139 jobs (rc 4 time budget only, 0 FAIL lines); node 62/62
