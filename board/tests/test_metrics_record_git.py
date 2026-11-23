import contextlib, io, json, os, re, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
FIX = HERE / "tests" / "fixtures" / "metrics"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics  # noqa: E402
from metrics_fixtures import cache_main_root  # noqa: E402

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


_TEMPLATE = {}


def _template():
    """The scratch repo every test starts from, built once per process and copied: it holds no worktrees, so a copy
    is independent of the template and of every other copy. Returns (repo dir, the hashes the tests compare)."""
    if not _TEMPLATE:
        tmp = tempfile.TemporaryDirectory()
        _TEMPLATE["tmp"] = tmp
        r = Path(tmp.name).resolve() / "repo"
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        write(r, "f.txt", "one\n")
        write(r, "g.txt", "g\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base")
        base0 = git(r, "rev-parse", "HEAD")
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
        merge_a = git(r, "rev-parse", "HEAD")
        # branch B from base: plan on the branch only, conflicts with a later main commit
        git(r, "checkout", "-q", "-b", "feat/b", base0)
        write(r, "docs/superpowers/plans/2026-01-02-b.md", f"# Plan B\n\n**Spec:** `{SPEC_B}`\n")
        write(r, "f.txt", "B edit\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "B work")
        head_b = git(r, "rev-parse", "HEAD")
        git(r, "checkout", "-q", "main")
        write(r, "f.txt", "main edit\n")
        git(r, "commit", "-q", "-am", "main moves f")
        _TEMPLATE["repo"] = r
        _TEMPLATE["hashes"] = (base0, merge_a, head_b, git(r, "rev-parse", "main"))
    return _TEMPLATE["repo"], _TEMPLATE["hashes"]


class Base(unittest.TestCase):
    def setUp(self):
        cache_main_root(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.repo = t / "repo"
        p = mock.patch.dict(os.environ, {"TC_STATE": str(t / "state"), "USAGE_ROOT": str(t / "proj")})
        p.start()
        self.addCleanup(p.stop)
        r = self.repo
        src, (self.base0, self.merge_a, self.head_b, self.main_tip) = _template()
        shutil.copytree(src, r, symlinks=True)
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

    def test_a_real_merge_wins_over_a_later_ledger_commit_on_main(self):
        """The fast-forward path is for runs with no merge commit: a merged run keeps its merge range even when main
        later gets another commit under the same ledger directory."""
        write(self.repo, "docs/superpowers/ledgers/2026-01-01-a/late.md", "late\n")
        git(self.repo, "add", "."); git(self.repo, "commit", "-q", "-m", "docs(ledger): late note")
        r = self.rec()
        self.assertEqual(r["merge"], self.merge_a)
        self.assertEqual(r["head"], git(self.repo, "rev-parse", self.merge_a + "^2"))
        self.assertEqual(r["base"], self.base0)

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
        self.assertEqual(r["declared_list"], ["src/a.py", "src/b.py"])
        self.assertEqual(r["touched_list"], ["bin.dat", "src/a.py", "src/extra.py"])
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
        self.assertNotIn("merge", r["missing"])  # kept: no merge is the result, not a gap
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
        for k in ("plan", "branch", "head", "base", "tasks", "stale_base", "bounces", "manifest"):
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

    def test_branch_flag_still_works_with_the_plan_on_main(self):
        git(self.repo, "branch", "feat/manual", self.merge_gamma + "^2")
        git(self.repo, "commit", "-q", "--amend", "-m", "Merge branch 'feat/zzz'")  # no merge matches gamma any more
        r = metrics.build_record_static(self.repo, "docs/superpowers/specs/gamma.md", "B", "kept", self.now, branch="feat/manual")
        self.assertEqual(r["branch"], "feat/manual")
        self.assertEqual(r["head"], git(self.repo, "rev-parse", "feat/manual"))
        self.assertIsNotNone(r["base"])

    def test_no_match_is_null_and_missing(self):
        git(self.repo, "branch", "-m", "feat/gamma", "feat/zzz")
        git(self.repo, "commit", "-q", "--amend", "-m", "Merge branch 'feat/zzz'")
        r = metrics.build_record_static(self.repo, "docs/superpowers/specs/gamma.md", "B", None, self.now)
        self.assertIsNone(r["merge"])
        self.assertNotIn("merge", r["missing"])
        # no merge found and the plan is on main: feat/unrelated also contains the plan commit, so no branch guess
        for k in ("branch", "head", "base", "touched_files", "diff_lines", "manifest"):
            self.assertIsNone(r[k], k)
        for k in ("branch", "head", "base"):
            self.assertIn(k, r["missing"], k)
        r = metrics.build_record_static(self.repo, "docs/superpowers/specs/gamma.md", "B", "merged", self.now)
        self.assertIsNone(r["merge"])
        self.assertIn("merge", r["missing"])


class FastForwardTest(unittest.TestCase):
    """finishing-a-development-branch fast-forwards main: no merge commit, the branch is deleted. The run is resolved
    from the plan's first commit (base = its parent) and the last commit that touched the plan's ledger (head)."""
    SPEC = "docs/superpowers/specs/ff.md"
    PLAN = "docs/superpowers/plans/2026-01-04-ff.md"

    def setUp(self):
        cache_main_root(self)
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
        self.base = git(r, "rev-parse", "HEAD")
        write(r, "other.txt", "o\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "other work before the plan")
        self.plan_parent = git(r, "rev-parse", "HEAD")
        write(r, self.PLAN, f"# P\n\n**Spec:** `{self.SPEC}`\n")
        write(r, self.PLAN + ".tasks.json", tasks_json(self.PLAN, [("standard", ["src/a.py", "src/b.py"])]))
        git(r, "add", "."); git(r, "commit", "-q", "-m", "docs(plan): ff")
        write(r, "src/a.py", "1\n2\n")
        write(r, "src/c.py", "c\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "feat: work")
        write(r, "docs/superpowers/ledgers/2026-01-04-ff/progress.md", "# progress\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "docs(ledger): ff")
        self.head = git(r, "rev-parse", "HEAD")
        write(r, "later.txt", "l\n")   # a later, unrelated commit on main (the metrics line, the next run)
        git(r, "add", "."); git(r, "commit", "-q", "-m", "docs(metrics): ff")
        self.now = time.time()
        metrics.append(r, {"kind": "batch", "batch": "B", "base": self.base, "configs": ["c"], "assignment": {},
                           "groups": [], "at": metrics.utc(self.now - 3600)})
        metrics.append(r, {"kind": "start", "batch": "B", "spec": self.SPEC, "at": metrics.utc(self.now - 1800),
                           "main": self.base, "worktree": ".claude/worktrees/ff"})

    def rec(self, outcome=None):
        return metrics.build_record_static(self.repo, self.SPEC, "B", outcome, self.now)

    def test_range_comes_from_plan_and_ledger_commits(self):
        r = self.rec()
        self.assertIsNone(r["merge"])
        self.assertEqual((r["head"], r["base"]), (self.head, self.plan_parent))
        self.assertEqual(r["touched_list"], ["src/a.py", "src/c.py"])   # docs/superpowers/ is excluded
        self.assertEqual(r["outcome"], "merged")
        for k in ("head", "base", "merge", "touched_files", "diff_lines", "touched_list", "manifest"):
            self.assertNotIn(k, r["missing"], k)
        self.assertEqual(r["manifest"]["source"], "tasks")
        self.assertEqual(r["manifest"]["both"], 1)

    def test_branch_comes_from_the_start_worktree(self):
        self.assertEqual(self.rec()["branch"], "ff")

    def test_plan_on_main_before_start_uses_the_start_main(self):
        plan_commit = git(self.repo, "log", "--format=%H", "-1", "--", self.PLAN)
        metrics.append(self.repo, {"kind": "start", "batch": "B", "spec": self.SPEC, "at": metrics.utc(self.now - 900),
                                   "main": plan_commit, "worktree": ".claude/worktrees/ff"})
        self.assertEqual(self.rec()["base"], plan_commit)   # the plan is an ancestor of start.main: the range starts there

    def test_failed_run_with_its_ledger_on_main_is_not_called_merged(self):
        """A failed spec whose ledger was committed on main (branch gone) resolves its range from the ledger commits, as a
        fast-forwarded run does; the outcome stays what the caller said and no `merge` gap is added. Known: touched_files
        and manifest then describe the ledger range, although nothing of it was merged by a merge."""
        r = self.rec("failed")
        self.assertEqual(r["outcome"], "failed")
        self.assertIsNone(r["merge"])
        self.assertNotIn("merge", r["missing"])
        self.assertEqual((r["head"], r["base"]), (self.head, self.plan_parent))
        self.assertEqual(r["touched_list"], ["src/a.py", "src/c.py"])


class PartRunTest(FastForwardTest):
    """A spec run in parts: `<spec>#part-2` has its own plan (named `...-part2`, its `Spec:` line without the suffix) next
    to the part-1 plan; the part-2 record must resolve against the part-2 plan and its ledger directory."""
    PLAN2 = "docs/superpowers/plans/2026-01-05-ff-part2.md"

    def setUp(self):
        super().setUp()
        r = self.repo
        write(r, self.PLAN2, f"# P2\n\n**Spec:** `{self.SPEC}` section 4 (part 2)\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "docs(plan): ff part 2")
        self.p2_parent = git(r, "rev-parse", "HEAD^")
        write(r, "src/part2.py", "p\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "feat: part 2 work")
        write(r, "docs/superpowers/ledgers/2026-01-05-ff-part2/progress.md", "# progress\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "docs(ledger): ff part 2")
        self.head2 = git(r, "rev-parse", "HEAD")
        metrics.append(r, {"kind": "start", "batch": "B", "spec": self.SPEC + "#part-2", "at": metrics.utc(self.now - 600),
                           "main": self.p2_parent, "worktree": ".claude/worktrees/ff-part2"})

    def test_part_2_resolves_against_its_own_plan_and_ledger(self):
        r = metrics.build_record_static(self.repo, self.SPEC + "#part-2", "B", None, self.now)
        self.assertEqual(r["plan"], self.PLAN2)
        self.assertEqual((r["head"], r["base"]), (self.head2, self.p2_parent))
        self.assertEqual(r["touched_list"], ["src/part2.py"])
        self.assertNotIn("plan", r["missing"])

    def test_the_plain_spec_still_resolves_to_the_first_plan(self):
        r = self.rec()
        self.assertEqual(r["plan"], self.PLAN)
        self.assertEqual(r["head"], self.head)


class BackfillFastForwardTest(FastForwardTest):
    """`metrics backfill <spec>|--all-null [--apply]`: re-resolve null run records, touching nothing else."""
    ODD = '{"kind":"start",  "batch": "B", "zz": 1,"a":2}'   # not in json.dumps(sort_keys) form: must survive byte for byte

    def setUp(self):
        super().setUp()
        self.log = metrics.log_path(self.repo)
        old = {"kind": "run", "batch": "B", "spec": self.SPEC, "at": "2026-01-01T00:00:00Z", "branch": None, "head": None,
               "base": None, "merge": None, "touched_files": None, "diff_lines": None, "touched_list": None, "manifest": None,
               "stale_base": None, "tokens": {"total": 5}, "outcome": "merged",
               "missing": ["branch", "head", "base", "merge", "touched_files", "diff_lines", "touched_list", "manifest",
                           "stale_base", "limits"]}
        other = {"kind": "run", "batch": "B", "spec": "docs/superpowers/specs/done.md", "branch": "b", "head": "h", "base": "x"}
        with open(self.log, "a") as f:
            f.write(self.ODD + "\n" + json.dumps(old, sort_keys=True) + "\n" + json.dumps(other, sort_keys=True) + "\n")
        self.before = self.log.read_text()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            metrics.main(["backfill", "--repo", str(self.repo), *argv])
        return out.getvalue()

    def test_dry_run_prints_old_and_new_and_writes_nothing(self):
        out = self.run_cli("--all-null")
        self.assertIn(self.SPEC, out)
        self.assertIn(f"head None -> {self.head}", out)
        self.assertIn("manifest.recall_existing None -> ", out)
        self.assertEqual(self.log.read_text(), self.before)
        self.assertEqual(list(self.log.parent.glob("runs.jsonl.bak-*")), [])

    def test_apply_rewrites_only_the_null_run_and_keeps_a_backup(self):
        self.run_cli(self.SPEC, "--apply")
        a, b = self.before.splitlines(), self.log.read_text().splitlines()
        self.assertEqual(len(a), len(b))
        changed = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        self.assertEqual(len(changed), 1)
        new = json.loads(b[changed[0]])
        self.assertEqual((new["head"], new["base"], new["branch"]), (self.head, self.plan_parent, "ff"))
        self.assertEqual(new["tokens"], {"total": 5})            # fields outside the resolved set stay
        self.assertEqual(new["missing"], ["limits"])
        self.assertEqual(new["manifest"]["source"], "tasks")
        baks = list(self.log.parent.glob("runs.jsonl.bak-*"))
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].read_text(), self.before)
        self.assertIn(self.ODD, b)                               # byte-identical odd line

    NOPE = "docs/superpowers/specs/nope.md"

    def add_unresolved(self):
        rec = {"kind": "run", "batch": "B", "spec": self.NOPE, "at": "2026-01-01T00:00:00Z", "head": None, "outcome": "merged"}
        with open(self.log, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        self.before = self.log.read_text()

    def test_second_apply_is_a_no_op(self):
        self.run_cli("--all-null", "--apply")
        mid = self.log.read_text()
        self.assertEqual(self.run_cli("--all-null", "--apply").strip(), "0 records to backfill, 0 skipped")
        self.assertEqual(self.log.read_text(), mid)

    def test_unresolved_spec_is_named_and_counted_in_dry_run_and_apply(self):
        self.add_unresolved()
        for argv, summary in ((("--all-null",), "1 records to backfill, 1 skipped"),
                              (("--all-null", "--apply"), "1 records backfilled, 1 skipped")):
            out = self.run_cli(*argv)
            self.assertIn(f"skipped {self.NOPE}: no plan found", out)
            self.assertEqual(out.strip().splitlines()[-1], summary)
        again = self.run_cli("--all-null", "--apply")
        self.assertIn(f"skipped {self.NOPE}: no plan found", again)   # still null: still named
        self.assertIn(json.dumps({"kind": "run", "batch": "B", "spec": self.NOPE, "at": "2026-01-01T00:00:00Z",
                                  "head": None, "outcome": "merged"}, sort_keys=True), self.log.read_text())

    def test_reason_when_the_plan_exists_but_no_ledger_is_on_main(self):
        write(self.repo, "docs/superpowers/plans/2026-01-06-nl.md", "# P\n\n**Spec:** `docs/superpowers/specs/nl.md`\n")
        git(self.repo, "add", "."); git(self.repo, "commit", "-q", "-m", "docs(plan): nl")
        with open(self.log, "a") as f:
            f.write(json.dumps({"kind": "run", "batch": "B", "spec": "docs/superpowers/specs/nl.md", "head": None}) + "\n")
        self.assertIn("skipped docs/superpowers/specs/nl.md: no ledger commit on main", self.run_cli("--all-null"))

    def test_a_line_appended_between_resolve_and_write_survives_apply(self):
        late = {"kind": "start", "batch": "B", "spec": "docs/superpowers/specs/late.md", "at": "2026-01-02T00:00:00Z"}
        seen = []
        def hook():
            seen.append(1)
            metrics.append(self.repo, late)
        changes = metrics.backfill_null_runs(self.repo, self.SPEC, apply=True, _after_resolve=hook)
        self.assertEqual(seen, [1])
        self.assertEqual(len(changes), 1)
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), len(self.before.splitlines()) + 1)
        self.assertEqual(json.loads(lines[-1]), late)
        self.assertEqual(sum(1 for l in lines if '"head": "%s"' % self.head in l), 1)   # the rewrite still happened

    def test_a_line_changed_between_resolve_and_write_is_skipped_with_a_message(self):
        def hook():
            lines = self.log.read_text().splitlines()
            i = next(i for i, l in enumerate(lines) if '"head": null' in l and self.SPEC in l)
            lines[i] = lines[i].replace('"outcome": "merged"', '"outcome": "kept"')
            self.log.write_text("\n".join(lines) + "\n")
        skipped, err = [], io.StringIO()
        with contextlib.redirect_stderr(err):
            changes = metrics.backfill_null_runs(self.repo, self.SPEC, apply=True, _after_resolve=hook, skipped=skipped)
        self.assertEqual(changes, [])
        self.assertIn("changed since it was read", err.getvalue())
        self.assertIn('"outcome": "kept"', self.log.read_text())
        self.assertNotIn(self.head, self.log.read_text())
        self.assertEqual(list(self.log.parent.glob("runs.jsonl.bak-*")), [])   # nothing written: no backup either
        self.assertEqual([s for s, _ in skipped], [self.SPEC])


if __name__ == "__main__":
    unittest.main()
