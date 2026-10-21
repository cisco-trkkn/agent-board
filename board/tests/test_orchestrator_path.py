"""The board starts the lead by absolute path: on a fresh install <repo>/bin is not on PATH."""
import importlib.util
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
BOARD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOARD))
import relay  # noqa: E402

REPO = BOARD.parent


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, check=False):
        self.calls.append(a)
        return ""


def typed(rec):
    return [c[-1] for c in rec.calls if c[0] == "send-keys" and "-l" in c][0]


class OrchestratorPathTest(unittest.TestCase):
    def test_respawn_types_the_absolute_launcher(self):
        rec = Rec()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_BOARD_REPO", None)
            relay.respawn(rec, "%1", "/r", "Read /d.md")
        words = shlex.split(typed(rec))
        self.assertEqual(words[0], str(REPO / "bin" / "claude-orchestrator"))
        self.assertTrue(os.access(words[0], os.X_OK))
        self.assertEqual(words[1:], ["Read /d.md"])

    def test_respawn_without_prompt_is_just_the_launcher(self):
        rec = Rec()
        os.environ.pop("AGENT_BOARD_REPO", None)
        relay.respawn(rec, "%1", "/r")
        self.assertEqual(shlex.split(typed(rec)), [str(REPO / "bin" / "claude-orchestrator")])

    def test_agent_board_repo_wins(self):
        rec = Rec()
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"AGENT_BOARD_REPO": d}):
            relay.respawn(rec, "%1", "/r")
        self.assertEqual(shlex.split(typed(rec)), [os.path.join(d, "bin", "claude-orchestrator")])

    def test_launcher_with_a_space_in_the_repo_path_is_quoted(self):
        rec = Rec()
        with mock.patch.dict(os.environ, {"AGENT_BOARD_REPO": "/a b/repo"}):
            relay.respawn(rec, "%1", "/r", "p")
        self.assertEqual(shlex.split(typed(rec)), ["/a b/repo/bin/claude-orchestrator", "p"])

    def test_manual_hint_names_the_absolute_launcher(self):
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with redirect_stderr(err), mock.patch.object(relay, "relay", side_effect=RuntimeError("x")):
            os.environ.pop("AGENT_BOARD_REPO", None)
            relay.main(["--session", "s", "--doc", "/d.md"])
        self.assertIn(str(REPO / "bin" / "claude-orchestrator"), err.getvalue())


if __name__ == "__main__":
    unittest.main()
