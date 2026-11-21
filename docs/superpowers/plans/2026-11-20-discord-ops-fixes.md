# Discord ops fixes and /queue spec summaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six Discord bridge / ops-bot defects and add `/queue` cards whose dropdown shows a summary of each queued spec.

**Architecture:** Board side (Python, `board/discord_*.py`) builds ops and views; the Node bridge (`tools/discord-bridge/`) executes outbox ops and answers interactions. Each fix stays in the module that owns the behaviour; the `/queue` feature adds `discord_ops.spec_summary`, a `views.json["specs"]` list, a `select` field on the `post` op and an `ab:ops:spec:<project>` handler.

**Tech Stack:** Python 3 unittest, Node `node --test`, zsh tests on a scratch tmux server, jq.

**Spec:** `docs/superpowers/specs/2026-11-19-discord-ops-fixes-design.md`

## Global Constraints

- The spec's line numbers are stale (written 2026-11-19; code has moved). Find code by function name: `_dc_token` (tools/lib/discord.zsh), `createCard`/`doCard`/`opPost`/`opEdit`/`onOpsInteraction` (bridge.js), `payload`/`handle` (lib/commands.js), `presence_op_due` (discord_feed.py, callers in discord_feed.py project ticker and discord_ops.tick), `handle_event`/`consume`/`_resume_all`/`tick` (discord_ops.py), `_ops` and its `handle_event` call (discord_controls.py), `post`/`click`/`request` (discord_ideas.py), `_check` (discord_feed.py).
- Old/new compatibility (spec): a bridge state without `card_pinned` counts as pinned; an ideas post state without `body` falls back to the header-only edit; an old bridge ignores unknown op fields (`reply`, `select`); an old bridge that never writes `presence` gets at most one resend a minute.
- Every new bridge failure path (pin retry, the edit's `reply`, a select reply) logs one line via `say(...)` and never fails the op that carried it. Exception: a malformed `select` field fails the post op (it goes to `failed/` like any invalid op).
- `spec_summary` never raises; any read/parse error gives the not-found summary.
- Discord limits: message text 2000; select ≤ 25 options, option label and value ≤ 100, custom_id ≤ 100; summary ≤ 1900; spec label ≤ 100; Problem excerpt ≤ 600 chars cut at a word boundary with `…`.
- Teammates share one worktree: stage only your own paths (`git add <paths>`), no whole-tree git commands.
- Fresh worktree: `tools/discord-bridge/node_modules` is installed (`npm ci` was run). Run bridge tests with `cd tools/discord-bridge && npm test` (not a bare `node --test test/`).
- Board tests that touch usage/statusline set `TC_STATE` to a temp dir; follow the existing test classes' setUp in each test file.
- Commit messages: conventional with scope (`fix(bridge): …`, `feat(board): …`), ending with the attribution trailer your harness specifies.

**User decisions (already made):**
- D1. The five small fixes take the spec's design; Park also gets a separate `parked ✓` reply.
- D2. `/queue` with no project posts one card per lead in #command-center, each with a dropdown of that lead's specs; picking one shows a private summary (title, Problem cut to ~600 chars, status and outcome, branch).
- D3. Branch comes from `metadata.worktree` and `metadata.branch`, written by the lead on every `Plan & run:` task.
- D4. `/ideas` always posts and edits through the ops bridge; project bots stop offering `/ideas`.
- D5. Frozen-dialog ideas are out of scope.

---

### Task 1: `ackReaction: null` gets 👀, and the pin permission wording

**Goal:** `tmux-ctl discord token` sets `ackReaction` to 👀 when the key is missing or `null`, keeps `""`, and INSTALL.md names "Pin Messages" for the project bot.

**Files:**
- Modify: `tools/lib/discord.zsh` (`_dc_token`, the `_dc_write` filter)
- Modify: `docs/INSTALL.md` (the project bot's permission list, currently "Manage Messages (pin)"; also the sentence in step 3 that says "unless that key already exists")
- Test: `tools/tests/test_ctl_discord.zsh`

**Acceptance Criteria:**
- [ ] `access.json` with `"ackReaction": null` → after `token`, `"👀"`.
- [ ] With `"ackReaction": ""` → stays `""`; key missing → `"👀"`; `"✅"` → stays `"✅"`.
- [ ] Mutation: revert the filter to `has("ackReaction")` → the null case fails.
- [ ] INSTALL.md's project-bot permission list says `Pin Messages` (not `Manage Messages (pin)`); step 3 says a missing or null value gets 👀 and an empty one means off.

**Verify:** `zsh tools/tests/test_ctl_discord.zsh 2>&1 | tail -3` → its ALL PASS / summary line with 0 failures

**Steps:**

- [ ] **Step 1: Write the failing test.** In `tools/tests/test_ctl_discord.zsh`, next to the existing token/ackReaction tests (grep `ackReaction`), add cases that seed `access.json` with `{"ackReaction": null}`, `{"ackReaction": ""}`, `{}` and `{"ackReaction": "✅"}`, pipe a token into `tmux-ctl discord token`, and assert `jq -r .ackReaction` is `👀`, `` (empty), `👀`, `✅`. Copy the existing test's setup and assertion helpers exactly.
- [ ] **Step 2: Run, expect the null case to FAIL.** `zsh tools/tests/test_ctl_discord.zsh 2>&1 | grep -E 'FAIL|ok' | tail -20`
- [ ] **Step 3: Implement.** In `_dc_token` replace the filter with:

```zsh
  _dc_write "$dir" 'if (.ackReaction // null) == null then .ackReaction = "👀" else . end' || return 1
```

(`""` is not null in jq, so `"" // null` is `""` and stays.)
- [ ] **Step 4: INSTALL.md.** Replace `Manage Messages (pin)` with `Pin Messages` in the project-bot permission list; in step 3 change "unless that key already exists (an empty value means you turned it off)" to "when the key is missing or null (an empty value means you turned it off)".
- [ ] **Step 5: Run, expect PASS.** Same command as Verify.
- [ ] **Step 6: Commit** `fix(discord): ackReaction null gets 👀; Pin Messages in INSTALL` — `git add tools/lib/discord.zsh docs/INSTALL.md tools/tests/test_ctl_discord.zsh`.

```json:metadata
{"files": ["tools/lib/discord.zsh", "docs/INSTALL.md", "tools/tests/test_ctl_discord.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_discord.zsh 2>&1 | tail -3", "acceptanceCriteria": ["null -> 👀", "\"\" kept, missing -> 👀, other value kept", "mutation has(ackReaction) fails the null case", "INSTALL says Pin Messages and the null rule"], "modelTier": "mechanical"}
```

### Task 2: Card pin retry in the bridge

**Goal:** A card whose pin failed (e.g. 403) is pinned by a later card op; a pinned or legacy card is never re-pinned.

**Files:**
- Modify: `tools/discord-bridge/bridge.js` (`createCard`, `doCard`)
- Test: `tools/discord-bridge/test/bridge.test.js` (uses `test/fake-client.js`; check whether it has `failNext`; if not, add a `failNext(method, err)` helper there that makes the next call of that method reject, and name it in your report)

**Acceptance Criteria:**
- [ ] `createCard`: send succeeds, `msg.pin()` rejects → card kept (`st.card_message_id` set), `st.card_pinned === false` saved, one log line `pin failed: grant Pin Messages (<reason>)`, the card op succeeds (file removed from the outbox, not in `failed/`). On pin success `st.card_pinned = true`.
- [ ] `doCard` after a successful edit retries `msg.pin()` only when `st.card_pinned === false`; a success sets it `true`. A state with no `card_pinned` key (a bridge that pinned before this change) counts as pinned: no pin call.
- [ ] A failed retry logs the `pin failed` line once per process (not every tick) and the op still succeeds.
- [ ] Tests: (a) pin 403 on create, next card op pins and sets `card_pinned: true`; (b) a pinned card (`card_pinned: true`) gets no pin call on edit; (c) legacy state without `card_pinned` gets no pin call; (d) two failed retries log one line. Mutation: drop the `card_pinned === false` check in `doCard` → (b) and (c) fail.

**Verify:** `cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'` → `# fail 0`

**Steps:**

- [ ] **Step 1:** Write tests (a)-(d) in `bridge.test.js` following the existing card tests (grep `card_message_id`). Run `npm test`, expect them to FAIL.
- [ ] **Step 2:** Implement. Shape:

```js
  let pinWarned = false;
  const pinFailed = (e) => { if (!pinWarned) { pinWarned = true; say(`pin failed: grant Pin Messages (${snip(e?.message)})`); } };

  async function createCard(text) {
    const ch = await home();
    const msg = await ch.send(cardPayload(text));
    st.card_message_id = msg.id; save();
    lastCardAt = now();
    try { await msg.pin(); st.card_pinned = true; } catch (e) { st.card_pinned = false; pinFailed(e); }
    save();
  }
```

and in `doCard`, after `await msg.edit(...)`; `lastCardAt = now();`:

```js
      if (st.card_pinned === false) {
        try { await msg.pin(); st.card_pinned = true; save(); } catch (e) { pinFailed(e); }
      }
```

Check `say` and `snip` are in scope at that point (they are used elsewhere in the same factory); if `createCard`'s first log should fire even after an earlier warning, keep the once-per-process rule anyway (spec).
- [ ] **Step 3:** `npm test` → `# fail 0`.
- [ ] **Step 4: Commit** `fix(bridge): retry a failed card pin on later card ops` — `git add tools/discord-bridge/bridge.js tools/discord-bridge/test/bridge.test.js` (plus `test/fake-client.js` if changed).

```json:metadata
{"files": ["tools/discord-bridge/bridge.js", "tools/discord-bridge/test/bridge.test.js", "tools/discord-bridge/test/fake-client.js"], "verifyCommand": "cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'", "acceptanceCriteria": ["pin failure on create keeps the card, card_pinned false, one log line, op succeeds", "later card op retries the pin while card_pinned === false", "card_pinned true or missing: no pin call", "failed retry logs once per process", "mutation dropping the check fails tests b and c"], "modelTier": "standard"}
```

### Task 3: Presence resend when the bridge lost it

**Goal:** `presence_op_due` also resends when the bridge's own `bridge-state.json` `presence` differs from the text and the last send is at least `PRESENCE_EVERY` (60 s) old.

**Files:**
- Modify: `board/discord_feed.py` (`presence_op_due`, its project-ticker caller)
- Modify: `board/discord_ops.py` (`tick`'s presence call)
- Test: `board/tests/test_discord_feed.py`, `board/tests/test_discord_ops.py`

**Acceptance Criteria:**
- [ ] New signature `presence_op_due(state, text, now, bridge_state=None)`. Returns the op when the text changed (today's rule, throttle included), or when `(bridge_state or {}).get("presence") != text` and `now - state.get("presence_ts", 0) >= PRESENCE_EVERY`. Otherwise `None`.
- [ ] Tests: same text, bridge presence differs, 59 s since last send → `None`; 60 s → op. Same text, bridge presence equal → `None` at any age. `bridge_state=None` / `{}` → treated as absent (op after 60 s). Mutation: drop the `>= PRESENCE_EVERY` check on the second branch → the 59 s test fails.
- [ ] Both callers pass the bridge state they read: `discord_feed._load`-style read of `<dir>/bridge-state.json` (missing/unreadable → `{}`), project dir in the project ticker, `tc_env.ops_dir()` in `discord_ops.tick`. A test per caller: seed `bridge-state.json` with `{"presence": "old"}`, same `presence_text` in the ticker state with an old `presence_ts`, run the tick → one presence op in the outbox.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Write the `presence_op_due` unit tests and the two caller tests; run, expect FAIL.
- [ ] **Step 2:** Implement:

```python
def presence_op_due(state, text, now, bridge_state=None):
    """A presence op when the text changed, or the bridge's own state lost it, and PRESENCE_EVERY seconds passed since state['presence_ts']; else None."""
    if now - state.get("presence_ts", 0) < PRESENCE_EVERY:
        return None
    if text != state.get("presence_text") or (bridge_state or {}).get("presence") != text:
        return {"op": "presence", "text": text}
    return None
```

In each caller read the bridge state once per tick with the module's existing JSON loader (discord_ops has `_load(p)`; in discord_feed reuse whatever helper reads `bridge-state.json` or a `try: json.loads(...) except (OSError, ValueError): {}`) and pass it.
- [ ] **Step 3:** Run the Verify command → OK.
- [ ] **Step 4: Commit** `fix(board): resend presence when the bridge lost it` with the four paths.

```json:metadata
{"files": ["board/discord_feed.py", "board/discord_ops.py", "board/tests/test_discord_feed.py", "board/tests/test_discord_ops.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3", "acceptanceCriteria": ["resend when bridge presence differs and >= 60 s since last send", "no resend before 60 s or when it matches", "missing bridge state counts as absent", "both callers pass the bridge state", "mutation removing the throttle fails the 59 s test"], "modelTier": "standard"}
```

### Task 4: `/pause` and `/resume` share `paused_by_ops`

**Goal:** A project paused by `/pause` (from either bot) or by the controls path is resumed by Resume all.

**Files:**
- Modify: `board/discord_ops.py` (`handle_event`, `consume`)
- Modify: `board/discord_controls.py` (the `_ops("handle_event", …)` call in `consume_events`)
- Test: `board/tests/test_discord_ops.py`, `board/tests/test_discord_controls.py`

**Acceptance Criteria:**
- [ ] `handle_event(project, d, ev, add_line, allow, run=None, spawn=None, st=None)`: in the plain slash branch, when `st` is given, `/pause` sets `st["paused_by_ops"][project] = time.time()` and `/resume` pops it, both before `add_line`.
- [ ] `consume` passes its `st` to `handle_event`.
- [ ] The controls path (`discord_controls.consume_events` forwarding slash events) calls a new `discord_ops.handle_event_locked(project, d, ev, add_line, allow, run, spawn)` that opens `_state(True)` (the same lock `consume` uses), calls `handle_event(..., st=st)` and lets `_state` save. When the ops bot is not configured it behaves as today (no state).
- [ ] Tests: slash `/pause p` through `consume` then a `ab:ops:resume-all` click resumes `p` (RESUME_LINE added for p) even though `st["queues"][p]` reads `queue: running`; the controls path `/pause` sets `paused_by_ops[p]`; `/resume` clears it. Mutation: remove the `st["paused_by_ops"][project] = …` line → the resume-all test fails.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Read `_state` in discord_ops.py (what it yields when not configured) and the existing `consume`/controls tests to copy their fixtures. Write the tests; expect FAIL.
- [ ] **Step 2:** Implement the `st` parameter, the `consume` pass-through, `handle_event_locked`, and switch the controls call to `_ops("handle_event_locked", project, d, ev, add_line, allow, lead_run or run, spawn)`.
- [ ] **Step 3:** Verify → OK. Also run `python3 -m unittest discover -s board/tests -p 'test_discord_controls*.py'`.
- [ ] **Step 4: Commit** `fix(board): /pause and /resume record paused_by_ops`.

```json:metadata
{"files": ["board/discord_ops.py", "board/discord_controls.py", "board/tests/test_discord_ops.py", "board/tests/test_discord_controls.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3", "acceptanceCriteria": ["handle_event st param sets/pops paused_by_ops before add_line", "consume passes st", "controls path loads ops state under the same lock and saves it", "slash pause then Resume all resumes a project whose queue reads running", "mutation fails the resume-all test"], "modelTier": "standard"}
```

### Task 5: `/ideas` keeps the list and sends a reply

**Goal:** Park / Brainstorm next / Drop edit the group message to its full body plus the status line, and the bridge sends a short reply after the edit.

**Files:**
- Modify: `board/discord_ideas.py` (`post`, `click`)
- Modify: `tools/discord-bridge/bridge.js` (`opEdit`)
- Modify: `board/discord_feed.py` (`_check`: allow an optional string `reply` on `edit`, ≤ 2000)
- Test: `board/tests/test_discord_ideas.py`, `tools/discord-bridge/test/bridge.test.js`

**Acceptance Criteria:**
- [ ] `post` stores each group's rendered text as `g["body"]` in the post state.
- [ ] `click` edits to `f"{body}\n{second}"`; when that exceeds 2000 the body is cut (status line kept whole) so the text is ≤ 2000. A group without `body` falls back to `f"{g['header']}\n{second}"`. The pre-action `_check` validates the full text actually sent.
- [ ] The edit op carries `reply`: `parked ✓`, `sent to <project> ✓`, or `dropped <n> ✓` (n = the count dropped). A tap on a group already done writes no op (today's idempotence).
- [ ] `opEdit`: after a successful `msg.edit`, if `typeof op.reply === 'string' && op.reply`, `await msg.reply({ content: op.reply.slice(0, 2000), allowedMentions: { parse: [] } })`; a failure logs one line and the op still succeeds.
- [ ] Tests (py): the edit text contains the first idea's text and the status line; a long body is cut and the status line kept; legacy state without `body` falls back; a repeat tap writes nothing. Tests (js): edit with `reply` sends one reply on the edited message; edit without `reply` sends none; reply failure → op succeeds. Mutation: drop the `reply` branch in `opEdit` → the js reply test fails.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3; cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'` → `OK` and `# fail 0`

**Steps:**

- [ ] **Step 1:** Read `post`, `click`, `_render` in discord_ideas.py and `_check` in discord_feed.py. Write the tests; expect FAIL.
- [ ] **Step 2:** Implement board side (body storage, edit text, cut, `reply` field; `_check` accepts `reply`).
- [ ] **Step 3:** Implement `opEdit`'s reply; check the fake client's message object supports `reply` (add it if not).
- [ ] **Step 4:** Verify.
- [ ] **Step 5: Commit** `fix(ideas): keep the group list on a tap and reply with the action`.

```json:metadata
{"files": ["board/discord_ideas.py", "board/discord_feed.py", "tools/discord-bridge/bridge.js", "board/tests/test_discord_ideas.py", "tools/discord-bridge/test/bridge.test.js", "tools/discord-bridge/test/fake-client.js"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3; cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'", "acceptanceCriteria": ["post stores body", "click edit = body + status line, cut to 2000 keeping the status line", "legacy no-body fallback", "edit op reply text per action; repeat tap writes nothing", "bridge sends reply after a successful edit; failure logged, op ok", "mutation fails the js reply test"], "modelTier": "standard"}
```

### Task 6: `/ideas` always goes through the ops bridge

**Goal:** `/ideas` from any bot posts and edits its groups in #command-center, and project bots stop registering `/ideas`.

**Files:**
- Modify: `board/discord_ops.py` (`handle_event`'s `ideas_slash` branch)
- Modify: `tools/discord-bridge/lib/commands.js` (`payload(ops)`)
- Test: `board/tests/test_discord_ops.py`, `tools/discord-bridge/test/commands.test.js`

**Acceptance Criteria:**
- [ ] `handle_event` calls `discord_ideas.request(ev.get("project"), "_ops", add_line, time.time())` whatever `ev["bridge"]` is. Test: an `/ideas` slash event with `bridge: "agent-board"` writes its post op to the ops outbox (`tc_env.ops_dir()/outbox`), not the project's.
- [ ] `payload(false)` has no `ideas` command; `payload(true)` still has it. Test both.
- [ ] Check `discord_ideas.click`/`post` and the expiry post write to the same bridge the request stored (they read it from the request record); confirm with a test that the group edit after a click goes to the ops outbox.
- [ ] Mutation: restore `ev.get("bridge")` → the py routing test fails.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3; cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'` → `OK` and `# fail 0`

**Steps:**

- [ ] **Step 1:** Tests; expect FAIL.
- [ ] **Step 2:** Implement: in `payload(ops)` filter `ideas` out of the command list when `!ops` (read how the list is built first; `ACTIONS` keeps `ideas` so an old registration still works).
- [ ] **Step 3:** Verify. **Step 4: Commit** `fix(ideas): /ideas always posts through the ops bridge`.

```json:metadata
{"files": ["board/discord_ops.py", "tools/discord-bridge/lib/commands.js", "board/tests/test_discord_ops.py", "tools/discord-bridge/test/commands.test.js"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3; cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'", "acceptanceCriteria": ["ideas request always uses _ops bridge", "group edits after a click go to the ops outbox", "payload(false) has no ideas, payload(true) has it", "mutation fails the routing test"], "modelTier": "standard"}
```

### Task 7: `spec_summary` and `views.json["specs"]`

**Goal:** Each ops tick writes, per project with a lead, a list of its `Plan & run:` tasks with a label and a ≤1900-char summary built from the spec file.

**Files:**
- Modify: `board/discord_ops.py` (new `spec_summary(root, task)`, new `specs_view(root, lead_tasks)`, `tick` writes `"specs"`)
- Test: `board/tests/test_discord_ops.py`

**Acceptance Criteria:**
- [ ] `spec_summary(root, task)`: path = subject after `Plan & run: `, minus a trailing ` (…)` and `#part-n`; resolved under `root`. Line 1 `**<first "# " line text>**`; then the `## Problem` section up to the next `## `, whitespace collapsed, cut at a word boundary to ≤ 600 chars with `…` appended when cut; then `Status: <pending|in progress|completed>` + ` — <metadata.outcome>` when set; then `Branch: <metadata.branch>` + ` · worktree <metadata.worktree>` when set, else `Branch: not started`. Whole summary ≤ 1900.
- [ ] Missing/unreadable spec → `**<spec file name>**` then `(spec file not found)`, status and branch lines kept. Never raises (test with `task={}` and a subject with no path).
- [ ] Cached per `(path, mtime)`: a second call on an unchanged file does not re-read it (test by patching `Path.read_text` / counting reads). Mutation: remove the cache → the read-count test fails.
- [ ] `views.json["specs"][p]` = list in task-id (numeric) order of `{"key": <task id str>, "label": <spec file name, ≤100>, "summary": …}` for the lead's `Plan & run:` tasks; projects without such tasks get `[]`.
- [ ] Test on a real spec file from `docs/superpowers/specs/` (this plan's spec): the summary starts with `**Discord bridge and ops fixes` and contains `Six small defects`.
- [ ] The repo root per project: find how `tick` (or `lead_info`) knows a project's repo root; if no root is available, use the lead's cwd from the existing lead info; document the source in your report. Use `metadata` from the task records as `tasks_by_project` gives them (check they include `metadata`; if not, extend the reader that builds them and say so).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Read `tick` and where `tasks_by_project` and `lead_info` come from (grep their callers in board/). Write the tests; expect FAIL.
- [ ] **Step 2:** Implement `spec_summary`, `specs_view`, and add `"specs"` to the `views.json` dict in `tick`.
- [ ] **Step 3:** Verify. **Step 4: Commit** `feat(board): spec summaries in views.json`.

```json:metadata
{"files": ["board/discord_ops.py", "board/tests/test_discord_ops.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3", "acceptanceCriteria": ["summary title, Problem excerpt <=600 with ellipsis, status+outcome, branch/worktree or not started", "missing spec gives not-found summary, never raises", "cache per (path, mtime), mutation fails read-count test", "views.json specs list in id order with key/label/summary", "real spec file test"], "modelTier": "standard"}
```

### Task 8: `/queue` cards with a spec dropdown

**Goal:** `/queue` with no project in ops mode posts one card per lead in #command-center with a select of its specs; picking one answers privately with the summary.

**Files:**
- Modify: `tools/discord-bridge/lib/commands.js` (`/queue` option optional in ops mode; no project → private `posting <n> queue cards` and a `slash` event `{command: "queue", project: null}`)
- Modify: `tools/discord-bridge/bridge.js` (`opPost` `select`; `onOpsInteraction` `ab:ops:spec:<project>`)
- Modify: `board/discord_ops.py` (`handle_event`: `/queue` with no project → one `post` op per project with a lead to the ops outbox)
- Modify: `board/discord_feed.py` (`_check`: validate `select`)
- Test: `tools/discord-bridge/test/bridge.test.js`, `tools/discord-bridge/test/ops.test.js` or `commands.test.js`, `board/tests/test_discord_ops.py`, `board/tests/test_discord_feed.py`

**Acceptance Criteria:**
- [ ] Bridge `/queue`: with a project → today's reply unchanged; without, in ops mode → private reply `posting <n> queue cards` (n = number of projects in `views.json["queue"]`) and a slash event `{type: "slash", command: "queue", project: null, …}`. Project mode keeps `project` required. (`NEEDS_PROJECT` today includes `queue`; adjust for ops mode only.)
- [ ] Board: that event → for each project in `views.json["queue"]` (the ops views file, read with `_load`) one `post` op to the ops outbox: text = the `queue_text` block, `select = {"custom_id": f"ab:ops:spec:{p}", "options": [{"label", "value"}…first 25 of specs[p]], "placeholder": "Pick a spec"}`; when specs > 25 the text ends with `… <k> more`; no specs → no `select`. Audit result `posted <n>`.
- [ ] `opPost`: `select` renders as its own action row `{type:1, components:[{type:3, custom_id, placeholder, options:[{label, value}]}]}` under the buttons row. Malformed `select` (not an object, > 25 options, label/value/custom_id over 100, missing custom_id) throws → op goes to `failed/`.
- [ ] `_check` validates the same `select` limits board-side (ValueError).
- [ ] `onOpsInteraction` handles `ab:ops:spec:<project>` like `ab:ops:diff:`: `i.values[0]` → entry in `views.json["specs"][project]` → private answer with its `summary`, or `that spec is no longer in the queue`. Same `allowFrom` check as other `ab:` ids.
- [ ] Tests: post with `select` renders a type-3 row; malformed select fails the op; `ab:ops:spec:p` answers with the summary and the not-in-queue text for an unknown key; `/queue` with no project in ops mode writes the slash event; board posts one card per lead with select and the `… k more` line at 26+ specs; `_check` rejects 26 options. Mutation: skip the select validation in `opPost` → the malformed test fails.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3; cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'` → `OK` and `# fail 0`

**Steps:**

- [ ] **Step 1:** Read the existing `/tasks` select (`ab:tasks:pick` in commands.js) and `ab:ops:diff:` in bridge.js `onOpsInteraction`; the differences from the `/tasks` select: this select is posted by the board via an outbox `post` op (not an interaction reply), and its handler lives in bridge.js `onOpsInteraction` (not `handleComponent`). Write the tests; expect FAIL.
- [ ] **Step 2:** Implement bridge, commands, board, `_check`.
- [ ] **Step 3:** Verify. **Step 4: Commit** `feat(discord): /queue cards with a spec summary dropdown`.

```json:metadata
{"files": ["tools/discord-bridge/lib/commands.js", "tools/discord-bridge/bridge.js", "board/discord_ops.py", "board/discord_feed.py", "tools/discord-bridge/test/bridge.test.js", "tools/discord-bridge/test/ops.test.js", "tools/discord-bridge/test/commands.test.js", "board/tests/test_discord_ops.py", "board/tests/test_discord_feed.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_*.py' 2>&1 | tail -3; cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'", "acceptanceCriteria": ["/queue no project in ops mode: private posting n and slash event", "board posts one card per lead with select, cut line past 25, no select when none", "opPost renders type-3 row; malformed select fails op", "_check validates select limits", "ab:ops:spec answers summary or not-in-queue", "mutation fails malformed test"], "modelTier": "standard"}
```

### Task 9: Lead rule for `metadata.worktree` and `metadata.branch`

**Goal:** The orchestrator rules and the handoff skill tell the lead to record the worktree and branch of every `Plan & run:` task.

**Files:**
- Modify: `claude/orchestrator.md` (Queue mode step 2: "then branch off `main` … in a worktree under `.claude/worktrees/`;")
- Modify: `claude/plugin/skills/handoff/SKILL.md` (where State of the work / Queue state lists `metadata.queue`)
- Test: `tools/tests/test_plugin.zsh` and any test that greps orchestrator.md (run `grep -rln 'orchestrator.md' tools/tests board/tests` and run those)

**Acceptance Criteria:**
- [ ] orchestrator.md step 2, right after the worktree clause, says: write `metadata.worktree = ".claude/worktrees/<name>"` and `metadata.branch = "<branch>"` with TaskUpdate, alongside `metadata.plan`.
- [ ] The handoff skill's list of per-task queue fields includes `metadata.worktree` and `metadata.branch` next to `metadata.queue`.
- [ ] `grep -c 'metadata.worktree' claude/orchestrator.md claude/plugin/skills/handoff/SKILL.md` → ≥1 each.
- [ ] Tests that read these files pass.

**Verify:** `grep -c 'metadata.worktree' claude/orchestrator.md claude/plugin/skills/handoff/SKILL.md` → both ≥ 1

**Steps:**

- [ ] **Step 1:** Edit orchestrator.md step 2: after "in a worktree under `.claude/worktrees/`;" insert " write `metadata.worktree = \".claude/worktrees/<name>\"` and `metadata.branch = \"<branch>\"` on the task with TaskUpdate;". Keep the rest of the sentence unchanged.
- [ ] **Step 2:** In SKILL.md find `metadata.queue` and add `metadata.worktree` and `metadata.branch` to the same list.
- [ ] **Step 3:** Run Verify and the tests found by the grep.
- [ ] **Step 4: Commit** `docs(orchestrator): record metadata.worktree and metadata.branch per Plan & run task`.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/plugin/skills/handoff/SKILL.md"], "verifyCommand": "grep -c 'metadata.worktree' claude/orchestrator.md claude/plugin/skills/handoff/SKILL.md", "acceptanceCriteria": ["orchestrator step 2 names both fields", "handoff skill lists both fields", "tests reading these files pass"], "modelTier": "mechanical"}
```

### Task 10: Full suite and read-only real-state checks

**Goal:** Every suite passes on the branch, and the new board code runs against the user's real task list, specs and ops state without writing anything.

**Files:**
- Read only: `~/.claude/tasks/session-68f302b9/*.json` (the running lead's task list), `docs/superpowers/specs/`, `~/.local/state/agent-board/discord/_ops/bridge-state.json`, `~/.local/state/agent-board/discord/_ops/views.json`

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh` verdict line ALL PASS (rc 0, or rc 4 = pass over budget, accepted on this machine).
- [ ] A read-only script imports `board/discord_ops.py` from the worktree and prints `specs_view` for the real task list: one entry per `Plan & run:` task in that list (16 today: count printed next to `grep -l '"Plan & run:' … | wc -l`), each summary ≤ 1900, #18's summary shows `Branch: feat/discord-ops-fixes · worktree .claude/worktrees/discord-ops-fixes`, and the `#part-2` / `(§4-5 only)` subjects resolve to their spec files (no `(spec file not found)` for any spec that exists: count printed).
- [ ] `presence_op_due` with the real `_ops/bridge-state.json` and a synthetic state returns the expected op/None (printed).
- [ ] No file under `~/.local/state/agent-board/` or `~/.claude/tasks/` changed (compare `stat -f %m` before/after, printed with the file count checked).

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → verdict ALL PASS and rc=0 or rc=4

```json:metadata
{"files": [], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["all.zsh ALL PASS rc 0 or 4", "real task list: every Plan & run summary built, <=1900, #18 shows branch and worktree, suffixed subjects resolve", "presence_op_due on real bridge state", "no state file changed, count checked printed"], "modelTier": "standard"}
```

### Task 11: User gate: `/queue`, `/ideas` and Park on the phone

**Goal:** After the merge and a bridge restart, the user confirms on the phone that `/queue` shows a card per lead with a spec dropdown and summaries, `/ideas` from the agent-board bot lands in #command-center, and Park keeps the list and replies `parked ✓`.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Read only: `~/.local/state/agent-board/discord/_ops/audit.jsonl`, `bridge.log`

**Acceptance Criteria:**
- [ ] `/queue` (no project) in #command-center: one card per lead, each with a dropdown; picking a spec shows its summary privately (user confirms; audit line `slash … posted <n>`).
- [ ] `/ideas` from the agent-board bot: the groups post in #command-center (audit line, outbox of `_ops`).
- [ ] Park on a group: message keeps the list plus `→ parked`, and a `parked ✓` reply appears.
- [ ] Waits for the morning (not run inside the queue).

**Verify:** `grep -E '"(slash|click)"' ~/.local/state/agent-board/discord/_ops/audit.jsonl | tail -5` → lines for queue, ideas and the park click after the merge time

```json:metadata
{"files": [], "verifyCommand": "grep -E '\"(slash|click)\"' ~/.local/state/agent-board/discord/_ops/audit.jsonl | tail -5", "acceptanceCriteria": ["/queue card per lead with dropdown and summary on the phone", "/ideas from the agent-board bot lands in #command-center", "Park keeps the list and replies parked ✓", "waits for the morning"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```
