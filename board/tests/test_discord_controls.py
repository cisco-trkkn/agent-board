"""discord_controls: react, click and reply consumption (the dialog routes are tested in test_discord_dialogs). Scratch TC_STATE; the runner and add_line are fakes.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_controls as dc  # noqa: E402
import tc_env  # noqa: E402

TC = str(dc.BIN / "tmux-ctl")
NOPROMPT = "approve: no permission prompt in w1"


class Runner:
    def __init__(self, shows=None, approve=None):
        self.calls, self.shows, self.approve = [], shows if shows is not None else {}, approve

    @property
    def presses(self):
        return [c for c in self.calls if c[3] != "show"]

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[2:4] and argv[3] == "show":
            v = self.shows.get(argv[2], NOPROMPT)
            if v.startswith("approve:"):
                raise RuntimeError(v)
            return v
        if isinstance(self.approve, Exception):
            raise self.approve
        return self.approve or ""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.d = tc_env.discord_dir("p")
        self.d.mkdir(parents=True)
        (self.d / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))
        self.lines = []
        self.add = lambda s, t: self.lines.append((s, t))

    def rec(self, *wins):
        return {"needs_you": [{"window": w, "pane": "%5", "kind": "permission", "reason": "x"} for w in wins]}

    def ops(self):
        return [json.loads(f.read_text()) for f in sorted((self.d / "outbox").glob("*.json"))] if (self.d / "outbox").exists() else []

    def audit(self):
        p = self.d / "audit.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def event(self, name, ev, raw=None):
        (self.d / "events").mkdir(exist_ok=True)
        (self.d / "events" / name).write_text(raw if raw is not None else json.dumps(ev))

    def step(self, runner, rec=None, now=100.0):
        return dc.step("p", rec if rec is not None else self.rec(), now, runner, self.add)

    def state(self):
        return json.loads((self.d / "controls-state.json").read_text())


class LeftoverPermTest(Base):
    """The old 🔐 prompt buttons are gone: a perm event left in the events dir presses nothing and is audited `unknown`."""

    def test_leftover_perm_event_is_unknown_and_presses_nothing(self):
        self.event("1-a.json", {"type": "perm", "key": "%5:abc", "choice": "allow", "user": "U1", "message_id": "m", "ts": 1})
        r = Runner()
        self.step(r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.ops(), [])
        self.assertEqual([(a["action"], a["result"]) for a in self.audit()], [("perm", "unknown")])
        self.assertEqual(list((self.d / "events").glob("*.json")), [])

    def test_leftover_perm_event_of_a_stranger_is_rejected(self):  # mutation: skip the allowlist -> "unknown"
        self.event("1-a.json", {"type": "perm", "key": "%5:abc", "choice": "allow", "user": "X", "message_id": "m", "ts": 1})
        self.step(Runner())
        self.assertEqual(self.audit()[-1]["result"], "rejected")

    def test_step_never_scans_panes(self):
        r = Runner()
        self.step(r, self.rec("w1"))
        self.assertEqual(r.calls, [])
        self.assertFalse(hasattr(dc, "scan_prompts") or hasattr(dc, "_perm"))


class ReactTest(Base):
    EXP = {"✅": '[Discord] ✅ yes to your message "hi there"', "❌": '[Discord] ❌ no to your message "hi there"',
           "🛑": "[Discord] 🛑 pause the queue", "▶️": "[Discord] ▶️ resume the queue", "⏭️": "[Discord] ⏭️ skip the running spec"}

    def react(self, emoji, user="U1", name="1-a.json", excerpt="hi\nthere"):
        self.event(name, {"type": "react", "emoji": emoji, "message_id": "m", "excerpt": excerpt, "user": user, "ts": 1})

    def test_five_emoji(self):
        for i, (e, line) in enumerate(self.EXP.items()):
            self.react(e, name=f"{i}-a.json")
        self.step(Runner())
        self.assertEqual(self.lines, [("p", l) for l in self.EXP.values()])
        self.assertEqual([a["result"] for a in self.audit()], ["queued"] * 5)
        self.assertEqual([a["target"] for a in self.audit()], list(self.EXP))

    def test_unknown_and_rejected(self):  # mutation: skip allowlist -> a line is queued
        self.react("👍")
        self.react("✅", user="X", name="2-a.json")
        self.step(Runner())
        self.assertEqual(self.lines, [])
        self.assertEqual([a["result"] for a in self.audit()], ["ignored", "rejected"])


class FilesTest(Base):
    def test_click_ignored_bad_file_failed_order(self):
        self.event("3-c.json", None, raw="{nope")
        self.event("2-b.json", {"type": "click", "custom_id": "ab:x", "user": "U1", "message_id": "m", "channel_id": "c", "ts": 1})
        self.event("1-a.json", {"type": "react", "emoji": "🛑", "user": "U1", "message_id": "m", "excerpt": "", "ts": 1})
        self.event("4-d.json", None, raw="[1]")
        self.step(Runner())
        self.assertEqual(self.lines, [("p", "[Discord] 🛑 pause the queue")])
        self.assertEqual([(a["action"], a["result"]) for a in self.audit()], [("react", "queued"), ("click", "ignored")])
        self.assertEqual(list((self.d / "events").glob("*.json")), [])
        self.assertEqual(sorted(f.name for f in (self.d / "events" / "failed").iterdir()), ["3-c.json", "4-d.json"])

    def test_click_rejected_user(self):
        self.event("1-a.json", {"type": "click", "custom_id": "ab:x", "user": "X", "message_id": "m", "channel_id": "c", "ts": 1})
        self.step(Runner())
        self.assertEqual(self.audit()[-1]["result"], "rejected")


class DreamClickTest(Base):
    CID = "ab:dream:revert:p:20261119-0300"

    def click(self, name, cid, user="U1"):
        self.event(name, {"type": "click", "custom_id": cid, "user": user, "message_id": "m", "channel_id": "c", "ts": 1})

    def test_allowlisted_click_runs_and_is_audited(self):   # mutation: no ab:dream: branch -> audit says "ignored"
        self.click("1-a.json", self.CID)
        with mock.patch.object(dc.dream_discord, "click", return_value="reverted") as c:
            self.step(Runner())
        c.assert_called_once()
        self.assertEqual(c.call_args.args[:3], ("p", "U1", self.CID))
        self.assertEqual([(a["action"], a["target"], a["result"]) for a in self.audit()], [("click", self.CID, "reverted")])
        self.assertEqual(list((self.d / "events").glob("*.json")), [])

    def test_other_user_rejected_and_nothing_runs(self):
        self.click("1-a.json", self.CID, user="X")
        with mock.patch.object(dc.dream_discord, "click") as c:
            self.step(Runner())
        c.assert_not_called()
        self.assertEqual(self.audit()[-1]["result"], "rejected")
        self.assertEqual(list((self.d / "events").glob("*.json")), [])

    def test_other_project_and_malformed(self):
        self.click("1-a.json", "ab:dream:revert:other:20261119-0300")
        self.click("2-b.json", "ab:dream:revert:p:nope")
        self.step(Runner())
        self.assertEqual([a["result"] for a in self.audit()], ["ignored", "unknown"])


class AnalyticsClickTest(Base):
    CID = "ab:analytics:idea:2026-W47:1"

    def run_click(self, user):
        self.event("1-a.json", {"type": "click", "custom_id": self.CID, "user": user, "message_id": "m", "channel_id": "c", "ts": 1})
        with mock.patch.object(dc.analytics_post, "click", return_value="filed") as c:
            self.step(Runner())
        return c

    def test_allowed_click_audits_result(self):   # mutation: no ab:analytics: branch -> audit says "ignored"
        c = self.run_click("U1")
        c.assert_called_once()
        self.assertEqual(c.call_args.args[:3], (self.d, "U1", self.CID))
        self.assertEqual([(a["action"], a["target"], a["result"]) for a in self.audit()], [("click", self.CID, "filed")])

    def test_other_user_rejected_and_nothing_runs(self):
        c = self.run_click("X")
        c.assert_not_called()
        self.assertEqual(self.audit()[-1]["result"], "rejected")


class DiscoverClickTest(Base):
    CID = "ab:discover:file:p:0123456789ab"

    def run_click(self, user):
        self.event("1-a.json", {"type": "click", "custom_id": self.CID, "user": user, "message_id": "m", "channel_id": "c", "ts": 1})
        with mock.patch.object(dc.discover_post, "click", return_value="filed") as c:
            self.step(Runner())
        return c

    def test_allowed_click_audits_result(self):   # mutation: no ab:discover: branch -> audit says "ignored"
        c = self.run_click("U1")
        c.assert_called_once()
        self.assertEqual(c.call_args.args[:3], ("p", "U1", self.CID))
        self.assertEqual([(a["action"], a["target"], a["result"]) for a in self.audit()], [("click", self.CID, "filed")])

    def test_other_user_rejected_and_nothing_runs(self):
        c = self.run_click("X")
        c.assert_not_called()
        self.assertEqual(self.audit()[-1]["result"], "rejected")


class ScoutRouteTest(Base):
    CID = "ab:scout:approve:agent-board:0123456789ab"
    KEY = "ab:scout:reject:agent-board:0123456789ab"

    def run_event(self, ev, fn, ret):
        self.event("1-a.json", dict(ev, message_id="m", channel_id="c", ts=1))
        with mock.patch.object(dc.scout_post, fn, return_value=ret) as c, \
                mock.patch.object(dc.discord_dialogs, "reply", side_effect=AssertionError("dialog consumer must not see it")):
            self.step(Runner())
        return c

    def test_click_routes_with_add_line(self):   # mutation: no ab:scout: click branch -> audit says "ignored"
        c = self.run_event({"type": "click", "custom_id": self.CID, "user": "U1"}, "click", "approved")
        c.assert_called_once()
        self.assertEqual(c.call_args.args[:2], ("U1", self.CID))
        c.call_args.kwargs["add_line"]("[Scout] x")
        self.assertEqual(self.lines, [("p", "[Scout] x")])
        self.assertEqual([(a["action"], a["target"], a["result"]) for a in self.audit()], [("click", self.CID, "approved")])

    def test_click_other_user_rejected(self):
        c = self.run_event({"type": "click", "custom_id": self.CID, "user": "X"}, "click", "approved")
        c.assert_not_called()
        self.assertEqual(self.audit()[-1]["result"], "rejected")

    def test_reply_routes_before_dialogs(self):   # mutation: dialog consumer first -> the AssertionError above
        c = self.run_event({"type": "reply", "key": self.KEY, "text": "too risky", "user": "U1"}, "reply", "noted")
        c.assert_called_once()
        self.assertEqual((c.call_args.args[:3]), ("U1", self.KEY, "too risky"))
        self.assertEqual([(a["action"], a["target"], a["result"]) for a in self.audit()], [("scout-reply", self.KEY, "noted")])

    def test_reply_other_user_rejected(self):
        c = self.run_event({"type": "reply", "key": self.KEY, "text": "t", "user": "X"}, "reply", "noted")
        c.assert_not_called()
        self.assertEqual(self.audit()[-1]["result"], "rejected")


class ScoutSourceRouteTest(Base):
    """Scout source requests (`source:` in #scout, /source) and the check mark on their prompt, on the agent-board bot only."""
    P = "agent-board"

    def setUp(self):
        super().setUp()
        self.d = tc_env.discord_dir(self.P)
        self.d.mkdir(parents=True)
        (self.d / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))

    def run_ev(self, ev, project=None, pending=False, **fns):
        self.event("1-a.json", dict(ev, ts=1))
        mocks = {n: mock.patch.object(dc.scout_sources, n, **({"side_effect": v} if isinstance(v, Exception) else {"return_value": v}))
                 for n, v in dict({"discord_request": "prompted", "discord_confirm": ("blog", "added"), "is_pending": pending}, **fns).items()}
        got = {n: m.start() for n, m in mocks.items()}
        for m in mocks.values():
            self.addCleanup(m.stop)
        dc.step(project or self.P, self.rec(), 100.0, Runner(), self.add)
        return got

    def shape(self):
        return [(a["user"], a["action"], a["target"], a["result"]) for a in self.audit()]

    SRC = {"type": "source", "via": "message", "text": "source: https://a.example/feed", "message_id": "200", "channel_id": "300", "user": "U1"}
    REACT = {"type": "react", "emoji": "✅", "message_id": "9001", "channel_id": "300", "scout": True, "user": "U1"}

    def test_source_event_reaches_the_request_handler(self):   # mutation: no source branch -> audited as an ignored click
        got = self.run_ev(self.SRC)
        got["discord_request"].assert_called_once()
        self.assertEqual(got["discord_request"].call_args.args[0]["text"], "source: https://a.example/feed")
        self.assertEqual(self.shape(), [("U1", "scout-source", "source: https://a.example/feed", "prompted")])

    def test_slash_source_event_is_audited_by_its_url(self):
        self.run_ev({"type": "source", "via": "slash", "url": "https://a.example/feed", "name": "", "iid": "I1", "message_id": "7", "channel_id": "3", "user": "U1"})
        self.assertEqual(self.shape(), [("U1", "scout-source", "https://a.example/feed", "prompted")])

    def test_source_event_of_a_stranger_is_rejected(self):   # mutation: skip the allowlist -> the handler runs
        got = self.run_ev(dict(self.SRC, user="X"))
        got["discord_request"].assert_not_called()
        self.assertEqual(self.shape(), [("X", "scout-source", "source: https://a.example/feed", "rejected")])

    def test_checkmark_on_a_prompt_adds_and_is_not_a_yes_to_the_lead(self):   # mutation: react branch first -> the lead gets a yes line
        got = self.run_ev(dict(self.REACT, excerpt="blog · rss"))
        self.assertEqual(got["discord_confirm"].call_args.args[:2], ("9001", "U1"))
        self.assertEqual(self.shape(), [("U1", "scout-source", "blog", "added")])
        self.assertEqual(self.lines, [])

    def test_checkmark_of_a_stranger_is_rejected_and_adds_nothing(self):
        got = self.run_ev(dict(self.REACT, user="X"))
        got["discord_confirm"].assert_not_called()
        self.assertEqual(self.shape(), [("X", "scout-source", "9001", "rejected")])
        self.assertEqual(self.lines, [])

    def test_home_channel_react_event_on_a_pending_prompt_is_the_scouts(self):
        ev = {k: v for k, v in self.REACT.items() if k != "scout"}   # the bridge's plain home-channel react event
        got = self.run_ev(dict(ev, excerpt="blog · rss"), pending=True)
        got["discord_confirm"].assert_called_once()
        self.assertEqual(self.lines, [])

    def test_checkmark_on_any_other_message_still_goes_to_the_lead(self):
        ev = {k: v for k, v in self.REACT.items() if k != "scout"}
        got = self.run_ev(dict(ev, excerpt="ship it?"), pending=False)
        got["discord_confirm"].assert_not_called()
        self.assertEqual(self.lines, [(self.P, '[Discord] ✅ yes to your message "ship it?"')])
        self.assertEqual(self.shape(), [("U1", "react", "✅", "queued")])

    def test_checkmark_on_a_prompt_that_is_gone(self):   # a second check mark: nothing to add, and no line for the lead
        self.run_ev(self.REACT, discord_confirm=None)
        self.assertEqual(self.shape(), [("U1", "scout-source", "9001", "gone")])
        self.assertEqual(self.lines, [])

    def test_other_emoji_with_the_scout_mark_is_not_routed(self):
        got = self.run_ev(dict(self.REACT, emoji="❌", excerpt="x"))
        got["discord_confirm"].assert_not_called()
        self.assertEqual(self.shape(), [("U1", "react", "❌", "queued")])

    def test_another_projects_bot_never_routes_to_the_scout(self):
        tc_env.discord_dir("p").joinpath("events").mkdir(exist_ok=True)
        (tc_env.discord_dir("p") / "events" / "1-a.json").write_text(json.dumps(dict(self.SRC, ts=1)))
        with mock.patch.object(dc.scout_sources, "discord_request") as req:
            dc.step("p", self.rec(), 100.0, Runner(), self.add)
        req.assert_not_called()
        a = [json.loads(l) for l in (tc_env.discord_dir("p") / "audit.jsonl").read_text().splitlines()]
        self.assertEqual([(x["action"], x["result"]) for x in a], [("click", "ignored")])

    def test_busy_scout_lock_leaves_the_event_for_the_next_tick(self):
        # mutation: consume a busy event -> a check mark given while the daily poll runs is lost until the next poll
        fresh = dict(self.REACT, ts=int(time.time() * 1000))
        (self.d / "events").mkdir(exist_ok=True)
        (self.d / "events" / "5-a.json").write_text(json.dumps(fresh))
        with mock.patch.object(dc.scout_sources, "discord_confirm", side_effect=dc.scout_sources.Busy()):
            dc.step(self.P, self.rec(), 100.0, Runner(), self.add)
        self.assertEqual(self.shape(), [])
        self.assertEqual([f.name for f in (self.d / "events").glob("*.json")], ["5-a.json"])
        with mock.patch.object(dc.scout_sources, "discord_confirm", return_value=("blog", "added")):
            dc.step(self.P, self.rec(), 101.0, Runner(), self.add)
        self.assertEqual(self.shape(), [("U1", "scout-source", "blog", "added")])
        self.assertEqual(list((self.d / "events").glob("*.json")), [])

    def test_busy_event_older_than_the_retry_window_is_dropped(self):
        old = dict(self.SRC, ts=int((time.time() - dc.EVENT_RETRY_S - 5) * 1000))
        (self.d / "events").mkdir(exist_ok=True)
        (self.d / "events" / "5-a.json").write_text(json.dumps(old))
        with mock.patch.object(dc.scout_sources, "discord_request", side_effect=dc.scout_sources.Busy()):
            dc.step(self.P, self.rec(), 100.0, Runner(), self.add)
        self.assertEqual(self.shape(), [("U1", "scout-source", "source: https://a.example/feed", "busy")])
        self.assertEqual(list((self.d / "events").glob("*.json")), [])

    def test_a_failing_handler_never_breaks_the_step(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.run_ev(self.SRC, discord_request=RuntimeError("boom"))
        self.assertIn("discord_controls: scout source failed: RuntimeError: boom", err.getvalue())
        self.assertEqual(self.shape(), [("U1", "scout-source", "source: https://a.example/feed", "error")])
        self.assertEqual(list((self.d / "events").glob("*.json")), [])


class ScoutSourceEndToEndTest(Base):
    """Bridge event files -> consume_events -> the real scout_sources, in temp dirs: a /source prompt, then the check mark.
    No network: the resolver and the fetcher are fakes, and a REST call to Discord fails the test."""
    P = "agent-board"
    URL = "https://github.com/anthropics/claude-code"

    def setUp(self):
        super().setUp()
        ss, sf = dc.scout_sources, dc.scout_sources.scout_fetch
        self.ss = ss
        self.d = tc_env.discord_dir(self.P)
        self.d.mkdir(parents=True)
        (self.d / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))
        self.fetched = []

        def fetch(src, state, installed_version=None):
            self.fetched.append(src["name"])
            return [{"title": f"v{i}", "url": "https://e.example/"} for i in range(1, 6)], {}

        def no_rest(*a, **k):
            raise AssertionError("no Discord REST call outside #scout")
        for target, name, value in ((os.environ, None, {"TC_SCOUT_DIR": self.tmp.name + "/scout"}), (ss, "_resolve", lambda host: ["93.184.215.14"]),
                                    (sf, "fetch", fetch), (sf, "post_message", no_rest), (sf, "edit_message", no_rest), (sf, "get", no_rest)):
            p = mock.patch.dict(target, value) if name is None else mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def put(self, n, ev):
        self.event(f"{n}-a.json", dict(ev, ts=n))
        dc.step(self.P, self.rec(), 100.0 + n, Runner(), self.add)

    def names(self):
        return [s["name"] for s in self.ss.load()["sources"]]

    def test_slash_prompt_then_checkmark_adds_once_and_fetches_once(self):
        self.put(1, {"type": "source", "via": "slash", "url": self.URL, "name": "cc", "iid": "I1", "message_id": "777", "channel_id": "555", "user": "U1"})
        self.assertEqual(json.loads((self.d / "scout-prompts.json").read_text()), {"777": "555"})
        self.assertNotIn("cc", self.names())
        react = {"type": "react", "emoji": "✅", "message_id": "777", "channel_id": "555", "scout": True, "user": "U1"}
        self.put(2, dict(react, user="X"))   # not in allowFrom
        self.assertEqual((self.names().count("cc"), self.fetched), (0, []))
        self.put(3, react)
        self.put(4, react)   # a second check mark
        self.assertEqual((self.names().count("cc"), self.fetched), (1, ["cc"]))
        self.assertEqual(json.loads((self.d / "scout-prompts.json").read_text()), {})
        row = [s for s in self.ss.load()["sources"] if s["name"] == "cc"][0]
        self.assertEqual((row["kind"], row["url"]), ("github_releases", "https://api.github.com/repos/anthropics/claude-code/releases"))
        self.assertEqual(self.ops(), [
            {"op": "ireply", "iid": "I1", "content": "```\ncc · github_releases · https://api.github.com/repos/anthropics/claude-code/releases\n```\nreact ✅ to add"},
            {"op": "edit", "key": "scout-src:777", "text": "```\nadded: cc (github_releases)\nv1\nv2\nv3\n```"}])
        self.assertEqual([(a["user"], a["action"], a["target"], a["result"]) for a in self.audit()], [
            ("U1", "scout-source", self.URL, "prompted"), ("X", "scout-source", "777", "rejected"),
            ("U1", "scout-source", "cc", "added"), ("U1", "scout-source", "777", "gone")])
        self.assertEqual(self.lines, [])


class ProjectBotLeadGauthTest(Base):
    """/lead restart|handoff and /gauth arrive as slash events in a project bot's dir: they reach the same runner and spawn
    seam the ops consumer uses (nothing here restarts a lead or starts gcloud)."""
    def setUp(self):
        super().setUp()
        import discord_ops
        self.discord_ops = discord_ops
        self.runs = []

        class FG:
            GauthError = type("GauthError", (Exception,), {})
            calls = []

            def load_config(self, p):
                self.calls.append(("load_config", p))
                return {}

            def status(self, p):
                return "idle"

            def start(self, p):
                self.calls.append(("start", p))

            def read_url(self, p, tmux=None, timeout=15):
                return "https://accounts.google.com/x"

            def close(self, p):
                self.calls.append(("close", p))

        self.fg = FG()
        FG.calls = []
        for patcher in (mock.patch.object(discord_ops, "gauth", self.fg),
                        mock.patch.object(discord_ops, "_pending_update", lambda *a, **k: None),
                        mock.patch.object(discord_ops, "_pending_load", lambda: {})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def lead_run(self, argv):
        self.runs.append(argv)
        return "restarted p: pane %5"

    def slash(self, name="1.json", **ev):
        self.event(name, {"type": "slash", "user": "U1", "iid": "I1", "ts": 1, "project": "p", **ev})

    def test_lead_restart_reaches_the_lead_runner(self):
        self.slash(command="lead", action="restart")
        dc.step("p", self.rec(), 100.0, Runner(), self.add, lead_run=self.lead_run, spawn=lambda f: f())
        self.assertEqual(self.runs, [[str(dc.BIN / "tmux-ctl"), "lead-restart", "p", "--resume"]])
        self.assertEqual([o["content"] for o in self.ops() if o["op"] == "ireply"], ["restarted p: pane %5"])
        self.assertEqual((self.audit()[-1]["target"], self.audit()[-1]["result"]), ("p:lead:restart", "restarted"))

    def test_lead_falls_back_to_run_like_the_ops_consumer(self):
        self.slash(command="lead", action="restart")
        r = Runner(approve="restarted p")
        dc.step("p", self.rec(), 100.0, r, self.add, spawn=lambda f: f())
        self.assertEqual(r.calls, [[str(dc.BIN / "tmux-ctl"), "lead-restart", "p", "--resume"]])
        self.assertNotIn("not available here", [o.get("content") for o in self.ops()])

    def test_event_for_another_project_targets_that_project(self):
        tc_env.discord_dir("q").mkdir(parents=True)
        self.ops_allow(["U1"])
        self.slash(command="lead", action="restart", project="q")
        self.slash("2.json", command="gauth", project="q")
        spawned = []
        dc.step("p", self.rec(), 100.0, Runner(), self.add, lead_run=self.lead_run, spawn=lambda f: (spawned.append(f), f()))
        self.assertEqual(self.runs[0][2:], ["q", "--resume"])
        self.assertIn(("load_config", "q"), self.fg.calls)
        self.assertNotIn(("load_config", "p"), self.fg.calls)

    def ops_allow(self, users):
        od = tc_env.ops_dir()
        od.mkdir(parents=True, exist_ok=True)
        if users is not None:
            (od / "access.json").write_text(json.dumps({"allowFrom": users}))

    def test_another_project_needs_the_user_in_the_ops_allowlist(self):
        tc_env.discord_dir("q").mkdir(parents=True)
        for users in (["U2"], None):   # a different list, then no ops access.json: both refuse
            self.slash("1.json", command="lead", action="restart", project="q")
            self.slash("2.json", command="gauth", project="q")
            self.slash("3.json", command="pause", project="q")
            self.ops_allow(users)
            spawned = []
            dc.step("p", self.rec(), 100.0, Runner(), self.add, lead_run=self.lead_run, spawn=spawned.append)
            self.assertEqual((self.runs, spawned, self.lines, self.fg.calls), ([], [], [], []))
        self.assertEqual([a["result"] for a in self.audit()], ["rejected"] * 6)
        self.assertEqual(list((self.d / "events").glob("*.json")), [])

    def test_own_project_does_not_need_the_ops_allowlist(self):
        self.slash(command="lead", action="restart")
        dc.step("p", self.rec(), 100.0, Runner(), self.add, lead_run=self.lead_run, spawn=lambda f: f())
        self.assertEqual(len(self.runs), 1)

    def test_gauth_slash_reaches_the_spawn_seam(self):
        self.slash(command="gauth")
        spawned = []
        dc.step("p", self.rec(), 100.0, Runner(), self.add, lead_run=self.lead_run, spawn=spawned.append)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(self.fg.calls, [("load_config", "p")])
        spawned[0]()
        self.assertIn(("start", "p"), self.fg.calls)


if __name__ == "__main__":
    unittest.main()
