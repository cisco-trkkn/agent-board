"""metrics analyze: fixture runs.jsonl / tasks.jsonl in temp project dirs. No real usage index, HOME, state dir or log."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import metrics, metrics_analyze  # noqa: E402

NOW = metrics._epoch("2026-11-16T12:00:00Z")
DAY = 86400
SINCE = NOW - 7 * DAY
PREV = SINCE - 7 * DAY
TREND_KEYS = ("specs_run", "specs_merged", "specs_failed", "median_usd_per_spec", "p90_usd_per_spec", "median_lead_share",
              "median_fix_rounds_per_spec", "median_elapsed_s", "median_active_min", "questions_per_spec", "rulings_per_spec")


def cur(n=0):
    return metrics.utc(NOW - DAY - n)          # inside the current window


def prv(n=0):
    return metrics.utc(SINCE - DAY - n)        # inside the previous window


def run(spec, ended, **kw):
    d = {"kind": "run", "batch": "B", "spec": spec, "ended_at": ended, "outcome": "merged", "usd": 1.0, "lead_share": 0.5,
         "fix_rounds": 0, "elapsed_s": 100, "active_min": 10, "questions": 0, "rulings": 0, "handoffs": 0,
         "manifest": {"precision": 0.9, "recall": 0.9}}
    d.update(kw)
    return d


def task(spec, n, **kw):
    d = {"spec": spec, "batch": "B", "task_id": n, "subject": f"Task {n}: s", "tier": "standard", "model_mapped": "sonnet",
         "model_used": "claude-sonnet-5", "escalated": False, "usd": 1.0, "tokens": 1000, "fix_rounds": 0,
         "findings": {"critical": 0, "important": 0, "minor": 0}, "review_rounds": 1, "outcome": "complete",
         "code_in_steps": False, "partial": False}
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name).resolve()
        self.dirs = {}

    def project(self, name, runs=(), tasks=()):
        d = self.t / name
        (d / "docs/superpowers/metrics").mkdir(parents=True, exist_ok=True)
        (d / "docs/superpowers/metrics/runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
        (d / "docs/superpowers/metrics/tasks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in tasks))
        self.dirs[name] = str(d)
        return str(d)

    def analyze(self, *names, **kw):
        return metrics_analyze.analyze([self.dirs[n] for n in names], kw.pop("since", SINCE), NOW, **kw)

    def one(self, runs=(), tasks=(), **kw):
        self.project("p", runs, tasks)
        return self.analyze("p", **kw)


class ShapeTest(Base):
    def test_top_level_keys_window_and_projects(self):
        self.project("alpha", [run("s1", cur())])
        self.project("beta", [])
        s = self.analyze("alpha", "beta")
        self.assertEqual(set(s), {"window", "projects", "projects_source", "trends", "by_tier_model", "flags", "coverage"})
        self.assertEqual(s["window"], {"since": metrics.utc(SINCE), "until": metrics.utc(NOW), "previous_since": metrics.utc(PREV)})
        self.assertEqual(s["projects"], ["alpha", "beta"])     # names only, never paths
        self.assertNotIn(str(self.t), json.dumps(s))
        self.assertEqual(set(s["flags"]), {"overpowered", "underpowered", "costly_steps", "handoffs", "forecast"})

    def test_empty_windows_still_valid(self):
        s = self.one()
        self.assertEqual(s["trends"]["specs_run"], {"current": 0, "previous": 0, "change": 0})
        self.assertIsNone(s["trends"]["median_usd_per_spec"]["current"])
        self.assertIsNone(s["trends"]["median_usd_per_spec"]["change"])
        self.assertEqual(s["by_tier_model"], {})
        self.assertEqual(s["coverage"], {"with_cost": 0, "tasks": 0})
        self.assertEqual(s["flags"]["forecast"], {"median_precision": None, "median_recall": None, "below_half": []})
        json.dumps(s)

    def test_window_membership(self):
        runs = [run("in-at-since", metrics.utc(SINCE)),            # boundary: since itself is current
                run("in-at-now", metrics.utc(NOW)),
                run("prev-just-before", metrics.utc(SINCE - 1)),   # mutation: `<` -> `<=` on the previous end moves this
                run("prev-at-start", metrics.utc(PREV)),
                run("too-old", metrics.utc(PREV - 1)),
                run("future", metrics.utc(NOW + 1))]
        t = self.one(runs)["trends"]["specs_run"]
        self.assertEqual((t["current"], t["previous"], t["change"]), (2, 2, 0))

    def test_last_run_per_batch_spec_wins(self):
        s = self.one([run("s1", cur(), usd=1.0), run("s1", cur(), usd=3.0)])
        self.assertEqual(s["trends"]["specs_run"]["current"], 1)
        self.assertEqual(s["trends"]["median_usd_per_spec"]["current"], 3.0)


class TrendsTest(Base):
    def setUp(self):
        super().setUp()
        runs = [run("c1", cur(1), usd=1.0, lead_share=0.2, fix_rounds=0, elapsed_s=100, active_min=10, questions=1, rulings=2),
                run("c2", cur(2), usd=2.0, lead_share=0.4, fix_rounds=1, elapsed_s=200, active_min=20, questions=3, rulings=4, outcome="failed"),
                run("c3", cur(3), usd=10.0, lead_share=0.9, fix_rounds=4, elapsed_s=301, active_min=31, questions=5, rulings=6, outcome="kept"),
                run("c4", cur(4), usd=4.0, lead_share=0.6, fix_rounds=2, elapsed_s=400, active_min=40, questions=7, rulings=8),
                run("p1", prv(1), usd=3.0, lead_share=0.1, fix_rounds=1, elapsed_s=50, active_min=5, questions=0, rulings=0),
                run("p2", prv(2), usd=5.0, lead_share=0.3, fix_rounds=3, elapsed_s=150, active_min=15, questions=2, rulings=2, outcome="failed")]
        self.s = self.one(runs)["trends"]

    def check(self, key, cur_v, prev_v, change):
        self.assertEqual(self.s[key], {"current": cur_v, "previous": prev_v, "change": change}, key)

    def test_counts(self):
        self.check("specs_run", 4, 2, 2)
        self.check("specs_merged", 2, 1, 1)         # c3 is `kept`: run, not merged, not failed
        self.check("specs_failed", 1, 1, 0)

    def test_usd_median_and_p90_nearest_rank(self):
        self.check("median_usd_per_spec", 3.0, 4.0, -1.0)          # (2,4)/(3,5) medians
        self.check("p90_usd_per_spec", 10.0, 5.0, 5.0)             # ceil(0.9*4)=4th of 4 sorted; ceil(0.9*2)=2nd of 2

    def test_other_medians_and_rounding(self):
        self.check("median_lead_share", 0.5, 0.2, 0.3)
        self.check("median_fix_rounds_per_spec", 1.5, 2.0, -0.5)
        self.check("median_elapsed_s", 250.5, 100.0, 150.5)         # 1 decimal
        self.check("median_active_min", 25.5, 10.0, 15.5)
        self.check("questions_per_spec", 4.0, 1.0, 3.0)
        self.check("rulings_per_spec", 5.0, 1.0, 4.0)

    def test_p90_is_nearest_rank_not_max(self):
        # 10 values: ceil(0.9 * 10) = 9th, so 9.0 (mutation: p90 = max gives 10.0)
        s = self.one([run(f"x{i}", cur(i), usd=float(i)) for i in range(1, 11)])["trends"]["p90_usd_per_spec"]
        self.assertEqual(s["current"], 9.0)

    def test_fractional_metrics_are_floats_even_when_the_median_is_whole(self):
        # an int `0` in stats.json would read as 0 decimals and let the evidence check match a claimed 0.4
        s = self.one([run("only", cur(), usd=3, fix_rounds=0, lead_share=1)])["trends"]
        for key in ("median_usd_per_spec", "p90_usd_per_spec", "median_lead_share", "median_fix_rounds_per_spec",
                    "median_elapsed_s", "median_active_min", "questions_per_spec"):
            self.assertIsInstance(s[key]["current"], float, key)
        self.assertIsInstance(s["specs_run"]["current"], int)

    def test_every_trend_key_present(self):
        self.assertEqual(set(self.s), set(TREND_KEYS))

    def test_null_values_skipped_and_change_null_when_one_side_empty(self):
        s = self.one([run("c", cur(), usd=None, lead_share=None), run("c2", cur(2), usd=4.0, lead_share=None),
                      run("p", prv(), usd=None, lead_share=None)])["trends"]
        self.assertEqual(s["median_usd_per_spec"], {"current": 4.0, "previous": None, "change": None})
        self.assertEqual(s["median_lead_share"], {"current": None, "previous": None, "change": None})


class ByTierModelTest(Base):
    def test_groups_by_tier_and_family_with_stats(self):
        tasks = [task("s", 1, usd=1.0, tokens=100, fix_rounds=0, findings={"critical": 0, "important": 1, "minor": 2}),
                 task("s", 2, usd=3.0, tokens=300, fix_rounds=2, escalated=True, outcome="parked",
                      findings={"critical": 1, "important": 0, "minor": 0}),
                 task("s", 3, tier="mechanical", model_used="claude-haiku-5", usd=0.5),
                 task("s", 4, model_used=None, usd=None),
                 task("s", 5, usd=9.0, model_used="claude-sonnet-5")]
        s = self.one([run("s", cur())], tasks)["by_tier_model"]
        self.assertEqual(set(s), {"standard|sonnet", "mechanical|haiku", "standard|unknown"})
        self.assertTrue(all("|" in k and "." not in k for k in s))
        e = s["standard|sonnet"]
        self.assertEqual(set(e), {"tasks", "median_usd", "median_tokens", "median_fix_rounds", "findings_per_task",
                                  "escalation_rate", "failure_rate"})
        self.assertEqual((e["tasks"], e["median_usd"], e["median_tokens"], e["median_fix_rounds"]), (3, 3.0, 300.0, 0.0))
        self.assertEqual(e["findings_per_task"], {"critical": 0.3333, "important": 0.3333, "minor": 0.6667})
        self.assertEqual((e["escalation_rate"], e["failure_rate"]), (0.3333, 0.3333))
        self.assertIsNone(s["standard|unknown"]["median_usd"])

    def test_previous_window_tasks_are_out(self):
        s = self.one([run("old", prv()), run("new", cur())], [task("old", 1), task("new", 1)])["by_tier_model"]
        self.assertEqual(s["standard|sonnet"]["tasks"], 1)

    def test_task_of_an_unknown_run_is_out(self):
        self.assertEqual(self.one([run("a", cur())], [task("zzz", 1)])["by_tier_model"], {})

    def test_last_task_line_per_key_wins(self):
        s = self.one([run("s", cur())], [task("s", 1, usd=1.0), task("s", 1, usd=7.0)])["by_tier_model"]
        self.assertEqual((s["standard|sonnet"]["tasks"], s["standard|sonnet"]["median_usd"]), (1, 7.0))

    def test_coverage(self):
        s = self.one([run("s", cur())], [task("s", 1, usd=1.0), task("s", 2, usd=None, partial=True), task("s", 3)])
        self.assertEqual(s["coverage"], {"with_cost": 2, "tasks": 3})


class FlagsTest(Base):
    def flags(self, runs, tasks):
        return self.one(runs, tasks)["flags"]

    # ---- overpowered: frontier family + code_in_steps + fix_rounds == 0 -------------------------------------------
    def test_overpowered_triggers_for_opus_and_fable(self):
        tasks = [task("s", 1, model_used="claude-opus-5-5", code_in_steps=True, tier="frontier"),
                 task("s", 2, model_used="claude-fable-5-1", code_in_steps=True)]
        rows = self.flags([run("s", cur())], tasks)["overpowered"]
        self.assertEqual([r["task_id"] for r in rows], [1, 2])
        self.assertEqual(set(rows[0]), {"project", "spec", "task_id", "subject", "model_used", "tier"})
        self.assertEqual((rows[0]["project"], rows[0]["tier"], rows[0]["model_used"]), ("p", "frontier", "claude-opus-5-5"))

    def test_overpowered_non_triggers(self):
        tasks = [task("s", 1, model_used="claude-opus-5-5", code_in_steps=True, fix_rounds=1),   # mutation: `== 0` -> `<= 1` flags this
                 task("s", 2, model_used="claude-opus-5-5", code_in_steps=False),                # mutation: ignore code_in_steps flags this
                 task("s", 3, model_used="claude-sonnet-5", code_in_steps=True),                 # not a frontier family
                 task("s", 4, model_used=None, code_in_steps=True)]
        self.assertEqual(self.flags([run("s", cur())], tasks)["overpowered"], [])

    # ---- underpowered -------------------------------------------------------------------------------------------
    def tier_tasks(self, fix_rounds, **kw):
        return [task("s", i + 1, fix_rounds=f, **kw) for i, f in enumerate(fix_rounds)]

    def test_underpowered_median_fix_rounds_needs_five_tasks(self):
        # mutation: `>= 5` -> `> 5` fails the 5-task case; `>= 2` -> `> 2` fails both medians of 2
        four = self.flags([run("s", cur())], self.tier_tasks([2, 2, 2, 2]))["underpowered"]
        self.assertEqual(four, [])
        five = self.flags([run("s", cur())], self.tier_tasks([2, 2, 2, 2, 2]))["underpowered"]
        self.assertEqual(len(five), 1)
        self.assertEqual({k: five[0][k] for k in ("tier_model", "tasks", "median_fix_rounds", "escalation_rate")},
                         {"tier_model": "standard|sonnet", "tasks": 5, "median_fix_rounds": 2.0, "escalation_rate": 0.0})
        self.assertIn("fix rounds", five[0]["reason"])

    def test_underpowered_median_below_two_does_not_trigger(self):
        self.assertEqual(self.flags([run("s", cur())], self.tier_tasks([1, 1, 1, 1, 1, 1]))["underpowered"], [])

    def test_underpowered_escalation_rate_boundary(self):
        # mutation: `>= 0.30` -> `> 0.30` fails the 0.30 case
        def tasks(n_esc, n):
            return [task("s", i + 1, escalated=i < n_esc) for i in range(n)]
        self.assertEqual(self.flags([run("s", cur())], tasks(29, 100))["underpowered"], [])    # 0.29
        hit = self.flags([run("s", cur())], tasks(3, 10))["underpowered"]                     # 0.30
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["escalation_rate"], 0.3)
        self.assertIn("escalation", hit[0]["reason"])

    def test_underpowered_escalation_needs_five_tasks(self):
        # same minimum as the fix-rounds branch (UNDER_MIN_TASKS = 5): 2 escalated of 2 is no evidence
        def tasks(n):
            return [task("s", i + 1, escalated=True) for i in range(n)]
        self.assertEqual(self.flags([run("s", cur())], tasks(4))["underpowered"], [])
        at = self.flags([run("s", cur())], tasks(5))["underpowered"]
        self.assertEqual((len(at), at[0]["tasks"], at[0]["escalation_rate"]), (1, 5, 1.0))

    # ---- costly_steps ---------------------------------------------------------------------------------------------
    def test_costly_steps_top_ten_by_usd_ignoring_null(self):
        tasks = [task("s", i, usd=float(i)) for i in range(1, 13)] + [task("s", 13, usd=None)]
        rows = self.flags([run("s", cur())], tasks)["costly_steps"]
        self.assertEqual([r["task_id"] for r in rows], [12, 11, 10, 9, 8, 7, 6, 5, 4, 3])    # mutation: [:11] adds task 2
        self.assertEqual(set(rows[0]), {"project", "spec", "task_id", "subject", "usd"})

    def test_whole_number_values_in_rows_are_floats(self):
        f = self.flags([run("s", cur(), manifest={"precision": 1, "recall": 0})], [task("s", 1, usd=3)])
        self.assertIsInstance(f["costly_steps"][0]["usd"], float)
        self.assertIsInstance(f["forecast"]["below_half"][0]["recall"], float)

    def test_costly_steps_fewer_than_ten(self):
        self.assertEqual(len(self.flags([run("s", cur())], [task("s", 1), task("s", 2)])["costly_steps"]), 2)

    # ---- handoffs (R2) ---------------------------------------------------------------------------------------------
    def test_handoffs_flag_rows_against_window_median(self):
        runs = [run("h", cur(1), handoffs=2, usd=6.0, active_min=60),         # 6.0 $/h
                run("a", cur(2), usd=2.0, active_min=60),                     # 2.0
                run("b", cur(3), usd=4.0, active_min=60),                     # 4.0 -> median of {6,2,4} = 4.0
                run("z", cur(4), handoffs=1, usd=1.0, active_min=0),          # no active time: no row
                run("n", cur(5), handoffs=1, usd=None, active_min=30),        # no cost: no row
                run("old", prv(), handoffs=3, usd=9.0, active_min=60)]        # previous window: out
        rows = self.flags(runs, [])["handoffs"]
        self.assertEqual(rows, [{"project": "p", "spec": "h", "handoffs": 2, "usd_per_active_hour": 6.0, "median_usd_per_active_hour": 4.0}])

    def test_handoffs_zero_does_not_trigger(self):
        self.assertEqual(self.flags([run("a", cur(), handoffs=0, usd=50.0, active_min=60)], [])["handoffs"], [])

    # ---- forecast ---------------------------------------------------------------------------------------------------
    def test_forecast_medians_and_below_half(self):
        runs = [run("lo", cur(1), manifest={"precision": 0.5, "recall": 0.49}),     # mutation: `< 0.5` -> `<= 0.5` adds "edge"
                run("edge", cur(2), manifest={"precision": 0.9, "recall": 0.5}),
                run("hi", cur(3), manifest={"precision": 0.7, "recall": 0.9}),
                run("none", cur(4), manifest=None)]
        f = self.flags(runs, [])["forecast"]
        self.assertEqual((f["median_precision"], f["median_recall"]), (0.7, 0.5))
        self.assertEqual(f["below_half"], [{"project": "p", "spec": "lo", "recall": 0.49}])


class MultiProjectTest(Base):
    def test_projects_are_combined_and_rows_carry_the_project(self):
        self.project("alpha", [run("s", cur())], [task("s", 1, usd=5.0)])
        self.project("beta", [run("s", cur())], [task("s", 1, usd=7.0)])     # same spec name, other project
        s = self.analyze("alpha", "beta")
        self.assertEqual(s["trends"]["specs_run"]["current"], 2)
        self.assertEqual([(r["project"], r["usd"]) for r in s["flags"]["costly_steps"]], [("beta", 7.0), ("alpha", 5.0)])

    def test_tasks_log_replaces_the_first_projects_tasks_file(self):
        self.project("alpha", [run("s", cur())], [task("s", 1, usd=5.0)])
        other = self.t / "scratch.jsonl"
        other.write_text(json.dumps(task("s", 1, usd=99.0)) + "\n" + json.dumps(task("s", 2, usd=1.0)) + "\n")
        s = self.analyze("alpha", tasks_log=str(other))
        self.assertEqual([r["usd"] for r in s["flags"]["costly_steps"]], [99.0, 1.0])

    def test_malformed_lines_are_skipped(self):
        d = self.project("alpha", [run("s", cur())], [task("s", 1)])
        with open(d + "/docs/superpowers/metrics/runs.jsonl", "a") as f:
            f.write("not json\n[1]\n")
        self.assertEqual(self.analyze("alpha")["trends"]["specs_run"]["current"], 1)

    def test_relative_project_path_still_has_a_name(self):
        d = self.project("alpha", [run("s", cur())])
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(d)
        self.assertEqual(metrics_analyze.analyze(["."], SINCE, NOW)["projects"], ["alpha"])

    def test_project_without_logs_is_fine(self):
        (self.t / "bare").mkdir()
        self.dirs["bare"] = str(self.t / "bare")
        self.assertEqual(self.analyze("bare")["trends"]["specs_run"]["current"], 0)


class LookupTest(Base):
    def leaves(self, d, path=""):
        if isinstance(d, dict):
            for k, v in d.items():
                yield from self.leaves(v, f"{path}.{k}" if path else k)
        elif isinstance(d, list):
            for i, v in enumerate(d):
                yield from self.leaves(v, f"{path}.{i}")
        else:
            yield path, d

    def test_lookup_resolves_every_leaf(self):
        runs = [run("s", cur(), handoffs=1, manifest={"precision": 0.9, "recall": 0.4}), run("p", prv())]
        tasks = [task("s", 1, model_used="claude-opus-5-5", code_in_steps=True), task("s", 2, tier="mechanical", model_used="claude-haiku-5")]
        s = self.one(runs, tasks)
        leaves = list(self.leaves(s))
        self.assertGreater(len(leaves), 60)
        for path, value in leaves:
            self.assertEqual(metrics_analyze.lookup(s, path), value, path)
        self.assertEqual(metrics_analyze.lookup(s, "trends.median_usd_per_spec.current"), 1.0)
        self.assertEqual(metrics_analyze.lookup(s, "by_tier_model.mechanical|haiku.tasks"), 1)

    def test_lookup_missing_step_raises_key_error(self):
        s = self.one([run("s", cur())])
        for bad in ("nope", "trends.nope", "trends.specs_run.current.deeper", "flags.overpowered.0", "trends.specs_run.", ""):
            with self.assertRaises(KeyError, msg=bad):
                metrics_analyze.lookup(s, bad)


class CliTest(Base):
    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), *argv])
        return rc, out.getvalue(), err.getvalue()

    def setUp(self):
        super().setUp()
        self.repo = self.t / "repo"
        self.repo.mkdir()
        os.system(f"git -C {self.repo} init -q -b main")
        self.state = self.t / "state"
        p = mock.patch.dict(os.environ, {"TC_STATE": str(self.state), "HOME": str(self.t / "home")})
        p.start()
        self.addCleanup(p.stop)
        self.project("alpha", [run("s", cur())], [task("s", 1)])
        self.project("beta", [run("s2", cur())], [task("s2", 1), task("s2", 2)])
        self.since = metrics.utc(SINCE)

    def test_summary_line_and_out_path(self):
        out = self.t / "o" / "stats.json"
        with mock.patch("time.time", return_value=NOW):
            rc, o, e = self.cli("analyze", "--since", self.since, "--projects", self.dirs["alpha"], self.dirs["beta"], "--out", str(out))
        self.assertEqual((rc, e), (0, ""), e)
        self.assertEqual(o.strip(), f"analyzed 2 specs, 3 tasks across 2 projects → {out}")
        stats = json.loads(out.read_text())
        self.assertEqual((stats["projects"], stats["projects_source"]), (["alpha", "beta"], "args"))

    def test_json_flag_prints_stats_and_default_path_is_state_analytics(self):
        with mock.patch("time.time", return_value=NOW):
            rc, o, e = self.cli("analyze", "--since", "7d", "--json", "--projects", self.dirs["alpha"])
        self.assertEqual((rc, e), (0, ""), e)
        self.assertEqual(json.loads(o)["trends"]["specs_run"]["current"], 1)
        self.assertEqual(json.loads((self.state / "analytics/stats.json").read_text()), json.loads(o))

    def test_since_forms(self):
        for since, expect in (("7d", NOW - 7 * DAY), ("30d", NOW - 30 * DAY), ("2026-11-01", metrics._epoch("2026-11-01T00:00:00Z")),
                              ("2026-11-02T03:04:05Z", metrics._epoch("2026-11-02T03:04:05Z"))):
            with mock.patch("time.time", return_value=NOW):
                rc, o, e = self.cli("analyze", "--since", since, "--json", "--projects", self.dirs["alpha"])
            self.assertEqual(rc, 0, e)
            self.assertEqual(json.loads(o)["window"]["since"], metrics.utc(expect), since)

    def test_bad_since_is_a_one_line_error(self):
        rc, o, e = self.cli("analyze", "--since", "soon", "--projects", self.dirs["alpha"])
        self.assertEqual(rc, 1)
        self.assertTrue(e.startswith("metrics: analyze: "), e)
        self.assertEqual(len(e.strip().splitlines()), 1)

    def test_tasks_log_flag(self):
        other = self.t / "scratch.jsonl"
        other.write_text("".join(json.dumps(task("s", i)) + "\n" for i in (1, 2, 3, 4)))
        with mock.patch("time.time", return_value=NOW):
            rc, o, e = self.cli("analyze", "--since", self.since, "--tasks-log", str(other), "--projects", self.dirs["alpha"], "--out", str(self.t / "x.json"))
        self.assertIn("1 specs, 4 tasks across 1 projects", o)

    def test_projects_from_overview_and_repo_only_fallback(self):
        ov = {"projects": [{"project": "alpha", "path": self.dirs["alpha"]}, {"project": "beta", "path": self.dirs["beta"]}]}
        with mock.patch("time.time", return_value=NOW), mock.patch.object(metrics_analyze, "overview_projects", return_value=[p["path"] for p in ov["projects"]]):
            rc, o, e = self.cli("analyze", "--since", self.since, "--json")
        self.assertEqual(json.loads(o)["projects_source"], "overview")
        self.assertEqual(json.loads(o)["projects"], ["alpha", "beta"])
        with mock.patch("time.time", return_value=NOW), mock.patch.object(metrics_analyze, "overview_projects", side_effect=OSError("down")):
            rc, o, e = self.cli("analyze", "--since", self.since, "--json")
        self.assertEqual((rc, e), (0, ""), e)
        self.assertEqual(json.loads(o)["projects_source"], "repo-only")
        self.assertEqual(json.loads(o)["projects"], ["repo"])

    def test_overview_projects_parses_the_json_and_fails_on_bad_output(self):
        good = mock.Mock(returncode=0, stdout=json.dumps({"projects": [{"path": "/a/b"}, {"path": "/c"}]}))
        with mock.patch("subprocess.run", return_value=good) as m:
            self.assertEqual(metrics_analyze.overview_projects(), ["/a/b", "/c"])
        self.assertEqual(m.call_args.kwargs["timeout"], 30)
        self.assertEqual(m.call_args.args[0][:2], [sys.executable, "-I"])
        self.assertTrue(m.call_args.args[0][2].endswith("overview.py"))
        for bad in (mock.Mock(returncode=1, stdout=""), mock.Mock(returncode=0, stdout="not json"), mock.Mock(returncode=0, stdout="{}")):
            with mock.patch("subprocess.run", return_value=bad), self.assertRaises(Exception):
                metrics_analyze.overview_projects()


if __name__ == "__main__":
    unittest.main()
