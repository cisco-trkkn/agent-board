# Agent Board agent controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A right-click (or long-press) menu on Agent Board cards that restarts the orchestrator, shuts down a worker, or asks the lead to shut down a teammate.

**Architecture:** Two new board actions in `server.py` (`stop_agent` kills a worker window by tmux window id after checking its `@tc_agent` tag; `ask_shutdown` queues a `[Board]` line for the lead through the existing Plan comment queue, which gains plain-text items). One global context menu element in `index.html`, filled per card from its role. One rule line in `~/.claude/orchestrator.md`.

**Tech Stack:** Python 3 stdlib (`http.server`), tested with `unittest`; vanilla JS/CSS in one `index.html`; tmux.

**Spec:** `docs/superpowers/specs/2026-10-16-board-agent-controls-design.md`

## Global Constraints

- **Repo:** the code lives in `~/agent-board` (`board/`, `bin/`, `claude/`). The live paths `~/.local/share/tmux-dash`, `~/.local/bin/tmux-*` and `~/.claude/orchestrator.md` are symlinks into that checkout, so edits are live at once. Work on branch `agent/board-agent-controls` in `~/agent-board` (`git switch -c agent/board-agent-controls`), commit after each task (`feat(board): …`), and skip the plan's `.bak-20261016-agentctl` backup steps. Paths below under `~/.local/share/tmux-dash/` are `board/` in the repo, and `~/.claude/orchestrator.md` is `claude/orchestrator.md`.
- **Test command:** `tmux-ctl run tests "cd ~/agent-board && python3 -m unittest discover -s board/tests"`. Every existing test stays green.
- **Exact strings (from the spec):**
  - worker confirmation: `Shut down <name>? Its window closes. Its worktree and branch stay in Worktrees for cleanup.`
  - queued line: `[Board] Please shut down teammate <name>.`
  - `stop_agent` reply: `shut down worker <name>; its worktree and branch are still in Worktrees`
  - `ask_shutdown` reply: `asked the lead to shut down <name>`
  - refusals: `no worker window named <name>`, `<name> is not a worker`, `more than one window named <name>; close it from its terminal`, `<name> is not a teammate`, `bad session`
- **Kill by window id**, never by name. Worker windows are tagged `@tc_agent=1` by `tmux-ctl agent`; teammate windows `@tc_teammate=1`; the hidden agents' session `<project>-bg` is tagged `@tc_bg`.
- **Menu items:** orchestrator card → `Restart orchestrator…`; worker → `Shut down worker…`; teammate → `Ask lead to shut down…`; any other card → no menu (browser default). The visible "Restart orchestrator" button is removed.
- **Live checks** run on the real board with its accumulated state; visibility is checked with `document.elementFromPoint`, never `getBoundingClientRect` alone. Before clicking an item that calls `confirm()`, stub it (`window.confirm = () => true`) through the javascript tool so no browser dialog blocks the extension.
- Restart the board after server changes with `tmux-dash stop && tmux-dash start` (a bare `tmux-dash` opens a browser).

**User decisions (already made):**
- Shutdown covers workers and teammates.
- The actions live in a right-click menu only: no `⋯` button on cards, and the visible "Restart orchestrator" button is removed.
- Teammate shutdown goes through the lead (a queued `[Board]` line), never by killing the teammate's window.
- A worker shutdown leaves its worktree and branch for the Worktrees panel.

---

### Task 0: Plain-text items in the lead's comment queue

**Goal:** `CommentQueue.add_line(sess, text)` queues one literal line for the lead, delivered by the same held-while-busy path as Plan comments.

**Files:**
- Modify: `~/.local/share/tmux-dash/artifacts.py` (class `CommentQueue`, around lines 103-150)
- Test: `~/.local/share/tmux-dash/tests/test_artifacts.py` (class `CommentTest`)

**Acceptance Criteria:**
- [ ] `add_line` stores `{"id", "text", "ts"}`; `CommentQueue.line(c)` returns `c["text"]` for such items, and the Plan comment format is unchanged for the others.
- [ ] Adding the same text twice for a session while the first is still queued keeps one item.
- [ ] An `add_line` item is held while the lead is `waiting`, not running Claude, or its input has text; it is delivered in queue order with Plan comments once the lead is ready.
- [ ] Control characters are stripped from the text; empty text raises `ValueError`.

**Verify:** `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_artifacts -v` → all tests OK

**Steps:**

- [ ] **Step 1: Back up** `cp -p ~/.local/share/tmux-dash/artifacts.py ~/.local/share/tmux-dash/artifacts.py.bak-20261016-agentctl` and the same for `tests/test_artifacts.py`.

- [ ] **Step 2: Write the failing tests** — append to `class CommentTest` in `tests/test_artifacts.py`:

```python
    def test_add_line_is_sent_verbatim_in_order(self):
        q = artifacts.CommentQueue()
        q.add("p", "/r/plan.md", "", "", "note")
        q.add_line("p", "[Board] Please shut down teammate py.")
        sent = []
        self.assertEqual(q.deliver("p", "%1", "claude", "ready", lambda p, t: sent.append(t)), 2)
        self.assertEqual(sent, ["[Plan comment] plan.md: — note", "[Board] Please shut down teammate py."])

    def test_add_line_held_while_busy(self):
        q = artifacts.CommentQueue()
        q.add_line("p", "[Board] x")
        sent = []
        self.assertEqual(q.deliver("p", "%1", "claude", "waiting", lambda p, t: sent.append(t)), 0)
        self.assertEqual(q.deliver("p", "%1", "shell", "idle", lambda p, t: sent.append(t)), 0)
        self.assertEqual(q.deliver("p", "%1", "claude", "ready", lambda p, t: sent.append(t), input_has_text=lambda pane: True), 0)
        self.assertEqual(sent, [])
        self.assertEqual(q.deliver("p", "%1", "claude", "ready", lambda p, t: sent.append(t), input_has_text=lambda pane: False), 1)
        self.assertEqual(sent, ["[Board] x"])

    def test_add_line_dedupes_while_queued(self):
        q = artifacts.CommentQueue()
        q.add_line("p", "[Board] x")
        q.add_line("p", "[Board] x")
        self.assertEqual(len(q.pending("p")), 1)
        q.add_line("other", "[Board] x")
        self.assertEqual(len(q.pending("other")), 1)

    def test_add_line_flattens_and_rejects_empty(self):
        q = artifacts.CommentQueue()
        c = q.add_line("p", "[Board]\x1b x\n y")
        self.assertEqual(artifacts.CommentQueue.line(c), "[Board] x y")
        with self.assertRaises(ValueError):
            q.add_line("p", " \x00 ")
```

- [ ] **Step 3: Run to see them fail**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_artifacts -v`
Expected: the four new tests ERROR with `AttributeError: 'CommentQueue' object has no attribute 'add_line'`.

- [ ] **Step 4: Implement** — in `artifacts.py`, class `CommentQueue`, add after `add`:

```python
    def add_line(self, sess, text):
        """Queue one literal line for the lead (board requests). A line already waiting is not queued twice."""
        text = _flat(text, 2000)
        if not text:
            raise ValueError("empty line")
        with self._lock:
            items = self._items.setdefault(sess, [])
            for c in items:
                if c.get("text") == text:
                    return c
            c = {"id": uuid.uuid4().hex[:8], "text": text, "ts": time.time()}
            items.append(c)
        return c
```

and make `line` return the text for such items (first statement of `line`):

```python
    @staticmethod
    def line(c):
        if "text" in c:
            return c["text"]
        where = f" § {c['anchor']}" if c["anchor"] else ""
        quote = f' "{c["quote"]}"' if c["quote"] else ""
        return f"[Plan comment] {_flat(Path(c['path']).name, 120)}{where}:{quote} — {c['note']}"
```

- [ ] **Step 5: Run the module, then the whole suite**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_artifacts -v` → OK
Run: `tmux-ctl run tests "cd ~/agent-board && python3 -m unittest discover -s board/tests"` → OK

```json:metadata
{"files": ["~/.local/share/tmux-dash/artifacts.py", "~/.local/share/tmux-dash/tests/test_artifacts.py"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_artifacts -v", "acceptanceCriteria": ["add_line items are sent verbatim by line()", "duplicate text while queued keeps one item", "held while waiting / not claude / input has text; delivered in order", "control chars stripped; empty raises ValueError"], "modelTier": "mechanical"}
```

---

### Task 1: `stop_agent` and `ask_shutdown` board actions, and the lead rule

**Goal:** Two `_act` actions: `stop_agent` kills exactly one worker window by id; `ask_shutdown` queues the `[Board]` line for one teammate. Plus the lead rule in `~/.claude/orchestrator.md`.

**Files:**
- Modify: `~/.local/share/tmux-dash/server.py` (`_act`, near the `restart_orchestrator` branch around line 361; new helpers after `restart_orchestrator`)
- Create: `~/.local/share/tmux-dash/tests/test_agent_controls.py`
- Modify: `~/.claude/orchestrator.md` (section "Controlling other agents in the project", the `- Teammates:` bullet)

**Acceptance Criteria:**
- [ ] `stop_agent` finds windows by exact name in the project session and in `<project>-bg` only when that session has `@tc_bg`; it kills the single match with `kill-window -t <window id>` only if it has `@tc_agent == 1`.
- [ ] `stop_agent` refuses, with the spec's messages and no `kill-window` call: the lead (`claude`), a teammate, a shell, an untagged Claude window, a prefix-only name match, two windows with the name, a missing name, a `_web-` session and an invalid session name.
- [ ] `ask_shutdown` queues exactly one `[Board] Please shut down teammate <name>.` (name without the `✦ ` prefix) for a window with `@tc_teammate == 1` in the project session, and refuses anything else with `<name> is not a teammate`.
- [ ] `~/.claude/orchestrator.md` tells the lead to answer that line with a `shutdown_request`.

**Verify:** `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_agent_controls -v` → all tests OK

**Steps:**

- [ ] **Step 1: Back up** `server.py` and `~/.claude/orchestrator.md` as `<file>.bak-20261016-agentctl` (`cp -p`).

- [ ] **Step 2: Write the failing tests** — create `tests/test_agent_controls.py`:

```python
import importlib.util
import os
import unittest
from pathlib import Path

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server_agentctl", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
SEP = server.SEP


class Fake:
    """Sessions -> windows (id, name, agent, teammate). Records every tmux call."""

    def __init__(self, sessions, bg_tagged=True):
        self.sessions, self.bg_tagged, self.calls = sessions, bg_tagged, []

    def tmux(self, *args, check=False):
        self.calls.append(args)
        if args[0] == "show-options":
            target = args[args.index("-t") + 1]
            sess = target.lstrip("=").rstrip(":")
            return "1\n" if self.bg_tagged and sess.endswith("-bg") and sess in self.sessions else ""
        if args[0] == "list-windows":
            sess = args[args.index("-t") + 1].lstrip("=")
            return "".join(f"{i}{SEP}{n}{SEP}{'1' if a else ''}{SEP}{'1' if t else ''}\n"
                           for i, n, a, t in self.sessions.get(sess, []))
        return ""

    def kills(self):
        return [c for c in self.calls if c[0] == "kill-window"]


WINDOWS = {
    "proj": [("@1", "claude", False, False), ("@2", "shell", False, False), ("@3", "✦ py", False, True),
             ("@4", "fix-login", True, False), ("@5", "plain-claude", False, False), ("@6", "fix-login-2", True, False)],
    "proj-bg": [("@8", "tests", False, False), ("@9", "bg-worker", True, False)],
}


class AgentControlsTest(unittest.TestCase):
    def setUp(self):
        self.saved = server.tmux
        server.COMMENTS = server.artifacts.CommentQueue()

    def tearDown(self):
        server.tmux = self.saved

    def act(self, fake, **body):
        server.tmux = fake.tmux
        return server._act(body)

    # stop_agent
    def test_stop_worker_kills_by_window_id(self):
        fake = Fake(WINDOWS)
        msg = self.act(fake, action="stop_agent", session="proj", window="fix-login")
        self.assertEqual(fake.kills(), [("kill-window", "-t", "@4")])
        self.assertEqual(msg, "shut down worker fix-login; its worktree and branch are still in Worktrees")

    def test_stop_worker_in_tagged_bg_session(self):
        fake = Fake(WINDOWS)
        self.act(fake, action="stop_agent", session="proj", window="bg-worker")
        self.assertEqual(fake.kills(), [("kill-window", "-t", "@9")])

    def test_untagged_bg_session_is_not_searched(self):
        fake = Fake(WINDOWS, bg_tagged=False)
        with self.assertRaisesRegex(RuntimeError, "no worker window named bg-worker"):
            self.act(fake, action="stop_agent", session="proj", window="bg-worker")
        self.assertEqual(fake.kills(), [])

    def test_stop_refuses_non_workers(self):
        for name in ("claude", "✦ py", "shell", "plain-claude", "tests"):
            fake = Fake(WINDOWS)
            with self.assertRaisesRegex(RuntimeError, f"{name} is not a worker"):
                self.act(fake, action="stop_agent", session="proj", window=name)
            self.assertEqual(fake.kills(), [], name)

    def test_stop_refuses_prefix_and_missing(self):
        for name in ("fix", "fix-login-", "nope", ""):
            fake = Fake(WINDOWS)
            with self.assertRaisesRegex(RuntimeError, "no worker window named"):
                self.act(fake, action="stop_agent", session="proj", window=name)
            self.assertEqual(fake.kills(), [], name)

    def test_stop_refuses_ambiguous_name(self):
        fake = Fake({"proj": [("@4", "dup", True, False), ("@7", "dup", True, False)]})
        with self.assertRaisesRegex(RuntimeError, "more than one window named dup"):
            self.act(fake, action="stop_agent", session="proj", window="dup")
        self.assertEqual(fake.kills(), [])

    def test_stop_refuses_bad_sessions(self):
        for sess in ("_web-1", "", "a b", "../x"):
            fake = Fake(WINDOWS)
            with self.assertRaisesRegex(RuntimeError, "bad session"):
                self.act(fake, action="stop_agent", session=sess, window="fix-login")
            self.assertEqual(fake.kills(), [], sess)

    # ask_shutdown
    def test_ask_shutdown_queues_one_line(self):
        fake = Fake(WINDOWS)
        msg = self.act(fake, action="ask_shutdown", session="proj", window="✦ py")
        self.assertEqual(msg, "asked the lead to shut down py")
        self.act(fake, action="ask_shutdown", session="proj", window="✦ py")
        lines = [server.artifacts.CommentQueue.line(c) for c in server.COMMENTS.pending("proj")]
        self.assertEqual(lines, ["[Board] Please shut down teammate py."])
        self.assertEqual(fake.kills(), [])

    def test_ask_shutdown_refuses_non_teammates(self):
        for name in ("claude", "fix-login", "shell", "py", "nope"):
            fake = Fake(WINDOWS)
            with self.assertRaisesRegex(RuntimeError, f"{name} is not a teammate"):
                self.act(fake, action="ask_shutdown", session="proj", window=name)
        self.assertEqual(server.COMMENTS.pending("proj"), [])

    def test_ask_shutdown_refuses_bad_session(self):
        with self.assertRaisesRegex(RuntimeError, "bad session"):
            self.act(Fake(WINDOWS), action="ask_shutdown", session="_web-1", window="✦ py")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to see them fail**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_agent_controls -v`
Expected: FAIL/ERROR with `unknown action 'stop_agent'` / `unknown action 'ask_shutdown'`.

- [ ] **Step 4: Implement** — in `server.py`, in `_act`, right after the `restart_orchestrator` branch:

```python
    if a == "stop_agent":
        return stop_agent(sess, body.get("window", ""))
    if a == "ask_shutdown":
        return ask_shutdown(sess, body.get("window", ""))
```

and add after `restart_orchestrator` (module level):

```python
def _check_project(sess):
    if not NAME_RE.fullmatch(sess or "") or sess.startswith("_web-"):
        raise RuntimeError("bad session")


def _windows_named(sess, name):
    """Windows named exactly `name` in the project session and its tagged -bg session."""
    found = []
    targets = [sess]
    if tmux("show-options", "-qv", "-t", f"={sess}-bg:", "@tc_bg").strip():
        targets.append(f"{sess}-bg")
    for t in targets:
        out = tmux("list-windows", "-t", f"={t}", "-F",
                   f"#{{window_id}}{SEP}#{{window_name}}{SEP}#{{@tc_agent}}{SEP}#{{@tc_teammate}}")
        for line in out.splitlines():
            f = line.split(SEP)
            if len(f) == 4 and f[1] == name:
                found.append({"session": t, "id": f[0], "agent": f[2] == "1", "teammate": f[3] == "1"})
    return found


def stop_agent(sess, name):
    """Close one worker window (tagged @tc_agent by tmux-ctl agent), by window id. Its worktree stays."""
    _check_project(sess)
    hits = _windows_named(sess, name) if name else []
    if not hits:
        raise RuntimeError(f"no worker window named {name}")
    if len(hits) > 1:
        raise RuntimeError(f"more than one window named {name}; close it from its terminal")
    if not hits[0]["agent"]:
        raise RuntimeError(f"{name} is not a worker")
    tmux("kill-window", "-t", hits[0]["id"], check=True)
    return f"shut down worker {name}; its worktree and branch are still in Worktrees"


def ask_shutdown(sess, name):
    """Ask the lead (through the comment queue) to shut a teammate down; the lead owns its team."""
    _check_project(sess)
    hits = [h for h in _windows_named(sess, name) if h["session"] == sess] if name else []
    if len(hits) != 1 or not hits[0]["teammate"]:
        raise RuntimeError(f"{name} is not a teammate")
    mate = re.sub(r"^✦\s*", "", name).strip()
    COMMENTS.add_line(sess, f"[Board] Please shut down teammate {mate}.")
    return f"asked the lead to shut down {mate}"
```

- [ ] **Step 5: Run the module, then the whole suite**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_agent_controls -v` → OK
Run: `tmux-ctl run tests "cd ~/agent-board && python3 -m unittest discover -s board/tests"` → OK

- [ ] **Step 6: Lead rule** — in `~/.claude/orchestrator.md`, section "Controlling other agents in the project", directly after the `- Teammates:` bullet (after the sentence ending "which is rejected."), add this bullet:

```markdown
- A line `[Board] Please shut down teammate <name>.` was sent by the user from the Agent Board: send that
  teammate a `shutdown_request` (same `reason` note as above) and confirm in one line.
```

Check: `grep -n "\[Board\] Please shut down teammate" ~/.claude/orchestrator.md` → one match.

- [ ] **Step 7: Restart the board** `tmux-dash stop && tmux-dash start`, then `curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:${TMUX_DASH_PORT:-7700}/$(cat ~/.local/state/tmux-dash/token)/"` → `200`.

```json:metadata
{"files": ["~/.local/share/tmux-dash/server.py", "~/.local/share/tmux-dash/tests/test_agent_controls.py", "~/.claude/orchestrator.md"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_agent_controls -v", "acceptanceCriteria": ["stop_agent kills only a single @tc_agent window by id, in the project or tagged -bg session", "stop_agent refuses lead, teammate, shell, untagged, prefix, ambiguous, missing, _web- and invalid sessions without killing", "ask_shutdown queues exactly one [Board] line for a @tc_teammate window and refuses others", "orchestrator.md carries the [Board] shutdown rule"], "modelTier": "standard"}
```

---

### Task 2: Agent context menu in the board UI

**Goal:** Right-click or a 500ms long press on an agent card opens a menu with the role's item; the visible "Restart orchestrator" button is gone.

**Files:**
- Modify: `~/.local/share/tmux-dash/index.html` — CSS near `.menu` (lines ~56-63); markup next to `<div class="toasts" id="toasts">` (~line 360); `card()` (~lines 430-470); new menu JS after the project menu block (~line 728)

**Acceptance Criteria:**
- [ ] Right-click on the orchestrator card shows exactly `Restart orchestrator…`; on a worker card `Shut down worker…`; on a teammate card `Ask lead to shut down…`; on any other card no board menu opens and the browser's menu is not prevented.
- [ ] The menu opens at the pointer, clamped inside the viewport; focus lands on its first item; ArrowUp/ArrowDown move, Enter/Space choose, Escape closes and returns focus to the card when it still exists.
- [ ] A click outside, a right-click elsewhere, a scroll or choosing an item closes it; the menu survives the 2s card refresh (it is not inside a card).
- [ ] A touch/pen long press (500ms, no move over 10px) opens it; a mouse press does not.
- [ ] `Restart orchestrator…` keeps the existing confirmation text and calls `restart_orchestrator` with `confirm: true`; `Shut down worker…` confirms with the spec text and calls `stop_agent`; `Ask lead to shut down…` calls `ask_shutdown` with no confirmation.
- [ ] No card has a visible "Restart orchestrator" button.

**Verify:** `grep -c 'acts.append(rs)' ~/.local/share/tmux-dash/index.html` → `0`, and `grep -c 'id="agent-menu"' ~/.local/share/tmux-dash/index.html` → `1`; behaviour is verified live in Task 3.

**Steps:**

- [ ] **Step 1: Back up** `cp -p ~/.local/share/tmux-dash/index.html ~/.local/share/tmux-dash/index.html.bak-20261016-agentctl`

- [ ] **Step 2: CSS** — after the `.menu .danger-item` rule add:

```css
.ctx-menu { position: fixed; right: auto; top: 0; left: 0; z-index: 30; }
```

- [ ] **Step 3: Markup** — directly before `<div class="toasts" id="toasts"></div>` add:

```html
<div class="menu ctx-menu" id="agent-menu" role="menu" hidden></div>
```

- [ ] **Step 4: Replace the Restart button in `card()`** — delete the whole block

```js
  if (w.name === "claude" && p.kind === "claude") {
    const rs = el("button", null, "Restart orchestrator");
    ...
    acts.append(rs);
  }
```

and in its place bind the menu to the card:

```js
  if (agentMenuItems(s, w, p).length) bindAgentMenu(c, () => agentMenuItems(s, w, p));
```

Also give the card `c.tabIndex = -1;` right after `const c = el("div", ...)` so focus can return to it.

- [ ] **Step 5: Menu JS** — after the project menu block (the `projMenu.addEventListener("keydown", ...)` handler) add:

```js
// agent cards: right-click (or a long press on touch) opens a role-specific menu at the pointer
function restartOrchestrator(s, p) {
  const mates = s.windows.filter((x) => x.teammate).length;
  const busy = p.status === "working" || p.status === "waiting";
  const msg = `Restart the orchestrator in ${s.name}? This ends the current Claude session in the claude window and starts a fresh claude-orchestrator.`
    + (busy ? ` It is still ${p.status === "working" ? "working" : "waiting on you"}.` : "")
    + (mates ? ` ${mates} teammate window${mates === 1 ? "" : "s"} it started will keep running.` : "");
  if (confirm(msg)) action({ action: "restart_orchestrator", session: s.name, confirm: true });
}

function agentMenuItems(s, w, p) {
  if (w.name === "claude" && p.kind === "claude")
    return [{ label: "Restart orchestrator…", danger: true, run: () => restartOrchestrator(s, p) }];
  const r = role(s, w, p);
  if (r === "worker")
    return [{ label: "Shut down worker…", danger: true, run: () => {
      if (confirm(`Shut down ${w.name}? Its window closes. Its worktree and branch stay in Worktrees for cleanup.`))
        action({ action: "stop_agent", session: s.name, window: w.name });
    } }];
  if (r === "teammate")
    return [{ label: "Ask lead to shut down…", run: () => action({ action: "ask_shutdown", session: s.name, window: w.name }) }];
  return [];
}

const agentMenu = $("#agent-menu");
let agentMenuFrom = null;
function openAgentMenu(x, y, items, from) {
  agentMenu.replaceChildren(...items.map((it) => {
    const b = el("button", it.danger ? "danger-item" : null, it.label);
    b.setAttribute("role", "menuitem");
    b.onclick = () => { closeAgentMenu(false); it.run(); };
    return b;
  }));
  agentMenu.hidden = false;
  agentMenuFrom = from;
  const r = agentMenu.getBoundingClientRect();
  agentMenu.style.left = Math.max(4, Math.min(x, innerWidth - r.width - 4)) + "px";
  agentMenu.style.top = Math.max(4, Math.min(y, innerHeight - r.height - 4)) + "px";
  agentMenu.querySelector("button").focus();
}
function closeAgentMenu(refocus) {
  if (agentMenu.hidden) return;
  agentMenu.hidden = true;
  if (refocus && agentMenuFrom && agentMenuFrom.isConnected) agentMenuFrom.focus();
  agentMenuFrom = null;
}
function bindAgentMenu(card, items) {
  card.addEventListener("contextmenu", (e) => { e.preventDefault(); openAgentMenu(e.clientX, e.clientY, items(), card); });
  let lp = null, x0 = 0, y0 = 0;
  const cancel = () => { clearTimeout(lp); lp = null; };
  card.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse") return;
    x0 = e.clientX; y0 = e.clientY; cancel();
    lp = setTimeout(() => { lp = null; openAgentMenu(x0, y0, items(), card); }, 500);
  });
  card.addEventListener("pointermove", (e) => { if (lp && Math.hypot(e.clientX - x0, e.clientY - y0) > 10) cancel(); });
  card.addEventListener("pointerup", cancel);
  card.addEventListener("pointercancel", cancel);
}
document.addEventListener("click", (e) => { if (!agentMenu.contains(e.target)) closeAgentMenu(false); });
document.addEventListener("contextmenu", (e) => { if (!e.defaultPrevented) closeAgentMenu(false); });
// only the page and the main column: the Activity drawer and previews auto-scroll on every poll
$("#main").addEventListener("scroll", () => closeAgentMenu(false));
window.addEventListener("scroll", () => closeAgentMenu(false));
agentMenu.addEventListener("keydown", (e) => {
  const items = [...agentMenu.querySelectorAll("button")], i = items.indexOf(document.activeElement);
  if (e.key === "Escape") { e.preventDefault(); closeAgentMenu(true); }
  else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
});
```

Function declarations are hoisted, so `card()` can call `agentMenuItems`/`bindAgentMenu` even though they appear later in the file; `agentMenu` (a `const`) is only read inside handlers that run after the script has loaded.

- [ ] **Step 6: Static checks**

Run: `grep -c 'acts.append(rs)' ~/.local/share/tmux-dash/index.html` → `0`
Run: `grep -c 'id="agent-menu"' ~/.local/share/tmux-dash/index.html` → `1`
Run: `node -e 'const h=require("fs").readFileSync(process.env.HOME+"/.local/share/tmux-dash/index.html","utf8");const m=[...h.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x=>x[1]).join("\n");new Function(m);console.log("syntax ok")'` → `syntax ok`
Then reload the board in the browser and confirm the console has no errors (`read_console_messages`).

```json:metadata
{"files": ["~/.local/share/tmux-dash/index.html"], "verifyCommand": "grep -c 'acts.append(rs)' ~/.local/share/tmux-dash/index.html; grep -c 'id=\"agent-menu\"' ~/.local/share/tmux-dash/index.html", "acceptanceCriteria": ["role-specific single item per card; no menu for other cards", "opens at pointer, clamped; keyboard nav; Escape returns focus", "closes on outside click, other right-click, scroll, choice; survives refresh", "touch/pen long press 500ms opens it, mouse press does not", "items call restart_orchestrator / stop_agent / ask_shutdown with the spec confirmations", "no visible Restart orchestrator button"], "modelTier": "standard"}
```

---

### Task 3: Live check on the real board

**Goal:** Prove each menu and both new actions work in Chrome on the real board, with its accumulated state.

**Files:**
- none modified (evidence only); fixes found here go back to the owning task

**Acceptance Criteria:**
- [ ] Orchestrator card: right-click shows `Restart orchestrator…` (checked with `elementFromPoint` at the item's centre); Escape closes it. Do not choose the item.
- [ ] Worker card (a scratch worker started from `+ New agent` with the task `scratch: idle, do nothing`): `Shut down worker…`; with `confirm` stubbed, choosing it shows the toast `shut down worker <name>; …`, the card disappears within one refresh, and `tmux list-windows -a -F '#{window_name}'` no longer lists it; its worktree is still listed in the Worktrees panel.
- [ ] Teammate card: if a teammate window exists, `Ask lead to shut down…` is shown; choosing it is NOT done on a real team. Instead `ask_shutdown` is checked against a scratch tmux session (below).
- [ ] A plain shell or window card: right-click does not open `#agent-menu`.
- [ ] Keyboard: ArrowDown/ArrowUp keep focus inside the menu; no "Restart orchestrator" button exists on any card (`[...document.querySelectorAll('.card-actions button')].some(b => b.textContent.includes('Restart'))` → `false`).
- [ ] Console has no errors after the checks.

**Verify:** the evidence list above, captured as tool output (screenshots or JS return values) in the report

**Steps:**

- [ ] **Step 1:** Load the browser tools in one ToolSearch call (`tabs_context_mcp, tabs_create_mcp, navigate, computer, read_page, javascript_tool, read_console_messages`), open the board URL in a new tab, and stub `window.confirm = () => true` before any click on a confirming item.
- [ ] **Step 2:** Run each acceptance check above in order, dispatching `contextmenu` with real mouse right-clicks (`computer` right_click on the card's preview area).
- [ ] **Step 3: Teammate queue check without a real team** — start a scratch session `tmux new-session -d -s agentctl-scratch -n claude` and a window `tmux new-window -d -t =agentctl-scratch: -n '✦ scratchmate'`, `tmux set-option -w -t '=agentctl-scratch:✦ scratchmate' @tc_teammate 1`. Then:
  `tok=$(cat ~/.local/state/tmux-dash/token); curl -s -X POST -H "X-Dash-Token: $tok" -H 'Content-Type: application/json' -d '{"action":"ask_shutdown","session":"agentctl-scratch","window":"✦ scratchmate"}' "http://127.0.0.1:${TMUX_DASH_PORT:-7700}/$tok/api/action"` → message `asked the lead to shut down scratchmate`; then on the board, switch to the `agentctl-scratch` project tab and confirm the artifacts sidebar shows `1 comment waiting for the lead` (the scratch `claude` window runs a shell, so the line stays queued). Kill the scratch session afterwards with `tmux kill-session -t =agentctl-scratch`.
- [ ] **Step 4:** Remove the scratch worker's worktree from the Worktrees panel (or leave it and report its name).

```json:metadata
{"files": [], "verifyCommand": "live Chrome checks on the board; evidence in the report", "acceptanceCriteria": ["orchestrator menu shown via elementFromPoint, not chosen", "scratch worker shut down from the menu: toast, card and window gone, worktree kept", "teammate menu item shown; ask_shutdown verified on a scratch session", "no menu for plain windows", "keyboard nav works; no Restart button on cards", "no console errors"], "modelTier": "standard"}
```
