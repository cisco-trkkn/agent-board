# Test hygiene, metrics and worktree fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five small faults: a leaked TUI stub, a leak check that sees other suites, a sweep that removes fresh fast-forwarded branches, metrics that miss rows from removed worktrees, and a failed-run log that can come from the wrong worktree.

**Architecture:** Five independent fixes in disjoint files (two zsh tests, `board/worktree_safety.py`, `board/metrics.py` + `claude/orchestrator.md`, `board/discord_feed.py`), each with its own tests, then one full-suite and real-state task.

**Tech Stack:** zsh test harness (`tools/tests/lib.zsh`), Python 3 unittest, git reflog.

**Spec:** `docs/superpowers/specs/2026-11-19-test-metrics-worktree-fixes-design.md`

## Global Constraints

- Work only in the worktree `.claude/worktrees/test-metrics-worktree-fixes` (branch `spec-test-metrics-worktree-fixes`). The live checkout runs `main` for every session.
- Each task stages only its own files (`git add <paths>`), never `-A` or `.`, and runs no whole-tree git command (`stash`, `reset`, `checkout`, `clean`, `rebase`).
- Commits: conventional with scope (`fix(tests): …`, `fix(worktree): …`, `feat(metrics): …`, `fix(discord): …`). End each commit message with the attribution trailer your harness specifies.
- Agent Bash runs zsh. Quote words that start with `=`.
- Line numbers in the spec are from 2026-11-19; the code moved since. The line references below are from `54f660a`.

**User decisions (already made):** D1–D5 in the spec ("1" on Discord, 2026-11-19):
- D1 Leak: an EXIT trap kills only the PIDs that match the test's own mark, then a check that none are left.
- D2 The fake holder's path is unique per run; the leak check greps for that path.
- D3 Grace when the newest reflog entry is under 24 h and every entry is a branch creation or a fast-forward (or a reset to an ancestor of the base).
- D4 `metrics start` records the spec's worktree; `record` counts every row whose cwd is under it.
- D5 `_failed_run_log` narrows to the spec's own worktree from `metadata.worktree`, falling back to today's pick without it.

**Lead rulings (made at plan time):**
- R1 Spec §2: the leak check was already scoped to `start $FB` by commit `703d27c`. What remains: the constant `/fake/discord/0.0.4` in `fc.js` becomes the per-run `$TT_DIR/fake/discord/0.0.4`, the leak check greps that path, and the decoy test is added.
- R2 Spec §3's "reset: moving to a commit that is an ancestor of the base": git writes the ref string as given (`reset: moving to HEAD~1`, probe below), not a SHA. So the check reads the entry's own SHA (`%H`) and tests it against the sweep's base refs (`ctx.refs`), which `_is_new` gets as a new argument.
- R3 Spec "Error handling": `metrics start --worktree` with a bad path exits 2. `metrics.main` returns 1 for every error today, so a `UsageError(MetricsError)` with `code = 2` is added and `main` returns `getattr(e, "code", 1)`. The printed line keeps `metrics.main`'s usual prefix: `metrics: start: --worktree must be under .claude/worktrees/`.

Reflog probe (git 2.54.0, scratch repo, run at plan time; newest first):

```
sp@{1795241560} commit (amend): own2
sp@{1795241560} commit: own
sp@{1795241560} merge main: Fast-forward
sp@{1795241560} reset: moving to HEAD~1
sp@{1795241560} merge main: Fast-forward
sp@{1795241560} branch: Created from HEAD
```

---

### Task 1: Stub reaping in test_discord_always_on.zsh

**Goal:** If part 3 of `tools/tests/test_discord_always_on.zsh` fails or is interrupted, it leaves no `fake_claude_tui.zsh` stub or fake discord server running.

**Files:**
- Modify: `tools/tests/test_discord_always_on.zsh` (part 3: `MARK=` at line 49, the leak checks at lines 123–124)

**Acceptance Criteria:**
- [ ] Right after `MARK=` is set, `dc_reap` is defined and `trap 'dc_reap; tt_teardown' EXIT INT TERM` is installed.
- [ ] `dc_reap` kills only PIDs from `pgrep -f "$MARK"`: TERM first, then KILL after 1 s for any still alive. It never fails the test (returns 0, ignores PIDs that are already gone).
- [ ] After the existing leak checks, a new check `leak: nothing with the test's mark left` asserts `pgrep -f "$MARK"` prints nothing.
- [ ] The existing kill loops stay as they are.
- [ ] Forced failure, run once and not kept: an `exit 1` inserted after the first `tt_wait 20 drawn` leaves no process matching `fake_claude_tui.zsh dcfake-` once the test exits. The before and after counts are in the report.
- [ ] `zsh tools/tests/test_discord_always_on.zsh` passes with no `FAIL` line.

**Verify:** `zsh tools/tests/test_discord_always_on.zsh > /tmp/dao.out 2>&1; echo rc=$?; grep -c '^FAIL' /tmp/dao.out; grep -c "nothing with the test's mark left" /tmp/dao.out` → `rc=0`, `0`, `1`

**Steps:**

- [ ] **Step 1: Add the reaper and trap.** Directly after the line `MARK="dcfake-$$-$RANDOM"`, insert:

```zsh
# a failure anywhere below must not leave the stub or its fake server running: reap by this run's own mark only
dc_reap() {
  local p
  for p in $(pgrep -f "$MARK"); do kill $p 2>/dev/null; done
  [[ -n "$(pgrep -f "$MARK")" ]] && { sleep 1; for p in $(pgrep -f "$MARK"); do kill -9 $p 2>/dev/null; done }
  return 0
}
trap 'dc_reap; tt_teardown' EXIT INT TERM
```

- [ ] **Step 2: Add the no-leftover check.** After the line `check "leak: no fake lead left" …`, add:

```zsh
check "leak: nothing with the test's mark left" test -z "$(pgrep -f "$MARK")"
```

- [ ] **Step 3: Forced-failure run (do not commit).** Count the stubs first: `pgrep -f 'fake_claude_tui.zsh dcfake-' | wc -l`. Insert `exit 1` on its own line right after the first `tt_wait 20 drawn`. Run `zsh tools/tests/test_discord_always_on.zsh; echo rc=$?`. Count again. The count after must equal the count before, normally 0 (a parallel suite elsewhere may own some; name them if so). Then remove the `exit 1` and check that `git diff tools/tests/test_discord_always_on.zsh` shows only Steps 1–2. For contrast, run the same forced failure once with the `trap` line commented out and report the count it leaves (expected: one more stub). Kill that stub by PID afterwards.

- [ ] **Step 4: Run the test.** Run the Verify line.

- [ ] **Step 5: Commit.**

```bash
git add tools/tests/test_discord_always_on.zsh
git commit -m "fix(tests): reap the fake claude TUI by its mark on any exit"
```

```json:metadata
{"files": ["tools/tests/test_discord_always_on.zsh"], "verifyCommand": "zsh tools/tests/test_discord_always_on.zsh > /tmp/dao.out 2>&1; echo rc=$?; grep -c '^FAIL' /tmp/dao.out; grep -c \"nothing with the test's mark left\" /tmp/dao.out", "acceptanceCriteria": ["dc_reap and trap 'dc_reap; tt_teardown' EXIT INT TERM installed right after MARK", "dc_reap kills only pgrep -f $MARK PIDs, TERM then KILL after 1 s, never fails", "new check: pgrep -f $MARK empty after the leak checks", "existing kill loops kept", "forced failure (not kept) leaves no stub; counts reported", "test passes with no FAIL line"], "modelTier": "mechanical"}
```

### Task 2: Per-run fake holder path in test_claude_orchestrator_dc.zsh

**Goal:** The fake holder in `tools/tests/test_claude_orchestrator_dc.zsh` carries a per-run plugin path, and its leak check greps that path, so a process from another suite never matches it.

**Files:**
- Modify: `tools/tests/test_claude_orchestrator_dc.zsh` (the `fc.js` heredoc at lines 96–101, `hold()` at 103–107, the leak check at 218–220)

**Acceptance Criteria:**
- [ ] `FP="$TT_DIR/fake/discord/0.0.4"` is set next to `FB=`, and `fc.js` takes the `--cwd` value from its argv (`process.argv[5]`, passed by `hold`), not the constant `/fake/discord/0.0.4`.
- [ ] `grep -c "'/fake/discord/0.0.4'" tools/tests/test_claude_orchestrator_dc.zsh` prints `0`.
- [ ] The wait loop and the leak check grep `ps -A -o args=` with `grep -F -- "$FP"`.
- [ ] A decoy started by the test (`node -e 'setTimeout(()=>{},30000)' bun run --cwd /fake/discord/0.0.4 start decoy`, without `DISCORD_STATE_DIR`) runs during the leak check, which still passes. The decoy is killed by its PID after the check, and a check confirms it is gone.
- [ ] Mutation, run once and not kept: grep the constant `fake/discord/0.0.4` instead of `$FP` in the leak check, and the test FAILs on that check (the decoy matches).
- [ ] All existing second-lead-guard checks still pass (`dc_holder` matches `*/discord/*` with `bun run .*start`, and `$FP` contains `/discord/`).

**Verify:** `zsh tools/tests/test_claude_orchestrator_dc.zsh > /tmp/ocd.out 2>&1; echo rc=$?; grep -c '^FAIL' /tmp/ocd.out; grep -c 'decoy' /tmp/ocd.out` → `rc=0`, `0`, `2` or more

**Steps:**

- [ ] **Step 1: Per-run path.** Change `FB="$TT_DIR/fb"; mkdir -p "$FB"; …` to also set `FP="$TT_DIR/fake/discord/0.0.4"; mkdir -p "$FP"`. In the `fc.js` heredoc, replace `'/fake/discord/0.0.4'` with `process.argv[5]`. In `hold()`, append `"$FP"` to the args: `… "$FB/claude" "$FB/fc.js" "$DC" "$f" "$FB" "$FP" …`. Do not change `process.argv[4]` (still `$FB`, used after `start`).

- [ ] **Step 2: Leak check by path, with a decoy.** Replace the two lines that grep `"start $FB"` (the `for i in {1..30}` wait and the `check "leak: no fake holder left"`) with:

```zsh
  for i in {1..30}; do [[ -z "$(ps -A -o args= | grep -F -- "$FP" | grep -v grep)" ]] && break; sleep 0.1; done
  # a decoy with the old constant path (another suite's holder) must not count as ours
  env -u DISCORD_STATE_DIR node -e 'setTimeout(()=>{},30000)' bun run --cwd /fake/discord/0.0.4 start decoy >/dev/null 2>&1 &
  DECOY=$!; sleep 0.3
  check "leak: decoy with the old constant path is running" kill -0 $DECOY
  # scoped to this run's own path ($FP is under $TT_DIR): other suites run fakes with other paths in parallel
  check "leak: no fake holder left"        test -z "$(ps -A -o args= | grep -F -- "$FP" | grep -v grep)"
  kill $DECOY 2>/dev/null; wait $DECOY 2>/dev/null
  check "leak: decoy gone"                 test -z "$(ps -A -o pid= | awk -v p=$DECOY '$1==p')"
```

- [ ] **Step 3: Mutation run (do not commit).** In the leak check line only, replace `"$FP"` with `fake/discord/0.0.4`. Run the test. Expect a `FAIL` on `leak: no fake holder left`. Revert it and check that `git diff` shows only Steps 1–2.

- [ ] **Step 4: Run the test.** Run the Verify line.

- [ ] **Step 5: Commit.**

```bash
git add tools/tests/test_claude_orchestrator_dc.zsh
git commit -m "fix(tests): per-run fake holder path; leak check ignores other suites"
```

```json:metadata
{"files": ["tools/tests/test_claude_orchestrator_dc.zsh"], "verifyCommand": "zsh tools/tests/test_claude_orchestrator_dc.zsh > /tmp/ocd.out 2>&1; echo rc=$?; grep -c '^FAIL' /tmp/ocd.out; grep -c 'decoy' /tmp/ocd.out", "acceptanceCriteria": ["FP=$TT_DIR/fake/discord/0.0.4 passed to fc.js as argv[5]; no '/fake/discord/0.0.4' constant left", "wait loop and leak check grep -F $FP", "a decoy with the old constant path runs during the leak check, which passes; decoy killed and checked gone", "mutation (grep the constant) makes the leak check FAIL, not kept", "all existing guard checks pass"], "modelTier": "mechanical"}
```

### Task 3: Reflog grace for fast-forwarded branches

**Goal:** A worktree branch created and then only fast-forwarded (or reset to an ancestor of the base) within 24 h is `kept` ("new, no commits yet") by the sweep, not removed as merged.

**Files:**
- Modify: `board/worktree_safety.py` (`_is_new` at 232–242, its call at 311)
- Test: `board/tests/test_worktree_safety_classify.py` (class `ClassifyStates`, near the grace tests at 48–81)

**Acceptance Criteria:**
- [ ] `_is_new(repo, branch, now, refs=())` reads `git reflog show --format=%gd %H %gs --date=unix refs/heads/<branch>`. It returns True only when the read succeeds, there is at least one entry, the newest (first) entry is under `NEW_GRACE` old (a future date counts as new, as today), and every entry's subject starts with `branch: Created from `, contains `: Fast-forward`, or starts with `reset: moving to ` with the entry's SHA an ancestor of one of `refs`.
- [ ] The call site passes `ctx.refs`. The docstring names the fast-forward and the reset cases.
- [ ] New tests: (a) created, then `merge --ff-only main` after a main commit, all entries back-dated to NOW−1 h → `("kept", "new, no commits yet")`; (b) the same back-dated to NOW−25 h → `safe`; (c) created, one own commit, back-dated NOW−1 h, not merged → state is not `kept` with reason `new, no commits yet`; (d) created, ff, then `reset --hard HEAD~1` (an ancestor of main), back-dated NOW−1 h → `kept` "new, no commits yet".
- [ ] Each new test names its mutation in a comment: dropping the `: Fast-forward` clause fails (a); dropping the age check fails (b); accepting any subject fails (c); dropping the reset clause fails (d). The RED run shows (a) and (d) fail on today's code.
- [ ] The existing tests in the file still pass (`test_unreadable_reflog_means_no_grace`, `test_a_young_worktree_with_a_merged_commit_is_safe`, `test_detached_worktree_gets_no_grace`, …).

**Verify:** `python3 -m unittest board.tests.test_worktree_safety_classify -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Failing tests.** Add a helper and four tests to `ClassifyStates`. `add_worktree` back-dates only the first reflog entry, and git stamps later entries with the wall clock (2026-11, after the fixture `NOW` of 2026-10-26), so the helper rewrites every entry:

```python
    def backdate_all(self, name, hours):
        # every reflog entry (not only the creation) to NOW - hours; git stamps entries with the wall clock
        log = self.repo / ".git" / "logs" / "refs" / "heads" / name
        t = int((NOW - timedelta(hours=hours)).timestamp())
        log.write_text(re.sub(r"> \d+ ", f"> {t} ", log.read_text()))

    def ff_worktree(self, name="w1"):
        wt = add_worktree(self.repo, name, created_hours_ago=1)
        git("commit", "--allow-empty", "-m", "on main", cwd=self.repo)
        git("merge", "--ff-only", "main", cwd=wt)
        return wt

    def test_fast_forwarded_young_branch_is_kept(self):   # mutation: drop the ': Fast-forward' clause -> fails
        self.ff_worktree()
        self.backdate_all("w1", 1)
        item = self.one()
        self.assertEqual((item["state"], item["reason"]), ("kept", "new, no commits yet"))

    def test_fast_forwarded_branch_past_24h_is_safe(self):   # mutation: drop the age check -> fails
        self.ff_worktree()
        self.backdate_all("w1", 25)
        self.assertEqual(self.one()["state"], "safe")

    def test_own_commit_gets_no_grace(self):   # mutation: accept any reflog subject -> fails
        add_worktree(self.repo, "w1", commits=1, created_hours_ago=1)
        self.backdate_all("w1", 1)
        item = self.one()
        self.assertNotEqual((item["state"], item["reason"]), ("kept", "new, no commits yet"))

    def test_reset_to_an_ancestor_of_base_is_kept(self):   # mutation: drop the reset clause -> fails
        wt = self.ff_worktree()
        git("reset", "--hard", "HEAD~1", cwd=wt)
        self.backdate_all("w1", 1)
        item = self.one()
        self.assertEqual((item["state"], item["reason"]), ("kept", "new, no commits yet"))
```

Add `import re` and `from datetime import timedelta` if the file lacks them. Import `NOW` (and `git`, `add_worktree`) from `worktree_fixtures` as the file already does for the others.

- [ ] **Step 2: RED.** `python3 -m unittest board.tests.test_worktree_safety_classify -v`: (a) and (d) FAIL (today's rule needs exactly one entry); (b) and (c) pass. Report the output.

- [ ] **Step 3: Implement.** Replace `_is_new`:

```python
def _is_new(repo, branch, now, refs=()):
    """True when the branch has no commits of its own and its newest reflog entry is under 24 h old: every entry is its
    creation (`branch: Created from …`), a fast-forward (`merge …: Fast-forward`, `pull: Fast-forward`), or a
    `reset: moving to` a commit that is an ancestor of one of `refs` (the sweep's base refs). A fresh spec branch that
    was fast-forwarded to main is such a branch: its HEAD is an ancestor of main, yet it is not merged work. Any other
    entry (`commit:`, `commit (amend):`, a real merge), an empty or unreadable reflog gives False (no grace)."""
    # %gd with --date=unix is `<branch>@{<epoch of the reflog entry>}`; %H is the entry's commit; %ct would be the commit date
    r = _git(repo, "reflog", "show", "--format=%gd %H %gs", "--date=unix", f"refs/heads/{branch}")
    lines = [l for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []
    m = re.match(r"\S*@\{(\d+)\} ", lines[0]) if lines else None
    if not m:
        return False
    if (now - datetime.fromtimestamp(int(m.group(1)), timezone.utc)).total_seconds() >= NEW_GRACE:
        return False
    for line in lines:
        parts = line.split(" ", 2)
        if len(parts) < 3:
            return False
        _, sha, subj = parts
        if subj.startswith("branch: Created from ") or ": Fast-forward" in subj:
            continue
        if subj.startswith("reset: moving to ") and any(_is_ancestor(repo, sha, ref) for ref in refs):
            continue
        return False
    return True
```

Change the call to `if branch and _is_new(ctx.repo, branch, ctx.now, ctx.refs):`. Read `_Ctx` first to check that `ctx.refs` holds ref names `_is_ancestor` accepts (it is already used that way at line 314).

- [ ] **Step 4: GREEN.** Run the Verify line. Then run the whole worktree_safety group: `python3 -m unittest discover -s board/tests -p 'test_worktree_safety*.py' 2>&1 | tail -3` → `OK`.

- [ ] **Step 5: Commit.**

```bash
git add board/worktree_safety.py board/tests/test_worktree_safety_classify.py
git commit -m "fix(worktree): 24 h grace covers a fresh branch fast-forwarded to main"
```

```json:metadata
{"files": ["board/worktree_safety.py", "board/tests/test_worktree_safety_classify.py"], "verifyCommand": "python3 -m unittest board.tests.test_worktree_safety_classify -v 2>&1 | tail -3", "acceptanceCriteria": ["_is_new(repo, branch, now, refs=()) reads %gd %H %gs; True only for young reflog of creations, fast-forwards, resets to an ancestor of refs", "call site passes ctx.refs; docstring names ff and reset", "tests (a) ff young kept, (b) ff 25h safe, (c) own commit no grace, (d) reset to ancestor kept", "each test names its mutation; RED shows (a),(d) failing on old code", "existing tests pass"], "modelTier": "standard"}
```

### Task 4: Worktree in the metrics start line

**Goal:** `tmux-ctl metrics start <spec> --batch <id> --worktree .claude/worktrees/<name>` records the worktree, and `record` counts every row whose cwd is under it, even after the worktree is gone. The queue rule passes `--worktree`.

**Files:**
- Modify: `board/metrics.py` (`_parser` start subparser ~1160, `cmd_start` 205–216, `build_record` 734, `main`'s error return ~1868, a new `rel_worktree` next to `rel_spec` ~1806)
- Modify: `claude/orchestrator.md` (Queue mode step 2, line 79)
- Test: `board/tests/test_metrics_record_usage.py` (class `AttributionTest`), plus a `start --worktree` CLI test in the same file or in the test file that already tests `metrics.main(["start", …])` (grep for it)

**Acceptance Criteria:**
- [ ] `metrics start` accepts `--worktree <path>`. Relative paths are taken from the main checkout root and absolute paths are made relative to it, the same way `rel_spec` does. A path that does not normalise to `.claude/worktrees/<name>[/…]` exits 2 with stderr `metrics: start: --worktree must be under .claude/worktrees/`, and nothing is appended to `runs.jsonl`.
- [ ] A valid `--worktree` writes `"worktree": ".claude/worktrees/<name>"` into the `start` record. Without the flag the record has no `worktree` key (byte-identical to today's shape).
- [ ] `build_record`: when the latest matching `start` record has `worktree`, `<root>/<worktree>` is added to the `wt` dirs given to `attributed_rows`. A row with `git_branch` "main" and cwd under that dir is counted, whether or not the directory exists. A row matched both by branch and by that dir is counted once.
- [ ] A `start` record without `worktree` is attributed as today: the same row is not counted.
- [ ] `MetricsError` subclass `UsageError` with `code = 2`. `main` returns `getattr(e, "code", 1)`. Every other error still returns 1.
- [ ] `claude/orchestrator.md` Queue mode step 2 reads ``run `tmux-ctl metrics start <spec> --batch <id> --worktree .claude/worktrees/<name>` after the branch and worktree exist, before `writing-plans` ``. Any test or other doc that quotes the old line (`grep -rn 'metrics start <spec>' claude tools board bin README.md docs/*.md`) is updated to match.
- [ ] Mutations named in the tests: dropping the `wt` union fails the "counted with worktree" test; skipping the validation fails the exit-2 test.

**Verify:** `python3 -m unittest board.tests.test_metrics_record_usage -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Failing tests** in `AttributionTest` (use the file's `Base` helpers `start`, `row`, `rec`; extend `start()` with a `worktree=None` keyword that adds the key when given):

```python
    def test_removed_worktree_rows_counted_when_start_names_it(self):   # mutation: drop the wt union in build_record -> fails
        self.start(SPEC1, worktree=".claude/worktrees/gone")
        self.row(self.t0 + 60, agent="impl", branch="main", cwd=self.root + "/.claude/worktrees/gone/board")   # dir never existed
        self.assertEqual(self.rec()["tokens"]["total"], 1500)

    def test_removed_worktree_rows_not_counted_without_it(self):
        self.start(SPEC1)
        self.row(self.t0 + 60, agent="impl", branch="main", cwd=self.root + "/.claude/worktrees/gone/board")
        self.assertEqual(self.rec()["tokens"]["total"], 0)

    def test_branch_and_worktree_row_counted_once(self):
        self.start(SPEC1, worktree=".claude/worktrees/gone")
        self.row(self.t0 + 60, agent="impl", branch="feat/x", cwd=self.root + "/.claude/worktrees/gone")
        self.assertEqual(self.rec()["tokens"]["total"], 1500)
```

(`row()` defaults to inp=1000, out=500, so one row is 1500 tokens; `rec()` uses branch `feat/x` for SPEC1.) Add a CLI test: `metrics.main(["start", SPEC1, "--batch", "B", "--worktree", "/tmp/elsewhere", "--repo", self.root])` returns 2 and the stderr line is exact (capture with `contextlib.redirect_stderr`). Do the same for `".claude/worktrees/../../x"` and for `".claude/worktrees"` (no name). `runs.jsonl` is unchanged after each (compare its bytes). With `".claude/worktrees/w1"`, the start record has `"worktree": ".claude/worktrees/w1"`. Use the repo-argument convention that existing CLI tests in the metrics test files use.

- [ ] **Step 2: RED.** Run the Verify line: the new tests fail (unknown argument / row not counted). Report the output.

- [ ] **Step 3: Implement.**

```python
class UsageError(MetricsError):
    """A bad argument value: exit 2."""
    code = 2


def rel_worktree(repo, path):
    """--worktree as `.claude/worktrees/<name>[/…]` relative to the main checkout; anything else is a UsageError."""
    root = os.path.realpath(main_root(repo))
    p = os.path.normpath(path if os.path.isabs(path) else os.path.join(root, path))
    rp = os.path.realpath(p) if os.path.exists(p) else os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))
    rel = os.path.relpath(rp, root)
    parts = rel.split(os.sep)
    if len(parts) < 3 or parts[:2] != [".claude", "worktrees"] or ".." in parts:
        raise UsageError("--worktree must be under .claude/worktrees/")
    return rel
```

In `_parser`: `st.add_argument("--worktree")`. In `cmd_start`, validate first, before any write: `wt = rel_worktree(repo, args.worktree) if args.worktree else None`. After building `rec`, set `if wt: rec["worktree"] = wt`. In `build_record`, after `wt = worktree_dirs(...)`:

```python
    if start and start.get("worktree"):
        wt = set(wt) | {os.path.join(root, start["worktree"])}   # rows of a worktree removed before record still count
```

In `main`'s `except`: `return getattr(e, "code", 1)`. Check that `UsageError` is defined after `MetricsError`.

- [ ] **Step 4: Orchestrator rule.** In `claude/orchestrator.md` step 2, replace ``run `tmux-ctl metrics start <spec> --batch <id>` before `writing-plans` `` with ``run `tmux-ctl metrics start <spec> --batch <id> --worktree .claude/worktrees/<name>` after the branch and worktree exist, before `writing-plans` ``. Grep for other copies and tests of this sentence (see the AC) and update them. Run any test that checks orchestrator.md text (`grep -rln 'orchestrator.md' tools/tests board/tests claude/hooks/tests`).

- [ ] **Step 5: GREEN.** Run the Verify line, then `python3 -m unittest discover -s board/tests -p 'test_metrics*.py' 2>&1 | tail -3` → `OK`.

- [ ] **Step 6: Commit.**

```bash
git add board/metrics.py board/tests/test_metrics_record_usage.py claude/orchestrator.md   # plus any test/doc updated in Step 4
git commit -m "feat(metrics): start --worktree; record counts rows of a removed worktree"
```

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_record_usage.py", "claude/orchestrator.md"], "verifyCommand": "python3 -m unittest board.tests.test_metrics_record_usage -v 2>&1 | tail -3", "acceptanceCriteria": ["start --worktree normalised like rel_spec; outside .claude/worktrees/<name> exits 2 with 'metrics: start: --worktree must be under .claude/worktrees/', nothing appended", "valid --worktree writes worktree into the start record; no flag = no key", "build_record adds <root>/<worktree> to wt dirs; main-branch row under a removed worktree counted; no double count", "start without worktree attributed as today", "UsageError code 2; other errors still 1", "orchestrator.md step 2 passes --worktree after the worktree exists; copies/tests updated", "tests name their mutations"], "modelTier": "standard"}
```

### Task 5: Failed-run log narrowed to the spec's worktree

**Goal:** When a failed `Plan & run:` task has `metadata.worktree`, the feed attaches the newest failing run from that worktree only, or none. Without the field, today's pick stands.

**Files:**
- Modify: `board/discord_feed.py` (`_failed_run_log` at 380–419, its call in `derive` at ~498)
- Test: `board/tests/test_discord_feed.py` (the failed-run-log class near 915–1010)

**Acceptance Criteria:**
- [ ] `_failed_run_log(project, now, worktree=None, root=None)`: when both are set, only runs whose cwd is `<root>/<worktree>` or below are candidates. With none, it returns None, and the post says `failed — no failing test run recorded` (the existing `no_run_log` path).
- [ ] `derive` passes `meta.get("worktree")` (only when it is a non-empty str) and its `root` for the completed failed `Plan & run:` task.
- [ ] Tests: (a) two worktrees' failing runs (`<root>/.claude/worktrees/a` older, `…/b` newer), `worktree=".claude/worktrees/a"` → the post names a's cmd and `· a ·`; (b) `worktree=".claude/worktrees/c"` with only a and b runs → no log; (c) `worktree` unset → b (today's newest pick); (d) a sibling-prefix cwd (`…/worktrees/ab`) is not under `…/worktrees/a`.
- [ ] Mutations named: removing the narrowing fails (a) and (b); using `startswith(base)` without the `/` fails (d).
- [ ] The existing tests in the class still pass (their records use cwd `/x/.claude/worktrees/w` and no `metadata.worktree`).

**Verify:** `python3 -m unittest board.tests.test_discord_feed -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Failing tests.** In the failed-run-log class, give `failed()` an optional `worktree=None` that sets `done["metadata"]["worktree"]` when given. Find the root the class's `derive` passes (`self.root` in the base class at ~478) and build cwds from it:

```python
    def test_worktree_narrows_to_own_run(self):   # mutation: drop the worktree narrowing -> fails
        a, b = str(self.root) + "/.claude/worktrees/a", str(self.root) + "/.claude/worktrees/b"
        self.write_runs(self.rec("ra", ts=self.NOW_I - 600, cmd="a cmd", cwd=a), self.rec("rb", ts=self.NOW_I - 60, cmd="b cmd", cwd=b))
        evs, st, ops = self.failed(worktree=".claude/worktrees/a")
        self.assertEqual(ops[1]["text"], f"failed run log: a cmd (exit 1) · a · {self.hhmm(self.NOW_I - 600)}")

    def test_worktree_without_own_run_posts_no_log(self):   # mutation: drop the narrowing -> b's log is posted
        b = str(self.root) + "/.claude/worktrees/b"
        self.write_runs(self.rec("rb", cwd=b))
        evs, st, ops = self.failed(worktree=".claude/worktrees/c")
        self.assertEqual(ops[1]["text"], "failed — no failing test run recorded")

    def test_no_worktree_keeps_newest_pick(self):
        a, b = str(self.root) + "/.claude/worktrees/a", str(self.root) + "/.claude/worktrees/b"
        self.write_runs(self.rec("ra", ts=self.NOW_I - 600, cmd="a cmd", cwd=a), self.rec("rb", ts=self.NOW_I - 60, cmd="b cmd", cwd=b))
        evs, st, ops = self.failed()
        self.assertEqual(ops[1]["text"], f"failed run log: b cmd (exit 1) · b · {self.hhmm(self.NOW_I - 60)}")

    def test_sibling_prefix_worktree_not_matched(self):   # mutation: startswith(base) without '/' -> fails
        ab = str(self.root) + "/.claude/worktrees/ab"
        self.write_runs(self.rec("rab", cwd=ab))
        evs, st, ops = self.failed(worktree=".claude/worktrees/a")
        self.assertEqual(ops[1]["text"], "failed — no failing test run recorded")
```

If this class's `derive` has no `self.root`, set one up the way the class at ~478 does. Report which one you used.

- [ ] **Step 2: RED.** Run the Verify line: (a), (b) and (d) fail. Report the output.

- [ ] **Step 3: Implement.** Change the signature to `def _failed_run_log(project, now, worktree=None, root=None):` and add to its docstring: "With `worktree` and `root`, only runs under <root>/<worktree> are candidates; none of them → None (another worktree's log is never posted)." After the `ok = [...]` filter, before `if not ok:`:

```python
    if worktree and root:
        base = os.path.join(str(root), str(worktree)).rstrip("/")
        ok = [r for r in ok if str(r.get("cwd", "")) == base or str(r.get("cwd", "")).startswith(base + "/")]
```

In `derive`, change the call to:

```python
                wt = meta.get("worktree") if isinstance(meta.get("worktree"), str) and meta.get("worktree") else None
                extra = _failed_run_log(project, now, wt, root) or {"no_run_log": True}
```

- [ ] **Step 4: GREEN.** Run the Verify line.

- [ ] **Step 5: Commit.**

```bash
git add board/discord_feed.py board/tests/test_discord_feed.py
git commit -m "fix(discord): failed-run log only from the spec's own worktree"
```

```json:metadata
{"files": ["board/discord_feed.py", "board/tests/test_discord_feed.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_feed -v 2>&1 | tail -3", "acceptanceCriteria": ["_failed_run_log(project, now, worktree=None, root=None) narrows to <root>/<worktree>; none -> None", "derive passes metadata.worktree (non-empty str) and root", "tests: own run picked; no own run -> no log; unset -> newest; sibling prefix not matched", "mutations named", "existing tests pass"], "modelTier": "standard"}
```

### Task 6: Full suite and read-only real-state checks

**Goal:** The whole suite is green on the branch, and each fix is checked once, read-only, against the real repo, usage index and run log.

**Files:**
- Read only: the live repo `/Users/francisco.ruiz/agent-board` (its reflogs, `docs/superpowers/metrics/runs.jsonl`), `$TMPDIR/tmux-ctl-$UID/usage.sqlite`, `~/.local/state/agent-board/runs-agent-board.jsonl`
- Create: `.superpowers/sdd/2026-11-21-test-metrics-worktree-fixes/real-state.md` (the evidence; not committed)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh; echo rc=$?` gives `rc=0`, or `rc=4` with its verdict line saying ALL PASS (4 = over the time budget, accepted on this machine). The verdict line is quoted.
- [ ] Reflog, real state: for every local branch of the live repo, `_is_new(repo, b, now, refs)` printed next to its reflog subjects (`git reflog show --format='%gs' refs/heads/<b>`). Uncapped counts: the branches checked, and the branches with a `commit` subject that got True (must be 0).
- [ ] Metrics, real state, nothing appended: `build_record` for spec `docs/superpowers/specs/2026-11-19-discord-ops-fixes-design.md` (batch `2026-11-11-1`, branch `feat/discord-ops-fixes`), called in Python on the real usage db with `runs.jsonl` read through an in-memory copy (or `metrics.LOG_OVERRIDE` if the module offers it) where the spec's latest start record gains `"worktree": ".claude/worktrees/discord-ops-fixes"`. It reports `tokens.total` with and without the field, and the new count is ≥ the old. The md5 of `docs/superpowers/metrics/runs.jsonl` is the same before and after.
- [ ] Failed-run log, real state: `_failed_run_log("agent-board", now, ".claude/worktrees/discord-ops-fixes", "/Users/francisco.ruiz/agent-board")` with `tc_env` pointed at a scratch discord dir (so no attachment lands in the real one), next to the same call with no worktree. Both results are printed. Every candidate the narrowed call could pick is under that worktree: a count of candidates outside it, printed, must be 0.
- [ ] `real-state.md` holds each command and its output.

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → `rc=0` (or `rc=4` with ALL PASS)

**Steps:**

- [ ] **Step 1: Full suite.** `tmux-ctl run -t 1200 tests "zsh tools/tests/all.zsh; echo rc=\$?"` from the worktree (`-C` the worktree path). Read the verdict line and `rc=`.
- [ ] **Step 2: Reflog check.** In Python with `sys.path` on `board/`: build `refs` the way `classify` builds `_Ctx.refs` (read `classify`), loop over `git for-each-ref --format=%(refname:short) refs/heads` of the live repo, and print `branch, _is_new(...), subjects`. Count as the AC says.
- [ ] **Step 3: Metrics check.** Read `build_record` and `read_log` to find how to feed it a log without touching the file (`LOG_OVERRIDE` at ~1797 is used by the backfill code). Take md5 before and after.
- [ ] **Step 4: Failed-run log check.** Point `TC_STATE` (or what `tc_env.discord_dir` reads) at a scratch dir, but read `runs-agent-board.jsonl` from the real state dir: copy it into the scratch state dir first.
- [ ] **Step 5: Write `real-state.md`** with each command and its output. No commit for this task (nothing in the repo changes). If any check fails, stop and report it to the lead with the output.

```json:metadata
{"files": [], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["all.zsh rc=0 or rc=4 with ALL PASS, verdict line quoted", "live repo: _is_new per branch with subjects; counts of branches checked and of commit-subject branches given True (0)", "real build_record for discord-ops-fixes with and without start worktree, tokens.total reported, runs.jsonl md5 unchanged", "real _failed_run_log narrowed vs unnarrowed, scratch discord dir, 0 candidates outside the worktree", "real-state.md holds commands and outputs"], "modelTier": "standard"}
```
