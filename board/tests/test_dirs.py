import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import dirs  # noqa: E402


class ListDirsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        for d in ["alpha", "beta", ".hidden", "repo/.git"]:
            (self.root / d).mkdir(parents=True)
        (self.root / "file.txt").write_text("x")
        (self.root / "link-dir").symlink_to(self.root / "alpha")
        (self.root / "link-file").symlink_to(self.root / "file.txt")

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, r):
        return [d["name"] for d in r["dirs"]]

    def test_only_dirs_sorted_with_flags(self):
        r = dirs.list_dirs(str(self.root))
        self.assertEqual(self.names(r), [".hidden", "alpha", "beta", "link-dir", "repo"])
        by = {d["name"]: d for d in r["dirs"]}
        self.assertTrue(by[".hidden"]["hidden"])
        self.assertFalse(by["alpha"]["hidden"])
        self.assertTrue(by["repo"]["git"])
        self.assertFalse(by["alpha"]["git"])
        self.assertEqual(r["path"], str(self.root))
        self.assertEqual(r["parent"], str(self.root.parent))
        self.assertFalse(r["truncated"])

    def test_hidden_filter_and_prefix(self):
        self.assertNotIn(".hidden", self.names(dirs.list_dirs(str(self.root), hidden=False)))
        self.assertEqual(self.names(dirs.list_dirs(str(self.root), prefix=".h")), [".hidden"])
        self.assertEqual(self.names(dirs.list_dirs(str(self.root), prefix="A")), [])

    def test_cap(self):
        many = self.root / "many"
        for i in range(dirs.CAP + 5):
            (many / f"d{i:04d}").mkdir(parents=True)
        r = dirs.list_dirs(str(many))
        self.assertEqual(len(r["dirs"]), dirs.CAP)
        self.assertTrue(r["truncated"])

    def test_tilde_and_root(self):
        self.assertEqual(dirs.list_dirs("~")["path"], os.path.realpath(os.path.expanduser("~")))
        self.assertEqual(dirs.list_dirs("")["path"], os.path.realpath(os.path.expanduser("~")))
        self.assertIsNone(dirs.list_dirs("/")["parent"])

    def test_errors(self):
        with self.assertRaisesRegex(NotADirectoryError, "not a folder"):
            dirs.list_dirs(str(self.root / "nope"))
        with self.assertRaisesRegex(NotADirectoryError, "not a folder"):
            dirs.list_dirs(str(self.root / "file.txt"))

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    def test_permission_error(self):
        locked = self.root / "locked"
        locked.mkdir()
        locked.chmod(0)
        try:
            with self.assertRaises(PermissionError):
                dirs.list_dirs(str(locked))
        finally:
            locked.chmod(0o755)


class RecentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_STATE"] = self.tmp.name
        self.base = Path(os.path.realpath(self.tmp.name))
        self.p = []
        for i in range(12):
            d = self.base / f"p{i}"
            d.mkdir()
            self.p.append(str(d))

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("TC_STATE", None)

    def stored(self):
        return json.loads((Path(self.tmp.name) / "recent-projects.json").read_text())

    def test_move_to_front_dedupe_cap(self):
        for p in self.p:
            dirs.record_recent(p)
        dirs.record_recent(self.p[5])
        s = self.stored()
        self.assertEqual(len(s), dirs.RECENT_MAX)
        self.assertEqual(s[0], self.p[5])
        self.assertEqual(s.count(self.p[5]), 1)
        self.assertEqual(s[1], self.p[11])

    def test_atomic_no_temp_left(self):
        dirs.record_recent(self.p[0])
        self.assertEqual(sorted(x.name for x in Path(self.tmp.name).iterdir() if x.name.startswith(".recent-")), [])

    def test_recent_merges_open_first_and_drops_missing(self):
        dirs.record_recent(self.p[0])
        dirs.record_recent(self.p[1])
        os.rmdir(self.p[0])
        self.assertEqual(dirs.recent([self.p[2], self.p[1]]), [self.p[2], self.p[1]])

    def test_corrupt_file_is_empty(self):
        (Path(self.tmp.name) / "recent-projects.json").write_text("{not json")
        self.assertEqual(dirs.recent([]), [])
        dirs.record_recent(self.p[0])
        self.assertEqual(self.stored(), [self.p[0]])

    def test_unreadable_state_file_is_empty(self):
        (Path(self.tmp.name) / "recent-projects.json").mkdir()  # reading a directory raises OSError
        self.assertEqual(dirs.recent([]), [])

    def test_failed_write_cleans_up_and_keeps_old_file(self):
        dirs.record_recent(self.p[0])
        with mock.patch.object(dirs.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                dirs.record_recent(self.p[1])
        self.assertEqual(self.stored(), [self.p[0]])
        self.assertEqual(sorted(x.name for x in Path(self.tmp.name).iterdir() if x.name.startswith(".recent-")), [])


import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from unittest import mock  # noqa: E402

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
import server  # noqa: E402


class DirsRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["TC_STATE"] = self.tmp.name
        self.root = Path(os.path.realpath(self.tmp.name)) / "tree"
        (self.root / "a").mkdir(parents=True)
        (self.root / ".h").mkdir()
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = self.httpd.server_address[1]
        self.hosts = mock.patch.object(server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"})
        self.hosts.start()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{port}"
        self.base = f"{self.origin}/{server.TOKEN}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)
        self.hosts.stop()
        self.tmp.cleanup()
        os.environ.pop("TC_STATE", None)

    def get(self, url):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode()
            finally:
                e.close()

    def test_listing(self):
        code, body = self.get(f"{self.base}/api/dirs?path={self.root}&hidden=0")
        self.assertEqual(code, 200)
        j = json.loads(body)
        self.assertEqual(set(j), {"path", "parent", "dirs", "truncated"})
        self.assertEqual([d["name"] for d in j["dirs"]], ["a"])

    def test_errors(self):
        code, body = self.get(f"{self.base}/api/dirs?path={self.root}/nope")
        self.assertEqual(code, 400)
        self.assertIn("not a folder", json.loads(body)["error"])
        with mock.patch.object(server.dirs, "list_dirs", side_effect=PermissionError):
            code, body = self.get(f"{self.base}/api/dirs?path=/x")
        self.assertEqual(code, 403)
        self.assertEqual(json.loads(body)["error"], "can't read /x: permission denied")

    def test_needs_token(self):
        self.assertEqual(self.get(f"{self.origin}/api/dirs?path=/")[0], 404)

    def test_null_byte_path_is_400(self):
        code, body = self.get(f"{self.base}/api/dirs?path=%00")
        self.assertEqual(code, 400)
        self.assertIn("not a folder", json.loads(body)["error"])

    def test_recent_open_first(self):
        dirs.record_recent(str(self.root / "a"))
        with mock.patch.object(server, "state", return_value={"sessions": [{"name": "t", "path": str(self.root)}]}):
            code, body = self.get(f"{self.base}/api/dirs/recent")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["recent"], [str(self.root), str(self.root / "a")])
        # a trailing slash on the open session's path must still dedupe against the stored realpath
        with mock.patch.object(server, "state", return_value={"sessions": [{"name": "t", "path": str(self.root) + "/"}]}):
            code, body = self.get(f"{self.base}/api/dirs/recent")
        self.assertEqual(json.loads(body)["recent"], [str(self.root), str(self.root / "a")])

    def test_recent_dedupes_open_symlink_against_realpath(self):
        dirs.record_recent(str(self.root / "a"))
        os.symlink(self.root / "a", self.root / "alink")
        with mock.patch.object(server, "state", return_value={"sessions": [{"name": "t", "path": str(self.root / "alink")}]}):
            code, body = self.get(f"{self.base}/api/dirs/recent")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["recent"], [str(self.root / "a")])

    def test_dev_records_only_on_success(self):
        with mock.patch.object(server, "run_script", return_value="ok"), mock.patch.object(server.dirs, "record_recent") as rec:
            server._act({"action": "dev", "path": str(self.root)})
        rec.assert_called_once_with(str(self.root))
        with mock.patch.object(server, "run_script", side_effect=RuntimeError("boom")), mock.patch.object(server.dirs, "record_recent") as rec:
            with self.assertRaises(RuntimeError):
                server._act({"action": "dev", "path": str(self.root)})
        rec.assert_not_called()

    def test_dev_ok_even_if_recording_fails(self):
        with mock.patch.object(server, "run_script", return_value="ok"), mock.patch.object(server.dirs, "record_recent", side_effect=OSError("disk full")):
            self.assertEqual(server._act({"action": "dev", "path": str(self.root)}), "ok")


if __name__ == "__main__":
    unittest.main()
