# Mod usage gauges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each session shows its own plan limits, context fill and cost in one status line under the prompt, read from its statusLine tap file.

**Architecture:** First, `claude/plugin/mods/index.js` becomes the single owner of `session.start` and `session.end`, and calls each mod's exported `start`/`end` in turn, each inside its own try/catch (ruling I-2 from spec 3's final review). Then a third mod, `usage-gauges.js`, exports `start`/`end` plus a pure `gaugeLine`. Every 10 s it reads `<state dir>/statusline/<own session id>.json` and calls `$.ui.status`.

**Tech Stack:** Claude Code mods (JS, `claude plugin test` with `claude-code/testing`), the statusLine tap (`claude/statusline/agent-board-statusline`), tmux for the real run.

**Spec:** `docs/superpowers/specs/2026-11-05-mod-usage-gauges-design.md`

## Global Constraints

- Claude Code loads one hooks module per plugin: `hooks.json` keeps `"modules": ["../mods/index.js"]`, and every mod is wired through `index.js`.
- After Task 1, only `index.js` registers `session.start` and `session.end`. No mod registers them, and no catch-all matcher (`{surface:/.*/}`, `{reason:/.*/}`) remains. Each mod's other hooks stay registered by its own `register(on)`.
- `index.js` calls the mods in this order: agent-status, team-band, usage-gauges. A throw in one mod's `start`/`end` is caught and the next mod still runs; the hook then returns `next(e)`.
- The state dir rule is the agent-status one: `$TC_STATE`, else (`$TMPDIR` minus a trailing `/`, default `/tmp`) + `/tmux-ctl-<uid>`. The tap file is `<state dir>/statusline/<session_id>.json`.
- Field paths, pinned from a real tap file (Claude Code 2.1.318, read 2026-11-05): `rate_limits.five_hour.used_percentage`, `rate_limits.seven_day.used_percentage`, `context_window.used_percentage`, `cost.total_cost_usd`, and `received_at` (epoch seconds, float). Percentages are integers in the payload.
- The line, exactly: `5h <n>% · 7d <n>% · ctx <n>% · $<cost with 2 decimals>`, in that order, joined by ` · `. Percentages are rounded with `Math.round`. A part whose value is missing or not a finite number is left out.
- Clear the line when there is no file, the JSON is unreadable, every part is missing, `received_at` is more than 300 s before `$.clock.now()`, or the file's `session_id` differs from the session's own id. Clearing means `$.ui.status('')`, which Task 3 verifies in a real session. The mod calls `$.ui.status` only when the text changes.
- The mod reads only the file named after `await $.session.id()`, read at each poll, so after a `/clear` it follows the new id.
- Errors never throw out of a hook or a timer.
- `claude plugin validate`: literal `$.env.get` names and literal `on()` event names.
- User rule: run only the targeted tests (`claude plugin test claude/plugin`, `claude plugin validate claude/plugin`, `zsh tools/tests/test_plugin.zsh`). Never run the full suites.

**User decisions (already made):** Queue item 4: merge to `main` locally, no push (`metadata.queue`, 2026-11-05T06:05:39Z). Spec 3's final-review ruling I-2: `index.js` owns `session.start`/`session.end` (ledger `docs/superpowers/ledgers/2026-11-05-mod-team-band/progress.md`).

**Rulings (lead):**
- Ruling: the spec's Files list says "add the module" to `hooks.json`. That is impossible (one module per plugin), so the module is wired through `index.js` instead.
- Ruling: `$.ui.status` prefixes the mod name (`⚠ agent-board: …`). The spec's line is the text after that prefix, and the prefix is accepted.

---

### Task 1: index.js owns session.start and session.end

**Goal:** `index.js` registers the plugin's only `session.start` and `session.end`, and calls each mod's exported `start($, e)` / `end($, e)` in order with per-mod try/catch. agent-status and team-band move their lifecycle code into those exports, with behaviour unchanged.

**Files:**
- Modify: `claude/plugin/mods/index.js`
- Modify: `claude/plugin/mods/agent-status.js` (its `session.start` and `session.end` handler bodies become `export async function start($, e)` / `end($, e)`, without `next`)
- Modify: `claude/plugin/mods/team-band.js` (the same; remove both catch-all matchers)
- Create: `claude/plugin/mods/index.test.ts`
- Modify: `claude/plugin/mods/agent-status.test.ts`, `claude/plugin/mods/team-band.test.ts`, only where a test names the removed matchers or registration (state any change in the report)

**Acceptance Criteria:**
- [ ] `grep -c "on('session\.\(start\|end\)'" claude/plugin/mods/*.js` totals 2, both in `index.js`, and `grep -c 'surface: /\.\*/\|reason: /\.\*/' claude/plugin/mods/*.js` totals 0.
- [ ] `index.js` exports a helper `runAll(mods, fn, $, e)` that calls `m[fn]($, e)` for each mod that has it, in order, catching each throw. `index.test.ts` tests it directly with fake mods: order kept, a throwing first mod doesn't stop the second, a mod without the export is skipped. Mutation: drop the per-mod try/catch → "a throwing mod does not stop the next" fails.
- [ ] Every existing agent-status and team-band test still passes, with any edits listed in the report: `claude plugin test claude/plugin` exits 0 with at least 56 + the new index tests passing.
- [ ] `claude plugin validate claude/plugin` passes, and `zsh tools/tests/test_plugin.zsh` ends ALL PASS.

**Verify:** `claude plugin test claude/plugin; echo rc=$?` → `rc=0`

**Steps:**

- [ ] **Step 1:** Write `index.test.ts` for `runAll` (RED: `runAll` not exported). Shape:

```typescript
import { expect, test } from 'claude-code/testing'
import { runAll } from './index.js'
test('a throwing mod does not stop the next', async () => {
  const seen: string[] = []
  const a = { start: async () => { seen.push('a'); throw new Error('boom') } }
  const b = { start: async () => { seen.push('b') } }
  await runAll([a, b], 'start', {} as any, {} as any)
  expect(seen).toEqual(['a', 'b'])
})
```

Add "order kept" and "a mod without the export is skipped" in the same style.
- [ ] **Step 2:** Run `claude plugin test claude/plugin; echo rc=$?` and see the new tests fail.
- [ ] **Step 3:** Implement:

```javascript
import * as agentStatus from './agent-status.js'
import * as teamBand from './team-band.js'

const MODS = [agentStatus, teamBand]

export async function runAll(mods, fn, $, e) {
  for (const m of mods) {
    if (typeof m[fn] !== 'function') continue
    try { await m[fn]($, e) } catch (x) { /* one mod never stops another */ }
  }
}

export function register(on) {
  on('session.start', async ($, e, next) => { await runAll(MODS, 'start', $, e); return next(e) })
  on('session.end', async ($, e, next) => { await runAll(MODS, 'end', $, e); return next(e) })
  for (const m of MODS) m.register(on)
}
```

In `agent-status.js` and `team-band.js`, move each `session.start` / `session.end` handler body into `export async function start($, e)` / `export async function end($, e)`, keep its try/catch, drop the `return next(e)`, and delete the two `on(...)` calls. Before you rely on it, check one behaviour difference: agent-status's `session.end` body awaited `st.q` before `next(e)`, and `runAll` awaits each `end`, so the order is kept. State that check in the report.
- [ ] **Step 4:** Run the verify command, `claude plugin validate claude/plugin`, `zsh tools/tests/test_plugin.zsh; echo rc=$?`, and the two greps from the Acceptance Criteria. Run the mutation (remove the try/catch in `runAll`) and paste its failing output.
- [ ] **Step 5:** Commit only your paths: `refactor(plugin): index.js owns session.start and session.end for every mod`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/plugin/mods/index.js", "claude/plugin/mods/agent-status.js", "claude/plugin/mods/team-band.js", "claude/plugin/mods/index.test.ts", "claude/plugin/mods/agent-status.test.ts", "claude/plugin/mods/team-band.test.ts"], "verifyCommand": "claude plugin test claude/plugin; echo rc=$?", "acceptanceCriteria": ["only index.js registers session.start/end; no catch-all matchers", "runAll tested: order, throw isolation (mutation named), missing export skipped", "existing tests pass, edits listed; rc=0", "validate passes; test_plugin ALL PASS"], "modelTier": "standard"}
```

### Task 2: usage-gauges mod

**Goal:** `usage-gauges.js` shows `5h <n>% · 7d <n>% · ctx <n>% · $<x.xx>` from the session's own tap file through `$.ui.status`, and clears it when the data is missing, stale or not its own. It is wired through `index.js`.

**Files:**
- Create: `claude/plugin/mods/usage-gauges.js`
- Create: `claude/plugin/mods/usage-gauges.test.ts`
- Create: `claude/plugin/mods/fixtures/statusline-tap.json` (copied from a real tap file, see Step 1)
- Modify: `claude/plugin/mods/index.js` (add `usageGauges` last to `MODS`)
- Modify: `claude/plugin/.claude-plugin/plugin.json` (description: add ", the usage-gauges mod (plan limits, context and cost under the prompt)")
- Modify: `tools/tests/test_plugin.zsh` (index.js imports `./usage-gauges.js`, the file exists, and the description names `usage-gauges`)

**Acceptance Criteria:**
- [ ] The fixture is a real tap file: `cp` of the newest `$TMPDIR/tmux-ctl-$(id -u)/statusline/*.json`. Then replace with fixed dummies: `session_id`, `transcript_path`, `cwd`, `scratchpad_dir`, `prompt_id`, `session_name`, every `workspace.*` path and the repo owner and name. The values the mod reads are kept. The report pastes the `cp` command and a `diff` of key paths (`python3` walk) between the real file and the fixture, showing only the replaced keys differ.
- [ ] `gaugeLine(payload)` tests, each RED then GREEN: the full line from the fixture (assert against the fixture's own values); each part left out when missing (one test per part); a non-number value is left out; all missing → `''`; `$` uses 2 decimals (`5.4901` → `$5.49`); `Math.round` (`61.5` → `62%`).
- [ ] Timer tests (`mock.clock`): a status with the line after the first 10 s poll; no `ui.status` call when the line has not changed; `''` when the file is missing, older than 300 s, has another `session_id`, or doesn't parse; a session id change (stub `session.id` answers a new id) reads the new file; `fs.read` denied → no throw and the line is cleared. Each guard test names its mutation (e.g. "drop the session_id check → `another session's file clears the line` fails"), and the RED run shows it failing.
- [ ] `claude plugin test claude/plugin` exits 0, with every earlier test passing. `claude plugin validate claude/plugin` passes. `zsh tools/tests/test_plugin.zsh` ends ALL PASS.

**Verify:** `claude plugin test claude/plugin; echo rc=$?` → `rc=0`

**Steps:**

- [ ] **Step 1:** Make the fixture: `mkdir -p claude/plugin/mods/fixtures && cp "$(ls -t $TMPDIR/tmux-ctl-$(id -u)/statusline/*.json | head -1)" <your scratchpad>/real.json`, then write the fixture with the identifiers replaced, using `python3` (never by hand), and paste the key-path diff.
- [ ] **Step 2:** Write `usage-gauges.test.ts` (import the fixture JSON with `import tap from './fixtures/statusline-tap.json'` if the kit allows it; otherwise read it with `$.fs.read` stubbed from an inline copy, and say which in the report). Stub `ui.status` and record `e.text`. The world also stubs every call agent-status and team-band make (copy `world()` from `team-band.test.ts`), so all three mods load.
- [ ] **Step 3:** Run `claude plugin test claude/plugin; echo rc=$?`. RED: the module is missing.
- [ ] **Step 4:** Implement:

```javascript
const POLL_MS = 10000
const STALE_S = 300
const pct = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v) + '%' : null)

export function gaugeLine(p) {
  if (!p || typeof p !== 'object') return ''
  const rl = p.rate_limits || {}
  const cost = p.cost && p.cost.total_cost_usd
  const parts = [
    pct(rl.five_hour && rl.five_hour.used_percentage) && '5h ' + pct(rl.five_hour.used_percentage),
    pct(rl.seven_day && rl.seven_day.used_percentage) && '7d ' + pct(rl.seven_day.used_percentage),
    pct(p.context_window && p.context_window.used_percentage) && 'ctx ' + pct(p.context_window.used_percentage),
    typeof cost === 'number' && Number.isFinite(cost) ? '$' + cost.toFixed(2) : null,
  ]
  return parts.filter(Boolean).join(' · ')
}
```

`start($, e)` resolves the state dir (literal `$.env.get('TC_STATE')`, `$.env.get('TMPDIR')`, and `id -u` only when `TC_STATE` is unset), then starts `$.clock.every(POLL_MS, poll)`. `poll` reads `sid = await $.session.id()`, then `$.fs.read(dir + '/statusline/' + sid + '.json')`, and parses it. Its text is `''` on any failure, on `p.session_id !== sid`, or on `secs(now) - p.received_at > STALE_S`. Otherwise the text is `gaugeLine(p)`. It calls `$.ui.status(text)` only when the text differs from the last one shown. `end($, e)` cancels the timer only when `e.reason` is neither `clear` nor `resume`. Add `usageGauges` last to `MODS` in `index.js`. Then update the manifest and `test_plugin.zsh` as in Files.
- [ ] **Step 5:** Run the verify command, validate and `test_plugin.zsh`, then each mutation. Paste the raw outputs into the report.
- [ ] **Step 6:** Commit only your paths: `feat(plugin): usage-gauges mod shows plan limits, context and cost under the prompt`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/plugin/mods/usage-gauges.js", "claude/plugin/mods/usage-gauges.test.ts", "claude/plugin/mods/fixtures/statusline-tap.json", "claude/plugin/mods/index.js", "claude/plugin/.claude-plugin/plugin.json", "tools/tests/test_plugin.zsh"], "verifyCommand": "claude plugin test claude/plugin; echo rc=$?", "acceptanceCriteria": ["fixture copied from a real tap file, identifiers replaced, key-path diff shown", "gaugeLine cases RED then GREEN", "timer tests: change-only status, clear on missing/stale/foreign/unparsable, follows new session id, fs.read denied no throw; mutations named", "plugin test rc=0, validate passes, test_plugin ALL PASS"], "modelTier": "standard"}
```

### Task 3: Real run with the statusLine tap

**Goal:** A real Claude Code session in a scratch tmux server, with the statusLine tap writing to a temp `TC_STATE`, shows the gauge line under its prompt. A stale or foreign file clears the line. Everything is recorded with raw output in `tools/tests/e2e-usage-gauges.md`.

**Files:**
- Create: `tools/tests/e2e-usage-gauges.md`

**Acceptance Criteria:**
- [ ] Setup: `~/.local/bin/tmux -L usage-gauges-e2e -f /dev/null`, `set-environment -g TC_STATE $TMP` before any claude, and `WT=$(git rev-parse --show-toplevel)`. The session is `TC_STATE=$TMP claude --model haiku --settings $WT/claude/session-settings.json --plugin-dir $WT/claude/plugin`, with the user's own statusLine setting (the tap) in effect. Show `ls $TMP/statusline/` naming the session's own file.
- [ ] After one turn (a short prompt, no tools), a full `capture-pane -p` shows `5h <n>% · 7d <n>% · ctx <n>% · $<x.xx>` (or the parts the tap file holds), and `cat` of the tap file shows the same numbers.
- [ ] Real-state check: in the same scratch `$TMP/statusline/`, put a copy of an older real tap file from the user's live dir (read-only copy) under a second session's name. The capture still shows only the session's own numbers. Then set the own file's `received_at` to now − 400 (the tap rewrites it on the next statusLine refresh, so do it between refreshes, or stop the refresh by staying idle) and show the line cleared within 12 s: the full capture plus `grep -c '5h \|ctx '` = 0. Record whether `$.ui.status('')` leaves an empty `⚠ agent-board:` prefix. If it does, report DONE_WITH_CONCERNS with the capture.
- [ ] Raw output under each literal `$ cmd` line, with no hand edits. `claude --version` is recorded. At the end the scratch server is killed and `ps` shows no scratch claude.
- [ ] If the line never shows, record the captures and `claude --debug` output, and report BLOCKED. Do not work around it.

**Verify:** `grep -c '^## ' tools/tests/e2e-usage-gauges.md` → at least 4

**Steps:**

- [ ] **Step 1:** Set up as in `tools/tests/e2e-team-band.md` §Setup (its `T()` helper, with socket `usage-gauges-e2e`). Send prompts with `send-keys "text"`, `sleep 1`, then a separate `send-keys Enter`.
- [ ] **Step 2:** Capture each step in the Acceptance Criteria, with full captures and counts.
- [ ] **Step 3:** Write the doc with sections `## Setup`, `## Gauge line`, `## Foreign and stale files`, `## Cleanup`, and commit it alone: `test(plugin): usage-gauges real run`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["tools/tests/e2e-usage-gauges.md"], "verifyCommand": "grep -c '^## ' tools/tests/e2e-usage-gauges.md", "acceptanceCriteria": ["scratch server -f /dev/null, TC_STATE before claude, own tap file listed", "capture shows gauge line matching the tap file", "foreign real tap copy ignored; stale own file clears within 12 s (full capture + count 0); empty-prefix behaviour recorded", "raw output, claude --version, server killed", "BLOCKED with evidence if the line never shows"], "modelTier": "standard"}
```
