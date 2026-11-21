import json, shutil, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))
import metrics  # noqa: E402
from test_metrics_log import Base  # noqa: E402

CHECKOUT = HERE.parent
DOCS = CHECKOUT / "docs/superpowers/metrics"


def run_line(n, recall=0.95, tokens=1000, mtokens=50, refreshes=0, batch="b1"):
    d = {"kind": "run", "batch": batch, "spec": f"s{n}", "tokens": {"total": tokens},
         "manifest": {"recall_existing": recall}, "manifest_tokens": mtokens}
    if refreshes is not None:
        d["refreshes"] = refreshes
    return d


class K1Test(Base):
    def setUp(self):
        super().setUp()
        m = self.repo / "docs/superpowers/metrics"
        (m / "gates").mkdir(parents=True)
        (m / "configs").mkdir(parents=True)
        shutil.copy(DOCS / "gates/K1.md", m / "gates/K1.md")
        shutil.copy(DOCS / "configs/upfront-seq.md", m / "configs/upfront-seq.md")
        self.log = str(Path(self.tmp.name) / "scratch" / "runs.jsonl")
        Path(self.log).parent.mkdir(parents=True)

    def put(self, *objs):
        with open(self.log, "a") as f:
            for o in objs:
                f.write(json.dumps(o) + "\n")

    def gate(self):
        return self.run_main("gate", "K1", "--log", self.log)

    def good(self, n=4, **kw):
        self.put(*[run_line(i, **kw) for i in range(n)])
        self.put({"kind": "analysis", "batch": "b1", "appends_verified": True, "parallelism": 2, "waves": {"append": 2}})

    def test_pass(self):
        self.good()
        rc, out, _ = self.gate()
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.startswith("gate K1: pass\n"), out)

    def test_wave_count_beside_parallelism(self):
        self.good()
        _, out, _ = self.gate()
        line = [l for l in out.splitlines() if l.startswith("analysis.parallelism")][0]
        self.assertTrue(line.endswith(" pass") and "(append waves 2)" in line, line)

    def test_recall_fails_alone(self):
        self.good(recall=0.5)
        rc, out, _ = self.gate()
        self.assertEqual((rc, out.splitlines()[0]), (1, "gate K1: fail"))

    def test_parallelism_fails_alone(self):
        self.put(*[run_line(i) for i in range(4)])
        self.put({"kind": "analysis", "appends_verified": True, "parallelism": 1, "waves": {"append": 4}})
        rc, out, _ = self.gate()
        self.assertEqual((rc, out.splitlines()[0]), (1, "gate K1: fail"))

    def test_manifest_tokens_fail_alone(self):
        self.good(mtokens=200)
        rc, out, _ = self.gate()
        self.assertEqual((rc, out.splitlines()[0]), (1, "gate K1: fail"))

    def test_three_specs_too_early(self):
        self.good(n=3)
        rc, out, _ = self.gate()
        self.assertEqual((rc, out.splitlines()[0]), (3, "gate K1: too early"))

    def test_unverified_appends_too_early(self):
        self.put(*[run_line(i) for i in range(4)])
        self.put({"kind": "analysis", "appends_verified": False, "parallelism": 2})
        rc, out, _ = self.gate()
        self.assertEqual((rc, out.splitlines()[0]), (3, "gate K1: too early"))

    def test_runs_without_refreshes_not_counted(self):
        self.put(*[run_line(i, refreshes=None) for i in range(4)])
        self.put({"kind": "analysis", "appends_verified": True, "parallelism": 2})
        rc, out, _ = self.gate()
        self.assertEqual((rc, out.splitlines()[0]), (3, "gate K1: too early"))

    def test_upfront_seq_config_loads(self):
        c = metrics.load_config(self.repo, "upfront-seq")
        self.assertEqual(c, {"id": "upfront-seq", "baseline": False, "targets": [{"metric": "tokens_per_task", "max": 1.0}]})

    def test_k1_file_is_the_spec_json(self):
        g = metrics.load_gate(self.repo, "K1")
        self.assertEqual(g, {"id": "K1", "min_specs": 4, "where": {"has": "refreshes"}, "conditions": [
            {"metric": "manifest.recall_existing", "agg": "median", "min": 0.9},
            {"metric": "analysis.parallelism", "agg": "last", "min": 1.5, "where": {"appends_verified": True}},
            {"metric": "manifest_tokens/tokens.total", "agg": "ratio_of_sums", "max": 0.10}]})


if __name__ == "__main__":
    unittest.main()
