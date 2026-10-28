import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ideas  # noqa: E402


class IssueTokenTest(unittest.TestCase):
    """' · gl#<iid>' on an idea line: parsed into "issue", kept by edit, dropped by move, written by set_issue."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("TC_IDEAS_DIR")
        os.environ["TC_IDEAS_DIR"] = self.tmp.name
        self.f = Path(self.tmp.name) / "p.md"

    def tearDown(self):
        if self.old is None:
            os.environ.pop("TC_IDEAS_DIR", None)
        else:
            os.environ["TC_IDEAS_DIR"] = self.old
        self.tmp.cleanup()

    def write(self, *lines):
        self.f.write_text("# Ideas: p\n\n" + "".join(l + "\n" for l in lines))

    def test_token_is_parsed_out_of_text(self):
        # mutation: drop the _split_issue call in load() -> text keeps ' · gl#12', issue missing
        self.write("- [ ] 2026-10-28 10:00 · retries · gl#12")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"]), ("retries", 12))
        self.assertEqual(i["key"], "2026-10-28 10:00 · retries · gl#12")

    def test_token_before_spec_suffix(self):
        self.write("- [x] 2026-10-28 10:00 · retries · gl#12 → docs/s.md")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"]), ("retries → docs/s.md", 12))

    def test_token_before_moved_suffix(self):
        self.write("- [-] 2026-10-28 10:00 · retries · gl#12 → moved to q")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"], i["moved_to"]), ("retries", 12, "q"))

    def test_gl_in_the_middle_is_text(self):
        # mutation: drop the (?= → |$) lookahead in ISSUE_RE -> issue == 3
        self.write("- [ ] 2026-10-28 10:00 · see · gl#3 for context")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"]), ("see · gl#3 for context", None))

    def test_no_token_issue_none(self):
        self.write("- [ ] 2026-10-28 10:00 · plain")
        self.assertIsNone(ideas.load("p")[0]["issue"])

    def test_edit_keeps_token(self):
        # mutation: return f"- [ ] {ts} · {text}" without the token in edit() -> issue None after edit
        self.write("- [ ] 2026-10-28 10:00 · retries · gl#12")
        ideas.edit("p", "2026-10-28 10:00 · retries · gl#12", "retries with backoff")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"]), ("retries with backoff", 12))

    def test_edit_cannot_type_a_token(self):
        self.write("- [ ] 2026-10-28 10:00 · retries")
        ideas.edit("p", "2026-10-28 10:00 · retries", "retries · gl#99")
        self.assertIsNone(ideas.load("p")[0]["issue"])

    def test_move_drops_token_on_target_keeps_on_source(self):
        self.write("- [ ] 2026-10-28 10:00 · retries · gl#12")
        ideas.move("p", "2026-10-28 10:00 · retries · gl#12", "q")
        [t] = ideas.load("q")
        self.assertEqual((t["text"], t["issue"]), ("retries", None))
        [s] = ideas.load("p")
        self.assertEqual((s["status"], s["issue"], s["moved_to"]), ("dropped", 12, "q"))

    def test_set_issue_open_appends(self):
        self.write("- [ ] 2026-10-28 10:00 · retries", "  detail")
        ideas.set_issue("p", "2026-10-28 10:00 · retries", 7)
        self.assertIn("- [ ] 2026-10-28 10:00 · retries · gl#7\n  detail\n", self.f.read_text())

    def test_set_issue_closed_goes_before_suffix(self):
        self.write("- [x] 2026-10-28 10:00 · a → b → docs/s.md")
        ideas.set_issue("p", "2026-10-28 10:00 · a → b → docs/s.md", 7)
        self.assertIn("· a → b · gl#7 → docs/s.md\n", self.f.read_text())

    def test_set_issue_same_iid_is_noop_other_iid_is_stale(self):
        # mutation: drop the `have != iid` check -> a second token is appended
        self.write("- [ ] 2026-10-28 10:00 · retries · gl#7")
        ideas.set_issue("p", "2026-10-28 10:00 · retries · gl#7", 7)
        self.assertEqual(self.f.read_text().count("gl#"), 1)
        with self.assertRaises(ideas.Stale):
            ideas.set_issue("p", "2026-10-28 10:00 · retries · gl#7", 8)


if __name__ == "__main__":
    unittest.main()
