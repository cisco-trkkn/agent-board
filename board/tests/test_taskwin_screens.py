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


if __name__ == "__main__":
    unittest.main()
