"""scout_pack: the weekly context pack. Scratch git repo, temp HOME/TC_*, fake claude on PATH."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import scout_pack  # noqa: E402

HEADINGS = ["## Shared context", "## Layout", "## Specs", "## Open ideas", "## Versions", "## Claude Code features in use"]


def git(root, *a):
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.root, self.home = t / "repo", t / "home"
        self.root.mkdir()
        self.home.mkdir()
        (t / "bin").mkdir()
        fake = t / "bin" / "claude"
        fake.write_text("#!/bin/sh\necho '2.1.330 (Claude Code)'\n")
        fake.chmod(0o755)
        self.env = {"HOME": str(self.home), "TC_CONTEXT_DIR": str(t / "ctx"), "TC_IDEAS_DIR": str(t / "ideas"),
                    "TC_SCOUT_DIR": str(t / "scout"), "TC_STATE": str(t / "state"),
                    "PATH": f"{t / 'bin'}:{os.environ['PATH']}"}
        self.env_patch = unittest.mock.patch.dict(os.environ, self.env)
        self.env_patch.start()
        os.environ.pop("TC_SCOUT_CLAUDE", None)
        git(self.root, "init", "-q", "-b", "main")
        (self.root / "docs/superpowers/specs").mkdir(parents=True)

    def tearDown(self):
        self.env_patch.stop()
        self.tmp.cleanup()

    def spec(self, name, text):
        p = self.root / "docs/superpowers/specs" / name
        p.write_text(text)
        return p

    def commit(self, msg):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "--allow-empty", "-m", msg)


import unittest.mock  # noqa: E402


class SpecStates(Base):
    def test_states(self):
        self.spec("2026-11-12-alpha-design.md", "# Alpha\n")
        self.spec("2026-11-13-beta-design.md", "# Beta\nStatus: superseded by x\n")
        self.spec("2026-11-14-gamma-design.md", "# Gamma\n")
        self.spec("2026-11-15-delta-design.md", "# Delta\nStatus: Implemented\n")
        self.spec("2026-11-16-eps.md", "# Eps\n")
        self.commit("docs(spec): all")
        self.commit("docs(metrics): 2026-11-12-alpha-design")
        (self.root / "docs/superpowers/ledgers/2026-11-20-eps").mkdir(parents=True)
        s = scout_pack.spec_states(self.root)
        p = "docs/superpowers/specs/"
        self.assertEqual(s[p + "2026-11-12-alpha-design.md"], "merged")
        self.assertEqual(s[p + "2026-11-13-beta-design.md"], "superseded")
        self.assertEqual(s[p + "2026-11-14-gamma-design.md"], "queued")
        self.assertEqual(s[p + "2026-11-15-delta-design.md"], "merged")
        self.assertEqual(s[p + "2026-11-16-eps.md"], "merged")

    def test_metrics_subject_on_other_branch_does_not_count(self):
        self.spec("2026-11-12-alpha-design.md", "# Alpha\n")
        self.commit("docs(spec): a")
        git(self.root, "checkout", "-q", "-b", "side")
        self.commit("docs(metrics): 2026-11-12-alpha-design")
        s = scout_pack.spec_states(self.root)
        self.assertEqual(s["docs/superpowers/specs/2026-11-12-alpha-design.md"], "queued")

    def test_no_git_repo_is_queued(self):
        d = Path(self.tmp.name) / "plain/docs/superpowers/specs"
        d.mkdir(parents=True)
        (d / "2026-11-12-a.md").write_text("# A\n")
        self.assertEqual(scout_pack.spec_states(Path(self.tmp.name) / "plain"), {"docs/superpowers/specs/2026-11-12-a.md": "queued"})


class Build(Base):
    def full(self):
        (self.root / "README.md").write_text("# x\n## Intro\nhi\n## Layout\n- board/\n- bin/\n## Other\nno\n")
        (self.root / "claude/plugin/hooks").mkdir(parents=True)
        (self.root / "claude/plugin/hooks/hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [], "Stop": []}}))
        (self.root / "claude/session-settings.json").write_text(json.dumps({"env": {}, "teammateMode": "auto"}))
        mods = self.root / "claude/plugin/mods"
        (mods / "fixtures").mkdir(parents=True)
        for n in ("index.js", "kill-guard.js", "kill-guard.test.ts"):
            (mods / n).write_text("//\n")
        self.spec("2026-11-12-alpha-design.md", "# Alpha title\n")
        Path(os.environ["TC_CONTEXT_DIR"]).mkdir(parents=True)
        (Path(os.environ["TC_CONTEXT_DIR"]) / "agent-board.md").write_text("CTXLINE\n")
        import ideas
        ideas.add("agent-board", "open idea one")
        ideas.add("agent-board", "closed idea two")
        ideas.set_status("agent-board", ideas.load("agent-board")[1]["key"], "dropped")
        pl = self.home / ".claude/plugins"
        pl.mkdir(parents=True)
        (pl / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {"foo@mkt": [{"version": "1.2.3"}]}}))
        self.commit("docs: init")

    def test_full(self):
        self.full()
        pack = scout_pack.build(self.root, 0)
        pos = [pack.index(h) for h in HEADINGS]
        self.assertEqual(pos, sorted(pos))
        self.assertIn("CTXLINE", pack)
        self.assertIn("- board/", pack)
        self.assertNotIn("no\n", pack.split("## Specs")[0].split("## Layout")[1])
        self.assertIn("docs/superpowers/specs/2026-11-12-alpha-design.md — Alpha title — queued", pack)
        self.assertIn("open idea one", pack)
        self.assertNotIn("closed idea two", pack)
        self.assertIn("2.1.330 (Claude Code)", pack)
        self.assertIn("foo@mkt 1.2.3", pack)
        self.assertIn("SessionStart", pack)
        self.assertIn("teammateMode", pack)
        mods_line = [l for l in pack.splitlines() if l.startswith("- mods:")][0]
        self.assertEqual(mods_line, "- mods: index.js, kill-guard.js")

    def test_missing_inputs_give_none(self):
        pack = scout_pack.build(self.root, 0)
        for h in HEADINGS:
            self.assertIn(h, pack)
        body = pack.split("## Shared context")[1].split("## Layout")[0]
        self.assertIn("(none)", body)
        self.assertIn("(none)", pack.split("## Open ideas")[1].split("## Versions")[0])
        self.assertIn("(none)", pack.split("## Specs")[1].split("## Open ideas")[0])
        self.assertIn("- mods: (none)", pack)

    def test_claude_failure(self):
        Path(self.tmp.name, "bin/claude").write_text("#!/bin/sh\nexit 3\n")
        self.assertIn("claude: unknown", scout_pack.build(self.root, 0))

    def test_cap(self):
        for i in range(200):
            self.spec(f"2026-01-{i:03d}-spec{i}-design.md", f"# Title {i} " + "x" * 40 + "\n")
        Path(os.environ["TC_CONTEXT_DIR"]).mkdir(parents=True)
        (Path(os.environ["TC_CONTEXT_DIR"]) / "agent-board.md").write_text(("c" * 99 + "\n") * 500)
        import ideas
        for i in range(60):
            ideas.add("agent-board", f"idea {i} " + "y" * 60)
        pack = scout_pack.build(self.root, 0)
        self.assertLessEqual(len(pack.encode()), 30720)
        for h in HEADINGS:
            self.assertIn(h, pack)
        self.assertEqual(pack.count(" — queued"), 60)

    def test_hard_cut(self):
        # a huge README Layout is not shrunk by the ordered cuts: only the hard cut saves the cap
        (self.root / "README.md").write_text("## Layout\n" + ("l" * 99 + "\n") * 600 + "## End\n")
        pack = scout_pack.build(self.root, 0)
        self.assertLessEqual(len(pack.encode()), 30720)
        self.assertTrue(pack.endswith("\n"))
        for h in HEADINGS:
            self.assertIn(h, pack)
        self.assertIn("(cut)", pack.split("## Layout")[1].split("## Specs")[0])

    def test_hard_cut_keeps_all_headings_with_big_variable_sections(self):
        import ideas
        for i in range(200):
            ideas.add("agent-board", f"idea {i} " + "z" * 200)
        ctx = Path(os.environ["TC_CONTEXT_DIR"])
        ctx.mkdir(parents=True, exist_ok=True)
        (ctx / "agent-board.md").write_text(("c" * 99 + "\n") * 520)
        for i in range(200):
            self.spec(f"2026-01-{i:03d}-s{i}-design.md", f"# Spec {i} " + "t" * 60 + "\n")
        pack = scout_pack.build(self.root, 0)
        self.assertLessEqual(len(pack.encode()), 30720)
        for h in HEADINGS:
            self.assertIn(h, pack)
        self.assertIn("2.1.330", pack.split("## Versions")[1])
        self.assertIn("more not shown)", pack.split("## Open ideas")[1].split("## Versions")[0])


if __name__ == "__main__":
    unittest.main()
