import io, json, os, subprocess, sys, tempfile, contextlib, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import sources_check  # noqa: E402
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "sources_check.py")
REAL_TAB = os.path.join(HERE, "fixtures", "sources-tab-real.md")   # Sources tab read back from the Task 9 Doc

GOOD = {"System map": {"type": "architecture", "stamp": "As built from mgr@" + "a" * 40 + ", 2026-10-20",
                       "sources": ["inventory:infra/ledger/google_sql_database_instance.ledger", "interview:1",
                                   "file:ci/x.yml:35-37"], "diagram": "091b3624-40b0"}}

def check(text):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = sources_check.main(text)
    return code, out.getvalue()

class SourcesCheck(unittest.TestCase):
    def test_valid_object(self):
        self.assertEqual(check(json.dumps(GOOD)), (0, "ok 1 sections\n"))

    def test_valid_fenced_block_in_tab_text(self):
        code, _ = check("Sources\n\n```json\n" + json.dumps(GOOD) + "\n```\n")
        self.assertEqual(code, 0)

    def test_each_problem_is_one_line(self):
        bad = {"A": {"type": "howto", "stamp": "", "sources": []},
               "B": {"type": "report", "stamp": "Report as of 2026-10-20, range a..b", "sources": ["jira:12"]}}
        code, out = check(json.dumps(bad))
        self.assertEqual(code, 1)
        self.assertEqual(sorted(out.splitlines()), sorted([
            "A: unknown type 'howto'", "A: empty stamp", "A: no sources",
            "B: source 'jira:12' matches no kind"]))

    def test_unparseable_is_exit_2(self):
        self.assertEqual(check("not json")[0], 2)

    def test_top_level_must_be_object(self):
        self.assertEqual(check("[1]")[0], 1)

    def test_kinds_accept_and_reject(self):
        cases = {
            "file:a/b.tf:12": True, "file:a/b.tf:12-14": True, "file:a/b.tf": False,
            "inventory:env:prod": True, "inventory:": False,
            "interview:3": True, "interview:x": False,
            "cloud:4": True, "cloud:": False,
            "mr:group/proj!123": True, "mr:proj123": False,
            "commit:df19131a": True, "commit:xyz1234": False, "commit:abc": False,
            "artefact:docs/superpowers/plans/p.md": True, "artefact:p.md:40": True, "artefact:": False,
            "section:System map@rev12": True, "section:System map": False,
        }
        for src, ok in cases.items():
            with self.subTest(src=src):
                self.assertEqual(sources_check.source_ok(src), ok)

    def test_non_list_sources_is_one_problem(self):
        for bad in ("file:a:1", {"k": "file:a:1"}, 5):
            with self.subTest(sources=bad):
                doc = {"A": {"type": "report", "stamp": "s", "sources": bad}}
                self.assertEqual(check(json.dumps(doc)), (1, "A: sources not a list\n"))

    def test_non_string_stamp_is_empty_stamp(self):
        for bad in (5, ["x"], {"a": 1}):
            with self.subTest(stamp=bad):
                doc = {"A": {"type": "report", "stamp": bad, "sources": ["interview:1"]}}
                self.assertEqual(check(json.dumps(doc)), (1, "A: empty stamp\n"))

    def test_trailing_newline_in_a_source_is_rejected(self):
        self.assertFalse(sources_check.source_ok("interview:1\n"))

    def test_real_captured_tab(self):
        self.assertEqual(check(open(REAL_TAB, encoding="utf-8").read()), (0, "ok 10 sections\n"))

def cli(*args):
    r = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr

class SourcesCheckCli(unittest.TestCase):
    def test_real_captured_tab_by_path(self):
        self.assertEqual(cli(REAL_TAB), (0, "ok 10 sections\n"))

    def assert_unusable(self, path):
        code, out = cli(path)
        self.assertEqual(code, 2, out)
        self.assertEqual(out.count("\n"), 1, out)
        self.assertNotIn("Traceback", out)

    def test_missing_file_is_exit_2(self):
        self.assert_unusable("/nonexistent/sources.md")

    def test_unreadable_path_is_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            self.assert_unusable(d)

    def test_non_utf8_file_is_exit_2(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"\xff\xfe\x00bad")
        try:
            self.assert_unusable(f.name)
        finally:
            os.unlink(f.name)
