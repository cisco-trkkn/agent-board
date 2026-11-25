import sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_metrics_log import Base  # noqa: E402
import metrics  # noqa: E402


def rec(spec, tokens, tasks=4, outcome="merged", **kw):
    r = {"kind": "run", "batch": "B", "spec": spec, "outcome": outcome, "tasks": tasks, "tokens": {"total": tokens},
         "fix_rounds": 0, "bounces": 0, "red_after_merge": False, "final_review_crit_imp": 0,
         "ended_at": "2026-11-20T10:00:00Z", "budget": {"x": 1}, "config": "eng"}
    r.update(kw)
    return r


def half(prefix, tokens, n=5, **kw):
    return [rec(f"{prefix}{i}", t, **kw) for i, t in enumerate(tokens if isinstance(tokens, list) else [tokens] * n)]


LOW = [100, 110, 120, 105, 115]
HIGH = [200, 220, 240, 210, 230]


class VariantsTest(Base):
    def setUp(self):
        super().setUp()
        self.cfg("A", True)
        _, out, _ = self.run_main("batch", "start", "--config", "A", "s1.md")
        self.bid = out.splitlines()[0]

    def test_start_stores_variants_and_the_record_copies_them(self):
        # mutation: drop the copy in build_record_static -> the record has no variants
        self.assertEqual(self.run_main("start", "s1.md", "--batch", self.bid, "--variants", "P1,P3")[0], 0)
        st = [l for l in self.lines() if l["kind"] == "start"][-1]
        self.assertEqual(st["variants"], ["P1", "P3"])
        r = metrics.build_record_static(self.repo, "s1.md", self.bid, None, time.time())
        self.assertEqual(r["variants"], ["P1", "P3"])

    def test_absent_flag_gives_empty_list(self):
        self.run_main("start", "s1.md", "--batch", self.bid)
        r = metrics.build_record_static(self.repo, "s1.md", self.bid, None, time.time())
        self.assertEqual(r["variants"], [])

    def test_no_ledger_gives_null_and_missing(self):
        self.run_main("start", "s1.md", "--batch", self.bid)
        r = metrics.build_record_static(self.repo, "s1.md", self.bid, None, time.time())
        for k in ("red_after_merge", "final_review_crit_imp"):
            self.assertIsNone(r[k])
            self.assertIn(k, r["missing"])


class LedgerFieldsTest(unittest.TestCase):
    def test_red_after_merge_true_only_with_the_line(self):
        self.assertTrue(metrics.ledger_fields("Merge: tests red after the merge\n", None)["red_after_merge"])
        self.assertFalse(metrics.ledger_fields("Task 1: complete\n", None)["red_after_merge"])

    def test_final_review_count_is_the_last_line(self):
        p = "Final review: 3 critical/important finding(s)\nFinal review: fix wave\nFinal review: 1 critical/important finding(s)\n"
        self.assertEqual(metrics.ledger_fields(p, None)["final_review_crit_imp"], 1)
        self.assertEqual(metrics.ledger_fields("Final review: 0 critical/important finding(s)\n", "## Important\n- a\n")
                         ["final_review_crit_imp"], 0)

    def test_falls_back_to_final_findings(self):
        # lead-run ledger: no engine line, the final-review.md count stands
        f = metrics.ledger_fields("Task 1: complete\n", "## Important\n- a\n- b\n")
        self.assertEqual(f["final_review_crit_imp"], 2)


class HalvesTest(unittest.TestCase):
    def test_too_early_under_four_specs_or_empty(self):
        self.assertEqual(metrics.compare_halves(half("t", LOW, 3)[:3], half("c", HIGH), "tokens_per_merged_task")["verdict"], "too early")
        self.assertEqual(metrics.compare_halves(half("t", LOW), half("c", HIGH)[:3], "tokens_per_merged_task")["verdict"], "too early")
        self.assertEqual(metrics.compare_halves([], [], "tokens_per_merged_task")["verdict"], "too early")

    def test_better_worse_equal(self):
        r = metrics.compare_halves(half("t", LOW), half("c", HIGH), "tokens_per_merged_task")
        self.assertEqual(r["verdict"], "better")
        self.assertLess(r["index"], 1)
        self.assertLess(r["p_better"], 0.10)
        self.assertEqual((r["n_trial"], r["n_control"]), (5, 5))
        self.assertEqual(set(r), {"verdict", "index", "p_better", "p_worse", "n_trial", "n_control", "trial_value", "control_value"})
        self.assertEqual(metrics.compare_halves(half("t", HIGH), half("c", LOW), "tokens_per_merged_task")["verdict"], "worse")
        self.assertEqual(metrics.compare_halves(half("t", LOW), half("c", LOW), "tokens_per_merged_task")["verdict"], "equal")

    def test_trial_with_no_merged_tasks_is_worse(self):
        t = half("t", LOW, outcome="failed")
        r = metrics.compare_halves(t, half("c", HIGH), "tokens_per_merged_task")
        self.assertEqual(r["verdict"], "worse")

    def test_r4_cheap_unmerged_failures_are_not_better(self):
        # mutation: sum tokens over merged specs only -> the cheap failures vanish and the trial comes out better
        t = half("m", [190] * 3) + half("f", [20] * 2, outcome="failed")
        c = half("c", [200] * 5)
        self.assertNotEqual(metrics.compare_halves(t, c, "tokens_per_merged_task")["verdict"], "better")

    def test_fix_rounds_and_bounces_per_task(self):
        t = [rec(f"t{i}", 100, fix_rounds=0, bounces=0) for i in range(5)]
        c = [rec(f"c{i}", 100, fix_rounds=3 + i % 2, bounces=2 + i % 2) for i in range(5)]
        self.assertEqual(metrics.compare_halves(t, c, "fix_rounds_per_task")["verdict"], "better")
        self.assertEqual(metrics.compare_halves(c, t, "bounces_per_task")["verdict"], "worse")
        self.assertEqual(metrics.compare_halves(t, t, "fix_rounds_per_task")["verdict"], "equal")

    def test_count_guardrails_use_the_quality_veto_inequality(self):
        t = [rec(f"t{i}", 100, red_after_merge=i < 3) for i in range(5)]
        c = half("c", 100)
        self.assertEqual(metrics.compare_halves(t, c, "red_after_merge")["verdict"], "worse")
        t2 = [rec(f"t{i}", 100, red_after_merge=i < 1) for i in range(5)]   # 1 > 0*5 + 1 is false
        self.assertEqual(metrics.compare_halves(t2, c, "red_after_merge")["verdict"], "equal")
        tf = [rec(f"t{i}", 100, outcome="failed" if i < 3 else "merged") for i in range(5)]
        self.assertEqual(metrics.compare_halves(tf, c, "failed_specs")["verdict"], "worse")
        tr = [rec(f"t{i}", 100, final_review_crit_imp=2) for i in range(5)]
        self.assertEqual(metrics.compare_halves(tr, c, "final_review_crit_imp_per_spec")["verdict"], "worse")

    def test_count_guardrail_judges_small_halves_and_is_too_early_only_when_empty(self):
        t = [rec(f"t{i}", 100, red_after_merge=True) for i in range(2)]
        c = half("c", 100)
        self.assertEqual(metrics.compare_halves(t, c, "red_after_merge")["verdict"], "worse")
        self.assertEqual(metrics.compare_halves(t, [], "red_after_merge")["verdict"], "too early")
        self.assertEqual(metrics.compare_halves([], c, "failed_specs")["verdict"], "too early")

    def test_r2_cheaper_but_red_after_merge(self):
        t = [rec(f"t{i}", t_, red_after_merge=i < 3) for i, t_ in enumerate([70, 77, 84, 73, 80])]
        c = half("c", [100, 110, 120, 105, 115])
        self.assertEqual(metrics.compare_halves(t, c, "tokens_per_merged_task")["verdict"], "better")
        self.assertEqual(metrics.compare_halves(t, c, "red_after_merge")["verdict"], "worse")


class BaselineTest(unittest.TestCase):
    CONFIGS = {"seq": {"baseline": True}, "eng": {"baseline": False}}

    def base(self):
        return [rec(f"b{i}", t, budget=None, config="seq") for i, t in enumerate(HIGH)]

    def test_zero_engine_runs_is_too_early(self):
        r = metrics.compare_to_baseline(self.base(), self.CONFIGS, "tokens_per_merged_task")
        self.assertEqual(r["verdict"], "too early")
        self.assertEqual(r["n_trial"], 0)

    def test_engine_runs_against_baseline_configs(self):
        recs = self.base() + half("e", LOW)
        r = metrics.compare_to_baseline(recs, self.CONFIGS, "tokens_per_merged_task")
        self.assertEqual((r["verdict"], r["n_trial"], r["n_control"]), ("better", 5, 5))

    def test_engine_run_baseline_config_record_is_challenger_only(self):
        # mutation: drop the budget filter on the reference -> n_control becomes 6
        recs = self.base() + [rec("e0", 100, config="seq")] + half("e", LOW)
        r = metrics.compare_to_baseline(recs, self.CONFIGS, "tokens_per_merged_task")
        self.assertEqual((r["n_trial"], r["n_control"]), (6, 5))

    def test_count_guardrail_against_baseline_is_not_too_early_with_few_specs(self):
        recs = self.base() + [rec(f"e{i}", 100, red_after_merge=True) for i in range(2)]
        self.assertEqual(metrics.compare_to_baseline(recs, self.CONFIGS, "red_after_merge")["verdict"], "worse")

    def test_since_filters_challengers(self):
        recs = self.base() + half("e", LOW)
        r = metrics.compare_to_baseline(recs, self.CONFIGS, "tokens_per_merged_task", since="2026-11-21T00:00:00Z")
        self.assertEqual((r["verdict"], r["n_trial"]), ("too early", 0))
        r = metrics.compare_to_baseline(recs, self.CONFIGS, "tokens_per_merged_task", since="2026-11-20T10:00:00Z")
        self.assertEqual(r["n_trial"], 5)


if __name__ == "__main__":
    unittest.main()
