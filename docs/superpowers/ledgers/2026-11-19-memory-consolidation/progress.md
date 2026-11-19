# SDD ledger — plan: docs/superpowers/plans/2026-11-19-memory-consolidation.md
Plan 307f1fd by mc-plan (frontier). Native tasks #19-#25 (MC Task 1-7), user gates #26-#27 (MC Task 8-9). Parent queue task #5.
Ruling: accept plan S2 (model edits run-dir copies, script commits under the lock) over spec's live-edit+restore — a 15 min lock cannot coexist with "context add waits 5 s"; same outcome on failure (nothing committed) — cost: one more copy step if wrong.
Ruling: accept plan S1, S3-S15 (spec vs code notes in the plan header) as written — each follows current code — cost: per-item rework.
Preflight scan: NOT YET RUN (next lead runs it before dispatching Tasks 1, 2, 3, 6 in parallel).
Lead relayed 2026-11-19T02:51Z; native tasks recreated: #1 queue parent, #2-#8 MC Task 1-7, #9-#10 MC Task 8-9 (user gates).
Preflight: dispatched mc-preflight (standard) -> preflight.mc-preflight.md
Preflight: table in preflight.mc-preflight.md (34 rows: 25 pair, 9 per-task; 21 findings F1-F21). Rulings:
Ruling: F1 — each of T1/T4/T5/T7 raises the `55` in `sed -n '2,55p'` (bin/tmux-ctl help) by the header lines it adds, and its help check asserts the new line and the trailing blank — help otherwise truncates — cost: one more edit per task.
Ruling: F2 — T2 runs parallel to T1; T2's test_cap_matches_context is skipUnless(hasattr(context,'CAP')) and the lead re-runs T2's Verify after T1 commits — avoids serialising — cost: one re-run.
Ruling: F3 — parallel tasks commit with `git commit -m … -- <own paths>` — a shared index would mix commits — cost: none.
Ruling: F4/F5/F6 — accept suggested: inputs/ tree as T3 defines it is the contract T4's prepare builds; <repo> = checkout holding board/dream.py; T4 defines the result dict and out/run.json keys per F6 and keeps shared path helpers outside dream.py — cost: T5 rework if T4's shape is wrong.
Ruling: F7 — revert/file_proposals use locked(p, wait=3); on timeout the click audits `busy` and posts nothing (G11 gains `busy`) — never stall the overview tick — cost: a tap that must be retried.
Ruling: F8 — one append_missing(text, lines) helper in T4 (may use context._insert), reused by T5; nothing inside locked() calls context.add — one copy of the logic, lockf is per process — cost: none.
Ruling: F9 — G13 orders recall by the entry's own (first) date — the archived-on date is not the fact's date — cost: recall order.
Ruling: F10 — INSTALL insert after the paragraph at line 139 as its own section; discord_watch lines 526-533 — line numbers stale — cost: none.
Ruling: F11 — T1 also rewrites orchestrator.md's "Over 8 KB" bullet (nightly run condenses; hand-condense only after a failed night; archive path) — two conflicting instructions otherwise — cost: wording.
Ruling: F12/F13 — add the missing tests (T1: add's 5 s exit-2 path, fixed mutations with real deadlines; T2: the five untested acceptance items) — acceptance items need tests — cost: ~6 s more test time.
Ruling: F14 — if D/dream/<p>/<run id> exists, refuse as a skip `dream: <p> already ran this minute` (not a failure) — protects Revert backups — cost: a same-minute rerun must wait a minute.
Ruling: F15 — T8 adds --root ~/agent-board, re-takes the sha listing if a logged context add changed agent-board.md, and checks `status | head -1` equals `loaded` exactly (T7 makes status print exactly `loaded`/`not loaded` on line 1) — cost: none.
Ruling: F16 — T7 writes TMPDIR (when TC_STATE unset) into the plist EnvironmentVariables; T8 checks the guard sees a tap under launchctl kickstart — 85% guard would fail open — cost: one plist key.
Ruling: F17 — numbers are "about 53 KB / 216 entries"; no behaviour change.
Ruling: F18 — G7 also allows Write(core.md) and Write(archive.md); T3's gate probe adds them as allowed attempts and updates its `checked N attempts` count, T8 expects the new N — a whole-file Write would fail a night — cost: none (paths are the run-dir copies).
Ruling: F19 — context-recall accepts session_id only if ^[A-Za-z0-9_-]+$, else exits 0 silently — path safety — cost: none.
Ruling: F20 — T4 starts claude in its own process group (start_new_session) and killpg's that PGID on timeout — no orphan after a hung night — cost: none.
Ruling: F21 — T4's zsh test exports temp HOME, TC_TMUX and TASK_OBSERVER_WORKSPACE — no real-state reads — cost: none.
BASE 307f1fd. Dispatched in parallel: Task 1 mc-t1 (sonnet), Task 2 mc-t2 (sonnet), Task 3 mc-t3 (fable), Task 6 mc-t6 (sonnet).
Task 2: dispatch mc-t2 done 272c43d (green rc=0); mc-t2 shut down, fixes go to a fresh implementer
Task 2: review dispatched mc-rev2 (sonnet) on review-307f1fd..272c43d.diff
Task 6: mc-t6 done 969e17e (green rc=0, DONE_WITH_CONCERNS); sent back pre-review: fixture six-paths criterion untested.
Task 2: minor (deferred): check/counts drop parse problems of OLD files (dream_check.py:147) — carry to Task 4: check parse(old) problems before a run.
Task 2: minor (deferred): verify tracebacks on missing/non-UTF-8 --old-core/--new-core (:195-217).
Task 2: minor (deferred): absolute or `..` (files: …) path tested outside root (:160).
Task 2: minor (deferred): was_stale set built twice; dead .lock branch in test_real_files_parse; small report_problem/counts/diff test gaps.
Task 2: complete (commits 307f1fd..272c43d, review clean; F2 cap test re-run after Task 1 commits)
Task 2: F2 cap test re-run after 5e00c59: OK rc=0.
Task 6: fix pre-review 221ba85 (six-paths check, green); mc-t6 shut down; review dispatched mc-rev2 on review-task6-307f1fd..221ba85.diff (path-scoped).
Task 1: mc-t1 done 5e00c59 (green rc=0); review dispatched mc-rev1 (sonnet) on review-task1-307f1fd..5e00c59.diff (path-scoped).
Task 1: minor (deferred): context.locked treats every OSError as "held"; narrow to BlockingIOError/PermissionError.
Task 1: minor (deferred): over-cap notice reads size after lock release (negligible).
Task 1: minor (deferred): test_over_cap_notice does not assert lines[0] is the `added under` line.
Task 1: complete (commits 307f1fd..5e00c59, review clean)
Task 6: ⚠ plugin validate resolved by lead: "Validation passed with warnings" rc=0.
Task 6: minor (deferred): six-paths check only discriminates for 3 of 6 paths (board/ entries also match as siblings).
Task 6: minor (deferred): cap loop `break` lets one >4096-byte entry suppress all older matches; `continue` would not.
Task 6: minor (deferred): whole payload via env var; a huge first prompt could fail the exec silently with no marker.
Task 6: minor (deferred): 3 further minors in task-6-review.mc-rev2.md.
Task 6: complete (commits 307f1fd..221ba85 path-scoped, review clean)
Task 3: mc-t3 done 76d80ef (green rc=0; gate 13 attempts GATE OK; 3 real runs verify ok, $1.92). DONE_WITH_CONCERNS: merge path untested vs model; core 6-7 KB; ~/ paths cited.
Ruling: Task 3 concern ~/ paths — missing-files.txt lists repo-relative paths only; ~/ and / paths are never "missing" — they are outside the repo — cost: a stale out-of-repo path is never flagged.
Ruling: Task 3 F18 — mc-t3 found Write on the copies already allowed under G7's Edit rules; settings unchanged, gate probe covers both (13 attempts) — cost: none, probe proves it.
Task 3: review dispatched mc-rev1 on review-task3-307f1fd..76d80ef.diff (path-scoped)
Ruling: Task 8 gate expects `checked 13 attempts` (not 11) — F18 added two allowed Write probes — cost: none.
Task 3: minor (deferred): gate script has no guard on mktemp failure.
Task 3: minor (deferred): snapshot excludes prompt.txt/result.json/stderr.txt by name at any depth (could hide writes under inputs/ or out/).
Task 3: minor (deferred): R6 (Bash absent) only proves no bash.txt appeared.
Task 3: minor (deferred): no attempt covers inputs/core.md depth matching of Edit(core.md), nor Grep/Glob on an outside path.
Task 3: minor (deferred): dream.md byte-bound band allows up to cap+300; upper edge = cap would be tighter.
Task 3: complete (commits 307f1fd..76d80ef path-scoped, review clean; ~/ path cross-task item ruled above)
Task 4: BASE 76d80ef+ (HEAD at dispatch); dispatched mc-t4 (sonnet)
Task 4: mc-t4 done 085a890 (green: test_dream 33 OK, zsh ALL PASS rc=0; all.zsh ALL PASS 160 jobs, rc=4 SLOW 6m32s only). Sent back pre-review: archive-changed-during-run test missing (G8).
Task 4: minor (deferred): all.zsh SLOW 6m32s over 5 min budget (rc=4) — final review to triage.
Task 4: fix pre-review af74e48 (archive-rewrite test, green); review dispatched mc-rev1 on review-76d80ef..af74e48.diff
Task 4: review mc-rev1: spec ok, 0 Critical, 1 Important (uncaught per-project exception stops --all, no failures++, no run.json), 6 Minor.
Ruling: Task 4 minor `_kill_group` skips KILL after leader exits + communicate() without timeout is promoted into fix round 1 — a hung night blocks every later launchd run — cost: one small fix.
Task 4: minor (deferred): sources_digest recomputed after the run (ledger changed mid-run counts as seen).
Task 4: minor (deferred): model stdout/stderr not saved in the run dir.
Task 4: minor (deferred): failed run writes root into dream.json (G8 letter).
Task 4: minor (deferred): unused params in _restore and elsewhere.
Task 4: minor (deferred): cited paths with `..` not treated as outside the repo.
Task 4: fix round 1 e7a51c9 green (37 OK rc=0; zsh ALL PASS rc=0); re-review dispatched mc-rev1
Task 4: fix round 1/5 (2 addressed, 0 open; commits af74e48..e7a51c9)
Task 4: minor (deferred): `error: <Type>: <msg>` may be multi-line in the one-line G10/G11 output; cut to first line.
Task 4: minor (deferred): an exception in _finish after a successful commit records the night as failed.
Task 4: complete (commits 76d80ef..e7a51c9, review clean)
Task 5: BASE e7a51c9; dispatched mc-t5 (sonnet)
Task 5: mc-t5 done 6335220 (Verify green: 62 py OK, zsh ALL PASS). all.zsh FAIL 1/162 board/test_dream twice at load 9-11 (different thread-timed Task 4 tests). Sent back pre-review: flake + run-field.
Ruling: dream.json `run` advances only on outcome ok (a committed run); unchanged nights update last_run/digest only — so Revert of the last committed run stays valid — cost: one condition in dream._finish.
Ruling: the test_dream timing flakes are fixed in this branch before merge (systematic-debugging; no sleeps-as-sync) — a flaky suite would fail every later queue spec — cost: test rework.
Task 5: fix pre-review ad19c8c (run-advance + sentinel sync; 5/5 under load; all.zsh ALL PASS 162, rc=4 SLOW); review dispatched mc-rev1
Task 5: review mc-rev1: spec ok, 0 Critical, 1 Important (_append_missing verbatim copy), 4 Minor, 1 ⚠ (observer note template unverified).
Ruling: Task 5 Important — F6 and F8 collide; move append_missing into board/context.py as a public helper, dream.py and dream_actions.py both import it, delete both private copies — context owns entry insertion — cost: a small move.
Task 5: minor (deferred): file_proposals holds the context lock across up to 20 observer subprocesses.
Task 5: minor (deferred): a Revert tap between commit and _finish can name the wrong run in `stale:`.
Task 5: minor (deferred): observer notes filed by the job can come back as next night's input.
Task 5: minor (deferred): no test covers a missing diff.txt.
Task 5: fix round 1 b10b6e1 green (64 OK, zsh ALL PASS, test_context 27 OK, test_dream 36 OK); re-review dispatched mc-rev1
Task 5: fix round 1/5 (2 addressed, 0 open; commits ad19c8c..b10b6e1)
Task 5: minor (deferred): observer note title uses ensure_ascii (\uXXXX escapes).
Task 5: minor (deferred): import-order nit in test_dream_actions.py.
Task 5: complete (commits e7a51c9..b10b6e1, review clean)
Task 7: BASE b10b6e1; dispatched mc-t7 (sonnet)
Task 7: mc-t7 done e8f9cba (16 OK, zsh ALL PASS rc=0; all.zsh ALL PASS 163, rc=4 SLOW); review dispatched mc-rev1
Task 7: minor (deferred): failing bootstrap after bootout leaves job unloaded, plist not restored from backup.
Task 7: minor (deferred): OSError writing the plist ends as a traceback, not one-line exit 1.
Task 7: minor (deferred): zsh "nothing under real Library" check cannot fail.
Task 7: minor (deferred): usage-order nit for unknown subcommands.
Task 7: open for Task 8: whether `claude` is on the plist PATH under launchd — a real night shows `model error` if not.
Task 7: complete (commits b10b6e1..e8f9cba, review clean)
Final review: dispatched mc-final (session level) on review-d8be3cf..4e10021.diff
Final review mc-final: ready after fixes — 0 Critical, 2 Important (I1 tmux lookup without -L under launchd; I2 _finish vs revert race / revert ignores run.lock), 5 Minor; deferred #19 (save model stdout/stderr) and #26 (folded into I2) fix before merge; 33 leave; SLOW not caused by this branch (main already 5m55s-7m34s).
Ruling: final fix wave = I1 (paneclass.tmux_cmd() + TMUX-unset test), I2 (revert/file_proposals answer busy while run.lock is held, and _finish re-reads dream.json under the context lock), deferred #19 (out/model.stdout, out/model.stderr) — the three load-bearing items — cost: one fix wave.
Final fix wave: BASE 4e10021; dispatched mc-fix (sonnet)
Final fix wave: d5b45f3 (I1, I2, #19; targeted 133 OK, all.zsh ALL PASS 163 rc=4 SLOW); re-review dispatched mc-rerev (sonnet)
Final re-review mc-rerev: all 3 addressed (I1, I2, #19), no new Critical/Important; scratch env -i dry run: agent-board, interiors, signal-hub-gcp resolve; francisco_ruiz prints no repo root.
Final: parked — francisco_ruiz `no repo root` in the dry run — Ruling: not I1; that context file has no live tmux session or group of that name (the home-dir session is `main`) and the plist passes no --root, so skipping it is the designed behaviour — cost if wrong: that one project's memory is never condensed at night; seen in dream.launchd.log during Task 9.
Final: minor (deferred): a model timeout saves no out/model.stdout/stderr.
