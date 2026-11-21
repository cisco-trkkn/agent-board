import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import taskwin  # noqa: E402
import taskwin_state  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_planview import FIX, SID1, fake_tmux  # noqa: E402

TASKWIN = HERE / "taskwin.py"


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        root = Path(self.td.name)
        self.home, self.repo, self.state = root / "home", root / "repo", root / "state"
        shutil.copytree(FIX / "sessions", self.home / "sessions")
        shutil.copytree(FIX / "tasks", self.home / "tasks")
        shutil.copytree(FIX / "repo", self.repo)
        self.state.mkdir()
        for name, val in (("TC_STATE", str(self.state)),):
            p = mock.patch.dict(os.environ, {name: val})
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("planview.pane_state", return_value="working")
        p.start()
        self.addCleanup(p.stop)


class TestRender(Base):
    def test_render_subcommand_prints_subjects_and_writes_no_state(self):
        env = {**os.environ, "TC_STATE": str(self.state), "NO_COLOR": "1"}
        r = subprocess.run([sys.executable, "-I", str(TASKWIN), "render", "--session", "nosuch",
                            "--root", str(self.repo), "--home", str(self.home), "--width", "100", "--height", "30"],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip(), "a frame is printed")
        self.assertFalse((self.state / "taskwin").exists())

    def test_render_with_real_lead_shows_subjects(self):
        out = io.StringIO()
        with mock.patch("paneclass.tmux_runner", return_value=fake_tmux()), redirect_stdout(out), \
                mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            rc = taskwin.main(["render", "--session", "proj", "--root", str(self.repo), "--home", str(self.home),
                               "--width", "100", "--height", "30"])
        self.assertEqual(rc, 0)
        self.assertIn("Task 1: x", out.getvalue())
        self.assertFalse((self.state / "taskwin").exists())


class TestWatch(Base):
    def run_watch(self, frames, view=None):
        out = io.StringIO()
        tmux = fake_tmux()
        with redirect_stdout(out), mock.patch("time.sleep"), mock.patch("paneclass.tmux_runner", return_value=tmux):
            if view:
                with mock.patch("planview.view", side_effect=view):
                    taskwin.watch("proj", self.repo, self.home, interval=0, frames=frames, stdin=io.StringIO())
            else:
                taskwin.watch("proj", self.repo, self.home, interval=0, frames=frames, stdin=io.StringIO())
        return out.getvalue()

    def test_watch_writes_state_and_brackets_cursor(self):
        out = self.run_watch(2)
        self.assertTrue(out.startswith("\x1b[?25l"))
        self.assertTrue(out.endswith("\x1b[?25h"))
        st = taskwin_state.load(taskwin_state.path_for(self.state, "proj"))
        self.assertEqual(st.get("lead"), SID1)
        self.assertIn("\x1b[K", out)
        self.assertIn("\x1b[J", out)

    def test_raising_view_restores_cursor_and_shows_error(self):
        import planview
        real = planview.view
        calls = []

        def view(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("boom")
            return real(*a, **k)
        out = self.run_watch(3, view=view)
        self.assertIn("boom", out)
        self.assertTrue(out.endswith("\x1b[?25h"))
        self.assertEqual(len(calls), 3, "the loop continued after the error")

    def one_task_view(self, name):
        return {"name": name, "active": True, "tasks": [
            {"id": "1", "subject": "only", "status": "pending", "owner": "", "state": "", "tier": "standard",
             "blockedBy": []}]}

    def test_load_tier_model_once_per_plan_name(self):
        names = iter(["a", "a", "b"])
        with mock.patch("taskwin.load_tier_model", wraps=taskwin.load_tier_model) as m:
            self.run_watch(3, view=lambda *a, **k: self.one_task_view(next(names)))
        self.assertEqual(m.call_count, 2)

    def test_frame_shows_routed_model(self):
        p = self.repo / "docs" / "superpowers"
        p.mkdir(parents=True, exist_ok=True)
        (p / "model-routing.json").write_text('{"standard": "opus"}')
        out = self.run_watch(1, view=lambda *a, **k: self.one_task_view("a"))
        self.assertIn("opus", out)
        self.assertNotIn("sonnet", out)

    def test_sigterm_handler_restores_cursor(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("time.sleep"), mock.patch("planview.view", side_effect=SystemExit(0)), \
                mock.patch("paneclass.tmux_runner", return_value=fake_tmux()):
            with self.assertRaises(SystemExit):
                taskwin.watch("proj", self.repo, self.home, interval=0, frames=5, stdin=io.StringIO())
        self.assertTrue(out.getvalue().endswith("\x1b[?25h"))


class TestWatchKeys(Base):
    """watch reads keys from a TTY in cbreak mode, redraws at once, keeps `ui` in the state file and restores the
    terminal on exit."""

    def pty(self):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        f = os.fdopen(slave, "r")
        self.addCleanup(f.close)
        return master, f

    def watch(self, frames, stdin, interval=0.05, view=None):
        out = io.StringIO()
        with contextlib.ExitStack() as es:
            es.enter_context(redirect_stdout(out))
            es.enter_context(mock.patch("paneclass.tmux_runner", return_value=fake_tmux()))
            if view:
                es.enter_context(mock.patch("planview.view", side_effect=view))
            taskwin.watch("proj", self.repo, self.home, interval=interval, frames=frames, stdin=stdin)
        return out.getvalue()

    def saved(self):
        return taskwin_state.load(taskwin_state.path_for(self.state, "proj"))

    def test_key_switches_view_and_is_kept(self):
        import termios
        master, f = self.pty()
        os.write(master, b"3")
        out = self.watch(3, f)
        self.assertEqual(self.saved()["ui"]["view"], "history")
        self.assertIn("[3 history]", taskwin.strip(out))
        lflag = termios.tcgetattr(f.fileno())[3]
        self.assertTrue(lflag & termios.ICANON and lflag & termios.ECHO, "terminal mode restored")

    def test_key_redraws_at_once(self):
        # remove the select wake-up (sleep the whole interval) -> this takes 30 s and fails
        master, f = self.pty()
        os.write(master, b"3")
        t0 = time.monotonic()
        self.watch(2, f, interval=30)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(self.saved()["ui"]["view"], "history")

    def test_arrow_moves_cursor(self):
        master, f = self.pty()
        os.write(master, b"2\x1b[B")
        self.watch(3, f)
        self.assertEqual(self.saved()["ui"]["cursor"]["plan"], 1)

    def test_eof_on_stdin_does_not_spin(self):
        r, w = os.pipe()
        os.close(w)                                  # a closed pipe: select says readable, read returns b""
        rf = os.fdopen(r, "r")
        self.addCleanup(rf.close)
        with mock.patch.object(rf, "isatty", return_value=True), mock.patch("termios.tcgetattr", return_value=[0] * 7), \
                mock.patch("termios.tcsetattr"), mock.patch("tty.setcbreak"), mock.patch("time.sleep") as sl:
            self.watch(4, rf)
        self.assertGreaterEqual(sl.call_count, 2, "after EOF the loop sleeps instead of selecting on stdin")

    def test_not_a_tty_sleeps_and_reads_no_keys(self):
        with mock.patch("time.sleep") as sl, mock.patch("tty.setcbreak") as cb:
            self.watch(2, io.StringIO())
        self.assertEqual(sl.call_count, 1)
        cb.assert_not_called()

    def test_journal_written_under_project_key(self):
        seq = iter(["in_progress", "completed"])

        def view(*a, **k):
            return {"name": "2026-11-21-x", "active": True, "tasks": [
                {"id": "1", "subject": "Task 1: x", "status": next(seq), "owner": "ann", "state": "", "tier": "mechanical",
                 "blockedBy": [], "outcome": "", "answeredAt": "", "planPath": ""}]}
        with mock.patch("time.sleep"):
            self.watch(2, io.StringIO(), view=view)
        j = taskwin_state.journal_path(self.state, "proj")
        lines = [json.loads(l) for l in j.read_text().splitlines()]
        self.assertEqual([(l["kind"], l["plan"], l["id"]) for l in lines], [("task_done", "2026-11-21-x", "1")])

    def test_failing_key_handler_keeps_the_window_alive(self):
        import termios
        master, f = self.pty()
        os.write(master, b"3")
        with mock.patch("taskwin_ui.handle_key", side_effect=RuntimeError("boom")):
            out = self.watch(3, f)
        self.assertIn("taskwin: boom", taskwin.strip(out))
        self.assertGreaterEqual(out.count("\x1b[H"), 3, "the remaining frames are still drawn")
        lflag = termios.tcgetattr(f.fileno())[3]
        self.assertTrue(lflag & termios.ICANON and lflag & termios.ECHO, "terminal mode restored")

    def test_tcgetattr_failure_means_no_key_mode(self):
        import termios
        master, f = self.pty()
        with mock.patch("termios.tcgetattr", side_effect=termios.error(25, "not a typewriter")), \
                mock.patch("tty.setcbreak") as cb, mock.patch("time.sleep") as sl:
            self.watch(2, f)
        cb.assert_not_called()
        self.assertEqual(sl.call_count, 1)


class TestTierModel(Base):
    def write(self, text):
        p = self.repo / "docs" / "superpowers"
        p.mkdir(parents=True, exist_ok=True)
        (p / "model-routing.json").write_text(text)

    def test_reads_string_values(self):
        self.write('{"mechanical": "haiku", "standard": "opus", "frontier": "inherit", "enforceEffort": true}')
        self.assertEqual(taskwin.load_tier_model(self.repo),
                         {"mechanical": "haiku", "standard": "opus", "frontier": "inherit"})

    def test_falls_back_per_tier(self):
        self.write('{"standard": 3, "frontier": "opus"}')
        self.assertEqual(taskwin.load_tier_model(self.repo),
                         {"mechanical": "haiku", "standard": "sonnet", "frontier": "opus"})

    def test_missing_malformed_and_non_dict_fall_back(self):
        self.assertEqual(taskwin.load_tier_model(self.repo / "nope"), taskwin.TIER_MODEL)
        for bad in ("{not json", "[1, 2]", ""):
            self.write(bad)
            self.assertEqual(taskwin.load_tier_model(self.repo), taskwin.TIER_MODEL, bad)


if __name__ == "__main__":
    unittest.main()
