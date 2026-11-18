"""ticker: pure line builders for the Discord status line."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import ticker  # noqa: E402

NOW = 1_800_000_000.0
SPEC = "2026-11-17-discord-ticker-design"
FULL = f"wk 33% ▲0.8× · 5h 25% · ctx 23% · $12.35 · {SPEC} 2/6"


def limits(w=33, f=25, resets=NOW + 4 * 86400, age=30):
    sd = {"used_percentage": w}
    if resets is not None:
        sd["resets_at"] = resets
    return {"session_id": "s", "received_at": NOW - age, "five_hour": {"used_percentage": f}, "seven_day": sd}


def live(ctx=23, sid="L1", role="lead", cwd="/r/a"):
    return {"session_id": sid, "role": role, "cwd": cwd, "context_pct": ctx}


def tasks(status="in_progress", spec=SPEC):
    t = [{"id": "2", "subject": f"Plan & run: docs/superpowers/specs/{spec}.md", "status": status}]
    for i in range(14, 20):
        t.append({"id": str(i), "subject": f"t{i}", "status": "completed" if i in (14, 15) else "pending"})
    return t


REC = {"project": "a", "path": "/r/a", "spend_today": 12.345}


def pl(record=REC, lv=None, lim=None, lt=None, floor=13, **kw):
    return ticker.project_line(record, [live()] if lv is None else lv, limits() if lim is None else lim,
                               tasks() if lt is None else lt, NOW, floor=floor, **kw)


class ProjectLine(unittest.TestCase):
    def test_exact_fixture(self):
        self.assertEqual(pl(), FULL)

    def test_pace_dash_under_12h(self):
        self.assertIn("▲—×", pl(lim=limits(resets=NOW + 7 * 86400 - 11 * 3600)))

    def test_pace_dash_without_resets_at(self):
        self.assertIn("wk 33% ▲—× ", pl(lim=limits(resets=None)))

    def test_warn_pace(self):
        self.assertTrue(pl(lim=limits(w=65, resets=NOW + 3.5 * 86400)).startswith("⚠ wk 65% ▲1.3×"))

    def test_no_warn_pace_exactly_1_2(self):
        # elapsed 0.5, w 60 -> pace exactly 1.2
        self.assertFalse(pl(lim=limits(w=60, resets=NOW + 3.5 * 86400)).startswith("⚠"))

    def test_warn_f_80_not_79(self):
        self.assertTrue(pl(lim=limits(f=80)).startswith("⚠ "))
        self.assertFalse(pl(lim=limits(f=79)).startswith("⚠"))

    def test_warn_ctx_40_not_39(self):
        self.assertTrue(pl(lv=[live(40)]).startswith("⚠ "))
        self.assertFalse(pl(lv=[live(39)]).startswith("⚠"))

    def test_stale_limits(self):
        s = pl(lim=limits(w=99, f=99, age=601))
        self.assertTrue(s.startswith("wk ?% ▲?× · 5h ?% · "), s)

    def test_fresh_at_600(self):
        self.assertIn("wk 33%", pl(lim=limits(age=600)))

    def test_no_limits(self):
        self.assertTrue(ticker.project_line(REC, [live()], None, tasks(), NOW, floor=13).startswith("wk ?% ▲?× · 5h ?% · "))

    def test_trim_200_char_spec(self):
        s = pl(lt=tasks(spec="x" * 200))
        self.assertEqual(len(s), 128)
        self.assertIn("…", s)
        self.assertTrue(s.startswith("wk 33% ▲0.8× · 5h 25% · ctx 23% · $12.35 · x"))
        self.assertTrue(s.endswith("… 2/6"))

    def test_idle(self):
        self.assertTrue(pl(lt=tasks(status="pending")).endswith(" · idle"))

    def test_unknown_floor_no_progress(self):
        self.assertTrue(pl(floor=None).endswith(f"· {SPEC}"))

    def test_spend_not_a_number(self):
        self.assertIn("· $— · ", pl(record={**REC, "spend_today": None}))

    def test_lead_sid_wins(self):
        rows = [live(23, "L1"), live(55, "W", role="lead")]
        self.assertIn("ctx 23%", pl(lv=rows, lead_sid="L1"))

    def test_lead_without_sid_max_role_lead(self):
        rows = [live(23, "L1"), live(31, "L2"), live(90, "X", role="worker"), live(80, "O", cwd="/r/other")]
        self.assertIn("ctx 31%", pl(lv=rows))

    def test_lead_in_worktree_by_sid(self):
        rows = [live(47, "L1", role="worker", cwd="/r/a/.claude/worktrees/w")]
        self.assertIn("ctx 47%", pl(lv=rows, lead_sid="L1"))

    def test_no_lead(self):
        self.assertIn("ctx — · ", pl(lv=[live(50, cwd="/r/other")]))


class OpsLine(unittest.TestCase):
    def test_max_ctx_and_warn(self):
        recs = [{"project": "a", "path": "/r/a", "spend_today": 1.5}, {"project": "b", "path": "/r/b", "spend_today": None},
                {"project": "c", "path": "/r/c", "spend_today": 2.25}]
        lv = [live(23, "L1", cwd="/r/a"), live(41, "L2", cwd="/r/b")]
        s = ticker.ops_line(recs[:2] + recs[2:], lv, limits(), {"a": tasks(), "b": tasks(), "c": tasks("pending")}, NOW,
                            floors={"a": 13, "b": 13})
        self.assertEqual(s, "⚠ wk 33% ▲0.8× · 5h 25% · ctx max 41% b · $3.75 · 2 running")

    def test_running_with_unknown_floor_counts(self):
        s = ticker.ops_line([REC], [live()], limits(), {"a": tasks()}, NOW)
        self.assertTrue(s.endswith("· 1 running"))

    def test_no_ctx_no_spend(self):
        s = ticker.ops_line([{"project": "a", "path": "/r/a"}], [], None, {}, NOW)
        self.assertEqual(s, "wk ?% ▲?× · 5h ?% · ctx max — · $— · 0 running")

    def test_ctx_tie_first_wins(self):
        recs = [{"project": "a", "path": "/r/a"}, {"project": "b", "path": "/r/b"}]
        s = ticker.ops_line(recs, [live(30, "x", cwd="/r/a"), live(30, "y", cwd="/r/b")], None, {}, NOW)
        self.assertIn("ctx max 30% a", s)

    def test_length_cap(self):
        recs = [{"project": "p" * 300, "path": "/r/a"}]
        s = ticker.ops_line(recs, [live(30)], None, {}, NOW)
        self.assertLessEqual(len(s), 128)


if __name__ == "__main__":
    unittest.main()
