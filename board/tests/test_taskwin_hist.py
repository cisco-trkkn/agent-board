import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskwin_hist as th  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


class RealFilesTest(unittest.TestCase):
    """Parsers against the real ledgers and queue report of this repo (read-only)."""

    def test_real_ledger(self):
        led = next(l for l in th.ledgers(REPO) if l["stem"] == "2026-11-09-remote-access")
        self.assertEqual(led, {"plan": "docs/superpowers/plans/2026-11-09-remote-access.md",
                               "stem": "2026-11-09-remote-access",
                               "spec": "docs/superpowers/specs/2026-11-09-remote-access-design.md",
                               "branch": "feat/remote-access", "day": "2026-11-09",
                               "dir": "docs/superpowers/ledgers/2026-11-09-remote-access/"})

    def test_every_real_ledger_with_a_plan_line_parses(self):
        files = sorted((REPO / th.LEDGERS).glob("*/progress.md"))
        want = [f for f in files if f.read_text(encoding="utf-8").startswith("# SDD ledger — plan: ")]
        self.assertGreaterEqual(len(want), 40)
        self.assertEqual(len(th.ledgers(REPO)), len(want))

    def test_real_report_outcomes(self):
        rows = [r for r in th.report_rows(REPO) if r["day"] == "2026-11-05"]
        self.assertGreaterEqual(len(rows), 11)
        self.assertEqual(rows[0], {"spec": "docs/superpowers/specs/2026-11-05-queue-followups-design.md",
                                   "outcome": "merged 5a90ba9",
                                   "ledger": "docs/superpowers/ledgers/2026-11-05-queue-followups/",
                                   "day": "2026-11-05"})
        self.assertTrue(any(r["outcome"].startswith("failed") for r in rows))

    def test_real_entries_link_report_to_ledger(self):
        e = next(x for x in th.entries(REPO, None) if x["key"] == "plan:2026-11-05-queue-followups")
        self.assertEqual((e["day"], e["outcome"]), ("2026-11-05", "merged 5a90ba9"))

    def test_real_spec_title(self):
        self.assertEqual(th.spec_title(REPO, "docs/superpowers/specs/2026-11-10-interactive-tasks-window-design.md#part-1"),
                         "Interactive tasks window: queue overview, filters, history")


class FakeRootTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        (self.root / th.LEDGERS / "2026-11-20-a").mkdir(parents=True)
        (self.root / th.LEDGERS / "2026-11-20-a" / "progress.md").write_text(
            "# SDD ledger — plan: docs/superpowers/plans/2026-11-20-a.md\nPreflight scan:\nSpec: docs/superpowers/specs/a-design.md\n")
        (self.root / th.LEDGERS / "2026-11-19-bad").mkdir(parents=True)
        (self.root / th.LEDGERS / "2026-11-19-bad" / "progress.md").write_text("# something else\n")
        (self.root / th.REPORTS).mkdir(parents=True)
        (self.root / th.REPORTS / "2026-11-20-queue.md").write_text(
            "# r\n## Outcomes\n\n| # | Spec | Outcome | Ledger |\n| --- | --- | --- | --- |\n"
            "| 1 | `docs/superpowers/specs/a-design.md` | merged `aaa1111` | `docs/superpowers/ledgers/2026-11-20-a/` |\n"
            "| 2 | `docs/superpowers/specs/c-design.md` (note) | failed — x | |\n| garbage |\n## Next\n| 9 | x | y | z |\n")
        self.j = self.root / "j.jsonl"
        self.t1 = time.mktime((2026, 11, 20, 12, 0, 0, 0, 0, -1))   # local noon: the same day in every TZ
        self.t2 = time.mktime((2026, 11, 21, 12, 0, 0, 0, 0, -1))
        self.j.write_text("\n".join([
            json.dumps({"kind": "task_done", "at": self.t1, "plan": "2026-11-20-a", "id": "1", "subject": "A1",
                        "owner": "o", "tier": "mechanical"}),
            "{bad", json.dumps([1]), json.dumps({"kind": "task_done", "plan": "x"}),       # skipped
            json.dumps({"kind": "task_done", "at": self.t2, "plan": "2026-11-21-b", "id": "2", "subject": "B2",
                        "owner": "", "tier": ""}),
            json.dumps({"kind": "queue_outcome", "at": self.t2, "spec": "docs/superpowers/specs/b-design.md",
                        "outcome": "kept spec-b", "plan": "2026-11-21-b"}),
        ]) + "\n")

    def test_bad_ledger_skipped_and_spec_from_any_head_line(self):
        self.assertEqual([(l["stem"], l["spec"]) for l in th.ledgers(self.root)],
                         [("2026-11-20-a", "docs/superpowers/specs/a-design.md")])

    def test_report_rows_only_from_outcomes_table(self):
        self.assertEqual([(r["spec"], r["outcome"], r["ledger"]) for r in th.report_rows(self.root)],
                         [("docs/superpowers/specs/a-design.md", "merged aaa1111", "docs/superpowers/ledgers/2026-11-20-a/"),
                          ("docs/superpowers/specs/c-design.md", "failed — x", "")])

    def test_entries_merge_sources_newest_first(self):
        es = th.entries(self.root, self.j)
        self.assertEqual([e["key"] for e in es],
                         ["plan:2026-11-21-b", "plan:2026-11-20-a", "spec:docs/superpowers/specs/c-design.md"])
        b = next(e for e in es if e["key"] == "plan:2026-11-21-b")
        self.assertEqual((b["day"], b["outcome"], [t["id"] for t in b["tasks"]]), ("2026-11-21", "kept spec-b", ["2"]))
        a = next(e for e in es if e["key"] == "plan:2026-11-20-a")
        self.assertEqual((a["outcome"], a["ledger"], len(a["tasks"])), ("merged aaa1111", "docs/superpowers/ledgers/2026-11-20-a/", 1))
        c = next(e for e in es if e["key"].startswith("spec:"))
        self.assertEqual((c["day"], c["outcome"], c["tasks"]), ("2026-11-20", "failed — x", []))
        days = [e["day"] for e in es]
        self.assertEqual(days, sorted(days, reverse=True))

    def test_missing_root_and_journal(self):
        self.assertEqual(th.entries(self.root / "nope", self.root / "nope.jsonl"), [])
        self.assertEqual(th.read_journal(None), [])

    def test_cache_rereads_after_change(self):
        self.assertEqual(len(th.read_journal(self.j)), 3)
        with open(self.j, "a") as f:
            f.write(json.dumps({"kind": "task_done", "at": self.t2 + 1, "plan": "p", "id": "9", "subject": "s"}) + "\n")
        st = self.j.stat()
        os.utime(self.j, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        self.assertEqual(len(th.read_journal(self.j)), 4)

    def test_queue_report(self):
        q = [{"answeredAt": "2026-11-21T01:00:00Z"}, {"answeredAt": "2026-11-20T23:00:00Z"}, {"answeredAt": ""}]
        self.assertEqual(th.queue_report(self.root, q), "docs/superpowers/reports/2026-11-20-queue.md")
        self.assertEqual(th.queue_report(self.root, q[:1]), "")
        self.assertEqual(th.queue_report(self.root, []), "")


if __name__ == "__main__":
    unittest.main()
