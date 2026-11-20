import json, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import metrics_tasks  # noqa: E402

# Fixture lines are copied verbatim from real ledgers, none edited:
#   docs/superpowers/ledgers/2026-11-16-discord-replaces-telegram/progress.md  (DISCORD: dc-launch did Tasks 1 and 2)
#   docs/superpowers/ledgers/2026-11-11-queue-metrics/progress.md               (QM, FRESH, MULTI, and the two minor lines in FINDINGS)
# FINDINGS also holds two Important lines the queue-metrics ledger lacks, verbatim from
#   docs/superpowers/ledgers/2026-10-28-overseer/progress.md                    (Task 10: Important: ...)
#   docs/superpowers/ledgers/2026-10-28-shared-project-context/progress.md      (Task 1: fix round 1/5 dispatched (Important: ...)
DISCORD = """\
Task 1: dispatched dc-launch (sonnet, base 22b8f60)
Task 1: green check ok; review dispatched dc-review (4e9d2cf..28b98dd)
Task 1: minor (deferred): has-token accepts a whitespace/quoted value; cache rewrite resets file mode to 0600; mtime-check test portability note
Task 1: complete (commits 4e9d2cf..28b98dd, review clean)
Task 2: dispatched dc-launch (sonnet, base 5f45fc3)
Task 2: green check ok; review dispatched dc-review (b1920d7..0bc8efc)
Task 2: minor (deferred): pair uses unvalidated senderId as a filename (approved/<id>); token drops stdin lines after the first silently
Task 2: complete (commits b1920d7..0bc8efc, review clean)
"""

QM = """\
Task 1: dispatched qm-impl (sonnet/standard), base 12862a6
Task 1: review dispatched to qm-rev (sonnet/standard), package review-12862a6..23b2afb.diff
Task 1: complete (commits 12862a6..23b2afb, review clean)
Task 2: dispatched qm-impl, base 23b2afb
Task 2: review dispatched to qm-rev, package review-23b2afb..5e8e5b2.diff
Task 2: review spec ❌ — 1 Important (merge stored as {commit,at}, spec §3: commit or null)
Task 2: minor (deferred): dead code (plan_text, if/pass, inline import, setUp loop)
Task 2: minor (deferred): branch --contains picks first non-main branch arbitrarily
Task 2: fix round 1/5 dispatched to qm-impl (FIX_BASE 5e8e5b2)
Task 2: fix commit a5a9a9e (16 OK rc=0; board 6 known FAIL); scoped re-review dispatched to qm-rev
Task 2: fix round 1/5 (3 addressed, 1 new open — branch --contains guess picks another spec's branch when plan is on main; commits 5e8e5b2..a5a9a9e)
Task 2: fix round 2/5 dispatched to qm-impl (FIX_BASE a5a9a9e)
Task 2: fix commits fe86c0d+539ddfc (17 OK rc=0); scoped re-review round 2 dispatched to qm-rev
Task 2: fix round 2/5 (1 addressed, 0 open; commits 3a29282..539ddfc)
Task 2: complete (commits 23b2afb..539ddfc excl. 3a29282, review clean)
Task 3: dispatched qm-impl, base a5a9a9e (T2 re-review in parallel)
Task 3: review dispatched to qm-rev, package review-a5a9a9e..3a29282.diff
Task 3: complete (commits a5a9a9e..3a29282, review clean)
"""

FINDINGS = """\
Task 10: Important: overseer read-only claim unsupported — --settings merges with ~/.claude/settings.json, whose allow list has Bash(tmux-ctl:*) (and any other user allows), so undenied tmux-ctl subcommands (_append writes an arbitrary file at bin/tmux-ctl:321, _done, _relay_failed) are allowed and the bare-overview probe proves nothing
Task 1: fix round 1/5 dispatched (Important: _insert newline fusion; plus stale _locked() comment), FIX_BASE 08c21c6
Task 2: minor (deferred): dead code (plan_text, if/pass, inline import, setUp loop)
Task 2: minor (deferred): branch --contains picks first non-main branch arbitrarily
"""

REVIEW_LINES = """\
Task 3: review ❌ spec (1 Important: graph→list fallback when cards <16 cells, unruled, untested), quality Approved
Task 3: review spec ✅ quality needs fixes (Important: TERM trap orphans job processes) — fix round 1 sent to fts-impl with M1,M2,M5,M6; FIX_BASE 18cc4e8
Task 4: review spec ❌ — 3 Important (failed-command span drops failed record; union only with --usage-db; limits end by spec path)
"""

# Structure copied from docs/superpowers/plans/2026-10-16-handoff-relay-artifacts-panel.md, Tasks 11-13 (Task 12 is the one
# plan that opens a four-backtick fence; its body holds ``` fences and `## ` headings); prose trimmed.
PLAN_SECTIONS = """\
### Task 11: Board Ideas box and Activity drawer

- [ ] **Step 1: Verify with the grep commands, then report.**

```json:metadata
{"files": ["board/server.py"]}
```

---

### Task 12: Handoff skill: checkpoint, Team section, confirm, relay

- [ ] **Step 2: Write `SKILL.md`**

````markdown
---
name: handoff
---

## 1. Checkpoint the team (skip if you have no teammates)

```
Handoff saved: <absolute path>
```
````

- [ ] **Step 4: Verify with the grep commands, then report.**

```json:metadata
{"files": ["~/.claude/skills/handoff/SKILL.md"]}
```

---

### Task 13: Prompt and doc updates

## Starting from a handoff

```json:metadata
{"files": ["x"]}
```
"""

FRESH = 'Task 6: fix round 1/5 dispatched to fresh qm-fix (sonnet/standard; qm-impl shut down) (FIX_BASE 5fa3176)'
MULTI = 'Task 4: fix round 1/5 (3 addressed, 0 open; commits 00574a4..b9ef776 + 2e39ac9..518d841)'

PRICES = {"default_context": 200000, "models": {
    "claude-sonnet-5": {"input": 3, "output": 15, "cache_read": 0.3, "cache_write_5m": 3.75, "cache_write_1h": 6, "context": 200000},
    "claude-haiku-5": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write_5m": 1.25, "cache_write_1h": 2, "context": 200000},
}}
ROUTING = {"mechanical": "haiku", "standard": "sonnet", "frontier": "fable"}


def row(ts, agent, model="claude-sonnet-5", out=1000, inp=0, cr=0, cw5=0, cw1=0, side=0, sub=0):
    # real row shape (usage index `calls`): a worktree cwd, git_branch 'main' (not the queue branch), team set
    return {"request_id": "r", "session_id": "s", "ts": float(ts), "model": model, "effort": "medium", "agent_name": agent,
            "team_name": "t", "git_branch": "main", "cwd": "/root/.claude/worktrees/gone", "sidechain": side,
            "subagent_file": sub, "input": inp, "output": out,
            "cache_read": cr, "cache_write_5m": cw5, "cache_write_1h": cw1}


def tasks_json(*specs):
    """specs: (subject, tier, extra description)."""
    ts = []
    for i, (subject, tier, extra) in enumerate(specs):
        desc = "**Goal:** x\n" + extra + '\n```json:metadata\n{"modelTier": "%s"}\n```' % tier
        ts.append({"id": i, "subject": subject, "status": "completed", "description": desc})
    return json.dumps({"planPath": "p.md", "tasks": ts})


def build(progress, tasks, rows, ends=None, run_end=None, plan_text=None):
    return metrics_tasks.build_task_lines(
        "docs/superpowers/specs/s.md", "2026-11-16-1", tasks, progress, ROUTING, rows,
        (ends or {}).get, run_end, prices=PRICES, plan_text=plan_text)


class TestParseLedger(unittest.TestCase):
    def test_fix_rounds_max_not_count(self):
        t = metrics_tasks.parse_ledger(QM)[2]
        self.assertEqual(t["fix_rounds"], 2)  # rounds 1 and 2, each named on 2-3 lines; counting lines would give 6

    def test_findings_counts(self):
        led = metrics_tasks.parse_ledger(FINDINGS)
        self.assertEqual(led[10]["findings"], {"critical": 0, "important": 1, "minor": 0})  # `Important:` line
        self.assertEqual(led[1]["findings"], {"critical": 0, "important": 1, "minor": 0})  # fix dispatch (Important: ...)
        self.assertEqual(led[2]["findings"], {"critical": 0, "important": 0, "minor": 2})
        # severity on the review-result line counts: QM's "review spec ❌ — 1 Important (...)"
        self.assertEqual(metrics_tasks.parse_ledger(QM)[2]["findings"]["important"], 1)

    def test_findings_on_review_result_lines(self):
        # verbatim: tasks-window Task 3 (paren form), fast-test-suite Task 3 ("quality needs fixes (Important: ...)"),
        # queue-metrics Task 4 ("— 3 Important (...)")
        led = metrics_tasks.parse_ledger(REVIEW_LINES)
        self.assertEqual(led[3]["findings"]["important"], 1 + 1)   # two Task 3 lines, one Important each
        self.assertEqual(led[4]["findings"]["important"], 3)

    def test_fix_dispatch_severity_not_double_counted(self):
        # the review line named the Important; the fix dispatch that answers it names it again: one finding
        led = metrics_tasks.parse_ledger(
            "Task 1: review spec ❌ (Important: a)\n"
            "Task 1: fix round 1/5 dispatched to w (Important: a)\n"
            "Task 1: review spec ✅ quality needs fixes (Critical: b)\n"
            "Task 1: fix round 2/5 dispatched to w (Critical: b)\n"
            "Task 2: fix round 1/5 dispatched to w (Important: d)\n")   # no review line: the dispatch counts
        self.assertEqual(led[2]["findings"]["important"], 1)
        self.assertEqual(led[1]["findings"], {"critical": 1, "important": 1, "minor": 0})

    def test_minor_deferred_body_is_not_parsed(self):
        led = metrics_tasks.parse_ledger(
            "Task 1: review dispatched to r (a..b)\n"
            "Task 1: minor (deferred, part 2): flags need re-review; review dispatched later; fix round 9 (Important: x)\n"
            "Task 1: minor (deferred): y\n")
        t = led[1]
        self.assertEqual((t["review_rounds"], t["fix_rounds"], t["findings"]), (1, 0, {"critical": 0, "important": 0, "minor": 2}))

    def test_owners_models_commit_end_complete(self):
        led = metrics_tasks.parse_ledger(DISCORD)
        self.assertEqual(led[1]["owners"], ["dc-launch"])
        self.assertEqual(led[1]["dispatch_models"], ["sonnet"])
        self.assertEqual(led[1]["commit_end"], "28b98dd")
        self.assertTrue(led[2]["complete"])
        self.assertEqual(led[2]["review_rounds"], 1)
        q = metrics_tasks.parse_ledger(QM)
        self.assertEqual(q[2]["owners"], ["qm-impl"])
        self.assertEqual(q[2]["dispatch_models"], [])  # "dispatched qm-impl, base" names no model
        self.assertEqual(q[2]["commit_end"], "539ddfc")  # review lines' A..B ranges are not commits
        self.assertEqual(q[2]["review_rounds"], 3)  # review dispatched + 2 scoped re-review dispatches

    def test_fix_dispatch_group_limited(self):
        led = metrics_tasks.parse_ledger("Task 3: fix round 1/5 dispatched to ovr-fix (fresh, standard)\n")
        self.assertEqual(led[3]["owners"], ["ovr-fix"])
        self.assertEqual(led[3]["dispatch_models"], [])

    def test_fresh_word_skipped_in_owner(self):
        t = metrics_tasks.parse_ledger(FRESH)[6]
        self.assertEqual(t["owners"], ["qm-fix"])
        self.assertEqual(t["dispatch_models"], ["sonnet"])

    def test_commit_end_is_last_range_on_line(self):
        self.assertEqual(metrics_tasks.parse_ledger(MULTI)[4]["commit_end"], "518d841")

    def test_review_ranges_recorded(self):
        t = metrics_tasks.parse_ledger(QM)[2]
        self.assertEqual(t["review_ends"], ["5e8e5b2"])


class TestBuild(unittest.TestCase):
    def two(self):
        return tasks_json(("Task 1: a", "standard", ""), ("Task 2: b", "standard", ""))

    def test_shared_owner_rows_split_by_commit_end(self):
        rows = [row(900, "dc-launch", out=1000), row(1500, "dc-launch", out=2000), row(2500, "dc-launch", out=4000)]
        r = build(DISCORD, self.two(), rows, ends={"28b98dd": 1000, "0bc8efc": 2000})
        self.assertEqual([r[0]["tokens"], r[1]["tokens"]], [1000, 6000])
        self.assertEqual(r[0]["ended_at"], "1970-01-01T00:15:00Z")
        self.assertEqual(r[1]["started_at"], "1970-01-01T00:25:00Z")

    def test_reviewer_rows_not_in_task_tokens(self):
        rows = [row(900, "dc-launch", out=1000), row(1100, "dc-review", out=500), row(2100, "dc-review", out=700)]
        r = build(DISCORD, self.two(), rows, ends={"28b98dd": 1000, "0bc8efc": 2000})
        self.assertEqual(r[0]["tokens"], 1000)
        self.assertEqual(r[0]["review_tokens"], 500)
        self.assertIsNone(r[1]["tokens"])
        self.assertEqual(r[1]["review_tokens"], 700)
        self.assertAlmostEqual(r[0]["review_usd"], 500 * 15 / 1e6)
        self.assertAlmostEqual(r[0]["usd"], 1000 * 15 / 1e6)

    def test_shared_reviewer_rows_follow_review_dispatch(self):
        # qm-rev reviews Tasks 1-3; Task 2's review (range end 5e8e5b2) ran before Task 2's final fix commit 539ddfc
        tasks = tasks_json(("Task 1: a", "standard", ""), ("Task 2: b", "standard", ""), ("Task 3: c", "standard", ""))
        ends = {"23b2afb": 1000, "5e8e5b2": 1500, "3a29282": 2500, "539ddfc": 3000}
        rows = [row(1100, "qm-rev", out=100), row(1600, "qm-rev", out=200),
                row(2000, "qm-rev", out=400), row(2600, "qm-rev", out=800)]
        r = build(QM, tasks, rows, ends=ends)
        self.assertEqual([t["review_tokens"] for t in r], [100, 600, 800])
        self.assertTrue(all(t["tokens"] is None for t in r))

    def test_no_rows_partial(self):
        r = build(DISCORD, self.two(), [], ends={})
        for t in r:
            self.assertIsNone(t["tokens"])
            self.assertIsNone(t["usd"])
            self.assertIsNone(t["model_used"])
            self.assertTrue(t["partial"])

    def test_rows_present_not_partial(self):
        r = build(DISCORD, self.two(), [row(900, "dc-launch")], ends={"28b98dd": 1000, "0bc8efc": 2000})
        self.assertFalse(r[0]["partial"])
        self.assertEqual(r[0]["model_used"], "claude-sonnet-5")
        self.assertEqual(r[0]["active_s"], 60)

    def test_escalated_by_dispatch_model(self):
        tasks = tasks_json(("Task 1: a", "mechanical", ""))
        led = "Task 1: dispatched dc-scrub (sonnet, base 22b8f60)\n"
        r = build(led, tasks, [row(10, "dc-scrub", model="claude-haiku-5")])
        self.assertEqual(r[0]["model_mapped"], "haiku")
        self.assertEqual(r[0]["model_used"], "claude-haiku-5")
        self.assertTrue(r[0]["escalated"])
        led2 = "Task 1: dispatched dc-scrub (haiku, base 22b8f60)\n"
        self.assertFalse(build(led2, tasks, [row(10, "dc-scrub", model="claude-haiku-5")])[0]["escalated"])
        self.assertTrue(build(led2, tasks, [row(10, "dc-scrub", model="claude-sonnet-5")])[0]["escalated"])

    def test_code_in_steps(self):
        tasks = tasks_json(("Task 1: a", "standard", "```python\nx = 1\n```"), ("Task 2: b", "standard", ""))
        r = build("", tasks, [])
        self.assertTrue(r[0]["code_in_steps"])
        self.assertFalse(r[1]["code_in_steps"])

    def test_code_in_steps_from_plan_section(self):
        # R3: the plan .md's `### Task N:` section decides; the tasks.json description (no Steps) is the fallback
        tasks = tasks_json(("Task 11: a", "standard", ""), ("Task 12: b", "standard", ""), ("Task 13: c", "standard", ""),
                           ("Task 14: d", "standard", "```python\nx = 1\n```"))
        r = build("", tasks, [], plan_text=PLAN_SECTIONS)
        # 11: only the json:metadata fence; 12: a four-backtick fence with ``` and `## ` lines inside; 13: only metadata
        self.assertEqual([t["code_in_steps"] for t in r], [False, True, False, True])   # 14 has no section: description

    def test_plan_fence_pairing_and_section_end(self):
        def one(body, nxt="### Task 2: next\n"):
            return build("", tasks_json(("Task 1: a", "standard", "```python\nx\n```")), [], plan_text="### Task 1: a\n" + body + nxt)[0]["code_in_steps"]
        self.assertFalse(one("text\n```json:metadata\n{}\n```\n", nxt="### Task 2: n\n```bash\nls\n```\n"))   # next task's fence is not ours
        self.assertFalse(one("text\n", nxt="## Later\n```bash\nls\n```\n"))                                  # a `## ` heading ends it
        self.assertTrue(one("````md\n```\n## inner\n```\n````\n"))
        self.assertFalse(one("````json:metadata\n```x\n```\n{}\n````\n"))   # the ``` inside the 4-fence is text; tag is metadata
        self.assertTrue(one("```bash\nls\n"))                                  # an unclosed fence still opened code

    def test_keys_exact(self):
        r = build(DISCORD, self.two(), [row(900, "dc-launch")])
        self.assertEqual(set(r[0]), set(
            "spec batch task_id subject tier model_mapped model_used escalated owner started_at ended_at "
            "active_s tokens usd review_tokens review_usd fix_rounds findings review_rounds outcome "
            "code_in_steps partial context_tokens missing".split()))
        self.assertEqual((r[0]["task_id"], r[0]["tier"], r[0]["owner"], r[0]["outcome"]), (1, "standard", "dc-launch", "complete"))

    def test_context_tokens_last_main_row_wins_over_larger_earlier(self):
        r = build(DISCORD, self.two(), [row(900, "dc-launch", inp=1, cr=500000), row(1000, "dc-launch", inp=2, cr=30, cw5=4, cw1=5)])
        self.assertEqual((r[0]["context_tokens"], r[0]["missing"]), (41, []))

    def test_context_tokens_skips_sidechain_and_subagent_rows(self):
        r = build(DISCORD, self.two(), [row(900, "dc-launch", cr=7), row(1000, "dc-launch", cr=999, side=1), row(1100, "dc-launch", cr=888, sub=1)])
        self.assertEqual(r[0]["context_tokens"], 7)

    def test_context_tokens_shared_owner_each_task_own_last_row(self):
        rows = [row(900, "dc-launch", cr=10), row(950, "dc-launch", cr=20), row(2500, "dc-launch", cr=300), row(2600, "dc-launch", cr=40)]
        r = build(DISCORD, self.two(), rows, ends={"28b98dd": 1000, "0bc8efc": 2000})
        self.assertEqual([r[0]["context_tokens"], r[1]["context_tokens"]], [20, 40])

    def test_context_tokens_reviewer_rows_never_supply_it(self):
        r = build(DISCORD, self.two(), [row(900, "dc-launch", cr=5), row(950, "dc-review", cr=777)], ends={"28b98dd": 1000, "0bc8efc": 2000})
        self.assertEqual(r[0]["context_tokens"], 5)
        self.assertEqual(r[1]["context_tokens"], None)

    def test_context_tokens_null_without_rows(self):
        r = build(DISCORD, self.two(), [])
        self.assertEqual((r[0]["context_tokens"], r[0]["missing"]), (None, ["context_tokens"]))

    def test_context_tokens_only_sidechain_rows_is_null(self):
        r = build(DISCORD, self.two(), [row(900, "dc-launch", cr=9, side=1)])
        self.assertEqual((r[0]["context_tokens"], r[0]["missing"]), (None, ["context_tokens"]))

    def test_task_id_falls_back_to_index(self):
        r = build("", tasks_json(("setup", "standard", "")), [])
        self.assertEqual(r[0]["task_id"], 1)

    def test_unfinished_task_outcome_is_status(self):
        r = build("Task 1: dispatched dc-launch (sonnet, base 1)\n", self.two(), [])
        self.assertEqual(r[0]["outcome"], "completed")


if __name__ == "__main__":
    unittest.main()
