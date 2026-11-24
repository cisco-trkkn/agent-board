"""watch: the night watch's actions on fixed overview records and a fake clock. Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §3, §5, §7.
Every test runs in a temp state dir (TC_STATE too); the runner, nudge and alert sinks are recorders."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import notify, watch  # noqa: E402


def project(name="p", lead_ready=True, **kw):
    rec = {"project": name, "path": f"/{name}", "needs_you": [], "last_run": None, "alerts": [],
           "plan": {"name": "plan-a", "active": True, "done": 1, "total": 3, "in_progress": []},
           "lead": {"status": "working", "last_active": 100.0, "idle_s": 0}, "artifacts": [], "epoch": 0, "spend_today": 0.0,
           "queue": True, "owned": [], "awake": True, "pace": None,
           "agents": [{"window": "claude", "pane": "%1", "state": "ready" if lead_ready else "working", "state_s": None,
                       "turn_s": None, "tool": None}]}
    rec.update(kw)
    return rec


GONE = [{"owner": "fake", "task": "7", "window": False, "dead": False, "ready_s": None}]


def ov(*projects):
    return {"generated": 0, "projects": list(projects)}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup)
        self.dir = Path(self.td.name)
        os.environ["TC_STATE"] = str(self.dir); self.addCleanup(os.environ.pop, "TC_STATE", None)
        self.clock = Clock()
        self.runs, self.nudges, self.alerts = [], [], []
        self.run_result = "ok"
        self.n = notify.Notifier(runner=lambda a: None, enabled=False, now=self.clock, sinks=[])
        self.w = self.watch()
        self.step(project())   # seed the notifier: a quiet project

    def watch(self):
        def run(argv):
            self.runs.append(argv)
            if self.run_result != "ok":
                raise RuntimeError(self.run_result)
            return "awake: on"
        return watch.Watch(now=self.clock, run=run, nudge=lambda p, line: self.nudges.append((p, line)),
                           alert=self.alerts.append, state_dir=self.dir)

    def step(self, *recs):
        o = ov(*recs)
        return self.w.observe(o, self.n.observe(o))


class StallTest(Base):
    def test_teammate_gone_one_nudge_to_a_ready_lead(self):
        self.step(project(owned=GONE))
        self.assertEqual(self.nudges, [("p", "[Watch] teammate fake window is gone (task #7 in progress): respawn it.")])
        self.clock.t += 60
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 1)   # mutation: drop the nudged_at check -> a second nudge, this fails

    def test_busy_lead_is_not_typed_at_until_it_is_ready(self):
        self.step(project(owned=GONE, lead_ready=False))
        self.assertEqual(self.nudges, [])   # mutation: drop _lead_ready -> this fails
        self.clock.t += 60
        self.step(project(owned=GONE, lead_ready=False))
        self.assertEqual(self.nudges, [])
        self.clock.t += 60
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 1)

    def test_teammate_silent_and_lead_idle_lines(self):
        silent = [{"owner": "fake", "task": "7", "window": True, "dead": False, "ready_s": 1860}]
        self.step(project(owned=silent))
        self.assertEqual(self.nudges[-1][1], "[Watch] teammate fake has been idle 31 min with task #7 in progress: check its report or nudge it.")
        self.step(project(owned=silent, lead={"status": "ready", "last_active": 1.0, "idle_s": 960}))
        self.assertEqual(self.nudges[-1][1], "[Watch] you have been idle 16 min with 2 open tasks: continue the queue.")
        self.assertEqual([a["text"] for a in self.alerts], ["idle 16 min with 2 open tasks"])   # lead_idle is posted by the watch
        self.assertEqual(self.alerts[0]["kind"], "watch")

    def test_queue_mode_off_no_action_no_state(self):
        # mutation: drop the p.get("queue") filter in observe -> nudges, this fails
        self.step(project(queue=False, owned=GONE, awake=False))
        self.assertEqual((self.nudges, self.runs, self.alerts), ([], [], []))
        self.assertFalse((self.dir / "watch.json").exists())

    def test_cleared_stall_is_removed_and_a_new_one_nudges_again(self):
        self.step(project(owned=GONE))
        self.step(project())
        self.assertEqual(json.loads((self.dir / "watch.json").read_text())["stalls"], {})
        self.clock.t += notify.RATE_S
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 2)


    def test_second_stall_inside_the_notifier_rate_window_still_nudges(self):
        # ruling: the watch latches on the record fields, not on the notifier event (RATE_S would swallow it)
        self.step(project(owned=GONE))
        self.step(project())
        self.clock.t += 60
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 2)

    def test_lead_idle_outside_queue_mode_no_watch_action(self):
        idle = {"status": "ready", "last_active": 1.0, "idle_s": 960}
        self.step(project(queue=False, lead=idle))
        self.assertEqual((self.nudges, self.runs, self.alerts), ([], [], []))
        self.assertFalse((self.dir / "watch.json").exists())


class AwakeFixTest(Base):
    def test_fix_runs_once_and_reports_ok(self):
        self.step(project(awake=False))
        self.assertEqual(self.runs, [["awake", "on", "--queue", "--lid"]])
        self.assertEqual(self.nudges, [("p", "[Watch] the awake hold dropped and I restarted it: ok.")])
        self.assertEqual([a["text"] for a in self.alerts], ["awake hold restarted: ok"])
        self.clock.t += 60
        self.step(project(awake=False))
        self.assertEqual(len(self.runs), 1)   # mutation: drop the fixed_at check -> a second run, this fails

    def test_fix_failure_is_one_line(self):
        self.run_result = "awake: no tmux server\nmore detail"
        self.step(project(awake=False))
        self.assertEqual(self.nudges[0][1], "[Watch] the awake hold dropped and I restarted it: failed: awake: no tmux server.")

    def test_no_other_kind_runs_a_fix(self):
        self.step(project(owned=GONE, lead={"status": "ready", "last_active": 1.0, "idle_s": 960}))
        self.assertEqual(self.runs, [])


class RealertTest(Base):
    def test_once_at_15_min_then_nothing(self):
        self.step(project(owned=GONE))
        self.clock.t += watch.REALERT_S - 1
        self.step(project(owned=GONE))
        self.assertEqual(self.alerts, [])   # mutation: REALERT_S check off by the minute -> this fails
        self.clock.t += 1
        self.step(project(owned=GONE))
        self.assertEqual([a["text"] for a in self.alerts],
                         ["teammate fake window is gone (task #7 in progress) — lead did not react (15 min)"])
        self.assertEqual(self.alerts[0]["title"], "p")
        self.clock.t += 3600
        self.step(project(owned=GONE))
        self.assertEqual(len(self.alerts), 1)

    def test_weekly_pace_alert_only(self):
        # mutation: put weekly_pace in STALL_KINDS -> a nudge and a re-alert, this fails
        hot = project(pace={"used": 80, "elapsed": 40.0})
        self.step(hot)
        self.clock.t += watch.REALERT_S * 2
        self.step(hot)
        self.assertEqual((self.nudges, self.alerts, self.runs), ([], [], []))


class RestartTest(Base):
    def test_watch_json_survives_a_restart_without_a_second_nudge(self):
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 1)
        d = json.loads((self.dir / "watch.json").read_text())["stalls"]
        self.assertEqual(list(d), ["p\tteammate_gone\tfake"])
        self.assertEqual(set(d["p\tteammate_gone\tfake"]), {"first_at", "nudged_at", "fixed_at", "realerted_at"})
        # a board restart: a fresh notifier (seeds, no events) and a fresh watch reading the file
        self.n = notify.Notifier(runner=lambda a: None, enabled=False, now=self.clock, sinks=[])
        self.w = self.watch()
        self.clock.t += 60
        self.step(project(owned=GONE))
        self.assertEqual(len(self.nudges), 1)
        # mutation: start with no stalls instead of reading watch.json in __init__ -> the seeded notifier gives no event, no re-alert, this fails
        self.clock.t += watch.REALERT_S
        self.step(project(owned=GONE))
        self.assertEqual(len(self.alerts), 1)   # the stall kept its first_at across the restart


class HeartbeatTest(Base):
    def test_every_overview_writes_at_and_queue_projects(self):
        self.step(project("a"), project("b", queue=False))
        hb = json.loads((self.dir / "watch" / "heartbeat").read_text())
        self.assertEqual(hb, {"at": watch.iso(self.clock.t), "queue": ["a"]})
        self.assertRegex(hb["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_default_state_dir_is_tc_state(self):
        w = watch.Watch(now=self.clock)
        self.assertEqual(w.file, self.dir / "watch.json")


if __name__ == "__main__":
    unittest.main()
