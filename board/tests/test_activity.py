import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
import activity  # noqa: E402

spec = importlib.util.spec_from_file_location("tmux_dash_server_act", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        os.environ["TC_STATE"] = str(self.state)
        logs = self.state / "logs" / "p"
        logs.mkdir(parents=True)
        (logs / "a.log").write_text("hi\n")
        recs = [
            {"id": "a", "ts": 10, "exit": None, "log": str(logs / "a.log"), "cmd": "pytest"},
            {"id": "b", "ts": 20, "exit": None, "log": str(logs / "b.log"), "cmd": "make"},
            {"id": "a", "ts": 10, "exit": 0, "log": str(logs / "a.log"), "cmd": "pytest", "summary": "3 passed"},
            {"id": "evil", "ts": 5, "exit": 0, "log": "/etc/hosts", "cmd": "x"},
        ]
        (self.state / "runs-p.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_STATE", None)

    def test_runs_dedupe(self):
        got = activity.runs("p")
        self.assertEqual([r["id"] for r in got], ["b", "a", "evil"])
        self.assertEqual(got[1]["exit"], 0)

    def test_log_by_id(self):
        self.assertEqual(activity.log_text("p", "a"), "hi\n")
        for bad in ("nope", "evil"):
            with self.assertRaises(FileNotFoundError):
                activity.log_text("p", bad)


class HideBgTest(unittest.TestCase):
    def test_bg_sessions_hidden(self):
        S = server.SEP
        row = lambda sess, bg: S.join([sess, "1", "1", "tests", "0", "", "0", "%1", "t", "zsh", "/r", "1", "1", "", bg])
        out = "\n".join([row("proj", ""), row("proj-bg", "1")])
        with mock.patch.object(server, "tmux", return_value=out), \
             mock.patch.object(server, "pane_text", return_value=[]), \
             mock.patch.object(server, "cached_worktrees", return_value=[]):
            names = [s["name"] for s in server.build_state()["sessions"]]
        self.assertEqual(names, ["proj"])


class RunsEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_STATE"] = self.tmp.name
        recs = [
            {"id": "r1", "ts": 2, "exit": None, "session": "proj", "win": "tests", "cmd": "pytest"},
            {"id": "r2", "ts": 1, "exit": 0, "session": "proj", "win": "tests", "cmd": "make"},
        ]
        (Path(self.tmp.name) / "runs-p.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        logs = Path(self.tmp.name) / "logs" / "p"
        logs.mkdir(parents=True)
        (logs / "r2.log").write_text("make output\n")
        recs[1]["log"] = str(logs / "r2.log")
        (Path(self.tmp.name) / "runs-p.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        self.ideas_dir = tempfile.TemporaryDirectory()
        os.environ["TC_IDEAS_DIR"] = self.ideas_dir.name
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = self.httpd.server_address[1]
        self.hosts = mock.patch.object(server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"})
        self.hosts.start()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{port}/{server.TOKEN}"
        self.url = f"{self.base}/api/runs?session=p"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)
        self.hosts.stop()
        self.tmp.cleanup()
        self.ideas_dir.cleanup()
        os.environ.pop("TC_STATE", None)
        os.environ.pop("TC_IDEAS_DIR", None)

    def get(self, path):
        try:
            with urllib.request.urlopen(f"{self.base}/{path}", timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode()
            finally:
                e.close()

    def test_runs_deduped_newest_first(self):
        with mock.patch.object(server, "tmux", return_value=""):
            code, body = self.get("api/runs?session=p")
        self.assertEqual(code, 200)
        self.assertEqual([r["id"] for r in json.loads(body)["runs"]], ["r1", "r2"])

    def test_log_known_and_unknown(self):
        self.assertEqual(self.get("api/log?session=p&id=r2"), (200, "make output\n"))
        self.assertEqual(self.get("api/log?session=p&id=nope")[0], 404)

    def test_idea_post_then_list(self):
        req = urllib.request.Request(f"{self.base}/api/action", method="POST", headers={"X-Dash-Token": server.TOKEN},
                                     data=json.dumps({"action": "idea", "session": "p", "text": "try  x", "detail": "why"}).encode())
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertTrue(json.loads(r.read())["ok"])
        code, body = self.get("api/ideas?session=p")
        d = json.loads(body)
        self.assertEqual((code, d["open"]), (200, 1))
        self.assertEqual((d["ideas"][0]["text"], d["ideas"][0]["detail"]), ("try x", "why"))

    def test_running_record_gets_window_index(self):
        S = server.SEP
        listing = f"claude{S}1\ntests{S}3\n"
        with mock.patch.object(server, "tmux", return_value=listing) as tm:
            with urllib.request.urlopen(self.url, timeout=5) as r:
                runs = {x["id"]: x for x in json.loads(r.read())["runs"]}
        self.assertEqual(runs["r1"]["window_index"], "3")
        self.assertNotIn("window_index", runs["r2"])  # finished: no lookup
        self.assertEqual(tm.call_count, 1)
        self.assertEqual(tm.call_args[0][:3], ("list-windows", "-t", "=proj"))


if __name__ == "__main__":
    unittest.main()
