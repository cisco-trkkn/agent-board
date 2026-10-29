import json
import os
import sys
import tempfile
import threading
import unittest
import importlib.util
from pathlib import Path
from unittest import mock

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
BOARD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOARD))
import gitlab_sync as g  # noqa: E402
import ideas  # noqa: E402

TS = "2026-10-28 10:00"


class KickBase(unittest.TestCase):
    """Popen is always patched: no test starts a real sync process."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.conf = self.dir / "gitlab.json"
        self.saved = {k: os.environ.get(k) for k in ("TC_IDEAS_DIR", "TC_GITLAB_CONF", "HOME")}
        os.environ.update(TC_IDEAS_DIR=str(self.dir), TC_GITLAB_CONF=str(self.conf))
        self.conf.write_text(json.dumps({"p": {"repo": "grp/repo", "since": "2026-10-28"},
                                         "q": {"repo": "grp/repo", "since": "2026-10-28"}}))
        patch = mock.patch.object(g.subprocess, "Popen")
        self.popen = patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def argvs(self):
        return [c.args[0] for c in self.popen.call_args_list]


class KickTest(KickBase):
    def test_add_on_mapped_project_starts_one_detached_sync(self):
        # mutation: drop the mapped() check in kick -> the unmapped test sees a call
        ideas.add("p", "x")
        [argv] = self.argvs()
        self.assertEqual(argv[:3], [sys.executable, "-I", str(BOARD / "ideas.py")])
        self.assertEqual(argv[3:], ["sync", "--project", "p"])
        kw = self.popen.call_args.kwargs
        self.assertTrue(kw["start_new_session"])
        for k in ("stdin", "stdout", "stderr"):
            self.assertIs(kw[k], g.subprocess.DEVNULL)

    def test_add_strips_a_typed_issue_token(self):
        # mutation: remove the strip in add() -> load()[0]["issue"] is 5 and sync would touch issue #5
        ideas.add("p", "foo · gl#5")
        [i] = ideas.load("p")
        self.assertEqual((i["text"], i["issue"]), ("foo", None))

    def test_unmapped_project_does_not_kick(self):
        ideas.add("other", "x")
        self.assertEqual(self.argvs(), [])

    def test_edit_and_status_kick(self):
        ideas.add("p", "x", now=1_700_000_000)
        key = ideas.load("p")[0]["key"]
        self.popen.reset_mock()
        ideas.edit("p", key, "y")
        key = ideas.load("p")[0]["key"]
        ideas.set_status("p", key, "dropped")
        self.assertEqual(len(self.argvs()), 2)

    def test_move_kicks_both_projects(self):
        ideas.add("p", "x", now=1_700_000_000)
        key = ideas.load("p")[0]["key"]
        self.popen.reset_mock()
        ideas.move("p", key, "q")
        self.assertEqual(sorted(a[-1] for a in self.argvs()), ["p", "q"])

    def test_set_issue_never_kicks(self):
        # mutation: add _kick to set_issue -> a call is seen
        ideas.add("p", "x", now=1_700_000_000)
        key = ideas.load("p")[0]["key"]
        self.popen.reset_mock()
        ideas.set_issue("p", key, 5)
        self.assertEqual(self.argvs(), [])

    def test_ideas_dir_seam_beats_a_real_looking_home_config(self):
        home = self.dir / "home"
        (home / ".config" / "agent-board").mkdir(parents=True)
        (home / ".config" / "agent-board" / "gitlab.json").write_text(
            json.dumps({"p": {"repo": "grp/repo", "since": "2026-10-28"}}))
        os.environ["HOME"] = str(home)
        del os.environ["TC_GITLAB_CONF"]
        ideas.add("p", "x")
        self.assertEqual(self.argvs(), [])

    def test_kick_swallows_every_error(self):
        self.popen.side_effect = OSError("no fork")
        ideas.add("p", "x")   # must not raise
        self.assertEqual(len(ideas.load("p")), 1)

    def test_kick_swallows_a_broken_config(self):
        self.conf.write_text("{not json")
        ideas.add("p", "x")
        self.assertEqual(len(ideas.load("p")), 1)


class BoardInfoTest(KickBase):
    def test_none_when_unmapped(self):
        self.assertIsNone(g.board_info("zz"))

    def test_no_status_file_yet(self):
        self.assertEqual(g.board_info("p"), {"repo": "grp/repo", "url": "https://gitlab.com/grp/repo", "ok": True, "error": ""})

    def test_status_file_values(self):
        (self.dir / "p.gitlab-status.json").write_text(json.dumps({"at": "x", "ok": False, "error": "boom", "pending": 1}))
        got = g.board_info("p")
        self.assertEqual((got["ok"], got["error"]), (False, "boom"))

    def test_config_error(self):
        self.conf.write_text("{not json")
        got = g.board_info("p")
        self.assertEqual((got["repo"], got["url"], got["ok"]), ("", "", False))
        self.assertTrue(got["error"])


class MappedProjectsTest(KickBase):
    def test_keys_that_are_valid_project_names(self):
        self.conf.write_text(json.dumps({"p": {}, "../x": {}, "a.b": {}}))
        self.assertEqual(g.mapped_projects(), ["p", "a.b"])

    def test_empty_on_config_error_or_absent(self):
        self.conf.write_text("{not json")
        self.assertEqual(g.mapped_projects(), [])
        self.conf.unlink()
        self.assertEqual(g.mapped_projects(), [])


class ServerThreadTest(unittest.TestCase):
    def test_importing_server_starts_no_gitlab_thread(self):
        # mutation: start the thread at import -> a thread named gitlab-sync is alive
        spec = importlib.util.spec_from_file_location("tmux_dash_server_kick", BOARD / "server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertFalse(any(t.name == "gitlab-sync" for t in threading.enumerate()))
        self.assertTrue(callable(mod.gitlab_loop))

    def test_loop_pass_kicks_each_mapped_project_and_never_syncs_in_process(self):
        # mutation: call sync() directly in gitlab_pass -> sync is called on a board-server thread
        spec = importlib.util.spec_from_file_location("tmux_dash_server_kick2", BOARD / "server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        kicked = []

        def fake_kick(p):
            kicked.append(p)
            if p == "a":
                raise RuntimeError("boom")

        with mock.patch.object(mod.gitlab_sync, "mapped_projects", return_value=["a", "b"]), \
             mock.patch.object(mod.gitlab_sync, "kick", side_effect=fake_kick), \
             mock.patch.object(mod.gitlab_sync, "sync") as sync, \
             mock.patch("sys.stderr") as err:
            mod.gitlab_pass()
        self.assertEqual(kicked, ["a", "b"])
        sync.assert_not_called()
        self.assertTrue(err.write.called)


class SysPathTest(KickBase):
    def test_writes_do_not_grow_sys_path(self):
        ideas.add("p", "one")
        n = len(sys.path)
        ideas.add("p", "two")
        ideas.add("p", "three")
        self.assertEqual(len(sys.path), n)


if __name__ == "__main__":
    unittest.main()
