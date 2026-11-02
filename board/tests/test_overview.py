"""overview: one digest record per project from fake tmux and scratch state folders.

Fixtures: the planview fixtures (captured, scrubbed: board/tests/fixtures/planview/README.md) for sessions, tasks and the
artifacts manifest; the run record and the live-usage entry below are synthetic but shape-exact (keys copied from a real
runs-agent-board.jsonl line read through the live board's /api/runs on 2026-10-28, and from usage._live_entry()).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import overview  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "planview"
NOW = 1_800_000_000.0


def fake_tmux(claude_pane="@80.%82", windows=(("claude", "%82"), ("✦ parse", "%90"))):
    def run(*args, check=False):
        if args[0] == "display" and "session_group" in args[-1]:
            return "proj\n"
        if args[0] == "display" and "#{window_id}.#{pane_id}" in args[-1]:
            return claude_pane + "\n"
        if args[0] == "list-windows":
            return "".join(f"{n}\t{p}\n" for n, p in windows)
        raise AssertionError(args)
    return run


def card(name="proj", path=None, lead_status="working", waiting=()):
    """A build_state() session card: windows claude (+ one teammate) with the given lead status; `waiting` names windows at a prompt."""
    def pane(pid, kind, status, idx=0):
        return {"id": pid, "index": idx, "title": "", "command": "claude" if kind == "claude" else "zsh", "path": path or f"/{name}",
                "active": True, "kind": kind, "status": status, "preview": []}
    wins = [{"index": 1, "name": "claude", "bell": False, "worker": False, "teammate": False, "active": True,
             "panes": [pane("%82", "claude", "waiting" if "claude" in waiting else lead_status)]},
            {"index": 2, "name": "✦ parse", "bell": False, "worker": False, "teammate": True, "active": False,
             "panes": [pane("%90", "claude", "waiting" if "✦ parse" in waiting else "working")]}]
    return {"name": name, "attached": True, "path": path or f"/{name}", "windows": wins, "worktrees": None}


RUN = {"id": "5847-14324", "ts": NOW - 120, "agent": "claude", "win": "tests", "session": "proj-bg", "cmd": "python3 -m unittest discover -s board/tests",
       "cwd": "/proj", "exit": 1, "duration": 30, "log": "/x/logs/proj/5847-14324.log", "summary": "Ran 3 tests, FAILED (failures=1)"}
LIVE = {"session_id": "abc", "name": "parse", "role": "teammate", "model": "claude-haiku-5-5", "effort": "low", "agent_name": "parse",
        "cwd": "/proj", "context": 170000, "context_pct": 85, "last_hour": 1.0, "total": 3.0,
        "alerts": [{"kind": "context", "label": "ctx 85%", "detail": "Context is 85% of the model window (alert at 80%)."}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup)
        root = Path(self.td.name)
        self.home, self.state = root / "home", root / "state"
        shutil.copytree(FIX / "sessions", self.home / "sessions"); shutil.copytree(FIX / "tasks", self.home / "tasks")
        self.state.mkdir(); shutil.copy(FIX / "artifacts-proj.jsonl", self.state / "artifacts-proj.jsonl")
        os.environ["TC_STATE"] = str(self.state); self.addCleanup(os.environ.pop, "TC_STATE", None)
        self.lin = root / "lineage"; self.lin.mkdir()
        os.environ["TC_LINEAGE"] = str(self.lin); self.addCleanup(os.environ.pop, "TC_LINEAGE", None)
        p = mock.patch("planview.pane_state", return_value="working"); p.start(); self.addCleanup(p.stop)

    def build(self, sessions=None, live=(), th=None, spend=None, activity=None, now=NOW):
        return overview.build(sessions if sessions is not None else [card()], list(live), now, home=self.home, state_dir=self.state,
                              tmux=fake_tmux(), th=th, spend=spend, activity=activity)


class BuildTest(Base):
    def test_record_keys_and_plan(self):
        r = self.build()["projects"][0]
        self.assertEqual(tuple(r), overview.RECORD_KEYS)
        self.assertEqual((r["plan"]["name"], r["plan"]["active"], r["plan"]["done"], r["plan"]["total"]), ("2026-01-01-demo", True, 1, 3))
        self.assertEqual([(t["subject"], t["owner"], t["state"]) for t in r["plan"]["in_progress"]], [("Task 2: x", "parse", "working")])

    def test_needs_you_lists_waiting_panes(self):
        r = self.build([card(waiting=("✦ parse",))])["projects"][0]
        self.assertEqual(r["needs_you"], [{"window": "✦ parse", "pane": "%90", "kind": "claude"}])
        self.assertEqual(self.build()["projects"][0]["needs_you"], [])

    def test_last_run_and_age(self):
        (self.state / "runs-proj.jsonl").write_text(json.dumps(RUN) + "\n")
        r = self.build()["projects"][0]["last_run"]
        self.assertEqual((r["id"], r["exit"], r["age_s"], r["summary"]), ("5847-14324", 1, 120, RUN["summary"]))

    def test_lead_state_from_claude_pane_and_window_activity(self):
        r = self.build([card(lead_status="ready")], activity={"proj": {"claude": NOW - 1000, "✦ parse": NOW}})["projects"][0]["lead"]
        self.assertEqual(r, {"status": "ready", "last_active": NOW - 1000, "idle_s": 1000})
        no_act = self.build([card()])["projects"][0]["lead"]
        self.assertEqual(no_act, {"status": "working", "last_active": None, "idle_s": None})

    def test_lead_missing_without_claude_window(self):
        c = card(); c["windows"] = c["windows"][1:]
        self.assertEqual(self.build([c])["projects"][0]["lead"]["status"], "missing")

    def test_artifacts_newest_three_and_epoch(self):
        lines = [{"ts": NOW - i, "path": f"/proj/docs/superpowers/specs/s{i}.md", "kind": "spec", "agent": "claude", "hash": "0", "epoch": 0} for i in range(5)]
        (self.state / "artifacts-proj.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines))
        (self.lin / "proj.jsonl").write_text('{"ts": 1, "doc": "/h.md"}\n')
        r = self.build()["projects"][0]
        self.assertEqual([a["path"][-5:] for a in r["artifacts"]], ["s0.md", "s1.md", "s2.md"])
        self.assertEqual(r["epoch"], 1)

    def test_alerts_from_live_sessions_and_day_total(self):
        r = self.build(live=[LIVE], th={**overview.usage.DEFAULT_ALERTS, "day_total": 5}, spend=lambda repo: 7.25)["projects"][0]
        self.assertEqual([(a["kind"], a["session"], a.get("context_pct")) for a in r["alerts"]], [("context", "parse", 85), ("day_total", None, None)])
        self.assertEqual(r["spend_today"], 7.25)
        other = dict(LIVE, cwd="/elsewhere")
        self.assertEqual(self.build(live=[other])["projects"][0]["alerts"], [])

    def test_lead_entry_is_named_lead_not_its_session_id_prefix(self):
        lead = dict(LIVE, role="lead", name="abc"[:8], session_id="abc", agent_name=None)
        r = self.build(live=[lead])["projects"][0]
        self.assertEqual([a["session"] for a in r["alerts"]], ["lead"])
        named = dict(lead, name="orchestrator")      # a tap that supplies a name keeps it
        self.assertEqual([a["session"] for a in self.build(live=[named])["projects"][0]["alerts"]], ["orchestrator"])

    def test_empty_project_no_plan_no_runs_no_alerts(self):
        self.state.joinpath("artifacts-proj.jsonl").unlink()
        shutil.rmtree(self.home / "tasks")
        c = card("bare", path=str(Path(self.td.name) / "bare")); Path(c["path"]).mkdir()
        r = self.build([c])["projects"][0]
        self.assertEqual(r["plan"], {"name": "", "active": False, "done": 0, "total": 0, "in_progress": []})
        self.assertIsNone(r["last_run"]); self.assertEqual(r["alerts"], []); self.assertEqual(r["artifacts"], []); self.assertEqual(r["epoch"], 0)
        self.assertIsNone(r["spend_today"])

    def test_web_views_and_overseer_are_not_projects(self):
        names = [p["project"] for p in self.build([card(), card("_web-1"), card("overseer")])["projects"]]
        self.assertEqual(names, ["proj"])

    def test_failing_spend_and_tmux_do_not_raise(self):
        def boom(repo):
            raise RuntimeError("sqlite locked")
        def bad_tmux(*a, check=False):
            raise RuntimeError("no server")
        ov = overview.build([card()], [], NOW, home=self.home, state_dir=self.state, tmux=bad_tmux, spend=boom)
        self.assertIsNone(ov["projects"][0]["spend_today"])
        self.assertEqual(ov["projects"][0]["plan"]["total"], 0)


class LineTest(unittest.TestCase):
    def rec(self, **kw):
        r = {"project": "proj", "path": "/proj", "attached": True, "plan": {"name": "demo", "active": True, "done": 1, "total": 3,
             "in_progress": [{"id": "2", "subject": "Task 2: x", "owner": "parse", "state": "working"}]},
             "needs_you": [], "last_run": {"id": "r", "cmd": "pytest", "exit": 1, "ts": 1, "age_s": 125, "summary": ""},
             "lead": {"status": "ready", "last_active": 1, "idle_s": 1260}, "artifacts": [], "epoch": 0,
             "alerts": [{"kind": "context", "label": "ctx 85%", "detail": "", "session": "parse", "context_pct": 85}], "spend_today": 3.5}
        r.update(kw)
        return r

    def test_line_has_every_field(self):
        l = overview.line(self.rec(needs_you=[{"window": "✦ parse", "pane": "%9", "kind": "claude"}]))
        for s in ("proj", "plan demo 1/3", "▶ Task 2: x→parse", "NEEDS YOU: ✦ parse", "lead ready 21m", "run exit 1 2m ago", "$3.50 today", "alerts ctx 85%"):
            self.assertIn(s, l)
        self.assertEqual(l.count("\n"), 0)

    def test_line_idle_plan_and_running_run(self):
        l = overview.line(self.rec(plan={"name": "", "active": False, "done": 0, "total": 0, "in_progress": []},
                                   last_run={"id": "r", "cmd": "x", "exit": None, "ts": 1, "age_s": 10, "summary": ""}, spend_today=None, alerts=[]))
        self.assertIn("plan - 0/0 (idle)", l); self.assertIn("run running 0m ago", l); self.assertNotIn("today", l); self.assertNotIn("alerts", l)


class FakeBoard(BaseHTTPRequestHandler):
    payload = {"generated": NOW, "projects": [], "events": []}

    def do_GET(self):
        body = json.dumps(self.payload).encode() if self.path.endswith("/api/overview") else b"not found"
        self.send_response(200 if body != b"not found" else 404); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


class CliTest(unittest.TestCase):
    """overview.py reads the board; tmux-ctl overview is its caller. Token dir: TMUX_DASH_STATE (same layout as ~/.local/state/tmux-dash: a `token` file)."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup)
        self.state = Path(self.td.name); (self.state / "token").write_text("tok\n")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeBoard)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)
        FakeBoard.payload = {"generated": NOW, "events": [], "projects": [
            {"project": "a", "path": "/a", "attached": True, "plan": {"name": "p", "active": True, "done": 0, "total": 2, "in_progress": []}, "needs_you": [],
             "last_run": None, "lead": {"status": "working", "last_active": None, "idle_s": None}, "artifacts": [], "epoch": 0, "alerts": [], "spend_today": None},
            {"project": "b", "path": "/b", "attached": False, "plan": {"name": "", "active": False, "done": 0, "total": 0, "in_progress": []}, "needs_you": [],
             "last_run": None, "lead": {"status": "missing", "last_active": None, "idle_s": None}, "artifacts": [], "epoch": 0, "alerts": [], "spend_today": 0.0}]}
        self.env = {**os.environ, "TMUX_DASH_STATE": str(self.state), "TMUX_DASH_PORT": str(self.httpd.server_address[1])}

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(HERE / "overview.py"), *args], capture_output=True, text=True, env=self.env, timeout=30)

    def test_lines_one_per_project(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 2); self.assertTrue(lines[0].startswith("a ")); self.assertIn("plan p 0/2", lines[0]); self.assertIn("plan - 0/0 (idle)", lines[1])

    def test_json_and_project_filter(self):
        r = self.run_cli("--project", "b", "--json")
        self.assertEqual([p["project"] for p in json.loads(r.stdout)["projects"]], ["b"])
        self.assertEqual(self.run_cli("--project", "zz").returncode, 1)

    def test_board_error_payload_is_printed_not_no_open_projects(self):
        # tmux down: the board answers 200 with projects [] and an error; the CLI must say why
        FakeBoard.payload = {"generated": NOW, "events": [], "projects": [], "error": "no server running on /tmp/tmux-1/default"}
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no server running on /tmp/tmux-1/default", r.stdout)
        self.assertNotIn("no open projects", r.stdout)

    def test_unknown_token_dir_falls_back_to_local(self):
        # main() runs in this process: point it (not just self.env) at a token dir with no token, never the user's live board
        with mock.patch.dict(os.environ, {"TMUX_DASH_STATE": str(self.state / "none")}), \
             mock.patch.object(overview, "local_overview", return_value={"projects": [], "events": [], "source": "local"}) as m:
            self.assertEqual(overview.main([]), 0)
            self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
