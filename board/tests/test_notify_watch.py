"""notify: the night watch kinds (teammate_gone, teammate_silent, awake_dropped, weekly_pace), queue mode only.
Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §2. Records are shape-exact overview records (RECORD_KEYS).
awake_dropped also needs queue mode in the PREVIOUS overview (pre-flight ruling: one-overview grace after queue start);
conditions() takes that as queue_before, the set of project names in queue mode in the previous overview."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_feed, notify  # noqa: E402


def project(name="p", **kw):
    rec = {"project": name, "path": f"/{name}", "needs_you": [], "last_run": None, "alerts": [],
           "plan": {"name": "plan-a", "active": True, "done": 1, "total": 3, "in_progress": []},
           "lead": {"status": "working", "last_active": 100.0, "idle_s": 0}, "artifacts": [], "epoch": 0, "spend_today": 0.0,
           "queue": True, "owned": [], "awake": True, "pace": None, "agents": []}
    rec.update(kw)
    return rec


def ov(*projects):
    return {"generated": 0, "projects": list(projects)}


def owned(**kw):
    o = {"owner": "fake", "task": "2", "window": True, "dead": False, "ready_s": None}
    o.update(kw)
    return o


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def kinds(rec, queue_before=("p",)):
    """(kind, key) of every condition for one record; by default the previous overview had queue mode on for p."""
    return [(c["kind"], c["key"]) for c in notify.conditions(ov(rec), queue_before=set(queue_before))]


class ConditionsTest(unittest.TestCase):
    def test_teammate_gone_window_missing_or_pane_dead(self):
        self.assertEqual(kinds(project(owned=[owned(window=False)])), [("teammate_gone", "fake")])
        c = notify.conditions(ov(project(owned=[owned(dead=True)])), queue_before={"p"})[0]
        self.assertEqual((c["kind"], c["title"]), ("teammate_gone", "p: teammate gone"))
        self.assertIn("pane is dead", c["text"])
        self.assertIn("#2", c["text"])

    def test_teammate_silent_at_30_min_not_before(self):
        # mutation: compare with > instead of >= -> the 1800 case fails
        self.assertEqual(kinds(project(owned=[owned(ready_s=1799)])), [])
        self.assertEqual(kinds(project(owned=[owned(ready_s=1800)])), [("teammate_silent", "fake")])
        self.assertIn("idle 30 min", notify.conditions(ov(project(owned=[owned(ready_s=1800)])), queue_before={"p"})[0]["text"])

    def test_awake_dropped(self):
        self.assertEqual(kinds(project(awake=False)), [("awake_dropped", "awake")])

    def test_awake_dropped_has_one_overview_grace_after_queue_start(self):
        # pre-flight ruling: queue mode on now but not in the previous overview -> no awake_dropped yet
        self.assertEqual(kinds(project(awake=False), queue_before=()), [])
        # the second overview with queue on and awake False -> it fires
        self.assertEqual(kinds(project(awake=False), queue_before=("p",)), [("awake_dropped", "awake")])

    def test_weekly_pace_over_15_points(self):
        self.assertEqual(kinds(project(pace={"used": 65, "elapsed": 50.0})), [])
        self.assertEqual(kinds(project(pace={"used": 65.1, "elapsed": 50.0})), [("weekly_pace", "seven_day")])

    def test_queue_mode_off_gives_none_of_them(self):
        # mutation: drop the `if p.get("queue")` gate -> this fails
        rec = project(queue=False, owned=[owned(window=False)], awake=False, pace={"used": 90, "elapsed": 10})
        self.assertEqual(kinds(rec), [])

    def test_records_without_the_new_fields_are_quiet(self):
        rec = project()
        for k in ("queue", "owned", "awake", "pace"):
            rec.pop(k)
        self.assertEqual(kinds(rec), [])

    def test_kinds_and_feed_tiers(self):
        for k in ("teammate_gone", "teammate_silent", "awake_dropped", "weekly_pace"):
            self.assertIn(k, notify.KINDS)
            self.assertEqual(discord_feed.NOTIFY_TIERS[k], "critical")
        self.assertEqual(discord_feed.NOTIFY_TIERS["watch"], "critical")
        self.assertEqual(discord_feed.NOTIFY_TIERS["lead_idle"], "routine")


class LatchTest(unittest.TestCase):
    def test_fires_once_while_it_holds_again_after_it_clears(self):
        clock = Clock()
        n = notify.Notifier(runner=lambda a: None, enabled=False, now=clock, sinks=[])
        n.observe(ov(project()))
        self.assertEqual([e["kind"] for e in n.observe(ov(project(awake=False)))], ["awake_dropped"])
        clock.t += 60
        self.assertEqual(n.observe(ov(project(awake=False))), [])
        n.observe(ov(project()))
        clock.t += notify.RATE_S
        self.assertEqual([e["kind"] for e in n.observe(ov(project(awake=False)))], ["awake_dropped"])

    def test_notifier_grace_after_queue_start(self):
        # queue mode starts on the second overview with awake False: nothing; the third overview fires
        n = notify.Notifier(runner=lambda a: None, enabled=False, now=Clock(), sinks=[])
        n.observe(ov(project(queue=False)))
        self.assertEqual(n.observe(ov(project(awake=False))), [])
        self.assertEqual([e["kind"] for e in n.observe(ov(project(awake=False)))], ["awake_dropped"])


if __name__ == "__main__":
    unittest.main()
