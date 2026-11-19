"""discord_ideas: /ideas requests, groups, buttons, clicks. Every test runs on temp TC_STATE and TC_IDEAS_DIR dirs."""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_feed  # noqa: E402
import discord_ideas as di  # noqa: E402
import ideas  # noqa: E402
import tc_env  # noqa: E402

TS = "2026-11-18 10:00"
A = f"- [ ] {TS} · alpha one\n  detail line\n- [-] {TS} · alpha dropped\n- [x] {TS} · alpha done → spec\n- [ ] {TS} · alpha two\n"
B = f"# Ideas: beta\n\n- [ ] {TS} · beta one\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state, self.ideas = root / "state", root / "ideas"
        self.ideas.mkdir()
        for name, body in (("alpha", A), ("beta", B)):
            (self.ideas / f"{name}.md").write_text(body)
        p = mock.patch.dict(os.environ, {"TC_STATE": str(self.state), "TC_IDEAS_DIR": str(self.ideas), "HOME": str(root / "home")})
        p.start()
        self.addCleanup(p.stop)
        k = mock.patch.object(ideas, "_kick")   # seam: no gitlab sync process
        k.start()
        self.addCleanup(k.stop)
        tc_env.discord_dir("alpha").mkdir(parents=True)
        self.lines = []
        self.add = lambda tgt, line: self.lines.append((tgt, line))

    def ids(self, project):
        return [i for i, p, _ in di.open_ideas(project)]

    def outbox(self, bridge="_ops"):
        d = (tc_env.ops_dir() if bridge == "_ops" else tc_env.discord_dir(bridge)) / "outbox"
        return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))] if d.is_dir() else []

    def ask(self, project=None, bridge="_ops", now=1000.0):
        self.assertEqual(di.request(project, bridge, self.add, now), "asked")
        return self.lines[-1][1].split()[2].rstrip(":")   # "[Discord] /ideas <id>:"

    def doc(self, req, groups):
        return {"request": req, "groups": groups}

    def grp(self, ids, project="alpha", title="T", emoji="🔧"):
        return {"title": title, "emoji": emoji, "project": project, "ideas": ids}


class TestIds(Base):
    def test_idea_id_formula(self):
        self.assertEqual(di.idea_id("p", "k"), hashlib.sha1(b"p\0k").hexdigest()[:10])

    def test_open_ideas_exactly_open(self):
        rows = di.open_ideas("alpha")
        self.assertEqual([t for _, _, t in rows], ["alpha one", "alpha two"])
        self.assertEqual(rows[0], (di.idea_id("alpha", f"{TS} · alpha one"), "alpha", "alpha one"))

    def test_open_ideas_all_sorted_by_project(self):
        self.assertEqual([(p, t) for _, p, t in di.open_ideas(None)],
                         [("alpha", "alpha one"), ("alpha", "alpha two"), ("beta", "beta one")])


class TestRequest(Base):
    def test_writes_request_and_overseer_line(self):
        req = self.ask("alpha")
        f = tc_env.ops_dir() / "ideas" / f"req-{req}.json"
        d = json.loads(f.read_text())
        self.assertEqual((d["id"], d["project"], d["bridge"], d["ts"], d["state"]), (req, "alpha", "_ops", 1000.0, "open"))
        self.assertEqual(self.lines, [("overseer", f"[Discord] /ideas {req}: group the open ideas of alpha, then run tmux-ctl discord ideas-post with the groups JSON")])

    def test_all_projects_wording(self):
        req = self.ask(None)
        self.assertEqual(self.lines[-1][1], f"[Discord] /ideas {req}: group the open ideas of all projects, then run tmux-ctl discord ideas-post with the groups JSON")

    def test_unknown_project_writes_nothing(self):
        self.assertEqual(di.request("nope", "_ops", self.add, 1.0), "unknown project")
        self.assertEqual(self.lines, [])
        self.assertEqual(list((tc_env.ops_dir() / "ideas").glob("req-*")) if (tc_env.ops_dir() / "ideas").is_dir() else [], [])

    def test_invalid_bridge_writes_nothing(self):
        for b in ("ghost", "../x", ""):
            self.assertEqual(di.request("alpha", b, self.add, 1.0), "invalid bridge", b)
        self.assertEqual(self.lines, [])
        self.assertFalse((tc_env.ops_dir() / "ideas").is_dir() and list((tc_env.ops_dir() / "ideas").glob("req-*")))

    def test_project_bridge_accepted(self):
        self.ask("alpha", "alpha")


class TestPost(Base):
    def test_posts_one_op_per_group_with_buttons(self):
        req = self.ask()
        i = self.ids("alpha") + self.ids("beta")
        rc, msg = di.post(self.doc(req, [self.grp(i[:2], title="Alpha", emoji="🅰"), self.grp(i[2:], "beta", "Beta", "🅱")]), 1010.0)
        self.assertEqual(rc, 0, msg)
        ops = self.outbox()
        self.assertEqual(len(ops), 2)
        self.assertEqual(ops[0]["text"], "🅰 **Alpha** · alpha · 2\n• alpha one\n• alpha two")
        self.assertEqual({k: ops[0][k] for k in ("op", "tier", "mention_user", "key")}, {"op": "post", "tier": "progress", "mention_user": False, "key": f"ideas-{req}-0"})
        self.assertEqual(ops[1]["key"], f"ideas-{req}-1")
        self.assertEqual(ops[0]["buttons"], [
            {"label": "Brainstorm next", "style": 1, "custom_id": f"ab:ideas:next:{req}:0"},
            {"label": "Park", "style": 2, "custom_id": f"ab:ideas:park:{req}:0"},
            {"label": "Drop", "style": 4, "custom_id": f"ab:ideas:drop:{req}:0"}])

    def test_posts_to_request_bridge(self):
        req = self.ask(bridge="alpha")
        self.assertEqual(di.post(self.doc(req, [self.grp(self.ids("alpha"))]), 1010.0)[0], 0)
        self.assertEqual((len(self.outbox("alpha")), len(self.outbox())), (1, 0))

    def test_drops_bad_ids_and_posts_skipped(self):
        req = self.ask()
        good = self.ids("alpha")[0]
        dropped = di.idea_id("alpha", f"{TS} · alpha dropped")
        beta = self.ids("beta")[0]
        rc, _ = di.post(self.doc(req, [self.grp([good, good, "deadbeef00", dropped, beta])]), 1010.0)
        self.assertEqual(rc, 0)
        ops = self.outbox()
        self.assertEqual([o["text"] for o in ops], ["🔧 **T** · alpha · 1\n• alpha one", "skipped: 4 ids"])
        self.assertNotIn("buttons", ops[1])

    def test_request_project_limits_ids(self):
        req = self.ask("alpha")
        di.post(self.doc(req, [self.grp(self.ids("alpha") + self.ids("beta"), "alpha")]), 1010.0)
        self.assertTrue(self.outbox()[-1]["text"].startswith("skipped: 1 ids") or self.outbox()[0]["text"].endswith("alpha two"))
        self.assertEqual(self.outbox()[0]["text"].splitlines()[0], "🔧 **T** · alpha · 2")

    def test_no_open_ideas(self):
        req = self.ask()
        rc, _ = di.post(self.doc(req, [self.grp(["deadbeef00"])]), 1010.0)
        self.assertEqual(rc, 0)
        self.assertEqual([o["text"] for o in self.outbox()], ["no open ideas", "skipped: 1 ids"])

    def test_refusals(self):
        self.assertEqual(di.post(self.doc("zzzzzzzz", []), 1.0)[0], 1)
        req = self.ask()
        self.assertEqual(di.post({"request": req, "groups": "x"}, 1010.0)[0], 1)
        self.assertEqual(di.post(self.doc(req, [self.grp(self.ids("alpha"))]), 1010.0)[0], 0)
        self.assertEqual(di.post(self.doc(req, [self.grp(self.ids("alpha"))]), 1011.0)[0], 1)   # answered

    def test_post_expired_request_refused(self):
        req = self.ask(now=1000.0)
        rc, msg = di.post(self.doc(req, [self.grp(self.ids("alpha"))]), 1600.0)
        self.assertEqual(rc, 1, msg)
        self.assertEqual(self.outbox(), [])
        self.assertEqual(di.post(self.doc(req, [self.grp(self.ids("alpha"))]), 1599.0)[0], 0)

    def test_dry_run_writes_nothing(self):
        req = self.ask()
        rc, msg = di.post(self.doc(req, [self.grp(self.ids("alpha"))]), 1010.0, dry_run=True)
        self.assertEqual(rc, 0, msg)
        d = tc_env.ops_dir()
        files = [p for p in d.rglob("*") if p.is_file() and "outbox" in p.parts or p.name.startswith("post-")]
        print(f"dry-run: checked {len(list(d.rglob('*')))} entries, {len(files)} outbox/post files")
        self.assertEqual(files, [])
        self.assertEqual(json.loads((d / "ideas" / f"req-{req}.json").read_text())["state"], "open")
        self.assertEqual(di.post(self.doc(req, [self.grp(self.ids("alpha"))]), 1010.0)[0], 0)   # still postable

    def test_dry_run_refuses_like_real(self):
        self.assertEqual(di.post(self.doc("zzzzzzzz", []), 1.0, dry_run=True)[0], 1)

    def test_limits(self):
        (self.ideas / "alpha.md").write_text("".join(f"- [ ] {TS} · {'x' * 200} {n}\n" for n in range(40)))
        req = self.ask("alpha")
        ids = self.ids("alpha")
        rc, _ = di.post(self.doc(req, [self.grp(ids)]), 1010.0)
        t = self.outbox()[0]["text"]
        self.assertLessEqual(len(t), 1900)
        self.assertRegex(t, r"… \d+ more$")
        self.assertTrue(all(len(l) <= 122 for l in t.splitlines()[1:-1]))   # "• " + 120

    def test_group_cap_ten(self):
        (self.ideas / "alpha.md").write_text("".join(f"- [ ] {TS} · idea {n}\n" for n in range(12)))
        req = self.ask()
        ids = self.ids("alpha")
        groups = [self.grp([ids[n]], title=f"g{n}") for n in range(12)]
        di.post(self.doc(req, groups), 1010.0)
        ops = self.outbox()
        self.assertEqual(len(ops), 11)
        self.assertEqual(ops[-1]["text"], "skipped: 2 ids")


class TestExpire(Base):
    def test_expire_posts_and_closes(self):
        req = self.ask(bridge="alpha", now=1000.0)
        self.assertEqual(di.expire(1179.0), 0)
        self.assertEqual(di.expire(1180.0), 1)
        self.assertEqual([o["text"] for o in self.outbox("alpha")], ["overseer didn't answer /ideas"])
        self.assertEqual(di.expire(1300.0), 0)
        rc, _ = di.post(self.doc(req, [self.grp(self.ids("alpha"))]), 1200.0)
        self.assertEqual(rc, 1)

    def test_answered_not_expired(self):
        req = self.ask(now=1000.0)
        di.post(self.doc(req, [self.grp(self.ids("alpha"))]), 1010.0)
        self.assertEqual(di.expire(5000.0), 0)


class TestClick(Base):
    def setUp(self):
        super().setUp()
        self.req = self.ask()
        self.a_ids = self.ids("alpha")
        di.post(self.doc(self.req, [self.grp(self.a_ids, title="Grp")]), 1010.0)
        self.before = len(self.outbox())

    def cid(self, act, g=0, req=None):
        return f"ab:ideas:{act}:{req or self.req}:{g}"

    def test_next(self):
        self.lines.clear()
        self.assertEqual(di.click("u1", self.cid("next"), self.add, 1020.0), "queued")
        self.assertEqual(self.lines, [("alpha", f"regroup: Grp — ideas: {', '.join(self.a_ids)}")])
        e = self.outbox()[-1]
        self.assertEqual(e, {"op": "edit", "key": f"ideas-{self.req}-0", "text": "🔧 **Grp** · alpha · 2\n→ sent to alpha's lead to brainstorm"})

    def test_park_leaves_file_identical(self):
        raw = (self.ideas / "alpha.md").read_bytes()
        self.assertEqual(di.click("u1", self.cid("park"), self.add, 1020.0), "parked")
        self.assertEqual((self.ideas / "alpha.md").read_bytes(), raw)
        self.assertEqual(self.outbox()[-1]["text"], "🔧 **Grp** · alpha · 2\n→ parked")
        self.assertEqual(self.lines[-1][0], "overseer")   # only the request line

    def test_drop(self):
        self.assertEqual(di.click("u1", self.cid("drop"), self.add, 1020.0), "dropped 2")
        self.assertEqual(self.ids("alpha"), [])
        text = (self.ideas / "alpha.md").read_text()
        self.assertIn(f"- [-] {TS} · alpha one", text)
        self.assertIn(f"- [x] {TS} · alpha done", text)
        self.assertEqual(self.outbox()[-1]["text"], "🔧 **Grp** · alpha · 2\ndropped 2")

    def test_drop_leaves_changed_line(self):
        ideas.set_status("alpha", f"{TS} · alpha one", "dropped")   # changed since the post
        self.assertEqual(di.click("u1", self.cid("drop"), self.add, 1020.0), "dropped 1")
        self.assertEqual(self.outbox()[-1]["text"], "🔧 **Grp** · alpha · 2\ndropped 1, 1 already changed")
        self.assertEqual(self.ids("alpha"), [])

    def test_second_click_unknown(self):
        raw = None
        self.assertEqual(di.click("u1", self.cid("park"), self.add, 1020.0), "parked")
        n = len(self.outbox())
        raw = (self.ideas / "alpha.md").read_bytes()
        n_lines = len(self.lines)
        for act in ("drop", "next", "park"):
            self.assertEqual(di.click("u1", self.cid(act), self.add, 1030.0), "unknown")
        self.assertEqual((len(self.outbox()), len(self.lines), (self.ideas / "alpha.md").read_bytes()), (n, n_lines, raw))

    def test_unknown_request_group_and_garbage(self):
        n = len(self.outbox())
        for cid in (self.cid("drop", req="ffffffff"), self.cid("drop", g=7), "ab:ideas:drop:x", "nope", self.cid("zap")):
            self.assertEqual(di.click("u1", cid, self.add, 1020.0), "unknown", cid)
        self.assertEqual(len(self.outbox()), n)
        self.assertEqual(len(self.ids("alpha")), 2)


class TestMain(Base):
    def run_main(self, argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(sys, "stdin", io.StringIO(stdin)):
            rc = di.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_list(self):
        rc, out, _ = self.run_main(["list", "beta"])
        self.assertEqual((rc, out), (0, f"{di.idea_id('beta', f'{TS} · beta one')}\tbeta\tbeta one\n"))
        self.assertEqual(len(self.run_main(["list"])[1].splitlines()), 3)

    def test_post_stdin_and_refusal(self):
        req = self.ask()
        with mock.patch.object(di.time, "time", return_value=1010.0):
            rc, _, _ = self.run_main(["post", "-", "--dry-run"], json.dumps(self.doc(req, [self.grp(self.ids("alpha"))])))
            self.assertEqual(rc, 0)
            self.assertEqual(self.run_main(["post", "-"], json.dumps(self.doc(req, [self.grp(self.ids("alpha"))])))[0], 0)
        rc, _, err = self.run_main(["post", "-"], json.dumps(self.doc(req, [])))
        self.assertEqual(rc, 1)
        self.assertTrue(err.strip())

    def test_post_file_and_bad_json(self):
        self.assertEqual(self.run_main(["post", "-"], "{not json")[0], 1)

    def test_bad_argv(self):
        for a in ([], ["bogus"], ["post"], ["list", "a", "b"], ["post", "-", "--wat"]):
            self.assertEqual(self.run_main(a)[0], 2, a)


class TestFeedButtons(unittest.TestCase):
    OP = {"op": "post", "text": "t", "tier": "progress", "mention_user": False}

    def ok(self, buttons):
        discord_feed._check({**self.OP, "buttons": buttons})

    def test_accepts(self):
        self.ok([{"label": "a", "style": 1, "custom_id": "x"}] * 5)
        self.ok([])

    def test_rejects(self):
        b = {"label": "a", "style": 1, "custom_id": "x"}
        for bad in ("x", [b] * 6, [{"label": "a", "style": 1}], [{**b, "extra": 1}], [{**b, "style": "1"}], [{**b, "label": 3}], [3], {"a": 1}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.ok(bad)

    def test_other_ops_reject_buttons(self):
        with self.assertRaises(ValueError):
            discord_feed._check({"op": "edit", "key": "k", "text": "t", "buttons": []})


if __name__ == "__main__":
    unittest.main()
