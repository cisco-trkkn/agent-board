import json, os, subprocess, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_metrics_log import Base, git  # noqa: E402
import metrics  # noqa: E402


class WorktreeCwdTest(Base):
    """Every command resolves run log, configs, gates and roadmap from the main checkout, whatever worktree the cwd is in."""

    def setUp(self):
        super().setUp()
        self.wt = self.repo.parent / "wt"
        git(self.repo, "worktree", "add", "-q", "-b", "feat/w", str(self.wt))

    def run_in(self, repo, *argv):
        return self.run_main_repo(repo, *argv)

    def run_main_repo(self, repo, *argv):
        import contextlib, io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(repo), *argv])
        return rc, out.getvalue(), err.getvalue()

    def test_start_from_a_worktree_finds_the_main_batch(self):
        self.cfg("A", True)
        _, out, _ = self.run_main("batch", "start", "--config", "A", "s1.md")
        bid = out.splitlines()[0]
        rc, _, err = self.run_in(self.wt, "start", "s1.md", "--batch", bid)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual([l["kind"] for l in self.lines()], ["batch", "start"])
        self.assertFalse((self.wt / "docs/superpowers/metrics/runs.jsonl").exists())
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")

    def test_configs_come_from_the_main_checkout(self):
        self.cfg("A", True)   # untracked file in main only
        rc, _, err = self.run_in(self.wt, "batch", "start", "--config", "A", "s1.md")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(len(self.lines()), 1)
        self.assertFalse((self.wt / "docs").exists())


class AbsoluteSpecTest(Base):
    def test_absolute_spec_is_stored_repo_relative(self):
        self.cfg("A", True)
        abs_spec = str(self.repo / "docs/superpowers/specs/b.md")
        rc, out, err = self.run_main("batch", "start", "--config", "A", abs_spec, "./docs/superpowers/specs/c.md")
        self.assertEqual((rc, err), (0, ""))
        bid = out.splitlines()[0]
        self.assertEqual(out.splitlines()[1:], ["docs/superpowers/specs/b.md A", "docs/superpowers/specs/c.md A"])
        self.assertEqual(self.run_main("start", abs_spec, "--batch", bid)[0], 0)
        self.assertEqual(self.run_main("defect", abs_spec, "x")[0], 0)
        specs = [l["spec"] for l in self.lines() if "spec" in l]
        self.assertEqual(specs, ["docs/superpowers/specs/b.md"] * 2)
        raw = metrics.log_path(self.repo).read_text()
        self.assertNotIn(str(self.repo), raw)
        self.assertNotIn(str(self.repo.resolve()), raw)

    def test_spec_outside_the_repo_is_refused_with_the_basename_only(self):
        other = self.repo.parent / "elsewhere" / "o.md"
        rc, out, err = self.run_main("defect", str(other), "x")
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(err, "metrics: defect: spec outside the repo: o.md\n")
        self.assertNotIn(str(self.repo.parent), metrics.log_path(self.repo).read_text() if metrics.log_path(self.repo).exists() else "")


class ErrorLogTest(Base):
    def test_error_in_a_repo_without_metrics_dir_leaves_the_tree_clean(self):
        rc, _, err = self.run_main("batch", "start", "--config", "seq-sdd", "x.md")
        self.assertEqual(rc, 1)
        self.assertTrue(err.startswith("metrics: batch start: unknown config seq-sdd"))
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertFalse((self.repo / "docs").exists())

    def test_error_in_a_repo_with_metrics_dir_is_logged(self):
        (self.repo / "docs/superpowers/metrics").mkdir(parents=True)
        self.run_main("start", "s.md", "--batch", "nope")
        self.assertEqual([l["kind"] for l in self.lines()], ["error"])

    def test_backfill_error_goes_to_the_given_log_not_the_real_one(self):
        (self.repo / "docs/superpowers/metrics").mkdir(parents=True)
        dry = self.repo.parent / "dry.jsonl"
        rc, _, _ = self.run_main("backfill", "--since", "bogus", "--log", str(dry), "--no-ingest",
                                 "--usage-db", str(self.repo.parent / "u.sqlite"))
        self.assertEqual(rc, 1)
        self.assertFalse((self.repo / "docs/superpowers/metrics/runs.jsonl").exists())
        self.assertEqual(json.loads(dry.read_text().splitlines()[0])["kind"], "error")


if __name__ == "__main__":
    unittest.main()
