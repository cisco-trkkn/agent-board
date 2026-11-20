"""gauth: a fixed-command Google re-auth that runs in a bg tmux window (spec §6).

The command comes only from <agent_base>/gauth/<project>.json (written at the terminal by `tmux-ctl gauth config`),
never from a chat message. start opens window gauth-<project> in <project>-bg; read_url returns the sign-in URL;
send_code types the code the user pasted; result reports the outcome; close kills the window.
<agent_base>/gauth/<project>.waiting ({started, window}) exists from start until close.
Every function that touches tmux takes a `tmux(*args, check=False) -> stdout` callable (default: the real one).
Test: tests/test_gauth.py."""
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_env  # noqa: E402

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
URL_RE = re.compile(r"https://accounts\.google\.com/\S+")


class GauthError(Exception):
    pass


def _dir():
    return tc_env.agent_base() / "gauth"


def _check_name(project):
    if not isinstance(project, str) or not NAME_RE.match(project):
        raise GauthError(f"bad project name {project!r}")


def _default_tmux():
    import paneclass
    return paneclass.tmux_runner()


def _window(project):
    """"." would split a target into window and pane, so it is mapped like the session name."""
    return f"gauth-{project}".replace(".", "_").replace(":", "_")


def _last_line(e):
    lines = [l.strip() for l in str(e).splitlines() if l.strip()]
    return lines[-1] if lines else e.__class__.__name__


def _bg(project):
    """The <project>-bg session name as tmux stores it: new-session turns "." and ":" into "_"."""
    return f"{project}-bg".replace(".", "_").replace(":", "_")


def _target(project):
    return f"={_bg(project)}:={_window(project)}"


def write_config(project, adc=True, impersonate="", account=""):
    _check_name(project)
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{project}.json"
    tmp = d / f".{project}.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"adc": bool(adc), "impersonate": impersonate or "", "account": account or ""}, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    return p


def load_config(project):
    _check_name(project)
    p = _dir() / f"{project}.json"
    try:
        cfg = json.loads(p.read_text())
    except (OSError, ValueError):
        raise GauthError(f"no gauth config for {project}; set it at the terminal: tmux-ctl gauth config {project} …")
    if not isinstance(cfg, dict):
        raise GauthError(f"no gauth config for {project}; set it at the terminal: tmux-ctl gauth config {project} …")
    return {"adc": bool(cfg.get("adc", True)), "impersonate": str(cfg.get("impersonate") or ""),
            "account": str(cfg.get("account") or "")}


def build_argv(cfg):
    argv = ["gcloud", "auth"] + (["application-default", "login"] if cfg["adc"] else ["login"]) + ["--no-launch-browser"]
    if cfg.get("impersonate"):
        argv.append(f"--impersonate-service-account={cfg['impersonate']}")
    if cfg.get("account") and not cfg["adc"]:
        argv.append(f"--account={cfg['account']}")
    return argv


def _window_alive(tmux, project):
    out = tmux("list-windows", "-t", f"={_bg(project)}:", "-F", "#{window_name}")
    return _window(project) in out.split()


def start(project, tmux=None):
    cfg = load_config(project)
    tmux = tmux or _default_tmux()
    waiting = _dir() / f"{project}.waiting"
    if waiting.exists() and _window_alive(tmux, project):
        raise GauthError(f"a /gauth for {project} is already waiting for its code")
    bg = _bg(project)
    cmd = f"{shlex.join(build_argv(cfg))}; exec sleep 3600"
    home = os.path.expanduser("~")
    try:
        if not tmux("list-windows", "-t", f"={bg}:", "-F", "#{window_name}").strip():
            tmux("new-session", "-d", "-s", bg, "-n", "tests", "-c", home, check=True)
            tmux("set-option", "-t", f"={bg}:", "@tc_bg", "1")
        tmux("kill-window", "-t", _target(project))
        tmux("new-window", "-d", "-t", f"={bg}:", "-n", _window(project), "-c", home, cmd, check=True)
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        raise GauthError(f"tmux failed: {_last_line(e)}")
    _dir().mkdir(parents=True, exist_ok=True)
    waiting.write_text(json.dumps({"started": int(time.time()), "window": _window(project)}))
    return _window(project)


def _capture(project, tmux):
    return tmux("capture-pane", "-p", "-J", "-S", "-300", "-t", _target(project))


def read_url(project, tmux=None, timeout=15):
    _check_name(project)
    tmux = tmux or _default_tmux()
    end = time.time() + timeout
    while True:
        m = URL_RE.search(_capture(project, tmux))
        if m:
            return m.group(0)
        if time.time() >= end:
            return None
        time.sleep(0.2)


def send_code(project, code, tmux=None):
    _check_name(project)
    if not code or "\n" in code or "\r" in code:
        raise GauthError("the code must be one line")
    tmux = tmux or _default_tmux()
    try:
        tmux("send-keys", "-t", _target(project), "-l", "--", code, check=True)
        tmux("send-keys", "-t", _target(project), "Enter", check=True)
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        raise GauthError(f"tmux failed: {_last_line(e)}")


def result(project, tmux=None):
    _check_name(project)
    tmux = tmux or _default_tmux()
    for line in _capture(project, tmux).splitlines():
        s = line.strip()
        if "Credentials saved" in s or "You are now logged in as" in s:
            return ("ok", s)
        if s.startswith("ERROR:"):
            return ("error", s)
    return None


def token_check(cfg):
    argv = ["gcloud", "auth"] + (["application-default"] if cfg["adc"] else []) + ["print-access-token"]
    if cfg.get("impersonate"):
        argv.append(f"--impersonate-service-account={cfg['impersonate']}")
    try:
        r = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return f"could not run gcloud: {e.__class__.__name__}"
    if r.returncode == 0:
        return "token ok"
    lines = [l.strip() for l in r.stderr.splitlines() if l.strip()]
    return lines[-1] if lines else f"gcloud exited {r.returncode}"


def close(project, tmux=None):
    _check_name(project)
    tmux = tmux or _default_tmux()
    tmux("kill-window", "-t", _target(project))
    try:
        (_dir() / f"{project}.waiting").unlink()
    except OSError:
        pass


def status(project, tmux=None):
    _check_name(project)
    tmux = tmux or _default_tmux()
    if (_dir() / f"{project}.waiting").exists() and _window_alive(tmux, project):
        return "waiting"
    return "idle"


def main(argv):
    usage = "usage: gauth.py config <p> [--adc|--no-adc] [--impersonate <sa>] [--account <email>] | start|status|close|url|result|check <p>"
    if len(argv) < 2:
        print(usage, file=sys.stderr)
        return 2
    sub, project, rest = argv[0], argv[1], argv[2:]
    try:
        if sub == "config":
            adc, imp, acct, i = True, "", "", 0
            while i < len(rest):
                a = rest[i]
                if a == "--adc":
                    adc = True
                elif a == "--no-adc":
                    adc = False
                elif a in ("--impersonate", "--account") and i + 1 < len(rest):
                    if a == "--impersonate":
                        imp = rest[i + 1]
                    else:
                        acct = rest[i + 1]
                    i += 1
                else:
                    print(usage, file=sys.stderr)
                    return 2
                i += 1
            p = write_config(project, adc, imp, acct)
            print(f"gauth: config written {p}: {' '.join(build_argv(load_config(project)))}")
        elif sub == "start":
            print(f"gauth: started {start(project)}")
        elif sub == "status":
            print(f"gauth: {status(project)}")
        elif sub == "close":
            close(project)
            print("gauth: closed")
        elif sub == "url":
            print(read_url(project) or "")
        elif sub == "result":
            r = result(project)
            print(f"{r[0]}: {r[1]}" if r else "pending")
        elif sub == "check":
            print(token_check(load_config(project)))
        else:
            print(usage, file=sys.stderr)
            return 2
    except GauthError as e:
        print(f"gauth: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
