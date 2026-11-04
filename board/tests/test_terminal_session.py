"""build_state: the terminal's landing tmux session (default `main`) is not a project card unless Claude runs in it."""
import os, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server

SEP = server.SEP


def row(sess, cmd, pid, widx="0", teammate="0", bg="0"):
    f = [sess, "1", widx, "w", "0", "0", "0", pid, "", cmd, "/r", "1", "1", teammate, bg, "/r"]
    assert len(f) == 16   # build_state's fmt has 16 fields
    return SEP.join(f)


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

    def test_fmt_has_sixteen_fields(self):
        self.layout = []
        with mock.patch.object(server, "tmux", return_value="") as t:
            server.build_state()
        self.assertEqual(t.call_args.args[3].count(SEP) + 1, 16)

    def test_claude_in_the_second_window_shows_main(self):
        self.layout = [row("main", "zsh", "%1", widx="0"), row("main", "claude", "%2", widx="1")]
        self.assertEqual(self.names(), ["main"])

    def test_version_string_command_counts_as_claude(self):
        self.layout = [row("main", "2.1.316", "%1")]
        self.assertEqual(self.names(), ["main"])

    def test_teammate_claude_pane_shows_main(self):
        self.layout = [row("main", "claude", "%1", teammate="1")]
        self.assertEqual(self.names(), ["main"])

    def test_claude_in_a_bg_row_does_not_show_main(self):
        self.layout = [row("main", "zsh", "%1"), row("main", "claude", "%2", bg="1")]
        self.assertEqual(self.names(), [])

    def test_env_is_read_at_import(self):
        with mock.patch.dict(os.environ, {"TC_TERMINAL_SESSION": ""}):
            import importlib.util
            spec = importlib.util.spec_from_file_location("tmux_dash_server_term", server.HERE / "server.py")
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        self.assertEqual(m.TERMINAL_SESSION, "")
        self.assertEqual(server.TERMINAL_SESSION, os.environ.get("TC_TERMINAL_SESSION", "main"))


if __name__ == "__main__":
    unittest.main()
