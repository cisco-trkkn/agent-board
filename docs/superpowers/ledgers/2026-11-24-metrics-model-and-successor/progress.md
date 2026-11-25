# SDD ledger — plan: docs/superpowers/plans/2026-11-24-metrics-model-and-successor.md
Spec: docs/superpowers/specs/2026-11-23-metrics-model-and-successor-design.md. Branch rebased onto main ef6c5ab → plan commit 851ee71 (BASE).
Stale check: registry stale said "no manifest" (the manifest is a json:manifest fence in the plan); manual: git diff 0af42b5 main over the plan's 13 files is empty → fresh.
Ruling: plan runs as written without a registry stale verdict — every file it writes is unchanged 0af42b5..main — cost if wrong: a task patches code that moved; reviews would catch it.
Preflight:
| pair/task | shared | finding |
| T2–T3 | test_metrics_tasks_log.py; build_task_lines(spawns, lead_sessions, run_start) produced by T2, consumed by T3 | sequential (T3 blockedBy T2) |
| T1–T3 | metrics_lead.lead_session_ids produced by T1, consumed by T3 | sequential |
| T1/T2/T3–T6 | T6 measures T1–T3 code | T6 last |
| T4, T5 | files disjoint from T1–T3 and each other; T4 reads only dict keys | parallel-safe with T1–T3 |
| each task | brief tests vs code consistent on read; no self-contradiction seen | ok |
Ruling: run T4 then T5 (mechanical, one implementer) in parallel with T1→T2→T3 (standard implementer); T4+T5 reviewed as one batch — files disjoint, no blockedBy — cost if wrong: a merge conflict in the shared worktree index; teammates commit path-scoped.
Task 1: dispatched impl (standard, sonnet), BASE 851ee71
Task 4: dispatched mech (standard, sonnet), BASE 851ee71
Ruling: mech (T4, T5, mechanical) runs on sonnet/medium — the routing gate refused haiku/low while T1 (standard) is in progress — cost if wrong: a few cents more per task.
Task 5: bounced 1/2 (no exact verify command or exit code in report)
Task 4: review dispatched rev45 (standard, sonnet) on review-851ee71..b18fabc.diff
Batch 4-5: reviewed together (2 tasks)
Task 4: minor (deferred): extra blank line in board/tests/test_metrics_analyze.py
Task 4: minor (deferred): new import in test_metrics_recommend.py as briefed (reviewer note)
Task 4: complete (commits 851ee71..72f8cc0, review clean)
Task 5: complete (commits 72f8cc0..b18fabc, review clean)
Task 1: review dispatched rev (standard, sonnet) on review-5f4b94b..9665000.diff
Task 1: minor (deferred): raw PHRASE pre-filter misses a phrase split across content blocks (plan A3 accepts this)
Task 1: minor (deferred): _HEADS/_RESULTS caches unbounded and unlocked
Task 1: minor (deferred): mid-file import in metrics_lead/test
Task 1: complete (commits 5f4b94b..9665000, review clean)
Task 2: dispatched impl (standard, sonnet), BASE 6543e77
Task 2: review dispatched rev (standard, sonnet) on review-6543e77..ae7c71a.diff
Task 2: Ruling: spawn window [run_start, task end] (plan A1) stands over the spec's "not after the task's first activity" — the spawn step runs only when the task has no usage rows, so no first-activity time exists — cost if wrong: a later re-dispatch spawn (e.g. an escalation) names the task's model instead of the first one.
Task 2: minor (deferred): escalated-from-spawn path untested
Task 2: minor (deferred): dead `source = None` assignment
Task 2: minor (deferred): ts upper bound inert when task end unknown
Task 2: complete (commits 6543e77..ae7c71a, review clean)
Task 3: dispatched impl (standard, sonnet), BASE 6885a52
Task 3: bounced 1/2 (verify exit code not read directly)
Task 3: review dispatched rev (standard, sonnet) on review-6885a52..9ae4196.diff
Task 3: minor (deferred): read_spawns catches only OSError — a non-UTF-8 spawns.jsonl raises through record
Task 3: minor (deferred): model_source "none" written once, never retried by backfill
Task 3: minor (deferred): extra tasks-log read in report
Task 3: complete (commits 6885a52..9ae4196, review clean)
Task 6: dispatched impl (standard, sonnet), BASE 9ae4196
Final: dispatched final (session level) on review-851ee71..01e3fa4.diff
Task 5: dispatched mech (standard, sonnet), BASE 72f8cc0 (with Task 4, one brief)
Task 5: review dispatched rev45 (standard, sonnet) on review-851ee71..b18fabc.diff
Final: verdict ready with fixes (0 C / 1 I / 4 M): reviewer dispatch lines parsed as owners; SKILL line lacks the review form
Ruling: reviewer dispatch lines in this ledger rewritten to `review dispatched <name> (<tier>, <model>) on …` before metrics record — final review Important 1; lead-local, gitignored — cost if wrong: none beyond this ledger's wording.
Final: fix wave dispatched impl (standard, sonnet), BASE 01e3fa4: SKILL review-dispatch clause, parse_ledger reviewer test, read_spawns (OSError, ValueError)
Final: fix wave d02908a (64 tests OK rc=0); review dispatched rerev (standard, sonnet) on review-01e3fa4..d02908a.diff
Final: re-review rerev: Important 1 ADDRESSED, Minor 1 ADDRESSED, no new breakage (commits 01e3fa4..d02908a)
Task 6: review dispatched t6rev (standard, sonnet) on review-d02908a..d365c0b.diff
Task 6: minor (deferred): raw timing outputs not kept in scratch; figures rest on the report
Task 6: minor (deferred): 6 of 22 resolved records counted by difference, not traced (stated in doc)
Task 6: complete (commits d02908a..2efccea, review clean)
Ruling: branch rebased onto origin/main 1a064b1 (dropping local-main-only e099984/ef6c5ab) before push — the PR then carries only this spec — cost if wrong: none; local main keeps both commits.
