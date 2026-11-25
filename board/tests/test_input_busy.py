"""server._input_busy captures the pane with -e, so a dimmed suggested prompt is told from typed text."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")  # server.py reads it at import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

RULE = "─" * 60


class InputBusyTest(unittest.TestCase):
    def busy(self, line):
        with mock.patch.object(server, "tmux", return_value=RULE + "\n" + line + "\n" + RULE + "\n") as m:
            return server._input_busy("%3"), m

    def test_captures_with_escape_sequences(self):   # mutation: drop -e -> argv lacks it
        busy, m = self.busy("\x1b[39m❯ \x1b[2mwhich project is the scout in?\x1b[0m")
        self.assertIn("-e", m.call_args.args)
        self.assertFalse(busy)

    def test_typed_text_is_busy(self):
        self.assertTrue(self.busy("\x1b[39m❯ half typed\x1b[0m")[0])

    def test_tmux_failure_holds(self):
        with mock.patch.object(server, "tmux", side_effect=RuntimeError):
            self.assertTrue(server._input_busy("%3"))


if __name__ == "__main__":
    unittest.main()
