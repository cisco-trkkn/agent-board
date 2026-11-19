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
            # mutation: no free-text filter in _buttonable -> a `3. Type something.` button appears here (Reply covers that row)
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
                         [("1. Yes, and use auto mode", 4), ("2. Yes, manually approve edits", 2), ("Reply", 1)])   # no button for the free-text row 3

    def test_free_text_label_keeps_its_button_when_the_dialog_takes_no_text(self):
        # mutation: filter the free-text labels whatever `other` says -> the row has neither a button nor a Reply
        show = dict(SINGLE, other=False)
        dd.scan([sess()], 100.0, Runner({"%12": show}))
        self.assertEqual([b["label"] for b in self.buttons(self.ops()[0])], ["1. Apple", "2. Pear", "3. Type something.", "4. Chat about this"])

    def test_multi_select_writes_toggles_submit_and_reply(self):
        dd.scan([sess()], 100.0, Runner({"%12": MULTI}))
        key = key_of("%12", MULTI["lines"])
        # no toggle for a row press cannot toggle (tools/lib/dialog.zsh: `option 5 is not a checkbox of this multi-select`).
        # mutation: drop the `Chat about this` filter for multi-selects in _buttonable -> a t5 toggle; drop the free-text one -> t4
        self.assertEqual([(b["label"], b["style"], b["custom_id"]) for b in self.buttons(self.ops()[0])], [
            ("1. Apple", 2, f"ab:dlg:{key}:t1"), ("2. Pear", 2, f"ab:dlg:{key}:t2"), ("3. Plum", 2, f"ab:dlg:{key}:t3"),
            ("Submit", 1, f"ab:dlg:{key}:submit"), ("Reply", 1, f"ab:dlg:{key}:reply")])

    def test_no_reply_button_without_other(self):
        # mutation: add Reply whatever `other` says -> a third button
        dd.scan([sess()], 100.0, Runner({"%12": TRUST}))
        self.assertEqual([b["label"] for b in self.buttons(self.ops()[0])], ["1. No, exit", "2. Yes, I trust this folder"])

    def test_multi_select_without_other_has_submit_and_no_reply(self):
        show = dict(MULTI, other=False)
        dd.scan([sess()], 100.0, Runner({"%12": show}))
        self.assertEqual([b["custom_id"].rsplit(":", 1)[1] for b in self.buttons(self.ops()[0])], ["t1", "t2", "t3", "t4", "submit"])

    def test_cap_and_more_count_run_on_the_buttonable_rows(self):
        # 21 options plus the free-text row: 21 buttonable rows, so 20 buttons and `1 more`.
        # mutation: count the more line on every option (len(opts) of the unfiltered list) -> `… 2 more options`
        opts = [{"n": n, "label": f"opt {n}", "permanent": False} for n in range(1, 22)] + [{"n": 22, "label": "Type something.", "permanent": False}]
        dd.scan([sess()], 100.0, Runner({"%12": dict(SINGLE, options=opts)}))
        op = self.ops()[0]
        self.assertEqual(op["text"].split("\n")[-1], "… 1 more options: answer at the terminal")
        self.assertEqual(len([b for b in self.buttons(op) if not b["custom_id"].endswith(":reply")]), 20)

    def test_20_buttonable_rows_plus_the_free_text_row_have_no_more_line(self):
        # mutation: count the more line on the unfiltered option list -> a `… 1 more options` line
        opts = [{"n": n, "label": f"opt {n}", "permanent": False} for n in range(1, 21)] + [{"n": 21, "label": "Type something.", "permanent": False}]
        dd.scan([sess()], 100.0, Runner({"%12": dict(SINGLE, options=opts)}))
        self.assertEqual(self.ops()[0]["text"].count("more options"), 0)

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
        # mutation: target_dir takes "ops bridge.json exists" for configured -> a dialog op in the ops dir
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
        # mutation: in _sweep treat ERROR like "no dialog" (drop ERROR from the kept set) -> an edit op, and the key is gone
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
        # mutation: _raw returns its stand-in even with no preview rows -> a dialog op with an empty code block
        dd.scan(self.raw(preview=[]), 100.0, Runner({}))
        self.assertEqual(self.ops(), [])

    def test_show_output_that_is_not_a_dialog_object_is_an_error_not_a_raw_post(self):
        # mutation: _show returns None (no dialog) for output that is not JSON or not a dialog object -> a raw post per bad output
        for out in ("not json", "[]", json.dumps({"kind": "question", "lines": []}), json.dumps({"kind": "question", "lines": ["a"], "options": "x"})):
            dd.scan(self.raw(), 100.0, Runner({"%12": out}))
        self.assertEqual(self.ops(), [])

    def test_show_result_without_kind_is_an_error(self):
        # mutation: drop the `kind` check in _show -> the op is written on every scan (the record never is: KeyError in _post)
        nokind = {k: v for k, v in SINGLE.items() if k != "kind"}
        with mock.patch.object(sys, "stderr"):
            for now in (100.0, 110.0, 120.0):
                dd.scan([sess()], now, Runner({"%12": nokind}))
        self.assertEqual(self.ops(), [])
        self.assertEqual(self.state(), {})

    def test_show_result_without_kind_keeps_a_known_key(self):
        # mutation: drop the `kind` check in _show -> the key of the kind-less lines differs or the sweep edits the message
        dd.scan([sess()], 100.0, Runner({"%12": SINGLE}))
        dd.scan([sess()], 110.0, Runner({"%12": {"question": "x", "lines": ["other"], "options": []}}))
        self.assertEqual([o["op"] for o in self.ops()], ["dialog"])
        self.assertEqual(list(self.state()), [key_of("%12", SINGLE["lines"])])


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


class PressRunner(Runner):
    """Runner whose `press` calls are recorded in .presses; press_result is returned, or raised when it is an Exception."""

    def __init__(self, shows=None, press_result='dialog: %12: chose "Yes"', delay=0.0, rows=None):
        super().__init__(shows, delay)
        self.presses, self.press_result, self.rows, self.types = [], press_result, rows if rows is not None else {}, []

    def __call__(self, argv):
        if len(argv) > 3 and argv[3] == "rows":   # `rows`: the text of the rows above the input box, or the error to raise
            self.calls.append(list(argv))
            v = self.rows.get(argv[2], f"dialog: {argv[2]}: no input box")
            if v.startswith("dialog:"):
                raise RuntimeError(v)
            return v
        if len(argv) > 3 and argv[3] == "type":
            self.calls.append(list(argv))
            self.types.append(list(argv))
            if isinstance(self.press_result, Exception):
                raise self.press_result
            return "dialog: %12: typed"
        if len(argv) > 3 and argv[3] == "press":
            self.calls.append(list(argv))
            self.presses.append(list(argv))
            if self.delay:
                time.sleep(self.delay)
            if isinstance(self.press_result, Exception):
                raise self.press_result
            return self.press_result
        return super().__call__(argv)


class ConsumerBase(Base):
    def post(self, show, pid="%12"):
        """Scan once so the dialog is in the state; returns its key."""
        dd.scan([sess(panes=[pane(pid)])], 100.0, Runner({pid: show}))
        return key_of(pid, show["lines"])

    def click(self, cid, user="u1", picks=None, run=None, **extra):
        ev = {"type": "click", "custom_id": cid, "user": user, "ts": 1, **extra}
        if picks is not None:
            ev["picks"] = picks
        run = run or self.run
        return dd.click(self.d, user, cid, ev, run, 200.0)

    def reply(self, key, text, run=None, **extra):
        ev = {"type": "reply", "key": key, "text": text, "user": "u1", "ts": 1, **extra}
        return dd.reply(self.d, "u1", ev, run or self.run, 200.0)

    def edits(self):
        return [o for o in self.ops() if o["op"] == "edit"]

    def setUp(self):
        super().setUp()
        self.run = PressRunner()


class AcceptedShapesTest(ConsumerBase):
    def test_single_choice_tap_presses_that_option_with_the_records_lines(self):
        key = self.post(SINGLE)
        r = self.click(f"ab:dlg:{key}:2")
        self.assertEqual(r, "pressed: Pear")
        self.assertEqual(self.run.presses, [[TC, "dialog", "%12", "press", "--expect", "\n".join(SINGLE["lines"]), "--option", "2"]])

    def test_success_edits_the_message_and_drops_the_key(self):
        key = self.post(SINGLE)
        self.click(f"ab:dlg:{key}:1")
        e = self.edits()
        self.assertEqual([(o["key"], o["text"]) for o in e], [(key, "❓ proj · win: Which fruit?\n→ Apple (from Discord)")])
        self.assertEqual(self.state(), {})

    def test_permanent_row_with_confirm_presses(self):
        key = self.post(PLAN)
        r = self.click(f"ab:dlg:{key}:1:confirm")
        self.assertTrue(r.startswith("pressed: "), r)
        self.assertEqual(self.run.presses[0][-2:], ["--option", "1"])

    def test_submit_presses_the_final_set_of_picks(self):
        key = self.post(MULTI)
        r = self.click(f"ab:dlg:{key}:submit", picks=[1, 3])
        self.assertTrue(r.startswith("pressed: "), r)
        self.assertEqual(self.run.presses[0][4:], ["--expect", "\n".join(MULTI["lines"]), "--option", "1", "--option", "3"])
        self.assertIn("Apple, Plum", self.edits()[0]["text"])

    def test_reply_presses_text(self):
        key = self.post(SINGLE)
        r = self.reply(key, "kiwi")
        self.assertEqual(r, "pressed: kiwi")
        self.assertEqual(self.run.presses[0][4:], ["--expect", "\n".join(SINGLE["lines"]), "--text", "kiwi"])
        self.assertEqual(self.state(), {})

    def test_reply_text_control_characters_become_spaces_and_it_is_cut(self):
        # mutation: skip the control-character replace -> the argv text keeps the \n and \x1b
        key = self.post(SINGLE)
        self.reply(key, "a\nb\x1bc\td" + "x" * 2000)
        t = self.run.presses[0][-1]
        self.assertTrue(t.startswith("a b c d"), repr(t[:10]))
        self.assertEqual(len(t), 1000)
        self.assertNotRegex(t, r"[\x00-\x1f]")


class RefusedTest(ConsumerBase):
    def check(self, result, audit=None):
        self.assertEqual(result, audit)
        self.assertEqual(self.run.presses, [])
        self.assertEqual(self.edits(), [])

    def test_permanent_without_confirm_needs_confirm(self):
        # mutation: drop the permanent check -> this presses
        key = self.post(PLAN)
        self.check(self.click(f"ab:dlg:{key}:1"), "needs confirm")
        self.assertIn(key, self.state())

    def test_confirm_on_a_row_that_is_not_permanent_is_ignored(self):
        key = self.post(SINGLE)
        self.check(self.click(f"ab:dlg:{key}:1:confirm"), "ignored")

    def test_toggle_id_is_ignored(self):
        key = self.post(MULTI)
        self.check(self.click(f"ab:dlg:{key}:t2"), "ignored")

    def test_unknown_suffixes_are_ignored(self):
        key = self.post(SINGLE)
        for suffix in ("reply", "t1:confirm", "cancel", "1:cancel", "x", "", "1:confirm:x"):
            self.check(self.click(f"ab:dlg:{key}:{suffix}"), "ignored")

    def test_bad_option_numbers_are_ignored(self):
        key = self.post(SINGLE)
        for n in ("0", "03", "99", "1e1", "-1", "１"):
            self.check(self.click(f"ab:dlg:{key}:{n}"), "ignored")

    def test_single_tap_on_a_multi_select_is_ignored(self):
        key = self.post(MULTI)
        self.check(self.click(f"ab:dlg:{key}:1"), "ignored")

    def test_the_free_text_row_has_no_button_so_a_forged_id_presses_nothing(self):
        key = self.post(SINGLE)
        self.check(self.click(f"ab:dlg:{key}:3"), "ignored")

    def test_key_of_another_pane_with_the_same_hash_is_already_answered(self):
        # mutation: look the key up by its hash part only -> this presses on %12
        key = self.post(SINGLE)
        other = "p13-" + key.split("-")[1]
        self.check(self.click(f"ab:dlg:{other}:1"), "already answered")

    def test_unknown_key_is_already_answered(self):
        # mutation: drop the key lookup -> KeyError or a press
        self.post(SINGLE)   # another dialog is live: the unknown key must not fall back to it
        self.check(self.click("ab:dlg:p12-0000000000000000:1"), "already answered")

    def test_bad_picks_press_nothing(self):
        key = self.post(MULTI)
        for picks in ([], None, [9], [1, 1], [4], [5], ["1"], [True], "1", [1.5]):
            self.check(self.click(f"ab:dlg:{key}:submit", picks=picks), "ignored")

    def test_picks_with_a_permanent_option_press_nothing(self):
        show = {**MULTI, "options": [{**o, "permanent": o["n"] == 2} for o in MULTI["options"]]}
        key = self.post(show)
        self.check(self.click(f"ab:dlg:{key}:submit", picks=[1, 2]), "ignored")

    def test_picks_on_a_single_choice_dialog_press_nothing(self):
        key = self.post(SINGLE)
        self.check(self.click(f"ab:dlg:{key}:submit", picks=[1]), "ignored")

    def test_reply_to_a_dialog_without_free_text_presses_nothing(self):
        key = self.post(TRUST)
        self.check(self.reply(key, "hello"), "ignored")

    def test_reply_for_an_unknown_key_is_already_answered(self):
        self.check(self.reply("p12-0000000000000000", "hello"), "already answered")

    def test_reply_with_a_message_id_that_disagrees_with_the_state_is_ignored(self):
        key = self.post(SINGLE)
        p = tc_env.agent_base() / "dialogs" / "state.json"
        st = json.loads(p.read_text(encoding="utf-8"))
        st["dialogs"][key]["message_id"] = "111"
        p.write_text(json.dumps(st), encoding="utf-8")
        self.check(self.reply(key, "kiwi", message_id="222"), "ignored")
        self.assertEqual(self.reply(key, "kiwi", message_id="111"), "pressed: kiwi")

    def test_empty_reply_after_cleaning_presses_nothing(self):
        key = self.post(SINGLE)
        self.check(self.reply(key, " \n\t "), "ignored")


class OutcomeTest(ConsumerBase):
    def test_changed_dialog_edits_drops_the_key_and_the_next_scan_posts_the_new_one(self):
        # mutation: remove the key before the press result is known / not on "changed" -> no edit, or the new dialog is not posted
        key = self.post(SINGLE)
        self.run.press_result = RuntimeError("dialog: the dialog in %12 changed")
        self.assertEqual(self.click(f"ab:dlg:{key}:1"), "changed")
        self.assertEqual([o["text"] for o in self.edits()], ["❓ proj · win: Which fruit?\nthe dialog changed; re-sent below"])
        self.assertEqual(self.state(), {})
        dd.scan([sess()], 300.0, Runner({"%12": SINGLE}))
        self.assertEqual([o["op"] for o in self.ops()], ["dialog", "edit", "dialog"])

    def test_other_error_edits_with_the_first_line_and_is_never_retried(self):
        key = self.post(SINGLE)
        self.run.press_result = RuntimeError("dialog: %12: no cursor in the dialog\nmore detail")
        r = self.click(f"ab:dlg:{key}:1")
        self.assertEqual(r, "not pressed: dialog: %12: no cursor in the dialog")
        self.assertEqual(self.edits()[0]["text"], "❓ proj · win: Which fruit?\n⚠️ not pressed: dialog: %12: no cursor in the dialog")
        self.assertEqual(len(self.run.presses), 1)
        self.assertEqual(self.state(), {})

    def test_a_timeout_is_a_not_pressed_outcome(self):
        key = self.post(SINGLE)
        self.run.press_result = subprocess.TimeoutExpired(["x"], 20)
        self.assertTrue(self.click(f"ab:dlg:{key}:1").startswith("not pressed: "))
        self.assertEqual(self.state(), {})


class DeliveryTest(ConsumerBase):
    def test_a_second_tap_on_one_button_presses_once(self):
        key = self.post(SINGLE)
        self.assertEqual(self.click(f"ab:dlg:{key}:1"), "pressed: Apple")
        self.assertEqual(self.click(f"ab:dlg:{key}:1"), "already answered")
        self.assertEqual(len(self.run.presses), 1)

    def test_confirm_after_the_dialog_was_answered_at_the_terminal_is_already_answered(self):
        key = self.post(PLAN)
        dd.scan([sess()], 150.0, Runner({}))   # the pane shows no dialog now: swept as answered at the terminal
        self.assertEqual(self.click(f"ab:dlg:{key}:1:confirm"), "already answered")
        self.assertEqual(self.run.presses, [])

    def test_two_dialogs_in_either_order_each_act_on_their_own_key(self):
        dd.scan([sess(panes=[pane("%12"), pane("%13")])], 100.0, Runner({"%12": SINGLE, "%13": PLAN}))
        a, b = key_of("%12", SINGLE["lines"]), key_of("%13", PLAN["lines"])
        self.assertEqual(self.click(f"ab:dlg:{b}:2"), "pressed: Yes, manually approve edits")
        self.assertEqual(self.click(f"ab:dlg:{a}:1"), "pressed: Apple")
        self.assertEqual([p[2] for p in self.run.presses], ["%13", "%12"])
        self.assertEqual(self.state(), {})

    def test_the_same_event_file_consumed_twice_presses_once(self):
        import discord_controls as dc
        key = self.post(SINGLE)
        ev = self.d / "events"
        ev.mkdir(exist_ok=True)
        body = json.dumps({"type": "click", "custom_id": f"ab:dlg:{key}:1", "user": "u1", "ts": 1})
        (self.d / "access.json").write_text(json.dumps({"allowFrom": ["u1"]}))
        for n in ("1", "2"):   # two files of one tap (a redelivered event)
            (ev / f"{n}.json").write_text(body)
        dc.consume_events(self.d, "proj", {}, self.run, lambda *a: None)
        self.assertEqual(len(self.run.presses), 1)
        lines = [json.loads(l) for l in (self.d / "audit.jsonl").read_text().splitlines()]
        self.assertEqual([l["result"] for l in lines], ["pressed: Apple", "already answered"])

    def test_two_threads_on_one_key_press_once(self):
        # mutation: drop the lock around lookup+press in click -> both threads press
        key = self.post(SINGLE)
        self.run.delay = 0.3
        out, errs = [], []

        def go():
            try:
                out.append(self.click(f"ab:dlg:{key}:1"))
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=go) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
        self.assertEqual(errs, [])
        self.assertEqual(sorted(out), ["already answered", "pressed: Apple"])
        self.assertEqual(len(self.run.presses), 1)


class RoutingConsumeTest(ConsumerBase):
    """The controls step and the ops consume route dialog clicks and replies; allowFrom is checked first."""

    def events(self, d, *evs):
        e = d / "events"
        e.mkdir(parents=True, exist_ok=True)
        for n, ev in enumerate(evs):
            (e / f"{n:03d}.json").write_text(json.dumps(ev))

    def audit(self, d):
        p = d / "audit.jsonl"
        return [(l["action"], l["user"], l["result"]) for l in map(json.loads, p.read_text().splitlines())] if p.exists() else []

    def test_controls_routes_click_and_reply_and_rejects_strangers(self):
        import discord_controls as dc
        key = self.post(SINGLE)
        (self.d / "access.json").write_text(json.dumps({"allowFrom": ["u1"]}))
        self.events(self.d,
                    {"type": "click", "custom_id": f"ab:dlg:{key}:1", "user": "stranger", "ts": 1},
                    {"type": "reply", "key": key, "text": "kiwi", "user": "stranger", "ts": 2},
                    {"type": "reply", "key": key, "text": "kiwi", "user": "u1", "ts": 3},
                    {"type": "perm", "key": "k", "choice": "allow", "user": "u1", "ts": 4})
        dc.consume_events(self.d, "proj", {}, self.run, lambda *a: None)
        self.assertEqual(self.audit(self.d), [("dialog", "stranger", "rejected"), ("dialog-reply", "stranger", "rejected"),
                                              ("dialog-reply", "u1", "pressed: kiwi"), ("perm", "u1", "unknown")])
        self.assertEqual(len(self.run.presses), 1)

    def test_ops_routes_click_and_reply(self):
        import discord_ops as ops
        self.ops_on()
        d = tc_env.ops_dir()
        dd.scan([sess(name="nochan")], 100.0, Runner({"%12": SINGLE}))   # no channel: posted to the ops dir
        key = key_of("%12", SINGLE["lines"])
        self.assertIn(key, self.state())
        (d / "access.json").write_text(json.dumps({"allowFrom": ["u1"]}))
        self.events(d, {"type": "click", "custom_id": f"ab:dlg:{key}:2", "user": "u1", "ts": 1},
                    {"type": "reply", "key": key, "text": "x", "user": "u1", "ts": 2})
        ops.consume(lambda *a: None, self.run, 300.0)
        self.assertEqual(self.audit(d), [("dialog", "u1", "pressed: Pear"), ("dialog-reply", "u1", "already answered")])
        self.assertEqual(len(self.run.presses), 1)
    def test_ops_rejects_a_stranger_click_and_reply_and_presses_nothing(self):
        # mutation: drop the `user in allow` check of the reply route -> the reply presses and is audited `pressed: …`
        import discord_ops as ops
        self.ops_on()
        d = tc_env.ops_dir()
        dd.scan([sess(name="nochan")], 100.0, Runner({"%12": SINGLE}))
        key = key_of("%12", SINGLE["lines"])
        (d / "access.json").write_text(json.dumps({"allowFrom": ["u1"]}))
        self.events(d, {"type": "click", "custom_id": f"ab:dlg:{key}:2", "user": "evil", "ts": 1},
                    {"type": "reply", "key": key, "text": "x", "user": "evil", "ts": 2})
        ops.consume(lambda *a: None, self.run, 300.0)
        self.assertEqual(self.audit(d), [("dialog", "evil", "rejected"), ("dialog-reply", "evil", "rejected")])
        self.assertEqual(self.run.presses, [])
        self.assertIn(key, self.state())


class IdleTest(ConsumerBase):
    """A claude pane that turns ready after working while a remote marker is fresh: one message with Reply; the reply is typed."""
    NOW = 1_000_000.0
    ROWS = ["⏺ Done. Which file next?", "✻ Brewed for 4s · done 4:20 PM"]
    PID = "%12"

    def setUp(self):
        super().setUp()
        self.run = PressRunner(rows={self.PID: "\n".join(self.ROWS)})

    def marker(self, age=60.0, sid="s1"):
        p = tc_env.state_dir() / "remote" / sid
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        os.utime(p, (self.NOW - age, self.NOW - age))

    def scan(self, status, t=0.0, **kw):
        s = sess(panes=[pane(self.PID, status=status, preview=["preview row"])])
        w = s["windows"][0]
        w.update({k: v for k, v in kw.items() if k in ("worker", "teammate")})
        if kw.get("discord"):
            w["panes"][0]["discord"] = True
        dd.scan([s], self.NOW + t, self.run)

    def key(self):
        return key_of(self.PID, self.ROWS)

    def test_working_to_ready_with_a_fresh_marker_posts_once_with_only_reply(self):
        self.marker()
        self.scan("working"); self.scan("ready", 10); self.scan("ready", 20)
        ops = [o for o in self.ops() if o["op"] == "dialog"]
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertEqual(op["key"], self.key())
        self.assertTrue(op["text"].startswith("❓ proj · win is waiting for your reply\n```\n"), op["text"])
        for r in self.ROWS:
            self.assertIn(r, op["text"])
        self.assertEqual(self.buttons(op), [{"label": "Reply", "style": 1, "custom_id": f"ab:dlg:{self.key()}:reply"}])
        self.assertIs(op["mention_user"], True)

    def test_waiting_to_ready_posts(self):
        self.marker()
        self.scan("waiting"); self.scan("ready", 10)   # the waiting scan posts a raw item (no dialog parses); it is closed, the idle item posts
        self.assertEqual([o["key"] for o in self.ops() if o["op"] == "dialog" and "waiting for your reply" in o["text"]], [self.key()])

    def test_ready_at_first_sight_posts_nothing(self):
        # mutation: treat a missing last_status as working -> this posts
        self.marker()
        self.scan("ready"); self.scan("ready", 10)
        self.assertEqual(self.ops(), [])

    def test_teammate_worker_and_discord_panes_post_nothing(self):
        self.marker()
        for kw in ({"teammate": True}, {"worker": True}, {"discord": True}):
            self.scan("working", **kw); self.scan("ready", 10, **kw)
            self.assertEqual(self.ops(), [], kw)

    def test_no_marker_or_only_an_old_one_posts_nothing(self):
        # mutation: skip the freshness check -> the 13 h old marker posts
        self.scan("working"); self.scan("ready", 10)
        self.assertEqual(self.ops(), [])
        self.marker(age=13 * 3600)
        self.scan("working", 20); self.scan("ready", 30)
        self.assertEqual(self.ops(), [])

    def test_pane_working_again_edits_to_answered_at_the_terminal(self):
        self.marker()
        self.scan("working"); self.scan("ready", 10); self.scan("working", 20)
        e = [o for o in self.ops() if o["op"] == "edit"]
        self.assertEqual([o["text"] for o in e], [f"❓ proj · win is waiting for your reply\n{ANSWERED}"])
        self.assertEqual(self.state(), {})

    def test_screen_changing_edits_to_answered_at_the_terminal(self):
        self.marker()
        self.scan("working"); self.scan("ready", 10)
        self.run.rows[self.PID] = "something else\nentirely"
        self.scan("ready", 20)
        self.assertEqual([o["op"] for o in self.ops()], ["dialog", "edit"])

    def test_reply_types_the_rows_shown_and_edits(self):
        self.marker()
        self.scan("working"); self.scan("ready", 10)
        r = self.reply(self.key(), "option 2")
        self.assertEqual(r, "pressed: option 2")
        self.assertEqual(self.run.types, [[TC, "dialog", "%12", "type", "--expect", "\n".join(self.ROWS), "--text", "option 2"]])
        self.assertEqual(self.run.presses, [])
        self.assertEqual(self.edits()[-1]["text"], "❓ proj · win is waiting for your reply\n→ option 2 (from Discord)")
        self.assertEqual(self.state(), {})

    def test_reply_text_in_the_edit_is_cut_to_60(self):
        self.marker()
        self.scan("working"); self.scan("ready", 10)
        self.reply(self.key(), "y" * 100)
        self.assertEqual(self.edits()[-1]["text"].split("\n")[1], f"→ {'y' * 60} (from Discord)")

    def test_a_changed_screen_edits_to_resent_below_and_posts_the_new_rows_once(self):
        # mutation: drop the re-post in _finish -> no second dialog op
        self.marker()
        self.scan("working"); self.scan("ready", 10)
        self.run.press_result = RuntimeError("dialog: the screen in %12 changed")
        new = ["⏺ A different question?", "✻ Brewed for 9s"]
        self.run.rows[self.PID] = "\n".join(new)
        self.assertEqual(self.reply(self.key(), "x"), "changed")
        self.assertEqual(self.edits()[-1]["text"].split("\n")[1], "the dialog changed; re-sent below")
        posts = [o for o in self.ops() if o["op"] == "dialog"]
        self.assertEqual([o["key"] for o in posts], [self.key(), key_of(self.PID, new)])
        for r in new:
            self.assertIn(r, posts[-1]["text"])
        self.assertEqual(list(self.state()), [key_of(self.PID, new)])
        self.scan("ready", 20)   # and the next scan adds nothing
        self.assertEqual(len([o for o in self.ops() if o["op"] == "dialog"]), 2)

    def test_a_changed_screen_with_no_rows_left_does_not_promise_a_resend(self):
        self.marker()
        self.scan("working"); self.scan("ready", 10)
        self.run.press_result = RuntimeError("dialog: the screen in %12 changed")
        del self.run.rows[self.PID]   # `rows` now fails: no input box
        self.assertEqual(self.reply(self.key(), "x"), "changed")
        self.assertEqual(self.edits()[-1]["text"].split("\n")[1], "the screen changed; nothing to re-send")
        self.assertEqual(len([o for o in self.ops() if o["op"] == "dialog"]), 1)

    def test_a_failed_idle_post_is_retried_on_the_next_scan(self):
        # mutation: do not restore last_status after the failed post -> the item is never posted
        self.marker()
        self.scan("working")
        with mock.patch.object(dd.discord_feed, "outbox_write", side_effect=OSError("disk full")), mock.patch("sys.stderr"):
            self.scan("ready", 10)
        self.assertEqual(self.ops(), [])
        self.scan("ready", 20)
        self.assertEqual([o["key"] for o in self.ops() if o["op"] == "dialog"], [self.key()])

    def test_an_idle_post_with_nowhere_to_go_is_retried_on_the_next_scan(self):
        self.marker()
        self.scan("working")
        with mock.patch.object(dd, "target_dir", return_value=None):
            self.scan("ready", 10)
        self.assertEqual(self.ops(), [])
        self.scan("ready", 20)
        self.assertEqual(len([o for o in self.ops() if o["op"] == "dialog"]), 1)

    def test_a_click_on_a_non_option_id_of_an_idle_item_presses_nothing(self):
        self.marker()
        self.scan("working"); self.scan("ready", 10)
        self.assertEqual(self.click(f"ab:dlg:{self.key()}:1"), "ignored")
        self.assertEqual(self.run.calls[-1][3], "rows")


class RawReplyTest(ConsumerBase):
    def test_a_reply_to_a_raw_item_runs_type_with_the_rows_shown(self):
        # mutation: leave raw replies on `press --text` -> the argv has press, not type
        pv = ["raw one", "raw two"]
        run = PressRunner(shows={"%12": "dialog: none in %12"}, rows={"%12": "\n".join(pv)})
        dd.scan([sess(panes=[pane("%12", preview=["preview only"])])], 100.0, run)
        key = key_of("%12", pv)
        self.assertIn(key, self.state())
        self.assertEqual(dd.reply(self.d, "u1", {"type": "reply", "key": key, "text": "hi", "user": "u1"}, run, 200.0), "pressed: hi")
        self.assertEqual(run.types, [[TC, "dialog", "%12", "type", "--expect", "raw one\nraw two", "--text", "hi"]])
        self.assertEqual(run.presses, [])

    def test_raw_item_falls_back_to_the_preview_when_rows_fail(self):
        run = PressRunner(shows={"%12": "dialog: none in %12"})
        dd.scan([sess(panes=[pane("%12", preview=["a", "b"])])], 100.0, run)
        self.assertIn(key_of("%12", ["a", "b"]), self.state())


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
        self.assertEqual([len(r) for r in ops[0]["rows"]], [3, 1])   # Apple, Pear, Chat about this; then Reply for the free-text row
        self.assertTrue(ops[1]["text"].startswith("❓ tt · idle: (dialog not parsed)"))
        st = json.loads((tc_env.agent_base() / "dialogs" / "state.json").read_text(encoding="utf-8"))["dialogs"]
        self.assertEqual({k: st[ops[0]["key"]]["show"][k] for k in ("kind", "question", "options", "multi", "other")},
                         {k: SINGLE[k] for k in ("kind", "question", "options", "multi", "other")})


if __name__ == "__main__":
    unittest.main()
