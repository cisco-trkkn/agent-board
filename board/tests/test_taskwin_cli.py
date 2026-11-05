import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
                    taskwin.watch("proj", self.repo, self.home, interval=0, frames=frames)
            else:
                taskwin.watch("proj", self.repo, self.home, interval=0, frames=frames)
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

    def test_sigterm_handler_restores_cursor(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("time.sleep"), mock.patch("planview.view", side_effect=SystemExit(0)), \
                mock.patch("paneclass.tmux_runner", return_value=fake_tmux()):
            with self.assertRaises(SystemExit):
                taskwin.watch("proj", self.repo, self.home, interval=0, frames=5)
        self.assertTrue(out.getvalue().endswith("\x1b[?25h"))


if __name__ == "__main__":
    unittest.main()
