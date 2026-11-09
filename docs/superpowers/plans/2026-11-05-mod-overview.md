# Mod overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The overview tab says what each agent is doing, why one needs the user, how long it has been in its state, and that one looks stuck or failing, from fields the agent-status mod writes.

**Architecture:** `claude/plugin/mods/agent-status.js` adds five fields to its per-session JSON file. `board/paneclass.py` gains `mod_records()` (pane → full fresh record) and `mod_states()` derives from it. `board/overview.py` takes those records as a new `mods` argument and adds `agents`, `needs_you[].reason`, a mod-based lead `idle_s` and two alert kinds; `board/server.py` passes them. `board/notify.py` and the overview page in `board/index.html` show the new data.

**Tech Stack:** Claude Code mods (JS, `claude plugin test`), Python 3 stdlib (unittest), vanilla JS page.

**Spec:** `docs/superpowers/specs/2026-11-05-mod-overview-design.md`

## Global Constraints

- Status file fields (spec §1), exact names: `tool` = `{"name", "arg", "startedAt"}` or `null`; `turnStartedAt`; `waiting` = `{"kind": "question"|"permission", "detail"}` or `null`; `failStreak` (int, starts 0); `lastToolAt` (epoch seconds or `null`). Existing fields `session_id, pane, state, since, updatedAt` unchanged. All times epoch **seconds** (the file's existing `secs()`).
- `arg`: Bash → the command's first line; Edit / Write / Read / MultiEdit → the file path; Agent → its description; anything else → `""`. Always cut to **80** characters. `tool.call`'s `e` carries the arguments **flat** (`e.command`, `e.file_path`, `e.description`, `e.questions`); `tool.check`'s carries them under `e.input`; `classic.PermissionRequest` under `e.tool_input` (probe: `docs/superpowers/notes/2026-11-05-shell-hooks-probe.md` L12).
- `waiting.detail`: question → AskUserQuestion's first question `header`, else its first question `question` text; permission → `"<tool>: <arg>"`. `waiting` is cleared exactly where `state` leaves `needs-you`.
- A failed tool call = `next()` resolves with `isError: true` (refused/denied calls included, probe (a),(b),(d)) or throws. A success resets `failStreak` to 0.
- Freshness of a status file: the existing `mod_states()` rule (pane is a string, state known, `-5 < now − updatedAt < 45`); the newest file per pane wins.
- Overview `RECORD_KEYS` gains `agents` only. Every existing record field keeps its name and type; new data is additions (`agents`, `needs_you[].reason`, new alert kinds).
- `agents[]` entry: `{"window", "pane", "state", "state_s", "tool", "turn_s"}`; `state` is the board status (`working`/`waiting`/`ready`); `state_s = now − since`, `turn_s = now − turnStartedAt` (or `null`), `tool` = `"<name>: <arg>"` (just `"<name>"` when arg is empty) or `null`; ints (`int(max(0, …))`). A pane without a fresh file: `state` from the board, the rest `null`.
- Thresholds in `usage.DEFAULT_ALERTS`: `failing_streak` 3, `stuck_turn_s` 1200, `stuck_quiet_s` 600.
- Alerts (per agent with a fresh file): `{"kind": "failing", "session": <window>, "fail_streak": n}` when `failStreak ≥ failing_streak`; `{"kind": "stuck", "session": <window>, "turn_s": s}` when the file's state is `busy`, `turn_s ≥ stuck_turn_s` and quiet ≥ `stuck_quiet_s` (quiet = `now − lastToolAt` when `lastToolAt ≥ turnStartedAt`, else `now − turnStartedAt`).
- Page agent line: `<window> · <state> <duration> · <tool>`, e.g. `✦ qrev · busy 12m · Bash: zsh tools/tests/run-all.zsh`, duration via the page's `fmtAge`.
- Every mod I/O stays wrapped: a mod error never blocks a tool or a turn. `claude plugin validate claude/plugin` must pass.
- User rule: never run the full suites; run only the targeted test files named in each task.
- Commits: conventional with scope; end with the attribution trailer your harness specifies.

**User decisions (already made):**
- All four additions: what each agent is doing; why it needs you; exact state durations; stuck / failing signals.
- Approach: extend the agent-status file (one file and one writer per session), not a second mod or an event log.

**Plan rulings (lead, queue mode):**
- Ruling: the page shows board states as words `working → busy`, `waiting → needs you`, `ready → idle` (the spec's example line says `busy`) — costs a label change if wrong.
- Ruling: `failing`/`stuck` alert dicts also carry `label` and `detail` (the page and notifier render `label`/`detail` for every alert) and `context_pct: None` like the day alert — additions only.
- Ruling: with parallel tool calls, `tool` holds the most recently started call and is cleared only when that same call (`tool_use_id`) ends — costs a briefly stale `tool` line if wrong.
- Ruling: `overview.build`/`record` get a keyword `mods=None` (pane id → fresh record); `server.build_overview` passes `paneclass.mod_records(now)` — keeps overview.py free of file I/O like its other inputs.
- Ruling: notify gets kinds `failing` (key = session window) and `stuck` (key = session window), sent through the existing latch and rate limit.

---

### Task 1: agent-status mod writes the new fields

**Goal:** `agent-status.js` writes `tool`, `turnStartedAt`, `waiting`, `failStreak`, `lastToolAt` per the Global Constraints, with tests.

**Files:**
- Modify: `claude/plugin/mods/agent-status.js`
- Test: `claude/plugin/mods/agent-status.test.ts`

**Acceptance Criteria:**
- [ ] `render()` emits the five new keys; a fresh session writes `tool: null, turnStartedAt: null, waiting: null, failStreak: 0, lastToolAt: null`.
- [ ] `tool` is set (and flushed) when a main-agent `tool.call` starts and cleared when its `next()` returns or throws; `arg` follows the per-tool rule and is ≤ 80 chars (test with a 200-char command and a 2-line command).
- [ ] `turnStartedAt` set at `turn.start`, `null` at `turn.complete`, `session.start`, and the clear/resume reset in `end()`.
- [ ] `waiting` = question kind with header (and with question text when no header) while an AskUserQuestion is open; permission kind `"<tool>: <arg>"` for both dialog paths (`classic.PermissionRequest`, and `tool.check` ask when classic hooks are absent); `null` after the state leaves `needs-you`.
- [ ] `failStreak` increments on `isError: true` and on a throwing `next()`, resets to 0 on success; `lastToolAt` set when a call ends.
- [ ] Events with `e.agentId` change none of the new fields.
- [ ] Each new test names its mutation and fails under it (report shows the RED runs).

**Verify:** `claude plugin test claude/plugin && claude plugin validate claude/plugin` → `0 fail`, validation passed, exit 0

**Steps:**

- [ ] **Step 1: Write the failing tests** in `agent-status.test.ts`, using the file's `world()` harness (`under.call` answers `tool.call`; return `{ result: 'Error: Exit code 1', text: 'Exit code 1', isError: true }` for a failure, throw for an interrupt). Cases and the mutation each must catch:
  - fresh file has the five keys with their initial values — mutation: drop `failStreak` from `render()`.
  - Bash call: during the gated call the file has `tool.name === 'Bash'`, `tool.arg` = first line, `startedAt` set; after, `tool === null`, `lastToolAt` set — mutation: remove the clear after `next()`.
  - 200-char command → `arg.length === 80` — mutation: drop the `.slice(0, 80)`.
  - Read / Edit → file path; Agent → description; `Grep` → `""`.
  - turn.start then turn.complete → `turnStartedAt` set then `null` — mutation: don't null it at turn.complete.
  - AskUserQuestion with `questions: [{header: 'Scope', question: 'Which?'}]` → `waiting = {kind:'question', detail:'Scope'}`; without header → `'Which?'`; after the answer `waiting === null` — mutation: don't clear `waiting` in `setState`.
  - permission dialog via `classic.PermissionRequest` (`tool_input.command = 'rm x'`) → `{kind:'permission', detail:'Bash: rm x'}`.
  - two failures → `failStreak 2`; then a success → `0`; a throwing `next()` counts — mutation: reset on every call.
  - a `tool.call` with `agentId` leaves `tool`, `failStreak`, `lastToolAt` unchanged.
- [ ] **Step 2: Run** `claude plugin test claude/plugin` → the new tests FAIL (missing keys), existing ones pass.
- [ ] **Step 3: Implement.** In `agent-status.js`:

```js
const ARG_MAX = 80
// the short argument shown beside a tool's name; `a` is the call's arguments (flat on tool.call, e.input on tool.check)
const argOf = (tool, a) => {
  a = a || {}
  let s = ''
  if (tool === 'Bash') s = String(a.command || '').split('\n')[0]
  else if (['Edit', 'Write', 'Read', 'MultiEdit'].includes(tool)) s = String(a.file_path || '')
  else if (tool === 'Agent') s = String(a.description || '')
  return s.slice(0, ARG_MAX)
}
const questionDetail = (a) => {
  const q = (a && Array.isArray(a.questions) && a.questions[0]) || {}
  return String(q.header || q.question || '').slice(0, ARG_MAX)
}
```

  - `st` (in `start`) gains `tool: null, toolId: null, turnStartedAt: null, waiting: null, failStreak: 0, lastToolAt: null`; `render()` adds the five keys (not `toolId`).
  - `setState`: when `state !== 'needs-you'`, also `st.waiting = null`.
  - `dialogOpen($, a, waiting)`: set `st.waiting = waiting` together with `askId`. Asks store their arguments: in `tool.check`, `args: (e && e.input) || {}`; the permission waiting is `{kind: 'permission', detail: (a.tool + ': ' + argOf(a.tool, a.args)).slice(0, ARG_MAX)}`, built the same way from `e.tool_input` in `classic.PermissionRequest`. The AskUserQuestion path passes `{kind: 'question', detail: questionDetail(e)}`.
  - `tool.call` (main agent only): before `next`, `st.tool = {name: e.tool, arg: argOf(e.tool, e), startedAt: secs(now)}`, `st.toolId = e.tool_use_id`, `st.updatedAt = secs(now)`, flush. After `next` (in the existing `finally` path, also on throw): `st.lastToolAt = secs(now)`; `failStreak` = threw or `out.isError` ? +1 : 0; if `st.toolId === e.tool_use_id` clear `tool`/`toolId`; flush (the existing busy flush may cover it — one flush per call end).
  - `turn.start`: `st.turnStartedAt = secs(now)` before its flush; `turn.complete`: `null`. `end()` clear/resume reset: `turnStartedAt = null, tool = null, toolId = null, waiting = null` (keep `failStreak`, `lastToolAt`).
  - Keep every new line inside the existing try blocks.
- [ ] **Step 4: Run** the Verify command → all pass, validate passed.
- [ ] **Step 5: Commit** `feat(mods): agent-status records the running tool, turn start, waiting reason and failures` (attribution trailer per your harness).

```json:metadata
{"files": ["claude/plugin/mods/agent-status.js", "claude/plugin/mods/agent-status.test.ts"], "verifyCommand": "claude plugin test claude/plugin && claude plugin validate claude/plugin", "acceptanceCriteria": ["render emits the five new keys with initial values", "tool set during a main-agent call and cleared after; arg per tool, <=80 chars", "turnStartedAt set at turn.start, null at turn.complete/session.start/clear reset", "waiting question/permission set while needs-you, null after", "failStreak counts isError and throws, resets on success; lastToolAt set", "agentId events change no new field", "each new test fails under its named mutation"], "modelTier": "standard"}
```

---

### Task 2: overview record carries agents, reasons, durations and alerts

**Goal:** `paneclass.mod_records()`, the three thresholds, and `overview.py`'s `agents`, `needs_you[].reason`, mod-based lead `idle_s`, and `failing`/`stuck` alerts, wired through `server.build_overview`.

**Files:**
- Modify: `board/paneclass.py`, `board/usage.py`, `board/overview.py`, `board/server.py`
- Test: `board/tests/test_paneclass.py` (or the file holding the existing `mod_states` tests: `grep -rln mod_states board/tests`), `board/tests/test_overview.py`, `board/tests/test_usage.py` (thresholds)
- Create: `board/tests/fixtures/agent-status/` fixture files

**Acceptance Criteria:**
- [ ] `mod_records(now=None, d=None)` → `{pane: record}` (the parsed JSON dict), same freshness and newest-per-pane rule as today; `mod_states()` returns `{pane: MOD_STATES[rec["state"]]}` built from it; existing `mod_states` tests pass unchanged.
- [ ] `usage.DEFAULT_ALERTS` has `failing_streak: 3, stuck_turn_s: 1200, stuck_quiet_s: 600`; an alerts file can override each.
- [ ] `RECORD_KEYS` ends with `"agents"`; `build(..., mods=None)` and `record(..., mods)`; `mods=None` gives every agent `null` extras and no new alerts (old callers unchanged).
- [ ] `agents` lists every pane with `kind == "claude"` in window order: fresh file → `state_s`, `turn_s`, `tool` per Global Constraints; no file → `null`s.
- [ ] `lead.idle_s` = `now − since` when the lead pane's file is fresh and its state is `ready`; otherwise today's window-activity value.
- [ ] `needs_you[]` entries gain `reason` (`"question: <detail>"` / `"permission: <detail>"` from a fresh file's `waiting`, else `None`).
- [ ] `failing` and `stuck` alerts per Global Constraints, with `label`/`detail`/`context_pct: None`; tests at threshold − 1 (no alert) and at threshold (alert) for `failStreak`, `turn_s` and quiet; stuck uses the whole turn when `lastToolAt` is `null` or older than `turnStartedAt`.
- [ ] Fixtures: one file copied from a real current status file in `${TMPDIR%/}/tmux-ctl-$UID/agent-status/` (pane/session id replaced with fixture values, the real field set kept: this is the "old file without the new fields" case, which must read as `null`/0), the others derived from it with the new fields.
- [ ] `server.build_overview` passes `mods=paneclass.mod_records(now)`.

**Verify:** `python3 -m unittest board.tests.test_overview board.tests.test_paneclass board.tests.test_usage board.tests.test_overview_api 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Write failing tests.** In the overview tests build sessions with the file's `card()` helper and pass `mods={pane_id: record}`. Name each mutation: `stuck` at exactly `stuck_turn_s` alerts (mutation: `>` instead of `≥` fails it); quiet uses `turnStartedAt` when `lastToolAt` predates the turn (mutation: always use `lastToolAt`); `reason` is `None` for a stale file (mutation: skip the freshness check in `mod_records`); lead `idle_s` from `since` (mutation: keep the window-activity value).
- [ ] **Step 2: Run** the Verify command → the new tests fail, others pass.
- [ ] **Step 3: Implement.** `paneclass.mod_records` holds today's loop but keeps `(rec, upd)`; `mod_states` maps it. In `overview.py`:

```python
def _secs(now, t):
    return int(max(0, now - t)) if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def agents(s, mods, now):
    out = []
    for w in s.get("windows") or []:
        for p in w.get("panes") or []:
            if p.get("kind") != "claude":
                continue
            rec = (mods or {}).get(p["id"])
            t = (rec or {}).get("tool")
            tool = (f"{t['name']}: {t['arg']}" if t.get("arg") else t.get("name")) if isinstance(t, dict) and t.get("name") else None
            out.append({"window": w["name"], "pane": p["id"], "state": p.get("status"),
                        "state_s": _secs(now, rec.get("since")) if rec else None,
                        "turn_s": _secs(now, rec.get("turnStartedAt")) if rec else None, "tool": tool})
    return out
```

  `needs_you(s, mods)` adds `reason`; `lead_state(s, win_activity, now, mods)` overrides `idle_s`; `agent_alerts(s, mods, now, th)` returns the two kinds (label e.g. `"failing ×3"` / `"stuck 25m"`, detail a sentence naming the window), appended in `record` after `project_alerts`. `usage.DEFAULT_ALERTS` gains the three keys.
- [ ] **Step 4: Run** the Verify command → `OK`.
- [ ] **Step 5: Commit** `feat(board): overview agents, needs-you reasons, durations and stuck/failing alerts`.

```json:metadata
{"files": ["board/paneclass.py", "board/usage.py", "board/overview.py", "board/server.py", "board/tests/test_overview.py", "board/tests/test_paneclass.py", "board/tests/test_usage.py", "board/tests/fixtures/agent-status/"], "verifyCommand": "python3 -m unittest board.tests.test_overview board.tests.test_paneclass board.tests.test_usage board.tests.test_overview_api 2>&1 | tail -3", "acceptanceCriteria": ["mod_records returns fresh records; mod_states derives from it, old tests pass", "DEFAULT_ALERTS has failing_streak 3, stuck_turn_s 1200, stuck_quiet_s 600", "RECORD_KEYS gains agents; mods=None keeps old behaviour", "agents per claude pane with state_s, turn_s, tool or nulls", "lead idle_s from since when fresh and ready", "needs_you reason from waiting", "failing and stuck alerts at threshold, not below; stuck quiet rule", "one fixture copied from a real status file", "server passes mod_records"], "modelTier": "standard"}
```

---

### Task 3: page agent lines, reasons, and notifier kinds

**Goal:** The overview card shows one line per agent and the needs-you reason; `failing`/`stuck` alerts render as badges and notify once per onset.

**Files:**
- Modify: `board/index.html` (overview `ovRow`), `board/notify.py`
- Test: `board/tests/test_overview_home_ui.py`, `board/tests/test_notify.py`

**Acceptance Criteria:**
- [ ] `ovRow` appends, per `p.agents` entry, a line `<window> · <word> <fmtAge(state_s)> · <tool>` (`working→busy`, `waiting→needs you`, `ready→idle`; the duration part omitted when `state_s` is null, the tool part when `tool` is null); a record without `agents` renders as today.
- [ ] Needs-you lines read `<window> needs you — <reason>` when `reason` is set, else as today.
- [ ] `failing`/`stuck` alerts show as badges (the existing alert loop); `alertColor` (`board/index.html:555`, today amber only for `context`/`burn`, red otherwise) returns amber for `failing` and `stuck`.
- [ ] `notify.KINDS` gains `failing`, `stuck`; `conditions()` adds one per alert with key = session; title `"<project>: agent failing"` / `"<project>: agent stuck"`; text names the window and the count/minutes. Latch test: fires once on onset, not again while held, again after clearing.

**Verify:** `python3 -m unittest board.tests.test_overview_home_ui board.tests.test_notify 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Write failing tests** following each file's existing style (the home-UI test drives the page script; mirror an existing `ovRow`/needs-you test). Mutations: drop the reason suffix → the reason test fails; omit `failing` from `conditions()` → the notify onset test fails.
- [ ] **Step 2: Run** Verify → new tests fail.
- [ ] **Step 3: Implement** in `ovRow`, after the needs-you loop:

```js
const OV_WORD = { working: "busy", waiting: "needs you", ready: "idle" };
for (const a of p.agents || []) {
  const parts = [a.window, [OV_WORD[a.state] || a.state || "", a.state_s != null ? fmtAge(a.state_s) : ""].filter(Boolean).join(" ")];
  if (a.tool) parts.push(a.tool);
  sub.append(el("div", "ov-agent ov-muted", parts.join(" · ")));
}
```

  and the needs-you line `` `${n.window} needs you${n.reason ? ` — ${n.reason}` : ""}` ``. In `notify.conditions`, inside the alerts loop: `elif a.get("kind") == "failing": add(name, "failing", who, f"{name}: agent failing", f"{who} failed {a.get('fail_streak')} tool calls in a row")` and the `stuck` analogue with `turn_s // 60` minutes. Change `alertColor` to `(kind) => (["context", "burn", "failing", "stuck"].includes(kind) ? "amber" : "red")`.
- [ ] **Step 4: Run** Verify → `OK`.
- [ ] **Step 5: Commit** `feat(board): overview agent lines, needs-you reasons, stuck/failing notifications`.

```json:metadata
{"files": ["board/index.html", "board/notify.py", "board/tests/test_overview_home_ui.py", "board/tests/test_notify.py"], "verifyCommand": "python3 -m unittest board.tests.test_overview_home_ui board.tests.test_notify 2>&1 | tail -3", "acceptanceCriteria": ["agent line per agents entry with state word, duration, tool", "needs-you line carries the reason", "failing/stuck render as badges", "notify fires failing/stuck once per onset"], "modelTier": "standard"}
```

---

### Task 4: real run and real-state check

**Goal:** One real lead session on a test board shows the agent line during a Bash call and the reason during an AskUserQuestion; the worktree board's `/api/overview` against the user's real tmux state only adds keys to what the live board (`:7700`, `main`) returns.

**Files:**
- Create: `tools/tests/e2e-mod-overview.md` (the run record)
- Create: `board/tests/fixtures/agent-status/real-new-fields.json` (a status file captured during the run, ids replaced), and a test in `board/tests/test_overview.py` that loads it

**Acceptance Criteria:**
- [ ] Scratch run (follow `tools/tests/e2e-agent-status.md` for the setup: scratch tmux `-L` with `-f /dev/null`, temp `TC_STATE`, the plugin from this worktree, test board `TMUX_DASH_PORT=7710 TMUX_DASH_TOKEN=x TMUX_DASH_TMUX_ARGS='-L <sock>' TC_OVERSEER=0 TC_NOTIFY=0`): during a `sleep 20` Bash call, `/api/overview` shows the lead's `agents[0].tool == "Bash: sleep 20"` and the page line (read via the page text or the rendered DOM) shows it; during an AskUserQuestion, `needs_you[0].reason` starts with `question: `. The record quotes both API excerpts and the status file.
- [ ] Real-state, read-only: a worktree board on `:7711` against the user's default tmux server (`TC_OVERSEER=0 TC_NOTIFY=0`, own temp `TMUX_DASH_STATE`), and the live board `:7700`: a script diffs the key paths of both `/api/overview` responses; every key path of the live one exists in the new one with the same JSON type; the only new paths are `agents…`, `needs_you[].reason`, alert `fail_streak`/`turn_s`. Recorded with the counts of paths checked (> 0) and of projects (> 1, the user's real sessions).
- [ ] The captured fixture test passes; no real session id, pane id or home path remains in committed files (`grep` count 0, printed with the number of files checked).
- [ ] Every process the run started (scratch tmux server, test boards, the scratch lead) is killed and checked gone with `ps`.

**Verify:** `python3 -m unittest board.tests.test_overview 2>&1 | tail -3` → `OK`

**Steps:** the run record lists each command run and its output. The scratch lead is started and driven as the shared context's "How to run" entries describe (send-keys text, wait 1 s, separate Enter; AskUserQuestion answered with one Enter). Commit `test(board): mod overview real run and fixture`.

```json:metadata
{"files": ["tools/tests/e2e-mod-overview.md", "board/tests/fixtures/agent-status/real-new-fields.json", "board/tests/test_overview.py"], "verifyCommand": "python3 -m unittest board.tests.test_overview 2>&1 | tail -3", "acceptanceCriteria": ["scratch lead: agents tool Bash: sleep 20 in API and page during the call", "needs_you reason question: during AskUserQuestion", "live :7700 vs worktree board key-path diff: only additions, counts recorded", "captured fixture test passes; leak grep 0 with files counted", "all started processes killed and checked"], "modelTier": "standard"}
```
