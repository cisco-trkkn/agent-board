# Mod shell hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run kill-guard, bash-mirror and artifact-register in-process as Claude Code mods, with the shell scripts kept as a fallback that exits early when the mod for that hook is active in the session.

**Architecture:** One file per hook under `claude/plugin/mods/`, each exporting `register(on)`, `start($, e)` and `end($, e)`, wired into the existing entry module `claude/plugin/mods/index.js` (the only `hooks.json` module). Shared helpers in `claude/plugin/mods/lib/env.js`. On `session.start` each mod writes the marker `<state dir>/mods-active/<session_id>.<hook>`; `session.end` removes it; each shell script exits 0 when its marker exists.

**Tech Stack:** Claude Code mods (JS, `$` API), `claude plugin test` (`*.test.ts`, `claude-code/testing`), zsh test harness (`tools/tests/*.zsh`).

**Spec:** `docs/superpowers/specs/2026-11-05-mod-shell-hooks-design.md`

## Global Constraints

- **Rulings carried from earlier specs and the spike (`docs/superpowers/notes/2026-11-05-mods-spike.md`)** — these override the spec's literal wording:
  - Ruling: "each listed in hooks.json `modules`" is impossible (Claude Code refuses a second module per plugin). Read it as one file per hook, each imported by `claude/plugin/mods/index.js` with named imports and called through thunks in `runAll`, exactly like the three existing mods. `hooks.json` `"modules"` stays `["../mods/index.js"]`. The per-hook isolation the spec wants comes from each mod registering its own `on()` handlers: one throwing handler is skipped by Claude Code without affecting others.
  - `$.fs` has write/read/list/exists/stat/ancestors only. Marker delete: `$.process.run(['rm', '-f', path])`. `$.fs.write` creates parent dirs.
  - `$.env.get` names must be literals; `$` may be passed only to module-level named helpers called as `f($)`, never via dynamic calls (`m[fn]($)`) — `claude plugin validate` refuses them.
  - `$.ui.status` is not used by this spec.
  - Hooks skip nothing on `e.agentId`: kill-guard, bash-mirror and artifact-register must cover subagent and in-process teammate calls too (today's shell hooks run for them). This differs from agent-status, which skips `e.agentId`.
- **Shell parity:** decisions, feed entries and JSONL records must match the shell scripts' (byte-identical apart from timestamps `ts` and `HH:MM:SS`/`@<epoch>`). The shell scripts are the reference: `claude/plugin/scripts/kill-guard.sh`, `bash-mirror.sh`, `artifact-register.sh`.
- **State dir rule:** `$TC_STATE`, else `${TMPDIR:-/tmp}` minus trailing `/` + `/tmux-ctl-<uid>` (uid from `$.process.run(['id','-u'])`). **Lineage dir rule:** `$TC_LINEAGE`, else `${XDG_STATE_HOME:-$HOME/.local/state}/agent-board/lineage`.
- **Marker path:** `<state dir>/mods-active/<session_id>.<hook>`, `<hook>` ∈ `kill-guard`, `bash-mirror`, `artifact-register`. Written in each mod's `start`, removed in its `end` (on every `end` reason; on `clear`/`resume` the mod writes a new marker for the new session id, re-read with `$.session.id()` — see agent-status.js `end`).
- **Never block a tool:** every handler wraps its own work in try/catch and returns `next`'s result. kill-guard fails open (allow) on its own errors.
- **artifact-register `session_id`:** in the mod it comes from `$.session.id()` (the hook payload's `session_id` equivalent), never from `CLAUDE_CODE_SESSION_ID`.
- **Tests run:** targeted only — `claude plugin test claude/plugin`, `zsh tools/tests/test_kill_guard.zsh`, `zsh tools/tests/test_mirror.zsh`, `zsh tools/tests/test_artifact_hook.zsh`, `zsh tools/tests/test_plugin.zsh`, `claude plugin validate claude/plugin`. Never the full suites.
- Commits: conventional with scope (`feat(mods): …`, `fix(hooks): …`), ending with the attribution trailer your harness specifies. Stage only your own paths.

**User decisions (already made):**
- Fallback: the shell scripts stay registered; each exits early when the mod for that hook is active in the session.
- kill-guard still denies; the denial lists the non-Claude PIDs the pattern matches and the exact `kill <pids>` to run instead. Nothing is rewritten.

---

### Task 1: Probe the tool.call and tool.check shapes

**Goal:** Record, from one real Claude Code run, the exact shapes the three mods depend on, in `docs/superpowers/notes/2026-11-05-shell-hooks-probe.md`.

**Files:**
- Create: `docs/superpowers/notes/2026-11-05-shell-hooks-probe.md`
- Scratch only (not committed): a probe mod in a temp plugin dir under the scratchpad.

**Acceptance Criteria:**
- [ ] The note answers each with the observed value and how it was captured: (a) the value `next(e)` resolves to in `tool.call` for Bash on success (exit 0), on a failing command (`false`), and what fields carry stdout, stderr and the exit code; (b) the same for Write, and for a Claude Docs / Artifact tool if reachable (else say "not probed" and cite the reference doc's result shape); (c) where the Bash call's cwd is readable from a mod (`e`, `$.session`, `session.start`'s `e.cwd`, or `$.process.run(['pwd'])`) and whether it tracks `cd` between calls; (d) whether `tool.check` returning `{ decision: 'deny', reason }` without calling `next` (and also after `next`) blocks the call and shows `reason` to the model; (e) whether `new Date(ms).toTimeString()` / `getHours()` gives local time in the mod runtime (compare with `date +%H:%M:%S`); (f) whether `tool.call` fires with `e.agentId` for a subagent's Bash call.
- [ ] Each answer cites the probe log line it came from.

**Verify:** `grep -c '^- (\(a\|b\|c\|d\|e\|f\))' docs/superpowers/notes/2026-11-05-shell-hooks-probe.md` → `6`

**Steps:**

- [ ] **Step 1:** Make a scratch plugin (`.claude-plugin/plugin.json`, `hooks/hooks.json` with `"modules": ["../mods/probe.js"]`) whose mod appends `JSON.stringify({ev, e, out})` per `tool.call` / `tool.check` to a file under the scratchpad via `$.fs.write` (read-append-write). Run `claude -p --plugin-dir <scratch> "<prompt>"` with a prompt that runs `echo hi`, `false`, `cd /tmp && pwd`, `pwd`, writes a scratch file, and starts one Agent subagent that runs `echo sub`. For (d) add a second probe variant that denies `echo DENYME`. Note: `-p` runs hooks (spike); use `--permission-mode bypassPermissions` or allow rules so nothing prompts.
- [ ] **Step 2:** Write the note, one `- (x)` line per question, then commit it (`docs(notes): shell-hooks mod probe`).

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-05-shell-hooks-probe.md"], "verifyCommand": "grep -c '^- (\\(a\\|b\\|c\\|d\\|e\\|f\\))' docs/superpowers/notes/2026-11-05-shell-hooks-probe.md", "acceptanceCriteria": ["note answers (a)-(f) with observed values", "each answer cites its probe log line"], "modelTier": "standard"}
```

---

### Task 2: lib/env.js, markers, and the shell scripts' early exit

**Goal:** Shared helpers and the marker dedupe: a mod-side `writeMarker`/`removeMarker`, and each shell script exiting 0 with no output when its marker exists.

**Files:**
- Create: `claude/plugin/mods/lib/env.js`, `claude/plugin/mods/lib/env.test.ts`
- Modify: `claude/plugin/scripts/kill-guard.sh`, `claude/plugin/scripts/bash-mirror.sh`, `claude/plugin/scripts/artifact-register.sh`
- Test: `tools/tests/test_kill_guard.zsh`, `tools/tests/test_mirror.zsh`, `tools/tests/test_artifact_hook.zsh` (one marker case each)

**Acceptance Criteria:**
- [ ] `lib/env.js` exports pure helpers `stateDir(tcState, tmpdir, uid)`, `lineageDir(tcLineage, xdgStateHome, home)`, `markerPath(stateDir, sid, hook)`, and module-level `$`-taking helpers `readEnv($)` (returns `{tcState, tmpdir, tcLineage, xdgStateHome, home, tmux, tmuxPane, uid}` using literal `$.env.get` names; uid via `id -u` only when needed), `writeMarker($, path)`, `removeMarker($, path)` (`rm -f` via `$.process.run`). All swallow their errors.
- [ ] `env.test.ts` covers: `TC_STATE` wins; `TMPDIR` with and without trailing `/`; `TMPDIR` unset → `/tmp`; lineage `TC_LINEAGE` → `XDG_STATE_HOME` → `$HOME/.local/state`; marker path shape.
- [ ] Each shell script, after its existing `--scoped`/`AGENT_BOARD` check and once it has the payload, exits 0 with no output and no side effect when `<state dir>/mods-active/<session_id>.<hook>` exists for the payload's `session_id`. An empty `session_id` never matches a marker. artifact-register manual mode (`--path`) ignores markers.
- [ ] Each zsh test file gains a marker case: marker present → no deny (kill-guard: exit 0, no stderr) / no feed entry / no JSONL line; marker for a different session id → the script runs as before. Mutation: delete the early-exit line → the marker case fails.
- [ ] kill-guard.sh still reads stdin once (the payload is reused for the marker check).

**Verify:** `zsh tools/tests/test_kill_guard.zsh && zsh tools/tests/test_mirror.zsh && zsh tools/tests/test_artifact_hook.zsh && claude plugin test claude/plugin`

**Steps:**

- [ ] **Step 1:** Write the zsh marker cases and `env.test.ts`; run them RED (mutation as above).
- [ ] **Step 2:** Implement. In the shell scripts the session id comes from the payload JSON (`session_id`): bash-mirror and artifact-register already parse it in Python — add the check where the payload is first available, without a second `python3` start if the existing one can return early (e.g. pass the marker dir as an argument and `sys.exit(1)` when the marker exists). kill-guard: check inside its existing Python, right after `json.loads`.
- [ ] **Step 3:** GREEN, commit `feat(hooks): shell hooks exit early when their mod is active`.

```json:metadata
{"files": ["claude/plugin/mods/lib/env.js", "claude/plugin/mods/lib/env.test.ts", "claude/plugin/scripts/kill-guard.sh", "claude/plugin/scripts/bash-mirror.sh", "claude/plugin/scripts/artifact-register.sh", "tools/tests/test_kill_guard.zsh", "tools/tests/test_mirror.zsh", "tools/tests/test_artifact_hook.zsh"], "verifyCommand": "zsh tools/tests/test_kill_guard.zsh && zsh tools/tests/test_mirror.zsh && zsh tools/tests/test_artifact_hook.zsh && claude plugin test claude/plugin", "acceptanceCriteria": ["lib/env.js helpers with literal env names", "env.test.ts covers state/lineage rules", "each script exits 0 silently with its marker", "marker case per zsh test with mutation", "manual artifact mode ignores markers"], "modelTier": "standard"}
```

---

### Task 3: kill-guard mod

**Goal:** `claude/plugin/mods/kill-guard.js`: a `tool.check` hook for Bash that denies a `pkill`/`killall` whose pattern matches a Claude process, listing the non-Claude PIDs and the `kill` line to run instead.

**Files:**
- Create: `claude/plugin/mods/kill-guard.js`, `claude/plugin/mods/kill-guard.test.ts`
- Modify: `claude/plugin/mods/index.js` (import; `start`/`end` thunks; `register`)

**Acceptance Criteria:**
- [ ] Same logic as `kill-guard.sh`: a quick `\b(pkill|killall)\b` pre-check; shlex-style tokenising with punctuation splitting (`();&|<>`) and posix quoting; every occurrence including nested `-c` strings to depth 3; raw-regex fallback on unbalanced quotes; `pkill -f` (any short flag cluster containing `f`, not `--…`) matches full args, plain `pkill` the basename of comm, `killall` the exact basename; last non-flag arg is the pattern; an invalid regex matches as a substring; Claude test = any of comm, argv[0], `readlink /proc/<pid>/exe` (when it succeeds) contains `/claude/versions/` or has basename `claude`; processes from `ps -axww -o pid=,comm=` and `ps -axww -o pid=,args=` via `$.process.run`.
- [ ] Python `re` vs JS `RegExp`: note in a code comment that JS regex syntax is used; patterns valid in one and not the other fall to substring matching.
- [ ] On a hit, returns `{ decision: 'deny', reason }` (shape confirmed by Task 1 (d)) where reason = the shell's BLOCKED text (`` `<tool> <args>` would also kill Claude Code process(es) [<pids>] … ``) followed by either `Instead run: kill <pid> <pid> …` (non-Claude PIDs the same pattern matches, ascending, excluding the mod's own process tree if identifiable) or `No other processes match.` Otherwise returns `next(e)`'s result unchanged.
- [ ] Any error in the mod's own work → falls through to `next(e)` (fail open).
- [ ] `kill-guard.test.ts` replays every case in `tools/tests/test_kill_guard.zsh` (same decision) with `ps`/`readlink` answered by a `process.run` stub, plus: denial lists non-Claude PIDs with the `kill` line; `No other processes match.` when none; a thrown `process.run` → allow. Mutation per guard test: remove the Claude test → the "non-Claude only" case denies; remove the `-c` recursion → the nested case allows.
- [ ] `start` writes the `kill-guard` marker, `end` removes it (tested with stubs).

**Verify:** `claude plugin test claude/plugin && claude plugin validate claude/plugin`

**Steps:**

- [ ] **Step 1:** Port the test cases from `test_kill_guard.zsh` to `kill-guard.test.ts`; RED.
- [ ] **Step 2:** Implement `kill-guard.js` (pure `scan(text)`/`tokens(text)`/`isClaude`/`matchPids` functions + the hook); wire into `index.js` the same way as the existing three mods.
- [ ] **Step 3:** GREEN; `claude plugin validate claude/plugin` clean of new errors; commit `feat(mods): kill-guard in-process`.

```json:metadata
{"files": ["claude/plugin/mods/kill-guard.js", "claude/plugin/mods/kill-guard.test.ts", "claude/plugin/mods/index.js"], "verifyCommand": "claude plugin test claude/plugin && claude plugin validate claude/plugin", "acceptanceCriteria": ["port of kill-guard.sh logic", "deny with BLOCKED text plus Instead run: kill … or No other processes match.", "fail open", "every test_kill_guard.zsh case replayed", "marker on start/end"], "modelTier": "standard"}
```

---

### Task 4: bash-mirror mod

**Goal:** `claude/plugin/mods/bash-mirror.js`: after each Bash `tool.call` resolves or rejects, append the same entry as `bash-mirror.sh` to the same feed log.

**Files:**
- Create: `claude/plugin/mods/bash-mirror.js`, `claude/plugin/mods/bash-mirror.test.ts`
- Modify: `claude/plugin/mods/index.js`

**Acceptance Criteria:**
- [ ] Runs only with `TMUX` and `TMUX_PANE` set. Skips commands starting with `tmux-ctl` (same regex). Same `classify` (tests vs shell) regexes, copied verbatim from the shell's Python (JS-compatible: Python `(?![\w-])` and `\x27` work in JS). Same exit code rule, using the result fields Task 1 (a) recorded (failure: a rejected `next` or an error result → parse `^Exit code (\d+)` else 1). Same output tail (last 12 lines of stdout+stderr), same first-line + ` …` rule, same `~` cwd shortening, cwd from the source Task 1 (c) recorded.
- [ ] Same tmux lookups via `$.process.run` on the tmux binary: `$TC_TMUX`, else `$HOME/.local/bin/tmux` if it exists, else `tmux`, with `-S ${TMUX%%,*}`; `display -p -t $TMUX_PANE` for session/window/canonical name; `list-windows`; `has-session -t =<canon>-bg`; strip `✦ ` from the caller. Differences from the shell: the shell sources `bin/_tc_bins.zsh` when present — the mod uses only the fallback chain above; state that in a comment.
- [ ] Same log path `<state dir>/feed-<canon>-<kind>.log`, same size trim (over 2097152 bytes → keep the last 1048576 bytes), same header `── HH:MM:SS · <caller> · <cwd> · exit N · @<epoch>` in local time, body `$ <first>` plus tail, trailing newline. Appends are read-modify-write through `$.fs` (no append API) or `$.process.run` — choose and justify in a comment; writes of one session are chained so two calls never interleave.
- [ ] Returns `next(e)`'s result; a rejected `next` is re-thrown after the entry is written.
- [ ] `bash-mirror.test.ts` replays every case in `tools/tests/test_mirror.zsh` and asserts the feed text equals the shell's apart from the time and `@epoch`; plus a rejected-`next` case and a `tmux-ctl` skip case. Mutation: remove the `tmux-ctl` skip → its test fails.
- [ ] `start` writes the `bash-mirror` marker, `end` removes it.

**Verify:** `claude plugin test claude/plugin && claude plugin validate claude/plugin`

**Steps:**

- [ ] **Step 1:** Port `test_mirror.zsh` cases; RED.
- [ ] **Step 2:** Implement and wire into `index.js`.
- [ ] **Step 3:** GREEN; commit `feat(mods): bash-mirror in-process`.

```json:metadata
{"files": ["claude/plugin/mods/bash-mirror.js", "claude/plugin/mods/bash-mirror.test.ts", "claude/plugin/mods/index.js"], "verifyCommand": "claude plugin test claude/plugin && claude plugin validate claude/plugin", "acceptanceCriteria": ["same entry format and log path as bash-mirror.sh", "requires TMUX and TMUX_PANE", "returns next result, rethrows rejection after writing", "every test_mirror.zsh case replayed", "marker on start/end"], "modelTier": "standard"}
```

---

### Task 5: artifact-register mod

**Goal:** `claude/plugin/mods/artifact-register.js`: after `tool.call` for `Write|Edit|MultiEdit|Artifact|mcp__claude_ai_Claude_Docs__batch|…__create|…__update`, append the same JSONL record as `artifact-register.sh` hook mode.

**Files:**
- Create: `claude/plugin/mods/artifact-register.js`, `claude/plugin/mods/artifact-register.test.ts`
- Modify: `claude/plugin/mods/index.js`

**Acceptance Criteria:**
- [ ] Matcher via `on('tool.call', { tool: [...] }, …)` (exact list above). Project from `tmux display -p -t $TMUX_PANE '#{?session_group,#{session_group},#{session_name}}'`, must match `^[A-Za-z0-9._-]+$`; agent from `#{window_name}` minus `✦ `, default `claude`; epoch = line count of `<lineage dir>/<project>.jsonl` (0 if absent).
- [ ] Same per-tool rules as the shell's hook mode: Artifact needs a `https://claude.ai/…` URL in the result (kind `published`); Claude Docs frame/slug/title/manifest-reuse rules including the `https://claude.ai/` URL guard; Write/Edit/MultiEdit use `file_path` (realpath, must be a file); `kind_of` rules (plan/spec/handoff/report, else skip); sha256 of the file for local paths (via `shasum -a 256` through `$.process.run`, or another route — justify; realpath via `realpath` or equivalent).
- [ ] `session_id` from `$.session.id()`; record keys and order `{ts,path,kind,agent,hash,url,title,slug,session_id,epoch}`; one line appended to `<state dir>/artifacts-<project>.jsonl`; writes chained.
- [ ] Returns `next(e)`'s result; nothing recorded when `next` rejects.
- [ ] `artifact-register.test.ts` replays every hook-mode case in `tools/tests/test_artifact_hook.zsh` (manual-mode cases are out of scope) and asserts records equal the shell's apart from `ts`. Mutation: drop the `https://claude.ai/` guard → the `javascript:` URL case records a line.
- [ ] `start` writes the `artifact-register` marker, `end` removes it.

**Verify:** `claude plugin test claude/plugin && claude plugin validate claude/plugin`

**Steps:**

- [ ] **Step 1:** Port the hook-mode cases; RED.
- [ ] **Step 2:** Implement and wire into `index.js`.
- [ ] **Step 3:** GREEN; commit `feat(mods): artifact-register in-process`.

```json:metadata
{"files": ["claude/plugin/mods/artifact-register.js", "claude/plugin/mods/artifact-register.test.ts", "claude/plugin/mods/index.js"], "verifyCommand": "claude plugin test claude/plugin && claude plugin validate claude/plugin", "acceptanceCriteria": ["same record as artifact-register.sh hook mode", "session_id from $.session.id()", "nothing recorded on rejected next", "every hook-mode case replayed", "marker on start/end"], "modelTier": "standard"}
```

---

### Task 6: Manifest, plugin test, and one real run

**Goal:** Update the manifest description and `tools/tests/test_plugin.zsh`, then prove the whole thing in one real scratch-tmux run.

**Files:**
- Modify: `claude/plugin/.claude-plugin/plugin.json` (description names the three new mods), `tools/tests/test_plugin.zsh` (asserts index.js imports the three new mods and the three shell scripts are still registered in hooks.json)
- Create: `tools/tests/e2e-shell-hooks.md` (the run's commands and observed output)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/test_plugin.zsh` passes and fails if any of the three imports is removed from `index.js`.
- [ ] Real run in a scratch tmux server (`~/.local/bin/tmux -L <sock> -f /dev/null`, temp `TC_STATE`, a `<project>-bg` session so feeds are written), lead started with `--plugin-dir` this worktree's `claude/plugin` and `--settings claude/session-settings.json`: three markers appear under `<TC_STATE>/mods-active/`; one Bash call yields exactly one feed entry (not two); `pkill -f <a pattern matching that claude process>` is denied and the denial shows the PID list and an `Instead run:`/`No other processes match.` line; one Write of a `docs/superpowers/specs/x.md` file yields exactly one artifact record. After the session exits, its markers are gone.
- [ ] Real-state check (read-only): the mod's feed header regex matches the last 5 headers of the user's real live feed log `"${TMPDIR%/}/tmux-ctl-$UID/feed-agent-board-shell.log"` (printing how many headers it checked).
- [ ] The scratch tmux server and every process it started are killed afterwards (`ps` checked).

**Verify:** `zsh tools/tests/test_plugin.zsh && grep -c 'OBSERVED' tools/tests/e2e-shell-hooks.md`

**Steps:**

- [ ] **Step 1:** Edit the manifest and `test_plugin.zsh`; RED by removing one import, then GREEN.
- [ ] **Step 2:** Do the real run (see `tools/tests/e2e-agent-status.md` for how a scratch lead was driven: send-keys text, wait 1 s, separate Enter). Record each check as an `OBSERVED:` line with the output.
- [ ] **Step 3:** Clean up, commit `test(mods): shell-hooks e2e and plugin manifest`.

```json:metadata
{"files": ["claude/plugin/.claude-plugin/plugin.json", "tools/tests/test_plugin.zsh", "tools/tests/e2e-shell-hooks.md"], "verifyCommand": "zsh tools/tests/test_plugin.zsh && grep -c 'OBSERVED' tools/tests/e2e-shell-hooks.md", "acceptanceCriteria": ["test_plugin.zsh asserts imports and shell registrations", "real run: one feed entry per Bash, pkill denied with PID list, one artifact record per Write, markers created and removed", "real-state header check against live feed log", "scratch server cleaned up"], "modelTier": "standard"}
```
