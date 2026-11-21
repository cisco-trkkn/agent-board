import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskwin_ui as tu  # noqa: E402
import taskwin_views as tv  # noqa: E402


def task(i, subject, status):
    return {"id": str(i), "subject": subject, "status": status, "owner": "", "tier": "", "blockedBy": []}


QUEUE = [task(1, "Plan & run: docs/superpowers/specs/a-design.md", "completed"),
         task(2, "Plan & run: docs/superpowers/specs/b-design.md", "in_progress"),
         task(3, "Task 1: one", "completed"), task(4, "Task 2: two", "completed"),
         task(5, "Task 3: three", "in_progress"), task(6, "Task 4: four", "blocked"), task(7, "Task 5: five", "pending")]
HIST = [{"key": "plan:x"}, {"key": "plan:y"}]


def press(keys, tasks=QUEUE, ui=None, history=HIST):
    ui = tu.normalize(ui, tasks)
    for k in keys:
        ui = tu.handle_key(ui, k, tv.model(tasks, ui, history))
    return ui


class DecodeTest(unittest.TestCase):
    def test_keys_and_arrows(self):
        self.assertEqual(tu.decode("3j\x1b[Bk\x1b[A\t\r\nfc?q"),
                         ["3", "j", "down", "k", "up", "tab", "enter", "enter", "f", "c", "?", "q"])

    def test_lone_esc_and_other_sequences_ignored(self):
        self.assertEqual(tu.decode("\x1b"), [])
        self.assertEqual(tu.decode("\x1bj"), ["j"])                  # ESC then j: the ESC alone is dropped
        self.assertEqual(tu.decode("\x1b[C\x1b[1;5A\x1bOB2"), ["down", "2"])   # right, ctrl-up dropped; SS3 down kept


class DefaultTest(unittest.TestCase):
    def test_default_view_queue_with_plan_and_run(self):
        self.assertEqual(tu.default_ui(QUEUE)["view"], "queue")

    def test_default_view_plan_without(self):
        self.assertEqual(tu.default_ui([task(1, "Task 1: x", "pending")])["view"], "plan")
        self.assertEqual(tu.default_ui([])["view"], "plan")

    def test_normalize_repairs_bad_fields(self):
        ui = tu.normalize({"view": "nope", "cursor": {"plan": -3, "queue": "x"}, "filter": 7,
                           "collapsed": {"a": True, "b": "yes"}, "help": 1}, QUEUE)
        self.assertEqual(ui, {"view": "queue", "cursor": {"queue": 0, "plan": 0, "history": 0}, "filter": "all",
                              "collapsed": {"a": True}, "help": False})


class KeyTest(unittest.TestCase):
    def test_tab_cycles_views(self):
        self.assertEqual([press(["tab"] * n)["view"] for n in range(4)], ["queue", "plan", "history", "queue"])

    def test_digits_and_q(self):
        self.assertEqual(press(["3"])["view"], "history")
        self.assertEqual(press(["2"])["view"], "plan")
        self.assertEqual(press(["3", "1"])["view"], "queue")
        self.assertEqual(press(["3", "q"])["view"], "queue")

    def test_cursor_clamped_to_rows(self):
        self.assertEqual(press(["j"] * 5)["cursor"]["queue"], 1)            # 2 queue rows
        self.assertEqual(press(["j", "down", "k", "up", "k"])["cursor"]["queue"], 0)
        self.assertEqual(press(["2"] + ["j"] * 9)["cursor"]["plan"], 4)     # 5 plan tasks

    def test_cursor_per_view(self):
        ui = press(["j", "2", "j", "j"])
        self.assertEqual((ui["cursor"]["queue"], ui["cursor"]["plan"]), (1, 2))

    def test_enter_on_running_queue_item_opens_plan(self):
        self.assertEqual(press(["j", "enter"])["view"], "plan")
        self.assertEqual(press(["enter"])["view"], "queue")                 # row 0 is finished: nothing to open

    def test_enter_on_done_task_collapses_done(self):
        ui = press(["2", "enter"])                                          # row 0 = task 3, completed
        self.assertTrue(ui["collapsed"][tv.DONE_KEY])
        self.assertEqual(tv.model(QUEUE, ui)["rows"]["plan"], ["p:done", "p:5", "p:6", "p:7"])
        ui = press(["enter"], ui=ui)                                        # row 0 = the done line: expand
        self.assertFalse(ui["collapsed"][tv.DONE_KEY])

    def test_enter_on_open_task_does_nothing(self):
        ui = press(["2", "j", "j", "enter"])                                # task 5, in progress
        self.assertEqual(ui["collapsed"], {})

    def test_enter_toggles_history_row(self):
        ui = press(["3", "enter"])
        self.assertFalse(tu.is_collapsed(ui, "h:plan:x"))                   # history rows start collapsed
        self.assertTrue(tu.is_collapsed(ui, "h:plan:y"))

    def test_filter_cycle(self):
        self.assertEqual([press(["f"] * n)["filter"] for n in range(4)], ["all", "hide_done", "active", "all"])

    def test_filter_rows(self):
        self.assertEqual(tv.model(QUEUE, press(["f"]))["rows"]["plan"], ["p:5", "p:6", "p:7"])
        self.assertEqual(tv.model(QUEUE, press(["f", "f"]))["rows"]["plan"], ["p:5", "p:6"])

    def test_collapse_all_toggle(self):
        ui = press(["3", "c"])                                              # history: all collapsed -> expand all
        self.assertEqual([tu.is_collapsed(ui, k) for k in ("h:plan:x", "h:plan:y")], [False, False])
        ui = press(["c"], ui=ui)
        self.assertEqual([tu.is_collapsed(ui, k) for k in ("h:plan:x", "h:plan:y")], [True, True])
        ui = press(["enter", "c"], ui=ui)                                   # one open, one closed -> collapse all
        self.assertEqual([tu.is_collapsed(ui, k) for k in ("h:plan:x", "h:plan:y")], [True, True])
        ui = press(["2", "c"], ui=ui)
        self.assertTrue(tu.is_collapsed(ui, tv.DONE_KEY))
        self.assertFalse(tu.is_collapsed(press(["c"], ui=ui), tv.DONE_KEY))

    def test_help_toggle(self):
        self.assertEqual([press(["?"] * n)["help"] for n in range(3)], [False, True, False])

    def test_unknown_key_changes_nothing(self):
        ui = tu.normalize(None, QUEUE)
        self.assertEqual(press(["x", "\x00", "enter"], tasks=[], ui=ui, history=[]), ui)

    def test_argument_not_mutated(self):
        ui = tu.normalize(None, QUEUE)
        before = repr(ui)
        tu.handle_key(ui, "j", tv.model(QUEUE, ui))
        self.assertEqual(repr(ui), before)


class QueueLabelTest(unittest.TestCase):
    def test_title_fragment_note_and_fallback(self):
        t = {"docs/s/a-design.md": "Alpha", "docs/s/b-design.md#part-1": "Beta"}
        self.assertEqual(tv.queue_label("Plan & run: docs/s/a-design.md", t), "Alpha")
        self.assertEqual(tv.queue_label("Plan & run: docs/s/b-design.md#part-1", t), "Beta #part-1")
        self.assertEqual(tv.queue_label("Plan & run: docs/s/c-design.md (§4-5 only)", t), "docs/s/c-design.md (§4-5 only)")
        self.assertEqual(tv.queue_label("Plan & run: docs/s/a-design.md  (x)", t), "Alpha (x)")


if __name__ == "__main__":
    unittest.main()
