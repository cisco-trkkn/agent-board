# Mod: agent status from events — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code mod writes each session's busy / ready / needs-you state to a per-session file, and the board reads that file before falling back to pane-text scraping.

**Architecture:** `claude/plugin/mods/agent-status.js` (registered through `claude/plugin/hooks/hooks.json` `"modules"`) writes `<state dir>/agent-status/<session_id>.json`. `board/paneclass.py` gains `mod_states()` (one directory listing per board poll) and an optional `mod` argument to `classify`; `server.build_state`, the restart check and `pane_status` pass it.

**Tech Stack:** Claude Code mods (ES module, `$` API, `claude plugin test` with `claude-code/testing`), Python 3 unittest, zsh test harness.

**Spec:** `docs/superpowers/specs/2026-11-05-mod-agent-status-design.md`

## Global Constraints

- Status file: `<state dir>/agent-status/<session_id>.json` holding `{"session_id", "pane", "state", "since", "updatedAt"}`; `pane` is `$TMUX_PANE` or `null`; `state` ∈ `ready | busy | needs-you`; times are epoch seconds.
- State dir rule = `tc_env.state_dir()`: `$TC_STATE`, else `${TMPDIR:-/tmp}` with trailing `/` stripped + `/tmux-ctl-<uid>` (probe 2026-11-05: live sessions have no `TC_STATE`; `$TMPDIR/tmux-ctl-503` exists and is what the board uses).
- Transitions (spec): `ready` on `session.start` and `turn.complete`; `busy` on `turn.start`; `needs-you` while `tool.call` for `AskUserQuestion` is inside `next()`, back to `busy` after; `needs-you` when `tool.check` decides `ask`, back to `busy` when that tool's `tool.call` starts, `ready` at `turn.complete`; heartbeat every 15000 ms rewrites `updatedAt` only; `session.end` deletes the file. Every handler wrapped: an error never blocks a tool or a turn.
- Writes: `<file>.tmp` then rename if `$.fs` has one, else direct write. One writer per file; `$.store` is not used.
- Board: a file counts only if its `pane` equals the pane id, `state` is known and `updatedAt` is under 45 s old; map `busy → working`, `needs-you → waiting`, `ready → ready`; otherwise pane-text classification as today. One directory listing per board poll. No board UI change.
- Scratch tmux servers start with `-f /dev/null`; tests use a temp `TC_STATE`; nothing writes into the live state dir.
- Targeted tests only (user rule): `python3 -m unittest board.tests.test_paneclass` style single files, `claude plugin test claude/plugin/mods`, `zsh tools/tests/test_plugin.zsh`. Never the full suites.
- Commits: conventional with scope; end with the attribution trailer your harness specifies.

**User decisions (already made):**
- A context where mods do not load keeps the scraping fallback; the spec fails only if mods load nowhere (record `failed — mods do not load`).
- Queue mode integration for this branch: merge to main locally.

**Rulings at plan time:**
- Ruling: state dir follows `tc_env.state_dir()` (`$TMPDIR/tmux-ctl-<uid>` fallback), not the spec's "else `~/.local/state/agent-board`" — the spec also says "as `tc_env.state_dir()` resolves it", and the board must read where the mod writes — costs a moved directory if the user meant the XDG path.

---

### Task 1: Spike — where mods load

**Goal:** A written record, from real runs, of which session kinds load the agent-board plugin's mod, whether `"modules"` coexists with the classic hooks in `hooks.json`, and the exact `$` API calls the mod will use.

**Files:**
- Create: `claude/plugin/mods/agent-status.js` (spike version: on `session.start`, write `{"session_id", "pane", "env_ok"}` to `<state dir>/agent-status/<session_id>.json`)
- Modify: `claude/plugin/hooks/hooks.json` (add `"modules": ["./mods/agent-status.js"]` in whatever position the docs say)
- Create: `docs/superpowers/notes/2026-11-05-mods-spike.md`

**Constraints:** read the mods docs first (https://code.claude.com/docs/en/plugins/mods/ — overview, interface, reference, events, api). Every run happens in a scratch tmux server (`~/.local/bin/tmux -L mods-spike -f /dev/null`) with a temp `TC_STATE`, launching `claude` with `--plugin-dir <worktree>/claude/plugin` (the worker launch line in `bin/tmux-ctl:422` and `ab_claude_args` in `bin/_ab_claude.zsh` show the real argv). Kill the scratch server and every claude it started when done; check with `ps`. Keep each real session to one trivial prompt.

**Acceptance Criteria:**
- [ ] The notes file has a table with one row per context: (a) interactive session launched like the `dev` lead, (b) a session launched like a `tmux-ctl agent` worker (`-w <name> -n <name>`), (c) a teammate spawned by an interactive lead with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, (d) `claude --bg`, (e) `claude -p`; each row: loaded yes/no, the evidence (the file's path and contents, or its absence), `TMUX_PANE` value seen.
- [ ] The notes say whether `hooks.json` with both `"hooks"` and `"modules"` loads both (a classic hook still fires — e.g. `context-inject` output present — and the mod's file appears), and `claude plugin validate claude/plugin` output is quoted.
- [ ] The notes list, each with a doc URL or a probe output: how the mod reads env vars (`TMUX_PANE`, `TC_STATE`, `TMPDIR`) and the uid; the `$.fs` calls for mkdir, write, rename (or its absence), delete; the payload fields for `session_id`, the tool name in `tool.call` / `tool.check`, and the `tool.check` decision value for "ask"; how `claude plugin test` tests import and drive a mod (`claude-code/testing`).
- [ ] If no context loads the mod: report BLOCKED with the evidence (the queue then fails this spec).

**Verify:** `grep -c '^| (' docs/superpowers/notes/2026-11-05-mods-spike.md` → `5`

```json:metadata
{"files": ["claude/plugin/mods/agent-status.js", "claude/plugin/hooks/hooks.json", "docs/superpowers/notes/2026-11-05-mods-spike.md"], "verifyCommand": "grep -c '^| (' docs/superpowers/notes/2026-11-05-mods-spike.md", "acceptanceCriteria": ["table row per context a-e with loaded yes/no, evidence, TMUX_PANE", "hooks+modules coexistence recorded with plugin validate output", "API facts listed with doc URL or probe output", "BLOCKED if no context loads"], "modelTier": "standard"}
```

---

### Task 2: The agent-status mod and its tests

**Goal:** `claude/plugin/mods/agent-status.js` implements every transition in Global Constraints, tested with `claude plugin test`, using the API facts from `docs/superpowers/notes/2026-11-05-mods-spike.md`.

**Files:**
- Modify: `claude/plugin/mods/agent-status.js` (replace the spike body)
- Create: `claude/plugin/mods/agent-status.test.ts`
- Modify: `claude/plugin/.claude-plugin/plugin.json` (description names the agent-status mod)
- Modify: `tools/tests/test_plugin.zsh` (checks below)

**Acceptance Criteria:**
- [ ] Tests, each seen failing first, for: `session.start` → `ready` file with all five keys and `pane` from `TMUX_PANE` (`null` when unset); `turn.start` → `busy`; `AskUserQuestion` `tool.call` → `needs-you` during `next()`, `busy` after; `tool.check` "ask" → `needs-you`, then that tool's `tool.call` → `busy`; `tool.check` "ask" then `turn.complete` → `ready`; `since` changes only when `state` changes; heartbeat rewrites `updatedAt` only; `session.end` deletes the file; a throwing `$.fs` write does not propagate (the hook's `next` result is still returned).
- [ ] The state dir rule matches `tc_env.state_dir()` (test: `TC_STATE` set → `<TC_STATE>/agent-status`; unset with `TMPDIR=/x/` → `/x/tmux-ctl-<uid>/agent-status`).
- [ ] `test_plugin.zsh` gains: "hooks.json registers the agent-status mod" (the `modules` entry names `./mods/agent-status.js`) and "plugin.json description names agent-status"; the existing "all four hooks" check still passes (adapt its loop only if the `modules` key sits inside `"hooks"`).
- [ ] `claude plugin test claude/plugin/mods; echo rc=$?` → every test passes, `rc=0`; `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`.

**Verify:** `claude plugin test claude/plugin/mods; echo rc=$?` → `rc=0`

```json:metadata
{"files": ["claude/plugin/mods/agent-status.js", "claude/plugin/mods/agent-status.test.ts", "claude/plugin/.claude-plugin/plugin.json", "tools/tests/test_plugin.zsh"], "verifyCommand": "claude plugin test claude/plugin/mods; echo rc=$?", "acceptanceCriteria": ["each transition tested RED then GREEN", "state dir rule matches tc_env.state_dir", "test_plugin gains modules and description checks, ALL PASS", "claude plugin test rc=0"], "modelTier": "standard"}
```

---

### Task 3: Board reads the status files first

**Goal:** `paneclass.classify` uses a fresh mod state for a claude pane, and `server.build_state`, the server's restart check and `paneclass.pane_status` pass it, with one directory listing per call.

**Files:**
- Modify: `board/paneclass.py`
- Modify: `board/server.py:319` and `board/server.py:864`
- Test: `board/tests/test_paneclass.py` (new class `ModStatesTest`)

**Acceptance Criteria:**
- [ ] The seven new tests fail before the change and pass after.
- [ ] `python3 -m unittest discover -s board/tests -p test_paneclass.py; echo rc=$?` → `OK`, `rc=0`.

**Verify:** `python3 -m unittest discover -s board/tests -p test_paneclass.py; echo rc=$?` → `OK`, `rc=0`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to `board/tests/test_paneclass.py` (it already imports `os`, `sys`, `unittest`, `Path`, `paneclass`; add `import json`, `import tempfile`, `import time` at the top if missing):

```python
class ModStatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = os.environ.get("TC_STATE")
        os.environ["TC_STATE"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("TC_STATE") if self.old is None else os.environ.__setitem__("TC_STATE", self.old))
        self.dir = Path(self.tmp.name) / "agent-status"
        self.dir.mkdir()
        self.now = 1_800_000_000.0

    def put(self, name, **rec):
        (self.dir / name).write_text(rec.pop("raw") if "raw" in rec else json.dumps(rec))

    def test_fresh_file_maps_state_for_its_pane(self):
        self.put("s1.json", session_id="s1", pane="%1", state="busy", since=self.now - 5, updatedAt=self.now - 10)
        self.put("s2.json", session_id="s2", pane="%2", state="needs-you", since=self.now, updatedAt=self.now)
        self.put("s3.json", session_id="s3", pane="%3", state="ready", since=self.now, updatedAt=self.now)
        self.assertEqual(paneclass.mod_states(now=self.now), {"%1": "working", "%2": "waiting", "%3": "ready"})

    def test_stale_file_is_ignored(self):  # mutation: drop the 45 s check -> this fails
        self.put("s1.json", session_id="s1", pane="%1", state="busy", since=self.now, updatedAt=self.now - 45)
        self.assertEqual(paneclass.mod_states(now=self.now), {})

    def test_partial_unknown_and_paneless_files_are_ignored(self):  # mutation: drop the except / state check -> fails
        self.put("bad.json", raw='{"session_id": "s1", "pane": "%1", "sta')
        self.put("odd.json", session_id="s2", pane="%2", state="thinking", since=self.now, updatedAt=self.now)
        self.put("nopane.json", session_id="s3", pane=None, state="busy", since=self.now, updatedAt=self.now)
        self.put("s4.json.tmp", session_id="s4", pane="%4", state="busy", since=self.now, updatedAt=self.now)
        self.assertEqual(paneclass.mod_states(now=self.now), {})

    def test_newest_file_wins_for_one_pane(self):  # mutation: keep the first file seen -> fails for one listing order
        self.put("old.json", session_id="old", pane="%1", state="busy", since=self.now, updatedAt=self.now - 20)
        self.put("new.json", session_id="new", pane="%1", state="ready", since=self.now, updatedAt=self.now - 1)
        self.assertEqual(paneclass.mod_states(now=self.now), {"%1": "ready"})

    def test_missing_dir_is_empty(self):
        self.dir.rmdir()
        self.assertEqual(paneclass.mod_states(now=self.now), {})

    def test_classify_prefers_mod_state_for_claude_only(self):  # mutation: ignore mod -> first assert fails
        self.assertEqual(paneclass.classify("2.1.318", ["> "], False, "working"), ("claude", "working"))
        self.assertEqual(paneclass.classify("2.1.318", ["> "], False, None), ("claude", "ready"))
        self.assertEqual(paneclass.classify("zsh", [], False, "working"), ("shell", "idle"))

    def test_pane_status_reads_the_pane_file(self):  # mutation: pane_status not passing mod -> fails
        self.put("s1.json", session_id="s1", pane="%7", state="needs-you", since=time.time(), updatedAt=time.time())

        def tmux(*args, check=False):
            return "2.1.318~|~0" if args[0] == "display" else "> \n"

        self.assertEqual(paneclass.pane_status(tmux, "%7"), ("claude", "waiting"))
```

- [ ] **Step 2: RED.** `python3 -m unittest discover -s board/tests -p test_paneclass.py 2>&1 | tail -3` → `FAILED (errors=7)` (`mod_states` missing / `classify` takes 3 args).

- [ ] **Step 3: Implement in `board/paneclass.py`.** Add `import json` and `import time` to the imports. After `MENU_RE`, add:

```python
STATUS_TTL = 45   # seconds: an agent-status file older than this is ignored (the mod's heartbeat is 15 s)
MOD_STATES = {"busy": "working", "needs-you": "waiting", "ready": "ready"}


def status_dir():
    """Where claude/plugin/mods/agent-status.js writes one <session_id>.json per session."""
    return tc_env.state_dir() / "agent-status"


def mod_states(now=None, d=None):
    """pane id -> board status from fresh agent-status files: one directory listing per call."""
    now = time.time() if now is None else now
    d = status_dir() if d is None else Path(d)
    best = {}
    try:
        names = os.listdir(d)
    except OSError:
        return {}
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            rec = json.loads((d / name).read_text())
            pane, state, upd = rec["pane"], rec["state"], float(rec["updatedAt"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not isinstance(pane, str) or state not in MOD_STATES or not -5 < now - upd < STATUS_TTL:
            continue
        if pane not in best or upd > best[pane][1]:
            best[pane] = (MOD_STATES[state], upd)
    return {p: s for p, (s, _) in best.items()}
```

Change `classify`'s signature and add the mod branch right after the shell check:

```python
def classify(cmd, rows, bell, mod=None):
    """kind: claude | shell | program ; status: waiting | working | ready | idle | running.
    mod: the pane's fresh agent-status state (mod_states()), preferred over pane text for a claude pane."""
    is_claude = is_claude_cmd(cmd)
    # Claude draws its prompts and spinner at the bottom; older scrollback may quote prompt text.
    tail = "\n".join(rows[-12:])
    if cmd in SHELLS:
        return "shell", "idle"
    if is_claude:
        if mod:
            return "claude", mod
        if WORKING_RE.search(tail) or spinner_live(rows[-30:]):  # no spinner while a prompt is open
```

(the rest of `classify` unchanged). In `pane_status`, change the return to `return classify(cmd, rows, bell == "1", mod_states().get(pane))`.

- [ ] **Step 4: Wire the server.** In `board/server.py`, add `mod_states` to the `from paneclass import …` list on line 33. In `build_state`, just before `sessions = {}` (line ~310), add `mods = mod_states()   # one listing per poll`, and change line 319 to `kind, status = classify(cmd, rows, bell == "1", mods.get(pid))`. Change line 864 to `kind, status = classify(cmd, pane_text(pane), bell == "1", mod_states().get(pane))`.

- [ ] **Step 5: GREEN.** `python3 -m unittest discover -s board/tests -p test_paneclass.py; echo rc=$?` → `OK`, `rc=0`. Also `python3 -m unittest discover -s board/tests -p 'test_overview_api.py'; echo rc=$?` → `rc=0` (touches build_state).

- [ ] **Step 6: Commit.** `git add board/paneclass.py board/server.py board/tests/test_paneclass.py && git commit -m "feat(board): read agent-status mod files before pane text"` (attribution trailer per your harness).

```json:metadata
{"files": ["board/paneclass.py", "board/server.py", "board/tests/test_paneclass.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p test_paneclass.py; echo rc=$?", "acceptanceCriteria": ["seven new tests RED then GREEN", "test_paneclass OK rc=0"], "modelTier": "mechanical"}
```

---

### Task 4: Real run, end to end

**Goal:** In a scratch tmux server, a real lead session loaded with the worktree's plugin goes `busy → ready`, and `needs-you` while an AskUserQuestion is open, seen in its status file and in a test board's `/api/state`; plus one read-only check against the live state.

**Files:**
- Create: `tools/tests/e2e-agent-status.md` (the procedure as run, with captured output)

**Constraints:** scratch server `~/.local/bin/tmux -L agent-status-e2e -f /dev/null`, temp `TC_STATE`; test board `TMUX_DASH_PORT=7710 TMUX_DASH_TOKEN=x TMUX_DASH_TMUX_ARGS='-L agent-status-e2e' TC_OVERSEER=0 TC_STATE=<tmp> python3 board/server.py` from the worktree (API at `http://127.0.0.1:7710/x/api/state`). Answering AskUserQuestion by send-keys: single-select is one Enter. Kill the board, the scratch server and their claude processes afterwards (check with `ps`).

**Acceptance Criteria:**
- [ ] Captured: the status file and the `/api/state` pane `status` for each of: during a turn (`busy` / `working`), after it (`ready` / `ready`), with an AskUserQuestion open (`needs-you` / `waiting`), after answering (`busy` then `ready`).
- [ ] Captured: after the session exits, its status file is gone.
- [ ] Captured, read-only against real state: `python3 -c 'import sys; sys.path.insert(0,"board"); import paneclass; print(paneclass.status_dir(), paneclass.mod_states())'` with the live environment (no `TC_STATE`) prints the live dir and does not raise; the live dir's file count is printed.
- [ ] `grep -c '^## ' tools/tests/e2e-agent-status.md` ≥ 4 (setup, transitions, exit, live read-only).

**Verify:** `grep -c '^## ' tools/tests/e2e-agent-status.md` → ≥ `4`

```json:metadata
{"files": ["tools/tests/e2e-agent-status.md"], "verifyCommand": "grep -c '^## ' tools/tests/e2e-agent-status.md", "acceptanceCriteria": ["file and /api/state captured for busy, ready, needs-you, answered", "file gone after exit", "read-only live mod_states run captured", "at least 4 sections"], "modelTier": "standard"}
```
