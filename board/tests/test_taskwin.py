import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import taskwin  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "taskwin"
NOW = 1_000_000.0
ESC = "\x1b"


def task(i, subject, status, blocked_by=(), owner="", state="", tier=""):
    return {"id": str(i), "subject": subject, "status": status, "owner": owner, "state": state, "tier": tier,
            "blockedBy": [str(b) for b in blocked_by]}


def chain(n, status="pending", first=1, done=0):
    """Tasks first..first+n-1, each blocked by the previous one; the first `done` of them completed."""
    out = []
    for k in range(n):
        i = first + k
        out.append(task(i, f"step {i}", "completed" if k < done else status, [i - 1] if k else []))
    return out


def timing(tasks_since, started=None, events=()):
    """Timing state: {id: since} plus the plan start and events."""
    t = {i: {"status": "x", "since": s, "started": started, "done": None} for i, s in tasks_since.items()}
    return {"lead": "L", "tasks": t, "events": list(events), "all_done": False}


# Two roots (1, 2); diamond 1→3→6 and 1→5→6 with 3→4→6 the longest unfinished chain; 4 and 6 blocked;
# 5's owner is waiting; tiers mixed, incl. one that gets no badge.
SIX = {"name": "tasks-window", "active": True, "tasks": [
    task(1, "planview carries tier and blockedBy", "completed", owner="scribe", state="gone", tier="haiku"),
    task(2, "timing and celebration state", "completed", tier=""),
    task(3, "the renderer, cards and a dependency graph that is long", "in_progress", [1, 2],
         owner="painter", state="working", tier="fable"),
    task(4, "watch loop, CLI and a real run", "blocked", [3], tier="sonnet"),
    task(5, "layout opens the window", "in_progress", [1], owner="wiring", state="waiting", tier="standard"),
    task(6, "docs name the window", "blocked", [4, 5], owner="quill", state="ready", tier="fable"),
]}
SIX_TIMING = timing({"1": NOW - 3600, "2": NOW - 1800, "3": NOW - 720, "4": NOW - 720, "5": NOW - 200,
                     "6": NOW - 720}, started=NOW - 7200)


def plain(view, width=120, height=40, t=None, now=NOW, frame=0, **kw):
    return taskwin.render(view, SIX_TIMING if t is None else t, width, height, now, frame, "none", **kw)


def view_of(tasks, name="plan"):
    return {"name": name, "active": True, "tasks": tasks}


def check_plain(tc, out, width, height):
    """Width (display cells), height, no escapes and no ✗: the invariants of every colour-none render."""
    lines = out.split("\n")
    tc.assertLessEqual(len(lines), height)
    for l in lines:
        tc.assertLessEqual(taskwin.cells(l), width, repr(l))
    tc.assertNotIn(ESC, out)
    tc.assertNotIn("✗", out)


class SnapshotTest(unittest.TestCase):
    def check_plain(self, out, width, height):
        check_plain(self, out, width, height)

    def test_wide_matches_snapshot(self):
        out = plain(SIX, 120, 40, session="dev")
        self.check_plain(out, 120, 40)
        self.assertEqual(out, (FIX / "wide.txt").read_text())

    def test_narrow_matches_snapshot(self):
        out = plain(SIX, 60, 40, session="dev")
        self.check_plain(out, 60, 40)
        self.assertEqual(out, (FIX / "narrow.txt").read_text())

    def test_every_width_respects_cells_and_height(self):
        for w, h in ((40, 12), (60, 40), (79, 30), (80, 30), (100, 24), (120, 40), (200, 8)):
            out = plain(SIX, w, h)
            self.check_plain(out, w, h)
            for t in SIX["tasks"]:
                if t["status"] != "completed":
                    self.assertIn(t["id"], out)

    def test_cells_counts_wide_glyphs_as_two(self):
        self.assertEqual(taskwin.cells("🔒"), 2)
        self.assertEqual(taskwin.cells("✦ ◐ ○ ◌ ● ╭─╮"), 13)
        self.assertEqual(taskwin.cells("á"), 1)


class HeaderTest(unittest.TestCase):
    def test_header_has_name_progress_and_elapsed(self):
        head = plain(SIX).split("\n")[0]
        self.assertIn("tasks-window", head)
        self.assertIn("2/6 done", head)
        self.assertIn("2h", head)

    def test_header_falls_back_to_tasks_and_dash(self):
        v = {"name": "", "active": True, "tasks": [task(1, "one", "pending")]}
        head = plain(v, t={}).split("\n")[0]
        self.assertTrue(head.startswith("Tasks"), head)
        self.assertIn("—", head)

    def test_progress_bar_is_green_over_grey(self):
        out = taskwin.render(SIX, SIX_TIMING, 120, 40, NOW, 0, "256")
        bar = out.split("\n")[1]
        self.assertIn(taskwin.SGR["green"][1], bar)
        self.assertIn(taskwin.SGR["grey"][1], bar)


class GlyphTest(unittest.TestCase):
    def test_status_glyphs(self):
        v = view_of([task(1, "a", "completed"), task(2, "b", "in_progress"), task(3, "c", "pending"),
                     task(4, "d", "blocked", [3])])
        out = plain(v, 60, 20, t={})
        lines = out.split("\n")
        self.assertTrue(any(l.startswith("● 1") for l in lines), out)
        self.assertTrue(any(l.startswith("◐ 2") for l in lines), out)
        self.assertTrue(any(l.startswith("○ 3") for l in lines), out)
        self.assertTrue(any(l.startswith("◌ 🔒 4") for l in lines), out)

    def test_in_progress_glyph_cycles_with_frame(self):
        v = view_of([task(2, "b", "in_progress")])
        seen = [plain(v, 60, 20, t={}, frame=f).split("\n")[3][0] for f in range(4)]
        self.assertEqual(seen, ["◐", "◓", "◑", "◒"])

    def test_subject_truncated_with_ellipsis(self):
        v = view_of([task(1, "x" * 200, "pending")])
        out = plain(v, 60, 20, t={})
        self.assertIn("…", out)
        self.assertNotIn("x" * 60, out)

    def test_owner_states(self):
        v = view_of([task(1, "a", "in_progress", owner="ann", state="working"),
                     task(2, "b", "in_progress", owner="bob", state="waiting"),
                     task(3, "c", "pending", owner="cid", state="ready"),
                     task(4, "d", "pending", owner="dan", state="gone")])
        out = plain(v, 60, 20, t={})
        self.assertIn("✦ ann", out)
        self.assertIn("✦ bob needs you", out)
        self.assertIn("✦ cid idle", out)
        self.assertIn("✦ dan gone", out)

    def test_working_owner_pulses_with_frame(self):
        v = view_of([task(1, "a", "in_progress", owner="ann", state="working")])
        a, b = (plain(v, 120, 20, t={}, frame=f) for f in (0, 1))
        self.assertNotEqual(a, b)

    def test_tier_badges_only_for_known_models(self):
        v = view_of([task(1, "a", "pending", tier="haiku"), task(2, "b", "pending", tier="sonnet"),
                     task(3, "c", "pending", tier="fable"), task(4, "d", "pending", tier="opus")])
        out = plain(v, 120, 30, t={})
        for word in ("haiku", "sonnet", "fable"):
            self.assertIn(word, out)
        self.assertNotIn("opus", out)
        col = taskwin.render(v, {}, 120, 30, NOW, 0, "256")
        for word, key in (("haiku", "cyan"), ("sonnet", "blue"), ("fable", "violet")):
            self.assertIn(taskwin.SGR[key][1] + "m" + word, col.replace("\x1b[", ""))

    def test_tier_names_map_to_model_badges(self):
        v = view_of([task(1, "a", "pending", tier="mechanical"), task(2, "b", "pending", tier="standard"),
                     task(3, "c", "pending", tier="frontier")])
        out = plain(v, 120, 30, t={})
        for word in ("haiku", "sonnet", "fable"):
            self.assertIn(word, out)
        for word in ("mechanical", "standard", "frontier"):
            self.assertNotIn(word, out)
        col = taskwin.render(v, {}, 120, 30, NOW, 0, "256").replace("\x1b[", "")
        for word, key in (("haiku", "cyan"), ("sonnet", "blue"), ("fable", "violet")):
            self.assertIn(taskwin.SGR[key][1] + "m" + word, col)

    def test_time_in_status(self):
        self.assertEqual(taskwin.fmt_dur(12 * 60), "12m")
        self.assertEqual(taskwin.fmt_dur(3 * 3600 + 20 * 60), "3h 20m")
        self.assertEqual(taskwin.fmt_dur(2 * 86400 + 3600), "2d 1h")
        self.assertEqual(taskwin.fmt_dur(30), "<1m")
        out = plain(SIX, 60, 40)
        self.assertIn("12m", out)
        self.assertIn("3m", out)


class GraphTest(unittest.TestCase):
    def test_diamond_depths(self):
        tasks = [task(1, "a", "pending"), task(2, "b", "pending", [1]), task(3, "c", "pending", [1]),
                 task(4, "d", "pending", [2, 3])]
        self.assertEqual(taskwin.depths(tasks), {"1": 0, "2": 1, "3": 1, "4": 2})

    def test_unknown_blockers_ignored(self):
        tasks = [task(1, "a", "pending", [99]), task(2, "b", "pending", [1, "zz"])]
        self.assertEqual(taskwin.depths(tasks), {"1": 0, "2": 1})

    def test_cycle_renders_without_hanging(self):
        tasks = [task(1, "a", "pending", [2]), task(2, "b", "pending", [1]), task(3, "c", "pending", [2])]
        d = taskwin.depths(tasks)
        self.assertEqual(set(d), {"1", "2", "3"})
        out = plain(view_of(tasks), 120, 30, t={})
        self.assertIn("╭", out)
        self.assertIsInstance(taskwin.critical_path(tasks), list)

    def test_wide_layout_draws_cards_and_connectors(self):
        out = plain(SIX, 120, 40)
        self.assertIn("╭", out)
        self.assertIn("╰", out)
        self.assertIn("│", out)
        self.assertNotIn("⇠", out)
        self.assertEqual(len(re.findall("╭─ [●○◐◓◑◒◌]", out)), 6, out)

    def test_narrow_layout_lists_with_blocker_hints(self):
        out = plain(SIX, 60, 40)
        self.assertNotIn("╭", out)
        self.assertIn("⇠ 1,2", out)
        self.assertIn("⇠ 4,5", out)

    def test_critical_path_is_longest_unfinished_chain(self):
        tasks = chain(3, first=1) + chain(2, first=10) + [task(20, "done", "completed")]
        self.assertEqual(taskwin.critical_path(tasks), ["1", "2", "3"])
        col = taskwin.render(view_of(tasks), {}, 120, 40, NOW, 0, "truecolor")
        accent = taskwin.SGR["accent"][0]
        accented = [taskwin.strip(l) for l in col.split("\n") if accent in l]
        self.assertTrue(accented)
        for l in accented:
            self.assertNotIn("step 10", l)
            self.assertNotIn("step 11", l)
            self.assertNotRegex(l, r"\b1[01]\b")

    def test_critical_path_ignores_completed(self):
        tasks = chain(3, "completed") + chain(2, first=10)
        self.assertEqual(taskwin.critical_path(tasks), ["10", "11"])

    def test_single_unfinished_task_is_no_path(self):
        self.assertEqual(taskwin.critical_path([task(1, "a", "pending"), task(2, "b", "completed")]), [])

    def test_collapse_keeps_unfinished_visible(self):
        tasks = [task(i, f"done {i}", "completed") for i in range(1, 28)]
        tasks += [task(i, f"todo {i}", "pending", [27]) for i in range(28, 31)]
        out = plain(view_of(tasks), 120, 20, t={})
        lines = out.split("\n")
        self.assertLessEqual(len(lines), 20)
        self.assertIn("● 1–27 done", out)
        for i in (28, 29, 30):
            self.assertIn(f"todo {i}", out)
        self.assertNotIn("done 5", out)

    def test_no_collapse_when_it_fits(self):
        out = plain(SIX, 120, 40)
        self.assertNotIn("done\n", out.split("\n")[3] + "\n")
        self.assertIn("planview carries", out)

    def test_deep_chain_collapses_done_columns_for_width(self):
        # 7 columns at 120 cols would leave cards under CARD_MIN; dropping the done column 0 makes 6 fit.
        tasks = chain(7, done=3)
        out = plain(view_of(tasks), 120, 40, t={})
        check_plain(self, out, 120, 40)
        self.assertIn("╭", out)
        self.assertIn("● 1 done", out)
        self.assertEqual(len(re.findall("╭─ [●○◐◓◑◒◌] ", out)), 6, out)
        for i in range(2, 8):
            self.assertIn(f"step {i}", out)
        self.assertNotIn("⇠", out)

    def test_deep_unfinished_chain_falls_back_to_list(self):
        # 12 unfinished columns cannot fit at CARD_MIN and nothing is done to collapse: the list keeps every task.
        tasks = chain(12)
        out = plain(view_of(tasks), 80, 40, t={})
        check_plain(self, out, 80, 40)
        self.assertNotIn("╭", out)
        for i in range(1, 13):
            self.assertIn(f"step {i}", out)
        self.assertIn("⇠ 11", out)

    def test_width_and_height_collapse_share_one_summary(self):
        # column 0 goes for width (7 columns), column 1 (three done tasks, 14 rows) for height (avail 9):
        # one summary line covers both, the remaining five columns are laid out from the left edge.
        tasks = chain(7, done=3)
        tasks += [task(8, "root 8", "completed"), task(9, "root 9", "completed"),
                  task(10, "after 10", "completed", [1]), task(11, "after 11", "completed", [1])]
        out = plain(view_of(tasks), 120, 12, t={})
        check_plain(self, out, 120, 12)
        body = out.split("\n")[3:]
        self.assertEqual([l.strip() for l in body if " done" in l], ["● 1–11 done"], out)
        self.assertEqual(len(re.findall("╭─ [●○◐◓◑◒◌] ", out)), 5, out)
        for i in range(3, 8):
            self.assertIn(f"step {i}", out)
        self.assertTrue(body[1].startswith("╭─ ● 3 "), out)


class CelebrationTest(unittest.TestCase):
    def test_done_event_shows_sparkle_line_for_two_seconds(self):
        young = timing({"1": NOW - 1}, events=[{"kind": "done", "id": "1", "at": NOW - 1}])
        old = timing({"1": NOW - 3}, events=[{"kind": "done", "id": "1", "at": NOW - 3}])
        v = view_of([task(1, "a", "completed"), task(2, "b", "pending")])
        self.assertIn("✦ Task 1 done ✦", plain(v, t=young))
        self.assertNotIn("✦ Task 1 done ✦", plain(v, t=old))

    def test_done_card_is_inverse_in_colour(self):
        young = timing({"1": NOW - 1}, events=[{"kind": "done", "id": "1", "at": NOW - 1}])
        v = view_of([task(1, "a", "completed"), task(2, "b", "pending")])
        col = taskwin.render(v, young, 120, 40, NOW, 0, "256")
        self.assertIn("\x1b[7", col)

    def test_plan_done_confetti_varies_with_frame(self):
        v = view_of([task(1, "a", "completed"), task(2, "b", "completed")])
        t = timing({"1": NOW - 1, "2": NOW - 1}, events=[{"kind": "plan_done", "at": NOW - 1}])
        a, b = (plain(v, t=t, frame=f) for f in (0, 1))
        self.assertNotEqual(a, b)
        self.assertNotIn("Plan done ✓", a)

    def test_all_done_without_events_is_calm_banner(self):
        v = view_of([task(1, "a", "completed"), task(2, "b", "completed")])
        out = plain(v, t={})
        self.assertIn("Plan done ✓", out)
        self.assertEqual(plain(v, t={}, frame=0), plain(v, t={}, frame=7))

    def test_unfinished_plan_has_no_banner(self):
        self.assertNotIn("Plan done", plain(SIX))


class ColourTest(unittest.TestCase):
    def test_truecolor_uses_24bit_sequences(self):
        out = taskwin.render(SIX, SIX_TIMING, 120, 40, NOW, 0, "truecolor")
        self.assertIn("38;2;", out)
        self.assertEqual(taskwin.strip(out), plain(SIX))

    def test_256_uses_palette_sequences_only(self):
        out = taskwin.render(SIX, SIX_TIMING, 120, 40, NOW, 0, "256")
        self.assertIn("38;5;", out)
        self.assertNotIn("38;2;", out)
        self.assertEqual(taskwin.strip(out), plain(SIX))

    def test_colour_lines_reset_and_respect_width(self):
        out = taskwin.render(SIX, SIX_TIMING, 120, 40, NOW, 0, "truecolor")
        for l in out.split("\n"):
            if ESC in l:
                self.assertTrue(l.endswith("\x1b[0m"), repr(l))
            self.assertLessEqual(taskwin.cells(taskwin.strip(l)), 120)

    def test_color_mode(self):
        self.assertEqual(taskwin.color_mode({"NO_COLOR": ""}), "none")
        self.assertEqual(taskwin.color_mode({"NO_COLOR": "1", "COLORTERM": "truecolor"}), "none")
        self.assertEqual(taskwin.color_mode({"COLORTERM": "truecolor"}), "truecolor")
        self.assertEqual(taskwin.color_mode({"COLORTERM": "24bit"}), "truecolor")
        self.assertEqual(taskwin.color_mode({"TERM": "xterm-256color"}), "256")
        self.assertEqual(taskwin.color_mode({}), "256")


class EmptyTest(unittest.TestCase):
    def test_empty_view_is_idle_screen_with_session(self):
        out = plain({"name": "", "active": False, "tasks": []}, 100, 20, t={}, session="agent-board")
        self.assertIn("No tasks yet — the lead's list shows up here", out)
        self.assertIn("agent-board", out)
        self.assertLessEqual(len(out.split("\n")), 20)
        self.assertNotIn(ESC, out)

    def test_empty_view_default_session(self):
        out = plain({"name": "", "active": False, "tasks": []}, 100, 20, t={})
        self.assertIn("No tasks yet", out)


class ImportTest(unittest.TestCase):
    def test_imports_under_isolated_python(self):
        import subprocess
        r = subprocess.run([sys.executable, "-I", str(Path(taskwin.__file__))], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
