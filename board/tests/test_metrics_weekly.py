"""metrics weekly --dry-run: analyze + recommend + the report text. The model is the fake claude (TC_CLAUDE_BIN); the project
list comes from the temp repo alone (overview_projects patched to fail, so the real board is never asked)."""
import contextlib, io, json, os, re, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
CHECKOUT = HERE.parent
sys.path.insert(0, str(HERE))
import metrics, metrics_analyze, metrics_recommend  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_claude_recommend.sh"
NOW = metrics._epoch("2026-11-16T12:00:00Z")
DAY = 86400


def cur(n=0):
    return metrics.utc(NOW - DAY - n)


def prv(n=0):
    return metrics.utc(NOW - 8 * DAY - n)


def run(spec, ended, **kw):
    d = {"kind": "run", "batch": "B", "spec": spec, "ended_at": ended, "outcome": "merged", "usd": 2.0, "lead_share": 0.5,
         "fix_rounds": 0, "elapsed_s": 100, "active_min": 60, "questions": 0, "rulings": 0, "handoffs": 0,
         "manifest": {"precision": 0.9, "recall": 0.9}}
    d.update(kw)
    return d


def task(spec, n, **kw):
    d = {"spec": spec, "batch": "B", "task_id": n, "subject": f"Task {n}: s", "tier": "standard", "model_mapped": "sonnet",
         "model_used": "claude-sonnet-5", "escalated": False, "usd": 1.0, "tokens": 1000, "fix_rounds": 0,
         "findings": {"critical": 0, "important": 0, "minor": 0}, "outcome": "complete", "code_in_steps": False}
    d.update(kw)
    return d


def item(title, *evidence, **kw):
    d = {"title": title, "change": "do x", "expected_effect": "less y", "risk": "low",
         "evidence": [{"key": k, "value": v} for k, v in evidence]}
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name).resolve()
        self.repo = self.t / "repo"
        (self.repo / "docs/superpowers/metrics").mkdir(parents=True)
        os.system(f"git -C {self.repo} init -q -b main")
        self.argv = self.t / "argv"
        env = {"TC_CLAUDE_BIN": str(FAKE), "TC_STATE": str(self.t / "state"), "HOME": str(self.t / "home"), "FAKE_ARGV": str(self.argv)}
        for k, v in env.items():
            p = mock.patch.dict(os.environ, {k: v})
            p.start()
            self.addCleanup(p.stop)
        for p in (mock.patch("time.time", return_value=NOW),
                  mock.patch.object(metrics_analyze, "overview_projects", side_effect=OSError("down"))):
            p.start()
            self.addCleanup(p.stop)

    def logs(self, runs=(), tasks=()):
        m = self.repo / "docs/superpowers/metrics"
        (m / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
        (m / "tasks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in tasks))

    def answer(self, items=None, rc=0):
        out = self.t / "out.json"
        out.write_text(json.dumps({"result": "```json\n" + json.dumps(items or []) + "\n```"}))
        os.environ["FAKE_RECOMMEND_OUT"] = str(out)
        os.environ["FAKE_RECOMMEND_RC"] = str(rc)
        self.addCleanup(os.environ.pop, "FAKE_RECOMMEND_OUT", None)
        self.addCleanup(os.environ.pop, "FAKE_RECOMMEND_RC", None)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), "weekly", *argv])
        return rc, out.getvalue(), err.getvalue()

    def rich(self):
        s1, s2 = "docs/superpowers/specs/alpha.md", "docs/superpowers/specs/beta.md"
        self.logs([run(s1, cur(1), handoffs=2, usd=6.0, manifest={"precision": 0.9, "recall": 0.4}), run(s2, cur(2), usd=2.0),
                   run("docs/superpowers/specs/old.md", prv(), usd=3.0)],
                  [task(s1, 1, model_used="claude-opus-5-5", code_in_steps=True, tier="frontier", subject="Task 1: wire it"),
                   task(s1, 2, usd=None, escalated=True),
                   *[task(s2, i, fix_rounds=2) for i in range(1, 6)]])


class TextTest(Base):
    def test_sections_in_order(self):
        self.rich()
        self.answer([item("Cut opus", ("trends.specs_run.current", 2), ("trends.median_usd_per_spec.current", 4.0))])
        rc, out, err = self.cli("--dry-run")
        self.assertEqual((rc, err), (0, ""), err)
        marks = [out.index(m) for m in ("Execution analytics, 2026-11-09 → 2026-11-16", "```\nmetric", "Flags:", "Recommendations:", "1. Cut opus",
                                        "(1 of 3 passed the evidence check)", "coverage: ", "stats: ")]
        self.assertEqual(marks, sorted(marks))
        self.assertEqual(len(set(marks)), len(marks))
        self.assertEqual(out.splitlines()[-1], f"stats: {self.t / 'state' / 'analytics' / 'stats.json'}")
        self.assertEqual(out.splitlines()[-2], "coverage: 6/7 tasks with cost data")
        self.assertEqual(out.splitlines()[0], "Execution analytics, 2026-11-09 → 2026-11-16")

    def test_table_has_one_row_per_trend_key(self):
        self.rich()
        self.answer()
        out = self.cli("--dry-run")[1]
        block = out.split("```")[1].strip().splitlines()
        self.assertEqual(re.sub(r"\s+", " ", block[0]), "metric | last week | this week | change")
        rows = {r.split("|")[0].strip(): [c.strip() for c in r.split("|")[1:]] for r in block[1:]}
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows["specs_run"], ["1", "2", "+1"])
        self.assertEqual(rows["median_usd_per_spec"], ["3.0", "4.0", "+1.0"])
        self.assertEqual(rows["median_fix_rounds_per_spec"], ["0.0", "0.0", "0"])
        self.assertEqual(set(rows), set(metrics_analyze.analyze([str(self.repo)], 0, NOW)["trends"]))

    def test_null_cell_is_a_dash_and_change_has_a_sign(self):
        self.logs([run("s", cur(), usd=None, lead_share=0.25)])
        self.answer()
        rows = {r.split("|")[0].strip(): [c.strip() for c in r.split("|")[1:]] for r in self.cli("--dry-run")[1].split("```")[1].strip().splitlines()[1:]}
        self.assertEqual(rows["median_usd_per_spec"], ["–", "–", "–"])
        self.assertEqual(rows["median_lead_share"], ["–", "0.25", "–"])
        self.assertEqual(rows["specs_run"][2], "+1")

    def test_flag_lines(self):
        self.rich()
        self.answer()
        out = self.cli("--dry-run")[1]
        flags = out.split("Flags:")[1].split("Recommendations:")[0].strip().splitlines()
        self.assertIn("- overpowered: alpha.md task 1 Task 1: wire it (claude-opus-5-5, 0 fix rounds)", flags)
        self.assertTrue(any(l.startswith("- underpowered: standard|sonnet:") and "median fix rounds 2.0 over 6 tasks" in l for l in flags), flags)
        self.assertTrue(any(l.startswith("- costly_steps: ") and "$1.0" in l for l in flags), flags)
        self.assertIn("- handoffs: alpha.md 2 handoffs, $6.0/h vs median $4.0/h", flags)
        self.assertIn("- forecast: alpha.md recall 0.4 (below 0.5; medians: precision 0.9, recall 0.65)", flags)
        self.assertTrue(all(len(l) <= 160 for l in flags), [len(l) for l in flags])

    def test_long_flag_line_is_capped_at_160(self):
        self.logs([run("s", cur())], [task("s", 1, usd=9.0, subject="Task 1: " + "very long " * 40)])
        self.answer()
        flags = self.cli("--dry-run")[1].split("Flags:")[1].split("Recommendations:")[0].strip().splitlines()
        self.assertTrue(flags and all(len(l) <= 160 for l in flags))
        self.assertTrue(flags[0].endswith("…"))

    def test_no_flags_prints_flags_none(self):
        self.logs([run("s", cur())], [])                  # no tasks: no costly_steps rows either
        self.answer()
        out = self.cli("--dry-run")[1]
        self.assertIn("Flags: none\nRecommendations:", out)
        self.assertNotIn("Flags:\n", out)

    def test_recommendation_layout(self):
        self.rich()
        self.answer([item("T one", ("trends.specs_run.current", 2), ("trends.specs_run.previous", 1),
                          change="make the change\nacross two lines", expected_effect="fewer", risk="small")])
        out = self.cli("--dry-run")[1]
        rec = out.split("Recommendations:\n")[1].split("(1 of 3")[0]
        self.assertEqual(rec, "1. T one\n   change: make the change across two lines\n   expected: fewer\n   risk: small\n"
                              "   evidence: trends.specs_run.current = 2; trends.specs_run.previous = 1\n")

    def test_unavailable_line_and_rest_of_text_survive(self):
        self.rich()
        self.answer(rc=1)
        rc, out, err = self.cli("--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("Recommendations:\nrecommendations unavailable: claude exited 1\ncoverage: ", out)
        self.assertNotIn("passed the evidence check", out)
        self.assertIn("```\nmetric", out)

    def test_dropped_items_are_not_in_the_text(self):
        self.rich()
        self.answer([item("good", ("trends.specs_run.current", 2)), item("bad", ("trends.nope", 1))])
        out = self.cli("--dry-run")[1]
        self.assertIn("1. good", out)
        self.assertNotIn("bad", out.split("Recommendations:")[1])
        self.assertIn("(1 of 3 passed the evidence check)", out)

    def test_since_sets_the_header_start(self):
        self.rich()
        self.answer()
        self.assertEqual(self.cli("--dry-run", "--since", "30d")[1].splitlines()[0], "Execution analytics, 2026-10-17 → 2026-11-16")

    def test_tasks_log_is_passed_through(self):
        self.rich()
        self.answer()
        scratch = self.t / "scratch.jsonl"
        scratch.write_text(json.dumps(task("docs/superpowers/specs/alpha.md", 1, usd=5.0)) + "\n")
        out = self.cli("--dry-run", "--tasks-log", str(scratch))[1]
        self.assertIn("coverage: 1/1 tasks with cost data", out)


class FlowTest(Base):
    def test_no_runs_skips_model(self):
        # mutation: call recommend unconditionally and the fake writes its argv file
        self.logs([run("docs/superpowers/specs/old.md", prv())])           # only a previous-window run
        self.answer([item("x", ("trends.specs_run.current", 0))])
        rc, out, err = self.cli("--dry-run")
        self.assertEqual((rc, out, err), (0, "no runs in the window; nothing to post\n", ""))
        self.assertFalse(self.argv.exists(), "the model was called")
        self.assertFalse((self.t / "state" / "analytics" / "recommend.json").exists())

    def test_without_dry_run_refuses(self):
        self.rich()
        self.answer()
        rc, out, err = self.cli()
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(err.strip(), "metrics: weekly: posting needs part 2 (discord bridge); use --dry-run")
        self.assertFalse(self.argv.exists())

    def test_recommend_json_is_written_beside_stats(self):
        self.rich()
        self.answer([item("good", ("trends.specs_run.current", 2))])
        self.cli("--dry-run")
        r = json.loads((self.t / "state" / "analytics" / "recommend.json").read_text())
        self.assertEqual((r["passed"], r["asked"]), (1, 3))


class HelpTest(unittest.TestCase):
    NEW = ("backfill-tasks", "analyze", "recommend", "weekly --dry-run")

    def test_help_lists_subs(self):
        text = (CHECKOUT / "bin/tmux-ctl").read_text()
        m = re.search(r"sed -n '2,(\d+)p' \"\$0\"", text)
        shown = [re.sub(r"^# ?", "", l) for l in text.splitlines()[1:int(m.group(1))]]
        for sub in self.NEW:
            self.assertTrue(any(l.lstrip().startswith(f"tmux-ctl metrics {sub}") for l in shown), sub)
        self.assertEqual(shown[-1], "")                                              # the range ends on the header's blank line
        self.assertTrue(shown[-2].startswith("  tmux-ctl metrics <sub>"), shown[-2])  # after the metrics line, as before
        for sub in ("backfill-tasks", "analyze", "recommend", "weekly"):
            self.assertIn(sub, metrics.SUBS)

    def test_the_help_range_covers_the_whole_comment_block(self):
        text = (CHECKOUT / "bin/tmux-ctl").read_text().splitlines()
        m = re.search(r"sed -n '2,(\d+)p' \"\$0\"", "\n".join(text))
        n = int(m.group(1))
        self.assertEqual(text[n - 1], "#")
        self.assertTrue(text[n - 2].startswith("#   tmux-ctl metrics <sub>"))
        self.assertTrue(text[n].startswith("# send/run only type"))


if __name__ == "__main__":
    unittest.main()
