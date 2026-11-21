"""scout_draft: draft() in a scratch git repo with a `main` branch and a fake claude. Real git, never the real claude.
Scratch TC_SCOUT_DIR, TC_STATE, HOME; every test checks the scratch repo's main checkout is untouched."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import scout_draft as sd  # noqa: E402
import scout_post  # noqa: E402

WEEK = "2026-11-15"
KEY = "abcdef0123456789:hooks"
OK = {"result": "done", "is_error": False, "total_cost_usd": 1.5, "usage": {"output_tokens": 9}, "duration_ms": 2500}
LIMIT = {"result": "Claude usage limit reached. Resets 3pm", "is_error": True}
SPEC = """# Hook replay — design

Proposed by: scout · Source: http://x/i1 (2026-11-14)

## Problem
Hooks are lost. See `board/server.py:1` and `README.md`, with the specs in `docs/superpowers/specs/`.

## Decisions
- Replay on start (*proposed, not approved*)

## Design
```
`board/not-checked-in-a-fence.py`
```
## Error handling
## Testing
## Out of scope
"""

# The fake claude: call n reads step n of plan.json (the last step repeats), records argv, cwd and stdin, then acts.
FAKE = """#!{py}
import json, os, sys, time
d = {d!r}
n = len([f for f in os.listdir(d) if f.startswith("argv-")])
json.dump(sys.argv[1:], open(os.path.join(d, "argv-%d.json" % n), "w"))
open(os.path.join(d, "cwd-%d.txt" % n), "w").write(os.getcwd())
open(os.path.join(d, "stdin-%d.txt" % n), "w").write(sys.stdin.read())
plan = json.load(open(os.path.join(d, "plan.json")))
step = plan[min(n, len(plan) - 1)]
for rel, text in (step.get("write") or {{}}).items():
    os.makedirs(os.path.dirname(rel) or ".", exist_ok=True)
    open(rel, "w").write(text)
time.sleep(step.get("sleep", 0))
sys.stderr.write(step.get("stderr", ""))
if "envelope" in step:
    print(json.dumps(step["envelope"]))
sys.exit(step.get("exit", 0))
"""


def git(cwd, *args):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if p.returncode:
        raise AssertionError(f"git {args}: {p.stderr}")
    return p.stdout.strip()


def pick(**kw):
    d = {"item": "abcdef0123456789", "component": "Hooks", "what_it_enables": "replay lost hooks", "value": "high", "effort": "S",
         "risk": "double delivery", "overlaps": [], "evidence": [{"url": "http://x/i1", "quote": "hooks can be replayed"}],
         "key": KEY, "url": "http://x/i1", "published": "2026-11-14"}
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name).resolve()
        env = {"TC_SCOUT_DIR": str(self.t / "scout"), "TC_STATE": str(self.t / "state"), "HOME": str(self.t / "home")}
        (self.t / "home").mkdir()
        self.fk = self.t / "fake"
        self.fk.mkdir()
        fake = self.fk / "claude"
        fake.write_text(FAKE.format(py=sys.executable, d=str(self.fk)))
        fake.chmod(0o755)
        env["TC_SCOUT_CLAUDE"] = str(fake)          # set before anything runs: the real claude is never reachable
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            os.environ.pop(k, None)
        self.root = self.t / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "t")
        git(self.root, "config", "user.email", "t@example.invalid")
        for rel, text in {".gitignore": ".claude/worktrees/\n", "README.md": "readme\n", "board/server.py": "x = 1\n",
                          "bin/tmux-ctl": "#!/bin/sh\n", "claude/orchestrator.md": "rules\n",
                          "docs/superpowers/model-routing.json": '{"frontier": "fable"}\n',
                          "docs/superpowers/specs/2026-11-01-old-design.md": "# Old\n"}.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        self.wt = self.root / ".claude" / "worktrees" / f"scout-{WEEK}"
        self.before = self.snapshot()
        self.addCleanup(self.assert_main_untouched)

    def snapshot(self):
        files = {}
        for f in sorted(self.root.rglob("*")):
            rel = f.relative_to(self.root)
            if f.is_file() and rel.parts[0] != ".git" and rel.parts[:2] != (".claude", "worktrees"):
                files[str(rel)] = hashlib.sha1(f.read_bytes()).hexdigest()
        return {"head": git(self.root, "rev-parse", "main"), "branch": git(self.root, "rev-parse", "--abbrev-ref", "HEAD"),
                "status": git(self.root, "status", "--porcelain"), "files": files,
                "index": hashlib.sha1((self.root / ".git" / "index").read_bytes()).hexdigest()}

    def assert_main_untouched(self):
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(self.before["status"], "")
        self.assertEqual(self.before["branch"], "main")

    def plan(self, *steps):
        (self.fk / "plan.json").write_text(json.dumps(list(steps)))

    def writes(self, text=SPEC, name=f"{WEEK}-hook-replay-design.md", **more):
        return {"write": dict({f"docs/superpowers/specs/{name}": text}, **more), "envelope": OK}

    def calls(self):
        return [json.loads(f.read_text()) for f in sorted(self.fk.glob("argv-*.json"))]

    def log(self):
        f = self.t / "scout" / "weekly.log"
        return f.read_text() if f.exists() else ""

    def branch_log(self, fmt="%s"):
        return git(self.root, "log", f"--format={fmt}", f"scout/{WEEK}").splitlines()


class KeptDraftTest(Base):
    def test_draft_record(self):
        self.plan(self.writes())
        info = {}
        d = sd.draft(self.root, WEEK, pick(), info=info)
        path = f"docs/superpowers/specs/{WEEK}-hook-replay-design.md"
        want = {"id": scout_post.draft_id(KEY), "key": KEY, "title": "Hook replay", "slug": "hook-replay", "path": path,
                "branch": f"scout/{WEEK}", "worktree": str(self.wt), "week": WEEK, "status": "pending", "why": "replay lost hooks",
                "what_it_enables": "replay lost hooks", "value": "high", "effort": "S", "risk": "double delivery",
                "url": "http://x/i1", "published": "2026-11-14", "evidence": [{"url": "http://x/i1", "quote": "hooks can be replayed"}],
                "protected": False, "post_key": f"scout-agent-board-{WEEK}", "note": None, "reason": None,
                "decided_at": None, "decided_by": None}
        self.assertRegex(d.pop("created_at"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.maxDiff = None
        self.assertEqual(d, want)
        self.assertEqual(info, {"cost_usd": 1.5, "usage": {"output_tokens": 9}, "model_s": 2.5, "model": "fable"})
        self.assertEqual((self.wt / path).read_text(), SPEC)

    def test_commit_has_trailer_and_only_the_spec(self):
        # the model also edits a tracked file and adds a stray one: neither is committed, both are gone afterwards
        self.plan(self.writes(**{"README.md": "hacked\n", "notes/stray.txt": "x\n"}))
        d = sd.draft(self.root, WEEK, pick())
        body = git(self.root, "log", "-1", "--format=%B", f"scout/{WEEK}")
        self.assertEqual(body.splitlines()[0], "docs(spec): Hook replay (scout draft)")
        self.assertIn(f"Scout-Item: {KEY}", body.splitlines())
        self.assertEqual(git(self.root, "log", "-1", "--format=%(trailers:key=Scout-Item,valueonly)", f"scout/{WEEK}"), KEY)
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", f"scout/{WEEK}"), d["path"])
        self.assertEqual(git(self.root, "rev-parse", f"scout/{WEEK}~1"), self.before["head"])
        self.assertEqual(git(self.wt, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual((self.wt / "README.md").read_text(), "readme\n")

    def test_argv_cwd_and_prompt(self):
        self.plan(self.writes())
        sd.draft(self.root, WEEK, pick())
        (argv,) = self.calls()
        self.assertEqual(argv, ["-p", "--model", "fable", "--permission-mode", "acceptEdits", "--strict-mcp-config",
                                "--disable-slash-commands", "--no-session-persistence", "--output-format", "json",
                                "--allowedTools", "Read,Grep,Glob,Write,Edit"])
        self.assertEqual(Path((self.fk / "cwd-0.txt").read_text()).resolve(), self.wt)
        prompt = (self.fk / "stdin-0.txt").read_text()
        for s in ("Proposed by: scout · Source: http://x/i1 (2026-11-14)", f"docs/superpowers/specs/{WEEK}-<slug>-design.md",
                  "proposed, not approved", "## Problem", "## Decisions", "## Design", "## Error handling", "## Testing",
                  "## Out of scope", "replay lost hooks", "hooks can be replayed"):
            self.assertIn(s, prompt)
        self.assertNotIn("Revision", prompt)

    def test_frontier_model_comes_from_the_roots_routing_file(self):
        self.assertEqual(sd.frontier_model(self.root), "fable")
        self.assertEqual(sd.frontier_model(self.t / "nowhere"), "opus")

    def test_second_draft_reuses_the_worktree(self):
        self.plan(self.writes(), self.writes(SPEC.replace("Hook replay", "Second"), f"{WEEK}-second-design.md"))
        a = sd.draft(self.root, WEEK, pick())
        b = sd.draft(self.root, WEEK, pick(key="ffff:statusline"))
        self.assertEqual((a["slug"], b["slug"], b["title"], b["worktree"]), ("hook-replay", "second", "Second", str(self.wt)))
        self.assertEqual(self.branch_log(), ["docs(spec): Second (scout draft)", "docs(spec): Hook replay (scout draft)", "init"])
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", f"scout/{WEEK}"), b["path"])

    def test_worktree_is_recreated_from_the_branch_when_its_dir_is_gone(self):
        self.plan(self.writes(), self.writes(SPEC.replace("Hook replay", "Second"), f"{WEEK}-second-design.md"))
        sd.draft(self.root, WEEK, pick())
        git(self.root, "worktree", "remove", "--force", str(self.wt))
        b = sd.draft(self.root, WEEK, pick(key="ffff:statusline"))
        self.assertEqual(b["title"], "Second")
        self.assertEqual(len(self.branch_log()), 3)

    def test_more_than_one_new_spec_keeps_the_first_by_name(self):
        self.plan(self.writes(**{f"docs/superpowers/specs/{WEEK}-zz-design.md": "# Z\n"}))
        d = sd.draft(self.root, WEEK, pick())
        self.assertEqual(d["slug"], "hook-replay")
        self.assertFalse((self.wt / f"docs/superpowers/specs/{WEEK}-zz-design.md").exists())

    def test_bad_week_is_refused_before_any_git_call(self):
        for week in ("../x", "2026-11-15/..", "", "main"):
            with self.assertRaises(ValueError):
                sd.draft(self.root, week, pick())
        self.assertEqual(self.calls(), [])


class DroppedTest(Base):
    def dropped(self, why, title="replay lost hooks", **kw):
        d = sd.draft(self.root, WEEK, pick(), **kw)
        self.assertEqual(d, {"id": scout_post.draft_id(KEY), "title": title, "why": why})
        return d

    def assert_nothing_committed(self):
        self.assertEqual(self.branch_log(), ["init"])
        self.assertEqual(git(self.wt, "status", "--porcelain", "--untracked-files=all"), "")

    def test_no_spec_written(self):
        self.plan({"envelope": OK})
        self.dropped("no spec written")
        self.assert_nothing_committed()

    def test_spec_for_another_week_is_no_spec(self):
        self.plan(self.writes(name="2026-11-08-hook-replay-design.md"))
        self.dropped("no spec written")
        self.assert_nothing_committed()

    def test_cites_missing_path(self):
        self.plan(self.writes(SPEC + "\nAlso `board/nope.py`.\n"))
        self.dropped("cites missing board/nope.py", title="Hook replay")
        self.assertFalse((self.wt / f"docs/superpowers/specs/{WEEK}-hook-replay-design.md").exists())
        self.assert_nothing_committed()

    def test_a_file_the_model_created_does_not_satisfy_the_citation(self):
        self.plan(self.writes(SPEC + "\nAlso `board/nope.py`.\n", **{"board/nope.py": "x\n"}))
        self.dropped("cites missing board/nope.py", title="Hook replay")
        self.assertFalse((self.wt / "board/nope.py").exists())
        self.assert_nothing_committed()

    def test_missing_citations_by_form(self):
        for cite, missing in (("`nope.json`", "nope.json"), ("`tools/gone/`", "tools/gone/"), ("`docs/x.md:12`", "docs/x.md"),
                              ("`claude/nope-*.md`", "claude/nope-*.md"), ("`bin/nope run`", "bin/nope"),
                              ("`/etc/hosts.json`", "/etc/hosts.json"), ("`../repo/README.md`", "../repo/README.md")):
            with self.subTest(cite=cite):
                self.assertEqual(sd.missing_citation(SPEC + cite, self.root), missing)

    def test_citations_that_pass(self):
        ok = "`board/server.py:3` `board/` `claude/orch*.md` `docs/superpowers/specs/<week>-<slug>-design.md` `x = 1` `tmux-ctl scout`"
        self.assertIsNone(sd.missing_citation(SPEC + ok, self.root))

    def test_worktree_path_that_is_not_a_worktree_is_refused(self):
        # a plain directory there would make `git -C` act on the main checkout
        self.wt.mkdir(parents=True)
        self.plan(self.writes())
        d = sd.draft(self.root, WEEK, pick())
        self.assertEqual((d["id"], d["why"]), (scout_post.draft_id(KEY), f"worktree not on scout/{WEEK}"))
        self.assertEqual(self.calls(), [])
        self.assertEqual(git(self.root, "branch", "--list", "scout/*"), "")

    def test_plain_dir_is_refused_even_when_the_root_is_on_the_scout_branch(self):
        # the branch check alone would pass here: `git -C <plain dir>` answers for the root checkout
        git(self.root, "checkout", "-q", "-b", f"scout/{WEEK}")
        self.before = self.snapshot()
        self.addCleanup(lambda: setattr(self, "before", dict(self.before, branch="main")))   # runs before the main check
        self.wt.mkdir(parents=True)
        self.plan(self.writes())
        self.assertEqual(sd.draft(self.root, WEEK, pick())["why"], f"worktree not on scout/{WEEK}")
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.snapshot(), self.before)
        git(self.root, "checkout", "-q", "main")

    def test_worktree_on_another_branch_is_refused(self):
        git(self.root, "worktree", "add", "-q", "-b", "other", str(self.wt), "main")
        self.plan(self.writes())
        self.assertEqual(sd.draft(self.root, WEEK, pick())["why"], f"worktree not on scout/{WEEK}")
        self.assertEqual(self.calls(), [])
        self.assertEqual(git(self.root, "log", "--format=%s", "other").splitlines(), ["init"])


class ProtectedTest(Base):
    def test_spec_naming_a_protected_path_is_flagged(self):
        self.plan(self.writes(SPEC + "\nChange `claude/orchestrator.md`.\n"))
        self.assertIs(sd.draft(self.root, WEEK, pick())["protected"], True)

    def test_protected_forms(self):
        for cite in ("`claude/worker.md`", "`claude/scout-draft.md`", "`board/scout_draft.py`", "`board/scout.py:12`",
                     "`bin/tmux-ctl scout weekly`", "`claude/scout-*.md`"):
            with self.subTest(cite=cite):
                self.assertTrue(sd.is_protected("see " + cite))
        for cite in ("claude/orchestrator.md without backticks", "`claude/scouting.md`", "`board/server.py`", "`bin/tmux-ctl-x`",
                     "`tmux-ctl`"):
            with self.subTest(cite=cite):
                self.assertFalse(sd.is_protected("see " + cite))


class ModelFailureTest(Base):
    def models(self):
        return [a[a.index("--model") + 1] for a in self.calls()]

    def test_limit_envelope_reruns_once_on_opus(self):
        # the limited run leaves a half-written spec behind: the rerun starts from a clean worktree
        self.plan({"write": {f"docs/superpowers/specs/{WEEK}-half-design.md": "# Half\n"}, "envelope": LIMIT, "exit": 1}, self.writes())
        info = {}
        d = sd.draft(self.root, WEEK, pick(), info=info)
        self.assertEqual((d["status"], d["slug"], info["model"]), ("pending", "hook-replay", "opus"))
        self.assertEqual(self.models(), ["fable", "opus"])
        self.assertRegex(self.log(), rf"(?m)^\d{{4}}-\d\d-\d\dT\d\d:\d\d:\d\d draft {d['id']}: fable limit, retried on opus$")
        self.assertEqual(len(self.log().splitlines()), 1)
        self.assertFalse((self.wt / f"docs/superpowers/specs/{WEEK}-half-design.md").exists())

    def test_limit_on_stderr_with_exit_code_reruns_on_opus(self):
        self.plan({"stderr": "API Error: 529 Overloaded\n", "exit": 1}, self.writes())
        self.assertEqual(sd.draft(self.root, WEEK, pick())["status"], "pending")
        self.assertEqual(self.models(), ["fable", "opus"])

    def test_limit_on_opus_too_is_dropped(self):
        self.plan({"envelope": LIMIT})
        self.assertEqual(sd.draft(self.root, WEEK, pick())["why"], "model limit")
        self.assertEqual(self.models(), ["fable", "opus"])

    def test_other_failures_drop_without_a_rerun(self):
        for step, why in (({"exit": 3, "stderr": "boom\n"}, "model exit 3"),
                          ({"envelope": {"result": "I could not do it", "is_error": True}}, "model error"),
                          ({"stderr": "rate limit\n"}, "model error"),          # exit 0, no envelope: not a limit
                          ({"envelope": dict(OK, result="the docs mention a rate limit")}, "no spec written")):
            with self.subTest(why=why):
                for f in self.fk.glob("argv-*.json"):
                    f.unlink()
                self.plan(dict(step, write={f"docs/superpowers/specs/{WEEK}-half-design.md": "# Half\n"}) if "exit" in step else step)
                self.assertEqual(sd.draft(self.root, WEEK, pick())["why"], why)
                self.assertEqual(self.models(), ["fable"])
                self.assertEqual(self.log(), "")
                self.assertEqual(self.branch_log(), ["init"])
                self.assertEqual(git(self.wt, "status", "--porcelain", "--untracked-files=all"), "")

    def test_cap_reached_is_dropped(self):
        self.plan(dict(self.writes(), sleep=30))
        with mock.patch.object(sd, "DRAFT_TIMEOUT", 1):
            self.assertEqual(sd.draft(self.root, WEEK, pick())["why"], "model timeout")
        self.assertEqual(self.models(), ["fable"])
        self.assertEqual(self.branch_log(), ["init"])
        self.assertEqual(git(self.wt, "status", "--porcelain", "--untracked-files=all"), "")

    def test_cap_is_twenty_minutes(self):
        self.assertEqual(sd.DRAFT_TIMEOUT, 1200)

    def test_missing_binary_is_dropped(self):
        os.environ["TC_SCOUT_CLAUDE"] = str(self.t / "no-such-binary")
        self.assertEqual(sd.draft(self.root, WEEK, pick())["why"], "model error")


class RevisionTest(Base):
    def first(self):
        self.plan(self.writes())
        return sd.draft(self.root, WEEK, pick())

    def test_revision_rewrites_the_previous_draft(self):
        old = self.first()
        self.plan(self.writes(SPEC.replace("Hook replay", "Hook replay two")))
        new = sd.draft(self.root, WEEK, dict(old, status="revise"), note="make it smaller", prev=old["path"])
        self.assertEqual((new["id"], new["path"], new["title"], new["status"], new["note"]),
                         (old["id"] + "-r1", old["path"], "Hook replay two", "pending", None))
        self.assertEqual(new["key"], KEY)
        prompt = (self.fk / "stdin-1.txt").read_text()
        for s in ("Revision", "make it smaller", old["path"], "# Hook replay — design"):
            self.assertIn(s, prompt)
        self.assertEqual(self.branch_log()[0], "docs(spec): Hook replay two (scout draft)")
        self.assertIn(f"Scout-Item: {KEY}", git(self.root, "log", "-1", "--format=%B", f"scout/{WEEK}"))

    def test_revision_may_write_a_new_file_and_counts_up(self):
        old = dict(self.first(), id=scout_post.draft_id(KEY) + "-r2")
        self.plan(self.writes(SPEC, f"{WEEK}-smaller-design.md"))
        new = sd.draft(self.root, WEEK, old, note=None, prev=old["path"])
        self.assertEqual((new["id"], new["slug"]), (scout_post.draft_id(KEY) + "-r3", "smaller"))
        self.assertIn("gave no note", (self.fk / "stdin-1.txt").read_text())

    def test_revision_that_changes_nothing_is_no_spec(self):
        old = self.first()
        self.plan({"envelope": OK})
        d = sd.draft(self.root, WEEK, old, note="x", prev=old["path"])
        self.assertEqual(d, {"id": old["id"] + "-r1", "title": "Hook replay", "why": "no spec written"})
        self.assertEqual(len(self.branch_log()), 2)

    def test_previous_draft_from_an_earlier_weeks_worktree_is_quoted(self):
        old = self.first()
        week2 = "2026-11-22"
        self.plan(self.writes(SPEC, f"{week2}-hook-replay-design.md"))
        new = sd.draft(self.root, week2, old, note="again", prev=old["path"])
        self.assertEqual((new["week"], new["branch"], new["path"]),
                         (week2, f"scout/{week2}", f"docs/superpowers/specs/{week2}-hook-replay-design.md"))
        self.assertIn("# Hook replay — design", (self.fk / "stdin-1.txt").read_text())
        self.assertEqual(git(self.root, "log", "--format=%s", f"scout/{week2}").splitlines(),
                         ["docs(spec): Hook replay (scout draft)", "init"])


if __name__ == "__main__":
    unittest.main()
