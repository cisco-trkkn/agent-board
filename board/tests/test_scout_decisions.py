"""scout_decisions: approve (path-scoped copy), retry_copies, redraft, expire, cleanup. Scratch git repo as root; scratch
TC_STATE, TC_SCOUT_DIR, TC_IDEAS_DIR, HOME and outbox. Never the real checkout."""
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
import findings  # noqa: E402
import ideas  # noqa: E402
import scout_decisions as sd  # noqa: E402
import scout_post  # noqa: E402
import tc_env  # noqa: E402

NOW = 1795000000.0
WEEK = "2026-11-22"
SPEC = "docs/superpowers/specs/2026-11-22-thing-design.md"


def git(cwd, *a):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, env=env, check=True).stdout


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        env = {"TC_STATE": t + "/state", "TC_SCOUT_DIR": t + "/scout", "TC_IDEAS_DIR": t + "/ideas", "TC_CONTEXT_DIR": t + "/ctx", "HOME": t + "/home"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.root = Path(t) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "t")
        git(self.root, "config", "user.email", "t@e")
        (self.root / "README.md").write_text("r\n")
        (self.root / "other.txt").write_text("o\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "init")
        self.lines = []

    def week_branch(self, week=WEEK, spec=SPEC):
        wt = self.root / ".claude" / "worktrees" / f"scout-{week}"
        git(self.root, "worktree", "add", "-q", "-b", f"scout/{week}", str(wt), "main")
        (wt / spec).parent.mkdir(parents=True, exist_ok=True)
        (wt / spec).write_text("# Thing\n\nbody\n")
        git(wt, "add", "--", spec)
        git(wt, "commit", "-q", "-m", "draft")
        return wt

    def draft(self, week=WEEK, spec=SPEC, **kw):
        d = {"id": "abc123abc123", "key": "item1:comp", "title": "Thing", "slug": "thing", "path": spec, "branch": f"scout/{week}",
             "worktree": str(self.root / ".claude" / "worktrees" / f"scout-{week}"), "week": week, "status": "approved",
             "why": "w", "value": "high", "effort": "S", "risk": "low", "url": "https://example.com/1", "published": None,
             "protected": False, "post_key": f"scout-agent-board-{week}", "note": None, "reason": None, "created_at": findings.iso(NOW),
             "decided_at": findings.iso(NOW), "decided_by": "u", "what_it_enables": "x",
             "evidence": [{"url": "https://example.com/1", "quote": "q"}]}
        d.update(kw)
        return d

    def store(self, *drafts, pending=()):
        s = scout_post._drafts()
        with s.locked():
            st = s.read()
            for d in drafts:
                st["drafts"][d["id"]] = d
            st["pending_copies"] = list(pending)
            s.write(st)

    def state(self):
        return scout_post._drafts().read()

    def commits(self):
        return int(git(self.root, "rev-list", "--count", "main").strip())

    def outbox(self):
        d = tc_env.discord_dir("agent-board") / "outbox"
        return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))] if d.exists() else []

    def add_line(self, t):
        self.lines.append(t)


class ApproveTest(Base):
    def setUp(self):
        super().setUp()
        self.week_branch()
        self.d = self.draft()
        self.store(self.d)

    def test_clean_repo_commits_one_file_with_trailer(self):
        self.assertEqual(sd.approve(self.d, self.root, NOW, self.add_line), "approved")
        self.assertEqual(git(self.root, "show", "--stat", "--format=%B", "HEAD").count("|"), 1)
        msg = git(self.root, "log", "-1", "--format=%B")
        self.assertIn("docs(spec): Thing (scout)", msg)
        self.assertIn("Scout-Item: item1:comp", msg)
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), [SPEC])
        self.assertEqual(self.lines, [f"[Scout] approved: {SPEC}"])
        got = ideas.load("agent-board")
        self.assertEqual(len(got), 1)
        self.assertIn(SPEC, got[0]["text"])
        rows = [json.loads(l) for l in (Path(os.environ["TC_SCOUT_DIR"]) / "approved.jsonl").read_text().splitlines()]
        self.assertEqual([(r["spec"], r["title"], r["protected"], r["consumed"]) for r in rows], [(SPEC, "Thing", False, False)])
        self.assertTrue(self.state()["drafts"][self.d["id"]]["copied_at"])

    def test_other_dirty_file_untouched_and_not_committed(self):
        (self.root / "other.txt").write_text("dirty\n")
        self.assertEqual(sd.approve(self.d, self.root, NOW, self.add_line), "approved")
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), [SPEC])
        self.assertEqual((self.root / "other.txt").read_text(), "dirty\n")
        self.assertIn("other.txt", git(self.root, "status", "--porcelain"))

    def test_spec_path_dirty_waits(self):
        p = self.root / SPEC
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("local edit\n")
        before = self.commits()
        self.assertEqual(sd.approve(self.d, self.root, NOW, self.add_line), "approved, waiting for main")
        self.assertEqual(self.commits(), before)
        self.assertEqual(self.state()["pending_copies"], [self.d["id"]])
        self.assertEqual(self.lines, [])

    def test_merge_in_progress_waits(self):
        (self.root / ".git" / "MERGE_HEAD").write_text(git(self.root, "rev-parse", "HEAD"))
        before = self.commits()
        self.assertEqual(sd.approve(self.d, self.root, NOW, self.add_line), "approved, waiting for main")
        self.assertEqual(self.commits(), before)
        self.assertEqual(self.state()["pending_copies"], [self.d["id"]])

    def test_rebase_in_progress_waits(self):
        (self.root / ".git" / "rebase-merge").mkdir()
        self.assertEqual(sd.approve(self.d, self.root, NOW), "approved, waiting for main")

    def test_head_not_on_main_waits(self):
        git(self.root, "checkout", "-q", "-b", "feature")
        before = self.commits()
        self.assertEqual(sd.approve(self.d, self.root, NOW), "approved, waiting for main")
        git(self.root, "checkout", "-q", "main")
        self.assertEqual(self.commits(), before)

    def test_repeat_approve_makes_no_second_commit(self):
        sd.approve(self.d, self.root, NOW, self.add_line)
        n = self.commits()
        self.assertEqual(sd.approve(self.d, self.root, NOW, self.add_line), "already approved")
        self.assertEqual(self.commits(), n)
        self.assertEqual(len(self.lines), 1)
        self.assertEqual(len(ideas.load("agent-board")), 1)

    def test_failing_follow_up_does_not_stop_the_others(self):
        with mock.patch("ideas.add_done", side_effect=OSError("disk")):
            self.assertEqual(sd.approve(self.d, self.root, NOW, self.add_line), "approved")
        self.assertEqual(self.lines, [f"[Scout] approved: {SPEC}"])
        self.assertTrue((Path(os.environ["TC_SCOUT_DIR"]) / "approved.jsonl").exists())
        log = (Path(os.environ["TC_SCOUT_DIR"]) / "weekly.log").read_text()
        self.assertIn("approve abc123abc123: add_done failed: OSError: disk", log)
        n = self.commits()
        self.assertEqual(sd.approve(self.d, self.root, NOW, self.add_line), "already approved")
        self.assertEqual(self.commits(), n)

    def test_waiting_then_retry_commits_once(self):
        (self.root / ".git" / "MERGE_HEAD").write_text("x")
        sd.approve(self.d, self.root, NOW, self.add_line)
        (self.root / ".git" / "MERGE_HEAD").unlink()
        sd.retry_copies(self.root, NOW + 60, self.add_line)
        self.assertEqual(self.state()["pending_copies"], [])
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), [SPEC])
        self.assertEqual(self.lines, [f"[Scout] approved: {SPEC}"])


class RetryTest(Base):
    def setUp(self):
        super().setUp()
        self.week_branch()
        self.d = self.draft(decided_at=findings.iso(NOW))
        self.store(self.d, pending=[self.d["id"]])
        (self.root / ".git" / "MERGE_HEAD").write_text("x")

    def test_busy_main_keeps_pending_before_24h(self):
        sd.retry_copies(self.root, NOW + 3600)
        self.assertEqual(self.state()["pending_copies"], [self.d["id"]])
        self.assertEqual(self.outbox(), [])

    def test_gives_up_after_24h_with_decision_post(self):
        sd.retry_copies(self.root, NOW + 25 * 3600)
        self.assertEqual(self.state()["pending_copies"], [])
        ops = self.outbox()
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["tier"], "decision")
        self.assertEqual(ops[0]["text"], "scout: Thing approved but main stayed busy for 24 h — run tmux-ctl scout approve abc123abc123")

    def test_unknown_id_is_dropped(self):
        self.store(pending=["nope"])
        sd.retry_copies(self.root, NOW)
        self.assertEqual(self.state()["pending_copies"], [])


class ThrottleTest(Base):
    def test_step_calls_retry_at_most_every_600s(self):
        import discord_controls as dc
        calls = []
        with mock.patch.object(sd, "retry_copies", lambda root, now, add_line=None: calls.append(now)), \
                mock.patch("dream.resolve_root", return_value=self.root):
            for now in (1000.0, 1300.0, 1601.0):
                dc.step("agent-board", None, now, lambda a: "", lambda s, t: None)
            st = json.loads((tc_env.discord_dir("agent-board") / "controls-state.json").read_text())
        self.assertEqual(calls, [1000.0, 1601.0])
        self.assertEqual(st["scout_retry_at"], 1601.0)

    def test_retry_without_live_session_uses_this_checkout(self):
        import discord_controls as dc
        got = []
        with mock.patch.object(sd, "retry_copies", lambda root, now, add_line=None: got.append(root)), \
                mock.patch("dream.live_session_root", return_value=None):
            dc.step("agent-board", None, 9000.0, lambda a: "", lambda s, t: None)
        self.assertEqual(got, [str(dc.scout_post.REPO.resolve())])

    def test_retry_failure_does_not_break_step(self):
        import discord_controls as dc
        with mock.patch.object(sd, "retry_copies", side_effect=RuntimeError("boom")), mock.patch("dream.resolve_root", return_value=self.root):
            dc.step("agent-board", None, 5000.0, lambda a: "", lambda s, t: None)


class ExpireTest(Base):
    def test_old_pending_expires_young_stays(self):
        old = self.draft(id="old000000000", key="k1:c", status="pending", created_at=findings.iso(NOW - 29 * 86400), decided_at=None)
        new = self.draft(id="new000000000", key="k2:c", status="pending", created_at=findings.iso(NOW - 27 * 86400), decided_at=None)
        self.store(old, new)
        with mock.patch.object(scout_post, "refresh") as rf:
            self.assertEqual(sd.expire(NOW), ["old000000000"])
        st = self.state()["drafts"]
        self.assertEqual((st["old000000000"]["status"], st["old000000000"]["reason"]), ("rejected", "expired"))
        self.assertEqual(st["new000000000"]["status"], "pending")
        self.assertIn("k1:c", findings.Store(Path(os.environ["TC_SCOUT_DIR"]) / "findings.json").read()["dismissed"])
        rf.assert_called_once_with(WEEK)


class RedraftTest(Base):
    def test_revise_redrafts_and_supersedes(self):
        old = self.draft(status="revise", note="shorter", key="item1:My Comp")
        self.store(old)
        newrec = self.draft(id="abc123abc123-r1", status="pending", path="docs/superpowers/specs/2026-11-22-thing2-design.md",
                            title="Thing 2", key="item1:My Comp")
        got = {}

        def fake(root, week, pick, note=None, prev=None, info=None):
            got.update(root=root, week=week, pick=pick, note=note, prev=prev)
            return newrec
        with mock.patch("scout_draft.draft", fake), mock.patch.object(scout_post, "refresh"):
            self.assertEqual(sd.redraft("abc123abc123", self.root), "abc123abc123-r1")
        self.assertEqual((got["note"], got["prev"], got["week"]), ("shorter", SPEC, WEEK))
        self.assertEqual(got["pick"]["component"], "My Comp")
        self.assertEqual(got["pick"]["key"], "item1:My Comp")
        st = self.state()["drafts"]
        self.assertEqual(st["abc123abc123"]["status"], "superseded")
        self.assertEqual(st["abc123abc123-r1"]["status"], "pending")
        ops = [o for o in self.outbox() if o["op"] == "post"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["key"], f"scout-agent-board-{WEEK}-abc123abc123-r1")
        self.assertEqual(ops[0]["tier"], "progress")

    def test_click_on_the_revision_edits_its_own_post(self):
        self.store(self.draft(status="revise"))
        newrec = self.draft(id="abc123abc123-r1", status="pending", key="item1:comp")
        with mock.patch("scout_draft.draft", return_value=newrec):
            sd.redraft("abc123abc123", self.root)
        n = len(self.outbox())
        self.assertEqual(scout_post.click("u", "ab:scout:reject:agent-board:abc123abc123-r1", NOW), "rejected")
        edits = [o for o in self.outbox()[n:] if o["op"] == "edit"]
        self.assertIn(f"scout-agent-board-{WEEK}-abc123abc123-r1", [o["key"] for o in edits])
        self.assertTrue(all(o["rows"] == [] for o in edits if o["key"].endswith("-r1")))

    def test_dropped_redraft_keeps_old_revise(self):
        self.store(self.draft(status="revise"))
        with mock.patch("scout_draft.draft", return_value={"id": "x", "title": "t", "why": "no spec written"}):
            self.assertIsNone(sd.redraft("abc123abc123", self.root))
        self.assertEqual(self.state()["drafts"]["abc123abc123"]["status"], "revise")

    def test_pending_revisions_lists_revise_only(self):
        self.store(self.draft(status="revise"), self.draft(id="b" * 12, key="k2:c", status="pending"))
        self.assertEqual([d["id"] for d in sd.pending_revisions()], ["abc123abc123"])


class CleanupTest(Base):
    def test_only_decided_week_removed(self):
        self.week_branch("2026-11-15", "docs/superpowers/specs/2026-11-15-a-design.md")
        self.week_branch(WEEK)
        self.store(self.draft(week="2026-11-15", id="a" * 12, key="a:c", status="rejected"),
                   self.draft(week="2026-11-15", id="c" * 12, key="c:c", status="superseded"),
                   self.draft(week=WEEK, id="b" * 12, key="b:c", status="pending"),
                   self.draft(week=WEEK, id="d" * 12, key="d:c", status="approved", copied_at=findings.iso(NOW)))
        sd.cleanup(self.root)
        branches = git(self.root, "branch", "--format=%(refname:short)").split()
        self.assertEqual(sorted(branches), ["main", f"scout/{WEEK}"])
        self.assertFalse((self.root / ".claude" / "worktrees" / "scout-2026-11-15").exists())
        self.assertTrue((self.root / ".claude" / "worktrees" / f"scout-{WEEK}").exists())

    def test_approved_waiting_for_copy_survives_until_copied(self):
        self.week_branch()
        d = self.draft()
        self.store(d, pending=[d["id"]])
        sd.cleanup(self.root)
        self.assertIn(f"scout/{WEEK}", git(self.root, "branch", "--format=%(refname:short)"))
        self.assertEqual(sd.approve(d, self.root, NOW), "approved")
        sd.cleanup(self.root)
        self.assertNotIn(f"scout/{WEEK}", git(self.root, "branch", "--format=%(refname:short)"))

    def test_revise_counts_as_undecided(self):
        self.week_branch()
        self.store(self.draft(status="revise"))
        sd.cleanup(self.root)
        self.assertIn(f"scout/{WEEK}", git(self.root, "branch", "--format=%(refname:short)"))


class ClickIntegrationTest(Base):
    def test_default_approve_fn_end_to_end(self):
        self.week_branch()
        self.store(self.draft(status="pending", decided_at=None, decided_by=None))
        with mock.patch("dream.resolve_root", return_value=self.root):
            r = scout_post.click("u", "ab:scout:approve:agent-board:abc123abc123", NOW, add_line=self.add_line)
        self.assertEqual(r, "approved")
        self.assertEqual(git(self.root, "show", "--name-only", "--format=", "HEAD").split(), [SPEC])
        self.assertEqual(self.lines, [f"[Scout] approved: {SPEC}"])
        self.assertEqual(len(ideas.load("agent-board")), 1)
        self.assertTrue((Path(os.environ["TC_SCOUT_DIR"]) / "approved.jsonl").exists())
        self.assertTrue(self.state()["drafts"]["abc123abc123"]["copied_at"])


if __name__ == "__main__":
    unittest.main()
