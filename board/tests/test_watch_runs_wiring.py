"""server wiring of the run watch: the teammate line goes through tell_pane (held while text sits in the pane's input),
and build_overview hands overview.build one ps sampler. Spec docs/superpowers/specs/2026-11-24-run-watch-design.md §b.
TC_STATE is a temp dir; nothing is typed into a real pane."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server_runwatch", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class TellPaneTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        p = mock.patch.dict(os.environ, {"TC_STATE": tmp}); p.start(); self.addCleanup(p.stop)

    def test_typed_when_the_input_is_empty_held_otherwise(self):
        with mock.patch.object(server, "_input_busy", return_value=False), mock.patch.object(server, "send_line") as sl:
            self.assertTrue(server.WATCH.tell("%9", "[Watch] killed x after 10 min, no progress: report to the lead"))
        sl.assert_called_once_with("%9", "[Watch] killed x after 10 min, no progress: report to the lead")
        # mutation: drop the _input_busy check in tell_pane -> send_line is called, this fails
        with mock.patch.object(server, "_input_busy", return_value=True), mock.patch.object(server, "send_line") as sl:
            self.assertFalse(server.WATCH.tell("%9", "x"))
        sl.assert_not_called()


class PsSampleTest(unittest.TestCase):
    def test_ps_text_parses_and_holds_this_process(self):
        procs = server.overview.parse_ps(server.ps_text())
        self.assertIn(os.getpid(), procs)
        self.assertEqual(procs[os.getpid()]["ppid"], os.getppid())

    def test_build_overview_passes_the_sampler(self):
        with mock.patch.object(server.overview, "build", return_value={"generated": 0, "projects": []}) as b, \
             mock.patch.object(server, "state", return_value={"sessions": []}):
            server.build_overview(1.0)
        self.assertIs(b.call_args.kwargs["ps"], server.ps_text)


if __name__ == "__main__":
    unittest.main()
