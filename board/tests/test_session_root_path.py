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
        with mock.patch.object(relay, "_git_root", wraps=relay._git_root) as mc:
            relay.root_for(str(self.r.repo)); relay.root_for(str(self.r.repo))
        self.assertEqual(mc.call_count, 1)

def commit(cwd):
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i", cwd=cwd)


class HomeGuardTest(unittest.TestCase):
    """~ is itself a git repo: a plain folder under it must not resolve to ~ (bin/dev's rule)."""
    def setUp(self):
        relay._roots.clear()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(os.path.realpath(self.tmp.name))
        self.home = base / "home"; self.home.mkdir()
        git("init", "-q", cwd=self.home); commit(self.home)
        p = mock.patch.dict(os.environ, {"HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        self.base = base

    def test_plain_child_of_home_repo_is_itself(self):   # mutation: remove the guard -> home
        child = self.home / "newproj"; child.mkdir()
        self.assertEqual(relay.main_checkout(str(child)), str(child))
        self.assertEqual(relay.root_for(str(child)), str(child))

    def test_home_is_home(self):
        self.assertEqual(relay.main_checkout(str(self.home)), str(self.home))

    def test_plain_child_of_other_repo_is_that_repo(self):
        other = self.base / "other"; other.mkdir(); git("init", "-q", cwd=other)
        child = other / "sub"; child.mkdir()
        self.assertEqual(relay.main_checkout(str(child)), str(other))

    def test_linked_worktree_of_home_repo_is_home(self):   # mutation: compare common-dir parent, not toplevel -> worktree
        wt = self.base / "hw"
        git("worktree", "add", "-q", str(wt), cwd=self.home)
        self.assertEqual(relay.main_checkout(str(wt)), str(self.home))

    def test_symlinked_home_still_guards(self):
        link = self.base / "homelink"; link.symlink_to(self.home)
        child = self.home / "np"; child.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(link)}):
            self.assertEqual(relay.main_checkout(str(link / "np")), str(link / "np"))


class StaleCacheTest(unittest.TestCase):
    def setUp(self):
        relay._roots.clear()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(os.path.realpath(self.tmp.name))
        self.home = base / "home"; self.home.mkdir()
        self.parent = base / "parent"; self.parent.mkdir(); git("init", "-q", cwd=self.parent)
        self.child = self.parent / "newproj"; self.child.mkdir()
        p = mock.patch.dict(os.environ, {"HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)

    def test_git_init_after_first_lookup_takes_effect(self):   # mutation: no .git staleness check -> parent
        self.assertEqual(relay.root_for(str(self.child)), str(self.parent))
        git("init", "-q", cwd=self.child)
        self.assertEqual(relay.root_for(str(self.child)), str(self.child))

    def test_session_root_sees_git_init(self):
        tm = lambda *a, **k: str(self.child) + "\n"
        self.assertEqual(relay.session_root(tm, "s"), str(self.parent))
        git("init", "-q", cwd=self.child)
        self.assertEqual(relay.session_root(tm, "s"), str(self.child))


class GitFailureTest(unittest.TestCase):
    def setUp(self):
        relay._roots.clear()
        self.r = Repo(); self.addCleanup(self.r.tmp.cleanup)
        self.home = tempfile.TemporaryDirectory(); self.addCleanup(self.home.cleanup)
        p = mock.patch.dict(os.environ, {"HOME": self.home.name}); p.start(); self.addCleanup(p.stop)

    def failing(self, exc):
        return mock.patch.object(relay.subprocess, "run", side_effect=exc)

    def test_git_missing_or_hung_returns_d_and_is_not_cached(self):   # mutation: drop the except -> raises
        d = str(self.r.repo)
        for exc in (FileNotFoundError("git"), subprocess.TimeoutExpired("git", 10)):
            with self.subTest(exc=type(exc).__name__), self.failing(exc):
                relay._roots.clear()
                self.assertEqual(relay.main_checkout(d), d)
                self.assertEqual(relay.root_for(d), d)
                self.assertNotIn(d, relay._roots)

    def test_build_state_survives_git_failing(self):
        S = server.SEP
        row = S.join(["proj", "1", "1", "claude", "0", "", "0", "%1", "t", "zsh", "/e", "1", "1", "", "", str(self.r.repo)])
        with mock.patch.object(server, "INDEXER", None), mock.patch.object(server, "tmux", return_value=row), \
             mock.patch.object(server, "pane_text", return_value=[]), mock.patch.object(server, "cached_worktrees", return_value=[]), \
             self.failing(FileNotFoundError("git")):
            sessions = server.build_state()["sessions"]
        self.assertEqual(sessions[0]["path"], str(self.r.repo))

    def test_retry_after_failure_returns_real_root(self):
        with self.failing(FileNotFoundError("git")):
            self.assertEqual(relay.root_for(str(self.r.wt)), str(self.r.wt))
        self.assertEqual(relay.root_for(str(self.r.wt)), str(self.r.repo))

    def test_not_a_repo_is_cached(self):
        plain = Path(self.home.name) / "plain"; plain.mkdir()
        relay.root_for(str(plain))
        self.assertIn(str(plain), relay._roots)


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
