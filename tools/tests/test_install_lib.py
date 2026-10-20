import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import install_lib  # noqa: E402

CMDS = ["~/.claude/hooks/bash-mirror.sh", "~/.claude/hooks/artifact-register.sh", "~/.claude/hooks/kill-guard.sh"]


def dump(d):
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


SETTINGS = {
    "env": {"KEEP": "1", "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"},
    "teammateMode": "tmux",
    "model": "opus ü",
    "hooks": {
        "PostToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/bash-mirror.sh"}]},
            {"matcher": "Write", "hooks": [{"type": "command", "command": "~/.claude/hooks/artifact-register.sh"}]},
            {"matcher": "TaskUpdate", "hooks": [{"type": "command", "command": 'bash "/x/superpowers-hook.sh" a.sh'}]},
        ],
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/kill-guard.sh"}]},
        ],
        "Stop": [
            {"hooks": [{"type": "command", "command": "keep-1"}, {"type": "command", "command": "~/.claude/hooks/kill-guard.sh"}]},
        ],
    },
}


class StripSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_drops_only_listed_commands_and_empty_containers(self):
        self.p.write_text(dump(SETTINGS))
        removed = install_lib.strip_settings(self.p, CMDS)
        self.assertEqual(sorted(removed), sorted(["~/.claude/hooks/bash-mirror.sh", "~/.claude/hooks/artifact-register.sh",
                                                  "~/.claude/hooks/kill-guard.sh", "~/.claude/hooks/kill-guard.sh"]))
        want = json.loads(json.dumps(SETTINGS))
        want["hooks"] = {"PostToolUse": [SETTINGS["hooks"]["PostToolUse"][2]],
                         "Stop": [{"hooks": [{"type": "command", "command": "keep-1"}]}]}
        self.assertEqual(self.p.read_text(), dump(want))

    def test_team_keys_only_with_flag(self):
        self.p.write_text(dump(SETTINGS))
        install_lib.strip_settings(self.p, CMDS)
        d = json.loads(self.p.read_text())
        self.assertIn("teammateMode", d)
        self.assertIn("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", d["env"])
        removed = install_lib.strip_settings(self.p, CMDS, team=True)
        d = json.loads(self.p.read_text())
        self.assertNotIn("teammateMode", d)
        self.assertEqual(d["env"], {"KEEP": "1"})
        self.assertEqual(sorted(removed), ["env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "teammateMode"])

    def test_nothing_to_remove_leaves_file_untouched(self):
        text = '{"a":   1}'      # odd formatting must survive when nothing changes
        self.p.write_text(text)
        self.assertEqual(install_lib.strip_settings(self.p, CMDS), [])
        self.assertEqual(self.p.read_text(), text)

    def test_dry_run_reports_without_writing(self):
        self.p.write_text(dump(SETTINGS))
        self.assertEqual(len(install_lib.strip_settings(self.p, CMDS, dry=True)), 4)
        self.assertEqual(self.p.read_text(), dump(SETTINGS))

    def test_missing_file_is_a_noop(self):
        self.assertEqual(install_lib.strip_settings(self.p, CMDS), [])
        self.assertFalse(self.p.exists())

    def test_bad_json_raises_and_keeps_file(self):
        self.p.write_text("{nope")
        with self.assertRaises(ValueError):
            install_lib.strip_settings(self.p, CMDS)
        self.assertEqual(self.p.read_text(), "{nope")

    def test_no_temp_file_left(self):
        self.p.write_text(dump(SETTINGS))
        install_lib.strip_settings(self.p, CMDS)
        self.assertEqual(os.listdir(self.tmp.name), ["settings.json"])


PATTERNS = install_lib.TMUX_PATTERNS


class StripTmuxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / ".tmux.conf"

    def tearDown(self):
        self.tmp.cleanup()

    def test_drops_exactly_the_matching_lines(self):
        mine = [
            'bind W display-popup -E -w 90% -h 60% -d "#{pane_current_path}" -T " clean up agent worktrees " "~/.local/bin/tmux-agent-cleanup"',
            "set-hook -g after-split-window 'run-shell -b \"~/.local/bin/tmux-teammate-window --hook #{pane_id}\"'",
            "set-hook -g session-closed 'run-shell -b \"~/.local/bin/tmux-session-closed #{q:hook_session_name}\"'",
            "bind f run-shell -b \"~/.local/bin/tmux display-popup -c '#{client_name}' -E -w 70% -h 50% -T ' jump to window ' \\\"~/.local/bin/tmux-jump '#{client_name}'\\\"\"",
            "bind D run-shell -b \"DEV_CLIENT='#{client_name}' ~/.local/bin/dev '#{pane_current_path}'\"",
        ]
        keep = [
            "# my config",
            "bind r source-file ~/.tmux.conf \; display 'reloaded'",
            "bind d run-shell 'echo dev'",
            "set -g @plugin 'tmux-plugins/tmux-resurrect'",
            "# tmux-jump is mentioned in a comment",
            "bind m display-menu -T x 'a' a 'echo'",
            "",
        ]
        lines = keep[:2] + mine[:3] + keep[2:4] + mine[3:] + keep[4:]
        self.p.write_text("\n".join(lines) + "\n")
        removed = install_lib.strip_tmux(self.p, PATTERNS)
        self.assertEqual(removed, mine)
        self.assertEqual(self.p.read_text(), "\n".join(keep) + "\n")

    def test_missing_file_and_no_match(self):
        self.assertEqual(install_lib.strip_tmux(self.p, PATTERNS), [])
        self.assertFalse(self.p.exists())
        self.p.write_text("set -g mouse on")        # no trailing newline kept as is
        self.assertEqual(install_lib.strip_tmux(self.p, PATTERNS), [])
        self.assertEqual(self.p.read_text(), "set -g mouse on")


if __name__ == "__main__":
    unittest.main()
