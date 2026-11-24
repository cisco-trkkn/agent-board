# Supervised improvement loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A code-only goal loop (`tmux-ctl improve …`) that collects proposals from the dream, discovery, scout, observer and user sources, derives their class, trials low and high ones on half of the engine-run specs by hash, keeps or reverts low ones by the metrics decision rule against outcome O1 and its guardrails, cards high and protected ones to the user, and never touches its protected set.

**Architecture:** Python modules `board/improve*.py` (one CLI `board/improve.py`, wrapped by `tmux-ctl improve` through `tools/lib/improve.zsh`) own the `proposals` table in the engine's SQLite database and write one engine event per state change. Comparisons go through a new pure function in `board/metrics.py` (`compare_halves`) that reuses the decision rule's permutation test and quality-veto formula. The Node engine (built by `2026-11-10-pcee-engine-design.md` parts 1 and 2) gains small hooks: trial overlays in the briefs it writes, `variants` in `metrics start`, a merge entry for `improve/<id>` branches that refuses protected paths, a default hold for protected paths, an `improve` schedule row, and a `schedule` inbox row after each morning report. Discord cards go through the existing outbox file contract, and clicks go through `board/discord_controls.py`.

**Tech Stack:** Python 3.9+ (`sqlite3`, `hashlib`, `fnmatch`, `subprocess`), Node >= 22.13 (`engine/`, `node:test`), zsh (`bin/tmux-ctl`, `tools/lib/improve.zsh`), git (`apply`, `revert`, `worktree`).

**Spec:** docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md",
 "base": "0af42b5b388826b46ecd25063192c9d2f558f87d",
 "refreshed_from": {"base": "878263ef370347c6be0e8911c42ef5a69911b9ff",
                    "stale_paths": ["bin/tmux-ctl", "board/discord_feed.py", "board/metrics.py", "docs/superpowers/engine.json",
                                    "docs/superpowers/metrics/runs.jsonl", "docs/superpowers/metrics/tasks.jsonl",
                                    "docs/superpowers/specs/2026-11-10-pcee-engine-design.md", "engine/bin/engine.js"]},
 "depends_on": [
   {"spec": "docs/superpowers/specs/2026-11-10-pcee-engine-design.md", "kind": "hard",
    "interface": "engine DB events/inbox (§1, §12), engine-run specs and briefs (§3 step 2), merge step and steps/Engine-Step (§3.7, §10.4), morning report (§7), approval holds (§13), schedules (§14), tmux-ctl engine (§5)"},
   {"spec": "docs/superpowers/specs/2026-11-10-queue-metrics-design.md", "kind": "soft", "interface": "run log, configurations, decision rule §5"},
   {"spec": "docs/superpowers/specs/2026-11-12-execution-analytics-design.md", "kind": "soft", "interface": "per-task records (tasks.jsonl)"}],
 "writes": [
   {"path": "docs/superpowers/notes/2026-11-21-improve-engine-interfaces.md", "mode": "create"},
   {"path": "docs/superpowers/outcomes/O1.json", "mode": "create"},
   {"path": "docs/superpowers/improve/protected.txt", "mode": "create"},
   {"path": "board/improve.py", "mode": "create"},
   {"path": "board/improve_class.py", "mode": "create"},
   {"path": "board/improve_store.py", "mode": "create"},
   {"path": "board/improve_adapters.py", "mode": "create"},
   {"path": "board/improve_trials.py", "mode": "create"},
   {"path": "board/improve_eval.py", "mode": "create"},
   {"path": "board/improve_pick.py", "mode": "create"},
   {"path": "board/improve_apply.py", "mode": "create"},
   {"path": "board/improve_discord.py", "mode": "create"},
   {"path": "claude/improve-rank.md", "mode": "create"},
   {"path": "tools/lib/improve.zsh", "mode": "create"},
   {"path": "bin/tmux-ctl", "mode": "modify"},
   {"path": "board/metrics.py", "mode": "modify"},
   {"path": "board/discord_controls.py", "mode": "modify"},
   {"path": "board/tests/improve_fixtures.py", "mode": "create"},
   {"path": "board/tests/test_improve_class.py", "mode": "create"},
   {"path": "board/tests/test_improve_store.py", "mode": "create"},
   {"path": "board/tests/test_improve_adapters.py", "mode": "create"},
   {"path": "board/tests/test_improve_trials.py", "mode": "create"},
   {"path": "board/tests/test_metrics_halves.py", "mode": "create"},
   {"path": "board/tests/test_improve_eval.py", "mode": "create"},
   {"path": "board/tests/test_improve_pick.py", "mode": "create"},
   {"path": "board/tests/test_improve_apply.py", "mode": "create"},
   {"path": "board/tests/test_improve_discord.py", "mode": "create"},
   {"path": "board/tests/test_improve_isolation.py", "mode": "create"},
   {"path": "tools/tests/test_ctl_improve.zsh", "mode": "create"},
   {"path": "engine/lib/improve.js", "mode": "create"},
   {"path": "engine/test/improve.test.js", "mode": "create"},
   {"path": "engine/test/improve_merge.test.js", "mode": "create"},
   {"path": "engine/test/improve_holds.test.js", "mode": "create"},
   {"path": "engine/lib/engine/core.js", "mode": "modify"},
   {"path": "engine/lib/engine/integrate.js", "mode": "modify"},
   {"path": "engine/lib/engine/cli.js", "mode": "modify"},
   {"path": "engine/lib/engine/rebuild.js", "mode": "modify"},
   {"path": "engine/lib/engine/queue_report.js", "mode": "modify"},
   {"path": "README.md", "mode": "modify"}],
 "reads": ["docs/superpowers/specs/2026-11-10-pcee-engine-design.md",
           "engine/bin/engine.js", "engine/bin/hold.js", "claude/hooks/engine-hold.sh", "docs/superpowers/engine.json",
           "engine/lib/engine/db.js", "engine/lib/engine/steps.js", "engine/lib/engine/paths.js", "engine/lib/engine/architect.js",
           "board/tests/test_metrics_weekly.py",
           "docs/superpowers/model-routing.json", "docs/superpowers/metrics/runs.jsonl", "docs/superpowers/metrics/tasks.jsonl",
           "docs/superpowers/metrics/configs/upfront-seq.md", "board/dream_paths.py", "board/dream_check.py",
           "board/findings.py", "board/scout_post.py", "board/scout_decisions.py", "board/discover_post.py",
           "board/dream_discord.py", "board/discord_feed.py", "board/ideas.py", "board/tc_env.py", "board/scout_eval.py",
           "claude/plugin/hooks/hooks.json"],
 "produces": ["tmux-ctl improve outcome|list|show|propose|revert|tick|variants|click", "proposals table in the engine DB",
              "run record field variants", "metrics.compare_halves", "engine merge entry for improve/<id> branches"],
 "consumes": ["engine events table (§1)", "engine inbox source schedule (§12, §14)", "engine brief builder (§3 step 2)",
              "engine merge step + steps kind merge + Engine-Step trailer (§3.7, §10.4)", "engine morning report writer (§7)",
              "engine.json holds + hold.js (§13)", "engine schedule add + engine wake (§14)", "tmux-ctl engine (§5)",
              "tmux-ctl metrics start|record|report", "metrics decision rule (queue-metrics §5)",
              "dream out/report.json", "findings core (scout drafts.json, discover state)", "task-observer skill-updates"],
 "tests": ["board/tests/test_improve_class.py", "board/tests/test_improve_store.py", "board/tests/test_improve_adapters.py",
           "board/tests/test_improve_trials.py", "board/tests/test_metrics_halves.py", "board/tests/test_improve_eval.py",
           "board/tests/test_improve_pick.py", "board/tests/test_improve_apply.py", "board/tests/test_improve_discord.py",
           "board/tests/test_improve_isolation.py", "tools/tests/test_ctl_improve.zsh", "engine/test/improve.test.js",
           "engine/test/improve_merge.test.js", "engine/test/improve_holds.test.js"]}
```

## Global Constraints

- **Engine parts 1 and 2 are on `main`** (merged as 064a029; refreshed onto main 0af42b5 on 2026-11-24). The CLI is
  `engine/bin/engine.js` → `engine/lib/engine/cli.js` (subcommands `run status events resume signal rebuild enqueue start
  done`, `cli.js:22`), and `bin/tmux-ctl` wraps it as `tmux-ctl engine` (`engine)` case, line ~796; it works outside
  tmux). Engine §13 (approval holds) and §14 (schedules) are **not** on main: there is no `engine/bin/hold.js`, no
  `claude/hooks/engine-hold.sh`, no `holds` key in `docs/superpowers/engine.json` (it holds only `test` and `test_ok`),
  no `schedule` inbox source and no `schedule`/`wake` subcommand. Task 1 confirms each interface on `main` before anything
  is built and stops the plan if one is missing. The engine files the later tasks are expected to change (from main
  0af42b5; Task 1's note confirms or corrects them) are in the manifest's `writes` as `modify`: `engine/lib/engine/core.js`
  (brief builder `briefFor` ~955, tier-to-model map ~151, `metrics start` call ~1121, queue report step ~1234),
  `engine/lib/engine/integrate.js` (merge ~83, revert ~216, `metrics record` argv ~158), `engine/lib/engine/cli.js`,
  `engine/lib/engine/rebuild.js` and `engine/lib/engine/queue_report.js`.
- **Protected set** (spec §6), the exact content of `docs/superpowers/improve/protected.txt`, one glob per line:
  ```
  board/metrics.py
  docs/superpowers/metrics/**
  docs/superpowers/outcomes/**
  docs/superpowers/improve/**
  claude/orchestrator.md
  claude/worker.md
  claude/plugin/hooks/**
  claude/plugin/mods/**
  .claude/settings*.json
  ~/.claude/settings*.json
  board/improve*.py
  tools/lib/improve.zsh
  bin/tmux-ctl#improve
  ```
  `bin/tmux-ctl#improve` means a patch hunk on `bin/tmux-ctl` that touches lines between the `  improve)` case label and
  its `;;`. Glob match: `fnmatch` on the repo-relative path, and `**` matches across `/`. A `~/` glob is matched after
  `os.path.expanduser` against the absolute target.
- **Classes** (spec §3), in this order: target protected → `protected`; kind `permission` → `protected`; kind `memory` →
  `observation`; kind `procedure` with a prose-only patch → `low`; else `high`. A *prose-only patch* is one where every
  added or removed line (`+`/`-`, not `+++`/`---`) is outside a code fence (tracked over the hunk context and the target
  file), is not inside a leading `---` frontmatter block, and does not start with `$ `, `    ` (indented code), `` ` ``
  or `tmux-ctl `. A null patch is never prose-only.
- **Proposal states** and the only allowed transitions:
  `proposed→trial|rejected|drafted`, `trial→kept|reverted|awaiting_you`, `awaiting_you→promoted|rejected|trial` (extend),
  `kept→reverted`, `promoted→reverted`, `drafted→rejected|promoted`. Any other transition raises `ImproveError`.
- **Events:** every proposal state change is one row in the engine's `events` table (kind `improve`, spec null, detail
  `{"proposal": id, "from": old, "to": new, "reason": …, "row": <the full new row>}`), in the same transaction as the
  `proposals` update. The row values let a replay rebuild the table (engine §1, §10.6).
- **R1, deterministic evidence:** each `evidence` item is `{"type": "run"|"task"|"event"|"ledger"|"report"|"hook", "ref": …}`.
  A proposal with no evidence item (or only `{"type": "note"}` items) is refused with `no deterministic evidence`. A dream
  or observer proposal cites its report file or run id, and its class is capped at `high` (it is never `low`).
- **Trial split** (spec §4): a spec is in proposal P's trial half when `int(sha256((spec_id + P).encode()).hexdigest(), 16) % 2 == 0`.
  `spec_id` is the metrics spec id (spec path, with `#part-N` when present).
- **Metric definitions (defined once; every task cites these):**
  - *trial half* of P: the latest run records (by `last_runs`) with `P` in `variants`. *Control half* of P: the run records
    of engine-run specs since P entered `trial`, whose spec is in P's control half by the split. Lead-run specs are in
    neither half. *Engine-run record*: at main 0af42b5 run records carry no `runner` field (the engine keeps `runner` on
    its own `specs` row, `engine/lib/engine/db.js:9`); a record is engine-run when its `budget` field is non-null, which
    only the engine's `metrics record --budget … --engine-jobs …` call sets (`engine/lib/engine/integrate.js:158`). Task 1
    row 6 confirms this or names the field to use instead.
  - `tokens_per_merged_task` (O1 signal, R4): `sum(tokens.total over every spec in the half, failed and abandoned
    included) / sum(tasks over specs with outcome merged or mr)`. Infinite (worse) when the denominator is 0.
  - `failed_specs`: count of specs with outcome `failed`. `red_after_merge`: count of specs whose run record has
    `red_after_merge` true (the field Task 5 adds). `final_review_crit_imp_per_spec`: sum of `final_review_crit_imp`
    (Task 5) / spec count. E1 extras: `fix_rounds_per_task` = sum `fix_rounds` / sum `tasks`; `bounces_per_task` = sum
    `bounces` / sum `tasks`.
  - **Verdict of `compare_halves`** for a ratio metric: `too early` when either half has fewer than 4 specs; else index =
    trial value / control value, a one-sided permutation p (`metrics.permutation_p` on per-spec log values of merged specs)
    toward "better" and one toward "worse"; `better` when index < 1 and p_better < 0.10; `worse` when index > 1 and
    (p_worse < 0.10 or the trial denominator is 0); else `equal`. For a count guardrail: `worse` when trial count > control
    rate × trial spec count + 1 (the `quality_veto` formula), else `equal`.
  - **Spend cap** (R4): `2 × mean(tokens.total of the control half) × trial_len`, where `trial_len` starts at 5 and grows by
    5 per Extend. With no control spec yet, no cap applies.
- **Tick decisions** (spec §2, error handling): P in `trial` with ≥ `trial_len` trial specs is evaluated. Low: signal
  `better|equal` and no guardrail `worse` → `kept`; signal or guardrail `worse` → `reverted`; signal `too early` →
  continue, unless the trial has ≥ 15 trial specs, then `reverted` with `no signal`. High: the same comparison, then
  `awaiting_you` (a `worse` result is still carded, with its numbers). A trial spec whose events carry a `ruling` or a
  review finding whose text contains `Trial <P>` → `reverted` at once (`variant blamed: <event id>`). Trial tokens over the
  spend cap → `reverted` (`over budget`).
- **Discord:** a card only per `awaiting_you`, per `drafted`, per guardrail breach, per `achieved`, and one weekly digest
  line `🧪 improve: <n> trials, <k> kept, <r> reverted, <a> awaiting you; O1 <value> vs target`. Nothing else is posted.
  Button custom ids: `ab:improve:<act>:<project>:<id>`, act in `promote|reject|extend|approve|revert`.
- **Writes to `main`** happen only through the engine's merge entry (Task 10). The loop never runs `git commit` on the
  main checkout itself.
- **Isolation in tests:** `TC_ENGINE_DIR`, `TC_STATE`, `HOME`-free state paths, and a scratch clone for every test that
  commits; a scratch tmux server only with `-f /dev/null`. No test opens `~/.local/state/agent-board/engine/` or the real
  `runs.jsonl` (Task 14 checks).
- **Zsh gotchas** (CLAUDE.md): never name a variable `path`; quote `=name` tmux targets; brace variables before `:`.
- **Commits:** conventional commits with scope (`feat(improve): …`, `feat(metrics): …`, `feat(engine): …`); end each
  commit message with the attribution trailer your harness specifies. Stage only your own paths (`git add <paths>`).

**User decisions (already made):** the spec's Decisions block (2026-11-16) and revisions R1–R5, E1, E5 (2026-11-20):
one spec queued last; first outcome O1 as written in spec §1; low changes kept or reverted automatically, skills, rules,
prompts and routing promoted only by the user, permissions and protected files never trialled; evidence from real work
only; protected set as §6; start quiet; Claude Code stays the runtime.

**Assumptions / known risk:** as queued, this plan will stop at Task 1 unless stage 7 (engine §13 approval holds and §14 schedules) lands first: the engine spec's 2026-11-19 revision, decision 5, moved both to stage 7. Lead ruling 2026-11-21: keep the stop, no fallbacks. Refresh 2026-11-24: engine parts 1 and 2 are now on main, but §13 and §14 are still absent at main 0af42b5 (see Global Constraints), so Task 1 rows 3 (the `schedule` source), 10 and 11 are expected to come out `MISSING` and the stop still applies.

**Assumptions (refresh 2026-11-24, refresh agent):**
- The loop's spend cap (R4) is separate from the engine's per-spec budget (engine §8b: attempts 60, tokens 5,000,000 by
  default, a `budget` wait when reached). A trial spec parked on `budget` stays a trial spec, and its tokens count in its
  half as recorded. A `ruling` event answering a `budget` wait (engine §8a: detail keys `kind`, `recommended`, `answer`,
  `followed`) is not a "variant blamed" ruling unless its text contains `Trial <P>`.
- `docs/superpowers/notes/2026-11-21-improve-engine-interfaces.md` (Task 1's first run, before the engine landed) is
  superseded: Task 1 re-runs against main and rewrites it.

**Rulings made while planning (planner, for the lead to confirm):**
- Ruling: engine §13 (approval holds) and §14 (schedules) are marked "moved to stage 7" in the engine spec's 2026-11-19
  revision, so parts 1 and 2 may not provide them. Task 1 treats them as required interfaces like the others: missing →
  the plan stops, as a failure for the lead. Cost if wrong: the spec waits for stage 7. (Sent to the lead while planning.)
- Ruling: the loop's code is split over `board/improve*.py` modules, so the protected glob is `board/improve*.py` (it
  covers the spec's `board/improve.py`). Cost if wrong: none; the set only grows.
- Ruling: memory consolidation's report proposals carry text, not a patch, and `dream_check` allows only kinds `idea` and
  `observer`. The dream adapter therefore inserts `observer` items as kind `procedure` with a null patch (never picked
  for a trial) and `idea` items as kind `spec`, state `drafted` (no branch). `tmux-ctl improve propose --from-dream
  <run>:<index> --patch <file> --target <path>` turns one real report proposal into a patched proposal, with source
  `dream` and the report as evidence. The user gate uses that path. Cost if wrong: a later dream change that emits patches
  needs one more adapter branch.
- Ruling: no source writes deterministic usage records for skills or memory entries yet, so no adapter emits `retire`
  (R5). `retire` proposals come from `improve propose --kind retire`, and the cap of 5 per tick applies to every retire
  insert. Cost if wrong: retire stays manual until a usage record exists.
- Ruling: the loop adds no hook that can block a Stop, so R3 has nothing to bind. Task 11 asserts that no `improve` entry
  is registered for `Stop` in `claude/plugin/hooks/hooks.json` and that the R3 rule is in `board/improve.py`'s docstring
  for any later gate. Cost if wrong: a later Stop gate must add the once-only test then.
- Ruling: the spend cap (R4) is checked by the tick after each trial spec's record, not inside a running spec. "Would
  cross it" becomes "has crossed it at the tick". Cost if wrong: at most one spec of overspend per trial.
- Ruling: the ranking step (spec §2.4) calls `claude -p` on the mechanical tier's model from
  `docs/superpowers/model-routing.json` (`haiku`, effort `low`), the way `board/scout_eval.py` calls the model
  (`TC_IMPROVE_CLAUDE` overrides the binary for tests), and caps output with a prompt rule plus a check that the reply is at
  most 2,000 tokens (`usage.output_tokens`). Cost if wrong: one argv to change.

---

### Task 1: Confirm the engine interfaces on main

**Goal:** A note on `main`'s real engine shows, for each engine interface this plan consumes, where it lives (file:line) and that it behaves as the plan assumes. If one is missing, the plan stops here as a failure for the lead.

**Files:**
- Create: `docs/superpowers/notes/2026-11-21-improve-engine-interfaces.md`

**Acceptance Criteria:**
- [ ] The note has a table `| Interface | Engine spec § | Where on main (file:line) | Check run | Result |` with exactly these 12 rows, each `present` or `MISSING`:
  1. engine DB path and `TC_ENGINE_DIR` override, `events` table columns (time, spec, job, kind, detail) — §1
  2. `engine rebuild --check` result after a scratch `proposals` table and one `improve` event are added to a scratch DB (does it ignore an unknown table, or does it need a registration?) — §10.6
  3. `inbox` table and the `schedule` source (`source_id` `<name>@<due_at>`) — §12
  4. the brief builder for an engine-run spec's jobs (function and file) and the worktree workspace `<worktree>/.superpowers/engine/` — §1, §3 step 2
  5. the tier-to-model map the engine uses for a spec's jobs (where it is read from `model-routing.json`) — §2
  6. `metrics start` / `metrics record` calls from the engine (argv) and how a run record is told to be engine-run (a `runner` field, or the non-null `budget` that the engine's `--budget` sets) — §3 step 7, §7
  7. the merge step: `steps` kind `merge`, `Engine-Step: <key>` trailer, live-checkout check — §3 step 7, §10.4
  8. the morning report writer (file, and the point after the report is committed) — §7
  9. the event forms for an architect `ruling`, a review finding, and "tests red after the merge" (the exact `kind` and `detail` keys) — §3, §4
  10. `engine.json` key `holds`, the default hold list, and `engine/bin/hold.js` + `claude/hooks/engine-hold.sh` — §13
  11. `tmux-ctl engine schedule add|list|rm|run-now` and `engine wake` — §14
  12. `tmux-ctl engine` wrapper in `bin/tmux-ctl` running `node engine/bin/engine.js` — §5
- [ ] Each `present` row cites a real `file:line` and the command run to check it, with its output line.
- [ ] Row 2 names which way Task 3 must go: `ignored` (the loop's table needs nothing) or `needs registration` (Task 3 adds the `proposals` table to the replay in the file named).
- [ ] The note ends with a section `## Files the later tasks change`: for each of Tasks 3, 5, 7, 10 and 11, the engine files it will modify, from what was found.
- [ ] If any row is `MISSING`: commit the note, mark this task `failed — engine interface missing: <row names>`, and message the lead. Do not start Task 2.
- [ ] The note is rewritten whole: the 2026-11-21 version (all `MISSING`, written before the engine landed) is superseded. Starting points found at main 0af42b5 (check each, do not copy): DB path `engine/lib/engine/paths.js:7`; tables `engine/lib/engine/db.js:9-23` (`events(seq, ts, spec, job, kind, detail)`, `inbox(... source, source_id ... UNIQUE(source, source_id))`, `steps`); replay `engine/lib/engine/rebuild.js`; brief builder `briefFor`, `engine/lib/engine/core.js:955`; routing map `core.js:151`; `metrics start` `core.js:1121`, `metrics record` `engine/lib/engine/integrate.js:158`; merge and `Engine-Step` `integrate.js:83`, `engine/lib/engine/steps.js:74`; queue report step `core.js:1234`, `engine/lib/engine/queue_report.js`; `ruling` events `core.js:772`, `engine/lib/engine/architect.js:62`; tests red after the merge `architect.js:6` (case `tests_red_after_merge`); wrapper `bin/tmux-ctl` `engine)` ~796. Not found at 0af42b5: `holds`, `hold.js`, `engine-hold.sh`, a `schedule` source, `schedule`/`wake` subcommands.

**Verify:** `grep -c '^| [0-9]' docs/superpowers/notes/2026-11-21-improve-engine-interfaces.md; grep -c 'MISSING' docs/superpowers/notes/2026-11-21-improve-engine-interfaces.md` → `12` then `0`

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-21-improve-engine-interfaces.md"], "verifyCommand": "grep -c '^| [0-9]' docs/superpowers/notes/2026-11-21-improve-engine-interfaces.md; grep -c 'MISSING' docs/superpowers/notes/2026-11-21-improve-engine-interfaces.md", "acceptanceCriteria": ["12-row interface table, each present or MISSING", "each present row cites file:line and a check command with output", "row 2 decides ignored vs needs registration", "section listing engine files each later task changes", "any MISSING: commit the note, fail the task, message the lead, stop", "note rewritten whole against main; the 2026-11-21 version superseded"], "modelTier": "standard"}
```

---

### Task 2: Outcome O1, the protected set and class derivation

**Goal:** `docs/superpowers/outcomes/O1.json` and `docs/superpowers/improve/protected.txt` exist with the spec's content, and `board/improve_class.py` derives a proposal's class from its kind, target and patch.

**Files:**
- Create: `docs/superpowers/outcomes/O1.json`, `docs/superpowers/improve/protected.txt`, `board/improve_class.py`, `board/tests/test_improve_class.py`

**Acceptance Criteria:**
- [ ] `O1.json` is byte-for-byte the spec §1 JSON (pretty-printed as in the spec, trailing newline).
- [ ] `protected.txt` is exactly the 13 lines of Global Constraints.
- [ ] `is_protected(target, patch=None)` is true for each glob's example, for `~/.claude/settings.json`, and for a `bin/tmux-ctl` patch whose hunk lies inside the `improve)` case, but false for a `bin/tmux-ctl` hunk elsewhere and for `docs/superpowers/model-routing.json`.
- [ ] `derive(kind, target, patch_text)` returns each class of the Global Constraints order. Tests cover every kind (`memory procedure skill rule prompt routing permission spec retire`) and the prose-only rule: a fenced block line, a frontmatter line, a `$ ` command line, or an indented code line in a procedure patch each make it `high`.
- [ ] `derive(..., source="dream"|"observer")` never returns `low` (R1 cap).

**Verify:** `python3 -m unittest board.tests.test_improve_class -v` → `OK`

**Steps:**

- [ ] **Step 1: Write the two data files.** `O1.json`:

```json
{"id": "O1",
 "statement": "Cheaper specs, quality held",
 "signal": {"metric": "tokens_per_task", "source": "metrics", "compare": "trial_vs_baseline"},
 "completion": {"change": -0.25, "min_queues": 2},
 "guardrails": [
   {"metric": "failed_specs", "rule": "not_worse"},
   {"metric": "red_after_merge", "rule": "not_worse"},
   {"metric": "final_review_crit_imp_per_spec", "rule": "not_worse"}],
 "state": "active"}
```

`protected.txt`: the 13 lines of Global Constraints, in that order.

- [ ] **Step 2: Write the failing tests** `board/tests/test_improve_class.py` (each names its mutation):

```python
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import improve_class as C  # noqa: E402

PROSE = """--- a/claude/skills/x/SKILL.md
+++ b/claude/skills/x/SKILL.md
@@ -3,3 +3,3 @@
 ## Procedure
-Read the plan first.
+Read the plan and its spec first.
 More prose.
"""
FENCE = PROSE.replace(" More prose.\n", " ```\n+echo hi\n ```\n")
FRONT = """--- a/s/SKILL.md
+++ b/s/SKILL.md
@@ -1,3 +1,3 @@
 ---
-name: old
+name: new
 ---
"""
CMD = PROSE.replace("+Read the plan and its spec first.", "+$ tmux-ctl run tests")


class T(unittest.TestCase):
    def test_protected_globs(self):  # mutation: return False in is_protected -> fails
        for t in ["board/metrics.py", "docs/superpowers/metrics/configs/a.md", "docs/superpowers/outcomes/O1.json",
                  "docs/superpowers/improve/protected.txt", "claude/orchestrator.md", "claude/worker.md",
                  "claude/plugin/hooks/hooks.json", "claude/plugin/mods/x.js", ".claude/settings.local.json",
                  "board/improve.py", "board/improve_eval.py", "tools/lib/improve.zsh"]:
            self.assertTrue(C.is_protected(t), t)
        self.assertFalse(C.is_protected("docs/superpowers/model-routing.json"))
        self.assertFalse(C.is_protected("claude/skills/x/SKILL.md"))

    def test_home_settings(self):  # mutation: drop expanduser -> fails
        self.assertTrue(C.is_protected(str(Path.home() / ".claude/settings.json")))

    def test_tmux_ctl_improve_section(self):  # mutation: treat every bin/tmux-ctl hunk alike -> one assert fails
        src = "a)\n  x ;;\n  improve)\n    exec y ;;\n  z)\n"
        inside = "--- a/bin/tmux-ctl\n+++ b/bin/tmux-ctl\n@@ -4,1 +4,1 @@\n-    exec y ;;\n+    exec w ;;\n"
        outside = "--- a/bin/tmux-ctl\n+++ b/bin/tmux-ctl\n@@ -2,1 +2,1 @@\n-  x ;;\n+  q ;;\n"
        self.assertTrue(C.is_protected("bin/tmux-ctl", inside, src))
        self.assertFalse(C.is_protected("bin/tmux-ctl", outside, src))

    def test_order(self):
        self.assertEqual(C.derive("procedure", "board/metrics.py", PROSE), "protected")   # target first
        self.assertEqual(C.derive("permission", "claude/skills/x/SKILL.md", PROSE), "protected")
        self.assertEqual(C.derive("memory", "claude/skills/x/SKILL.md", None), "observation")
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", PROSE), "low")
        for k in ["skill", "rule", "prompt", "routing", "spec", "retire"]:
            self.assertEqual(C.derive(k, "claude/skills/x/SKILL.md", PROSE), "high", k)

    def test_prose_only(self):  # mutation: prose_only returns True -> fails
        for p in [FENCE, FRONT, CMD, None]:
            self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", p), "high")

    def test_dream_never_low(self):  # mutation: ignore source -> fails
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", PROSE, source="dream"), "high")
        self.assertEqual(C.derive("procedure", "claude/skills/x/SKILL.md", PROSE, source="observer"), "high")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run, expect FAIL** (`ModuleNotFoundError: improve_class`): `python3 -m unittest board.tests.test_improve_class -v`

- [ ] **Step 4: Write `board/improve_class.py`:**

```python
"""improve_class: the protected set and class derivation of the supervised improvement loop (spec §3, §6).
Test: tests/test_improve_class.py."""
import fnmatch
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROTECTED = REPO / "docs" / "superpowers" / "improve" / "protected.txt"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? ")


def globs():
    return [g.strip() for g in PROTECTED.read_text().splitlines() if g.strip() and not g.startswith("#")]


def _match(target, glob):
    if glob.startswith("~/"):
        return fnmatch.fnmatchcase(os.path.expanduser(target), os.path.expanduser(glob))
    return fnmatch.fnmatchcase(target, glob)   # fnmatch's * already crosses "/", so ** works too


def _improve_range(src):
    lines = src.splitlines()
    try:
        lo = next(i for i, l in enumerate(lines, 1) if l.strip() == "improve)")
    except StopIteration:
        return None
    hi = next((i for i, l in enumerate(lines[lo - 1:], lo) if l.rstrip().endswith(";;")), len(lines))
    return lo, hi


def _hunks(patch):
    for line in (patch or "").splitlines():
        m = HUNK.match(line)
        if m:
            start, n = int(m.group(1)), int(m.group(2) or 1)
            yield start, start + max(n, 1) - 1


def is_protected(target, patch=None, tmux_ctl_src=None):
    for g in globs():
        if "#" in g:
            path_part, section = g.split("#", 1)
            if target != path_part or section != "improve":
                continue
            src = tmux_ctl_src if tmux_ctl_src is not None else (REPO / path_part).read_text()
            rng = _improve_range(src)
            if patch is None or (rng and any(a <= rng[1] and b >= rng[0] for a, b in _hunks(patch))):
                return True
        elif _match(target, g):
            return True
    return False


def prose_only(patch):
    if not patch:
        return False
    fence = front = False
    first = True
    for line in patch.splitlines():
        if line.startswith(("+++", "---", "@@")):
            if line.startswith("@@"):
                first = True
            continue
        body = line[1:] if line[:1] in "+- " else line
        if first and body.strip() == "---":
            front = True
            first = False
            if line[:1] in "+-":
                return False
            continue
        first = False
        if front:
            if body.strip() == "---":
                front = False
            if line[:1] in "+-":
                return False
            continue
        if body.lstrip().startswith("```"):
            if line[:1] in "+-":
                return False
            fence = not fence
            continue
        if line[:1] in "+-":
            if fence or body.startswith(("$ ", "    ", "`", "tmux-ctl ")):
                return False
    return True


def derive(kind, target, patch, source=None, tmux_ctl_src=None):
    if target and is_protected(target, patch, tmux_ctl_src):
        return "protected"
    if kind == "permission":
        return "protected"
    if kind == "memory":
        return "observation"
    if kind == "procedure" and prose_only(patch) and source not in ("dream", "observer"):
        return "low"
    return "high"
```

Note on `prose_only`: `first` tracks "first body line of a hunk", so a hunk that starts at line 1 with `---` is read as frontmatter. The FRONT test hits this path.

- [ ] **Step 5: Run, expect PASS.** Then **commit** `feat(improve): outcome O1, protected set, class derivation`.

```json:metadata
{"files": ["docs/superpowers/outcomes/O1.json", "docs/superpowers/improve/protected.txt", "board/improve_class.py", "board/tests/test_improve_class.py"], "verifyCommand": "python3 -m unittest board.tests.test_improve_class -v", "acceptanceCriteria": ["O1.json equals the spec section 1 JSON", "protected.txt has the 13 lines", "is_protected: globs, ~/ settings, tmux-ctl improve section only", "derive: class order and prose-only rule (fence, frontmatter, command, indented code -> high)", "dream/observer never low"], "modelTier": "mechanical"}
```

---

### Task 3: The proposals store, events and `tmux-ctl improve` (list, show, propose)

**Goal:** `board/improve_store.py` keeps the `proposals` table in the engine database with one `improve` event per state change, and `tmux-ctl improve list|show|propose|outcome status` works through `tools/lib/improve.zsh` and `board/improve.py`.

**Files:**
- Create: `board/improve_store.py`, `board/improve.py`, `tools/lib/improve.zsh`, `board/tests/improve_fixtures.py`, `board/tests/test_improve_store.py`, `tools/tests/test_ctl_improve.zsh`
- Modify: `bin/tmux-ctl` (new `improve)` case after `engine)` (~796) and before `metrics)` (~853)), and the engine replay file (`engine/lib/engine/rebuild.js` at main 0af42b5, or the file Task 1's note names) when row 2 says `needs registration`. The help line is Task 13's.

**Acceptance Criteria:**
- [ ] DB path: `${TC_ENGINE_DIR:-~/.local/state/agent-board/engine}/<project>.sqlite`, `<project>` from `tc_env` as the rest of `board/` does. `CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, source, kind, target, patch, evidence, class, state, outcome, created_at, updated_at, trial_started_at, trial_len INTEGER DEFAULT 5, commit_sha, dedupe_key TEXT UNIQUE, title, shrinks_reads INTEGER DEFAULT 0, reason)`. The loop never creates the engine's own tables. With no `events` table (no engine DB yet), the store refuses with `improve: no engine database at <path>` and exit 1.
- [ ] `insert(...)` assigns `P<n>` (n = 1 + max existing), derives the class (Task 2), refuses with `no deterministic evidence` per R1, and is a no-op returning the existing id when `dedupe_key = sha256(source + "\0" + target + "\0" + sha256(patch or ""))` exists. It refuses a 6th `retire` insert in one tick (`retire cap`).
- [ ] `transition(id, to, reason)` enforces the Global Constraints transitions (else `ImproveError`), updates the row and appends one `events` row (kind `improve`, detail as Global Constraints) in one transaction. Test: kill the transaction midway (raise after the UPDATE) → neither row changed nor event written. Mutation: commit after the UPDATE → test fails.
- [ ] Every proposal patch file is stored under `${TC_STATE}/improve/<project>/patches/<id>.diff`.
- [ ] `tmux-ctl improve propose --kind K --target T --patch F [--outcome O1] [--evidence JSON] [--shrinks-reads] [--from-dream <run>:<index>]` prints the id. `--from-dream` sets source `dream`, reads the report at `dream_paths.run_dir(project, run)/out/report.json`, and adds `{"type": "report", "ref": "<path>#proposals[<index>]"}` to the evidence.
- [ ] `tmux-ctl improve list [--state S]` prints one line per proposal `P<n> <state> <class> <kind> <target>`. `improve show <id>` prints the row, the patch, the evidence, the trial numbers (if any) and the commit.
- [ ] `tmux-ctl improve outcome status [<id>]` prints for each active outcome: the current value of its signal vs the baseline configuration (`tokens_per_merged_task` of engine-run records since the outcome file's first commit vs records of configs flagged `"baseline": true`), each guardrail's verdict (Global Constraints), and the overall verdict. Before Task 8 lands, this may print `too early`.
- [ ] If Task 1's row 2 says `needs registration`, the engine's replay rebuilds `proposals` from `improve` events, and `engine rebuild --check` exits 0 after a scratch insert + 3 transitions.
- [ ] `tools/tests/test_ctl_improve.zsh` runs `tmux-ctl improve propose`, `list` and `show` against a temp `TC_ENGINE_DIR` with a fixture engine DB, and prints `ok`/`FAIL` lines.

**Verify:** `python3 -m unittest board.tests.test_improve_store -v && zsh tools/tests/test_ctl_improve.zsh` → `OK`, then no `FAIL` line

**Steps:**

- [ ] **Step 1:** `board/tests/improve_fixtures.py`: `engine_db(tmp)` creates `<tmp>/<project>.sqlite` with the engine's real `events` columns, `events(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, spec TEXT, job TEXT, kind TEXT, detail TEXT)` at main 0af42b5 (`engine/lib/engine/db.js:16`; Task 1's note row 1 confirms). The store writes `ts` as epoch seconds, as the engine does. Add `run(spec, **kw)` (a run record dict with `kind: "run"`, `outcome`, `tasks`, `tokens: {"total": …}`, `variants`, `runner`, `batch`, `ended_at`) and `write_log(tmp, lines)` for later tasks.
- [ ] **Step 2:** RED tests for every criterion above (store and CLI), each naming its mutation.
- [ ] **Step 3:** Implement `improve_store.py` (sqlite3, `BEGIN IMMEDIATE` per change, `detail` JSON), `improve.py` (argparse subcommands, one-line errors `improve: <sub>: <reason>` to stderr, exit 1), `tools/lib/improve.zsh` (`exec python3 -I "$root/board/improve.py" "$@"`), and the `bin/tmux-ctl` case:

```zsh
  improve)
    source "${0:A:h:h}/tools/lib/improve.zsh"; improve_main "${0:A:h:h}" "$@" ;;
```

  and `tools/lib/improve.zsh`:

```zsh
# improve: the supervised improvement loop's tmux-ctl entry (spec 2026-11-16 §5). Protected (docs/superpowers/improve/protected.txt).
improve_main() {
  local root=$1; shift
  exec python3 -I "$root/board/improve.py" "$@"
}
```

  and the case passes the root: `source "${0:A:h:h}/tools/lib/improve.zsh"; improve_main "${0:A:h:h}" "$@" ;;`. Inside a zsh function `$0` is the function's name, so the root is passed as an argument, not read from `$0` there (the same reason `discord)` at line ~318 sources with `${0:A:h:h}` at the case level).
- [ ] **Step 4:** GREEN; **commit** `feat(improve): proposals store, events and the improve CLI`.

```json:metadata
{"files": ["board/improve_store.py", "board/improve.py", "tools/lib/improve.zsh", "bin/tmux-ctl", "engine/lib/engine/rebuild.js", "board/tests/improve_fixtures.py", "board/tests/test_improve_store.py", "tools/tests/test_ctl_improve.zsh"], "verifyCommand": "python3 -m unittest board.tests.test_improve_store -v && zsh tools/tests/test_ctl_improve.zsh", "acceptanceCriteria": ["proposals table in the engine DB; refuses without one", "insert: P<n>, derived class, R1 refusal, dedupe key no-op, retire cap 5 per tick", "transition: allowed set only, one improve event in the same transaction, atomic", "patches under TC_STATE/improve/<project>/patches", "propose incl. --from-dream with report evidence", "list and show", "outcome status prints value vs baseline, guardrails, verdict", "replay registration when Task 1 row 2 says so; rebuild --check 0", "zsh CLI test ok"], "modelTier": "standard"}
```

---

### Task 4: Adapters: dream, discovery, scout, observer

**Goal:** At the start of each tick `improve_adapters.run_all(project)` reads the four sources and inserts proposals idempotently; a source that cannot be read logs one event and is skipped.

**Files:**
- Create: `board/improve_adapters.py`, `board/tests/test_improve_adapters.py`

**Acceptance Criteria:**
- [ ] `dream`: for the newest run dir under `dream_paths.project_dir(project)` with `out/report.json`, each `proposals[i]`: `observer` → kind `procedure`, patch null, state `proposed`; `idea` → kind `spec`, state `drafted`, no branch. Evidence `[{"type": "report", "ref": "<report path>#proposals[i]"}]` plus each `evidence` string of the item as `{"type": "note", …}`. Target: `item.get("target")`, else `dream:<run>:<i>`.
- [ ] `scout`: each draft in `scout_post._drafts().read()["drafts"]` with a `path` → kind `spec`, state `drafted`, target the draft's `path`, evidence `{"type": "report", "ref": "scout drafts.json#<id>"}`, outcome `O1` only when the draft's title or text contains `O1`. The scout's own approval flow is not touched.
- [ ] `discovery`: each item in the discover state (`discover_post` store) that carries a drafted spec path → the same as scout. Items without one are skipped.
- [ ] `observer`: the task-observer workspace (`TC_OBSERVER_DIR`, default `~/.task-observer`). For each round named "awaiting install" in `skill-updates/PENDING.md`, each `skill-updates/<round>/<skill>/SKILL.md` becomes kind `skill`, target `<skill>`, patch = `diff -u <live skill SKILL.md> <staged SKILL.md>` (live from `claude/skills/<skill>/SKILL.md`, else `~/.claude/skills/<skill>/SKILL.md`; neither → skipped with an event). Each `_target-files/<name>.patch` becomes kind `rule` with target the file it patches (its `+++` line). Evidence `{"type": "report", "ref": "<PENDING.md>#<round>"}`.
- [ ] Re-running every adapter on unchanged sources inserts nothing (dedupe key from Task 3). A changed patch is a new proposal.
- [ ] A missing or unparsable source writes one `events` row (kind `improve_adapter_error`, detail `{source, reason}`) and the other adapters still run.
- [ ] Fixtures: a dream `report.json`, a scout `drafts.json`, a discover state file and an observer workspace (PENDING.md + one round with one skill and one `_target-files` patch), all in temp dirs. No test reads `~/.task-observer` or `~/.local/state`.
- [ ] A `_target-files` patch on `claude/orchestrator.md` is classed `protected` (end to end through `insert`).

**Verify:** `python3 -m unittest board.tests.test_improve_adapters -v` → `OK`

**Steps:**

- [ ] RED tests per criterion (mutation for the idempotence test: drop the dedupe lookup → second run inserts again). Implement with the paths and stores the criteria name; read `board/dream_paths.py`, `board/scout_post.py` and `board/discover_post.py` first and add a `TC_*` override only where none exists. GREEN; **commit** `feat(improve): source adapters`.

```json:metadata
{"files": ["board/improve_adapters.py", "board/tests/test_improve_adapters.py"], "verifyCommand": "python3 -m unittest board.tests.test_improve_adapters -v", "acceptanceCriteria": ["dream: observer -> procedure null patch, idea -> drafted spec, report evidence", "scout drafts -> drafted spec, O1 link by text", "discovery items with a drafted spec only", "observer: staged SKILL.md diffs -> skill, _target-files patches -> rule", "idempotent re-run inserts nothing", "unreadable source: one event, others run", "temp-dir fixtures only", "orchestrator.md patch classed protected"], "modelTier": "standard"}
```

---

### Task 5: Metrics: `variants`, guardrail fields and `compare_halves`

**Goal:** Run records carry `variants`, `red_after_merge` and `final_review_crit_imp`, and `board/metrics.py` gains `compare_halves`, the decision rule for a trial half against a control half.

**Files:**
- Modify: `board/metrics.py` (`cmd_start` ~219 and the start parser: `--variants`; `build_record` ~836: copy `variants` from the start record, add `red_after_merge` and `final_review_crit_imp`; new `compare_halves` next to `permutation_p` ~1418 and `quality_veto` ~1469). At main 0af42b5 the engine calls `metrics start <spec> --batch B --worktree W` (`engine/lib/engine/core.js:1121`) and `metrics record <spec> --batch B --outcome O --budget JSON --engine-jobs JSON` (`engine/lib/engine/integrate.js:158`); `build_record` already takes `engine_jobs` and `budget_spec`. Keep both flags working.
- Create: `board/tests/test_metrics_halves.py`

**Acceptance Criteria:**
- [ ] `tmux-ctl metrics start … --variants P1,P3` stores `"variants": ["P1","P3"]` on the start line; `metrics record` copies it to the run record (an absent flag gives `[]`). Same pattern as `--worktree` (TMW Task 4): read that code first.
- [ ] `red_after_merge`: true when the spec's ledger (`docs/superpowers/ledgers/<plan basename>/progress.md`) has a line in the form the engine writes for "tests red after the merge" (Task 1 note, row 9), else false. `final_review_crit_imp`: the count of critical and important final-review findings from the same ledger's final-review lines (the line forms `ledger_fields` already parses; add the severities if it only counts). Both are null with a `missing` reason when no ledger exists.
- [ ] `compare_halves(trial, control, metric, defects=())` implements the Metric definitions verdict exactly: `too early` (< 4 specs in either half), `better`, `equal`, `worse` for `tokens_per_merged_task`, `fix_rounds_per_task` and `bounces_per_task`; `worse`/`equal` for the count guardrails. It returns `{"verdict", "index", "p_better", "p_worse", "n_trial", "n_control", "trial_value", "control_value"}`.
- [ ] R4 test: a trial half whose failed specs are cheap but unmerged does not come out `better` than control (mutation: sum tokens over merged specs only → test fails).
- [ ] R2 fixture: trial `tokens_per_merged_task` 30% lower (`better`) while `red_after_merge` is 3 vs 0 over 5 specs each → the guardrail verdict is `worse`. (Task 8 asserts the resulting `reverted`.)
- [ ] `metrics report` and `metrics compare` output on the existing fixtures is unchanged (`test_metrics_report.py` passes as-is), and a record built with `--budget`/`--engine-jobs` still carries `budget`, `control_tokens` and `control_share`.

**Verify:** `python3 -m unittest board.tests.test_metrics_halves board.tests.test_metrics_report -v` → `OK`

**Steps:**

- [ ] RED tests per criterion (each naming its mutation), implement in `board/metrics.py` reusing `permutation_p` and the `quality_veto` formula (do not change either function), GREEN; **commit** `feat(metrics): variants, guardrail fields, compare_halves`.

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_halves.py"], "verifyCommand": "python3 -m unittest board.tests.test_metrics_halves board.tests.test_metrics_report -v", "acceptanceCriteria": ["metrics start --variants stored and copied to the run record", "red_after_merge and final_review_crit_imp from the ledger, null+missing without one", "compare_halves verdicts per the Metric definitions", "R4: cheap unmerged failures never better", "R2 fixture guardrail worse", "metrics report unchanged"], "modelTier": "standard"}
```

---

### Task 6: Trial assignment and `tmux-ctl improve variants`

**Goal:** `improve_trials.py` decides which `trial` proposals apply to a spec and, through `tmux-ctl improve variants <spec> --json`, gives the engine what it needs to build that spec's trial briefs, challenger skills and routing.

**Files:**
- Create: `board/improve_trials.py`, `board/tests/test_improve_trials.py`
- Modify: `board/improve.py` (subcommand `variants`)

**Acceptance Criteria:**
- [ ] `in_trial(spec_id, pid)` is the Global Constraints split. Over 100 synthetic spec ids (`docs/superpowers/specs/s{i}.md`) and `P1`, the trial count is between 40 and 60, and two calls agree (stable).
- [ ] `variants <spec> --json` prints `{"spec": …, "variants": [{"id", "kind", "target", …}]}` for every proposal in `trial` whose split puts the spec in the trial half:
  - `procedure|rule|prompt`: `"overlay": "## Trial <id>\n<changed text>\n(This replaces the section <section heading> of <target>.)"`. The changed text is the patched section of the target after `git apply` in a temp copy, and the section is the nearest `#` heading above the first hunk.
  - `skill`: `"skill_copy": {"from": "claude/skills/<skill>", "to": ".superpowers/improve/skills/<skill>@<id>", "patch": "<patch path>"}`.
  - `routing`: `"routing": <the patched model-routing.json object>`.
  - Code Mode (E5): a proposal of kind `routing` whose patch adds `"codeMode": true` for the mechanical tier gives `"env": {"CLAUDE_CODE_EXPERIMENTAL_CODE_MODE": "1"}, "applies_to": {"tier": "mechanical", "kind": "implement"}`.
- [ ] A spec in no trial prints `{"spec": …, "variants": []}`. A patch that no longer applies to the main checkout moves the proposal to `rejected` with `stale patch` (error handling) and leaves it out.
- [ ] The champion files are byte-identical after `variants` runs (sha256 of target before/after in the test).

**Verify:** `python3 -m unittest board.tests.test_improve_trials -v` → `OK`

**Steps:**

- [ ] RED tests (mutation for the split: use `% 3` → the 40-60 band fails; for champion identity: apply in place → sha differs), implement, GREEN; **commit** `feat(improve): trial split and variants for the engine`.

```json:metadata
{"files": ["board/improve_trials.py", "board/improve.py", "board/tests/test_improve_trials.py"], "verifyCommand": "python3 -m unittest board.tests.test_improve_trials -v", "acceptanceCriteria": ["hash split stable, 40-60 of 100 in trial", "variants JSON: overlay, skill_copy, routing, Code Mode env", "no-trial spec prints empty variants; stale patch -> rejected", "champion files byte-identical"], "modelTier": "standard"}
```

---

### Task 7: Engine: trial overlays, challenger skills, routing and `variants` on engine-run specs

**Goal:** Every brief the engine writes for an engine-run spec carries that spec's trial overlays, its jobs use the challenger skill copies and the patched routing map, and its `metrics start` call passes `--variants`, all from `tmux-ctl improve variants <spec> --json`.

**Files:**
- Create: `engine/lib/improve.js`, `engine/test/improve.test.js`
- Modify: the engine's brief builder, job dispatch and `metrics start` call: at main 0af42b5 all in `engine/lib/engine/core.js` (`briefFor` ~955, the tier-to-model map ~151, `metrics start` ~1121); Task 1's note, section "Files the later tasks change", Task 7, confirms or corrects this

**Constraints:**
- The engine calls only `tmux-ctl improve variants <spec> --json` (one call per spec when it starts running), stores the result on the spec (an event, so replay holds), and never opens the `proposals` table.
- Overlays go only into briefs of trial specs. A challenger copy is created only in that spec's worktree under `.superpowers/improve/skills/` (git-ignored), and the brief names `<skill>@<id>` instead of the champion. Routing: the patched tier-to-model map applies only to that spec's jobs. Code Mode env applies only to mechanical-tier `implement` jobs.
- Lead-run specs get none of this (spec, out of scope: no trials on lead-run specs).
- A failing `improve variants` call (exit ≠ 0) runs the spec with no variants and records one `improve_variants_error` event. It never fails the spec.
- The champion files on `main` are never touched.

**Acceptance Criteria:**
- [ ] With the fake backend and a fixture proposal set, a trial spec's implementer brief contains `## Trial P1` and a control spec's brief does not.
- [ ] A skill trial creates `<worktree>/.superpowers/improve/skills/<skill>@P2/SKILL.md` (patched) in the trial spec's worktree only. `git status --porcelain` in that worktree stays clean, and the champion `claude/skills/<skill>/SKILL.md` sha256 is unchanged.
- [ ] A routing trial makes the trial spec's mechanical jobs start on the patched model; the control spec's start on the champion model.
- [ ] The engine's `metrics start` argv for a trial spec contains `--variants P1,P2`.
- [ ] `improve variants` exiting 1 → the spec runs, one `improve_variants_error` event.
- [ ] `engine rebuild --check` exits 0 after a run with variants.

**Verify:** `(cd engine && node --test test/improve.test.js)` → `# fail 0`

```json:metadata
{"files": ["engine/lib/improve.js", "engine/lib/engine/core.js", "engine/test/improve.test.js"], "verifyCommand": "(cd engine && node --test test/improve.test.js)", "acceptanceCriteria": ["overlay only in trial specs' briefs", "challenger skill copy only in the trial worktree, git-ignored, champion unchanged", "routing trial changes only the trial spec's mechanical model", "metrics start carries --variants", "variants call failure: spec runs, one error event", "rebuild --check 0"], "modelTier": "frontier"}
```

---

### Task 8: The tick: observe, evaluate trials, evaluate outcomes

**Goal:** `tmux-ctl improve tick` runs the adapters, then evaluates each trial and each active outcome by the Tick decisions in Global Constraints, as one transaction and event per step.

**Files:**
- Create: `board/improve_eval.py`, `board/tests/test_improve_eval.py`
- Modify: `board/improve.py` (subcommand `tick`; R3 rule in the module docstring)

**Acceptance Criteria:**
- [ ] Order per tick: adapters (Task 4) → observe (`metrics` run records read through `board/metrics.py` functions, never by opening the file elsewhere) → evaluate trials → evaluate outcomes → pick trials (Task 9; this task calls it when it exists, else skips) → digest (Task 12). Each step writes one `improve_step` event `{step, counts}`.
- [ ] Synthetic run logs (via `--log`-style override or the fixture helpers), one test per path, each naming its mutation:
  - low, signal `better`, guardrails `equal` → `kept` (and Task 10's apply is called; mocked here)
  - low, signal `worse` → `reverted`
  - R2 fixture (signal better, `red_after_merge` worse) → `reverted`, never `kept` or `awaiting_you` (mutation: drop the guardrail check → kept)
  - high, any verdict → `awaiting_you` with the numbers in `reason`
  - `too early` with 7 trial specs → stays `trial`; 15 trial specs still `too early` → `reverted` / `no signal`
  - trial tokens over the spend cap → `reverted` / `over budget`
  - a trial spec whose events hold a `ruling` citing `Trial P1` → `reverted` / `variant blamed: <event id>`
  - E1: a proposal with `shrinks_reads` and `fix_rounds_per_task` worse → `reverted`
  - guardrail worse across all engine-run specs since the last tick (vs baseline) → every `trial` reverted, and a breach card lists the `kept` changes since the last tick with one Revert button each (card call mocked; nothing reverted by itself)
  - O1 completion met (pooled `tokens_per_merged_task` index ≤ 0.75 over ≥ 2 batches, guardrails not worse) → the outcome is reported `achieved` once (one event + one post call); the outcome file is not edited (it is protected; the event records it)
- [ ] An outcome in state `paused` or `achieved` is not evaluated.
- [ ] A trial whose specs stopped (no new record) keeps its state.

**Verify:** `python3 -m unittest board.tests.test_improve_eval -v` → `OK`

**Steps:**

- [ ] RED tests per path above, using `board/tests/improve_fixtures.py` to build run logs with `variants`, `runner` and outcomes. Implement `improve_eval.evaluate_trials(store, runs, now)` and `evaluate_outcomes(store, runs, outcomes, last_tick)` on `metrics.compare_halves`. GREEN; **commit** `feat(improve): tick evaluates trials and outcomes`.

```json:metadata
{"files": ["board/improve_eval.py", "board/improve.py", "board/tests/test_improve_eval.py"], "verifyCommand": "python3 -m unittest board.tests.test_improve_eval -v", "acceptanceCriteria": ["tick order with one improve_step event per step", "low kept / low reverted", "R2 fixture reverted", "high -> awaiting_you with numbers", "too early continues; 15 specs -> no signal", "spend cap -> over budget", "variant blamed by a ruling -> reverted", "E1 shrinks_reads judged on fix rounds and bounces", "guardrail breach reverts trials, cards kept changes, reverts none", "O1 achieved once; outcome file untouched", "paused/achieved outcomes skipped; stalled trial keeps state"], "modelTier": "standard"}
```

---

### Task 9: Pick trials (the ranking step)

**Goal:** The tick starts at most two trials at a time, ranked by one mechanical-tier model call over the candidates' evidence; a ranking failure picks nothing that tick.

**Files:**
- Create: `board/improve_pick.py`, `claude/improve-rank.md`, `board/tests/test_improve_pick.py`

**Acceptance Criteria:**
- [ ] Candidates: `proposed`, class `low` or `high`, non-null patch, target not already in a `trial`. With 2 trials running, no call is made (mutation: drop the slot check → a fake `claude` records a call → test fails).
- [ ] The call: `[TC_IMPROVE_CLAUDE or "claude", "-p", "--model", <mechanical model from docs/superpowers/model-routing.json>, "--effort", "low", "--permission-mode", "dontAsk", "--output-format", "json"]`, prompt `claude/improve-rank.md` + the candidates (id, kind, target, evidence, linked outcome) + the active outcomes. The prompt asks for a JSON list of ids, best first, and nothing else. Timeout 300 s.
- [ ] The reply is accepted only when it parses as a list of candidate ids and `usage.output_tokens` ≤ 2000. Then the top `2 - running` start: `trial`, `trial_started_at` now. Anything else (exit ≠ 0, timeout, bad JSON, unknown id, over 2000 tokens) → one `improve_rank_failed` event, nothing starts.
- [ ] A fake `claude` script (written by the test into a temp dir) serves each case. No test runs the real `claude`.

**Verify:** `python3 -m unittest board.tests.test_improve_pick -v` → `OK`

**Steps:**

- [ ] Read `board/scout_eval.py` `run_evaluate` (lines ~30-75) and copy its subprocess and JSON-result handling. Differences that change behaviour: the model comes from `model-routing.json` `mechanical` (not a literal `sonnet`), the effort is `low`, there are no input files (the candidates go in the prompt text), and the output-token check. RED, implement, GREEN; **commit** `feat(improve): pick trials by one ranking call`.

```json:metadata
{"files": ["board/improve_pick.py", "claude/improve-rank.md", "board/tests/test_improve_pick.py"], "verifyCommand": "python3 -m unittest board.tests.test_improve_pick -v", "acceptanceCriteria": ["candidate filter; no call with 2 trials running", "argv from model-routing mechanical, effort low, prompt file", "accept only a valid id list within 2000 output tokens; else one event, none started", "fake claude only"], "modelTier": "standard"}
```

---

### Task 10: Promotion, revert, retire and drafted specs through the engine's merge step

**Goal:** `kept` and `promoted` proposals land on `main` as one `improve(<kind>): <id> <title>` commit through a new engine merge entry that refuses protected paths, `improve revert <id>` reverts that commit the same way, retire is a soft delete, and a protected proposal becomes a drafted spec on its own branch.

**Files:**
- Create: `board/improve_apply.py`, `board/tests/test_improve_apply.py`, `engine/test/improve_merge.test.js`
- Modify: `board/improve.py` (`revert`), the engine merge step and CLI (at main 0af42b5: `engine/lib/engine/integrate.js`, merge ~83 and revert ~216; `engine/lib/engine/cli.js`, the `SUBS` list ~22 gains the merge entry; the `Engine-Step` check is `engine/lib/engine/steps.js:74`; Task 1's note, Task 10, confirms), `engine/lib/improve.js` (protected-path check, reads `docs/superpowers/improve/protected.txt`)

**Constraints:**
- The loop builds the commit on branch `improve/<id>` (from `main`, in a worktree under `${TC_STATE}/improve/<project>/wt/<id>`). Message `improve(<kind>): <id> <title>`, trailers `Proposal: <id>` and `Engine-Step: improve:<id>@<main sha>`. Path-scoped: the commit touches only the patch's target. It then asks the engine to merge it with one command (name it in the note, for example `tmux-ctl engine merge-branch improve/<id> --key improve:<id>@<sha> --proposal <id>`). The engine runs its merge step: a `steps` row kind `merge`, the live-checkout check (mid-change → the commit waits for the next tick, state unchanged), and the trailer check on resume (§10.4).
- The engine's merge refuses (exit 2, `protected path <p>`) an `improve(...)` commit whose diff touches any protected path, unless the proposal's state is `promoted` and its class is not `protected`. It reads the class and state with `tmux-ctl improve show <id> --json`.
- `revert <id>`: refused for a protected target (`protected`) or without `commit_sha` (`no commit`). Otherwise a `git revert --no-edit <sha>` on branch `improve/<id>-revert` with the trailers, merged by the same entry. State `reverted`, one event.
- Retire (R5): applying a kept or promoted `retire` moves the target to `.superpowers/improve/retired/<id>/` (or comments out its section with a `retired: <id>` marker when the target is a section, `path#heading`) in the commit, and logs an undo line in the event. `improve revert` restores it.
- Drafted spec for a `protected` proposal: the tick writes `docs/superpowers/specs/drafts/<date>-improve-<id>.md` (title, the proposal, its evidence, its patch in a fenced `diff` block) on branch `improve/<id>` from `main`, committed on that branch only, and state `drafted`. Approve (Task 12) merges that branch through the same entry, adds the ideas line (`ideas.add_done(project, "improve: <title>", <draft path>)`) and tells the lead `[Improve] approved: <draft path>`, the steps `scout_decisions._follow` takes.
- A patch that no longer applies on `main` → `rejected` / `stale patch`.

**Acceptance Criteria:**
- [ ] On a scratch clone (`TC_ENGINE_DIR`, `TC_STATE` temp): a low `kept` proposal gives exactly one commit on `main` with the subject and both trailers, touching only its target. Running the apply again (crash after the merge, before the state write) makes no second commit (the trailer check).
- [ ] The engine merge refuses an `improve(...)` commit touching `claude/orchestrator.md` (exit 2) for a `kept` proposal, and refuses a promoted one whose class is `protected`.
- [ ] `improve revert P1` creates one revert commit with the trailers, and refuses `no commit` / `protected`.
- [ ] Retire then revert restores the file byte for byte (sha256).
- [ ] A protected proposal yields the draft file on `improve/<id>` only: `git log main -- docs/superpowers/specs/drafts/` is empty.
- [ ] Live checkout mid-change (a dirty tracked file in the scratch clone's main checkout) → no commit, state unchanged, one `improve_waiting` event.

**Verify:** `python3 -m unittest board.tests.test_improve_apply -v && (cd engine && node --test test/improve_merge.test.js)` → `OK` and `# fail 0`

```json:metadata
{"files": ["board/improve_apply.py", "board/improve.py", "engine/lib/improve.js", "engine/lib/engine/integrate.js", "engine/lib/engine/cli.js", "board/tests/test_improve_apply.py", "engine/test/improve_merge.test.js"], "verifyCommand": "python3 -m unittest board.tests.test_improve_apply -v && (cd engine && node --test test/improve_merge.test.js)", "acceptanceCriteria": ["one improve commit with Proposal and Engine-Step trailers, path-scoped, no duplicate on re-run", "engine merge refuses protected paths unless promoted and not protected", "revert: one commit, refuses no commit / protected", "retire + revert byte-identical", "drafted spec only on improve/<id>", "live checkout mid-change waits"], "modelTier": "frontier"}
```

---

### Task 11: Engine: protected-path hold, the `improve` schedule and the post-report tick

**Goal:** Engine workers are held on Write or Edit of a protected path, `improve tick` runs on the engine schedule `weekly Sun 08:00`, and the engine inserts a `schedule` inbox row for `improve` after each morning report.

**Files:**
- Create: `engine/test/improve_holds.test.js`
- Modify: `engine/lib/improve.js`, the engine's hold defaults, report writer and install/schedule setup (files in Task 1's note, Task 11). At main 0af42b5 the report writer is the `queue_report` step (`engine/lib/engine/core.js:1234`, `engine/lib/engine/queue_report.js`); hold defaults and the schedule setup do not exist yet (engine §13/§14, stage 7), which is why Task 1 stops the plan until they do.

**Constraints:**
- Hold (§13, spec §6): the engine's default hold list gains, for each line of `protected.txt` (except `~/` lines, which become an absolute-path pattern, and `bin/tmux-ctl#improve`, which becomes `bin/tmux-ctl`), a `{"tool": "Write|Edit", "pattern": <regex of the glob>, "outside_worktree": false}`. Patterns are built when the hold hook loads, from the file on `main`.
- Schedule (§14, spec §2): one row `improve`, rule `weekly Sun 08:00`, command `tmux-ctl improve tick`, default `skip_if_weekly_usage` 85, added by `tmux-ctl engine schedule add` in the plan's install step (idempotent: an existing `improve` row is left as it is).
- After the morning report is committed (§7), the engine inserts `inbox` source `schedule`, `source_id` `improve@<report date>`, payload the same command. It is drained like any schedule row.
- R3: the loop adds no Stop hook. `claude/plugin/hooks/hooks.json` gains nothing.

**Acceptance Criteria:**
- [ ] A fake worker's Edit of `claude/orchestrator.md` (inside its worktree) is denied with a hold id, and an Edit of `claude/skills/x/SKILL.md` is not held.
- [ ] `tmux-ctl engine schedule list` (temp `TC_ENGINE_DIR`) shows `improve` `weekly Sun 08:00` after the install step, and running the step twice leaves one row.
- [ ] A fixture queue's report write produces exactly one inbox row `schedule` / `improve@<date>`; a second write the same day adds none (`INSERT OR IGNORE`).
- [ ] At or over 85% weekly usage (fixture tap) the scheduled `improve` run is skipped with a `schedule_skipped` event.
- [ ] `grep -c improve claude/plugin/hooks/hooks.json` → 0, and `board/improve.py`'s docstring contains `stop_hook_active`.

**Verify:** `(cd engine && node --test test/improve_holds.test.js) && test "$(grep -c improve claude/plugin/hooks/hooks.json)" = 0 && grep -c stop_hook_active board/improve.py` → `# fail 0`, then `1` or more

```json:metadata
{"files": ["engine/lib/improve.js", "engine/lib/engine/core.js", "engine/lib/engine/queue_report.js", "engine/test/improve_holds.test.js", "board/improve.py"], "verifyCommand": "(cd engine && node --test test/improve_holds.test.js) && test \"$(grep -c improve claude/plugin/hooks/hooks.json)\" = 0 && grep -c stop_hook_active board/improve.py", "acceptanceCriteria": ["Edit of a protected path held; other paths not", "improve schedule row weekly Sun 08:00, idempotent install", "one schedule inbox row per report date", "85% weekly usage skips with an event", "no improve Stop hook; R3 rule in improve.py docstring"], "modelTier": "frontier"}
```

---

### Task 12: Discord cards, clicks and the weekly digest line

**Goal:** `board/improve_discord.py` posts only the five kinds of card the Global Constraints allow, handles `ab:improve:` clicks through `board/discord_controls.py`, and the Sunday tick posts the one digest line.

**Files:**
- Create: `board/improve_discord.py`, `board/tests/test_improve_discord.py`
- Modify: `board/discord_controls.py` (route `ab:improve:` clicks), `board/improve.py` (`click` subcommand for CLI parity)

**Acceptance Criteria:**
- [ ] Cards are written with `discord_feed.outbox_write(tc_env.discord_dir(project), op)` as `board/dream_discord.py` does (read it first; differences: tier `decision` for awaiting_you, drafted and breach cards, `progress` for achieved and the digest; no files attached; the custom ids below). Custom ids ≤ 100 chars, else the card text ends with the CLI command instead of buttons.
  - `awaiting_you`: text `🧪 <id> <kind> <target>: trial <signal verdict> (index <x>, p <y>), guardrails <list>` with buttons Promote (`promote`), Reject (`reject`), Extend trial by 5 (`extend`).
  - `drafted`: Approve (`approve`), Reject (`reject`).
  - breach: one line per kept change since the last tick, with a Revert (`revert`) button each.
  - achieved: `🎯 <outcome id> achieved: <value> vs <target>` (no buttons).
  - digest (Sunday tick only, once per ISO week, key `improve-digest-<project>-<week>`): `🧪 improve: <n> trials, <k> kept, <r> reverted, <a> awaiting you; O1 <value> vs target`.
- [ ] `click(project, user, cid, now)`: `promote` → `promoted` then Task 10's apply; `reject` → `rejected`; `extend` → back to `trial` with `trial_len += 5`; `approve` (drafted) → Task 10's approve path; `revert` → Task 10's revert. A click for another project → `ignored`; an unknown id → `unknown`; a state that no longer allows the action → `stale` (no change). Each acting click writes one result post.
- [ ] `discord_controls` routes `ab:improve:` like `ab:dream:` (allowlist check, `audit_append`). Existing `test_discord_controls.py` passes.
- [ ] No other code path posts (a test greps `board/improve*.py` for `outbox_write` and finds it only in `improve_discord.py`).

**Verify:** `python3 -m unittest board.tests.test_improve_discord board.tests.test_discord_controls -v` → `OK`

**Steps:**

- [ ] RED tests (a double click → second is `stale`, mutation: skip the state check → two transitions), implement, GREEN; **commit** `feat(improve): Discord cards, clicks, weekly digest`.

```json:metadata
{"files": ["board/improve_discord.py", "board/discord_controls.py", "board/improve.py", "board/tests/test_improve_discord.py"], "verifyCommand": "python3 -m unittest board.tests.test_improve_discord board.tests.test_discord_controls -v", "acceptanceCriteria": ["five card kinds only, through outbox_write, custom ids <= 100 chars", "click actions promote/reject/extend/approve/revert; ignored/unknown/stale", "discord_controls routes ab:improve:", "outbox_write only in improve_discord.py"], "modelTier": "standard"}
```

---

### Task 13: README, help and the all.zsh jobs

**Goal:** The README documents the loop and its protected set, `tmux-ctl help` lists `improve`, and `tools/tests/all.zsh` picks up the new suites.

**Files:**
- Modify: `README.md` (one section "Supervised improvement loop"), `bin/tmux-ctl` (help comment lines in the header block that `help` prints). `tools/tests/all.zsh` needs no change: it adds one job per `board/tests/test_*.py` and `tools/tests/test_*.zsh` and runs `engine/test/*.test.js` (lines 36-44), so the new files are picked up.

**Acceptance Criteria:**
- [ ] README section names: `tmux-ctl improve outcome status|list|show|propose|revert|tick`, the protected file `docs/superpowers/improve/protected.txt`, the outcome files `docs/superpowers/outcomes/`, and the rule "learning is cheap, changing behaviour needs evidence, changing authority needs approval".
- [ ] `zsh bin/tmux-ctl help | grep -c improve` ≥ 1.
- [ ] `zsh tools/tests/all.zsh --list | grep -c improve` ≥ 1.
- [ ] The help header still ends `…registry|engine <sub> …` / `…metrics <sub> …` / `#`, and `python3 -m unittest board.tests.test_metrics_weekly.HelpTest` passes (it pins the `metrics <sub>` line as the last line of the printed range and the range end on the header's `#` line).

**Verify:** `zsh bin/tmux-ctl help | grep -c improve; zsh tools/tests/all.zsh --list | grep -c improve; grep -c 'protected.txt' README.md; python3 -m unittest board.tests.test_metrics_weekly.HelpTest` → each count ≥ 1, then `OK`

**Steps:**

- [ ] **Step 1:** In `README.md`, after the section that describes the trend scout (find it with `grep -n -i scout README.md`), add:

```markdown
## Supervised improvement loop

Learning is cheap, changing behaviour needs evidence, changing authority needs approval. `tmux-ctl improve tick`
(weekly on the engine schedule, and after every queue's morning report) collects proposals from memory consolidation,
opportunity discovery, the trend scout, task-observer and `tmux-ctl improve propose`, trials low and high ones on half
of the engine-run specs, keeps or reverts low ones by the metrics decision rule against the active outcomes in
`docs/superpowers/outcomes/`, and cards the rest to you on Discord. It never changes a path in
`docs/superpowers/improve/protected.txt`. Commands: `tmux-ctl improve outcome status|list|show|propose|revert|tick`.
```

- [ ] **Step 2:** In `bin/tmux-ctl`'s help header (the lines `sed -n '2,85p'` prints, at line ~857), add this line directly **above** the `#   tmux-ctl registry|engine <sub> …` line (line 83 at main 0af42b5), in the same comment style:

```
#   tmux-ctl improve outcome status|list|show|propose|revert|tick   the supervised improvement loop (board/improve.py)
```

  Not after the `metrics` line: `board/tests/test_metrics_weekly.py` `HelpTest` requires `#   tmux-ctl metrics <sub>` to stay the last line before the header's `#` line. The header grows by one line, so change `sed -n '2,85p'` to `sed -n '2,86p'`, then check `sed -n '86p' bin/tmux-ctl` prints `#` and `sed -n '87p' bin/tmux-ctl` starts `# send/run only type`.
- [ ] **Step 3:** Confirm `zsh tools/tests/all.zsh --list | grep improve` lists `zsh/test_ctl_improve.zsh` and the `board/test_improve_*` jobs.
- [ ] **Step 4:** Run Verify; **commit** `docs(improve): README, help, all.zsh job`.

```json:metadata
{"files": ["README.md", "bin/tmux-ctl"], "verifyCommand": "zsh bin/tmux-ctl help | grep -c improve; zsh tools/tests/all.zsh --list | grep -c improve; grep -c 'protected.txt' README.md; python3 -m unittest board.tests.test_metrics_weekly.HelpTest", "acceptanceCriteria": ["README section with commands, protected.txt, outcomes dir, the rule", "tmux-ctl help lists improve", "all.zsh --list shows the improve jobs (auto-discovered)", "help line above registry|engine, range 2,86p, metrics <sub> still last; HelpTest passes"], "modelTier": "mechanical"}
```

---

### Task 14: Isolation, leak check, full suite and read-only real-state checks

**Goal:** No test touches the real engine database, state dir, task-observer workspace or `main`, every suite passes, and the loop's read paths behave on the real state, read-only.

**Files:**
- Create: `board/tests/test_improve_isolation.py`

**Acceptance Criteria:**
- [ ] `test_improve_isolation.py` records the sha256 and mtime of `~/.local/state/agent-board/engine/` (each file, or `absent`), the real `docs/superpowers/metrics/runs.jsonl`, `~/.task-observer/skill-updates/PENDING.md` and `git rev-parse main` of the main checkout. It runs every `board/tests/test_improve_*.py` module in a subprocess, then asserts all are unchanged. It prints the count of files checked (≥ 3), so it cannot pass on an empty set.
- [ ] `zsh tools/tests/all.zsh; echo rc=$?` → the runner's verdict line `ALL PASS …` with `rc=0` or `rc=4` (over budget, accepted).
- [ ] Read-only real state (each command and its output in the ledger):
  - `zsh bin/tmux-ctl improve outcome status O1` against the real run log prints O1's value vs the baseline and `too early` or a verdict, and exits 0 (it writes nothing: `git status --porcelain docs/superpowers/metrics/` is empty afterwards).
  - the observer adapter in dry-run mode (`python3 -I board/improve.py adapters --dry-run --source observer`) on the real `~/.task-observer` lists the staged rounds `PENDING.md` names as awaiting install (≥ 1), with their derived classes, and inserts nothing.
  - the dream adapter in dry-run mode on the real newest dream run for this project prints its proposals' kinds, or `no report`.
  - `python3 -I board/improve.py variants docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md --json` prints `"variants": []` (no trial exists yet).
- [ ] `adapters --dry-run` exists (add it to `board/improve.py` if Task 4 did not), and prints the count of items read per source.

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → the runner's verdict line `ALL PASS …` and `rc=0` or `rc=4`

**Steps:**

- [ ] Run each criterion's command through `tmux-ctl run -t 1200 tests "<cmd>; echo rc=\$?"`, and capture the output in the ledger. Any failure: use `superpowers-extended-cc:systematic-debugging`, fix it in the owning task's files, re-run that task's Verify, then this one. **Commit** `test(improve): isolation and leak check`.

```json:metadata
{"files": ["board/tests/test_improve_isolation.py", "board/improve.py"], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["leak check: real engine dir, runs.jsonl, PENDING.md, main unchanged; prints files checked >= 3", "all.zsh ALL PASS rc 0 or 4", "outcome status O1 on the real log, nothing written", "observer adapter dry-run on the real workspace lists awaiting rounds, inserts nothing", "dream adapter dry-run on the real newest run", "variants for this spec is empty"], "modelTier": "standard"}
```

---

### Task 15: User gate: one real queue with O1 active and one low proposal

**Goal:** In the next real queue with engine-run specs, one low-authority proposal from a real memory consolidation report is trialled: the split, the overlay in a real brief, and the tick's verdict line appear in the morning report.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Test only

**Acceptance Criteria:**
- [ ] Before the queue: `tmux-ctl improve propose --from-dream <run>:<index> --kind procedure --target <skill or rule path> --patch <file>` from a real report in this project's dream dir gives a proposal whose `improve show` says class `high`, because R1 caps dream proposals at `high`. If the user wants a `low` trial, the user files the same prose patch with `--kind procedure` as source `user`, citing the report as evidence. The lead asks the user which, with the class each gives.
- [ ] After the queue's specs ran: `tmux-ctl improve show <id>` lists the trial and control specs by the hash split. At least one trial spec's brief file under `<worktree>/.superpowers/engine/` contains `## Trial <id>` (captured with `grep -l`), and at least one control spec's does not.
- [ ] The run records of those specs carry `variants` (`tmux-ctl metrics runs <batch> --json`).
- [ ] The morning report `docs/superpowers/reports/<date>-queue.md` shows the post-report tick's verdict line for the proposal (`kept`, `reverted`, `awaiting_you` or `trial: <n>/5 specs`).

**Verify:** `tmux-ctl improve show <id>` → trial and control specs listed, state and verdict line recorded as evidence

```json:metadata
{"files": [], "verifyCommand": "tmux-ctl improve show <id>", "acceptanceCriteria": ["real dream-report proposal filed; class shown; lead asks user for low via user source", "trial spec brief has the Trial block, a control brief does not", "run records carry variants", "morning report shows the tick verdict line"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```

---

## Execution handoff

Run this plan with `superpowers-extended-cc:subagent-driven-development` (with `subagent-driven-development-extras`).
Task 1 runs first and alone. If it fails, the plan stops there and the lead gets the failure.
