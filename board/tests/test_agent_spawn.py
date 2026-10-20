"""+ New agent: the board passes model/effort to `tmux-ctl agent`, validated against tc-env.zsh."""
import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
BOARD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOARD))
import tc_env  # noqa: E402

spec = importlib.util.spec_from_file_location("tmux_dash_server_spawn", BOARD / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class SpawnTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.saved = (server.run_script, server.session_path)
        server.run_script = lambda args, **kw: self.calls.append(args) or "started"
        server.session_path = lambda sess: "/tmp"
        self.addCleanup(lambda: (setattr(server, "run_script", self.saved[0]), setattr(server, "session_path", self.saved[1])))

    def act(self, **extra):
        return server._act({"action": "agent", "session": "proj", "name": "w1", "task": "do the thing", **extra})

    def test_defaults_are_sonnet_medium(self):
        self.act()
        a = self.calls[0]
        self.assertEqual(a[a.index("--model") + 1], "sonnet")
        self.assertEqual(a[a.index("--effort") + 1], "medium")

    def test_choices_pass_through(self):
        self.act(model="haiku", effort="low")
        a = self.calls[0]
        self.assertEqual(a[1:], ["agent", "w1", "--model", "haiku", "--effort", "low", "do the thing"])

    def test_rejects_unknown_model_or_effort(self):
        with self.assertRaises(RuntimeError):
            self.act(model="gpt-9")
        with self.assertRaises(RuntimeError):
            self.act(effort="max")
        self.assertEqual(self.calls, [])


class IndexHtmlTest(unittest.TestCase):
    html = (BOARD / "index.html").read_text(encoding="utf-8")

    def options(self, sel_id):
        m = re.search(rf'<select id="{sel_id}"[^>]*>(.*?)</select>', self.html, re.S)
        self.assertTrue(m, sel_id)
        return re.findall(r'<option value="([^"]+)"( selected)?', m.group(1))

    def test_selects_match_tc_env_and_default(self):
        for sel, allowed, default in (("agent-model", tc_env.MODELS, tc_env.DEFAULT_MODEL),
                                      ("agent-effort", tc_env.EFFORTS, tc_env.DEFAULT_EFFORT)):
            opts = self.options(sel)
            self.assertEqual(tuple(v for v, _ in opts), allowed)
            self.assertEqual([v for v, s in opts if s], [default])

    def test_form_sends_them(self):
        self.assertIn('model: $("#agent-model").value', self.html)
        self.assertIn('effort: $("#agent-effort").value', self.html)


if __name__ == "__main__":
    unittest.main()
