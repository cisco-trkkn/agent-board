import contextlib, io, json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics, usage  # noqa: E402
from metrics_fixtures import cache_main_root  # noqa: E402

REPO_ROOT = HERE.parent
SPEC = "docs/superpowers/specs/2026-01-01-thing-design.md"
PLAN = "docs/superpowers/plans/2026-01-02-thing.md"
OPUS = "claude-opus-5-5"
FACTS = {"recall_existing": 1.0, "recall_created": 1.0, "precision": 0.6667, "append_violations": [], "refreshes": 1,
         "stale_paths": 2, "writes": [], "declared": 3, "touched": 2, "both": 2, "missed": []}
WANT_MANIFEST = {"declared": 3, "touched": 2, "both": 2, "precision": 0.6667, "recall": 1.0, "recall_existing": 1.0,
                 "recall_created": 1.0, "append_violations": [], "source": "manifest"}


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


def plan_text(base, with_manifest=True):
    mf = {"spec": SPEC, "base": base, "depends_on": [], "reads": [], "produces": [], "consumes": [], "tests": [],
          "writes": [{"path": "old.txt", "mode": "modify"}, {"path": "new.txt", "mode": "create"}, {"path": "ghost.txt", "mode": "modify"}],
          "refreshed_from": {"base": base, "stale_paths": ["old.txt", "ghost.txt"]}}
    fence = "```json:manifest\n" + json.dumps(mf) + "\n```\n" if with_manifest else ""
    return f"# Thing\n\n**Spec:** `{SPEC}`\n\n{fence}\nbody\n"


class Base(unittest.TestCase):
    with_manifest = True

    def setUp(self):
        cache_main_root(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name).resolve()
        self.repo = r = t / "repo"
        r.mkdir()
        for k, v in {"TC_STATE": str(t / "state"), "USAGE_ROOT": str(t / "proj"), "TC_LINEAGE": str(t / "lin")}.items():
            p = mock.patch.dict(os.environ, {k: v}); p.start(); self.addCleanup(p.stop)
        git(r, "init", "-q", "-b", "main")
        (r / "old.txt").write_text("one\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base")
        self.base0 = git(r, "rev-parse", "HEAD")
        (r / PLAN).parent.mkdir(parents=True)
        (r / PLAN).write_text(plan_text(self.base0, self.with_manifest))
        meta = json.dumps({"files": ["old.txt", "new.txt"], "modelTier": "standard"})
        (r / (PLAN + ".tasks.json")).write_text(json.dumps({"planPath": PLAN, "tasks": [
            {"id": 1, "subject": "Task 1", "description": "x\n\n```json:metadata\n" + meta + "\n```\n"}]}))
        git(r, "add", "."); git(r, "commit", "-q", "-m", "plan")
        git(r, "checkout", "-q", "-b", "feat")
        (r / "old.txt").write_text("one\ntwo\n")
        (r / "new.txt").write_text("n\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "work")
        git(r, "checkout", "-q", "main")
        first = git(r, "rev-parse", "HEAD")
        git(r, "merge", "-q", "--no-ff", "-m", "Merge branch 'feat'", "feat")
        self.merge = {"sha": git(r, "rev-parse", "HEAD"), "subject": "Merge branch 'feat'", "first": first,
                      "second": git(r, "rev-parse", "feat"), "ct": int(git(r, "log", "-1", "--format=%ct"))}
        self.now = float(int(time.time()))
        self.t0 = self.now - 1800
        metrics.append(r, {"kind": "batch", "batch": "B", "base": first, "configs": ["cfg"], "assignment": {SPEC: "cfg", "docs/superpowers/specs/other.md": "cfg"},
                           "groups": [], "at": metrics.utc(self.t0 - 600)})
        metrics.append(r, {"kind": "start", "batch": "B", "spec": SPEC, "at": metrics.utc(self.t0), "main": first})
        self.db = t / "usage.sqlite"
        self.conn = usage.connect(self.db)
        self.addCleanup(self.conn.close)
        self.stub = t / "facts.json"
        self.stub.write_text(json.dumps(FACTS))
        self.n = 0

    def facts_cmd(self, cmd):
        p = mock.patch.dict(os.environ, {"TC_REGISTRY_FACTS_CMD": cmd}); p.start(); self.addCleanup(p.stop)

    def stub_cmd(self):
        sh = Path(self.tmp.name) / "stub.sh"
        sh.write_text(f"#!/bin/sh\ncat {self.stub}\n")
        self.facts_cmd(f"sh {sh}")

    def real_cmd(self):
        self.facts_cmd(f"node {REPO_ROOT}/engine/bin/registry.js")

    def static(self):
        return metrics.build_record_static(self.repo, SPEC, "B", None, self.now, merge=self.merge)

    def row(self, ts, agent, cwd=None, inp=100, out=10, cr=5, cw5=3, cw1=2):
        self.n += 1
        t = (f"r{self.n}", "s1", ts, OPUS, None, agent, None, "main", cwd or str(self.repo), 0, 0, inp, out, cr, cw5, cw1)
        self.conn.execute(f"insert into calls ({','.join(usage.COLS)}) values ({','.join('?' * 16)})", t)
        self.conn.commit()


class FactsTest(Base):
    def check(self, r):
        self.assertEqual(r["manifest"], WANT_MANIFEST)
        self.assertEqual((r["refreshes"], r["stale_paths"]), (1, 2))
        self.assertNotIn("manifest_facts", r["missing"])

    def test_stubbed_facts_fill_the_manifest(self):
        self.stub_cmd()
        self.check(self.static())

    def test_real_facts_give_the_same_fields(self):
        self.real_cmd()
        self.check(self.static())

    def test_default_command_is_tmux_ctl_registry(self):
        os.environ.pop("TC_REGISTRY_FACTS_CMD", None)
        with mock.patch.object(metrics.subprocess, "run", wraps=metrics.subprocess.run) as run:
            self.static()
        cmds = [c.args[0] for c in run.call_args_list if "registry" in c.args[0]]
        self.assertEqual(cmds[0][:3], ["zsh", str(HERE.parent / "bin/tmux-ctl"), "registry"])
        self.assertEqual(cmds[0][3:6], ["facts", SPEC, "--base"])

    def test_facts_failure_falls_back_and_is_named(self):
        self.facts_cmd("sh -c 'echo boom >&2; exit 1'")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            r = self.static()
        self.assertEqual(r["manifest"]["source"], "tasks")
        self.assertIn("manifest_facts", r["missing"])
        self.assertEqual(err.getvalue().strip(), "metrics: record: registry facts failed: boom")
        self.assertNotIn("refreshes", r)


class NoManifestTest(Base):
    with_manifest = False

    def test_no_manifest_leaves_the_line_unchanged(self):
        self.real_cmd()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            r = self.static()
        self.assertEqual(err.getvalue(), "")
        self.assertNotIn("refreshes", r)
        self.assertNotIn("stale_paths", r)
        self.assertNotIn("manifest_facts", r["missing"])
        self.assertEqual(r["manifest"]["source"], "tasks")


class TokensTest(Base):
    def rec(self):
        self.stub_cmd()
        return metrics.build_record(self.repo, SPEC, "B", None, self.now, conn=self.conn, project="proj", merge=self.merge, branch="feat")

    def test_refresh_plus_crossplan_share(self):
        mid = self.t0 + 100
        each = 100 + 10 + 5 + 3 + 2
        self.row(mid, "refresh-thing")                       # in window: counts whole
        self.row(self.t0 - 400, "crossplan-B")               # after batch at (t0-600): counts, share 1/2
        self.row(self.t0 - 400, "crossplan-B")
        self.row(mid, "refresh-other")                       # unrelated agent
        self.row(self.t0 - 900, "crossplan-B")               # before the batch line
        self.row(self.t0 - 400, "crossplan-OTHER")
        self.assertEqual(self.rec()["manifest_tokens"], each + 2 * each / 2)

    def test_no_rows_is_zero(self):
        r = self.rec()
        self.assertEqual(r["manifest_tokens"], 0)
        self.assertNotIn("manifest_tokens", r["missing"])

    def test_no_batch_line_is_null_and_missing(self):
        self.stub_cmd()
        r = metrics.build_record(self.repo, SPEC, "NOPE", None, self.now, conn=self.conn, project="proj", merge=self.merge, branch="feat")
        self.assertIsNone(r["manifest_tokens"])
        self.assertIn("manifest_tokens", r["missing"])


if __name__ == "__main__":
    unittest.main()
