import importlib.util
import os
import unittest
from pathlib import Path

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
SEP = server.SEP


class Fake:
    """Records tmux calls; answers list-windows / list-panes / has-session."""

    def __init__(self, windows, cmd="2.1.0", rows=(), bell="0", has=True):
        self.windows = windows  # list of (index, name, teammate)
        self.cmd, self.rows, self.bell, self.has = cmd, list(rows), bell, has
        self.calls = []

    def tmux(self, *args, check=False):
        self.calls.append(args)
        if args[0] == "has-session":
            if not self.has and check:
                raise RuntimeError("can't find session")
            return ""
        if args[0] == "list-windows":
            return "\n".join(f"{i}{SEP}{n}{SEP}{'1' if t else '0'}" for i, n, t in self.windows) + "\n"
        if args[0] == "list-panes":
            return f"%7{SEP}{self.cmd}{SEP}{self.bell}\n"
        if args[0] == "new-window":
            return "%9\n"
        if args[0] == "show-options":
            return "1\n"
        return ""

    def names(self):
        return [c[0] for c in self.calls]

    def find(self, name):
        return [c for c in self.calls if c[0] == name]


class RestartOrchestratorTest(unittest.TestCase):
    def run_act(self, fake, **body):
        saved = (server.tmux, server.git, server.pane_text, server.session_path)
        server.tmux = fake.tmux
        server.git = lambda path, *a: type("R", (), {"returncode": 0, "stdout": "/proj/root\n", "stderr": ""})()
        server.pane_text = lambda target, lines=40: fake.rows
        server.session_path = lambda sess: "/proj/root/sub"
        try:
            return server._act({"action": "restart_orchestrator", "session": "proj", **body})
        finally:
            server.tmux, server.git, server.pane_text, server.session_path = saved

    def test_close_session_also_kills_bg_by_exact_name(self):
        fake = Fake([(1, "claude", False)])
        saved = server.tmux
        server.tmux = fake.tmux
        try:
            server._act({"action": "close_session", "session": "proj"})
        finally:
            server.tmux = saved
        killed = [c[2] for c in fake.find("kill-session")]
        self.assertIn("=proj", killed)
        self.assertIn("=proj-bg", killed)

    def test_name_re_matches_ideas_rule(self):
        for bad in (".", "..", ".hidden", "a/b", ""):
            self.assertIsNone(server.NAME_RE.fullmatch(bad), bad)
        for good in ("proj", "my-proj_1", "a.b", "_web-1"):
            self.assertIsNotNone(server.NAME_RE.fullmatch(good), good)

    def test_close_session_spares_a_user_session_named_like_bg(self):
        class NoTag(Fake):
            def tmux(self, *args, check=False):
                if args[0] == "show-options":
                    self.calls.append(args)
                    return ""    # no @tc_bg: not one of ours
                return super().tmux(*args, check=check)
        fake = NoTag([(1, "claude", False)])
        saved = server.tmux
        server.tmux = fake.tmux
        try:
            server._act({"action": "close_session", "session": "proj"})
        finally:
            server.tmux = saved
        self.assertNotIn("=proj-bg", [c[2] for c in fake.find("kill-session")])

    def test_web_session_rejected(self):
        fake = Fake([(1, "claude", False)])
        with self.assertRaises(RuntimeError):
            self.run_act(fake, session="_web-x")
        self.assertEqual(fake.find("respawn-pane"), [])

    def test_missing_session_rejected(self):
        fake = Fake([(1, "claude", False)], has=False)
        with self.assertRaises(RuntimeError):
            self.run_act(fake)
        self.assertEqual(fake.find("respawn-pane"), [])

    def test_busy_without_confirm_refuses(self):
        fake = Fake([(1, "claude", False)], rows=["esc to interrupt"])
        with self.assertRaises(RuntimeError) as cm:
            self.run_act(fake)
        self.assertIn("busy", str(cm.exception))
        self.assertIn("working", str(cm.exception))
        self.assertEqual(fake.find("respawn-pane"), [])
        self.assertEqual(fake.find("send-keys"), [])

    def test_busy_with_confirm_restarts(self):
        fake = Fake([(1, "claude", False)], rows=["esc to interrupt"])
        msg = self.run_act(fake, confirm=True)
        self.assertEqual(len(fake.find("respawn-pane")), 1)
        self.assertIn("restarted", msg)

    def test_idle_respawns_in_root_then_sends_keys(self):
        fake = Fake([(1, "claude", False)], rows=["> "])
        msg = self.run_act(fake)
        self.assertEqual(fake.find("respawn-pane")[0], ("respawn-pane", "-k", "-t", "%7", "-c", "/proj/root"))
        sk = fake.find("send-keys")
        self.assertEqual(sk[0], ("send-keys", "-t", "%7", "-l", "--", "claude-orchestrator"))
        self.assertEqual(sk[1], ("send-keys", "-t", "%7", "Enter"))
        self.assertLess(fake.names().index("respawn-pane"), fake.names().index("send-keys"))
        self.assertEqual(msg, "restarted the orchestrator in proj:claude")

    def test_shell_in_claude_window_restarts_without_confirm(self):
        fake = Fake([(1, "claude", False)], cmd="zsh")
        self.run_act(fake)
        self.assertEqual(len(fake.find("respawn-pane")), 1)

    def test_no_claude_window_creates_one(self):
        fake = Fake([(2, "shell", False)])
        msg = self.run_act(fake)
        nw = fake.find("new-window")[0]
        self.assertEqual(nw[:2], ("new-window", "-d"))
        self.assertEqual(nw[nw.index("-t") + 1], "=proj:")
        self.assertIn("claude", nw)
        self.assertIn("/proj/root", nw)
        self.assertEqual([r[3] for r in fake.find("respawn-pane")], ["%9"])
        self.assertIn("-P", nw)
        self.assertEqual(nw[nw.index("-F") + 1], "#{pane_id}")
        self.assertEqual(fake.find("send-keys"), [("send-keys", "-t", "%9", "-l", "--", "claude-orchestrator"),
                                                  ("send-keys", "-t", "%9", "Enter")])
        self.assertEqual(len(fake.find("move-window")), 1)  # index 1 is free
        self.assertEqual(msg, "started an orchestrator in proj:claude")

    def test_no_move_when_index_one_taken(self):
        fake = Fake([(1, "shell", False)])
        self.run_act(fake)
        self.assertEqual(fake.find("move-window"), [])
        self.assertEqual(fake.find("send-keys")[0][2], "%9")

    def test_teammate_count_in_message(self):
        fake = Fake([(1, "claude", False), (2, "✦ a", True), (3, "✦ b", True)])
        msg = self.run_act(fake)
        self.assertIn("2 teammate windows", msg)

    def test_one_teammate_singular(self):
        fake = Fake([(1, "claude", False), (2, "✦ a", True)])
        self.assertIn("1 teammate window ", self.run_act(fake))


if __name__ == "__main__":
    unittest.main()
