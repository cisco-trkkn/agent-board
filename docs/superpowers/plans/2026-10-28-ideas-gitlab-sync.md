# Ideas → GitLab Issues Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every new idea in a mapped project becomes a title-only GitLab issue, and later edits, take-ups, drops, restores and moves update that issue, one way only (local → GitLab).

**Architecture:** `board/ideas.py` gains a `· gl#<iid>` token on idea lines. A new `board/gitlab_sync.py` reconciles a project's ideas file against a last-pushed sidecar through `glab api`. It runs detached after every ideas write and every 60 s from the board server. The board's Ideas box shows the issue link and a sync warning.

**Tech Stack:** Python 3 stdlib (`fcntl`, `subprocess`, `json`), `glab api` (glab 1.121), the board's vanilla JS `index.html`, `unittest`, node (for the page tests).

**Spec:** `docs/superpowers/specs/2026-10-28-ideas-gitlab-sync-design.md`

## Global Constraints

- One way only: nothing reads GitLab state back into the ideas file or the sidecar, except the marker search before a create.
- Issue title = the idea text only. Detail lines are never sent. Label `idea` on create. The description is the marker line only: `<!-- agent-board:<project>:<ts>#<n> -->`, where `n` is the 1-based position among all lines in the file with the same `ts`, in file order, whatever their status (ideas are never deleted, so `n` is stable across edits). The ordinal is needed because ideas share minutes: the real master-gcp-repo file has three at `2026-10-22 17:52`.
- Config `~/.config/agent-board/gitlab.json`: `{"<project>": {"repo": "<group/…/name>", "since": "YYYY-MM-DD"}}`. `TC_GITLAB_CONF` overrides the path. **When `TC_IDEAS_DIR` is set and `TC_GITLAB_CONF` is not, the feature is off.** That is the isolation seam: a redirected ideas dir (every test, every scratch run) can never push to the real tracker.
- Every GitLab call goes through `glab api -i -X <METHOD> <path> -f k=v…` (probe-pinned; see Task 2). Never `glab issue …`: its output is not JSON.
- Capturing an idea never waits on GitLab and never fails because of it.
- Tests never run real `glab` except the one read-only probe in Task 2 and the read-only dry run in Task 5. PATH is pointed at the fake before any RED run.
- Commits: conventional with scope (`feat(board): …`). End every commit message with the attribution trailer your harness specifies. Stage only your own paths (`git add <paths>`). No whole-tree git operations.
- Run the board suite with `tmux-ctl run tests "python3 -m unittest discover -s board/tests"`, never as a long foreground Bash call.

**User decisions (already made):**
- First use is the ideas backlog, not plan sync.
- Issues go to a per-project mapped GitLab repo; unmapped projects stay local.
- Every new idea in a mapped project is pushed automatically; opting in is the consent. No bulk import (the `since` date).
- Status changes **and** text edits are pushed.
- Title only; detail lines stay local.
- Mechanism: reconciler, not inline calls.

---

### Task 1: Issue token on idea lines

**Goal:** `ideas.load()` exposes `issue` (int or None) parsed from a ` · gl#<iid>` token; `edit()` keeps it, `move()` doesn't copy it, and the new `set_issue()` writes it.

**Files:**
- Modify: `board/ideas.py`
- Test: `board/tests/test_ideas_issue.py` (create)

**Acceptance Criteria:**
- [ ] `load()` on `- [ ] 2026-10-28 10:00 · retries · gl#12` gives `text == "retries"`, `issue == 12`, and `key` unchanged (raw, token included).
- [ ] The token is found before a ` → …` suffix (`[x] … → spec`, `[-] … → moved to q`), and a `gl#3` in the middle of the text is not a token.
- [ ] `edit()` keeps the token and strips one the user typed. `move()` gives the target line no token and keeps it on the source.
- [ ] `set_issue(project, key, iid)` appends the token to an open idea, inserts it before the last ` → ` on a closed one, is a no-op for the same iid, and raises `Stale` for a different iid.
- [ ] All `board/tests/test_ideas*.py` tests pass (38 tests, run by the plan author against this exact diff).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_ideas*.py'` → `Ran 38 tests` … `OK`

**Steps:**

- [ ] **Step 1: Write the failing test.** Create `board/tests/test_ideas_issue.py`:

```python
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ideas  # noqa: E402


class IssueTokenTest(unittest.TestCase):
    """' · gl#<iid>' on an idea line: parsed into "issue", kept by edit, dropped by move, written by set_issue."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("TC_IDEAS_DIR")
        os.environ["TC_IDEAS_DIR"] = self.tmp.name
        self.f = Path(self.tmp.name) / "p.md"

    def tearDown(self):
        if self.old is None:
            os.environ.pop("TC_IDEAS_DIR", None)
        else:
            os.environ["TC_IDEAS_DIR"] = self.old
        self.tmp.cleanup()

    def write(self, *lines):
        self.f.write_text("# Ideas: p\n\n" + "".join(l + "\n" for l in lines))

    def test_token_is_parsed_out_of_text(self):
        # mutation: drop the _split_issue call in load() -> text keeps ' · gl#12', issue missing
        self.write("- [ ] 2026-10-28 10:00 · retries · gl#12")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"]), ("retries", 12))
        self.assertEqual(i["key"], "2026-10-28 10:00 · retries · gl#12")

    def test_token_before_spec_suffix(self):
        self.write("- [x] 2026-10-28 10:00 · retries · gl#12 → docs/s.md")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"]), ("retries → docs/s.md", 12))

    def test_token_before_moved_suffix(self):
        self.write("- [-] 2026-10-28 10:00 · retries · gl#12 → moved to q")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"], i["moved_to"]), ("retries", 12, "q"))

    def test_gl_in_the_middle_is_text(self):
        # mutation: drop the (?= → |$) lookahead in ISSUE_RE -> issue == 3
        self.write("- [ ] 2026-10-28 10:00 · see · gl#3 for context")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"]), ("see · gl#3 for context", None))

    def test_no_token_issue_none(self):
        self.write("- [ ] 2026-10-28 10:00 · plain")
        self.assertIsNone(ideas.load("p")[0]["issue"])

    def test_edit_keeps_token(self):
        # mutation: return f"- [ ] {ts} · {text}" without the token in edit() -> issue None after edit
        self.write("- [ ] 2026-10-28 10:00 · retries · gl#12")
        ideas.edit("p", "2026-10-28 10:00 · retries · gl#12", "retries with backoff")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"]), ("retries with backoff", 12))

    def test_edit_cannot_type_a_token(self):
        self.write("- [ ] 2026-10-28 10:00 · retries")
        ideas.edit("p", "2026-10-28 10:00 · retries", "retries · gl#99")
        self.assertIsNone(ideas.load("p")[0]["issue"])

    def test_move_drops_token_on_target_keeps_on_source(self):
        self.write("- [ ] 2026-10-28 10:00 · retries · gl#12")
        ideas.move("p", "2026-10-28 10:00 · retries · gl#12", "q")
        [t] = ideas.load("q")
        self.assertEqual((t["text"], t["issue"]), ("retries", None))
        [s] = ideas.load("p")
        self.assertEqual((s["status"], s["issue"], s["moved_to"]), ("dropped", 12, "q"))

    def test_set_issue_open_appends(self):
        self.write("- [ ] 2026-10-28 10:00 · retries", "  detail")
        ideas.set_issue("p", "2026-10-28 10:00 · retries", 7)
        self.assertIn("- [ ] 2026-10-28 10:00 · retries · gl#7\n  detail\n", self.f.read_text())

    def test_set_issue_closed_goes_before_suffix(self):
        self.write("- [x] 2026-10-28 10:00 · a → b → docs/s.md")
        ideas.set_issue("p", "2026-10-28 10:00 · a → b → docs/s.md", 7)
        self.assertIn("· a → b · gl#7 → docs/s.md\n", self.f.read_text())

    def test_set_issue_same_iid_is_noop_other_iid_is_stale(self):
        # mutation: drop the `have != iid` check -> a second token is appended
        self.write("- [ ] 2026-10-28 10:00 · retries · gl#7")
        ideas.set_issue("p", "2026-10-28 10:00 · retries · gl#7", 7)
        self.assertEqual(self.f.read_text().count("gl#"), 1)
        with self.assertRaises(ideas.Stale):
            ideas.set_issue("p", "2026-10-28 10:00 · retries · gl#7", 8)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it, expect RED.** `python3 -m unittest discover -s board/tests -p test_ideas_issue.py 2>&1 | tail -3`. Expected: `FAILED (errors=11)`, with `AttributeError`/`KeyError: 'issue'`/`set_issue` errors. Then run one named mutation after Step 3 and report that it fails: drop the `(?= → |$)` lookahead from `ISSUE_RE` → `test_gl_in_the_middle_is_text` fails.

- [ ] **Step 3: Implement.** Apply this patch (generated from a tested copy; `patch -p0 < file` from the repo root, or make the same edits by hand):

```diff
--- board/ideas.py
+++ board/ideas.py
@@ -23,6 +23,7 @@
 LINE_RE = re.compile(r"^- \[( |x|-)\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (.*)$")
 STATUS = {" ": "open", "x": "taken", "-": "dropped"}
 MOVED_RE = re.compile(r" → moved to ([A-Za-z0-9_-][A-Za-z0-9._-]*)$")
+ISSUE_RE = re.compile(r" · gl#(\d+)(?= → |$)")   # the GitLab issue token gitlab_sync.py writes
 
 
 class Stale(ValueError):
@@ -69,6 +70,12 @@
             f.write(entry)
 
 
+def _split_issue(text):
+    """'a · gl#12 → b' -> ('a → b', 12); text without the token -> (text, None)."""
+    m = ISSUE_RE.search(text)
+    return (text[:m.start()] + text[m.end():], int(m[1])) if m else (text, None)
+
+
 def _clean_detail(detail):
     return [l.strip() for l in str(detail).splitlines() if l.strip()]
 
@@ -110,7 +117,7 @@
 
 
 def edit(project, key, text, detail=""):
-    text = " ".join(str(text).split())
+    text = _split_issue(" ".join(str(text).split()))[0]
     if not text:
         raise ValueError("empty idea")
     new_detail = _clean_detail(detail)
@@ -118,7 +125,8 @@
     def change(box, ts, raw, old):
         if box != " ":
             raise ValueError("only open ideas can be edited")
-        return f"- [ ] {ts} · {text}", new_detail
+        iid = _split_issue(raw)[1]
+        return f"- [ ] {ts} · {text}" + (f" · gl#{iid}" if iid else ""), new_detail
     return _rewrite(project, key, change)[6:]
 
 
@@ -157,6 +165,21 @@
     return _rewrite(project, key, change)
 
 
+def set_issue(project, key, iid):
+    """Record GitLab issue #iid on the idea: the token goes before a ' → …' suffix on a closed idea,
+    at the end of an open one. Called by gitlab_sync only; it never triggers a sync."""
+    def change(box, ts, raw, detail):
+        have = _split_issue(raw)[1]
+        if have is not None and have != iid:
+            raise Stale(f"the idea already has issue #{have}")
+        if have == iid:
+            return f"- [{box}] {ts} · {raw}", detail
+        cut = raw.rfind(" → ") if box != " " else -1
+        raw = raw[:cut] + f" · gl#{iid}" + raw[cut:] if cut >= 0 else raw + f" · gl#{iid}"
+        return f"- [{box}] {ts} · {raw}", detail
+    return _rewrite(project, key, change)
+
+
 def load(project):
     p = ideas_path(project)
     if not p.exists():
@@ -169,7 +192,8 @@
         m = LINE_RE.match(line)
         if m:
             mv = MOVED_RE.search(m[3]) if m[1] == "-" else None
-            out.append({"status": STATUS[m[1]], "ts": m[2], "text": m[3][:mv.start()] if mv else m[3],
+            text, iid = _split_issue(m[3][:mv.start()] if mv else m[3])
+            out.append({"status": STATUS[m[1]], "ts": m[2], "text": text, "issue": iid,
                         "detail": "", "key": f"{m[2]} · {m[3]}", "moved_to": mv[1] if mv else ""})
         elif out and line.startswith("  ") and line.strip():
             d = out[-1]["detail"]
```

Also add one line to the module docstring after the "[x] = taken up…" sentence: `An idea pushed to GitLab carries " · gl#<iid>" before any " → …" suffix (see gitlab_sync.py).`

- [ ] **Step 4: Run GREEN.** The Verify command → `Ran 38 tests … OK`.

- [ ] **Step 5: Commit.** `git add board/ideas.py board/tests/test_ideas_issue.py && git commit -m "feat(board): gl#<iid> issue token on idea lines"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["board/ideas.py", "board/tests/test_ideas_issue.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_ideas*.py'", "acceptanceCriteria": ["load() parses gl#<iid> into issue, key unchanged", "token found before → suffix, gl# mid-text not a token", "edit keeps/strips token, move drops on target", "set_issue appends/inserts/no-op/Stale", "38 ideas tests pass"], "modelTier": "mechanical"}
```

---

### Task 2: `gitlab_sync.py` — config, glab client and reconciler

**Goal:** `gitlab_sync.sync(project, dry_run=False)` brings a mapped project's GitLab issues in line with its ideas file, and `ideas.py sync --project P [--dry-run]` runs it.

**Files:**
- Create: `board/gitlab_sync.py`
- Modify: `board/ideas.py` (the `sync` subcommand in `main()`; lazy `import gitlab_sync` inside the branch to avoid a cycle)
- Create: `board/tests/fake_glab.py`, `board/tests/test_gitlab_sync.py`
- Add (already captured by the plan author from real `glab api -i`, untracked in the worktree): `board/tests/fixtures/glab/list-empty-200.txt`, `board/tests/fixtures/glab/get-404.txt`

**Acceptance Criteria:**
- [ ] Config: `conf_path()` = `$TC_GITLAB_CONF`; else `None` (off) when `$TC_IDEAS_DIR` is set; else `~/.config/agent-board/gitlab.json`. `mapping(p)` returns `None` when the file is absent or p is unmapped. It raises `ConfigError` for invalid JSON, a missing `repo`, or a missing or non-`YYYY-MM-DD` `since`. `mapped(p)` is True when the file is unreadable as JSON (so sync can record the error) or names p.
- [ ] Client: `api()` and `_parse()` exactly as given below. A non-`HTTP/` stdout, HTTP ≥ 400, a timeout or a missing binary raises `GlabError`. HTTP 429 or `Ratelimit-Remaining: 0` raises `RateLimited`.
- [ ] Reconcile, per idea in file order, with `enc = urllib.parse.quote(repo, safe="")` and `base = f"projects/{enc}/issues"`:
  - **create**: the idea is open, has no token, and `ts[:10] >= since`. Run `GET base` with `search=<marker>`, `in=description`, `state=all`, `per_page=20`, and adopt the first result whose `description` contains the exact marker. Otherwise `POST base` with `title`, `labels=idea` and `description=<marker>`, and read `iid`. Then `ideas.set_issue(project, key, iid)`. On `Stale`, skip; the next pass picks it up. Only after that, write the sidecar entry `{"ts", "title", "state": "open"}`.
  - **retitle**: the idea is open, has a token, and the sidecar title ≠ text. Run `PUT base/<iid>` with `title=<text>`.
  - **taken** `[x]` (the desired state is `closed-done`; the suffix is the part after the last ` → ` in `text`): `PUT base/<iid>` with `state_event=close`, then `POST base/<iid>/notes` with `body=Taken up → <suffix>`.
  - **dropped** `[-]` with no `moved_to` (`closed-dropped`): `PUT base/<iid>` with `state_event=close` and `add_labels=not-planned`.
  - **moved** (`closed-moved`): `PUT base/<iid>` with `state_event=close`, then `POST …/notes` with `body=Moved to <target>`.
  - **restored** (the idea is open, the sidecar state is not `open`): `PUT base/<iid>` with `state_event=reopen` and `remove_labels=not-planned`.
  - **token but no sidecar entry**: assume `{"title": <current title>, "state": "open"}`, then reconcile as above.
  - **no-op**: the sidecar already matches. No call is made.
- [ ] The sidecar `<ideas_dir>/<project>.gitlab.json` is keyed by iid as a string. It is written atomically (tmp + `os.replace`) under `<ideas_dir>/<project>.md.lock` after each issue's calls succeed, and never for a failed one.
- [ ] A `GlabError` on one idea is recorded and the loop continues. `RateLimited` stops the pass. A second concurrent `sync` exits at once on a non-blocking `fcntl` lock on `<ideas_dir>/<project>.md.sync.lock`.
- [ ] After a non-dry pass, the status file `<ideas_dir>/<project>.gitlab-status.json` holds `{"at": <ISO local time>, "ok": bool, "error": <first error or "">, "pending": <ideas whose change was not pushed>}`. A `ConfigError` also writes it (ok false) and the CLI exits 2.
- [ ] Dry run: only `GET` calls. It prints one action line per change (`create "<title>"`, `adopt #N "<title>"`, `retitle #N`, `close-done #N`, `close-dropped #N`, `close-moved #N`, `reopen #N`). It writes no token, no sidecar and no status file.
- [ ] CLI: `ideas.py sync --project P [--dry-run]` prints the actions. It exits 0 when ok or unmapped, 1 if any push failed, and 2 on `ConfigError`.
- [ ] Tests, using the fake `glab` on a temp PATH, with `TC_IDEAS_DIR`, `TC_GITLAB_CONF` and `FAKE_GLAB_DIR` set in `setUp`, cover each bullet above. Each guard test names its mutation:
  - unmapped project → `log.jsonl` absent. Mutation: skip the `mapping()` None check → a GET is logged.
  - an idea before `since` → no create. Mutation: drop the `since` comparison → POST logged.
  - an existing marker hit → adopt, no POST. Mutation: skip the search → POST logged and `iid` differs.
  - a search hit whose description lacks the exact marker → not adopted.
  - a failed POST (rule status 500) → no token, no sidecar entry, status `ok: false`, and the next idea is still processed. Mutation: write the sidecar before the call → entry present.
  - the second pass after success makes zero calls (idempotence). Mutation: compare the title against the stale value → PUT logged.
  - `Stale` from `set_issue` (monkeypatch `ideas.set_issue` to raise `ideas.Stale`) → no sidecar entry, and the next idea is still processed.
  - the sync lock held by the test → `sync` returns at once with no calls.
  - dry run → only GET in the log, and the ideas file bytes, the sidecar and the status file are unchanged. Mutation: let dry run POST → POST logged.
  - `RateLimited` on the first idea → no call for the second.
  - `TC_IDEAS_DIR` set and `TC_GITLAB_CONF` unset → `conf_path()` is None.
- [ ] One real read-only probe, run once and its output pasted into the report: `python3 -I -c "import sys; sys.path.insert(0,'board'); import gitlab_sync as g; print(g.api('GET','projects/trkkn%2Ftrkkn-na%2Fmaster-gcp-repo/issues',[('state','all'),('per_page','1')]))"` → `[]` (or a list), no exception.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_gitlab_sync.py'` → `OK`, then the full board suite through `tmux-ctl run tests "python3 -m unittest discover -s board/tests"` → `OK`

**Steps:**

- [ ] **Step 1: The fake glab.** Create `board/tests/fake_glab.py` exactly as below (run once by the plan author with these results: a `once` POST rule answered `{'iid': 5}` and then fell through to `{}`, a 404 rule raised `GlabError HTTP 404: 404 Not found`, and `remaining: 0` raised `RateLimited`). In tests, write `<tmp>/bin/glab` as `#!/bin/sh\nexec python3 -I <repo>/board/tests/fake_glab.py "$@"\n`, `chmod +x` it, and prepend `<tmp>/bin` to `PATH` in `setUp`, restoring it in `tearDown`.

```python
#!/usr/bin/env python3
"""A stand-in for `glab api -i -X METHOD PATH [-f k=v]...` in tests.

$FAKE_GLAB_DIR/log.jsonl  gets one {"method", "path", "fields"} line per call.
$FAKE_GLAB_DIR/rules.json is a list of {"method", "path_re", "status", "body", "remaining", "once"};
the first rule whose method matches and whose path_re re.search-es the path answers (a "once" rule is
then removed). No match: GET -> 200 [], anything else -> 200 {}. The header block is the real
capture in fixtures/glab/list-empty-200.txt, with the status line and Ratelimit-Remaining replaced.
"""
import json
import os
import re
import sys
from pathlib import Path

d = Path(os.environ["FAKE_GLAB_DIR"])
argv = sys.argv[1:]
if argv[:2] != ["api", "-i"] or argv[2] != "-X":
    print(f"fake glab: unexpected argv {argv}", file=sys.stderr)
    sys.exit(2)
method, path, rest = argv[3], argv[4], argv[5:]
fields = {}
while rest:
    flag, kv, rest = rest[0], rest[1], rest[2:]
    assert flag == "-f", flag
    k, _, v = kv.partition("=")
    fields[k] = v
with open(d / "log.jsonl", "a") as f:
    f.write(json.dumps({"method": method, "path": path, "fields": fields}) + "\n")
rules_f = d / "rules.json"
rules = json.loads(rules_f.read_text()) if rules_f.exists() else []
hit = next((r for r in rules if r.get("method", "GET") == method and re.search(r["path_re"], path)), None)
if hit and hit.get("once"):
    rules.remove(hit)
    rules_f.write_text(json.dumps(rules))
status = hit["status"] if hit else 200
body = hit["body"] if hit else ([] if method == "GET" else {})
remaining = str(hit.get("remaining", 1990)) if hit else "1990"
head = (Path(__file__).resolve().parent / "fixtures" / "glab" / "list-empty-200.txt").read_text()
head = head.replace("\r\n", "\n").partition("\n\n")[0].split("\n")[1:]
head = [l for l in head if not l.lower().startswith(("ratelimit-remaining", "content-length"))]
reason = {200: "OK", 201: "Created", 404: "Not Found", 429: "Too Many Requests", 500: "Internal Server Error"}.get(status, "X")
text = json.dumps(body)
out = f"HTTP/2.0 {status} {reason}\n" + "".join(f"{l}\r\n" for l in head + [f"Ratelimit-Remaining: {remaining}", f"Content-Length: {len(text)}"]) + "\r\n" + text
sys.stdout.write(out)
if status >= 400:
    msg = body.get("message", "error") if isinstance(body, dict) else "error"
    print(f"glab: {msg} (HTTP {status})", file=sys.stderr)
    sys.exit(1)
```

- [ ] **Step 2: The client.** Put these at the top of `board/gitlab_sync.py`. They were run by the plan author against the fake and against real `glab` (`[]` for a list, and `GlabError HTTP 404: 404 Not found` for a missing issue). `subprocess` text mode turns `\r\n` into `\n`; that is why `_parse` normalises first and why the header split is `\n\n`:

```python
import json, subprocess
class GlabError(RuntimeError): pass
class RateLimited(GlabError): pass
def _parse(raw):
    head, _, body = raw.replace("\r\n", "\n").partition("\n\n")
    lines = head.split("\n")
    hdr = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:])}
    return int(lines[0].split()[1]), hdr, (json.loads(body) if body.strip() else None)
def api(method, path, fields=()):
    cmd = ["glab", "api", "-i", "-X", method, path]
    for k, v in fields:
        cmd += ["-f", f"{k}={v}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GlabError(f"glab: {e}") from e
    if not r.stdout.startswith("HTTP/"):
        raise GlabError((r.stderr.strip().splitlines() or [f"glab exited {r.returncode}"])[-1])
    code, hdr, body = _parse(r.stdout)
    if code == 429 or hdr.get("ratelimit-remaining") == "0":
        raise RateLimited(f"rate limited (HTTP {code})")
    if code >= 400:
        raise GlabError(f"HTTP {code}: {body.get('message') if isinstance(body, dict) else body}")
    return body
```

- [ ] **Step 3: Write the tests (RED).** Write `board/tests/test_gitlab_sync.py` covering every Acceptance Criteria bullet, with its rule files and log assertions. Run it, expect failures (`gitlab_sync` has no `sync`), and run the named mutations once GREEN.
- [ ] **Step 4: Config, sidecar, status, lock and reconcile.** Implement them in `gitlab_sync.py` to the criteria, then add the `sync` subcommand to `ideas.py main()`.
- [ ] **Step 5: GREEN.** Run the Verify commands and the real probe.
- [ ] **Step 6: Commit.** `git add board/gitlab_sync.py board/ideas.py board/tests/fake_glab.py board/tests/test_gitlab_sync.py board/tests/fixtures/glab/ && git commit -m "feat(board): gitlab_sync reconciles ideas to GitLab issues"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["board/gitlab_sync.py", "board/ideas.py", "board/tests/fake_glab.py", "board/tests/test_gitlab_sync.py", "board/tests/fixtures/glab/list-empty-200.txt", "board/tests/fixtures/glab/get-404.txt"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_gitlab_sync.py'", "acceptanceCriteria": ["config resolution with the TC_IDEAS_DIR seam and ConfigError cases", "api/_parse as given; GlabError and RateLimited", "create with marker search/adopt, retitle, close-done, close-dropped, close-moved, reopen, no-op", "sidecar written only after success, atomically, under the lock", "per-idea failure continues, rate limit stops, sync lock", "status file", "dry run GET-only, writes nothing", "CLI exit codes 0/1/2", "tests with named mutations", "one real read-only probe"], "modelTier": "standard"}
```

---

### Task 3: Triggers, board API and docs

**Goal:** Every ideas write starts a detached sync for mapped projects, the board server re-syncs mapped projects every 60 s, and `/api/ideas` reports the GitLab link and status.

**Files:**
- Modify: `board/gitlab_sync.py` (`kick(project)`, `board_info(project)`, `mapped_projects()`)
- Modify: `board/ideas.py` (call `_kick` at the end of `add`, `edit`, `set_status`, `move` (both projects); `set_issue` never kicks)
- Modify: `board/server.py` (`/api/ideas` adds `"gitlab"`; a daemon thread started in `__main__` only)
- Modify: `docs/CUSTOMIZATION.md` (a §0 row for `gitlab.json`, a §1 row for `TC_GITLAB_CONF`, and a short "GitLab issues for ideas" subsection giving the file format and the `TC_IDEAS_DIR` seam)
- Test: `board/tests/test_ideas_kick.py` (create), plus an `/api/ideas` case added to `board/tests/test_ideas_actions.py`

**Acceptance Criteria:**
- [ ] `kick(p)`: when `mapped(p)` is true, it runs `subprocess.Popen([sys.executable, "-I", <abs path of ideas.py>, "sync", "--project", p], stdin/stdout/stderr=DEVNULL, start_new_session=True)`. When false, there is no Popen. `ideas._kick` imports lazily and swallows every exception, so capture never fails. Tests patch `gitlab_sync.subprocess.Popen`:
  - mapped `add` → one call whose argv ends `sync --project p`. Mutation: drop the `mapped()` check → the unmapped test sees a call.
  - `move` → two calls (p and q).
  - `set_issue` → no call. Mutation: add `_kick` to `set_issue` → a call is seen.
  - `TC_IDEAS_DIR` set and `TC_GITLAB_CONF` unset → no call, even with a real-looking HOME config.
- [ ] `board_info(p)` → `None` when unmapped. Otherwise `{"repo", "url": "https://gitlab.com/<repo>", "ok", "error"}`, where `ok`/`error` come from the status file (`ok: true`, `error: ""` when there is none yet). A `ConfigError` gives `{"repo": "", "url": "", "ok": false, "error": str(e)}`.
- [ ] `/api/ideas` JSON = `{"ideas", "open", "gitlab": board_info(sess)}`. Each idea already carries `issue` from Task 1.
- [ ] The server thread loops `for p in mapped_projects(): sync(p)` and then sleeps 60 s. Each sync runs in a `try` that logs one line to stderr on error. It starts only in `if __name__ == "__main__":`, so importing `server` in tests starts nothing. A test asserts no thread named `gitlab-sync` is alive after the import. Mutation: start it at import → the test fails.
- [ ] `mapped_projects()` = the config keys that pass `ideas.ideas_path` validation, or `[]` on `ConfigError` or an absent file.
- [ ] The CUSTOMIZATION.md rows and subsection exist. `grep -c gitlab.json docs/CUSTOMIZATION.md` ≥ 2.
- [ ] The full board suite passes.

**Verify:** `tmux-ctl run tests "python3 -m unittest discover -s board/tests"` → `OK`

**Steps:**

- [ ] **Step 1:** Write `test_ideas_kick.py` and the `/api/ideas` case (follow `test_ideas_actions.py`'s server import pattern), then run them RED.
- [ ] **Step 2:** Implement `kick`, `board_info` and `mapped_projects` in `gitlab_sync.py`, then add `_kick` to `ideas.py`:

```python
def _kick(*projects):
    """Start a detached GitLab sync for each mapped project; never fails the write that called it."""
    try:
        import gitlab_sync
        for p in projects:
            gitlab_sync.kick(p)
    except Exception:
        pass
```

Call `_kick(project)` as the last statement before the `return` of `add`, `edit` and `set_status` (store the result in a local first), and `_kick(project, target)` in `move`.
- [ ] **Step 3:** Change the server: `/api/ideas` and the `__main__` thread (`threading.Thread(target=_gitlab_loop, name="gitlab-sync", daemon=True).start()`).
- [ ] **Step 4:** Update the docs. Run GREEN, then the named mutations.
- [ ] **Step 5: Commit.** `git add board/gitlab_sync.py board/ideas.py board/server.py docs/CUSTOMIZATION.md board/tests/test_ideas_kick.py board/tests/test_ideas_actions.py && git commit -m "feat(board): sync ideas to GitLab after each write and every 60s"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["board/gitlab_sync.py", "board/ideas.py", "board/server.py", "docs/CUSTOMIZATION.md", "board/tests/test_ideas_kick.py", "board/tests/test_ideas_actions.py"], "verifyCommand": "tmux-ctl run tests \"python3 -m unittest discover -s board/tests\"", "acceptanceCriteria": ["kick Popens a detached sync only for mapped projects; set_issue never kicks; TC_IDEAS_DIR seam", "board_info shape incl. ConfigError", "/api/ideas carries gitlab", "60s daemon thread only under __main__", "mapped_projects", "CUSTOMIZATION.md documents gitlab.json and TC_GITLAB_CONF", "full board suite OK"], "modelTier": "standard"}
```

---

### Task 4: Ideas box shows the issue link and sync warning

**Goal:** The board's Ideas box shows a `GitLab #N` link on each idea that has an issue, and a one-line `GitLab sync: <error>` warning when the project's sync is failing.

**Files:**
- Modify: `board/index.html` (`pollIdeas`'s `addRow` meta line and the box header area)
- Test: `board/tests/test_ideas_gitlab_ui.py` (create; reuse the node harness pattern of `board/tests/test_ideas_switch.py`, which extracts `pollIdeas` from the page and runs it with stubbed `pollJSON`/`el`/`$`)

**Acceptance Criteria:**
- [ ] An idea with `issue: 12`, when `d.gitlab.url` is set, renders an `<a>` whose text is `GitLab #12`, `href` = `${d.gitlab.url}/-/issues/12`, `target="_blank"` and `rel="noopener"`, inside the row's `<small>` meta line. An idea with `issue: null` renders no link. Mutation: always render the link → the null case fails.
- [ ] `d.gitlab && !d.gitlab.ok` → a `div.ideas-gitlab-warn` with the text `GitLab sync: <error>` appears once in the box. It is gone on the next poll where `ok` is true. Mutation: never remove it → the second-poll assertion fails.
- [ ] `d.gitlab === null` → no link and no warning (an unmapped project looks exactly as it does today).
- [ ] Text is set with `textContent` or `el()`, never `innerHTML` (the error string comes from glab).
- [ ] `test_ideas_switch.py` still passes.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_ideas*ui*.py' && python3 -m unittest discover -s board/tests -p 'test_ideas_switch.py'` → both `OK` (both are skipped only if node is missing; it is at `~/Library/Python/3.14/bin/node`)

**Steps:**

- [ ] **Step 1:** Write the node-driven tests (RED).
- [ ] **Step 2:** Implement it in `index.html`. Add a small CSS rule for `.ideas-gitlab-warn` with the warning colour the page already uses for toasts with `error`.
- [ ] **Step 3:** GREEN, then the named mutations.
- [ ] **Step 4: Commit.** `git add board/index.html board/tests/test_ideas_gitlab_ui.py && git commit -m "feat(board): GitLab issue link and sync warning in the Ideas box"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["board/index.html", "board/tests/test_ideas_gitlab_ui.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_ideas*ui*.py' && python3 -m unittest discover -s board/tests -p 'test_ideas_switch.py'", "acceptanceCriteria": ["GitLab #N link with href url/-/issues/N, target _blank, only when issue set", "warning div appears when ok false and clears when ok true", "unmapped project unchanged", "no innerHTML for glab text", "test_ideas_switch passes"], "modelTier": "standard"}
```

---

### Task 5: Real-state dry run against the live master-gcp-repo inbox

**Goal:** Prove the reconciler against the user's real, aged ideas file and the real GitLab repo, writing nothing: a dry run lists exactly the creates the real data implies.

**Files:**
- Create: `docs/superpowers/plans/2026-10-28-ideas-gitlab-sync-e2e-report.md`

**Acceptance Criteria:**
- [ ] The run reads the real `~/.local/state/agent-board/ideas/master-gcp-repo.md` (TC_IDEAS_DIR **unset**) with a scratch config (`TC_GITLAB_CONF=<scratch>/gitlab.json` mapping `master-gcp-repo` → `trkkn/trkkn-na/master-gcp-repo`, `since` `2026-10-22`). The file has ideas spanning several days, including three in the same minute (`2026-10-22 17:52`).
- [ ] The output has one `create "<title>"` line per open idea dated on or after 2026-10-22 with no token. The expected count is computed independently with `grep -cE '^- \[ \] 2026-10-(2[2-9]|3[01])' <file>` and quoted next to it. The three same-minute ideas produce three distinct creates, not one adopt.
- [ ] Nothing is written: `shasum -a 256` of the ideas file is identical before and after, and `ls <ideas_dir>/master-gcp-repo.gitlab*.json` shows no new files.
- [ ] The report quotes the commands, the full dry-run output (uncapped), both counts and both hashes. It also has a "User gate after merge" section that copies the spec's e2e check: map one project for real, add one idea, see the issue, drop it, and see it closed with `not-planned`.

**Verify:** `test "$(grep -c '^- create' docs/superpowers/plans/2026-10-28-ideas-gitlab-sync-e2e-report.md)" -ge 1 && grep -q 'User gate after merge' docs/superpowers/plans/2026-10-28-ideas-gitlab-sync-e2e-report.md && echo E2E-REPORT-OK` → `E2E-REPORT-OK`

**Steps:**

- [ ] **Step 1:** In the worktree, run `env -u TC_IDEAS_DIR TC_GITLAB_CONF=<scratch>/gitlab.json python3 -I board/ideas.py sync --project master-gcp-repo --dry-run`, taking the hashes before and after.
- [ ] **Step 2:** Write the report, listing each dry-run action as a `- create "…"` bullet. Commit it with `git add docs/superpowers/plans/2026-10-28-ideas-gitlab-sync-e2e-report.md && git commit -m "docs(plan): ideas-gitlab-sync real-state dry run"`, ending with your harness's attribution trailer.

```json:metadata
{"files": ["docs/superpowers/plans/2026-10-28-ideas-gitlab-sync-e2e-report.md"], "verifyCommand": "test \"$(grep -c '^- create' docs/superpowers/plans/2026-10-28-ideas-gitlab-sync-e2e-report.md)\" -ge 1 && grep -q 'User gate after merge' docs/superpowers/plans/2026-10-28-ideas-gitlab-sync-e2e-report.md && echo E2E-REPORT-OK", "acceptanceCriteria": ["dry run on the real master-gcp-repo inbox with TC_IDEAS_DIR unset and a scratch TC_GITLAB_CONF", "create count equals independent grep count; same-minute ideas give distinct creates", "ideas file hash unchanged, no sidecar/status files", "report with uncapped output and the user gate"], "modelTier": "standard"}
```
