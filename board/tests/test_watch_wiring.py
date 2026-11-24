"""server.observe_overview: the notifier, then the night watch on its events; TC_WATCH=0 and a failing watch.
Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §6. TC_STATE is a temp dir; run_script is never called for real."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server_watch", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class Recorder:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def observe(self, ov, events=None):
        self.calls.append((ov, events))
        if self.fail:
            raise RuntimeError("boom")
        return ["ev"]


class ObserveOverviewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        for p in (mock.patch.dict(os.environ, {"TC_STATE": tmp}), mock.patch.object(server, "run_script")):
            p.start(); self.addCleanup(p.stop)
        self.n, self.w = Recorder(), Recorder()
        for p in (mock.patch.object(server, "NOTIFIER", self.n), mock.patch.object(server, "WATCH", self.w)):
            p.start(); self.addCleanup(p.stop)

    def test_watch_gets_the_notifiers_events(self):
        ov = {"generated": 1, "projects": []}
        self.assertEqual(server.observe_overview(ov), ["ev"])
        self.assertEqual(self.w.calls, [(ov, ["ev"])])   # mutation: call WATCH.observe(ov, []) -> this fails

    def test_tc_watch_0_turns_the_watch_off(self):
        with mock.patch.dict(os.environ, {"TC_WATCH": "0"}):
            server.observe_overview({"generated": 1, "projects": []})
        self.assertEqual((len(self.n.calls), self.w.calls), (1, []))

    def test_a_failing_watch_never_breaks_the_overview(self):
        server.WATCH.fail = True
        self.assertEqual(server.observe_overview({"generated": 1, "projects": []}), ["ev"])



class RealWatchWiringTest(unittest.TestCase):
    """The module-level WATCH: its runner prefixes tmux-ctl, its nudge queues a line for the lead (COMMENTS, the [Board] path)."""
    def test_runner_and_nudge(self):
        with mock.patch.object(server, "run_script", return_value="awake: on") as rs:
            server.WATCH.run(["awake", "on", "--queue", "--lid"])
        self.assertEqual(rs.call_args.args[0], [server.TMUX_CTL, "awake", "on", "--queue", "--lid"])
        server.WATCH.nudge("proj-w", "[Watch] teammate fake window is gone (task #7 in progress): respawn it.")
        self.addCleanup(server.COMMENTS._items.pop, "proj-w", None)
        self.assertEqual([c["text"] for c in server.COMMENTS.pending("proj-w")],
                         ["[Watch] teammate fake window is gone (task #7 in progress): respawn it."])


if __name__ == "__main__":
    unittest.main()
