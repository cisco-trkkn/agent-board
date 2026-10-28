import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import planview  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "planview"
SID1 = "11111111-1111-1111-1111-111111111111"
SID2 = "22222222-2222-2222-2222-222222222222"


def fake_tmux(claude_pane="@80.%82", windows=(("claude", "%82"), ("✦ parse", "%90")), status=None):
    status = status or {}

    def run(*args, check=False):
        if args[0] == "display" and "#{window_id}.#{pane_id}" in args[-1]:
            return claude_pane + "\n"
        if args[0] == "list-windows":
            return "".join(f"{n}\t{p}\n" for n, p in windows)
        raise AssertionError(args)
    run.status = status
    return run


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        self.home = self.root / "home"
        self.repo = self.root / "repo"
        self.state = self.root / "state"
        shutil.copytree(FIX / "sessions", self.home / "sessions")
        shutil.copytree(FIX / "tasks", self.home / "tasks")
        shutil.copytree(FIX / "repo", self.repo)
        p = mock.patch("planview.pane_state", return_value="working")  # no capture-pane is faked
        p.start()
        self.addCleanup(p.stop)
        self.state.mkdir()
        shutil.copy(FIX / "artifacts-proj.jsonl", self.state / "artifacts-proj.jsonl")

    def view(self, tmux=None, session="proj"):
        return planview.view(session, self.repo, self.home, self.state, tmux or fake_tmux())

    def put_task(self, sid8, n, **kw):
        d = self.home / "tasks" / f"session-{sid8}"
        t = {"id": str(n), "subject": f"T{n}", "status": "pending", "owner": "", "blockedBy": [], "blocks": []}
        t.update(kw)
        (d / f"{n}.json").write_text(json.dumps(t))

    def clear_tasks(self, sid8):
        for f in (self.home / "tasks" / f"session-{sid8}").glob("*.json"):
            f.unlink()

    def write_manifest(self, lines):
        (self.state / "artifacts-proj.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines))


class TestPlanview(Base):
    def test_lead_matched_by_claude_pane(self):
        v = self.view()
        self.assertEqual([t["subject"] for t in v["tasks"]][0], "Task 1: x")
        self.assertEqual(len(v["tasks"]), 3)
        self.assertTrue(v["active"])
        v2 = self.view(fake_tmux(claude_pane="@81.%83"))
        self.assertEqual([t["subject"] for t in v2["tasks"]], ["decoy"])

    def test_tasks_sorted_numerically(self):
        self.clear_tasks("11111111")
        for n in (2, 10, 1):
            self.put_task("11111111", n)
        self.assertEqual([t["id"] for t in self.view()["tasks"]], ["1", "2", "10"])

    def test_pending_with_open_blocker_is_blocked(self):
        self.clear_tasks("11111111")
        self.put_task("11111111", 1, status="in_progress")
        self.put_task("11111111", 2, blockedBy=["1"])
        self.assertEqual([t["status"] for t in self.view()["tasks"]], ["in_progress", "blocked"])

    def test_pending_with_done_blocker_is_pending(self):
        self.clear_tasks("11111111")
        self.put_task("11111111", 1, status="completed")
        self.put_task("11111111", 2, blockedBy=["1"])
        self.assertEqual([t["status"] for t in self.view()["tasks"]], ["completed", "pending"])

    def test_owner_state_mapping(self):
        self.clear_tasks("11111111")
        wins = (("claude", "%82"), ("✦ a", "%90"), ("✦ b", "%91"), ("✦ c", "%92"))
        for n, o in enumerate("abcd", 1):
            self.put_task("11111111", n, owner=o)
        side = {"%90": "working", "%91": "waiting", "%92": "ready"}
        with mock.patch("planview.pane_state", side_effect=lambda t, p: side[p]):
            v = self.view(fake_tmux(windows=wins))
        self.assertEqual([t["state"] for t in v["tasks"]], ["working", "waiting", "ready", "gone"])

    def test_unowned_task_has_empty_state(self):
        self.clear_tasks("11111111")
        self.put_task("11111111", 1)
        self.assertEqual(self.view()["tasks"][0]["state"], "")

    def test_name_from_newest_plan_line_of_this_lead(self):
        base = {"kind": "plan", "session_id": SID1}
        self.write_manifest([
            dict(base, ts=1, path="/p/a-old.md"),
            dict(base, ts=2, path="/p/b-new.md"),
            dict(base, ts=3, path="/p/c.md", session_id=SID2),
            {"ts": 4, "path": "/p/mark.md", "session_id": SID1},
        ])
        self.assertEqual(self.view()["name"], "b-new")

    def test_empty_live_list_falls_back_to_tasks_json(self):
        self.clear_tasks("11111111")
        v = self.view()
        self.assertEqual(v["name"], "2026-01-01-demo")
        self.assertFalse(v["active"])
        self.assertEqual([t["id"] for t in v["tasks"]], ["1", "2", "3"])
        self.assertEqual(v["tasks"][1]["status"], "completed")

    def test_no_plan_line_falls_back_to_newest_repo_tasks_json(self):
        self.clear_tasks("11111111")
        self.write_manifest([])
        d = self.repo / "docs/superpowers/plans"
        (d / "2026-02-02-newer.md.tasks.json").write_text(json.dumps({"tasks": [{"id": 7, "subject": "n", "status": "pending"}]}))
        import os
        os.utime(d / "2026-01-01-demo.md.tasks.json", (1, 1))
        v = self.view()
        self.assertEqual((v["name"], v["active"], [t["id"] for t in v["tasks"]]), ("2026-02-02-newer", False, ["7"]))

    def test_nothing_gives_empty_view(self):
        empty = {"name": "", "active": False, "tasks": []}
        shutil.rmtree(self.repo)
        shutil.rmtree(self.home)
        self.assertEqual(self.view(), empty)

    def test_missing_home_and_bad_json_do_not_raise(self):
        for f in (self.home / "tasks" / "session-11111111").glob("*.json"):
            f.write_text("{bad")
        (self.home / "sessions" / "1002.json").write_text("not json")
        (self.state / "artifacts-proj.jsonl").write_text("{bad\n")
        (self.repo / "docs/superpowers/plans/2026-01-01-demo.md.tasks.json").write_text("[")
        self.assertEqual(self.view()["tasks"], [])

    def test_tmux_raising_gives_empty_view(self):
        def boom(*a, **k):
            raise RuntimeError("no tmux")
        self.assertEqual(self.view(boom), {"name": "", "active": False, "tasks": []})
        self.assertEqual(self.view(lambda *a, **k: ""), {"name": "", "active": False, "tasks": []})


class TestPaneState(unittest.TestCase):
    def test_pane_state_maps_pane_status(self):
        for ret, want in ((("claude", "working"), "working"), (("claude", "waiting"), "waiting"),
                          (("claude", "ready"), "ready"), (("shell", "ready"), "ready")):
            with mock.patch("planview.paneclass.pane_status", return_value=ret):
                self.assertEqual(planview.pane_state(None, "%1"), want)

    def test_pane_state_error_is_ready(self):
        with mock.patch("planview.paneclass.pane_status", side_effect=RuntimeError):
            self.assertEqual(planview.pane_state(None, "%1"), "ready")


if __name__ == "__main__":
    unittest.main()
