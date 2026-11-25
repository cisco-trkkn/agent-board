# SDD ledger — plan: docs/superpowers/plans/2026-11-24-remote-lead-liveness.md
Preflight: table in preflight.preflight.md (pairs 1→2,1→3,3→4,4→5,4→8,1/2↔4,4/5↔night-watch,4↔6,6↔new-project,7↔8,9→1-8; per-task 1-10); 14 findings, none blocking.
Stale check: stale (server.py, bridge.js, commands.js, commands.test.js, discord_ops.py, fake-client.js); drift carried into briefs instead of a plan refresh.
Ruling: stale plan refreshed through briefs (preflight §c anchors) rather than a refresh agent — preflight already mapped every drifted anchor at HEAD — a brief that misses an anchor costs one red run.
Ruling: F1 manifest base set to the final integrated main before dispatch — plan anchors verified there — registry validate blocks otherwise.
Ruling: F2/F3 noteOwn on watchTick's home send + test that a watch post after the target keeps 📨 — removes a false ✅ — user sees ✅ on unanswered message while board down.
Ruling: F4 Task 2 tests also patch observe_overview and read_limits — keeps the real WATCH out of tests — test writes watch.json or calls tmux-ctl.
Ruling: F5/F6 Task 6 brief lists commands.js:32 → ops || name !== 'new-project', commands.test.js 50/54 and the test at 278 → project 'myproj' — pinned lists drifted — reviewer flags as scope creep.
Ruling: F7/F8 liveTick sets lastLiveAt = now() after an evaluation; tests step 10 000 ms after the first — matches spec 10 s — 5× Discord reads unnoticed.
Ruling: F9 L.shown/L.added set in opLiveness after the Discord call succeeds; failure leaves shown so the next evaluation retries — at-least-once — a lost reaction stays wrong until state changes.
Ruling: F11 Task 6 adds ideas-wiring cases, existing ops-bridge test kept — it still passes — none.
Ruling: F12/F13 outbox cap for liveness ops and per-tick holder_of cost accepted as follow-ups — low probability — dropped reaction op or slower overview with many projects.
Task 1: dispatched impl1 (mechanical/haiku), BASE 0bfcf43
Task 1: report in, verify green (15 OK), commit 166f3ea
Task 1: ⚠️ transcript row shape resolved by lead: transcript_info on the live lead transcript 019bd56d… returned the newest channel text, its message_id and queued 0.
Task 1: minor (deferred): M2 tail drops a whole first line at a boundary; M3 transcript miss re-globs each tick; M4 tmp left on write failure; M5 _cache never evicted; M6 test stderr noise.
Ruling: M1 (first channel tag of a batched row, not the newest) fixed in Task 2, which already edits lead_state.py: use the last tag in the row — a batched row would show the older message as read — one extra edit in Task 2's diff.
Task 1: complete (commits 0bfcf43..166f3ea, review clean)
Task 2: dispatched impl2 (standard/sonnet), BASE 166f3ea
Task 3: dispatched impl3 (mechanical/haiku) in parallel (files disjoint), BASE 166f3ea
Task 2: report in, verify green (26 OK), commit 41695ee
Task 3: report in, verify green (8/8, npm test 234/234), commit 9b2944f
Task 3: minor (deferred): readState test leaves one mkdtemp dir (leak)
Task 3: ⚠️ mutation check resolved by lead: report carries RED/GREEN/mutation output (expected 🙋, actual ✅, restored, cmp identical).
Task 3: minor (deferred): unknown state → 📨 / down: line (unreachable); future `at` never stale (clock skew).
Ruling: Task 4's bridge test reads one lead-state fixture captured from real `python3 board/lead_state.py --dry-run` output (would_write object) — fixtures so far are hand-written from the schema — a key-name mismatch between writer and reader would pass every test.
Task 3: complete (commits 41695ee..9b2944f, review clean)
Task 2: ⚠️ real dry-run resolved by lead → real gap: live transcript 3.62 MB, newest channel row at byte 2.28 MB, outside the 1 MiB tail after ~2 min of work (one screenshot + tool output) → last_read null, the reaction would fall from 👀 back to ⏳.
Ruling: transcript_info carries the last channel read forward when the tail holds no channel row: first from the per-path cache's previous result, else (board restart, no cache) from the previous lead-state.json's last_read_* — keeps the 1 MiB cap the spec sets — a carried read can point to an older session's message after a relay (still a real read message of this project's lead).
Task 2: minor (deferred): Wiring tests don't clear TC_LEAD_STATE; _holder_and_sid duplicates server's holder lookup.
Task 7: dispatched impl7 (standard/sonnet) in parallel, BASE 9b2944f
Task 8: dispatched impl8 (standard/sonnet) in parallel, BASE 9b2944f
Task 2: fix round 1/5 dispatched to rerev2 (1 Important + 1 Minor; commits 9b2944f..ef1a4e3)
Task 2: fix round 1/5 (2 addressed, 0 open; commits 9b2944f..ef1a4e3)
Task 2: minor (deferred): carried read never expires; tail-wins test has no mutation run.
Task 2: complete (commits 166f3ea..ef1a4e3, review clean)
Task 4: dispatched impl4 (standard/sonnet), BASE ef1a4e3
Task 6: dispatched impl6 (standard/sonnet) in parallel, BASE ef1a4e3
Task 7: report in, verify green (76 OK), commit a4edc1a
Task 7: implementer addition carry_to_successor (skips the 30 s poll when the old session has no marker) — left for rev7 to judge; no real-tmux relay run (user-gate Task 10 covers live)
Task 7: ⚠️ resolved by lead: live ~/.claude/sessions/*.json has startedAt in ms and tmux "sess:@win.%pane", matching session_started_after's endswith("."+pane).
Task 7: fix round 1/5 dispatched to impl7b (fresh; Critical: restart_lead --resume calls session_for_pane with home/state None → TypeError)
Task 6: report in, verify green (node 53/53, python 82 OK), commit 427698e
Task 7: fix round 1 report in (covering test test_resume_defaults_home_and_state_when_not_given, 77 OK), commit e8b6cd8
Task 7: fix round 1/5 (1 addressed, 0 open; commit e8b6cd8)
Task 7: complete (commits a4edc1a, e8b6cd8; review clean after 1 round)
Task 4: report in, verify green (npm test 251/251), commit 8d4bdb8
Task 6: ⚠️ resolved by lead: project discord dirs hold no views.json (only _ops), so ctx.views().projects is not an array on a project bot and `unknown` is false: /ideas project:<own> passes.
Task 6: minor (deferred): "any channel" not exercised with a distinct channel; refusal branch in discord_ops is defensive only.
Task 6: complete (commit 427698e, review clean)
Task 8: ⚠️ resolved by lead: on-disk discord dirs (agent-board, interiors, scratch) are named by session name as A6 assumes; a hook without TMUX_PANE and DISCORD_STATE_DIR is inert (fails safe, no false remote).
Task 8: minor (deferred): a long autonomous turn can push the last typed prompt past the 4 MiB tail → false remote (same window as last_user_row); empty vs unreadable transcript_path edge asymmetry; discord_dir spawns tmux per ask.
Task 8: complete (commit 87bc3d9, review clean)
Ruling: F11 revised — the ops-bridge test did need its bridge argument set to "_ops" (it sent bridge="alpha"); impl6 changed only that argument — the lead's F11 read was wrong — none (ops behaviour unchanged).
Task 4: minor (deferred): newer message within ~2 s of an enqueue leaves the pending add on the old message; 👀 added=null branch forgets a bridge-owned 👀 on a replayed op; watchTick ms race can show false ✅; real-writer fixture literal carries a /Users/francisco.ruiz path.
Task 4: fix round 1/5 dispatched to impl4 (Important: permanently failing liveness op retried every 10 s unbounded → outbox/failed growth + log noise)
Task 4: ⚠️ discord.js cache key for ⚠️ (FE0F): reactionOf falls back to a match with U+FE0F stripped, so either key form is found; live confirmation in user-gate Task 10.
Task 4: fix round 1 report in (covering test 'a permanently failing react is given up on after 3 attempts', 252/252), commit 9d8b430; rerev4 dispatched
Task 4: fix round 1/5 (1 addressed, 0 open; commit 9d8b430)
Task 4: minor (deferred): a success on another (message, emoji) key does not clear a stale failure count.
Task 4: complete (commits 9b2944f..9d8b430 excl. other tasks: 8d4bdb8, 9d8b430; review clean after 1 round)
Task 5: dispatched to impl4 (resumed, standard), BASE 9d8b430
Task 5: report in, verify green (npm test 258/258), commit 99ac3d9 — review not yet dispatched (handoff)
Task 5: rev5 review: spec ✅, quality Approved
Task 5: ⚠️ resolved by lead: real-Discord partial-message channel id and Manage Messages removal are covered by user-gate Task 10.
Task 5: minor (deferred): a repeat ❓ inside the 10 s dedupe leaves the second ❓ on the message (no unreact); opLivenessReply relies on generic outbox retry.
Task 5: complete (commit 99ac3d9, review clean)
Task 9: dispatched to impl9 (haiku, mechanical), BASE 99ac3d9
Task 9: report in, verify green (1 / 6), commit b8916c7
Task 9: rev9 dispatched (standard)
Task 9: rev9 review: spec ✅, quality Approved
Task 9: minor (deferred): carry paragraph does not say <state> (tmux-ctl dir) is a different base from the discord dir; outbox op shapes/naming not listed.
Task 9: ⚠️ resolved by lead: #lead-liveness-on-discord anchor follows GitHub's slug rule for that heading.
Task 9: complete (commit b8916c7, review clean)
Merged local main d3242b4 into branch (78486cf, note only). Final review dispatched to final-rev (session model), range d3242b4..78486cf
Final review (final-rev): Ready with fixes — I1 carried marker cleared by successor's startup prompt; I2 bot system messages give false ✅; I3 queued_command channel rows never read; M1-M3 minor; all deferred minors can wait
Ruling: I1 fixed by the guard ignoring human rows matching relay.prompt_for's anchored sentence (option b), test generating the text from prompt_for — simpler than a marker content protocol — if wrong, a user who types exactly that sentence keeps the remote marker (harmless: asks go to Discord)
Ruling: I2 fixed by ignoring bot messages with msg.system or type ∉ {0,19} in track() — Discord system types are bot-authored — if wrong, a legitimate bot reply of another type misses ✅ (shows ⏳/📨)
Ruling: I3 fixed by also reading attachment/queued_command rows with Discord channel origin — shape from real transcripts — if wrong, 👀 stays missing for mid-turn messages (status quo)
Final fix wave dispatched to fixfinal (standard), FIX_BASE 78486cf
Final fix wave: report in, green (bridge 259/259, board 111 OK, guard ALL PASS), commits 355e05a..9c02a74; re-review sent to final-rev
Final fix wave: re-review (final-rev): I1, I2, I3, M2 ADDRESSED; no new Critical/Important
Final: minor (deferred): ARCHITECTURE.md:277 new sentence makes "It then denies" read ambiguously; a user typing the exact relay sentence is not treated as typed (by design)
Final review: clean after one fix wave (commits 355e05a..9c02a74)
Finish: all.zsh FAIL 1/232 board/test_discord_ops test_ideas_slash_from_a_project_bridge_goes_through_ops ('a' != '_ops')
Ruling: the failing test (01c93f3, pre-branch) pinned "/ideas always posts through ops", which spec §4 replaced; code kept, test rewritten to spec §4 (own project, no project, other project refused) — F11 had looked at a different test — if wrong, project-bot /ideas posts in the project channel instead of #command-center
Finish: fix 418354f (fixideas), re-review ADDRESSED (rerevideas); merged origin/main (c2ce816, tree unchanged)
Finish: all.zsh rerun FAIL 2/232 test_repo_paths + engine: both pass alone (repo_paths 2/2 runs, engine 445/445) — load flakes; bridge 259/259
