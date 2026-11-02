"""The overseer's permission settings (claude/overseer-settings.json) are read-only by rule, not by prompt; its prompt exists."""
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SETTINGS = REPO / "claude" / "overseer-settings.json"
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit", "Agent", "SendMessage", "WebFetch", "WebSearch", "Skill")
WRITE_CTL = ("send", "run", "tell", "agent", "keys", "relay", "context")
# the allowed read-only git commands still write a file with --output=<file>
GIT_OUTPUT = ("git log", "git show")


class OverseerSettingsTest(unittest.TestCase):
    def setUp(self):
        self.d = json.loads(SETTINGS.read_text())
        self.allow, self.deny = self.d["permissions"]["allow"], self.d["permissions"]["deny"]

    def test_every_write_and_messaging_tool_is_denied(self):
        for t in WRITE_TOOLS:
            with self.subTest(tool=t):
                self.assertIn(t, self.deny)
        for sub in WRITE_CTL:
            with self.subTest(ctl=sub):
                self.assertIn(f"Bash(tmux-ctl {sub} *)", self.deny)
        self.assertIn("Bash(tmux send-keys *)", self.deny)
        # the hidden writers (_append, _done, _relay_failed) are not covered by the named subcommands above
        self.assertIn("Bash(tmux-ctl _*)", self.deny)
        for g in GIT_OUTPUT:
            with self.subTest(git=g):
                self.assertIn(f"Bash({g} *--output*)", self.deny)

    def test_overview_and_read_only_git_allowed(self):
        self.assertIn("Bash(tmux-ctl overview *)", self.allow)
        for t in ("Read", "Grep", "Glob", "Bash(git log *)", "Bash(git status *)", "Bash(git show *)"):
            self.assertIn(t, self.allow, t)

    def test_no_allow_has_a_wildcard_before_the_git_verb(self):
        # final review C1: `git -C * log *` also admits `-c core.fsmonitor=…`, `-c alias.x=!…` and `tag show`
        for a in self.allow:
            with self.subTest(allow=a):
                self.assertNotIn("-C", a)
                self.assertNotRegex(a, r"git \S*\*")

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
        # the user's ~/.claude/settings.json allows (Bash(tmux-ctl:*) …) must not widen the overseer's rules
        self.assertRegex(launcher, r"--setting-sources project,local\b")
        self.assertIn("unset CLAUDE_CODE_CHILD_SESSION", launcher)

    def test_overseer_session_starts_outside_the_repo(self):
        # started in the repo, usage matching by cwd would count its own session toward the agent-board project's alerts
        script = (REPO / "bin" / "tmux-overseer").read_text()
        self.assertNotIn('-c "$AB_REPO"', script)
        self.assertIn("agent-board/overseer", script)


if __name__ == "__main__":
    unittest.main()
