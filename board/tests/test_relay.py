import io
import json
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
    def __init__(self):
        self.calls = []

    def __call__(self, *a, check=False):
        self.calls.append(a)
        if a[0] == "list-windows":
            return f"shell{SEP}2\nclaude{SEP}1\n"
        if a[0] == "list-panes":
            return "%5\n"
        if a[0] == "display":
            return "/not/a/repo\n"
        return ""

    def names(self):
        return [c[0] for c in self.calls]


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
        self.assertEqual(rp[0], ("respawn-pane", "-k", "-t", "%5", "-c", "/not/a/repo"))
        self.assertEqual(sk[0], ("send-keys", "-t", "%5", "-l", "--",
                                 "claude-orchestrator 'Read /d.md and continue from where the previous session left off.'"))
        self.assertEqual(sk[1], ("send-keys", "-t", "%5", "Enter"))
        # the session flags come from claude-orchestrator itself, never from the typed text
        self.assertNotIn("--settings", sk[0][-1])
        self.assertTrue(sk[0][-1].startswith("claude-orchestrator "))
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
        self.assertIn("claude-orchestrator 'Read /d.md", err.getvalue())


if __name__ == "__main__":
    unittest.main()
