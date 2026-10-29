"""GET /api/overview: the digest plus the notifier's events and the overseer's session info; TC_OVERSEER=0 never spawns."""
import importlib.util
import json
import os
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
os.environ["TC_OVERSEER"] = "0"
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server_overview", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def card(name, status="working"):
    return {"name": name, "attached": True, "path": f"/{name}", "worktrees": None, "windows": [
        {"index": 1, "name": "claude", "bell": False, "worker": False, "teammate": False, "active": True,
         "panes": [{"id": "%1", "index": 0, "title": "", "command": "claude", "path": f"/{name}", "active": True, "kind": "claude", "status": status, "preview": []}]}]}


class OverviewApiTest(unittest.TestCase):
    def setUp(self):
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = self.httpd.server_address[1]
        self.hosts = mock.patch.object(server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"}); self.hosts.start()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{port}/{server.TOKEN}"
        server._overview_cache.update(at=0.0, value=None)
        server.NOTIFIER = server.notify.Notifier(runner=lambda argv: None, enabled=True)
        server._last["windows"] = {"proj": {"claude": 1}, "overseer": {"claude": 1}}
        self.sessions = [card("proj")]
        self.patches = [mock.patch.object(server, "state", side_effect=lambda: {"sessions": self.sessions}),
                        mock.patch.object(server, "window_activity", return_value={"proj": {"claude": 1}}),
                        mock.patch.object(server, "spend_today", return_value=None),
                        mock.patch.object(server.overview.planview, "view", return_value=dict(server.overview.planview.EMPTY)),
                        mock.patch.object(server, "run_script", side_effect=AssertionError("must not spawn"))]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.hosts.stop()

    def get(self):
        with urllib.request.urlopen(f"{self.base}/api/overview", timeout=5) as r:
            return json.load(r)

    def test_payload_shape(self):
        d = self.get()
        self.assertEqual([p["project"] for p in d["projects"]], ["proj"])
        self.assertEqual(d["events"], [])
        self.assertEqual(d["overseer"], {"session": "overseer", "running": True, "window_index": 1})

    def test_events_appear_after_a_change(self):
        self.get()                                            # seeds the notifier
        server._overview_cache.update(at=0.0, value=None)     # expire the cache
        self.sessions = [card("proj", status="waiting")]
        d = self.get()
        self.assertEqual([(e["kind"], e["project"]) for e in d["events"]], [("needs_you", "proj")])

    def test_overseer_session_is_not_a_project_card(self):
        S = server.SEP
        row = lambda sess: S.join([sess, "1", "1", "claude", "0", "", "0", "%1", "t", "zsh", "/r", "1", "1", "", ""])
        out = "\n".join([row("proj"), row("overseer")])
        with mock.patch.object(server, "tmux", side_effect=lambda *a, **k: out if a[0] == "list-panes" else ""), \
             mock.patch.object(server, "cached_worktrees", return_value=None), mock.patch.object(server, "deliver_comments"):
            st = server.build_state()
        self.assertEqual([s["name"] for s in st["sessions"]], ["proj"])
        self.assertEqual(server.overseer_info()["running"], True)

    def test_tc_overseer_off_never_spawns(self):
        server._last["windows"] = {"proj": {"claude": 1}}     # no overseer running, a project with a claude window
        server.ensure_overseer()                               # run_script is patched to fail: not called
        with mock.patch.dict(os.environ, {"TC_OVERSEER": "1"}), mock.patch.object(server, "run_script", return_value="started") as rs:
            server.ensure_overseer()
            self.assertEqual(rs.call_args[0][0][-1], "ensure")


if __name__ == "__main__":
    unittest.main()
