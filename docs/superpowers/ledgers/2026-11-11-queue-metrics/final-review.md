# Final whole-branch review: queue-metrics (565352b..bd0da1a)

Reviewer: qm-final (session model, read-only, single pass over the whole diff, no subagents).
Read: the spec, the plan (Global Constraints, Metric definitions, Tasks 1-7, "After the merge"), the ledger, `board/metrics.py` (all 1519 lines), the six test files, the `bin/tmux-ctl`, `claude/orchestrator.md`, handoff SKILL and config/roadmap diffs, and the committed `runs.jsonl`.

## Verification run this session

- `python3 -I -m unittest discover -s board/tests -p 'test_metrics_*.py'` → `Ran 123 tests in 135.972s` / `OK`, rc=0, 0 FAIL/ERROR lines (full output: `final-verify.txt`). The real-state test ran (not skipped): `totals: tokens 578.8M (appendix 588.4), usd 195.77 (199.01), active 596 (599)`, all within 2%.
- Fixtures: `cmp` shows `board/tests/fixtures/metrics/remote-access-progress.md` and `remote-access.tasks.json` are byte-identical to `docs/superpowers/ledgers/2026-11-09-remote-access/progress.md` and `docs/superpowers/plans/2026-11-09-remote-access.md.tasks.json`.
- Python 3.9: a grep of `board/metrics.py` and `board/tests/test_metrics_*.py` for `match `, `X | None`, `removeprefix/suffix`, `zip(strict`, `bit_count`, `assertNoLogs`, `:=`, `pairwise`, `tomllib`, `datetime.UTC` returns 0 hits; `math.comb` is 3.8+.
- Scratch-repo probes (scratchpad `probe/`, `TC_STATE`, `USAGE_ROOT` and `TC_LINEAGE` pointed at temp dirs), with results quoted in the findings below: P1 a failing `backfill --log`, P2 an absolute spec path, P3 a late-joining spec, P4 a repo without metrics files, P5 `start` run from a worktree.

## Strengths

- One module with plain functions, a single error contract and no tracebacks. `main()` wraps everything, and the one-line stderr contract holds in every probe.
- The tests run real git (`merge-tree`, `log --first-parent`, `merge-base`) on scratch repos. The only patches are of internal seams (`_merge_trees`, `quality_veto`, `compare_text`/`status_line`, and `plan_limits` for the backfill-limits case). Mutation runs are recorded in the ledger for every task.
- The real-state backfill really reproduces the appendix (12 specs, -1.63% tokens, -1.63% usd, -0.5% active), runs read-only against a copy of the snapshot, and skips cleanly when `~/.local/state/agent-board/metrics/usage-snapshot-20261111.sqlite` is absent, as it is on CI (`test_metrics_backfill.py:159-160`). The fixtures for the ledger and tasks file are real copies.
- The permutation test (exact, or sampled with a fixed seed), the quality veto with its 14-day window, and the decision-rule ordering follow spec §5 closely. The rulings that tightened rule 3 to included specs are sound.

## Critical

None.

## Important

- board/metrics.py:47-48, 167-168 (with `claude/orchestrator.md` step 2): run-log commands resolve the log from the cwd's checkout, so a lead working in the spec's worktree cannot stamp a start and dirties the feature branch. Probe P5: after `batch start` on main, `metrics start docs/superpowers/specs/w.md --batch <id>` run inside `.claude/worktrees/w` printed `metrics: start: unknown batch 2026-11-11-2` (rc=1), and `git -C .claude/worktrees/w status --porcelain` showed ` M docs/superpowers/metrics/runs.jsonl` (an error line on the branch). The later `record` from main then finds no start line and takes the derived window from the batch line's time (`metrics.py:654`), so spec N of a queue is charged every repo-root call since the batch began. Orchestrator step 2 runs `metrics start` after the worktree branch-off and before `writing-plans`, and this run's own team works with the worktree as its cwd. Fix: resolve `log_path` (and config/gate/roadmap reads) from `main_root(repo)`, which already exists at `metrics.py:468`, so every checkout of the repo shares main's log. Add a test that runs `start` from a `git worktree add` dir and asserts the line lands in the main checkout's log.
- board/metrics.py:1433-1442 (post-merge step 1, plan:273): the lead's `tmux-ctl metrics backfill` after merging this spec will charge it about 22 hours of unrelated repo-root work. `prev_ct` only advances on merges that have a plan. The four first-parent merges since remote-access (`fix/linux-ci`, `fix/telegram-always-on`, `fix/telegram-watch-quiet`, `fix/telegram-watch-ghost`) have none (checked with `_plan_for_merge` over the real `main`), so queue-metrics' derived window starts at remote-access's merge (2026-11-10T03:00Z). In the live index, repo-root rows between that merge and this plan's first commit (12862a6) total 792 calls and 142.9M tokens. All attributed rows after that commit total 67.4M so far. That one record would be about 3x its real size and become the largest baseline (`seq-sdd`) record. Fix: advance the window anchor on every first-parent merge once the first plan merge has been seen (the first record keeps the plan's first commit), or start the window at the later of the previous merge and the plan's first commit. Verify that the real-state test still lands within 2% (the 12 appendix specs have no plan-less merges between them), and that a dry run (`backfill --log <tmp>` on main after the merge) gives queue-metrics `started_at` ≥ 565352b's commit time.
- board/metrics.py:658-659 (and :1126 in compare): a spec that joins a batch late is invisible to every comparison. The orchestrator tells the lead that "A spec queued later joins that batch: do not run `batch start` again", but `config` comes only from the batch line's `assignment`, so the late spec gets `config: null` and is not named in `missing`. Probe P3: `config= None config in missing: False`. `compare_data` selects baseline rows by their config's `baseline` flag and challenger rows by `config == <id>`, so the run is silently dropped from both sides. This upgrades T3's deferred minor ("null config not in missing"). Fix: when the spec is not in `assignment` and the batch has one config, use that config. With two configs, use null plus `missing: ["config"]` (or have `start` refuse a spec outside a two-config batch).
- board/metrics.py:166-181, 146-163 (and the record/defect paths); test board/tests/test_metrics_backfill.py:216-221: absolute spec paths reach the committed log, and the privacy sweep cannot see absolute-path leaks. This confirms and extends ruled item 4. Probe P2: `metrics start <abs path>/docs/superpowers/specs/b.md --batch <id>` → rc=0, and `grep -c <scratch root> runs.jsonl` = 1. `batch start`, `record` and `defect` take the same unvalidated `spec`. The sweep's absolute-path check tests only for `/Users/` and `$HOME`, but every test repo lives under `tempfile` (`/var/folders/...` on macOS, `/tmp/...` on Linux CI), so a leak of the test repo's own path would pass. Its "no absolute paths" claim therefore rests on no evidence for test-produced lines. Fix: in one helper used by every subcommand, convert a spec path inside the repo root to repo-relative and refuse any other absolute path or `..` (`metrics: <sub>: spec must be repo-relative`). In the sweep, also assert that no line contains the test's temp root or matches `"/(?:private|var|tmp|home)/`, and add one test that passes an absolute spec path.
- tools/tests/test_ctl_telegram.zsh:133: ruled item 1 is confirmed. The help output now ends with `#   tmux-ctl metrics <sub> …` (bin/tmux-ctl:42), so the expectation `outside tmux give --project <name>` fails. Change the expected last line to the metrics line, and update the mutation comment at :131: a range of `2,42` now cuts the metrics line, and `2,44` shows the `send/run only type` line. The `sed -n '2,43p'` range itself is right (line 43 is the blank `#`).
- claude/orchestrator.md:78-79 (Queue mode steps 1, 2 and 5); board/metrics.py:1475-1482: ruled item 2 is confirmed and extends to code. Probe P4: in a repo without metrics files, `metrics batch start --config seq-sdd x.md` → `metrics: batch start: unknown config seq-sdd`, rc=1, and `git status --porcelain` shows `?? docs/`, because `_log_error` created `docs/superpowers/metrics/runs.jsonl` holding one error line. Guard the three orchestrator additions with "in a repo that has `docs/superpowers/metrics/configs/seq-sdd.md`", as ruled. In code, `_log_error` should not create the metrics dir: append only when `docs/superpowers/metrics/` already exists. That also closes T4's deferred "runs.jsonl created with only an error line".

## Minor

- board/metrics.py:1454-1472, 1475-1482: `backfill --log PATH` resets `LOG_OVERRIDE` in its `finally` before `main()` logs the error, so a failed dry run writes its error line into the repo's real `runs.jsonl`. Probe P1: `--since bogus --log dry.jsonl` → rc=1, `dry.jsonl` absent, and the repo log gained `{"kind": "error", ... "sub": "backfill"}`. The real-state test runs against the real checkout's toplevel with `--log`, so a failing run there would dirty the live checkout's committed log. Fix: skip `_log_error` when `--log` was given, or reset the override after logging.
- board/metrics.py:1512-1514: every failing subcommand appends a `kind: error` line, including the read-only ones (`report`, `compare`, `gate`, `status`). A user running `metrics compare X` therefore mutates a committed file, and `error` is not among spec §1's kinds. Suggest logging only for the writing subcommands (`batch start`, `start`, `record`, `defect`, `backfill`). Readers already ignore the kind.
- board/metrics.py:621-633: an unrecorded started spec (its `record` failed, or the lead skipped it) keeps its window open to `now`. Every later spec in a sequential batch then has its repo-root rows split 1/2 and `lead_shared: true`, permanently. Consider ending an unrecorded window at that spec's next `start` line in the batch, or at the next spec's start when the batch has one config, and naming it in `missing`.
- board/metrics.py:218-242: `find_plan` runs `git show` for every plan on every local branch. On this repo, with 3 branches, it measured 5.7 s for one lookup, and it grows with branches times plans. It runs once per `record`, so it is tolerable. A cheaper order: working tree first, and return on a hit.
- board/metrics.py:402: for a merged spec, `ended_at` is the merge commit time, not the record time. Work done after the merge inside `finishing-a-development-branch` (tests on main, cleanup) is not counted. The plan's M-window allows this ("record time (live) or merge commit time"); note it in the spec's §3 Time bullet so live and backfilled windows read the same.
- board/tests/test_metrics_record_usage.py:224: the AskUserQuestion fixture line has the real shape (checked against four real lead transcripts: `type: assistant`, `message.content[].type == tool_use`, `name == AskUserQuestion`, no `agentName`), but uses whole-second timestamps, while real lines carry milliseconds (`2026-11-10T18:11:08.311Z`). `count_questions` never ran on real transcripts (the real-state test sets `USAGE_ROOT` to an empty dir). Add one fixture line with milliseconds.
- bin/tmux-ctl:554-555: no test runs `tmux-ctl metrics …`. The exec line is trivial, but T1's acceptance item "runs from any dir inside the repo" rests on the implementer's report only. One `run-all.zsh` check (`tmux-ctl metrics status` from a subdirectory, rc 0) would pin it.

## Ruled item 3 (M-attr wording): where to record it

Update the plan's M-attr text (plan:31). The "PLUS" clause should read "rows (lead or agent) with `cwd == repo root` in the window". In the spec, add one line under **Decisions** rather than rewriting §3: "Implementation (2026-11-11): the repo-root part of the attribution counts every row there, lead or agent (teammates of the lead start in the repo root); lead rows still define `lead_share`; the backfill checks within 2% under this rule." The spec is what stage-2 specs and later `compare` readers consult, so the deviation must be visible there. A Decisions line keeps §3's original design readable and dates the change.

## Deferred-minor triage (ledger `minor (deferred)` lines)

| Task | Deferred minor | Ruling |
| --- | --- | --- |
| T1 | private argparse hack in `main()` (`ap._subparsers`) | fine to leave |
| T1 | absolute or duplicate spec paths not rejected | **must fix before merge** (Important above; duplicates may stay) |
| T1 | `append()` does not guard a missing trailing newline | fine to leave (only a hand edit triggers it; both lines would be counted malformed) |
| T2 | dead code (plan_text, if/pass, inline import, setUp loop) | fine to leave |
| T2 | `branch --contains` picks the first non-main branch | fine to leave (only reached with no merge, no `--branch`, plan not on main) |
| T2 | `--outcome merged` with merge null unflagged | already fixed (`metrics.py:411-412`, test in `PlanAlreadyOnMainTest`) |
| T2 | bounces/parked/fix_wave tests mirror the impl expression; clean stale_base case never diverged | fine to leave |
| T2 | slug `endswith` match is loose | fine to leave |
| T3 | `LEAD_KEYS` misnamed (it is the token keys) | fine to leave |
| T3 | `seq-sdd` hard-coded for backfill | fine to leave (backfill is the baseline by definition in this repo) |
| T3 | null config not in missing | **must fix before merge** (Important above: late-joining specs vanish from compare) |
| T3 | overlapping specs count each other's worktree questions | fine to leave (no overlapping batches until PCEE) |
| T4 | loose sentence-placement test | fine to leave |
| T4 | wrong `_merge_trees` docstring | already fixed (the docstring at `metrics.py:726-728` now matches the probe) |
| T4 | runs.jsonl created with only an error line | **must fix before merge**, with ruled item 2 (`_log_error` must not create the dir) |
| T5 | unknown target metric silently blocks replace | fine to leave; a one-line `compare` output note is cheap if touched |
| T6 | ready_at/wait_s null but not in missing | already fixed (`metrics.py:669`) |
| T6 | plan M-attr text still says lead rows | **must fix before merge** (ruled item 3, wording above) |
| T6 | 70 s privacy sweep (the whole metrics suite now takes 136 s) | fine to leave; candidate for fast-test-suite's slow tier |
| T6 | `--until` constant comment; `added[0]` | fine to leave |
| T7 | late-joining spec not told to write the batch id into its task | **fix with ruled item 2's orchestrator edit** (one clause: "and write the batch id into its `metadata.queue.batch`"); otherwise a handoff starts a new batch for it |
| T7 | uncommitted runs.jsonl may read as a user edit at finishing | fixed by the worktree Important (the log is then only ever main's) plus the existing path-scoped commit rule |
| T7 | a two-batch queue needs one report per batch | fine to leave (this queue has one batch after the post-merge step) |

## Evidence checks

1. Fixture origin. The ledger and tasks fixtures are real copies (`cmp` identical). The usage rows are hand-inserted, which spec Testing sanctions. The transcript AskUserQuestion line is hand-written but matches the real shape (see the Minor on milliseconds). The lineage lines are hand-written and match the real keys (`doc, old_session_id, pane, ts`, checked against `~/.local/state/agent-board/lineage/agent-board.jsonl`). The git histories are scratch repos built with real git. The real-state test reads the real repo and a copy of the real snapshot.
2. Artefact under test. Every test imports `board/metrics.py` and drives `metrics.main([...])` or its functions; nothing re-implements it. External commands: git runs unstubbed on scratch repos (`merge-tree --write-tree --merge-base`, including tree OIDs, probed on this host's git). The only patched seams are internal (listed under Strengths). `tmux-ctl metrics` itself is untested (Minor). `usage.plan_limits` is patched in one test; the other tests read an empty `TC_STATE/statusline`.
3. User-experienced check. Not applicable: no UI in the diff.
4. State. The real-state backfill runs on real data. Live `record` has never run on real state: the spec makes the morning report the end-to-end gate. Long-lived conditions never met: a lead whose cwd is a worktree (it fails, Important), a late-joining spec (Important), a mid-batch record failure (Minor), and plan-less merges between plan merges (Important, in the post-merge backfill). HOME: only `SNAPSHOT` reads under HOME, and it is skip-guarded. CI has no snapshot, so that test skips, and `test_committed_run_log` reads only the repo file. Other tests set `TC_STATE`, `USAGE_ROOT` and (where `record` runs) `TC_LINEAGE` to temp dirs. I did not see a run with a scratch HOME. The suite does not depend on one beyond `SNAPSHOT`.
5. Universal claims. The privacy sweep prints its counts (the committed log has 12 lines; the test logs have N lines spied through `metrics.append`, which is uncapped), but its absolute-path predicate cannot see temp-dir paths (Important). Its UUID check is the fixed prefix `[0-9a-f]{8}-[0-9a-f]{4}-`, which is fine. No assertion compares a whole env mapping.
6. Inputs agents cannot read. None: the usage index and git history were readable here, and the backfill window pollution was measured on the live index.
7. Runbook preconditions. The orchestrator's `metrics batch start --config seq-sdd` needs `docs/superpowers/metrics/configs/seq-sdd.md` (ruled item 2: guard it). `metrics start` and `record` need the lead's cwd to be the main checkout (Important: fix in code, not in prose). `tmux-ctl metrics` needs `$TMUX` (ruled at T1: every lead runs in tmux).
8. Endpoint trust. Not applicable: no endpoints.

## Recommendations

- Fold the six Importants into the fix wave with ruled items 1-4. Every one has a small, local fix and a one-test proof. The two data-integrity ones (worktree cwd, post-merge window) matter most, because they would put wrong numbers into the committed baseline before the first live batch.
- After the fix wave, run the post-merge `backfill` once with `--log <tmp>` on the merged main, and check queue-metrics' `started_at` and token total before committing it.

Ready to merge: with fixes
