"""findings: the shared state store, dismissal rule, line rendering and File/Dismiss decision. Scratch TC_STATE."""
import fcntl
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import analytics_post  # noqa: E402
import findings  # noqa: E402

NOW = 1795000000.0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name + "/state"})
        p.start()
        self.addCleanup(p.stop)
        self.path = Path(self.tmp.name) / "d" / "x.json"


class StoreTest(Base):
    def test_defaults(self):
        st = findings.Store(self.path).load()
        self.assertEqual(st, {"root": "", "failures": 0, "reported": {}, "dismissed": {}, "filed": {}, "posts": {}})

    def test_extra_defaults_and_type_check(self):
        s = findings.Store(self.path, extra={"drafts": {}, "pending_copies": []})
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"drafts": {"a": 1}, "pending_copies": "bad", "failures": "bad"}))
        st = s.read()
        self.assertEqual((st["drafts"], st["pending_copies"], st["failures"]), ({"a": 1}, [], 0))

    def test_roundtrip_atomic_and_keep(self):
        s = findings.Store(self.path, keep=3)
        st = s.load()
        st["posts"] = {f"n{d:02d}": {} for d in range(10)}
        s.write(st)
        self.assertEqual(sorted(s.read()["posts"]), ["n07", "n08", "n09"])
        self.assertFalse(self.path.with_suffix(".tmp").exists())
        self.assertEqual(len(findings.Store(self.path).read()["posts"]), 3)

    def test_default_keep_14(self):
        s = findings.Store(self.path)
        st = s.load()
        st["posts"] = {f"n{d:02d}": {} for d in range(20)}
        s.write(st)
        self.assertEqual(len(s.read()["posts"]), 14)

    def test_corrupt_file_reads_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[1")
        self.assertEqual(findings.Store(self.path).read()["failures"], 0)

    def test_lock_file_beside_and_exclusive(self):
        s = findings.Store(self.path)
        with s.locked():
            lock = self.path.with_suffix(".lock")
            self.assertTrue(lock.exists())
            with open(lock, "a") as f:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_update_saves_and_returns(self):
        s = findings.Store(self.path)
        out = s.update(lambda st: st.update(failures=2))
        self.assertEqual(out["failures"], 2)
        self.assertEqual(s.read()["failures"], 2)


class RuleTest(unittest.TestCase):
    def test_regrowth_boundary(self):
        st = {"dismissed": {"k": {"evidence_count": 10}}}
        self.assertEqual(findings.REGROWTH, 1.5)
        self.assertTrue(findings.dismissed_blocks(st, "k", 14))   # 1.4x
        self.assertTrue(findings.dismissed_blocks(st, "k", 14.9))  # 1.49x
        self.assertFalse(findings.dismissed_blocks(st, "k", 15))  # 1.5x shown
        self.assertFalse(findings.dismissed_blocks(st, "other", 1))

    def test_exports(self):
        self.assertIs(findings.escape, analytics_post.escape)
        self.assertEqual(findings.URL_MAX, 150)
        self.assertEqual(findings.MARKS["filed"], "💡 filed")
        self.assertEqual(findings.cut("a  b\nc", 10), "a b c")
        self.assertEqual(findings.cut("abcdefghij", 5), "abcd…")
        self.assertEqual(len(findings.kid("x")), 12)

    def test_value_line_drops_cut_link(self):
        parts = [("short", "http://a/b"), ("x" * 50, "http://c/d")]
        line = findings.value_line("high", "S", "low", parts, 20)
        self.assertIn("[short](http://a/b)", line)
        self.assertNotIn("http://c/d", line)
        self.assertIn("…", line)
        self.assertTrue(line.startswith("value high · effort S · risk low · evidence: "))
        self.assertNotIn("](", findings.value_line("v", "e", "r", parts, 20, links=False))


class DecideTest(unittest.TestCase):
    def st(self):
        return {"filed": {}, "dismissed": {}}

    def it(self):
        return {"key": "k", "count": 4, "decision": None}

    def test_file(self):
        st, it = self.st(), self.it()
        self.assertEqual(findings.decide(st, it, "file", NOW, lambda i: "L-" + i["key"]), "filed")
        self.assertEqual(st["filed"]["k"]["idea_line"], "L-k")
        self.assertEqual(it["decision"], "filed")

    def test_dismiss(self):
        st, it = self.st(), self.it()
        self.assertEqual(findings.decide(st, it, "dismiss", NOW, None), "dismissed")
        self.assertEqual(st["dismissed"]["k"]["evidence_count"], 4)
        self.assertEqual(it["decision"], "dismissed")

    def test_already_filed(self):
        st, it = self.st(), self.it()
        st["filed"]["k"] = {}
        self.assertEqual(findings.decide(st, it, "dismiss", NOW, None), "already filed")
        self.assertIsNone(it["decision"])

    def test_already_dismissed(self):
        st, it = self.st(), self.it()
        st["dismissed"]["k"] = {"evidence_count": 4}
        self.assertEqual(findings.decide(st, it, "file", NOW, None), "already dismissed")

    def test_already_decision(self):
        st, it = self.st(), self.it()
        it["decision"] = "dismissed"
        self.assertEqual(findings.decide(st, it, "file", NOW, None), "already dismissed")
        it["decision"] = "filed"
        self.assertEqual(findings.decide(st, it, "dismiss", NOW, None), "already filed")

    def test_regrown_dismissed_can_be_filed(self):
        st, it = self.st(), self.it()
        st["dismissed"]["k"] = {"evidence_count": 2}
        self.assertEqual(findings.decide(st, it, "file", NOW, lambda i: "L"), "filed")


if __name__ == "__main__":
    unittest.main()
