# SDD ledger — plan: docs/superpowers/plans/2026-10-28-ideas-gitlab-sync.md
Spec: docs/superpowers/specs/2026-10-28-ideas-gitlab-sync-design.md
## Preflight scan
| pair / task | produces → consumes | finding |
|---|---|---|
| T1→T2 ideas.py | load()["issue"], set_issue(), Stale → sync reconciler | consistent |
| T2→T3 gitlab_sync.py, ideas.py | mapped(), sync(), conf_path seam → kick/_kick/board_info/server loop | consistent; set_issue never kicks (T1 has no _kick) |
| T2,T3,T5 ideas.py CLI under `python3 -I` | `ideas.py sync` lazy-imports gitlab_sync; kick runs `-I ideas.py`; T5 runs `-I` | DEFECT: py3.14 -I implies -P, sibling import fails (probed: ModuleNotFoundError) |
| T3→T4 /api/ideas | gitlab {repo,url,ok,error} + idea.issue → pollIdeas link/warn | consistent |
| T3→T5 | CLI dry run | consistent |
| T1 self | test count 38 vs diff | consistent (author ran 38 OK + mutation) |
| T2 self | Verify line = verifyCommand + suite prose | consistent |
| T3 self | kick test via TC_IDEAS_DIR seam vs T2 conf_path | consistent |
| T4 self | node harness exists (test_ideas_switch) | consistent |
| T5 self | expected count grep vs `create` line format | consistent |
Ruling: ideas.py's sync branch and gitlab_sync.py put their own directory on sys.path (`sys.path.insert(0, str(Path(__file__).resolve().parent))`) before importing the sibling; kick keeps `-I` — keeps isolation from cwd/env while making the sibling import work — if wrong: one import line to revert.
Task 1: dispatch impl-t1 (haiku/mechanical) BASE a7ec51c
Task 1: reviewer rev (sonnet) dispatched on a7ec51c..daf3669
Task 1: minor (deferred): edit() `if iid` drops gl#0 (theoretical)
Task 1: minor (deferred): no set_issue test on a `[-] … → moved to` line
Task 1: Ruling: add() must strip a typed ` · gl#N` like edit() does — carried into Task 3 (which edits add()) — else a typed token would let sync retitle/close an unrelated issue; cost if wrong: one extra strip line
Task 1: complete (commits a7ec51c..daf3669, review clean)
Task 2: dispatch impl (sonnet/standard) BASE daf3669
Task 2: Ruling: full-suite failure test_artifacts.MoveTest.test_move_file_and_sidecar is a pre-existing path-sensitive assert ("git" substring; worktree dir `ideas-gitlab-sync` contains it) — passes on main, not caused by Task 2, not a bounce — cost if wrong: a real regression in artifacts.move ships; final review re-runs suite on merged main
Task 2: minor (deferred): test_artifacts line 268 asserts "git" not in hook path — breaks under any path containing "git"
Task 2: reviewer rev dispatched on daf3669..4d06223
Task 2: ⚠️ resolved: test_move_file_and_sidecar passes on main (path artefact, see ruling above)
Task 2: Ruling: marker becomes `<!-- agent-board:<project>:<ts>#<n> -->`, n = 1-based position of the idea among ALL lines with that ts in the file (any status) — ideas are never deleted and moves leave the source line, so n is edit-proof; sha8 broke the spec's "token write lost (stale key) → no duplicate" — cost if wrong: a moved-in idea with an older ts could share an ordinal-shifted marker (adopt only exact match, so worst case one duplicate)
Task 2: Ruling: close-done/close-moved do PUT close first, then POST note — a retry after a failed note re-closes (idempotent) instead of double-posting the note; overrides plan's note-then-close order — cost if wrong: note may land after close in the issue timeline
Task 2: minor (deferred): dry run creates an empty .sync.lock file
Task 2: minor (deferred): RateLimited raised on a successful POST with Remaining 0 (adopt recovers next pass)
Task 2: fix round 1 dispatched to impl (FIX_BASE 4d06223): marker ordinal, close-then-note
Task 2: fix round 1/5 committed 4d06223..1b31814 (40 OK); scoped re-review dispatched to rev (standard)
Task 2: fix round 1/5 (2 addressed, 0 open; commits 4d06223..1b31814)
Task 2: minor (deferred): _marker uses todo.index(idea) — byte-identical lines share n=1 (already Stale-stuck, no duplicate)
Task 2: minor (deferred): close-first + failed note leaves GitLab closed, sidecar open — restore of a moved idea is refused by set_status, and a restored dropped idea's reopen is sent anyway; narrow
Task 2: Ruling: Task 3 updates spec + plan text to the ordinal marker and close-then-note order — docs must match code — cost if wrong: none
Task 2: complete (commits daf3669..1b31814, review clean)
Task 3: dispatch impl (sonnet/standard) BASE 1b31814
Task 3: impl committed f9b8bd2 (suite 531/532, known artefact); reviewer rev dispatched on 58b5849..f9b8bd2
Task 3: minor (deferred): a write during a running pass loses its own kick (sync.lock); next write or 60s tick picks it up
Task 3: minor (deferred): gitlab_loop sleep/repeat itself untested (only the pass)
Task 3: fix round 1 dispatched to impl (FIX_BASE f9b8bd2): loop spawns kick() not in-process sync (lockf per-process race); sys.path guard in _kick
Task 3: fix round 1/5 committed f9b8bd2..f545142 (kick 18 OK, actions 7 OK); scoped re-review dispatched to rev
Task 3: fix round 1/5 (2 addressed, 0 open; commits f9b8bd2..f545142)
Task 3: complete (commits 58b5849..f545142, review clean)
Task 4: dispatch impl (sonnet) BASE a6c0d84
Task 5: dispatch dryrun (sonnet) BASE a6c0d84 (parallel with Task 4; disjoint files)
Task 5: dryrun committed ebd39bf (7 creates = grep 7, hashes equal); reviewer rev dispatched on a6c0d84..ebd39bf
Task 4: impl committed f84b68c,f989108 (ui 4 OK, switch 2 OK); reviewer rev queued on ebd39bf..f989108
Task 5: Ruling: issue titles are capped at 255 chars (GitLab's title limit; real ideas are 248-334): longer text → text[:254] + "…"; description stays marker-only; sidecar title and retitle comparison use the capped title — fix in gitlab_sync.py by impl, then dryrun re-runs the dry run — cost if wrong (limit higher): long titles lose their tail on GitLab only; local text intact
Task 5: minor (deferred → fixed in report): dry run creates master-gcp-repo.md.sync.lock; report must say lock files appear
Task 5: minor (deferred): an empty marker search on the real instance is unproven until the user gate's second pass
Task 5: fix round 1 dispatched: impl (title cap, FIX_BASE f989108) then dryrun (re-run + wording)
Task 4: minor (deferred): report wrongly says url unvalidated (board_info hard-codes https://gitlab.com/<repo>); report omits colour commit
Task 4: minor (deferred): ok:false with empty error shows "GitLab sync: " (unreachable from Task 3 sources)
Task 4: minor (deferred): no visual/browser check; no test for dropped-row link or warning while editing
Task 4: complete (commits ebd39bf..f989108, review clean)
Task 5: impl title-cap fix committed f989108..45dd5a4 (43 OK); dryrun re-run with GET trace dispatched
Task 5: dryrun committed 07a7472 (7 creates, trace 7/7 GET, max title 255); scoped re-review dispatched on f989108..07a7472
Task 5: fix round 1/5 (3 addressed, 0 open; commits f989108..07a7472)
Task 5: minor (deferred): _title computed up to 3× per line; an adopted longer-titled issue is retitled once
Task 5: complete (commits a6c0d84..07a7472, review clean)
Final review: finalrev (session model) dispatched on 03b40d3..af71e48
Final review: done (final-review.md) — With fixes: 0 Critical, 2 Important, minors 1-6 can wait
Final review: Ruling: fix wave = I1 (non-JSON reply) + I2/Rec2/Minor6 docs + closed-adopted check (F3); minors 1-5 deferred as the review triaged — reviewer's triage stands — cost if wrong: a deferred minor surfaces after merge
Final review: Ruling: T4 browser check done by a read-only teammate uicheck in parallel with impl (disjoint, no writes) — keeps ONE fix dispatch — cost if wrong: none
Final fix: dispatch impl (sonnet/standard) BASE af71e48, brief final-fix-brief.md; uicheck (sonnet/standard, read-only) brief uicheck-brief.md
Final fix: uicheck PASS 3/3 (uicheck-report.md); A link contrast 1.67:1 real
Final fix: Ruling: link contrast (A) added to the same fix wave as F4 for impl, not deferred — a branch-introduced defect the user sees on every gl# row — cost if wrong: one extra small commit
Final fix: Ruling: 'Show dropped' no re-render (B) is pre-existing on main → filed as an idea, out of scope — cost if wrong: none for this branch
Final fix: impl committed af71e48..d9df82d (F1-F3; focused 87 OK rc=0; full 544, 1 allowed artefact failure); F4 pending
Final fix: impl F4 committed aa8cff7 (focused 87 OK rc=0; contrast 4.66/6.16 computed); fix wave af71e48..aa8cff7
Final fix: scoped re-review rerev (sonnet/standard) dispatched on af71e48..aa8cff7
Final fix: scoped re-review: all 5 ADDRESSED, no new Critical/Important (final-rereview.md)
Final fix: parked — dropped-row muted text 4.38:1 on light --panel-2 — Ruling: stands; --muted is the board-wide de-emphasis colour and the link itself passes — cost if wrong: one CSS tweak of --muted later
Final fix: parked — spec keeps an older sidecar-states sentence without closed-adopted, just below the new one — Ruling: no second fix wave; doc-only inconsistency, the new sentence is right — cost if wrong: a reader of the spec is briefly confused
Finish: merged into main as 9c06adc (--no-ff); board suite on merged main 548 OK rc=0; tools 15 OK, docs-architecture 45 OK, docs-compose 14 OK, docs-report 10 OK, hooks 6/6
Finish: run-all.zsh rc=1, 3 FAIL in test_bg.zsh (interrupted exit 143/summary, no stuck records) — reproduced under CPU load on unchanged code (diff a59ffc7..9c06adc over bin/ tools/ claude/hooks is empty); passes unloaded — Ruling: pre-existing timing flake, not a merge regression; filed as an idea — cost if wrong: a real tmux-ctl stuck-record bug stays on main until the idea is taken up
