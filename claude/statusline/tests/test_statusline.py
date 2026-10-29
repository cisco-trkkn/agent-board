import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "agent-board-statusline"
FIXTURE = HERE / "fixtures" / "statusline-sample.json"


def run(stdin, state):
    env = dict(os.environ, TC_STATE=str(state))
    return subprocess.run([str(SCRIPT)], input=stdin, capture_output=True, text=True, env=env, timeout=20)


def count_files(root):
    return sum(len(f) for _, _, f in os.walk(root))


class StatuslineTap(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.payload = json.loads(FIXTURE.read_text())

    def test_fixture_is_stored_and_line_shows_model_and_context(self):
        r = run(FIXTURE.read_text(), self.state)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "Haiku 5.5 · ctx 4% · 5h 63%")
        f = self.state / "statusline" / f"{self.payload['session_id']}.json"
        stored = json.loads(f.read_text())
        self.assertIsInstance(stored.pop("received_at"), float)
        self.assertEqual(stored, self.payload)
        self.assertEqual([p.name for p in f.parent.iterdir()], [f.name])  # no temp file left

    def test_null_context_and_no_rate_limits(self):
        self.payload["context_window"]["used_percentage"] = None
        del self.payload["rate_limits"]
        r = run(json.dumps(self.payload), self.state)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "Haiku 5.5 · ctx –")

    def test_invalid_json_prints_fallback_and_writes_nothing(self):
        r = run("{not json", self.state)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "agent-board")
        self.assertEqual(count_files(self.root), 0)

    def test_write_failure_still_exits_zero_with_a_line(self):
        d = self.state / "statusline"
        d.mkdir()
        d.chmod(0o500)
        self.addCleanup(d.chmod, 0o700)
        r = run(FIXTURE.read_text(), self.state)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip())
        self.assertEqual(count_files(self.root), 0)

    def test_hostile_session_id_writes_nothing(self):
        for sid in ("../x", "a/b", "..", "a b", ""):
            with self.subTest(sid=sid):
                self.payload["session_id"] = sid
                before = count_files(self.root)
                r = run(json.dumps(self.payload), self.state)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("Haiku 5.5", r.stdout)
                self.assertEqual(count_files(self.root), before)

    def test_missing_session_id_writes_nothing(self):
        del self.payload["session_id"]
        r = run(json.dumps(self.payload), self.state)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Haiku 5.5", r.stdout)
        self.assertEqual(count_files(self.root), 0)


if __name__ == "__main__":
    unittest.main()
