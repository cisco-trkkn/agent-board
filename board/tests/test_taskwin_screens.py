import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskwin  # noqa: E402
import taskwin_hist as th  # noqa: E402
import taskwin_ui as tu  # noqa: E402

NOW = time.mktime((2026, 11, 21, 12, 0, 0, 0, 0, -1))
RED256 = "38;5;167"


def task(i, subject, status, blocked_by=(), owner="", tier="", outcome="", answered=""):
    return {"id": str(i), "subject": subject, "status": status, "owner": owner, "state": "", "tier": tier,
            "blockedBy": [str(b) for b in blocked_by], "outcome": outcome, "answeredAt": answered, "planPath": ""}


SA = "docs/superpowers/specs/a-design.md"
QTASKS = [
    task(1, "Plan & run: " + SA, "completed", outcome="merged abc1234", answered="2026-11-21T01:00:00Z"),
    task(2, "Plan & run: docs/superpowers/specs/b-design.md#part-1", "completed", outcome="mr https://gl/x/-/merge_requests/7"),
    task(3, "Plan & run: docs/superpowers/specs/c-design.md (§4-5 only)", "completed", outcome="kept spec-c"),
    task(4, "Plan & run: docs/superpowers/specs/d-design.md", "completed", outcome="failed — residual N1"),
    task(5, "Plan & run: docs/superpowers/specs/e-design.md", "in_progress"),
    task(6, "Plan & run: docs/superpowers/specs/f-design.md", "pending"),
    task(10, "Task 1: one", "completed", owner="ann", tier="mechanical"),
    task(11, "Task 2: two", "in_progress", [10], owner="bob", tier="standard"),
    task(12, "Task 3: three", "blocked", [11]),
    task(13, "Task 4: four", "pending", [10]),
]
QTIMING = {"lead": "L", "events": [], "all_done": False, "tasks": {
    "1": {"status": "completed", "since": NOW - 7200, "started": NOW - 9000, "done": NOW - 7200},
    "5": {"status": "in_progress", "since": NOW - 600, "started": NOW - 600, "done": None},
    "11": {"status": "in_progress", "since": NOW - 720, "started": NOW - 720, "done": None}}}
CTX = {"titles": {SA: "Alpha spec", "docs/superpowers/specs/b-design.md#part-1": "Beta spec"},
       "report": "docs/superpowers/reports/2026-11-21-queue.md", "history": []}


def ui(tasks=QTASKS, **kw):
    return tu.normalize(kw, tasks)


def render(tasks=QTASKS, timing=None, width=120, height=40, color="none", u=None, ctx=None):
    return taskwin.render({"name": "2026-11-21-plan", "active": True, "tasks": tasks},
                          QTIMING if timing is None else timing, width, height, NOW, 0, color,
                          ui=ui(tasks) if u is None else u, ctx=CTX if ctx is None else ctx)


def line_with(out, text):
    return next(l for l in out.split("\n") if text in taskwin.strip(l))


class QueueScreenTest(unittest.TestCase):
    def test_tabs_name_report_in_header(self):
        first = render().split("\n")[0]
        self.assertTrue(first.startswith("[1 queue] 2 plan 3 history  Queue · docs/superpowers/reports/2026-11-21-queue.md"), first)
        self.assertTrue(render(u=ui(view="plan")).split("\n")[0].startswith("1 queue [2 plan] 3 history  2026-11-21-plan"))

    def test_active_tab_bold_in_colour(self):
        self.assertIn("\x1b[1m[1 queue]", render(color="256").split("\n")[0])

    def test_rows_title_times_outcome(self):
        out = render()
        a = line_with(out, "Alpha spec")
        self.assertIn("● Alpha spec", a)
        self.assertIn(f"{th.hm(NOW - 9000)} → {th.hm(NOW - 7200)}", a)
        self.assertIn("merged abc1234", a)
        self.assertIn("Beta spec #part-1", line_with(out, "Beta spec"))
        self.assertIn("mr https://gl/x/-/merge_requests/7", out)
        self.assertIn("docs/superpowers/specs/c-design.md (§4-5 only)", line_with(out, "kept spec-c"))  # no title: path
        self.assertIn(f"{th.hm(NOW - 600)} → …", line_with(out, "e-design.md"))
        self.assertIn("—", line_with(out, "f-design.md"))
        self.assertNotIn("Task 1: one", out.split("e-design.md")[0])   # plan tasks only under the running item

    def test_failed_outcome_red(self):
        self.assertIn(RED256, line_with(render(color="256"), "failed — residual N1"))
        self.assertNotIn(RED256, line_with(render(color="256"), "merged abc1234"))

    def test_running_item_expanded(self):
        lines = [taskwin.strip(l) for l in render().split("\n")]
        i = next(n for n, l in enumerate(lines) if "e-design.md" in l)
        self.assertEqual(lines[i + 1].strip(), "1/4 · 1 running · 1 blocked")
        self.assertEqual(lines[i + 2].strip(), "#11 Task 2: two · bob · 12m")
        self.assertIn("f-design.md", lines[i + 3])

    def test_running_item_collapsed_hides_detail(self):
        out = render(u=ui(collapsed={"q:5": True}))
        self.assertNotIn("1 running", out)

    def test_cursor_gutter(self):
        out = render(u=ui(cursor={"queue": 1}))
        self.assertTrue(taskwin.strip(line_with(out, "Beta spec")).startswith("▸ "))
        self.assertTrue(taskwin.strip(line_with(out, "Alpha spec")).startswith("  "))
        self.assertIn("\x1b[7", line_with(render(color="256", u=ui(cursor={"queue": 1})), "Beta spec"))

    def test_no_queue_hint(self):
        tasks = [t for t in QTASKS if not t["subject"].startswith("Plan & run")]
        out = render(tasks=tasks, u=ui(tasks, view="queue"))
        self.assertIn("no queue", out)
        self.assertIn("2: plan", out)

    def test_cursor_scrolls_into_view(self):
        tasks = [task(i, f"Plan & run: docs/superpowers/specs/s{i}-design.md", "pending") for i in range(1, 41)]
        out = render(tasks=tasks, height=12, u=ui(tasks, cursor={"queue": 35}))
        self.assertIn("s36-design.md", out)
        self.assertLessEqual(len(out.split("\n")), 12)

    def test_help_line_at_bottom(self):
        lines = render(height=40, u=ui(help=True)).split("\n")
        self.assertEqual(len(lines), 40)
        self.assertEqual(lines[-1], taskwin.HELP)

    def test_width_and_height_kept(self):
        for w in (40, 80, 120):
            for h in (5, 12, 40):
                lines = render(width=w, height=h).split("\n")
                self.assertLessEqual(len(lines), h)
                self.assertTrue(all(taskwin.cells(l) <= w for l in lines), (w, h))

    def test_ui_none_is_todays_render(self):
        v = {"name": "p", "active": True, "tasks": QTASKS}
        self.assertNotIn("[1 queue]", taskwin.render(v, QTIMING, 120, 40, NOW, 0, "none"))


class PlanScreenTest(unittest.TestCase):
    def test_queue_items_not_in_plan_view(self):
        out = render(u=ui(view="plan"))
        self.assertNotIn("Plan & run", out)
        self.assertIn("Task 2: two", out)

    def test_header_counts_plan_tasks_only(self):
        self.assertIn("1/4 done", render(u=ui(view="plan")).split("\n")[0])

    def test_filter_hide_done(self):
        for w in (60, 120):
            out = render(width=w, u=ui(view="plan", filter="hide_done"))
            self.assertIn("filter: hide done", out.split("\n")[0])
            self.assertNotIn("Task 1: one", out)
            self.assertIn("Task 4: four", out)

    def test_filter_active(self):
        out = render(width=60, u=ui(view="plan", filter="active"))
        self.assertIn("filter: active", out.split("\n")[0])
        self.assertIn("Task 2: two", out)
        self.assertIn("Task 3: three", out)
        self.assertNotIn("Task 4: four", out)
        self.assertNotIn("Task 1: one", out)

    def test_no_filter_note_for_all(self):
        self.assertNotIn("filter:", render(u=ui(view="plan")))

    def test_empty_filter_says_no_match(self):
        tasks = [task(1, "a", "completed")]
        out = render(tasks=tasks, u=ui(tasks, view="plan", filter="active"))
        self.assertIn("no tasks match filter: active", out)

    def test_collapsed_done_line(self):
        for w in (60, 120):
            lines = [taskwin.strip(l) for l in render(width=w, u=ui(view="plan", collapsed={"p:done": True}, cursor={"plan": 1})).split("\n")]
            self.assertEqual(lines[3].strip(), "✓ 1 done")
            self.assertFalse(any("Task 1: one" in l for l in lines))

    def test_done_line_cursor_marker(self):
        out = render(width=60, u=ui(view="plan", collapsed={"p:done": True}))
        self.assertEqual(taskwin.strip(out.split("\n")[3]).strip(), "> ✓ 1 done")
        self.assertIn("\x1b[7", render(width=60, color="256", u=ui(view="plan", collapsed={"p:done": True})).split("\n")[3])

    def test_list_cursor(self):
        out = render(width=60, u=ui(view="plan", cursor={"plan": 1}))
        self.assertRegex(taskwin.strip(line_with(out, "Task 2: two")), r"^\S >\*?11 ")
        self.assertIn("\x1b[7", line_with(render(width=60, color="256", u=ui(view="plan", cursor={"plan": 1})), "Task 2: two"))

    def test_list_cursor_inverse_covers_row_text(self):
        row = line_with(render(width=60, color="256", u=ui(view="plan", cursor={"plan": 1})), "Task 2: two")
        before_text = row.split("Task 2: two")[0]
        self.assertTrue(before_text.rindex("\x1b[7") > before_text.rfind("\x1b[0m"), row)  # inverse still on at the subject

    def test_queue_cursor_inverse_covers_row_text(self):
        row = line_with(render(color="256", u=ui(cursor={"queue": 1})), "Beta spec")
        before_text = row.split("Beta spec")[0]
        self.assertTrue(before_text.rindex("\x1b[7") > before_text.rfind("\x1b[0m"), row)

    def test_graph_cursor_heavy_corners(self):
        out = render(width=120, u=ui(view="plan", cursor={"plan": 1}))
        self.assertEqual(out.count("┏"), 1)
        self.assertRegex(line_with(out, "┏"), r" \*?11 ")

    def test_list_scrolls_to_cursor(self):
        tasks = [task(i, f"t{i}", "pending") for i in range(1, 31)]
        out = render(tasks=tasks, width=60, height=12, u=ui(tasks, view="plan", cursor={"plan": 25}))
        self.assertRegex(out, r"(?m)^\S >\*?26 ")
        self.assertLessEqual(len(out.split("\n")), 12)

    def test_plan_view_idle_without_plan_tasks(self):
        tasks = [t for t in QTASKS if t["subject"].startswith("Plan & run")]
        out = render(tasks=tasks, u=ui(tasks, view="plan"))
        self.assertIn(taskwin.IDLE_LINE, out)
        self.assertIn("[2 plan]", out.split("\n")[0])


T1 = time.mktime((2026, 11, 21, 9, 30, 0, 0, 0, -1))
HISTORY = [
    {"key": "plan:2026-11-21-b", "day": "2026-11-21", "name": "2026-11-21-b", "spec": "", "outcome": "kept spec-b",
     "ledger": "", "tasks": [{"kind": "task_done", "at": T1, "plan": "2026-11-21-b", "id": "2", "subject": "B two",
                              "owner": "ann", "tier": "standard"}]},
    {"key": "plan:2026-11-20-a", "day": "2026-11-20", "name": "2026-11-20-a", "spec": "docs/superpowers/specs/a-design.md",
     "outcome": "merged aaa1111", "ledger": "docs/superpowers/ledgers/2026-11-20-a/", "tasks": []},
    {"key": "spec:docs/superpowers/specs/c-design.md", "day": "2026-11-20", "name": "docs/superpowers/specs/c-design.md",
     "spec": "docs/superpowers/specs/c-design.md", "outcome": "", "ledger": "", "tasks": []},
]
HCTX = {"titles": {}, "report": "", "history": HISTORY}


class HistoryScreenTest(unittest.TestCase):
    def lines(self, **kw):
        out = render(ctx=HCTX, u=ui(view="history", **kw))
        return [taskwin.strip(l) for l in out.split("\n")]

    def test_grouped_by_day_newest_first(self):
        ls = self.lines()
        self.assertTrue(ls[0].startswith("1 queue 2 plan [3 history]  History"))
        body = [l for l in ls[3:] if l.strip()]
        self.assertEqual(body, ["2026-11-21",
                                "▸ 2026-11-21-b · 1 task · kept spec-b",
                                "2026-11-20",
                                "  2026-11-20-a · merged aaa1111",
                                "  docs/superpowers/specs/c-design.md · —"])

    def test_expand_shows_journaled_tasks(self):
        ls = self.lines(collapsed={"h:plan:2026-11-21-b": False})
        self.assertIn(f"    ✓ #2 B two · ann · standard · {th.hm(T1)}", ls)

    def test_expand_without_journal_shows_ledger(self):
        ls = self.lines(collapsed={"h:plan:2026-11-20-a": False}, cursor={"history": 1})
        self.assertIn("    docs/superpowers/ledgers/2026-11-20-a/", ls)
        self.assertIn("▸ 2026-11-20-a · merged aaa1111", ls)

    def test_filter_does_not_apply(self):
        self.assertEqual(self.lines(filter="active")[3:], self.lines()[3:])

    def test_failed_outcome_red(self):
        h = [dict(HISTORY[1], outcome="failed — x")]
        out = render(color="256", ctx={"titles": {}, "report": "", "history": h}, u=ui(view="history"))
        self.assertIn(RED256, line_with(out, "failed — x"))

    def test_empty_history(self):
        out = render(ctx={"titles": {}, "report": "", "history": []}, u=ui(view="history"))
        self.assertIn("no history yet", out)

    def test_history_without_tasks(self):
        out = render(tasks=[], ctx=HCTX, u=ui([], view="history"))
        self.assertIn("2026-11-21-b", out)

    def test_scrolls_to_cursor(self):
        h = [dict(HISTORY[1], key=f"plan:p{i}", name=f"p{i}", day=f"2026-10-{i:02d}") for i in range(1, 21)]
        out = render(height=10, ctx={"titles": {}, "report": "", "history": h},
                     u=ui(view="history", cursor={"history": 15}))
        self.assertIn("▸ p16 · merged aaa1111", [taskwin.strip(l) for l in out.split("\n")])
        self.assertLessEqual(len(out.split("\n")), 10)

    def test_expanded_task_without_id_or_subject_does_not_raise(self):
        h = [dict(HISTORY[0], tasks=[{"kind": "task_done", "at": T1}])]
        out = render(ctx={"titles": {}, "report": "", "history": h},
                     u=ui(view="history", collapsed={"h:plan:2026-11-21-b": False}))
        self.assertIn("✓ #", out)

    def test_cursor_inverse_covers_row_text(self):
        row = line_with(render(color="256", ctx=HCTX, u=ui(view="history")), "2026-11-21-b")
        before = row.split("kept spec-b")[0]
        self.assertTrue(before.rindex("\x1b[7") > before.rfind("\x1b[0m"), row)


if __name__ == "__main__":
    unittest.main()


BASE_TIMING = {"lead": "L", "events": [], "all_done": False, "tasks": {
    "1": {"status": "x", "since": NOW - 60, "started": NOW - 600, "done": None}}}


class BaseCompatTest(unittest.TestCase):
    """render(ui=None) returns exactly what the base (403f675) returned: the base module is loaded from git."""

    def test_render_without_ui_matches_base(self):
        import importlib.util
        import subprocess
        import tempfile
        src = subprocess.run(["git", "show", "403f675:board/taskwin.py"], capture_output=True, text=True,
                             cwd=Path(__file__).resolve().parent)
        if src.returncode:
            self.skipTest("base commit 403f675 not available")
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "taskwin_base.py"
            f.write_text(src.stdout)
            spec = importlib.util.spec_from_file_location("taskwin_base", f)
            base = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(base)
        bad = []
        for n in (0, 2, 3, 5, 12, 30):
            tasks = [task(i, f"step {i}", "completed" if i <= n // 3 else "pending", [i - 1] if i > 1 else [])
                     for i in range(1, n + 1)]
            view = {"name": "plan", "active": True, "tasks": tasks}
            for width in (40, 70, 120):
                for height in range(1, 13):
                    for color in ("none", "256"):
                        a = taskwin.render(view, BASE_TIMING, width, height, NOW, 0, color, ui=None)
                        b = base.render(view, BASE_TIMING, width, height, NOW, 0, color)
                        if a != b:
                            bad.append((n, width, height, color))
        self.assertEqual(bad, [])
