import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))
import metrics  # noqa: E402
from test_metrics_log import Base  # noqa: E402

METRICS = str(HERE / "metrics.py")


class AppendBase(Base):
    def setUp(self):
        super().setUp()
        self.log = str(Path(self.tmp.name) / "scratch" / "runs.jsonl")

    def ln(self):
        return [json.loads(x) for x in Path(self.log).read_text().splitlines()]

    def put(self, *objs):
        Path(self.log).parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "a") as f:
            for o in objs:
                f.write(json.dumps(o) + "\n")


class TestAppend(AppendBase):
    def test_append_sets_kind_and_batch(self):
        rc, out, err = self.run_main("append", "analysis", "--json", '{"kind":"zzz","specs":2}', "--batch", "b1", "--log", self.log)
        self.assertEqual((rc, out), (0, ""))
        self.assertEqual(len(self.ln()), 1)
        d = self.ln()[0]
        self.assertEqual((d["kind"], d["batch"], d["specs"]), ("analysis", "b1", 2))

    def test_append_refuses_stage1_kinds(self):
        for k in ("batch", "start", "run", "defect"):
            with self.subTest(k):
                rc, out, err = self.run_main("append", k, "--json", "{}", "--log", self.log)
                self.assertEqual(rc, 1)
                self.assertEqual(len(err.strip().splitlines()), 1)
                self.assertIn("has its own command", err)
        self.assertFalse([d for d in (self.ln() if Path(self.log).exists() else []) if d.get("kind") in ("batch", "start", "run", "defect")])

    def test_append_refuses_non_object(self):
        for j in ("[1]", "nope"):
            with self.subTest(j):
                rc, out, err = self.run_main("append", "analysis", "--json", j, "--log", self.log)
                self.assertEqual(rc, 1)
                self.assertEqual(len(err.strip().splitlines()), 1)
                self.assertIn("--json", err)

    def test_concurrent_appends_are_whole_lines(self):
        pad = "x" * 4000
        cmd = [sys.executable, "-I", METRICS, "--repo", str(self.repo), "append", "x", "--json", json.dumps({"pad": pad}), "--log", self.log]
        def loop():
            return subprocess.Popen(["sh", "-c", 'for i in $(seq 200); do "$@" || exit 1; done', "sh", *cmd])
        ps = [loop(), loop()]
        self.assertEqual([p.wait() for p in ps], [0, 0])
        self.assertEqual(len(self.ln()), 400)
        self.assertTrue(os.path.exists(self.log + ".lock"))


class TestHasRuns(AppendBase):
    def test_has_kind_spec_batch(self):
        self.put({"kind": "analysis", "batch": "b1", "spec": "docs/s.md"}, {"kind": "other", "batch": "b2"})
        h = lambda *a: self.run_main("has", *a, "--log", self.log)
        self.assertEqual(h("analysis"), (0, "", ""))
        self.assertEqual(h("analysis", "--batch", "b1")[0], 0)
        self.assertEqual(h("analysis", "--batch", "b2")[0], 1)
        self.assertEqual(h("analysis", "--spec", "docs/s.md")[0], 0)
        self.assertEqual(h("analysis", "--spec", "docs/t.md")[0], 1)
        self.assertEqual(h("nokind"), (1, "", ""))

    def test_runs_json_shape(self):
        self.put({"kind": "batch", "batch": "b1", "base": "abc", "at": "2026-11-21T00:00:00Z", "specs": ["a.md", "b.md"]},
                 {"kind": "run", "batch": "b1", "spec": "a.md", "outcome": "merged"},
                 {"kind": "run", "batch": "b1", "spec": "c.md", "outcome": "mr"})
        rc, out, err = self.run_main("runs", "b1", "--json", "--log", self.log)
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        self.assertEqual(sorted(d), ["at", "base", "batch", "pairs", "runs", "specs"])
        self.assertEqual(d["specs"], ["a.md", "b.md", "c.md"])
        self.assertIsNone(d["runs"]["b.md"])
        self.assertEqual(d["runs"]["a.md"]["outcome"], "merged")
        self.assertEqual((d["base"], d["at"]), ("abc", "2026-11-21T00:00:00Z"))

    def test_runs_unknown_batch_exits_1(self):
        self.put({"kind": "batch", "batch": "b1", "specs": []})
        rc, out, err = self.run_main("runs", "nope", "--json", "--log", self.log)
        self.assertEqual(rc, 1)

    def test_log_override_restored(self):
        self.run_main("has", "x", "--log", self.log)
        self.assertIsNone(metrics.LOG_OVERRIDE)


if __name__ == "__main__":
    unittest.main()
