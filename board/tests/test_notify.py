import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import notify  # noqa: E402


def project(name="p", **kw):
    rec = {"project": name, "path": f"/{name}", "needs_you": [], "last_run": None, "alerts": [],
           "plan": {"name": "plan-a", "active": True, "done": 1, "total": 3, "in_progress": []},
           "lead": {"status": "working", "last_active": 100.0, "idle_s": 0}, "artifacts": [], "epoch": 0, "spend_today": 0.0}
    rec.update(kw)
    return rec


def ov(*projects):
    return {"generated": 0, "projects": list(projects)}


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class NotifierTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.clock = Clock()
        self.n = notify.Notifier(runner=self.calls.append, enabled=True, now=self.clock)
        self.n.observe(ov(project()))   # seed: a quiet project

    def fire(self, **kw):
        return self.n.observe(ov(project(**kw)))

    # each of the six events fires once, and the banner names project and agent
    def test_needs_you(self):
        ev = self.fire(needs_you=[{"window": "✦ parse", "pane": "%9", "kind": "claude"}])
        self.assertEqual([e["kind"] for e in ev], ["needs_you"])
        self.assertEqual(ev[0]["title"], "p: needs you")
        self.assertIn("✦ parse", ev[0]["text"])

    def test_plan_done(self):
        ev = self.fire(plan={"name": "plan-a", "active": False, "done": 3, "total": 3, "in_progress": []})
        self.assertEqual([(e["kind"], e["key"]) for e in ev], [("plan_done", "plan-a")])

    def test_test_failed(self):
        ev = self.fire(last_run={"id": "r1", "cmd": "pytest -q", "exit": 1, "ts": 1, "age_s": 5, "summary": "1 failed"})
        self.assertEqual([e["kind"] for e in ev], ["test_failed"])
        self.assertIn("exit 1", ev[0]["text"])
        self.assertEqual(self.fire(last_run={"id": "r2", "cmd": "x", "exit": 0, "ts": 2, "age_s": 1, "summary": ""}), [])

    def test_lead_idle(self):
        ev = self.fire(lead={"status": "ready", "last_active": 1.0, "idle_s": 900})
        self.assertEqual([e["kind"] for e in ev], ["lead_idle"])
        self.assertIn("2 open tasks", ev[0]["text"])

    def test_lead_idle_needs_open_tasks_and_ready(self):
        self.assertEqual(self.fire(lead={"status": "working", "last_active": 1.0, "idle_s": 900}), [])
        self.n._last.clear()
        ev = self.fire(lead={"status": "ready", "last_active": 1.0, "idle_s": 900},
                       plan={"name": "plan-a", "active": False, "done": 3, "total": 3, "in_progress": []})
        self.assertEqual([e["kind"] for e in ev], ["plan_done"])   # no open tasks: plan_done, never lead_idle

    def test_high_context_names_project_agent_and_pct(self):
        ev = self.fire(alerts=[{"kind": "context", "label": "ctx 85%", "detail": "", "session": "parse", "context_pct": 85}])
        self.assertEqual(ev[0]["kind"], "context")
        self.assertEqual(ev[0]["title"], "p: high context")
        self.assertEqual(ev[0]["text"], "parse context at 85%")
        self.assertEqual(self.calls[-1], ["osascript", "-e", 'display notification "parse context at 85%" with title "p: high context"'])

    def test_high_usage_session_and_day_total(self):
        ev = self.fire(alerts=[{"kind": "burn", "label": "$20/h", "detail": "", "session": "lead", "context_pct": 10}])
        self.assertEqual([e["kind"] for e in ev], ["usage"])
        self.assertEqual(ev[0]["text"], "lead $20/h")
        self.clock.t += 301   # past the rate limit: a second usage condition of another key may fire
        ev = self.fire(alerts=[{"kind": "burn", "label": "$20/h", "detail": "", "session": "lead", "context_pct": 10},
                               {"kind": "day_total", "label": "$40 today", "detail": "", "session": None}])
        self.assertEqual([e["text"] for e in ev], ["p $40 today"])

    def test_failing_agent_names_window_and_count(self):   # mutation: omit failing from conditions() -> no event
        ev = self.fire(alerts=[{"kind": "failing", "label": "failing ×3", "detail": "", "session": "✦ parse", "fail_streak": 3, "context_pct": None}])
        self.assertEqual([(e["kind"], e["key"]) for e in ev], [("failing", "✦ parse")])
        self.assertEqual(ev[0]["title"], "p: agent failing")
        self.assertEqual(ev[0]["text"], "✦ parse failed 3 tool calls in a row")

    def test_stuck_agent_names_window_and_minutes(self):   # mutation: omit stuck from conditions() -> no event
        al = {"kind": "stuck", "label": "stuck 25m", "detail": "", "session": "claude", "turn_s": 1530, "quiet_s": 1400, "tool": None, "context_pct": None}
        ev = self.fire(alerts=[al])
        self.assertEqual([(e["kind"], e["key"]) for e in ev], [("stuck", "claude")])
        self.assertEqual(ev[0]["title"], "p: agent stuck")
        self.assertEqual(ev[0]["text"], "claude has been on one turn for 25 min and no tool call has finished for 23 min")
        self.clock.t += 1000
        self.fire(alerts=[])
        self.clock.t += 301
        ev = self.fire(alerts=[dict(al, tool="Bash: zsh tools/tests/run-all.zsh")])   # mutation: revert to "with no tool call" -> fails
        self.assertEqual(ev[0]["text"], "claude has been on one turn for 25 min and no tool call has finished for 23 min (running Bash: zsh tools/tests/run-all.zsh)")

    def test_failing_and_stuck_latch_once_per_onset(self):
        al = [{"kind": "failing", "label": "failing ×3", "detail": "", "session": "claude", "fail_streak": 3, "context_pct": None}]
        self.assertEqual(len(self.fire(alerts=al)), 1)
        self.clock.t += 1000
        self.assertEqual(self.fire(alerts=al), [])                      # held: no repeat
        self.assertEqual(self.fire(alerts=[]), [])                      # cleared
        self.clock.t += 301
        self.assertEqual(len(self.fire(alerts=al)), 1)                  # back: fires again
        st = [{"kind": "stuck", "label": "stuck 20m", "detail": "", "session": "claude", "turn_s": 1200, "context_pct": None}]
        self.clock.t += 301
        self.assertEqual([e["kind"] for e in self.fire(alerts=st)], ["stuck"])
        self.clock.t += 1000
        self.assertEqual(self.fire(alerts=st), [])

    def test_kinds_list_has_failing_and_stuck(self):
        self.assertIn("failing", notify.KINDS)
        self.assertIn("stuck", notify.KINDS)

    # once per appearance
    def test_no_refire_while_condition_holds(self):
        ny = [{"window": "✦ parse", "pane": "%9", "kind": "claude"}]
        self.assertEqual(len(self.fire(needs_you=ny)), 1)
        self.clock.t += 1000
        self.assertEqual(self.fire(needs_you=ny), [])

    def test_refires_after_clear_and_return(self):
        ny = [{"window": "✦ parse", "pane": "%9", "kind": "claude"}]
        self.fire(needs_you=ny)
        self.fire(needs_you=[])
        self.clock.t += 301
        self.assertEqual(len(self.fire(needs_you=ny)), 1)

    def test_rate_limit_per_kind_and_project(self):
        self.fire(needs_you=[{"window": "a", "pane": "%1", "kind": "claude"}])
        self.assertEqual(self.fire(needs_you=[{"window": "a", "pane": "%1", "kind": "claude"}, {"window": "b", "pane": "%2", "kind": "claude"}]), [])   # same kind within 5 min: dropped
        # a different kind in the same project, and the same kind in another project, are not limited
        ev = self.n.observe(ov(project(needs_you=[{"window": "a", "pane": "%1", "kind": "claude"}, {"window": "b", "pane": "%2", "kind": "claude"}],
                                       last_run={"id": "r1", "cmd": "x", "exit": 2, "ts": 1, "age_s": 1, "summary": ""})))
        self.assertEqual([e["kind"] for e in ev], ["test_failed"])

    def test_first_overview_and_new_project_only_seed(self):
        n = notify.Notifier(runner=self.calls.append, enabled=True, now=self.clock)
        self.assertEqual(n.observe(ov(project(needs_you=[{"window": "a", "pane": "%1", "kind": "claude"}]))), [])
        # a project that appears later with a condition already true is seeded, not announced
        self.assertEqual(n.observe(ov(project(), project("q", needs_you=[{"window": "a", "pane": "%1", "kind": "claude"}]))), [])
        self.assertEqual(len(n.observe(ov(project(), project("q", needs_you=[{"window": "a", "pane": "%1", "kind": "claude"}, {"window": "b", "pane": "%2", "kind": "claude"}])))), 1)

    def test_tc_notify_off_sends_nothing(self):
        n = notify.Notifier(runner=self.calls.append, enabled=False, now=self.clock)
        n.observe(ov(project()))
        self.assertEqual(n.observe(ov(project(needs_you=[{"window": "a", "pane": "%1", "kind": "claude"}]))), [])
        self.assertEqual(self.calls, [])
        self.assertEqual(n.recent(), [])

    def test_enabled_reads_env(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"TC_NOTIFY": "0"}):
            self.assertFalse(notify.Notifier(runner=self.calls.append).enabled)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TC_NOTIFY", None)
            self.assertTrue(notify.Notifier(runner=self.calls.append).enabled)

    def test_runner_failure_is_logged_not_raised(self):
        def boom(argv):
            raise RuntimeError("no osascript")
        n = notify.Notifier(runner=boom, enabled=True, now=self.clock)
        n.observe(ov(project()))
        ev = n.observe(ov(project(needs_you=[{"window": "a", "pane": "%1", "kind": "claude"}])))
        self.assertEqual(len(ev), 1)
        self.assertEqual(len(n.recent()), 1)

    def test_banner_argv_escapes_quotes_and_backslashes(self):
        argv = notify.banner_argv('say "hi"', 'a\\b "c"')
        self.assertEqual(argv[2], 'display notification "a\\\\b \\"c\\"" with title "say \\"hi\\""')

    def test_recent_is_capped(self):
        n = notify.Notifier(runner=self.calls.append, enabled=True, now=self.clock, keep=3, rate_s=0)
        n.observe(ov(project()))
        for i in range(5):
            n.observe(ov(project(needs_you=[{"window": "a", "pane": f"%{i}", "kind": "claude"}])))
        self.assertEqual([e["key"] for e in n.recent()], ["%2", "%3", "%4"])


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("osascript"), "macOS banners only")
class RealOsascriptTest(unittest.TestCase):
    def test_real_banner_call_exits_zero(self):
        notify.osascript_runner(notify.banner_argv("agent-board test", 'notify.py real call: quote " and \\ pass'))   # raises on a non-zero exit


if __name__ == "__main__":
    unittest.main()
