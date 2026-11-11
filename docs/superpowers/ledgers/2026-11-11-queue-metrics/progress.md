# SDD ledger — plan: docs/superpowers/plans/2026-11-11-queue-metrics.md
Spec: docs/superpowers/specs/2026-11-10-queue-metrics-design.md · branch feat/queue-metrics · base 565352b · queue batch: none yet (spec 1 of 10)
## Pre-flight scan
| Tasks | Shared | Found |
| T1→T6 | board/metrics.py | strictly serial (blockedBy chain), one implementer at a time |
| T2/T4 | run record fields | T4 adds declared_list/touched_list to T2's record — T4 owns that edit |
| T4/T5 | compare_text, status_line | T4 calls them guarded; T5 defines them — consistent |
| T2,T3/T6 | record builders | T6 backfill reuses them with derived windows — consistent |
| T1/T6 | usage snapshot | T1 makes it, T6 real-state test reads it |
| T7 | claude/orchestrator.md + handoff SKILL | shared lead config → never batched; own review |
| T1..T6 self | tests vs code | consistent |
| T6 self | privacy sweep "every test's temp logs" | not reachable across test files |
Ruling: T6's privacy sweep covers logs T6's own test produces by driving every subcommand (batch start, start, record, defect, backfill, error line) plus the committed runs.jsonl — other test files' temp dirs are gone by then — cost if wrong: a privacy leak in a code path only another test exercises.
Ruling: native task descriptions carry Goal/Verify/metadata and point to the brief files; the brief file is the full requirements — cost if wrong: none, briefs are verbatim plan text.
Ruling: one implementer teammate (qm-impl) is reused across T1–T6 (serial, same module) — cost if wrong: a larger implementer context.
Task 1: dispatched qm-impl (sonnet/standard), base 12862a6
Task 1: report green (19 OK rc=0; board 912 run, 6 known FAIL; group mutation 2 FAIL)
Task 1: review dispatched to qm-rev (sonnet/standard), package review-12862a6..23b2afb.diff
Ruling: dispatch T2 to qm-impl while T1 is in review — same writer, T1 fixes land as separate commits after T2's — cost if wrong: a fixup touching both tasks' code.
Task 2: dispatched qm-impl, base 23b2afb
Task 1: minor (deferred): private argparse hack in main()
Task 1: minor (deferred): absolute or duplicate spec paths not rejected (absolute path would put /Users/ in the log — final review: fix before merge)
Task 1: minor (deferred): append() does not guard a missing trailing newline
Ruling: tmux-ctl metrics behind the existing $TMUX guard is acceptable — every lead runs in tmux — cost if wrong: metrics unusable from a plain shell until exempted like other subcommands.
Task 1: complete (commits 12862a6..23b2afb, review clean)
Task 2: report green (14 OK rc=0; stale_base mutation FAIL)
Task 2: review dispatched to qm-rev, package review-23b2afb..5e8e5b2.diff
Task 2: review spec ❌ — 1 Important (merge stored as {commit,at}, spec §3: commit or null)
Ruling: record time keys are the spec's started_at/ended_at; T2's window_start/window_end are renamed in this fix round — spec §3 names them — cost if wrong: one rename.
Ruling: promote T2 minor 1 to the fix round — merge search must pick a merge whose first parent does NOT contain the plan commit; if the plan commit is on main already, match the merge subject's branch to the plan basename without its date prefix; else merge null + missing — backfill (T6) depends on it — cost if wrong: a branch-name heuristic misses a renamed branch (null, named in missing).
Task 2: minor (deferred): dead code (plan_text, if/pass, inline import, setUp loop)
Task 2: minor (deferred): branch --contains picks first non-main branch arbitrarily
Task 2: minor (deferred): --outcome merged with merge null unflagged
Task 2: minor (deferred): bounces/parked/fix_wave tests mirror impl expression; clean stale_base case never diverged
Task 2: fix round 1/5 dispatched to qm-impl (FIX_BASE 5e8e5b2)
Task 2: fix commit a5a9a9e (16 OK rc=0; board 6 known FAIL); scoped re-review dispatched to qm-rev
Ruling: list merge in missing only when outcome is merged or mr (a kept/failed spec's null merge is not a missing source) — carried into T3 — cost if wrong: a merged spec whose merge was not found but outcome text said kept goes unflagged.
Task 3: dispatched qm-impl, base a5a9a9e (T2 re-review in parallel)
Task 2: fix round 1/5 (3 addressed, 1 new open — branch --contains guess picks another spec's branch when plan is on main; commits 5e8e5b2..a5a9a9e)
Task 2: minor (deferred): slug endswith match is loose
Task 2: fix round 2/5 dispatched to qm-impl (FIX_BASE a5a9a9e)
Task 2: fix commits fe86c0d+539ddfc (17 OK rc=0); scoped re-review round 2 dispatched to qm-rev
Task 3: report green (40 OK rc=0; board 952, 6 known FAIL; 3 mutations FAIL)
Task 3: review dispatched to qm-rev, package review-a5a9a9e..3a29282.diff
Task 4: dispatched qm-impl, base 539ddfc (T2 r2 + T3 reviews in parallel)
Task 2: fix round 2/5 (1 addressed, 0 open; commits 3a29282..539ddfc)
Task 2: complete (commits 23b2afb..539ddfc excl. 3a29282, review clean)
Task 3: minor (deferred): LEAD_KEYS misnamed; seq-sdd hard-coded for backfill; null config not in missing; overlapping specs count each other's worktree questions
Ruling: handoffs keyed by repo basename stays (lineage files are keyed by tmux session name, which matches here: agent-board.jsonl); T6 real-state check prints the handoff count read from the real lineage dir — cost if wrong: handoffs reads 0 in a repo whose tmux session is named differently.
Task 3: complete (commits a5a9a9e..3a29282, review clean)
Task 4: report green (20 OK rc=0; all metrics OK; pair-clean mutation FAIL); board 8 FAIL pre-fix (6 known + 2 own, fixed, metrics re-run only)
Ruling: limits at batch end = the run line with the latest at, not table order — spec §6 'at the batch's start and end' — goes into T4's fix round — cost if wrong: none.
Task 4: review dispatched to qm-rev, package review-539ddfc..00574a4.diff
Task 5: dispatched qm-impl, base 00574a4 (T4 review in parallel)
Task 4: review spec ❌ — 3 Important (failed-command span drops failed record; union only with --usage-db; limits end by spec path)
Task 4: fix round 1/5 dispatched to qm-impl (FIX_BASE 00574a4)
Task 4: minor (deferred): loose sentence-placement test; wrong _merge_trees docstring; runs.jsonl created with only an error line
Task 4: fix commits b9ef776 (limits) + 518d841 (span, default db); 23 OK rc=0; 2 mutations FAIL; scoped re-review dispatched
Task 5: report green (24 OK rc=0; veto + direction mutations FAIL); board 998: 6 known + test_worktree_lock test_dead_pid_clean_tree_is_removed (passes alone; same file as the CI macOS flake idea)
Task 5: review dispatched to qm-rev, package review-b9ef776..2e39ac9.diff
Task 6: dispatched qm-impl, base 518d841 (T4 re-review + T5 review in parallel)
Task 4: fix round 1/5 (3 addressed, 0 open; commits 00574a4..b9ef776 + 2e39ac9..518d841)
Ruling: promote T4 re-review minor — union 0 from an index lacking the batch's days falls back to the sum with '(sum, index lacks the window)' — carried into T5 fix round — cost if wrong: none.
Task 4: complete (commits 539ddfc..518d841 excl. T5, review clean)
Task 5: review spec ✅ quality ❌ — 1 Important (status_line says all stages passed with no Status rows)
Ruling: rule 3 (replace) counts only included (non-excluded) challenger specs toward its 8 — spec §5 index excludes them — cost if wrong: replace verdicts arrive later.
Task 5: fix round 1/5 dispatched to qm-impl (FIX_BASE 518d841)
Task 5: minor (deferred): unknown target metric silently blocks replace
Ruling: M-attr 'plus' part counts every row with cwd == repo root (lead or agent) in the window, split 1/k on overlap — spec §3 names the lead's calls, but teammates of the lead start in the repo root and are that spec's work; real backfill then lands within 2% (tokens -1.63%, usd -1.63%, active -0.5%) — cost if wrong: lead_share slightly low and agents of an unrelated root session counted to a sequential spec.
Task 5: fix commit d5a583c (3 mutations FAIL; metrics OK); scoped re-review dispatched
Task 6: report green (real-state PASS: tokens -1.63%, usd -1.63%, active -0.5%; runs.jsonl 12 lines clean; board 1015, 6 known FAIL; skip mutation 2 FAIL)
Ruling: accept backfill --until (not in brief) — keeps the real-state test and committed log at the appendix's 12 specs as later merges land — cost if wrong: one extra flag.
Task 6: review dispatched to qm-rev, package review-d5a583c..5fa3176.diff (includes attribution fix aa97464)
Ruling: run T7 (orchestrator.md + handoff SKILL, files disjoint from T6) in parallel with T5/T6 reviews, on a fresh implementer qm-docs (haiku/mechanical); qm-impl shut down (context past budget) — later fix rounds go to a fresh implementer with the report files — cost if wrong: a fixer re-reads context.
Task 7: dispatched qm-docs (haiku/mechanical), base 5fa3176
Task 5: fix round 1/5 (4 addressed, 0 open; commits 518d841..d5a583c)
Task 5: complete (commits b9ef776..2e39ac9 + d5a583c, review clean)
Task 6: review spec ❌ — 1 Important (backfilled lines carry today's limits as record limits)
Task 6: minor (deferred): ready_at/wait_s null but not in missing; plan M-attr text still says lead rows
Task 6: fix round 1/5 dispatched to fresh qm-fix (sonnet/standard; qm-impl shut down) (FIX_BASE 5fa3176)
Task 6: fix commit cc4c885 (metrics 123 OK rc=0; mutation FAIL); scoped re-review dispatched
Task 6: fix round 1/5 (1 addressed, 0 open; commits 5fa3176..cc4c885)
Task 6: minor (deferred): 70 s privacy sweep; --until constant comment; added[0]
Task 6: complete (commits d5a583c..cc4c885, review clean)
Ruling: T7 verify counts occurrences (grep -o 'tmux-ctl metrics' | wc -l ≥ 4), not lines — the plan's grep -c counts lines and the items are single lines — cost if wrong: none.
Task 7: report green (6 occurrences; board 6 known FAIL; tools OK); zsh run-all rc=1: test_ctl_telegram 'help ends at header last line' (T1 regression: metrics line is now last) + test_telegram_always_on ghost checks (pass alone in worktree and on main — load flake)
Ruling: the help-test regression from T1 goes to the final fix wave (update the expected last header line to the metrics line) — cost if wrong: none.
Task 7: review dispatched to qm-rev, package review-cc4c885..bd0da1a.diff
Task 7: review spec ✅ quality approved; 1 Important (spec-mandated): metrics steps run in every project; repo without configs/seq-sdd.md gets a stray runs.jsonl error line
Ruling: T7 Important goes to the final fix wave: guard the three steps with 'in a repo that has docs/superpowers/metrics/configs/seq-sdd.md' — orchestrator.md is every project's lead prompt — cost if wrong: none.
Task 7: minor (deferred): late-joining spec not told to write batch id into its task; uncommitted runs.jsonl may read as a user edit at finishing; two-batch queue needs one report per batch
Task 7: complete (commits cc4c885..bd0da1a, Important carried to final fix wave)
Final review: with fixes — 0 Critical, 6 Important (run log from cwd checkout; backfill window start; late-join config null; absolute spec paths; help test; repos without metrics) + plan/spec wording
Ruling: derived backfill window starts at the later of the previous plan merge and the last first-parent merge before the plan's first commit — keeps baseline windows while excluding plan-less fix merges' work — cost if wrong: baseline records drift from the appendix (guarded by the 2% test).
Ruling: spec gets one dated Decisions bullet for the repo-root attribution ruling; §3 unchanged — cost if wrong: none.
Final fix wave dispatched to qm-wave (sonnet/standard), FIX_BASE bd0da1a
Final fix wave: commits bd0da1a..afeea5f (134 OK rc=0; board 1027, 6 known; real-state within 2%); scoped re-review dispatched to qm-rev
Ruling: first backfilled spec keeps window start at its plan's first commit (the spec's §7 rule), ruling 2 applies from the second on — cost if wrong: none (baseline unchanged).
Final fix wave re-review: 8 addressed; 1 new Important (orchestrator item 1 last sentence unguarded)
Ruling: the new Important is breakage inside the wave's own diff in every project's lead prompt — qm-wave completes the wave with a docs-only edit (guard that sentence; guard item 5's roadmap sentence 'when that file exists'; plan M-attr overlap sentence 'each repo-root row'); status_line doc-path minor left — cost if wrong: one extra small commit in the wave.
Task final: minor (deferred): status_line reads the Status doc from the cwd checkout but the roadmap from main
Final fix wave: complete (commits bd0da1a..0565daa; guard commit checked by lead: 3 word changes as briefed)
