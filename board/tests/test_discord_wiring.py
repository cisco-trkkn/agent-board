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
import discord_merge  # noqa: E402
import discord_ops  # noqa: E402
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
        self.assertEqual(tick.call_args[1], {"lead_tasks": tasks, "list_id": "session-sid", "live": None, "limits": mock.ANY, "lead_sid": "sid"})

    def test_tick_and_ops_get_live_limits_and_lead_ids(self):
        self.configure("p")
        live = [{"session_id": "s1"}]
        lim = {"seven_day": {}}
        with mock.patch.object(server.planview, "lead_entry", return_value=("sid", 5, 6)), \
             mock.patch.object(server.planview, "raw_live_list", return_value=("l", [])), \
             mock.patch.object(server.usage, "tap_entries", return_value=[]), \
             mock.patch.object(server.usage, "plan_limits", return_value=lim) as pl, \
             mock.patch.object(server.discord_ops, "configured", return_value=True), \
             mock.patch.object(server.discord_feed, "tick") as tick, \
             mock.patch.object(server.discord_controls, "step"), \
             mock.patch.object(server, "ops_tick") as ot:
            server.feed_tick([rec("p"), rec("nochan")], 1000.0, live=live)
        pl.assert_called_once()
        self.assertEqual(tick.call_args[1]["live"], live)
        self.assertIs(tick.call_args[1]["limits"], lim)
        self.assertEqual(tick.call_args[1]["lead_sid"], "sid")
        self.assertEqual(ot.call_args[1], {"limits": lim, "live": live, "lead_sids": {"p": "sid", "nochan": "sid"}, "lead_info": {}})

    def test_overview_payload_passes_indexer_snapshot(self):
        ov = {"generated": 1.0, "projects": [rec("p")]}
        idx = mock.Mock()
        idx.snapshot.return_value = [{"session_id": "x"}]
        with mock.patch.object(server, "build_overview", return_value=ov), mock.patch.object(server, "INDEXER", idx), \
             mock.patch.object(server, "ensure_overseer"), mock.patch.object(server, "ensure_discord_bridges"), \
             mock.patch.object(server, "read_limits", return_value={"five_hour": 1}) as rl, mock.patch.object(server, "feed_tick") as ft:
            server._overview_cache.update(at=0.0, value=None)
            server.overview_payload()
        self.assertEqual(ft.call_args[1], {"live": [{"session_id": "x"}], "limits": {"five_hour": 1}})
        rl.assert_called_once()   # one tap read per tick, shared by the overview build and feed_tick


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

    def test_dialog_scan_runs_once_per_tick_before_the_projects_with_the_last_sessions(self):
        # mutation: call the scan inside the per-project loop -> two calls for two projects
        self.configure("a")
        self.configure("b")
        order, seen = [], {}
        sessions = [{"name": "a", "windows": []}, {"name": "overseer", "windows": []}]

        def scan(sess, now, run):
            order.append("scan")
            seen.update(sess=sess, now=now, run=run)
        with mock.patch.object(server, "_dialog_sessions", sessions), \
             mock.patch.object(server.discord_dialogs, "scan", side_effect=scan) as sc, \
             mock.patch.object(server.discord_feed, "tick", side_effect=lambda *a, **k: order.append("tick")), \
             mock.patch.object(server.discord_controls, "step"), \
             mock.patch.object(server, "run_script", return_value="{}") as rs:
            server.feed_tick([rec("a"), rec("b")], 1000.0)
            seen["run"](["x", "y"])
        sc.assert_called_once()
        self.assertEqual(order, ["scan", "tick", "tick"])
        self.assertIs(seen["sess"], sessions)
        self.assertEqual(seen["now"], 1000.0)
        self.assertEqual(rs.call_args[0][0], ["x", "y"])
        self.assertNotIn("extra_env", rs.call_args[1])   # no TC_SESSION: the scan reads any project's panes by id
        self.assertEqual(rs.call_args[1]["timeout"], 20)

    def test_each_projects_lead_tasks_go_to_gates_inside_its_own_try(self):
        # mutation: pass [] (or skip the call) -> gates never sees the tasks
        self.configure("a")
        self.configure("b")
        tasks = [{"id": "1", "subject": "User gate: x", "status": "pending"}]
        seen = []

        def gates(project, tk, now):
            seen.append((project, tk, now))
            if project == "a":
                raise RuntimeError("gates broke")
        with mock.patch.object(server.planview, "raw_live_list", return_value=("session-sid", tasks)), \
             mock.patch.object(server.discord_dialogs, "scan"), \
             mock.patch.object(server.discord_dialogs, "gates", side_effect=gates), \
             mock.patch.object(server.discord_feed, "tick"), mock.patch.object(server.discord_controls, "step") as step, \
             mock.patch("sys.stderr") as err:
            server.feed_tick([rec("a"), rec("b")], 1000.0)
        self.assertEqual(seen, [("a", tasks, 1000.0), ("b", tasks, 1000.0)])
        self.assertEqual(step.call_count, 2)   # a failed gates call does not skip the controls step
        self.assertIn("gates broke", "".join(c[0][0] for c in err.write.call_args_list))

    def test_dialog_scan_error_does_not_stop_the_tick(self):
        self.configure("p")
        with mock.patch.object(server.discord_dialogs, "scan", side_effect=RuntimeError("scan broke")), \
             mock.patch.object(server.discord_feed, "tick") as tick, \
             mock.patch.object(server.discord_controls, "step") as step, \
             mock.patch("sys.stderr") as err:
            server.feed_tick([rec("p")], 1000.0)
        tick.assert_called_once()
        step.assert_called_once()
        self.assertIn("discord dialogs failed: RuntimeError: scan broke", "".join(c[0][0] for c in err.write.call_args_list))

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
        def step(project, record, now, run, add_line, lead_run=None, spawn=None):
            captured["run"], captured["lead_run"] = run, lead_run
        with mock.patch.object(server.discord_feed, "tick"), \
             mock.patch.object(server.discord_controls, "step", side_effect=step), \
             mock.patch.object(server, "run_script", return_value="") as rs:
            server.feed_tick([rec("p")], 1000.0)
            captured["run"](["/bin/x", "discord"])
            rs.assert_called_once()
            self.assertEqual(rs.call_args[0][0], ["/bin/x", "discord"])
            self.assertEqual(rs.call_args[1]["extra_env"], {"TC_SESSION": "p"})
            self.assertEqual(rs.call_args[1]["timeout"], 20)
            rs.reset_mock()
            captured["lead_run"](["/bin/x", "lead-restart"])   # the same 120 s runner the ops consumer gets
            self.assertEqual((rs.call_args[0][0], rs.call_args[1]["timeout"]), (["/bin/x", "lead-restart"], 120))

    def test_discord_controls_bin_is_server_bin(self):
        self.assertEqual(server.discord_controls.BIN, server.BIN)


class OpsBase(Base):
    def configure_ops(self, token=True, channels=True):
        d = tc_env.ops_dir()
        d.mkdir(parents=True, exist_ok=True)
        if token:
            (d / ".env").write_text("DISCORD_BOT_TOKEN=dummy\n")
        if channels:
            (d / "bridge.json").write_text(json.dumps({"command_center": "CC", "approvals": "AP", "user": "u1"}))
        return d


class OpsKeeperTest(OpsBase):
    def setUp(self):
        super().setUp()
        server._discord_checked.clear()
        self.run = mock.patch.object(server, "run_script")
        self.m = self.run.start()
        self.addCleanup(self.run.stop)
        self.mono = mock.patch.object(server.time, "monotonic", return_value=1000.0)
        self.clock = self.mono.start()
        self.addCleanup(self.mono.stop)

    def test_starts_ops_bridge_with_ops_flag(self):
        self.configure_ops()
        server.ensure_discord_bridges([])
        self.m.assert_called_once_with([str(server.BIN / "tmux-ctl"), "discord", "bridge", "start", "--keeper", "--ops"], timeout=20)

    def test_needs_token_and_both_channels(self):
        self.configure_ops(token=False)
        server.ensure_discord_bridges([])
        d = tc_env.ops_dir()
        (d / "bridge.json").unlink()
        self.configure_ops(token=True, channels=False)
        server.ensure_discord_bridges([])
        (d / "bridge.json").write_text(json.dumps({"command_center": "CC"}))
        server.ensure_discord_bridges([])
        self.m.assert_not_called()

    def test_once_per_60s(self):
        self.configure_ops()
        server.ensure_discord_bridges([])
        self.clock.return_value = 1059.0
        server.ensure_discord_bridges([])
        self.assertEqual(self.m.call_count, 1)
        self.clock.return_value = 1061.0
        server.ensure_discord_bridges([])
        self.assertEqual(self.m.call_count, 2)

    def test_kill_switch(self):
        self.configure_ops()
        with mock.patch.dict(os.environ, {"TC_DISCORD_BRIDGE": "0"}):
            server.ensure_discord_bridges([])
        self.m.assert_not_called()

    def test_failure_logged_and_rate_limited(self):
        self.configure_ops()
        self.m.side_effect = RuntimeError("boom")
        with mock.patch("sys.stderr") as err:
            server.ensure_discord_bridges([])
            server.ensure_discord_bridges([])
        self.assertEqual(self.m.call_count, 1)
        self.assertIn("boom", "".join(c[0][0] for c in err.write.call_args_list))

    def test_project_bridges_still_start(self):
        self.configure("p"); self.configure_ops()
        server.ensure_discord_bridges([rec("p")])
        argvs = [c[0][0] for c in self.m.call_args_list]
        self.assertIn([str(server.BIN / "tmux-ctl"), "discord", "bridge", "start", "--keeper", "--project", "p"], argvs)
        self.assertEqual(len(argvs), 2)


class OpsTickWiringTest(OpsBase):
    def setUp(self):
        super().setUp()
        server._discord_checked.clear()
        self.order = []
        self.tick = mock.patch.object(server.discord_ops, "tick", side_effect=lambda *a, **k: self.order.append("ops-tick"))
        self.consume = mock.patch.object(server.discord_ops, "consume", side_effect=lambda *a, **k: self.order.append("ops-consume"))
        self.mt, self.mc = self.tick.start(), self.consume.start()
        self.addCleanup(self.tick.stop); self.addCleanup(self.consume.stop)
        self.limits = mock.patch.object(server.usage, "plan_limits", return_value={"five_hour": 12})
        self.taps = mock.patch.object(server.usage, "tap_entries", return_value=["tap"])
        self.ml, self.mtaps = self.limits.start(), self.taps.start()
        self.addCleanup(self.limits.stop); self.addCleanup(self.taps.stop)

    def run_tick(self, records, tasks=None, now=1000.0):
        tasks = tasks if tasks is not None else [{"id": "1", "subject": "s", "status": "pending"}]
        with mock.patch.object(server.planview, "lead_entry", return_value=("sid", 5, 6)), \
             mock.patch.object(server.planview, "raw_live_list", return_value=("lid", tasks)), \
             mock.patch.object(server.discord_feed, "tick", side_effect=lambda p, *a, **k: self.order.append(("feed", p))), \
             mock.patch.object(server.discord_controls, "step", side_effect=lambda p, *a, **k: self.order.append(("step", p))):
            server.feed_tick(records, now)

    def test_one_tick_and_one_consume_after_every_project(self):
        self.configure("a"); self.configure("b"); self.configure_ops()
        self.run_tick([rec("a"), rec("b")])
        self.assertEqual(self.order, [("feed", "a"), ("step", "a"), ("feed", "b"), ("step", "b"), "ops-tick", "ops-consume"])

    def test_lead_restart_gets_a_120s_run_and_the_rest_20s(self):
        # mutation: pass timeout=20 (or no lead_run) -> a slow successful restart reads as failed
        self.configure("a"); self.configure_ops()
        self.run_tick([rec("a")])
        k = self.mc.call_args
        with mock.patch.object(server, "run_script", return_value="") as rs:
            k[0][1](["x"])
            k[1]["lead_run"](["y"])
        self.assertEqual([c.kwargs["timeout"] for c in rs.call_args_list], [20, 120])

    def test_tick_args_cover_every_project_even_without_a_channel(self):
        self.configure("a"); self.configure_ops()
        tasks = [{"id": "1", "subject": "s", "status": "pending"}]
        records = [rec("a"), rec("nochan")]
        self.run_tick(records, tasks=tasks, now=1234.0)
        a = self.mt.call_args[0]
        self.assertEqual(a[0], records)
        self.assertEqual(a[1], {"a": tasks, "nochan": tasks})
        self.assertEqual(a[2], {"five_hour": 12})
        self.assertEqual(a[3], 1234.0)
        self.assertEqual(a[4], server.COMMENTS.add_line)
        self.mtaps.assert_called_once_with(1234.0, 10 ** 9)
        self.ml.assert_called_once_with(["tap"])

    def test_consume_gets_add_line_run_now_and_merge_hook(self):
        self.configure_ops()
        self.run_tick([rec("a")], now=55.0)
        args, kw = self.mc.call_args
        self.assertEqual(args[0], server.COMMENTS.add_line)
        self.assertTrue(callable(args[1]))
        self.assertEqual(args[2], 55.0)
        self.assertIs(kw["on_merge"], discord_merge.on_merge)

    def test_ops_not_configured_makes_no_ops_calls(self):
        self.configure("a")
        self.run_tick([rec("a")])
        self.mt.assert_not_called(); self.mc.assert_not_called()

    def test_limits_failure_is_none(self):
        self.configure_ops()
        self.ml.side_effect = RuntimeError("no taps")
        self.run_tick([rec("a")])
        self.assertIsNone(self.mt.call_args[0][2])

    def test_tick_exception_logged_overview_and_consume_continue(self):
        self.configure_ops()
        self.mt.side_effect = RuntimeError("ops tick broke")
        with mock.patch("sys.stderr") as err:
            self.run_tick([rec("a")])
        self.mc.assert_called_once()
        self.assertIn("tmux-dash: discord ops failed: RuntimeError: ops tick broke", "".join(c[0][0] for c in err.write.call_args_list))

    def test_consume_exception_logged(self):
        self.configure_ops()
        self.mc.side_effect = RuntimeError("consume broke")
        with mock.patch("sys.stderr") as err:
            self.run_tick([rec("a")])
        self.assertIn("tmux-dash: discord ops failed: RuntimeError: consume broke", "".join(c[0][0] for c in err.write.call_args_list))

    def test_task_fetch_failure_for_one_project_does_not_stop_ops(self):
        self.configure_ops()
        with mock.patch.object(server.planview, "lead_entry", side_effect=RuntimeError("no lead")), \
             mock.patch("sys.stderr"):
            server.feed_tick([rec("a")], 1.0)
        self.assertEqual(self.mt.call_args[0][1], {"a": []})
        self.mc.assert_called_once()

    def test_overview_payload_returns_when_ops_raises(self):
        self.configure_ops()
        self.mt.side_effect = RuntimeError("x"); self.mc.side_effect = RuntimeError("y")
        ov = {"generated": 1.0, "projects": [rec("p")]}
        with mock.patch.object(server, "build_overview", return_value=ov), \
             mock.patch.object(server, "ensure_overseer"), mock.patch.object(server, "ensure_discord_bridges"), \
             mock.patch.object(server.planview, "lead_entry", return_value=("", 0, 0)), \
             mock.patch.object(server.planview, "raw_live_list", return_value=("", [])), \
             mock.patch("sys.stderr"):
            server._overview_cache.update(at=0.0, value=None)
            value = server.overview_payload()
        self.assertEqual(value["projects"][0]["project"], "p")


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


class LeadInfosTest(Base):
    """server.lead_infos on a faked tmux: the display format split, the status -> state mapping, and its output through discord_ops.lead_view."""

    def infos(self, status, out="%7\t4242\tclaude\t0\n"):
        seen = []
        def fake_tmux(*a, **kw):
            seen.append(a)
            return out
        with mock.patch.object(server, "tmux", fake_tmux), \
                mock.patch.object(server, "capture_panes", lambda ids: {i: ["row"] for i in ids}), \
                mock.patch.object(server, "classify", lambda cmd, rows, bell, mod: ("claude", status)), \
                mock.patch.object(server, "mod_states", lambda: {}), \
                mock.patch.object(server.relay, "session_root", lambda t, p: Path("/root/p")):
            return server.lead_infos(["p"], {"p": "sid-1"}, {"p": 99}), seen

    def test_state_mapping_and_fields(self):
        # mutation: map "working" to idle, or swap the split fields -> the matching case fails
        for status, state in (("working", "busy"), ("waiting", "waiting"), ("waiting-on-lead", "waiting"), ("ready", "idle"), ("idle", "idle"), ("running", "idle")):
            info, seen = self.infos(status)
            self.assertEqual(info["p"], {"window": "claude", "pane": "%7", "pane_pid": 4242, "pid": 99, "session_id": "sid-1",
                                         "root": "/root/p", "state": state}, status)
        self.assertEqual(seen[0][:4], ("display", "-p", "-t", "=p:claude"))
        self.assertEqual(seen[0][4], "#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{window_bell_flag}")

    def test_no_claude_window_leaves_project_out(self):
        self.assertEqual(self.infos("working", out="")[0], {})

    def test_output_feeds_lead_view(self):
        info, _ = self.infos("working")
        v = discord_ops.lead_view(info["p"], {"%7"}, {}, self.tmp.name, 1_800_000_000.0)
        self.assertEqual((v["pane"], v["pid"], v["state"], v["holds_bot"], v["session_id"]), ("%7", 99, "busy", True, "sid-1"))
