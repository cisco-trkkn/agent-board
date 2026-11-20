# SDD ledger — plan: docs/superpowers/plans/2026-11-20-lead-recovery-discord-commands.md
Spec: docs/superpowers/specs/2026-11-19-lead-recovery-discord-commands-design.md. Branch base 6c6c1dd; main merged in at dcb0437 (relay respawn fix c5f2acb).
Native tasks: plan T1..T12 = #43..#54.
## Preflight scan
| pair / task | shared | finding |
|---|---|---|
| T1/T3 | board/relay.py | T1 may touch wait_turn_end; T3 adds new functions; serial (T3 blockedBy T2<-T1): ok |
| T2/T3/T8 | bin/tmux-ctl | three writers; T2->T3 serial; T8 must not run concurrently with T2/T3 |
| T2/T10 | tmux-orchestrator SKILL.md x2 | T2 edits relay row, T10 adds lead-restart row; T10 after T2 |
| T3/T6 | relay.newest_handoff | T6 consumes T3's helper: T6 after T3 (plan order ok) |
| T6/T7 | views.json keys tasks, leads | T7 consumes T6 shapes: T7 brief carries the shapes from T6's AC |
| T7/T9 | events slash lead/gauth (iid), modal gauth, ireply op | T9 consumes T7's event shapes: both briefs quote T7 AC shapes |
| T8/T9 | board/gauth.py API | T9 uses start/read_url/send_code/result/token_check/close |
| T7 | board/discord_feed.py | ireply op kind; T5 posts via discord_feed too (different function): no overlap in edits |
| T1 | board/paneclass.py | fix/resume-wrapped-footer also edits paneclass: T1 waits for that merge, then main merged in |
| each task | self-consistency | T3 AC "runs outside tmux" needs line-107 exemption (listed in Files): ok; T9 "poll read_url up to 30 s" blocks consume: Ruling below |
Ruling: T9 may run the gauth URL wait and the code/result wait off the consumer thread (a thread or a tick-driven state machine), implementer's choice — a 30 s+ block in discord_ops.consume stalls every other Discord event — if wrong, a simpler blocking version is a small rework.
Ruling: execution order T4 || T7 first (disjoint files), then T1 after the resume fix merges, T2, T3, T8, T5, T6, T9, T10, T11 — files disjointness per scan — if wrong, only wall-clock.
Task 4: dispatched lr-t4 (sonnet, effort-medium), BASE dcb0437
Task 7: dispatched lr-t7 (sonnet, effort-medium), BASE dcb0437 (parallel with T4: disjoint files)
Task 7: report DONE_WITH_CONCERNS b02bd4a (assumptions: ireply components = rows shape; /tasks none → "no task lists"; no lead entry → "no lead info for <p>"; read events for /tasks,/lead status; ireply falls back on editReply throw); bounce check green
Task 8: dispatched lr-t8 (sonnet, effort-medium), BASE b02bd4a
Task 7: review dispatched rev-t7 (sonnet) on review-dcb0437..b02bd4a.diff
Task 7: review rev-t7 spec ✅ quality needs fixes: I1 Confirm double click writes two lead events; I2 ireply fallback posts gauth URL publicly / falls back on transient errors. Minors: modal "Code sent." before writeEvent; no real discord.js payload test (deferred)
Ruling: T7 I2 — ireply falls back to a channel post only when the iid is unknown/expired; an editReply error is logged (`ireply <iid> failed: <err>`), not posted; an op with `private: true` never falls back (logged `ireply <iid> dropped (private)`); Task 9 sends gauth URL replies with private: true — the URL never lands in a channel — if wrong, a lost lead-restart result on a transient error (still visible via /lead status).
Ruling: T7 ⚠️a — preview suffix reads `; it is <state> right now` for any state other than idle/null — T6 states are idle|busy|waiting — if wrong, wording only.
Task 7: fix round 1 dispatched to lr-t7b (fresh, prior implementer gone), FIX_BASE b02bd4a
Task 7: fix round 1 done 25ce9cd (npm 173/0, feed 89 OK); re-review rr-t7 dispatched
Task 7: fix round 1/5 (5 addressed, 0 open; commits b02bd4a..25ce9cd)
Task 7: minor (deferred): no real discord.js select/modal payload test (FakeClient only)
Task 7: minor (deferred): Confirm id consumed before writeEvent (failed write burns it); consumed-id Set never pruned
Task 7: complete (commits dcb0437..25ce9cd, review clean)
Task 8: report DONE 34adc0f (test_gauth 17 OK rc0); bounce green; review rev-t8 dispatched
Task 8: review rev-t8 spec ✅ quality needs fixes: I1 result() misses non-adc "You are now logged in as"; I2 "." in project name vs tmux session-name mangling; I3 no test for a code starting with "-". Minor: tmux failure in start not a GauthError (included in fix); fake gcloud output hand-written (deferred)
Ruling: T8 I1 — result() returns ("ok", line) for "Credentials saved" OR "You are now logged in as" — the brief's wording named only the adc line; the spec's intent is "the window's success line" — if wrong, a wrong ok text match, caught at the /gauth gate.
Ruling: T8 I2 — keep "." legal in project names (same regex as tmux-ctl discord) and map the name to tmux's session form ("." and ":" → "_") wherever gauth builds a tmux target — dropping "." would diverge from the other commands — if wrong, a dotted project's gauth window not found.
Task 8: fix round 1 sent to lr-t8 (resumed), FIX_BASE 34adc0f
Task 4: report DONE_WITH_CONCERNS 4be44f3 (test_claude_orchestrator_dc ALL PASS rc0, 63 ok); bounce green
Ruling: T4 "no wait" AC measured as elapsed < 10 s with TC_DC_WAIT=20 plus no "waiting" line, not elapsed < 1 s — one launcher run takes 1-4.7 s here (dc_holder ps scans) — if wrong, a short accidental wait (<10 s) could go unnoticed.
Task 8: fix round 1 done f02d26b (test_gauth 22 OK); note for T9: use gauth._window(p) or waiting file window
Task 4: review rev-t4 spec ✅ quality needs fixes: I1 bad/0/negative TC_DC_POLL loops forever; I2 wait counts sleeps only, not dc_holder scans (60 s can take 90-180 s). Minor: bad TC_DC_WAIT silently 0 / math error, no knob test (included)
Task 4: fix round 1 sent to lr-t4 (resumed), FIX_BASE 4be44f3
Task 8: fix round 1/5 (4 addressed, 0 open; commits 34adc0f..f02d26b)
Task 8: minor (deferred): fake gcloud output hand-written, not captured from a real login
Task 8: complete (commits 25ce9cd..f02d26b, review clean)
Lead handoff 2026-11-20: tasks.json T7/T8 sync committed aca911d; lr-t4 respawned (fix round 1 resume, uncommitted edits kept)
Task 4: fix round 1 done 2cb52cc (test_claude_orchestrator_dc ALL PASS rc0); bounce green; scoped re-review rr-t4 over aca911d..2cb52cc
Task 4: fix round 1/5 (3 addressed, 0 open; commits aca911d..2cb52cc)
Task 4: minor (deferred): test 40 s watchdog spans five ~7 s runs, can fire early under load (false fail, not false pass); 15 s watchdog never cancelled
Task 4: minor (deferred): fix-round mutations reasoned, not executed
Task 4: complete (commits f02d26b..2cb52cc, review clean)
Main 483eb44 (resume fix 86ff527) merged into branch at 3d06f78
Task 1: dispatched lr-t1 (standard), BASE 3d06f78
Task 1: report DONE_WITH_CONCERNS 67d6723 (no bug on branch; regression fixtures; verify 97 OK rc0; board 1934 OK rc0); bounce green
Task 1: review rev-t1 dispatched (3d06f78..67d6723)
Task 1: review rev-t1 spec ✅ quality approved (busy record delays end ≤45 s TTL < 120 s cap)
Task 1: minor (deferred): test_paneclass mutation comments :110/:118 not run; :118 would not fail under its named mutation; idle fixture trimmed to 22 lines, README doesn't say
Ruling: T1 no code fix — the idle-with-task-list capture already reads ended on the branch (classify ready, wait_turn_end True); kept as regression fixtures per the brief's no-bug AC — if wrong, the original busy misread recurs in T2/T3 relay and shows at the T12 gate.
Task 1: complete (commits 3d06f78..67d6723, review clean)
Task 2: dispatched lr-t2 (standard), BASE 223fc3e
Task 2: report DONE 9b3d7a4 (test_ctl_relay ALL PASS rc0; help tests green); bounce green; review rev-t2 dispatched
Task 2: review rev-t2 spec ✅ quality approved
Task 2: minor (deferred → carried into T3 dispatch): tmux-ctl:672 list-windows -t "=$csess:" uses the feed key; a grouped session's group name can fail silently and skip the duplicate-claude guard; use the pane's own session
Task 2: complete (commits 223fc3e..9b3d7a4, review clean)
Task 3: dispatched lr-t3 (standard), BASE cf7cddc (carries T2 grouped-session minor)
Task 10: dispatched lr-t10 (mechanical) in parallel with T3, disjoint files, BASE cf7cddc
Task 10: report DONE 618fd80 (verify greps 1,1,1,1 rc0); bounce green; review rev-t10 dispatched
Task 10: review rev-t10 spec ✅ quality approved, no findings
Task 10: complete (commits cf7cddc..618fd80, review clean)
Note for T3 review / final review: check lead-restart flags match the T10 skill-table row ([--resume|--doc <d>])
Ruling: T3 R4 wrapper — run it with job control (set -m) so the orchestrator is the pane's foreground job (pane_current_command = claude, as for a shell-started lead); a plain 'sh -c' wrapper leaves the shell as foreground and the board/discord-watch would read the lead as a shell — if wrong (job control not taking effect), fall back to lr-t3's wait_lead_started and T5/T9 must not rely on pane_current_command.
Task 3: report DONE_WITH_CONCERNS 3696c9b + job-control follow-up 2e9f4a3 (zsh -f -i -c wrapper; pane_current_command = stub; lead_restart 37 ok, test_relay 50 OK)
Task 3: bounced 1/2 (follow-up section lacks test_ctl_relay output)
Task 3: bounce cleared (test_ctl_relay 61 ok ALL PASS); review rev-t3 dispatched 33f5b79..2e9f4a3
Task 3: review rev-t3 spec ✅ quality approved
Task 3: minor (deferred): relay.py:254-261 rename claude-next→claude happens before respawn; a failed respawn leaves the window renamed
Task 3: minor (deferred): zsh "nothing typed" check (test_ctl_lead_restart.zsh:654) greps for "cd -- " and cannot fail meaningfully; real guard is the stub assertNotIn(send-keys)
Task 3: minor (deferred): non-zsh $SHELL branch (no -f) untested; restart_lead unit tests mock wait_started; held-by-old-holder bot wait is 20 s then "not held"
Task 3: complete (commits 33f5b79..2e9f4a3, review clean)
Task 5: dispatched lr-t5 (standard), BASE ceacd3e (new lead after handoff)
Task 6: dispatched lr-t6 (standard) in parallel with T5, disjoint files, BASE ceacd3e
Task 6: report DONE_WITH_CONCERNS 4f2f720 (test_discord_ops 62 OK rc0); bounce green; review rev-t6 dispatched
Task 5: report DONE 2d9ef03 (test_discord_watch 79 OK rc0); bounce green; review rev-t5 dispatched 4f2f720..2d9ef03
Task 6: review rev-t6 spec ✅ quality needs fixes (1 Important: server.lead_infos untested)
Task 6: minor (deferred): /tasks with no spec floor says none while the card falls back to non-completed tasks (discord_ops.py:56 vs discord_feed.py:259)
Task 6: minor (deferred): tasks_text does not check the Plan & run task is in_progress; a stale floor lists a finished spec's tasks
Task 6: minor (deferred): lead_view context_window .get chain unguarded; a non-dict tap payload raises inside tick (use usage._get)
Task 6: minor (deferred): tap freshness 3600 s hard-coded; mod_states() re-read per project in lead_infos; odd 1x fixture in test_discord_ops:297
Task 6: ⚠️ bridge leadStatus keys resolved by lead: commands.js reads the same 9 keys lead_view writes
Task 6: fix round 1/5 sent to lr-t6 (Important: lead_infos untested)
Task 5: review rev-t5 spec ✅ quality approved
Task 5: minor (deferred, final review should weigh): repair_botless runs inside watch_once unguarded; a raising seam aborts the old reconnect path, and _restart can block 120 s before it
Task 5: minor (deferred): real-default argv of _holder/_restart/_lead_of and _post through outbox_write untested; _holder uses state_dir() not state_dir(env); loose log assertion; idle_seen of vanished projects never pruned
Task 5: complete (commits 4f2f720..2d9ef03, review clean)
Task 6: fix round 1 report d316be9 (wiring+ops 103 OK rc0); re-review rr-t6 dispatched 2d9ef03..d316be9
Task 6: fix round 1/5 (1 addressed, 0 open; commits 2d9ef03..d316be9)
Task 6: complete (commits ceacd3e..d316be9, review clean)
Task 9: dispatched lr-t9 (standard), BASE dd1062e
Task 9: report DONE 68e5c7a (test_discord_ops 81 OK rc0; board suite 1985 OK rc0); bounce green; review rev-t9 dispatched
Task 9: review rev-t9 spec ✅ (2 ⚠️) quality approved; 1 Important (plan-mandated: 30 s/60 s gauth waits block consume/ops_tick under the ops lock)
Task 9: ⚠️ doc resolved by lead: views.json leads[p].doc is relay.newest_handoff's full path (discord_ops.py:138), the same doc the /lead preview showed
Task 9: ⚠️ confirmed real gap: run_script timeout=20 (server.py:607) < spec §2 step 5's 60 s start wait + bot check; a slow successful restart reads as failed
Ruling: T9 Important 1 — fix now, not as a follow-up: lead-restart, the gauth URL poll and the result wait run off the tick (a worker thread per action, seamed so tests run it synchronously), consume returns at once; the spec's 30 s/10 min limits are unchanged — if wrong, a thread outlives a board restart's state and the 10-min tick sweep is the only cleanup.
Ruling: T9 Minor 1 joins fix round 1 — the failure paths it names are the code the fix moves into the worker, so any exception there closes the gauth window and ireplies; if wrong, it costs a few extra lines in this round.
Task 9: minor (deferred): outcome ireply non-private (expired interaction falls back to a channel post with gcloud ERROR line); plaintext code event file lives until the finally unlink; lead with run=None returns ignored with no ireply; test naming/slicing nits and leak test not grepping gauth-pending.json/views.json; doc from views.json tied to tick freshness
Task 9: fix round 1/5 sent to lr-t9 (Important 1 non-blocking, ⚠️ restart timeout, Minor 1 by ruling)
Task 9: fix round 1 report 5a4dac0 (ops+wiring 132 OK rc0); re-review rr-t9 dispatched 68e5c7a..5a4dac0
Task 9: follow-up test-only commit fdef732 (join worker in default-spawn test, flaky 1/3); added to rr-t9 scope
Task 9: fix round 1/5 (3 addressed, 0 open; commits 68e5c7a..fdef732; fdef732 test-isolation only)
Task 9: minor (deferred, final review should weigh): two quick /lead restart confirms run lead-restart concurrently (no per-project guard; the second respawn -k could kill the lead the first just started)
Task 9: minor (deferred): a board exit mid /lead worker leaves no audit/ireply; gauth_sweep at ~599 s can close under a modal worker awaiting result (two replies)
Task 9: complete (commits dd1062e..fdef732, review clean)
Task 11: dispatched lr-t11 (standard), BASE ea0913b
Task 11: BLOCKED all.zsh rc=1, FAIL 1/174 test_claude_orchestrator_dc.zsh (T4 checks, load-flaky); npm 173 pass; real-state check matches; runbook e3b9f15
Ruling: the T4 orchestrator wait flake is fixed before merge, not accepted — the checks are new on this branch and would make main flaky; lr-t4f (standard) diagnoses and fixes, T11 reruns all.zsh after — if wrong, a slower path to the merge only.
Task 11: rerun all.zsh rc=1 again, same file (+ leak: no fake holder left); data forwarded to lr-t4f
Task 4 flake: report DONE 0a56def test-only (root cause: fixed timers/shared watchdog raced the launcher under load); 20 loaded runs rc0 0 FAIL; mutations requested; review rev-t4f dispatched
Task 4 flake: review rev-t4f ADDRESSED, 2 Minor (deadline check lost its upper bound; settle pkill -P misses grandchildren)
Ruling: flake-fix Minor 1 (deadline upper bound) joins a fix round — it loosens the guard T4 fix round 1 added, against the dispatch's no-loosening rule; Minor 2 rides along (same file, leak class seen in the suite) — if wrong, one extra small round.
Task 4 flake: fix round 1 sent to lr-t4f (+ 4 mutation checks)
User (terminal, 16:50Z): /gauth should work for logging into any GCP account, not only signal-hub-gcp/cox-agent; the T12 gate picks the project/account then (gauth config takes --adc/--impersonate/--account per project)
Task 4 flake: round 2 703d27c — real race in bin/claude-orchestrator (dying old lead: dc_holder returns pid with no pane, ended the wait early) fixed test-first; leak check scoped to own holders; 20 loaded runs rc0
CHECKPOINT (user reboot gate #6, ~17:00Z): T1-T10 complete. Open: flake fix round 1 (deadline upper bound, killtree, 4 mutations) — lr-t4f finishing, see its "## Checkpoint" in task-4-flake-report.md; then a scoped re-review of e3b9f15..<head> incl. 703d27c's code change (bin/claude-orchestrator: needs a standard reviewer); then T11 rerun all.zsh (+ npm test still 173/173 at e3b9f15) and complete T11; then final whole-branch review; merge (no push); restart board + bridge; T12 phone gate with user (gauth: user picks project/account).
Task 4 flake: fix round 1 committed 87fc9af (deadline 3<=el<20 from waiting line; killtree); file alone rc0; NOT run: 20-run load rerun, 4 mutation checks — do these first on resume
RESUME after reboot (17:20Z): respawning flake-fix finisher lr-t4g
Task 4 flake: re-review rr-t4f dispatched 0a56def..87fc9af (incl. 703d27c code change), parallel with lr-t4g evidence
Task 4 flake: re-review rr-t4f ADDRESSED both, 703d27c code change sound (wait stays bounded by DC_WAIT); open gate: lr-t4g evidence
Task 4 flake: minor (deferred): deadline lower bound 4.5→3 unexplained; mislabelled held-by line after a deadline break on a pane-less reused pid; R3 seam lacks never-returns and different-pane-less-holder cases
HANDOFF (17:5xZ): lr-t4g load rerun 20/20 rc0 0 FAIL; killed mid-mutations (M5 left in bin/claude-orchestrator, reverted by lead); M1-M5 to rerun. Doc ~/.local/state/agent-board/handoffs/2026-11-20-lr-flake-evidence-final.md
RESUME (new lead b94397a7): lr-t4g respawned for M1-M5 only (load rerun recorded from handoff)
Task 4 flake: evidence DONE (lr-t4g): load 20/20 rc0 0 FAIL; M1/M1b/M2/M3/M4/M5 each fail their check (rc=1), reverted; file alone rc0; no test change
Task 11: rerun dispatched lr-t11b (standard), all.zsh + npm test at 87fc9af
Task 11: rerun green at 87fc9af: all.zsh ALL PASS 174 jobs rc=4 (over budget), 0 FAIL; npm 173/173 fail 0
Final review: dispatched lr-final (session level), package review-483eb44..87fc9af.diff, includes T11 task review
Final review: lr-final ready-with-fixes, 0C/2I/7M: I1 runbook item 4 one-account + wrong expecteds/paths (T11 spec ❌); I2 repair_botless unguarded in watch_once; recommended: private gauth outcome/timeout replies, usage._get for T6 lookup; rest accepted (table in final-review.md)
Ruling: a /gauth code reply from another user is ignored silently and the window stays open (code + spec's test list say 'ignored'); the runbook is fixed to match the code, not the code to the runbook — if wrong, a small follow-up to reply/close.
Ruling: the two recommended final-review minors (private gauth outcome/timeout replies; usage._get for the T6 lookup) ride in the one fix wave, each is one small change — if wrong, a slightly larger fix diff to re-review.
Final fix: dispatched lr-fix (standard), FIX_BASE 87fc9af
Final fix: lr-fix DONE 5ec80a0..5f657b1 (I1, I2, 2 minors); board 1996 OK rc0; watch 80, ops 91
Final fix: re-review lr-rr: I1, I2, 2 minors ADDRESSED; no new breakage
Task 11: complete (commits e3b9f15..5f657b1, review clean after final fix wave)
Final review: clean after one fix wave (5ec80a0..5f657b1)
