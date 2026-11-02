# SDD ledger — plan: docs/superpowers/plans/2026-11-02-session-path-root.md
Spec: docs/superpowers/specs/2026-11-02-session-path-root-design.md (approved 2026-11-02)
Preflight scan:
| pair / task | produces vs consumes | found |
| T1 → T2 | T1: /api/state path = root_for(#{session_path}); T2 reads /api/state path and /api/usage rows | consistent |
| T1 | tests (root_for, build_state, label_targets, api/usage) vs code steps (root_for, format +#{session_path}, field counts 16/10) | consistent; plan snippet run once by lead: RED errors=4, GREEN 4 OK, relay+restart 28 OK, cache mutation fails |
| T1 | files vs AC: fixture rows "any other test" beyond listed files | Ruling below |
| T2 | read-only + 7710 board; 4 sections | consistent |
Ruling: T1 may also touch fixture rows in board tests not named in its files list (e.g. test_restart_orchestrator, test_relay) when they feed build_state/label_targets/session_root — the AC requires every fake row updated — cost if wrong: a reviewer flags out-of-list files
Task 1: dispatch root (sonnet/standard) BASE 84eab26
Task 1: root committed 9b0a605 (RED 10E/1F; targeted 195 OK; board 613 OK rc=0; cache and window-1 mutations fail); green check passed; reviewer rev dispatched on 84eab26..9b0a605
Task 1: minor (deferred): no single test runs real root_for on a scratch repo+worktree into /api/usage (mapping and scoping covered in halves) — Task 2 real-state run covers the combined path
Task 1: minor (deferred): no test runs real tmux #{session_path} through build_state (rests on the lead's tmux 3.8 probe) — Task 2's 7710 board reads the live server's list-panes
Task 1: minor (deferred): a transient git failure in main_checkout caches the dir itself as its root
Task 1: complete (commits 84eab26..9b0a605, review clean)
Task 2: dispatch e2e (sonnet/standard) on 9b0a605
Task 2: e2e committed a370929 (verify 4 rc=0; 4 sessions; usage counts api=in-process agent-board 6/6, francisco_ruiz 0/0, interiors 2/2, master-gcp-repo 0/0; card paths = session_path; worktrees under roots; 7710 stopped); green check passed; reviewer rev dispatched on 9b0a605..a370929
Task 2: minor (deferred): per-row cwds/counts came from an unkept scratch script; saving it or its output would make the check reproducible
Task 2: minor (deferred): francisco_ruiz (0=0, root ~) lacks the "no row evidence" clause master-gcp-repo got
Task 2: minor (deferred): only agent-board exercises the .claude/worktrees/ branch of in_project
Task 2: closes Task 1 minor 2 (real tmux #{session_path} through build_state); Task 1 minor 1 stays open (covered manually only)
Task 2: complete (commits 9b0a605..a370929, review clean)
Final review: dispatched final (session level) on e730fbd..a370929
Final review: with fixes — 0 Critical, 3 Important: (I1) plain folder under ~ resolves to ~; (I2) root cache stale after git init, regression for session_root; (I3) main_checkout on poll path with no timeout/guard, a raise blanks the board; T1 transient-failure minor must-fix with I3; other deferred minors can wait
Final review: minor: M1 root_for runs per pane; M3 session started in a worktree loses lead match; M4 lead working in a worktree gets no card label; M5 bare repo/submodule wrong root; M6 ~2 s cold start
Task 1: Ruling: user approved the home guard (AskUserQuestion 2026-11-02), beyond the spec's wording; compare --show-toplevel as bin/dev does, not the reviewer's common-dir parent, or a worktree of ~ would stay itself — cost if wrong: a plain folder or home worktree gets the wrong root
Task 1: Ruling: I2 fixed by a per-folder own-.git staleness check in root_for instead of session_root bypassing the cache, so cards refresh too — cost if wrong: one stat per pane per poll
Final review: fix wave dispatched to fixer (sonnet/standard): I1, I2, I3, M2, M7, spec update
Final review: fixer committed f6e4bc6 + d723fb8 (RED 4F/4E; 4 modules 58 OK; board 624 OK rc=0; 4 mutations fail); green check passed; scoped re-review to rev2 on a370929..d723fb8
Final review: fix wave re-review: 6 addressed, 0 open, no new breakage (commits a370929..d723fb8); final review clean
Final review: minor (deferred): a start path inside .git now returns that path, old code returned the repo root; spec line "keeps today's outcome" is wrong for this unreachable case
