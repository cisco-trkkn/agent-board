# Mod: the plugin's shell hooks in-process

Date: 2026-11-05 · Status: approved design, awaiting spec review
Source: ideas file, 2026-11-04 23:23 "mod: move the plugin's shell hooks in-process" (picked in a `regroup`, 2026-11-05).
Depends on: `2026-11-05-mod-agent-status-design.md` (its spike, `docs/superpowers/notes/2026-11-05-mods-spike.md`, records
where mods load and the `$` API calls; its `claude/plugin/mods/` layout and `hooks.json` `"modules"` entry).

## Problem

`kill-guard`, `bash-mirror` and `artifact-register` run as shell hooks: each Bash or Write call starts zsh and
Python processes before and after the tool. Claude Code mods run in-process. kill-guard also only blocks; it
does not tell the agent which processes it can safely kill instead.

## User decisions (2026-11-05)

- **Fallback:** the shell scripts stay registered. Each exits early when the mod for that hook is active in the
  session. Sessions where mods do not load keep today's protection.
- **kill-guard:** still denies. The denial lists the non-Claude PIDs the pattern matches and the exact
  `kill <pids>` to run instead. Nothing is rewritten behind the agent's back.

## Design

### 1. Layout and dedupe

- One mod per hook: `claude/plugin/mods/kill-guard.js`, `bash-mirror.js`, `artifact-register.js`, each listed in
  `claude/plugin/hooks/hooks.json` `"modules"`. Shared helpers in `claude/plugin/mods/lib/env.js`: state dir
  (the `tc_env.state_dir()` rule: `$TC_STATE`, else `${TMPDIR:-/tmp}` minus trailing `/` + `/tmux-ctl-<uid>`), lineage
  dir (the `tc-env.zsh` rule), `TMUX`/`TMUX_PANE`, uid. One file per hook so one hook's error or timeout skips only
  that hook.
- Marker: on `session.start` each mod writes `<state dir>/mods-active/<session_id>.<hook>` (`<hook>` is
  `kill-guard`, `bash-mirror` or `artifact-register`); `session.end` deletes it.
- Each shell script keeps its `--scoped` / `AGENT_BOARD` check, then reads `session_id` from the hook payload and
  exits 0 with no output when its marker exists. No marker (mods did not load, or the mod failed before writing
  it): the script runs as today. Session ids are unique, so a marker left by a crashed session mutes nothing else.
- The manual mode `artifact-register.sh --path …` (used by `tmux-ctl artifact`) has no payload and always runs.

### 2. kill-guard

- Handler on `tool.check` for `Bash` (the allow / ask / deny decision before any prompt).
- A JS port of `claude/plugin/scripts/kill-guard.sh`'s logic, same behaviour:
  - shlex-style tokens with punctuation splitting, every `pkill`/`killall` occurrence including nested `-c` strings;
    a raw regex over the text when quoting is unbalanced;
  - the Claude-process test: any of comm, argv[0] or `/proc/<pid>/exe` (when readable) is under `/claude/versions/`
    or has basename `claude`;
  - pattern matching: `pkill -f` against full args, plain `pkill` against the basename of comm, `killall` by exact
    basename; an invalid regex matches as a substring;
  - processes from `ps -axww -o pid=,comm=` and `ps -axww -o pid=,args=` through `$.process.run`.
- On a hit: deny with a message naming the Claude PIDs it would kill, then either
  `Instead run: kill <pid> <pid> …` (the non-Claude processes the same pattern matches) or
  `No other processes match.`
- Its own errors fail open (allow), as today.

### 3. bash-mirror and artifact-register

- bash-mirror: on `tool.call` for `Bash`, after `await next(e)` returns, success or failure, append the same entry
  to the same feed log as `bash-mirror.sh` (header `── HH:MM:SS · <agent> · <cwd> · exit N · @<epoch>`, same body,
  same agent and log-file resolution). Requires `TMUX` and `TMUX_PANE`, as today.
- artifact-register: on `tool.call` for the same tools as today's matcher (`Write|Edit|MultiEdit|Artifact|`
  `mcp__claude_ai_Claude_Docs__batch|…__create|…__update`), after `next()`, append the same JSONL record
  `{ts,path,kind,agent,hash,url,title,slug,session_id,epoch}` to the same `$STATE/artifacts-<project>.jsonl`.
- Both never throw into the tool: every handler returns `next`'s result.

## Files

- Create: `claude/plugin/mods/kill-guard.js`, `bash-mirror.js`, `artifact-register.js`, `lib/env.js`, and a
  `*.test.ts` beside each.
- Modify: `claude/plugin/hooks/hooks.json` (`"modules"`), `claude/plugin/scripts/kill-guard.sh`,
  `bash-mirror.sh`, `artifact-register.sh` (marker early exit), the plugin manifest description,
  `tools/tests/test_plugin.zsh` (modules listed; scripts still registered).

## Testing

- Parity: every case in `tools/tests/test_kill_guard.zsh`, `test_mirror.zsh` and `test_artifact_hook.zsh` replayed
  against the mod with `claude plugin test`: same allow/deny decision; feed lines and JSONL records byte-identical
  to the shell's output apart from timestamps.
- New kill-guard cases: the denial lists the non-Claude PIDs and the `kill` line; "No other processes match." when
  none.
- Dedupe: with the marker, each shell script exits 0 and writes nothing; without it, it runs (the existing zsh tests,
  plus one marker case each).
- One real run in a scratch tmux server (`-f /dev/null`, temp `TC_STATE`), lead launched with the worktree's plugin:
  one feed entry per Bash call (not two), a `pkill -f <claude pattern>` denied with the PID list, one artifact record
  per Write.
- Targeted runs only: `claude plugin test claude/plugin/mods`, the three zsh test files, `zsh tools/tests/test_plugin.zsh`.

## Failure

If the mods spike shows mods load in no lead context, or `tool.check` cannot deny with a message, this spec fails in
the queue (`failed — <which>`); the shell hooks stay as they are.

## Not in scope

`context-inject`, `worktree-sweep`, `plan-handoff-guard` and `sdd-call-guard` stay shell hooks. Rewriting a pkill into
a PID kill (decided against).
