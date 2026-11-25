import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import improve_class as C  # noqa: E402

PROSE = """--- a/claude/skills/x/SKILL.md
+++ b/claude/skills/x/SKILL.md
@@ -3,3 +3,3 @@
 ## Procedure
-Read the plan first.
+Read the plan and its spec first.
 More prose.
"""
FENCE = PROSE.replace(" More prose.\n", " ```\n+echo hi\n ```\n")
FRONT = """--- a/s/SKILL.md
+++ b/s/SKILL.md
@@ -1,3 +1,3 @@
 ---
-name: old
+name: new
 ---
"""
CMD = PROSE.replace("+Read the plan and its spec first.", "+$ tmux-ctl run tests")
# target file for PROSE: its hunk starts at old line 3, with no frontmatter and no fence
TARGET_PROSE = "a\nb\n## Procedure\nRead the plan first.\nMore prose.\n"
# review probe 1: frontmatter edit in a hunk at -3; the opening --- is at line 1, outside the hunk
FM_MID = """--- a/claude/skills/x/SKILL.md
+++ b/claude/skills/x/SKILL.md
@@ -3,3 +3,3 @@
-description: old
+description: new trigger
 ---
 more
"""
TARGET_FM = "---\nname: x\ndescription: old\n---\nmore\n"
# review probe 2: new file whose frontmatter is added (@@ -0,0)
FM_NEW = """--- /dev/null
+++ b/claude/skills/x/SKILL.md
@@ -0,0 +1,4 @@
+---
+name: x
+description: y
+---
"""
# review probe 3: edit inside a fence, with no fence marker in the hunk
FENCE_BODY = "intro\n```\nbar baz\n```\n"
FENCE_EDIT = """--- a/claude/skills/x/SKILL.md
+++ b/claude/skills/x/SKILL.md
@@ -3,1 +3,1 @@
-bar baz
+bar qux
"""


class T(unittest.TestCase):
    def test_protected_globs(self):  # mutation: return False in is_protected -> fails
        for t in ["board/metrics.py", "docs/superpowers/metrics/configs/a.md", "docs/superpowers/outcomes/O1.json",
                  "docs/superpowers/improve/protected.txt", "claude/orchestrator.md", "claude/worker.md",
                  "claude/plugin/hooks/hooks.json", "claude/plugin/mods/x.js", ".claude/settings.local.json",
                  "board/improve.py", "board/improve_eval.py", "tools/lib/improve.zsh"]:
            self.assertTrue(C.is_protected(t), t)
        self.assertFalse(C.is_protected("docs/superpowers/model-routing.json"))
        self.assertFalse(C.is_protected("claude/skills/x/SKILL.md"))

    def test_protected_file(self):  # mutation: drop one C6 line from protected.txt -> fails
        g = C.globs()
        self.assertEqual(len(g), 19)
        self.assertIn("engine/lib/engine/hold.js", g)
        self.assertEqual(g[-1], "bin/tmux-ctl#improve")

    def test_vectors(self):  # mutation: drop the six C6 lines from protected.txt -> the engine/lib/engine/hold.js vector fails
        v = json.loads((C.REPO / "docs/superpowers/improve/glob-vectors.json").read_text())
        self.assertGreaterEqual(len(v["protected"]) + len(v["not_protected"]), 29)
        for t in v["protected"]:
            self.assertTrue(C.is_protected(t), t)
        for t in v["not_protected"]:
            self.assertFalse(C.is_protected(t), t)

    def test_home_settings(self):  # mutation: drop expanduser -> fails
        self.assertTrue(C.is_protected(str(Path.home() / ".claude/settings.json")))

    def test_tmux_ctl_improve_section(self):  # mutation: treat every bin/tmux-ctl hunk alike -> one assert fails
        src = "a)\n  x ;;\n  improve)\n    exec y ;;\n  z)\n"
        inside = "--- a/bin/tmux-ctl\n+++ b/bin/tmux-ctl\n@@ -4,1 +4,1 @@\n-    exec y ;;\n+    exec w ;;\n"
        outside = "--- a/bin/tmux-ctl\n+++ b/bin/tmux-ctl\n@@ -2,1 +2,1 @@\n-  x ;;\n+  q ;;\n"
        self.assertTrue(C.is_protected("bin/tmux-ctl", inside, src))
        self.assertFalse(C.is_protected("bin/tmux-ctl", outside, src))

    def test_order(self):
        self.assertEqual(C.derive("procedure", "board/metrics.py", PROSE), "protected")   # target first
        self.assertEqual(C.derive("permission", "claude/skills/x/SKILL.md", PROSE), "protected")
        self.assertEqual(C.derive("memory", "claude/skills/x/SKILL.md", None), "observation")
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", PROSE, target_text=TARGET_PROSE), "low")
        for k in ["skill", "rule", "prompt", "routing", "spec", "retire"]:
            self.assertEqual(C.derive(k, "claude/skills/x/SKILL.md", PROSE), "high", k)

    def test_prose_only(self):  # mutation: prose_only returns True -> fails
        for p in [FENCE, FRONT, CMD, None]:
            self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", p), "high")

    def test_mid_file_hunk_without_target_is_high(self):  # mutation: drop the start-line-1 rule -> fails
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", PROSE), "high")

    def test_frontmatter_mid_file_hunk_is_high(self):  # review probe 1: frontmatter edit in a hunk at -3
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", FM_MID, target_text=TARGET_FM), "high")
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", FM_MID), "high")

    def test_new_file_frontmatter_is_high(self):  # review probe 2: @@ -0,0 adds a frontmatter block
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", FM_NEW, target_text=""), "high")
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", FM_NEW), "high")

    def test_fence_edit_without_marker_is_high(self):  # review probe 3: edit inside a fence, no marker in the hunk
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", FENCE_EDIT, target_text=FENCE_BODY), "high")
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", FENCE_EDIT), "high")

    def test_dream_never_low(self):  # mutation: ignore source -> fails
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", PROSE, source="dream"), "high")
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", PROSE, source="observer"), "high")


if __name__ == "__main__":
    unittest.main()
