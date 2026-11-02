import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import relay, server


def git(*a, cwd):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


class Repo:
    """A scratch git repo with one worktree under .claude/worktrees/w."""
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(os.path.realpath(self.tmp.name)) / "proj"
        self.repo.mkdir()
        git("init", "-q", cwd=self.repo)
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i", cwd=self.repo)
        self.wt = self.repo / ".claude" / "worktrees" / "w"
        git("worktree", "add", "-q", str(self.wt), cwd=self.repo)


class RootForTest(unittest.TestCase):
    def setUp(self):
        relay._roots.clear()
        self.r = Repo(); self.addCleanup(self.r.tmp.cleanup)
        self.home = tempfile.TemporaryDirectory(); self.addCleanup(self.home.cleanup)

    def test_repo_is_its_own_root(self):
        self.assertEqual(relay.root_for(str(self.r.repo)), str(self.r.repo))

    def test_worktree_maps_to_main_checkout(self):
        self.assertEqual(relay.root_for(str(self.r.wt)), str(self.r.repo))

    def test_missing_or_empty_falls_back_to_home(self):
        with mock.patch.dict(os.environ, {"HOME": self.home.name}):
            self.assertEqual(relay.root_for(str(self.r.repo / "gone")), self.home.name)
            self.assertEqual(relay.root_for(""), self.home.name)

    def test_cached_per_start_path(self):   # mutation: drop the cache -> called twice
        with mock.patch.object(relay, "main_checkout", wraps=relay.main_checkout) as mc:
            relay.root_for(str(self.r.repo)); relay.root_for(str(self.r.repo))
        self.assertEqual(mc.call_count, 1)


class RootedBase(unittest.TestCase):
    def setUp(self):
        relay._roots.clear()
        self.r = Repo(); self.addCleanup(self.r.tmp.cleanup)
        self.home = tempfile.TemporaryDirectory(); self.addCleanup(self.home.cleanup)
        p = mock.patch.dict(os.environ, {"HOME": self.home.name}); p.start(); self.addCleanup(p.stop)


class BuildStateRootTest(RootedBase):
    def state(self, start):
        S = server.SEP
        row = S.join(["proj", "1", "1", "claude", "0", "", "0", "%1", "t", "zsh", "/elsewhere", "1", "1", "", "", start])
        with mock.patch.object(server, "INDEXER", None), mock.patch.object(server, "tmux", return_value=row), \
             mock.patch.object(server, "pane_text", return_value=[]), mock.patch.object(server, "cached_worktrees", return_value=[]):
            return server.build_state()["sessions"][0]

    def test_path_is_start_folder_root_pane_path_unchanged(self):
        s = self.state(str(self.r.repo))
        # mutation: restore `if s["path"] is None or widx == "1": s["path"] = path` -> "/elsewhere"
        self.assertEqual(s["path"], str(self.r.repo))
        self.assertEqual(s["windows"][0]["panes"][0]["path"], "/elsewhere")

    def test_worktree_start_maps_to_main_checkout(self):
        self.assertEqual(self.state(str(self.r.wt))["path"], str(self.r.repo))

    def test_removed_or_empty_start_is_home(self):
        self.assertEqual(self.state(str(self.r.repo / "gone"))["path"], self.home.name)
        self.assertEqual(self.state("")["path"], self.home.name)


class LabelTargetsRootTest(RootedBase):
    def targets(self, start):
        row = server.SEP.join(["p", "1", "claude", "", "", "", "%1", "/elsewhere", "", start])
        return server.label_targets(run=lambda *a, **k: row)[0]

    def test_path_is_start_folder_root(self):
        s = self.targets(str(self.r.repo))
        self.assertEqual(s["path"], str(self.r.repo))
        self.assertEqual(s["windows"][0]["panes"][0]["path"], "/elsewhere")

    def test_worktree_start_maps_to_main_checkout(self):
        self.assertEqual(self.targets(str(self.r.wt))["path"], str(self.r.repo))

    def test_removed_or_empty_start_is_home(self):
        self.assertEqual(self.targets(str(self.r.repo / "gone"))["path"], self.home.name)
        self.assertEqual(self.targets("")["path"], self.home.name)


if __name__ == "__main__":
    unittest.main()
