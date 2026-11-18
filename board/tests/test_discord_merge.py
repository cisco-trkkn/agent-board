"""discord_merge: merge evidence from a fixture git repo (temp dir), request(), on_merge() and the CLI main().
Scratch TC_STATE; the repo is built with `git -c user.name=t -c user.email=t@t`; no Discord, no live outbox.
Each guard test names the mutation that must make it fail."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_feed as df  # noqa: E402
import discord_merge as dm  # noqa: E402
import discord_ops as ops  # noqa: E402
import tc_env  # noqa: E402

NOW = 1_800_000_000.0


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"TC_STATE": self.tmp.name + "/state", "HOME": self.tmp.name + "/home"})
        p.start()
        self.addCleanup(p.stop)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "base.txt").write_text("base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        git(self.repo, "checkout", "-q", "-b", "feat")
        self.ops = tc_env.ops_dir()
        self.lines = []
        self.add = lambda p, t: self.lines.append((p, t))

    def configure(self):
        self.ops.mkdir(parents=True, exist_ok=True)
        (self.ops / "bridge.json").write_text(json.dumps({"command_center": "C", "approvals": "A", "user": "U1"}))
        (self.ops / "access.json").write_text(json.dumps({"allowFrom": ["U1"]}))

    def commit_files(self, files, msg="work"):
        for name, body in files.items():
            p = self.repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body if isinstance(body, bytes) else body.encode())
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", msg)

    def request(self, task="7", spec="spec-x", branch="feat", findings=(), tests="12 passed", verdict="Approved"):
        return dm.request("proj", str(self.repo), task, spec, branch, "main", tests, verdict, list(findings), NOW)

    def feed(self):
        p = tc_env.feed_path("proj")
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def evfile(self, task="7"):
        return json.loads((self.ops / "evidence" / f"proj-{task}.json").read_text())


class Evidence(Base):
    def test_many_files_cut_to_25_stat_lines_and_more(self):
        self.commit_files({f"f{i:02d}.txt": "x\n" for i in range(30)})
        ev = dm.evidence(str(self.repo), "feat", "main")
        self.assertEqual(len(ev["files"]), 30)
        text = dm.post_text("spec-x", "feat", "main", ev, "12 passed", "Approved", [])
        lines = text.split("\n")
        self.assertEqual(lines[0], "merge approval: spec-x")
        self.assertEqual(lines[1], f"feat → main @ {ev['sha'][:8]}")
        stat = [l for l in lines[2:] if " | " in l]
        self.assertEqual(len(stat), 25)   # mutation: drop the [:25] cut -> 30 stat lines
        self.assertIn("… 5 more", lines)
        self.assertEqual(lines[-3:], ["tests: 12 passed", "final review: Approved", "diff: 30 files, +30 −0"])
        self.assertEqual(lines[-1], "diff: 30 files, +30 −0")
        self.assertLessEqual(len(text), 1900)

    def test_text_layout_with_findings_cut_to_200(self):
        self.commit_files({"a.txt": "1\n2\n"})
        ev = dm.evidence(str(self.repo), "feat", "main")
        text = dm.post_text("s", "feat", "main", ev, "T", "V", ["short", "y" * 300])
        lines = text.split("\n")
        i = lines.index("final review: V")
        self.assertEqual(lines[i - 1], "tests: T")
        self.assertEqual(lines[i + 1], "short")
        self.assertEqual(lines[i + 2], "y" * 200)   # mutation: drop the 200 cut
        self.assertEqual(lines[-1], "diff: 1 files, +2 −0")

    def test_text_cut_to_1900(self):
        self.commit_files({"a.txt": "1\n"})
        ev = dm.evidence(str(self.repo), "feat", "main")
        text = dm.post_text("s", "feat", "main", ev, "T", "V", ["z" * 200] * 20)
        self.assertEqual(len(text), 1900)

    def test_binary_file_counts_zero(self):
        self.commit_files({"bin.dat": bytes(range(256)) * 4, "a.txt": "1\n"})
        ev = dm.evidence(str(self.repo), "feat", "main")
        by = {f["path"]: f for f in ev["files"]}
        self.assertEqual((by["bin.dat"]["add"], by["bin.dat"]["del"]), (0, 0))   # mutation: int('-') -> ValueError
        self.assertEqual((by["a.txt"]["add"], by["a.txt"]["del"]), (1, 0))

    def test_long_diff_cut_with_note_short_diff_whole(self):
        self.commit_files({"big.txt": "line of text number\n" * 200, "small.txt": "x\n"})
        ev = dm.evidence(str(self.repo), "feat", "main")
        d = ev["diffs"]["big.txt"]
        self.assertTrue(d.endswith("\n… too long, see board"))
        self.assertEqual(len(d), 1800 + len("\n… too long, see board"))
        self.assertNotIn("too long", ev["diffs"]["small.txt"])

    def test_sha_is_rev_parse_and_rename_listed_by_new_path(self):
        self.commit_files({"old.txt": "keep\n" * 5})
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--ff-only", "feat")
        git(self.repo, "checkout", "-q", "-b", "ren")
        git(self.repo, "mv", "old.txt", "new.txt")
        git(self.repo, "commit", "-q", "-m", "mv")
        ev = dm.evidence(str(self.repo), "ren", "main")
        self.assertEqual(ev["sha"], git(self.repo, "rev-parse", "ren"))
        self.assertEqual(sorted(f["path"] for f in ev["files"]), ["new.txt", "old.txt"])   # --no-renames: no "old => new" path


class Request(Base):
    def test_writes_evidence_and_one_feed_event(self):
        self.configure()
        self.commit_files({"a.txt": "1\n"})
        sha = git(self.repo, "rev-parse", "feat")
        r = self.request(findings=["f1"])
        f = self.evfile()
        self.assertEqual((f["sha"], f["project"], f["task"], f["spec"], f["branch"], f["target"]), (sha, "proj", "7", "spec-x", "feat", "main"))
        self.assertEqual(f["files"], [{"path": "a.txt", "add": 1, "del": 0}])
        self.assertIn("a.txt", f["diffs"])
        self.assertEqual(oct((self.ops / "evidence" / "proj-7.json").stat().st_mode & 0o777), "0o600")
        (ev,) = self.feed()
        self.assertEqual((ev["kind"], ev["tier"], ev["spec"], ev["project"], ev["ts"]), ("merge_approval", "decision", "spec-x", "proj", NOW))
        self.assertEqual(ev["refs"]["task"], "7")
        self.assertEqual(ev["refs"]["sha"], sha)
        self.assertEqual(ev["refs"]["evidence"], str(self.ops / "evidence" / "proj-7.json"))
        self.assertTrue(ev["text"].startswith("merge approval: spec-x"))
        self.assertTrue(r["ops"])

    def test_without_ops_still_posts_the_feed_event(self):
        self.commit_files({"a.txt": "1\n"})
        r = self.request()
        self.assertFalse(r["ops"])
        self.assertEqual(len(self.feed()), 1)
        self.assertFalse((self.ops / "evidence").exists())

    def test_ops_key_for_the_event_carries_the_sha(self):
        self.assertEqual(df.merge_key({"task": "7", "sha": "abcdef0123456789"}), "merge:7:abcdef01")
        self.assertEqual(df.merge_key({"task": "7"}), "merge:7")

    def test_bad_values_write_nothing(self):
        self.configure()
        self.commit_files({"a.txt": "1\n"})
        for kw in ({"branch": "-x"}, {"branch": "a b"}, {"branch": "$(id)"}, {"branch": "a;b"}, {"branch": "a..b"}, {"branch": ""},
                   {"task": "../x"}, {"task": ""}, {"spec": ""}):
            with self.assertRaises(ValueError, msg=str(kw)):
                self.request(**kw)
        with self.assertRaises(ValueError):
            dm.request("proj", str(self.repo), "7", "s", "feat", "-main", "t", "v", [], NOW)
        with self.assertRaises(ValueError):
            dm.request("../p", str(self.repo), "7", "s", "feat", "main", "t", "v", [], NOW)
        self.assertEqual(self.feed(), [])
        self.assertFalse((self.ops / "evidence").exists())

    def test_every_git_call_is_an_argv_list_with_double_dash_before_paths(self):
        self.commit_files({"a.txt": "1\n"})
        calls = []
        real = subprocess.run

        def spy(args, *a, **kw):
            calls.append((args, kw))
            return real(args, *a, **kw)
        with mock.patch.object(dm.subprocess, "run", spy):
            dm.evidence(str(self.repo), "feat", "main")
        self.assertTrue(calls)
        for args, kw in calls:
            self.assertIsInstance(args, list)   # mutation: build a shell string -> fails
            self.assertFalse(kw.get("shell"))
            if "diff" in args and "a.txt" in args:
                self.assertEqual(args[args.index("a.txt") - 1], "--")
            if "diff" in args:
                self.assertIn("--", args)

    def test_a_branch_named_like_a_command_is_refused_and_runs_nothing(self):
        marker = Path(self.tmp.name) / "PWNED"
        with self.assertRaises(ValueError):
            dm.evidence(str(self.repo), f"feat;touch {marker}", "main")
        self.assertFalse(marker.exists())


class OnMerge(Base):
    def posted(self):
        self.configure()
        self.commit_files({"a.txt": "1\n"})
        r = self.request()
        return r["src_key"]

    def rec(self, src):
        return {"project": "proj", "kind": "merge", "src_key": src, "spec": "spec-x", "title": "t", "link": "", "ts": NOW}

    def test_equal_sha_sends_the_lead_line(self):
        src = self.posted()
        out = dm.on_merge("proj", src, self.rec(src), self.add, NOW + 5)
        self.assertEqual(self.lines, [("proj", "[Discord] merge approved for spec-x")])
        self.assertEqual(out, {"result": "merged", "text": "merge approved — sent to the lead"})
        self.assertEqual(len(self.feed()), 1)

    def test_changed_branch_edits_and_posts_fresh_request(self):
        src = self.posted()
        self.commit_files({"b.txt": "2\n"}, "more")
        new = git(self.repo, "rev-parse", "feat")
        out = dm.on_merge("proj", src, self.rec(src), self.add, NOW + 5)
        self.assertEqual(self.lines, [])   # mutation: send the merge line anyway
        self.assertEqual(out, {"result": "stale", "text": "branch changed since this was posted"})
        evs = self.feed()
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[1]["refs"]["sha"], new)
        self.assertEqual(self.evfile()["sha"], new)
        self.assertEqual(sorted(f["path"] for f in self.evfile()["files"]), ["a.txt", "b.txt"])
        self.assertNotEqual(df.merge_key(evs[0]["refs"]), df.merge_key(evs[1]["refs"]))

    def test_merge_request_from_a_spec_worktree_survives_its_removal(self):
        # I1: --repo omitted, run inside a linked worktree; the stored repo must be the main checkout
        self.configure()
        git(self.repo, "checkout", "-q", "main")
        wt = Path(self.tmp.name) / "wt"
        git(self.repo, "worktree", "add", "-q", "-b", "spec", str(wt))
        (wt / "w.txt").write_text("w\n")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "w")
        cwd = os.getcwd()
        os.chdir(wt)
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                rc = dm.main(["request", "--project", "proj", "--task", "7", "--spec", "spec-x", "--branch", "spec",
                              "--tests", "ok", "--verdict", "Approved"])
        finally:
            os.chdir(cwd)
        self.assertEqual(rc, 0)
        self.assertEqual(os.path.realpath(self.evfile()["repo"]), os.path.realpath(self.repo))
        git(self.repo, "worktree", "remove", "--force", str(wt))
        src = [e for e in self.feed() if e.get("kind") == "merge_approval"][-1]
        src = f"merge:7:{self.evfile()['sha'][:8]}"
        out = dm.on_merge("proj", src, self.rec(src), self.add, NOW + 5)
        self.assertEqual(out["result"], "merged")
        self.assertEqual(self.lines, [("proj", "[Discord] merge approved for spec-x")])

    def test_diffs_ignore_user_git_config_color_and_external_diff(self):
        # M1: a real git run with color.ui=always and diff.external set; the stored output must be plain
        self.commit_files({"a.txt": "1\n"})
        env = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "color.ui", "GIT_CONFIG_VALUE_0": "always",
               "GIT_CONFIG_KEY_1": "diff.external", "GIT_CONFIG_VALUE_1": "false"}
        with mock.patch.dict(os.environ, env):
            ev = dm.evidence(str(self.repo), "feat", "main")
        self.assertNotIn("\x1b", "".join(ev["stat"]) + ev["diffs"]["a.txt"])
        self.assertIn("+1", ev["diffs"]["a.txt"])

    def test_branch_gone_is_stale_without_a_new_request(self):
        src = self.posted()
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "branch", "-D", "feat")
        out = dm.on_merge("proj", src, self.rec(src), self.add, NOW + 5)
        self.assertEqual((out["result"], self.lines, len(self.feed())), ("stale", [], 1))
        self.assertIn("branch changed", out["text"])

    def test_missing_or_superseded_evidence_is_stale_and_sends_nothing(self):
        src = self.posted()
        (self.ops / "evidence" / "proj-7.json").unlink()
        out = dm.on_merge("proj", src, self.rec(src), self.add, NOW)
        self.assertEqual((out["result"], self.lines), ("stale", []))
        src2 = self.request()["src_key"]
        old = src.rsplit(":", 1)[0] + ":deadbeef"
        out = dm.on_merge("proj", old, self.rec(old), self.add, NOW)
        self.assertEqual((out["result"], self.lines), ("stale", []))
        self.assertIn("newer", out["text"])
        self.assertTrue(src2)

    def test_second_tap_is_unknown_through_discord_ops(self):
        # the click path: first tap merges, the record is popped, the second tap audits unknown and sends nothing
        src = self.posted()
        proj_dir = tc_env.discord_dir("proj")
        proj_dir.mkdir(parents=True)
        k = hashlib.sha1(("proj\0" + src).encode()).hexdigest()[:12]
        (self.ops / "ops-state.json").write_text(json.dumps({"approvals": {k: self.rec(src)}}))
        for n in (1, 2):
            (self.ops / "events").mkdir(exist_ok=True)
            (self.ops / "events" / f"{n}.json").write_text(json.dumps({"type": "click", "custom_id": f"ab:ops:merge:{k}", "user": "U1", "ts": NOW}))
            ops.consume(self.add, lambda argv: "", NOW, on_merge=dm.on_merge)
        audit = [json.loads(l) for l in (self.ops / "audit.jsonl").read_text().splitlines()]
        self.assertEqual([a["result"] for a in audit], ["merged", "unknown"])
        self.assertEqual(self.lines, [("proj", "[Discord] merge approved for spec-x")])
        self.assertEqual(ops._default_merge.__name__, "_default_merge")

    def test_default_on_merge_is_discord_merge(self):
        src = self.posted()
        out = ops._default_merge("proj", src, self.rec(src), self.add, NOW)
        self.assertEqual(out["result"], "merged")


class Cli(Base):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = dm.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    BASE = ["request", "--project", "proj", "--task", "7", "--spec", "spec-x", "--branch", "feat", "--tests", "12 passed", "--verdict", "OK"]

    def test_posted_with_ops(self):
        self.configure()
        self.commit_files({"a.txt": "1\n"})
        rc, out, _ = self.run_main(*self.BASE, "--repo", str(self.repo), "--finding", "f1", "--finding", "f2")
        self.assertEqual((rc, out), (0, "merge-request: posted spec-x\n"))
        self.assertIn("f2", self.feed()[0]["text"])

    def test_posted_without_ops_says_so(self):
        self.commit_files({"a.txt": "1\n"})
        rc, out, _ = self.run_main(*self.BASE, "--repo", str(self.repo))
        self.assertEqual((rc, out), (0, "merge-request: posted spec-x (ops bot not set up: project channel only)\n"))

    def test_repo_defaults_to_the_callers_toplevel(self):
        self.commit_files({"a.txt": "1\n"})
        old = os.getcwd()
        os.chdir(self.repo / "sub") if (self.repo / "sub").exists() else os.chdir(self.repo)
        self.addCleanup(os.chdir, old)
        rc, out, _ = self.run_main(*self.BASE)
        self.assertEqual(rc, 0)

    def test_bad_branch_rc_2_nothing_written_value_not_echoed(self):
        self.configure()
        secret = "MTIzNDU2.abcdef.ghijklmnopqrstuvwxyz0123456789ABCDEFG;x"
        rc, out, err = self.run_main("request", "--project", "proj", "--task", "7", "--spec", "s", "--branch", secret,
                                     "--tests", "t", "--verdict", "v", "--repo", str(self.repo))
        self.assertEqual(rc, 2)
        self.assertNotIn(secret, out + err)
        self.assertEqual(self.feed(), [])
        self.assertFalse((self.ops / "evidence").exists())

    def test_unknown_option_rc_2_without_echo(self):
        rc, out, err = self.run_main("request", "--nope", "SECRETVALUE")
        self.assertEqual(rc, 2)
        self.assertNotIn("SECRETVALUE", out + err)
        self.assertNotIn("--nope", out + err)


if __name__ == "__main__":
    unittest.main()
