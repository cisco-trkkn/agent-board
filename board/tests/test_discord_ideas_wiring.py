"""The /ideas wiring: slash event -> discord_ideas.request, ab:ideas clicks from both consumers, the tick's expire, overseer line delivery.
Scratch TC_STATE; discord_ideas is a fake where only the call is checked. Each test names the mutation that must fail it."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_controls as dc  # noqa: E402
import discord_ideas  # noqa: E402
import discord_ops as ops  # noqa: E402
import server  # noqa: E402
import tc_env  # noqa: E402

NOW = 1_800_000_000.0
CID = "ab:ideas:park:abcd1234:0"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        self.ops = tc_env.ops_dir()
        self.ops.mkdir(parents=True)
        (self.ops / "bridge.json").write_text(json.dumps({"command_center": "C1", "approvals": "A1", "user": "U1"}))
        (self.ops / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))
        self.lines = []
        self.add = lambda s, t: self.lines.append((s, t))

    def audit(self, d):
        f = Path(d) / "audit.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


class Slash(Base):
    def slash(self, project, bridge="_ops", user="U1"):
        return ops.handle_event(None, self.ops, {"type": "slash", "command": "ideas", "project": project, "bridge": bridge,
                                                 "user": user, "ts": NOW}, self.add, {"U1"})

    def test_null_project_reaches_request_before_known(self):   # mutation: ideas branch after _known -> "unknown project"
        with mock.patch.object(discord_ideas, "request", return_value="asked") as rq:
            self.assertEqual(self.slash(None), "asked")
        self.assertEqual(rq.call_args.args[:2], (None, "_ops"))
        self.assertEqual(rq.call_args.args[2], self.add)
        self.assertIsInstance(rq.call_args.args[3], float)
        self.assertEqual(self.audit(self.ops)[-1]["result"], "asked")
        self.assertEqual(self.audit(self.ops)[-1]["target"], "ideas:all")

    def test_named_project_passes_through_with_bridge(self):
        with mock.patch.object(discord_ideas, "request", return_value="unknown project") as rq:
            self.assertEqual(self.slash("alpha", bridge="alpha"), "unknown project")
        self.assertEqual(rq.call_args.args[:2], ("alpha", "alpha"))
        self.assertEqual(self.audit(self.ops)[-1]["target"], "ideas:alpha")

    def test_disallowed_user_is_rejected_without_request(self):   # mutation: branch before the allow check
        with mock.patch.object(discord_ideas, "request") as rq:
            r = ops.handle_event(None, self.ops, {"type": "slash", "command": "ideas", "user": "X"}, self.add, {"U1"})
        self.assertEqual(r, "rejected")
        rq.assert_not_called()

    def test_other_slash_commands_unchanged(self):
        with mock.patch.object(discord_ideas, "request") as rq:
            r = ops.handle_event(None, self.ops, {"type": "slash", "command": "pause", "project": "nope", "user": "U1"}, self.add, {"U1"})
        self.assertEqual(r, "unknown project")
        rq.assert_not_called()


class Clicks(Base):
    def test_ops_consumer_routes_ideas_click(self):   # mutation: prefix check after the ab:ops early return -> "ignored"
        ev = self.ops / "events"
        ev.mkdir()
        (ev / "1.json").write_text(json.dumps({"type": "click", "custom_id": CID, "user": "U1", "ts": NOW}))
        with mock.patch.object(discord_ideas, "click", return_value="parked") as ck:
            ops.consume(self.add, lambda a: "", NOW)
        self.assertEqual(ck.call_args.args[:2], ("U1", CID))
        a = self.audit(self.ops)[-1]
        self.assertEqual((a["target"], a["result"]), (CID, "parked"))

    def test_project_consumer_routes_ideas_click(self):   # mutation: falls to the generic "ignored" audit
        d = tc_env.discord_dir("alpha")
        (d / "events").mkdir(parents=True)
        (d / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))
        (d / "events" / "1.json").write_text(json.dumps({"type": "click", "custom_id": CID, "user": "U1"}))
        with mock.patch.object(discord_ideas, "click", return_value="dropped 2") as ck:
            dc.consume_events(d, "alpha", {"prompts": {}}, lambda a: "", self.add)
        self.assertEqual(ck.call_args.args[:2], ("U1", CID))
        a = self.audit(d)[-1]
        self.assertEqual((a["target"], a["result"]), (CID, "dropped 2"))

    def test_project_consumer_rejects_stranger(self):   # mutation: allowlist check dropped
        d = tc_env.discord_dir("alpha")
        (d / "events").mkdir(parents=True)
        (d / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))
        (d / "events" / "1.json").write_text(json.dumps({"type": "click", "custom_id": CID, "user": "U9"}))
        with mock.patch.object(discord_ideas, "click") as ck:
            dc.consume_events(d, "alpha", {"prompts": {}}, lambda a: "", self.add)
        ck.assert_not_called()
        self.assertEqual(self.audit(d)[-1]["result"], "rejected")


class Tick(Base):
    def tick(self):
        with mock.patch.object(server.discord_ops, "tick"), mock.patch.object(server.discord_ops, "consume"), \
             mock.patch.object(server.discord_digest, "tick"):
            server.ops_tick([], {}, NOW, limits=None)

    def test_expire_runs_once_per_pass(self):   # mutation: call removed
        with mock.patch.object(discord_ideas, "expire", return_value=0) as ex:
            self.tick()
        ex.assert_called_once()

    def test_expire_error_is_logged_and_tick_goes_on(self):   # mutation: no try/except
        with mock.patch.object(discord_ideas, "expire", side_effect=RuntimeError("boom")), \
             mock.patch.object(server.discord_digest, "tick") as dg, mock.patch("sys.stderr") as err:
            with mock.patch.object(server.discord_ops, "tick"), mock.patch.object(server.discord_ops, "consume"):
                server.ops_tick([], {}, NOW, limits=None)
        dg.assert_called_once()
        self.assertIn("tmux-dash: ideas expire failed: RuntimeError: boom", "".join(c.args[0] for c in err.write.call_args_list))


SEP = server.SEP


def row(sess, wname, pid):
    f = [sess, "1", "0", wname, "0", "0", "0", pid, "", "claude", "/r", "1", "1", "0", "0", "/r", "999"]
    return SEP.join(f)


class OverseerDelivery(Base):
    def test_overseer_session_gets_delivery_but_no_card(self):   # mutation: deliver_comments(out) only
        layout = "\n".join([row("proj", "claude", "%1"), row("overseer", "claude", "%9")])
        got = []
        server.COMMENTS.add_line("overseer", "[Discord] /ideas abcd1234: group")   # a waiting line is what makes the overseer deliverable
        self.addCleanup(lambda: server.COMMENTS.pending("overseer") and server.COMMENTS.deliver("overseer", "%9", "claude", "idle", lambda p, t: None))
        with mock.patch.object(server, "tmux", return_value=layout), \
             mock.patch.object(server, "capture_panes", side_effect=lambda ids: {i: [] for i in ids}), \
             mock.patch.object(server, "cached_worktrees", return_value=None), \
             mock.patch.object(server.relay, "root_for", side_effect=lambda p: p), \
             mock.patch.object(server, "deliver_comments", side_effect=lambda s: got.extend(s)):
            server._last["panes"] = []
            st = server.build_state()
        self.assertEqual([s["name"] for s in st["sessions"]], ["proj"])
        self.assertIn("overseer", [s["name"] for s in got])

    def test_queued_overseer_line_is_sent_to_its_claude_pane(self):
        sent = []
        server.COMMENTS.add_line("overseer", "[Discord] /ideas abcd1234: group")
        self.addCleanup(lambda: server.COMMENTS.pending("overseer") and server.COMMENTS.deliver("overseer", "%9", "claude", "idle", lambda p, t: None))
        sess = [{"name": "overseer", "windows": [{"name": "claude", "panes": [{"id": "%9", "kind": "claude", "status": "idle"}]}]}]
        with mock.patch.object(server, "send_line", side_effect=lambda p, t: sent.append((p, t))), \
             mock.patch.object(server, "_input_busy", return_value=False):
            server.deliver_comments(sess)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "%9")
        self.assertIn("/ideas abcd1234", sent[0][1])

    def _build(self):
        layout = "\n".join([row("proj", "claude", "%1"), row("overseer", "claude", "%9")])
        calls = []

        def fake_tmux(*a):
            calls.append(a)
            return layout + server.MARK + "%1\nhello"
        with mock.patch.object(server, "tmux", side_effect=fake_tmux), \
             mock.patch.object(server, "cached_worktrees", return_value=None), \
             mock.patch.object(server.relay, "root_for", side_effect=lambda p: p), \
             mock.patch.object(server, "deliver_comments"):
            server._last["panes"] = ["%1"]
            server.build_state()
        return calls

    def test_idle_overseer_costs_no_extra_tmux_call(self):   # mutation: _overseer_sessions captures without checking pending
        self.assertFalse(server.COMMENTS.pending("overseer"))
        self.assertEqual(len(self._build()), 1)

    def test_pending_overseer_line_still_captures_its_pane(self):   # mutation: early return always []
        server.COMMENTS.add_line("overseer", "[Discord] /ideas abcd1234: group")
        self.addCleanup(lambda: server.COMMENTS.pending("overseer") and server.COMMENTS.deliver("overseer", "%9", "claude", "idle", lambda p, t: None))
        self.assertGreater(len(self._build()), 1)


if __name__ == "__main__":
    unittest.main()
