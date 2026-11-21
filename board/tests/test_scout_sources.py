"""scout_sources: sources.json, the sources CLI, the daily poll, #scout requests. Local HTTP server only (127.0.0.1)."""
import contextlib
import io
import json
import os
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
            return self._send(404, b"{}")
        if path in Handler.routes:
            status, body, ctype = Handler.routes[path]
            return self._send(status, body, ctype)
        self._send(404, b"nope", "text/plain")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


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
        Handler.fail_posts = 0
        self.now = 1_800_000_000.0

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


if __name__ == "__main__":
    unittest.main()
