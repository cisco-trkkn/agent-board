"""dream_actions: Revert and File proposals (Task 5). State is built by real dream.run_project runs against the fake model,
so revert is tested on what a real run leaves. Each guard test names the mutation that must fail it."""
import contextlib
import hashlib
import io
import json
import re
import os
import stat
import subprocess
import sys
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import context  # noqa: E402
import dream  # noqa: E402
import dream_actions as A  # noqa: E402
import dream_paths as P  # noqa: E402
import ideas  # noqa: E402
from test_dream import DreamBase, listing, sha  # noqa: E402

PROPOSALS = [{"kind": "idea", "text": "script the ledger check", "evidence": ["spec-a ledger", "spec-b ledger"]},
             {"kind": "idea", "text": "cache the digest", "evidence": ["spec-c"]},
             {"kind": "observer", "text": "workers skip the report", "evidence": ["spec-a"]}]

WRAP = """#!/usr/bin/env python3
import json, os, subprocess, sys
r = subprocess.run([os.environ["REAL_FAKE"]] + sys.argv[1:], input=sys.stdin.read(), text=True, capture_output=True)
rp = "out/report.json"
if os.path.exists(rp):
    d = json.load(open(rp))
    d["proposals"] = json.loads(os.environ.get("WRAP_PROPOSALS", "[]"))
    json.dump(d, open(rp, "w"))
sys.stdout.write(r.stdout)
sys.exit(r.returncode)
"""


class Base(DreamBase):
    def setUp(self):
        super().setUp()
        w = self.tmp / "wrapclaude"
        w.write_text(WRAP)
        w.chmod(w.stat().st_mode | stat.S_IXUSR)
        os.environ["REAL_FAKE"] = os.environ["TC_DREAM_CLAUDE"]
        os.environ["TC_DREAM_CLAUDE"] = str(w)
        os.environ["WRAP_PROPOSALS"] = json.dumps(PROPOSALS)
        os.environ.pop("TC_OBSERVER_SCRIPT", None)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("REAL_FAKE", "WRAP_PROPOSALS")])

    def night(self):
        """One good run (the clock advances a minute). -> run id"""
        rc, out = self.run_dream("--force")
        self.assertEqual(rc, 0, out)
        return self.dj()["run"]

    def files(self):
        return listing(self.D)

    def observer_script(self, body=None):
        s = self.tmp / "new-observation.sh"
        obs = self.tmp / "obsdir"
        s.write_text(body or f'#!/bin/bash\nmkdir -p {obs}\nf={obs}/0001-$1.md\n: > "$f"\necho "$f"\n')
        s.chmod(0o755)
        os.environ["TC_OBSERVER_SCRIPT"] = str(s)
        return obs


class RevertTest(Base):
    def test_revert_restores_both_files_and_marks_state(self):
        before = self.core.read_text()
        run = self.night()
        self.assertNotEqual(self.core.read_text(), before)
        self.assertEqual(A.revert("p", run), "reverted")
        self.assertEqual(self.core.read_text(), before)
        self.assertFalse(context.archive_path("p").exists())          # empty archive backup = it did not exist
        self.assertEqual((self.D / "backups" / f"p.md.{run}.pre-revert").read_text().count("## Map"), 1)
        self.assertTrue((self.D / "backups" / f"p.archive.md.{run}.pre-revert").is_file())
        self.assertEqual(self.dj()["reverted"], run)
        self.assertNotIn("sources_digest", {k for k, v in self.dj().items() if v})
        rc, out = self.run_dream()                                      # the next night runs again, without --force
        self.assertIn("ok", out)

    def test_second_revert_changes_nothing(self):     # mutation: drop the `reverted` check -> the add is lost and hashes differ
        run = self.night()
        self.assertEqual(A.revert("p", run), "reverted")
        context.add("p", "Gotchas", "added between the taps")
        h1 = self.files()
        self.assertEqual(A.revert("p", run), "already reverted")
        self.assertEqual(self.files(), h1)
        self.assertIn("added between the taps", self.core.read_text())

    def test_revert_of_older_run_is_stale(self):      # mutation: skip the dream.json.run comparison -> B's core is overwritten
        a = self.night()
        context.add("p", "Map", "new fact for night two " + "y" * 200 + " (files: board/gone-new.py)")
        b = self.night()
        self.assertNotEqual(a, b)
        h = self.files()
        self.assertEqual(A.revert("p", a), f"stale: newer run {b}")
        self.assertEqual(self.files(), h)

    def test_revert_still_works_after_an_unchanged_night(self):   # mutation: _finish sets `run` on unchanged -> stale
        a = self.night()
        after_a = self.core.read_text()
        rc, out = self.run_dream("--force", mode="unchanged")
        self.assertIn("no changes", out)
        d = self.dj()
        self.assertEqual((d["run"], d["failures"], d["reverted"]), (a, 0, None))
        self.assertTrue(d["last_report"].split("/dream/p/")[1].startswith(a))
        self.assertEqual(self.core.read_text(), after_a)
        self.assertEqual(A.revert("p", a), "reverted")

    def test_unknown_runs(self):
        run = self.night()
        h = self.files()
        for bad in ("20200101-0000", "garbage", "", "../x"):
            self.assertEqual(A.revert("p", bad), "unknown", bad)
        (self.D / "backups" / f"p.md.{run}").unlink()                   # pruned
        self.assertEqual(A.revert("p", run), "unknown")
        self.assertEqual(self.files(), [r for r in h if not r[0].endswith(f"p.md.{run}")])

    def test_revert_keeps_entries_added_since(self):  # mutation: restore without re-appending -> fails
        run = self.night()
        line = context.add("p", "Gotchas", "kept after revert")
        self.assertEqual(A.revert("p", run), "reverted")
        sec = dict((l, s) for s, l in context.entries(self.core.read_text()))
        self.assertEqual(sec[line], "Gotchas")

    def test_revert_restores_an_existing_archive(self):
        arch = context.archive_path("p")
        arch.write_text("# p: archived agent context\n\n" + "".join(f"## {s}\n\n" for s in ("Map", "How to run", "Gotchas", "Decisions")))
        before = arch.read_text()
        run = self.night()
        self.assertNotEqual(arch.read_text(), before)
        self.assertEqual(A.revert("p", run), "reverted")
        self.assertEqual(arch.read_text(), before)

    def test_revert_waits_for_the_lock(self):         # mutation: write outside context.locked -> restored while the lock is held
        run = self.night()
        after = self.core.read_text()
        holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
            import sys, time; sys.path.insert(0, {str(HERE.parent)!r})
            import context
            with context.locked("p", wait=5):
                print("held", flush=True); time.sleep(1.2)""")], stdout=subprocess.PIPE, text=True, env=dict(os.environ))
        self.addCleanup(holder.wait)
        self.addCleanup(holder.stdout.close)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        res = []
        t = threading.Thread(target=lambda: res.append(A.revert("p", run)))
        t0 = time.monotonic()
        t.start()
        time.sleep(0.5)
        self.assertEqual(self.core.read_text(), after)                 # still waiting
        t.join(10)
        self.assertEqual(res, ["reverted"])
        self.assertGreater(time.monotonic() - t0, 1.0)

    def test_busy_when_lock_stays_held(self):
        run = self.night()
        h = self.files()
        holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
            import sys, time; sys.path.insert(0, {str(HERE.parent)!r})
            import context
            with context.locked("p", wait=5):
                print("held", flush=True); time.sleep(4.5)""")], stdout=subprocess.PIPE, text=True, env=dict(os.environ))
        self.addCleanup(holder.wait)
        self.addCleanup(holder.stdout.close)
        holder.stdout.readline()
        with mock.patch.object(context, "locked", wraps=context.locked) as lk:
            self.assertEqual(A.revert("p", run), "busy")
        self.assertEqual(lk.call_args.kwargs.get("wait"), 3)
        self.assertEqual(self.files(), h)

    def test_revert_during_model_step_is_busy(self):
        a = self.night()
        context.add("p", "Map", "night two fact " + "z" * 200 + " (files: board/gone-two.py)")
        real = dream.run_model
        seen = []
        def mid(*args):
            r = real(*args)
            before = self.files()
            seen.append((A.revert("p", a), A.file_proposals("p"), before == self.files()))
            return r
        with mock.patch.object(dream, "run_model", mid):
            rc, out = self.run_dream("--force")
        self.assertEqual(rc, 0, out)
        self.assertEqual(seen, [("busy", "busy", True)])
        self.assertIsNone(self.dj()["reverted"])
        self.assertEqual(self.dj()["failures"], 0)

    def test_second_revert_tap_says_already_reverted_and_changes_nothing(self):
        run = self.night()
        self.assertEqual(A.revert("p", run), "reverted")
        h = self.files()
        self.assertEqual(A.revert("p", run), "already reverted")
        self.assertEqual(self.files(), h)
        self.assertEqual(self.dj()["reverted"], run)

    def test_revert_of_previous_run_between_commit_and_finish_cannot_restore_it(self):
        a = self.night()
        context.add("p", "Map", "night two fact " + "z" * 200 + " (files: board/gone-two.py)")
        real = dream._finish
        seen = []
        def late(*args, **kw):
            seen.append(A.revert("p", a))
            return real(*args, **kw)
        with mock.patch.object(dream, "_finish", late):
            rc, out = self.run_dream("--force")
        self.assertEqual(rc, 0, out)
        self.assertIn(seen[0], ("busy", "stale: newer run " + self.dj()["run"]))
        self.assertIsNone(self.dj()["reverted"])
        self.assertIn("night two fact", self.core.read_text() + context.archive_path("p").read_text())

    def test_finish_keeps_a_revert_that_landed_after_its_state_was_read(self):
        a = self.night()
        state = dict(P.load("p"))
        self.assertEqual(A.revert("p", a), "reverted")
        res = {"outcome": "failed", "failures": 0, "at": "x", "diff": None, "cost_usd": None, "tokens": None,
               "duration_s": 0, "posted": False, "check": "x", "counts": None, "proposals": [], "contradictions": [],
               "project": "p", "run": "x"}
        with mock.patch.object(dream, "notify"), mock.patch.object(dream, "record_metrics"):
            dream._finish(res, "p", state, str(self.repo), self.now, None, "20990101-0000")
        self.assertEqual(self.dj()["reverted"], a)


class FileTest(Base):
    def setUp(self):
        super().setUp()
        self.obs = self.observer_script()
        self.run = self.night()

    def idea_text(self):
        p = ideas.ideas_path("p")
        return p.read_text() if p.is_file() else ""

    def test_files_each_once(self):                    # mutation: no filed.json check -> second call files again
        self.assertEqual(A.file_proposals("p"), "filed 3")
        self.assertEqual(self.idea_text().count("script the ledger check"), 1)
        self.assertIn("evidence: spec-a ledger", self.idea_text())
        self.assertEqual(len(list(self.obs.glob("*.md"))), 1)
        body = next(self.obs.glob("*.md")).read_text()
        self.assertIn("workers skip the report", body)
        h = self.files()
        self.assertEqual(A.file_proposals("p", self.run), "already filed")
        self.assertEqual(self.idea_text().count("cache the digest"), 1)
        self.assertEqual(self.files(), h)

    def test_same_proposal_next_night_once(self):
        A.file_proposals("p")
        context.add("p", "Map", "night two fact " + "z" * 200 + " (files: board/gone-two.py)")
        run2 = self.night()
        self.assertNotEqual(run2, self.run)
        self.assertEqual(A.file_proposals("p"), "already filed")
        self.assertEqual(self.idea_text().count("cache the digest"), 1)

    def test_resumes_after_crash(self):               # mutation: write filed.json once at the end -> first idea filed twice
        real = ideas.add
        n = []
        def boom(*a, **k):
            n.append(1)
            if len(n) == 2:
                raise OSError("disk")
            return real(*a, **k)
        with mock.patch.object(ideas, "add", boom):
            with self.assertRaises(OSError):
                A.file_proposals("p")
        self.assertEqual(self.idea_text().count("script the ledger check"), 1)
        self.assertEqual(A.file_proposals("p"), "filed 2")
        self.assertEqual(self.idea_text().count("script the ledger check"), 1)

    def test_observer_script_missing_leaves_unfiled(self):
        os.environ["TC_OBSERVER_SCRIPT"] = str(self.tmp / "nope.sh")
        with mock.patch.object(A, "_glob_observer", return_value=None):
            self.assertEqual(A.file_proposals("p"), "filed 2, skipped 1 observer (no task-observer script)")
            self.assertEqual(A.file_proposals("p"), "filed 0, skipped 1 observer (no task-observer script)")
        self.observer_script()
        self.assertEqual(A.file_proposals("p"), "filed 1")

    def test_observer_note_written(self):
        A.file_proposals("p")
        f = next(self.obs.glob("*.md"))
        self.check_note(f, "0001")
        self.assertIn("spec-a", f.read_text())

    def check_note(self, f, prefix):
        """The shape the task-observer log requires: frontmatter (id = the file's NNNN prefix, status open, non-empty
        siblings_checked, quoted prose values) then Issue / Suggested improvement / Principle."""
        t = f.read_text()
        head, body = t.split("\n---\n", 1)
        self.assertTrue(head.startswith("---\n"), t)
        fm = dict(l.split(":", 1) for l in head.splitlines()[1:] if re.match(r"^[a-z_]+:", l))
        self.assertEqual(int(fm["id"]), int(prefix))
        self.assertEqual(fm["status"].strip(), "open")
        self.assertTrue(fm["siblings_checked"].strip().startswith('"'))
        for k in ("title", "area", "session_context"):
            self.assertRegex(fm[k].strip(), r'^".+"$')
        self.assertRegex(fm["date"].strip(), r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(body, r"(?s)\*\*Issue:\*\*.*\*\*Suggested improvement:\*\*.*\*\*Principle:\*\*")

    def test_real_observer_script_makes_a_valid_note(self):   # one unpatched run of the deciding external command
        import glob, pwd
        home = pwd.getpwuid(os.getuid()).pw_dir   # HOME is patched to a temp dir; the plugin copy is read, never written
        found = glob.glob(os.path.join(home, ".claude/plugins/**/task-observer/scripts/new-observation.sh"), recursive=True)
        if not found:
            self.skipTest("no task-observer script under ~/.claude/plugins")
        os.environ["TC_OBSERVER_SCRIPT"] = max(found, key=os.path.getmtime)
        ws = self.tmp / "ws"
        (ws / "skill-observations/observation-log/archive").mkdir(parents=True)
        os.environ["TASK_OBSERVER_WORKSPACE"] = str(ws)
        self.assertEqual(A.file_proposals("p"), "filed 3")
        notes = list((ws / "skill-observations/observation-log").glob("*.md"))
        self.assertEqual(len(notes), 1)
        self.check_note(notes[0], notes[0].name[:4])
        self.assertTrue(notes[0].name.startswith("0001-dream-"))

    def test_observer_timeout_is_ten_seconds(self):
        os.environ["TC_OBSERVER_SCRIPT"] = str(self.tmp / "slow.sh")
        (self.tmp / "slow.sh").write_text("#!/bin/bash\nsleep 30\n")
        (self.tmp / "slow.sh").chmod(0o755)
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 10)) as r:
            self.assertEqual(A.file_proposals("p"), "filed 2, skipped 1 observer (script failed)")
        self.assertEqual(r.call_args.kwargs["timeout"], 10)

    def test_no_proposals_and_unknown(self):
        os.environ["WRAP_PROPOSALS"] = "[]"
        context.add("p", "Map", "night two fact " + "z" * 200 + " (files: board/gone-two.py)")
        run2 = self.night()
        self.assertEqual(A.file_proposals("p", run2), "no proposals")
        self.assertEqual(A.file_proposals("p", "20200101-0000"), "unknown")
        self.assertEqual(A.file_proposals("nobody"), "unknown")

    def test_at_most_twenty_per_call(self):
        os.environ["WRAP_PROPOSALS"] = json.dumps([{"kind": "idea", "text": f"idea number {i}", "evidence": ["e"]} for i in range(25)])
        context.add("p", "Map", "night two fact " + "z" * 200 + " (files: board/gone-two.py)")
        self.night()
        self.assertEqual(A.file_proposals("p"), "filed 20")
        self.assertEqual(A.file_proposals("p"), "filed 5")

    def test_busy_when_lock_held(self):
        h = self.files()
        with mock.patch.object(context, "locked", side_effect=ValueError("locked by another writer (the nightly run?); retry in a moment")) as lk:
            self.assertEqual(A.file_proposals("p"), "busy")
        self.assertEqual(lk.call_args.kwargs.get("wait"), 3)
        self.assertEqual(self.files(), h)


class PostedTest(Base):
    def box(self):
        import tc_env
        return sorted((tc_env.discord_dir("p") / "outbox").glob("*.json")) if (tc_env.discord_dir("p") / "outbox").exists() else []

    def test_real_run_posts_once_and_records_posted(self):
        import tc_env
        tc_env.discord_dir("p").mkdir(parents=True)
        (tc_env.discord_dir("p") / "bridge.json").write_text(json.dumps({"channel": "C1"}))
        run = self.night()
        ops = [json.loads(f.read_text()) for f in self.box()]
        self.assertEqual([o["key"] for o in ops], [f"dream-p-{run}"])
        self.assertEqual([b["label"] for b in ops[0]["buttons"]], ["Revert", "File proposals"])
        self.assertTrue(json.loads((self.D / "dream/p" / run / "out" / "run.json").read_text())["posted"])

    def test_no_channel_no_post_and_report_still_prints(self):
        run = self.night()
        self.assertEqual(self.box(), [])
        self.assertFalse(json.loads((self.D / "dream/p" / run / "out" / "run.json").read_text())["posted"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(dream.report("p"), 0)
        self.assertIn("summary: fake summary", out.getvalue())


class CliTest(Base):
    def test_cli_twins_print_results(self):
        self.observer_script()
        run = self.night()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(dream.main(["file", "p"]), 0)
            self.assertEqual(dream.main(["file", "p"]), 0)
            self.assertEqual(dream.main(["revert", "p", run]), 0)
            self.assertEqual(dream.main(["revert", "p", run]), 0)
        self.assertEqual(out.getvalue().splitlines(), ["filed 3", "already filed", "reverted", "already reverted"])


if __name__ == "__main__":
    unittest.main()
