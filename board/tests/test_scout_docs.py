"""The scout is documented where the lead, the README and the install guide look for it."""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


class ScoutDocsTest(unittest.TestCase):
    def test_orchestrator_has_scout_approvals_rule(self):
        text = _read("claude/orchestrator.md")
        self.assertIn("Scout approvals", text)
        self.assertIn("approved.jsonl", text)

    def test_install_has_scout_schedule_step(self):
        self.assertIn("scout schedule install", _read("docs/INSTALL.md"))

    def test_readme_names_scout_modules(self):
        self.assertIn("scout_sources.py", _read("README.md"))


if __name__ == "__main__":
    unittest.main()
