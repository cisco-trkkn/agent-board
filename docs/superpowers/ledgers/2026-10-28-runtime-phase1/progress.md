# SDD ledger — plan: docs/superpowers/plans/2026-10-28-runtime-phase1.md
Spec: docs/superpowers/specs/2026-10-28-runtime-phase1-design.md · branch feat/runtime-phase1 · start 9071aa5

## Preflight scan
| Pair / task | Produces → consumes | Found |
| --- | --- | --- |
| T3 ↔ T8 | guard teammate sentence ↔ worker.md teammate context rule | consistent |
| T3 ↔ T11 | event handling (Stop, PostToolUse) ↔ registrations Stop + PostToolUse SendMessage\|Agent | consistent |
| T4 ↔ T8 | `^Reason:` regex ↔ orchestrator "Reason: line" rule | consistent |
| T4 ↔ T11 | spawns.jsonl path + script ↔ registration + link | link must exist before settings go live (see R2) |
| T5 ↔ T6 | non-`completed` review-started ↔ `limit-hit/budget-hit <date>` | consistent |
| T7 ↔ T11 | lineage/<p>.jsonl ↔ migration target | consistent |
| T9 ↔ T11 | docs-report handoff path ↔ handoff dir move | consistent |
| T10 ↔ T11 | overrides.json ↔ settings swap | consistent |
| T1 ↔ T8 | refused orchestrator.md.patch ↔ folded into T8 | consistent |
| T12 ↔ T2–T6 | cites their numbers | consistent |
| T11 ↔ T13 / final review | T11 "after merge" vs SDD final review after all tasks | conflict (R1) |
| T1 | gate + merge | self-consistent |
| T2 | 7 cases vs code; real plugin used | self-consistent |
| T3 | band code vs AC | self-consistent |
| T4 | code run once by author (2 lines, fail-open) | self-consistent |
| T5 | K from PENDING.md `awaiting install` heading (heading exists) | self-consistent |
| T6 | budget probe is a paid API call | R3 |
| T7 | lib.zsh + python tests both need TC_LINEAGE | self-consistent (AC covers) |
| T8 | rules.zsh run RED by author | self-consistent |
| T9 | descriptions.py run RED by author (12 over) | self-consistent |
| T10 | row count = listed skills + 2 | self-consistent |
| T12, T13 | docs only | self-consistent |
Ruling: R1 T11 splits — (a) repo claude/settings.json + test_install on the branch before the final review; (b) live swap, links, handoff move, lineage migration after merge; T13 after (b); final review covers T1–T10, T11a, T12 — SDD final review needs all branch work done, T11b is live config — cost if wrong: final review misses the live half (it has no diff anyway).
Ruling: R2 after merge, create ~/.claude/hooks/spawn-record.sh link before anything else — agent-board sessions load repo settings from main, so a merge before the link makes Agent calls show a hook error — cost if wrong: a few non-blocking hook errors.
Ruling: R3 T6 budget probe (one claude -p, cap $0.01) is allowed — the plan requires one real run of the deciding command; cost ≤ $0.01 — cost if wrong: one cent.
Task 1: complete — 10-28 round installed e19c92f on main (6 by installer; CLAUDE.md, orchestrator.md by patch; writing-plans-extras §13 merged by hand); main merged into branch 391104f
Wave 1 dispatched (BASE 391104f, sonnet/effort-medium): T2 shortcircuit, T3 ctxguard, T4 spawnrec, T5 obstub, T6 reviewjob, T7 lineage, T10 overrides
Ruling: R4 T3 fixture is hand-built (type/isSidechain/usage only, numbers copied from 48822fd2's last main-thread line) because the auto-mode classifier denied capture_fixture.py on a real transcript; real-state replay kept as a separate read-only test — lead does not run the denied command for the teammate — cost if wrong: fixture drifts from the real line shape (replay test still covers the real file).
Task 6: report DONE 3f4b2e7, green check passed (verify rc=0); review dispatched
Task 3: report DONE_WITH_CONCERNS 5095b04, green (21/0); review dispatched
Task 4: report DONE 082e11f, green (28/0); review dispatched
Task 5: report DONE 3338a2f, green (47/0); review dispatched
Task 2: report DONE 29234ab, green (16/0); review dispatched
Task 6: review spec PASS / quality PASS, 0 C/I; minors :91-93 (log not live) and :87 ($5 default unbacked) taken into fix round 1 as load-bearing for an unattended multi-hour job
Task 6: minor (deferred): unanchored grep over whole output could mislabel a failing run that quotes the phrase
Task 10: report DONE (59 listed, 8 name-only proposed, 0 off); asked to commit
Ruling: R5 T6 minors :91-93 and :87 enter a fix round despite Minor label — an unattended job that loses its output when killed, or whose $5 cap cuts every review short, defeats item 1.4 — cost if wrong: one extra small round.
Task 4: complete (commits 3f4b2e7..082e11f, review clean)
Task 4: minor (deferred): spawn-record.sh:19 `\s*` in Reason regex crosses newline — use [ \t]*
Task 4: minor (deferred): spawn-record.sh:13 routing file only at <cwd>/docs/…; subdirectory cwd gives tier null
Task 4: minor (deferred): test default-path case untested; leak check skips once real spawns.jsonl exists
Task 3: review PASS/PASS, 5 minors; fix round 1 sent (band reset below threshold, silent unwritable dir, leak check + replay assertion)
Ruling: R6 T3 minors 3,4 (+1 test) enter a fix round — warnings suppressed after /compact until the old band is passed defeats item 1.9's purpose — cost if wrong: one small round.
Task 3: minor (deferred): brief's `redact_check.sh <dir>` errors — script takes files; fix in later briefs
Task 5: review spec PASS, quality 1 Important (no offer-the-review text when due); fix round 1 sent with minors hook:46, hook:38
Task 10: committed 053fad5; review dispatched
Task 6: fix round 1/5 (2 addressed pending re-review — live tee log + EXIT trap; budget default 25 from ≈$8.26 run ×3; commits 3f4b2e7..cd9cd5e)
Ruling: R7 T6 budget default 25 USD rests on assumed Opus-class list prices ($5/$25/$6.25/$0.50 per MTok) — no local price source; cap is a guard, not a quota — cost if wrong: a review cut short (marker budget-hit, visible at next session start) or a higher spend ceiling than intended.
Task 5: fix round 1/5 (3 sent — offer text, pinned wording, grep -F; commit fb2a5e6; 52/0) re-review dispatched
Task 3: fix round 1/5 (3 sent — band reset, silent unwritable, leak+replay; commit dc0710e; 27/0) re-review dispatched
Task 6: re-review 3/3 ADDRESSED; complete (commits 391104f..cd9cd5e via 3f4b2e7, cd9cd5e)
Task 10: complete (commit 053fad5, review clean)
Task 10: minor (deferred): overrides.md wording (Rule paragraph, pseudo-row, "1 calls")
Ruling: R8 T11 applies overrides.json minus anthropic-skills:skill-creator and anthropic-skills:find-skills — both have calls outside the two audited repos (2 and 2, all projects) — cost if wrong: ~600 chars kept in the listing.
Wave 2 dispatched (BASE dc0710e): T8 rules (fable), T9 skilltext (sonnet)
Task 5: re-review 3/3 ADDRESSED; complete (commits 082e11f..fb2a5e6 via 3338a2f, fb2a5e6)
Task 5: minor (deferred): regex-escape test uses `2026-10-2x` (x not a metachar) — passes on unfixed code; use `2026-10-2.`
Task 5: minor (deferred): hook:38 fixed-string match unanchored
Task 3: re-review 3/3 ADDRESSED; complete (commits 3338a2f..dc0710e via 5095b04, dc0710e)
Task 3: minor (deferred): test's generic STATE var could be inherited; leak check can flake if a live session writes a .band during the run
Task 2: review spec FAIL / quality FAIL — Critical: revalidate guard reads the transcript, task dir is emptied (4 of 9 gate sessions have empty dirs); Important: no test for it
Ruling: R9 T2 revalidate marker becomes transcript TaskCreate/TaskUpdate tool_use lines matching the gate words (spec 1.3 and plan AC amended); wait-guard keeps the task-dir marker, which its guard reads — the plan-mandated marker could skip a blocking Stop — cost if wrong: revalidate runs on a few more Stops than needed.
Task 2: fix round 1/5 sent (Critical marker, Important test, Minor stdin identity)
Task 9: report DONE_WITH_CONCERNS 00842b3 (descriptions ok 17, suites green); bounced 1/2 (handoff SKILL.md frontmatter fails yaml.safe_load — load-bearing for T11 link repoint) — fix + parse check requested
Task 9: bounce fixed 27b7ed9 (handoff YAML quoted; parse check; 17 ok; suites green); review dispatched
Task 9: review spec PASS / quality PASS with 1 Important (gitlab-ci-loop lost new/blank-repo trigger); fix round 1 sent with minors (tmux-orchestrator "watch a window", docs-explainer "or client")
Task 9: minor (deferred): descriptions.py strips quotes without unescaping; PyYAML-missing fallback unexercised
Task 9: fix round 1/5 (3 sent; commit 98cf823; descriptions ok 17) re-review dispatched
Task 2: fix round 1/5 (Critical marker → python scan of TaskCreate/TaskUpdate lines, 9/9 gate transcripts run the guard; commit c40485a; 20/0) re-review dispatched
Ruling: R10 T2's <100 ms skip AC holds for typical transcripts (~0.07 s); the largest (33 MB) skips in 0.25–0.59 s under load ~46, still below the guard's ~1 s median — scan cost grows with transcript size — cost if wrong: long sessions save less per Stop.
Task 9: re-review 3/3 ADDRESSED; complete (commits 00842b3, 27b7ed9, 98cf823)
Task 2: re-review 3/3 ADDRESSED (guard-arms=9 marker-matches=9 armed-but-skipped=0 over 1495 transcripts); redact_check clean (2 files, lead ran); complete (commits 29234ab, c40485a)
Task 2: minor (deferred): superpowers-hook.sh header says empty session_id passes through — now wait-guard only
Task 2: minor (deferred): gate fixture matches by three routes at once; no test isolates one
Task 12: dispatched (BASE c40485a, haiku/effort-low)
Task 8: report DONE_WITH_CONCERNS c204335, rules ok; orchestrator.md 20211→19336 (−875 vs AC −1500)
Ruling: R11 T8 accept −875 bytes — the AC did not subtract the ~925 bytes of lead rules the same task adds; the removed duplicates total 1783 bytes; meeting −1500 would cut rule 3 or unrelated prose — cost if wrong: ~600 bytes more per lead turn than planned.
Task 8: review dispatched
Task 12: report DONE_WITH_CONCERNS 3433be9 (verify 1 and 2; hook-test loop 6 files, 0 failed); "4 gate-marked" correctly omitted (task-dir count superseded by R9); review dispatched
Task 8: review spec PASS / quality PASS, 0 C/I; complete (commit c204335)
Task 8: minor (deferred, Medium): orchestrator.md:146-150 — rules 4–6, 8 reach teammates only via "read worker.md"; a teammate that skips the read loses pkill/tmux-ctl guards (kill-guard hook still blocks Claude-matching pkill)
Task 8: minor (deferred): worker.md Finish "Don't push, merge or delete" now binds teammates; ambiguous beside "as its brief says"
Task 8: minor (deferred): rule 3 in two files, rules.zsh does not check they stay in sync
Task 12: review PASS/PASS; complete (commit 3433be9)
Task 12: minor (deferred): upstream-task-observer.md:27 names a repo path and internal terms; upstream-superpowers-stop-hooks.md:10-11 probe figures lack their source/sample note — fix before any submission
Task 7: report DONE_WITH_CONCERNS 3da98ec (run-all rc=0, 34 files, 0 FAIL; lineage counts 1/13/2/13); bounced 1/2 (board/tests OK line of verifyCommand not captured)
Task 7: bounce fixed (verifyCommand board OK, 3 zsh ALL PASS, rc=0); review dispatched
Task 7: review PASS/PASS; complete (commit 3da98ec)
Task 7: minor (deferred): config/tmux.conf:19 comment says lineage deleted on close; test_tc_env.py:70-71 vacuous when XDG set; test_poll_efficiency/planview/activity read real lineage dir (read-only); artifact-register.sh:13 fallback untested
Task 7: note for T11: re-run wc -l on old lineage files before migrating (report and audit counts differ per file, both total 29); append, never overwrite
Task 11a: repo claude/settings.json committed de3ba8b (6 name-only per R8; Stop + PostToolUse SendMessage|Agent context guard; PostToolUse Agent spawn-record async); test_install ALL PASS rc=0, 0 FAIL
Final review dispatched (package e19c92f..de3ba8b, 21 commits, session model)
Final review: With fixes — I1 (Stop consumes context band; model never sees the warning), I2 (live settings has a permission the repo copy lacks — build 11b .next from live), M1–M6; board rc=1 1 FAIL (test_worktree_board timing flake 3.18s/3s at load ~33, 3/3 alone), all other suites rc=0 0 FAIL
Ruling: R2 premise corrected — sessions load claude/session-settings.json; claude/settings.json is a mirror, so the merge registers nothing; link-before-swap still applies to the live swap — cost if wrong: none.
Final fix wave dispatched (I1, M5, T4 default-path test, tmux.conf:19, M6)
Final fix wave: 4c46305 (guard 33/33, stub 54/54, spawn 30/30, superpowers-hook 20/20, rules ok); scoped re-review dispatched
Final fix wave: re-review 5/5 ADDRESSED (guard 33/0 rerun by reviewer); final review clean
Final: parked — context-size-guard.sh:31 Stop below threshold still removes the band file (untested) — Ruling: stands; matches the /compact reset intent — cost if wrong: one extra warning after a dip.
Final: parked — Stop repeats its user-visible warning in an unrecorded band until a UserPromptSubmit/PostToolUse records it — Ruling: stands; consequence of I1's fix, user-visible only — cost if wrong: repeated status line.
Remaining after merge: Task 11b (lead, live config), Task 13 (measurement)
Merge: feat/runtime-phase1 → main e28de44 (main had moved to 9c06adc; no conflicts); pre-merge branch merge 8c97122 resolved relay.py + ARCHITECTURE.md conflicts with main's start-dir fix
Task 11b: spawn-record link created; lineage migrated (agent-board 2, francisco_ruiz 13, interiors 2, master-gcp-repo 13; new files empty before); ~/.claude/settings.json.bak-20261028 + generated .next (permissions and all non-hook keys identical; 6 name-only, Stop + PostToolUse registrations) swapped; handoffs 47 → ~/.local/state/agent-board/handoffs, ~/.claude/handoffs now a link; skills/handoff → ~/agent-board/claude/plugin/skills/handoff (old ../../.agents/skills/handoff); fresh claude -p started (hit $0.05 cap — settings parse)
Resume 2026-10-28 21:35: Task 13 in worktree .claude/worktrees/runtime-phase1-measure, branch docs/runtime-phase1-measure from main 45781bb
Task 13: Ruling: "before" = docs/superpowers/reports/runtime-audit/report.md lines 9, 103, 172, 174, 182 (2026-10-25 audit-out JSON was deleted with the runtime-audit worktree; gitignored) — report figures were read from that JSON, so they are the same numbers — cost if wrong: before-values unverifiable at JSON level
Task 13: Ruling: "after" scope = sessions started at/after 2026-10-29T01:15Z (2026-10-28 21:15 EDT, the settings swap); after-window n will be tiny, stated per verdict; week-scale comparison deferred to the 2026-11-04 follow-up — cost if wrong: after medians not representative
Task 13: dispatch measurer (standard, sonnet), BASE 45781bb
Task 13: measurer DONE_WITH_CONCERNS 216971b (n=2 after-window); verify 15 rc0
Task 13: dispatch checker (task review, standard) on review-45781bb..216971b
Task 13: minor (deferred): claude/hooks/task-observer-session-start.sh is mode 644 (settings run it via sh; direct exec denied)
Task 13: review checker: spec ❌ (follow-up 2 not runnable), quality needs fixes; 0C/3I/5M
Task 13: Ruling: Stop after-figures = median over every stop_hook_summary in session 5387f433 up to a stated cutoff timestamp, n stated — the session keeps growing; a fixed cutoff makes the cell reproducible — cost if wrong: medians shift as more events land
Task 13: minor (deferred): measurement.md:13 say 21,213 is teammate's, 17,873 lead's
Task 13: minor (deferred): measurement.md:14 pooled 38,723.5 median of mixed kinds
Task 13: minor (deferred): measurement.md:49 spawns.jsonl "1 line" stale
Task 13: minor (deferred): measurement.md:53 no per-week find command for earlier weeks
Task 13: minor (deferred): after-column one-off python snippet not in doc
Task 13: fix round 1 commit 082fb4b (verify 15 rc0); re-review dispatched to checker
Task 13: fix round 1/5 (3 addressed, 2 new open — N1 all-sessions column is 32/35 tctest harness dirs; N2 "load noise" unevidenced; commits 216971b..082fb4b)
Task 13: Ruling: N1 — exclude test-harness transcripts (tctest / /private/var/folders / tmp) from the post-install column, rename it, reconcile every n statement — harness runs are not user sessions — cost if wrong: smaller n
Task 13: Ruling: N2 — reword to "cause not measured" (load cannot be recorded retroactively) — cost if wrong: none
Task 13: fix round 2 commit 2921a91 (verify 15 rc0); re-review 2 dispatched to checker
Task 13: fix round 2/5 (2 addressed, 0 open; commits 082fb4b..2921a91)
Task 13: minor (deferred): measurement.md says "large majority tctest" — exact is all 32 of 32
Task 13: minor (deferred): snippet's -tmp prefix filter would hide a real project folder starting with -tmp (none today)
Task 13: complete (commits 45781bb..2921a91, review clean)
Task 13: Ruling: no separate final whole-branch review — branch is Task 13's 3 commits on one doc, all covered by the task review and 2 re-reviews — cost if wrong: a cross-file issue the task review could not see (none possible, one file)
Task 13: idea filed (2026-11-04 follow-up); team shut down
