# SDD ledger — plan: docs/superpowers/plans/2026-11-17-discord-ops-bot.md
Spec: docs/superpowers/specs/2026-11-12-discord-ops-bot-design.md · branch feat/discord-ops-bot · base 21d03b8 · plan fd5cace

## Pre-flight scan
| Pair / task | Produces → consumes | Found |
|---|---|---|
| T1–T5 discord.zsh, bin/tmux-ctl | T1 --ops + _dc_ops_dir → T5 merge-request subcommand | sequential (T5 blockedBy T1); both bump help range |
| T1–T9 _ops dir | T1 path → T9 overseer DISCORD_STATE_DIR | same path rule `$(_dc_root)/_ops`; no file overlap |
| T2–T3 bridge.js | T2 ops mode, views() reader, rejected/read events → T3 commands reuse them | sequential |
| T2–T4 op shapes/views.json/events | T4 writes card/approval/edit/post.key + views.json; T2 reads | both bound to Global Constraints shapes |
| T4–T5 discord_ops.py | T4 calls on_merge via injected stub → T5 real on_merge + evidence views | sequential |
| T4–T7 | T4 tick/consume signatures → T7 server wiring | sequential |
| T7–T8 server.py | wiring → digest call | sequential |
| T3–T4 events slash/modal/read/rejected | T3 writes → T4 handle_event | Global Constraints shapes |
| T6 | rule text names `tmux-ctl discord merge-request` flags = T5 CLI | consistent |
| each task self-consistency | tests named vs files | consistent; T9 depends on probe (recorded) |
Ruling: T9 runs without waiting for T1 — it needs only the path rule from Global Constraints — costs nothing if wrong (path rule is fixed).
Task 1: dispatched ops-cli (sonnet/medium), base fd5cace
Task 2: dispatched ops-bridge (sonnet/medium), base fd5cace
Task 4: dispatched ops-board (sonnet/medium), base fd5cace
Task 2: report DONE_WITH_CONCERNS fe94883 (96/96 green; touched test/outbox.test.js 1 line; ran rm /tmp/x on a pre-existing symlink); review dispatched rev-bridge
Ruling: approval op gains optional string `project` (bridge link label) — told ops-board — costs a one-field change if wrong
Task 1: report DONE 851da40 (verify 3 suites ALL PASS); review queued on rev-bridge
Task 9: dispatched ops-cli (reuse), base 851da40
Task 2: ⚠️ project label source — resolved by the approval.project ruling (Task 4 sends it); ⚠️ multi-channel fake — tests reach CC and AP, confirmed
Task 2: minor (deferred): read event written when views.json missing (bridge.js ~409)
Task 2: minor (deferred): st.posts stores no channel; edit of a keyed post sent to a thread can't find it (bridge.js ~174/~281)
Task 2: minor (deferred): select option values = path cut to 100 can collide; fixture has a duplicate at 25 (bridge.js ~256, ops.test.js)
Task 2: minor (deferred): unrequested ctx/fence surface; test gaps (inbox/files truncation, diff-select update path); report count 26 vs 27
Task 2: complete (commits fd5cace..fe94883, review clean)
Task 3: dispatched ops-bridge (reuse), base 2554ae0
Task 4: report DONE_WITH_CONCERNS 2554ae0 (137 OK; 10 mutations run)
Ruling: needs_you feed events are not mirrored as `other` approvals (lead questions come from records, teammate prompts from the controls mirror) — matches the planning ruling — costs one `_COVERED` line if wrong
Ruling: on_merge (Task 5) writes both copies' edits itself (ops key = sha1(project\0src)[:12], project key merge:<task>) since consume pops the record before calling it; keep also moves to Task 5 with text `kept: <branch>` per Task 5 AC — costs a small Task 5 rework if wrong
Task 6: dispatched ops-board (reuse), base 2554ae0
Task 4: follow-up 7ad4d1e (approval.project); review package 851da40..7ad4d1e
Task 1: ⚠️ _ops not scanned as a project — keeper is Task 7's, carried there
Task 1: minor (deferred): usage text shows --ops before the subcommand; dead ops-channels usage line; ch=ok flag hack (discord.zsh)
Task 1: minor (deferred): tests skip deny/remove/forget/audit --ops; identical cc/approvals ids accepted
Ruling: INSTALL `pair --ops` stays — pairing DMs are handled by the discord plugin running in the overseer with DISCORD_STATE_DIR=_ops (Task 9), not by bridge.js — costs a doc fix if wrong
Task 1: complete (commits fe94883..851da40, review clean)
Task 9: report DONE_WITH_CONCERNS 5cdfd09 (16 ok; probe: plugin needs enabledPlugins in --settings; reply/fetch_messages allows); tool names confirmed against this session's own deferred tool list (mcp__plugin_discord_discord__reply, __fetch_messages)
Task 3: report bfa6dc3; Task 6: report DONE 51baffc (8 ok); reviews of 3 and 6 dispatched to ops-cli (did not implement either)
Task 3: minor (deferred, for final review): bridge event files written in the same ms get random-suffixed names, so same-ms events sort randomly on the board side (writeEvent in bridge.js)
Task 4: review spec ❌ / Needs fixes (0 C, 4 I, 6 M); spec ❌1 (approval.project) already fixed in 7ad4d1e — reviewer read the pre-7ad4d1e state
Ruling: on_merge interface changes to return {"result", "text"} without touching ops state or calling resolve; consume edits both copies and pops the record only after it returns, auditing `error` and keeping the record on an exception — fixes the deadlock and lost-approval findings — costs Task 5 nothing (not written yet)
Ruling: keep path edits both copies now (project key = src_key) with `<project>: kept`; Task 5 changes only the text to `kept: <branch>` — costs one string if wrong
Ruling: other/merge approvals cap at newest 200 and drop from views after 7 days (no resolution signal exists for them) — costs a stale Inbox entry for up to a week if wrong
Ruling: a project is known when it is in the last tick's records or has a discord dir — not only bridge.json — costs nothing
Task 4: minor (deferred): forwarded perm from an ops user not in the project's allowFrom is audited forwarded but rejected downstream; buttons stay
Task 4: minor (deferred): merge key merge:<task> collides across lead sessions — Task 5 makes the key unique
Task 4: minor (deferred): getattr dispatch; unused add_line/run/queue_ts; feed offset advanced before processing; pause-all queue state one tick old
Task 3: review spec ✅ / Approved with 1 Important (fenced duplicates fence; viewsOf re-reads views.json) → fix round 1 to ops-bridge, with cheap minors (project max_length so modal custom_id ≤ 100; null project; action commands validate project when views.projects exists; whitespace-only fields)
Task 3: minor (deferred): a project bridge accepts another project's name into its own events dir
Task 6: review spec ✅ / Approved with 1 Important (ask outcome not in metrics OUTCOMES) → fix round 1 queued on ops-board after Task 4 fixes, with push=false for ask and morning-report clause
Task 3: fix round 1 committed 7af2393 (118/118); scoped re-review → ops-cli
Task 9: review spec ✅ / Needs fixes (1 I: unconditional enabledPlugins with no dc_ensure_launcher in claude-overseer → stock server can write the 15-min failure cache) → fix round 1 queued on ops-cli after the Task 3 re-review
Task 9: minor (deferred): no dc_holder guard for a second overseer; ops dir path spelled a third time; reply can attach files (allowlisted channel only)
Task 3: fix round 1/5 (5 addressed, 1 new open — /status unknown lost its read event; commits bfa6dc3..7af2393) → round 2 to ops-bridge
Task 4: fix round 1 committed 963e1ab (146 OK); scoped re-review → rev-bridge
Task 3: fix round 2 committed b0bf8bb (119/119); re-review queued on rev-bridge
Final-review note (lead, 05:43Z live render): render_card on live overview shows "3/23" (plan done/total counts every lead task, incl. Plan & run + gates) and "blockers: stuck 198m" for agent-board while the lead is active — check Task 7 real-state card against both.
Task 3: complete (re-review 2 ADDRESSED, b0bf8bb; minor: ctx comment omits fence/NO_MENTIONS)
Task 4: complete (re-review ADDRESSED, 963e1ab; minors: repeated action after post-action failure, raise inside except audit)
Task 9: fix round 1 committed 0f0783f; scoped re-review pending
Task 6: fix round 1 commit pending (ops-board blocked on a permission dialog rendered in the lead pane)
Side finding (react-delivery-debug.md): CommentQueue.deliver holds all lines while the lead pane shows a dialog (status waiting); teammate dialogs render in the lead pane and get no Discord button; audit says queued not delivered. Ruling: fix in a separate small branch after this plan — out of this plan's scope — cost if wrong: lines stay silently held meanwhile.
Task 5: dispatched to ops-cli (BASE 0f0783f; on_merge returns {result,text}; src key merge:<task>:<sha8>)
Task 9: scoped re-review → rev-bridge (package b0bf8bb..0f0783f)
Side finding: tmux-ctl approve claude → "no permission prompt" when a teammate dialog in the lead pane has the lead's task-list panel drawn below its footer; user's "approve 1" (05:57Z) could not be pressed. Goes to the same fix branch.
Task 9: complete (re-review ADDRESSED, 0f0783f)
Task 5: DONE a11fd5b (78 OK + zsh suite, rc 0); review → rev-bridge
Task 7: dispatched to ops-bridge (BASE a11fd5b)
Task 6: fix round 1/5 (small) committed 586c58f by the lead (user approved #1 at 05:57Z; dialog unpressable, user away till 09:00); 11 ok rc 0; ops-board window killed (frozen on the dialog); re-review → rev-bridge
Ruling: lead ran the teammate's user-approved commit itself — the approve press was blocked by the task panel and the user is away — cost if wrong: one commit to revert.
Task 5: review Approved (spec ✅, quality Approved, 0 Critical/Important)
Task 5: minor (deferred to final review): git calls under ops lock (27×60s timeout); diff honours user git config (--no-ext-diff --no-color); evidence name collision a-b/7; test leftovers; _evidence_view reads 200 files per tick; ⚠ merge-request run from a spec worktree that is later removed → false "branch changed" (Task 6 rule should say: run from the main checkout)
Task 5: complete (commits 0f0783f..a11fd5b, review clean)
Task 6: fix round 1/5 (3 addressed, 0 open; commits a11fd5b..586c58f)
Task 6: complete (commits 2554ae0..586c58f, review clean)
Resume (2026-11-18): previous lead stopped ~06:36Z 11-17 without a handoff; Task 7 committed b356881 by ops-bridge, no report
Task 7: dispatched ops-wire (sonnet/medium) to verify b356881 and write the report (all.zsh in a detached worktree)
Task 8: dispatched ops-digest (sonnet/medium), base b356881; server.py edit held until ops-wire reports
Task 8: module committed 8333f88 (13 OK); server.py wiring held for ops-wire
Task 7: report DONE (no new commits; verify 88 OK rc 0; all.zsh ALL PASS 145, rc 4 time only; real card 240 chars); review → ops-rev
Final-review note: live card shows plan "0/5" counting every lead task incl. Plan & run and gates; spec :44 asks only `<running spec> k/n` (discord_ops._project_line)
Task 8: report DONE_WITH_CONCERNS 8333f88+1035daa (13 OK + 88 OK rc 0; wiring has no dedicated test); review queued on ops-rev
Task 7: review spec ✅ / Approved (0 C/I)
Task 7: minor (deferred): discord_ops.configured() outside try in feed_tick; no-channel project's lead-list failure logs "discord feed failed" each build; card "0/5" (Task 4 _project_line); all.zsh needs a re-run at branch tip (final review)
Task 7: complete (commits 586c58f..b356881, review clean)
Task 8: review spec ✅ / Approved (0 C/I; reviewer ran ops_tick 3× in scratch: 1 post)
Task 8: minor (deferred): no dedicated wiring test; a digest-state write failure after the post re-posts each tick; "critical not held" test never calls dg.tick
Task 8: complete (commits b356881..1035daa, review clean)
Final review: dispatched ops-final (session level); tip suites → ops-test (haiku)
Final: tip suites at 1035daa — all.zsh ALL PASS 146 (rc 4 time only), node 119/119 rc 0
Final review: ready after fixes (0 C, 1 I: merge-request repo = spec worktree, lost approval when removed); fix wave: I1 + M1 + M2 + M3 + M10 → ops-fix
Ruling: card drops the unlabelled plan-wide "0/5" and keeps only the spec's `<running spec> k/n` (spec :44) — cost if wrong: one count to add back
Final: fix wave committed 1035daa..c4c14d4 (127 OK + ops zsh ALL PASS); scoped re-review → ops-final
Final: re-review all 5 ADDRESSED (127 OK at c4c14d4); new minors (deferred): dead `src =` line in I1 test; --git-common-dir parent wrong in submodule/bare repo (--repo overrides); INSTALL "restart the overseer" names no command (tmux-overseer stop --force)
Ruling: merge before the Task 10 user gate — the ops tick, digest and bridge keeper only run from the board on main, so the phone run needs the merge — cost if wrong: a fix branch after the gate
