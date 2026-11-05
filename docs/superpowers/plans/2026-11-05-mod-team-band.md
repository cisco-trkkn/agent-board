# Mod team band Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dev lead's terminal shows one line above the prompt naming the teammates that need the user, and counts of the busy, ready and unknown ones.

**Architecture:** A second Claude Code mod, `claude/plugin/mods/team-band.js`, in the agent-board plugin. At `session.start` it checks whether it runs in the lead (tmux window `claude`). Only there does it start two timers: one lists the lead session's panes (10 s), the other reads the `agent-status/*.json` files the agent-status mod writes (2 s). A pure function `bandLine` builds the line, and a `ui.render` hook on `AbovePrompt` draws it.

**Tech Stack:** Claude Code mods (JS module, `claude plugin test` TypeScript tests, `claude-code/testing` kit), tmux, zsh.

**Spec:** `docs/superpowers/specs/2026-11-05-mod-team-band-design.md`

## Global Constraints

- The state dir rule is the agent-status mod's: `$TC_STATE`, else (`$TMPDIR` minus a trailing `/`, default `/tmp`) + `/tmux-ctl-<uid>`, then `/agent-status`. It is copied from `agent-status.js` `stateDir` (same expression).
- Line format, exactly: needs-you first, as `Needs you: <window name>[, <window name>…]`, then `busy N`, `ready N`, `? N` in that order, joined by ` · `. Zero counts are left out. Examples: `Needs you: ✦ qrev · busy 2 · ready 1`, `busy 2 · ready 1`, `? 1`. An empty line draws no band (the hook returns `next(e)`).
- Staleness: a file whose `updatedAt` (epoch seconds) is more than 45 s before `$.clock.now()` counts as `?`, never as ready. A state other than `ready`/`busy`/`needs-you` also counts as `?`.
- Only the lead draws: `tmux display -p -t $TMUX_PANE '#{window_name}\t#{session_name}'`, run once at `session.start`, must print window name `claude`. With `TMUX_PANE` unset, or tmux failing, the mod starts no timers, runs no further tmux, and draws nothing.
- The lead's own pane (`$TMUX_PANE`) is never counted.
- Errors (tmux missing, the dir unreadable, a bad JSON file) never throw out of a hook or timer. A failed poll leaves the last good line in place. A single unreadable file is skipped and the other files still count.
- `claude plugin validate` rules: `$.env.get` takes literal names only, and `on()` takes literal event names. A module-level helper may take `$` as a parameter, as `flush` does in `agent-status.js`.
- `claude plugin test` loads every mod of the plugin in every test file. Both test files stub every API call either mod makes, and `agent-status.test.ts` stays green unchanged.
- User rule: run only the targeted tests: `claude plugin test claude/plugin` and `zsh tools/tests/test_plugin.zsh`. Never run the full board or tools suites.

**User decisions (already made):** Queue item 3. Integration is merge to `main` locally with no push (`metadata.queue`, 2026-11-05T06:05:39Z).

**Rulings (lead, for gaps in the spec):**
- Ruling: a pane counts as an agent when a status file names it, or when its window name starts with `✦ `. A `✦ ` window with no file counts as `?`, which is the spec's "file missing". Any other window with no file (`tasks`, a user shell) is not counted. Otherwise the `tasks` window would always show `? 1`.
- Ruling: when several files name one pane (left behind by a `/clear` race), the one with the largest `updatedAt` wins.
- Ruling: files are named by window name. Window names keep tmux's order (`list-panes -s` order), and needs-you names are joined with `, `.
- Ruling: the band keeps what later mods draw. The hook returns a `Box` (column) holding our `Text` and then `await next(e)` when that is truthy, or our `Text` alone when it is not.
- Ruling: after a poll changes the line, the mod calls `$.ui.invalidate('ui.render')`. It uses no `$.state`, which would need a manifest declaration.

---

### Task 1: team-band mod, its tests, and its registration

**Goal:** `team-band.js` builds and draws the band in the lead only, is registered in `hooks.json` and the manifest, and is covered by `claude plugin test` and `test_plugin.zsh`.

**Files:**
- Create: `claude/plugin/mods/team-band.js`
- Create: `claude/plugin/mods/team-band.test.ts`
- Modify: `claude/plugin/hooks/hooks.json` (`"modules": ["../mods/agent-status.js", "../mods/team-band.js"]`)
- Modify: `claude/plugin/.claude-plugin/plugin.json` (description: after "the agent-status mod (session state from events, read by the board)", add ", the team-band mod (who needs you, above the lead's prompt)")
- Modify: `tools/tests/test_plugin.zsh:30-36` (modules check expects both entries and checks each file exists; add a check that the description names `team-band`)

**Acceptance Criteria:**
- [ ] `bandLine` cases each tested RED then GREEN: needs-you first with names, the exact separator format, zero counts left out, stale file → `?`, `✦` window with no file → `?`, a non-`✦` window with no file left out, own pane left out, the freshest of two files for one pane wins, a file for a pane not in the session left out, nothing → empty string.
- [ ] Mount tests: `$.ui.mount` of `AbovePrompt` in a lead finds `Text` `Needs you: ✦ qrev · busy 1` from fixture files. With no agents it finds no such text, and the stubbed `ui.render` below it is what is drawn. A non-lead session (window `✦ qrev`) draws nothing, and its `process.run` log holds the one `display` call and no `list-panes`.
- [ ] Error tests: `fs.list` denied after one good poll keeps the last line, one unparsable file is skipped while the others count, and a failing `tmux` (exitCode 1) at start leaves no band and no timers.
- [ ] Each guard test names its mutation in a comment, and the implementer's RED run shows that mutation failing it.
- [ ] `claude plugin test claude/plugin` exits 0, with the agent-status tests unchanged and passing.
- [ ] `zsh tools/tests/test_plugin.zsh` ends ALL PASS, and `claude plugin validate claude/plugin` reports no error.

**Verify:** `claude plugin test claude/plugin; echo rc=$?` → `rc=0`

**Steps:**

- [ ] **Step 1: Write the tests first** (`team-band.test.ts`). The world stubs everything both mods call. For agent-status: `session.id`, `settings.read`, `fs.write`, `process.run` (`id`, `mv`, `rm`), and the engine events. For team-band: `process.run` for `tmux display` / `tmux list-panes`, plus `fs.list` and `fs.read` over an in-memory dir. Copy the shape of `world()` in `agent-status.test.ts`, with these differences: `fs.list` answers from the in-memory map for the dir `/s/agent-status` and is denied when `w.failList` is set, `fs.read` returns the map entry, and `process.run` answers `tmux` from `w.window` / `w.panes` (exitCode 1 when `w.tmuxFail`). Mount props for the band:

```typescript
const BAND = {
  plugin: 'agent-board', component: 'AbovePrompt', viewport: { columns: 120, rows: 30 },
  props: { hasSurvey: false, isWorking: false, maxRows: 4, bodyColumns: 120, scroll: { offset: 0, bodyRows: 4 }, view: {} },
} as const
// stub for what is drawn below this mod
on('ui.render', () => ({ type: 'Text', props: {}, children: ['below'] }))
```

Test `bandLine` directly by importing it (`import { bandLine } from './team-band.js'`). Test the timers with `mock.clock` and `clock.advance(2000)` / `clock.settle()`, as the agent-status heartbeat tests do. Mutations to name, for example: "drop the `f.pane === own` skip → `own pane is left out` fails", "treat stale as ready → `stale file counts as ?` fails", "start timers before the lead check → `non-lead runs no list-panes` fails", "reset `line` on a failed poll → `failed poll keeps the last line` fails".

- [ ] **Step 2: Run them and see them fail**

Run: `claude plugin test claude/plugin; echo rc=$?`
Expected: the team-band tests FAIL (module missing / not registered), and the agent-status tests pass.

- [ ] **Step 3: Write the mod.** Core function (export it for the tests):

```javascript
// panes: Map pane_id -> window name, in tmux order; files: parsed status objects; own: the lead's pane; now: epoch s
export function bandLine(panes, files, own, now) {
  const best = new Map()
  for (const f of files) {
    if (!f || typeof f.pane !== 'string' || f.pane === own || !panes.has(f.pane)) continue
    const b = best.get(f.pane)
    if (!b || (Number(f.updatedAt) || 0) > (Number(b.updatedAt) || 0)) best.set(f.pane, f)
  }
  const need = []
  let busy = 0, ready = 0, unknown = 0
  for (const [id, name] of panes) {
    if (id === own) continue
    const f = best.get(id)
    if (!f) { if (name.startsWith('✦ ')) unknown++; continue }
    const age = now - (Number(f.updatedAt) || 0)
    if (age > STALE_S) unknown++
    else if (f.state === 'needs-you') need.push(name)
    else if (f.state === 'busy') busy++
    else if (f.state === 'ready') ready++
    else unknown++
  }
  const parts = []
  if (busy) parts.push('busy ' + busy)
  if (ready) parts.push('ready ' + ready)
  if (unknown) parts.push('? ' + unknown)
  if (need.length) parts.unshift('Needs you: ' + need.join(', '))
  return parts.join(' · ')
}
```

The rest of the module: `STALE_S = 45`, `POLL_MS = 2000`, `PANES_MS = 10000`, and `stateDir` (same expression as agent-status). In `session.start`, read `TMUX_PANE`, `TC_STATE` and `TMPDIR` with literal `$.env.get` calls. Run `['tmux', 'display', '-p', '-t', pane, '#{window_name}\t#{session_name}']`, and continue only when it exits 0 and the window name is `claude`. Then run `['id', '-u']` only when `TC_STATE` is unset. Load the panes once (`['tmux', 'list-panes', '-s', '-t', session, '-F', '#{pane_id} #{window_name}']`, each line split at its first space) and poll once. Then start `$.clock.every(PANES_MS, …)` and `$.clock.every(POLL_MS, …)`. A poll runs `$.fs.list(dir)`, keeps `kind === 'file'` names ending in `.json`, reads and `JSON.parse`s each one (skipping a file that throws), and computes `bandLine` with `secs(await $.clock.now())`. If the line changed it stores it and calls `$.ui.invalidate('ui.render')`. A poll that throws before `bandLine` keeps the old line. Cancel both timers on a `session.end` whose reason is not `clear`/`resume`. Then the `ui.render` hook, filtered on `{ component: 'AbovePrompt' }`, follows the band ruling above. Wrap every hook and timer body in try/catch, as `agent-status.js` does.

- [ ] **Step 4: Register it.** Update `hooks.json` `modules` and `plugin.json` `description` as in Files. In `test_plugin.zsh`, change the modules assertion to `["../mods/agent-status.js", "../mods/team-band.js"]` with an `isfile` check per entry, and add:

```zsh
check "plugin.json description names team-band" zsh -c 'python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\"description\"])" "$1" | grep -qF team-band' _ "$P/.claude-plugin/plugin.json"
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `claude plugin test claude/plugin; echo rc=$?` → `rc=0`; `claude plugin validate claude/plugin`; `zsh tools/tests/test_plugin.zsh; echo rc=$?` → ALL PASS, `rc=0`.

- [ ] **Step 6: Commit** only your paths (`git add claude/plugin/mods/team-band.js claude/plugin/mods/team-band.test.ts claude/plugin/hooks/hooks.json claude/plugin/.claude-plugin/plugin.json tools/tests/test_plugin.zsh`), with the message `feat(plugin): team-band mod shows who needs you above the lead's prompt`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/plugin/mods/team-band.js", "claude/plugin/mods/team-band.test.ts", "claude/plugin/hooks/hooks.json", "claude/plugin/.claude-plugin/plugin.json", "tools/tests/test_plugin.zsh"], "verifyCommand": "claude plugin test claude/plugin; echo rc=$?", "acceptanceCriteria": ["bandLine cases RED then GREEN", "mount tests: lead draws line, empty draws only below, non-lead draws nothing and runs no list-panes", "error tests: failed list keeps line, bad file skipped, failing tmux no band", "guard tests name mutations", "claude plugin test rc=0 with agent-status tests unchanged", "test_plugin.zsh ALL PASS, plugin validate clean"], "modelTier": "standard"}
```

### Task 2: Real run in a scratch tmux server

**Goal:** A real Claude Code lead in a scratch tmux server draws the band from real files: the needs-you name, the `?` count for a stale and an aged fixture, an update on a state change, and no band when no agents are left. All of it is recorded with raw output in `tools/tests/e2e-team-band.md`.

**Files:**
- Create: `tools/tests/e2e-team-band.md`

**Acceptance Criteria:**
- [ ] Setup uses `~/.local/bin/tmux -L team-band-e2e -f /dev/null`, and `set-environment -g TC_STATE <tmp>` before any claude starts. The lead runs in a window named `claude`: `TC_STATE=$TMP claude --model haiku --settings $WT/claude/session-settings.json --plugin-dir $WT/claude/plugin`.
- [ ] The aged and multi-agent fixture: window `✦ qrev` (`sleep 9999`) with a file saying `needs-you` refreshed every 10 s; window `✦ old` with a file whose `updatedAt` is yesterday (now − 90000); a file for a pane id not in the session; a leftover `x.json.tmp`; and the lead's own real file. The pane capture of the lead shows `Needs you: ✦ qrev · ? 1`.
- [ ] The `✦ qrev` file is switched to `busy`, and within 6 s the capture shows `busy 1 · ? 1` with no `Needs you`.
- [ ] Both `✦` windows are killed and the fixtures removed, and within 12 s the capture shows no band line. A non-lead check: a second claude started in window `✦ peer` with the same flags draws no band, read from its own capture.
- [ ] Every result is the raw output pasted under the command that produced it (not retyped into a table). `claude --version` is recorded. The scratch server is killed at the end (`tmux -L team-band-e2e kill-server`, then `ps` shows no `sleep 9999`).
- [ ] If the band never appears, the doc says so with the captures and the mod's skip line (`claude --debug` or its log), and the task reports BLOCKED. It is not worked around.

**Verify:** `grep -c '^## ' tools/tests/e2e-team-band.md` → at least 4

**Steps:**

- [ ] **Step 1:** Set up as in `tools/tests/e2e-agent-status.md` §Setup (same `T()` helper, with socket `team-band-e2e`). Send prompts with `send-keys "text"`, `sleep 1`, then a separate `send-keys Enter`. Find the panes with `T list-panes -a -F '#{pane_id} #{window_name}'`. Write fixture files with `python3 -c` (JSON with `session_id`, `pane`, `state`, `since`, `updatedAt`), and refresh the `✦ qrev` one in a background loop whose PID is saved and killed at the end.
- [ ] **Step 2:** Capture with `T capture-pane -p -t <lead pane> | grep -v '^$' | tail -12` for each step in the Acceptance Criteria, waiting the stated times.
- [ ] **Step 3:** Write the doc with sections `## Setup`, `## Band with needs-you`, `## State change`, `## No agents and non-lead`, `## Cleanup`, and commit it alone (`git add tools/tests/e2e-team-band.md`), with the message `test(plugin): team-band real run`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["tools/tests/e2e-team-band.md"], "verifyCommand": "grep -c '^## ' tools/tests/e2e-team-band.md", "acceptanceCriteria": ["scratch server -f /dev/null, TC_STATE set before claude, lead window claude", "aged multi-agent fixture: capture shows Needs you: ✦ qrev · ? 1", "busy switch shows busy 1 · ? 1 within 6 s", "no agents: no band within 12 s; non-lead peer draws no band", "raw output under each command; claude --version; server killed", "BLOCKED with evidence if band never draws"], "modelTier": "standard"}
```
