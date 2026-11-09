# SDD ledger — plan: docs/superpowers/plans/2026-11-05-mod-shell-hooks.md
Preflight scan:
| pair/task | produces → consumes | found |
| T1→T3,T4,T5 | probe note (deny shape, tool.call result, cwd, local time, agentId) → mod code | ok; later tasks read the note |
| T2→T3,T4,T5 | lib/env.js stateDir/lineageDir/markerPath/readEnv/writeMarker/removeMarker → mods | ok |
| T3,T4,T5 index.js | each adds import+thunks+register | sequential, one writer at a time: ok |
| T3-5→T6 | index.js imports → test_plugin.zsh asserts | ok |
| T1 self | verify counts 6 lines | ok |
| T2 self | tests in zsh files + env.test.ts vs code | ok |
| T3 self | deny shape depends on T1(d) | ok |
| T4 self | cwd/result fields depend on T1(a,c) | ok |
| T5 self | result fields depend on T1(b) | ok |
| T6 self | real run uses all | ok |
Ruling: spec "each listed in hooks.json modules" read as one file per hook behind index.js — the loader refuses a second module (spike) — costs nothing if wrong beyond a hooks.json edit.
Ruling: the three mods do not skip e.agentId events — the shell hooks they replace run for subagent calls too — if wrong, subagent calls get mirrored/guarded twice-or-never differently from today.
Task 1: dispatched hooks (standard/sonnet) base a58213c
Task 1: Ruling: probe note reviewed by the lead, no reviewer seat — the deliverable is a findings note whose every claim cites a log line, and Tasks 3-5 reviews and the Task 6 real run test each shape again — if wrong, a shape error surfaces one task later.
Task 1: Ruling: bash-mirror cwd = await $.session.cwd() read after next() (reference.md lists $.session.cwd), fallback session.start e.cwd; Task 6 real run checks it tracks a cd — if wrong, feed headers show the start dir after a persistent cd.
Task 1: Ruling: Write result shape unprobed; Task 5 keys off e (file_path) and isError, not the result body, for Write/Edit — if wrong, a failed Write could be recorded (file must exist anyway).
Task 1: complete (commits a58213c..d8f5324, lead-reviewed)
Task 2: dispatched hooks base d8f5324
Task 2: interrupted by system sleep ~20:36Z-23:13Z (caffeinate held; likely lid); hooks resumed 23:14Z
Task 2: bounce check green (rc=0 chain, mutation shown); review dispatched rev7 (standard) on d8f5324..c299175
Task 3: dispatched hooks base c299175 (parallel with Task 2 review; T3 reads env.js only)
Task 2: minor (deferred→folded into T3 dispatch): M1 kill-guard.sh TMPDIR='' gives /tmux-ctl-uid, mismatch with mod — fix (os.environ.get("TMPDIR") or "/tmp")
Task 2: minor (deferred): M2 artifact-register.sh marker check after mkdir/tmux display (two forks)
Task 2: minor (deferred): M3 writeMarker takes sid 3rd arg (carried to T3-5)
Task 2: minor (deferred): M4 $-helpers tested only via mods' start/end in T3-5 (T3 review must check marker path test)
Task 2: minor (deferred): M5 unused $ param in env.js get($,name)
Task 2: complete (commits d8f5324..c299175, review clean)
Task 3: bounced 1/2 (folded M1 TMPDIR fix missing)
Task 3: green after bounce (119/0, validate ok); review dispatched rev7 c299175..2c6bd79; Task 4: dispatched hooks base 2c6bd79
Task 3: minor (deferred): M1 own-ps skip dead (kill-guard.js:260); stale pid may appear in Instead run list
Task 3: minor (deferred): M2 Python-valid/JS-invalid pattern falls to substring (plan-mandated, documented)
Task 3: minor (deferred): M3 SIGKILLed session leaves marker; mods-active/ grows (no mute risk: sids unique)
Task 3: minor (deferred): M4 test stub answers unknown process.run with 503
Task 3: complete (commits c299175..2c6bd79, review clean)
Task 4: green (162/0, validate ok); review dispatched rev7 2c6bd79..ccbd100; Task 5: dispatched hooks base ccbd100
Task 4: review: spec ok, quality changes needed (I1 refusal strings mirrored as exit 1)
Task 4: Ruling: fold review minors M2 (don't await feed write), M3 (skip on non-ENOENT read failure), M4 (exit 3 case) into fix round 1 — M2 restores the shell hook's async behaviour, M3 prevents log loss — costs one larger fix diff.
Task 4: minor (deferred): M1 out.deny after next (tool ran, another mod withheld result) skipped; shell would mirror
Task 5: green (196/0, validate ok); review dispatched rev7 ccbd100..0dc0f0a
Task 5: review: spec ok, quality approved
Task 5: Ruling: "byte-identical" JSONL read as "equal as parsed JSON, same key order" — every reader parses JSON (artifacts.py, planview.py json.loads; tmux-ctl jq) — if wrong, a text matcher on the raw line would miss records.
Task 5: Ruling: the mod records Write/Edit/MultiEdit only; Artifact and Claude Docs stay on artifact-register.sh (its marker early exit applies to Write/Edit/MultiEdit only) — the mod-side result shape for those tools is unverified and verifying it means publishing a real doc/artifact in the user's account; a wrong guess would silently stop recording docs — costs the shell forks for those (rare) calls; lift once a real run confirms the shape.
Task 5: fix round 1 queued: the Docs/Artifact narrowing above + M1 (cheap path/kind filters before tmux/lineage/session.id) + M2 (sha256sum fallback)
Task 5: minor (deferred): M3 non-object manifest line skipped vs Python aborts lookup
Task 5: minor (deferred): M4 no symlink realpath test
Task 4: fix round 1 committed 3391ff9 (203/0); re-review dispatched rev7 0dc0f0a..3391ff9
Task 4: fix round 1/5 (4 addressed, 0 open; commits 0dc0f0a..3391ff9)
Task 4: minor (deferred): m1 tests use fixed 40 ms settle(), may flake under load
Task 4: minor (deferred): m3 user-declined dialog text unprobed (Task 6 real run: include one declined call if it can without a user)
Task 4: complete (commits 2c6bd79..3391ff9, review clean after 1 fix round)
Task 5: fix round 1 committed 4c25df3; re-review dispatched rev7 3391ff9..4c25df3; Task 6: dispatched hooks base 4c25df3
Task 5: fix round 1/5 (3 addressed, 0 open; commits 3391ff9..4c25df3)
Task 5: minor (deferred): m1 artifact record awaits hash/tmux/write for known-kind .md (bash-mirror no longer awaits)
Task 5: minor (deferred): m2 no symlink realpath test (also M3 non-object manifest line moot: Docs code removed)
Task 5: complete (commits ccbd100..4c25df3, review clean after 1 fix round)
Task 6: green (test_plugin ALL PASS, 19 OBSERVED, 193/0); real run passed incl. pkill denial on a 1-pid token
Task 6: Ruling: Task 6 has no separate task review; the session-level final review covers it — its diff is a manifest line, a test assertion and an e2e record whose observations the final reviewer reads — if wrong, a Task 6 defect is found one step later.
Task 6: minor (deferred → final review): $.session.cwd() lags one call behind a cd (cd call's entry shows the old cwd); shell used payload cwd
Task 6: complete (commits 4c25df3..2079830, covered by final review)
Final review: dispatched final7 (session level)
Final review: with fixes — I1 no marker after /clear,/resume (double feed entries); I2 read-modify-write append loses concurrent lines; minors: none block
Final fix: dispatched fix7 (standard) base 2079830
Final fix: fix7 lost to a forced restart (no commits after 2079830, no report); re-dispatched fix7b (standard) base 2079830 on 2026-11-09
Final fix: committed ed755a9..3529275 (verify chain rc=0, 199/0); re-review dispatched rerev7 (standard) 2079830..3529275
Final fix: re-review rerev7 — I1 ADDRESSED, I2 ADDRESSED; new N1, N2 (Important)
Final: parked — N1 bash-mirror has no re-key unit test (mutation survives) — Ruling: code stands; the reviewer's scratch test passes with the re-key and fails without it, and kill-guard/artifact-register cover the shared rekeyMarker helper — costs a future regression in bash-mirror's re-key call going unnoticed by tests.
Final: parked — N2 trim reads $.fs.stat(log).size, a shape the docs do not give — Ruling: merge as is and list a real probe as a follow-up in the report; a wrong shape reads size 0 and only skips the trim (feed log grows; every reader uses tail -n), never loses or duplicates an entry — costs unbounded feed-log growth until the follow-up.
