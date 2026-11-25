"""Leak check for the improvement loop (plan Task 14): running every other test_improve_*.py module must leave the real
metrics log, the task-observer PENDING.md, `main` and (when no engine runs) the real engine dir exactly as they were.
It excludes itself: running itself would recurse. Run: python3 -m unittest board.tests.test_improve_isolation"""
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TIMEOUT = 600


def main_checkout():
    r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True, cwd=REPO)
    return Path(r.stdout.strip()).parent


def sha(p):
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "absent"


def engine_running():
    return subprocess.run(["pgrep", "-f", "engine/bin/engine.js"], capture_output=True).returncode == 0


def snapshot():
    main = main_checkout()
    snap = {
        "runs.jsonl": sha(main / "docs" / "superpowers" / "metrics" / "runs.jsonl"),
        "PENDING.md": sha(Path.home() / ".task-observer" / "skill-updates" / "PENDING.md"),
        "main": subprocess.run(["git", "rev-parse", "main"], capture_output=True, text=True, cwd=main).stdout.strip() or "absent",
    }
    eng = Path.home() / ".local" / "state" / "agent-board" / "engine"
    if engine_running():
        print("engine dir skipped: engine running")
    elif eng.is_dir():
        for f in sorted(eng.rglob("*")):
            if f.is_file():
                snap[f"engine/{f.relative_to(eng)}"] = sha(f)
    return snap


def modules():
    return sorted(f.stem for f in HERE.glob("test_improve_*.py") if f.name != Path(__file__).name)


class IsolationTest(unittest.TestCase):
    def test_improve_suites_leave_real_state_unchanged(self):
        mods = modules()
        self.assertGreaterEqual(len(mods), 8, mods)
        before = snapshot()
        self.assertGreaterEqual(len(before), 3)
        for m in mods:
            r = subprocess.run([sys.executable, "-m", "unittest", m], cwd=HERE, capture_output=True, text=True, timeout=TIMEOUT)
            self.assertEqual(r.returncode, 0, f"{m}\n{r.stderr[-2000:]}")
        after = snapshot()
        print(f"isolation: {len(before)} item(s) checked across {len(mods)} module(s)")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
