# Board ideas management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the Agent Board, drop/restore, edit and move ideas, and move plan/spec documents to another open project.

**Architecture:** `board/ideas.py` gains locked, key-checked rewrite operations; `board/artifacts.py` gains a file move plus an append-only "moved" marker in the manifest; `board/server.py` exposes four new actions; `board/index.html` adds row menus (the existing agent-menu component), inline edit and a "Show dropped" toggle.

**Tech Stack:** Python 3 stdlib (server, unittest), vanilla JS in one HTML file.

**Spec:** `docs/superpowers/specs/2026-10-19-board-ideas-management-design.md`

## Global Constraints

- Work in a git worktree on branch `feat/ideas-management`, never on a branch in the live checkout `~/agent-board` (it is symlinked into the live install and another orchestrator works there).
- An idea's **key** is `"<ts> · <raw text>"`, where raw text is everything after `· ` on the first line, including any ` → …` suffix. `load()` returns it as `key`; every operation takes it.
- Nothing is ever removed from an ideas file. Drop = `[-]`; move = append to target, then mark source `[-] … → moved to <target>`.
- Ideas-file writes: exclusive `fcntl.lockf` on `<file>.lock`, write to a temp file in the same dir, then `os.replace`.
- Artifact manifests (`$TC_STATE/artifacts-<p>.jsonl`) stay append-only.
- No git commands in `artifacts.move` (no add, no commit).
- Move targets: projects open on the board (`state()["sessions"]` names, `_web-*` excluded), never the source project.
- Tests: `python3 -m unittest discover -s board/tests` must stay green (110 tests before this plan).
- Commits: conventional with scope (`feat(board): …`, `test(board): …`), ending with the attribution trailer your harness specifies.
- Test runs go through `tmux-ctl run -C <worktree> tests "<cmd>"` (options before the window).

**User decisions (already made):**
- "Delete" on the board marks the idea dropped `[-]`; it is never removed from the file, and can be restored.
- Moving a plan/spec moves the file and its `.tasks.json` to the same path in the target repo and does not commit.
- Move targets are only the projects open on the board.

---

### Task 1: Ideas operations — edit, drop/restore, move

**Goal:** `board/ideas.py` gains `edit`, `set_status`, `move`, a `Stale` error, and `key`/`moved_to` fields in `load()`.

**Files:**
- Modify: `board/ideas.py`
- Test: `board/tests/test_ideas.py`

**Acceptance Criteria:**
- [ ] `load()` items carry `key` (`"ts · raw text"`) and `moved_to` (`""` unless a dropped line ends with ` → moved to <p>`); `text` excludes that suffix.
- [ ] `edit` keeps timestamp and checkbox, replaces text and all detail lines, returns the new key; refuses non-open ideas.
- [ ] A key that matches 0 or 2+ lines raises `ideas.Stale`.
- [ ] `set_status` flips open↔dropped, refuses taken ideas and restoring moved ideas.
- [ ] `move` appends the idea (original timestamp and detail) to the target file (with header if new), then marks the source `[-] … → moved to <target>`.
- [ ] All existing ideas tests still pass.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_ideas.py' -v` → all OK

**Steps:**

- [ ] **Step 1: Write the failing tests** — append to `board/tests/test_ideas.py`, inside `class IdeasTest` (helpers use the existing `self.tmp` / `TC_IDEAS_DIR` setup):

```python
    SAMPLE = ("# Ideas: p\n\n"
              "- [ ] 2026-10-16 10:00 · one\n  d1\n  d2\n"
              "- [x] 2026-10-16 10:01 · two → docs/s.md\n"
              "- [ ] 2026-10-16 10:02 · three\n")

    def write(self, text, project="p"):
        (Path(self.tmp.name) / f"{project}.md").write_text(text)

    def read(self, project="p"):
        return (Path(self.tmp.name) / f"{project}.md").read_text()

    def test_load_keys(self):
        self.write(self.SAMPLE + "- [-] 2026-10-16 10:03 · four → moved to q\n")
        got = ideas.load("p")
        self.assertEqual(got[0]["key"], "2026-10-16 10:00 · one")
        self.assertEqual(got[1]["key"], "2026-10-16 10:01 · two → docs/s.md")
        self.assertEqual((got[3]["text"], got[3]["moved_to"]), ("four", "q"))
        self.assertEqual(got[3]["key"], "2026-10-16 10:03 · four → moved to q")
        self.assertEqual(got[0]["moved_to"], "")

    def test_edit_replaces_text_and_detail(self):
        self.write(self.SAMPLE)
        key = ideas.edit("p", "2026-10-16 10:00 · one", "  one   better ", "e1\n\ne2")
        self.assertEqual(key, "2026-10-16 10:00 · one better")
        self.assertEqual(self.read(), self.SAMPLE.replace("· one\n  d1\n  d2\n", "· one better\n  e1\n  e2\n"))

    def test_edit_can_clear_detail(self):
        self.write(self.SAMPLE)
        ideas.edit("p", "2026-10-16 10:00 · one", "one", "")
        self.assertIn("· one\n- [x]", self.read())

    def test_edit_refuses_taken_and_empty(self):
        self.write(self.SAMPLE)
        with self.assertRaises(ValueError):
            ideas.edit("p", "2026-10-16 10:01 · two → docs/s.md", "x")
        with self.assertRaises(ValueError):
            ideas.edit("p", "2026-10-16 10:00 · one", "   ")
        self.assertEqual(self.read(), self.SAMPLE)

    def test_stale_key(self):
        self.write(self.SAMPLE)
        with self.assertRaises(ideas.Stale):
            ideas.edit("p", "2026-10-16 10:00 · gone", "x")
        self.write(self.SAMPLE + "- [ ] 2026-10-16 10:02 · three\n")
        with self.assertRaises(ideas.Stale):
            ideas.set_status("p", "2026-10-16 10:02 · three", "dropped")

    def test_drop_and_restore(self):
        self.write(self.SAMPLE)
        ideas.set_status("p", "2026-10-16 10:02 · three", "dropped")
        self.assertIn("- [-] 2026-10-16 10:02 · three\n", self.read())
        ideas.set_status("p", "2026-10-16 10:02 · three", "open")
        self.assertEqual(self.read(), self.SAMPLE)

    def test_status_refusals(self):
        self.write(self.SAMPLE + "- [-] 2026-10-16 10:03 · four → moved to q\n")
        with self.assertRaises(ValueError):
            ideas.set_status("p", "2026-10-16 10:01 · two → docs/s.md", "dropped")
        with self.assertRaises(ValueError):
            ideas.set_status("p", "2026-10-16 10:03 · four → moved to q", "open")
        with self.assertRaises(ValueError):
            ideas.set_status("p", "2026-10-16 10:02 · three", "taken")

    def test_move(self):
        self.write(self.SAMPLE)
        ideas.move("p", "2026-10-16 10:00 · one", "q")
        self.assertEqual(self.read("q"), "# Ideas: q\n\n- [ ] 2026-10-16 10:00 · one\n  d1\n  d2\n")
        self.assertIn("- [-] 2026-10-16 10:00 · one → moved to q\n  d1\n  d2\n", self.read())
        got = ideas.load("p")[0]
        self.assertEqual((got["status"], got["text"], got["moved_to"]), ("dropped", "one", "q"))
        ideas.move("p", "2026-10-16 10:02 · three", "q")   # appends under the existing header
        self.assertEqual(self.read("q").count("# Ideas"), 1)
        self.assertEqual([i["text"] for i in ideas.load("q")], ["one", "three"])

    def test_move_refusals(self):
        self.write(self.SAMPLE)
        with self.assertRaises(ValueError):
            ideas.move("p", "2026-10-16 10:00 · one", "p")
        with self.assertRaises(ValueError):
            ideas.move("p", "2026-10-16 10:00 · one", "../x")
        with self.assertRaises(ValueError):
            ideas.move("p", "2026-10-16 10:01 · two → docs/s.md", "q")
        with self.assertRaises(ideas.Stale):
            ideas.move("p", "2026-10-16 10:00 · nope", "q")
        self.assertFalse((Path(self.tmp.name) / "q.md").exists())

    def test_add_after_edit(self):
        self.write(self.SAMPLE)
        ideas.edit("p", "2026-10-16 10:02 · three", "3")
        ideas.add("p", "five")
        self.assertEqual([i["text"] for i in ideas.load("p")], ["one", "two → docs/s.md", "3", "five"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `tmux-ctl run -C <worktree> tests "python3 -m unittest discover -s board/tests -p 'test_ideas.py' -v"`
Expected: errors — `KeyError: 'key'`, `AttributeError: module 'ideas' has no attribute 'edit'` (and `Stale`, `set_status`, `move`).

- [ ] **Step 3: Implement** — in `board/ideas.py`:

Update the module docstring's second paragraph to add: `The board can edit, drop/restore and move ideas; a move appends to the target and marks the source "[-] … → moved to <target>".`

Add after `STATUS = …`:

```python
MOVED_RE = re.compile(r" → moved to ([A-Za-z0-9_-][A-Za-z0-9._-]*)$")


class Stale(ValueError):
    """The key no longer names exactly one idea: the file changed since it was loaded."""
```

Replace `add` with a version that shares the append with `move`:

```python
def _append(project, first, detail_lines):
    p = ideas_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = first + "\n" + "".join(f"  {l}\n" for l in detail_lines)
    with open(f"{p}.lock", "w") as lk:
        fcntl.lockf(lk, fcntl.LOCK_EX)
        new = not p.exists() or p.stat().st_size == 0
        with open(p, "a") as f:
            if new:
                f.write(f"# Ideas: {project}\n\n")
            f.write(entry)


def _clean_detail(detail):
    return [l.strip() for l in str(detail).splitlines() if l.strip()]


def add(project, text, detail="", now=None):
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("empty idea")
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    first = f"- [ ] {stamp} · {text}"
    _append(project, first, _clean_detail(detail))
    return first


def _rewrite(project, key, change):
    """Under the lock, find the one idea whose key matches and replace it (first line + detail)
    with change(box, ts, raw_text, detail_lines) -> (first_line, detail_lines)."""
    p = ideas_path(project)
    with open(f"{p}.lock", "w") as lk:
        fcntl.lockf(lk, fcntl.LOCK_EX)
        lines = p.read_text().splitlines(keepends=True) if p.exists() else []
        hits = [i for i, l in enumerate(lines)
                if (m := LINE_RE.match(l.rstrip("\n"))) and f"{m[2]} · {m[3]}" == key]
        if len(hits) != 1:
            raise Stale("the idea changed since you loaded it")
        i = j = hits[0]
        j += 1
        while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
            j += 1
        m = LINE_RE.match(lines[i].rstrip("\n"))
        first, detail = change(m[1], m[2], m[3], [l.strip() for l in lines[i + 1:j]])
        lines[i:j] = [first + "\n"] + [f"  {d}\n" for d in detail]
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text("".join(lines))
        os.replace(tmp, p)
        return first


def edit(project, key, text, detail=""):
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("empty idea")
    new_detail = _clean_detail(detail)

    def change(box, ts, raw, old):
        if box != " ":
            raise ValueError("only open ideas can be edited")
        return f"- [ ] {ts} · {text}", new_detail
    return _rewrite(project, key, change)[6:]


def set_status(project, key, status):
    flip = {"dropped": (" ", "-"), "open": ("-", " ")}
    if status not in flip:
        raise ValueError(f"bad status {status!r}")
    want, to = flip[status]

    def change(box, ts, raw, detail):
        if box != want:
            raise ValueError(f"the idea is {STATUS[box]}")
        if to == " " and MOVED_RE.search(raw):
            raise ValueError("a moved idea cannot be restored here; restore it in the project it moved to")
        return f"- [{to}] {ts} · {raw}", detail
    return _rewrite(project, key, change)


def move(project, key, target):
    ideas_path(target)   # validates the name
    if target == project:
        raise ValueError("the idea is already in that project")
    got = [i for i in load(project) if i["key"] == key]
    if len(got) != 1:
        raise Stale("the idea changed since you loaded it")
    idea = got[0]
    if idea["status"] != "open":
        raise ValueError("only open ideas can be moved")
    # append first: a failure before the source is marked leaves a duplicate, never a lost idea
    _append(target, f"- [ ] {idea['ts']} · {idea['text']}", idea["detail"].splitlines())

    def change(box, ts, raw, detail):
        if box != " ":
            raise Stale("the idea changed since you loaded it")
        return f"- [-] {ts} · {raw} → moved to {target}", detail
    return _rewrite(project, key, change)
```

In `load`, replace the `out.append(...)` for a matched line with:

```python
            mv = MOVED_RE.search(m[3]) if m[1] == "-" else None
            out.append({"status": STATUS[m[1]], "ts": m[2], "text": m[3][:mv.start()] if mv else m[3],
                        "detail": "", "key": f"{m[2]} · {m[3]}", "moved_to": mv[1] if mv else ""})
```

- [ ] **Step 4: Run to verify they pass**

Run: `tmux-ctl run -C <worktree> tests "python3 -m unittest discover -s board/tests -v"`
Expected: all OK (110 + 10 new).

- [ ] **Step 5: Commit**

```bash
git add board/ideas.py board/tests/test_ideas.py
git commit -m "feat(board): ideas edit, drop/restore and move"   # end with your harness's attribution trailer
```

```json:metadata
{"files": ["board/ideas.py", "board/tests/test_ideas.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -v", "acceptanceCriteria": ["load() items carry key and moved_to; text excludes the moved suffix", "edit keeps timestamp, replaces text and detail, returns new key, refuses non-open", "0 or 2+ matches raise ideas.Stale", "set_status flips open<->dropped, refuses taken and restoring moved", "move appends to target with original ts/detail then marks source", "existing ideas tests pass"], "modelTier": "mechanical"}
```

---

### Task 2: Artifact move

**Goal:** `board/artifacts.py` gains `move()`; `summary()` and `read()` treat a path whose latest manifest entry is a move as gone.

**Files:**
- Modify: `board/artifacts.py`
- Test: `board/tests/test_artifacts.py`

**Acceptance Criteria:**
- [ ] `move` relocates the file and its `.tasks.json` to the same relative path under the target repo, creating parent dirs.
- [ ] Refuses: target == project, path not in the manifest or already moved, path outside `docs/superpowers/plans/` or `specs/` of the source repo, any path under `/.claude/worktrees/`, an existing destination (file or sidecar). A refusal changes nothing on disk.
- [ ] Calls the register hook for the target with `--agent you --project <target>` and appends `{"ts", "path", "moved_to", "agent": "you"}` to the source manifest.
- [ ] `summary()` hides the moved item; `read()` of the old path raises `FileNotFoundError`.
- [ ] No git command runs (no `git` in any `subprocess.run` call).

**Verify:** `python3 -m unittest discover -s board/tests -v` → all OK

**Steps:**

- [ ] **Step 1: Write the failing tests** — add a new class to `board/tests/test_artifacts.py` (after `Base`'s other subclasses; it reuses `Base`'s temp `TC_STATE`):

```python
class MoveTest(Base):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.src, self.dst = root / "srcrepo", root / "dstrepo"
        (self.src / "docs/superpowers/plans").mkdir(parents=True)
        self.dst.mkdir()
        self.doc = self.src / "docs/superpowers/plans/2026-10-19-x.md"
        self.doc.write_text("# X\n")
        self.side = Path(f"{self.doc}.tasks.json")
        self.side.write_text("{}\n")
        with open(self.state / "artifacts-p.jsonl", "a") as f:
            f.write(json.dumps({"ts": 9, "path": str(self.doc), "kind": "plan", "agent": "claude",
                                "hash": sha("# X\n"), "url": "", "epoch": 1}) + "\n")

    def move(self, path=None, target="t"):
        return artifacts.move("p", str(path or self.doc), target, str(self.src), str(self.dst))

    def test_move_file_and_sidecar(self):
        with mock.patch.object(artifacts.subprocess, "run") as run:
            msg = self.move()
        new = self.dst / "docs/superpowers/plans/2026-10-19-x.md"
        self.assertEqual(new.read_text(), "# X\n")
        self.assertEqual(Path(f"{new}.tasks.json").read_text(), "{}\n")
        self.assertFalse(self.doc.exists() or self.side.exists())
        self.assertIn("t", msg)
        args = run.call_args[0][0]
        self.assertEqual(args[1:], ["--path", str(new), "--agent", "you", "--project", "t"])
        self.assertFalse(any("git" in str(c[0][0][0]) for c in run.call_args_list))
        last = json.loads((self.state / "artifacts-p.jsonl").read_text().splitlines()[-1])
        self.assertEqual((last["path"], last["moved_to"], last["agent"]), (str(self.doc), str(new), "you"))
        self.assertNotIn(str(self.doc), [i["path"] for i in artifacts.summary("p")["items"]])
        with self.assertRaises(FileNotFoundError):
            artifacts.read("p", str(self.doc))

    def test_move_without_sidecar(self):
        self.side.unlink()
        with mock.patch.object(artifacts.subprocess, "run"):
            self.move()
        self.assertTrue((self.dst / "docs/superpowers/plans/2026-10-19-x.md").exists())

    def test_refusals_change_nothing(self):
        (self.dst / "docs/superpowers/plans").mkdir(parents=True)
        (self.dst / "docs/superpowers/plans/2026-10-19-x.md").write_text("theirs\n")
        other = self.src / "notes.md"
        other.write_text("n\n")
        with open(self.state / "artifacts-p.jsonl", "a") as f:
            f.write(json.dumps({"ts": 10, "path": str(other), "kind": "other", "agent": "you", "url": ""}) + "\n")
        before = (self.state / "artifacts-p.jsonl").read_text()
        with mock.patch.object(artifacts.subprocess, "run") as run:
            with self.assertRaises(ValueError):   # destination exists
                self.move()
            with self.assertRaises(ValueError):   # outside docs/superpowers/plans|specs
                self.move(path=other)
            with self.assertRaises(ValueError):   # same project
                self.move(target="p")
            with self.assertRaises(FileNotFoundError):   # not in the manifest
                self.move(path=self.src / "docs/superpowers/plans/unknown.md")
        run.assert_not_called()
        self.assertTrue(self.doc.exists() and self.side.exists())
        self.assertEqual((self.state / "artifacts-p.jsonl").read_text(), before)

    def test_refuses_worktree_paths(self):
        wt = self.src / ".claude/worktrees/w/docs/superpowers/plans/y.md"
        wt.parent.mkdir(parents=True)
        wt.write_text("y\n")
        with open(self.state / "artifacts-p.jsonl", "a") as f:
            f.write(json.dumps({"ts": 11, "path": str(wt), "kind": "plan", "agent": "w", "url": ""}) + "\n")
        with mock.patch.object(artifacts.subprocess, "run"):
            with self.assertRaises(ValueError):
                self.move(path=wt)
        self.assertTrue(wt.exists())

    def test_moved_twice_is_refused(self):
        with mock.patch.object(artifacts.subprocess, "run"):
            self.move()
            with self.assertRaises(FileNotFoundError):
                self.move()
```

- [ ] **Step 2: Run to verify they fail**

Run: `tmux-ctl run -C <worktree> tests "python3 -m unittest discover -s board/tests -p 'test_artifacts.py' -v"`
Expected: `AttributeError: module 'artifacts' has no attribute 'move'`.

- [ ] **Step 3: Implement** — in `board/artifacts.py`:

Add `import shutil` to the imports. Add after `lineage()`:

```python
def _moved(project):
    """Paths whose latest manifest entry is a move to another project."""
    gone = set()
    for e in entries(project):
        key = e.get("url") or e.get("path")
        if not key:
            continue
        if e.get("moved_to"):
            gone.add(key)
        else:
            gone.discard(key)
    return gone
```

In `summary()`, right after `by = {}` add `gone = _moved(project)`, and change the loop's skip to `if not key or key in gone or e.get("moved_to"):` then `continue`.

In `read()`, change the allowlist check to:

```python
    if path in _moved(project) or not any(e.get("path") == path and not e.get("url") for e in entries(project)):
        raise FileNotFoundError(path)
```

Add after `save()`:

```python
DOC_DIRS = ("docs/superpowers/plans/", "docs/superpowers/specs/")


def move(project, path, target, source_repo, target_repo):
    """Move a plan or spec (and its .tasks.json) to the same path in another project's repo.
    No git commands: both repos are left with the change uncommitted."""
    if target == project:
        raise ValueError("the document is already in that project")
    if path in _moved(project) or not any(e.get("path") == path and not e.get("url") for e in entries(project)):
        raise FileNotFoundError(path)
    rel = os.path.relpath(path, source_repo)
    if not rel.startswith(DOC_DIRS) or any("/.claude/worktrees/" in f"{p}/" for p in (path, source_repo, target_repo)):
        raise ValueError("only plans and specs under docs/superpowers/ in the project's own checkout can move")
    src, dst = Path(path), Path(target_repo) / rel
    side, dside = Path(f"{src}.tasks.json"), Path(f"{dst}.tasks.json")
    for p in (dst, dside) if side.exists() else (dst,):
        if p.exists():
            raise ValueError(f"{p} already exists in {target}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    if side.exists():
        shutil.move(str(side), str(dside))
    subprocess.run([str(HOOK), "--path", str(dst), "--agent", "you", "--project", target],
                   capture_output=True, timeout=10, env={**os.environ, "TC_STATE": str(state_dir())})
    with open(state_dir() / f"artifacts-{project}.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "path": path, "moved_to": str(dst), "agent": "you"}) + "\n")
    return f"moved {rel} to {target}; commit it in both repos"
```

Note: `HOOK` is a `Path`; `str(HOOK)` is `args[0]`, so the test's "no git" check inspects `args[0]` of every call.

- [ ] **Step 4: Run to verify they pass**

Run: `tmux-ctl run -C <worktree> tests "python3 -m unittest discover -s board/tests -v"`
Expected: all OK.

- [ ] **Step 5: Commit**

```bash
git add board/artifacts.py board/tests/test_artifacts.py
git commit -m "feat(board): move a plan or spec to another project"   # end with your harness's attribution trailer
```

```json:metadata
{"files": ["board/artifacts.py", "board/tests/test_artifacts.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -v", "acceptanceCriteria": ["move relocates file and .tasks.json to same relative path in target repo", "refusals (same project, not in manifest/already moved, outside plans|specs, worktree path, existing destination) change nothing", "hook called for target with --agent you; source manifest gets a moved_to line", "summary hides the moved item; read of old path raises FileNotFoundError", "no git command runs"], "modelTier": "mechanical"}
```

---

### Task 3: Server actions

**Goal:** `board/server.py` exposes `idea_edit`, `idea_status`, `idea_move`, `artifact_move`, validates project names and open targets, and maps `ideas.Stale` to HTTP 409.

**Files:**
- Modify: `board/server.py`
- Create: `board/tests/test_ideas_actions.py`

**Acceptance Criteria:**
- [ ] Each action validates `session` (and `target`) with `_check_project`; a target not among open board projects is refused with "<t> is not open on the board".
- [ ] `artifact_move` passes the repo top-levels of both projects (main checkout, via `git rev-parse --git-common-dir`) to `artifacts.move`.
- [ ] `ideas.Stale` → HTTP 409 with `ok: false` and the message; other errors stay 400.
- [ ] Messages: "idea updated", "idea dropped", "idea restored", "idea moved to <t>", and the artifacts.move message.

**Verify:** `python3 -m unittest discover -s board/tests -v` → all OK

**Steps:**

- [ ] **Step 1: Write the failing tests** — create `board/tests/test_ideas_actions.py`:

```python
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("tmux_dash_server_ideas", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
ideas = server.ideas

STATE = {"sessions": [{"name": "p"}, {"name": "q"}, {"name": "_web-1"}]}
SAMPLE = "# Ideas: p\n\n- [ ] 2026-10-16 10:00 · one\n  d\n"


class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_IDEAS_DIR"] = self.tmp.name
        (Path(self.tmp.name) / "p.md").write_text(SAMPLE)
        self.st = mock.patch.object(server, "state", return_value=STATE)
        self.st.start()

    def tearDown(self):
        self.st.stop()
        self.tmp.cleanup()
        os.environ.pop("TC_IDEAS_DIR", None)

    def act(self, **body):
        return server._act(body)

    def test_edit_status_move(self):
        k = "2026-10-16 10:00 · one"
        self.assertEqual(self.act(action="idea_edit", session="p", key=k, text="uno", detail="x"), "idea updated")
        k = "2026-10-16 10:00 · uno"
        self.assertEqual(self.act(action="idea_status", session="p", key=k, status="dropped"), "idea dropped")
        self.assertEqual(self.act(action="idea_status", session="p", key=k, status="open"), "idea restored")
        self.assertEqual(self.act(action="idea_move", session="p", key=k, target="q"), "idea moved to q")
        self.assertEqual([i["text"] for i in ideas.load("q")], ["uno"])

    def test_target_must_be_open(self):
        k = "2026-10-16 10:00 · one"
        for t in ("zz", "_web-1", "../q"):
            with self.assertRaises(Exception):
                self.act(action="idea_move", session="p", key=k, target=t)
        with self.assertRaises(Exception):
            self.act(action="idea_edit", session="_web-1", key=k, text="x")
        self.assertEqual((Path(self.tmp.name) / "p.md").read_text(), SAMPLE)

    def test_artifact_move_passes_repos(self):
        with mock.patch.object(server, "project_repo", side_effect=lambda s: f"/repos/{s}"), \
             mock.patch.object(server.artifacts, "move", return_value="moved") as mv:
            got = self.act(action="artifact_move", session="p", path="/repos/p/docs/superpowers/plans/a.md", target="q")
        self.assertEqual(got, "moved")
        mv.assert_called_once_with("p", "/repos/p/docs/superpowers/plans/a.md", "q", "/repos/p", "/repos/q")

    def test_project_repo_is_main_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git -C '{d}' init -q && git -C '{d}' commit -q --allow-empty -m i")
            os.system(f"git -C '{d}' worktree add -q '{d}/.claude/worktrees/w' -b w")
            with mock.patch.object(server, "session_path", return_value=f"{d}/.claude/worktrees/w"):
                self.assertEqual(os.path.realpath(server.project_repo("p")), os.path.realpath(d))

    def test_stale_is_409(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with mock.patch.object(server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"}):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/{server.TOKEN}/api/action", method="POST",
                    headers={"X-Dash-Token": server.TOKEN},
                    data=json.dumps({"action": "idea_status", "session": "p", "key": "2026-10-16 10:00 · gone",
                                     "status": "dropped"}).encode())
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(cm.exception.code, 409)
                self.assertFalse(json.loads(cm.exception.read())["ok"])
                cm.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            t.join(5)
```

- [ ] **Step 2: Run to verify they fail**

Run: `tmux-ctl run -C <worktree> tests "python3 -m unittest discover -s board/tests -p 'test_ideas_actions.py' -v"`
Expected: `RuntimeError: unknown action 'idea_edit'`, `AttributeError: … 'project_repo'`, and 400 instead of 409.

- [ ] **Step 3: Implement** — in `board/server.py`:

Add after `session_path()`:

```python
def project_repo(sess):
    """The project's main checkout, even when its lead pane sits in a worktree."""
    r = git(session_path(sess), "rev-parse", "--path-format=absolute", "--git-common-dir")
    if r.returncode != 0:
        raise RuntimeError(f"{sess} is not in a git repo")
    return str(Path(r.stdout.strip()).parent)


def open_projects():
    return [s["name"] for s in state()["sessions"] if not s["name"].startswith("_web-")]


def _check_target(sess, target):
    _check_project(target)
    if target == sess or target not in open_projects():
        raise RuntimeError(f"{target} is not open on the board")
```

In `_act`, add before the line `if a in ("save", "comment", "idea") and not NAME_RE.fullmatch(sess):`:

```python
    if a in ("idea_edit", "idea_status", "idea_move", "artifact_move"):
        _check_project(sess)
        key = str(body.get("key") or "")
        if a == "idea_edit":
            ideas.edit(sess, key, body.get("text", ""), body.get("detail", ""))
            return "idea updated"
        if a == "idea_status":
            status = str(body.get("status") or "")
            ideas.set_status(sess, key, status)
            return "idea restored" if status == "open" else "idea dropped"
        target = str(body.get("target") or "")
        _check_target(sess, target)
        if a == "idea_move":
            ideas.move(sess, key, target)
            return f"idea moved to {target}"
        return artifacts.move(sess, str(body.get("path") or ""), target, project_repo(sess), project_repo(target))
```

In `do_POST`, add before `except artifacts.Conflict as e:`:

```python
        except ideas.Stale as e:
            self._json(409, {"ok": False, "message": str(e)})
```

- [ ] **Step 4: Run to verify they pass**

Run: `tmux-ctl run -C <worktree> tests "python3 -m unittest discover -s board/tests -v"`
Expected: all OK.

- [ ] **Step 5: Commit**

```bash
git add board/server.py board/tests/test_ideas_actions.py
git commit -m "feat(board): actions to edit, drop, restore and move ideas and docs"   # end with your harness's attribution trailer
```

```json:metadata
{"files": ["board/server.py", "board/tests/test_ideas_actions.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -v", "acceptanceCriteria": ["session and target validated; target must be an open board project other than the source", "artifact_move passes both main-checkout repo paths", "ideas.Stale maps to HTTP 409, ok false", "action messages as specified"], "modelTier": "mechanical"}
```

---

### Task 4: Board UI — idea and document menus

**Goal:** In `board/index.html`, idea rows and plan/spec rows get the agent-menu (right-click / long-press) with Edit, Drop, Restore and Move to <project>; edit is inline; a "Show dropped" toggle lists dropped ideas.

**Files:**
- Modify: `board/index.html` (ideas box ~L1069-1096, `artButton` ~L895-908, styles ~L241-243)

**Acceptance Criteria:**
- [ ] Each open idea row opens a menu with *Edit*, *Drop*, and one *Move to <p>* per other open project (no submenu: the menu component has none). Rows carry `data-key` = `idea:<key>` so a mid-press rebuild still finds the row.
- [ ] *Edit* replaces the row with an input (text) and textarea (detail) pre-filled; Enter in the input or a *Save* button posts `idea_edit` with the row's `key`; Escape or *Cancel* restores. While any row is being edited, `pollIdeas` does not rebuild the list.
- [ ] A *Show dropped* checkbox under the list (remembered per browser via `localStorage`, wrapped in try/catch) shows dropped ideas dimmed, newest first, moved ones labelled `→ <p>`; their menu has *Restore* (none for moved ones).
- [ ] Artifact rows whose path contains `/docs/superpowers/plans/` or `/docs/superpowers/specs/` and not `/.claude/worktrees/` get a menu with *Move to <p>* per other open project; it posts `artifact_move` with a `confirm()` naming the target ("Move <file> to <p>? It is left uncommitted in both repos.").
- [ ] Every post shows the server's message with `toast(msg, isError)`; a 409 shows "the idea changed since you loaded it" and refreshes the list.
- [ ] Existing behaviour unchanged: the add form, Enter-to-add, the 20-item cap for open ideas, artifact click-to-open.

**Verify:** `python3 -m unittest discover -s board/tests -v` → all OK, then the live checks in Task 5.

**Steps:**

- [ ] **Step 1: Read** `bindAgentMenu`, `openAgentMenu`, `agentMenuItems`, `post`, `action`, `toast`, `artButton`, `renderArtifacts` and `pollIdeas` in `board/index.html` to match their idioms. Open projects for the menus come from the global `data` that `refresh()` sets from `/api/state` (`data.sessions`), names not starting with `_web-`, excluding `session().name`.

- [ ] **Step 2: Idea rows** — in `pollIdeas`, build each row with `data-key="idea:" + i.key`, and `bindAgentMenu(row, () => ideaMenuItems(i))`. Add:

```js
function otherProjects() {
  const me = session().name;
  return (data.sessions || []).map((s) => s.name).filter((n) => n !== me && !n.startsWith("_web-"));
}
function ideaMenuItems(i) {
  const s = session().name;
  if (i.status === "dropped") return i.moved_to ? [] : [{ label: "Restore", run: () => ideaPost({ action: "idea_status", session: s, key: i.key, status: "open" }) }];
  return [
    { label: "Edit", run: () => editIdea(i) },
    { label: "Drop", danger: true, run: () => ideaPost({ action: "idea_status", session: s, key: i.key, status: "dropped" }) },
    ...otherProjects().map((p) => ({ label: `Move to ${p}`, run: () => ideaPost({ action: "idea_move", session: s, key: i.key, target: p }) })),
  ];
}
async function ideaPost(body) {
  const { status, j } = await post(body);
  toast(j.message || (status === 200 ? "Done" : "Failed"), status !== 200);
  pollIdeas();
}
```


- [ ] **Step 3: Inline edit** — `editIdea(i)` sets a module-level `ideaEditing = i.key`, replaces the row's children with an input (value `i.text`), a textarea (value `i.detail`), *Save* and *Cancel* buttons; Enter in the input or *Save* → `post({action: "idea_edit", session, key: i.key, text, detail})`, then `ideaEditing = null` and `ideaPost`-style toast + `pollIdeas()`; Escape or *Cancel* → `ideaEditing = null; pollIdeas()`. At the top of the list rebuild in `pollIdeas`: `if (ideaEditing) return;` (after updating the header count).

- [ ] **Step 4: Show dropped** — a checkbox labelled *Show dropped* after the list, built once with the form; state in `localStorage` key `dash.ideas.dropped` (try/catch on read and write). When on, append dropped ideas (`d.ideas.filter(i => i.status === "dropped").reverse()`) as rows with class `idea dropped`; the small line shows `ts` plus `→ <moved_to>` for moved ones. CSS: `.idea.dropped { opacity: .55; }`.

- [ ] **Step 5: Document rows** — in `artButton`, when `it.path` matches `/\/docs\/superpowers\/(plans|specs)\//` and not `/\/\.claude\/worktrees\//`, set `b.dataset.key = "art:" + it.path` and `bindAgentMenu(b, () => otherProjects().map((p) => ({ label: `Move to ${p}`, run: () => moveDoc(it.path, p) })))`. `moveDoc` confirms (text in the acceptance criteria), posts `artifact_move`, toasts the message, and calls `pollArtifacts()`.

- [ ] **Step 6: Run the suite** — `tmux-ctl run -C <worktree> tests "python3 -m unittest discover -s board/tests -v"` → all OK; also open the file in the worktree server per Task 5's setup if you want an early look.

- [ ] **Step 7: Commit**

```bash
git add board/index.html
git commit -m "feat(board): idea and document menus — edit, drop, restore, move"   # end with your harness's attribution trailer
```

```json:metadata
{"files": ["board/index.html"], "verifyCommand": "python3 -m unittest discover -s board/tests -v", "acceptanceCriteria": ["open idea rows: Edit, Drop, Move to <p> per other open project; data-key idea:<key>", "inline edit posts idea_edit; poll does not rebuild while editing", "Show dropped toggle (localStorage, try/catch); Restore for dropped not moved", "plan/spec rows outside worktrees: Move to <p> with confirm, posts artifact_move", "messages toasted; 409 refreshes list", "existing ideas add form and artifact open unchanged"], "modelTier": "standard"}
```

---

### Task 5: Live check on a scratch board with aged real ideas

**Goal:** The worktree's board, run against a scratch tmux server and a copy of the user's real ideas file, does every new operation end to end in a browser, and the user's live board and ideas are untouched.

**Files:**
- none committed (scratch dirs only); results go into the task report.

**Acceptance Criteria:**
- [ ] Setup: a scratch tmux server (`~/.local/bin/tmux -L ideas-e2e -f /dev/null`) with sessions `pa` and `pb`, each in its own scratch git repo; `pa`'s repo has `docs/superpowers/plans/2026-10-17-demo.md` + `.tasks.json` registered in a scratch `TC_STATE` manifest; scratch `TC_IDEAS_DIR` holds `pa.md` = a copy of the real `~/.claude/ideas/agent-board.md` (aged, multi-day, with detail lines and `[x]` entries) with the header changed to `# Ideas: pa`.
- [ ] The worktree server runs as `TMUX_DASH_TOKEN=e2e TMUX_DASH_PORT=7710 TMUX_DASH_TMUX_ARGS='-L ideas-e2e -f /dev/null' TC_STATE=… TC_IDEAS_DIR=… python3 <worktree>/board/server.py`, and the page at `http://127.0.0.1:7710/e2e/` loads with project `pa` selected.
- [ ] In the browser: edit an idea that has a detail line, drop one, toggle *Show dropped*, restore it, move one to `pb`, move the demo plan to `pb` — after each, the file on disk shows the expected line (`diff` of `pa.md` against the copy shows only those lines changed; `pb.md` has the moved idea with its original timestamp; `pb`'s repo has the plan and sidecar, `git -C <pb repo> status --short` shows them untracked, `git -C <pa repo> status --short` shows the deletion, no new commits in either).
- [ ] Real state untouched (read-only checks): `sha256sum ~/.claude/ideas/agent-board.md` is the same before and after; the live board at port 7700 still answers `/api/state` with 200.
- [ ] Teardown: worktree server stopped by its PID, scratch tmux server killed with `~/.local/bin/tmux -L ideas-e2e kill-server`, scratch dirs removed.

**Verify:** the commands and outputs above, captured in the report; plus `python3 -m unittest discover -s board/tests -v` → all OK and `zsh tools/tests/run-all.zsh` → ALL PASS in the worktree.

```json:metadata
{"files": [], "verifyCommand": "python3 -m unittest discover -s board/tests -v && zsh tools/tests/run-all.zsh", "acceptanceCriteria": ["scratch tmux server + two scratch repos + aged copy of the real ideas file", "worktree server on 7710 loads with project pa", "browser: edit, drop, show dropped, restore, move idea, move plan; disk state matches after each; no commits", "real ideas file sha unchanged; live board 7700 /api/state 200", "teardown by PID and kill-server on the scratch socket"], "modelTier": "standard"}
```
