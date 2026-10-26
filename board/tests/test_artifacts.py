import hashlib
import importlib.util
import json
import os
import subprocess
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

    def test_summary_returns_items_from_every_epoch(self):
        # the client now lists everything the server returns, so the server must not drop old epochs
        rows = [{"ts": 10 + e, "path": f"/x/{n}", "kind": "plan", "agent": "claude", "hash": "", "url": "", "epoch": e}
                for e, n in enumerate(["old-plan.md", "mid-spec.md", "new-plan.md"])]
        (self.state / "artifacts-m.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (self.state / "lineage-m.jsonl").write_text(json.dumps({"ts": 10.5}) + "\n" + json.dumps({"ts": 11.5}) + "\n")
        s = artifacts.summary("m")
        self.assertEqual(s["epoch"], 2)
        self.assertEqual(sorted(it["latest"]["epoch"] for it in s["items"]), [0, 1, 2])

    def test_empty_project(self):
        s = artifacts.summary("none")
        self.assertEqual((s["epoch"], s["items"], s["active_plan"], s["started_from"]), (0, [], None, None))

    def test_sections_split_and_skip_active_plan(self):
        s = artifacts.summary("p")
        self.assertEqual(s["sections"], [
            {"name": "specs", "items": [str(self.spec)]},
            {"name": "docs", "items": ["https://claude.ai/code/artifact/a"]},
        ])

    def test_older_plans_newest_registered_first(self):
        (self.state / "artifacts-s.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
            {"ts": 1, "path": "/a.md", "kind": "plan", "agent": "claude", "epoch": 0},
            {"ts": 2, "path": "/b.md", "kind": "plan", "agent": "claude", "epoch": 0},
            {"ts": 3, "path": "/c.md", "kind": "plan", "agent": "claude", "epoch": 0},
            {"ts": 4, "path": "/a.md", "kind": "plan", "agent": "claude", "epoch": 0},   # /a.md written again: registered first, latest write 4
            {"ts": 5, "path": "/d.md", "kind": "plan", "agent": "claude", "epoch": 0},   # newest write: the pinned plan
            {"ts": 6, "path": "/h.md", "kind": "handoff", "agent": "claude", "epoch": 0},
            {"ts": 7, "path": "https://claude.ai/doc/d1", "url": "https://claude.ai/doc/d1", "title": "Report", "kind": "doc", "agent": "claude", "epoch": 0},
            {"ts": 8, "path": "/x/page.html", "url": "https://claude.ai/code/artifact/p", "kind": "published", "agent": "claude", "epoch": 0},
            {"ts": 9, "path": "/w.txt", "kind": "weird", "agent": "claude", "epoch": 0},
        ]))
        s = artifacts.summary("s")
        self.assertEqual(s["active_plan"], "/d.md")
        self.assertEqual(s["sections"], [
            {"name": "plans", "items": ["/c.md", "/b.md", "/a.md"]},
            {"name": "docs", "items": ["https://claude.ai/code/artifact/p", "https://claude.ai/doc/d1"]},
            {"name": "other", "items": ["/w.txt", "/h.md"]},
        ])

    def test_title_and_first_ts(self):
        (self.state / "artifacts-t.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
            {"ts": 1, "path": "https://claude.ai/doc/d1", "url": "https://claude.ai/doc/d1", "title": "First", "kind": "doc", "epoch": 0},
            {"ts": 2, "path": "https://claude.ai/doc/d1", "url": "https://claude.ai/doc/d1", "title": "", "kind": "doc", "epoch": 0},
            {"ts": 3, "path": "/x.md", "kind": "spec", "epoch": 0},
        ]))
        by = {i["url"] or i["path"]: i for i in artifacts.summary("t")["items"]}
        self.assertEqual(by["https://claude.ai/doc/d1"]["title"], "First")
        self.assertEqual(by["https://claude.ai/doc/d1"]["first_ts"], 1)
        self.assertEqual(by["/x.md"]["title"], "")


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


class MoveTest(Base):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.src, self.dst = root / "srcrepo", root / "dstrepo"
        (self.src / "docs/superpowers/plans").mkdir(parents=True)
        self.dst.mkdir()
        self.doc = self.src / "docs/superpowers/plans/2026-10-19-x.md"
        self.doc.write_text("# X\n")
        self.side = Path(f"{self.doc}.tasks.json")
        self.side.write_text("{}\n")
        with open(self.state / "artifacts-p.jsonl", "a") as f:
            f.write(json.dumps({"ts": 9, "path": str(self.doc), "kind": "plan", "agent": "claude",
                                "hash": sha("# X\n"), "url": "", "epoch": 1}) + "\n")

    def move(self, path=None, target="t"):
        return artifacts.move("p", str(path or self.doc), target, str(self.src), str(self.dst))

    def test_move_file_and_sidecar(self):
        with mock.patch.object(artifacts.subprocess, "run") as run:
            msg = self.move()
        new = self.dst / "docs/superpowers/plans/2026-10-19-x.md"
        self.assertEqual(new.read_text(), "# X\n")
        self.assertEqual(Path(f"{new}.tasks.json").read_text(), "{}\n")
        self.assertFalse(self.doc.exists() or self.side.exists())
        self.assertIn("t", msg)
        args = run.call_args[0][0]
        self.assertEqual(args[1:], ["--path", str(new), "--agent", "you", "--project", "t"])
        self.assertFalse(any("git" in str(c[0][0][0]) for c in run.call_args_list))
        last = json.loads((self.state / "artifacts-p.jsonl").read_text().splitlines()[-1])
        self.assertEqual((last["path"], last["moved_to"], last["agent"]), (str(self.doc), str(new), "you"))
        self.assertNotIn(str(self.doc), [i["path"] for i in artifacts.summary("p")["items"]])
        with self.assertRaises(FileNotFoundError):
            artifacts.read("p", str(self.doc))

    def test_hook_is_the_repos_own_script(self):
        repo = Path(artifacts.__file__).resolve().parent.parent
        self.assertEqual(artifacts.HOOK, repo / "claude/hooks/artifact-register.sh")
        self.assertTrue(os.access(artifacts.HOOK, os.X_OK))

    def test_move_with_the_real_hook_and_an_other_kind_plan(self):
        doc = self.src / "docs/superpowers/plans/2026-10-19-real.md"
        doc.write_text("# Real\n")
        env = {**os.environ, "TC_STATE": str(self.state)}
        subprocess.run([str(artifacts.HOOK), "--path", str(doc), "--kind", "other", "--project", "p"],
                       env=env, check=True, capture_output=True, timeout=20)
        real = os.path.realpath(doc)   # the hook resolves symlinks (/var -> /private/var)
        item = next(i for i in artifacts.summary("p")["items"] if os.path.realpath(i["path"]) == real)
        self.assertEqual(item["kind"], "other")
        with mock.patch.dict(os.environ, {"TC_STATE": str(self.state)}):
            artifacts.move("p", item["path"], "t", os.path.realpath(self.src), os.path.realpath(self.dst))
        new = os.path.realpath(self.dst / "docs/superpowers/plans/2026-10-19-real.md")
        self.assertEqual([os.path.realpath(i["path"]) for i in artifacts.summary("t")["items"]], [new])
        self.assertNotIn(real, [os.path.realpath(i["path"]) for i in artifacts.summary("p")["items"]])

    def test_move_without_sidecar(self):
        self.side.unlink()
        with mock.patch.object(artifacts.subprocess, "run"):
            self.move()
        self.assertTrue((self.dst / "docs/superpowers/plans/2026-10-19-x.md").exists())

    def test_refusals_change_nothing(self):
        (self.dst / "docs/superpowers/plans").mkdir(parents=True)
        (self.dst / "docs/superpowers/plans/2026-10-19-x.md").write_text("theirs\n")
        other = self.src / "notes.md"
        other.write_text("n\n")
        with open(self.state / "artifacts-p.jsonl", "a") as f:
            f.write(json.dumps({"ts": 10, "path": str(other), "kind": "other", "agent": "you", "url": ""}) + "\n")
        before = (self.state / "artifacts-p.jsonl").read_text()
        with mock.patch.object(artifacts.subprocess, "run") as run:
            with self.assertRaises(ValueError):   # destination exists
                self.move()
            with self.assertRaises(ValueError):   # outside docs/superpowers/plans|specs
                self.move(path=other)
            with self.assertRaises(ValueError):   # same project
                self.move(target="p")
            with self.assertRaises(FileNotFoundError):   # not in the manifest
                self.move(path=self.src / "docs/superpowers/plans/unknown.md")
        run.assert_not_called()
        self.assertTrue(self.doc.exists() and self.side.exists())
        self.assertEqual((self.state / "artifacts-p.jsonl").read_text(), before)

    def test_refuses_worktree_paths(self):
        wt = self.src / ".claude/worktrees/w/docs/superpowers/plans/y.md"
        wt.parent.mkdir(parents=True)
        wt.write_text("y\n")
        with open(self.state / "artifacts-p.jsonl", "a") as f:
            f.write(json.dumps({"ts": 11, "path": str(wt), "kind": "plan", "agent": "w", "url": ""}) + "\n")
        with mock.patch.object(artifacts.subprocess, "run"):
            with self.assertRaises(ValueError):
                self.move(path=wt)
        self.assertTrue(wt.exists())

    def test_moved_twice_is_refused(self):
        with mock.patch.object(artifacts.subprocess, "run"):
            self.move()
            with self.assertRaises(FileNotFoundError):
                self.move()

    def test_hook_timeout_still_records_the_move(self):
        with mock.patch.object(artifacts.subprocess, "run", side_effect=artifacts.subprocess.TimeoutExpired("hook", 10)):
            self.move()
        new = self.dst / "docs/superpowers/plans/2026-10-19-x.md"
        self.assertTrue(new.exists())
        last = json.loads((self.state / "artifacts-p.jsonl").read_text().splitlines()[-1])
        self.assertEqual((last["path"], last["moved_to"], last["agent"]), (str(self.doc), str(new), "you"))
        self.assertNotIn(str(self.doc), [i["path"] for i in artifacts.summary("p")["items"]])

    def test_failed_sidecar_move_rolls_back(self):
        real_move = artifacts.shutil.move

        def flaky(a, b):
            if str(a).endswith(".tasks.json"):
                raise OSError("disk full")
            return real_move(a, b)

        before = (self.state / "artifacts-p.jsonl").read_text()
        with mock.patch.object(artifacts.shutil, "move", side_effect=flaky), \
                mock.patch.object(artifacts.subprocess, "run") as run:
            with self.assertRaises(OSError):
                self.move()
        run.assert_not_called()
        self.assertTrue(self.doc.exists() and self.side.exists())
        self.assertFalse((self.dst / "docs/superpowers/plans/2026-10-19-x.md").exists())
        self.assertEqual((self.state / "artifacts-p.jsonl").read_text(), before)


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


class DismissTest(Base):
    URL = "https://claude.ai/code/artifact/a"

    def keys(self, s, name="items"):
        return [i["url"] or i["path"] for i in s[name]]

    def test_dismiss_hides_and_restore_brings_back(self):
        before = artifacts.summary("p")
        artifacts.dismiss("p", [str(self.spec)])
        s = artifacts.summary("p")
        flags = {(i["url"] or i["path"]): i["dismissed"] for i in s["items"]}
        self.assertEqual(flags, {self.URL: False, str(self.plan): False, str(self.spec): True})
        self.assertEqual(s["dismissed"], [str(self.spec)])
        shown = [k for sec in s["sections"] for k in sec["items"]]
        self.assertNotIn(str(self.spec), shown)
        self.assertIn(self.URL, shown)
        last = artifacts.entries("p")[-1]
        self.assertEqual((last["path"], last["dismissed"], last["agent"]), (str(self.spec), True, "you"))
        artifacts.dismiss("p", [str(self.spec)], dismissed=False)
        after = artifacts.summary("p")
        self.assertEqual(after["dismissed"], [])
        self.assertEqual(after["sections"], before["sections"])

    def test_dismiss_lines_are_not_writes(self):
        before = {i["path"]: i for i in artifacts.summary("p")["items"]}
        artifacts.dismiss("p", [str(self.spec)])
        artifacts.dismiss("p", [str(self.spec)], dismissed=False)
        after = {i["path"]: i for i in artifacts.summary("p")["items"]}
        for k, it in before.items():
            for f in ("history", "latest", "title", "first_ts"):
                self.assertEqual(it[f], after[k][f])

    def test_dismiss_line_creates_no_item(self):
        with open(self.state / "artifacts-p.jsonl", "a") as f:
            f.write(json.dumps({"ts": 9, "path": "/ghost.md", "dismissed": True, "agent": "you"}) + "\n")
        self.assertNotIn("/ghost.md", [i["path"] for i in artifacts.summary("p")["items"]])

    def test_url_item_keyed_by_url(self):
        artifacts.dismiss("p", [self.URL])
        self.assertEqual(artifacts.entries("p")[-1]["url"], self.URL)
        self.assertEqual(artifacts.summary("p")["dismissed"], [self.URL])

    def test_later_write_brings_it_back(self):
        artifacts.dismiss("p", [str(self.spec)])
        with open(self.state / "artifacts-p.jsonl", "a") as f:
            f.write(json.dumps({"ts": 20, "path": str(self.spec), "kind": "spec", "agent": "claude", "hash": "n", "url": "", "epoch": 1}) + "\n")
        s = artifacts.summary("p")
        self.assertEqual(s["dismissed"], [])
        self.assertFalse([i for i in s["items"] if i["path"] == str(self.spec)][0]["dismissed"])

    def test_newest_first(self):
        artifacts.dismiss("p", [str(self.spec), self.URL])
        self.assertEqual(sorted(artifacts.summary("p")["dismissed"]), sorted([str(self.spec), self.URL]))
        self.assertEqual(artifacts.summary("p")["dismissed"][0], self.URL)   # newer write (ts 4) first

    def test_pinned_plan_is_refused(self):
        with self.assertRaises(ValueError):
            artifacts.dismiss("p", [str(self.plan)])
        self.assertEqual(len(artifacts.entries("p")), 4)
        # even a hand-written dismiss line never hides the pin
        with open(self.state / "artifacts-p.jsonl", "a") as f:
            f.write(json.dumps({"ts": 9, "path": str(self.plan), "dismissed": True, "agent": "you"}) + "\n")
        s = artifacts.summary("p")
        self.assertEqual(s["active_plan"], str(self.plan))
        self.assertNotIn(str(self.plan), s["dismissed"])

    def test_unknown_key_is_refused_and_nothing_written(self):
        with self.assertRaises(FileNotFoundError):
            artifacts.dismiss("p", [str(self.spec), "/nope.md"])
        self.assertEqual(len(artifacts.entries("p")), 4)

    def test_session_dismiss_leaves_pin_and_other_epochs(self):
        artifacts.dismiss_session("p", 1)
        s = artifacts.summary("p")
        self.assertEqual(s["dismissed"], [self.URL])          # epoch 1: the page; the plan is pinned
        self.assertEqual(s["active_plan"], str(self.plan))
        self.assertFalse({i["path"]: i["dismissed"] for i in s["items"]}[str(self.spec)])   # epoch 0 stays
        self.assertEqual(artifacts.dismiss_session("p", 1), 0)   # nothing left to dismiss

    def test_summary_keys_unchanged(self):
        s = artifacts.summary("p")
        self.assertEqual(set(s), {"epoch", "lineage", "items", "active_plan", "sections", "started_from", "dismissed"})
        self.assertEqual(set(s["items"][0]), {"path", "kind", "url", "title", "history", "latest", "first_ts", "dismissed"})


class DismissActionTest(Base):
    def act(self, **body):
        return server._act(body)

    def test_dismiss_and_restore_actions(self):
        self.assertEqual(self.act(action="art_dismiss", session="p", keys=[str(self.spec)], dismissed=True), "dismissed 1")
        self.assertEqual(artifacts.summary("p")["dismissed"], [str(self.spec)])
        self.assertEqual(self.act(action="art_dismiss", session="p", keys=[str(self.spec)], dismissed=False), "restored 1")
        self.assertEqual(artifacts.summary("p")["dismissed"], [])

    def test_session_action(self):
        self.assertEqual(self.act(action="art_dismiss_session", session="p", epoch=1), "dismissed 1")
        self.assertEqual(artifacts.summary("p")["dismissed"], ["https://claude.ai/code/artifact/a"])

    def test_bad_input(self):
        for body in ({"session": "_web-1", "keys": ["x"]}, {"session": "../p", "keys": ["x"]},
                     {"session": "p", "keys": "x"}, {"session": "p", "keys": []},
                     {"session": "p", "keys": [str(self.plan)]}, {"session": "p", "keys": ["/nope.md"]}):
            with self.assertRaises(Exception, msg=body):
                self.act(action="art_dismiss", **body)
        for ep in ("1", None, True, -1):
            with self.assertRaises(Exception, msg=ep):
                self.act(action="art_dismiss_session", session="p", epoch=ep)
        self.assertEqual(len(artifacts.entries("p")), 4)

    def test_http_unknown_key_is_400_with_message(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with mock.patch.object(server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"}):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/{server.TOKEN}/api/action", method="POST",
                    headers={"X-Dash-Token": server.TOKEN},
                    data=json.dumps({"action": "art_dismiss", "session": "p", "keys": ["/nope.md"], "dismissed": True}).encode())
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(cm.exception.code, 400)
                self.assertFalse(json.loads(cm.exception.read())["ok"])
                cm.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            t.join(5)


if __name__ == "__main__":
    unittest.main()
