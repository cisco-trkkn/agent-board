# SDD ledger — plan: docs/superpowers/plans/2026-11-16-discord-bridge-visibility.md
Spec: docs/superpowers/specs/2026-11-11-discord-bridge-visibility-design.md (reachable)
Preflight scan:
| pair/task | produces → consumes | finding |
| T1↔T5 | `tmux-ctl discord bridge start --project P` → ensure_discord_bridges argv | consistent |
| T1↔T2 | window cmd `node bridge.js <dir>` → bridge main(argv dir) | consistent |
| T2↔T3/T4 | outbox op keys, bridge-state keys (Global Constraints) | consistent; both read the same block |
| T3↔T4 | outbox_write/append_event/read_events/card_op_due → tick | consistent |
| T4↔T5 | tick(project, record, root, home, now), feed-state thread key → discord_sink refs | consistent |
| T3,T4,T5 share board/discord_feed.py | sequential (blockedBy chain) | no overlap in time |
| T6 | orchestrator patch + metadata.plan rule (P3) ↔ T4 reads metadata.plan | consistent |
| T7 | depends on T1,T2,T5,T6 outputs | consistent |
| each task self-consistency | tests named vs files listed | T5 Verify uses test_server*.py (exists: test_server_bind.py) ok; T6 install.sh is zsh → zsh -n ok |
Parallel: T1 (zsh), T2 (node), T3 (python) have disjoint files and no blockedBy → run concurrently.
Task 1: dispatched bv-zsh (sonnet, base d9fa638)
Task 2: dispatched bv-node (sonnet, base d9fa638)
Task 3: dispatched bv-py (sonnet, base d9fa638)
Task 3: green check ok (21 tests rc 0); review dispatched bv-rev (31e123b)
Task 4: dispatched bv-py (resume, sonnet)
Task 3: minor (deferred): waiting teammate renders idle (only working = busy)
Task 3: minor (deferred): zero-task-line overflow slice can cut `updated HH:MM`; untested
Task 3: minor (deferred): 2 more in task-3-review.md
Task 3: complete (commits 31e123b, review clean)
Task 2: green check ok (25 tests rc 0); review dispatched bv-rev (cd19db1)
Ruling: Task 2 fix round 1 also carries two review minors (throttled card file deleted before accept; raw e.message logged) — both break explicit Global Constraints, so they are spec gaps, not polish — cost if wrong: a few extra lines in one fix round.
Task 2: minor (deferred): null guild id possible in deep links; no live-pid check in main
Task 2: fix round 1 dispatched bv-node (no-status errors retried forever + 2 ruled items)
Ruling: Task 4 first-tick baseline (no `primed` → existing history marked seen, not emitted; in-progress spec_started/plan_written still emit) accepted — avoids replaying every old ledger line after a lost feed-state — cost if wrong: events between a state loss and the next tick are not posted.
Task 4: green check ok (41+43 tests rc 0); review dispatched bv-rev (ae36664)
Task 5: dispatched bv-py (resume, sonnet)
Task 4: ⚠️ task ids restart after a relay — confirmed real gap (this session recreated #1–#16); joins fix round
Task 4: fix round 1 dispatched bv-py (empty-first-read priming; poison event; list-dir-qualified keys)
Task 1: green check ok (37 checks ALL PASS rc 0); review dispatched bv-rev (a96fb7b)
Ruling: audit.jsonl ts is ISO 8601 UTC string (spec §10 `--since <ISO>`); python audit_append changed in Task 4 fix round — cost if wrong: none.
Task 6: dispatched bv-zsh (sonnet, mechanical task)
Task 2: fix round 1 green (30 tests rc 0, 6ddb5c8); re-review queued bv-rev
Task 1: minor (deferred): byte-identical check has a stray && outside check (bridge.json bytes unasserted; mtime covers)
Task 1: minor (deferred): 4 more in task-1-review.md
Task 1: complete (commits a96fb7b, review clean)
Task 2: fix round 1/5 (3 addressed, 1 new open — AbortError/timeout classified permanent; commits cd19db1..6ddb5c8)
Task 2: minor (deferred): transient flush error at shutdown moves held card files to failed/
Task 2: fix round 2 dispatched bv-node
Task 2: fix round 2 green (31 tests rc 0, 9bdd816); re-review dispatched bv-rev
Task 6: green check ok (4 greps =1, zsh -n rc 0, test_install ALL PASS); review queued bv-rev (25bf328)
Task 2: fix round 2/5 (1 addressed, 0 open; commits 6ddb5c8..9bdd816)
Task 2: complete (commits cd19db1..9bdd816, review clean)
Task 4: fix round 1 green (44+43 tests, b822444); re-review dispatched bv-rev
Task 6: review spec ❌ (state files not under ## State files; duplicate table in Feed events)
Ruling: Task 6 fix round 1 also corrects the feed example (thread_key form, `✓ <subject>` text) — a wrong schema example in ARCHITECTURE.md misleads PCEE authors — cost if wrong: none.
Task 6: minor (deferred): 300-char cut enforced by derive only, not append_event; 3 more in task-6-review.md
Task 6: fix round 1 dispatched bv-zsh
Task 6: fix round 1 green (fcf2e41, 21 lines → standard re-review); queued bv-rev
Task 4: fix round 1/5 (4 addressed, 0 open; commits ae36664..b822444)
Ruling: Task 4 fix round 2 — priming per task list (`primed_lists`) so a relay's recreated list and a session/team list-name flip don't repost history — real-state shape: this session recreated its queue after a relay — cost if wrong: a new list's genuinely new completions before first poll are not posted.
Task 4: minor (deferred): OSError from outbox_write (disk full) uncaught in tick
Task 4: fix round 2 queued to bv-py (after Task 5 commit)
Task 6: fix round 1/5 (2 addressed, 0 open; commits 25bf328..fcf2e41)
Task 6: minor (deferred): feed example uses the same id for refs.task and thread_key suffix; plan_done source listed as task list/ledger
Task 6: complete (commits 25bf328..fcf2e41, review clean)
Task 5: green check ok (24+14+1 tests rc 0, 5adc280); review dispatched bv-rev
Task 4: fix round 2 green (47+43, 8807793); re-review queued bv-rev
Task 1: regression found by full suite — added usage line shifts tmux-ctl's numbered help range (test_metrics_weekly HelpTest x2, test_metrics_backfill_privacy); reopened, fix dispatched bv-zsh
Task 5: minor (deferred): _ms_lock two-thread test is smoke only (no mutation failure under the GIL)
Ruling: Task 5 maps overview record name → discord project (no session_group field; adding one changes build_state's 17-field parse) — the real dirs (agent-board, interiors) match session names — cost if wrong: a grouped project with a differently named group gets no feed until a group field is added.
Task 4: fix round 2/5 (1 addressed, 0 open; commits b822444..8807793)
Task 4: minor (deferred): flip to a list holding the same in-progress Plan & run re-emits spec_started (second thread); untested
Task 4: complete (commits ae36664..8807793, review clean)
Task 5: ⚠️ group-name mapping not implemented — resolved by the existing record-name ruling
Task 5: minor (deferred): routine kinds appended to the feed file though never posted; feed file append-only, no rotation; 3 more in task-5-review.md
Task 5: complete (commits 5adc280, review clean)
Task 7: dispatched bv-py (resume, sonnet)
Task 7: e2e done (379f997): channel no-op, tick 2 = 0 ops, 200 outbox drained 0 failed, real dirs unchanged; found 2 real defects
Ruling: outbox cap never drops `thread`/`archive` ops (a dropped thread op orphans every later post of that spec) — cost if wrong: cap can exceed 200 by a few structural ops.
Ruling: card shows only the running spec's tasks: feed-state `spec_floor` = highest task id when the spec started; tasks above it shown; no floor → only non-completed — real card showed task #2 from the previous spec — cost if wrong: a plan task created with a lower id than the floor is hidden.
Task 4: fix round 3 dispatched bv-py (e2e findings; then Task 7 note refresh)
Task 1: fix round 1 green (46c61a1; metrics 266 OK, Task 1 verify ALL PASS); re-review dispatched bv-rev
Task 4: fix round 3 green (50+43 tests; d73ad79; note 784df85) — real card now empty (floor 24 when first seen mid-spec)
Ruling: no recorded floor + metadata.plan → card shows the n highest-id non-Plan&run tasks, n = plan's task count, then pins that floor — cost if wrong: extra fix-wave tasks push the oldest plan task off the card.
Task 4: fix round 4 dispatched bv-py
Task 1: fix round 1/5 (1 addressed, 0 open; commits a96fb7b..46c61a1)
Task 1: minor (deferred): tmux-ctl help range is a hand-bumped constant (sed -n '2,51p')
Task 1: complete (commits a96fb7b..46c61a1, review clean)
Task 4: fix round 4 green (53+43; ad600e5; note 5bacb2d); real card shows #17–#24; re-review r3+r4 + Task 7 review dispatched bv-rev
Task 4: fix rounds 3–4/5 (3 addressed, 0 open; commits d73ad79, ad600e5)
Task 4: minor (deferred): floor too low if plan tasks not created yet when first seen; None floor hides spec's own completed tasks; no spec running → card lists all non-completed lead tasks
Task 7: minor (deferred): card op never drained through the bridge in e2e (cap dropped it among 413 review posts; edit 0 pin 0); .env "never read" wording (hashed); before/after md5 sets not both pasted; harness scripts only in scratchpad
Task 7: complete (commits 379f997..5bacb2d, review clean)
Final review: dispatched bv-final (session model, 71675a8..5bacb2d, final-review-brief.md)
Final review: with fixes (0 C, 3 I) — bridge stop not sticky; status lacks outbox backlog; orchestrator remote rule contradiction; final-review.md
Ruling: `bridge stop` writes bridge.stopped; keeper calls `bridge start --keeper` which honours it; a typed `bridge start` clears it — cost if wrong: a user who stops the bridge must start it by hand.
Ruling: lead posts completions/agent-waiting on Discord only when no bridge is running; otherwise the bridge does — cost if wrong: duplicate or missing notices while a bridge is flapping.
Final fix wave: dispatched bv-fix (sonnet, base 5bacb2d, fix-wave-brief.md)
User (Discord 21:57Z): interiors bridge wanted too (answer 1) — merge-gate item settled
Lead handoff: new lead resumed; bv-fix respawned (sonnet, resume note bv-fix-resume.md)
Final fix wave: green (ef4c326; discord zsh ALL PASS, board 1255 OK, npm 31/31); re-review dispatched bv-rr (sonnet)
Final fix wave: re-review clean (3/3 addressed, 0 new C/I; fix-wave-rereview.md; commits 5bacb2d..ef4c326)
Final: minor (deferred): bridge stop on a project with no dir fails with a shell error from the marker redirect instead of "bridge: not running"
