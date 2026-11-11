"""The privacy sweeps over the committed run log and over every line the other test_metrics_* tests write."""
import os, re, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CHECKOUT = HERE.parent
sys.path.insert(0, str(HERE))

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-")

SWEEP = r"""
import sys, unittest
sys.path.insert(0, {board!r})
import metrics
sink = open({sink!r}, "a")
orig = metrics.append
def spy(repo, obj):
    import json
    sink.write(json.dumps(obj, sort_keys=True) + "\n")
    sink.flush()
    orig(repo, obj)
metrics.append = spy
suite = unittest.defaultTestLoader.discover({tests!r}, pattern={pattern!r})
res = unittest.TextTestRunner(stream=open({log!r}, "w")).run(suite)
sys.exit(0 if res.wasSuccessful() else 1)
"""


ABS_VALUE = re.compile(r'"/[A-Za-z]')
TEMP_ROOTS = sorted({tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())} - {"/"})


class PrivacySweepTest(unittest.TestCase):
    def sweep(self, lines, label):
        home = os.path.expanduser("~")
        for l in lines:
            self.assertNotIn("/Users/", l, f"{label}: {l[:200]}")
            self.assertNotIn(home, l, f"{label}: {l[:200]}")
            self.assertIsNone(UUID.search(l), f"{label}: {l[:200]}")
            self.assertIsNone(ABS_VALUE.search(l), f"{label}: absolute path value in {l[:200]}")
            for root in TEMP_ROOTS:
                self.assertNotIn(root, l, f"{label}: temp root in {l[:200]}")

    def test_committed_run_log(self):
        p = CHECKOUT / "docs/superpowers/metrics/runs.jsonl"
        if not p.exists():
            self.skipTest("docs/superpowers/metrics/runs.jsonl is not committed yet")
        lines = p.read_text().splitlines()
        self.sweep(lines, "runs.jsonl")
        print(f"checked {len(lines)} lines (committed runs.jsonl)")
        self.assertGreater(len(lines), 0)

    @unittest.skipIf(os.environ.get("METRICS_SWEEP_INNER"), "already inside the sweep's own run")
    def test_every_line_the_other_metrics_tests_write(self):
        # one process per test file, all at once: the lines written are the same as in one discover run, the wall
        # time is the slowest file's
        files = sorted(p.name for p in (HERE / "tests").glob("test_metrics_[!b]*.py"))
        with tempfile.TemporaryDirectory() as d:
            procs = []
            for f in files:
                sink, log = Path(d) / f"{f}.sink.jsonl", Path(d) / f"{f}.log"
                code = SWEEP.format(board=str(HERE), sink=str(sink), tests=str(HERE / "tests"), pattern=f, log=str(log))
                procs.append((f, sink, log, subprocess.Popen([sys.executable, "-I", "-c", code], stdout=subprocess.PIPE,
                                                             stderr=subprocess.PIPE, text=True,
                                                             env={**os.environ, "METRICS_SWEEP_INNER": "1"})))
            lines = []
            for f, sink, log, proc in procs:
                _, err = proc.communicate()
                self.assertEqual(proc.returncode, 0, f"{f}: {err}{log.read_text()[-2000:]}")
                lines += sink.read_text().splitlines() if sink.exists() else []
        self.assertGreater(len(lines), 20)
        self.sweep(lines, "test logs")
        print(f"checked {len(lines)} lines (every run-log line the other test_metrics_* tests wrote)")


if __name__ == "__main__":
    unittest.main()
