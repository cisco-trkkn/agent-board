# SDD ledger — plan: docs/superpowers/plans/2026-11-18-reboot-auto-restore.md
Spec: docs/superpowers/specs/2026-11-18-reboot-auto-restore-design.md
Preflight scan:
| pair/task | produces vs consumes | finding |
| T1-T4 restore.py | T1 snapshot/save/load/restore_dir/boot_time -> T4 tick/restore | T4 extends same file, sequential (blockedBy) — ok |
| T2-T4 | DEV_NO_LEAD + agent-board restore dispatch -> T4 env + argparse main | ok |
| T3-T4 | send -m text-only -> T4 report | ok |
| T5-T4 | restore_schedule install/uninstall/status -> T4 argparse `schedule` | ok; T5 status reads snapshot via restore.load/restore_dir (T1) — T5 may import restore.py after T1 lands; brief says so |
| T4-T6 | seams TC_RESTORE_CTL/ORCH/DEV, snapshot --print -> e2e | ok |
| T6-T7 | merged main -> user gate | ok |
| T1 self | tests vs code consistent | ok |
| T2 self | AC --help moved to T4/T6 (fixed before commit) | ok |
| T3,T5,T6,T7 self | consistent | ok |
Ruling: R1 restore dir = agent_base()/restore, not state_dir() — TMPDIR state is cleared at reboot — if wrong: snapshot path differs from spec text only when TC_STATE unset
Ruling: R2 no DISCORD_STATE_DIR in lead env — claude-orchestrator:34 unsets it and derives its own — if wrong: a discord lead restores without its channel (caught by the reboot gate)
Ruling: R3 --model only when snapshot model non-null — orchestrator defaults opus — if wrong: none
Ruling: worktree recreated at f702497 after the board's sweep removed the ff'd one (no own commits, counted merged); locked until finish — if wrong: none
Task 1: dispatched rar-snap (sonnet) base daf19f0
Task 5: dispatched rar-sched (sonnet) base daf19f0
Task 2,3: dispatched rar-mech (sonnet; routing gate refused haiku while T1/T5 standard in progress) base daf19f0
Task 2: green check ok (rc=0 in report); batched with Task 3
Task 5: green check ok (10 OK rc=0); review dispatched rar-rev pkg review-ed01280..e46008f.diff
Task 1: green check ok (25 OK rc=0); review queued rar-rev pkg review-e46008f..b905c17.diff
Task 5: review spec ok, quality 1 I (cli path from __file__, no exec/worktree guard) -> fix round 1
Task 5: minor (deferred): status() unguarded restore import/call
Task 5: minor (deferred): vacuous assertIn("loaded") in a status test
Task 5: minor (deferred): main() exit-1 path untested
Task 5: fix round 1 committed f2fedf1; re-review queued
Task 1: complete (commits e46008f..b905c17, review clean)
Task 1: minor (deferred): _discord does not check token follows --channels
Task 1: minor (deferred): .next test would pass with a direct write
Task 1: minor (deferred): snapshot catch-all hides programming errors as tmux down
Ruling: Task 4 tick carries the previous snapshot's lead.session_id forward when the new one is null for the same project — a stale (>45 s) status file would otherwise overwrite a good id and a restore would fall back to --continue — if wrong: a relayed lead could resume an old sid for up to one stale window
Task 5: fix round 1/5 (1 addressed, 0 open; commits b905c17..f2fedf1)
Task 5: minor (deferred): without ~/.local/bin link, install from a worktree still schedules the worktree path; INSTALL lacks "run from main checkout" note
Task 5: complete (commits ed01280..f2fedf1, review clean)
Ruling: Task 3 widened to bin/tmux-ctl:48 header + its test check — usage text must match _dc_usage — if wrong: none
Task 3: green check ok (33 ok rc=0); follow-up 5b19682
Batch 2-3: review dispatched rar-rev (pkg review-batch-T2-T3.diff)
Batch 2-3: reviewed together (2 tasks)
Task 2: complete (commits daf19f0..ed01280, review clean)
Task 3: complete (commits f2fedf1..5b19682, review clean)
Task 3: minor (deferred): docs/INSTALL.md:253 still shows send <file>… [-m <text>]
Task 2: minor (deferred): dispatch test only greps; negative grep passes on empty capture (T6 e2e covers both)
Task 4: dispatched rar-snap base 5b19682
Task 4: green check ok (65 OK rc=0); review dispatched rar-rev
Task 4: review spec FAIL 1 C (bare sysctl/route not on plist PATH), 2 I (AbandonProcessGroup; session name from basename) -> fix round 1 (rar-snap, widened to restore_schedule.py)
Ruling: restore keys sessions by the snapshot entry name, not basename(path); dev still gets the path; mismatch recorded as a failure — snapshot name is what tmux had — if wrong: a renamed folder restores under a failure line instead of silently
Task 4: minor (deferred): already-open project makes awake report "no lead pid"
Task 4: fix round 1 committed 66e3f6b; re-review dispatched
Task 4: fix round 1/5 (3 addressed, 0 open; commits 580b8d4..66e3f6b)
Task 4: minor (deferred): group-name snapshot entry with no same-named session gives false "session name" failure
Task 4: complete (commits 5b19682..66e3f6b, review clean)
Task 6: dispatched rar-snap base 66e3f6b
Task 6: bounced 1/2 (no env -i launchd-like e2e case)
Task 6: green check ok (18 ALL PASS rc=0); review dispatched
Task 6: complete (commits 66e3f6b..5df0198, review clean)
Task 6: minor (deferred): second-tick check passes on a crash; "log unchanged" and new-boot snapshot unasserted
Task 6: minor (deferred): env -i case runs against a live scratch server; tmux server start from launchd env uncovered (reboot gate covers)
Task 6: minor (deferred): launchd case skip is silent (ALL PASS rc 0)
Final review: 0 C, 3 I (I1 e2e env -i drops TMUX_TMPDIR -> stray server + all.zsh red [confirmed: all.zsh FAIL 1/151 test_restore_e2e]; I2 `again` lost after next tick; I3 guards replay projects closed on purpose), 5 minor
Ruling: I3 — a running server with zero projects replaces the snapshot only after two ticks >=50 s apart both see zero; server-down never replaces; `schedule uninstall` marks the snapshot restored — closing everything on purpose must stick, while a shutdown race must not wipe it — if wrong: closing all projects then crashing within ~1 min restores nothing
Ruling: final fix wave also takes M1 (boot diff >60 s), M2 (LANG in plist), M4 (INSTALL MDM wording), M5 (log snapshot exceptions), T3 INSTALL:253 — each a few lines, all on the restore path — if wrong: none
Final: fix wave dispatched rar-snap base 5df0198
Final: fix wave 5df0198..15829c5, re-review 8/8 addressed, 0 new C/I
Final: minor (deferred): last-restore.json written without .next+rename; zero-project branch _write skips save guards (boot null harmless)
Final: all.zsh ALL PASS 151 jobs (rc=4 slow budget only), 0 FAIL
