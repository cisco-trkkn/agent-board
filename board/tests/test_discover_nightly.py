import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))
import discover as D  # noqa: E402
import discover_post  # noqa: E402
import dream  # noqa: E402
import tc_env  # noqa: E402
from test_discover import fake_claude, item, git  # noqa: E402

NOW = 1_800_000_000
NIGHT = __import__("time").strftime("%Y%m%d", __import__("time").localtime(NOW))


def cand(key="todo:a.py:11111111", count=1):
    return {"signal": "todo", "key": key, "title": "T", "evidence": [{"text": "a.py:1 TODO x", "path": "a.py", "line": 1, "url": None}],
            "first_seen": "2026-01-01", "count": count}


def tree(d):
    return sorted(str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()) if Path(d).exists() else []


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.state = self.t / "state"
        self.state.mkdir()
        (self.t / "ctx").mkdir()
        p = mock.patch.dict(os.environ, {"TC_STATE": str(self.state), "TC_IDEAS_DIR": str(self.t / "ideas"),
                                         "TC_CONTEXT_DIR": str(self.t / "ctx")})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("TC_DISCOVER", None)
        for patcher in (mock.patch.object(dream, "live_session_root", return_value=None),
                        mock.patch.object(dream, "weekly_pct", return_value=10)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.coll = {"candidates": [cand()], "sources_skipped": [{"signal": "dependency", "why": "no gh"}]}
        pc = mock.patch.object(D, "collect", side_effect=lambda p, r, n: dict(self.coll, project=p, root=str(r), at="x", head=None))
        pc.start()
        self.addCleanup(pc.stop)
        self.result = json.dumps({"items": [item()]})
        self.mode = "ok"

    def project(self, name="p", metrics=False):
        (self.t / "ctx" / f"{name}.md").write_text("# x\n")
        root = self.t / f"repo-{name}"
        root.mkdir()
        git(root, "init", "-q")
        git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        d = tc_env.agent_base() / "discover"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.json").write_text(json.dumps({"root": str(root)}))
        if metrics:
            m = root / "docs" / "superpowers" / "metrics"
            m.mkdir(parents=True)
            (m / "runs.jsonl").write_text("")
        return root

    def nightly(self, *args, now=NOW):
        claude = fake_claude(self.t, self.result, self.mode)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"TC_DISCOVER_CLAUDE": str(claude)}), redirect_stdout(out), redirect_stderr(err):
            rc = D.main(["nightly", *args], now=now)
        return rc, out.getvalue(), err.getvalue()

    def st(self, p="p"):
        return discover_post.load_state(p)

    def outbox(self, p="p"):
        box = tc_env.discord_dir(p) / "outbox"
        return [json.loads(f.read_text()) for f in sorted(box.glob("*.json"))] if box.is_dir() else []

    def log(self):
        f = tc_env.agent_base() / "discover" / "discover.log"
        return f.read_text().splitlines() if f.is_file() else []


class GuardsTest(Base):
    def test_off_env(self):
        self.project()
        with mock.patch.dict(os.environ, {"TC_DISCOVER": "0"}):
            rc, out, _ = self.nightly()
        self.assertEqual((rc, out.strip()), (0, "discover: off"))
        self.assertFalse((self.t / "argv.json").exists())

    def test_off_file(self):
        self.project()
        (tc_env.agent_base() / "discover.off").write_text("")
        rc, out, _ = self.nightly()
        self.assertEqual((rc, out.strip()), (0, "discover: off"))
        self.assertFalse((self.t / "argv.json").exists())

    def test_weekly_skip_and_force(self):
        self.project()
        with mock.patch.object(dream, "weekly_pct", return_value=90):
            rc, out, _ = self.nightly()
            self.assertEqual((rc, out.strip()), (0, "discover: skipped, weekly 90%"))
            self.assertFalse((self.t / "argv.json").exists())
            rc, out, _ = self.nightly("--force")
        self.assertIn("posted", out)

    def test_no_repo_skipped(self):
        (self.t / "ctx" / "ghost.md").write_text("# x\n")
        rc, out, _ = self.nightly()
        self.assertEqual(rc, 0)
        self.assertIn("discover: ghost: no repo", out)
        self.assertFalse((self.t / "argv.json").exists())


class NightTest(Base):
    def test_normal_night_posts(self):
        self.project()
        rc, out, _ = self.nightly()
        self.assertEqual(rc, 0)
        self.assertIn("discover: p: 1 candidates, 1 ranked, 1 new, posted", out)
        ops = self.outbox()
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["key"], f"discover-p-{NIGHT}")
        self.assertIn("todo:a.py:11111111", self.st()["reported"])
        self.assertEqual(self.st()["root"], str((self.t / "repo-p").resolve()))
        self.assertTrue(any(l.endswith(" p posted") for l in self.log()))

    def test_nothing_new(self):
        self.project()
        self.nightly()
        rc, out, _ = self.nightly()
        self.assertIn("discover: p: 1 candidates, 1 ranked, 0 new, nothing new", out)
        self.assertEqual(len(self.outbox()), 1)
        self.assertTrue(self.log()[-1].endswith(" p nothing-new"))

    def test_good_night_resets_failures(self):
        self.project()
        discover_post.save_state("p", dict(self.st(), failures=2))
        self.nightly()
        self.assertEqual(self.st()["failures"], 0)

    def test_one_project_raising_does_not_stop_others(self):
        self.project("a")
        self.project("b")
        real = D._night
        def boom(project, *a, **k):
            if project == "a":
                raise RuntimeError("kaboom")
            return real(project, *a, **k)
        with mock.patch.object(D, "_night", side_effect=boom):
            rc, out, err = self.nightly()
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.outbox("b")), 1)
        self.assertIn("kaboom", out + err)

    def test_project_flag(self):
        self.project("a")
        self.project("b")
        self.nightly("--project", "b")
        self.assertEqual(self.outbox("a"), [])
        self.assertEqual(len(self.outbox("b")), 1)


class DryRunTest(Base):
    def test_dry_run_prints_and_writes_nothing(self):
        root = self.project(metrics=True)
        discover_post.save_state("p", dict(self.st(), failures=1))
        before = (tree(self.state), tree(tc_env.discord_dir("p")), (root / "docs/superpowers/metrics/runs.jsonl").read_text(),
                  (tc_env.agent_base() / "discover" / "p.json").read_text())
        rc, out, _ = self.nightly("--dry-run")
        after = (tree(self.state), tree(tc_env.discord_dir("p")), (root / "docs/superpowers/metrics/runs.jsonl").read_text(),
                 (tc_env.agent_base() / "discover" / "p.json").read_text())
        self.assertEqual(rc, 0)
        self.assertEqual(before, after)
        self.assertIn("🔎 discover p: 1 new", out)
        self.assertIn("File as idea 1", out)
        self.assertIn("Dismiss 1", out)

    def test_dry_run_failure_does_not_touch_failures(self):
        self.project()
        self.mode = "exit1"
        before = tree(self.state)
        rc, _, _ = self.nightly("--dry-run")
        self.assertEqual(self.st()["failures"], 0)
        self.assertEqual(before, tree(self.state))
        self.assertEqual(self.log(), [])
        self.assertEqual(self.outbox(), [])


class FailureTest(Base):
    def setUp(self):
        super().setUp()
        self.project(metrics=True)
        self.mode = "exit1"

    def test_failure_counts_and_logs(self):
        rc, out, err = self.nightly()
        self.assertEqual(rc, 1)
        self.assertEqual(self.st()["failures"], 1)
        self.assertEqual(self.outbox(), [])
        self.assertRegex(self.log()[-1], r"^\d{4}-\d\d-\d\dT[\d:]+ p failed: model exit 1$")

    def test_critical_at_exactly_three(self):
        for _ in range(2):
            self.nightly()
        self.assertEqual(self.outbox(), [])
        self.nightly()
        ops = self.outbox()
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["tier"], "critical")
        self.assertTrue(ops[0]["mention_user"])
        self.assertEqual(ops[0]["key"], f"discover-p-fail-{NIGHT}")
        self.assertTrue(ops[0]["text"].startswith("🔎 discover: p failed 3 nights running — "))
        self.assertIn("model exit 1", ops[0]["text"])

    def test_fourth_failure_posts_nothing_new(self):
        for _ in range(3):
            self.nightly()
        self.nightly()
        self.assertEqual(self.st()["failures"], 4)
        self.assertEqual(len(self.outbox()), 1)

    def test_good_night_after_failures_resets_and_rearms(self):
        for _ in range(3):
            self.nightly()
        self.mode = "ok"
        self.nightly()
        self.assertEqual(self.st()["failures"], 0)

    def test_unfittable_post_counts_as_failure(self):
        self.mode = "ok"
        with mock.patch.object(discover_post, "build_op", side_effect=ValueError("does not fit")):
            rc, _, _ = self.nightly()
        self.assertEqual(rc, 1)
        self.assertEqual(self.st()["failures"], 1)
        self.assertIn("does not fit", self.log()[-1])
        self.assertEqual(self.outbox(), [])


class CollectRaisesTest(Base):
    def test_collect_exception_is_a_failed_night(self):
        self.project()
        self.project("q")
        calls = []
        def collect(p, r, n):
            if p == "p":
                raise OSError("disk gone")
            calls.append(p)
            return dict(self.coll, project=p, root=str(r), at="x", head=None)
        with mock.patch.object(D, "collect", side_effect=collect):
            rc, _, _ = self.nightly()
            self.assertEqual(rc, 1)
            self.assertEqual(self.st()["failures"], 1)
            self.assertIn("p failed: OSError: disk gone", self.log()[0])
            self.assertEqual(len(self.outbox("q")), 1)
            for _ in range(2):
                self.nightly("--project", "p")
        ops = self.outbox("p")
        self.assertEqual([o["tier"] for o in ops], ["critical"])

    def test_collect_exception_dry_run_touches_nothing(self):
        self.project()
        before = tree(self.state)
        with mock.patch.object(D, "collect", side_effect=OSError("x")):
            rc, _, _ = self.nightly("--dry-run")
        self.assertEqual(self.st()["failures"], 0)
        self.assertEqual(before, tree(self.state))


class MetricsTest(Base):
    def rec(self, root):
        return [json.loads(l) for l in (root / "docs/superpowers/metrics/runs.jsonl").read_text().splitlines()]

    def test_record_on_posted_night(self):
        root = self.project(metrics=True)
        self.nightly()
        (r,) = self.rec(root)
        self.assertEqual({k: r[k] for k in ("kind", "project", "outcome", "candidates", "ranked", "new", "model")},
                         {"kind": "discover", "project": "p", "outcome": "posted", "candidates": 1, "ranked": 1, "new": 1, "model": "sonnet"})
        for k in ("at", "sources_skipped", "cost_usd", "tokens", "duration_s"):
            self.assertIn(k, r)
        self.assertEqual(r["cost_usd"], 0.01)

    def test_record_nothing_new_and_failed(self):
        root = self.project(metrics=True)
        self.nightly()
        self.nightly()
        self.mode = "exit1"
        self.nightly()
        self.assertEqual([r["outcome"] for r in self.rec(root)], ["posted", "nothing-new", "failed"])

    def test_missing_runs_jsonl_no_record_no_error(self):
        root = self.project(metrics=False)
        rc, _, _ = self.nightly()
        self.assertEqual(rc, 0)
        self.assertFalse((root / "docs/superpowers/metrics/runs.jsonl").exists())
        self.assertFalse((root / "docs").exists())


if __name__ == "__main__":
    unittest.main()
