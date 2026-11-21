"""scout_fetch plugin and discord_channel kinds: temp HOME plugin trees and a local fake Discord API (127.0.0.1)."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scout_fetch as sf  # noqa: E402
import tc_env  # noqa: E402

FIX = HERE / "fixtures" / "scout"
TOKEN = "tok-SECRET-123"
CHAN = "1234567890"


class Handler(BaseHTTPRequestHandler):
    routes = {}      # path -> (status, body bytes, content type)
    messages = []    # discord messages served for CHAN
    raw_messages = None  # bytes: served verbatim as the messages body
    seen = []        # (method, path+query, headers, body)

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
        Handler.seen.append((method, self.path, dict(self.headers), data))
        u = urlsplit(self.path)
        if u.path.startswith("/api/"):
            if self.headers.get("Authorization") != f"Bot {TOKEN}":
                return self._send(401, b'{"message": "401: Unauthorized"}')
            parts = u.path.split("/")  # '', api, channels, id, messages, [mid, reactions, emoji]
            if parts[3] != CHAN:
                return self._send(404, b'{"message": "Unknown Channel"}')
            if Handler.raw_messages is not None and method == "GET" and len(parts) == 5:
                return self._send(200, Handler.raw_messages)
            if method == "GET" and len(parts) == 5 and parts[4] == "messages":
                msgs = list(Handler.messages)
                after = parse_qs(u.query).get("after")
                if after:
                    msgs = [m for m in msgs if int(m["id"]) > int(after[0])]
                return self._send(200, json.dumps(msgs).encode())
            if method == "POST" and len(parts) == 5:
                return self._send(200, json.dumps({"id": "999"}).encode())
            if method == "GET" and len(parts) == 8 and parts[6] == "reactions":
                return self._send(200, json.dumps([{"id": "42"}, {"id": "43"}]).encode())
            return self._send(404, b"{}")
        if u.path in Handler.routes:
            return self._send(Handler.routes[u.path][0], Handler.routes[u.path][1], Handler.routes[u.path][2])
        f = FIX / u.path.lstrip("/")
        if u.path.startswith("/raw/") and f.name == "marketplace.json":
            return self._send(404, b"{}")
        self._send(404, b"nope", "text/plain")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


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
        self.home = Path(self.tmp.name) / "home"
        (self.home / ".claude/plugins").mkdir(parents=True)
        env = {"TC_SCOUT_DIR": self.tmp.name + "/scout", "TC_STATE": self.tmp.name + "/state", "HOME": str(self.home),
               "TC_SCOUT_RAW_BASE": self.base + "/raw", "TC_SCOUT_DISCORD_API": self.base + "/api"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        Handler.routes, Handler.messages, Handler.seen, Handler.raw_messages = {}, [], [], None


class PluginTest(Base):
    def setUp(self):
        super().setUp()
        self.installed = json.loads((FIX / "plugins_installed.json").read_text())
        self.known = json.loads((FIX / "plugins_known_marketplaces.json").read_text())
        self.remote = json.loads((FIX / "sp_remote.json").read_text())
        self.write()

    def write(self, remote=None):
        d = self.home / ".claude/plugins"
        (d / "installed_plugins.json").write_text(json.dumps(self.installed))
        (d / "known_marketplaces.json").write_text(json.dumps(self.known))
        Handler.routes["/raw/pcvelz/superpowers/main/.claude-plugin/marketplace.json"] = (
            200, json.dumps(remote or self.remote).encode(), "application/json")

    def run_plugin(self):
        return sf.fetch({"name": "plugins", "kind": "plugin", "url": ""}, {})

    def sp(self):
        return self.installed["plugins"]["superpowers-extended-cc@superpowers-extended-cc-marketplace"][0]

    def test_newer_gives_item_and_sha_plugin_is_skipped(self):
        items, state = self.run_plugin()
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["title"], "superpowers-extended-cc 6.5.3-dev → 7.1.2")
        self.assertEqual(it["version"], "7.1.2")
        self.assertEqual(set(it), {"title", "url", "version", "published", "excerpt", "content_hash"})
        self.assertIn("pcvelz/superpowers", it["url"])
        # gitlab@anthropic-plugin-directory: sha version and marketplace absent from known_marketplaces
        self.assertEqual(state, {"skipped_no_version": 1})

    def test_equal_and_older_give_no_item(self):
        for v in ("7.1.2", "7.2.0", "10.0.0"):
            self.sp()["version"] = v
            self.write()
            items, state = self.run_plugin()
            self.assertEqual(items, [], v)
            self.assertEqual(state, {"skipped_no_version": 1})

    def test_version_compare_suffix_sorts_before_release(self):
        k = sf.version_key
        self.assertLess(k("6.5.3-dev"), k("6.5.3"))
        self.assertLess(k("6.5.3"), k("7.1.2"))
        self.assertLess(k("6.5"), k("6.5.1"))
        self.assertEqual(k("6.5"), k("6.5.0"))
        self.assertLess(k("2.9.0"), k("2.10.0"))
        self.assertIsNone(k("73c8cf3ea7e2-4d8728a6"))
        self.assertIsNone(k("abc"))
        self.sp()["version"] = "7.1.2-dev"
        self.write()
        items, _ = self.run_plugin()  # 7.1.2-dev < 7.1.2
        self.assertEqual([i["version"] for i in items], ["7.1.2"])

    def test_marketplace_entry_without_version_counts_as_skipped(self):
        del self.remote["plugins"][0]["version"]
        self.write(self.remote)
        items, state = self.run_plugin()
        self.assertEqual(items, [])
        self.assertEqual(state, {"skipped_no_version": 2})

    def test_unknown_marketplace_and_sha_version_skipped(self):
        self.sp()["version"] = "cb12f4fdfcd3"
        self.write()
        items, state = self.run_plugin()
        self.assertEqual(items, [])
        self.assertEqual(state, {"skipped_no_version": 2})

    def test_remote_fetched_once_per_marketplace(self):
        self.installed["plugins"]["second@superpowers-extended-cc-marketplace"] = [{"version": "1.0.0"}]
        self.remote["plugins"].append({"name": "second", "version": "1.1.0"})
        self.write(self.remote)
        items, _ = self.run_plugin()
        self.assertEqual(sorted(i["version"] for i in items), ["1.1.0", "7.1.2"])
        raw = [s for s in Handler.seen if s[1].startswith("/raw/")]
        self.assertEqual(len(raw), 1)

    def test_broken(self):
        # remote 404 for every marketplace -> FetchError
        Handler.routes.clear()
        with self.assertRaises(sf.FetchError):
            self.run_plugin()
        # invalid JSON remote
        Handler.routes["/raw/pcvelz/superpowers/main/.claude-plugin/marketplace.json"] = (200, b"{nope", "application/json")
        with self.assertRaises(sf.FetchError):
            self.run_plugin()
        # no installed_plugins.json
        (self.home / ".claude/plugins/installed_plugins.json").unlink()
        with self.assertRaises(sf.FetchError):
            self.run_plugin()
        (self.home / ".claude/plugins/installed_plugins.json").write_text("not json")
        with self.assertRaises(sf.FetchError):
            self.run_plugin()


def msg(mid, content, ts="2026-11-20T10:00:00.123000+00:00", author="alice", bot=False):
    return {"id": str(mid), "content": content, "timestamp": ts, "author": {"id": "7", "username": author, "bot": bot}}


class DiscordTest(Base):
    def setUp(self):
        super().setUp()
        d = tc_env.discord_dir("agent-board")
        d.mkdir(parents=True)
        (d / ".env").write_text(f"OTHER=1\nDISCORD_BOT_TOKEN={TOKEN}\n")
        (d / "access.json").write_text(json.dumps({"allowFrom": [7]}))   # msg() authors are id "7"
        import scout_sources
        p = mock.patch.object(scout_sources, "_HTTP_OK_HOSTS", ("127.0.0.1",))   # the local fake server is http
        p.start()
        self.addCleanup(p.stop)
        self.src = {"name": "scout-channel", "kind": "discord_channel", "url": CHAN}
        Handler.routes["/p/a.html"] = (200, b"<html><head><title> Page  A </title></head><body><nav>menu</nav><main>Main  text of A</main></body></html>", "text/html")
        Handler.routes["/p/b.html"] = (200, b"<html><body>Body B</body></html>", "text/html; charset=utf-8")

    def url(self, p):
        return self.base + p

    def test_page_items_and_state_after(self):
        Handler.messages = [msg(105, f"look {self.url('/p/a.html')}."), msg(104, "just chatting"),
                            msg(103, f"two <{self.url('/p/b.html')}> and {self.url('/p/missing.html')}", ts="2026-11-20T12:00:00+02:00")]
        items, state = sf.fetch(self.src, {})
        self.assertEqual(state, {"after": "105"})
        self.assertEqual([i["url"] for i in items], [self.url("/p/a.html"), self.url("/p/b.html")])  # missing url skipped
        a, b = items
        self.assertEqual(a["title"], "Page A")
        self.assertEqual(a["excerpt"], "Main text of A")
        self.assertEqual(a["published"], "2026-11-20T10:00:00Z")
        self.assertIsNone(a["version"])
        self.assertEqual(len(a["content_hash"]), 64)
        self.assertEqual(b["title"], self.url("/p/b.html"))  # no <title>: the URL
        self.assertEqual(b["published"], "2026-11-20T10:00:00Z")  # +02:00 -> UTC
        self.assertEqual(b["excerpt"], "Body B")
        self.assertEqual(set(a), {"title", "url", "version", "published", "excerpt", "content_hash"})

    def test_request_url_and_after_cursor_and_header(self):
        Handler.messages = [msg(105, "x")]
        sf.fetch(self.src, {})
        m, path, headers, _ = Handler.seen[0]
        self.assertEqual(urlsplit(path).path, f"/api/channels/{CHAN}/messages")
        self.assertEqual(parse_qs(urlsplit(path).query), {"limit": ["50"]})
        self.assertEqual(headers["Authorization"], f"Bot {TOKEN}")
        Handler.seen.clear()
        items, state = sf.fetch(self.src, {"after": "100"})
        self.assertEqual(parse_qs(urlsplit(Handler.seen[0][1]).query), {"limit": ["50"], "after": ["100"]})
        self.assertEqual(state, {"after": "105"})
        # nothing new: the cursor is kept
        Handler.messages = []
        items, state = sf.fetch(self.src, {"after": "105"})
        self.assertEqual((items, state), ([], {"after": "105"}))

    def test_source_request_is_not_an_item(self):
        Handler.messages = [msg(110, f"source: {self.url('/p/a.html')} new pricing page, watch it", author="bob"),
                            msg(109, "source:    https://x.example/feed.xml   why: a feed"),
                            msg(108, f"not a request source: {self.url('/p/b.html')}")]
        items, state = sf.fetch(self.src, {})
        reqs = [i["request"] for i in items if "request" in i]
        self.assertEqual(reqs[0], {"url": self.url("/p/a.html"), "why": "new pricing page, watch it", "message_id": "110", "author": "bob", "author_id": "7"})
        self.assertEqual(reqs[1]["url"], "https://x.example/feed.xml")
        self.assertEqual(reqs[1]["why"], "why: a feed")
        pages = [i for i in items if "request" not in i]
        self.assertEqual([p["url"] for p in pages], [self.url("/p/b.html")])  # the request URLs were not fetched as pages
        self.assertEqual(state, {"after": "110"})
        self.assertNotIn("/p/a.html", [s[1] for s in Handler.seen])

    def test_link_from_an_author_outside_allowfrom_is_ignored(self):
        Handler.messages = [dict(msg(130, f"see {self.url('/p/a.html')}"), author={"id": "99", "username": "mallory", "bot": False}),
                            msg(129, f"and {self.url('/p/b.html')}")]
        items, state = sf.fetch(self.src, {})
        self.assertEqual([i["url"] for i in items], [self.url("/p/b.html")])
        self.assertNotIn("/p/a.html", [s[1] for s in Handler.seen])
        self.assertEqual(state, {"after": "130"})

    def test_http_and_loopback_links_are_refused(self):
        import scout_sources
        Handler.messages = [msg(140, f"{self.url('/p/a.html')} https://127.0.0.1/p/b.html http://example.com/x")]
        with mock.patch.object(scout_sources, "_HTTP_OK_HOSTS", ()):
            items, _ = sf.fetch(self.src, {})
        self.assertEqual(items, [])
        self.assertNotIn("/p/a.html", [s[1] for s in Handler.seen])

    def test_bot_messages_ignored(self):
        Handler.messages = [msg(120, f"parsed: {self.url('/p/a.html')}", bot=True)]
        items, state = sf.fetch(self.src, {})
        self.assertEqual(items, [])
        self.assertEqual(state, {"after": "120"})

    def test_no_token_and_no_channel(self):
        with self.assertRaises(sf.FetchError) as cm:
            sf.fetch({"name": "c", "kind": "discord_channel", "url": ""}, {})
        self.assertEqual(str(cm.exception), "no channel")
        with self.assertRaises(sf.FetchError) as cm:
            sf.fetch({"name": "c", "kind": "discord_channel", "url": "abc"}, {})
        self.assertEqual(str(cm.exception), "no channel")
        (tc_env.discord_dir("agent-board") / ".env").unlink()
        with self.assertRaises(sf.FetchError) as cm:
            sf.fetch(self.src, {})
        self.assertEqual(str(cm.exception), "no token")
        (tc_env.discord_dir("agent-board") / ".env").write_text("OTHER=1\n")
        with self.assertRaises(sf.FetchError) as cm:
            sf.fetch(self.src, {})
        self.assertEqual(str(cm.exception), "no token")
        self.assertEqual(Handler.seen, [])

    def test_broken_response(self):
        with self.assertRaises(sf.FetchError):  # unknown channel: 404
            sf.fetch({"name": "c", "kind": "discord_channel", "url": "5555"}, {})
        for raw in (b"x", b"", b'{"message": "oops"}'):
            Handler.raw_messages = raw
            with self.assertRaises(sf.FetchError, msg=raw):
                sf.fetch(self.src, {})

    def test_post_message_and_reactions(self):
        mid = sf.post_message(CHAN, "parsed: source x", reply_to="110")
        self.assertEqual(mid, "999")
        m, path, headers, body = Handler.seen[-1]
        self.assertEqual((m, urlsplit(path).path), ("POST", f"/api/channels/{CHAN}/messages"))
        self.assertEqual(headers["Authorization"], f"Bot {TOKEN}")
        payload = json.loads(body)
        self.assertEqual(payload["content"], "parsed: source x")
        self.assertEqual(payload["message_reference"], {"message_id": "110"})
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        sf.post_message(CHAN, "plain")
        self.assertNotIn("message_reference", json.loads(Handler.seen[-1][3]))
        self.assertEqual(sf.reactions(CHAN, "999", "✅"), ["42", "43"])
        self.assertIn("%E2%9C%85", Handler.seen[-1][1])
        self.assertIn("/messages/999/reactions/", Handler.seen[-1][1])

    def test_post_and_reactions_need_token(self):
        (tc_env.discord_dir("agent-board") / ".env").unlink()
        with self.assertRaises(sf.FetchError):
            sf.post_message(CHAN, "x")
        with self.assertRaises(sf.FetchError):
            sf.reactions(CHAN, "1", "✅")

    def test_token_never_leaks(self):
        out, err = io.StringIO(), io.StringIO()
        collected = []
        Handler.messages = [msg(105, f"look {self.url('/p/a.html')}")]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            items, state = sf.fetch(self.src, {})
            collected.append(json.dumps([items, state]))
            mid = sf.post_message(CHAN, "hi")
            collected.append(mid)
            collected.append(json.dumps(sf.reactions(CHAN, "1", "✅")))
            # failing runs: the fake rejects any other token with 401
            (tc_env.discord_dir("agent-board") / ".env").write_text(f"DISCORD_BOT_TOKEN={TOKEN}x\n")  # wrong token, still contains TOKEN
            for call in (lambda: sf.fetch(self.src, {}), lambda: sf.post_message(CHAN, "hi"),
                         lambda: sf.reactions(CHAN, "1", "✅")):
                with self.assertRaises(sf.FetchError) as cm:
                    call()
                collected.append(str(cm.exception))
                collected.append(repr(cm.exception))
                collected.append(str(cm.exception.__cause__))
        blob = "\n".join(collected) + out.getvalue() + err.getvalue()
        self.assertNotIn(TOKEN, blob)
        self.assertIn("401", blob)  # the failure really was the 401 path

    def test_token_not_in_urlerror_text(self):
        with mock.patch.dict(os.environ, {"TC_SCOUT_DISCORD_API": "http://127.0.0.1:1/api"}):
            with self.assertRaises(sf.FetchError) as cm:
                sf.fetch(self.src, {})
        self.assertNotIn(TOKEN, str(cm.exception))


if __name__ == "__main__":
    unittest.main()
