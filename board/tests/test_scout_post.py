"""scout_post: the weekly digest, drafts.json / findings.json state, clicks and replies. Scratch TC_STATE, TC_SCOUT_DIR, TC_IDEAS_DIR, HOME."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_feed  # noqa: E402
import findings  # noqa: E402
import scout_post as sp  # noqa: E402
import tc_env  # noqa: E402

NOW = 1795000000.0
WEEK = "2026-11-22"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        env = {"TC_STATE": t + "/state", "TC_SCOUT_DIR": t + "/scout", "TC_IDEAS_DIR": t + "/ideas", "TC_CONTEXT_DIR": t + "/ctx", "HOME": t + "/home"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)

    def outbox(self):
        d = tc_env.discord_dir("agent-board") / "outbox"
        return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))] if d.exists() else []

    def spec(self, name="a-spec.md"):
        p = Path(self.tmp.name) / "wt" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# spec\n")
        return str(p)

    def draft(self, i=1, **kw):
        d = {"id": f"d{i:011d}", "key": f"item{i}:comp", "title": f"Draft {i}", "slug": f"s{i}", "path": self.spec(f"s{i}-spec.md"),
             "branch": f"scout/s{i}", "worktree": "/w", "week": WEEK, "why": f"why {i}", "value": "high", "effort": "S", "risk": "low",
             "url": f"https://example.com/{i}", "published": None, "protected": False, "what_it_enables": "x",
             "evidence": [{"url": f"https://example.com/{i}", "quote": "q1"}, {"url": "https://example.com/z", "quote": "q2"}]}
        d.update(kw)
        return d

    def other(self, i=1, **kw):
        o = {"key": f"other{i}:comp", "title": f"Other {i}", "why": f"owhy {i}", "what_it_enables": f"enables {i}", "value": "med",
             "effort": "M", "risk": "low", "url": f"https://example.com/o{i}",
             "evidence": [{"url": f"https://example.com/o{i}", "quote": f"oq{i}"}]}
        o.update(kw)
        return o

    def publish(self, drafts=None, others=None, **kw):
        a = dict(overlaps=[], dropped=[], health={"sources": [{"kind": "discord_channel", "name": "scout"}], "health": {}}, tokens=1234)
        a.update(kw)
        return sp.publish(WEEK, [self.draft(1)] if drafts is None else drafts, others or [], a["overlaps"], a["dropped"], a["health"], a["tokens"], NOW)

    def dstate(self):
        return sp._drafts().read()

    def fstate(self):
        return sp._findings().read()

    def click(self, act, ident, **kw):
        kw.setdefault("approve_fn", lambda d, add: None)
        return sp.click("U1", f"ab:scout:{act}:agent-board:{ident}", NOW + 5, **kw)


class BuildTest(Base):
    def build(self, drafts, others, **kw):
        a = dict(overlaps=[], dropped=[], health={"sources": [{"kind": "discord_channel"}], "health": {}}, tokens=99)
        a.update(kw)
        return sp.build_op(WEEK, drafts, others, a["overlaps"], a["dropped"], a["health"], a["tokens"])

    def test_order_header_rows_files(self):
        d1, o1 = self.draft(1), self.other(1)
        op = self.build([d1], [o1], overlaps=["dup of x"], dropped=["bad y"], health={"sources": [{"kind": "rss"}], "health": {"feed": {"failures": 3}, "ok": {"failures": 2}}})
        t = op["text"]
        self.assertTrue(t.startswith("🛰 scout agent-board 2026-11-22: 1 drafted, 1 other\n1. Draft 1 — why 1\n   value high · effort S · risk low · source: [link](https://example.com/1)"))
        order = [t.index(s) for s in ("1. Draft 1", "Other findings:", "2. Other 1", "Overlaps:", "Dropped:", "Source health:", "tokens: 99")]
        self.assertEqual(order, sorted(order))
        self.assertIn("feed", t.split("Source health:")[1])
        self.assertNotIn("ok", t.split("Source health:")[1].replace("tokens", ""))
        self.assertIn("#scout not set", t)
        self.assertEqual([[(b["label"], b["style"]) for b in r] for r in op["rows"]],
                         [[("Approve 1", 3), ("Reject 1", 4), ("Revise 1", 2)], [("File as idea 2", 1), ("Dismiss 2", 2)]])
        self.assertEqual(op["rows"][0][0]["custom_id"], f"ab:scout:approve:agent-board:{d1['id']}")
        self.assertEqual(op["rows"][1][1]["custom_id"], f"ab:scout:dismiss:agent-board:{findings.kid(o1['key'])}")
        self.assertEqual((op["key"], op["tier"], op["mention_user"]), ("scout-agent-board-" + WEEK, "progress", False))
        self.assertEqual(op["files"], [str(Path(self.tmp.name) / "scout" / "runs" / WEEK / "files" / "s1-spec.md")])
        self.assertTrue(Path(op["files"][0]).is_file())
        discord_feed._check(op)

    def test_files_resolve_a_repo_relative_path_under_the_worktree(self):
        wt = Path(self.tmp.name) / "wt2"
        rel = "docs/superpowers/specs/2026-11-22-x-design.md"
        (wt / rel).parent.mkdir(parents=True)
        (wt / rel).write_text("# X\n")
        op = self.build([self.draft(1, path=rel, worktree=str(wt))], [])
        self.assertEqual([Path(f).name for f in op["files"]], ["2026-11-22-x-design.md"])
        self.assertEqual(Path(op["files"][0]).read_text(), "# X\n")

    def test_empty_sections_left_out(self):
        t = self.build([self.draft(1)], [])["text"]
        for s in ("Other findings:", "Overlaps:", "Dropped:", "Source health:"):
            self.assertNotIn(s, t)
        self.assertIn("tokens: 99", t)

    def test_protected_flag(self):
        self.assertIn("⚠ touches protected files", self.build([self.draft(1, protected=True)], [])["text"])
        self.assertNotIn("⚠", self.build([self.draft(1)], [])["text"])

    def test_cap_shrinks_and_sections_survive(self):
        big = "w" * 3000
        ds = [self.draft(i, title=big, why=big) for i in (1, 2, 3)]
        os_ = [self.other(i, title=big, why=big, evidence=[{"url": "https://e/x", "quote": big}]) for i in (1, 2)]
        op = self.build(ds, os_, overlaps=[big], dropped=[big], health={"sources": [], "health": {"s": {"failures": 9}}})
        self.assertLessEqual(len(op["text"]), 1900)
        for s in ("Overlaps:", "Dropped:", "Source health:", "tokens: 99", "Other findings:", "5. "):
            self.assertIn(s, op["text"])
        discord_feed._check(op)

    def test_row_limit_five_others_listed_without_buttons(self):
        op = self.build([self.draft(1), self.draft(2)], [self.other(i) for i in range(1, 5)])
        self.assertEqual(len(op["rows"]), 5)
        self.assertIn("6. Other 4", op["text"])
        self.assertNotIn("Dismiss 6", json.dumps(op["rows"]))


class PublishTest(Base):
    def test_state_written(self):
        self.publish(others=[self.other(1)])
        d = self.dstate()
        dr = d["drafts"][self.draft(1)["id"]]
        self.assertEqual((dr["status"], dr["post_key"]), ("pending", "scout-agent-board-" + WEEK))
        f = self.fstate()
        self.assertEqual(f["reported"]["other1:comp"]["last_evidence_count"], 1)
        self.assertIn(WEEK, f["posts"])
        self.assertEqual(len(self.outbox()), 1)
        self.assertTrue(sp.scout_dir().joinpath("drafts.json").is_file())

    def test_republish_keeps_a_decided_draft(self):
        d1, d2 = self.draft(1), self.draft(2)
        self.publish(drafts=[d1, d2])
        self.assertEqual(self.click("approve", d1["id"]), "approved")
        before = self.dstate()["drafts"][d1["id"]]
        self.publish(drafts=[d1, d2])                      # weekly --force in the same week
        after = self.dstate()["drafts"]
        self.assertEqual({k: after[d1["id"]][k] for k in ("status", "decided_at", "decided_by")},
                         {k: before[k] for k in ("status", "decided_at", "decided_by")})
        self.assertEqual(after[d2["id"]]["status"], "pending")
        op = self.outbox()[-1]
        self.assertEqual(op["op"], "post")
        self.assertIn("✅ approved", op["text"])
        self.assertEqual([b["label"] for r in op["rows"] for b in r], ["Approve 2", "Reject 2", "Revise 2"])

    def test_outbox_failure_leaves_both_states(self):
        with mock.patch.object(discord_feed, "outbox_write", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.publish(others=[self.other(1)])
        self.assertEqual(self.dstate()["drafts"], {})
        self.assertEqual((self.fstate()["reported"], self.fstate()["posts"]), ({}, {}))


class ClickTest(Base):
    def setUp(self):
        super().setUp()
        self.d = self.draft(1)
        self.o = self.other(1)
        self.publish(drafts=[self.d], others=[self.o])
        self.did, self.okid = self.d["id"], findings.kid(self.o["key"])

    def last(self):
        return self.outbox()[-1]

    def test_approve(self):
        calls = []
        add = lambda t: None  # noqa: E731
        r = self.click("approve", self.did, approve_fn=lambda d, a: calls.append((d["id"], d["status"], a)), add_line=add)
        self.assertEqual(r, "approved")
        self.assertEqual(calls, [(self.did, "approved", add)])
        dr = self.dstate()["drafts"][self.did]
        self.assertEqual((dr["status"], dr["decided_by"]), ("approved", "U1"))
        op = self.last()
        self.assertEqual((op["op"], op["key"]), ("edit", "scout-agent-board-" + WEEK))
        self.assertIn("— ✅ approved", op["text"])
        self.assertNotIn("Approve 1", json.dumps(op["rows"]))
        self.assertIn("Dismiss 2", json.dumps(op["rows"]))

    def test_reject_dismisses_key_with_evidence_count(self):
        self.assertEqual(self.click("reject", self.did), "rejected")
        self.assertEqual(self.dstate()["drafts"][self.did]["status"], "rejected")
        self.assertEqual(self.fstate()["dismissed"]["item1:comp"]["evidence_count"], 2)
        self.assertIn("— ✖ rejected", self.last()["text"])

    def test_revise(self):
        self.assertEqual(self.click("revise", self.did), "revise")
        self.assertEqual(self.dstate()["drafts"][self.did]["status"], "revise")
        self.assertIn("— ✏ revise", self.last()["text"])

    def test_expired_mark(self):
        def f(st):
            st["drafts"][self.did]["status"] = "expired"
        sp._drafts().update(f)
        sp.refresh(WEEK)
        t = self.last()["text"]
        self.assertIn("— ⌛ expired", t)
        self.assertEqual(self.last()["rows"][0][0]["custom_id"].split(":")[2], "file")

    def test_file_and_dismiss_other(self):
        self.assertEqual(self.click("file", self.okid), "filed")
        line = self.fstate()["filed"]["other1:comp"]["idea_line"]
        self.assertIn("scout: Other 1 — enables 1 (https://example.com/o1)", json.dumps(line) if not isinstance(line, str) else line)
        self.assertIn("— 💡 filed", self.last()["text"])
        self.assertEqual(self.click("dismiss", self.okid), "already filed")

    def test_dismiss_other(self):
        self.assertEqual(self.click("dismiss", self.okid), "dismissed")
        self.assertEqual(self.fstate()["dismissed"]["other1:comp"]["evidence_count"], 1)
        self.assertIn("— ✖ dismissed", self.last()["text"])

    def test_ignored_unknown_garbage(self):
        self.assertEqual(sp.click("U1", f"ab:scout:approve:other:{self.did}", NOW), "ignored")
        self.assertEqual(self.click("approve", "nope"), "unknown")
        self.assertEqual(self.click("file", "0123456789ab"), "unknown")
        self.assertEqual(sp.click("U1", "ab:scout:zzz", NOW), "unknown")

    def test_decided_draft_is_already(self):
        self.click("revise", self.did)
        self.assertEqual(self.click("approve", self.did), "already revise")

    def test_default_approve_fn_uses_scout_decisions(self):
        fake = mock.Mock()
        fake.approve.return_value = None
        with mock.patch.dict(sys.modules, {"scout_decisions": fake}), mock.patch.object(sp.dream, "resolve_root", return_value="/r"):
            r = sp.click("U1", f"ab:scout:approve:agent-board:{self.did}", NOW, add_line="A")
        self.assertEqual(r, "approved")
        args = fake.approve.call_args.args
        self.assertEqual((args[0]["id"], args[1], args[3]), (self.did, "/r", "A"))

    def test_default_approve_without_live_session_uses_this_checkout(self):
        fake = mock.Mock()
        fake.approve.return_value = None
        with mock.patch.dict(sys.modules, {"scout_decisions": fake}), mock.patch.object(sp.dream, "live_session_root", return_value=None):
            r = sp.click("U1", f"ab:scout:approve:agent-board:{self.did}", NOW, add_line="A")
        self.assertEqual(r, "approved")
        self.assertEqual(fake.approve.call_args.args[1], str(sp.REPO.resolve()))

    def test_two_threads_one_approval(self):
        calls, res, gate = [], [], threading.Barrier(2)

        def go():
            gate.wait()
            res.append(self.click("approve", self.did, approve_fn=lambda d, a: calls.append(1)))
        ts = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(res), ["already approved", "approved"])
        self.assertEqual(len(calls), 1)

    def test_reject_after_approve(self):
        self.click("approve", self.did)
        self.assertEqual(self.click("reject", self.did), "already approved")
        self.assertEqual(self.dstate()["drafts"][self.did]["status"], "approved")
        self.assertNotIn("item1:comp", self.fstate()["dismissed"])

    def test_approve_fn_error_is_audited_not_raised(self):
        def boom(d, a):
            raise RuntimeError("x")
        self.assertEqual(self.click("approve", self.did, approve_fn=boom), "error: RuntimeError")


class ReplyTest(Base):
    def setUp(self):
        super().setUp()
        self.d = self.draft(1)
        self.publish(drafts=[self.d])
        self.rk = f"ab:scout:reject:agent-board:{self.d['id']}"
        self.vk = f"ab:scout:revise:agent-board:{self.d['id']}"

    def test_reason_and_note(self):
        self.assertEqual(sp.reply("U1", self.rk, "too risky", NOW), "noted")
        self.assertEqual(sp.reply("U1", self.vk, "shorter please", NOW), "noted")
        dr = self.dstate()["drafts"][self.d["id"]]
        self.assertEqual((dr["reason"], dr["note"]), ("too risky", "shorter please"))

    def test_cut_to_500_and_repeat_keeps_last(self):
        sp.reply("U1", self.rk, "a" * 900, NOW)
        self.assertEqual(len(self.dstate()["drafts"][self.d["id"]]["reason"]), 500)
        sp.reply("U1", self.rk, "first", NOW)
        self.assertEqual(sp.reply("U1", self.rk, "last", NOW), "noted")
        self.assertEqual(self.dstate()["drafts"][self.d["id"]]["reason"], "last")

    def test_other_keys_ignored(self):
        for k in ("ab:dlg:x", f"ab:scout:approve:agent-board:{self.d['id']}", "ab:scout:reject:agent-board:nope", "ab:scout:reject:other:" + self.d["id"]):
            self.assertEqual(sp.reply("U1", k, "t", NOW), "ignored", k)


if __name__ == "__main__":
    unittest.main()
