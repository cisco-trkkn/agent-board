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


class IdeasLegacyTest(unittest.TestCase):
    """Without TC_IDEAS_DIR: ~/.local/state/agent-board/ideas, reading the old ~/.claude/ideas until the first write."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.old_env = {k: os.environ.pop(k, None) for k in ("TC_IDEAS_DIR",)}
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        self.legacy = self.home / ".claude" / "ideas"
        self.legacy.mkdir(parents=True)
        self.old = "# Ideas: p\n\n- [ ] 2026-10-16 10:00 · old one\n  detail\n"
        (self.legacy / "p.md").write_text(self.old)
        self.new = self.home / ".local" / "state" / "agent-board" / "ideas" / "p.md"

    def tearDown(self):
        os.environ["HOME"] = self.old_home
        for k, v in self.old_env.items():
            if v is not None:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_load_reads_legacy_when_new_missing(self):
        self.assertEqual([i["text"] for i in ideas.load("p")], ["old one"])
        self.assertFalse(self.new.exists())

    def test_first_write_copies_legacy_and_leaves_it(self):
        ideas.add("p", "new one", now=0)
        self.assertEqual([i["text"] for i in ideas.load("p")], ["old one", "new one"])
        self.assertTrue(self.new.read_text().startswith(self.old))
        self.assertEqual((self.legacy / "p.md").read_text(), self.old)

    def test_edit_seeds_from_legacy_too(self):
        key = ideas.load("p")[0]["key"]
        ideas.edit("p", key, "changed")
        self.assertEqual([i["text"] for i in ideas.load("p")], ["changed"])
        self.assertEqual((self.legacy / "p.md").read_text(), self.old)

    def test_new_file_wins_over_legacy(self):
        self.new.parent.mkdir(parents=True)
        self.new.write_text("# Ideas: p\n\n- [ ] 2026-10-17 10:00 · fresh\n")
        self.assertEqual([i["text"] for i in ideas.load("p")], ["fresh"])
        ideas.add("p", "more", now=0)
        self.assertEqual([i["text"] for i in ideas.load("p")], ["fresh", "more"])

    def test_tc_ideas_dir_wins_over_both(self):
        d = self.home / "elsewhere"
        os.environ["TC_IDEAS_DIR"] = str(d)
        try:
            self.assertEqual(ideas.load("p"), [])
            ideas.add("p", "only", now=0)
            self.assertEqual([i["text"] for i in ideas.load("p")], ["only"])
            self.assertFalse(self.new.exists())
        finally:
            os.environ.pop("TC_IDEAS_DIR")


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

    SAMPLE = ("# Ideas: p\n\n"
              "- [ ] 2026-10-16 10:00 · one\n  d1\n  d2\n"
              "- [x] 2026-10-16 10:01 · two → docs/s.md\n"
              "- [ ] 2026-10-16 10:02 · three\n")

    def write(self, text, project="p"):
        (Path(self.tmp.name) / f"{project}.md").write_text(text)

    def read(self, project="p"):
        return (Path(self.tmp.name) / f"{project}.md").read_text()

    def test_load_keys(self):
        self.write(self.SAMPLE + "- [-] 2026-10-16 10:03 · four → moved to q\n")
        got = ideas.load("p")
        self.assertEqual(got[0]["key"], "2026-10-16 10:00 · one")
        self.assertEqual(got[1]["key"], "2026-10-16 10:01 · two → docs/s.md")
        self.assertEqual((got[3]["text"], got[3]["moved_to"]), ("four", "q"))
        self.assertEqual(got[3]["key"], "2026-10-16 10:03 · four → moved to q")
        self.assertEqual(got[0]["moved_to"], "")

    def test_edit_replaces_text_and_detail(self):
        self.write(self.SAMPLE)
        key = ideas.edit("p", "2026-10-16 10:00 · one", "  one   better ", "e1\n\ne2")
        self.assertEqual(key, "2026-10-16 10:00 · one better")
        self.assertEqual(self.read(), self.SAMPLE.replace("· one\n  d1\n  d2\n", "· one better\n  e1\n  e2\n"))

    def test_edit_can_clear_detail(self):
        self.write(self.SAMPLE)
        ideas.edit("p", "2026-10-16 10:00 · one", "one", "")
        self.assertIn("· one\n- [x]", self.read())

    def test_edit_refuses_taken_and_empty(self):
        self.write(self.SAMPLE)
        with self.assertRaises(ValueError):
            ideas.edit("p", "2026-10-16 10:01 · two → docs/s.md", "x")
        with self.assertRaises(ValueError):
            ideas.edit("p", "2026-10-16 10:00 · one", "   ")
        self.assertEqual(self.read(), self.SAMPLE)

    def test_stale_key(self):
        self.write(self.SAMPLE)
        with self.assertRaises(ideas.Stale):
            ideas.edit("p", "2026-10-16 10:00 · gone", "x")
        self.write(self.SAMPLE + "- [ ] 2026-10-16 10:02 · three\n")
        with self.assertRaises(ideas.Stale):
            ideas.set_status("p", "2026-10-16 10:02 · three", "dropped")

    def test_drop_and_restore(self):
        self.write(self.SAMPLE)
        ideas.set_status("p", "2026-10-16 10:02 · three", "dropped")
        self.assertIn("- [-] 2026-10-16 10:02 · three\n", self.read())
        ideas.set_status("p", "2026-10-16 10:02 · three", "open")
        self.assertEqual(self.read(), self.SAMPLE)

    def test_status_refusals(self):
        self.write(self.SAMPLE + "- [-] 2026-10-16 10:03 · four → moved to q\n")
        with self.assertRaises(ValueError):
            ideas.set_status("p", "2026-10-16 10:01 · two → docs/s.md", "dropped")
        with self.assertRaises(ValueError):
            ideas.set_status("p", "2026-10-16 10:03 · four → moved to q", "open")
        with self.assertRaises(ValueError):
            ideas.set_status("p", "2026-10-16 10:02 · three", "taken")

    def test_move(self):
        self.write(self.SAMPLE)
        ideas.move("p", "2026-10-16 10:00 · one", "q")
        self.assertEqual(self.read("q"), "# Ideas: q\n\n- [ ] 2026-10-16 10:00 · one\n  d1\n  d2\n")
        self.assertIn("- [-] 2026-10-16 10:00 · one → moved to q\n  d1\n  d2\n", self.read())
        got = ideas.load("p")[0]
        self.assertEqual((got["status"], got["text"], got["moved_to"]), ("dropped", "one", "q"))
        ideas.move("p", "2026-10-16 10:02 · three", "q")   # appends under the existing header
        self.assertEqual(self.read("q").count("# Ideas"), 1)
        self.assertEqual([i["text"] for i in ideas.load("q")], ["one", "three"])

    def test_move_refusals(self):
        self.write(self.SAMPLE)
        with self.assertRaises(ValueError):
            ideas.move("p", "2026-10-16 10:00 · one", "p")
        with self.assertRaises(ValueError):
            ideas.move("p", "2026-10-16 10:00 · one", "../x")
        with self.assertRaises(ValueError):
            ideas.move("p", "2026-10-16 10:01 · two → docs/s.md", "q")
        with self.assertRaises(ideas.Stale):
            ideas.move("p", "2026-10-16 10:00 · nope", "q")
        self.assertFalse((Path(self.tmp.name) / "q.md").exists())

    def test_add_after_edit(self):
        self.write(self.SAMPLE)
        ideas.edit("p", "2026-10-16 10:02 · three", "3")
        ideas.add("p", "five")
        self.assertEqual([i["text"] for i in ideas.load("p")], ["one", "two → docs/s.md", "3", "five"])


if __name__ == "__main__":
    unittest.main()
