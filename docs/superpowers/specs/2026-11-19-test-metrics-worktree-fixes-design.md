# Test hygiene, metrics and worktree fixes (regroup group B)

Date: 2026-11-19 · Decided with the user over Discord, 2026-11-19 (regroup group B; ideas 20be1757d7, 008dd4acfd, 8e7b8becf8, c082e65f13, e3ce28f853). Runs after `2026-11-19-discord-ops-fixes-design.md`, which adds `metadata.worktree`.

## Problem

1. `tools/tests/test_discord_always_on.zsh` part 3 starts a `fake_claude_tui.zsh` stub marked `dcfake-$$-$RANDOM` (`:48-51`) and kills it with explicit loops (`:75, 96, 115, 124`). There is no trap, so a failure between `:51` and `:124` leaves the stub running (one leaked for about an hour).
2. `tools/tests/test_claude_orchestrator_dc.zsh:136` checks for leaks with a machine-wide `ps -A` grep for the constant `fake/discord/0.0.4`, so a parallel suite in another worktree makes it fail.
3. `board/worktree_safety._is_new` (`:234-246`) gives the 24 h grace only to a branch whose reflog has exactly one entry. A fresh spec branch that was fast-forwarded to `main` has two, its HEAD is an ancestor of `main`, and the sweep removes it as "merged" (seen 2026-11-18 17:32).
4. `board/metrics.attributed_rows` (`:535-551`) keeps rows by `git_branch`, by a cwd under `worktree_dirs` (from `git worktree list`, or from cwds of rows on the branch), or by cwd == root. A worker row with `git_branch` "main" whose worktree was removed before `record` matches none, so the run under-counts.
5. `board/discord_feed._failed_run_log(project, now)` (`:345-387`) posts the newest failing run of any worktree of the project, so with two worktrees running it can post the other spec's log.

## Decisions (user, Discord, 2026-11-19, answer "1")

- D1. Leak: an EXIT trap kills only the PIDs that match the test's own mark, then a check that none are left.
- D2. The fake holder's path is unique per run; the leak check greps for that path.
- D3. The grace applies when the newest reflog entry is under 24 h old and every entry is a branch creation or a fast-forward; a merged branch then waits up to 24 h before removal.
- D4. `tmux-ctl metrics start` records the spec's worktree path; `record` counts every row whose cwd is under it, even after the worktree is gone.
- D5. `_failed_run_log` narrows to the spec's own worktree from `metadata.worktree`, falling back to today's pick without it.

## Design

### 1. Stub reaping (`tools/tests/test_discord_always_on.zsh`)

After `MARK` is set, install `trap 'dc_reap; tt_teardown' EXIT INT TERM`, where `dc_reap` runs `pgrep -f "$MARK"` and kills each PID (TERM, then KILL after 1 s for any still alive). The pattern is the test's own scratch string, so nothing else on the machine matches. The existing kill loops stay. After the last one, a check asserts `pgrep -f "$MARK"` prints nothing. `lib.zsh`'s own trap is replaced only in this file, and the new trap still calls `tt_teardown`.

### 2. Per-run fake path (`tools/tests/test_claude_orchestrator_dc.zsh`)

The fake plugin dir becomes `$TT_DIR/fake/discord/0.0.4` (the run's scratch dir), and so does the path the fake holder's args carry. The leak check greps `ps -A -o args=` for that full path. A suite in another worktree has a different `TT_DIR` and never matches.

### 3. Reflog grace (`board/worktree_safety.py`)

`_is_new` reads `git reflog show --format='%gd %gs' --date=unix refs/heads/<branch>`. It returns True when:
- the read succeeds and there is at least one entry,
- the newest entry (the first line) is under `NEW_GRACE` (24 h) old, and
- every entry's subject starts with `branch: Created from` or contains `: Fast-forward` (git's wording for `merge`/`pull --ff`), or is `reset: moving to` a commit that is an ancestor of the base. A branch with any commit of its own (`commit:`, `commit (amend):`, a non-fast-forward merge) gets no grace from this rule, which matches today.

An unreadable reflog still gives False. The docstring names the fast-forward case.

### 4. Worktree in the metrics start line (`board/metrics.py`, `bin/tmux-ctl`, `claude/orchestrator.md`)

- `tmux-ctl metrics start <spec> --batch <id> [--worktree <path>]` writes `"worktree": "<path relative to the repo>"` into the `start` record when given. The path is normalised like `rel_spec` and must lie under `.claude/worktrees/`; anything else is an error (`metrics: --worktree must be under .claude/worktrees/`).
- `cmd_record` reads the latest `start` record for the spec and batch. When it has `worktree`, `attributed_rows` also keeps every row whose cwd is that directory or below it, whatever its `git_branch`. Rows already kept by the other rules are not counted twice.
- Queue mode step 2 in `claude/orchestrator.md`: `tmux-ctl metrics start <spec> --batch <id> --worktree .claude/worktrees/<name>`, after the branch and worktree exist.
- A `start` record without `worktree` (every run before this change) is attributed as today.

### 5. Failed-run log by worktree (`board/discord_feed.py`)

`_failed_run_log(project, now, worktree=None)`: when `worktree` is set, only runs whose cwd is under `<root>/<worktree>` are candidates; with none, it returns None (no log posted) rather than another worktree's run. `derive` passes `meta.get("worktree")` from the running `Plan & run:` task's metadata (read at `:436`). Without the field, today's pick stands.

## Error handling

- `dc_reap` never fails the test on its own: a PID that is already gone is ignored.
- `metrics start --worktree` with a bad path exits 2 with the one-line error and writes nothing.
- `_is_new` keeps its conservative default: any unexpected reflog line means no grace.

## Testing

- `tools/tests/test_discord_always_on.zsh`: the new no-leftover check; a forced failure (run once while writing the change, not kept) shows the trap reaps the stub.
- `tools/tests/test_claude_orchestrator_dc.zsh`: the leak check passes while a decoy process with the old constant path `fake/discord/0.0.4` runs (started and killed by the test itself).
- `board/tests/test_worktree_safety_classify.py`: a branch created and then fast-forwarded to main within 24 h is `kept` ("new, no commits yet"); the same branch with back-dated entries over 24 h is `safe`; a branch with one own commit gets no grace; an unreadable reflog gives no grace. Fixtures back-date entries as `worktree_fixtures.py:58-63` does.
- `board/tests/test_metrics_record_usage.py`: a worker row (`git_branch` "main") with cwd in a worktree removed before `record` is counted when the start record has `worktree`, and not counted without it; no double count with a branch-matched row; `start --worktree` outside `.claude/worktrees/` exits 2.
- `board/tests/test_discord_feed.py` near `:859-914`: two worktrees' failing runs, `worktree` set → the spec's own log; `worktree` set with no matching run → no log; unset → today's newest pick.

## Out of scope

- Reaping in other tests (a sweep for the same pattern elsewhere is a separate idea if one is found).
- Back-filling `worktree` into old start records.
- Writing `metadata.worktree` (spec A does that).
