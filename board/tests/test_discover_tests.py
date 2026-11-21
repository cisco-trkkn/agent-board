import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discover_tests as dt  # noqa: E402

DAY = 86400
NOW = 1_800_000_000
ROOT = "/work/agent-board"


def local_date(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def entry(ts, jobs, head="a" * 40, dirty=False, full=True, root=ROOT):
    return {"ts": ts, "root": root, "head": head, "dirty": dirty, "full": full, "jobs": jobs}


class LoadHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name) / "history.jsonl"

    def test_missing_file_is_empty(self):
        self.assertEqual(dt.load_history(self.p, NOW), [])

    def test_window_and_malformed(self):
        good = entry(NOW - DAY, {"j": [0, 1.0]})
        old = entry(NOW - 31 * DAY, {"j": [0, 1.0]})
        self.p.write_text("\n".join([
            json.dumps(good), "not json", json.dumps(old), "[1, 2]",
            json.dumps({"ts": "x"}), "",
        ]) + "\n")
        self.assertEqual(dt.load_history(self.p, NOW), [good])


class ForRootTest(unittest.TestCase):
    def test_only_rows_under_the_project_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve() / "proj"
            (root / ".claude" / "worktrees" / "w").mkdir(parents=True)
            (Path(d) / "proj-other").mkdir()
            h = [entry(NOW - DAY, {"a": [0, 1.0]}, root=str(root)),
                 entry(NOW - DAY, {"b": [0, 1.0]}, root=str(root / ".claude" / "worktrees" / "w")),
                 entry(NOW - DAY, {"c": [0, 1.0]}, root=str(Path(d) / "proj-other")),
                 entry(NOW - DAY, {"d": [0, 1.0]}, root="/nowhere/else"),
                 entry(NOW - DAY, {"e": [0, 1.0]}, root="")]
            out = dt.for_root(h, str(root))
        self.assertEqual([next(iter(x["jobs"])) for x in out], ["a", "b"])


class FlakyTest(unittest.TestCase):
    def keys(self, hist):
        return [c["key"] for c in dt.flaky_tests(hist, NOW)]

    def test_same_head_clean_pass_and_fail(self):
        h = [entry(NOW - 3 * DAY, {"t": [0, 1.0]}), entry(NOW - 2 * DAY, {"t": [1, 1.0]})]
        c = dt.flaky_tests(h, NOW)
        self.assertEqual([x["key"] for x in c], ["flaky_test:t"])
        self.assertEqual(c[0]["signal"], "flaky_test")
        self.assertEqual(c[0]["count"], 1)
        self.assertEqual(c[0]["first_seen"], local_date(NOW - 2 * DAY))
        self.assertEqual(c[0]["evidence"][0]["text"], f"{local_date(NOW - 2 * DAY)} agent-board @aaaaaaaa rc=1")
        self.assertEqual(self.keys(h), self.keys(h))

    def test_two_flips_in_one_root(self):
        h = [entry(NOW - 4 * DAY, {"t": [1, 1.0]}, head="b" * 40),
             entry(NOW - 3 * DAY, {"t": [0, 1.0]}, head="c" * 40),
             entry(NOW - 2 * DAY, {"t": [1, 1.0]}, head="d" * 40)]
        c = dt.flaky_tests(h, NOW)
        self.assertEqual([x["key"] for x in c], ["flaky_test:t"])
        self.assertEqual(c[0]["count"], 2)

    # mutation: trigger on flips >= 1 instead of >= 2
    def test_one_flip_does_not_trigger(self):
        h = [entry(NOW - 3 * DAY, {"t": [1, 1.0]}, head="b" * 40),
             entry(NOW - 2 * DAY, {"t": [0, 1.0]}, head="c" * 40)]
        self.assertEqual(self.keys(h), [])

    # mutation: ignore the dirty flag in the same-head rule
    def test_dirty_run_does_not_trigger(self):
        h = [entry(NOW - 3 * DAY, {"t": [0, 1.0]}),
             entry(NOW - 2 * DAY, {"t": [1, 1.0]}, dirty=True)]
        self.assertEqual(self.keys(h), [])
        h = [entry(NOW - 3 * DAY, {"t": [0, 1.0]}, dirty=True),
             entry(NOW - 2 * DAY, {"t": [1, 1.0]})]
        self.assertEqual(self.keys(h), [])

    # mutation: group flips across all roots instead of per root
    def test_flips_split_across_roots_do_not_trigger(self):
        h = [entry(NOW - 4 * DAY, {"t": [1, 1.0]}, head="b" * 40, root="/r1"),
             entry(NOW - 3 * DAY, {"t": [0, 1.0]}, head="c" * 40, root="/r2"),
             entry(NOW - 2 * DAY, {"t": [1, 1.0]}, head="d" * 40, root="/r1")]
        self.assertEqual(self.keys(h), [])

    def test_flips_order_by_ts_not_file_order(self):
        h = [entry(NOW - 2 * DAY, {"t": [1, 1.0]}, head="d" * 40),
             entry(NOW - 4 * DAY, {"t": [1, 1.0]}, head="b" * 40),
             entry(NOW - 3 * DAY, {"t": [0, 1.0]}, head="c" * 40)]
        self.assertEqual(self.keys(h), ["flaky_test:t"])


class SlowTest(unittest.TestCase):
    def hist(self, base, cur, job="t", **kw):
        h = [entry(NOW - 29 * DAY, {job: [0, base]}, **kw)]
        for i in range(3):
            h.append(entry(NOW - (3 - i) * DAY, {job: [0, cur]}, **kw))
        return h

    def test_triggers_at_25_percent(self):
        c = dt.slow_tests(self.hist(100.0, 125.0), NOW)
        self.assertEqual([x["key"] for x in c], ["slow_test:t"])
        self.assertEqual(c[0]["count"], 25)
        self.assertEqual(c[0]["signal"], "slow_test")
        self.assertEqual(len(c[0]["evidence"]), 3)

    # mutation: threshold 1.20 instead of 1.25
    def test_24_percent_does_not_trigger(self):
        self.assertEqual(dt.slow_tests(self.hist(100.0, 124.0), NOW), [])

    # mutation: drop the top-5 filter
    def test_job_outside_slowest_five_ignored(self):
        h = self.hist(100.0, 125.0, job="t")
        for n in range(5):
            for e in self.hist(1000.0, 1000.0, job=f"big{n}"):
                h.append(e)
        keys = [x["key"] for x in dt.slow_tests(h, NOW)]
        self.assertNotIn("slow_test:t", keys)

    # mutation: treat a missing baseline as 0 / as current
    def test_no_baseline_no_candidate(self):
        h = [entry(NOW - (3 - i) * DAY, {"t": [0, 500.0]}) for i in range(3)]
        self.assertEqual(dt.slow_tests(h, NOW), [])

    # mutation: drop the `full` filter
    def test_partial_runs_ignored(self):
        h = self.hist(100.0, 125.0, full=False)
        self.assertEqual(dt.slow_tests(h, NOW), [])

    def test_current_is_median_of_last_three(self):
        h = [entry(NOW - 29 * DAY, {"t": [0, 100.0]}),
             entry(NOW - 4 * DAY, {"t": [0, 900.0]}),  # outside the last 3
             entry(NOW - 3 * DAY, {"t": [0, 100.0]}),
             entry(NOW - 2 * DAY, {"t": [0, 200.0]}),
             entry(NOW - 1 * DAY, {"t": [0, 130.0]})]
        c = dt.slow_tests(h, NOW)
        self.assertEqual(c[0]["count"], 30)  # median(100,200,130)=130


class FailedRunsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.root = self.d / "proj"
        self.root.mkdir()
        (self.d / "wt").mkdir()
        self.p = self.d / "runs.jsonl"
        self.lines = []
        self.n = 0

    def run_rec(self, ts, exit, cmd="zsh tests.zsh", cwd=None, log_rc=None, start=True):
        self.n += 1
        rid = f"r{self.n}"
        log = self.d / f"{rid}.log"
        if log_rc is not None:
            log.write_text(f"out\nrc={log_rc}\n")
        base = {"id": rid, "ts": ts, "cmd": cmd, "cwd": str(cwd or self.root), "log": str(log)}
        if start:
            self.lines.append({**base, "exit": None})
        self.lines.append({**base, "exit": exit})
        return base

    def go(self):
        self.p.write_text("\n".join(json.dumps(x) for x in self.lines) + "\n")
        return dt.failed_runs(self.p, str(self.root), NOW)

    def test_old_failure_without_green(self):
        r = self.run_rec(NOW - 2 * DAY, 1)
        c = self.go()
        self.assertEqual(len(c), 1)
        k = hashlib.sha1(b"zsh tests.zsh").hexdigest()[:10]
        self.assertEqual(c[0]["key"], f"failed_run:{k}")
        self.assertEqual(c[0]["signal"], "failed_run")
        self.assertEqual(c[0]["count"], 1)
        self.assertEqual(c[0]["evidence"][0]["path"], r["log"])
        self.assertTrue(c[0]["evidence"][0]["text"].endswith("rc=1 zsh tests.zsh"))
        self.assertEqual(c[0]["first_seen"], local_date(NOW - 2 * DAY))

    # mutation: drop the green-within-24h check
    def test_green_within_24h_clears(self):
        self.run_rec(NOW - 3 * DAY, 1)
        self.run_rec(NOW - 3 * DAY + 3600, 0)
        self.assertEqual(self.go(), [])

    # mutation: drop the green-within-24h check (the latest-run check alone would
    # hide it unless a young failure follows the green)
    def test_green_within_24h_clears_even_when_a_young_failure_follows(self):
        self.run_rec(NOW - 5 * DAY, 1)
        self.run_rec(NOW - 5 * DAY + 3600, 0)
        self.run_rec(NOW - 3600, 1)
        self.assertEqual(self.go(), [])

    def test_green_of_other_cmd_does_not_clear(self):
        self.run_rec(NOW - 3 * DAY, 1)
        self.run_rec(NOW - 3 * DAY + 3600, 0, cmd="other")
        self.assertEqual(len(self.go()), 1)

    # mutation: skip the "latest run is not rc 0" check
    def test_later_green_after_24h_clears(self):
        self.run_rec(NOW - 5 * DAY, 1)
        self.run_rec(NOW - 2 * DAY, 0)
        self.assertEqual(self.go(), [])

    # mutation: accept any cwd under or outside the root
    def test_worktree_cwd_ignored(self):
        self.run_rec(NOW - 2 * DAY, 1, cwd=self.d / "wt")
        self.run_rec(NOW - 2 * DAY, 1, cwd=self.root / "sub")
        self.assertEqual(self.go(), [])

    def test_symlink_to_root_counts(self):
        link = self.d / "link"
        os.symlink(self.root, link)
        self.run_rec(NOW - 2 * DAY, 1, cwd=link)
        self.assertEqual(len(self.go()), 1)

    # mutation: drop the 24h age floor
    def test_young_failure_ignored(self):
        self.run_rec(NOW - 3600, 1)
        self.assertEqual(self.go(), [])

    # mutation: trust `exit` over the log's rc= line
    def test_log_rc_overrides_exit(self):
        self.run_rec(NOW - 2 * DAY, 0, log_rc=3)  # exit says ok, log says fail
        self.assertEqual(len(self.go()), 1)

    def test_log_rc_zero_overrides_exit(self):
        self.lines.clear()
        self.run_rec(NOW - 2 * DAY, 1, log_rc=0)  # `; echo rc=$?` style: rc line wins
        self.assertEqual(self.go(), [])

    # mutation: use the first line per id (the exit: null start line)
    def test_final_record_per_id(self):
        base = self.run_rec(NOW - 2 * DAY, 1, start=False)
        # start line after the final one in file order would be wrong to prefer, but
        # the null-exit line alone must never count as a failed run
        self.lines.append({**base, "id": "only-start", "exit": None})
        c = self.go()
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["count"], 1)

    def test_count_is_failing_runs_in_window(self):
        self.run_rec(NOW - 10 * DAY, 1)
        self.run_rec(NOW - 5 * DAY, 1)
        self.run_rec(NOW - 40 * DAY, 1)  # outside the window
        c = self.go()
        self.assertEqual(c[0]["count"], 2)

    def test_missing_file(self):
        self.assertEqual(dt.failed_runs(self.d / "none.jsonl", str(self.root), NOW), [])


if __name__ == "__main__":
    unittest.main()
