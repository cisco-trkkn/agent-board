"""scout_fetch: one fetcher per web source kind for the trend scout.

fetch(source, state, installed_version=None) -> (items, new_state). Every item is
{title, url, version, published, excerpt, content_hash}; the poll adds key, source,
kind and fetched_at. Fetchers return every item, newest first; the first-poll rule
(keep only the newest 3) is the poll's job. Any failure raises FetchError.
Stdlib only: urllib, xml.etree, html.parser (never regex on HTML).
"""
import hashlib
import html
import json
import re
import os
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

import tc_env

UA = "agent-board-scout"
TIMEOUT = 20
MAX_BYTES = 4 * 1024 * 1024
EXCERPT_MAX = 4096
ATOM = "{http://www.w3.org/2005/Atom}"
GH_HOSTS = {"api.github.com", "127.0.0.1", "localhost"}  # hosts that may receive the gh token


class FetchError(Exception):
    pass


FALLBACK_CA = "/etc/ssl/cert.pem"


def _ssl_context():
    """The default verifying context. A Python with no CA bundle of its own (python.org builds before "Install Certificates")
    falls back to the system bundle, unless SSL_CERT_FILE names one. Verification is never turned off."""
    ctx = ssl.create_default_context()
    vp = ssl.get_default_verify_paths()
    have = any(p and os.path.exists(p) for p in (vp.cafile, vp.capath, vp.openssl_cafile, vp.openssl_capath))
    if not have and not os.environ.get("SSL_CERT_FILE") and os.path.isfile(FALLBACK_CA):
        ctx.load_verify_locations(FALLBACK_CA)
    return ctx


# no HTTPCookieProcessor: no cookies are stored or replayed
_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()))


def _open(req):
    """Open a Request -> (status, body (at most MAX_BYTES), content type). FetchError text never carries request headers."""
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            return r.status, r.read(MAX_BYTES), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        e.close()
        raise FetchError(f"HTTP {e.code} for {req.full_url}") from None
    except Exception as e:  # URLError, timeout, ssl, bad url, connection reset
        raise FetchError(f"{type(e).__name__}: {e}") from None


def get(url, accept=None, headers=None):
    """GET url -> (status, body bytes (at most MAX_BYTES), content type). FetchError on a network error or status >= 400."""
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    h.update(headers or {})
    return _open(urllib.request.Request(url, headers=h))


def _cut(text, limit=EXCERPT_MAX):
    """Cut to at most limit UTF-8 bytes on a character boundary."""
    b = text.encode("utf-8")
    return text if len(b) <= limit else b[:limit].decode("utf-8", "ignore")


def _item(title, url, version=None, published=None, excerpt="", content_hash=None):
    return {"title": title, "url": url, "version": version, "published": published,
            "excerpt": _cut(excerpt), "content_hash": content_hash}


def _body(url, accept=None, headers=None):
    _, body, _ = get(url, accept, headers)
    if not body.strip():
        raise FetchError("empty body")
    return body


def _text(body):
    return body.decode("utf-8", "replace")


class _Text(HTMLParser):
    """Visible text of a fragment: tags dropped, script and style skipped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def strip_tags(s):
    p = _Text()
    p.feed(s or "")
    p.close()
    return " ".join(" ".join(p.parts).split())


def _iso_date(s):
    """RFC 822 (RSS) or ISO 8601 (Atom) -> UTC 'YYYY-MM-DDTHH:MM:SSZ'; None when empty or unparseable."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        if re.match(r"\d{4}-\d\d-\d\d", s):
            d = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
        else:
            d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, IndexError):
        return None


def _newest_first(items):
    # stable: ties keep feed order; unparseable dates (None) sort last
    return sorted(items, key=lambda i: (i["published"] is not None, i["published"] or ""), reverse=True)


# ---- changelog_md -------------------------------------------------------------------------

_VERSION = re.compile(r"\d+\.\d+\.\d+")


def parse_installed_version(output):
    """First \\d+.\\d+.\\d+ token of `claude --version` output, else None."""
    for tok in (output or "").split():
        if _VERSION.fullmatch(tok):
            return tok
    return None


def _changelog_md(source, state, installed_version):
    text = _text(_body(source["url"]))
    sections, cur = [], None
    for line in text.splitlines():
        m = re.match(r"##\s+(\S+)\s*$", line)
        if m:
            cur = [m.group(1), []]
            sections.append(cur)
        elif cur is not None:
            cur[1].append(line)
    if not sections:
        raise FetchError("no '## <version>' sections")
    items = []
    for version, lines in sections:
        body = "\n".join(lines).strip()
        if installed_version:
            first, _, rest = body.partition("\n")
            body = f"{first} (installed {installed_version})" + ("\n" + rest if rest else "")
        items.append(_item(f"Claude Code {version}", source["url"], version=version, excerpt=body))
    return items, {}


# ---- github_releases ----------------------------------------------------------------------

def _gh_token_impl():
    """`gh auth token`, only when `gh auth status` exits 0; None otherwise. Never logged."""
    try:
        if subprocess.run(["gh", "auth", "status"], capture_output=True, timeout=15).returncode != 0:
            return None
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    tok = r.stdout.strip()
    return tok if r.returncode == 0 and tok else None


def _gh_token():
    return _gh_token_impl()


def _github_releases(source, state, installed_version):
    host = urllib.parse.urlsplit(source["url"]).hostname
    headers = {}
    if host in GH_HOSTS:
        tok = _gh_token()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
    data = json.loads(_text(_body(source["url"], "application/vnd.github+json", headers)))
    if not isinstance(data, list):
        raise FetchError("releases response is not a list")
    items = []
    for r in data:
        tag = r["tag_name"]
        items.append(_item(r.get("name") or tag, r["html_url"], version=tag, published=r.get("published_at"),
                           excerpt=r.get("body") or ""))
    return _newest_first(items), {}


# ---- rss / atom ---------------------------------------------------------------------------

def _rss(source, state, installed_version):
    root = ET.fromstring(_body(source["url"]))
    items = []
    if root.tag == "rss" or root.find("channel") is not None:
        for it in root.iter("item"):
            desc = it.findtext("description") or it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
            items.append(_item((it.findtext("title") or "").strip(), (it.findtext("link") or "").strip(),
                               published=_iso_date(it.findtext("pubDate")), excerpt=strip_tags(desc)))
    elif root.tag == ATOM + "feed":
        for e in root.iter(ATOM + "entry"):
            link = ""
            for l in e.findall(ATOM + "link"):
                if l.get("rel", "alternate") == "alternate" and l.get("href"):
                    link = l.get("href")
                    break
            summ = e.findtext(ATOM + "summary") or e.findtext(ATOM + "content") or ""
            items.append(_item((e.findtext(ATOM + "title") or "").strip(), link,
                               published=_iso_date(e.findtext(ATOM + "published") or e.findtext(ATOM + "updated")),
                               excerpt=strip_tags(summ)))
    else:
        raise FetchError("not an RSS or Atom feed")
    return _newest_first(items), {}


# ---- html_links ---------------------------------------------------------------------------

class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []     # [href, text parts]
        self._cur = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._cur = [dict(attrs).get("href") or "", []]
            self.links.append(self._cur)

    def handle_endtag(self, tag):
        if tag == "a":
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur[1].append(data)


def _html_links(source, state, installed_version):
    base = source["url"]
    prefix = source.get("prefix") or "/"
    host = urllib.parse.urlsplit(base).netloc
    p = _Links()
    p.feed(_text(_body(base)))
    p.close()
    found = {}  # url -> title (document order)
    for href, parts in p.links:
        if not href:
            continue
        u = urllib.parse.urlsplit(urllib.parse.urljoin(base, href))
        if u.netloc != host or u.scheme not in ("http", "https"):
            continue
        if not u.path.startswith(prefix) or len(u.path) <= len(prefix):
            continue
        url = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))
        title = " ".join(" ".join(parts).split())
        if url not in found or (not found[url] and title):
            found[url] = title
    items = [_item(t or u.rstrip("/").rsplit("/", 1)[-1], u) for u, t in found.items()]
    return items, {}


# ---- html_diff ----------------------------------------------------------------------------

_CHROME = {"nav", "header", "footer"}
_CODE = {"script", "style"}


class _Page(HTMLParser):
    """Collects the text of <main> (as is) and of <body> minus nav/header/footer. script/style are never text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main, self.body = [], []
        self.has_main = False
        self._chrome = self._code = self._main = self._in_body = 0

    def handle_starttag(self, tag, attrs):
        if tag in _CHROME:
            self._chrome += 1
        elif tag in _CODE:
            self._code += 1
        elif tag == "main":
            self.has_main = True
            self._main += 1
        elif tag == "body":
            self._in_body += 1

    def handle_endtag(self, tag):
        if tag in _CHROME:
            self._chrome = max(0, self._chrome - 1)
        elif tag in _CODE:
            self._code = max(0, self._code - 1)
        elif tag == "main":
            self._main = max(0, self._main - 1)
        elif tag == "body":
            self._in_body = max(0, self._in_body - 1)

    def handle_data(self, data):
        if self._code:
            return
        if self._main:
            self.main.append(data)
        if not self._chrome and (self._in_body or not self.has_main):
            self.body.append(data)


def _page_text(markup):
    """The collapsed text of <main>, else of <body> minus nav/header/footer."""
    p = _Page()
    p.feed(markup)
    p.close()
    return " ".join(" ".join(p.main if p.has_main else p.body).split())


def _html_diff(source, state, installed_version):
    text = _page_text(_text(_body(source["url"])))
    if not text:
        raise FetchError("no page text")
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    new_state = {"hash": h}
    old = (state or {}).get("hash")
    if old is None or old == h:
        return [], new_state
    return [_item(f"Page changed: {source.get('name') or source['url']}", source["url"], excerpt=text,
                  content_hash=h)], new_state


# ---- npm ----------------------------------------------------------------------------------

def _npm(source, state, installed_version):
    """source url = <registry>/<pkg> (e.g. https://registry.npmjs.org/@anthropic-ai/claude-code);
    reads the small <registry>/-/package/<pkg>/dist-tags document, not the full packument."""
    u = urllib.parse.urlsplit(source["url"])
    pkg = u.path.strip("/")
    if not pkg:
        raise FetchError("npm source url has no package")
    tags_url = urllib.parse.urlunsplit((u.scheme, u.netloc, f"/-/package/{pkg}/dist-tags", "", ""))
    latest = json.loads(_text(_body(tags_url, "application/json")))["latest"]
    if not isinstance(latest, str) or not latest:
        raise FetchError("bad dist-tags latest")
    new_state = {"latest": latest}
    if latest == (state or {}).get("latest"):
        return [], new_state
    return [_item(f"{pkg} {latest}", "https://www.npmjs.com/package/" + pkg, version=latest)], new_state


# ---- plugin -------------------------------------------------------------------------------

_VER = re.compile(r"\d+(\.\d+)+(-[0-9A-Za-z.]+)?$")


def version_key(v):
    """Sort key for 'N.N.N' with an optional '-suffix' (a suffix sorts before the plain release); None when v is not such a version."""
    if not isinstance(v, str) or not _VER.match(v):
        return None
    core, _, suffix = v.partition("-")
    nums = [int(x) for x in core.split(".")]
    while len(nums) > 1 and nums[-1] == 0:
        nums.pop()
    return (tuple(nums), 0 if suffix else 1)


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FetchError(f"{Path(path).name}: {type(e).__name__}") from None


def _plugin(source, state, installed_version):
    """Installed plugins with a newer version in their marketplace's remote marketplace.json.
    new_state = {"skipped_no_version": n}: plugins that could not be compared."""
    pdir = Path(os.environ.get("HOME", "")) / ".claude" / "plugins"
    installed = _load_json(pdir / "installed_plugins.json").get("plugins") or {}
    kp = pdir / "known_marketplaces.json"
    known = _load_json(kp) if kp.exists() else {}
    base = (os.environ.get("TC_SCOUT_RAW_BASE") or "https://raw.githubusercontent.com").rstrip("/")
    remotes, errors, items, skipped = {}, 0, [], 0   # remotes: marketplace -> {plugin name: entry} | None (failed)
    for key, entries in installed.items():
        name, _, market = key.rpartition("@")
        cur = (entries or [{}])[0].get("version")
        src = (known.get(market) or {}).get("source") or {}
        if not name or src.get("source") != "github" or not src.get("repo") or version_key(cur) is None:
            skipped += 1
            continue
        if market not in remotes:
            try:
                data = json.loads(_text(_body(f"{base}/{src['repo']}/main/.claude-plugin/marketplace.json")))
                remotes[market] = {p["name"]: p for p in data["plugins"]}
            except (FetchError, ValueError, KeyError, TypeError):
                remotes[market] = None
                errors += 1
        if remotes[market] is None:
            continue
        entry = remotes[market].get(name) or {}
        new = entry.get("version")
        if version_key(new) is None:
            skipped += 1
            continue
        if version_key(new) > version_key(cur):
            items.append(_item(f"{name} {cur} \u2192 {new}", f"https://github.com/{src['repo']}", version=new,
                               excerpt=entry.get("description") or ""))
    if errors and not any(v is not None for v in remotes.values()):
        raise FetchError("every marketplace fetch failed")
    return items, {"skipped_no_version": skipped}


# ---- discord_channel ----------------------------------------------------------------------

_SOURCE_REQ = re.compile(r"^source:\s+(\S+)\s+(.+)$")
_URL = re.compile(r"https?://[^\s<>]+")


def _discord_token():
    try:
        text = (tc_env.discord_dir("agent-board") / ".env").read_text(encoding="utf-8")
    except OSError:
        raise FetchError("no token") from None
    for line in text.splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "DISCORD_BOT_TOKEN" and v.strip().strip("'\""):
            return v.strip().strip("'\"")
    raise FetchError("no token")


def _discord_api():
    return (os.environ.get("TC_SCOUT_DISCORD_API") or "https://discord.com/api/v10").rstrip("/")


def _discord(method, path, body=None):
    """One authenticated Discord REST call -> parsed JSON. The token only ever sits in the request header."""
    headers = {"User-Agent": UA, "Authorization": "Bot " + _discord_token(), "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    _, raw, _ = _open(urllib.request.Request(_discord_api() + path, data=data, headers=headers, method=method))
    try:
        return json.loads(raw.decode("utf-8")) if raw.strip() else None
    except ValueError:
        raise FetchError("discord: invalid JSON") from None


def _channel(channel_id):
    cid = str(channel_id or "").strip()
    if not cid.isdigit():
        raise FetchError("no channel")
    return cid


def post_message(channel_id, text, reply_to=None):
    """Post text to a channel (no mentions allowed); returns the new message id."""
    body = {"content": text, "allowed_mentions": {"parse": []}}
    if reply_to:
        body["message_reference"] = {"message_id": str(reply_to)}
    r = _discord("POST", f"/channels/{_channel(channel_id)}/messages", body)
    return str((r or {}).get("id") or "")


def reactions(channel_id, message_id, emoji):
    """User ids that reacted to a message with emoji."""
    r = _discord("GET", f"/channels/{_channel(channel_id)}/messages/{message_id}/reactions/"
                 f"{urllib.parse.quote(emoji, safe='')}?limit=100")
    return [str(u["id"]) for u in r or []]


class _Title(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._in = [], False

    def handle_starttag(self, tag, attrs):
        self._in = self._in or tag == "title"

    def handle_endtag(self, tag):
        if tag == "title":
            self._in = False

    def handle_data(self, data):
        if self._in:
            self.parts.append(data)


def _page_item(url, published):
    """A page item for a URL posted in the channel; None when the page cannot be read (that URL is skipped)."""
    try:
        _, body, ctype = get(url)
    except FetchError:
        return None
    if ctype and "html" not in ctype.lower() and "text" not in ctype.lower():
        return None
    markup = _text(body)
    t = _Title()
    t.feed(markup)
    t.close()
    text = _page_text(markup)
    title = " ".join(" ".join(t.parts).split()) or url
    return _item(title, url, published=published, excerpt=text,
                 content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest())


def _discord_channel(source, state, installed_version):
    cid = _channel(source.get("url"))
    _discord_token()  # "no token" before any request
    after = (state or {}).get("after")
    msgs = _discord("GET", f"/channels/{cid}/messages?limit=50" + (f"&after={after}" if after else ""))
    if not isinstance(msgs, list):
        raise FetchError("discord: messages response is not a list")
    msgs.sort(key=lambda m: int(m["id"]), reverse=True)
    import scout_sources  # lazy: scout_sources imports this module
    allow = scout_sources._allow()
    items, seen_urls = [], set()
    for m in msgs:
        author = m.get("author") or {}
        if author.get("bot"):
            continue  # the poll's own replies carry URLs; they are not input
        content = (m.get("content") or "").strip()
        req = _SOURCE_REQ.match(content)
        if req:
            items.append({"request": {"url": req.group(1), "why": req.group(2).strip(), "message_id": str(m["id"]),
                                      "author": author.get("username") or "", "author_id": str(author.get("id") or "")}})
            continue
        if str(author.get("id") or "") not in allow:
            continue  # only an allowFrom user's links are fetched, the rule `source:` requests already follow
        for url in _URL.findall(content):
            url = url.rstrip(".,;:!?)")
            if url in seen_urls:
                continue
            try:
                scout_sources._check_request_url(url)
                if urllib.parse.urlsplit(url).hostname in ("localhost", "127.0.0.1", "::1") \
                        and urllib.parse.urlsplit(url).hostname not in scout_sources._HTTP_OK_HOSTS:
                    raise scout_sources.Refusal("loopback")
            except scout_sources.Refusal:
                continue
            seen_urls.add(url)
            it = _page_item(url, _iso_date(m.get("timestamp")))
            if it:
                items.append(it)
    newest = str(max((int(m["id"]) for m in msgs), default=after or ""))
    return items, ({"after": newest} if newest else {})


KINDS = {"changelog_md": _changelog_md, "github_releases": _github_releases, "rss": _rss,
         "html_links": _html_links, "html_diff": _html_diff, "npm": _npm,
         "plugin": _plugin, "discord_channel": _discord_channel}


def fetch(source, state, installed_version=None):
    """Dispatch on source["kind"] -> (items newest first, new per-source state). Raises FetchError only."""
    fn = KINDS.get(source.get("kind"))
    if fn is None:
        raise FetchError("unknown kind")
    try:
        return fn(source, state or {}, installed_version)
    except FetchError:
        raise
    except Exception as e:  # bad JSON/XML, missing keys, odd shapes
        raise FetchError(f"{source.get('kind')}: {type(e).__name__}: {e}") from None
