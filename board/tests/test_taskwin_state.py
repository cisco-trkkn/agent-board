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

    def test_blank_lead_tick_keeps_state(self):
        st = ts.update({}, "a", [T(1, "in_progress")], 100.0)
        st = ts.update(st, "", [], 150.0)
        self.assertEqual(st["lead"], "a")
        st = ts.update(st, "a", [T(1, "in_progress")], 200.0)
        self.assertEqual(st["tasks"]["1"]["since"], 100.0)
        self.assertEqual(st["tasks"]["1"]["started"], 100.0)
        st = ts.update(st, "b", [T(1, "in_progress")], 300.0)
        self.assertEqual(st["lead"], "b")
        self.assertEqual(st["tasks"]["1"]["since"], 300.0)

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


def Q(i, s, subject="Plan & run: docs/superpowers/specs/a-design.md", outcome="", plan=""):
    return {"id": str(i), "status": s, "subject": subject, "outcome": outcome, "planPath": plan, "owner": "", "tier": ""}


def P(i, s, subject="Task 1: x", owner="ann", tier="mechanical"):
    return {"id": str(i), "status": s, "subject": subject, "owner": owner, "tier": tier}


class UiKeptTest(unittest.TestCase):
    def test_ui_kept_across_lead_change(self):
        st = ts.update({}, "L1", [T(1, "pending")], 100.0)
        st["ui"] = {"view": "history", "filter": "active"}
        st = ts.update(st, "L2", [T(1, "pending")], 101.0)
        self.assertEqual(st["lead"], "L2")
        self.assertEqual(st["ui"], {"view": "history", "filter": "active"})
        self.assertEqual(list(st["tasks"]), ["1"])     # the rest was reset: task 1 seen fresh at 101
        self.assertEqual(st["tasks"]["1"]["since"], 101.0)


class JournalTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.state = Path(td.name)
        self.j = ts.journal_path(self.state, "grp")

    def lines(self):
        return [json.loads(l) for l in self.j.read_text().splitlines()] if self.j.exists() else []

    def test_journal_path_uses_project_key(self):
        self.assertEqual(ts.journal_path("/s", "agent board"), Path("/s/taskwin/agent_board.history.jsonl"))

    def test_task_done_on_transition_only(self):
        st = ts.update({}, "L", [P(1, "in_progress"), P(2, "completed")], 100.0, journal=self.j, plan="2026-11-21-x")
        self.assertEqual(self.lines(), [])              # 2 was already completed at first sight: no back-fill
        ts.update(st, "L", [P(1, "completed"), P(2, "completed")], 160.0, journal=self.j, plan="2026-11-21-x")
        self.assertEqual(self.lines(), [{"kind": "task_done", "at": 160.0, "plan": "2026-11-21-x", "id": "1",
                                         "subject": "Task 1: x", "owner": "ann", "tier": "mechanical"}])

    def test_queue_outcome_line(self):
        st = ts.update({}, "L", [Q(1, "in_progress")], 100.0, journal=self.j)
        ts.update(st, "L", [Q(1, "completed", subject="Plan & run: docs/superpowers/specs/a-design.md#part-1 (x)",
                              outcome="merged abc1234", plan="docs/superpowers/plans/2026-11-21-a.md")],
                  160.0, journal=self.j)
        self.assertEqual(self.lines(), [{"kind": "queue_outcome", "at": 160.0,
                                         "spec": "docs/superpowers/specs/a-design.md#part-1",
                                         "outcome": "merged abc1234", "plan": "2026-11-21-a"}])

    def test_dedupe_against_recent_lines(self):
        # a relay re-reads the same list under a new lead: the same completion is journaled once
        for lead in ("L1", "L2"):
            st = ts.update({}, lead, [P(1, "in_progress")], 100.0, journal=self.j, plan="p")
            ts.update(st, lead, [P(1, "completed")], 160.0, journal=self.j, plan="p")
        self.assertEqual(len(self.lines()), 1)

    def test_cap_keeps_newest_lines(self):
        self.j.parent.mkdir(parents=True)
        self.j.write_text("".join(json.dumps({"kind": "task_done", "plan": "old", "id": str(i), "subject": "s"}) + "\n"
                                  for i in range(ts.JOURNAL_CAP)))
        ts.append_journal(self.j, [{"kind": "task_done", "plan": "new", "id": "1", "subject": "s"}])
        got = self.lines()
        self.assertEqual(len(got), ts.JOURNAL_CAP)
        self.assertEqual((got[0]["id"], got[-1]["plan"]), ("1", "new"))   # line 0 of the old file dropped
        self.assertFalse(self.j.with_name(self.j.name + ".tmp").exists())

    def test_io_error_is_ignored(self):
        bad = self.state / "file"
        bad.write_text("x")
        ts.append_journal(bad / "sub" / "j.jsonl", [{"kind": "task_done", "id": "1"}])   # parent is a file: no raise

    def test_malformed_lines_skipped(self):
        self.j.parent.mkdir(parents=True)
        self.j.write_text("{not json\n[1]\n")
        ts.append_journal(self.j, [{"kind": "task_done", "plan": "p", "id": "1", "subject": "s"}])
        self.assertEqual(len(self.j.read_text().splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
