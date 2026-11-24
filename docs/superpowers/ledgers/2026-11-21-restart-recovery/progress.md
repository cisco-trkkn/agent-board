# SDD ledger — plan: docs/superpowers/plans/2026-11-21-restart-recovery.md
Spec: docs/superpowers/specs/2026-11-10-restart-recovery-design.md (§4-5). Queue #13, batch 2026-11-21-1, up-front plan 2fddec6, stale check fresh.
Native tasks: T1=#134 T2=#135 T3=#136 T4=#137 T5=#138 T6=#139 T7=#140 T8=#133 (user gate).
Preflight scan:
| pair/task | shared | produces → consumes | found |
| T1–T2 | test_session_root_path.py | T1 FolderGone, root_for→None → T2 display `or p`, lead_info catch | consistent; T2 blockedBy T1 |
| T2–T4 | board/server.py | different regions (build_state/label_targets vs import+build_state return) | sequential; T4 after T2 |
| T3–T4 | — | T3 restore.tmux_server_cwd → T4 server_warning | consistent; T4 blockedBy T3 |
| T3–T5 | warning text | Python copy vs zsh copy must be byte-identical | reviewer of T5 checks against T3 |
| T1..T8 self | — | tests vs code in each brief; probe applied full code, 157 OK | clean |
Ruling: native task descriptions carry the tasks.json structured body with the long code in the briefs, not pasted — keeps the task list small — costs nothing, briefs are the source.
Ruling: T2 also gets blockedBy nothing beyond T1, and T4 is blockedBy T2 too (shared server.py) — serialises the two writers — costs one slot of parallelism.
T1 T3 T6 dispatched in parallel (disjoint files), BASE 2fddec6
Ruling: routing gate misread tiers after the 7 rejected TaskCreates; re-stated modelTier via TaskUpdate metadata, then dispatched — no bypass — costs nothing
Ruling: implementer-rules hardcoded an Opus trailer (my error; plan says harness trailer); 4688e2d keeps it, no amend in a shared worktree; rules fixed for later dispatches — costs one wrong attribution line
Task 6: green check ok (verify rc=0, 4688e2d); held for batched review with T3
Task 3: bounced 1/2 (brief mutation checks not run)
Task 3: green check ok after bounce (5 OK rc=0, 4 mutations caught)
Batch 3,6: review dispatched (rev-rr-t3t6, 2fddec6..7a7165c)
Batch 3,6: reviewed together (2 tasks)
Task 3: minor (deferred): lsof binary choice not asserted by a test
Task 3: minor (deferred): empty socket_path prints `-S  kill-server`
Task 3: minor (deferred): variable `l` naming
Task 6: minor (deferred): 2 doc notes, no action (see review-batch-t3-t6.report.md)
Task 3: complete (commits 4688e2d..7a7165c, review clean)
Task 6: complete (commits 2fddec6..4688e2d, review clean)
Cross-task: T5 zsh warning must equal restore.CWD_GONE byte for byte; INSTALL row claims list warning + banner + dev from ~ (T4, T5)
Task 5: dispatched impl-rr-t5
Ruling: T1 verify red on exactly BuildStateRootTest/LabelTargetsRootTest.test_removed_or_empty_start_is_home, which Task 2 owns and rewrites — accepted as green-for-T1, T2's verify must run both modules OK — plan defect (T1 verify spans T2's tests); costs a red window between T1 and T2 only
Task 1: green check ok under ruling (75/77, the 2 are T2's); review dispatched 7a7165c..db510fd
Task 1: minor (deferred): FolderGoneRefusalTest sits after the unittest.main() guard in test_relay.py (plan-mandated; fine under discover) + 3 more in review-t1.report.md
Task 1: complete (commits 7a7165c..db510fd, review clean)
Task 1 ⚠ checked: server.py 791 session_path / 1078 callers raise FolderGone (RuntimeError) → _act toast; T2 brief says no change needed there
Task 2: dispatched impl-rr-t2 (BASE db510fd)
Task 1: minor (deferred): _gone_root picks the wrong dir when the nearest existing parent is in a submodule or bare repo
Task 1: minor (deferred): any gone path under a repo maps to that repo, not only removed worktrees (matches the nearest-parent rule)
Task 5: bounced 1/2 (dev mutation in _tc_bins.zsh not run)
Task 5: green check ok after bounce (ALL PASS rc=0, both mutations caught, a6114a8); held to batch with T2
Task 2: bounced 1/2 (restart mutation not run); verify 86 OK rc=0, T1 modules 77 OK rc=0 (0587451)
Task 2: green check ok after bounce (mutation caught)
Batch 2,5: review dispatched (rev-rr-t2t5, db510fd..0587451)
Batch 2,5: reviewed together (2 tasks)
Task 5: minor (deferred): srv_*/lsof_bin globals at top-level script scope in tmux-ctl list
Task 5: minor (deferred): test srv_cwd helper calls bare lsof
Task 5: complete (commits db510fd..a6114a8, review clean)
Task 2: fix round 1/5 dispatched (Important: _lead_root FolderGone->"" branch untested; FIX_BASE 0587451)
Task 2: fix round 1/5 (small: +17 lines, 1 test file; verify 66 OK rc=0; mutation caught) e1e0211; scoped re-review sent to rev-rr-t2t5
Task 2: fix round 1/5 (1 addressed, 0 open; commits 0587451..e1e0211)
Task 2: complete (commits db510fd..e1e0211, review clean)
Task 4: dispatched impl-rr-t4 (BASE e1e0211)
Task 4: green check ok (12 OK rc=0; T2 tests 40 OK; 4 mutations caught; 0edeebe)
Task 4: review dispatched (rev-rr-t4, e1e0211..0edeebe)
Task 4: minor (deferred): server_warning has no lock; two threads at the 60 s edge may both run the check (duplicate lsof at worst)
Task 4: minor (deferred): check runs inline in the state poll; restore._run has timeout=10, so a hung lsof stalls the poll at most ~10 s per call, once per 60 s
Task 4: minor (deferred): .server-warn banner has no wrap/max-width in the flex header (long path may squeeze tabs)
Task 4: complete (commits e1e0211..0edeebe, review clean)
Task 7: dispatched test-rr-t7 (head 0edeebe)
Task 7: complete (no code; all.zsh ALL PASS 209 jobs rc=4, 0 FAIL; real state: cwd None, 9 sessions 0 None, list row, main unchanged)
Final review: dispatched rev-rr-final (2fddec6..0edeebe), report final-review.report.md
Final review: not ready (I 1, M 5); fix wave dispatched fix-rr-final (base 0edeebe): I-1, M-3, test_relay guard
Final fix: c542b3c (I-1, M-3, guard; 105 tests OK rc=0); scoped re-review dispatched rr-rereview
Final fix: re-review rr-rereview: 3/3 ADDRESSED, no new breakage (0edeebe..c542b3c)
Final: parked — M-1 Python lsof warning path never run against real lsof — Ruling: deferred; zsh test proves the shared format, parse is one line — if wrong, a Python-only lsof format slip hides the banner
Final: parked — M-2 board tests calling build_state touch live tmux + lsof — Ruling: deferred; read-only, cached 60 s — if wrong, a test differs on a machine whose server cwd is gone
Final: parked — M-4 relay.main prints a manual relaunch line with no cd after FolderGone — Ruling: deferred, optional per review — if wrong, a user may start a lead with no project folder
Final: parked — M-5 project_repo error text does not say the folder is gone — Ruling: deferred, still a refusal — if wrong, a confusing error message
Final review: complete (2fddec6..c542b3c, 4 parked minors)
User gate #133 (T8): closed 2026-11-23 19:15Z restart. ~/.zshrc:22 = `(cd ~ && tmux -L agent-board -f "$HOME/agent-board/config/tmux.conf" new-session -A -s main)` (one line); server pid 18085 lsof cwd = /Users/francisco.ruiz; restore.tmux_server_cwd() → None (no banner); `tmux-ctl list | head -1` = window row. Caveat: the server was started by the restore launchd job (`new-session -d -s _ops-bg`, WorkingDirectory=HOME, RunAtLoad + every 60 s), not by the ~/.zshrc line, so that path itself was not exercised. Ruling (user): close with the caveat — the restore job wins the race at login and after a kill — if wrong, a terminal that starts the server first could run it from a non-home cwd.
