# Session path = project root Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/api/state`'s session `path` is the project's main checkout (from tmux `#{session_path}`), not window 1's cwd, so the Usage tab, card alerts and labels, card worktree list, `project_repo()` and the header all see the right project.

**Architecture:** One shared rule, `relay.root_for(start_path)` (start folder if it is a directory, else `$HOME`, mapped through `main_checkout`, cached per start folder). `relay.session_root` delegates to it; `build_state` and `label_targets` read `#{session_path}` from the `list-panes` they already run and set `s["path"]` from it. Consumers are unchanged.

**Tech Stack:** Python 3 stdlib (`board/`), tmux 3.8, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-02-session-path-root-design.md`

## Global Constraints

- Worktree: `/Users/francisco.ruiz/agent-board/.claude/worktrees/usage-scope`, branch `feat/usage-scope`. The live checkout `~/agent-board` stays on `main` (it is the live install); never edit or run anything there.
- Never touch the live tmux server except read-only (`list-*`, `display`, `show-options`), and never the live board on port 7700. A real-state check runs a second board from the worktree: `TMUX_DASH_PORT=7710 python3 board/server.py` (its API URLs carry a token prefix: `http://127.0.0.1:7710/<token>/api/...`).
- Scratch tmux servers start with `-f /dev/null` (`~/.local/bin/tmux -L <unique-sock> -f /dev/null …`) and are killed afterwards.
- The root rule is exactly the spec's: the first of `#{session_path}`, `$HOME` that is a non-empty existing directory, mapped through `relay.main_checkout`; if neither is, `str(Path.home())`. Each pane's own `path` stays its `#{pane_current_path}`.
- `build_state` must not add a tmux exec: `#{session_path}` goes into the existing `list-panes -a` format (`board/tests/test_poll_efficiency.py` counts execs).
- `state()` must not raise on an empty or removed `#{session_path}`.
- Board tests set `TC_STATE` to a temp dir (they read `<TC_STATE>/statusline/`).
- Suite verdict: the board suite's own `Ran N tests … OK` line.
- Commits: conventional with scope (`fix(board): …`, `docs(plan): …`), ending with the attribution trailer your harness specifies.

**User decisions (already made):**
- Fix `path` at its source (state() and label_targets), not per consumer and not as a second `root` field (AskUserQuestion, 2026-11-02).
- Design and spec approved as written (2026-11-02).

---

### Task 1: A session's path comes from its start folder

**Goal:** `relay.root_for` exists and is cached; `session_root`, `build_state` and `label_targets` all use it, so a session whose window 1 sits in `~` gets its repo as `path`.

**Files:**
- Modify: `board/relay.py` (`main_checkout` / `session_root`, around lines 53-74)
- Modify: `board/server.py` (`build_state` around 284-321; `label_targets` around 330-350)
- Create: `board/tests/test_session_root_path.py`
- Modify (fixture rows only, to the new field count): `board/tests/test_activity.py`, `board/tests/test_usage.py`, and any other test whose fake `list-panes` rows feed `build_state` or `label_targets`

**Acceptance Criteria:**
- [ ] `relay.root_for(start_path)` implements the Global Constraints rule; a second call with the same existing `start_path` runs no git (`main_checkout` called once). Mutation: drop the cache → the cache test fails.
- [ ] `relay.session_root(tmux, sess)` keeps its signature and returns `root_for(<#{session_path}>)`; `board/tests/test_relay.py` and `board/tests/test_restart_orchestrator.py` still pass.
- [ ] `build_state`: with a fake `list-panes` where window 1's pane cwd is `/elsewhere` and `#{session_path}` is a scratch git repo, `s["path"]` is that repo and the pane's `path` is still `/elsewhere`. Mutation: restore "window 1's cwd" → fails.
- [ ] `label_targets`: the same, through its `run=` fake.
- [ ] `#{session_path}` a worktree of the scratch repo (real `git worktree add`) → `path` is the main checkout. Empty or removed → `path` is the (patched, temp) `$HOME`; `build_state` does not raise.
- [ ] `/api/usage?session=<s>` for such a session returns rows whose `cwd` is under the repo (not the home lead's). If an HTTP test harness exists in `board/tests/test_usage.py` use it; otherwise test the handler's path lookup plus `usage.report(…, repo)` together.
- [ ] Every existing fake `list-panes` row is updated (uncapped `grep -c` of the rows before and after, in the report); `board/tests/test_poll_efficiency.py` passes unchanged.
- [ ] Board suite: `Ran N tests … OK`.

**Verify:** `python3 -m unittest discover -s board/tests 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Read.** `board/relay.py:53-74`, `board/server.py` `build_state`, `label_targets`, `session_path`, `project_repo`, the `api/usage` handler (around 923-940), and `board/tests/test_session_path.py` (the board-bugs Task 1 tests, for the fake-tmux style). Count the existing fake rows: `grep -n -E "S\.join\(\[|label_rows\(" board/tests/*.py` (uncapped; record the count).

- [ ] **Step 2: Write the failing tests** in `board/tests/test_session_root_path.py`. Shape (adapt names to what Step 1 shows):

```python
import os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
import sys; sys.path.insert(0, str(HERE.parent))
import relay, server

def git(*a, cwd):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)

class Repo:
    """A scratch git repo with one worktree under .claude/worktrees/w."""
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(os.path.realpath(self.tmp.name)) / "proj"
        self.repo.mkdir()
        git("init", "-q", cwd=self.repo)
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i", cwd=self.repo)
        self.wt = self.repo / ".claude" / "worktrees" / "w"
        git("worktree", "add", "-q", str(self.wt), cwd=self.repo)

class RootForTest(unittest.TestCase):
    def setUp(self):
        relay._roots.clear()
        self.r = Repo(); self.addCleanup(self.r.tmp.cleanup)
        self.home = tempfile.TemporaryDirectory(); self.addCleanup(self.home.cleanup)

    def test_repo_is_its_own_root(self):
        self.assertEqual(relay.root_for(str(self.r.repo)), str(self.r.repo))

    def test_worktree_maps_to_main_checkout(self):
        self.assertEqual(relay.root_for(str(self.r.wt)), str(self.r.repo))

    def test_missing_or_empty_falls_back_to_home(self):
        with mock.patch.dict(os.environ, {"HOME": self.home.name}):
            self.assertEqual(relay.root_for(str(self.r.repo / "gone")), self.home.name)
            self.assertEqual(relay.root_for(""), self.home.name)

    def test_cached_per_start_path(self):   # mutation: drop the cache -> called twice
        with mock.patch.object(relay, "main_checkout", wraps=relay.main_checkout) as mc:
            relay.root_for(str(self.r.repo)); relay.root_for(str(self.r.repo))
        self.assertEqual(mc.call_count, 1)
```

  Then `BuildStateRootTest` and `LabelTargetsRootTest`: build fake `list-panes` output with `server.SEP.join(...)` in the field order of `build_state`'s / `label_targets`' format **with `#{session_path}` appended as the last field**; window 1's pane cwd `/elsewhere`, session_path `str(self.r.repo)` (and the worktree, and a removed path). Patch `server.tmux` (and `server.cached_worktrees`, `server.pane_text` as the existing `build_state` tests do); call `server.build_state()` / `server.label_targets(run=fake)`. Assert `s["path"]` and the pane `path`. Mutation note beside the first assert: "restore `if s["path"] is None or widx == "1": s["path"] = path` → fails". Then the `/api/usage` scope test (see Acceptance Criteria).

- [ ] **Step 3: Run; expect failures** (`AttributeError: module 'relay' has no attribute '_roots'` / `root_for`, and `path == '/elsewhere'`): `python3 -m unittest board.tests.test_session_root_path -v`

- [ ] **Step 4: Implement `root_for`** in `board/relay.py` and make `session_root` use it:

```python
_roots = {}   # start path -> main checkout; main_checkout of an existing dir does not change


def root_for(start_path):
    """The project's main checkout for a session started in start_path: that dir, else $HOME, else Path.home().

    A path that is empty or no longer a directory (a removed worktree) is skipped and its cache entry dropped.
    """
    for d in (start_path, os.environ.get("HOME", "")):
        if d and os.path.isdir(d):
            if d not in _roots:
                _roots[d] = main_checkout(d)
            return _roots[d]
        _roots.pop(d, None)
    return str(Path.home())


def session_root(tmux, sess):
    """Where the new lead starts: the project's main checkout, never a worktree (auto-cleanup may remove it).
    The claude pane's current path is not used: Claude Code follows the lead's cd."""
    return root_for(tmux("display", "-p", "-t", f"={sess}:", "#{session_path}").strip())
```

  If an existing `test_relay.py` / `test_restart_orchestrator.py` case patches `main_checkout` with different results for the same path, clear `relay._roots` in that class's `setUp` (the cache, not the test, is the change).

- [ ] **Step 5: `build_state` and `label_targets`.** Append `"#{session_path}"` as the last field of each format; bump the field-count checks (`len(f) == 15` → `16` in `build_state`, `9` → `10` in `label_targets`); read the session path from the new last field; set `s["path"] = relay.root_for(<session path>)` when the session dict is created; delete the two `if s["path"] is None or widx == "1": s["path"] = path` blocks. Indexes `f[0..14]` keep their meaning (the new field is last, so `f[14]` is still `@tc_bg`).

- [ ] **Step 6: Update the existing fake rows** found in Step 1 to the new field count: append the session path as the last element of each row. Where a test's assertion depends on `path` matching a fake cwd like `"/r"` (the `build_state` tests in `board/tests/test_usage.py`, whose `LEAD` has `cwd "/r"`), patch `server.relay.root_for` with `side_effect=lambda p: p` in that test so `"/r"` stays `"/r"`. Re-count the rows (uncapped) and confirm the count matches Step 1.

- [ ] **Step 7: Run** the new tests, `board.tests.test_relay`, `board.tests.test_restart_orchestrator`, `board.tests.test_poll_efficiency`, `board.tests.test_usage`, `board.tests.test_activity`; then apply each named mutation once and show it fails; then the board suite (output to a file, ~5 min; read its own `Ran N tests … OK` line).

- [ ] **Step 8: Commit by path:** `fix(board): a session's path is its project root, from tmux session_path`.

```json:metadata
{"files": ["board/relay.py", "board/server.py", "board/tests/test_session_root_path.py", "board/tests/test_activity.py", "board/tests/test_usage.py"], "verifyCommand": "python3 -m unittest discover -s board/tests 2>&1 | tail -3", "acceptanceCriteria": ["root_for implements the spec rule and caches per start path; cache mutation fails a test", "session_root delegates to root_for; relay and restart tests pass", "build_state path = root of #{session_path}, pane path unchanged; window-1 mutation fails", "label_targets same", "worktree start path -> main checkout; empty/removed -> $HOME; no raise", "/api/usage for such a session returns the project's rows", "every fake list-panes row updated (counts before/after); poll_efficiency unchanged", "board suite OK"], "modelTier": "standard"}
```

---

### Task 2: Real-state check of project scoping

**Goal:** Prove on the real sessions that, with the fix, each project session's `/api/usage` returns that project's live rows and its card carries the project root.

**Files:**
- Create: `docs/superpowers/plans/2026-11-02-session-path-root-e2e-report.md`

**Acceptance Criteria:**
- [ ] A second board runs from the worktree on port 7710 (`TMUX_DASH_PORT=7710 python3 board/server.py`) against the real state dir (no `TC_STATE` override); the live board on 7700 is not touched. The report gives the command and stops the server afterwards (PID killed, `ps` shows it gone).
- [ ] For each project session on the real tmux server (`tmux list-sessions`, excluding `-bg` and `_web-` sessions; the count stated), the report holds: its `#{session_path}`, its window 1 `#{pane_current_path}`, its `path` from 7710's `/api/state`, and the `cwd` of every row from 7710's `/api/usage?session=<name>`.
- [ ] For each of those sessions, the row count from `/api/usage` equals the live-row count of an in-process `usage.report()` for the same root, stated uncapped per session; every row's `cwd` is the root or under `<root>/.claude/worktrees/`. At least one session has window 1's cwd ≠ its root (on 2026-11-02: `agent-board`, `interiors`, `master-gcp-repo`, all with window 1 in `~`) and still returns its own project's rows.
- [ ] Each card's `worktrees` list in `/api/state` holds only paths under that card's root.
- [ ] Only read-only commands ran against the live tmux server; the report lists every command run.
- [ ] The report has exactly 4 `## ` sections: Setup, Usage per project, Cards, Commands run.

**Verify:** `grep -c '^## ' docs/superpowers/plans/2026-11-02-session-path-root-e2e-report.md` → `4`

**Steps:**

- [ ] **Step 1:** Start the 7710 board in the background from the worktree, save its PID, read its printed URL (token prefix).
- [ ] **Step 2:** Collect the sessions and their `#{session_path}` / window 1 cwd with read-only `tmux list-sessions` / `list-panes` / `display`.
- [ ] **Step 3:** For each session, fetch `/api/state` (once) and `/api/usage?session=<name>`; run `usage.report()` in-process for the same root (same `live_s`) and compare counts; read both within a few seconds, and if a count differs re-read both once and report both reads.
- [ ] **Step 4:** Write the report with the 4 sections; kill the server by PID and show `ps` without it.
- [ ] **Step 5:** Commit the report by path: `docs(plan): session path root real-state check`.

```json:metadata
{"files": ["docs/superpowers/plans/2026-11-02-session-path-root-e2e-report.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/plans/2026-11-02-session-path-root-e2e-report.md", "acceptanceCriteria": ["second board on 7710 from the worktree, real state; stopped afterwards", "per session: session_path, window-1 cwd, /api/state path, /api/usage row cwds", "per-session row counts match in-process report(); a session with window-1 cwd != root returns its own rows", "card worktrees under the card root", "read-only against live tmux; commands listed", "report has 4 ## sections"], "modelTier": "standard"}
```
