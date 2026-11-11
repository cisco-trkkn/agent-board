"""Fixtures shared by test_worktree_board*.py: the board server module, BoardBase, add_worktree, Fake."""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree_fixtures import WITH_START, git, glab_stub, make_repo, tmux_stub  # noqa: E402,F401  (WITH_START, git: re-exported)
from worktree_fixtures import add_worktree as _add_worktree  # noqa: E402


def add_worktree(repo, name, **kw):
    # the board classifies on the wall clock, so date fixtures from it, not from the engine tests' fixed NOW
    return _add_worktree(repo, name, now=datetime.now(timezone.utc), **kw)

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
SERVER = Path(__file__).resolve().parent.parent / "server.py"
spec = importlib.util.spec_from_file_location("tmux_dash_server_wtboard", SERVER)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
SEP = server.SEP


class BoardBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = make_repo(self.tmp)
        self.bin = Path(self.tmp) / "stubs"
        self.bin.mkdir()
        self.state = Path(self.tmp) / "state"
        self.marker = Path(self.tmp) / "glab-called"
        patcher = mock.patch.dict(os.environ, {
            "AW_TMUX": tmux_stub(self.bin / "tmux"), "AW_STATE_DIR": str(self.state),
            "AW_GLAB": glab_stub(self.bin / "glab", "0" * 40, marker=self.marker)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.procs = []
        server.forget_worktrees()

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def listed(self, name):
        # match worktree dir names, not the whole output: a random temp dir in the repo path can contain `name`
        out = git("worktree", "list", "--porcelain", cwd=self.repo).stdout
        return name in {Path(l[len("worktree "):]).name for l in out.splitlines() if l.startswith("worktree ")}

    def item(self, name):
        return next(i for i in server.worktrees(str(self.repo))["items"] if i["name"] == name)


class Fake:
    def __init__(self, wt_path, pane_pids=(), on_kill=None):
        self.wt_path, self.calls, self.pane_pids, self.on_kill = wt_path, [], pane_pids, on_kill

    def tmux(self, *args, check=False):
        self.calls.append(args)
        if args[0] == "list-windows":
            return f"@4{SEP}fix-login{SEP}1{SEP}\n"
        if args[0] == "display-message":
            return self.wt_path + "\n"
        if args[0] == "list-panes":
            return "".join(f"{p}\n" for p in self.pane_pids)
        if args[0] == "kill-window" and self.on_kill:
            self.on_kill()
        return ""

