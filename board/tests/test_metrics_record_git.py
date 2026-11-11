import json, os, re, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
FIX = HERE / "tests" / "fixtures" / "metrics"
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402

SPEC_A, SPEC_B = "docs/superpowers/specs/a.md", "docs/superpowers/specs/b.md"
PLAN_A = "docs/superpowers/plans/2026-01-01-a.md"
RESERVED = ("manifest_tokens", "lock_wait_s", "lock_wait_cause", "repair_runs", "integration_s", "integration_tokens")


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


def write(repo, rel, text, mode="w"):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if "b" in mode:
        p.write_bytes(text)
    else:
        p.write_text(text)


def tasks_json(plan, tasks):
    out = []
    for i, (tier, files) in enumerate(tasks, 1):
        meta = json.dumps({"files": files, "modelTier": tier})
        out.append({"id": i, "subject": f"Task {i}", "description": "x\n\n```json:metadata\n" + meta + "\n```\n"})
    return json.dumps({"planPath": plan, "tasks": out})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.repo = t / "repo"
        self.repo.mkdir()
        p = mock.patch.dict(os.environ, {"TC_STATE": str(t / "state"), "USAGE_ROOT": str(t / "proj")})
        p.start()
        self.addCleanup(p.stop)
        r = self.repo
        git(r, "init", "-q", "-b", "main")
        write(r, "f.txt", "one\n")
        write(r, "g.txt", "g\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base")
        self.base0 = git(r, "rev-parse", "HEAD")
        # branch A: plan, tasks, ledger, code (3 lines in src/a.py, 2 in src/extra.py, a binary), merged
        git(r, "checkout", "-q", "-b", "feat/a")
        write(r, PLAN_A, f"# Plan A\n\n**Goal:** g\n\n**Spec:** `{SPEC_A}`\n\nbody\n")
        write(r, PLAN_A + ".tasks.json", tasks_json(PLAN_A, [("standard", ["src/a.py", "src/b.py", "docs/superpowers/x.md"]),
                                                          ("mechanical", ["src/a.py"])]))
        write(r, "docs/superpowers/ledgers/2026-01-01-a/progress.md", (FIX / "remote-access-progress.md").read_text())
        write(r, "docs/superpowers/ledgers/2026-01-01-a/final-review.md",
              "# Final\n\n### Critical\n\nNone.\n\n### Important\n\n- one\n- two\n\n### Minor\n\n- m\n")
        write(r, "src/a.py", "1\n2\n3\n")
        write(r, "src/extra.py", "x\ny\n")
        write(r, "bin.dat", b"\x00\x01\x02", "wb")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "A work")
        git(r, "checkout", "-q", "main")
        git(r, "merge", "-q", "--no-ff", "-m", "Merge branch 'feat/a'", "feat/a")
        self.merge_a = git(r, "rev-parse", "HEAD")
        # branch B from base: plan on the branch only, conflicts with a later main commit
        git(r, "checkout", "-q", "-b", "feat/b", self.base0)
        write(r, "docs/superpowers/plans/2026-01-02-b.md", f"# Plan B\n\n**Spec:** `{SPEC_B}`\n")
        write(r, "f.txt", "B edit\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "B work")
        self.head_b = git(r, "rev-parse", "HEAD")
        git(r, "checkout", "-q", "main")
        write(r, "f.txt", "main edit\n")
        git(r, "commit", "-q", "-am", "main moves f")
        self.main_tip = git(r, "rev-parse", "main")
        self.now = time.time()
        metrics.append(r, {"kind": "batch", "batch": "B1", "base": self.base0, "configs": ["c"], "assignment": {SPEC_A: "c"},
                           "groups": [], "at": metrics.utc(self.now - 3600)})
        metrics.append(r, {"kind": "batch", "batch": "B2", "base": self.main_tip, "configs": ["c"], "assignment": {SPEC_B: "c"},
                           "groups": [], "at": metrics.utc(self.now - 3600)})
        for b, s in (("B1", SPEC_A), ("B2", SPEC_B)):
            metrics.append(r, {"kind": "start", "batch": b, "spec": s, "at": metrics.utc(self.now - 1800), "main": self.base0})

    def rec(self, spec=SPEC_A, batch="B1", outcome=None, **kw):
        return metrics.build_record_static(self.repo, spec, batch, outcome, self.now, **kw)


class MergedTest(Base):
    def test_identity_and_merge(self):
        r = self.rec()
        self.assertEqual((r["kind"], r["batch"], r["spec"]), ("run", "B1", SPEC_A))
        self.assertEqual(r["plan"], PLAN_A)
        self.assertEqual(r["branch"], "feat/a")
        self.assertEqual(r["merge"], self.merge_a)
        self.assertEqual(r["head"], git(self.repo, "rev-parse", self.merge_a + "^2"))
        self.assertEqual(r["base"], self.base0)
        self.assertEqual(r["outcome"], "merged")
        self.assertRegex(r["ended_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(r["ended_at"], metrics.utc(int(git(self.repo, "log", "-1", "--format=%ct", self.merge_a))))
        self.assertRegex(r["started_at"], r"^\d{4}-\d\d-\d\dT")
        self.assertEqual(r["missing"], [])

    def test_part_suffix_kept_in_record_and_stripped_for_match(self):
        r = self.rec(spec=SPEC_A + "#part-2")
        self.assertEqual(r["spec"], SPEC_A + "#part-2")
        self.assertEqual(r["plan"], PLAN_A)

    def test_outcome_mapping(self):
        for text, want, miss in (("mr", "mr", False), ("kept because x", "kept", False), ("FAILED hard", "failed", False),
                                 ("merged", "merged", False), ("weird words", "weird", True)):
            r = self.rec(outcome=text)
            self.assertEqual(r["outcome"], want, text)
            self.assertEqual("outcome" in r["missing"], miss, text)

    def test_size(self):
        r = self.rec()
        self.assertEqual(r["tasks"], 2)
        self.assertEqual(r["tiers"], {"standard": 1, "mechanical": 1})
        self.assertEqual(r["declared_files"], 2)  # src/a.py, src/b.py (docs/superpowers excluded)
        # touched: src/a.py, src/extra.py, bin.dat (docs/superpowers excluded)
        self.assertEqual(r["touched_files"], 3)
        self.assertEqual(r["diff_lines"], 5)  # 3 + 2 + binary 0
        m = r["manifest"]
        self.assertEqual((m["declared"], m["touched"], m["both"]), (2, 3, 1))
        self.assertEqual((m["precision"], m["recall"]), (0.5, round(1 / 3, 4)))

    def test_ledger_fields_match_grep_on_fixture(self):
        r = self.rec()
        fx = FIX / "remote-access-progress.md"
        lines = fx.read_text().splitlines()
        self.assertEqual(r["fix_rounds"], sum(1 for l in lines if "fix round" in l))
        self.assertEqual(r["rulings"], sum(1 for l in lines if l.startswith("Ruling:")))
        self.assertEqual(r["bounces"], sum(1 for l in lines if re.search(r"review.*❌|quality ❌", l)))
        self.assertEqual(r["fix_wave"], any("fix wave" in l.lower() for l in lines))
        self.assertEqual(r["parked"], sum(1 for l in lines if "minor (deferred)" in l or "parked" in l))
        self.assertEqual(r["final_findings"], 2)
        # the fixture must exercise the counters, or the equalities above prove nothing
        self.assertGreater(r["fix_rounds"], 0)
        self.assertGreater(r["rulings"], 0)
        self.assertGreater(r["bounces"], 0)
        self.assertGreater(r["parked"], 0)
        self.assertTrue(r["fix_wave"])

    def test_manifest_on_real_tasks_fixture(self):
        text = (FIX / "remote-access.tasks.json").read_text()
        d = json.loads(text)
        union = set()
        for t in d["tasks"]:
            m = re.search(r"```json:metadata\n(.*?)\n```", t["description"], re.S)
            union.update(json.loads(m.group(1))["files"])
        want = len({f for f in union if not f.startswith("docs/superpowers/")})
        self.assertGreater(want, 0)
        info = metrics.parse_tasks(text)
        self.assertEqual(len(info["declared"]), want)
        self.assertEqual(info["tasks"], len(d["tasks"]))

    def test_stale_base_clean(self):
        r = self.rec()
        self.assertEqual(r["stale_base"], {"result": "clean", "paths": []})

    def test_reserved_null(self):
        r = self.rec()
        for k in RESERVED:
            self.assertIn(k, r)
            self.assertIsNone(r[k])
            self.assertNotIn(k, r["missing"])

    def test_ledger_missing(self):
        git(self.repo, "rm", "-q", "-r", "docs/superpowers/ledgers")
        git(self.repo, "commit", "-q", "-m", "drop ledger")
        r = self.rec()
        for k in ("bounces", "fix_rounds", "final_findings", "fix_wave", "rulings", "parked"):
            self.assertIsNone(r[k], k)
            self.assertIn(k, r["missing"])

    def test_merge_search_skips_merges_before_start(self):
        metrics.append(self.repo, {"kind": "start", "batch": "B1", "spec": SPEC_A, "at": metrics.utc(self.now + 3600), "main": "x"})
        r = self.rec()
        self.assertIsNone(r["merge"])
        self.assertEqual(r["outcome"], "kept")


class UnmergedTest(Base):
    def test_conflict_and_branch_from_plan_commit(self):
        r = self.rec(spec=SPEC_B, batch="B2")
        self.assertIsNone(r["merge"])
        self.assertIn("merge", r["missing"])
        self.assertEqual(r["branch"], "feat/b")
        self.assertEqual(r["head"], self.head_b)
        self.assertEqual(r["outcome"], "kept")
        self.assertEqual(r["base"], self.base0)
        self.assertEqual(r["stale_base"]["result"], "conflict")
        self.assertEqual(r["stale_base"]["paths"], ["f.txt"])

    def test_branch_flag_wins(self):
        git(self.repo, "branch", "feat/other", self.head_b)
        r = self.rec(spec=SPEC_B, batch="B2", branch="feat/other")
        self.assertEqual(r["branch"], "feat/other")
        self.assertEqual(r["head"], self.head_b)

    def test_stale_base_failure_is_null_and_missing(self):
        metrics.append(self.repo, {"kind": "batch", "batch": "B3", "base": "nonsense", "configs": ["c"],
                                   "assignment": {}, "groups": [], "at": metrics.utc(self.now)})
        r = self.rec(spec=SPEC_B, batch="B3")
        self.assertIsNone(r["stale_base"])
        self.assertIn("stale_base", r["missing"])

    def test_no_plan_no_branch(self):
        r = self.rec(spec="docs/superpowers/specs/none.md", batch="B1")
        self.assertEqual((r["kind"], r["batch"], r["spec"], r["outcome"]), ("run", "B1", "docs/superpowers/specs/none.md", "kept"))
        self.assertIn("at", r)
        self.assertIn("ended_at", r)
        ident = {"kind", "batch", "spec", "outcome", "at", "started_at", "ended_at", "missing"}
        nulls = [k for k in r if k not in ident]
        self.assertGreater(len(nulls), 10)
        for k in nulls:
            self.assertIsNone(r[k], k)
        for k in ("plan", "branch", "head", "base", "merge", "tasks", "stale_base", "bounces", "manifest"):
            self.assertIn(k, r["missing"], k)


class PlanAlreadyOnMainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        p = mock.patch.dict(os.environ, {"TC_STATE": str(t / "state"), "USAGE_ROOT": str(t / "proj")})
        p.start()
        self.addCleanup(p.stop)
        self.repo = r = t / "repo"
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        write(r, "f.txt", "1\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base")
        self.plan = "docs/superpowers/plans/2026-01-03-gamma.md"
        write(r, self.plan, "# P\n\n**Spec:** `docs/superpowers/specs/gamma.md`\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "plan on main")
        for br, f in (("feat/unrelated", "u.txt"), ("feat/gamma", "g.txt")):
            git(r, "checkout", "-q", "-b", br, "main")
            write(r, f, "x\n")
            git(r, "add", "."); git(r, "commit", "-q", "-m", br)
            git(r, "checkout", "-q", "main")
            git(r, "merge", "-q", "--no-ff", "-m", f"Merge branch '{br}'", br)
            setattr(self, "merge_" + br.split("/")[1], git(r, "rev-parse", "HEAD"))
        self.now = time.time()
        metrics.append(r, {"kind": "batch", "batch": "B", "base": git(r, "rev-parse", "HEAD~2"), "configs": ["c"],
                           "assignment": {}, "groups": [], "at": metrics.utc(self.now)})

    def test_branch_name_picks_the_matching_merge(self):
        r = metrics.build_record_static(self.repo, "docs/superpowers/specs/gamma.md", "B", None, self.now)
        self.assertEqual(r["merge"], self.merge_gamma)
        self.assertNotEqual(r["merge"], self.merge_unrelated)
        self.assertEqual(r["branch"], "feat/gamma")

    def test_no_match_is_null_and_missing(self):
        git(self.repo, "branch", "-m", "feat/gamma", "feat/zzz")
        git(self.repo, "commit", "-q", "--amend", "-m", "Merge branch 'feat/zzz'")
        r = metrics.build_record_static(self.repo, "docs/superpowers/specs/gamma.md", "B", None, self.now)
        self.assertIsNone(r["merge"])
        self.assertIn("merge", r["missing"])


if __name__ == "__main__":
    unittest.main()
