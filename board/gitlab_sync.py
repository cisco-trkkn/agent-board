#!/usr/bin/env python3
"""gitlab_sync: one-way sync of a project's ideas file to GitLab issues (see ideas.py, `sync`).

Config  ~/.config/agent-board/gitlab.json (or $TC_GITLAB_CONF): {"<project>": {"repo": "grp/proj", "since": "YYYY-MM-DD"}}
Sidecar <ideas_dir>/<project>.gitlab.json   what was last pushed per issue iid: {"<iid>": {"ts", "title", "state"}}
Status  <ideas_dir>/<project>.gitlab-status.json   {"at", "ok", "error", "pending"} after each real pass
"""
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python3 -I implies -P
import ideas  # noqa: E402


class GlabError(RuntimeError): pass
class RateLimited(GlabError): pass
class ConfigError(ValueError): pass


def _parse(raw):
    head, _, body = raw.replace("\r\n", "\n").partition("\n\n")
    lines = head.split("\n")
    hdr = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:])}
    return int(lines[0].split()[1]), hdr, body


def _json(code, body):
    """The decoded body; text that is not JSON (a Rack::Attack 429, a Cloudflare 502 page) is a GlabError."""
    if not body.strip():
        return None
    try:
        return json.loads(body)
    except ValueError:
        what = f"HTTP {code}: {body.strip()[:200]}" if code >= 400 else f"HTTP {code}: reply is not JSON: {body.strip()[:200]}"
        raise GlabError(what) from None


def api(method, path, fields=()):
    cmd = ["glab", "api", "-i", "-X", method, path]
    for k, v in fields:
        cmd += ["-f", f"{k}={v}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GlabError(f"glab: {e}") from e
    if not r.stdout.startswith("HTTP/"):
        raise GlabError((r.stderr.strip().splitlines() or [f"glab exited {r.returncode}"])[-1])
    code, hdr, raw = _parse(r.stdout)
    if code == 429 or hdr.get("ratelimit-remaining") == "0":
        raise RateLimited(f"rate limited (HTTP {code})")
    body = _json(code, raw)
    if code >= 400:
        raise GlabError(f"HTTP {code}: {body.get('message') if isinstance(body, dict) else body}")
    return body


# ---- config -----------------------------------------------------------------------------------

def conf_path():
    if os.environ.get("TC_GITLAB_CONF"):
        return Path(os.environ["TC_GITLAB_CONF"])
    if os.environ.get("TC_IDEAS_DIR"):
        return None
    return Path.home() / ".config" / "agent-board" / "gitlab.json"


def _read_conf():
    p = conf_path()
    if p is None or not p.is_file():
        return None
    try:
        conf = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        raise ConfigError(f"{p}: {e}") from e
    if not isinstance(conf, dict):
        raise ConfigError(f"{p}: expected an object keyed by project")
    return conf


def mapping(project):
    conf = _read_conf()
    m = conf.get(project) if conf else None
    if m is None:
        return None
    if not isinstance(m, dict) or not isinstance(m.get("repo"), str) or not m["repo"].strip():
        raise ConfigError(f"{project}: missing repo")
    since = m.get("since")
    if not isinstance(since, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        raise ConfigError(f"{project}: since must be YYYY-MM-DD")
    return {"repo": m["repo"].strip(), "since": since}


def mapped(project):
    """True when sync has something to do or to report: the project is named, or the file is broken."""
    try:
        return mapping(project) is not None
    except ConfigError:
        return True


# ---- files ------------------------------------------------------------------------------------

def _sidecar_path(project):
    return ideas.ideas_dir() / f"{project}.gitlab.json"


def _load_sidecar(project):
    try:
        return json.loads(_sidecar_path(project).read_text())
    except (OSError, ValueError):
        return {}


def _write_atomic(path, obj, lock_project=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    lk = open(f"{ideas.ideas_path(lock_project)}.lock", "w") if lock_project else None
    try:
        if lk:
            fcntl.lockf(lk, fcntl.LOCK_EX)
        tmp.write_text(json.dumps(obj, indent=1))
        os.replace(tmp, path)
    finally:
        if lk:
            lk.close()


def _save_entry(project, side, iid, entry):
    side[str(iid)] = entry
    _write_atomic(_sidecar_path(project), side, lock_project=project)


def _write_status(project, ok, error, pending):
    _write_atomic(ideas.ideas_dir() / f"{project}.gitlab-status.json",
                  {"at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                   "ok": ok, "error": error, "pending": pending})


# ---- reconcile --------------------------------------------------------------------------------

TITLE_MAX = 255   # GitLab rejects longer issue titles


def _title(text):
    return text if len(text) <= TITLE_MAX else text[:TITLE_MAX - 1] + "…"


def _marker(project, idea, todo):
    """<ts>#<n>: n = 1-based position among ALL lines with this ts, in file order. Ideas are never deleted
    and a move leaves the source line in place, so n survives edits."""
    n = 1 + sum(1 for i in todo[:todo.index(idea)] if i["ts"] == idea["ts"])
    return f"<!-- agent-board:{project}:{idea['ts']}#{n} -->"


def _want(idea):
    if idea["status"] == "open":
        return "open"
    if idea["status"] == "taken":
        return "closed-done"
    return "closed-moved" if idea["moved_to"] else "closed-dropped"


def _ops(idea, entry, base):
    """The pushes this issue needs: [(action label, [(method, path, fields)], entry changes)]."""
    iid, url, text, want = idea["issue"], f"{base}/{idea['issue']}", idea["text"], _want(idea)
    close = ("PUT", url, [("state_event", "close")])
    ops = []
    if want == "open":
        if entry["state"] != "open":
            ops.append((f"reopen #{iid}", [("PUT", url, [("state_event", "reopen"), ("remove_labels", "not-planned")])],
                        {"state": "open"}))
        if entry["title"] != _title(text):
            ops.append((f"retitle #{iid}", [("PUT", url, [("title", _title(text))])], {"title": _title(text)}))
    elif entry["state"] != want:
        if want == "closed-done":
            suffix = text.rsplit(" → ", 1)[1] if " → " in text else text
            ops.append((f"close-done #{iid}", [close, ("POST", f"{url}/notes", [("body", f"Taken up → {suffix}")])],
                        {"state": want}))
        elif want == "closed-moved":
            ops.append((f"close-moved #{iid}", [close, ("POST", f"{url}/notes", [("body", f"Moved to {idea['moved_to']}")])],
                        {"state": want}))
        else:
            ops.append((f"close-dropped #{iid}", [("PUT", url, [("state_event", "close"), ("add_labels", "not-planned")])],
                        {"state": want}))
    return ops


def _entry(idea, side):
    return side.get(str(idea["issue"])) or {"title": _title(idea["text"]), "state": "open"}


def _needs(idea, side, since, base):
    if idea["issue"] is None:
        return idea["status"] == "open" and idea["ts"][:10] >= since
    return bool(_ops(idea, _entry(idea, side), base))


def sync(project, dry_run=False):
    """Returns {"ok", "error", "pending", "actions", "skipped"}. Raises ConfigError (after recording it)."""
    out = {"ok": True, "error": "", "pending": 0, "actions": [], "skipped": False}
    try:
        m = mapping(project)
    except ConfigError as e:
        if not dry_run:
            _write_status(project, False, str(e), 0)
        raise
    if m is None:
        return out
    d = ideas.ideas_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{project}.md.sync.lock", "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            out["skipped"] = True
            return out
        _pass(project, m, dry_run, out)
    if not dry_run:
        _write_status(project, out["ok"], out["error"], out["pending"])
    return out


def _fail(out, e):
    out["ok"] = False
    out["error"] = out["error"] or str(e)
    out["pending"] += 1


def _pass(project, m, dry_run, out):
    base = f"projects/{urllib.parse.quote(m['repo'], safe='')}/issues"
    side = _load_sidecar(project)
    todo = ideas.load(project)
    for n, idea in enumerate(todo):
        try:
            _one(project, m, base, side, idea, todo, dry_run, out)
        except RateLimited as e:
            _fail(out, e)
            out["pending"] += sum(_needs(i, side, m["since"], base) for i in todo[n + 1:])
            return
        except GlabError as e:
            _fail(out, e)


def _one(project, m, base, side, idea, todo, dry_run, out):
    if idea["issue"] is None:
        if not _needs(idea, side, m["since"], base):
            return
        mk = _marker(project, idea, todo)
        found = api("GET", base, [("search", mk), ("in", "description"), ("state", "all"), ("per_page", "20")]) or []
        hit = next((r for r in found if mk in (r.get("description") or "")), None)
        if dry_run:
            out["actions"].append(f'adopt #{hit["iid"]} "{_title(idea["text"])}"' if hit else f'create "{_title(idea["text"])}"')
            return
        if hit:
            iid, entry = hit["iid"], {"ts": idea["ts"], "title": hit.get("title") or _title(idea["text"]),
                                      "state": "open" if hit.get("state") != "closed" else "closed-adopted"}
        else:
            body = api("POST", base, [("title", _title(idea["text"])), ("labels", "idea"), ("description", mk)])
            if not isinstance(body, dict) or "iid" not in body:
                raise GlabError("create returned no iid")
            iid, entry = body["iid"], {"ts": idea["ts"], "title": _title(idea["text"]), "state": "open"}
        try:
            ideas.set_issue(project, idea["key"], iid)
        except ideas.Stale:
            out["pending"] += 1   # the next pass finds the issue by its marker
            return
        _save_entry(project, side, iid, entry)
        idea = {**idea, "issue": iid}
    entry = dict(_entry(idea, side))
    for label, calls, change in _ops(idea, entry, base):
        out["actions"].append(label)
        if dry_run:
            continue
        for method, path, fields in calls:
            api(method, path, fields)
        entry = {**entry, "ts": idea["ts"], **change}
        _save_entry(project, side, idea["issue"], entry)


# ---- triggers and board ------------------------------------------------------------------------

def kick(project):
    """Start a detached `ideas.py sync` for a mapped project; nothing for an unmapped one."""
    if not mapped(project):
        return
    subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve().parent / "ideas.py"), "sync", "--project", project],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def mapped_projects():
    try:
        conf = _read_conf() or {}
    except ConfigError:
        return []
    out = []
    for name in conf:
        try:
            ideas.ideas_path(name)
        except ValueError:
            continue
        out.append(name)
    return out


def board_info(project):
    """None when unmapped, else what the Ideas box shows: the repo link and the last pass's outcome."""
    try:
        m = mapping(project)
    except ConfigError as e:
        return {"repo": "", "url": "", "ok": False, "error": str(e)}
    if m is None:
        return None
    try:
        st = json.loads((ideas.ideas_dir() / f"{project}.gitlab-status.json").read_text())
    except (OSError, ValueError):
        st = {}
    return {"repo": m["repo"], "url": f"https://gitlab.com/{m['repo']}",
            "ok": bool(st.get("ok", True)), "error": str(st.get("error") or "")}
