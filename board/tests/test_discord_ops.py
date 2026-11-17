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
        self.on_merge = lambda *a: self.merges.append(a)

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
        self.assertEqual(lines[1], "**a** · queue: running x (1/2) · 1/3 · blockers: ctx 90% · waiting on you: 1 · <https://discord.com/channels/9/1>")
        self.assertEqual(lines[2], "**b** · queue: idle · 0/0 · blockers: none · waiting on you: 0")
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
        self.assertEqual(v["queue"]["a"].split("\n"), ["queue: running y (2/3)", "✓ x — merged", "▶ y", "· z"])
        self.assertEqual(v["approvals"], [])
        self.assertEqual(v["evidence"], {})
        self.assertFalse(list(self.ops.glob("*.tmp")))

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
        self.assertEqual(ap["key"], okey("a", "merge:7"))
        self.assertEqual(self.state()["approvals"][ap["key"]]["src_key"], "merge:7")

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


class Mirror(Base):
    def test_mirror_prompt_posts_perm_and_resolve_edits(self):
        self.configure()
        lines = [f"l{i}" for i in range(20)]
        ops.mirror_prompt("a", "%5:abc", "w1", "Bash command", lines)
        (ap,) = self.outbox()
        self.assertEqual((ap["op"], ap["kind"], ap["key"]), ("approval", "perm", okey("a", "%5:abc")))
        self.assertTrue(ap["text"].startswith("🔐 a · w1 wants to run Bash command\n```\n"))
        self.assertIn("l14", ap["text"])
        self.assertNotIn("l15", ap["text"])
        ops.mirror_prompt("a", "%5:abc", "w1", "Bash command", lines)   # same key: no second post
        self.assertEqual(len(self.outbox()), 1)
        ops.resolve("a", "%5:abc", "✅ allowed by you")
        ed = self.outbox()[1]
        self.assertEqual((ed["op"], ed["key"], ed["text"]), ("edit", ap["key"], "a: ✅ allowed by you"))
        self.assertEqual(self.state()["approvals"], {})

    def test_noop_when_unconfigured(self):
        # mutation: drop the configured() guard in mirror_prompt/resolve -> the outbox appears
        ops.mirror_prompt("a", "k", "w", "t", ["x"])
        ops.resolve("a", "k", "x")
        self.assertFalse((self.ops / "outbox").exists())

    def test_resolve_unknown_key_edits_nothing(self):
        self.configure()
        ops.resolve("a", "never-mirrored", "x")
        self.assertEqual(self.outbox(), [])

    def test_resolve_removes_from_views(self):
        self.configure()
        self.project("a")
        ops.mirror_prompt("a", "k1", "w", "t", ["x"])
        self.tick([rec("a")])
        self.assertEqual(len(json.loads((self.ops / "views.json").read_text())["approvals"]), 1)
        ops.resolve("a", "k1", "done")
        self.assertEqual(json.loads((self.ops / "views.json").read_text())["approvals"], [])


class Events(Base):
    def setUp(self):
        super().setUp()
        self.configure()
        self.pd = self.project("a")
        self.project("b")

    def test_allow_forwarded_as_perm_event(self):
        ops.mirror_prompt("a", "%5:abc", "w1", "Bash", ["x"])
        self.event("1.json", ok(f"ab:ops:allow:{okey('a', '%5:abc')}"))
        self.consume()
        (f,) = (self.pd / "events").glob("*.json")
        ev = json.loads(f.read_text())
        self.assertEqual((ev["type"], ev["key"], ev["choice"], ev["user"]), ("perm", "%5:abc", "allow", "U1"))
        self.assertEqual(self.audit()[-1]["result"], "forwarded")
        self.assertEqual(list((self.ops / "events").glob("*.json")), [])

    def test_deny_forwarded(self):
        ops.mirror_prompt("a", "k", "w1", "Bash", ["x"])
        self.event("1.json", ok(f"ab:ops:deny:{okey('a', 'k')}"))
        self.consume()
        (f,) = (self.pd / "events").glob("*.json")
        self.assertEqual(json.loads(f.read_text())["choice"], "deny")

    def test_allow_unknown_key_forwards_nothing(self):
        self.event("1.json", ok("ab:ops:allow:deadbeef0000"))
        self.consume()
        self.assertEqual(list((self.pd / "events").glob("*.json")), [])
        self.assertEqual(self.audit()[-1]["result"], "unknown")

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

    def test_repeated_pause_all_files_send_per_file(self):
        self.seed_queues(a="queue: running x (1/2)")
        for n in ("1.json", "2.json"):
            self.event(n, ok(f"ab:ops:pause-all-confirm:{int(NOW * 1000)}"))
        self.consume()
        self.consume()   # files are gone: nothing more
        self.assertEqual(self.lines, [("a", PAUSE), ("a", PAUSE)])

    def test_duplicate_allow_presses_once(self):
        # drive the real controls step: the second forwarded perm event finds no prompt and presses nothing
        import discord_controls as dc
        src = '%5:' + hashlib.sha1(b'x').hexdigest()
        ops.mirror_prompt("a", src, "w1", "Bash", ["x"])
        k = okey("a", src)
        for n in ("1.json", "2.json"):
            self.event(n, ok(f"ab:ops:allow:{k}"))
        self.consume()
        presses = []
        def run(argv):
            if argv[3] == "show":
                return "T:Bash\nP:x\n"
            presses.append(argv)
            return ""
        (self.pd / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))
        (self.pd / "controls-state.json").write_text(json.dumps({"prompts": {src: {"window": "w1", "pane": "%5", "tool": "Bash", "lines": ["x"], "ts": NOW}}}))
        dc.step("a", {"needs_you": []}, NOW, run, self.add)
        self.assertEqual(len(presses), 1)

    def test_events_processed_in_filename_order(self):
        # mutation: iterate an unsorted glob -> order flips on filesystems that list reverse; here sorted() removal is checked via the reversed glob
        self.seed_queues(a="queue: running x (1/2)")
        self.event("2-b.json", {"type": "slash", "command": "resume", "project": "a", "user": "U1", "ts": NOW})
        self.event("1-a.json", {"type": "slash", "command": "pause", "project": "a", "user": "U1", "ts": NOW})
        real = Path.glob
        with mock.patch.object(Path, "glob", lambda self_, pat: reversed(list(real(self_, pat)))):
            self.consume()
        self.assertEqual([t for _, t in self.lines], [PAUSE, RESUME])

    def test_merge_and_keep(self):
        k = okey("a", "merge:7")
        (self.ops / "ops-state.json").write_text(json.dumps({"approvals": {k: {"project": "a", "kind": "merge", "src_key": "merge:7", "spec": "s1", "title": "t", "link": "", "ts": NOW}}}))
        self.event("1.json", ok(f"ab:ops:merge:{k}"))
        self.consume()
        self.assertEqual(len(self.merges), 1)
        self.assertEqual(self.merges[0][0:2], ("a", "merge:7"))
        self.event("2.json", ok(f"ab:ops:merge:{k}"))   # second tap: record is gone
        self.consume()
        self.assertEqual(len(self.merges), 1)
        self.assertEqual(self.audit()[-1]["result"], "unknown")
        k2 = okey("a", "merge:8")
        (self.ops / "ops-state.json").write_text(json.dumps({"approvals": {k2: {"project": "a", "kind": "merge", "src_key": "merge:8", "spec": "s2", "title": "t", "link": "", "ts": NOW}}}))
        self.event("3.json", ok(f"ab:ops:keep:{k2}"))
        self.consume()
        self.assertEqual(self.lines, [("a", "[Discord] keep branch for s2")])

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
