"""build_state: the terminal's landing tmux session (default `main`) is not a project card unless Claude runs in it."""
import os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server

SEP = server.SEP


def row(sess, cmd, pid):
    return SEP.join([sess, "1", "0", "w", "0", "0", "0", pid, "", cmd, "/r", "1", "1", "0", "0", "/r"])


class TerminalSessionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        self.layout = []
        patches = [mock.patch.dict(os.environ, {"TC_STATE": tmp}),   # usage/state reads never touch the real state dir
                   mock.patch.object(server, "tmux", side_effect=lambda *a, **k: "\n".join(self.layout)),
                   mock.patch.object(server, "capture_panes", side_effect=lambda ids: {i: [] for i in ids}),
                   mock.patch.object(server, "cached_worktrees", return_value=None),
                   mock.patch.object(server.relay, "root_for", side_effect=lambda p: p)]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        server._last["panes"] = []

    def names(self):
        return [s["name"] for s in server.build_state()["sessions"]]

    def test_main_with_only_a_shell_is_hidden(self):
        self.layout = [row("main", "zsh", "%1"), row("proj", "claude", "%2")]
        self.assertEqual(self.names(), ["proj"])

    def test_main_with_claude_is_shown(self):
        self.layout = [row("main", "zsh", "%1"), row("main", "claude", "%2")]
        self.assertEqual(self.names(), ["main"])

    def test_other_session_with_only_a_shell_is_shown(self):
        self.layout = [row("work", "zsh", "%1")]
        self.assertEqual(self.names(), ["work"])

    def test_env_names_the_terminal_session(self):
        self.layout = [row("term", "zsh", "%1"), row("main", "zsh", "%2")]
        with mock.patch.object(server, "TERMINAL_SESSION", "term"):
            self.assertEqual(self.names(), ["main"])

    def test_empty_name_disables_the_hiding(self):
        self.layout = [row("main", "zsh", "%1")]
        with mock.patch.object(server, "TERMINAL_SESSION", ""):
            self.assertEqual(self.names(), ["main"])

    def test_env_is_read_at_import(self):
        with mock.patch.dict(os.environ, {"TC_TERMINAL_SESSION": ""}):
            import importlib.util
            spec = importlib.util.spec_from_file_location("tmux_dash_server_term", server.HERE / "server.py")
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        self.assertEqual(m.TERMINAL_SESSION, "")
        self.assertEqual(server.TERMINAL_SESSION, os.environ.get("TC_TERMINAL_SESSION", "main"))


if __name__ == "__main__":
    unittest.main()
