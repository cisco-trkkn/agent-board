# SDD ledger — plan: docs/superpowers/plans/2026-11-05-mod-team-band.md
Spec: docs/superpowers/specs/2026-11-05-mod-team-band-design.md
Preflight scan:
| pair/task | produces vs consumes | found |
| T1↔T2 | T1 team-band.js + hooks.json registration; T2 runs it via --plugin-dir | consistent (T2 reads only, creates e2e doc) |
| T1 self | tests (bandLine, mount, errors) vs code (bandLine, render, timers); files created vs touched | consistent |
| T2 self | AC expected line `Needs you: ✦ qrev · ? 1` vs bandLine rules (own pane out, foreign pane out, .tmp out, aged → ?) | consistent |
Ruling: ✦ window with no file = ?, other fileless windows ignored — spec "file missing" would otherwise count the tasks window forever — costs: a non-✦ agent window with no file is not shown
Ruling: freshest file per pane wins — /clear race leaves two — costs: none likely
Ruling: band keeps later mods' drawing via Box(Text, next(e)) — future band mods (spec 4) — costs: layout tweak if real render rejects
Ruling: redraw via $.ui.invalidate, no $.state — avoids manifest declaration — costs: none
Task 1: dispatched (standard/sonnet, base 3cc91a8)
Ruling: one hooks module per plugin (loader refuses a second "modules" entry) — mods/index.js imports and calls both register(on); hooks.json points at it; agent-status untouched — costs: if validate refuses imports, team-band must be inlined or go to a second plugin
Task 1: report green (55 pass rc=0, test_plugin rc=0, validate ok); commit 3b5f104; review dispatched (standard)
Ruling: team-band registers session.start/session.end with catch-all matchers ({surface:/.*/}, {reason:/.*/}) since one module can't register an event twice — costs: if a real event lacks the field the band never starts (Task 2 e2e checks)
Task 1: minor (deferred): bandLine own-pane and !panes.has guards are dead (loop over panes covers them)
Task 1: minor (deferred): ui.render catch calls next(e) again if the first next threw
Task 1: minor (deferred): 4 tests name no mutation; one stale comment
Task 1: minor (deferred): red1.txt shows only module-missing RED, not per case (mutations.txt covers 17 guards)
Task 1: minor (deferred): 2 s poll can overlap if a run is slow
Ruling: ⚠ session.end matcher {reason:/.*/} with no reason, and find() exact vs substring — left to Task 2 e2e (exact band text from real capture); a missed session.end only leaves timers until process exit — costs: timers run after /exit until the process dies
Task 1: complete (commits 3cc91a8..3b5f104, review clean)
Task 2: dispatched (standard/sonnet, base 3b5f104)
Task 2: report green (grep -c 5, rc=0); commits 8f8aaa2,4ee4e40 (peer file removed on /exit: yes); review dispatched (standard)
Task 2: review ❌ (3 Important: absence claims lack full capture/count; output without commands + hand edits; lead's own file never shown) — fix round 1 sent to bande2e (fix base 4ee4e40)
Task 2: fix round 1 done (commit 29d429b); scoped re-review dispatched to rev2
Task 2: fix round 1/5 (3 addressed, 0 open; commits 4ee4e40..29d429b)
Task 2: minor (deferred): peer file content not cat'ed in final run (only ls); $WT undefined in doc
Task 2: complete (commits 3b5f104..29d429b, review clean)
Final review: 0 Critical, 2 Important, 3 Minor (final-review.finalrev.md). I-1 pane list freezes after grouped _web-* view session dies -> fix wave (list-panes -t own pane). M-3 ($WT, tmux path) folded into fix wave.
Ruling: I-2 (one-entry-module pattern for later mods) — when spec 4 is planned, adopt option (a): index.js owns the single session.start/session.end and calls each mod's exported start/end in its own try/catch; spec 4's first task refactors agent-status + team-band to it; spec 7's "one module per hook in hooks.json" is read as one file per hook behind index.js — avoids per-mod regex catch-all matchers whose distinctness is undocumented — costs: a refactor of two merged mods inside spec 4, and one shared 10 s session.start budget
Ruling: M-1 (e2e lead never ran a turn or /clear) and M-2 (leftover status files read every 2 s) deferred — same render site, 2 files today; sweep belongs to agent-status/board — costs: a regression there shows only in the morning user gate
Final fix wave dispatched (standard/sonnet, base 29d429b)
Final fix wave: commit 839f6ce (56 pass rc=0); scoped re-review dispatched (standard)
Final fix wave: re-review clean (I-1, M-3 addressed; 0 new)
