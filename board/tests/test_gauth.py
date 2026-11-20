import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gauth  # noqa: E402

TMUX_BIN = os.path.expanduser("~/.local/bin/tmux") if os.access(os.path.expanduser("~/.local/bin/tmux"), os.X_OK) else shutil.which("tmux")
URL = "https://accounts.google.com/o/oauth2/auth?client_id=abc&scope=x"
TOKEN = "ya29.SECRET-TOKEN-VALUE"

FAKE = f"""#!/bin/sh
D="$(dirname "$0")"
printf '%s\\n' "$*" >> "$D/argv.log"
case "$*" in
  *print-access-token*)
    echo {TOKEN}
    if [ -f "$D/token-fail" ]; then echo "noise" >&2; echo "ERROR: (gcloud.auth.print-access-token) reauth needed" >&2; exit 1; fi
    exit 0 ;;
esac
echo "Go to the following link in your browser:"
echo
echo "    {URL}"
echo
printf 'Enter authorization code: '
read code
printf 'GOT[%s]\\n' "$code"
if [ -f "$D/login-fail" ]; then echo "ERROR: (gcloud.auth.login) bad code"; else echo "Credentials saved to file: [/x/y.json]"; fi
"""


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        g = self.bin / "gcloud"
        g.write_text(FAKE)
        g.chmod(g.stat().st_mode | stat.S_IXUSR)
        self.state = self.tmp / "state"
        old = dict(os.environ)
        os.environ["TC_STATE"] = str(self.state)
        os.environ["PATH"] = f"{self.bin}:{os.environ['PATH']}"
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))

    def argv(self):
        f = self.bin / "argv.log"
        return f.read_text().splitlines() if f.exists() else []

    def write_cfg(self, project="proj", **kw):
        cfg = {"adc": True, "impersonate": "", "account": ""}
        cfg.update(kw)
        d = self.state / "gauth"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{project}.json").write_text(json.dumps(cfg))


class ConfigTest(Base):
    def test_no_config_hint(self):
        with self.assertRaises(gauth.GauthError) as cm:
            gauth.load_config("proj")
        self.assertEqual(str(cm.exception), "no gauth config for proj; set it at the terminal: tmux-ctl gauth config proj …")

    def test_bad_project_name(self):
        for bad in ("", "../x", "a b", "-x", "a/b"):
            with self.assertRaises(gauth.GauthError, msg=bad):
                gauth.load_config(bad)

    def test_write_config_is_0600_and_roundtrips(self):
        gauth.write_config("proj", adc=False, impersonate="sa@x.iam", account="me@x.com")
        p = self.state / "gauth" / "proj.json"
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(gauth.load_config("proj"), {"adc": False, "impersonate": "sa@x.iam", "account": "me@x.com"})

    def test_argv_adc(self):
        self.assertEqual(gauth.build_argv({"adc": True, "impersonate": "", "account": "me@x.com"}),
                         ["gcloud", "auth", "application-default", "login", "--no-launch-browser"])

    def test_argv_adc_impersonate(self):
        self.assertEqual(gauth.build_argv({"adc": True, "impersonate": "sa@x.iam", "account": ""}),
                         ["gcloud", "auth", "application-default", "login", "--no-launch-browser", "--impersonate-service-account=sa@x.iam"])

    def test_argv_user_login_with_account(self):
        self.assertEqual(gauth.build_argv({"adc": False, "impersonate": "", "account": "me@x.com"}),
                         ["gcloud", "auth", "login", "--no-launch-browser", "--account=me@x.com"])


class CtlConfigTest(Base):
    """tmux-ctl gauth config works outside tmux (the line-107 exemption) and writes the 0600 file."""

    def test_config_outside_tmux(self):
        ctl = Path(__file__).resolve().parents[2] / "bin" / "tmux-ctl"
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        r = subprocess.run([str(ctl), "gauth", "config", "proj", "--impersonate", "sa@x.iam"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        p = self.state / "gauth" / "proj.json"
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(gauth.load_config("proj")["impersonate"], "sa@x.iam")


class RealGcloudFlagsTest(unittest.TestCase):
    """One unpatched run of the deciding external command: the flags build_argv emits exist in the installed gcloud."""

    @unittest.skipUnless(shutil.which("gcloud"), "no gcloud")
    def test_no_launch_browser_documented(self):
        for argv in (["gcloud", "auth", "application-default", "login", "--help"], ["gcloud", "auth", "login", "--help"]):
            out = subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout
            self.assertIn("--no-launch-browser", out, argv)


@unittest.skipUnless(TMUX_BIN, "no tmux")
class FlowTest(Base):
    def setUp(self):
        super().setUp()
        self.sock = f"gauth-{os.getpid()}-{id(self) % 100000}"

        def tmux(*args, check=False):
            r = subprocess.run([TMUX_BIN, "-L", self.sock, "-f", "/dev/null", *args], capture_output=True, text=True)
            if check and r.returncode:
                raise RuntimeError(r.stderr)
            return r.stdout

        self.tmux = tmux
        self.addCleanup(lambda: tmux("kill-server"))
        # keep one session alive so the scratch server survives and never reads ~/.tmux.conf
        tmux("new-session", "-d", "-s", "keep", "-f", "/dev/null", "sleep 300")
        self.write_cfg()

    def windows(self):
        return self.tmux("list-windows", "-a", "-F", "#{session_name}:#{window_name}").split()

    def test_start_url_code_result_close(self):
        gauth.start("proj", tmux=self.tmux)
        self.assertIn("proj-bg:gauth-proj", self.windows())
        self.assertEqual(gauth.read_url("proj", tmux=self.tmux, timeout=10), URL)
        self.assertEqual(self.argv()[0], "auth application-default login --no-launch-browser")
        self.assertIsNone(gauth.result("proj", tmux=self.tmux))
        gauth.send_code("proj", "4/0Ab C;d $x 'q'", tmux=self.tmux)
        for _ in range(50):
            r = gauth.result("proj", tmux=self.tmux)
            if r:
                break
            time.sleep(0.1)
        self.assertEqual(r[0], "ok")
        self.assertIn("Credentials saved", r[1])
        out = self.tmux("capture-pane", "-p", "-J", "-t", "=proj-bg:=gauth-proj")
        self.assertIn("GOT[4/0Ab C;d $x 'q']", out)
        gauth.close("proj", tmux=self.tmux)
        self.assertNotIn("proj-bg:gauth-proj", self.windows())
        self.assertFalse((self.state / "gauth" / "proj.waiting").exists())

    def test_code_that_is_a_key_name_stays_literal(self):
        gauth.start("proj", tmux=self.tmux)
        gauth.read_url("proj", tmux=self.tmux, timeout=10)
        gauth.send_code("proj", "Enter", tmux=self.tmux)
        for _ in range(50):
            if gauth.result("proj", tmux=self.tmux):
                break
            time.sleep(0.1)
        self.assertIn("GOT[Enter]", self.tmux("capture-pane", "-p", "-J", "-t", "=proj-bg:=gauth-proj"))

    def test_error_result(self):
        (self.bin / "login-fail").write_text("")
        gauth.start("proj", tmux=self.tmux)
        gauth.read_url("proj", tmux=self.tmux, timeout=10)
        gauth.send_code("proj", "bad", tmux=self.tmux)
        for _ in range(50):
            r = gauth.result("proj", tmux=self.tmux)
            if r:
                break
            time.sleep(0.1)
        self.assertEqual(r, ("error", "ERROR: (gcloud.auth.login) bad code"))

    def test_second_start_refused_and_waiting_state(self):
        gauth.start("proj", tmux=self.tmux)
        w = json.loads((self.state / "gauth" / "proj.waiting").read_text())
        self.assertEqual(w["window"], "gauth-proj")
        self.assertIn("started", w)
        with self.assertRaises(gauth.GauthError) as cm:
            gauth.start("proj", tmux=self.tmux)
        self.assertEqual(str(cm.exception), "a /gauth for proj is already waiting for its code")
        self.assertEqual(self.windows().count("proj-bg:gauth-proj"), 1)

    def test_stale_waiting_file_does_not_block(self):
        d = self.state / "gauth"
        (d / "proj.waiting").write_text(json.dumps({"started": 1, "window": "gauth-proj"}))
        gauth.start("proj", tmux=self.tmux)  # no such window: the file is stale
        self.assertIn("proj-bg:gauth-proj", self.windows())

    def test_start_without_config_opens_nothing(self):
        with self.assertRaises(gauth.GauthError):
            gauth.start("other", tmux=self.tmux)
        self.assertFalse([w for w in self.windows() if "gauth" in w])

    def test_send_code_rejects_newline(self):
        with self.assertRaises(gauth.GauthError):
            gauth.send_code("proj", "a\nb", tmux=self.tmux)


class TokenCheckTest(Base):
    def test_ok_never_prints_token(self):
        for adc, want in ((True, "auth application-default print-access-token"), (False, "auth print-access-token")):
            msg = gauth.token_check({"adc": adc, "impersonate": "", "account": ""})
            self.assertEqual(msg, "token ok")
            self.assertNotIn(TOKEN, msg)
            self.assertEqual(self.argv()[-1], want)

    def test_failure_returns_last_stderr_line(self):
        (self.bin / "token-fail").write_text("")
        msg = gauth.token_check({"adc": True, "impersonate": "", "account": ""})
        self.assertEqual(msg, "ERROR: (gcloud.auth.print-access-token) reauth needed")
        self.assertNotIn(TOKEN, msg)


if __name__ == "__main__":
    unittest.main()
