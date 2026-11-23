# SDD ledger — plan: docs/superpowers/plans/2026-11-21-execution-analytics-part2.md
Spec: docs/superpowers/specs/2026-11-12-execution-analytics-design.md §4 (part 2). Branch spec-execution-analytics-part2, base f1d070e, plan 9f74fcf. Native tasks #88-#94 = plan 1-7.
Preflight scan:
| pair/task | produces → consumes | found |
| T1↔T2 metrics_recommend.py | T1 run_claude/recommend usage; T2 adds trends_table | sequential, disjoint functions: ok |
| T1→T4 | recommend()["usage"] → record cost/tokens sum | ok |
| T2→T3 | _write_state + <d>/analytics/.lock → click reads/locks same | ok |
| T2→T4 | publish(d,project,stats,rec,stats_path,multi), build_ops(stats,rec,week,stats_path,multi), week_id | ok (T4 dry-run needs week_id(window.until)) |
| T4↔T5 bin/tmux-ctl | T4 help lines; T5 no-tmux block | sequential: ok |
| T5 self | Verify uses ./bin/tmux-ctl from worktree | ok after lead fix (probe: metrics needs tmux today) |
| T6 self | real dry-run --json reads real state, no outbox write | ok |
| T7 | user gate after merge | waits for morning |
Ruling: analytics.off lives in agent_base() (persistent, like dream.off), not state_dir() — spec says "state dir" ambiguously — cost if wrong: a file in another dir to move.
Ruling: weekly post split into two ops (A trends+flags, B recs+buttons+stats.json) — bridge cuts text at 2000 silently — cost if wrong: two messages instead of one.
Ruling: ops post files ideas under the job's repo name; project posts under that project — spec silent — cost if wrong: idea lands in another project's inbox.
Ruling: metrics weekly failures do not append kind:error to tracked runs.jsonl (part-1 minors 39/69) — cost if wrong: errors only visible in analytics.launchd.log.
Task 1: dispatched impl-t1 (sonnet), base 9f74fcf
Task 1: implementer DONE 8bdf469; review rev-t1 on review-9f74fcf..8bdf469.diff
Task 1: minor (deferred): untested "unavailable after real usage" path in recommend()
Task 1: minor (deferred): no type check on token values in _usage
Task 1: minor (deferred): NO_USAGE constant unused in one test
Task 1: complete (commits 9f74fcf..8bdf469, review clean)
Task 2: dispatched impl-t2 (sonnet), base 8bdf469
Task 2: implementer DONE 5305391; review rev-t2
Task 2: minor (deferred): feed re-read once per flag line (thread_link)
Task 2: minor (deferred): truncation after escape can split an escape sequence
Task 2: minor (deferred): _write_state except too narrow for a malformed old state file (plan-mandated snippet)
Task 2: minor (deferred): spec names unescaped in flag lines
Task 2: minor (deferred): no tests for underpowered lines and the deepest fit levels
Task 2: complete (commits 8bdf469..5305391, review clean)
Task 3: dispatched impl-t3 (sonnet), base 5305391
Task 3: implementer DONE a3e776f; review rev-t3
Task 3: minor (deferred): state write OSError after ideas.add raises; a retap files again (analytics_post.py:258-263)
Task 3: minor (deferred): outbox_write error after done saved raises; confirmation lost (analytics_post.py:267)
Task 3: minor (deferred): no real concurrent-tap test; done-on-disk-before-reply not asserted
Task 3: complete (commits 5305391..a3e776f, review clean)
Task 4: dispatched impl-t4 (sonnet), base a3e776f
Task 4: implementer DONE 57a8542; review rev-t4
Task 4: minor (deferred): redundant week line in dry-run
Task 4: minor (deferred): --json without --dry-run silently ignored
Task 4: minor (deferred): no multi-destination record test
Task 4: minor (deferred): "no runs" message printed when there is no destination at all
Task 4: ⚠️ help names metrics schedule before Task 5 adds it — resolved by Task 5 (planned order)
Task 4: complete (commits a3e776f..57a8542, review clean)
Task 5: dispatched impl-t5 (sonnet), base 57a8542
Task 5: implementer DONE_WITH_CONCERNS b1f0fe9 (also widened the early tmux guard at bin/tmux-ctl:114 — needed); review rev-t5
Task 5: minor (deferred): weekly zsh check only asserts absence of "not inside tmux"
Task 5: minor (deferred): leftover TW_BIN_DIR seam; dead TC_ANALYTICS env entry
Task 5: minor (deferred): status tests read the checkout's real runs.jsonl
Task 5: minor (deferred): usage-string wording differs from dream's
Task 5: complete (commits 57a8542..b1f0fe9, review clean)
Task 6: dispatched impl-t6 (sonnet), base b1f0fe9
Task 6: implementer DONE_WITH_CONCERNS 4f9c11f..e196062 (suite ALL PASS 181 jobs rc=4; bridge 189/189; real dry-run 2 ops to _ops, _check ok, max 1784 chars, cost $0.0808; outbox counts unchanged)
Ruling: Task 6 is a note-only verification task; the lead checked Verify (4 headings) and the evidence lines, and the final whole-branch review covers it instead of a separate task reviewer — cost if wrong: a wrong figure in the note reaches the morning report.
Task 6: minor (deferred): 0 links in the real 30d dry-run — the flag lines that fit are pre-feed specs (feed starts 11-11); the 7d weekly window will mostly hold feed-era specs
Task 6: minor (deferred): part-1 line 78 "handoffs flag fires on 13/18 specs" not addressed by part 2
Task 6: complete (commits b1f0fe9..e196062, lead-checked)
Final review: dispatched final-rev (session model) on f1d070e..e196062
Final review: not ready (1 Critical, 1 Important, 5 Minor); final-review.md
Ruling: same-week re-run does not re-post: publish skips a dir whose post-<week>.json exists (prints "already posted <week>", --force overrides) — the remap of old buttons onto new items is otherwise unfixable without changing the custom id format — cost if wrong: a manual re-run in the same week needs --force.
Ruling: all 5 final minors go into the one fix wave with the Critical and Important — each is small and local — cost if wrong: a larger fix diff.
Final fix: dispatched fix-final (sonnet), base e196062
Ruling: weekly --json without --dry-run becomes an error (final-rev suggestion; today it posts for real) — added to the fix wave as item 8 — cost if wrong: none, the flag had no other use.
Final fix: fix-final DONE e196062..aa6e739 (8 items); re-review final-rev
Final re-review: all 8 ADDRESSED, no new Critical/Important, ready to merge; final-rereview.md
Final: minor (deferred): N1 same-week re-run still pays the model call before publish skips
Final: minor (deferred): N2 state written + outbox write failed → retry needs --force (documented)
Final: minor (deferred): N3 plist pins the checkout analytics_schedule.py runs from; install via ~/.local/bin (main)
Final: minor (deferred): N4 click reply outbox_write and evidence join outside the try
User gate #94 (Task 7), 2026-11-23: the user ran `tmux-ctl metrics schedule install` (agent Bash was denied by the auto-mode classifier) → metrics weekly Mondays 09:00; status `loaded`. `tmux-ctl metrics weekly` rc=0: one `kind: analytics` record (2026-W48, 2 posts to `_ops`, $0.0793; commit d92ff3c). Taps on File as idea 1: audit `filed` 19:04:30Z, `already filed` 19:04:41Z and 19:05:12Z; the ideas file gained exactly one line. Gate closed.
