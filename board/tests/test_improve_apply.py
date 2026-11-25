"""Task 10: improve_apply (apply, revert, retire, drafted specs) through the engine's real `merge-branch` entry.
Every test commits only in a scratch repo in a temp dir (TC_IMPROVE_REPO), with a temp TC_ENGINE_DIR and TC_STATE; the
tmux-ctl the code calls is a stub (TC_TMUX_CTL) that runs this checkout's engine CLI and improve.py against those."""
import hashlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_store as S  # noqa: E402
import improve_apply as A  # noqa: E402
import improve  # noqa: E402
import improve_fixtures as F  # noqa: E402

CODE = Path(__file__).resolve().parents[2]
EV = [{"type": "run", "ref": "r1"}]
PROSE = "--- a/docs/foo.md\n+++ b/docs/foo.md\n@@ -1 +1 @@\n-old\n+new\n"
ORCH = "--- a/claude/orchestrator.md\n+++ b/claude/orchestrator.md\n@@ -1 +1 @@\n-rules\n+looser rules\n"
SKILL = b"---\nname: x\n---\n\n# X\n\nbody \xc3\xa9\n\n```sh\n$ run\n```\n"
NOTES = "# Notes\n\nintro\n\n## Old rule\n\nnever do this\n\n### Detail\n\nmore\n\n## Other\n\nstays\n"


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo, eng, state = self.tmp / "repo", self.tmp / "engine", self.tmp / "state"
        for d in (self.repo, eng, state):
            d.mkdir()
        stub = self.tmp / "tmux-ctl"
        stub.write_text('#!/bin/sh\ncmd=$1; shift\ncase "$cmd" in\n'
                        f'  engine) exec node "{CODE}/engine/bin/engine.js" "$@" ;;\n'
                        f'  improve) exec python3 -I "{CODE}/board/improve.py" "$@" ;;\nesac\nexit 64\n')
        stub.chmod(0o755)
        env = mock.patch.dict(os.environ, {"TC_IMPROVE_PROJECT": "proj", "TC_ENGINE_DIR": str(eng), "TC_STATE": str(state), "TC_OBSERVER_DIR": str(state),
                                           "TC_IMPROVE_REPO": str(self.repo), "TC_TMUX_CTL": str(stub), "TC_PROJECT": "proj"})
        env.start()
        self.addCleanup(env.stop)
        self.state = state
        self.git("init", "-q", "-b", "main")
        for k, v in (("user.email", "t@example.com"), ("user.name", "T"), ("commit.gpgsign", "false")):
            self.git("config", k, v)
        for f, data in (("docs/foo.md", b"old\n"), ("claude/orchestrator.md", b"rules\n"), ("claude/skills/x/SKILL.md", SKILL),
                        ("docs/notes.md", NOTES.encode()), ("other.txt", b"o\n")):
            (self.repo / f).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / f).write_bytes(data)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "files")
        F.engine_db(eng)
        self.s = S.Store("proj")

    def git(self, *a, check=True):
        r = subprocess.run(["git", "-C", str(self.repo), *a], capture_output=True, text=True)
        if check and r.returncode:
            raise AssertionError(f"git {' '.join(a)}: {r.stderr}")
        return r.stdout

    def head(self, ref="main"):
        return self.git("rev-parse", ref).strip()

    def count(self, since):
        return int(self.git("rev-list", "--count", f"{since}..main"))

    def events(self, kind):
        c = self.s._conn()
        try:
            return [json.loads(r["detail"]) for r in c.execute("SELECT detail FROM events WHERE kind = ? ORDER BY seq", (kind,))]
        finally:
            c.close()

    def kept(self, patch=PROSE, target="docs/foo.md", kind="procedure", title="Better words", to="kept"):
        """A proposal the store classed by this checkout's rules, moved to `kept` (or through awaiting_you to `promoted`)."""
        pid = self.s.insert("manual", kind, target, patch, EV, title=title)
        self.s.transition(pid, "trial", "go", trial_started_at=1.0)
        if to == "promoted":
            self.s.transition(pid, "awaiting_you", "numbers")
        self.s.transition(pid, to, "numbers")
        return pid

    def leftovers(self):
        """Worktrees besides the main checkout, and improve branches."""
        wts = [l for l in self.git("worktree", "list", "--porcelain").splitlines() if l.startswith("worktree ")][1:]
        return wts, self.git("branch", "--list", "improve/*", "--format=%(refname:short)").split()


class ApplyTest(Base):
    def test_low_kept_gives_one_commit_with_subject_trailers_and_only_its_target(self):
        # mutation: the build also edits other.txt, stages with `git add -A` and skips the target check -> name-only lists two paths
        pid = self.kept()
        self.assertEqual(self.s.get(pid)["class"], "low")
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "applied")
        self.assertEqual(self.count(before), 1)
        msg = self.git("log", "-1", "--format=%B", "main").splitlines()
        self.assertEqual(msg[0], f"improve(procedure): {pid} Better words")
        self.assertIn(f"Proposal: {pid}", msg)
        self.assertIn(f"Engine-Step: improve:{pid}@{before}", msg)
        self.assertEqual(self.git("diff", "--name-only", before, "main").split(), ["docs/foo.md"])
        self.assertEqual(len(self.git("rev-list", "--parents", "-n", "1", "main").split()), 2)
        self.assertEqual((self.repo / "docs/foo.md").read_text(), "new\n")
        row = self.s.get(pid)
        self.assertEqual((row["state"], row["commit_sha"]), ("kept", self.head()))
        ev = self.events("improve")[-1]
        self.assertEqual((ev["proposal"], ev["from"], ev["to"], ev["reason"]), (pid, "kept", "kept", "applied"))
        self.assertEqual(ev["rows"][0]["row"]["commit_sha"], self.head())
        self.assertEqual(self.leftovers(), ([], []))

    def test_apply_again_after_a_crash_before_the_state_write_makes_no_second_commit(self):
        # mutation: drop the trailer lookup on main (_landed) -> a second commit attempt; the patch no longer applies -> `stale`, state `rejected`
        pid = self.kept()
        before = self.head()
        with mock.patch.object(A, "_record", side_effect=RuntimeError("crash")):
            self.assertEqual(A.apply(self.s, pid), "refused: RuntimeError: crash")   # apply never raises
        self.assertEqual(self.count(before), 1)
        self.assertIsNone(self.s.get(pid)["commit_sha"])
        head = self.head()
        self.assertEqual(A.apply(self.s, pid), "applied")
        self.assertEqual(self.head(), head)
        self.assertEqual(self.count(before), 1)
        self.assertEqual((self.s.get(pid)["state"], self.s.get(pid)["commit_sha"]), ("kept", head))
        self.assertEqual(A.apply(self.s, pid), "applied")   # and with the sha stored: nothing at all
        self.assertEqual(self.head(), head)
        self.assertEqual(self.leftovers(), ([], []))

    def test_main_moved_since_the_trial_the_commit_is_rebased_onto_it(self):
        pid = self.kept()
        (self.repo / "other.txt").write_text("moved\n")
        self.git("commit", "-q", "-am", "main moves")
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "applied")
        self.assertEqual(self.count(before), 1)
        self.assertEqual(self.git("rev-parse", "main^").strip(), before)

    def test_live_checkout_mid_change_no_commit_state_unchanged_one_waiting_event(self):
        # mutation: treat exit 3 as merged -> commit_sha is set and no improve_waiting event exists
        pid = self.kept()
        before, row = self.head(), self.s.get(pid)
        (self.repo / "other.txt").write_text("half an edit\n")
        self.assertEqual(A.apply(self.s, pid), "waiting")
        self.assertEqual(self.head(), before)
        self.assertEqual(self.s.get(pid), row)
        w = self.events("improve_waiting")
        self.assertEqual(len(w), 1)
        self.assertEqual((w[0]["proposal"], w[0]["key"]), (pid, f"improve:{pid}@{before}"))
        self.assertEqual((self.repo / "other.txt").read_text(), "half an edit\n")
        # the next tick: the checkout is clean again and the same branch lands
        self.git("checkout", "-q", "--", "other.txt")
        self.assertEqual(A.sweep_apply(self.s), {"applied": 1})
        self.assertEqual(self.count(before), 1)
        self.assertIn(f"Engine-Step: improve:{pid}@{before}", self.git("log", "-1", "--format=%B", "main").splitlines())
        self.assertEqual(len(self.events("improve_waiting")), 1)
        self.assertEqual(A.sweep_apply(self.s), {})   # idempotent: nothing left to apply, no second commit
        self.assertEqual(self.count(before), 1)

    def test_kept_proposal_touching_a_protected_path_is_refused_by_the_engine(self):
        # the class is forced to low, as if the protected list had gained the path after the proposal was classed
        pid = self.kept(patch=ORCH, target="claude/orchestrator.md")
        c = self.s._conn()
        c.execute("UPDATE proposals SET class = 'low' WHERE id = ?", (pid,))
        c.close()
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "refused: protected path claude/orchestrator.md")
        self.assertEqual(self.head(), before)
        self.assertIsNone(self.s.get(pid)["commit_sha"])
        self.assertEqual(self.events("improve_refused")[0]["why"], "protected path claude/orchestrator.md")

    def test_protected_class_is_never_applied(self):
        pid = self.kept(patch=ORCH, target="claude/orchestrator.md", to="promoted")
        self.assertEqual(self.s.get(pid)["class"], "protected")
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "skipped")
        self.assertEqual(self.head(), before)
        self.assertEqual(self.leftovers(), ([], []))

    def test_stale_patch_goes_to_rejected_from_kept_and_promoted_and_nothing_lands(self):
        # lead ruling: `reverted` means a commit landed and was undone; a stale patch is `rejected` from every state
        # mutation: _stale moves a kept row to `reverted` -> ("reverted", ...) != ("rejected", ...)
        prom = self.kept(patch="--- a/other.txt\n+++ b/other.txt\n@@ -1 +1 @@\n-o\n+p\n", target="other.txt", to="promoted")
        (self.repo / "other.txt").write_text("rewritten\n")
        self.git("commit", "-q", "-am", "main rewrote other")
        self.assertEqual(A.apply(self.s, prom), "stale")
        self.assertEqual((self.s.get(prom)["state"], self.s.get(prom)["reason"]), ("rejected", "stale patch"))
        pid = self.kept()
        (self.repo / "docs/foo.md").write_text("rewritten\n")
        self.git("commit", "-q", "-am", "main rewrote it")
        before = self.head()
        self.assertFalse(A.applies(self.s, pid))
        self.assertEqual(A.apply(self.s, pid), "stale")
        self.assertEqual(self.head(), before)
        row = self.s.get(pid)
        self.assertEqual((row["state"], row["reason"], row["commit_sha"]), ("rejected", "stale patch", None))
        self.assertEqual(self.leftovers(), ([], []))

    def test_stale_patch_in_trial_goes_to_rejected(self):
        pid = self.s.insert("manual", "procedure", "docs/foo.md", PROSE, EV)
        self.s.transition(pid, "trial", "go", trial_started_at=1.0)
        self.assertTrue(A.applies(self.s, pid))
        (self.repo / "docs/foo.md").write_text("rewritten\n")
        self.git("commit", "-q", "-am", "main rewrote it")
        self.assertEqual(A.reject_if_stale(self.s, pid), True)
        self.assertEqual((self.s.get(pid)["state"], self.s.get(pid)["reason"]), ("rejected", "stale patch"))

    def test_patch_touching_a_second_path_is_stale(self):
        two = PROSE + "--- a/other.txt\n+++ b/other.txt\n@@ -1 +1 @@\n-o\n+changed\n"
        pid = self.kept(patch=two)
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "stale")
        self.assertEqual(self.head(), before)

    def test_not_kept_or_promoted_is_skipped(self):
        pid = self.s.insert("manual", "procedure", "docs/foo.md", PROSE, EV)
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "skipped")
        self.assertEqual(self.head(), before)

    def test_through_the_real_bin_tmux_ctl_outside_tmux(self):
        # no stub: bin/tmux-ctl of this checkout dispatches `engine merge-branch`, and the engine calls it back for `improve show`
        pid = self.kept()
        before = self.head()
        env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE", "TC_TMUX_CTL", "TC_PROJECT", "TC_SESSION")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(A.apply(self.s, pid), "applied")
        self.assertEqual(self.count(before), 1)
        self.assertEqual(self.s.get(pid)["commit_sha"], self.head())

    def test_the_tick_hook_is_this_apply(self):
        import improve_eval
        self.assertIs(improve_eval.load_hooks()["apply"], A.apply)


class RevertTest(Base):
    def applied(self, **kw):
        pid = self.kept(**kw)
        self.assertEqual(A.apply(self.s, pid), "applied")
        return pid

    def test_revert_creates_one_revert_commit_with_the_trailers(self):
        # mutation: skip the amend that adds the trailers -> the engine refuses the branch (no Proposal trailer)
        pid = self.applied()
        applied, before = self.s.get(pid)["commit_sha"], self.head()
        sha = A.revert(self.s, pid)
        self.assertEqual(self.count(before), 1)
        self.assertEqual(sha, self.head())
        msg = self.git("log", "-1", "--format=%B", "main").splitlines()
        self.assertEqual(msg[0], f'Revert "improve(procedure): {pid} Better words"')
        self.assertIn(f"This reverts commit {applied}.", msg)
        self.assertIn(f"Proposal: {pid}", msg)
        self.assertIn(f"Engine-Step: improve:{pid}:revert@{before}", msg)
        self.assertEqual((self.repo / "docs/foo.md").read_text(), "old\n")
        row = self.s.get(pid)
        self.assertEqual((row["state"], row["commit_sha"]), ("reverted", applied))
        evs = [e for e in self.events("improve") if e["to"] == "reverted"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(self.leftovers(), ([], []))

    def test_revert_refuses_no_commit_and_protected(self):
        # mutation: drop the commit_sha check -> `git revert None` fails with another message
        pid = self.kept()
        with self.assertRaises(A.ApplyError) as cm:
            A.revert(self.s, pid)
        self.assertEqual(str(cm.exception), "no commit")
        prot = self.kept(patch=ORCH, target="claude/orchestrator.md", to="promoted")
        c = self.s._conn()
        c.execute("UPDATE proposals SET commit_sha = ? WHERE id = ?", (self.head(), prot))
        c.close()
        before = self.head()
        with self.assertRaises(A.ApplyError) as cm:
            A.revert(self.s, prot)
        self.assertEqual(str(cm.exception), "protected")
        self.assertEqual(self.head(), before)
        self.assertEqual(self.s.get(prot)["state"], "promoted")

    def test_cli_revert_prints_the_sha_and_refuses_in_one_line(self):
        pid = self.applied()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = improve.main(["--project", "proj", "revert", pid])
        self.assertEqual((rc, out.getvalue().strip()), (0, f"reverted {pid}: {self.head()}"))
        other = self.kept(patch="--- a/other.txt\n+++ b/other.txt\n@@ -1 +1 @@\n-o\n+p\n", target="other.txt")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = improve.main(["--project", "proj", "revert", other])
        self.assertEqual((rc, err.getvalue().strip()), (1, "improve: revert: no commit"))

    def test_revert_waits_for_a_busy_checkout_then_lands_once(self):
        pid = self.applied()
        before = self.head()
        (self.repo / "other.txt").write_text("half\n")
        with self.assertRaises(A.ApplyError) as cm:
            A.revert(self.s, pid)
        self.assertIn("live checkout is mid-change", str(cm.exception))
        self.assertEqual((self.head(), self.s.get(pid)["state"]), (before, "kept"))
        self.git("checkout", "-q", "--", "other.txt")
        A.revert(self.s, pid)
        self.assertEqual(self.count(before), 1)
        self.assertEqual(self.s.get(pid)["state"], "reverted")


class RetireTest(Base):
    def test_retire_then_revert_restores_the_file_byte_for_byte(self):
        # mutation: the revert commit rewrites the restored file through a latin-1 text round trip -> the sha256 differs (the é line)
        target = "claude/skills/x/SKILL.md"
        want = sha256(self.repo / target)
        pid = self.kept(patch="--- a/claude/skills/x/SKILL.md\n+++ /dev/null\n", target=target, kind="retire", title="Retire x")
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "applied")
        self.assertEqual(self.count(before), 1)
        self.assertFalse((self.repo / target).exists())
        moved = self.repo / ".superpowers/improve/retired" / pid / target
        self.assertEqual(sha256(moved), want)
        self.assertEqual(sorted(self.git("diff", "--name-only", "--no-renames", before, "main").split()),
                         sorted([target, f".superpowers/improve/retired/{pid}/{target}"]))
        ev = self.events("improve")[-1]
        self.assertEqual(ev["undo"], f"tmux-ctl improve revert {pid}")
        A.revert(self.s, pid)
        self.assertEqual(sha256(self.repo / target), want)
        self.assertFalse(moved.exists())
        self.assertEqual(self.s.get(pid)["state"], "reverted")

    def test_retire_with_a_gitignored_destination_deletes_in_the_commit_and_keeps_a_local_copy(self):
        (self.repo / ".gitignore").write_text(".superpowers/\n")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "ignore")
        target = "claude/skills/x/SKILL.md"
        want = sha256(self.repo / target)
        pid = self.kept(patch=None, target=target, kind="retire", title="Retire x")
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "applied")
        self.assertEqual(self.git("diff", "--name-only", before, "main").split(), [target])
        self.assertEqual(sha256(self.repo / ".superpowers/improve/retired" / pid / target), want)
        self.assertEqual(self.git("status", "--porcelain").strip(), "")
        A.revert(self.s, pid)
        self.assertEqual(sha256(self.repo / target), want)

    def test_retire_a_section_comments_it_out_with_the_marker_and_revert_restores_it(self):
        want = sha256(self.repo / "docs/notes.md")
        pid = self.kept(patch=None, target="docs/notes.md#Old rule", kind="retire", title="Retire old rule")
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "applied")
        self.assertEqual(self.git("diff", "--name-only", before, "main").split(), ["docs/notes.md"])
        self.assertEqual((self.repo / "docs/notes.md").read_text(),
                         f"# Notes\n\nintro\n\n<!-- retired: {pid}\n## Old rule\n\nnever do this\n\n### Detail\n\nmore\n\n-->\n## Other\n\nstays\n")
        A.revert(self.s, pid)
        self.assertEqual(sha256(self.repo / "docs/notes.md"), want)

    def test_retire_of_a_missing_target_or_heading_is_stale(self):
        pid = self.kept(patch=None, target="docs/notes.md#No such heading", kind="retire")
        self.assertEqual(A.apply(self.s, pid), "stale")
        pid = self.kept(patch=None, target="docs/gone.md", kind="retire")
        self.assertEqual(A.apply(self.s, pid), "stale")


class DraftTest(Base):
    def proposed(self):
        pid = self.s.insert("manual", "rule", "claude/orchestrator.md", ORCH, EV, title="Looser rules")
        self.assertEqual(self.s.get(pid)["class"], "protected")
        return pid

    def test_protected_proposal_yields_the_draft_on_its_branch_only(self):
        # mutation: fast-forward main to the draft branch after building it -> `git log main -- docs/superpowers/specs/drafts/` is not empty
        pid = self.proposed()
        before = self.head()
        rel = A.draft(self.s, pid)
        self.assertEqual(self.git("log", "main", "--format=%H", "--", "docs/superpowers/specs/drafts/").strip(), "")
        self.assertRegex(rel, rf"^docs/superpowers/specs/drafts/\d{{4}}-\d\d-\d\d-improve-{pid}\.md$")
        self.assertEqual(self.head(), before)
        self.assertFalse((self.repo / rel).exists())
        self.assertEqual(self.git("status", "--porcelain").strip(), "")
        self.assertEqual(self.git("diff", "--name-only", "main", f"improve/{pid}").split(), [rel])
        text = self.git("show", f"improve/{pid}:{rel}")
        self.assertIn(f"# Improve {pid}: Looser rules", text)
        self.assertIn("claude/orchestrator.md", text)
        self.assertIn('{"type": "run", "ref": "r1"}', text)
        self.assertIn("```diff\n" + ORCH + "```", text)
        row = self.s.get(pid)
        self.assertEqual((row["state"], row["reason"]), ("drafted", "protected"))
        self.assertEqual(self.leftovers(), ([], [f"improve/{pid}"]))
        self.assertEqual(A.draft(self.s, pid), rel)   # again: the same draft, no second commit
        self.assertEqual(int(self.git("rev-list", "--count", f"main..improve/{pid}")), 1)

    def test_sweep_drafts_takes_proposed_protected_rows_only(self):
        pid = self.proposed()
        low = self.s.insert("manual", "procedure", "docs/foo.md", PROSE, EV)
        adapter = self.s.insert("scout", "spec", "docs/superpowers/specs/drafts/x.md", None, EV, state="drafted", reason="adapter draft")
        self.assertEqual(A.sweep_drafts(self.s), {"drafted": 1})
        self.assertEqual([self.s.get(i)["state"] for i in (pid, low, adapter)], ["drafted", "proposed", "drafted"])
        self.assertEqual(A.sweep_drafts(self.s), {})
        self.assertEqual(int(self.git("rev-list", "--count", f"main..improve/{pid}")), 1)   # never drafted twice
        self.assertEqual(len([e for e in self.events("improve") if e["to"] == "drafted" and e["proposal"] == pid]), 1)

    def test_approve_draft_merges_the_branch_adds_the_ideas_line_and_tells_the_lead(self):
        pid = self.proposed()
        rel = A.draft(self.s, pid)
        before, done, lines = self.head(), [], []
        self.assertEqual(A.approve_draft(self.s, pid, add_line=lines.append, add_done=lambda *a: done.append(a)), "approved")
        self.assertEqual(self.count(before), 1)
        self.assertEqual(self.git("diff", "--name-only", before, "main").split(), [rel])
        self.assertTrue((self.repo / rel).is_file())
        self.assertEqual((self.repo / "claude/orchestrator.md").read_text(), "rules\n")   # the draft, never the patch
        row = self.s.get(pid)
        self.assertEqual((row["state"], row["commit_sha"]), ("promoted", self.head()))
        self.assertEqual(done, [("proj", "improve: Looser rules", rel)])
        self.assertEqual(lines, [f"[Improve] approved: {rel}"])
        self.assertEqual(self.leftovers(), ([], []))
        with self.assertRaises(A.ApplyError):
            A.approve_draft(self.s, pid, add_done=lambda *a: done.append(a))
        self.assertEqual(len(done), 1)

    def test_approve_draft_waits_for_a_busy_checkout_and_refuses_adapter_drafts(self):
        pid = self.proposed()
        A.draft(self.s, pid)
        before = self.head()
        (self.repo / "other.txt").write_text("half\n")
        done = []
        self.assertEqual(A.approve_draft(self.s, pid, add_done=lambda *a: done.append(a)), "waiting")
        self.assertEqual((self.head(), self.s.get(pid)["state"], done), (before, "drafted", []))
        self.assertEqual(len(self.events("improve_waiting")), 1)
        adapter = self.s.insert("scout", "spec", "docs/superpowers/specs/drafts/x.md", None, EV, state="drafted", reason="adapter draft")
        with self.assertRaises(A.ApplyError) as cm:
            A.approve_draft(self.s, adapter, add_done=lambda *a: done.append(a))
        self.assertEqual(str(cm.exception), "not a protected draft")


OTHER = "--- a/other.txt\n+++ b/other.txt\n@@ -1 +1 @@\n-o\n+p\n"


class NeverRaisesTest(Base):
    def test_apply_returns_refused_with_one_event_and_the_row_unchanged_when_the_build_fails(self):
        # mutation: apply without the catch -> OSError leaves apply
        pid = self.kept()
        before, row = self.head(), self.s.get(pid)
        with mock.patch.object(A, "_build", side_effect=OSError("disk full")):
            self.assertEqual(A.apply(self.s, pid), "refused: OSError: disk full")
        self.assertEqual((self.head(), self.s.get(pid)), (before, row))
        ev = self.events("improve_refused")
        self.assertEqual([(e["proposal"], e["why"]) for e in ev], [(pid, "OSError: disk full")])
        self.assertEqual(A.sweep_apply(self.s), {"applied": 1})   # the next tick's sweep retries it
        self.assertEqual(self.count(before), 1)

    def test_apply_of_an_unknown_proposal_and_a_failing_git_are_refused_not_raised(self):
        self.assertEqual(A.apply(self.s, "P99"), "refused: ApplyError: no proposal P99")
        pid = self.kept()
        with mock.patch.dict(os.environ, {"TC_IMPROVE_REPO": str(self.tmp / "no-such-repo")}):
            self.assertRegex(A.apply(self.s, pid), r"^refused: ")
        self.assertEqual(self.s.get(pid)["state"], "kept")

    def test_retire_of_a_section_in_a_file_that_is_not_utf8_is_stale(self):
        # mutation: decode without the catch -> UnicodeDecodeError (as `refused`), the row stays kept and every sweep retries it
        (self.repo / "docs/latin.md").write_bytes(b"# T\n\n## Old rule\n\ncaf\xe9\n")
        self.git("add", "docs/latin.md")
        self.git("commit", "-q", "-m", "latin")
        pid = self.kept(patch=None, target="docs/latin.md#Old rule", kind="retire")
        before = self.head()
        self.assertEqual(A.apply(self.s, pid), "stale")
        self.assertEqual((self.head(), self.s.get(pid)["state"], self.s.get(pid)["reason"]), (before, "rejected", "stale patch"))
        self.assertEqual(self.leftovers(), ([], []))

    def test_the_tick_finishes_the_other_proposals_and_its_later_steps_when_one_apply_fails(self):
        # mutation: apply without the catch -> the tick dies in the hook after the first `kept`: the second trial is never judged
        import improve_eval as E
        import improve_trials as T
        first = self.s.insert("manual", "procedure", "docs/foo.md", PROSE, EV, title="First")
        second = self.s.insert("manual", "procedure", "other.txt", OTHER, EV, title="Second")
        runs = []
        for pid, pre in ((first, "a"), (second, "b")):
            self.s.transition(pid, "trial", "go", trial_started_at=1.0, trial_len=5)
            t, c, i = [], [], 0
            while len(t) < 5 or len(c) < 5:
                sp = f"{pre}{i}"
                i += 1
                (t if T.in_trial(sp, pid) else c).append(sp)
            runs += [F.run(sp, budget=1, variants=[pid], tokens={"total": 500}) for sp in t[:5]]
            runs += [F.run(sp, budget=1, tokens={"total": 1000}) for sp in c[:5]]
        before, real, later = self.head(), A._build, []

        def build(repo, project, branch, make):
            if branch == f"improve/{first}":
                raise OSError("disk full")
            return real(repo, project, branch, make)
        hooks = {"apply": A.apply, "pick": lambda *a: later.append("pick") or [], "digest": lambda *a: later.append("digest") or {}}
        with mock.patch.object(A, "_build", side_effect=build):
            out = E.tick(self.s, "proj", runs, [], configs={"base": {"baseline": True}}, hooks=hooks, adapters=lambda *a, **k: {})
        self.assertEqual(out["trials"]["kept"], 2, out)
        self.assertEqual([self.s.get(p)["state"] for p in (first, second)], ["kept", "kept"])
        self.assertEqual(later, ["pick", "digest"])
        self.assertIsNone(self.s.get(first)["commit_sha"])
        self.assertEqual(self.s.get(second)["commit_sha"], self.head())
        self.assertEqual(self.count(before), 1)
        self.assertEqual([e["proposal"] for e in self.events("improve_refused")], [first])

    def test_sweep_drafts_counts_an_unexpected_error_and_goes_on(self):
        one = self.s.insert("manual", "rule", "claude/orchestrator.md", ORCH, EV, title="One")
        two = self.s.insert("manual", "rule", "claude/worker.md", ORCH.replace("orchestrator", "worker"), EV, title="Two")
        real = A._build

        def build(repo, project, branch, make):
            if branch == f"improve/{one}":
                raise OSError("disk full")
            return real(repo, project, branch, make)
        with mock.patch.object(A, "_build", side_effect=build):
            self.assertEqual(A.sweep_drafts(self.s), {"error": 1, "drafted": 1})
        self.assertEqual([self.s.get(p)["state"] for p in (one, two)], ["proposed", "drafted"])


class SweepWaitingTest(Base):
    def test_a_waiting_commit_retries_twice_without_a_duplicate(self):
        # the checkout stays busy over two sweeps: one branch, one key, no commit; then it lands once
        pid = self.kept()
        before = self.head()
        (self.repo / "other.txt").write_text("half\n")
        self.assertEqual(A.sweep_apply(self.s), {"waiting": 1})
        tip = self.head(f"improve/{pid}")
        self.assertEqual(A.sweep_apply(self.s), {"waiting": 1})
        self.assertEqual((self.head(), self.head(f"improve/{pid}")), (before, tip))
        self.assertEqual({w["key"] for w in self.events("improve_waiting")}, {f"improve:{pid}@{before}"})
        self.git("checkout", "-q", "--", "other.txt")
        self.assertEqual(A.sweep_apply(self.s), {"applied": 1})
        self.assertEqual(A.sweep_apply(self.s), {})
        self.assertEqual(self.count(before), 1)


class TickCliTest(Base):
    def test_improve_tick_retries_a_waiting_apply_and_drafts_protected_proposals(self):
        pid = self.kept()
        prot = self.s.insert("manual", "rule", "claude/orchestrator.md", ORCH, EV, title="Looser rules")
        before = self.head()
        out = io.StringIO()
        with mock.patch.object(improve.improve_eval, "tick", return_value={"observe": {"records": 0}}), \
                mock.patch.object(improve.metrics, "read_log", return_value=([], [])), redirect_stdout(out):
            rc = improve.main(["--project", "proj", "tick"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().splitlines(), ['apply {"applied": 1}', 'observe {"records": 0}', 'drafts {"drafted": 1}'])
        self.assertEqual(self.count(before), 1)
        self.assertEqual(self.s.get(pid)["commit_sha"], self.head())
        self.assertEqual(self.s.get(prot)["state"], "drafted")


if __name__ == "__main__":
    unittest.main()
