import importlib.util
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
import paneclass  # noqa: E402

spec = importlib.util.spec_from_file_location("tmux_dash_server_pc", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ClassifyTest(unittest.TestCase):
    def test_shell_idle(self):
        self.assertEqual(paneclass.classify("zsh", [], False), ("shell", "idle"))

    def test_working(self):
        self.assertEqual(paneclass.classify("2.1.0", ["✻ Thinking… (esc to interrupt)"], False), ("claude", "working"))

    def test_waiting(self):
        self.assertEqual(paneclass.classify("2.1.0", ["Do you want to proceed?", "❯ 1. Yes"], False), ("claude", "waiting"))

    def test_ready(self):
        self.assertEqual(paneclass.classify("2.1.0", ["> "], True), ("claude", "ready"))

    def test_program(self):
        self.assertEqual(paneclass.classify("vim", [], False), ("program", "running"))

    def test_server_uses_shared(self):
        self.assertIs(server.classify, paneclass.classify)


class PaneStatusTest(unittest.TestCase):
    def test_pane_status(self):
        calls = []

        def tmux(*a, check=False):
            calls.append(a)
            if a[0] == "display":
                return f"2.1.0{paneclass.SEP}0\n"
            return "line\n✻ Working (esc to interrupt)\n\n"

        self.assertEqual(paneclass.pane_status(tmux, "%3"), ("claude", "working"))
        self.assertEqual(calls[0][:3], ("display", "-p", "-t"))
        self.assertEqual(calls[1][0], "capture-pane")


if __name__ == "__main__":
    unittest.main()


class InputTextTest(unittest.TestCase):
    RULE = "─" * 78
    # rows captured read-only from a live Claude Code 2.1.301 lead pane (empty input, agent list below)
    LIVE = [
        "⏺ review's idle notice repeats what it already reported. fixer is working on those fixes now,",
        "  and I'll report when it's done.",
        "",
        "─" * 78 + " orchestrator ─",
        "❯ ",
        "─" * 93,
        "  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents · ↓ to manage",
        "",
        "  ⏺ main",
        "  ◯ review  Final whole-plan code review                                            27m 42s",
        "  ◯ fixer   Fix final review findings                                               20m 31s",
    ]

    def live(self, text="", extra_agents=0):
        rows = list(self.LIVE)
        rows[4] = "❯ " + text
        rows += [f"  ◯ agent{n}  doing things   1m" for n in range(extra_agents)]
        return rows

    def test_live_layout(self):
        import paneclass
        self.assertFalse(paneclass.input_has_text(self.live()))
        self.assertTrue(paneclass.input_has_text(self.live("half typed message")))
        self.assertFalse(paneclass.input_has_text(self.live('Try "fix the bug"')))

    def test_many_agents_below_the_input(self):
        import paneclass
        self.assertTrue(paneclass.input_has_text(self.live("half typed", extra_agents=12)))

    def test_permission_menu_is_not_input(self):
        import paneclass
        rows = ["─" * 60, "❯ 1. Yes", "  2. No", "─" * 60]
        self.assertFalse(paneclass.input_has_text(rows))

    def test_box_layout_still_works(self):
        import paneclass
        box = lambda t: ["out", "╭────╮", f"│ > {t:<20}│", "╰────╯", "  ? for shortcuts"]
        self.assertTrue(paneclass.input_has_text(box("half typed")))
        self.assertFalse(paneclass.input_has_text(box("")))
        self.assertFalse(paneclass.input_has_text(["no prompt here"]))
