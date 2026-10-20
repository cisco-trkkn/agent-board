"""Stale-server guard: /api/version, self re-exec on module mtime change, and the 404 banner."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

BOARD = Path(__file__).resolve().parent.parent
TOKEN = "reloadtesttoken"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ReloadTest(unittest.TestCase):
    def setUp(self):
        # Run a COPY of the board so touching activity.py never disturbs the checkout, with scratch state.
        self.tmp = Path(tempfile.mkdtemp(prefix="reload-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = self.tmp / "app"
        shutil.copytree(BOARD, self.app, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        (self.tmp / "tools").mkdir()   # tc_env.py parses ../tools/lib/tc-env.zsh, so the copy keeps the repo layout
        shutil.copytree(BOARD.parent / "tools" / "lib", self.tmp / "tools" / "lib")
        self.port = free_port()
        env = {**os.environ, "TMUX_DASH_TOKEN": TOKEN, "TMUX_DASH_PORT": str(self.port),
               "TMUX_DASH_TTYD_PORT": str(free_port()), "TC_STATE": str(self.tmp / "state"),
               "TC_IDEAS_DIR": str(self.tmp / "ideas"), "TMUX_DASH_TMUX_ARGS": f"-L reload-{os.getpid()} -f /dev/null"}
        self.log = open(self.tmp / "server.log", "wb")
        self.proc = subprocess.Popen([sys.executable, str(self.app / "server.py")], env=env, stdout=self.log, stderr=self.log)
        self.addCleanup(self._stop)
        self._wait_up()

    def _stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.log.close()

    def get(self, sub):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/{TOKEN}/{sub}")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)

    def _wait_up(self):
        end = time.time() + 10
        while time.time() < end:
            try:
                return self.get("api/version")
            except Exception:
                time.sleep(0.1)
        self.fail("server did not come up: " + (self.tmp / "server.log").read_text())

    def test_version_reports_start_time(self):
        v = self.get("api/version")
        self.assertIn("started", v)
        self.assertEqual(v["pid"], self.proc.pid)

    def test_touching_a_module_restarts_the_server_within_10s(self):
        first = self.get("api/version")["started"]
        time.sleep(0.05)
        os.utime(self.app / "activity.py", None)
        end = time.time() + 10
        second = first
        while time.time() < end and second == first:
            time.sleep(0.5)
            try:
                second = self.get("api/version")["started"]   # any request is the trigger
            except OSError:
                pass   # the port is briefly closed while the process re-execs
        self.assertGreater(second, first, "server kept running old code after a module changed\n" + (self.tmp / "server.log").read_text())
        self.assertEqual(self.get("api/version")["pid"], self.proc.pid, "re-exec must keep the same pid")


    def test_broken_module_keeps_the_old_server_running(self):
        first = self.get("api/version")["started"]
        with open(self.app / "activity.py", "a") as f:
            f.write("\nthis is not python (\n")
        for _ in range(14):   # well past the 5 s check interval
            time.sleep(0.5)
            v = self.get("api/version")
        self.assertEqual(v["started"], first, "server re-executed into code that does not load")
        self.assertIsNone(self.proc.poll())
        self.assertIn("does not load", (self.tmp / "server.log").read_text())


@unittest.skipUnless(shutil.which("node"), "node needed to run the page's pollActivity")
class StaleBannerTest(unittest.TestCase):
    def test_404_from_runs_shows_banner(self):
        html = (BOARD / "index.html").read_text()
        m = re.search(r"^async function pollActivity\(\) \{.*?^\}\n", html, re.S | re.M)
        self.assertIsNotNone(m, "pollActivity not found in index.html")
        pj = re.search(r"^async function pollJSON\(path\) \{.*?^\}\n", html, re.S | re.M)
        self.assertIsNotNone(pj, "pollJSON not found in index.html")
        js = """
const els = {};
const $ = (id) => els[id] || (els[id] = {textContent: "", hidden: true, classList: {toggle() {}}});
const session = () => ({name: "s"});
const ACT = {open: false, seeded: false, seenFails: new Set()};
const API = "", POLL = new Map();
const fetch = async () => ({ok: false, status: 404, headers: {get: () => null}});   // an old server: no /api/runs
const renderRuns = () => {}, renderCmds = async () => {};
%s
%s
pollActivity().then(() => {
  const b = els["#act-stale"];
  if (!b || b.hidden || !/restart/i.test(b.textContent)) { console.log("NO BANNER", JSON.stringify(b)); process.exit(1); }
  console.log("banner:", b.textContent);
});
""" % (pj.group(0), m.group(0))
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
