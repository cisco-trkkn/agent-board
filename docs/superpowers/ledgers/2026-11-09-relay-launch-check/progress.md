# SDD ledger — plan: docs/superpowers/plans/2026-11-09-relay-launch-check.md
Spec: docs/superpowers/specs/2026-11-09-relay-launch-check-design.md (read)
Preflight:
| pair/task | produces → consumes | found |
| T1↔T2/T3 | T1 notes may name an uncovered cause → lead adds a task | independent files; T1 runs in parallel |
| T2→T3 | relay.py retry/manual line → tmux-ctl _relay_failed reads `manual:`; e2e bad case needs --start-cap | consistent; both diffs applied on a scratch copy by lead: 20 relay tests OK |
| T2,T3→T4 | merged relay → real post-merge relay | T4 is a lead post-merge check, outside SDD |
| T2 self | patch ↔ tests: author ran RED/mutations; RED step used git stash | Ruling below |
| T3 self | same stash RED step | Ruling below |
Ruling: RED steps of Tasks 2-3 changed from tagged git stash to copy/restore of the one file — shared-worktree rule forbids stash — costs if wrong: nothing (same RED evidence)
Ruling: Task 4 (post-merge real relay) is run by the lead at the next handoff, outside the SDD loop, and listed as a user gate in the morning report — it cannot run before the merge — costs if wrong: a broken relay is seen only at the next handoff
BASE 2b70123
repro11 dispatched (Task 1, fable)
impl11 dispatched (Tasks 2-3, haiku)
Task 2: green check ok (411b795); batched with Task 3
Task 3: green check ok (6e419d5); Batch 2-3: review 2b70123..6e419d5
Batch 2-3: reviewed together (2 tasks); Task 2 spec ❌ (I1: notice built from attempt line), Task 3 ✅ minors; fix round 1 sent to impl11 (FIX_BASE 6e419d5)
Task 2: fix round 1/5 (4 addressed, 0 open — notice from attempt line; bad-notice e2e; test off real tmux; no-cd comment; commits 6e419d5..8207893)
Task 2: minor (deferred): notice reason ends "the pane shows:" — pane text only in the log (log path is in the notice)
Task 3: minor (deferred): nc check covers only the session_root-succeeds path
Task 2: complete (commits 2b70123..8207893, review clean after 1 fix round)
Task 3: complete (commits 411b795..6e419d5 + fix 8207893, review clean)
Task 1: green check ok (0e2c3b9); cause = tmux server cwd deleted, panes ignore -c; covered for relay only
Ruling: Task 1 root cause (tmux server cwd deleted; panes ignore -c) not covered by Tasks 2-3 → added Task 5 (tc_tmux new-session from $HOME; tmux-ctl agent line cds); health check filed as an idea; ~/.zshrc auto-open line and restarting the live server left to the user — costs if wrong: one extra small change in this branch
Task 1: minor (deferred): notes' suggested zshrc fix `( cd ~ && tmux … -c "$PWD" )` passes home as -c (wrong; capture PWD before cd)
Task 1: minor (deferred): repro used `!` bash mode (scratch config not logged in); disclosed
Task 1: minor (deferred): why the server started in home-study and the removal window rest on reflog/mtime, stated as fact in the chain
Task 1: complete (commits 8207893..0e2c3b9, review clean)
Task 5: green check ok (abf11a9); rev12 review 3eff335..abf11a9
Task 5: minor (deferred): a relative TC_TMUX or -S socket path would resolve from $HOME in new-session
Task 5: minor (deferred): test_tc_tmux_cwd uses sleep 1 before reading pane_current_path (could flake)
Task 5: complete (commits 3eff335..abf11a9, review clean)
Final: final11 dispatched 5e602c3..abf11a9
Final: With fixes, 0/2/3 (final-review.md); fix11 dispatched for I1 (ARCHITECTURE relay paragraph stale) + M3 (notes zshrc $PWD); FIX_BASE abf11a9
Ruling: final I2 (relay.root_for silently falls back to $HOME when session_path is gone, pinned by a test; pre-existing) not fixed in this branch — filed as an idea and named in the morning report — costs if wrong: a relay from a removed-worktree session still lands the lead in ~
Final fix: re-review ADDRESSED (abf11a9..42d9387), ready Yes
