# SDD ledger — plan: docs/superpowers/plans/2026-11-21-pcee-registry.md
Spec: docs/superpowers/specs/2026-11-10-pcee-registry-design.md · branch pcee-registry · plan commit 3aa437a · native tasks #120-#132 (= plan Tasks 1-13)

## Preflight scan
| pair / task | shared | produces → consumes | found |
|---|---|---|---|
| T1–T8–T10 | board/metrics.py | T1 _with_log/append → T10 gate --log; T8 record fields | serialized by blockedBy (T8 after T1, T10 after T8): ok |
| T2–T4..T9 | engine/bin/registry.js, test/helpers.js | T2 dispatcher main(args,ctx) + scratchRepo → all lib modules | later tasks only add lib/registry/<sub>.js: ok |
| T1–T6/T9 | metrics runs --json | JSON shape (specs, runs, pairs) → readBatch | ok |
| T4–T5..T9 | git.js findPlan, manifest.js parseManifest | → stale, facts, analyse, report | ok |
| T7–T8 | registry facts CLI JSON | → metrics record | key names fixed in Global Constraints: ok |
| T7–T9 | facts function | → report | plan says "facts.js's function" without a name: ruled below |
| T6–T9 | analyse | → report runs analyse when no doc | function name unstated: ruled below |
| T1–T10 | tmux-ctl metrics append --log | → engine gate.test.js | ok |
| T2–T3 | bin/tmux-ctl vs install.sh | disjoint | ok |
| T11 | orchestrator.md, SKILL.md, README | none | ok |
| each task self-consistency | T1..T13 | tests vs code vs files | T3: test_install line 59 counts 9 ok lines (8 + node) still 9 with node ok: ok; others ok |
Ruling: facts.js exports computeFacts(repo, spec, base, head) → the facts object; report.js calls it — the plan names no function — cost if wrong: a rename.
Ruling: analyse.js exports runAnalyse(repo, batchId, relationsPath|null) → {docPath, line}; report.js calls it — same reason — cost if wrong: a rename.
Task 1: dispatched impl-metrics (sonnet, base 3aa437a)
Task 2: dispatched impl-engine (haiku, base 3aa437a)
Task 11: dispatched impl-rules (sonnet, base 3aa437a)
Task 2: green check ok (verify rc 0, # fail 0); held for batch review with Task 3
Ruling: Task 2 keeps all.zsh's awk unchanged (no `# pass` pattern) — node's TAP already prints `ok N` lines the awk counts; the pattern would double-count — cost if wrong: an informational test count off.
Task 3: dispatched impl-engine (reused, haiku, base 1c865fa)
Task 11: green check ok (lead re-ran verify: 1,1,1; rules suites 0 FAIL; test_install FAILs are Task 3 in progress)
Task 1: green check ok (verify OK rc=0)
Tasks 11,1: review dispatched to reviewer (sonnet)
Task 4: dispatched impl-rules (reused, sonnet, base 15631db)
Ruling: metrics runs takes specs from the batch line's `assignment` keys (real batch lines have no `specs` key; my dispatch decision was wrong) plus late specs with a run line — cost if wrong: none, matches the real log. Goes to Task 1's fix round.
Ruling: runs.jsonl.lock must not show as untracked in the main checkout: add `docs/superpowers/metrics/*.lock` to .gitignore in Task 1's fix round — cost if wrong: one ignore line.
Task 11: review spec ✅ quality needs fixes (1 Imp, 3 Min); fix round 1 queued to impl-rules after Task 4
Task 1: review spec ❌ (4 Imp, 4 Min); fix round 1 sent to impl-metrics
Ruling: Task 1 Imp #3 (plan-mandated concurrency test cannot prove exclusion) — replaced by a deterministic held-lock test; the plan's 2x200 test may stay — cost if wrong: none.
Task 3: green check ok (91 ok, rc 0), commit 6f2e1df
Ruling: a failed engine npm ci makes install exit 1 (bridge keeps returning 0) — the engine is required per spec §8 — cost if wrong: an install that stops on a flaky npm.
Batch 2-3: review dispatched (diff = commits 1c865fa, 6f2e1df only)
Task 4: green check ok (# fail 0, validate rc 0), commit 8f25a89; review dispatched
Task 5: dispatched impl-graphs (sonnet, base 8f25a89); impl-engine shut down
Task 11: fix round 1 done 4eaa666; re-review queued to reviewer
Task 7: dispatched impl-rules (reused, sonnet, base 4eaa666)
Task 1: fix round 1 done 2660657 (63 OK rc 0); re-review queued to reviewer
Task 5: green check ok (13/13, npm 33/33, rc 0), commit e6e9f15; review queued to reviewer
Ruling: `order` relations count as hard dependencies for wave placement and cycle detection (impl-graphs' reading) — spec §4 makes an order relation a dependency edge and waves follow dependencies — cost if wrong: an order relation could push a wave later than needed.
Task 6: dispatched impl-graphs (reused, sonnet, base e6e9f15)
Note for final review: dream/discover/scout write runs.jsonl via metrics.append (locked); check analytics_schedule plist_text's use of runs.jsonl path (launchd stdout?).
Batch 2-3: reviewed together (2 tasks): T2 ✅/Approved 4 Min; T3 ✅/Approved 4 Min
Task 3: complete (commit 6f2e1df, review clean)
Task 3: minor (deferred): engine npm ci output discarded; v22.x arithmetic; engine_deps runs after failed link; INSTALL row long
Ruling: Task 2 minors 1-3 promoted to a fix round (null throw breaks the no-stack-trace constraint; gpgsign breaks later scratch commits; node-missing error convention) — given to impl-metrics with Task 4's fix — cost if wrong: one small extra round.
Task 2: minor (deferred): test_ctl_registry.zsh RED not seen
Task 4: review spec ✅ (⚠️ relative plan path vs cwd = lead decision, intended) quality needs fixes (1 Imp findPlan exact-line test, 5 Min); fix round 1 → impl-metrics
Task 11: fix round 1/5 (4 addressed, 0 open; commits acfa0cc..4eaa666)
Task 11: complete (commits 3aa437a..4eaa666, review clean)
Task 11: minor (deferred): backticks inside code span in up-front step (1); failed-planner spec should reuse its metrics start/worktree before step 2
Task 1: fix round 1/5 (4 addressed, 0 open; commits 15631db..2660657)
Task 1: complete (commits acfa0cc..2660657, review clean)
Task 1: minor (deferred): pair_results base check fires for conflict-only pairs; no CLI test of pairs clean:true / null; cmd_backfill hand-rolled LOG_OVERRIDE
Task 5: complete (commits 4eaa666..e6e9f15, review clean; JS and Python wave maps identical 13/13)
Task 5: minor (deferred): clusters test passes an ignored relation (vacuous); +4 more in task-5-review.md
Ruling: order relation {a,b,kind:order} means a runs after b (code's reading); the orchestrator crossplan rule must say so — added to the final fix wave list with Task 11's deferred minors — cost if wrong: reversed order edges from the crossplan agent.
Task 6: green check ok (7/7 rc 0), commit e9cafdd; review dispatched
Task 4: fix round 1 done 9413494; Task 2: promoted-minors fix fb00e52; re-reviews queued (remaining engine fails are Task 7's: cli facts test, test_ctl_registry facts case, stale test in progress)
Task 2: follow-up 2144013 moved catch test to registry_main.test.js
Task 6: review spec ✅ quality needs fixes (2 Imp, 6 Min); fix round 1 → impl-graphs
Ruling: `tmux-ctl metrics append|has|runs` are exempt from the TMUX check (registry calls them outside tmux too); readBatch says `unknown batch` only for that error — cost if wrong: none.
Task 7: impl-rules reported 7a9c052 (19/19); cli.test.js and test_ctl_registry follow-up in progress (npm test 1 fail)
Task 8: dispatched impl-metrics (sonnet, base 7a9c052)
Task 4: fix round 1/5 (1 addressed, 0 open; commit 9413494)
Task 4: complete (commits 15631db..9413494, review clean)
Task 2: fix round 1/5 (3 lead-promoted minors addressed; commits fb00e52, 2144013)
Task 2: complete (commits 3aa437a..2144013, review clean)
Task 7: addendum baeb130 (cli/ctl facts tests replaced; npm test 61/61, ctl 0 FAIL); review pending
Task 6: fix round 1 done edb1e9a (9/9, npm 63/63); scoped re-review NOT yet run
Ruling: analysis line `specs` = plans with a valid manifest (the plans in the graphs), so parallelism = specs/waves is self-consistent; K1 min_specs counts run records, manifest_tokens divides by the batch line's spec count — no change — cost if wrong: parallelism overstated when some plans lack manifests.
Task 8: reported ea02e2a (68 OK rc 0); weekly HelpTest regression from Task 2 help line (sed 2,84p) — unassigned
Lead handoff: new lead f505969e resumed; reviewer and impl-metrics respawned
Task 8: green check ok (68 OK rc 0); review dispatched with T6 re-review and T7 review
Task 2 follow-up: help-range regression (test_metrics_weekly HelpTest) → impl-metrics
Task 6: fix round 1/5 (2 addressed, 0 open; commit edb1e9a)
Task 6: complete (commits e6e9f15..edb1e9a, review clean)
Task 8: review spec ✅ quality Approved (3 Min)
Task 8: complete (commit ea02e2a, review clean)
Task 8: minor (deferred): manifest_tokens not scoped by project; stored unrounded; invalid manifest fence rc 3 fallback silent, untested, no manifest_facts in missing
Task 7: review spec ✅ quality needs fixes (1 Imp: git diff --name-only hides renames in facts.js/stale.js → --no-renames + rename tests); fix round 1 → impl-rules
Ruling: registry facts with no manifest exits 3 and prints `registry: facts: no manifest` on stderr (brief and test pin it; the error-line constraint covers every non-zero exit); "silent" in the handoff meant record treats it as no facts — cost if wrong: one stderr line in record's output.
Ruling: Task 9 starts while Task 7's fix round runs — files are disjoint and the fix (--no-renames) leaves computeFacts' signature unchanged — cost if wrong: T9 tests rerun after the T7 fix lands.
Task 9: dispatched impl-graphs (respawned, sonnet)
Task 7: fix round 1 done 4021be3 (stale_facts 21/21; ctl 0 FAIL; npm 2 fails are T9 WIP); green check ok; re-review dispatched
Task 7: fix round 1/5 (1 addressed, 0 open; commit 4021be3)
Task 7: complete (commits 2144013..4021be3, review clean)
Task 9: green check ok (report 6/6, npm 71/71, rc 0), commit 2b25e93; review dispatched
Task 9: review spec ✅ quality Approved (Minors only)
Task 9: ⚠️ resolved: real run lines carry base and head (29 of 36 run records in main's runs.jsonl; the rest are backfills without them → no facts rows, as intended)
Ruling: report's superseding line keeps appends_verified true even when a spec had no head or its facts errored (brief mandates true; those specs show n/a rows) — cost if wrong: K1 counts an analysis as verified with a spec unchecked.
Task 9: complete (commits 4021be3..2b25e93, review clean)
Task 9: minor (deferred): see task-9-review.md; final review: superseding line records relations 0 without --relations (original line may have had n)
Task 2 follow-up: help fix 6394126 (metrics tests 358 OK rc 0; ctl registry 0 FAIL); re-review dispatched
Task 10: dispatched impl-metrics (reused, sonnet, base 6394126)
Task 2 follow-up: help fix re-review ADDRESSED (commit 6394126); minor (deferred): help range is still a hard-coded line number
Task 10: green check ok (gate_k1 10 OK, gate.test 1/0, metrics 368 OK, rc 0), commits 5909b42 b013dfe; review dispatched
Ruling: Task 12 (read-only suite + real-state checks) starts while Task 10 is in review — saves a ~9 min suite wait; any T10 fix gets its affected suites re-run — cost if wrong: one re-run.
Task 10: review spec ✅ quality needs fixes (1 Imp: gate.test.js fails outside tmux — gate not TMUX-exempt; 3 Min); fix round 1 → impl-metrics after the T12 all.zsh run
Task 10: minor (deferred): no nested-suffix test; suffix text-only; gate.test pass path only; ⚠️ K1 last/runs span all batches (pre-existing)
Ruling: K1's last analysis line and run counts span every batch in runs.jsonl (existing evaluator behaviour) — spec §6 counts specs with manifests across runs, and the newest analysis is the current batch's — cost if wrong: K1 mixes an old batch's parallelism after a newer batch without analysis.
Task 12: incident: a failed `metrics gate K1 --log <real>` appended an error line to main's runs.jsonl; lead removed it (checksum back to 5be45d6d); later real-log checks use scratch copies
Task 12: minor (deferred, final review): metrics gate error path appends to the log, so gate is not read-only on failure; gate files read from the main checkout, not --repo
Task 10: fix round 1 done eb4eb01 (env -u TMUX gate.test 1/0, gate_k1 10 OK, ctl ALL PASS); re-review dispatched
Task 12: all.zsh at b013dfe rc=1 FAIL 1/205 (test_teammate_window flagged teammate); lead re-ran it alone at eb4eb01: ALL PASS rc 0; engine 72/72 after eb4eb01; real-state checks all as specified; real log checksum unchanged
Ruling: Task 12 accepts the single all.zsh failure as a load flake — the job passes alone twice (implementer and lead), no plan file touches it — cost if wrong: a real teammate-window regression ships; the post-merge suite on main re-checks it.
Task 12: minor (deferred, final review): tmux-ctl metrics exemption reads $2, so a flag before the subcommand defeats it
Task 12: complete (no commits; checks in task-12-report.md, 1 ruling)
Task 10: fix round 1/5 (1 addressed, 0 open; commit eb4eb01)
Task 10: complete (commits 6394126..eb4eb01, review clean)
Final review: dispatched final-reviewer (session level, 30b7e22..eb4eb01)
Final review: with fixes (0 Crit, 2 Imp: I1 report drops relations → saved analysis/<batch>.relations.json fallback; I2 orchestrator order direction + T11 minors); other minors stay deferred; no ruling overturned
Ruling: final-wave also makes the morning-report step commit the analysis document (reviewer's optional) — no rule commits it today — cost if wrong: one more file in the report commit.
Final fix wave: dispatched impl-metrics (sonnet, base eb4eb01)
Final fix wave: done 7e0effa 105fbe4 (npm 74/74 rc 0, also outside tmux; rules tests pass); scoped re-review dispatched
Merge gates: install.sh --check rc 0 (node v22.13.1 ok); real npm ci --omit=dev on a copy of engine/package*.json rc 0
Final fix wave: re-review I1 ADDRESSED, I2 ADDRESSED, no new breakage (commits eb4eb01..105fbe4)
Final: minor (deferred): I1 test does not pin a wave difference (both fixture specs write `log`); disjoint-writes fixture would close it
Final review: clean after one fix wave
