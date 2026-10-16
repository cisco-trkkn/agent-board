import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
import artifacts  # noqa: E402

spec = importlib.util.spec_from_file_location("tmux_dash_server_art", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        os.environ["TC_STATE"] = str(self.state)
        self.plan = Path(self.tmp.name) / "plan.md"
        self.plan.write_text("# Plan\n")
        self.spec = Path(self.tmp.name) / "spec.md"
        self.spec.write_text("# Spec\n")
        rows = [
            {"ts": 1, "path": str(self.spec), "kind": "spec", "agent": "claude", "hash": sha("# Spec\n"), "url": "", "epoch": 0},
            {"ts": 2, "path": str(self.plan), "kind": "plan", "agent": "claude", "hash": "old", "url": "", "epoch": 0},
            {"ts": 3, "path": str(self.plan), "kind": "plan", "agent": "impl", "hash": sha("# Plan\n"), "url": "", "epoch": 1},
            {"ts": 4, "path": "/x/page.html", "kind": "published", "agent": "claude", "hash": "", "url": "https://claude.ai/code/artifact/a", "epoch": 1},
        ]
        (self.state / "artifacts-p.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "garbage\n")
        (self.state / "lineage-p.jsonl").write_text(json.dumps({"ts": 2.5, "old_session_id": "O", "doc": "/h.md", "pane": "%1"}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_STATE", None)


class SummaryTest(Base):
    def test_summary(self):
        s = artifacts.summary("p")
        self.assertEqual(s["epoch"], 1)
        self.assertEqual(s["active_plan"], str(self.plan))
        self.assertEqual(s["started_from"], "/h.md")
        self.assertEqual([i["kind"] for i in s["items"]], ["published", "plan", "spec"])
        plan = s["items"][1]
        self.assertEqual(len(plan["history"]), 2)
        self.assertEqual(plan["latest"]["agent"], "impl")

    def test_active_plan_ignores_newer_worker_worktree_plan(self):
        wt = "/r/.claude/worktrees/w1/docs/superpowers/plans/x.md"
        with (self.state / "artifacts-p.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 9, "path": wt, "kind": "plan", "agent": "w1", "hash": "h", "url": "", "epoch": 1}) + "\n")
        self.assertEqual(artifacts.summary("p")["active_plan"], str(self.plan))

    def test_active_plan_prefers_lead_in_current_epoch_then_newest(self):
        wt = "/r/.claude/worktrees/w1/docs/superpowers/plans/x.md"
        (self.state / "artifacts-q.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
            {"ts": 1, "path": "/old.md", "kind": "plan", "agent": "claude", "hash": "", "url": "", "epoch": 0},
            {"ts": 2, "path": "/cur.md", "kind": "plan", "agent": "you", "hash": "", "url": "", "epoch": 1},
            {"ts": 3, "path": "/newer-old.md", "kind": "plan", "agent": "claude", "hash": "", "url": "", "epoch": 0}]))
        (self.state / "lineage-q.jsonl").write_text(json.dumps({"ts": 1.5}) + "\n")
        self.assertEqual(artifacts.summary("q")["active_plan"], "/cur.md")
        (self.state / "artifacts-r.jsonl").write_text(json.dumps({"ts": 1, "path": wt, "kind": "plan", "agent": "w1", "hash": "", "url": "", "epoch": 0}) + "\n")
        self.assertIsNone(artifacts.summary("r")["active_plan"])   # only another agent's worktree plan: no pin

    def test_flat_strips_control_characters(self):
        self.assertEqual(artifacts._flat("a\x1b[31mb\x03c\x7fd\te", 50), "a [31mb c d e")

    def test_comment_line_flattens_file_name(self):
        line = artifacts.CommentQueue.line({"path": "/x/a\x1bb.md", "anchor": "", "quote": "", "note": "n"})
        self.assertNotIn("\x1b", line)

    def test_comment_held_while_user_has_typed_text(self):
        q = artifacts.CommentQueue()
        q.add("p", "/x/a.md", "", "", "note")
        sent = []
        self.assertEqual(q.deliver("p", "%1", "claude", "ready", lambda p, t: sent.append(t), input_has_text=lambda pane: True), 0)
        self.assertEqual(sent, [])
        self.assertEqual(len(q.pending("p")), 1)   # still queued
        self.assertEqual(q.deliver("p", "%1", "claude", "ready", lambda p, t: sent.append(t), input_has_text=lambda pane: False), 1)

    def test_empty_project(self):
        s = artifacts.summary("none")
        self.assertEqual((s["epoch"], s["items"], s["active_plan"], s["started_from"]), (0, [], None, None))


class ReadSaveTest(Base):
    def test_read_allowlist(self):
        self.assertEqual(artifacts.read("p", str(self.plan))["text"], "# Plan\n")
        with self.assertRaises(FileNotFoundError):
            artifacts.read("p", "/etc/passwd")
        with self.assertRaises(FileNotFoundError):
            artifacts.read("p", "/x/page.html")

    def test_save_conflict(self):
        with self.assertRaises(artifacts.Conflict) as cm:
            artifacts.save("p", str(self.plan), "stale", "new\n")
        self.assertEqual(cm.exception.current["text"], "# Plan\n")
        self.assertEqual(self.plan.read_text(), "# Plan\n")

    def test_save_ok(self):
        with mock.patch.object(artifacts.subprocess, "run") as run:
            got = artifacts.save("p", str(self.plan), sha("# Plan\n"), "# Plan v2\n")
        self.assertEqual(self.plan.read_text(), "# Plan v2\n")
        self.assertEqual(got["hash"], sha("# Plan v2\n"))
        args = run.call_args[0][0]
        self.assertEqual(args[1:], ["--path", str(self.plan), "--agent", "you", "--project", "p"])

    def test_server_save_conflict(self):
        with self.assertRaises(artifacts.Conflict):
            server._act({"action": "save", "session": "p", "path": str(self.plan), "base_hash": "stale", "text": "x"})


class HttpTest(Base):
    def setUp(self):
        super().setUp()
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.hosts = mock.patch.object(server, "ALLOWED_HOSTS", {f"127.0.0.1:{self.port}"})
        self.hosts.start()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}/{server.TOKEN}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)
        self.hosts.stop()
        super().tearDown()

    def call(self, req):
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            finally:
                e.close()

    def test_unlisted_path_is_404(self):
        code, body = self.call(f"{self.base}/api/artifact?session=p&path=/etc/passwd")
        self.assertEqual(code, 404)

    def test_listed_path_is_served(self):
        code, body = self.call(f"{self.base}/api/artifact?session=p&path={self.plan}")
        self.assertEqual((code, body["text"]), (200, "# Plan\n"))

    def test_vendor_http(self):
        with urllib.request.urlopen(f"{self.base}/vendor/marked.min.js", timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertTrue(r.headers["Content-Type"].startswith("application/javascript"))
            self.assertEqual(r.headers["Cache-Control"], "max-age=86400")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(f"{self.base}/vendor/other.js", timeout=5)
        cm.exception.close()
        self.assertEqual(cm.exception.code, 404)

    def test_stale_save_is_409_with_current(self):
        req = urllib.request.Request(
            f"{self.base}/api/action", method="POST", headers={"X-Dash-Token": server.TOKEN},
            data=json.dumps({"action": "save", "session": "p", "path": str(self.plan), "base_hash": "stale", "text": "x"}).encode())
        code, body = self.call(req)
        self.assertEqual(code, 409)
        self.assertEqual(body["current"]["text"], "# Plan\n")
        self.assertEqual(self.plan.read_text(), "# Plan\n")


class VendorRouteTest(unittest.TestCase):
    def test_vendor_route(self):
        self.assertEqual(server.vendor_file("marked.min.js").name, "marked.min.js")
        self.assertIsNone(server.vendor_file("other.js"))
        self.assertIsNone(server.vendor_file("../server.py"))


class CommentTest(unittest.TestCase):
    def test_line_format(self):
        q = artifacts.CommentQueue()
        c = q.add("p", "/r/plan.md", "Task 3", 'do  "X"', "split  it")
        self.assertEqual(artifacts.CommentQueue.line(c), '[Plan comment] plan.md § Task 3: "do "X"" — split it')

    def test_held_while_waiting(self):
        q = artifacts.CommentQueue()
        q.add("p", "/r/plan.md", "", "", "note")
        sent = []
        self.assertEqual(q.deliver("p", "%1", "claude", "waiting", lambda p, t: sent.append(t)), 0)
        self.assertEqual(q.deliver("p", "%1", "shell", "idle", lambda p, t: sent.append(t)), 0)
        self.assertEqual(sent, [])
        self.assertEqual(q.deliver("p", "%1", "claude", "working", lambda p, t: sent.append(t)), 1)
        self.assertEqual(sent, ["[Plan comment] plan.md: — note"])
        self.assertEqual(q.pending("p"), [])

    def test_send_error_requeues(self):
        q = artifacts.CommentQueue()
        q.add("p", "/r/a.md", "", "", "one")
        q.add("p", "/r/a.md", "", "", "two")

        def boom(p, t):
            raise RuntimeError("tmux gone")

        self.assertEqual(q.deliver("p", "%1", "claude", "ready", boom), 0)
        self.assertEqual(len(q.pending("p")), 2)

    def test_empty_note_rejected(self):
        with self.assertRaises(ValueError):
            artifacts.CommentQueue().add("p", "/a.md", "", "", "  ")

    def test_add_line_is_sent_verbatim_in_order(self):
        q = artifacts.CommentQueue()
        q.add("p", "/r/plan.md", "", "", "note")
        q.add_line("p", "[Board] Please shut down teammate py.")
        sent = []
        self.assertEqual(q.deliver("p", "%1", "claude", "ready", lambda p, t: sent.append(t)), 2)
        self.assertEqual(sent, ["[Plan comment] plan.md: — note", "[Board] Please shut down teammate py."])

    def test_add_line_held_while_busy(self):
        q = artifacts.CommentQueue()
        q.add_line("p", "[Board] x")
        sent = []
        self.assertEqual(q.deliver("p", "%1", "claude", "waiting", lambda p, t: sent.append(t)), 0)
        self.assertEqual(q.deliver("p", "%1", "shell", "idle", lambda p, t: sent.append(t)), 0)
        self.assertEqual(q.deliver("p", "%1", "claude", "ready", lambda p, t: sent.append(t), input_has_text=lambda pane: True), 0)
        self.assertEqual(sent, [])
        self.assertEqual(q.deliver("p", "%1", "claude", "ready", lambda p, t: sent.append(t), input_has_text=lambda pane: False), 1)
        self.assertEqual(sent, ["[Board] x"])

    def test_add_line_dedupes_while_queued(self):
        q = artifacts.CommentQueue()
        q.add_line("p", "[Board] x")
        q.add_line("p", "[Board] x")
        self.assertEqual(len(q.pending("p")), 1)
        q.add_line("other", "[Board] x")
        self.assertEqual(len(q.pending("other")), 1)

    def test_add_line_flattens_and_rejects_empty(self):
        q = artifacts.CommentQueue()
        c = q.add_line("p", "[Board]\x1b x\n y")
        self.assertEqual(artifacts.CommentQueue.line(c), "[Board] x y")
        with self.assertRaises(ValueError):
            q.add_line("p", " \x00 ")


if __name__ == "__main__":
    unittest.main()
