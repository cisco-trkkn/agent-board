# Board artifacts panel sections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The board's artifacts panel shows the pinned plan, then Plans (older ones, newest first), Specs, Docs & pages (Claude Docs and published Artifacts, opening in the web) and Other, and the artifact hook records Claude Docs that a session creates or edits.

**Architecture:** `artifacts.summary()` gains an ordered `sections` list and per-item `title` and `first_ts`; the panel renders those sections instead of `Session N` groups. The PostToolUse hook `artifact-register.sh` also matches the Claude Docs create/edit tools and records `{url, title, kind: "doc"}`, parsed from payloads captured from a real session.

**Tech Stack:** Python 3.9 (`board/artifacts.py`, unittest), vanilla JS in `board/index.html`, zsh + embedded Python hook (`claude/plugin/scripts/artifact-register.sh`), zsh test harness `tools/tests/lib.zsh` (scratch tmux server).

**Spec:** `docs/superpowers/specs/2026-10-21-board-artifacts-sections-design.md`

## Global Constraints

- Work in a worktree `.claude/worktrees/artifacts-sections` on branch `feat/board-artifacts-sections` from `main`. Never edit `~/agent-board` itself: it is the live install.
- Section names and order are fixed: `plans`, `specs`, `docs`, `other`. Kind → section: `plan` → `plans`, `spec` → `specs`, `doc` and `published` → `docs`, everything else (`handoff`, `report`, `other`, unknown) → `other`.
- Ordering: `plans` by first-registered time (`history[0].ts`), newest first; every other section by last write (`latest.ts`), newest first. `active_plan` never appears in a section.
- `summary()` keeps every existing key (`epoch`, `lineage`, `items`, `active_plan`, `started_from`); `sections`, `title`, `first_ts` are additions.
- Section open state: `localStorage` key `dash.art.<project>.sec.<name>`, stored only when it differs from the default (open for all but `other`, which defaults closed). Every `localStorage` access is in try/catch.
- Unchanged behaviour: move-to-project menu, "N comments waiting for the lead", "Plan done · N ideas ready", unread-change dots, files opening in the doc pane, URL items opening in a new tab with `noopener`.
- The hook never fails a tool call: it stays `async`, exits 0, and records nothing on input it cannot parse.
- Test fixtures for the Claude Docs payloads come from a real session (Task 1), never hand-written. Scrub user email addresses and account/org ids from them; keep the shape.
- Commands: `python3 -m unittest discover -s board/tests`; `zsh tools/tests/run-all.zsh`; single hook test `zsh tools/tests/test_artifact_hook.zsh`. Run suites with `tmux-ctl run -C <worktree> tests "<cmd>"`.
- UI checks run an ephemeral board from the worktree: `TMUX_DASH_PORT=7710 python3 board/server.py` (never the live :7700 board). Kill it by its PID.
- Commits: conventional with scope (`feat(board): …`, `test(hooks): …`), ending with the attribution trailer your harness specifies.

**User decisions (already made):**
- Sections by type, not session groups; each item carries a small session tag `S<n>` (2026-10-20).
- Pin rule unchanged: the lead's newest plan, carried over across sessions (2026-10-20).
- Docs & pages lists Claude Docs a session created or edited, not ones it only read (2026-10-20).
- Capture approach: extend the existing PostToolUse hook (2026-10-20).
- Spec approved (2026-10-21).

---

### Task 1: Capture real Claude Docs hook payloads

**Goal:** Two real PostToolUse hook payloads, one for a Claude Docs create and one for an edit, saved as scrubbed fixtures, plus a short note naming where the doc URL and title sit in each.

**Files:**
- Create: `tools/tests/fixtures/docs-hook/create.json`, `tools/tests/fixtures/docs-hook/update.json`, `tools/tests/fixtures/docs-hook/read.json`
- Create: `tools/tests/fixtures/docs-hook/README.md`

**Acceptance Criteria:**
- [ ] Payloads were written by a real Claude Code PostToolUse hook, not typed: run a headless session `claude -p` with `--settings <scratch settings.json>` whose only hook is `{"matcher": "mcp__claude_ai_Claude_Docs__.*", "hooks": [{"type": "command", "command": "cat >> <scratch>/payloads.jsonl"}]}`, prompting it to create a doc titled `agent-board hook fixture (delete me)` with one line of text, then edit that doc once, then read it. The README records the exact command, the Claude Code version (`claude --version`) and the date.
- [ ] `create.json` is the payload of the create call (`tool_name` ending `__batch` or `__create`), `update.json` of the edit (`__update` or `__batch`), `read.json` of the read. Each is one JSON object, pretty-printed.
- [ ] Scrubbed: no email address and no `session_id`/`transcript_path`/`cwd` that names the user's home (replace with `S1`, `/tmp/t`, `/tmp/t`); the doc URL is kept as is. `grep -rE '[[:alnum:]._%+-]+@[[:alnum:].-]+\.[a-z]{2,}' tools/tests/fixtures/docs-hook/` prints nothing.
- [ ] README states, for create and update: the JSON path to the doc's `claude.ai` URL inside `tool_response` (or "none"), and where the title is (`tool_input…` path or `tool_response…` path, or "none").
- [ ] The scratch doc is deleted afterwards with the Claude Docs delete tool, and the README says so. No change to any real settings file (`git status` and `~/.claude/settings.json` mtime unchanged).

**Verify:** `python3 -c "import json,sys;[json.load(open('tools/tests/fixtures/docs-hook/'+f+'.json')) for f in ('create','update','read')];print('ok')"` → `ok`

**Steps:**

- [ ] **Step 1:** Make the scratch dir and settings file outside the repo (scratchpad). Run `claude --version`.
- [ ] **Step 2:** Run `claude -p --settings <scratch>/settings.json --allowedTools 'mcp__claude_ai_Claude_Docs__*' "<prompt>"` with the prompt from the first criterion. If the headless session lacks the Claude Docs connector, or the hook file stays empty, message the lead before trying anything else.
- [ ] **Step 3:** Split `payloads.jsonl` into the three files with `jq`, scrub as above, write the README.
- [ ] **Step 4:** Delete the scratch doc; record it.
- [ ] **Step 5: Commit.** `git add tools/tests/fixtures/docs-hook && git commit -m "test(hooks): real Claude Docs PostToolUse payload fixtures"` with the attribution trailer your harness specifies.

```json:metadata
{"files": ["tools/tests/fixtures/docs-hook/create.json", "tools/tests/fixtures/docs-hook/update.json", "tools/tests/fixtures/docs-hook/read.json", "tools/tests/fixtures/docs-hook/README.md"], "verifyCommand": "python3 -c \"import json,sys;[json.load(open('tools/tests/fixtures/docs-hook/'+f+'.json')) for f in ('create','update','read')];print('ok')\"", "acceptanceCriteria": ["payloads written by a real PostToolUse hook via claude -p --settings scratch; command, version, date in README", "create/update/read fixtures, one JSON object each", "scrubbed: no email, no home paths, url kept", "README names url and title paths for create and update", "scratch doc deleted; no real settings changed"], "modelTier": "standard"}
```

---

### Task 2: Hook records Claude Docs as `doc` items

**Goal:** `artifact-register.sh` records a Claude Docs create or edit as `{path: <url>, url, title, kind: "doc"}`, ignores reads and responses without a doc URL, and the plugin's PostToolUse matcher includes the Docs create/edit tools.

**Files:**
- Modify: `claude/plugin/scripts/artifact-register.sh` (the embedded Python: tool dispatch near `if tool == "Artifact":`, and the final `print(json.dumps(...))`)
- Modify: `claude/plugin/hooks/hooks.json` (the `Write|Edit|MultiEdit|Artifact` matcher)
- Test: `tools/tests/test_artifact_hook.zsh`

**Acceptance Criteria:**
- [ ] RED first: the new checks fail on the current hook; the failing output is in the report.
- [ ] Fed `fixtures/docs-hook/create.json`, the hook appends one line with `kind` `doc`, `url` = the doc's `claude.ai` URL, `path` = the same URL, and `title` = the doc title from the fixture (`agent-board hook fixture (delete me)`).
- [ ] Fed `update.json`, it appends a second line for the same URL (`kind` `doc`); the title comes from the payload if present, else the field is `""`.
- [ ] Fed `read.json`, or a Docs payload with no `claude.ai` URL, it appends nothing and exits 0.
- [ ] Only tools named `mcp__claude_ai_Claude_Docs__batch`, `…__create`, `…__update` are handled; other `mcp__…` names append nothing.
- [ ] Every recorded line now carries a `title` key (`""` for files and Artifacts); existing checks in `test_artifact_hook.zsh` still pass.
- [ ] `hooks.json` matcher is `Write|Edit|MultiEdit|Artifact|mcp__claude_ai_Claude_Docs__batch|mcp__claude_ai_Claude_Docs__create|mcp__claude_ai_Claude_Docs__update`; `zsh tools/tests/test_plugin.zsh` passes.
- [ ] `zsh tools/tests/run-all.zsh` → ALL PASS.

**Verify:** `zsh tools/tests/test_artifact_hook.zsh | tail -1` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing checks.** Append to `tools/tests/test_artifact_hook.zsh` before `tt_done` (adjust nothing in the fixture; the expected URL is read from it with the path the Task 1 README names, written here as `<URL_JQ>` — replace it with that jq path):

```zsh
FX="$TT_REPO/tools/tests/fixtures/docs-hook"
want_url="$(jq -r '<URL_JQ>' "$FX/create.json")"
n0=$(wc -l < "$m")
hook "$(<"$FX/create.json")"
check "doc create recorded"  test "$(jq -r .kind "$m" | tail -1)" = doc -a "$(wc -l < "$m")" -eq $(( n0 + 1 ))
check "doc url and path"     test "$(jq -r .url "$m" | tail -1)" = "$want_url" -a "$(jq -r .path "$m" | tail -1)" = "$want_url"
check "doc title"            test "$(jq -r .title "$m" | tail -1)" = "agent-board hook fixture (delete me)"
hook "$(<"$FX/update.json")"
check "doc edit recorded"    test "$(jq -r .url "$m" | tail -1)" = "$want_url" -a "$(wc -l < "$m")" -eq $(( n0 + 2 ))
n1=$(wc -l < "$m")
hook "$(<"$FX/read.json")"
check "doc read ignored"     test "$(wc -l < "$m")" -eq "$n1"
hook '{"tool_name":"mcp__claude_ai_Claude_Docs__batch","tool_input":{},"tool_response":"no link here"}'
check "doc without url"      test "$(wc -l < "$m")" -eq "$n1"
hook '{"tool_name":"mcp__other__create","tool_input":{},"tool_response":"https://claude.ai/x/y"}'
check "other mcp ignored"    test "$(wc -l < "$m")" -eq "$n1"
check "file lines have title" test "$(jq -r 'select(.kind=="plan") | has("title")' "$m" | tail -1)" = true
```

The last check needs one more plan write after the change; put `hook "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$plan\"}}"` right before it.

- [ ] **Step 2: Run to see RED.** `tmux-ctl run -C <worktree> tests "zsh tools/tests/test_artifact_hook.zsh"` → the new checks FAIL.

- [ ] **Step 3: Implement.** In the embedded Python, after the `Artifact` branch add a Docs branch, and add `title` to the output. The URL lookup reuses the Artifact regex over the whole `tool_response`; the title lookup follows the paths the Task 1 README names (for a `batch` create the spec's example shape is `tool_input.container.create.name`):

```python
    elif tool.startswith("mcp__claude_ai_Claude_Docs__") and tool.rsplit("__", 1)[1] in ("batch", "create", "update"):
        m = re.search(r"https://claude\.ai/[\w/.-]+", json.dumps(d.get("tool_response") or ""))
        if not m:
            sys.exit(0)
        url, kind = m.group(0), "doc"
        path = url
        title = doc_title(ti, d.get("tool_response"))
```

with `title = ""` initialised next to `url = sid = ""`, a `doc_title(ti, resp)` helper defined above the dispatch that returns the first non-empty string at the README's paths (else `""`), and `"title": title` added to the final `json.dumps({...})`.

In `hooks.json`, set the matcher to the value in the acceptance criteria.

- [ ] **Step 4: GREEN.** `test_artifact_hook.zsh` and `test_plugin.zsh` → ALL PASS, then `run-all.zsh` → ALL PASS.

- [ ] **Step 5: Commit.** `git add claude/plugin/scripts/artifact-register.sh claude/plugin/hooks/hooks.json tools/tests/test_artifact_hook.zsh && git commit -m "feat(hooks): record Claude Docs a session creates or edits"` with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/plugin/scripts/artifact-register.sh", "claude/plugin/hooks/hooks.json", "tools/tests/test_artifact_hook.zsh"], "verifyCommand": "zsh tools/tests/test_artifact_hook.zsh | tail -1", "acceptanceCriteria": ["RED recorded", "create fixture -> kind doc, url=path=doc url, title from fixture", "update fixture -> second line same url", "read fixture and url-less payload append nothing", "only Docs batch/create/update handled", "every line carries title; old checks pass", "hooks.json matcher extended; test_plugin passes", "run-all ALL PASS"], "modelTier": "standard"}
```

---

### Task 3: `summary()` returns sections, titles and first-registered time

**Goal:** `artifacts.summary()` adds `sections` (ordered, per the Global Constraints) and per-item `title` and `first_ts`, without changing existing keys.

**Files:**
- Modify: `board/artifacts.py` (`summary()`)
- Test: `board/tests/test_artifacts.py` (`SummaryTest`)

**Acceptance Criteria:**
- [ ] RED first: the new tests fail on the current code.
- [ ] For the `Base` fixture, `summary("p")["sections"]` == `[{"name": "specs", "items": [<spec path>]}, {"name": "docs", "items": ["https://claude.ai/code/artifact/a"]}]` (the active plan is in no section; empty sections are omitted).
- [ ] Older plans are ordered by first-registered time, newest first, even when an older-registered plan was written last.
- [ ] `doc` and `published` share `docs`; `handoff`/`report`/`other`/unknown go to `other`.
- [ ] Each item has `title` (the last non-empty `title` among its entries, else `""`) and `first_ts` (`history[0].ts`, `0` if missing).
- [ ] `python3 -m unittest discover -s board/tests` → OK.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_artifacts.py' 2>&1 | tail -1` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Add to `SummaryTest` in `board/tests/test_artifacts.py`:

```python
    def test_sections_split_and_skip_active_plan(self):
        s = artifacts.summary("p")
        self.assertEqual(s["sections"], [
            {"name": "specs", "items": [str(self.spec)]},
            {"name": "docs", "items": ["https://claude.ai/code/artifact/a"]},
        ])

    def test_older_plans_newest_registered_first(self):
        (self.state / "artifacts-s.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
            {"ts": 1, "path": "/a.md", "kind": "plan", "agent": "claude", "epoch": 0},
            {"ts": 2, "path": "/b.md", "kind": "plan", "agent": "claude", "epoch": 0},
            {"ts": 3, "path": "/c.md", "kind": "plan", "agent": "claude", "epoch": 0},
            {"ts": 4, "path": "/a.md", "kind": "plan", "agent": "claude", "epoch": 0},   # /a.md written last, registered first
            {"ts": 5, "path": "/h.md", "kind": "handoff", "agent": "claude", "epoch": 0},
            {"ts": 6, "path": "https://claude.ai/doc/d1", "url": "https://claude.ai/doc/d1", "title": "Report", "kind": "doc", "agent": "claude", "epoch": 0},
        ]))
        s = artifacts.summary("s")
        self.assertEqual(s["active_plan"], "/a.md")
        self.assertEqual(s["sections"], [
            {"name": "plans", "items": ["/c.md", "/b.md"]},
            {"name": "docs", "items": ["https://claude.ai/doc/d1"]},
            {"name": "other", "items": ["/h.md"]},
        ])

    def test_title_and_first_ts(self):
        (self.state / "artifacts-t.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
            {"ts": 1, "path": "https://claude.ai/doc/d1", "url": "https://claude.ai/doc/d1", "title": "First", "kind": "doc", "epoch": 0},
            {"ts": 2, "path": "https://claude.ai/doc/d1", "url": "https://claude.ai/doc/d1", "title": "", "kind": "doc", "epoch": 0},
            {"ts": 3, "path": "/x.md", "kind": "spec", "epoch": 0},
        ]))
        by = {i["url"] or i["path"]: i for i in artifacts.summary("t")["items"]}
        self.assertEqual(by["https://claude.ai/doc/d1"]["title"], "First")
        self.assertEqual(by["https://claude.ai/doc/d1"]["first_ts"], 1)
        self.assertEqual(by["/x.md"]["title"], "")
```

- [ ] **Step 2: Run to see RED.** `python3 -m unittest board.tests.test_artifacts -k sections -k older -k title` from the repo root (or `discover -p test_artifacts.py`) → 3 failures (`KeyError: 'sections'` / `'title'`).

- [ ] **Step 3: Implement.** In `board/artifacts.py`, add above `summary()`:

```python
SECTION_OF = {"plan": "plans", "spec": "specs", "doc": "docs", "published": "docs"}
SECTIONS = ("plans", "specs", "docs", "other")


def _sections(items, active):
    """Items (newest write first) split by type; plans re-sorted newest registered first; the pinned plan left out."""
    out = {n: [] for n in SECTIONS}
    for it in items:
        if it["path"] == active and not it["url"]:
            continue
        out[SECTION_OF.get(it["kind"], "other")].append(it)
    out["plans"].sort(key=lambda i: i["first_ts"], reverse=True)
    return [{"name": n, "items": [i["url"] or i["path"] for i in out[n]]} for n in SECTIONS if out[n]]
```

In `summary()`, in the entry loop, after `it["history"].append(...)` add `if e.get("title"): it["title"] = e["title"]`, and create items with `"title": ""` in the `setdefault` dict. In the `for it in by.values():` loop add `it["first_ts"] = it["history"][0]["ts"] or 0`. Compute `active = plans[0]["path"] if plans else None` once and return it as `active_plan`, plus `"sections": _sections(items, active)`.

- [ ] **Step 4: GREEN.** `python3 -m unittest discover -s board/tests` → OK (262+3 tests).

- [ ] **Step 5: Commit.** `git add board/artifacts.py board/tests/test_artifacts.py && git commit -m "feat(board): artifacts summary groups items into sections"` with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/artifacts.py", "board/tests/test_artifacts.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_artifacts.py' 2>&1 | tail -1", "acceptanceCriteria": ["RED recorded", "Base fixture sections == specs then docs, active plan excluded, empty omitted", "older plans newest registered first", "doc+published in docs; handoff/report/other in other", "title last non-empty else empty; first_ts history[0].ts", "board suite OK"], "modelTier": "mechanical"}
```

---

### Task 4: Panel renders sections, titles and session tags

**Goal:** `board/index.html` renders the pinned plan, then one collapsible group per `sections` entry with its title and count, items labelled by `title` (falling back to today's label) with an `S<n>` session tag, open state remembered per section; checked in a browser against both a scratch state and the real, aged artifact manifest.

**Files:**
- Modify: `board/index.html` (`artFor`, `pollArtifacts`, `artButton`, `renderArtifacts`, `KIND_ICON`, CSS near `.art-group`)

**Acceptance Criteria:**
- [ ] `renderArtifacts()` no longer builds `Session N` groups; it renders `A.sections` in order with headings `Plans`, `Specs`, `Docs & pages`, `Other`, each `· <count>`; `Other` starts collapsed, the rest open; toggling stores `dash.art.<project>.sec.<name>` only when it differs from the default.
- [ ] Item label is `it.title` when non-empty, else today's label (URL last segment or file name); each item shows the agent badge and a tag `S<epoch+1>`; `doc` items get their own `KIND_ICON` entry.
- [ ] A `doc` or `published` item opens its URL in a new tab with `noopener`; file items open in the doc pane; the move menu, comments line, "Plan done" line and unread dots behave as before.
- [ ] `python3 -m unittest discover -s board/tests` → OK.
- [ ] Browser check on an ephemeral board from the worktree (`TMUX_DASH_PORT=7710`), scratch `TC_STATE` seeded with a lead plan, two older plans, a spec, a doc with a title and a handoff across two epochs: sections render in the order above, the doc shows its title and opens its URL, collapsing `Specs` survives a reload. Screenshot or `read_page` output in the report.
- [ ] Real-state check (read-only): the same ephemeral board pointed at the real state dir (`TC_STATE` unset or set to the live one) renders this project's real manifest, which spans several sessions and days, with no console errors (`read_console_messages` output in the report); the live manifest file's checksum is unchanged before and after (`shasum` output in the report).

**Verify:** `python3 -m unittest discover -s board/tests 2>&1 | tail -1` → `OK`

**Steps:**

- [ ] **Step 1: Data in the client.** `artFor` gets `sections: []`; `pollArtifacts` adds `sections: d.sections || []` to its `Object.assign`.

- [ ] **Step 2: Labels and tags.** In `artButton`, replace the label/badge append with:

```js
  const label = it.title || (it.url ? it.url.split("/").pop() : it.path.split("/").pop());
  b.append(el("span", "", KIND_ICON[it.kind] || "•"), el("span", "nm", label), el("span", "badge", it.latest.agent || "?"), el("span", "badge sess", `S${(it.latest.epoch ?? 0) + 1}`));
```

Add `doc: "✎"` to `KIND_ICON`.

- [ ] **Step 3: Sections.** In `renderArtifacts`, replace everything from `const groups = new Map();` through the closing `}` of the epoch `for` loop with:

```js
  const SECTION_TITLE = { plans: "Plans", specs: "Specs", docs: "Docs & pages", other: "Other" };
  const box = $("#art-groups"); box.replaceChildren();
  const openKey = (n) => `dash.art.${s.name}.sec.${n}`;
  for (const sec of A.sections) {
    const its = sec.items.map((k) => A.items.get(k)).filter(Boolean);
    if (!its.length) continue;
    const g = el("details", "art-group"), dflt = sec.name !== "other";
    let saved = null; try { saved = localStorage.getItem(openKey(sec.name)); } catch (err) {}
    g.open = saved ? saved === "open" : dflt;
    const sum = el("summary"); sum.append(el("h4", "", `${SECTION_TITLE[sec.name] || sec.name} · ${its.length}`));
    g.append(sum);
    g.addEventListener("toggle", () => { try { if (g.open === dflt) localStorage.removeItem(openKey(sec.name)); else localStorage.setItem(openKey(sec.name), g.open ? "open" : "closed"); } catch (err) {} });   // keep only choices that differ from the default
    for (const it of its) g.append(artButton(A, it));
    box.append(g);
  }
```

Keep the `if (!A.items.size)` empty-state line after it. Add CSS `.art .badge.sess { opacity: .7; }` next to the existing `.art-group` rules.

- [ ] **Step 4: Tests.** `python3 -m unittest discover -s board/tests` → OK.

- [ ] **Step 5: Browser checks.** Use the `claude-in-chrome` skill. Start the ephemeral board with a scratch `TC_STATE` (seed `artifacts-<project>.jsonl` and `lineage-<project>.jsonl` as in the criteria), check, kill by PID; then restart it against the real state dir read-only, record `shasum` of the live `artifacts-agent-board.jsonl` before and after, check the panel and console, kill by PID. Put the evidence in the report.

- [ ] **Step 6: Commit.** `git add board/index.html && git commit -m "feat(board): artifacts panel sections by type with titles and session tags"` with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/index.html"], "verifyCommand": "python3 -m unittest discover -s board/tests 2>&1 | tail -1", "acceptanceCriteria": ["sections rendered in order with titles and counts; Other collapsed; toggle stored only when non-default", "title label with fallback; agent badge and S<n> tag; doc icon", "url items open new tab noopener; existing behaviours unchanged", "board suite OK", "browser check on ephemeral 7710 scratch state: order, doc title+url, toggle survives reload", "real-state read-only check: real manifest renders, no console errors, manifest checksum unchanged"], "modelTier": "standard"}
```
