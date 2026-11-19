import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import context  # noqa: E402
import dream_check as dc  # noqa: E402

REAL = Path.home() / ".local/state/agent-board/context"


def doc(map=(), run=(), gotchas=(), decisions=(), title="# p: shared agent context\nLast curated: 2026-11-18\n"):
    out = [title] if title else []
    for name, lines in (("Map", map), ("How to run", run), ("Gotchas", gotchas), ("Decisions", decisions)):
        out.append(f"## {name}\n")
        out.extend(lines)
        if lines:
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def e(text, date="2026-11-01", files=None, suffix=""):
    f = f" (files: {', '.join(files)})" if files is not None else ""
    return f"- {text}{f} · {date}{suffix}"


REPORT = {"changed": {"merged": [], "archived": 0, "stale": 0, "added": 0},
          "contradictions": [], "proposals": [], "summary": "s"}


def rep(**kw):
    r = json.loads(json.dumps(REPORT))
    r.update(kw)
    return r


EMPTY = doc(title="")
A = e("alpha fact one", files=["a.py"])
B = e("beta fact two", files=["b.py"])


class ParseTest(unittest.TestCase):
    def test_ok(self):
        ents, probs = dc.parse(doc(map=[A], gotchas=[B]))
        self.assertEqual(probs, [])
        self.assertEqual(ents, [("Map", A), ("Gotchas", B)])

    def test_missing_heading(self):
        _, probs = dc.parse("## Map\n\n## Gotchas\n\n## Decisions\n")
        self.assertTrue(any("headings" in p for p in probs))

    def test_stray_line(self):
        _, probs = dc.parse(doc(map=[A, "stray prose"]))
        self.assertTrue(any("not an entry" in p for p in probs))

    def test_undated_entry(self):
        _, probs = dc.parse(doc(map=["- no date here"]))
        self.assertTrue(any("not a valid entry" in p for p in probs))

    def test_date_of_is_the_entry_date_not_archived(self):
        line = e("x", date="2026-10-01", suffix=" · archived 2026-11-18")
        self.assertEqual(dc.date_of(line), "2026-10-01")
        line = e("x", date="2026-10-01", suffix=" · archived 2026-11-18 · stale: a.py gone")
        self.assertEqual(dc.date_of(line), "2026-10-01")
        self.assertEqual(dc.base(line), e("x", date="2026-10-01"))

    def test_real_files_parse(self):
        if not (REAL / "agent-board.md").exists():
            self.skipTest("no real context files")
        for p in sorted(REAL.glob("*.md")):
            if p.name.endswith(".lock"):
                continue
            _, probs = dc.parse(p.read_text())
            self.assertEqual(probs, [], p.name)
        ents, _ = dc.parse((REAL / "agent-board.md").read_text())
        self.assertTrue(ents)


class CapTest(unittest.TestCase):
    @unittest.skipUnless(hasattr(context, "CAP"), "context.CAP not added yet (Task 1)")
    def test_cap_matches_context(self):
        self.assertEqual(dc.CAP, context.CAP)

    def core_of(self, n):
        pad = "x" * (n - len(doc(map=[e("")]).encode()))
        core = doc(map=[e(pad)])
        self.assertEqual(len(core.encode()), n)
        return core

    def test_over_cap_rejected(self):
        self.assertIsNone(dc.check(EMPTY, EMPTY, self.core_of(8192), EMPTY, REPORT))
        self.assertEqual(dc.check(EMPTY, EMPTY, self.core_of(8193), EMPTY, REPORT),
                         "core over 8192 bytes (8193)")

    def test_cap_is_bytes_not_chars(self):
        core = doc(map=[e("é" * 4100)])
        self.assertLess(len(core), 8192)
        self.assertTrue(dc.check(EMPTY, EMPTY, core, EMPTY, REPORT).startswith("core over 8192 bytes"))


class CheckTest(unittest.TestCase):
    def chk(self, oc, oa, nc, na, report=REPORT, root=None):
        return dc.check(oc, oa, nc, na, report, root)

    def test_unchanged_passes(self):
        self.assertIsNone(self.chk(doc(map=[A]), EMPTY, doc(map=[A]), EMPTY))

    def test_lost_entry_rejected(self):
        r = self.chk(doc(map=[A, B]), EMPTY, doc(map=[A]), EMPTY)
        self.assertEqual(r, "entry lost: " + B[:60])

    def test_moved_entry_with_suffixes_is_not_lost(self):
        moved = A + " · archived 2026-11-18 · stale: a.py gone"
        self.assertIsNone(self.chk(doc(map=[A]), EMPTY, doc(), doc(map=[moved])))

    def test_lost_from_old_archive(self):
        old_a = doc(map=[A + " · archived 2026-11-01"])
        self.assertTrue(self.chk(doc(), old_a, doc(), EMPTY).startswith("entry lost: "))

    def test_archived_entry_in_core(self):
        r = self.chk(doc(map=[A]), EMPTY, doc(map=[A + " · archived 2026-11-18"]), EMPTY)
        self.assertEqual(r, "core invalid: archived entry in the core")
        r = self.chk(doc(map=[A]), EMPTY, doc(map=[A + " · stale: a.py gone"]), EMPTY)
        self.assertEqual(r, "core invalid: archived entry in the core")

    def test_core_invalid_first_problem(self):
        r = self.chk(EMPTY, EMPTY, doc(map=["junk"]), EMPTY)
        self.assertTrue(r.startswith("core invalid: line "))

    def test_archive_invalid(self):
        r = self.chk(EMPTY, EMPTY, EMPTY, doc(map=["junk"]))
        self.assertTrue(r.startswith("archive invalid: "))

    def test_empty_archives_are_skeletons(self):
        self.assertIsNone(self.chk(doc(map=[A]), "", doc(map=[A]), ""))

    def test_report_invalid_comes_first(self):
        r = self.chk(doc(map=[A]), EMPTY, doc(map=["junk"]), EMPTY, report=[])
        self.assertTrue(r.startswith("report invalid: "))

    # merges (G3)
    def merge_case(self, new, into=None, declared=True):
        old = [e("first part", files=["a.py"]), e("second part", files=["b.py"])]
        merged = [{"into": new[:60] if into is None else into, "from": [o[:60] for o in old]}] if declared else []
        report = rep(changed={**REPORT["changed"], "merged": merged})
        return self.chk(doc(map=old), EMPTY, doc(map=[new]), EMPTY, report)

    def test_merged_entry_accepted(self):
        new = e("first and second part", date="2026-11-10", files=["a.py", "b.py", "c.py"])
        self.assertIsNone(self.merge_case(new))

    def test_merge_dropping_a_file_rejected(self):
        new = e("first and second part", date="2026-11-10", files=["a.py"])
        self.assertTrue(self.merge_case(new).startswith("entry lost: "))

    def test_merge_with_older_date_rejected(self):
        new = e("first and second part", date="2026-10-01", files=["a.py", "b.py"])
        self.assertTrue(self.merge_case(new).startswith("entry lost: "))

    def test_undeclared_merge_rejected(self):
        new = e("first and second part", date="2026-11-10", files=["a.py", "b.py"])
        self.assertTrue(self.merge_case(new, declared=False).startswith("entry lost: "))

    def test_merge_into_missing_entry_rejected(self):
        new = e("first and second part", date="2026-11-10", files=["a.py", "b.py"])
        self.assertTrue(self.merge_case(new, into="- nothing like this").startswith("entry lost: "))

    # stale (G5)
    def test_stale_claim_file_exists(self):
        stale = A + " · archived 2026-11-18 · stale: a.py gone"
        with tempfile.TemporaryDirectory() as root:
            args = (doc(map=[A]), EMPTY, doc(), doc(map=[stale]))
            self.assertIsNone(self.chk(*args, root=root))
            (Path(root) / "a.py").write_text("x")
            self.assertEqual(self.chk(*args, root=root), "stale claim: a.py exists")
            self.assertIsNone(self.chk(*args))   # no root: not checked

    def test_stale_claim_without_files(self):
        old = e("no files cited")
        stale = old + " · archived 2026-11-18 · stale: x gone"
        with tempfile.TemporaryDirectory() as root:
            r = self.chk(doc(map=[old]), EMPTY, doc(), doc(map=[stale]), root=root)
        self.assertEqual(r, "stale claim: no files cited")

    def test_already_stale_is_not_rechecked(self):
        stale = A + " · archived 2026-11-01 · stale: a.py gone"
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "a.py").write_text("x")
            self.assertIsNone(self.chk(EMPTY, doc(map=[stale]), EMPTY, doc(map=[stale]), root=root))


class CountsTest(unittest.TestCase):
    def test_counts_ignore_the_report(self):
        old = [e("first part", files=["a.py"]), e("second part", files=["b.py"]), A, B]
        merged_into = e("first and second part", date="2026-11-10", files=["a.py", "b.py"])
        stale_b = B + " · archived 2026-11-18 · stale: b.py gone"
        new_core = doc(map=[merged_into, e("brand new")])
        new_arch = doc(map=[A + " · archived 2026-11-18", stale_b])
        liar = rep(changed={"merged": [{"into": merged_into[:60], "from": [o[:60] for o in old[:2]]}],
                            "archived": 99, "stale": 99, "added": 99})
        got = dc.counts(doc(map=old), EMPTY, new_core, new_arch, liar)
        self.assertEqual(got, {"merged": 2, "archived": 2, "stale": 1, "added": 1})

    def test_no_change_is_zero(self):
        self.assertEqual(dc.counts(doc(map=[A]), EMPTY, doc(map=[A]), EMPTY, REPORT),
                         {"merged": 0, "archived": 0, "stale": 0, "added": 0})


class ReportProblemTest(unittest.TestCase):
    def bad(self, report):
        r = dc.report_problem(report)
        self.assertIsInstance(r, str)
        self.assertTrue(r)

    def test_valid(self):
        good = rep(contradictions=[{"a": "x", "b": "y", "note": "n"}],
                   proposals=[{"kind": "idea", "text": "t", "evidence": ["e"]}])
        self.assertIsNone(dc.report_problem(good))

    def test_wrong_shapes(self):
        self.bad([])
        self.bad({})
        self.bad(rep(changed=[]))
        for k in ("merged", "archived", "stale", "added"):
            r = rep()
            del r["changed"][k]
            self.bad(r)
        self.bad(rep(changed={**REPORT["changed"], "merged": "x"}))
        self.bad(rep(changed={**REPORT["changed"], "merged": [{"into": 1, "from": []}]}))
        self.bad(rep(changed={**REPORT["changed"], "merged": [{"into": "i", "from": "f"}]}))
        self.bad(rep(changed={**REPORT["changed"], "archived": "3"}))
        self.bad(rep(changed={**REPORT["changed"], "stale": 1.5}))
        self.bad(rep(changed={**REPORT["changed"], "added": True}))
        self.bad(rep(contradictions={}))
        self.bad(rep(contradictions=[{"a": "x", "b": "y"}]))
        self.bad(rep(proposals="x"))
        self.bad(rep(proposals=[{"kind": "rule", "text": "t", "evidence": []}]))
        self.bad(rep(proposals=[{"kind": "idea", "text": "", "evidence": []}]))
        self.bad(rep(proposals=[{"kind": "idea", "text": "  ", "evidence": []}]))
        self.bad(rep(proposals=[{"kind": "observer", "text": "t", "evidence": "e"}]))
        self.bad(rep(summary=3))
        r = rep()
        del r["summary"]
        self.bad(r)


class DiffTest(unittest.TestCase):
    def test_empty_when_unchanged(self):
        self.assertEqual(dc.diff(doc(map=[A]), EMPTY, doc(map=[A]), EMPTY, "p"), "")

    def test_labels_and_both_files(self):
        out = dc.diff(doc(map=[A]), EMPTY, doc(), doc(map=[A + " · archived 2026-11-18"]), "p")
        self.assertIn("--- p.md", out)
        self.assertIn("+++ p.md", out)
        self.assertIn("--- p.archive.md", out)
        self.assertIn("+++ p.archive.md", out)
        self.assertIn("-" + A, out)
        self.assertIn("+" + A + " · archived 2026-11-18", out)


class CliTest(unittest.TestCase):
    def run_cli(self, files, report=REPORT, root=None, skip=()):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            args = []
            for flag, name in (("--old-core", "oc"), ("--old-archive", "oa"), ("--new-core", "nc"),
                               ("--new-archive", "na")):
                p = d / name
                if name not in skip:
                    p.write_text(files[name])
                args += [flag, str(p)]
            (d / "r.json").write_text(json.dumps(report))
            args += ["--report", str(d / "r.json")]
            if root:
                args += ["--root", root]
            return subprocess.run([sys.executable, "-I", str(HERE / "dream_check.py"), "verify", *args],
                                  capture_output=True, text=True)

    def test_verify_cli_ok_and_fail(self):
        ok = self.run_cli({"oc": doc(map=[A]), "oa": EMPTY, "nc": doc(map=[A]), "na": EMPTY})
        self.assertEqual((ok.returncode, ok.stdout.strip()), (0, "ok"))
        bad = self.run_cli({"oc": doc(map=[A, B]), "oa": EMPTY, "nc": doc(map=[A]), "na": EMPTY})
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(bad.stdout.strip(), "entry lost: " + B[:60])

    def test_missing_archives_read_as_empty(self):
        r = self.run_cli({"oc": doc(map=[A]), "nc": doc(map=[A])}, skip=("oa", "na"))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"))

    def test_root_is_passed(self):
        stale = A + " · archived 2026-11-18 · stale: a.py gone"
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "a.py").write_text("x")
            r = self.run_cli({"oc": doc(map=[A]), "oa": EMPTY, "nc": doc(), "na": doc(map=[stale])}, root=root)
        self.assertEqual((r.returncode, r.stdout.strip()), (1, "stale claim: a.py exists"))


if __name__ == "__main__":
    unittest.main()
