# Fast Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command, `zsh tools/tests/all.zsh`, runs every suite in CLAUDE.md Commands in parallel, green, in under 5 minutes, with one verdict line.

**Architecture:** `tools/tests/all.zsh` globs one job per test file (or per skill suite dir), schedules them slowest-first from a timings file with at most `-j N` running, isolates each job's `TMPDIR`/`TC_STATE`, and prints one verdict. The suite is made parallel-safe (audit + fixes), the five files over 30 s are sped up, and the five failing files on main are fixed first.

**Tech Stack:** zsh (runner, zsh tests via `tools/tests/lib.zsh`), Python 3.9-compatible stdlib unittest, bash hook tests, git.

**Spec:** `docs/superpowers/specs/2026-11-10-fast-test-suite-design.md` — every executor reads the spec section its task cites.

## Global Constraints

- **No test is removed and no assertion is weakened** (spec Decisions, Out of scope "changing what the tests assert"). Test counts per file before and after a change are equal: unittest `Ran N`, zsh `grep -c '^ok '` of the file's output. Record both numbers in the ledger for every file you change.
- **Runner contract (spec §1), quoted:** verdict line exactly `ALL PASS <n> jobs in <m>m<s>s` or `FAIL <k>/<n>: <job names>`; exit 0 all pass under budget, 1 any failure, 4 all pass but wall time > budget (verdict line then `SLOW: <m>m<s>s over the 5 min budget`); `TC_TEST_BUDGET=<s>` overrides 300; flags `--suite board|zsh|tools|skills|statusline|hooks` (repeatable), `--serial`, `-j N`, `--list`; a file whose first 5 lines contain `# serial` runs alone after the parallel phase; timings in `<TC_STATE>/test-timings.tsv` (job name TAB seconds), rewritten after every full run (no `--suite` filter); jobs with no timing run first, then slowest first; per job `TMPDIR` = fresh dir under one `mktemp -d` run dir, `TC_STATE=$TMPDIR/state`, output to `<rundir>/<job>.log`; run dir removed on all-pass, kept (path printed) on failure; a failed job prints `FAIL <job> (<s>s)` and the last 30 lines of its log; end prints the 5 slowest jobs with times before the verdict.
- **Job names:** `board/<module>` (e.g. `board/test_usage`), `zsh/<file>` (e.g. `zsh/test_bg.zsh`), `tools/<file>` (e.g. `tools/test_install_lib.py`), `skill/<dir name>` (e.g. `skill/docs-architecture`), `statusline`, `hooks/<file>` — the same names the baseline TSV uses where it has them.
- **TC_STATE for the runner's own timings file:** `${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}` (the tmux-ctl default). Each job gets its own `TC_STATE` as above; the runner's timings path is resolved once, before jobs override it.
- **`TC_TEST_ROOT`** overrides the repo root the runner globs (tests use a fake layout); default is the repo root from `${0:A:h}/../..`.
- `tools/tests/run-all.zsh` is not changed.
- **zsh gotchas** (user rules): never name a variable `path`; brace variables before a colon (`"${x}:y"`); quote tmux `=name` targets; scratch tmux servers start with `-f /dev/null` (lib.zsh already does).
- **Running zsh suites from an agent:** via `tmux-ctl run tests "<cmd>; echo rc=\$?"` and read the `rc=` line (`test_prompt_argv.zsh` is PATH-dependent until Task 2 fixes it). The full board suite takes ~7.5 min and the zsh suite >10 min serially: run them in the background.
- **Known flakes under load** (not failures of this plan unless they repeat): `board/tests/test_worktree_lock.py` `test_live_non_claude_pid_is_stale`, ghost checks in `tools/tests/test_telegram_always_on.zsh`. Task 5 must make them pass in parallel runs or mark them `# serial` with the reason.
- **Commits:** conventional with scope (`fix(tests): …`, `feat(tests): …`, `perf(tests): …`, `docs(claude): …`); end with the attribution trailer your harness specifies. Stage only your own paths (`git add <paths>`).
- **Ledger:** `docs/superpowers/ledgers/2026-11-11-fast-test-suite/progress.md` holds the per-file before/after counts and times, profiling notes, and Task 7's acceptance runs.

**User decisions (already made):**
- "Anything may change if coverage is kept: a parallel runner, plus speeding up every file over 30 s. No test is removed." (spec Decisions)
- This spec runs second in the queue and fixes all five failing files (spec §4).
- Orchestrator/restart tests assert against `relay.launch_line(root, prompt)`; no change to `board/relay.py` (spec §4).

---

### Task 1: Orchestrator and restart tests assert against `relay.launch_line`

**Goal:** `board/tests/test_orchestrator_path.py` (4 failures) and `board/tests/test_restart_orchestrator.py` (2 failures) pass by asserting the typed launch text equals `relay.launch_line(root, prompt)`.

**Files:**
- Modify: `board/tests/test_orchestrator_path.py`
- Modify: `board/tests/test_restart_orchestrator.py`

**Acceptance Criteria:**
- [ ] Each of the 6 failing assertions compares against `relay.launch_line(<root the code under test used>, <prompt or None>)`, not a copied literal string.
- [ ] `git diff main -- board/relay.py board/server.py` is empty.
- [ ] Test counts unchanged: `Ran 5` and `Ran 15`.
- [ ] Mutation: change `launch_line` in a scratch copy to drop `cd -- ` → the fixed tests still pass only if they call `launch_line` (they do); change `respawn` to send `orchestrator()` alone → at least one fixed test fails. Report both outcomes.

**Verify:** `python3 -m unittest board.tests.test_orchestrator_path board.tests.test_restart_orchestrator 2>&1 | tail -3` → `Ran 20 tests` … `OK`

**Steps:**
- [ ] Run the two modules; read each failing assertion (current failures: the expected list/tuple lacks the `cd -- <root> &&` prefix).
- [ ] Replace each expected launcher string with `relay.launch_line(root, prompt)` built from the same root/prompt the test passes in (import `relay` the way the module already imports board code). Where a test splits the line with `shlex.split`, split `launch_line(...)` the same way.
- [ ] Run the mutation in the AC (revert it), run Verify, commit `fix(tests): assert launch text against relay.launch_line`.

```json:metadata
{"files": ["board/tests/test_orchestrator_path.py", "board/tests/test_restart_orchestrator.py"], "verifyCommand": "python3 -m unittest board.tests.test_orchestrator_path board.tests.test_restart_orchestrator 2>&1 | tail -3", "acceptanceCriteria": ["6 assertions compare against relay.launch_line", "no change to board/relay.py or board/server.py", "Ran 5 and Ran 15 unchanged", "mutation of respawn fails a fixed test"], "modelTier": "standard"}
```

### Task 2: Fix `test_session_path`, `test_session_root_path`, `test_prompt_argv.zsh`

**Goal:** The three files pass when run alone (one module / one file per process, as `all.zsh` will run them), inside and outside a live agent-board tmux pane, with the root cause fixed.

**Files:**
- Modify: `board/tests/test_session_path.py`, `board/tests/test_session_root_path.py`, `tools/tests/test_prompt_argv.zsh` (and code only if debugging shows the code is wrong)
- Ledger: root cause per file

**Acceptance Criteria:**
- [ ] Use `superpowers-extended-cc:systematic-debugging`. Known evidence: `python3 -m unittest board.tests.test_session_path` alone errors with `KeyError: 'TMUX_DASH_TOKEN'` (`board/server.py:47` reads it at import) — under `discover` an earlier module apparently sets it. `test_prompt_argv.zsh` fails when PATH holds `<repo>/bin`. Root cause for each is written in the ledger before the fix.
- [ ] Fix is isolation in the test (set the env the module needs in the test module before importing `server`, or scrub inherited `PATH`/`TMUX`/`TC_*`) unless debugging proves the code wrong; a code change is justified in the ledger.
- [ ] All three pass: alone; under `python3 -m unittest discover -s board/tests`; with `env -u TMUX -u TMUX_PANE`; and the zsh file both with and without `<repo>/bin` at the front of PATH.
- [ ] Test counts unchanged (`Ran 5` for test_session_path; record the others).

**Verify:** `python3 -m unittest board.tests.test_session_path board.tests.test_session_root_path 2>&1 | tail -1 && PATH="$PWD/bin:$PATH" zsh tools/tests/test_prompt_argv.zsh | tail -1` → `OK` then `ALL PASS`

**Steps:**
- [ ] Reproduce each failure alone and record the exact error.
- [ ] Find what `discover` order supplies (grep `TMUX_DASH_TOKEN` in `board/tests/`); find which assertion in `test_prompt_argv.zsh` depends on the caller's PATH.
- [ ] Fix in the tests, run every AC combination, commit `fix(tests): isolate session-path and prompt-argv tests from the caller's env`.

```json:metadata
{"files": ["board/tests/test_session_path.py", "board/tests/test_session_root_path.py", "tools/tests/test_prompt_argv.zsh"], "verifyCommand": "python3 -m unittest board.tests.test_session_path board.tests.test_session_root_path 2>&1 | tail -1 && PATH=\"$PWD/bin:$PATH\" zsh tools/tests/test_prompt_argv.zsh | tail -1", "acceptanceCriteria": ["root cause per file in the ledger", "fix is test isolation unless proven otherwise", "pass alone, under discover, without TMUX, with and without repo/bin on PATH", "test counts unchanged"], "modelTier": "standard"}
```

### Task 3: `tools/tests/all.zsh` runner with its own test

**Goal:** The parallel runner exactly as the Global Constraints' runner contract and spec §1 state, tested by `tools/tests/test_all_runner.zsh` on a fake layout.

**Files:**
- Create: `tools/tests/all.zsh`
- Create: `tools/tests/test_all_runner.zsh`

**Acceptance Criteria:**
- [ ] Use `superpowers-extended-cc:test-driven-development` (+ extras). `test_all_runner.zsh` builds a fake repo under `mktemp -d` (`TC_TEST_ROOT`) with stub jobs in each suite shape (board `test_*.py` modules, `tools/tests/test_*.zsh`, `tools/tests/test_*.py`, one skill dir, statusline dir, `claude/hooks/tests/test-*.sh`) that sleep, pass, fail and carry `# serial`, and checks, each as its own `check` line:
  - slowest-first order from a seeded `test-timings.tsv`, untimed jobs first (stubs append start stamps to a shared log);
  - `-j 2` never has more than 2 jobs running at once (start/end stamps);
  - `# serial` jobs start only after every parallel job ended, one at a time;
  - verdict `ALL PASS <n> jobs in …` and rc 0; `FAIL 1/<n>: <name>` and rc 1 with `FAIL <job> (<s>s)` plus the failed log's tail; rc 4 and the `SLOW:` line with `TC_TEST_BUDGET=0`;
  - `--suite zsh` runs only zsh jobs; `--list` runs nothing (no stamps) and prints every job name with its command; `--serial` runs in suite order with one at a time;
  - timings file rewritten after a full run and not after a `--suite` run;
  - each job sees its own `TMPDIR` and `TC_STATE=$TMPDIR/state` (stub prints them);
  - run dir removed on pass, kept and printed on fail.
- [ ] Each guard check names its mutation in a comment (e.g. "drop the `-j` cap → the concurrency check fails"), and the RED run shows it failing for that reason.
- [ ] `zsh tools/tests/all.zsh --list` on the real repo lists one job per file in every suite: count equals `ls board/tests/test_*.py tools/tests/test_*.zsh tools/tests/test_*.py claude/hooks/tests/test-*.sh | wc -l` + 4 (three skill dirs + statusline).
- [ ] Works with macOS zsh and Linux (`nproc` fallback when `sysctl -n hw.ncpu` fails).

**Verify:** `zsh tools/tests/test_all_runner.zsh | tail -1` → `ALL PASS`

**Steps:**
- [ ] Write `test_all_runner.zsh` (source `lib.zsh` for `ok/fail/check/tt_done`; no tmux server needed), run it RED.
- [ ] Implement `all.zsh`: glob jobs per suite, read timings, background jobs with a running-count cap (`wait` on PIDs / `jobs` table), per-job `env TMPDIR=… TC_STATE=…`, collect rc and seconds (`$EPOCHREALTIME`), serial phase, summary, verdict, exit code, timings rewrite.
- [ ] GREEN, then `zsh tools/tests/all.zsh --list | head` on the real repo; commit `feat(tests): add parallel all.zsh runner with one verdict line`.

```json:metadata
{"files": ["tools/tests/all.zsh", "tools/tests/test_all_runner.zsh"], "verifyCommand": "zsh tools/tests/test_all_runner.zsh | tail -1", "acceptanceCriteria": ["fake-layout test covers order, -j cap, serial phase, verdicts, exit codes 0/1/4, failed tail, --suite, --list, --serial, timings rewrite, per-job TMPDIR/TC_STATE, run dir keep/remove", "each guard check names its mutation and RED shows it", "--list count matches the real file count + 4", "nproc fallback"], "modelTier": "standard"}
```

### Task 4: Speed up the two board worktree files

**Goal:** `board/tests/test_worktree_safety.py` (113 s) and `board/tests/test_worktree_board.py` (44 s) each finish under 30 s solo with the same test count (spec §3).

**Files:**
- Modify: `board/tests/test_worktree_safety.py`, `board/tests/test_worktree_board.py`

**Acceptance Criteria:**
- [ ] Profile first (e.g. `python3 -m cProfile -s cumtime -m unittest board.tests.test_worktree_safety 2>&1 | head -40`, or time `setUp` vs test bodies); the split goes in the ledger.
- [ ] Fixture repos are built once per class (`setUpClass`) and each test gets an independent copy (`shutil.copytree` or `git clone --local`), so no test sees another's mutations; per-test `tearDown` cleanup kept.
- [ ] `Ran N` before == after for each file (record N); solo wall time < 30 s each (record before/after).
- [ ] Both still pass under `python3 -m unittest discover -s board/tests -p 'test_worktree*'`.

**Verify:** `for m in test_worktree_safety test_worktree_board; do /usr/bin/time -p python3 -m unittest board.tests.$m 2>&1 | grep -E '^(Ran|OK|FAILED|real)'; done` → each `OK` and `real` < 30

```json:metadata
{"files": ["board/tests/test_worktree_safety.py", "board/tests/test_worktree_board.py"], "verifyCommand": "for m in test_worktree_safety test_worktree_board; do /usr/bin/time -p python3 -m unittest board.tests.$m 2>&1 | grep -E '^(Ran|OK|FAILED|real)'; done", "acceptanceCriteria": ["profile split in ledger", "templates once per class, independent copy per test", "Ran N unchanged and solo < 30 s each", "pass under discover"], "modelTier": "standard"}
```

### Task 5: Speed up the three slow zsh files

**Goal:** `tools/tests/test_ctl_approve.zsh` (115 s), `tools/tests/test_teammate_window.zsh` (58 s) and `tools/tests/test_bg.zsh` (38 s) each finish under 30 s solo with the same `ok` count (spec §3).

**Files:**
- Modify: `tools/tests/test_ctl_approve.zsh`, `tools/tests/test_teammate_window.zsh`, `tools/tests/test_bg.zsh` (and `tools/tests/lib.zsh` only to add a shared helper, without changing existing helpers' behaviour)

**Acceptance Criteria:**
- [ ] Profile first (timestamp each case, e.g. `zsh -x` with `PS4='+%D{%s.%.} '` or `print` stamps); the per-case split goes in the ledger.
- [ ] Fixed `sleep`s become `tt_wait <secs> <condition>` polling on what the sleep waited for; cases that do not need a fresh server share one scratch tmux server per file.
- [ ] A wait that is inherent (a real timeout under test) is kept, with its reason in the ledger; if that keeps a file over 30 s, the ledger says so with the remaining time.
- [ ] `grep -c '^ok '` before == after per file (record); no `FAIL` lines; solo wall time < 30 s each (record before/after).
- [ ] Each file passes 3 times in a row solo (flake check), run via `tmux-ctl run tests`.

**Verify:** `for f in test_ctl_approve test_teammate_window test_bg; do s=$EPOCHSECONDS; zsh tools/tests/$f.zsh | tail -1; print "$f $(( EPOCHSECONDS - s ))s"; done` → each `ALL PASS` and < 30 s

```json:metadata
{"files": ["tools/tests/test_ctl_approve.zsh", "tools/tests/test_teammate_window.zsh", "tools/tests/test_bg.zsh", "tools/tests/lib.zsh"], "verifyCommand": "for f in test_ctl_approve test_teammate_window test_bg; do s=$EPOCHSECONDS; zsh tools/tests/$f.zsh | tail -1; print \"$f $(( EPOCHSECONDS - s ))s\"; done", "acceptanceCriteria": ["profile split in ledger", "sleeps replaced by tt_wait on the condition; shared server where independent", "inherent waits kept with reason", "ok count unchanged, solo < 30 s each", "3 solo passes in a row each"], "modelTier": "standard"}
```

### Task 6: Parallel-safety audit and fixes

**Goal:** Every test file is safe to run concurrently with every other under `all.zsh` (spec §2), proven by two back-to-back green parallel runs whose counts equal a `--serial` run's.

**Files:**
- Create: `docs/superpowers/notes/2026-11-11-test-parallel-audit.md`
- Modify: any test file the audit flags (not the files Tasks 4–5 own unless the finding is about shared state), plus `# serial` markers

**Acceptance Criteria:**
- [ ] The audit doc has a table with one row per test file / job (every name `all.zsh --list` prints), columns `job | shared state found | fix | serial?`. Checks: fixed `/tmp/...` paths, writes under `~/.claude` or `~/.local/state` or `$HOME`, fixed ports (`TMUX_DASH_PORT`, any literal port), fixed tmux socket names (`-L <literal>`), env read at import that another module supplies (the Task 2 pattern), the real `~/.claude/projects` or usage index.
- [ ] Every module/file passes when run alone as its job command (`all.zsh --list` commands, one at a time) — this catches order dependence under `discover`.
- [ ] Each finding is fixed to use `TMPDIR`/`TC_STATE`/a free port (`socket.bind(('127.0.0.1', 0))`), or the file gets `# serial` in its first 5 lines with a one-line reason; the known flakes (`test_worktree_lock`, `test_telegram_always_on.zsh` ghost checks) are among the rows.
- [ ] Two consecutive `zsh tools/tests/all.zsh` runs → `ALL PASS`, and one `zsh tools/tests/all.zsh --serial` run → `ALL PASS` with the same job count; total tests (sum of `Ran N` + `ok` lines over job logs, method written in the doc) equal across the three. Wall times in the ledger.

**Verify:** see verifyCommand → first line = (`zsh tools/tests/all.zsh --list | wc -l`) + 2 (header + separator), then `ALL PASS …` and `rc=0`

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-11-test-parallel-audit.md"], "verifyCommand": "grep -c '^| ' docs/superpowers/notes/2026-11-11-test-parallel-audit.md; zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["one table row per job with the listed checks", "every job passes alone", "each finding fixed or # serial with reason, known flakes included", "two parallel ALL PASS runs + one --serial ALL PASS with equal job and test counts"], "modelTier": "standard"}
```

### Task 7: Docs and acceptance runs

**Goal:** CLAUDE.md and README point at `all.zsh`, and the spec's acceptance (three consecutive green runs under 300 s, counts equal to `--serial`) is recorded.

**Files:**
- Modify: `CLAUDE.md` (Commands), `README.md` (test commands block near line 61), `docs/ARCHITECTURE.md` only if it lists test commands
- Ledger: acceptance section

**Acceptance Criteria:**
- [ ] CLAUDE.md Commands starts with `zsh tools/tests/all.zsh   # every suite, parallel; one verdict line`; the per-suite lines stay below it.
- [ ] README's test block lists the same line first.
- [ ] Three consecutive `zsh tools/tests/all.zsh; echo rc=$?` runs on the branch tip (rebased/merged onto current `main` if `main` moved) each print `ALL PASS` and `rc=0`; the three wall times and the job/test counts (equal to Task 6's `--serial` counts) are in the ledger. A real-state check: one of the three runs inside the live `dev` session's `tests` window via `tmux-ctl run tests` (inherits the real `TMUX`, `PATH`, `TC_*`).

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → `ALL PASS <n> jobs in <m>m<s>s` (< 5m) and `rc=0`

**Steps:**
- [ ] Edit the two docs; commit `docs(claude): run every suite with tools/tests/all.zsh`.
- [ ] Run the three acceptance runs (background, one at a time); record times and counts; commit the ledger lines with the plan's ledger.

```json:metadata
{"files": ["CLAUDE.md", "README.md"], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["CLAUDE.md Commands starts with the all.zsh line", "README test block lists it first", "three consecutive ALL PASS rc=0 runs under 5 min, one in the live tests window, times and counts in the ledger"], "modelTier": "mechanical"}
```
