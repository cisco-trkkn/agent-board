"""lead_state: the per-project lead-state.json (spec 2026-11-23-remote-lead-liveness §1). Scratch TC_STATE.
Transcript rows copy the shape of real lead transcript rows (038623a9, 2026-11-17): a channel user row with
origin {kind: channel, server: plugin:discord:discord} and queue-operation enqueue/dequeue/remove/popAll rows; ids and text replaced."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lead_state  # noqa: E402
import tc_env  # noqa: E402

NOW = 1_800_000_000.0


def rec(status="ready", tool=None, project="alpha"):
    return {"project": project, "lead": {"status": status}, "needs_you": [],
            "agents": [{"window": "claude", "pane": "%1", "tool": tool}]}


def chan(text, mid="m1"):
    return {"type": "user", "isSidechain": False, "isMeta": True, "origin": {"kind": "channel", "server": "plugin:discord:discord"},
            "message": {"role": "user", "content": f'<channel source="plugin:discord:discord" chat_id="C1" message_id="{mid}" user="u" user_id="U1" ts="2026-11-24T21:00:00.000Z">\n{text}\n</channel>'}}


def q(op, content=None):
    r = {"type": "queue-operation", "operation": op, "timestamp": "2026-11-24T21:00:00Z", "sessionId": "s1"}
    if content is not None:
        r["content"] = content
    return r


CH = lambda t, mid="m9": chan(t, mid)["message"]["content"]   # noqa: E731


# A mid-turn channel message as the lead transcript records it, copied from 019bd56d-*.jsonl (2026-11-25) with ids, user and text
# redacted (the <channel …> tag attributes the code reads are kept): queue-operation enqueue, queue-operation remove
# (reason absorbed_mid_turn), then the attachment row with attachment.type queued_command. There is no user row for it.
_QTAG = '<channel source="plugin:discord:discord" chat_id="C1" message_id="{mid}" user="u" user_id="U1" ts="2026-11-25T00:02:48.730Z">\n{text}\n</channel>'


def queued_rows(text, mid="m7"):
    tag = _QTAG.format(mid=mid, text=text)
    return [
        {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-11-25T00:02:48.752Z", "sessionId": "s1", "content": tag},
        {"type": "queue-operation", "operation": "remove", "timestamp": "2026-11-25T00:02:49.695Z", "sessionId": "s1", "content": tag,
         "reason": "absorbed_mid_turn", "commandUuid": "cu1", "deliveryId": "d1"},
        {"parentUuid": "p1", "isSidechain": False,
         "attachment": {"type": "queued_command", "prompt": tag, "source_uuid": "cu1", "delivery_id": "d1", "commandMode": "prompt",
                        "origin": {"kind": "channel", "server": "plugin:discord:discord"}, "timestamp": "2026-11-25T00:02:48.752Z", "isMeta": True},
         "type": "attachment", "uuid": "u1", "timestamp": "2026-11-25T00:02:48.752Z",
         "rendered": [{"content": "<system-reminder>\nA message arrived from plugin:discord:discord while you were working:\n" + tag + "\n</system-reminder>"}],
         "renderedRole": "user", "session_id": "s1", "userType": "external", "entrypoint": "cli", "cwd": "/x", "sessionId": "s1", "version": "2.1.0",
         "gitBranch": "main", "dataFlowOn": True},
    ]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        lead_state._cache.clear()
        lead_state._paths.clear()
        self.home = Path(self.tmp.name) / "home"
        self.d = tc_env.discord_dir("alpha")
        self.d.mkdir(parents=True)
        (self.d / "bridge.json").write_text(json.dumps({"channel": "C1"}))

    def transcript(self, rows, sid="s1"):
        f = self.home / "projects" / "-x" / f"{sid}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return f

    def tick(self, records, now=NOW, holder=True, sid="s1"):
        lead_state.tick(records, now, holder_of=lambda p: holder, sid_of=lambda p: sid, home=self.home)

    def state(self, project="alpha"):
        return json.loads((tc_env.discord_dir(project) / "lead-state.json").read_text())


class States(Base):
    def test_each_state(self):
        for status, holder, want in [("working", True, "busy"), ("ready", True, "ready"), ("waiting", True, "needs_you"),
                                     ("missing", True, "down"), ("ready", False, "down")]:
            with self.subTest(status=status, holder=holder):
                self.tick([rec(status)], holder=holder)
                self.assertEqual(self.state()["state"], want)

    def test_down_reasons(self):   # mutation: holder checked before the missing lead -> the first reason is "bot not held"
        self.tick([rec("missing")], holder=False)
        self.assertEqual(self.state()["reason"], "no claude in the lead window")
        self.tick([rec("ready")], holder=False)
        self.assertEqual(self.state()["reason"], "bot not held")
        self.assertIs(self.state()["holder"], False)

    def test_tool_only_while_busy(self):
        self.tick([rec("working", tool="Bash: npm test")])
        self.assertEqual(self.state()["tool"], "Bash: npm test")
        self.tick([rec("ready", tool="Bash: npm test")])
        self.assertIsNone(self.state()["tool"])

    def test_since_kept_across_writes_and_reset_on_change(self):   # mutation: since = iso(now) always -> fails
        self.tick([rec("working")], now=NOW)
        self.tick([rec("working")], now=NOW + 30)
        s = self.state()
        self.assertEqual(s["since"], lead_state.iso(NOW))
        self.assertEqual(s["at"], lead_state.iso(NOW + 30))
        self.tick([rec("ready")], now=NOW + 60)
        self.assertEqual(self.state()["since"], lead_state.iso(NOW + 60))

    def test_no_file_without_bridge_json(self):
        tc_env.discord_dir("beta").mkdir(parents=True)
        self.tick([rec(project="beta")])
        self.assertFalse((tc_env.discord_dir("beta") / "lead-state.json").exists())

    def test_one_failing_project_does_not_stop_the_next(self):
        def holder(p):
            if p == "alpha":
                raise RuntimeError("boom")
            return True
        tc_env.discord_dir("gamma").mkdir(parents=True)
        (tc_env.discord_dir("gamma") / "bridge.json").write_text("{}")
        lead_state.tick([rec(project="alpha"), rec(project="gamma")], NOW, holder_of=holder, sid_of=lambda p: "", home=self.home)
        self.assertEqual(self.state("gamma")["state"], "ready")

    def test_atomic_write_leaves_no_temp_file(self):   # mutation: write straight to the target path -> a replace never happens
        with mock.patch.object(lead_state.os, "replace", wraps=os.replace) as rp:
            self.tick([rec()])
        self.assertEqual(rp.call_count, 1)
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ["bridge.json", "lead-state.json"])


class Transcript(Base):
    def test_last_read_text_and_id_from_the_newest_channel_row(self):
        self.transcript([chan("first", "m1"), {"type": "user", "origin": {"kind": "human"}, "message": {"content": "typed"}},
                         chan("  deploy it?  ", "m2")])
        self.tick([rec()])
        s = self.state()
        self.assertEqual((s["last_read_text"], s["last_read_message_id"]), ("deploy it?", "m2"))

    def test_queued_channel_message_counts_as_read(self):   # final review I3; mutation: ignore attachment rows -> (None, None)
        self.transcript(queued_rows("deploy it?", "m7"))
        self.tick([rec()])
        s = self.state()
        self.assertEqual((s["last_read_text"], s["last_read_message_id"], s["queued"]), ("deploy it?", "m7", 0))

    def test_latest_of_user_row_and_queued_attachment_wins(self):
        self.transcript([chan("old", "m1")] + queued_rows("newer", "m2"))
        self.tick([rec()])
        self.assertEqual((self.state()["last_read_text"], self.state()["last_read_message_id"]), ("newer", "m2"))
        self.transcript(queued_rows("older", "m3") + [chan("newest", "m4")])
        self.tick([rec()], now=NOW + 10)
        self.assertEqual((self.state()["last_read_text"], self.state()["last_read_message_id"]), ("newest", "m4"))

    def test_queued_attachment_prompt_as_content_blocks(self):
        rows = queued_rows("blocks", "m5")
        rows[2]["attachment"]["prompt"] = [{"type": "text", "text": rows[2]["attachment"]["prompt"]}]
        self.transcript(rows)
        self.tick([rec()])
        self.assertEqual((self.state()["last_read_text"], self.state()["last_read_message_id"]), ("blocks", "m5"))

    def test_queued_attachment_from_another_origin_or_type_is_ignored(self):
        rows = queued_rows("nope", "m6")
        rows[2]["attachment"]["origin"] = {"kind": "channel", "server": "plugin:other:other"}
        rows.append({"type": "attachment", "attachment": {"type": "other", "prompt": _QTAG.format(mid="m8", text="x"),
                                                          "origin": {"kind": "channel", "server": "plugin:discord:discord"}}})
        self.transcript(rows)
        self.tick([rec()])
        self.assertEqual((self.state()["last_read_text"], self.state()["last_read_message_id"]), (None, None))

    def test_row_with_several_tags_reports_the_last(self):   # mutation: first match -> "one"/"m1"
        r = chan("one", "m1")
        r["message"]["content"] += "\n" + CH("two", "m2")
        self.transcript([r])
        self.tick([rec()])
        s = self.state()
        self.assertEqual((s["last_read_text"], s["last_read_message_id"]), ("two", "m2"))

    def grow_past_tail(self, f):
        with open(f, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "pad": "y" * (lead_state.TAIL + 10)}) + "\n")

    def test_read_carried_when_it_slides_out_of_the_tail(self):   # mutation: drop the carry -> None
        f = self.transcript([chan("deploy it?", "m1")])
        self.tick([rec()])
        self.grow_past_tail(f)
        self.tick([rec()], now=NOW + 10)
        s = self.state()
        self.assertEqual((s["last_read_text"], s["last_read_message_id"]), ("deploy it?", "m1"))

    def test_cache_carries_the_read_without_a_state_file(self):   # mutation: drop the cache carry -> (None, None, 0)
        f = self.transcript([chan("deploy it?", "m1")])
        self.assertEqual(lead_state.transcript_info(str(f))[:2], ("deploy it?", "m1"))
        self.grow_past_tail(f)
        self.assertEqual(lead_state.transcript_info(str(f))[:2], ("deploy it?", "m1"))

    def test_read_carried_from_the_previous_file_without_a_cache(self):   # mutation: drop the prev fallback -> None
        f = self.transcript([chan("deploy it?", "m1")])
        self.tick([rec()])
        self.grow_past_tail(f)
        lead_state._cache.clear()   # a board restart
        self.tick([rec()], now=NOW + 10)
        s = self.state()
        self.assertEqual((s["last_read_text"], s["last_read_message_id"]), ("deploy it?", "m1"))

    def test_a_newer_row_in_the_tail_replaces_the_carried_read(self):   # mutation: carry over a tail match -> "old"
        f = self.transcript([chan("old", "m1")])
        self.tick([rec()])
        with open(f, "a") as fh:
            fh.write(json.dumps(chan("new", "m2")) + "\n")
        self.tick([rec()], now=NOW + 10)
        s = self.state()
        self.assertEqual((s["last_read_text"], s["last_read_message_id"]), ("new", "m2"))

    def test_text_cut_to_200(self):
        self.transcript([chan("x" * 300)])
        self.tick([rec()])
        self.assertEqual(self.state()["last_read_text"], "x" * 200)

    def test_sidechain_rows_ignored(self):
        self.transcript([chan("main", "m1"), dict(chan("side", "m2"), isSidechain=True)])
        self.tick([rec()])
        self.assertEqual(self.state()["last_read_text"], "main")

    def test_no_transcript_no_channel_row(self):
        self.tick([rec()], sid="")
        s = self.state()
        self.assertEqual((s["last_read_text"], s["last_read_message_id"], s["queued"]), (None, None, 0))

    def test_queued_counts_pending_channel_enqueues(self):
        # 3 channel enqueues, a teammate enqueue; one dequeue (FIFO: the first channel one), one remove of the third
        self.transcript([q("enqueue", CH("a", "m1")), q("enqueue", "<teammate-message>x</teammate-message>"),
                         q("enqueue", CH("b", "m2")), q("enqueue", CH("c", "m3")), q("dequeue"), q("remove", CH("c", "m3"))])
        self.tick([rec("working")])
        self.assertEqual(self.state()["queued"], 1)   # mutation: count every pending enqueue -> 2

    def test_pop_all_clears(self):
        self.transcript([q("enqueue", CH("a")), q("enqueue", CH("b")), q("popAll", "x")])
        self.tick([rec("working")])
        self.assertEqual(self.state()["queued"], 0)

    def test_unchanged_transcript_is_not_read_again(self):   # mutation: drop the cache check -> _tail_lines runs twice
        self.transcript([chan("hi")])
        with mock.patch.object(lead_state, "_tail_lines", wraps=lead_state._tail_lines) as tl:
            self.tick([rec()])
            self.tick([rec()], now=NOW + 10)
        self.assertEqual(tl.call_count, 1)

    def test_tail_only(self):   # a channel row before the last TAIL bytes is not seen
        f = self.transcript([chan("old", "m1")])
        with open(f, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "pad": "y" * (lead_state.TAIL + 10)}) + "\n")
        self.tick([rec()])
        self.assertIsNone(self.state()["last_read_text"])


if __name__ == "__main__":
    unittest.main()
