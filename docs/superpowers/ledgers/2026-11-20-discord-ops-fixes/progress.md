# SDD ledger — plan: docs/superpowers/plans/2026-11-20-discord-ops-fixes.md
Spec: docs/superpowers/specs/2026-11-19-discord-ops-fixes-design.md · branch feat/discord-ops-fixes · base 926040c
## Pre-flight scan
| pair / task | produces → consumes | found |
|---|---|---|
| T2/T5/T8 bridge.js | T2 createCard/doCard; T5 opEdit reply; T8 opPost select + onOpsInteraction | disjoint functions; T5 and T8 may both extend fake-client (msg.reply / select) — sequential, ok |
| T3/T4/T6/T7/T8 discord_ops.py | T3 tick presence; T4 handle_event st + handle_event_locked; T6 ideas branch; T7 tick specs; T8 /queue branch | T8 consumes T7's specs {key,label,summary}: matches; T8 must branch before _known(project) (None project → "unknown project" today) |
| T5/T8 discord_feed._check | T5 edit.reply; T8 post.select | disjoint fields, ok |
| T6/T8 commands.js | T6 payload(ops) drops ideas; T8 /queue optional in ops | disjoint, ok |
| T7/T9/T10 metadata.branch | T9 rule writes it; T7 reads; T10 checks #18 (written by lead) | consistent |
| T3/T4 discord_feed/controls tests | separate test files except test_discord_ops shared, sequential | ok |
| each task self-consistency T1-T11 | tests vs code vs files | T1 jq snippet run by author (4 cases ok); others prose-specified standard; no contradictions found |
| rubric conflicts | none mandated | none |
Ruling: T8 handles the no-project /queue slash before the _known(project) check in handle_event — the spec says the board answers it with one post per project; today's flow would audit "unknown project" — cost if wrong: one reordered branch.
Note (gate #70, outside this plan): #55→#18 boundary: handoff Skill 03:39:05Z, 5 s after TaskUpdate #55 completed 03:39:00Z, no user msg between; lineage ts 03:39:58Z — pass. Nudge text absent after the TaskUpdate: session 3016db14 started 23:59Z before the merge (03:38Z) put the hook into the live hooks.json; a dry run of the hook on this session's folder prints the nudge. Re-check criterion 3 at the #18→#19 boundary.
Task 1: dispatched impl-t1 (haiku, effort-low), base 926040c
Task 1: report DONE 6678ffc, verify green; review dispatched rev-t1 (sonnet)
Task 2: dispatched impl-t2 (sonnet), base 6678ffc (parallel to Task 1 review; disjoint files)
Task 1: minor (deferred): jq `//` also maps ackReaction false to 👀 (spec filter as written)
Task 1: complete (commits 926040c..6678ffc, review clean)
Task 3: dispatched impl-t3 (sonnet), base 6678ffc (parallel to Task 2; disjoint files)
Task 2: report DONE 9461375, verify green; review dispatched rev-t2 (sonnet)
Task 2: complete (commits 6678ffc..9461375, review clean)
Task 3: report DONE d0121e3, verify green; 3 existing tests reseeded with bridge presence (spec behaviour)
Task 3: review dispatched rev-t3 (sonnet)
Task 9: dispatched impl-t9 (haiku, effort-low), base d0121e3 (docs only, disjoint)
Task 3: complete (commits 9461375..d0121e3, review clean)
Task 4: dispatched impl-t4 (sonnet), base d0121e3
Task 9: report DONE 083bcc4, verify green; review dispatched rev-t9 (sonnet)
Task 4: report DONE a906dea, verify green
Task 4: review dispatched rev-t4 (sonnet)
Task 9: review ❌ 1 Important (State of the work bullet lacks the fields); fix round 1 sent to impl-t9
Task 4: minor (deferred): every forwarded controls-path slash/modal/read runs under the ops flock, so a slow /gauth could delay the ops consume tick
Task 4: minor (deferred): unconfigured fallback of handle_event_locked untested
Task 4: complete (commits 083bcc4..a906dea, review clean; lead re-ran test_discord_*: 491 OK)
Task 9: fix round 1/5 (small, mechanical re-review) dispatched rerev-t9 (haiku); commits a906dea..f4b0f86
Task 5: dispatched impl-t5 (sonnet), base f4b0f86
Task 9: fix round 1/5 (small, mechanical re-review) (1 addressed, 0 open; commits a906dea..f4b0f86)
Task 9: complete (commits d0121e3..f4b0f86, review clean after 1 round)
Task 5: report DONE 1476db5, verify green (py OK, js 184/0)
Task 5: review dispatched rev-t5 (sonnet)
Task 6: dispatched impl-t6 (sonnet), base 1476db5 (parallel to Task 5 review; disjoint files)
Task 5: minor (deferred): pre-action _check probe uses a worst-case drop line (shape-only check)
Task 5: minor (deferred): body cut counts code points (len) while the bridge slices UTF-16 units; emoji-heavy body near 2000 could be sliced by the bridge
Task 5: complete (commits f4b0f86..1476db5, review clean)
Task 6: report DONE 01c93f3, verify green (py 502 OK, js 184/0); also edited test_discord_ideas_wiring.py
Task 6: review dispatched rev-t6 (sonnet)
Task 6: complete (commits 1476db5..01c93f3, review clean)
Task 7: dispatched impl-t7 (sonnet), base 01c93f3
Task 7: report DONE fbe2a19, verify green (510 OK)
Task 7: review dispatched rev-t7 (sonnet)
Task 7: review ❌ 1 Important (unhashable status raises) + 4 Minor
Ruling: Task 7 Minor 1 (empty label on no-path subject) and Minor 2 (path escapes root) enter the fix round — Task 8 posts the label as a Discord select option label, which must be non-empty; relative_to is cheap — cost if wrong: a few lines
Task 7: minor (deferred): title over ~1800 chars cut without closing **
Task 7: fix round 1 sent to impl-t7 (status key, try/except, label fallback, root containment)
Task 7: ⚠️ resolved by lead: lead_info root is set live by server.py:540 (relay.session_root)
Task 7: fix round 1 committed f44a687; scoped re-review (standard) not yet dispatched — FIX_BASE fbe2a19
Task 7: fix round 1 re-review (standard) dispatched rerev-t7 (sonnet); diff fbe2a19..f44a687
Task 7: fix round 1/5 (4 addressed, 0 open; commits fbe2a19..f44a687)
Task 7: minor (deferred): label "task None" when a task dict has no id
Task 7: complete (commits 01c93f3..f44a687, review clean after 1 round)
Task 8: dispatched impl-t8 (sonnet), base f44a687
Task 8: report DONE e811a04, verify green (py OK, js 188/0)
Task 8: review dispatched rev-t8 (sonnet)
Task 8: minor (deferred): latent KeyError in _queue_cards on a malformed spec entry (views.json specs written by our own tick)
Task 8: minor (deferred): two brief-named mutations not run (only the opPost one)
Task 8: minor (deferred): select tests live in ops.test.js, not bridge.test.js
Task 8: complete (commits f44a687..e811a04, review clean)
Task 10: dispatched test-t10 (sonnet), head e811a04
Final review: dispatched rev-final (session level), range e8fecf3..e811a04 (parallel to Task 10, read-only)
Final review: Ready to merge, 0 C / 0 I / 4 Minor; all 11 deferred minors fine to defer
Ruling: final Minors 1 (/queue cards for lead-less projects) and 2 (no real-tick chain test) go into the one final fix wave; Minors 3 (card unfenced) and 4 (presence ops pile up while a bridge is down) deferred — 1 deviates from spec §7 "one card per lead" and would show at gate #81, and it came from the lead's Decided "keys of views.queue"; 2 is cheap — cost if wrong: one small commit and a re-review
Final fix: dispatch held until test-t10's full suite finishes (shared working tree)
Task 10: full suite ALL PASS 178 jobs 8m39s rc=4 (on e811a04); report pending from test-t10
Final fix: dispatched impl-final (sonnet), base e811a04
Task 10: complete (no commits; suite ALL PASS rc=4, real-state checks pass, 0 own writes; 25 live-writer mtimes during the suite)
Final fix: report DONE 92908cb, verify green (py OK, js 189/0); scoped re-review dispatched rerev-final (sonnet)
Final fix: re-review clean (2 addressed, 0 open; commits e811a04..92908cb); final Minors 3, 4 deferred
