import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import ideas  # noqa: E402


class IdeasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_IDEAS_DIR"] = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_IDEAS_DIR", None)

    def test_add_and_load(self):
        ideas.add("p", "a\nb", "x\ny", now=0)
        text = (Path(self.tmp.name) / "p.md").read_text()
        self.assertTrue(text.startswith("# Ideas: p\n\n"))
        self.assertRegex(text, r"- \[ \] \d{4}-\d{2}-\d{2} \d{2}:\d{2} · a b\n  x\n  y\n")
        ideas.add("p", "second")
        text = (Path(self.tmp.name) / "p.md").read_text()
        self.assertEqual(text.count("# Ideas"), 1)
        got = ideas.load("p")
        self.assertEqual([i["text"] for i in got], ["a b", "second"])
        self.assertEqual(got[0]["detail"], "x\ny")

    def test_statuses(self):
        (Path(self.tmp.name) / "p.md").write_text(
            "# Ideas: p\n\n- [ ] 2026-10-16 10:00 · one\n- [x] 2026-10-16 10:01 · two → docs/s.md\n- [-] 2026-10-16 10:02 · three\n")
        self.assertEqual([i["status"] for i in ideas.load("p")], ["open", "taken", "dropped"])
        self.assertEqual(ideas.open_count("p"), 1)

    def test_bad_input(self):
        for bad in ("a/b", "..", ""):
            with self.assertRaises(ValueError):
                ideas.add(bad, "x")
        with self.assertRaises(ValueError):
            ideas.add("p", "   ")

    def test_concurrent_cli(self):
        env = {**os.environ, "TC_IDEAS_DIR": self.tmp.name}
        procs = [subprocess.Popen([sys.executable, "-I", str(HERE / "ideas.py"), "add", "--project", "p", "--", f"idea {n}"], env=env)
                 for n in range(20)]
        self.assertEqual([p.wait() for p in procs], [0] * 20)
        self.assertEqual(len(ideas.load("p")), 20)
        self.assertEqual(sorted(int(re.search(r"\d+$", i["text"]).group()) for i in ideas.load("p")), list(range(20)))


if __name__ == "__main__":
    unittest.main()
