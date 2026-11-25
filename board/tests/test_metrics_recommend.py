"""metrics recommend: the model step is the fake claude in fixtures/ (TC_CLAUDE_BIN). The real claude is never run."""
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
CHECKOUT = HERE.parent
sys.path.insert(0, str(HERE))
import analytics_post, metrics, metrics_analyze, metrics_recommend  # noqa: E402

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

NO_USAGE = {"cost_usd": None, "tokens": None}


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
        self.assertEqual(([i["title"] for i in r["items"]], r["dropped"]), (["one", "two", "three"],
                         [{"title": "four", "reason": "beyond three", "item": item("four", ("trends.specs_run.current", 4))}]))

    def test_dropped_entry_keeps_the_full_item(self):
        bad = item("ghost", ("nope", 1), change="the whole text")
        self.answer(GOOD[:1] + [bad])
        self.run_stats()
        self.assertEqual(self.result()["dropped"], [{"title": "ghost", "reason": "unknown key nope", "item": bad}])

    def test_count_line(self):
        # mutation: print the count of asked items, or put the line before the item lines
        self.answer(GOOD[:1] + [item("ghost", ("nope", 1))])
        rc, out, err = self.run_stats()
        self.assertEqual(out.splitlines()[-1], "(1 of 3 passed the evidence check)")
        self.assertEqual(out.splitlines()[0], "- one")


class ProseNumbersTest(Base):
    def kept(self, **fields):
        """Titles kept and the dropped list for one item citing escalation_rate 0.3333 and median_usd current 3.46."""
        it = item("t", ("by_tier_model.standard|sonnet.escalation_rate", 0.3333), ("trends.median_usd_per_spec.current", 3.46))
        it.update(fields)
        self.answer([it])
        self.run_stats()
        r = self.result()
        return [i["title"] for i in r["items"]], r["dropped"]

    def test_uncited_number_in_prose_dropped(self):
        # mutation: skip the prose check, or check only `change`, and these survive
        for field in ("title", "change", "expected_effect"):
            with self.subTest(field):
                kept, dropped = self.kept(**{field: "cuts the cost to 4 per spec"} if field != "title" else {"title": "cut cost to 4"})
                self.assertEqual(kept, [])
                self.assertEqual(dropped[0]["reason"], f"uncited number 4 in {field}")

    def test_stderr_line_names_the_uncited_number(self):
        it = item("t", ("trends.specs_run.current", 4), change="run 9 specs")
        self.answer([it])
        rc, out, err = self.run_stats()
        self.assertEqual(err.strip(), 'metrics: recommend: dropped "t": uncited number 9 in change')

    def test_cited_numbers_in_prose_kept(self):
        kept, dropped = self.kept(change="median cost 3.46 per spec; escalation is 0.3333", expected_effect="3.46 falls")
        self.assertEqual((kept, dropped), (["t"], []))

    def test_cited_number_matches_after_rounding_to_the_stats_decimals(self):
        kept, dropped = self.kept(change="escalation 0.33333 and 3.460 per spec")
        self.assertEqual(kept, ["t"])
        kept, dropped = self.kept(change="cost 3.5 per spec")
        self.assertEqual(kept, [])

    def test_percent_matches_a_stats_ratio(self):
        self.assertEqual(self.kept(change="escalation of 33% on standard")[0], ["t"])
        self.assertEqual(self.kept(change="escalation of 33.3% on standard")[0], ["t"])
        kept, dropped = self.kept(change="escalation of 50% on standard")          # mutation: match any percent
        self.assertEqual((kept, dropped[0]["reason"]), ([], "uncited number 50% in change"))

    def test_key_tokens_model_names_and_list_numbers_are_not_numbers(self):
        kept, dropped = self.kept(title="Move by_tier_model.standard|sonnet.tasks to claude-opus-5-5 or sonnet-5 (p90 cost)",
                                  change="1. watch trends.specs_run.current.0 and flags.overpowered.0.model_used")
        self.assertEqual((len(kept), dropped), (1, []))

    def test_non_string_prose_fields_are_ignored(self):
        self.assertEqual(self.kept(risk="a risk of 7 percent")[0], ["t"])            # risk is not checked


# The second item of the real stream-json run (docs/superpowers/notes/2026-11-16-execution-analytics-e2e.md §3), verbatim; it was
# dropped with `uncited number 5 in change` because the quoted `Task 5: …` subjects are cited string evidence.
REAL_SUBJECT_ITEM = {
    "title": "Split the largest plan tasks so no single task is a costly step",
    "change": "In plans for test-suite and tooling work, split any task that bundles several files or an audit plus fixes into smaller tasks, each with a complete spec. The two costliest steps were 'Task 5: Speed up the three slow zsh files' and 'Task 6: Parallel-safety audit and fixes'. Split each into one task per file or per audit area.",
    "expected_effect": "The costly_steps list shrinks, and the p90 cost per spec falls from 42.46 USD. Median fix rounds per spec stay at or below 3.5.",
    "evidence": [
        {"key": "flags.costly_steps.0.usd", "value": 6.82},
        {"key": "flags.costly_steps.0.subject", "value": "Task 5: Speed up the three slow zsh files"},
        {"key": "flags.costly_steps.1.usd", "value": 5.92},
        {"key": "flags.costly_steps.1.subject", "value": "Task 6: Parallel-safety audit and fixes"},
        {"key": "trends.p90_usd_per_spec.current", "value": 42.46},
        {"key": "trends.median_fix_rounds_per_spec.current", "value": 3.5}],
    "risk": "Cost data covers only 43 of 90 tasks (coverage.with_cost, coverage.tasks), so the costly-step list may miss expensive tasks. Smaller tasks add dispatch and review overhead, which could raise the lead share of cost."}
REAL_STATS = {"trends": {"p90_usd_per_spec": {"current": 42.46, "previous": None, "change": None},
                         "median_fix_rounds_per_spec": {"current": 3.5, "previous": None, "change": None}},
              "flags": {"costly_steps": [
                  {"project": "agent-board", "spec": "docs/superpowers/specs/2026-11-10-fast-test-suite-design.md", "task_id": 5,
                   "subject": "Task 5: Speed up the three slow zsh files", "usd": 6.82},
                  {"project": "agent-board", "spec": "docs/superpowers/specs/2026-11-10-fast-test-suite-design.md", "task_id": 6,
                   "subject": "Task 6: Parallel-safety audit and fixes", "usd": 5.92}]}}


class CitedStringTest(unittest.TestCase):
    def test_numbers_inside_cited_strings_are_not_uncited(self):
        self.assertIsNone(metrics_recommend.check_item(REAL_SUBJECT_ITEM, REAL_STATS))

    def test_a_number_outside_the_cited_string_still_drops(self):
        it = dict(REAL_SUBJECT_ITEM, change=REAL_SUBJECT_ITEM["change"] + " Aim for 7 tasks.")
        self.assertEqual(metrics_recommend.check_item(it, REAL_STATS), "uncited number 7 in change")

    def test_uncited_string_does_not_hide_numbers(self):
        # the quote is not in the item's evidence: its `5` stays uncited
        it = dict(REAL_SUBJECT_ITEM, evidence=[e for e in REAL_SUBJECT_ITEM["evidence"] if not e["key"].endswith("0.subject")])
        self.assertEqual(metrics_recommend.check_item(it, REAL_STATS), "uncited number 5 in change")


class ParsingTest(Base):
    def test_accepts_fence_bare_list_and_items_object(self):
        for wrap in ("fence", "bare", "items"):
            with self.subTest(wrap):
                self.answer(GOOD, wrap=wrap)
                self.assertEqual(self.run_stats()[0], 0)
                self.assertEqual(self.result()["passed"], 3)
                self.rec.unlink()

    def test_prose_brackets_before_the_array_do_not_win(self):
        # mutation: take the first decodable list, and [1] (or [2, 3]) is returned
        text = "See [1] and [2, 3] for background.\n" + json.dumps(GOOD)
        out = self.t / "out.json"
        out.write_text(json.dumps({"result": text}))
        os.environ["FAKE_RECOMMEND_OUT"] = str(out)
        self.addCleanup(os.environ.pop, "FAKE_RECOMMEND_OUT", None)
        self.assertEqual(self.run_stats()[0], 0)
        self.assertEqual(self.result()["passed"], 3)

    def test_unparseable_answer_is_unavailable(self):
        self.answer([], wrap="garbage")
        rc, out, err = self.run_stats()
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "recommendations unavailable: no JSON result")
        self.assertEqual(self.result(), {"items": [], "unavailable": "no JSON result", "usage": NO_USAGE})

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
        self.assertEqual(self.result(), {"items": [], "unavailable": "claude exited 1", "usage": {"cost_usd": None, "tokens": None}})

    def fake_doc(self, **extra):
        out = self.t / "out.json"
        out.write_text(json.dumps(dict({"type": "result", "result": json.dumps(GOOD)}, **extra)))
        os.environ["FAKE_RECOMMEND_OUT"] = str(out)
        os.environ["FAKE_RECOMMEND_RC"] = "0"
        self.addCleanup(os.environ.pop, "FAKE_RECOMMEND_OUT", None)
        self.addCleanup(os.environ.pop, "FAKE_RECOMMEND_RC", None)

    def test_usage_parsed_from_the_claude_json(self):
        self.fake_doc(total_cost_usd=0.12, usage={"input_tokens": 10, "output_tokens": 20,
                                                  "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40})
        self.assertEqual(metrics_recommend.recommend(self.stats)["usage"],
                         {"cost_usd": 0.12, "tokens": {"input": 10, "output": 20, "cache_read": 30, "cache_write": 40}})

    def test_usage_is_none_when_the_json_has_none(self):
        # mutation: index doc["usage"] / u["input_tokens"] without .get -> KeyError
        self.fake_doc()
        self.assertEqual(metrics_recommend.recommend(self.stats)["usage"], {"cost_usd": None, "tokens": None})
        self.fake_doc(usage={"input_tokens": 1})
        self.assertEqual(metrics_recommend.recommend(self.stats)["usage"],
                         {"cost_usd": None, "tokens": {"input": 1, "output": None, "cache_read": None, "cache_write": None}})

    def test_usage_in_the_unavailable_shape(self):
        self.answer(GOOD, rc=1)
        self.assertEqual(metrics_recommend.recommend(self.stats)["usage"], {"cost_usd": None, "tokens": None})

    def test_timeout_is_unavailable(self):
        os.environ["FAKE_SLEEP"] = "30"
        self.addCleanup(os.environ.pop, "FAKE_SLEEP", None)
        with mock.patch.object(metrics_recommend, "TIMEOUT_S", 1):
            rc, out, err = self.run_stats()
        self.assertEqual(rc, 0)
        self.assertEqual(self.result(), {"items": [], "unavailable": "timeout after 1 s", "usage": NO_USAGE})

    def test_missing_claude_binary_is_unavailable(self):
        os.environ["TC_CLAUDE_BIN"] = str(self.t / "no-such-claude")
        rc, out, err = self.run_stats()
        self.assertEqual(rc, 0)
        self.assertEqual(self.result(), {"items": [], "unavailable": "claude not found", "usage": NO_USAGE})

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

    def test_relative_stats_path_is_resolved(self):
        # mutation: use the path as given: cwd becomes the parent but the prompt line stays relative
        self.answer(GOOD)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.t)
        self.assertEqual(self.cli("--stats", "an/stats.json")[0], 0)
        last = (self.t / "stdin").read_text().rstrip("\n").splitlines()[-1]
        self.assertEqual(last, f"Stats file: {self.stats}")
        self.assertTrue(Path(last.split(": ", 1)[1]).is_absolute() and Path(last.split(": ", 1)[1]).exists())
        self.assertEqual(self.result()["passed"], 3)                                  # recommend.json beside the real file

    def test_recommend_function_with_a_relative_path(self):
        self.answer(GOOD)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.t)
        self.assertEqual(metrics_recommend.recommend("an/stats.json")["passed"], 3)
        self.assertEqual((self.t / "stdin").read_text().rstrip("\n").splitlines()[-1], f"Stats file: {self.stats}")

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
                       "exactly three", "must also appear in that item's evidence", "evidence", "expected_effect", "title", "change", "risk"):
            self.assertIn(phrase, text, phrase)


class NoModelLabelTest(unittest.TestCase):
    def flags(self, key):
        return {"overpowered": [], "costly_steps": [], "handoffs": [],
                "underpowered": [{"tier_model": key, "tasks": 6, "median_fix_rounds": 2.0, "escalation_rate": 0.0,
                                  "reason": "median fix rounds 2.0 over 6 tasks"}],
                "forecast": {"median_precision": None, "median_recall": None, "below_half": []}}

    def test_terminal_and_discord_say_no_model_recorded(self):
        self.assertEqual(metrics_recommend._flag_lines(self.flags("standard|nomodel")),
                         ["- underpowered: standard|no model recorded: median fix rounds 2.0 over 6 tasks"])
        rows = analytics_post._flag_rows(self.flags("standard|nomodel"))
        esc = analytics_post.escape   # Discord text escapes markdown characters, `|` included
        self.assertEqual([r[2] for r in rows],
                         [f"underpowered: {esc('standard|no model recorded')}: {esc('median fix rounds 2.0 over 6 tasks')}"])

    def test_other_keys_unchanged(self):
        self.assertEqual(metrics_recommend._flag_lines(self.flags("standard|sonnet")),
                         ["- underpowered: standard|sonnet: median fix rounds 2.0 over 6 tasks"])


if __name__ == "__main__":
    unittest.main()
