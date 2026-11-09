# SDD ledger — plan: docs/superpowers/plans/2026-11-09-lead-named-agents.md
Spec: docs/superpowers/specs/2026-11-09-lead-named-agents-design.md (read)
Preflight:
| pair/task | produces → consumes | found |
| T1↔T2 | T1 creates scripts/agent-name-guard.sh (755) → T2 registers it, checks -x | consistent |
| T2↔T4 | both append checks to tools/tests/test_plugin.zsh at different anchors (T2 after sdd registration PY, T4 after queue lead-rules check) | serial (T4 blockedBy chain), no conflict |
| T1,T2,T3,T4→T5 | T5 runs the real lead using all four | consistent |
| T1 self | test code ↔ script code: run once by plan author, ALL PASS, 4 mutations fail as stated | ok |
| T2 self | checks ↔ edits: hooks.json line style, description string match | ok |
| T3 self | diff dry-run clean against ee41ea4; 2 mutations fail as stated (run by author) | ok |
| T4 self | grep strings ↔ bullet text identical | ok |
| T5 self | frontier-style goal/AC, no steps; Verify counts 3 sections | ok |
No rulings needed.
BASE ee41ea4
impl10 dispatched (Task 1, haiku)
Task 1: green check ok; rev10 dispatched (review ee41ea4..0056475)
Task 1: minor (deferred): early-allow cat ignores closed stdin (fine); test sets AGENT_NAME_GUARD empty not unset
Task 1: minor (deferred): unnamed fork covered only via the name path
Task 1: complete (commits ee41ea4..0056475, review clean)
Task 2: green check ok; rev10 review 0056475..c652e5a
Task 2: minor (deferred): INSTALL.md agent-name-guard parenthetical long ("lead only" inside every-Claude sentence)
Task 2: complete (commits 0056475..c652e5a, review clean)
Task 3: green check ok (45b176d); batched with Task 4
Task 4: green check ok (dc3ff03); Batch 3-4: rev10 review c652e5a..dc3ff03
Batch 3-4: reviewed together (2 tasks)
Task 3: minor (deferred): processes the lead's Bash starts directly (e.g. a hand-run claude) inherit the marker; Task 5 checks teammates
Task 3: complete (commits c652e5a..45b176d, review clean)
Task 4: complete (commits 45b176d..dc3ff03, review clean)
Task 5: e2e10 dispatched (sonnet)
Task 5: green check ok (14d4504); rev10 review dc3ff03..14d4504
Ruling: Task 5 ✦ window shown as a teammate pane on the -f /dev/null scratch server (no agent-board tmux hooks there) — ✦ placement is unchanged tmux-teammate-window behaviour, and this session's own named teammates opened ✦ windows on the live server — costs if wrong: a named-agent window regression would go unseen until a live session
Task 5: minor (deferred): predicate same shape as hook (independent code, not idea)
Task 5: minor (deferred): predicate denies non-object tool_input where guard allows; 0 such cases; doc silent
Task 5: complete (commits dc3ff03..14d4504, review clean)
Final: final10 dispatched (session level) 31505e6..14d4504
Final: With fixes, 0/0/3 (final-review.md)
Ruling: final minor 1 (hook "after" order has no runtime effect; hooks run in parallel) parked — both guards are independent and either exit 2 blocks — costs if wrong: a misleading test name only
Ruling: final minor 2 (named isolation:"remote" agent passes but opens no window) fixed now — user decision "never run agents hidden in the background, no exemptions" covers it though the spec lists only name/fork — costs if wrong: a remote agent the user wanted is refused until AGENT_NAME_GUARD=0
Ruling: final minor 3 (.tasks.json statuses) committed with the ledger archive — lead bookkeeping file — costs if wrong: nothing
Final fix: fix10 dispatched (haiku), FIX_BASE 14d4504
Final fix: re-review ADDRESSED (14d4504..75e7c45), no new breakage
Ruling: residual doc touch-up (INSTALL.md:23, orchestrator.md:14, guard header still say "no name, or a fork", not remote) parked — no second fix wave; the deny reason text names remote — costs if wrong: docs understate the guard by one case
