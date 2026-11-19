"""discord_dialogs.gates / gate click: a pending, unblocked user-gate task posts once per project and subject with its acceptance
criteria and Done / Not yet; Done queues `[Discord] gate done <subject>` for the lead. Scratch TC_STATE; nothing real is touched."""
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
import discord_dialogs as dd  # noqa: E402
import tc_env  # noqa: E402

SUBJECT = "User gate: dialogs answered on the phone"


def gkey(project, subject):
    return "g" + hashlib.sha1((project + "\0" + subject).encode("utf-8")).hexdigest()[:12]


def task(tid="1", subject=SUBJECT, status="pending", blocked=(), meta=None, desc=""):
    t = {"id": tid, "subject": subject, "status": status, "description": desc, "blockedBy": list(blocked)}
    if meta is not None:
        t["metadata"] = meta
    return t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.d = tc_env.discord_dir("proj")
        self.d.mkdir(parents=True)
        (self.d / "bridge.json").write_text(json.dumps({"channel": "123"}))
        self.lines = []
        self.add = lambda s, t: self.lines.append((s, t))

    def ops(self, d=None):
        box = (d or self.d) / "outbox"
        return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(box.glob("*.json"))] if box.exists() else []

    def click(self, cid, user="u1", allow=("u1",)):
        ev = {"type": "click", "custom_id": cid, "user": user, "ts": 1}
        return dd.consume_event(self.d, ev, set(allow), None, 200.0, add_line=self.add)


class PostTest(Base):
    def test_metadata_gate_posts_once_with_criteria_and_buttons(self):
        t = task(meta={"userGate": True, "acceptanceCriteria": ["it works", "on the phone"]}, subject="Phone check")
        dd.gates("proj", [t], 100.0)
        (op,) = self.ops()
        k = gkey("proj", "Phone check")
        self.assertEqual(op["op"], "dialog")
        self.assertEqual(op["key"], k)
        self.assertEqual(op["text"], "🚧 proj · user gate: Phone check\n- it works\n- on the phone")
        self.assertEqual(op["rows"], [[{"label": "Done", "style": 3, "custom_id": f"ab:gate:{k}:done"},
                                       {"label": "Not yet", "style": 2, "custom_id": f"ab:gate:{k}:notyet"}]])

    def test_subject_prefix_gate_posts_once_and_second_tick_writes_nothing(self):
        dd.gates("proj", [task()], 100.0)
        dd.gates("proj", [task()], 110.0)
        self.assertEqual(len(self.ops()), 1)

    def test_criteria_from_the_description_when_metadata_has_none(self):
        desc = "intro\n\n**Acceptance Criteria:**\n- [ ] first thing\n- [x] second thing\n\n**Verify:** x\n"
        dd.gates("proj", [task(desc=desc)], 100.0)
        self.assertEqual(self.ops()[0]["text"], f"🚧 proj · user gate: {SUBJECT}\n- first thing\n- second thing")

    def test_criteria_are_cut_to_1500_characters(self):
        dd.gates("proj", [task(meta={"userGate": True, "acceptanceCriteria": ["x" * 400] * 6})], 100.0)
        body = self.ops()[0]["text"].split("\n", 1)[1]
        self.assertLessEqual(len(body), 1500)

    def test_a_task_that_is_not_a_gate_posts_nothing(self):
        dd.gates("proj", [task(subject="Task 3: build it"), task("2", subject="Gate", meta={"userGate": False})], 100.0)
        self.assertEqual(self.ops(), [])

    def test_completed_gate_never_posts(self):
        dd.gates("proj", [task(status="completed")], 100.0)
        dd.gates("proj", [task(status="in_progress")], 100.0)
        self.assertEqual(self.ops(), [])

    def test_blocked_gate_posts_after_its_last_blocker_completes(self):
        # mutation: drop the blockedBy check -> the first tick posts
        a, b = task("1", subject="Task 1: x"), task("2", subject="Task 2: y")
        g = task("3", blocked=["1", "2"])
        dd.gates("proj", [a, b, g], 100.0)
        b["status"] = "completed"
        dd.gates("proj", [a, b, g], 110.0)
        self.assertEqual(self.ops(), [])
        a["status"] = "completed"
        dd.gates("proj", [a, b, g], 120.0)
        self.assertEqual(len(self.ops()), 1)

    def test_same_subject_under_a_new_list_id_does_not_post_again(self):
        # mutation: key the dedupe on the task id -> the relay's new list (ids restart, one differs) posts again
        dd.gates("proj", [task("4")], 100.0)
        dd.gates("proj", [task("9")], 110.0)
        self.assertEqual(len(self.ops()), 1)

    def test_no_channel_posts_to_the_ops_dir(self):
        tc_env.ops_dir().mkdir(parents=True)
        (tc_env.ops_dir() / "bridge.json").write_text(json.dumps({"command_center": "1", "approvals": "2"}))
        dd.gates("nochan", [task()], 100.0)
        self.assertEqual(len(self.ops(tc_env.ops_dir())), 1)

    def test_nothing_configured_posts_nothing_and_a_later_tick_still_can(self):
        dd.gates("nochan", [task()], 100.0)
        self.assertEqual(self.ops(tc_env.ops_dir()), [])
        tc_env.ops_dir().mkdir(parents=True)
        (tc_env.ops_dir() / "bridge.json").write_text(json.dumps({"command_center": "1", "approvals": "2"}))
        dd.gates("nochan", [task()], 110.0)
        self.assertEqual(len(self.ops(tc_env.ops_dir())), 1)

    def test_an_edited_subject_is_a_new_gate(self):
        dd.gates("proj", [task()], 100.0)
        dd.gates("proj", [task(subject=SUBJECT + " v2")], 110.0)
        self.assertEqual(len(self.ops()), 2)


class ClickTest(Base):
    def setUp(self):
        super().setUp()
        dd.gates("proj", [task()], 100.0)
        self.k = gkey("proj", SUBJECT)

    def test_done_queues_the_exact_line_edits_and_audits_via_the_result(self):
        r = self.click(f"ab:gate:{self.k}:done")
        self.assertEqual(r, ("gate", f"ab:gate:{self.k}:done", "done"))
        self.assertEqual(self.lines, [("proj", f"[Discord] gate done {SUBJECT}")])
        e = [o for o in self.ops() if o["op"] == "edit"]
        self.assertEqual([(o["key"], o["text"]) for o in e], [(self.k, f"🚧 proj · user gate: {SUBJECT}\n→ Done (from Discord)")])

    def test_second_done_is_already_answered_and_queues_nothing(self):
        self.click(f"ab:gate:{self.k}:done")
        r = self.click(f"ab:gate:{self.k}:done")
        self.assertEqual(r[2], "already answered")
        self.assertEqual(len(self.lines), 1)

    def test_done_stays_answered_after_the_gate_is_seen_again(self):
        self.click(f"ab:gate:{self.k}:done")
        dd.gates("proj", [task()], 300.0)   # the lead has not completed the task yet
        self.assertEqual(len([o for o in self.ops() if o["op"] == "dialog"]), 1)

    def test_not_yet_only_audits_and_the_message_stays(self):
        r = self.click(f"ab:gate:{self.k}:notyet")
        self.assertEqual(r[2], "not yet")
        self.assertEqual(self.lines, [])
        self.assertEqual([o["op"] for o in self.ops()], ["dialog"])
        self.assertEqual(self.click(f"ab:gate:{self.k}:done")[2], "done")   # still answerable

    def test_stranger_is_rejected_and_nothing_happens(self):
        r = self.click(f"ab:gate:{self.k}:done", user="evil")
        self.assertEqual(r[2], "rejected")
        self.assertEqual(self.lines, [])
        self.assertEqual(self.click(f"ab:gate:{self.k}:done")[2], "done")

    def test_unknown_gate_and_bad_shapes(self):
        self.assertEqual(self.click("ab:gate:g000000000000:done")[2], "already answered")
        for bad in (f"ab:gate:{self.k}:x", f"ab:gate:{self.k}", f"ab:gate:{self.k}:done:x", "ab:gate:zz:done"):
            self.assertEqual(self.click(bad)[2], "ignored", bad)
        self.assertEqual(self.lines, [])

    def test_a_failing_add_line_keeps_the_gate_open(self):
        def boom(s, t):
            raise ValueError("empty line")
        ev = {"type": "click", "custom_id": f"ab:gate:{self.k}:done", "user": "u1", "ts": 1}
        with self.assertRaises(ValueError):
            dd.consume_event(self.d, ev, {"u1"}, None, 200.0, add_line=boom)
        self.assertEqual(self.click(f"ab:gate:{self.k}:done")[2], "done")


class RouteTest(Base):
    def setUp(self):
        super().setUp()
        dd.gates("proj", [task()], 100.0)
        self.k = gkey("proj", SUBJECT)

    def events(self, d, *evs):
        (d / "events").mkdir(parents=True, exist_ok=True)
        for n, ev in enumerate(evs):
            (d / "events" / f"{n:03d}.json").write_text(json.dumps(ev))

    def audit(self, d):
        p = d / "audit.jsonl"
        return [(l["action"], l["user"], l["result"]) for l in map(json.loads, p.read_text().splitlines())] if p.exists() else []

    def test_controls_routes_gate_clicks_and_checks_allowfrom_first(self):
        import discord_controls as dc
        (self.d / "access.json").write_text(json.dumps({"allowFrom": ["u1"]}))
        self.events(self.d, {"type": "click", "custom_id": f"ab:gate:{self.k}:done", "user": "evil", "ts": 1},
                    {"type": "click", "custom_id": f"ab:gate:{self.k}:done", "user": "u1", "ts": 2},
                    {"type": "click", "custom_id": f"ab:gate:{self.k}:done", "user": "u1", "ts": 3})
        dc.consume_events(self.d, "proj", {}, None, self.add)
        self.assertEqual(self.audit(self.d), [("gate", "evil", "rejected"), ("gate", "u1", "done"), ("gate", "u1", "already answered")])
        self.assertEqual(self.lines, [("proj", f"[Discord] gate done {SUBJECT}")])

    def test_ops_routes_gate_clicks_of_a_project_without_a_channel(self):
        import discord_ops as ops
        tc_env.ops_dir().mkdir(parents=True)
        (tc_env.ops_dir() / "bridge.json").write_text(json.dumps({"command_center": "1", "approvals": "2"}))
        (tc_env.ops_dir() / "access.json").write_text(json.dumps({"allowFrom": ["u1"]}))
        dd.gates("nochan", [task()], 100.0)
        k = gkey("nochan", SUBJECT)
        self.events(tc_env.ops_dir(), {"type": "click", "custom_id": f"ab:gate:{k}:done", "user": "u1", "ts": 1},
                    {"type": "click", "custom_id": f"ab:gate:{k}:done", "user": "evil", "ts": 2})
        ops.consume(self.add, None, 300.0)
        self.assertEqual(self.audit(tc_env.ops_dir()), [("gate", "u1", "done"), ("gate", "evil", "rejected")])
        self.assertEqual(self.lines, [("nochan", f"[Discord] gate done {SUBJECT}")])


if __name__ == "__main__":
    unittest.main()
