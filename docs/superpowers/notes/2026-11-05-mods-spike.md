# Mods spike: where mods load (2026-11-05, Claude Code 2.1.318)

Spike mod: `claude/plugin/mods/agent-status.js` (session.start writes `{session_id, pane, env_ok}` to
`<state dir>/agent-status/<session_id>.json`, plus probe files in `<state dir>/agent-status-probe/`).
Every run: scratch tmux server `-L mods-spike -f /dev/null`, `TC_STATE` = a temp dir, model haiku, one trivial prompt,
launched with `--settings <wt>/claude/session-settings.json --plugin-dir <wt>/claude/plugin`.

## Verdict

The mod loads in all five contexts. The spec stands. Two spec details need changing (see "Findings for Task 2").

## Contexts

| Context | Loaded | Evidence | TMUX_PANE seen |
| :- | :- | :- | :- |
| (a) interactive, launched like the dev lead | yes | `$TC_STATE/agent-status/2354629a-17dd-45ea-9171-0385fab16158.json` = `{"session_id":"2354629a-…","pane":"%0","env_ok":true}`; probes for session.start, turn.start, turn.complete also written | `%0` |
| (b) like a `tmux-ctl agent` worker (`-w spikeworker -n spikeworker`) | yes | `$TC_STATE/agent-status/8a9cce35-07f9-4637-b79d-8cb4e1bb732a.json` = `{…,"pane":"%0","env_ok":true}`; same probes | `%0` |
| (c) teammate spawned by an interactive lead (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) | yes, as its own session | The teammate opened as a split pane `%1` of the same scratch tmux server (separate process: `--agent-id probe@session-22cf1a73 --parent-session-id 22cf1a73-… --plugin-dir <wt>/claude/plugin`). It wrote its own file `6a0a488b-42ab-42be-aedb-3605407b4a2f.json` = `{…,"pane":"%1","env_ok":true}`; the lead wrote `22cf1a73-….json` with pane `%0`. **The teammate's file went to `${TMPDIR}tmux-ctl-503/agent-status/`, not the temp `TC_STATE`**: the teammate pane inherits the tmux server's environment, and `TC_STATE` was set only on the lead's command line (probe: `tcState: null`). I copied those two stray dirs to the scratchpad and deleted them from the live state dir. | `%1` |
| (d) `claude --bg` (prints `backgrounded · b8fc4fd1`; stopped with `claude stop b8fc4fd1`) | yes | `$TC_STATE/agent-status/b8fc4fd1-ebb9-4c3c-9c5c-d361bc085a61.json` = `{…,"pane":null,"env_ok":false}`. `TC_STATE` from the launching shell did reach the session (probe `tcState` matched). | none (`null`: the background service has no tmux pane) |
| (e) `claude -p 'reply ok'` (output `ok`, rc=0) | yes | `$TC_STATE/agent-status/b7ca4892-bd98-45c0-b246-b08cb35cbdf5.json` = `{…,"pane":"%0","env_ok":true}`; session.start, turn.start, turn.complete and session.end probes all written, so `session.end` fires in -p | `%0` (run inside a tmux pane) |

## hooks.json: `modules` beside `hooks`

- Works. `claude/plugin/hooks/hooks.json` now holds `"modules": ["../mods/agent-status.js"]` as a top-level key before the unchanged `"hooks"` object.
- **The path is relative to `hooks/hooks.json`**, so `"./mods/agent-status.js"` fails validation (`hooks/mods/agent-status.js: no such file`); the file living at `claude/plugin/mods/` needs `../mods/…`.
- A classic hook still fires beside the mod: in run (b) the plugin's SessionStart hook `context-inject.sh` injected a marker from a temp `TC_CONTEXT_DIR` (`spike.md` containing `SPIKE-CTX-MARKER`; the marker appears 3 times in that session's transcript), and the mod's file also appeared.
- `claude plugin validate claude/plugin` (rc 0, "Validation passed with warnings"); hooks part verbatim:

    Validating hooks: /Users/francisco.ruiz/agent-board/.claude/worktrees/mod-agent-status/claude/plugin/hooks/hooks.json
    
      ❯ ../mods/agent-status.js hooks: session.start, turn.start, turn.complete, tool.check, tool.call, session.end
      ❯ ../mods/agent-status.js gating hook without .catch: tool.check
      ❯ ../mods/agent-status.js gating hook without .catch: tool.call
      ❯ ../mods/agent-status.js calls: $.env.get, $.fs.write, $.process.run, $.session.id
      ❯ ../mods/agent-status.js env writes: nothing
      ❯ ../mods/agent-status.js env reads: TC_STATE, TMPDIR, TMUX_PANE
    

  The manifest warns `author: No author information provided`; the directory-profile checks (LICENSE, icon) do not affect the result.

## API facts for the real mod

| Need | Fact | Source |
| :- | :- | :- |
| Env vars | `await $.env.get('TMUX_PANE')`, also `'TC_STATE'`, `'TMPDIR'`. The validator **rejects a non-literal name** (`$.env.get takes a literal name as its first argument`). An unset variable gives `undefined`/`null` (probe: `tcState: null`). `TMPDIR` on this Mac is `/var/folders/…/T/` with a trailing slash: strip it. | probe output; validate error; reference "$.env" |
| uid | `(await $.process.run(['id', '-u'])).stdout.trim()` → `'503'` (no env var for it) | probe |
| State dir | `TC_STATE` else `$TMPDIR` (trailing `/` stripped, default `/tmp`) + `/tmux-ctl-<uid>`: same as `tc_env.state_dir()` | probe: dir built this way was written |
| `$.fs` methods | Only `read`, `write`, `list`, `exists`, `stat`, `ancestors`. **No mkdir, no rename, no delete.** `$.fs.write(path, text)` creates missing parent directories (probe: `agent-status/` did not exist, `writeDirect: "ok"`). `write` is not atomic (reference: "replaces the file's content in place"). | https://code.claude.com/docs/en/plugins/mods/reference.md (Mods API methods); probe |
| Rename | `$.process.run(['mv', a, b])` works (probe `mvViaProcess: "ok"`); there is no `$.fs` call | probe |
| Delete | `$.process.run(['rm', '-f', path])` (argv, no shell): not run in this spike, same mechanism as `mv`; Task 2's real run must show it | reference (no `$.fs` delete) |
| Session id | `await $.session.id()` → the transcript id, equal to the `<session_id>` the statusline tap uses (e.g. `2354629a-17dd-45ea-9171-0385fab16158`). `session.end` events also carry `sessionId`. | probe; test-kit table lists `$.session.id` |
| Event payloads (keys seen) | `session.start`: `cwd, surface, isInteractive`. `turn.start`: `text, turnId`. `turn.complete`: `answer, durationMs, isAborted, turnId, reason, usage`. `session.end`: `reason, sessionId, resume`. `tool.call`: `tool, tool_use_id` plus the tool's own args at top level (`command, description` for Bash; `questions` for AskUserQuestion). `tool.check`: `tool, input, tool_use_id, approver` (+ `isReadOnly`), args under `e.input`. | probe files |
| Tool name | `e.tool` on both `tool.call` and `tool.check` (`'Bash'`, `'AskUserQuestion'`, `'Agent'`); matcher `on('tool.call', { tool: 'AskUserQuestion' }, …)` | probe; events doc |
| `tool.check` "ask" | `await next(e)` resolves to `{ decision: 'ask', reason }` (probe: Bash `touch` outside the work dir in default permission mode → `{decision:'ask', reason:"touch in '…' needs approval…"}`; allowed call → `{decision:'allow', hook:'PreToolUse'}`) | probe; events doc |
| **Event order** | For one tool call, `tool.call` is entered **before** `tool.check` (probe timestamps: `tool.call` entered at 1793859995873 ms, `tool.check` entered 150 ms later, `tool.call`'s `next(e)` returned 16.6 s later, after the user pressed Enter on the dialog). | probe |
| AskUserQuestion | `tool.call` for it stays pending while the dialog is open (entered …078771, returned …098444 after the answer); its `tool.check` also returns `{decision:'ask', reason:'Answer questions?'}` (entered …079166, 7 ms) | probe |
| Static checks | `claude plugin validate` rejects: reading `$.fs` as a value (`$.fs is used as a value`), a non-literal `$.env.get` name, a non-literal `on()` event name. **Correction (Task 2, fix round 1): it ACCEPTS a module-level `async function flush($)` that takes `$` as a parameter and is called `flush($)`** — validate reports `calls: … $.fs.write (via flush), …`. The final mod uses one such helper instead of repeating the write block per handler. A closure inside `register` cannot use `$` lexically (`$` is only a handler parameter). It warns `gating hook without .catch` for `tool.check` and `tool.call` hooks (add `.catch` or accept). | validate output |
| Testing | `claude plugin test` runs `*.test.ts(x)` files under the plugin dir. `import { expect, test, mock } from 'claude-code/testing'`; `test(name, async ($, on) => { … })`. `$` there acts as Claude Code: `await $.tool.call({ tool: 'Bash', command: 'ls' })` fires the event through the mod; `on('name', stub)` answers mods API calls (`on('fs.write', () => ({ value: undefined }))`, `on('process.run', ($, e) => ({ value: { exitCode: 0, stdout: '503\n', stderr: '' } }))`, `on('session.id', () => ({ value: 'abc' }))`; `on('tool.call', () => ({ result: 'ok' }))` answers the tool). `mock.env(on, { TMUX_PANE: '%3' })` answers `$.env.get`; `mock.clock(on)` returns a clock the test advances (for `$.clock.every`). `session.start` does not run by itself: `await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })`. Register every stub before the first call on `$`. 5 s per test unless the test sets `timeoutMs` (reference.md, Limits table: "One `claude plugin test` test"). Not run in this spike (no test file yet). | https://code.claude.com/docs/en/plugins/mods/test.md; https://code.claude.com/docs/en/plugins/mods/reference.md |

## Findings for Task 2 (spec changes)

0. **In-process teammates were not tested.** Run (c) used a split-pane teammate (its own process and session). The docs (reference.md, `tool.check` fields: `e.agentId`) describe in-process teammates and subagents whose events reach the lead's mod with `e.agentId` set ("set when a subagent or an in-process teammate makes the call, and absent when the main conversation does"); the display mode was not tested here. Lead ruling: the mod skips every event that carries `e.agentId`, so a teammate's or subagent's activity never changes the lead's state.

1. **Transition "back to busy when that tool's `tool.call` starts" is wrong.** `tool.call` starts before `tool.check`. Use: `needs-you` when `tool.check` resolves `ask` (after `await next(e)`); back to `busy` when the same tool's `tool.call` `await next(e)` returns (the user answered and the tool ran or was refused), or `ready` at `turn.complete`. Keep the `tool_use_id` (present on both events) to pair them. AskUserQuestion is covered either way: its `tool.call` `next()` returns after the answer.
2. **There is no `$.fs` rename or delete.** Atomic-write-by-rename and `session.end` deletion go through `$.process.run(['mv', …])` and `['rm', '-f', …]`; `$.fs.write` creates parent dirs, so no mkdir call.
3. **Teammates get their own session id and file, but may not see `TC_STATE`** (it is not in the tmux server environment unless `tt set-environment -g`/the launcher sets it); the board must read the same dir the mod resolves, i.e. fall back to `$TMPDIR/tmux-ctl-<uid>` exactly as `tc_env.state_dir()` does.
4. **A `--bg` session has `pane: null`**: the board cannot match it by pane; the file is still written.
5. The validator forces inline `$.env.get('LITERAL')`, literal `on('event')` names, and no helpers taking `$`; the mod's handler bodies need repeating or the logic must be written over plain values.
6. Loading a plugin dir interactively makes Claude Code write `claude/plugin/tsconfig.json` (and `.claude-plugin/types/`); the spike did not commit them.
