import contextlib, io, json, os, re, subprocess, sys, tempfile, time, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CHECKED = []


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.repo = t / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        self.state = t / "state"
        self.state.mkdir()
        self.env = mock_env(TC_STATE=str(self.state), USAGE_ROOT=str(t / "proj"))
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = metrics.main(["--repo", str(self.repo), *argv])
            except SystemExit as e:
                rc = e.code
        return rc or 0, out.getvalue(), err.getvalue()

    def lines(self):
        ls, bad = metrics.read_log(self.repo)
        for l in ls:
            s = json.dumps(l)
            CHECKED.append(s)
            self.assertNotIn("/Users/", s)
            self.assertIsNone(UUID.search(s))
        return ls

    def cfg(self, name, baseline=False):
        d = self.repo / "docs/superpowers/metrics/configs"
        d.mkdir(parents=True, exist_ok=True)
        (d / (name + ".md")).write_text("prose\n\n```json:config\n" + json.dumps({"id": name, "baseline": baseline}) + "\n```\n")


def mock_env(**kv):
    from unittest import mock
    return mock.patch.dict(os.environ, kv)


class LogTest(Base):
    def test_malformed_skipped_and_counted(self):
        p = metrics.log_path(self.repo)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"kind":"run","batch":"b","spec":"s","n":1}\nnot json\n[1]\n{"kind":"zzz"}\n')
        ls, bad = metrics.read_log(self.repo)
        self.assertEqual(bad, 2)
        self.assertEqual(len(ls), 2)  # unknown kind kept

    def test_last_run_supersedes_and_unknown_ignored(self):
        ls = [{"kind": "run", "batch": "b", "spec": "s", "n": 1}, {"kind": "analysis", "batch": "b", "spec": "s"},
              {"kind": "run", "batch": "b", "spec": "s", "n": 2}, {"kind": "run", "batch": "b", "spec": "t", "n": 3}]
        r = metrics.last_runs(ls)
        self.assertEqual(r[("b", "s")]["n"], 2)
        self.assertEqual(len(r), 2)

    def test_missing_log(self):
        self.assertEqual(metrics.read_log(self.repo), ([], 0))

    def test_config_and_gate_fences(self):
        self.cfg("a", True)
        self.assertEqual(metrics.load_config(self.repo, "a"), {"id": "a", "baseline": True})
        self.assertIsNone(metrics.load_config(self.repo, "nope"))
        g = self.repo / "docs/superpowers/metrics/gates"
        g.mkdir(parents=True)
        (g / "x.md").write_text("t\n```json:gate\n{\"min\": 3}\n```\n")
        self.assertEqual(metrics.load_gate(self.repo, "x"), {"min": 3})
        self.assertIsNone(metrics.load_gate(self.repo, "y"))


class AssignTest(unittest.TestCase):
    def test_deterministic(self):
        sp = ["a.md", "b.md", "c.md", "d.md"]
        a = metrics.assign("2026-11-11-1", sp, [], ["X", "Y"], "X")
        self.assertEqual(a, metrics.assign("2026-11-11-1", sp, [], ["X", "Y"], "X"))

    def test_alternates_from_baseline(self):
        sp = ["a.md", "b.md", "c.md", "d.md"]
        a = metrics.assign("2026-11-11-1", sp, [], ["X", "Y"], "Y")
        order = sorted(sp, key=lambda s: metrics.unit_key("2026-11-11-1", s))
        self.assertEqual([a[s] for s in order], ["Y", "X", "Y", "X"])

    def test_group_stays_together(self):
        sp = [f"s{i}.md" for i in range(8)]
        for bid in ("2026-11-11-1", "2026-11-11-2", "2026-11-12-1"):
            a = metrics.assign(bid, sp, [["s0.md", "s1.md"], ["s2.md", "s3.md"]], ["X", "Y"], "X")
            self.assertEqual(a["s0.md"], a["s1.md"])
            self.assertEqual(a["s2.md"], a["s3.md"])

    def test_one_config(self):
        a = metrics.assign("b", ["a", "b"], [], ["X"], "X")
        self.assertEqual(a, {"a": "X", "b": "X"})


class CommandsTest(Base):
    def test_batch_start_line_and_counter(self):
        self.cfg("A", True)
        self.cfg("B")
        rc, out, err = self.run_main("batch", "start", "--config", "A", "--config", "B", "s1.md", "s2.md", "s3.md")
        self.assertEqual((rc, err), (0, ""))
        ol = out.splitlines()
        today = time.strftime("%Y-%m-%d", time.gmtime())
        self.assertEqual(ol[0], today + "-1")
        self.assertEqual(len(ol), 4)
        b = [l for l in self.lines() if l["kind"] == "batch"][0]
        self.assertEqual(set(b), {"kind", "batch", "base", "configs", "assignment", "groups", "at"})
        self.assertEqual(b["base"], git(self.repo, "rev-parse", "main"))
        self.assertEqual(b["configs"], ["A", "B"])
        self.assertEqual(set(b["assignment"]), {"s1.md", "s2.md", "s3.md"})
        for line in ol[1:]:
            spec, cfg = line.split(" ")
            self.assertEqual(b["assignment"][spec], cfg)
        rc, out, _ = self.run_main("batch", "start", "--config", "A", "s1.md")
        self.assertEqual(out.splitlines()[0], today + "-2")

    def test_baseline_first_even_if_listed_second(self):
        self.cfg("A")
        self.cfg("B", True)
        self.run_main("batch", "start", "--config", "A", "--config", "B", "s1.md", "s2.md")
        b = self.lines()[0]
        first = sorted(["s1.md", "s2.md"], key=lambda s: metrics.unit_key(b["batch"], s))[0]
        self.assertEqual(b["assignment"][first], "B")

    def test_groups_recorded_and_together(self):
        self.cfg("A", True)
        self.cfg("B")
        sp = [f"s{i}.md" for i in range(6)]
        self.run_main("batch", "start", "--config", "A", "--config", "B", "--group", "s0.md,s1.md", *sp)
        b = self.lines()[0]
        self.assertEqual(b["groups"], [["s0.md", "s1.md"]])
        self.assertEqual(b["assignment"]["s0.md"], b["assignment"]["s1.md"])

    def test_start_line(self):
        self.cfg("A", True)
        _, out, _ = self.run_main("batch", "start", "--config", "A", "s1.md")
        bid = out.splitlines()[0]
        rc, _, err = self.run_main("start", "s1.md", "--batch", bid)
        self.assertEqual((rc, err), (0, ""))
        s = [l for l in self.lines() if l["kind"] == "start"][0]
        self.assertEqual((s["batch"], s["spec"]), (bid, "s1.md"))
        self.assertEqual(s["main"], git(self.repo, "rev-parse", "main"))
        self.assertIsNone(s["limits"])
        self.assertEqual(s["missing"], ["limits"])

    def test_start_limits_from_tap(self):
        self.cfg("A", True)
        _, out, _ = self.run_main("batch", "start", "--config", "A", "s1.md")
        d = self.state / "statusline"
        d.mkdir()
        (d / "x.json").write_text(json.dumps({"session_id": "12345678-1234-1234-1234-123456789abc",
                                              "received_at": time.time(),
                                              "rate_limits": {"five_hour": {"used_percentage": 12}, "seven_day": {"used_percentage": 3}}}))
        self.run_main("start", "s1.md", "--batch", out.splitlines()[0])
        s = [l for l in self.lines() if l["kind"] == "start"][0]
        self.assertEqual(s["limits"], {"five_hour": {"used_percentage": 12}, "seven_day": {"used_percentage": 3}})
        self.assertNotIn("missing", s)

    def test_start_unknown_batch(self):
        rc, out, err = self.run_main("start", "s1.md", "--batch", "nope")
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(err, "metrics: start: unknown batch nope\n")

    def test_defect(self):
        rc, _, _ = self.run_main("defect", "s1.md", "broke it")
        self.assertEqual(rc, 0)
        d = self.lines()[0]
        self.assertEqual((d["kind"], d["spec"], d["what"]), ("defect", "s1.md", "broke it"))
        self.assertRegex(d["date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_no_subcommand_is_a_one_line_usage_error(self):
        rc, _, err = self.run_main()
        self.assertEqual(rc, 1)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertTrue(err.startswith("metrics: metrics: usage: metrics <"))

    def test_missing_config_one_line_error(self):
        rc, out, err = self.run_main("batch", "start", "--config", "ghost", "s1.md")
        self.assertEqual(rc, 1)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertTrue(err.startswith("metrics: batch start: "))

    def test_not_a_repo(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = metrics.main(["--repo", self.tmp.name, "defect", "s", "w"])
            except SystemExit as e:
                rc = e.code
        self.assertEqual(rc, 1)
        self.assertEqual(len(err.getvalue().splitlines()), 1)


class ZPrivacySummary(unittest.TestCase):
    def test_zz_print_count(self):
        print(f"private-data check: {len(CHECKED)} log lines checked")


if __name__ == "__main__":
    unittest.main()
