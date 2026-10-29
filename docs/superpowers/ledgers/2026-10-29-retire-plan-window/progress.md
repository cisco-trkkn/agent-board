# SDD ledger — plan: docs/superpowers/plans/2026-10-29-retire-plan-window.md
Spec: docs/superpowers/specs/2026-10-29-retire-plan-window-design.md (approved). BASE 379707f.
Preflight scan:
| Pair/Task | Produces vs consumes | Found |
| T1×T4 | T1 layout close logic → T4 probes it | ordered by blockedBy; ok |
| T1×T3 | T1 edits docs/INSTALL.md, config/tmux.conf → T3's grep covers both | T3 grep shows T1's lines until T1 lands → Ruling below |
| T2×T3 | T2 rewrites planview.py docstring → T3's grep covers board/ | same as above → Ruling below |
| T1×T2 | T1 deletes bin/tmux-plan → T2's test_tmux_plan_script_runs_watch reads it | T2 deletes that test; board suite red only between the two commits; ok |
| T1 | tests (5 RED, 1 already green) vs layout code | consistent; snippet probed on tmux 3.8 |
| T2 | AC diff-shape vs Step 2 new test | fixed in 379707f |
| T3 | files vs grep scope | consistent |
| T4 | read-only live probe + scratch probe | consistent |
Ruling: T3's grep criterion is judged on the merged head of T1-T3, not on T3's commit alone; hits in T1/T2 files are theirs — tasks run in parallel on disjoint files — cost if wrong: a stray mention survives until the final review catches it
Ruling: T1-T3 run in parallel (disjoint files metadata); one shared worktree, each stages only its own paths — cost if wrong: index.lock retries
Task 1: dispatch layout (sonnet/standard) BASE 379707f
Task 2: dispatch planview (sonnet/standard) BASE 379707f (parallel, disjoint)
Task 3: dispatch docs (sonnet/standard) BASE 379707f (parallel, disjoint)
Task 3: docs committed 8a388f0 (test_plugin rc=0); note: 8a388f0 also carries Task 1's staged deletions (bin/tmux-plan, e2e-plan-window.zsh) — shared-index sweep
Task 3: Ruling: board/index.html:388 text and teams-plan Task 13's e2e-plan-window pattern pointer added to Task 3 scope (docs) — outside every file list, plain text — cost if wrong: one extra review line
Task 3: docs scope additions committed 9ee3d06 (test_plugin rc=0, json rc=0); green check passed; reviewer rev (sonnet/standard) dispatched on 379707f..9ee3d06
Task 3: complete (commits 379707f..9ee3d06, review clean)
Task 2: planview committed c1264df (test_planview 27 OK rc=0; board 536 OK)
Task 2: Ruling: `planview.py view` text mode (non-JSON) printed render(); with render gone it keeps the empty-view line and prints JSON for a non-empty view — only dated history docs used the text mode; overseer/night-mode call view() in-process; spec binds view() — cost if wrong: a human typing `planview.py view` sees JSON instead of lines
Task 2: green check passed; reviewer rev dispatched on 9ee3d06..c1264df
Task 2: minor (deferred): test_watch_subcommand_is_gone could use run_cli() (isolates HOME/TC_STATE/TC_TMUX); a regressed watch would poll real tmux for 20s
Task 2: minor (deferred): planview docstring says "for board consumers" but no current caller outside tests (queued plans will be)
Task 2: complete (commits 9ee3d06..c1264df, review clean)
Task 1: layout committed c4a98ce (test_layout ALL PASS rc=0; run-all rc=0, grep -c FAIL 1 = passing test name); green check passed; reviewer rev (sonnet/standard) dispatched on c1264df..c4a98ce
Task 1: concern: test_dedicated_server.zsh:80 edited outside the brief (expected "claude plan "); put to review
Task 4: Ruling: Task 4 starts in parallel with Task 1's review — it is read-only plus its own report file — cost if wrong: a review fix to the close logic forces a re-run of its scratch probe
Task 4: dispatch realstate (sonnet/standard) on c4a98ce
Task 1: minor (deferred): bin/tmux-dev-layout:57-58 — two+ windows named plan make =sess:plan ambiguous; kill-window fails, old tmux-plan window stays (fails safe); fix would loop over window ids
Task 1: minor (deferred): bin/tmux-dev-layout:57 — pane_start_command reads the active pane only (old window was single-pane)
Task 1: complete (commits c1264df..c4a98ce, review clean)
Task 4: realstate committed 8a67cee + d6cced4 (per-session plan count; verify 4 rc=0); green check passed; reviewer rev dispatched on c4a98ce..d6cced4
Task 4: minor (deferred): e2e report Counts cites live.txt, which is not in the repo, so its greps can't be re-run as written
Task 4: minor (deferred): the report doesn't show that no …-shortened line contains tmux-plan (reviewer's independent run confirms count 3 = 0)
Task 4: complete (commits c4a98ce..d6cced4, review clean)
Final: whole-branch review dispatched (final, session-level) on 5070db3..d6cced4
Final: review "With fixes" — 0 Critical, 1 Important (teams plan Task 6 md:438,445 + tasks.json still target deleted planview.watch); deferred minors: none block merge
Final: Ruling: the teams-plan amendment (Global Constraints exception) extends from Task 5 to Task 6's two watch lines — spec §4 scoped it to Task 5 only, but a queued plan pointing at a deleted function would be built on — cost if wrong: two lines of a dated plan edited beyond the spec's scope
Final: Ruling: e2e report gets a correction paragraph (install is dedicated mode, -L agent-board; default-server plan windows must be closed by hand), folded into the one fix wave — the report's "dev would clean" line was wrong for the default server — cost if wrong: one extra paragraph
Final: fix wave dispatched fixer (haiku/mechanical) on d6cced4
Final: minor (deferred): board/planview.py:198 NO_PLANS still says "prefix S for a shell", a plan-window-era hint
Final: minor (deferred): planview view prints JSON without --json for a non-empty view (covered by Task 2's ruling)
Final: fixdocs committed b5cfc26 (json rc=0, watch 2→0, ## = 4); scoped re-review dispatched (sonnet/standard; 3 files, not small)
Final: re-review — 2 addressed, 0 open, no new breakage (d6cced4..b5cfc26); final review clean
