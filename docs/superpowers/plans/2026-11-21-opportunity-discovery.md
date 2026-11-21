# Opportunity Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A nightly job collects work signals per project, has a model rank the top 5, and posts them to the project's Discord home channel with "File as idea" / "Dismiss" buttons; it never acts by itself.

**Architecture:** Code-only signal collectors (`board/discover_tests.py`, `board/discover_repo.py`) feed `board/discover.py` (collect, rank through `claude -p`, nightly loop, metrics). `board/discover_post.py` owns the state file, the selection rules, the post and the click handler. `tools/tests/all.zsh` gains a per-run test history file, because the run records hold no test ids or HEAD. A LaunchAgent (`board/discover_schedule.py`) runs `tmux-ctl discover nightly` at 07:00.

**Tech Stack:** Python 3 stdlib (board/), zsh (bin/tmux-ctl, tools/tests/all.zsh), Node (tools/discord-bridge), launchd.

**Spec:** `docs/superpowers/specs/2026-11-12-opportunity-discovery-design.md`

## Global Constraints

- **Candidate shape** (every collector returns a list of these; `discover.collect` adds nothing to them):
  `{"signal": str, "key": str, "title": str, "evidence": [{"text": str, "path": str|None, "line": int|None, "url": str|None}], "first_seen": "YYYY-MM-DD", "count": int}`.
  `key` starts with `<signal>:` and is stable for the same underlying finding across nights. `evidence` holds at most 20 items, newest last. **Evidence count** (the number the dismissal rule compares) is `count`, defined per signal below, never `len(evidence)`.
- **Signal definitions** (window = the 30 days before `now` unless stated):
  - `flaky_test`: from the test history file. A job with results both `rc == 0` and `rc != 0` on the same `head` with `dirty == false` in both, OR ≥ 2 pass/fail flips in its chronological results within one `root`. `count` = number of failing results in the window. Key `flaky_test:<job name>`.
  - `slow_test`: full runs only (`full == true`). Current = median secs of the job's last 3 full runs; baseline = median secs of its full runs in the first 7 days of the window. Candidate when the job is in the slowest 5 by current AND has a baseline AND current ≥ 1.25 × baseline. `count` = round(100 × (current − baseline) / baseline) (percent growth). Key `slow_test:<job name>`.
  - `failed_run`: from `tc_env.state_dir()/runs-<project>.jsonl`. Final record per `id` (the last line with a non-null `exit`). Its rc = the last `^rc=(\d+)$` line of its `log` when that file is readable, else `exit`. "On main" = the record's `cwd` resolves to the project root itself (not a path under it). Candidate when rc ≠ 0, `ts ≤ now − 24h`, no rc-0 run of the same `cmd` in the same cwd within `ts .. ts+24h`, and the latest run of that `cmd` there is not rc 0. `count` = failing runs of that cmd in the window. Key `failed_run:<sha1(cmd)[:10]>`.
  - `repeated_ruling`: `Ruling:` lines in `<root>/docs/superpowers/ledgers/*/progress.md`. Normalise: text after `Ruling:`, cut at ` — cost if wrong` (or ` - cost if wrong`), lowercase, words = `[a-z0-9]+`. Group A: same first 6 words. Group B: same first cited path (regex `[\w./-]+\.(py|zsh|js|md|sh|json)`) and same first 3 words. Candidate when a group spans ≥ 3 distinct ledger dirs; a ruling line counts in at most one candidate (A groups first). `count` = distinct ledger dirs. Key `repeated_ruling:<words joined by ->` (A) or `repeated_ruling:<path>:<3 words joined by ->` (B).
  - `deferred_minor`: ledger lines matching `(?i)\b(deferred|parked)\b` that cite a path (same regex) existing at HEAD. Candidate when `git log --since=<ledger date> -- <path>` (ledger date = the `YYYY-MM-DD` prefix of its dir name) shows a commit not mentioned in that ledger AND no line in any ledger dated later contains the same path and the word `fix`/`fixed`. `count` = commits touching the path since the ledger date. Key `deferred_minor:<ledger dir>:<sha1(line)[:8]>`.
  - `todo`: `git log -p --since=30.days --no-merges -U0` additions (`+` lines, not `+++`) matching `\b(TODO|FIXME|XXX)\b` in files not ending `.md`, whose stripped text is still a line of `git show HEAD:<path>`. `count` = 1. Key `todo:<path>:<sha1(stripped line)[:8]>`. `first_seen` = the adding commit's date.
  - `dependency`: GitHub remote + `gh auth status` exit 0 → `gh api 'repos/<owner>/<repo>/dependabot/alerts?state=open&per_page=100'`; any non-zero exit → skipped with the first stderr line. `npm audit --json` in each dir of a tracked `package-lock.json` (timeout 120 s); `pip-audit -f json` only when `pip-audit` is on PATH and a tracked `requirements*.txt` exists. Severity ≥ moderate. `count` = 1. Keys `dependency:github:<alert number>`, `dependency:npm:<dir>:<package>`, `dependency:pip:<package>:<vuln id>`.
  - `stale_idea`: `ideas.load(project)` entries with `status == "open"` and `ts` older than 30 days. `count` = age in days. Key `stale_idea:<sha1(idea key)[:12]>`.
- **Test history file:** `${TC_STATE:-$HOME/.local/state/agent-board}/tests/history.jsonl` (Python: `tc_env.agent_base() / "tests" / "history.jsonl"`), one line per finished `all.zsh` run (an interrupted run writes nothing): `{"ts": <epoch int>, "root": "<abs root>", "head": "<sha>"|null, "dirty": bool, "full": bool, "jobs": {"<job name>": [<rc int>, <secs float>]}}`. Above 2000 lines it is cut to the last 1500.
- **State file:** `tc_env.agent_base()/discover/<project>.json`, written under `flock` on `<project>.lock` beside it, atomically (tmp + `os.replace`):
  `{"root": str, "failures": int, "reported": {key: {"first_reported": iso, "last_evidence_count": int}}, "dismissed": {key: {"at": iso, "evidence_count": int}}, "filed": {key: {"at": iso, "idea_line": str}}, "posts": {"<night>": {"key": str, "items": [...]}}}`. `posts` keeps the last 14 nights. `<night>` = local `YYYYMMDD`.
- **Selection rule (spec §3, exact):** an item is shown when its key is not in `filed`, and either not in `dismissed` or `count ≥ 1.5 × dismissed[key].evidence_count`. A shown item whose key is in `reported` with `last_evidence_count == count` and that was not regrown past a dismissal is *unchanged*: not reposted, counted in `still open: <n>`. A `repeated_ruling` item the memory run already proposed is listed as `also proposed by the memory run` and not counted as new. No new item → no post.
- **Button ids:** `ab:discover:file:<project>:<kid>` and `ab:discover:dismiss:<project>:<kid>`, `kid = sha1(key)[:12]` (a key can exceed the 100-char custom_id limit). One button row per item: `[File as idea <n> (style 1), Dismiss <n> (style 2)]`, at most 5 rows.
- **Post:** one outbox `post` op to `tc_env.discord_dir(project)`, `tier: "progress"`, `mention_user: false`, `key: "discover-<project>-<night>"`, text ≤ 1900 chars, every model-written string through `analytics_post.escape`.
- **Model step:** `claude -p --model sonnet --effort medium`, prompt `claude/discover.md`, timeout 600 s, the binary overridable by `TC_DISCOVER_CLAUDE` (tests use a fake). Tests never run the real `claude`.
- Off switches: `TC_DISCOVER=0` or `tc_env.agent_base()/discover.off`. Weekly usage guard: `dream.weekly_pct(now) >= 85` skips unless `--force`.
- No-tmux: every `tmux-ctl discover …` subcommand works outside tmux (launchd).
- Commit messages: conventional with scope (`feat(discover): …`); end with the attribution trailer your harness specifies.

**User decisions (already made):**
- Report only: the job ranks and explains; the user taps "File as idea" or "Dismiss". It never files, drafts specs or starts work by itself.
- Dismissed items do not come back unless their evidence grows.
- Queue item: integration merge to `main` locally, no push.

**Plan-time rulings (lead, recorded in the ledger):**
- The run records (`runs-<project>.jsonl`) carry neither test ids nor HEAD, so `flaky_test` and `slow_test` read a new history file written by `all.zsh` (Task 1). Cost if wrong: both signals stay empty until the file has a month of runs; nothing else depends on them.
- "On main" for `failed_run` = run in the project's own checkout (worktree runs are branches). Cost if wrong: misses failures on main run from elsewhere.
- The model gets only `Read` and answers with the rank JSON as its result text; the script writes `rank.json`. Cost if wrong: none for the user; a model that wraps JSON in a fence is unwrapped.
- Memory overlap = a proposal in the project's latest memory `report.json` whose evidence names ≥ 3 of the candidate's ledger dirs (memory proposals have no key). Cost if wrong: a duplicate post line.
- `deep links where they exist` = GitHub/GitLab https blob URLs at HEAD for evidence with a path; none otherwise.

---

### Task 1: all.zsh writes the test history file

**Goal:** Every finished `all.zsh` run appends one history line (Global Constraints, "Test history file").

**Files:**
- Modify: `tools/tests/all.zsh` (after the summary loop, before the verdict)
- Test: `tools/tests/test_all_runner.zsh`

**Acceptance Criteria:**
- [ ] A full run against the runner test's fake root appends one line with `full: true`, every job name, `[rc, secs]`, `head` = the fake root's HEAD (the test makes it a git repo with one commit), `dirty` false.
- [ ] A `--suite board` run appends a line with `full: false`.
- [ ] A run with a failing job records that job's non-zero rc and the file still gets its line (the FAIL exit path writes it too).
- [ ] A non-git root writes `head: null`.
- [ ] A file of 2001 lines is cut to 1500 lines plus the new one.
- [ ] Each new check names its mutation and the implementer's RED run shows it failing (e.g. "drop the history write → `history: full run appends one line` fails").

**Verify:** `zsh tools/tests/test_all_runner.zsh` → no `FAIL` line, exit 0

**Steps:**

- [ ] **Step 1:** Add failing checks to `tools/tests/test_all_runner.zsh` (it already runs all.zsh with `TC_TEST_ROOT=$ROOT TC_STATE=$SCR/st`; the history lands in `$SCR/st/tests/history.jsonl`). Parse lines with `python3 -c 'import json,sys; …'`. Run, see them fail.
- [ ] **Step 2:** In `all.zsh`, resolve at start `hfile="${TC_STATE:-$HOME/.local/state/agent-board}/tests/history.jsonl"` (next to `tfile`; jobs get their own TC_STATE later). After the summary loop and before either exit, write the line with one `python3 -I -c` reading `name<TAB>rc<TAB>secs` rows on stdin and argv `hfile ts root head dirty full`; `head` from `git -C "$root" rev-parse HEAD 2>/dev/null` (empty → null), `dirty` from `git -C "$root" status --porcelain --untracked-files=no` non-empty. Append under `fcntl.flock` on `hfile + ".lock"`, then cut to the last 1500 lines (tmp + `os.replace`) when the file exceeds 2000. A history write failure prints one `all.zsh: history: <error>` line to stderr and never changes the exit code.
- [ ] **Step 3:** Run the runner test; all green. Commit `feat(tests): all.zsh appends a per-run test history`.

```json:metadata
{"files": ["tools/tests/all.zsh", "tools/tests/test_all_runner.zsh"], "verifyCommand": "zsh tools/tests/test_all_runner.zsh", "acceptanceCriteria": ["full run appends one line with full true, all jobs, head, dirty false", "--suite run appends full false", "failing job rc recorded on the FAIL path", "non-git root head null", "2001 lines cut to 1500 + 1", "each check names its mutation"], "modelTier": "standard"}
```

### Task 2: test and run signals (`board/discover_tests.py`)

**Goal:** `flaky_tests`, `slow_tests` and `failed_runs` return candidates exactly as defined in Global Constraints.

**Files:**
- Create: `board/discover_tests.py`
- Test: `board/tests/test_discover_tests.py`

**Acceptance Criteria:**
- [ ] `load_history(path, now)` returns the lines in the 30-day window, skipping malformed lines; a missing file returns `[]`.
- [ ] `flaky_tests(history, now)`: triggers on same-head clean pass+fail; triggers on ≥ 2 flips within one root; does NOT trigger on one fail→pass flip, on a pass+fail where either run is dirty, or on flips split across two roots. Keys stable across calls.
- [ ] `slow_tests(history, now)`: triggers at +25 %, not at +24 %, not for a job outside the slowest 5, not without baseline runs, ignores `full: false` runs; `count` = percent growth.
- [ ] `failed_runs(records_path, root, now)`: triggers for a main-checkout failure older than 24 h with no green; not when a green of the same cmd/cwd follows within 24 h; not for a worktree cwd; not for a failure younger than 24 h; reads the `rc=` line from the log over `exit`; uses the final record per id (the `exit: null` start line is ignored).
- [ ] Every test of an absence names its mutation in a comment, and the RED run shows it failing.

**Verify:** `python3 -m unittest board.tests.test_discover_tests -v` → `OK`

**Steps:**

- [ ] **Step 1:** Fixtures as in-test data (lists of history dicts; a temp runs jsonl plus log files). Real record shape to copy (from `runs-agent-board.jsonl`): `{"id":"15107-5819","ts":1795247246,"agent":"claude","win":"tests","session":"agent-board-bg","cmd":"zsh tools/tests/all.zsh; echo rc=$?","cwd":"/…/agent-board","exit":0,"duration":484,"log":"/…/logs/agent-board/15107-5819.log","summary":""}` — the same id appears first with `"exit":null`.
- [ ] **Step 2:** Write the tests, run, see them fail (module missing, then assertions).
- [ ] **Step 3:** Implement. Signatures: `load_history(path, now) -> list[dict]`, `flaky_tests(history, now) -> list[cand]`, `slow_tests(history, now) -> list[cand]`, `failed_runs(records_path, root, now) -> list[cand]`. Evidence texts: `"<iso date> <root basename> @<head[:8]> rc=<rc>"` for test results; `"<iso> rc=<rc> <cmd[:80]>"` with `path` = the log path for runs.
- [ ] **Step 4:** Green. Commit `feat(discover): test and run signals`.

```json:metadata
{"files": ["board/discover_tests.py", "board/tests/test_discover_tests.py"], "verifyCommand": "python3 -m unittest board.tests.test_discover_tests -v", "acceptanceCriteria": ["load_history window and malformed lines", "flaky_tests trigger and non-trigger cases, stable keys", "slow_tests 25% threshold, top 5, baseline, full only", "failed_runs main-only, 24h green, rc line, final record", "absence tests name their mutation"], "modelTier": "standard"}
```

### Task 3: repo signals (`board/discover_repo.py`)

**Goal:** `repeated_rulings`, `deferred_minors`, `todos`, `dependencies` and `stale_ideas` return candidates exactly as defined in Global Constraints.

**Files:**
- Create: `board/discover_repo.py`
- Test: `board/tests/test_discover_repo.py`

**Acceptance Criteria:**
- [ ] `repeated_rulings(root)`: three ledgers with rulings sharing the first 6 normalised words → one candidate with `count` 3; two ledgers → none; same cited path + first 3 words in 3 ledgers → one group-B candidate; a line is in at most one candidate; ` — cost if wrong` tails and `Task N:` prefixes do not change the key.
- [ ] `deferred_minors(root)`: a deferred line citing a file touched by a later commit and never fixed → candidate; the same with a later ledger line `… <path> … fixed` → none; a deferred line with no path → none.
- [ ] `todos(root, now)` on a temp git repo: a TODO added 3 days ago and still present → candidate; one added and later removed → none; one added 40 days ago → none; one in a `.md` file → none; key unchanged when the line moves.
- [ ] `dependencies(root, run=…)` returns `(cands, skipped)`: fake `gh`/`npm` outputs through the injected `run`; a moderate npm vuln → candidate, a low one → none; `gh` exit 1 with `HTTP 403` → `skipped` holds `{"signal": "dependency", "why": "gh: Dependabot alerts are disabled …"}` and npm still runs; no lockfile and no remote → `([], [...])` without raising.
- [ ] `stale_ideas(project, now)` with `TC_IDEAS_DIR` at a temp dir: an open idea 31 days old → candidate; 29 days → none; a taken (`- [x]`) one → none.
- [ ] `link(root, head, path, line)` returns `https://github.com/<o>/<r>/blob/<head>/<path>#L<line>` for an https or ssh GitHub origin, the `/-/blob/` form for GitLab, `None` otherwise; collectors fill `url` with it.
- [ ] Absence tests name their mutation; RED run shown.

**Verify:** `python3 -m unittest board.tests.test_discover_repo -v` → `OK`

**Steps:**

- [ ] **Step 1:** Real formats to copy into fixtures:
  - Ruling line: `Ruling: board-suite count criterion is baseline-on-3f0b5ad + 15 (baseline measured before Task 1), not literal 482 — cost if wrong: none, the OK verdict is what matters.` and `Task 1: Ruling: fix the plan-verbatim _insert …`.
  - Deferred line: `Task 2: minor (deferred): exit-code checks assert non-zero, not literally 2` and `Task 5: parked — claude/skills/tmux-orchestrator/SKILL.md (legacy copy) lacks tmux-ctl context — Ruling: leave it; …`.
  - npm audit JSON (probe, `tools/discord-bridge`, 2026-11-21): top keys `['auditReportVersion', 'vulnerabilities', 'metadata']`; `vulnerabilities` maps package name → `{"severity": "moderate", "via": [...], "range": "...", …}`.
  - gh probe on this repo (2026-11-21): exit 1, stderr `gh: Dependabot alerts are disabled for this repository. (HTTP 403)`. An enabled repo returns a JSON list of `{"number", "state", "security_advisory": {"severity", "summary", "ghsa_id"}, "dependency": {"package": {"name", "ecosystem"}}, "html_url"}`.
- [ ] **Step 2:** Tests first (temp git repos via `git init`, `git -c user.name=t -c user.email=t@t commit`, dates via `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE`); run, see them fail.
- [ ] **Step 3:** Implement; every git/gh/npm call through `run` (default `subprocess.run`, `timeout=120`, `capture_output=True, text=True`).
- [ ] **Step 4:** Green. Commit `feat(discover): repo signals`.

```json:metadata
{"files": ["board/discover_repo.py", "board/tests/test_discover_repo.py"], "verifyCommand": "python3 -m unittest board.tests.test_discover_repo -v", "acceptanceCriteria": ["repeated_rulings groups A and B, >=3 ledgers, one candidate per line", "deferred_minors touched-not-fixed rule", "todos 30 days, still at HEAD, not .md, stable key", "dependencies fake gh/npm, severity, skipped on gh 403", "stale_ideas 30 days, open only", "link() github/gitlab/None", "absence tests name their mutation"], "modelTier": "standard"}
```

### Task 4: `discover collect` and `discover rank` (`board/discover.py`, `claude/discover.md`)

**Goal:** `collect` merges every signal into one JSON with `sources_skipped`; `rank` runs the model on it and keeps only valid items.

**Files:**
- Create: `board/discover.py`, `claude/discover.md`
- Modify: `bin/tmux-ctl` (dispatch `discover` without tmux; help lines at the top)
- Test: `board/tests/test_discover.py`

**Acceptance Criteria:**
- [ ] `collect(project, root, now)` returns `{"project", "root", "at", "head", "candidates", "sources_skipped"}`; a collector that raises is listed in `sources_skipped` as `{"signal", "why": "error: <Type>: <msg>"}` and the others still run; a missing source (no history file, no ledgers dir, no ideas file) is `sources_skipped` with a plain why, not an error.
- [ ] `tmux-ctl discover collect <project> [--root <dir>] [--json]` works outside tmux (`env -u TMUX`); `--json` prints the collect JSON; without it, one line per candidate `<signal>\t<count>\t<key>\t<title>` then `skipped: <signal> (<why>)` lines. Root: `--root`, else `dream.resolve_root(project, state, None)` with the discover state's `root`; none → exit 2 `discover: no repo for <project>`.
- [ ] `rank(project, root, now, run_dir)` writes `collected.json` into `run_dir`, runs the model with cwd `run_dir`, writes `rank.json` = `{"items": [...]}`; the fake `claude` (`TC_DISCOVER_CLAUDE`) tests show: an item with an unknown key dropped; an item with an `evidence_refs` index out of range (or not an int) dropped; bad `expected_value`/`effort` enums dropped; more than 5 cut to 5; a result wrapped in a ```json fence parsed; a non-zero model exit, a timeout (fake sleeps, test sets the timeout to 1 s through a module constant), or unparseable JSON returns a failure text (`model exit 1` / `model timeout` / `model error`) and writes no `rank.json`.
- [ ] The model argv is `[<claude>, "-p", "--model", "sonnet", "--effort", "medium", "--tools", "Read", "--permission-mode", "dontAsk", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--output-format", "json"]`, the prompt on stdin, environment scrubbed with `dream.SCRUB`, own process group killed on timeout (`dream._kill_group`). The fake records its argv; a test checks it.
- [ ] `claude/discover.md` asks for value to the user's work (time saved, failures avoided, cost), not tidiness for its own sake; forbids items that change `claude/orchestrator.md`, the worker rules or `claude/discover.md`; names the exact output shape `{"items": [{"key", "title", "why", "expected_value": "high|medium|low", "effort": "S|M|L", "risk", "evidence_refs": [int]}]}`, at most 5, JSON only. A test greps the file for each of these.
- [ ] `tmux-ctl discover rank <project> [--root <dir>]` prints the `rank.json` path and one line per item; failure → exit 1 with the failure text.

**Verify:** `python3 -m unittest board.tests.test_discover -v` → `OK`

**Steps:**

- [ ] **Step 1:** Tests first, with a fake `claude` script written into the temp dir (prints a JSON envelope `{"type":"result","is_error":false,"result":"<rank json text>","total_cost_usd":0.01,"usage":{…},"duration_ms":10}` chosen by an env var, records argv to a file).
- [ ] **Step 2:** Implement `collect`, `run_model` (copy `dream.run_model`; differences that change behaviour: tools `Read` only, no `--restricted`/`--settings`, timeout 600 s, the rank JSON is parsed from the envelope's `result` string — strip one surrounding ```json fence — not from files the model writes), `validate(items, candidates)`, `rank`, and `main(argv)` with subcommands `collect`, `rank` (and placeholders that exit 2 `not yet` for `nightly`, replaced in Task 7). Run dir: `tc_env.agent_base()/discover/runs/<project>/<YYYYmmdd-HHMM>/` (keep the last 14 per project).
- [ ] **Step 3:** `bin/tmux-ctl`: before the tmux guard's dispatch block, `if [[ "$cmd" == discover ]]; then exec python3 -I "${0:A:h:h}/board/discover.py" "$@"; fi` and add `"$1" == discover` to the no-tmux guard on line ~114; add help lines `tmux-ctl discover collect|rank <project> …`, `tmux-ctl discover nightly [--project <p>] [--dry-run] [--force]`, `tmux-ctl discover schedule install|status|uninstall`.
- [ ] **Step 4:** Green, plus `env -u TMUX bin/tmux-ctl discover collect agent-board --root "$PWD" --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["candidates"]), [s["signal"] for s in d["sources_skipped"]])'` prints a count and a list. Commit `feat(discover): collect and rank`.

```json:metadata
{"files": ["board/discover.py", "claude/discover.md", "bin/tmux-ctl", "board/tests/test_discover.py"], "verifyCommand": "python3 -m unittest board.tests.test_discover -v", "acceptanceCriteria": ["collect shape, raising collector in sources_skipped, missing sources skipped", "tmux-ctl discover collect outside tmux, --json and text forms, root resolution", "rank drops unknown keys, bad refs, bad enums, cuts to 5, parses fenced json, failure texts", "model argv and scrubbed env checked through fake", "discover.md content checks", "tmux-ctl discover rank output"], "modelTier": "standard"}
```

### Task 5: bridge posts accept `rows`

**Goal:** An outbox `post` op may carry `rows` (up to 5 rows of up to 5 buttons), so one post holds two buttons per item.

**Files:**
- Modify: `board/discord_feed.py` (`_POST_OPT`, `_check`), `tools/discord-bridge/bridge.js` (post handler, ~line 198)
- Test: `board/tests/test_discord_feed.py` (or the existing feed op test file — find it with `grep -l "_check" board/tests/*.py`), `tools/discord-bridge/test/outbox.test.js`

**Acceptance Criteria:**
- [ ] `discord_feed._check` accepts a post with `rows` that passes `_check_rows`, rejects a post with malformed `rows`, and rejects a post carrying both `buttons` and `rows`.
- [ ] The bridge sends `components: toRows(op.rows)` for a post with `rows` (the fake client records it); a post with `buttons` behaves as before; `select` still appends its row after either.
- [ ] `npm test` in `tools/discord-bridge` passes (run `npm ci` first in a fresh worktree).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_feed*.py' && (cd tools/discord-bridge && npm test)` → `OK` and `# fail 0`

**Steps:**

- [ ] **Step 1:** Tests first in both places; run, see them fail.
- [ ] **Step 2:** `discord_feed.py`: add `"rows": list` to `_POST_OPT`; in `_check` for `post`, call `_check_rows(op["rows"])` when present and raise `ValueError("post takes buttons or rows, not both")` when both are present.
- [ ] **Step 3:** `bridge.js` post handler, replacing the `buttons` block:

```js
    if (Array.isArray(op.rows) && op.rows.length) {
      payload.components = toRows(op.rows);
    } else if (Array.isArray(op.buttons) && op.buttons.length) {
      payload.components = [{ type: 1, components: op.buttons.slice(0, 5).map((b) => ({ type: 2, style: Number(b.style) || 2, label: String(b.label).slice(0, 80), custom_id: String(b.custom_id) })) }];
    }
```

  `toRows` is a `const` at ~line 223 in the same enclosing scope as `opPost` (line 175); it is initialised before any outbox op runs, so no move is needed (checked).
- [ ] **Step 4:** Green. Commit `feat(bridge): post ops accept button rows`.

```json:metadata
{"files": ["board/discord_feed.py", "tools/discord-bridge/bridge.js", "tools/discord-bridge/test/outbox.test.js"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_feed*.py' && (cd tools/discord-bridge && npm test)", "acceptanceCriteria": ["_check accepts valid rows, rejects malformed rows and buttons+rows", "bridge sends toRows(op.rows), buttons unchanged, select appended", "npm test passes"], "modelTier": "mechanical"}
```

### Task 6: state, selection, post and clicks (`board/discover_post.py`)

**Goal:** Turn a night's rank into at most one post per the selection rule, and handle the two buttons.

**Files:**
- Create: `board/discover_post.py`
- Modify: `board/discord_controls.py` (route `ab:discover:` clicks)
- Test: `board/tests/test_discover_post.py`

**Acceptance Criteria:**
- [ ] `load_state(project)` / `save_state(project, st)` per Global Constraints (lock, atomic write, defaults for missing keys, `posts` cut to 14 nights).
- [ ] `select(items, cands, st, memory_dirs)` returns `{"new": [...], "still_open": int, "also_memory": [...]}`: filed → never shown; dismissed with count 10 → hidden at 14, shown at 15; reported and unchanged → `still_open`, not new; reported with a changed count → new; a `repeated_ruling` whose ledger dirs overlap a memory proposal's by ≥ 3 → `also_memory`, not new.
- [ ] `memory_dirs(project)` reads the newest `report.json` under `dream_paths.project_dir(project)` (`<run>/out/report.json`) and returns one set of ledger dir names per proposal, from evidence entries `inputs/ledgers/<name>/progress.md:<n>`; no report → `[]`.
- [ ] `build_op(project, night, new, still_open, also_memory)` returns a valid `post` op (passes `discord_feed._check`) with numbered items `title — why`, a line `value <v> · effort <e> · risk <r> · evidence: <first 2 evidence texts, each as a markdown link when it has a url>`, the footer `still open: <n>` when n > 0 and `also proposed by the memory run: <titles>` when any; model strings escaped; text ≤ 1900 chars even with 5 items of 900-char `why` (the `why` fields are cut evenly first); `rows` per Global Constraints.
- [ ] `publish(project, night, new, still_open, also_memory, cands, now)` writes the op to `tc_env.discord_dir(project)` outbox, records `reported[key]` and `posts[night]` (items with `n, key, kid, title, why, summary, count, decision: null`); nothing new → returns 0 and writes nothing.
- [ ] `click(project, user, cid, now)`: bad id → `unknown`; another project's id → `ignored`; File → `ideas.add(project, "<title>: <why> (evidence: <summary>)")` once, `filed[key]` recorded, returns `filed`, a second tap returns `already filed` and adds no idea line; Dismiss → `dismissed[key] = {at, evidence_count: count}`, returns `dismissed`, again → `already dismissed`; after each decision an `edit` op (key = the post's key) rewrites the text with `— 💡 filed` / `— ✖ dismissed` after that item and drops that item's row; an exception returns `error: <Type>`.
- [ ] `discord_controls.consume_events` routes `custom_id` starting `ab:discover:` to `discover_post.click(project, user, cid, time.time())` for allowlisted users (`rejected` otherwise) and audits the result like the `ab:dream:` branch (a test drives one event file through `consume_events` and reads `audit.jsonl`).
- [ ] Absence tests (no idea added on the second tap, no post when nothing new) name their mutation; RED shown.

**Verify:** `python3 -m unittest board.tests.test_discover_post board.tests.test_discord_controls -v` → `OK`

**Steps:**

- [ ] **Step 1:** Tests first, with `TC_STATE` and `TC_IDEAS_DIR` at temp dirs (every test class sets `TC_STATE`). Run, see them fail.
- [ ] **Step 2:** Implement. Follow `analytics_post.click` (lock, read, act once, atomic write) and `dream_discord.click` (project check, never raise). Differences from `analytics_post` that change behaviour: state lives in `agent_base()/discover/<project>.json`, not the destination dir; the id carries a project and a key hash, not a week and an index; a decision edits the original post (`edit` op with `rows`) instead of writing a new post.
- [ ] **Step 3:** Add the `ab:discover:` branch to `discord_controls.consume_events` next to `ab:dream:`.
- [ ] **Step 4:** Green. Commit `feat(discover): selection, post and buttons`.

```json:metadata
{"files": ["board/discover_post.py", "board/discord_controls.py", "board/tests/test_discover_post.py", "board/tests/test_discord_controls.py"], "verifyCommand": "python3 -m unittest board.tests.test_discover_post board.tests.test_discord_controls -v", "acceptanceCriteria": ["state load/save lock, atomic, 14 nights", "select: filed, dismissal 50% regrowth, unchanged not reposted, memory overlap", "memory_dirs from newest report.json", "build_op shape, escape, 1900 cap, rows", "publish writes once, nothing new writes nothing", "click file once, dismiss records, edit op, unknown/ignored/error", "discord_controls routes and audits ab:discover:", "absence tests name their mutation"], "modelTier": "standard"}
```

### Task 7: `discover nightly`

**Goal:** One command runs the whole night for every project with a repo, records it, and handles failures.

**Files:**
- Modify: `board/discover.py`
- Test: `board/tests/test_discover_nightly.py`

**Acceptance Criteria:**
- [ ] `tmux-ctl discover nightly [--project <p>] [--dry-run] [--force]`: off (`TC_DISCOVER=0` or `discover.off`) → prints `discover: off`, exit 0, no model call; weekly ≥ 85 % → `discover: skipped, weekly <n>%`, exit 0, unless `--force`.
- [ ] Projects = `dream.projects()` (or the one `--project`), each root resolved as in Task 4; a project with no repo is skipped with a line `discover: <p>: no repo`.
- [ ] A normal night: collect → rank → select → publish; prints `discover: <p>: <candidates> candidates, <ranked> ranked, <new> new, posted|nothing new`.
- [ ] `--dry-run` runs collect and the model, prints the post text and its rows' labels, and writes nothing to the state file, the outbox or the metrics log (a test lists both dirs before and after).
- [ ] A model failure: no post, `failures` +1 in the state, one line in `agent_base()/discover/discover.log` with the reason; exactly at 3 failures a `critical` post `🔎 discover: <p> failed 3 nights running — <why>` (`mention_user: true`, key `discover-<p>-fail-<night>`); the 4th failed night posts nothing new; a good night resets `failures` to 0. `--dry-run` never touches `failures`.
- [ ] Every non-dry night appends to `<root>/docs/superpowers/metrics/runs.jsonl` when that file exists: `{"kind": "discover", "at", "project", "outcome": "posted"|"nothing-new"|"failed", "candidates", "ranked", "new", "sources_skipped", "cost_usd", "tokens", "duration_s", "model": "sonnet"}` via `metrics.append`; missing file → no record, no error.
- [ ] One project raising does not stop the others; exit 1 when any project failed.

**Verify:** `python3 -m unittest board.tests.test_discover_nightly -v` → `OK`

**Steps:**

- [ ] **Step 1:** Tests first: temp `TC_STATE`, `TC_CONTEXT_DIR` with project core files (so `dream.projects()` lists them), temp git repos as roots passed through the discover state's `root` (no live tmux in tests: patch `dream.live_session_root` to return None), fake `claude`, `dream.weekly_pct` patched. Run, see them fail.
- [ ] **Step 2:** Implement `nightly(argv)` in `discover.py` replacing the Task 4 placeholder; reuse `dream.weekly_pct`, `dream.projects`, `dream.resolve_root`, `metrics.append`, `discover_post.*`.
- [ ] **Step 3:** Green. Commit `feat(discover): nightly run`.

```json:metadata
{"files": ["board/discover.py", "board/tests/test_discover_nightly.py"], "verifyCommand": "python3 -m unittest board.tests.test_discover_nightly -v", "acceptanceCriteria": ["off switches and weekly guard", "projects with repos only", "normal night output line", "dry-run writes nothing", "failure counter, log, critical at exactly 3, reset", "metrics kind discover record", "one project raising does not stop others"], "modelTier": "standard"}
```

### Task 8: the 07:00 LaunchAgent and docs

**Goal:** `tmux-ctl discover schedule install|status|uninstall` manages `com.user.agent-board-discover`, and the docs describe the job.

**Files:**
- Create: `board/discover_schedule.py`
- Modify: `bin/tmux-ctl` (route `discover schedule` to the new module before the `discover.py` exec), `docs/INSTALL.md`, `README.md` (one line in its commands list if it has one for `metrics schedule`)
- Test: `board/tests/test_discover_schedule.py`

**Acceptance Criteria:**
- [ ] `plist_text(cli, home, log)` gives `Label` `com.user.agent-board-discover`, `ProgramArguments` `[cli, "discover", "nightly"]`, `StartCalendarInterval` `{"Hour": 7, "Minute": 0}` (no `Weekday`), `WorkingDirectory` = this checkout, the same `EnvironmentVariables` rules as `analytics_schedule` (PATH, LANG, TC_STATE or TMPDIR).
- [ ] `status` prints `loaded`/`not loaded` first, then `off: TC_DISCOVER=0` / `off: discover.off` lines when they apply, and the last night from `discover.log`.
- [ ] install/uninstall tests use the same launchctl seam as `test_analytics_schedule.py` (no real launchctl call); non-macOS raises `MacOnly`.
- [ ] `docs/INSTALL.md` has a section naming the install command, the 07:00 time, both off switches, the 85 % guard, and the log path.

**Verify:** `python3 -m unittest board.tests.test_discover_schedule -v && grep -c 'discover schedule install' docs/INSTALL.md` → `OK` and a count ≥ 1

**Steps:**

- [ ] **Step 1:** Copy `board/analytics_schedule.py` and its test. Differences that change behaviour: label; argv `discover nightly` with no `--repo` (nightly resolves each project's root itself); daily `{"Hour": 7, "Minute": 0}`; off switch names `TC_DISCOVER` / `discover.off`; `status` reads the last line of `agent_base()/discover/discover.log` instead of the metrics runs. Everything else identical (checked: `_cli_path`, `_launchctl`, the plist path under `~/Library/LaunchAgents`).
- [ ] **Step 2:** Tests first, red, then implement, green.
- [ ] **Step 3:** `bin/tmux-ctl`: `[[ "$1" == schedule ]]` inside the `discover` block → `[[ "$2" == (install|status|uninstall) ]] || die 'usage: tmux-ctl discover schedule install|status|uninstall'; exec python3 -I "${0:A:h:h}/board/discover_schedule.py" "$2"`.
- [ ] **Step 4:** Docs. Commit `feat(discover): 07:00 LaunchAgent and docs`.

```json:metadata
{"files": ["board/discover_schedule.py", "board/tests/test_discover_schedule.py", "bin/tmux-ctl", "docs/INSTALL.md", "README.md"], "verifyCommand": "python3 -m unittest board.tests.test_discover_schedule -v && grep -c 'discover schedule install' docs/INSTALL.md", "acceptanceCriteria": ["plist label, argv, daily 07:00, WorkingDirectory, env", "status loaded/off/last night", "launchctl seam, MacOnly", "INSTALL.md section"], "modelTier": "mechanical"}
```

### Task 9: full suite and read-only real-state checks

**Goal:** The whole suite is green and the collectors work on the user's real state without writing to it.

**Files:**
- Create: `docs/superpowers/notes/2026-11-21-discover-real-state.md`

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh; echo rc=$?` → `ALL PASS` with rc 0 or 4 (4 = over budget, accepted on this machine).
- [ ] Real state, read-only: `env -u TMUX bin/tmux-ctl discover collect agent-board --root /Users/francisco.ruiz/agent-board --json` parses; the note records the candidate count per signal, `sources_skipped` (expected: `dependency` github skipped with the 403 text; `flaky_test`/`slow_test` thin or empty because the history file is new) and the 3 highest-count keys with their evidence, each checked by hand against its source file (ledger line, git log, ideas file).
- [ ] The real ledgers yield at least one `repeated_ruling` or `deferred_minor` candidate, or the note explains from the ledger text why none qualifies.
- [ ] `TC_DISCOVER_CLAUDE=<fake that ranks the top 3 collected keys> env -u TMUX bin/tmux-ctl discover nightly --project agent-board --dry-run` on real state prints a post under 1900 chars with 3 numbered items and 3 rows; `ls -la ~/.local/state/agent-board/discover/ ~/.local/state/agent-board/discord/agent-board/outbox/` before and after shows no new state or outbox file (the run dir under `discover/runs/` is the one allowed write).
- [ ] The history file got a line from the full-suite run above (`tail -1 ~/.local/state/agent-board/tests/history.jsonl` shows `full: true` and this worktree's root).

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → `ALL PASS` and `rc=0` or `rc=4`

**Steps:**

- [ ] **Step 1:** Run the suite through `tmux-ctl run -t 1500 tests "zsh tools/tests/all.zsh; echo rc=\$?"`; read the verdict and rc lines.
- [ ] **Step 2:** The real-state commands above; write the note with the outputs.
- [ ] **Step 3:** Commit `docs(notes): discover real-state checks`.

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-21-discover-real-state.md"], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["ALL PASS rc 0 or 4", "real collect parses, note lists counts, skipped, 3 keys checked by hand", "real ledgers give a ruling/minor candidate or the note explains", "dry-run on real state with fake model: post <1900, 3 items/rows, no state/outbox write", "history file got the suite's line"], "modelTier": "standard"}
```

### Task 10: User gate: one real `discover nightly --dry-run`

**Goal:** The user sees one real model-ranked report for this repo before the schedule is installed.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none (a check)

**Acceptance Criteria:**
- [ ] `env -u TMUX ~/.local/bin/tmux-ctl discover nightly --project agent-board --dry-run` from `main` after the merge, with the real `claude`, exits 0 and prints at most 5 items, each key present in that night's `collected.json` (in the `run dir:` it prints). While weekly usage is ≥ 85 % the guard prints `discover: skipped, weekly <n>%`: add `--force` to this command and to Verify (ruled in the ledger, 2026-11-21).
- [ ] The user reads the printed post and says whether the items are worth having; their answer is recorded on the task.
- [ ] Only after that, if the user wants it: `~/.local/bin/tmux-ctl discover schedule install` and `tmux-ctl discover schedule status` shows `loaded`.

**Verify:** `env -u TMUX ~/.local/bin/tmux-ctl discover nightly --project agent-board --dry-run; echo rc=$?` → `rc=0` and ≤ 5 numbered items

```json:metadata
{"files": [], "verifyCommand": "env -u TMUX ~/.local/bin/tmux-ctl discover nightly --project agent-board --dry-run; echo rc=$?", "acceptanceCriteria": ["real dry-run rc 0, <=5 items, keys in collected.json", "user's verdict recorded", "schedule installed only if the user wants it"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```
