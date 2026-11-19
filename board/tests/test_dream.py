"""dream.py: the nightly memory consolidation run, against the fake model board/tests/fixtures/dream/claude.
Every test points TC_CONTEXT_DIR, TC_STATE, HOME and TASK_OBSERVER_WORKSPACE at temp dirs (G14)."""
import contextlib
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import signal
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
import context  # noqa: E402
import dream  # noqa: E402
import dream_check  # noqa: E402
import dream_paths  # noqa: E402
import metrics  # noqa: E402

FAKE = HERE / "tests" / "fixtures" / "dream" / "claude"
REPO_OF_DREAM = HERE.parent
SECTIONS = ("Map", "How to run", "Gotchas", "Decisions")
SCRUBBED = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_MESSAGING_SOCKET",
            "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_CHILD_SESSION", "TMUX", "TMUX_PANE")


def core_text(project="p", n=8):
    out = [f"# {project}: shared agent context", "Last curated: 2026-11-01", ""]
    for s in SECTIONS:
        out.append(f"## {s}")
        for i in range(n):
            gone = f"board/gone-{s[0]}{i}.py"
            files = f"docs/real.txt, {gone}" if i % 2 else gone
            out.append(f"- {s} fact {i} {'x' * 250} (files: {files}) · 2026-11-{i + 1:02d}")
        out.append("")
    return "\n".join(out)


def sha(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


def listing(d):
    return sorted((str(p.relative_to(d)), p.stat().st_size, sha(p)) for p in Path(d).rglob("*") if p.is_file())


class DreamBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dreamtest."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.D = self.tmp / "ctx"
        self.D.mkdir()
        self.log = self.tmp / "fake.log"
        self.repo = self.tmp / "repo"
        self.make_repo(self.repo)
        env = {"TC_CONTEXT_DIR": str(self.D), "TC_STATE": str(self.tmp / "state"), "HOME": str(self.tmp / "home"),
               "TASK_OBSERVER_WORKSPACE": str(self.tmp / "obs"), "TC_TMUX": "/nonexistent/tmux",
               "TC_DREAM_CLAUDE": str(FAKE), "FAKE_DREAM_LOG": str(self.log)}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for k in ("TC_DREAM", "FAKE_DREAM_MODE", "FAKE_DREAM_SLEEP"):
            os.environ.pop(k, None)
        (self.tmp / "home").mkdir()
        self.core = self.D / "p.md"
        self.core.write_text(core_text())
        self.now = time.time()

    def make_repo(self, repo, metrics_log=False):
        (repo / "docs/superpowers/ledgers/2026-11-01-spec").mkdir(parents=True)
        (repo / "docs/superpowers/reports").mkdir(parents=True)
        (repo / "docs/real.txt").write_text("real\n")
        (repo / "docs/superpowers/ledgers/2026-11-01-spec/progress.md").write_text("Ruling: a\nline 2\n")
        (repo / "docs/superpowers/reports/r1.md").write_text("report\n")
        if metrics_log:
            (repo / "docs/superpowers/metrics").mkdir(parents=True)
            (repo / "docs/superpowers/metrics/runs.jsonl").write_text(json.dumps({"kind": "run", "batch": "b", "spec": "s"}) + "\n")
        for c in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                  ["add", "-A"], ["commit", "-qm", "init"]):
            subprocess.run(["git", "-C", str(repo)] + c, check=True, capture_output=True)

    def run_dream(self, *args, mode="good", now=None, root=True, project="p"):
        """-> (rc, stdout). Each call advances the clock one minute unless now is given."""
        if now is None:
            self.now += 60
            now = self.now
        os.environ["FAKE_DREAM_MODE"] = mode
        argv = ["run"] + ([project] if project else []) + list(args)
        if root:
            argv += ["--root", str(self.repo)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = dream.main(argv, now=now)
        return rc, out.getvalue()

    def run_dream_mutating(self, mutate, **kw):
        """Run the `slow` fake model and call mutate() while it is inside the model step (after the snapshot, before the commit).
        Synced by files, not by time: the fake writes ENTERED, waits for RELEASE. -> (rc, stdout)"""
        entered, release = self.tmp / "entered", self.tmp / "release"
        os.environ["FAKE_DREAM_ENTERED"], os.environ["FAKE_DREAM_RELEASE"] = str(entered), str(release)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("FAKE_DREAM_ENTERED", "FAKE_DREAM_RELEASE")])
        errs = []

        def worker():
            try:
                end = time.monotonic() + 60
                while not entered.exists() and time.monotonic() < end:
                    time.sleep(0.02)
                if not entered.exists():
                    raise AssertionError("the model step never started")
                mutate()
            except BaseException as e:   # noqa: BLE001 -- surfaced in the test thread below
                errs.append(e)
            finally:
                release.write_text("")
        t = threading.Thread(target=worker)
        t.start()
        try:
            return self.run_dream(mode="slow", **kw)
        finally:
            release.write_text("")
            t.join()
            if errs:
                raise errs[0]

    def rundir(self):
        return next(d for d in (self.D / "dream/p").iterdir() if d.is_dir())

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def dj(self):
        return json.loads((self.D / "p.dream.json").read_text())

    def reset_state(self):
        (self.D / "p.dream.json").unlink(missing_ok=True)
        self.log.unlink(missing_ok=True)

    def tap(self, pct, resets_in=3600):
        d = Path(os.environ["TC_STATE"]) / "statusline"
        d.mkdir(parents=True, exist_ok=True)
        (d / "s1.json").write_text(json.dumps({"session_id": "s1", "received_at": time.time(),
                                               "rate_limits": {"seven_day": {"used_percentage": pct, "resets_at": time.time() + resets_in}}}))


class SkipTest(DreamBase):
    def test_off_starts_no_model(self):
        os.environ["TC_DREAM"] = "0"
        self.assertEqual(self.run_dream(), (0, "dream: off\n"))
        del os.environ["TC_DREAM"]
        (self.D / "dream.off").write_text("")
        self.assertEqual(self.run_dream(), (0, "dream: off\n"))
        self.assertFalse(self.log.exists())

    def test_usage_skip_starts_no_model(self):
        self.tap(85)
        self.assertEqual(self.run_dream(), (0, "dream: skipped, weekly 85%\n"))
        self.assertFalse(self.log.exists())
        self.tap(99)
        rc, out = self.run_dream("--force")
        self.assertEqual(len(self.calls()), 1, out)

    def test_usage_below_threshold_or_unknown_runs(self):
        for label, setup in (("84", lambda: self.tap(84)), ("expired", lambda: self.tap(99, resets_in=-10)),
                             ("none", lambda: shutil.rmtree(Path(os.environ["TC_STATE"]) / "statusline"))):
            with self.subTest(label):
                self.reset_state()
                setup()
                self.run_dream()
                self.assertEqual(len(self.calls()), 1, label)

    def test_digest_skip_starts_no_model(self):
        self.run_dream()
        self.assertEqual(len(self.calls()), 1)
        rc, out = self.run_dream(mode="unchanged")
        self.assertEqual(out, "dream: p skipped, unchanged sources\n")
        self.assertEqual(len(self.calls()), 1)

    def test_each_source_makes_it_run(self):
        self.run_dream()
        led = self.repo / "docs/superpowers/ledgers/2026-11-01-spec/progress.md"
        obs = self.tmp / "obs/skill-observations/observation-log"
        obs.mkdir(parents=True)

        def commit():
            (self.repo / "docs/new.txt").write_text("n")
            subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "two"], check=True, capture_output=True)
        muts = {"core": lambda: context.add("p", "Map", "new core entry (files: none)"),
                "archive": lambda: (self.D / "p.archive.md").write_text("# p: archived agent context\n\n" + dream_check.SKELETON),
                "ledger": lambda: led.write_text(led.read_text() + "more\n"),
                "report": lambda: (self.repo / "docs/superpowers/reports/r1.md").write_text("changed report\n"),
                "observer": lambda: (obs / "o.md").write_text("p note\n"),
                "head": commit}
        for name, mut in muts.items():
            with self.subTest(name):
                n = len(self.calls())
                mut()
                self.run_dream(mode="unchanged")
                self.assertEqual(len(self.calls()), n + 1, name)

    def test_force_runs_regardless(self):
        self.run_dream()
        self.run_dream("--force", mode="unchanged")
        self.assertEqual(len(self.calls()), 2)

    def test_no_repo_root(self):
        rc, out = self.run_dream(root=False)
        self.assertEqual(out, "dream: p skipped, no repo root\n")
        self.assertFalse(self.log.exists())

    def test_root_from_dream_json_then_flag(self):
        (self.D / "p.dream.json").write_text(json.dumps({"root": str(self.repo), "failures": 0}))
        self.run_dream(root=False)
        self.assertEqual(len(self.calls()), 1)

    def test_root_from_live_tmux_session_first(self):
        other = self.tmp / "other"
        self.make_repo(other)
        fake = self.tmp / "tmux"
        fake.write_text(f"#!/bin/sh\nprintf 'p\\t\\t{other}\\t\\nbg\\t\\t{self.repo}\\t1\\n'\n")
        fake.chmod(0o755)
        os.environ["TC_TMUX"] = str(fake)
        self.run_dream()   # --root points at self.repo, the live session says other
        self.assertEqual(self.dj()["root"], str(other.resolve()))


class ModelStepTest(DreamBase):
    def test_argv_cwd_stdin_are_exact(self):
        self.run_dream()
        c = self.calls()[0]
        settings = str(REPO_OF_DREAM / "claude" / "dream-settings.json")
        self.assertEqual(c["argv"], ["-p", "--model", "sonnet", "--effort", "medium", "--restricted", "--tools",
                                     "Read,Grep,Glob,Write,Edit", "--permission-mode", "dontAsk", "--settings", settings,
                                     "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
                                     "--output-format", "json"])
        rid = time.strftime("%Y%m%d-%H%M", time.localtime(self.now))
        self.assertEqual(Path(c["cwd"]).resolve(), (self.D / "dream/p" / rid).resolve())
        today = time.strftime("%Y-%m-%d", time.localtime(self.now))
        self.assertEqual(c["stdin"], (REPO_OF_DREAM / "claude/dream.md").read_text()
                         + f"\n\nProject: p\nToday: {today}\nCore cap: 8192 bytes\n")

    def test_env_is_scrubbed(self):
        with mock.patch.dict(os.environ, {k: "x" for k in SCRUBBED}):
            self.run_dream()
        self.assertEqual(self.calls()[0]["env"], {})

    def test_inputs_tree(self):
        self.run_dream()
        rd = self.rundir()
        self.assertTrue((rd / "out").is_dir())
        self.assertEqual((rd / "inputs/ledgers/2026-11-01-spec/progress.md").read_text(), "Ruling: a\nline 2\n")
        self.assertEqual((rd / "inputs/reports/r1.md").read_text(), "report\n")
        self.assertIn("docs/real.txt", (rd / "inputs/gitlog.txt").read_text())
        missing = (rd / "inputs/missing-files.txt").read_text().split("\n")
        self.assertIn("board/gone-M0.py", missing)
        self.assertNotIn("docs/real.txt", missing)

    def test_missing_files_skip_paths_outside_the_repo_and_none(self):
        self.core.write_text(core_text(n=1).replace("(files: board/gone-M0.py)", "(files: ~/x/y, /abs/z, none, board/gone-M0.py)"))
        self.run_dream(mode="unchanged")
        rd = self.rundir()
        self.assertEqual((rd / "inputs/missing-files.txt").read_text().split("\n")[0], "board/gone-D0.py")
        txt = (rd / "inputs/missing-files.txt").read_text()
        for bad in ("~/x/y", "/abs/z", "none"):
            self.assertNotIn(bad, txt.split("\n"))

    def test_archive_exists_even_when_live_one_does_not(self):
        self.run_dream(mode="unchanged")
        rd = self.rundir()
        self.assertEqual((rd / "archive.md").read_text(), "# p: archived agent context\n\n" + dream_check.SKELETON)


class GoodRunTest(DreamBase):
    def test_good_run_replaces_both_files(self):
        old = self.core.read_bytes()
        rc, out = self.run_dream()
        self.assertEqual(rc, 0, out)
        rid = time.strftime("%Y%m%d-%H%M", time.localtime(self.now))
        rd = self.D / "dream/p" / rid
        self.assertEqual((self.D / f"backups/p.md.{rid}").read_bytes(), old)
        self.assertTrue((self.D / f"backups/p.archive.md.{rid}").exists())
        new_core, new_arch = self.core.read_text(), (self.D / "p.archive.md").read_text()
        self.assertLessEqual(len(new_core.encode()), 8192)
        self.assertIn("archived", new_arch)
        counts = dream_check.counts(old.decode(), "", new_core, new_arch, json.loads((rd / "out/report.json").read_text()))
        self.assertEqual(out, f"dream: p ok — merged {counts['merged']}, archived {counts['archived']}, stale {counts['stale']}, "
                              f"added {counts['added']}; 0 proposals; 0 contradictions\n")
        self.assertGreater(counts["archived"], 0)
        d = self.dj()
        self.assertEqual((d["run"], d["root"], d["failures"], d["reverted"]), (rid, str(self.repo.resolve()), 0, None))
        self.assertEqual(d["last_report"], str(rd / "out/report.json"))
        self.assertEqual(d["sources_digest"], dream.digest("p", str(self.repo.resolve())))
        self.assertTrue(d["last_run"].endswith("Z"))
        self.assertEqual((rd / "out/core.after.md").read_text(), new_core)
        self.assertIn("@@", (rd / "out/diff.txt").read_text())
        run = json.loads((rd / "out/run.json").read_text())
        for k in ("project", "run", "outcome", "check", "counts", "cost_usd", "tokens", "duration_s", "proposals",
                  "contradictions", "posted"):
            self.assertIn(k, run)
        self.assertEqual((run["outcome"], run["cost_usd"]), ("ok", 0.01))

    def test_merged_counts_two(self):
        rc, out = self.run_dream(mode="merged")
        self.assertEqual(rc, 0, out)
        self.assertIn("merged 2,", out)

    def test_unchanged_is_ok_no_changes(self):
        self.core.write_text(core_text(n=1))
        rc, out = self.run_dream(mode="unchanged")
        self.assertEqual((rc, out), (0, "dream: p ok — no changes\n"))
        self.assertTrue(self.dj()["sources_digest"])

    def test_good_run_after_failures_resets_them(self):
        (self.D / "p.dream.json").write_text(json.dumps({"failures": 2}))
        self.run_dream()
        self.assertEqual(self.dj()["failures"], 0)

    def test_ran_this_minute_is_a_skip(self):
        (self.D / "dream/p" / time.strftime("%Y%m%d-%H%M", time.localtime(self.now + 60))).mkdir(parents=True)
        (self.D / "p.dream.json").write_text(json.dumps({"failures": 1}))
        rc, out = self.run_dream()
        self.assertEqual((rc, out), (0, "dream: p already ran this minute\n"))
        self.assertEqual(self.dj()["failures"], 1)
        self.assertFalse(self.log.exists())


class FailTest(DreamBase):
    def snapshot(self):
        top = sorted((p.name, sha(p)) for p in self.D.iterdir() if p.is_file() and not p.name.endswith((".dream.json", ".lock")))
        return top, sorted(p.name for p in (self.D / "backups").glob("*")) if (self.D / "backups").exists() else []

    def test_failed_run_changes_nothing(self):
        cases = {"overcap": "core over 8192 bytes (", "lost": "entry lost: ", "badreport": "report invalid: ",
                 "noreport": "report missing", "exit1": "model exit 1", "errorjson": "model error", "hang": "model timeout"}
        for mode, text in cases.items():
            with self.subTest(mode), mock.patch.object(dream, "TIMEOUT", 1):
                self.reset_state()
                (self.D / "p.dream.json").write_text(json.dumps({"last_run": "2026-01-01T00:00:00Z", "sources_digest": "old", "failures": 0}))
                before = self.snapshot()
                self.assertTrue(before[0])
                rc, out = self.run_dream(mode=mode)
                self.assertEqual(rc, 1, out)
                self.assertTrue(out.startswith(f"dream: p failed — {text}"), out)
                self.assertEqual(self.snapshot(), before)
                d = self.dj()
                self.assertEqual((d["last_run"], d["sources_digest"], d["failures"]), ("2026-01-01T00:00:00Z", "old", 1))

    def test_hang_leaves_no_child(self):
        with mock.patch.object(dream, "TIMEOUT", 1):
            self.run_dream(mode="hang")
        pid = self.calls()[0]["pid"]
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_old_core_with_problems_fails(self):
        self.core.write_text(core_text() + "\nstray line\n")
        rc, out = self.run_dream()
        self.assertEqual(rc, 1)
        self.assertIn("core invalid: line", out)
        self.assertFalse(self.log.exists())
        self.assertEqual(json.loads((self.rundir() / "out/run.json").read_text())["outcome"], "failed")

    def test_add_during_run_survives(self):
        entry = "added mid run (files: docs/real.txt)"

        def add():
            subprocess.run([sys.executable, str(HERE / "context.py"), "add", "--project", "p", "--section", "Gotchas", "--", entry],
                           check=True, capture_output=True)
        rc, out = self.run_dream_mutating(add)
        self.assertEqual(rc, 0, out)
        sec = re.search(r"## Gotchas\n(.*?)(?=\n## )", self.core.read_text(), re.S).group(1)
        self.assertIn(entry, sec)

    def test_rewrite_during_run_fails(self):
        before = self.core.read_text()

        def rewrite():
            self.core.write_text(before.replace("Map fact 0", "Map FACT 0"))
        rc, out = self.run_dream_mutating(rewrite)
        self.assertEqual(rc, 1)
        self.assertIn("files changed during the run", out)
        self.assertIn("Map FACT 0", self.core.read_text())

    def test_archive_rewrite_during_run_fails(self):
        arch = self.D / "p.archive.md"
        arch.write_text("# p: archived agent context\n\n" + dream_check.SKELETON)

        def rewrite():
            arch.write_text(arch.read_text() + "\n")
        before_core = self.core.read_bytes()
        rc, out = self.run_dream_mutating(rewrite)
        self.assertEqual(rc, 1)
        self.assertIn("files changed during the run", out)
        self.assertEqual(self.core.read_bytes(), before_core)
        self.assertTrue(arch.read_text().endswith("\n\n"))
        self.assertFalse((self.D / "backups").exists())
        self.assertEqual(self.dj()["failures"], 1)

    def test_write_failure_restores(self):
        (self.D / "p.archive.md").write_text("# p: archived agent context\n\n" + dream_check.SKELETON)
        old_core, old_arch = self.core.read_bytes(), (self.D / "p.archive.md").read_bytes()
        real = os.replace

        def boom(src, dst, *a, **k):
            if str(dst) == str(self.core):
                raise OSError("disk full")
            return real(src, dst, *a, **k)
        with mock.patch.object(dream.os, "replace", boom):
            rc, out = self.run_dream()
        self.assertEqual(rc, 1)
        self.assertIn("write failed: disk full", out)
        self.assertEqual(self.core.read_bytes(), old_core)
        self.assertEqual((self.D / "p.archive.md").read_bytes(), old_arch)
        rid = time.strftime("%Y%m%d-%H%M", time.localtime(self.now))
        self.assertEqual((self.D / f"backups/p.md.{rid}").read_bytes(), old_core)
        self.assertEqual((self.D / f"backups/p.archive.md.{rid}").read_bytes(), old_arch)


class DryRunTest(DreamBase):
    def test_dry_run_writes_nothing(self):
        (self.repo / "docs/superpowers/metrics").mkdir(parents=True)
        mlog = self.repo / "docs/superpowers/metrics/runs.jsonl"
        mlog.write_text("")
        before = listing(self.D)
        self.assertIn("p.md", [r[0] for r in before])
        rc, out = self.run_dream("--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertTrue(out.startswith("dream: p dry run — merged "), out)
        self.assertIn("@@", out)
        self.assertEqual(listing(self.D), before)
        self.assertEqual(mlog.read_text(), "")
        self.assertFalse((Path(os.environ["TC_STATE"]) / "discord").exists())
        cwd = Path(self.calls()[0]["cwd"])
        self.assertFalse(cwd.exists())
        self.assertNotIn(self.D.resolve(), cwd.resolve().parents)

    def test_dry_run_failure_prints_and_changes_nothing(self):
        before = listing(self.D)
        rc, out = self.run_dream("--dry-run", mode="overcap")
        self.assertEqual(rc, 1)
        self.assertIn("dream: p failed — core over 8192 bytes (", out)
        self.assertEqual(listing(self.D), before)


class LockAndPruneTest(DreamBase):
    def test_second_process_sees_already_running(self):
        lock = self.D / "dream/p/run.lock"
        lock.parent.mkdir(parents=True)
        with open(lock, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_dream(), (0, "dream: p already running\n"))
        self.assertFalse(self.log.exists())

    def test_prune_keeps_recent(self):
        def rid(days):
            return time.strftime("%Y%m%d-%H%M", time.localtime(self.now + 60 - days * 86400))
        old, young = rid(20), rid(5)
        (self.D / "backups").mkdir()
        for r in (old, young):
            for n in (f"p.md.{r}", f"p.archive.md.{r}"):
                (self.D / "backups" / n).write_text("b")
            (self.D / "dream/p" / r / "out").mkdir(parents=True)
        for p in (self.D / "backups" / f"p.md.{young}", self.D / "dream/p" / young):   # mtime says old, run id says young
            os.utime(p, (1, 1))
        for p in (self.D / "backups" / f"p.md.{old}", self.D / "dream/p" / old):   # mtime says new, run id says old
            os.utime(p, None)
        self.run_dream()
        names = {p.name for p in (self.D / "backups").iterdir()} | {p.name for p in (self.D / "dream/p").iterdir()}
        for gone in (f"p.md.{old}", f"p.archive.md.{old}", old):
            self.assertNotIn(gone, names)
        for kept in (f"p.md.{young}", f"p.archive.md.{young}", young):
            self.assertIn(kept, names)


class MetricsTest(DreamBase):
    def test_metrics_line_only_where_log_exists(self):
        self.run_dream()
        self.assertFalse((self.repo / "docs/superpowers/metrics").exists())
        other = self.tmp / "repo2"
        self.make_repo(other, metrics_log=True)
        log = other / "docs/superpowers/metrics/runs.jsonl"
        lines0 = [json.loads(l) for l in log.read_text().splitlines()]
        self.reset_state()
        self.core.write_text(core_text())
        self.repo = other
        self.run_dream()
        lines = [json.loads(l) for l in log.read_text().splitlines()]
        self.assertEqual(len(lines), len(lines0) + 1)
        rec = lines[-1]
        self.assertEqual(set(rec), {"kind", "at", "project", "run", "outcome", "cost_usd", "tokens", "duration_s", "model"})
        self.assertEqual((rec["kind"], rec["project"], rec["outcome"], rec["model"]), ("dream", "p", "ok", "sonnet"))
        self.assertEqual(metrics.last_runs(lines), metrics.last_runs(lines0))


class AllTest(DreamBase):
    def test_all_runs_sorted_and_exits_1_after_trying_all(self):
        for name in ("b", "a", "c"):
            (self.D / f"{name}.md").write_text(core_text(name) if name != "b" else core_text(name) + "\nstray\n")
        (self.D / "a.archive.md").write_text("# a: archived agent context\n\n" + dream_check.SKELETON)
        self.core.unlink()
        rc, out = self.run_dream("--all", project=None)
        self.assertEqual(rc, 1)
        lines = out.splitlines()
        self.assertEqual([l.split()[1] for l in lines], ["a", "b", "c"])
        self.assertIn("ok", lines[0])
        self.assertIn("failed — core invalid", lines[1])
        self.assertIn("ok", lines[2])


class UnexpectedErrorTest(DreamBase):
    def test_exception_in_one_project_is_a_failed_night_and_all_goes_on(self):
        for name in ("a", "b"):
            (self.D / f"{name}.md").write_text(core_text(name))
        self.core.unlink()
        real = dream.prepare

        def boom(run_dir, project, *args, **kw):
            if project == "a":
                raise OSError("disk exploded")
            return real(run_dir, project, *args, **kw)
        with mock.patch.object(dream, "prepare", boom):
            rc, out = self.run_dream("--all", project=None)
        self.assertEqual(rc, 1)
        lines = out.splitlines()
        self.assertEqual(lines[0], "dream: a failed — error: OSError: disk exploded")
        self.assertTrue(lines[1].startswith("dream: b ok"), out)
        d = json.loads((self.D / "a.dream.json").read_text())
        self.assertEqual(d["failures"], 1)
        rd = next(p for p in (self.D / "dream/a").iterdir() if p.is_dir())
        run = json.loads((rd / "out/run.json").read_text())
        self.assertEqual((run["outcome"], run["check"]), ("failed", "error: OSError: disk exploded"))

    def test_exception_before_the_run_dir_still_counts(self):
        with mock.patch.object(dream, "digest", side_effect=RuntimeError("no git")):
            rc, out = self.run_dream()
        self.assertEqual((rc, out), (1, "dream: p failed — error: RuntimeError: no git\n"))
        self.assertEqual(self.dj()["failures"], 1)


class KillGroupTest(DreamBase):
    def test_term_ignoring_grandchild_holding_the_pipe_does_not_hang(self):
        """The leader dies on TERM at once, but a grandchild that ignores TERM keeps the stdout pipe open."""
        fake = self.tmp / "stubborn"
        fake.write_text(f"#!/bin/sh\n(trap '' TERM; sleep 30) &\necho $! > {self.tmp}/gc.pid\nsleep 30\n")
        fake.chmod(0o755)
        os.environ["TC_DREAM_CLAUDE"] = str(fake)
        t0 = time.monotonic()
        with mock.patch.object(dream, "TIMEOUT", 1), mock.patch.object(dream, "GRACE", 1), mock.patch.object(dream, "REAP", 2):
            rc, out = self.run_dream()
        self.assertLess(time.monotonic() - t0, 15)
        self.assertIn("model timeout", out)
        time.sleep(0.3)
        with self.assertRaises(ProcessLookupError):
            os.kill(int((self.tmp / "gc.pid").read_text()), 0)


class ReportTest(DreamBase):
    def test_report_prints_last_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(dream.main(["report", "p"]), 0)
        self.assertEqual(out.getvalue(), "dream: p has no run yet\n")
        self.run_dream()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(dream.main(["report", "p"]), 0)
        for s in ("outcome", "ok", "cost_usd", "fake summary", "proposals", "contradictions"):
            self.assertIn(s, out.getvalue())


if __name__ == "__main__":
    unittest.main()
