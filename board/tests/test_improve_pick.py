"""Task 9: improve_pick, the tick's ranking step. Every test uses a fake `claude` script (TC_IMPROVE_CLAUDE) in a temp dir
and a scratch engine DB, TC_STATE and TC_OBSERVER_DIR; no test runs the real `claude`."""
import json, os, shutil, stat, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_store as S  # noqa: E402
import improve_pick as P  # noqa: E402
import improve_fixtures as F  # noqa: E402

EV = [{"type": "run", "ref": "r1"}]
PROSE = "--- a/docs/%s.md\n+++ b/docs/%s.md\n@@ -1 +1 @@\n-old\n+new\n"
CODE = "--- a/docs/%s.md\n+++ b/docs/%s.md\n@@ -1 +1 @@\n-old\n+$ tmux-ctl x\n"
REAL_ROUTING = Path(__file__).resolve().parents[2] / "docs" / "superpowers" / "model-routing.json"


def fake_claude(d, reply_text=None, exit_code=0, tokens=50, raw=None, sleep=0):
    """Write a fake claude: records argv and stdin under d, prints a claude -p json result."""
    out = raw if raw is not None else json.dumps({"is_error": False, "result": reply_text, "usage": {"output_tokens": tokens}})
    script = Path(d) / "claude"
    script.write_text("#!/bin/sh\necho called >> '%s/calls'\nprintf '%%s\\n' \"$@\" > '%s/argv'\ncat > '%s/stdin'\n"
                      "sleep %s\ncat <<'EOF_OUT'\n%s\nEOF_OUT\nexit %d\n" % (d, d, d, sleep, out, exit_code))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp, self.state, self.bin = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {"TC_ENGINE_DIR": self.tmp, "TC_STATE": self.state, "TC_OBSERVER_DIR": self.state})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(lambda: [shutil.rmtree(d, ignore_errors=True) for d in (self.tmp, self.state, self.bin)])
        F.engine_db(self.tmp)
        self.s = S.Store("proj")
        self.n = 0

    def prop(self, patch=PROSE, target=None, kind="procedure"):
        self.n += 1
        target = target or f"docs/t{self.n}.md"
        return self.s.insert("manual", kind, target, (patch % (target[5:-3], target[5:-3])) if patch else None, EV)

    def trial(self, pid):
        self.s.transition(pid, "trial", "go", trial_started_at=1.0)

    def use(self, **kw):
        env = mock.patch.dict(os.environ, {"TC_IMPROVE_CLAUDE": fake_claude(self.bin, **kw)})
        env.start()
        self.addCleanup(env.stop)

    def calls(self):
        f = Path(self.bin) / "calls"
        return len(f.read_text().split()) if f.exists() else 0

    def failed_events(self):
        c = self.s._conn()
        try:
            return [json.loads(d) for (d,) in c.execute("SELECT detail FROM events WHERE kind='improve_rank_failed'")]
        finally:
            c.close()

    def states(self):
        return {p["id"]: p["state"] for p in self.s.list()}


class Candidates(Base):
    def test_two_running_makes_no_call(self):
        a, b, c = self.prop(), self.prop(), self.prop()
        self.trial(a); self.trial(b)
        self.use(reply_text=json.dumps([c]))
        self.assertEqual(P.pick(self.s, [], 1), [])
        self.assertEqual(self.calls(), 0)
        self.assertEqual(self.failed_events(), [])

    def test_filter_class_patch_and_target_in_trial(self):
        run = self.prop(target="docs/run.md")
        self.trial(run)
        same = self.prop(patch=CODE, target="docs/run.md")      # target already in a trial
        nopatch = self.prop(patch=None, kind="memory")           # class observation, no patch
        prot = self.prop(kind="permission")                      # protected
        ok1, ok2 = self.prop(), self.prop(patch=CODE)            # low and high
        self.use(reply_text=json.dumps([ok2, ok1]))
        got = P.pick(self.s, [], 1, outcomes=[])
        self.assertEqual(got, [ok2])                             # one slot left
        stdin = (Path(self.bin) / "stdin").read_text()
        for pid in (ok1, ok2):
            self.assertIn(f'"id": "{pid}"', stdin)
        for pid in (same, nopatch, prot):
            self.assertNotIn(f'"id": "{pid}"', stdin)
        self.assertEqual(self.states()[ok2], "trial")
        self.assertEqual(self.states()[ok1], "proposed")
        self.assertIsNotNone(self.s.get(ok2)["trial_started_at"])


class Call(Base):
    def test_argv_prompt_and_outcomes(self):
        a = self.prop()
        self.use(reply_text=json.dumps([a]))
        routing = json.loads(REAL_ROUTING.read_text())
        P.pick(self.s, [], 1, outcomes=[{"id": "cheaper", "state": "active", "title": "Cut tokens"}])
        argv = (Path(self.bin) / "argv").read_text().split("\n")[:-1]
        self.assertEqual(argv, ["-p", "--model", routing["mechanical"], "--effort", "low", "--permission-mode", "dontAsk",
                                "--output-format", "json"])
        stdin = (Path(self.bin) / "stdin").read_text()
        self.assertTrue(stdin.startswith((P.REPO / "claude" / "improve-rank.md").read_text()))
        self.assertIn("cheaper", stdin)
        self.assertIn(a, stdin)

    def test_model_comes_from_routing_file(self):
        a = self.prop()
        self.use(reply_text=json.dumps([a]))
        r = Path(self.bin) / "routing.json"
        r.write_text(json.dumps({"mechanical": "model-x"}))
        with mock.patch.object(P, "ROUTING", r):
            P.pick(self.s, [], 1, outcomes=[])
        self.assertIn("model-x", (Path(self.bin) / "argv").read_text().split("\n"))

    def test_timeout_is_300(self):
        self.assertEqual(P.RANK_TIMEOUT, 300)


class Replies(Base):
    def setUp(self):
        super().setUp()
        self.a, self.b, self.c = self.prop(), self.prop(), self.prop()

    def fails(self, **kw):
        self.use(**kw)
        self.assertEqual(P.pick(self.s, [], 1, outcomes=[]), [])
        self.assertEqual(len(self.failed_events()), 1)
        self.assertEqual(set(self.states().values()), {"proposed"})

    def test_good_reply_starts_top_two_in_order(self):
        self.use(reply_text=json.dumps([self.c, self.a, self.b]))
        self.assertEqual(P.pick(self.s, [], 1, outcomes=[]), [self.c, self.a])
        self.assertEqual(self.states(), {self.a: "trial", self.b: "proposed", self.c: "trial"})
        self.assertEqual(self.failed_events(), [])

    def test_fenced_reply_is_accepted(self):
        self.use(reply_text="```json\n" + json.dumps([self.b]) + "\n```")
        self.assertEqual(P.pick(self.s, [], 1, outcomes=[]), [self.b])

    def test_exit_nonzero(self):
        self.fails(reply_text=json.dumps([self.a]), exit_code=1)

    def test_bad_json(self):
        self.fails(reply_text="not json at all")

    def test_not_a_list(self):
        self.fails(reply_text=json.dumps({"ids": [self.a]}))

    def test_unknown_id(self):
        self.fails(reply_text=json.dumps([self.a, "P999"]))

    def test_over_2000_tokens(self):
        self.fails(reply_text=json.dumps([self.a]), tokens=2001)

    def test_exactly_2000_tokens_ok(self):
        self.use(reply_text=json.dumps([self.a]), tokens=2000)
        self.assertEqual(P.pick(self.s, [], 1, outcomes=[]), [self.a])

    def test_timeout(self):
        self.use(reply_text=json.dumps([self.a]), sleep=5)
        with mock.patch.object(P, "RANK_TIMEOUT", 1):
            self.assertEqual(P.pick(self.s, [], 1, outcomes=[]), [])
        self.assertEqual(len(self.failed_events()), 1)
        self.assertEqual(set(self.states().values()), {"proposed"})

    def test_missing_claude_binary(self):
        with mock.patch.dict(os.environ, {"TC_IMPROVE_CLAUDE": "/nonexistent/claude"}):
            self.assertEqual(P.pick(self.s, [], 1, outcomes=[]), [])
        self.assertEqual(len(self.failed_events()), 1)

    def test_no_candidates_no_call(self):
        for p in (self.a, self.b, self.c):
            self.s.transition(p, "rejected", "x")
        self.use(reply_text="[]")
        self.assertEqual(P.pick(self.s, [], 1, outcomes=[]), [])
        self.assertEqual(self.calls(), 0)


if __name__ == "__main__":
    unittest.main()
