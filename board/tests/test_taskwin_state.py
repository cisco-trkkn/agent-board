import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskwin_state as ts  # noqa: E402


def T(i, s):
    return {"id": str(i), "status": s}


class UpdateTest(unittest.TestCase):
    def test_first_sight_records_since_and_no_event(self):
        st = ts.update({}, "L", [T(1, "in_progress"), T(2, "completed")], 100.0)
        self.assertEqual(st["tasks"]["1"], {"status": "in_progress", "since": 100.0, "started": 100.0, "done": None})
        self.assertEqual(st["tasks"]["2"]["done"], 100.0)
        self.assertEqual(st["events"], [])

    def test_done_event_once_per_transition(self):
        st = ts.update({}, "L", [T(1, "in_progress"), T(2, "pending")], 100.0)
        st = ts.update(st, "L", [T(1, "completed"), T(2, "pending")], 160.0)
        self.assertEqual(st["events"], [{"kind": "done", "id": "1", "at": 160.0}])
        self.assertEqual(st["tasks"]["1"]["since"], 160.0)
        st = ts.update(st, "L", [T(1, "completed"), T(2, "pending")], 161.0)
        self.assertEqual([e for e in st["events"] if e["kind"] == "done"], [{"kind": "done", "id": "1", "at": 160.0}])

    def test_events_expire_after_ten_seconds(self):
        st = ts.update({}, "L", [T(1, "in_progress"), T(2, "pending")], 100.0)
        st = ts.update(st, "L", [T(1, "completed"), T(2, "pending")], 160.0)
        st = ts.update(st, "L", [T(1, "completed"), T(2, "pending")], 171.0)
        self.assertEqual(st["events"], [])

    def test_plan_done_once_and_not_on_first_poll(self):
        st = ts.update({}, "L", [T(1, "completed")], 100.0)
        self.assertEqual(st["events"], [])
        st = ts.update({}, "L", [T(1, "in_progress")], 100.0)
        st = ts.update(st, "L", [T(1, "completed")], 120.0)
        self.assertIn({"kind": "plan_done", "at": 120.0}, st["events"])
        st = ts.update(st, "L", [T(1, "completed")], 121.0)
        self.assertEqual(sum(e["kind"] == "plan_done" for e in st["events"]), 1)

    def test_restart_does_not_replay(self):
        with tempfile.TemporaryDirectory() as d:
            p = ts.path_for(d, "dev/x:1")
            self.assertEqual(p, Path(d) / "taskwin" / "dev_x_1.json")
            st = ts.update({}, "L", [T(1, "in_progress")], 100.0)
            st = ts.update(st, "L", [T(1, "completed")], 120.0)
            ts.save(p, st)
            st2 = ts.update(ts.load(p), "L", [T(1, "completed")], 200.0)
            self.assertEqual(st2["events"], [])
            self.assertEqual(st2["tasks"]["1"]["done"], 120.0)

    def test_new_lead_resets(self):
        st = ts.update({}, "L", [T(1, "in_progress")], 100.0)
        st = ts.update(st, "M", [T(1, "in_progress")], 200.0)
        self.assertEqual(st["lead"], "M")
        self.assertEqual(st["tasks"]["1"]["since"], 200.0)

    def test_load_missing_or_corrupt_and_save_unwritable(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ts.load(Path(d) / "nope.json"), {})
            (Path(d) / "bad.json").write_text("{nope")
            self.assertEqual(ts.load(Path(d) / "bad.json"), {})
            (Path(d) / "list.json").write_text(json.dumps([1]))
            self.assertEqual(ts.load(Path(d) / "list.json"), {})
            f = Path(d) / "file"
            f.write_text("x")
            ts.save(f / "sub" / "s.json", {"a": 1})   # parent is a file: must not raise


if __name__ == "__main__":
    unittest.main()
