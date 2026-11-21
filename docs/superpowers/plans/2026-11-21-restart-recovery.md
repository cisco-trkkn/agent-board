# Restart recovery §4-5: tmux server cwd warning and `root_for` without the `$HOME` fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A gone tmux server cwd is reported (board banner, first line of `tmux-ctl list`), and `relay.root_for` never silently answers `$HOME`: a removed worktree maps to its main checkout, anything else unknowable is `None`, and relay, lead-restart and the board's restart refuse with `project folder is gone: <start_path>`.

**Architecture:** `board/relay.py` gains `_gone_root`, `FolderGone` and `session_start`; `root_for` returns `None` instead of `$HOME`, and `session_root` raises `FolderGone`. Display callers in `board/server.py` show `root_for(p) or p`. Detection is `restore.tmux_server_cwd(run, tmux)` (`display -p '#{pid}|#{socket_path}'` then `lsof -a -p <pid> -d cwd -Fn`), which the board caches for 60 s into `build_state()["server_warning"]` and shows in a header banner. `bin/tmux-ctl list` does its own `lsof`. Docs gain the `(cd ~ && …)` auto-attach snippet, and the user changes `~/.zshrc` line 22 at the user gate.

**Tech Stack:** Python 3.9+ (`unittest`, `unittest.mock`), zsh (`bin/tmux-ctl`, `tools/tests/lib.zsh`), tmux 3.8 (`~/.local/bin/tmux`), macOS `/usr/sbin/lsof`, node (the board-page test harness), vanilla JS in `board/index.html`.

**Spec:** docs/superpowers/specs/2026-11-10-restart-recovery-design.md (§4, §5, and their Error handling and Testing items only)

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-10-restart-recovery-design.md",
 "base": "878263e",
 "depends_on": [],
 "writes": [{"path": "board/relay.py", "mode": "modify"},
            {"path": "board/server.py", "mode": "modify"},
            {"path": "board/restore.py", "mode": "modify"},
            {"path": "board/index.html", "mode": "modify"},
            {"path": "bin/tmux-ctl", "mode": "modify"},
            {"path": "board/tests/test_relay.py", "mode": "modify"},
            {"path": "board/tests/test_session_root_path.py", "mode": "modify"},
            {"path": "board/tests/test_restart_orchestrator.py", "mode": "modify"},
            {"path": "board/tests/test_server_cwd.py", "mode": "create"},
            {"path": "board/tests/test_server_warning.py", "mode": "create"},
            {"path": "board/tests/test_server_warn_ui.py", "mode": "create"},
            {"path": "tools/tests/test_server_cwd.zsh", "mode": "create"},
            {"path": "docs/INSTALL.md", "mode": "modify"},
            {"path": "docs/CUSTOMIZATION.md", "mode": "modify"}],
 "reads": ["bin/_tc_bins.zsh", "bin/dev", "bin/tmux-dash", "board/paneclass.py", "board/dream.py",
           "board/tests/test_discord_wiring.py", "tools/tests/lib.zsh", "tools/tests/test_tc_tmux_cwd.zsh", "~/.zshrc"],
 "produces": ["relay.FolderGone", "relay.session_start", "restore.tmux_server_cwd", "server.server_warning",
              "build_state server_warning key", "tmux-ctl list cwd warning line"],
 "consumes": ["tc_tmux new-session runs from $HOME (abf11a9)"],
 "tests": ["board/tests/test_relay.py", "board/tests/test_session_root_path.py", "board/tests/test_restart_orchestrator.py",
           "board/tests/test_server_cwd.py", "board/tests/test_server_warning.py", "board/tests/test_server_warn_ui.py",
           "tools/tests/test_server_cwd.zsh"]}
```

## Global Constraints

- **Scope:** spec §4 and §5 only. §1-3 (snapshot, board at login, restore) shipped earlier under
  `2026-11-18-reboot-auto-restore` (`board/restore.py`, commits b905c17..15829c5); nothing here touches them.
- **Prevention is already shipped, so it is not re-planned:** `tc_tmux new-session` runs from `$HOME` (commit abf11a9,
  `bin/_tc_bins.zsh` lines 61-67, covered by `tools/tests/test_tc_tmux_cwd.zsh`). `bin/dev`, `bin/tmux-ctl`,
  `bin/tmux-overseer` and `bin/tmux-dev-layout` create sessions through it, and `bin/tmux-dash` creates none. This plan
  only adds a regression check that `dev` leaves the server in `$HOME` (Task 5).
- **The warning text, exactly** (`<cwd>` = lsof's `n` line, `<socket>` = the server's `#{socket_path}`):
  `tmux server cwd is gone (<cwd>): new panes start there; restart the tmux server from ~ (tmux -S <socket> kill-server ends every session on it; reopen each project with agent-board dev)`.
  The Python and zsh copies must be byte-identical.
- **The refusal text, exactly:** `project folder is gone: <start_path>` (`<start_path>` as tmux reports
  `#{session_path}`, possibly empty). Relay CLI: `relay failed: project folder is gone: …` on stderr, exit 1.
  lead-restart: `lead-restart: project folder is gone: …` on stderr, exit 1. Board: the action's error toast.
- **Failure is silent:** no server, `lsof` missing or failing, an unparsable pid, or any exception means no warning
  and never an error in the state poll (spec, Error handling).
- **`lsof` path:** `/usr/sbin/lsof` when it exists, else `lsof` on `PATH` (the LaunchAgent `PATH` lacks `/usr/sbin`).
- **Zsh gotchas** (CLAUDE.md): never name a variable `path`; quote `=name` tmux targets; brace variables before `:`.
  Test servers start with `-f /dev/null`.
- **Commits:** conventional with scope (`fix(relay): …`, `feat(board): …`, `feat(tmux-ctl): …`, `docs(install): …`).
  End each commit message with the attribution trailer your harness specifies. Stage only your own paths.

**User decisions (already made):** the spec's Decisions block (restore is one click, and so on: §1-3, already shipped).
Planning scope from the lead: §4-5 only.

**Recorded spec deviations (approved by the lead, 2026-11-21):**
- **Spec §4 warning advice was corrected.** The spec's text ends `restart the tmux server (agent-board dash stop, then
  start)`. `bin/tmux-dash` `stop` (lines 62-64) stops only the board and ttyd, never the tmux server, so that advice
  does not fix anything. The text above names `tmux -S <socket> kill-server` with the server's real socket from
  `#{socket_path}`. It does not say `-L agent-board`, because `bin/_tc_bins.zsh` `tc_tmux_resolve` puts a legacy install on
  the default socket (`-L default`, or `$TMUX`'s socket) and honours `AGENT_BOARD_TMUX_SOCKET`. Probe 2026-11-21:
  `~/.local/bin/tmux -L agent-board display -p '#{pid}|#{socket_path}'` → `1303|/private/tmp/tmux-503/agent-board`.
- **The spec's "INSTALL's auto-attach snippet" does not exist.** `docs/INSTALL.md` has none, and only
  `docs/CUSTOMIZATION.md` line 50 mentions `new-session -A -s main`. Task 6 adds an optional snippet to INSTALL in the
  `(cd ~ && …)` form and updates the CUSTOMIZATION example.
- **The spec's display rule `root_for(p) or p` also covers `label_targets`** (`board/server.py` ~669, the session
  label path). It is the second `build_state`-style caller the spec means by "both places".
- **`lead_info` keeps `relay.session_root` and catches `FolderGone` → `""`** instead of raising, so a project with a
  gone folder keeps its lead view. `board/tests/test_discord_wiring.py` `LeadInfosTest` mocks `session_root`.

**Probes run while planning (2026-11-21, tmux 3.8, macOS):**
- `lsof` on a scratch server whose start dir was then `rmdir`ed still prints the old path as its `n` line (`n/private/tmp/cwdp.1ZR6`
  before and after), so "not a dir" is the gone test.
- The plan's full code was applied once in the worktree. All of `python3 -m unittest discover -s board/tests` was run
  with the `root_for` change: exactly 6 old tests failed, all on the removed fallback (`test_relay`
  `test_deleted_worktree_session_path_falls_back_to_home`, `test_nothing_usable_falls_back_to_home`;
  `test_session_root_path` `test_missing_or_empty_falls_back_to_home` and both `test_removed_or_empty_start_is_home`;
  `test_discord_wiring` `LeadInfosTest.test_state_mapping_and_fields`, fixed by the `lead_info` design above). With the
  rewrites below, the affected modules ran 157 tests, OK. Every mutation named below was run and fails its test. The
  zsh test is RED on main only at "first line warns" and passes with Task 5's code. The probe edits were reverted, and
  this branch holds only the plan.

---

### Task 1: `root_for` without the `$HOME` fallback; relay and lead-restart refuse

**Goal:** `relay.root_for` maps a removed worktree to its main checkout and returns `None` for an empty path or a gone path outside any repo (never `$HOME`); `relay.session_root` raises `FolderGone("project folder is gone: <start_path>")`, and `relay.relay` and `relay.restart_lead` refuse before waiting or respawning.

**Files:**
- Modify: `board/relay.py` (`root_for` ~line 84, `session_root` ~line 104, `relay` ~line 161, `restart_lead` ~line 260)
- Modify: `board/tests/test_relay.py` (`SessionRootTest` ~lines 162-179, new `FolderGoneRefusalTest` at the end)
- Modify: `board/tests/test_session_root_path.py` (`RootForTest` ~line 39, `HomeGuardTest`)

**Acceptance Criteria:**
- [ ] `root_for("<repo>/.claude/worktrees/w")` after `git worktree remove` returns `<repo>`.
- [ ] `root_for("")` and `root_for("<non-git tmp>/gone/deeper")` return `None`; `root_for("~/gone-project/x")` with `~` a git repo returns `None`.
- [ ] An existing dir behaves exactly as before (all other `RootForTest`, `HomeGuardTest`, `SessionRootTest` tests pass unchanged).
- [ ] `session_root` with a gone non-git or empty start path raises `relay.FolderGone` with message `project folder is gone: <start_path>`.
- [ ] `relay.relay` with a gone start path raises `FolderGone` without calling `wait_turn_end` or `respawn-pane`; `relay.main([...])` returns 1 and prints `relay failed: project folder is gone: <path>` on stderr.
- [ ] `relay.restart_lead` with a gone start path raises `LeadRestartError("project folder is gone: <path>")` and sends no `respawn-pane`.

**Verify:** `python3 -m unittest board.tests.test_relay board.tests.test_session_root_path` → `OK`

**Steps:**

- [ ] **Step 1: Rewrite the fallback tests (RED).** In `board/tests/test_relay.py` `SessionRootTest`, replace `test_deleted_worktree_session_path_falls_back_to_home` and `test_nothing_usable_falls_back_to_home` with:

```python
    def test_deleted_worktree_session_path_maps_to_main_checkout(self):
        git(self.repo, "worktree", "remove", "--force", str(self.wt))
        with mock.patch.dict(os.environ, {"HOME": str(self.plain)}):
            self.assertEqual(self.root(RootTmux({"%5": str(self.plain)}, session_path=str(self.wt))), str(self.repo))

    def test_gone_non_git_session_path_raises_folder_gone(self):   # mutation: return $HOME instead -> no raise
        gone = str(self.plain / "gone")
        with mock.patch.dict(os.environ, {"HOME": str(self.plain)}), self.assertRaises(relay.FolderGone) as cm:
            self.root(RootTmux({"%5": str(self.repo)}, session_path=gone))
        self.assertEqual(str(cm.exception), f"project folder is gone: {gone}")
```

and

```python
    def test_empty_session_path_raises_folder_gone(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.plain)}), self.assertRaises(relay.FolderGone) as cm:
            self.root(RootTmux({"%5": "/gone"}, session_path=""))
        self.assertEqual(str(cm.exception), "project folder is gone: ")
```

Add `import contextlib` and `import io` at the top of `test_relay.py` (beside the other imports), and append this class at the end of the file:

```python
class FolderGoneRefusalTest(unittest.TestCase):
    """A gone, non-git start path: relay and lead-restart refuse before any respawn (spec restart-recovery §5)."""
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.gone = str(self.d / "gone")
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.d), "SHELL": "/bin/zsh"}); self.env.start(); self.addCleanup(self.env.stop)

    def test_relay_refuses_without_waiting_or_respawning(self):   # mutation: move session_root after the wait -> wait_turn_end called
        fake = FakeTmux(); fake.root = self.gone
        with mock.patch.object(relay, "wait_turn_end") as wait, self.assertRaises(relay.FolderGone) as cm:
            relay.relay(fake, "proj", "/d.md", str(self.d), "OLD1", sleep=lambda s: None)
        self.assertEqual(str(cm.exception), f"project folder is gone: {self.gone}")
        wait.assert_not_called()
        self.assertNotIn("respawn-pane", fake.names())

    def test_relay_cli_exits_1_with_the_message(self):
        fake = FakeTmux(); fake.root = self.gone
        err = io.StringIO()
        with mock.patch.object(paneclass, "tmux_runner", return_value=fake), contextlib.redirect_stderr(err):
            rc = relay.main(["--session", "proj", "--doc", "/d.md", "--state", str(self.d)])
        self.assertEqual(rc, 1)
        self.assertIn(f"relay failed: project folder is gone: {self.gone}", err.getvalue())
        self.assertNotIn("respawn-pane", fake.names())

    def test_lead_restart_refuses_with_lead_restart_error(self):   # mutation: drop the FolderGone -> LeadRestartError wrap -> FolderGone escapes
        t = LeadTmux([("proj", "", "")], {"proj": [("claude", "@1", "%5")]}, root=self.gone)
        with self.assertRaises(relay.LeadRestartError) as cm:
            relay.restart_lead(t, "proj", resume=True, home=str(self.d), state=str(self.d))
        self.assertEqual(str(cm.exception), f"project folder is gone: {self.gone}")
        self.assertNotIn("respawn-pane", t.names())
```

In `board/tests/test_session_root_path.py` `RootForTest`, replace `test_missing_or_empty_falls_back_to_home` with:

```python
    def test_removed_worktree_maps_to_main_checkout(self):   # mutation: return None for every gone path -> fails
        git("worktree", "remove", "--force", str(self.r.wt), cwd=self.r.repo)
        with mock.patch.dict(os.environ, {"HOME": self.home.name}):
            self.assertEqual(relay.root_for(str(self.r.wt)), str(self.r.repo))

    def test_gone_non_git_path_and_empty_are_none(self):   # mutation: restore the $HOME fallback -> home returned
        with mock.patch.dict(os.environ, {"HOME": self.home.name}):
            self.assertIsNone(relay.root_for(str(Path(self.home.name) / "gone" / "deeper")))
            self.assertIsNone(relay.root_for(""))
```

and append to the end of `HomeGuardTest` (its `setUp` makes `self.home` a git repo):

```python
    def test_gone_path_under_the_home_repo_is_none(self):   # mutation: drop the toplevel == $HOME check -> ~ returned
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertIsNone(relay.root_for(str(self.home / "gone-project" / "x")))
```

- [ ] **Step 2: Run RED.** `python3 -m unittest board.tests.test_relay board.tests.test_session_root_path` → errors `AttributeError: module 'relay' has no attribute 'FolderGone'` and failures on the `root_for` tests (home returned).

- [ ] **Step 3: Implement in `board/relay.py`.** Replace the whole `root_for` function and the whole `session_root` function (from `def root_for(start_path):` up to, not including, `def orchestrator():`) with:

```python
def _gone_root(start_path):
    """The main checkout for a start path that no longer exists (a removed worktree): the repo of its nearest existing
    parent, stopping before /. None when that parent is in no repo, git cannot run, or the repo's toplevel is $HOME."""
    p = os.path.dirname(os.path.normpath(start_path))
    while p != os.path.dirname(p) and not os.path.isdir(p):
        p = os.path.dirname(p)
    if p == os.path.dirname(p):   # reached /
        return None
    try:
        r = subprocess.run(["git", "-C", p, "rev-parse", "--path-format=absolute", "--git-common-dir", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = r.stdout.splitlines()
    if r.returncode != 0 or len(lines) < 2 or not lines[0].strip():
        return None
    home = os.environ.get("HOME", "")
    if home and os.path.realpath(lines[1].strip()) == os.path.realpath(home):
        return None
    return str(Path(lines[0].strip()).parent)


def root_for(start_path):
    """The project's main checkout for a session started in start_path, or None when it cannot be known.

    An existing dir maps as before (cached per path). A path that is gone maps to the repo of its nearest existing
    parent (a removed <repo>/.claude/worktrees/x gives <repo>), unless that repo is ~ itself; its cache entry is
    dropped. An empty path, or a gone path in no repo, gives None: never a silent $HOME.
    """
    if not start_path:
        return None
    if not os.path.isdir(start_path):
        _roots.pop(start_path, None)
        return _gone_root(start_path)
    has_git = os.path.exists(os.path.join(start_path, ".git"))
    hit = _roots.get(start_path)
    if hit is not None and hit[0] == has_git:
        return hit[1]
    root = _git_root(start_path)
    if root is None:
        return start_path
    _roots[start_path] = (has_git, root)
    return root


class FolderGone(RuntimeError):
    """The session's start path is gone and maps to no main checkout."""


def session_start(tmux, sess):
    """The session's start path (#{session_path}) as tmux reports it, possibly empty or gone."""
    return tmux("display", "-p", "-t", f"={sess}:", "#{session_path}").strip()


def session_root(tmux, sess):
    """Where the new lead starts: the project's main checkout, never a worktree (auto-cleanup may remove it).
    The claude pane's current path is not used: Claude Code follows the lead's cd. Raises FolderGone when the start
    path is gone and maps to no checkout: the caller refuses to respawn."""
    start = session_start(tmux, sess)
    root = root_for(start)
    if root is None:
        raise FolderGone(f"project folder is gone: {start}")
    return root
```

In `relay(...)`, move the root lookup above the wait. Replace:

```python
    if not wait_turn_end(tmux, pane, **wait):
        raise RuntimeError("the lead is still busy after the wait; not switching. Run tmux-ctl relay again when it is idle")
    root = session_root(tmux, sess)
```

with:

```python
    root = session_root(tmux, sess)   # FolderGone before the wait: nothing is respawned into a folder that is gone
    if not wait_turn_end(tmux, pane, **wait):
        raise RuntimeError("the lead is still busy after the wait; not switching. Run tmux-ctl relay again when it is idle")
```

In `restart_lead(...)`, replace `    root = os.path.realpath(session_root(tmux, sess))` with:

```python
    try:
        root = os.path.realpath(session_root(tmux, sess))
    except FolderGone as e:
        raise LeadRestartError(str(e)) from None
```

`main()` needs no change: its `except Exception` prints `relay failed: <message>` and returns 1, and its fallback
`session_root` call raises again and is caught, so the manual line has no `cd` (root unknown).

- [ ] **Step 4: Run GREEN.** `python3 -m unittest board.tests.test_relay board.tests.test_session_root_path` → `OK`. RED check for the mutations named in the test comments: for each one, apply it, see its test fail, then revert.

- [ ] **Step 5: Commit.** `git add board/relay.py board/tests/test_relay.py board/tests/test_session_root_path.py`, then `git commit -m "fix(relay): root_for maps a removed worktree to its checkout, never \$HOME; relay and lead-restart refuse a gone folder"`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/relay.py", "board/tests/test_relay.py", "board/tests/test_session_root_path.py"], "verifyCommand": "python3 -m unittest board.tests.test_relay board.tests.test_session_root_path", "acceptanceCriteria": ["removed worktree -> main checkout", "empty, gone non-git and gone-under-home-repo -> None", "existing dirs unchanged", "session_root raises FolderGone 'project folder is gone: <start_path>'", "relay refuses before wait/respawn; CLI exit 1 with 'relay failed: project folder is gone: …'", "restart_lead raises LeadRestartError with the message, no respawn"], "modelTier": "standard"}
```

---

### Task 2: Board callers: display `root_for(p) or p`, restart refuses, lead view survives

**Goal:** `build_state` and `label_targets` show `relay.root_for(p) or p` (display only), `lead_info` gives `root: ""` for a gone folder instead of dropping the lead view, and the board's `restart_orchestrator` action refuses a gone folder with `project folder is gone: <start_path>` and no respawn.

**Files:**
- Modify: `board/server.py` (`build_state` ~line 390, lead info ~line 540, `label_targets` ~line 669)
- Modify: `board/tests/test_session_root_path.py` (`BuildStateRootTest`, `LabelTargetsRootTest`)
- Modify: `board/tests/test_restart_orchestrator.py`

**Acceptance Criteria:**
- [ ] `build_state()` and `label_targets()` with start path `<repo>/gone` show `<repo>`; with `<non-git>/gone` show that path as given; with `""` show `""`.
- [ ] `_act({"action": "restart_orchestrator", ...})` on a session whose start path is gone and in no repo raises `RuntimeError("project folder is gone: <path>")` and sends no `respawn-pane` and no `new-window`.
- [ ] `board/tests/test_discord_wiring.py` `LeadInfosTest` passes unchanged (it mocks `relay.session_root`).

**Verify:** `python3 -m unittest board.tests.test_session_root_path board.tests.test_restart_orchestrator board.tests.test_discord_wiring board.tests.test_session_path` → `OK`

**Steps:**

- [ ] **Step 1: Rewrite the tests (RED).** In `board/tests/test_session_root_path.py`, replace `test_removed_or_empty_start_is_home` in `BuildStateRootTest` with:

```python
    def test_removed_start_maps_to_repo_gone_non_git_shows_as_given(self):   # mutation: drop `or start` -> None
        self.assertEqual(self.state(str(self.r.repo / "gone"))["path"], str(self.r.repo))
        gone = str(Path(self.home.name) / "gone")
        self.assertEqual(self.state(gone)["path"], gone)
        self.assertEqual(self.state("")["path"], "")
```

and the one in `LabelTargetsRootTest` with:

```python
    def test_removed_start_maps_to_repo_gone_non_git_shows_as_given(self):   # mutation: drop `or start` -> None
        self.assertEqual(self.targets(str(self.r.repo / "gone"))["path"], str(self.r.repo))
        gone = str(Path(self.home.name) / "gone")
        self.assertEqual(self.targets(gone)["path"], gone)
        self.assertEqual(self.targets("")["path"], "")
```

In `board/tests/test_restart_orchestrator.py`, add `from unittest import mock` after `import unittest`, and insert before `def test_web_session_rejected`:

```python
    def test_gone_folder_refuses_without_respawn(self):   # mutation: catch FolderGone and fall back to $HOME -> respawn-pane called
        fake = Fake([(1, "claude", False)], cmd="zsh")
        fake.session_path = self.elsewhere + "/gone"
        saved = (server.tmux, server.pane_text)
        server.tmux, server.pane_text = fake.tmux, (lambda target, lines=40: fake.rows)
        try:
            with mock.patch.dict(os.environ, {"HOME": self.elsewhere}), self.assertRaises(RuntimeError) as cm:
                server._act({"action": "restart_orchestrator", "session": "proj"})
        finally:
            server.tmux, server.pane_text = saved
        self.assertEqual(str(cm.exception), f"project folder is gone: {self.elsewhere}/gone")
        self.assertEqual(fake.find("respawn-pane"), [])
        self.assertEqual(fake.find("new-window"), [])
```

- [ ] **Step 2: Run RED.** Run the Verify command. `test_removed_start_maps_to_repo_gone_non_git_shows_as_given` fails (`None != '…/gone'`) in both classes, and `LeadInfosTest` still passes. `test_gone_folder_refuses_without_respawn` already passes after Task 1, because `restart_orchestrator` calls `relay.session_root`. Its mutation is to wrap that call in `try/except relay.FolderGone: root = os.environ["HOME"]`, which makes the test fail.

- [ ] **Step 3: Implement in `board/server.py`.** Three one-line replacements, plus one helper above `def build_state():`:

  - In `build_state`: `"path": relay.root_for(f[15])})` → `"path": relay.root_for(f[15]) or f[15]})`
  - In `label_targets`: `"path": relay.root_for(start), "windows"` → `"path": relay.root_for(start) or start, "windows"`
  - In the lead-info loop: `"root": str(relay.session_root(tmux, p) or "")` → `"root": _lead_root(p)`
  - Insert directly above `def build_state():`:

```python
def _lead_root(p):
    """The lead view's root: relay.session_root, or "" when the project folder is gone (shown, not raised)."""
    try:
        return str(relay.session_root(tmux, p))
    except relay.FolderGone:
        return ""


```

  `restart_orchestrator`, `session_path` and their callers need no change: `relay.FolderGone` is a `RuntimeError`, which `_act` already turns into the error toast.

- [ ] **Step 4: Run GREEN.** Run the Verify command → `OK`.

- [ ] **Step 5: Commit.** `git add board/server.py board/tests/test_session_root_path.py board/tests/test_restart_orchestrator.py`, then `git commit -m "fix(board): show a gone start path as given; restart refuses a gone project folder"`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/server.py", "board/tests/test_session_root_path.py", "board/tests/test_restart_orchestrator.py"], "verifyCommand": "python3 -m unittest board.tests.test_session_root_path board.tests.test_restart_orchestrator board.tests.test_discord_wiring board.tests.test_session_path", "acceptanceCriteria": ["build_state and label_targets: <repo>/gone -> <repo>, gone non-git as given, empty as empty", "restart_orchestrator refuses a gone folder with the message, no respawn-pane/new-window", "LeadInfosTest passes unchanged"], "modelTier": "mechanical"}
```

---

### Task 3: `restore.tmux_server_cwd`

**Goal:** `board/restore.py` gains `tmux_server_cwd(run=_run, tmux=None)`, which returns the exact warning text (Global Constraints) when the tmux server's cwd is gone, and `None` when it exists, when there is no server, when `lsof` fails, or on any error.

**Files:**
- Modify: `board/restore.py` (insert above `def restore_dir():`, ~line 37)
- Create: `board/tests/test_server_cwd.py`

**Acceptance Criteria:**
- [ ] With a stub runner whose `display` answers `4242|/tmp/tmux-1/sock` and whose lsof answers `n/gone/dir`, the result is the warning with `(/gone/dir)` and `tmux -S /tmp/tmux-1/sock kill-server`. The first call is `tmux + ["display", "-p", "#{pid}|#{socket_path}"]`, and the second is `[<lsof>, "-a", "-p", "4242", "-d", "cwd", "-Fn"]`.
- [ ] An existing cwd gives `None`; lsof exit 1 gives `None`; a failed `display` gives `None` with no lsof call; a raising runner gives `None`.

**Verify:** `python3 -m unittest board.tests.test_server_cwd` → `OK` (5 tests)

**Steps:**

- [ ] **Step 1: Write the test (RED).** Create `board/tests/test_server_cwd.py`:

```python
"""restore.tmux_server_cwd: the warning when the tmux server's own cwd is gone (spec restart-recovery §4)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import restore  # noqa: E402

T = ["tmux", "-L", "x"]
WARN = ("tmux server cwd is gone (/gone/dir): new panes start there; restart the tmux server from ~ "
        "(tmux -S /tmp/tmux-1/sock kill-server ends every session on it; reopen each project with agent-board dev)")


def runner(pid=(0, "4242|/tmp/tmux-1/sock\n"), lsof=(0, "p4242\nfcwd\nn/gone/dir\n")):
    calls = []

    def run(cmd):
        calls.append(cmd)
        return pid if cmd[:len(T)] == T else lsof
    return run, calls


class TmuxServerCwdTest(unittest.TestCase):
    def test_gone_cwd_gives_the_warning(self):
        run, calls = runner()
        self.assertEqual(restore.tmux_server_cwd(run=run, tmux=T), WARN)
        self.assertEqual(calls[0], T + ["display", "-p", "#{pid}|#{socket_path}"])
        self.assertEqual(calls[1][1:], ["-a", "-p", "4242", "-d", "cwd", "-Fn"])

    def test_existing_cwd_gives_none(self):   # mutation: drop the isdir check -> the warning is returned
        with tempfile.TemporaryDirectory() as d:
            run, _ = runner(lsof=(0, f"p4242\nfcwd\nn{d}\n"))
            self.assertIsNone(restore.tmux_server_cwd(run=run, tmux=T))

    def test_lsof_failure_gives_none(self):   # mutation: ignore lsof's exit code -> the n line is parsed, warning returned
        run, _ = runner(lsof=(1, "p4242\nfcwd\nn/gone/dir\n"))
        self.assertIsNone(restore.tmux_server_cwd(run=run, tmux=T))

    def test_no_server_gives_none_and_skips_lsof(self):   # mutation: drop the pid check -> lsof is called
        run, calls = runner(pid=(1, ""))
        self.assertIsNone(restore.tmux_server_cwd(run=run, tmux=T))
        self.assertEqual(len(calls), 1)

    def test_a_raising_runner_gives_none(self):   # mutation: drop the try/except -> OSError escapes
        def run(cmd):
            raise OSError("no tmux")
        self.assertIsNone(restore.tmux_server_cwd(run=run, tmux=T))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run RED.** `python3 -m unittest board.tests.test_server_cwd` → `AttributeError: module 'restore' has no attribute 'tmux_server_cwd'`.

- [ ] **Step 3: Implement.** In `board/restore.py`, insert directly above `def restore_dir():`:

```python
LSOF = "/usr/sbin/lsof"   # not on the LaunchAgent PATH either
CWD_GONE = ("tmux server cwd is gone ({cwd}): new panes start there; restart the tmux server from ~ "
            "(tmux -S {sock} kill-server ends every session on it; reopen each project with agent-board dev)")


def tmux_server_cwd(run=_run, tmux=None):
    """The warning line when the tmux server's own cwd is gone, else None (spec restart-recovery §4): tmux 3.8 starts
    new panes there and ignores -c. tmux is the server's command words (default paneclass.tmux_cmd()). No server,
    lsof missing or failing, or any error -> None."""
    try:
        words = list(tmux) if tmux is not None else paneclass.tmux_cmd()
        rc, out = run(words + ["display", "-p", "#{pid}|#{socket_path}"])
        pid, _, sock = (out or "").strip().partition("|")
        if rc != 0 or not pid.isdigit():
            return None
        rc, out = run([LSOF if os.path.exists(LSOF) else "lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"])
        if rc != 0:
            return None
        cwd = next((l[1:] for l in (out or "").splitlines() if l.startswith("n")), "")
        return CWD_GONE.format(cwd=cwd, sock=sock) if cwd and not os.path.isdir(cwd) else None
    except Exception:   # noqa: BLE001 -- detection only: a failure is no warning
        return None


```

- [ ] **Step 4: Run GREEN.** Run the Verify command → `OK`. Then run each mutation named in the test comments.

- [ ] **Step 5: Commit.** `git add board/restore.py board/tests/test_server_cwd.py`, then `git commit -m "feat(restore): tmux_server_cwd warns when the tmux server's cwd is gone"`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/restore.py", "board/tests/test_server_cwd.py"], "verifyCommand": "python3 -m unittest board.tests.test_server_cwd", "acceptanceCriteria": ["gone cwd -> exact warning naming cwd and socket; display then lsof argv as specified", "existing cwd, lsof rc 1, failed display (no lsof call), raising runner -> None"], "modelTier": "mechanical"}
```

---

### Task 4: Board banner: `server_warning` in `build_state`, checked at most every 60 s

**Goal:** `build_state()` carries `"server_warning"` (the Task 3 warning or `""`), recomputed at most once per 60 s and never raising, and the board page shows it in a red banner in the header that hides when it is empty.

**Files:**
- Modify: `board/server.py` (import line ~35, above `def build_state():`, `build_state` return ~line 421)
- Modify: `board/index.html` (CSS ~line 76, header ~line 349, `render()` ~line 725)
- Create: `board/tests/test_server_warning.py`
- Create: `board/tests/test_server_warn_ui.py`

**Acceptance Criteria:**
- [ ] `server_warning(now=1000)`, then `(now=1059)` and `(now=1060)`, calls `restore.tmux_server_cwd` twice and returns the cached value at 1059.
- [ ] `None` from the check, or an exception, gives `""`.
- [ ] `build_state()["server_warning"]` is the value of `server_warning()`.
- [ ] `index.html` has `<div class="server-warn" id="server-warn" role="alert" hidden>`. `render()` calls `renderServerWarn()`. Under node, `renderServerWarn` shows the text with `hidden=false` for a warning and `hidden=true` with empty text for `""` and for `data = null`.

**Verify:** `python3 -m unittest board.tests.test_server_warning board.tests.test_server_warn_ui board.tests.test_activity` → `OK`

**Steps:**

- [ ] **Step 1: Write the tests (RED).** Create `board/tests/test_server_warning.py`:

```python
"""server.server_warning: the board's copy of restore.tmux_server_cwd, checked at most every 60 s and carried by
build_state as server_warning (spec restart-recovery §4)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")  # server.py reads it at import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

WARN = "tmux server cwd is gone (/gone/dir): new panes start there"


class ServerWarningTest(unittest.TestCase):
    def setUp(self):
        server._cwd_check.update(at=None, msg="")

    def test_checked_at_most_every_60s(self):   # mutation: drop the age check -> called three times
        with mock.patch.object(server.restore, "tmux_server_cwd", side_effect=["w1", "w2"]) as m:
            self.assertEqual(server.server_warning(now=1000.0), "w1")
            self.assertEqual(server.server_warning(now=1059.0), "w1")
            self.assertEqual(server.server_warning(now=1060.0), "w2")
        self.assertEqual(m.call_count, 2)

    def test_none_and_errors_are_empty(self):
        with mock.patch.object(server.restore, "tmux_server_cwd", return_value=None):
            self.assertEqual(server.server_warning(now=1.0), "")
        server._cwd_check.update(at=None, msg="")
        with mock.patch.object(server.restore, "tmux_server_cwd", side_effect=RuntimeError("boom")):
            self.assertEqual(server.server_warning(now=1.0), "")

    def test_build_state_carries_the_warning(self):   # mutation: drop the key from build_state -> KeyError
        with mock.patch.object(server, "tmux", return_value=""), \
             mock.patch.object(server, "cached_worktrees", return_value=[]), \
             mock.patch.object(server, "server_warning", return_value=WARN):
            self.assertEqual(server.build_state()["server_warning"], WARN)


if __name__ == "__main__":
    unittest.main()
```

Create `board/tests/test_server_warn_ui.py`:

```python
"""The board's tmux server cwd banner: renderServerWarn shows data.server_warning and hides itself when it is empty.
Runs the page's own function under node with a stubbed $ (the harness style of test_ideas_dropped_ui.py)."""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

BOARD = Path(os.environ.get("BOARD_DIR") or Path(__file__).resolve().parent.parent)


@unittest.skipUnless(shutil.which("node"), "node needed to run the page's renderServerWarn")
class ServerWarnUiTest(unittest.TestCase):
    def setUp(self):
        self.html = (BOARD / "index.html").read_text()

    def test_banner_element_and_render_call(self):   # mutation: drop renderServerWarn() from render() -> fails
        self.assertIn('id="server-warn"', self.html)
        self.assertRegex(self.html, r"function render\(\) \{[^\n]*\n[^\n]*renderServerWarn\(\)")

    def test_shows_then_hides(self):   # mutation: drop `b.hidden = !w` -> the second state stays visible
        fn = re.search(r"^function renderServerWarn\(\) \{.*?$", self.html, re.M)
        self.assertIsNotNone(fn, "renderServerWarn not found in index.html")
        js = fn.group(0) + """
const B = {textContent: "", hidden: true}; const $ = () => B; let data;
const out = [];
data = {server_warning: "tmux server cwd is gone (/x): new panes start there"}; renderServerWarn(); out.push([B.textContent, B.hidden]);
data = {server_warning: ""}; renderServerWarn(); out.push([B.textContent, B.hidden]);
data = null; renderServerWarn(); out.push([B.textContent, B.hidden]);
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(),
                         '[["tmux server cwd is gone (/x): new panes start there",false],["",true],["",true]]')


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run RED.** Run the Verify command. It fails with `AttributeError: … has no attribute '_cwd_check'` (and `server_warning`), and the UI tests fail with `renderServerWarn not found`.

- [ ] **Step 3: Implement the server side.** In `board/server.py`:
  - Add `restore` to the module import line: `…, planview, relay, usage, worktree_safety  # noqa: E402` → `…, planview, relay, restore, usage, worktree_safety  # noqa: E402`.
  - Insert directly above `def build_state():` (below Task 2's `_lead_root`):

```python
CWD_EVERY = 60   # seconds between checks of the tmux server's own cwd (spec restart-recovery §4)
_cwd_check = {"at": None, "msg": ""}


def server_warning(now=None):
    """restore.tmux_server_cwd's warning, "" when none; re-checked at most every CWD_EVERY seconds. Never raises."""
    now = time.monotonic() if now is None else now
    if _cwd_check["at"] is None or now - _cwd_check["at"] >= CWD_EVERY:
        try:
            msg = restore.tmux_server_cwd(tmux=TMUX) or ""
        except Exception:   # noqa: BLE001 -- a failed check is no warning; it never breaks the state poll
            msg = ""
        _cwd_check.update(at=now, msg=msg)
    return _cwd_check["msg"]


```

  - Replace the `build_state` return line
    `    return {"sessions": out, "ttyd": {"port": TTYD_PORT, "base": f"/{TOKEN}-tty"}, "last_sweep": last_sweep()}` with:

```python
    return {"sessions": out, "ttyd": {"port": TTYD_PORT, "base": f"/{TOKEN}-tty"}, "last_sweep": last_sweep(),
            "server_warning": server_warning()}
```

- [ ] **Step 4: Implement the page.** In `board/index.html`:
  - After the CSS line `.offline-banner[hidden] { display: none; }` add:

```css
.server-warn { background: var(--red-soft); color: var(--red); border: 1px solid var(--red); border-radius: 6px; padding: 2px 10px; font-size: 12px; }
.server-warn[hidden] { display: none; }
```

  - After `<div class="offline-banner" id="offline-banner" role="status" hidden>Board server unreachable — retrying</div>` add:

```html
    <div class="server-warn" id="server-warn" role="alert" hidden></div>
```

  - Replace the end of `render()` and the line after it:

```js
renderCards(); renderWorktrees(); }

function setOffline(off) {
```

    with:

```js
renderCards(); renderWorktrees(); renderServerWarn(); }
function renderServerWarn() { const w = (data && data.server_warning) || "", b = $("#server-warn"); b.textContent = w; b.hidden = !w; }

function setOffline(off) {
```

  The state endpoint's ETag already covers the whole JSON, so a change in `server_warning` reaches the page on the next poll.

- [ ] **Step 5: Run GREEN.** Run the Verify command → `OK`. Then run the mutations named in the test comments.

- [ ] **Step 6: Commit.** `git add board/server.py board/index.html board/tests/test_server_warning.py board/tests/test_server_warn_ui.py`, then `git commit -m "feat(board): banner when the tmux server's cwd is gone"`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/server.py", "board/index.html", "board/tests/test_server_warning.py", "board/tests/test_server_warn_ui.py"], "verifyCommand": "python3 -m unittest board.tests.test_server_warning board.tests.test_server_warn_ui board.tests.test_activity", "acceptanceCriteria": ["server_warning checked at most every 60 s (2 calls for 1000/1059/1060)", "None or exception -> ''", "build_state carries server_warning", "index.html banner element, render() calls renderServerWarn, node run shows then hides"], "modelTier": "standard"}
```

---

### Task 5: `tmux-ctl list` warns first; `dev` keeps the server in `$HOME`

**Goal:** `tmux-ctl list` prints the exact warning (Global Constraints) as its first line when its tmux server's cwd is gone, and nothing extra otherwise. A zsh test also pins that a server started by `dev`, typed in a folder that is later removed, has `$HOME` as its cwd.

**Files:**
- Modify: `bin/tmux-ctl` (the `list)` branch, ~line 374, before the first `list_session` call)
- Create: `tools/tests/test_server_cwd.zsh`

**Acceptance Criteria:**
- [ ] Scratch server started with `cd <dir> && tmux -L <sock> -f /dev/null new-session …`: while `<dir>` exists, `tmux-ctl list` prints no `tmux server cwd is gone` line. After `rmdir <dir>`, its first line is the warning naming `<dir>` and the server's `#{socket_path}`, and the window rows still follow.
- [ ] `bin/dev <proj>` typed in a dir that is then removed (fresh scratch server through `TMUX_DASH_TMUX_ARGS="-L <sock> -f /dev/null"`, `HOME=<tmp>/home`) leaves the server cwd at `<tmp>/home`. This check passes from the start (prevention shipped in abf11a9); its mutation is to remove `builtin cd -q -- "$HOME"` in `bin/_tc_bins.zsh` `tc_tmux`, which makes it fail.
- [ ] The file is picked up by `tools/tests/all.zsh` (glob `tools/tests/test_*.zsh`; `zsh tools/tests/all.zsh --list | grep test_server_cwd.zsh`).

**Verify:** `zsh tools/tests/test_server_cwd.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the test (RED).** Create `tools/tests/test_server_cwd.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
# The tmux server's own cwd (spec restart-recovery §4). tmux 3.8 starts new panes in a gone server cwd and ignores -c,
# so dev starts the server from $HOME, and tmux-ctl list warns, as its first line, when the server cwd is gone.
R="${0:A:h:h:h}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/tcsrv.XXXXXX")"; tmp="${tmp:A}"
dsock="tcsrvd$$"; lsock="tcsrvl$$"
TB="${TC_TMUX:-$HOME/.local/bin/tmux}"; [[ -x "$TB" ]] || TB="$(command -v tmux)"
trap '"$TB" -L "$dsock" kill-server 2>/dev/null; "$TB" -L "$lsock" kill-server 2>/dev/null; rm -rf "$tmp"' EXIT INT TERM
mkdir -p "$tmp/home" "$tmp/devstart" "$tmp/proj" "$tmp/start" "$tmp/target" "$tmp/state"
srv_cwd() { lsof -a -p "$("$TB" -L "$1" display -p '#{pid}')" -d cwd -Fn | sed -n 's/^n//p' }

# 1. dev typed in a directory that is later removed: the server it starts sits in $HOME
( cd "$tmp/devstart" && unset TMUX TMUX_PANE && HOME="$tmp/home" ZDOTDIR="$tmp/home" TC_STATE="$tmp/state" TC_TMUX="$TB" \
    TMUX_DASH_TMUX_ARGS="-L $dsock -f /dev/null" TC_LAYOUT=/usr/bin/true DEV_NO_ATTACH=1 DEV_NO_LEAD=1 \
    zsh "$R/bin/dev" "$tmp/proj" >/dev/null 2>&1 )
rmdir "$tmp/devstart"
check "dev started the server" "$TB" -L "$dsock" has-session -t "=proj"
check "dev's server cwd is \$HOME, not the directory dev was typed in" test "$(srv_cwd "$dsock")" = "$tmp/home"

# 2. a server started straight from a directory (not through tc_tmux), then that directory is removed
( cd "$tmp/start" && "$TB" -L "$lsock" -f /dev/null new-session -d -s cw -n claude -c "$tmp/target" )
export TMUX="$("$TB" -L "$lsock" display -p '#{socket_path}'),$$,0"
export TMUX_PANE="$("$TB" -L "$lsock" display -p -t '=cw:claude' '#{pane_id}')" TC_STATE="$tmp/state"
unset TMUX_DASH_TMUX_ARGS TC_SESSION
check "no warning while the server cwd exists" sh -c "! zsh '$R/bin/tmux-ctl' list 2>&1 | grep -q 'tmux server cwd is gone'"
rmdir "$tmp/start"
lsp="$("$TB" -L "$lsock" display -p '#{socket_path}')"
check "first line warns that the server cwd is gone, naming its socket" test "$(zsh "$R/bin/tmux-ctl" list 2>&1 | head -1)" = "tmux server cwd is gone ($tmp/start): new panes start there; restart the tmux server from ~ (tmux -S $lsp kill-server ends every session on it; reopen each project with agent-board dev)"
check "the window listing still follows" sh -c "zsh '$R/bin/tmux-ctl' list 2>&1 | grep -q '  claude  '"
tt_done
```

- [ ] **Step 2: Run RED.** `zsh tools/tests/test_server_cwd.zsh` → exactly one `FAIL - first line warns that the server cwd is gone, naming its socket`, then `1 FAILED` (planning run, 2026-11-21).

- [ ] **Step 3: Implement.** In `bin/tmux-ctl`, inside the `list)` branch, replace

```zsh
    list_session
    if t has-session -t "=$BG" 2>/dev/null; then
```

with:

```zsh
    # a tmux server whose own cwd is gone starts every new pane there and ignores -c (tmux 3.8): say so first
    IFS='|' read -r srv_pid srv_sock <<< "$(t display -p '#{pid}|#{socket_path}' 2>/dev/null)"
    lsof_bin=/usr/sbin/lsof; [[ -x "$lsof_bin" ]] || lsof_bin="${commands[lsof]:-}"
    if [[ "$srv_pid" == <-> && -n "$lsof_bin" ]]; then
      srv_cwd="$("$lsof_bin" -a -p "$srv_pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
      [[ -n "$srv_cwd" && ! -d "$srv_cwd" ]] && print -r -- "tmux server cwd is gone ($srv_cwd): new panes start there; restart the tmux server from ~ (tmux -S $srv_sock kill-server ends every session on it; reopen each project with agent-board dev)"
    fi
    list_session
    if t has-session -t "=$BG" 2>/dev/null; then
```

- [ ] **Step 4: Run GREEN.** `zsh tools/tests/test_server_cwd.zsh` → `ALL PASS`. Mutation: change `[[ -n "$srv_cwd" && ! -d "$srv_cwd" ]]` to `[[ -n "$srv_cwd" ]]`, which makes exactly one check fail ("no warning while the server cwd exists"), then `1 FAILED`. Then revert. Also `zsh tools/tests/test_tc_tmux_cwd.zsh` → `ALL PASS`.

- [ ] **Step 5: Commit.** `git add bin/tmux-ctl tools/tests/test_server_cwd.zsh`, then `git commit -m "feat(tmux-ctl): list warns first when the tmux server's cwd is gone"`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_server_cwd.zsh"], "verifyCommand": "zsh tools/tests/test_server_cwd.zsh", "acceptanceCriteria": ["no warning while the server cwd exists", "after rmdir: first line is the exact warning naming the dir and socket; window rows follow", "dev from a removed dir leaves the server cwd at $HOME", "picked up by all.zsh --list"], "modelTier": "mechanical"}
```

---

### Task 6: Docs: the `(cd ~ && …)` auto-attach snippet and the warning

**Goal:** `docs/INSTALL.md` documents an optional auto-attach snippet in the `(cd ~ && tmux -L agent-board … new-session -A -s main)` form and has a Troubleshooting row for the warning, and `docs/CUSTOMIZATION.md`'s `TC_TERMINAL_SESSION` example uses the same form.

**Files:**
- Modify: `docs/INSTALL.md` (`### Things to know` bullet list ~line 111; Troubleshooting table ~line 350)
- Modify: `docs/CUSTOMIZATION.md` (line 50, `TC_TERMINAL_SESSION` row)

**Acceptance Criteria:**
- [ ] `grep -c '(cd ~ && tmux -L agent-board' docs/INSTALL.md docs/CUSTOMIZATION.md` → 1 for each file.
- [ ] `grep -c 'tmux server cwd is gone' docs/INSTALL.md` → 1 (the Troubleshooting row).
- [ ] No other line of either file changes (`git diff --stat` shows only these two files, with few lines).

**Verify:** `grep -c '(cd ~ && tmux -L agent-board' docs/INSTALL.md docs/CUSTOMIZATION.md; grep -c 'tmux server cwd is gone' docs/INSTALL.md` → `docs/INSTALL.md:1`, `docs/CUSTOMIZATION.md:1`, `1`

**Steps:**

- [ ] **Step 1: INSTALL, Things to know.** Append this bullet after the `- **Teammates.** …` bullet:

````markdown
- **Opening agent-board in every new terminal (optional).** Add this to `~/.zshrc` (use your clone's path for the config). The `cd ~` matters: a tmux server keeps the folder it was started in for life, and once that folder is deleted (a merged worktree), tmux starts every new pane there and ignores `-c`.

  ```zsh
  if [[ -o interactive && -z "$TMUX" && -t 1 ]] && command -v tmux >/dev/null; then
    (cd ~ && tmux -L agent-board -f ~/agent-board/config/tmux.conf new-session -A -s main)
  fi
  ```
````

- [ ] **Step 2: INSTALL, Troubleshooting.** Add this row after the `tmux-ctl: not inside tmux` row:

```markdown
| `tmux-ctl list` (or a red banner on the board) says `tmux server cwd is gone (…)` | the tmux server was started from a folder that was later deleted, and new panes start there whatever `-c` says. Close your projects, run the `tmux -S <socket> kill-server` the line names, then reopen each project with `agent-board dev`, which starts the server from `~`. Use the `(cd ~ && …)` form in `~/.zshrc` (Things to know). |
```

- [ ] **Step 3: CUSTOMIZATION.** On line 50, replace `(e.g. \`new-session -A -s main\` in \`~/.zshrc\`)` with `(e.g. \`(cd ~ && tmux -L agent-board -f … new-session -A -s main)\` in \`~/.zshrc\`, see INSTALL's Things to know)`.

- [ ] **Step 4: Verify.** Run the Verify command and check the counts.

- [ ] **Step 5: Commit.** `git add docs/INSTALL.md docs/CUSTOMIZATION.md`, then `git commit -m "docs(install): start the auto-attach server from ~; the cwd warning"`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["docs/INSTALL.md", "docs/CUSTOMIZATION.md"], "verifyCommand": "grep -c '(cd ~ && tmux -L agent-board' docs/INSTALL.md docs/CUSTOMIZATION.md; grep -c 'tmux server cwd is gone' docs/INSTALL.md", "acceptanceCriteria": ["INSTALL and CUSTOMIZATION each carry the (cd ~ && tmux -L agent-board form once", "INSTALL Troubleshooting has the warning row", "no other lines change"], "modelTier": "mechanical"}
```

---

### Task 7: Full suite and read-only real-state checks

**Goal:** Every suite passes, and the new code behaves as before on the user's real tmux server and sessions, read-only.

**Files:**
- Test only (no file changes; fixes go back to the owning task's files)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh; echo rc=$?` → the runner's `ALL PASS` verdict line with rc 0 or 4 (4 = over the time budget, accepted on this machine), and `zsh/test_server_cwd.zsh` in `--list`.
- [ ] Real server, read-only: `python3 -c 'import sys; sys.path.insert(0, "board"); import restore; print(repr(restore.tmux_server_cwd()))'` run outside tmux (agent-board's own server) → `None` (its cwd `/Users/francisco.ruiz` exists, probed 2026-11-21). If it prints a warning, record it: that is a real finding for the user, not a test failure.
- [ ] Real sessions, read-only. This snippet prints `checked N sessions, M None` with N >= 1, and M = 0 (every live start path existed on 2026-11-21). For each of the N sessions, the new `root_for` equals the old behaviour for an existing dir:

```zsh
python3 - <<'EOF'
import subprocess, sys
sys.path.insert(0, "board")
import paneclass, relay
rows = subprocess.run(paneclass.tmux_cmd() + ["list-sessions", "-F", "#{session_name}\t#{session_path}"], capture_output=True, text=True).stdout.splitlines()
res = [(n, p, relay.root_for(p)) for n, _, p in (r.partition("\t") for r in rows)]
for n, p, r in res: print(n, p, "->", r)
print(f"checked {len(res)} sessions, {sum(1 for x in res if x[2] is None)} None")
EOF
```

- [ ] Inside a live project pane, `zsh bin/tmux-ctl list | head -1` prints a window row (`1  claude  [...]`), not a warning.
- [ ] Afterwards `git status --porcelain` in the main checkout shows no change made by these checks.

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → the runner's verdict line `ALL PASS …` and `rc=0` or `rc=4`

**Steps:**

- [ ] Run each criterion's command through `tmux-ctl run -t 1200 tests "<cmd>"` and capture the output in the ledger. On any failure, use `superpowers-extended-cc:systematic-debugging`, fix in the owning task's files, re-run that task's Verify, then this one.

```json:metadata
{"files": [], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["all.zsh ALL PASS rc 0 or 4, test_server_cwd.zsh listed", "tmux_server_cwd() on the real server -> None (or a recorded real warning)", "root_for over every live session: N>=1 checked, 0 None", "tmux-ctl list first line is a window row on the real server", "main checkout unchanged by the checks"], "modelTier": "standard"}
```

---

### Task 8: User gate: `~/.zshrc` starts the server from `~`

**Goal:** The user changes `~/.zshrc` line 22 to `(cd ~ && tmux -L agent-board -f "$HOME/agent-board/config/tmux.conf" new-session -A -s main)`. After the next start of the agent-board tmux server from a terminal, its cwd is `$HOME` (`lsof -a -p <server pid> -d cwd -Fn` → `n$HOME`).

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Test only (the user edits `~/.zshrc`; the plan never edits it, per spec §4)

**Acceptance Criteria:**
- [ ] The lead tells the user the one-line change (current line 22, read 2026-11-21: `  tmux -L agent-board -f "$HOME/agent-board/config/tmux.conf" new-session -A -s main`; new line: `  (cd ~ && tmux -L agent-board -f "$HOME/agent-board/config/tmux.conf" new-session -A -s main)`), and the user applies it.
- [ ] `grep -n 'new-session -A -s main' ~/.zshrc` prints exactly one line, and it contains `(cd ~ && tmux -L agent-board`.
- [ ] After the next server start from a terminal (the next reboot, or the user's own restart), `lsof -a -p "$(~/.local/bin/tmux -L agent-board display -p '#{pid}')" -d cwd -Fn | sed -n 's/^n//p'` prints the user's home directory.
- [ ] On the board, no red `tmux server cwd is gone` banner shows, and `zsh bin/tmux-ctl list | head -1` in a project pane is a window row.

**Verify:** `grep -n 'new-session -A -s main' ~/.zshrc; lsof -a -p "$(~/.local/bin/tmux -L agent-board display -p '#{pid}')" -d cwd -Fn | sed -n 's/^n//p'` → one line containing `(cd ~ && tmux -L agent-board`, then the user's home directory

```json:metadata
{"files": [], "verifyCommand": "grep -n 'new-session -A -s main' ~/.zshrc; lsof -a -p \"$(~/.local/bin/tmux -L agent-board display -p '#{pid}')\" -d cwd -Fn | sed -n 's/^n//p'", "acceptanceCriteria": ["the lead gave the user the one-line ~/.zshrc change and the user applied it", "~/.zshrc has exactly one new-session -A -s main line, in the (cd ~ && tmux -L agent-board form", "after the next server start its lsof cwd is the user's home", "no cwd banner on the board; tmux-ctl list first line is a window row"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```

---

## Execution handoff

Run with `superpowers-extended-cc:subagent-driven-development` (together with `subagent-driven-development-extras`): the lead calls the Skill tool with it when this spec's run begins, and asks nothing about the execution method. Tasks 1 → 2 and 3 → 4 run in order, since each pair edits the same files. Tasks 5 and 6 are independent of the rest. Task 7 runs after 1-6, and Task 8 runs after 7.
