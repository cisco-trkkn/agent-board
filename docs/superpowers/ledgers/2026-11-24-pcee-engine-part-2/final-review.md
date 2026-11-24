# Final whole-branch review: PCEE engine part 2

Reviewer: final-rev (frontier). Range `08c8601..00cb186` on `spec-pcee-engine-part-2` (23 commits, 56 files). Read-only: no source file edited, no git state changed.

**Verdict: ready after fixes.** Critical 0, Important 5, Minor 12. Two Important items (I1, I2) must be fixed before the merge; I3 needs a ruling; I4 and I5 can follow the merge.

## How this was reviewed

- Read in full at head: `engine/lib/engine/core.js`, `cli.js`, `queue.js`, `queue_report.js`, `lead.js`, `steps.js`, `integrate.js`, `inbox.js`, `policy.js`, `board/engine_lines.py`.
- Read as diffs: `bin/tmux-ctl`, `board/restore.py`, `board/server.py`, `board/discord_feed.py`, `board/metrics.py`, `db.js`, both backends, `claude/orchestrator.md`, the handoff skill, `docs/ARCHITECTURE.md`, the two metrics config files.
- Tests: read the test names of the queue, parking, report, restore and engine-lines files; did not read every test body. No suite was run (Task 14 owns that).
- One scratch run (isolated `TC_ENGINE_DIR`, fake backend, `TC_TMUX_CTL=/usr/bin/true`) to confirm I2.
- One read-only look at the real state: `~/.local/state/agent-board/engine/` does not exist on this machine, so the first real queue starts on an empty database and no part 1 database will go through the `ALTER TABLE` migration here.

## Strengths

- The pump's rule (one command, one event with `cause` and `idx`) holds for every new command; the queue-level writes that are not commands (`lead_turn`, `gate_result`, `parked_failed`, `queue_finished`, `unparked`) each sit behind a keyed step or an idempotent predicate. I traced a kill at each of them and found no double action.
- `queue.unfinished` is one predicate for `status --unfinished`, `start --preflight` and restore, and it covers the kill between the last spec's end and `queue_finished` (`queue.js:29-35`).
- The report hook reruns cleanly: outputs of the outside reads are cached in their step rows, the file name is fixed by the marker, and the commit is checked by its trailer inside the step (`queue_report.js:137-185`).
- The lead-lines design keeps the engine out of the lead's window; the cursor is the file's own tail, and the board moves its cursor only after the line left the queue.
- `tmux-ctl engine start` is tested against the real wrapper on a scratch tmux server with `$TMUX` unset, which is the launchd path.
- Aged-state tests exist for the two long waits (a 25 h lead turn, a 26 h parked spec).

## Critical

None.

## Important

### I1. Rulings R4 and R5 never reached the lead rule or its test (must fix before merge)

- Where: `claude/orchestrator.md:101` (the Engine queue block, step (3)) and `:107`; `tools/tests/test_queue_engine_rule.zsh` (no check for either).
- What: the block says "When `engine start` exits non-zero, run the queue as steps 2 to 5 say". R5 says exit 4 (an engine already runs) counts as started. The block also runs a third `metrics batch start` after step 1's and the up-front planning's, where R4 says the engine path replaces those two and the planner's `metrics start`, with the test pinning that sentence. `task-13-brief.md` carries neither ruling (its block text is the plan's), so the implementer and the reviewer never saw them.
- Failure scenario (R5): a lead that takes over mid-queue (a handoff, a relay, a restart) reads the block, enqueues again and runs `tmux-ctl engine start`. The engine is running, so it exits 4. The rule sends the lead to "run the queue as before": the lead and the engine now run the same specs in the same worktrees. The same happens when a `[Engine] stopped` line is delivered twice after a board restart.
- Failure scenario (R4): in this repo three batch lines are written per queue. The planners' `metrics start` lines carry the up-front batch id and the engine's `metrics start` carries the new one, so the K2 comparison this part exists for is fed from records whose windows start after planning.
- Fix: in the block, (a) "Exit 0 or 4 from `engine start` means the engine has the queue; any other code: run the queue as before"; (b) "A lead that starts with `tmux-ctl engine status --unfinished` exiting 0 skips (1) to (3)"; (c) R4's sentence; pin all three in `test_queue_engine_rule.zsh`.

### I2. A queue whose `engine start` failed leaves its enqueue rows live; the next queue runs them (must fix before merge)

- Where: `engine/lib/engine/queue.js:40-42`, `core.js:613-625` (`onEnqueue`), `claude/orchestrator.md:101` (the fallback).
- What: `enqueue` only writes inbox rows. When `engine start` then fails, the rule tells the lead to run the queue itself, and nothing drops the rows. `status --unfinished` exits 1 for them, so nothing shows them either.
- Failure scenario, confirmed in a scratch run: enqueue `a.md` (batch b1), no start; the next night enqueue `b.md` (batch b2) and start. The engine added both and wrote `[Engine] your turn: docs/a.md`. For an engine-run spec the engine would run last night's already merged plan again; if its worktree is gone, `wtOf` falls back to the main checkout (`core.js:156`).
- Fix (either): `onEnqueue` drops a row whose `batch` is not the batch of the newest enqueue row (reason `stale batch`), with a test; or a `tmux-ctl engine dequeue --batch <id>` that the fallback sentence names. The first needs no rule change.

### I3. `awake off` runs before the lead hears `queue finished`, so `ask` merge requests wait for the morning (needs a ruling)

- Where: `engine/lib/engine/queue_report.js:183`; `claude/orchestrator.md:101` ("its merge request is posted when the queue has finished") and `:108`.
- What: the hook runs `awake off` inside the report step, before `queue_finished` is written and the line is published. Queue mode arms the hold with `--lid`; with the lid closed the Mac sleeps when the hold is released.
- Failure scenario: a queue with `ask` specs ends at 03:00. The report is committed and published, the Mac sleeps, and the lead never gets the line until the lid opens. A remote user sees no merge request on Discord. Before this branch the lead posted each merge request during the night.
- This follows spec section 7 and 9 as written, so it is a ruling, not a defect of the implementation. Options: the engine skips `awake off` when the queue has an `ask` or lead-run spec and the `queue finished` rule ends with `tmux-ctl awake off`; or accept and say so in the PR.

### I4. A pane that quotes the limit sentence fails a finished job (Task 2's deferred minor, promoted; first fix after merge)

- Where: `engine/lib/engine/backend/claude_tmux.js:201-208`; `core.js:484`.
- What: the regex `/You've hit your (.+?) limit/` is unanchored and runs on the last 40 lines of any ready pane. `poll` emits the limit event before the report event, and `onWorker` fails the attempt on a limit state without looking at the report.
- Failure scenario: a worker whose last lines quote the sentence (a review of this backend, a test output, a diff) is ready with a valid report. The job is failed as `model_limit` and rerun on Opus, or as `usage_limit`, which pauses the whole engine for up to an hour. Both recover by themselves, which is why this can follow the merge, but they cost tokens in the runs K2 measures.
- Fix: anchor the match to a line start (`/^\s*You've hit your (\S+(?: \S+)?) limit/m`), and in `onWorker` finish the job from a valid report before treating a limit state as a failure.
- Open, for Task 15: the fixtures come from transcript text, not a real pane capture. Any wording other than `5-hour`, `weekly` or `session` is treated as a model limit.

### I5. The first real queue runs on paths no real command has exercised (merge-gate items for the PR)

Not a code defect: these are the checks an agent could not run. Each belongs in the PR description as an unchecked item with its command.

- Task 15 itself (the plan's gate).
- `python3 -I board/metrics.py gate K2 --log docs/superpowers/metrics/runs.jsonl` on `main` prints `gate K2: too early`, rc 3 (ledger l.44).
- One real `tmux-ctl metrics gate <id>` and one gate-failed `metrics record` (Task 7 minor 4).
- A second, unstubbed `tmux-ctl engine start` against a running engine exits 4 (ledger l.86).
- One real job ends with integer `tokens` in its `job_done` event; if the session id does not resolve to a transcript, every job parks `cost unknown` (ledger l.66).
- One real `metrics append ask` line after a real answer (Task 4 minor).
- Every feed line with `src` has `kind` and `spec` once an engine has run (command in `rev1-task-11-review.md`).

## Minor

1. `cli.js:339-342` — `engine resume` prints `nothing to resume` when every spec is done and no step is at intent, while `status --unfinished` exits 0 for the same database (a kill between the last spec's end and `queue_finished`). With a step at intent it reconciles and stops, also without the queue's end. Restore and the lead rule use `engine start`, so nothing breaks today. Fix: `cmdResume` uses `queue.unfinished` for its early exits.
2. `claude/orchestrator.md:108` — the rule says the engine "wrote and committed" the report. The line can be `[Engine] queue finished: (no report)` (R15; then `awake off` did not run either), and the report can be left uncommitted (`report_uncommitted`). One sentence each: write the report as step 5 says and run `awake off`; commit the report with the rulings.
3. `queue.js:70-73` — a kill between the `queue_finished` event and the last `publish`, or a failing last `publish`, loses the line for good: `start --preflight` then says there is nothing to do. Fix: `preflight` also answers 0 when the lead file is behind the events.
4. `docs/ARCHITECTURE.md:307,321` — the Engine section does not describe what `tmux-ctl engine start` does: the `engine` window in `<project>-bg`, `--session` outside tmux, `--here`, the log `<engine dir>/<project>.log`, `TC_ENGINE=0`. The exit-code line says `start: 0 queue finished`; for the command the lead runs, 0 means the window opened, 1 that the engine exited at once, 2 `TC_ENGINE=0`, 4 also "window exists".
5. `docs/ARCHITECTURE.md:333-334` — "`engine resume` on a part 1 database does not do this … and does not resume it" is wrong as written: `engine resume` on a parked `engine run` spec now marks it `failed — awaiting you` at once (`core.js:1202`, through `queue.run`), writes a metrics record, and a later signal plus resume does resume it (parking test, line 438). `cli.js:352` still says such a spec "is left waiting".
6. `queue_report.js:160` — after a kill between the commit and `awake off`, the rerun writes the file again. When a read that failed the first time now succeeds, the tracked report is left modified, and the next queue's merges park on "live checkout is mid-change" (`integrate.js:47-51` exempts only `.claude/` and `docs/superpowers/metrics/`). Fix: skip the write when the `commit_report:<rel>` step is done.
7. Stale comments after the `reportPath` ruling: `core.js:1220-1222`, `queue_report.js:3`, `steps.js:122` and `steps.js:130` ("the owners of these steps have no check yet"). `opts.reportPath` in `core.js:1232` is now used only by tests.
8. `board/discord_feed.py:437-450` — the engine's own `spec_done` or `fail_spec` line for a lead-run spec (from `engine done`) sets the engine-run mark again, so the board's derived `spec_outcome` post for that spec is dropped. The engine's line carries the outcome, so the user still sees it. See the ruling note below.
9. `claude/orchestrator.md:110` — engine-run tasks stay pending until the report, and each `Plan & run:` task is blocked by the one before it. A lead-run spec whose turn comes after an engine-run spec has a blocked task. One clause: the `your turn` line overrides the block.
10. `queue_report.js:146-148,170` — the commit takes the paths `registry report` prints. Step 5 also commits `<batch>.relations.json`. I did not check what `registry report` prints; if it prints only the analysis document, the relations file stays untracked (and invisible to the dirty check).
11. `core.js:1176-1182` — the plan is compiled in the `try` and again on the next line; harmless (cached), but the second call is dead for queue specs.
12. `lead.js:47-60` — the floor file is written without a temp file and rename, and survives a deleted lead file (then history from the floor is replayed). Already on the ledger.

## Evidence checks (review extras 1 to 5)

1. Fixture origin: the limit-message fixtures are built from transcript text, not a pane capture (I4). The report tests stub `tmux-ctl` for `metrics report`, `registry report`, `metrics status`, `awake` and `artifact`; the argv is pinned and the real run is Task 15.
2. Artefact under test: `test_engine_start.zsh` and the restore scratch test run the real `bin/tmux-ctl`; the report tests run real git on a temp repo (commit trailer, path scope). `engine_lines` is tested as the module; its wiring in `server.py:614-618` has no test (ledger l.51).
3. User-experienced check: none in this diff.
4. State: every e2e runs on fresh scratch state. The two aged cases are simulated by clock. No real engine database exists on this machine, so the migration of an aged part 1 database is covered only by the fixture test.
5. Universal claims: I ran no suite. "No finding at a kill point" above rests on reading the code paths, not on the kill matrices; Task 14's run of those is the evidence.

## Deferred-minor triage

| Ledger line | Item | Verdict | Reason |
| --- | --- | --- | --- |
| 14 | `NEVER_PARK` comment stale | can wait | comment only |
| 15 | a `not_done` row of a kind other than `metrics_start` stays at intent; `reconciled N` repeats | can wait | such rows are run again by their owner (`steps.run` reruns an intent row); only the count is noisy |
| 16 | `metricsStart` passes `"null"` as `--worktree` | can wait | only for a spec with no worktree; engine-run specs always have one |
| 17, 60 | `engine_resume` kill matrix slow and load-flaky | can wait | test runtime; Task 14 runs it alone |
| 19 | `engine_cli` resume test swallows errors | can wait | test diagnostics |
| 24 | limit regex not anchored | fix first after merge | see I4; self-recovering, costs tokens |
| 25 | limit fixtures from transcripts | can wait | Task 15 gate (I5) |
| 26 | capture on every poll; fixed waits in tests | can wait | one `capture-pane` per ready handle per 5 s |
| 27 | tests written with the code | can wait | process note; mutations recorded |
| 34 | migrate can race on `ALTER` | can wait | needs two first opens of a part 1 database at once; none exists here |
| 35 | policy hash depends on key order | can wait | bites only when someone reorders the constants, and then parks with a clear question |
| 36 | `core.park` hard-codes approve | closed | done by R11 (`core.js:237-241`) |
| 37 | `waitProblem` accepts an object recommendation | can wait | every caller passes JSON text |
| 45 | ask line without batch not reported; flag shapes unchecked; no permutation p; CLI path unexercised | can wait | the engine always passes a batch; shapes come from one builder; I5 covers the real run |
| 51 | `server.py` wiring untested | can wait | five lines; a wrong key shows on the first real queue (I5) |
| 52 | real-state `src` check vacuous | can wait | Task 15 gate |
| 53 | fixture uses `#part-2`; two reads per tick; base match can silence a lead-run `#part-1` | can wait | only for a spec split across runners |
| 55 | a suppressed event's key is marked seen | can wait | costs two progress posts for a handed-over spec |
| 59 | unknown site falls back to deny; ask never appended for real; two test gaps | can wait | `deny` is the safe side; I5 covers the real append |
| 65 | fake usage 0 for an unknown handle; `fix_wave` not counted; misnamed test; duplicate predicate; dead branch; usage-wrapper assert | can wait | test and tidy items; the hang guard is worth doing in the fix wave |
| 74 | Task 7 minors 2 and 3 (kill between `lead_turn` and publish untested; plan compiled twice) | can wait | design covers the first (the cursor is the file); second is Minor 11 |
| 74 | Task 7 minor 4 | merge-gate item | I5 |
| 78 | floor not written by rename; floor survives a deleted lead file; stderr not rate-limited | can wait | Minor 12 |
| 88 | fish as default shell; rc line order | can wait | this machine's shell is zsh |
| 90 | the cwd guard refuses a worktree; a missing session says "no git pane path" | can wait | restore passes the main checkout; message only |
| 96 | minor 3 (run-alone list), minor 4 (docs) | closed | handed to Tasks 14 and 13 |
| 98, 100 | `engine run` guard has its own SQL | can wait | `engine run` beside a queue is refused by the lock anyway |
| 100 | test for a second queue's own `queue_report` key | closed | `engine_queue_report.test.js:218` |
| 107 | Task 12 minor 3 (session-created branch not run on the scratch server) | can wait | covered by the recorder tests |
| 113 | engine-only project with a finished queue gets an empty session | can wait | cosmetic |
| 121 | ARCHITECTURE first line unwrapped; report-step order not traced | closed for the order | I traced it: commit, artifact, awake off, then `queue_finished` (`queue_report.js:166-183`, `core.js:1332-1333`); the wrap can wait |
| 122 | handoff skill boundary line longer than the brief | can wait | the added clause is correct |
| 127 | rerender after the commit; two test gaps | can wait | Minor 6 names the one case with a consequence |

## Rulings

I read every `Ruling:` line. None is wrong in a way that changes the merge. Notes:

- Line 9 (R1 to R24): R4 and the rule half of R5 were ruled but not carried into Task 13's dispatch (I1). The other rulings I checked against the code hold (R6, R7, R11, R12, R13, R15, R16, R17, R18).
- Line 50 (engine-run mark): "a lead-run spec keeps its derived Discord posts" holds only until `engine done`; the engine's `spec_done` line sets the mark again (Minor 8).
- Line 94 (adopt running jobs before due timers): sound; the literal order of section 9 would fail a live job on a deadline that passed while the engine was down.
- Line 111 (no `reportPath`): sound and it supersedes line 99; it leaves the stale comments of Minor 7.
- Line 5 and the plan's Task 15: the merge puts `engine-c1.md` on `main`, which switches the Engine queue block on for the next lead. If the rest of tonight's queue is not meant to be that first real queue, the handoff must say `TC_ENGINE=0`.

## Assessment

**Ready to merge: with fixes.** The engine code is restart-safe at every point I traced and the cross-task wiring (queue, parking, report, restore, wrapper, board lines) is consistent. The gaps are at the lead-rule boundary: two rulings that never reached the rule (I1) and enqueue rows that outlive a failed start (I2). Both are small, and both can make the lead and the engine run the same spec on the first unattended night.

Context learned:
- Gotchas: a ruling made at pre-flight reaches a task only through its brief; `task-13-brief.md` carried the plan's block text and neither R4 nor R5, and the task review checked against the brief (files: `.superpowers/sdd/2026-11-24-pcee-engine-part-2/preflight-rulings.md`, `task-13-brief.md`).
- Map: `enqueue` rows live only in the `inbox` table until an engine drains them; `engine status` and `status --unfinished` do not show them, `start --preflight` does (files: `engine/lib/engine/queue.js`, `engine/lib/engine/cli.js`).
- How to run: an engine CLI scratch run needs `TC_ENGINE_DIR`, `TC_STATE`, `TC_PROJECT` and `TC_TMUX_CTL=/usr/bin/true`, with `start --here --backend fake` under `perl -e 'alarm N; exec @ARGV'` (a lead turn waits forever) (files: `engine/bin/engine.js`).
