import fcntl
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import context  # noqa: E402
import ideas  # noqa: E402

SKELETON = ("# p: shared agent context\nLast curated: 2026-10-28\n\n"
            "## Map\n\n## How to run\n\n## Gotchas\n\n## Decisions\n")
T0 = time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1))   # 2026-10-28 local


class ContextPathTest(unittest.TestCase):
    """Path resolution: TC_CONTEXT_DIR, else ~/.local/state/agent-board/context; the key rules match ideas.py."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = os.environ.pop("TC_CONTEXT_DIR", None)
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp.name

    def tearDown(self):
        os.environ["HOME"] = self.old_home
        if self.old_env is not None:
            os.environ["TC_CONTEXT_DIR"] = self.old_env
        else:
            os.environ.pop("TC_CONTEXT_DIR", None)
        self.tmp.cleanup()

    def test_default_dir_under_home(self):
        self.assertEqual(context.context_path("p"),
                         Path(self.tmp.name) / ".local" / "state" / "agent-board" / "context" / "p.md")

    def test_tc_context_dir_wins(self):
        os.environ["TC_CONTEXT_DIR"] = os.path.join(self.tmp.name, "elsewhere")
        self.assertEqual(context.context_path("p"), Path(self.tmp.name) / "elsewhere" / "p.md")

    def test_project_key_rules_match_ideas(self):
        for good in ("agent-board", "foo_bar", "a.b", "x-1"):
            self.assertEqual(context.context_path(good).name, ideas.ideas_path(good).name)
        for bad in ("a/b", "..", ".", "", ".hidden"):
            with self.assertRaises(ValueError):
                ideas.ideas_path(bad)
            with self.assertRaises(ValueError):
                context.context_path(bad)


class ContextAddTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_CONTEXT_DIR"] = self.tmp.name
        self.p = Path(self.tmp.name) / "p.md"

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_CONTEXT_DIR", None)

    def read(self):
        return self.p.read_text()

    def test_add_creates_the_four_section_file(self):
        line = context.add("p", "Map", "board code is in board/ (files: board/server.py)", now=T0)
        self.assertEqual(line, "- board code is in board/ (files: board/server.py) · 2026-10-28")
        self.assertEqual(self.read(), SKELETON.replace("## Map\n", "## Map\n" + line + "\n"))

    def test_add_places_entries_under_the_right_heading_in_order(self):
        context.add("p", "Gotchas", "g1", now=T0)
        context.add("p", "Map", "m1", now=T0)
        context.add("p", "Gotchas", "g2", now=T0)
        context.add("p", "Decisions", "d1", now=T0)
        context.add("p", "How to run", "h1", now=T0)
        self.assertEqual(self.read(), (
            "# p: shared agent context\nLast curated: 2026-10-28\n\n"
            "## Map\n- m1 · 2026-10-28\n\n"
            "## How to run\n- h1 · 2026-10-28\n\n"
            "## Gotchas\n- g1 · 2026-10-28\n- g2 · 2026-10-28\n\n"
            "## Decisions\n- d1 · 2026-10-28\n"))

    def test_add_dates_an_undated_entry_and_keeps_a_dated_one(self):
        context.add("p", "Map", "undated", now=T0)
        context.add("p", "Map", "dated · 2026-01-02", now=T0)
        self.assertIn("- undated · 2026-10-28\n- dated · 2026-01-02\n", self.read())

    def test_add_normalises_whitespace_and_refuses_empty(self):
        self.assertEqual(context.add("p", "Map", "  two\n words ", now=T0), "- two words · 2026-10-28")
        with self.assertRaises(ValueError):
            context.add("p", "Map", "   ")

    def test_unknown_section_refused_and_nothing_written(self):
        with self.assertRaisesRegex(ValueError, "unknown section"):
            context.add("p", "Notes", "x")
        with self.assertRaisesRegex(ValueError, "unknown section"):
            context.add("p", "map", "x")        # headings are case-sensitive
        self.assertFalse(self.p.exists())

    def test_add_updates_last_curated(self):
        self.p.write_text(SKELETON.replace("2026-10-28", "2026-01-01"))
        context.add("p", "Map", "m", now=T0)
        self.assertIn("Last curated: 2026-10-28\n", self.read())
        self.assertNotIn("2026-01-01", self.read())

    def test_missing_heading_in_an_existing_file_is_refused(self):
        self.p.write_text("# p: shared agent context\nLast curated: 2026-01-01\n\n## Map\n")
        with self.assertRaises(ValueError):
            context.add("p", "Gotchas", "g", now=T0)
        self.assertEqual(self.read(), "# p: shared agent context\nLast curated: 2026-01-01\n\n## Map\n")

    def test_last_heading_without_trailing_newline(self):
        self.p.write_text(SKELETON.rstrip("\n"))
        context.add("p", "Decisions", "d", now=T0)
        self.assertTrue(self.read().endswith("## Decisions\n- d · 2026-10-28\n"), self.read())

    def test_last_entry_without_trailing_newline(self):
        self.p.write_text(SKELETON.replace("## Decisions\n", "## Decisions\n- a · 2026-01-01").rstrip("\n"))
        context.add("p", "Decisions", "two", now=T0)
        self.assertTrue(self.read().endswith("## Decisions\n- a · 2026-01-01\n- two · 2026-10-28\n"), self.read())

    def test_empty_file_is_treated_as_new(self):
        self.p.write_text("")
        context.add("p", "Map", "m", now=T0)
        self.assertTrue(self.read().startswith("# p: shared agent context\n"))

    def test_show_and_path(self):
        self.assertEqual(context.show("p"), "")
        context.add("p", "Map", "m", now=T0)
        self.assertEqual(context.show("p"), self.read())
        self.assertEqual(context.context_path("p"), self.p)

    def test_add_blocks_while_the_lock_is_held(self):
        # Hold the lock in this process; a child `add` must not touch the file until it is released.
        # Mutation: remove the lockf call in add() -> "unchanged while locked" fails.
        context.add("p", "Map", "first", now=T0)
        before = self.read()
        env = {**os.environ, "TC_CONTEXT_DIR": self.tmp.name}
        with open(f"{self.p}.lock", "w") as lk:
            fcntl.lockf(lk, fcntl.LOCK_EX)
            child = subprocess.Popen([sys.executable, "-I", str(HERE / "context.py"), "add", "--project", "p",
                                      "--section", "Map", "--", "second"], env=env)
            time.sleep(0.7)
            self.assertIsNone(child.poll(), "child finished while the lock was held")
            self.assertEqual(self.read(), before, "unchanged while locked")
            fcntl.lockf(lk, fcntl.LOCK_UN)
        self.assertEqual(child.wait(timeout=10), 0)
        self.assertIn("- second · ", self.read())

    def test_concurrent_cli_adds_all_land(self):
        env = {**os.environ, "TC_CONTEXT_DIR": self.tmp.name}
        secs = list(context.SECTIONS)
        procs = [subprocess.Popen([sys.executable, "-I", str(HERE / "context.py"), "add", "--project", "p",
                                   "--section", secs[n % 4], "--", f"entry {n}"], env=env) for n in range(20)]
        self.assertEqual([p.wait() for p in procs], [0] * 20)
        text = self.read()
        self.assertEqual(text.count("# p: shared agent context"), 1)
        self.assertEqual(sorted(int(m) for m in re.findall(r"^- entry (\d+) · ", text, re.M)), list(range(20)))
        for n in range(20):   # each entry sits under its own heading
            sec_text = text.split(f"## {secs[n % 4]}\n", 1)[1].split("\n## ", 1)[0]
            self.assertIn(f"- entry {n} · ", sec_text)

    def test_cli(self):
        env = {**os.environ, "TC_CONTEXT_DIR": self.tmp.name}
        run = lambda *a: subprocess.run([sys.executable, "-I", str(HERE / "context.py"), *a], env=env,
                                        capture_output=True, text=True)
        r = run("show", "--project", "p")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = run("path", "--project", "p")
        self.assertEqual((r.returncode, r.stdout), (0, f"{self.p}\n"))
        r = run("add", "--project", "p", "--section", "Gotchas", "--", "flaky", "test")
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"^added under ## Gotchas: - flaky test · \d{4}-\d{2}-\d{2}\n$")
        r = run("add", "--project", "p", "--section", "Nope", "--", "x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown section", r.stderr)
        r = run("show", "--project", "p")
        self.assertEqual(r.stdout, self.read())


HOLD = "import fcntl,sys,time;lk=open(sys.argv[1],'w');fcntl.lockf(lk,fcntl.LOCK_EX);print('held',flush=True);time.sleep(float(sys.argv[2]))"


class ArchiveAndSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = os.environ.get("TC_CONTEXT_DIR")
        self.old_home = os.environ.get("HOME")
        os.environ["TC_CONTEXT_DIR"] = self.tmp.name
        os.environ["HOME"] = self.tmp.name
        self.p = Path(self.tmp.name) / "p.md"
        self.holders = []

    def tearDown(self):
        for h in self.holders:
            h.kill()
            h.wait()
        os.environ["HOME"] = self.old_home
        if self.old_env is None:
            os.environ.pop("TC_CONTEXT_DIR", None)
        else:
            os.environ["TC_CONTEXT_DIR"] = self.old_env
        self.tmp.cleanup()

    def hold(self, secs):
        h = subprocess.Popen([sys.executable, "-c", HOLD, f"{self.p}.lock", str(secs)], stdout=subprocess.PIPE, text=True)
        self.holders.append(h)
        self.assertEqual(h.stdout.readline().strip(), "held")
        return h

    def cli(self, *a, timeout=15):
        return subprocess.run([sys.executable, "-I", str(HERE / "context.py"), *a],
                              env={**os.environ, "TC_CONTEXT_DIR": self.tmp.name}, capture_output=True, text=True,
                              timeout=timeout)

    def test_cap_and_archive_path(self):
        self.assertEqual(context.CAP, 8192)
        self.assertEqual(context.archive_path("p"), Path(self.tmp.name) / "p.archive.md")
        with self.assertRaises(ValueError):
            context.archive_path("a/b")

    def test_lock_wait_times_out(self):
        # Mutation: a blocking lockf instead of the polling loop -> the child outlives its own 5 s deadline.
        self.hold(8)
        code = ("import sys;sys.path.insert(0,sys.argv[1]);import context\n"
                "try:\n    context.locked('p', wait=0.5).__enter__()\nexcept ValueError: print('timeout')")
        r = subprocess.run([sys.executable, "-c", code, str(HERE)], env={**os.environ}, capture_output=True,
                           text=True, timeout=5)
        self.assertEqual(r.stdout.strip(), "timeout")

    def test_add_waits_for_a_short_hold(self):
        # Mutation: wait=0 in add -> ValueError.
        self.hold(1)
        t = time.monotonic()
        line = context.add("p", "Map", "waited", now=T0)
        self.assertIn("waited", line)
        self.assertGreaterEqual(time.monotonic() - t, 0.5)

    def test_add_exits_2_when_held_past_the_default_bound(self):
        self.hold(8)
        t = time.monotonic()
        r = self.cli("add", "--project", "p", "--section", "Map", "--", "x", timeout=7.5)
        self.assertLess(time.monotonic() - t, 7.5)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stderr.strip(),
                         "context: locked by another writer (the nightly run?); retry in a moment")

    def test_over_cap_notice(self):
        # Mutation: len(text) instead of the byte size -> a '·'-heavy core between the two counts gets no notice.
        context.add("p", "Map", "seed", now=T0)
        pad = "- " + "·" * 4040 + "\n"          # 4040 chars, 8080 bytes
        with open(self.p, "a") as f:
            f.write(pad)
        r = self.cli("add", "--project", "p", "--section", "Map", "--", "more words to cross")
        n = self.p.stat().st_size
        self.assertGreater(n, 8192)
        self.assertLessEqual(len(self.p.read_text()), 8192)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[1], f"context: core over 8 KB ({n}), the nightly run will condense it")

    def test_no_notice_at_cap(self):
        # Mutation: >= instead of > -> a core of exactly 8192 bytes prints the notice.
        context.add("p", "Map", "seed", now=T0)
        context.add("q", "Map", "seed", now=T0)
        q = Path(self.tmp.name) / "q.md"
        before = q.stat().st_size
        context.add("q", "Map", "last words", now=T0)
        growth = q.stat().st_size - before
        pad = 8192 - growth - self.p.stat().st_size
        with open(self.p, "a") as f:
            f.write("- " + "x" * (pad - 3) + "\n")
        self.assertEqual(self.p.stat().st_size, 8192 - growth)
        r = self.cli("add", "--project", "p", "--section", "Map", "--", "last words")
        self.assertEqual(self.p.stat().st_size, 8192)
        self.assertEqual(len(r.stdout.splitlines()), 1)

    def test_search_all_words_both_files(self):
        # Mutation: any instead of all -> three rows.
        self.p.write_text("# p: shared agent context\nLast curated: 2026-11-18\n\n## Map\n- usage tap row\n"
                          "- usage only\n## Gotchas\n- nothing\n")
        (Path(self.tmp.name) / "p.archive.md").write_text("# p\n\n## Decisions\n- Usage TAP archived\n")
        self.assertEqual(context.search("p", ["usage", "tap"]),
                         [("core", "Map", "- usage tap row"), ("archive", "Decisions", "- Usage TAP archived")])
        self.assertEqual(context.entries(self.p.read_text())[-1], ("Gotchas", "- nothing"))

    def test_search_no_archive_file(self):
        self.p.write_text("## Map\n- usage tap\n")
        self.assertEqual(context.search("p", ["usage"]), [("core", "Map", "- usage tap")])
        self.assertEqual(context.search("nofile", ["x"]), [])

    def test_search_cli(self):
        self.p.write_text("## Map\n- usage tap\n")
        r = self.cli("search", "--project", "p", "--", "usage", "tap")
        self.assertEqual((r.returncode, r.stdout), (0, "[core] Map: - usage tap\n"))
        r = self.cli("search", "--project", "p", "--", "zzz")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", "context: no entries match\n"))


if __name__ == "__main__":
    unittest.main()
