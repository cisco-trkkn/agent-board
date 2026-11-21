"""discord_feed core: spool writer, feed file, status card, audit. Every test runs on a TC_STATE temp dir."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_feed as df  # noqa: E402
import tc_env  # noqa: E402
from overview import RECORD_KEYS  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.dir = tc_env.discord_dir("proj")


class PathsTest(Base):
    def test_paths(self):
        self.assertEqual(tc_env.agent_base(), Path(self.tmp.name))
        self.assertEqual(self.dir, Path(self.tmp.name) / "discord" / "proj")
        self.assertEqual(tc_env.feed_path("proj"), Path(self.tmp.name) / "feed" / "proj.jsonl")

    def test_default_base(self):
        with mock.patch.dict(os.environ, {"HOME": "/h"}):
            os.environ.pop("TC_STATE")
            self.assertEqual(tc_env.agent_base(), Path("/h/.local/state/agent-board"))


def post(text="x", tier="progress", mention=False, **kw):
    return {"op": "post", "text": text, "tier": tier, "mention_user": mention, **kw}


class OutboxTest(Base):
    def names(self):
        return sorted(p.name for p in (self.dir / "outbox").glob("*.json"))

    def test_name_shape_and_order(self):
        for i in range(30):
            df.outbox_write(self.dir, post(str(i)))
        names = self.names()
        self.assertEqual(len(names), 30)
        for n in names:
            stem = n[:-5]
            ts, _, hid = stem.partition("-")
            self.assertEqual((len(ts), len(hid)), (13, 8))
            int(ts), int(hid, 16)
        texts = [json.loads((self.dir / "outbox" / n).read_text())["text"] for n in names]
        self.assertEqual(texts, [str(i) for i in range(30)])
        self.assertFalse(list((self.dir / "outbox").glob("*.tmp")))

    def test_order_when_clock_goes_back(self):
        with mock.patch("time.time", return_value=1700000000.0):
            for i in range(5):
                df.outbox_write(self.dir, post(str(i)))
        texts = [json.loads((self.dir / "outbox" / n).read_text())["text"] for n in self.names()]
        self.assertEqual(texts, [str(i) for i in range(5)])

    def test_two_threads_distinct_names_in_order_per_thread(self):
        import threading
        names = {0: [], 1: []}

        def work(k):
            for i in range(200):
                names[k].append(df.outbox_write(self.dir, post(f"{k}-{i}")).name)
        # the cap would delete files; read names from the return values only
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)   # make a thread switch inside the name generation likely
        self.addCleanup(sys.setswitchinterval, old)
        with mock.patch.object(df, "CAP", 10 ** 6), mock.patch.object(df.time, "time", side_effect=lambda: 1700000000.0):
            ts = [threading.Thread(target=work, args=(k,)) for k in (0, 1)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        allnames = names[0] + names[1]
        self.assertEqual(len(set(allnames)), 400)
        self.assertEqual(len({n.split("-")[0] for n in allnames}), 400)   # distinct ms: order never rests on the random hex
        for k in (0, 1):
            self.assertEqual(names[k], sorted(names[k]))

    def test_validation(self):
        bad = [{"op": "nope"}, {"op": "card", "text": "t", "extra": 1}, {"op": "card"},
               post(tier="routine"), post(tier="loud"), {"op": "thread", "key": "k"},
               {"op": "archive", "key": "k", "x": 1}, "notadict",
               {"op": "post", "text": "x", "tier": "progress"}]
        for op in bad:
            with self.assertRaises(ValueError, msg=str(op)):
                df.outbox_write(self.dir, op)
        self.assertFalse((self.dir / "outbox").exists() and self.names())

    def test_valid_shapes(self):
        for op in (post(thread_key="t", link_thread_key="t", files=["/a"]), {"op": "card", "text": "c"},
                   {"op": "thread", "key": "k", "title": "T"}, {"op": "archive", "key": "k"}):
            df.outbox_write(self.dir, op)
        self.assertEqual(len(self.names()), 4)

    def test_cap_keeps_mentions(self):
        kinds = []
        for i in range(205):
            if i % 5 == 0:
                op = post(f"m{i}", tier="critical", mention=True)
            elif i % 3 == 0:
                op = {"op": "card", "text": f"c{i}"}
            else:
                op = post(f"p{i}")
            kinds.append(op)
            df.outbox_write(self.dir, op)
        names = self.names()
        self.assertEqual(len(names), 200)
        texts = [json.loads((self.dir / "outbox" / n).read_text()).get("text") for n in names]
        for i in range(0, 205, 5):
            self.assertIn(f"m{i}", texts)
        # cards went first: the oldest card is gone before any non-card, non-mention survivor was lost
        self.assertNotIn("c3", texts)
        self.assertIn("p1", texts)

    def test_cap_oldest_mention_survives_without_cards(self):
        df.outbox_write(self.dir, post("M", tier="decision", mention=True))
        for i in range(204):
            df.outbox_write(self.dir, post(f"p{i}"))
        texts = [json.loads((self.dir / "outbox" / n).read_text())["text"] for n in self.names()]
        self.assertEqual(len(texts), 200)
        self.assertIn("M", texts)
        self.assertNotIn("p0", texts)

    def test_cap_keeps_structural_ops(self):
        df.outbox_write(self.dir, {"op": "thread", "key": "k", "title": "T"})
        df.outbox_write(self.dir, {"op": "archive", "key": "old"})
        for i in range(205):
            df.outbox_write(self.dir, post(f"p{i}"))
        ops = [json.loads((self.dir / "outbox" / n).read_text()) for n in self.names()]
        self.assertEqual(len(ops), 200)
        self.assertEqual([o["op"] for o in ops if o["op"] in ("thread", "archive")], ["thread", "archive"])

    def test_prompt_and_edit_shapes(self):
        pr = {"op": "prompt", "key": "%1:ab", "window": "w", "tool": "Bash command", "lines": ["a", "b"], "tier": "decision", "mention_user": True}
        df.outbox_write(self.dir, pr)
        df.outbox_write(self.dir, {"op": "edit", "key": "%1:ab", "text": "t"})
        self.assertEqual(len(self.names()), 2)
        bad = [{k: v for k, v in pr.items() if k != "tool"}, {**pr, "x": 1}, {**pr, "lines": "a"}, {**pr, "lines": [1]},
               {**pr, "tier": "loud"}, {**pr, "mention_user": "yes"}, {**pr, "key": 3},
               {"op": "edit", "key": "k"}, {"op": "edit", "key": "k", "text": "t", "x": 1}, {"op": "edit", "key": "k", "text": 5}]
        for op in bad:
            with self.assertRaises(ValueError, msg=str(op)):
                df.outbox_write(self.dir, op)
        self.assertEqual(len(self.names()), 2)

    def test_cap_keeps_prompt_and_edit(self):  # mutation: drop them in _enforce_cap -> they vanish
        df.outbox_write(self.dir, {"op": "prompt", "key": "k", "window": "w", "tool": "t", "lines": ["l"], "tier": "decision", "mention_user": True})
        df.outbox_write(self.dir, {"op": "edit", "key": "k", "text": "e"})
        for i in range(205):
            df.outbox_write(self.dir, post(f"p{i}"))
        ops = [json.loads((self.dir / "outbox" / n).read_text()) for n in self.names()]
        self.assertEqual(len(ops), 200)
        self.assertEqual([o["op"] for o in ops if o["op"] in ("prompt", "edit")], ["prompt", "edit"])

    def test_dialog_and_edit_rows_shapes(self):
        b = {"label": "1. Yes", "style": 1, "custom_id": "ab:dlg:p1-0123456789abcdef:1"}
        dlg = {"op": "dialog", "key": "p1-0123456789abcdef", "text": "t", "rows": [[b]], "mention_user": True}
        df.outbox_write(self.dir, dlg)
        df.outbox_write(self.dir, {"op": "edit", "key": "k", "text": "t", "rows": [[b] * 5] * 5})
        self.assertEqual(len(self.names()), 2)
        bad = [{**dlg, "rows": [[b]] * 6}, {**dlg, "rows": [[b] * 6]}, {**dlg, "rows": [[{**b, "style": "1"}]]},
               {**dlg, "rows": [[{**b, "style": True}]]}, {**dlg, "rows": [[{**b, "custom_id": "x" * 101}]]},
               {**dlg, "rows": [[{**b, "label": 3}]]}, {**dlg, "rows": [[{"label": "a", "style": 1}]]},
               {**dlg, "rows": [b]}, {**dlg, "rows": "x"},
               {k: v for k, v in dlg.items() if k != "mention_user"}, {**dlg, "mention_user": "yes"}, {**dlg, "x": 1},
               {"op": "edit", "key": "k", "text": "t", "rows": [[b]] * 6},
               {"op": "edit", "key": "k", "text": "t", "rows": [[{**b, "custom_id": "x" * 101}]]}]
        for op in bad:
            with self.assertRaises(ValueError, msg=str(op)):
                df.outbox_write(self.dir, op)
        self.assertEqual(len(self.names()), 2)

    def test_cap_keeps_dialog(self):  # mutation: leave dialog out of _enforce_cap's keep list -> the oldest op, the dialog, is the one removed
        b = {"label": "1. Yes", "style": 1, "custom_id": "ab:dlg:p1-0123456789abcdef:1"}
        df.outbox_write(self.dir, {"op": "dialog", "key": "p1-0123456789abcdef", "text": "t", "rows": [[b]], "mention_user": False})
        for i in range(205):
            df.outbox_write(self.dir, post(f"p{i}"))
        ops = [json.loads((self.dir / "outbox" / n).read_text()) for n in self.names()]
        self.assertEqual(len(ops), 200)
        self.assertEqual([o["op"] for o in ops if o["op"] == "dialog"], ["dialog"])

    def test_cap_keeps_ireply(self):  # mutation: leave ireply out of _enforce_cap's keep list -> the oldest op, the ireply, is the one removed
        df.outbox_write(self.dir, {"op": "ireply", "iid": "1", "content": "restarted"})
        for i in range(205):
            df.outbox_write(self.dir, post(f"p{i}"))
        ops = [json.loads((self.dir / "outbox" / n).read_text()) for n in self.names()]
        self.assertEqual(len(ops), 200)
        self.assertEqual([o["op"] for o in ops if o["op"] == "ireply"], ["ireply"])

    def test_cap_drops_non_mention_after_cards(self):
        for i in range(201):
            df.outbox_write(self.dir, post(f"p{i}"))
        texts = [json.loads((self.dir / "outbox" / n).read_text())["text"] for n in self.names()]
        self.assertEqual(len(texts), 200)
        self.assertNotIn("p0", texts)
        self.assertIn("p200", texts)


class FeedTest(Base):
    def test_append_and_read(self):
        df.append_event("proj", {"ts": 1.5, "project": "proj", "spec": "s", "kind": "task_done", "tier": "progress", "text": "t"})
        ev, off = df.read_events("proj", 0)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["refs"], {})
        self.assertEqual(set(ev[0]), {"ts", "project", "spec", "kind", "tier", "text", "refs"})
        self.assertEqual(df.read_events("proj", off), ([], off))

    def test_extra_key_dropped_missing_key_error(self):
        df.append_event("proj", {"ts": 1.0, "project": "p", "spec": "s", "kind": "k", "tier": "progress", "text": "t", "zzz": 1, "refs": {"task": "3"}})
        ev, _ = df.read_events("proj", 0)
        self.assertNotIn("zzz", ev[0])
        self.assertEqual(ev[0]["refs"], {"task": "3"})
        with self.assertRaises(ValueError):
            df.append_event("proj", {"ts": 1.0})

    def test_torn_last_line(self):
        f = tc_env.feed_path("proj")
        f.parent.mkdir(parents=True)
        whole = json.dumps({"ts": 1.0, "project": "p", "spec": "s", "kind": "k", "tier": "progress", "text": "a", "refs": {}})
        f.write_text(whole + "\n" + whole[:20])
        ev, off = df.read_events("proj", 0)
        self.assertEqual(len(ev), 1)
        self.assertEqual(off, len(whole) + 1)
        with open(f, "a") as fh:
            fh.write(whole[20:] + "\n")
        ev, off2 = df.read_events("proj", off)
        self.assertEqual(len(ev), 1)
        self.assertEqual(off2, f.stat().st_size)

    def test_missing_file(self):
        self.assertEqual(df.read_events("nope", 0), ([], 0))


def rec(plan=None, needs=None, agents=None):
    r = dict.fromkeys(RECORD_KEYS)
    r.update(project="proj", plan=plan or {"name": "", "active": False, "done": 0, "total": 0, "in_progress": []},
             needs_you=needs or [], agents=agents or [])
    return r


def task(i, subject, status="pending", owner="", tier=None):
    t = {"id": str(i), "subject": subject, "status": status, "owner": owner}
    if tier:
        t["description"] = f"x\n```json:metadata\n{{\"modelTier\": \"{tier}\"}}\n```"
    return t


NOW = 1700000000.0
HHMM = __import__("time").strftime("%H:%M", __import__("time").localtime(NOW))


class CardTest(unittest.TestCase):
    def test_idle(self):
        t = df.render_card(rec(), [], NOW)
        self.assertTrue(t.startswith("```\n") and t.endswith("\n```"))
        self.assertIn("queue: idle", t)
        self.assertIn("waiting on you: none", t)
        self.assertIn(f"updated {HHMM}", t)

    def test_paused(self):
        lead = [task(1, "Plan & run: docs/superpowers/specs/a.md")]
        self.assertIn("queue: paused", df.render_card(rec(), lead, NOW))

    def test_running_k_of_n(self):
        lead = [task(1, "Plan & run: docs/superpowers/specs/a.md", "completed"),
                task(2, "Plan & run: docs/superpowers/specs/2026-11-16-b.md", "in_progress"),
                task(3, "Plan & run: docs/superpowers/specs/c.md"),
                task(4, "Task 1: feed core", "completed", tier="standard"),
                task(5, "Task 2: node bridge", "in_progress", "bv-node", "frontier"),
                task(6, "Task 3: docs")]
        t = df.render_card(rec(), lead, NOW, floor=0)
        self.assertIn("queue: running 2026-11-16-b (tasks 1/3 · spec 2 of 3)", t)
        self.assertIn("✓ Task 1: feed core", t)
        self.assertRegex(t, r"▶ Task 2: node bridge .*bv-node.*frontier")
        self.assertIn("· Task 3: docs", t)
        self.assertNotIn("Plan & run: docs", t.split("\n", 2)[2])

    def test_agents_and_needs(self):
        ag = [{"window": "bv-node", "pane": "%1", "state": "working"}, {"window": "bv-py", "pane": "%2", "state": "ready"}]
        ne = [{"window": "lead", "pane": "%0", "kind": "permission", "reason": "r"}]
        t = df.render_card(rec(needs=ne, agents=ag), [], NOW)
        self.assertIn("bv-node busy", t)
        self.assertIn("bv-py idle", t)
        self.assertIn("waiting on you:", t)
        self.assertIn("lead", t.split("waiting on you:")[1])
        self.assertNotIn("none", t.split("waiting on you:")[1])

    def test_cap(self):
        lead = [task(1, "Plan & run: s.md", "in_progress")] + [task(i + 10, f"Task {i}: " + "w" * 30, "pending") for i in range(60)]
        t = df.render_card(rec(), lead, NOW)
        self.assertLessEqual(len(t), 1900)
        self.assertTrue(t.endswith("\n```"))
        self.assertTrue([l for l in t.split("\n") if __import__("re").fullmatch(r"… \d+ more", l)])
        self.assertIn(f"updated {HHMM}", t)

    def test_floor_limits_task_lines_to_the_running_spec(self):
        # real-shaped list: #2 completed fix wave from before the spec, #17.. the spec's tasks
        lead = [task(1, "Plan & run: a.md", "completed"), task(2, "EA part 1: final-review fix wave", "completed"),
                task(3, "Plan & run: b.md", "in_progress"), task(17, "BV Task 1", "in_progress", "bv-zsh"), task(18, "BV Task 2", "completed"),
                task(19, "BV Task 3")]
        t = df.render_card(rec(), lead, NOW, floor=16)
        self.assertNotIn("EA part 1", t)
        for s in ("▶ BV Task 1", "✓ BV Task 2", "· BV Task 3"):
            self.assertIn(s, t)
        nofloor = df.render_card(rec(), lead, NOW)   # no floor known: only tasks that are not completed
        self.assertNotIn("EA part 1", nofloor)
        self.assertNotIn("BV Task 2", nofloor)
        self.assertIn("BV Task 1", nofloor)

    def test_small_not_cut(self):
        self.assertNotIn("more", df.render_card(rec(), [], NOW))


class SpecProgressTest(Base):
    def lead(self):
        runs = [task(i, f"Plan & run: docs/superpowers/specs/s{i}.md", "in_progress" if i == 2 else "completed") for i in range(2, 14)]
        own = [task(i, f"Task {i}", "completed" if i < 16 else "pending") for i in range(14, 20)]
        old = [task(1, "EA fix wave", "completed")]   # before the spec: at or below the floor
        return old + runs + own

    def test_progress_counts_own_tasks_above_floor(self):
        # mutation: drop the `> floor` filter -> total includes the 12 runs and fails
        self.assertEqual(df.spec_progress(self.lead(), 13), (2, 6))

    def test_progress_none_without_floor(self):
        self.assertIsNone(df.spec_progress(self.lead(), None))

    def test_card_shows_tasks_and_spec(self):
        t = df.render_card(rec(), self.lead(), NOW, floor=13)
        self.assertIn("queue: running s2 (tasks 2/6 · spec 1 of 12)", t)

    def test_card_without_floor(self):
        t = df.render_card(rec(), self.lead(), NOW)
        self.assertIn("queue: running s2 (spec 1 of 12)", t)

    def test_spec_floor_reads_feed_state(self):
        self.dir.mkdir(parents=True)
        (self.dir / "feed-state.json").write_text(json.dumps({"running_thread_key": "3", "spec_floor": {"3": 13}}))
        self.assertEqual(df.spec_floor("proj"), 13)

    def test_spec_floor_none_when_absent_or_not_int(self):
        self.assertIsNone(df.spec_floor("proj"))
        self.dir.mkdir(parents=True)
        (self.dir / "feed-state.json").write_text(json.dumps({"running_thread_key": "3", "spec_floor": {"3": None}}))
        self.assertIsNone(df.spec_floor("proj"))
        (self.dir / "feed-state.json").write_text(json.dumps({"running_thread_key": "3", "spec_floor": {"3": True}}))
        self.assertIsNone(df.spec_floor("proj"))


class PresenceCheckTest(unittest.TestCase):
    def test_valid(self):
        df._check({"op": "presence", "text": "x"})
        df._check({"op": "presence", "text": "x" * 128})

    def test_invalid(self):
        for op in ({"op": "presence", "text": ""}, {"op": "presence", "text": "x" * 129}, {"op": "presence", "text": 5},
                   {"op": "presence", "text": "x", "extra": "y"}, {"op": "presence"}):
            with self.assertRaises(ValueError, msg=str(op)):
                df._check(op)


class SelectCheckTest(unittest.TestCase):
    def sel(self, n=2, **kw):
        s = {"custom_id": "ab:ops:spec:a", "placeholder": "Pick a spec", "options": [{"label": f"l{i}", "value": str(i)} for i in range(n)]}
        s.update(kw)
        return {"op": "post", "text": "t", "tier": "progress", "mention_user": False, "select": s}

    def test_valid(self):
        df._check(self.sel(2))
        df._check(self.sel(25))

    def test_invalid(self):
        bad = [self.sel(26), {**self.sel(), "select": "no"}, self.sel(custom_id="c" * 101), self.sel(options=[{"label": "l" * 101, "value": "v"}]),
               self.sel(options=[{"label": "l", "value": "v" * 101}]), self.sel(options=[{"label": "l"}])]
        no_id = self.sel(); del no_id["select"]["custom_id"]
        for op in bad + [no_id]:
            with self.assertRaises(ValueError, msg=str(op)[:80]):
                df._check(op)


class IreplyCheckTest(unittest.TestCase):
    ROW = [[{"label": "Enter code", "style": 1, "custom_id": "ab:gauth:code:alpha"}]]

    def test_valid(self):
        df._check({"op": "ireply", "iid": "123", "content": "hi"})
        df._check({"op": "ireply", "iid": "123", "content": "hi", "components": self.ROW})
        df._check({"op": "ireply", "iid": "123", "content": "hi", "private": True})

    def test_invalid(self):
        for op in ({"op": "ireply", "iid": "123"}, {"op": "ireply", "content": "hi"},
                   {"op": "ireply", "iid": 5, "content": "hi"}, {"op": "ireply", "iid": "1", "content": "hi", "extra": "y"},
                   {"op": "ireply", "iid": "1", "content": "hi", "components": [[{"label": "x"}]]},
                   {"op": "ireply", "iid": "1", "content": "hi", "components": "no"},
                   {"op": "ireply", "iid": "1", "content": "hi", "private": "yes"}):
            with self.assertRaises(ValueError, msg=str(op)):
                df._check(op)


class DueTest(unittest.TestCase):
    def test_due(self):
        st = {"card_text": "a", "card_ts": 1000.0}
        self.assertIsNone(df.card_op_due(st, "a", 1300.0))
        self.assertIsNone(df.card_op_due(st, "b", 1029.0))
        self.assertEqual(df.card_op_due(st, "b", 1030.0), {"op": "card", "text": "b"})
        self.assertEqual(df.card_op_due({}, "b", NOW), {"op": "card", "text": "b"})


class AuditTest(Base):
    def test_audit(self):
        df.audit_append(self.dir, "u1", "pause", "x" * 200, "ok")
        line = json.loads((self.dir / "audit.jsonl").read_text().splitlines()[0])
        self.assertEqual(set(line), {"ts", "user", "action", "target", "result"})
        self.assertEqual(len(line["target"]), 80)
        self.assertRegex(line["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual((line["user"], line["action"], line["result"]), ("u1", "pause", "ok"))
        df.audit_append(self.dir, "u1", "a", "t", "r")
        self.assertEqual(len((self.dir / "audit.jsonl").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()


# ---- Task 4: derivation, dedupe, ops, tick ----
import copy  # noqa: E402
import fcntl  # noqa: E402
import importlib  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "discord_feed"
PLAN = "docs/superpowers/plans/2026-11-16-discord-bridge-visibility.md"
PBASE = "2026-11-16-discord-bridge-visibility"
SPEC = "2026-11-11-discord-bridge-visibility-design"


def fx(name, **over):
    d = json.loads((FIX / "tasks" / name).read_text())
    d.update(over)
    return d


def primed():
    return {"primed": True, "seen": []}


class PresenceDueTest(unittest.TestCase):
    def test_due(self):
        st = {"presence_text": "a", "presence_ts": 1000.0}
        self.assertIsNone(df.presence_op_due(st, "a", 1300.0, {"presence": "a"}))
        self.assertIsNone(df.presence_op_due(st, "b", 1059.0))
        self.assertEqual(df.presence_op_due(st, "b", 1060.0), {"op": "presence", "text": "b"})
        self.assertEqual(df.presence_op_due({}, "b", NOW), {"op": "presence", "text": "b"})

    def test_bridge_lost_presence(self):
        # mutation: drop the >= PRESENCE_EVERY check on the bridge branch -> the 59 s assertion fails
        st = {"presence_text": "a", "presence_ts": 1000.0}
        self.assertIsNone(df.presence_op_due(st, "a", 1059.0, {"presence": "old"}))
        self.assertEqual(df.presence_op_due(st, "a", 1060.0, {"presence": "old"}), {"op": "presence", "text": "a"})
        self.assertIsNone(df.presence_op_due(st, "a", 9999.0, {"presence": "a"}))
        self.assertEqual(df.presence_op_due(st, "a", 1060.0, None), {"op": "presence", "text": "a"})
        self.assertEqual(df.presence_op_due(st, "a", 1060.0, {}), {"op": "presence", "text": "a"})
        self.assertIsNone(df.presence_op_due(st, "a", 1059.0, {}))


class DeriveBase(Base):
    def setUp(self):
        super().setUp()
        self.root = Path(self.tmp.name) / "repo"
        (self.root / "docs/superpowers/plans").mkdir(parents=True)
        (self.root / PLAN).write_text("# P\n### Task 1: a\n### Task 2: b\n### Task 3: c\nnot ### Task 4\n")
        self.run_task = fx("3.json")
        self.sub = fx("19.json", status="completed")

    def derive(self, tasks, state, now=NOW):
        return df.derive("proj", self.root, tasks, state, now)

    def ledger(self, src, plan_base=PBASE):
        d = self.root / ".superpowers" / "sdd" / plan_base
        d.mkdir(parents=True, exist_ok=True)
        (d / "progress.md").write_text((FIX / "ledgers" / src / "progress.md").read_text())


class TriggerTest(DeriveBase):
    def kinds(self, evs):
        return [e["kind"] for e in evs]

    def test_spec_started_and_plan_written(self):
        evs, st = self.derive([self.run_task], primed())
        self.assertEqual(self.kinds(evs), ["spec_started", "plan_written"])
        self.assertEqual(evs[0]["refs"]["thread_key"], "3")
        self.assertEqual(evs[0]["spec"], SPEC)
        self.assertEqual(evs[0]["tier"], "progress")
        self.assertEqual(evs[1]["text"], "plan written: 3 tasks")
        self.assertEqual(set(evs[0]), set(df.EVENT_KEYS))
        self.assertEqual(st["running_thread_key"], "3")
        ops = df.ops_for_events(evs, st)
        self.assertEqual(ops[0], {"op": "thread", "key": "3", "title": SPEC})
        self.assertEqual([o["op"] for o in ops], ["thread", "post", "post"])
        self.assertTrue(all(o["thread_key"] == "3" and o["mention_user"] is False for o in ops[1:]))

    def test_part_suffix_kept(self):
        t = fx("1.json", status="in_progress")
        evs, _ = self.derive([t], primed())
        self.assertEqual(evs[0]["spec"], "2026-11-12-execution-analytics-design#part-1")
        self.assertEqual(df.ops_for_events(evs, {})[0]["title"], "2026-11-12-execution-analytics-design#part-1")

    def test_plan_in_worktree_and_late_file(self):
        (self.root / PLAN).unlink()
        evs, st = self.derive([self.run_task], primed())
        self.assertEqual(self.kinds(evs), ["spec_started"])
        wt = self.root / ".claude/worktrees/w1" / PLAN
        wt.parent.mkdir(parents=True)
        wt.write_text("### Task 1: a\n### Task 2: b\n")
        evs, st = self.derive([self.run_task], st)
        self.assertEqual([e["text"] for e in evs], ["plan written: 2 tasks"])

    def test_no_plan_metadata_no_plan_written(self):
        t = self.run_task
        t["metadata"].pop("plan")
        evs, _ = self.derive([t], primed())
        self.assertEqual(self.kinds(evs), ["spec_started"])

    def test_task_done_only_while_run_in_progress(self):
        evs, st = self.derive([self.sub], primed())
        self.assertEqual(evs, [])
        evs, st = self.derive([self.run_task, self.sub], primed())
        done = [e for e in evs if e["kind"] == "task_done"]
        self.assertEqual([e["text"] for e in done], ["✓ BV Task 3: feed core (spool, feed file, card)"])
        self.assertEqual(done[0]["refs"]["task"], "19")
        self.assertEqual(done[0]["refs"]["thread_key"], "3")

    def test_out_of_order_completed_first_emits_once(self):
        st = primed()
        evs, st = self.derive([self.run_task, self.sub], st)
        self.assertEqual(sum(e["kind"] == "task_done" for e in evs), 1)
        for _ in range(3):
            evs, st = self.derive([self.run_task, self.sub], st)
            self.assertEqual(evs, [])
        # and the usual order: seen in_progress, later completed
        st = primed()
        run = self.run_task
        ip = fx("19.json", status="in_progress")
        _, st = self.derive([run, ip], st)
        evs, st = self.derive([run, self.sub], st)
        self.assertEqual(sum(e["kind"] == "task_done" for e in evs), 1)

    def test_review_lines_real_ledgers(self):
        for src, n, line in (("ea1", 17, "Task 1: complete (commits b869c53..1bf9a9a, review clean)"),
                             ("drt", 14, "Task 7: complete (commits 22b8f60..4e9d2cf, review clean)")):
            with self.subTest(src):
                self.ledger(src)
                st = primed()
                evs, st = self.derive([self.run_task], st)
                rev = [e for e in evs if e["kind"] == "review"]
                self.assertEqual(len(rev), n)
                self.assertIn("review: " + line, [e["text"] for e in rev])
                self.assertTrue(all(e["text"].startswith("review: ") and len(e["text"]) <= 300 for e in rev))
                self.assertEqual(self.derive([self.run_task], st)[0], [])

    def test_review_ledger_in_worktree_and_long_line(self):
        d = self.root / ".claude/worktrees/w9/.superpowers/sdd" / PBASE
        d.mkdir(parents=True)
        (d / "progress.md").write_text("Task 9: complete " + "x" * 500 + "\nTask 9: dispatched\nbatch noise\n")
        evs, _ = self.derive([self.run_task], primed())
        rev = [e for e in evs if e["kind"] == "review"]
        self.assertEqual(len(rev), 1)
        self.assertEqual(len(rev[0]["text"]), 300)

    def test_outcome_merged_archives(self):
        done = fx("1.json")
        evs, st = self.derive([done], primed())
        self.assertEqual(self.kinds(evs), ["spec_outcome"])
        self.assertEqual(evs[0]["text"], "merged 1e3772f")
        self.assertEqual(evs[0]["tier"], "progress")
        ops = df.ops_for_events(evs, st)
        self.assertEqual([o["op"] for o in ops], ["post", "archive"])
        self.assertEqual(ops[0]["thread_key"], "1")
        self.assertEqual(ops[1]["key"], "1")

    def test_outcome_failed_is_critical_home_with_mention(self):
        done = fx("1.json")
        done["metadata"]["outcome"] = "failed — tests red"
        evs, st = self.derive([done], primed())
        self.assertEqual(evs[0]["tier"], "critical")
        ops = df.ops_for_events(evs, st)
        self.assertEqual(ops[0], {"op": "post", "text": "failed — tests red", "tier": "critical", "mention_user": True, "link_thread_key": "1"})
        self.assertEqual(ops[1]["text"], "failed — no failing test run recorded")   # no run record in this fixture
        self.assertEqual(ops[2], {"op": "archive", "key": "1"})

    def test_report_written_home_channel(self):
        r = self.root / "docs/superpowers/reports"
        r.mkdir(parents=True)
        (r / "2026-11-16-queue.md").write_text("# Queue report 2026-11-16\n\nbody\n")
        evs, st = self.derive([], primed())
        self.assertEqual(self.kinds(evs), ["report_written"])
        self.assertIn("Queue report 2026-11-16", evs[0]["text"])
        op = df.ops_for_events(evs, {"running_thread_key": "3"})[0]
        self.assertNotIn("thread_key", op)
        self.assertEqual(self.derive([], st)[0], [])

    def test_first_run_baselines_history(self):
        self.ledger("ea1")
        r = self.root / "docs/superpowers/reports"
        r.mkdir(parents=True)
        (r / "old-queue.md").write_text("# old\n")
        evs, st = self.derive([self.run_task, self.sub, fx("1.json")], {})
        self.assertEqual(self.kinds(evs), ["spec_started", "plan_written"])
        self.assertTrue(st["primed"])
        self.assertEqual(self.derive([self.run_task, self.sub, fx("1.json")], st)[0], [])


class DedupeTest(DeriveBase):
    def test_empty_task_list_does_not_prime(self):
        # a board that starts before the lead's task dir resolves reads []; the next poll must still baseline history
        self.ledger("ea1")
        evs, st = self.derive([], {})
        self.assertEqual(evs, [])
        self.assertFalse(st.get("primed"))
        evs, st = self.derive([self.run_task, self.sub, fx("1.json")], st)
        self.assertEqual([e["kind"] for e in evs], ["spec_started", "plan_written"])
        self.assertTrue(st["primed"])

    def real_list(self):
        t = [fx("1.json"), fx("19.json", id="2", status="completed", subject="EA fix wave"), self.run_task]
        t += [fx("19.json", id=str(i), status="completed" if i < 20 else "pending", subject=f"BV Task {i - 16}") for i in range(17, 25)]
        return t

    def test_floor_for_a_spec_first_seen_already_running_uses_the_plan_task_count(self):
        lead = self.real_list()   # plan file has 3 "### Task" headings in this fixture root
        _, st = self.derive(lead, {})
        self.assertEqual(st["spec_floor"], {"3": 21})   # the 3 highest ids: 22, 23, 24
        card = df.render_card(rec(), lead, NOW, st["spec_floor"]["3"])
        self.assertNotIn("EA fix wave", card)
        self.assertIn("BV Task 7", card)
        self.assertNotIn("BV Task 1\n", card)
        _, st2 = self.derive(lead + [fx("19.json", id="30")], st)
        self.assertEqual(st2["spec_floor"], {"3": 21})   # stable afterwards

    def test_floor_eight_task_plan_shows_17_to_24_not_2(self):
        (self.root / PLAN).write_text("".join(f"### Task {i}: x\n" for i in range(1, 9)))
        lead = self.real_list()
        _, st = self.derive(lead, {})
        self.assertEqual(st["spec_floor"], {"3": 16})
        card = df.render_card(rec(), lead, NOW, 16)
        self.assertNotIn("EA fix wave", card)
        self.assertEqual(card.count("BV Task"), 8)

    def test_no_plan_metadata_means_no_floor_on_first_sight(self):
        lead = self.real_list()
        lead[2]["metadata"].pop("plan")
        _, st = self.derive(lead, {})
        self.assertEqual(st["spec_floor"], {"3": None})
        card = df.render_card(rec(), lead, NOW, None)
        self.assertNotIn("EA fix wave", card)
        _, st = self.derive(lead, st)
        self.assertEqual(st["spec_floor"], {"3": None})   # not replaced by a max-id floor later

    def test_spec_floor_recorded_once_per_spec(self):
        tasks = [self.run_task, fx("19.json", id="19"), fx("1.json", id="2", status="completed", subject="old fix wave")]
        _, st = self.derive(tasks, primed())
        self.assertEqual(st["spec_floor"], {"3": 19})
        tasks.append(fx("19.json", id="30"))
        _, st = self.derive(tasks, st)
        self.assertEqual(st["spec_floor"], {"3": 19})   # later tasks do not move it

    def test_new_list_baselines_its_completed_history(self):
        st = primed()
        a, st = df.derive("proj", self.root, [self.run_task], st, NOW, "session-aaaaaaaa")
        self.assertEqual(len(a), 2)
        done = [fx("19.json", status="completed"), fx("1.json")]
        done[0]["id"] = "40"
        b, st = df.derive("proj", self.root, [self.run_task] + done, st, NOW, "session-bbbbbbbb")
        self.assertEqual([e["kind"] for e in b], ["spec_started", "plan_written"])   # no task_done, no outcome for the old tasks
        self.assertEqual(st["primed_lists"], ["session-aaaaaaaa", "session-bbbbbbbb"])

    def test_list_name_flip_emits_nothing_new(self):
        st = {}
        a1, st = df.derive("proj", self.root, [self.run_task, self.sub], st, NOW, "session-aaaaaaaa")
        self.assertEqual([e["kind"] for e in a1], ["spec_started", "plan_written"])
        team = [fx("19.json", status="completed", id="7"), fx("1.json", id="8")]
        b, st = df.derive("proj", self.root, team, st, NOW, "team-x")
        self.assertEqual(b, [])
        a2, st = df.derive("proj", self.root, [self.run_task, self.sub], st, NOW, "session-aaaaaaaa")
        self.assertEqual(a2, [])
        b2, st = df.derive("proj", self.root, team, st, NOW, "team-x")
        self.assertEqual(b2, [])

    def test_same_task_ids_from_two_lists_both_emit(self):
        st = primed()
        a, st = df.derive("proj", self.root, [self.run_task], st, NOW, "session-aaaaaaaa")
        self.assertEqual(a[0]["refs"]["thread_key"], "session-aaaaaaaa:3")
        self.assertEqual(st["running_thread_key"], "session-aaaaaaaa:3")
        b, st = df.derive("proj", self.root, [self.run_task], st, NOW, "session-bbbbbbbb")
        self.assertEqual(b[0]["refs"]["thread_key"], "session-bbbbbbbb:3")
        self.assertEqual([e["kind"] for e in b], ["spec_started", "plan_written"])   # a new list is a new spec thread
        done = fx("1.json")
        c, st = df.derive("proj", self.root, [done], st, NOW, "session-aaaaaaaa")
        d, st = df.derive("proj", self.root, [done], st, NOW, "session-bbbbbbbb")
        self.assertEqual((len(c), len(d)), (1, 1))
        self.assertEqual(df.ops_for_events(d, st)[-1], {"op": "archive", "key": "session-bbbbbbbb:1"})

    def test_seen_cap(self):
        st = {"primed": True, "seen": [f"k{i}" for i in range(2000)]}
        evs, st = self.derive([self.run_task], st)
        self.assertEqual(len(evs), 2)
        self.assertEqual(len(st["seen"]), 2000)
        self.assertNotIn("k0", st["seen"])
        self.assertIn("k1999", st["seen"])

    def test_derive_does_not_mutate_input_state(self):
        st = primed()
        before = copy.deepcopy(st)
        self.derive([self.run_task], st)
        self.assertEqual(st, before)


class OpsTest(Base):
    def ev(self, kind, tier, refs=None, text="t"):
        return {"ts": 1.0, "project": "p", "spec": "s", "kind": kind, "tier": tier, "text": text, "refs": refs or {}}

    def test_tier_table(self):
        st = {"running_thread_key": "7"}
        ops = df.ops_for_events([self.ev("task_done", "progress"), self.ev("needs_you", "decision"),
                                 self.ev("test_failed", "critical"), self.ev("usage", "routine"),
                                 self.ev("spec_outcome", "progress", text="failed — x")], st)
        self.assertEqual(ops[0], {"op": "post", "thread_key": "7", "text": "t", "tier": "progress", "mention_user": False})
        self.assertEqual(ops[1], {"op": "post", "text": "t", "tier": "decision", "mention_user": True, "link_thread_key": "7",
                                  "key": "dec:" + hashlib.sha1(b"1.0|t").hexdigest()[:12]})   # decision posts carry a key (ops mirror)
        self.assertEqual(ops[2]["tier"], "critical")
        self.assertTrue(ops[2]["mention_user"])
        self.assertEqual(len(ops), 4)  # routine: no op
        self.assertEqual(ops[3]["tier"], "critical")  # failed outcome forced critical
        for o in ops:
            df._check(o)

    def test_no_running_spec(self):
        ops = df.ops_for_events([self.ev("task_done", "progress"), self.ev("needs_you", "decision")], {})
        self.assertNotIn("thread_key", ops[0])
        self.assertNotIn("link_thread_key", ops[1])


class TickTest(DeriveBase):
    def setUp(self):
        super().setUp()
        self.prime = [fx("1.json", status="pending")]   # a non-empty list primes; an empty one does not

    def tick(self, tasks, now=NOW, record=None):
        return df.tick("proj", record or rec(), self.root, now, lead_tasks=tasks)

    def outbox(self):
        box = tc_env.discord_dir("proj") / "outbox"
        return [json.loads(p.read_text()) for p in sorted(box.glob("*.json"))] if box.exists() else []

    def test_tick_writes_feed_outbox_card(self):
        self.tick(self.prime)  # primes
        self.tick([self.run_task, self.sub], now=NOW + 100)
        ev, _ = df.read_events("proj", 0)
        self.assertEqual([e["kind"] for e in ev], ["spec_started", "plan_written", "task_done"])
        ops = self.outbox()
        self.assertEqual([o["op"] for o in ops].count("thread"), 1)
        self.assertEqual([o["op"] for o in ops].count("post"), 3)
        self.assertGreaterEqual([o["op"] for o in ops].count("card"), 1)
        st = json.loads((tc_env.discord_dir("proj") / "feed-state.json").read_text())
        self.assertEqual(st["running_thread_key"], "3")
        self.assertIn("card_text", st)

    def test_events_from_others_flow_through(self):
        self.tick(self.prime)
        df.append_event("proj", {"ts": 5.0, "project": "proj", "spec": "", "kind": "needs_you", "tier": "decision", "text": "lead waits", "refs": {}})
        self.tick([], now=NOW + 100)
        posts = [o for o in self.outbox() if o["op"] == "post"]
        self.assertEqual([p["text"] for p in posts], ["lead waits"])
        self.assertTrue(posts[0]["mention_user"])
        self.tick([], now=NOW + 200)
        self.assertEqual(len([o for o in self.outbox() if o["op"] == "post"]), 1)

    def test_restart_emits_nothing(self):
        global df
        self.tick(self.prime)
        self.tick([self.run_task, self.sub], now=NOW + 100)
        n_feed = len(df.read_events("proj", 0)[0])
        n_out = len([o for o in self.outbox() if o["op"] != "card"])   # a card op may follow: "updated HH:MM" moves
        df = importlib.reload(df)  # a fresh process: nothing but feed-state.json survives
        self.tick([self.run_task, self.sub], now=NOW + 200)
        self.assertEqual(len(df.read_events("proj", 0)[0]), n_feed)
        self.assertEqual(len([o for o in self.outbox() if o["op"] != "card"]), n_out)

    def test_malformed_foreign_event_is_skipped_and_offset_moves(self):
        self.tick(self.prime)
        f = tc_env.feed_path("proj")
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a") as fh:
            fh.write(json.dumps({"ts": 1.0, "kind": "needs_you", "tier": "decision"}) + "\n")   # no text
            fh.write(json.dumps([1, 2]) + "\n")
            fh.write(json.dumps({"ts": 2.0, "project": "proj", "spec": "", "kind": "needs_you", "tier": "decision", "text": "ok", "refs": {}}) + "\n")
        with mock.patch("sys.stderr"):
            self.tick([self.run_task], now=NOW + 100)
        posts = [o for o in self.outbox() if o["op"] == "post"]
        self.assertIn("ok", [p["text"] for p in posts])
        n = len(self.outbox())
        feed_n = len(df.read_events("proj", 0)[0])
        with mock.patch("sys.stderr"):
            self.tick([self.run_task], now=NOW + 200)
        self.assertEqual(len(df.read_events("proj", 0)[0]), feed_n)   # nothing re-derived or re-appended
        self.assertEqual(len([o for o in self.outbox() if o["op"] != "card"]), len([o for o in self.outbox()[:n] if o["op"] != "card"]))

    def presence(self):
        return [o for o in self.outbox() if o["op"] == "presence"]

    def ptick(self, now, spend, live=()):
        r = rec()
        r["spend_today"] = spend
        return df.tick("proj", r, self.root, now, lead_tasks=self.prime, live=list(live), limits=None)

    def test_presence_throttled_60s_and_on_change(self):
        # mutation: drop the 60 s check in presence_op_due -> the t+30 assertion fails
        self.ptick(NOW, 1.0)
        self.assertEqual(len(self.presence()), 1)
        self.ptick(NOW + 30, 2.0)
        self.assertEqual(len(self.presence()), 1)
        self.ptick(NOW + 61, 2.0)
        self.assertEqual(len(self.presence()), 2)
        self.assertIn("$2.00", self.presence()[1]["text"])
        (tc_env.discord_dir("proj") / "bridge-state.json").write_text(json.dumps({"presence": self.presence()[1]["text"]}))
        self.ptick(NOW + 120, 2.0)
        self.assertEqual(len(self.presence()), 2)
        st = json.loads((tc_env.discord_dir("proj") / "feed-state.json").read_text())
        self.assertEqual((st["presence_text"], st["presence_ts"]), (self.presence()[1]["text"], NOW + 61))

    def test_presence_resent_when_bridge_state_lost_it(self):
        self.ptick(NOW, 1.0)
        text = self.presence()[0]["text"]
        (tc_env.discord_dir("proj") / "bridge-state.json").write_text(json.dumps({"presence": "old"}))
        self.ptick(NOW + 61, 1.0)
        self.assertEqual([o["text"] for o in self.presence()], [text, text])

    def test_no_presence_when_live_is_none(self):
        self.tick(self.prime)
        self.assertEqual(self.presence(), [])
        st = json.loads((tc_env.discord_dir("proj") / "feed-state.json").read_text())
        self.assertNotIn("presence_text", st)

    def test_bad_presence_op_is_logged_and_does_not_block_card(self):
        # mutation: save presence_text although the write raised -> presence_text in state
        with mock.patch("ticker.project_line", return_value=""), mock.patch("sys.stderr") as err:
            df.tick("proj", rec(), self.root, NOW, lead_tasks=self.prime, live=[], limits=None)
        self.assertEqual(self.presence(), [])
        self.assertEqual([o["op"] for o in self.outbox()].count("card"), 1)
        st = json.loads((tc_env.discord_dir("proj") / "feed-state.json").read_text())
        self.assertNotIn("presence_text", st)

    def test_line_failure_never_stops_card(self):
        with mock.patch("ticker.project_line", side_effect=RuntimeError("boom")), mock.patch("sys.stderr") as err:
            df.tick("proj", rec(), self.root, NOW, lead_tasks=self.prime, live=[], limits=None)
        self.assertEqual([o["op"] for o in self.outbox()].count("card"), 1)
        self.assertIn("boom", "".join(c[0][0] for c in err.write.call_args_list))

    def test_held_lock_skips_tick(self):
        d = tc_env.discord_dir("proj")
        d.mkdir(parents=True)
        fh = open(d / "feed-state.lock", "w")
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            self.assertIsNone(self.tick([self.run_task]))
            self.assertFalse((d / "feed-state.json").exists())
            self.assertEqual(self.outbox(), [])
        finally:
            fh.close()
        self.assertIsNotNone(self.tick([self.run_task]))
        self.assertTrue((d / "feed-state.json").exists())


# ---- discord-files Task 2: report and failed-run log attachments, delete_files ----
class DeleteFilesTest(Base):
    def test_bool_accepted_non_bool_rejected(self):
        df.outbox_write(self.dir, post(files=["/a/b.png"], delete_files=True))
        with self.assertRaises(ValueError):
            df.outbox_write(self.dir, post(files=["/a/b.png"], delete_files="yes"))


class ReportFilesTest(DeriveBase):
    def test_report_post_carries_file(self):
        r = self.root / "docs/superpowers/reports"
        r.mkdir(parents=True)
        (r / "2026-11-16-queue.md").write_text("# Queue report\n")
        evs, _ = self.derive([], primed())
        self.assertEqual(evs[0]["refs"]["path"], str(r / "2026-11-16-queue.md"))
        op = df.ops_for_events(evs, {"running_thread_key": "3"})[0]
        self.assertEqual(op["files"], [str(r / "2026-11-16-queue.md")])
        self.assertNotIn("thread_key", op)
        df._check(op)

    def test_event_without_path_posts_without_files(self):
        ev = {"ts": 1.0, "project": "p", "spec": "", "kind": "report_written", "tier": "progress", "text": "queue report: x",
              "refs": {"file": "x-queue.md"}}
        op = df.ops_for_events([ev], {})[0]
        self.assertNotIn("files", op)


class FailedRunLogTest(DeriveBase):
    NOW_I = int(NOW)

    def setUp(self):
        super().setUp()
        self.runs = Path(self.tmp.name) / "runs"
        self.runs.mkdir()
        self.n = 0

    def log(self, lines=300, name=None):
        self.n += 1
        p = self.runs / (name or f"log{self.n}.out")
        p.write_text("".join(f"line {i}\n" for i in range(1, lines + 1)))
        return p

    def write_runs(self, *recs):
        f = Path(self.tmp.name) / "runs-proj.jsonl"
        f.write_text("".join(json.dumps(r) + "\n" for r in recs))

    def rec(self, rid="r1", **over):
        r = {"id": rid, "ts": self.NOW_I - 3600, "agent": "w", "win": "tests", "session": "s", "cmd": "python3 -m unittest",
             "cwd": "/x/.claude/worktrees/w", "exit": 1, "duration": 5, "log": str(self.log()), "summary": ""}
        r.update(over)
        return r

    def failed(self):
        done = fx("1.json")
        done["metadata"]["outcome"] = "failed — tests red"
        evs, st = self.derive([done], primed())
        return evs, st, df.ops_for_events(evs, st)

    @staticmethod
    def hhmm(ts):
        import datetime
        return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")

    def test_post_names_worktree_and_time(self):
        self.write_runs(self.rec(cwd="/x/.claude/worktrees/queue-reliability"))
        evs, st, ops = self.failed()
        self.assertEqual(ops[1]["text"], f"failed run log: python3 -m unittest (exit 1) · queue-reliability · {self.hhmm(self.NOW_I - 3600)}")

    def test_post_empty_cmd_shows_id(self):
        self.write_runs(self.rec("r9", cmd="  "))
        evs, st, ops = self.failed()
        self.assertEqual(ops[1]["text"], f"failed run log: r9 (exit 1) · w · {self.hhmm(self.NOW_I - 3600)}")

    def test_post_long_cmd_cut_to_200(self):
        self.write_runs(self.rec(cmd="a" * 500))
        evs, st, ops = self.failed()
        self.assertEqual(ops[1]["text"], f"failed run log: {'a' * 200}… (exit 1) · w · {self.hhmm(self.NOW_I - 3600)}")

    def attach(self, rid):
        return tc_env.discord_dir("proj") / "attachments" / f"{rid}.log"

    def test_log_attached_in_thread(self):
        self.write_runs({**self.rec(), "exit": None}, self.rec())
        evs, st, ops = self.failed()
        f = self.attach("r1")
        self.assertEqual(f.read_text().splitlines(), [f"line {i}" for i in range(101, 301)])
        self.assertEqual([o["op"] for o in ops], ["post", "post", "archive"])
        self.assertEqual(ops[0], {"op": "post", "text": "failed — tests red", "tier": "critical", "mention_user": True, "link_thread_key": "1"})
        self.assertEqual(ops[1], {"op": "post", "text": f"failed run log: python3 -m unittest (exit 1) · w · {self.hhmm(self.NOW_I - 3600)}", "tier": "progress",
                                  "mention_user": False, "thread_key": "1", "files": [str(f)]})
        for o in ops:
            df._check(o)

    def assert_no_log(self, *recs):
        self.write_runs(*recs)
        evs, st, ops = self.failed()
        self.assertEqual([o["op"] for o in ops], ["post", "post", "archive"])
        self.assertEqual(ops[1]["text"], "failed — no failing test run recorded")
        self.assertNotIn("files", ops[1])
        self.assertEqual(ops[1]["thread_key"], "1")
        self.assertFalse((tc_env.discord_dir("proj") / "attachments").exists())

    def test_exit_zero_not_picked(self):       # mutation: drop the exit != 0 filter -> this fails
        self.assert_no_log(self.rec(exit=0))

    def test_start_record_only_not_picked(self):
        self.assert_no_log(self.rec(exit=None))

    def test_cwd_outside_worktrees_not_picked(self):   # mutation: drop the cwd filter -> this fails
        self.assert_no_log(self.rec(cwd="/x/main"))

    def test_older_than_24h_not_picked(self):
        self.assert_no_log(self.rec(ts=self.NOW_I - 86400 - 10))

    def test_missing_log_file_not_picked(self):
        self.assert_no_log(self.rec(log=str(self.runs / "gone.out")))

    def test_newest_qualifying_wins(self):
        self.write_runs(self.rec("old", ts=self.NOW_I - 7200, cmd="old cmd"), self.rec("new", ts=self.NOW_I - 60, cmd="new cmd"),
                        self.rec("newer-ok", ts=self.NOW_I - 30, exit=0))
        evs, st, ops = self.failed()
        self.assertEqual(ops[1]["text"], f"failed run log: new cmd (exit 1) · w · {self.hhmm(self.NOW_I - 60)}")
        self.assertTrue(self.attach("new").is_file())

    def test_attachments_pruned_to_20(self):
        d = tc_env.discord_dir("proj") / "attachments"
        d.mkdir(parents=True)
        for i in range(25):
            p = d / f"old{i:02d}.log"
            p.write_text("x")
            os.utime(p, (1000 + i, 1000 + i))
        self.write_runs(self.rec())
        self.failed()
        names = sorted(p.name for p in d.iterdir())
        self.assertEqual(len(names), 20)
        self.assertIn("r1.log", names)
        self.assertNotIn("old00.log", names)

    def test_merged_outcome_adds_no_log_post(self):
        self.write_runs(self.rec())
        evs, st = self.derive([fx("1.json")], primed())
        self.assertEqual([o["op"] for o in df.ops_for_events(evs, st)], ["post", "archive"])

    def test_replay_does_not_rewrite_log(self):
        self.write_runs(self.rec())
        done = fx("1.json")
        done["metadata"]["outcome"] = "failed — tests red"
        evs, st = self.derive([done], primed())
        self.attach("r1").unlink()
        self.assertEqual(self.derive([done], st)[0], [])
        self.assertFalse(self.attach("r1").exists())
