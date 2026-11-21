"""analytics_post: escaping, week id, thread links, the two ops, the state file. TC_STATE is a temp dir: nothing real is written."""
import copy, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import analytics_post as ap, discord_feed, tc_env  # noqa: E402

ZW = "​"


def stats_fixture(n_flags=0):
    t = lambda p, c: {"previous": p, "current": c, "change": None if p is None else c - p}  # noqa: E731
    over = [{"project": "p1", "spec": f"docs/specs/2026-11-12-x{i}.md", "task_id": i, "subject": f"Task {i}: a long subject for the flag",
             "model_used": "claude-opus-5"} for i in range(n_flags)]
    return {"window": {"since": "2026-11-09T12:00:00Z", "until": "2026-11-16T12:00:00Z", "previous_since": "2026-11-02T12:00:00Z"},
            "projects": ["p1"], "trends": {"specs_merged": t(1, 2), "specs_mr": t(0, 1)},
            "flags": {"overpowered": over, "underpowered": [],
                      "costly_steps": [{"project": "p1", "spec": "2026-11-12-x#part-2", "task_id": i, "subject": f"Task {i}: s", "usd": 5.0 - i}
                                       for i in range(5)],
                      "handoffs": [], "forecast": {"median_precision": 0.9, "median_recall": 0.9, "below_half": []}},
            "coverage": {"with_cost": 3, "tasks": 4}}


def item(i, title=None):
    return {"title": title or f"Item {i}", "change": f"change {i}", "expected_effect": f"effect {i}", "risk": f"risk {i}",
            "evidence": [{"key": "trends.specs_merged.current", "value": 2}]}


def rec_fixture(items=None):
    items = items if items is not None else [item(1), item(2), item(3)]
    return {"items": items, "dropped": [], "passed": len(items), "asked": 3, "usage": {"cost_usd": 0.1, "tokens": None}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def feed(self, project="p1", spec="2026-11-12-x#part-2"):
        f = tc_env.feed_path(project)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("garbage\n" + json.dumps({"ts": 1, "project": project, "spec": spec, "kind": "spec_started", "tier": "progress",
                                               "text": "", "refs": {"thread_key": "session-ab:9"}}) + "\n")
        d = tc_env.discord_dir(project)
        d.mkdir(parents=True, exist_ok=True)
        (d / "bridge-state.json").write_text(json.dumps({"guild_id": "G", "threads": {"session-ab:9": "T"}}))


class Pure(Base):
    def test_escape(self):
        self.assertEqual(ap.escape("@everyone *x*"), f"@{ZW}everyone \\*x\\*")
        self.assertEqual(ap.escape("a`b\\c_d~e|f>g#h"), "a\\`b\\\\c\\_d\\~e\\|f\\>g\\#h")

    def test_week_id(self):
        self.assertRegex(ap.week_id("2026-11-16T12:00:00Z"), r"^\d{4}-W\d{2}$")
        self.assertEqual(ap.week_id("2026-11-16T12:00:00Z"), "2026-W47")
        self.assertEqual(ap.week_id("2026-01-01T12:00:00Z"), "2026-W01")

    def test_validate_buttons(self):
        ok = {"label": "x", "style": 1, "custom_id": "y"}
        ap.validate_buttons([ok] * 5)
        for bad in ([ok] * 6, [dict(ok, label="x" * 81)], [dict(ok, custom_id="y" * 101)]):
            with self.assertRaises(ValueError):
                ap.validate_buttons(bad)


class Links(Base):
    def test_full_fixture(self):
        self.feed()
        self.assertEqual(ap.thread_link("p1", "docs/2026-11-12-x#part-2.md"), "<https://discord.com/channels/G/T>")

    def test_no_feed(self):
        self.assertIsNone(ap.thread_link("p1", "2026-11-12-x"))

    def test_part_suffix_matches_either_side(self):
        self.feed()
        self.assertEqual(ap.thread_link("p1", "2026-11-12-x.md"), "<https://discord.com/channels/G/T>")
        self.assertIsNone(ap.thread_link("p1", "2026-11-12-y.md"))


class Ops(Base):
    def build(self, stats=None, rec=None, multi=False):
        return ap.build_ops(stats or stats_fixture(), rec or rec_fixture(), "2026-W47", Path("/x/stats.json"), multi)

    def test_two_ops_pass_check_and_shape(self):
        a, b = self.build()
        for op in (a, b):
            discord_feed._check(op)
            self.assertLessEqual(len(op["text"]), 1900)
        self.assertEqual((a["key"], b["key"]), ("analytics-2026-W47-a", "analytics-2026-W47-b"))
        self.assertEqual(b["files"], ["/x/stats.json"])
        self.assertNotIn("stats:", b["text"])
        self.assertNotIn("/x/stats.json", a["text"] + b["text"])
        self.assertEqual([x["label"] for x in b["buttons"]], ["File as idea 1", "File as idea 2", "File as idea 3"])
        self.assertEqual(b["buttons"][1], {"label": "File as idea 2", "style": 1, "custom_id": "ab:analytics:idea:2026-W47:2"})
        self.assertIn("(3 of 3 passed the evidence check)", b["text"])
        self.assertIn("coverage: 3/4 tasks with cost data", b["text"])
        self.assertNotIn("delete_files", b)

    def test_costly_top3_and_project_prefix(self):
        a, _ = self.build()
        self.assertEqual(a["text"].count("costly_steps"), 3)
        self.assertNotIn("[p1]", a["text"])
        a, _ = self.build(multi=True)
        self.assertIn("[p1]", a["text"])

    def test_link_on_flag_line(self):
        self.feed()
        a, _ = self.build()
        lines = [l for l in a["text"].splitlines() if "costly_steps" in l]
        self.assertTrue(all(l.endswith(" <https://discord.com/channels/G/T>") for l in lines), lines)

    def test_overflow(self):
        titles = [item(i, "T" * 300) for i in (1, 2, 3)]
        a, b = self.build(stats_fixture(30), rec_fixture(titles))
        self.assertLessEqual(len(a["text"]), 1900)
        self.assertLessEqual(len(b["text"]), 1900)
        m = [l for l in a["text"].splitlines() if l.startswith("… and ")]
        self.assertEqual(len(m), 1)
        self.assertTrue(m[0].endswith(" more flags in stats.json"))
        self.assertEqual(len(b["buttons"]), 3)

    def test_unavailable(self):
        _, b = self.build(rec={"items": [], "unavailable": "claude exited 1", "usage": {}})
        self.assertNotIn("buttons", b)
        self.assertIn("recommendations unavailable: claude exited 1", b["text"])
        discord_feed._check(b)

    def test_model_strings_escaped(self):
        _, b = self.build(rec=rec_fixture([item(1, "@here **x**")]))
        self.assertIn(f"@{ZW}here \\*\\*x\\*\\*", b["text"])
        st = stats_fixture(1)
        st["flags"]["overpowered"][0]["subject"] = "@here *s*"
        a, _ = self.build(st)
        self.assertIn(f"@{ZW}here \\*s\\*", a["text"])

    def test_too_many_items_raises(self):
        with self.assertRaises(ValueError):
            self.build(rec=rec_fixture([item(i) for i in range(1, 7)]))


class Publish(Base):
    def test_writes_state_then_ops_and_keeps_done(self):
        d = Path(self.tmp.name) / "dest"
        st = stats_fixture()
        self.assertEqual(ap.publish(d, "proj", st, rec_fixture(), Path("/x/stats.json"), False), 2)
        self.assertEqual(len(list((d / "outbox").glob("*.json"))), 2)
        sp = d / "analytics" / "post-2026-W47.json"
        doc = json.loads(sp.read_text())
        self.assertEqual(doc["project"], "proj")
        self.assertEqual([i["n"] for i in doc["items"]], [1, 2, 3])
        self.assertEqual(doc["items"][0]["done"], False)
        doc["items"][0]["done"] = "2026-11-17T10:00:00Z"
        sp.write_text(json.dumps(doc))
        ap.publish(d, "proj", st, rec_fixture([item(1), item(2, "New"), item(3)]), Path("/x/stats.json"), False)
        items = json.loads(sp.read_text())["items"]
        self.assertEqual(items[0]["done"], "2026-11-17T10:00:00Z")
        self.assertEqual(items[1]["done"], False)


if __name__ == "__main__":
    unittest.main()
