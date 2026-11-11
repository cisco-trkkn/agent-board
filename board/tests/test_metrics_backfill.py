import contextlib, io, json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
CHECKOUT = HERE.parent
sys.path.insert(0, str(HERE))
import metrics, usage  # noqa: E402

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-")
SNAPSHOT = Path.home() / ".local/state/agent-board/metrics/usage-snapshot-20261111.sqlite"
UNTIL = "2026-11-10T12:00:00Z"   # the appendix's period: later merges (this spec among them) are out of it
# appendix of docs/superpowers/specs/2026-11-10-queue-metrics-design.md: name -> (active min, priced $, tokens M)
APPENDIX = {
    "overnight-queue": (34, 11.39, 33.5), "mod-agent-status": (112, 44.76, 103.3), "mod-team-band": (36, 11.65, 29.1),
    "mod-usage-gauges": (40, 10.74, 34.5), "tasks-window-polish": (33, 11.81, 33.0), "artifact-session-id": (19, 5.73, 20.3),
    "mod-shell-hooks": (64, 23.12, 66.3), "mod-overview": (40, 14.45, 48.3), "queue-keep-awake": (42, 16.85, 46.6),
    "lead-named-agents": (26, 9.63, 30.0), "relay-launch-check": (39, 9.90, 41.3), "remote-access": (114, 28.98, 102.2),
}
TOTALS = {"tokens_m": 588.4, "usd": 199.01, "active_min": 599}


def git(repo, *a, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"{int(date)} +0000"
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True, env=env).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name).resolve()
        self.repo = self.t / "repo"
        self.repo.mkdir()
        p = mock.patch.dict(os.environ, {"TC_STATE": str(self.t / "state"), "USAGE_ROOT": str(self.t / "proj"),
                                         "TC_LINEAGE": str(self.t / "lin")})
        p.start()
        self.addCleanup(p.stop)
        self.db = self.t / "u.sqlite"
        conn = usage.connect(self.db)
        conn.close()

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), *argv])
        return rc, out.getvalue(), err.getvalue()

    def runs(self, path=None):
        lines = metrics.read_log(self.repo)[0] if path is None else [json.loads(l) for l in Path(path).read_text().splitlines()]
        return [l for l in lines if l.get("kind") == "run"]


class FixtureBackfillTest(Base):
    def setUp(self):
        super().setUp()
        r = self.repo
        self.T = 1_790_000_000
        git(r, "init", "-q", "-b", "main")
        (r / "f.txt").write_text("1\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base", date=self.T)
        # gamma's plan is on main before its branch exists: found by the branch name
        (r / "docs/superpowers/plans").mkdir(parents=True)
        (r / "docs/superpowers/plans/2026-01-03-gamma.md").write_text("# G\n\n**Spec:** `docs/superpowers/specs/gamma-design.md`\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "gamma plan", date=self.T + 50)
        self.merges = {}
        for i, (name, plan) in enumerate((("alpha", True), ("beta", True), ("gamma", False), ("nofan", False))):
            git(r, "checkout", "-q", "-b", f"feat/{name}", "main")
            if plan:
                (r / f"docs/superpowers/plans/2026-01-0{i + 1}-{name}.md").write_text(f"# P\n\n**Spec:** `docs/superpowers/specs/{name}-design.md`\n")
                git(r, "add", "."); git(r, "commit", "-q", "-m", f"{name} plan", date=self.T + 100 * (i + 1))
            (r / f"{name}.txt").write_text("x\n")
            git(r, "add", "."); git(r, "commit", "-q", "-m", f"{name} work", date=self.T + 100 * (i + 1) + 10)
            git(r, "checkout", "-q", "main")
            self.merges[name] = self.T + 1000 * (i + 1)
            git(r, "merge", "-q", "--no-ff", "-m", f"Merge branch 'feat/{name}'", f"feat/{name}", date=self.merges[name])
        self.plan_ts = {}

    def backfill(self, *extra):
        return self.cli("backfill", "--since", "2026-01-01", "--usage-db", str(self.db), "--no-ingest", *extra)

    def test_windows_chain_and_fields(self):
        rc, out, err = self.backfill()
        self.assertEqual((rc, err), (0, ""))
        runs = self.runs()
        self.assertEqual([r["spec"] for r in runs], ["docs/superpowers/specs/alpha-design.md", "docs/superpowers/specs/beta-design.md",
                                                     "docs/superpowers/specs/gamma-design.md"])   # nofan has no plan: skipped
        for r in runs:
            self.assertEqual((r["batch"], r["config"], r["backfilled"], r["window"], r["outcome"]), ("backfill", "seq-sdd", True, "derived", "merged"))
        a, b, g = runs
        self.assertEqual(a["ended_at"], metrics.utc(self.merges["alpha"]))
        self.assertEqual(b["started_at"], a["ended_at"])                 # the second starts at the first's merge
        self.assertEqual(b["ended_at"], metrics.utc(self.merges["beta"]))
        self.assertEqual(g["started_at"], b["ended_at"])
        self.assertEqual(a["started_at"], metrics.utc(self.T + 100))     # the first starts at its plan's first commit
        self.assertEqual(a["elapsed_s"], self.merges["alpha"] - (self.T + 100))
        self.assertEqual(a["merge"], git(self.repo, "rev-parse", "main~3"))
        self.assertEqual(g["plan"], "docs/superpowers/plans/2026-01-03-gamma.md")
        self.assertEqual(g["branch"], "feat/gamma")

    def test_backfilled_lines_carry_no_live_limits_reading(self):
        live = {"five_hour": {"used_percentage": 39}, "seven_day": {"used_percentage": 58}}
        with mock.patch.object(usage, "plan_limits", return_value=live):   # a fresh tap reading exists today
            rc, _, err = self.backfill()
        self.assertEqual((rc, err), (0, ""))
        for r in self.runs():
            self.assertEqual(r["limits"], {"start": None, "record": None})
            for k in ("limits", "ready_at", "wait_s"):
                self.assertIn(k, r["missing"])
                if k != "limits":
                    self.assertIsNone(r[k])

    def test_rerun_appends_nothing(self):
        self.backfill()
        before = metrics.log_path(self.repo).read_text()
        rc, out, _ = self.backfill()
        self.assertEqual(rc, 0)
        self.assertEqual(metrics.log_path(self.repo).read_text(), before)
        self.assertEqual(len(before.splitlines()), 3)

    def test_skip_counts_a_run_line_in_any_batch(self):
        metrics.append(self.repo, {"kind": "run", "batch": "2026-01-01-1", "spec": "docs/superpowers/specs/beta-design.md"})
        self.backfill()
        specs = [r["spec"] for r in self.runs() if r["batch"] == "backfill"]
        self.assertEqual(specs, ["docs/superpowers/specs/alpha-design.md", "docs/superpowers/specs/gamma-design.md"])

    def test_until_and_since_bound_the_merges(self):
        rc, _, _ = self.cli("backfill", "--since", "2026-01-01", "--until", metrics.utc(self.merges["beta"] + 1),
                            "--usage-db", str(self.db), "--no-ingest")
        self.assertEqual(len(self.runs()), 2)

    def test_log_option_writes_elsewhere(self):
        tmp_log = self.t / "other.jsonl"
        rc, _, err = self.cli("backfill", "--since", "2026-01-01", "--usage-db", str(self.db), "--no-ingest", "--log", str(tmp_log))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(len(self.runs(tmp_log)), 3)
        self.assertFalse(metrics.log_path(self.repo).exists())

    def test_plan_without_spec_line_uses_the_plan_path(self):
        git(self.repo, "checkout", "-q", "-b", "feat/nospec", "main")
        (self.repo / "docs/superpowers/plans/2026-01-09-nospec.md").write_text("# no spec header\n")
        git(self.repo, "add", "."); git(self.repo, "commit", "-q", "-m", "p", date=self.T + 9000)
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "Merge branch 'feat/nospec'", "feat/nospec", date=self.T + 9500)
        self.backfill()
        self.assertEqual(self.runs()[-1]["spec"], "docs/superpowers/plans/2026-01-09-nospec.md")

    def test_records_use_the_first_parent_as_the_stale_base(self):
        self.backfill()
        a = self.runs()[0]
        self.assertEqual(a["stale_base"], {"result": "clean", "paths": []})


class RealStateTest(Base):
    def test_backfill_matches_the_appendix(self):
        if not SNAPSHOT.exists():
            self.skipTest(f"no usage snapshot at {SNAPSHOT}")
        snap = self.t / "snap.sqlite"
        shutil.copyfile(SNAPSHOT, snap)       # the snapshot itself stays untouched
        c = sqlite3.connect(snap)
        n = c.execute("select count(*) from calls where ts < ?", (1793000000,)).fetchone()[0]
        c.close()
        if n == 0:
            self.skipTest("the snapshot holds no rows before 2026-11-05")
        top = Path(subprocess.run(["git", "-C", str(CHECKOUT), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                                  check=True).stdout.strip())
        log = self.t / "real.jsonl"
        env = {"USAGE_ROOT": str(self.t / "no-transcripts")}      # read-only on the repo; no transcript scan
        with mock.patch.dict(os.environ, env):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = metrics.main(["--repo", str(top), "backfill", "--since", "2026-11-04", "--until", UNTIL,
                                   "--usage-db", str(snap), "--no-ingest", "--log", str(log)])
        self.assertEqual((rc, err.getvalue()), (0, ""), err.getvalue())
        runs = self.runs(log)
        names = [re.sub(r"-design$", "", re.sub(r"^\d{4}-\d\d-\d\d-", "", Path(r["spec"]).stem)) for r in runs]
        got = {n: r for n, r in zip(names, runs)}
        table = ["", f"{'spec':22} {'active':>7} {'app':>5}  {'usd':>8} {'app':>7}  {'tokM':>7} {'app':>6}  handoffs"]
        for n, r in zip(names, runs):
            a = APPENDIX.get(n, (None, None, None))
            table.append(f"{n:22} {r['active_min']:7} {str(a[0]):>5}  {r['usd']:8.2f} {str(a[1]):>7}  {r['tokens']['total'] / 1e6:7.1f} {str(a[2]):>6}  {r['handoffs']}")
        print("\n".join(table))
        self.assertEqual(sorted(got), sorted(APPENDIX), "\n".join(table))
        tok = sum(r["tokens"]["total"] for r in runs) / 1e6
        usd = sum(r["usd"] for r in runs)
        act = sum(r["active_min"] for r in runs)
        print(f"totals: tokens {tok:.1f}M (appendix {TOTALS['tokens_m']}), usd {usd:.2f} ({TOTALS['usd']}), active {act} ({TOTALS['active_min']})")
        self.assertEqual(len(runs), 12)
        self.assertAlmostEqual(tok, TOTALS["tokens_m"], delta=TOTALS["tokens_m"] * 0.02, msg="\n".join(table))
        self.assertAlmostEqual(usd, TOTALS["usd"], delta=TOTALS["usd"] * 0.02, msg="\n".join(table))
        self.assertAlmostEqual(act, TOTALS["active_min"], delta=TOTALS["active_min"] * 0.02, msg="\n".join(table))


SWEEP = r"""
import sys, unittest
sys.path.insert(0, {board!r})
import metrics
sink = open({sink!r}, "a")
orig = metrics.append
def spy(repo, obj):
    import json
    sink.write(json.dumps(obj, sort_keys=True) + "\n")
    sink.flush()
    orig(repo, obj)
metrics.append = spy
suite = unittest.defaultTestLoader.discover({tests!r}, pattern={pattern!r})
res = unittest.TextTestRunner(stream=open({log!r}, "w")).run(suite)
sys.exit(0 if res.wasSuccessful() else 1)
"""


ABS_VALUE = re.compile(r'"/[A-Za-z]')
TEMP_ROOTS = sorted({tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())} - {"/"})


class PlanlessMergeWindowTest(Base):
    """A plan-less merge between two plan merges starts the second window when the second plan came after it."""

    def build(self, plan_before_fix):
        r, T = self.repo, 1_790_000_000
        self.T = T
        git(r, "init", "-q", "-b", "main")
        (r / "f.txt").write_text("1\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base", date=T)

        def branch(name, plan, when_plan, when_work, when_merge):
            git(r, "checkout", "-q", "-b", f"feat/{name}", "main")
            if plan:
                (r / "docs/superpowers/plans").mkdir(parents=True, exist_ok=True)
                (r / f"docs/superpowers/plans/2026-01-01-{name}.md").write_text(f"# P\n\n**Spec:** `docs/superpowers/specs/{name}-design.md`\n")
                git(r, "add", "."); git(r, "commit", "-q", "-m", f"{name} plan", date=when_plan)
            (r / f"{name}.txt").write_text("x\n")
            git(r, "add", "."); git(r, "commit", "-q", "-m", f"{name} work", date=when_work)
            git(r, "checkout", "-q", "main")
            git(r, "merge", "-q", "--no-ff", "-m", f"Merge branch 'feat/{name}'", f"feat/{name}", date=when_merge)

        branch("alpha", True, T + 100, T + 110, T + 1000)
        branch("fixit", False, None, T + 1500, T + 2000)
        branch("beta", True, T + (1200 if plan_before_fix else 2500), T + 2600, T + 3000)

    def window_starts(self):
        rc, _, err = self.cli("backfill", "--since", "2026-01-01", "--usage-db", str(self.db), "--no-ingest")
        self.assertEqual((rc, err), (0, ""))
        return {r["spec"].split("/")[-1]: r["started_at"] for r in self.runs()}

    def test_window_starts_at_the_planless_merge_when_the_plan_came_after_it(self):
        self.build(plan_before_fix=False)
        st = self.window_starts()
        self.assertEqual(st["beta-design.md"], metrics.utc(self.T + 2000))
        self.assertEqual(st["alpha-design.md"], metrics.utc(self.T + 100))

    def test_window_starts_at_the_previous_plan_merge_when_the_plan_predates_the_planless_one(self):
        self.build(plan_before_fix=True)
        self.assertEqual(self.window_starts()["beta-design.md"], metrics.utc(self.T + 1000))


class PrivacySweepTest(unittest.TestCase):
    def sweep(self, lines, label):
        home = os.path.expanduser("~")
        for l in lines:
            self.assertNotIn("/Users/", l, f"{label}: {l[:200]}")
            self.assertNotIn(home, l, f"{label}: {l[:200]}")
            self.assertIsNone(UUID.search(l), f"{label}: {l[:200]}")
            self.assertIsNone(ABS_VALUE.search(l), f"{label}: absolute path value in {l[:200]}")
            for root in TEMP_ROOTS:
                self.assertNotIn(root, l, f"{label}: temp root in {l[:200]}")

    def test_committed_run_log(self):
        p = CHECKOUT / "docs/superpowers/metrics/runs.jsonl"
        if not p.exists():
            self.skipTest("docs/superpowers/metrics/runs.jsonl is not committed yet")
        lines = p.read_text().splitlines()
        self.sweep(lines, "runs.jsonl")
        print(f"checked {len(lines)} lines (committed runs.jsonl)")
        self.assertGreater(len(lines), 0)

    @unittest.skipIf(os.environ.get("METRICS_SWEEP_INNER"), "already inside the sweep's own run")
    def test_every_line_the_other_metrics_tests_write(self):
        with tempfile.TemporaryDirectory() as d:
            sink, log = Path(d) / "sink.jsonl", Path(d) / "run.log"
            code = SWEEP.format(board=str(HERE), sink=str(sink), tests=str(HERE / "tests"),
                                pattern="test_metrics_[!b]*.py", log=str(log))
            p = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                               env={**os.environ, "METRICS_SWEEP_INNER": "1"})
            self.assertEqual(p.returncode, 0, p.stderr + log.read_text()[-2000:])
            lines = sink.read_text().splitlines()
        self.assertGreater(len(lines), 20)
        self.sweep(lines, "test logs")
        print(f"checked {len(lines)} lines (every run-log line the other test_metrics_* tests wrote)")


if __name__ == "__main__":
    unittest.main()
