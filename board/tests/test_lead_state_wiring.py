"""server.lead_state_tick / overview_payload wiring and `lead_state.py --dry-run` (plan 2026-11-24-remote-lead-liveness, Task 2).
TC_STATE is a temp dir; build_overview, read_limits, observe_overview, the overseer, the bridges and the feed are patched, so no real
NOTIFIER/WATCH, tmux or Discord call runs."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
BOARD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOARD))
spec = importlib.util.spec_from_file_location("tmux_dash_server_lead_state", BOARD / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
import lead_state  # noqa: E402
import tc_env  # noqa: E402

OV = {"generated": 1234.5, "projects": [{"project": "alpha"}], "events": []}


class Payload(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        env = mock.patch.dict(os.environ, {"TC_STATE": tmp})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("TC_LEAD_STATE", None)
        server._overview_cache.update(at=0.0, value=None)
        self.addCleanup(server._overview_cache.update, at=0.0, value=None)
        self.tick = mock.Mock()
        for name, kw in [("read_limits", {"return_value": None}), ("build_overview", {"return_value": dict(OV)}),
                         ("observe_overview", {"return_value": []}), ("ensure_overseer", {}), ("ensure_discord_bridges", {}),
                         ("feed_tick", {}), ("overseer_info", {"return_value": None})]:
            p = mock.patch.object(server, name, **kw)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(server.lead_state, "tick", self.tick)
        p.start()
        self.addCleanup(p.stop)

    def test_tick_once_per_fresh_build_not_on_cache_hit(self):   # mutation: call before the cache check -> 2 calls
        server.overview_payload()
        server.overview_payload()
        self.assertEqual(self.tick.call_count, 1)
        self.assertEqual(self.tick.call_args.args, (OV["projects"], OV["generated"]))

    def test_tick_runs_after_feed_tick(self):
        order = []
        server.feed_tick.side_effect = lambda *a, **k: order.append("feed")
        self.tick.side_effect = lambda *a, **k: order.append("lead")
        server.overview_payload()
        self.assertEqual(order, ["feed", "lead"])

    def test_failure_is_logged_and_the_value_returned(self):   # mutation: drop the try -> RuntimeError escapes
        self.tick.side_effect = RuntimeError("boom")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            v = server.overview_payload()
        self.assertIn("projects", v)
        self.assertIn("lead state failed", err.getvalue())

    def test_tc_lead_state_0_turns_it_off(self):
        with mock.patch.dict(os.environ, {"TC_LEAD_STATE": "0"}):
            server.overview_payload()
        self.tick.assert_not_called()


class Wiring(unittest.TestCase):
    """lead_state_tick's holder_of / sid_of, through the kwargs it hands lead_state.tick."""
    def setUp(self):
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("TC_LEAD_STATE", None)

    def kwargs(self):
        with mock.patch.object(server.lead_state, "tick") as t:
            server.lead_state_tick([], 1.0)
        return t.call_args.kwargs

    def test_holder_true_when_the_pane_holds_the_bot(self):
        with mock.patch.object(server, "tmux", return_value="%7\t4242") as tm, \
                mock.patch.object(server, "discord_leads", return_value={"%7"}) as dl:
            self.assertTrue(self.kwargs()["holder_of"]("alpha"))
        self.assertEqual(tm.call_args.args, ("display", "-p", "-t", "=alpha:claude", "#{pane_id}\t#{pane_pid}"))
        dl.assert_called_once_with([("%7", 4242)])

    def test_holder_false_when_nobody_holds_it(self):
        with mock.patch.object(server, "tmux", return_value="%7\t4242"), mock.patch.object(server, "discord_leads", return_value=set()):
            self.assertFalse(self.kwargs()["holder_of"]("alpha"))

    def test_holder_false_without_a_claude_window(self):
        with mock.patch.object(server, "tmux", return_value=""), mock.patch.object(server, "discord_leads") as dl:
            self.assertFalse(self.kwargs()["holder_of"]("alpha"))
        dl.assert_not_called()

    def test_sid_of_is_lead_entry_first_item(self):
        with mock.patch.object(server.planview, "lead_entry", return_value=("sid-1", 5, 6)) as le:
            self.assertEqual(self.kwargs()["sid_of"]("alpha"), "sid-1")
        self.assertEqual(le.call_args.args[:2], ("alpha", server.HOME / ".claude"))


class DryRun(unittest.TestCase):
    def test_prints_and_writes_nothing(self):   # mutation: write() in dry-run -> the file exists
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TC_STATE": tmp}):
            d = tc_env.discord_dir("alpha")
            d.mkdir(parents=True)
            (d / "bridge.json").write_text("{}")
            ov = {"projects": [{"project": "alpha", "lead": {"status": "ready"}, "agents": []},
                               {"project": "beta", "lead": {"status": "ready"}, "agents": []}]}
            out = io.StringIO()
            with mock.patch("overview.board_overview", return_value=ov), \
                    mock.patch.object(lead_state, "_holder_and_sid", return_value=(True, "")), contextlib.redirect_stdout(out):
                rc = lead_state.main(["--dry-run", "--project", "alpha"])
            lines = out.getvalue().strip().splitlines()
            self.assertEqual((rc, len(lines)), (0, 1))
            j = json.loads(lines[0])
            self.assertEqual((j["project"], j["would_write"]["state"]), ("alpha", "ready"))
            self.assertFalse((d / "lead-state.json").exists())

    def test_without_dry_run_is_usage(self):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(lead_state.main([]), 2)


if __name__ == "__main__":
    unittest.main()
