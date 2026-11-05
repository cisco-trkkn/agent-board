# SDD ledger — plan: docs/superpowers/plans/2026-11-04-tasks-window.md
Preflight scan:
| pair/task | shared | finding |
| T1-T3 | view task dict (tier, blockedBy) | T1 produces keys T3 consumes — ok, T3 blockedBy T1 |
| T2-T3 | timing state schema (tasks.since/started, events) | T2 defines it, T3 reads — ok, T3 blockedBy T2 |
| T2-T4 | update/save/path_for/load | T4 calls them as defined — ok |
| T3-T4 | board/taskwin.py | both write it; T4 blockedBy T3 — serial ok |
| T4-T5 | taskwin.py watch CLI flags --session --root | T5 layout starts `watch --session --root` matching T4 CLI — ok |
| T5-T6 | none (T6 docs only) | disjoint |
| T1 self | tests vs code | author-run RED errors=4 → GREEN OK, overview_api OK |
| T2 self | tests vs code | author-run RED ModuleNotFound → GREEN OK |
| T3 self | frontier, no steps | AC consistent with Global Constraints glyphs/colours |
| T4 self | e2e not test_ prefixed (stays out of run-all) | ok |
| T5 self | test vs code | author-run RED 7 FAILED → GREEN ALL PASS; test_layout + test_teammate_window green |
| T6 self | AC wording on test_plugin | corrected before commit to the real rule — ok |
Ruling: T1, T2 and T6 run in parallel (disjoint files, no blockedBy) — cost if wrong: one rebase-free re-order
BASE 69c0144
Task 1: dispatched tierdoc (haiku/low); Task 2: dispatched statewriter (sonnet/medium); Task 6: tierdoc after T1
Task 2: green check ok (RED errors=1, GREEN OK rc=0, 4 mutations caught); review dispatched twrev (sonnet/medium) on 69c0144..44a99af
Task 1: green check ok (RED errors=4, GREEN 31 OK); held for batched mechanical review with Task 6
Task 2: complete (commits 69c0144..44a99af, review clean)
Task 2: minor (deferred): save catches only OSError (TypeError on non-serialisable)
Task 2: minor (deferred): wrong-shape JSON ({"tasks":{"1":5}}, event at:"x") makes update raise
Task 2: minor (deferred): empty list then all-completed fires plan_done without a seen not-done state
Task 2: minor (deferred): fixed .tmp name shared by concurrent writers; leftover .tmp on failed write
Task 2: minor (deferred): reopened task keeps stale done — Task 3 must read done only for completed tasks
Task 2: minor (deferred): no test for no leftover .tmp
Task 1: batch closed early (Task 3 next is non-mechanical); review dispatched twrev on 44a99af..9ec0571
Task 6: green check ok (test_plugin ALL PASS rc=0); review queued for twrev after Task 1
Task 1: complete (commits 44a99af..9ec0571, review clean)
Task 1: minor (deferred): metadata modelTier "" wins over a real fence tier, unpinned
Task 1: minor (deferred): CRLF description gives "" tier
Task 1: minor (deferred): non-str modelTier and non-list blockedBy untested
Task 3: dispatched painter (fable, frontier), BASE cc53892; carries T2 minor: read done only for completed tasks
Task 6: complete (commits 9ec0571..cc53892, review clean)
Task 6: minor (deferred): docs describe Tasks 3-5 behaviour — final review re-checks each sentence against the code (merge-gate)
Task 6: minor (deferred): ARCHITECTURE says $TC_STATE/taskwin, plan says state_dir() — equivalent by default
Task 3: Ruling: tier badge maps mechanical→haiku, standard→sonnet, frontier→fable (model names also accepted) — plans store tiers, not model names, so the plan's map showed no badge — cost if wrong: a 3-line dict to drop
Task 3: DONE_WITH_CONCERNS ad91d78 (36 tests OK rc=0); tier map ruling sent after commit — pending as fix before review; NO_COLOR has no critical-path marker (concern)
Task 3: tier map fix 5de443c (37 tests OK rc=0); awaiting task review
Task 3: review dispatched twrev (sonnet/medium) on cc53892..5de443c (new session)
Task 3: review ❌ spec (1 Important: graph→list fallback when cards <16 cells, unruled, untested), quality Approved
Task 3: Ruling: at width ≥80 the graph stays; when columns don't fit, all-completed columns collapse into the done summary first (freeing width), list fallback only if unfinished columns still can't fit at CARD_MIN; both pinned by tests — spec says graph ≥80 and "collapse completed first"; serial plans of 7+ are common — cost if wrong: a list layout the user preferred, one revert
Task 3: minor (deferred): list layout drops surplus unfinished tasks without "+N more"
Task 3: minor (deferred): duplicated cells/_cw helpers
Task 3: minor (deferred): redundant min/max at taskwin.py:555
Task 3: minor (deferred): critical path colour-only (no NO_COLOR marker)
Task 3: minor (deferred): sparkle line shows for a deleted task
Task 3: fix round 1 dispatched painter (fable, frontier, fresh session), FIX_BASE 5de443c
Task 3: minor (deferred): human merge-gate — light-terminal look and 🔒/◌ alignment in the user font unverified
Task 3: fix 26e17aa green (RED failures=2 → 40 OK rc=0); re-review sent twrev on 5de443c..26e17aa; painter concern: width collapse lowest-depth-first, height tallest-first, kept
Task 3: fix round 1/5 (1 addressed, 0 open — graph→list fallback; commits 5de443c..26e17aa)
Task 3: complete (commits cc53892..26e17aa, review clean)
Task 4: dispatched statewriter (sonnet/medium), BASE 26e17aa
Task 4: DONE_WITH_CONCERNS 37585da; green check ok (RED failures=1 errors=4 → 5 OK rc=0; e2e ALL PASS rc=0; live render rc=0, no taskwin/ created)
Task 4: Ruling: e2e copies the newest real task dir with 5–13 tasks (not ≥5) — the newest ≥5 dir (14 tasks, 9 roots) falls back to the list at 50 rows so the `╭` check cannot pass; the acceptance check stays real state — cost if wrong: e2e misses a large-plan regression
Task 4: minor (deferred): a real 14-task plan with 9 roots renders as the list at 120×50 — final review: is the tall-root-column fallback acceptable UX
Task 4: review dispatched twrev on 26e17aa..37585da
Task 4: complete (commits 26e17aa..37585da, review clean)
Task 4: minor (deferred): _draw error line not clipped to width (500-char error wraps)
Task 4: minor (deferred): render makes an unused lead_session tmux call
Task 4: minor (deferred): get_terminal_size prefers $COLUMNS/$LINES over the tty
Task 4: minor (deferred): no subprocess test sends a real signal (reviewer did: SIGTERM/SIGHUP rc=0, cursor restored)
Task 4: minor (deferred): e2e depends on ~/.claude/tasks holding a 5–13-task dir
Task 4: minor (deferred): Ctrl-C on a real tty untested — final review checks via scratch tmux send-keys C-c
Task 5: dispatched statewriter (sonnet/medium), BASE 37585da
Task 5: green check ok (RED 7 FAILED → 8 ALL PASS rc=0; run-all rc=0); review dispatched twrev on 37585da..9aca91c
Task 5: complete (commits 37585da..9aca91c, review clean)
Task 5: minor (deferred): has_win tasks guards on name only — a user window named tasks suppresses ours
Task 5: minor (deferred): no remain-on-exit — window vanishes silently if taskwin.py dies
Task 5: minor (deferred): test never uses a session/root with spaces or quotes (reviewer probed it by hand: ok)
Task 5: minor (deferred): test checks --session in start command but not --root
Task 5: minor (deferred): human gate after merge — tasks right after claude in a real dev session, new teammate after it
Final review: dispatched finalrev (session level) on 69c0144..9aca91c
Final review: Ready to merge yes; 0 Critical, 0 Important, 6 Minor; Ctrl-C PASS; no false doc sentence; 28 deferred minors triaged OK
Final review: Ruling: one fix wave for Minors 1 (lead "" resets state), 2 (layout header names tasks), 5 (session-closed removes taskwin json) — real, small, in files the branch owns or names in its docs — cost if wrong: one revertable commit
Final review: Ruling: Minors 3 (shared edge bus), 4 (TIER_MODEL hard-coded), 6 (only first concurrent done sparkles) left as follow-ups filed as ideas — UX/config work beyond the spec's must-haves — cost if wrong: a misleading badge where routing.json differs from the default
Final fix: dispatched statewriter (sonnet/medium), FIX_BASE 9aca91c
Final fix: 7cfe6f3 green (RED 2 failing → state+cli 13 OK, session_closed/tasks_window/layout ALL PASS rc=0); re-review sent twrev on 9aca91c..7cfe6f3
Final fix: re-review all 3 ADDRESSED, no new breakage
Final fix: minor (deferred): leftover .json.tmp and empty taskwin/ dir not removed on session close; session-closed name regex and path_for rule not tied in code
Final review: clean — plan complete
