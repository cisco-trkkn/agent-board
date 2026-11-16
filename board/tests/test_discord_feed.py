"""discord_feed core: spool writer, feed file, status card, audit. Every test runs on a TC_STATE temp dir."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_feed as df  # noqa: E402
import tc_env  # noqa: E402
from overview import RECORD_KEYS  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.dir = tc_env.discord_dir("proj")


class PathsTest(Base):
    def test_paths(self):
        self.assertEqual(tc_env.agent_base(), Path(self.tmp.name))
        self.assertEqual(self.dir, Path(self.tmp.name) / "discord" / "proj")
        self.assertEqual(tc_env.feed_path("proj"), Path(self.tmp.name) / "feed" / "proj.jsonl")

    def test_default_base(self):
        with mock.patch.dict(os.environ, {"HOME": "/h"}):
            os.environ.pop("TC_STATE")
            self.assertEqual(tc_env.agent_base(), Path("/h/.local/state/agent-board"))


def post(text="x", tier="progress", mention=False, **kw):
    return {"op": "post", "text": text, "tier": tier, "mention_user": mention, **kw}


class OutboxTest(Base):
    def names(self):
        return sorted(p.name for p in (self.dir / "outbox").glob("*.json"))

    def test_name_shape_and_order(self):
        for i in range(30):
            df.outbox_write(self.dir, post(str(i)))
        names = self.names()
        self.assertEqual(len(names), 30)
        for n in names:
            stem = n[:-5]
            ts, _, hid = stem.partition("-")
            self.assertEqual((len(ts), len(hid)), (13, 8))
            int(ts), int(hid, 16)
        texts = [json.loads((self.dir / "outbox" / n).read_text())["text"] for n in names]
        self.assertEqual(texts, [str(i) for i in range(30)])
        self.assertFalse(list((self.dir / "outbox").glob("*.tmp")))

    def test_order_when_clock_goes_back(self):
        with mock.patch("time.time", return_value=1700000000.0):
            for i in range(5):
                df.outbox_write(self.dir, post(str(i)))
        texts = [json.loads((self.dir / "outbox" / n).read_text())["text"] for n in self.names()]
        self.assertEqual(texts, [str(i) for i in range(5)])

    def test_validation(self):
        bad = [{"op": "nope"}, {"op": "card", "text": "t", "extra": 1}, {"op": "card"},
               post(tier="routine"), post(tier="loud"), {"op": "thread", "key": "k"},
               {"op": "archive", "key": "k", "x": 1}, "notadict",
               {"op": "post", "text": "x", "tier": "progress"}]
        for op in bad:
            with self.assertRaises(ValueError, msg=str(op)):
                df.outbox_write(self.dir, op)
        self.assertFalse((self.dir / "outbox").exists() and self.names())

    def test_valid_shapes(self):
        for op in (post(thread_key="t", link_thread_key="t", files=["/a"]), {"op": "card", "text": "c"},
                   {"op": "thread", "key": "k", "title": "T"}, {"op": "archive", "key": "k"}):
            df.outbox_write(self.dir, op)
        self.assertEqual(len(self.names()), 4)

    def test_cap_keeps_mentions(self):
        kinds = []
        for i in range(205):
            if i % 5 == 0:
                op = post(f"m{i}", tier="critical", mention=True)
            elif i % 3 == 0:
                op = {"op": "card", "text": f"c{i}"}
            else:
                op = post(f"p{i}")
            kinds.append(op)
            df.outbox_write(self.dir, op)
        names = self.names()
        self.assertEqual(len(names), 200)
        texts = [json.loads((self.dir / "outbox" / n).read_text()).get("text") for n in names]
        for i in range(0, 205, 5):
            self.assertIn(f"m{i}", texts)
        # cards went first: the oldest card is gone before any non-card, non-mention survivor was lost
        self.assertNotIn("c3", texts)
        self.assertIn("p1", texts)

    def test_cap_oldest_mention_survives_without_cards(self):
        df.outbox_write(self.dir, post("M", tier="decision", mention=True))
        for i in range(204):
            df.outbox_write(self.dir, post(f"p{i}"))
        texts = [json.loads((self.dir / "outbox" / n).read_text())["text"] for n in self.names()]
        self.assertEqual(len(texts), 200)
        self.assertIn("M", texts)
        self.assertNotIn("p0", texts)

    def test_cap_drops_non_mention_after_cards(self):
        for i in range(201):
            df.outbox_write(self.dir, post(f"p{i}"))
        texts = [json.loads((self.dir / "outbox" / n).read_text())["text"] for n in self.names()]
        self.assertEqual(len(texts), 200)
        self.assertNotIn("p0", texts)
        self.assertIn("p200", texts)


class FeedTest(Base):
    def test_append_and_read(self):
        df.append_event("proj", {"ts": 1.5, "project": "proj", "spec": "s", "kind": "task_done", "tier": "progress", "text": "t"})
        ev, off = df.read_events("proj", 0)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["refs"], {})
        self.assertEqual(set(ev[0]), {"ts", "project", "spec", "kind", "tier", "text", "refs"})
        self.assertEqual(df.read_events("proj", off), ([], off))

    def test_extra_key_dropped_missing_key_error(self):
        df.append_event("proj", {"ts": 1.0, "project": "p", "spec": "s", "kind": "k", "tier": "progress", "text": "t", "zzz": 1, "refs": {"task": "3"}})
        ev, _ = df.read_events("proj", 0)
        self.assertNotIn("zzz", ev[0])
        self.assertEqual(ev[0]["refs"], {"task": "3"})
        with self.assertRaises(ValueError):
            df.append_event("proj", {"ts": 1.0})

    def test_torn_last_line(self):
        f = tc_env.feed_path("proj")
        f.parent.mkdir(parents=True)
        whole = json.dumps({"ts": 1.0, "project": "p", "spec": "s", "kind": "k", "tier": "progress", "text": "a", "refs": {}})
        f.write_text(whole + "\n" + whole[:20])
        ev, off = df.read_events("proj", 0)
        self.assertEqual(len(ev), 1)
        self.assertEqual(off, len(whole) + 1)
        with open(f, "a") as fh:
            fh.write(whole[20:] + "\n")
        ev, off2 = df.read_events("proj", off)
        self.assertEqual(len(ev), 1)
        self.assertEqual(off2, f.stat().st_size)

    def test_missing_file(self):
        self.assertEqual(df.read_events("nope", 0), ([], 0))


def rec(plan=None, needs=None, agents=None):
    r = dict.fromkeys(RECORD_KEYS)
    r.update(project="proj", plan=plan or {"name": "", "active": False, "done": 0, "total": 0, "in_progress": []},
             needs_you=needs or [], agents=agents or [])
    return r


def task(i, subject, status="pending", owner="", tier=None):
    t = {"id": str(i), "subject": subject, "status": status, "owner": owner}
    if tier:
        t["description"] = f"x\n```json:metadata\n{{\"modelTier\": \"{tier}\"}}\n```"
    return t


NOW = 1700000000.0
HHMM = __import__("time").strftime("%H:%M", __import__("time").localtime(NOW))


class CardTest(unittest.TestCase):
    def test_idle(self):
        t = df.render_card(rec(), [], NOW)
        self.assertTrue(t.startswith("```\n") and t.endswith("\n```"))
        self.assertIn("queue: idle", t)
        self.assertIn("waiting on you: none", t)
        self.assertIn(f"updated {HHMM}", t)

    def test_paused(self):
        lead = [task(1, "Plan & run: docs/superpowers/specs/a.md")]
        self.assertIn("queue: paused", df.render_card(rec(), lead, NOW))

    def test_running_k_of_n(self):
        lead = [task(1, "Plan & run: docs/superpowers/specs/a.md", "completed"),
                task(2, "Plan & run: docs/superpowers/specs/2026-11-16-b.md", "in_progress"),
                task(3, "Plan & run: docs/superpowers/specs/c.md"),
                task(4, "Task 1: feed core", "completed", tier="standard"),
                task(5, "Task 2: node bridge", "in_progress", "bv-node", "frontier"),
                task(6, "Task 3: docs")]
        t = df.render_card(rec(), lead, NOW)
        self.assertIn("queue: running 2026-11-16-b (2/3)", t)
        self.assertIn("✓ Task 1: feed core", t)
        self.assertRegex(t, r"▶ Task 2: node bridge .*bv-node.*frontier")
        self.assertIn("· Task 3: docs", t)
        self.assertNotIn("Plan & run: docs", t.split("\n", 2)[2])

    def test_agents_and_needs(self):
        ag = [{"window": "bv-node", "pane": "%1", "state": "working"}, {"window": "bv-py", "pane": "%2", "state": "ready"}]
        ne = [{"window": "lead", "pane": "%0", "kind": "permission", "reason": "r"}]
        t = df.render_card(rec(needs=ne, agents=ag), [], NOW)
        self.assertIn("bv-node busy", t)
        self.assertIn("bv-py idle", t)
        self.assertIn("waiting on you:", t)
        self.assertIn("lead", t.split("waiting on you:")[1])
        self.assertNotIn("none", t.split("waiting on you:")[1])

    def test_cap(self):
        lead = [task(1, "Plan & run: s.md", "in_progress")] + [task(i + 10, f"Task {i}: " + "w" * 30, "pending") for i in range(60)]
        t = df.render_card(rec(), lead, NOW)
        self.assertLessEqual(len(t), 1900)
        self.assertTrue(t.endswith("\n```"))
        self.assertTrue([l for l in t.split("\n") if __import__("re").fullmatch(r"… \d+ more", l)])
        self.assertIn(f"updated {HHMM}", t)

    def test_small_not_cut(self):
        self.assertNotIn("more", df.render_card(rec(), [], NOW))


class DueTest(unittest.TestCase):
    def test_due(self):
        st = {"card_text": "a", "card_ts": 1000.0}
        self.assertIsNone(df.card_op_due(st, "a", 1300.0))
        self.assertIsNone(df.card_op_due(st, "b", 1029.0))
        self.assertEqual(df.card_op_due(st, "b", 1030.0), {"op": "card", "text": "b"})
        self.assertEqual(df.card_op_due({}, "b", NOW), {"op": "card", "text": "b"})


class AuditTest(Base):
    def test_audit(self):
        df.audit_append(self.dir, "u1", "pause", "x" * 200, "ok")
        line = json.loads((self.dir / "audit.jsonl").read_text().splitlines()[0])
        self.assertEqual(set(line), {"ts", "user", "action", "target", "result"})
        self.assertEqual(len(line["target"]), 80)
        self.assertEqual((line["user"], line["action"], line["result"]), ("u1", "pause", "ok"))
        df.audit_append(self.dir, "u1", "a", "t", "r")
        self.assertEqual(len((self.dir / "audit.jsonl").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
