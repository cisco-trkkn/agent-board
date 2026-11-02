# SDD ledger — plan: docs/superpowers/plans/2026-10-28-overseer.md
Spec: docs/superpowers/specs/2026-10-28-overseer-design.md. Branch feat/overseer cut from main 486b284 (shared-context merged). Board baseline on 486b284: Ran 566 OK (verified post-merge); run-all 37 ALL PASS.
Preflight scan (plan verified on a59ffc7; main drifted in bin/tmux-ctl, bin/tmux-session-closed, board/server.py, board/index.html, tools/tests/lib.zsh, docs/ARCHITECTURE|INSTALL|CUSTOMIZATION.md; board/usage.py, test_usage.py, tmux-dev-layout unchanged):
| pair/task | produces → consumes | finding |
| T1→T2 | usage.spend_since/day_alert/OPTIONAL_ALERTS → overview alerts, spend_today | consistent |
| T2→T3 | RECORD_KEYS record → notify.conditions | consistent (same record shape in Global Constraints) |
| T2,T3,T4→T5 | builder, notifier, tmux-overseer → server thread + api/overview | consistent |
| T5→T6 | api/overview + token → tmux-ctl overview / overview CLI | consistent |
| T2,T6 share test_overview.py | T2 12 tests, T6 adds 3 (15) | serialized |
| T4,T5→T7 | tmux-overseer ensure/stop → layout, session-closed | session-closed rm line changed on main (lineage removed) — re-anchor |
| T5→T8 | api/overview payload → index.html home | index.html changed on main — re-anchor |
| T2 self | test_artifacts_newest_three_and_epoch writes <state>/lineage-proj.jsonl | main moved lineage to tc_env.lineage_dir() ($TC_LINEAGE) — fixture at wrong layout, epoch assertion would fail |
| T6 self | help sed range 2,31p → 2,33p | main is already 2,33p (context subcommand); overseer adds 2 header lines → 2,35p |
| T9 | docs lists | docs drifted (context rows added) — counts may shift |
| T10 | e2e on scratch board | depends on all; board count target = 566 + new board tests |
Ruling: Task 2's epoch test sets TC_LINEAGE to a temp lineage dir and writes the fixture at $TC_LINEAGE/proj.jsonl (tc_env.lineage_dir layout), not <state>/lineage-proj.jsonl — main moved lineage out of the state dir and artifacts.lineage reads only there — cost if wrong: one fixture path.
Ruling: Task 6's help range becomes 2,35p (main's 2,33p plus the plan's two header lines), with the help test checking the last line — cost if wrong: help prints one line short/long, caught by the existing help test.
Ruling: drifted hunks are re-anchored at the same semantic spot with the added text unchanged; Task 7's session-closed hunk keeps main's rm line (no lineage) — cost if wrong: placement only.
Ruling: board-suite count criteria are 566 + the board tests this branch adds (planner's 512 was on a59ffc7) — cost if wrong: none, OK verdict decides.
Task 1: dispatched ovr-impl, BASE 486b284
Task 1: green (test_usage Ran 102 OK; board 570 OK). Commits 486b284..44a2f6f; review → ovr-rev
Task 1: minor (deferred): spend_since with repo "/" or "" builds a degenerate prefix (no caller does); day_alert detail prints limit as written ($10 / $7.5)
Task 1: complete (commits 486b284..44a2f6f, review clean)
Task 2: dispatched ovr-impl, BASE 44a2f6f
Task 2: green (test_overview 12 OK; board 582 OK). Commits 44a2f6f..747b073; review → ovr-rev
Task 2: cross-task: overview.local_overview() calls server.window_activity(), which Task 5 must add (carry into Task 5 dispatch; Task 6 CLI exercises it)
Task 2: minor (deferred): last_run/recent_artifacts read $TC_STATE via artifacts.state_dir(), ignoring a differing state_dir param (plan-mandated); test cleanup pops env vars instead of restoring prior values; unused imports until Task 6; day alert key order
Task 2: complete (commits 44a2f6f..747b073, review clean)
Task 3: dispatched ovr-impl, BASE 747b073
Task 3: green (test_notify 17 OK incl one real osascript call; board 599 OK). Commits 747b073..12791e9; held for batch review 3-4
Task 4: dispatched ovr-impl, BASE 12791e9
Task 4: green (test_overseer 5 OK; board 604 OK). Commits 12791e9..c2d24a9
Batch 3-4: review dispatched to ovr-rev
Task 3: minor (deferred): real-banner test runs on every Mac suite run (consider TC_NOTIFY=0 skip); r["id"] KeyError on hand-built last_run; disabled path updates _last
Task 3: complete (commits 747b073..12791e9, review clean)
Task 4: Ruling: fix the plan-mandated read-only hole — allowed `git log/show *` accept `--output=<file>`, which writes; spec says the overseer never writes and settings enforce it — add denies for `--output` on git log/show/diff (both `git …` and `git -C * …` forms) plus `Skill` and `tmux-ctl context *`, and test them — cost if wrong: a few extra deny lines.
Task 4: minor (deferred): tmux-overseer new-session 2>/dev/null || exit 0 hides a real tmux failure
Task 4: fix round 1/5 dispatched (Important: git --output write hole; plus WRITE_TOOLS test omits MultiEdit/WebFetch/WebSearch), FIX_BASE c2d24a9
Batch 3-4: reviewed together (2 tasks)
Task 4: fix round 1/5 — commits c2d24a9..c10f659; test_overseer RED 6 subTest failures → GREEN 5 OK
Ruling: remaining overseer write paths the settings can't express as a prefix (shell redirection `git log … > f`, --ext-diff/--textconv) are settled by a real probe in Task 10's e2e: the live overseer is asked to run `git log --output=<scratch>` and `git log > <scratch>` and both must be refused with the scratch files absent — only live Claude Code shows how its matcher treats redirects — cost if wrong: one more deny line after the e2e.
Task 4: re-review round 1: 2 addressed, 0 open, no new breakage (rule matching checked by syntax only; live check in Task 10)
Task 4: complete (commits 12791e9..c10f659, review clean)
Task 5: dispatched ovr-impl, BASE c10f659
Task 5: green (test_overview_api 4 OK; board 608 OK; smoke on scratch port ok, no overseer session). Commits c10f659..15bb4ef; review → ovr-rev
Task 5: note: smoke showed agent-board record path = /Users/francisco.ruiz — pre-existing server.session_path() pane-path idea (already filed), not this branch
Task 5: minor (deferred): failed build re-runs per request while tmux is down (never cached); spend_today reconnects (WAL pragma + schema) per project per build
Ruling: Task 5 fix round 1 also takes three review items beyond the Important — ensure_overseer moved outside _overview_lock (a 20 s hang must not stall api/overview); TC_OVERSEER=0 set per-test with restore, not at import (leaks to every module); tmux-overseer starts the overseer in a dedicated dir ${XDG_STATE_HOME:-$HOME/.local/state}/agent-board/overseer instead of $AB_REPO, so its own usage session isn't counted toward agent-board's alerts/spend by cwd matching — cost if wrong: a trust prompt in the new dir, which Task 10's real overseer run would show.
Task 5: fix round 1/5 dispatched (Important: TC_OVERSEER=0 guard test asserts nothing; + the three items above), FIX_BASE 15bb4ef
Task 5: fix round 1/5 — commits 15bb4ef..7c54df9; test_overview_api 5 OK, test_overseer 6 OK, board 610 OK; re-review → ovr-rev
Task 5: re-review round 1: 4 addressed, 0 open, no new breakage
Task 5: minor (deferred): start-dir test asserts script source text; new start dir only zsh -n checked — Task 7 zsh test / Task 10 e2e must run ensure for real
Task 5: complete (commits c10f659..7c54df9, review clean)
Task 6: dispatched ovr-impl, BASE 7c54df9
Task 6: green (test_overview 15 OK; board 613 OK; help zsh tests ALL PASS). Commits 7c54df9..0361edf; deviation: fallback test isolated from live board via patch.dict; review → ovr-rev
Task 6: minor (deferred): CLI hides a board 200 error payload's error text (only --json shows it); tmux-ctl overview wiring (rc 1/2) has no automated test — Task 7 zsh test should cover; third minor in review-task-6.md
Task 6: complete (commits 7c54df9..0361edf, review clean)
Task 7: dispatched ovr-impl, BASE 0361edf
Task 7: green (test_overseer.zsh 24 ALL PASS; run-all run 2 rc0 0 FAIL 38/38; run 1 test_layout FAIL at load 58 debugged: no link to Task 7). Commits 0361edf..103f558; review → ovr-rev
Task 7: minor (deferred): 3 minors in review-task-7.md
Task 7: complete (commits 0361edf..103f558, review clean; run 1 test_layout FAIL ruled a load flake by ordering argument)
Task 8: dispatched ovr-impl, BASE 103f558
Task 8: reported DONE_WITH_CONCERNS (4a48b6b, index.html only; browser-checked on :7710; grep 10 not 9 — brief's own code has seenTs twice; board 613 with 1-2 load timing failures). Lead rerunning board suite before review (green-before-review)
Task 8: green (lead rerun at load ~5: board Ran 613 OK; implementer's 1-2 failures were pre-existing timing tests test_worktree_board / test_planview under load 20-30). Commits 103f558..4a48b6b; review → ovr-rev
Ruling: Task 8 Verify grep count is 10, not the brief's 9 — the brief's own code names dash.notif.seenTs on two lines — cost if wrong: none.
Task 8: fix round 1/5 dispatched (Important: header controls act on first project from Overview; overseer iframe collapses to ~190px; + Lead missing styled green), FIX_BASE 4a48b6b
Task 8: fix round 1/5 — commits 4a48b6b..0c0c560; browser-verified iframe 615px/879 (70%), controls hidden on Overview; re-review → ovr-rev
Task 8: re-review round 1: 3 addressed, 0 open, no new breakage
Task 8: minor (deferred): renderHome rebuilds DOM every 2 s poll; each open tab raises its own banner (tag dedups per tab only); requestPermission().then throws on callback-only Safari API; "Lead idle 0s" for a freshly ready lead (notifier uses 900 s)
Task 8: complete (commits 103f558..0c0c560, review clean)
Task 9: dispatched ovr-impl, BASE 0c0c560
Task 9: green (Verify grep ARCHITECTURE 8 README 2 INSTALL 1 CUSTOMIZATION 4; test_plugin, test_repo_paths ALL PASS). Commits 0c0c560..d2f784b; review → ovr-rev
Task 9: minor (deferred): day_total row could read as a Usage-tab/card alert (it's project-level only); overseer state dir + new modules/scripts missing from State paths / Repository layout inventories; INSTALL TC_OVERSEER=0 note doesn't say it won't stop a running overseer (stop --force does)
Task 9: complete (commits 0c0c560..d2f784b, review clean)
Task 10: dispatched ovr-impl, BASE d2f784b
Ruling: bin/claude-overseer clears CLAUDE_CODE_CHILD_SESSION before exec (unset, not a force flag) — the live tmux server's global env holds CLAUDE_CODE_CHILD_SESSION=1, so a real overseer would silently stop saving transcripts — goes into the final fix wave with a test — cost if wrong: one unset line.
Task 10: runs 1-4 failed on script bugs only (trust prompt defaults to "No, exit"; real-state calls inherited scratch env; live overseer self-refused probes so a permission-layer probe via claude -p --settings was added — all 3 write probes DENIED by rules incl. `>` redirect; ideas-dir check hashed dir mtime). No probe wrote a file in any run. Side effects: scratch transcripts under ~/.claude/projects, hasTrustDialogAccepted entries for scratch folders in ~/.claude.json (written by Claude), 2 real banners per run.
Ruling: the folder-trust prompt in the overseer's new start dir becomes a post-merge gate — start the real overseer once in ${XDG_STATE_HOME:-~/.local/state}/agent-board/overseer and see whether the dialog appears; if it does, the user accepts it once (a write to ~/.claude.json is theirs, not the plan's) — e2e ran under a scratch /var/folders path, which says nothing about a dir under the trusted home — cost if wrong: overseer pane parked at the trust dialog until accepted.
Task 10: green (run 5 E2E PASS, 21 checks ok). Commit e69854d; review → ovr-rev
Ruling: no full-suite rerun for Task 10 — since the last clean runs (board 613 OK at 4a48b6b, run-all 38 ALL PASS at 103f558) only index.html (browser-checked, no board test reads it), docs and the e2e script/report changed, and load is 139-151 from another worktree's agent — suites run again on the merged result — cost if wrong: caught at the merge-result run.
Task 10: review spec ✅ quality Needs fixes, 0/1/6 (review-task-10.md)
Task 10: Important: overseer read-only claim unsupported — --settings merges with ~/.claude/settings.json, whose allow list has Bash(tmux-ctl:*) (and any other user allows), so undenied tmux-ctl subcommands (_append writes an arbitrary file at bin/tmux-ctl:321, _done, _relay_failed) are allowed and the bare-overview probe proves nothing
Ruling: Task 10 fix round 1 (fresh standard implementer; touches Task 4 files) = (1) make the overseer's permissions independent of the user's settings: probe `claude --help` for --setting-sources (or equivalent) and start the overseer without the user source if available; else deny `Bash(tmux-ctl _*)` and every writing subcommand, and record which user allows still apply; (2) bin/claude-overseer unsets CLAUDE_CODE_CHILD_SESSION (earlier ruling); (3) e2e: add a `tmux-ctl _append` probe and one probe run with the user settings source excluded, and reword "no settings gap" to what the probes show; (4) list the 3 claude -p probe sessions per run among side effects. Spec: the overseer never writes, enforced by settings — cost if wrong: one more probe round.
Task 10: minor (deferred): real-state line count not cross-checked vs tmux session list; tmux-ctl artifact registration of the e2e report not done; usage.connect is write-capable (read-only claim overstated); 15 s no-refire check can't tell latch from 300 s rate limit
NEXT (for the next lead): dispatch Task 10 fix round 1 per the ruling above, scoped re-review, then final whole-branch review (deferred minors listed in this ledger), one fix wave, finishing-a-development-branch (ask user), merged-result suites, post-merge gate: start the real overseer once and check for the folder-trust prompt in ~/.local/state/agent-board/overseer.
Task 10: fix round 1/5 dispatched to ovr-fix (fresh, standard), FIX_BASE e69854d, brief task-10-fix-1-brief.md
Task 10: fix round 1 green (e2e E2E PASS 25 ok rc0; test_overseer.py 6 OK; test_overseer.zsh 24 ALL PASS). Commits e69854d..309c04e; re-review → ovr-rev (respawned)
Task 10: fix round 1/5 (7 addressed, 0 open; commits e69854d..309c04e)
Task 10: minor (deferred): _append e2e probe passes with or without the _* deny (catch-all refuses too; Python test pins the rule); report's "Every check" list and "fifth run" header still show the pre-fix 21-check run
Task 10: minor (deferred): --setting-sources project,local still loads project/local settings from the overseer start dir — note it in overseer.md or the spec; managed policy settings not excluded
Task 10: complete (commits d2f784b..309c04e, review clean)
Final review: dispatched ovr-final (session level), range 486b284..309c04e, plus merge-tree vs main e730fbd
Final review: 1 Critical / 4 Important / 7 Minor, With fixes (final-review.md)
Ruling: Final C1 — drop the three `Bash(git -C * …)` allows (and their now-moot `git -C` --output denies); keep the plain `git log/status/show *` allows and denies; overseer.md says history comes from the digest and Read/Grep/Glob, spec line 70 gets a dated note — the read-only guarantee is the spec's core ("read-only by permission settings, not by prompt") and outranks the git-history convenience; a wildcard before the verb can't be made safe by more denies — cost if wrong: the overseer can't answer git-history questions for repos outside its cwd; a fixed read-only wrapper (`tmux-ctl gitlog <project>`) can be added later.
Ruling: fix wave starts by merging main e730fbd into feat/overseer (resolutions per final-review.md Check 6) — I1's fix needs main's relay.session_root, and the merged result is what the suites must pass — cost if wrong: finishing takes a merge commit instead of a rebase; history only.
Ruling: fix wave scope = C1, I1, I2, I3, I4, Minors 1-7, triage fixes (Task 6 CLI error payload, inventories, stale e2e report), then one e2e rerun with the three C1 probes added — cost if wrong: a larger single wave; there is no second wave.
Final fix wave: dispatched ovr-wave (fresh, standard), FIX_BASE 309c04e
Final fix wave: PAUSED for the move to the dedicated tmux server. Commits 309c04e..dbd19fc (merge 038f73a; C1 1e6578b; I1 4c07b43 646fe4d; I2+I3 8f4f656; I4 2297fe8; minors/triage dd92ad4 1ea38da 9434f87 6e3c080 dbd19fc). Targeted tests OK at HEAD. Left: e2e to E2E PASS (rerun in flight at pause), e2e report edit, test_overseer.zsh rerun, both full suites, final-fix-report.md per-finding section. Notes in final-fix-report.md.
Final fix wave: minor (deferred): overview.local_overview (no-board fallback) still uses the pane path, not the session root
NEXT (for the next lead): resume the fix wave with a fresh standard implementer reading final-fix-brief.md + final-fix-report.md (finish the left items), then one scoped re-review of 309c04e..HEAD (ovr-rev role), adjudicate residuals, finishing-a-development-branch (ask user), post-merge gates (final-review.md).
Final fix wave: e2e rerun at dbd19fc finished after the pause: E2E PASS, 31 ok, 0 FAIL, rc=0, load 6.4, no tctest/overseer process left (output was in ovr-wave's scratchpad e2e.out; copy its checks into the e2e report on resume). Still left: e2e report edit, test_overseer.zsh rerun, both full suites, per-finding report.
Final fix wave: main moved to 1d26986 (session-path-root: a session's path is its project root, relay.session_root/main_checkout); merge-tree with dbd19fc is clean but overlaps I1 — on resume merge it and re-check I1 (4c07b43, 646fe4d) for redundancy.
Lead moved to the agent-board session's orchestrator; handoff 2026-11-02-overseer-final-wave-finish.md.
Final fix wave: resumed by new lead; merged main 1d26986 into feat/overseer: d2af619 (clean). test_overview_api 1 failure after merge (no session in build_state); test_session_root_path 21 OK, test_overview 17 OK.
Ruling: remove I1's `root` plumbing (build_overview's relay.session_root loop, overview's s["root"]) and keep the behaviour test — after the merge build_state's s["path"] is relay.root_for(#{session_path}), the same value, so the loop is a redundant tmux call per session per build; card path becomes the project root, as on every other board surface; this also closes the local_overview deferred minor — cost if wrong: one small revert.
Final fix wave: resumed with ovr-finish (fresh, standard), FIX_BASE d2af619, brief final-fix-resume-brief.md
Final fix wave: user reviewed preview on 7710: Overview page rejected (empty overseer panel, uneven spacing, unreadable text, ugly). User chose status rows over tidy cards.
Ruling: Overview redesign runs after ovr-finish on current HEAD (brief overview-ui-brief.md, standard tier, one writer) and the one scoped re-review covers it too — user-directed change, not a second fix wave; a concurrent writer would invalidate the final suites — cost if wrong: one more suite run.
Final fix wave: ovr-finish DONE_WITH_CONCERNS, commits d2af619..a863e32; e2e 31 ok rc0; test_overseer.zsh ALL PASS; board 681 OK; tools 15, docs-arch 45, compose 14, report 10, statusline 6 OK; run-all ALL PASS rc0; no .agent-ci.yml. Minor 3 = stale e2e report, fixed by a863e32.
Ruling: test-task-observer-session-start.sh failing in the tmux-ctl tests window is an environment dependency, not a branch regression — claude/hooks is unchanged against main and the test reads the real ~/.claude and task-observer workspace, passing from the Bash tool — cost if wrong: a hook test gap that already exists on main.
Final fix wave: Overview redesign dispatched to ovr-ui (fresh, standard), FIX_BASE a863e32, brief overview-ui-brief.md
Final fix wave: user reported interiors shown idle while busy. Root cause: paneclass.WORKING_RE needs "esc to interrupt", which Claude Code 2.1.316's spinner no longer prints ("· Spelunking… (6m 56s · ↓ 25.0k tokens)"), so every Claude pane reads ready; pre-existing on main. Reproduced on %18 and %100 while both were running.
Ruling: fix the spinner match in this branch via ovr-ui, and make the digest's lead status working when any Claude pane in the project works — the overseer's idle event and home status depend on it and would misreport otherwise — cost if wrong: a project with a stuck teammate shows Working; one small change.
Ruling: paneclass spinner fix moves off feat/overseer to fix/pane-working from main (pane-fix, brief under ~/.local/state/agent-board/briefs) — the bug is on main and breaks the restart guard and relay, so it should not wait for the overseer; feat/overseer takes it by merging main — cost if wrong: one extra merge.
Final fix wave: ovr-ui redesign e8e72b0 + lead_state a71763d; board 698 OK. Waiting on fix/pane-working merge to main, then merge main here and scoped re-review 309c04e..HEAD.
Final fix wave: fix/pane-working merged to main (4fc52c9, ff, user-authorised) and main merged here. Remaining minors: finished reply ending "⏺ Checking…" reads working; plain ─ rule above a dialog after a spinner reads working.
Gotcha: a Claude pane scrolled up hides its spinner, so it reads ready (seen on the lead %18); not fixed.
Final re-review: 14 addressed, 1 open (I2 board path = New-1), 5 Minor (final-rereview.md).
Ruling: New-1 is load-bearing (spec "a crashed or killed overseer is recreated"; a refused trust dialog on day one leaves it dead) — smallest fix: ensure_overseer calls bin/tmux-overseer ensure at most once per 60 s while the session exists, the script keeps deciding; one small dispatch plus re-check, not a second wave — cost if wrong: one zsh spawn a minute.
Ruling: Minor-A fixed in the same dispatch (the brief required rows not to jump): sort by name inside a group. Minors B, C, D, E parked: cosmetic, nothing builds on them — cost if wrong: small UI follow-ups; B's status colours are 3:1 on light theme.
Final fix: ovr-last 2b060e5 (ensure throttle + name sort); board 715 OK, test_overseer.zsh ALL PASS, run-all rc0, e2e 31 ok. Scoped re-check of New-1/Minor-A dispatched.
