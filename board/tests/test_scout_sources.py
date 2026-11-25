"""scout_sources: sources.json, the sources CLI, the daily poll, #scout requests. Local HTTP server only (127.0.0.1)."""
import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scout_sources as ss  # noqa: E402
import tc_env  # noqa: E402

FIX = HERE / "fixtures" / "scout"
TOKEN = "tok-SECRET-123"
CHAN = "1234567890123456"
ALLOWED = "7"


def changelog(n):
    return "# Changelog\n\n" + "".join(f"## 2.1.{300 + i}\n\n- change {i}\n\n" for i in range(n, 0, -1))


class Handler(BaseHTTPRequestHandler):
    routes = {}
    messages = []
    posted = []        # POST bodies
    fail_posts = 0     # next N POSTs answer 500
    reacted = {}       # reply id -> [user ids]
    edited = []        # (message id, PATCH body)
    fail_edits = 0     # next N PATCHes answer 500
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, status, body, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n) if n else b""
        path = self.path.split("?")[0]
        Handler.seen.append((method, self.path))
        if path.startswith("/api/"):
            parts = path.split("/")  # '', api, channels, id, messages, [mid, reactions, emoji]
            if method == "GET" and len(parts) == 5:
                return self._send(200, json.dumps(Handler.messages).encode())
            if method == "POST" and len(parts) == 5:
                if Handler.fail_posts > 0:
                    Handler.fail_posts -= 1
                    return self._send(500, b"{}")
                body = json.loads(data)
                Handler.posted.append(body)
                return self._send(200, json.dumps({"id": str(9000 + len(Handler.posted))}).encode())
            if method == "GET" and len(parts) == 8 and parts[6] == "reactions":
                if parts[7] != "%E2%9C%85":
                    return self._send(404, b"{}")
                return self._send(200, json.dumps([{"id": u} for u in Handler.reacted.get(parts[5], [])]).encode())
            if method == "PATCH" and len(parts) == 6:
                if Handler.fail_edits > 0:
                    Handler.fail_edits -= 1
                    return self._send(500, b"{}")
                Handler.edited.append((parts[5], json.loads(data)))
                return self._send(200, json.dumps({"id": parts[5]}).encode())
            return self._send(404, b"{}")
        if path in Handler.routes:
            status, body, ctype = Handler.routes[path]
            return self._send(status, body, ctype)
        self._send(404, b"nope", "text/plain")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


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
        t = self.tmp.name
        self.home = Path(t) / "home"
        (self.home / ".claude/plugins").mkdir(parents=True)
        env = {"TC_SCOUT_DIR": t + "/scout", "TC_STATE": t + "/state", "HOME": self.home.as_posix(),
               "TC_SCOUT_RAW_BASE": self.base + "/raw", "TC_SCOUT_DISCORD_API": self.base + "/api"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.scout = Path(t) / "scout"
        Handler.routes, Handler.messages, Handler.posted, Handler.reacted, Handler.seen = {}, [], [], {}, []
        Handler.fail_posts, Handler.edited, Handler.fail_edits = 0, [], 0
        self.now = 1_800_000_000.0
        import scout_sources as _ss   # the URL check's test seam: the local server is http on 127.0.0.1; other hosts resolve to a global address
        for _n, _v in (("_HTTP_OK_HOSTS", ("127.0.0.1",)), ("_resolve", lambda host: ["93.184.215.14"])):
            _p = mock.patch.object(_ss, _n, _v)
            _p.start()
            self.addCleanup(_p.stop)

    def sources(self, *rows, health=None):
        ss.save({"sources": [dict({"why": "", "added": "x", "builtin": False}, **r) for r in rows], "health": health or {}})

    def serve(self, path, body, ctype="text/plain"):
        Handler.routes[path] = (200, body.encode() if isinstance(body, str) else body, ctype)

    def items(self):
        p = self.scout / "items.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def seen_state(self):
        return json.loads((self.scout / "seen.json").read_text())

    def log(self):
        p = self.scout / "poll.log"
        return p.read_text() if p.exists() else ""

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ss.main(list(argv))
        return rc, out.getvalue(), err.getvalue()


class SourcesTest(Base):
    def test_default_sources_are_the_probe_table(self):
        want = [("claude-code-changelog", "changelog_md", "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md", None),
                ("claude-code-npm", "npm", "https://registry.npmjs.org/@anthropic-ai/claude-code", None),
                ("anthropic-news", "html_links", "https://www.anthropic.com/news", "/news/"),
                ("anthropic-engineering", "html_links", "https://www.anthropic.com/engineering", "/research/"),
                ("claude-blog", "rss", "https://claude.com/resources/articles/rss.xml", None),
                ("claude-code-release-notes", "html_diff", "https://code.claude.com/docs/en/changelog", None),
                ("api-release-notes", "html_diff", "https://platform.claude.com/docs/en/release-notes/overview", None),
                ("models-overview", "html_diff", "https://platform.claude.com/docs/en/models/overview", None),
                ("api-pricing", "html_diff", "https://platform.claude.com/docs/en/about-claude/pricing", None),
                ("plugins", "plugin", "~/.claude/plugins", None)]
        got = [(s["name"], s["kind"], s["url"], s.get("prefix")) for s in ss.DEFAULT_SOURCES]
        self.assertEqual(got, want)
        self.assertTrue(all(s["builtin"] for s in ss.DEFAULT_SOURCES))

    def test_first_call_writes_defaults(self):
        rc, out, _ = self.cli("source", "list")
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[0].split("\t"), ["claude-code-changelog", "changelog_md",
                         "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md", "0"])
        self.assertTrue((self.scout / "sources.json").exists())

    def test_add_refusals_exit_2(self):
        bad = [(["x", "--kind", "bogus", "--url", "https://a.example/"], "kind"),
               (["Bad Name", "--kind", "rss", "--url", "https://a.example/"], "name"),
               (["x", "--kind", "rss", "--url", "http://a.example/"], "url"),
               (["x", "--kind", "discord_channel", "--url", "123"], "url"),
               (["x", "--kind", "discord_channel", "--url", "abcdefghijklmnop"], "url"),
               (["claude-blog", "--kind", "rss", "--url", "https://a.example/"], "duplicate")]
        for args, what in bad:
            rc, out, err = self.cli("source", "add", *args, "--why", "w")
            self.assertEqual(rc, 2, what)
            self.assertTrue((out + err).startswith("scout: "), (what, out, err))
        self.assertEqual(len(ss.load()["sources"]), 10)

    def test_add_list_remove(self):
        rc, out, _ = self.cli("source", "add", "my-feed", "--kind", "rss", "--url", "https://a.example/f.xml", "--why", "because")
        self.assertEqual((rc, out.strip()), (0, "added my-feed (rss)"))
        rc, out, _ = self.cli("source", "add", "chan", "--kind", "discord_channel", "--url", CHAN, "--why", "x")
        self.assertEqual(rc, 0)
        rc, out, _ = self.cli("source", "add", "pg", "--kind", "html_links", "--url", "https://a.example/blog", "--why", "x")
        self.assertEqual(ss.load()["sources"][-1]["prefix"], "/blog/")
        self.assertIn("my-feed\trss\thttps://a.example/f.xml\t0", self.cli("source", "list")[1])
        self.assertEqual(self.cli("source", "remove", "my-feed")[0], 0)
        self.assertNotIn("my-feed", self.cli("source", "list")[1])
        rc, out, err = self.cli("source", "remove", "my-feed")
        self.assertEqual(rc, 2)
        self.assertTrue((out + err).startswith("scout: "))

    def test_source_test_prints_items_and_writes_nothing(self):
        self.serve("/c.md", changelog(2))
        self.sources({"name": "cl", "kind": "changelog_md", "url": self.base + "/c.md"})
        before = tree(self.scout)
        rc, out, _ = self.cli("source", "test", "cl")
        self.assertEqual(rc, 0)
        self.assertEqual([l.split("\t")[0] for l in out.splitlines()], ["Claude Code 2.1.302", "Claude Code 2.1.301"])
        self.assertEqual(tree(self.scout), before)
        self.assertEqual(self.cli("source", "test", "nope")[0], 2)

    def test_add_refuses_a_private_or_unresolvable_host(self):
        with mock.patch.object(ss, "_resolve", lambda host: ["10.0.0.5"]):
            rc, out, err = self.cli("source", "add", "intra", "--kind", "rss", "--url", "https://intra.example.com/f.xml")
        self.assertEqual((rc, err.strip()), (2, "scout: private address 10.0.0.5"))
        rc, out, err = self.cli("source", "add", "meta", "--kind", "html_links", "--url", "https://169.254.169.254/latest/")
        self.assertEqual((rc, err.strip()), (2, "scout: link-local address 169.254.169.254"))
        self.assertNotIn("intra", [s["name"] for s in ss.load()["sources"]])


class PollTest(Base):
    def poll(self, dt=0):
        return ss.poll(self.now + dt)

    def test_first_poll_caps_at_three_then_only_new(self):
        self.serve("/c.md", changelog(6))
        self.sources({"name": "cl", "kind": "changelog_md", "url": self.base + "/c.md"})
        self.assertEqual(self.poll(), (3, 1, 0))
        self.assertEqual(len(self.items()), 3)
        it = self.items()[0]
        self.assertEqual(set(it), {"key", "source", "kind", "title", "url", "published", "fetched_at", "excerpt"})
        self.assertEqual(it["source"], "cl")
        self.serve("/c.md", changelog(7))
        self.assertEqual(self.poll(60), (1, 1, 0))
        self.assertEqual(len(self.items()), 4)
        self.assertEqual(self.items()[-1]["title"], "Claude Code 2.1.307")
        self.assertIn("cl", self.seen_state()["sources"])

    def test_second_poll_over_unchanged_fixtures_adds_nothing(self):
        self.serve("/c.md", changelog(6))
        self.serve("/f.xml", (FIX / "claude_blog_rss.xml").read_text(), "application/rss+xml")
        self.sources({"name": "cl", "kind": "changelog_md", "url": self.base + "/c.md"},
                     {"name": "blog", "kind": "rss", "url": self.base + "/f.xml"})
        self.poll()
        n = len(self.items())
        self.assertEqual(n, 6)
        self.assertEqual(self.poll(60)[0], 0)
        self.assertEqual(len(self.items()), n)

    def test_html_baseline_then_change(self):
        self.serve("/p.html", "<html><body><main>one</main></body></html>", "text/html")
        self.serve("/idx.html", '<html><body><a href="/news/a">A</a></body></html>', "text/html")
        self.sources({"name": "pg", "kind": "html_diff", "url": self.base + "/p.html"},
                     {"name": "idx", "kind": "html_links", "url": self.base + "/idx.html", "prefix": "/news/"})
        self.assertEqual(self.poll()[0], 0)
        self.assertEqual(self.items(), [])
        self.serve("/p.html", "<html><body><main>two</main></body></html>", "text/html")
        self.serve("/idx.html", '<html><body><a href="/news/a">A</a><a href="/news/b">B</a></body></html>', "text/html")
        self.assertEqual(self.poll(60)[0], 2)
        self.assertEqual(sorted(i["source"] for i in self.items()), ["idx", "pg"])
        self.assertEqual(self.poll(120)[0], 0)

    def test_failures_logged_counted_and_reset(self):
        self.sources({"name": "bad", "kind": "rss", "url": self.base + "/missing.xml"},
                     {"name": "ok", "kind": "changelog_md", "url": self.base + "/c.md"})
        self.serve("/c.md", changelog(1))
        for i in range(3):
            self.assertEqual(self.poll(i * 60), (1 if i == 0 else 0, 2, 1))
        self.assertIn("poll bad: ", self.log())
        self.assertEqual([h["name"] for h in ss.health_report()], ["bad"])
        self.assertEqual(ss.health_report()[0]["failures"], 3)
        self.serve("/missing.xml", (FIX / "claude_blog_rss.xml").read_text(), "application/rss+xml")
        self.poll(300)
        self.assertEqual(ss.health_report(), [])
        h = ss.load()["health"]["bad"]
        self.assertEqual(h["failures"], 0)
        self.assertTrue(h["last_ok"])

    def test_exception_in_a_source_is_a_failure(self):
        self.sources({"name": "ok", "kind": "changelog_md", "url": self.base + "/c.md"})
        self.serve("/c.md", changelog(1))
        with mock.patch.object(ss.scout_fetch, "fetch", side_effect=RuntimeError("boom")):
            self.assertEqual(self.poll(), (0, 1, 1))
        self.assertIn("poll ok: RuntimeError: boom", self.log())

    def test_summary_line_is_printed_last(self):
        self.serve("/c.md", changelog(2))
        self.sources({"name": "cl", "kind": "changelog_md", "url": self.base + "/c.md"})
        rc, out, _ = self.cli("poll")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip().splitlines()[-1], "poll: 2 new from 1 sources, 0 failed")

    def test_off_file_skips(self):
        self.scout.mkdir(parents=True)
        (self.scout / "off").write_text("")
        self.assertEqual(self.cli("poll"), (0, "scout: off\n", ""))
        self.assertFalse((self.scout / "poll.log").exists())

    def test_plugin_skipped_count_is_logged_not_stored(self):
        (self.home / ".claude/plugins/installed_plugins.json").write_text(
            (FIX / "plugins_installed.json").read_text())
        self.sources({"name": "plugins", "kind": "plugin", "url": "~/.claude/plugins"})
        self.poll()
        self.assertIn("poll plugins: 2 without a version", self.log())
        self.assertNotIn("plugins", self.seen_state()["state"])

    def test_old_keys_are_pruned(self):
        self.serve("/c.md", changelog(1))
        self.sources({"name": "cl", "kind": "changelog_md", "url": self.base + "/c.md"})
        self.poll()
        st = self.seen_state()
        st["keys"]["oldkey"] = "2020-01-01T00:00:00Z"
        (self.scout / "seen.json").write_text(json.dumps(st))
        self.poll(60)
        self.assertNotIn("oldkey", self.seen_state()["keys"])

    def test_still_listed_key_is_not_rewritten_at_day_181(self):
        self.serve("/c.md", changelog(6))
        self.sources({"name": "cl", "kind": "changelog_md", "url": self.base + "/c.md"})
        self.poll()
        n = len(self.items())
        self.assertEqual(self.poll(100 * 86400)[0], 0)
        self.assertEqual(self.poll(181 * 86400)[0], 0)
        self.assertEqual(len(self.items()), n)

    def test_key_the_source_no_longer_lists_is_pruned_after_180_days(self):
        self.serve("/c.md", changelog(6))
        self.sources({"name": "cl", "kind": "changelog_md", "url": self.base + "/c.md"})
        self.poll()
        self.serve("/c.md", changelog(2))
        self.poll(100 * 86400)
        self.assertEqual(len(self.seen_state()["keys"]), 6)
        self.poll(181 * 86400)
        self.assertEqual(len(self.seen_state()["keys"]), 2)


def dmsg(mid, content, author="alice", uid=ALLOWED):
    return {"id": str(mid), "content": content, "timestamp": "2026-11-20T10:00:00+00:00",
            "author": {"id": uid, "username": author, "bot": False}}


class RequestTest(Base):
    def setUp(self):
        super().setUp()
        d = tc_env.discord_dir("agent-board")
        d.mkdir(parents=True)
        (d / ".env").write_text(f"DISCORD_BOT_TOKEN={TOKEN}\n")
        (d / "access.json").write_text(json.dumps({"allowFrom": [int(ALLOWED), "8"]}))
        self.d = d
        self.sources({"name": "scout", "kind": "discord_channel", "url": CHAN})
        self.serve("/blog/feed", '<?xml version="1.0"?><rss><channel></channel></rss>', "text/html")
        self.url = self.base + "/blog/feed"
        p = mock.patch.object(ss, "_HTTP_OK_HOSTS", ("127.0.0.1",))
        p.start()
        self.addCleanup(p.stop)

    def request(self, **kw):
        Handler.messages = [dmsg(200, f"source: {self.url} a good feed", **kw)]
        self.assertEqual(ss.poll(self.now)[2], 0)

    def names(self):
        return [s["name"] for s in ss.load()["sources"]]

    def test_request_gets_reply_and_is_recorded(self):
        self.request()
        self.assertEqual(len(Handler.posted), 1)
        p = Handler.posted[0]
        self.assertEqual(p["content"], "source request: 127-blog (rss) — react ✅ to add")
        self.assertEqual(p["message_reference"], {"message_id": "200"})
        r = self.seen_state()["requests"]["9001"]
        self.assertEqual((r["url"], r["why"], r["name"], r["kind"]), (self.url, "a good feed", "127-blog", "rss"))
        self.assertEqual(self.names(), ["scout"])

    def test_checkmark_from_allowed_user_adds_source_and_audits(self):
        self.request()
        Handler.reacted["9001"] = ["99", ALLOWED]
        Handler.messages = []
        ss.poll(self.now + 60)
        s = [x for x in ss.load()["sources"] if x["name"] == "127-blog"][0]
        self.assertEqual((s["kind"], s["url"], s["why"], s["builtin"]), ("rss", self.url, "a good feed", False))
        self.assertEqual(self.seen_state()["requests"], {})
        audit = [json.loads(l) for l in (self.d / "audit.jsonl").read_text().splitlines()]
        self.assertEqual([(a["user"], a["action"], a["target"], a["result"]) for a in audit],
                         [(ALLOWED, "scout-source", "127-blog", "added")])
        ss.poll(self.now + 120)
        self.assertEqual(len(Handler.posted), 1)
        self.assertEqual(self.names().count("127-blog"), 1)

    def test_no_checkmark_stays_pending_then_drops_after_14_days(self):
        self.request()
        Handler.messages = []
        ss.poll(self.now + 86400)
        self.assertEqual(self.names(), ["scout"])
        self.assertIn("9001", self.seen_state()["requests"])
        ss.poll(self.now + 15 * 86400)
        self.assertEqual(self.seen_state()["requests"], {})
        self.assertEqual(self.names(), ["scout"])

    def test_checkmark_from_user_not_in_allowfrom_is_ignored(self):
        self.request()
        Handler.reacted["9001"] = ["99"]
        Handler.messages = []
        ss.poll(self.now + 60)
        self.assertEqual(self.names(), ["scout"])
        self.assertIn("9001", self.seen_state()["requests"])
        self.assertFalse((self.d / "audit.jsonl").exists())

    def test_request_from_non_allowlisted_author_is_ignored(self):
        self.request(uid="99", author=ALLOWED)  # username equals an allowed id: only the user id counts
        self.assertEqual(Handler.posted, [])
        self.assertEqual(self.seen_state()["requests"], {})

    def test_missing_scout_channel_logged_once_per_poll(self):
        self.sources({"name": "other", "kind": "rss", "url": self.base + "/nope"})
        ss.poll(self.now)
        self.assertEqual(self.log().count("poll scout: skipped (no #scout channel set)"), 1)

    def test_http_request_to_unlisted_host_is_refused(self):
        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ()):
            self.request()
        self.assertEqual(Handler.posted, [])
        self.assertEqual(self.seen_state()["requests"], {})
        self.assertIn(f"poll scout: request {self.url} refused: url must start with https://", self.log())

    def test_pending_http_request_is_not_added_when_host_no_longer_listed(self):
        self.request()
        Handler.reacted["9001"] = [ALLOWED]
        Handler.messages = []
        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ()):
            ss.poll(self.now + 60)
        self.assertEqual(self.names(), ["scout"])
        self.assertEqual(self.seen_state()["requests"], {})

    def test_failed_reply_keeps_cursor_and_retries(self):
        Handler.fail_posts = 1
        self.request()
        self.assertEqual(self.seen_state()["requests"], {})
        self.assertNotIn("scout", self.seen_state()["state"])
        self.assertIn("reply failed", self.log())
        ss.poll(self.now + 60)  # the same message is returned again
        self.assertEqual(len(Handler.posted), 1)
        self.assertEqual(self.seen_state()["requests"]["9001"]["message_id"], "200")
        self.assertEqual(self.seen_state()["state"]["scout"], {"after": "200"})

    def test_request_to_a_private_host_is_refused_and_logged(self):
        url = "https://intra.example.com/feed"
        Handler.messages = [dmsg(200, f"source: {url} internal")]
        with mock.patch.object(ss, "_resolve", lambda host: ["10.0.0.5"]):
            ss.poll(self.now)
        self.assertEqual(Handler.posted, [])
        self.assertIn(f"poll scout: request {url} refused: private address 10.0.0.5", self.log())

    def test_kind_guess(self):
        self.serve("/a", "<html>x</html>", "application/atom+xml")
        self.serve("/b", "<?xml version='1.0'?><x/>", "text/html")
        self.serve("/c", "<feed></feed>", "text/plain")
        self.serve("/d", "<html><body>hi</body></html>", "text/html")
        self.assertEqual([ss._guess_kind(self.base + p) for p in "/a /b /c /d".split()],
                         ["rss", "rss", "rss", "html_links"])

    def test_name_is_slugged_and_deduped(self):
        self.assertEqual(ss.request_name("https://www.Example.com/Some Path/x", {"scout"}), "example-some-path")
        self.assertEqual(ss.request_name("https://blog.example.com/a", {"blog-a"}), "blog-a-2")
        self.assertEqual(ss.request_name("https://blog.example.com/", set()), "blog")


HOME_CHAN = "5555555555555555"   # any channel that is not the #scout channel


def feed(*titles):
    return '<?xml version="1.0"?><rss><channel>' + "".join(
        f"<item><title>{t}</title><link>https://e.example/{i}</link></item>" for i, t in enumerate(titles)) + "</channel></rss>"


def block(*lines):
    return "```\n" + "\n".join(lines) + "\n```"


class InstantAddTest(Base):
    """`source: <url> [name]` in #scout and /source as bridge events: the prompt at once, the add on the check mark (plan Task 5)."""

    def setUp(self):
        super().setUp()
        d = tc_env.discord_dir("agent-board")
        d.mkdir(parents=True)
        (d / ".env").write_text(f"DISCORD_BOT_TOKEN={TOKEN}\n")
        (d / "access.json").write_text(json.dumps({"allowFrom": [int(ALLOWED)]}))
        self.d = d
        self.sources({"name": "scout", "kind": "discord_channel", "url": CHAN})
        self.serve("/blog/feed", feed("T1", "T2", "T3", "T4", "T5"), "application/rss+xml")
        self.url = self.base + "/blog/feed"

    def msg_event(self, text=None, mid="200", chan=CHAN):
        return ss.discord_request({"type": "source", "via": "message", "text": text or f"source: {self.url}", "message_id": mid,
                                   "channel_id": chan, "user": ALLOWED, "ts": 1}, self.now)

    def slash_event(self, url=None, name="", mid="777", chan=HOME_CHAN, iid="I1"):
        return ss.discord_request({"type": "source", "via": "slash", "url": url or self.url, "name": name, "iid": iid,
                                   "message_id": mid, "channel_id": chan, "user": ALLOWED, "ts": 1}, self.now)

    def names(self):
        return [s["name"] for s in ss.load()["sources"]]

    def pending(self):
        return self.seen_state()["requests"] if (self.scout / "seen.json").exists() else {}

    def prompts(self):
        p = self.d / "scout-prompts.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def ops(self):
        return [json.loads(f.read_text()) for f in sorted((self.d / "outbox").glob("*.json"))] if (self.d / "outbox").exists() else []

    def fake_fetch(self, titles=("A", "B", "C", "D"), exc=None):
        calls = []

        def fetch(src, state, installed_version=None):
            calls.append(src["name"])
            if exc:
                raise exc
            return [{"title": t, "url": "https://e.example/" + t} for t in titles], {}
        p = mock.patch.object(ss.scout_fetch, "fetch", fetch)
        p.start()
        self.addCleanup(p.stop)
        return calls

    # ---- parsing (A5)

    def test_request_tail_one_name_token_is_the_name_else_the_why(self):
        self.assertEqual(ss.request_tail("my-feed.2"), ("my-feed.2", ""))
        self.assertEqual(ss.request_tail("a good feed"), (None, "a good feed"))
        self.assertEqual(ss.request_tail("Interesting"), (None, "Interesting"))   # not a NAME_RE token
        self.assertEqual(ss.request_tail("x" * 41), (None, "x" * 41))
        self.assertEqual(ss.request_tail(""), (None, ""))

    # ---- the prompt

    def test_source_message_in_scout_gets_the_prompt_at_once(self):
        self.assertEqual(self.msg_event(), "prompted")
        self.assertEqual(len(Handler.posted), 1)
        p = Handler.posted[0]
        self.assertEqual(p["content"], block(f"127-blog · rss · {self.url}") + "\nreact ✅ to add")
        self.assertEqual(p["message_reference"], {"message_id": "200"})
        self.assertEqual(p["allowed_mentions"], {"parse": []})
        r = self.pending()["9001"]
        self.assertEqual((r["url"], r["name"], r["kind"], r["why"], r["channel"], r["message_id"], r["via"]),
                         (self.url, "127-blog", "rss", "", CHAN, "200", "message"))
        self.assertEqual(self.prompts(), {"9001": CHAN})   # what the bridge reads to forward a check mark from any channel
        self.assertTrue(ss.is_pending("9001"))
        self.assertFalse(ss.is_pending("200"))
        self.assertEqual(self.names(), ["scout"])

    def test_name_token_names_the_source_and_longer_text_is_the_why(self):
        self.msg_event(f"source: {self.url} myfeed", mid="200")
        self.msg_event(f"source: {self.url} worth a look", mid="201")
        a, b = self.pending()["9001"], self.pending()["9002"]
        self.assertEqual((a["name"], a["why"]), ("myfeed", ""))
        self.assertEqual((b["name"], b["why"]), ("127-blog", "worth a look"))
        self.assertIn("myfeed · rss · ", Handler.posted[0]["content"])

    def test_source_message_outside_scout_is_ignored(self):
        self.assertEqual(self.msg_event(chan=HOME_CHAN), "ignored")
        self.assertEqual(self.msg_event(text="sources: nothing to see"), "ignored")
        self.assertEqual((Handler.posted, self.pending(), self.prompts()), ([], {}, {}))

    def test_refused_url_gets_refused_and_no_prompt(self):   # mutation: record the request before the check -> a later check mark adds it
        with mock.patch.object(ss, "_resolve", lambda host: ["10.0.0.5"]):
            self.assertEqual(self.msg_event("source: https://intra.example.com/feed"), "refused")
        self.assertEqual(Handler.posted[0]["content"], block("refused: private address 10.0.0.5"))
        self.assertEqual(Handler.posted[0]["message_reference"], {"message_id": "200"})
        self.assertEqual((self.pending(), self.prompts()), ({}, {}))
        calls = self.fake_fetch()
        self.assertIsNone(ss.discord_confirm("9001", ALLOWED, self.now + 5))   # a check mark on the refusal reply
        self.assertEqual((self.names(), calls, Handler.edited), (["scout"], [], []))

    def test_slash_prompt_goes_through_the_bridge_outbox(self):
        self.assertEqual(self.slash_event(name="mine"), "prompted")
        self.assertEqual(Handler.posted, [])   # no REST post outside #scout
        self.assertEqual(self.ops(), [{"op": "ireply", "iid": "I1", "content": block(f"mine · rss · {self.url}") + "\nreact ✅ to add"}])
        r = self.pending()["777"]
        self.assertEqual((r["name"], r["kind"], r["channel"], r["via"], r["iid"]), ("mine", "rss", HOME_CHAN, "slash", "I1"))
        self.assertEqual(self.prompts(), {"777": HOME_CHAN})

    def test_slash_bad_name_and_refused_url(self):
        self.assertEqual(self.slash_event(name="Not A Name"), "refused")
        with mock.patch.object(ss, "_resolve", lambda host: ["169.254.169.254"]):
            self.assertEqual(self.slash_event(url="https://meta.example.com/x", mid="778", iid="I2"), "refused")
        ops = self.ops()
        self.assertEqual([o["iid"] for o in ops], ["I1", "I2"])
        self.assertTrue(ops[0]["content"].startswith("```\nrefused: bad name"), ops[0])
        self.assertEqual(ops[1]["content"], block("refused: link-local address 169.254.169.254"))
        self.assertEqual((self.pending(), self.prompts()), ({}, {}))

    def test_github_url_shows_the_detected_kind_and_url(self):
        self.slash_event(url="https://github.com/anthropics/claude-code")
        self.assertEqual(self.ops()[0]["content"],
                         block("github-anthropics · github_releases · https://api.github.com/repos/anthropics/claude-code/releases") + "\nreact ✅ to add")

    def test_the_same_message_is_answered_once_by_event_and_poll(self):   # mutation: no request_msgs mark -> the poll replies again
        self.assertEqual(self.msg_event(), "prompted")
        self.assertEqual(self.msg_event(), "duplicate")
        self.fake_fetch()
        self.assertEqual(ss.discord_confirm("9001", ALLOWED, self.now + 5), ("127-blog", "added"))
        Handler.messages = [dmsg(200, f"source: {self.url}")]   # the daily poll reads the same message later
        ss.poll(self.now + 60)
        self.assertEqual(len(Handler.posted), 1)
        self.assertEqual(self.pending(), {})

    def test_a_request_the_poll_already_answered_is_a_duplicate_event(self):
        Handler.messages = [dmsg(200, f"source: {self.url}")]
        ss.poll(self.now)
        self.assertEqual(len(Handler.posted), 1)
        self.assertEqual(self.prompts(), {"9001": CHAN})   # the poll's own prompt takes an instant check mark too
        self.assertEqual(self.msg_event(), "duplicate")
        self.assertEqual(len(Handler.posted), 1)

    def test_failed_reply_leaves_the_request_to_the_poll(self):
        Handler.fail_posts = 1
        self.assertEqual(self.msg_event(), "reply failed")
        self.assertEqual((self.pending(), self.prompts()), ({}, {}))
        Handler.messages = [dmsg(200, f"source: {self.url}")]
        ss.poll(self.now + 60)
        self.assertEqual(self.pending()["9001"]["message_id"], "200")

    def test_unexpected_detect_error_answers_nothing_and_leaves_the_request_to_the_poll(self):
        with mock.patch.object(ss, "detect", side_effect=RuntimeError("boom")):
            self.assertEqual(self.msg_event(), "error")
        self.assertEqual((Handler.posted, self.pending(), self.seen_state()["request_msgs"]), ([], {}, {}))
        self.assertIn("scout source: request", self.log())
        self.assertEqual(self.msg_event(), "prompted")   # not marked as answered

    def test_long_url_is_cut_to_the_discord_limit_inside_the_fence(self):
        url = "https://e.example/" + "a" * 3000
        self.slash_event(url=url)
        c = self.ops()[0]["content"]
        self.assertLessEqual(len(c), 2000)
        self.assertTrue(c.endswith("\n```\nreact ✅ to add"), c[-40:])
        self.assertEqual(self.pending()["777"]["url"], url)   # only the display is cut

    # ---- the check mark

    def test_checkmark_adds_once_fetches_once_and_shows_three_titles(self):
        # mutation: drop the pending-record removal in _confirm_locked -> the second check mark adds 127-blog-2
        self.msg_event()
        calls = self.fake_fetch()
        with mock.patch.object(ss, "add_url", wraps=ss.add_url) as add:
            self.assertEqual(ss.discord_confirm("9001", ALLOWED, self.now + 5), ("127-blog", "added"))
        self.assertEqual(add.call_count, 1)   # the one add path
        self.assertEqual(add.call_args.args[:3], (self.url, "127-blog", "rss"))
        self.assertEqual(calls, ["127-blog"])
        self.assertEqual(Handler.edited, [("9001", {"content": block("added: 127-blog (rss)", "A", "B", "C"), "allowed_mentions": {"parse": []}})])
        row = [s for s in ss.load()["sources"] if s["name"] == "127-blog"][0]
        self.assertEqual((row["kind"], row["url"], row["builtin"], row["added"]), ("rss", self.url, False, ss._iso(self.now + 5)))
        self.assertEqual((self.pending(), self.prompts()), ({}, {}))
        self.assertIsNone(ss.discord_confirm("9001", ALLOWED, self.now + 6))   # a second check mark
        self.assertEqual(calls, ["127-blog"])
        Handler.reacted["9001"] = [ALLOWED]
        Handler.messages = []
        ss.poll(self.now + 60)   # and the next poll's _check_requests
        self.assertEqual([n for n in self.names() if n.startswith("127-blog")], ["127-blog"])
        self.assertEqual(calls, ["127-blog", "scout", "127-blog"])   # only the poll's own fetch of each source
        self.assertEqual(len(Handler.edited), 1)

    def test_checkmark_with_the_real_fetcher_shows_the_feeds_first_three_titles(self):
        self.msg_event()
        self.assertEqual(ss.discord_confirm("9001", ALLOWED, self.now + 5), ("127-blog", "added"))
        self.assertEqual(Handler.edited[0][1]["content"], block("added: 127-blog (rss)", "T1", "T2", "T3"))
        self.assertEqual([p for m, p in Handler.seen if p == "/blog/feed"], ["/blog/feed"] * 2)   # detect, then the one first fetch

    def test_first_fetch_failure_keeps_the_source_and_its_health(self):
        self.sources({"name": "scout", "kind": "discord_channel", "url": CHAN}, health={"scout": {"failures": 1, "last_error": "x", "last_ok": None}})
        self.msg_event()
        calls = self.fake_fetch(exc=ss.scout_fetch.FetchError("HTTP 500 for " + self.url))
        self.assertEqual(ss.discord_confirm("9001", ALLOWED, self.now + 5), ("127-blog", "added"))
        self.assertEqual(calls, ["127-blog"])
        self.assertEqual(Handler.edited[0][1]["content"], block("added, first fetch failed: HTTP 500 for " + self.url))
        self.assertIn("127-blog", self.names())
        self.assertEqual(ss.load()["health"], {"scout": {"failures": 1, "last_error": "x", "last_ok": None}})
        self.assertEqual(ss.health_report(), [])

    def test_first_fetch_writes_no_poll_state(self):   # the next poll still treats the source as new (first-poll cap)
        self.msg_event()
        before = (self.scout / "seen.json").read_text()
        self.fake_fetch()
        ss.discord_confirm("9001", ALLOWED, self.now + 5)
        seen = self.seen_state()
        self.assertEqual((seen.get("keys"), seen.get("sources"), seen.get("state")), ({}, {}, {}))
        self.assertFalse((self.scout / "items.jsonl").exists())
        self.assertNotEqual(before, (self.scout / "seen.json").read_text())   # only the pending request went

    def test_duplicate_name_at_checkmark_time_gets_the_next_free_suffix(self):
        self.msg_event(f"source: {self.url} myfeed")
        ss.add_source("myfeed", "rss", self.base + "/other")   # taken between the prompt and the check mark
        ss.add_source("myfeed-2", "rss", self.base + "/other2")
        self.fake_fetch()
        self.assertEqual(ss.discord_confirm("9001", ALLOWED, self.now + 5), ("myfeed-3", "added"))
        self.assertEqual(Handler.edited[0][1]["content"].splitlines()[1], "added: myfeed-3 (rss)")
        self.assertEqual(ss._free_name("x" * 40, {"x" * 40}), "x" * 38 + "-2")   # the suffix still fits NAME_RE
        self.assertTrue(ss.NAME_RE.match(ss._free_name("x" * 40, {"x" * 40})))

    def test_url_refused_at_checkmark_time_is_not_added(self):
        self.msg_event()
        calls = self.fake_fetch()
        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ()):
            self.assertEqual(ss.discord_confirm("9001", ALLOWED, self.now + 5), ("127-blog", "refused"))
        self.assertEqual(Handler.edited[0][1]["content"], block("refused: url must start with https://"))
        self.assertEqual((self.names(), calls, self.pending(), self.prompts()), (["scout"], [], {}, {}))

    def test_slash_prompt_outside_scout_is_edited_through_the_outbox(self):
        self.slash_event()
        self.fake_fetch()
        self.assertEqual(ss.discord_confirm("777", ALLOWED, self.now + 5), ("127-blog", "added"))
        self.assertEqual((Handler.posted, Handler.edited), ([], []))   # no REST call outside #scout
        self.assertEqual(self.ops()[1], {"op": "ireply", "iid": "I1", "content": block("added: 127-blog (rss)", "A", "B", "C")})

    def test_slash_prompt_inside_scout_is_edited_in_place(self):
        self.slash_event(chan=CHAN)
        self.fake_fetch()
        ss.discord_confirm("777", ALLOWED, self.now + 5)
        self.assertEqual([m for m, _ in Handler.edited], ["777"])
        self.assertEqual(len(self.ops()), 1)   # only the prompt went through the outbox

    def test_titles_are_data_fenced_one_line_each_and_cut(self):
        self.msg_event()
        self.fake_fetch(titles=("```\n@everyone [x](https://evil.example)", "b\n  b", "c" * 5000, "d"))
        ss.discord_confirm("9001", ALLOWED, self.now + 5)
        body = Handler.edited[0][1]
        c = body["content"]
        self.assertEqual(body["allowed_mentions"], {"parse": []})
        self.assertLessEqual(len(c), 2000)
        self.assertEqual(c.count("```"), 2)   # only the block's own fence: the title's backticks are broken up
        lines = c.splitlines()
        self.assertEqual((lines[0], lines[1], lines[-1], len(lines)), ("```", "added: 127-blog (rss)", "```", 6))
        self.assertEqual(lines[3], "b b")
        self.assertNotIn("d", lines[4])   # exactly three titles

    def test_failed_edit_is_logged_and_the_source_stays(self):
        self.msg_event()
        self.fake_fetch()
        Handler.fail_edits = 1
        self.assertEqual(ss.discord_confirm("9001", ALLOWED, self.now + 5), ("127-blog", "added"))
        self.assertIn("127-blog", self.names())
        self.assertIn("scout source: edit 9001 failed", self.log())

    def test_token_is_in_no_reply_edit_or_log(self):
        self.msg_event()
        self.fake_fetch(exc=ss.scout_fetch.FetchError("HTTP 401 for " + self.url))
        Handler.fail_edits = 1
        ss.discord_confirm("9001", ALLOWED, self.now + 5)
        self.slash_event(mid="778")
        blob = json.dumps([Handler.posted, Handler.edited, self.ops()]) + self.log() + (self.scout / "seen.json").read_text()
        self.assertEqual(blob.count(TOKEN), 0)
        self.assertEqual(blob.count("Authorization"), 0)

    # ---- the poll fallback (a check mark the bridge missed)

    def test_poll_checkmark_goes_through_the_one_add_path(self):
        # mutation: _check_requests builds its own row again -> add_url is never called
        Handler.messages = [dmsg(200, f"source: {self.url} myfeed")]
        ss.poll(self.now)
        self.assertEqual(Handler.posted[0]["content"], "source request: myfeed (rss) — react ✅ to add")
        Handler.reacted["9001"] = [ALLOWED]
        Handler.messages = []
        with mock.patch.object(ss, "add_url", wraps=ss.add_url) as add:
            ss.poll(self.now + 60)
        self.assertEqual(add.call_count, 1)
        self.assertEqual(add.call_args.args[:3], (self.url, "myfeed", "rss"))
        self.assertEqual(self.names().count("myfeed"), 1)
        self.assertEqual((self.pending(), self.prompts()), ({}, {}))
        self.assertIsNone(ss.discord_confirm("9001", ALLOWED, self.now + 90))   # the bridge's event for the same check mark, late
        self.assertEqual(self.names().count("myfeed") + self.names().count("myfeed-2"), 1)

    def test_bare_source_request_is_answered_by_the_poll(self):
        Handler.messages = [dmsg(200, f"source: {self.url}")]
        ss.poll(self.now)
        self.assertEqual(Handler.posted[0]["content"], "source request: 127-blog (rss) — react ✅ to add")

    def test_handled_message_marks_age_out(self):
        self.msg_event()
        self.assertIn("200", self.seen_state()["request_msgs"])
        Handler.messages = []
        ss.poll(self.now + 15 * 86400)
        self.assertEqual(self.seen_state()["request_msgs"], {})


class DetectTest(Base):
    """detect(): one row of the spec's table per test, from inline HTML served by the local server."""

    def test_github_repo_and_releases_need_no_fetch(self):
        for url in ("https://github.com/anthropics/claude-code", "https://github.com/anthropics/claude-code/releases",
                    "https://github.com/anthropics/claude-code.git"):
            d = ss.detect(url, taken=set())
            self.assertEqual((d["kind"], d["url"]), ("github_releases", "https://api.github.com/repos/anthropics/claude-code/releases"), url)
        self.assertEqual(Handler.seen, [])

    def test_npm_package_page(self):
        d = ss.detect("https://www.npmjs.com/package/@anthropic-ai/claude-code", taken=set())
        self.assertEqual((d["kind"], d["url"]), ("npm", "https://registry.npmjs.org/@anthropic-ai/claude-code"))
        d = ss.detect("https://www.npmjs.com/package/left-pad", taken=set())
        self.assertEqual(d["url"], "https://registry.npmjs.org/left-pad")

    def test_raw_changelog(self):
        url = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
        self.assertEqual(ss.detect(url, taken=set())["kind"], "changelog_md")
        self.assertEqual(ss.detect(url, taken=set())["url"], url)
        self.assertEqual(Handler.seen, [])

    def test_page_with_a_feed_link_gives_the_absolute_feed_url(self):
        self.serve("/blog", '<html><head><link rel="stylesheet" href="/s.css">'
                            '<link rel="alternate" type="application/rss+xml" href="/blog/feed.xml"></head></html>', "text/html")
        self.serve("/news", '<html><head><link rel="Alternate home" type="application/atom+xml" '
                            'href="https://feeds.example.com/atom"></head></html>', "text/html")
        self.assertEqual(ss.detect(self.base + "/blog", taken=set())[ "url"], self.base + "/blog/feed.xml")
        self.assertEqual(ss.detect(self.base + "/blog", taken=set())["kind"], "rss")
        self.assertEqual(ss.detect(self.base + "/news", taken=set())["url"], "https://feeds.example.com/atom")

    def test_feed_link_to_a_private_address_is_refused(self):
        # mutation: drop the check of the feed URL -> an rss row pointing at 10.0.0.5
        self.serve("/blog", '<html><head><link rel="alternate" type="application/rss+xml" href="https://10.0.0.5/f"></head></html>', "text/html")
        with self.assertRaises(ss.Refusal) as cm:
            ss.detect(self.base + "/blog", taken=set())
        self.assertEqual(str(cm.exception), "private address 10.0.0.5")

    def test_url_that_is_itself_a_feed(self):
        self.serve("/a", "<html>x</html>", "application/atom+xml")
        self.serve("/b", "<?xml version='1.0'?><rss/>", "text/html")
        self.serve("/c", "<feed></feed>", "text/plain")
        for p in ("/a", "/b", "/c"):
            self.assertEqual((ss.detect(self.base + p, taken=set())["kind"], ss.detect(self.base + p, taken=set())["url"]),
                             ("rss", self.base + p), p)

    def test_anything_else_is_html_links_with_its_path_as_prefix(self):
        self.serve("/docs/changes", "<html><body><a href='/docs/changes/1'>one</a></body></html>", "text/html")
        d = ss.detect(self.base + "/docs/changes", taken=set())
        self.assertEqual((d["kind"], d["url"], d["prefix"]), ("html_links", self.base + "/docs/changes", "/docs/changes/"))

    def test_failed_fetch_falls_back_to_html_links(self):
        d = ss.detect(self.base + "/missing/page", taken=set())   # 404
        self.assertEqual((d["kind"], d["prefix"]), ("html_links", "/missing/page/"))

    def test_refused_url_and_redirect_hop(self):
        with self.assertRaises(ss.Refusal):
            ss.detect("https://10.0.0.5/x", taken=set())
        Handler.routes["/go"] = (200, b"", "text/html")
        import scout_fetch
        with mock.patch.object(scout_fetch, "get", side_effect=scout_fetch.Refused("refused: link-local address 169.254.169.254")):
            with self.assertRaises(ss.Refusal) as cm:
                ss.detect(self.base + "/go", taken=set())
        self.assertEqual(str(cm.exception), "link-local address 169.254.169.254")

    def test_one_fetch_with_a_10_second_timeout(self):
        import scout_fetch
        with mock.patch.object(scout_fetch, "get", return_value=(200, b"<html></html>", "text/html")) as g:
            ss.detect(self.base + "/x", taken=set())
        self.assertEqual(g.call_count, 1)
        self.assertEqual(g.call_args.kwargs.get("timeout"), 10)

    def test_name_default_and_duplicates(self):
        self.assertEqual(ss.detect("https://github.com/Anthropics/claude-code", taken=set())["name"], "github-anthropics")
        self.assertEqual(ss.detect("https://github.com/anthropics/x", taken={"github-anthropics"})["name"], "github-anthropics-2")
        self.assertEqual(ss.detect("https://github.com/anthropics/x", taken={"github-anthropics", "github-anthropics-2"})["name"],
                         "github-anthropics-3")
        self.sources({"name": "github-anthropics", "kind": "rss", "url": "https://a.example/f"})
        self.assertEqual(ss.detect("https://github.com/anthropics/y")["name"], "github-anthropics-2")   # taken read from sources.json

    def test_cli_add_without_kind_detects_it(self):
        import scout_fetch   # add_source takes https only, so the fetch is faked rather than served over http
        with mock.patch.object(scout_fetch, "get", return_value=(200, b"<?xml version='1.0'?><rss/>", "application/rss+xml")):
            rc, out, _ = self.cli("source", "add", "feed1", "--url", "https://feeds.example.com/f.xml")
        self.assertEqual((rc, out.strip()), (0, "added feed1 (rss)"))
        rc, out, _ = self.cli("source", "add", "cc", "--url", "https://github.com/anthropics/claude-code")
        self.assertEqual((rc, out.strip()), (0, "added cc (github_releases)"))
        row = [s for s in ss.load()["sources"] if s["name"] == "cc"][0]
        self.assertEqual(row["url"], "https://api.github.com/repos/anthropics/claude-code/releases")
        rc, _, err = self.cli("source", "add", "bad", "--url", "https://10.0.0.5/")
        self.assertEqual((rc, err.strip()), (2, "scout: private address 10.0.0.5"))


class UrlCheckTest(unittest.TestCase):
    """check_url_safe: each refused address class through a fake resolver, literal IP hosts, one real resolution."""

    def check(self, url, addrs=()):
        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ()), mock.patch.object(ss, "_resolve", lambda host: list(addrs)):
            ss.check_url_safe(url)

    def refused(self, url, addrs=()):
        with self.assertRaises(ss.Refusal) as cm:
            self.check(url, addrs)
        return str(cm.exception)

    def test_each_refused_class_through_the_resolver(self):
        cases = [("169.254.169.254", "link-local"), ("10.0.0.5", "private"), ("172.16.3.4", "private"),
                 ("192.168.1.1", "private"), ("127.0.0.1", "loopback"), ("127.8.9.10", "loopback"), ("::1", "loopback"),
                 ("fc00::1", "private"), ("fd12::1", "private"), ("fe80::1", "link-local"), ("224.0.0.1", "multicast"),
                 ("ff02::1", "multicast"), ("0.0.0.0", "unspecified"), ("::", "unspecified"), ("100.64.0.1", "non-global"),
                 ("::ffff:10.0.0.5", "private"), ("::ffff:169.254.169.254", "link-local")]
        for ip, cls in cases:
            self.assertEqual(self.refused("https://feeds.example.com/x", [ip]), f"{cls} address {ip}", ip)
        self.assertRaises(ss.Refusal, self.check, "https://feeds.example.com/x", ["240.0.0.1"])   # reserved

    def test_one_bad_address_among_global_ones_refuses(self):
        # mutation: test only the first resolved address -> passes
        self.assertEqual(self.refused("https://a.example.com/", ["93.184.215.14", "10.1.2.3"]), "private address 10.1.2.3")

    def test_literal_ip_hosts(self):
        for url, why in (("https://169.254.169.254/latest/meta-data", "link-local address 169.254.169.254"),
                         ("https://[::1]:8443/x", "loopback address ::1"),
                         ("https://[::ffff:127.0.0.1]/", "loopback address ::ffff:127.0.0.1"),
                         ("https://10.0.0.5/feed", "private address 10.0.0.5")):
            self.assertEqual(self.refused(url, ["93.184.215.14"]), why, url)   # the resolver is not asked for a literal

    def test_global_addresses_pass(self):
        self.check("https://a.example.com/feed", ["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"])
        self.check("https://8.8.8.8/x")
        self.check("https://a.example.com/x", ["::ffff:8.8.8.8"])

    def test_scheme_and_resolution_failures(self):
        self.assertEqual(self.refused("http://a.example.com/", ["93.184.215.14"]), "url must start with https://")
        self.assertEqual(self.refused("ftp://a.example.com/", ["93.184.215.14"]), "url must start with https://")
        self.assertEqual(self.refused("https://empty.example.com/", []), "host does not resolve: empty.example.com")

        def boom(host):
            raise socket.gaierror(8, "nodename nor servname provided")
        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ()), mock.patch.object(ss, "_resolve", boom):
            with self.assertRaises(ss.Refusal) as cm:
                ss.check_url_safe("https://nothere.invalid/")
        self.assertEqual(str(cm.exception), "host does not resolve: nothere.invalid")

    def test_real_resolution_of_localhost_is_refused(self):
        # the real resolver (no fake): localhost and the decimal form of 127.0.0.1 both resolve to loopback
        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ()):
            for url in ("https://localhost/x", "https://2130706433/x"):
                with self.assertRaises(ss.Refusal) as cm:
                    ss.check_url_safe(url)
                self.assertTrue(str(cm.exception).startswith("loopback address "), (url, str(cm.exception)))

    def test_http_ok_hosts_seam_skips_scheme_and_address(self):
        with mock.patch.object(ss, "_HTTP_OK_HOSTS", ("127.0.0.1",)):
            ss.check_url_safe("http://127.0.0.1:8000/x")
        self.assertEqual(ss._HTTP_OK_HOSTS, ())   # empty in production


if __name__ == "__main__":
    unittest.main()
