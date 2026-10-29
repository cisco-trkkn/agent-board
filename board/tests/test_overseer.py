"""The overseer's permission settings (claude/overseer-settings.json) are read-only by rule, not by prompt; its prompt exists."""
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SETTINGS = REPO / "claude" / "overseer-settings.json"
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "Agent", "SendMessage")
WRITE_CTL = ("send", "run", "tell", "agent", "keys", "relay")


class OverseerSettingsTest(unittest.TestCase):
    def setUp(self):
        self.d = json.loads(SETTINGS.read_text())
        self.allow, self.deny = self.d["permissions"]["allow"], self.d["permissions"]["deny"]

    def test_every_write_and_messaging_tool_is_denied(self):
        for t in WRITE_TOOLS:
            self.assertIn(t, self.deny, t)
        for sub in WRITE_CTL:
            self.assertIn(f"Bash(tmux-ctl {sub} *)", self.deny, sub)
        self.assertIn("Bash(tmux send-keys *)", self.deny)

    def test_overview_and_read_only_git_allowed(self):
        self.assertIn("Bash(tmux-ctl overview *)", self.allow)
        for t in ("Read", "Grep", "Glob", "Bash(git log *)", "Bash(git status *)", "Bash(git show *)"):
            self.assertIn(t, self.allow, t)

    def test_everything_else_is_denied_without_a_prompt(self):
        # deny beats allow in Claude Code, so a bare "Bash" deny would also kill the allowed tmux-ctl overview;
        # "any other Bash" is covered by dontAsk, which auto-denies every call no allow rule matches.
        self.assertEqual(self.d["permissions"]["defaultMode"], "dontAsk")
        self.assertNotIn("Bash", self.deny)
        self.assertFalse(any(a in ("Bash", "Bash(*)") for a in self.allow))

    def test_allow_and_deny_do_not_contradict(self):
        self.assertEqual(set(self.allow) & set(self.deny), set())

    def test_prompt_and_launcher_exist_and_agree(self):
        prompt = REPO / "claude" / "overseer.md"
        self.assertTrue(prompt.is_file() and prompt.stat().st_size > 200)
        text = prompt.read_text()
        for s in ("tmux-ctl overview", "read-only", "task-observer"):
            self.assertIn(s, text, s)
        launcher = (REPO / "bin" / "claude-overseer").read_text()
        for s in ("--model haiku", "--effort low", "claude/overseer-settings.json", "claude/overseer.md"):
            self.assertIn(s, launcher, s)
        self.assertNotIn("--plugin-dir", launcher)


if __name__ == "__main__":
    unittest.main()
