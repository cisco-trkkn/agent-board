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
        # never the real state dir or alerts file: last_run / recent_artifacts read TC_STATE, thresholds() the alerts file
        import shutil, tempfile
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp)
        for p in (mock.patch.dict(os.environ, {"TC_STATE": tmp}), mock.patch.object(server.usage, "ALERTS_PATH", Path(tmp) / "none.json")):
            p.start(); self.addCleanup(p.stop)
        self.patches = [mock.patch.object(server, "state", side_effect=lambda: {"sessions": self.sessions}),
                        mock.patch.object(server, "window_activity", return_value={"proj": {"claude": 1}}),
                        mock.patch.object(server, "spend_today", return_value=None),
                        mock.patch.object(server.overview.planview, "view", return_value=dict(server.overview.planview.EMPTY)),
                        mock.patch.object(server, "run_script"),
                        mock.patch.dict(os.environ, {"TC_OVERSEER": "0"})]   # restored on cleanup: no leak into other modules
        self.run_script = self.patches[4].start(); self.addCleanup(self.patches[4].stop)
        for p in self.patches[:4] + self.patches[5:]:
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

    def test_home_page_ships_the_overview_markup_and_script(self):
        # spec acceptance "Home route": GET /<token>/ serves the overseer home, its script and the notifier
        with urllib.request.urlopen(f"{self.base}/", timeout=5) as r:
            html = r.read().decode()
        for s in ('id="ov-cards"', 'id="ov-events"', 'id="ov-frame"', "function renderHome", "function homeView", "function notifyNew"):
            self.assertIn(s, html, s)

    def test_events_appear_after_a_change(self):
        self.get()                                            # seeds the notifier
        server._overview_cache.update(at=0.0, value=None)     # expire the cache
        self.sessions = [card("proj", status="waiting")]
        d = self.get()
        self.assertEqual([(e["kind"], e["project"]) for e in d["events"]], [("needs_you", "proj")])

    def test_overseer_session_is_not_a_project_card(self):
        S = server.SEP
        row = lambda sess: S.join([sess, "1", "1", "claude", "0", "", "0", "%1", "t", "zsh", "/r", "1", "1", "", "", "/r"])
        out = "\n".join([row("proj"), row("overseer")])
        with mock.patch.object(server, "tmux", side_effect=lambda *a, **k: out if a[0] == "list-panes" else ""), \
             mock.patch.object(server.relay, "root_for", side_effect=lambda p: p), \
             mock.patch.object(server, "cached_worktrees", return_value=None), mock.patch.object(server, "deliver_comments"):
            st = server.build_state()
        self.assertEqual([s["name"] for s in st["sessions"]], ["proj"])
        self.assertEqual(server.overseer_info()["running"], True)

    def test_project_root_is_the_session_root_not_the_pane_path(self):
        # the lead's pane sits in $HOME while the session started in the project: alerts, spend and plan follow #{session_path}
        S = server.SEP
        row = S.join(["proj", "1", "1", "claude", "0", "", "0", "%1", "t", "zsh", "/pane-elsewhere", "1", "1", "", "", "/proj-root"])
        tm = lambda *a, **k: row if a[0] == "list-panes" else ""
        live = [{"name": "a1", "cwd": "/proj-root", "context_pct": 90, "alerts": [{"kind": "context", "label": "ctx 90%"}]},
                {"name": "b1", "cwd": "/pane-elsewhere", "context_pct": 91, "alerts": [{"kind": "context", "label": "ctx 91%"}]}]
        with mock.patch.object(server, "state", side_effect=lambda: server.build_state()), \
             mock.patch.object(server, "tmux", side_effect=tm), mock.patch.object(server.relay, "root_for", side_effect=lambda p: p), \
             mock.patch.object(server, "cached_worktrees", return_value=None), mock.patch.object(server, "deliver_comments"), \
             mock.patch.object(server, "spend_today", return_value=1.0) as sp, \
             mock.patch.object(server.overview.planview, "view", return_value=dict(server.overview.planview.EMPTY)) as pv, \
             mock.patch.object(server, "INDEXER", mock.Mock(snapshot=lambda: live)):
            ov = server.build_overview(1000.0)
        self.assertEqual(sp.call_args[0][0], "/proj-root")
        self.assertEqual(pv.call_args[0][1], "/proj-root")
        self.assertEqual([a["label"] for a in ov["projects"][0]["alerts"] if a["kind"] == "context"], ["ctx 90%"])   # the agent under the pane path is not this project's
        self.assertEqual(ov["projects"][0]["path"], "/proj-root")

    def test_build_overview_passes_the_fresh_agent_status_records(self):   # mutation: build_overview without mods= -> agents has null extras
        d = Path(os.environ["TC_STATE"]) / "agent-status"; d.mkdir()
        rec = json.loads((Path(__file__).resolve().parent / "fixtures" / "agent-status" / "busy-tool.json").read_text())
        rec.update(pane="%1", since=998, updatedAt=999, turnStartedAt=990)
        (d / "s.json").write_text(json.dumps(rec))
        ov = server.build_overview(1000.0)
        self.assertEqual(ov["projects"][0]["agents"], [{"window": "claude", "pane": "%1", "state": "working", "state_s": 2, "turn_s": 10,
                                                        "tool": "Bash: zsh tools/tests/run-all.zsh"}])

    def test_tc_overseer_off_never_spawns(self):
        server._last["windows"] = {"proj": {"claude": 1}}     # no overseer running, a project with a claude window
        server.ensure_overseer()
        self.run_script.assert_not_called()                    # TC_OVERSEER=0 (set in setUp)
        with mock.patch.dict(os.environ, {"TC_OVERSEER": "1"}):
            server.ensure_overseer()
        self.run_script.assert_called_once()
        self.assertEqual(self.run_script.call_args[0][0][-1], "ensure")

    def test_existing_overseer_is_rechecked_at_most_once_a_minute(self):
        # mutation: return early when the session exists (today) -> the first call never runs the script; drop the interval -> the second does
        server._last["windows"] = {"proj": {"claude": 1}, "overseer": {"claude": 1}}
        server._overseer_checked = None
        with mock.patch.dict(os.environ, {"TC_OVERSEER": "1"}), mock.patch.object(server.time, "monotonic") as mono:
            mono.return_value = 1000.0
            server.ensure_overseer()
            self.assertEqual(self.run_script.call_count, 1)
            self.assertEqual(self.run_script.call_args[0][0][-1], "ensure")
            mono.return_value = 1059.0
            server.ensure_overseer()
            self.assertEqual(self.run_script.call_count, 1)    # within 60 s
            mono.return_value = 1061.0
            server.ensure_overseer()
            self.assertEqual(self.run_script.call_count, 2)    # after 60 s

    def test_tc_overseer_off_never_rechecks_an_existing_session(self):
        server._last["windows"] = {"proj": {"claude": 1}, "overseer": {"claude": 1}}
        server._overseer_checked = None
        server.ensure_overseer()                               # TC_OVERSEER=0 from setUp
        self.run_script.assert_not_called()

    def test_missing_overseer_spawns_every_call_as_before(self):
        server._last["windows"] = {"proj": {"claude": 1}}
        server._overseer_checked = None
        with mock.patch.dict(os.environ, {"TC_OVERSEER": "1"}):
            server.ensure_overseer(); server.ensure_overseer()
        self.assertEqual(self.run_script.call_count, 2)

    def test_ensure_runs_outside_the_overview_lock(self):
        held = []
        with mock.patch.object(server, "ensure_overseer", side_effect=lambda: held.append(server._overview_lock.locked())) as ens:
            self.get()
        ens.assert_called_once()
        self.assertEqual(held, [False])                        # a slow tmux-overseer must not stall /api/overview


if __name__ == "__main__":
    unittest.main()
