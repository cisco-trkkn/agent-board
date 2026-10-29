# Night mode and teammate handover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overnight work keeps going: `tmux-ctl night on` keeps the Mac awake and makes the lead decide or park instead of asking, with a morning report; and a teammate whose context reaches its tier's budget is handed over to a fresh teammate of the same name from a checkpoint, prompted by a board line to the lead.

**Architecture:** `board/night.py` (new) owns night-mode state (`$TC_STATE/night-<project>.json` with the caffeinate pid, the session option `@tc_night=1`), the pre-flight check (waiting prompts, non-auto panes, battery) and the stop condition; `bin/tmux-ctl night` is a thin front; `board/server.py` runs a `night-watch` thread that stops caffeinate when the plan has no open task and no running test, marks 🌙 on the project and queues the handover line through the existing `CommentQueue`; `board/usage.py` gains the `teammate_context_budget` key, the tier resolution through the routing map, the 80%-of-window cap, the `teammate_budget` alert and the once-per-session notice rule; `claude/plugin/scripts/night-guard.sh` denies AskUserQuestion while `@tc_night=1`; `claude/orchestrator.md` carries the Night mode rules, the Teammate handover protocol and teammate rule 9 (`checkpoint now`); the overseer's notifier gains a `teammate_budget` event.

**Tech Stack:** Python 3.9+ standard library (unittest), zsh (tmux-ctl, tests on a scratch tmux server via `tools/tests/lib.zsh`), bash + `python3 -I` for the hook, tmux 3.8, macOS `caffeinate` / `pmset` (both optional at runtime: Linux gets no battery warning and `TC_CAFFEINATE_CMD` can name another command).

**Spec:** `docs/superpowers/specs/2026-10-28-night-mode-and-teammate-handover-design.md` (read it with this plan; the sibling specs `2026-10-28-overseer-design.md` and `2026-10-28-teams-in-one-project-design.md` define the notifier and `usage-alerts.json` interfaces this plan extends).

## Global Constraints

- **Repo:** `~/agent-board`. It is the live install (`~/.local/bin/agent-board` links into this checkout): plans execute in a worktree under `.claude/worktrees/`, never in the live checkout. Commands are in `~/agent-board/CLAUDE.md`. Conventional commits with scope: `feat(board): …`, `feat(tmux-ctl): …`, `feat(plugin): …`, `docs(rules): …`, `docs: …`.
- **Workspace:** run in a new worktree `.claude/worktrees/night-mode-and-teammate-handover` on branch `feat/night-mode-and-teammate-handover` cut from `main`; no question about working on main.
- **Precondition (fixed order of the round: shared-context, overseer, teams, night mode):** plans 1–3, `docs/superpowers/plans/2026-10-28-shared-project-context.md`, `2026-10-28-overseer.md` and `2026-10-28-teams-in-one-project.md`, have merged into `main`. This plan uses the overseer's `board/notify.py` (`conditions()` and its `add(...)` lines, Task 9) and its `usage.OPTIONAL_ALERTS`-era `thresholds()` loop (Task 1), and extends files those plans also edit (`board/usage.py`, `board/server.py`, `bin/tmux-ctl`, `bin/tmux-session-closed`, `claude/plugin/hooks/hooks.json`, `claude/plugin/.claude-plugin/plugin.json`, `claude/orchestrator.md`, `claude/plugin/skills/handoff/SKILL.md`, the docs). Nothing here may be needed by those earlier plans.
- **Anchored patch scripts, not diffs.** Because earlier plans touch the same files, every edit to an existing file in this plan is a Python script that asserts a short anchor is present exactly once and replaces it (`python3 - <<'PYEOF' … PYEOF` from the worktree root). Each script was run once by the plan author against today's `main` and reproduced the author's verified files byte for byte. If an assertion fails after the earlier merges, find the equivalent spot by meaning (the anchor's comment says what it is), apply the same replacement there, and say so in the task report; never skip the edit.
- **Commit steps** end with the attribution trailer your harness specifies; never a literal Co-Authored-By line.
- **Agents' shell is zsh** (gotchas in `~/.claude/CLAUDE.md`): quote tmux `=name` targets, brace a variable before a colon (`"=${sess}:claude"`), never name a variable `path`. Scratch tmux servers start with `-L <sock> -f /dev/null` (`tools/tests/lib.zsh` does). A suite verdict comes from the runner's summary line (`OK`/`FAILED` for unittest; `ALL PASS`/`N FAILED` for one zsh test) or, for `run-all.zsh` which prints no aggregate, from `zsh tools/tests/run-all.zsh > F; echo rc=$?` plus `grep -c '^FAIL' F`. Never from `tail`. Runs over 100 s go through `tmux-ctl run -t <secs> tests "<cmd>"`. A new `tools/tests/test_*.zsh` file is picked up by `run-all.zsh` automatically (its loop is `for f in "$dir"/test_*.zsh(N)`, read 2026-10-28).
- **Hooks** follow `claude/plugin/scripts/plan-handoff-guard.sh` and `sdd-call-guard.sh`: a bash wrapper plus `python3 -I`, `--scoped` accepted, an off switch (`TC_NIGHT_GUARD=0`), fail-open (any error exits 0). Every place that lists the hooks lists `night-guard` too (observation #102): `docs/INSTALL.md` line "How the rest reaches Claude…", `docs/ARCHITECTURE.md` Hooks table, `docs/CUSTOMIZATION.md` §6, `claude/plugin/.claude-plugin/plugin.json`, `tools/tests/test_plugin.zsh`.
- **Night-mode flag.** The session option `@tc_night=1` lives on the project's canonical tmux session (`tmux-ctl`'s `FEEDKEY`: `#{session_group}`, else the session name). The board's `_web-*` views are grouped sessions that share the windows but **not** the option (probe 2026-10-28, tmux 3.8: `display -p -t '=np_view:' '#{@tc_night}'` → empty while `show-options -qv -t '=np:' @tc_night` → `1`), so every reader resolves the canonical session first. `night-<project>.json` in `TC_STATE` is the board's source of truth for 🌙 and for the watch thread; the option is what the hook and the lead's rules read.
- **Caffeinate is killed by its recorded pid only, and only while `ps -o command= -p <pid>` still shows the recorded command's basename** (`night.pid_matches`). `TC_CAFFEINATE_CMD` replaces `caffeinate -i` (tests use `sleep 300`). The stop condition "no open plan task and no running test" must hold on two consecutive 30 s polls (`night.STOP_AFTER_POLLS = 2`, `server.NIGHT_WATCH_S = 30`); a `tmux-ctl run` record without an exit code older than 6 h (`night.RUN_STALE_S`) is a crashed run, not work; "no live task list" (planview `active: False`) counts as no open task.
- **Budget rule** (spec): `teammate_context_budget` default `{"mechanical": 150000, "standard": 300000, "frontier": 300000}`; a partial object keeps the other tiers' defaults; an invalid value (not an object, empty, unknown tier, non-positive or non-numeric value) is reported in the thresholds warning and the default applies. Tier = the teammate's model family through `<repo>/docs/superpowers/model-routing.json` (`{tier: model}` inverted, over the defaults haiku→mechanical, sonnet→standard, fable/opus→frontier); a model whose window (`board/prices.json`, else `default_context`) is smaller than the budget gets 80% of its window. The alert `teammate_budget` fires at `context * 100 >= 85 * budget` (exact integer comparison, not a rounded percentage). The lead's line is exactly `[Board] Teammate <name> is at <N>K context (<tier> budget <B>K): hand it over.` with `N = context // 1000`, `B = budget // 1000`; once per teammate session, once more if still over 100% ten minutes (600 s) later, never a third time.
- **Delivery semantics of the handover line:** the existing `CommentQueue` (`board/artifacts.py`) holds a line while the lead's pane shows a prompt (`status == "waiting"`), is not a Claude pane, or has typed text in its input; it types the line otherwise (a working Claude queues typed input as its next message). `add_line` drops an identical line already waiting. Repeats are prevented upstream by `usage.HandoverNotices` (in-memory, per board process: a board restart may send one more notice per teammate), out-of-order builds cannot happen (one `build_state` at a time under `_state_lock`), and concurrent `/api/state` requests share one cached build (`STATE_TTL`).
- **Path parameters for test isolation** (observation #101): `night.py` takes `state_dir`, `home`, `tmux` (a `tmux(*args, check=False) -> stdout` callable) and `root_of`; tests write the real relative layout: `<home>/sessions/*.json`, `<home>/tasks/session-<id8>/*.json`, `<state>/artifacts-<project>.jsonl`, `<state>/runs-<project>.jsonl`, `<state>/night-<project>.json`, `<repo>/docs/superpowers/model-routing.json`. Board tests set `TC_STATE` to a temp dir and never read the real HOME, state dir or board.
- **Fixtures:** the Claude status line `  ⏵⏵ auto mode on (shift+tab to cycle) · ctrl+t to hide tasks` and the working variant `… · esc to interrupt` were captured read-only from live Claude Code 2.1.312 panes on 2026-10-28; the `pmset -g batt` lines are from this Mac the same day (`Now drawing from 'AC Power'`); the AskUserQuestion payload shape is the one `test_plan_handoff_guard.zsh` copied from a real transcript. Everything else in the tests is synthetic but shape-exact and labelled so in each test module's docstring; Task 10 pairs it with read-only runs on the real `usage.sqlite`, the real routing file and the live board.
- **Facts probed at plan time (2026-10-28, this Mac):** `caffeinate -i` started with `subprocess.Popen(..., start_new_session=True)` outlives the Python process (re-parented to pid 1; `ps -o command=` shows `caffeinate -i`); `ps -o command= -p <pid>` is empty for a dead pid; a copied `/bin/sh` renamed `claude` shows as `bash` in `#{pane_current_command}` (sh re-execs bash), a copied `/bin/bash` renamed `claude` shows as `claude` after `codesign --force -s -`; `claude --help` 2.1.312 has `--permission-mode <mode>` with `auto` among the modes and the status line shows the mode as `⏵⏵ <mode> on`.
- **Model routing:** every task carries `modelTier`. The code in Tasks 2, 4, 5 and the test files is to be copied verbatim: the plan author ran it once in a scratch copy of the checkout (outside the repo), unit tests green and each named mutation red.

**User decisions (already made, spec "Decisions", 2026-10-28):**
- Pain points: sleep stops the work, and agents stop for input; reattaching is not the problem.
- Questions at night: the lead decides and logs reversible choices, and parks gated tasks until the morning report.
- Sleep: keep the Mac awake while work runs, then let it sleep (lid-closed-on-battery is out of scope).
- Handover trigger: the lead starts it, prompted by the board's alert (a teammate never hands itself over).
- Budget: per model tier.

---

## File structure

| File | Responsibility | Task |
| --- | --- | --- |
| `board/usage.py` | `teammate_context_budget` key and validation; `routing_map`, `tier_of`, `context_budget`, `teammate_budget`, `with_budget_alerts`; `HandoverNotices`, `handover_lines`; `Indexer.settings()`; `card_alerts(th, prices)` | 1 |
| `board/tests/test_usage_budget.py` (new), `board/tests/test_usage.py` (one assertion) | the budget rules, the alert, the notices | 1 |
| `board/night.py` (new) | night state file, caffeinate start/stop by recorded pid, `check()`, `open_work()`, `tick()`, CLI `on|off|status|check|_stop` | 2 |
| `board/tests/test_night.py` (new) | state, pid safety, check fixtures, tick, open_work over the real planview/activity readers, one real `caffeinate -i -t 2` (macOS) | 2 |
| `board/server.py`, `board/index.html` | `queue_handovers`, `mark_night` (🌙), `night_watch` thread, build order | 3 |
| `board/tests/test_night_server.py` (new) | the queue once / again over 100% / idle-pane delivery, the 🌙 field | 3 |
| `bin/tmux-ctl` | `night on|off|status` → `board/night.py`; help lines | 4 |
| `tools/tests/test_ctl_night.zsh` (new) | on/off/status on a scratch server with `TC_CAFFEINATE_CMD='sleep 300'`, the three warnings, pid safety, leak check | 4 |
| `claude/plugin/scripts/night-guard.sh` (new), `claude/plugin/hooks/hooks.json`, `claude/plugin/.claude-plugin/plugin.json`, `tools/tests/test_plugin.zsh` | the backstop hook and its registration | 5 |
| `tools/tests/test_night_guard.zsh` (new) | deny / silent / off switch / garbage / outside tmux / grouped view | 5 |
| `bin/tmux-session-closed`, `tools/tests/test_session_closed.zsh` | a closing project stops its recorded caffeinate pid | 6 |
| `claude/orchestrator.md`, `claude/plugin/skills/handoff/SKILL.md`, `tools/tests/test_plugin.zsh` | Night mode section, Teammate handover protocol, teammate rule 9, shared checkpoint shape | 7 |
| `docs/ARCHITECTURE.md`, `docs/INSTALL.md`, `docs/CUSTOMIZATION.md` | night mode, the hook, the env vars, the usage key, the state file | 8 |
| `board/notify.py`, `board/tests/test_notify.py`, docs | overseer event `teammate_budget` | 9 |
| `docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md` (new) | the e2e evidence | 10 |

Dependency order: 1 → 3; 2 → 3, 4, 6; 5 → 7 (both edit `test_plugin.zsh`); 4, 5 → 8; 1 → 9; everything → 10.

---

### Task 1: usage.py: budget key, tier, cap, alert, handover notices

**Goal:** `board/usage.py` reads and validates `teammate_context_budget`, resolves a teammate's tier through the project's routing map, caps the budget at 80% of a small window, adds the `teammate_budget` alert to the card alerts and the Usage report, and decides (`HandoverNotices`, `handover_lines`) when the lead gets the handover line.

**Files:**
- Modify: `board/usage.py` (`DEFAULT_ALERTS`, `_valid_threshold`, `thresholds`, new functions before `_rows`, `report`, `Indexer`, `card_alerts`)
- Modify: `board/tests/test_usage.py` (one assertion in `test_report_alerts_carry_session_name`: the 850K-context opus teammate now also carries `teammate_budget`)
- Create: `board/tests/test_usage_budget.py`

**Acceptance Criteria:**
- [ ] `usage.thresholds()` without the key gives the spec default; `{"mechanical": 50000}` merges over the default; each of `300000`, `{"mechanical": 0}`, `{"mechanical": "many"}`, `{"unknown": 1}`, `{}`, `{"standard": true}`, `[1]` is reported in the one-line warning naming `teammate_context_budget` and leaves the default, while a good key in the same file still applies.
- [ ] `tier_of(model, repo)`: defaults haiku→mechanical, sonnet→standard, fable/opus→frontier; a routing file `{"mechanical": "sonnet", "standard": "opus", …}` wins for the families it names and the rest keep the defaults; an unmapped family or an invalid file gives `None` / the defaults.
- [ ] `context_budget`: 150000/300000/300000 per tier; haiku-4-5 (200K window) with a 300K budget → 160000; an unknown model (default_context 200K) → 160000; a budget below the window is not capped.
- [ ] `teammate_budget(entry, th, prices, repo)` returns `(tier, budget, None)` at 254,999 of 300,000 and `(…, {"kind": "teammate_budget", "label": "budget 85%", "detail": "Teammate py is at 255K context (standard budget 300K): hand it over."})` at 255,000; `(None, None, None)` for a lead or an unmapped model.
- [ ] `with_budget_alerts` never mutates a snapshot entry; `card_alerts([s], live, th, prices)` puts the alert on the teammate's pane and counts it; `report()` lists it with the session name.
- [ ] `HandoverNotices.due`: True once per session id; again only when `context > budget` and ≥ 600 s after the first notice; never a third time; sessions independent. `handover_lines` yields `(session name, "[Board] " + detail)` per project for due teammates only.
- [ ] `python3 -m unittest discover -s board/tests -p 'test_usage*.py'` → `OK` (`Ran` = the count after the overseer plan, 102, plus 14 new = 116; today's main gives 112). Mutations, each run once then restored, fail the named test: `return int(budget) if window >= budget else …` → `return int(budget)` fails `test_small_window_caps_at_80_percent`; `BUDGET_ALERT_PCT = 80` fails `test_alert_at_85_percent`; the exact comparison replaced by `round(100 * ctx / budget) < BUDGET_ALERT_PCT` fails `test_alert_at_85_percent`; dropping `and context > budget` fails `test_once_then_again_only_over_100_percent_after_ten_minutes` and `test_handover_lines_per_project`; dropping `and now - st["ts"] >= self.RESEND_AFTER_S` fails `test_once_then_again_only_over_100_percent_after_ten_minutes`; `th[k] = v` instead of the merge fails `test_partial_override_merges_over_the_default`; dropping `bool(v) and` fails `test_invalid_values_warn_and_fall_back`; mutating the entry in `with_budget_alerts` fails `test_with_budget_alerts_copies_entries`; `return dict(DEFAULT_ROUTING)` in `routing_map` fails `test_routing_file_wins`; `if False:` for the role check fails `test_only_teammates_with_a_mapped_model`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_usage*.py'` → `OK`, 0 failures (`Ran 116 tests` after the overseer plan; `Ran 112` on today's main)

**Steps:**

- [ ] **Step 1: Write the failing tests.** Create `board/tests/test_usage_budget.py`:

```python
"""teammate_context_budget: the per-tier context budget for teammates, its alert and the handover notices to the lead."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import usage  # noqa: E402

PRICES = {"models": {"claude-haiku-5-5": {"context": 1000000}, "claude-haiku-4-5": {"context": 200000},
                     "claude-sonnet-5-5": {"context": 1000000}, "claude-fable-5-1": {"context": 1000000},
                     "claude-opus-5-5": {"context": 1000000}}, "default_context": 200000}


def entry(**kw):
    e = {"session_id": "t1", "name": "py", "role": "teammate", "model": "claude-sonnet-5-5", "effort": "medium",
         "agent_name": "py", "cwd": "/r", "context": 0, "context_pct": 0, "last_hour": 0.0, "total": 0.0, "alerts": []}
    e.update(kw)
    return e


class ThresholdKeyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = self.tmp / "usage-alerts.json"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_default_without_the_key(self):
        th, warn = usage.thresholds(self.p)
        self.assertEqual(th["teammate_context_budget"], {"mechanical": 150000, "standard": 300000, "frontier": 300000})
        self.assertIsNone(warn)

    def test_partial_override_merges_over_the_default(self):
        self.p.write_text('{"teammate_context_budget": {"mechanical": 50000}}')
        th, warn = usage.thresholds(self.p)
        self.assertEqual(th["teammate_context_budget"], {"mechanical": 50000, "standard": 300000, "frontier": 300000})
        self.assertIsNone(warn)
        self.assertEqual(usage.DEFAULT_ALERTS["teammate_context_budget"]["mechanical"], 150000)   # the default is not mutated

    def test_invalid_values_warn_and_fall_back(self):
        for bad in ('300000', '{"mechanical": 0}', '{"mechanical": "many"}', '{"unknown": 1}', '{}', '{"standard": true}', '[1]'):
            self.p.write_text('{"teammate_context_budget": %s, "session_total": 40}' % bad)
            th, warn = usage.thresholds(self.p)
            self.assertEqual(th["teammate_context_budget"], usage.DEFAULT_ALERTS["teammate_context_budget"], bad)
            self.assertTrue(warn and "teammate_context_budget" in warn and "\n" not in warn, (bad, warn))
            self.assertEqual(th["session_total"], 40)


class TierTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.repo)

    def routing(self, text):
        d = self.repo / "docs" / "superpowers"
        d.mkdir(parents=True, exist_ok=True)
        (d / "model-routing.json").write_text(text)

    def test_defaults_without_a_routing_file(self):
        self.assertEqual([usage.tier_of(m, self.repo) for m in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-opus-5-5")],
                         ["mechanical", "standard", "frontier", "frontier"])
        self.assertIsNone(usage.tier_of("claude-nova-1", self.repo))
        self.assertIsNone(usage.tier_of("", self.repo))

    def test_routing_file_wins(self):
        self.routing('{"mechanical": "sonnet", "standard": "opus", "frontier": "fable", "enforceEffort": true}')
        self.assertEqual(usage.tier_of("claude-sonnet-5-5", self.repo), "mechanical")
        self.assertEqual(usage.tier_of("claude-opus-5-5", self.repo), "standard")
        self.assertEqual(usage.tier_of("claude-haiku-5-5", self.repo), "mechanical")   # unmapped families keep the default

    def test_bad_routing_file_falls_back(self):
        self.routing("{nope")
        self.assertEqual(usage.tier_of("claude-sonnet-5-5", self.repo), "standard")
        self.routing('{"mechanical": 3}')
        self.assertEqual(usage.tier_of("claude-haiku-5-5", self.repo), "mechanical")


class BudgetTest(unittest.TestCase):
    TH = dict(usage.DEFAULT_ALERTS)

    def test_budget_per_tier(self):
        self.assertEqual(usage.context_budget("claude-haiku-5-5", "mechanical", self.TH, PRICES), 150000)
        self.assertEqual(usage.context_budget("claude-sonnet-5-5", "standard", self.TH, PRICES), 300000)
        self.assertEqual(usage.context_budget("claude-fable-5-1", "frontier", self.TH, PRICES), 300000)

    def test_small_window_caps_at_80_percent(self):
        th = {**self.TH, "teammate_context_budget": {"mechanical": 300000, "standard": 300000, "frontier": 300000}}
        self.assertEqual(usage.context_budget("claude-haiku-4-5", "mechanical", th, PRICES), 160000)   # 200K window
        self.assertEqual(usage.context_budget("claude-haiku-4-5", "mechanical", self.TH, PRICES), 150000)   # budget below the window: no cap
        self.assertEqual(usage.context_budget("claude-nova-1", "standard", self.TH, PRICES), 160000)   # default_context 200K

    def test_alert_at_85_percent(self):
        tier, budget, alert = usage.teammate_budget(entry(context=254_999), self.TH, PRICES, "/r")
        self.assertEqual((tier, budget, alert), ("standard", 300000, None))
        tier, budget, alert = usage.teammate_budget(entry(context=255_000), self.TH, PRICES, "/r")
        self.assertEqual(alert, {"kind": "teammate_budget", "label": "budget 85%",
                                 "detail": "Teammate py is at 255K context (standard budget 300K): hand it over."})

    def test_only_teammates_with_a_mapped_model(self):
        self.assertEqual(usage.teammate_budget(entry(role="lead", agent_name=None, context=900_000), self.TH, PRICES, "/r"), (None, None, None))
        self.assertEqual(usage.teammate_budget(entry(model="claude-nova-1", context=900_000), self.TH, PRICES, "/r"), (None, None, None))

    def test_with_budget_alerts_copies_entries(self):
        hot, cold = entry(session_id="a", context=290_000, alerts=[{"kind": "burn", "label": "x", "detail": "y"}]), entry(session_id="b", context=10)
        out = usage.with_budget_alerts([hot, cold], self.TH, PRICES, "/r")
        self.assertEqual([a["kind"] for a in out[0]["alerts"]], ["burn", "teammate_budget"])
        self.assertEqual([a["kind"] for a in hot["alerts"]], ["burn"])   # the snapshot entry is untouched
        self.assertIs(out[1], cold)

    def test_card_alerts_and_report_carry_the_alert(self):
        s = {"name": "proj", "path": "/r", "windows": [{"name": "✦ py", "teammate": True, "worker": False, "panes": [{"id": "%7", "path": "/r"}]}]}
        usage.card_alerts([s], [entry(context=290_000)], self.TH, PRICES)
        self.assertEqual([a["kind"] for a in s["usage_alerts"]["%7"]], ["teammate_budget"])
        self.assertEqual(s["usage_alert_count"], 1)
        usage.card_alerts([s], [entry(context=10)], self.TH, PRICES)
        self.assertEqual((s["usage_alerts"], s["usage_alert_count"]), ({}, 0))


class HandoverNoticeTest(unittest.TestCase):
    def test_once_then_again_only_over_100_percent_after_ten_minutes(self):
        n = usage.HandoverNotices()
        self.assertTrue(n.due("t1", 260_000, 300_000, 1000))
        self.assertFalse(n.due("t1", 270_000, 300_000, 1100))        # same session: not again
        self.assertFalse(n.due("t1", 310_000, 300_000, 1500))        # over 100% but under ten minutes
        self.assertFalse(n.due("t1", 290_000, 300_000, 1700))        # ten minutes later but under 100%
        self.assertTrue(n.due("t1", 310_000, 300_000, 1700))         # over 100%, ten minutes later: once more
        self.assertFalse(n.due("t1", 400_000, 300_000, 9000))        # never a third time
        self.assertTrue(n.due("t2", 260_000, 300_000, 9000))         # another session has its own notice

    def test_handover_lines_per_project(self):
        th, n = dict(usage.DEFAULT_ALERTS), usage.HandoverNotices()
        s = {"name": "proj", "path": "/r", "windows": []}
        other = {"name": "other", "path": "/o", "windows": []}
        live = [entry(session_id="a", name="py", context=290_000, cwd="/r/.claude/worktrees/x"),
                entry(session_id="b", name="js", context=10, cwd="/r"),
                entry(session_id="c", name="go", context=290_000, cwd="/o")]
        self.assertEqual(usage.handover_lines([s, other], live, th, PRICES, n, 1000),
                         [("proj", "[Board] Teammate py is at 290K context (standard budget 300K): hand it over."),
                          ("other", "[Board] Teammate go is at 290K context (standard budget 300K): hand it over.")])
        self.assertEqual(usage.handover_lines([s, other], live, th, PRICES, n, 1100), [])
        live[0]["context"] = 310_000
        self.assertEqual(usage.handover_lines([s, other], live, th, PRICES, n, 1700),
                         [("proj", "[Board] Teammate py is at 310K context (standard budget 300K): hand it over.")])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: RED.** `python3 -m unittest discover -s board/tests -p 'test_usage_budget.py'` → `FAILED (errors=14)`, every error an `AttributeError: module 'usage' has no attribute …` (`tier_of`, `context_budget`, `teammate_budget`, `with_budget_alerts`, `HandoverNotices`) or the default-key assertion.

- [ ] **Step 3: Apply the patch script** (from the worktree root; it asserts each anchor exactly once and also edits the one `test_usage.py` assertion):

```python
"""Task 1 patch: anchor-asserted edits to board/usage.py (run from the repo root: python3 - < this file, or paste it)."""
from pathlib import Path
p = Path("board/usage.py"); s = p.read_text()
def rep(old, new):
    global s
    assert s.count(old) == 1, ("anchor not unique or missing", old[:70], s.count(old))
    s = s.replace(old, new)
rep('''DEFAULT_ALERTS = {"context_pct": 80, "burn_per_hour": 15, "burn_window_s": 900, "session_total": 25,
                  "mismatch_efforts": ["low", "medium"], "mismatch_models": ["opus", "fable"], "live_s": 1800}
''', '''TIERS = ("mechanical", "standard", "frontier")
DEFAULT_ROUTING = {"haiku": "mechanical", "sonnet": "standard", "fable": "frontier", "opus": "frontier"}   # model family -> tier
DEFAULT_ALERTS = {"context_pct": 80, "burn_per_hour": 15, "burn_window_s": 900, "session_total": 25,
                  "mismatch_efforts": ["low", "medium"], "mismatch_models": ["opus", "fable"], "live_s": 1800,
                  "teammate_context_budget": {"mechanical": 150000, "standard": 300000, "frontier": 300000}}
BUDGET_ALERT_PCT = 85      # teammate_budget alert: context at this % of the tier's budget
BUDGET_WINDOW_CAP = 0.8    # a model whose window is below its tier's budget gets this share of the window instead
''')
rep('''def _valid_threshold(default, v):
    if isinstance(default, list):
''', '''def _valid_threshold(default, v):
    if isinstance(default, dict):   # per-tier budgets: a non-empty object, tier names only, positive numbers
        return (isinstance(v, dict) and bool(v) and set(v) <= set(default)
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in v.values()))
    if isinstance(default, list):
''')
rep('''        if _valid_threshold(DEFAULT_ALERTS[k], v):
            th[k] = v
''', '''        if _valid_threshold(DEFAULT_ALERTS[k], v):
            th[k] = {**DEFAULT_ALERTS[k], **v} if isinstance(v, dict) else v   # a partial budget keeps the other tiers' defaults
''')
rep('''def _rows(conn, sql, args=()):''', '''def routing_map(repo):
    """{model family: tier} from <repo>/docs/superpowers/model-routing.json ({tier: model}), over DEFAULT_ROUTING.
    A missing or invalid file is the defaults alone."""
    m = {}
    try:
        d = json.loads((Path(repo) / "docs" / "superpowers" / "model-routing.json").read_text())
        if isinstance(d, dict):
            m = {str(d[t]).lower(): t for t in TIERS if isinstance(d.get(t), str)}
    except (OSError, ValueError, TypeError):
        m = {}
    return {**DEFAULT_ROUTING, **m}


def tier_of(model, repo):
    """The tier of a teammate's model through the project's routing map, or None for a family nobody maps."""
    return routing_map(repo).get(_family(model))


def context_budget(model, tier, th, prices):
    """The tier's context budget in tokens; a model whose window is smaller than that budget gets BUDGET_WINDOW_CAP of its window."""
    budget = th["teammate_context_budget"][tier]
    window = context_window(model, prices)
    return int(budget) if window >= budget else int(BUDGET_WINDOW_CAP * window)


def teammate_budget(entry, th, prices, repo):
    """(tier, budget, alert or None) for a live entry. Only teammates on a mapped model have a budget; the alert fires at
    BUDGET_ALERT_PCT of it. Its detail is the line the lead gets."""
    if entry.get("role") != "teammate":
        return None, None, None
    tier = tier_of(entry.get("model") or "", repo)
    if not tier:
        return None, None, None
    budget = context_budget(entry["model"], tier, th, prices)
    ctx = entry.get("context") or 0
    if not budget or ctx * 100 < BUDGET_ALERT_PCT * budget:   # exact: 254,999 of 300,000 is under 85%
        return tier, budget, None
    pct = 100 * ctx // budget
    return tier, budget, {"kind": "teammate_budget", "label": f"budget {pct}%",
                          "detail": f"Teammate {entry['name']} is at {ctx // 1000}K context ({tier} budget {budget // 1000}K): hand it over."}


def with_budget_alerts(entries, th, prices, repo):
    """The live entries with the teammate_budget alert appended where due; entries that gain one are copies."""
    out = []
    for e in entries:
        _, _, a = teammate_budget(e, th, prices, repo)
        out.append({**e, "alerts": list(e.get("alerts") or []) + [a]} if a else e)
    return out


class HandoverNotices:
    """Which teammate sessions the lead has been told to hand over: once when the alert first shows, and once more when
    the session is still above 100% of its budget RESEND_AFTER_S later. In-memory, per board process."""

    RESEND_AFTER_S = 600

    def __init__(self):
        self._sent = {}

    def due(self, session_id, context, budget, now):
        st = self._sent.get(session_id)
        if st is None:
            self._sent[session_id] = {"ts": now, "resent": False}
            return True
        if not st["resent"] and context > budget and now - st["ts"] >= self.RESEND_AFTER_S:
            st["resent"] = True
            return True
        return False


def handover_lines(sessions, live, th, prices, notices, now):
    """[(session name, "[Board] Teammate … hand it over.")] for each project's teammates at their budget alert whose notice is due."""
    out = []
    for s in sessions:
        for e in _project_live(s, live):
            tier, budget, alert = teammate_budget(e, th, prices, s.get("path") or "")
            if alert and notices.due(e["session_id"], e.get("context") or 0, budget, now):
                out.append((s["name"], "[Board] " + alert["detail"]))
    return out


def _settings(th, prices):
    return (th if th is not None else dict(DEFAULT_ALERTS)), (prices if prices is not None else load_prices())


def _rows(conn, sql, args=()):''')
rep('''    live = [e for e in live_sessions(conn, prices, th, now) if in_project(e["cwd"], repo)]
    alerts = [dict(a, session=e["name"]) for e in live for a in e["alerts"]]''',
'''    live = with_budget_alerts([e for e in live_sessions(conn, prices, th, now) if in_project(e["cwd"], repo)], th, prices, repo)
    alerts = [dict(a, session=e["name"]) for e in live for a in e["alerts"]]''')
rep('''        self._snapshot = []
        self._progress = {"done": 0, "total": 0}''', '''        self._snapshot = []
        self._settings = (dict(DEFAULT_ALERTS), None)   # (thresholds, prices) of the last pass; prices None until then
        self._progress = {"done": 0, "total": 0}''')
rep('''            with self._lock:
                self._snapshot = live
                self._first_pass_done = True''', '''            with self._lock:
                self._snapshot = live
                self._settings = (th, prices)
                self._first_pass_done = True''')
rep('''    def snapshot(self):
        with self._lock:
            return list(self._snapshot)
''', '''    def snapshot(self):
        with self._lock:
            return list(self._snapshot)

    def settings(self):
        """(thresholds, prices) the last pass used, for card_alerts and handover_lines on the state path."""
        with self._lock:
            return self._settings
''')
rep('''def card_alerts(sessions, live):
    """Attach usage alerts to board cards: s["usage_alerts"] = {pane id: [alerts]}, s["usage_alert_count"].

    Matching is _agent_windows'. The count covers every live session in the project, matched or not, so it
    equals the number of alerts the Usage tab lists.
    """
    for s in sessions:
        mine = _project_live(s, live)''', '''def card_alerts(sessions, live, th=None, prices=None):
    """Attach usage alerts to board cards: s["usage_alerts"] = {pane id: [alerts]}, s["usage_alert_count"].

    Matching is _agent_windows'. The count covers every live session in the project, matched or not, so it
    equals the number of alerts the Usage tab lists. The teammate_budget alert is added here, per project, because
    its tier comes from the project's routing map (th, prices: the indexer's last pass; defaults when None).
    """
    th, prices = _settings(th, prices)
    for s in sessions:
        mine = with_budget_alerts(_project_live(s, live), th, prices, s.get("path") or "")''')
p.write_text(s)
t = Path("board/tests/test_usage.py"); s = t.read_text()
old = '        self.assertEqual([(a["kind"], a["session"]) for a in al], [("context", "mate")])\n'
new = '        self.assertEqual([(a["kind"], a["session"]) for a in al], [("context", "mate"), ("teammate_budget", "mate")])   # 850K on opus (frontier budget 300K)\n'
assert s.count(old) == 1, "test_report_alerts_carry_session_name anchor"
t.write_text(s.replace(old, new))
print("usage.py and test_usage.py patched")
```

  The overseer plan inserts `OPTIONAL_ALERTS = ("day_total",)` after `DEFAULT_ALERTS` and an `if k in OPTIONAL_ALERTS: … continue` block before the `if k not in DEFAULT_ALERTS` check: both anchors above still match around them. If the `report()` anchor (`live = [e for e in live_sessions(...)]` + `alerts = […]`) moved, the change is: wrap the project-filtered live list in `with_budget_alerts(..., th, prices, repo)` before `alerts` is built.

- [ ] **Step 4: GREEN.** The Verify command → `OK`.

- [ ] **Step 5: Mutations, once each, restore after each:** the ten listed in the Acceptance Criteria, with `python3 -m unittest discover -s board/tests -p 'test_usage_budget.py'`; each must print `FAILED` naming the stated test.

- [ ] **Step 6: Commit** `feat(board): teammate_context_budget, teammate_budget alert and handover notices` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["board/usage.py", "board/tests/test_usage_budget.py", "board/tests/test_usage.py"], "acceptanceCriteria": ["key default, partial merge, seven invalid shapes warned", "tier via routing map with defaults; cap at 80% of a small window", "alert at exactly 85% with the spec label and detail; teammates only", "card_alerts and report carry the alert; snapshot entries not mutated", "HandoverNotices once, again over 100% after 600 s, never a third time; handover_lines per project", "usage suites OK; ten mutations each fail their named test"], "modelTier": "standard", "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_usage*.py'"}
```

### Task 2: board/night.py: state, caffeinate pid, check, stop condition, CLI

**Goal:** `board/night.py` keeps night-mode state per project, starts the keep-awake process detached and stops it by its recorded pid only, computes the pre-flight warnings (waiting prompt, non-auto Claude pane, battery), counts open work from the real planview/activity readers, and runs the board's `tick()`; its CLI serves `tmux-ctl night` and the session-closed hook.

**Files:**
- Create: `board/night.py`
- Create: `board/tests/test_night.py`

**Acceptance Criteria:**
- [ ] `state_file("proj", d)` is `d/night-proj.json`; names failing `NAME_RE` (`""`, `..`, `a/b`, `.hidden`) raise `ValueError`, `active()` returns False for them. `save` is atomic (no temp file left), `load` returns None for missing or non-object JSON.
- [ ] `pid_matches(pid, cmd, ps)` is True only for an int pid > 1 whose `ps` line's argv[0] basename equals `cmd[0]`'s basename; `stop_caffeinate` kills exactly that pid with SIGTERM, writes `pid: null` + `stopped`, keeps the file (night mode stays on), says `"pid N is not caffeinate any more; not killed"` for a reused pid, and `"caffeinate already stopped"` / `"no night state"` otherwise.
- [ ] `check(session, tmux, battery)`: a Claude pane classified `waiting` → `window '<w>' is waiting at a permission prompt or a question…`; a Claude pane whose last 12 rows lack `auto mode on` → `window '<w>' is not in auto permission mode…`; shells and programs ignored; `battery()` output without `AC Power` → the lid warning, empty output (no pmset) → none; a failing tmux → no warnings.
- [ ] `open_work` counts non-completed tasks of a live task list only (planview `active`), and `tmux-ctl run` records with `exit: null` younger than `RUN_STALE_S`.
- [ ] `tick`: stops after two consecutive idle polls and notifies `[Board] Night work finished … morning report …`; a busy poll resets the count; a file that disappears notifies `[Board] Night mode is off: …` once; `.hidden`/other files skipped.
- [ ] One real detached `sleep 300` is started, matched by the real `ps`, stopped and seen gone; one real `caffeinate -i -t 2` run, skipped off macOS.
- [ ] `python3 -m unittest discover -s board/tests -p 'test_night.py'` → `Ran 21 tests … OK`. Mutations, once each, restored: `if pid_matches(pid, cmd, ps):` → `if True:` fails `test_stop_refuses_a_reused_pid`; `STOP_AFTER_POLLS = 1` fails `test_stops_after_two_idle_polls_and_tells_the_lead` and `test_open_task_or_running_test_keeps_caffeinate`; `memo["idle"][project] = 0` → `pass` fails `test_open_task_or_running_test_keeps_caffeinate`; `AUTO_RE` text → `never-matches` fails `test_non_auto_claude_is_reported`, `test_quiet_when_every_claude_is_auto_and_idle_on_ac`, `test_waiting_prompt_is_reported`; dropping the `RUN_STALE_S` condition fails `test_counts_open_tasks_and_running_runs`; `pid <= 1` → `pid < 0` fails `test_pid_matches_only_the_recorded_command`; `if status == "waiting":` → `"never"` fails `test_waiting_prompt_is_reported`; the off-transition loop → `for project in ():` fails `test_off_transition_tells_the_lead`; dropping ` if v.get("active") else 0` fails `test_no_live_task_list_counts_as_no_open_task`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_night.py'` → `Ran 21 tests` … `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Create `board/tests/test_night.py`:

```python
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import night  # noqa: E402

SEP = "\t"
AUTO = "  ⏵⏵ auto mode on (shift+tab to cycle) · ctrl+t to hide tasks"   # a live Claude Code 2.1.312 status line (2026-10-28)
BUSY = "  ⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt"      # the same line while Claude works


class FakeTmux:
    """list-panes -s rows and the rows each pane shows. panes: [(window, pane id, command, bell, rows)]."""

    def __init__(self, panes):
        self.panes, self.calls = panes, []

    def __call__(self, *a, check=False):
        self.calls.append(a)
        if a[0] == "list-panes":
            return "".join(f"{w}{SEP}{p}{SEP}{c}{SEP}{b}\n" for w, p, c, b, _ in self.panes)
        if a[0] == "capture-pane":
            pane = a[a.index("-t") + 1]
            return "\n".join(next(r for _, p, _, _, r in self.panes if p == pane)) + "\n"
        return ""


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_state_file_layout_and_name_rule(self):
        self.assertEqual(night.state_file("proj", self.tmp), self.tmp / "night-proj.json")
        for bad in ("", "..", "a/b", ".hidden"):
            with self.assertRaises(ValueError):
                night.state_file(bad, self.tmp)
        self.assertFalse(night.active("a/b", self.tmp))

    def test_save_load_active(self):
        self.assertFalse(night.active("proj", self.tmp))
        self.assertIsNone(night.load("proj", self.tmp))
        night.save("proj", {"project": "proj", "pid": 42, "since": 1.0, "cmd": ["caffeinate", "-i"]}, self.tmp)
        self.assertTrue(night.active("proj", self.tmp))
        self.assertEqual(night.load("proj", self.tmp)["pid"], 42)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["night-proj.json"])   # no temp file left behind
        (self.tmp / "night-proj.json").write_text("[1]")
        self.assertIsNone(night.load("proj", self.tmp))

    def test_pid_matches_only_the_recorded_command(self):
        ps = {42: "caffeinate -i", 43: "/usr/bin/caffeinate -i -t 2", 44: "zsh"}.get
        cmd = ["caffeinate", "-i"]
        self.assertTrue(night.pid_matches(42, cmd, ps=lambda p: ps(p) or ""))
        self.assertTrue(night.pid_matches(43, cmd, ps=lambda p: ps(p) or ""))
        self.assertFalse(night.pid_matches(44, cmd, ps=lambda p: ps(p) or ""))     # pid reused by another program
        self.assertFalse(night.pid_matches(45, cmd, ps=lambda p: ps(p) or ""))     # gone
        for pid in (0, 1, -5, None, "42", True):
            self.assertFalse(night.pid_matches(pid, cmd, ps=lambda p: "caffeinate -i"), pid)
        self.assertFalse(night.pid_matches(42, [], ps=lambda p: "caffeinate -i"))

    def test_stop_kills_only_the_recorded_pid_and_clears_it(self):
        night.save("proj", {"project": "proj", "pid": 42, "since": 1.0, "cmd": ["caffeinate", "-i"]}, self.tmp)
        killed = []
        what = night.stop_caffeinate("proj", self.tmp, kill=lambda p, s: killed.append((p, s)), ps=lambda p: "caffeinate -i")
        self.assertEqual([k[0] for k in killed], [42])
        self.assertIn("stopped caffeinate (pid 42)", what)
        d = night.load("proj", self.tmp)
        self.assertIsNone(d["pid"])
        self.assertIn("stopped", d)
        self.assertTrue(night.active("proj", self.tmp))   # night mode itself stays on
        self.assertEqual(night.stop_caffeinate("proj", self.tmp, kill=lambda p, s: killed.append((p, s))), "caffeinate already stopped")
        self.assertEqual(len(killed), 1)

    def test_stop_refuses_a_reused_pid(self):
        night.save("proj", {"project": "proj", "pid": 42, "since": 1.0, "cmd": ["caffeinate", "-i"]}, self.tmp)
        killed = []
        what = night.stop_caffeinate("proj", self.tmp, kill=lambda p, s: killed.append(p), ps=lambda p: "python3 server.py")
        self.assertEqual(killed, [])
        self.assertIn("not killed", what)
        self.assertIsNone(night.load("proj", self.tmp)["pid"])

    def test_stop_without_state(self):
        self.assertEqual(night.stop_caffeinate("proj", self.tmp, kill=lambda p, s: None), "no night state")

    def test_start_and_stop_a_real_detached_process(self):
        # `sleep` stands in for caffeinate (TC_CAFFEINATE_CMD does the same for tmux-ctl); the real ps decides the match
        pid = night.start_caffeinate(["sleep", "300"])
        try:
            self.assertTrue(night.pid_matches(pid, ["sleep", "300"]))
            night.save("proj", {"project": "proj", "pid": pid, "since": time.time(), "cmd": ["sleep", "300"]}, self.tmp)
            what = night.stop_caffeinate("proj", self.tmp)
            self.assertIn(f"stopped caffeinate (pid {pid})", what)
            deadline = time.time() + 5
            while time.time() < deadline and night.ps_command(pid):
                time.sleep(0.1)
            self.assertEqual(night.ps_command(pid), "")
        finally:
            try:
                os.kill(pid, 9)
            except OSError:
                pass

    @unittest.skipUnless(sys.platform == "darwin", "caffeinate is macOS only")
    def test_real_caffeinate_runs(self):
        pid = night.start_caffeinate(["caffeinate", "-i", "-t", "2"])
        try:
            self.assertTrue(night.pid_matches(pid, ["caffeinate", "-i"]))
        finally:
            try:
                os.kill(pid, 15)
            except OSError:
                pass


class CheckTest(unittest.TestCase):
    AC = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=36241507)\t100%; charged; 0:00 remaining present: true\n"
    BATT = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=36241507)\t87%; discharging; 4:10 remaining present: true\n"

    def warnings(self, panes, battery=None):
        return night.check("proj", FakeTmux(panes), battery=lambda: battery if battery is not None else self.AC)

    def test_quiet_when_every_claude_is_auto_and_idle_on_ac(self):
        panes = [("claude", "%1", "2.1.312", "0", ["⏺ done", "", "❯ ", AUTO]),
                 ("✦ py", "%2", "2.1.312", "0", ["working", "✻ Thinking… (esc to interrupt)", BUSY]),
                 ("shell", "%3", "zsh", "0", ["$ "])]
        self.assertEqual(self.warnings(panes), [])

    def test_waiting_prompt_is_reported(self):
        panes = [("✦ py", "%2", "2.1.312", "1", ["Do you want to proceed?", "❯ 1. Yes", "  2. No", AUTO])]
        w = self.warnings(panes)
        self.assertEqual(len(w), 1)
        self.assertIn("window '✦ py' is waiting at a permission prompt or a question", w[0])

    def test_non_auto_claude_is_reported(self):
        panes = [("claude", "%1", "2.1.312", "0", ["❯ ", "  ⏵⏵ accept edits on (shift+tab to cycle)"]),
                 ("fix-login", "%4", "2.1.312", "0", ["❯ ", "  ⏵⏵ bypass permissions on (shift+tab to cycle)"]),
                 ("✦ ok", "%5", "2.1.312", "0", ["❯ ", AUTO])]
        w = self.warnings(panes)
        self.assertEqual(len(w), 2)
        self.assertTrue(all("is not in auto permission mode" in x for x in w))
        self.assertIn("'claude'", w[0])
        self.assertIn("'fix-login'", w[1])

    def test_shell_and_program_panes_are_ignored(self):
        panes = [("shell", "%3", "zsh", "1", ["Do you want to proceed?"]), ("plan", "%6", "Python", "0", ["no plans yet"])]
        self.assertEqual(self.warnings(panes), [])

    def test_battery_is_reported(self):
        w = self.warnings([], battery=self.BATT)
        self.assertEqual(len(w), 1)
        self.assertIn("closing the lid on battery still sleeps it", w[0])
        self.assertEqual(self.warnings([], battery=""), [])   # no pmset (Linux): no battery warning

    def test_tmux_failure_gives_no_warning(self):
        def tmux(*a, check=False):
            raise RuntimeError("no server")
        self.assertEqual(night.check("proj", tmux, battery=lambda: self.AC), [])


class TickTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.notes, self.killed = [], []
        self.memo = {"idle": {}, "on": set()}
        self.saved = night.stop_caffeinate
        night.stop_caffeinate = lambda project, state_dir=None, **kw: (self.killed.append(project), self.saved(project, state_dir, kill=lambda p, s: None, ps=lambda p: "caffeinate -i"))[1]

    def tearDown(self):
        night.stop_caffeinate = self.saved
        shutil.rmtree(self.tmp)

    def on(self, project, pid=42):
        night.save(project, {"project": project, "pid": pid, "since": 1.0, "cmd": ["caffeinate", "-i"]}, self.tmp)

    def tick(self, work):
        night.tick(self.tmp, self.tmp / "home", lambda *a, check=False: "", lambda p: "/r", lambda p, l: self.notes.append((p, l)),
                   self.memo, work=lambda project, root, home, sd, tmux: work[project])

    def test_stops_after_two_idle_polls_and_tells_the_lead(self):
        self.on("proj")
        self.tick({"proj": (0, 0)})
        self.assertEqual(self.killed, [])
        self.tick({"proj": (0, 0)})
        self.assertEqual(self.killed, ["proj"])
        self.assertEqual(len(self.notes), 1)
        self.assertEqual(self.notes[0][0], "proj")
        self.assertIn("Night work finished", self.notes[0][1])
        self.assertIn("morning report", self.notes[0][1])
        self.assertTrue(night.active("proj", self.tmp))
        self.tick({"proj": (0, 0)})   # pid already cleared: nothing more happens
        self.assertEqual((self.killed, len(self.notes)), (["proj"], 1))

    def test_open_task_or_running_test_keeps_caffeinate(self):
        self.on("proj")
        for work in ((1, 0), (0, 1), (0, 0), (2, 1), (0, 0)):   # an idle poll between busy ones never accumulates
            self.tick({"proj": work})
        self.assertEqual(self.killed, [])
        self.assertEqual(self.notes, [])

    def test_off_transition_tells_the_lead(self):
        self.on("proj")
        self.tick({"proj": (1, 0)})
        (self.tmp / "night-proj.json").unlink()   # tmux-ctl night off
        self.tick({})
        self.assertEqual(self.notes, [("proj", f"[Board] Night mode is off: {night.REPORT_HINT}.")])
        self.tick({})
        self.assertEqual(len(self.notes), 1)

    def test_bad_names_and_other_files_are_skipped(self):
        (self.tmp / "night-.hidden.json").write_text("{}")
        (self.tmp / "runs-proj.jsonl").write_text("")
        self.tick({})
        self.assertEqual((self.killed, self.notes, self.memo["on"]), ([], [], set()))   # .hidden fails NAME_RE


class OpenWorkTest(unittest.TestCase):
    """Real planview and activity readers over the fixture layout the board reads: <home>/.claude/{sessions,tasks}, and
    $TC_STATE/{artifacts,runs}-<project>.jsonl."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home" / ".claude"
        (self.home / "sessions").mkdir(parents=True)
        (self.home / "tasks" / "session-aaaaaaaa").mkdir(parents=True)
        self.state = self.tmp / "state"
        self.state.mkdir()
        self.env = dict(os.environ)
        os.environ["TC_STATE"] = str(self.state)
        (self.home / "sessions" / "1.json").write_text(json.dumps(
            {"pid": 1, "sessionId": "aaaaaaaa-0000-0000-0000-000000000000", "tmux": "proj:@1.%1", "updatedAt": 5}))

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp)

    def tmux(self, *a, check=False):
        if a[0] == "display" and a[-1] == "#{window_id}.#{pane_id}":
            return "@1.%1\n"
        if a[0] == "display":
            return "proj\n"
        return ""

    def task(self, i, status):
        (self.home / "tasks" / "session-aaaaaaaa" / f"{i}.json").write_text(json.dumps({"id": i, "subject": f"t{i}", "status": status}))

    def run_record(self, rid, exit_code, age):
        rec = {"id": rid, "ts": time.time() - age, "exit": exit_code, "cmd": "x", "win": "tests"}
        with (self.state / "runs-proj.jsonl").open("a") as h:
            h.write(json.dumps(rec) + "\n")

    def work(self):
        return night.open_work("proj", self.tmp, self.home, self.state, self.tmux)   # home = the Claude config dir, as planview reads it

    def test_counts_open_tasks_and_running_runs(self):
        self.task(1, "completed"); self.task(2, "in_progress"); self.task(3, "pending")
        self.run_record("r1", None, 10); self.run_record("r2", 0, 10); self.run_record("r3", None, night.RUN_STALE_S + 5)
        self.assertEqual(self.work(), (2, 1))

    def test_all_done_and_no_runs(self):
        self.task(1, "completed")
        self.assertEqual(self.work(), (0, 0))

    def test_no_live_task_list_counts_as_no_open_task(self):
        (self.tmp / "docs" / "superpowers" / "plans").mkdir(parents=True)
        (self.tmp / "docs" / "superpowers" / "plans" / "old.md.tasks.json").write_text(json.dumps({"tasks": [{"id": 1, "subject": "s", "status": "pending"}]}))
        self.assertEqual(self.work(), (0, 0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: RED.** The Verify command → `ModuleNotFoundError: No module named 'night'`.

- [ ] **Step 3: Create `board/night.py`:**

```python
#!/usr/bin/env python3
"""night: night mode per project. The caffeinate pid file, the pre-flight check, and when the board stops caffeinate.

State: $TC_STATE/night-<project>.json = {"project", "pid", "since", "cmd"}. The tmux session option @tc_night=1 on the
project's canonical session is the flag the night-guard hook and the lead's rules read (grouped _web-* views do not see
it; readers resolve the canonical session first). Caffeinate is killed by the pid in the file only, and only while `ps`
still shows that pid running the recorded command.
CLI (tmux-ctl night): night.py on|off|status|check --session S --project P [--root R]; _stop --project P (session-closed hook).
"""
import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import activity, paneclass, planview, tc_env  # noqa: E402

ERRORS = (OSError, ValueError, RuntimeError, subprocess.SubprocessError)
NAME_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")   # the same rule as server.py and ideas.py
# Claude Code's status line in auto mode. Probe 2026-10-28, Claude Code 2.1.312, a live lead pane:
# "  ⏵⏵ auto mode on (shift+tab to cycle) · ctrl+t to hide tasks"
AUTO_RE = re.compile(r"auto mode on")
RUN_STALE_S = 6 * 3600     # a run record still without an exit code after this long is a crashed run, not work
STOP_AFTER_POLLS = 2       # "no open task, no running test" must hold on this many consecutive board polls
REPORT_HINT = "write the morning report .superpowers/night/<YYYY-MM-DD>.md and register it with tmux-ctl artifact"


def caffeinate_cmd():
    """The keep-awake command; TC_CAFFEINATE_CMD overrides it (tests use `sleep 300`)."""
    return shlex.split(os.environ.get("TC_CAFFEINATE_CMD") or "caffeinate -i")


def state_file(project, state_dir=None):
    if not NAME_RE.fullmatch(project or ""):
        raise ValueError(f"bad project name {project!r}")
    return Path(state_dir or tc_env.state_dir()) / f"night-{project}.json"


def load(project, state_dir=None):
    try:
        d = json.loads(state_file(project, state_dir).read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def active(project, state_dir=None):
    """Night mode is on while the project's state file exists (caffeinate may already have been stopped)."""
    try:
        return state_file(project, state_dir).exists()
    except ValueError:
        return False


def save(project, data, state_dir=None):
    p = state_file(project, state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, p)


def start_caffeinate(cmd=None):
    """Start the keep-awake process detached (own session, no terminal); returns its pid. It outlives this process."""
    cmd = list(cmd or caffeinate_cmd())
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    return p.pid


def ps_command(pid):
    """The command line `ps` shows for pid, or "" when it is gone."""
    try:
        r = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip()


def pid_matches(pid, cmd, ps=ps_command):
    """True while pid runs the recorded command (same argv[0] basename), so a reused pid is never killed."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1 or not cmd:
        return False
    line = ps(pid)
    return bool(line) and os.path.basename(line.split()[0]) == os.path.basename(cmd[0])


def stop_caffeinate(project, state_dir=None, kill=os.kill, ps=ps_command):
    """Kill the recorded pid if it still runs the recorded command; clear it from the file. Returns what happened."""
    d = load(project, state_dir)
    if not d:
        return "no night state"
    pid, cmd = d.get("pid"), d.get("cmd") or caffeinate_cmd()
    if not pid:
        return "caffeinate already stopped"
    if pid_matches(pid, cmd, ps):
        try:
            kill(pid, signal.SIGTERM)
            what = f"stopped caffeinate (pid {pid})"
        except OSError as e:
            what = f"could not stop pid {pid}: {e}"
    else:
        what = f"pid {pid} is not caffeinate any more; not killed"
    save(project, {**d, "pid": None, "stopped": time.time()}, state_dir)
    return what


def pmset_batt():
    try:
        return subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def check(session, tmux, battery=pmset_batt):
    """Warnings before night mode goes on: a Claude pane waiting at a prompt or question, a Claude pane not in auto
    permission mode, and battery power. tmux(*args) -> stdout (paneclass.tmux_runner shape)."""
    warnings = []
    try:
        lines = tmux("list-panes", "-s", "-t", f"={session}", "-F",
                     "#{window_name}\t#{pane_id}\t#{pane_current_command}\t#{window_bell_flag}").splitlines()
    except ERRORS:
        lines = []
    for l in lines:
        f = l.split("\t")
        if len(f) != 4:
            continue
        wname, pane, cmd, bell = f
        try:
            rows = [r.rstrip() for r in tmux("capture-pane", "-p", "-J", "-t", pane, "-S", "-40").splitlines()]
        except ERRORS:
            continue
        while rows and not rows[-1]:
            rows.pop()
        kind, status = paneclass.classify(cmd, rows, bell == "1")
        if kind != "claude":
            continue
        if status == "waiting":
            warnings.append(f"window '{wname}' is waiting at a permission prompt or a question: answer it, or the work parks there")
        if not any(AUTO_RE.search(r) for r in rows[-12:]):
            warnings.append(f"window '{wname}' is not in auto permission mode (shift+tab in it cycles to auto)")
    out = battery() or ""
    if out and "AC Power" not in out:
        warnings.append("running on battery: caffeinate keeps the Mac awake, but closing the lid on battery still sleeps it")
    return warnings


def open_work(project, root, home, state_dir, tmux, now=None):
    """(open plan tasks, running test runs) for a project. Open: a live task list with a task not completed.
    Running: a `tmux-ctl run` record without an exit code, younger than RUN_STALE_S."""
    v = planview.view(project, root, home, state_dir, tmux)
    open_tasks = sum(1 for t in v.get("tasks") or [] if t.get("status") != "completed") if v.get("active") else 0
    now = now or time.time()
    running = sum(1 for r in activity.runs(project) if r.get("exit") is None and now - (r.get("ts") or 0) < RUN_STALE_S)
    return open_tasks, running


def tick(state_dir, home, tmux, root_of, notify, memo, work=open_work):
    """One board poll over every night-<project>.json. Stops caffeinate once a project has had no open plan task and no
    running test on STOP_AFTER_POLLS consecutive polls, and tells the lead (notify(project, line)); also tells the lead
    when a project's night mode went off since the last poll. memo = {"idle": {project: polls}, "on": set(projects)}."""
    state_dir = Path(state_dir)
    present = set()
    for f in sorted(state_dir.glob("night-*.json")):
        project = f.name[len("night-"):-len(".json")]
        if not NAME_RE.fullmatch(project):
            continue
        present.add(project)
        d = load(project, state_dir)
        if not d or not d.get("pid"):
            continue
        try:
            open_tasks, running = work(project, root_of(project), home, state_dir, tmux)
        except ERRORS:
            continue
        if open_tasks or running:
            memo["idle"][project] = 0
            continue
        memo["idle"][project] = memo["idle"].get(project, 0) + 1
        if memo["idle"][project] >= STOP_AFTER_POLLS:
            what = stop_caffeinate(project, state_dir)
            notify(project, f"[Board] Night work finished (no open plan task, no running test): {what}. "
                            f"Night mode stays on; {REPORT_HINT}.")
    for project in memo.get("on", set()) - present:
        notify(project, f"[Board] Night mode is off: {REPORT_HINT}.")
    memo["on"] = present


def status_line(project, state_dir=None, ps=ps_command):
    d = load(project, state_dir)
    if not d:
        return f"night mode off for {project}"
    since = time.strftime("%Y-%m-%d %H:%M", time.localtime(d.get("since") or 0))
    pid = d.get("pid")
    caf = f"caffeinate pid {pid} running" if pid and pid_matches(pid, d.get("cmd") or caffeinate_cmd(), ps) else "caffeinate stopped"
    return f"night mode on for {project} since {since}; {caf}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="night")
    ap.add_argument("cmd", choices=("on", "off", "status", "check", "_stop"))
    ap.add_argument("--project", required=True)
    ap.add_argument("--session")
    ap.add_argument("--root", default=".")
    a = ap.parse_args(argv)
    project, session = a.project, a.session or a.project
    sd = tc_env.state_dir()
    if a.cmd == "_stop":   # session-closed hook: no tmux session left to ask
        print(stop_caffeinate(project, sd))
        try:
            state_file(project, sd).unlink()
        except OSError:
            pass
        return 0
    if a.cmd == "status":
        print(status_line(project, sd))
        return 0
    tmux = paneclass.tmux_runner()
    if a.cmd == "check":
        for w in check(session, tmux):
            print(f"night: warning: {w}")
        return 0
    if a.cmd == "on":
        for w in check(session, tmux):
            print(f"night: warning: {w}", file=sys.stderr)
        d = load(project, sd)
        if d and d.get("pid") and pid_matches(d["pid"], d.get("cmd") or caffeinate_cmd()):
            tmux("set-option", "-t", f"={project}:", "@tc_night", "1", check=True)
            print(f"night mode already on for {project} (caffeinate pid {d['pid']})")
            return 0
        cmd = caffeinate_cmd()
        pid = start_caffeinate(cmd)
        save(project, {"project": project, "pid": pid, "since": time.time(), "cmd": cmd}, sd)
        tmux("set-option", "-t", f"={project}:", "@tc_night", "1", check=True)
        print(f"night mode on for {project}: caffeinate pid {pid}; the board stops it once the plan has no open task and no "
              f"test runs. Questions are now decided and logged, or parked (orchestrator.md, Night mode).")
        return 0
    what = stop_caffeinate(project, sd)   # off
    try:
        state_file(project, sd).unlink()
    except OSError:
        pass
    tmux("set-option", "-u", "-t", f"={project}:", "@tc_night")
    print(f"night mode off for {project}: {what}. Now {REPORT_HINT}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: GREEN.** The Verify command → `Ran 21 tests … OK`.

- [ ] **Step 5: Mutations, once each, restore after each:** the nine listed in the Acceptance Criteria; each run of the Verify command must print `FAILED` naming the stated test(s).

- [ ] **Step 6: Commit** `feat(board): night.py, night-mode state, caffeinate pid and stop condition` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["board/night.py", "board/tests/test_night.py"], "acceptanceCriteria": ["state file layout and name rule; atomic save", "pid matched by ps argv[0] basename; stop kills the recorded pid only, keeps night mode on", "check: waiting prompt, non-auto pane, battery; shells ignored; tmux failure quiet", "open_work over real planview/activity readers; stale runs ignored; idle view = no open task", "tick: two idle polls then stop + notify; busy resets; off transition notified once", "one real detached process and one real caffeinate -i -t 2 (macOS)", "21 tests OK; nine mutations each fail their named test"], "modelTier": "mechanical", "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_night.py'"}
```

### Task 3: server.py: handover line, 🌙 marker, night-watch thread

**Goal:** `board/server.py` queues the handover line through `CommentQueue` on every state build (once per teammate session, again over 100% after ten minutes), marks each project `night: true|false` so the page draws 🌙 on its tab, and runs the `night-watch` thread that stops caffeinate when the work ends and tells the lead.

**Files:**
- Modify: `board/server.py` (imports, `HANDOVER`, new `queue_handovers` / `mark_night` / `night_watch`, `build_state` order, `__main__`)
- Modify: `board/index.html` (`renderTabs`, one line)
- Create: `board/tests/test_night_server.py`

**Acceptance Criteria:**
- [ ] `queue_handovers(sessions, live, th, prices, now)` queues `[Board] Teammate py is at 290K context (standard budget 300K): hand it over.` once for three builds at 290K; after delivery, a 299K build and a 310K build inside ten minutes queue nothing; a 310K build ten minutes after the first queues the 310K line; a 400K build later queues nothing; another project's teammate reaches no line in this project.
- [ ] Delivery follows `CommentQueue.deliver`: held while the lead pane is `waiting` or has typed text; typed when `ready` with an empty input (`test_delivered_only_when_the_lead_pane_takes_input`).
- [ ] `mark_night` sets `night` from `$TC_STATE/night-<name>.json` (True, False, False for a bad name); `index.html` renders `s.night ? \`${s.name} 🌙\` : s.name` in `renderTabs`; `__main__` starts `threading.Thread(target=night_watch, name="night-watch", daemon=True)`.
- [ ] `build_state` order: `card_alerts(out, snap, th, prices)` → `card_labels` → `queue_handovers` → `mark_night` → `deliver_comments` (a line queued this build is delivered this build). `th, prices` come from `INDEXER.settings()`.
- [ ] `python3 -m unittest discover -s board/tests -p 'test_night_server.py'` → `Ran 7 tests … OK`; `test_agent_controls.py`, `test_poll_efficiency.py`, `test_reload.py` (they load `server.py`) still `OK`. Mutations, once each, restored: `COMMENTS.add_line(sess, text)` → `pass` fails the three queue tests; `s["night"] = False` fails `test_mark_night_reads_the_state_file`; removing the `Thread(... night_watch ...)` line fails `test_watch_thread_is_started_with_the_indexer`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_night_server.py'` → `Ran 7 tests` … `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Create `board/tests/test_night_server.py`:

```python
"""server.py's night-mode and handover pieces: the 🌙 field, the handover line in the lead's comment queue, the watch thread wiring."""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("tmux_dash_server_night", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
usage, night = server.usage, server.night

PRICES = {"models": {"claude-sonnet-5-5": {"context": 1000000}}, "default_context": 200000}


def mate(sid, name, ctx, cwd="/r"):
    return {"session_id": sid, "name": name, "role": "teammate", "model": "claude-sonnet-5-5", "effort": "medium",
            "agent_name": name, "cwd": cwd, "context": ctx, "context_pct": 0, "last_hour": 0.0, "total": 0.0, "alerts": []}


class HandoverQueueTest(unittest.TestCase):
    def setUp(self):
        server.COMMENTS = server.artifacts.CommentQueue()
        server.HANDOVER = usage.HandoverNotices()
        self.sess = [{"name": "proj", "path": "/r", "windows": [{"name": "claude", "panes": [{"id": "%1", "kind": "claude", "status": "ready"}]}]}]

    def pending(self):
        return [server.COMMENTS.line(c) for c in server.COMMENTS.pending("proj")]

    def test_line_queued_once_per_teammate_session(self):
        live = [mate("a", "py", 290_000), mate("b", "js", 10)]
        for now in (1000, 1001, 1002):
            server.queue_handovers(self.sess, live, dict(usage.DEFAULT_ALERTS), PRICES, now=now)
        self.assertEqual(self.pending(), ["[Board] Teammate py is at 290K context (standard budget 300K): hand it over."])

    def test_requeued_only_over_100_percent_after_ten_minutes(self):
        th = dict(usage.DEFAULT_ALERTS)
        server.queue_handovers(self.sess, [mate("a", "py", 290_000)], th, PRICES, now=1000)
        server.COMMENTS.deliver("proj", "%1", "claude", "ready", lambda p, t: None)   # delivered: the queue is empty again
        server.queue_handovers(self.sess, [mate("a", "py", 299_000)], th, PRICES, now=1700)
        self.assertEqual(self.pending(), [])
        server.queue_handovers(self.sess, [mate("a", "py", 310_000)], th, PRICES, now=1500)
        self.assertEqual(self.pending(), [])
        server.queue_handovers(self.sess, [mate("a", "py", 310_000)], th, PRICES, now=1700)
        self.assertEqual(self.pending(), ["[Board] Teammate py is at 310K context (standard budget 300K): hand it over."])
        server.queue_handovers(self.sess, [mate("a", "py", 400_000)], th, PRICES, now=9000)
        self.assertEqual(len(self.pending()), 1)

    def test_delivered_only_when_the_lead_pane_takes_input(self):
        server.queue_handovers(self.sess, [mate("a", "py", 290_000)], dict(usage.DEFAULT_ALERTS), PRICES, now=1000)
        sent = []
        q = server.COMMENTS
        self.assertEqual(q.deliver("proj", "%1", "claude", "waiting", lambda p, t: sent.append(t)), 0)      # a permission prompt is open
        self.assertEqual(q.deliver("proj", "%1", "claude", "ready", lambda p, t: sent.append(t), input_has_text=lambda pane: True), 0)   # the user is typing
        self.assertEqual(sent, [])
        self.assertEqual(q.deliver("proj", "%1", "claude", "ready", lambda p, t: sent.append(t), input_has_text=lambda pane: False), 1)
        self.assertEqual(sent, ["[Board] Teammate py is at 290K context (standard budget 300K): hand it over."])

    def test_other_projects_teammates_do_not_reach_this_lead(self):
        server.queue_handovers(self.sess, [mate("c", "go", 290_000, cwd="/other")], dict(usage.DEFAULT_ALERTS), PRICES, now=1000)
        self.assertEqual(self.pending(), [])


class NightFieldTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = dict(os.environ)
        os.environ["TC_STATE"] = str(self.tmp)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.tmp)

    def test_mark_night_reads_the_state_file(self):
        night.save("proj", {"project": "proj", "pid": None, "since": 1.0, "cmd": ["caffeinate", "-i"]}, self.tmp)
        out = server.mark_night([{"name": "proj"}, {"name": "other"}, {"name": "bad name"}])
        self.assertEqual([s["night"] for s in out], [True, False, False])

    def test_page_draws_the_marker_from_the_field(self):
        html = (HERE / "index.html").read_text()
        self.assertIn("s.night ? `${s.name} 🌙` : s.name", html)

    def test_watch_thread_is_started_with_the_indexer(self):
        src = (HERE / "server.py").read_text()
        main = src[src.index('if __name__ == "__main__":'):]
        self.assertIn('threading.Thread(target=night_watch, name="night-watch", daemon=True).start()', main)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: RED.** The Verify command → `AttributeError: module 'tmux_dash_server_night' has no attribute 'night'` (import error of the test module).

- [ ] **Step 3: Apply the patch script** (worktree root). The import edit is computed, not anchored: it adds `night` to the existing `import activity, artifacts, dirs, ideas, … # noqa: E402` line whatever the earlier plans added (`notify`, `overview`, `claims`, `context`):

```python
"""Task 3 patch: anchor-asserted edits to board/server.py and board/index.html."""
from pathlib import Path
p = Path("board/server.py"); s = p.read_text()
def rep(old, new):
    global s
    assert s.count(old) == 1, ("anchor not unique or missing", old[:70], s.count(old))
    s = s.replace(old, new)
# the import line: add `night` to the module list, whatever else earlier plans added to it
import re
m = re.search(r"^import (activity, artifacts, dirs, ideas, [^\n]*?)  # noqa: E402$", s, re.M)
assert m and "night" not in m.group(1), "import line"
mods = sorted(set(m.group(1).split(", ")) | {"night"})
rep(m.group(0), f"import {', '.join(mods)}  # noqa: E402")
rep('''COMMENTS = artifacts.CommentQueue()
''', '''COMMENTS = artifacts.CommentQueue()
HANDOVER = usage.HandoverNotices()   # which teammate sessions the lead was told to hand over (per board process)
''')
rep('''def last_sweep(max_bytes=65536):''', '''def queue_handovers(sessions, live, th=None, prices=None, now=None):
    """Queue "[Board] Teammate <name> is at <N>K context (<tier> budget <B>K): hand it over." for the lead of each project
    with a teammate at its context budget (usage.handover_lines decides once per session, once more over 100% ten
    minutes later). CommentQueue types it into the claude pane when that pane takes input."""
    th, prices = usage._settings(th, prices)
    for sess, text in usage.handover_lines(sessions, live, th, prices, HANDOVER, now or time.time()):
        COMMENTS.add_line(sess, text)


def mark_night(sessions):
    """s["night"]: the project is in night mode (its $TC_STATE/night-<project>.json exists); the page draws 🌙 on the tab."""
    for s in sessions:
        s["night"] = night.active(s["name"])
    return sessions


NIGHT_WATCH_S = 30


def night_watch(interval=NIGHT_WATCH_S):
    """Every interval: stop a night-mode project's caffeinate once its plan has no open task and no test runs, and tell
    its lead through the comment queue (board/night.py tick). A failing poll is logged and the next one runs."""
    memo = {"idle": {}, "on": set()}
    while True:
        try:
            night.tick(tc_env.state_dir(), HOME / ".claude", tmux, lambda p: relay.session_root(tmux, p), COMMENTS.add_line, memo)
        except Exception as e:  # noqa: BLE001 - the watch must outlive a tmux hiccup
            print(f"night watch: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(interval)


def last_sweep(max_bytes=65536):''')
rep('''    deliver_comments(out)
    snap = INDEXER.snapshot() if INDEXER else []
    usage.card_alerts(out, snap)
    usage.card_labels(out, snap)
''', '''    snap = INDEXER.snapshot() if INDEXER else []
    th, prices = INDEXER.settings() if INDEXER else (None, None)
    usage.card_alerts(out, snap, th, prices)
    usage.card_labels(out, snap)
    queue_handovers(out, snap, th, prices)   # before delivery, so a line queued this build goes out this build
    mark_night(out)
    deliver_comments(out)
''')
rep('''    INDEXER.start()
''', '''    INDEXER.start()
    threading.Thread(target=night_watch, name="night-watch", daemon=True).start()
''')
p.write_text(s)
h = Path("board/index.html"); s = h.read_text()
old = '''    const b = el("button", "tab" + (s.name === (session() || {}).name ? " on" : ""), s.name);'''
new = '''    const b = el("button", "tab" + (s.name === (session() || {}).name ? " on" : ""), s.night ? `${s.name} 🌙` : s.name);   // 🌙: night mode (tmux-ctl night on)'''
assert s.count(old) == 1, "renderTabs anchor"
h.write_text(s.replace(old, new))
print("server.py and index.html patched")
```

  The overseer plan adds its own threads next to `INDEXER.start()`; the `night-watch` thread goes after them, order irrelevant. If the overseer moved `deliver_comments(out)` or the `card_alerts` lines in `build_state`, keep this order: `card_alerts(out, snap, th, prices)`, `card_labels`, `queue_handovers`, `mark_night`, `deliver_comments`.

- [ ] **Step 4: GREEN.** The Verify command → `Ran 7 tests … OK`; then `python3 -m unittest discover -s board/tests -p 'test_agent_controls.py'`, `-p 'test_poll_efficiency.py'`, `-p 'test_reload.py'` → each `OK`.

- [ ] **Step 5: Mutations, once each, restore after each:** the three listed in the Acceptance Criteria.

- [ ] **Step 6: Commit** `feat(board): handover line to the lead, 🌙 night marker, night-watch thread` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["board/server.py", "board/index.html", "board/tests/test_night_server.py"], "acceptanceCriteria": ["handover line once per session; again only over 100% after ten minutes; other projects excluded", "held while the lead pane waits or has typed text; typed when ready", "mark_night from the state file; 🌙 in renderTabs; night-watch thread started in __main__", "build order: card_alerts(th, prices), card_labels, queue_handovers, mark_night, deliver_comments", "7 tests OK; server-loading suites still OK; three mutations each fail their named test"], "modelTier": "standard", "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_night_server.py'"}
```

### Task 4: tmux-ctl night on|off|status

**Goal:** `tmux-ctl night on | off | status` runs `board/night.py` for the caller's project (`--session "$SESSION" --project "$FEEDKEY" --root <git toplevel>`), and the header/help name it; a zsh test drives it on a scratch tmux server with `TC_CAFFEINATE_CMD='sleep 300'`.

**Files:**
- Modify: `bin/tmux-ctl` (two header lines, the `night)` case before `""|-h|--help|help)`, the help `sed -n '2,Np'` range +2)
- Create: `tools/tests/test_ctl_night.zsh`

**Acceptance Criteria:**
- [ ] `tmux-ctl night status` → `night mode off for tt`; `night on` exits 0, sets `@tc_night=1` on `=tt:`, writes `$TC_STATE/night-tt.json` whose `pid` runs `sleep 300` and whose `cmd` is `["sleep","300"]`, prints `caffeinate pid <pid>`; a second `on` keeps the pid and says `already on`.
- [ ] With three fake Claude panes (a copied `/bin/bash` named `claude`, codesigned) showing `accept edits on`, `auto mode on`, and a `Do you want to proceed?` menu, `night on` prints `window '✦ manual' is not in auto permission mode` and `window '✦ asks' is waiting at a permission prompt or a question` to stderr, nothing about `✦ auto`, and still sets the option.
- [ ] `night off` unsets the option, removes the file, kills the recorded pid (seen gone within 5 s), says `stopped caffeinate (pid N)` and `morning report .superpowers/night/<YYYY-MM-DD>.md`; with the file's `pid` edited to the test's own shell, `off` kills nothing and says `is not caffeinate any more; not killed`; `night bogus` exits 2; `tmux-ctl help` lists `night on | off | status`; the leak check finds no keep-awake process of the test alive.
- [ ] `zsh tools/tests/test_ctl_night.zsh` → `ALL PASS` (32 checks). Mutation, once, restored: in `board/night.py` `kill(pid, signal.SIGTERM)` → `pass` fails `off kills the recorded pid` and the leak check.

**Verify:** `zsh tools/tests/test_ctl_night.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test.** Create `tools/tests/test_ctl_night.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
# tmux-ctl night on|off|status (board/night.py). TC_CAFFEINATE_CMD='sleep 300' stands in for `caffeinate -i`: the pid file,
# the ps match and the kill path are the same. Fake Claude panes: a copy of /bin/sh named claude (pane_current_command
# must look like Claude for paneclass.classify; a copy of /bin/sh shows as "bash" because sh re-execs it), codesigned so macOS runs the copy, exec'd from a script that first
# prints the status line a real pane shows (captured 2026-10-28 from Claude Code 2.1.312: "⏵⏵ auto mode on (shift+tab to cycle)").
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude
export TC_CAFFEINATE_CMD='sleep 300'
f="$TC_STATE/night-tt.json"
opt() { tt show-options -qv -t '=tt:' @tc_night }
alive() { kill -0 "$1" 2>/dev/null }
check "status off before"                   zsh -c '[[ "$($1 night status)" == "night mode off for tt" ]]' _ "$C"
out="$($C night on 2>"$TT_DIR/warn")"; rc=$?
check "on exits 0"                          test $rc -eq 0
check "on sets @tc_night=1 on the session"  test "$(opt)" = 1
check "on writes the pid file"              test -s "$f"
pid="$(jq -r .pid "$f")"
check "recorded pid runs the keep-awake command" zsh -c '[[ "$(ps -o command= -p $1)" == "sleep 300" ]]' _ "$pid"
check "pid file records the command"        test "$(jq -c .cmd "$f")" = '["sleep","300"]'
check "on names the pid"                    zsh -c '[[ $1 == *"caffeinate pid $2"* ]]' _ "$out" "$pid"
check "status says on with the pid"         zsh -c '[[ "$($1 night status)" == *"caffeinate pid $2 running"* ]]' _ "$C" "$pid"
out2="$($C night on 2>/dev/null)"
check "second on keeps the same pid"        test "$(jq -r .pid "$f")" = "$pid"
check "second on says already on"           zsh -c '[[ $1 == *"already on"* ]]' _ "$out2"
# the check on `on`: non-auto and waiting Claude panes draw warnings; an auto pane does not; warnings never stop night mode
mkdir -p "$TT_DIR/bin"; cp /bin/bash "$TT_DIR/bin/claude"; codesign --force -s - "$TT_DIR/bin/claude" 2>/dev/null   # /bin/sh re-execs bash and would show as "bash"
fake() {   # fake <window name> <lines...>: a window whose Claude-looking pane shows these lines
  local n="$1"; shift; local s="$TT_DIR/$n.sh"
  { print '#!/bin/sh'; for l in "$@"; do print -r -- "printf '%s\\n' ${(qq)l}"; done; print -r -- "exec ${(q)TT_DIR}/bin/claude -c 'sleep 300; :'"; } > "$s"
  chmod +x "$s"; tt new-window -d -t '=tt:' -n "✦ $n" "$s"
}
fake manual "❯ " "  ⏵⏵ accept edits on (shift+tab to cycle)"
fake auto   "❯ " "  ⏵⏵ auto mode on (shift+tab to cycle)"
fake asks   "Do you want to proceed?" "❯ 1. Yes" "  2. No" "  ⏵⏵ auto mode on (shift+tab to cycle)"
tt_wait 5 zsh -c '[[ "$(tmux -S ${TMUX%%,*} display -p -t "=tt:✦ asks" "#{pane_current_command}")" == claude ]]' 2>/dev/null
check "fake panes look like Claude"         test "$(tt display -p -t '=tt:✦ asks' '#{pane_current_command}')" = claude
$C night on >/dev/null 2>"$TT_DIR/warn2"
check "warns about the non-auto window"     grep -q "window '✦ manual' is not in auto permission mode" "$TT_DIR/warn2"
check "warns about the waiting window"      grep -q "window '✦ asks' is waiting at a permission prompt or a question" "$TT_DIR/warn2"
check "no warning for the auto window"      zsh -c '! grep -q "✦ auto" "$1"' _ "$TT_DIR/warn2"
check "warnings do not stop night mode"     test "$(opt)" = 1
out3="$($C night off)"
check "off unsets the option"               test -z "$(opt)"
check "off removes the pid file"            test ! -e "$f"
check "off kills the recorded pid"          tt_wait 5 zsh -c '! kill -0 $1 2>/dev/null' _ "$pid"
check "off names what it stopped"           zsh -c '[[ $1 == *"stopped caffeinate (pid $2)"* ]]' _ "$out3" "$pid"
check "off asks for the morning report"     zsh -c '[[ $1 == *"morning report .superpowers/night/<YYYY-MM-DD>.md"* ]]' _ "$out3"
check "status off after"                    zsh -c '[[ "$($1 night status)" == "night mode off for tt" ]]' _ "$C"
# a pid that is no longer the keep-awake command is never killed (the file is edited to point at this test's own shell)
$C night on >/dev/null 2>&1; pid2="$(jq -r .pid "$f")"
jq --argjson p $$ '.pid = $p' "$f" > "$f.new" && mv "$f.new" "$f"
out4="$($C night off)"
check "a reused pid is not killed"          alive $$
check "off says why it did not kill"        zsh -c '[[ $1 == *"is not caffeinate any more; not killed"* ]]' _ "$out4"
kill "$pid2" 2>/dev/null   # the real keep-awake process from this round: ours to clean up
$C night bogus >/dev/null 2>&1; check "bad subcommand exits 2" test $? -eq 2
check "help lists night"                    zsh -c '$1 help | grep -q "night on | off | status"' _ "$C"
check "leak check: no keep-awake process of this test left" zsh -c '! kill -0 $1 2>/dev/null && ! kill -0 $2 2>/dev/null' _ "$pid" "$pid2"
tt_done
```

- [ ] **Step 2: RED.** The Verify command → `18 FAILED` (every `night` call dies `tmux-ctl: unknown command 'night' (tmux-ctl help)`, exit 2; the remaining checks pass trivially on empty output).

- [ ] **Step 3: Apply the patch script** (worktree root; the help range is computed from the current `sed -n '2,Np'`, so the overseer's/teams' header lines are fine):

```python
"""Task 4 patch: the `night` subcommand in bin/tmux-ctl, its two header lines, and the help range."""
import re
from pathlib import Path
p = Path("bin/tmux-ctl"); s = p.read_text()
def rep(old, new):
    global s
    assert s.count(old) == 1, ("anchor not unique or missing", old[:70], s.count(old))
    s = s.replace(old, new)
# header: two lines after the last `#   tmux-ctl …` usage line (the header block ends with a bare `#` line)
header_end = s.index("\n#\n# send/run only type into windows' main pane")
assert header_end > 0, "header end anchor"
s = s[:header_end] + '''
#   tmux-ctl night on | off | status       night mode for this project: keep the Mac awake (caffeinate) while the
#                                          plan runs, warn about waiting prompts / non-auto agents / battery, set @tc_night''' + s[header_end:]
# help prints the header with sed -n '2,Np': N grows by the two lines added above
m = re.search(r"sed -n '2,(\d+)p' \"\$0\"", s)
assert m, "help sed range"
s = s.replace(m.group(0), f"sed -n '2,{int(m.group(1)) + 2}p' \"$0\"")
rep('''  ""|-h|--help|help)''', '''  night)
    [[ "$1" == (on|off|status) ]] || die "usage: tmux-ctl night on|off|status"
    warn_web_key
    root="$(git rev-parse --show-toplevel 2>/dev/null)" || root="$PWD"
    # board/night.py owns the state ($STATE/night-<project>.json), the check and the caffeinate pid; TC_CAFFEINATE_CMD overrides the command (tests)
    python3 -I "${0:A:h:h}/board/night.py" "$1" --session "$SESSION" --project "$FEEDKEY" --root "$root" ;;

  ""|-h|--help|help)''')
p.write_text(s)
print("tmux-ctl patched")
```

- [ ] **Step 4: GREEN.** The Verify command → `ALL PASS`; `tmux-ctl help | tail -3` shows the two new lines and the blank line, nothing from the code below the header.

- [ ] **Step 5: Mutation, once:** `board/night.py` `            kill(pid, signal.SIGTERM)` → `            pass`; Verify → `2 FAILED` (`off kills the recorded pid`, `leak check…`); restore; Verify → `ALL PASS`.

- [ ] **Step 6: Commit** `feat(tmux-ctl): night on|off|status` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_night.zsh"], "acceptanceCriteria": ["on: option, pid file with cmd, pid runs the command, second on idempotent", "the three warnings from fake Claude panes; auto pane quiet; warnings never block", "off: option unset, file gone, recorded pid killed, reused pid left alone, morning-report hint", "bad subcommand exit 2; help lists night; leak check", "ALL PASS; the kill mutation fails two checks"], "modelTier": "standard", "verifyCommand": "zsh tools/tests/test_ctl_night.zsh"}
```

### Task 5: night-guard.sh hook, registration, test

**Goal:** `claude/plugin/scripts/night-guard.sh` (PreToolUse `AskUserQuestion`) denies the question while the project's canonical session has `@tc_night=1`, is silent otherwise and with `TC_NIGHT_GUARD=0`, fails open on any error; it is registered in `hooks.json`, named in `plugin.json`, and checked by `test_night_guard.zsh` and `test_plugin.zsh`.

**Files:**
- Create: `claude/plugin/scripts/night-guard.sh` (`chmod +x`)
- Create: `tools/tests/test_night_guard.zsh`
- Modify: `claude/plugin/hooks/hooks.json` (second entry under the `AskUserQuestion` matcher), `claude/plugin/.claude-plugin/plugin.json` (description), `tools/tests/test_plugin.zsh` (two registration checks)

**Acceptance Criteria:**
- [ ] Night mode off → exit 0, no output. `@tc_night=1` on `=tt:` → exit 2 with stderr `Night mode: decide and log it as an assumption, or park the task as blocked; the user reads the morning report. (Kill switch: TC_NIGHT_GUARD=0.)`; `--scoped` behaves the same; a `Bash` payload passes; `TC_NIGHT_GUARD=0`, garbage input, empty input, `TMUX`/`TMUX_PANE` unset and `TC_TMUX=/usr/bin/false` all exit 0 silently; `{"tool_name":"AskUserQuestion"}` without `tool_input` is still denied; from a pane of a grouped `_web-9` view (which carries no option) the hook is still denied via the canonical session; after `set-option -u` it passes again.
- [ ] `hooks.json` has exactly one `night-guard.sh" --scoped` entry, under matcher `AskUserQuestion`, timeout 10; `plugin.json`'s description names `night-guard`.
- [ ] `zsh tools/tests/test_night_guard.zsh` → `ALL PASS` (15 checks); `zsh tools/tests/test_plugin.zsh` → `ALL PASS` (the two new checks pass; the Task 7 prose checks are not in yet). Mutations, once each, restored: `[[ "$night" == 1 ]]` → `== 2` fails 5 checks (every deny); `'#{?session_group,#{session_group},#{session_name}}'` → `'#{session_name}'` fails `from the view's pane: denied via the canonical session`.

**Verify:** `zsh tools/tests/test_night_guard.zsh && zsh tools/tests/test_plugin.zsh` → `ALL PASS` twice

**Steps:**

- [ ] **Step 1: Write the failing test.** Create `tools/tests/test_night_guard.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
# night-guard: PreToolUse(AskUserQuestion) hook that denies a question while the project's canonical tmux session has
# @tc_night=1 (tmux-ctl night on). Feeds PreToolUse JSON on stdin; the AskUserQuestion tool_input shape is the one
# test_plan_handoff_guard.zsh copied from a real transcript on 2026-10-28.
H="${TC_NIGHTGUARD:-$TT_REPO/claude/plugin/scripts/night-guard.sh}"
tt_setup claude
tmp="$TT_DIR"
MSG="Night mode: decide and log it as an assumption, or park the task as blocked; the user reads the morning report."
payload() { python3 -c 'import json,sys; print(json.dumps({"tool_name":sys.argv[1],"tool_input":{"questions":[{"question":"Merge into main now?","header":"Merge","multiSelect":False,"options":[{"label":"A","description":"a"},{"label":"B","description":"b"}]}]}}))' "${1:-AskUserQuestion}"; }
run_hook() { payload "$@" | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
denied()  { run_hook "$@"; [[ $rc == 2 && "$err" == *"$MSG"* ]]; }
allowed() { run_hook "$@"; [[ $rc == 0 && -z "$out" && -z "$err" ]]; }
check "night mode off: question allowed"            allowed
tt set-option -t '=tt:' @tc_night 1
check "night mode on: denied with the night message" denied
check "deny text names the kill switch"             zsh -c '[[ $1 == *TC_NIGHT_GUARD=0* ]]' _ "$(run_hook; print -r -- $err)"
check "other tools pass"                            allowed Bash
payload | TC_NIGHT_GUARD=0 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "TC_NIGHT_GUARD=0 lets the question through"  test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?
check "--scoped registration denies the same way"   test $rc -eq 2
echo 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "garbage input: exit 0, silent"               test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
printf '' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "empty input: exit 0, silent"                 test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
print -r -- '{"tool_name":"AskUserQuestion"}' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "no tool_input: still denied (the tool name decides)" test $rc -eq 2
payload | TMUX= TMUX_PANE= "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "outside tmux: allowed"                       test $rc -eq 0 -a ! -s "$tmp/e"
payload | TC_TMUX=/usr/bin/false "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "tmux failing: allowed (fail-open)"           test $rc -eq 0 -a ! -s "$tmp/e"
# the board's _web-* views are grouped sessions: they share the windows but not the option, so the hook asks the canonical session
tt new-session -d -s _web-9 -t tt
check "grouped view does not carry the option"      test -z "$(tt show-options -qv -t '=_web-9:' @tc_night)"
payload | TMUX_PANE="$(tt display -p -t '=_web-9:claude' '#{pane_id}')" "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "from the view's pane: denied via the canonical session" test $rc -eq 2
tt kill-session -t '=_web-9'
tt set-option -u -t '=tt:' @tc_night
check "after night off: allowed again"              allowed
tt_done
```

- [ ] **Step 2: RED.** `zsh tools/tests/test_night_guard.zsh` → `13 FAILED` (no such hook file: every run fails with `no such file or directory`, the two "allowed" checks on unset TMUX pass trivially).

- [ ] **Step 3: Create `claude/plugin/scripts/night-guard.sh`** and `chmod +x` it:

```bash
#!/usr/bin/env bash
# PreToolUse(AskUserQuestion): while the project is in night mode (@tc_night=1 on its canonical tmux session, set by
# `tmux-ctl night on`), deny the question so the lead decides and logs an assumption, or parks the task as blocked
# (docs/superpowers/specs/2026-10-28-night-mode-and-teammate-handover-design.md). Silent when night mode is off, outside
# tmux, and with TC_NIGHT_GUARD=0. Fail-open: any error lets the question through. --scoped (the plugin registration)
# is accepted and changes nothing. The board's _web-* views are grouped sessions that share the windows but not the
# option, so the canonical session (#{session_group}, else the session name) is asked, as tmux-ctl's FEEDKEY does.
[[ "$TC_NIGHT_GUARD" == 0 ]] && { cat >/dev/null; exit 0; }
input=$(cat) || exit 0
[[ -n "$TMUX" && -n "$TMUX_PANE" ]] || exit 0
tool=$(python3 -I -c 'import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get("tool_name") or "" if isinstance(d, dict) else "")
except Exception:
    print("")' "$input" 2>/dev/null) || exit 0
[[ "$tool" == AskUserQuestion ]] || exit 0
# tmux binary in bin/_tc_bins.zsh's order: TC_TMUX, ~/.local/bin/tmux if executable, tmux on PATH; the server is $TMUX's
if [[ -n "$TC_TMUX" ]]; then tmux_bin="$TC_TMUX"
elif [[ -x "$HOME/.local/bin/tmux" ]]; then tmux_bin="$HOME/.local/bin/tmux"
else tmux_bin=$(command -v tmux) || exit 0; fi
canon=$("$tmux_bin" -S "${TMUX%%,*}" display -p -t "$TMUX_PANE" '#{?session_group,#{session_group},#{session_name}}' 2>/dev/null) || exit 0
[[ -n "$canon" ]] || exit 0
night=$("$tmux_bin" -S "${TMUX%%,*}" show-options -qv -t "=${canon}:" @tc_night 2>/dev/null) || exit 0
[[ "$night" == 1 ]] || exit 0
printf '%s\n' "Night mode: decide and log it as an assumption, or park the task as blocked; the user reads the morning report. (Kill switch: TC_NIGHT_GUARD=0.)" >&2
exit 2
```

- [ ] **Step 4: Apply the registration patch script** (worktree root; the `plugin.json` edit appends `and night-guard` to whatever hook list the description holds):

```python
"""Task 5 patch: register night-guard in hooks.json and plugin.json; add the registration checks to test_plugin.zsh."""
from pathlib import Path
h = Path("claude/plugin/hooks/hooks.json"); s = h.read_text()
old = '''"command": "\\"${CLAUDE_PLUGIN_ROOT}/scripts/plan-handoff-guard.sh\\" --scoped", "timeout": 10 }
        ]'''
new = '''"command": "\\"${CLAUDE_PLUGIN_ROOT}/scripts/plan-handoff-guard.sh\\" --scoped", "timeout": 10 },
          { "type": "command", "command": "\\"${CLAUDE_PLUGIN_ROOT}/scripts/night-guard.sh\\" --scoped", "timeout": 10 }
        ]'''
assert s.count(old) == 1, "hooks.json: the AskUserQuestion matcher's plan-handoff-guard entry"
h.write_text(s.replace(old, new))
j = Path("claude/plugin/.claude-plugin/plugin.json"); s = j.read_text()
assert "night-guard" not in s and " hooks" in s, "plugin.json description"
# the description lists the hooks as "…, X and Y hooks": add night-guard as the last one, whatever the list holds today
i = s.index(" hooks"); k = s.rfind(" and ", 0, i)
assert k > 0, "plugin.json: ' and ' before ' hooks'"
s = s[:k] + ", " + s[k + len(" and "):i] + " and night-guard" + s[i:]
j.write_text(s)
t = Path("tools/tests/test_plugin.zsh"); s = t.read_text()
old = '''check "settings.json no longer registers hooks (no double run)"'''
new = '''check "hooks.json registers night-guard on PreToolUse AskUserQuestion, --scoped, timeout 10" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]["PreToolUse"]
hit = [(e["matcher"], h) for e in d for h in e["hooks"] if h["command"].endswith("/scripts/night-guard.sh\\" --scoped")]
assert len(hit) == 1 and hit[0][0] == "AskUserQuestion" and hit[0][1]["timeout"] == 10, hit
PY
check "plugin.json names night-guard" grep -q night-guard "$P/.claude-plugin/plugin.json"
check "settings.json no longer registers hooks (no double run)"'''
assert s.count(old) == 1, "test_plugin.zsh anchor"
t.write_text(s.replace(old, new))
print("hooks.json, plugin.json, test_plugin.zsh patched")
```

- [ ] **Step 5: GREEN.** The Verify command → `ALL PASS` twice (`test_plugin.zsh` may print `skip - no claude (headless probe)` or skip the parity block; those are not failures).

- [ ] **Step 6: Mutations, once each, restore after each:** the two listed in the Acceptance Criteria, with `zsh tools/tests/test_night_guard.zsh`.

- [ ] **Step 7: Commit** `feat(plugin): night-guard denies AskUserQuestion while night mode is on` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["claude/plugin/scripts/night-guard.sh", "tools/tests/test_night_guard.zsh", "claude/plugin/hooks/hooks.json", "claude/plugin/.claude-plugin/plugin.json", "tools/tests/test_plugin.zsh"], "acceptanceCriteria": ["denies with the spec message while @tc_night=1 on the canonical session, also from a grouped view pane", "silent when off, TC_NIGHT_GUARD=0, other tools, garbage/empty input, outside tmux, tmux failing", "registered once under AskUserQuestion with --scoped and timeout 10; plugin.json names it", "test_night_guard ALL PASS (15), test_plugin ALL PASS; two mutations fail their named checks"], "modelTier": "standard", "verifyCommand": "zsh tools/tests/test_night_guard.zsh && zsh tools/tests/test_plugin.zsh"}
```

### Task 6: tmux-session-closed stops the project's caffeinate

**Goal:** When a project's last session closes, `bin/tmux-session-closed` stops the recorded keep-awake pid through `board/night.py _stop` (recorded pid only, still running the recorded command) and removes `night-<project>.json` with the other per-project state. (Spec gap filled: the spec names the board and `night off` as the only stoppers; a closed project has neither, and its caffeinate would run until reboot.)

**Files:**
- Modify: `bin/tmux-session-closed` (two lines before the `rm -f`, `night-$n.json` added to it)
- Modify: `tools/tests/test_session_closed.zsh` (four checks before the hostile-names block)

**Acceptance Criteria:**
- [ ] Closing session `nite` whose `night-nite.json` records a live `sleep 300` pid with `cmd ["sleep","300"]` kills that pid (gone within 5 s) and removes the file.
- [ ] Closing `nite2` whose file records the test's own shell pid with `cmd ["caffeinate","-i"]` leaves that shell alive and still removes the file.
- [ ] `zsh tools/tests/test_session_closed.zsh` → `ALL PASS` (the 16 existing checks plus 4). Mutation, once, restored: the `[[ -f "$STATE/night-$n.json" ]] && python3 …` line's test → `[[ -f "$STATE/nope" ]]` fails `night: the recorded keep-awake pid is stopped`.

**Verify:** `zsh tools/tests/test_session_closed.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Apply the patch script** (worktree root). It adds the test checks and the hook lines together; run the test first with only the test half if you want a RED — the RED for this change is the mutation in Step 3, which is the same check failing for the same reason (pid alive):

```python
"""Task 6 patch: tmux-session-closed stops the project's recorded caffeinate pid; test case in test_session_closed.zsh."""
from pathlib import Path
c = Path("bin/tmux-session-closed"); s = c.read_text()
old = '''rm -f -- "$STATE/artifacts-$n.jsonl" "$STATE/lineage-$n.jsonl" "$STATE/runs-$n.jsonl" \\
  "$STATE/feed-$n-tests.log" "$STATE/feed-$n-shell.log" "$STATE/relay-$n.log" "$STATE/relay-failed-$n.txt"'''
new = '''# night mode: the project's keep-awake process goes with it, by its recorded pid only (night.py checks the pid still runs caffeinate)
[[ -f "$STATE/night-$n.json" ]] && python3 -I "${0:A:h:h}/board/night.py" _stop --project "$n" >/dev/null 2>&1
rm -f -- "$STATE/artifacts-$n.jsonl" "$STATE/lineage-$n.jsonl" "$STATE/runs-$n.jsonl" "$STATE/night-$n.json" \\
  "$STATE/feed-$n-tests.log" "$STATE/feed-$n-shell.log" "$STATE/relay-$n.log" "$STATE/relay-failed-$n.txt"'''
assert s.count(old) == 1, "tmux-session-closed rm -f anchor"
c.write_text(s.replace(old, new))
t = Path("tools/tests/test_session_closed.zsh"); s = t.read_text()
old = '''# hostile session names must never reach a shell'''
new = '''# night mode: the recorded keep-awake pid dies with the project, and only that pid
mk nite; sleep 300 & spid=$!
print -r -- "{\\"project\\":\\"nite\\",\\"pid\\":$spid,\\"since\\":1,\\"cmd\\":[\\"sleep\\",\\"300\\"]}" > "$TC_STATE/night-nite.json"
mk nite2; print -r -- "{\\"project\\":\\"nite2\\",\\"pid\\":$$,\\"since\\":1,\\"cmd\\":[\\"caffeinate\\",\\"-i\\"]}" > "$TC_STATE/night-nite2.json"
tt new-session -d -s nite -c "$TT_DIR"; tt new-session -d -s nite2 -c "$TT_DIR"
tt kill-session -t '=nite'; tt kill-session -t '=nite2'
check "night: the recorded keep-awake pid is stopped" tt_wait 5 zsh -c '! kill -0 $1 2>/dev/null' _ "$spid"
check "night: the state file is removed"            tt_wait 5 test ! -e "$TC_STATE/night-nite.json"
check "night: a pid that is not caffeinate is left alone" kill -0 $$
check "night: its state file is still removed"      tt_wait 5 test ! -e "$TC_STATE/night-nite2.json"
# hostile session names must never reach a shell'''
assert s.count(old) == 1, "test_session_closed.zsh anchor"
t.write_text(s.replace(old, new))
print("tmux-session-closed and test_session_closed.zsh patched")
```

- [ ] **Step 2: GREEN.** The Verify command → `ALL PASS`.

- [ ] **Step 3: Mutation, once:** `[[ -f "$STATE/night-$n.json" ]] && python3` → `[[ -f "$STATE/nope" ]] && python3`; Verify → `1 FAILED` (`night: the recorded keep-awake pid is stopped`); restore; Verify → `ALL PASS`.

- [ ] **Step 4: Commit** `fix(tmux-session-closed): stop the project's caffeinate by its recorded pid` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["bin/tmux-session-closed", "tools/tests/test_session_closed.zsh"], "acceptanceCriteria": ["recorded live pid killed and file removed on close", "a pid that is not the recorded command is left alone; file still removed", "ALL PASS; the mutation fails the pid check"], "modelTier": "mechanical", "verifyCommand": "zsh tools/tests/test_session_closed.zsh"}
```

### Task 7: orchestrator.md + handoff skill: night mode, handover, checkpoint now

**Goal:** `claude/orchestrator.md` gains the "Night mode" section (reversible choices → `assumed:`, gates → `blocked: waiting for user — …`, teammates' questions, the hook, the morning report), the "Teammate handover" rule (five steps, no asking in night mode) and teammate rule 9 (`checkpoint now` → `.superpowers/checkpoints/<name>.md` → `checkpoint written`, never a new task after it); the handoff skill points its teammate checkpoint at the same shape; `test_plugin.zsh` checks the needles.

**Files:**
- Modify: `claude/orchestrator.md` (two sections before "## Workflow: the superpowers skills, automatically"; the preamble count `rules 1–8` → `1–9`; rule 9 after rule 8)
- Modify: `claude/plugin/skills/handoff/SKILL.md` (one paragraph in step 1)
- Modify: `tools/tests/test_plugin.zsh` (two checks before "# 3. headless probe")

**Acceptance Criteria:**
- [ ] `orchestrator.md` contains `## Night mode`, `## Teammate handover`, `` `checkpoint now` ``, `` `checkpoint written` ``, `.superpowers/checkpoints/<name>.md`, `assumed:`, `blocked: waiting for user`, `handover: <name> at <N>K`, `.superpowers/night/<YYYY-MM-DD>.md`, `rules 1–9`; the handover steps are exactly the spec's five in order; the morning report lists the spec's four items; the teammate rule names the six headings (task, files, progress, next step, assumptions, how to verify).
- [ ] `handoff/SKILL.md` names `.superpowers/checkpoints/<name>.md` as the shape of its step-1 checkpoint.
- [ ] `zsh tools/tests/test_plugin.zsh` → `ALL PASS` (its item-4 check that every skill name in `orchestrator.md` resolves still passes: the new text names no new skills). Mutation, once, restored: delete the `9. On the message …` rule → the `orchestrator.md has Night mode…` check fails with `AssertionError: `checkpoint now``.
- [ ] If an earlier plan of the round already renumbered the teammate rules (the preamble no longer says `rules 1–8`), the new rule takes the next number and both the preamble and the needle `rules 1–9` in `test_plugin.zsh` are adjusted to it; say so in the report.

**Verify:** `zsh tools/tests/test_plugin.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Apply the patch script** (worktree root; it adds the two `test_plugin.zsh` checks too, so Step 2 is RED only if you run the test half first; the RED of record is the Step 4 mutation):

```python
"""Task 7 patch: Night mode section, Teammate handover rule and teammate rule 9 in claude/orchestrator.md; the shared
checkpoint shape in the handoff skill; the prose checks in test_plugin.zsh."""
from pathlib import Path
p = Path("claude/orchestrator.md"); s = p.read_text()
def rep(old, new):
    global s
    assert s.count(old) == 1, ("anchor not unique or missing", old[:70], s.count(old))
    s = s.replace(old, new)
rep('''## Workflow: the superpowers skills, automatically''', '''## Night mode

`tmux-ctl night on` (per project; also `off` and `status`) puts the project in night mode: the tmux session option `@tc_night=1` is set, the board shows 🌙 on the project, and `caffeinate -i` keeps the Mac awake until the board sees no open plan task and no running test, or night mode is turned off. While `@tc_night=1` nobody is reading, so nothing may wait on the user:

- **Reversible choices** (a wording, a fixture, one of two equivalent approaches): make the reasonable choice, continue, and record `assumed: <choice> (task <id>)` in the plan's SDD progress ledger.
- **Gates** (destructive steps, merges, pushes, shared-state changes, removing anything, and the user-confirm steps a loaded skill names, such as `finishing-a-development-branch`'s integration question): don't ask. Mark the task `blocked: waiting for user — <question>` (TaskUpdate), log the same line in the ledger, and continue with the tasks that don't depend on it.
- **Teammates' questions** reach you as usual; apply the same two rules to them.
- The plugin's `night-guard.sh` hook denies AskUserQuestion while `@tc_night=1` (`TC_NIGHT_GUARD=0` disables it). The two rules above are what to do instead, not a reason to retry the question.
- **Morning report.** When night mode is turned off, or the active plan finishes while it is on (the board types a `[Board] Night …` line into your window either way), write `.superpowers/night/<YYYY-MM-DD>.md` and register it with `tmux-ctl artifact <path> --kind report`. It lists: finished tasks with their evidence; every `assumed:` line; blocked tasks and their questions; test runs with their exit codes (the ledger, `tmux-ctl feed` and the board's Runs tab have them).

## Teammate handover

A teammate's context has a budget per tier (`usage-alerts.json` → `teammate_context_budget`; default 150K mechanical, 300K standard and frontier). When a teammate reaches 85% of it, the board types `[Board] Teammate <name> is at <N>K context (<tier> budget <B>K): hand it over.` into your window (once; once more if it is still over 100% ten minutes later). On that line, replace the teammate under the same name:

1. Send it `checkpoint now` (SendMessage).
2. Wait for its reply `checkpoint written`. After two minutes without one, treat it as `no checkpoint`, as the handoff skill does, and capture its window with `tmux-ctl read "✦ <name>" 40`.
3. Send the shutdown request and wait for the termination notice (the "Replacing a stalled teammate" rule below).
4. Start a fresh teammate with the same name, role and tier. Its prompt is the teammate rules (1–9 below) followed by the contents of `.superpowers/checkpoints/<name>.md` (or the captured output, with "re-check the state of your files before continuing").
5. Log `handover: <name> at <N>K` in the plan's SDD progress ledger.

In night mode, run this without asking.

## Workflow: the superpowers skills, automatically''')
# the preamble counts the teammate rules: 1–8 today (an earlier plan of the round may have made it 1–9 already; then the new rule is 10 and the count 1–10: adjust both numbers below by hand)
rep('''copies rules 1–8 word for word or points to this section''', '''copies rules 1–9 word for word or points to this section''')
rep('''8. Do not invoke `task-observer` or write to its log (the session-start protocol is the lead's); put any
   skill findings in the final report for you to log.
''', '''8. Do not invoke `task-observer` or write to its log (the session-start protocol is the lead's); put any
   skill findings in the final report for you to log.
9. On the message `checkpoint now`: finish the current step, not the whole task; write
   `.superpowers/checkpoints/<name>.md` with these headings, in this order: task (id and subject), files you own,
   progress so far, next step, assumptions made, how to verify (the same shape as the handoff skill's teammate
   checkpoints); reply `checkpoint written`; and never start a new task after it.
''')
p.write_text(s)
h = Path("claude/plugin/skills/handoff/SKILL.md"); s = h.read_text()
old = '''Wait up to 2 minutes for the replies.'''
new = '''Those fields are the shape of `.superpowers/checkpoints/<name>.md`, the file a teammate writes on `checkpoint now` (orchestrator.md → Teammate handover); a teammate that has one may reply with its path instead of repeating the fields, and you copy the file's contents into the doc.

Wait up to 2 minutes for the replies.'''
assert s.count(old) == 1, "handoff SKILL.md anchor"
h.write_text(s.replace(old, new))
t = Path("tools/tests/test_plugin.zsh"); s = t.read_text()
old = '''# 3. headless probe'''
new = '''# the lead rules carry night mode and the teammate handover; the handoff skill shares the checkpoint shape
check "orchestrator.md has Night mode, Teammate handover and the checkpoint-now teammate rule" python3 - "$R/claude/orchestrator.md" <<'PY'
import sys
s = open(sys.argv[1]).read()
for needle in ("## Night mode", "## Teammate handover", "`checkpoint now`", "`checkpoint written`", ".superpowers/checkpoints/<name>.md",
               "assumed:", "blocked: waiting for user", "handover: <name> at <N>K", ".superpowers/night/<YYYY-MM-DD>.md", "rules 1–9"):
    assert needle in s, needle
PY
check "handoff skill names the shared teammate checkpoint shape" grep -q 'checkpoints/<name>.md' "$P/skills/handoff/SKILL.md"

# 3. headless probe'''
assert s.count(old) == 1, "test_plugin.zsh anchor"
t.write_text(s.replace(old, new))
print("orchestrator.md, handoff SKILL.md, test_plugin.zsh patched")
```

- [ ] **Step 2: Read the result once** (`sed -n '/^## Night mode/,/^## Workflow/p' claude/orchestrator.md`): the two sections sit between "Plan comments from the board" and "Workflow", and rule 9 follows rule 8 in the teammate rules.

- [ ] **Step 3: GREEN.** The Verify command → `ALL PASS`.

- [ ] **Step 4: Mutation, once:** remove the four lines of rule 9; Verify → `1 FAILED` (`orchestrator.md has Night mode…`, `AssertionError: `checkpoint now``); restore; Verify → `ALL PASS`.

- [ ] **Step 5: Commit** `docs(rules): night mode, teammate handover and the checkpoint-now teammate rule` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["claude/orchestrator.md", "claude/plugin/skills/handoff/SKILL.md", "tools/tests/test_plugin.zsh"], "acceptanceCriteria": ["Night mode section: assumed:, blocked: waiting for user, teammates' questions, the hook, the four-item morning report", "Teammate handover: the spec's five steps, no asking in night mode", "teammate rule 9 with the six checkpoint headings; preamble says rules 1–9", "handoff skill names the shared checkpoint shape", "test_plugin ALL PASS; deleting rule 9 fails its check"], "modelTier": "standard", "verifyCommand": "zsh tools/tests/test_plugin.zsh"}
```

### Task 8: docs: night mode, night-guard, env vars, usage key, state file

**Goal:** `docs/ARCHITECTURE.md`, `docs/INSTALL.md` and `docs/CUSTOMIZATION.md` describe `tmux-ctl night`, `night-guard.sh`, `TC_NIGHT_GUARD`, `TC_CAFFEINATE_CMD`, `teammate_context_budget` and `night-<p>.json` next to the existing entries (observation #102: every list of hooks names the new one).

**Files:**
- Modify: `docs/ARCHITECTURE.md` (tmux-ctl subcommand table, Hooks table, usage-alerts key table, State files table)
- Modify: `docs/INSTALL.md` (the "How the rest reaches Claude…" hook list)
- Modify: `docs/CUSTOMIZATION.md` (§1 env table: two rows; §5 usage-alerts example and a paragraph; §6 a "Night guard" subsection)

**Acceptance Criteria:**
- [ ] `grep -c 'night-guard' docs/ARCHITECTURE.md docs/INSTALL.md docs/CUSTOMIZATION.md` → 2, 1, 2 (or more); `grep -c 'teammate_context_budget' docs/ARCHITECTURE.md docs/CUSTOMIZATION.md` → 1, 2; `grep -c 'night-<p>.json' docs/ARCHITECTURE.md` → 1; `grep -c 'TC_NIGHT_GUARD\|TC_CAFFEINATE_CMD' docs/CUSTOMIZATION.md` → 3.
- [ ] The ARCHITECTURE Hooks table row for `night-guard.sh` quotes the deny message and names the off switch and fail-open; the tmux-ctl row names `@tc_night`, the pid file, the stop condition and the morning report; the usage-key row states the default, the 85% alert, the routing map, the 80% cap and the lead's line.
- [ ] `python3 -m unittest discover -s board/tests -p 'test_tc_env.py'` and `zsh tools/tests/test_plugin.zsh` still pass (the docs are read by no test; this is the regression check that nothing else moved).

**Verify:** `grep -c 'night-guard' docs/ARCHITECTURE.md docs/INSTALL.md docs/CUSTOMIZATION.md && grep -c 'teammate_context_budget' docs/ARCHITECTURE.md docs/CUSTOMIZATION.md && grep -c 'night-<p>.json' docs/ARCHITECTURE.md` → `docs/ARCHITECTURE.md:2`, `docs/INSTALL.md:1`, `docs/CUSTOMIZATION.md:2`, `docs/ARCHITECTURE.md:1`, `docs/CUSTOMIZATION.md:2`, `1` (each count may be higher, never 0)

**Steps:**

- [ ] **Step 1: Apply the patch script** (worktree root). The INSTALL anchor is the tail of the `sdd-call-guard` parenthesis; if the shared-context plan already appended `context-inject` there, anchor on `, the \`tmux-orchestrator\` and \`handoff\` skills` instead and insert `night-guard (…)` before it:

```python
"""Task 8 patch: night mode, the hook, TC_NIGHT_GUARD / TC_CAFFEINATE_CMD and teammate_context_budget in the docs."""
from pathlib import Path
def patch(path, pairs):
    p = Path(path); s = p.read_text()
    for old, new in pairs:
        assert s.count(old) == 1, (path, "anchor not unique or missing", old[:60], s.count(old)); s = s.replace(old, new)
    p.write_text(s)
patch("docs/ARCHITECTURE.md", [
 ('''| `relay <doc> [--old-session ID]` | after this turn, restart the `claude` window as a fresh orchestrator reading `<doc>` (used by `/handoff`) |
''', '''| `relay <doc> [--old-session ID]` | after this turn, restart the `claude` window as a fresh orchestrator reading `<doc>` (used by `/handoff`) |
| `night on \\| off \\| status` | night mode for the project (`board/night.py`): `on` warns about Claude panes waiting at a prompt, panes not in auto permission mode and battery power, then starts `caffeinate -i`, records its pid in `night-<project>.json` and sets the session option `@tc_night=1`; `off` kills that pid (only while `ps` still shows it running caffeinate), removes the file and unsets the option. The board's `night-watch` thread stops caffeinate once the plan has no open task and no running test, and types a `[Board] Night …` line to the lead; the lead then writes the morning report (`claude/orchestrator.md`, Night mode). `TC_CAFFEINATE_CMD` replaces the command (tests use `sleep 300`) |
'''),
 ('''| PreToolUse, `Bash` | `kill-guard.sh` | nothing; exit 2 blocks the call |''', '''| PreToolUse, `AskUserQuestion` | `night-guard.sh` | nothing; exit 2 denies the question | While the project's canonical session has `@tc_night=1` (`tmux-ctl night on`), denies the question with "Night mode: decide and log it as an assumption, or park the task as blocked; the user reads the morning report." Silent when night mode is off, outside tmux, and with `TC_NIGHT_GUARD=0`; fails open on any error. |
| PreToolUse, `Bash` | `kill-guard.sh` | nothing; exit 2 blocks the call |'''),
 ('''  | `live_s` | 1800 | (not an alert) how recent a session's last call must be to count as live |
''', '''  | `live_s` | 1800 | (not an alert) how recent a session's last call must be to count as live |
  | `teammate_context_budget` | `{"mechanical": 150000, "standard": 300000, "frontier": 300000}` | `teammate_budget`: a teammate's context is at 85% of its tier's budget. The tier comes from the teammate's model through the project's `docs/superpowers/model-routing.json` (else haiku→mechanical, sonnet→standard, fable/opus→frontier); a model whose window is smaller than the budget gets 80% of its window. A partial object keeps the other tiers' defaults. The board also types `[Board] Teammate <name> is at <N>K context (<tier> budget <B>K): hand it over.` into the lead's window, once per teammate session and once more if it is still over 100% ten minutes later; the lead's handover protocol is in `claude/orchestrator.md` (Teammate handover) |
'''),
 ('''| `recent-projects.json` | board `dev` action | Open project dialog |
''', '''| `recent-projects.json` | board `dev` action | Open project dialog |
| `night-<p>.json` | `tmux-ctl night` (`board/night.py`): `{project, pid, since, cmd}`; the board clears `pid` when it stops caffeinate | board (🌙 on the tab, the `night-watch` thread), `night-guard.sh` reads the session option instead |
'''),
])
patch("docs/INSTALL.md", [
 ('''`SDD_CALL_GUARD=0` disables it), the `tmux-orchestrator` and `handoff` skills''',
  '''`SDD_CALL_GUARD=0` disables it), `night-guard` (denies AskUserQuestion while the project is in night mode, `tmux-ctl night on`; `TC_NIGHT_GUARD=0` disables it), the `tmux-orchestrator` and `handoff` skills'''),
])
patch("docs/CUSTOMIZATION.md", [
 ('''| `TC_AGENT_DRYRUN` | unset | `tmux-ctl agent` | Test seam: print the task and stop before creating a window. |
''', '''| `TC_AGENT_DRYRUN` | unset | `tmux-ctl agent` | Test seam: print the task and stop before creating a window. |
| `TC_NIGHT_GUARD` | unset | `night-guard.sh` | `0` lets AskUserQuestion through in night mode (the hook is otherwise active while `tmux-ctl night on` holds). |
| `TC_CAFFEINATE_CMD` | `caffeinate -i` | `board/night.py` (`tmux-ctl night`) | The keep-awake command night mode starts and later kills by pid; tests set `sleep 300`. |
'''),
 ('''{ "context_pct": 85, "burn_per_hour": 30, "session_total": 50, "mismatch_models": ["opus"] }
```
''', '''{ "context_pct": 85, "burn_per_hour": 30, "session_total": 50, "mismatch_models": ["opus"],
  "teammate_context_budget": { "mechanical": 100000, "standard": 250000 } }
```

`teammate_context_budget` is per tier (`mechanical`, `standard`, `frontier`); tiers you leave out keep their defaults (150K, 300K, 300K). The tier of a teammate comes from its model through the project's `docs/superpowers/model-routing.json`.
'''),
 ('''### Kill guard
''', '''### Night guard

`night-guard.sh` denies `AskUserQuestion` while the project's canonical tmux session carries `@tc_night=1` (`tmux-ctl night on`), so a lead or teammate decides and logs an assumption, or parks the task, instead of waiting for a user who is asleep (`claude/orchestrator.md`, Night mode). `TC_NIGHT_GUARD=0` disables it; it fails open on any error. The check `tmux-ctl night on` prints (waiting prompts, non-auto panes, battery) is `check()` in `board/night.py`.

### Kill guard
'''),
])
print("docs patched")
```

- [ ] **Step 2: Verify** with the command above; every count ≥ the stated value.

- [ ] **Step 3: Commit** `docs: night mode, night-guard, teammate_context_budget` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["docs/ARCHITECTURE.md", "docs/INSTALL.md", "docs/CUSTOMIZATION.md"], "acceptanceCriteria": ["night-guard in every hook list (INSTALL, ARCHITECTURE table, CUSTOMIZATION §6)", "tmux-ctl night row, usage-key row, state-file row in ARCHITECTURE", "TC_NIGHT_GUARD and TC_CAFFEINATE_CMD rows and the budget example in CUSTOMIZATION", "grep counts as stated"], "modelTier": "standard", "verifyCommand": "grep -c 'night-guard' docs/ARCHITECTURE.md docs/INSTALL.md docs/CUSTOMIZATION.md && grep -c 'teammate_context_budget' docs/ARCHITECTURE.md docs/CUSTOMIZATION.md && grep -c 'night-<p>.json' docs/ARCHITECTURE.md"}
```

### Task 9: notify.py: the teammate_budget event

**Goal:** The overseer's notifier (`board/notify.py`, from plan 2) fires one event of kind `teammate_budget` when a project's alerts gain a `teammate_budget` alert, with the alert's `detail` as text, under the notifier's existing once-per-appearance and rate-limit rules, so the user gets a banner and a board notification as well as the lead's line (spec: "B1's high-context banner tells the user as well"; a 300K budget on a 1M window is 30% context, so the `context` event alone would never fire).

**Files:**
- Modify: `board/notify.py` (`conditions()`: one `elif` before the `USAGE_KINDS` branch)
- Modify: `board/tests/test_notify.py` (one firing test, one no-refire test)
- Modify: `docs/ARCHITECTURE.md` (the overseer section's event kinds list gains `teammate_budget`); `board/index.html` only if the home view maps event kinds to icons or titles (then add the kind the same way the others are mapped)

**Acceptance Criteria:**
- [ ] An overview whose project record carries `{"kind": "teammate_budget", "label": "budget 87%", "detail": "Teammate py is at 262K context (standard budget 300K): hand it over.", "session": "py"}` makes `Notifier.observe` emit exactly one event `{"project": <name>, "kind": "teammate_budget", "key": "py", "title": "<name>: teammate at its context budget", "text": <the detail>}` (after the seeding first overview, as the other kinds); it is not emitted again while the alert holds; it is emitted again after the alert clears and returns (the latch is the notifier's).
- [ ] The event is not also counted as a `usage` event (the `elif` chain keeps one branch per alert).
- [ ] `python3 -m unittest discover -s board/tests -p 'test_notify.py'` → `OK` with two more tests than the overseer plan left (its Verify said `Ran 17 tests`; expect `Ran 19 tests`). Mutation, once, restored: the new `elif` → `elif False:` fails the firing test.
- [ ] The ARCHITECTURE event-kinds list names `teammate_budget`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_notify.py'` → `OK` (`Ran 19 tests` if the overseer plan landed its 17)

**Steps:**

- [ ] **Step 1: Read `board/notify.py` `conditions()` and `board/tests/test_notify.py` as merged.** The overseer plan's shape (its Task 3) is an `add(project, kind, key, title, text)` helper and, inside `for a in p.get("alerts") or []:`, `who = a.get("session") or name`, `if a.get("kind") == "context": add(...)`, `elif a.get("kind") in USAGE_KINDS: add(name, "usage", …)`.

- [ ] **Step 2: Write the two failing tests** next to the existing per-kind tests, using that file's fixtures (its overview builder and clock):

```python
    def test_teammate_budget_fires_once_with_the_detail(self):
        al = {"kind": "teammate_budget", "label": "budget 87%", "detail": "Teammate py is at 262K context (standard budget 300K): hand it over.", "session": "py"}
        self.n.observe(self.ov())                                   # seed
        ev = self.n.observe(self.ov(alerts=[al]))
        self.assertEqual([(e["kind"], e["key"], e["title"], e["text"]) for e in ev],
                         [("teammate_budget", "py", "proj: teammate at its context budget", al["detail"])])
        self.assertEqual(self.n.observe(self.ov(alerts=[al])), [])  # holds: no refire

    def test_teammate_budget_is_not_a_usage_event(self):
        al = {"kind": "teammate_budget", "label": "budget 87%", "detail": "d", "session": "py"}
        self.n.observe(self.ov())
        self.assertEqual([e["kind"] for e in self.n.observe(self.ov(alerts=[al]))], ["teammate_budget"])
```

  (`self.ov(alerts=…)` and `"proj"` stand for that file's overview builder and project name; adapt the two names to the merged file, nothing else.)

- [ ] **Step 3: RED.** The Verify command → `FAILED (failures=2)`: the first test gets `[]` (no event), the second `[]`.

- [ ] **Step 4: Add the branch** in `conditions()`, before the `USAGE_KINDS` branch:

```python
            elif a.get("kind") == "teammate_budget":
                add(name, "teammate_budget", who, f"{name}: teammate at its context budget",
                    a.get("detail") or f"{who} {a.get('label', '')}".strip())
```

- [ ] **Step 5: GREEN.** The Verify command → `OK`. Mutation, once: `elif a.get("kind") == "teammate_budget":` → `elif False:` → `FAILED (failures=2)`; restore → `OK`.

- [ ] **Step 6: Docs.** In `docs/ARCHITECTURE.md`, the overseer's event kinds list (`needs_you | plan_done | test_failed | lead_idle | context | usage` plus teams' `claims_overlap`, however it is written there) gains `teammate_budget` with the sentence "a teammate reached its context budget (the lead gets the handover line)". If `board/index.html`'s home view maps kinds to icons/titles, add `teammate_budget` the same way.

- [ ] **Step 7: Commit** `feat(board): teammate_budget notifier event` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["board/notify.py", "board/tests/test_notify.py", "docs/ARCHITECTURE.md", "board/index.html"], "acceptanceCriteria": ["one teammate_budget event per appearance with the alert detail as text, keyed by the teammate", "not double-counted as usage", "test_notify OK (+2 tests); the elif mutation fails both", "event kind documented"], "modelTier": "standard", "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_notify.py'"}
```

### Task 10: e2e on real state: night mode and a teammate handover

**Goal:** Prove the two flows end to end in a scratch `dev` session on a scratch board, against real long-lived state read-only, and leave the evidence in `docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md`.

**Files:**
- Create: `docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md`
- Read-only: `$TC_STATE/usage.sqlite`, `docs/superpowers/model-routing.json`, the live board's `/api/state`, `pmset -g batt`

**Constraints:**
- Scratch everything that is written: `TC_STATE`, `TC_IDEAS_DIR`, `TC_CONTEXT_DIR` point at fresh temp dirs; the board is a second instance from the worktree (`TMUX_DASH_PORT=7710 TMUX_DASH_TTYD_PORT=7711 … python3 board/server.py`, as `claude/orchestrator.md` prescribes for UI checks), the tmux server is scratch (`-L <sock> -f /dev/null`); the real `~/.config/agent-board/usage-alerts.json`, the real ideas, context and handoff folders and the live board on :7700 are not written. `pkill`/`killall` by pattern are never used; every process started is killed by PID and checked gone.
- Real state, read-only: (a) open the real `$TC_STATE/usage.sqlite` (default `${TMPDIR:-/tmp}/tmux-ctl-$UID/usage.sqlite`) with `sqlite3.connect("file:…?mode=ro", uri=True)`, run `usage.live_sessions(conn, usage.load_prices(), {**usage.DEFAULT_ALERTS, "live_s": 7*86400}, time.time())` and `usage.teammate_budget(e, th, prices, repo)` for every teammate entry of the real `agent-board` repo path, and record per teammate: name, model, tier, budget, context, alert or none (at least one real teammate session over 85% of its budget is expected in a week of history; if none, say so and show the highest ratio); (b) read the real `docs/superpowers/model-routing.json` through `usage.routing_map` and record the inverted map; (c) `GET /api/state` on the live board :7700 (read-only, with its token from `~/.local/state/tmux-dash/token`) shows `night: false` on every project and the real projects' tabs render unchanged (the `_web-*` views stay hidden); (d) `pmset -g batt` on this Mac is recorded with the check's output for it.
- Night mode: in the scratch session, with a scratch plan (a two-task `.md.tasks.json` registered through `tmux-ctl artifact`, a lead stand-in whose pane shows `⏵⏵ auto mode on` and a live task list under a scratch `HOME/.claude`), `tmux-ctl night on` starts caffeinate (real `caffeinate -i`, pid recorded, `ps` shows it), 🌙 appears on the scratch board's tab, the hook denies a real `AskUserQuestion` payload (the `night-guard.sh` run against the scratch server), and when both tasks are marked completed and no run is live the `night-watch` thread stops caffeinate within 90 s and the `[Board] Night work finished …` line reaches the lead pane (visible in `capture-pane`); `tmux-ctl night off` then prints the morning-report hint. The real flow of a lead turning a question into an `assumed:` line and the morning report in the artifacts panel is exercised with a real `claude-orchestrator` lead on a throwaway plan only if a Claude run is affordable in this session; otherwise it is recorded as "not run, by hand" with the exact prompt to run, and the hook denial above stands in for the question path.
- Handover: a scratch `usage-alerts.json` (`ALERTS_PATH` for the scratch board) with `{"teammate_context_budget": {"mechanical": 20000}}`, a real haiku teammate started by a real lead (`claude-orchestrator` in the scratch session, a two-line task that reads a few files), and the budget line observed in the lead's pane within two polls after the teammate's context passes 17K; the lead then runs the five-step handover (checkpoint written to `.superpowers/checkpoints/<name>.md`, shutdown, respawn under the same name, `handover:` ledger line). If no Claude run is affordable, the handover line's arrival is still proven with a synthetic live entry injected through the indexer's snapshot (`INDEXER._snapshot`) and the lead's steps are recorded as "not run, by hand".
- The report has these sections, in order: `## Setup` (sockets, ports, temp dirs, what real state was read), `## Real state (read-only)` (a–d with the numbers), `## Night mode` (each step with the command, its output and the pane capture), `## Handover` (the same), `## Suites` (the full board suite `OK` line and `zsh tools/tests/run-all.zsh > F; echo rc=$?` with `grep -c '^FAIL' F` = 0), `## Leak check` (`ps` for caffeinate, the scratch tmux server and the scratch board, all gone), `## Not run` (anything recorded by hand, with the exact command to run it).

**Acceptance Criteria:**
- [ ] The report exists with the seven sections (`grep -c '^## ' <report>` → 7) and is registered with `tmux-ctl artifact <report> --kind report`.
- [ ] Real state (a)–(d) appear with concrete values; nothing under `~/.config/agent-board`, `~/.local/state/agent-board` or the live board's state changed (`git status` of the main checkout and `ls -l` of those folders before/after agree).
- [ ] Night mode: caffeinate started (pid, `ps` line), 🌙 on the tab (the `/api/state` field `night: true` and a screenshot or the `curl` output), the hook denial (exit 2, message), caffeinate stopped by the watch with the `[Board] Night work finished` line captured from the lead pane, `night off` output.
- [ ] Handover: the exact `[Board] Teammate <name> is at <N>K context (mechanical budget 20K): hand it over.` line captured from the lead pane; either the five lead steps with the checkpoint file's contents and the `handover:` ledger line, or the "Not run" entry.
- [ ] Suites: `python3 -m unittest discover -s board/tests` → `OK`; `zsh tools/tests/run-all.zsh > F; echo rc=$?` → `rc=0` and `grep -c '^FAIL' F` → `0` (both through `tmux-ctl run -t 900 tests …`).
- [ ] Leak check: no `caffeinate` of this run, no scratch tmux server, no scratch board process remains (`ps -ax -o pid,command | grep -c "[c]affeinate -i"` → 0 or the pre-run count).

**Verify:** `test "$(grep -c '^## ' docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md)" = 7 && grep -q 'hand it over' docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md && grep -q 'Night work finished' docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md && echo e2e-report-ok` → `e2e-report-ok`

```json:metadata
{"files": ["docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md"], "acceptanceCriteria": ["report with seven sections, registered as an artifact", "real usage.sqlite, routing map, live board and pmset read-only with values; nothing real written", "night mode: caffeinate on, 🌙, hook denial, watch stop with the Board line, night off", "handover line captured; lead steps or Not run entry", "full board suite OK; run-all rc=0 with 0 FAIL lines", "leak check clean"], "modelTier": "frontier", "verifyCommand": "test \"$(grep -c '^## ' docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md)\" = 7 && grep -q 'hand it over' docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md && grep -q 'Night work finished' docs/superpowers/plans/2026-10-28-night-mode-and-teammate-handover-e2e-report.md && echo e2e-report-ok"}
```

---

## Self-review (plan author, 2026-10-28)

- **Spec coverage.** C1 `night on|off|status` + option + 🌙: Tasks 2–4. The check (waiting prompt, non-auto, battery, on regardless): 2, 4. Staying awake, stop by the board, recorded pid only: 2, 3, plus 6 for a closed project (spec gap, see Task 6). Questions at night, backstop hook, morning report: 5, 7. C2 budget key, cap, tier via routing map, alert at 85%, delivery through CommentQueue once / again over 100% after ten minutes, B1 banner, lead protocol, teammate rule: 1, 3, 7, 9. Docs: 8. Acceptance list: `test_night.py` (2), `test_night_guard.zsh` (5), `test_usage*.py` (1), the board queue test (3), E2E (10).
- **Placeholders.** None: every code step carries its code; Task 9's two names (`self.ov`, `"proj"`) are named as the merged file's own and nothing else is left open; Task 10 is frontier and has no Steps block.
- **Type consistency.** `night.active(project, state_dir=None)`, `night.tick(state_dir, home, tmux, root_of, notify, memo, work=open_work)`, `usage.card_alerts(sessions, live, th=None, prices=None)`, `usage.handover_lines(sessions, live, th, prices, notices, now)`, `Indexer.settings() -> (th, prices)` are used with those signatures in Tasks 1–4 and 6; the hook message and the lead line are quoted identically in Tasks 1, 3, 5, 7, 8.
- **Verify = verifyCommand** for every task (checked mechanically when the tasks file was generated).
