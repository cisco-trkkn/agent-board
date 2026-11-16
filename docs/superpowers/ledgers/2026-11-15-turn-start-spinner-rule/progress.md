# SDD ledger — plan: docs/superpowers/plans/2026-11-15-turn-start-spinner-rule.md
Spec: docs/superpowers/specs/2026-11-11-turn-start-spinner-rule-design.md
Preflight scan:
| pair/task | produces vs consumes | finding |
| T1 x T2 | T1 makes working.txt live in spinner_live; T2's agreement test needs >=1 live fixture and idle_at_prompt calls spinner_live | consistent; T2 after T1 |
| T2 x T3 | T2 adds the agreement test over every .txt fixture; T3 may add turn-start-live.txt | consistent; T3 re-runs T2's suite |
| T1 self | tests (working.txt working, tip+⏺ ready, kept indented case) vs code (TIP_RE + in_tip) | consistent; plan author ran RED and GREEN once |
| T2 self | tests (agreement, argv, real pane) vs code (send_remove, spinner_live in idle_at_prompt) | consistent; prototype 64 OK, mutation fails on working |
| T3 self | note + optional fixture vs Verify (grep bullets, watch suite) | consistent |
Ruling: idle_at_prompt keeps an explicit spinner_live check on top of classify (spec offered either form) — a fresh mod state can say ready over a live spinner and the watchdog must not type then — cost if wrong: none beyond one redundant check.
Ruling: scratch-pane test uses bash --norc --noprofile, not the spec's cat — probe: cat echoes ^[[4~^[[D raw, zsh -f leaves abcXef~, bash leaves abcdef — cost if wrong: the test exercises bash's readline, not Claude's input box.
Ruling: Tasks 1-2 (mechanical) share one implementer and one batched review — cost if wrong: one reviewer reads two small diffs together.
Task 1-2: dispatched spin-impl (haiku/low), base 5bf2b9b
Task 1: bounce check green (verifyCommand rc=0, 38 OK; mutation rc=1), commit 7b4124c; review batched with Task 2
Task 2: bounce check green (verifyCommand 64 OK; mutation fails on working; grep 0; pgrep 0), commit ec10715
Batch 1-2: reviewed together (2 tasks) — dispatched spin-rev (sonnet/medium)
Batch 1-2: T1 spec ✅ Approved, T2 spec ✅ Approved; ⚠️ fixture verdicts resolved by lead (tests and fixtures pure additions, 0 removed lines; 60 pre-existing pass)
Task 1: minor (deferred): Ctrl+Y row accepted only as a tip continuation; no synthetic test pins it
Task 1: minor (deferred): RED run test name and exit code not captured in report
Task 2: minor (deferred): test_real_pane falls back to /opt/homebrew/bin/tmux and errors (not skips) without tmux (test_telegram_watch.py:238)
Task 2: minor (deferred): capture-pane failure in the poll loop raises CalledProcessError, not an assertion (test_telegram_watch.py:241)
Task 2: minor (deferred): stale tw-remove-* socket files seen, vanished with no known cause
Task 1: complete (commits 5bf2b9b..7b4124c, review clean)
Task 2: complete (commits 7b4124c..ec10715, review clean)
Task 3: dispatched spin-check (sonnet/medium), base ec10715
Task 3: live run1 finding — task-label spinner (multi-word) + task-list rows + column-0 "busy N · ready N [-]" row: worktree and main paneclass both say ready; board working came from mod state
Ruling: add Task 4 (standard) to widen paneclass for task-label spinners, task-list rows and the teammate status row, instead of parking it — same failure the spec targets (a working lead shown ready; the watchdog would call it idle) and present on every lead with an active task or teammates — cost if wrong: a wider spinner regex can call a transcript line ending in … live; limited by the spinner-glyph set and the column-0 rule
Ruling: Task 3 commits the run1 captures as fixtures now and re-runs the live loop after Task 4 to close
Task 3: finding committed by spin-check c7182bf (note + 3 live fixtures); live re-run pending after Task 4
Task 4: dispatched spin-wide (sonnet/medium), base c7182bf
Task 4: spin-wide stopped before code — idle-with-teammates fixture (786.286) identical in shape to the turn start
Ruling: idle-with-teammates fixture replaced with 1794710785.280 (last frame before the message row; no spinner line) — run1 shows the turn's spinner from 785.559, the mod state lagged ~1 s so 786.286 was a working frame mislabelled idle — cost if wrong: none for the rule; the fixture's provenance is recorded in its README line
Task 4: bounce check green (verifyCommand rc=0, 45 + 65 OK; 3 mutations fail as named), commit e76e40c
Ruling: idle-with-teammates stays out of Screens.test_idle_screens_are_idle — its input line shows `❯ keep going with the queue` (likely Claude's greyed suggestion; a plain capture can't tell) so idle_at_prompt is false; a separate test pins ready + no live spinner — cost if wrong: the watchdog idle verdict on a teammate lead with an empty input is only covered by the agreement test
Task 4: review dispatched to spin-rev (sonnet/medium), package review-59eeb3d..e76e40c.diff
Task 4: reviewed by spin-rev: spec ✅ (deviation accepted), quality needs fixes — 1 Important (indented prose ending … reads as live spinner; anchor glyph at column 0), 3 Minor
Task 4: minor (deferred): fixture_rows duplicates fixture-loading code
Task 4: fix round 1 dispatched to spin-wide (Important + TIP_RE double match + team-row-before-task test; '*' glyph kept only if used)
Task 4: fix round 1 by spin-wide, commit b30f0f4 (47 + 65 OK); '*' dropped (0 uses); scoped re-review to spin-rev
Task 4: fix round 1/5 (3 addressed, 1 open — '*' dropped from glyph set against the brief; commits e76e40c..b30f0f4)
Ruling: restore '*' to the spinner glyph set (column-0 anchored) — Claude Code likely draws '*' outside macOS; the column-0 anchor already closes the indented-prose false positive; the lead's own brief wrongly allowed dropping it — cost if wrong: a column-0 line starting '* ' and ending … above the rule reads as a live spinner (rare: assistant text is indented under ⏺)
Task 4: fix round 2 by spin-wide, commit a78275e (12 lines, 2 files; 48 + 65 OK); scoped re-review to spin-rev
Task 4: fix round 2/5 (1 addressed, 0 open — '*' restored; commits b30f0f4..a78275e)
Task 4: minor (deferred): round-1 column-0 anchor mutation not re-run after round 2 (negative subcases still guard it)
Task 4: gate (user): capture a spinner row on a Linux host (`tmux capture-pane -p -t <pane>` mid-turn) and confirm its glyph is in ·✢✳✶✻✽*
Task 4: complete (commits 59eeb3d..a78275e, review clean)
Task 3: live run2 (spin-check 397b453): pre-turn ready, first frame working, elapsed working; gap: 16/146 hook-suffix spinner frames (bracket starts with hook text, row wraps at 111 cols) classify ready
Ruling: add Task 5 (standard) for hook-suffix spinners, joined or wrapped — same failure class (working lead read as ready; watchdog would call it idle) and ~11% of frames in a real turn — cost if wrong: a wrapped-pair rule could join an unrelated column-0 row; limited to a row directly after a glyph row ending in an open bracket
Task 5: dispatched spin-hook (sonnet/medium), base 33e71af
Task 5: bounce check green (verifyCommand rc=0, 53 + 65 OK; RED 4 failures; 2 mutations fail as named), commit f1fb9cd; review to spin-rev
Task 5: reviewed by spin-rev: spec ✅, quality needs fixes — 1 Important (wrap handled only after the hook '·'), 3 Minor; run2 count: 16/16 real wraps break after '·' (2 hook name, 14 'N/N ·')
Ruling: replace the wrap head/tail regex pair with a general join (glyph row + directly following plain column-0 row, joined with or without a space, must match a spinner regex) — wrap points move with label length and width — cost if wrong: an unrelated plain column-0 row after a glyph row could complete a spinner; limited by the glyph anchor and the excluded leading characters
Task 5: minor (deferred): no test puts a team row or indented row between a wrapped head and tail
Task 5: minor (deferred): joined tests hand-concatenate real rows; spin-check's run3 -J capture settles the real joined shape
Task 5: fix round 1 dispatched to spin-hook (general join + (2 if wrapped else 1) once)
Task 3: run3 (spin-check 1bf5014): -J does not join hook-suffix wraps (24/24 two rows; Claude wraps itself); wrapped fixtures are the real board/watchdog shape; -J frames to classify at Task 5 HEAD
Task 5: fix round 1 by spin-hook, commit ae58ae1 (56 + 65 OK; RED 3 failures on f1fb9cd; mutation fails b,c,d + both fixtures); scoped re-review pending (next lead)
Ruling: accept spin-hook's deviation — the join is also tried when the head has an unclosed '(' even if the head alone matches SPINNER_RE (its ')' is optional); the joined row must still match — cost if wrong: none found; tightening SPINNER_RE would also work
Task 5: scoped re-review of fix round 1 dispatched to spin-rev (sonnet/medium), package review-f1fb9cd..ae58ae1.diff (new lead after relay)
Task 5: fix round 1/5 (2 addressed, 0 open — general join; (2 if wrapped else 1) once; commits f1fb9cd..ae58ae1)
Task 5: minor (deferred): a wrap landing right before '· 2s' (tail starts with '·', a glyph) still reads ready (paneclass.py:14,109)
Task 5: minor (deferred): a column-0 '*'/'·' prose row plus an unindented continuation ending … can read working (paneclass.py:108-109)
Task 5: complete (commits 33e71af..ae58ae1, review clean)
Task 3: close-out dispatched to spin-check (sonnet/medium): classify run3 -J at ae58ae1, task-3-report.md
Task 3: close-out by spin-check, commit 684a57b (run3 -J 195 working/196 ready, 0 disagreements; '·'-tail count 0/391; verifyCommand 33 + 65 OK rc=0); review to spin-rev, package review-task3-ec10715..684a57b.diff (Task 3 paths only)
Task 3: reviewed by spin-rev: spec ✅ (6/6), quality Approved, 4 Minor; fixtures cmp-identical to captures
Task 3: minor (deferred): note headline (line 3) and run2 "Gap found" read as current; add "Status at ae58ae1: fixed" under the title
Task 3: minor (deferred): criterion 3's literal classify command and output not pasted in the note
Task 3: minor (deferred): run1 capture median gap 0.28 s, above the 0.25 s target (run2/run3 meet it)
Task 3: minor (deferred): no real frame has a '·'-led wrap tail, so Task 5's residual minor has no real-data evidence either way
Task 3: complete (commits ec10715..684a57b, review clean)
Final review: dispatched to spin-final (session level), package review-d0009d3..684a57b.diff
Final review: spin-final: ready to merge, 0 Critical / 0 Important / 5 Minor; 56 + 65 OK at 684a57b; all 15 ledger minors stay deferred
Final: minor (deferred): a user prompt row (❯ > ›) is not excluded as a wrap tail; '✻ Worked for 5s' + a prompt ending … reads working (paneclass.py:26)
Final: minor (deferred): bare ◼/◻ task rows can keep a stale first-frame spinner live (needs an idle task list without its header; no real capture) (paneclass.py:30)
Final: minor (deferred): no test pins _do_reconnect's argv into send_remove (telegram_watch.py:470)
Final: minor (deferred): spec still says the elapsed-form rule is unchanged; Tasks 4-5 changed it
Final: minor (deferred): working.txt README line does not say it is a real capture
Final: gate (user): Linux spinner glyph capture still open (morning report)
