"""discord_controls: prompt watch, perm and react consumption. Scratch TC_STATE; the runner and add_line are fakes.
The SHOW text below is the real `_ap_prompt` output (T: second B: line, P: lines) on tools/tests/fixtures/approve/bash-multiline.txt."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_controls as dc  # noqa: E402
import tc_env  # noqa: E402

SHOW = "T:Bash command\nP:│ echo a\nP:│ ──── echo probe\n"
LINES = ["│ echo a", "│ ──── echo probe"]
KEY = "%5:" + hashlib.sha1("\n".join(LINES).encode()).hexdigest()
SHOW2 = "T:Create file\nP:notes.txt\n"
KEY2 = "%5:" + hashlib.sha1(b"notes.txt").hexdigest()
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

    def seed(self, key=KEY, window="w1", lines=LINES):
        (self.d / "controls-state.json").write_text(json.dumps({"prompts": {key: {"window": window, "pane": "%5", "tool": "Bash command", "lines": lines, "ts": 1.0}}}))


class ScanTest(Base):
    def test_posts_once(self):  # mutation: skip the "key already stored" check -> two ops
        r = Runner({"w1": SHOW})
        self.step(r, self.rec("w1"))
        self.step(r, self.rec("w1"))
        self.assertEqual(self.ops(), [{"op": "prompt", "key": KEY, "window": "w1", "tool": "Bash command", "lines": LINES, "tier": "decision", "mention_user": True}])
        self.assertEqual(r.calls[0], [TC, "approve", "w1", "show"])
        self.assertEqual(self.state()["prompts"][KEY]["lines"], LINES)

    def test_claude_window_never_shown(self):
        r = Runner({"claude": SHOW})
        self.step(r, self.rec("claude"))
        self.assertEqual(r.calls, [])
        self.assertEqual(self.ops(), [])

    def test_show_error_posts_nothing(self):
        r = Runner({"w1": "approve: ambiguous prompt in w1"})
        self.step(r, self.rec("w1"))
        self.assertEqual(self.ops(), [])

    def test_gone_prompt_reshown_then_answered_elsewhere(self):
        self.seed()
        r = Runner({})  # no prompt
        self.step(r, self.rec())
        self.assertEqual(r.calls, [[TC, "approve", "w1", "show"]])
        self.assertEqual(self.ops(), [{"op": "edit", "key": KEY, "text": "🔐 w1 wants to run Bash command: answered elsewhere"}])
        self.assertEqual(self.state()["prompts"], {})

    def test_flicker_keeps_key_when_same_prompt_shows(self):  # mutation: drop without re-show
        self.seed()
        r = Runner({"w1": SHOW})
        self.step(r, self.rec())
        self.assertEqual(self.ops(), [])
        self.assertIn(KEY, self.state()["prompts"])

    def test_different_key_in_needs_you_window_edits_old_and_posts_new(self):
        self.seed()
        r = Runner({"w1": SHOW2})
        self.step(r, self.rec("w1"))
        ops = self.ops()
        self.assertEqual([o["op"] for o in ops], ["edit", "prompt"] if ops[0]["op"] == "edit" else ["prompt", "edit"])
        self.assertEqual(list(self.state()["prompts"]), [KEY2])
        self.assertEqual(r.calls, [[TC, "approve", "w1", "show"]])

    def test_other_show_error_keeps_key(self):
        self.seed()
        self.step(Runner({"w1": "approve: ambiguous prompt in w1"}), self.rec())
        self.assertIn(KEY, self.state()["prompts"])
        self.assertEqual(self.ops(), [])


class TimeoutTest(Base):
    """run_script(timeout=20) raises subprocess.TimeoutExpired, which is not a RuntimeError: a hung show is an 'error', never an abort."""
    class Hung(Runner):
        def __call__(self, argv):
            if argv[3] == "show" and argv[2] in self.hang:
                self.calls.append(list(argv))
                raise subprocess.TimeoutExpired(argv, 20)
            return super().__call__(argv)

    def hung(self, shows, hang):
        r = self.Hung(shows)
        r.hang = hang
        return r

    def react(self, emoji, name="1-a.json"):
        self.event(name, {"type": "react", "emoji": emoji, "message_id": "m", "excerpt": "hi", "user": "U1", "ts": 1})

    def test_hung_show_keeps_key_and_scan_continues(self):  # mutation: except RuntimeError only -> w2 never posted
        self.seed()
        r = self.hung({"w2": SHOW2}, hang={"w1"})
        self.step(r, self.rec("w1", "w2"))
        self.assertIn(KEY, self.state()["prompts"])
        self.assertEqual([o["op"] for o in self.ops()], ["prompt"])
        self.assertEqual(self.ops()[0]["window"], "w2")

    def test_hung_show_still_consumes_react(self):
        self.seed()
        self.react("✅")
        lines = []
        dc.step("p", self.rec("w1"), 100.0, self.hung({}, hang={"w1"}), lambda s, t: lines.append((s, t)))
        self.assertEqual(lines, [("p", '[Discord] ✅ yes to your message "hi"')])
        self.assertIn(KEY, self.state()["prompts"])
        self.assertEqual([a["result"] for a in self.audit()], ["queued"])


class ScanFailureTest(Base):
    def test_scan_exception_still_consumes_events_and_saves_state(self):
        self.event("1-a.json", {"type": "react", "emoji": "🛑", "message_id": "m", "excerpt": "", "user": "U1", "ts": 1})
        lines = []
        with mock.patch.object(dc, "scan_prompts", side_effect=RuntimeError("boom")), mock.patch("sys.stderr") as err:
            dc.step("p", self.rec("w1"), 100.0, Runner(), lambda s, t: lines.append((s, t)))
        self.assertEqual(lines, [("p", "[Discord] 🛑 pause the queue")])
        self.assertTrue((self.d / "controls-state.json").exists())
        self.assertIn("discord_controls: scan failed (p): RuntimeError: boom", "".join(c[0][0] for c in err.write.call_args_list))


class PermTest(Base):
    def perm(self, choice="allow", user="U1", key=KEY, name="1-a.json"):
        self.event(name, {"type": "perm", "key": key, "choice": choice, "user": user, "message_id": "m", "ts": 1})

    def test_allow(self):
        self.seed()
        self.perm()
        r = Runner({"w1": SHOW})
        self.step(r)
        self.assertEqual(r.presses, [[TC, "approve", "w1", "once", "--expect", "\n".join(LINES)]])
        self.assertEqual(self.ops()[-1], {"op": "edit", "key": KEY, "text": "🔐 w1 wants to run Bash command: ✅ allowed by you"})
        self.assertEqual(self.state()["prompts"], {})
        self.assertEqual(self.audit()[-1]["result"], "allowed")
        self.assertEqual(list((self.d / "events").glob("*.json")), [])

    def test_deny(self):
        self.seed()
        self.perm("deny")
        r = Runner({"w1": SHOW})
        self.step(r)
        self.assertEqual(r.presses[0][3], "deny")
        self.assertEqual(self.ops()[-1]["text"], "🔐 w1 wants to run Bash command: ⛔ denied")
        self.assertEqual(self.audit()[-1], {**self.audit()[-1], "action": "perm", "target": KEY, "result": "denied", "user": "U1"})

    def test_changed_prompt_not_pressed_no_retry(self):
        self.seed()
        self.perm()
        r = Runner({"w1": SHOW}, approve=RuntimeError("approve: the prompt in w1 changed\nwas: x\nnow: y"))
        self.step(r)
        self.assertEqual(len(r.presses), 1)
        self.assertEqual(self.ops()[-1]["text"], "🔐 w1 wants to run Bash command: ⚠️ not pressed: approve: the prompt in w1 changed")
        self.assertEqual(self.state()["prompts"], {})
        self.assertEqual(self.audit()[-1]["result"], "not pressed")
        self.step(r)
        self.assertEqual(len(r.presses), 1)

    def test_empty_error_text(self):
        self.seed()
        self.perm()
        self.step(Runner({"w1": SHOW}, approve=RuntimeError("")))
        self.assertEqual(self.ops()[-1]["text"], "🔐 w1 wants to run Bash command: ⚠️ not pressed: exit error")

    def test_unknown_key(self):
        self.perm(key="%9:abc")
        r = Runner({"w1": SHOW})
        self.step(r)
        self.assertEqual(r.presses, [])
        self.assertEqual(self.ops(), [])  # an unknown key writes no edit
        self.assertEqual(self.audit()[-1]["result"], "unknown")

    def test_double_tap_keeps_the_real_outcome(self):  # mutation: edit "not pressed" for an unknown key -> last edit is overwritten
        self.seed()
        self.perm("allow", name="1-a.json")
        self.perm("deny", name="2-b.json")
        r = Runner({"w1": SHOW})
        self.step(r)
        self.assertEqual(len(r.presses), 1)
        edits = [o for o in self.ops() if o["op"] == "edit"]
        self.assertEqual(edits, [{"op": "edit", "key": KEY, "text": "🔐 w1 wants to run Bash command: ✅ allowed by you"}])
        self.assertEqual([a["result"] for a in self.audit() if a["action"] == "perm"], ["allowed", "unknown"])

    def test_rejected_user(self):  # mutation: skip allowlist -> runner called
        self.seed()
        self.perm(user="X")
        r = Runner({"w1": SHOW})
        self.step(r)
        self.assertEqual(r.presses, [])
        self.assertEqual(self.ops(), [])
        self.assertEqual(self.audit()[-1]["result"], "rejected")
        self.assertIn(KEY, self.state()["prompts"])
        self.assertEqual(list((self.d / "events").glob("*.json")), [])

    def test_real_fixture_key_roundtrip(self):
        r = Runner({"w1": SHOW})
        self.step(r, self.rec("w1"))
        self.perm()
        self.step(r, self.rec("w1"))
        self.assertEqual(r.presses[-1][-1], "│ echo a\n│ ──── echo probe")


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


if __name__ == "__main__":
    unittest.main()
