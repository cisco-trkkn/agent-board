import json, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import metrics_tasks  # noqa: E402

# Fixture lines are copied from the real ledgers
#   docs/superpowers/ledgers/2026-11-16-discord-replaces-telegram/progress.md  (DISCORD: dc-launch did Tasks 1 and 2)
#   docs/superpowers/ledgers/2026-11-11-queue-metrics/progress.md               (QM: fix rounds, re-review)
# The one `Important:` line is copied from docs/superpowers/ledgers/2026-10-28-overseer/progress.md.
DISCORD = """\
Task 1: dispatched dc-launch (sonnet, base 22b8f60)
Task 1: green check ok; review dispatched dc-review (4e9d2cf..28b98dd)
Task 1: minor (deferred): has-token accepts a whitespace/quoted value; cache rewrite resets file mode to 0600; mtime-check test portability note
Task 1: complete (commits 4e9d2cf..28b98dd, review clean)
Task 2: dispatched dc-launch (sonnet, base 5f45fc3)
Task 2: green check ok; review dispatched dc-review (b1920d7..0bc8efc)
Task 2: minor (deferred): pair uses unvalidated senderId as a filename (approved/<id>); token drops stdin lines after the first silently
Task 2: complete (commits b1920d7..0bc8efc, review clean)
"""

QM = """\
Task 1: dispatched qm-impl (sonnet/standard), base 12862a6
Task 1: review dispatched to qm-rev (sonnet/standard), package review-12862a6..23b2afb.diff
Task 1: complete (commits 12862a6..23b2afb, review clean)
Task 2: dispatched qm-impl, base 23b2afb
Task 2: review dispatched to qm-rev, package review-23b2afb..5e8e5b2.diff
Task 2: minor (deferred): dead code (plan_text, if/pass, inline import, setUp loop)
Task 2: minor (deferred): branch --contains picks first non-main branch arbitrarily
Task 2: Important: overseer read-only claim unsupported — --settings merges with ~/.claude/settings.json
Task 2: fix round 1/5 dispatched to qm-impl (FIX_BASE 5e8e5b2)
Task 2: fix round 1/5 dispatched (Important: _insert newline fusion; plus stale _locked() comment), FIX_BASE 08c21c6
Task 2: fix round 1/5 — commits 5e8e5b2..a5a9a9e; scoped re-review dispatched to qm-rev
Task 2: complete (commits 23b2afb..539ddfc excl. 3a29282, review clean)
"""

PRICES = {"default_context": 200000, "models": {
    "claude-sonnet-5": {"input": 3, "output": 15, "cache_read": 0.3, "cache_write_5m": 3.75, "cache_write_1h": 6, "context": 200000},
    "claude-haiku-5": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write_5m": 1.25, "cache_write_1h": 2, "context": 200000},
}}
ROUTING = {"mechanical": "haiku", "standard": "sonnet", "frontier": "fable"}


def row(ts, agent, model="claude-sonnet-5", out=1000):
    return {"ts": float(ts), "model": model, "agent_name": agent, "input": 0, "output": out,
            "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}


def tasks_json(*specs):
    """specs: (subject, tier, extra description)."""
    ts = []
    for i, (subject, tier, extra) in enumerate(specs):
        desc = "**Goal:** x\n" + extra + '\n```json:metadata\n{"modelTier": "%s"}\n```' % tier
        ts.append({"id": i, "subject": subject, "status": "completed", "description": desc})
    return json.dumps({"planPath": "p.md", "tasks": ts})


def build(progress, tasks, rows, ends=None, run_end=None):
    return metrics_tasks.build_task_lines(
        "docs/superpowers/specs/s.md", "2026-11-16-1", tasks, progress, ROUTING, rows,
        (ends or {}).get, run_end, prices=PRICES)


class TestParseLedger(unittest.TestCase):
    def test_fix_rounds_max_not_count(self):
        t = metrics_tasks.parse_ledger(QM)[2]
        self.assertEqual(t["fix_rounds"], 1)  # 3 lines name round 1; counting lines would give 3

    def test_findings_counts(self):
        t = metrics_tasks.parse_ledger(QM)[2]
        self.assertEqual(t["findings"], {"critical": 0, "important": 2, "minor": 2})

    def test_owners_models_commit_end_complete(self):
        led = metrics_tasks.parse_ledger(DISCORD)
        self.assertEqual(led[1]["owners"], ["dc-launch"])
        self.assertEqual(led[1]["dispatch_models"], ["sonnet"])
        self.assertEqual(led[1]["commit_end"], "28b98dd")
        self.assertTrue(led[2]["complete"])
        self.assertEqual(led[2]["review_rounds"], 1)
        q = metrics_tasks.parse_ledger(QM)
        self.assertEqual(q[2]["owners"], ["qm-impl"])
        self.assertEqual(q[2]["dispatch_models"], [])  # "dispatched qm-impl, base" names no model
        self.assertEqual(q[2]["commit_end"], "539ddfc")
        self.assertEqual(q[2]["review_rounds"], 2)  # review dispatched + the re-review line

    def test_fix_dispatch_group_limited(self):
        led = metrics_tasks.parse_ledger("Task 3: fix round 1/5 dispatched to ovr-fix (fresh, standard)\n")
        self.assertEqual(led[3]["owners"], ["ovr-fix"])
        self.assertEqual(led[3]["dispatch_models"], [])


class TestBuild(unittest.TestCase):
    def two(self):
        return tasks_json(("Task 1: a", "standard", ""), ("Task 2: b", "standard", ""))

    def test_shared_owner_rows_split_by_commit_end(self):
        rows = [row(900, "dc-launch", out=1000), row(1500, "dc-launch", out=2000), row(2500, "dc-launch", out=4000)]
        r = build(DISCORD, self.two(), rows, ends={"28b98dd": 1000, "0bc8efc": 2000})
        self.assertEqual([r[0]["tokens"], r[1]["tokens"]], [1000, 6000])
        self.assertEqual(r[0]["ended_at"], "1970-01-01T00:15:00Z")
        self.assertEqual(r[1]["started_at"], "1970-01-01T00:25:00Z")

    def test_reviewer_rows_not_in_task_tokens(self):
        rows = [row(900, "dc-launch", out=1000), row(1100, "dc-review", out=500), row(2100, "dc-review", out=700)]
        r = build(DISCORD, self.two(), rows, ends={"28b98dd": 1000, "0bc8efc": 2000})
        self.assertEqual(r[0]["tokens"], 1000)
        self.assertEqual(r[0]["review_tokens"], 500)
        self.assertIsNone(r[1]["tokens"])
        self.assertEqual(r[1]["review_tokens"], 700)
        self.assertAlmostEqual(r[0]["review_usd"], 500 * 15 / 1e6)
        self.assertAlmostEqual(r[0]["usd"], 1000 * 15 / 1e6)

    def test_no_rows_partial(self):
        r = build(DISCORD, self.two(), [], ends={})
        for t in r:
            self.assertIsNone(t["tokens"])
            self.assertIsNone(t["usd"])
            self.assertIsNone(t["model_used"])
            self.assertTrue(t["partial"])

    def test_rows_present_not_partial(self):
        r = build(DISCORD, self.two(), [row(900, "dc-launch")], ends={"28b98dd": 1000, "0bc8efc": 2000})
        self.assertFalse(r[0]["partial"])
        self.assertEqual(r[0]["model_used"], "claude-sonnet-5")
        self.assertEqual(r[0]["active_s"], 60)

    def test_escalated_by_dispatch_model(self):
        tasks = tasks_json(("Task 1: a", "mechanical", ""))
        led = "Task 1: dispatched dc-scrub (sonnet, base 22b8f60)\n"
        r = build(led, tasks, [row(10, "dc-scrub", model="claude-haiku-5")])
        self.assertEqual(r[0]["model_mapped"], "haiku")
        self.assertEqual(r[0]["model_used"], "claude-haiku-5")
        self.assertTrue(r[0]["escalated"])
        led2 = "Task 1: dispatched dc-scrub (haiku, base 22b8f60)\n"
        self.assertFalse(build(led2, tasks, [row(10, "dc-scrub", model="claude-haiku-5")])[0]["escalated"])
        self.assertTrue(build(led2, tasks, [row(10, "dc-scrub", model="claude-sonnet-5")])[0]["escalated"])

    def test_code_in_steps(self):
        tasks = tasks_json(("Task 1: a", "standard", "```python\nx = 1\n```"), ("Task 2: b", "standard", ""))
        r = build("", tasks, [])
        self.assertTrue(r[0]["code_in_steps"])
        self.assertFalse(r[1]["code_in_steps"])

    def test_keys_exact(self):
        r = build(DISCORD, self.two(), [row(900, "dc-launch")])
        self.assertEqual(set(r[0]), set(
            "spec batch task_id subject tier model_mapped model_used escalated owner started_at ended_at "
            "active_s tokens usd review_tokens review_usd fix_rounds findings review_rounds outcome "
            "code_in_steps partial".split()))
        self.assertEqual((r[0]["task_id"], r[0]["tier"], r[0]["owner"], r[0]["outcome"]), (1, "standard", "dc-launch", "complete"))

    def test_task_id_falls_back_to_index(self):
        r = build("", tasks_json(("setup", "standard", "")), [])
        self.assertEqual(r[0]["task_id"], 1)

    def test_unfinished_task_outcome_is_status(self):
        r = build("Task 1: dispatched dc-launch (sonnet, base 1)\n", self.two(), [])
        self.assertEqual(r[0]["outcome"], "completed")


if __name__ == "__main__":
    unittest.main()
