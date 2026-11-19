"""discord_dialogs.scan: one `dialog` op per distinct dialog, its buttons, routing and lifecycle. Scratch TC_STATE; the runner is a fake
that answers `tmux-ctl dialog <pane> show` with the oracle of a real captured screen (tools/tests/fixtures/dialogs/expect/*.json) plus
the fixture rows `show` returns as `lines` (the FROM/TO rows of tools/tests/test_ctl_dialog_show.zsh). RealShowTest runs the real
`tmux-ctl dialog … show` once on a scratch tmux server and checks the fake's `lines` against it."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_dialogs as dd  # noqa: E402
import paneclass  # noqa: E402
import tc_env  # noqa: E402

FX = HERE.parent / "tools" / "tests" / "fixtures"
TC = str(HERE.parent / "bin" / "tmux-ctl")
NONE = "dialog: none in %12"
ANSWERED = "answered at the terminal"


def rows(path, a, b):
    """Fixture rows a..b (1-based) the way `show` gives `lines`: trailing blanks dropped, empty rows dropped."""
    return [r for r in (l.rstrip() for l in path.read_text(encoding="utf-8").split("\n")[a - 1:b]) if r]


def fixture(name, a, b):
    d = json.loads((FX / "dialogs" / "expect" / f"{name}.json").read_text(encoding="utf-8"))
    d["lines"] = rows(FX / "dialogs" / f"{name}.txt", a, b)
    return d


SINGLE = fixture("question-single", 9, 19)
MULTI = fixture("question-multi", 28, 41)
PLAN = fixture("plan", 6, 48)
TRUST = fixture("trust", 3, 15)
PERM = {"kind": "permission", "question": "Do you want to proceed?", "multi": False, "other": False,
        "options": [{"n": 1, "label": "Yes", "permanent": False},
                    {"n": 2, "label": "Yes, and don’t ask again for: git config *", "permanent": True},
                    {"n": 3, "label": "Yes, and switch to auto mode · auto mode handles these prompts for you", "permanent": True},
                    {"n": 4, "label": "No", "permanent": False}],
        "lines": rows(FX / "approve" / "bash-git.txt", 29, 41)}


def key_of(pane, lines):
    return f"p{pane.lstrip('%')}-{hashlib.sha1(chr(10).join(lines).encode('utf-8')).hexdigest()[:16]}"


def pane(pid="%12", status="waiting", kind="claude", preview=()):
    return {"id": pid, "kind": kind, "status": status, "discord": False, "preview": list(preview)}


def sess(name="proj", win="win", panes=None):
    return {"name": name, "windows": [{"name": win, "worker": False, "teammate": False, "panes": panes if panes is not None else [pane()]}]}


class Runner:
    """shows: pane id -> dict (printed as JSON), str (stdout as is when it starts with `{` or `not`, else raised as the error text), or an Exception."""

    def __init__(self, shows=None, delay=0.0):
        self.calls, self.shows, self.delay = [], shows if shows is not None else {}, delay

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.delay:
            time.sleep(self.delay)
        v = self.shows.get(argv[2], f"dialog: none in {argv[2]}")
        if isinstance(v, Exception):
            raise v
        if isinstance(v, dict):
            return json.dumps(v, ensure_ascii=False)
        if v.startswith("dialog:"):
            raise RuntimeError(v)
        return v


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.d = tc_env.discord_dir("proj")
        self.channel("proj")

    def channel(self, project):
        d = tc_env.discord_dir(project)
        d.mkdir(parents=True, exist_ok=True)
        (d / "bridge.json").write_text(json.dumps({"channel": "123"}))

    def ops_on(self):
        tc_env.ops_dir().mkdir(parents=True, exist_ok=True)
        (tc_env.ops_dir() / "bridge.json").write_text(json.dumps({"command_center": "1", "approvals": "2"}))

    def ops(self, d=None):
        box = (d or self.d) / "outbox"
        return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(box.glob("*.json"))] if box.exists() else []

    def state(self):
        p = tc_env.agent_base() / "dialogs" / "state.json"
        return json.loads(p.read_text(encoding="utf-8"))["dialogs"] if p.exists() else {}

    def buttons(self, op):
        return [b for r in op["rows"] for b in r]


class ShapeTest(Base):
    def test_single_choice_posts_one_dialog_op(self):
        r = Runner({"%12": SINGLE})
        dd.scan([sess()], 100.0, r)
        key = key_of("%12", SINGLE["lines"])
        self.assertRegex(key, r"^p12-[0-9a-f]{16}$")
        ops = self.ops()
        self.assertEqual([o["op"] for o in ops], ["dialog"])
        op = ops[0]
        self.assertEqual(op["key"], key)
        self.assertTrue(op["text"].startswith("❓ proj · win: Which fruit?\n```\n"), op["text"])
        for l in SINGLE["lines"]:
            self.assertIn(l, op["text"])
        self.assertIs(op["mention_user"], True)
        self.assertEqual(self.buttons(op), [
            {"label": "1. Apple", "style": 2, "custom_id": f"ab:dlg:{key}:1"},
            {"label": "2. Pear", "style": 2, "custom_id": f"ab:dlg:{key}:2"},
            {"label": "3. Type something.", "style": 2, "custom_id": f"ab:dlg:{key}:3"},
            {"label": "4. Chat about this", "style": 2, "custom_id": f"ab:dlg:{key}:4"},
            {"label": "Reply", "style": 1, "custom_id": f"ab:dlg:{key}:reply"}])
        self.assertEqual(r.calls, [[TC, "dialog", "%12", "show"]])

    def test_state_record_holds_pane_window_project_dir_show_and_header(self):
        dd.scan([sess()], 100.0, Runner({"%12": SINGLE}))
        rec = self.state()[key_of("%12", SINGLE["lines"])]
        self.assertEqual({k: rec[k] for k in ("pane", "window", "project", "dir", "show", "header", "kind")},
                         {"pane": "%12", "window": "win", "project": "proj", "dir": str(self.d), "show": SINGLE,
                          "header": "❓ proj · win: Which fruit?", "kind": "question"})

    def test_second_scan_of_the_same_screen_writes_nothing(self):
        # mutation: drop the `key in dialogs` check in _post (post every tick) -> two dialog ops
        r = Runner({"%12": SINGLE})
        dd.scan([sess()], 100.0, r)
        dd.scan([sess()], 110.0, r)
        self.assertEqual([o["op"] for o in self.ops()], ["dialog"])
        self.assertEqual(list(self.state()), [key_of("%12", SINGLE["lines"])])

    def test_permission_header_and_red_permanent_rows(self):
        dd.scan([sess()], 100.0, Runner({"%12": PERM}))
        op = self.ops()[0]
        self.assertTrue(op["text"].startswith("🔐 proj · win: Do you want to proceed?\n"), op["text"])
        self.assertEqual([b["style"] for b in self.buttons(op)], [2, 4, 4, 2])
        self.assertEqual(self.buttons(op)[1]["label"], "2. Yes, and don’t ask again for: git config *")
        self.assertEqual(self.buttons(op)[2]["label"], "3. Yes, and switch to auto mode · auto mode handles these prompts for you"[:80])
        self.assertTrue(all(len(b["label"]) <= 80 for b in self.buttons(op)))

    def test_plan_dialog_has_a_red_auto_mode_row_and_reply(self):
        dd.scan([sess()], 100.0, Runner({"%12": PLAN}))
        op = self.ops()[0]
        self.assertTrue(op["text"].startswith("❓ proj · win: Claude has written up a plan and is ready to execute. Would you like to proceed?\n"))
        self.assertEqual([(b["label"], b["style"]) for b in self.buttons(op)],
                         [("1. Yes, and use auto mode", 4), ("2. Yes, manually approve edits", 2), ("3. Tell Claude what to change", 2), ("Reply", 1)])

    def test_multi_select_writes_toggles_submit_and_reply(self):
        dd.scan([sess()], 100.0, Runner({"%12": MULTI}))
        key = key_of("%12", MULTI["lines"])
        self.assertEqual([(b["label"], b["style"], b["custom_id"]) for b in self.buttons(self.ops()[0])], [
            ("1. Apple", 2, f"ab:dlg:{key}:t1"), ("2. Pear", 2, f"ab:dlg:{key}:t2"), ("3. Plum", 2, f"ab:dlg:{key}:t3"),
            ("4. Type something", 2, f"ab:dlg:{key}:t4"), ("5. Chat about this", 2, f"ab:dlg:{key}:t5"),
            ("Submit", 1, f"ab:dlg:{key}:submit"), ("Reply", 1, f"ab:dlg:{key}:reply")])

    def test_no_reply_button_without_other(self):
        # mutation: add Reply whatever `other` says -> a third button
        dd.scan([sess()], 100.0, Runner({"%12": TRUST}))
        self.assertEqual([b["label"] for b in self.buttons(self.ops()[0])], ["1. No, exit", "2. Yes, I trust this folder"])

    def test_multi_select_without_other_has_submit_and_no_reply(self):
        show = dict(MULTI, other=False)
        dd.scan([sess()], 100.0, Runner({"%12": show}))
        self.assertEqual([b["custom_id"].rsplit(":", 1)[1] for b in self.buttons(self.ops()[0])], ["t1", "t2", "t3", "t4", "t5", "submit"])

    def test_23_options_give_20_buttons_and_the_more_line(self):
        show = dict(SINGLE, options=[{"n": n, "label": f"opt {n}", "permanent": False} for n in range(1, 24)])
        dd.scan([sess()], 100.0, Runner({"%12": show}))
        op = self.ops()[0]
        opts = [b for b in self.buttons(op) if not b["custom_id"].endswith(":reply")]
        self.assertEqual([b["label"] for b in opts], [f"{n}. opt {n}" for n in range(1, 21)])
        self.assertEqual(op["text"].split("\n")[-1], "… 3 more options: answer at the terminal")
        self.assertEqual([len(r) for r in op["rows"]], [5, 5, 5, 5, 1])   # the outbox accepts at most 5 rows of 5
        self.assertTrue(self.buttons(op)[-1]["custom_id"].endswith(":reply"))

    def test_20_options_have_no_more_line(self):
        # mutation: always add the more line -> it shows `… 0 more options`
        show = dict(SINGLE, options=[{"n": n, "label": f"opt {n}", "permanent": False} for n in range(1, 21)])
        dd.scan([sess()], 100.0, Runner({"%12": show}))
        self.assertEqual(self.ops()[0]["text"].count("more options"), 0)

    def test_a_body_over_1500_characters_is_cut(self):
        lines = [f"line {n:03d} " + "x" * 60 for n in range(60)]   # 60 * 69 characters
        dd.scan([sess()], 100.0, Runner({"%12": dict(SINGLE, lines=lines)}))
        op = self.ops()[0]
        body = op["text"].split("```")[1].strip("\n")
        self.assertLessEqual(len(body), 1500 + len("\n… (99 more lines)"))
        self.assertIn(lines[0], body)
        self.assertNotIn(lines[-1], body)
        shown = sum(1 for l in lines if l in body)
        self.assertEqual(body.split("\n")[-1], f"… ({60 - shown} more lines)")
        self.assertLessEqual(len("\n".join(lines[:shown])), 1500)
        self.assertGreater(len("\n".join(lines[:shown + 1])), 1500)
        self.assertEqual(op["key"], key_of("%12", lines))   # the key is of all the lines, not of the cut body
        self.assertEqual(self.state()[op["key"]]["show"]["lines"], lines)   # --expect needs every line

    def test_one_line_over_1500_characters_is_cut_inside_the_line(self):
        dd.scan([sess()], 100.0, Runner({"%12": dict(SINGLE, lines=["y" * 4000])}))
        text = self.ops()[0]["text"]
        self.assertLessEqual(len(text), 2000)
        self.assertIn("y" * 1500, text)
        self.assertNotIn("y" * 1501, text)

    def test_a_code_fence_in_the_dialog_does_not_close_the_block(self):
        dd.scan([sess()], 100.0, Runner({"%12": dict(SINGLE, lines=["a ``` b", "c"])}))
        self.assertEqual(self.ops()[0]["text"].count("```"), 2)

    def test_a_long_question_keeps_the_text_under_2000(self):
        show = dict(SINGLE, question="q" * 3000, lines=["z" * 70] * 30)
        dd.scan([sess()], 100.0, Runner({"%12": show}))
        op = self.ops()[0]
        self.assertLessEqual(len(op["text"]), 2000)
        self.assertNotIn("\n", self.state()[op["key"]]["header"])


class RoutingTest(Base):
    def test_only_waiting_claude_panes_are_shown(self):
        # mutation: drop the status check in _waiting -> the ready and the working claude panes are shown and get a message
        r = Runner({"%1": SINGLE, "%2": SINGLE, "%3": SINGLE})
        dd.scan([sess(panes=[pane("%1", status="ready"), pane("%2", kind="shell", status="idle"), pane("%3", status="working"),
                             pane("%4", kind="program", status="waiting")])], 100.0, r)
        self.assertEqual(r.calls, [])
        self.assertEqual(self.ops(), [])

    def test_project_with_a_channel_posts_to_its_own_dir(self):
        self.ops_on()
        dd.scan([sess()], 100.0, Runner({"%12": SINGLE}))
        self.assertEqual(len(self.ops()), 1)
        self.assertEqual(self.ops(tc_env.ops_dir()), [])

    def test_session_without_a_channel_posts_to_the_ops_dir(self):
        self.ops_on()
        dd.scan([sess(name="peer")], 100.0, Runner({"%12": SINGLE}))
        ops = self.ops(tc_env.ops_dir())
        self.assertEqual([o["op"] for o in ops], ["dialog"])
        self.assertTrue(ops[0]["text"].startswith("❓ peer · win: Which fruit?"))
        self.assertEqual(self.state()[ops[0]["key"]]["dir"], str(tc_env.ops_dir()))
        self.assertFalse((tc_env.discord_dir("peer") / "outbox").exists())

    def test_no_channel_and_no_ops_posts_nothing_and_keeps_no_state(self):
        # mutation: fall back to tc_env.discord_dir(project) when nothing is configured -> an outbox file and a state key appear
        dd.scan([sess(name="peer")], 100.0, Runner({"%12": SINGLE}))
        self.assertEqual(self.state(), {})
        self.assertEqual([str(p) for p in Path(self.tmp.name).rglob("outbox/*.json")], [])

    def test_half_configured_ops_is_not_configured(self):
        tc_env.ops_dir().mkdir(parents=True)
        (tc_env.ops_dir() / "bridge.json").write_text(json.dumps({"command_center": "1"}))
        dd.scan([sess(name="peer")], 100.0, Runner({"%12": SINGLE}))
        self.assertEqual(self.ops(tc_env.ops_dir()), [])

    def test_every_session_is_covered(self):
        self.channel("other")
        r = Runner({"%12": SINGLE, "%7": PERM})
        dd.scan([sess(), sess(name="other", win="w2", panes=[pane("%7")])], 100.0, r)
        self.assertEqual([o["key"] for o in self.ops()], [key_of("%12", SINGLE["lines"])])
        self.assertEqual([o["key"] for o in self.ops(tc_env.discord_dir("other"))], [key_of("%7", PERM["lines"])])

    def test_same_dialog_text_in_two_panes_is_two_messages(self):
        dd.scan([sess(panes=[pane("%1"), pane("%2")])], 100.0, Runner({"%1": SINGLE, "%2": SINGLE}))
        self.assertEqual([o["key"][:3] for o in self.ops()], ["p1-", "p2-"])


class LifecycleTest(Base):
    def posted(self, show=SINGLE, sessions=None):
        dd.scan(sessions or [sess()], 100.0, Runner({"%12": show}))
        key = key_of("%12", show["lines"])
        self.assertIn(key, self.state())
        return key

    def assert_answered(self, key, header="❓ proj · win: Which fruit?"):
        edits = [o for o in self.ops() if o["op"] == "edit"]
        self.assertEqual(edits, [{"op": "edit", "key": key, "text": f"{header}\n{ANSWERED}"}])
        self.assertNotIn(key, self.state())

    def test_dialog_gone_while_the_pane_is_ready_is_answered_at_the_terminal(self):
        key = self.posted()
        dd.scan([sess(panes=[pane(status="ready")])], 110.0, Runner({}))
        self.assert_answered(key)
        self.assertEqual(self.state(), {})

    def test_dialog_changed_edits_the_old_message_and_posts_the_new_one(self):
        key = self.posted()
        dd.scan([sess()], 110.0, Runner({"%12": PERM}))
        self.assert_answered(key)
        self.assertEqual([o["op"] for o in self.ops()], ["dialog", "edit", "dialog"])
        self.assertEqual(list(self.state()), [key_of("%12", PERM["lines"])])

    def test_pane_gone_is_answered_at_the_terminal(self):
        key = self.posted()
        r = Runner({})
        dd.scan([], 110.0, r)
        self.assert_answered(key)
        self.assertEqual(r.calls, [])   # a pane that is not on the server is not shown

    def test_edit_goes_to_the_dir_the_message_was_posted_in(self):
        self.ops_on()
        dd.scan([sess(name="peer")], 100.0, Runner({"%12": SINGLE}))
        dd.scan([], 110.0, Runner({}))
        self.assertEqual([o["op"] for o in self.ops(tc_env.ops_dir())], ["dialog", "edit"])

    def test_show_error_keeps_the_key(self):
        # mutation: in _sweep treat ERROR like "no dialog" (drop the `got is ERROR` branch) -> an edit op, and the key is gone
        key = self.posted()
        for err in (RuntimeError("dialog: %12 is in copy mode"), subprocess.TimeoutExpired("tmux-ctl", 30), RuntimeError("exit 1")):
            dd.scan([sess()], 110.0, Runner({"%12": err}))
        dd.scan([sess()], 120.0, Runner({"%12": "not json"}))
        self.assertEqual([o["op"] for o in self.ops()], ["dialog"])
        self.assertEqual(list(self.state()), [key])

    def test_show_error_on_a_new_pane_posts_nothing(self):
        # mutation: treat any show failure as "no dialog" -> a raw `(dialog not parsed)` message
        dd.scan([sess(panes=[pane(preview=["some row"])])], 100.0, Runner({"%12": RuntimeError("dialog: %12 is in copy mode")}))
        self.assertEqual(self.ops(), [])
        self.assertEqual(self.state(), {})

    def test_known_dialog_still_on_screen_is_kept_when_the_pane_stops_classifying_as_waiting(self):
        # a tall prompt can fall out of the classifier's 12-row tail. mutation: sweep by "pane not waiting" without a show -> an edit op
        key = self.posted()
        r = Runner({"%12": SINGLE})
        dd.scan([sess(panes=[pane(status="ready")])], 110.0, r)
        self.assertEqual([o["op"] for o in self.ops()], ["dialog"])
        self.assertEqual(list(self.state()), [key])
        self.assertEqual(r.calls, [[TC, "dialog", "%12", "show"]])

    def test_one_failing_pane_never_stops_the_others(self):
        # mutation: let the show exception out of _show -> scan raises and %2 gets no message
        r = Runner({"%1": ValueError("boom"), "%2": SINGLE})
        dd.scan([sess(panes=[pane("%1"), pane("%2")])], 100.0, r)
        self.assertEqual([o["key"] for o in self.ops()], [key_of("%2", SINGLE["lines"])])

    def test_a_failed_outbox_write_does_not_stop_the_others_and_keeps_no_state(self):
        real = dd.discord_feed.outbox_write
        calls = []

        def flaky(d, op):
            calls.append(op["key"])
            if len(calls) == 1:
                raise OSError("disk full")
            return real(d, op)

        with mock.patch.object(dd.discord_feed, "outbox_write", flaky), mock.patch.object(sys, "stderr"):
            dd.scan([sess(panes=[pane("%1"), pane("%2")])], 100.0, Runner({"%1": SINGLE, "%2": SINGLE}))
        self.assertEqual(list(self.state()), [key_of("%2", SINGLE["lines"])])   # %1 is retried on the next tick
        dd.scan([sess(panes=[pane("%1"), pane("%2")])], 110.0, Runner({"%1": SINGLE, "%2": SINGLE}))
        self.assertEqual(sorted(o["key"] for o in self.ops()), sorted(key_of(p, SINGLE["lines"]) for p in ("%1", "%2")))

    def test_a_damaged_record_is_dropped_and_the_scan_goes_on(self):
        p = tc_env.agent_base() / "dialogs" / "state.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"dialogs": {"p1-0000000000000000": "x", "p2-0000000000000000": {"pane": "%2"}}}))
        dd.scan([sess()], 100.0, Runner({"%12": SINGLE}))
        self.assertEqual(list(self.state()), [key_of("%12", SINGLE["lines"])])
        self.assertEqual([o["op"] for o in self.ops()], ["dialog"])

    def test_corrupt_state_file_is_an_empty_state(self):
        p = tc_env.agent_base() / "dialogs" / "state.json"
        p.parent.mkdir(parents=True)
        p.write_text("{not json")
        dd.scan([sess()], 100.0, Runner({"%12": SINGLE}))
        self.assertEqual(len(self.ops()), 1)
        self.assertEqual(len(self.state()), 1)


class RawTest(Base):
    PREVIEW = ["  Some new screen", "  ❯ a row", "Enter to confirm · Esc to cancel"]

    def raw(self, preview=None, status="waiting"):
        return [sess(panes=[pane(preview=self.PREVIEW if preview is None else preview, status=status)])]

    def test_unparsed_waiting_pane_gets_the_raw_message_with_only_reply(self):
        dd.scan(self.raw(), 100.0, Runner({}))
        key = key_of("%12", self.PREVIEW)
        op = self.ops()[0]
        self.assertEqual(op["key"], key)
        self.assertEqual(op["text"], "❓ proj · win: (dialog not parsed)\n```\n" + "\n".join(self.PREVIEW) + "\n```")
        self.assertEqual(op["rows"], [[{"label": "Reply", "style": 1, "custom_id": f"ab:dlg:{key}:reply"}]])
        self.assertIs(op["mention_user"], True)
        rec = self.state()[key]
        self.assertEqual((rec["kind"], rec["show"]["kind"], rec["show"]["lines"], rec["pane"]), ("raw", "raw", self.PREVIEW, "%12"))

    def test_raw_message_is_posted_once(self):
        # mutation: drop the `key in dialogs` check in _post -> two dialog ops
        for now in (100.0, 110.0):
            dd.scan(self.raw(), now, Runner({}))
        self.assertEqual([o["op"] for o in self.ops()], ["dialog"])

    def test_raw_pane_that_stops_waiting_is_answered(self):
        dd.scan(self.raw(), 100.0, Runner({}))
        dd.scan(self.raw(status="ready"), 110.0, Runner({}))
        self.assertEqual(self.ops()[-1], {"op": "edit", "key": key_of("%12", self.PREVIEW), "text": f"❓ proj · win: (dialog not parsed)\n{ANSWERED}"})
        self.assertEqual(self.state(), {})

    def test_raw_pane_whose_show_errors_keeps_its_key(self):
        dd.scan(self.raw(), 100.0, Runner({}))
        dd.scan(self.raw(), 110.0, Runner({"%12": RuntimeError("dialog: %12 is in copy mode")}))
        self.assertEqual([o["op"] for o in self.ops()], ["dialog"])
        self.assertEqual(len(self.state()), 1)

    def test_raw_pane_that_now_parses_is_replaced_by_the_dialog(self):
        dd.scan(self.raw(), 100.0, Runner({}))
        dd.scan(self.raw(), 110.0, Runner({"%12": SINGLE}))
        self.assertEqual([o["op"] for o in self.ops()], ["dialog", "edit", "dialog"])
        self.assertEqual(list(self.state()), [key_of("%12", SINGLE["lines"])])

    def test_waiting_pane_with_an_empty_preview_posts_nothing(self):
        dd.scan(self.raw(preview=[]), 100.0, Runner({}))
        self.assertEqual(self.ops(), [])

    def test_show_output_that_is_not_a_dialog_object_is_an_error_not_a_raw_post(self):
        for out in ("not json", "[]", json.dumps({"kind": "question", "lines": []}), json.dumps({"kind": "question", "lines": ["a"], "options": "x"})):
            dd.scan(self.raw(), 100.0, Runner({"%12": out}))
        self.assertEqual(self.ops(), [])


class ConcurrencyTest(Base):
    def test_two_scans_at_once_post_one_message(self):
        # mutation: drop the flock in _locked (yield without locking) -> both threads post, two dialog ops
        errs = []

        def go():
            try:
                dd.scan([sess()], 100.0, Runner({"%12": SINGLE}, delay=0.3))
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=go) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
        self.assertEqual(errs, [])
        self.assertEqual([o["op"] for o in self.ops()], ["dialog"])
        self.assertEqual(len(self.state()), 1)

    def test_state_is_written_by_replace_next_to_the_lock(self):
        base = tc_env.agent_base() / "dialogs"
        with mock.patch.object(dd.os, "replace", wraps=os.replace) as rep:
            dd.scan([sess()], 100.0, Runner({"%12": SINGLE}))
        self.assertIn(str(base / "state.json"), [str(c.args[1]) for c in rep.call_args_list])
        self.assertEqual(sorted(p.name for p in base.iterdir()), ["state.json", "state.lock"])   # no temp file left behind


class RealShowTest(unittest.TestCase):
    """One real `tmux-ctl dialog <pane id> show` on a scratch tmux server (-L, -f /dev/null) showing a real captured screen:
    the argv, the JSON and the `dialog: none in` error text scan relies on are the real ones."""

    def setUp(self):
        self.tmux = paneclass.tmux_bin()
        if not (os.access(self.tmux, os.X_OK) or subprocess.run(["which", self.tmux], capture_output=True).returncode == 0):
            self.skipTest("no tmux")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sock = f"ddtest-{os.getpid()}"
        env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE", "TC_SESSION", "TMUX_DASH_TMUX_ARGS")}
        self.env = dict(env, TC_STATE=self.tmp.name, AGENT_BOARD_TMUX_SOCKET=self.sock)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.t("-f", "/dev/null", "new-session", "-d", "-s", "tt", "-n", "win", "-x", "200", "-y", "50",
               f"cat {FX / 'dialogs' / 'question-single.txt'}; sleep 600")
        self.addCleanup(self.kill)
        self.t("new-window", "-d", "-t", "=tt:", "-n", "idle", "sleep 600")
        sock_path = self.t("display", "-p", "-t", "=tt:win", "#{socket_path}").strip()
        self.env["TMUX"] = f"{sock_path},0,0"
        self.sock_path = sock_path

    def t(self, *args):
        return subprocess.run([self.tmux, "-L", self.sock, *args], capture_output=True, text=True, env=self.env, timeout=20).stdout

    def kill(self):
        self.t("kill-server")
        try:
            os.unlink(self.sock_path)
        except OSError:
            pass

    def run_real(self, argv):   # server.run_script without the board's own tmux lookup
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=self.env)
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            raise RuntimeError(out or f"exit {r.returncode}")
        return out

    def test_real_show_feeds_scan(self):
        ids = {}
        for w in ("win", "idle"):
            ids[w] = self.t("display", "-p", "-t", f"=tt:{w}", "#{pane_id}").strip()
        for _ in range(100):   # the fixture is on the pane once its footer shows
            if "Enter to select" in self.t("capture-pane", "-p", "-t", ids["win"]):
                break
            time.sleep(0.05)
        tc_env.discord_dir("tt").mkdir(parents=True)
        (tc_env.discord_dir("tt") / "bridge.json").write_text(json.dumps({"channel": "1"}))
        sessions = [{"name": "tt", "windows": [{"name": "win", "worker": False, "teammate": False, "panes": [pane(ids["win"])]},
                                               {"name": "idle", "worker": False, "teammate": False, "panes": [pane(ids["idle"], preview=["x"])]}]}]
        with self.assertRaises(RuntimeError) as cm:
            self.run_real([TC, "dialog", ids["idle"], "show"])
        self.assertTrue(str(cm.exception).startswith(dd._NONE), str(cm.exception))
        dd.scan(sessions, 100.0, self.run_real)
        ops = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((tc_env.discord_dir("tt") / "outbox").glob("*.json"))]
        self.assertEqual([o["key"] for o in ops], [key_of(ids["win"], SINGLE["lines"]), key_of(ids["idle"], ["x"])])   # the fake's lines are the real ones
        self.assertTrue(ops[0]["text"].startswith("❓ tt · win: Which fruit?\n"))
        self.assertEqual([len(r) for r in ops[0]["rows"]], [4, 1])   # four options, then Reply
        self.assertTrue(ops[1]["text"].startswith("❓ tt · idle: (dialog not parsed)"))
        st = json.loads((tc_env.agent_base() / "dialogs" / "state.json").read_text(encoding="utf-8"))["dialogs"]
        self.assertEqual({k: st[ops[0]["key"]]["show"][k] for k in ("kind", "question", "options", "multi", "other")},
                         {k: SINGLE[k] for k in ("kind", "question", "options", "multi", "other")})


if __name__ == "__main__":
    unittest.main()
