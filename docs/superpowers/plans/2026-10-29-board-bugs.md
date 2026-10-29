# Board bugs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four board bugs: `session_path()` returns the project root, "Show dropped" re-renders at once, the Usage tab reads Claude Code's own figures through a statusLine tap, and `test_bg.zsh` stops flaking under load.

**Architecture:** (a) `board/server.py` `session_path` delegates to `relay.session_root`. (b) `pollIdeas(fromCache)` re-renders from the `POLL` cache. (c) A probe records the statusLine JSON; a tap script writes it per session under `<state_dir>/statusline/`; `board/usage.py` prefers the tap for live rows. (d) `systematic-debugging` decides between a real early-TERM bug in `bin/tmux-ctl` and a timing-only test.

**Tech Stack:** Python 3 stdlib (board, tap script, unittest), zsh (tmux-ctl, test harness), tmux 3.8, node (page-function tests), Claude Code 2.1.312 statusLine.

**Spec:** `docs/superpowers/specs/2026-10-29-board-bugs-design.md` (approved 2026-10-29)

## Global Constraints

- Scratch tmux servers start with `-f /dev/null` (`tools/tests/lib.zsh` and the board tests' scratch servers already do).
- Never touch the live tmux server except read-only (`list-*`, `display`, `show-options`), and never the live board on port 7700. A UI or e2e check runs a second board from the worktree: `TMUX_DASH_PORT=7710 python3 board/server.py`.
- `<state_dir>` is `board/tc_env.py` `state_dir()`: `$TC_STATE`, else `${TMPDIR:-/tmp}/tmux-ctl-<uid>`. The tap script resolves it with that same function, never its own copy of the rule.
- The tap script never fails Claude Code: any error prints a fallback line and exits 0. It writes only under `<state_dir>/statusline/`.
- `~/.claude/settings.json` is user-global config: it is written only in Task 6, after the lead has the user's yes, and backed up first to `~/.claude/settings.json.bak-YYYYMMDD`.
- `board/prices.json` context windows stay as the transcript fallback. The board's cost model is unchanged.
- Out of scope: plan-limit enforcement or alerts; how `tmux-ctl` records runs beyond what (d)'s root cause needs.
- Suite verdicts:
  - the board suite's verdict is its own `Ran N tests … OK` line;
  - `run-all.zsh` has no summary line: read its exit code alone (`zsh tools/tests/run-all.zsh; echo rc=$?`, nothing chained after it) plus an uncapped `grep -c FAIL` of its output. One match is the passing test name "zsh FAILED line beats unittest OK".
- Known environment quirk: in the `tests` window, `claude/hooks/tests/test-task-observer-session-start.sh` fails because that pane carries a stale `TASK_OBSERVER_WORKSPACE`. It is not this plan's concern; run that hook test from a normal shell.
- Commits: conventional with scope (`fix(board): …`, `feat(statusline): …`, `test(tmux-ctl): …`), ending with the attribution trailer your harness specifies.

**User decisions (already made):**
- The spec is approved as written (2026-10-29), including the accepted cost in (a): a board-spawned agent branches from the main checkout's HEAD.
- The statusLine install is a user gate: the lead asks before writing `~/.claude/settings.json`.

## Task order

- Tasks 1, 2, 3 and 4 touch disjoint files and may run in parallel.
- Task 5 needs Task 4 (the probe's field table and fixture).
- Task 6 (install, a user gate) needs Task 5.
- Task 7 needs Tasks 2 (both edit `board/index.html`), 4 and 5.
- Task 8 (e2e) needs Tasks 6 and 7.

---

### Task 1: `session_path()` returns the session root

**Goal:** `board/server.py` `session_path(sess)` returns the project's main checkout via `relay.session_root`, so its three callers stop following the lead's `cd`.

**Files:**
- Modify: `board/server.py:458-462` (`session_path`)
- Create: `board/tests/test_session_path.py`

**Acceptance Criteria:**
- [ ] `session_path(sess)` raises `RuntimeError(f"no session '{sess}'")` when the session does not exist, and otherwise returns `relay.session_root(tmux, sess)`. Existence is checked first: `relay.session_root` falls back to `$HOME` for a missing session and never raises.
- [ ] New tests run on a scratch tmux server (`-f /dev/null`, `server.TMUX` pointed at it, killed in cleanup). The fixture is a git repo with a worktree under `.claude/worktrees/`; the session's start path is the repo and its active pane has `cd`'d into the worktree.
  - `session_path` returns the repo;
  - the three callers get the repo: the board-spawn naming at `server.py:500`, the `cwd` passed to `run_script` for `tmux-ctl agent` at `:539` (capture it with a stub `run_script`), and the worktree listing at `:807`;
  - a missing session raises `RuntimeError` with that message.
- [ ] Mutation: restore the old `#{pane_current_path}` body → the three caller tests and the `session_path` test fail (they get the worktree).
- [ ] Board suite: `Ran N tests … OK`.

**Verify:** `python3 -m unittest discover -s board/tests 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests** in `board/tests/test_session_path.py`. Follow an existing scratch-server test for setup (`board/tests/test_poll_efficiency.py` or `test_reload.py` start `tmux -L <sock> -f /dev/null`). Create the repo with one commit (`git -c user.name=t -c user.email=t@t`), `git worktree add .claude/worktrees/wt -b wt`, then `new-session -d -s proj -c <repo>` and `send-keys -t =proj: 'cd <wt>' Enter`. Wait until `display -p -t =proj: '#{pane_current_path}'` shows the worktree, so the test exercises the bug.
- [ ] **Step 2: Run them; expect failures** where the worktree path comes back instead of the repo. Then run the mutation check from the criteria after Step 3.
- [ ] **Step 3: Implement**

```python
def session_path(sess):
    """The project's main checkout for sess (relay.session_root): its start path, then $HOME. Not the pane's cwd,
    which follows the lead's cd into worktrees."""
    if not tmux("display", "-p", "-t", f"={sess}:", "#{session_name}").strip():
        raise RuntimeError(f"no session '{sess}'")
    return relay.session_root(tmux, sess)
```

- [ ] **Step 4: Run the new tests and the board suite**; both green.
- [ ] **Step 5: Commit** `board/server.py` and `board/tests/test_session_path.py` by path: `fix(board): session_path returns the session root, not the lead's cwd`.

```json:metadata
{"files": ["board/server.py", "board/tests/test_session_path.py"], "verifyCommand": "python3 -m unittest discover -s board/tests 2>&1 | tail -3", "acceptanceCriteria": ["missing session raises RuntimeError(no session 'X'); else relay.session_root", "scratch-server tests: session_path and the three callers (:500, :539, :807) get the main checkout when the pane is in a worktree", "mutation: old pane_current_path body fails the caller tests", "board suite OK"], "modelTier": "standard"}
```

---

### Task 2: "Show dropped" re-renders at once

**Goal:** Ticking or unticking "Show dropped" re-renders the Ideas box at once from the last reply, without a fetch.

**Files:**
- Modify: `board/index.html` (`pollIdeas`, around line 1271, and its checkbox `onchange` around line 1289)
- Create: `board/tests/test_ideas_dropped_ui.py`
- Modify: `board/tests/test_ideas_switch.py:52`, `board/tests/test_ideas_gitlab_ui.py` (the `grab` pattern for `pollIdeas`)

**Acceptance Criteria:**
- [ ] With an unchanged poll (304), ticking shows the dropped rows and unticking hides them, with zero fetches. Mutation: `onchange` calls `pollIdeas()` without the cache → `test_toggle_shows_then_hides_dropped_without_fetch` fails ("after tick [ 'keep' ]").
- [ ] With no cached reply, the toggle falls back to one normal fetch and renders. Mutation: return early when there is no cache → `test_toggle_before_any_data_fetches` fails.
- [ ] `test_ideas_switch.py` and `test_ideas_gitlab_ui.py` still pass with the widened `grab` pattern.
- [ ] Board suite: `Ran N tests … OK`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_ideas*' -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing test.** Create `board/tests/test_ideas_dropped_ui.py` with exactly this content:

```python
"""Ticking "Show dropped" re-renders the Ideas box at once from the last data, without a fetch.
Runs the page's own pollJSON and pollIdeas under node with stubbed fetch/el/$ (the harness of test_ideas_gitlab_ui.py);
here fetch answers 304 when If-None-Match matches, as the server does for an unchanged list."""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

BOARD = Path(os.environ.get("BOARD_DIR") or Path(__file__).resolve().parent.parent)


def grab(html, pattern, what):
    m = re.search(pattern, html, re.S | re.M)
    assert m, f"{what} not found in index.html"
    return m.group(0)


@unittest.skipUnless(shutil.which("node"), "node needed to run the page's pollIdeas")
class IdeasDroppedUiTest(unittest.TestCase):
    def run_page(self, scenario):
        html = (BOARD / "index.html").read_text()
        js = """
let PAYLOAD = null, FETCHES = 0;
const session = () => ({name: "A"});
const API = "", POLL = new Map();
// one fixed ETag: the first call answers 200, every later conditional call 304 (an unchanged list)
const fetch = async (url, opts) => {
  FETCHES++;
  const inm = opts && opts.headers && opts.headers["If-None-Match"];
  if (inm === "e1") return {ok: false, status: 304, headers: {get: () => "e1"}, json: async () => null};
  return {ok: true, status: 200, headers: {get: () => "e1"}, json: async () => JSON.parse(JSON.stringify(PAYLOAD))};
};
function mk() {
  return {children: [], dataset: {}, textContent: "", append(...c) { this.children.push(...c); }, replaceChildren(...c) { this.children = c; },
          querySelector(sel) { return this.children.find((c) => c.cls && sel.includes(c.cls.split(" ")[0])) || null; }};
}
const el = (tag, cls, text) => { const n = mk(); n.cls = cls || ""; n.textContent = text || ""; n.tag = tag; return n; };
const box = mk();
const $ = () => box;
const bindAgentMenu = () => {}, post = async () => ({status: 200, j: {}}), toast = () => {};
const localStorage = {setItem() {}};
window = {};
let ideaEditing = null, ideaShowDropped = false, ideasShown = null;
%s
%s
const idea = (status, text) => ({status, ts: "t", text, detail: "", key: text, moved_to: "", issue: null});
const rows = () => box.querySelector(".ideas-list").children.map((r) => r.textContent);
const checkbox = () => box.children.flatMap((c) => c.children || []).find((c) => c.id === "ideas-show-dropped");
(async () => {
%s
})().catch((e) => { console.log("ERR", e.stack); process.exit(2); });
""" % (grab(html, r"^async function pollJSON\(path\) \{.*?^\}\n", "pollJSON"),
       grab(html, r"^async function pollIdeas\([^)]*\) \{.*?^\}\n", "pollIdeas"), scenario)
        return subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)

    def check(self, scenario):
        r = self.run_page(scenario)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_toggle_shows_then_hides_dropped_without_fetch(self):
        # mutation: cb.onchange calls pollIdeas() (no cache) -> the 304 early return keeps "gone" hidden
        self.check("""
PAYLOAD = {ideas: [idea("open", "keep"), idea("dropped", "gone")], open: 1, gitlab: null};
await pollIdeas();
await pollIdeas();   // an unchanged poll (304) renders nothing new
if (rows().join() !== "keep") { console.log("before", rows()); process.exit(1); }
const before = FETCHES, cb = checkbox();
cb.checked = true; await cb.onchange();
if (rows().join() !== "keep,gone") { console.log("after tick", rows()); process.exit(1); }
cb.checked = false; await cb.onchange();
if (rows().join() !== "keep") { console.log("after untick", rows()); process.exit(1); }
if (FETCHES !== before) { console.log("toggle fetched", FETCHES - before); process.exit(1); }
""")

    def test_toggle_before_any_data_fetches(self):
        # no cached reply yet: the toggle falls back to a normal poll
        # mutation: return early when there is no cache -> rows stay [ 'keep' ]
        self.check("""
PAYLOAD = {ideas: [idea("open", "keep"), idea("dropped", "gone")], open: 1, gitlab: null};
await pollIdeas();
POLL.clear();
const cb = checkbox(), before = FETCHES;
cb.checked = true; await cb.onchange();
if (FETCHES !== before + 1) { console.log("expected one fetch", FETCHES - before); process.exit(1); }
if (rows().join() !== "keep,gone") { console.log("rows", rows()); process.exit(1); }
""")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it; expect 2 failures.** `python3 -m unittest board.tests.test_ideas_dropped_ui -v` from the repo root, or `python3 -I board/tests/test_ideas_dropped_ui.py`. Expected: `after tick [ 'keep' ]` and `rows [ 'keep' ]` (the current `onchange` neither uses a cache nor returns its promise). Verified by the plan author on 2026-10-29.
- [ ] **Step 3: Implement.** In `board/index.html` replace the first three lines of `pollIdeas`:

```js
async function pollIdeas() {
  const s = session(); if (!s) return;
  const p = await pollJSON(`ideas?session=${encodeURIComponent(s.name)}`); if (!p.ok || (!p.changed && ideasShown === s.name)) return;
```

with:

```js
async function pollIdeas(fromCache) {   // fromCache: re-render from the last reply (the Show dropped toggle), no fetch
  const s = session(); if (!s) return;
  const path = `ideas?session=${encodeURIComponent(s.name)}`, last = fromCache && POLL.get(`${API}/${path}`);
  const p = last ? { ok: true, changed: true, json: last.json } : await pollJSON(path); if (!p.ok || (!p.changed && ideasShown === s.name)) return;
```

and in the checkbox handler replace `catch (e) {} pollIdeas(); };` with `catch (e) {} return pollIdeas(true); };`.

- [ ] **Step 4: Widen the other two harnesses.** In `board/tests/test_ideas_switch.py` and `board/tests/test_ideas_gitlab_ui.py`, replace `r"^async function pollIdeas\(\) \{.*?^\}\n"` with `r"^async function pollIdeas\([^)]*\) \{.*?^\}\n"`.
- [ ] **Step 5: Run** the Verify command (all `test_ideas*` OK; the plan author ran the new test GREEN against this exact patch), then the board suite.
- [ ] **Step 6: Commit** the four files by path: `fix(board): Show dropped re-renders at once from the last ideas reply`.

```json:metadata
{"files": ["board/index.html", "board/tests/test_ideas_dropped_ui.py", "board/tests/test_ideas_switch.py", "board/tests/test_ideas_gitlab_ui.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_ideas*' -v 2>&1 | tail -3", "acceptanceCriteria": ["unchanged poll: tick shows dropped, untick hides, zero fetches; mutation named", "no cache: one fetch fallback; mutation named", "switch and gitlab ui harnesses pass with widened grab", "board suite OK"], "modelTier": "mechanical"}
```

---

### Task 3: `test_bg.zsh` stops flaking under load

**Goal:** `tools/tests/test_bg.zsh` passes 5 of 5 runs under 2×ncpu CPU load, with the root cause decided by `superpowers-extended-cc:systematic-debugging` and recorded.

**Files:**
- Modify: `tools/tests/test_bg.zsh`
- Modify (only if the root cause is the early-TERM bug): `bin/tmux-ctl`
- Create: `docs/superpowers/plans/2026-10-29-board-bugs-test-bg-report.md`

**Acceptance Criteria:**
- [ ] The report's `## Root cause` section names one of the spec's two causes, with the evidence that decides it: a captured `exit: null` record after an early TERM, or its absence across the reproduction runs.
- [ ] If the cause is the early-TERM bug: `bin/tmux-ctl` finalises the record when TERM lands before the run's trap or record is in place, and a new test step in `test_bg.zsh` sends TERM at once (no wait) and checks the record ends with exit 143 and summary `interrupted`. Mutation: revert the `bin/tmux-ctl` change → that step fails.
- [ ] Either way, every `tt_wait` in the interrupted-run block is failure-checked: a timeout fails the step loudly with its own name (`check "<name>" tt_wait …`), not by a later assertion. Waits are on conditions with a cap sized from the timed load iteration, not fixed 5 s windows.
- [ ] Load runs follow the repeat-count rules:
  - Step 0 times one loaded iteration and sizes the per-run cap from it;
  - each iteration appends `pass|fail`, a wall-clock timestamp and its duration to a tally file, and the report's `## Load runs` section quotes the tally;
  - a failing iteration keeps its full output and a `ps` snapshot;
  - the `yes` load processes are started with saved PIDs, killed in a `trap` (early stop included), and checked gone with `ps` afterwards;
  - the run sits under `caffeinate -w <pid>`.
- [ ] 5 of 5 loaded runs pass, and `zsh tools/tests/run-all.zsh; echo rc=$?` → `rc=0` (the uncapped `grep -c FAIL` is 1, the passing test name).
- [ ] The report has exactly 3 `## ` sections: Root cause, Change, Load runs.

**Verify:** `grep -c '^## ' docs/superpowers/plans/2026-10-29-board-bugs-test-bg-report.md` → `3`

**Steps:**

- [ ] **Step 1:** Invoke `superpowers-extended-cc:systematic-debugging`. Read `tools/tests/test_bg.zsh:26-48` (the interrupted-run block: `tt_wait 5` for the `sleep 30` start record, `kill -TERM`, `tt_wait 5` for `exit: 143`) and the run/trap/record code in `bin/tmux-ctl`.
- [ ] **Step 2:** Reproduce under load as the spec describes (2×ncpu `yes`). On a failure, capture the run record file and decide between the two causes. Write the evidence into the report.
- [ ] **Step 3:** Apply the change the cause calls for (criteria above), test first where a test can come first (`superpowers-extended-cc:test-driven-development`).
- [ ] **Step 4:** The 5 loaded runs with the tally, then run-all.
- [ ] **Step 5:** Commit by path: `fix(tmux-ctl): …` or `test(tmux-ctl): …` to match the cause, plus the report.

```json:metadata
{"files": ["tools/tests/test_bg.zsh", "bin/tmux-ctl", "docs/superpowers/plans/2026-10-29-board-bugs-test-bg-report.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/plans/2026-10-29-board-bugs-test-bg-report.md", "acceptanceCriteria": ["root cause named with deciding evidence", "early-TERM bug: tmux-ctl finalises the record; immediate-TERM test with named mutation", "every tt_wait in the block failure-checked; condition waits sized from a timed iteration", "repeat-count rules: timed iteration, per-iteration tally, full output on failure, load PIDs trapped and checked, caffeinate", "5/5 loaded passes; run-all rc=0", "report has 3 ## sections"], "modelTier": "standard"}
```

---

### Task 4: Probe the statusLine JSON

**Goal:** Record, read-only, the JSON Claude Code 2.1.312 passes to a statusLine command in a real interactive session, as a field table and a scrubbed sample that later tasks use as their fixture.

**Constraints:**
- The temporary statusLine is set only in a scratch project's `.claude/settings.local.json` (or an equivalent session-local setting), never in `~/.claude/settings.json`.
- The interactive session runs in a scratch tmux window or server (`-f /dev/null`) and is closed afterwards; nothing else on the live server is touched.
- The sample is scrubbed: no path under `/Users/`, nothing secret-shaped (tokens, keys, emails). Scrubbed values keep their type and shape (`/Users/x/…` → `/home/user/…`).

**Files:**
- Create: `docs/superpowers/plans/2026-10-29-statusline-probe.md`
- Create: `claude/statusline/tests/fixtures/statusline-sample.json`

**Acceptance Criteria:**
- [ ] The report's field table lists, for each of these, the JSON path or "absent": context-window size, used tokens, used %, model id, model display name, effort, session id, cost, and each plan-limit window (5-hour, weekly). Each row cites the sample.
- [ ] It says when Claude Code calls the statusLine (on which events, how often) and whether it passes the session id the transcripts use, so the board can join the two.
- [ ] If no plan-limit window is in the JSON, the report says "not exposed locally".
- [ ] `statusline-sample.json` is one real captured payload, scrubbed, and parses: `python3 -c "import json,sys; json.load(open(sys.argv[1]))" claude/statusline/tests/fixtures/statusline-sample.json` exits 0. `grep -c '/Users/' <fixture>` → 0.
- [ ] The report has exactly 4 `## ` sections: How captured, Fields, Call timing, Sample.

**Verify:** `grep -c '^## ' docs/superpowers/plans/2026-10-29-statusline-probe.md` → `4`

```json:metadata
{"files": ["docs/superpowers/plans/2026-10-29-statusline-probe.md", "claude/statusline/tests/fixtures/statusline-sample.json"], "verifyCommand": "grep -c '^## ' docs/superpowers/plans/2026-10-29-statusline-probe.md", "acceptanceCriteria": ["field table: context size, used tokens, used %, model id/name, effort, session id, cost, plan-limit windows — path or absent, cited", "call timing and session-id join stated", "no plan-limit -> 'not exposed locally'", "fixture parses, 0 /Users/ hits", "report has 4 ## sections"], "modelTier": "frontier"}
```

---

### Task 5: The statusLine tap script

**Goal:** `claude/statusline/agent-board-statusline` stores each statusLine payload atomically per session and prints a one-line status, and never fails Claude Code.

**Files:**
- Create: `claude/statusline/agent-board-statusline` (python3, executable)
- Create: `claude/statusline/tests/test_statusline.py`
- Modify: `CLAUDE.md` (add the test command to `## Commands`)

**Acceptance Criteria:**
- [ ] It reads the JSON on stdin and writes it, plus `"received_at": <epoch float>`, to `<state_dir>/statusline/<session_id>.json` by temp file in the same directory and `os.replace`. `<state_dir>` comes from importing `board/tc_env.py` (path resolved from the script's real location, symlinks followed); the field names come from the probe report (`docs/superpowers/plans/2026-10-29-statusline-probe.md`).
- [ ] It prints one line: model display name, context %, and the plan-limit figure when the probe found one.
- [ ] A session id containing `/` or `..`, or missing, writes nothing (it cannot escape `<state_dir>/statusline/`); the line still prints.
- [ ] Tests (subprocess runs of the real script, `TC_STATE` pointed at a temp dir):
  - the probe fixture → the file exists with the payload and `received_at`, and the line shows model and context %;
  - invalid JSON → a fallback line, exit 0, no file;
  - a write failure (`statusline/` made read-only) → exit 0 and a line;
  - a hostile session id (`../x`) → exit 0, nothing written outside the temp dir (count files under it before and after).
  Mutation per test: remove the `try/except` → the invalid-JSON test sees a non-zero exit; drop the id check → the hostile-id test finds a file outside `statusline/`.
- [ ] `CLAUDE.md` lists `python3 -m unittest discover -s claude/statusline/tests`.

**Verify:** `python3 -m unittest discover -s claude/statusline/tests -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Read the probe report's field table and the fixture. Write the four tests; run them; expect failures (script missing).
- [ ] **Step 2:** Write the script. The whole body sits in one `try`; the `except` prints `agent-board` (the fallback line) and the script exits 0 on every path. Keep it fast: stdlib only, no subprocess.
- [ ] **Step 3:** Run the tests and each mutation once; record both in your report.
- [ ] **Step 4:** Commit the three files by path: `feat(statusline): tap script stores Claude Code's statusLine payload per session`.

```json:metadata
{"files": ["claude/statusline/agent-board-statusline", "claude/statusline/tests/test_statusline.py", "CLAUDE.md"], "verifyCommand": "python3 -m unittest discover -s claude/statusline/tests -v 2>&1 | tail -3", "acceptanceCriteria": ["atomic write to <state_dir>/statusline/<session_id>.json with received_at; state_dir via board/tc_env.py; fields from the probe report", "one-line status: model, context %, plan-limit if any", "hostile or missing session id writes nothing", "tests: fixture, invalid JSON, write failure, hostile id — all exit 0; mutations named", "CLAUDE.md lists the test command"], "modelTier": "standard"}
```

---

### Task 6: Install the statusLine (user gate)

**Goal:** `~/.claude/settings.json` gets a `statusLine` that runs the tap script, only after the user says yes.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Modify (outside the repo): `~/.claude/settings.json`
- Modify: `docs/INSTALL.md` (one paragraph: what the statusLine does, the settings line, how to remove it)

**Acceptance Criteria:**
- [ ] The lead asks the user with AskUserQuestion before any write. The question names the file (`~/.claude/settings.json`, user-global, read by every Claude Code session), shows the exact `statusLine` JSON, says no `statusLine` exists today, and says the command points at this worktree's script until the merge, after which the lead re-points it at `~/agent-board/claude/statusline/agent-board-statusline`. One yes covers both writes.
- [ ] Before the write: `ls -l ~/.claude/settings.json` (a symlink is edited at its `realpath`), then a backup `~/.claude/settings.json.bak-YYYYMMDD`. The edit is a JSON load/modify/dump that changes only the `statusLine` key: `diff <(jq -S 'del(.statusLine)' backup) <(jq -S 'del(.statusLine)' ~/.claude/settings.json)` prints nothing.
- [ ] The installed value is `{"type": "command", "command": "<absolute script path>"}`, and running that command with the probe fixture on stdin prints the status line and exits 0.
- [ ] Within 2 minutes of the install, at least one live session's tap file appears: `ls -l "$(python3 -c 'import sys; sys.path.insert(0,"board"); import tc_env; print(tc_env.state_dir())')/statusline/"` lists a `.json` with a fresh mtime.
- [ ] `docs/INSTALL.md` has the paragraph; committed by path: `docs(install): the agent-board statusLine`.

**Verify:** `jq -r '.statusLine.command' ~/.claude/settings.json` → the absolute path of `agent-board-statusline`

```json:metadata
{"files": ["docs/INSTALL.md"], "verifyCommand": "jq -r '.statusLine.command' ~/.claude/settings.json", "acceptanceCriteria": ["AskUserQuestion before any write, naming file, exact JSON, the re-point after merge", "symlink check, dated backup, only statusLine key changed (jq diff empty)", "installed command prints a line on the fixture, exit 0", "a fresh tap file appears within 2 minutes", "INSTALL.md paragraph committed"], "modelTier": "mechanical", "userGate": true, "tags": ["user-gate"]}
```

---

### Task 7: The Usage tab reads the tap

**Goal:** `board/usage.py` takes Context %, Model and Effort for a live row from its fresh tap file, decides liveness from tap files too, and the tab shows plan-limit windows or labels its money columns "API-equivalent $".

**Files:**
- Modify: `board/usage.py` (`_live_entry`, `live_sessions`, around lines 205-246)
- Modify: `board/index.html` (Usage table header around line 1449, plus a plan-limit block if the probe found windows)
- Modify: `board/tests/test_usage.py`

**Acceptance Criteria:**
- [ ] A tap file is fresh when its `received_at` is within `live_s` of now. A live row with a fresh tap file takes `context_pct`, `model` and `effort` from it, using the probe report's field paths; without one it keeps today's transcript values (`board/prices.json` windows stay as the fallback).
- [ ] Liveness: a session is live when its tap file is fresh, or when it had a transcript call within `live_s` and has no tap file at all. A session whose tap file is stale and whose transcript call is recent is live from transcripts (spec: "a session with a stale or missing tap file still shows a row, from transcripts").
- [ ] A tap-only live session (fresh tap, no transcript call yet) gets a row; its money columns are 0.
- [ ] Each live row carries `"source": "tap"` or `"source": "transcript"`, so Task 8 can count rows by source.
- [ ] Plan-limit windows: if the probe found them, `report()` returns them and the tab shows them in their own block above the table. If not, the "Last hour" and "Total" headers read "Last hour (API-equivalent $)" and "Total (API-equivalent $)".
- [ ] Tests in `board/tests/test_usage.py` (temp `TC_STATE`, tap files built from the probe fixture):
  - fresh tap → tap values and `source: tap`; mutation: ignore the tap → fails;
  - stale tap + recent transcript call → transcript values; mutation: drop the freshness check → fails;
  - no tap → today's behaviour unchanged (the existing tests stay green);
  - fresh tap, no transcript call → a row; mutation: liveness from transcripts only → fails.
- [ ] Board suite: `Ran N tests … OK`.

**Verify:** `python3 -m unittest discover -s board/tests 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Read the probe report, the tap script's output format (Task 5), and `board/usage.py:205-300` (`_live_entry`, `live_sessions`, `report`). Read how the Usage tab renders a row (`board/index.html` around 1398-1470).
- [ ] **Step 2:** Write the tests; run; expect failures.
- [ ] **Step 3:** Implement: a `tap_entries(now, live_s)` reader over `<state_dir>/statusline/*.json` (skip unparseable files); merge it into `live_sessions`; overlay tap fields in `_live_entry`. Then the header or plan-limit block in `index.html`.
- [ ] **Step 4:** Run the tests, each mutation once, then the board suite.
- [ ] **Step 5:** Commit the three files by path: `feat(board): the Usage tab reads Claude Code's own figures from the statusLine tap`.

```json:metadata
{"files": ["board/usage.py", "board/index.html", "board/tests/test_usage.py"], "verifyCommand": "python3 -m unittest discover -s board/tests 2>&1 | tail -3", "acceptanceCriteria": ["fresh tap (received_at within live_s) overrides context_pct, model, effort via probe field paths", "liveness: fresh tap, or recent transcript call with no tap file; stale tap + recent call -> transcript row", "tap-only session gets a row", "rows carry source tap|transcript", "plan-limit block if probed, else money headers say API-equivalent $", "tests with named mutations; board suite OK"], "modelTier": "standard"}
```

---

### Task 8: Real-state check of the Usage tab

**Goal:** Prove on real sessions that, for every live interactive session with a fresh tap file, the board's Context % is within ±1 point of the tap's and Model and Effort match exactly.

**Files:**
- Create: `docs/superpowers/plans/2026-10-29-board-bugs-e2e-report.md`

**Acceptance Criteria:**
- [ ] A second board runs from the worktree on port 7710 (`TMUX_DASH_PORT=7710 python3 board/server.py`) against the real state dir; the live board on 7700 is not touched. The report gives the command and stops the server afterwards (PID killed, `ps` shows it gone).
- [ ] For each project session on the real tmux server, the report holds `/api/usage?session=<name>` from port 7710 and a per-row comparison against the matching tap file: board Context % vs tap %, Model, Effort, and the row's `source`. Uncapped: the report states the total number of live rows and of tap files, and the counts of `source: tap` rows, rows within ±1, and Model/Effort matches. Every `source: tap` row is within ±1 with exact Model and Effort.
- [ ] At least one row from transcripts is shown: a session whose tap file is stale or missing (for example a worker started before the install, or a session whose tap file the check renames aside for one poll and then restores).
- [ ] Only read-only commands ran against the live tmux server; the report lists every command run.
- [ ] The report has exactly 4 `## ` sections: Setup, Comparison, Transcript fallback, Commands run.

**Verify:** `grep -c '^## ' docs/superpowers/plans/2026-10-29-board-bugs-e2e-report.md` → `4`

```json:metadata
{"files": ["docs/superpowers/plans/2026-10-29-board-bugs-e2e-report.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/plans/2026-10-29-board-bugs-e2e-report.md", "acceptanceCriteria": ["second board on 7710 from the worktree, real state; stopped afterwards", "per-row comparison with uncapped counts; every tap row within ±1 and exact model/effort", "at least one transcript-fallback row shown", "read-only against live tmux; commands listed", "report has 4 ## sections"], "modelTier": "standard"}
```

---

## After the plan (lead)

- At the finish step, re-point the statusLine at `~/agent-board/claude/statusline/agent-board-statusline` (covered by Task 6's yes), with a fresh dated backup.
- In the Next steps round, mark the four ideas the spec closes as `- [x] … → docs/superpowers/specs/2026-10-29-board-bugs-design.md`.
