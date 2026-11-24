import contextlib, io, json, os, re, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics, usage  # noqa: E402
from metrics_fixtures import cache_main_root  # noqa: E402

SENTENCE = "These numbers see textual conflicts only. Two specs that merge cleanly can still be wrong together."
S1, S2, S3 = "docs/superpowers/specs/s1.md", "docs/superpowers/specs/s2.md", "docs/superpowers/specs/s3.md"


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


def iso(ts):
    return metrics.utc(ts)


_TEMPLATE = {}


def _template():
    """The scratch repo every test starts from, built once per process and copied (it holds no worktrees, so a copy
    is independent of the template and of every other copy). Returns (repo dir, base commit)."""
    if not _TEMPLATE:
        tmp = tempfile.TemporaryDirectory()
        _TEMPLATE["tmp"] = tmp
        r = Path(tmp.name).resolve() / "repo"
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        for name, text in (("f.txt", "a\n"), ("k.txt", "k\n"), ("hot.txt", "\n".join(f"l{i}" for i in range(1, 12)) + "\n")):
            (r / name).write_text(text)
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base")
        _TEMPLATE["repo"] = (r, git(r, "rev-parse", "HEAD"))
    return _TEMPLATE["repo"]


class Base(unittest.TestCase):
    def setUp(self):
        cache_main_root(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name).resolve()
        self.t = t
        self.repo = t / "repo"
        self.repo.mkdir()
        p = mock.patch.dict(os.environ, {"TC_STATE": str(t / "state"), "USAGE_ROOT": str(t / "proj"), "TC_LINEAGE": str(t / "lin")})
        p.start()
        self.addCleanup(p.stop)
        r = self.repo
        shutil.rmtree(r)
        src, self.base = _template()
        shutil.copytree(src, r, symlinks=True)
        self.t0 = float(int(time.time())) - 7200
        self.heads = {}

    def branch(self, name, edits):
        git(self.repo, "checkout", "-q", "-b", name, self.base)
        for f, text in edits.items():
            (self.repo / f).write_text(text)
        git(self.repo, "commit", "-q", "-am", name)
        self.heads[name] = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")

    def batch(self, configs=("A",), assignment=None, at=None):
        metrics.append(self.repo, {"kind": "batch", "batch": "B", "base": self.base, "configs": list(configs),
                                   "assignment": assignment or {}, "groups": [], "at": iso(at or self.t0 - 60)})

    def run_line(self, spec, head=None, **kw):
        d = {"kind": "run", "batch": "B", "spec": spec, "outcome": "merged", "tasks": 2,
             "tokens": {"total": 4000}, "active_min": 10, "lead_share": 0.25, "fix_rounds": 1,
             "manifest": {"recall": 0.5}, "base": self.base, "head": head,
             "stale_base": {"result": "clean", "paths": []},
             "started_at": iso(self.t0), "ended_at": iso(self.t0 + 600), "at": iso(self.t0 + 600),
             "declared_list": [], "touched_list": [], "limits": {"start": None, "record": None}}
        d.update(kw)
        metrics.append(self.repo, d)

    def report(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), "report", "B", *extra])
        return rc, out.getvalue(), err.getvalue()


class GitFixtureTest(Base):
    def setUp(self):
        super().setUp()
        self.branch("s1", {"f.txt": "one\n"})
        self.branch("s2", {"f.txt": "two\n"})
        self.branch("s3", {"k.txt": "three\n"})
        self.batch()
        for spec, br, files in ((S1, "s1", ["f.txt"]), (S2, "s2", ["f.txt"]), (S3, "s3", ["k.txt"])):
            self.run_line(spec, head=self.heads[br], touched_list=files, declared_list=files)

    def test_conflicting_pair_listed_with_path_and_clean_pairs_counted(self):
        rc, out, err = self.report()
        self.assertEqual((rc, err), (0, ""))
        self.assertRegex(out, r"Parallel-buildable pairs: 2 of 3")
        self.assertIn(f"{S1} <-> {S2}: f.txt", out)
        self.assertNotIn(f"{S1} <-> {S3}: ", out)

    def test_sentence_directly_under_the_table(self):
        _, out, _ = self.report()
        lines = out.splitlines()
        i = lines.index(SENTENCE)
        self.assertTrue(lines[i - 1].startswith("|") or lines[i - 1] == "")
        self.assertEqual(out.count(SENTENCE), 1)

    def test_waves_from_touched_and_declared(self):
        _, out, _ = self.report()
        self.assertIn("Waves (touched files): 2, 3 specs / 2 waves = 1.50", out)
        self.assertIn("Waves (declared files): 2, 3 specs / 2 waves = 1.50", out)

    def test_overlap_pairs_and_share(self):
        _, out, _ = self.report()
        self.assertIn(f"{S1} <-> {S2}: declared 1 (f.txt), touched 1 (f.txt)", out)
        self.assertIn("Pairs overlapping: 1 of 3", out)

    def test_conflict_stale_base_conflicts_with_everyone(self):
        self.run_line(S3, head=self.heads["s3"], touched_list=["k.txt"], stale_base={"result": "conflict", "paths": ["k.txt"]})
        _, out, _ = self.report()
        self.assertIn("Parallel-buildable pairs: 0 of 3", out)
        self.assertIn(f"{S1} <-> {S3}: k.txt", out)

    def test_table_rows_use_last_run_per_spec(self):
        self.run_line(S3, head=self.heads["s3"], touched_list=["k.txt"], outcome="failed", tasks=4, tokens={"total": 8000})
        _, out, _ = self.report()
        row = [l for l in out.splitlines() if l.startswith("| " + S3)][0]
        cells = [c.strip() for c in row.strip("|").split("|")]
        self.assertEqual(cells[1:5], ["failed", "4", "8000", "2000"])
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("| " + S3)]), 1)

    def test_pair_probe_failure_is_null_and_missing(self):
        with mock.patch.object(metrics, "_merge_trees", return_value=None):
            _, out, _ = self.report()
        self.assertIn("Parallel-buildable pairs: unavailable", out)
        self.assertIn("parallel_pairs", out)


class SyntheticTest(Base):
    def test_hot_file_and_triangle_waves(self):
        self.batch()
        for s in (S1, S2, S3):
            self.run_line(s, touched_list=["hot.txt", "own-" + s[-5:]], stale_base=None)
        _, out, _ = self.report()
        self.assertIn("Hot files (touched by 3+ specs): hot.txt (3)", out)
        self.assertIn("Waves (touched files): 3, 3 specs / 3 waves = 1.00", out)
        self.assertIn("Pairs overlapping: 3 of 3", out)

    def test_throughput_sum_when_no_overlap_and_union_when_overlap(self):
        self.batch()
        self.run_line(S1, started_at=iso(self.t0), ended_at=iso(self.t0 + 600), active_min=10, tasks=2)
        self.run_line(S2, started_at=iso(self.t0 + 1200), ended_at=iso(self.t0 + 1800), active_min=20, tasks=3, outcome="kept")
        _, out, _ = self.report()
        self.assertIn("Accepted: 1 specs, 2 tasks; batch active 30 min", out)
        self.assertIn("per active hour: 2.00 specs, 4.00 tasks", out)

    def test_overlap_without_db_says_sum(self):
        self.batch()
        self.run_line(S1, started_at=iso(self.t0), ended_at=iso(self.t0 + 600), active_min=10)
        self.run_line(S2, started_at=iso(self.t0 + 300), ended_at=iso(self.t0 + 900), active_min=10)
        _, out, _ = self.report()
        self.assertIn("(sum, windows overlap)", out)

    def test_overlap_union_from_usage_index(self):
        self.batch()
        self.run_line(S1, started_at=iso(self.t0), ended_at=iso(self.t0 + 600), active_min=2, branch="b1")
        self.run_line(S2, started_at=iso(self.t0 + 300), ended_at=iso(self.t0 + 900), active_min=2, branch="b2")
        db = self.t / "u.sqlite"
        conn = usage.connect(db)
        m = int(self.t0 // 60 + 6) * 60  # t0+360..540: inside both windows
        for i, (ts, br) in enumerate(((m, "b1"), (m + 60, "b1"), (m + 60, "b2"), (m + 120, "b2"))):
            conn.execute(f"insert into calls ({','.join(usage.COLS)}) values ({','.join('?' * 16)})",
                         (f"r{i}", "s", ts, "claude-opus-5-5", None, None, None, br, "/x", 0, 0, 1, 1, 0, 0, 0))
        conn.commit()
        conn.close()
        _, out, _ = self.report("--usage-db", str(db))
        self.assertIn("batch active 3 min", out)
        self.assertNotIn("(sum, windows overlap)", out)

    def test_union_uses_the_default_usage_db_when_it_exists(self):
        self.batch()
        self.run_line(S1, started_at=iso(self.t0), ended_at=iso(self.t0 + 600), active_min=2, branch="b1")
        self.run_line(S2, started_at=iso(self.t0 + 300), ended_at=iso(self.t0 + 900), active_min=2, branch="b2")
        _, out, _ = self.report()
        self.assertIn("(sum, windows overlap)", out)          # no db at the default path yet
        conn = usage.connect(usage.db_path())                  # TC_STATE/usage.sqlite
        m = int(self.t0 // 60 + 6) * 60
        for i, (ts, br) in enumerate(((m, "b1"), (m + 60, "b1"), (m + 60, "b2"), (m + 120, "b2"))):
            conn.execute(f"insert into calls ({','.join(usage.COLS)}) values ({','.join('?' * 16)})",
                         (f"r{i}", "s", ts, "claude-opus-5-5", None, None, None, br, "/x", 0, 0, 1, 1, 0, 0, 0))
        conn.commit()
        conn.close()
        _, out, _ = self.report()
        self.assertIn("batch active 3 min", out)
        self.assertNotIn("(sum, windows overlap)", out)

    def test_empty_default_index_falls_back_to_the_sum_with_its_own_label(self):
        self.batch()
        self.run_line(S1, started_at=iso(self.t0), ended_at=iso(self.t0 + 600), active_min=10, branch="b1")
        self.run_line(S2, started_at=iso(self.t0 + 300), ended_at=iso(self.t0 + 900), active_min=10, branch="b2")
        usage.connect(usage.db_path()).close()       # the default index exists but holds no rows
        _, out, _ = self.report()
        self.assertIn("batch active 20 min (sum, index lacks the window)", out)
        self.assertNotIn("batch active 0 min", out)

    def test_limits_start_and_end(self):
        self.batch()
        metrics.append(self.repo, {"kind": "start", "batch": "B", "spec": S1, "at": iso(self.t0), "main": "x",
                                   "limits": {"five_hour": {"used_percentage": 5}, "seven_day": {"used_percentage": 40}}})
        self.run_line(S1, limits={"start": None, "record": {"five_hour": {"used_percentage": 30}, "seven_day": {"used_percentage": 44}}})
        _, out, _ = self.report()
        self.assertIn("Limits at start: five_hour 5, seven_day 40", out)
        self.assertIn("Limits at end: five_hour 30, seven_day 44", out)

    SCOPE = ("Re-reads count files read with Read, cat, sed, head, tail or grep in the new lead's first 10 turns "
             "that the previous lead also read; Grep and Glob calls are not counted.")

    def lead(self, spec, peak, handoffs, rereads, **kw):
        self.run_line(spec, lead_context_peak=peak, lead_handoffs=handoffs, post_handoff_tokens=[1] * handoffs,
                      rereads=rereads, **kw)

    def lead_lines(self, out):
        return [l for l in out.splitlines() if ": Lead: " in l]

    def test_lead_line_with_peak_and_no_handoffs(self):
        self.batch()
        self.lead(S1, 123456, 0, [])
        _, out, _ = self.report()
        self.assertEqual(self.lead_lines(out), [f"{S1}: Lead: peak 123K tokens, 0 handoffs"])
        self.assertNotIn(self.SCOPE, out)
        lines = out.splitlines()
        self.assertTrue(lines[lines.index(self.lead_lines(out)[0]) - 1].startswith("Limits at end"))

    def test_lead_line_with_handoffs_and_rereads_and_the_scope_line(self):
        self.batch()
        self.lead(S1, 200999, 2, [3, None])
        _, out, _ = self.report()
        self.assertEqual(self.lead_lines(out), [f"{S1}: Lead: peak 200K tokens, 2 handoffs, 3 re-reads after handoff"])
        self.assertEqual(out.count(self.SCOPE), 1)
        lines = out.splitlines()
        self.assertEqual(lines[lines.index(self.lead_lines(out)[0]) + 1], self.SCOPE)

    def test_no_scope_line_when_rereads_are_all_null_or_empty(self):
        self.batch()
        self.lead(S1, 1000, 1, [None])
        _, out, _ = self.report()
        self.assertEqual(self.lead_lines(out), [f"{S1}: Lead: peak 1K tokens, 1 handoffs"])
        self.assertNotIn(self.SCOPE, out)

    def test_null_peak_prints_a_dash(self):
        self.batch()
        self.lead(S1, None, 0, [])
        _, out, _ = self.report()
        self.assertEqual(self.lead_lines(out), [f"{S1}: Lead: peak - tokens, 0 handoffs"])

    def test_old_record_without_the_key_has_no_lead_line(self):
        self.batch()
        self.run_line(S1)
        _, out, _ = self.report()
        self.assertEqual(self.lead_lines(out), [])
        self.assertNotIn("Re-reads count", out)

    def test_lead_lines_sorted_by_spec(self):
        self.batch()
        self.lead(S2, 2000, 0, [])
        self.lead(S1, 1000, 0, [])
        _, out, _ = self.report()
        self.assertEqual([l.split(":")[0] for l in self.lead_lines(out)], [S1, S2])

    def test_printed_figures_equal_the_record_fields(self):
        self.batch()
        self.lead(S1, 87654, 2, [4, 1])
        _, out, _ = self.report()
        rec = [d for d in metrics.read_log(self.repo)[0] if d.get("kind") == "run"][-1]
        self.assertEqual(self.lead_lines(out), [
            f"{S1}: Lead: peak {rec['lead_context_peak'] // 1000}K tokens, {rec['lead_handoffs']} handoffs, "
            f"{sum(x for x in rec['rereads'] if x is not None)} re-reads after handoff"])

    def test_limits_missing_lines_for_runs_and_starts(self):
        self.batch()
        metrics.append(self.repo, {"kind": "start", "batch": "B", "spec": S2, "at": iso(self.t0), "main": "x",
                                   "limits": None, "missing": ["limits"],
                                   "missing_reason": {"limits": "no statusline tap with rate_limits at start"}})
        self.run_line(S1, missing_reason={"limits": "backfilled run: no tap reading exists for a past window"})
        _, out, _ = self.report()
        self.assertIn(f"Limits missing: {S1}: backfilled run: no tap reading exists for a past window", out)
        self.assertIn(f"Limits missing: start {S2}: no statusline tap with rate_limits at start", out)

    def test_no_limits_missing_line_without_reasons(self):
        self.batch()
        self.run_line(S1)
        _, out, _ = self.report()
        self.assertNotIn("Limits missing", out)

    def test_limits_at_end_come_from_the_run_with_the_latest_at(self):
        self.batch()
        lim = lambda n: {"start": None, "record": {"five_hour": {"used_percentage": n}, "seven_day": {"used_percentage": n}}}
        self.run_line(S1, at=iso(self.t0 + 900), limits=lim(77))   # latest at, first by spec path
        self.run_line(S3, at=iso(self.t0 + 300), limits=lim(11))
        self.run_line(S2, at=iso(self.t0 + 600), limits=lim(22))
        _, out, _ = self.report()
        self.assertIn("Limits at end: five_hour 77, seven_day 77", out)

    def test_excluded_malformed_and_errors(self):
        self.batch(assignment={S1: "A", S2: "A"})
        self.run_line(S1, touched_list=None, stale_base=None)
        with open(metrics.log_path(self.repo), "a") as f:
            f.write("garbage\n{broken\n")
        metrics.append(self.repo, {"kind": "error", "sub": "record", "reason": "unknown batch X", "at": iso(self.t0 + 100)})
        metrics.append(self.repo, {"kind": "error", "sub": "start", "reason": "too early", "at": iso(self.t0 - 99999)})
        _, out, _ = self.report()
        self.assertIn(f"{S1} (no touched_list)", out)
        self.assertIn(f"{S2} (no run line)", out)
        self.assertIn("Malformed log lines: 2", out)
        self.assertIn("record: unknown batch X", out)
        self.assertNotIn("too early", out)

    def test_failed_record_after_the_last_run_line_is_listed(self):
        self.batch()
        self.run_line(S1)
        later = self.t / "dbdir"
        later.mkdir()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), "record", S2, "--batch", "B", "--usage-db", str(later), "--no-ingest"])
        self.assertEqual(rc, 1)   # a real failing record: the db path is a directory
        _, rep, _ = self.report()
        self.assertRegex(rep, r"Failed commands: record: ")
        # an error dated after the next batch line belongs to that batch, not this one
        metrics.append(self.repo, {"kind": "batch", "batch": "B9", "base": self.base, "configs": ["A"], "assignment": {},
                                   "groups": [], "at": iso(time.time() + 100)})
        metrics.append(self.repo, {"kind": "error", "sub": "start", "reason": "belongs to B9", "at": iso(time.time() + 200)})
        _, rep, _ = self.report()
        self.assertIn("record: ", rep)
        self.assertNotIn("belongs to B9", rep)

    def test_unknown_batch_is_one_line_error(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), "report", "nope"])
        self.assertEqual((rc, out.getvalue(), err.getvalue()), (1, "", "metrics: report: unknown batch nope\n"))

    def test_compare_and_status_hooks_guarded(self):
        (self.repo / "docs/superpowers/metrics").mkdir(parents=True)
        (self.repo / "docs/superpowers/metrics/roadmap").write_text("PCEE x\n")
        for name, text in (("A", True), ("B", False)):
            d = self.repo / "docs/superpowers/metrics/configs"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{name}.md").write_text("```json:config\n" + json.dumps({"id": name, "baseline": text}) + "\n```\n")
        self.batch(configs=("A", "B"))
        self.run_line(S1)
        _, out, _ = self.report()  # Task 5 functions may not exist yet: must not crash
        self.assertIn(SENTENCE, out)
        with mock.patch.object(metrics, "compare_text", create=True, side_effect=lambda repo, c: f"COMPARE {c}") as ct, \
                mock.patch.object(metrics, "status_line", create=True, return_value="STATUS LINE"):
            _, out, _ = self.report()
        ct.assert_called_once_with(self.repo, "B")
        self.assertIn("COMPARE B", out)
        self.assertEqual(out.rstrip("\n").splitlines()[-2:], ["STATUS LINE", "asks: 0"])   # the asks line ends the report

    def test_no_roadmap_no_status_line(self):
        self.batch()
        self.run_line(S1)
        with mock.patch.object(metrics, "status_line", create=True, return_value="STATUS LINE"):
            _, out, _ = self.report()
        self.assertNotIn("STATUS LINE", out)


class ErrorLineTest(Base):
    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_failing_command_appends_error_line_without_paths(self):
        (self.repo / "docs/superpowers/metrics").mkdir(parents=True, exist_ok=True)   # the log is appended only where metrics exist
        rc, _, err = self.main("--repo", str(self.repo), "start", "s.md", "--batch", f"{self.repo}/nope")
        self.assertEqual(rc, 1)
        errs = [l for l in metrics.read_log(self.repo)[0] if l["kind"] == "error"]
        self.assertEqual(len(errs), 1)
        self.assertEqual((errs[0]["sub"],), ("start",))
        self.assertRegex(errs[0]["at"], r"^\d{4}-\d\d-\d\dT")
        self.assertNotIn(str(self.repo), json.dumps(errs[0]))
        self.assertNotIn("/Users/", json.dumps(errs[0]))
        self.assertIn("./nope", errs[0]["reason"])

    def test_home_is_tilde(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.t / "home")}):
            self.assertEqual(metrics.clean_reason(f"cannot read {self.t}/home/x/y", self.repo), "cannot read ~/x/y")

    def test_repo_not_found_prints_and_skips_append(self):
        rc, _, err = self.main("--repo", str(self.t), "defect", "s", "w")
        self.assertEqual(rc, 1)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertFalse(metrics.log_path(self.t).exists())


class RecordDeclaredListTest(unittest.TestCase):
    def test_lists_are_sorted_and_exclude_docs(self):
        info = metrics.parse_tasks(json.dumps({"tasks": [{"description": "```json:metadata\n" + json.dumps(
            {"files": ["z.py", "a.py", "docs/superpowers/x.md"], "modelTier": "standard"}) + "\n```"}]}))
        self.assertEqual(sorted(info["declared"]), ["a.py", "z.py"])


if __name__ == "__main__":
    unittest.main()
