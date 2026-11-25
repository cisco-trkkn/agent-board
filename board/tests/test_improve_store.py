import json, os, shutil, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_store as S  # noqa: E402
import improve_fixtures as F  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EV = [{"type": "run", "ref": "r1"}]
PATCH = "--- a/docs/x.md\n+++ b/docs/x.md\n@@ -1,1 +1,1 @@\n-a\n+b\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"TC_ENGINE_DIR": self.tmp, "TC_STATE": self.state})
        self.env.start()
        F.engine_db(self.tmp)
        self.s = S.Store("proj")

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def ins(self, **kw):
        a = dict(source="manual", kind="rule", target="claude/x.md", patch=PATCH, evidence=EV)
        a.update(kw)
        return self.s.insert(**a)

    def events(self):
        c = sqlite3.connect(Path(self.tmp) / "proj.sqlite")
        try:
            return [(k, json.loads(d)) for k, d in c.execute("SELECT kind, detail FROM events ORDER BY seq")]
        finally:
            c.close()


class SchemaTest(Base):
    def test_statement_is_byte_identical_to_db_js(self):
        # mutation: drop a column from one copy -> this fails
        self.assertIn(S.PROPOSALS_SQL, (REPO / "engine/lib/engine/db.js").read_text())

    def test_no_events_table_refuses(self):
        d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"TC_ENGINE_DIR": d}):
            with self.assertRaises(S.ImproveError) as cm:
                S.Store("proj")
        self.assertEqual(str(cm.exception), f"improve: no engine database at {Path(d) / 'proj.sqlite'}")

    def test_creates_only_proposals(self):
        c = sqlite3.connect(Path(self.tmp) / "proj.sqlite")
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        c.close()
        self.assertEqual(names, {"events", "proposals", })


class InsertTest(Base):
    def test_ids_increment(self):
        self.assertEqual(self.ins(target="a"), "P1")
        self.assertEqual(self.ins(target="b"), "P2")

    def test_dream_prose_procedure_is_high(self):
        # mutation: drop source= from derive -> low
        pid = self.ins(source="dream", kind="procedure", target="docs/x.md")
        self.assertEqual(self.s.get(pid)["class"], "high")
        pid = self.ins(source="manual", kind="procedure", target="docs/y.md")
        self.assertEqual(self.s.get(pid)["class"], "low")

    def test_no_deterministic_evidence(self):
        for ev in ([], [{"type": "note", "ref": "x"}], None):
            with self.assertRaisesRegex(S.ImproveError, "no deterministic evidence"):
                self.ins(evidence=ev)

    def test_dedupe_returns_existing(self):
        a = self.ins()
        n = len(self.events())
        self.assertEqual(self.ins(), a)
        self.assertEqual(len(self.events()), n)

    def test_retire_cap_per_tick(self):
        for i in range(5):
            self.ins(kind="retire", target=f"t{i}", patch=None, tick=7)
        with self.assertRaisesRegex(S.ImproveError, "retire cap"):
            self.ins(kind="retire", target="t5", patch=None, tick=7)
        self.ins(kind="retire", target="t5", patch=None, tick=8)   # another tick is fine

    def test_retire_cap_without_tick_counts_24h(self):
        for i in range(5):
            self.ins(kind="retire", target=f"t{i}", patch=None)
        with self.assertRaisesRegex(S.ImproveError, "retire cap"):
            self.ins(kind="retire", target="t5", patch=None)
        c = sqlite3.connect(Path(self.tmp) / "proj.sqlite")
        c.execute("UPDATE events SET ts = ts - 100000"); c.commit(); c.close()
        self.ins(kind="retire", target="t6", patch=None)   # old inserts fall out of the window

    def test_event_and_patch_file(self):
        pid = self.ins(tick=3)
        ev = [d for k, d in self.events() if k == "improve"][0]
        self.assertEqual((ev["proposal"], ev["from"], ev["to"], ev["tick"]), (pid, None, "proposed", 3))
        self.assertEqual(ev["rows"][0]["table"], "proposals")
        self.assertEqual(ev["rows"][0]["row"]["id"], pid)
        f = Path(self.state) / "improve" / "proj" / "patches" / f"{pid}.diff"
        self.assertEqual(f.read_text(), PATCH)


class TransitionTest(Base):
    def test_allowed_and_event(self):
        pid = self.ins()
        self.s.transition(pid, "trial", "go")
        self.assertEqual(self.s.get(pid)["state"], "trial")
        ev = [d for k, d in self.events() if k == "improve"][-1]
        self.assertEqual((ev["from"], ev["to"], ev["reason"]), ("proposed", "trial", "go"))
        self.assertEqual(ev["rows"][0]["row"]["state"], "trial")

    def test_disallowed(self):
        pid = self.ins()
        for to in ("kept", "reverted", "promoted", "awaiting_you", "bogus"):
            with self.assertRaises(S.ImproveError):
                self.s.transition(pid, to, "x")
        self.s.transition(pid, "rejected", "x")
        with self.assertRaises(S.ImproveError):
            self.s.transition(pid, "trial", "x")

    def test_kept_and_promoted_can_be_rejected_for_a_stale_patch(self):
        # lead ruling (Task 10): a patch found stale at apply time is `rejected`, never `reverted`
        kept = self.ins()
        self.s.transition(kept, "trial", "go")
        self.s.transition(kept, "kept", "numbers")
        self.assertEqual(self.s.transition(kept, "rejected", "stale patch")["state"], "rejected")
        prom = self.s.insert("manual", "procedure", "docs/bar.md", PATCH, EV)
        for to in ("trial", "awaiting_you", "promoted"):
            self.s.transition(prom, to, "x")
        self.assertEqual(self.s.transition(prom, "rejected", "stale patch")["state"], "rejected")
        with self.assertRaises(S.ImproveError):
            self.s.transition(prom, "trial", "x")

    def test_atomic(self):
        # mutation: commit after the UPDATE -> row changes despite the failure
        pid = self.ins()
        n = len(self.events())
        with mock.patch.object(S.Store, "_append_event", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.s.transition(pid, "trial", "go")
        self.assertEqual(self.s.get(pid)["state"], "proposed")
        self.assertEqual(len(self.events()), n)


class RebuildTest(Base):
    def test_rebuild_check_after_insert_and_three_transitions(self):
        d = tempfile.mkdtemp()
        env = dict(os.environ, TC_ENGINE_DIR=d)
        subprocess.run(["node", "-e", "require('./engine/lib/engine/db').open('p')"], cwd=REPO, env=env, check=True)
        with mock.patch.dict(os.environ, {"TC_ENGINE_DIR": d}):
            s = S.Store("p")
            pid = s.insert("manual", "rule", "claude/x.md", PATCH, EV)
            s.transition(pid, "trial", "a"); s.transition(pid, "awaiting_you", "b"); s.transition(pid, "promoted", "c")
        r = subprocess.run(["node", "engine/bin/engine.js", "rebuild", "--check", "--project", "p"], cwd=REPO, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        shutil.rmtree(d, ignore_errors=True)


class CliTest(Base):
    def cli(self, *a, ok=True, extra=None):
        env = dict(os.environ, TC_PROJECT="proj", TC_IMPROVE_PROJECT="proj", **(extra or {}))
        r = subprocess.run([sys.executable, "-I", str(REPO / "board/improve.py"), *a], capture_output=True, text=True, env=env, cwd=REPO)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def patchfile(self):
        p = Path(self.tmp) / "p.diff"; p.write_text(PATCH); return str(p)

    def test_propose_list_show(self):
        r = self.cli("propose", "--kind", "rule", "--target", "claude/x.md", "--patch", self.patchfile(),
                     "--evidence", json.dumps(EV), "--outcome", "O1", "--shrinks-reads")
        self.assertEqual(r.stdout.strip(), "P1")
        r = self.cli("list")
        self.assertEqual(r.stdout.strip(), "P1 proposed high rule claude/x.md")
        self.assertEqual(self.cli("list", "--state", "trial").stdout.strip(), "")
        j = json.loads(self.cli("list", "--json").stdout)
        self.assertEqual(j[0]["id"], "P1")
        sh = self.cli("show", "P1").stdout
        self.assertIn(PATCH, sh)
        self.assertIn('"type": "run"', sh)
        j = json.loads(self.cli("show", "P1", "--json").stdout)
        self.assertEqual((j["id"], j["state"], j["class"], j["kind"], j["target"]), ("P1", "proposed", "high", "rule", "claude/x.md"))
        self.assertEqual(j["shrinks_reads"], 1)

    def test_propose_without_evidence_errors(self):
        r = self.cli("propose", "--kind", "rule", "--target", "t", "--patch", self.patchfile(), ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr.strip(), "improve: propose: no deterministic evidence")

    def test_from_dream(self):
        ctx = tempfile.mkdtemp()
        run = Path(ctx) / "dream" / "proj" / "20261125-0300" / "out"
        run.mkdir(parents=True)
        (run / "report.json").write_text(json.dumps({"proposals": [{"kind": "observer", "text": "x"}]}))
        env = dict(os.environ, TC_PROJECT="proj", TC_IMPROVE_PROJECT="proj", TC_CONTEXT_DIR=ctx)
        r = subprocess.run([sys.executable, "-I", str(REPO / "board/improve.py"), "propose", "--kind", "procedure",
                            "--target", "docs/x.md", "--patch", self.patchfile(), "--from-dream", "20261125-0300:0"],
                           capture_output=True, text=True, env=env, cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.s.get("P1")
        self.assertEqual(row["source"], "dream")
        self.assertEqual(row["class"], "high")
        self.assertEqual(json.loads(row["evidence"])[-1], {"type": "report", "ref": f"{run / 'report.json'}#proposals[0]"})
        shutil.rmtree(ctx, ignore_errors=True)

    def test_outcome_status(self):
        r = self.cli("outcome", "status")
        self.assertIn("O1", r.stdout)
        self.assertIn("too early", r.stdout)
        self.assertEqual(self.cli("outcome", "status", "O1").returncode, 0)
        self.assertEqual(self.cli("outcome", "status", "O9", ok=False).returncode, 1)

    def test_no_db(self):
        env = dict(os.environ, TC_PROJECT="other", TC_IMPROVE_PROJECT="other")
        r = subprocess.run([sys.executable, "-I", str(REPO / "board/improve.py"), "list"], capture_output=True, text=True, env=env, cwd=REPO)
        self.assertEqual(r.returncode, 1)
        self.assertIn("improve: no engine database at", r.stderr)


class LoopProjectTest(Base):
    """Final review I1: the loop is agent-board's own. Any other project gets one line and exit 0, before any store,
    engine call or adapter."""
    SUBS = (["list"], ["show", "P1"], ["propose", "--kind", "rule", "--target", "t", "--patch", "/nonexistent"],
            ["variants", "specX", "--json"], ["tick"], ["adapters", "--dry-run"], ["revert", "P1"], ["click", "promote", "P1"],
            ["outcome", "status"], ["schedule", "install"])

    def run_cli(self, *a, **env):
        base = {k: v for k, v in os.environ.items() if k not in ("TC_PROJECT", "TC_IMPROVE_PROJECT", "TC_IMPROVE_REPO")}
        # a tmux-ctl that fails loudly: a refused command must never reach the engine
        return subprocess.run([sys.executable, "-I", str(REPO / "board/improve.py"), *a], capture_output=True, text=True,
                              env=dict(base, TC_TMUX_CTL="/nonexistent/tmux-ctl", **env), cwd=REPO)

    def test_every_subcommand_refuses_another_project(self):
        before = sorted(os.listdir(self.tmp))
        for sub in self.SUBS:
            for how in ("env", "flag"):
                with self.subTest(sub=sub, how=how):
                    if how == "env":
                        r = self.run_cli(*sub, TC_PROJECT="second-brain", TC_IMPROVE_PROJECT="proj")
                    else:
                        r = self.run_cli("--project", "second-brain", *sub, TC_PROJECT="proj", TC_IMPROVE_PROJECT="proj")
                    self.assertEqual((r.returncode, r.stdout, r.stderr), (0, f"improve: {sub[0]}: not the loop's project\n", ""))
        self.assertEqual(sorted(os.listdir(self.tmp)), before, "no database of the other project was made or opened")
        self.assertEqual(self.s.list(), [])

    def test_the_loops_project_is_the_main_checkout_of_this_code(self):
        # unpatched: git names the main checkout, also from a linked worktree
        import improve
        common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True).stdout.strip()
        with mock.patch.dict(os.environ):
            os.environ.pop("TC_IMPROVE_PROJECT", None); os.environ.pop("TC_IMPROVE_REPO", None)
            self.assertEqual(improve.loop_project(), Path(common).parent.name)
        name = Path(common).parent.name
        F.engine_db(self.tmp, name) if name != "proj" else None
        r = self.run_cli("list", TC_PROJECT=name)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        r = self.run_cli("list", TC_PROJECT="proj")
        self.assertEqual(r.stdout, "improve: list: not the loop's project\n")

    def test_tc_improve_repo_names_the_project_in_tests(self):
        repo = Path(self.tmp) / "proj"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        r = self.run_cli("list", TC_PROJECT="proj", TC_IMPROVE_REPO=str(repo))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        r = self.run_cli("list", TC_PROJECT="other", TC_IMPROVE_REPO=str(repo))
        self.assertEqual(r.stdout, "improve: list: not the loop's project\n")
        r = self.run_cli("list", TC_PROJECT="proj", TC_IMPROVE_REPO=str(repo / "nope"))
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stderr, r"^improve: list: cannot tell the loop's project: ")

    def test_project_flag_beats_a_stale_tc_project_for_everything_downstream(self):
        import improve
        seen = []
        with mock.patch.dict(os.environ, {"TC_PROJECT": "stale", "TC_IMPROVE_PROJECT": "proj"}), \
                mock.patch.object(improve, "cmd_list", lambda a, store: seen.append((os.environ["TC_PROJECT"], store.project))):
            self.assertEqual(improve.main(["--project", "proj", "list"]), 0)
        self.assertEqual(seen, [("proj", "proj")])


if __name__ == "__main__":
    unittest.main()
