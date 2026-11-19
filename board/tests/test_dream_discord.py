"""dream_discord: the post, the failure line and the click handler (Task 5, G11). Scratch TC_STATE / TC_CONTEXT_DIR; nothing is posted for real."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_feed  # noqa: E402
import dream  # noqa: E402
import dream_actions  # noqa: E402
import dream_discord as DD  # noqa: E402
import tc_env  # noqa: E402

RUN = "20261119-0300"


class Base(unittest.TestCase):
    channel = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name + "/state", "TC_CONTEXT_DIR": self.tmp.name + "/ctx"})
        p.start()
        self.addCleanup(p.stop)
        self.d = tc_env.discord_dir("p")
        self.d.mkdir(parents=True)
        if self.channel:
            (self.d / "bridge.json").write_text(json.dumps({"channel": "C1"}))
        self.rd = Path(self.tmp.name) / "ctx" / "dream" / "p" / RUN
        (self.rd / "out").mkdir(parents=True)
        (self.rd / "out" / "diff.txt").write_text("diff\n")

    def res(self, **kw):
        r = {"project": "p", "run": RUN, "outcome": "ok", "dry_run": False, "failures": 0, "check": None,
             "counts": {"merged": 1, "archived": 2, "stale": 3, "added": 4}, "proposals": [], "contradictions": [],
             "summary": "fake summary", "posted": False, "run_dir": str(self.rd)}
        r.update(kw)
        return r

    def ops(self):
        box = self.d / "outbox"
        return [json.loads(f.read_text()) for f in sorted(box.glob("*.json"))] if box.exists() else []


PROP = [{"kind": "idea", "text": "t", "evidence": ["e"]}]


class OpShapes(Base):
    def test_changes_op_equals_g11(self):
        r = self.res(proposals=PROP)
        dream.notify(r)
        self.assertEqual(self.ops(), [{
            "op": "post", "text": "🌙 memory: merged 1, archived 2, stale 3, added 4; 1 proposals; 0 contradictions\nfake summary",
            "tier": "progress", "mention_user": False, "key": f"dream-p-{RUN}", "files": [str(self.rd / "out" / "diff.txt")],
            "buttons": [{"label": "Revert", "style": 4, "custom_id": f"ab:dream:revert:p:{RUN}"},
                        {"label": "File proposals", "style": 1, "custom_id": f"ab:dream:file:p:{RUN}"}]}])
        self.assertTrue(r["posted"])
        for op in self.ops():
            discord_feed._check(op)

    def test_no_file_button_without_proposals(self):
        dream.notify(self.res())
        self.assertEqual([b["label"] for b in self.ops()[0]["buttons"]], ["Revert"])

    def test_long_custom_id_drops_buttons(self):
        long = "p" * 90
        (tc_env.discord_dir(long)).mkdir(parents=True)
        (tc_env.discord_dir(long) / "bridge.json").write_text(json.dumps({"channel": "C"}))
        DD.post_run(self.res(project=long, proposals=PROP))
        box = tc_env.discord_dir(long) / "outbox"
        op = json.loads(next(box.glob("*.json")).read_text())
        self.assertNotIn("buttons", op)
        self.assertTrue(op["text"].endswith(f"\nrevert: tmux-ctl context dream-revert {long} {RUN}"))

    def test_text_cut_to_1900(self):
        dream.notify(self.res(summary="x" * 5000))
        self.assertEqual(len(self.ops()[0]["text"]), 1900)

    def test_contradictions_add_decision_op(self):
        c = [{"a": f"A{i}", "b": f"B{i}", "note": "n"} for i in range(7)]
        dream.notify(self.res(contradictions=c))
        ops = self.ops()
        self.assertEqual(len(ops), 2)
        self.assertEqual({k: ops[1][k] for k in ("op", "tier", "mention_user", "key")},
                         {"op": "post", "tier": "decision", "mention_user": True, "key": f"dream-p-{RUN}-contra"})
        self.assertTrue(ops[1]["text"].startswith("🌙 memory: these entries contradict each other. Which is right?\n1. A: A0\n   B: B0"))
        self.assertIn("5. A: A4", ops[1]["text"])
        self.assertNotIn("A5", ops[1]["text"])
        discord_feed._check(ops[1])

    def test_no_contradiction_op_without_contradictions(self):
        dream.notify(self.res())
        self.assertEqual(len(self.ops()), 1)

    def test_nothing_to_post_cases(self):
        zero = {"merged": 0, "archived": 0, "stale": 0, "added": 0}
        for r in (self.res(outcome="unchanged"), self.res(dry_run=True), self.res(counts=zero)):
            dream.notify(r)
            self.assertFalse(r["posted"])
        self.assertEqual(self.ops(), [])

    def test_critical_only_at_three(self):
        for n, want in ((1, 0), (2, 0), (3, 1), (4, 1)):   # cumulative outbox size
            dream.notify(self.res(outcome="failed", failures=n, check="model timeout", counts=None))
            self.assertEqual(len(self.ops()), want, n)
        self.assertEqual(self.ops()[0], {"op": "post", "text": "🌙 memory: p failed 3 nights running — model timeout",
                                         "tier": "critical", "mention_user": True, "key": f"dream-p-fail-{RUN}"})


class NoChannel(Base):
    channel = False

    def test_no_channel_no_op(self):
        r = self.res(proposals=PROP)
        dream.notify(r)
        self.assertEqual(self.ops(), [])
        self.assertFalse(r["posted"])


class Clicks(Base):
    def click(self, cid, project="p"):
        return DD.click(project, "U1", cid, 1.0)

    def test_revert_click_posts_a_post_not_an_edit(self):      # mutation: result as op edit
        with mock.patch.object(dream_actions, "revert", return_value="reverted"):
            self.assertEqual(self.click(f"ab:dream:revert:p:{RUN}"), "reverted")
        ops = self.ops()
        self.assertEqual(ops, [{"op": "post", "text": f"↩️ memory run {RUN} reverted", "tier": "progress", "mention_user": False,
                                "key": f"dream-p-{RUN}-reverted"}])
        self.assertNotIn("edit", [o["op"] for o in ops])

    def test_file_click_posts_count(self):
        with mock.patch.object(dream_actions, "file_proposals", return_value="filed 3") as f:
            self.assertEqual(self.click(f"ab:dream:file:p:{RUN}"), "filed 3")
        f.assert_called_once_with("p", RUN)
        self.assertEqual(self.ops()[0]["text"], "📌 filed 3 proposals")
        self.assertEqual(self.ops()[0]["key"], f"dream-p-{RUN}-filed")

    def test_a_tap_that_did_nothing_posts_nothing(self):
        for fn, ret, cid in (("revert", "already reverted", "revert"), ("revert", "stale: newer run 20261120-0300", "revert"),
                             ("revert", "busy", "revert"), ("file_proposals", "already filed", "file"),
                             ("file_proposals", "no proposals", "file"), ("file_proposals", "unknown", "file")):
            with mock.patch.object(dream_actions, fn, return_value=ret):
                self.assertEqual(self.click(f"ab:dream:{cid}:p:{RUN}"), ret)
        self.assertEqual(self.ops(), [])

    def test_click_wrong_project_ignored(self):
        with mock.patch.object(dream_actions, "revert") as rv:
            self.assertEqual(self.click(f"ab:dream:revert:other:{RUN}"), "ignored")
        rv.assert_not_called()

    def test_malformed_id_unknown(self):
        for cid in ("ab:dream:revert:p:2026", "ab:dream:nuke:p:" + RUN, "ab:dream:"):
            self.assertEqual(self.click(cid), "unknown")

    def test_click_results_land_in_the_project_outbox_never_ops(self):
        with mock.patch.object(dream_actions, "revert", return_value="reverted"):
            self.click(f"ab:dream:revert:p:{RUN}")
        self.assertTrue(self.ops())
        self.assertFalse((tc_env.ops_dir() / "outbox").exists())

    def test_action_error_is_audited_not_raised(self):
        with mock.patch.object(dream_actions, "revert", side_effect=OSError("disk")):
            self.assertEqual(self.click(f"ab:dream:revert:p:{RUN}"), "error: OSError")


if __name__ == "__main__":
    unittest.main()
