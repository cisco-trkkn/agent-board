import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import metrics  # noqa: E402

FULL = {"spec": "s1", "kind": "needs_you", "recommended": "approve", "confidence": "low", "answer": "approve", "followed": True,
        "asked_at": "2026-11-24T10:00:00Z", "answered_at": "2026-11-24T10:01:00Z"}


class AskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        metrics.append(self.repo, {"kind": "batch", "batch": "B", "configs": [], "assignment": {},
                                   "at": "2026-11-24T00:00:00Z"})

    def append(self, obj, kind="ask"):
        args = metrics._parser().parse_args(["append", kind, "--json", json.dumps(obj), "--batch", "B"])
        metrics.cmd_append(self.repo, args)

    def test_complete_line_appended_with_kind(self):
        self.append({k: v for k, v in FULL.items()})
        lines, _ = metrics.read_log(self.repo)
        self.assertEqual(lines[-1]["kind"], "ask")
        self.assertEqual(lines[-1]["spec"], "s1")
        self.assertEqual(lines[-1]["ask_kind"], "needs_you")   # the wait kind survives; `kind` is the log kind

    def test_missing_key_rejected(self):
        for k in ("spec", "kind", "recommended", "confidence", "answer", "followed", "asked_at", "answered_at"):
            with self.subTest(k=k):
                obj = {a: b for a, b in FULL.items() if a != k}
                with self.assertRaises(metrics.MetricsError):
                    self.append(obj)

    def test_followed_must_be_boolean(self):
        for bad in ("yes", 1, None):
            with self.subTest(bad=bad):
                with self.assertRaises(metrics.MetricsError):
                    self.append(dict(FULL, followed=bad))

    def test_other_kinds_unchanged(self):
        self.append({"spec": "s1"}, kind="note")
        self.assertEqual(metrics.read_log(self.repo)[0][-1]["kind"], "note")

    def report(self):
        return metrics.report_text(self.repo, "B")

    def test_report_no_asks(self):
        self.assertTrue(self.report().rstrip().endswith("asks: 0"))

    def test_report_asks_overall_and_per_kind(self):
        for kind, fol in (("stop_class", True), ("stop_class", False), ("needs_you", True), ("needs_you", True),
                          ("needs_you", True), ("budget", False)):
            self.append(dict(FULL, kind=kind, followed=fol))
        tail = self.report().rstrip().splitlines()[-4:]
        self.assertEqual(tail, ["asks: 6, followed 4 (67%)", "  budget: 1, followed 0 (0%)",
                                "  needs_you: 3, followed 3 (100%)", "  stop_class: 2, followed 1 (50%)"])


if __name__ == "__main__":
    unittest.main()
