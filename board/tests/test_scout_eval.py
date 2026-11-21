"""scout_eval: run_evaluate (fake claude), validate drops, pick order. Scratch TC_SCOUT_DIR, TC_STATE, HOME."""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import findings  # noqa: E402
import scout_eval as se  # noqa: E402

ENV = {"result": "", "is_error": False, "total_cost_usd": 0.5, "usage": {"output_tokens": 7}, "duration_ms": 1500}


def ent(item="i1", comp="Hooks", value="high", effort="S", quotes=1, url="http://x/i1", overlaps=None, **kw):
    d = {"item": item, "component": comp, "what_it_enables": "thing " + item, "value": value, "effort": effort, "risk": "r",
         "overlaps": overlaps or [], "evidence": [{"url": url, "quote": f"q{i}"} for i in range(quotes)]}
    d.update(kw)
    return d


def items(*keys):
    return [{"key": k, "url": f"http://x/{k}", "published": "2026-11-%02d" % (10 + n)} for n, k in enumerate(keys)]


def state(**kw):
    return dict({"filed": {}, "reported": {}, "dismissed": {}}, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        env = {"TC_SCOUT_DIR": str(self.t / "scout"), "TC_STATE": str(self.t / "state"), "HOME": str(self.t / "home")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.run_dir = self.t / "run"
        self.run_dir.mkdir()


class RunEvaluateTest(Base):
    def fake(self, body):
        f = self.t / "claude"
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
        os.environ["TC_SCOUT_CLAUDE"] = str(f)
        self.addCleanup(os.environ.pop, "TC_SCOUT_CLAUDE", None)

    def canned(self, result, **kw):
        (self.t / "env.json").write_text(json.dumps(dict(ENV, result=result, **kw)))
        self.fake(f'cat > {self.t}/stdin.txt\necho "$@" > {self.t}/argv.txt\npwd > {self.t}/cwd.txt\ncat {self.t}/env.json\n')

    def test_success_argv_info_and_file(self):
        entries = [ent()]
        self.canned("```json\n" + json.dumps({"entries": entries}) + "\n```")
        fail, got, info = se.run_evaluate(self.run_dir, self.t / "repo")
        self.assertIsNone(fail)
        self.assertEqual(got, entries)
        self.assertEqual(json.loads((self.run_dir / "evaluate.json").read_text()), {"entries": entries})
        self.assertEqual(info, {"cost_usd": 0.5, "usage": {"output_tokens": 7}, "model_s": 1.5})
        argv = (self.t / "argv.txt").read_text().split()
        self.assertEqual(argv[:1], ["-p"])
        for pair in (["--model", "sonnet"], ["--effort", "medium"], ["--permission-mode", "dontAsk"], ["--output-format", "json"],
                     ["--allowedTools", "Read,Grep,Glob,WebFetch"], ["--add-dir", str(self.t / "repo")]):
            i = argv.index(pair[0])
            self.assertEqual(argv[i:i + 2], pair)
        for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertEqual(Path((self.t / "cwd.txt").read_text().strip()).resolve(), self.run_dir.resolve())
        self.assertIn("items.json", (self.t / "stdin.txt").read_text())

    def test_bad_envelopes(self):
        for res, kw in (("not json", {}), (json.dumps({"entries": "x"}), {}), (json.dumps({"entries": []}), {"is_error": True})):
            self.canned(res, **kw)
            fail, got, _ = se.run_evaluate(self.run_dir, self.t)
            self.assertEqual((fail, got), ("model error", None))
            self.assertFalse((self.run_dir / "evaluate.json").exists())

    def test_non_string_result(self):
        (self.t / "env.json").write_text(json.dumps(dict(ENV, result={"entries": []})))
        self.fake(f"cat {self.t}/env.json\n")
        self.assertEqual(se.run_evaluate(self.run_dir, self.t)[0], "model error")

    def test_exit_code(self):
        self.fake("exit 3\n")
        self.assertEqual(se.run_evaluate(self.run_dir, self.t)[0], "model exit 3")
        self.assertFalse((self.run_dir / "evaluate.json").exists())

    def test_timeout(self):
        self.fake("sleep 30\n")
        with mock.patch.object(se, "EVAL_TIMEOUT", 2):
            fail, got, _ = se.run_evaluate(self.run_dir, self.t)
        self.assertEqual((fail, got), ("model timeout", None))

    def test_stale_evaluate_removed_on_failure(self):
        (self.run_dir / "evaluate.json").write_text("{}")
        self.fake("exit 1\n")
        se.run_evaluate(self.run_dir, self.t)
        self.assertFalse((self.run_dir / "evaluate.json").exists())


class ValidateTest(Base):
    def run_v(self, entries, st=None, its=None):
        info = {}
        return se.validate(entries, its or items("i1", "i2"), st or state(), info), info

    def test_valid_kept(self):
        v, info = self.run_v([ent()])
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["key"], "i1:hooks")
        self.assertEqual(info["dropped"], {})

    def test_component_key_form(self):
        v, _ = self.run_v([ent(comp="Agent Teams")])
        self.assertEqual(v[0]["key"], "i1:agent-teams")

    def test_unknown_item(self):
        v, info = self.run_v([ent(item="zzz")])
        self.assertEqual((v, info["dropped"]), ([], {"unknown item": 1}))

    def test_no_quote(self):
        v, info = self.run_v([ent(evidence=[{"url": "http://x/i1", "quote": "  "}]), ent(evidence=[])])
        self.assertEqual((v, info["dropped"]), ([], {"no quote": 2}))

    def test_url_outside_items(self):
        v, info = self.run_v([ent(url="http://evil/9")])
        self.assertEqual((v, info["dropped"]), ([], {"url not an item url": 1}))

    def test_bad_value_effort(self):
        v, info = self.run_v([ent(value="huge"), ent(effort="XL")])
        self.assertEqual((v, info["dropped"]), ([], {"bad value or effort": 2}))

    def test_filed(self):
        v, info = self.run_v([ent()], state(filed={"i1:hooks": {}}))
        self.assertEqual((v, info["dropped"]), ([], {"filed": 1}))

    def test_reported_dropped_unless_regrown(self):
        st = state(reported={"i1:hooks": {"last_evidence_count": 2}})
        v, info = self.run_v([ent(quotes=2)], st)
        self.assertEqual((v, info["dropped"]), ([], {"reported": 1}))
        v, _ = self.run_v([ent(quotes=3)], st)
        self.assertEqual(len(v), 1)

    def test_dismissed_not_regrown(self):
        st = state(dismissed={"i1:hooks": {"evidence_count": 2}})
        v, info = self.run_v([ent(quotes=2)], st)
        self.assertEqual((v, info["dropped"]), ([], {"dismissed": 1}))

    def test_dismissed_regrown(self):
        st = state(dismissed={"i1:hooks": {"evidence_count": 2}})
        v, _ = self.run_v([ent(quotes=3)], st)
        self.assertEqual(len(v), 1)

    def test_non_dict_entries_ignored(self):
        v, info = self.run_v(["x", None, ent()])
        self.assertEqual((len(v), info["dropped"]), (1, {"malformed": 2}))


class PickTest(Base):
    def valid(self, *specs):
        """specs: (item, value, effort[, published]); entries as validate returns them."""
        return [dict(ent(item=k, comp="c", value=v, effort=e), key=f"{k}:c", url=f"http://x/{k}", published=(r[0] if r else None))
                for k, v, e, *r in specs]

    def test_order_value_then_effort_then_published(self):
        v = self.valid(("a", "low", "S", "2026-11-01"), ("b", "high", "L", "2026-11-09"), ("c", "high", "S", "2026-11-05"),
                       ("d", "high", "S", None), ("e", "medium", "S", "2026-11-02"), ("f", "high", "S", "2026-11-07"))
        r = se.pick(v, [], [])
        self.assertEqual([e["item"] for e in r["picks"]], ["f", "c", "d"])
        self.assertEqual([e["item"] for e in r["others"]], ["b", "e", "a"])

    def test_cap_counts_revisions(self):
        v = self.valid(("a", "high", "S"), ("b", "high", "S"), ("c", "high", "S"))
        r = se.pick(v, [{"id": "r1"}, {"id": "r2"}], [])
        self.assertEqual(r["revisions"], [{"id": "r1"}, {"id": "r2"}])
        self.assertEqual(len(r["picks"]), 1)
        self.assertEqual(len(r["others"]), 2)

    def test_revisions_alone_fill_cap(self):
        r = se.pick(self.valid(("a", "high", "S")), [{"id": i} for i in "1234"], [])
        self.assertEqual((len(r["revisions"]), r["picks"]), (3, []))

    def test_overlap_becomes_note(self):
        s = "docs/superpowers/specs/x-design.md"
        v = self.valid(("a", "high", "S"), ("b", "low", "L"))
        v[0]["overlaps"] = [s, "some idea"]
        r = se.pick(v, [], [s])
        self.assertEqual([e["item"] for e in r["picks"]], ["b"])
        self.assertEqual(r["notes"], [f"{s}: could use thing a (http://x/a)"])
        self.assertEqual(r["others"], [])

    def test_overlap_with_unqueued_spec_is_drafted(self):
        v = self.valid(("a", "high", "S"))
        v[0]["overlaps"] = ["docs/superpowers/specs/merged.md"]
        self.assertEqual(len(se.pick(v, [], [])["picks"]), 1)

    def test_others_cap_10(self):
        r = se.pick(self.valid(*[(f"k{i}", "low", "S") for i in range(14)]), [], [])
        self.assertEqual((len(r["picks"]), len(r["others"])), (3, 10))


if __name__ == "__main__":
    unittest.main()
