import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("tmux_dash_server_ideas", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
ideas = server.ideas

STATE = {"sessions": [{"name": "p"}, {"name": "q"}, {"name": "_web-1"}]}
SAMPLE = "# Ideas: p\n\n- [ ] 2026-10-16 10:00 · one\n  d\n"


class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_IDEAS_DIR"] = self.tmp.name
        (Path(self.tmp.name) / "p.md").write_text(SAMPLE)
        self.st = mock.patch.object(server, "state", return_value=STATE)
        self.st.start()

    def tearDown(self):
        self.st.stop()
        self.tmp.cleanup()
        os.environ.pop("TC_IDEAS_DIR", None)

    def act(self, **body):
        return server._act(body)

    def test_edit_status_move(self):
        k = "2026-10-16 10:00 · one"
        self.assertEqual(self.act(action="idea_edit", session="p", key=k, text="uno", detail="x"), "idea updated")
        k = "2026-10-16 10:00 · uno"
        self.assertEqual(self.act(action="idea_status", session="p", key=k, status="dropped"), "idea dropped")
        self.assertEqual(self.act(action="idea_status", session="p", key=k, status="open"), "idea restored")
        self.assertEqual(self.act(action="idea_move", session="p", key=k, target="q"), "idea moved to q")
        self.assertEqual([i["text"] for i in ideas.load("q")], ["uno"])

    def test_target_must_be_open(self):
        k = "2026-10-16 10:00 · one"
        for t in ("zz", "_web-1", "../q"):
            with self.assertRaises(Exception):
                self.act(action="idea_move", session="p", key=k, target=t)
        with self.assertRaises(Exception):
            self.act(action="idea_edit", session="_web-1", key=k, text="x")
        self.assertEqual((Path(self.tmp.name) / "p.md").read_text(), SAMPLE)

    def test_artifact_move_passes_repos(self):
        with mock.patch.object(server, "project_repo", side_effect=lambda s: f"/repos/{s}"), \
             mock.patch.object(server.artifacts, "move", return_value="moved") as mv:
            got = self.act(action="artifact_move", session="p", path="/repos/p/docs/superpowers/plans/a.md", target="q")
        self.assertEqual(got, "moved")
        mv.assert_called_once_with("p", "/repos/p/docs/superpowers/plans/a.md", "q", "/repos/p", "/repos/q")

    def test_project_repo_is_main_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            os.system(f"git -C '{d}' init -q && git -C '{d}' commit -q --allow-empty -m i")
            os.system(f"git -C '{d}' worktree add -q '{d}/.claude/worktrees/w' -b w")
            with mock.patch.object(server, "session_path", return_value=f"{d}/.claude/worktrees/w"):
                self.assertEqual(os.path.realpath(server.project_repo("p")), os.path.realpath(d))

    def test_stale_is_409(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with mock.patch.object(server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"}):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/{server.TOKEN}/api/action", method="POST",
                    headers={"X-Dash-Token": server.TOKEN},
                    data=json.dumps({"action": "idea_status", "session": "p", "key": "2026-10-16 10:00 · gone",
                                     "status": "dropped"}).encode())
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(cm.exception.code, 409)
                self.assertFalse(json.loads(cm.exception.read())["ok"])
                cm.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            t.join(5)
