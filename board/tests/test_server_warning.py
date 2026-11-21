"""server.server_warning: the board's copy of restore.tmux_server_cwd, checked at most every 60 s and carried by
build_state as server_warning (spec restart-recovery §4)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")  # server.py reads it at import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

WARN = "tmux server cwd is gone (/gone/dir): new panes start there"


class ServerWarningTest(unittest.TestCase):
    def setUp(self):
        server._cwd_check.update(at=None, msg="")

    def test_checked_at_most_every_60s(self):   # mutation: drop the age check -> called three times
        with mock.patch.object(server.restore, "tmux_server_cwd", side_effect=["w1", "w2"]) as m:
            self.assertEqual(server.server_warning(now=1000.0), "w1")
            self.assertEqual(server.server_warning(now=1059.0), "w1")
            self.assertEqual(server.server_warning(now=1060.0), "w2")
        self.assertEqual(m.call_count, 2)

    def test_none_and_errors_are_empty(self):
        with mock.patch.object(server.restore, "tmux_server_cwd", return_value=None):
            self.assertEqual(server.server_warning(now=1.0), "")
        server._cwd_check.update(at=None, msg="")
        with mock.patch.object(server.restore, "tmux_server_cwd", side_effect=RuntimeError("boom")):
            self.assertEqual(server.server_warning(now=1.0), "")

    def test_build_state_carries_the_warning(self):   # mutation: drop the key from build_state -> KeyError
        with mock.patch.object(server, "tmux", return_value=""), \
             mock.patch.object(server, "cached_worktrees", return_value=[]), \
             mock.patch.object(server, "server_warning", return_value=WARN):
            self.assertEqual(server.build_state()["server_warning"], WARN)


if __name__ == "__main__":
    unittest.main()
