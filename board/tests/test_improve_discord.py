"""Task 12: improve_discord (the loop's only Discord poster) and its click handler. Every test uses a temp discord dir, engine dir
and TC_STATE; nothing is posted for real and no engine or git is run (improve_apply is patched where a click reaches it)."""
import json, os, re, shutil, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_store as S  # noqa: E402
import improve_apply as A  # noqa: E402
import improve_discord as D  # noqa: E402
import tc_env  # noqa: E402
import improve_fixtures as F  # noqa: E402

BOARD = Path(__file__).resolve().parents[1]
EV = [{"type": "run", "ref": "r1"}]
PROSE = "--- a/docs/foo.md\n+++ b/docs/foo.md\n@@ -1 +1 @@\n-old\n+new\n"
SUNDAY = time.mktime((2026, 11, 22, 9, 0, 0, 0, 0, -1))   # a Sunday, ISO week 47
MONDAY = SUNDAY + 86400


class Base(unittest.TestCase):
    channel = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {"TC_ENGINE_DIR": self.tmp + "/eng", "TC_STATE": self.tmp + "/state",
                                           "TC_OBSERVER_DIR": self.tmp + "/state", "TC_PROJECT": "proj"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        Path(self.tmp + "/eng").mkdir()
        F.engine_db(self.tmp + "/eng")
        self.now = SUNDAY
        self.s = S.Store("proj", now=lambda: self.now)
        self.d = tc_env.discord_dir("proj")
        self.d.mkdir(parents=True)
        if self.channel:
            (self.d / "bridge.json").write_text(json.dumps({"channel": "C1"}))

    def ops(self):
        box = self.d / "outbox"
        return [json.loads(f.read_text()) for f in sorted(box.glob("*.json"))] if box.exists() else []

    def awaiting(self, **kw):
        pid = self.s.insert("manual", "procedure", "docs/foo.md", PROSE, EV, **kw)
        self.s.transition(pid, "trial", "go", trial_started_at=1.0, trial_len=5)
        self.s.transition(pid, "awaiting_you", "tokens_per_merged_task better index 0.80 (5/5 specs)")
        return pid

    def draft(self, reason="protected"):
        return self.s.insert("manual", "rule", "claude/orchestrator.md", PROSE, EV, state="drafted", reason=reason)


class Cards(Base):
    def test_awaiting_you_card(self):
        pid = self.awaiting(title="shorter")
        self.assertTrue(D.card("awaiting_you", {"id": pid, "reason": "tokens_per_merged_task better index 0.80 (5/5 specs)"}))
        (op,) = self.ops()
        self.assertEqual(op["tier"], "decision")
        self.assertEqual(op["op"], "post")
        self.assertNotIn("files", op)
        self.assertTrue(op["text"].startswith(f"🧪 {pid} procedure docs/foo.md: trial "), op["text"])
        self.assertIn("index 0.80", op["text"])
        self.assertEqual([(b["label"], b["custom_id"]) for b in op["buttons"]],
                         [("Promote", f"ab:improve:promote:proj:{pid}"), ("Reject", f"ab:improve:reject:proj:{pid}"),
                          ("Extend trial by 5", f"ab:improve:extend:proj:{pid}")])

    def test_long_custom_id_falls_back_to_the_cli_command(self):
        pid = self.awaiting()
        with mock.patch.dict(os.environ, {"TC_PROJECT": "p" * 90}):
            with mock.patch.object(D, "_project", return_value="p" * 90), mock.patch.object(D, "_store", return_value=self.s), \
                    mock.patch.object(D, "_has_channel", return_value=True), mock.patch.object(D, "_write") as w:
                self.assertTrue(D.card("awaiting_you", {"id": pid, "reason": "r"}))
        op = w.call_args.args[1]
        self.assertNotIn("buttons", op)
        self.assertIn("tmux-ctl improve", op["text"])

    def test_drafted_card_only_for_protected_non_adapter_rows(self):   # mutation: card every drafted row -> second assertion fails
        pid = self.draft()
        self.assertTrue(D.card("drafted", {"id": pid}))
        (op,) = self.ops()
        self.assertEqual(op["tier"], "decision")
        self.assertEqual([b["custom_id"] for b in op["buttons"]], [f"ab:improve:approve:proj:{pid}", f"ab:improve:reject:proj:{pid}"])
        adapter = self.s.insert("adapter", "rule", "claude/worker.md", PROSE + " ", EV, state="drafted", reason=A.ADAPTER_DRAFT)
        self.assertFalse(D.card("drafted", {"id": adapter}))
        self.assertEqual(len(self.ops()), 1)

    def test_breach_card_one_revert_button_per_kept_change(self):
        a = self.s.insert("manual", "procedure", "docs/foo.md", PROSE, EV)
        b = self.s.insert("manual", "procedure", "docs/bar.md", PROSE.replace("foo", "bar"), EV)
        for p in (a, b):
            self.s.transition(p, "trial", "go", trial_started_at=1.0)
            self.s.transition(p, "kept", "ok")
        self.assertTrue(D.card("breach", {"metric": "failed_specs", "numbers": "failed_specs worse 3 vs 1 (5/5 specs)", "kept": [a, b]}))
        (op,) = self.ops()
        self.assertEqual(op["tier"], "decision")
        self.assertIn("failed_specs", op["text"])
        self.assertEqual([b_["custom_id"] for b_ in op["buttons"]], [f"ab:improve:revert:proj:{a}", f"ab:improve:revert:proj:{b}"])
        self.assertTrue(all(b_["label"].startswith("Revert") for b_ in op["buttons"]))
        self.assertEqual(sum(1 for ln in op["text"].splitlines() if ln.startswith(("↩️", "•", "-"))), 2, op["text"])

    def test_breach_with_nothing_kept_has_no_buttons(self):
        self.assertTrue(D.card("breach", {"metric": "failed_specs", "numbers": "n", "kept": []}))
        self.assertNotIn("buttons", self.ops()[0])

    def test_achieved_card(self):
        with mock.patch.object(D, "_target", return_value="0.75"):
            self.assertTrue(D.card("achieved", {"id": "O1", "index": 0.7, "batches": 3}))
        (op,) = self.ops()
        self.assertEqual(op["tier"], "progress")
        self.assertEqual(op["text"], "🎯 O1 achieved: 0.70 vs 0.75")
        self.assertNotIn("buttons", op)

    def test_unknown_kind_or_missing_row_posts_nothing_and_never_raises(self):
        self.assertFalse(D.card("nonsense", {}))
        self.assertFalse(D.card("awaiting_you", {"id": "P99", "reason": "r"}))
        self.assertFalse(D.card("awaiting_you", None))
        self.assertEqual(D.digest(None, 1)["posted"], 0)
        self.assertEqual(self.ops(), [])

    def test_a_card_that_fails_to_write_returns_false(self):
        pid = self.awaiting()
        with mock.patch.object(D.discord_feed, "outbox_write", side_effect=OSError("disk")):
            self.assertFalse(D.card("awaiting_you", {"id": pid, "reason": "r"}))

    def test_no_channel_no_card(self):
        for f in self.d.glob("bridge.json"):
            f.unlink()
        pid = self.awaiting()
        self.assertFalse(D.card("awaiting_you", {"id": pid, "reason": "r"}))
        self.assertEqual(self.ops(), [])

    def test_sweep_drafts_posts_the_drafted_card(self):
        pid = self.s.insert("manual", "rule", "claude/orchestrator.md", PROSE, EV)

        def fake_draft(store, p, repo=None):
            store.transition(p, "drafted", "protected")
        with mock.patch.object(A, "draft", fake_draft):
            self.assertEqual(A.sweep_drafts(self.s), {"drafted": 1})
        self.assertEqual([b["custom_id"] for b in self.ops()[0]["buttons"]][0], f"ab:improve:approve:proj:{pid}")


class Digest(Base):
    def tr(self, pid_kind="procedure", n=1):
        for i in range(n):
            pid = self.s.insert("manual", pid_kind, f"docs/f{i}.md", PROSE.replace("foo", f"f{i}"), EV)
            self.s.transition(pid, "trial", "go", trial_started_at=1.0)
            yield pid

    def test_sunday_digest_counts_transitions_only(self):
        a, b, c = self.tr(n=3)
        self.s.transition(a, "kept", "ok")
        self.s.transition(b, "reverted", "bad")
        self.s.transition(c, "awaiting_you", "x")
        for i in range(4):   # sweeps repeat these every tick: they are not transitions
            D.improve_apply._event(self.s, "improve_refused", {"proposal": a, "from": "kept", "to": "reverted", "why": "w"})
            D.improve_apply._event(self.s, "improve_waiting", {"proposal": a, "from": "kept", "to": "reverted"})
        with mock.patch.object(D, "_o1", return_value="O1 0.90 vs 0.75"):
            out = D.digest(self.s, 1)
        (op,) = self.ops()
        self.assertEqual(op["text"], "🧪 improve: 3 trials, 1 kept, 1 reverted, 1 awaiting you; O1 0.90 vs 0.75")
        self.assertEqual(op["tier"], "progress")
        self.assertEqual(op["key"], "improve-digest-proj-2026-W47")
        self.assertNotIn("buttons", op)
        self.assertEqual(out["posted"], 1)

    def test_once_per_iso_week(self):
        with mock.patch.object(D, "_o1", return_value="O1 n/a vs target"):
            D.digest(self.s, 1)
            self.now += 3600
            self.assertEqual(D.digest(self.s, 2)["posted"], 0)
        self.assertEqual(len(self.ops()), 1)

    def test_not_on_other_days_and_a_quiet_tick_writes_no_outbox_file(self):
        self.now = MONDAY
        self.assertEqual(D.digest(self.s, 1)["posted"], 0)
        self.assertFalse((self.d / "outbox").exists())

    def test_only_this_weeks_transitions_count(self):
        (a,) = self.tr()
        self.s.transition(a, "kept", "ok")
        self.now = SUNDAY + 7 * 86400
        with mock.patch.object(D, "_o1", return_value="O1 n/a vs target"):
            D.digest(self.s, 1)
        self.assertTrue(self.ops()[0]["text"].startswith("🧪 improve: 0 trials, 0 kept, 0 reverted, 0 awaiting you"))


class Click(Base):
    def cid(self, act, pid, project="proj"):
        return f"ab:improve:{act}:{project}:{pid}"

    def click(self, act, pid, project="proj", **kw):
        return D.click("proj", "U1", self.cid(act, pid, project), self.now, **kw)

    def test_promote_then_apply_and_a_result_post(self):
        pid = self.awaiting()
        with mock.patch.object(A, "reject_if_stale", return_value=False) as rs, mock.patch.object(A, "apply", return_value="applied:abc") as ap:
            self.assertEqual(self.click("promote", pid), "promoted")
        self.assertEqual(self.s.get(pid)["state"], "promoted")
        rs.assert_called_once()
        ap.assert_called_once_with(mock.ANY, pid)
        (op,) = self.ops()
        self.assertEqual(op["tier"], "progress")
        self.assertIn(pid, op["text"])

    def test_promote_of_a_stale_patch_is_stale_and_does_not_promote(self):
        pid = self.awaiting()
        with mock.patch.object(A, "reject_if_stale", side_effect=lambda st, p: st.transition(p, "rejected", "stale patch") and True), \
                mock.patch.object(A, "apply") as ap:
            self.assertEqual(self.click("promote", pid), "stale")
        ap.assert_not_called()
        self.assertEqual(self.s.get(pid)["state"], "rejected")

    def test_reject(self):
        pid = self.awaiting()
        self.assertEqual(self.click("reject", pid), "rejected")
        self.assertEqual(self.s.get(pid)["state"], "rejected")
        self.assertEqual(len(self.ops()), 1)

    def test_extend_goes_back_to_trial_with_five_more(self):
        pid = self.awaiting()
        self.assertEqual(self.click("extend", pid), "extended")
        row = self.s.get(pid)
        self.assertEqual((row["state"], row["trial_len"]), ("trial", 10))
        self.assertEqual(len(self.ops()), 1)

    def test_double_click_second_is_stale(self):   # mutation: skip the state check -> two transitions (second raises or re-acts)
        pid = self.awaiting()
        self.assertEqual(self.click("reject", pid), "rejected")
        n = len(self.ops())
        self.assertEqual(self.click("reject", pid), "stale")
        self.assertEqual(self.click("extend", pid), "stale")
        self.assertEqual(self.s.get(pid)["state"], "rejected")
        self.assertEqual(len(self.ops()), n)
        c = self.s._conn()
        try:
            moves = [json.loads(d)["to"] for (d,) in c.execute("SELECT detail FROM events WHERE kind='improve'") if json.loads(d).get("proposal") == pid]
        finally:
            c.close()
        self.assertEqual(moves.count("rejected"), 1)

    def test_approve_a_protected_draft(self):
        pid = self.draft()
        with mock.patch.object(A, "approve_draft", return_value="approved") as ap:
            self.assertEqual(self.click("approve", pid, add_line=lambda t: None), "approved")
        ap.assert_called_once()
        self.assertEqual(len(self.ops()), 1)

    def test_approve_of_an_adapter_draft_is_stale(self):   # mutation: skip the reason check -> approve_draft is called
        pid = self.draft(reason=A.ADAPTER_DRAFT)
        with mock.patch.object(A, "approve_draft") as ap:
            self.assertEqual(self.click("approve", pid), "stale")
        ap.assert_not_called()
        self.assertEqual(self.ops(), [])

    def test_reject_of_a_draft(self):
        pid = self.draft()
        self.assertEqual(self.click("reject", pid), "rejected")

    def test_revert_a_kept_change(self):
        pid = self.s.insert("manual", "procedure", "docs/foo.md", PROSE, EV)
        self.s.transition(pid, "trial", "go", trial_started_at=1.0)
        self.s.transition(pid, "kept", "ok")
        with mock.patch.object(A, "revert", return_value="abc123") as rv:
            self.assertEqual(self.click("revert", pid), "reverted")
        rv.assert_called_once_with(mock.ANY, pid, reason="reverted by U1")
        self.assertEqual(len(self.ops()), 1)

    def test_revert_of_a_proposal_that_is_not_kept_is_stale(self):
        pid = self.awaiting()
        with mock.patch.object(A, "revert") as rv:
            self.assertEqual(self.click("revert", pid), "stale")
        rv.assert_not_called()

    def test_other_project_unknown_and_missing(self):
        pid = self.awaiting()
        self.assertEqual(self.click("reject", pid, project="other"), "ignored")
        self.assertEqual(D.click("proj", "U1", "ab:improve:bogus:proj:P1", self.now), "unknown")
        self.assertEqual(D.click("proj", "U1", "ab:improve:reject:proj:P1;x", self.now), "unknown")
        self.assertEqual(D.click("proj", "U1", None, self.now), "unknown")
        self.assertEqual(self.click("reject", "P99"), "stale")
        self.assertEqual(self.s.get(pid)["state"], "awaiting_you")
        self.assertEqual(self.ops(), [])

    def test_a_failing_action_is_an_error_result_never_a_raise(self):
        pid = self.awaiting()
        with mock.patch.object(A, "reject_if_stale", side_effect=RuntimeError("boom")):
            self.assertEqual(self.click("promote", pid), "error: RuntimeError")


class Isolation(unittest.TestCase):
    def test_outbox_write_only_in_improve_discord(self):
        hits = sorted(p.name for p in BOARD.glob("improve*.py") if "outbox_write" in p.read_text())
        self.assertEqual(hits, ["improve_discord.py"])

    def test_cli_click_subcommand_exists(self):
        import improve
        self.assertIn("click", improve.parser().format_help())


if __name__ == "__main__":
    unittest.main()
