import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
import paneclass  # noqa: E402

spec = importlib.util.spec_from_file_location("tmux_dash_server_pc", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class IsClaudeCmdTest(unittest.TestCase):
    def test_version_string_and_claude_name_are_claude_a_shell_is_not(self):
        self.assertTrue(paneclass.is_claude_cmd("2.1.316"))
        self.assertTrue(paneclass.is_claude_cmd("Claude"))
        self.assertFalse(paneclass.is_claude_cmd("zsh"))


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


class SpinnerFormatTest(unittest.TestCase):
    """Claude Code 2.1.316 prints no "esc to interrupt"; the live spinner line is `<glyph> <Word>… (<elapsed> · ↓ <n> tokens)`."""
    RULE = "─" * 70
    # layout captured from a live 2.1.316 pane: spinner, blank, rule, empty input, rule, status lines
    def live(self, top):
        return top + ["", self.RULE, "❯ ", self.RULE, "  Sonnet 5.5 · ctx 8%", "  ⏵⏵ auto mode on"]

    def cls(self, rows):
        return paneclass.classify("2.1.316", rows, False)

    def test_new_spinner_lines_are_working(self):
        for line in ("· Spelunking… (6m 56s · ↓ 25.0k tokens)", "· Hyperspacing… (30s · ↓ 2.2k tokens)",
                     "✽ Spelunking… (7m 51s · ↓ 29.0k tokens)", "✻ Effecting… (19s · ↓ 715 tokens · thought for 1s)"):
            with self.subTest(line=line):
                self.assertEqual(self.cls(self.live(["some output", line])), ("claude", "working"))

    def test_finished_line_stays_ready(self):
        self.assertEqual(self.cls(self.live(["some output", "✻ Baked for 30s · done 3:26 AM"])), ("claude", "ready"))

    def test_prose_quoting_a_spinner_is_not_working(self):
        rows = self.live(["the spinner reads · Spelunking… (6m 56s · ↓ 25.0k tokens) in 2.1.316"])
        self.assertEqual(self.cls(rows), ("claude", "ready"))

    def test_stale_spinner_in_transcript_above_finished_line(self):
        rows = self.live(["· Spelunking… (6m 56s · ↓ 25.0k tokens)", "", "⏺ all done, results below", "✻ Baked for 30s · done 3:26 AM"])
        self.assertEqual(self.cls(rows), ("claude", "ready"))

    def test_task_list_under_the_spinner_is_still_working(self):
        rows = self.live(["· Spelunking… (6m 56s · ↓ 25.0k tokens)", "  ⎿  ◼ Fix the thing", "     ◻ Test the thing"])
        self.assertEqual(self.cls(rows), ("claude", "working"))

    def test_permission_prompt_beats_spinner(self):
        rows = ["· Spelunking… (6m 56s · ↓ 25.0k tokens)", "Do you want to proceed?", "❯ 1. Yes", "  2. No"]
        self.assertEqual(self.cls(rows), ("claude", "waiting"))


class SpinnerLayoutsTest(unittest.TestCase):
    """Layouts under/around the spinner. Tip rows: rows captured with `tmux capture-pane -p` from a live pane (%47,
    2.1.316, 18m spinner). Lead footer: the footer rows of live lead %18 (idle at capture time) under a spinner line
    added by hand. The first-frame and one-line tip rows are built from the review's quoted rows (not on screen)."""
    RULE = "─" * 62 + " @scribe ─"
    INPUT = ["❯ ", "─" * 72, "  Sonnet 5.5 · ctx 22% · 5h 36%", "  ⏵⏵ auto mode on (shift+tab to cycle)"]

    def cls(self, rows):
        return paneclass.classify("2.1.316", rows, False)

    def test_wrapped_tip_row_under_spinner(self):   # live %47
        rows = ["     (ctrl+b ctrl+b (twice) to run in background)", "✶ Skedaddling… (18m 41s · ↓ 19.4k tokens)",
                "  ⎿  Tip: Just want the answer? Run /focus now to hide the steps along", "     the way", self.RULE] + self.INPUT
        self.assertEqual(self.cls(rows), ("claude", "working"))

    def test_one_line_tip_row_under_spinner(self):   # review's quoted row
        rows = ["x", "· Lollygagging… (17s · ↓ 661 tokens)", "  tmux focus-events off · add 'set -g focus-events on' to ~/.tmux.con…",
                self.RULE] + self.INPUT
        self.assertEqual(self.cls(rows), ("claude", "working"))

    def test_lead_footer_with_four_teammates(self):   # footer rows of live %18
        footer = ["  ⏺ main"] + [f"  ◯ mate{n}  doing things   {n}m 1s" for n in range(4)]
        rows = ["⏺ text", "✻ Orchestrating… (4m 1s · ↓ 5.0k tokens)", "", "─" * 72] + self.INPUT[:1] + \
               ["─" * 72, "  Opus 5.5 · ctx 20% · 5h 36%", "  ⏵⏵ auto mode on · 1 shell", ""] + footer
        self.assertNotIn(rows[1], rows[-12:])   # the spinner is outside the 12-row tail
        self.assertEqual(self.cls(rows), ("claude", "working"))

    def test_first_frame_without_parenthesis(self):
        self.assertEqual(self.cls(["x", "✢ Thinking…", "", self.RULE] + self.INPUT), ("claude", "working"))

    def test_first_frame_shaped_line_in_transcript_is_not_working(self):
        rows = ["✢ Thinking…", "⏺ done", "", self.RULE] + self.INPUT
        self.assertEqual(self.cls(rows), ("claude", "ready"))
        rows = ["✢ Thinking…", "  some indented output", self.RULE] + self.INPUT
        self.assertEqual(self.cls(rows), ("claude", "ready"))

    def test_open_prompt_below_spinner_is_waiting(self):
        rows = ["· Spelunking… (6m 56s · ↓ 25.0k tokens)", "  tip row", "Do you want to proceed?", "❯ 1. Yes", "  2. No"]
        self.assertEqual(self.cls(rows), ("claude", "waiting"))


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


class ModStatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = os.environ.get("TC_STATE")
        os.environ["TC_STATE"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("TC_STATE") if self.old is None else os.environ.__setitem__("TC_STATE", self.old))
        self.dir = Path(self.tmp.name) / "agent-status"
        self.dir.mkdir()
        self.now = 1_800_000_000.0

    def put(self, name, **rec):
        (self.dir / name).write_text(rec.pop("raw") if "raw" in rec else json.dumps(rec))

    def test_fresh_file_maps_state_for_its_pane(self):
        self.put("s1.json", session_id="s1", pane="%1", state="busy", since=self.now - 5, updatedAt=self.now - 10)
        self.put("s2.json", session_id="s2", pane="%2", state="needs-you", since=self.now, updatedAt=self.now)
        self.put("s3.json", session_id="s3", pane="%3", state="ready", since=self.now, updatedAt=self.now)
        self.assertEqual(paneclass.mod_states(now=self.now), {"%1": "working", "%2": "waiting", "%3": "ready"})

    def test_stale_file_is_ignored(self):  # mutation: drop the 45 s check -> this fails
        self.put("s1.json", session_id="s1", pane="%1", state="busy", since=self.now, updatedAt=self.now - 45)
        self.assertEqual(paneclass.mod_states(now=self.now), {})

    def test_partial_unknown_and_paneless_files_are_ignored(self):  # mutation: drop the except / state check -> fails
        self.put("bad.json", raw='{"session_id": "s1", "pane": "%1", "sta')
        self.put("odd.json", session_id="s2", pane="%2", state="thinking", since=self.now, updatedAt=self.now)
        self.put("nopane.json", session_id="s3", pane=None, state="busy", since=self.now, updatedAt=self.now)
        self.put("s4.json.tmp", session_id="s4", pane="%4", state="busy", since=self.now, updatedAt=self.now)
        self.assertEqual(paneclass.mod_states(now=self.now), {})

    def test_newest_file_wins_for_one_pane(self):  # mutation: keep the first file seen -> fails for one listing order
        self.put("old.json", session_id="old", pane="%1", state="busy", since=self.now, updatedAt=self.now - 20)
        self.put("new.json", session_id="new", pane="%1", state="ready", since=self.now, updatedAt=self.now - 1)
        self.assertEqual(paneclass.mod_states(now=self.now), {"%1": "ready"})

    def test_missing_dir_is_empty(self):
        self.dir.rmdir()
        self.assertEqual(paneclass.mod_states(now=self.now), {})

    def test_classify_prefers_mod_state_for_claude_only(self):  # mutation: ignore mod -> first assert fails
        self.assertEqual(paneclass.classify("2.1.318", ["> "], False, "working"), ("claude", "working"))
        self.assertEqual(paneclass.classify("2.1.318", ["> "], False, None), ("claude", "ready"))
        self.assertEqual(paneclass.classify("zsh", [], False, "working"), ("shell", "idle"))

    def test_pane_status_reads_the_pane_file(self):  # mutation: pane_status not passing mod -> fails
        self.put("s1.json", session_id="s1", pane="%7", state="needs-you", since=time.time(), updatedAt=time.time())

        def tmux(*args, check=False):
            return "2.1.318~|~0" if args[0] == "display" else "> \n"

        self.assertEqual(paneclass.pane_status(tmux, "%7"), ("claude", "waiting"))


if __name__ == "__main__":
    unittest.main()
