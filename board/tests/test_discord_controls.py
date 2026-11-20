"""discord_controls: react, click and reply consumption (the dialog routes are tested in test_discord_dialogs). Scratch TC_STATE; the runner and add_line are fakes.
"""
import json
import os
import sys
import tempfile
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


class ProjectBotLeadGauthTest(Base):
    """/lead restart|handoff and /gauth arrive as slash events in a project bot's dir: they reach the same runner and spawn
    seam the ops consumer uses (nothing here restarts a lead or starts gcloud)."""
    def setUp(self):
        super().setUp()
        import discord_ops
        self.ops = discord_ops
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

    def slash(self, **ev):
        self.event("1.json", {"type": "slash", "user": "U1", "iid": "I1", "ts": 1, "project": "p", **ev})

    def test_lead_restart_reaches_the_lead_runner(self):   # mutation: step/consume_events drop lead_run -> "not available here"
        self.slash(command="lead", action="restart")
        dc.step("p", self.rec(), 100.0, Runner(), self.add, lead_run=self.lead_run, spawn=lambda f: f())
        self.assertEqual(self.runs, [[str(dc.BIN / "tmux-ctl"), "lead-restart", "p", "--resume"]])
        self.assertEqual([o["content"] for o in self.ops_out() if o["op"] == "ireply"], ["restarted p: pane %5"])
        self.assertEqual((self.audit()[-1]["target"], self.audit()[-1]["result"]), ("p:lead:restart", "restarted"))

    def test_lead_falls_back_to_run_like_the_ops_consumer(self):
        self.slash(command="lead", action="restart")
        r = Runner(approve="restarted p")
        dc.step("p", self.rec(), 100.0, r, self.add, spawn=lambda f: f())
        self.assertEqual(r.calls, [[str(dc.BIN / "tmux-ctl"), "lead-restart", "p", "--resume"]])
        self.assertNotIn("not available here", [o.get("content") for o in self.ops_out()])

    def test_gauth_slash_reaches_the_spawn_seam(self):   # mutation: spawn not passed -> a real thread, start() may run after the assert
        self.slash(command="gauth")
        spawned = []
        dc.step("p", self.rec(), 100.0, Runner(), self.add, lead_run=self.lead_run, spawn=spawned.append)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(self.fg.calls, [("load_config", "p")])
        spawned[0]()
        self.assertIn(("start", "p"), self.fg.calls)

    def ops_out(self):
        return self.ops_list()

    def ops_list(self):
        return Base.ops(self)


if __name__ == "__main__":
    unittest.main()
