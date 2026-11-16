"""Board wiring of the discord feed: the bridge keeper, the feed tick in overview_payload, the notifier's discord sink. Every test runs on a TC_STATE temp dir; run_script and the clock are faked."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("tmux_dash_server_discord", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
import discord_controls  # noqa: E402
import discord_feed  # noqa: E402
import notify  # noqa: E402
import tc_env  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("TC_DISCORD_BRIDGE", None)
        os.environ.pop("TC_DISCORD_ALERTS", None)

    def configure(self, project, token=True, channel="123"):
        d = tc_env.discord_dir(project)
        d.mkdir(parents=True, exist_ok=True)
        if token:
            (d / ".env").write_text("DISCORD_BOT_TOKEN=dummy\n")
        if channel:
            (d / "bridge.json").write_text(json.dumps({"channel": channel, "user": "u1"}))
        return d


def rec(name="p"):
    return {"project": name, "path": f"/{name}", "needs_you": [], "agents": [], "plan": {}}


class BridgeKeeperTest(Base):
    def setUp(self):
        super().setUp()
        server._discord_checked.clear()
        self.run = mock.patch.object(server, "run_script")
        self.m = self.run.start()
        self.addCleanup(self.run.stop)
        self.mono = mock.patch.object(server.time, "monotonic", return_value=1000.0)
        self.clock = self.mono.start()
        self.addCleanup(self.mono.stop)

    def test_starts_configured_project_with_argv(self):
        self.configure("p")
        server.ensure_discord_bridges([rec("p")])
        self.m.assert_called_once()
        self.assertEqual(self.m.call_args[0][0][1:], ["discord", "bridge", "start", "--keeper", "--project", "p"])
        self.assertTrue(self.m.call_args[0][0][0].endswith("/bin/tmux-ctl"))
        self.assertEqual(self.m.call_args[1], {"timeout": 20})

    def test_needs_token_and_channel(self):
        self.configure("a", token=False)
        self.configure("b", channel="")
        server.ensure_discord_bridges([rec("a"), rec("b"), rec("c")])
        self.m.assert_not_called()

    def test_once_per_60s_per_project(self):
        self.configure("p")
        self.configure("q")
        server.ensure_discord_bridges([rec("p")])
        self.clock.return_value = 1059.0
        server.ensure_discord_bridges([rec("p"), rec("q")])
        self.assertEqual([c[0][0][-1] for c in self.m.call_args_list], ["p", "q"])
        self.clock.return_value = 1061.0
        server.ensure_discord_bridges([rec("p")])
        self.assertEqual(self.m.call_count, 3)

    def test_kill_switch(self):
        self.configure("p")
        with mock.patch.dict(os.environ, {"TC_DISCORD_BRIDGE": "0"}):
            server.ensure_discord_bridges([rec("p")])
        self.m.assert_not_called()

    def test_failure_is_logged_not_raised_and_still_rate_limited(self):
        self.configure("p")
        self.m.side_effect = RuntimeError("boom")
        server.ensure_discord_bridges([rec("p")])
        server.ensure_discord_bridges([rec("p")])
        self.assertEqual(self.m.call_count, 1)


class FeedTickWiringTest(Base):
    def setUp(self):
        super().setUp()
        server._discord_checked.clear()

    def test_payload_runs_keeper_then_tick_after_overseer(self):
        order = []
        ov = {"generated": 1.0, "projects": [rec("p"), rec("nochan")]}
        self.configure("p")
        with mock.patch.object(server, "build_overview", return_value=ov), \
             mock.patch.object(server, "ensure_overseer", side_effect=lambda: order.append("overseer")), \
             mock.patch.object(server, "ensure_discord_bridges", side_effect=lambda r: order.append("bridges")), \
             mock.patch.object(server.discord_feed, "tick", side_effect=lambda *a, **k: order.append(("tick", a[0]))), \
             mock.patch.object(server.discord_controls, "step", side_effect=lambda *a, **k: order.append(("step", a[0]))), \
             mock.patch.object(server.planview, "lead_entry", return_value=("", 0, 0)):
            server._overview_cache.update(at=0.0, value=None)
            server.overview_payload()
        self.assertEqual(order, ["overseer", "bridges", ("tick", "p"), ("step", "p")])

    def test_feed_exception_never_breaks_overview(self):
        ov = {"generated": 1.0, "projects": [rec("p")]}
        self.configure("p")
        with mock.patch.object(server, "build_overview", return_value=ov), \
             mock.patch.object(server, "ensure_overseer"), mock.patch.object(server, "ensure_discord_bridges"), \
             mock.patch.object(server.discord_feed, "tick", side_effect=RuntimeError("feed broke")), \
             mock.patch.object(server.discord_controls, "step"), \
             mock.patch.object(server.planview, "lead_entry", return_value=("", 0, 0)), \
             mock.patch("sys.stderr") as err:
            server._overview_cache.update(at=0.0, value=None)
            value = server.overview_payload()
        self.assertEqual(value["projects"][0]["project"], "p")
        self.assertIn("feed broke", "".join(c[0][0] for c in err.write.call_args_list))

    def test_tick_passes_raw_lead_tasks(self):
        self.configure("p")
        tasks = [{"id": "1", "subject": "s", "status": "pending"}]
        with mock.patch.object(server.planview, "lead_entry", return_value=("sid", 5, 6)), \
             mock.patch.object(server.planview, "raw_live_list", return_value=("session-sid", tasks)) as raw, \
             mock.patch.object(server.discord_feed, "tick") as tick, \
             mock.patch.object(server.discord_controls, "step"):
            server.feed_tick([rec("p")], 1000.0)
        raw.assert_called_once_with(server.HOME / ".claude", "sid", 5, 6)
        self.assertEqual(tick.call_args[1], {"lead_tasks": tasks, "list_id": "session-sid"})


class FeedStepWiringTest(Base):
    """feed_tick runs discord_controls.step after discord_feed.tick, with the real runner and the comment queue."""
    def setUp(self):
        super().setUp()
        server._discord_checked.clear()
        self.patches = [
            mock.patch.object(server.planview, "lead_entry", return_value=("sid", 5, 6)),
            mock.patch.object(server.planview, "raw_live_list", return_value=("session-sid", [])),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_step_runs_after_tick_with_runner_and_comments(self):
        self.configure("p")
        order = []
        with mock.patch.object(server.discord_feed, "tick", side_effect=lambda *a, **k: order.append("tick")), \
             mock.patch.object(server.discord_controls, "step", side_effect=lambda *a, **k: order.append("step")) as step:
            server.feed_tick([rec("p")], 1000.0)
        self.assertEqual(order, ["tick", "step"])
        args, kw = step.call_args
        self.assertEqual(args[0], "p")
        self.assertEqual(args[1], rec("p"))
        self.assertEqual(args[2], 1000.0)
        self.assertEqual(kw["add_line"], server.COMMENTS.add_line)   # bound methods compare by (self, func)
        self.assertTrue(callable(kw["run"]))

    def test_step_exception_isolated_per_project(self):
        self.configure("a")
        self.configure("b")
        seen = []
        def step(project, *a, **k):
            seen.append(project)
            if project == "a":
                raise RuntimeError("controls broke")
        with mock.patch.object(server.discord_feed, "tick"), \
             mock.patch.object(server.discord_controls, "step", side_effect=step), \
             mock.patch("sys.stderr") as err:
            server.feed_tick([rec("a"), rec("b")], 1000.0)
        self.assertEqual(seen, ["a", "b"])
        self.assertIn("controls broke", "".join(c[0][0] for c in err.write.call_args_list))

    def test_tick_error_does_not_skip_step(self):  # mutation: step inside the tick's try -> a's step never runs
        self.configure("a")
        self.configure("b")
        seen = []
        def tick(project, *a, **k):
            if project == "a":
                raise RuntimeError("tick broke")
        with mock.patch.object(server.discord_feed, "tick", side_effect=tick), \
             mock.patch.object(server.discord_controls, "step", side_effect=lambda project, *a, **k: seen.append(project)), \
             mock.patch("sys.stderr") as err:
            server.feed_tick([rec("a"), rec("b")], 1000.0)
        self.assertEqual(seen, ["a", "b"])
        self.assertIn("discord feed failed (a): RuntimeError: tick broke", "".join(c[0][0] for c in err.write.call_args_list))

    def test_no_channel_never_calls_step(self):
        self.configure("p", channel="")
        with mock.patch.object(server.discord_feed, "tick"), \
             mock.patch.object(server.discord_controls, "step") as step:
            server.feed_tick([rec("p"), rec("q")], 1000.0)
        step.assert_not_called()

    def test_runner_passes_tc_session_and_timeout(self):
        self.configure("p")
        captured = {}
        def step(project, record, now, run, add_line):
            captured["run"] = run
        with mock.patch.object(server.discord_feed, "tick"), \
             mock.patch.object(server.discord_controls, "step", side_effect=step), \
             mock.patch.object(server, "run_script", return_value="") as rs:
            server.feed_tick([rec("p")], 1000.0)
            captured["run"](["/bin/x", "discord"])
        rs.assert_called_once()
        self.assertEqual(rs.call_args[0][0], ["/bin/x", "discord"])
        self.assertEqual(rs.call_args[1]["extra_env"], {"TC_SESSION": "p"})
        self.assertEqual(rs.call_args[1]["timeout"], 20)

    def test_discord_controls_bin_is_server_bin(self):
        self.assertEqual(server.discord_controls.BIN, server.BIN)


class SinkTest(Base):
    def ev(self, kind="needs_you", project="p"):
        return {"id": 1, "ts": 1000.0, "project": project, "kind": kind, "key": "k", "title": f"{project}: needs you", "text": "w is waiting"}

    def feed(self, project="p"):
        return discord_feed.read_events(project, 0)[0]

    def test_only_with_channel(self):
        notify.discord_sink(self.ev())
        self.assertEqual(self.feed(), [])
        self.configure("p")
        notify.discord_sink(self.ev())
        e = self.feed()
        self.assertEqual([(x["kind"], x["tier"]) for x in e], [("needs_you", "decision")])
        self.assertIn("w is waiting", e[0]["text"])
        self.assertEqual(e[0]["refs"], {})

    def test_tiers(self):
        self.configure("p")
        for k in ("needs_you", "test_failed", "failing", "stuck", "plan_done", "lead_idle", "context", "usage"):
            notify.discord_sink(self.ev(k))
        self.assertEqual({x["kind"]: x["tier"] for x in self.feed()},
                         {"needs_you": "decision", "test_failed": "critical", "failing": "critical", "stuck": "critical",
                          "plan_done": "progress", "lead_idle": "routine", "context": "routine", "usage": "routine"})

    def test_thread_key_from_feed_state(self):
        d = self.configure("p")
        (d / "feed-state.json").write_text(json.dumps({"running_thread_key": "3"}))
        notify.discord_sink(self.ev())
        self.assertEqual(self.feed()[0]["refs"], {"thread_key": "3"})

    def test_never_raises(self):
        self.configure("p")
        with mock.patch.object(discord_feed, "append_event", side_effect=OSError("disk")), mock.patch("sys.stderr") as err:
            notify.discord_sink(self.ev())
        self.assertIn("notify: discord sink failed", "".join(c[0][0] for c in err.write.call_args_list))
