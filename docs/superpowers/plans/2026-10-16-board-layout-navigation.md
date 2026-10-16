# Agent Board Layout, Navigation and Folder Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Agent Board's header, add section navigation, turn the terminal and document panes into a resizable side drawer, fix the worktrees row layout, and add a folder picker (autocomplete plus a browser) to the Open project dialog.

**Architecture:**
- A new `dirs.py` module lists folders and keeps a recent-projects file. `server.py` exposes it as two GET routes and records each project opened.
- Everything else is in the single-page `index.html`: header menu, Jump-to row, drawer, worktrees row and dialog. It uses plain DOM code and CSS, in the style already there.

**Tech Stack:**
- Python 3 stdlib (`http.server`, `os.scandir`), tested with `unittest`;
- vanilla JS and CSS in `index.html`;
- the Chrome tools for the live check.

**Spec:** `docs/superpowers/specs/2026-10-16-board-layout-navigation-design.md`

## Global Constraints

- **Code location:** all code is in `~/.local/share/tmux-dash`, which is **not under git**. Before the first edit of each file in a task, copy it to `F.bak-20261016-nav` (do this once per file; if the backup exists, don't overwrite it). "Commit" in a step means writing the task report and a `diff -u F.bak-20261016-nav F` patch into the task workspace; never `git` in that folder.
- **Token:** every new route sits behind the existing `_guard`, so a request without the token gets **404**.
- **`/api/dirs` response shape:** exactly `{"path", "parent", "dirs": [{"name", "git", "hidden"}], "truncated"}`.
  - `parent` is `null` at `/`.
  - The list is capped at 500.
  - Folders only; file names are never returned.
- **`/api/dirs` errors:** 400 `{"error": "not a folder: <p>"}` and 403 `{"error": "can't read <p>: permission denied"}`.
- **Recent projects:**
  - stored in `recent-projects.json` in `artifacts.state_dir()`;
  - absolute paths, newest first, deduplicated, at most 10;
  - written atomically (temp file plus `os.replace`).
- **Browser storage:**
  - keys are `dash.drawerWidth` (px) and `dash.showHidden` (`"1"`/`"0"`);
  - every `localStorage` access is wrapped in try/catch.
- **Drawer:**
  - width is clamped to the range 320px to 70% of the viewport, default 45%;
  - below 900px wide, the drawer stacks under the page at 60vh, as today.
- **Autocomplete:** at most 20 suggestions, debounced by 150ms; stale responses are dropped.
- **Shared file:** Tasks 3, 4 and 5 all edit `index.html`. They run in order (3, then 4, then 5) with one implementer, never in parallel.
- **Test commands:** run suites with `tmux-ctl run tests "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests"`.
- **Board restart:** after changing `server.py` or `index.html`, restart the board with `tmux-dash stop && tmux-dash`.

**User decisions (already made):**
- Navigation is option C: the single page stays, with a sticky Jump-to row, a ⋯ menu holding Open and Close, and the terminal as a side drawer.
- The folder picker has both autocomplete and a Browse button, with Show hidden and a Recent list.
- The folder listing is not limited to `$HOME`. It is protected by the board token and localhost binding.
- The live check runs on the real board with its accumulated state, not on a fresh scratch project.

---

## File structure

| File | Responsibility |
|---|---|
| `dirs.py` (new) | `list_dirs(path, prefix, hidden)`, `record_recent(path)`, `recent(open_paths)`, and nothing else |
| `tests/test_dirs.py` (new) | unit tests for `dirs.py` and route tests for `/api/dirs` and `/api/dirs/recent` |
| `server.py` | the two GET routes; `dirs.record_recent` after a successful `dev` action |
| `index.html` | the header menu, Jump-to row, drawer and grip, worktrees row CSS, and the Open-project dialog |

---

### Task 1: `dirs.py` folder listing and recent projects

**Goal:** A tested `dirs.py` module that lists only folders, with hidden and git flags, and keeps the recent-projects file.

**Files:**
- Create: `~/.local/share/tmux-dash/dirs.py`
- Test: `~/.local/share/tmux-dash/tests/test_dirs.py`

**Acceptance Criteria:**
- [ ] `list_dirs` returns only directories, including symlinks to directories, never files or symlinks to files
- [ ] `hidden=False` leaves out names that start with `.`; every entry carries `hidden` and `git`
- [ ] `prefix` filters case-sensitively; the results are sorted by name; the cap of 500 sets `truncated`
- [ ] `~` expands; `parent` is `None` at `/`; a missing path raises `NotADirectoryError("not a folder: …")`; an unreadable directory raises `PermissionError`
- [ ] `record_recent` moves a path to the front, deduplicates, caps the list at 10 and writes atomically; `recent(open_paths)` puts the open sessions first and drops paths that no longer exist

**Verify:** `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_dirs -v` → all tests OK

**Steps:**

- [ ] **Step 1: Write the failing tests** in `tests/test_dirs.py`:

```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import dirs  # noqa: E402


class ListDirsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        for d in ["alpha", "beta", ".hidden", "repo/.git"]:
            (self.root / d).mkdir(parents=True)
        (self.root / "file.txt").write_text("x")
        (self.root / "link-dir").symlink_to(self.root / "alpha")
        (self.root / "link-file").symlink_to(self.root / "file.txt")

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, r):
        return [d["name"] for d in r["dirs"]]

    def test_only_dirs_sorted_with_flags(self):
        r = dirs.list_dirs(str(self.root))
        self.assertEqual(self.names(r), [".hidden", "alpha", "beta", "link-dir", "repo"])
        by = {d["name"]: d for d in r["dirs"]}
        self.assertTrue(by[".hidden"]["hidden"])
        self.assertFalse(by["alpha"]["hidden"])
        self.assertTrue(by["repo"]["git"])
        self.assertFalse(by["alpha"]["git"])
        self.assertEqual(r["path"], str(self.root))
        self.assertEqual(r["parent"], str(self.root.parent))
        self.assertFalse(r["truncated"])

    def test_hidden_filter_and_prefix(self):
        self.assertNotIn(".hidden", self.names(dirs.list_dirs(str(self.root), hidden=False)))
        self.assertEqual(self.names(dirs.list_dirs(str(self.root), prefix=".h")), [".hidden"])
        self.assertEqual(self.names(dirs.list_dirs(str(self.root), prefix="A")), [])

    def test_cap(self):
        many = self.root / "many"
        for i in range(dirs.CAP + 5):
            (many / f"d{i:04d}").mkdir(parents=True)
        r = dirs.list_dirs(str(many))
        self.assertEqual(len(r["dirs"]), dirs.CAP)
        self.assertTrue(r["truncated"])

    def test_tilde_and_root(self):
        self.assertEqual(dirs.list_dirs("~")["path"], os.path.realpath(os.path.expanduser("~")))
        self.assertEqual(dirs.list_dirs("")["path"], os.path.realpath(os.path.expanduser("~")))
        self.assertIsNone(dirs.list_dirs("/")["parent"])

    def test_errors(self):
        with self.assertRaisesRegex(NotADirectoryError, "not a folder"):
            dirs.list_dirs(str(self.root / "nope"))
        with self.assertRaisesRegex(NotADirectoryError, "not a folder"):
            dirs.list_dirs(str(self.root / "file.txt"))

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_permission_error(self):
        locked = self.root / "locked"
        locked.mkdir()
        locked.chmod(0)
        try:
            with self.assertRaises(PermissionError):
                dirs.list_dirs(str(locked))
        finally:
            locked.chmod(0o755)


class RecentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_STATE"] = self.tmp.name
        self.base = Path(os.path.realpath(self.tmp.name))
        self.p = []
        for i in range(12):
            d = self.base / f"p{i}"
            d.mkdir()
            self.p.append(str(d))

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_STATE", None)

    def stored(self):
        return json.loads((Path(self.tmp.name) / "recent-projects.json").read_text())

    def test_move_to_front_dedupe_cap(self):
        for p in self.p:
            dirs.record_recent(p)
        dirs.record_recent(self.p[5])
        s = self.stored()
        self.assertEqual(len(s), dirs.RECENT_MAX)
        self.assertEqual(s[0], self.p[5])
        self.assertEqual(s.count(self.p[5]), 1)
        self.assertEqual(s[1], self.p[11])

    def test_atomic_no_temp_left(self):
        dirs.record_recent(self.p[0])
        self.assertEqual(sorted(x.name for x in Path(self.tmp.name).iterdir() if x.name.startswith(".recent-")), [])

    def test_recent_merges_open_first_and_drops_missing(self):
        dirs.record_recent(self.p[0])
        dirs.record_recent(self.p[1])
        os.rmdir(self.p[0])
        self.assertEqual(dirs.recent([self.p[2], self.p[1]]), [self.p[2], self.p[1]])

    def test_corrupt_file_is_empty(self):
        (Path(self.tmp.name) / "recent-projects.json").write_text("{not json")
        self.assertEqual(dirs.recent([]), [])
        dirs.record_recent(self.p[0])
        self.assertEqual(self.stored(), [self.p[0]])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_dirs -v`
Expected: ERROR `ModuleNotFoundError: No module named 'dirs'`

- [ ] **Step 3: Implement `dirs.py`**

```python
"""Folder listing and recent projects for the board's Open project dialog."""
import json
import os
import tempfile

from artifacts import state_dir

CAP = 500          # entries returned by one listing
RECENT_MAX = 10    # stored recent projects


def resolve(path):
    p = (path or "").strip() or "~"
    return os.path.realpath(os.path.expanduser(p))


def list_dirs(path="", prefix="", hidden=True):
    """Folders (never files) directly under path. Raises NotADirectoryError or PermissionError."""
    root = resolve(path)
    if not os.path.isdir(root):
        raise NotADirectoryError(f"not a folder: {path or '~'}")
    with os.scandir(root) as it:
        entries = sorted(it, key=lambda e: e.name)
    out = []
    for e in entries:
        n = e.name
        if prefix and not n.startswith(prefix):
            continue
        if not hidden and n.startswith("."):
            continue
        try:
            if not e.is_dir(follow_symlinks=True):
                continue
        except OSError:
            continue
        out.append({"name": n, "git": os.path.exists(os.path.join(root, n, ".git")), "hidden": n.startswith(".")})
    parent = None if root == "/" else os.path.dirname(root)
    return {"path": root, "parent": parent, "dirs": out[:CAP], "truncated": len(out) > CAP}


def _recent_file():
    return state_dir() / "recent-projects.json"


def _load():
    try:
        v = json.loads(_recent_file().read_text())
    except (FileNotFoundError, ValueError):
        return []
    return [p for p in v if isinstance(p, str)] if isinstance(v, list) else []


def record_recent(path):
    p = resolve(path)
    items = [p] + [x for x in _load() if x != p]
    f = _recent_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".recent-")
    with os.fdopen(fd, "w") as fh:
        json.dump(items[:RECENT_MAX], fh)
    os.replace(tmp, f)


def recent(open_paths=()):
    """Open sessions' paths first, then the stored list; no duplicates, no missing folders."""
    seen, out = set(), []
    for p in list(open_paths) + _load():
        if p and p not in seen and os.path.isdir(p):
            seen.add(p)
            out.append(p)
    return out
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_dirs -v`
Expected: every test `ok`. `test_permission_error` is skipped only when running as root.

- [ ] **Step 5: Run the full suite**

Run: `tmux-ctl run tests "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests"`
Expected: `OK`, with 65 + the new tests.

- [ ] **Step 6: "Commit".** Write the task report with the test output, and save `dirs.py` and `tests/test_dirs.py` in full as the task patch (they are new files).

```json:metadata
{"files": ["~/.local/share/tmux-dash/dirs.py", "~/.local/share/tmux-dash/tests/test_dirs.py"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_dirs -v", "acceptanceCriteria": ["only dirs incl. dir symlinks", "hidden filter and flags, git flag", "prefix, sort, 500 cap with truncated", "~ expansion, parent null at /, NotADirectoryError, PermissionError", "recent: move-to-front, dedupe, cap 10, atomic, open-first merge, missing dropped"], "modelTier": "mechanical"}
```

---

### Task 2: `/api/dirs` and `/api/dirs/recent` routes; record opened projects

**Goal:** `server.py` serves the folder listing and the recent list behind the token, and records each project opened from the board.

**Files:**
- Modify: `~/.local/share/tmux-dash/server.py`:
  - the import line (`import activity, artifacts, ideas, relay`);
  - `do_GET` (add two `elif` branches before the final `else`);
  - `_act` (the `if a == "dev":` branch).
- Test: `~/.local/share/tmux-dash/tests/test_dirs.py` (append a route test class)

**Acceptance Criteria:**
- [ ] `GET /<token>/api/dirs?path=<dir>&hidden=0` → 200 with the spec's JSON shape, and no hidden names
- [ ] a missing path → 400 `{"error": "not a folder: …"}`; an unreadable path → 403 `{"error": "can't read …: permission denied"}`
- [ ] `GET /api/dirs` without the token → 404
- [ ] `GET /<token>/api/dirs/recent` → 200 `{"recent": [...]}`, with open sessions' paths first
- [ ] a successful `dev` action calls `dirs.record_recent(path)`; a failed one does not

**Verify:** `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_dirs -v` → all OK, including `DirsRouteTest`

**Steps:**

- [ ] **Step 1: Append the failing route tests** to `tests/test_dirs.py`, before the `if __name__` block:

```python
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from unittest import mock  # noqa: E402

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
import server  # noqa: E402


class DirsRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_STATE"] = self.tmp.name
        self.root = Path(os.path.realpath(self.tmp.name)) / "tree"
        (self.root / "a").mkdir(parents=True)
        (self.root / ".h").mkdir()
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = self.httpd.server_address[1]
        self.hosts = mock.patch.object(server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"})
        self.hosts.start()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{port}"
        self.base = f"{self.origin}/{server.TOKEN}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)
        self.hosts.stop()
        self.tmp.cleanup()
        os.environ.pop("TC_STATE", None)

    def get(self, url):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode()
            finally:
                e.close()

    def test_listing(self):
        code, body = self.get(f"{self.base}/api/dirs?path={self.root}&hidden=0")
        self.assertEqual(code, 200)
        j = json.loads(body)
        self.assertEqual(set(j), {"path", "parent", "dirs", "truncated"})
        self.assertEqual([d["name"] for d in j["dirs"]], ["a"])

    def test_errors(self):
        code, body = self.get(f"{self.base}/api/dirs?path={self.root}/nope")
        self.assertEqual(code, 400)
        self.assertIn("not a folder", json.loads(body)["error"])
        with mock.patch.object(server.dirs, "list_dirs", side_effect=PermissionError):
            code, body = self.get(f"{self.base}/api/dirs?path=/x")
        self.assertEqual(code, 403)
        self.assertEqual(json.loads(body)["error"], "can't read /x: permission denied")

    def test_needs_token(self):
        self.assertEqual(self.get(f"{self.origin}/api/dirs?path=/")[0], 404)

    def test_recent_open_first(self):
        dirs.record_recent(str(self.root / "a"))
        with mock.patch.object(server, "state", return_value={"sessions": [{"name": "t", "path": str(self.root)}]}):
            code, body = self.get(f"{self.base}/api/dirs/recent")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["recent"], [str(self.root), str(self.root / "a")])

    def test_dev_records_only_on_success(self):
        with mock.patch.object(server, "run_script", return_value="ok"), mock.patch.object(server.dirs, "record_recent") as rec:
            server._act({"action": "dev", "path": str(self.root)})
        rec.assert_called_once_with(str(self.root))
        with mock.patch.object(server, "run_script", side_effect=RuntimeError("boom")), mock.patch.object(server.dirs, "record_recent") as rec:
            with self.assertRaises(RuntimeError):
                server._act({"action": "dev", "path": str(self.root)})
        rec.assert_not_called()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_dirs -v`
Expected: `DirsRouteTest` fails with 404 on `api/dirs`, and with `AttributeError: module 'server' has no attribute 'dirs'`.

- [ ] **Step 3: Implement.** In `server.py`:

Import line:

```python
import activity, artifacts, dirs, ideas, relay  # noqa: E402
```

In `do_GET`, add these branches immediately before the final `else:`:

```python
        elif sub == "api/dirs":
            path = (q.get("path") or [""])[0]
            try:
                self._json(200, dirs.list_dirs(path, (q.get("prefix") or [""])[0], (q.get("hidden") or ["1"])[0] != "0"))
            except NotADirectoryError as e:
                self._json(400, {"error": str(e)})
            except PermissionError:
                self._json(403, {"error": f"can't read {path or '~'}: permission denied"})
        elif sub == "api/dirs/recent":
            try:
                open_paths = [s.get("path") for s in state().get("sessions", []) if s.get("path")]
            except Exception:  # tmux not running: the stored list still helps
                open_paths = []
            self._json(200, {"recent": dirs.recent(open_paths)})
```

In `_act`, replace the `dev` branch with:

```python
    if a == "dev":
        path = os.path.expanduser(body["path"].strip())
        if not os.path.isdir(path):
            raise RuntimeError(f"not a folder: {path}")
        msg = run_script([DEV, path], extra_env={"DEV_NO_ATTACH": "1"})
        dirs.record_recent(path)
        return msg or "session ready"
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `tmux-ctl run tests "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests"`
Expected: `OK`, with no regressions in the other suites.

- [ ] **Step 5: Restart the board and check it live**

```bash
tmux-dash stop && tmux-dash
T=$(cat ~/.local/state/tmux-dash/token); P=$(grep -o '127.0.0.1:[0-9]*' ~/.local/state/tmux-dash/server.log | tail -1)
curl -s "http://$P/$T/api/dirs?path=~&prefix=.cl" | python3 -m json.tool | head -20
curl -s "http://$P/$T/api/dirs/recent"
```

Expected: the first `curl` lists `.claude` with `"hidden": true`; the second returns `{"recent": [...]}` that includes `/Users/francisco.ruiz/master-gcp-repo`.

- [ ] **Step 6: "Commit".** Save `diff -u server.py.bak-20261016-nav server.py` and the test diff to the task workspace, along with the report.

```json:metadata
{"files": ["~/.local/share/tmux-dash/server.py", "~/.local/share/tmux-dash/tests/test_dirs.py"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest tests.test_dirs -v", "acceptanceCriteria": ["/api/dirs 200 with spec shape, hidden=0 filters", "400 not a folder, 403 permission denied", "no token -> 404", "/api/dirs/recent open sessions first", "dev records recent only on success"], "modelTier": "mechanical"}
```

---

### Task 3: Header ⋯ menu and Jump-to row

**Goal:** Close project moves into a ⋯ menu, away from the main actions, and a sticky Jump-to row scrolls to each section and highlights the one in view.

**Files:**
- Modify: `~/.local/share/tmux-dash/index.html`:
  - `<header>` `.hdr-actions`;
  - the `.col` section titles;
  - the CSS block near `.hdr-actions`;
  - the JS near `$("#btn-project").onclick`.

**Acceptance Criteria:**
- [ ] The header shows `+ New agent` and a `⋯` button. `Open project…` and `Close project…` are only inside the menu, with Close below a divider, in `var(--red)`.
- [ ] The menu opens on a click or on Enter/Space on `⋯`, and closes on Escape (focus returns to `⋯`), on an outside click, or once an item is chosen. ArrowUp and ArrowDown move focus between items.
- [ ] Both items still open their existing dialogs, and Close keeps its confirmation dialog.
- [ ] A sticky row `Agents · Windows · Worktrees · Activity` stays at the top of the scrolling column. Clicking scrolls smoothly to that section, not hidden under the row; Activity also opens the Activity panel.
- [ ] The Jump-to entry for the section in view is highlighted (`.on`) while scrolling.

**Verify:** Restart the board. In Chrome, open the board, click `⋯` then `Open project…` (the dialog opens), press Escape on an open menu (it closes), click `Worktrees` in the Jump-to row (the worktrees title is at the top and `Worktrees` is highlighted). Capture a screenshot for the report.

**Steps:**

- [ ] **Step 1: HTML.** Replace the `.hdr-actions` div with:

```html
    <div class="hdr-actions">
      <button class="primary" id="btn-agent">+ New agent</button>
      <div class="menu-wrap">
        <button id="btn-menu" aria-haspopup="menu" aria-expanded="false" title="Project actions">⋯</button>
        <div class="menu" id="proj-menu" role="menu" hidden>
          <button role="menuitem" id="btn-project">Open project…</button>
          <hr>
          <button role="menuitem" class="danger-item" id="btn-close">Close project…</button>
        </div>
      </div>
    </div>
```

Give the three section titles inside `.col` the ids `sec-agents`, `sec-windows` and `sec-worktrees`. For example:

```html
      <div class="section-title" id="sec-agents"><span>Agents <span class="count" id="agent-count"></span></span>…
```

Add the Jump-to row as the first child of `<div class="col">`:

```html
      <nav class="jump" id="jump">
        <a href="#sec-agents" data-sec="sec-agents">Agents</a>
        <a href="#sec-windows" data-sec="sec-windows">Windows</a>
        <a href="#sec-worktrees" data-sec="sec-worktrees">Worktrees</a>
        <a href="#activity" data-sec="activity">Activity</a>
      </nav>
```

- [ ] **Step 2: CSS.** Add after the `.hdr-actions` rule:

```css
.menu-wrap { position: relative; }
.menu { position: absolute; right: 0; top: calc(100% + 6px); z-index: 20; min-width: 180px; display: flex; flex-direction: column;
  background: var(--panel); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow); padding: 4px; }
.menu[hidden] { display: none; }
.menu button { border: 0; background: none; text-align: left; padding: 7px 10px; border-radius: 6px; }
.menu button:hover, .menu button:focus-visible { background: var(--panel-2); outline: none; }
.menu hr { border: 0; border-top: 1px solid var(--border); margin: 4px 0; }
.menu .danger-item { color: var(--red); }
.jump { position: sticky; top: 0; z-index: 4; display: flex; gap: 4px; padding: 6px 0; background: var(--bg); }
.jump a { padding: 4px 10px; border-radius: 999px; color: var(--muted); text-decoration: none; font-size: 12px; }
.jump a:hover { background: var(--panel-2); }
.jump a.on { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.section-title { scroll-margin-top: 44px; }
```

- [ ] **Step 3: JS.** Add right after the `$("#btn-close").onclick = …` block:

```js
const projMenu = $("#proj-menu"), menuBtn = $("#btn-menu");
function setMenu(open) {
  projMenu.hidden = !open; menuBtn.setAttribute("aria-expanded", String(open));
  if (open) projMenu.querySelector("button").focus();
}
menuBtn.onclick = (e) => { e.stopPropagation(); setMenu(projMenu.hidden); };
document.addEventListener("click", (e) => { if (!projMenu.hidden && !projMenu.contains(e.target)) setMenu(false); });
projMenu.addEventListener("click", () => setMenu(false));   // runs after the item's own onclick
projMenu.addEventListener("keydown", (e) => {
  const items = [...projMenu.querySelectorAll("button")], i = items.indexOf(document.activeElement);
  if (e.key === "Escape") { e.preventDefault(); setMenu(false); menuBtn.focus(); }
  else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
});

const jumpLinks = [...document.querySelectorAll("#jump a")];
for (const a of jumpLinks) a.onclick = (e) => {
  e.preventDefault();
  const t = document.getElementById(a.dataset.sec);
  if (a.dataset.sec === "activity" && !t.classList.contains("open")) $("#act-toggle").click();
  t.scrollIntoView({ behavior: "smooth", block: "start" });
};
const jumpIO = new IntersectionObserver((ents) => {
  for (const en of ents) if (en.isIntersecting) jumpLinks.forEach((a) => a.classList.toggle("on", a.dataset.sec === en.target.id));
}, { root: $(".col"), rootMargin: "0px 0px -70% 0px" });
["sec-agents", "sec-windows", "sec-worktrees"].forEach((id) => jumpIO.observe(document.getElementById(id)));
```

- [ ] **Step 4: Check.** Run the Python suite (it loads `index.html` for the page route), restart the board, and run the Verify steps in Chrome.

Run: `tmux-ctl run tests "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests"` → `OK`. Then `tmux-dash stop && tmux-dash`.

- [ ] **Step 5: "Commit".** Save `diff -u index.html.bak-20261016-nav index.html`, the screenshot path and the report to the task workspace.

```json:metadata
{"files": ["~/.local/share/tmux-dash/index.html"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests && (tmux-dash stop; tmux-dash)", "acceptanceCriteria": ["header: + New agent and ⋯; Open/Close only in menu, Close below divider in red", "menu keyboard/escape/outside-click behaviour", "items open existing dialogs; Close keeps confirmation", "sticky Jump-to row scrolls to sections; Activity opens the panel", "in-view section highlighted"], "modelTier": "standard"}
```

---

### Task 4: Resizable side drawer and worktrees row layout

**Goal:** The terminal and document panes share one side drawer that you can resize, whose width is remembered, and the worktrees Remove button stays visible at any column width.

**Files:**
- Modify: `~/.local/share/tmux-dash/index.html`:
  - CSS rules `main.with-term` (line ~66), `main.with-doc` (line ~155), `.wt-row` (line ~114) and the `@media (max-width: 900px)` block;
  - the `#term` and `#doc` section markup;
  - `renderWorktrees()`.

**Acceptance Criteria:**
- [ ] With the terminal or a document open, the main column and the drawer sit side by side. The drawer's width comes from `--drawer-w`, which defaults to 45%.
- [ ] Dragging the grip on the drawer's left edge resizes it within the range 320px to 70% of the viewport. The width is saved to `localStorage["dash.drawerWidth"]` and restored after a reload. The iframe doesn't swallow the drag.
- [ ] Below 900px wide, the drawer stacks under the page at 60vh and the grip is hidden.
- [ ] With the drawer at its widest, every worktree row shows its Remove button. The name and branch truncate with an ellipsis, with the full text in `title`.
- [ ] When the worktrees panel is narrower than 520px, the status pills wrap under the name.

**Verify:** Restart the board. In Chrome: open a terminal on any window and drag the grip to the widest setting. Every worktree row's Remove button is visible and has a non-zero bounding box inside the column (check with `getBoundingClientRect()` through the JS tool). Reload the page, open the terminal again, and the width is the same. Capture a screenshot.

**Steps:**

- [ ] **Step 1: CSS.** Delete the rule `main.with-term { grid-template-columns: minmax(360px, 1fr) minmax(420px, 1.25fr); }` and the rule `main.with-doc { grid-template-columns: minmax(320px, .8fr) minmax(460px, 1.4fr); }`. Add:

```css
main.with-term, main.with-doc { grid-template-columns: minmax(0, 1fr) var(--drawer-w, 45%); }
.term, .doc { position: relative; }
.grip { position: absolute; left: 0; top: 0; bottom: 0; width: 8px; cursor: col-resize; z-index: 3; }
.grip:hover, body.resizing .grip { background: var(--accent-soft); }
body.resizing, body.resizing * { cursor: col-resize !important; user-select: none; }
body.resizing iframe { pointer-events: none; }
.wt { container-type: inline-size; }
```

Change `.wt-row` to:

```css
.wt-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 12px; align-items: center; padding: 10px 14px;
  border-top: 1px solid var(--border); }
.wt-row > div:first-child { min-width: 0; }
.wt-row b, .wt-row small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wt-row .tags { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.wt-row > button { white-space: nowrap; }
@container (max-width: 520px) {
  .wt-row { grid-template-columns: minmax(0, 1fr) auto; }
  .wt-row .tags { grid-column: 1; grid-row: 2; justify-content: flex-start; }
  .wt-row > button { grid-column: 2; grid-row: 1 / span 2; }
}
```

In the `@media (max-width: 900px)` block, replace the `main.with-term` line with:

```css
  main.with-term, main.with-doc { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto 60vh; }
  .grip { display: none; }
```

- [ ] **Step 2: HTML.** Add `<div class="grip" title="Drag to resize"></div>` as the first child of `<section class="term" id="term">` and of `<section class="doc" id="doc">`.

- [ ] **Step 3: JS.** Add after the `$("#term-close").onclick = …` line:

```js
const DRAWER_KEY = "dash.drawerWidth";
function setDrawer(px) {
  const w = Math.round(Math.min(window.innerWidth * 0.7, Math.max(320, px)));
  $("#main").style.setProperty("--drawer-w", w + "px");
  return w;
}
try { const w = Number(localStorage.getItem(DRAWER_KEY)); if (w) setDrawer(w); } catch (e) {}
for (const g of document.querySelectorAll(".grip")) g.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  g.setPointerCapture(e.pointerId);
  const right = $("#main").getBoundingClientRect().right - 20;   // main's right padding
  document.body.classList.add("resizing");
  const move = (ev) => setDrawer(right - ev.clientX);
  const up = (ev) => {
    g.removeEventListener("pointermove", move); g.removeEventListener("pointerup", up);
    document.body.classList.remove("resizing");
    const w = setDrawer(right - ev.clientX);
    try { localStorage.setItem(DRAWER_KEY, String(w)); } catch (err) {}
  };
  g.addEventListener("pointermove", move); g.addEventListener("pointerup", up);
});
```

In `renderWorktrees()`, after `const info = el("div"); …`, add:

```js
    info.title = `${it.name} — ${it.branch || "detached"}`;
```

- [ ] **Step 4: Check.** Run the Python suite (`OK`), restart the board, and run the Verify steps in Chrome. Then resize the browser window to under 900px wide and confirm the drawer stacks and the grip is hidden.

- [ ] **Step 5: "Commit".** Save `diff -u index.html.bak-20261016-nav index.html` (cumulative), the screenshots and the report.

```json:metadata
{"files": ["~/.local/share/tmux-dash/index.html"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests && (tmux-dash stop; tmux-dash)", "acceptanceCriteria": ["term/doc side by side using --drawer-w default 45%", "grip resize clamped 320px..70vw, persisted in dash.drawerWidth, iframe doesn't eat drag", "<900px stacks at 60vh, grip hidden", "Remove visible on every worktree row at max drawer width; ellipsis + title", "<520px container: pills wrap under name"], "modelTier": "standard"}
```

---

### Task 5: Open-project dialog with autocomplete and folder browser

**Goal:** Typing a path suggests matching folders, including hidden ones, and `Browse…` lets you click through folders, with Show hidden and a Recent list, to fill the input.

**Files:**
- Modify: `~/.local/share/tmux-dash/index.html`:
  - the `<dialog id="dlg-project">` markup;
  - the dialog CSS;
  - the JS around `$("#btn-project").onclick` and `#form-project`.

**Acceptance Criteria:**
- [ ] Typing `~/.cl` shows a suggestion list containing `.claude/` within about 150ms. Requests are debounced, and a stale response never replaces a newer one. There are at most 20 suggestions.
- [ ] ArrowUp and ArrowDown move the selection. Tab fills in `<dir><name>/` and fetches the next level. Escape closes the list without closing the dialog. Enter submits the dialog. Clicking a suggestion picks it.
- [ ] `Browse…` swaps the input view for the browser. It starts at the typed folder if that exists, otherwise at `~`.
- [ ] The breadcrumb segments and `↑ Up` navigate, and `↑ Up` is disabled at `/`.
- [ ] `Show hidden` is off by default, remembered in `dash.showHidden`, and re-lists when toggled.
- [ ] Recent projects (from `/api/dirs/recent`, up to 10) appear above the folders. Folders carry a `git` badge where they contain `.git`.
- [ ] `Open this folder` fills the input and returns to the input view, and `Back` returns without changing it.
- [ ] A listing error shows inline in red, and the previous folder's listing stays.
- [ ] Opening the dialog always starts in the input view.

**Verify:** Restart the board. In Chrome:
1. Open ⋯ → Open project…, type `~/.cl` and wait; the list shows `.claude/`.
2. Press Tab; the input reads `~/.claude/`.
3. Clear the input and click Browse…; Recent lists `/Users/francisco.ruiz/master-gcp-repo`.
4. Tick Show hidden; `.claude` appears.
5. Click `.claude`, then Open this folder; the input reads `/Users/francisco.ruiz/.claude`.
6. Cancel.

Capture a GIF named `open_project_picker.gif`.

**Steps:**

- [ ] **Step 1: HTML.** Replace the `<dialog id="dlg-project">…</dialog>` block with:

```html
<dialog id="dlg-project"><form method="dialog" id="form-project">
  <h3>Open project</h3>
  <p>Creates a session with claude (orchestrator), shell and tests windows, the same as running <code>dev</code>.</p>
  <div id="pick-input">
    <div class="ac-wrap">
      <input id="project-path" placeholder="~/master-gcp-repo" required autocomplete="off" spellcheck="false"
             role="combobox" aria-autocomplete="list" aria-controls="ac-list" aria-expanded="false">
      <button type="button" id="btn-browse">Browse…</button>
    </div>
    <ul class="ac" id="ac-list" role="listbox" hidden></ul>
  </div>
  <div id="pick-browse" hidden>
    <div class="br-top">
      <button type="button" id="br-up">↑ Up</button>
      <span class="crumbs" id="br-crumbs"></span>
      <label class="br-hide"><input type="checkbox" id="br-hidden"> Show hidden</label>
    </div>
    <div class="br-err" id="br-err"></div>
    <div class="br-list" id="br-list"></div>
    <div class="row"><button type="button" id="br-back">Back</button><button type="button" class="primary" id="br-use">Open this folder</button></div>
  </div>
  <div class="row" id="pick-actions"><button value="cancel" formnovalidate>Cancel</button><button class="primary" value="ok">Open</button></div>
</form></dialog>
```

- [ ] **Step 2: CSS.** Add near the `dialog` rule:

```css
.ac-wrap { display: flex; gap: 8px; }
.ac-wrap input { flex: 1; }
.ac { list-style: none; margin: 4px 0 0; padding: 4px; border: 1px solid var(--border); border-radius: 8px;
  max-height: 220px; overflow: auto; font: 12px var(--mono); }
.ac[hidden] { display: none; }
.ac li { padding: 4px 8px; border-radius: 6px; cursor: pointer; }
.ac li.on, .ac li:hover { background: var(--accent-soft); }
.br-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.crumbs { flex: 1; display: flex; flex-wrap: wrap; gap: 2px; font: 12px var(--mono); min-width: 0; }
.crumb { border: 0; background: none; padding: 2px 4px; border-radius: 4px; }
.crumb:hover { background: var(--panel-2); }
.crumb + .crumb:not(:nth-child(2))::before { content: "/"; color: var(--muted); margin-right: 4px; }
.br-hide { white-space: nowrap; font-size: 12px; }
.br-list { max-height: 50vh; overflow: auto; display: flex; flex-direction: column; margin: 8px 0; min-width: min(420px, 80vw); }
.br-list h4 { margin: 6px 4px 2px; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.br-dir { display: flex; gap: 8px; align-items: center; justify-content: space-between; border: 0; background: none;
  text-align: left; padding: 6px 8px; border-radius: 6px; }
.br-dir:hover { background: var(--panel-2); }
.br-dir span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.br-err { color: var(--red); font-size: 12px; margin-top: 6px; }
.br-err:empty { display: none; }
```

- [ ] **Step 3: JS.** Replace `$("#btn-project").onclick = …;` with the following, and keep the existing `#form-project` submit handler:

```js
const pathIn = $("#project-path"), acList = $("#ac-list");
let acSeq = 0, acItems = [], acSel = -1, acTimer = null, brPath = "~", brRecent = [];
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}
function splitPath(v) { const i = v.lastIndexOf("/"); return i < 0 ? ["", v] : [v.slice(0, i + 1), v.slice(i + 1)]; }
function acRender() {
  acList.replaceChildren(...acItems.map((d, i) => {
    const li = el("li", i === acSel ? "on" : null, d.name + "/");
    li.setAttribute("role", "option");
    li.onmousedown = (e) => { e.preventDefault(); acPick(i); };
    return li;
  }));
  acList.hidden = !acItems.length;
  pathIn.setAttribute("aria-expanded", String(!!acItems.length));
}
function acClear() { acItems = []; acSel = -1; acRender(); }
function acPick(i) {
  const [dir] = splitPath(pathIn.value.trim());
  pathIn.value = dir + acItems[i].name + "/";
  acClear(); acQuery(); pathIn.focus();
}
async function acQuery() {
  const seq = ++acSeq, [dir, prefix] = splitPath(pathIn.value.trim());
  if (!dir) { acClear(); return; }
  let items = [];
  try {
    const j = await getJSON(`${API}/dirs?path=${encodeURIComponent(dir)}&prefix=${encodeURIComponent(prefix)}&hidden=1`);
    items = j.dirs.slice(0, 20);
  } catch (e) { items = []; }
  if (seq !== acSeq) return;            // a newer request was sent
  acItems = items; acSel = items.length ? 0 : -1; acRender();
}
pathIn.addEventListener("input", () => { clearTimeout(acTimer); acTimer = setTimeout(acQuery, 150); });
pathIn.addEventListener("keydown", (e) => {
  if (acList.hidden) return;
  if (e.key === "ArrowDown") { e.preventDefault(); acSel = (acSel + 1) % acItems.length; acRender(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); acSel = (acSel - 1 + acItems.length) % acItems.length; acRender(); }
  else if (e.key === "Tab" && acSel >= 0) { e.preventDefault(); acPick(acSel); }
  else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); acClear(); }
});
pathIn.addEventListener("blur", () => setTimeout(acClear, 120));

function pickMode(browse) { $("#pick-input").hidden = browse; $("#pick-actions").hidden = browse; $("#pick-browse").hidden = !browse; }
try { $("#br-hidden").checked = localStorage.getItem("dash.showHidden") === "1"; } catch (e) {}
function brButton(label, cls, onclick) { const b = el("button", cls); b.type = "button"; b.append(...[label].flat()); b.onclick = onclick; return b; }
async function brLoad(path) {
  let j;
  try { j = await getJSON(`${API}/dirs?path=${encodeURIComponent(path)}&hidden=${$("#br-hidden").checked ? 1 : 0}`); }
  catch (e) { $("#br-err").textContent = e.message; return false; }
  $("#br-err").textContent = "";
  brPath = j.path;
  const parts = j.path.split("/").filter(Boolean), crumbs = $("#br-crumbs");
  crumbs.replaceChildren(brButton("/", "crumb", () => brLoad("/")),
    ...parts.map((p, i) => brButton(p, "crumb", () => brLoad("/" + parts.slice(0, i + 1).join("/")))));
  $("#br-up").disabled = !j.parent;
  $("#br-up").onclick = () => { if (j.parent) brLoad(j.parent); };
  const list = $("#br-list"); list.replaceChildren();
  if (brRecent.length) {
    list.append(el("h4", null, "Recent"));
    for (const p of brRecent) list.append(brButton([el("span", null, p)], "br-dir", () => brLoad(p)));
    list.append(el("h4", null, "Folders"));
  }
  for (const d of j.dirs) {
    const kids = [el("span", null, d.name)];
    if (d.git) kids.push(el("span", "badge", "git"));
    list.append(brButton(kids, "br-dir", () => brLoad(j.path.replace(/\/$/, "") + "/" + d.name)));
  }
  if (!j.dirs.length) list.append(el("div", "empty", "No folders here."));
  if (j.truncated) list.append(el("div", "empty", "Showing the first 500 folders."));
  return true;
}
$("#btn-browse").onclick = async () => {
  acClear(); pickMode(true);
  try { brRecent = (await getJSON(`${API}/dirs/recent`)).recent.slice(0, 10); } catch (e) { brRecent = []; }
  const typed = pathIn.value.trim();
  if (!(typed && await brLoad(typed))) await brLoad("~");
};
$("#br-hidden").onchange = () => {
  try { localStorage.setItem("dash.showHidden", $("#br-hidden").checked ? "1" : "0"); } catch (e) {}
  brLoad(brPath);
};
$("#br-use").onclick = () => { pathIn.value = brPath; pickMode(false); pathIn.focus(); };
$("#br-back").onclick = () => { pickMode(false); pathIn.focus(); };
$("#btn-project").onclick = () => { pickMode(false); acClear(); $("#dlg-project").showModal(); pathIn.focus(); };
```

- [ ] **Step 4: Check.** Run the Python suite (`OK`), restart the board, and run the Verify steps in Chrome, recording the GIF with the Chrome GIF tool.

- [ ] **Step 5: "Commit".** Save the cumulative `index.html` diff, the GIF path and the report.

```json:metadata
{"files": ["~/.local/share/tmux-dash/index.html"], "verifyCommand": "cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests && (tmux-dash stop; tmux-dash)", "acceptanceCriteria": ["~/.cl suggests .claude/, debounced, stale dropped, <=20", "arrow/Tab/Escape/Enter/click behaviour", "Browse starts at typed folder or ~", "breadcrumbs and Up navigate; Up disabled at /", "Show hidden off by default, persisted in dash.showHidden", "Recent above folders; git badge", "Open this folder fills input; Back leaves it", "listing error inline in red, previous listing kept", "dialog opens in input view"], "modelTier": "standard"}
```

---

### Task 6: Live check on the real board

**Goal:** Every spec requirement is confirmed on the user's live board, with its accumulated sessions, worktrees and recent projects, and the evidence is in a report.

**Files:**
- Create: the report `.superpowers/sdd/2026-10-16-board-layout-navigation/live-check.md` in `~/master-gcp-repo` (the git-ignored SDD workspace)

**Acceptance Criteria:**
- [ ] Both suites are green: `zsh ~/.local/share/tmux-tools/tests/run-all.zsh` and the tmux-dash `unittest discover`.
- [ ] The board is restarted and `curl /api/state` returns 200.
- [ ] The ⋯ menu: Close is separated from Open, and both dialogs open.
- [ ] Jump-to scrolls to each of its four targets and highlights the right entry.
- [ ] With the terminal drawer open and dragged to its widest, the `master-gcp-repo` worktree rows each show a Remove button. The width survives a reload.
- [ ] `~/.cl` suggests `.claude/`.
- [ ] Browse with Show hidden lists `.claude`, Recent shows `~/master-gcp-repo`, and Open this folder fills the input.
- [ ] A browser window under 900px stacks the drawer at 60vh.
- [ ] Nothing is closed or removed: no project is closed and no worktree is removed during the check. Remove is only checked for visibility and enabled state.

**Verify:** The report lists each criterion with PASS or FAIL and evidence: a screenshot path, JS tool output or a command's output.

**Steps:**

- [ ] **Step 1:** Run both suites through `tmux-ctl run tests`. Restart the board with `tmux-dash stop && tmux-dash`. Check `/api/state` with `curl`.
- [ ] **Step 2:** In Chrome, use a new tab on the board URL. Read the URL from `~/.local/state/tmux-dash/server.log` and the token file. Walk each criterion. Use the JS tool for the bounding boxes (`[...document.querySelectorAll('.wt-row > button')].map(b => b.getBoundingClientRect().width)`, all > 0) and for the stored width (`localStorage.getItem('dash.drawerWidth')`). Record `board_nav_check.gif`.
- [ ] **Step 3:** Write the report. Send its path and the PASS/FAIL summary to the lead.

```json:metadata
{"files": [".superpowers/sdd/2026-10-16-board-layout-navigation/live-check.md"], "verifyCommand": "zsh ~/.local/share/tmux-tools/tests/run-all.zsh && cd ~/.local/share/tmux-dash && python3 -m unittest discover -s tests", "acceptanceCriteria": ["both suites green", "board restarted, /api/state 200", "menu separates Close; dialogs open", "jump-to scrolls + highlights", "Remove visible with drawer widest; width survives reload", "~/.cl suggests .claude/", "Browse: hidden, Recent, Open this folder", "<900px stacks", "no project closed, no worktree removed"], "modelTier": "standard"}
```

---

## Dependencies

| Task | Blocked by |
|---|---|
| 1 | — |
| 2 | 1 |
| 3 | — |
| 4 | 3 (same file: `index.html`) |
| 5 | 2, 4 (needs the routes; same file) |
| 6 | 1–5 |
