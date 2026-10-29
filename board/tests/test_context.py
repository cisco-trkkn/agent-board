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
        # Mutation: remove the lockf call in _locked() -> "unchanged while locked" fails.
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


if __name__ == "__main__":
    unittest.main()
