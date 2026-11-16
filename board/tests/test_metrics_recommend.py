"""metrics recommend: the model step is the fake claude in fixtures/ (TC_CLAUDE_BIN). The real claude is never run."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
CHECKOUT = HERE.parent
sys.path.insert(0, str(HERE))
import metrics, metrics_analyze, metrics_recommend  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_claude_recommend.sh"
STATS = {"trends": {"median_usd_per_spec": {"current": 3.46, "previous": 4.0, "change": -0.54},
                    "specs_run": {"current": 4, "previous": 2, "change": 2}},
         "by_tier_model": {"standard|sonnet": {"tasks": 5, "escalation_rate": 0.3333, "median_fix_rounds": 2.0}},
         "flags": {"overpowered": [{"spec": "s", "model_used": "claude-opus-5-5"}]}}


def item(title, *evidence, **kw):
    d = {"title": title, "change": "do x", "expected_effect": "less y", "risk": "low",
         "evidence": [{"key": k, "value": v} for k, v in evidence]}
    d.update(kw)
    return d


GOOD = [item("one", ("trends.median_usd_per_spec.current", 3.46)),
        item("two", ("trends.specs_run.current", 4), ("by_tier_model.standard|sonnet.tasks", 5)),
        item("three", ("flags.overpowered.0.model_used", "claude-opus-5-5"))]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name).resolve()
        self.repo = self.t / "repo"
        self.repo.mkdir()
        os.system(f"git -C {self.repo} init -q -b main")
        self.stats = self.t / "an" / "stats.json"
        self.stats.parent.mkdir()
        self.stats.write_text(json.dumps(STATS))
        self.rec = self.stats.parent / "recommend.json"
        self.env = {"TC_CLAUDE_BIN": str(FAKE), "TC_STATE": str(self.t / "state"), "HOME": str(self.t / "home"),
                    "FAKE_ARGV": str(self.t / "argv"), "FAKE_STDIN": str(self.t / "stdin"), "FAKE_CWD": str(self.t / "cwd")}
        p = mock.patch.dict(os.environ, self.env)
        p.start()
        self.addCleanup(p.stop)

    def answer(self, items, wrap="fence", rc=0):
        text = json.dumps(items)
        result = {"fence": f"Here you go:\n```json\n{text}\n```\nDone.", "bare": f"Sure. {text} Hope it helps.",
                  "items": json.dumps({"items": items}), "garbage": "I cannot help with that."}[wrap]
        out = self.t / "out.json"
        out.write_text(json.dumps({"type": "result", "result": result}))
        os.environ["FAKE_RECOMMEND_OUT"] = str(out)
        os.environ["FAKE_RECOMMEND_RC"] = str(rc)
        self.addCleanup(os.environ.pop, "FAKE_RECOMMEND_OUT", None)
        self.addCleanup(os.environ.pop, "FAKE_RECOMMEND_RC", None)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), "recommend", *argv])
        return rc, out.getvalue(), err.getvalue()

    def run_stats(self, *extra):
        return self.cli("--stats", str(self.stats), *extra)

    def result(self):
        return json.loads(self.rec.read_text())


class EvidenceCheckTest(Base):
    def test_three_valid_kept(self):
        self.answer(GOOD)
        rc, out, err = self.run_stats()
        self.assertEqual((rc, err), (0, ""))
        r = self.result()
        self.assertEqual(([i["title"] for i in r["items"]], r["dropped"], r["passed"], r["asked"]), (["one", "two", "three"], [], 3, 3))
        self.assertEqual(out.splitlines(), ["- one", "- two", "- three", "(3 of 3 passed the evidence check)"])

    def test_unknown_key_dropped(self):
        # mutation: skip the lookup (or treat KeyError as a match) and the item survives
        self.answer(GOOD[:2] + [item("ghost", ("trends.no_such.current", 1))])
        rc, out, err = self.run_stats()
        self.assertEqual(rc, 0)
        self.assertEqual(err.strip(), 'metrics: recommend: dropped "ghost": unknown key trends.no_such.current')
        self.assertEqual([d["title"] for d in self.result()["dropped"]], ["ghost"])
        self.assertTrue(out.rstrip().endswith("(2 of 3 passed the evidence check)"))

    def test_wrong_value_dropped(self):
        self.answer(GOOD[:2] + [item("liar", ("trends.median_usd_per_spec.current", 3.5))])
        rc, out, err = self.run_stats()
        self.assertEqual(err.strip(), 'metrics: recommend: dropped "liar": trends.median_usd_per_spec.current is 3.46, not 3.5')
        self.assertEqual(self.result()["passed"], 2)

    def test_rounded_value_kept(self):
        # mutation: compare the model's number unrounded and 0.333333 != 0.3333 drops it
        self.answer([item("r1", ("by_tier_model.standard|sonnet.escalation_rate", 0.33333333)),
                     item("r2", ("trends.specs_run.current", 4.0)),             # an int in stats: 0 decimals
                     item("r3", ("trends.median_usd_per_spec.change", -0.5400001))])
        rc, out, err = self.run_stats()
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(self.result()["passed"], 3)

    def test_rounding_goes_to_the_stats_decimals_not_further(self):
        self.answer([item("close", ("by_tier_model.standard|sonnet.escalation_rate", 0.334))])   # 0.334 rounds to 0.334 != 0.3333
        self.run_stats()
        self.assertEqual(self.result()["passed"], 0)

    def test_strings_compare_exactly_and_types_do_not_mix(self):
        self.answer([item("s1", ("flags.overpowered.0.model_used", "claude-opus-5-5")),
                     item("s2", ("flags.overpowered.0.model_used", "claude-opus-5")),
                     item("s3", ("trends.specs_run.current", "4"))])                # a string for a number
        self.run_stats()
        self.assertEqual([i["title"] for i in self.result()["items"]], ["s1"])
        self.assertEqual([d["title"] for d in self.result()["dropped"]], ["s2", "s3"])
        self.answer([item("b", ("trends.specs_run.current", True))])                # a bool for a number: True == 1 in python
        self.stats.write_text(json.dumps(dict(STATS, trends={"specs_run": {"current": 1}})))
        self.run_stats()
        self.assertEqual(self.result()["items"], [])
        self.stats.write_text(json.dumps({"x": {"label": "5"}}))                    # a number for a string: no str() coercion
        self.answer([item("n", ("x.label", 5))])
        self.run_stats()
        self.assertEqual(self.result()["items"], [])

    def test_a_key_that_resolves_to_a_container_or_null_never_matches(self):
        STATS2 = dict(STATS, trends=dict(STATS["trends"], nothing={"current": None}))
        self.stats.write_text(json.dumps(STATS2))
        self.answer([item("c", ("trends.specs_run", 4)), item("n", ("trends.nothing.current", None))])
        self.run_stats()
        self.assertEqual(self.result()["passed"], 0)

    def test_every_evidence_entry_must_pass(self):
        self.answer([item("half", ("trends.specs_run.current", 4), ("trends.specs_run.previous", 99))])
        self.run_stats()
        self.assertEqual(self.result()["items"], [])

    def test_item_missing_a_field_is_dropped(self):
        bad = item("nofx")
        del bad["expected_effect"]
        noev = item("noev")
        noev["evidence"] = []
        self.answer([bad, noev, GOOD[0]])
        rc, out, err = self.run_stats()
        reasons = {d["title"]: d["reason"] for d in self.result()["dropped"]}
        self.assertEqual(reasons, {"nofx": "missing field expected_effect", "noev": "no evidence"})
        self.assertEqual(self.result()["passed"], 1)

    def test_more_than_three_keeps_the_first_three(self):
        self.answer(GOOD + [item("four", ("trends.specs_run.current", 4))])
        self.run_stats()
        r = self.result()
        self.assertEqual(([i["title"] for i in r["items"]], r["dropped"]), (["one", "two", "three"], [{"title": "four", "reason": "beyond three"}]))

    def test_count_line(self):
        # mutation: print the count of asked items, or put the line before the item lines
        self.answer(GOOD[:1] + [item("ghost", ("nope", 1))])
        rc, out, err = self.run_stats()
        self.assertEqual(out.splitlines()[-1], "(1 of 3 passed the evidence check)")
        self.assertEqual(out.splitlines()[0], "- one")


class ParsingTest(Base):
    def test_accepts_fence_bare_list_and_items_object(self):
        for wrap in ("fence", "bare", "items"):
            with self.subTest(wrap):
                self.answer(GOOD, wrap=wrap)
                self.assertEqual(self.run_stats()[0], 0)
                self.assertEqual(self.result()["passed"], 3)
                self.rec.unlink()

    def test_unparseable_answer_is_unavailable(self):
        self.answer([], wrap="garbage")
        rc, out, err = self.run_stats()
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "recommendations unavailable: no JSON result")
        self.assertEqual(self.result(), {"items": [], "unavailable": "no JSON result"})

    def test_stdout_that_is_not_json_is_unavailable(self):
        out = self.t / "raw.txt"
        out.write_text("plain text, not the json envelope")
        os.environ["FAKE_RECOMMEND_OUT"] = str(out)
        self.addCleanup(os.environ.pop, "FAKE_RECOMMEND_OUT", None)
        self.assertEqual(self.run_stats()[1].strip(), "recommendations unavailable: no JSON result")


class RunTest(Base):
    def test_model_failure_unavailable(self):
        # mutation: let the non-zero exit raise (rc 1) instead of writing `unavailable`
        self.answer(GOOD, rc=1)
        rc, out, err = self.run_stats()
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "recommendations unavailable: claude exited 1")
        self.assertEqual(self.result(), {"items": [], "unavailable": "claude exited 1"})

    def test_timeout_is_unavailable(self):
        os.environ["FAKE_SLEEP"] = "30"
        self.addCleanup(os.environ.pop, "FAKE_SLEEP", None)
        with mock.patch.object(metrics_recommend, "TIMEOUT_S", 1):
            rc, out, err = self.run_stats()
        self.assertEqual(rc, 0)
        self.assertEqual(self.result(), {"items": [], "unavailable": "timeout after 1 s"})

    def test_missing_claude_binary_is_unavailable(self):
        os.environ["TC_CLAUDE_BIN"] = str(self.t / "no-such-claude")
        rc, out, err = self.run_stats()
        self.assertEqual(rc, 0)
        self.assertEqual(self.result(), {"items": [], "unavailable": "claude not found"})

    def test_argv_flags(self):
        # mutation: drop any one flag (e.g. --strict-mcp-config) and its pair below fails
        self.answer(GOOD)
        self.run_stats()
        argv = (self.t / "argv").read_text().split("\n")[:-1]
        self.assertEqual(argv, ["-p", "--model", "sonnet", "--effort", "medium", "--tools", "Read", "--allowedTools", "Read",
                                "--permission-mode", "dontAsk", "--no-session-persistence", "--strict-mcp-config",
                                "--output-format", "json"])

    def test_prompt_on_stdin_ends_with_the_stats_path_and_cwd_is_the_stats_dir(self):
        self.answer(GOOD)
        self.run_stats()
        stdin = (self.t / "stdin").read_text()
        self.assertEqual(stdin.rstrip("\n").splitlines()[-1], f"Stats file: {self.stats}")
        self.assertTrue(stdin.startswith((CHECKOUT / "claude/analytics.md").read_text()))
        self.assertEqual((self.t / "cwd").read_text().strip(), str(self.stats.parent))

    def test_without_stats_it_runs_analyze_first(self):
        self.answer(GOOD)
        with mock.patch.object(metrics_analyze, "overview_projects", side_effect=OSError("down")):
            rc, out, err = self.cli("--since", "30d")
        self.assertEqual(rc, 0, err)
        stats = self.t / "state" / "analytics" / "stats.json"
        self.assertEqual(json.loads(stats.read_text())["projects_source"], "repo-only")
        self.assertTrue((stats.parent / "recommend.json").exists())
        self.assertEqual((self.t / "stdin").read_text().rstrip("\n").splitlines()[-1], f"Stats file: {stats}")
        self.assertIn("(0 of 3 passed the evidence check)", out)      # the analyzed stats lack the fixture's keys

    def test_missing_stats_file_is_a_one_line_error(self):
        rc, out, err = self.cli("--stats", str(self.t / "nope" / "stats.json"))
        self.assertEqual(rc, 1)
        self.assertEqual(err.strip(), "metrics: recommend: stats file not found: stats.json")


class PromptTest(unittest.TestCase):
    def test_prompt_rules(self):
        text = (CHECKOUT / "claude/analytics.md").read_text().lower()
        for phrase in ("routing", "plan granularity", "review setup", "team shape", "workflow rules", "small", "testable",
                       "never recommend editing the orchestrator", "its own prompt", "next week", "stats.json", "exact values",
                       "exactly three", "evidence", "expected_effect", "title", "change", "risk"):
            self.assertIn(phrase, text, phrase)


if __name__ == "__main__":
    unittest.main()
