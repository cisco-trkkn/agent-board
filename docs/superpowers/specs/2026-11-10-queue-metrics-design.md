# Queue metrics: measuring spec runs on real work

Date: 2026-11-10 · Sub-project 1 of `docs/superpowers/specs/2026-11-10-pcee-decomposition.md`
Related: `claude/orchestrator.md` (Queue mode), `board/usage.py`, `docs/superpowers/reports/2026-11-05-queue.md`,
`~/.claude/skills/subagent-driven-development-extras/SKILL.md` (ledger archive)

## Problem

The user wants to replace the sequential, lead-run queue with a concurrent execution engine (PCEE), in six
sub-projects with four kill-or-adjust checkpoints. Nothing today can say whether a new way of running specs is
better than the current one:

1. **No record per spec.** What a spec cost, how long it took and how it ended is spread over the usage index,
   git, the ledger and the morning report. The usage index lives under the temporary directory
   (`$TMPDIR/tmux-ctl-<uid>/usage.sqlite`) and transcripts expire, so the numbers of past runs can disappear.
2. **No comparison.** Nothing records which way of running (configuration) ran a spec, and nothing compares two
   configurations.
3. **No data on PCEE's premises.** Whether declared file sets are accurate, how much specs overlap, and how many
   could have been built in parallel is unmeasured.

The user decided to measure on real work only: no frozen replays and no dedicated benchmark runs.

## Decisions

- **Real work only.** Real queues run under named configurations; the run log compares them. No extra tokens.
- **Run log committed in the repo**, written by code at the end of each spec (`tmux-ctl metrics record`).
- **The unit of comparison is the batch**: a set of specs run under one configuration. Code assigns specs to
  configurations when a queue is split.
- **Metrics** include escaped defects (a manual command) and, from now on, what PCEE will be judged on: manifest
  accuracy, overlap, waves under exclusive file locks, stale-base sensitivity.
- **Normalise per task. Replace at 8 or more challenger specs over 2 or more batches. Large effects only.**
- **Queue order:** this spec runs first in the queue of 2026-11-10. Every spec after it, fast-test-suite
  included, is measured live under `seq-sdd`; only the earlier specs are backfilled.

## Design

### 1. Run log and configurations

- **Run log:** `docs/superpowers/metrics/runs.jsonl` in the project's repo, one JSON object per line, append-only.
  Line kinds, in a `kind` field: `batch`, `start`, `run`, `defect`.
- **Materialised, not queried:** a `run` line holds the computed numbers. Readers never recompute them from the
  usage index.
- **Superseding:** recording the same spec in the same batch again appends a new `run` line. Readers take the
  last `run` line per `(batch, spec)`.
- **Nothing private:** numbers, repo-relative paths, commit ids, configuration and batch ids, and the defect
  text. No session ids, prompts, agent names or absolute paths: the repo may be a client's and pushed.
- **Configurations:** `docs/superpowers/metrics/configs/<id>.md`. Prose says what differs from baseline; one
  fenced block tagged `json:config` holds the machine-read part:

      {"id": "seq-sdd", "baseline": true}
      {"id": "engine-c1", "baseline": false, "targets": [{"metric": "tokens_per_task", "max": 1.0}]}

  `targets` are the thresholds of the checkpoint the configuration is tested for (`max` or `min`, as a ratio to
  baseline). This spec ships `seq-sdd.md` only: today's queue (lead on Opus, SDD with the extras, one spec at
  a time, merge per spec).
- **Batch id:** `<YYYY-MM-DD>-<n>`, the batch's start date and a counter per day.

### 2. Commands

`board/metrics.py` holds the logic as functions over git, the plan's tasks file, the archived ledger and the
usage index. `tmux-ctl metrics <sub>` runs it the way `tmux-ctl overview` runs `board/overview.py`. All commands
act on the repo of the current directory.

| Command | Does |
| --- | --- |
| `metrics batch start --config <id> [--config <id2>] [--group "<spec>,<spec>"]… <spec>…` | Appends a `batch` line with the batch id, the batch base (`main`'s commit now), the configuration ids and the assignment of each spec; prints the batch id and the assignment. |
| `metrics start <spec> --batch <id>` | Appends a `start` line: time, `main`'s commit, the 5-hour and 7-day limit percentages. |
| `metrics record <spec> --batch <id> [--outcome <text>]` | Computes and appends the `run` line (section 3). |
| `metrics defect <spec> "<what>"` | Appends a `defect` line with the date. |
| `metrics report <batch>` | Prints the Markdown Metrics section (section 6). |
| `metrics compare <config>` | Prints the index and the verdict of the decision rule (section 5), with its inputs. |
| `metrics backfill [--since <date>]` | Writes `run` lines for specs already merged (section 7). |
| `metrics gate <id>` | Evaluates a gate file and prints `gate <id>: pass`, `fail` or `too early` with each condition's value and threshold (section 5). Exit 0, 1, 3. |
| `metrics status` | Prints the one-line roadmap status (section 6). |

- `<spec>` is the spec's repo-relative path. The plan is the file in `docs/superpowers/plans/` whose header names
  that spec; the branch and merge commit come from the first-parent merge on `main` after the `start` line whose
  second parent contains the plan's commit. A spec that was not merged (`failed`, `kept`) is recorded from its
  branch tip.
- **Assignment with two configurations:** specs (and `--group` units, which stay together) are sorted by
  `sha256(batch id + spec path)` and given the configurations alternately, the baseline first. Neither the lead
  nor the user chooses which spec gets the challenger.
- **Fresh index:** before reading the usage index, `record` and `backfill` run `usage.ingest` over the project's
  transcript files (incremental, safe to repeat, independent of the board).

### 3. The `run` record

Fields, grouped. A field whose source is missing is `null` and its name is added to `missing`.

- **Identity:** `batch`, `config`, `spec`, `plan`, `branch`, `base` (the branch's merge base), `head`, `merge`
  (commit or `null`), `outcome` (`merged`, `failed`, `kept`, `mr`), `backfilled` (bool), `window`
  (`stamped` when a `start` line exists, else `derived` from the plan commit or the previous merge).
- **Budget:** `tokens` (`input`, `output`, `cache_read`, `cache_write`, `total`), `usd`, `unpriced_calls`,
  `by_role` (tokens and usd for `lead` and `agents`), `lead_share` (lead tokens over total), `by_model` (tokens),
  `limits` (`five_hour` and `seven_day` percentages at start and at record, from the freshest status-line tap).
  - Attribution: calls whose branch is the spec's branch or whose directory is inside its worktree, up to the
    record time; plus, in a sequential batch, the lead's calls in the repo root between start and record. The
    lead's rows are those with no agent name that are not subagent rows.
  - In a batch where specs overlap in time, the lead's calls between a spec's start and record are divided evenly
    among the specs open at each call, and `lead_shared` is `true`.
  - `usd` is incomplete when `unpriced_calls` is above zero. Tokens are the primary budget number.
- **Time:** `ready_at` (the batch start), `started_at`, `ended_at`, `wait_s`, `elapsed_s`, `active_min` (minutes
  with at least one attributed call), `agents_active_min` (`{"0": n, "1": n, "2+": n}` over the window's minutes).
- **Size:** `tasks`, `tiers` (`mechanical`, `standard`, `frontier` counts), `declared_files`, `touched_files`,
  `diff_lines` (added plus deleted). Touched files and diff lines exclude `docs/superpowers/`.
- **Quality and rework** (from the archived ledger `docs/superpowers/ledgers/<plan-basename>/progress.md`):
  `bounces`, `fix_rounds`, `final_findings`, `fix_wave` (bool), `rulings`, `parked`; `questions` (AskUserQuestion
  calls in the lead's transcripts inside the window); `handoffs` (lead relays inside the window, from the lineage
  log).
- **PCEE premises:**
  - `manifest`: `declared`, `touched`, `both`, `precision` (`both / declared`), `recall` (`both / touched`).
    Declared files are the union of the plan tasks' `files`; until manifests exist they stand in for write sets.
  - `stale_base`: `clean` or `conflict`, with the conflicting paths: whether the spec's diff (`base..head`)
    applies without textual conflict onto the batch base
    (`git merge-tree --write-tree --merge-base=<base> <batch base> <head>`).
- **Reserved, `null` until later stages fill them:** `manifest_tokens` (stage 2), `lock_wait_s`,
  `lock_wait_cause`, `repair_runs`, `integration_s`, `integration_tokens`.

### 4. Batch numbers

Derived by `report` and `compare` from the batch's `run` lines, never stored:

- **Throughput:** accepted specs and accepted tasks (outcome `merged` or `mr`) per active hour, where the
  batch's active minutes are the minutes with at least one call attributed to any of its specs.
- **Overlap:** for every pair of specs, the shared declared files and the shared touched files; the share of
  pairs that overlap; hot files (touched by three or more specs).
- **Waves under exclusive file locks:** a greedy colouring of the specs by shared touched files, most-overlapping
  first; reported as the wave count and `specs / waves`. The same number from declared files is reported beside
  it.
- **Parallel-buildable pairs:** for two specs whose `stale_base` is `clean`, both diffs are applied to the batch
  base and the two resulting trees merged with the batch base as merge base (`git merge-tree`, no checkout). The
  share of pairs without textual conflict is reported, with the conflicting paths of the others. A spec whose
  `stale_base` is `conflict` counts as conflicting with every other.
- These numbers see textual conflicts only. Two specs that merge cleanly can still be wrong together; the report
  prints that sentence under the table.
- Needs a git whose `merge-tree --write-tree` takes `--merge-base` and tree arguments (checked on git 2.54). When
  the command refuses them these fields are `null` and named in `missing`.

### 5. Normalisation and the decision rule

- **Normalised numbers:** `tokens_per_task` and `active_min_per_task` per spec. Raw per-spec and
  per-declared-file numbers are printed beside them. Only facts known before the run normalise (tasks, declared
  files, tiers); fix rounds and diff size never do, because the configuration influences them.
- **Why per task:** in the baseline (appendix) cost per spec varies eightfold and no size measure explains much
  of it. The spread that remains (standard deviation of the logarithm) is 0.38 for tokens per task, 0.45 for
  tokens per declared file and 0.9 per diff line.
- **Index:** the median of the challenger's specs' normalised numbers divided by the baseline's median. Baseline
  is every `run` line whose configuration has `"baseline": true`, backfilled ones included.
- **Excluded from an index, and counted in the output:** records with `tokens`, `active_min` or `tasks` missing
  or zero, and specs with outcome `failed` or `kept` (they count in the failed share instead).
- **Verdict** printed by `compare <config>`, the first rule that applies:
  1. `too early`: fewer than 4 challenger specs. No index verdict.
  2. `kill or adjust`: at least 8 challenger specs and either a target's index is on the wrong side of 1.0 or
     the quality veto holds.
  3. `replace`: at least 8 challenger specs over at least 2 batches; every target in the configuration met; for
     per-spec targets, a one-sided permutation test on the logarithm of the normalised number against the
     baseline specs below 0.10 (exact when the number of splits is at most 200,000, else 20,000 samples with a
     fixed seed); for batch targets (throughput), the target met in every challenger batch; no quality veto.
  4. `weak evidence`: 16 or more challenger specs without rule 2 or 3 applying. The line states which side of
     each target the index is on and that the evidence is weak; the user decides.
  5. `continue`: otherwise.
- **Quality veto:** for each of failed specs, escaped defects and fix waves, the challenger's count is above
  the baseline's rate times the challenger's spec count, plus one. Escaped defects count only `defect` lines
  dated within 14 days of the spec's end, for both sides.
- **Stated limit:** with this spread, a 2x effect shows after about 4 specs per configuration, 1.5x after about
  9, and 20% needs about 30. Differences under about 1.5x are not decidable this way; the checkpoints in the
  decomposition are set at large effects for that reason. `compare` prints this limit under its verdict.

- **Gates:** `docs/superpowers/metrics/gates/<id>.md` describes a checkpoint in prose and holds one fenced block
  tagged `json:gate`. `metrics gate <id>` evaluates it from the run log alone, so an unattended run can check it:

      {"id": "K2", "compare": "engine-c1"}
      {"id": "K1", "min_specs": 4, "where": {"has": "manifest_tokens"}, "conditions": [
        {"metric": "manifest.recall", "agg": "median", "min": 0.9},
        {"metric": "analysis.parallelism", "agg": "last", "min": 1.5},
        {"metric": "manifest_tokens/tokens.total", "agg": "ratio_of_sums", "max": 0.10}]}

  - A `compare` gate passes on the verdict `replace`, fails on `kill or adjust`, and is `too early` otherwise.
  - A `conditions` gate takes the last `run` line per `(batch, spec)` that has the `where` field, is `too early`
    below `min_specs`, and passes when every condition holds. `agg` is `median`, `ratio_of_sums` (sum of the
    numerator over sum of the denominator) or `last` (the newest `analysis` line's value).
  - This spec ships the evaluator and no gate files. Each stage's spec adds its gate file and the fields it reads
    (`manifest_tokens` and the `analysis` line kind come with stage 2).

### 6. Queue mode and the morning report

Four additions to Queue mode in `claude/orchestrator.md`: three numbered here, the fourth under Roadmap status.
The file has an uncommitted edit of the user's; the plan carries it across as Queue mode's own rule says (a
dry-run-checked patch).

1. Step 1, after the answers are written: `tmux-ctl metrics batch start --config seq-sdd <specs>`; the batch id
   goes into each queued task's `metadata.queue.batch`, so a handoff carries it. A spec queued later joins the
   batch (`metrics batch start` is not run again; its `start` line names the batch).
2. Step 2: `tmux-ctl metrics start <spec> --batch <id>` before `writing-plans`; `tmux-ctl metrics record <spec>
   --batch <id> --outcome <outcome>` after `finishing-a-development-branch` (and for a failed spec, after its
   outcome is written). The lead commits the run log by itself on `main`, path-scoped:
   `docs(metrics): <spec basename>`. When the live checkout is mid-change it stays uncommitted until the report.
3. Step 5: the morning report gains a **Metrics** section, the output of `tmux-ctl metrics report <batch>`:
   - one row per spec: outcome, tasks, tokens, tokens per task, active minutes, lead share, fix rounds,
     manifest recall, stale-base result;
   - the batch numbers of section 4;
   - the limit percentages at the batch's start and end;
   - records excluded and metrics commands that failed;
   - for a challenger configuration, the output of `compare`;
   - last, when the repo has a roadmap, the output of `tmux-ctl metrics status`, one line.

**Roadmap status.** `docs/superpowers/metrics/roadmap` is one line, `<label> <repo-relative path>`, naming a
document with a `## Status` table of the columns Stage, Spec, Gate, State, Evidence, Date. In this repo:
`PCEE docs/superpowers/specs/2026-11-10-pcee-decomposition.md`. `metrics status` prints

    PCEE: stage 2 running, next gate K1: manifest.recall 0.84 (min 0.9), analysis.parallelism 1.7 (min 1.5), … fail

- The stage shown is the first row whose state is not `passed`; the next gate is that row's gate, or the next
  row's that has one.
- After the colon comes `metrics gate <id>`'s result: each condition's value and threshold and `pass` or `fail`,
  or `too early`, or `no gate file` when `gates/<id>.md` does not exist.
- A repo with no roadmap file prints nothing, and the report has no such line.

A fourth addition to the lead rules, in the morning-report step: after writing the Metrics section, update the
roadmap document's Status table (state, evidence, date) for every stage whose spec ran in this queue, and commit
it with the report.

The handoff skill's State of the work already lists `metadata.queue`; the batch id rides in it.

### 7. Baseline and the queued specs

- `metrics backfill` writes `run` lines (`backfilled: true`, `window: derived`, batch `backfill`) for every
  first-parent merge on `main` since `--since` (default 2026-11-04) whose branch has a plan in
  `docs/superpowers/plans/`. Window: from the previous such merge (the first one: from the plan's commit) to the
  merge. It skips a spec that already has a `run` line.
- Backfill runs in the plan's first task: the usage index may not survive a reboot. The appendix holds the
  numbers computed on 2026-11-10 as the fallback and as the check for the real-state test.
- Not in the backfill: `queue-followups` (merged without a merge commit). Known gap: Fable 5.2 is unpriced, so
  `usd` understates runs that used it; tokens are complete.
- **Order in the queue of 2026-11-10:** this spec first. Then `fast-test-suite`, `telegram-fixes`,
  `restart-recovery`, `queue-reliability` and `interactive-tasks-window` are recorded live under `seq-sdd`.
  Only this spec's own run and the earlier specs are backfilled.
- **Relation to those specs:** all five are independent of this one. `interactive-tasks-window` keeps a history
  journal of task transitions in the state directory, for display; the run log holds per-spec measurements in
  the repo, for decisions. Neither reads the other.

## Error handling

- Measurement never stops or fails a spec. A `metrics` command that fails prints one line
  (`metrics: <sub>: <reason>`) and exits non-zero; the lead goes on and the morning report lists the failure.
- A missing source (no ledger, no tasks file, no `start` line, no limit reading, a git without the needed `merge-tree`) leaves its
  fields `null` and names them in `missing`. `record` still writes the line.
- A malformed run-log line is skipped by every reader and counted in `report`'s output.
- `record` for a spec with no plan and no branch (it failed before planning) writes identity, outcome and time
  fields only.
- `compare` with no baseline records prints `metrics: compare: no baseline records` and exits 1.

## Testing

- **Unit, on fixtures:** a scratch git repository with merged branches, one crafted textual conflict against the
  batch base and one crafted pairwise conflict (for `stale_base`, parallel-buildable pairs, overlap and waves);
  a small usage database built with `usage.connect` and inserted rows (attribution by branch, worktree and
  window; the even split of shared lead calls; `unpriced_calls`); a copy of a real archived ledger and tasks
  file (`docs/superpowers/ledgers/2026-11-09-remote-access/progress.md` and its plan's `.tasks.json`) for
  bounces, fix rounds, findings, declared files and tiers.
- **Gates and status:** a `compare` gate and a `conditions` gate, each for pass, fail and too early, with the
  exit codes; `metrics status` against a fixture Status table (first not-passed row, `no gate file`, no roadmap).
- **Decision rule:** one synthetic run log per verdict (`too early`, `kill or adjust` by index, `kill or adjust`
  by veto, `replace`, `continue`, `weak evidence`), and the assignment (deterministic, groups kept together,
  alternating from the baseline).
- **Robustness:** missing sources give `null` plus `missing`; a malformed line is skipped; re-recording
  supersedes; every command's failure is one line and a non-zero exit.
- **Privacy:** an uncapped grep of a run log produced by the tests and by the real backfill finds no session id
  (UUID shape), no `/Users/` and no home path.
- **Real state:** `metrics backfill` on this repo gives the 12 records of the appendix; total tokens, total
  priced cost and total active minutes each within 2% of the appendix totals when the usage index still holds
  those days (the test is skipped, and says so, when it does not).
- **Full suite:** when this spec runs, `main` has five known failing test files (`test_orchestrator_path`,
  `test_restart_orchestrator`, `test_session_path`, `test_session_root_path`, `tools/tests/test_prompt_argv.zsh`)
  and no single runner (`tools/tests/all.zsh` comes with fast-test-suite). Acceptance on the suites of CLAUDE.md
  Commands is: no new failures beyond those five.
- **First live use:** the specs after this one in the queue are recorded under `seq-sdd`; the morning
  report's Metrics section is the end-to-end evidence and a user gate.

## Out of scope

- A board panel for metrics.
- Any replay harness or dedicated benchmark run.
- Prices for unpriced models (follow-up: Fable 5.2 in the prices file).
- Semantic-conflict detection.
- Everything in sub-projects 2 to 6 of the decomposition; their reserved fields stay `null`.

## Appendix: baseline computed on 2026-11-10

From the usage index, `git log --merges --first-parent main` and the archived ledgers, with the attribution of
section 3 and derived windows. Elapsed minutes include sleep and the four-day limit stall; active minutes do not.

| Spec | Tasks | Declared files | Touched files | Diff lines | Fix rounds | Elapsed min | Active min | Priced $ | Lead % of $ | Tokens (M) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overnight-queue | 2 | 4 | 4 | 92 | 3 | 34 | 34 | 11.39 | 59 | 33.5 |
| mod-agent-status | 4 | 10 | 10 | 1080 | 18 | 663 | 112 | 44.76 | 53 | 103.3 |
| mod-team-band | 2 | 6 | 7 | 1321 | 3 | 38 | 36 | 11.65 | 52 | 29.1 |
| mod-usage-gauges | 3 | 12 | 11 | 1946 | 5 | 92 | 40 | 10.74 | 48 | 34.5 |
| tasks-window-polish | 5 | 6 | 5 | 522 | 0 | 33 | 33 | 11.81 | 55 | 33.0 |
| artifact-session-id | 2 | 4 | 5 | 60 | 0 | 42 | 19 | 5.73 | 64 | 20.3 |
| mod-shell-hooks | 6 | 19 | 19 | 1688 | 8 | 5654 | 64 | 23.12 | 48 | 66.3 |
| mod-overview | 4 | 16 | 24 | 862 | 4 | 40 | 40 | 14.45 | 53 | 48.3 |
| queue-keep-awake | 4 | 6 | 15 | 661 | 1 | 45 | 42 | 16.85 | 56 | 46.6 |
| lead-named-agents | 5 | 11 | 11 | 167 | 0 | 29 | 26 | 9.63 | 72 | 30.0 |
| relay-launch-check | 5 | 8 | 8 | 191 | 3 | 41 | 39 | 9.90 | 74 | 41.3 |
| remote-access | 7 | 13 | 29 | 1397 | 15 | 349 | 114 | 28.98 | 57 | 102.2 |

Totals: 49 tasks, 599 active minutes, $199.01 priced, 588.4M tokens. Per spec: 50 active minutes, 49M tokens,
median $11.73. Accepted tasks per active hour: 4.9. The Lead % column is by priced cost; the record's
`lead_share` is by tokens.

Fix rounds count the ledger lines containing `fix round`. Remote-access's row ends at its merge
(2026-11-10 03:00Z) and so includes both its failed queue run and the N1 fix that followed.

Overlap for the 13 plans of that period (these 12 and queue-followups), by declared files: 36 of 78 pairs share
a file; a greedy colouring gives 7 waves. On the five specs merged on 2026-11-09 after mod-shell-hooks, four
apply cleanly onto the `main` that stretch started from and remote-access does not.
