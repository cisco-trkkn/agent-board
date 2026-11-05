# SDD ledger — plan: docs/superpowers/plans/2026-11-05-mod-usage-gauges.md
Spec: docs/superpowers/specs/2026-11-05-mod-usage-gauges-design.md
Preflight scan:
| T1↔T2 | T1 index.js MODS + runAll + start/end exports; T2 adds usageGauges to MODS, exports start/end | consistent |
| T2↔T3 | T2 mod + tap path; T3 runs it via --plugin-dir | consistent |
| T1 self | grep ACs vs code (only index.js registers lifecycle) | consistent |
| T2 self | fixture from real file vs gaugeLine paths pinned in Global Constraints | consistent |
| T3 self | stale clear via received_at edit vs tap rewriting the file | risk noted in AC (edit between refreshes) |
Ruling: spec "add the module to hooks.json" impossible (one module per plugin) — wire through index.js — costs: none
Ruling: $.ui.status prefix "⚠ agent-board:" accepted; spec line is the text after it — costs: user may dislike the ⚠ prefix
Ruling: clear = $.ui.status('') pending Task 3 real check — costs: an empty prefix line if '' doesn't clear
Task 1: dispatched (standard/sonnet, base b0017ed)
Ruling: runAll takes thunks (validate refuses $ passed via m[fn]/alias/.call; module then fails to load) — named imports called inside thunks; 'missing export skipped' test dropped (load error instead) — costs: each new mod needs two lines in index.js (start/end thunks)
Task 1: report green (59 pass rc=0); commit 3106c82; review dispatched (standard)
Task 1: minor (deferred): hook-level index test doesn't guard runAll's catch (mods catch their own); wrong comment index.test.ts:464; unused e in start
Task 1: complete (commits b0017ed..3106c82, review clean)
Task 2: dispatched to gauge1 (standard/sonnet, base 3106c82)
Task 2: report green (79 pass rc=0, 10 mutations); commit 52fe942; review dispatched (standard)
Task 2: minor (deferred): inline fixture copy in test has no drift check vs fixtures/statusline-tap.json
Task 2: minor (deferred): tap file with no received_at is never stale
Task 2: minor (deferred): start() calls stop() without marking old record ended
Task 2: minor (deferred): no test at the exact 300 s boundary
Task 2: complete (commits 3106c82..52fe942, review clean)
Task 3: dispatched to gauge1 (standard/sonnet, base 52fe942)
Task 3: report: real line shown and matches tap; foreign ignored; stale clears text but $.ui.status('') leaves an empty "⚠ agent-board:" row — fix round 1/5 sent (probe undefined/null/()/' ')
Ruling: one status row per mod and the plugin is ONE mod (single module) — later mods (specs 7, 8) that use $.ui.status share agent-board's one row with usage-gauges — costs: those specs must compose one status text or use another site
Task 3: fix round 1 (status(undefined) removes row; commit 100f3bb, 79 pass rc=0); task review dispatched over 52fe942..100f3bb (standard)
Task 3: review ❌ (2 Important: foreign real session id committed in doc; fix-round RED/GREEN/mutation numbers only) — fix round 2/5 sent (fix base 100f3bb)
Ruling: the foreign session id stays in branch history (commit 597f7aa) after redaction in 99598e3 — a session id is not a credential and rewriting history in a queue run is riskier — costs: the id is readable via git log -p
Task 3: fix round 1/5 (status row clear; commit 100f3bb); fix round 2/5 (2 addressed, 0 open; commits 100f3bb..99598e3)
Task 3: complete (commits 52fe942..99598e3, review clean)
Final review dispatched (session level)
Final review: ready yes; 0 Critical, 1 Important, 5 Minor; all deferred minors can wait
Ruling: I-1 (gauges vanish after 300 s idle: tap only refreshes on events) — fix (a): INSTALL.md statusLine gains "refreshInterval": 60; the user's ~/.claude/settings.json is NOT edited (morning gate: user adds it) — keeps the spec's stale rule — costs: until the user adds it, idle sessions lose the row after 5 min
Final fix wave dispatched (INSTALL.md one line; standard)
Final fix wave: re-review clean (I-1 addressed; commit 069c30c)
