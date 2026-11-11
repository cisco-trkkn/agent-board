import contextlib, io, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics  # noqa: E402
from metrics_fixtures import cache_main_root  # noqa: E402

LIMIT = ("With this spread, a 2x effect shows after about 4 specs per configuration, 1.5x after about 9, and 20% needs about 30; "
         "differences under about 1.5x are not decidable this way.")
BASE = [100, 104, 108, 112, 116, 120, 124, 128]


class Base(unittest.TestCase):
    def setUp(self):
        cache_main_root(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name).resolve()
        self.repo = self.t / "repo"
        (self.repo / "docs/superpowers/metrics/configs").mkdir(parents=True)
        subprocess.run(["git", "-C", str(self.repo), "init", "-q", "-b", "main"], check=True)
        (self.repo / "docs/superpowers/metrics/gates").mkdir(parents=True)
        p = mock.patch.dict(os.environ, {"TC_STATE": str(self.t / "state"), "USAGE_ROOT": str(self.t / "proj")})
        p.start()
        self.addCleanup(p.stop)
        self.n = 0
        self.cfg("A", True)
        self.cfg("B", False, targets=[{"metric": "tokens_per_task", "max": 1.0}])

    def cfg(self, name, baseline, **extra):
        d = {"id": name, "baseline": baseline}
        d.update(extra)
        (self.repo / f"docs/superpowers/metrics/configs/{name}.md").write_text("prose\n```json:config\n" + json.dumps(d) + "\n```\n")

    def add(self, config, tpt, batch="b1", outcome="merged", tasks=2, **kw):
        self.n += 1
        d = {"kind": "run", "batch": batch, "spec": f"docs/superpowers/specs/{config}{self.n}.md", "config": config,
             "outcome": outcome, "tasks": tasks, "tokens": {"total": int(tpt * tasks)}, "active_min": 10 * tasks,
             "fix_wave": False, "ended_at": "2026-11-10T12:00:00Z", "at": "2026-11-10T12:00:00Z"}
        d.update(kw)
        metrics.append(self.repo, d)
        return d["spec"]

    def baseline(self, values=BASE):
        for v in values:
            self.add("A", v, batch="base")

    def challenger(self, values, batches=("b1", "b2"), **kw):
        return [self.add("B", v, batch=batches[i % len(batches)], **kw) for i, v in enumerate(values)]

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), *argv])
        return rc, out.getvalue(), err.getvalue()

    def verdict(self):
        rc, out, err = self.main("compare", "B")
        self.assertEqual((rc, err), (0, ""))
        line = [l for l in out.splitlines() if l.startswith("Verdict: ")]
        self.assertEqual(len(line), 1, out)
        return line[0][len("Verdict: "):], out


class VerdictTest(Base):
    def test_too_early(self):
        self.baseline()
        self.challenger([50, 52, 54])
        v, out = self.verdict()
        self.assertEqual(v, "too early")
        self.assertIn(LIMIT, out)

    def test_kill_or_adjust_by_index(self):
        self.baseline()
        self.challenger([200, 204, 208, 212, 216, 220, 224, 228])
        self.assertEqual(self.verdict()[0], "kill or adjust")

    def test_kill_or_adjust_by_veto(self):
        self.baseline()
        self.challenger([50, 52, 54], outcome="merged")
        self.challenger([60, 61, 62, 63, 64], outcome="failed")   # 5 failed of 8 > 0 * 8 + 1
        v, out = self.verdict()
        self.assertEqual(v, "kill or adjust")
        self.assertIn("failed specs 5", out)

    def test_veto_always_false_mutation_target(self):
        # the same data without the veto would be a replace: index 0.5, exact p tiny; guards the veto test above
        self.baseline()
        self.challenger([50, 52, 54], outcome="merged")
        self.challenger([60, 61, 62, 63, 64], outcome="failed")
        with mock.patch.object(metrics, "quality_veto", return_value=(False, [])):
            self.assertNotEqual(self.verdict()[0], "kill or adjust")

    def test_replace(self):
        self.baseline()
        self.challenger([50, 52, 54, 56, 58, 60, 62, 64])
        v, out = self.verdict()
        self.assertEqual(v, "replace")
        self.assertIn("exact", out)
        self.assertIn(LIMIT, out)

    def test_replace_needs_two_batches(self):
        self.baseline()
        self.challenger([50, 52, 54, 56, 58, 60, 62, 64], batches=("b1",))
        self.assertEqual(self.verdict()[0], "continue")

    def test_continue_when_not_significant(self):
        self.baseline()
        self.challenger([98, 102, 106, 110, 114, 118, 122, 126])
        self.assertEqual(self.verdict()[0], "continue")

    def test_weak_evidence(self):
        self.cfg("B", False, targets=[{"metric": "tokens_per_task", "max": 0.9}])
        self.baseline()
        self.challenger([v * 0.95 for v in BASE] * 2)
        v, out = self.verdict()
        self.assertEqual(v, "weak evidence")
        self.assertIn("weak", out)

    def test_defects_count_only_within_14_days(self):
        self.baseline()
        specs = self.challenger([50, 52, 54, 56, 58, 60, 62, 64])
        for s, d in ((specs[0], "2026-11-12"), (specs[1], "2026-11-20"), (specs[2], "2026-12-30")):
            metrics.append(self.repo, {"kind": "defect", "spec": s, "what": "x", "date": d})
        v, out = self.verdict()
        self.assertEqual(v, "kill or adjust")   # 2 defects within 14 days > 0 * 8 + 1
        self.assertIn("escaped defects 2", out)

    def test_fix_waves_use_baseline_rate(self):
        for v in BASE:
            self.add("A", v, batch="base", fix_wave=True)   # rate 1.0 per spec
        self.challenger([50, 52, 54, 56, 58, 60, 62, 64], fix_wave=True)    # 8 > 1.0 * 8 + 1 is false
        self.assertEqual(self.verdict()[0], "replace")

    def test_replace_counts_only_included_specs(self):
        self.baseline()
        self.challenger([50, 52, 54, 56, 58, 60])
        self.challenger([60, 61], outcome="kept")      # 8 challenger lines, 2 excluded: only 6 reach the index
        v, out = self.verdict()
        self.assertNotEqual(v, "replace")
        self.assertEqual(v, "continue")

    def test_throughput_batch_target_met_and_not_met(self):
        self.cfg("B", False, targets=[{"metric": "throughput", "min": 1.5}])
        self.baseline()                                              # 2 tasks / 20 min each: 6 tasks per hour
        self.add("B", 50, batch="b1", active_min=10)                 # 2 tasks / 10 min: 12 per hour, ratio 2.0
        t = metrics.compare_data(self.repo, "B")["targets"][0]
        self.assertTrue(t["batch_met"])
        self.assertTrue(t["met"])
        self.assertAlmostEqual(t["index"], 2.0)
        self.add("B", 50, batch="b2", active_min=40)                 # 2 tasks / 40 min: 3 per hour, ratio 0.5
        t = metrics.compare_data(self.repo, "B")["targets"][0]
        self.assertFalse(t["batch_met"])                             # not met in every challenger batch
        self.assertFalse(t["met"])
        self.assertIn("every challenger batch not met", metrics.compare_text(self.repo, "B"))

    def test_exclusions_are_counted_and_printed(self):
        self.baseline()
        self.challenger([50, 52, 54, 56, 58, 60, 62, 64])
        self.add("B", 70, tokens=None)
        self.add("B", 70, tasks=0)
        _, out = self.verdict()
        self.assertRegex(out, r"Excluded: 2")

    def test_no_baseline_records(self):
        self.challenger([50])
        rc, out, err = self.main("compare", "B")
        self.assertEqual((rc, out, err), (1, "", "metrics: compare: no baseline records\n"))

    def test_sampled_when_too_many_splits(self):
        self.baseline([100 + i for i in range(20)])
        self.challenger([50 + i for i in range(20)])      # comb(40, 20) is far above 200000
        v, out = self.verdict()
        self.assertEqual(v, "replace")
        self.assertIn("sampled", out)

    def test_permutation_is_deterministic_and_one_sided(self):
        a, b = [1.0, 2.0, 3.0, 9.0], [2.0, 3.0, 4.0, 5.0]
        r1 = metrics.permutation_p(a, b, "max")
        self.assertEqual(r1, metrics.permutation_p(a, b, "max"))
        self.assertEqual(r1[1], "exact")
        self.assertTrue(0 < r1[0] <= 1)
        # one challenger against one baseline value: 2 splits, the observed one is the lower of the two
        self.assertEqual(metrics.permutation_p([1.0], [9.0], "max"), (0.5, "exact"))
        self.assertEqual(metrics.permutation_p([1.0], [9.0], "min"), (1.0, "exact"))
        big = metrics.permutation_p([float(i + 1) for i in range(20)], [float(i + 30) for i in range(20)], "max")
        self.assertEqual(big[1], "sampled")
        self.assertEqual(big, metrics.permutation_p([float(i + 1) for i in range(20)], [float(i + 30) for i in range(20)], "max"))


class GateTest(Base):
    def gate(self, text_obj, name="K"):
        (self.repo / f"docs/superpowers/metrics/gates/{name}.md").write_text("prose\n```json:gate\n" + json.dumps(text_obj) + "\n```\n")

    def test_compare_gate_pass_fail_too_early(self):
        self.gate({"id": "K", "compare": "B"})
        self.baseline()
        self.challenger([50])
        rc, out, _ = self.main("gate", "K")
        self.assertEqual((rc, out.splitlines()[0]), (3, "gate K: too early"))
        self.challenger([52, 54, 56, 58, 60, 62, 64])
        rc, out, _ = self.main("gate", "K")
        self.assertEqual((rc, out.splitlines()[0]), (0, "gate K: pass"))
        self.add("B", 400, batch="b3")
        for v in (410, 420, 430, 440, 450, 460, 470, 480, 490, 500, 510):
            self.add("B", v, batch="b3")
        rc, out, _ = self.main("gate", "K")
        self.assertEqual((rc, out.splitlines()[0]), (1, "gate K: fail"))

    def conds(self, recall=(0.95, 0.92, 0.97), tokens=1000, mt=100):
        for i, r in enumerate(recall):
            self.add("A", 100, batch="g", manifest_tokens=mt, manifest={"recall_existing": r}, tokens={"total": tokens})
        self.add("A", 100, batch="g")   # no manifest_tokens: filtered out by where.has

    def body(self, **over):
        g = {"id": "K1", "min_specs": 3, "where": {"has": "manifest_tokens"}, "conditions": [
            {"metric": "manifest.recall_existing", "agg": "median", "min": 0.9},
            {"metric": "manifest_tokens/tokens.total", "agg": "ratio_of_sums", "max": 0.2}]}
        g.update(over)
        return g

    def test_conditions_gate_pass(self):
        self.conds()
        self.gate(self.body(), "K1")
        rc, out, _ = self.main("gate", "K1")
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines(), ["gate K1: pass", "manifest.recall_existing 0.95 (min 0.9) pass",
                                            "manifest_tokens/tokens.total 0.1 (max 0.2) pass"])

    def test_conditions_gate_fail(self):
        self.conds(mt=500)
        self.gate(self.body(), "K1")
        rc, out, _ = self.main("gate", "K1")
        self.assertEqual(rc, 1)
        self.assertEqual(out.splitlines()[0], "gate K1: fail")
        self.assertIn("manifest_tokens/tokens.total 0.5 (max 0.2) fail", out)

    def test_conditions_gate_too_early_below_min_specs(self):
        self.conds()
        self.gate(self.body(min_specs=4), "K1")
        rc, out, _ = self.main("gate", "K1")
        self.assertEqual((rc, out.splitlines()[0]), (3, "gate K1: too early"))

    def test_last_condition_uses_newest_analysis_line_and_where(self):
        self.conds()
        cond = {"metric": "analysis.parallelism", "agg": "last", "min": 1.5, "where": {"appends_verified": True}}
        self.gate(self.body(conditions=[cond]), "K1")
        metrics.append(self.repo, {"kind": "analysis", "analysis": {"parallelism": 2.0}, "appends_verified": True})
        rc, out, _ = self.main("gate", "K1")
        self.assertEqual((rc, out.splitlines()[:2]), (0, ["gate K1: pass", "analysis.parallelism 2.0 (min 1.5) pass"]))
        metrics.append(self.repo, {"kind": "analysis", "analysis": {"parallelism": 3.0}, "appends_verified": False})
        rc, out, _ = self.main("gate", "K1")
        self.assertEqual(rc, 3)   # the newest line does not satisfy the where: too early

    def test_missing_gate_file(self):
        rc, out, err = self.main("gate", "NOPE")
        self.assertEqual((rc, out, err), (1, "", "metrics: gate: no gate file NOPE\n"))


class StatusTest(Base):
    def roadmap(self, doc_text, line="PCEE docs/superpowers/specs/dec.md"):
        (self.repo / "docs/superpowers/metrics/roadmap").write_text(line + "\n")
        (self.repo / "docs/superpowers/specs").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs/superpowers/specs/dec.md").write_text(doc_text)

    def table(self, rows):
        # columns deliberately not in the documented order, header case differs
        out = ["# Dec", "", "## Status", "", "| state | STAGE | Spec | gate | Evidence | Date |", "|---|---|---|---|---|---|"]
        out += [f"| {s} | {n} | x.md | {g} | - | - |" for n, s, g in rows]
        return "\n".join(out) + "\n\n## Later\n"

    def gate(self, name, obj):
        (self.repo / f"docs/superpowers/metrics/gates/{name}.md").write_text("```json:gate\n" + json.dumps(obj) + "\n```\n")

    def test_first_not_passed_row_with_its_gate(self):
        self.roadmap(self.table([("1", "passed", "K0"), ("2", "running", "K1"), ("3", "planned", "K3")]))
        for i in range(3):
            self.add("A", 100, batch="g", manifest={"recall_existing": 0.5}, manifest_tokens=1)
        self.gate("K1", {"id": "K1", "min_specs": 1, "where": {"has": "manifest_tokens"},
                         "conditions": [{"metric": "manifest.recall_existing", "agg": "median", "min": 0.9}]})
        rc, out, _ = self.main("status")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "PCEE: stage 2 running, next gate K1: manifest.recall_existing 0.5 (min 0.9) fail\n")

    def test_next_rows_gate_and_no_gate_file(self):
        self.roadmap(self.table([("1", "passed", "K0"), ("2", "running", "-"), ("3", "planned", "K3")]))
        rc, out, _ = self.main("status")
        self.assertEqual((rc, out), (0, "PCEE: stage 2 running, next gate K3: no gate file\n"))

    def test_status_line_function(self):
        self.roadmap(self.table([("1", "planned", "K9")]))
        self.assertEqual(metrics.status_line(self.repo), "PCEE: stage 1 planned, next gate K9: no gate file")

    def test_doc_without_a_status_table_is_an_error_not_success(self):
        self.roadmap("# Dec\n\nno table here\n")
        rc, out, err = self.main("status")
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(err, "metrics: status: no Status table in docs/superpowers/specs/dec.md\n")
        self.roadmap("# Dec\n\n## Status\n\n| Stage | State |\n|---|---|\n")    # a header and no rows
        rc, out, err = self.main("status")
        self.assertEqual((rc, out), (1, ""))

    def test_no_roadmap_prints_nothing(self):
        rc, out, err = self.main("status")
        self.assertEqual((rc, out, err), (0, "", ""))
        self.assertEqual(metrics.status_line(self.repo), "")


if __name__ == "__main__":
    unittest.main()
