# PCEE engine part 3 (approval holds and schedules) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Engine workers are held on a stop-class tool call (push, hard reset, branch delete, clean, recursive delete or write outside the worktree, PR merge) until the user approves it once, and recurring jobs run from rows in the engine's `timers` table, fired by one launchd heartbeat (`tmux-ctl engine wake`), with the earlier agent-board LaunchAgents migrated into rows.

**Architecture:** A `PreToolUse` hook in the agent-board plugin (`claude/hooks/engine-hold.sh` → `node engine/bin/hold.js`) acts only inside an engine worker (`ENGINE_JOB` set). It matches the call against the hold rules; without a pass it writes one `approval` inbox row and denies; with a pass it consumes it (one event) and allows. The core drains the row, ends the job as `escalated`, parks the spec with the exact call, and on `approve` writes a one-time pass and resumes the worker's session (or a fresh worker). Schedules are `timers` rows of kind `schedule`; `engine wake` (launchd, every 15 minutes and at load) moves each due row to its next occurrence and inserts one `schedule` inbox row; the running engine drains it on its tick, or, with no engine running, `engine wake` takes the lock and runs a short pass that drains only `schedule` rows. Each run is a window `sched·<name>` in `<project>-bg`.

**Tech Stack:** Node >= 22.13 (`node:sqlite`, `node:test`), no npm dependency; bash (the hook entry), zsh (`bin/tmux-ctl`, `tools/tests`), tmux 3.8, launchd (`launchctl`, `plutil`), git.

**Spec:** docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-3

Sections 13 (approval holds) and 14 (schedules) as written, pulled forward by revision G1 (2026-11-24); the Holds and Schedules items of the spec's Testing section; section 12's `approval` and `schedule` inbox writers. Out of this part (revision items 14 and 18): the SDK-backend variant of holds (`canUseTool`, stage 8) and the Discord interface (stage 7). Parts 1 and 2 are merged (064a029); their plans' Global Constraints still bind and are not repeated, except where this plan changes one (marked **changes part 2**).

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-3",
 "base": "1d6d988a170f21dd40e79b2a468e9ce0dc12fed6",
 "depends_on": [{"spec": "docs/superpowers/specs/2026-11-10-pcee-engine-design.md#part-2", "kind": "hard"}],
 "writes": [
  {"path": "engine/lib/engine/hold.js", "mode": "create"},
  {"path": "engine/bin/hold.js", "mode": "create"},
  {"path": "engine/lib/engine/schedule_rules.js", "mode": "create"},
  {"path": "engine/lib/engine/schedule.js", "mode": "create"},
  {"path": "engine/lib/engine/wake.js", "mode": "create"},
  {"path": "engine/lib/engine/launchd.js", "mode": "create"},
  {"path": "engine/lib/engine/db.js", "mode": "modify"},
  {"path": "engine/lib/engine/policy.js", "mode": "modify"},
  {"path": "engine/lib/engine/inbox.js", "mode": "modify"},
  {"path": "engine/lib/engine/steps.js", "mode": "modify"},
  {"path": "engine/lib/engine/core.js", "mode": "modify"},
  {"path": "engine/lib/engine/cli.js", "mode": "modify"},
  {"path": "engine/lib/engine/backend/claude_tmux.js", "mode": "modify"},
  {"path": "engine/lib/engine/backend/fake.js", "mode": "modify"},
  {"path": "engine/test/engine_hold.test.js", "mode": "create"},
  {"path": "engine/test/engine_holds_core.test.js", "mode": "create"},
  {"path": "engine/test/engine_schedule_rules.test.js", "mode": "create"},
  {"path": "engine/test/engine_schedule.test.js", "mode": "create"},
  {"path": "engine/test/engine_wake.test.js", "mode": "create"},
  {"path": "engine/test/engine_schedule_core.test.js", "mode": "create"},
  {"path": "engine/test/engine_migrate.test.js", "mode": "create"},
  {"path": "engine/test/engine_backend.test.js", "mode": "modify"},
  {"path": "engine/test/engine_db.test.js", "mode": "modify"},
  {"path": "engine/test/engine_inbox.test.js", "mode": "modify"},
  {"path": "engine/test/engine_cli.test.js", "mode": "modify"},
  {"path": "engine/test/engine_steps.test.js", "mode": "modify"},
  {"path": "claude/plugin/scripts/engine-hold.sh", "mode": "create"},
  {"path": "claude/hooks/engine-hold.sh", "mode": "create"},
  {"path": "claude/hooks/tests/test-engine-hold.sh", "mode": "create"},
  {"path": "claude/plugin/hooks/hooks.json", "mode": "modify"},
  {"path": "bin/tmux-ctl", "mode": "modify"},
  {"path": "tools/tests/test_plugin.zsh", "mode": "modify"},
  {"path": "tools/tests/test_agent_dir.zsh", "mode": "modify"},
  {"path": "docs/INSTALL.md", "mode": "modify"},
  {"path": "docs/ARCHITECTURE.md", "mode": "modify"},
  {"path": "docs/superpowers/notes/2026-11-24-engine-part-3-interfaces.md", "mode": "create"},
  {"path": "docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md", "mode": "create"}
 ],
 "reads": ["docs/superpowers/specs/2026-11-10-pcee-engine-design.md", "docs/superpowers/plans/2026-11-23-pcee-engine-part-1.md",
           "docs/superpowers/plans/2026-11-24-pcee-engine-part-2.md", "docs/superpowers/ledgers/2026-11-24-pcee-engine-part-2/preflight-rulings.md",
           "engine/lib/engine/paths.js", "engine/lib/engine/feed.js", "engine/lib/engine/rebuild.js", "engine/lib/engine/queue.js",
           "engine/lib/engine/strategy/spec_driven.js", "engine/test/engine_helpers.js", "engine/test/fixtures/engine/fake-worker.js",
           "engine/test/engine_cli.test.js", "engine/test/engine_core.test.js", "engine/test/engine_rebuild.test.js",
           "claude/plugin/scripts/kill-guard.sh", "claude/plugin/mods/agent-status.js", "board/scout_schedule.py", "board/usage.py",
           "tools/tests/lib.zsh", "tools/tests/all.zsh", "docs/superpowers/engine.json"],
 "produces": ["engine/bin/hold.js PreToolUse hook", "claude/hooks/engine-hold.sh", "engine.json key holds", "holds table",
              "inbox sources approval and schedule", "tmux-ctl engine schedule add|list|rm|run-now|migrate",
              "tmux-ctl engine wake [install|status|uninstall]", "launchd com.user.agent-board-engine-wake",
              "worker env ENGINE_JOB ENGINE_DIR ENGINE_PROJECT ENGINE_WORKTREE"],
 "consumes": ["engine inbox, waits, steps, timers, events (parts 1 and 2)", "tmux-ctl agent --dir --resume", "agent-status files",
              "statusline tap files", "launchctl", "plutil"],
 "tests": ["engine/test/engine_hold.test.js", "engine/test/engine_holds_core.test.js", "engine/test/engine_schedule_rules.test.js",
           "engine/test/engine_schedule.test.js", "engine/test/engine_wake.test.js", "engine/test/engine_schedule_core.test.js",
           "engine/test/engine_migrate.test.js", "claude/hooks/tests/test-engine-hold.sh"]}
```

## Global Constraints

Every task respects these. Reviewers check against them and against spec sections 12, 13 and 14.

- **Parts 1 and 2 stand:** CommonJS, `"use strict"`, standard library only; argv arrays for every external command; test isolation (`TC_ENGINE_DIR` and `TC_STATE` in a temp dir via `engine_helpers.tmpEnv()`, scratch tmux with `-f /dev/null` and a short `TMUX_TMPDIR` via `engine_helpers.scratchTmux()`, `HOME` pointed at a temp dir for anything under `~/Library/LaunchAgents`); `engine/test/engine_helpers.js` is not edited (a task that needs a helper puts it in its own test file). One command, one event (the pump's invariant): every command a task adds to `core.apply` writes exactly one event carrying `{cause, idx}`, and an outside action it runs first is a `steps` row. `engine rebuild --check` exits 0 after every new path (each test that writes rows ends with it).
- **Never touched by any test:** the real engine directory (`~/.local/state/agent-board/engine`), the real tmux server, the real `~/Library/LaunchAgents`, `launchctl` itself (tests use `AS_LAUNCHCTL` pointing at a logging stub). Each test file that could reach one of them ends with a leak check (the real engine dir's file list and mtimes unchanged; no `com.user.agent-board-engine-wake.plist` under the real `~/Library/LaunchAgents` that was not there before).
- **Worker environment (Task 2 sets it; Tasks 1 and 3 read it).** Every worker the engine starts or resumes gets `ENGINE_JOB=<job id>`, `ENGINE_PROJECT=<project>`, `ENGINE_DIR=<engine state dir, paths.engineDir()>`, `ENGINE_WORKTREE=<the spec's worktree, absolute>`. The spec names `ENGINE_JOB` and `ENGINE_DIR`; `ENGINE_PROJECT` and `ENGINE_WORKTREE` are added because the hook needs the database name and the worktree root.
- **Hold rules (Task 1).** A rule is `{"tool": "<regex>", "pattern": "<regex>", "outside_worktree": true|false}`. `tool` is matched against the whole tool name (`^(?:<tool>)$`), so `Write|Edit` is one rule. `pattern` is matched (unanchored, JS `RegExp`) against: for `Bash`, `tool_input.command`; for any other tool, the call's path (`tool_input.file_path`, else `notebook_path`, else `path`), tested against both the absolute path and the path relative to `ENGINE_WORKTREE` (a match on either counts). `outside_worktree: true` adds a condition: at least one path the call touches resolves outside `ENGINE_WORKTREE` (for `Bash`, the words that follow the pattern's match up to the next `;`, `&&`, `||`, `|` or newline, skipping words that start with `-`, with `~` expanded and resolved against the hook input's `cwd`; for other tools, the call's path). A path is outside when its `realpath` (of the deepest existing ancestor, then the rest appended) does not start with the worktree's `realpath` plus `/`. The rules are `hold.DEFAULT_HOLDS` followed by `engine.json` key `holds` (added, never replacing). A call is held when any rule matches.
- **`hold.DEFAULT_HOLDS`, exactly (spec 13 defaults; the patterns were run by the plan author against 36 bypass cases, see Task 1).** With `GIT` = `` (?:^|[;&|(`'"]|\$\(|\b(?:env|command|exec|nohup|time|xargs)\s+(?:\S+=\S*\s+)*|\s)(?:\S*/)?git(?:\s+(?:-C\s+\S+|-c\s+\S+|--[a-z-]+(?:=\S+)?|-[pP]))*\s+ ``:

  | id | tool | pattern | outside_worktree |
  | --- | --- | --- | --- |
  | `git_push` | `Bash` | `GIT + push\b` | false |
  | `git_reset_hard` | `Bash` | `GIT + reset\b(?=[^;&\|]*\s--hard\b)` | false |
  | `git_branch_force_delete` | `Bash` | `GIT + branch\b(?=[^;&\|]*\s(?:-[a-zA-Z]*D[a-zA-Z]*\|--delete\s+--force\|--force\s+--delete\|-d\s+--force\|-f\s+-d\|-df\|-fd)(?:\s\|$))` | false |
  | `git_clean` | `Bash` | `GIT + clean\b` | false |
  | `rm_recursive_outside` | `Bash` | `` (?:^\|[;&\|(`'"\s])(?:\S*/)?rm\s+(?:-[a-zA-Z]*[rR][a-zA-Z]*\|--recursive)\b `` | true |
  | `write_outside` | `Write\|Edit\|MultiEdit\|NotebookEdit` | `.*` | true |
  | `pr_merge` | `Bash` | `` (?:^\|[;&\|(`'"\s])(?:\S*/)?(?:glab\s+mr\s+merge\|gh\s+pr\s+merge)\b `` | false |

  (`\|` in this table is a literal `|` in the regex.) Each entry also carries its `id` (not part of the config shape; config rules get `config:<index>`).
- **Call hash.** `call_hash = sha256(tool_name + "\n" + canonical(input))`, where `canonical` is `JSON.stringify` with keys sorted at every level, after dropping the top-level key `description`. Probe (plan author, 2026-11-24, Claude Code 2.1.331, `claude -p --model haiku` with a logging PreToolUse hook): a Bash call's `tool_input` is `{"command": "echo hi", "description": "Print hi"}`; the model writes `description` itself, so a retried call "exactly as before" may carry a different one. A Write call's `tool_input` keys are `content`, `file_path`.
- **Hook output (probe, same run).** Deny: stdout `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "<reason>"}}`, exit 0; the model received the reason verbatim and did not retry. Allow: the same with `"allow"`; the call ran without `--allowedTools`. A matcher `"*"` fired on a Write call. The hook input's keys: `cwd`, `effort`, `hook_event_name`, `permission_mode`, `prompt_id`, `session_id`, `tool_input`, `tool_name`, `tool_use_id`, `transcript_path`.
- **Hold reason, exactly:** `held for approval <hold id>: report status blocked with the concern "awaiting approval <hold id>", then stop`. Hold ids are `crypto.randomUUID()`.
- **The `approval` inbox row:** `source` `approval`, `source_id` the hold id, `spec` the job's spec, `job` `ENGINE_JOB`, `kind` `hold`, `payload` `{hold_id, tool, input, call_hash, rule, session_id, cwd}` (`session_id` from the hook input). The hook writes this row and nothing else when it holds.
- **`holds` table (Task 1):** `holds(hold_id TEXT PRIMARY KEY, spec TEXT, job TEXT, call_hash TEXT, tool TEXT, input TEXT, created_at REAL, expires_at REAL, used_at REAL)`. Only two writers: the core writes a row on `approve` (`expires_at` = now + 3600); `hold.js` sets `used_at` when it allows the call, in one transaction with an event `hold_pass_used` carrying the row (so replay holds; spec 13 has the hook set `used_at`). A pass matches when `call_hash` is equal, `used_at` is null, `expires_at` > now, and the pass's `spec` equals the spec of `ENGINE_JOB` (the pass is bound to the call and the spec, not the session: spec 13, "the pass still applies").
- **Hold park (Task 3):** step `core:hold:<hold id>`, wait kind `stop_class` (default recommendation `deny`, spec 8a), options `approve|deny|fail`, question `<tool>: <command>` for Bash, `<tool>: <path>` for a path tool, else `<tool>: <canonical input>`, cut to 300 characters.
- **Resume texts, exactly (spec 13):** approve `approval <hold id> granted: retry the held call exactly as before`; deny `denied: <note>. Continue without it, or report blocked.` (`<note>` is the signal's note, or `no reason given` when there is none).
- **Schedules (Tasks 4 to 8).** A schedule is a `timers` row: `id` `schedule:<name>`, `spec` null, `job` null, `kind` `schedule`, `due_at` its next occurrence (epoch seconds), `payload` JSON `{"name", "command", "rule", "skip_if_weekly_usage", "cwd", "env"}`, `fired_at` null while active. `schedule rm` retires a row by setting `fired_at` (rebuild replays only puts, so a row is never deleted). `inbox.moveDueTimers` never touches kind `schedule` (**changes part 1**). Names match `^[A-Za-z0-9][A-Za-z0-9._-]*$`. Rules: `daily HH:MM`, `weekly <Mon|Tue|Wed|Thu|Fri|Sat|Sun> HH:MM`, `every <n>m`, local time. `skip_if_weekly_usage` default 85; `null` never skips.
- **The `schedule` inbox row:** `source` `schedule`, `source_id` `<name>@<due_at>` (the occurrence that came due, epoch seconds as written in the row) or `<name>@now:<epoch seconds>` for `run-now`, `kind` `run`, `spec` null, `payload` the schedule's payload plus `"force": true` for `run-now`. Any writer may insert such a row with at least `{"command"}`; a missing `name` is the `source_id` before `@` (the supervised improvement loop's post-report row relies on this).
- **Weekly usage:** the newest file under `<stateDir>/statusline/*.json` (by its `received_at`) that has `rate_limits.seven_day.used_percentage`; none: unknown, and the run goes ahead with `usage: null` in its event.
- **A run:** a window `sched·<name>` in session `<project>-bg` (created when absent: `new-session -d -s <project>-bg -n shell -c <cwd>`, then `set-option -t =<project>-bg: @tc_bg 1`, the same mark `ensure_bg` in `bin/tmux-ctl` sets), running `zsh -c` on `( <env assignments> <command> ) 2>&1 | tee <log>; print -r -- ${pipestatus[1]} > <rc>`, in `cwd`. Files: `<engineDir>/sched/<project>/<name>-<run key>.log` and `.rc`, with `<run key>` the `source_id` after `@` with `:` replaced by `-`. tmux is called with `TMUX_DASH_TMUX_ARGS` split on spaces as leading arguments (the seam the CLI already uses), and with `TMUX` removed from the environment. Events: `schedule_skipped {name, reason, usage}`, `schedule_started {name, key, window, rc_file, log}`, `schedule_ran {name, key, rc, log}`. A run is a `steps` row kind `schedule_run`, key `schedule_run:<source_id>`, `spec` null.
- **The heartbeat:** launchd label `com.user.agent-board-engine-wake`, `ProgramArguments` `[<tmux-ctl>, "engine", "wake"]`, `StartInterval` 900, `RunAtLoad` true, `WorkingDirectory` the checkout root, `EnvironmentVariables` `PATH` (`<home>/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`), `LANG`, and `TC_STATE`, else `TMPDIR`, when set (the scout plist's rule, `board/scout_schedule.py` `plist_text`), plus `TC_ENGINE_DIR` when set. The tmux-ctl path: `~/.local/bin/tmux-ctl` when executable, else `<checkout>/bin/tmux-ctl`.
- **`bin/tmux-ctl`'s help** prints `sed -n '2,85p'` and nine suites pin it: no task adds a header line. `engine)` already exists and `engine` already works outside tmux (line 122), so `engine wake` from launchd needs no new exemption.
- **Commits.** Conventional commits with scope (`feat(engine): …`, `feat(hooks): …`, `feat(tmux-ctl): …`, `docs(engine): …`); end every commit message with the attribution trailer your harness specifies. Stage only your own paths (`git add <paths>`, commit with `-- <paths>`). Nothing is pushed and no PR is opened by this plan.

**User decisions (already made):**
- "G1. Sections 13 (approval holds) and 14 (schedules) are built now as Part 3 of this spec, as written there, on top of Parts 1 and 2 as merged (064a029). … stage 7 keeps the Discord interface. The SDK-backend variant of holds (revision 18, `canUseTool`) stays with stage 8." (spec, Revised 2026-11-24)
- "The engine-hold hook calls `node engine/bin/hold.js`." (revision item 14, 2026-11-19)
- "Discord in stage 3 goes only through the existing file contracts" (item 13): the hold's park is a feed `decision` line like every park; no Discord code changes here.
- "runs.jsonl has one writer" (item 10): nothing here writes it.
- Spec 14: "Part 2's finishing step runs [`schedule migrate`] once; the stored Queue mode answer is the user's approval." With G1 this is Part 3's finishing step (see Finishing, below).

**Assumptions (plan author's; each costs one small change if wrong):**
- A1. `ENGINE_DIR` is the engine's state directory (where `<project>.sqlite` lives), not the worktree; `ENGINE_PROJECT` and `ENGINE_WORKTREE` are added (Global Constraints).
- A2. The call hash drops `description` (probe above). Any other change to the input is a different call and is held again.
- A3. `engine.json` `holds` adds to the defaults; there is no way to switch a default off in this part.
- A4. Known limits of the hold, tested as "not held" so a change is visible: `"git" push`, `g\it push`, a script file or alias that pushes (`sh push.sh`), `git push` assembled from variables. The hold guards an engine worker's mistakes; it is not a sandbox. Permission prompts and section 2's ten-minute `needs-you` park still apply. False positives (`echo git push`) are held and cost one approval.
- A5. Every end of a held job (valid report, `ready`, gone, any timeout) sets it `escalated`: no retry, no architect case, no `job_done` or `job_failed` input. The strategy hears of the task again from the resumed job's `job_done` (it keys tasks by kind and task number, `spec_driven.js` `onJobDone`).
- A6. `backend.resume(handle, text, job)` gains a third argument, the new job row, so the resumed window gets the new job's `ENGINE_JOB` and report path. A backend that ignores it still works for fix rounds.
- A7. A second hold while the spec already has an open wait is recorded (`hold_skipped` event) and not parked; the worker was told to stop after the first.
- A8. A schedule's command runs under `zsh -c` in the row's `cwd` (default: the toplevel of the checkout where `schedule add` ran, else its cwd) with the row's `env` (default `{}`); `schedule add -- <one word>` stores that word verbatim (so a quoted pipeline works), more words are joined with zsh quoting.
- A9. `schedule add` on an existing active name with the same rule and command prints `unchanged` and exits 0 (idempotent installs); a different rule or command exits 1 `schedule <name> exists: rm it first`.
- A10. `engine wake`'s short pass waits for each run to end, at most the payload's `timeout_min` (default 120) per run; past it the wake exits with the run still open, and a later wake or a running engine records `schedule_ran` from the rc file.
- A11. Migration covers the five plists installed on this machine (read-only probe, 2026-11-24): `com.user.agent-board-dream` (`context dream --all`, 03:30), `com.user.agent-board-discover` (`discover nightly`, 07:00), `com.user.agent-board-scout-poll` (`scout poll`, 06:00), `com.user.agent-board-scout-weekly` (`scout weekly`, Sun 07:00), `com.user.agent-board-scout-weekly-retry` (`scout weekly --retry`, Mon 07:00); each has `EnvironmentVariables` `LANG`, `PATH`, `TMPDIR`, carried into the row's `env`. The ops bot's daily digest has no plist (it runs in the bridge's tick, `board/discord_digest.py`): migrate prints it as `nothing to migrate`. `com.user.agent-board-analytics`, `-restore` and `-discord-watch` are not in the spec's list and stay plists.
- A12. `schedule migrate` refuses (exit 2, `the wake heartbeat is not loaded: run tmux-ctl engine wake install first`) unless `launchctl print gui/<uid>/com.user.agent-board-engine-wake` exits 0, so no job is ever left without a runner. `--dry-run` prints the rows and removals and writes nothing.
- A13. Migrated rows keep the default `skip_if_weekly_usage` 85 (spec 14's default); the scout's own 85% guard is unchanged.

## Finishing (lead, after the merge to `main`; not a plan task)

`schedule migrate` and `wake install` change the live machine, and the installed `~/.local/bin/tmux-ctl` runs `main`: both run only after this branch is merged. The lead runs, from the live checkout on `main`: `tmux-ctl engine wake install`, then `tmux-ctl engine schedule migrate --dry-run`, then `tmux-ctl engine schedule migrate`, then `tmux-ctl engine schedule list` and `tmux-ctl engine wake status`, and puts the four outputs in the ledger. Rollback: `tmux-ctl scout schedule install`, `tmux-ctl discover schedule install`, `tmux-ctl context dream-schedule install` reinstall the old plists; `tmux-ctl engine schedule rm <name>` for each migrated row.

## Interfaces the supervised improvement loop consumes

Its plan (`docs/superpowers/plans/2026-11-21-supervised-improvement-loop.md`, branch `supervised-improvement-loop`) Task 1 rows 3, 10 and 11 check these. Names as built here, with each difference from that plan's wording:

| Its row | Built here | Difference |
| --- | --- | --- |
| 3: `inbox` source `schedule`, `source_id` `<name>@<due_at>` | `engine/lib/engine/schedule.js`, Task 6 | `due_at` is epoch seconds; `run-now` rows are `<name>@now:<epoch>`; a row from another writer needs only `{"command"}` in its payload |
| 10: `engine.json` key `holds`, the default hold list, `engine/bin/hold.js`, `claude/hooks/engine-hold.sh` | `engine/lib/engine/hold.js` (`DEFAULT_HOLDS`, `rulesFor`), `engine/bin/hold.js`, `claude/hooks/engine-hold.sh` (a link to `claude/plugin/scripts/engine-hold.sh`, registered in the plugin's `hooks.json`) | `tool` is a regex over the whole tool name (its `Write\|Edit` works); a path pattern is tested on the absolute and the worktree-relative path; the default list is the `DEFAULT_HOLDS` array its Task 11 extends |
| 11: `tmux-ctl engine schedule add\|list\|rm\|run-now` and `engine wake` | `engine/lib/engine/cli.js`, Tasks 5 to 8 | `schedule add` is idempotent for an identical row (A9); `wake install\|status\|uninstall` manage the heartbeat |

Task 9 writes this table into `docs/superpowers/notes/2026-11-24-engine-part-3-interfaces.md` with file:line references from the built code.

---

### Task 1: Hold rules, the `holds` table and `engine/bin/hold.js`

**Goal:** A process that reads a PreToolUse hook input on stdin decides hold, pass or nothing for an engine worker's call, writing only the `approval` inbox row (hold) or the pass's `used_at` with its event (pass).

**Files:**
- Create: `engine/lib/engine/hold.js`, `engine/bin/hold.js`, `engine/test/engine_hold.test.js`
- Modify: `engine/lib/engine/db.js` (the `holds` table), `engine/lib/engine/policy.js` (`loadConfig` returns `holds`)
- Test: `engine/test/engine_hold.test.js`, `engine/test/engine_db.test.js`

**Acceptance Criteria:**
- [ ] `db.js` `SCHEMA` creates `holds` with the Global Constraints columns; an existing part 2 database gains it on `db.open` (`CREATE TABLE IF NOT EXISTS` is enough; a test opens a database made by the base commit's schema and finds the table, and `rebuild.check` rc 0).
- [ ] `policy.loadConfig(repo).holds` is the `engine.json` `holds` array, else `[]`; a non-array value throws `engine.json holds must be a list`. Because `policyHash` covers the raw file, a changed `holds` changes the hash (one test).
- [ ] `hold.js` (lib) exports `DEFAULT_HOLDS` (the Global Constraints table, ids included), `rulesFor(config)` (defaults then config rules, each compiled once; a config rule whose regex does not compile throws `bad hold rule <index>: <message>`), `match(rules, {tool_name, tool_input, cwd}, worktree)` → the first matching rule or null, `callHash(tool, input)`, `question(tool, input)` (the Hold park question form), and `decide(db, hookInput, env, now)` → `{decision: "none"}` | `{decision: "deny", hold_id, reason}` | `{decision: "allow", hold_id}`.
- [ ] Pattern table test: the plan author's 36 cases pass as listed below, plus these path cases with `ENGINE_WORKTREE=<tmp>/wt` and `cwd` `<tmp>/wt`: `rm -rf build` not held; `rm -rf ../other` held; `rm -rf /tmp/x` held; `rm -r ~/x` held; `rm -f a.txt` not held (not recursive); `cd .. && rm -rf wt2` not held (a known limit, named in the test: the `cd` is not followed, so `wt2` resolves against `cwd` to `<tmp>/wt/wt2`); `Write` of `<tmp>/wt/a.js` not held; `Write` of `<tmp>/elsewhere/a.js` held; `Edit` of `<tmp>/wt/../x.js` held; `NotebookEdit` with `notebook_path` outside held; a worktree path through a symlinked parent (`/tmp` vs `/private/tmp` on macOS) not held.
- [ ] Config rule test: `{"tool": "Write|Edit", "pattern": "claude/orchestrator\\.md$", "outside_worktree": false}` holds an `Edit` of `<wt>/claude/orchestrator.md` (relative match) and not of `<wt>/claude/skills/x/SKILL.md`.
- [ ] `callHash`: same command with two different `description`s → equal; keys in a different order → equal; a different command → different.
- [ ] `decide`, with a database holding a spec `S` and a running job `J` of it: `ENGINE_JOB` unset → `none`, and the engine directory is not created (the lib does not open a database); a non-matching call → `none` with no row written (table counts unchanged); a matching call without a pass → `deny`, exactly one `inbox` row with the Global Constraints shape, no other table changed; the reason equals the exact text. With a pass row (`call_hash` equal, `expires_at` in the future, `used_at` null, `spec` `S`) → `allow`, `used_at` set, one `hold_pass_used` event whose `rows` carry the `holds` row; the same call again → `deny` with a new hold id; a pass with `expires_at` in the past → `deny`; a pass of another spec → `deny`. After each case `rebuild.check` rc 0 (the `new` inbox row is excluded by `rebuild.js`'s PENDING rule).
- [ ] `engine/bin/hold.js`: reads all of stdin as JSON, runs `decide` with `process.env`, prints the Global Constraints hook JSON for `deny` and `allow` and nothing for `none`, exits 0. An exception while a rule matched (database unwritable) prints a `deny` with reason `engine hold check failed: <message>; report status blocked` (fail closed: the call matched a stop-class rule). An exception before any rule matched (unparsable stdin) prints nothing and exits 0. It loads `node:sqlite` only after a rule matched.
- [ ] Mutations named in the test file: "drop the `outside_worktree` check" → `rm -rf build` is held; "hash with `description`" → the two-description case differs; "ignore `expires_at`" → the expired pass allows; "match the pass on hash only" → the other-spec pass allows.

The plan author's 36 cases (`kind`, expected held, command), all run against the patterns above on 2026-11-24 with 0 mismatches:

```
git_push true: git push | git push origin main | git  push | git -C /x push | git -c a=b push | /usr/bin/git push | env A=1 git push | cd x && git push | bash -c 'git push' | echo git push | git --no-pager push
git_push false: git pushd | git status; echo push | gitpush | git log --grep push | "git" push | g\it push
git_reset_hard true: git reset --hard | git reset --hard HEAD~1 | git -C w reset --hard
git_reset_hard false: git reset --soft HEAD~1 | git reset HEAD f; echo --hard
git_branch_force_delete true: git branch -D x | git branch --delete --force x | git branch -d --force x | git branch -df x | git branch -vD x
git_branch_force_delete false: git branch -d x | git branch -a
git_clean true: git clean -fdx | git clean -n
git_clean false: git cleanup
pr_merge true: gh pr merge 3 | glab mr merge 4 | echo x | gh pr merge --squash
pr_merge false: gh pr view 3
```

**Verify:** `cd engine && node --test test/engine_hold.test.js test/engine_db.test.js test/engine_rebuild.test.js`

**Steps:**
- [ ] Write `engine/test/engine_hold.test.js` with the case table above (split each line on ` | `; the `kind` names the rule by id), the path cases, the config case, the hash cases and the `decide` cases. The `decide` tests build the database with `db.open` in `tmpEnv()` and rows put with `db.put` (a spec, a running job). The bin tests spawn `node engine/bin/hold.js` with the env and stdin and parse stdout. Run: they fail (module missing).
- [ ] `db.js`: add `CREATE TABLE IF NOT EXISTS holds(hold_id TEXT PRIMARY KEY, spec TEXT, job TEXT, call_hash TEXT, tool TEXT, input TEXT, created_at REAL, expires_at REAL, used_at REAL);` to `SCHEMA`. `policy.js` `loadConfig`: add `holds` to both returns (validated as a list).
- [ ] `engine/lib/engine/hold.js`: the rules, matcher, hash and `decide`. Paths: `realpathDeep(p)` = `fs.realpathSync` of the deepest existing ancestor joined with the rest. Bash outside words: take `command.slice(m.index + m[0].length)`, cut at the first `;`, `&&`, `||`, `|` or newline, split on whitespace, drop words starting with `-`, strip one level of surrounding quotes, expand a leading `~` to `process.env.HOME`. `decide` reads `ENGINE_JOB`, `ENGINE_PROJECT`, `ENGINE_DIR`, `ENGINE_WORKTREE` from its `env` argument; it sets `process.env.TC_ENGINE_DIR = env.ENGINE_DIR` before `require("./db").open(project)` (the hook's process is its own). The config comes from `policy.loadConfig(<main checkout of ENGINE_WORKTREE>)`: `git -C <worktree> rev-parse --path-format=absolute --git-common-dir`, its parent; a failed read falls back to the defaults alone. The pass lookup and `used_at` write run in one `db.tx`; the job's spec comes from `SELECT spec FROM jobs WHERE id=?`.
- [ ] `engine/bin/hold.js`: `#!/usr/bin/env node`, the stdin read, `decide`, the output, the two error paths.
- [ ] Run the Verify command: all pass. Commit `feat(engine): hold rules, the holds table and hold.js`.

```json:metadata
{"files": ["engine/lib/engine/hold.js", "engine/bin/hold.js", "engine/lib/engine/db.js", "engine/lib/engine/policy.js", "engine/test/engine_hold.test.js", "engine/test/engine_db.test.js"], "verifyCommand": "cd engine && node --test test/engine_hold.test.js test/engine_db.test.js test/engine_rebuild.test.js", "acceptanceCriteria": ["holds table on fresh and part 2 databases, rebuild check 0", "loadConfig returns holds; hash covers them", "hold.js exports DEFAULT_HOLDS, rulesFor, match, callHash, question, decide", "36 bypass cases and the path cases pass", "config Write|Edit rule matches the relative path", "callHash drops description and sorts keys", "decide: none without ENGINE_JOB and no db opened; deny writes one inbox row; pass allows once with hold_pass_used; expired and other-spec passes refused", "bin prints the hook JSON; fails closed only after a match", "mutations named"], "modelTier": "standard"}
```

---

### Task 2: The hook entry, its registration and the worker environment

**Goal:** Every engine worker (started or resumed) runs with the four `ENGINE_*` variables, and the agent-board plugin runs `claude/hooks/engine-hold.sh` before every tool call, which does nothing outside an engine worker and runs `engine/bin/hold.js` inside one.

**Files:**
- Create: `claude/plugin/scripts/engine-hold.sh`, `claude/hooks/engine-hold.sh` (symlink to `../plugin/scripts/engine-hold.sh`, as `claude/hooks/kill-guard.sh` is), `claude/hooks/tests/test-engine-hold.sh`
- Modify: `claude/plugin/hooks/hooks.json`, `bin/tmux-ctl` (the `agent)` case), `engine/lib/engine/backend/claude_tmux.js`, `engine/lib/engine/backend/fake.js`, `engine/lib/engine/cli.js` (`makeBackend` passes the project), `tools/tests/test_plugin.zsh`, `tools/tests/test_agent_dir.zsh`
- Test: `claude/hooks/tests/test-engine-hold.sh`, `tools/tests/test_plugin.zsh`, `tools/tests/test_agent_dir.zsh`, `engine/test/engine_backend.test.js`

**Acceptance Criteria:**
- [ ] `claude/plugin/scripts/engine-hold.sh` (bash, executable): `[[ -n "$ENGINE_JOB" ]] || exit 0` is its first command after the shebang and comment, so a session outside the engine spawns no node; then it resolves the repo as `$AGENT_BOARD_REPO`, else three directories above the script's real path, and `exec node --no-warnings "$repo/engine/bin/hold.js"`. `--scoped` is accepted and changes nothing. A missing `node` or `hold.js` prints the deny JSON with reason `engine hold unavailable: <what>; report status blocked` (fail closed inside an engine worker).
- [ ] `hooks.json` gains, under `PreToolUse`, one entry `{"matcher": "*", "hooks": [{"type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/engine-hold.sh\" --scoped", "timeout": 10}]}`, placed first in the list. `test_plugin.zsh` gains a check of exactly that entry; its existing checks still pass (they read `e["matcher"]`, which this entry has).
- [ ] `test-engine-hold.sh` (pattern of `test-spawn-record.sh`: temp dir, `check name got want`, prints `PASS`/`FAIL` lines, exits 1 on any failure): with `ENGINE_JOB` unset and a stub `node` first on `PATH` that touches a marker, the script exits 0, prints nothing and the marker is absent; with `ENGINE_JOB` set the stub is called with `--no-warnings <repo>/engine/bin/hold.js` and gets the stdin; end to end with the real `node`, a temp `ENGINE_DIR` holding a database with a running job, and the input `{"tool_name":"Bash","tool_input":{"command":"git push"},"cwd":"<wt>","session_id":"s1"}` → stdout's `permissionDecision` is `deny` and the reason starts with `held for approval `; the same with `git status` → empty stdout. Leak check: the real engine directory's listing is unchanged. Mutation named: "drop the ENGINE_JOB guard" → the marker test fails.
- [ ] `bin/tmux-ctl agent`: when `ENGINE_JOB` is set in its environment, the launch line carries `ENGINE_JOB=… ENGINE_PROJECT=… ENGINE_DIR=… ENGINE_WORKTREE=…` (each `${(q)…}`) right after `AGENT_BOARD_REPO=…`; when it is unset the line is byte-identical to today's (the golden line in `test_agent_dir.zsh` still passes). `test_agent_dir.zsh` gains one dry-run check with the four variables set (`TC_AGENT_DRYRUN`) that finds them in the line, and one with `--resume <sid>` that finds both `--resume` and `ENGINE_JOB=`. No help header line is added.
- [ ] `claude_tmux.js`: `createBackend` takes `opts.project`; `launch(window, job, extra, briefPath)` passes `ENGINE_JOB=job.id`, `ENGINE_PROJECT=opts.project`, `ENGINE_DIR=paths.engineDir()`, `ENGINE_WORKTREE=path.resolve(job.worktree)` in the env of the `tmux-ctl agent` call. `resume(handle, text, job)`: when `job` is given, the new window is launched and registered with `{...e.job, ...job, worktree: e.worktree}` (the new job's id and report path), so its `ENGINE_JOB` is the new job's; the window name stays `<held job's window>-r<n>` as today; without it, today's behaviour. `cli.js` `makeBackend` passes `project`.
- [ ] `fake.js` `resume(handle, text, job)` records `job` in its `calls` entry, and a `script` key `resume_fails: true` makes `resume` throw `cannot resume` (Task 3's unresumable case).
- [ ] `engine_backend.test.js` gains: on the scratch tmux server with the existing logging `tmux-ctl` stub, `start` and `resume(handle, text, job)` both pass the four variables with the right job id (the stub logs its env); mutation named: "launch with e.job on resume" → the resumed call's `ENGINE_JOB` is the old id.

**Verify:** `bash claude/hooks/tests/test-engine-hold.sh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_agent_dir.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh && cd engine && node --test test/engine_backend.test.js`

**Steps:**
- [ ] Read `claude/plugin/scripts/kill-guard.sh` (the `--scoped` header form), `tools/tests/test_agent_dir.zsh` (the dry-run seam and the golden line), `claude/hooks/tests/test-spawn-record.sh` (the bash test form) and the `launch` function of `claude_tmux.js`.
- [ ] Write the failing checks: `test-engine-hold.sh`, the two `test_agent_dir.zsh` checks, the `test_plugin.zsh` check, the backend test. Run each: they fail.
- [ ] `engine-hold.sh`:

```bash
#!/usr/bin/env bash
# PreToolUse(*): approval holds for engine workers (engine spec section 13). Outside an engine worker it does nothing.
# Inside one it runs engine/bin/hold.js, which denies a stop-class call until the user approves it once.
# --scoped (the plugin registration) is accepted and changes nothing.
[[ -n "$ENGINE_JOB" ]] || exit 0
deny() { printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"engine hold unavailable: %s; report status blocked"}}\n' "$1"; exit 0; }
repo="$AGENT_BOARD_REPO"
if [[ -z "$repo" ]]; then
  self="$(python3 -I -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}" 2>/dev/null)" || deny "cannot resolve the script path"
  repo="$(cd "$(dirname "$self")/../../.." && pwd)"
fi
[[ -f "$repo/engine/bin/hold.js" ]] || deny "no $repo/engine/bin/hold.js"
command -v node >/dev/null 2>&1 || deny "no node on PATH"
exec node --no-warnings "$repo/engine/bin/hold.js"
```

  Then `ln -s ../plugin/scripts/engine-hold.sh claude/hooks/engine-hold.sh` and `chmod +x claude/plugin/scripts/engine-hold.sh`.
- [ ] `hooks.json`: insert the entry first under `PreToolUse`.
- [ ] `bin/tmux-ctl`, in `agent)`, just before `line=…` (line 594 at base): `eenv=""; [[ -n "$ENGINE_JOB" ]] && eenv=" ENGINE_JOB=${(q)ENGINE_JOB} ENGINE_PROJECT=${(q)ENGINE_PROJECT} ENGINE_DIR=${(q)ENGINE_DIR} ENGINE_WORKTREE=${(q)ENGINE_WORKTREE}"`, and in `line=` replace `AGENT_BOARD_REPO=${(q)AB_REPO} $cmd` with `AGENT_BOARD_REPO=${(q)AB_REPO}${eenv} $cmd`. Plan author's run of this snippet in zsh (2026-11-24): with `ENGINE_JOB` empty the line ends `AGENT_BOARD_REPO=/a\ b/repo claude -x` (unchanged); with it set, `AGENT_BOARD_REPO=/a\ b/repo ENGINE_JOB=s:implement1:1 ENGINE_PROJECT=p ENGINE_DIR=/e\ d ENGINE_WORKTREE=/w claude -x`. (Not a `${line/…/…}` substitution: its pattern is a glob, and a repo path with glob characters would not match.)
- [ ] `claude_tmux.js`, `fake.js`, `cli.js` per the criteria.
- [ ] Run the Verify command: all pass. Commit `feat(hooks): engine-hold hook entry and the engine worker environment`.

```json:metadata
{"files": ["claude/plugin/scripts/engine-hold.sh", "claude/hooks/engine-hold.sh", "claude/hooks/tests/test-engine-hold.sh", "claude/plugin/hooks/hooks.json", "bin/tmux-ctl", "engine/lib/engine/backend/claude_tmux.js", "engine/lib/engine/backend/fake.js", "engine/lib/engine/cli.js", "tools/tests/test_plugin.zsh", "tools/tests/test_agent_dir.zsh", "engine/test/engine_backend.test.js"], "verifyCommand": "bash claude/hooks/tests/test-engine-hold.sh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_agent_dir.zsh && env -u AGENT_BOARD_LEAD zsh tools/tests/test_plugin.zsh && cd engine && node --test test/engine_backend.test.js", "acceptanceCriteria": ["engine-hold.sh exits before node outside an engine worker; fails closed inside one when hold.js is unavailable", "hooks.json PreToolUse matcher * entry first, test_plugin pins it", "hook test end to end: git push denied with a hold id, git status silent, leak check", "tmux-ctl agent passes the four ENGINE_ variables only when ENGINE_JOB is set; golden line unchanged", "claude-tmux start and resume pass the new job's variables", "fake resume records the job and can fail", "mutations named"], "modelTier": "standard"}
```

---

### Task 3: Holds in the core: park, approve, deny, fail, resume

**Goal:** A drained `approval` row ends the held job as `escalated` and parks its spec with the exact call; `approve` writes a one-time pass and resumes the worker's session with the approval text (or starts a fresh worker with the brief, the report and the answer); `deny` resumes with the note and the spec goes on; `fail` fails the spec.

**Files:**
- Modify: `engine/lib/engine/core.js`
- Create: `engine/test/engine_holds_core.test.js`

**Constraints:**
- Spec section 13 as written, with the Global Constraints' hold park, resume texts and pass row, and assumptions A5 to A7.
- The pump's invariant: each new command writes exactly one event with `{cause, idx}`; the hold handler runs inside the drain's transaction for its row (`core.handler`, source `approval`). The answer arrives as part 2's `signal` input, so `coreSignal` handles step `core:hold:<id>` (approve: a pass command, then a resume command; deny: a resume command that also returns the spec to its `prev_state`; fail: part 2's `failed — <note>`).
- The resume is a new job row (`newJob`, same kind, task, tier and model as the held job, detail `{resume_of: <held job>, hold: <hold id>, hold_answer: "approve"|"deny", resume_text: <exact text>}`), dispatched by the existing `dispatch()`: it tries `backend.resume(handleOf(prev), resume_text, <job>)` and falls back to `backend.start` with a brief that `briefFor` extends by a section `## Held call` naming the earlier report path, the call and the answer (approve: "approved: retry the held call exactly as before"; deny: the deny text). No second job of the spec is dispatched while the held job is still `running` (part 2's dispatch gate already holds: the spec is no longer `awaiting_you`).
- A hold for a job that is not `running`, or whose spec is `done`, is dropped with the reason (`job not running`, `spec done`).
- Nothing here changes a strategy file, the waits validation, or the end-of-queue rules: a hold left unanswered at the end of a queue fails the spec as `failed — awaiting you: <question>` like every park (part 2, section 11).

**Acceptance Criteria:**
- [ ] On the fake backend (core driven with a fake `now`), for each default rule a job whose script makes the hook call (the test runs `engine/bin/hold.js` as a child process with the job's `ENGINE_*` env and the call, then ticks): the spec is `awaiting_you`, its open wait has kind `stop_class`, options `approve|deny|fail`, the exact question form, step `core:hold:<id>`; the feed file has a `decision` line whose text contains the call; the job ends `escalated` once its report is written (or on its next `ready`) and its window is closed by part 1's `closeWindows`. A call inside the worktree (`rm -rf build`) produces no row and the job finishes normally.
- [ ] A held job's report `blocked` does not start an architect job and does not retry (A5): no `escalated` event with case `blocked`, no `job_failed`.
- [ ] `approve` (via `engine signal` written as part 2's inbox row): one `holds` row (`expires_at` = answered time + 3600, `used_at` null, spec and job set), one resume job; the fake backend's `calls` hold one `resume` whose handle carries the held job's `session_id` and whose text is exactly `approval <id> granted: retry the held call exactly as before`, with the new job as third argument. Then `hold.js` run with the new job's env and the same call → `allow`; again → `deny` with a new hold id (and the spec parks again).
- [ ] A pass older than one hour (fake `now` advanced 3601 s before the hook runs) → `deny`.
- [ ] `deny` with `--note "use a PR"`: no `holds` row; the resume text is exactly `denied: use a PR. Continue without it, or report blocked.`; the spec is back in its previous state (`running`); without a note the text says `no reason given`.
- [ ] `fail --note "x"`: the spec ends `done` with outcome `failed — x` (part 2's rule), and the held job is not resumed.
- [ ] Unresumable session (fake `resume_fails`, or the held job has no `session_id`): a fresh worker is started (`calls` has a `start` for the resume job), its brief has the `## Held call` section with the earlier report path and the answer; for `approve` the pass still allows the call from the fresh job (bound to the spec).
- [ ] A second `approval` row while the spec's wait is open → `hold_skipped` event, no second wait.
- [ ] Crash and resume: the engine stopped between the `signal` event and the resume job's `job_created`, then restarted (`core.start` on the same database, `resume()`, ticks) → exactly one `holds` row, one resume job and one `resume` call (the pump applies the missing command only).
- [ ] `engine rebuild --check` exits 0 after each case above.
- [ ] Mutations named in the test file: "park without dropping a finished job's row" → the not-running case parks; "drop the pass command on approve" → the resumed call is denied; "keep the spec parked on deny" → the deny case finds `awaiting_you`.

**Verify:** `cd engine && node --test test/engine_holds_core.test.js test/engine_core.test.js test/engine_rebuild.test.js`

```json:metadata
{"files": ["engine/lib/engine/core.js", "engine/test/engine_holds_core.test.js"], "verifyCommand": "cd engine && node --test test/engine_holds_core.test.js test/engine_core.test.js test/engine_rebuild.test.js", "acceptanceCriteria": ["each default rule's call parks the spec with the exact call, stop_class, approve|deny|fail; feed decision line; held job escalated and its window closed", "inside-worktree call not held", "held job's blocked report starts no architect and no retry", "approve: one holds row, resume with the session id and the exact text, pass allows once then holds again", "pass older than 1 h refused", "deny resumes with the note and returns the spec to running", "fail fails the spec", "unresumable session gets a fresh worker with the answer; the pass still applies", "second hold while parked is hold_skipped", "crash between signal and resume: one pass, one resume", "rebuild check 0 after each case", "mutations named"], "modelTier": "frontier"}
```

---

### Task 4: Schedule rules and their next occurrence

**Goal:** `engine/lib/engine/schedule_rules.js` parses the three rule forms and gives the next occurrence after a time, in local time, across DST changes.

**Files:**
- Create: `engine/lib/engine/schedule_rules.js`, `engine/test/engine_schedule_rules.test.js`

**Acceptance Criteria:**
- [ ] `parseRule` accepts exactly `daily HH:MM`, `weekly <Mon|Tue|Wed|Thu|Fri|Sat|Sun> HH:MM`, `every <n>m` (n ≥ 1) and throws on `daily 3:30`, `weekly sun 07:00`, `every 0m`, `daily 24:00`, `hourly`.
- [ ] Under `TZ=America/New_York` (each case runs in a child `node` process with that `TZ`, so the zone is fixed for the process): `daily 03:30` after Tue 2026-11-24 02:00 → same day 03:30, after 03:30 → Wed 03:30; `weekly Sun 07:00` after Tue 2026-11-24 12:00 → Sun 2026-11-29 07:00; `daily 02:30` after 2027-03-14 00:00 (spring forward, 02:30 does not exist) → 2027-03-14 03:30; `daily 01:30` after 2026-11-01 00:00 (fall back, 01:30 occurs twice) → the first 01:30, and the next after that → 2026-11-02 01:30 (runs once); `daily 07:00` after 2026-10-31 08:00 → 25 hours after 2026-10-31 07:00; `every 15m` with anchor 100 after 1000 → 1900, after 50 → 100. These are the plan author's results of running this exact code on 2026-11-24.
- [ ] Mutation named: "compare `t >= after` instead of `t > after`" → the "after 03:30" case returns the same day.

**Verify:** `cd engine && node --test test/engine_schedule_rules.test.js`

**Steps:**
- [ ] Write `engine/test/engine_schedule_rules.test.js`. Each DST case spawns `process.execPath` with `-e` running the module and printing `new Date(t*1000).toString().slice(0, 24)`, with `env: {...process.env, TZ: "America/New_York"}`; local times are built in the child as `new Date(y, mo - 1, d, h, mi).getTime() / 1000`. Expected strings: `Tue Nov 24 2026 03:30:00`, `Wed Nov 25 2026 03:30:00`, `Sun Nov 29 2026 07:00:00`, `Sun Mar 14 2027 03:30:00`, `Sun Nov 01 2026 01:30:00`, `Mon Nov 02 2026 01:30:00`; the 25-hour case compares the difference in hours (25). Run: fails (module missing).
- [ ] Create `engine/lib/engine/schedule_rules.js`:

```js
"use strict";
// Schedule rules (spec section 14): `daily HH:MM`, `weekly <Mon…Sun> HH:MM`, `every <n>m`, in local time.
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// rule text -> {kind: "daily", h, m} | {kind: "weekly", day, h, m} | {kind: "every", minutes}; throws on anything else.
function parseRule(text) {
  const s = String(text).trim();
  let m = /^daily (\d{2}):(\d{2})$/.exec(s);
  if (m) return hm({ kind: "daily" }, m[1], m[2], s);
  m = /^weekly (Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{2}):(\d{2})$/.exec(s);
  if (m) return hm({ kind: "weekly", day: DAYS.indexOf(m[1]) }, m[2], m[3], s);
  m = /^every ([1-9]\d*)m$/.exec(s);
  if (m) return { kind: "every", minutes: Number(m[1]) };
  throw new Error(`bad rule "${s}": daily HH:MM | weekly <Mon…Sun> HH:MM | every <n>m`);
}
function hm(r, h, mm, s) {
  const H = Number(h);
  const M = Number(mm);
  if (H > 23 || M > 59) throw new Error(`bad rule "${s}": time out of range`);
  return { ...r, h: H, m: M };
}

// The first occurrence strictly after `after` (epoch seconds), in local time. For `every`, `anchor` (epoch seconds,
// the row's previous due time) keeps the grid: anchor + k*n minutes; without one the grid starts at `after`.
// A local time that a DST change skips runs one hour later (JS Date rolls 02:30 forward to 03:30); a time that
// occurs twice runs once, at its first occurrence.
function nextAfter(rule, after, anchor) {
  const r = typeof rule === "string" ? parseRule(rule) : rule;
  if (r.kind === "every") {
    const step = r.minutes * 60;
    const base = anchor === undefined || anchor === null ? after : anchor;
    if (base > after) return base;
    return base + (Math.floor((after - base) / step) + 1) * step;
  }
  const d = new Date(after * 1000);
  for (let i = 0; i <= 8; i++) {
    const c = new Date(d.getFullYear(), d.getMonth(), d.getDate() + i, r.h, r.m, 0, 0);
    if (r.kind === "weekly" && c.getDay() !== r.day) continue;
    const t = c.getTime() / 1000;
    if (t > after) return t;
  }
  throw new Error("no next occurrence"); // unreachable: 8 days always hold one
}

module.exports = { DAYS, parseRule, nextAfter };
```

- [ ] Run the Verify command: all pass. Commit `feat(engine): schedule rules and next occurrence`.

```json:metadata
{"files": ["engine/lib/engine/schedule_rules.js", "engine/test/engine_schedule_rules.test.js"], "verifyCommand": "cd engine && node --test test/engine_schedule_rules.test.js", "acceptanceCriteria": ["three rule forms parse; five bad forms throw", "next occurrence for daily, weekly, every with anchor", "spring-forward 02:30 runs at 03:30; fall-back 01:30 runs once", "cases run in a child process with TZ=America/New_York", "mutation named"], "modelTier": "mechanical"}
```

---

### Task 5: Schedule rows and `engine schedule add|list|rm`

**Goal:** Schedules are `timers` rows of kind `schedule` written with an event each, listed and retired from the CLI, and part 1's timer path never fires them.

**Files:**
- Create: `engine/lib/engine/schedule.js` (the row functions; Tasks 6 and 7 add the runner to it), `engine/test/engine_schedule.test.js`
- Modify: `engine/lib/engine/inbox.js` (`moveDueTimers` skips kind `schedule`), `engine/lib/engine/cli.js` (subcommand `schedule`)
- Test: `engine/test/engine_schedule.test.js`, `engine/test/engine_inbox.test.js`

**Acceptance Criteria:**
- [ ] `schedule.add(db, {name, rule, command, skip_if_weekly_usage = 85, cwd, env = {}}, now)`: validates the name and the rule (`schedule_rules.parseRule`), writes the Global Constraints row with `due_at = nextAfter(rule, now)` (anchor `now` for `every`) and one event `schedule_added` carrying it, in one `db.tx`. Returns `{status: "added" | "unchanged"}`; an active row with another rule or command throws `schedule <name> exists: rm it first` (A9); a retired row is replaced.
- [ ] `schedule.list(db)` → active rows (`fired_at IS NULL`) by name, payload parsed. `schedule.rm(db, name, now)` sets `fired_at` with one event `schedule_removed`; an unknown or retired name throws `no schedule <name>`.
- [ ] `inbox.moveDueTimers` selects `kind != 'schedule'`; a test puts a due schedule row and a due retry row and finds only the retry row moved (mutation named: "drop the kind filter" → the schedule row is fired).
- [ ] CLI (`engine schedule …`, project from `--project` or `TC_PROJECT` as every subcommand): `schedule add <name> --rule "<rule>" [--skip-if-weekly-usage <0-100|none>] -- <command…>` prints `added <name>: <rule>, next <local ISO-like time>` or `unchanged <name>`, exit 0; a bad name, rule or missing command exits 2 with the usage; the exists case exits 1. `cwd` is `git rev-parse --show-toplevel` of the caller's cwd, else the cwd. One word after `--` is the command verbatim; more words are joined with zsh-style quoting (each word in single quotes with `'` as `'\''` unless it matches `^[A-Za-z0-9_./:=@%+-]+$`). `schedule list` prints one line per row: `<name>  <rule>  next <YYYY-MM-DD HH:MM>  <command>` (local time), or `no schedules`. `schedule rm <name>` prints `removed <name>`, exit 0; unknown exits 1. `--` handling: `parseArgs` stops at `--` (the words after it are the command, never flags).
- [ ] `rebuild.check` rc 0 after add, add again (unchanged), rm, and add of the retired name.
- [ ] CLI tests spawn `node engine/bin/engine.js` with `TC_ENGINE_DIR` in a temp dir and `--project t`, as `engine_cli.test.js` does.

**Verify:** `cd engine && node --test test/engine_schedule.test.js test/engine_inbox.test.js`

**Steps:**
- [ ] Write the failing tests (library first, then CLI).
- [ ] `schedule.js`: `add`, `list`, `rm`, `shellJoin(words)`; it requires `./db` (`tx`, `put`, `event`) and `./schedule_rules`.
- [ ] `inbox.js`: add `AND kind != 'schedule'` to `moveDueTimers`' select.
- [ ] `cli.js`: add `schedule` to `SUBS`; a `cmdSchedule(args, io)` that splits `args` at the first `--` before `parseArgs`, adds `--rule` and `--skip-if-weekly-usage` to `VALUE_FLAGS`, and dispatches `add|list|rm` (Tasks 7 and 8 add `run-now` and `migrate`).
- [ ] Run the Verify command, then `cd engine && node --test test/engine_cli.test.js` (no regression in the usage line test: update its expected `SUBS` list if it pins it). Commit `feat(engine): schedule rows and engine schedule add|list|rm`.

```json:metadata
{"files": ["engine/lib/engine/schedule.js", "engine/lib/engine/inbox.js", "engine/lib/engine/cli.js", "engine/test/engine_schedule.test.js", "engine/test/engine_inbox.test.js", "engine/test/engine_cli.test.js"], "verifyCommand": "cd engine && node --test test/engine_schedule.test.js test/engine_inbox.test.js", "acceptanceCriteria": ["add writes the timers row and schedule_added; unchanged and exists cases", "list active rows; rm retires with schedule_removed", "moveDueTimers never fires kind schedule (mutation named)", "CLI add|list|rm output and exit codes; -- ends flags; one-word command verbatim", "rebuild check 0 after add, re-add, rm, re-add"], "modelTier": "standard"}
```

---

### Task 6: `engine wake`: due rows, the short pass and the runner

**Goal:** `tmux-ctl engine wake` moves every due schedule row of every project database to its next future occurrence with one `schedule` inbox row per due row, and, for a project with no engine running, takes the lock, drains only `schedule` rows, runs each in a window `sched·<name>` of `<project>-bg`, records `schedule_ran` with its exit code, releases the lock and exits.

**Files:**
- Create: `engine/lib/engine/wake.js`, `engine/test/engine_wake.test.js`
- Modify: `engine/lib/engine/schedule.js` (`moveDue`, `handleRow`, `runIntents`, `finishRuns`, `weeklyUsage`), `engine/lib/engine/inbox.js` (`drain` filter), `engine/lib/engine/steps.js` (`CHECKS.schedule_run`), `engine/lib/engine/core.js` (export `takeLock`), `engine/lib/engine/cli.js` (subcommand `wake`)
- Test: `engine/test/engine_wake.test.js`

**Acceptance Criteria:**
- [ ] `schedule.moveDue(db, now)`: for each active schedule row with `due_at <= now`, one `db.tx`: the row's `due_at` becomes `nextAfter(rule, now, <old due_at for every>)` (missed occurrences collapse into one), one `schedule` inbox row (`source_id` `<name>@<old due_at>`, Global Constraints payload), one event `schedule_due` carrying the timers row and the inbox row. A row due three days ago yields one inbox row and a `due_at` in the future.
- [ ] `inbox.drain(db, handle, now, {source})`: with `source` given, only `new` rows of that source are handled, oldest first; without it, today's behaviour (a test with one `user` and one `schedule` row drains only the second). Inside its transaction `drain` re-reads the row and skips it unless it is still `new`, so two processes draining at once (a `run-now` racing a wake) handle each row once: a test opens two connections, takes the next id in both, drains with the first and then the second, and finds one `schedule_run` step and one `inbox_schedule` event (mutation named: "drop the re-check" → two events). Repeats are already one row (`INSERT OR IGNORE` on `(source, source_id)`); a row for a retired schedule still runs once (it was due when inserted).
- [ ] `schedule.handleRow(db, row, ctx)` (runs inside the drain's transaction): `force` absent and weekly usage ≥ the row's `skip_if_weekly_usage` → one `schedule_skipped` event (`reason` `weekly usage <n>% >= <limit>%`); a window `sched·<name>` already open in `<project>-bg` → `schedule_skipped` with reason `still running`; else a `steps` row kind `schedule_run` at `intent` (Global Constraints key and facts `{name, command, cwd, env, window, rc_file, log}`) with its `step_intent` event. A payload without `command` is dropped (`no command`).
- [ ] `schedule.runIntents(db, ctx)`: for each `schedule_run` step at `intent`: create `<project>-bg` when absent (Global Constraints), open the window with the run line, finish the step (`done`, result adds `started_at`) and write `schedule_started`. `schedule.finishRuns(db, ctx)`: for each `schedule_run` step `done` with no `schedule_ran` event for its key, whose rc file exists → one `schedule_ran {name, key, rc, log}`.
- [ ] `steps.CHECKS.schedule_run`: the rc file exists, or the window is open in `<project>-bg` → `done`; else `not_done`; tmux unreachable → `unknown`.
- [ ] `wake.run({now, io})`: for each `<engineDir>/*.sqlite` (project = basename): `moveDue`; then, if the project's lock is held by a live pid, nothing more (the engine drains on its tick, Task 7); else `core.takeLock(project)`, `steps.reconcile` of `schedule_run` rows only, `drain` with `{source: "schedule"}` and `handleRow`, `runIntents`, then `finishRuns` every second until every run of this pass has `schedule_ran` or its `timeout_min` passed (A10), then remove the lock. Prints one line per project: `<project>: <n> due, <m> ran, <k> skipped` (or `<project>: engine running, <n> due`). Exit 0; an error in one project prints `<project>: error: <message>`, the others still run, exit 1.
- [ ] CLI: `engine wake` (no project needed) runs `wake.run`.
- [ ] On a scratch tmux server (`TMUX_DASH_TMUX_ARGS="-L <sock> -f /dev/null"`, short `TMUX_TMPDIR`), a temp engine dir with project `p` and a row `echo1` rule `every 1m` command `echo hi; exit 3`, `due_at` in the past: `engine wake` creates `p-bg` (with `@tc_bg` 1), runs the window, records `schedule_ran` rc 3 with the log containing `hi`, leaves the lock file absent, and the row's `due_at` in the future; a second `engine wake` at once runs nothing (`0 due`). A row due 3 days ago runs once. A fixture tap file with `seven_day.used_percentage` 91 skips a row with limit 85 (`schedule_skipped`), and a `run-now`-style row with `force: true` runs anyway. With the lock file holding a live pid (the test process's own pid), `engine wake` inserts the inbox row, writes no `schedule_run` step and opens no window. `rebuild.check` rc 0 after each. Leak check: the real engine dir unchanged, and the real tmux server (default socket) has no session `p-bg`.
- [ ] Mutations named: "skip the collapse (one row per missed occurrence)" → the 3-days case yields three inbox rows; "run even when the lock is held" → the lock case opens a window.

**Verify:** `cd engine && node --test test/engine_wake.test.js test/engine_schedule.test.js test/engine_steps.test.js`

**Steps:**
- [ ] Write `engine/test/engine_wake.test.js` with the scratch server (`engine_helpers.scratchTmux()`), the rows, the tap fixture under `<TC_STATE>/statusline/x.json` (`{"received_at": <now>, "rate_limits": {"seven_day": {"used_percentage": 91, "resets_at": <now+86400>}}}`), and the CLI spawned with `TMUX_DASH_TMUX_ARGS`. Run: fails.
- [ ] `inbox.drain` filter; `core.js` `module.exports` adds `takeLock`; `steps.js` `CHECKS.schedule_run` (its tmux call uses `ctx.tmuxArgs` like `tmuxList`).
- [ ] `schedule.js`: `weeklyUsage()` per Global Constraints; `moveDue`, `handleRow`, `runIntents`, `finishRuns`. The run line, built in zsh syntax and passed as the window's command: `zsh -c <line>` where `line` = `` `( ${envAssignments} ${command} ) 2>&1 | tee ${q(log)}; print -r -- ${pipestatus[1]} > ${q(rc)}` `` with `q` the zsh quoting of Task 5 and `envAssignments` `export K=V;` per env key. `tmux new-window -d -t =<project>-bg: -n sched·<name> -c <cwd> zsh -c <line>` with argv arrays.
- [ ] `wake.js` and the `wake` subcommand in `cli.js` (no `--project` needed; `wake install|status|uninstall` are Task 8's).
- [ ] Run the Verify command: all pass. Commit `feat(engine): engine wake, the short pass and the schedule runner`.

```json:metadata
{"files": ["engine/lib/engine/wake.js", "engine/lib/engine/schedule.js", "engine/lib/engine/inbox.js", "engine/lib/engine/steps.js", "engine/lib/engine/core.js", "engine/lib/engine/cli.js", "engine/test/engine_wake.test.js"], "verifyCommand": "cd engine && node --test test/engine_wake.test.js test/engine_schedule.test.js test/engine_steps.test.js", "acceptanceCriteria": ["moveDue collapses missed occurrences into one inbox row and a future due_at, with schedule_due", "drain source filter; drain re-checks state new so a row is handled once across two processes", "handleRow: usage skip, still-running skip, schedule_run intent step", "runIntents opens sched·<name> in <project>-bg, finishRuns records schedule_ran with the rc", "schedule_run step check", "wake: lock held inserts only; no lock runs the short pass and releases the lock", "scratch tmux e2e: rc 3 recorded, second wake runs nothing, 3-days-missed runs once, 91% skips, force runs, leak check", "rebuild check 0", "mutations named"], "modelTier": "standard"}
```

---

### Task 7: Schedule rows in a running engine, `schedule run-now`, and resume

**Goal:** A running engine drains `schedule` rows on its tick without blocking it, records each run's end on a later tick, keeps runs out of the queue's concurrency, and `schedule run-now <name>` runs a schedule at once whether or not an engine is running.

**Files:**
- Create: `engine/test/engine_schedule_core.test.js`
- Modify: `engine/lib/engine/core.js`, `engine/lib/engine/cli.js`, `engine/lib/engine/schedule.js` (only if a helper is missing)
- Test: `engine/test/engine_schedule_core.test.js`

**Acceptance Criteria:**
- [ ] `core.handler`: source `schedule` → `schedule.handleRow(db, row, sctx)` (sctx: `{project, tmuxArgs, now}`); source `approval` stays Task 3's. `tick()` calls `schedule.runIntents` and `schedule.finishRuns` after `advance()` and before `dispatch()`; neither waits for a command to end. `NEVER_PARK` gains `schedule_run` (a run the check cannot tell is failed, never parks a spec: it has no spec).
- [ ] A scheduled run is not a job: during a fake-backend spec run with a job `running`, a drained schedule row opens its window on the same tick (the test's scratch tmux server) and the spec's next job is dispatched as it would be without it (same `dispatched` events in the same order as a run without the schedule row, compared by kind and job id).
- [ ] The queue's end (`finish()`) is not delayed by an open run: `atEnd` ignores `schedule_run` steps; a run still open when the engine stops is recorded by the next `engine wake` (`finishRuns` there) or the next engine tick.
- [ ] `resume()`: `steps.reconcile` already covers `schedule_run` rows (Task 6's check); a row the check calls `not_done` stays at `intent` and the next tick's `runIntents` opens it once (a test kills between `step_intent` and the window: one window, one `schedule_started`).
- [ ] `schedule run-now <name>`: inserts the `run-now` inbox row (Global Constraints, `force: true`); with no engine running it then runs `wake.run` for that project only (so the command runs now and the CLI waits like the short pass); with an engine running it prints `queued for the running engine` and exits 0. An unknown or retired name exits 1 `no schedule <name>`.
- [ ] `rebuild.check` rc 0 after each case; leak check as in Task 6.
- [ ] Mutation named: "drain schedule rows after dispatch" → the same-tick window test finds the window one tick late; "count schedule_run in atEnd" → the end-of-queue test does not finish.

**Verify:** `cd engine && node --test test/engine_schedule_core.test.js test/engine_core.test.js`

**Steps:**
- [ ] Write the failing tests; the core runs on the fake backend with the scratch tmux server's args passed as `tmuxArgs` (the schedule runner uses real tmux; jobs use the fake backend).
- [ ] `core.js`: the handler branch, the two tick calls, `NEVER_PARK`, `atEnd` unchanged in shape (it reads specs and inbox rows only: confirm with the test, then leave it).
- [ ] `cli.js`: `schedule run-now`.
- [ ] Run the Verify command: all pass. Commit `feat(engine): schedule rows in the running engine and schedule run-now`.

```json:metadata
{"files": ["engine/lib/engine/core.js", "engine/lib/engine/cli.js", "engine/lib/engine/schedule.js", "engine/test/engine_schedule_core.test.js"], "verifyCommand": "cd engine && node --test test/engine_schedule_core.test.js test/engine_core.test.js", "acceptanceCriteria": ["running engine drains schedule rows and opens the window on the same tick without blocking", "a schedule run does not change job dispatch order", "queue end not delayed by an open run; a later wake records it", "kill between intent and window: one window after resume", "run-now: runs at once without an engine, queues with one, unknown name exit 1", "schedule_run never parks", "rebuild check 0, leak check", "mutations named"], "modelTier": "standard"}
```

---

### Task 8: The wake heartbeat plist and `schedule migrate`

**Goal:** `tmux-ctl engine wake install|status|uninstall` manage the launchd heartbeat, and `tmux-ctl engine schedule migrate [--dry-run]` turns the earlier agent-board LaunchAgents into schedule rows with the same times, commands, working directory and environment, then unloads and removes each plist as a `plist_remove` step.

**Files:**
- Create: `engine/lib/engine/launchd.js`, `engine/test/engine_migrate.test.js`
- Modify: `engine/lib/engine/cli.js`, `engine/lib/engine/steps.js` (`CHECKS.plist_remove`)
- Test: `engine/test/engine_migrate.test.js`

**Acceptance Criteria:**
- [ ] `launchd.js` seams, as `board/scout_schedule.py`: `HOME` (plists under `$HOME/Library/LaunchAgents`), `AS_LAUNCHCTL` (the launchctl command, split on spaces), `AS_PLUTIL` (default `plutil`), `AS_BIN_DIR` (the fallback tmux-ctl directory). Off macOS (`process.platform !== "darwin"`) each command prints `macOS only` and exits 2.
- [ ] `wake install`: writes `com.user.agent-board-engine-wake.plist` (Global Constraints keys; XML written by `launchd.plistXml(obj)` for strings, integers, booleans, arrays and dicts, escaped; a test round-trips it through `plutil -convert json -o -` and compares), backs up an existing one to `<name>.bak-YYYYMMDD`, runs `launchctl bootout gui/<uid>/<label>` (failure ignored) then `bootstrap gui/<uid> <plist>`; a failed bootstrap exits 1 with launchctl's message. `wake status`: `loaded` or `not loaded` (`launchctl print`), then `last wake: <the newest schedule_due or schedule_ran event time over every project database, or none>`. `wake uninstall`: bootout and remove, `removed <path>` or `not installed`.
- [ ] `schedule migrate`: refuses with exit 2 and A12's message unless the heartbeat is loaded (`--dry-run` skips this check). For each label of A11 whose plist exists: read it with `plutil -convert json -o - <plist>`; rule from `StartCalendarInterval` (`{Hour, Minute}` → `daily HH:MM`; with `Weekday` 0 or 7 → `Sun`, 1-6 → `Mon`-`Sat`; any other shape is reported `cannot migrate <label>: <why>` and left installed); command from `ProgramArguments` with element 0 replaced by `tmux-ctl` and the rest quoted as Task 5's join; `cwd` from `WorkingDirectory`; `env` from `EnvironmentVariables`; name `dream`, `discover-nightly`, `scout-poll`, `scout-weekly`, `scout-weekly-retry`. Then `schedule.add` (an identical row is `unchanged`), then a `steps` row `plist_remove:<label>` (`steps.run`): `launchctl bootout gui/<uid>/<label>`, then unlink the plist. Prints one line per label: `migrated <label> -> <name> (<rule>)`, `already migrated <label>`, `not installed <label>`, and the line `ops digest: no launchd job (runs in the bridge's tick): nothing to migrate`. `--dry-run` prints the same lines prefixed `would ` and writes nothing (no database file is created when none existed).
- [ ] `steps.CHECKS.plist_remove`: done when the plist is gone and `launchctl list` (the seam) does not print the label; `unknown` when launchctl fails. Resume never parks a spec on it (no spec): it joins `NEVER_PARK`.
- [ ] Tests with a temp `HOME` holding fixture plists for the five labels (written by `launchd.plistXml` with the shapes of A11's probe: `ProgramArguments` `["/h/.local/bin/tmux-ctl", "scout", "weekly", "--retry"]`, `StartCalendarInterval` `{"Hour": 7, "Minute": 0, "Weekday": 1}`, `WorkingDirectory`, `EnvironmentVariables` `{LANG, PATH, TMPDIR}`) plus one with `StartInterval` only, and a logging launchctl stub (exit 0 for `print` of the wake label, logs every call): migrate yields the five rows with the right rules, commands, cwd and env, five `plist_remove` steps `done`, the five plists gone, the odd one left with its `cannot migrate` line; a second migrate prints `already migrated` or `not installed` and changes nothing; the stub answering `print` with exit 113 → exit 2 and no row. Kill between the `plist_remove` intent and the unlink: resume's reconcile reruns it once (one bootout per label in the log after the rerun). `rebuild.check` rc 0.
- [ ] Real state, read-only: one test runs `schedule migrate --dry-run` with the real `HOME` (reading the real `~/Library/LaunchAgents`), a temp `TC_ENGINE_DIR` and `AS_LAUNCHCTL` pointing at a stub that fails every call except `list`, and prints its lines; it asserts each output line has one of the known forms and that the real plists' mtimes are unchanged after the run. Skipped with a printed reason off macOS.
- [ ] Leak check: no file under the real `~/Library/LaunchAgents` changed (mtimes before and after), the real engine directory unchanged.
- [ ] Mutations named: "skip the heartbeat check" → the exit-113 case writes rows; "remove before add" → the kill-between test loses a row.

**Verify:** `cd engine && node --test test/engine_migrate.test.js test/engine_steps.test.js`

**Steps:**
- [ ] Write the failing tests (fixtures and the stub launchctl as a small shell script in the test's temp dir).
- [ ] `launchd.js`: `plistXml`, `readPlist` (plutil), `launchctl(args)`, `labelLoaded(label)`, `install`, `status`, `uninstall`, `migrate({dryRun})`.
- [ ] `steps.js` `CHECKS.plist_remove`; `core.js` `NEVER_PARK` gains `plist_remove` (one word; the file is already in Task 3's and 7's scope).
- [ ] `cli.js`: `wake install|status|uninstall` and `schedule migrate [--dry-run]` (`--dry-run` to `BOOL_FLAGS`).
- [ ] Run the Verify command: all pass. Commit `feat(engine): wake heartbeat install and schedule migrate`.

```json:metadata
{"files": ["engine/lib/engine/launchd.js", "engine/lib/engine/cli.js", "engine/lib/engine/steps.js", "engine/lib/engine/core.js", "engine/test/engine_migrate.test.js"], "verifyCommand": "cd engine && node --test test/engine_migrate.test.js test/engine_steps.test.js", "acceptanceCriteria": ["wake install writes the heartbeat plist (StartInterval 900, RunAtLoad) and bootstraps it; status and uninstall", "migrate refuses unless the heartbeat is loaded; dry-run writes nothing", "five fixture plists become rows with the same rule, command, cwd and env; plist_remove steps done; odd shape left installed", "second migrate changes nothing", "kill between intent and unlink reruns once", "read-only dry run over the real LaunchAgents, mtimes unchanged", "leak check", "mutations named"], "modelTier": "standard"}
```

---

### Task 9: Docs: install, architecture and the interface note

**Goal:** The install guide says how to turn the wake heartbeat on and migrate, the architecture page describes holds and schedules, and a note gives the supervised improvement loop's Task 1 the file:line of each interface it checks.

**Files:**
- Modify: `docs/INSTALL.md`, `docs/ARCHITECTURE.md`
- Create: `docs/superpowers/notes/2026-11-24-engine-part-3-interfaces.md`

**Acceptance Criteria:**
- [ ] `docs/INSTALL.md`, next to the other `schedule install` blocks, a block with the three lines `tmux-ctl engine wake install`, `tmux-ctl engine wake status`, `tmux-ctl engine wake uninstall`, one line each on what it does, then `tmux-ctl engine schedule migrate --dry-run` and `tmux-ctl engine schedule migrate` with one sentence: migrate moves the dream, discover and scout LaunchAgents into engine schedule rows and needs the wake heartbeat loaded first.
- [ ] `docs/ARCHITECTURE.md`, in its engine section, two paragraphs: approval holds (the hook, the rules and `engine.json` `holds`, park, one-time pass, resume) and schedules (timers rows, `engine wake`, `sched·<name>` windows, `schedule add|list|rm|run-now|migrate`), each naming its files.
- [ ] The note has the table `| Its row | Interface | Where (file:line) | Difference from its wording |` with rows 3, 10 and 11 of the supervised improvement loop plan's Task 1, filled from the built code (`grep -n` each symbol; the plan's "Interfaces the supervised improvement loop consumes" section is the starting text), and a section `## Payload contract of a schedule row from another writer` quoting the Global Constraints rule.

**Verify:** `grep -c 'engine wake install' docs/INSTALL.md && grep -c 'engine-hold' docs/ARCHITECTURE.md && grep -cE '^\| (3|10|11) ' docs/superpowers/notes/2026-11-24-engine-part-3-interfaces.md`

**Steps:**
- [ ] Read the two docs' engine and schedule sections; write the additions in their style.
- [ ] Write the note: for each row run `grep -n` for its symbols (`source === "schedule"`, `DEFAULT_HOLDS`, `function rulesFor`, `cmdSchedule`, `wake`) and cite the lines.
- [ ] Run the Verify command: three counts, each at least 1 (the last is 3). Commit `docs(engine): holds, schedules and the wake heartbeat`.

```json:metadata
{"files": ["docs/INSTALL.md", "docs/ARCHITECTURE.md", "docs/superpowers/notes/2026-11-24-engine-part-3-interfaces.md"], "verifyCommand": "grep -c 'engine wake install' docs/INSTALL.md && grep -c 'engine-hold' docs/ARCHITECTURE.md && grep -cE '^\\| (3|10|11) ' docs/superpowers/notes/2026-11-24-engine-part-3-interfaces.md", "acceptanceCriteria": ["INSTALL block for wake install|status|uninstall and migrate with the heartbeat precondition", "ARCHITECTURE paragraphs for holds and schedules naming their files", "interface note with rows 3, 10, 11 and file:line from the built code, plus the payload contract"], "modelTier": "mechanical"}
```

---

### Task 10: Full suites

**Goal:** Every suite of the repo passes on the branch.

**Files:**
- none (fixes, if any, go in the files of the task that broke the suite, as a `fix(…)` commit)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh` with `AGENT_BOARD_LEAD` unset exits 0, or 4 (every job passed, over the time budget: accepted on this machine).
- [ ] `cd engine && node --test test/*.test.js` summary shows `# fail 0`. If `engine_resume.test.js` times out under load, it is run alone with `--test-timeout=300000` and that run's summary is the one reported (shared context: its kill matrix is load-sensitive).
- [ ] The report quotes each runner's own summary line and exit code (no `tail` of a loop).

**Verify:** `env -u AGENT_BOARD_LEAD zsh tools/tests/all.zsh; rc=$?; [ $rc -eq 0 ] || [ $rc -eq 4 ]`

**Steps:**
- [ ] Run `env -u AGENT_BOARD_LEAD zsh tools/tests/all.zsh > /tmp/p3-all.txt 2>&1; echo rc=$?` through `tmux-ctl run -t 900 tests` (the shared context's way to keep the full verdict), then read the summary line and rc from the file.
- [ ] Any failure: find the task that caused it, fix it in that task's files, commit `fix(<scope>): …`, rerun.

```json:metadata
{"files": [], "verifyCommand": "env -u AGENT_BOARD_LEAD zsh tools/tests/all.zsh; rc=$?; [ $rc -eq 0 ] || [ $rc -eq 4 ]", "acceptanceCriteria": ["all.zsh exits 0 or 4 with AGENT_BOARD_LEAD unset", "engine node suite fail 0 (engine_resume alone with a longer timeout if load-bound)", "summary lines and exit codes quoted"], "modelTier": "mechanical"}
```

---

### Task 11: Real run, part 3

**Goal:** One real Claude worker under the engine is held on a real `git push` by the real hook, the spec parks with the exact call, `engine signal approve` resumes the real session and the push goes through once; and one real `engine wake` runs a due schedule row in a real `<project>-bg` window; both recorded in a note.

**Files:**
- Create: `docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md`

**Acceptance Criteria:**
- [ ] Setup, all scratch: a clone of this repo at the branch head in a temp dir with a local bare repo as `origin`; a scratch tmux server (`-L p3real -f /dev/null`, short `TMUX_TMPDIR`) with one session `p3real`; `TC_ENGINE_DIR`, `TC_STATE` in temp dirs; a one-task plan committed in the clone whose task tells the worker to commit one file and run `git push origin HEAD`, with `verifyCommand` `git ls-remote origin | grep -q .` and `modelTier` `mechanical` (Haiku). `engine run <spec> --integration keep` from inside the scratch session, backend `claude-tmux`.
- [ ] Observed and quoted in the note (each with the command that showed it): the worker's pane shows the deny reason `held for approval <id>…`; `engine status --waiting` shows the question `Bash: git push origin HEAD` (or the worker's exact command) with options `approve|deny|fail` and the `I recommend: deny (medium)` line; after `engine signal <spec> approve`, a window `<slug>·implement1-r1` (or the fresh-worker window) opens, `git ls-remote origin` shows the pushed sha, the `holds` row has `used_at` set, and a second push attempt in that session (if the worker makes one) is held again; `engine rebuild --check` exits 0 at the end.
- [ ] Schedule part: `engine schedule add realecho --rule "every 1m" -- 'echo real-wake; date'` with `--project p3real`, the row's `due_at` moved into the past with one `UPDATE` through `node -e` (documented in the note), then `engine wake` with `TMUX_DASH_TMUX_ARGS="-L p3real -f /dev/null"`: the note quotes the wake's line, `tmux -L p3real list-windows -t =p3real-bg` while it runs, the `schedule_ran` event (rc 0) and the log's first line `real-wake`.
- [ ] Real state, read-only: the note quotes `tmux-ctl engine schedule migrate --dry-run` run with the real `HOME`, a temp `TC_ENGINE_DIR` and the stub launchctl of Task 8 (`would migrate …` for each installed label), and the real `~/Library/LaunchAgents` listing before and after (unchanged).
- [ ] Cleanup: the scratch server killed (`kill-server` on `-L p3real`), temp dirs removed, `ps` shows no leftover `claude` process started by the run (by its pid, recorded at start). The note ends with `## Result` saying pass or what failed. If a real Claude session cannot start (auth, network), the task reports `blocked` with the pane text, not a fake pass.

**Verify:** `test -f docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md && grep -c '^## Result' docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md && grep -c 'held for approval' docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md && grep -c 'schedule_ran' docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md`

**Steps:**
- [ ] Read part 2's real-run note (`docs/superpowers/notes/2026-11-24-engine-part-2-real-queue.md`) for how its scratch run was set up; differences here: one spec, `engine run` not a queue, the `claude-tmux` backend with a real Haiku worker, and a local bare remote.
- [ ] Build the scratch clone and plan; start the scratch server with `-f /dev/null`; run `engine run` in a window of it under `perl -e 'alarm 1800; exec @ARGV'` (macOS has no `timeout`).
- [ ] Observe and record each item; answer the park with `engine signal … approve` from a second window.
- [ ] Run the schedule part and the read-only dry run.
- [ ] Clean up by pid and server socket; write the note; run the Verify command (four counts ≥ 1). Commit `docs(engine): part 3 real run`.

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md"], "verifyCommand": "test -f docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md && grep -c '^## Result' docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md && grep -c 'held for approval' docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md && grep -c 'schedule_ran' docs/superpowers/notes/2026-11-24-engine-part-3-real-run.md", "acceptanceCriteria": ["real Haiku worker's git push denied by the real hook with a hold id", "status --waiting shows the exact call, options and deny recommendation", "approve resumes the session; push reaches the bare remote once; pass used; rebuild check 0", "real engine wake runs a due row in <project>-bg, schedule_ran rc 0, log quoted", "read-only migrate dry run over the real LaunchAgents, listing unchanged", "cleanup by pid and socket; Result section; blocked, not faked, if Claude cannot start"], "modelTier": "standard"}
```
