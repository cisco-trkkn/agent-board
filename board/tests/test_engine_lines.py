"""engine_lines: the board delivers the engine's lead-lines file, one line in flight, cursor after delivery."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import artifacts  # noqa: E402
import engine_lines  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name, "TC_ENGINE_DIR": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.dir = Path(self.tmp.name)
        self.q = artifacts.CommentQueue()
        self.add = lambda text: self.q.add_line("p", text)
        self.pending = lambda: [c["text"] for c in self.q.pending("p")]

    def write(self, *lines, raw=()):
        with open(self.dir / "p.lead.jsonl", "a", encoding="utf-8") as f:
            for seq, text in lines:
                f.write(json.dumps({"seq": seq, "ts": 1.0, "text": text}) + "\n")
            for r in raw:
                f.write(r + "\n")

    def tick(self, state, **kw):
        return engine_lines.tick("p", self.add, self.pending, state, **kw)

    def cursor(self):
        p = self.dir / "p.lead.cursor"
        return p.read_text().strip() if p.exists() else None

    def deliver(self):
        for c in self.q.pending("p"):
            self.q._items["p"].remove(c)


class TickTest(Base):
    def test_one_in_flight_then_next_after_delivery(self):
        self.write((1, "[Engine] your turn: a"), (2, "[Engine] your turn: b"))
        st = {}
        self.tick(st)
        self.assertEqual(self.pending(), ["[Engine] your turn: a"])
        self.tick(st)
        self.assertEqual(self.pending(), ["[Engine] your turn: a"])   # still waiting: nothing advances
        self.assertIsNone(self.cursor())
        self.deliver()
        self.tick(st)   # delivered: cursor moves, next is handed over
        self.assertEqual(self.cursor(), "1")
        self.assertEqual(self.pending(), ["[Engine] your turn: b"])
        self.deliver()
        self.tick(st)
        self.assertEqual(self.cursor(), "2")
        self.assertEqual(self.pending(), [])

    def test_concurrent_ticks_add_once(self):
        self.write((1, "[Engine] your turn: a"))
        self.tick({})
        self.tick({})
        self.assertEqual(self.pending(), ["[Engine] your turn: a"])

    def test_seq_at_or_under_cursor_never_handed_over_after_restart(self):
        self.write((1, "x1"), (2, "x2"), (2, "x2 again"), (1, "x1 again"), (3, "x3"))
        (self.dir / "p.lead.cursor").write_text("2")
        self.tick({})   # fresh state, as after a restart
        self.assertEqual(self.pending(), ["x3"])

    def test_lost_queue_hands_same_line_again(self):
        self.write((1, "[Engine] awaiting you: s: q"))
        self.tick({})
        self.q = artifacts.CommentQueue()   # board restart: queue empty, state fresh
        self.tick({})
        self.assertEqual(self.pending(), ["[Engine] awaiting you: s: q"])
        self.assertIsNone(self.cursor())

    def test_malformed_lines_skipped_and_counted(self):
        self.write((1, "ok"), raw=["{not json", json.dumps({"seq": "x", "text": "t"}), json.dumps({"seq": 5})])
        r = self.tick({})
        self.assertEqual(r["bad"], 3)
        self.assertEqual(self.pending(), ["ok"])

    def test_flattened_text_dedupe(self):
        self.write((1, "line one\nline two"))
        st = {}
        self.tick(st)
        self.assertEqual(self.pending(), ["line one line two"])
        self.deliver()
        self.tick(st)
        self.assertEqual(self.cursor(), "1")

    def test_control_characters_match_queue_text(self):
        self.write((1, "a\x1bb\x00c\x7f"), (2, "next"))
        st = {}
        self.tick(st)
        self.assertEqual(self.pending(), ["a b c"])
        self.tick(st)   # still waiting: the cursor stays and the next line is not added beside it
        self.assertIsNone(self.cursor())
        self.assertEqual(self.pending(), ["a b c"])

    def test_all_control_line_skipped_cursor_advanced(self):
        self.write((1, "\x1b\x00\x1b"), (2, "next"))
        r = self.tick({})
        self.assertEqual(r["skipped"], 1)
        self.assertEqual(self.cursor(), "1")
        self.assertEqual(self.pending(), ["next"])

    def test_no_file(self):
        self.assertEqual(self.tick({})["lines"], 0)

    def test_cursor_written_via_next_rename(self):
        self.write((1, "a"))
        st = {}
        self.tick(st)
        self.deliver()
        self.tick(st)
        self.assertFalse((self.dir / "p.lead.cursor.next").exists())


class RealStateTest(unittest.TestCase):
    def test_dry_run_over_real_engine_dir(self):
        d = Path(os.environ.get("HOME", "")) / ".local/state/agent-board/engine"
        cur = d / "agent-board.lead.cursor"
        before = cur.stat().st_mtime if cur.exists() else None
        with mock.patch.dict(os.environ):
            os.environ.pop("TC_ENGINE_DIR", None)
            r = engine_lines.tick("agent-board", lambda t: None, lambda: [], {}, dry_run=True)
        print(f"engine lead lines seen: {r['lines']}")
        after = cur.stat().st_mtime if cur.exists() else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
