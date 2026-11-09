"""build_state marks a lead pane `telegram` when its process tree runs claude with --channels plugin:telegram.

server.tmux, proc_table and the slow collaborators are patched; no tmux or ps runs.
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BOARD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOARD))

os.environ.setdefault("TMUX_DASH_TOKEN", "x")
spec = importlib.util.spec_from_file_location("tmux_dash_server_tgbadge", BOARD / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
SEP = server.SEP


def row(sess, widx, wname, pane_id, pid, cmd="claude", mate="", bg=""):
    return SEP.join([sess, "1", str(widx), wname, "0", "", "0", pane_id, "t", cmd, "/p", "1", "1", mate, bg, "/p", str(pid)])


TG = "node claude --model opus --channels plugin:telegram@claude-plugins-official"
PLAIN = "node claude --model opus"


class TelegramBadgeTest(unittest.TestCase):
    def build(self, rows, table):
        calls = []

        def ps():
            calls.append(1)
            return table

        patches = [
            mock.patch.object(server, "tmux", return_value="\n".join(rows)),
            mock.patch.object(server, "capture_panes", side_effect=lambda ids: {i: [] for i in ids}),
            mock.patch.object(server, "mod_states", return_value={}),
            mock.patch.object(server, "cached_worktrees", return_value=[]),
            mock.patch.object(server, "deliver_comments"),
            mock.patch.object(server.usage, "card_alerts"),
            mock.patch.object(server.usage, "card_labels"),
            mock.patch.object(server, "last_sweep", return_value=None),
            mock.patch.object(server.relay, "root_for", return_value="/p"),
            mock.patch.object(server, "proc_table", side_effect=ps),
            mock.patch.object(server, "INDEXER", None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        st = server.build_state()
        return {p["id"]: p["telegram"] for s in st["sessions"] for w in s["windows"] for p in w["panes"]}, calls

    def test_flag_on_a_descendant_marks_the_lead(self):
        rows = [row("a", 0, "claude", "%1", 100)]
        table = {100: (1, "-zsh"), 101: (100, "bun run"), 102: (101, TG)}
        flags, _ = self.build(rows, table)
        self.assertEqual(flags, {"%1": True})

    def test_flag_on_the_pane_process_itself(self):
        flags, _ = self.build([row("a", 0, "claude", "%1", 100)], {100: (1, TG)})
        self.assertEqual(flags, {"%1": True})

    def test_lead_without_flag_is_false(self):
        flags, _ = self.build([row("a", 0, "claude", "%1", 100)], {100: (1, PLAIN)})
        self.assertEqual(flags, {"%1": False})

    def test_flag_in_an_unrelated_tree_does_not_count(self):
        flags, _ = self.build([row("a", 0, "claude", "%1", 100)], {100: (1, PLAIN), 200: (1, TG)})
        self.assertEqual(flags, {"%1": False})

    def test_teammate_window_with_flag_is_false(self):
        rows = [row("a", 0, "claude", "%1", 100), row("a", 1, "✦ mate", "%2", 200, mate="1")]
        flags, _ = self.build(rows, {100: (1, PLAIN), 200: (1, TG)})
        self.assertEqual(flags, {"%1": False, "%2": False})

    def test_non_claude_window_is_never_a_lead(self):
        rows = [row("a", 0, "claude", "%1", 100), row("a", 1, "other", "%2", 200)]
        flags, _ = self.build(rows, {100: (1, PLAIN), 200: (1, TG)})
        self.assertEqual(flags["%2"], False)

    def test_ps_runs_once_for_two_lead_panes(self):
        rows = [row("a", 0, "claude", "%1", 100), row("b", 0, "claude", "%2", 200)]
        flags, calls = self.build(rows, {100: (1, TG), 200: (1, PLAIN)})
        self.assertEqual(flags, {"%1": True, "%2": False})
        self.assertEqual(len(calls), 1)

    def test_no_ps_without_a_lead_pane(self):
        flags, calls = self.build([row("a", 0, "shell", "%1", 100, cmd="zsh")], {})
        self.assertEqual(flags, {"%1": False})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
