# Execution analytics part 2: the weekly Discord post — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tmux-ctl metrics weekly` posts the execution-analytics findings to Discord every Monday 09:00 with a `File as idea` button per recommendation, and the run is recorded as metrics kind `analytics`.

**Architecture:** Part 1 (merged) computes `stats.json` (`board/metrics_analyze.py`), asks the model for recommendations (`board/metrics_recommend.py`) and prints `weekly --dry-run` text. Part 2 adds `board/analytics_post.py` (Discord ops, thread links, state file, button click), wires `cmd_weekly` to write outbox ops into the ops dir (or each project's dir), adds `ab:analytics:` click branches to both event consumers, and a LaunchAgent `board/analytics_schedule.py` modelled on `board/dream_schedule.py`.

**Tech Stack:** Python 3 stdlib (unittest, plistlib, fcntl), zsh (`bin/tmux-ctl`), the Discord bridge outbox (`board/discord_feed.py`).

**Spec:** `docs/superpowers/specs/2026-11-12-execution-analytics-design.md` §4 (part 2), plus part-1 minors marked "(part 2)" in `docs/superpowers/ledgers/2026-11-16-execution-analytics-part-1/progress.md` (lines 39, 69, 70, 78; line 38's `mr` row).

## Global Constraints

- **Outbox ops** go through `discord_feed.outbox_write(dir, op)` only. A `post` op is `{"op":"post","text":str,"tier":"progress","mention_user":False}` plus optional `key`, `buttons`, `files`. No other keys (`_check` raises "bad keys"). Never set `delete_files` (stats.json is outside `<dir>/tmp`).
- **Discord limits:** every post's `text` ≤ 1900 chars (the bridge cuts at 2000 silently). `buttons` ≤ 5, one row, each `{"label": ≤80 chars, "style": 1, "custom_id": ≤100 chars}`; the plan's code validates them because `_check` does not.
- **Escaping (part-1 minor 70):** every model-written string (title, change, expected_effect, risk, evidence values) and every task subject in a post is passed through `analytics_post.escape()`: backslash-escape `\ * _ ~ | > #` and backticks, and replace `@` with `@​` (zero-width space after `@`). Text inside the trends code block is numbers and metric names only and is not escaped.
- **No absolute paths in posts:** the `stats: <path>` line is not in Discord text; stats.json is attached via `files` instead.
- **Custom id:** `ab:analytics:idea:<week>:<n>`, `<week>` = `time.strftime("%G-W%V", time.localtime(until_ts))` of the window's end (e.g. `2026-W47`), `<n>` = 1-based recommendation number. Regex `^ab:analytics:idea:(\d{4}-W\d{2}):([1-5])$`.
- **State file:** `<dir>/analytics/post-<week>.json` = `{"week", "project", "items": [{"n", "title", "change", "evidence": [{"key","value"}], "done": false|"<ISO>"}]}`, where `<dir>` is the outbox dir the post was written to. Written with an atomic replace (`tmp` + `os.replace`), read and updated under `fcntl.flock` on `<dir>/analytics/.lock`.
- **Destination:** `discord_ops.configured()` true → one post set into `tc_env.ops_dir()` over all projects. Else, for each project path from `metrics_analyze.overview_projects()` (fallback: this repo) whose name `Path(p).name` has `discord_feed.channel_of(name) != ""`: a post set into `tc_env.discord_dir(name)` built from `write_stats(repo, since, projects=[p], out=<state_dir>/analytics/<name>/stats.json)` and its own recommend run. A project with 0 runs in the window gets nothing.
- **Idea filing project:** ops post → `Path(main_root(repo)).name` (the repo the job runs from); project post → that project's name. Stored in the state file's `project`.
- **Off switch:** `TC_ANALYTICS=0` in the environment, or the file `tc_env.agent_base() / "analytics.off"` exists → `metrics weekly` (without `--dry-run`) prints `analytics: off` and exits 0, writing nothing. `--dry-run` ignores the switch.
- **Errors of the weekly job (part-1 minors 39, 69):** `metrics weekly` failures never append `kind:error` to the tracked `runs.jsonl`; they go to stderr only (the launchd log). Other subcommands keep today's `_log_error` behaviour.
- **Run record:** one line per non-dry-run `metrics weekly` that is not off, appended with `metrics.append(repo, rec)` only when `mdir(repo)/runs.jsonl` exists: `{"kind":"analytics","at":utc(),"week":<week>,"outcome":"posted"|"no-runs"|"partial","posts":<int ops written>,"destinations":[<dir names>],"cost_usd":<float|null>,"tokens":{"input","output","cache_read","cache_write"}|null,"duration_s":<int>,"model":"sonnet"}`. `partial` = posted but at least one recommend run was unavailable. Readers that filter `kind=="run"` ignore it.
- **LaunchAgent:** label `com.user.agent-board-analytics`, `StartCalendarInterval {"Weekday":1,"Hour":9,"Minute":0}`, args `[<tmux-ctl>, "metrics", "weekly"]`, log `agent_base()/analytics.launchd.log`, same env block and install/uninstall/status behaviour as `board/dream_schedule.py`, launchctl seam `AS_LAUNCHCTL`. CLI `tmux-ctl metrics schedule install|status|uninstall`.
- Tests never post for real: every test sets `TC_STATE` to a temp dir (so `agent_base()`, `ops_dir()`, `discord_dir()` resolve under it) and patches `ideas._kick`.
- Commits: conventional with scope (`feat(metrics): …`, `feat(discord): …`); end with the attribution trailer your harness specifies.

**User decisions (already made):**
- A weekly findings post with trends, flags and three recommendations, each with its evidence and a "file as idea" button; no board page (spec, 2026-11-12).
- Numbers by code, words by a model; every cited number checked (spec, 2026-11-12).
- Queue item: integration merge to main locally, no push (2026-11-12T14:34:29Z).

## Decided (lead, from the spec and code)

- The post is split in two ops: **post A** = header, trends code block, flags (flag lines beyond what fits are replaced by `… and <k> more flags in stats.json`); **post B** = recommendations, evidence-check count line, coverage line, buttons, `files: [stats.json]`. Keys `analytics-<week>-a` / `analytics-<week>-b`.
- `costly_steps` shows only the top 3 rows in the post (part-1 minor 78: always 10 rows); stats.json keeps all 10.
- Flag lines gain a `[<project>]` prefix when the post covers more than one project.
- A flag row's deep link: from `tc_env.feed_path(project)` read the last `spec_started` event whose `spec` equals the flag spec's basename without `.md` (also matching a `#part-N` suffix on either side by prefix `<name>#`), take `refs.thread_key`, look it up in `tc_env.discord_dir(project)/bridge-state.json` `threads`, and build `<https://discord.com/channels/<guild_id>/<thread id>>` (angle brackets: no embed). Missing anything → no link, no error.
- `trends` gains `specs_mr` (count of runs with outcome starting `mr`), after `specs_merged` (part-1 ruling line 38).
- A repeat run in the same week for the same dir carries `done` over for items whose `title` is equal; others start `false`.
- A click on a filed item returns `already filed` and writes nothing else; a first click files `ideas.add(project, f"{title}: {change} (evidence: {k}={v}; …)")`, marks done, then writes a reply post `{"op":"post","text":"💡 filed as idea: <escaped title>","tier":"progress","mention_user":False,"key":"analytics-<week>-<n>-filed"}` into the same dir. The buttons stay (no edit), like dream's File proposals.

---

### Task 1: Usage from the model run, `specs_mr` trend

**Goal:** `metrics_recommend.recommend()` returns the model run's cost and tokens, and `stats.trends` gains `specs_mr`.

**Files:**
- Modify: `board/metrics_recommend.py` (`run_claude`, `recommend`)
- Modify: `board/metrics_analyze.py` (trends block ~line 130-142)
- Test: `board/tests/test_metrics_recommend.py`, `board/tests/test_metrics_analyze.py`

**Acceptance Criteria:**
- [ ] `run_claude(path)` returns `(text, usage)` where `usage = {"cost_usd": total_cost_usd or None, "tokens": {"input","output","cache_read","cache_write"} or None}` from the claude JSON (`usage.input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`); missing fields → `None`, never an exception.
- [ ] `recommend()` result has key `usage` in both the success and the `unavailable` shape (`{"cost_usd": None, "tokens": None}` when the run never produced JSON).
- [ ] Every existing caller of `run_claude` is updated (grep shows none left using the old single return).
- [ ] `stats["trends"]["specs_mr"]` = `{current, previous, change}` counting runs whose `outcome` starts with `mr`; key order puts it right after `specs_merged`.
- [ ] Tests: usage parsed from a fake claude JSON with all four token fields; usage `None` on a JSON without `usage` (mutation: drop the `.get` default → test fails with KeyError); `specs_mr` counts `"mr https://…"` and not `"merged abc"`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_re*.py' && python3 -m unittest discover -s board/tests -p 'test_metrics_analyze.py'` → `OK` twice

**Steps:**

- [ ] **Step 1:** Write failing tests in `test_metrics_recommend.py` (the fake claude in that file prints a JSON; add a variant printing `{"result": "...", "total_cost_usd": 0.12, "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40}}` and assert `recommend(path)["usage"] == {"cost_usd": 0.12, "tokens": {"input": 10, "output": 20, "cache_read": 30, "cache_write": 40}}`), and in `test_metrics_analyze.py` a fixture run with outcome `mr https://x/1` in the current window.
- [ ] **Step 2:** Run the Verify command; expect failures on the new tests only.
- [ ] **Step 3:** Implement:

```python
def _usage(doc):
    u = doc.get("usage") if isinstance(doc, dict) else None
    tokens = None
    if isinstance(u, dict):
        tokens = {"input": u.get("input_tokens"), "output": u.get("output_tokens"),
                  "cache_read": u.get("cache_read_input_tokens"), "cache_write": u.get("cache_creation_input_tokens")}
    cost = doc.get("total_cost_usd") if isinstance(doc, dict) else None
    return {"cost_usd": cost if isinstance(cost, (int, float)) else None, "tokens": tokens}
```

  `run_claude` parses `doc = json.loads(p.stdout)` once and returns `(doc["result"], _usage(doc))`. `recommend()` keeps the usage from the call (or `{"cost_usd": None, "tokens": None}` when `Unavailable` was raised) and adds `"usage"` to the returned dict. In `metrics_analyze.py` add `"specs_mr": _trend(count_prefix(cur_runs, "mr"), count_prefix(prev_runs, "mr"), 0)` using the same counting helper style as `specs_merged` (outcome `str.startswith("mr")`), and insert `"specs_mr"` after `"specs_merged"` in the key-order tuple.
- [ ] **Step 4:** Run Verify → OK. Also run `python3 -m unittest discover -s board/tests -p 'test_metrics_weekly.py'` → OK (weekly text gains a `specs_mr` row; update any exact-text expectation there).
- [ ] **Step 5:** Commit `feat(metrics): recommend returns usage; specs_mr trend`.

```json:metadata
{"files": ["board/metrics_recommend.py", "board/metrics_analyze.py", "board/tests/test_metrics_recommend.py", "board/tests/test_metrics_analyze.py", "board/tests/test_metrics_weekly.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_re*.py' && python3 -m unittest discover -s board/tests -p 'test_metrics_analyze.py'", "acceptanceCriteria": ["run_claude returns (text, usage) with None for missing fields", "recommend result has usage in success and unavailable shapes", "no caller left on the old run_claude return", "trends.specs_mr counts outcomes starting with mr, after specs_merged", "tests for usage parse, missing usage, specs_mr"], "modelTier": "standard"}
```

---

### Task 2: `board/analytics_post.py`: ops, links, state file

**Goal:** A module that turns `(stats, rec)` into the two Discord post ops for one destination dir, resolves spec-thread links, and writes the state file the button needs.

**Files:**
- Create: `board/analytics_post.py`
- Test: `board/tests/test_analytics_post.py`

**Acceptance Criteria:**
- [ ] `escape(s) -> str` implements the Global Constraints escaping; `escape("@everyone *x*")` == `"@​everyone \\*x\\*"`.
- [ ] `week_id(until_iso) -> "YYYY-Www"` (ISO week of the window end, local time).
- [ ] `thread_link(project, spec) -> str|None` per the Decided rule; returns `None` when the feed, the `spec_started` event, the thread key, the `threads` entry or `guild_id` is missing (one test per missing piece is not required; one test with a full fixture → link, one with no feed → `None`, one with a `#part-2` spec matching a feed spec `name#part-2`).
- [ ] `build_ops(stats, rec, week, stats_path, multi_project) -> [opA, opB]`: both pass `discord_feed._check`; each `text` ≤ 1900 chars for a fixture with 30 flags and 3 long recommendations (titles 300 chars); opA ends with `… and <k> more flags in stats.json` when flags were cut; costly_steps shows at most 3 lines; flag lines carry `[project]` only when `multi_project`; flag lines with a link end with ` <https://…>`; opB has one button per surviving recommendation (`label` = `File as idea <n>`, `style` 1, `custom_id` per Global Constraints), `files: [str(stats_path)]`, no `stats:` line, the `(<passed> of <asked> passed the evidence check)` or `recommendations unavailable: <reason>` line, and the coverage line; with `unavailable`, opB has no `buttons` key.
- [ ] `validate_buttons(buttons)` raises `ValueError` for >5 buttons, a label >80 or a custom_id >100; `build_ops` calls it.
- [ ] `publish(d, project, stats, rec, stats_path, multi_project) -> int` writes the state file (carrying `done` for equal titles from an existing file of the same week) and then the ops via `discord_feed.outbox_write(d, op)`; returns the number of ops written. Test: two `publish` calls in one week where item 1 was done keep item 1 done.
- [ ] Every model string and subject in the post text went through `escape` (test: a title `@here **x**` appears escaped in opB).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_analytics_post.py'` → `OK`

**Steps:**

- [ ] **Step 1:** Write `test_analytics_post.py`. setUp: `TemporaryDirectory`, `mock.patch.dict(os.environ, {"TC_STATE": tmp})`; build a stats fixture shaped like `metrics_analyze.analyze` output (keys `window{since,until,previous_since}`, `projects`, `trends`, `flags{overpowered,underpowered,costly_steps,handoffs,forecast{below_half,median_precision,median_recall}}`, `coverage{with_cost,tasks}`; reuse `board/tests/metrics_fixtures.py` helpers if they build stats). Feed fixture: write `tc_env.feed_path("p1")` with one JSON line `{"ts":…,"project":"p1","spec":"2026-11-12-x#part-2","kind":"spec_started","tier":"progress","text":"","refs":{"thread_key":"session-ab:9"}}`; `tc_env.discord_dir("p1")/bridge-state.json` = `{"guild_id":"G","threads":{"session-ab:9":"T"}}` → expect `<https://discord.com/channels/G/T>`.
- [ ] **Step 2:** Run Verify → fails (module missing).
- [ ] **Step 3:** Implement the module. Reuse `metrics_recommend._one_line` and the trends-table layout of `metrics_recommend.weekly_text` (factor the table into `metrics_recommend.trends_table(stats) -> list[str]` and call it from both, so the two never drift; `weekly_text` output must stay byte-identical — existing `test_metrics_weekly.py` proves it). Differences from `weekly_text`, all intended: escaped strings, `[project]` prefix, links, costly top 3, two posts, no `stats:` line, `File as idea` buttons. Fitting: add flag lines to opA while `len(text) + len(line) + 1 <= 1900 - 60`, then the `… and <k> more` line. For opB, if the text exceeds 1900, shorten each item's `change`/`expected`/`risk` lines to 200 chars (`…`), then cut the coverage line last. State file write:

```python
def _write_state(d, week, project, items):
    p = Path(d) / "analytics" / f"post-{week}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    old = {}
    try:
        old = {i["title"]: i.get("done") for i in json.loads(p.read_text()).get("items", [])}
    except (OSError, ValueError):
        pass
    doc = {"week": week, "project": project,
           "items": [{"n": n, "title": it["title"], "change": it["change"], "evidence": it["evidence"],
                      "done": old.get(it["title"]) or False} for n, it in enumerate(items, 1)]}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    os.replace(tmp, p)
```

  (`publish` takes the flock on `<d>/analytics/.lock` around `_write_state`.)
- [ ] **Step 4:** Run Verify → OK; run `python3 -m unittest discover -s board/tests -p 'test_metrics_weekly.py'` → OK (byte-identical text).
- [ ] **Step 5:** Commit `feat(metrics): analytics_post builds the weekly Discord ops`.

```json:metadata
{"files": ["board/analytics_post.py", "board/metrics_recommend.py", "board/tests/test_analytics_post.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_analytics_post.py'", "acceptanceCriteria": ["escape per Global Constraints", "week_id ISO week", "thread_link full fixture, no feed, #part-2 match", "build_ops: _check passes, <=1900 chars, more-flags line, costly top 3, project prefix only multi, links, buttons, files, no stats line, unavailable has no buttons", "validate_buttons limits", "publish writes state then ops, carries done for equal titles", "model strings escaped", "weekly_text byte-identical via shared trends_table"], "modelTier": "standard"}
```

---

### Task 3: The `File as idea` click

**Goal:** A tap on `ab:analytics:idea:<week>:<n>` files the recommendation as an idea exactly once, from either the ops bot or a project bot.

**Files:**
- Modify: `board/analytics_post.py` (add `click`)
- Modify: `board/discord_controls.py` (~line 94, the click branches)
- Modify: `board/discord_ops.py` (`_click`, ~line 762)
- Test: `board/tests/test_analytics_post.py`, `board/tests/test_discord_controls.py`, `board/tests/test_discord_ops.py`

**Acceptance Criteria:**
- [ ] `analytics_post.click(d, user, cid, now) -> str`: `"unknown"` for a cid not matching the regex or a week with no state file or an `n` not in items; `"already filed"` when the item is done (nothing written: idea file and outbox unchanged — test counts both); otherwise calls `ideas.add(state["project"], text)` with `text = f"{title}: {change} (evidence: {k1}={v1}; {k2}={v2})"`, sets `done` to the ISO time and writes the state file **before** writing the reply post, returns `"filed"`.
- [ ] Concurrency/repeat: two `click` calls for the same item (sequential in the test, the flock covers concurrent ones) file once (`ideas.add` mock called once; mutation: move the `done` check outside the lock or drop it → second call files again, test fails). Order: a click for week W while week W+1's file exists still resolves W's file (state is per week).
- [ ] An `ideas.add` `ValueError` returns `"error: <msg>"` and leaves `done` false.
- [ ] `discord_controls.consume_events`: a `click` with cid starting `ab:analytics:` from an allowed user audits `analytics_post.click(d, …)`'s result; a non-allowed user audits `"rejected"` and never calls `click`.
- [ ] `discord_ops._click`: `parts[:2] == ["ab", "analytics"]` → `analytics_post.click(d, user, cid, now)`; the caller's existing audit line records the result.
- [ ] The reply post lands in the same dir the click came from (test: ops-dir click → ops outbox; project click → project outbox, never ops).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_analytics_post.py' && python3 -m unittest discover -s board/tests -p 'test_discord_controls.py' && python3 -m unittest discover -s board/tests -p 'test_discord_ops.py'` → `OK` three times

**Steps:**

- [ ] **Step 1:** Failing tests: in `test_analytics_post.py` (state file from `publish`, `mock.patch.object(ideas, "add")` and `mock.patch.object(ideas, "_kick")`), and one consumer test each in `test_discord_controls.py` and `test_discord_ops.py`, copying the setup of the existing `ab:ideas:` click tests there (same event file shape `{"type":"click","custom_id":…,"user":…}`; the only difference is the cid prefix and the patched handler `analytics_post.click`).
- [ ] **Step 2:** Run Verify → new tests fail.
- [ ] **Step 3:** Implement `click` under the same `fcntl.flock` on `<d>/analytics/.lock` used by `publish`; read state, check, `ideas.add`, write state (atomic), release, then `discord_feed.outbox_write(d, reply_op)`. Add the two consumer branches next to the `ab:ideas:` ones, importing `analytics_post` the way those files import `discord_ideas`.
- [ ] **Step 4:** Run Verify → OK.
- [ ] **Step 5:** Commit `feat(discord): File as idea button for the weekly analytics post`.

```json:metadata
{"files": ["board/analytics_post.py", "board/discord_controls.py", "board/discord_ops.py", "board/tests/test_analytics_post.py", "board/tests/test_discord_controls.py", "board/tests/test_discord_ops.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_analytics_post.py' && python3 -m unittest discover -s board/tests -p 'test_discord_controls.py' && python3 -m unittest discover -s board/tests -p 'test_discord_ops.py'", "acceptanceCriteria": ["click unknown/already filed/filed/error results", "files once under lock, done written before the reply post", "per-week state resolves old weeks", "controls branch audits result, rejects non-allowed", "ops _click branch", "reply post lands in the clicked dir"], "modelTier": "standard"}
```

---

### Task 4: `metrics weekly` posts, records, and honours the off switch

**Goal:** `tmux-ctl metrics weekly` (without `--dry-run`) writes the post sets per the Destination rule, records one `kind:analytics` line, and `--dry-run --json` prints the ops it would write.

**Files:**
- Modify: `board/metrics.py` (`cmd_weekly`, weekly parser, `main`'s error path, module docstring kinds line)
- Modify: `bin/tmux-ctl` (help line 74)
- Test: `board/tests/test_metrics_weekly.py`

**Acceptance Criteria:**
- [ ] Off: `TC_ANALYTICS=0` or `agent_base()/analytics.off` → stdout `analytics: off`, rc 0, no outbox file, no runs.jsonl line, no model run (fake claude never invoked — check its argv log is absent).
- [ ] Ops configured (fixture `ops_dir()/bridge.json` with `command_center` and `approvals`): ops land in `ops_dir()/outbox` only (2 files), state file in `ops_dir()/analytics/`, and project dirs get nothing.
- [ ] Ops not configured, two fixture projects (`--projects` is not a weekly flag: patch `metrics_analyze.overview_projects` to return both paths), project A with a `bridge.json` `channel` and runs, project B with a channel and no runs in the window: A's dir gets 2 ops built from A's rows only (its stats file at `state_dir()/analytics/<A>/stats.json`, `projects == [A]`), B gets nothing.
- [ ] No runs anywhere: stdout `no runs in the window; nothing to post`, no ops, one record with `outcome: "no-runs"`, `posts: 0`.
- [ ] Recommend unavailable (fake claude exits 1): ops still written (opB with `recommendations unavailable: claude exited 1`, no buttons), record `outcome: "partial"`.
- [ ] Record: exactly one `kind:analytics` line per run with the Global Constraints fields; `cost_usd` is the sum over recommend runs (None when all None); appended only when runs.jsonl exists (a repo without it stays clean).
- [ ] A weekly failure (e.g. `write_stats` raising) prints `metrics: weekly: <reason>` rc 1 and appends no `kind:error` line to runs.jsonl; `analyze` failures still do (existing test stays green).
- [ ] `--dry-run` without `--json` prints today's text unchanged; `--dry-run --json` prints one JSON op per line (as `build_ops` returns them, for the same destination choice) and writes nothing to any outbox or runs.jsonl.
- [ ] `bin/tmux-ctl` help: line 74 reads `#   tmux-ctl metrics weekly [--dry-run [--json]] [--since] [--tasks-log P]  analyze + recommend; post to Discord (or print)`; a new line `#   tmux-ctl metrics schedule install|status|uninstall  the Monday 09:00 weekly post (launchd)` stays inside the `sed -n '2,76p'` help range (adjust the range end if needed; `HelpTest` in `test_metrics_weekly.py` covers it).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_weekly.py'` → `OK`

**Steps:**

- [ ] **Step 1:** Failing tests in `test_metrics_weekly.py` using its `Base` (temp repo, fake claude via `TC_CLAUDE_BIN`, `TC_STATE`). Write project fixtures with `docs/superpowers/metrics/runs.jsonl` run lines inside the 7-day window.
- [ ] **Step 2:** Run Verify → new tests fail.
- [ ] **Step 3:** Implement in `cmd_weekly`:

```python
def _analytics_off():
    return os.environ.get("TC_ANALYTICS") == "0" or (tc_env.agent_base() / "analytics.off").exists()

def _destinations(repo):
    """[(dir, project_name_for_ideas, projects_or_None, stats_out_or_None, multi)]"""
    import discord_ops, discord_feed, metrics_analyze
    if discord_ops.configured():
        return [(tc_env.ops_dir(), Path(main_root(repo)).name, None, None, True)]
    try:
        paths = metrics_analyze.overview_projects()
    except Exception:
        paths = [main_root(repo)]
    out = []
    for p in paths:
        name = Path(p).name
        if discord_feed.channel_of(name):
            out.append((tc_env.discord_dir(name), name, [p], tc_env.state_dir() / "analytics" / name / "stats.json", False))
    return out
```

  Loop over destinations: `write_stats(repo, args.since, projects, args.tasks_log, out)`; skip when `specs_run.current == 0`; `rec = _recommend_to_file(path)`; `analytics_post.publish(...)` (non-dry) or print `json.dumps(op)` per `build_ops` op (`--json`). Sum usage, count ops, then `append` the record if `log_path(repo).is_file()`. In `main`'s `except`, skip `_log_error` when `args.sub == "weekly"`. Add `--json` to the weekly parser. Docstring line 4: kinds `batch|start|run|defect|error|dream|analytics`.
- [ ] **Step 4:** Run Verify → OK. Run `python3 -m unittest discover -s board/tests -p 'test_metrics*.py'` → OK.
- [ ] **Step 5:** Commit `feat(metrics): weekly posts to Discord and records kind analytics`.

```json:metadata
{"files": ["board/metrics.py", "bin/tmux-ctl", "board/tests/test_metrics_weekly.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_weekly.py'", "acceptanceCriteria": ["off switch env and file: analytics: off, nothing written, no model run", "ops configured: ops dir only", "per-project: own rows, no-runs project skipped", "no runs: message and no-runs record", "unavailable: posted, partial record", "one analytics record with fields, only when runs.jsonl exists", "weekly failure appends no kind:error", "--dry-run text unchanged, --dry-run --json prints ops and writes nothing", "help lines inside range"], "modelTier": "standard"}
```

---

### Task 5: The Monday 09:00 LaunchAgent

**Goal:** `tmux-ctl metrics schedule install|status|uninstall` manages `com.user.agent-board-analytics`, which runs `tmux-ctl metrics weekly` Mondays at 09:00 local.

**Files:**
- Create: `board/analytics_schedule.py`
- Modify: `bin/tmux-ctl` (a no-tmux block beside `context dream-schedule`, ~line 316)
- Test: `tools/tests/test_ctl_metrics_schedule.zsh`
- Modify: `docs/INSTALL.md` (new section after "Nightly memory consolidation")
- Test: `board/tests/test_analytics_schedule.py`

**Acceptance Criteria:**
- [ ] `board/analytics_schedule.py` is `board/dream_schedule.py` with exactly these differences (checked: no others change behaviour): `LABEL = "com.user.agent-board-analytics"`; `StartCalendarInterval {"Weekday": 1, "Hour": 9, "Minute": 0}`; `ProgramArguments [cli, "metrics", "weekly"]`; log `agent_base()/analytics.launchd.log`; launchctl seam env `AS_LAUNCHCTL` (bin dir seam `AS_BIN_DIR`); `status()` first line `loaded`/`not loaded`, then `last run: <at> <outcome>` from the newest `kind:analytics` line in this checkout's runs.jsonl, or `last run: none`; off switch shown as `off: TC_ANALYTICS=0` / `off: analytics.off` when set.
- [ ] `install` backs up an existing plist as `.bak-YYYYMMDD`, `bootout` then `bootstrap gui/<uid>`; `uninstall` boots out and removes the plist; off macOS every command prints `macOS only`, rc 2 — all as in dream_schedule.
- [ ] `tmux-ctl metrics schedule <x>` and `tmux-ctl metrics weekly …` run outside tmux; `schedule <x>` with x in install|status|uninstall runs `python3 -I board/analytics_schedule.py <x>`; anything else dies with `usage: tmux-ctl metrics schedule install|status|uninstall`. Other `metrics` subcommands still exec metrics.py.
- [ ] Tests (copy `board/tests/test_dream_schedule.py`'s Base: temp HOME, stub launchctl logging args via `AS_LAUNCHCTL`, fake `~/.local/bin/tmux-ctl`): plist fields via `plistlib.loads`, install/uninstall launchctl calls, backup, status lines. Leak check: the real `~/Library/LaunchAgents/com.user.agent-board-analytics.plist` existence is the same before and after the test run.
- [ ] INSTALL.md section "Weekly execution analytics (optional)" with the three commands, the schedule, the log path, the two off switches, the destination rule (ops bot #command-center, else each project's home channel) and "runs whatever branch the main checkout holds".

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_analytics_schedule.py' && env -u TMUX ./bin/tmux-ctl metrics schedule bogus 2>&1 | grep -c 'usage: tmux-ctl metrics schedule'` → `OK`, then `1`

**Steps:**

- [ ] **Step 1:** `cp board/dream_schedule.py board/analytics_schedule.py`, `cp board/tests/test_dream_schedule.py board/tests/test_analytics_schedule.py`; edit the test copy first to the new expectations (label, interval, args, log, seams, status lines) → run → fails.
- [ ] **Step 2:** Edit `analytics_schedule.py` to the listed differences only. Remove dream-specific status lines (per-project dream runs) and replace with the `last run` line.
- [ ] **Step 3:** Probe (lead, run 2026-11-21 on main): `env -u TMUX ./bin/tmux-ctl metrics bogus` prints `tmux-ctl: not inside tmux`, so today's `metrics)` case is unreachable from launchd. Add a no-tmux block beside the `context dream-schedule` one (~line 316, before the tmux check), and leave the `metrics)` case as it is for the other subcommands:

```zsh
if [[ "$cmd" == metrics && ( "$1" == schedule || "$1" == weekly ) ]]; then   # no tmux needed (launchd runs it)
  if [[ "$1" == schedule ]]; then
    [[ "$2" == (install|status|uninstall) ]] || die 'usage: tmux-ctl metrics schedule install|status|uninstall'
    exec python3 -I "${0:A:h:h}/board/analytics_schedule.py" "$2"
  fi
  exec python3 -I "${0:A:h:h}/board/metrics.py" "$@"
fi
```

  Add a zsh check to `tools/tests/test_ctl_dream.zsh`'s style in a new `tools/tests/test_ctl_metrics_schedule.zsh` (or extend an existing metrics zsh test if one exists): outside tmux (`env -u TMUX`), `metrics schedule bogus` prints the usage line, `metrics weekly --dry-run --since 1d` does not print `not inside tmux`, and `metrics status` still prints `not inside tmux` (mutation: widen the condition to all of `metrics` → that last check fails).
- [ ] **Step 4:** Verify → `OK` and `1`; run the new zsh test → all ok.
- [ ] **Step 5:** INSTALL.md section; commit `feat(metrics): weekly analytics LaunchAgent`.

```json:metadata
{"files": ["board/analytics_schedule.py", "bin/tmux-ctl", "docs/INSTALL.md", "board/tests/test_analytics_schedule.py", "tools/tests/test_ctl_metrics_schedule.zsh"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_analytics_schedule.py' && env -u TMUX ./bin/tmux-ctl metrics schedule bogus 2>&1 | grep -c 'usage: tmux-ctl metrics schedule'", "acceptanceCriteria": ["copy of dream_schedule with only the listed differences", "install/uninstall/backup/macOS only as dream_schedule", "tmux-ctl metrics schedule dispatch and usage", "tests incl. real plist leak check", "INSTALL.md section", "metrics weekly runs outside tmux"], "modelTier": "standard"}
```

---

### Task 6: Full suite and read-only real-state checks

**Goal:** The whole repo is green on the branch and the weekly ops built from the user's real metrics, feed and bridge state are valid Discord posts, without posting anything.

**Files:**
- Create: `docs/superpowers/notes/2026-11-21-analytics-part2-real-state.md`

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh; echo rc=$?` from the worktree: verdict line `ALL PASS` (rc 0 or 4) — quote the verdict line.
- [ ] `cd tools/discord-bridge && npm ci && npm test` → all pass (no bridge change is expected; this proves it).
- [ ] Real-state, read-only, from the worktree with the real `TC_STATE` unset (so the real `~/.local/state/agent-board` dirs are read): `python3 -I board/metrics.py --repo . weekly --dry-run --json --since 30d > <scratch>/ops.jsonl` → each line passes `discord_feed._check`, each `text` ≤ 1900, at least one flag line carries a `<https://discord.com/channels/…>` link resolved from the real feed (or the note states which piece was missing for every flag and why), buttons ≤ 5. The note records the count of ops, max text length, links found / flag lines, and the destination chosen (ops dir or project names).
- [ ] Leak check: the count of files in `~/.local/state/agent-board/discord/_ops/outbox/` and each project's `outbox/` is the same before and after (print both counts), and `git status --short` in the live checkout shows no runs.jsonl change from this run. The model run in the dry-run is real (one `claude -p`); its cost appears in the note.
- [ ] The note lists every part-1 "(part 2)" minor (ledger lines 38, 39, 69, 70, 78) with the task that closed it.

**Verify:** `grep -c '^## ' docs/superpowers/notes/2026-11-21-analytics-part2-real-state.md` → `4` (sections: Suite, Real-state ops, Leak check, Part-1 minors)

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-21-analytics-part2-real-state.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/notes/2026-11-21-analytics-part2-real-state.md", "acceptanceCriteria": ["all.zsh ALL PASS quoted", "bridge npm test passes", "real-state dry-run --json ops valid, <=1900, links counted, destination named", "outbox counts unchanged, no runs.jsonl change", "part-1 minors mapped to tasks"], "modelTier": "standard"}
```

---

### Task 7: User gate: the first real weekly post on the phone

**Goal:** One real `tmux-ctl metrics weekly` posts to the user's Discord and one `File as idea` tap files exactly one idea.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none (runtime check after merge; the live bridge may need a restart to load the merged code)

**Acceptance Criteria:**
- [ ] After merge, `tmux-ctl metrics schedule install` then `tmux-ctl metrics schedule status` → first line `loaded`.
- [ ] `tmux-ctl metrics weekly` once by hand → two posts appear in #command-center (or the project home channel), the second with `File as idea` buttons and stats.json attached; one `kind:analytics` line in runs.jsonl.
- [ ] The user taps `File as idea 1` once and again: the ideas file gains exactly one line for that recommendation, the ops `audit.jsonl` shows `filed` then `already filed`.

**Verify:** `tmux-ctl metrics schedule status | head -1; tail -2 ~/.local/state/agent-board/discord/_ops/audit.jsonl` → `loaded`, then audit lines with results `filed` and `already filed`

```json:metadata
{"files": [], "verifyCommand": "tmux-ctl metrics schedule status | head -1; tail -2 ~/.local/state/agent-board/discord/_ops/audit.jsonl", "acceptanceCriteria": ["schedule status loaded after install", "one real weekly run posts two posts with buttons and attachment, one analytics record", "two taps: one idea line, audit filed then already filed"], "modelTier": "mechanical", "userGate": true, "tags": ["user-gate"]}
```

## Dependencies

Task 2 after Task 1 (usage key, `trends_table`); Task 3 after Task 2; Task 4 after Tasks 2 and 3; Task 5 after Task 4 (`bin/tmux-ctl` help lines); Task 6 after 1-5; Task 7 after 6 and the merge.
