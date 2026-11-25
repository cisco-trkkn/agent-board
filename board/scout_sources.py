"""scout_sources: the trend scout's sources.json, the `source` CLI, the daily poll (no model) and #scout source requests.

State lives in scout_dir() (TC_SCOUT_DIR, else ~/.local/state/agent-board/scout): sources.json (sources + health),
seen.json (keys, per-source first poll time and fetcher state, pending source requests, answered request messages),
items.jsonl, poll.log. poll() fetches each source through scout_fetch, writes unseen items and tracks failures (three in
a row show in health_report()).

Source requests (`source: <url> [name]` in #scout, /source on the agent-board bot) arrive as bridge events through
discord_controls: discord_request() answers at once with a prompt and records it as pending, discord_confirm() adds the
source through add_url() on an allowFrom user's check mark, fetches it once and edits the prompt. The poll is the
fallback for a request or a check mark the bridge missed. The pending prompts are mirrored to
<discord dir>/scout-prompts.json, which the bridge reads to forward a check mark from any channel.
Test: tests/test_scout_sources.py."""
import argparse
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.parse
from html.parser import HTMLParser
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
PROMPTS_FILE = "scout-prompts.json"   # in the agent-board discord dir: {pending prompt message id: channel id}
TITLES_SHOWN = 3
LOCK_WAIT = 2.0   # seconds a bridge event waits for the sources lock, which the daily poll holds for its whole run
_HTTP_OK_HOSTS = ()  # test seam: hosts whose requested URL may be http


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


class Busy(Exception):
    """The sources lock is held (the daily poll is running): the bridge event is tried again on a later board tick."""


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
def _lock(wait=None):
    """The sources lock. wait=None blocks; wait=<seconds> gives up with Busy, so the board tick never waits out a poll."""
    d = scout_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "sources.lock", "a") as f:
        if wait is None:
            fcntl.flock(f, fcntl.LOCK_EX)
        else:
            end = time.monotonic() + wait
            while True:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= end:
                        raise Busy("sources lock is held") from None
                    time.sleep(0.05)
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


def _resolve(host):
    """Every address host resolves to, as strings (test seam: tests replace it with a fake resolver)."""
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})


def _addr_class(ip):
    """None for a global address, else the class that refuses it. An IPv4-mapped IPv6 address is judged as its IPv4."""
    a = ipaddress.ip_address(ip.split("%", 1)[0])
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    for cls, flag in (("unspecified", a.is_unspecified), ("loopback", a.is_loopback), ("link-local", a.is_link_local),
                      ("multicast", a.is_multicast), ("private", a.is_private), ("reserved", a.is_reserved)):
        if flag:
            return cls
    return None if a.is_global else "non-global"


def check_url_safe(url):
    """The one URL rule for every source add, #scout request and fetch hop: https (http only for _HTTP_OK_HOSTS, a test
    seam that is empty in production and also skips the address test), and every address the host resolves to (or the
    literal IP) is global. Refusal("<one line>") otherwise."""
    u = urllib.parse.urlsplit(url or "")
    host = u.hostname
    if host and host in _HTTP_OK_HOSTS and u.scheme in ("http", "https"):
        return
    if u.scheme != "https" or not host:
        raise Refusal("url must start with https://")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        ips = [host]
    except ValueError:
        try:
            ips = _resolve(host)
        except (OSError, UnicodeError):
            raise Refusal(f"host does not resolve: {host}") from None
    if not ips:
        raise Refusal(f"host does not resolve: {host}")
    for ip in ips:
        cls = _addr_class(ip)
        if cls:
            raise Refusal(f"{cls} address {ip}")


def _check_request_url(url):
    """Kept for callers of the old name: the same rule as check_url_safe."""
    check_url_safe(url)


GH_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/releases)?/?$")
NPM_RE = re.compile(r"^https://www\.npmjs\.com/package/((?:@[A-Za-z0-9._~-]+/)?[A-Za-z0-9._~-]+)/?$")
FEED_TYPES = ("application/rss+xml", "application/atom+xml")
DETECT_TIMEOUT = 10


class _AltFeed(HTMLParser):
    """The first <link rel="alternate" type="application/rss+xml|application/atom+xml" href=…>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "link" and self.href is None and "alternate" in a.get("rel", "").lower().split() \
                and a.get("type", "").lower().strip() in FEED_TYPES and a.get("href", "").strip():
            self.href = a["href"].strip()


def _taken():
    seen = _read(scout_dir() / "seen.json", {})
    reqs = seen.get("requests") if isinstance(seen.get("requests"), dict) else {}
    return {s["name"] for s in load(create=False)["sources"]} | {r.get("name") for r in reqs.values() if isinstance(r, dict)}


def detect(url, taken=None):
    """url -> {kind, url, name, prefix?}; first match wins (spec 2026-11-23-hardening §b2). At most one page is fetched
    (through check_url_safe, DETECT_TIMEOUT s); a failed fetch falls back to html_links. Refusal for a refused URL."""
    check_url_safe(url)
    name = request_name(url, _taken() if taken is None else set(taken))
    m = GH_RE.match(url)
    if m:
        return {"kind": "github_releases", "url": f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/releases", "name": name}
    m = NPM_RE.match(url)
    if m:
        return {"kind": "npm", "url": f"https://registry.npmjs.org/{m.group(1)}", "name": name}
    if urllib.parse.urlsplit(url).path.endswith("CHANGELOG.md"):
        return {"kind": "changelog_md", "url": url, "name": name}
    try:
        _, body, ctype = scout_fetch.get(url, timeout=DETECT_TIMEOUT)
    except scout_fetch.Refused as e:
        raise Refusal(str(e).split(": ", 1)[-1]) from None
    except scout_fetch.FetchError:
        body, ctype = b"", ""
    p = _AltFeed()
    try:
        p.feed(body.decode("utf-8", "replace"))
        p.close()
    except Exception:  # noqa: BLE001  (odd markup: no feed link)
        p.href = None
    if p.href:
        feed = urllib.parse.urljoin(url, p.href)
        check_url_safe(feed)
        return {"kind": "rss", "url": feed, "name": name}
    head = body[:200].lstrip().lower()
    if "xml" in (ctype or "").lower() or head.startswith((b"<?xml", b"<rss", b"<feed")):
        return {"kind": "rss", "url": url, "name": name}
    return {"kind": "html_links", "url": url, "name": name, "prefix": urllib.parse.urlsplit(url).path.rstrip("/") + "/"}


def add_url(url, name=None, kind=None, why="", now=None, st=None):
    """The one add path (the CLI, a #scout request, /source): detect() picks kind, url and name unless kind is given.
    st: see add_source."""
    if kind is None:
        d = detect(url)
        kind, url, name = d["kind"], d["url"], name or d["name"]
    elif not name:
        name = request_name(url, _taken())
    return add_source(name, kind, url, why, now=now, st=st)


def add_source(name, kind, url, why="", prefix=None, now=None, st=None):
    """Check and append one source row. With st (the loaded sources.json) the caller already holds the sources lock and
    saves st itself; without it the row is added under the lock here."""
    if kind not in scout_fetch.KINDS:
        raise Refusal(f"unknown kind {kind!r} (one of {', '.join(sorted(scout_fetch.KINDS))})")
    if not NAME_RE.match(name or ""):
        raise Refusal(f"bad name {name!r} (must match {NAME_RE.pattern})")
    if kind in ("discord_channel", "plugin"):
        _check_url(kind, url)
    else:
        check_url_safe(url)   # the one URL rule: https and a host, as _check_url asks, plus the address test

    def put(st):
        if any(s["name"] == name for s in st["sources"]):
            raise Refusal(f"duplicate name {name!r}")
        row = {"name": name, "kind": kind, "url": url, "why": why or "", "added": _iso(now or time.time()), "builtin": False}
        if kind == "html_links":
            row["prefix"] = prefix or urllib.parse.urlsplit(url).path.rstrip("/") + "/"
        st["sources"].append(row)
        return row

    if st is not None:
        return put(st)
    with _lock():
        st = load()
        row = put(st)
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


def request_tail(text):
    """The text after a request's URL: the source name when it is one NAME_RE token, else the why -> (name or None, why)."""
    t = " ".join(str(text or "").split())
    return (t, "") if NAME_RE.match(t) else (None, t)


def _free_name(name, taken):
    """name, or name-2, name-3… when taken (the base is cut so the suffix still fits NAME_RE)."""
    out, n = name, 1
    while out in taken:
        n += 1
        out = f"{name[:40 - len(str(n)) - 1]}-{n}"
    return out


def _load_seen():
    seen = _read(scout_dir() / "seen.json", {})
    for k in ("keys", "sources", "state", "requests", "request_msgs"):
        if not isinstance(seen.get(k), dict):
            seen[k] = {}
    return seen


def _write_prompts(seen):
    """Mirror the pending prompts for the bridge. Written only when it changes; a missing file means none."""
    p = tc_env.discord_dir(PROJECT) / PROMPTS_FILE
    want = {str(rid): str(r.get("channel") or "") for rid, r in seen["requests"].items() if isinstance(r, dict)}
    if _read(p, {}) != want:
        _atomic(p, want)


def is_pending(rid):
    """True when rid is the message id of a pending source prompt."""
    reqs = _read(scout_dir() / "seen.json", {}).get("requests")
    return isinstance(reqs, dict) and str(rid) in reqs


def _scout_channels():
    """The channel ids of the discord_channel sources (#scout)."""
    return {str(s.get("url") or "").strip() for s in load(create=False)["sources"] if s.get("kind") == "discord_channel"} - {""}


def _fence(text):
    """Text for a ``` block: a run of three or more backticks is broken up with zero-width spaces (as commands.js fence)."""
    return re.sub(r"`{3,}", lambda m: "\u200b".join(m.group(0)), str(text))


def _say(lines, tail=""):
    """One Discord message: the data lines in a code block (one line each, never markup), then the fixed tail line.
    At most scout_fetch.DISCORD_MAX characters; a cut never loses the closing fence or the tail."""
    end = "\n```" + (f"\n{tail}" if tail else "")
    body = _fence("\n".join(" ".join(str(l).split()) for l in lines))
    room = scout_fetch.DISCORD_MAX - len("```\n") - len(end)
    if len(body) > room:
        body = body[:room - 1] + "…"
    return "```\n" + body + end


def _confirm_locked(seen, st, rid, now):
    """A check mark on the pending request rid: take the request out of seen and add its source to st through add_url.
    The caller holds the sources lock and saves both, so the source is added once whichever path (the bridge event or
    the poll) sees the check mark first. -> (row, None), or (None, reason) when the add is refused."""
    r = seen["requests"].pop(rid)
    try:
        name = _free_name(r["name"], {s["name"] for s in st["sources"]})
        return add_url(r["url"], name, r["kind"], r.get("why", ""), now=now, st=st), None
    except Refusal as e:
        return None, str(e)
    except (KeyError, TypeError):
        return None, "bad request record"


def _reply_failed(what, e, now):
    _log(f"scout source: {what} failed: {type(e).__name__}: {e}", now)


def discord_request(ev, now=None):
    """A `source: <url> [name]` message in #scout (via "message") or a /source command (via "slash"), as the bridge event
    of an allowFrom user -> the audit result. detect() runs here and the answer goes out at once: the prompt
    `<name> · <kind> · <url>` / `react ✅ to add`, recorded as pending under the prompt's message id, or `refused: <reason>`
    with nothing recorded. A #scout message is answered with a REST reply; a /source reply is edited through the bridge
    (an ireply outbox op), so nothing is posted by REST outside #scout. Busy when the daily poll holds the sources lock:
    nothing has been done yet and the event can be handled again."""
    now = time.time() if now is None else now
    slash = ev.get("via") == "slash"
    chan, mid, iid = str(ev.get("channel_id") or ""), str(ev.get("message_id") or ""), str(ev.get("iid") or "")
    if slash:
        url, name, why = str(ev.get("url") or "").strip(), str(ev.get("name") or "").strip() or None, ""
    else:
        req = scout_fetch.parse_request(ev.get("text"))
        if not req or chan not in _scout_channels():
            return "ignored"
        url = req[0]
        name, why = request_tail(req[1])
    if not url or not mid.isdigit() or not chan.isdigit() or (slash and not iid):
        return "ignored"
    with _lock(LOCK_WAIT):   # mark the message as answered first, so the poll does not answer it too
        seen = _load_seen()
        if mid in seen["request_msgs"] or mid in seen["requests"] or any(r.get("message_id") == mid for r in seen["requests"].values()):
            return "duplicate"
        seen["request_msgs"][mid] = _iso(now)
        _atomic(scout_dir() / "seen.json", seen)

    def answer(text):
        if slash:
            discord_feed.outbox_write(tc_env.discord_dir(PROJECT), {"op": "ireply", "iid": iid, "content": text})
            return mid   # the interaction's own reply is the prompt
        return scout_fetch.post_message(chan, text, reply_to=mid)

    def forget():   # not answered: the poll may still pick the message up
        with _lock():
            seen = _load_seen()
            seen["request_msgs"].pop(mid, None)
            seen["requests"].pop(mid, None)
            _atomic(scout_dir() / "seen.json", seen)
            _write_prompts(seen)

    try:
        if name is not None and not NAME_RE.match(name):
            raise Refusal(f"bad name {name!r} (must match {NAME_RE.pattern})")
        d = detect(url)
    except Refusal as e:
        _log(f"scout source: request {url} refused: {e}", now)
        try:
            answer(_say([f"refused: {e}"]))
        except Exception as e2:  # noqa: BLE001
            _reply_failed(f"reply to {mid}", e2, now)
        return "refused"
    except Exception as e:  # noqa: BLE001  (detect falls back on a failed fetch; anything else is a bug, not an answer)
        _reply_failed(f"request {url}", e, now)
        forget()
        return "error"
    name = _free_name(name, _taken()) if name else d["name"]
    rec = {"url": d["url"], "why": why, "name": name, "kind": d["kind"], "channel": chan, "message_id": mid,
           "created": _iso(now), "via": "slash" if slash else "message"}
    if slash:
        rec["iid"] = iid

    def record(rid):
        with _lock():
            seen = _load_seen()
            seen["requests"][rid] = rec
            _atomic(scout_dir() / "seen.json", seen)
            _write_prompts(seen)

    text = _say([f"{name} · {d['kind']} · {d['url']}"], f"react {CHECK} to add")
    if slash:
        record(mid)   # before the prompt shows: a check mark can come at once
    try:
        rid = answer(text)
    except Exception as e:  # noqa: BLE001
        _reply_failed(f"reply to {mid}", e, now)
        forget()
        return "reply failed"
    if not slash:
        if not rid:
            forget()
            return "reply failed"
        record(rid)
    return "prompted"


def discord_confirm(rid, user, now=None):
    """A check mark by an allowFrom user on the pending prompt rid (bridge event) -> (source name, audit result), or None
    when rid is not pending (a second check mark, a refusal reply, a prompt the poll already took). The source is added
    at once through add_url, fetched once (nothing of that fetch is stored: the next poll treats the source as new), and
    the prompt is edited to `added: <name> (<kind>)` plus the first TITLES_SHOWN titles, or to
    `added, first fetch failed: <reason>` (the source stays, its health is the poll's business). A prompt in #scout is
    edited by REST; a /source reply is edited by the bridge (an `edit` op keyed scout-src:<message id>, which works in
    any channel and after the interaction has expired). Busy when the daily poll holds the sources lock: nothing changed."""
    now = time.time() if now is None else now
    rid = str(rid)
    with _lock(LOCK_WAIT):
        seen = _load_seen()
        r = seen["requests"].get(rid)
        if not isinstance(r, dict):
            return None
        st = load()
        row, why_not = _confirm_locked(seen, st, rid, now)
        _atomic(scout_dir() / "seen.json", seen)   # the pending record goes first (as in poll): a crash here loses the request, never adds it twice
        _write_prompts(seen)
        if row is not None:
            save(st)
    if row is None:
        _log(f"scout source: request {r.get('url')} refused: {why_not}", now)
        text, result = _say([f"refused: {why_not}"]), (str(r.get("name") or rid), "refused")
    else:
        try:
            items, _ = scout_fetch.fetch(row, {})
            titles = [str(i.get("title") or i.get("url") or "")[:300] for i in items if "request" not in i][:TITLES_SHOWN]
            text = _say([f"added: {row['name']} ({row['kind']})"] + titles)
        except Exception as e:  # noqa: BLE001  (fetch raises FetchError only; anything else is still a failed first fetch)
            reason = str(e) if isinstance(e, scout_fetch.FetchError) else f"{type(e).__name__}: {e}"
            text = _say([f"added, first fetch failed: {reason[:300]}"])
        result = (row["name"], "added")
    try:
        if r.get("via") == "slash":
            discord_feed.outbox_write(tc_env.discord_dir(PROJECT), {"op": "edit", "key": f"scout-src:{rid}", "text": text})
        else:   # a REST reply in #scout: REST edits stay inside #scout
            scout_fetch.edit_message(str(r.get("channel") or ""), rid, text)
    except Exception as e:  # noqa: BLE001
        _reply_failed(f"edit {rid}", e, now)
    return result


def _handle_requests(chan, reqs, seen, st, now):
    """New #scout requests the bridge did not hand over (it was down) -> a reply and a pending record. Only allowFrom user ids count."""
    allow = _allow()
    pending = {r.get("message_id") for r in seen["requests"].values()} | set(seen["request_msgs"])
    retry = False
    for r in reqs:
        if r["author_id"] not in allow or r["message_id"] in pending:
            continue
        url = r["url"]
        try:
            _check_request_url(url)
        except Refusal as e:
            _log(f"poll scout: request {url} refused: {e}", now)
            continue
        try:
            kind = _guess_kind(url)
        except Exception as e:  # noqa: BLE001  (a dead URL is dropped, not retried)
            _log(f"poll scout: request {url}: {type(e).__name__}: {e}", now)
            continue
        taken = {s["name"] for s in st["sources"]} | {x["name"] for x in seen["requests"].values()}
        name, why = request_tail(r["why"])
        name = _free_name(name, taken) if name else request_name(url, taken)
        try:
            reply = scout_fetch.post_message(chan, f"source request: {name} ({kind}) — react {CHECK} to add",
                                             reply_to=r["message_id"])
        except Exception as e:  # noqa: BLE001
            _log(f"poll scout: request {url}: reply failed, will retry: {type(e).__name__}: {e}", now)
            retry = True
            continue
        if reply:
            seen["requests"][reply] = {"url": url, "why": why, "name": name, "kind": kind, "channel": chan,
                                       "message_id": r["message_id"], "created": _iso(now)}
            seen["request_msgs"][r["message_id"]] = _iso(now)
    return retry


def _check_requests(seen, st, now):
    """Pending requests: add the source when an allowFrom user reacted (a check mark the bridge did not hand over), drop after REQUEST_DAYS."""
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
        row, why_not = _confirm_locked(seen, st, rid, now)
        if row is None:
            _log(f"poll scout: request {r.get('url')} refused: {why_not}", now)
            continue
        discord_feed.audit_append(tc_env.discord_dir(PROJECT), who, "scout-source", row["name"], "added")


def poll(now=None):
    """Run one poll -> (new items, sources polled, failed). Not model-backed."""
    now = time.time() if now is None else now
    d = scout_dir()
    with _lock():
        st = load()
        seen = _load_seen()
        cutoff = _iso(now - KEY_DAYS * 86400)
        seen["keys"] = {k: v for k, v in seen["keys"].items() if v >= cutoff}
        msg_cutoff = _iso(now - REQUEST_DAYS * 86400)
        seen["request_msgs"] = {k: v for k, v in seen["request_msgs"].items() if isinstance(v, str) and v >= msg_cutoff}
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
                for it in items:  # every key the source still lists is refreshed, so only vanished keys age out
                    seen["keys"][it["key"]] = _iso(now)
                for it in write:
                    lines.append(json.dumps({"key": it["key"], "source": name, "kind": src["kind"], "title": it["title"],
                                             "url": it["url"], "published": it.get("published"), "fetched_at": _iso(now),
                                             "excerpt": it.get("excerpt") or ""}, ensure_ascii=False))
                retry = False
                if src["kind"] == "discord_channel" and reqs:
                    retry = _handle_requests(scout_fetch._channel(src["url"]), reqs, seen, st, now)
                if new_state is not None and not retry:  # a failed reply keeps the old cursor: the request is seen again
                    seen["state"][name] = new_state
                seen["sources"].setdefault(name, _iso(now))
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
        _write_prompts(seen)
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
    a.add_argument("--kind")
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
            row = add_url(args.url, args.name, args.kind, args.why)
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
