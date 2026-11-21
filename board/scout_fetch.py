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
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

UA = "agent-board-scout"
TIMEOUT = 20
MAX_BYTES = 4 * 1024 * 1024
EXCERPT_MAX = 4096
ATOM = "{http://www.w3.org/2005/Atom}"
GH_HOSTS = {"api.github.com", "127.0.0.1", "localhost"}  # hosts that may receive the gh token


class FetchError(Exception):
    pass


# no HTTPCookieProcessor: no cookies are stored or replayed
_OPENER = urllib.request.build_opener()


def get(url, accept=None, headers=None):
    """GET url -> (status, body bytes (at most MAX_BYTES), content type). FetchError on a network error or status >= 400."""
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            return r.status, r.read(MAX_BYTES), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} for {url}") from None
    except Exception as e:  # URLError, timeout, ssl, bad url, connection reset
        raise FetchError(f"{type(e).__name__}: {e}") from None


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
    """RFC 822 (RSS) -> ISO UTC; anything else (Atom ISO) passes through; None when empty."""
    s = (s or "").strip()
    if not s:
        return None
    if re.match(r"\d{4}-\d\d-\d\d", s):
        return s
    try:
        return parsedate_to_datetime(s).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return s


def _newest_first(items):
    return sorted(items, key=lambda i: i["published"] or "", reverse=True)  # stable: ties keep feed order


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


def _html_diff(source, state, installed_version):
    p = _Page()
    p.feed(_text(_body(source["url"])))
    p.close()
    text = " ".join(" ".join(p.main if p.has_main else p.body).split())
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
    data = json.loads(_text(_body(source["url"], "application/json")))
    latest = data["dist-tags"]["latest"]
    new_state = {"latest": latest}
    if latest == (state or {}).get("latest"):
        return [], new_state
    name = data.get("name") or "package"
    published = (data.get("time") or {}).get(latest)
    url = "https://www.npmjs.com/package/" + name
    return [_item(f"{name} {latest}", url, version=latest, published=published)], new_state


KINDS = {"changelog_md": _changelog_md, "github_releases": _github_releases, "rss": _rss,
         "html_links": _html_links, "html_diff": _html_diff, "npm": _npm}


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
