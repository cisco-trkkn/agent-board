# Discord ticker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every project bot and the ops bot show one live status line (plan use, pace, 5 h use, lead context, spend, running spec) as their Discord custom status, and the status cards count the running spec's own tasks.

**Architecture:** A pure module `board/ticker.py` builds the project and ops lines. `discord_feed.tick` and `discord_ops.tick` write a throttled `presence` outbox op (≤1 per 60 s, only on change). The node bridge applies it with `client.user.setPresence` (custom activity) and re-applies it after a reconnect. A shared `discord_feed.spec_progress` gives the running spec's done/total, used by the cards and the ticker.

**Tech Stack:** Python 3 stdlib (`unittest`), Node 20 `node --test`, discord.js 14.28.1.

**Spec:** `docs/superpowers/specs/2026-11-17-discord-ticker-design.md`

## Global Constraints

- Line formats, exactly (spec § The line):
  - project: `[⚠ ]wk <w>% ▲<pace>× · 5h <f>% · ctx <c>% · $<spend> · <spec> <k>/<n>`
  - ops: `[⚠ ]wk <w>% ▲<pace>× · 5h <f>% · ctx max <c>% <project> · $<spend all> · <r> running`
- `w`, `f`: `round(used_percentage)` from `usage.plan_limits(...)["seven_day"|"five_hour"]`. `?` when there are no limits, the field is missing, or the limits are stale (`now - received_at > 600`). Stale/unknown fields never trigger ⚠.
- `pace`: `(w/100) / elapsed`, `elapsed = 1 - (seven_day.resets_at - now) / 604800`, one decimal (`f"{x:.1f}"`). `—` when `resets_at` is missing or `elapsed < 12/168`. `?` when `w` is `?`.
- `c`: the lead's `context_pct` (see Decided R2). `—` when none. Ops: highest `c` across projects, `ctx max <c>% <project>`, or `ctx max —`.
- `spend`: `f"{x:.2f}"` of `record["spend_today"]`; `$—` when not a number. Ops: sum of the numeric ones; `$—` when none is numeric.
- spec: `<_spec_name> <k>/<n>`; `<_spec_name>` alone when the floor is unknown (R3); `idle` when no `Plan & run:` task is `in_progress`. Ops: `<r> running` = number of projects with an `in_progress` `Plan & run:` task.
- ⚠ (`"⚠ "` prefix) when pace > 1.2, or `f` ≥ 80, or `c` ≥ 40 (ops: the max `c`). 39 → no ⚠, 40 → ⚠.
- Max 128 characters. Trim the spec name first, ending it with `…`; if still over, cut the whole line to 127 chars + `…`.
- Presence op: `{"op": "presence", "text": <str 1..128>}`. Sent only when the text differs from the last sent and ≥ 60 s since that send. Last text/time: `presence_text`/`presence_ts` in `feed-state.json` (project) or `ops-state.json` (ops).
- Bridge: `client.user.setPresence({ activities: [{ type: 4, name: 'custom', state: text }], status: 'online' })` (`ActivityType.Custom === 4`, probed: `node -e "console.log(require('discord.js').ActivityType.Custom)"` → `4`). A failure is logged and the op consumed, never retried. Re-applied on `ready`/`shardResume` (the existing `onReady`).
- Nothing in this plan posts a message.
- Delivery semantics (presence op): repeated → setting the same status twice is harmless; out of order → the bridge reads the outbox in name (time) order, newest wins; concurrent → one bridge per bot, board writes under the feed-state / ops-state flock.

**User decisions (already made):**
- Where: the bot's own custom status line, not a pinned message or card lines.
- Content: default line + running spec progress + ⚠ prefix.
- Which bots: both; each project bot its project, the ops bot one line for everything.
- ⚠ on context at 40 % or more.
- (Handoff) Fix the live card count here: the card's `(1/14)` counted queued `Plan & run:` tasks, not the spec's own tasks; `blockers: opus@medium` is wrong.

**Decided (lead rulings, queue mode):**
- R1 Blockers: `blockers:` on the ops card lists only alerts of kind `failing` or `stuck`; every other alert label (ctx, burn, total, model_mismatch `opus@medium`, day) moves to an ` · alerts: <labels>` part shown only when there are any. Cost if wrong: a ctx alert the user wanted under "blockers" now reads under "alerts".
- R2 Lead context: the live row whose `session_id` equals the project's lead session id (`planview.lead_entry`), else the highest `context_pct` among rows with `role == "lead"` and `usage.in_project(cwd, repo)`. Reason: a lead working inside a worktree is labelled `worker` by `usage.role`, so role alone misses it. Cost if wrong: a stale lead row could show.
- R3 Unknown floor (no feed-state for the project or floor `None`): the line shows the spec name without `k/n`, the card shows `queue: running <spec> (spec p of N)`.
- R4 Card queue line: `queue: running <spec> (tasks k/n · spec p of N)`; prefix `queue: running` is unchanged (pause/resume match it).
- R5 `discord_feed.tick` builds a presence line only when the caller passes `live` (not `None`), so existing tick tests stay op-for-op the same.
- R6 `project_line`/`ops_line` take the floor and lead ids as extra keyword arguments (the spec's signature lacked them).

---

### Task 1: Spec progress and card fixes

**Goal:** The project card and ops card count the running spec's own tasks, and the ops card's `blockers:` lists only failing/stuck; the `presence` op validates.

**Files:**
- Modify: `board/discord_feed.py` (`_check`, `_queue`, `render_card`; add `spec_progress`, `spec_floor`, `PRESENCE_MAX = 128`)
- Modify: `board/discord_ops.py` (`queue_text`, `_project_line`, `tick`'s `st["queues"]`)
- Test: `board/tests/test_discord_feed.py`, `board/tests/test_discord_ops.py`

**Acceptance Criteria:**
- [ ] `spec_progress(tasks, floor)` returns `(done, total)` over tasks that are not `Plan & run:` and have a numeric id > floor; `None` when floor is `None`.
- [ ] Card with a running spec and floor 13, tasks 14..19 with 2 completed, runs 2..13 with run 2 in progress → `queue: running <name> (tasks 2/6 · spec 1 of 12)`.
- [ ] Floor `None` → `queue: running <name> (spec p of N)`.
- [ ] Ops `_project_line` with alerts `[{"kind":"model_mismatch","label":"opus@medium"}]` → `blockers: none · alerts: opus@medium`; with `[{"kind":"stuck","label":"stuck 12m"}]` → `blockers: stuck 12m` and no alerts part.
- [ ] The ops card and views read each project's floor via `discord_feed.spec_floor(project)` (feed-state.json `spec_floor[running_thread_key]`, `None` when absent).
- [ ] `_check({"op":"presence","text":"x"})` passes; empty text, 129 chars, non-string text and extra keys raise `ValueError`.
- [ ] Every existing test updated to the new format; full board suite green.

**Verify:** `python3 -m unittest discover -s board/tests` → `OK`

**Steps:**

- [ ] **Step 1: Write failing tests** in `test_discord_feed.py` for `spec_progress`, the new `_queue` text (both floor cases), `spec_floor` reading a seeded `feed-state.json` under the test's `TC_STATE`, and the presence `_check` cases; in `test_discord_ops.py` for the blockers/alerts split. Mutation each guard test must catch: drop the `n > floor` filter → the `tasks 2/6` test fails; drop the kind filter → the `opus@medium` test fails.
- [ ] **Step 2: Run** `python3 -m unittest board.tests.test_discord_feed board.tests.test_discord_ops` from `board/`'s parent as the existing tests do (check the file header for the import style) → new tests FAIL.
- [ ] **Step 3: Implement.**

```python
PRESENCE_MAX = 128

def spec_progress(lead_tasks, floor):
    """(done, total) of the running spec's own tasks: not `Plan & run:`, numeric id above floor. None when floor is None."""
    if floor is None:
        return None
    own = [t for t in lead_tasks if isinstance(t, dict) and not str(t.get("subject", "")).startswith(_PLAN_RUN)
           and (_num(t.get("id")) or 0) > floor]
    return sum(t.get("status") == "completed" for t in own), len(own)


def spec_floor(project):
    """The running spec's floor from the project's feed-state.json, None when unknown."""
    import tc_env
    st = _load(tc_env.discord_dir(project) / "feed-state.json")
    v = (st.get("spec_floor") or {}).get(st.get("running_thread_key") or "")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _queue(lead_tasks, floor=None):
    runs = sorted((t for t in lead_tasks if str(t.get("subject", "")).startswith(_PLAN_RUN)), key=_tid)
    for k, t in enumerate(runs, 1):
        if t.get("status") == "in_progress":
            prog = spec_progress(lead_tasks, floor)
            tasks = f"tasks {prog[0]}/{prog[1]} · " if prog else ""
            return f"queue: running {_spec_name(t['subject'])} ({tasks}spec {k} of {len(runs)})"
    if any(t.get("status") == "pending" for t in runs):
        return "queue: paused"
    return "queue: idle"
```

`render_card` passes its `floor` to `_queue`. `_check` gains `"presence": ({"op", "text"}, set())` and, for presence, `if not op["text"] or len(op["text"]) > PRESENCE_MAX: raise ValueError("presence text must be 1..128 chars")`. In `discord_ops`: `queue_text(lead_tasks, floor=None)` and `_project_line(record, tasks, link, floor=None)` pass the floor to `_queue`; `tick` computes `floors = {p: discord_feed.spec_floor(p) for p in projects}` once and uses it for `st["queues"]`, `render_card` (thread it through `render_card(..., floors=None)`), `status` and `queue`. Blockers:

```python
BLOCKING = ("failing", "stuck")
al = [a for a in record.get("alerts") or [] if isinstance(a, dict)]
label = lambda a: str(a.get("label", a.get("kind", "?")))
blockers = ", ".join(label(a) for a in al if a.get("kind") in BLOCKING) or "none"
others = ", ".join(label(a) for a in al if a.get("kind") not in BLOCKING)
line = (f"**{p}** · {discord_feed._queue(tasks, floor)} · blockers: {blockers}" + (f" · alerts: {others}" if others else "")
        + f" · waiting on you: {len(record.get('needs_you') or [])}")
```

- [ ] **Step 4: Update the existing assertions** that expect `(1/2)`-style text or `blockers: ctx 90%` to the new format (seeded `queues` strings in pause/resume tests can stay: they only need the `queue: running` prefix).
- [ ] **Step 5: Run** `python3 -m unittest discover -s board/tests` → `OK`.
- [ ] **Step 6: Commit** `git add board/discord_feed.py board/discord_ops.py board/tests/test_discord_feed.py board/tests/test_discord_ops.py` then `git commit -m "fix(discord): cards count the running spec's own tasks; blockers are failing/stuck only"` (end with the attribution trailer your harness specifies).

```json:metadata
{"files": ["board/discord_feed.py", "board/discord_ops.py", "board/tests/test_discord_feed.py", "board/tests/test_discord_ops.py"], "verifyCommand": "python3 -m unittest discover -s board/tests", "acceptanceCriteria": ["spec_progress done/total above floor, None without floor", "card: queue: running <name> (tasks 2/6 · spec 1 of 12)", "floor None: (spec p of N)", "ops blockers only failing/stuck, other labels under alerts:", "ops card reads floors via spec_floor", "_check presence 1..128 string", "board suite OK"], "modelTier": "standard"}
```

### Task 2: Ticker line builders

**Goal:** `board/ticker.py` with pure `project_line` and `ops_line` that produce the exact lines of Global Constraints.

**Files:**
- Create: `board/ticker.py`
- Test: `board/tests/test_ticker.py`

**Acceptance Criteria:**
- [ ] `project_line(record, live, limits, lead_tasks, now, floor=None, lead_sid="")` and `ops_line(records, live, limits, tasks_by_project, now, floors=None, lead_sids=None)` exist; both return `str` ≤ 128 chars; no I/O, no imports beyond stdlib, `discord_feed` and `usage`.
- [ ] Fixture with w=33, resets_at = now + 4 d, f=25, lead ctx 23, spend 12.345, spec `2026-11-17-discord-ticker-design` running with 2/6 → exactly `wk 33% ▲0.8× · 5h 25% · ctx 23% · $12.35 · 2026-11-17-discord-ticker-design 2/6` (0.33/(3/7)=0.77 → `0.8`).
- [ ] Pace `—` with resets_at = now + 7 d − 11 h (under 12 h), and with no `resets_at`.
- [ ] ⚠ for pace 1.3, f 80, ctx 40; no ⚠ for ctx 39, f 79, pace 1.2.
- [ ] Stale limits (`received_at` = now − 601): `wk ?% ▲?× · 5h ?%` and no ⚠ even with used 99.
- [ ] No limits (`None`): same `?` fields.
- [ ] A 200-char spec name is trimmed with `…` and the line is exactly 128 chars, keeping every other field.
- [ ] Idle (no in-progress run) → ends with `· idle`; floor `None` → spec name with no `k/n`.
- [ ] Lead pick (R2): the `lead_sid` row wins over a role-lead row with higher ctx; without `lead_sid`, the max ctx role-lead row in the project; rows of another repo ignored; none → `ctx —`.
- [ ] Ops: two projects with ctx 23 and 41 → `ctx max 41% <that project>` and ⚠; spend 1.5 + None + 2.25 → `$3.75`; two running specs out of three → `2 running`.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_ticker.py'` → `OK`

**Steps:**

- [ ] **Step 1: Write `test_ticker.py`** with one test per criterion above. Fixtures: `limits = {"session_id": "s", "received_at": now - 30, "five_hour": {"used_percentage": 25}, "seven_day": {"used_percentage": 33, "resets_at": now + 4 * 86400}}`; `live = [{"session_id": "L1", "role": "lead", "cwd": "/r/a", "context_pct": 23}]`; `record = {"project": "a", "path": "/r/a", "spend_today": 12.345}`; tasks: runs `{"id": "2", "subject": "Plan & run: docs/superpowers/specs/2026-11-17-discord-ticker-design.md", "status": "in_progress"}` plus ids 14..19 with 14 and 15 completed, floor 13. Mutations to check in RED: remove the stale check → the stale test fails; change `>= 40` to `> 40` → the ctx-40 test fails.
- [ ] **Step 2: Run** → FAIL (no module).
- [ ] **Step 3: Implement** `board/ticker.py`. Helpers: `_limits(limits, now)` → `(w, f, resets_at)` with `None` for unknown/stale; `_pace(w, resets_at, now)` → float or `None` (for `—`); `_lead_ctx(live, repo, sid)` per R2 (repo from `record["path"]`, match with `usage.in_project`); `_spec(lead_tasks, floor)` → `("<name>", "k/n" or "")` or `None` for idle, using `discord_feed._spec_name` and `discord_feed.spec_progress`; `_fit(prefix, name, suffix)` trims `name` so the whole is ≤ 128. Formatting per Global Constraints. ⚠ only from known values.
- [ ] **Step 4: Run** → `OK`.
- [ ] **Step 5: Commit** `git add board/ticker.py board/tests/test_ticker.py` then `git commit -m "feat(board): ticker line builders for the discord status line"` (attribution trailer from your harness).

```json:metadata
{"files": ["board/ticker.py", "board/tests/test_ticker.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_ticker.py'", "acceptanceCriteria": ["signatures and pure", "exact fixture line", "pace dash under 12h and without reset", "warn thresholds incl ctx 39/40", "stale and missing limits give ? and no warn", "128 trim on spec name", "idle and unknown floor", "lead pick by sid then role", "ops max ctx, spend sum, running count"], "modelTier": "standard"}
```

### Task 3: Presence ops from the board ticks

**Goal:** The project feed tick and the ops tick write a throttled `presence` op with the ticker line, and `server.feed_tick` passes them the live rows, limits and lead ids.

**Files:**
- Modify: `board/discord_feed.py` (`tick`, add `presence_op_due`, `PRESENCE_EVERY = 60`)
- Modify: `board/discord_ops.py` (`tick`)
- Modify: `board/server.py` (`feed_tick`, `ops_tick`, `overview_payload`)
- Test: `board/tests/test_discord_feed.py`, `board/tests/test_discord_ops.py`, `board/tests/test_discord_wiring.py`

**Acceptance Criteria:**
- [ ] `presence_op_due(state, text, now)` → `{"op":"presence","text":text}` when text ≠ `state["presence_text"]` and `now - state.get("presence_ts", 0) >= 60`, else `None`.
- [ ] `discord_feed.tick(..., live=None, limits=None, lead_sid="")`: with `live` given, a changed line writes one presence op and saves `presence_text`/`presence_ts`; same text → no op; changed text 30 s later → no op; 60 s later → op. With `live=None`, no presence op (R5).
- [ ] `discord_ops.tick(records, tasks_by_project, limits, now, add_line, live=None, lead_sids=None)` writes the ops line the same way into the ops outbox, state in `ops-state.json`; nothing when `live is None` or ops is not configured.
- [ ] `server.feed_tick(records, now, live=None)`: computes `limits` once (same try/except as `ops_tick`), keeps each project's lead sid from `planview.lead_entry`, passes `live`, `limits`, `lead_sid` to `discord_feed.tick` and `live`, `lead_sids` to `ops_tick` → `discord_ops.tick`; `overview_payload` passes `live=INDEXER.snapshot() if INDEXER else []`.
- [ ] A presence failure path cannot break the card: a bad line (e.g. `_check` ValueError) is logged and the rest of the tick's ops are still written.
- [ ] Full board suite green.

**Verify:** `python3 -m unittest discover -s board/tests` → `OK`

**Steps:**

- [ ] **Step 1: Tests first.** Feed: drive `tick` three times with a fake clock (t, t+30 changed text, t+61) under the test's `TC_STATE`, read the outbox files, count `presence` ops: 1, 1, 2. Same text at t+120 → still 2. Mutation: drop the 60 s check → the t+30 assertion fails. Ops: same pattern via `discord_ops.tick` with a configured ops dir (copy the existing ops test setup). Wiring: extend `test_discord_wiring.py` so `feed_tick` with a stub `discord_feed.tick` records `live`, `limits`, `lead_sid` kwargs.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** In `discord_feed.tick`, after the card op:

```python
if live is not None:
    import ticker
    line = ticker.project_line(record, live, limits, lead_tasks or [], now,
                               floor=st.get("spec_floor", {}).get(st.get("running_thread_key")), lead_sid=lead_sid)
    pres = presence_op_due(st, line, now)
    if pres:
        ops.append(pres)
```

and after writing, `if pres and <it was written>: st["presence_text"], st["presence_ts"] = line, now` (track written-ness per op so a rejected op does not save its text). Same in `discord_ops.tick` with `ticker.ops_line(records, live, limits, tasks_by_project, now, floors=floors, lead_sids=lead_sids)` (reuse Task 1's `floors`).
- [ ] **Step 4: Run** → `OK`.
- [ ] **Step 5: Commit** `git add board/discord_feed.py board/discord_ops.py board/server.py board/tests/test_discord_feed.py board/tests/test_discord_ops.py board/tests/test_discord_wiring.py` then `git commit -m "feat(discord): throttled presence ops from the feed and ops ticks"` (attribution trailer from your harness).

```json:metadata
{"files": ["board/discord_feed.py", "board/discord_ops.py", "board/server.py", "board/tests/test_discord_feed.py", "board/tests/test_discord_ops.py", "board/tests/test_discord_wiring.py"], "verifyCommand": "python3 -m unittest discover -s board/tests", "acceptanceCriteria": ["presence_op_due change + 60s", "feed tick presence throttled and state saved only when written", "live=None writes no presence", "ops tick presence into ops outbox", "server passes live, limits, lead ids", "bad presence op does not block other ops", "board suite OK"], "modelTier": "standard"}
```

### Task 4: Bridge applies presence

**Goal:** The node bridge, in both modes, applies a `presence` op as the bot's custom status and re-applies it after a reconnect.

**Files:**
- Modify: `tools/discord-bridge/bridge.js` (add `opPresence` to `handlers`; re-apply in `onReady`)
- Modify: `tools/discord-bridge/test/fake-client.js` (`user.setPresence` recorder)
- Test: `tools/discord-bridge/test/bridge.test.js`

**Acceptance Criteria:**
- [ ] A `{"op":"presence","text":"wk 1%"}` outbox file → `client.user.setPresence` called once with `{ activities: [{ type: 4, name: 'custom', state: 'wk 1%' }], status: 'online' }`, the file removed, `bridge.log` gets `presence wk 1%`. Works with `ops: true` and `ops: false`.
- [ ] After that, `onReady()` (what `shardResume` calls) calls `setPresence` again with the same text; before any presence op, `onReady()` does not call it.
- [ ] `setPresence` throwing → logged as `presence failed: <msg>`, the file removed (not moved to failed, not retried), next op still processed.
- [ ] A presence op whose `text` is not a non-empty string → moved to `failed/` (existing failure path).
- [ ] `cd tools/discord-bridge && npm test` passes.

**Verify:** `cd tools/discord-bridge && npm test` → all pass, `# fail 0`

**Steps:**

- [ ] **Step 0:** The worktree has no `node_modules`; link the main checkout's: `ln -s /Users/francisco.ruiz/agent-board/tools/discord-bridge/node_modules tools/discord-bridge/node_modules` (do not commit it; check `git status` shows it ignored or untracked and never `git add` it).
- [ ] **Step 1: Tests.** In `fake-client.js` give `this.user` a `setPresence(p) { this.presences.push(p); if (this.presenceError) throw this.presenceError; return {}; }` and `this.presences = []`. In `bridge.test.js` follow the existing outbox-op tests' setup (temp dir, `createBridge({dir, client, log})`, write the op with the outbox helper, `await bridge.tick()`). Mutation: remove the `onReady` re-apply → the reconnect test fails.
- [ ] **Step 2: Run** `npm test` → new tests FAIL.
- [ ] **Step 3: Implement** in `createBridge`:

```js
const PRESENCE_MAX = 128;
let presenceText = null;
function applyPresence() {
  if (presenceText === null || !client.user?.setPresence) return;
  client.user.setPresence({ activities: [{ type: 4, name: 'custom', state: presenceText }], status: 'online' });
}
async function opPresence(op) {
  if (typeof op.text !== 'string' || !op.text) throw new Error('presence text must be a non-empty string');
  presenceText = op.text.slice(0, PRESENCE_MAX);
  try { applyPresence(); say(`presence ${snip(presenceText)}`); } catch (e) { say(`presence failed: ${snip(e?.message)}`); }
}
```

Add `presence: opPresence` to `handlers`; in `onReady`, after `register(ch)`: `try { applyPresence(); } catch (e) { say(`presence failed: ${snip(e?.message)}`); }`. The thrown-error path inside `opPresence` returns normally, so `tick` removes the file (consumed).
- [ ] **Step 4: Run** `npm test` → pass.
- [ ] **Step 5: Commit** `git add tools/discord-bridge/bridge.js tools/discord-bridge/test/fake-client.js tools/discord-bridge/test/bridge.test.js` then `git commit -m "feat(discord-bridge): presence op sets the bot's custom status"` (attribution trailer from your harness).

```json:metadata
{"files": ["tools/discord-bridge/bridge.js", "tools/discord-bridge/test/fake-client.js", "tools/discord-bridge/test/bridge.test.js"], "verifyCommand": "cd tools/discord-bridge && npm test", "acceptanceCriteria": ["presence op calls setPresence with custom activity type 4, both modes, file removed, logged", "onReady re-applies last text, not before any op", "setPresence throw logged and consumed", "bad text moved to failed", "npm test passes"], "modelTier": "standard"}
```

### Task 5: Real-state check and full suite

**Goal:** A read-only command prints both lines from this Mac's live state, and its `k/n` matches the running plan's own task count; the whole repo suite is green.

**Files:**
- Modify: `board/ticker.py` (add `main()` behind `if __name__ == "__main__":`)
- Test: `board/tests/test_ticker.py` (one test of `main` with stubbed inputs)

**Acceptance Criteria:**
- [ ] `python3 board/ticker.py <project>...` prints `project <name>: <line>` per project, then `ops: <line>`; reads only: taps (`usage.tap_entries`/`plan_limits`), the usage index (`usage.connect(usage.db_path())`, `usage.live_sessions(conn, usage.load_prices(), usage.thresholds()[0], now)`), `usage.spend_since(conn, repo, usage._midnight(now, 0), prices)`, tmux session paths (`tmux display -p -t "=<name>:" '#{session_path}'`), `planview.lead_entry`/`raw_live_list` with `home=~/.claude`, and `discord_feed.spec_floor`. It writes nothing (no outbox, no state).
- [ ] Real run (read-only, the user's live state): `python3 board/ticker.py agent-board` while this plan runs prints a project line whose `k/n` has `n` = the number of this plan's tasks in the lead's live list above the floor (6 = Tasks 1-5 + the user gate), not 12/13 (the queue) and not the whole list; `w`/`f` are numbers (fresh taps exist), and `ctx` is a number.
- [ ] `zsh tools/tests/all.zsh` verdict line: ALL PASS (an rc from the time budget only is reported as such, with the line).

**Verify:** `python3 board/ticker.py agent-board && zsh tools/tests/all.zsh; echo rc=$?`

**Steps:**

- [ ] **Step 1:** Test `main` with `usage`, `planview`, `tmux` and `discord_feed.spec_floor` patched (`unittest.mock.patch.object`), asserting the printed lines and that no file under the test's `TC_STATE` is created (mutation: make `main` call `discord_feed.tick` → the no-write assertion fails).
- [ ] **Step 2:** Implement `main()`; a project with no tmux session prints `project <name>: no session` and is skipped.
- [ ] **Step 3:** Run the real check from the worktree: `python3 board/ticker.py agent-board`. Report the two printed lines and, beside them, the lead's own count: `python3 -c` that loads the same raw list and floor and prints `done/total` (or read it from the `tasks` window). They must match.
- [ ] **Step 4:** `zsh tools/tests/all.zsh; echo rc=$?` → paste the verdict line.
- [ ] **Step 5: Commit** `git add board/ticker.py board/tests/test_ticker.py` then `git commit -m "feat(board): ticker.py prints the live status lines (read-only check)"` (attribution trailer from your harness).

```json:metadata
{"files": ["board/ticker.py", "board/tests/test_ticker.py"], "verifyCommand": "python3 board/ticker.py agent-board && zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["main prints project and ops lines read-only", "real run k/n equals this plan's own task count", "all.zsh ALL PASS"], "modelTier": "standard"}
```

### Task 6: User gate — the line on the phone

**Goal:** The user sees both bots' status lines in Discord's member list and sees them change.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none (runs on the merged `main` with both bridges restarted)

**Acceptance Criteria:**
- [ ] After `tmux-ctl discord bridge restart` (project) and the ops bridge restart, `bridge.log` of each shows a `presence …` line.
- [ ] The user confirms on the phone that the agent-board bot and the ops bot each show the line in the member list.
- [ ] The user confirms the line changes within about 2 min of a change (e.g. a task completing).

**Verify:** `grep presence ~/.local/state/agent-board/discord/agent-board/bridge.log | tail -3; grep presence ~/.local/state/agent-board/discord/_ops/bridge.log | tail -3`

```json:metadata
{"files": [], "verifyCommand": "grep presence ~/.local/state/agent-board/discord/agent-board/bridge.log | tail -3; grep presence ~/.local/state/agent-board/discord/_ops/bridge.log | tail -3", "acceptanceCriteria": ["both bridge.log files show presence lines", "user sees both lines in the member list", "user sees the line change within ~2 min"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```
