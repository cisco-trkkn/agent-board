"""claude/dream-settings.json is the permission gate of the nightly dream run (plan G7).

The file is asserted by equality: a wider rule (Edit(**), a Bash entry, a path that leaves the run
dir) would let the model write outside its three paths, and nothing else in the run would notice.
What the rules do in a real `claude` is checked by tools/tests/check_real_dream_gate.zsh.
"""
import json
import unittest
from pathlib import Path

SETTINGS = Path(__file__).resolve().parent.parent.parent / "claude" / "dream-settings.json"

ALLOW = ["Read", "Grep", "Glob", "Edit(core.md)", "Edit(archive.md)", "Edit(out/**)"]
DENY = ["Bash", "WebFetch", "WebSearch", "Agent", "Skill", "NotebookEdit"]
WRITABLE = ("core.md", "archive.md", "out/**")


def rule_path(entry):
    """The path inside `Tool(path)`, or None for a bare tool name."""
    if "(" not in entry:
        return None
    return entry[entry.index("(") + 1:].rstrip(")")


class DreamSettingsTest(unittest.TestCase):
    def setUp(self):
        self.perms = json.loads(SETTINGS.read_text())["permissions"]

    def test_file_is_exactly_g7(self):
        self.assertEqual(json.loads(SETTINGS.read_text()),
                         {"permissions": {"defaultMode": "dontAsk", "allow": ALLOW, "deny": DENY}})

    def test_allow_list(self):
        self.assertEqual(self.perms["allow"], ALLOW)

    def test_deny_list(self):
        self.assertEqual(self.perms["deny"], DENY)

    def test_default_mode_refuses_what_no_rule_allows(self):
        self.assertEqual(self.perms["defaultMode"], "dontAsk")

    def test_no_allow_entry_runs_code(self):
        for entry in self.perms["allow"]:
            self.assertFalse(entry.startswith("Bash"), entry)

    def test_write_and_edit_rules_name_only_the_three_paths(self):
        for entry in self.perms["allow"]:
            if entry.startswith(("Write", "Edit", "MultiEdit", "NotebookEdit")):
                self.assertIn(rule_path(entry), WRITABLE, entry)

    def test_no_allow_path_leaves_the_run_dir(self):
        for entry in self.perms["allow"]:
            p = rule_path(entry)
            if p is None:
                continue
            self.assertNotIn("..", p, entry)
            self.assertFalse(p.startswith(("/", "~")), entry)

    def test_no_allow_entry_is_denied(self):
        allowed_tools = {e.split("(")[0] for e in self.perms["allow"]}
        self.assertEqual(allowed_tools & set(self.perms["deny"]), set())


if __name__ == "__main__":
    unittest.main()
