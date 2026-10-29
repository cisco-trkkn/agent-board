# SDD ledger — plan: docs/superpowers/plans/2026-10-29-board-bugs.md
Spec: docs/superpowers/specs/2026-10-29-board-bugs-design.md (approved). BASE 9c1fb0b.
Preflight scan:
| Pair/Task | Produces vs consumes | Found |
| T2×T7 | both edit board/index.html (T2 pollIdeas, T7 Usage header) | ordered: T7 blockedBy T2; ok |
| T4×T5 | T4 field table + fixture → T5 reads field paths, tests on fixture | ordered; ok |
| T4×T7 | probe field paths, plan-limit presence → T7 overlay + block-or-label branch | ordered; T7 AC is conditional on the probe; ok |
| T5×T6 | T5 script path → T6 installs it | ordered; ok |
| T5×T7 | tap file shape (<state_dir>/statusline/<sid>.json + received_at) → T7 reader | consistent |
| T6×T8 | install → live tap files for e2e | ordered; ok |
| T1×T3 | server.py vs test_bg.zsh/bin/tmux-ctl | disjoint |
| T1 | tests (scratch server, 3 callers) vs code snippet | consistent; display #{session_name} probed: empty for a missing session |
| T2 | test code vs patch | consistent; author ran RED (2 fail) and GREEN on a scratch copy |
| T3 | files vs conditional tmux-ctl change | consistent |
| T4 | frontier, no steps; files vs AC | consistent |
| T5 | files vs AC | consistent |
| T6 | user gate; files list only INSTALL.md (settings.json outside repo) | consistent |
| T7 | files vs AC | consistent |
| T8 | read-only + 7710 board | consistent |
Ruling: T1-T4 run in parallel (disjoint files metadata); one shared worktree, each stages only its own paths — cost if wrong: index.lock retries
Ruling: T6 (user gate) is run by the lead itself, not a teammate — its first step is an AskUserQuestion to the user — cost if wrong: none beyond lead context
Task 1: dispatch sroot (sonnet/standard) BASE 9c1fb0b
Task 2: dispatch dropped (haiku/mechanical) BASE 9c1fb0b (parallel, disjoint)
Task 3: dispatch bgflake (sonnet/standard) BASE 9c1fb0b (parallel, disjoint)
Task 4: dispatch probe (fable/frontier) BASE 9c1fb0b (parallel, disjoint)
Task 4: probe committed b46148b (verify 4 rc=0; fixture parses, 0 /Users/); green check passed; reviewer rev (sonnet/standard) dispatched
Task 1: sroot committed f38c5aa (board 560 OK; 4 RED→GREEN; mutation 4 fail); green check passed; review queued to rev on b46148b..f38c5aa
Task 5: Ruling: Task 5 starts while Task 4 is in review — files disjoint, and the probe's field table is evidence-backed — cost if wrong: a review change to the field paths means a fix round on Task 5
Task 5: dispatch tap (sonnet/standard) on f38c5aa
Task 4: minor (deferred→fixing with follow-up): probe doc Sample prompt_cache.misses 0 vs fixture 1; turn numbering differs between sections
Task 4: complete (commits 9c1fb0b..b46148b, review clean); follow-up asked: start-payload fixture + the two doc minors
Task 2: dropped committed ed47713 (test_ideas* 63 OK; mutations fail as named); board suite FAILED 6 during concurrent Task 1 edit (both modules pass alone); real ideas file untouched; re-run asked
Task 1: minor (deferred): test_session_path :807 test's final out["repo"] assertion can't fail under the mutation (recorded-arg assertion carries it)
Task 1: complete (commits b46148b..f38c5aa, review clean)
Task 5: tap committed b66985a (6 OK; mutations fail as named); green check passed; reviewer rev dispatched on ed47713..a5bdd4a (with Task 4 follow-up a5bdd4a)
Task 6: user said yes (AskUserQuestion 2026-10-29): install statusLine at the worktree path now, re-point after merge; install waits for Task 5's review
Task 5: minor (deferred): closed stdout pipe makes the fallback print raise inside except → exit 120 (breaks "every path exits 0"); guard the fallback print
Task 5: minor (deferred): display_name with a newline prints two lines
Task 5: minor (deferred): a silent store failure leaves no trace (Task 7's empty state must not assume the tap works)
Task 5: minor (deferred): no tests for non-dict JSON or broken tc_env (reviewer checked by hand)
Task 5: complete (commits ed47713..a5bdd4a, review clean; a5bdd4a = Task 4 follow-up, addressed)
Task 2: board suite re-run: 560, FAILED 1 = test_worktree_board StopWaitsForExit wall-clock assertLess(3) at 3.008 s under load; not Task 2's code
Task 2: Ruling: Task 2's board-suite criterion counts as met — the one failure is a pre-existing wall-clock assert in an untouched module, under load avg 12-26 from parallel agents; it passed on the earlier run — cost if wrong: a real regression hides behind "flake"; the final review re-runs the suite
Task 2: green check passed; reviewer rev dispatched on f38c5aa..ed47713
Task 3: bgflake committed d667965 (cause: early-TERM bug — trap installed after the exit:null start record; 5/5 loaded passes; run-all rc=0 on rerun, first rerun failed "send returns fast" timing under load); green check passed; reviewer dispatched on a5bdd4a..d667965
Task 6: installed by lead: backup ~/.claude/settings.json.bak-20261029-statusline (a .bak-20261029 from 00:26 already existed, kept); jq diff without statusLine empty; command prints "Haiku 5.5 · ctx 4% · 5h 63%" rc=0 on the fixture; 13 live tap files within seconds; fixture-run tap file for the probe session removed from the real state dir; INSTALL.md 6dad3fd
Task 6: complete (user gate: AskUserQuestion yes; AC re-validated above)
Task 2: minor (deferred): a toggle during an inline edit is stored but not shown until data changes (pre-existing); pollIdeas(true) in done() would fix
Task 2: complete (commits f38c5aa..ed47713, review clean)
Task 3: review: spec ✅, quality needs fixes — Important: test_bg.zsh:36,52 tt_all_idle checks session tt, runs are in tt-bg (waits pass at once); test_bg.zsh:46 uncapped until-grep loop can hang
Task 3: minor (deferred): narrow window around RLOCKD release in append_capped (between rm -rf and RLOCKD=)
Task 3: minor (deferred): report says caffeinate -i, brief asked -w <pid>; report silent on failing iteration's full output + ps
Task 3: fix round 1/5 dispatched to bgflake (resume)
Task 7: dispatch usage (sonnet/standard) on 6dad3fd
Session resumed from handoff 2026-10-29-board-bugs-run.md; native tasks recreated (#1=T3, #2=T7, #3=T8)
Task 7: usage committed 9c37de4 (board 594 OK rc=0; 3 mutations fail as named); green check passed; reviewer rev dispatched on 6dad3fd..9c37de4
Task 3: fix round 1/5 resumed by respawned bgflake (uncommitted test_bg.zsh edit carried over)
Task 7: review: spec ✅, quality needs fixes — Important: usage.py:216-221 tap_entries out[sid]=d outside try, non-str/unhashable session_id raises into report(); usage.py:241 plan_limits compares float>str when received_at is a numeric string (store the float)
Task 7: minor (deferred): TapTest subclasses ReportTest and re-runs its 23 inherited tests
Task 7: minor (deferred): plan_limits uses only taps fresh within live_s, so the block disappears after 30 idle min (matches lead decision)
Task 7: fix round 1/5 dispatched to usage (fresh; original implementer's session gone) — includes robustness tests for non-dict JSON, bad received_at, non-str session_id
Task 3: bounced 1/2 (unloaded run 1 of 3 rc=1: "bg windows" and "read bg" failed after "tests is busy — using lane tests·claude"; same file, in Task 3 scope)
Task 7: usage committed 04af3ab (test_usage 137 OK; RED 1F/2E on 9c37de4; board 599 OK rc=0); green check passed; scoped re-review to rev on ea59f10..04af3ab (04af3ab only; ea59f10 is Task 3)
Task 7: fix round 1/5 (2 addressed, 0 open; commits ea59f10..04af3ab)
Task 7: complete (commits 6dad3fd..04af3ab, review clean; ea59f10 inside the range is Task 3)
Task 8: dispatch e2e (sonnet/standard) on 04af3ab
Task 8: e2e committed c3d8c85 (verify 4 rc=0; 21 tap files, 21 live rows, 21 source:tap, 21 within ±1, 21 model/effort match; transcript row via 515fe2c8 renamed aside and restored; 7710 stopped); green check passed
Task 8: Ruling: /api/usage?session=<name> scopes by /api/state's window-1 pane path (server.py:930), not session_path, so sessions whose claude window sits in ~ show the home project; accepted in-process usage.report() per project path as the comparison for those projects, and the scoping bug is out of this spec (spec (a) names session_path's three callers only), filed as an idea — cost if wrong: the Usage tab keeps showing the home project for those sessions until the idea is taken up
Task 8: reviewer rev dispatched on 04af3ab..c3d8c85
Task 8: minor (deferred): "21 within ±1" headline counts the 2 null-percentage rows; caveat follows (19 numeric + 2 null)
Task 8: minor (deferred): "in-process, 21 rows" is 20 in-process + the API home row
Task 8: minor (deferred): only the home lead row went through /api/usage; fallback row in-process (per lead ruling)
Task 8: complete (commits 04af3ab..c3d8c85, review clean)
Task 3: Ruling: the bounce cause (a fresh tt-bg tests pane read as busy at first use, so tmux-ctl opens a lane) is fixed in bin/tmux-ctl with a capped wait for a pane ensure_bg just created — it is test_bg.zsh flake root cause (spec (d)), not run recording, and hiding it in the test would leave real first use racy — cost if wrong: up to ~3 s extra on the first run into a brand-new bg session
Task 3: bgflake committed ea59f10 + c3c1679 (bounce cause fixed in tmux-ctl: BG_FRESH capped 3 s wait; test_bg_fresh mutation 3 FAILED→ALL PASS; unloaded 3/3, loaded 2/2 at 48 yes; run-all rc=0 grep -c FAIL=1); green check passed; scoped re-review to rev on d667965..c3c1679 (Task 3 paths only)
Task 3: fix round 1/5 (2 addressed, 0 open; BG_FRESH wait reviewed scoped; commits d667965..c3c1679)
Task 3: minor (deferred): a caller that loses the bg session-creation race gets no fresh-pane wait
Task 3: minor (deferred): bg_idle can pass early in an early-TERM trial if C-c lands before sleep starts
Task 3: minor (deferred): the fresh-pane startup mechanism is inferred (~5% under 48-yes load), never captured
Task 3: complete (commits a5bdd4a..c3c1679, review clean)
Final review: dispatched final (session level) on 0473a9e..c3c1679
Final review: with fixes — 0 Critical, 2 Important: (1) context alert/amber bar built from transcript % before _overlay_tap (usage.py:288, 247-251, 268; index.html:1467); (2) merge gate: re-point statusLine before the worktree is removed (already the lead's After-the-merge step); all 16 deferred minors + rulings: can wait
Final review: minor: tap builds the status line before storing, so a payload shape change also stops the store silently
Final review: minor: tap_entries parses every tap file per poll; old tap files never pruned
Final review: minor: tap-only row with null % shows "0%"
Final review: minor: spec liveness sentence ("has no tap file at all") contradicts spec line 58
Final review: fix wave dispatched to fixer (sonnet/standard): Important 1 + the null-% minor (same code)
Final review: fixer committed 19e5039 (RED 3 new; test_usage 140 OK; mutation fails; board 602 OK rc=0); green check passed; scoped re-review to rev on c3c1679..19e5039
Final review: fix wave re-review: 2 addressed, 0 open, no new breakage (commits c3c1679..19e5039); final review clean
