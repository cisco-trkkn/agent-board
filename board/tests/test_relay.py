import io
import os
import shlex
import shutil
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paneclass  # noqa: E402
import relay  # noqa: E402

SEP = paneclass.SEP


class FakeTmux:
    root = str(Path(tempfile.gettempdir()).resolve())  # an existing non-git dir

    def __init__(self):
        self.calls = []

    def __call__(self, *a, check=False):
        self.calls.append(a)
        if a[0] == "list-windows":
            return f"shell{SEP}2\nclaude{SEP}1\n"
        if a[0] == "list-panes":
            return "%5\n"
        if a[0] == "display":
            return self.root + "\n"
        return ""

    def names(self):
        return [c[0] for c in self.calls]


class RootTmux:
    """tmux stub for session_root: pane_current_path per pane id, session_path per session."""

    def __init__(self, panes, session_path="", active_path=""):
        self.panes, self.session_path, self.active_path = panes, session_path, active_path

    def __call__(self, *a, check=False):
        if a[0] == "list-windows":
            return f"shell{SEP}2\nclaude{SEP}1\n"
        if a[0] == "list-panes":
            return "%5\n"
        if a[0] == "display":
            target, fmt = a[-2], a[-1]
            if fmt == "#{session_path}":
                return self.session_path + "\n"
            if fmt == "#{pane_current_path}":
                return (self.panes[target] if target in self.panes else self.active_path) + "\n"
        return ""


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def statuses(*seq):
    return mock.patch.object(paneclass, "pane_status", side_effect=[("claude", s) for s in seq])


class WaitTest(unittest.TestCase):
    def test_needs_two_in_a_row(self):
        sleeps = []
        with statuses("working", "ready", "working", "ready", "ready"):
            self.assertTrue(relay.wait_turn_end(FakeTmux(), "%5", sleep=sleeps.append))
        self.assertEqual(len(sleeps), 4)

    def test_times_out(self):
        clock = iter(range(0, 1000, 2))
        with statuses(*["working"] * 100):
            ok = relay.wait_turn_end(FakeTmux(), "%5", cap=10, sleep=lambda s: None, clock=lambda: next(clock))
        self.assertFalse(ok)


class SessionRootTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "i")
        self.wt = self.repo / ".claude" / "worktrees" / "w1"
        git(self.repo, "worktree", "add", "-q", str(self.wt), "-b", "w1")
        self.plain = self.tmp / "plain"
        self.plain.mkdir()

    def root(self, tmux, **kw):
        return relay.session_root(tmux, "proj", **kw)

    def test_session_path_wins_over_pane_path(self):
        # the lead cd'd into a repo; the project is rooted at the session's start dir
        tmux = RootTmux({"%5": str(self.repo)}, session_path=str(self.plain))
        self.assertEqual(self.root(tmux), str(self.plain))

    def test_pane_path_ignored_for_active_window_too(self):
        tmux = RootTmux({"%5": str(self.wt)}, session_path=str(self.plain), active_path=str(self.repo))
        self.assertEqual(self.root(tmux), str(self.plain))

    def test_session_path_in_live_worktree_resolves_to_main_checkout(self):
        self.assertEqual(self.root(RootTmux({}, session_path=str(self.wt))), str(self.repo))

    def test_deleted_worktree_session_path_falls_back_to_home(self):
        git(self.repo, "worktree", "remove", "--force", str(self.wt))
        with mock.patch.dict(os.environ, {"HOME": str(self.plain)}):
            self.assertEqual(self.root(RootTmux({"%5": str(self.repo)}, session_path=str(self.wt))), str(self.plain))

    def test_session_subdir_resolves_to_main_checkout(self):
        self.assertEqual(self.root(RootTmux({}, session_path=str(self.repo / ".claude"))), str(self.repo))

    def test_session_path_that_is_a_git_repo_is_returned_unchanged(self):
        # a project rooted at $HOME which is itself a repo
        self.assertEqual(self.root(RootTmux({"%5": str(self.plain)}, session_path=str(self.repo))), str(self.repo))

    def test_non_git_session_path_is_returned_as_is(self):
        self.assertEqual(self.root(RootTmux({}, session_path=str(self.plain))), str(self.plain))

    def test_nothing_usable_falls_back_to_home(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.plain)}):
            self.assertEqual(self.root(RootTmux({"%5": "/gone"}, session_path="")), str(self.plain))


TMUX_BIN = os.path.expanduser("~/.local/bin/tmux") if os.access(os.path.expanduser("~/.local/bin/tmux"), os.X_OK) else shutil.which("tmux")


@unittest.skipUnless(TMUX_BIN, "no tmux")
class RealTmuxSessionRootTest(unittest.TestCase):
    """session_root against a real scratch tmux server: the lead's pane moves, the session path stays."""

    def test_pane_cd_does_not_move_the_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        a, b = Path(tmp.name).resolve() / "A", Path(tmp.name).resolve() / "B"
        a.mkdir()
        b.mkdir()
        sock = f"relay-root-{os.getpid()}"

        def tmux(*args, check=False):
            r = subprocess.run([TMUX_BIN, "-L", sock, "-f", "/dev/null", *args], capture_output=True, text=True)
            if check and r.returncode:
                raise RuntimeError(r.stderr)
            return r.stdout

        self.addCleanup(lambda: tmux("kill-server"))
        # the pane process cd's like a lead does, then stays alive
        tmux("new-session", "-d", "-s", "proj", "-n", "claude", "-c", str(a), f"cd {b} && exec sleep 60", check=True)
        pane = tmux("list-panes", "-t", "=proj:claude", "-F", "#{pane_id}").split()[0]
        for _ in range(50):
            if tmux("display", "-p", "-t", pane, "#{pane_current_path}").strip() == str(b):
                break
            time.sleep(0.1)
        self.assertEqual(tmux("display", "-p", "-t", pane, "#{pane_current_path}").strip(), str(b))  # really diverged
        self.assertEqual(relay.session_root(tmux, "proj"), str(a))


class RelayTest(unittest.TestCase):
    def test_relay_respawns_and_writes_lineage(self):
        fake = FakeTmux()
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as ld, statuses("idle", "idle"), \
                mock.patch.dict(os.environ, {"TC_LINEAGE": ld}):
            msg = relay.relay(fake, "proj", "/d.md", d, "OLD1", sleep=lambda s: None)
            lines = (Path(ld) / "proj.jsonl").read_text().splitlines()
            self.assertFalse((Path(d) / "lineage-proj.jsonl").exists())   # state_dir no longer decides the path
        self.assertIn("relayed", msg)
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual((rec["old_session_id"], rec["doc"], rec["pane"]), ("OLD1", "/d.md", "%5"))
        rp = [c for c in fake.calls if c[0] == "respawn-pane"]
        sk = [c for c in fake.calls if c[0] == "send-keys"]
        self.assertEqual(rp[0], ("respawn-pane", "-k", "-t", "%5", "-c", fake.root))
        self.assertEqual(sk[0], ("send-keys", "-t", "%5", "-l", "--",
                                 shlex.quote(relay.orchestrator()) + " 'Read /d.md and continue from where the previous session left off.'"))
        self.assertEqual(sk[1], ("send-keys", "-t", "%5", "Enter"))
        # the session flags come from claude-orchestrator itself, never from the typed text
        self.assertNotIn("--settings", sk[0][-1])
        self.assertTrue(sk[0][-1].startswith(shlex.quote(relay.orchestrator()) + " "))
        self.assertLess(fake.names().index("respawn-pane"), fake.names().index("send-keys"))

    def test_busy_leaves_pane_alone(self):
        fake = FakeTmux()
        clock = iter(range(0, 1000, 2))
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as ld, statuses(*["working"] * 100), \
                mock.patch.dict(os.environ, {"TC_LINEAGE": ld}):
            with self.assertRaises(RuntimeError):
                relay.relay(fake, "proj", "/d.md", d, "", cap=6, sleep=lambda s: None, clock=lambda: next(clock))
            self.assertFalse((Path(ld) / "proj.jsonl").exists())
        self.assertNotIn("respawn-pane", fake.names())

    def test_main_failure_prints_manual_command(self):
        err = io.StringIO()
        with mock.patch.object(relay, "relay", side_effect=RuntimeError("boom")), redirect_stderr(err):
            rc = relay.main(["--session", "proj", "--doc", "/d.md", "--state", "/tmp"])
        self.assertEqual(rc, 1)
        self.assertIn(shlex.quote(relay.orchestrator()) + " 'Read /d.md", err.getvalue())


if __name__ == "__main__":
    unittest.main()
