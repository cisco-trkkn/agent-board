import json, os, shutil, sqlite3, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dream_check  # noqa: E402
import improve_adapters as A  # noqa: E402
import improve_fixtures as F  # noqa: E402
import improve_store as S  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SKILL = "docs-compose"
LIVE = (REPO / "claude" / "skills" / SKILL / "SKILL.md").read_text()
# header forms copied from real observer patches (2026-10-19 round: absolute ---, bare .new +++, tab + timestamp)
ORCH_PATCH = ("--- /Users/x/agent-board/claude/orchestrator.md\t2026-10-19 22:37:49\n"
              "+++ orchestrator.md.new\t2026-10-19 23:14:37\n@@ -1,1 +1,1 @@\n-a\n+b\n")


def w(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if isinstance(text, str) else json.dumps(text))
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.d = {k: tempfile.mkdtemp() for k in ("engine", "state", "obs", "ctx", "scout")}
        self.env = mock.patch.dict(os.environ, {"TC_IMPROVE_PROJECT": "proj", "TC_ENGINE_DIR": self.d["engine"], "TC_STATE": self.d["state"],
                                                "TC_OBSERVER_DIR": self.d["obs"], "TC_CONTEXT_DIR": self.d["ctx"],
                                                "TC_SCOUT_DIR": self.d["scout"]})
        self.env.start()
        F.engine_db(self.d["engine"])
        self.s = S.Store("proj")

    def tearDown(self):
        self.env.stop()
        for v in self.d.values():
            shutil.rmtree(v, ignore_errors=True)

    def events(self, kind):
        c = sqlite3.connect(Path(self.d["engine"]) / "proj.sqlite")
        try:
            return [json.loads(x) for (x,) in c.execute("SELECT detail FROM events WHERE kind=?", (kind,))]
        finally:
            c.close()

    def rows(self):
        return self.s.list()


class Dream(Base):
    def report(self, run, props):
        rep = {"changed": {"merged": [], "archived": 0, "stale": 0, "added": 0}, "contradictions": [], "proposals": props,
               "summary": "s"}
        self.assertIsNone(dream_check.report_problem(rep))
        return w(Path(self.d["ctx"]) / "dream" / "proj" / run / "out" / "report.json", rep)

    def test_observer_and_idea(self):
        old = self.report("20261101-0300", [{"kind": "observer", "text": "old", "evidence": ["x"]}])
        p = self.report("20261102-0300", [{"kind": "observer", "text": "t line\nmore", "target": "claude/worker.md", "evidence": ["e1"]},
                                          {"kind": "idea", "text": "i", "evidence": []}])
        A.run_all("proj")
        r = self.rows()
        self.assertEqual(len(r), 2)
        self.assertEqual((r[0]["kind"], r[0]["patch"], r[0]["state"], r[0]["target"]), ("procedure", None, "proposed", "claude/worker.md"))
        self.assertEqual((r[1]["kind"], r[1]["state"], r[1]["reason"], r[1]["target"]), ("spec", "drafted", "adapter draft", "dream:20261102-0300:1"))
        ev = json.loads(r[0]["evidence"])
        self.assertEqual(ev[0], {"type": "report", "ref": f"{p}#proposals[0]"})
        self.assertEqual(ev[1]["type"], "note")
        self.assertEqual(r[0]["title"], "t line")
        self.assertNotIn(str(old), r[0]["evidence"])


class Scout(Base):
    def drafts(self, d):
        w(Path(self.d["scout"]) / "drafts.json", {"drafts": d})

    def test_drafts(self):
        self.drafts({"a1": {"id": "a1", "path": "docs/superpowers/specs/a.md", "title": "Fix O1 thing", "text": ""},
                     "b2": {"id": "b2", "path": "docs/superpowers/specs/b.md", "title": "other", "text": "none"},
                     "c3": {"id": "c3", "title": "no path"}})
        A.run_all("proj")
        r = {x["target"]: x for x in self.rows()}
        self.assertEqual(len(r), 2)
        a = r["docs/superpowers/specs/a.md"]
        self.assertEqual((a["kind"], a["state"], a["outcome"], a["reason"]), ("spec", "drafted", "O1", "adapter draft"))
        self.assertEqual(json.loads(a["evidence"]), [{"type": "report", "ref": "scout drafts.json#a1"}])
        self.assertIsNone(r["docs/superpowers/specs/b.md"]["outcome"])

    def test_o1_by_text(self):
        self.drafts({"a1": {"id": "a1", "path": "x.md", "title": "t", "text": "moves O1"}})
        A.run_all("proj")
        self.assertEqual(self.rows()[0]["outcome"], "O1")


class Discovery(Base):
    def test_items_with_spec_path_only(self):
        st = {"posts": {"2026-11-01": {"items": [{"key": "k1", "title": "t", "path": "docs/superpowers/specs/d.md"},
                                                 {"key": "k2", "title": "no spec"}]}}}
        w(Path(self.d["state"]) / "discover" / "proj.json", st)
        A.run_all("proj")
        r = self.rows()
        self.assertEqual([(x["kind"], x["state"], x["target"], x["reason"]) for x in r],
                         [("spec", "drafted", "docs/superpowers/specs/d.md", "adapter draft")])


class Observer(Base):
    def ws(self, status="awaiting install", staged=None, patch=ORCH_PATCH):
        o = Path(self.d["obs"]) / "skill-updates"
        w(o / "PENDING.md", f"# Pending\n\n## 2026-11-01 (review): {status}\n\nx\n\n## 2026-10-01 (old): installed\n")
        w(o / "2026-11-01" / SKILL / "SKILL.md", staged if staged is not None else LIVE + "\nextra line\n")
        w(o / "2026-11-01" / "_target-files" / "orch.patch", patch)
        w(o / "2026-10-01" / SKILL / "SKILL.md", "ignored round")
        return o

    def test_skill_and_rule(self):
        self.ws()
        A.run_all("proj")
        r = {x["kind"]: x for x in self.rows()}
        self.assertEqual(set(r), {"skill", "rule"})
        self.assertEqual(r["skill"]["target"], f"claude/skills/{SKILL}/SKILL.md")
        self.assertEqual(r["skill"]["patch"].splitlines()[:2], [f"--- a/claude/skills/{SKILL}/SKILL.md", f"+++ b/claude/skills/{SKILL}/SKILL.md"])
        self.assertEqual(r["rule"]["patch"], "--- a/claude/orchestrator.md\n+++ b/claude/orchestrator.md\n@@ -1,1 +1,1 @@\n-a\n+b\n")
        self.assertIn("+extra line", r["skill"]["patch"])
        self.assertEqual(r["rule"]["target"], "claude/orchestrator.md")
        self.assertEqual(r["rule"]["class"], "protected")
        pend = Path(self.d["obs"]) / "skill-updates" / "PENDING.md"
        self.assertEqual(json.loads(r["rule"]["evidence"]), [{"type": "report", "ref": f"{pend}#2026-11-01"}])

    def test_bare_plus_line_resolves_to_repo_file(self):
        o = self.ws(patch="--- orchestrator.md\n+++ orchestrator.md\n@@ -1 +1 @@\n-a\n+b\n")
        A.run_all("proj")
        self.assertEqual({x["target"]: x["class"] for x in self.rows() if x["kind"] == "rule"}, {"claude/orchestrator.md": "protected"})

    def test_unresolvable_name_is_skipped_with_one_error(self):
        # a bare name that is no single repo file (and a file outside the repo) can be neither trialled nor landed
        o = self.ws(patch="--- zz-nothing.md\n+++ zz-nothing.md.new\n@@ -1 +1 @@\n-a\n+b\n")
        w(o / "2026-11-01" / "_target-files" / "home.patch",
          "--- /Users/x/.zz-nothing-rc\t2026-10-19 22:37:49\n+++ /Users/x/.zz-nothing-rc.new\t2026\n@@ -1 +1 @@\n-a\n+b\n")
        A.run_all("proj")
        self.assertEqual([x["kind"] for x in self.rows()], ["skill"])
        reasons = sorted(e["reason"] for e in self.events("improve_adapter_error"))
        self.assertEqual(len(reasons), 2)
        self.assertRegex(reasons[0], r"^no single repo file for .*home\.patch \(/Users/x/\.zz-nothing-rc\)$")
        self.assertRegex(reasons[1], r"^no single repo file for .*orch\.patch \(zz-nothing\.md\)$")

    def test_patch_of_two_files_is_skipped_with_one_error(self):
        two = ORCH_PATCH + "--- /Users/x/agent-board/claude/worker.md\t2026\n+++ worker.md.new\t2026\n@@ -1,1 +1,1 @@\n-a\n+b\n"
        self.ws(patch=two)
        A.run_all("proj")
        self.assertEqual([x["kind"] for x in self.rows()], ["skill"])
        self.assertRegex(self.events("improve_adapter_error")[0]["reason"], r"^not a one-file patch: .*orch\.patch$")

    def test_removed_line_that_looks_like_a_header_is_left_alone(self):
        body = "@@ -1,3 +1,3 @@\n--- not a header\n+++ nor this\n@@ in text\n x\n"
        self.ws(patch="--- orchestrator.md\n+++ orchestrator.md\n" + body)
        A.run_all("proj")
        r = [x for x in self.rows() if x["kind"] == "rule"]
        self.assertEqual([x["patch"] for x in r], ["--- a/claude/orchestrator.md\n+++ b/claude/orchestrator.md\n" + body])

    def test_skill_that_lives_outside_the_repo_is_skipped_with_one_error(self):
        o = self.ws()
        home = Path(self.d["state"]) / "home"
        w(home / ".claude" / "skills" / "zz-home-only" / "SKILL.md", "live\n")
        w(o / "2026-11-01" / "zz-home-only" / "SKILL.md", "live\nmore\n")
        with mock.patch.object(Path, "home", return_value=home):
            A.run_all("proj")
        self.assertEqual(sorted(x["target"] for x in self.rows()), ["claude/orchestrator.md", f"claude/skills/{SKILL}/SKILL.md"])
        self.assertEqual([e["reason"] for e in self.events("improve_adapter_error")],
                         ["skill zz-home-only lives outside the repo (round 2026-11-01)"])

    def test_rule_target_forms(self):
        for hdr, want in [("--- a/claude/worker.md\n+++ b/claude/worker.md\n", "claude/worker.md"),
                          ("--- /x/.live-mirror/agent-board/claude/worker.md\t2026-10-21 01:22:43\n+++ /x/2026-10-21/_target-files/worker.md.new\t2026\n", "claude/worker.md")]:
            self.assertEqual(A.rule_target(hdr + "@@\n"), want)

    def test_not_awaiting_skipped(self):
        self.ws(status="installed")
        A.run_all("proj")
        self.assertEqual(self.rows(), [])

    def test_skill_without_live_copy_skipped_with_event(self):
        o = self.ws()
        shutil.rmtree(o / "2026-11-01" / SKILL)
        w(o / "2026-11-01" / "zz-no-such-skill-xyz" / "SKILL.md", "x")
        A.run_all("proj")
        self.assertEqual([x["kind"] for x in self.rows()], ["rule"])
        ev = self.events("improve_adapter_error")
        self.assertEqual([(e["source"]) for e in ev], ["observer"])
        self.assertIn("zz-no-such-skill-xyz", ev[0]["reason"])


class ObserverToTrialAndApply(Base):
    """Final review I2: what observer() stores is what a trial and the apply step can use. The round is laid out as a real
    one, and its rule patch is a real `diff -u` between the two files of that layout, so the headers are the ones diff
    writes there. Shape copied (read-only, 2026-11-25) from
    ~/.task-observer/skill-updates/2026-11-02/_target-files/worker.md.patch:
      --- /Users/<u>/.task-observer/skill-updates/.live-mirror/agent-board/claude/worker.md<TAB>2026-10-29 01:50:47
      +++ /Users/<u>/.task-observer/skill-updates/2026-11-02/_target-files/worker.md.new<TAB>2026-11-02 12:12:46"""
    RULE = "claude/worker.md"
    MARK = "- Observer marker 5c1e: say so in the report."

    def setUp(self):
        super().setUp()
        import subprocess
        o = Path(self.d["obs"]) / "skill-updates"
        live = (REPO / self.RULE).read_text()
        mirror = w(o / ".live-mirror" / "agent-board" / self.RULE, live)
        new = w(o / "2026-11-02" / "_target-files" / "worker.md.new", live + self.MARK + "\n")
        d = subprocess.run(["diff", "-u", str(mirror), str(new)], capture_output=True, text=True)
        self.assertEqual(d.returncode, 1, d.stderr)
        self.raw = d.stdout
        w(o / "2026-11-02" / "_target-files" / "worker.md.patch", self.raw)
        w(o / "2026-11-02" / SKILL / "SKILL.md", LIVE + "\nObserver skill line 5c1e.\n")
        w(o / "PENDING.md", "# Pending\n\n## 2026-11-02 (review): awaiting install\n\nx\n")
        # a scratch main with the two champion files: `applies` reads git, and never this checkout's
        self.main = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.main, True)
        self.skill_rel = f"claude/skills/{SKILL}/SKILL.md"
        for rel in (self.RULE, self.skill_rel):
            w(self.main / rel, (REPO / rel).read_text())
        for a in (["init", "-q", "-b", "main"], ["add", "-A"],
                  ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "champions"]):
            subprocess.run(["git", "-C", str(self.main), *a], check=True, capture_output=True)

    def test_the_fixture_has_the_real_header_shape(self):
        head = self.raw.splitlines()[:2]
        self.assertRegex(head[0], r"^--- /.+/skill-updates/\.live-mirror/agent-board/claude/worker\.md\t\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
        self.assertRegex(head[1], r"^\+\+\+ /.+/skill-updates/2026-11-02/_target-files/worker\.md\.new\t\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")

    def test_stored_rows_reach_a_variant_and_apply_on_main(self):
        import improve_apply
        import improve_trials
        self.assertEqual(A.run_all("proj")["observer"], 2)
        self.assertEqual(self.events("improve_adapter_error"), [])
        rows = {x["kind"]: x for x in self.rows()}
        self.assertEqual({k: v["target"] for k, v in rows.items()}, {"rule": self.RULE, "skill": self.skill_rel})
        for row in rows.values():
            self.assertEqual(row["patch"].splitlines()[:2], [f"--- a/{row['target']}", f"+++ b/{row['target']}"])
            self.s.transition(row["id"], "trial", "test")
        ids = [r["id"] for r in rows.values()]
        spec = next(f"docs/s{i}.md" for i in range(500) if all(improve_trials.in_trial(f"docs/s{i}.md", p) for p in ids))
        got = {v["kind"]: v for v in improve_trials.variants(spec, self.s)["variants"]}
        self.assertEqual(set(got), {"rule", "skill"}, [(r["id"], r["state"], r["reason"]) for r in self.rows()])
        self.assertIn(self.MARK, got["rule"]["overlay"])
        self.assertEqual(got["skill"]["skill_copy"]["from"], f"claude/skills/{SKILL}")
        self.assertEqual({r["state"] for r in self.rows()}, {"trial"})
        for row in rows.values():
            self.assertTrue(improve_apply.applies(self.s, row["id"], repo=self.main), row["target"])

    def test_the_raw_real_shaped_patch_is_what_used_to_fail(self):
        # the stored form before the fix: the trial calls it unsafe and git cannot apply it on main
        import improve_apply
        import improve_trials
        pid = self.s.insert("observer", "rule", self.RULE, self.raw, [{"type": "report", "ref": "x"}])
        d, err = improve_trials._apply(REPO, self.raw, self.RULE)
        shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(err, "unsafe path")
        self.assertFalse(improve_apply.applies(self.s, pid, repo=self.main))


class Idempotence(Base):
    def test_rerun_inserts_nothing_changed_patch_is_new(self):
        o = Observer.ws(self)
        A.run_all("proj")
        n = len(self.rows())
        A.run_all("proj")
        self.assertEqual(len(self.rows()), n)
        w(o / "2026-11-01" / "_target-files" / "orch.patch", ORCH_PATCH.replace("+b", "+c"))
        A.run_all("proj")
        self.assertEqual(len(self.rows()), n + 1)


class Errors(Base):
    def test_unparsable_source_one_event_others_run(self):
        w(Path(self.d["scout"]) / "drafts.json", "{not json")
        w(Path(self.d["state"]) / "discover" / "proj.json", {"posts": {"n": {"items": [{"key": "k", "path": "d.md"}]}}})
        A.run_all("proj")
        ev = self.events("improve_adapter_error")
        self.assertEqual([e["source"] for e in ev], ["scout"])
        self.assertTrue(ev[0]["reason"])
        self.assertEqual([x["target"] for x in self.rows()], ["d.md"])

    def test_unparsable_pending_one_event(self):
        o = Path(self.d["obs"]) / "skill-updates"
        o.mkdir(parents=True)
        (o / "PENDING.md").write_bytes(b"\xff\xfe")
        A.run_all("proj")
        self.assertEqual([e["source"] for e in self.events("improve_adapter_error")], ["observer"])

    def test_missing_observer_workspace_is_absent_not_error(self):
        shutil.rmtree(self.d["obs"])
        self.assertEqual(A.run_all("proj")["observer"], 0)
        self.assertEqual(self.events("improve_adapter_error"), [])

    def test_absent_scout_and_discover_files_are_not_errors(self):
        A.run_all("proj")
        self.assertEqual(self.events("improve_adapter_error"), [])


class DryRun(Base):
    """`improve adapters --dry-run`: reads each source, prints what it would insert and the count read, writes nothing."""
    ws = Observer.ws

    def run_cli(self, *a, **extra):
        import subprocess
        env = dict(os.environ, TC_PROJECT="proj", **extra)
        return subprocess.run([sys.executable, "-I", str(REPO / "board/improve.py"), "adapters", *a],
                              capture_output=True, text=True, env=env, cwd=REPO)

    def test_observer_lists_items_with_classes_and_inserts_nothing(self):
        self.ws()
        before = len(self.rows())
        r = self.run_cli("--dry-run", "--source", "observer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("observer skill claude/skills/docs-compose/SKILL.md", r.stdout)
        self.assertIn("observer rule claude/orchestrator.md protected", r.stdout)
        self.assertIn("observer: 2 item(s) read", r.stdout)
        self.assertEqual(len(self.rows()), before)
        self.assertEqual(self.events("improve_adapter_error"), [])

    def test_needs_dry_run_flag(self):
        r = self.run_cli("--source", "observer")
        self.assertEqual(r.returncode, 1)

    def test_works_without_an_engine_database(self):
        self.ws()
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, True)
        r = self.run_cli("--dry-run", "--source", "observer", TC_ENGINE_DIR=empty)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(empty), [])


class DryRunDream(DryRun):
    def rep(self, run, props):
        return Dream.report(self, run, props)

    def test_kinds_of_the_newest_run(self):
        self.rep("20261101-0300", [{"kind": "idea", "text": "old", "evidence": []}])
        self.rep("20261102-0300", [{"kind": "observer", "text": "a", "evidence": ["e"]}, {"kind": "idea", "text": "b", "evidence": []}])
        r = self.run_cli("--dry-run", "--source", "dream")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dream 20261102-0300: observer, idea", r.stdout)
        self.assertIn("dream: 2 item(s) read", r.stdout)

    def test_empty_report(self):
        self.rep("20261102-0300", [])
        r = self.run_cli("--dry-run", "--source", "dream")
        self.assertIn("dream 20261102-0300: no proposals", r.stdout)

    def test_no_report(self):
        r = self.run_cli("--dry-run", "--source", "dream")
        self.assertIn("dream: no report", r.stdout)


if __name__ == "__main__":
    unittest.main()
