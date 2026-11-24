import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import metrics  # noqa: E402
from test_metrics_record_usage import Base, SPEC1, SID_LEAD, SID_A, SID_B  # noqa: E402


class ControlTokensTest(Base):
    def _three(self):
        self.start(SPEC1)
        self.row(self.t0 + 10, sid=SID_LEAD, inp=100, out=0)    # the lead session
        self.row(self.t0 + 20, sid=SID_A, inp=700, out=0)       # engine implement session (looks like a lead row)
        self.row(self.t0 + 30, sid=SID_B, inp=50, out=0)        # engine architect session

    def test_control_is_lead_plus_architect_and_implement_is_agents(self):
        self._three()
        r = self.rec(engine_jobs={SID_A: "implement", SID_B: "architect"})
        self.assertEqual(r["control_tokens"], 150)
        self.assertEqual(r["by_role"]["lead"]["tokens"], 100)
        self.assertEqual(r["by_role"]["agents"]["tokens"], 750)
        self.assertEqual(r["lead_share"], round(100 / 850, 4))
        self.assertEqual(r["control_share"], round(150 / 850, 4))

    def test_without_engine_jobs_control_share_is_lead_share(self):
        self._three()
        r = self.rec()
        self.assertEqual(r["control_tokens"], 850)
        self.assertEqual(r["control_share"], r["lead_share"])

    def test_record_flags_store_budget_and_engine_jobs(self):
        self._three()
        bud = {"attempts": [3, 60], "tokens": [10, 5000000], "lower_bound": False}
        r = self.rec(engine_jobs={SID_A: "implement"}, budget_spec=bud)
        self.assertEqual(r["budget"], bud)
        self.assertIsNone(self.rec()["budget"])

    def test_cmd_record_bad_json_is_a_metrics_error(self):
        for flag in ("--budget", "--engine-jobs"):
            with self.subTest(flag=flag):
                args = metrics._parser().parse_args(["record", SPEC1, "--batch", "B", flag, "{nope"])
                with self.assertRaises(metrics.MetricsError):
                    metrics.cmd_record(self.repo, args)


class ControlShareCompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.repo = Path(self.tmp.name) / "repo"
        d = self.repo / "docs/superpowers/metrics/configs"
        d.mkdir(parents=True)
        (d / "base.md").write_text('```json:config\n{"id": "base", "baseline": true, "targets": []}\n```\n')
        (d / "chal.md").write_text('```json:config\n{"id": "chal", "baseline": false, "targets": '
                                   '[{"metric": "control_share", "max": 0.5}]}\n```\n')

    def run_line(self, cfg, spec, batch="b1", **kw):
        d = {"kind": "run", "batch": batch, "spec": spec, "config": cfg, "outcome": "merged", "tasks": 2,
             "tokens": {"total": 1000}, "active_min": 10, "lead_share": 0.4, "control_share": 0.1}
        d.update(kw)
        metrics.append(self.repo, d)

    def index(self):
        t = metrics.compare_data(self.repo, "chal")["targets"][0]
        return t["index"], t["met"]

    def test_index_under_and_over(self):
        for i in range(4):
            self.run_line("base", f"s{i}", lead_share=0.8, control_share=None)
        for i in range(4):
            self.run_line("chal", f"c{i}", control_share=0.2)
        idx, met = self.index()
        self.assertAlmostEqual(idx, 0.25)
        self.assertTrue(met)

    def test_index_over(self):
        for i in range(4):
            self.run_line("base", f"s{i}", lead_share=0.4)
        for i in range(4):
            self.run_line("chal", f"c{i}", control_share=0.3)
        idx, met = self.index()
        self.assertAlmostEqual(idx, 0.75)
        self.assertFalse(met)

    def test_last_run_line_wins_in_compare_and_report(self):
        for i in range(4):
            self.run_line("base", f"s{i}", lead_share=0.4)
        for i in range(4):
            self.run_line("chal", f"c{i}", control_share=0.1)
        self.run_line("chal", "c0", control_share=0.9, outcome="failed")   # the parked spec failed later
        d = metrics.compare_data(self.repo, "chal")
        self.assertEqual(len(d["chal"]), 4)
        self.assertEqual(sum(1 for r in d["chal"] if r["outcome"] == "failed"), 1)
        self.assertEqual(len(d["inc_c"]), 3)
        metrics.append(self.repo, {"kind": "batch", "batch": "b1", "configs": ["base", "chal"],
                                   "assignment": {}, "at": "2026-11-24T00:00:00Z"})
        txt = metrics.report_text(self.repo, "b1")
        self.assertEqual(txt.count("| c0 |"), 1)
        self.assertIn("| c0 | failed |", txt)


if __name__ == "__main__":
    unittest.main()
