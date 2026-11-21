import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discover_repo  # noqa: E402

NOW = datetime(2026, 11, 21, 12, 0, 0)


def git(root, *args, date=None):
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root), *args],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def new_repo(tmp):
    root = Path(tmp)
    git(root, "init", "-q", "-b", "main")
    return root


def commit(root, files, msg="c", days_ago=0):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(root, "add", "-A")
    d = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")
    git(root, "commit", "-q", "-m", msg, date=d)
    return git(root, "rev-parse", "HEAD")


def ledger(root, name, text):
    d = root / "docs" / "superpowers" / "ledgers" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "progress.md").write_text(text)


class RepeatedRulingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_three_ledgers_same_six_words(self):
        for i, n in enumerate(["2026-10-01-a", "2026-10-05-b", "2026-10-09-c"]):
            ledger(self.root, n, f"Ruling: board suite count criterion is baseline plus {i} — cost if wrong: none.\n")
        c = discover_repo.repeated_rulings(self.root)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["signal"], "repeated_ruling")
        self.assertEqual(c[0]["count"], 3)
        self.assertEqual(c[0]["key"], "repeated_ruling:board-suite-count-criterion-is-baseline")
        self.assertEqual(c[0]["first_seen"], "2026-10-01")

    def test_two_ledgers_none(self):
        for n in ["2026-10-01-a", "2026-10-05-b"]:
            ledger(self.root, n, "Ruling: board suite count criterion is baseline plus one\n")
        self.assertEqual(discover_repo.repeated_rulings(self.root), [])

    def test_group_b_same_path_first_three_words(self):
        for i, n in enumerate(["2026-10-01-a", "2026-10-05-b", "2026-10-09-c"]):
            ledger(self.root, n, f"Ruling: leave the legacy copy {'x' * (i + 1)} board/server.py as it is\n")
        # first 6 words differ (x, xx, xxx), first 3 words and cited path are shared
        c = discover_repo.repeated_rulings(self.root)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["key"], "repeated_ruling:board/server.py:leave-the-legacy")
        self.assertEqual(c[0]["count"], 3)

    def test_line_in_at_most_one_candidate(self):
        # all three share 6 words AND the path+3 words: group A takes them, B must not repeat them
        for n in ["2026-10-01-a", "2026-10-05-b", "2026-10-09-c"]:
            ledger(self.root, n, "Ruling: keep the legacy copy in board/server.py untouched\n")
        c = discover_repo.repeated_rulings(self.root)
        self.assertEqual(len(c), 1)
        self.assertTrue(c[0]["key"].startswith("repeated_ruling:keep-the-legacy"))
        self.assertNotIn("board/server.py", c[0]["key"])

    def test_cost_tail_and_task_prefix_do_not_change_key(self):
        texts = ["Ruling: fix the plan verbatim insert helper now — cost if wrong: a",
                 "Task 1: Ruling: fix the plan verbatim insert helper now - cost if wrong: b",
                 "Task 9: Ruling: Fix the plan verbatim insert helper now"]
        for n, t in zip(["2026-10-01-a", "2026-10-05-b", "2026-10-09-c"], texts):
            ledger(self.root, n, t + "\n")
        c = discover_repo.repeated_rulings(self.root)
        self.assertEqual([x["key"] for x in c], ["repeated_ruling:fix-the-plan-verbatim-insert-helper"])

    def test_evidence_has_path_line_and_url_none_without_remote(self):
        for n in ["2026-10-01-a", "2026-10-05-b", "2026-10-09-c"]:
            ledger(self.root, n, "intro\nRuling: one two three four five six seven\n")
        ev = discover_repo.repeated_rulings(self.root)[0]["evidence"]
        self.assertEqual(len(ev), 3)
        self.assertEqual(ev[0]["path"], "docs/superpowers/ledgers/2026-10-01-a/progress.md")
        self.assertEqual(ev[0]["line"], 2)

    def test_missing_ledgers_dir(self):
        self.assertEqual(discover_repo.repeated_rulings(self.root), [])

    def test_url_with_github_origin_and_none_without(self):
        git(self.root, "init", "-q", "-b", "main") if not (self.root / ".git").exists() else None
        for n in ["2026-10-01-a", "2026-10-05-b", "2026-10-09-c"]:
            ledger(self.root, n, "Ruling: one two three four five six seven\n")
        head = commit(self.root, {"f": "x\n"}, "c")
        self.assertTrue(all(e["url"] is None for e in discover_repo.repeated_rulings(self.root)[0]["evidence"]))
        git(self.root, "remote", "add", "origin", "https://github.com/o/r.git")
        ev = discover_repo.repeated_rulings(self.root)[0]["evidence"]
        self.assertEqual(ev[0]["url"], f"https://github.com/o/r/blob/{head}/docs/superpowers/ledgers/2026-10-01-a/progress.md#L1")


class LinkTest(unittest.TestCase):
    def remote(self, url):
        def run(argv, **kw):
            if argv[:2] == ["git", "-C"] and "get-url" in argv:
                return SimpleNamespace(returncode=0 if url else 2, stdout=(url or "") + "\n", stderr="")
            raise AssertionError(argv)
        return run

    def test_forms(self):
        cases = [
            ("https://github.com/o/r.git", "https://github.com/o/r/blob/abc/a/b.py#L7"),
            ("https://github.com/o/r", "https://github.com/o/r/blob/abc/a/b.py#L7"),
            ("git@github.com:o/r.git", "https://github.com/o/r/blob/abc/a/b.py#L7"),
            ("ssh://git@github.com/o/r.git", "https://github.com/o/r/blob/abc/a/b.py#L7"),
            ("git@gitlab.com:g/s/r.git", "https://gitlab.com/g/s/r/-/blob/abc/a/b.py#L7"),
            ("https://gitlab.com/g/r.git", "https://gitlab.com/g/r/-/blob/abc/a/b.py#L7"),
            ("https://example.com/o/r.git", None),
            (None, None),
        ]
        for url, want in cases:
            with self.subTest(url=url):
                self.assertEqual(discover_repo.link("/x", "abc", "a/b.py", 7, run=self.remote(url)), want)

    def test_no_head_is_none(self):
        self.assertIsNone(discover_repo.link("/x", None, "a", 1, run=self.remote("https://github.com/o/r")))

    def test_real_git_origin(self):
        with tempfile.TemporaryDirectory() as t:
            root = new_repo(t)
            git(root, "remote", "add", "origin", "git@github.com:o/r.git")
            self.assertEqual(discover_repo.link(root, "h", "p.py", 3), "https://github.com/o/r/blob/h/p.py#L3")


class DeferredMinorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = new_repo(self.tmp.name)
        commit(self.root, {"board/x.py": "a\n"}, "init", days_ago=30)

    def tearDown(self):
        self.tmp.cleanup()

    def touch_later(self):
        return commit(self.root, {"board/x.py": "a\nb\n"}, "later", days_ago=5)

    def test_touched_not_fixed(self):
        ledger(self.root, "2026-11-01-p", "Task 2: minor (deferred): board/x.py uses a bare except\n")
        self.touch_later()
        c = discover_repo.deferred_minors(self.root)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["signal"], "deferred_minor")
        self.assertTrue(c[0]["key"].startswith("deferred_minor:2026-11-01-p:"))
        self.assertEqual(c[0]["count"], 1)
        self.assertEqual(c[0]["first_seen"], "2026-11-01")
        self.assertEqual(c[0]["evidence"][0]["path"], "docs/superpowers/ledgers/2026-11-01-p/progress.md")

    def test_later_ledger_fix_line_clears_it(self):
        ledger(self.root, "2026-11-01-p", "Task 2: minor (deferred): board/x.py uses a bare except\n")
        ledger(self.root, "2026-11-10-q", "Task 4: board/x.py bare except fixed\n")
        self.touch_later()
        self.assertEqual(discover_repo.deferred_minors(self.root), [])

    def test_no_path_none(self):
        ledger(self.root, "2026-11-01-p", "Task 2: minor (deferred): exit-code checks assert non-zero, not literally 2\n")
        self.touch_later()
        self.assertEqual(discover_repo.deferred_minors(self.root), [])

    def test_commit_mentioned_in_ledger_is_not_new(self):
        sha = self.touch_later()
        ledger(self.root, "2026-11-01-p", f"Task 2: minor (deferred): board/x.py bare except (see {sha[:7]})\n")
        self.assertEqual(discover_repo.deferred_minors(self.root), [])

    def test_untouched_after_ledger_date_none(self):
        ledger(self.root, "2026-11-20-p", "Task 2: deferred: board/x.py bare except\n")
        self.assertEqual(discover_repo.deferred_minors(self.root), [])

    def test_path_not_at_head_none(self):
        commit(self.root, {"board/gone.py": "g\n"}, "add gone", days_ago=10)
        git(self.root, "rm", "-q", "board/gone.py")
        commit(self.root, {}, "remove gone", days_ago=5)   # a later commit touches the path, but HEAD lacks it
        ledger(self.root, "2026-11-01-p", "Task 2: parked: board/gone.py is odd\n")
        self.assertEqual(discover_repo.deferred_minors(self.root), [])

    def test_missing_ledgers_dir(self):
        self.assertEqual(discover_repo.deferred_minors(self.root), [])

    def test_url_with_github_origin_and_none_without(self):
        ledger(self.root, "2026-11-01-p", "Task 2: minor (deferred): board/x.py uses a bare except\n")
        head = self.touch_later()
        self.assertIsNone(discover_repo.deferred_minors(self.root)[0]["evidence"][0]["url"])
        git(self.root, "remote", "add", "origin", "git@github.com:o/r.git")
        self.assertEqual(discover_repo.deferred_minors(self.root)[0]["evidence"][0]["url"],
                         f"https://github.com/o/r/blob/{head}/docs/superpowers/ledgers/2026-11-01-p/progress.md#L1")


class TodosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = new_repo(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_recent_still_present(self):
        commit(self.root, {"a.py": "x = 1\n"}, "init", days_ago=50)
        commit(self.root, {"a.py": "x = 1\n# TODO: tighten this\n"}, "todo", days_ago=3)
        c = discover_repo.todos(self.root, NOW)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["signal"], "todo")
        self.assertEqual(c[0]["count"], 1)
        self.assertEqual(c[0]["first_seen"], "2026-11-18")
        self.assertTrue(c[0]["key"].startswith("todo:a.py:"))
        self.assertEqual(c[0]["evidence"][0]["path"], "a.py")
        self.assertEqual(c[0]["evidence"][0]["line"], 2)

    def test_removed_later_none(self):
        commit(self.root, {"a.py": "x = 1\n# TODO: tighten this\n"}, "todo", days_ago=5)
        commit(self.root, {"a.py": "x = 1\n"}, "done", days_ago=1)
        self.assertEqual(discover_repo.todos(self.root, NOW), [])

    def test_older_than_30_days_none(self):
        commit(self.root, {"a.py": "x = 1\n# FIXME old\n"}, "todo", days_ago=40)
        self.assertEqual(discover_repo.todos(self.root, NOW), [])

    def test_markdown_none(self):
        commit(self.root, {"n.md": "- TODO write this\n"}, "md", days_ago=2)
        self.assertEqual(discover_repo.todos(self.root, NOW), [])

    def test_key_stable_when_line_moves(self):
        commit(self.root, {"a.py": "x = 1\n# TODO: tighten this\n"}, "todo", days_ago=5)
        k1 = discover_repo.todos(self.root, NOW)[0]["key"]
        commit(self.root, {"a.py": "y = 2\nz = 3\nx = 1\n# TODO: tighten this\n"}, "move", days_ago=2)
        c = discover_repo.todos(self.root, NOW)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["key"], k1)
        self.assertEqual(c[0]["evidence"][0]["line"], 4)

    def test_marker_in_string_literal_none(self):
        commit(self.root, {"a.py": 'msg = "TODO: later"\nx = "FIXME"\n'}, "str", days_ago=2)
        self.assertEqual(discover_repo.todos(self.root, NOW), [])

    def test_marker_in_tests_dir_none(self):
        commit(self.root, {"board/tests/x.py": "# TODO: fixture\n", "test/y.js": "// FIXME fixture\n"}, "t", days_ago=2)
        self.assertEqual(discover_repo.todos(self.root, NOW), [])

    def test_comment_forms_count(self):
        commit(self.root, {"a.py": "x = 1  # TODO: inline\n", "b.js": "f()  // FIXME later\n",
                           "c.css": "/* XXX hack */\n", "d.js": "/**\n * TODO: doc\n */\n",
                           "e.html": "<!-- TODO: markup -->\n", "f.sql": "select 1 -- TODO: cte\n",
                           "g.py": "# plain\n", "tests_helper.py": "# TODO: file name only\n"}, "c", days_ago=2)
        paths = sorted(c["evidence"][0]["path"] for c in discover_repo.todos(self.root, NOW))
        self.assertEqual(paths, ["a.py", "b.js", "c.css", "d.js", "e.html", "f.sql", "tests_helper.py"])

    def test_url_with_github_origin_and_none_without(self):
        head = commit(self.root, {"a.py": "x = 1\n# TODO: tighten\n"}, "todo", days_ago=2)
        self.assertIsNone(discover_repo.todos(self.root, NOW)[0]["evidence"][0]["url"])
        git(self.root, "remote", "add", "origin", "https://github.com/o/r.git")
        self.assertEqual(discover_repo.todos(self.root, NOW)[0]["evidence"][0]["url"],
                         f"https://github.com/o/r/blob/{head}/a.py#L2")

    def test_goes_through_run(self):
        commit(self.root, {"a.py": "# TODO: q\n"}, "todo", days_ago=1)
        seen = []

        def run(argv, **kw):
            seen.append(argv[0])
            return subprocess.run(argv, **kw)
        discover_repo.todos(self.root, NOW, run=run)
        self.assertTrue(seen and set(seen) == {"git"})


def fake_run(table, calls=None):
    """table: list of (argv prefix, (rc, stdout, stderr)); first match wins; no match -> rc 1."""
    def run(argv, **kw):
        if calls is not None:
            calls.append((list(argv), kw.get("cwd")))
        for prefix, (rc, out, err) in table:
            if list(argv[:len(prefix)]) == prefix:
                return SimpleNamespace(returncode=rc, stdout=out, stderr=err)
        return SimpleNamespace(returncode=1, stdout="", stderr="")
    return run


GH_REMOTE = (["git", "-C"], (0, "https://github.com/o/r.git\n", ""))


class DependenciesTest(unittest.TestCase):
    def remote_and_lock(self, lock="tools/discord-bridge/package-lock.json\n", remote="https://github.com/o/r.git\n"):
        def run_table(extra):
            def run(argv, **kw):
                self.calls.append((list(argv), kw.get("cwd")))
                if "get-url" in argv:
                    return SimpleNamespace(returncode=0 if remote else 2, stdout=remote, stderr="")
                if "ls-files" in argv:
                    return SimpleNamespace(returncode=0, stdout=lock, stderr="")
                for prefix, (rc, out, err) in extra:
                    if list(argv[:len(prefix)]) == prefix:
                        return SimpleNamespace(returncode=rc, stdout=out, stderr=err)
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            return run
        return run_table

    def setUp(self):
        self.calls = []

    def npm_json(self, **sev):
        return json.dumps({"auditReportVersion": 2, "metadata": {},
                           "vulnerabilities": {k: {"severity": v, "via": [], "range": "<2"} for k, v in sev.items()}})

    def test_npm_moderate_candidate_low_none(self):
        run = self.remote_and_lock(remote="")([(["npm", "audit"], (1, self.npm_json(ws="moderate", lo="low", hi="high"), ""))])
        cands, skipped = discover_repo.dependencies("/r", run=run)
        self.assertEqual(sorted(c["key"] for c in cands),
                         ["dependency:npm:tools/discord-bridge:hi", "dependency:npm:tools/discord-bridge:ws"])
        self.assertTrue(all(c["signal"] == "dependency" and c["count"] == 1 for c in cands))
        self.assertEqual(skipped, [])
        npm_calls = [c for c in self.calls if c[0][0] == "npm"]
        self.assertEqual(len(npm_calls), 1)
        self.assertTrue(npm_calls[0][1].endswith("tools/discord-bridge"))

    def test_gh_403_skipped_and_npm_still_runs(self):
        run = self.remote_and_lock()([
            (["gh", "auth", "status"], (0, "", "")),
            (["gh", "api"], (1, "", "gh: Dependabot alerts are disabled for this repository. (HTTP 403)\n")),
            (["npm", "audit"], (0, self.npm_json(ws="moderate"), "")),
        ])
        cands, skipped = discover_repo.dependencies("/r", run=run)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["signal"], "dependency")
        self.assertTrue(skipped[0]["why"].startswith("gh: Dependabot alerts are disabled"), skipped)
        self.assertEqual([c["key"] for c in cands], ["dependency:npm:tools/discord-bridge:ws"])

    def test_gh_alerts_to_candidates(self):
        alerts = [{"number": 7, "state": "open", "html_url": "https://github.com/o/r/security/dependabot/7",
                   "security_advisory": {"severity": "high", "summary": "Bad thing", "ghsa_id": "GHSA-x"},
                   "dependency": {"package": {"name": "left-pad", "ecosystem": "npm"}}},
                  {"number": 8, "state": "open", "html_url": "u8",
                   "security_advisory": {"severity": "low", "summary": "Meh", "ghsa_id": "GHSA-y"},
                   "dependency": {"package": {"name": "tiny", "ecosystem": "npm"}}}]
        run = self.remote_and_lock(lock="")([(["gh", "auth", "status"], (0, "", "")),
                                             (["gh", "api"], (0, json.dumps(alerts), ""))])
        cands, skipped = discover_repo.dependencies("/r", run=run)
        self.assertEqual([c["key"] for c in cands], ["dependency:github:7"])
        self.assertIn("left-pad", cands[0]["title"])
        self.assertEqual(cands[0]["evidence"][0]["url"], "https://github.com/o/r/security/dependabot/7")
        self.assertEqual(skipped, [])
        api = [c for c in self.calls if c[0][:2] == ["gh", "api"]][0][0]
        self.assertIn("repos/o/r/dependabot/alerts?state=open&per_page=100", api)

    def test_gh_not_authenticated_skipped(self):
        run = self.remote_and_lock(lock="")([(["gh", "auth", "status"], (1, "", "You are not logged in\n"))])
        cands, skipped = discover_repo.dependencies("/r", run=run)
        self.assertEqual(cands, [])
        self.assertEqual(skipped[0]["why"], "gh: You are not logged in")

    def test_no_lockfile_no_remote_does_not_raise(self):
        run = self.remote_and_lock(lock="", remote="")([])
        cands, skipped = discover_repo.dependencies("/r", run=run)
        self.assertEqual(cands, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["signal"], "dependency")

    def test_missing_binary_is_skipped_not_raised(self):
        def run(argv, **kw):
            if "get-url" in argv:
                return SimpleNamespace(returncode=2, stdout="", stderr="")
            if "ls-files" in argv:
                return SimpleNamespace(returncode=0, stdout="package-lock.json\n", stderr="")
            raise FileNotFoundError(argv[0])
        cands, skipped = discover_repo.dependencies("/r", run=run)
        self.assertEqual(cands, [])
        self.assertTrue(any("npm" in s["why"] for s in skipped), skipped)

    def test_pip_audit_vulns(self):
        pj = json.dumps({"dependencies": [{"name": "flask", "version": "1", "vulns": [{"id": "PYSEC-1", "fix_versions": ["2"]}]},
                                          {"name": "ok", "version": "1", "vulns": []}]})
        run = self.remote_and_lock(lock="requirements.txt\n", remote="")([(["pip-audit"], (1, pj, ""))])
        cands, _ = discover_repo.dependencies("/r", run=run)
        self.assertEqual([c["key"] for c in cands], ["dependency:pip:flask:PYSEC-1"])

    def test_pip_audit_absent_is_silent(self):
        def run(argv, **kw):
            if "get-url" in argv:
                return SimpleNamespace(returncode=2, stdout="", stderr="")
            if "ls-files" in argv:
                return SimpleNamespace(returncode=0, stdout="requirements.txt\n", stderr="")
            raise FileNotFoundError(argv[0])
        cands, skipped = discover_repo.dependencies("/r", run=run)
        self.assertEqual(cands, [])
        self.assertEqual([s for s in skipped if "pip" in s["why"]], [])


class StaleIdeasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("TC_IDEAS_DIR")
        os.environ["TC_IDEAS_DIR"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("TC_IDEAS_DIR", None)
        else:
            os.environ["TC_IDEAS_DIR"] = self.old
        self.tmp.cleanup()

    def write(self, *lines):
        (Path(self.tmp.name) / "proj.md").write_text("# Ideas: proj\n\n" + "\n".join(lines) + "\n")

    def ts(self, days):
        return (NOW - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")

    def test_open_31_days_candidate(self):
        self.write(f"- [ ] {self.ts(31)} · tidy the board")
        c = discover_repo.stale_ideas("proj", NOW)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["signal"], "stale_idea")
        self.assertEqual(c[0]["count"], 31)
        self.assertEqual(len(c[0]["key"]), len("stale_idea:") + 12)
        self.assertIn("tidy the board", c[0]["title"])
        self.assertEqual(c[0]["first_seen"], self.ts(31)[:10])

    def test_29_days_none(self):
        self.write(f"- [ ] {self.ts(29)} · fresh")
        self.assertEqual(discover_repo.stale_ideas("proj", NOW), [])

    def test_taken_and_dropped_none(self):
        self.write(f"- [x] {self.ts(60)} · done → spec", f"- [-] {self.ts(60)} · dropped")
        self.assertEqual(discover_repo.stale_ideas("proj", NOW), [])

    def test_aware_now_and_epoch_accepted(self):
        self.write(f"- [ ] {self.ts(40)} · old")
        self.assertEqual(len(discover_repo.stale_ideas("proj", NOW.timestamp())), 1)
        self.assertEqual(len(discover_repo.stale_ideas("proj", NOW.astimezone(timezone.utc))), 1)

    def test_no_file(self):
        self.assertEqual(discover_repo.stale_ideas("nothere", NOW), [])


if __name__ == "__main__":
    unittest.main()
