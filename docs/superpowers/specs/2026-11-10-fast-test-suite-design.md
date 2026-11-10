# Full test suite in under 5 minutes

Date: 2026-11-10 · Requested by the user during the 2026-11-10 regroup
Baseline: `docs/superpowers/notes/2026-11-10-test-timings-baseline.tsv` (name, seconds, exit code per file; serial run
on main `638c602`, 12 cores)

## Problem

Every suite in CLAUDE.md Commands, run one file at a time, takes **885 s**: zsh `run-all.zsh` 591 s (54 files),
board unittest 261 s (40 modules), docs skills 18 s, hooks 14 s, statusline 1 s, tools unittest under 1 s. Each
suite has its own command; there is no single runner or verdict line. The slowest files:

| File | s |
| --- | --- |
| `tools/tests/test_ctl_approve.zsh` | 115 |
| `board/tests/test_worktree_safety.py` | 113 (126 tests, ~100 git subprocess calls, fixtures built per `setUp`) |
| `tools/tests/test_teammate_window.zsh` | 58 |
| `board/tests/test_worktree_board.py` | 44 |
| `tools/tests/test_bg.zsh` | 38 |

Five files fail on main: `test_orchestrator_path`, `test_restart_orchestrator` (the relay launch line change), and `test_session_path` (4 errors), `test_session_root_path`,
`tools/tests/test_prompt_argv.zsh` (`orchestrator puts <repo>/bin first`, `set-environment PATH has <repo>/bin`).

## Decisions

Anything may change if coverage is kept: a parallel runner, plus speeding up every file over 30 s. No test is removed.

## Design

### 1. `tools/tests/all.zsh`

- Jobs, one per file, from every suite in CLAUDE.md Commands:
  - `board/tests/test_*.py` → `python3 -m unittest board.tests.<module>` (cwd = repo root);
  - `tools/tests/test_*.zsh` → `zsh <file>`;
  - `tools/tests/test_*.py` → `python3 -m unittest discover -s tools/tests -p '<file>'`;
  - `claude/skills/docs-{architecture,compose,report}/tests` and `claude/statusline/tests` → one job per suite dir
    (`python3 -m unittest discover -s <dir>`);
  - `claude/hooks/tests/test-*.sh` → `bash <file>`.
  The file lists are globbed at run time, so a new test file is picked up without editing the runner.
- Scheduling: at most `-j N` jobs at once (default `sysctl -n hw.ncpu`, Linux `nproc`). Order: slowest first by
  `<TC_STATE>/test-timings.tsv` (job name, seconds; rewritten after every full run); jobs with no timing first.
  Files whose first 5 lines contain `# serial` run alone, after the parallel phase.
- Per job: `TMPDIR` = a fresh dir under one run dir (`mktemp -d`), `TC_STATE` = `$TMPDIR/state`, stdout+stderr to
  `<rundir>/<job>.log`, exit code and wall time recorded. The run dir is removed on an all-pass run and kept (path
  printed) on a failure.
- Output: one line per finished job is not printed (quiet); a failed job prints `FAIL <job> (<s>s)` and the last 30
  lines of its log. End: the 5 slowest jobs with times, then exactly one verdict line:
  `ALL PASS <n> jobs in <m>m<s>s` or `FAIL <k>/<n>: <job names>`.
- Exit: 0 all pass under budget; 1 any failure; 4 all pass but wall time > 300 s (verdict line followed by
  `SLOW: <m>m<s>s over the 5 min budget`). `TC_TEST_BUDGET=<s>` overrides 300.
- Flags: `--suite board|zsh|tools|skills|statusline|hooks` (repeatable), `--serial` (`-j 1`, original suite order),
  `-j N`, `--list` (print job names and commands, run nothing).
- `tools/tests/run-all.zsh` stays as is (other docs and habits call it).

### 2. Parallel safety

The zsh tests already isolate (`tools/tests/lib.zsh`: socket `tctest-$$-$RANDOM`, `mktemp -d` state). The plan
audits every other test file for shared state: fixed `/tmp/...` paths, writes under `~/.claude` or
`~/.local/state`, fixed ports (board servers: `TMUX_DASH_PORT`), fixed tmux socket names, and fixes each so it uses
`TMPDIR`/`TC_STATE` or a free port. A file that cannot be made safe gets `# serial` with a one-line reason. Done when
two parallel runs back to back are green (flake check) and their pass counts equal a `--serial` run's.

### 3. Speed up files over 30 s

Each of the five files above ends under 30 s in a solo run, with the same number of tests (unittest `Ran N`, zsh
`ok` line count before and after, recorded in the plan's ledger):

- `test_worktree_safety.py`, `test_worktree_board.py`: build template git repos once per class (`setUpClass`) and
  give each test a copy (`shutil.copytree`, or `git clone --local --shared`), instead of `git init` + commits per
  `setUp`.
- `test_ctl_approve.zsh`, `test_teammate_window.zsh`, `test_bg.zsh`: replace fixed `sleep`s with `tt_wait` polling
  on the condition the sleep was waiting for; share one scratch tmux server per file where cases do not depend on a
  fresh server.
Profile first (where the time goes) before changing each file; a file whose time is inherent (a real timeout under
test) keeps it and the reason goes in the ledger.

### 4. Green baseline

This spec runs **second** in the queue, right after the queue-metrics spec and before restart-recovery (user's call, 2026-11-10), so it fixes all five failing files:

- `board/tests/test_orchestrator_path.py` (4) and `board/tests/test_restart_orchestrator.py` (2): the expected launch
  text becomes `relay.launch_line(root, prompt)`'s output (`cd -- <root> && <launcher> [prompt]`), asserted against
  the function, not a copied string. No change to `board/relay.py`.
- `test_session_path`, `test_session_root_path` and `test_prompt_argv.zsh` are debugged with
  `superpowers-extended-cc:systematic-debugging` (root cause first: the tests or the code) and fixed. Check first
  whether they fail only when run inside a live tmux/agent-board pane (inherited `TMUX`, `TC_*` or `PATH`): if so,
  the fix is isolation in the test (a clean env), not a code change.

### 5. Docs

CLAUDE.md Commands starts with `zsh tools/tests/all.zsh   # every suite, parallel; one verdict line` and keeps the
per-suite lines below it. README's test section (if any) points to it.

## Testing

- `tools/tests/test_all_runner.zsh`: a fake repo layout (env override for the roots, e.g. `TC_TEST_ROOT`) with stub
  jobs that sleep, pass, fail and carry `# serial`: slowest-first order from a timings file; `-j 2` never runs more
  than 2 at once (stubs log start/end stamps); serial jobs run alone after the rest; verdict line for pass and fail;
  exit 1 on failure, 4 over a tiny `TC_TEST_BUDGET`, 0 otherwise; failed log tail printed; `--suite`, `--list`,
  `--serial`; timings file rewritten. Marked `# serial` itself is not needed (it isolates).
- Acceptance: three consecutive `zsh tools/tests/all.zsh; echo rc=$?` runs on the merged result, each `ALL PASS` and
  rc=0 (under 300 s), wall times recorded in the ledger; total job and test counts equal a `--serial` run.

## Out of scope

CI configuration; changing what the tests assert; coverage measurement.
