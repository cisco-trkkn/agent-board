"""derive posts nothing for a Plan & run spec the engine runs (feed line with src engine)."""
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

TASKS = [
    {"id": "1", "subject": "Plan & run: docs/superpowers/specs/eng-spec.md#part-2", "status": "in_progress"},
    {"id": "2", "subject": "Plan & run: docs/superpowers/specs/lead-spec.md", "status": "completed", "metadata": {"outcome": "completed"}},
    {"id": "3", "subject": "Task A", "status": "completed"},
]


class DeriveEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def run_derive(self, st):
        base = {"primed": True, "primed_lists": ["l"]}
        base.update(st)
        return df.derive("p", self.tmp.name, TASKS, base, 100.0, "l")

    def test_engine_spec_silent_lead_spec_emits(self):
        ev, _ = self.run_derive({"engine_specs": ["eng-spec"]})
        specs = {e["spec"] for e in ev}
        self.assertNotIn("eng-spec#part-2", specs)
        self.assertIn("lead-spec", specs)   # spec_outcome of the lead-run spec

    def test_without_marking_emits_as_before(self):
        ev, _ = self.run_derive({})
        self.assertIn("eng-spec#part-2", {e["spec"] for e in ev})

    def test_note_engine_specs_from_feed_lines(self):
        st = df.note_engine_specs({}, [{"src": "engine", "spec": "eng-spec#part-2"}, {"spec": "other"}, {"src": "engine", "spec": ""}])
        self.assertEqual(st["engine_specs"], ["eng-spec"])
        ev, _ = self.run_derive(st)
        self.assertNotIn("eng-spec#part-2", {e["spec"] for e in ev})

    def test_newest_200_kept(self):
        st = df.note_engine_specs({}, [{"src": "engine", "spec": f"s{i}"} for i in range(250)])
        self.assertEqual(len(st["engine_specs"]), 200)
        self.assertEqual(st["engine_specs"][-1], "s249")

    def test_tick_marks_before_derive_same_pass(self):
        df.append_event("p", {"ts": 1.0, "project": "p", "spec": "eng-spec#part-2", "kind": "x", "tier": "routine", "text": "t"})
        fp = Path(self.tmp.name) / "feed" / "p.jsonl"
        with open(fp, "a") as f:
            f.write(json.dumps({"ts": 2.0, "project": "p", "spec": "eng-spec#part-2", "kind": "spec_started", "tier": "progress",
                                "text": "t", "refs": {}, "src": "engine"}) + "\n")
        sd = Path(self.tmp.name) / "discord" / "p"
        sd.mkdir(parents=True)
        (sd / "feed-state.json").write_text(json.dumps({"feed_offset": 0, "primed": True}))   # not a first tick: the feed is read from 0
        df.tick("p", {"project": "p"}, self.tmp.name, 100.0, lead_tasks=TASKS, list_id="l")
        st = json.loads((Path(self.tmp.name) / "discord" / "p" / "feed-state.json").read_text())
        self.assertEqual(st["engine_specs"], ["eng-spec"])
        written = [json.loads(l) for l in fp.read_text().splitlines()]
        derived = [w for w in written if w.get("spec") == "eng-spec#part-2" and "src" not in w and w["kind"] != "x"]
        self.assertEqual(derived, [])   # derive appended nothing for the engine-run spec in the pass that first saw its line


class RealFeedTest(unittest.TestCase):
    def test_real_feed_parses(self):
        p = Path(os.environ.get("HOME", "")) / ".local/state/agent-board/feed/agent-board.jsonl"
        if not p.exists():
            self.skipTest("no real feed")
        lines = p.read_text(encoding="utf-8").splitlines()[-200:]
        objs = [json.loads(l) for l in lines]
        withsrc = [o for o in objs if "src" in o]
        print(f"real feed: {len(objs)} lines, {len(withsrc)} with src")
        for o in withsrc:
            self.assertIn("kind", o)
            self.assertIn("spec", o)


if __name__ == "__main__":
    unittest.main()
