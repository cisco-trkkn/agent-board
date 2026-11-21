"""discover_post: state file, selection rule, the nightly post and the File / Dismiss clicks. Scratch TC_STATE, TC_IDEAS_DIR, TC_CONTEXT_DIR."""
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import discord_feed  # noqa: E402
import discover_post as dp  # noqa: E402
import ideas  # noqa: E402
import tc_env  # noqa: E402

NOW = 1795000000.0


def kid(key):
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def cand(key, count=1, evidence=None, signal=None):
    return {"signal": signal or key.split(":")[0], "key": key, "title": "t " + key, "count": count, "first_seen": "2026-11-01",
            "evidence": evidence if evidence is not None else [{"text": f"e{i}", "path": None, "line": None, "url": None} for i in range(3)]}


def item(key, **kw):
    d = {"key": key, "title": "Fix " + key, "why": "because it hurts", "expected_value": "high", "effort": "S", "risk": "low",
         "evidence_refs": [0]}
    d.update(kw)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {"TC_STATE": self.tmp.name + "/state", "TC_IDEAS_DIR": self.tmp.name + "/ideas", "TC_CONTEXT_DIR": self.tmp.name + "/ctx"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)

    def outbox(self):
        d = tc_env.discord_dir("p") / "outbox"
        return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))] if d.exists() else []


class StateTest(Base):
    def test_defaults(self):
        st = dp.load_state("p")
        self.assertEqual((st["failures"], st["reported"], st["dismissed"], st["filed"], st["posts"]), (0, {}, {}, {}, {}))

    def test_roundtrip_atomic_and_cut_to_14_nights(self):
        st = dp.load_state("p")
        st["posts"] = {f"202611{d:02d}": {"key": "k", "items": []} for d in range(1, 21)}
        dp.save_state("p", st)
        p = tc_env.agent_base() / "discover" / "p.json"
        self.assertTrue(p.exists())
        self.assertFalse(list(p.parent.glob("*.tmp")))
        got = dp.load_state("p")
        self.assertEqual(sorted(got["posts"]), [f"202611{d:02d}" for d in range(7, 21)])

    def test_partial_file_gets_defaults(self):
        p = tc_env.agent_base() / "discover" / "p.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"failures": 2}))
        st = dp.load_state("p")
        self.assertEqual((st["failures"], st["filed"]), (2, {}))


def mem_report(ctx, project, run, proposals):
    d = Path(ctx) / "dream" / project / run / "out"
    d.mkdir(parents=True)
    (d / "report.json").write_text(json.dumps({"proposals": proposals}))


class MemoryDirsTest(Base):
    def test_no_report(self):
        self.assertEqual(dp.memory_dirs("p"), [])

    def test_newest_report_one_set_per_proposal(self):
        ctx = os.environ["TC_CONTEXT_DIR"]
        mem_report(ctx, "p", "20261101-0300", [{"evidence": ["inputs/ledgers/OLD/progress.md:1"]}])
        mem_report(ctx, "p", "20261102-0300", [
            {"evidence": ["inputs/ledgers/a/progress.md:4", "inputs/ledgers/b/progress.md:9", "x"]},
            {"evidence": []}, {"text": "no evidence key"}])
        (Path(ctx) / "dream" / "p" / "20261103-0300").mkdir()   # newest run dir without a report is skipped
        self.assertEqual([s for s in dp.memory_dirs("p") if s], [{"a", "b"}])


class SelectTest(Base):
    def st(self, **kw):
        s = dp.load_state("p")
        s.update(kw)
        return s

    def test_filed_never_shown(self):
        r = dp.select([item("todo:a")], {"todo:a": cand("todo:a")}, self.st(filed={"todo:a": {"at": "x", "idea_line": "l"}}), [])
        self.assertEqual((r["new"], r["still_open"], r["also_memory"]), ([], 0, []))

    def test_dismissed_regrowth_boundary(self):
        d = {"todo:a": {"at": "x", "evidence_count": 10}}
        rep = {"todo:a": {"first_reported": "x", "last_evidence_count": 10}}
        r14 = dp.select([item("todo:a")], {"todo:a": cand("todo:a", 14)}, self.st(dismissed=d, reported=rep), [])
        r15 = dp.select([item("todo:a")], {"todo:a": cand("todo:a", 15)}, self.st(dismissed=d, reported=rep), [])
        self.assertEqual((r14["new"], r14["still_open"]), ([], 0))
        self.assertEqual([i["key"] for i in r15["new"]], ["todo:a"])
        self.assertEqual(r15["new"][0]["count"], 15)

    def test_regrown_dismissed_item_is_reposted_once(self):   # mutation: keep `and not regrown` -> new again on nights 2 and 3
        s = self.st(dismissed={"todo:a": {"at": "x", "evidence_count": 10}},
                    reported={"todo:a": {"first_reported": "x", "last_evidence_count": 10}})
        cs = {"todo:a": cand("todo:a", 15)}
        seen = []
        for night in ("n1", "n2", "n3"):
            r = dp.select([item("todo:a")], cs, s, [])
            seen.append((len(r["new"]), r["still_open"]))
            dp.publish("p", night, r["new"], r["still_open"], [], cs, NOW) if r["new"] else None
            s = dp.load_state("p") if r["new"] else s
            s["dismissed"] = {"todo:a": {"at": "x", "evidence_count": 10}}
        self.assertEqual(seen, [(1, 0), (0, 1), (0, 1)])

    def test_unchanged_is_still_open_changed_is_new(self):
        rep = {"todo:a": {"first_reported": "x", "last_evidence_count": 3}}
        same = dp.select([item("todo:a")], {"todo:a": cand("todo:a", 3)}, self.st(reported=rep), [])
        chg = dp.select([item("todo:a")], {"todo:a": cand("todo:a", 4)}, self.st(reported=rep), [])
        self.assertEqual((same["new"], same["still_open"]), ([], 1))
        self.assertEqual((len(chg["new"]), chg["still_open"]), (1, 0))

    def test_memory_overlap_ge3_is_also_memory(self):
        ev = [{"text": "r", "path": f"docs/superpowers/ledgers/L{i}/progress.md", "line": 3, "url": None} for i in range(4)]
        c = {"repeated_ruling:x": cand("repeated_ruling:x", 4, ev), "todo:b": cand("todo:b", evidence=ev)}
        its = [item("repeated_ruling:x"), item("todo:b")]
        hit = dp.select(its, c, self.st(), [{"L0", "L1", "L2", "zz"}])
        self.assertEqual(([i["key"] for i in hit["new"]], [i["key"] for i in hit["also_memory"]]), (["todo:b"], ["repeated_ruling:x"]))
        miss = dp.select(its[:1], c, self.st(), [{"L0", "L1"}])
        self.assertEqual([i["key"] for i in miss["new"]], ["repeated_ruling:x"])


def many(n=5, why="because it hurts"):
    its = [item(f"todo:{i}", why=why) for i in range(n)]
    cs = {i["key"]: cand(i["key"], 2) for i in its}
    return its, cs


class BuildOpTest(Base):
    def new(self, its, cs):
        return [dict(i, count=cs[i["key"]]["count"]) for i in its]

    def test_shape_and_lines(self):
        its, cs = many(2)
        cs["todo:0"]["evidence"][0].update(text="a_b", url="https://h/x")
        op = dp.build_op("p", "20261121", self.new(its, cs), 3, [item("repeated_ruling:z", title="Rule *z*")], cs)
        discord_feed._check(op)
        self.assertEqual((op["tier"], op["mention_user"], op["key"]), ("progress", False, "discover-p-20261121"))
        t = op["text"]
        self.assertIn("1. Fix todo:0 — because it hurts", t)
        self.assertIn("value high · effort S · risk low · evidence: [a\\_b](https://h/x)", t)
        self.assertIn("still open: 3", t)
        self.assertIn("also proposed by the memory run: Rule \\*z\\*", t)
        self.assertEqual(op["rows"][1], [{"label": "File as idea 2", "style": 1, "custom_id": f"ab:discover:file:p:{kid('todo:1')}"},
                                         {"label": "Dismiss 2", "style": 2, "custom_id": f"ab:discover:dismiss:p:{kid('todo:1')}"}])

    def test_no_footer_when_zero(self):
        its, cs = many(1)
        t = dp.build_op("p", "n", self.new(its, cs), 0, [], cs)["text"]
        self.assertNotIn("still open", t)
        self.assertNotIn("memory run", t)

    def test_escapes_model_strings(self):
        its, cs = many(1)
        its[0].update(title="@everyone `x`", why="_why_")
        t = dp.build_op("p", "n", self.new(its, cs), 0, [], cs)["text"]
        self.assertNotIn("@everyone", t)
        self.assertIn("\\`x\\`", t)
        self.assertIn("\\_why\\_", t)

    def test_cap_1900_five_long_whys(self):
        its, cs = many(5, "y" * 900)
        op = dp.build_op("p", "n", self.new(its, cs), 4, [item("repeated_ruling:q")], cs)
        discord_feed._check(op)
        self.assertLessEqual(len(op["text"]), 1900)
        self.assertEqual(len(op["rows"]), 5)
        for n in range(1, 6):
            self.assertIn(f"{n}. Fix todo:{n - 1}", op["text"])   # every item survives, the whys were cut


class FitTest(Base):
    def test_long_titles_and_evidence_keep_items_footer_and_links(self):   # mutation: slice text[:LIMIT] -> items 4-5/footer lost
        its = [item(f"todo:{i}", title="T" * 500, why="w" * 500, expected_value="v" * 300) for i in range(5)]
        cs = {i["key"]: cand(i["key"], 2, [{"text": "E" * 500, "path": None, "line": None, "url": "https://h/x(1)"},
                                           {"text": "short", "path": None, "line": None, "url": "https://h/y"}]) for i in its}
        for i in its:
            i["evidence_refs"] = [0, 1]
        op = dp.build_op("p", "n", [dict(i, count=2) for i in its], 4, [item("repeated_ruling:q", title="Q" * 500)], cs)
        discord_feed._check(op)
        t = op["text"]
        self.assertLessEqual(len(t), 1900)
        for n in range(1, 6):
            self.assertIn(f"\n{n}. ", t)
        self.assertIn("still open: 4", t)
        self.assertIn("also proposed by the memory run: ", t)
        self.assertEqual(t.count("]("), t.count("](") and len(__import__("re").findall(r"\]\([^)]*\)", t)))

    def test_huge_urls_still_fit(self):   # mutation: links never dropped / url length unbounded -> text far over 1900
        its = [item(f"todo:{i}", title="T" * 300) for i in range(5)]
        cs = {i["key"]: cand(i["key"], 2, [{"text": "e" * 20, "path": None, "line": None, "url": "https://h/" + "u" * 800}] * 2) for i in its}
        for i in its:
            i["evidence_refs"] = [0, 1]
        op = dp.build_op("p", "n", [dict(i, count=2) for i in its], 2, [item("repeated_ruling:q")], cs)
        t = op["text"]
        self.assertLessEqual(len(t), 1900)
        for n in range(1, 6):
            self.assertIn(f"\n{n}. ", t)
        self.assertIn("still open: 2", t)
        self.assertIn("also proposed by the memory run: ", t)
        self.assertEqual(t.count("]("), len(re.findall(r"\[[^\]]*\]\([^)]*\)", t)))

    def test_header_names_project(self):
        its, cs = many(1)
        self.assertTrue(dp.build_op("projx", "20261121", [dict(its[0], count=2)], 0, [], cs)["text"].startswith("🔎 discover projx: 1 new"))


class PublishTest(Base):
    def test_failed_outbox_write_leaves_state(self):   # mutation: save state before the outbox write -> reported[] set
        its, cs = many(1)
        with mock.patch.object(dp.discord_feed, "outbox_write", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                dp.publish("p", "20261121", [dict(its[0], count=2)], 0, [], cs, NOW)
        st = dp.load_state("p")
        self.assertEqual((st["reported"], st["posts"]), ({}, {}))

    def test_nothing_new_writes_nothing(self):   # mutation: drop the early return -> an op is written
        self.assertEqual(dp.publish("p", "20261121", [], 2, [], {}, NOW), 0)
        self.assertEqual(self.outbox(), [])
        self.assertEqual(dp.load_state("p")["posts"], {})

    def test_writes_op_and_state(self):
        its, cs = many(2)
        new = [dict(i, count=2) for i in its]
        rep = dp.load_state("p")
        rep["reported"]["todo:0"] = {"first_reported": "2026-11-01T00:00:00Z", "last_evidence_count": 1}
        dp.save_state("p", rep)
        self.assertEqual(dp.publish("p", "20261121", new, 0, [], cs, NOW), 1)
        ops = self.outbox()
        self.assertEqual(len(ops), 1)
        st = dp.load_state("p")
        self.assertEqual(st["reported"]["todo:0"]["first_reported"], "2026-11-01T00:00:00Z")
        self.assertEqual(st["reported"]["todo:0"]["last_evidence_count"], 2)
        self.assertEqual(st["reported"]["todo:1"]["last_evidence_count"], 2)
        post = st["posts"]["20261121"]
        self.assertEqual(post["key"], "discover-p-20261121")
        self.assertEqual([(i["n"], i["key"], i["kid"], i["count"], i["decision"]) for i in post["items"]],
                         [(1, "todo:0", kid("todo:0"), 2, None), (2, "todo:1", kid("todo:1"), 2, None)])
        self.assertEqual(post["items"][0]["summary"], "e0")


class ClickTest(Base):
    def setUp(self):
        super().setUp()
        its, cs = many(2)
        dp.publish("p", "20261121", [dict(i, count=2) for i in its], 0, [], cs, NOW)
        self.k0 = kid("todo:0")
        self.out0 = len(self.outbox())

    def cid(self, act, k=None, p="p"):
        return f"ab:discover:{act}:{p}:{k or self.k0}"

    def idea_lines(self):
        p = ideas.ideas_path("p")
        return p.read_text().splitlines() if p.exists() else []

    def test_bad_and_foreign(self):
        self.assertEqual(dp.click("p", "U", "ab:discover:file:p", NOW), "unknown")
        self.assertEqual(dp.click("p", "U", self.cid("file", p="other"), NOW), "ignored")
        self.assertEqual(dp.click("p", "U", self.cid("file", k="0" * 12), NOW), "unknown")

    def test_file_once(self):   # mutation: drop the filed check -> the second tap adds a second idea line
        self.assertEqual(dp.click("p", "U", self.cid("file"), NOW), "filed")
        n = len(self.idea_lines())
        self.assertEqual(dp.click("p", "U", self.cid("file"), NOW), "already filed")
        self.assertEqual(len(self.idea_lines()), n)
        self.assertEqual(sum("Fix todo:0: because it hurts (evidence: e0)" in l for l in self.idea_lines()), 1)
        st = dp.load_state("p")
        self.assertIn("Fix todo:0", st["filed"]["todo:0"]["idea_line"])
        self.assertEqual(st["posts"]["20261121"]["items"][0]["decision"], "filed")

    def test_dismiss_records_count_and_repeats(self):
        self.assertEqual(dp.click("p", "U", self.cid("dismiss"), NOW), "dismissed")
        st = dp.load_state("p")
        self.assertEqual(st["dismissed"]["todo:0"]["evidence_count"], 2)
        self.assertEqual(dp.click("p", "U", self.cid("dismiss"), NOW), "already dismissed")
        self.assertEqual(self.idea_lines(), [])

    def test_edit_op_marks_item_and_drops_row(self):
        dp.click("p", "U", self.cid("file"), NOW)
        dp.click("p", "U", self.cid("dismiss", kid("todo:1")), NOW)
        eds = [o for o in self.outbox() if o["op"] == "edit"]
        self.assertEqual(len(eds), 2)
        for o in eds:
            discord_feed._check(o)
            self.assertEqual(o["key"], "discover-p-20261121")
        self.assertIn("— 💡 filed", eds[0]["text"])
        self.assertEqual(len(eds[0]["rows"]), 1)
        self.assertIn(kid("todo:1"), eds[0]["rows"][0][0]["custom_id"])
        self.assertIn("— ✖ dismissed", eds[1]["text"])
        self.assertEqual(eds[1]["rows"], [])

    def test_decided_by_key_across_nights(self):   # mutation: decide per post item only -> second night's button acts again
        its, cs = many(2)
        dp.click("p", "U", self.cid("file"), NOW)
        dp.click("p", "U", self.cid("dismiss", kid("todo:1")), NOW)
        dp.publish("p", "20261122", [dict(i, count=2) for i in its], 0, [], cs, NOW)
        n = len(self.idea_lines())
        self.assertEqual(dp.click("p", "U", self.cid("dismiss"), NOW), "already filed")
        self.assertEqual(dp.click("p", "U", self.cid("file"), NOW), "already filed")
        self.assertEqual(dp.click("p", "U", self.cid("dismiss", kid("todo:1")), NOW), "already dismissed")
        self.assertEqual(len(self.idea_lines()), n)

    def test_exception_is_error_type(self):
        with mock.patch.object(dp.ideas, "add", side_effect=OSError("boom")):
            self.assertEqual(dp.click("p", "U", self.cid("file"), NOW), "error: OSError")
        self.assertNotIn("todo:0", dp.load_state("p")["filed"])


if __name__ == "__main__":
    unittest.main()
