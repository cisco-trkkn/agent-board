# Trend Scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily code-only poll collects new items from outside sources. A weekly model pass judges them against agent-board, drafts up to 3 specs on a scout branch, and posts one digest with Approve / Reject / Revise for drafts and File as idea / Dismiss for the other findings. An approved spec lands on `main` and joins the lead's queue without another question.

**Architecture:** First, opportunity discovery's state, dismissal rule, line renderer and File/Dismiss handling move into `board/findings.py`, and `discover_post` keeps its behaviour on top of it. Then come the scout modules: `scout_fetch.py` (one fetcher per source kind), `scout_sources.py` (sources.json, the poll, the `#scout` channel), `scout_pack.py` (the context pack), `scout_eval.py` (evaluate, validate, pick), `scout_draft.py` (the draft worktree and checks), `scout_post.py` (the digest, drafts state, clicks, decisions) and `scout.py` (the CLI and the weekly pass). Two LaunchAgents run `tmux-ctl scout poll` and `tmux-ctl scout weekly`. The bridge arms a reply on Reject and Revise clicks, and the controls loop routes `ab:scout:` clicks and replies.

**Tech Stack:** Python 3 stdlib (board/), zsh (bin/tmux-ctl), Node (tools/discord-bridge), launchd.

**Spec:** `docs/superpowers/specs/2026-11-13-trend-scout-design.md`

## Global Constraints

- **State dir** `SCOUT_DIR` = `$TC_SCOUT_DIR`, else `$HOME/.local/state/agent-board/scout` (never `TC_STATE`, never `tc_env.state_dir()`). Every scout module gets it from `scout_sources.scout_dir()`. Files:
  - `sources.json`: `{"sources": [{"name": str, "kind": str, "url": str, "prefix": str (html_links only), "why": str, "added": iso, "builtin": bool}], "health": {name: {"failures": int, "last_error": str, "last_ok": iso|null}}}`. It is written on the first `poll` or `source …` call from `DEFAULT_SOURCES`. Names match `^[a-z0-9][a-z0-9._-]{0,39}$`.
  - `items.jsonl`: one item per line, `{key, source, kind, title, url, published, fetched_at, excerpt}`. `key` = `sha256(source name + "\n" + url + "\n" + (version or content hash)).hexdigest()[:16]`. `excerpt` is plain text, ≤ 4096 bytes UTF-8, cut on a character boundary. `published` is ISO or null. `fetched_at` is ISO UTC.
  - `seen.json`: `{"keys": {key: fetched_at}, "sources": {name: first poll iso}, "state": {name: per-source fetcher state (html_diff hash, npm latest, discord after id)}, "requests": {…}}`. Keys older than 180 days are pruned.
  - `poll.log` and `weekly.log`: one line per event, `<ISO local> <text>`.
  - `findings.json`: the shared findings state (Task 1 schema) for the scout's "other findings".
  - `drafts.json`: `{"drafts": {id: Draft}, "pending_copies": [id, …]}`, where Draft = `{"id", "key", "title", "slug", "path", "branch", "worktree", "week", "status": "pending"|"approved"|"rejected"|"expired"|"revise"|"superseded", "why", "value", "effort", "risk", "url", "published", "protected": bool, "post_key", "note": str|null, "reason": str|null, "created_at", "decided_at": iso|null, "decided_by": str|null}`. `id` = `sha1(finding key)[:12]` plus `-r<n>` for the n-th redraft.
  - `weekly.json`: `{"last_run_at": iso|null, "last_week": "YYYY-MM-DD"|null, "skipped_week": "YYYY-MM-DD"|null, "failed_weeks": int}`. `week` = the local date of the most recent Sunday on or before now.
  - `approved.jsonl`: `{"spec": "docs/superpowers/specs/…", "approved_at": iso, "title": str, "protected": bool, "consumed": false}`. The lead rewrites a line to `"consumed": true` (Task 13).
  - `runs/<YYYYMMDD-HHMM>/`: `items.json`, `context-pack.md`, `evaluate.json`, `model-output*.txt`; the last 8 are kept.
  - `off`: when present (or `TC_SCOUT=0`), every `poll` and `weekly` prints `scout: off` and exits 0.
- **One project.** The scout serves `agent-board` only. The project name is the constant `PROJECT = "agent-board"`. The repo root is `dream.resolve_root(PROJECT, {}, None)`; tests pass `--root`.
- **Fetch rules:** stdlib `urllib.request` only, header `User-Agent: agent-board-scout`, timeout 20 s, body cap 4 MB (the changelog is 1.3 MB), no cookies, no personal data. Tests serve fixtures from a local `http.server` and put its URLs into `sources.json`. The only base-URL overrides are `TC_SCOUT_RAW_BASE` (default `https://raw.githubusercontent.com`, for remote marketplace files) and `TC_SCOUT_DISCORD_API` (default `https://discord.com/api/v10`).
- **First poll of a source** (it has no entry in `seen.json` `sources`): every item is marked seen, and only the newest 3 are written to `items.jsonl` for `changelog_md`, `github_releases`, `rss` and `npm`. `html_links` and `html_diff` write none and only store their baseline. This keeps 446 changelog sections and the news category pages out of the first week. After that, `seen.json` `sources[name] = first poll time`.
- **Item shape returned by every fetcher:** `{"title": str, "url": str, "version": str|None, "published": iso|None, "excerpt": str, "content_hash": str|None}`. The poll adds `key`, `source`, `kind` and `fetched_at`.
- **Model binary:** `$TC_SCOUT_CLAUDE`, else `claude`. Tests always use a fake. Env scrub: `dream.SCRUB`. Process group killed on timeout (`dream._kill_group`).
- **Evaluate:** `claude -p --model sonnet --effort medium --permission-mode dontAsk --strict-mcp-config --disable-slash-commands --no-session-persistence --output-format json --allowedTools Read,Grep,Glob,WebFetch`, cwd = the run dir with the repo given as `--add-dir <root>`, timeout 900 s. The prompt limits WebFetch to the week's item URLs, and code drops any entry whose evidence URL is not an item URL (Task 6). Cost if the model fetches elsewhere: only tokens, since nothing it read off-list can be cited.
- **Draft:** `claude -p --model <frontier model> --permission-mode acceptEdits --strict-mcp-config --disable-slash-commands --no-session-persistence --output-format json --allowedTools Read,Grep,Glob,Write,Edit`, cwd = the draft worktree, timeout 1200 s. `<frontier model>` = `docs/superpowers/model-routing.json` `frontier` at the repo root (`fable` today). On a model-limit error it runs once more with `--model opus`, and writes the `weekly.log` line `draft <id>: <model> limit, retried on opus`.
- **Finding key** = `<item key>:<component>`, with the component lowercased and spaces turned into `-`.
- **Shared dismissal rule (from discovery, unchanged):** a dismissed key comes back only when its evidence count is ≥ `findings.REGROWTH` (1.5) × the dismissed count. The scout's evidence count is the number of evidence quotes the entry carries (`len(evidence)`).
- **Protected paths:** `claude/orchestrator.md`, `claude/worker.md`, any `claude/scout-*.md`, any `board/scout*.py`, `bin/tmux-ctl`. A draft is flagged when its text names one of them in backticks.
- **Button ids** (each ≤ 100 chars): `ab:scout:approve:agent-board:<id>`, `ab:scout:reject:agent-board:<id>`, `ab:scout:revise:agent-board:<id>`, and for other findings `ab:scout:file:agent-board:<kid>` and `ab:scout:dismiss:agent-board:<kid>` (`kid = sha1(key)[:12]`).
- **Digest:** one outbox `post` to `tc_env.discord_dir("agent-board")`, `tier: "progress"`, `mention_user: false`, `key: "scout-agent-board-<week>"`, text ≤ 1900 chars, the drafted spec files in `files` (absolute paths, copied to `SCOUT_DIR/runs/<run>/files/`), every model-written string through `analytics_post.escape`. Decisions edit this post (`edit` op with the same key).
- **Usage guard:** `dream.weekly_pct(now) >= dream.WEEKLY_MAX` (85) skips `weekly` unless `--force`.
- **No tmux needed:** every `tmux-ctl scout …` subcommand works outside tmux, because launchd runs it.
- **Never:** the scout pushes nothing, writes `main` only through Approve, and never edits `claude/orchestrator.md`, `claude/worker.md` or its own prompts by itself.
- **Isolation in tests:** every test sets `TC_SCOUT_DIR`, `TC_STATE` and `HOME` to temp dirs, uses a scratch git repo and a fake `claude`, and asserts the real `~/.local/state/agent-board/scout` is untouched (Task 15 leak check).
- Commit messages: conventional with scope (`feat(scout): …`, `refactor(discover): …`). End with the attribution trailer your harness specifies.

**User decisions (already made, spec "Decisions"):**
- The scout drafts specs. The user only approves, rejects or asks for a revision. An approved spec joins the queue without another question.
- Sources: Claude Code releases; Anthropic news, engineering and release notes; installed plugins; models and pricing; links posted in `#scout`; manual additions. Community sources are not defaults.
- Weekly: one Sunday pass, at most 3 drafts, skipped at ≥ 85% weekly usage. The daily poll uses no model.
- A headless launchd pipeline, not a lead task.
- Queue item: integration merge to `main` locally, no push.

**Plan-time rulings (lead, recorded in the ledger):**
- The scout's evidence count, for the shared 50% regrowth rule, is the number of evidence quotes. Discovery's rule is `count ≥ 1.5 × dismissed`, which the #10 ruling settled. Cost if wrong: a dismissed scout finding comes back a little early or late.
- `#scout` source requests and their ✅ go through the Discord REST API in the daily poll, not the bridge. The poll posts the parsed reply in `#scout`. The next poll reads ✅ reactions on that reply from `access.json` `allowFrom` users, adds the source and appends an audit line. Cost if wrong: a requested source waits up to a day.
- Reject and Revise notes: the bridge arms the digest message for one reply after an `ab:scout:reject|revise` click. A Discord reply to the digest from an allowlisted user becomes a `reply` event with `key = <custom_id>`. Reject acts at once, and a later reason is stored on the draft. Revise stores the note when it arrives. Revise with no note still redrafts. Cost if wrong: a note typed as a plain message, not as a reply, is not seen.
- The `[Scout] approved: <spec>` line goes to the lead through the board's `add_line` queue (the controls path, Approve clicked on the phone). `tmux-ctl scout approve` from a shell writes `approved.jsonl` only, and the lead picks it up at its Next-steps round. Cost if wrong: a shell-approved spec waits for the next round.
- The mid-change retry (Approve step 1) is driven by the controls tick: `scout_post.retry_copies(now)` runs at most every 10 minutes from `discord_controls.step`, and gives up after 24 h with a `decision` post. Cost if wrong: retries stop while the board is down.
- The Monday retry is a second LaunchAgent interval (Monday 07:00) that runs `scout weekly --retry`. That run does work only when `weekly.json` `skipped_week` is the current week and `last_week` is not. Cost if wrong: none beyond a no-op run.
- "The week's new items" = items with `fetched_at` after `weekly.json` `last_run_at` (when null, the last 7 days).

---

### Task 1: Extract the shared findings core

**Goal:** `board/findings.py` holds the parts discovery and the scout share (state store, dismissal rule, line rendering, File/Dismiss decision). `discover_post` uses it, and its behaviour and tests stay unchanged.

**Files:**
- Create: `board/findings.py`
- Modify: `board/discover_post.py`
- Test: `board/tests/test_findings.py` (new); `board/tests/test_discover_post.py` and `board/tests/test_discover_nightly.py` stay unedited and green

**Acceptance Criteria:**
- [ ] `findings.Store(path)` gives `locked()`, `read()`, `write(st)`, `update(fn)` and `load()`, with the flock on `<path stem>.lock` beside it and the atomic tmp + `os.replace` write. The default schema is `{"root": "", "failures": 0, "reported": {}, "dismissed": {}, "filed": {}, "posts": {}}`, `posts` cut to the last `keep` entries (default 14). The `extra` dict argument adds keys with defaults.
- [ ] `findings.REGROWTH = 1.5`. `findings.dismissed_blocks(st, key, count)` is True when `key in st["dismissed"]` and `count < REGROWTH * st["dismissed"][key]["evidence_count"]`.
- [ ] `findings.kid`, `findings.cut`, `findings.value_line(value, effort, risk, parts, cap, links=True)` (discover's `_line` without the `it` dict), `findings.escape` (= `analytics_post.escape`), `findings.URL_MAX`, `findings.MARKS`.
- [ ] `findings.decide(st, it, act, now, idea_line_fn)` applies `file`/`dismiss` to a stored post item exactly as `discover_post.click` does today. It returns `"filed"`, `"dismissed"`, `"already filed"`, `"already dismissed"` or `"already <decision>"`, and mutates `st` and `it`. `idea_line_fn(it)` returns the ideas line, so each user builds its own text.
- [ ] `discover_post` keeps every public name (`kid`, `escape`, `load_state`, `save_state`, `update`, `select`, `build_op`, `publish`, `click`, `REGROWTH`, `LIMIT`, `MARKS`) as thin uses of `findings`. `git diff main -- board/tests/test_discover_post.py board/tests/test_discover_nightly.py` is empty.
- [ ] `test_findings.py` covers the store lock and defaults, `dismissed_blocks` at 1.49× (blocked) and 1.5× (shown), `value_line` dropping a cut link, and `decide` for each return value. Mutation: change `<` to `<=` in `dismissed_blocks` → the 1.5× test fails.

**Verify:** `python3 -m unittest board.tests.test_findings board.tests.test_discover_post board.tests.test_discover_nightly board.tests.test_discover -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Write `board/tests/test_findings.py` against the API above (set `TC_STATE` to a temp dir in `setUp`). Run it: it fails with `ModuleNotFoundError: findings`.
- [ ] **Step 2:** Create `board/findings.py` by moving `_locked/_read/_write/update`, `kid`, `_cut`, `_line` and the decision body of `click` out of `discover_post.py` into the shapes above. The `Store` path for discovery is `tc_env.agent_base()/discover/<project>.json`, and the lock `<project>.lock` is unchanged. `discover_post._paths` stays and builds the `Store`.
- [ ] **Step 3:** Rewire `discover_post` to call `findings`. `click` keeps its regex, `_find` and `_edit`, and calls `findings.decide(st, it, act, now, lambda it: ideas.add(project, f"{it['title']}: {it['why']} (evidence: {it['summary']})"))`.
- [ ] **Step 4:** Run the Verify command and `python3 -m unittest discover -s board/tests -p 'test_discover*.py'`. Both print `OK`.
- [ ] **Step 5:** Commit `refactor(discover): shared findings core in board/findings.py`.

```json:metadata
{"files": ["board/findings.py", "board/discover_post.py", "board/tests/test_findings.py"], "verifyCommand": "python3 -m unittest board.tests.test_findings board.tests.test_discover_post board.tests.test_discover_nightly board.tests.test_discover -v 2>&1 | tail -3", "acceptanceCriteria": ["findings.Store with lock, defaults, atomic write", "REGROWTH and dismissed_blocks", "kid/cut/value_line/escape exported", "decide matches discover click results", "discover tests unedited and green", "test_findings with named mutation"], "modelTier": "standard"}
```

---

### Task 2: Web fetchers

**Goal:** `board/scout_fetch.py` has one fetcher per web kind (`changelog_md`, `github_releases`, `rss`, `html_links`, `html_diff`, `npm`). Each returns the Global Constraints item shape and is tested against a local HTTP server.

**Files:**
- Create: `board/scout_fetch.py`, `board/tests/fixtures/scout/` (fixtures cut from the probe samples listed in Task 4's table, each ≤ 20 KB)
- Test: `board/tests/test_scout_fetch.py`

**Acceptance Criteria:**
- [ ] `get(url, accept=None, headers=None) -> (status, bytes, content_type)` sends `User-Agent: agent-board-scout`, uses a 20 s timeout, reads at most 4 MB, sends no cookies, and raises `FetchError(str)` on a network error or a status ≥ 400.
- [ ] `fetch(source, state) -> list[item]` dispatches on `source["kind"]`. `state` is the per-source seen data the poll passes in (for `html_diff`, the previous hash).
- [ ] `changelog_md`: one item per `## <version>` section (the header form from the probe report), `title = "Claude Code <version>"`, `version` set, `excerpt` = the section text. It accepts `installed_version` from `claude --version` (first token matching `\d+\.\d+\.\d+`) and appends `(installed <v>)` to the excerpt's first line.
- [ ] `github_releases`: one item per release (`tag_name`, `html_url`, `published_at`, `body`). It uses `gh auth token` as a `Authorization: Bearer` header only when `gh auth status` exits 0. The token is never logged or put in an item.
- [ ] `rss`: RSS 2.0 `<item>` and Atom `<entry>`, title, link (Atom `link[@href]`), date, and summary or content with tags stripped.
- [ ] `html_links`: links on the index page (relative hrefs resolved against the index URL) whose URL has the same host and a path starting with the source's `prefix` and longer than it, deduped, fragment and query dropped. `title` = the anchor text, collapsed. Fixtures: `anthropic_news.index.html` (prefix `/news/`), `anthropic_engineering.index.html` (prefix `/research/`).
- [ ] `html_diff`: the text of `<main>`, else `<body>` minus `nav`, `header` and `footer` (an `html.parser.HTMLParser` subclass), whitespace collapsed, hashed with sha256. It returns one item when the hash differs from `state["hash"]` (none on the first run, which only stores the hash), with `content_hash` set. The test proves that changing only the nav, header or footer gives no item. Mutation: drop the nav/header/footer skip → that test fails.
- [ ] `npm`: one item when `dist-tags.latest` differs from `state["latest"]`, `version` = latest.
- [ ] Each kind has a new, an unchanged and a broken-response test (a 500, invalid XML or JSON, an empty body): the broken one raises `FetchError`, never another exception type.
- [ ] `excerpt` ≤ 4096 bytes UTF-8 for every kind (a fixture with a 10 KB section proves the cut).

**Verify:** `python3 -m unittest board.tests.test_scout_fetch -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** The raw probe samples are already in `board/tests/fixtures/scout/` (committed with the plan, home paths replaced by `/home/user`). Recut `changelog.md` at a section boundary (it ends mid-line), and add `-changed` variants for one `html_diff` page (main text changed) and `-navonly` (only the nav changed). Keep every fixture ≤ 20 KB.
- [ ] **Step 2:** Write the tests with a `ThreadingHTTPServer` on `127.0.0.1:0` serving the fixtures directory, plus a handler path that returns 500. Run them: they fail on import.
- [ ] **Step 3:** Implement `scout_fetch.py`. Use `xml.etree.ElementTree` for feeds (namespaces `http://www.w3.org/2005/Atom`) and `html.parser` for HTML. Never use regex to parse HTML.
- [ ] **Step 4:** Run the Verify command: `OK`.
- [ ] **Step 5:** Commit `feat(scout): web source fetchers`.

```json:metadata
{"files": ["board/scout_fetch.py", "board/tests/test_scout_fetch.py", "board/tests/fixtures/scout/"], "verifyCommand": "python3 -m unittest board.tests.test_scout_fetch -v 2>&1 | tail -3", "acceptanceCriteria": ["get() UA/timeout/cap/FetchError", "six kinds per item shape", "html_diff ignores nav/header/footer with mutation", "new/unchanged/broken per kind", "excerpt cap 4096 bytes"], "modelTier": "standard"}
```

---

### Task 3: Plugin and Discord-channel fetchers

**Goal:** `scout_fetch` gains `plugin` (an installed plugin with a newer marketplace version) and `discord_channel` (`#scout` messages through the REST API). The bot token never appears in any output.

**Files:**
- Modify: `board/scout_fetch.py`
- Test: `board/tests/test_scout_fetch_local.py`

**Acceptance Criteria:**
- [ ] `plugin` reads `$HOME/.claude/plugins/installed_plugins.json` (`{"version": 2, "plugins": {"<plugin>@<marketplace>": [{"scope", "version", "gitCommitSha", "installPath", …}]}}`) and `known_marketplaces.json` (`{"<marketplace>": {"source": {"source": "github", "repo": "<owner>/<repo>"}, …}}`). For each installed plugin whose marketplace has a `github` source, it fetches `<TC_SCOUT_RAW_BASE>/<owner>/<repo>/main/.claude-plugin/marketplace.json` (the remote copy, because the local copy can be weeks stale) and reads that plugin's `plugins[].version`. It returns one item when that version is newer than the installed `version`, comparing the numeric dotted parts with a `-suffix` sorting before the plain release (`6.5.3-dev` < `6.5.3` < `7.1.2`). `title = "<plugin> <installed> → <new>"`, and `version` = new. These are skipped without error and counted in the poll log as `plugins: <n> without a version`: a plugin whose marketplace entry has no `version`, an installed version that is a git sha (not `\d+(\.\d+)+`), and a marketplace missing from `known_marketplaces.json` (the `@anthropic-plugin-directory` ones). The remote file is fetched once per marketplace per poll. Fixtures: `plugins_installed.json`, `plugins_known_marketplaces.json`, `sp_remote.json`, under a temp `HOME`. Tests cover newer, equal, older, a sha version, no `version` field, and an unknown marketplace.
- [ ] `discord_channel`: `GET https://discord.com/api/v10/channels/<id>/messages?limit=50[&after=<last id>]` with `Authorization: Bot <token>`, the token read from `tc_env.discord_dir("agent-board")/.env` (`DISCORD_BOT_TOKEN=`). The API base can be overridden by `TC_SCOUT_DISCORD_API` so tests can use the local server. Each URL in a message's content becomes a page item (`kind` `html_diff`-style excerpt: the page's main text, cut to 4 KB). A message matching `^source:\s+(\S+)\s+(.+)$` is returned as a source request (`{"request": {"url", "why", "message_id", "author"}}`), not as an item. `state["after"]` is the newest message id seen.
- [ ] A missing `.env` or a missing channel id raises `FetchError("no token")` / `FetchError("no channel")`. The poll turns these into "skipped" (Task 4).
- [ ] Leak check: a test sets a token `tok-SECRET-123`, runs a fetch that succeeds and one that fails (401), and asserts the string is in neither stdout, stderr, the raised message nor the returned items. Mutation: include the request headers in the `FetchError` text → the test fails.

**Verify:** `python3 -m unittest board.tests.test_scout_fetch_local -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Write tests with temp `HOME` plugin trees and a local HTTP server that fakes the Discord messages endpoint and checks the `Authorization` header. Run them: they fail.
- [ ] **Step 2:** Implement both kinds in `scout_fetch.py`.
- [ ] **Step 3:** Run the Verify command: `OK`. Commit `feat(scout): plugin and #scout fetchers`.

```json:metadata
{"files": ["board/scout_fetch.py", "board/tests/test_scout_fetch_local.py"], "verifyCommand": "python3 -m unittest board.tests.test_scout_fetch_local -v 2>&1 | tail -3", "acceptanceCriteria": ["plugin newer/equal/older/missing", "discord_channel items and source requests", "no token/no channel FetchError", "token leak check with mutation"], "modelTier": "standard"}
```

---

### Task 4: Sources file, the sources CLI and the daily poll

**Goal:** `board/scout_sources.py` owns `sources.json`, `DEFAULT_SOURCES`, `scout source add|list|remove|test` and `scout poll`, including `#scout` source requests and the three-failures health rule.

**Files:**
- Create: `board/scout_sources.py`
- Test: `board/tests/test_scout_sources.py`

**Acceptance Criteria:**
- [ ] `DEFAULT_SOURCES` holds exactly the rows of the table below, each `builtin: true`. `discord_channel` `scout` exists only after the user adds it. The engineering index lists its articles under `/research/`, not `/engineering/`, so `html_links` sources carry a `prefix` field (default: the index URL's path plus `/`).

  | name | kind | url | prefix |
  | --- | --- | --- | --- |
  | `claude-code-changelog` | `changelog_md` | `https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md` | |
  | `claude-code-npm` | `npm` | `https://registry.npmjs.org/@anthropic-ai/claude-code` | |
  | `anthropic-news` | `html_links` | `https://www.anthropic.com/news` | `/news/` |
  | `anthropic-engineering` | `html_links` | `https://www.anthropic.com/engineering` | `/research/` |
  | `claude-blog` | `rss` | `https://claude.com/resources/articles/rss.xml` | |
  | `claude-code-release-notes` | `html_diff` | `https://code.claude.com/docs/en/changelog` | |
  | `api-release-notes` | `html_diff` | `https://platform.claude.com/docs/en/release-notes/overview` | |
  | `models-overview` | `html_diff` | `https://platform.claude.com/docs/en/models/overview` | |
  | `api-pricing` | `html_diff` | `https://platform.claude.com/docs/en/about-claude/pricing` | |
  | `plugins` | `plugin` | `~/.claude/plugins` | |

  (All ten answered HTTP 200 on 2026-11-21. The probe's evidence and the raw samples are in `board/tests/fixtures/scout/`.)

- [ ] `source add <name> --kind <kind> --url <url> --why "<text>"` refuses an unknown kind, a name not matching the pattern, a duplicate name, and a URL that is not `https://…` (for `discord_channel`, not `^\d{15,22}$`). Each refusal exits 2 and prints `scout: <reason>`. On success it prints `added <name> (<kind>)`.
- [ ] `source list` prints `name\tkind\turl\tfailures` per source. `source remove <name>` removes it (exit 2 if unknown). `source test <name>` fetches once, prints `title\turl` per item, and writes nothing (the test compares the `SCOUT_DIR` tree before and after).
- [ ] `poll`: for every source, fetch; drop items whose key is in `seen.json`; append the rest to `items.jsonl`; add their keys; store `html_diff`/`npm`/`discord_channel` state. A `FetchError` or any exception logs `<ts> poll <name>: <error>` in `poll.log`, bumps `health[name].failures`, and goes on. A success resets it to 0 and sets `last_ok`. A missing `discord_channel` source logs `poll scout: skipped (no #scout channel set)` once per poll. The last line is `poll: <n> new from <m> sources, <f> failed`.
- [ ] First-poll test (Global Constraints, "First poll of a source"): a changelog fixture with 6 sections writes 3 items on the first poll. One new section added → the second poll writes 1. Mutation: drop the first-poll cap → the first poll writes 6.
- [ ] Dedupe test: two polls over unchanged fixtures add items once. Mutation: skip the `seen.json` check → the second poll doubles the lines.
- [ ] `health_report()` returns the sources with `failures >= 3`. Test: three failing polls → listed, then one success → not listed.
- [ ] `#scout` requests: a request from an `allowFrom` user gets a reply posted through the REST API (`POST /channels/<id>/messages`, `message_reference` set) with the text `source request: <name> (<kind>) — react ✅ to add`, recorded in `seen.json` `requests: {reply message id: {url, why, name, kind}}`. The next poll reads `GET …/messages/<reply id>/reactions/%E2%9C%85`. When an `allowFrom` user reacted, the source is added and `discord_feed.audit_append(discord_dir, user, "scout-source", name, "added")` runs. Without the ✅ nothing is added and the request stays pending (at most 14 days, then dropped). The kind guess is `rss` when the URL's `Content-Type` contains `xml` or the body starts with `<?xml`/`<rss`/`<feed`, else `html_links`. The name is the URL host's first label plus the path's first segment, slugged and deduped with `-2`. Tests cover with ✅, without ✅, the ✅ from a user not in `allowFrom` (not added), and a request from a non-allowlisted author (ignored).

**Verify:** `python3 -m unittest board.tests.test_scout_sources -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Write the tests: local HTTP server, fixtures from Task 2, a fake Discord REST handler, temp `TC_SCOUT_DIR`/`TC_STATE`/`HOME`. Run them: they fail.
- [ ] **Step 2:** Implement `scout_sources.py` with `scout_dir()`, `load()`/`save()` (atomic), `add/remove/list/test_source`, `poll(now)`, `health_report()`, and a `main(argv)` for the `source` and `poll` subcommands.
- [ ] **Step 3:** Run the Verify command: `OK`. Commit `feat(scout): sources and the daily poll`.

```json:metadata
{"files": ["board/scout_sources.py", "board/tests/test_scout_sources.py"], "verifyCommand": "python3 -m unittest board.tests.test_scout_sources -v 2>&1 | tail -3", "acceptanceCriteria": ["DEFAULT_SOURCES from probe table", "source add refusals exit 2", "list/remove/test, test writes nothing", "poll appends, dedupes (mutation), logs failures", "health_report three-failures rule", "#scout request with/without ✅, allowFrom checks"], "modelTier": "standard"}
```

---

### Task 5: The context pack

**Goal:** `board/scout_pack.py` builds `context-pack.md` (≤ 30 KB) from the repo and local state, as spec §3 step 1 lists.

**Files:**
- Create: `board/scout_pack.py`
- Test: `board/tests/test_scout_pack.py`

**Acceptance Criteria:**
- [ ] Sections in order: `## Shared context` (the context file `tc_env`'s context dir `/<project>.md`: `${TC_CONTEXT_DIR:-$HOME/.local/state/agent-board/context}/agent-board.md`), `## Layout` (README.md's `## Layout` section up to the next `## `), `## Specs` (one line per `docs/superpowers/specs/*.md`: `<path> — <first # title> — <state>`), `## Open ideas` (`ideas.load("agent-board")` open titles), `## Versions` (`claude --version` output, and each installed plugin with its version), `## Claude Code features in use` (hook event names from `claude/plugin/hooks/hooks.json`, the mods index file names if `claude/mods/` exists, the top-level keys of `claude/session-settings.json`).
- [ ] Spec state: `merged` when `git log main --oneline -- <spec>` shows a commit and a `Plan & run:` merge exists for it (a `docs(metrics): <basename>` commit on main), `superseded` when its text has a line starting `Status:` containing `superseded`, else `queued`.
- [ ] Size cap: when over 30 KB, cut in this order until it fits: Specs lines beyond the newest 60, then Open ideas beyond 40, then the Shared context to its first 12 KB. A last hard cut at 30 KB on a line boundary. A test builds a 200-spec repo and a 50 KB context file and asserts `len(pack.encode()) <= 30720` and that all 6 headings are present. Mutation: remove the hard cut → the test fails.
- [ ] A missing input (no ideas file, no hooks.json) gives that section the line `(none)`, never an error.

**Verify:** `python3 -m unittest board.tests.test_scout_pack -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Write the tests on a scratch git repo with a README, specs and hooks.json, temp `TC_CONTEXT_DIR`/`TC_IDEAS_DIR`, and a fake `claude` on `PATH` printing `2.1.330 (Claude Code)`. Run them: they fail.
- [ ] **Step 2:** Implement `build(root, now) -> str`.
- [ ] **Step 3:** Verify `OK`. Commit `feat(scout): context pack`.

```json:metadata
{"files": ["board/scout_pack.py", "board/tests/test_scout_pack.py"], "verifyCommand": "python3 -m unittest board.tests.test_scout_pack -v 2>&1 | tail -3", "acceptanceCriteria": ["six sections in order", "spec state merged/superseded/queued", "30 KB cap order with mutation", "missing inputs give (none)"], "modelTier": "standard"}
```

---

### Task 6: Evaluate, validate and pick

**Goal:** `board/scout_eval.py` runs the evaluate model step, keeps only valid entries, and picks at most 3 drafts plus the overlap notes and other findings.

**Files:**
- Create: `board/scout_eval.py`, `claude/scout-evaluate.md`
- Test: `board/tests/test_scout_eval.py`

**Acceptance Criteria:**
- [ ] `claude/scout-evaluate.md` tells the model: read `items.json` and `context-pack.md` in the current directory; read repo files with Read/Grep/Glob under the `--add-dir` root; fetch only URLs listed in `items.json`; answer with one JSON object `{"entries": [...]}` in the spec §3 step 2 shape; every entry quotes evidence verbatim from an item excerpt or a fetched page; no entry for an item that would not improve agent-board.
- [ ] `run_evaluate(run_dir, root) -> (fail|None, entries, info)` builds the argv from Global Constraints. It parses the `--output-format json` envelope as `discover.run_model` does (fence unwrap, `is_error` false, `result` a string), writes `evaluate.json` only on success, and returns `info = {"cost_usd", "usage", "model_s"}`. A timeout returns `"model timeout"`, a non-zero exit `"model exit <n>"`, a bad envelope `"model error"`.
- [ ] `validate(entries, items, findings_state)`: drop an entry whose `item` is not a key in the week's items, whose `evidence` has no entry with a non-empty `quote`, whose `value` is not in `high|medium|low` or `effort` not in `S|M|L`, or whose evidence URL is not an item URL. Then compute the finding key and drop it when it is in `filed`, in `reported` (unless regrown per the shared rule), or in `dismissed` and `findings.dismissed_blocks` is true. Each drop reason is counted in `info["dropped"]`. Tests: unknown item, no quote, a URL outside the items, already reported, dismissed and not regrown (2 quotes against 2), dismissed and regrown (3 quotes against 2).
- [ ] `pick(valid, revise_first, queued_specs)`: first the drafts in `revise_first` (pending revisions, Task 10), then the valid entries by value (high, medium, low), then effort (S, M, L), then item `published` (newest first). The total is capped at 3. An entry whose `overlaps` names a spec path in `queued_specs` (state `queued` from the pack) is not drafted. It becomes the note `<spec>: could use <what_it_enables> (<url>)`. The rest, up to 10, become other findings. Tests cover order, the cap counting revisions, and the overlap rule. Mutation: sort effort before value → the order test fails.

**Verify:** `python3 -m unittest board.tests.test_scout_eval -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Write the prompt file and the tests with a fake `claude` script (`TC_SCOUT_CLAUDE`) that prints a canned envelope from a fixture file named in an env var, and one that sleeps (timeout set to 2 s through a module constant patched in the test).
- [ ] **Step 2:** Implement `scout_eval.py`.
- [ ] **Step 3:** Verify `OK`. Commit `feat(scout): evaluate, validate and pick`.

```json:metadata
{"files": ["board/scout_eval.py", "claude/scout-evaluate.md", "board/tests/test_scout_eval.py"], "verifyCommand": "python3 -m unittest board.tests.test_scout_eval -v 2>&1 | tail -3", "acceptanceCriteria": ["prompt file", "run_evaluate argv/envelope/failures", "validate drops with reasons", "pick order, cap 3 incl. revisions, overlap notes, mutation"], "modelTier": "standard"}
```

---

### Task 7: Draft a spec in the scout worktree

**Goal:** `board/scout_draft.py` drafts each pick as a spec on branch `scout/<week>` in `.claude/worktrees/scout-<week>`, checks it, and commits it with the `Scout-Item` trailer.

**Files:**
- Create: `board/scout_draft.py`, `claude/scout-draft.md`
- Test: `board/tests/test_scout_draft.py`

**Constraints:**
- The worktree is created from `main` at the repo root (`git worktree add -b scout/<week> <root>/.claude/worktrees/scout-<week> main`), or reused when it exists for this week.
- The model is the frontier tier's model with the Opus fallback, per Global Constraints. It runs with a 20-minute cap and the `claude/scout-draft.md` prompt. The prompt asks for the spec form of spec §3 step 4 (header line `Proposed by: scout · Source: <url> (<published date>)`; sections Problem, Decisions with each marked *proposed, not approved*, Design, Error handling, Testing, Out of scope), at `docs/superpowers/specs/<week>-<slug>-design.md`, citing only files it has read. For a revision it passes the user's note and the previous draft path.
- Model-limit detection: the envelope `is_error` true with a result text matching `(?i)usage limit|rate limit|limit reached|overloaded`, or exit code with stderr matching the same.
- The draft step never touches the live checkout, and never pushes.

**Acceptance Criteria:**
- [ ] `draft(root, week, pick, note=None, prev=None) -> Draft | Dropped`, where Dropped = `{"id", "title", "why": "<reason>"}`.
- [ ] Spec file missing after the run → dropped `no spec written`. Any backticked repo path (regex `` `([\w./-]+\.(py|zsh|js|md|sh|json|plist))` `` or a backticked path that starts with `board/`, `bin/`, `claude/`, `tools/` or `docs/`) that does not exist in the worktree → dropped `cites missing <path>`, and the file is removed from the worktree. Test: a fake model writing a spec that cites `board/nope.py` → dropped with that reason.
- [ ] The protected flag (Global Constraints list) is set when the spec names a protected path in backticks. Test: a spec citing `claude/orchestrator.md` → `protected: true`. Mutation: an empty protected list → the test fails.
- [ ] A kept draft is committed on the scout branch with only its spec path staged (`git add -- <path>`), message `docs(spec): <title> (scout draft)` and trailer `Scout-Item: <finding key>`. A test reads `git log -1 --format=%B scout/<week>` and finds the trailer.
- [ ] Model limit on the frontier model → one rerun with `--model opus` and the log line. Any other failure, or the cap reached → dropped `model <reason>`. Tests use a fake `claude` that fails the first call with a limit envelope and succeeds the second.
- [ ] A test asserts the scratch repo's `main` HEAD and working tree are unchanged after a draft.

**Verify:** `python3 -m unittest board.tests.test_scout_draft -v 2>&1 | tail -3` → `OK`

```json:metadata
{"files": ["board/scout_draft.py", "claude/scout-draft.md", "board/tests/test_scout_draft.py"], "verifyCommand": "python3 -m unittest board.tests.test_scout_draft -v 2>&1 | tail -3", "acceptanceCriteria": ["draft returns Draft or Dropped", "missing-spec and missing-citation drops", "protected flag with mutation", "path-scoped commit with Scout-Item trailer", "opus fallback once on limit", "main untouched"], "modelTier": "frontier"}
```

---

### Task 8: Digest, drafts state and clicks

**Goal:** `board/scout_post.py` renders and posts the weekly digest, keeps `drafts.json` and the scout's `findings.json`, and handles every `ab:scout:` click and reply, so each decision edits the post.

**Files:**
- Create: `board/scout_post.py`
- Test: `board/tests/test_scout_post.py`

**Acceptance Criteria:**
- [ ] `build_op(week, drafts, others, overlaps, dropped, health, tokens)` renders, in order: `🛰 scout agent-board <week>: <d> drafted, <o> other`; one numbered block per draft (title, why, `value <v> · effort <e> · risk <r> · source: [link](url)` through `findings.value_line`, and `⚠ touches protected files` when flagged); `Other findings:` numbered on from the drafts (through `findings.value_line`); `Overlaps:`, `Dropped:`, `Source health:` (each source with ≥ 3 failures, plus `#scout not set` when there is no `discord_channel` source), and `tokens: <total>`. Each section is left out when empty. Text ≤ 1900, shrinking like discovery's `_fit` (a shared cap loop over every model string; the section lines survive). Button rows: per draft `[Approve n (3), Reject n (4), Revise n (2)]`, per other finding `[File as idea n (1), Dismiss n (2)]`, at most 5 rows. Drafts come first; other findings beyond the row limit are listed without buttons. `files` holds the draft spec copies.
- [ ] `publish(...)` writes the op and the state under the drafts lock: drafts stored with `status: pending` and `post_key`, other findings stored as a `findings` post (`posts[week]`) and marked `reported`. A failed outbox write leaves both states as they were (the test makes `outbox_write` raise).
- [ ] `click(user, cid, now, add_line=None)` for `approve|reject|revise|file|dismiss`: a project other than `agent-board` → `"ignored"`; an unknown id → `"unknown"`; a decided draft → `"already <status>"`. `file`/`dismiss` go through `findings.decide`, whose ideas line is `scout: <title> — <what_it_enables> (<url>)`. `approve` sets the draft to `approved` and calls `approve_fn(draft, add_line)`, where `click(..., approve_fn=None)` defaults to `scout_decisions.approve` imported inside the function, because Task 9 creates that module. Task 8 tests pass a recorder, `reject` sets `rejected` and records the finding key as dismissed with `evidence_count = len(evidence)`, and `revise` sets `revise` (Task 9 handles redraft). Each click edits the post (`edit` op, same key): a decided draft shows `— ✅ approved`, `— ✖ rejected`, `— ✏ revise` or `— ⌛ expired`, and loses its buttons.
- [ ] `reply(user, key, text, now)` for a `reply` event whose key is an `ab:scout:reject|revise` id: it stores `reason`/`note` (≤ 500 chars) on that draft and returns `"noted"`. Any other key returns `"ignored"`.
- [ ] Delivery semantics, each with a test: two clicks on the same Approve at once (two threads) → one approval, one `"already approved"`; a reject arriving after an approve → `"already approved"`, the spec stays approved; a repeated `reply` → the last text kept, still `"noted"`.
- [ ] `discord_controls.consume_events` routes a `click` starting `ab:scout:` to `scout_post.click(user, cid, now, add_line=lambda t: add_line(project, t))`, and a `reply` event whose key starts `ab:scout:` to `scout_post.reply`, each with an audit line (`click` / `scout-reply`), `rejected` for a user not in `allowFrom`. This goes before the dialog consumer's `reply` branch. `board/tests/test_discord_controls.py` gains one test per route.

**Verify:** `python3 -m unittest board.tests.test_scout_post board.tests.test_discord_controls -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Write the tests with a temp outbox (`TC_STATE`) and `TC_SCOUT_DIR`. Run them: they fail.
- [ ] **Step 2:** Implement `scout_post.py` on `findings.Store` (`SCOUT_DIR/findings.json`) and a second `findings.Store(SCOUT_DIR/drafts.json, extra={"drafts": {}, "pending_copies": []})`.
- [ ] **Step 3:** Add the two routes to `discord_controls.py`. Find where `reply` events are consumed today (`discord_dialogs.consume_event`) and put the scout check before it.
- [ ] **Step 4:** Verify `OK`, and `python3 -m unittest discover -s board/tests -p 'test_discord_*.py'` is `OK`. Commit `feat(scout): digest, drafts state and clicks`.

```json:metadata
{"files": ["board/scout_post.py", "board/discord_controls.py", "board/tests/test_scout_post.py", "board/tests/test_discord_controls.py"], "verifyCommand": "python3 -m unittest board.tests.test_scout_post board.tests.test_discord_controls -v 2>&1 | tail -3", "acceptanceCriteria": ["digest sections, cap, rows", "publish atomic with outbox failure", "click results and post edits", "reply stores reason/note", "concurrent/out-of-order/repeat tests", "controls routes with audit"], "modelTier": "standard"}
```

---

### Task 9: Approve, reject, revise, expire, cleanup

**Goal:** `board/scout_decisions.py` carries out each decision: Approve copies the spec onto `main` path-scoped (with the mid-change retry), adds the ideas `--done` line, appends `approved.jsonl` and tells the lead. Revise redrafts, a 4-week-old draft expires, and a fully decided scout branch and worktree are removed.

**Files:**
- Create: `board/scout_decisions.py`
- Modify: `board/ideas.py` (`add_done(project, text, spec)`), `bin/tmux-ctl` (`idea --done "<text>" --spec <path>`), `board/discord_controls.py` (the throttled `retry_copies` call)
- Test: `board/tests/test_scout_decisions.py`, `board/tests/test_ideas.py` (one new test)

**Acceptance Criteria:**
- [ ] `approve(draft, root, now, add_line=None)`: when the live checkout at `root` is mid-change (a merge or rebase in progress: `.git/MERGE_HEAD`, `.git/rebase-merge`, `.git/rebase-apply`; or `git status --porcelain -- <spec path>` not empty; or HEAD not on `main`), it adds the id to `pending_copies` and returns `"approved, waiting for main"`. Otherwise it runs `git -C <root> show scout/<week>:<path> > <root>/<path>`, `git add -- <path>`, and `git commit -m "docs(spec): <title> (scout)" -m "Scout-Item: <key>" -- <path>`. Only that path is in the commit (`git show --stat HEAD` lists one file). Then it calls `ideas.add_done("agent-board", "scout: <title>", <path>)`, appends `approved.jsonl`, and, when `add_line` is given, calls `add_line("[Scout] approved: <path>")`. It returns `"approved"`. Tests: a clean scratch repo (one file in the commit, trailer present), another file dirty in the checkout (still one file committed, the dirty file untouched), the spec path dirty (waits), a merge in progress (waits).
- [ ] `retry_copies(root, now)`: for each pending id older than 24 h, drop it and post a `decision` line `scout: <title> approved but main stayed busy for 24 h — run tmux-ctl scout approve <id>`. Otherwise retry `approve`. `discord_controls.step` calls it at most every 600 s (the last call time kept in `controls-state.json` `scout_retry_at`). Tests cover the throttle and the 24-hour give-up.
- [ ] `ideas.add_done(project, text, spec)` appends `- [x] <YYYY-MM-DD HH:MM> · <text> → <spec>` under the ideas lock. `tmux-ctl idea --done "<text>" --spec <path>` calls it. A test in `test_ideas.py` reads the line back through `ideas.load` with status `done`.
- [ ] `redraft(id)`: a draft in `revise` is redrafted now through `scout_draft.draft(..., note, prev)`. The new draft gets id `<id>-r<n>`, the old one becomes `superseded`, and a new digest entry is posted as its own `post` (key `scout-agent-board-<week>-<newid>`). `pending_revisions()` lists the `revise` drafts for the Sunday pick (Task 6 `revise_first`).
- [ ] `expire(now)`: a `pending` draft with `created_at` older than 28 days → `rejected`, reason `expired`, dismissed in findings, the post edited.
- [ ] `cleanup(root)`: for each `scout/<week>` branch whose drafts are all decided (`approved`, `rejected`, `expired`, `superseded`), run `git worktree remove --force <worktree>` and `git branch -D scout/<week>`. Never touch any other branch. A test has one decided week and one undecided week: only the decided one is gone.
- [ ] Integration test: `scout_post.click(user, "ab:scout:approve:agent-board:<id>", now, add_line=rec)` with the default `approve_fn` makes the commit, adds the ideas line, appends `approved.jsonl` and records `[Scout] approved: <path>` in `rec`.
- [ ] Delivery: `approve` on an already approved id → `"already approved"` and no second commit (test counts commits).

**Verify:** `python3 -m unittest board.tests.test_scout_decisions board.tests.test_ideas -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Write the tests on a scratch repo with a `scout/<week>` branch holding a spec, a fake `add_line` recorder, a temp ideas dir and a temp outbox. Run them: they fail.
- [ ] **Step 2:** Implement `scout_decisions.py`, `ideas.add_done` (plus an `add-done --project <p> --spec <path> -- <text>` subcommand in `ideas.py`'s `main`), and the `--done` flag in the `idea)` branch of `bin/tmux-ctl`:

```zsh
  idea)
    if [[ "$1" == --done ]]; then
      [[ -n "$2" && "$3" == --spec && -n "$4" ]] || die 'usage: tmux-ctl idea --done "<text>" --spec <path>'
      python3 -I "${0:A:h:h}/board/ideas.py" add-done --project "$FEEDKEY" --spec "$4" -- "$2"
    else
      [[ -n "$*" ]] || die "usage: tmux-ctl idea <text>"
      python3 -I "${0:A:h:h}/board/ideas.py" add --project "$FEEDKEY" -- "$*"
    fi ;;
```

- [ ] **Step 3:** Wire `retry_copies` into `discord_controls.step` behind the 600 s throttle.
- [ ] **Step 4:** Verify `OK`. Commit `feat(scout): approve, reject, revise, expire`.

```json:metadata
{"files": ["board/scout_decisions.py", "board/ideas.py", "bin/tmux-ctl", "board/discord_controls.py", "board/tests/test_scout_decisions.py", "board/tests/test_ideas.py"], "verifyCommand": "python3 -m unittest board.tests.test_scout_decisions board.tests.test_ideas -v 2>&1 | tail -3", "acceptanceCriteria": ["approve path-scoped one-file commit with trailer", "mid-change waits", "retry throttle and 24h give-up", "ideas add_done and idea --done", "redraft supersedes", "expire after 28 days", "cleanup only decided branches", "repeat approve no second commit"], "modelTier": "standard"}
```

---

### Task 10: The bridge arms a reply on Reject and Revise

**Goal:** After a `ab:scout:reject|revise` click, the bridge arms the clicked message for one reply, so a Discord reply to the digest becomes a `reply` event keyed by the custom id.

**Files:**
- Modify: `tools/discord-bridge/bridge.js` (`onInteraction`)
- Test: `tools/discord-bridge/test/scout-reply.test.js`

**Acceptance Criteria:**
- [ ] In `onInteraction`, after the click event is written for an id matching `^ab:scout:(reject|revise):`, it sets `st.reply_armed[i.message.id] = id` and calls `save()`. A later armed click on the same message replaces the key (the newest click wins).
- [ ] `onMessage` is unchanged: a reply from an allowlisted user to that message writes `{type: 'reply', key: <custom id>, text, user, message_id}` and disarms.
- [ ] Tests: a reject click then a reply → one reply event with that key; a reply with no click → no event; an approve click → not armed. Use the harness style of the existing bridge tests (find the test that covers `reply_armed` for dialogs and follow it). Differences from the dialog arming: no `Reply` button, the arm comes from the decision click itself, and the edit that clears `reply_armed` for a key (line ~327, by dialog key) must not clear a scout arm. Check that function's key match and add a test that a scout post `edit` keeps the arm.

**Verify:** `cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'` → `# fail 0`

**Steps:**

- [ ] **Step 1:** In a fresh worktree, run `npm ci` in `tools/discord-bridge` first.
- [ ] **Step 2:** Write the test and run `npm test`: the new test fails.
- [ ] **Step 3:** Implement and run `npm test`: `# fail 0`. Commit `feat(bridge): arm a reply after scout reject/revise`.

```json:metadata
{"files": ["tools/discord-bridge/bridge.js", "tools/discord-bridge/test/scout-reply.test.js"], "verifyCommand": "cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'", "acceptanceCriteria": ["reject/revise click arms the message", "reply event keyed by custom id", "no arm without click or on approve", "scout post edit keeps the arm"], "modelTier": "standard"}
```

---

### Task 11: The weekly pass and the scout CLI

**Goal:** `board/scout.py` is the CLI (`poll`, `source …`, `weekly [--dry-run] [--force] [--retry]`, `approve|reject|revise <id> [--note]`, `redraft <id>`, `pack [--root <dir>]`, which prints the context pack) and runs the Sunday pass end to end, with the skip rules, the failure posts and the metrics record.

**Files:**
- Create: `board/scout.py`
- Modify: `bin/tmux-ctl` (a `scout` branch next to `discover`, in the no-tmux list, usage lines in the header), `board/metrics.py` (docstring kinds list gains `scout`)
- Test: `board/tests/test_scout_weekly.py`

**Acceptance Criteria:**
- [ ] `weekly`: off switch → `scout: off`. When `--force` is absent and `weekly_pct >= 85` → `scout: skipped, weekly <n>%`, a `weekly.log` line, and `skipped_week = week`. `--retry` with `skipped_week != week` or `last_week == week` → `scout: nothing to retry`. No new items since `last_run_at` → `scout: no new items`, no post, `last_week` and `last_run_at` set. Otherwise: pack, evaluate, validate, pick, draft (each pick), expire, publish, cleanup, then `last_week`, `last_run_at` and `failed_weeks = 0`.
- [ ] A model step failure (evaluate fails, or every draft fails with a model reason while picks existed) → no digest, the reason in `weekly.log`, `failed_weeks += 1`. When it reaches 2 → one outbox `post`, `tier: "critical"`, `mention_user: true`, text `🛰 scout: two Sundays failed — <reason>`, key `scout-agent-board-fail-<week>`.
- [ ] Metrics: when the repo's `docs/superpowers/metrics/runs.jsonl` exists, it appends `{"kind": "scout", "at", "outcome": "posted"|"no-new-items"|"skipped"|"failed", "items", "findings", "drafts", "dropped", "tokens": {"evaluate": usage, "draft": [usage…]}, "cost_usd", "duration_s"}`.
- [ ] `--dry-run` runs every step, including the model steps and the draft worktree in a temp dir, but writes no `SCOUT_DIR` state, makes no commit on the real repo and no outbox file, and prints the op's text and `buttons: …`. The test compares the `SCOUT_DIR` tree, the outbox dir and `git -C <root> for-each-ref` before and after. Mutation: let dry-run call `publish` → the test fails.
- [ ] Draft worktrees in `--dry-run` are made from a temporary clone (`git clone --shared <root> <tmp>`), not from the real repo.
- [ ] Tests for: the 85% skip and the Monday retry (skip on Sunday, run on `--retry` Monday, a second `--retry` → nothing), no new items, the full happy path with a fake model (one draft, two other findings, one overlap, one dropped), two failed Sundays → one critical post.
- [ ] `tmux-ctl scout …` dispatches outside tmux: `TMUX= zsh bin/tmux-ctl scout source list` prints the list (test in `test_scout_weekly.py` through `subprocess` with `TC_SCOUT_DIR` set).

**Verify:** `python3 -m unittest board.tests.test_scout_weekly -v 2>&1 | tail -3` → `OK`

```json:metadata
{"files": ["board/scout.py", "bin/tmux-ctl", "board/metrics.py", "board/tests/test_scout_weekly.py"], "verifyCommand": "python3 -m unittest board.tests.test_scout_weekly -v 2>&1 | tail -3", "acceptanceCriteria": ["skip rules: off, 85%, retry, no items", "two failed Sundays critical post", "metrics kind scout", "dry-run writes nothing (mutation), clone for drafts", "happy path with fake model", "tmux-ctl scout outside tmux"], "modelTier": "frontier"}
```

---

### Task 12: The two LaunchAgents

**Goal:** `board/scout_schedule.py` installs `com.user.agent-board-scout-poll` (daily 06:00) and `com.user.agent-board-scout-weekly` (Sunday 07:00 `scout weekly`, Monday 07:00 `scout weekly --retry`) with `tmux-ctl scout schedule install|status|uninstall`.

**Files:**
- Create: `board/scout_schedule.py`
- Modify: `bin/tmux-ctl` (`scout schedule` dispatch)
- Test: `board/tests/test_scout_schedule.py`

**Acceptance Criteria:**
- [ ] It copies `board/discover_schedule.py`'s structure (`MacOnly`, `_home`, `_cli_path`, `_launchctl`, install/uninstall/status). The differences: two labels and two plists; the poll plist has `StartCalendarInterval {"Hour": 6, "Minute": 0}` and `ProgramArguments [cli, "scout", "poll"]`; the weekly job is two plists because the Monday run has different arguments: `com.user.agent-board-scout-weekly` (`{"Weekday": 0, "Hour": 7, "Minute": 0}`, `[cli, "scout", "weekly"]`) and `com.user.agent-board-scout-weekly-retry` (`{"Weekday": 1, "Hour": 7, "Minute": 0}`, `[cli, "scout", "weekly", "--retry"]`). The env also pins `TC_SCOUT_DIR` when set. The logs are `SCOUT_DIR/launchd-poll.log` and `SCOUT_DIR/launchd-weekly.log`. No other behaviour differs from discover_schedule (checked by reading it side by side).
- [ ] Tests (as `test_discover_schedule.py`, with `launchctl` faked): plist contents for all three, install writes three files and bootstraps three labels, uninstall removes them, status prints each label's loaded state and the last `poll.log`/`weekly.log` line.
- [ ] The spec says "two launchd jobs". Three plists serve those two jobs, and status lists them as `poll`, `weekly` and `weekly (Monday retry)`.

**Verify:** `python3 -m unittest board.tests.test_scout_schedule -v 2>&1 | tail -3` → `OK`

```json:metadata
{"files": ["board/scout_schedule.py", "bin/tmux-ctl", "board/tests/test_scout_schedule.py"], "verifyCommand": "python3 -m unittest board.tests.test_scout_schedule -v 2>&1 | tail -3", "acceptanceCriteria": ["three plists with exact intervals and args", "install/uninstall/status with fake launchctl", "differences from discover_schedule named"], "modelTier": "standard"}
```

---

### Task 13: Lead rule, docs and README

**Goal:** The lead knows what to do with `[Scout] approved:` and `approved.jsonl`, and the README and docs describe the scout.

**Files:**
- Modify: `claude/orchestrator.md` (Ideas inbox section), `README.md` (Commands, Layout), `docs/INSTALL.md` (the `scout schedule install` step next to `discover schedule install`)
- Test: `tools/tests/test_orchestrator_rules.zsh` if it exists (grep the rules), else a new `board/tests/test_scout_docs.py` that greps the three files

**Acceptance Criteria:**
- [ ] `claude/orchestrator.md`, Ideas inbox, gains one bullet with this exact text:

  `- **Scout approvals.** A line \`[Scout] approved: <spec path>\`, or at a Next steps round each line of \`~/.local/state/agent-board/scout/approved.jsonl\` (\`TC_SCOUT_DIR\` overrides) with \`"consumed": false\`: create a pending \`Plan & run: <spec path>\` task blocked by the last queued \`Plan & run:\` task, with \`metadata.queue = {"integration": "merge", "push": false, "answeredAt": "<approved_at>"}\` (plus the running batch id in Queue mode), then rewrite that line with \`"consumed": true\`. Ask nothing: the Approve is the user's queue answer. When the line has \`"protected": true\`, post one \`decision\` line before the spec runs: \`scout spec <title> changes protected files; approved by you at <time>\`.`
- [ ] README: `tmux-ctl scout …` in Commands, and the `board/scout*.py` modules in Layout, one line each. INSTALL: one line, `tmux-ctl scout schedule install`.
- [ ] The test greps `Scout approvals` and `approved.jsonl` in `claude/orchestrator.md`, `scout schedule install` in `docs/INSTALL.md`, and `scout_sources.py` in `README.md`.

**Verify:** `grep -c 'Scout approvals' claude/orchestrator.md; grep -c 'scout schedule install' docs/INSTALL.md` → `1` and `1`

```json:metadata
{"files": ["claude/orchestrator.md", "README.md", "docs/INSTALL.md"], "verifyCommand": "grep -c 'Scout approvals' claude/orchestrator.md; grep -c 'scout schedule install' docs/INSTALL.md", "acceptanceCriteria": ["orchestrator bullet exact text", "README commands and layout lines", "INSTALL line", "grep test"], "modelTier": "mechanical"}
```

---

### Task 14: Full suite and read-only real-state checks

**Goal:** Every suite passes on the branch, the isolation leak check passes, and the scout reads the user's real state without writing to it.

**Files:**
- Create: `docs/superpowers/notes/2026-11-21-scout-real-state.md`
- Test: `board/tests/test_scout_isolation.py`

**Acceptance Criteria:**
- [ ] `test_scout_isolation.py` runs `poll`, `weekly` (fake model) and an approve click with every env var pointed at temp dirs. It snapshots `~/.local/state/agent-board/scout` (absent or its mtime tree), the real ideas file's mtime, the real discord outbox listing and the repo's `git for-each-ref` output before and after, and asserts all are unchanged. It prints how many paths it compared.
- [ ] `zsh tools/tests/all.zsh; echo rc=$?` → the ALL PASS verdict line, with rc 0 or 4 (rc 4 = over the time budget, accepted on this machine).
- [ ] Real-state checks, read only, each command and output in the note: `TC_SCOUT_DIR=<tmp> tmux-ctl scout source test <name>` for every default source (each prints ≥ 1 item, or the note names the source and why it has none this week); `tmux-ctl scout pack --root ~/agent-board | wc -c` ≤ 30720 with all six headings, built from the real context file and the real ideas file; and `ls ~/.local/state/agent-board/scout` before and after showing that nothing was created.
- [ ] `discover nightly --dry-run --force --project agent-board` still prints its run dir and exits 0 (the shared core refactor on real state).

**Verify:** `python3 -m unittest board.tests.test_scout_isolation -v 2>&1 | tail -3` → `OK`

```json:metadata
{"files": ["board/tests/test_scout_isolation.py", "docs/superpowers/notes/2026-11-21-scout-real-state.md"], "verifyCommand": "python3 -m unittest board.tests.test_scout_isolation -v 2>&1 | tail -3", "acceptanceCriteria": ["isolation leak check with counted paths", "all.zsh ALL PASS rc 0 or 4", "source test on every default source", "real pack <= 30 KB six headings", "real scout dir untouched", "discover dry-run on real state"], "modelTier": "standard"}
```

---

### Task 15: User gate: one real `scout weekly --dry-run`

**Goal:** One real `tmux-ctl scout weekly --dry-run --force` on this repo, with real sources and the real model, its printed digest shown to the user.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none (evidence in the ledger)

**Acceptance Criteria:**
- [ ] `TC_SCOUT_DIR=<tmp> tmux-ctl scout poll` then `TC_SCOUT_DIR=<tmp> tmux-ctl scout weekly --dry-run --force` run on the real repo with the real `claude`. The printed digest text and buttons are captured in full.
- [ ] The user has seen the printed digest (posted to them in Discord or the terminal) and answered.
- [ ] `git -C ~/agent-board for-each-ref refs/heads/scout` is empty afterwards, and `~/.local/state/agent-board/scout` was not created.

**Verify:** `TC_SCOUT_DIR=$(mktemp -d) zsh -c 'tmux-ctl scout poll && tmux-ctl scout weekly --dry-run --force'` → a printed digest starting `🛰 scout agent-board`

```json:metadata
{"files": [], "verifyCommand": "TC_SCOUT_DIR=$(mktemp -d) zsh -c 'tmux-ctl scout poll && tmux-ctl scout weekly --dry-run --force'", "acceptanceCriteria": ["real poll + weekly --dry-run --force output captured", "user saw the digest and answered", "no scout branch, real scout dir not created"], "modelTier": "mechanical", "userGate": true, "tags": ["user-gate"]}
```
