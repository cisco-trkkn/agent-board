"""scout_sources: the trend scout's sources.json, the `source` CLI, the daily poll (no model) and #scout source requests.

State lives in scout_dir() (TC_SCOUT_DIR, else ~/.local/state/agent-board/scout): sources.json (sources + health),
seen.json (keys, per-source first poll time and fetcher state, pending #scout requests), items.jsonl, poll.log.
poll() fetches each source through scout_fetch, writes unseen items, tracks failures (three in a row show in
health_report()), and drives #scout source requests: a reply is posted through the Discord REST API and the next poll
adds the source when an allowFrom user reacted with a check mark. Test: tests/test_scout_sources.py."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

import discord_feed
import scout_fetch
import tc_env

PROJECT = "agent-board"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
CHANNEL_RE = re.compile(r"^\d{15,22}$")
FIRST_POLL_CAP = 3
CAPPED_KINDS = {"changelog_md", "github_releases", "rss", "npm"}
BASELINE_KINDS = {"html_links", "html_diff"}
KEY_DAYS = 180
REQUEST_DAYS = 14
HEALTH_FAILURES = 3
CHECK = "✅"


def _src(name, kind, url, prefix=None):
    d = {"name": name, "kind": kind, "url": url, "why": "default source", "added": "builtin", "builtin": True}
    if prefix:
        d["prefix"] = prefix
    return d


DEFAULT_SOURCES = [
    _src("claude-code-changelog", "changelog_md", "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"),
    _src("claude-code-npm", "npm", "https://registry.npmjs.org/@anthropic-ai/claude-code"),
    _src("anthropic-news", "html_links", "https://www.anthropic.com/news", "/news/"),
    _src("anthropic-engineering", "html_links", "https://www.anthropic.com/engineering", "/research/"),
    _src("claude-blog", "rss", "https://claude.com/resources/articles/rss.xml"),
    _src("claude-code-release-notes", "html_diff", "https://code.claude.com/docs/en/changelog"),
    _src("api-release-notes", "html_diff", "https://platform.claude.com/docs/en/release-notes/overview"),
    _src("models-overview", "html_diff", "https://platform.claude.com/docs/en/models/overview"),
    _src("api-pricing", "html_diff", "https://platform.claude.com/docs/en/about-claude/pricing"),
    _src("plugins", "plugin", "~/.claude/plugins"),
]


class Refusal(Exception):
    pass


def scout_dir():
    env = os.environ.get("TC_SCOUT_DIR")
    return Path(env) if env else Path(os.environ.get("HOME") or str(Path.home())) / ".local" / "state" / "agent-board" / "scout"


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read(path, default):
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
        return v if default is None or isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


@contextlib.contextmanager
def _lock():
    d = scout_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "sources.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _defaults():
    rows = json.loads(json.dumps(DEFAULT_SOURCES))
    for r in rows:
        r["added"] = _iso(time.time())
    return {"sources": rows, "health": {}}


def load(create=True):
    """sources.json as {"sources": [...], "health": {...}}. A missing file is written from DEFAULT_SOURCES (unless create=False)."""
    p = scout_dir() / "sources.json"
    st = _read(p, None) if p.exists() else None
    if not isinstance(st, dict) or not isinstance(st.get("sources"), list):
        st = _defaults()
        if create:
            _atomic(p, st)
    if not isinstance(st.get("health"), dict):
        st["health"] = {}
    return st


def save(st):
    _atomic(scout_dir() / "sources.json", st)


def health_report():
    """Sources that failed HEALTH_FAILURES polls in a row: [{name, failures, last_error, last_ok}]."""
    out = []
    for name, h in sorted(load(create=False)["health"].items()):
        if isinstance(h, dict) and int(h.get("failures") or 0) >= HEALTH_FAILURES:
            out.append({"name": name, "failures": int(h["failures"]), "last_error": h.get("last_error", ""),
                        "last_ok": h.get("last_ok")})
    return out


# ---- source add / remove / list / test ---------------------------------------------------------

def _check_url(kind, url):
    if kind == "discord_channel":
        if not CHANNEL_RE.match(url or ""):
            raise Refusal("a discord_channel url must be a channel id (15-22 digits)")
    elif not (url or "").startswith("https://") or not urllib.parse.urlsplit(url).netloc:
        raise Refusal("url must start with https://")


def add_source(name, kind, url, why="", prefix=None, now=None):
    if kind not in scout_fetch.KINDS:
        raise Refusal(f"unknown kind {kind!r} (one of {', '.join(sorted(scout_fetch.KINDS))})")
    if not NAME_RE.match(name or ""):
        raise Refusal(f"bad name {name!r} (must match {NAME_RE.pattern})")
    _check_url(kind, url)
    with _lock():
        st = load()
        if any(s["name"] == name for s in st["sources"]):
            raise Refusal(f"duplicate name {name!r}")
        row = {"name": name, "kind": kind, "url": url, "why": why or "", "added": _iso(now or time.time()), "builtin": False}
        if kind == "html_links":
            row["prefix"] = prefix or urllib.parse.urlsplit(url).path.rstrip("/") + "/"
        st["sources"].append(row)
        save(st)
    return row


def remove_source(name):
    with _lock():
        st = load()
        keep = [s for s in st["sources"] if s["name"] != name]
        if len(keep) == len(st["sources"]):
            raise Refusal(f"unknown source {name!r}")
        st["sources"] = keep
        st["health"].pop(name, None)
        save(st)


def test_source(name):
    """Fetch once, return the items; nothing is written."""
    st = load(create=False)
    src = next((s for s in st["sources"] if s["name"] == name), None)
    if src is None:
        raise Refusal(f"unknown source {name!r}")
    seen = _read(scout_dir() / "seen.json", {})
    items, _ = scout_fetch.fetch(src, (seen.get("state") or {}).get(name) or {})
    return [i for i in items if "request" not in i]


test_source.__test__ = False  # not a test case for pytest collection


# ---- the poll ----------------------------------------------------------------------------------

def _log(line, now=None):
    d = scout_dir()
    d.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now or time.time()))
    with open(d / "poll.log", "a", encoding="utf-8") as f:
        f.write(f"{ts} {' '.join(str(line).split())}\n")


def _key(source, it):
    return hashlib.sha256(f"{source}\n{it['url']}\n{it.get('version') or it.get('content_hash') or ''}".encode()).hexdigest()[:16]


def _allow():
    try:
        a = json.loads((tc_env.discord_dir(PROJECT) / "access.json").read_text(encoding="utf-8")).get("allowFrom")
    except (OSError, ValueError, AttributeError):
        return set()
    return {str(x) for x in a} if isinstance(a, list) else set()


def _slug(s):
    return re.sub(r"[^a-z0-9._-]+", "-", s.lower()).strip("-._")


def request_name(url, taken):
    """Host's first label (without a leading www.) plus the path's first segment, slugged, -2/-3 on a clash."""
    u = urllib.parse.urlsplit(url)
    host = u.hostname or ""
    labels = [x for x in host.split(".") if x]
    if labels and labels[0] == "www" and len(labels) > 1:
        labels = labels[1:]
    seg = next((x for x in u.path.split("/") if x), "")
    base = _slug("-".join(x for x in (labels[0] if labels else "", urllib.parse.unquote(seg)) if x))[:34].strip("-._") or "source"
    name, n = base, 1
    while name in taken:
        n += 1
        name = f"{base}-{n}"
    return name


def _guess_kind(url):
    _, body, ctype = scout_fetch.get(url)
    head = body[:200].lstrip().lower()
    xml = "xml" in (ctype or "").lower() or head.startswith((b"<?xml", b"<rss", b"<feed"))
    return "rss" if xml else "html_links"


def _handle_requests(chan, reqs, seen, st, now):
    """New #scout requests -> a reply and a pending record. Only allowFrom user ids count."""
    allow = _allow()
    pending = {r.get("message_id") for r in seen["requests"].values()}
    for r in reqs:
        if r["author_id"] not in allow or r["message_id"] in pending:
            continue
        url = r["url"]
        try:
            if not url.startswith(("https://", "http://")):
                raise scout_fetch.FetchError("not an http(s) url")
            kind = _guess_kind(url)
            taken = {s["name"] for s in st["sources"]} | {x["name"] for x in seen["requests"].values()}
            name = request_name(url, taken)
            reply = scout_fetch.post_message(chan, f"source request: {name} ({kind}) — react {CHECK} to add",
                                             reply_to=r["message_id"])
        except Exception as e:  # noqa: BLE001
            _log(f"poll scout: request {url}: {type(e).__name__}: {e}", now)
            continue
        if reply:
            seen["requests"][reply] = {"url": url, "why": r["why"], "name": name, "kind": kind, "channel": chan,
                                       "message_id": r["message_id"], "created": _iso(now)}


def _check_requests(seen, st, now):
    """Pending requests: add the source when an allowFrom user reacted, drop after REQUEST_DAYS."""
    allow = _allow()
    for rid, r in list(seen["requests"].items()):
        created = time.mktime(time.strptime(r.get("created") or "1970-01-01T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        if now - created > REQUEST_DAYS * 86400:
            del seen["requests"][rid]
            continue
        try:
            users = scout_fetch.reactions(r["channel"], rid, CHECK)
        except Exception as e:  # noqa: BLE001
            _log(f"poll scout: reactions {rid}: {type(e).__name__}: {e}", now)
            continue
        who = next((u for u in users if u in allow), None)
        if who is None:
            continue
        name = r["name"]
        if any(s["name"] == name for s in st["sources"]):
            name = request_name(r["url"], {s["name"] for s in st["sources"]})
        row = {"name": name, "kind": r["kind"], "url": r["url"], "why": r.get("why", ""), "added": _iso(now), "builtin": False}
        if r["kind"] == "html_links":
            row["prefix"] = urllib.parse.urlsplit(r["url"]).path.rstrip("/") + "/"
        st["sources"].append(row)
        discord_feed.audit_append(tc_env.discord_dir(PROJECT), who, "scout-source", name, "added")
        del seen["requests"][rid]


def poll(now=None):
    """Run one poll -> (new items, sources polled, failed). Not model-backed."""
    now = time.time() if now is None else now
    d = scout_dir()
    with _lock():
        st = load()
        seen = _read(d / "seen.json", {})
        for k, dflt in (("keys", {}), ("sources", {}), ("state", {}), ("requests", {})):
            if not isinstance(seen.get(k), dict):
                seen[k] = dflt
        cutoff = _iso(now - KEY_DAYS * 86400)
        seen["keys"] = {k: v for k, v in seen["keys"].items() if v >= cutoff}
        n_new = failed = 0
        lines = []
        if not any(s["kind"] == "discord_channel" for s in st["sources"]):
            _log("poll scout: skipped (no #scout channel set)", now)
        elif seen["requests"]:
            _check_requests(seen, st, now)
        sources = list(st["sources"])
        for src in sources:
            name = src["name"]
            h = st["health"].setdefault(name, {"failures": 0, "last_error": "", "last_ok": None})
            try:
                items, new_state = scout_fetch.fetch(src, seen["state"].get(name) or {})
                reqs = [i["request"] for i in items if "request" in i]
                items = [i for i in items if "request" not in i]
                if src["kind"] == "plugin":
                    skipped = int((new_state or {}).get("skipped_no_version") or 0)
                    if skipped > 0:
                        _log(f"poll {name}: {skipped} without a version", now)
                    new_state = None
                first = name not in seen["sources"]
                fresh = []
                for it in items:
                    it["key"] = _key(name, it)
                    if it["key"] not in seen["keys"]:
                        fresh.append(it)
                if first and src["kind"] in BASELINE_KINDS:
                    write = []
                elif first and src["kind"] in CAPPED_KINDS:
                    write = fresh[:FIRST_POLL_CAP]
                else:
                    write = fresh
                for it in fresh:
                    seen["keys"][it["key"]] = _iso(now)
                for it in write:
                    lines.append(json.dumps({"key": it["key"], "source": name, "kind": src["kind"], "title": it["title"],
                                             "url": it["url"], "published": it.get("published"), "fetched_at": _iso(now),
                                             "excerpt": it.get("excerpt") or ""}, ensure_ascii=False))
                if new_state is not None:
                    seen["state"][name] = new_state
                seen["sources"].setdefault(name, _iso(now))
                if src["kind"] == "discord_channel" and reqs:
                    _handle_requests(scout_fetch._channel(src["url"]), reqs, seen, st, now)
                n_new += len(write)
                h.update(failures=0, last_error="", last_ok=_iso(now))
            except Exception as e:  # noqa: BLE001
                failed += 1
                msg = " ".join(f"{type(e).__name__}: {e}".split()) if not isinstance(e, scout_fetch.FetchError) else str(e)
                h["failures"] = int(h.get("failures") or 0) + 1
                h["last_error"] = msg[:300]
                _log(f"poll {name}: {msg}", now)
        if lines:
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "items.jsonl", "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        _atomic(d / "seen.json", seen)
        save(st)
    return n_new, len(sources), failed


# ---- CLI ---------------------------------------------------------------------------------------

def _off():
    return (scout_dir() / "off").exists() or os.environ.get("TC_SCOUT") == "0"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("poll")
    sp = sub.add_parser("source").add_subparsers(dest="sub", required=True)
    a = sp.add_parser("add")
    a.add_argument("name")
    a.add_argument("--kind", required=True)
    a.add_argument("--url", required=True)
    a.add_argument("--why", default="")
    sp.add_parser("list")
    for c in ("remove", "test"):
        sp.add_parser(c).add_argument("name")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    try:
        if args.cmd == "poll":
            if _off():
                print("scout: off")
                return 0
            n, m, f = poll()
            print(f"poll: {n} new from {m} sources, {f} failed")
        elif args.sub == "add":
            row = add_source(args.name, args.kind, args.url, args.why)
            print(f"added {row['name']} ({row['kind']})")
        elif args.sub == "list":
            st = load()
            for s in st["sources"]:
                print("\t".join([s["name"], s["kind"], s["url"], str((st["health"].get(s["name"]) or {}).get("failures", 0))]))
        elif args.sub == "remove":
            remove_source(args.name)
            print(f"removed {args.name}")
        else:
            for it in test_source(args.name):
                print(f"{it['title']}\t{it['url']}")
    except Refusal as e:
        print(f"scout: {e}", file=sys.stderr)
        return 2
    except scout_fetch.FetchError as e:
        print(f"scout: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
