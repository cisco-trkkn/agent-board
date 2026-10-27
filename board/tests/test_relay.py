import io
import os
import shlex
import json
import subprocess
import sys
import tempfile
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

    def test_live_worktree_resolves_to_main_checkout(self):
        self.assertEqual(self.root(RootTmux({"%5": str(self.wt)})), str(self.repo))

    def test_deleted_worktree_falls_back_to_session_path(self):
        git(self.repo, "worktree", "remove", "--force", str(self.wt))
        self.assertEqual(self.root(RootTmux({"%5": str(self.wt)}, session_path=str(self.repo))), str(self.repo))

    def test_empty_pane_path_uses_session_path(self):
        self.assertEqual(self.root(RootTmux({"%5": ""}, session_path=str(self.repo / ".claude"))), str(self.repo))

    def test_non_git_dir_is_returned_as_is(self):
        self.assertEqual(self.root(RootTmux({"%5": str(self.plain)})), str(self.plain))

    def test_uses_claude_pane_not_active_window(self):
        tmux = RootTmux({"%5": str(self.wt)}, active_path=str(self.plain))
        self.assertEqual(self.root(tmux), str(self.repo))

    def test_nothing_usable_falls_back_to_home(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.plain)}):
            self.assertEqual(self.root(RootTmux({"%5": "/gone"}, session_path="")), str(self.plain))


class RelayTest(unittest.TestCase):
    def test_relay_respawns_and_writes_lineage(self):
        fake = FakeTmux()
        with tempfile.TemporaryDirectory() as d, statuses("idle", "idle"):
            msg = relay.relay(fake, "proj", "/d.md", d, "OLD1", sleep=lambda s: None)
            lines = (Path(d) / "lineage-proj.jsonl").read_text().splitlines()
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
        with tempfile.TemporaryDirectory() as d, statuses(*["working"] * 100):
            with self.assertRaises(RuntimeError):
                relay.relay(fake, "proj", "/d.md", d, "", cap=6, sleep=lambda s: None, clock=lambda: next(clock))
            self.assertFalse((Path(d) / "lineage-proj.jsonl").exists())
        self.assertNotIn("respawn-pane", fake.names())

    def test_main_failure_prints_manual_command(self):
        err = io.StringIO()
        with mock.patch.object(relay, "relay", side_effect=RuntimeError("boom")), redirect_stderr(err):
            rc = relay.main(["--session", "proj", "--doc", "/d.md", "--state", "/tmp"])
        self.assertEqual(rc, 1)
        self.assertIn(shlex.quote(relay.orchestrator()) + " 'Read /d.md", err.getvalue())


if __name__ == "__main__":
    unittest.main()
