"""scout: the weekly pass and the scout CLI, end to end. Real git on a scratch repo, a fake claude (TC_SCOUT_CLAUDE), a local
HTTP server for the one source, scratch TC_SCOUT_DIR / TC_STATE / HOME / TC_IDEAS_DIR / TC_CONTEXT_DIR. Every weekly call
passes --root, so the real checkout is never the repo under test."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scout  # noqa: E402
import scout_eval  # noqa: E402
import scout_post  # noqa: E402
import scout_sources  # noqa: E402
import tc_env  # noqa: E402

REPO = HERE.parents[1]
RSS = (HERE / "fixtures" / "scout" / "claude_blog_rss.xml").read_bytes()   # three items
T1, T2, T3 = "Linked billing on the Claude Platform", "The Claude Tag guide for startups", "Building always-on agents"
SUN = time.mktime((2026, 11, 22, 7, 0, 0, 0, 0, -1))     # a Sunday, 07:00 local
WEEK, WEEK2 = "2026-11-22", "2026-11-29"
DAY = 86400
QUEUED = "docs/superpowers/specs/2026-11-01-queued-design.md"
EVAL_USAGE = {"input_tokens": 100, "output_tokens": 20}
DRAFT_USAGE = {"input_tokens": 50, "output_tokens": 10}


def spec(title, cite="board/server.py"):
    return (f"# {title} — design\n\nProposed by: scout · Source: http://x (2026-11-14)\n\n## Problem\nSee `{cite}`.\n\n"
            "## Decisions\n- one (*proposed, not approved*)\n\n## Design\n## Error handling\n## Testing\n## Out of scope\n")


# The fake claude. `--version` answers a version. A call with --effort is the evaluate step: plan["evaluate"] gives the
# entries, each naming its item by title ("t"). Any other call is a draft: the step is plan["drafts"][<component>], found by
# the component named in the prompt. Every model call is appended to calls.jsonl.
FAKE = """#!{py}
import json, os, re, subprocess, sys
d = {d!r}
args = sys.argv[1:]
if args == ["--version"]:
    print("9.9.9 (Claude Code)")
    sys.exit(0)
stdin = sys.stdin.read()
plan = json.load(open(os.path.join(d, "plan.json")))
ev = "--effort" in args
call = {{"kind": "evaluate" if ev else "draft", "argv": args, "cwd": os.getcwd(), "stdin": stdin}}
if ev:
    step = plan.get("evaluate") or {{}}
    items = {{i["title"]: i for i in json.load(open("items.json"))}}
    entries = []
    for e in step.get("entries") or []:
        it = items.get(e["t"]) or {{"key": "nokey", "url": "http://nowhere/"}}
        entries.append({{"item": it["key"], "component": e["c"], "what_it_enables": e.get("w", "enables " + e["c"]),
                        "value": e.get("v", "high"), "effort": e.get("e", "S"), "risk": "some risk", "overlaps": e.get("o", []),
                        "evidence": [{{"url": it["url"], "quote": "quote for " + e["c"]}}]}})
    env = {{"result": json.dumps({{"entries": entries}}), "is_error": False, "total_cost_usd": 0.5, "usage": {eu!r}, "duration_ms": 1000}}
else:
    comp = next((c for c in plan.get("drafts") or {{}} if '"component": "%s"' % c in stdin), None)
    step = (plan.get("drafts") or {{}}).get(comp) or {{}}
    call["component"] = comp
    g = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True).stdout.strip()
    alt = os.path.join(g, "objects", "info", "alternates")
    call["alternates"] = open(alt).read() if os.path.exists(alt) else ""
    week = re.search(r"specs/(\\d{{4}}-\\d\\d-\\d\\d)-<slug>", stdin).group(1)
    if "slug" in step:
        rel = "docs/superpowers/specs/%s-%s-design.md" % (week, step["slug"])
        os.makedirs(os.path.dirname(rel), exist_ok=True)
        open(rel, "w").write(step["text"])
    env = {{"result": "done", "is_error": False, "total_cost_usd": 1.5, "usage": {du!r}, "duration_ms": 2000}}
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(call) + "\\n")
if step.get("exit"):
    sys.exit(step["exit"])
print(json.dumps(env))
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        ok = self.path == "/rss.xml"
        body = RSS if ok else b"nope"
        self.send_response(200 if ok else 404)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def git(cwd, *args):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if p.returncode:
        raise AssertionError(f"git {args}: {p.stderr}")
    return p.stdout.strip()


def tree(root):
    root = Path(root)
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


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
        self.t = Path(self.tmp.name).resolve()
        self.scout = self.t / "scout"
        self.fk = self.t / "fake"
        self.fk.mkdir()
        (self.t / "home").mkdir()
        fake = self.fk / "claude"
        fake.write_text(FAKE.format(py=sys.executable, d=str(self.fk), eu=EVAL_USAGE, du=DRAFT_USAGE))
        fake.chmod(0o755)
        self.env = {"TC_SCOUT_DIR": str(self.scout), "TC_STATE": str(self.t / "state"), "HOME": str(self.t / "home"),
                    "TC_IDEAS_DIR": str(self.t / "ideas"), "TC_CONTEXT_DIR": str(self.t / "ctx"), "TC_SCOUT_CLAUDE": str(fake),
                    "TMPDIR": str(self.t / "tmpdir")}
        (self.t / "tmpdir").mkdir()
        p = mock.patch.dict(os.environ, self.env)
        p.start()
        self.addCleanup(p.stop)
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "TC_SCOUT"):
            os.environ.pop(k, None)
        old = tempfile.tempdir
        tempfile.tempdir = None                     # the dry-run temp dir must land under this test's TMPDIR
        self.addCleanup(setattr, tempfile, "tempdir", old)
        self.root = self.t / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "t")
        git(self.root, "config", "user.email", "t@example.invalid")
        for rel, text in {".gitignore": ".claude/worktrees/\n", "README.md": "readme\n\n## Layout\nboard/ the board\n",
                          "board/server.py": "x = 1\n", "docs/superpowers/model-routing.json": '{"frontier": "fable"}\n',
                          "docs/superpowers/metrics/runs.jsonl": '{"kind": "batch", "batch": "b1"}\n',
                          QUEUED: "# Queued thing\n"}.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "init")
        self.main_head = git(self.root, "rev-parse", "main")
        self.plan({"evaluate": {"entries": []}})

    # ---- helpers ----
    def plan(self, plan):
        (self.fk / "plan.json").write_text(json.dumps(plan))

    def calls(self, kind=None):
        f = self.fk / "calls.jsonl"
        rows = [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []
        return [r for r in rows if kind is None or r["kind"] == kind]

    def run_scout(self, *argv, now=SUN, root=True):
        out, err = io.StringIO(), io.StringIO()
        full = list(argv) + (["--root", str(self.root)] if root else [])
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = scout.main(full, now=now)
        return rc, out.getvalue() + err.getvalue()

    def add_items(self, at, titles=(T1, T2, T3), tag=""):
        """Item lines as the poll writes them, fetched at `at`."""
        self.scout.mkdir(parents=True, exist_ok=True)
        with open(self.scout / "items.jsonl", "a") as f:
            for n, t in enumerate(titles):
                f.write(json.dumps({"key": f"{tag}k{n:015d}"[:16], "source": "blog", "kind": "rss", "title": t, "url": f"https://example.com/{tag}{n}",
                                    "published": "2026-11-17T00:00:00Z", "fetched_at": scout_sources._iso(at), "excerpt": "text"}) + "\n")

    def poll_rss(self, at):
        """One real poll of the local RSS source: the three fixture items land in items.jsonl."""
        self.scout.mkdir(parents=True, exist_ok=True)
        (self.scout / "sources.json").write_text(json.dumps({"sources": [
            {"name": "blog", "kind": "rss", "url": self.base + "/rss.xml", "why": "t", "added": "x", "builtin": False}], "health": {}}))
        self.assertEqual(scout_sources.poll(at), (3, 1, 0))

    def weekly(self):
        try:
            return json.loads((self.scout / "weekly.json").read_text())
        except OSError:
            return {}

    def log(self):
        p = self.scout / "weekly.log"
        return p.read_text() if p.exists() else ""

    def outbox(self):
        d = tc_env.discord_dir("agent-board") / "outbox"
        return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))] if d.exists() else []

    def drafts(self):
        return scout_post._drafts().read()["drafts"]

    def records(self):
        lines = (self.root / "docs/superpowers/metrics/runs.jsonl").read_text().splitlines()
        return [d for d in map(json.loads, lines) if d.get("kind") == "scout"]

    def ok_plan(self, comps=("Hooks",), entries=None):
        ents = entries or [{"t": T3, "c": c} for c in comps]
        return {"evaluate": {"entries": ents}, "drafts": {c: {"slug": c.lower(), "text": spec(f"{c} thing")} for c in comps}}


class SkipRulesTest(Base):
    def test_off_file_and_env(self):
        self.add_items(SUN - 3600)
        self.scout.joinpath("off").write_text("")
        self.assertEqual(self.run_scout("weekly"), (0, "scout: off\n"))
        self.scout.joinpath("off").unlink()
        with mock.patch.dict(os.environ, {"TC_SCOUT": "0"}):
            self.assertEqual(self.run_scout("weekly"), (0, "scout: off\n"))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.weekly(), {})

    def test_week_is_the_sunday_on_or_before_now(self):
        self.assertEqual([scout.week_of(SUN + n * DAY) for n in (-1, 0, 1, 6, 7)],
                         ["2026-11-15", WEEK, WEEK, WEEK, WEEK2])

    def test_no_new_items(self):
        rc, out = self.run_scout("weekly")
        self.assertEqual((rc, out), (0, "scout: no new items\n"))
        w = self.weekly()
        self.assertEqual((w["last_week"], w["last_run_at"]), (WEEK, scout_sources._iso(SUN)))
        self.assertEqual((self.outbox(), self.calls()), ([], []))
        self.assertEqual([r["outcome"] for r in self.records()], ["no-new-items"])

    def test_items_before_the_last_run_are_not_new(self):
        self.add_items(SUN - 3 * DAY)
        self.scout.joinpath("weekly.json").write_text(json.dumps({"last_run_at": scout_sources._iso(SUN - 2 * DAY), "last_week": "2026-11-15"}))
        self.assertEqual(self.run_scout("weekly"), (0, "scout: no new items\n"))

    def test_with_no_last_run_only_the_last_seven_days_count(self):
        self.add_items(SUN - 8 * DAY)
        self.assertEqual(self.run_scout("weekly"), (0, "scout: no new items\n"))

    def test_skip_at_85_then_monday_retry_runs_once(self):
        self.add_items(SUN - 3600)
        self.plan(self.ok_plan())
        with mock.patch.object(scout.dream, "weekly_pct", return_value=85):
            rc, out = self.run_scout("weekly")
        self.assertEqual((rc, out), (0, "scout: skipped, weekly 85%\n"))
        w = self.weekly()
        self.assertEqual((w["skipped_week"], w.get("last_week")), (WEEK, None))
        self.assertIn("skipped, weekly 85%", self.log())
        self.assertEqual((self.calls(), self.outbox()), ([], []))
        self.assertEqual([r["outcome"] for r in self.records()], ["skipped"])
        with mock.patch.object(scout.dream, "weekly_pct", return_value=40):
            rc, out = self.run_scout("weekly", "--retry", now=SUN + DAY)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.weekly()["last_week"], WEEK)       # Monday's retry is still Sunday's week
        self.assertEqual([o["key"] for o in self.outbox()], ["scout-agent-board-" + WEEK])
        n = len(self.calls())
        self.assertEqual(self.run_scout("weekly", "--retry", now=SUN + DAY), (0, "scout: nothing to retry\n"))
        self.assertEqual(len(self.calls()), n)

    def test_retry_without_a_skipped_sunday_does_nothing(self):
        self.add_items(SUN - 3600)
        self.assertEqual(self.run_scout("weekly", "--retry", now=SUN + DAY), (0, "scout: nothing to retry\n"))
        self.assertEqual(self.calls(), [])

    def test_force_runs_over_the_guard(self):
        self.add_items(SUN - 3600)
        with mock.patch.object(scout.dream, "weekly_pct", return_value=99):
            rc, out = self.run_scout("weekly", "--force")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.calls("evaluate")), 1)

    def test_second_run_in_a_week_needs_force(self):
        self.add_items(SUN - 3600)
        self.assertEqual(self.run_scout("weekly")[0], 0)
        self.add_items(SUN + 3600, tag="b")
        self.assertEqual(self.run_scout("weekly", now=SUN + 2 * DAY), (0, f"scout: already ran for {WEEK}\n"))
        self.assertEqual(len(self.calls("evaluate")), 1)
        self.assertEqual(self.run_scout("weekly", "--force", now=SUN + 2 * DAY)[0], 0)
        self.assertEqual(len(self.calls("evaluate")), 2)

    def test_unknown_usage_does_not_skip(self):
        self.add_items(SUN - 3600)
        rc, out = self.run_scout("weekly")       # dream.weekly_pct unpatched: no statusline tap under the scratch TC_STATE
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.calls("evaluate")), 1)


class HappyPathTest(Base):
    def test_one_draft_two_others_one_overlap_one_dropped(self):
        self.poll_rss(SUN - 3600)
        self.plan({"evaluate": {"entries": [
            {"t": T3, "c": "Hooks", "v": "high", "e": "S", "w": "replay lost hooks"},
            {"t": T2, "c": "Statusline", "v": "high", "e": "M"},
            {"t": T1, "c": "Queue", "v": "high", "e": "S", "o": [QUEUED]},
            {"t": T1, "c": "Relay", "v": "medium", "e": "S"},
            {"t": T2, "c": "Feed", "v": "low", "e": "L"},
            {"t": "no such item", "c": "Ghost"}]},
            "drafts": {"Hooks": {"slug": "hook-replay", "text": spec("Hook replay")},
                       "Statusline": {"slug": "statusline", "text": spec("Statusline", cite="board/missing.py")}}})
        with mock.patch.object(scout_eval, "MAX_PICKS", 2):      # two picks: one drafts, one is dropped
            rc, out = self.run_scout("weekly")
        self.assertEqual(rc, 0, out)
        self.assertIn("scout: posted", out)
        ops = self.outbox()
        self.assertEqual(len(ops), 1)
        op = ops[0]
        self.assertEqual((op["op"], op["key"], op["tier"], op["mention_user"]), ("post", "scout-agent-board-" + WEEK, "progress", False))
        t = op["text"]
        self.assertIn(f"🛰 scout agent-board {WEEK}: 1 drafted, 2 other", t)
        self.assertIn("1. Hook replay — replay lost hooks", t)
        self.assertIn("Other findings:", t)
        self.assertIn(f"2. {T1} — enables Relay", t)
        self.assertIn(f"3. {T2} — enables Feed", t)
        self.assertIn("Overlaps: " + QUEUED.replace("_", "\\_") + ": could use enables Queue", t.replace("\\-", "-"))
        self.assertIn("Dropped: Statusline (cites missing board/missing.py)", t.replace("\\", ""))
        self.assertIn("tokens: 180", t)                           # evaluate 120 + one draft 60
        self.assertEqual([b["label"] for r in op["rows"] for b in r],
                         ["Approve 1", "Reject 1", "Revise 1", "File as idea 2", "Dismiss 2", "File as idea 3", "Dismiss 3"])
        # the drafted spec is attached, copied out of the scout worktree
        self.assertEqual(len(op["files"]), 1)
        self.assertEqual(Path(op["files"][0]).read_text(), spec("Hook replay"))
        self.assertTrue(op["files"][0].startswith(str(self.scout / "runs")))
        # state
        d = list(self.drafts().values())
        self.assertEqual([(x["status"], x["title"], x["week"], x["path"]) for x in d],
                         [("pending", "Hook replay", WEEK, f"docs/superpowers/specs/{WEEK}-hook-replay-design.md")])
        reported = scout_post._findings().read()["reported"]
        self.assertEqual(sorted(k.split(":")[1] for k in reported), ["feed", "relay"])
        w = self.weekly()
        self.assertEqual((w["last_week"], w["last_run_at"], w["failed_weeks"]), (WEEK, scout_sources._iso(SUN), 0))
        # the run dir
        runs = sorted(p.name for p in (self.scout / "runs").iterdir() if p.name != WEEK)
        self.assertEqual(runs, [time.strftime("%Y%m%d-%H%M", time.localtime(SUN))])
        names = sorted(p.name for p in (self.scout / "runs" / runs[0]).iterdir())
        self.assertEqual(names, ["context-pack.md", "evaluate.json", "items.json", "model-output-evaluate.txt"])
        self.assertEqual(len(json.loads((self.scout / "runs" / runs[0] / "items.json").read_text())), 3)
        self.assertIn(QUEUED, (self.scout / "runs" / runs[0] / "context-pack.md").read_text())
        # the model steps: evaluate in the run dir with the repo added, drafts in the scout worktree of the real repo
        ev = self.calls("evaluate")
        self.assertEqual((len(ev), ev[0]["cwd"]), (1, str(self.scout / "runs" / runs[0])))
        self.assertEqual(ev[0]["argv"][ev[0]["argv"].index("--add-dir") + 1], str(self.root))
        wt = str(self.root / ".claude" / "worktrees" / f"scout-{WEEK}")
        self.assertEqual([(c["component"], c["cwd"]) for c in self.calls("draft")], [("Hooks", wt), ("Statusline", wt)])
        # git: main untouched, one commit on scout/<week> with the trailer
        self.assertEqual(git(self.root, "rev-parse", "main"), self.main_head)
        self.assertEqual(git(self.root, "rev-list", "--count", f"main..scout/{WEEK}"), "1")
        self.assertIn("Scout-Item: " + d[0]["key"], git(self.root, "log", "-1", "--format=%B", f"scout/{WEEK}"))
        # metrics
        rec = self.records()
        self.assertEqual(len(rec), 1)
        r = rec[0]
        self.assertEqual({k: r[k] for k in ("outcome", "items", "findings", "drafts", "dropped", "cost_usd")},
                         {"outcome": "posted", "items": 3, "findings": 5, "drafts": 1, "dropped": 1, "cost_usd": 2.0})
        self.assertEqual(r["tokens"], {"evaluate": EVAL_USAGE, "draft": [DRAFT_USAGE]})
        self.assertIsInstance(r["duration_s"], int)
        self.assertRegex(r["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")

    def test_no_metrics_file_no_record(self):
        git(self.root, "rm", "-q", "docs/superpowers/metrics/runs.jsonl")
        git(self.root, "commit", "-q", "-m", "no metrics")
        self.add_items(SUN - 3600)
        self.assertEqual(self.run_scout("weekly")[0], 0)
        self.assertFalse((self.root / "docs/superpowers/metrics/runs.jsonl").exists())

    def test_revision_is_redrafted_first_and_counts_toward_three(self):
        self.add_items(SUN - 3600)
        self.plan(self.ok_plan())
        self.assertEqual(self.run_scout("weekly")[0], 0)
        (did,) = self.drafts()
        rc, out = self.run_scout("revise", did, "--note", "make it shorter")
        self.assertEqual((rc, out), (0, "revise\n"))
        self.assertEqual((self.drafts()[did]["status"], self.drafts()[did]["note"]), ("revise", "make it shorter"))
        self.add_items(SUN + 6 * DAY, tag="b")
        comps = ("Alpha", "Beta", "Gamma")
        p = self.ok_plan(comps)
        p["drafts"]["hooks"] = {"slug": "hooks", "text": spec("Hooks thing, shorter")}     # the stored component is lowercased
        self.plan(p)
        rc, out = self.run_scout("weekly", now=SUN + 7 * DAY)
        self.assertEqual(rc, 0, out)
        d = self.drafts()
        self.assertEqual(d[did]["status"], "superseded")
        self.assertEqual((d[did + "-r1"]["status"], d[did + "-r1"]["title"], d[did + "-r1"]["week"]), ("pending", "Hooks thing, shorter", WEEK))
        calls = self.calls("draft")[1:]
        self.assertEqual([c["component"] for c in calls], ["hooks", "Alpha", "Beta"])   # the revision, then two picks: three in all
        self.assertIn("Their note: make it shorter", calls[0]["stdin"])
        posts = [o for o in self.outbox() if o["op"] == "post"]
        self.assertEqual([o["key"] for o in posts],
                         ["scout-agent-board-" + WEEK, f"scout-agent-board-{WEEK}-{did}-r1", "scout-agent-board-" + WEEK2])
        self.assertIn(f"{WEEK2}: 2 drafted, 1 other", posts[-1]["text"])

    def test_runs_keep_the_last_eight(self):
        for n in range(10):
            (self.scout / "runs" / f"202609{n + 10:02d}-0700").mkdir(parents=True)
        self.add_items(SUN - 3600)
        self.assertEqual(self.run_scout("weekly")[0], 0)
        runs = sorted(p.name for p in (self.scout / "runs").iterdir() if p.name != WEEK)
        self.assertEqual(len(runs), 8)
        self.assertEqual(runs[-1], time.strftime("%Y%m%d-%H%M", time.localtime(SUN)))
        self.assertEqual(runs[0], "20260913-0700")


class FailureTest(Base):
    def test_two_failed_sundays_post_one_critical_line(self):
        self.plan({"evaluate": {"exit": 3}})
        for n, week in enumerate((WEEK, WEEK2, "2026-12-06")):
            now = SUN + 7 * n * DAY
            self.add_items(now - 3600, tag=str(n))
            rc, out = self.run_scout("weekly", now=now)
            self.assertEqual((rc, out), (1, "scout: failed: model exit 3\n"))
            self.assertEqual(self.weekly()["failed_weeks"], n + 1)
            self.assertNotEqual(self.weekly().get("last_week"), week)
            ops = self.outbox()
            self.assertEqual(len(ops), 0 if n == 0 else 1)
        self.assertEqual(ops[0], {"op": "post", "tier": "critical", "mention_user": True,
                                  "text": "🛰 scout: two Sundays failed — model exit 3", "key": "scout-agent-board-fail-" + WEEK2})
        self.assertEqual(self.log().count("failed: model exit 3"), 3)
        self.assertEqual([r["outcome"] for r in self.records()], ["failed"] * 3)
        self.assertEqual(self.drafts(), {})

    def test_every_draft_failing_on_the_model_is_a_failed_week_and_a_good_week_resets(self):
        self.add_items(SUN - 3600)
        self.plan({"evaluate": {"entries": [{"t": T1, "c": "Hooks"}, {"t": T2, "c": "Feed"}]},
                   "drafts": {"Hooks": {"exit": 1}, "Feed": {"exit": 1}}})
        rc, out = self.run_scout("weekly")
        self.assertEqual((rc, out), (1, "scout: failed: model exit 1\n"))
        self.assertEqual((self.weekly()["failed_weeks"], self.outbox()), (1, []))
        self.assertIn("failed: model exit 1", self.log())
        self.add_items(SUN + 6 * DAY, tag="b")
        self.plan(self.ok_plan())
        self.assertEqual(self.run_scout("weekly", now=SUN + 7 * DAY)[0], 0)
        self.assertEqual(self.weekly()["failed_weeks"], 0)

    def test_a_dropped_draft_is_not_a_failed_week(self):
        self.add_items(SUN - 3600)
        self.plan({"evaluate": {"entries": [{"t": T1, "c": "Hooks"}]},
                   "drafts": {"Hooks": {"slug": "hooks", "text": spec("Hooks", cite="board/missing.py")}}})
        rc, out = self.run_scout("weekly")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.weekly()["failed_weeks"], 0)
        self.assertIn("0 drafted, 0 other", self.outbox()[0]["text"])
        self.assertIn("Dropped:", self.outbox()[0]["text"])


class DryRunTest(Base):
    def snap(self):
        return {"scout": tree(self.scout), "state": tree(self.t / "state"), "refs": git(self.root, "for-each-ref"),
                "worktrees": git(self.root, "worktree", "list"), "status": git(self.root, "status", "--porcelain", "--untracked-files=all"),
                "repo": {k: v for k, v in tree(self.root).items() if not k.startswith(".git/")}}

    def test_dry_run_prints_the_post_and_writes_nothing(self):
        self.poll_rss(SUN - 3600)
        self.plan(self.ok_plan(("Hooks", "Feed", "Relay"), entries=[{"t": T3, "c": "Hooks"}, {"t": T2, "c": "Feed", "e": "M"},
                                                                     {"t": T1, "c": "Relay", "e": "L"}, {"t": T1, "c": "Bar", "v": "low"}]))
        before = self.snap()
        rc, out = self.run_scout("weekly", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.snap(), before)                 # SCOUT_DIR, the outbox (under TC_STATE), refs, worktrees, files
        self.assertFalse((tc_env.discord_dir("agent-board") / "outbox").exists())
        self.assertIn(f"🛰 scout agent-board {WEEK}: 3 drafted, 1 other", out)
        self.assertIn("1. Hooks thing — enables Hooks", out)
        self.assertIn("buttons: Approve 1 | Reject 1 | Revise 1 | Approve 2", out)
        # every step ran, the model steps included; the drafts ran in a worktree of a --shared clone, not of the real repo
        self.assertEqual(len(self.calls("evaluate")), 1)
        dr = self.calls("draft")
        self.assertEqual(len(dr), 3)
        for c in dr:
            self.assertFalse(c["cwd"].startswith(str(self.root) + os.sep), c["cwd"])
            self.assertTrue(c["cwd"].endswith(f"/.claude/worktrees/scout-{WEEK}"), c["cwd"])
            self.assertEqual(c["alternates"].strip(), str(self.root / ".git" / "objects"))
        # the clone is gone; the dry-run state copy is kept and named, with the drafted spec in it
        kept = [l.split(": ", 1)[1] for l in out.splitlines() if l.startswith("dry-run dir: ")]
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].startswith(str(self.t / "tmpdir")), kept[0])
        self.assertEqual(sorted(p.name for p in Path(kept[0]).parent.iterdir()), ["scout"])
        files = [l.split(": ", 1)[1] for l in out.splitlines() if l.startswith("file: ")]
        self.assertEqual(len(files), 3)
        self.assertEqual(Path(files[0]).read_text(), spec("Hooks thing"))
        self.assertEqual(os.environ["TC_SCOUT_DIR"], str(self.scout))

    def test_dry_run_after_a_real_week_leaves_its_state_alone(self):
        self.add_items(SUN - 3600)
        self.plan(self.ok_plan())
        self.assertEqual(self.run_scout("weekly")[0], 0)
        self.add_items(SUN + 6 * DAY, tag="b")
        self.plan(self.ok_plan(("Alpha",)))
        before = self.snap()
        rc, out = self.run_scout("weekly", "--dry-run", now=SUN + 7 * DAY)
        self.assertEqual(rc, 0, out)
        self.assertIn(f"{WEEK2}: 1 drafted", out)
        self.assertEqual(self.snap(), before)

    def test_dry_run_names_a_waiting_revision_and_posts_nothing(self):
        self.add_items(SUN - 3600)
        self.plan(self.ok_plan())
        self.assertEqual(self.run_scout("weekly")[0], 0)
        (did,) = self.drafts()
        self.assertEqual(self.run_scout("revise", did)[0], 0)
        self.add_items(SUN + 6 * DAY, tag="b")
        self.plan(self.ok_plan(("Alpha",)))
        before, ncalls = self.snap(), len(self.calls("draft"))
        rc, out = self.run_scout("weekly", "--dry-run", now=SUN + 7 * DAY)
        self.assertEqual(rc, 0, out)
        self.assertIn(f"would redraft: {did} Hooks thing", out)
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.drafts()[did]["status"], "revise")
        self.assertEqual([c["component"] for c in self.calls("draft")[ncalls:]], ["Alpha"])

    def test_dry_run_of_a_failing_week_writes_nothing(self):
        self.add_items(SUN - 3600)
        self.scout.joinpath("weekly.json").write_text(json.dumps({"failed_weeks": 1}))
        self.plan({"evaluate": {"exit": 3}})
        before = self.snap()
        rc, out = self.run_scout("weekly", "--dry-run")
        self.assertEqual(rc, 1)
        self.assertIn("scout: failed: model exit 3", out)
        self.assertEqual(self.snap(), before)

    def test_dry_run_with_no_scout_dir_creates_none(self):
        rc, out = self.run_scout("weekly", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("scout: no new items", out)
        self.assertFalse(self.scout.exists())


class CliTest(Base):
    def test_tmux_ctl_scout_runs_outside_tmux(self):
        env = dict(os.environ, **self.env)
        env.pop("TMUX", None)
        env["TMUX"] = ""
        p = subprocess.run(["zsh", str(REPO / "bin" / "tmux-ctl"), "scout", "source", "list"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = [l.split("\t") for l in p.stdout.splitlines()]
        self.assertEqual(len(rows), len(scout_sources.DEFAULT_SOURCES))
        self.assertEqual(rows[0][:2], ["claude-code-changelog", "changelog_md"])
        self.assertTrue((self.scout / "sources.json").is_file())

    def test_source_refusal_exits_2(self):
        rc, out = self.run_scout("source", "add", "x", "--kind", "nope", "--url", "https://example.com", root=False)
        self.assertEqual(rc, 2)
        self.assertTrue(out.startswith("scout: "), out)

    def test_poll_off(self):
        with mock.patch.dict(os.environ, {"TC_SCOUT": "0"}):
            self.assertEqual(self.run_scout("poll", root=False), (0, "scout: off\n"))

    def test_pack_prints_the_context_pack(self):
        rc, out = self.run_scout("pack")
        self.assertEqual(rc, 0)
        self.assertIn("## Specs", out)
        self.assertIn(f"{QUEUED} — Queued thing — queued", out)

    def test_approve_copies_the_spec_to_main(self):
        self.add_items(SUN - 3600)
        self.plan(self.ok_plan())
        self.assertEqual(self.run_scout("weekly")[0], 0)
        git(self.root, "commit", "-q", "-m", "metrics", "--", "docs/superpowers/metrics/runs.jsonl")
        (did,) = self.drafts()
        rc, out = self.run_scout("approve", did)
        self.assertEqual((rc, out), (0, "approved\n"))
        rel = f"docs/superpowers/specs/{WEEK}-hooks-design.md"
        self.assertEqual(git(self.root, "show", f"main:{rel}"), spec("Hooks thing").strip())
        line = json.loads((self.scout / "approved.jsonl").read_text())
        self.assertEqual((line["spec"], line["consumed"]), (rel, False))
        self.assertEqual(self.run_scout("approve", did), (0, "already approved\n"))
        self.assertEqual(git(self.root, "rev-list", "--count", f"{self.main_head}..main"), "2")

    def test_approve_again_copies_a_spec_that_was_waiting_for_main(self):
        self.add_items(SUN - 3600)
        self.plan(self.ok_plan())
        self.assertEqual(self.run_scout("weekly")[0], 0)
        git(self.root, "commit", "-q", "-m", "metrics", "--", "docs/superpowers/metrics/runs.jsonl")
        (did,) = self.drafts()
        git(self.root, "checkout", "-q", "-b", "feature")                  # main is busy: the copy waits
        self.assertEqual(self.run_scout("approve", did), (0, "approved, waiting for main\n"))
        git(self.root, "checkout", "-q", "main")
        self.assertEqual(self.run_scout("approve", did), (0, "approved\n"))
        self.assertTrue((self.root / f"docs/superpowers/specs/{WEEK}-hooks-design.md").is_file())

    def test_reject_stores_the_reason_and_dismisses(self):
        self.add_items(SUN - 3600)
        self.plan(self.ok_plan())
        self.assertEqual(self.run_scout("weekly")[0], 0)
        (did,) = self.drafts()
        self.assertEqual(self.run_scout("reject", did, "--note", "not now"), (0, "rejected\n"))
        d = self.drafts()[did]
        self.assertEqual((d["status"], d["reason"], d["decided_by"]), ("rejected", "not now", "cli"))
        self.assertIn(d["key"], scout_post._findings().read()["dismissed"])

    def test_unknown_id_and_unknown_command(self):
        rc, out = self.run_scout("approve", "nope")
        self.assertEqual((rc, out), (1, "scout: unknown\n"))
        self.assertEqual(self.run_scout("frobnicate", root=False)[0], 2)

    def test_redraft_now(self):
        self.add_items(SUN - 3600)
        self.plan(self.ok_plan())
        self.assertEqual(self.run_scout("weekly")[0], 0)
        (did,) = self.drafts()
        self.assertEqual(self.run_scout("redraft", did), (1, f"scout: {did} not redrafted\n"))   # not in revise
        self.assertEqual(self.run_scout("revise", did)[0], 0)
        p = self.ok_plan()
        p["drafts"]["hooks"] = {"slug": "hooks", "text": spec("Hooks again")}
        self.plan(p)
        self.assertEqual(self.run_scout("redraft", did), (0, f"redrafted {did} as {did}-r1\n"))
        self.assertEqual(self.drafts()[did + "-r1"]["title"], "Hooks again")


if __name__ == "__main__":
    unittest.main()
