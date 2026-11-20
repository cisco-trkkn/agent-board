import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctxsize  # noqa: E402
import usage  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "ctxsize", "lead.jsonl")
SCRIPT = os.path.join(os.path.dirname(HERE), "ctxsize.py")
# literals from fixtures/ctxsize/README.md
T1, T2, T3, T4 = 1795216603.804, 1795216611.375, 1795216623.086, 1795216632.145
TURNS = [(T1, 63194, 63403), (T2, 67099, 67478), (T3, 73748, 74262), (T4, 75890, 76129)]


def cli(*args):
    p = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True)
    return p.returncode, p.stdout.strip()


class Base(unittest.TestCase):
    def tmp(self, text):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, True))
        p = os.path.join(d, "f")
        with open(p, "w") as f:
            f.write(text)
        return p


class TestReader(Base):
    def test_last_turn_skips_no_usage_line(self):
        self.assertEqual(ctxsize.context_tokens(FIX), 75890)

    def test_sidechain_ignored_everywhere(self):
        self.assertEqual(ctxsize.peak(FIX), 75890)   # sidechain line is 95453
        self.assertNotIn(95453, [t["context"] for t in ctxsize.turns(FIX)])

    def test_turns_collapse_request_ids(self):
        got = [(t["ts"], t["context"], t["total"]) for t in ctxsize.turns(FIX)]
        self.assertEqual(got, TURNS)

    def test_peak_window_excluding_largest(self):
        self.assertEqual(ctxsize.peak(FIX, until=T3 + 1), 73748)
        self.assertEqual(ctxsize.peak(FIX, since=T1, until=T2), 67099)

    def test_peak_since_only_until_only_and_empty(self):
        self.assertEqual(ctxsize.peak(FIX, since=T2), 75890)
        self.assertEqual(ctxsize.peak(FIX, until=T1), 63194)
        self.assertIsNone(ctxsize.peak(FIX, since=T4 + 100))
        self.assertIsNone(ctxsize.peak(FIX, since=T1 + 0.1, until=T1 + 0.2))

    def test_first_turns_tokens(self):
        self.assertEqual(ctxsize.first_turns_tokens(FIX, n=2), 63403 + 67478)
        self.assertEqual(ctxsize.first_turns_tokens(FIX, n=10), 63403 + 67478 + 74262 + 76129)
        self.assertEqual(ctxsize.first_turns_tokens(FIX), 63403 + 67478 + 74262 + 76129)

    def test_agrees_with_usage_index(self):
        n = 0
        for raw in open(FIX).read().splitlines():
            d = json.loads(raw)
            if d.get("type") == "assistant" and not d.get("isSidechain") and (d.get("message") or {}).get("usage"):
                row = usage.row_from_line(d, False)
                self.assertIn(usage.context_tokens(row), [t[1] for t in TURNS])
                n += 1
        self.assertEqual(n, 7)

    def test_bad_input_returns_none(self):
        d = tempfile.mkdtemp()
        for p in (os.path.join(d, "missing"), self.tmp(""), self.tmp("not json\n{broken\n"), self.tmp("[1,2]\n3\n\"s\"\nnull\n")):
            self.assertIsNone(ctxsize.context_tokens(p))
            self.assertIsNone(ctxsize.peak(p))
            self.assertEqual(ctxsize.turns(p), [])
            self.assertIsNone(ctxsize.first_turns_tokens(p))


class TestDoc(Base):
    def test_under_budget(self):
        line, over = ctxsize.doc_estimate(self.tmp("## A\n" + "x" * 400))
        self.assertFalse(over)
        self.assertEqual(line, "handoff doc: 101 tokens (budget 3000): ok")

    def test_over_budget_names_largest_section(self):
        text = "top\n## Small\nabc\n## Big\n" + "y" * 13000 + "\n"
        line, over = ctxsize.doc_estimate(self.tmp(text))
        self.assertTrue(over)
        self.assertIn("over; largest section: Big", line)
        self.assertEqual(ctxsize.doc_estimate(self.tmp(text), budget=100000)[1], False)

    def test_unreadable(self):
        self.assertIsNone(ctxsize.doc_estimate("/nonexistent/zzz"))


class TestCli(Base):
    def test_last_and_peak(self):
        self.assertEqual(cli("last", FIX), (0, "75890"))
        self.assertEqual(cli("peak", FIX), (0, "75890"))
        self.assertEqual(cli("peak", FIX, "--until", "2026-11-20T23:17:04Z"), (0, "73748"))
        self.assertEqual(cli("peak", FIX, "--since", "2026-11-20T23:16:50Z", "--until", "2026-11-20T23:16:55Z"), (0, "67099"))

    def test_doc(self):
        rc, out = cli("doc", self.tmp("## A\nhi\n"))
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("handoff doc: "))

    def test_silent_exit_zero(self):
        self.assertEqual(cli(), (0, ""))
        self.assertEqual(cli("last", "/nonexistent/zzz"), (0, ""))
        self.assertEqual(cli("last", self.tmp("garbage\n")), (0, ""))
        self.assertEqual(cli("doc", "/nonexistent/zzz"), (0, ""))
        self.assertEqual(cli("peak", FIX, "--since", "2099-01-01T00:00:00Z"), (0, ""))


if __name__ == "__main__":
    unittest.main()
