"""scout_fetch: the web fetchers, against a local 127.0.0.1 server that serves board/tests/fixtures/scout/."""
import json
import os
import warnings
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scout_fetch as sf  # noqa: E402

FIX = HERE / "fixtures" / "scout"


class Handler(BaseHTTPRequestHandler):
    extra = {}      # path -> (bytes, content type); overrides the fixture dir
    seen = []       # (path, headers dict) of every request
    redirects = {}  # path -> Location of a 302

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.seen.append((self.path, dict(self.headers)))
        path = self.path.split("?")[0]
        if path in Handler.redirects:
            self.send_response(302)
            self.send_header("Location", Handler.redirects[path])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/500":
            self.send_response(500)
            self.end_headers()
            return
        if path in Handler.extra:
            body, ctype = Handler.extra[path]
        else:
            f = FIX / path.lstrip("/")
            if not f.is_file():
                self.send_response(404)
                self.end_headers()
                return
            body = f.read_bytes()
            ctype = "text/html" if f.suffix == ".html" else "application/json" if f.suffix == ".json" else "text/plain"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "a=b")
        self.end_headers()
        self.wfile.write(body)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {"TC_SCOUT_DIR": self.tmp.name + "/scout", "TC_STATE": self.tmp.name + "/state", "HOME": self.tmp.name}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        Handler.extra = {}
        Handler.seen = []
        Handler.redirects = {}
        import scout_sources as _ss   # the URL check's test seam: the local server is http on 127.0.0.1; other hosts resolve to a global address
        for _n, _v in (("_HTTP_OK_HOSTS", ("127.0.0.1",)), ("_resolve", lambda host: ["93.184.215.14"])):
            _p = mock.patch.object(_ss, _n, _v)
            _p.start()
            self.addCleanup(_p.stop)
        g = mock.patch.object(sf, "_gh_token", return_value=None)
        g.start()
        self.addCleanup(g.stop)

    def src(self, kind, path, **kw):
        d = {"name": "s", "kind": kind, "url": self.base + path}
        d.update(kw)
        return d

    def assertShape(self, it):
        self.assertEqual(set(it), {"title", "url", "version", "published", "excerpt", "content_hash"})
        self.assertLessEqual(len(it["excerpt"].encode("utf-8")), 4096)


class GetTest(Base):
    def test_get_ok_headers_and_no_cookie_replay(self):
        st, body, ct = sf.get(self.base + "/npm.json", accept="application/json", headers={"X-A": "1"})
        self.assertEqual(st, 200)
        self.assertIn(b"latest", body)
        self.assertEqual(ct, "application/json")
        sf.get(self.base + "/npm.json")
        h = Handler.seen[0][1]
        self.assertEqual(h["User-Agent"], "agent-board-scout")
        self.assertEqual(h["Accept"], "application/json")
        self.assertEqual(h["X-A"], "1")
        self.assertNotIn("Cookie", Handler.seen[1][1])

    def test_status_ge_400_raises_fetcherror(self):
        for p in ("/500", "/nothere"):
            with self.assertRaises(sf.FetchError):
                sf.get(self.base + p)

    def test_http_error_closes_response_no_resourcewarning(self):
        import gc
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            for p in ("/500", "/nothere"):
                with self.assertRaises(sf.FetchError):
                    sf.get(self.base + p)
            gc.collect()
        self.assertEqual([x for x in w if issubclass(x.category, ResourceWarning)], [])

    def test_network_error_raises_fetcherror(self):
        with self.assertRaises(sf.FetchError):
            sf.get("http://127.0.0.1:1/x")

    def test_timeout_is_20s_and_cap_is_4mb(self):
        self.assertEqual(sf.TIMEOUT, 20)
        self.assertEqual(sf.MAX_BYTES, 4 * 1024 * 1024)
        Handler.extra["/big"] = (b"x" * (5 * 1024 * 1024), "text/plain")
        _, body, _ = sf.get(self.base + "/big")
        self.assertEqual(len(body), 4 * 1024 * 1024)
        with mock.patch("urllib.request.OpenerDirector.open", side_effect=TimeoutError("t")) as m:
            with self.assertRaises(sf.FetchError):
                sf.get(self.base + "/npm.json")
        self.assertEqual(m.call_args.kwargs.get("timeout"), 20)


class RedirectTest(Base):
    """get() follows redirects by hand: every hop passes scout_sources.check_url_safe before it is requested."""

    def ok_hosts(self, *hosts):
        import scout_sources
        p = mock.patch.object(scout_sources, "_HTTP_OK_HOSTS", hosts)
        p.start()
        self.addCleanup(p.stop)

    def test_redirects_followed_by_hand(self):
        Handler.redirects = {"/r1": "/r2", "/r2": "/npm.json"}
        st, body, _ = sf.get(self.base + "/r1")
        self.assertEqual(st, 200)
        self.assertIn(b"latest", body)
        self.assertEqual([p for p, _ in Handler.seen], ["/r1", "/r2", "/npm.json"])

    def test_first_url_refused_before_any_request(self):
        with self.assertRaises(sf.Refused) as cm:
            sf.get("https://10.0.0.5/feed")
        self.assertEqual(str(cm.exception), "refused: private address 10.0.0.5")
        self.assertEqual(Handler.seen, [])

    def test_redirect_to_a_private_address_is_refused(self):
        # mutation: check only the first URL in get() -> the hop is requested and the test sees a network error instead
        Handler.redirects = {"/r1": "https://10.0.0.5/meta"}
        with self.assertRaises(sf.Refused) as cm:
            sf.get(self.base + "/r1")
        self.assertEqual(str(cm.exception), "refused: private address 10.0.0.5")
        self.assertEqual([p for p, _ in Handler.seen], ["/r1"])

    def test_redirect_to_a_name_that_resolves_to_metadata_is_refused(self):
        import scout_sources
        fake = lambda host: ["169.254.169.254"] if host == "metadata.example.com" else ["93.184.215.14"]
        with mock.patch.object(scout_sources, "_resolve", fake):
            Handler.redirects = {"/r1": "https://metadata.example.com/latest/meta-data"}
            with self.assertRaises(sf.Refused) as cm:
                sf.get(self.base + "/r1")
        self.assertEqual(str(cm.exception), "refused: link-local address 169.254.169.254")

    def test_at_most_five_redirects(self):
        Handler.redirects = {f"/l{i}": f"/l{i + 1}" for i in range(6)}
        Handler.extra["/l6"] = (b"end", "text/plain")
        self.assertEqual(sf.get(self.base + "/l1")[1], b"end")   # five hops: followed
        self.assertEqual(len(Handler.seen), 6)
        Handler.seen = []
        with self.assertRaises(sf.FetchError) as cm:   # six hops: refused after the fifth
            sf.get(self.base + "/l0")
        self.assertEqual(str(cm.exception), "more than 5 redirects")
        self.assertEqual(len(Handler.seen), 6)

    def test_authorization_goes_only_to_the_first_host(self):
        # mutation: send the same headers on every hop -> the second request carries the token
        self.ok_hosts("127.0.0.1", "localhost")
        port = self.srv.server_address[1]
        Handler.redirects = {"/r1": f"http://localhost:{port}/npm.json"}
        sf.get(self.base + "/r1", headers={"Authorization": "Bearer T"})
        self.assertEqual(Handler.seen[0][1].get("Authorization"), "Bearer T")
        self.assertEqual(Handler.seen[1][0], "/npm.json")
        self.assertNotIn("Authorization", Handler.seen[1][1])


class DispatchTest(Base):
    def test_unknown_kind(self):
        for k in ("nope", None, ""):
            with self.assertRaises(sf.FetchError) as cm:
                sf.fetch(self.src(k, "/x"), {})
            self.assertEqual(str(cm.exception), "unknown kind")


class ChangelogTest(Base):
    def test_sections_newest_first(self):
        items, state = sf.fetch(self.src("changelog_md", "/changelog.md"), {})
        self.assertEqual(state, {})
        self.assertEqual([i["version"] for i in items], ["2.1.330", "2.1.329", "2.1.328"])
        self.assertEqual(items[0]["title"], "Claude Code 2.1.330")
        self.assertIn("easel", items[0]["excerpt"])
        self.assertNotIn("2.1.329", items[0]["excerpt"])
        for i in items:
            self.assertShape(i)

    def test_installed_version_on_first_line(self):
        items, _ = sf.fetch(self.src("changelog_md", "/changelog.md"), {}, installed_version="2.1.330")
        first = items[0]["excerpt"].split("\n")[0]
        self.assertTrue(first.endswith("(installed 2.1.330)"), first)

    def test_parse_installed_version(self):
        self.assertEqual(sf.parse_installed_version("2.1.330 (Claude Code)\n"), "2.1.330")
        self.assertIsNone(sf.parse_installed_version("garbage"))

    def test_big_section_cut_to_4096_bytes_on_char_boundary(self):
        body = "# Changelog\n\n## 3.0.0\n\n" + "- é" * 5000 + "\n\n## 2.9.0\n\n- small\n"
        Handler.extra["/big.md"] = (body.encode(), "text/plain")
        items, _ = sf.fetch(self.src("changelog_md", "/big.md"), {}, installed_version="3.0.0")
        self.assertLessEqual(len(items[0]["excerpt"].encode()), 4096)
        self.assertGreater(len(items[0]["excerpt"].encode()), 4000)
        items[0]["excerpt"].encode("utf-8").decode("utf-8")

    def test_broken(self):
        for path, body in (("/500", None), ("/empty", b""), ("/nosec", b"just text, no headers")):
            if body is not None:
                Handler.extra[path] = (body, "text/plain")
            with self.assertRaises(sf.FetchError, msg=path):
                sf.fetch(self.src("changelog_md", path), {})


class GithubReleasesTest(Base):
    REL = [{"tag_name": "v1.2.0", "name": "One two", "html_url": "https://github.com/o/r/releases/tag/v1.2.0",
            "published_at": "2026-11-20T10:00:00Z", "body": "Notes **here**"},
           {"tag_name": "v1.1.0", "html_url": "https://github.com/o/r/releases/tag/v1.1.0",
            "published_at": "2026-11-10T10:00:00Z", "body": None}]

    def setUp(self):
        super().setUp()
        Handler.extra["/rel.json"] = (json.dumps(self.REL).encode(), "application/json")

    def test_items(self):
        items, state = sf.fetch(self.src("github_releases", "/rel.json"), {})
        self.assertEqual(state, {})
        self.assertEqual([i["version"] for i in items], ["v1.2.0", "v1.1.0"])
        self.assertEqual(items[0]["url"], self.REL[0]["html_url"])
        self.assertEqual(items[0]["published"], "2026-11-20T10:00:00Z")
        self.assertIn("Notes", items[0]["excerpt"])
        self.assertEqual(items[1]["excerpt"], "")
        for i in items:
            self.assertShape(i)

    def test_token_only_when_gh_logged_in_and_never_in_items(self):
        with mock.patch.object(sf, "_gh_token", return_value="SEKRET-TOKEN"):
            items, _ = sf.fetch(self.src("github_releases", "/rel.json"), {})
        self.assertEqual(Handler.seen[-1][1].get("Authorization"), "Bearer SEKRET-TOKEN")
        self.assertNotIn("SEKRET-TOKEN", json.dumps(items))
        Handler.seen.clear()
        sf.fetch(self.src("github_releases", "/rel.json"), {})
        self.assertNotIn("Authorization", Handler.seen[-1][1])

    def test_token_not_sent_to_other_hosts(self):
        with mock.patch.object(sf, "_gh_token", return_value="SEKRET-TOKEN"):
            with self.assertRaises(sf.FetchError):
                sf.fetch({"name": "s", "kind": "github_releases", "url": "http://example.invalid:1/x"}, {})
        self.assertEqual(Handler.seen, [])

    def test_gh_token_real_subprocess_with_fake_gh(self):
        # unpatched _gh_token against a fake `gh` first on PATH
        for status, expect in ((0, "tok123"), (1, None)):
            with tempfile.TemporaryDirectory() as d:
                gh = Path(d) / "gh"
                gh.write_text('#!/bin/sh\n[ "$1 $2" = "auth status" ] && exit %d\n[ "$1 $2" = "auth token" ] && echo tok123\n' % status)
                gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
                with mock.patch.dict(os.environ, {"PATH": d + os.pathsep + "/usr/bin:/bin"}):
                    self.assertEqual(sf._gh_token_impl(), expect)

    def test_gh_missing_gives_none(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertIsNone(sf._gh_token_impl())

    def test_broken(self):
        Handler.extra["/bad.json"] = (b"{not json", "application/json")
        Handler.extra["/obj.json"] = (b'{"message": "x"}', "application/json")
        Handler.extra["/empty"] = (b"", "application/json")
        for p in ("/500", "/bad.json", "/obj.json", "/empty"):
            with self.assertRaises(sf.FetchError, msg=p):
                sf.fetch(self.src("github_releases", p), {})


ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
<entry><title>Atom one</title><link rel="alternate" href="https://e.com/a1"/><updated>2026-11-20T01:00:00Z</updated>
<summary>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</summary></entry>
<entry><title>Atom two</title><link href="https://e.com/a2"/><published>2026-11-10T01:00:00Z</published>
<content type="html">&lt;div&gt;Body&lt;/div&gt;</content></entry></feed>"""

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>c</title>
<item><title>Old</title><link>https://e.com/old</link><pubDate>Fri, 13 Nov 2026 00:00:00 GMT</pubDate></item>
<item><title>New</title><link>https://e.com/new</link><pubDate>Tue, 17 Nov 2026 00:00:00 GMT</pubDate>
<description>&lt;p&gt;Some &lt;i&gt;text&lt;/i&gt;&lt;/p&gt;</description></item></channel></rss>"""


class RssTest(Base):
    def test_fixture_no_description(self):
        items, state = sf.fetch(self.src("rss", "/claude_blog_rss.xml"), {})
        self.assertEqual(state, {})
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["title"], "Linked billing on the Claude Platform")
        self.assertEqual(items[0]["url"], "https://claude.com/resources/articles/linked-billing-on-claude-platform")
        self.assertEqual(items[0]["excerpt"], "")
        self.assertTrue(items[0]["published"].startswith("2026-11-17"))
        for i in items:
            self.assertShape(i)

    def test_rss_description_stripped_and_sorted_newest_first(self):
        Handler.extra["/r.xml"] = (RSS.encode(), "application/xml")
        items, _ = sf.fetch(self.src("rss", "/r.xml"), {})
        self.assertEqual([i["title"] for i in items], ["New", "Old"])
        self.assertEqual(items[0]["excerpt"], "Some text")

    def test_atom(self):
        Handler.extra["/a.xml"] = (ATOM.encode(), "application/atom+xml")
        items, _ = sf.fetch(self.src("rss", "/a.xml"), {})
        self.assertEqual([i["url"] for i in items], ["https://e.com/a1", "https://e.com/a2"])
        self.assertEqual(items[0]["excerpt"], "Hello world")
        self.assertEqual(items[1]["excerpt"], "Body")
        self.assertEqual(items[1]["published"], "2026-11-10T01:00:00Z")

    def test_dates_converted_to_utc_and_bad_dates_none_sorted_last(self):
        cases = {"Tue, 17 Nov 2026 12:00:00 +0200": "2026-11-17T10:00:00Z",
                 "Tue, 17 Nov 2026 12:00:00 -0500": "2026-11-17T17:00:00Z",
                 "Tue, 17 Nov 2026 12:00:00 GMT": "2026-11-17T12:00:00Z",
                 "2026-11-20T01:00:00Z": "2026-11-20T01:00:00Z",
                 "2026-11-20T03:00:00+02:00": "2026-11-20T01:00:00Z",
                 "not a date": None, "": None}
        for raw, want in cases.items():
            self.assertEqual(sf._iso_date(raw), want, raw)
        feed = ("<rss><channel>" + "".join(
            f"<item><title>{n}</title><link>https://e.com/{n}</link><pubDate>{d}</pubDate></item>" for n, d in
            (("bad", "garbage"), ("a", "Tue, 17 Nov 2026 12:00:00 +0200"), ("b", "Tue, 17 Nov 2026 11:00:00 GMT"))
        ) + "</channel></rss>")
        Handler.extra["/d.xml"] = (feed.encode(), "application/xml")
        items, _ = sf.fetch(self.src("rss", "/d.xml"), {})
        self.assertEqual([i["title"] for i in items], ["b", "a", "bad"])  # b 11:00Z > a 10:00Z; None last
        self.assertIsNone(items[2]["published"])

    def test_long_summary_cut(self):
        big = "<rss><channel><item><title>t</title><link>https://e.com/x</link><description>" + "é" * 10000 + "</description></item></channel></rss>"
        Handler.extra["/b.xml"] = (big.encode(), "application/xml")
        items, _ = sf.fetch(self.src("rss", "/b.xml"), {})
        self.assertLessEqual(len(items[0]["excerpt"].encode()), 4096)
        self.assertGreater(len(items[0]["excerpt"].encode()), 4000)

    def test_broken(self):
        Handler.extra["/bad.xml"] = (b"<rss><channel>", "application/xml")
        Handler.extra["/empty"] = (b"", "application/xml")
        Handler.extra["/other.xml"] = (b"<html/>", "application/xml")
        for p in ("/500", "/bad.xml", "/empty", "/other.xml"):
            with self.assertRaises(sf.FetchError, msg=p):
                sf.fetch(self.src("rss", p), {})


class HtmlLinksTest(Base):
    def test_news(self):
        s = self.src("html_links", "/anthropic_news.index.html", prefix="/news/")
        items, state = sf.fetch(s, {})
        self.assertEqual(state, {})
        urls = [i["url"] for i in items]
        self.assertIn(self.base + "/news/public-benefit-fund", urls)
        self.assertEqual(len(urls), len(set(urls)))
        for i in items:
            self.assertTrue(i["url"].startswith(self.base + "/news/") and len(i["url"]) > len(self.base + "/news/"))
            self.assertNotIn("#", i["url"])
            self.assertNotIn("?", i["url"])
            self.assertEqual(i["title"], " ".join(i["title"].split()))
            self.assertTrue(i["title"])
            self.assertShape(i)

    def test_engineering_prefix_research(self):
        s = self.src("html_links", "/anthropic_engineering.index.html", prefix="/research/")
        items, _ = sf.fetch(s, {})
        self.assertIn(self.base + "/research/components-of-agent-memory", [i["url"] for i in items])
        self.assertTrue(all("/research/" in i["url"] for i in items))

    def test_filters_host_fragment_query_prefix_and_collapses_title(self):
        html = ('<a href="/news/a?x=1#frag">  Title\n  A </a><a href="/news/a">dup</a><a href="/news/">idx</a>'
                '<a href="/news">idx2</a><a href="https://other.example/news/b">ext</a>'
                f'<a href="{self.base}/news/c">C</a><a href="/blog/d">D</a><a href="/news/e"><img alt="x"></a>'
                '<a href="/news/e">E title</a>')
        Handler.extra["/idx.html"] = (html.encode(), "text/html")
        items, _ = sf.fetch(self.src("html_links", "/idx.html", prefix="/news/"), {})
        got = {i["url"].replace(self.base, ""): i["title"] for i in items}
        self.assertEqual(got, {"/news/a": "Title A", "/news/c": "C", "/news/e": "E title"})

    def test_broken(self):
        Handler.extra["/empty"] = (b"", "text/html")
        Handler.extra["/nolinks.html"] = (b"<html><body>none</body></html>", "text/html")
        for p in ("/500", "/empty"):
            with self.assertRaises(sf.FetchError, msg=p):
                sf.fetch(self.src("html_links", p, prefix="/news/"), {})
        # a page with no matching links is a valid (empty) result, not an error
        items, _ = sf.fetch(self.src("html_links", "/nolinks.html", prefix="/news/"), {})
        self.assertEqual(items, [])


class HtmlDiffTest(Base):
    def run_diff(self, path, state):
        return sf.fetch(self.src("html_diff", path), state)

    def test_first_run_stores_hash_only(self):
        items, state = self.run_diff("/cc_changelog.html", {})
        self.assertEqual(items, [])
        self.assertEqual(len(state["hash"]), 64)

    def test_unchanged(self):
        _, st = self.run_diff("/cc_changelog.html", {})
        items, st2 = self.run_diff("/cc_changelog.html", st)
        self.assertEqual(items, [])
        self.assertEqual(st2, st)

    def test_changed_main_gives_item(self):
        _, st = self.run_diff("/cc_changelog.html", {})
        Handler.extra["/page.html"] = ((FIX / "cc_changelog-changed.html").read_bytes(), "text/html")
        items, st2 = self.run_diff("/page.html", st)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertShape(it)
        self.assertEqual(it["content_hash"], st2["hash"])
        self.assertNotEqual(st2["hash"], st["hash"])
        self.assertIn("2.1.331", it["excerpt"])
        self.assertEqual(it["url"], self.base + "/page.html")

    def test_nav_header_footer_only_changes_give_no_item(self):
        _, st = self.run_diff("/cc_changelog.html", {})
        items, st2 = self.run_diff("/cc_changelog-navonly.html", st)
        self.assertEqual(items, [])
        self.assertEqual(st2["hash"], st["hash"])

    def test_body_fallback_skips_nav_header_footer(self):
        def page(nav, head, foot, body="Real content"):
            return f"<html><body><nav>{nav}</nav><header>{head}</header><div>{body}</div><footer>{foot}</footer></body></html>".encode()
        Handler.extra["/nomain.html"] = (page("n1", "h1", "f1"), "text/html")
        _, st = self.run_diff("/nomain.html", {})
        Handler.extra["/nomain.html"] = (page("n2", "h2", "f2"), "text/html")
        items, _ = self.run_diff("/nomain.html", st)
        self.assertEqual(items, [])
        Handler.extra["/nomain.html"] = (page("n1", "h1", "f1", "Other content"), "text/html")
        items, _ = self.run_diff("/nomain.html", st)
        self.assertEqual(len(items), 1)

    def test_whitespace_changes_ignored(self):
        Handler.extra["/w.html"] = (b"<main>a   b\n c</main>", "text/html")
        _, st = self.run_diff("/w.html", {})
        Handler.extra["/w.html"] = (b"<main>a b c</main>", "text/html")
        items, _ = self.run_diff("/w.html", st)
        self.assertEqual(items, [])

    def test_all_four_probe_pages_have_main_text(self):
        for p in ("cc_changelog", "api_release_notes", "models_overview", "pricing"):
            _, st = self.run_diff(f"/{p}.html", {})
            self.assertEqual(len(st["hash"]), 64, p)

    def test_excerpt_cut(self):
        Handler.extra["/big.html"] = (("<main>" + "é " * 9000 + "</main>").encode(), "text/html")
        items, _ = self.run_diff("/big.html", {"hash": "old"})
        self.assertLessEqual(len(items[0]["excerpt"].encode()), 4096)
        self.assertGreater(len(items[0]["excerpt"].encode()), 4000)

    def test_broken(self):
        Handler.extra["/empty"] = (b"", "text/html")
        Handler.extra["/notext.html"] = (b"<html><body><nav>x</nav></body></html>", "text/html")
        for p in ("/500", "/empty", "/notext.html"):
            with self.assertRaises(sf.FetchError, msg=p):
                self.run_diff(p, {})


class NpmTest(Base):
    TAGS = "/-/package/@anthropic-ai/claude-code/dist-tags"
    PKG = "/@anthropic-ai/claude-code"

    def setUp(self):
        super().setUp()
        Handler.extra[self.TAGS] = ((FIX / "npm.json").read_bytes(), "application/json")

    def test_reads_dist_tags_url_built_from_source_path(self):
        sf.fetch(self.src("npm", self.PKG), {})
        self.assertEqual([p for p, _ in Handler.seen], [self.TAGS])

    def test_new_version(self):
        items, state = sf.fetch(self.src("npm", self.PKG), {})
        self.assertEqual(state, {"latest": "2.1.330"})
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertShape(it)
        self.assertEqual(it["version"], "2.1.330")
        self.assertEqual(it["title"], "@anthropic-ai/claude-code 2.1.330")
        self.assertEqual(it["url"], "https://www.npmjs.com/package/@anthropic-ai/claude-code")

    def test_unchanged(self):
        items, state = sf.fetch(self.src("npm", self.PKG), {"latest": "2.1.330"})
        self.assertEqual(items, [])
        self.assertEqual(state, {"latest": "2.1.330"})

    def test_changed(self):
        items, state = sf.fetch(self.src("npm", self.PKG), {"latest": "2.1.329"})
        self.assertEqual([i["version"] for i in items], ["2.1.330"])
        self.assertEqual(state, {"latest": "2.1.330"})

    def test_broken(self):
        Handler.extra["/-/package/bad/dist-tags"] = (b"nope", "application/json")
        Handler.extra["/-/package/nolatest/dist-tags"] = (b'{"next": "1.0.0"}', "application/json")
        Handler.extra["/-/package/empty/dist-tags"] = (b"", "application/json")
        for p in ("/500", "/bad", "/nolatest", "/empty", "/missing", "/"):
            with self.assertRaises(sf.FetchError, msg=p):
                sf.fetch(self.src("npm", p), {})


class IsolationTest(Base):
    def test_real_scout_dir_untouched(self):
        real = Path.home() / ".local/state/agent-board/scout"
        before = sorted(p.name for p in real.iterdir()) if real.exists() else None
        Handler.extra[NpmTest.TAGS] = ((FIX / "npm.json").read_bytes(), "application/json")
        sf.fetch(self.src("npm", NpmTest.PKG), {})
        after = sorted(p.name for p in real.iterdir()) if real.exists() else None
        self.assertEqual(before, after)


class SslContextTest(unittest.TestCase):
    """_ssl_context: a Python with no CA bundle falls back to the system file; verification stays on."""
    MISSING = mock.Mock(cafile=None, capath=None, openssl_cafile="/nonexistent/cert.pem", openssl_capath="/nonexistent/certs")

    def ctx(self, env=None, fallback_exists=True, paths=None):
        fake = mock.Mock()
        e = {k: v for k, v in os.environ.items() if k != "SSL_CERT_FILE"}
        e.update(env or {})
        with mock.patch.dict(os.environ, e, clear=True), \
                mock.patch.object(sf.ssl, "create_default_context", return_value=fake), \
                mock.patch.object(sf.ssl, "get_default_verify_paths", return_value=paths or self.MISSING), \
                mock.patch.object(sf.os.path, "isfile", return_value=fallback_exists):
            sf._ssl_context()
        return fake

    def test_missing_bundle_loads_the_system_file(self):
        self.ctx().load_verify_locations.assert_called_once_with("/etc/ssl/cert.pem")

    def test_ssl_cert_file_set_is_not_overridden(self):
        self.ctx(env={"SSL_CERT_FILE": "/some/ca.pem"}).load_verify_locations.assert_not_called()

    def test_an_existing_default_bundle_is_not_overridden(self):
        here = mock.Mock(cafile=None, capath=None, openssl_cafile=__file__, openssl_capath="/nonexistent")
        self.ctx(paths=here).load_verify_locations.assert_not_called()

    def test_no_system_file_loads_nothing(self):
        self.ctx(fallback_exists=False).load_verify_locations.assert_not_called()

    def test_real_context_verifies(self):
        c = sf._ssl_context()                      # unpatched: the host's real ssl module
        self.assertEqual((c.verify_mode, c.check_hostname), (sf.ssl.CERT_REQUIRED, True))


if __name__ == "__main__":
    unittest.main()
