import importlib.util
import os
import unittest
from pathlib import Path

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server_agentctl", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
SEP = server.SEP


class Fake:
    """Sessions -> windows (id, name, agent, teammate). Records every tmux call."""

    def __init__(self, sessions, bg_tagged=True):
        self.sessions, self.bg_tagged, self.calls = sessions, bg_tagged, []

    def tmux(self, *args, check=False):
        self.calls.append(args)
        if args[0] == "show-options":
            target = args[args.index("-t") + 1]
            sess = target.lstrip("=").rstrip(":")
            return "1\n" if self.bg_tagged and sess.endswith("-bg") and sess in self.sessions else ""
        if args[0] == "list-windows":
            sess = args[args.index("-t") + 1].lstrip("=")
            return "".join(f"{i}{SEP}{n}{SEP}{'1' if a else ''}{SEP}{'1' if t else ''}\n"
                           for i, n, a, t in self.sessions.get(sess, []))
        return ""

    def kills(self):
        return [c for c in self.calls if c[0] == "kill-window"]


WINDOWS = {
    "proj": [("@1", "claude", False, False), ("@2", "shell", False, False), ("@3", "✦ py", False, True),
             ("@4", "fix-login", True, False), ("@5", "plain-claude", False, False), ("@6", "fix-login-2", True, False)],
    "proj-bg": [("@8", "tests", False, False), ("@9", "bg-worker", True, False)],
}


class AgentControlsTest(unittest.TestCase):
    def setUp(self):
        self.saved = server.tmux
        server.COMMENTS = server.artifacts.CommentQueue()

    def tearDown(self):
        server.tmux = self.saved

    def act(self, fake, **body):
        server.tmux = fake.tmux
        return server._act(body)

    # stop_agent
    def test_stop_worker_kills_by_window_id(self):
        fake = Fake(WINDOWS)
        msg = self.act(fake, action="stop_agent", session="proj", window="fix-login")
        self.assertEqual(fake.kills(), [("kill-window", "-t", "@4")])
        self.assertEqual(msg, "shut down worker fix-login; its worktree and branch are still in Worktrees")

    def test_stop_worker_in_tagged_bg_session(self):
        fake = Fake(WINDOWS)
        self.act(fake, action="stop_agent", session="proj", window="bg-worker")
        self.assertEqual(fake.kills(), [("kill-window", "-t", "@9")])

    def test_untagged_bg_session_is_not_searched(self):
        fake = Fake(WINDOWS, bg_tagged=False)
        with self.assertRaisesRegex(RuntimeError, "no worker window named bg-worker"):
            self.act(fake, action="stop_agent", session="proj", window="bg-worker")
        self.assertEqual(fake.kills(), [])

    def test_stop_refuses_non_workers(self):
        for name in ("claude", "✦ py", "shell", "plain-claude", "tests"):
            fake = Fake(WINDOWS)
            with self.assertRaisesRegex(RuntimeError, f"{name} is not a worker"):
                self.act(fake, action="stop_agent", session="proj", window=name)
            self.assertEqual(fake.kills(), [], name)

    def test_stop_refuses_prefix_and_missing(self):
        for name in ("fix", "fix-login-", "nope", ""):
            fake = Fake(WINDOWS)
            with self.assertRaisesRegex(RuntimeError, "no worker window named"):
                self.act(fake, action="stop_agent", session="proj", window=name)
            self.assertEqual(fake.kills(), [], name)

    def test_stop_refuses_ambiguous_name(self):
        fake = Fake({"proj": [("@4", "dup", True, False), ("@7", "dup", True, False)]})
        with self.assertRaisesRegex(RuntimeError, "more than one window named dup"):
            self.act(fake, action="stop_agent", session="proj", window="dup")
        self.assertEqual(fake.kills(), [])

    def test_stop_refuses_bad_sessions(self):
        for sess in ("_web-1", "", "a b", "../x"):
            fake = Fake(WINDOWS)
            with self.assertRaisesRegex(RuntimeError, "bad session"):
                self.act(fake, action="stop_agent", session=sess, window="fix-login")
            self.assertEqual(fake.kills(), [], sess)

    # ask_shutdown
    def test_ask_shutdown_queues_one_line(self):
        fake = Fake(WINDOWS)
        msg = self.act(fake, action="ask_shutdown", session="proj", window="✦ py")
        self.assertEqual(msg, "asked the lead to shut down py")
        self.act(fake, action="ask_shutdown", session="proj", window="✦ py")
        lines = [server.artifacts.CommentQueue.line(c) for c in server.COMMENTS.pending("proj")]
        self.assertEqual(lines, ["[Board] Please shut down teammate py."])
        self.assertEqual(fake.kills(), [])

    def test_ask_shutdown_refuses_non_teammates(self):
        for name in ("claude", "fix-login", "shell", "py", "nope"):
            fake = Fake(WINDOWS)
            with self.assertRaisesRegex(RuntimeError, f"{name} is not a teammate"):
                self.act(fake, action="ask_shutdown", session="proj", window=name)
        self.assertEqual(server.COMMENTS.pending("proj"), [])

    def test_ask_shutdown_refuses_bad_session(self):
        with self.assertRaisesRegex(RuntimeError, "bad session"):
            self.act(Fake(WINDOWS), action="ask_shutdown", session="_web-1", window="✦ py")


if __name__ == "__main__":
    unittest.main()
