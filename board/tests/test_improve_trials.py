import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_store as S  # noqa: E402
import improve_trials as T  # noqa: E402
import improve_fixtures as F  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EV = [{"type": "run", "ref": "r1"}]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def diff(path, old, new):
    """A real unified diff of one file, made by git."""
    d = tempfile.mkdtemp()
    a, b = Path(d, "a", path), Path(d, "b", path)
    a.parent.mkdir(parents=True); b.parent.mkdir(parents=True)
    a.write_text(old); b.write_text(new)
    r = subprocess.run(["git", "diff", "--no-index", "--no-color", f"a/{path}", f"b/{path}"], cwd=d, capture_output=True, text=True)
    shutil.rmtree(d)
    return r.stdout.replace(f"a/a/{path}", f"a/{path}").replace(f"b/b/{path}", f"b/{path}")


class SplitTest(unittest.TestCase):
    def test_split_is_balanced_and_stable(self):
        # mutation: % 3 -> count falls to ~33, outside 40..60
        ids = [f"docs/superpowers/specs/s{i}.md" for i in range(100)]
        n = sum(T.in_trial(s, "P1") for s in ids)
        self.assertTrue(40 <= n <= 60, n)
        self.assertEqual(n, sum(T.in_trial(s, "P1") for s in ids))

    def test_split_follows_spec_formula(self):
        h = int(hashlib.sha256(("s1" + "P2").encode()).hexdigest(), 16) % 2 == 0
        self.assertEqual(T.in_trial("s1", "P2"), h)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp, self.state, self.repo = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"TC_ENGINE_DIR": self.tmp, "TC_STATE": self.state, "TC_OBSERVER_DIR": self.state})
        self.env.start()
        F.engine_db(self.tmp)
        self.s = S.Store("proj")
        self.addCleanup(lambda: [shutil.rmtree(d, ignore_errors=True) for d in (self.tmp, self.state, self.repo)])
        self.addCleanup(self.env.stop)
        # a spec id that is in P1's trial half and one that is out
        self.inn = next(f"s{i}" for i in range(200) if T.in_trial(f"s{i}", "P1"))
        self.out = next(f"s{i}" for i in range(200) if not T.in_trial(f"s{i}", "P1"))

    def put(self, rel, text):
        p = Path(self.repo, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def trial(self, kind, target, patch):
        pid = self.s.insert("manual", kind, target, patch, EV)
        self.s.transition(pid, "trial", "go")
        return pid

    def variants(self, spec):
        return T.variants(spec, self.s, repo=Path(self.repo))


class VariantsTest(Base):
    def test_overlay_for_rule_patch(self):
        old = "# Top\nintro\n## Rules\nold line\nkeep\n## Other\nx\n"
        new = old.replace("old line", "new line")
        f = self.put("claude/x.md", old)
        pid = self.trial("rule", "claude/x.md", diff("claude/x.md", old, new))
        self.assertEqual(pid, "P1")
        before = sha(f)
        v = self.variants(self.inn)
        self.assertEqual(v["spec"], self.inn)
        (e,) = v["variants"]
        self.assertEqual((e["id"], e["kind"], e["target"]), ("P1", "rule", "claude/x.md"))
        self.assertEqual(e["overlay"], "## Trial P1\n## Rules\nnew line\nkeep\n(This replaces the section ## Rules of claude/x.md.)")
        self.assertEqual(sha(f), before)   # mutation: apply in place -> sha differs

    def test_control_spec_gets_no_variants(self):
        old = "# T\na\n"
        self.put("claude/x.md", old)
        self.trial("rule", "claude/x.md", diff("claude/x.md", old, "# T\nb\n"))
        self.assertEqual(self.variants(self.out), {"spec": self.out, "variants": []})

    def test_skill_copy(self):
        old = "# S\na\n"
        self.put("claude/skills/foo/SKILL.md", old)
        pid = self.trial("skill", "claude/skills/foo/SKILL.md", diff("claude/skills/foo/SKILL.md", old, "# S\nb\n"))
        (e,) = self.variants(self.inn)["variants"]
        self.assertEqual(e["skill_copy"], {"from": "claude/skills/foo", "to": ".superpowers/improve/skills/foo@P1",
                                           "patch": str(S.patches_dir("proj") / "P1.diff")})
        self.assertTrue(Path(e["skill_copy"]["patch"]).is_file())

    def test_routing_and_code_mode(self):
        old = '{\n  "mechanical": "haiku",\n  "standard": "sonnet"\n}\n'
        new = '{\n  "mechanical": "haiku",\n  "standard": "sonnet",\n  "codeMode": true\n}\n'
        self.put("docs/superpowers/model-routing.json", old)
        self.trial("routing", "docs/superpowers/model-routing.json", diff("docs/superpowers/model-routing.json", old, new))
        (e,) = self.variants(self.inn)["variants"]
        self.assertEqual(e["routing"], {"mechanical": "haiku", "standard": "sonnet", "codeMode": True})
        self.assertEqual(e["env"], {"CLAUDE_CODE_EXPERIMENTAL_CODE_MODE": "1"})
        self.assertEqual(e["applies_to"], {"tier": "mechanical", "kind": "implement"})

    def test_plain_routing_has_no_env(self):
        old = '{\n  "mechanical": "haiku"\n}\n'
        new = '{\n  "mechanical": "sonnet"\n}\n'
        self.put("docs/superpowers/model-routing.json", old)
        self.trial("routing", "docs/superpowers/model-routing.json", diff("docs/superpowers/model-routing.json", old, new))
        (e,) = self.variants(self.inn)["variants"]
        self.assertEqual(e["routing"], {"mechanical": "sonnet"})
        self.assertNotIn("env", e)

    def test_stale_patch_is_rejected_and_left_out(self):
        old = "# T\na\n"
        f = self.put("claude/x.md", old)
        self.trial("rule", "claude/x.md", diff("claude/x.md", old, "# T\nb\n"))
        f.write_text("# T\nchanged since\n")
        before = sha(f)
        self.assertEqual(self.variants(self.inn)["variants"], [])
        p = self.s.get("P1")
        self.assertEqual((p["state"], p["reason"]), ("rejected", "stale patch"))
        self.assertEqual(sha(f), before)
        n = len([1 for _ in self.s._conn().execute("SELECT 1 FROM events WHERE kind='improve'")])
        self.assertEqual(n, 3)   # insert, trial, stale rejection

    def test_only_trial_state_counts(self):
        old = "# T\na\n"
        self.put("claude/x.md", old)
        self.s.insert("manual", "rule", "claude/x.md", diff("claude/x.md", old, "# T\nb\n"), EV)   # stays proposed
        self.assertEqual(self.variants(self.inn)["variants"], [])


class StaleTest(Base):
    def rejected(self, pid="P1"):
        p = self.s.get(pid)
        return (p["state"], p["reason"])

    def test_dotdot_patch_writes_nothing_and_is_rejected(self):
        sib = Path(self.repo).parent / f"victim-{os.getpid()}.txt"
        sib.write_text("orig\n")
        self.addCleanup(lambda: sib.unlink() if sib.exists() else None)
        self.put("claude/x.md", "# T\na\n")
        patch = f"--- a/../{sib.name}\n+++ b/../{sib.name}\n@@ -1 +1 @@\n-orig\n+PWNED\n"
        self.trial("rule", "claude/x.md", patch)
        self.assertEqual(self.variants(self.inn)["variants"], [])
        self.assertEqual(sib.read_text(), "orig\n")
        self.assertEqual(self.rejected(), ("rejected", "stale patch"))

    def test_absolute_patch_path_is_rejected(self):
        self.put("claude/x.md", "# T\na\n")
        self.trial("rule", "claude/x.md", "--- a//etc/hosts\n+++ b//etc/hosts\n@@ -1 +1 @@\n-a\n+b\n")
        self.assertEqual(self.variants(self.inn)["variants"], [])
        self.assertEqual(self.rejected(), ("rejected", "stale patch"))

    def test_bad_routing_json_is_stale(self):
        old = '{\n  "mechanical": "haiku"\n}\n'
        self.put("docs/superpowers/model-routing.json", old)
        self.trial("routing", "docs/superpowers/model-routing.json",
                   diff("docs/superpowers/model-routing.json", old, '{\n  "mechanical": \n}\n'))
        self.assertEqual(self.variants(self.inn)["variants"], [])
        self.assertEqual(self.rejected(), ("rejected", "stale patch"))

    def test_patch_that_creates_its_target_is_stale(self):
        patch = "--- /dev/null\n+++ b/claude/new.md\n@@ -0,0 +1 @@\n+hello\n"
        self.trial("rule", "claude/new.md", patch)
        self.assertEqual(self.variants(self.inn)["variants"], [])
        self.assertEqual(self.rejected(), ("rejected", "stale patch"))

    def test_skill_target_without_skills_part_is_stale(self):
        old = "# S\na\n"
        self.put("claude/other/SKILL.md", old)
        self.trial("skill", "claude/other/SKILL.md", diff("claude/other/SKILL.md", old, "# S\nb\n"))
        self.assertEqual(self.variants(self.inn)["variants"], [])
        self.assertEqual(self.rejected(), ("rejected", "stale patch"))


class ContentLookalikeTest(Base):
    def one(self, old, new, rel="claude/x.md"):
        self.put(rel, old)
        self.trial("rule", rel, diff(rel, old, new))
        return self.variants(self.inn)

    def test_removed_dash_dash_content_line_applies(self):
        # a removed line `-- x` shows as `--- x` in the patch: not a file header
        v = self.one("# T\n-- \nkeep\n", "# T\nkeep\n")
        self.assertEqual(self.s.get("P1")["state"], "trial")
        self.assertIn("keep", v["variants"][0]["overlay"])

    def test_added_plus_plus_content_line_applies(self):
        v = self.one("# T\nkeep\n", "# T\n++ \nkeep\n")
        self.assertEqual(self.s.get("P1")["state"], "trial")
        self.assertIn("++ \n", v["variants"][0]["overlay"])

    def test_removed_dotdot_content_line_is_not_an_unsafe_path(self):
        v = self.one("# T\n-- ../x\nkeep\n", "# T\nkeep\n")
        self.assertEqual(len(v["variants"]), 1)
        self.assertEqual(self.s.get("P1")["state"], "trial")

    def test_first_change_ignores_lookalike_lines(self):
        old = "# A\n-- x\n## B\nkeep\nmore\n"
        v = self.one(old, old.replace("keep", "new"))
        self.assertTrue(v["variants"][0]["overlay"].startswith("## Trial P1\n## B\nnew"))


class CliTest(Base):
    def test_variants_json_on_the_cli(self):
        # the real command, unpatched, against the scratch engine db; no trial -> empty list
        r = subprocess.run([sys.executable, "-I", str(REPO / "board/improve.py"), "--project", "proj", "variants", "specX", "--json"],
                           capture_output=True, text=True, env={**os.environ})
        self.assertEqual((r.returncode, json.loads(r.stdout)), (0, {"spec": "specX", "variants": []}), r.stderr)


if __name__ == "__main__":
    unittest.main()
