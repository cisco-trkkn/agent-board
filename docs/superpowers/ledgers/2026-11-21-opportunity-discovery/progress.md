# SDD ledger — plan: docs/superpowers/plans/2026-11-21-opportunity-discovery.md
Spec: docs/superpowers/specs/2026-11-12-opportunity-discovery-design.md · branch spec-opportunity-discovery · base 52073ad (plan 174e81c)
Ruling: run records carry no test ids or HEAD, so flaky_test/slow_test read a new all.zsh history file (Task 1) — spec names run records/all.zsh records as sources — cost if wrong: both signals stay empty for a month.
Ruling: failed_run "on main" = cwd is the project's own checkout — run records carry no branch — cost if wrong: misses main failures run elsewhere.
Ruling: model gets Read only and returns rank JSON as result text; script writes rank.json — simpler sandbox than dream's Write allowlist — cost if wrong: none for the user.
Ruling: memory overlap = a memory proposal citing >=3 of the candidate's ledger dirs — memory proposals have no key — cost if wrong: a duplicate post line.
Ruling: button custom_id carries sha1(key)[:12], not the key — keys can exceed Discord's 100-char custom_id — cost if wrong: none (state maps kid->key).
Ruling: post ops gain `rows` (Task 5) — post `buttons` is one row of 5, the spec needs 2 buttons x 5 items — cost if wrong: a small bridge change.
Preflight scan:
| pair/task | shared | finding |
| T1-T2 | history file format (GC) | T1 writes, T2 reads; same GC block — ok |
| T2,T3-T4 | candidate shape (GC), function names | T4 imports both modules' named functions — ok |
| T4-T7 | board/discover.py, bin/tmux-ctl | T7 replaces T4's nightly placeholder; sequential (T7 blockedBy T6<-T4) — ok |
| T4-T8 | bin/tmux-ctl | T8 adds schedule route inside T4's discover block; sequential — ok |
| T5-T6 | post rows | T6 builds rows T5 accepts; T6 blockedBy T5 — ok |
| T6-T7 | discover_post API | T7 calls load_state/select/publish/build_op — names fixed in T6 AC — ok |
| T6 | discord_controls.py | only T6 touches it — ok |
| each task | own tests vs own code | consistent; T9/T10 checks only |
Parallel wave 1: T1, T2, T3 (files disjoint, no blockedBy between them).
Task 1: dispatched impl-t1 (sonnet, base 174e81c)
Task 2: dispatched impl-t2 (sonnet, base 174e81c)
Task 3: dispatched impl-t3 (sonnet, base 174e81c)
Task 2: review dispatched rev-t2 (sonnet, 174e81c..8691289)
Task 2: minor (deferred): test_final_record_per_id cannot fail under its named mutation (no null-exit start line; other tests cover it)
Task 2: minor (deferred): round() is banker's rounding on exact .5 percent growth
Task 2: minor (deferred): no test for the 20-item evidence cap
Task 2: complete (commits 174e81c..8691289, review clean)
Task 2: minor (deferred): needless self.lines.clear() in test_log_rc_zero_overrides_exit
Task 3: review dispatched rev-t3 (sonnet, 8691289..f309f36)
Task 5: dispatched impl-t5 (haiku, base f309f36)
Task 3: review rev-t3: spec ✅, 1 Important (url fill untested)
Task 3: minor (deferred): 20-item evidence cap untested; link() runs git remote get-url per evidence item; non-ASCII (git-quoted) paths skipped in todos parse
Ruling: todos counts a marker only in a comment (after #, //, /*, <!--, leading *, --) and skips paths with a tests/ or test/ dir segment — spec rule flagged 8 self/fixture candidates on this repo, noise to the user — cost if wrong: a TODO in a string or a test file is missed.
Task 5: bounced 1/2 (malformed-rows RED not re-run after the assertion was tightened)
Task 3: fix round 1/5 (2 addressed, 0 open; commits f309f36..f6ae46c)
Task 3: minor (deferred): todo comment check is a heuristic (a string holding // or -- before the marker, or a leading-* line, still counts)
Task 3: complete (commits 8691289..f6ae46c, review clean)
Task 4: dispatched impl-t4 (sonnet, base f6ae46c)
Task 5: green check passed after bounce (post-specific _check_rows call is redundant with the generic rows check; mutation of both fails)
Task 5: review dispatched rev-t5 (sonnet, f309f36..f069841)
Task 5: minor (deferred): post-specific _check_rows call in discord_feed._check is redundant with the generic rows check (plan-prescribed, harmless)
Task 5: complete (commits f309f36..f069841, review clean)
Task 4: review dispatched rev-t4 (sonnet, f6ae46c..652d848)
Task 4: review rev-t4: spec ✅, quality needs fixes (2 Important: unhashable key crash, stale rank.json on same-minute failure)
Ruling: plan defect — rank model runs with --restricted (Read confined to the run dir, proven in the memory plan's P1 probe) — the model reads untrusted text (TODO lines, ledger text, advisories) and its output is posted to Discord; unrestricted Read could leak any local file — cost if wrong: none.
Ruling: duplicate keys in the model's items are Important, not Minor — two items with one key give two buttons with the same custom_id, which Discord rejects, so the whole post fails — keep the first — cost if wrong: none.
Task 4: minor (deferred): title/why/risk have no length cap in validate (Task 6 build_op cuts text to fit)
Task 1: review dispatched rev-t1 (sonnet, 652d848..dfa56ae)
Task 4: probe (lead, real claude haiku): --restricted --tools Read --permission-mode dontAsk without --settings: Read collected.json in cwd OK (X=42), Read ../outside.txt refused (confined to working directory); cost $0.0008
Task 4: fix round 1/5 (4 addressed, 0 open; commits 652d848..c209963)
Task 4: complete (commits f6ae46c..c209963, review clean)
Task 6: dispatched impl-t6 (sonnet, base c209963)
Task 1: minor (deferred): history write runs before `total` is computed (adds ms to the reported time)
Task 1: minor (deferred): a non-git root nested inside a repo records the parent repo's HEAD
Task 1: minor (deferred): the interrupt test can pass without the run having started
Task 1: complete (commits 652d848..dfa56ae, review clean)
Task 1: minor (deferred): no test of two concurrent all.zsh runs writing the history (flock in place)
Task 6: review dispatched rev-t6 (sonnet, c209963..d925cfc)
Task 6: review rev-t6: spec ❌, 3 Important (regrown item reposted nightly; only why cut to 1900; state saved before outbox write)
Task 6: minor (deferred): ideas.add runs before the state write; a failed write after it files the idea again on retry
Ruling: the post header names the project (`🔎 discover <project>: <n> new`) — the user reads several projects' home channels and the night is in the timestamp — cost if wrong: header wording.
Task 6: minor (deferred): click records the decision before the edit op; a failed edit leaves the post un-edited (click returns error:)
Task 6: fix round 1/5 (6 addressed, 1 new open — A: unbounded URLs break the 1900 cap; commits d925cfc..fc1f2dd)
Task 6: minor (deferred): the "no half links" test assertion is nearly a tautology
Task 6: fix round 2 dispatched to impl-t6 (finding A; FIX_BASE fc1f2dd)
Task 6: fix round 2 committed by impl-t6 (fc1f2dd..d447d5a); scoped re-review pending (handoff)
Task 6: re-review dispatched rev-t6 (sonnet, fc1f2dd..d447d5a) after handoff
Task 6: fix round 2/5 (2 addressed, 0 open; commits fc1f2dd..d447d5a)
Task 6: complete (commits c209963..d447d5a, review clean)
Task 7: dispatched impl-t7 (sonnet, base d447d5a)
Task 7: review dispatched rev-t7 (sonnet, fe8bb57..c22e6fc)
Task 7: review rev-t7: spec ✅, 1 Important (a failed night exits 0; brief says exit 1)
Ruling: "failed" in the exit rule = any failed night (model failure, unfittable post, or a raising collect), so nightly exits 1 and a raising collect also counts toward failures and the log — the LaunchAgent exit status is the only failure signal outside Discord — cost if wrong: one extra failure count on a collect crash.
Task 7: minor (deferred): the "rearms" test does not test rearming
Task 7: minor (deferred): state read-modify-write in _fail and the reset runs outside the state lock (a click at the same moment could be lost)
Task 7: minor (deferred): the 85 % weekly boundary is untested
Task 7: fix round 1 dispatched to impl-t7 (FIX_BASE c22e6fc)
Task 7: minor (deferred): the critical post's 1900-char cut runs after escaping and could split an escape sequence
Task 7: ⚠️ outside-tmux run resolved by lead: `env -u TMUX TC_DISCOVER=0 bin/tmux-ctl discover nightly` prints `discover: off`, rc 0; the full path outside tmux is Task 10's real dry-run
Task 7: fix round 1/5 (1 addressed, 0 open; commits c22e6fc..26225a3)
Task 7: minor (deferred): the dry-run collect-exception test asserts no rc or outbox
Task 7: minor (deferred): exceptions after rank (select, publish OSError, _record) give rc 1 without a failure count or log line
Task 7: complete (commits fe8bb57..26225a3, review clean)
Task 8: dispatched impl-t8 (haiku, base 26225a3)
Task 8: review dispatched rev-t8 (sonnet, 26225a3..1e38741)
Task 8: minor (deferred): no separate mutation for the discover.off and `last night: none` branches
Task 8: minor (deferred): status reads TC_DISCOVER from the caller's env, not the plist's
Task 8: ⚠️ real launchctl install not run (side effect outside the worktree) — morning-report item with Task 10
Task 8: complete (commits 26225a3..1e38741, review clean)
Task 9: dispatched impl-t9 (sonnet, base e5e3933)
Task 9: real dry-run hit the weekly guard (94%); lead ok'd --force with the fake model (no real model call, nothing written)
Task 9: suite red FAIL 9/187 (bin/tmux-ctl help sed range 2,77p misses the 3 new discover usage lines); real-state checks met
Task 9: fix round 1 dispatched to impl-t9 (FIX_BASE 05c8dda; help range + header wording + dry-run outbox check)
Task 9: minor (deferred): deferred_minor signal counts a ledger line that is a ruling scheduling the fix (bridge.js candidate) — false positive on real state
Task 9: fix round 1 committed (05c8dda..67d562d, ALL PASS 187 rc=4); review dispatched rev-t9 (sonnet, e5e3933..67d562d)
Task 9: minor (deferred): the fake model used for the real-state dry-run lives outside the repo (not reproducible from the note)
Task 9: minor (deferred): dry-run summary line says "posted" though nothing is posted (board/discover.py:278)
Task 9: complete (commits e5e3933..67d562d, review clean)
Task 10: user gate — not run in queue mode; waits for the morning
Final review dispatched final-rev (session model, 52073ad..54cffe0)
Final review final-rev: ready with fixes, 0 Critical, 4 Important (history rows not filtered by root; exact-count "changed" reposts drifting counts nightly; second same-night post orphans first post's clicks; Task 10 gate names a run dir never printed + weekly guard)
Ruling: flaky_test/slow_test keep only history rows whose root is the project root or under it — the history file is global — cost if wrong: none.
Ruling: plan defect — "reported and changed → new" means the count grew ≥ 50% over last_evidence_count (the spec's dismissal regrowth rule); a drop or smaller growth stays still_open; stale_idea never counts as changed once reported (its count is age, not evidence) — spec says unchanged items are not reposted — cost if wrong: a real worsening under 50% waits in still_open.
Ruling: a non-dry nightly that finds posts[night] already set publishes nothing for that project and prints `discover: <p>: already posted <night>` — one post per project per night is the spec — cost if wrong: a forced re-run the same night posts nothing.
Ruling: fix the output, not the gate — --dry-run uses a normal run dir under discover/runs/ (Task 9's brief names it the one allowed write), keeps it, and prints `run dir: <path>`; the gate command gains `--force` only because weekly usage is ≥ 85% (a changed condition), noted on the task — cost if wrong: one kept run dir per dry-run (pruned with the others).
Final fix wave dispatched to impl-final (FIX_BASE 54cffe0; 4 Important + 2 minors: dry-run "posted" wording, state RMW under the lock)
Final fix wave committed by impl-final (54cffe0..53a3457, 133 tests OK); scoped re-review dispatched to final-rev
Final re-review final-rev: 6/6 ADDRESSED, no new Critical/Important — ready to merge (Task 10 user gate waits)
Final: minor (deferred): dry runs push real run dirs out of the newest 14; a dry run in the same minute as a real run overwrites that dir's collected.json/rank.json
Final: minor (deferred): a dismissed stale_idea never comes back (follows the ruling: stale_idea never counts as changed)
Final: complete (final review clean after one fix wave 54cffe0..53a3457; suite ALL PASS 187 rc=4)
