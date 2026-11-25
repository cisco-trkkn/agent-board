"""One real run of the night watch's awake fix: server.WATCH.run(["awake", "on", "--queue"]) through the real
run_script and bin/tmux-ctl, against a scratch tmux server (-f /dev/null) and a temp TC_STATE. No stubs, no --lid
(so pmset and sudo are never touched)."""
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BOARD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOARD))
import paneclass  # noqa: E402

REAL_TMUX = os.environ.get("TC_REAL_TMUX") or paneclass.tmux_bin()
TMUX_CTL = BOARD.parent / "bin" / "tmux-ctl"


def _digest(p):
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None   # absent


def _real_files():
    tmpdir = (os.environ.get("TMPDIR") or "/tmp").rstrip("/")
    return [f"{tmpdir}/tmux-ctl-{os.getuid()}/awake.json",
            os.path.expanduser("~/.local/state/agent-board/awake.json")]


@unittest.skipUnless(shutil.which("tmux") or os.path.exists(REAL_TMUX), "tmux not on PATH")
@unittest.skipUnless(shutil.which("caffeinate"), "caffeinate not on PATH")
class WatchAwakeRealTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nwa-", dir="/tmp"))   # short: a long socket path fails
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "state"
        self.state.mkdir()
        sock = f"nwawake{os.getpid()}"
        (self.tmp / "tmx").mkdir()
        self.env = {"TMUX": "", "TMUX_TMPDIR": str(self.tmp / "tmx"), "TC_STATE": str(self.state),
                    "AGENT_BOARD_TMUX_SOCKET": sock, "TMUX_DASH_TMUX_ARGS": f"-L {sock} -f /dev/null",
                    "TMUX_DASH_TOKEN": "x", "TC_NOTIFY": "0"}
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.addCleanup(self._restore_env)
        self.before = {p: _digest(p) for p in _real_files()}
        self.real = [REAL_TMUX, "-L", sock, "-f", "/dev/null"]
        r = subprocess.run(self.real + ["new-session", "-d", "-s", "keep", "sleep 600"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.addCleanup(self._cleanup_hold)   # runs first (LIFO after env restore is registered earlier)
        spec = importlib.util.spec_from_file_location("tmux_dash_server_awake_real", BOARD / "server.py")
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.server.RELOAD_EVERY = 10 ** 9
        import overview
        self.overview = overview

    def _restore_env(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _cleanup_hold(self):
        cp = None
        try:
            cp = json.loads((self.state / "awake.json").read_text()).get("caffeinatePid")
        except (OSError, ValueError):
            pass
        subprocess.run([str(TMUX_CTL), "awake", "off"], env=dict(os.environ), capture_output=True, text=True, timeout=30)
        subprocess.run(self.real + ["kill-server"], capture_output=True, text=True)
        if cp:   # by PID only, never a pattern kill
            for _ in range(20):
                try:
                    os.kill(int(cp), 0)
                except OSError:
                    break
                time.sleep(0.1)
            else:
                os.kill(int(cp), signal.SIGTERM)
                self.fail(f"caffeinate {cp} survived `awake off`")
        self.assertEqual({p: _digest(p) for p in _real_files()}, self.before, "a real awake.json changed")

    def test_real_awake_on_queue(self):
        out = self.server.WATCH.run(["awake", "on", "--queue"])   # the real run_script and bin/tmux-ctl; no --lid
        self.assertIn("awake", out)
        rec = json.loads((self.state / "awake.json").read_text())
        self.assertIs(rec.get("queue"), True)
        self.assertTrue(self.overview.awake_live(self.state))


if __name__ == "__main__":
    unittest.main()
