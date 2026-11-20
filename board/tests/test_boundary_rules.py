import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
import ctxsize  # noqa: E402


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class BoundaryRules(unittest.TestCase):
    def test_orchestrator_names_the_hook_message(self):
        self.assertIn("Spec boundary: hand off now (agent-board:handoff) before the next Plan & run task.",
                      read("claude", "orchestrator.md"))

    def test_skill_sections_in_fixed_order(self):
        text = read("claude", "plugin", "skills", "handoff", "SKILL.md")
        at = [text.find(f"## {n}") for n in ("Queue state", "Live state", "Carried over", "Pointers")]
        self.assertTrue(all(i >= 0 for i in at), at)
        self.assertEqual(at, sorted(at))

    def test_skill_trigger_command_and_never_blocks(self):
        text = read("claude", "plugin", "skills", "handoff", "SKILL.md")
        self.assertIn("a `Plan & run:` spec finished in queue mode, with another pending", text)
        self.assertIn('ctxsize.py" doc', text)
        self.assertIn("never blocks", text)

    def test_doc_estimate_names_the_largest_section(self):
        body = "## Queue state\nx\n## Live state\ny\n## Carried over\n" + "z" * 13000 + "\n## Pointers\np\n"
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
            line, over = ctxsize.doc_estimate(p)
        self.assertTrue(over)
        self.assertIn("over; largest section: Carried over", line)


if __name__ == "__main__":
    unittest.main()
