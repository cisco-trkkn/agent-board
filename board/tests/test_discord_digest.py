"""discord_digest: due(), build(), tick(). Scratch TC_STATE and TZ; nothing touches the real state dir."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_digest as dg  # noqa: E402
import discord_feed as df  # noqa: E402
import discord_ops as ops  # noqa: E402
import tc_env  # noqa: E402


def ts(day, hm):
    return time.mktime(time.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M"))


def ev(t, kind, text, spec="", tier="progress"):
    return {"ts": t, "project": "p", "spec": spec, "kind": kind, "tier": tier, "text": text, "refs": {}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # cleanups run last-in first-out: tzset must run after the env patch is undone
        self.addCleanup(time.tzset)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name, "TZ": "Europe/Madrid"})
        p.start()
        self.addCleanup(p.stop)
        time.tzset()
        dg._warned = False
        self.ops = tc_env.ops_dir()
        self.ops.mkdir(parents=True)

    def configure(self):
        (self.ops / "bridge.json").write_text(json.dumps({"command_center": "C1", "approvals": "A1", "user": "U1"}))

    def feed(self, project, events):
        p = tc_env.feed_path(project)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(e) + "\n" for e in events))

    def outbox(self):
        return [json.loads(f.read_text()) for f in sorted((self.ops / "outbox").glob("*.json"))] if (self.ops / "outbox").exists() else []


class TestDue(Base):
    def test_before_and_after_at(self):
        self.assertFalse(dg.due({}, ts("2026-11-18", "07:59"), "08:00"))
        self.assertTrue(dg.due({}, ts("2026-11-18", "08:00"), "08:00"))

    def test_once_per_day(self):
        st = {"last_day": "2026-11-18", "last_ts": ts("2026-11-18", "08:00")}
        self.assertFalse(dg.due(st, ts("2026-11-18", "20:00"), "08:00"))
        self.assertTrue(dg.due(st, ts("2026-11-19", "08:01"), "08:00"))

    def test_off(self):
        self.assertFalse(dg.due({}, ts("2026-11-18", "12:00"), "off"))

    def test_bad_value_defaults_and_warns_once(self):
        with mock.patch("sys.stderr") as err:
            self.assertFalse(dg.due({}, ts("2026-11-18", "07:00"), "banana"))
            self.assertTrue(dg.due({}, ts("2026-11-18", "08:00"), "25:99"))
            self.assertTrue(dg.due({}, ts("2026-11-18", "09:00"), "banana"))
        self.assertEqual(sum(1 for c in err.write.call_args_list if "TC_DISCORD_DIGEST_AT" in str(c)), 1)


class TestBuild(Base):
    def test_header_and_lines(self):
        now = ts("2026-11-18", "08:00")
        since = ts("2026-11-17", "08:00")
        feeds = {"a": [ev(since + 10, "spec_outcome", "merged abc", "s1"), ev(since + 20, "spec_outcome", "failed: x", "s2"),
                       ev(since + 30, "spec_started", "spec started: s3", "s3"), ev(since + 40, "test_failed", "t", "s3", "critical")],
                 "b": [ev(since - 5, "spec_outcome", "merged old", "old")], "c": []}
        approvals = [{"project": "a", "title": "merge s1", "link": "https://d/1"}]
        recs = [{"project": "a", "spend_today": 1.5}, {"project": "b", "spend_today": 0.5}, {"project": "c"}]
        out = dg.build(["a", "b", "c"], feeds, approvals, recs, {"five_hour": 12.4, "seven_day": 40}, since, now)
        lines = out.split("\n")
        self.assertEqual(lines[0], "digest 2026-11-18 · 5h 12% · week 40% · spend $2.00")
        self.assertEqual(lines[1], "a: merged 1 (s1) · failed 1 (s2) · running s3 · decisions 1 · test runs failed 1")
        self.assertIn("merge s1 https://d/1", lines[2])
        self.assertIn("b: quiet", out)
        self.assertIn("c: quiet", out)

    def test_specs_cut_to_three(self):
        since = 1000.0
        feeds = {"a": [ev(since + i, "spec_outcome", "merged x", f"s{i}") for i in range(5)]}
        out = dg.build(["a"], feeds, [], [], None, since, since + 100)
        self.assertIn("merged 5 (s0, s1, s2, …)", out)

    def test_length_cap(self):
        since = 1000.0
        projects = [f"proj{i:03d}" + "x" * 40 for i in range(80)]
        feeds = {p: [ev(since + 1, "test_failed", "t")] for p in projects}
        out = dg.build(projects, feeds, [], [], None, since, since + 100)
        self.assertLessEqual(len(out), 1900)
        self.assertRegex(out.split("\n")[-1], r"^… \d+ more projects$")


class TestTick(Base):
    def test_unconfigured_nothing(self):
        dg.tick([{"project": "a"}], None, ts("2026-11-18", "09:00"))
        self.assertEqual(self.outbox(), [])
        self.assertFalse((self.ops / "digest-state.json").exists())

    def test_one_post_per_day(self):
        self.configure()
        recs = [{"project": "a", "spend_today": 1.0}]
        dg.tick(recs, None, ts("2026-11-18", "08:05"))
        dg.tick(recs, None, ts("2026-11-18", "08:15"))
        posts = self.outbox()
        self.assertEqual(len(posts), 1)
        self.assertEqual((posts[0]["op"], posts[0]["tier"], posts[0]["mention_user"]), ("post", "progress", False))
        self.assertTrue(posts[0]["text"].startswith("digest 2026-11-18"))
        st = json.loads((self.ops / "digest-state.json").read_text())
        self.assertEqual(st["last_day"], "2026-11-18")
        dg.tick(recs, None, ts("2026-11-19", "08:05"))
        self.assertEqual(len(self.outbox()), 2)

    def test_first_run_since_is_24h(self):
        self.configure()
        now = ts("2026-11-18", "08:00")
        self.feed("a", [ev(now - 86400 - 60, "spec_outcome", "merged x", "old"), ev(now - 3600, "spec_outcome", "merged y", "new")])
        dg.tick([{"project": "a"}], None, now)
        text = self.outbox()[0]["text"]
        self.assertIn("merged 1 (new)", text)

    def test_feed_spanning_midnight(self):
        self.configure()
        since = ts("2026-11-17", "08:00")
        (self.ops / "digest-state.json").write_text(json.dumps({"last_ts": since, "last_day": "2026-11-17"}))
        self.feed("a", [ev(ts("2026-11-17", "23:50"), "spec_outcome", "merged y", "yday"),
                        ev(ts("2026-11-18", "00:10"), "spec_outcome", "merged t", "today")])
        dg.tick([{"project": "a"}], None, ts("2026-11-18", "08:00"))
        self.assertIn("merged 2 (yday, today)", self.outbox()[0]["text"])

    def test_critical_not_held(self):
        self.configure()
        (self.ops / "digest-state.json").write_text(json.dumps({"last_ts": 1.0, "last_day": "2026-11-18"}))
        now = ts("2026-11-18", "07:00")
        r = [{"project": "a", "needs_you": [], "alerts": [], "plan": {}}]
        ops.tick(r, {}, None, now, lambda *a: None)   # first sight: offset at end
        self.feed("a", [ev(now, "test_failed", "boom", "s", "critical")])
        ops.tick(r, {}, None, now + 1, lambda *a: None)
        self.assertTrue(any(o["op"] == "post" and o["tier"] == "critical" for o in self.outbox()))

    def test_open_approvals_from_ops_state(self):
        self.configure()
        (self.ops / "ops-state.json").write_text(json.dumps({"approvals": {"k": {"project": "a", "kind": "merge", "title": "merge s9", "link": "https://d/9"}}}))
        dg.tick([{"project": "a"}], None, ts("2026-11-18", "09:00"))
        text = self.outbox()[0]["text"]
        self.assertIn("decisions 1", text)
        self.assertIn("merge s9 https://d/9", text)


if __name__ == "__main__":
    unittest.main()
