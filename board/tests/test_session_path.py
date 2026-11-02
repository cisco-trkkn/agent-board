"""session_path returns the project's main checkout, not the lead pane's cwd (which follows the lead's cd into a worktree).

Runs against a scratch tmux server (-L <sock> -f /dev/null); server.TMUX points at it and cleanup kills it.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

BOARD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOARD))
import paneclass  # noqa: E402

REAL_TMUX = os.environ.get("TC_REAL_TMUX") or paneclass.tmux_bin()


class SessionPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sesspath-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        g = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "init"], check=True)
        self.wt = self.repo / ".claude" / "worktrees" / "wt"
        subprocess.run(g + ["worktree", "add", "-q", str(self.wt), "-b", "wt"], check=True)
        self.sock = f"sesspath-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.real = [REAL_TMUX, "-L", self.sock, "-f", "/dev/null"]
        self.addCleanup(self._kill)
        self.env = {"TMUX_DASH_TMUX_ARGS": f"-L {self.sock} -f /dev/null", "TC_STATE": str(self.tmp / "state")}
        (self.tmp / "state").mkdir()
        saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.addCleanup(self._restore, saved)
        spec = importlib.util.spec_from_file_location("tmux_dash_server_sesspath", BOARD / "server.py")
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.server.RELOAD_EVERY = 10 ** 9
        # start path = the repo; the pane's process then cd's into the worktree, as the lead's cd does
        subprocess.run(self.real + ["new-session", "-d", "-s", "proj", "-x", "200", "-y", "50", "-c", str(self.repo),
                                    f"cd {self.wt} && exec sleep 600"], check=True, capture_output=True)
        deadline = time.time() + 10
        while time.time() < deadline:
            cur = subprocess.run(self.real + ["display", "-p", "-t", "=proj:", "#{pane_current_path}"],
                                 capture_output=True, text=True).stdout.strip()
            if Path(cur).resolve() == self.wt.resolve():
                break
            time.sleep(0.1)
        else:
            self.fail(f"pane never reached the worktree: {cur!r}")

    def _kill(self):
        r = subprocess.run(self.real + ["display", "-p", "#{socket_path}"], capture_output=True, text=True)
        subprocess.run(self.real + ["kill-server"], capture_output=True)
        if r.stdout.strip():
            Path(r.stdout.strip()).unlink(missing_ok=True)

    def _restore(self, saved):
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_session_path_is_the_repo(self):
        self.assertEqual(Path(self.server.session_path("proj")).resolve(), self.repo.resolve())

    def test_missing_session_raises(self):
        with self.assertRaises(RuntimeError) as cm:
            self.server.session_path("nope")
        self.assertEqual(str(cm.exception), "no session 'nope'")

    def test_agent_name_looks_in_the_repo_worktrees(self):
        # task "wt": the repo's .claude/worktrees/wt is taken, so the name must get a suffix
        self.assertEqual(self.server.agent_name("proj", "wt"), "wt-2")

    def test_agent_action_runs_tmux_ctl_in_the_repo(self):
        seen = {}
        self.server.run_script = lambda args, cwd=None, extra_env=None, timeout=30: seen.update(cwd=cwd, args=args) or "ok"
        self.server._act({"action": "agent", "session": "proj", "name": "x", "task": "do it"})
        self.assertEqual(Path(seen["cwd"]).resolve(), self.repo.resolve())

    def test_session_worktree_lists_from_the_repo(self):
        seen = []
        real = self.server.worktrees
        self.server.worktrees = lambda path: seen.append(path) or real(path)
        out = self.server.session_worktree("proj", str(self.wt))
        self.assertEqual([Path(p).resolve() for p in seen], [self.repo.resolve()])
        self.assertEqual(Path(out["repo"]).resolve(), self.repo.resolve())


if __name__ == "__main__":
    unittest.main()
