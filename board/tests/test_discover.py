import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import discover as D  # noqa: E402
import discover_repo  # noqa: E402

NOW = 1_800_000_000


def git(root, *a):
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = Path(self.tmp.name)
        self.state = self.t / "state"
        self.state.mkdir()
        p = mock.patch.dict(os.environ, {"TC_STATE": str(self.state), "TC_IDEAS_DIR": str(self.t / "ideas"),
                                         "TC_CONTEXT_DIR": str(self.t / "ctx")})
        p.start()
        self.addCleanup(p.stop)
        self.root = self.t / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q")
        git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")


class CollectTest(Base):
    def test_shape_and_missing_sources(self):
        d = D.collect("p", str(self.root), NOW)
        self.assertEqual(set(d), {"project", "root", "at", "head", "candidates", "sources_skipped"})
        self.assertEqual(d["project"], "p")
        self.assertEqual(len(d["head"]), 40)
        skipped = {s["signal"]: s["why"] for s in d["sources_skipped"]}
        self.assertEqual(skipped["flaky_test"], "no test history")
        self.assertEqual(skipped["slow_test"], "no test history")
        self.assertEqual(skipped["failed_run"], "no run records")
        self.assertEqual(skipped["repeated_ruling"], "no ledgers")
        self.assertEqual(skipped["deferred_minor"], "no ledgers")
        self.assertEqual(skipped["stale_idea"], "no ideas file")
        self.assertEqual(d["candidates"], [])

    def test_raising_collector_is_skipped_others_run(self):
        cand = {"signal": "todo", "key": "todo:a:1", "title": "t", "evidence": [], "first_seen": "2026-01-01", "count": 1}
        with mock.patch.object(discover_repo, "todos", side_effect=ValueError("boom")), \
                mock.patch.object(discover_repo, "dependencies", return_value=([cand], [])):
            d = D.collect("p", str(self.root), NOW)
        skipped = {s["signal"]: s["why"] for s in d["sources_skipped"]}
        self.assertEqual(skipped["todo"], "error: ValueError: boom")
        self.assertEqual(d["candidates"], [cand])

    def test_dependency_skipped_appended_as_is(self):
        sk = [{"signal": "dependency", "why": "no gh"}]
        with mock.patch.object(discover_repo, "dependencies", return_value=([], sk)):
            d = D.collect("p", str(self.root), NOW)
        self.assertIn(sk[0], d["sources_skipped"])

    def test_present_sources_not_skipped(self):
        (self.state / "tests").mkdir()
        (self.state / "tests" / "history.jsonl").write_text("")
        (self.state / "runs-p.jsonl").write_text("")
        (self.root / "docs/superpowers/ledgers").mkdir(parents=True)
        (self.t / "ideas").mkdir()
        (self.t / "ideas" / "p.md").write_text("")
        d = D.collect("p", str(self.root), NOW)
        sig = {s["signal"] for s in d["sources_skipped"]}
        self.assertFalse(sig & {"flaky_test", "slow_test", "failed_run", "repeated_ruling", "deferred_minor", "stale_idea"}, sig)


def fake_claude(t, result_text, mode="ok"):
    """A fake claude: records argv and cwd, prints an envelope whose result is the file's text."""
    res = t / "result.txt"
    res.write_text(result_text)
    s = t / "fakeclaude"
    s.write_text(f"""#!/usr/bin/env python3
import json, os, sys, time
open({str(t / 'argv.json')!r}, 'w').write(json.dumps({{"argv": sys.argv, "cwd": os.getcwd(), "stdin": sys.stdin.read(),
    "env": [k for k in os.environ if k in ("TMUX", "CLAUDECODE")]}}))
mode = {mode!r}
if mode == "sleep":
    time.sleep(30)
if mode == "exit1":
    sys.exit(1)
text = open({str(res)!r}).read()
print(json.dumps({{"type": "result", "is_error": False, "result": text, "total_cost_usd": 0.01,
                  "usage": {{"input_tokens": 1, "output_tokens": 2}}, "duration_ms": 10}}))
""")
    s.chmod(0o755)
    return s


CANDS = [
    {"signal": "todo", "key": "todo:a.py:11111111", "title": "T1", "evidence": [{"text": "a"}, {"text": "b"}],
     "first_seen": "2026-01-01", "count": 1},
    {"signal": "todo", "key": "todo:b.py:22222222", "title": "T2", "evidence": [{"text": "a"}],
     "first_seen": "2026-01-01", "count": 1},
]


def item(key="todo:a.py:11111111", **kw):
    d = {"key": key, "title": "t", "why": "w", "expected_value": "high", "effort": "S", "risk": "low", "evidence_refs": [0]}
    d.update(kw)
    return d


class RankTest(Base):
    def run_rank(self, result_text, mode="ok", timeout=None):
        claude = fake_claude(self.t, result_text, mode)
        run_dir = self.t / "run"
        coll = {"project": "p", "root": str(self.root), "at": "x", "head": "h", "candidates": CANDS, "sources_skipped": []}
        env = {"TC_DISCOVER_CLAUDE": str(claude)}
        with mock.patch.dict(os.environ, env), mock.patch.object(D, "collect", return_value=coll), \
                mock.patch.object(D, "RANK_TIMEOUT", timeout or 600):
            self.res = D.rank("p", str(self.root), NOW, run_dir)
        self.run_dir = run_dir
        return self.res

    def items(self):
        return json.loads((self.run_dir / "rank.json").read_text())["items"]

    def test_valid_items_kept_and_files_written(self):
        r = self.run_rank(json.dumps({"items": [item(), item("todo:b.py:22222222", effort="L", expected_value="low")]}))
        self.assertEqual(r[0], None)
        self.assertEqual(len(self.items()), 2)
        self.assertEqual(json.loads((self.run_dir / "collected.json").read_text())["candidates"], CANDS)

    def test_argv_cwd_env_stdin(self):
        self.run_rank(json.dumps({"items": []}))
        rec = json.loads((self.t / "argv.json").read_text())
        self.assertEqual(rec["argv"][1:], ["-p", "--model", "sonnet", "--effort", "medium", "--restricted", "--tools", "Read",
                                           "--permission-mode", "dontAsk", "--strict-mcp-config",
                                           "--disable-slash-commands", "--no-session-persistence",
                                           "--output-format", "json"])
        self.assertEqual(os.path.realpath(rec["cwd"]), os.path.realpath(self.run_dir))
        self.assertIn("value", rec["stdin"].lower())

    def test_scrubbed_env(self):
        with mock.patch.dict(os.environ, {"TMUX": "x", "CLAUDECODE": "1"}):
            self.run_rank(json.dumps({"items": []}))
        self.assertEqual(json.loads((self.t / "argv.json").read_text())["env"], [])

    def test_unknown_key_dropped(self):
        self.run_rank(json.dumps({"items": [item("nope:1"), item()]}))
        self.assertEqual([i["key"] for i in self.items()], ["todo:a.py:11111111"])

    def test_bad_refs_dropped(self):
        bad = [item(evidence_refs=[2]), item(evidence_refs=["0"]), item(evidence_refs=[True]), item(evidence_refs=[-1]),
               item(evidence_refs="0"), item(evidence_refs=[1.0])]
        self.run_rank(json.dumps({"items": bad + [item(evidence_refs=[0, 1])]}))
        self.assertEqual(len(self.items()), 1)

    def test_ref_range_is_per_candidate(self):
        # candidate 2 has one evidence entry: ref 1 is out of range there
        self.run_rank(json.dumps({"items": [item("todo:b.py:22222222", evidence_refs=[1])]}))
        self.assertEqual(self.items(), [])

    def test_bad_enums_dropped(self):
        self.run_rank(json.dumps({"items": [item(expected_value="huge"), item(effort="XL"), item(effort="s"), item()]}))
        self.assertEqual(len(self.items()), 1)

    def test_missing_text_fields_dropped(self):
        bad = item(); del bad["why"]
        self.run_rank(json.dumps({"items": [bad, item(title=""), item(risk=3), item()]}))
        self.assertEqual(len(self.items()), 1)

    def test_unhashable_or_non_str_key_dropped(self):
        self.run_rank(json.dumps({"items": [item(key=["todo:a.py:11111111"]), item(key={"a": 1}), item(key=5), item()]}))
        self.assertEqual([i["key"] for i in self.items()], ["todo:a.py:11111111"])

    def test_duplicate_keys_keep_first(self):
        self.run_rank(json.dumps({"items": [item(title="first"), item(title="second"), item("todo:b.py:22222222")]}))
        self.assertEqual([(i["key"], i["title"]) for i in self.items()],
                         [("todo:a.py:11111111", "first"), ("todo:b.py:22222222", "t")])

    def test_failed_rank_removes_stale_rank_json(self):
        self.run_rank(json.dumps({"items": [item()]}))
        self.assertTrue((self.run_dir / "rank.json").exists())
        claude = fake_claude(self.t, "{}", "exit1")
        coll = {"project": "p", "root": str(self.root), "at": "x", "head": "h", "candidates": CANDS, "sources_skipped": []}
        with mock.patch.dict(os.environ, {"TC_DISCOVER_CLAUDE": str(claude)}), mock.patch.object(D, "collect", return_value=coll):
            r = D.rank("p", str(self.root), NOW, self.run_dir)
        self.assertEqual(r[0], "model exit 1")
        self.assertFalse((self.run_dir / "rank.json").exists())

    def test_cut_to_five(self):
        many = [dict(CANDS[0], key=f"todo:k{i}", evidence=[{"text": "a"}]) for i in range(8)]
        with mock.patch.object(sys.modules[__name__], "CANDS", many):
            self.run_rank(json.dumps({"items": [item(f"todo:k{i}") for i in range(8)]}))
        self.assertEqual([i["key"] for i in self.items()], [f"todo:k{i}" for i in range(5)])

    def test_fenced_json(self):
        self.run_rank("```json\n" + json.dumps({"items": [item()]}) + "\n```\n")
        self.assertEqual(len(self.items()), 1)

    def test_nonzero_exit(self):
        r = self.run_rank("{}", mode="exit1")
        self.assertEqual(r[0], "model exit 1")
        self.assertFalse((self.run_dir / "rank.json").exists())

    def test_timeout(self):
        r = self.run_rank("{}", mode="sleep", timeout=1)
        self.assertEqual(r[0], "model timeout")
        self.assertFalse((self.run_dir / "rank.json").exists())

    def test_unparseable(self):
        for text in ("not json at all", json.dumps([1]), json.dumps({"items": "x"}), json.dumps({"nope": []})):
            r = self.run_rank(text)
            self.assertEqual(r[0], "model error", text)
            self.assertFalse((self.run_dir / "rank.json").exists())

    def test_prune_keeps_14(self):
        base = self.state / "discover" / "runs" / "p"
        base.mkdir(parents=True)
        for i in range(20):
            (base / f"202611{i + 1:02d}-0000").mkdir()
        D.prune_runs("p")
        left = sorted(x.name for x in base.iterdir())
        self.assertEqual(len(left), 14)
        self.assertEqual(left[0], "20261107-0000")


class PromptTest(unittest.TestCase):
    def test_prompt_content(self):
        text = (REPO / "claude" / "discover.md").read_text()
        for needle in ("time saved", "failures avoided", "cost", "claude/orchestrator.md", "worker rules",
                       "claude/discover.md", '{"items": [{"key", "title", "why", "expected_value": "high|medium|low", '
                       '"effort": "S|M|L", "risk", "evidence_refs": [int]}]}', "at most 5", "JSON only"):
            self.assertIn(needle, text)


class CliTest(Base):
    def ctl(self, *args, env=None):
        e = {k: v for k, v in os.environ.items() if k != "TMUX"}
        e.update(env or {})
        return subprocess.run([str(REPO / "bin" / "tmux-ctl"), "discover", *args], capture_output=True, text=True, env=e)

    def test_collect_json_outside_tmux(self):
        r = self.ctl("collect", "p", "--root", str(self.root), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["project"], "p")
        self.assertTrue(d["sources_skipped"])

    def test_collect_text(self):
        r = self.ctl("collect", "p", "--root", str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("skipped: flaky_test (no test history)", r.stdout)

    def test_text_candidate_line(self):
        coll = {"project": "p", "root": "r", "at": "x", "head": "h", "candidates": CANDS, "sources_skipped": []}
        with mock.patch.object(D, "collect", return_value=coll), mock.patch("builtins.print") as pr:
            rc = D.main(["collect", "p", "--root", str(self.root)])
        self.assertEqual(rc, 0)
        self.assertEqual(pr.call_args_list[0].args[0], "todo\t1\ttodo:a.py:11111111\tT1")

    def test_no_root(self):
        r = self.ctl("collect", "zz-none")
        self.assertEqual(r.returncode, 2)
        self.assertIn("discover: no repo for zz-none", r.stderr)

    def test_root_from_state(self):
        (self.state / "discover").mkdir()
        (self.state / "discover" / "p.json").write_text(json.dumps({"root": str(self.root)}))
        r = self.ctl("collect", "p", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["root"], str(self.root.resolve()))

    def test_rank_output_and_failure(self):
        claude = fake_claude(self.t, json.dumps({"items": [item()]}))
        r = self.ctl("rank", "p", "--root", str(self.root), env={"TC_DISCOVER_CLAUDE": str(claude)})
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].endswith("rank.json"))
        self.assertEqual(len(lines), 1)   # no candidate matches the item's key here: dropped
        claude = fake_claude(self.t, "{}", "exit1")
        r = self.ctl("rank", "p", "--root", str(self.root), env={"TC_DISCOVER_CLAUDE": str(claude)})
        self.assertEqual(r.returncode, 1)
        self.assertIn("model exit 1", r.stderr + r.stdout)

    def test_nightly_reachable_outside_tmux(self):
        r = self.ctl("nightly", env={"TC_DISCOVER": "0"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "discover: off")

    def test_tmux_ctl_help_lines(self):
        text = (REPO / "bin" / "tmux-ctl").read_text()
        for s in ("tmux-ctl discover collect|rank <project>", "tmux-ctl discover nightly", "tmux-ctl discover schedule install|status|uninstall"):
            self.assertIn(s, text)


if __name__ == "__main__":
    unittest.main()
