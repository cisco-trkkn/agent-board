# Queue Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A committed per-spec run log (`docs/superpowers/metrics/runs.jsonl`) written by `tmux-ctl metrics …`, with batch numbers, a decision rule, gate evaluation, a roadmap status line, a backfilled baseline, and Queue-mode rules that use it.

**Architecture:** `board/metrics.py` holds all logic as plain functions over git (subprocess), the plan's `.tasks.json`, the archived ledger, the usage index (`board/usage.py`) and the lineage log; a `main()` with argparse subcommands. `bin/tmux-ctl metrics <sub>` execs it the way `overview` execs `board/overview.py`. Tests are `board/tests/test_metrics_*.py` on scratch git repos and scratch sqlite files.

**Tech Stack:** Python 3.9-compatible stdlib only (CI runs 3.9 on Ubuntu: no `match`, no `X | Y` annotations), git ≥ 2.38 `merge-tree --write-tree`, zsh (`bin/tmux-ctl`), unittest.

**Spec:** `docs/superpowers/specs/2026-11-10-queue-metrics-design.md` — every task's executor reads the section numbers cited in its task.

## Global Constraints

- **Run log format** (spec §1): one JSON object per line, `kind` ∈ `batch|start|run|defect` (`analysis` is reserved for stage 2; readers must ignore unknown kinds). Append-only; readers take the last `run` line per `(batch, spec)`; a malformed line is skipped by every reader and counted. Written with `json.dumps(obj, sort_keys=True)` + `\n`, appended with `open(path, "a")`.
- **Nothing private in any run-log line or config/gate file:** no session ids, no prompts, no agent names, no absolute paths (no `/Users/`, no `$HOME`), no tmux pane ids. Paths are repo-relative. A test (Task 6) greps the test-produced log and the real backfilled log, uncapped, and prints the number of lines checked.
- **Error contract** (spec "Error handling"): a failing `metrics` command prints exactly one line `metrics: <sub>: <reason>` to stderr and exits non-zero (1 unless the spec names another code). A missing source sets its fields to `null` and appends the field name to the record's `missing` list; `record` still writes the line. Never raise a traceback to the user.
- **Repo:** every command acts on `git rev-parse --show-toplevel` of the current directory; `--repo <dir>` overrides it (tests use it). Worktrees: the repo root for run-log paths is the toplevel of the cwd's checkout, but `main`'s commit is `git rev-parse main`.
- **Usage index:** open with `usage.connect(path)` where `path` is `--usage-db` if given, else `usage.db_path()`. Before reading, `record` and `backfill` ingest the project's transcripts: every `*.jsonl` under `usage.root()/<slug>/` (slug = repo root with `/` and `.` replaced by `-`, the Claude Code convention, e.g. `-Users-x-agent-board`) and its worktrees' slugs (`<slug>--claude-worktrees-*`), recursively (subagent files included), via `usage.ingest(conn, path)`. `--no-ingest` skips it (tests).
- **Lead rows** (spec §3): `agent_name` empty/null AND `sidechain == 0` AND `subagent_file == 0`. Do NOT use `usage.role()` for this (it calls a lead in a worktree a "worker"). Agent rows = all other attributed rows.
- **Tokens:** `total = input + output + cache_read + cache_write_5m + cache_write_1h`; `cache_write` in the record = `cache_write_5m + cache_write_1h`. `usd` = sum of `usage.call_cost(row, prices)` over priced rows; `unpriced_calls` = rows where it returns `None`.
- **Time:** all record timestamps are ISO-8601 UTC strings with `Z` (`2026-11-11T05:10:26Z`); durations are integers in seconds or minutes as named.
- **Excluded from touched files and diff lines:** paths under `docs/superpowers/`.
- **Python style:** follow `board/overview.py` / `board/usage.py` (module-level functions, `from usage import …` sibling imports; tests do `sys.path.insert(0, <board dir>)` like `board/tests/test_usage.py`). Run python as `python3 -I`.
- **Test isolation:** every test that touches state sets `TC_STATE` to a temp dir, uses `--repo <tmp git repo>` and `--usage-db <tmp sqlite>`, and never reads `~/.claude/projects` (set `USAGE_ROOT` to a temp dir). The only exception is Task 6's real-state test, which is read-only against the real repo and a snapshot copy of the usage index.
- **Known failing tests that don't count against this plan** (fixed by the next queued spec): `board/tests/test_orchestrator_path.py`, `board/tests/test_restart_orchestrator.py`, and `tools/tests/test_prompt_argv.zsh` when the caller's PATH already holds `<repo>/bin` (run zsh suites via `tmux-ctl run tests "…"`). `test_session_path`/`test_session_root_path` pass on macOS. Acceptance on CLAUDE.md suites = no new failures beyond these.
- **Commits:** conventional with scope (`feat(metrics): …`, `docs(orchestrator): …`); end with the attribution trailer your harness specifies. Stage only your own paths (`git add <paths>`).

### Metric definitions (each defined once; tasks cite these names)

- **M-attr (attributed calls of a spec):** usage rows with `ts` in `[window_start, window_end]` and (`git_branch == spec branch` OR `cwd` is inside the spec's worktree path `<repo>/.claude/worktrees/<name>/…` for a worktree whose branch is the spec branch — derive the worktree dir name from `git worktree list --porcelain` when it exists, else from rows whose `git_branch` matches) — PLUS, when the batch is sequential (no other spec of the batch has a window overlapping this one), every row (lead or agent) with `cwd == repo root` in the window. When windows overlap, each repo-root row in the overlap is divided evenly (tokens and usd × 1/k) among the k specs whose windows contain it, and `lead_shared = true`.
- **M-window:** `stamped`: start = the spec's last `start` line time, end = record time (live) or merge commit time. `derived` (backfill/no start line): start = previous backfilled merge's committer time on first-parent `main` (first one: the plan file's first commit time), end = the merge commit's committer time.
- **M-active (active minutes):** the number of distinct `floor(ts/60)` minutes among M-attr rows. `agents_active_min`: for each minute in the window that has ≥1 attributed row, count distinct `session_id`s among attributed agent rows in that minute → bucket `"0"`, `"1"`, `"2+"`.
- **M-ledger:** file `docs/superpowers/ledgers/<plan basename without .md>/progress.md`. `bounces` = lines matching `review spec ❌` or `quality ❌` or `❌` after `review` (regex `review.*❌`); `fix_rounds` = lines containing `fix round` and `dispatched` (one per dispatched round; the appendix counted all lines containing `fix round` — use `fix round` alone, to match the appendix); `final_findings` = count of lines starting `- ` under a heading containing `Important` or `Critical` in `final-review.md` of the same dir (0 when absent, `null` + missing when the dir is absent); `fix_wave` = a ledger line contains `fix wave` (case-insensitive); `rulings` = lines starting `Ruling:`; `parked` = lines containing `minor (deferred)` or `parked`.
- **M-manifest:** declared = union of every task's `files` in the plan's `.tasks.json` (metadata fence `json:metadata`, key `files`), repo-relative, excluding `docs/superpowers/`; touched = `git diff --name-only base..head` excluding `docs/superpowers/`; `both = |declared ∩ touched|`; `precision = both/declared`, `recall = both/touched` (null when the denominator is 0).
- **M-norm:** `tokens_per_task = tokens.total / tasks`; `active_min_per_task = active_min / tasks`.
- **M-accepted:** outcome ∈ {`merged`, `mr`}.

**User decisions (already made):** Real work only, no benchmark runs. Run log committed in the repo. Batch = unit of comparison; code assigns configurations. Normalise per task; replace at ≥8 challenger specs over ≥2 batches; large effects only. Queue integration for this spec: merge to `main` locally, no push.

**Rulings (lead, at plan time):**
- The spec's "uncommitted edit of the user's" in `claude/orchestrator.md` is gone: the live checkout was clean at `565352b`. Task 7 edits the file directly. Cost if wrong: none (git status was clean).
- "Backfill runs in the plan's first task" is met by Task 1 snapshotting the usage index (sqlite `.backup`) to `~/.local/state/agent-board/metrics/usage-snapshot-20261111.sqlite`; the backfill command itself comes in Task 6 and reads that snapshot when the live index lacks the days. Cost if wrong: none — the snapshot holds the same rows.

---

### Task 1: Scaffold, snapshot, run-log I/O and the simple commands

**Goal:** `board/metrics.py` with run-log reading/writing, config and gate file parsing, batch ids, assignment, and the `batch start`, `start`, `defect` subcommands, wired as `tmux-ctl metrics`; the usage index snapshotted.

**Files:**
- Create: `board/metrics.py`, `board/tests/test_metrics_log.py`, `docs/superpowers/metrics/configs/seq-sdd.md`, `docs/superpowers/metrics/roadmap`
- Modify: `bin/tmux-ctl` (help header line + `metrics)` case next to `overview)`)

**Acceptance Criteria:**
- [ ] `~/.local/state/agent-board/metrics/usage-snapshot-20261111.sqlite` exists and `sqlite3 <it> "select count(*) from calls"` ≥ 57000 (made with `sqlite3 <live> ".backup <snapshot>"`; not committed).
- [ ] `read_log(repo)` returns `(lines, malformed_count)`; unknown kinds are kept but ignored by `last_runs()`; `last_runs(lines)` returns the last `run` per `(batch, spec)`.
- [ ] `load_config(repo, id)` parses the `json:config` fence of `configs/<id>.md`; `load_gate(repo, id)` parses the `json:gate` fence of `gates/<id>.md`; missing file → `None`.
- [ ] `seq-sdd.md` has prose describing today's queue (lead on Opus, SDD with the extras, one spec at a time, merge per spec) and the fence `{"id": "seq-sdd", "baseline": true}`.
- [ ] `roadmap` holds exactly `PCEE docs/superpowers/specs/2026-11-10-pcee-decomposition.md` + newline.
- [ ] `metrics batch start --config A [--config B] [--group "s1,s2"]… <spec>…` appends one `batch` line `{kind, batch, base, configs, assignment: {spec: config}, groups, at}` with batch id `<YYYY-MM-DD>-<n>` (n = 1 + number of batch lines already dated that day), base = `git rev-parse main`; prints the id on line 1 and `<spec> <config>` lines after.
- [ ] Assignment with two configs: units (a group, or a single spec) sorted by `sha256((batch_id + first spec path of unit).encode()).hexdigest()`, configs given alternately starting with the baseline config (the one whose config file says `baseline: true`; if neither or both, the first `--config`). Deterministic across runs; groups stay together. With one config every spec gets it.
- [ ] `metrics start <spec> --batch <id>` appends `{kind:"start", batch, spec, at, main, limits:{five_hour, seven_day}}`; limits from the freshest status-line tap with `rate_limits` (`usage.plan_limits(usage.tap_entries(now, 10**9))`, percentages only — never the session id); null + `missing` when no tap.
- [ ] `metrics defect <spec> "<what>"` appends `{kind:"defect", spec, what, date:"YYYY-MM-DD"}`.
- [ ] Unknown `--batch` for `start` → `metrics: start: unknown batch <id>` exit 1; every failure is one stderr line.
- [ ] `tmux-ctl metrics batch start …` runs from any dir inside the repo; `tmux-ctl help` lists `metrics`.
- [ ] Tests: malformed-line skip and count; superseding; assignment determinism (same input twice → same output), group kept together (mutation: drop group handling → test fails), alternation starting with baseline; batch counter per day; private-data check on lines written by the tests (no `/Users/`, no UUID-shaped string; prints lines checked).

**Verify:** `python3 -I -m unittest discover -s board/tests -p 'test_metrics_log.py'` → `OK`

**Steps:**

- [ ] **Step 1: Snapshot the usage index**

```zsh
mkdir -p ~/.local/state/agent-board/metrics
live="${TC_STATE:-$TMPDIR/tmux-ctl-$(id -u)}/usage.sqlite"
sqlite3 "$live" ".backup $HOME/.local/state/agent-board/metrics/usage-snapshot-20261111.sqlite"
sqlite3 ~/.local/state/agent-board/metrics/usage-snapshot-20261111.sqlite "select count(*) from calls"
```

- [ ] **Step 2: Write failing tests** in `board/tests/test_metrics_log.py` for the acceptance criteria above (scratch repo via `git init`, one commit on `main`, `--repo` it). Run them; they fail with `ModuleNotFoundError: metrics`.
- [ ] **Step 3: Implement** `board/metrics.py`: `repo_root(repo_arg)`, `log_path(repo)`, `read_log`, `append(repo, obj)`, `last_runs`, `_fence(text, tag)`, `load_config`, `load_gate`, `new_batch_id(repo, today)`, `assign(batch_id, specs, groups, configs, baseline)`, `cmd_batch_start`, `cmd_start`, `cmd_defect`, `main(argv)` with argparse subparsers (`batch start`, `start`, `record`, `defect`, `report`, `compare`, `backfill`, `gate`, `status` — the not-yet-built ones print `metrics: <sub>: not implemented` exit 1 until their task lands). Wrap `main` so any exception prints `metrics: <sub>: <exc>` and exits 1.
- [ ] **Step 4: Wire tmux-ctl** — add a help header line `#   tmux-ctl metrics <sub> …                run-log metrics (board/metrics.py)` in the header block and, next to `overview)`:

```zsh
  metrics)
    exec python3 -I "${0:A:h:h}/board/metrics.py" "$@" ;;
```

  If the help `sed -n '2,42p'` range no longer covers the header after your line, widen it to the header's last line.
- [ ] **Step 5: Config and roadmap files**, run tests → OK, commit `feat(metrics): run log, batches and simple commands`.

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_log.py", "docs/superpowers/metrics/configs/seq-sdd.md", "docs/superpowers/metrics/roadmap", "bin/tmux-ctl"], "verifyCommand": "python3 -I -m unittest discover -s board/tests -p 'test_metrics_log.py'", "acceptanceCriteria": ["usage snapshot >= 57000 calls", "read_log/last_runs/malformed count", "config and gate fence parsing", "seq-sdd.md and roadmap files", "batch start line, id counter, assignment deterministic/grouped/alternating", "start line with limits or missing", "defect line", "one-line errors", "tmux-ctl metrics wired + help", "privacy check on test output"], "modelTier": "standard"}
```

---

### Task 2: `record` — identity, size, manifest, stale base, ledger

**Goal:** The git- and file-derived half of the `run` record (spec §3 Identity, Size, Quality and rework except `questions`/`handoffs`, PCEE premises), computed by `build_record_static(repo, spec, batch, outcome, now)`.

**Files:**
- Modify: `board/metrics.py`
- Create: `board/tests/test_metrics_record_git.py`, `board/tests/fixtures/metrics/remote-access-progress.md` (copy of `docs/superpowers/ledgers/2026-11-09-remote-access/progress.md`), `board/tests/fixtures/metrics/remote-access.tasks.json` (copy of `docs/superpowers/plans/2026-11-09-remote-access.md.tasks.json`)

**Acceptance Criteria:**
- [ ] Plan lookup: the file in `docs/superpowers/plans/*.md` whose header has a line `**Spec:**` containing the spec path (strip a `#part-N` suffix from the spec for matching; keep it in the record). No plan → `plan: null`, `missing` has `plan`.
- [ ] Branch and merge: the first first-parent merge on `main` (`git log --first-parent --merges main --format=%H %P %ct %s`) after the spec's `start` line time (or, with none, after the plan's first commit) whose second parent has the plan file's first commit as ancestor (`git merge-base --is-ancestor`). `branch` is parsed from the merge subject `Merge branch '<b>'`; `head` = second parent; `base` = `git merge-base <first parent> <head>`. Not merged → `merge: null`, branch from `--branch <b>` if given else the branch whose tip contains the plan commit (`git branch --contains`), head = its tip.
- [ ] `outcome` from `--outcome` text: first word mapped (`merged`→merged, `mr`→mr, `kept`→kept, `failed`→failed); with no `--outcome`, `merged` when `merge` is set else `kept`.
- [ ] Size: `tasks` = number of tasks in the plan's `.tasks.json`; `tiers` counts by `modelTier`; `declared_files`, `touched_files`, `diff_lines` (from `git diff --numstat base..head`, binary `-` counts 0) per Global Constraints exclusions.
- [ ] Ledger fields per **M-ledger**; ledger missing → those fields null + named in `missing`. Against the remote-access fixture: `fix_rounds` equals `grep -c 'fix round' <fixture>` (assert by computing the grep in the test, not by a hard-coded number), `rulings` = `grep -c '^Ruling:'`.
- [ ] `manifest` per **M-manifest**; on the remote-access tasks fixture `declared` equals the size of the union of its tasks' `files` minus `docs/superpowers/` paths.
- [ ] `stale_base`: `git merge-tree --write-tree --merge-base=<base> <batch base> <head>`; exit 0 → `{"result":"clean","paths":[]}`, exit 1 → `{"result":"conflict","paths":[conflicted paths from the --name-only output]}`; any other failure → `null` + `missing`. Batch base = the batch line's `base` (backfill batch: the first parent of the merge).
- [ ] Reserved fields present and `null`: `manifest_tokens, lock_wait_s, lock_wait_cause, repair_runs, integration_s, integration_tokens`.
- [ ] Fixture repo in the test: `main` with a base commit, branch A (merged, has a plan file naming spec A and a tasks.json), branch B crafted to conflict textually with a later `main` commit (stale_base `conflict`, path listed) — mutation: return `clean` unconditionally → the conflict test fails.
- [ ] A spec with no plan and no branch gives a record with identity, outcome and time fields only, all others null and in `missing`.

**Verify:** `python3 -I -m unittest discover -s board/tests -p 'test_metrics_record_git.py'` → `OK`

**Steps:**

- [ ] **Step 1:** Copy the two fixtures; write failing tests for every criterion (scratch repos built in `setUp` with `git -c user.name=t -c user.email=t@t commit`).
- [ ] **Step 2:** Probe once in zsh that this git prints conflicted paths: in a scratch repo, `git merge-tree --write-tree --name-only --merge-base=<b> <x> <y>; echo rc=$?` → rc=1 and the tree OID line then the path. Note the exact output layout in a comment above the parser.
- [ ] **Step 3:** Implement; tests green; commit `feat(metrics): run record from git, plan and ledger`.

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_record_git.py", "board/tests/fixtures/metrics/remote-access-progress.md", "board/tests/fixtures/metrics/remote-access.tasks.json"], "verifyCommand": "python3 -I -m unittest discover -s board/tests -p 'test_metrics_record_git.py'", "acceptanceCriteria": ["plan lookup by Spec header", "branch/merge/base/head from first-parent merges", "outcome mapping", "size fields with docs/superpowers excluded", "ledger fields per M-ledger, missing when absent", "manifest precision/recall", "stale_base clean/conflict/null", "reserved fields null", "no-plan record"], "modelTier": "standard"}
```

---

### Task 3: `record` — budget, time, questions, handoffs; the `record` command

**Goal:** The usage-index half of the record (spec §3 Budget and Time, `questions`, `handoffs`) and the `metrics record` subcommand that merges both halves and appends the line.

**Files:**
- Modify: `board/metrics.py`
- Create: `board/tests/test_metrics_record_usage.py`

**Acceptance Criteria:**
- [ ] Attribution per **M-attr**, window per **M-window**, active minutes per **M-active**; `tokens`, `usd`, `unpriced_calls`, `by_role` (`lead`/`agents`: `{tokens, usd}`), `lead_share` (lead tokens / total, null when total 0), `by_model` (tokens), `lead_shared`.
- [ ] Time: `ready_at` = batch line `at`; `started_at`/`ended_at` = window; `wait_s = started_at − ready_at`; `elapsed_s = ended_at − started_at`; `active_min`; `agents_active_min`.
- [ ] `limits`: `{"start": <start line's limits or null>, "record": <freshest tap's five_hour/seven_day percentages or null>}`.
- [ ] `questions`: count of `tool_use` blocks named `AskUserQuestion` in lead transcript lines (files under the project slug dirs, not under `subagents/`, `agentName` absent) with timestamps inside the window. Scan only files whose mtime ≥ window start.
- [ ] `handoffs`: lines of `tc_env.lineage_dir()/<project>.jsonl` with `ts` in the window (project = repo basename unless `--project` given). Only the count is stored.
- [ ] `metrics record <spec> --batch <id> [--outcome <t>] [--usage-db p] [--no-ingest]` ingests (Global Constraints), builds static + usage halves, appends `kind:"run"`, `backfilled:false`, `window:"stamped"` when a start line exists else `"derived"`, `config` = the batch assignment's config, and prints a one-line summary `recorded <spec> <batch>: <tasks> tasks, <tokens>M tokens, <active_min> active min`.
- [ ] Tests on a sqlite built with `usage.connect(tmp)` and inserted rows: rows on the branch counted; rows in the worktree cwd counted; lead repo-root rows counted only inside the window; two overlapping specs split a shared lead row 50/50 and set `lead_shared`; an unpriced model row increments `unpriced_calls` and adds no usd (mutation: drop the `None` check → test fails); a subagent row with no agent name is an agent row, not lead (mutation: use `usage.role()` → test fails).
- [ ] `missing` lists `limits` when no tap and `questions` when no transcripts dir; the record is still written.
- [ ] No session id, agent name or absolute path in the written line (test greps it).

**Verify:** `python3 -I -m unittest discover -s board/tests -p 'test_metrics_record*.py'` → `OK`

**Steps:**

- [ ] **Step 1:** Failing tests for each criterion (insert rows as tuples in `usage.COLS` order).
- [ ] **Step 2:** Implement `attributed_rows(conn, repo, spec_ctx, window, overlapping)`, `budget(rows, prices)`, `time_fields(...)`, `count_questions(...)`, `count_handoffs(...)`, `cmd_record`.
- [ ] **Step 3:** Green; commit `feat(metrics): budget and time attribution, record command`.

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_record_usage.py"], "verifyCommand": "python3 -I -m unittest discover -s board/tests -p 'test_metrics_record*.py'", "acceptanceCriteria": ["attribution by branch, worktree, window", "even split of shared lead calls", "unpriced_calls", "lead rows exclude subagent rows", "time fields and agents_active_min", "limits start/record", "questions and handoffs counts", "record command appends run line and prints summary", "missing fields named", "no private data"], "modelTier": "standard"}
```

---

### Task 4: `report` and the batch numbers

**Goal:** `metrics report <batch>` prints the Markdown Metrics section of spec §6 step 3 with the batch numbers of spec §4.

**Files:**
- Modify: `board/metrics.py`
- Create: `board/tests/test_metrics_report.py`

**Acceptance Criteria:**
- [ ] One table row per spec (last run line per spec in the batch): outcome, tasks, tokens, tokens per task, active minutes, lead share, fix rounds, manifest recall, stale-base result.
- [ ] Throughput: accepted specs and accepted tasks (**M-accepted**) per active hour. The batch's active minutes = distinct minutes over the union of its specs' attributed rows: when no two windows overlap this is the sum of the run lines' `active_min`; when they overlap, `report` recomputes the union from the usage index (`--usage-db`) when available, else uses the sum and says `(sum, windows overlap)` on the line.
- [ ] Overlap: per pair shared declared files and shared touched files (declared/touched file lists are stored in the run line as `declared_list`/`touched_list`, repo-relative — add them in this task to the record built by Task 2), share of pairs overlapping, hot files (touched by ≥3 specs).
- [ ] Waves: greedy colouring over the touched-file conflict graph, vertices ordered by degree descending then spec path; print wave count and `specs / waves`; same from declared files beside it.
- [ ] Parallel-buildable pairs: for each pair with both `stale_base.result == clean`, apply each spec's diff onto the batch base without checkout (`git merge-tree --write-tree --merge-base=<base_i> <batch base> <head_i>` → tree T_i, same for j), then `git merge-tree --write-tree --merge-base=<batch base> T_i T_j` (tree arguments: probe once that this git accepts trees, and if it refuses, set the field to null and list it in `missing`); share of clean pairs plus the conflicting paths of the others; a `conflict` stale-base spec conflicts with every other. Under the table print exactly: `These numbers see textual conflicts only. Two specs that merge cleanly can still be wrong together.`
- [ ] Limits at the batch's start (first start line) and end (last run line's `limits.record`).
- [ ] Lists records excluded (and why), the malformed-line count, and failed metrics commands. For the last, `main()`'s error wrapper also appends a `kind:"error"` line (`{kind:"error", sub, reason, at}`; reason must not contain absolute paths — replace the repo root with `.` and `$HOME` with `~`) and list errors dated within the batch's span.
- [ ] For a batch whose configs include a non-baseline config, appends `compare <config>`'s output (Task 5 provides `compare_text`; until it exists call it guarded with `getattr`).
- [ ] Last line: `status_line(repo)` output when `docs/superpowers/metrics/roadmap` exists (Task 5 provides it; guard the same way).
- [ ] Tests on a fixture repo with three specs: one pairwise textual conflict (pair listed as conflicting with its path), one non-conflicting pair, hot-file detection with three specs touching one file, wave count 2 for a triangle-free conflict pair; mutation: skip the pairwise merge and call every pair clean → the conflict test fails.

**Verify:** `python3 -I -m unittest discover -s board/tests -p 'test_metrics_report.py'` → `OK`

**Steps:**

- [ ] **Step 1:** Probe: in a scratch repo, `git merge-tree --write-tree --merge-base=<tree> <tree> <tree>; echo rc=$?` with tree OIDs — record whether trees are accepted (comment in code).
- [ ] **Step 2:** Failing tests, implement, green, commit `feat(metrics): batch report with overlap, waves and parallel pairs`.

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_report.py"], "verifyCommand": "python3 -I -m unittest discover -s board/tests -p 'test_metrics_report.py'", "acceptanceCriteria": ["per-spec rows", "throughput with union or stated sum", "overlap and hot files", "waves from touched and declared", "parallel-buildable pairs with textual-only sentence", "limits start/end", "excluded, malformed and error lines listed", "compare and status hooks", "fixture conflict test with mutation"], "modelTier": "standard"}
```

---

### Task 5: `compare`, gates and roadmap `status`

**Goal:** The decision rule (spec §5), the gate evaluator, and `metrics status` (spec §6 Roadmap status).

**Files:**
- Modify: `board/metrics.py`
- Create: `board/tests/test_metrics_decide.py`

**Acceptance Criteria:**
- [ ] `compare <config>`: normalised numbers per **M-norm**; index = median(challenger) / median(baseline) per target metric; baseline = every last-run line whose config file has `baseline: true` (backfilled included); exclusions (missing/zero tokens, active_min or tasks; outcome failed/kept) counted and printed.
- [ ] Verdict rules 1–5 in the spec's order, exactly as worded there (`too early`, `kill or adjust`, `replace`, `weak evidence`, `continue`), with the quality veto (failed specs, escaped defects within 14 days of the spec's `ended_at`, fix waves: challenger count > baseline rate × challenger spec count + 1).
- [ ] Permutation test: one-sided on `log` of the normalised number, statistic = mean(challenger log) − mean(baseline log), p = share of splits with statistic ≤ observed (for a `max` target; ≥ for `min`); exact enumeration when `comb(n+m, m) ≤ 200000`, else 20,000 random splits with `random.Random(0)`. Batch targets (`throughput`): target met in every challenger batch.
- [ ] `compare` prints, under its verdict, the stated limit: `With this spread, a 2x effect shows after about 4 specs per configuration, 1.5x after about 9, and 20% needs about 30; differences under about 1.5x are not decidable this way.`
- [ ] No baseline records → `metrics: compare: no baseline records`, exit 1.
- [ ] `gate <id>`: `compare` gates (pass on `replace`, fail on `kill or adjust`, else too early) and `conditions` gates (`min_specs`, `where: {"has": field}`, `agg` ∈ `median|ratio_of_sums|last`, condition-level `where`, dotted metric paths, `a/b` ratio paths); prints `gate <id>: pass|fail|too early` then one line per condition `<metric> <value> (min|max <t>) pass|fail`; exit 0 pass, 1 fail, 3 too early; missing gate file → `metrics: gate: no gate file <id>` exit 1.
- [ ] `status`: reads `roadmap` (`<label> <path>`), the `## Status` table (columns Stage, Spec, Gate, State, Evidence, Date), picks the first row whose State is not `passed`, the next gate (that row's, else the next row's that has one), prints `<label>: stage <n> <state>, next gate <id>: <conditions summary> <result>` or `… : no gate file`; no roadmap → prints nothing, exit 0.
- [ ] Tests: one synthetic run log per verdict (`too early`; `kill or adjust` by index; `kill or adjust` by veto; `replace`; `continue`; `weak evidence`) — each asserts the verdict word; compare gate and conditions gate each for pass/fail/too early with exit codes 0/1/3; status against a fixture table (first not-passed row, `no gate file`, no roadmap → empty output). Mutation: make the veto always false → the veto test fails.

**Verify:** `python3 -I -m unittest discover -s board/tests -p 'test_metrics_decide.py'` → `OK`

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_decide.py"], "verifyCommand": "python3 -I -m unittest discover -s board/tests -p 'test_metrics_decide.py'", "acceptanceCriteria": ["index and exclusions", "five verdict rules in order", "quality veto", "permutation test exact/sampled", "stated limit printed", "no baseline error", "gate evaluator compare/conditions with exit codes", "status line from roadmap table", "one test per verdict, mutation on veto"], "modelTier": "standard"}
```

---

### Task 6: `backfill`, the real-state check and privacy sweep

**Goal:** `metrics backfill [--since <date>]` writes the baseline `run` lines of spec §7, verified against the appendix on this repo's real history.

**Files:**
- Modify: `board/metrics.py`
- Create: `board/tests/test_metrics_backfill.py`, `docs/superpowers/metrics/runs.jsonl` (the real backfill output, committed)

**Acceptance Criteria:**
- [ ] Backfill: every first-parent merge on `main` since `--since` (default `2026-11-04`) whose branch has a plan in `docs/superpowers/plans/` (plan found by matching the branch's commits that add a plan file) → a `run` line with `batch:"backfill"`, `config:"seq-sdd"`, `backfilled:true`, `window:"derived"` (**M-window**), outcome `merged`; skips a spec that already has a run line in any batch; `queue-followups` (no merge commit) is naturally absent.
- [ ] Unit test on a fixture repo with two merges: windows chain (second starts at the first's merge time), re-running backfill appends nothing (mutation: drop the skip → the test fails).
- [ ] Real-state test (read-only on the real repo `git rev-parse --show-toplevel` of the test file's checkout, usage DB = the Task 1 snapshot; SKIP with a printed reason when the snapshot is absent or holds no rows before 2026-11-05): run backfill into a temp copy of the run-log path (`--log <tmp>` option) and check: 12 records whose spec basenames are the appendix's (overnight-queue … remote-access); sum of `tokens.total` within 2% of 588.4M; sum of `usd` within 2% of $199.01; sum of `active_min` within 2% of 599. If a total misses, print each spec's value beside the appendix row so the diff is visible; do NOT loosen the 2%. If, after fixing real attribution bugs, a total still misses because the appendix's method differs, report it to the lead with the per-spec table instead of changing the test.
- [ ] The committed `runs.jsonl` is the real backfill output on this repo (run against the snapshot) — 12 lines — plus nothing else.
- [ ] Privacy sweep test: over every run-log line written by all `test_metrics_*` tests' temp logs and the committed `runs.jsonl`, uncapped: no `/Users/`, no `os.path.expanduser('~')`, no UUID-shaped string (`[0-9a-f]{8}-[0-9a-f]{4}-`); prints `checked <n> lines` with n > 0.

**Verify:** `python3 -I -m unittest discover -s board/tests -p 'test_metrics_*.py' -v 2>&1 | tail -5` → `OK` (skips allowed only for the real-state test, with its reason printed)

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_backfill.py", "docs/superpowers/metrics/runs.jsonl"], "verifyCommand": "python3 -I -m unittest discover -s board/tests -p 'test_metrics_*.py' -v 2>&1 | tail -5", "acceptanceCriteria": ["backfill run lines with derived windows", "skip already-recorded specs", "real-state: 12 records, tokens/usd/active_min within 2% of appendix", "committed runs.jsonl is the real output", "privacy sweep uncapped with count"], "modelTier": "standard"}
```

---

### Task 7: Queue-mode rules and the lead's post-merge steps

**Goal:** `claude/orchestrator.md` Queue mode carries the four additions of spec §6; the handoff skill notes the batch id.

**Files:**
- Modify: `claude/orchestrator.md` (Queue mode steps 1, 2, 5), `claude/plugin/skills/handoff/SKILL.md` (one clause: `metadata.queue.batch` rides in State of the work)

**Acceptance Criteria:**
- [ ] Step 1 gains: after the answers are written, `tmux-ctl metrics batch start --config seq-sdd <specs>`; the printed batch id goes into each queued task's `metadata.queue.batch`; a spec queued later joins the batch (no second `batch start`; its `start` line names the batch); a lead in Queue mode whose pending tasks have no `metadata.queue.batch` runs `metrics batch start` for the pending specs before the next one.
- [ ] Step 2 gains: `tmux-ctl metrics start <spec> --batch <id>` before `writing-plans`; `tmux-ctl metrics record <spec> --batch <id> --outcome <outcome>` after `finishing-a-development-branch` (and for a failed spec after its outcome is written); the lead commits `docs/superpowers/metrics/runs.jsonl` alone on `main`, path-scoped, `docs(metrics): <spec basename>`; when the live checkout is mid-change it stays uncommitted until the report. Measurement never fails a spec: a failing metrics command is noted and the run goes on.
- [ ] Step 5 gains: a **Metrics** section = output of `tmux-ctl metrics report <batch>`; after it, update the roadmap document's Status table (state, evidence, date) for every stage whose spec ran in this queue, committed with the report.
- [ ] Wording follows the file's style (short sentences, imperative, one rule per sentence); no other section changed. `grep -c 'tmux-ctl metrics' claude/orchestrator.md` ≥ 4.
- [ ] Suites of CLAUDE.md Commands: no new failures beyond the known ones (Global Constraints); zsh suite run via `tmux-ctl run tests "zsh tools/tests/run-all.zsh; echo rc=\$?"` from the worktree (`-C <worktree>`), verdict from rc plus `grep -c FAIL`.

**Verify:** `grep -c 'tmux-ctl metrics' claude/orchestrator.md` → a number ≥ 4

```json:metadata
{"files": ["claude/orchestrator.md", "claude/plugin/skills/handoff/SKILL.md"], "verifyCommand": "grep -c 'tmux-ctl metrics' claude/orchestrator.md", "acceptanceCriteria": ["step 1 batch start + metadata.queue.batch + late join + pending-without-batch rule", "step 2 start/record/commit rules", "step 5 Metrics section + roadmap Status update", "style kept, nothing else changed", "full suites: no new failures"], "modelTier": "mechanical"}
```

---

### After the merge (lead, not a task)

1. `tmux-ctl metrics backfill` on `main` — records this spec's own run (no start line → derived window); commit `docs(metrics): queue-metrics`.
2. Pending queue specs have no `metadata.queue.batch`: run `tmux-ctl metrics batch start --config seq-sdd <pending spec paths>` and write the id into each pending `Plan & run:` task's `metadata.queue.batch`.
3. Hand off to a fresh lead with `agent-board:handoff` (Queue mode: relays without asking), so the new rules take effect.
