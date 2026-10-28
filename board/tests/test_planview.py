import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import planview  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "planview"
SID1 = "11111111-1111-1111-1111-111111111111"
SID2 = "22222222-2222-2222-2222-222222222222"


def fake_tmux(claude_pane="@80.%82", windows=(("claude", "%82"), ("✦ parse", "%90")), status=None, group=""):
    status = status or {}

    def run(*args, check=False):
        if args[0] == "display" and "session_group" in args[-1]:
            return (group or "proj") + "\n"
        if args[0] == "display" and "#{window_id}.#{pane_id}" in args[-1]:
            return claude_pane + "\n"
        if args[0] == "list-windows":
            return "".join(f"{n}\t{p}\n" for n, p in windows)
        raise AssertionError(args)
    run.status = status
    return run


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        self.home = self.root / "home"
        self.repo = self.root / "repo"
        self.state = self.root / "state"
        shutil.copytree(FIX / "sessions", self.home / "sessions")
        shutil.copytree(FIX / "tasks", self.home / "tasks")
        shutil.copytree(FIX / "repo", self.repo)
        p = mock.patch("planview.pane_state", return_value="working")  # no capture-pane is faked
        p.start()
        self.addCleanup(p.stop)
        self.state.mkdir()
        shutil.copy(FIX / "artifacts-proj.jsonl", self.state / "artifacts-proj.jsonl")

    def view(self, tmux=None, session="proj"):
        return planview.view(session, self.repo, self.home, self.state, tmux or fake_tmux())

    def put_task(self, sid8, n, **kw):
        d = self.home / "tasks" / f"session-{sid8}"
        t = {"id": str(n), "subject": f"T{n}", "status": "pending", "owner": "", "blockedBy": [], "blocks": []}
        t.update(kw)
        (d / f"{n}.json").write_text(json.dumps(t))

    def clear_tasks(self, sid8):
        for f in (self.home / "tasks" / f"session-{sid8}").glob("*.json"):
            f.unlink()

    def write_manifest(self, lines):
        (self.state / "artifacts-proj.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines))


class TestPlanview(Base):
    def test_lead_matched_by_claude_pane(self):
        v = self.view()
        self.assertEqual([t["subject"] for t in v["tasks"]][0], "Task 1: x")
        self.assertEqual(len(v["tasks"]), 3)
        self.assertTrue(v["active"])
        v2 = self.view(fake_tmux(claude_pane="@81.%83"))
        self.assertEqual([t["subject"] for t in v2["tasks"]], ["decoy"])

    def test_tasks_sorted_numerically(self):
        self.clear_tasks("11111111")
        for n in (2, 10, 1):
            self.put_task("11111111", n)
        self.assertEqual([t["id"] for t in self.view()["tasks"]], ["1", "2", "10"])

    def test_pending_with_open_blocker_is_blocked(self):
        self.clear_tasks("11111111")
        self.put_task("11111111", 1, status="in_progress")
        self.put_task("11111111", 2, blockedBy=["1"])
        self.assertEqual([t["status"] for t in self.view()["tasks"]], ["in_progress", "blocked"])

    def test_pending_with_done_blocker_is_pending(self):
        self.clear_tasks("11111111")
        self.put_task("11111111", 1, status="completed")
        self.put_task("11111111", 2, blockedBy=["1"])
        self.assertEqual([t["status"] for t in self.view()["tasks"]], ["completed", "pending"])

    def test_owner_state_mapping(self):
        self.clear_tasks("11111111")
        wins = (("claude", "%82"), ("✦ a", "%90"), ("✦ b", "%91"), ("✦ c", "%92"))
        for n, o in enumerate("abcd", 1):
            self.put_task("11111111", n, owner=o)
        side = {"%90": "working", "%91": "waiting", "%92": "ready"}
        with mock.patch("planview.pane_state", side_effect=lambda t, p: side[p]):
            v = self.view(fake_tmux(windows=wins))
        self.assertEqual([t["state"] for t in v["tasks"]], ["working", "waiting", "ready", "gone"])

    def test_unowned_task_has_empty_state(self):
        self.clear_tasks("11111111")
        self.put_task("11111111", 1)
        self.assertEqual(self.view()["tasks"][0]["state"], "")

    def test_name_from_newest_plan_line_of_this_lead(self):
        base = {"kind": "plan", "session_id": SID1}
        self.write_manifest([
            dict(base, ts=1, path="/p/a-old.md"),
            dict(base, ts=2, path="/p/b-new.md"),
            dict(base, ts=3, path="/p/c.md", session_id=SID2),
            {"ts": 4, "path": "/p/mark.md", "session_id": SID1},
        ])
        self.assertEqual(self.view()["name"], "b-new")

    def test_empty_live_list_falls_back_to_tasks_json(self):
        self.clear_tasks("11111111")
        v = self.view()
        self.assertEqual(v["name"], "2026-01-01-demo")
        self.assertFalse(v["active"])
        self.assertEqual([t["id"] for t in v["tasks"]], ["1", "2", "3"])
        self.assertEqual(v["tasks"][1]["status"], "completed")

    def test_no_plan_line_falls_back_to_newest_repo_tasks_json(self):
        self.clear_tasks("11111111")
        self.write_manifest([])
        d = self.repo / "docs/superpowers/plans"
        (d / "2026-02-02-newer.md.tasks.json").write_text(json.dumps({"tasks": [{"id": 7, "subject": "n", "status": "pending"}]}))
        import os
        os.utime(d / "2026-01-01-demo.md.tasks.json", (1, 1))
        v = self.view()
        self.assertEqual((v["name"], v["active"], [t["id"] for t in v["tasks"]]), ("2026-02-02-newer", False, ["7"]))

    def test_nothing_gives_empty_view(self):
        empty = {"name": "", "active": False, "tasks": []}
        shutil.rmtree(self.repo)
        shutil.rmtree(self.home)
        self.assertEqual(self.view(), empty)

    def test_missing_home_and_bad_json_do_not_raise(self):
        for f in (self.home / "tasks" / "session-11111111").glob("*.json"):
            f.write_text("{bad")
        (self.home / "sessions" / "1002.json").write_text("not json")
        (self.state / "artifacts-proj.jsonl").write_text("{bad\n")
        (self.repo / "docs/superpowers/plans/2026-01-01-demo.md.tasks.json").write_text("[")
        self.assertEqual(self.view()["tasks"], [])

    def test_tmux_raising_falls_back_to_newest_repo_tasks_json(self):
        def boom(*a, **k):
            raise RuntimeError("no tmux")
        for tmux in (boom, lambda *a, **k: ""):
            v = self.view(tmux)
            self.assertEqual((v["name"], v["active"], [t["id"] for t in v["tasks"]]), ("2026-01-01-demo", False, ["1", "2", "3"]))
            self.assertEqual({t["state"] for t in v["tasks"]}, {""})

    def test_tmux_raising_and_no_repo_gives_empty_view(self):
        def boom(*a, **k):
            raise RuntimeError("no tmux")
        shutil.rmtree(self.repo)
        self.assertEqual(self.view(boom), {"name": "", "active": False, "tasks": []})

    def test_no_matching_lead_falls_back_to_repo_tasks_json(self):
        v = self.view(fake_tmux(claude_pane="@99.%99"))
        self.assertEqual((v["name"], v["active"], len(v["tasks"])), ("2026-01-01-demo", False, 3))

    def test_manifest_keyed_by_session_group(self):
        (self.state / "artifacts-proj.jsonl").unlink()
        (self.state / "artifacts-grp.jsonl").write_text(json.dumps({"kind": "plan", "session_id": SID1, "ts": 1, "path": "/p/zz-grp.md"}) + "\n")
        for grp in ("grp", "grp-bg"):
            self.assertEqual(self.view(fake_tmux(group=grp), session="_web-1")["name"], "zz-grp", grp)

    def test_group_lookup_failure_uses_session_name(self):
        (self.state / "artifacts-proj.jsonl").write_text(json.dumps({"kind": "plan", "session_id": SID1, "ts": 1, "path": "/p/zz-own.md"}) + "\n")
        base = fake_tmux()

        def tmux(*args, check=False):
            if "session_group" in args[-1]:
                raise RuntimeError("no")
            return base(*args)
        self.assertEqual(self.view(tmux)["name"], "zz-own")


def T(i, subject, status, owner="", state=""):
    return {"id": str(i), "subject": subject, "status": status, "owner": owner, "state": state}


ACTIVE = {"name": "demo", "active": True, "tasks": [
    T(1, "Parse", "completed", "parse", "ready"), T(2, "Build", "in_progress", "sift", "waiting"),
    T(3, "Ship", "pending"), T(4, "Wait", "blocked")]}
EMPTY_VIEW = {"name": "", "active": False, "tasks": []}


class TestRender(unittest.TestCase):
    def test_active_snapshot(self):
        self.assertEqual(planview.render(ACTIVE, 40, False), [
            "demo \u00b7 1/4 done", "\u2713 Parse", "\u25b6 Build \u2192 sift (waiting)", "\u00b7 Ship", "\u2717 Wait"])

    def test_long_subject_cut_keeps_owner_suffix(self):
        v = {"name": "d", "active": True, "tasks": [T(1, "x" * 60, "in_progress", "parse", "working")]}
        line = planview.render(v, 40, False)[1]
        self.assertLessEqual(len(line), 40)
        self.assertTrue(line.endswith("\u2192 parse (working)"), line)
        self.assertIn("\u2026", line)

    def test_wide_characters_count_two_columns(self):
        v = {"name": "d", "active": True, "tasks": [T(1, "\u4e2d" * 30, "pending")]}
        line = planview.render(v, 20, False)[1]
        self.assertLessEqual(planview.display_width(line), 20)
        self.assertIn("\u2026", line)

    def test_every_line_fits_narrow_width(self):
        for line in planview.render(ACTIVE, 8, False):
            self.assertLessEqual(planview.display_width(line), 8, line)

    def test_width_30_cuts_subject_before_owner_suffix(self):
        v = {"name": "d", "active": True, "tasks": [T(1, "y" * 50, "in_progress", "parse", "waiting")]}
        line = planview.render(v, 30, False)[1]
        self.assertTrue(line.endswith(" \u2192 parse (waiting)"), line)
        self.assertLessEqual(len(line), 30)
        self.assertIn("\u2026", line)
        red = planview.render(v, 30, True)[1]
        self.assertIn("\033[1;31m\u2192 parse (waiting)\033[0m", red)

    def test_width_30_cuts_name_before_header_counts(self):
        v = {"name": "n" * 40, "active": True, "tasks": [T(1, "a", "completed"), T(2, "b", "pending")]}
        head = planview.render(v, 30, False)[0]
        self.assertTrue(head.endswith(" \u00b7 1/2 done"), head)
        self.assertLessEqual(len(head), 30)
        self.assertIn("\u2026", head)

    def test_inactive_view(self):
        v = dict(ACTIVE, active=False)
        lines = planview.render(v, 40, False)
        self.assertEqual(lines[1], "no active plan")
        self.assertEqual(len(lines), 6)

    def test_empty_view(self):
        self.assertEqual(planview.render(EMPTY_VIEW, 40, True), ["no plans yet \u00b7 prefix S for a shell"])

    def test_color_waiting_bold_red_and_inactive_dim(self):
        lines = planview.render(ACTIVE, 60, True)
        self.assertIn("\033[1;31m\u2192 sift (waiting)\033[0m", lines[2])
        dim = planview.render(dict(ACTIVE, active=False), 60, True)
        self.assertTrue(dim[2].startswith("\033[2m"), dim[2])
        self.assertTrue(dim[2].endswith("\033[0m"))

    def test_no_color_has_no_escapes(self):
        for v in (ACTIVE, dict(ACTIVE, active=False), EMPTY_VIEW):
            self.assertNotIn("\033", "\n".join(planview.render(v, 40, False)))


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": os.environ["PATH"], "HOME": tmp, "TC_STATE": tmp, "TC_TMUX": "/nonexistent"}
            return subprocess.run([sys.executable, "-I", str(HERE / "planview.py"), *args, "--root", tmp],
                                  capture_output=True, text=True, env=env, timeout=20)

    def test_view_without_tmux_prints_empty_line(self):
        r = self.run_cli("view", "nosuch")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "no plans yet \u00b7 prefix S for a shell"), r.stderr)

    def test_view_json(self):
        r = self.run_cli("view", "nosuch", "--json")
        self.assertEqual(json.loads(r.stdout), EMPTY_VIEW)

    def test_watch_draws_once_and_exits_zero_on_sigint(self):
        import signal
        import time
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": os.environ["PATH"], "HOME": tmp, "TC_STATE": tmp, "TC_TMUX": "/nonexistent"}
            p = subprocess.Popen([sys.executable, "-I", str(HERE / "planview.py"), "watch", "nosuch", "--root", tmp],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            time.sleep(1.5)
            p.send_signal(signal.SIGINT)
            out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out.count("no plans yet"), 1)

    def test_watch_redraws_only_when_lines_change(self):
        views = [ACTIVE, ACTIVE, dict(ACTIVE, name="other"), dict(ACTIVE, name="other")]
        calls = []

        def sleep(_):
            calls.append(1)
            if len(calls) == len(views):
                raise KeyboardInterrupt
        out = io.StringIO()
        with mock.patch("planview._snapshot", side_effect=views), mock.patch("planview.time.sleep", sleep), \
                mock.patch("sys.stdout", out), self.assertRaises(KeyboardInterrupt):
            planview.watch("s", Path("."))
        self.assertEqual(out.getvalue().count("\033[H\033[2J"), 2)

    def test_tmux_plan_script_runs_watch(self):
        f = HERE.parent / "bin" / "tmux-plan"
        self.assertTrue(os.access(f, os.X_OK))
        self.assertIn('exec python3 -I "${0:A:h:h}/board/planview.py" watch "$1" --root "$2"', f.read_text())
        import signal
        import time
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": os.environ["PATH"], "HOME": tmp, "TC_STATE": tmp, "TC_TMUX": "/nonexistent"}
            p = subprocess.Popen([str(f), "nosuch", tmp], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            time.sleep(2)
            p.send_signal(signal.SIGINT)
            out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, err)
        self.assertIn("no plans yet \u00b7 prefix S for a shell", out)

    def test_positional_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-I", str(HERE / "planview.py"), "view", "nosuch", tmp],
                               capture_output=True, text=True, timeout=20)
        self.assertNotEqual(r.returncode, 0)


class TestPaneState(unittest.TestCase):
    def test_pane_state_maps_pane_status(self):
        for ret, want in ((("claude", "working"), "working"), (("claude", "waiting"), "waiting"),
                          (("claude", "ready"), "ready"), (("shell", "ready"), "ready")):
            with mock.patch("planview.paneclass.pane_status", return_value=ret):
                self.assertEqual(planview.pane_state(None, "%1"), want)

    def test_pane_state_error_is_ready(self):
        with mock.patch("planview.paneclass.pane_status", side_effect=RuntimeError):
            self.assertEqual(planview.pane_state(None, "%1"), "ready")


if __name__ == "__main__":
    unittest.main()
