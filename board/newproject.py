"""newproject: the /new-project step machine (spec docs/superpowers/specs/2026-11-23-new-project-remote-design.md).

Seven steps, in order: disk, bot, check, joined, channel, access, start. Each step's state is one of pending, running,
waiting, done, failed; it lives with its last error in <agent_base>/newproject/<name>.json (mode 600), never the token.
Mac-side steps run tmux-ctl in a worker (`_spawn`); the two Discord-side steps are create_channel / channel_overwrite
outbox ops on the ops bridge, answered by np_result events that carry the op's req. Every worker result is applied only
if the step still carries the worker's run id, so a stale or repeated answer changes nothing. The card is one post in the
command center (key np:<name>:<n>), edited after every change. discord_ops dispatches the events here; its tick calls tick().
Seams for tests: _http, _run, _spawn, _clock, _session_exists, _env_fn. Test: tests/test_newproject.py."""
import contextlib
import fcntl
import functools
import json
import os
import re
import secrets
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import discord_feed
import tc_env

STEPS = ("disk", "bot", "check", "joined", "channel", "access", "start")
LABELS = {"disk": "Project on disk", "bot": "Bot", "check": "Check", "joined": "Joined", "channel": "Channel",
          "access": "Access", "start": "Start"}
# The eight home-channel permissions of docs/INSTALL.md: View 1<<10, Send Messages 1<<11, Send Messages in Threads 1<<38,
# Create Public Threads 1<<35, Pin Messages 1<<51, Read Message History 1<<16, Add Reactions 1<<6, Attach Files 1<<15.
PERMS = sum(1 << b for b in (10, 11, 38, 35, 51, 16, 6, 15))   # 2252109051432000
INTENT_FLAGS = (1 << 18) | (1 << 19)   # GATEWAY_MESSAGE_CONTENT | GATEWAY_MESSAGE_CONTENT_LIMITED
POLL_S = 10
JOIN_TIMEOUT_S = 1800
DISK_TIMEOUT_S = 1800      # a clone can be slow: the disk step gets its own, much longer, tmux-ctl timeout
STALE_RUN_S = 900          # a running step whose worker or bridge answer never came (board restart, lost op)
TOKEN_FILE_TTL_S = 600     # a one-shot token file no event claimed is deleted after this
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$")
TOKEN_FILE_RE = re.compile(r"^[0-9]+-[0-9a-f]{8}\.tok$")
API = "https://discord.com/api/v10"
PORTAL = "https://discord.com/developers/applications"
TMUX_CTL = Path(__file__).resolve().parent.parent / "bin" / "tmux-ctl"
EMOJI = {"pending": "▫️", "running": "⏳", "waiting": "⏳", "done": "✅", "failed": "❌"}

_clock = time.time
_env_fn = lambda: dict(os.environ)   # noqa: E731 -- board/server.py sets it to tmux_env, so tmux-ctl reaches the board's server
_THREAD_LOCK = threading.Lock()


class StepFailed(Exception):
    pass


def _spawn(fn):
    threading.Thread(target=fn, daemon=True).start()


def _run(argv, stdin=None, timeout=180):
    """(rc, combined output). A timeout or a missing binary is rc 124 / 127 with a one-line reason."""
    try:
        # own process group: on a timeout the whole tree (zsh and the git clone under it) dies, not only the shell
        p = subprocess.Popen([str(a) for a in argv], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env=_env_fn(), start_new_session=True)
    except OSError as e:
        return 127, type(e).__name__
    try:
        out, err = p.communicate(input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        return 124, f"timed out after {timeout}s"
    return p.returncode, (out + err).strip()


@functools.lru_cache(maxsize=None)
def _ssl_context():
    """Default verifying context; python.org builds ship no CA bundle, so load SSL_CERT_FILE or the macOS system bundle."""
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) == 0:
        for cafile in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem"):
            if cafile and os.path.exists(cafile):
                ctx.load_verify_locations(cafile=cafile)
                break
    return ctx


def _http(method, path, token):
    """(status, parsed JSON or None) for a Discord REST call with a bot token. A network failure raises OSError."""
    req = urllib.request.Request(API + path, method=method, headers={
        "Authorization": f"Bot {token}", "User-Agent": "DiscordBot (agent-board, 1)"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, None


def _session_exists(name):
    import paneclass
    try:
        return subprocess.run(paneclass.tmux_cmd() + ["has-session", "-t", f"={name}"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ---- state ----
def _dir():
    return tc_env.agent_base() / "newproject"


def _path(name):
    return _dir() / f"{name}.json"


def token_dir():
    return tc_env.ops_dir() / "np-token"


def load(name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        return None
    try:
        v = json.loads(_path(name).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _save(st):
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    tmp = d / f".{st['name']}.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, _path(st["name"]))


@contextlib.contextmanager
def _locked(name):
    """flock on <dir>/.<name>.lock, plus a process lock (flock is per open file, threads of this process share it safely
    only through separate fds). Never nested: every caller releases it before _advance."""
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        with open(d / f".{name}.lock", "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def _step(st, s):
    return st["steps"][s]


def _set(st, s, state, error="", **kw):
    st["steps"][s] = {"state": state, "error": error, "at": _clock(), **kw}


def _last_line(out):
    lines = [l.strip() for l in str(out or "").splitlines() if l.strip()]
    return lines[-1][:300] if lines else ""


def _scrub(text, secret):
    return str(text).replace(secret, "***") if secret else str(text)


def _say(msg):
    print(f"newproject: {msg}", file=sys.stderr, flush=True)


def _env_token(name):
    """The project bot's saved token (<discord dir>/<name>/.env), read the way bridge.js readToken does."""
    try:
        txt = (tc_env.discord_dir(name) / ".env").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^DISCORD_BOT_TOKEN=(.*)$", txt, re.M)
    return m.group(1).strip().strip("\"'") if m else None


# ---- the card ----
def invite_url(st):
    return (f"https://discord.com/oauth2/authorize?client_id={st['app_id']}&scope=bot&permissions={PERMS}"
            f"&guild_id={st['guild']}&disable_guild_select=true")


def _line(st, s):
    step = _step(st, s)
    state, err = step["state"], step.get("error") or ""
    n = STEPS.index(s) + 1
    head = f"{EMOJI[state]} {n}. {LABELS[s]}"
    if s == "disk" and state == "done":
        return f"{head}: {st.get('dir')}"
    if s == "bot" and state in ("waiting", "running"):
        body = (f"{head}: in the Developer Portal ({PORTAL}) New Application → Bot → turn on Message Content Intent → "
                f"Reset Token, then Paste token")
        return body + (f"\n   {err}" if err else "")
    if s == "check" and state == "done":
        return f"{head}: bot {st.get('bot_id')} ok · Invite: {invite_url(st)}"
    if s == "joined" and state == "waiting":
        return f"{head}: open the Invite link above and add the bot (checking every {POLL_S} s, up to {JOIN_TIMEOUT_S // 60} min)"
    if s == "channel" and state == "done":
        return f"{head}: <#{st.get('channel_id')}>"
    if s == "start" and state == "done":
        return f"{head}: bridge and lead started; the lead says hello in <#{st.get('channel_id')}>"
    return f"{head}: {err}" if state == "failed" and err else head


def render(st):
    """(text, rows) of the setup card."""
    src = st["source"] + (f" {st['target']}" if st.get("target") else "")
    lines = [f"🆕 new project {st['name']} ({src})"] + [_line(st, s) for s in STEPS]
    if st.get("done"):
        lines.append(f"Done: https://discord.com/channels/{st['guild']}/{st['channel_id']}")
    row = []
    if _step(st, "bot")["state"] == "waiting":
        row.append({"label": "Paste token", "style": 1, "custom_id": f"ab:np:token:{st['name']}"})
    for s in STEPS:
        if _step(st, s)["state"] == "failed":
            row.append({"label": f"Retry {LABELS[s].lower()}", "style": 2, "custom_id": f"ab:np:retry:{st['name']}:{s}"})
    return "\n".join(lines)[:2000], ([row[:5]] if row else [])


def _card(d, st):
    text, rows = render(st)
    discord_feed.outbox_write(d, {"op": "edit", "key": st["card"], "text": text, "rows": rows})


def _post_card(d, st):
    text, rows = render(st)
    op = {"op": "post", "text": text, "tier": "decision", "mention_user": False, "key": st["card"]}
    if rows:
        op["rows"] = rows
    discord_feed.outbox_write(d, op)


def _ireply(d, iid, content):
    if iid:
        discord_feed.outbox_write(d, {"op": "ireply", "iid": str(iid), "content": str(content)[:1900], "private": True})


def _audit(d, user, step, name, result):
    discord_feed.audit_append(d, str(user or ""), "newproject", f"{name}:np:{step}", result)


# ---- refusals and the start of a setup ----
def _command_center():
    try:
        return str(json.loads((tc_env.ops_dir() / "bridge.json").read_text(encoding="utf-8")).get("command_center") or "")
    except (OSError, ValueError):
        return ""


def _guild():
    try:
        return str(json.loads((tc_env.ops_dir() / "bridge-state.json").read_text(encoding="utf-8")).get("guild_id") or "")
    except (OSError, ValueError):
        return ""


def _refusal(name, source, target):
    if not NAME_RE.match(name or ""):
        return "Bad name: letters, digits, '_' and '-', starting with a letter or digit, at most 60."
    if source not in ("new", "clone", "folder"):
        return "Source must be new, clone or folder."
    if source != "new" and not target:
        return f"Source {source} needs a {'git URL' if source == 'clone' else 'path'}."
    if tc_env.discord_dir(name).exists():
        return f"A project state dir for {name} already exists ({tc_env.discord_dir(name)})."
    if _session_exists(name):
        return f"A tmux session {name} already exists."
    if source in ("new", "clone") and (Path.home() / name).exists():
        return f"~/{name} already exists."
    if source == "folder":
        p = Path(os.path.expanduser(target)).resolve()
        rc, top = _run(["git", "-C", str(p), "rev-parse", "--show-toplevel"], timeout=20)
        if not p.is_dir() or rc != 0 or Path(top.strip()).resolve() != p:
            return f"{target} is not a git work tree."
        if p.name != name:
            return f"The folder is named {p.name}, not {name}: the dev session takes the folder's name."
    if not _guild():
        return "The ops bot has not connected yet; try again in a minute."
    return None


def on_modal(d, ev):
    """The new-project form. Answers one private line; posts the card and runs the first step, or resumes."""
    f = ev.get("fields") if isinstance(ev.get("fields"), dict) else {}
    name, source, target = str(f.get("name") or ""), str(f.get("source") or ""), str(f.get("target") or "").strip()
    user, iid = str(ev.get("user") or ""), ev.get("iid")
    if str(ev.get("channel_id") or "") != _command_center():
        _ireply(d, iid, "Use /new-project in the command center.")
        return "refused: not the command center"
    st = load(name)
    if st is not None:
        return _resume(d, st, iid, source, target)
    why = _refusal(name, source, target)
    if why:
        _ireply(d, iid, why)
        return f"refused: {why}"[:80]
    st = {"name": name, "source": source, "target": target if source != "new" else "", "dir": None, "user": user,
          "guild": _guild(), "bot_id": None, "app_id": None, "channel_id": None, "card": f"np:{name}:1", "n": 1,
          "steps": {}, "req": {}, "join": {}, "created": _clock(), "done": False}
    for s in STEPS:
        _set(st, s, "pending")
    with _locked(name):
        _save(st)
    _post_card(d, st)
    _ireply(d, iid, f"Setting up {name}: follow the card in this channel.")
    _advance(d, name)
    return "started"


def _correct(st, source, target):
    """The form named an unfinished setup whose disk step is not done: its source and target replace the saved ones
    (a mistyped URL is fixed from the phone). Returns (changed, refusal)."""
    if _step(st, "disk")["state"] == "done" or not source or (source, target) == (st["source"], st.get("target") or ""):
        return False, None
    if source not in ("new", "clone", "folder"):
        return False, "Source must be new, clone or folder."
    if source != "new" and not target:
        return False, f"Source {source} needs a {'git URL' if source == 'clone' else 'path'}."
    if _step(st, "disk")["state"] == "running":
        return False, "The project folder is still being made; wait for it to finish or fail, then submit again."
    if source == "folder":
        p = Path(os.path.expanduser(target)).resolve()
        rc, top = _run(["git", "-C", str(p), "rev-parse", "--show-toplevel"], timeout=20)
        if not p.is_dir() or rc != 0 or Path(top.strip()).resolve() != p:
            return False, f"{target} is not a git work tree."
        if p.name != st["name"]:
            return False, f"The folder is named {p.name}, not {st['name']}: the dev session takes the folder's name."
    return True, None


def _resume(d, st, iid, source="", target=""):
    if st.get("done"):
        _ireply(d, iid, f"{st['name']} is already set up.")
        return "already set up"
    name = st["name"]
    changed, why = _correct(st, source, target)
    if why:
        _ireply(d, iid, why)
        return f"refused: {why}"[:80]
    with _locked(name):
        st = load(name)
        if changed and _step(st, "disk")["state"] != "running":
            st["source"], st["target"], st["dir"] = source, (target if source != "new" else ""), None
            _set(st, "disk", "pending")
        else:
            changed = False
        old = st["card"]
        st["n"] = int(st.get("n") or 1) + 1
        st["card"] = f"np:{st['name']}:{st['n']}"
        _save(st)
    text, _ = render(st)
    discord_feed.outbox_write(d, {"op": "edit", "key": old, "text": f"{text}\n(moved to a new card below)"[:2000], "rows": []})
    _post_card(d, st)
    _ireply(d, iid, f"Resumed {st['name']}: the setup card is below.")
    if changed:
        _advance(d, name)
    return "resumed"


def on_slash(d, ev):
    """/new-project <name>: resume an unfinished setup."""
    name, iid = str(ev.get("name") or ""), ev.get("iid")
    if str(ev.get("channel_id") or "") != _command_center():
        _ireply(d, iid, "Use /new-project in the command center.")
        return "refused: not the command center"
    st = load(name)
    if st is None:
        _ireply(d, iid, f"No setup for {name}; run /new-project without a name to start one.")
        return "no setup"
    return _resume(d, st, iid)


# ---- running steps ----
def _next(st):
    for s in STEPS:
        if _step(st, s)["state"] != "done":
            return s
    return None


def _advance(d, name):
    """Start the first step that is not done, if it is pending. Never called with the lock held."""
    st = load(name)
    if st is None or st.get("done"):
        return
    s = _next(st)
    if s is None or _step(st, s)["state"] != "pending":
        return
    if s == "disk":
        _start(d, name, "disk", _do_disk)
    elif s == "bot":
        with _locked(name):
            st = load(name)
            _set(st, "bot", "waiting")
            _save(st)
        _card(d, st)
    elif s == "check":
        _start(d, name, "check", _do_check)
    elif s == "joined":
        with _locked(name):
            st = load(name)
            _set(st, "joined", "waiting")
            st["join"] = {"since": _clock(), "last": 0, "inflight": None}
            _save(st)
        _card(d, st)
    elif s == "channel":
        _channel_op(d, name)
    elif s == "access":
        _start(d, name, "access", _do_access)
    elif s == "start":
        _start(d, name, "start", _do_start)


def _start(d, name, s, fn, payload=None):
    """Mark s running with a fresh run id, then run fn(st, payload) -> dict of state updates in a worker. The result
    lands only while the step still carries that run id."""
    run = secrets.token_hex(4)
    with _locked(name):
        st = load(name)
        _set(st, s, "running", run=run)
        _save(st)
    _card(d, st)

    def go():
        secret = payload if isinstance(payload, str) else None
        try:
            upd, err = fn(load(name), payload) or {}, None
        except StepFailed as e:
            upd, err = None, _scrub(e, secret)
        except Exception as e:   # noqa: BLE001 -- only the class leaves the worker: the text could echo a token
            upd, err = None, f"failed ({type(e).__name__})"
        with _locked(name):
            st = load(name)
            if st is None or _step(st, s).get("run") != run:
                _say(f"{name} {s}: stale result dropped")
                return
            if err is None:
                for k, v in upd.items():
                    if k != "_steps":
                        st[k] = v
                _set(st, s, "done")
            elif s == "bot":   # a token that could not be saved: back to waiting, Paste token again
                _set(st, "bot", "waiting", f"could not save the token: {err}"[:300])
            else:
                _set(st, s, "failed", err[:300])
            if err is None:
                for k, (state, e2) in upd.get("_steps", {}).items():
                    _set(st, k, state, e2)
            if err is not None and s == "check" and err.startswith("token rejected"):
                _set(st, "bot", "waiting", "token rejected: Paste token again")
            if s == "start" and err is None:
                st["done"] = True
            _save(st)
        _card(d, st)
        _audit(d, st.get("user"), s, name, "done" if err is None else f"failed: {err}"[:80])
        _say(f"{name} {s}: {'done' if err is None else 'failed'}")
        if err is None:
            _advance(d, name)
    _spawn(go)


def _ctl(*args, stdin=None, timeout=180):
    rc, out = _run([TMUX_CTL, *args], stdin=stdin, timeout=timeout)
    if rc != 0:
        raise StepFailed(_last_line(out) or f"tmux-ctl {args[0]} exited {rc}")
    return out


def _do_disk(st, _):
    flag = {"new": ["--init"], "clone": ["--clone", st["target"]], "folder": ["--dir", os.path.expanduser(st["target"])]}[st["source"]]
    out = _ctl("project", "new", st["name"], *flag, timeout=DISK_TIMEOUT_S)
    return {"dir": _last_line(out)}


def _do_token(st, tok):
    """Pipe the pasted token into tmux-ctl discord token (stdin only)."""
    _ctl("discord", "token", "--project", st["name"], stdin=tok + "\n")
    return {}


def _do_check(st, _):
    tok = _env_token(st["name"])
    if not tok:
        raise StepFailed("token rejected: no saved token")
    try:
        code, me = _http("GET", "/users/@me", tok)
        if code == 401:
            raise StepFailed("token rejected")
        if code != 200 or not isinstance(me, dict) or not me.get("id"):
            raise StepFailed(f"Discord answered {code} for the bot user")
        code, app = _http("GET", "/applications/@me", tok)
        if code != 200 or not isinstance(app, dict):
            raise StepFailed(f"Discord answered {code} for the application")
    except OSError as e:
        raise StepFailed(f"Discord unreachable ({type(e).__name__})")
    if not int(app.get("flags") or 0) & INTENT_FLAGS:
        raise StepFailed("turn on Message Content Intent, then Retry")
    return {"bot_id": str(me["id"]), "app_id": str(app.get("id") or me["id"])}


def _do_access(st, _):
    _ctl("discord", "allow", st["user"], "--project", st["name"])
    _ctl("discord", "policy", "allowlist", "--project", st["name"])
    _ctl("discord", "channel", st["channel_id"], "--project", st["name"])
    return {}


def _do_start(st, _):
    try:
        _ctl("discord", "bridge", "start", "--project", st["name"])
    except StepFailed as e:
        raise StepFailed(f"bridge: {e}")
    extra = ["--dir", st["dir"]] if st["source"] == "folder" and st.get("dir") else []
    _ctl("project", "start", st["name"], *extra)
    return {}


def _channel_op(d, name):
    """Step 5: create_channel, or straight to channel_overwrite when a retry already knows the channel."""
    req = secrets.token_hex(4)
    with _locked(name):
        st = load(name)
        _set(st, "channel", "running", run=req)
        st["req"] = {"channel": req}
        _save(st)
    if st.get("channel_id"):
        _overwrite_op(d, st)
    else:
        discord_feed.outbox_write(d, {"op": "create_channel", "guild": st["guild"], "name": name, "req": req})
    _card(d, st)


def _overwrite_op(d, st):
    discord_feed.outbox_write(d, {"op": "channel_overwrite", "channel": st["channel_id"], "user": st["bot_id"],
                                  "allow": str(PERMS), "name": st["name"], "req": st["req"]["channel"]})


def on_result(d, ev):
    """np_result from the ops bridge. Matched by req: a stale, repeated or out-of-order answer is dropped."""
    name, req, action = str(ev.get("name") or ""), str(ev.get("req") or ""), ev.get("action")
    advance = False
    with _locked(name) if NAME_RE.match(name) else contextlib.nullcontext():
        st = load(name)
        if st is None or _step(st, "channel")["state"] != "running" or (st.get("req") or {}).get("channel") != req:
            return "stale"
        if action == "create_channel" and not st.get("channel_id"):
            if ev.get("ok") and re.match(r"^[0-9]{1,20}$", str(ev.get("channel_id") or "")):
                st["channel_id"] = str(ev["channel_id"])
                _save(st)
                _overwrite_op(d, st)
                result = "channel created"
            else:
                err = "ops bot lacks Manage Channels" if ev.get("error") == "missing permissions" else f"could not create the channel: {ev.get('error')}"
                _set(st, "channel", "failed", err[:300])
                _save(st)
                result = "failed"
        elif action == "channel_overwrite" and st.get("channel_id"):
            if ev.get("ok"):
                _set(st, "channel", "done")
                result, advance = "done", True
            else:
                err = ("ops bot lacks Manage Roles (or one of the eight permissions) for the channel overwrite"
                       if ev.get("error") == "missing permissions" else f"could not set the channel overwrite: {ev.get('error')}")
                _set(st, "channel", "failed", err[:300])
                result = "failed"
            _save(st)
        else:
            return "stale"
    _card(d, st)
    if result in ("done", "failed"):
        _audit(d, st.get("user"), "channel", name, result)
    if advance:
        _advance(d, name)
    return result


def drop_token_file(ev):
    """Delete the one-shot token file an np_token event names (only a valid name inside the token dir)."""
    f = str(ev.get("file") or "")
    if TOKEN_FILE_RE.match(f):
        try:
            (token_dir() / f).unlink()
        except OSError:
            pass


def on_token(d, ev):
    """np_token: read the one-shot file, delete it whatever happens, and run the bot step (save) then check."""
    name, iid = str(ev.get("name") or ""), ev.get("iid")
    tok = ""
    try:
        f = str(ev.get("file") or "")
        if TOKEN_FILE_RE.match(f):
            try:
                tok = (token_dir() / f).read_text(encoding="utf-8").strip()
            except OSError:
                tok = ""
    finally:
        drop_token_file(ev)
    st = load(name)
    if st is None or _step(st, "bot")["state"] != "waiting":
        _ireply(d, iid, f"No setup of {name} is waiting for a token.")
        return "not waiting"
    if not tok or any(c.isspace() for c in tok):
        _ireply(d, iid, "That does not look like a bot token; Paste token again.")
        return "bad token"
    _ireply(d, iid, "Token received; checking it.")

    def save(st, tok):
        _do_token(st, tok)
        # the check step runs next from _advance; a token pasted after a rejected check re-arms that check
        return {"_steps": {"check": ("pending", "")}}
    _start(d, name, "bot", save, payload=tok)
    return "token received"


def on_click(d, user, cid):
    """ab:np:retry:<name>:<step>: rerun only that step, and only when it failed."""
    parts = cid.split(":")
    if len(parts) != 5 or parts[:3] != ["ab", "np", "retry"] or parts[4] not in STEPS:
        return "ignored"
    name, s = parts[3], parts[4]
    st = load(name)
    if st is None:
        return "unknown"
    if _step(st, s)["state"] != "failed":
        return "not failed"
    with _locked(name):
        st = load(name)
        _set(st, s, "pending")
        _save(st)
    _audit(d, user, s, name, "retry")
    _advance(d, name)
    return "retrying"


# ---- tick: the joined poll, stale runs, orphan token files ----
def _poll(d, name, run):
    st = load(name)
    tok = _env_token(name)
    err, joined = None, False
    try:
        code, guilds = _http("GET", "/users/@me/guilds", tok or "")
        if code == 401:
            err = "token rejected"
        elif code == 200 and isinstance(guilds, list):
            joined = any(str(g.get("id")) == st["guild"] for g in guilds if isinstance(g, dict))
    except OSError:
        pass   # a network blip: the next poll tries again
    with _locked(name):
        st = load(name)
        if st is None or (st.get("join") or {}).get("inflight") != run or _step(st, "joined")["state"] != "waiting":
            return
        st["join"]["inflight"] = None
        st["join"]["last"] = _clock()
        if joined:
            _set(st, "joined", "done")
        elif err or _clock() - st["join"]["since"] >= JOIN_TIMEOUT_S:
            _set(st, "joined", "failed", err or "invite not accepted")
        else:
            _save(st)
            return
        _save(st)
    _card(d, st)
    _audit(d, st.get("user"), "joined", name, "done" if joined else "failed")
    if joined:
        _advance(d, name)


def tick(d, now):
    try:
        for f in token_dir().glob("*.tok"):
            try:
                if now - f.stat().st_mtime > TOKEN_FILE_TTL_S:
                    f.unlink()
            except OSError:
                pass
    except OSError:
        pass
    for p in sorted(_dir().glob("*.json")) if _dir().exists() else []:
        name = p.stem
        st = load(name)
        if st is None or st.get("done"):
            continue
        changed, stale, poll = False, False, None
        with _locked(name):
            st = load(name)
            for s in STEPS:
                step = _step(st, s)
                limit = DISK_TIMEOUT_S + STALE_RUN_S if s == "disk" else STALE_RUN_S
                if step["state"] == "running" and now - float(step.get("at") or 0) > limit:
                    _set(st, s, "failed", "no answer from the ops bridge; Retry" if s == "channel" else "interrupted; Retry")
                    changed = stale = True
            j = st.get("join") or {}
            if _step(st, "joined")["state"] == "waiting" and now - float(j.get("last") or 0) >= POLL_S:
                inflight = j.get("inflight")
                if not inflight or now - float(j.get("inflight_at") or 0) > 60:
                    poll = secrets.token_hex(4)
                    st["join"].update({"inflight": poll, "inflight_at": now})
                    changed = True
            if changed:
                _save(st)
        if stale:
            _card(d, st)
        if poll:
            _spawn(lambda n=name, r=poll: _poll(d, n, r))
