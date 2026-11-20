"""discord_ops: card, views.json, decision mirror, lead questions, ops events. Scratch TC_STATE; add_line, ideas.add and on_merge are fakes.
Each guard test names the mutation that must make it fail."""
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
import discord_ops as ops  # noqa: E402
import tc_env  # noqa: E402

NOW = 1_800_000_000.0
PAUSE = "[Discord] 🛑 pause the queue"
RESUME = "[Discord] ▶️ resume the queue"


def rec(project, needs=(), alerts=(), spend=None, done=1, total=3):
    return {"project": project, "needs_you": [{"window": w, "pane": "%1", "kind": "claude", "reason": ""} for w in needs],
            "alerts": [{"kind": "context", "label": l} for l in alerts], "spend_today": spend,
            "plan": {"name": "p", "active": True, "done": done, "total": total, "in_progress": []}}


def run_task(i, spec, status, outcome=None):
    t = {"id": str(i), "subject": f"Plan & run: docs/superpowers/specs/{spec}.md", "status": status}
    if outcome:
        t["metadata"] = {"outcome": outcome}
    return t


def ok(key, user="U1", **kw):
    return {"type": "click", "custom_id": key, "user": user, "ts": NOW, **kw}


def okey(project, src):
    return hashlib.sha1((project + "\0" + src).encode()).hexdigest()[:12]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.ops = tc_env.ops_dir()
        self.ops.mkdir(parents=True)
        self.lines = []
        self.add = lambda s, t: self.lines.append((s, t))
        self.merges = []
        self.merge_ret = {"result": "merged abc", "text": "merge approved — sent to the lead"}
        self.on_merge = lambda *a: (self.merges.append(a), self.merge_ret)[1]

    def configure(self, user="U1"):
        (self.ops / "bridge.json").write_text(json.dumps({"command_center": "C1", "approvals": "A1", "user": user}))
        (self.ops / "access.json").write_text(json.dumps({"allowFrom": [user]}))

    def project(self, name, channel="123", guild="999"):
        d = tc_env.discord_dir(name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "bridge.json").write_text(json.dumps({"channel": channel, "user": "U1"}))
        if guild:
            (d / "bridge-state.json").write_text(json.dumps({"guild_id": guild}))
        return d

    def outbox(self, d=None):
        box = (d or self.ops) / "outbox"
        return [json.loads(f.read_text()) for f in sorted(box.glob("*.json"))] if box.exists() else []

    def state(self):
        return json.loads((self.ops / "ops-state.json").read_text())

    def feed(self, project, **ev):
        base = {"ts": NOW, "project": project, "spec": "s", "kind": "custom", "tier": "decision", "text": "t", "refs": {}}
        df.append_event(project, {**base, **ev})

    def tick(self, records, tasks=None, limits=None, now=NOW):
        return ops.tick(records, tasks or {}, limits, now, self.add)

    def event(self, name, ev, d=None):
        e = (d or self.ops) / "events"
        e.mkdir(exist_ok=True)
        (e / name).write_text(json.dumps(ev))

    def consume(self, now=NOW):
        return ops.consume(self.add, lambda argv: "", now, on_merge=self.on_merge)


class RenderCard(Base):
    LINKS = {"a": "https://discord.com/channels/9/1", "b": ""}

    def test_two_projects_format(self):
        r = [rec("a", needs=["claude"], alerts=["ctx 90%"], spend=1.5), rec("b", spend=0.25, done=0, total=0)]
        tasks = {"a": [run_task(1, "x", "in_progress"), run_task(2, "y", "pending")], "b": []}
        limits = {"five_hour": {"used_percentage": 63}, "seven_day": {"used_percentage": 93.4}}
        out = ops.render_card(r, tasks, self.LINKS, limits, NOW)
        lines = out.split("\n")
        self.assertEqual(lines[0], "usage: 5h 63% · week 93% · today $1.75")
        self.assertEqual(lines[1], "**a** · queue: running x (spec 1 of 2) · blockers: none · alerts: ctx 90% · waiting on you: 1 · <https://discord.com/channels/9/1>")
        self.assertEqual(lines[2], "**b** · queue: idle · blockers: none · waiting on you: 0")
        self.assertTrue(lines[3].startswith("updated "))
        self.assertNotIn("```", out)

    def test_unknown_usage_parts_are_dashes(self):
        out = ops.render_card([rec("a")], {}, {}, None, NOW)
        self.assertEqual(out.split("\n")[0], "usage: 5h — · week — · today $—")

    def test_utilization_field_name_also_read(self):
        out = ops.render_card([], {}, {}, {"five_hour": {"utilization": 12}, "seven_day": None}, NOW)
        self.assertEqual(out.split("\n")[0], "usage: 5h 12% · week — · today $—")

    def test_overflow_cut_with_more(self):
        # mutation: drop the length loop (return all lines) -> the 1900 cap assertion fails
        r = [rec(f"project-{i:02d}", alerts=["ctx 90%"], spend=1.0) for i in range(40)]
        links = {x["project"]: f"https://discord.com/channels/9/{i}" for i, x in enumerate(r)}
        out = ops.render_card(r, {}, links, None, NOW)
        self.assertLessEqual(len(out), 1900)
        self.assertRegex(out, r"… \d+ more")
        self.assertTrue(out.split("\n")[-1].startswith("updated "))


class BlockersSplit(Base):
    def line(self, alerts, floor=None):
        r = rec("a"); r["alerts"] = alerts
        return ops._project_line(r, [], "", floor)

    def test_non_blocking_alert_goes_under_alerts(self):
        # mutation: drop the kind filter -> opus@medium lands under blockers
        self.assertIn("blockers: none · alerts: opus@medium · waiting", self.line([{"kind": "model_mismatch", "label": "opus@medium"}]))

    def test_stuck_is_a_blocker_without_alerts_part(self):
        out = self.line([{"kind": "stuck", "label": "stuck 12m"}])
        self.assertIn("blockers: stuck 12m · waiting", out)
        self.assertNotIn("alerts:", out)

    def test_floor_reaches_the_queue_text(self):
        tasks = [run_task(1, "x", "in_progress"), {"id": "5", "subject": "T", "status": "completed"}]
        r = rec("a")
        self.assertIn("(tasks 1/1 · spec 1 of 1)", ops._project_line(r, tasks, "", 2))
        self.assertIn("(tasks 1/1 · spec 1 of 1)", ops.queue_text(tasks, 2))

    def test_tick_reads_floor_from_feed_state(self):
        self.configure()
        d = self.project("a")
        (d / "feed-state.json").write_text(json.dumps({"running_thread_key": "k", "spec_floor": {"k": 1}}))
        tasks = {"a": [run_task(1, "x", "in_progress"), {"id": "5", "subject": "T", "status": "completed"}]}
        self.tick([rec("a")], tasks)
        self.assertEqual(self.state()["queues"]["a"], "queue: running x (tasks 1/1 · spec 1 of 1)")
        v = json.loads((self.ops / "views.json").read_text())
        self.assertIn("tasks 1/1", v["status"]["a"])
        self.assertIn("tasks 1/1", v["queue"]["a"])
        self.assertIn("tasks 1/1", v["status"]["_all"])


class Tick(Base):
    def test_unconfigured_writes_nothing(self):
        # mutation: drop the configured() guard -> files appear under _ops and the test fails
        before = sorted(p.name for p in self.ops.iterdir())
        self.assertIsNone(self.tick([rec("a")]))
        self.assertIsNone(self.consume())
        self.assertEqual(sorted(p.name for p in self.ops.iterdir()), before)

    def test_configured_needs_both_channels(self):
        (self.ops / "bridge.json").write_text(json.dumps({"command_center": "C1"}))
        self.assertFalse(ops.configured())
        self.configure()
        self.assertTrue(ops.configured())

    def test_card_written_once_then_throttled(self):
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        cards = [o for o in self.outbox() if o["op"] == "card"]
        self.assertEqual(len(cards), 1)
        self.tick([rec("a")], now=NOW + 5)
        self.assertEqual(len([o for o in self.outbox() if o["op"] == "card"]), 1)   # unchanged text
        self.tick([rec("a", needs=["w"])], now=NOW + 10)
        self.assertEqual(len([o for o in self.outbox() if o["op"] == "card"]), 1)   # inside the 30 s throttle
        self.tick([rec("a", needs=["w"])], now=NOW + 40)
        self.assertEqual(len([o for o in self.outbox() if o["op"] == "card"]), 2)

    def test_views_json_shape_and_atomic(self):
        self.configure()
        self.project("a")
        tasks = {"a": [run_task(1, "x", "completed", "merged"), run_task(2, "y", "in_progress"), run_task(3, "z", "pending")]}
        self.tick([rec("a")], tasks)
        v = json.loads((self.ops / "views.json").read_text())
        self.assertEqual(v["ts"], NOW)
        self.assertEqual(v["projects"], ["a"])
        self.assertIn("a", v["status"])
        self.assertIn("_all", v["status"])
        self.assertEqual(v["queue"]["a"].split("\n"), ["queue: running y (spec 2 of 3)", "✓ x — merged", "▶ y", "· z"])
        self.assertEqual(v["approvals"], [])
        self.assertEqual(v["evidence"], {})
        self.assertEqual((v["tasks"], v["leads"]), ({}, {}))
        self.assertFalse(list(self.ops.glob("*.tmp")))

    def floor(self, project, n):
        (tc_env.discord_dir(project) / "feed-state.json").write_text(json.dumps({"spec_floor": {"k": n}, "running_thread_key": "k"}))

    def test_tasks_view_lists_running_spec_own_tasks_capped(self):
        # mutation: drop the id > floor rule -> task 1 (an earlier spec's) is listed and the test fails
        self.configure()
        self.project("a")
        self.project("b")
        self.floor("a", 1)
        own = [{"id": "2", "subject": "S" * 80, "status": "completed", "owner": "w1", "metadata": {"modelTier": "standard"}},
               {"id": "3", "subject": "next", "status": "pending"}]
        tasks = {"a": [run_task(1, "x", "in_progress"), {"id": "1x", "subject": "old", "status": "completed"}] + own, "b": []}
        tasks["a"][1]["id"] = "1"
        self.tick([rec("a"), rec("b")], tasks)
        v = json.loads((self.ops / "views.json").read_text())
        self.assertEqual(list(v["tasks"]), ["a"])
        self.assertEqual(v["tasks"]["a"].split("\n"), [f"#2 completed w1 standard {'S' * 60}", "#3 pending - - next"])

    def test_tasks_view_total_cap(self):
        self.configure()
        self.project("a")
        self.floor("a", 0)
        tasks = {"a": [{"id": str(i), "subject": "s" * 100, "status": "pending"} for i in range(1, 80)]}
        self.tick([rec("a")], tasks)
        self.assertLessEqual(len(json.loads((self.ops / "views.json").read_text())["tasks"]["a"]), 1800)

    def test_leads_view_fields_and_null_when_missing(self):
        self.configure()
        self.project("a")
        self.project("b")
        hd = Path(self.tmp.name) / "handoffs"
        hd.mkdir()
        doc = hd / "h.md"
        doc.write_text("Project: /root/a\nFocus\n")
        os.utime(doc, (NOW - 90, NOW - 90))
        sd = Path(self.tmp.name) / "statusline"
        sd.mkdir()
        (sd / "s.json").write_text(json.dumps({"session_id": "sid-a", "received_at": NOW - 5, "context_window": {"used_percentage": 42}}))
        info = {"a": {"window": "claude", "pane": "%3", "pane_pid": 100, "pid": 101, "session_id": "sid-a", "state": "busy", "root": "/root/a"},
                "b": {"window": "claude", "pane": "%4", "pane_pid": 200, "pid": 0, "session_id": "", "state": "idle", "root": "/root/b"}}
        ops.tick([rec("a"), rec("b")], {}, None, NOW, self.add, lead_info=info, holder_panes=lambda panes: {"%3"}, handoffs=str(hd))
        v = json.loads((self.ops / "views.json").read_text())["leads"]
        self.assertEqual(v["a"], {"window": "claude", "pane": "%3", "pid": 101, "state": "busy", "holds_bot": True, "context_pct": 42,
                                  "session_id": "sid-a", "doc": str(doc), "doc_age_s": 90})
        self.assertEqual(v["b"], {"window": "claude", "pane": "%4", "pid": None, "state": "idle", "holds_bot": False, "context_pct": None,
                                  "session_id": None, "doc": None, "doc_age_s": None})

    def test_holder_looked_up_once_per_tick(self):
        # mutation: call holder_panes inside the per-project loop -> 2 calls and the test fails
        self.configure()
        self.project("a")
        self.project("b")
        calls = []
        info = {p: {"window": "claude", "pane": "%" + p, "pane_pid": 1, "pid": 1, "session_id": "", "state": "idle", "root": "/r/" + p} for p in "ab"}
        ops.tick([rec("a"), rec("b")], {}, None, NOW, self.add, lead_info=info, holder_panes=lambda panes: calls.append(panes) or set())
        self.assertEqual(len(calls), 1)
        self.assertEqual(sorted(calls[0]), [("%a", 1), ("%b", 1)])

    def test_queue_text_cut_to_1800(self):
        tasks = [run_task(i, "s" * 100, "pending") for i in range(1, 60)]
        self.assertLessEqual(len(ops.queue_text(tasks)), 1800)

    def test_first_sight_does_not_replay_feed(self):
        # mutation: start the offset at 0 -> the old event is posted and the test fails
        self.configure()
        self.project("a")
        self.feed("a", text="old")
        self.tick([rec("a")])
        self.assertEqual([o for o in self.outbox() if o["op"] == "approval"], [])
        self.feed("a", text="new one")
        self.tick([rec("a")])
        ap = [o for o in self.outbox() if o["op"] == "approval"]
        self.assertEqual(len(ap), 1)
        self.assertIn("new one", ap[0]["text"])

    def test_decision_becomes_approval_other_with_link(self):
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        self.feed("a", text="needs a call")
        self.tick([rec("a")])
        (ap,) = [o for o in self.outbox() if o["op"] == "approval"]
        self.assertEqual((ap["kind"], ap["mention_user"], ap["link"]), ("other", True, "https://discord.com/channels/999/123"))
        self.assertEqual(ap["text"], "a: needs a call")
        self.assertEqual(ap["project"], "a")   # mutation: drop op["project"] in _approve -> fails
        self.assertEqual(self.state()["approvals"][ap["key"]]["project"], "a")

    def test_merge_approval_becomes_merge_kind_keyed_by_task(self):
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        self.feed("a", kind="merge_approval", text="merge approval: s", refs={"task": "7", "sha": "abc"})
        self.tick([rec("a")])
        (ap,) = [o for o in self.outbox() if o["op"] == "approval"]
        self.assertEqual(ap["kind"], "merge")
        self.assertEqual(ap["key"], okey("a", "merge:7:abc"))   # the source key carries the branch sha: task ids restart per session
        self.assertEqual(self.state()["approvals"][ap["key"]]["src_key"], "merge:7:abc")

    def test_approval_title_is_the_first_line_cut_to_100(self):
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        self.feed("a", kind="merge_approval", text="merge approval: s\nfeat/x → main @ abc\n a.py | 1 +" + "y" * 200,
                  refs={"task": "7", "sha": "abc"})
        self.feed("a", text="x" * 150 + "\nsecond line")
        self.tick([rec("a")])
        titles = sorted(r["title"] for r in self.state()["approvals"].values())
        self.assertEqual(titles, ["merge approval: s", "x" * 100])

    def test_merge_approval_keeps_the_branch_and_views_carry_the_evidence(self):
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        sha = "0123456789abcdef"
        (self.ops / "evidence").mkdir()
        (self.ops / "evidence" / "a-7.json").write_text(json.dumps({"sha": sha, "files": [{"path": "x.py", "add": 1, "del": 0}], "diffs": {"x.py": "+1"}}))
        (self.ops / "evidence" / "a-8.json").write_text(json.dumps({"sha": "ffffffff00", "files": [{"path": "other", "add": 1, "del": 0}], "diffs": {}}))
        self.feed("a", kind="merge_approval", text="merge approval: s", refs={"task": "7", "sha": sha, "branch": "feat/x"})
        self.feed("a", kind="merge_approval", text="merge approval: t", refs={"task": "8", "sha": "11111111aa", "branch": "feat/y"})   # evidence sha differs
        self.tick([rec("a")])
        k = okey("a", "merge:7:01234567")
        self.assertEqual(self.state()["approvals"][k]["branch"], "feat/x")
        ev = json.loads((self.ops / "views.json").read_text())["evidence"]
        self.assertEqual(ev, {k: {"files": [{"path": "x.py", "add": 1, "del": 0}], "diffs": {"x.py": "+1"}}})   # mutation: ignore the sha check -> a-8 appears

    def test_critical_becomes_ops_post_with_mention(self):
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        self.feed("a", kind="failing", tier="critical", text="boom")
        self.tick([rec("a")])
        (p,) = [o for o in self.outbox() if o["op"] == "post"]
        self.assertEqual((p["text"], p["tier"], p["mention_user"]), ("a: boom", "critical", True))

    def test_needs_you_decision_not_mirrored_twice(self):
        # mutation: drop the _COVERED filter -> a needs_you event also becomes an `other` approval beside the perm/question ones
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        self.feed("a", kind="needs_you", text="w1: needs you")
        self.tick([rec("a")])
        self.assertEqual([o for o in self.outbox() if o["op"] == "approval"], [])

    def test_progress_events_are_ignored(self):
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        self.feed("a", tier="progress")
        self.tick([rec("a")])
        self.assertEqual([o for o in self.outbox() if o["op"] in ("post", "approval")], [])

    def test_decision_mirrored_once(self):
        # mutation: skip the `mirrored` membership check -> a second approval appears after the offset is reset
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        self.feed("a", text="once")
        self.tick([rec("a")])
        st = self.state()
        st["offsets"]["a"] = 0
        (self.ops / "ops-state.json").write_text(json.dumps(st))
        self.tick([rec("a")])
        self.assertEqual(len([o for o in self.outbox() if o["op"] == "approval"]), 1)

    def test_mirrored_keeps_newest_2000(self):
        self.configure()
        self.project("a")
        self.tick([rec("a")])
        st = self.state()
        st["mirrored"] = [f"k{i}" for i in range(2100)]
        (self.ops / "ops-state.json").write_text(json.dumps(st))
        self.feed("a", text="x")
        self.tick([rec("a")])
        m = self.state()["mirrored"]
        self.assertEqual(len(m), 2000)
        self.assertEqual(m[-1], okey("a", "dec:" + hashlib.sha1(f"{NOW}|x".encode()).hexdigest()[:12]))

    def test_open_approvals_capped_and_aged_out_of_views(self):
        # mutation: drop _trim_open / the age filter -> 205 records stay / the stale one stays in views.approvals
        self.configure()
        self.project("a")
        st = {"approvals": {f"k{i:03d}": {"project": "a", "kind": "other", "src_key": f"s{i}", "title": "t", "link": "", "ts": NOW - 100 + i} for i in range(205)}}
        st["approvals"]["perm1"] = {"project": "a", "kind": "perm", "src_key": "p", "title": "t", "link": "", "ts": NOW - 99 * 86400}
        (self.ops / "ops-state.json").write_text(json.dumps(st))
        self.tick([rec("a")])
        ap = self.state()["approvals"]
        self.assertEqual(len([k for k, v in ap.items() if v["kind"] in ("other", "merge")]), 200)
        self.assertNotIn("k000", ap)
        self.assertIn("k204", ap)
        self.assertIn("perm1", ap)   # perm/question are resolved by their own flows, never capped
        keys = {a["key"] for a in json.loads((self.ops / "views.json").read_text())["approvals"]}
        self.assertIn("perm1", keys)

    def test_open_approval_older_than_7_days_leaves_views(self):
        self.configure()
        self.project("a")
        mk = lambda ts: {"project": "a", "kind": "merge", "src_key": "m", "title": "t", "link": "", "ts": ts}
        (self.ops / "ops-state.json").write_text(json.dumps({"approvals": {"old": mk(NOW - 8 * 86400), "fresh": mk(NOW - 6 * 86400)}}))
        self.tick([rec("a")])
        self.assertEqual([a["key"] for a in json.loads((self.ops / "views.json").read_text())["approvals"]], ["fresh"])

    def presence(self):
        return [o for o in self.outbox() if o["op"] == "presence"]

    def ptick(self, now, spend, live=()):
        return ops.tick([rec("a", spend=spend)], {}, None, now, self.add, live=list(live))

    def test_presence_throttled_60s_and_on_change(self):
        # mutation: drop the 60 s check in presence_op_due -> the t+30 assertion fails
        self.configure()
        self.project("a")
        self.ptick(NOW, 1.0)
        self.assertEqual(len(self.presence()), 1)
        self.ptick(NOW + 30, 2.0)
        self.assertEqual(len(self.presence()), 1)
        self.ptick(NOW + 61, 2.0)
        self.assertEqual(len(self.presence()), 2)
        self.ptick(NOW + 120, 2.0)
        self.assertEqual(len(self.presence()), 2)
        st = self.state()
        self.assertEqual((st["presence_text"], st["presence_ts"]), (self.presence()[1]["text"], NOW + 61))

    def test_no_presence_when_live_is_none(self):
        self.configure()
        self.tick([rec("a")])
        self.assertEqual(self.presence(), [])
        self.assertNotIn("presence_text", self.state())

    def test_presence_needs_ops_configured(self):
        self.assertIsNone(self.ptick(NOW, 1.0))
        self.assertFalse((self.ops / "outbox").exists())

    def test_bad_presence_does_not_block_card_or_views(self):
        self.configure()
        with mock.patch("ticker.ops_line", return_value=""), mock.patch("sys.stderr"):
            self.ptick(NOW, 1.0)
        self.assertEqual(self.presence(), [])
        self.assertEqual([o["op"] for o in self.outbox()].count("card"), 1)
        self.assertNotIn("presence_text", self.state())
        self.assertTrue((self.ops / "views.json").exists())

    def test_line_failure_never_stops_card(self):
        self.configure()
        with mock.patch("ticker.ops_line", side_effect=RuntimeError("boom")), mock.patch("sys.stderr") as err:
            self.ptick(NOW, 1.0)
        self.assertEqual([o["op"] for o in self.outbox()].count("card"), 1)
        self.assertIn("boom", "".join(c[0][0] for c in err.write.call_args_list))

    def test_lock_held_returns_none(self):
        import fcntl
        self.configure()
        with open(self.ops / "ops-state.lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            self.assertIsNone(self.tick([rec("a")]))

    def test_lead_question_posted_once_then_answered(self):
        # mutation: drop the questions[p] check -> a second approval is posted on the next tick
        self.configure()
        self.project("a")
        self.tick([rec("a", needs=["claude"])])
        self.tick([rec("a", needs=["claude"])], now=NOW + 10)
        (ap,) = [o for o in self.outbox() if o["op"] == "approval"]
        self.assertEqual((ap["kind"], ap["text"], ap["link"]), ("question", "a: the lead is waiting on you", "https://discord.com/channels/999/123"))
        self.tick([rec("a")], now=NOW + 20)
        (ed,) = [o for o in self.outbox() if o["op"] == "edit"]
        self.assertEqual((ed["key"], ed["text"]), (ap["key"], "a: answered"))
        self.assertEqual(self.state()["questions"], {})
        self.assertEqual(self.state()["approvals"], {})

    def test_teammate_waiting_is_not_a_lead_question(self):
        self.configure()
        self.project("a")
        self.tick([rec("a", needs=["w1"])])
        self.assertEqual([o for o in self.outbox() if o["op"] == "approval"], [])

    def test_queue_state_recorded_for_consume(self):
        self.configure()
        self.project("a")
        self.tick([rec("a")], {"a": [run_task(1, "x", "in_progress")]})
        self.assertTrue(self.state()["queues"]["a"].startswith("queue: running"))


class Events(Base):
    def setUp(self):
        super().setUp()
        self.configure()
        self.pd = self.project("a")
        self.project("b")

    def test_old_allow_and_deny_buttons_are_ignored_and_forward_nothing(self):
        # mutation: restore the allow/deny branch of _click -> a perm event is written into the project's events dir
        for n, act in enumerate(("allow", "deny")):
            self.event(f"{n}.json", ok(f"ab:ops:{act}:deadbeef0000"))
        self.consume()
        self.assertEqual(list((self.pd / "events").glob("*.json")), [])
        self.assertEqual([a["result"] for a in self.audit()], ["ignored", "ignored"])

    def test_non_allowlisted_rejected_and_nothing_done(self):
        # mutation: drop the allowlist check -> the line is queued and the test fails
        self.event("1.json", ok("ab:ops:resume-all", user="EVIL"))
        self.consume()
        self.assertEqual(self.lines, [])
        self.assertEqual(self.audit()[-1]["result"], "rejected")

    def test_allowlist_reread_per_event(self):
        self.event("1.json", ok("ab:ops:resume-all"))
        self.event("2.json", ok("ab:ops:resume-all"))
        orig = ops._allow
        calls = []
        def spy(d):
            calls.append(1)
            return orig(d)
        with mock.patch.object(ops, "_allow", spy):
            self.consume()
        self.assertEqual(len(calls), 2)

    def seed_queues(self, **q):
        (self.ops / "ops-state.json").write_text(json.dumps({"queues": q}))

    def test_pause_all_confirm_hits_running_projects(self):
        self.seed_queues(a="queue: running x (1/2)", b="queue: idle")
        self.event("1.json", ok(f"ab:ops:pause-all-confirm:{int(NOW * 1000) - 5000}"))
        self.consume()
        self.assertEqual(self.lines, [("a", PAUSE)])
        self.assertEqual(self.audit()[-1]["result"], "queued 1")

    def test_pause_all_confirm_expired(self):
        # mutation: drop the 60 s check -> the pause line is sent and the test fails
        self.seed_queues(a="queue: running x (1/2)")
        self.event("1.json", ok(f"ab:ops:pause-all-confirm:{int(NOW * 1000) - 61000}"))
        self.consume()
        self.assertEqual(self.lines, [])
        self.assertEqual(self.audit()[-1]["result"], "expired")

    def test_resume_all_hits_paused_projects(self):
        self.seed_queues(a="queue: paused", b="queue: running y (1/1)")
        self.event("1.json", ok("ab:ops:resume-all"))
        self.consume()
        self.assertEqual(self.lines, [("a", RESUME)])

    def test_resume_all_after_pause_all_when_queue_still_reads_running(self):
        # the pause is a lead line: the task list (and so queues) still reads running afterwards
        self.seed_queues(a="queue: running x (1/2)", b="queue: running y (1/1)")
        self.event("1.json", ok(f"ab:ops:pause-all-confirm:{int(NOW * 1000)}"))
        self.event("2.json", ok("ab:ops:resume-all"))
        self.event("3.json", ok("ab:ops:resume-all"))
        self.consume()
        self.assertEqual(self.lines, [("a", PAUSE), ("b", PAUSE), ("a", RESUME), ("b", RESUME)])
        self.assertEqual([r["result"] for r in self.audit()[-2:]], ["queued 2", "queued 0"])
        self.assertEqual(json.loads((self.ops / "ops-state.json").read_text())["paused_by_ops"], {})

    def test_resume_all_does_not_double_send_when_paused_by_ops_and_reads_paused(self):
        self.seed_queues(a="queue: paused")
        st = json.loads((self.ops / "ops-state.json").read_text())
        st["paused_by_ops"] = {"a": NOW}
        (self.ops / "ops-state.json").write_text(json.dumps(st))
        self.event("1.json", ok("ab:ops:resume-all"))
        self.consume()
        self.assertEqual(self.lines, [("a", RESUME)])

    def test_repeated_pause_all_files_send_per_file(self):
        self.seed_queues(a="queue: running x (1/2)")
        for n in ("1.json", "2.json"):
            self.event(n, ok(f"ab:ops:pause-all-confirm:{int(NOW * 1000)}"))
        self.consume()
        self.consume()   # files are gone: nothing more
        self.assertEqual(self.lines, [("a", PAUSE), ("a", PAUSE)])

    def test_events_processed_in_filename_order(self):
        # mutation: iterate an unsorted glob -> order flips on filesystems that list reverse; here sorted() removal is checked via the reversed glob
        self.seed_queues(a="queue: running x (1/2)")
        self.event("2-b.json", {"type": "slash", "command": "resume", "project": "a", "user": "U1", "ts": NOW})
        self.event("1-a.json", {"type": "slash", "command": "pause", "project": "a", "user": "U1", "ts": NOW})
        real = Path.glob
        with mock.patch.object(Path, "glob", lambda self_, pat: reversed(list(real(self_, pat)))):
            self.consume()
        self.assertEqual([t for _, t in self.lines], [PAUSE, RESUME])

    def seed_merge(self, src="merge:7", spec="s1", ts=NOW):
        k = okey("a", src)
        st = json.loads((self.ops / "ops-state.json").read_text()) if (self.ops / "ops-state.json").exists() else {}
        st.setdefault("approvals", {})[k] = {"project": "a", "kind": "merge", "src_key": src, "spec": spec, "title": "t", "link": "", "ts": ts}
        (self.ops / "ops-state.json").write_text(json.dumps(st))
        return k

    def test_merge_calls_on_merge_and_edits_both_copies(self):
        k = self.seed_merge()
        self.event("1.json", ok(f"ab:ops:merge:{k}"))
        self.consume()
        (m,) = self.merges
        self.assertEqual((m[0], m[1], m[2]["kind"], m[2]["spec"]), ("a", "merge:7", "merge", "s1"))
        (ed,) = self.outbox()
        self.assertEqual(ed, {"op": "edit", "key": k, "text": "a: merge approved — sent to the lead"})
        (ped,) = self.outbox(self.pd)
        self.assertEqual(ped, {"op": "edit", "key": "merge:7", "text": "merge approved — sent to the lead"})
        self.assertEqual(self.audit()[-1]["result"], "merged abc")
        self.assertEqual(self.state()["approvals"], {})
        self.event("2.json", ok(f"ab:ops:merge:{k}"))   # second tap: record is gone
        self.consume()
        self.assertEqual(len(self.merges), 1)
        self.assertEqual(self.audit()[-1]["result"], "unknown")

    def test_merge_failure_keeps_record_and_audits_error(self):
        # mutation: pop the record before calling on_merge -> the record is gone and the test fails
        k = self.seed_merge()
        def boom(*a):
            raise RuntimeError("boom\nsecond line")
        self.on_merge = boom
        self.event("1.json", ok(f"ab:ops:merge:{k}"))
        self.consume()
        self.assertIn(k, self.state()["approvals"])
        self.assertEqual(self.audit()[-1]["result"], "error: boom")
        self.assertEqual(self.outbox(), [])
        self.assertEqual(list((self.ops / "events").glob("*.json")), [])

    def test_keep_edits_both_copies(self):
        # mutation: edit only the ops copy -> the project outbox stays empty and the test fails
        k = self.seed_merge("merge:8", "s2")
        self.event("1.json", ok(f"ab:ops:keep:{k}"))
        self.consume()
        self.assertEqual(self.lines, [("a", "[Discord] keep branch for s2")])
        self.assertEqual(self.outbox()[-1], {"op": "edit", "key": k, "text": "a: kept"})
        self.assertEqual(self.outbox(self.pd)[-1], {"op": "edit", "key": "merge:8", "text": "kept"})
        self.assertEqual(self.state()["approvals"], {})

    def test_keep_names_the_branch_when_the_record_has_it(self):
        k = self.seed_merge("merge:9:abcdef01", "s3")
        st = json.loads((self.ops / "ops-state.json").read_text())
        st["approvals"][k]["branch"] = "feat/z"
        (self.ops / "ops-state.json").write_text(json.dumps(st))
        self.event("1.json", ok(f"ab:ops:keep:{k}"))
        self.consume()
        self.assertEqual(self.outbox()[-1]["text"], "a: kept: feat/z")
        self.assertEqual(self.outbox(self.pd)[-1]["text"], "kept: feat/z")

    def test_event_exception_audited_as_error(self):
        # mutation: drop the audit line in consume's except -> no `error:` audit and the test fails
        def bad(p, t):
            raise OSError("disk gone\nmore")
        self.event("1.json", {"type": "slash", "command": "pause", "project": "a", "user": "U1", "ts": NOW})
        ops.consume(bad, lambda argv: "", NOW, on_merge=self.on_merge)
        self.assertEqual(self.audit()[-1]["result"], "error: disk gone")

    def test_known_project_from_last_tick_or_discord_dir(self):
        # mutation: back to bridge.json-only -> a project with a bare discord dir or only in the last tick is "unknown project"
        bare = tc_env.discord_dir("bare")
        bare.mkdir(parents=True)
        self.tick([rec("ticked")])
        for name in ("bare", "ticked", "nowhere"):
            self.event(f"{name}.json", {"type": "slash", "command": "pause", "project": name, "user": "U1", "ts": NOW})
        self.consume()
        self.assertEqual(sorted(p for p, _ in self.lines), ["bare", "ticked"])
        self.assertEqual([a["result"] for a in self.audit()], ["queued", "unknown project", "queued"])   # bare, nowhere, ticked

    def test_slash_pause_resume_and_unknown_project(self):
        self.event("1.json", {"type": "slash", "command": "pause", "project": "a", "user": "U1", "ts": NOW})
        self.event("2.json", {"type": "slash", "command": "resume", "project": "nope", "user": "U1", "ts": NOW})
        self.consume()
        self.assertEqual(self.lines, [("a", PAUSE)])
        self.assertEqual(self.audit()[-1]["result"], "unknown project")

    def test_modal_idea_and_new_spec(self):
        with mock.patch.object(ops.ideas, "add") as add:
            self.event("1.json", {"type": "modal", "form": "idea", "project": "a", "fields": {"title": "T  x", "text": "more\ndetail"}, "user": "U1", "ts": NOW})
            self.event("2.json", {"type": "modal", "form": "new-spec", "project": "a", "fields": {"what": "do  it", "why": "b" * 400}, "user": "U1", "ts": NOW})
            self.consume()
        add.assert_called_once_with("a", "T x", detail="more\ndetail")
        (p, text), = self.lines
        self.assertEqual(p, "a")
        self.assertEqual(text, "[Discord] new spec request: do it — " + "b" * 300)

    def test_read_and_rejected_audited(self):
        self.event("1.json", {"type": "read", "what": "/status", "user": "U1", "ts": NOW})
        self.event("2.json", {"type": "rejected", "what": "ab:ops:resume-all", "user": "EVIL", "ts": NOW})
        self.consume()
        self.assertEqual([a["result"] for a in self.audit()], ["answered", "rejected"])

    def test_handle_event_defaults_project_and_audits_to_d(self):
        allow = {"U1"}
        r = ops.handle_event("a", self.pd, {"type": "slash", "command": "pause", "user": "U1", "ts": NOW}, self.add, allow)
        self.assertEqual(self.lines, [("a", PAUSE)])
        self.assertEqual(r, "queued")
        self.assertTrue((self.pd / "audit.jsonl").exists())

    def audit(self):
        return [json.loads(l) for l in (self.ops / "audit.jsonl").read_text().splitlines()]


class FakeGauth:
    """Stands in for the gauth module: nothing here starts gcloud or a tmux window."""
    class GauthError(Exception):
        pass

    def __init__(self):
        self.calls, self.cfg, self.waiting = [], {"adc": True, "impersonate": "", "account": ""}, False
        self.url, self.res, self.start_err, self.send_err, self.check = "https://accounts.google.com/o/oauth2/auth?x=1", ("ok", "Credentials saved"), None, None, "token ok"
        self.no_config = False

    def load_config(self, p):
        self.calls.append(("load_config", p))
        if self.no_config:
            raise self.GauthError(f"no gauth config for {p}; set it at the terminal: tmux-ctl gauth config {p} …")
        return self.cfg

    def status(self, p):
        return "waiting" if self.waiting else "idle"

    def start(self, p):
        self.calls.append(("start", p))
        if self.start_err:
            raise self.start_err
        return "gauth-" + p

    def read_url(self, p, tmux=None, timeout=15):
        self.calls.append(("read_url", p))
        return self.url

    def send_code(self, p, code):
        self.calls.append(("send_code", p, code))
        if self.send_err:
            raise self.send_err

    def result(self, p):
        self.calls.append(("result", p))
        return self.res

    def token_check(self, cfg):
        return self.check

    def close(self, p):
        self.calls.append(("close", p))


class FakeClock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


CODE = "4/0AQSTgQ-SECRET-CODE-123"


class LeadGauth(Base):
    def setUp(self):
        super().setUp()
        self.configure()
        self.pd = self.project("a")
        self.g, self.clock, self.runs = FakeGauth(), FakeClock(), []
        for patcher in (mock.patch.object(ops, "gauth", self.g), mock.patch.object(ops, "_clock", self.clock),
                        mock.patch.object(ops, "_sleep", self.clock.sleep)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.run_out = "restarted a: pane %5"
        self.run_err = None

    def fake_run(self, argv):
        self.runs.append(argv)
        if self.run_err:
            raise self.run_err
        return self.run_out

    def send(self, ev, name="1.json"):
        self.event(name, ev)
        ops.consume(self.add, self.fake_run, NOW, spawn=lambda f: f())

    def audit(self):
        return [json.loads(l) for l in (self.ops / "audit.jsonl").read_text().splitlines()]

    def ireplies(self):
        return [o for o in self.outbox() if o["op"] == "ireply"]

    def lead(self, action="restart", user="U1", project="a", **kw):
        return {"type": "slash", "command": "lead", "action": action, "project": project, "user": user, "iid": "I1", "ts": NOW, **kw}

    def gauth(self, **kw):
        return {"type": "slash", "command": "gauth", "project": "a", "user": "U1", "iid": "I2", **kw}

    def modal(self, user="U1", code=CODE, project="a"):
        return {"type": "modal", "form": "gauth", "project": project, "user": user, "text": code, "ts": NOW}

    def pending(self):
        return json.loads((self.ops / "gauth-pending.json").read_text())

    def seed_pending(self, url_ts=NOW, user="U1"):
        (self.ops / "gauth-pending.json").write_text(json.dumps({"a": {"project": "a", "user": user, "iid": "I2", "url_ts": url_ts}}))

    # ---- /lead ----
    def test_lead_restart_runs_resume_and_ireplies_its_line(self):
        self.send(self.lead("restart"))
        self.assertEqual(self.runs, [[str(ops.discord_dialogs.BIN / "tmux-ctl"), "lead-restart", "a", "--resume"]])
        self.assertEqual(self.ireplies(), [{"op": "ireply", "iid": "I1", "content": "restarted a: pane %5"}])
        self.assertEqual((self.audit()[-1]["target"], self.audit()[-1]["result"]), ("a:lead:restart", "restarted"))

    def test_lead_handoff_passes_the_newest_doc(self):
        (self.ops / "views.json").write_text(json.dumps({"leads": {"a": {"doc": "/h/new.md"}}}))
        self.send(self.lead("handoff"))
        self.assertEqual(self.runs[0], [str(ops.discord_dialogs.BIN / "tmux-ctl"), "lead-restart", "a", "--doc", "/h/new.md"])
        self.assertEqual(self.audit()[-1]["result"], "restarted")

    def test_lead_handoff_without_a_doc_does_not_restart(self):
        self.send(self.lead("handoff"))
        self.assertEqual(self.runs, [])
        self.assertEqual(self.ireplies()[0]["content"], "no handoff doc for a")
        self.assertEqual(self.audit()[-1]["result"], "no handoff doc")

    def test_lead_failure_is_ireplied_and_audited(self):
        self.run_err = RuntimeError("lead-restart: no claude window")
        self.send(self.lead("restart"))
        self.assertIn("no claude window", self.ireplies()[0]["content"])
        self.assertEqual(self.audit()[-1]["result"], "failed")

    def test_lead_bad_action_or_unknown_project_runs_nothing(self):
        self.send(self.lead("nuke"), "1.json")
        self.send(self.lead("restart", project="nope"), "2.json")
        self.send(self.lead("restart", user="EVIL"), "3.json")
        self.assertEqual(self.runs, [])
        self.assertEqual([a["result"] for a in self.audit()], ["ignored", "unknown project", "rejected"])

    # ---- /gauth slash ----
    def test_gauth_no_config_ireplies_the_hint(self):
        self.g.no_config = True
        self.send(self.gauth())
        self.assertIn("tmux-ctl gauth config a", self.ireplies()[0]["content"])
        self.assertNotIn(("start", "a"), self.g.calls)
        self.assertEqual(self.audit()[-1]["result"], "no config")

    def test_gauth_already_waiting_is_refused(self):
        self.g.waiting = True
        self.send(self.gauth())
        self.assertNotIn(("start", "a"), self.g.calls)
        self.assertIn("already", self.ireplies()[0]["content"])
        self.assertEqual(self.audit()[-1]["result"], "busy")

    def test_gauth_sends_the_url_privately_with_the_button_and_stores_pending(self):
        # mutation: drop private=True -> the URL would be posted to the channel when the interaction expires
        self.send(self.gauth())
        r, = self.ireplies()
        self.assertTrue(r["private"])
        self.assertIn(self.g.url, r["content"])
        self.assertIn("10 min", r["content"])
        self.assertEqual(r["components"], [[{"label": "Enter code", "style": 1, "custom_id": "ab:gauth:code:a"}]])
        self.assertEqual(self.pending(), {"a": {"project": "a", "user": "U1", "iid": "I2", "url_ts": NOW}})
        self.assertEqual(self.audit()[-1]["result"], "url sent")

    def test_gauth_url_never_appears_polls_30s_then_closes(self):
        self.g.url = None
        self.send(self.gauth())
        self.assertIn(("close", "a"), self.g.calls)
        self.assertGreaterEqual(self.clock.t - NOW, 30)
        self.assertLess(self.clock.t - NOW, 40)
        self.assertEqual(self.audit()[-1]["result"], "failed")
        self.assertEqual(json.loads((self.ops / "gauth-pending.json").read_text()), {})

    # ---- /gauth modal ----
    def test_modal_same_user_within_window_sends_code_and_reports(self):
        self.seed_pending(url_ts=NOW - 599)
        self.send(self.modal())
        self.assertIn(("send_code", "a", CODE), self.g.calls)
        self.assertIn(("close", "a"), self.g.calls)
        self.assertIn("token ok", self.ireplies()[0]["content"])
        self.assertEqual(self.ireplies()[0]["iid"], "I2")
        self.assertEqual(self.audit()[-1]["result"], "authenticated")
        self.assertEqual(json.loads((self.ops / "gauth-pending.json").read_text()), {})

    def test_modal_auth_error_is_reported(self):
        self.seed_pending()
        self.g.res = ("error", "ERROR: invalid_grant")
        self.send(self.modal())
        self.assertIn("invalid_grant", self.ireplies()[0]["content"])
        self.assertEqual(self.audit()[-1]["result"], "auth failed")
        self.assertIn(("close", "a"), self.g.calls)

    def test_modal_non_allowlisted_user_is_rejected_and_sends_nothing(self):
        self.seed_pending()
        self.send(self.modal(user="U2"))
        self.assertFalse([c for c in self.g.calls if c[0] == "send_code"])
        self.assertEqual(self.audit()[-1]["result"], "rejected")   # U2 is not on the allowlist either

    def test_modal_allowlisted_other_user_is_ignored(self):
        (self.ops / "access.json").write_text(json.dumps({"allowFrom": ["U1", "U2"]}))
        self.seed_pending()
        self.send(self.modal(user="U2"))
        self.assertFalse([c for c in self.g.calls if c[0] == "send_code"])
        self.assertEqual(self.audit()[-1]["result"], "ignored")
        self.assertTrue((self.ops / "gauth-pending.json").exists())

    def test_modal_late_is_ignored_closes_and_says_timed_out(self):
        # mutation: change the 600 s window to 700 -> a 650 s old code is sent
        self.seed_pending(url_ts=NOW - 601)
        self.send(self.modal())
        self.assertFalse([c for c in self.g.calls if c[0] == "send_code"])
        self.assertIn(("close", "a"), self.g.calls)
        self.assertEqual(self.audit()[-1]["result"], "timed out")
        self.assertIn("timed out", self.ireplies()[0]["content"])

    def test_modal_without_pending_is_ignored(self):
        self.send(self.modal())
        self.assertFalse([c for c in self.g.calls if c[0] == "send_code"])
        self.assertEqual(self.audit()[-1]["result"], "ignored")

    def test_modal_unknown_project_never_reaches_gauth(self):
        self.send(self.modal(project="../x"))
        self.assertEqual(self.g.calls, [])

    def test_code_never_in_audit_logs_posts_or_reraised_errors(self):
        # mutation: put the code in an audit target/result, a print, or let the GauthError text through -> a hit below
        import io
        import contextlib
        self.seed_pending()
        self.g.send_err = self.g.GauthError(f"tmux failed: {CODE}")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(err):
            self.send(self.modal(), "1.json")
        self.seed_pending()
        self.g.send_err = None
        self.g.res = ("error", f"ERROR: bad code {CODE}")
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(err):
            self.send(self.modal(), "2.json")
        files = [self.ops / "audit.jsonl"] + list((self.ops / "outbox").glob("*.json")) + [self.ops / "ops-state.json"]
        for f in files:
            self.assertEqual(f.read_text().count(CODE), 0, f.name)
        self.assertEqual(err.getvalue().count(CODE), 0)
        self.assertTrue(self.ireplies())

    # ---- tick ----
    def tick_now(self, now):
        return ops.tick([rec("a")], {}, None, now, self.add)

    # ---- the slow work leaves consume ----
    def test_consume_returns_before_any_slow_step(self):
        # mutation: call the worker inline in handle_event (spawn(fn) -> fn()) -> start/read_url/run happen inside consume
        spawned = []
        self.event("1.json", self.gauth())
        self.event("2.json", self.lead("restart"), )
        ops.consume(self.add, self.fake_run, NOW, spawn=spawned.append)
        self.assertEqual(len(spawned), 2)
        self.assertEqual(self.runs, [])
        self.assertEqual([c for c in self.g.calls if c[0] in ("start", "read_url")], [])
        self.assertEqual(self.ireplies(), [])
        self.assertIn("a", self.pending())   # written before the worker starts
        self.assertEqual(self.clock.t, NOW)
        spawned[0]()
        self.assertIn(("start", "a"), self.g.calls)

    def test_default_spawn_runs_the_worker_on_another_thread(self):
        import threading
        seen = []
        done = threading.Event()
        self.g.read_url = lambda p, tmux=None, timeout=15: (seen.append(threading.current_thread()), done.set(), self.g.url)[2]
        self.event("1.json", self.gauth())
        ops.consume(self.add, self.fake_run, NOW)
        self.assertTrue(done.wait(5))
        self.assertIsNot(seen[0], threading.main_thread())
        self.assertTrue(seen[0].daemon)

    def test_a_dead_gauth_worker_is_closed_by_the_tick_sweep(self):
        self.event("1.json", self.gauth())
        ops.consume(self.add, self.fake_run, NOW, spawn=lambda f: None)   # the worker never ran
        self.tick_now(NOW + 601)
        self.assertIn(("close", "a"), self.g.calls)
        self.assertEqual(self.audit()[-1]["result"], "timed out")

    def test_second_gauth_while_pending_is_busy(self):
        self.event("1.json", self.gauth())
        ops.consume(self.add, self.fake_run, NOW, spawn=lambda f: None)
        self.send(self.gauth(iid="I3"), "2.json")
        self.assertEqual(self.audit()[-1]["result"], "busy")

    def test_lead_run_wins_over_run_for_lead_restart(self):
        calls = []
        self.event("1.json", self.lead("restart"))
        ops.consume(self.add, self.fake_run, NOW, lead_run=lambda a: calls.append(a) or "ok line", spawn=lambda f: f())
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.runs, [])
        self.assertEqual(self.ireplies()[0]["content"], "ok line")

    # ---- any exception in the worker closes the window ----
    def test_read_url_raising_closes_and_ireplies(self):
        # mutation: catch only GauthError in the slash worker -> window, .waiting and pending stay
        self.g.read_url = mock.Mock(side_effect=RuntimeError("tmux capture failed"))
        self.send(self.gauth())
        self.assertIn(("close", "a"), self.g.calls)
        self.assertFalse(json.loads((self.ops / "gauth-pending.json").read_text()))
        self.assertIn("RuntimeError", self.ireplies()[0]["content"])
        self.assertEqual(self.audit()[-1]["result"], "failed")

    def test_result_raising_closes_and_ireplies(self):
        self.seed_pending()
        self.g.result = mock.Mock(side_effect=RuntimeError("tmux capture failed"))
        self.send(self.modal())
        self.assertIn(("close", "a"), self.g.calls)
        self.assertFalse(json.loads((self.ops / "gauth-pending.json").read_text()))
        self.assertIn("RuntimeError", self.ireplies()[0]["content"])
        self.assertEqual(self.audit()[-1]["result"], "auth failed")

    def test_start_raising_plain_exception_closes(self):
        self.g.start_err = RuntimeError("boom")
        self.send(self.gauth())
        self.assertIn(("close", "a"), self.g.calls)
        self.assertEqual(self.audit()[-1]["result"], "failed")

    def test_modal_resubmit_while_sending_is_ignored(self):
        self.seed_pending()
        self.event("1.json", self.modal())
        ops.consume(self.add, self.fake_run, NOW, spawn=lambda f: None)
        self.send(self.modal(), "2.json")
        self.assertFalse([c for c in self.g.calls if c[0] == "send_code"])
        self.assertEqual(self.audit()[-1]["result"], "ignored")

    def test_tick_closes_a_timed_out_gauth(self):
        # mutation: drop the tick sweep -> window stays open and pending stays
        self.seed_pending(url_ts=NOW - 601)
        self.tick_now(NOW)
        self.assertIn(("close", "a"), self.g.calls)
        self.assertEqual(json.loads((self.ops / "gauth-pending.json").read_text()), {})
        self.assertIn("timed out", self.ireplies()[0]["content"])
        self.assertEqual((self.audit()[-1]["target"], self.audit()[-1]["result"]), ("a:gauth", "timed out"))

    def test_tick_leaves_a_fresh_gauth_alone(self):
        self.seed_pending(url_ts=NOW - 100)
        self.tick_now(NOW)
        self.assertNotIn(("close", "a"), self.g.calls)
        self.assertIn("a", json.loads((self.ops / "gauth-pending.json").read_text()))


class ControlsHooks(Base):
    """The hook discord_controls has into discord_ops (slash/modal/read/rejected events), driven through the real controls step."""
    SRC = "%5:" + hashlib.sha1(b"x").hexdigest()

    def setUp(self):
        super().setUp()
        self.configure()
        self.pd = self.project("a")
        (self.pd / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))
        self.shows = {"w1": "T:Bash\nP:x\n", "w2": "T:Edit\nP:y\n"}

    def run_(self, argv):
        if argv[3] == "show":
            if self.shows.get(argv[2]) is None:
                raise RuntimeError("approve: no permission prompt")
            return self.shows[argv[2]]
        return ""

    def step(self, needs=("w1",)):
        import discord_controls as dc
        r = {"needs_you": [{"window": w, "pane": "%5", "kind": "claude", "reason": ""} for w in needs]}
        dc.step("a", r, NOW, self.run_, self.add)

    def test_slash_modal_read_rejected_routed_to_handle_event(self):
        # mutation: delete the routing branch in consume_events -> these fall to the click audit and the results differ
        evs = [{"type": "slash", "command": "pause", "project": "a", "user": "U1", "ts": NOW},
               {"type": "read", "what": "/status", "user": "U1", "ts": NOW},
               {"type": "rejected", "what": "/pause", "user": "EVIL", "ts": NOW}]
        for i, e in enumerate(evs):
            self.event(f"{i}.json", e, d=self.pd)
        with mock.patch.object(ops.ideas, "add"):
            self.event("3.json", {"type": "modal", "form": "idea", "fields": {"title": "T", "text": "d"}, "user": "U1", "ts": NOW}, d=self.pd)
            self.step(needs=())
        au = [json.loads(l) for l in (self.pd / "audit.jsonl").read_text().splitlines()]
        self.assertEqual([a["result"] for a in au], ["queued", "answered", "rejected", "idea added"])
        self.assertEqual(self.lines, [("a", PAUSE)])


class FeedChanges(Base):
    def test_check_accepts_approval_and_post_key(self):
        df._check({"op": "approval", "key": "k", "kind": "perm", "text": "t", "mention_user": True})
        df._check({"op": "approval", "key": "k", "kind": "question", "text": "t", "mention_user": True, "link": "https://x", "project": "a"})
        df._check({"op": "post", "text": "t", "tier": "critical", "mention_user": True, "key": "k"})
        with self.assertRaises(ValueError):
            df._check({"op": "approval", "key": "k", "kind": "bogus", "text": "t", "mention_user": True})
        with self.assertRaises(ValueError):
            df._check({"op": "approval", "key": "k", "kind": "perm", "text": "t"})

    def test_approval_survives_cap(self):
        d = self.ops
        df.outbox_write(d, {"op": "approval", "key": "k", "kind": "perm", "text": "t", "mention_user": True})
        for _ in range(df.CAP + 5):
            df.outbox_write(d, {"op": "post", "text": "x", "tier": "progress", "mention_user": False})
        self.assertEqual(len([o for o in self.outbox() if o["op"] == "approval"]), 1)

    def test_decision_post_gets_key_and_merge_key(self):
        evs = [{"ts": 5, "project": "a", "spec": "s", "kind": "needs_you", "tier": "decision", "text": "hi", "refs": {}},
               {"ts": 6, "project": "a", "spec": "s", "kind": "merge_approval", "tier": "decision", "text": "m", "refs": {"task": "7"}}]
        ops_ = df.ops_for_events(evs, {})
        self.assertEqual(ops_[0]["key"], "dec:" + hashlib.sha1(b"5|hi").hexdigest()[:12])
        self.assertEqual(ops_[1]["key"], "merge:7")
        crit = df.ops_for_events([{"ts": 1, "project": "a", "spec": "", "kind": "x", "tier": "critical", "text": "c", "refs": {}}], {})
        self.assertNotIn("key", crit[0])


if __name__ == "__main__":
    unittest.main()
