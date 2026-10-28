import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import gitlab_sync as g  # noqa: E402
import ideas  # noqa: E402

REPO = "grp/repo"
BASE = "projects/grp%2Frepo/issues"
TS = "2026-10-28 10:00"


def marker(project, ts, text):
    return f"<!-- agent-board:{project}:{ts}:{hashlib.sha256(text.encode()).hexdigest()[:8]} -->"


class Env(unittest.TestCase):
    """Every test: temp ideas dir, temp config, temp fake-glab dir, fake `glab` first on PATH.
    No test can reach the real glab or the real config."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.dir, self.fake, self.bin = t / "ideas", t / "fake", t / "bin"
        for d in (self.dir, self.fake, self.bin):
            d.mkdir()
        self.conf = t / "gitlab.json"
        glab = self.bin / "glab"
        glab.write_text(f"#!/bin/sh\nexec python3 -I {HERE}/fake_glab.py \"$@\"\n")
        glab.chmod(0o755)
        self.saved = {k: os.environ.get(k) for k in ("TC_IDEAS_DIR", "TC_GITLAB_CONF", "FAKE_GLAB_DIR", "PATH")}
        os.environ.update(TC_IDEAS_DIR=str(self.dir), TC_GITLAB_CONF=str(self.conf), FAKE_GLAB_DIR=str(self.fake),
                          PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        self.map({"p": {"repo": REPO, "since": "2026-10-28"}})

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def map(self, obj):
        self.conf.write_text(json.dumps(obj))

    def ideas(self, *lines, project="p"):
        (self.dir / f"{project}.md").write_text(f"# Ideas: {project}\n\n" + "".join(l + "\n" for l in lines))

    def text(self, project="p"):
        return (self.dir / f"{project}.md").read_text()

    def sidecar_put(self, obj, project="p"):
        (self.dir / f"{project}.gitlab.json").write_text(json.dumps(obj))

    def sidecar(self, project="p"):
        f = self.dir / f"{project}.gitlab.json"
        return json.loads(f.read_text()) if f.exists() else None

    def status(self, project="p"):
        f = self.dir / f"{project}.gitlab-status.json"
        return json.loads(f.read_text()) if f.exists() else None

    def rules(self, *rs):
        (self.fake / "rules.json").write_text(json.dumps(list(rs)))

    def log(self):
        f = self.fake / "log.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def calls(self, method=None):
        return [(c["method"], c["path"], c["fields"]) for c in self.log() if method in (None, c["method"])]


class ConfigTest(Env):
    def test_conf_path_env_wins(self):
        self.assertEqual(g.conf_path(), self.conf)

    def test_conf_path_off_when_ideas_dir_set_and_conf_unset(self):
        # mutation: drop the TC_IDEAS_DIR check -> returns ~/.config/agent-board/gitlab.json
        del os.environ["TC_GITLAB_CONF"]
        self.assertIsNone(g.conf_path())

    def test_conf_path_default(self):
        del os.environ["TC_GITLAB_CONF"]
        del os.environ["TC_IDEAS_DIR"]
        self.assertEqual(g.conf_path(), Path.home() / ".config" / "agent-board" / "gitlab.json")

    def test_mapping_none_when_off_absent_or_unmapped(self):
        self.assertIsNone(g.mapping("other"))
        self.conf.unlink()
        self.assertIsNone(g.mapping("p"))
        self.assertFalse(g.mapped("p"))
        del os.environ["TC_GITLAB_CONF"]
        self.assertIsNone(g.mapping("p"))

    def test_mapping_returns_repo_and_since(self):
        m = g.mapping("p")
        self.assertEqual((m["repo"], m["since"]), (REPO, "2026-10-28"))
        self.assertTrue(g.mapped("p"))
        self.assertFalse(g.mapped("other"))

    def test_config_errors(self):
        for bad in ('{not json', '[]', '{"p": {"since": "2026-10-28"}}', '{"p": {"repo": "a/b"}}',
                    '{"p": {"repo": "a/b", "since": "28/10/2026"}}', '{"p": {"repo": "a/b", "since": 20261028}}'):
            self.conf.write_text(bad)
            with self.subTest(bad=bad):
                with self.assertRaises(g.ConfigError):
                    g.mapping("p")
        self.conf.write_text("{not json")
        self.assertTrue(g.mapped("p"))   # so sync can record the error


class ClientTest(Env):
    def test_parse_real_captures(self):
        fx = HERE / "fixtures" / "glab"
        code, hdr, body = g._parse((fx / "list-empty-200.txt").read_text())
        self.assertEqual((code, body), (200, []))
        self.assertEqual(hdr["ratelimit-remaining"], "1999")
        code, hdr, body = g._parse((fx / "get-404.txt").read_text())
        self.assertEqual(code, 404)

    def test_ok_body(self):
        self.rules({"method": "GET", "path_re": "issues", "status": 200, "body": [{"iid": 1}]})
        self.assertEqual(g.api("GET", BASE, [("state", "all")]), [{"iid": 1}])
        self.assertEqual(self.calls(), [("GET", BASE, {"state": "all"})])

    def test_http_error(self):
        self.rules({"method": "GET", "path_re": "issues/9", "status": 404, "body": {"message": "404 Not found"}})
        with self.assertRaisesRegex(g.GlabError, "HTTP 404: 404 Not found"):
            g.api("GET", f"{BASE}/9")

    def test_rate_limited_by_status_and_by_header(self):
        self.rules({"method": "GET", "path_re": "a$", "status": 429, "body": {"message": "slow"}},
                   {"method": "GET", "path_re": "b$", "status": 200, "body": [], "remaining": 0})
        for p in ("a", "b"):
            with self.subTest(p=p), self.assertRaises(g.RateLimited):
                g.api("GET", p)

    def test_missing_binary(self):
        os.environ["PATH"] = str(self.dir)   # no glab here
        with self.assertRaises(g.GlabError):
            g.api("GET", BASE)

    def test_rate_limited_is_a_glab_error(self):
        self.assertTrue(issubclass(g.RateLimited, g.GlabError))


class SyncTest(Env):
    def create_rules(self, iid=5):
        self.rules({"method": "POST", "path_re": "issues$", "status": 201, "body": {"iid": iid}})

    def test_unmapped_project_makes_no_call(self):
        # mutation: skip the mapping() None check -> a GET is logged
        self.ideas(f"- [ ] {TS} · a")
        self.map({"other": {"repo": REPO, "since": "2026-10-28"}})
        g.sync("p")
        self.assertEqual(self.log(), [])
        self.assertIsNone(self.status())

    def test_idea_before_since_is_not_created(self):
        # mutation: drop the since comparison -> POST logged
        self.ideas("- [ ] 2026-10-27 23:59 · old")
        g.sync("p")
        self.assertEqual(self.calls("POST"), [])
        self.assertNotIn("gl#", self.text())

    def test_create_searches_then_posts_then_tokens_then_sidecar(self):
        self.ideas(f"- [ ] {TS} · retries")
        self.create_rules(5)
        r = g.sync("p")
        mk = marker("p", TS, "retries")
        self.assertEqual(self.calls(), [
            ("GET", BASE, {"search": mk, "in": "description", "state": "all", "per_page": "20"}),
            ("POST", BASE, {"title": "retries", "labels": "idea", "description": mk})])
        self.assertIn(f"{TS} · retries · gl#5", self.text())
        self.assertEqual(self.sidecar(), {"5": {"ts": TS, "title": "retries", "state": "open"}})
        st = self.status()
        self.assertEqual((st["ok"], st["error"], st["pending"]), (True, "", 0))
        self.assertTrue(st["at"])
        self.assertTrue(r["ok"])

    def test_marker_hit_is_adopted_without_post(self):
        # mutation: skip the search -> POST logged and the iid differs
        self.ideas(f"- [ ] {TS} · retries")
        mk = marker("p", TS, "retries")
        self.rules({"method": "GET", "path_re": "issues$", "status": 200,
                    "body": [{"iid": 9, "title": "retries", "state": "opened", "description": f"x\n{mk}"}]},
                   {"method": "POST", "path_re": "issues$", "status": 201, "body": {"iid": 77}})
        g.sync("p")
        self.assertEqual(self.calls("POST"), [])
        self.assertIn("retries · gl#9", self.text())
        self.assertEqual(self.sidecar()["9"]["state"], "open")

    def test_hit_without_exact_marker_is_not_adopted(self):
        self.ideas(f"- [ ] {TS} · retries")
        other = marker("p", TS, "retriesX")
        self.rules({"method": "GET", "path_re": "issues$", "status": 200,
                    "body": [{"iid": 9, "title": "t", "state": "opened", "description": other}]},
                   {"method": "POST", "path_re": "issues$", "status": 201, "body": {"iid": 77}})
        g.sync("p")
        self.assertEqual(len(self.calls("POST")), 1)
        self.assertIn("gl#77", self.text())

    def test_failed_post_leaves_no_token_or_entry_and_next_idea_continues(self):
        # mutation: write the sidecar before the call -> an entry for the failed idea is present
        self.ideas(f"- [ ] {TS} · first", f"- [ ] {TS} · second")
        self.rules({"method": "POST", "path_re": "issues$", "status": 500, "body": {"message": "boom"}, "once": True},
                   {"method": "POST", "path_re": "issues$", "status": 201, "body": {"iid": 3}})
        r = g.sync("p")
        t = self.text()
        self.assertNotIn("first · gl#", t)
        self.assertIn("second · gl#3", t)
        self.assertEqual(list(self.sidecar()), ["3"])
        st = self.status()
        self.assertFalse(st["ok"])
        self.assertIn("500", st["error"])
        self.assertEqual(st["pending"], 1)
        self.assertFalse(r["ok"])

    def test_second_pass_makes_no_calls(self):
        # mutation: compare the title against a stale value -> a PUT is logged
        self.ideas(f"- [ ] {TS} · retries")
        self.create_rules(5)
        g.sync("p")
        n = len(self.log())
        g.sync("p")
        self.assertEqual(len(self.log()), n)

    def test_stale_set_issue_skips_and_continues(self):
        self.ideas(f"- [ ] {TS} · first", f"- [ ] {TS} · second")
        self.create_rules(5)
        with mock.patch.object(ideas, "set_issue", side_effect=ideas.Stale("moved")) as m:
            g.sync("p")
        self.assertEqual(m.call_count, 2)
        self.assertIsNone(self.sidecar())
        self.assertEqual(self.status()["error"], "")

    def test_retitle(self):
        self.ideas(f"- [ ] {TS} · new words · gl#5")
        self.sidecar_put({"5": {"ts": TS, "title": "old words", "state": "open"}})
        g.sync("p")
        self.assertEqual(self.calls(), [("PUT", f"{BASE}/5", {"title": "new words"})])
        self.assertEqual(self.sidecar()["5"]["title"], "new words")

    def test_taken_notes_then_closes(self):
        self.ideas(f"- [x] {TS} · retries · gl#5 → docs/s.md")
        self.sidecar_put({"5": {"ts": TS, "title": "retries → docs/s.md", "state": "open"}})
        g.sync("p")
        self.assertEqual(self.calls(), [("POST", f"{BASE}/5/notes", {"body": "Taken up → docs/s.md"}),
                                        ("PUT", f"{BASE}/5", {"state_event": "close"})])
        self.assertEqual(self.sidecar()["5"]["state"], "closed-done")
        g.sync("p")
        self.assertEqual(len(self.log()), 2)

    def test_dropped_closes_as_not_planned(self):
        self.ideas(f"- [-] {TS} · retries · gl#5")
        self.sidecar_put({"5": {"ts": TS, "title": "retries", "state": "open"}})
        g.sync("p")
        self.assertEqual(self.calls(), [("PUT", f"{BASE}/5", {"state_event": "close", "add_labels": "not-planned"})])
        self.assertEqual(self.sidecar()["5"]["state"], "closed-dropped")

    def test_moved_notes_then_closes(self):
        self.ideas(f"- [-] {TS} · retries · gl#5 → moved to other")
        self.sidecar_put({"5": {"ts": TS, "title": "retries", "state": "open"}})
        g.sync("p")
        self.assertEqual(self.calls(), [("POST", f"{BASE}/5/notes", {"body": "Moved to other"}),
                                        ("PUT", f"{BASE}/5", {"state_event": "close"})])
        self.assertEqual(self.sidecar()["5"]["state"], "closed-moved")

    def test_restored_reopens(self):
        self.ideas(f"- [ ] {TS} · retries · gl#5")
        self.sidecar_put({"5": {"ts": TS, "title": "retries", "state": "closed-dropped"}})
        g.sync("p")
        self.assertEqual(self.calls(), [("PUT", f"{BASE}/5", {"state_event": "reopen", "remove_labels": "not-planned"})])
        self.assertEqual(self.sidecar()["5"]["state"], "open")

    def test_token_without_sidecar_entry_assumes_open_and_current_title(self):
        self.ideas(f"- [ ] {TS} · retries · gl#5")
        g.sync("p")
        self.assertEqual(self.log(), [])

    def test_token_without_sidecar_entry_still_closes_a_taken_idea(self):
        self.ideas(f"- [x] {TS} · retries · gl#5 → docs/s.md")
        g.sync("p")
        self.assertEqual(len(self.calls("PUT")), 1)

    def test_sync_lock_held_returns_at_once(self):
        self.ideas(f"- [ ] {TS} · retries")
        with open(self.dir / "p.md.sync.lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            g.sync("p")
        self.assertEqual(self.log(), [])
        self.assertIsNone(self.status())

    def test_dry_run_only_gets_and_writes_nothing(self):
        # mutation: let dry run POST -> a POST is logged
        self.ideas(f"- [ ] {TS} · fresh",
                   f"- [ ] {TS} · renamed · gl#1",
                   f"- [x] {TS} · done · gl#2 → docs/s.md",
                   f"- [-] {TS} · dropped · gl#3",
                   f"- [-] {TS} · moved · gl#4 → moved to q",
                   f"- [ ] {TS} · back · gl#6")
        self.sidecar_put({"1": {"ts": TS, "title": "old", "state": "open"},
                          "2": {"ts": TS, "title": "done", "state": "open"},
                          "3": {"ts": TS, "title": "dropped", "state": "open"},
                          "4": {"ts": TS, "title": "moved", "state": "open"},
                          "6": {"ts": TS, "title": "back", "state": "closed-dropped"}})
        before = {f.name: f.read_bytes() for f in self.dir.iterdir()}
        r = g.sync("p", dry_run=True)
        self.assertEqual({m for m, _, _ in self.calls()}, {"GET"})
        self.assertEqual({f.name: f.read_bytes() for f in self.dir.iterdir() if f.suffix != ".lock"},
                         {k: v for k, v in before.items() if not k.endswith(".lock")})
        self.assertFalse((self.dir / "p.gitlab-status.json").exists())
        self.assertEqual(r["actions"], ['create "fresh"', "retitle #1", "close-done #2", "close-dropped #3",
                                        "close-moved #4", "reopen #6"])

    def test_dry_run_adopt_line(self):
        self.ideas(f"- [ ] {TS} · retries")
        mk = marker("p", TS, "retries")
        self.rules({"method": "GET", "path_re": "issues$", "status": 200,
                    "body": [{"iid": 9, "title": "retries", "state": "opened", "description": mk}]})
        self.assertEqual(g.sync("p", dry_run=True)["actions"], ['adopt #9 "retries"'])

    def test_rate_limit_stops_the_pass(self):
        self.ideas(f"- [ ] {TS} · first", f"- [ ] {TS} · second")
        self.rules({"method": "GET", "path_re": "issues$", "status": 429, "body": {"message": "slow"}})
        r = g.sync("p")
        self.assertEqual(len(self.log()), 1)
        st = self.status()
        self.assertFalse(st["ok"])
        self.assertEqual(st["pending"], 2)
        self.assertFalse(r["ok"])

    def test_config_error_writes_status_and_raises(self):
        self.conf.write_text("{not json")
        with self.assertRaises(g.ConfigError):
            g.sync("p")
        self.assertFalse(self.status()["ok"])
        self.assertEqual(self.log(), [])

    def test_sidecar_is_written_atomically(self):
        self.ideas(f"- [ ] {TS} · retries")
        self.create_rules(5)
        with mock.patch("os.replace", wraps=os.replace) as rep:
            g.sync("p")
        dests = [Path(c.args[1]).name for c in rep.call_args_list]
        self.assertIn("p.gitlab.json", dests)
        self.assertEqual([f.name for f in self.dir.iterdir() if f.name.endswith(".tmp")], [])


class CliTest(Env):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(HERE.parent / "ideas.py"), "sync", *args],
                              capture_output=True, text=True, env=dict(os.environ), timeout=60)

    def test_unmapped_exits_0_under_isolated_mode(self):
        # python3 -I implies -P on 3.14: ideas.py must find gitlab_sync itself
        r = self.run_cli("--project", "unmapped")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.log(), [])

    def test_dry_run_prints_actions(self):
        self.ideas(f"- [ ] {TS} · fresh")
        r = self.run_cli("--project", "p", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('create "fresh"', r.stdout)

    def test_exit_1_when_a_push_failed(self):
        self.ideas(f"- [ ] {TS} · fresh")
        self.rules({"method": "POST", "path_re": "issues$", "status": 500, "body": {"message": "boom"}})
        self.assertEqual(self.run_cli("--project", "p").returncode, 1)

    def test_exit_2_on_config_error(self):
        self.conf.write_text("{not json")
        r = self.run_cli("--project", "p")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self.status()["ok"])


if __name__ == "__main__":
    unittest.main()
