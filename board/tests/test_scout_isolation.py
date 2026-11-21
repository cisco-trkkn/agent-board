"""scout: the isolation leak check. A poll, a weekly pass (fake model) and an approve click run with every env var on temp
dirs; the user's real scout dir, ideas files, discord outbox and this repo's refs must be exactly as they were. The real
paths are resolved at import, before any test patches HOME."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import test_scout_weekly as W  # noqa: E402
import scout_sources  # noqa: E402

REAL_HOME = Path(os.path.expanduser("~"))
REAL_SCOUT = REAL_HOME / ".local" / "state" / "agent-board" / "scout"
REAL_IDEAS = [REAL_HOME / ".local" / "state" / "agent-board" / "ideas" / "agent-board.md",
              REAL_HOME / ".claude" / "ideas" / "agent-board.md"]
REAL_OUTBOX = REAL_HOME / ".local" / "state" / "agent-board" / "discord" / "agent-board" / "outbox"
REPO = W.REPO


def _stat(p):
    try:
        s = p.stat()
        return (s.st_mtime_ns, s.st_size)
    except OSError:
        return None


def snapshot():
    """Every real path the scout could touch, as {label: state}: absent paths show as None."""
    snap = {}
    for root in (REAL_SCOUT, REAL_OUTBOX):
        snap[str(root)] = _stat(root)
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                snap[str(p)] = _stat(p)
    for p in REAL_IDEAS:
        snap[str(p)] = _stat(p)
    snap["git for-each-ref"] = subprocess.run(["git", "-C", str(REPO), "for-each-ref"], capture_output=True, text=True).stdout
    return snap


class IsolationTest(W.Base):
    def test_poll_weekly_and_approve_leave_the_real_state_alone(self):
        before = snapshot()
        self.poll_rss(W.SUN - 3600)                       # a real poll of the local RSS source
        self.plan(self.ok_plan())
        rc, out = self.run_scout("weekly")
        self.assertEqual(rc, 0, out)
        W.git(self.root, "commit", "-q", "-m", "metrics", "--", "docs/superpowers/metrics/runs.jsonl")
        (did,) = self.drafts()
        self.assertEqual(self.run_scout("approve", did), (0, "approved\n"))
        # the run really happened, in the scratch dirs
        self.assertTrue((self.scout / "approved.jsonl").exists())
        self.assertTrue(self.outbox())
        after = snapshot()
        self.assertEqual(before, after)
        print(f"\nscout isolation: compared {len(after)} real paths, none changed")


if __name__ == "__main__":
    unittest.main()
