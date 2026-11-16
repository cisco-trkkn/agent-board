# SDD ledger — plan: docs/superpowers/plans/2026-11-16-execution-analytics-part-1.md
Spec: docs/superpowers/specs/2026-11-12-execution-analytics-design.md#part-1. Branch queue/execution-analytics-part-1, base bb840e7 (main) + plan b869c53.
Preflight scan:
| pair / task | shared | produces → consumes | found |
| T1→T2 | metrics_tasks.build_task_lines | T1 signature (spec,batch,tasks_text,progress,routing,rows,commit_time,run_end) → T2 caller | ok |
| T2,T3,T4,T5 | board/metrics.py | each adds a subcommand to _parser/dispatch/SUBS | serial by blockedBy; ok |
| T2→T3 | tasks.jsonl line shape | T1 keys → analyze reads tier, model_used, usd, tokens, fix_rounds, findings, escalated, outcome, code_in_steps | ok |
| T3→T4 | metrics_analyze.lookup + stats.json rounding | → evidence check | ok |
| T4→T5 | metrics_recommend.py | T5 adds weekly_text | ok |
| T3,T5→T6 | --tasks-log on analyze and weekly | e2e uses both | ok (added at plan time) |
| T1 | regexes vs real ledger | DISPATCH model group limited to model names (probed: "(fresh, standard)" no longer read as model) | ok |
| T4 | claude flags | --effort/--tools/--allowedTools/--permission-mode dontAsk/--no-session-persistence/--strict-mcp-config/--output-format probed in claude --help | ok |
| each task self-consistency | tests vs code vs files | checked | ok |
Ruling: R1–R5 in plan Global Constraints (task windows from ledger+commit times; handoffs flag $/active-hour; code_in_steps from tasks.json fences; projects from overview.py; stats.json in $TC_STATE/analytics) — cost if wrong: see each in the plan.
Task 1: dispatched ea-impl (sonnet, base b869c53)
Task 1: green check ok; review dispatched ea-rev (b869c53..c7e8202)
Task 1: review spec ❌ (Important: shared-reviewer rows misattributed before final fix commit; QM fixture lines adapted/spliced, not real)
Task 1: minor (deferred): review_rounds counts dispatch + re-review result line twice (brief wording)
Ruling: Task 1 fix round 1 also takes two minors (owner "fresh" from `dispatched to fresh qm-fix`; `commits A..B + C..D` uses first range) — both corrupt task lines Task 2 will write, same lines of code — cost if wrong: a slightly larger fix diff.
Task 1: fix round 1/5 dispatched to ea-impl (FIX_BASE c7e8202)
Task 1: fix round 1 green (17 OK, metrics 151 OK); scoped re-review → ea-rev (c7e8202..1bf9a9a)
Task 1: fix round 1/5 (4 addressed, 0 open; commits c7e8202..1bf9a9a)
Task 1: minor (deferred): test_metrics_tasks.py:21 DISCORD minor line truncated while header says verbatim
Task 1: minor (deferred): `commits (.*)` last-pair would pick a later non-commit range (`commits A..B; base C..D`); no real line today
Task 1: complete (commits b869c53..1bf9a9a, review clean)
Task 2: dispatched ea-impl (sonnet, base 1bf9a9a)
Task 2: green check ok (14 OK; metrics 165 OK); review dispatched ea-rev (1bf9a9a..c26fe6e)
Task 2: ⚠️ circular import under `python3 -I board/metrics.py` resolved by lead: `status` rc=0, `backfill-tasks --help` ok
Task 2: minor (deferred): main-root cwd match is equality only (subdir agents dropped), undocumented/untested
Task 2: minor (deferred): cwd==root rows weigh 1 for every overlapping spec (attributed_rows divides by k)
Task 2: minor (deferred): unreachable shas in backfill → all ends = ended_at, shared owner's rows to first task, partial:false with no signal — watch in Task 6
Task 2: minor (deferred): untested `backfill-tasks: skipped <spec>` and `run has no window` paths
Task 2: minor (deferred): metrics↔metrics_tasks import cycle; lazy import would avoid second module copy
Task 2: minor (deferred): repeat record appends duplicate task lines (readers take last)
Task 2: complete (commits 1bf9a9a..c26fe6e, review clean)
Task 3: dispatched ea-impl (sonnet, base c26fe6e)
Task 3: green check ok (39 OK; metrics 204 OK); review dispatched ea-rev (c26fe6e..77a2ef3)
Ruling: specs_merged counts outcome "merged" only (an "mr" run is in specs_run but neither merged nor failed) — spec §2 says "merged"; part-2 post can add an mr row — cost if wrong: MR-integrated queues show a merged-count dip.
Task 3: minor (deferred): failed analyze appends kind:error to tracked runs.jsonl via _log_error (shared by read-only subs) — matters for part-2 weekly job
Task 3: minor (deferred): --tasks-log replaces projects[0], not strictly "current repo", with --projects A B or overview omitting this repo
Task 3: minor (deferred): no underpowered median=1.5 fixture; `>= 2` → `>= 1.5` mutant survives
Task 3: minor (deferred): underpowered escalation branch has no min task count (1 escalated task flags at 100%)
Task 3: minor (deferred): two projects with the same basename merge indistinguishably
Task 3: complete (commits c26fe6e..77a2ef3, review clean)
Task 4: dispatched ea-impl (sonnet, base 77a2ef3)
Task 4: green check ok (22 OK; metrics 226 OK); review dispatched ea-rev (77a2ef3..7c0be79)
Task 4: review quality needs fixes (Important: relative --stats not resolved; prompt names a path that doesn't resolve from cwd)
Ruling: kept-only `items` in recommend.json meets "parsed items" (dropped carry title+reason) — cost if wrong: dropped bodies lost for debugging.
Ruling: numbers in title/change/expected_effect are checked too: each must match (M-rounding) a value in that item's own evidence list, else the item is dropped with `uncited number <n> in <field>` — spec Decisions "every number it cites is checked against them" outranks the brief's evidence-only scope — cost if wrong: more items dropped.
Ruling: parse_items no-fence path takes the first decodable list whose elements are dicts (or {"items":[...]}) — prose `[1]` must not win — cost if wrong: none.
Task 4: minor (deferred): int/float decimals from repr accept 4.4 for 4 and 3.04 for 3.0 (spec wording "after rounding to the stats' precision")
Task 4: minor (deferred): --tools Read not path-scoped to stats.json; check in Task 6 real run
Task 4: minor (deferred): test_prompt_rules greps generic words (small/title/change/risk)
Task 4: minor (deferred): any OSError reported as `claude not found`
Task 4: fix round 1/5 dispatched to ea-impl (FIX_BASE 7c0be79)
Task 4: fix round 1 green (32 OK; metrics 236 OK); scoped re-review → ea-rev (7c0be79..4964962)
Task 4: fix round 1/5 (3 addressed, 0 open; commits 7c0be79..4964962)
Ruling: `33%` vs 0.3333 compares at the written precision (33 vs 33.33 rounded to 0 decimals) — matches the M-rounding intent — cost if wrong: loose percent matches.
Task 4: minor (deferred): prose check ignores suffixed numbers (10x, 40min, 5k), flags dates and `1,000` as uncited, compares signs ("falls by 0.54" vs -0.54 dropped) — watch drop count in Task 6 real run
Task 4: minor (deferred): non-string title/change/expected_effect skip the check (require strings)
Task 4: minor (deferred): {"recommendations":[...]} wrapper not found; skip and empty-list fallback untested; test_non_string_prose_fields_are_ignored misnamed; path resolved three times
Task 4: complete (commits 77a2ef3..4964962, review clean)
Task 5: dispatched ea-impl (sonnet, base 4964962)
Task 5: green check ok (16 OK; board 1171 OK); review dispatched ea-rev (4964962..07f3084)
Ruling: keep the out-of-files metrics_analyze._round change (whole medians stay floats; fixes latent 0.4-matches-0 evidence bug) — small, tested, reviewer agrees — cost if wrong: none found.
Task 5: minor (deferred): flag lines show spec basename only; same-named specs across projects read as one ([project] prefix)
Task 5: minor (deferred): forecast medians only on below_half rows; no summary line when none below 0.5
Task 5: minor (deferred): null subject prints "None"; untested multi-line evidence / null subject / _log_error side effect
Task 5: minor (deferred): --dry-run refusal appends kind:error to tracked runs.jsonl (same as Task 3 minor)
Task 5: minor (deferred, part 2): model strings unescaped for Discord (mentions/markdown); stats line carries absolute path
Task 5: complete (commits 4964962..07f3084, review clean)
Task 6: dispatched ea-impl (sonnet, base 07f3084)
Task 6: green check ok (verify count ≥1, rc 0); review dispatched ea-rev (07f3084..cda3610)
Ruling: R3 was a plan defect — .tasks.json descriptions never carry Steps (0 of 34 tasks across 5 past plans have a non-metadata fence), so code_in_steps is always false and `overpowered` can never fire; final fix wave reads the plan .md's `### Task N:` section for a non-metadata fence (tasks.json kept as fallback) — spec §2 defines it on "the plan step text" — cost if wrong: overpowered stays dead.
Ruling: final fix wave also fixes the prose-number false drop (a number inside a cited string-evidence value, e.g. 'Task 5: …' subject, reads as uncited) by blanking cited string values before scanning, and stores dropped items' full text in recommend.json `dropped[].item` — real run dropped 1 of 3 by this, 1 more unjudgeable — cost if wrong: none.
Task 6: minor (deferred): note §3 nests ``` inside ``` (render broken; use ````)
Task 6: minor (deferred): second (stream-json) model run's false-drop answer only in scratch; paste the item into the note
Task 6: minor (deferred, part 2): flags barely discriminate (costly always 10 rows; handoffs 13/18 specs); underpowered/rec 1 rest on 2 tasks (no min n)
Task 6: minor (deferred): weekly text does not show dropped titles/reasons
Task 6: minor (deferred): cause of 12 owner-but-no-rows partial tasks unchecked
Task 6: complete (commits 07f3084..cda3610, review clean)
Final review: dispatched ea-final (session model, bb840e7..cda3610, final-review-brief.md)
Final review: complete — not ready (1 Critical, 3 Important, 6 Minor); final-review.md
Final fix wave: dispatched ea-fix (sonnet, base cda3610, fix-wave-brief.md)
Final fix wave: green check ok (1183 tests OK rc 0; backfill 39/90 partial, owner-no-rows 12→4); commits cda3610..1e85a15
Ruling: accept 39/90 partial vs "well below 47" — 35 of 39 are pre-ledger runs with no owner (data limit, not C1); owner-but-no-rows fell 12→4 — cost if wrong: per-task cost coverage stays thin for old runs only.
Final fix wave: re-review clean (10/10 addressed, 0 new breakage; fix-wave-rereview.md)
Finish: ledger archived; merge locally (queue answer), no push
Task 7: complete (user gate: user answered "Useful" on Discord, 2026-11-16T21:12Z)
