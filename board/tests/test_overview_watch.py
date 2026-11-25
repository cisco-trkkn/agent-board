"""overview: the night watch fields (queue, owned, awake, pace). Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §2, §6."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import overview  # noqa: E402
import planview  # noqa: E402

NOW = 1_800_000_000.0


def task(i, subject, status, owner="", queue=False):
    return {"id": str(i), "subject": subject, "status": status, "owner": owner, "queue": queue}


def view(*tasks, active=True):
    return {"name": "p", "active": active, "tasks": list(tasks)}


def panes(*rows):
    """A tmux runner answering list-panes -s with rows (window, pane, dead, index); anything else is an error."""
    def run(*args, check=False):
        if args[0] == "list-panes" and "-s" in args:
            return "".join(f"{w}\t{p}\t{d}\t{i}\n" for w, p, d, i in rows)
        raise AssertionError(args)
    return run


class QueueModeTest(unittest.TestCase):
    def test_open_plan_and_run_with_queue_metadata_is_queue_mode(self):
        for st in ("pending", "blocked", "in_progress"):
            self.assertTrue(overview.queue_mode(view(task(1, "Plan & run: docs/s.md", st, queue=True))), st)

    def test_without_queue_metadata_completed_or_idle_view_it_is_off(self):
        # mutation: drop the `t.get("queue")` check -> the first assertion fails
        self.assertFalse(overview.queue_mode(view(task(1, "Plan & run: docs/s.md", "pending"))))
        self.assertFalse(overview.queue_mode(view(task(1, "Plan & run: docs/s.md", "completed", queue=True))))
        self.assertFalse(overview.queue_mode(view(task(1, "Task 1: x", "pending", queue=True))))
        # mutation: drop the view["active"] check -> this fails (an idle .tasks.json view is not the lead's list)
        self.assertFalse(overview.queue_mode(view(task(1, "Plan & run: docs/s.md", "pending", queue=True), active=False)))


class OwnedTest(unittest.TestCase):
    V = view(task(1, "Plan & run: docs/s.md", "in_progress", queue=True), task(2, "Task 2: x", "in_progress", owner="fake"),
             task(3, "Task 3: y", "pending", owner="other"), task(4, "Task 4: z", "in_progress", owner="team-lead"))

    def test_window_present_alive_and_ready_since(self):
        mods = {"%9": {"state": "ready", "since": NOW - 1900}}
        got = overview.owned_tasks("p", self.V, panes(("claude", "%1", "0", "0"), ("✦ fake", "%9", "0", "0")), mods, NOW)
        self.assertEqual(got, [{"owner": "fake", "task": "2", "window": True, "dead": False, "ready_s": 1900}])

    def test_window_gone(self):
        got = overview.owned_tasks("p", self.V, panes(("claude", "%1", "0", "0")), {}, NOW)
        self.assertEqual(got, [{"owner": "fake", "task": "2", "window": False, "dead": False, "ready_s": None}])

    def test_dead_pane_and_busy_agent(self):
        # mutation: read pane_dead from the wrong column -> dead stays False and this fails
        got = overview.owned_tasks("p", self.V, panes(("✦ fake", "%9", "1", "0")), {"%9": {"state": "busy", "since": NOW - 5000}}, NOW)
        self.assertEqual(got, [{"owner": "fake", "task": "2", "window": True, "dead": True, "ready_s": None}])

    def test_first_pane_of_the_window_decides(self):
        got = overview.owned_tasks("p", self.V, panes(("✦ fake", "%8", "0", "1"), ("✦ fake", "%9", "1", "0")), {}, NOW)
        self.assertTrue(got[0]["dead"])

    def test_failing_tmux_is_unknown_not_gone(self):
        # mutation: return entries with window False on a tmux error -> this fails
        def boom(*a, check=False):
            raise RuntimeError("no server")
        self.assertEqual(overview.owned_tasks("p", self.V, boom, {}, NOW), [])

    def test_empty_listing_is_unknown_not_gone(self):
        # ruling: a tmux that answers "" (no server, no panes) is unknown too
        self.assertEqual(overview.owned_tasks("p", self.V, lambda *a, check=False: "", {}, NOW), [])


class RecordGatingTest(unittest.TestCase):
    """record(): owned runs only in queue mode (ruling); the new keys are present and ordered."""
    def rec(self, v, calls):
        def tmux(*a, check=False):
            calls.append(a)
            return "✦ fake\t%9\t0\t0\n"
        from unittest import mock
        with tempfile.TemporaryDirectory() as td, mock.patch("overview.planview.view", return_value=v):
            return overview.record({"name": "p", "path": td}, [], NOW, home=Path(td), state_dir=Path(td), tmux=tmux,
                                   th=overview.usage.DEFAULT_ALERTS, spend=None, activity={}, mods={})

    def test_owned_only_in_queue_mode(self):
        calls = []
        r = self.rec(view(task(2, "Task 2: x", "in_progress", owner="fake")), calls)
        self.assertEqual((r["queue"], r["owned"]), (False, []))
        self.assertEqual([c for c in calls if c[0] == "list-panes"], [])
        r = self.rec(view(task(1, "Plan & run: d.md", "in_progress", queue=True), task(2, "Task 2: x", "in_progress", owner="fake")), calls)
        self.assertTrue(r["queue"])
        self.assertEqual(len(r["owned"]), 1)
        self.assertEqual(tuple(r)[-6:], ("queue", "owned", "awake", "pace", "runs", "agents"))


class AwakeTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup)
        self.d = Path(self.td.name)

    def test_missing_file_is_not_live(self):
        self.assertFalse(overview.awake_live(self.d, lambda pid: True))

    def test_live_and_dead_caffeinate(self):
        (self.d / "awake.json").write_text(json.dumps({"caffeinatePid": 4242, "queue": True}))
        self.assertTrue(overview.awake_live(self.d, lambda pid: pid == 4242))
        # mutation: skip the pid_alive call -> this fails
        self.assertFalse(overview.awake_live(self.d, lambda pid: False))

    def test_real_pid_check(self):
        (self.d / "awake.json").write_text(json.dumps({"caffeinatePid": os.getpid()}))
        self.assertTrue(overview.awake_live(self.d))


class PaceTest(unittest.TestCase):
    def test_used_and_elapsed_percent(self):
        lim = {"seven_day": {"used_percentage": 60, "resets_at": NOW + 3.5 * 86400}}
        self.assertEqual(overview.weekly_pace(lim, NOW), {"used": 60, "elapsed": 50.0})

    def test_unknown_or_past_window_is_none(self):
        self.assertIsNone(overview.weekly_pace(None, NOW))
        self.assertIsNone(overview.weekly_pace({"seven_day": {"used_percentage": 60}}, NOW))
        self.assertIsNone(overview.weekly_pace({"seven_day": {"used_percentage": 60, "resets_at": NOW - 1}}, NOW))


class PlanviewQueueFlagTest(unittest.TestCase):
    def test_queue_flag_follows_the_metadata_key(self):
        # mutation: hardcode False in _norm -> the first assertion fails
        raw = [{"id": "1", "subject": "Plan & run: d.md", "metadata": {"queue": {"batch": "b"}}},
               {"id": "2", "subject": "Plan & run: e.md", "metadata": {}}, {"id": "3", "subject": "x"}]
        self.assertEqual([t["queue"] for t in planview._finish([planview._norm(t) for t in raw])], [True, False, False])


class RecordKeysTest(unittest.TestCase):
    def test_new_keys_sit_before_agents(self):
        self.assertEqual(overview.RECORD_KEYS[-6:], ("queue", "owned", "awake", "pace", "runs", "agents"))


if __name__ == "__main__":
    unittest.main()
