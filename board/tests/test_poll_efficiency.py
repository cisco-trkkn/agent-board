"""Per-poll cost: tmux execs per state build (a shim tmux logs every call), ETag/304 on the polled endpoints.

Every test runs against a scratch tmux server on its own socket (-L poll-<pid> -f /dev/null), never the live one.
"""
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

BOARD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOARD))
import paneclass  # noqa: E402  (tmux_bin: TC_TMUX, else ~/.local/bin/tmux if executable, else tmux on PATH)

# Resolved before any test sets TC_TMUX to its logging shim, so the shim never execs itself.
REAL_TMUX = os.environ.get("TC_REAL_TMUX") or paneclass.tmux_bin()
SOCK = f"poll-{os.getpid()}"
TOKEN = "poll-test-token"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Scratch:
    """A scratch tmux server, a logging `tmux` shim, and the board module loaded against both."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="poll-test-"))
        self.log = self.tmp / "tmux-calls.log"
        self.log.touch()
        shim = self.tmp / "bin" / "tmux"
        shim.parent.mkdir()
        shim.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> {self.log}\nexec {REAL_TMUX} "$@"\n')
        shim.chmod(0o755)
        self.real = [REAL_TMUX, "-L", SOCK, "-f", "/dev/null"]
        self.port = free_port()
        (self.tmp / "state").mkdir()
        (self.tmp / "cwd").mkdir()
        self.env = {"TMUX_DASH_TOKEN": TOKEN, "TMUX_DASH_PORT": str(self.port), "TC_TMUX": str(shim),
                    "TMUX_DASH_TMUX_ARGS": f"-L {SOCK} -f /dev/null", "TC_STATE": str(self.tmp / "state")}
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        spec = importlib.util.spec_from_file_location("tmux_dash_server_poll", BOARD / "server.py")
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.server.RELOAD_EVERY = 10 ** 9   # never re-exec the test process

    def tmux(self, *args):
        return subprocess.run(self.real + list(args), capture_output=True, text=True, check=True).stdout

    def layout(self):
        """Project session `t`: 3 windows x 2 panes (6 panes), plus `t-bg` (tagged @tc_bg) with tests/shell windows."""
        cwd = str(self.tmp / "cwd")
        self.tmux("new-session", "-d", "-s", "t", "-n", "claude", "-x", "200", "-y", "50", "-c", cwd, "sleep 600")
        self.tmux("split-window", "-d", "-h", "-t", "=t:claude", "-c", cwd, "sleep 600")
        for n in ("shell", "w3"):
            self.tmux("new-window", "-d", "-t", "=t:", "-n", n, "-c", cwd, "sleep 600")
            self.tmux("split-window", "-d", "-h", "-t", f"=t:{n}", "-c", cwd, "sleep 600")
        self.tmux("new-session", "-d", "-s", "t-bg", "-n", "tests", "-x", "200", "-y", "50", "-c", cwd, "sleep 600")
        self.tmux("set-option", "-t", "=t-bg:", "@tc_bg", "1")
        self.tmux("new-window", "-d", "-t", "=t-bg:", "-n", "shell", "-c", cwd, "sleep 600")
        time.sleep(1.2)   # let the creation-second elapse, so the first build's captures can be reused

    def calls(self):
        return [l for l in self.log.read_text().split("\n") if l]   # not splitlines(): keep the split explicit; the chain marker is printable

    def during(self, fn):
        """(result, tmux calls made while fn ran)."""
        before = len(self.calls())
        out = fn()
        return out, self.calls()[before:]

    def close(self):
        try:
            subprocess.run(self.real + ["kill-server"], capture_output=True)
        finally:   # restore the environment even when kill-server can't run: a leaked TC_TMUX/TMUX_DASH_* breaks later test modules
            for k, v in self.saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            import shutil
            shutil.rmtree(self.tmp, ignore_errors=True)


def pane_ids(state):
    return [p["id"] for s in state["sessions"] for w in s["windows"] for p in w["panes"]]


class ExecCountTest(unittest.TestCase):
    def setUp(self):
        self.sc = Scratch()
        self.addCleanup(self.sc.close)
        self.sc.layout()

    def test_build_goes_through_tc_tmux(self):
        st, calls = self.sc.during(self.sc.server.build_state)
        self.assertEqual(len(pane_ids(st)), 6, st)
        self.assertTrue(calls, "server.py ignores TC_TMUX: the shim logged nothing")

    def test_first_build_chains_all_captures_into_one_exec(self):
        st, calls = self.sc.during(self.sc.server.build_state)
        caps = [c for c in calls if "capture-pane" in c]
        self.assertEqual(len(caps), 1, caps)
        for pid in pane_ids(st):
            self.assertIn(f"-t {pid} ", caps[0] + " ")

    def test_idle_rebuild_runs_at_most_two_execs(self):
        self.sc.server.build_state()
        st, calls = self.sc.during(self.sc.server.build_state)
        self.assertEqual(len(pane_ids(st)), 6)
        self.assertLessEqual(len(calls), 2, calls)
        self.assertEqual(len(calls), 1, calls)   # list-panes and the captures share one exec

    def previews(self, st):
        return {p["id"]: "".join(p["preview"]) for s in st["sessions"] for w in s["windows"] for p in w["panes"]}

    def test_output_shows_in_the_next_build_with_one_exec(self):
        st = self.sc.server.build_state()
        self.sc.server.build_state()
        target = pane_ids(st)[3]
        self.sc.tmux("send-keys", "-t", target, "hello-poll")   # `sleep` ignores it, but the tty echoes it
        time.sleep(0.3)
        st, calls = self.sc.during(self.sc.server.build_state)
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("hello-poll", self.previews(st)[target])

    def test_new_pane_is_captured_on_the_next_build(self):
        self.sc.server.build_state()
        self.sc.tmux("split-window", "-d", "-h", "-t", "=t:w3", "-c", str(self.sc.tmp / "cwd"), "echo new-pane-here; sleep 600")
        time.sleep(0.3)
        st, calls = self.sc.during(self.sc.server.build_state)
        self.assertEqual(len(pane_ids(st)), 7)
        self.assertLessEqual(len(calls), 2, calls)
        self.assertEqual([v for v in self.previews(st).values() if "new-pane-here" in v], ["new-pane-here"])

    def test_vanished_pane_keeps_the_panes_after_it(self):
        st = self.sc.server.build_state()
        ids = pane_ids(st)
        self.sc.tmux("send-keys", "-t", ids[-1], "still-here")
        self.sc.tmux("kill-pane", "-t", ids[1])
        time.sleep(0.3)
        st = self.sc.server.build_state()
        self.assertEqual(len(pane_ids(st)), 5)
        self.assertNotIn(ids[1], pane_ids(st))
        self.assertIn("still-here", self.previews(st)[ids[-1]])


class PollEndpointsTest(unittest.TestCase):
    """ETag/304 on the polled endpoints, served by the real Handler on a free port."""

    def setUp(self):
        self.sc = Scratch()
        self.addCleanup(self.sc.close)
        self.sc.layout()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.sc.port), self.sc.server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.state = self.sc.tmp / "state"

    def get(self, sub, etag=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.sc.port}/{TOKEN}/{sub}")
        if etag:
            req.add_header("If-None-Match", etag)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers.get("ETag"), r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers.get("ETag"), e.read()

    def test_unchanged_runs_answer_304(self):
        (self.state / "runs-p.jsonl").write_text(json.dumps({"id": "a", "ts": 10, "exit": 0, "cmd": "make"}) + "\n")
        code, etag, body = self.get("api/runs?session=p")
        self.assertEqual(code, 200)
        self.assertTrue(etag, "no ETag on /api/runs")
        self.assertEqual(json.loads(body)["runs"][0]["id"], "a")
        code, etag2, body = self.get("api/runs?session=p", etag)
        self.assertEqual((code, etag2, body), (304, etag, b""))
        with (self.state / "runs-p.jsonl").open("a") as f:
            f.write(json.dumps({"id": "b", "ts": 20, "exit": None, "cmd": "pytest"}) + "\n")
        code, etag3, body = self.get("api/runs?session=p", etag)
        self.assertEqual(code, 200)
        self.assertNotEqual(etag3, etag)
        self.assertEqual([r["id"] for r in json.loads(body)["runs"]], ["b", "a"])

    def test_unchanged_state_artifacts_ideas_usage_answer_304(self):
        # usage needs a real session (`t`); it 404s for unknown ones
        for sub in ("api/state", "api/artifacts?session=p", "api/ideas?session=p", "api/usage?session=t"):
            code, etag, _ = self.get(sub)
            self.assertEqual(code, 200, sub)
            self.assertTrue(etag, f"no ETag on /{sub}")
            self.assertEqual(self.get(sub, etag)[0], 304, sub)

    def test_running_run_gets_its_window_index_without_a_tmux_exec(self):
        (self.state / "runs-p.jsonl").write_text(
            json.dumps({"id": "a", "ts": 10, "exit": None, "cmd": "make", "session": "t-bg", "win": "shell"}) + "\n")
        self.get("api/state")   # the poll always asks for the state first
        (code, _, body), calls = self.sc.during(lambda: self.get("api/runs?session=p"))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["runs"][0]["window_index"], 1)   # base-index 0: tests=0, shell=1
        self.assertEqual([c for c in calls if "list-windows" in c], [], calls)


if __name__ == "__main__":
    unittest.main()
