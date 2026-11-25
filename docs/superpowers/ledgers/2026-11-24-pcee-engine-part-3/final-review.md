# Final whole-branch review: engine part 3 (`01bfb7a..fc0e59c`)

Reviewer: finalrev. Read-only; nothing edited or committed except this file.

**Verdict: ready after fixes.** The code can merge once C1 and I1 are fixed (or the plan's "Finishing" step is held back until they are): both live in the launchd path, which no test and no real run has exercised, and the Finishing step removes five live LaunchAgents on top of it. The holds half is in good shape.

How I reviewed: read every production file changed (`hold.js`, `bin/hold.js`, `engine-hold.sh`, `schedule.js`, `schedule_rules.js`, `wake.js`, `launchd.js`, and the diffs of `core.js`, `cli.js`, `db.js`, `inbox.js`, `steps.js`, `policy.js`, both backends, `bin/tmux-ctl`, `hooks.json`) in full; skimmed the test files by grep for fixtures, seams and leak checks rather than reading all ~2,300 test lines; ran read-only probes on this machine (listed under each finding). I did not rerun the suites.

## Strengths

- The hold is fail-closed where it matters: a bad config rule keeps the defaults (`hold.js:119-123`), a database error after a rule matched denies (`bin/hold.js:20`), a missing `hold.js` or `node` denies (`engine-hold.sh:12-13`). `node:sqlite` is loaded only after a rule matched, so an ordinary tool call costs no database open.
- The pass is bound to call hash and spec, written by the core and consumed by the hook in one transaction with its event (`hold.js:136-145`); `rebuild --check` covers it (`core.js` `PK.holds`).
- The deny ruling (spec leaves the park inside the `signal` event, `core.js:610-613`) is right: it closes a crash window the brief's version had.
- Migrate writes the schedule row before the plist goes, and a reinstalled plist gets a new step key (`launchd.js:203-208`), so a kill mid-way loses no job definition.
- `db.js` first-open race fix is narrow (only `duplicate column name`, only lock/busy on the WAL switch) and has a test that fails on the old code.
- The real run found and fixed a load-bearing bug (report path after a hold resume) that every unit test had passed.
- Tests run the deployed artefacts: `bin/hold.js` as a child process, the real `engine-hold.sh` with real node and a real `git init` worktree, real `plutil`, a scratch tmux server. Leak checks are present in each file that could reach real state.

## Issues

### Critical

**C1. The wake heartbeat cannot start on this machine: `node` is not on its PATH.** `engine/lib/engine/launchd.js:70`
- The plist's PATH is fixed to `~/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`. `bin/tmux-ctl:804` does `command -v node || die`. Here `node` exists only at `~/Library/Python/3.14/bin/node` (`which -a node`; none in `/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`, `/usr/bin`).
- Probe run: `env -i HOME=$HOME LANG=en_US.UTF-8 PATH=<that PATH> ./bin/tmux-ctl engine bogus` printed `tmux-ctl: engine: node >= 22.13 is required`, rc 2.
- Why it matters: `wake install` still bootstraps and prints `installed`; `migrate`'s guard (`launchd.js:177`, `launchctl print` exits 0) only proves the job is *loaded*, so it passes; the five plists are removed; every 15 minutes the heartbeat exits 2. Dream, discover and the three scout jobs then have no runner, silently. `wake status` prints `loaded` / `last wake: none`, which is also what a healthy install prints right after migrate. This is exactly the outcome A12 promises cannot happen.
- Fix: put `path.dirname(process.execPath)` (the node that ran `wake install`) at the front of the plist PATH, and make the migrate guard prove the heartbeat *ran*: e.g. `wake` writes a small `wake_ran` marker (file or event) each pass, and migrate refuses unless one is newer than the plist; or parse `last exit code = 0` from `launchctl print`. Add a test for the PATH line. See merge gate G1.

### Important

**I1. A launchd wake talks to tmux's default socket, not the live `agent-board` server.** `engine/lib/engine/wake.js:54`, `engine/lib/engine/schedule.js:70-71`, `bin/tmux-ctl:856-858`
- The engine takes its tmux server only from `TMUX_DASH_TMUX_ARGS`; `schedule.tmuxRun` also blanks `TMUX`. The live server is `-L agent-board` (this session: `TMUX=/private/tmp/tmux-503/agent-board,…`, `TMUX_DASH_TMUX_ARGS=-L agent-board -f …/config/tmux.conf`). The heartbeat plist carries neither variable and `tmux-ctl engine` does not export its own resolution (`tc_tmux_args_str`).
- Result under launchd (from reading the code, not run): `has-session` fails on the default socket, `new-session` starts a second, plain tmux server that loads `~/.tmux.conf` (resurrect and continuum plugins, save interval 15), and every scheduled run happens in an `agent-board-bg` there. The runs are invisible to the board and the Activity drawer, and a stray server stays up. It also contradicts the Global Constraint "a window `sched·<name>` in session `<project>-bg`" as the user sees it. I did not verify whether the stray server's continuum save overwrites the resurrect state the user relies on; treat that as an open risk.
- The real run used `TMUX_DASH_TMUX_ARGS='-L p3real -f /dev/null'`, so it never met this.
- Fix: in `bin/tmux-ctl` `engine)`, `export TMUX_DASH_TMUX_ARGS="${TMUX_DASH_TMUX_ARGS:-$(tc_tmux_args_str)}"` before `exec node` (one resolver, as `_tc_bins.zsh` intends), or write it into the plist. One test with `TMUX` unset.

**I2. `removeAct` unlinks the plist when `bootout` failed (Task 8 deferred minor): fix before merge.** `engine/lib/engine/launchd.js:153-157`
- A failed bootout (launchd's `Boot-out failed: 5: Input/output error` is common) leaves the job loaded in memory with its plist gone. The step is recorded `done`, migrate prints `migrated`, and the job then runs twice a day (launchd and the schedule row) until logout: two dreams, two scout polls with their Discord posts and usage. `CHECKS.plist_remove` would catch it (`launchctl list` still prints the label) but only runs on an engine resume, and by then the step is `done`, so it is never looked at.
- Fix (small): after bootout, if `labelLoaded(label)` is still true, throw; the step fails, the plist stays, migrate prints `cannot migrate <label>: still loaded`. One test with the stub's `print` rc 0 after bootout. See merge gate G2 as the check either way.

**I3. `rm -r` outside the worktree is missed for the most likely forms.** `engine/lib/engine/hold.js:19, 59-67`
- Probe (`hold.match` with the default rules): not held: `rm -rf $HOME/foo`, `rm -rf "$HOME/foo"`, `rm -rf ${TMPDIR}x`, `rm -r "/tmp/a b"` (the quoted word is split on the space, so `unquote` never fires and it resolves inside the worktree), `rm -f -r /tmp/x` (the pattern wants the recursive flag as the first flag). Held as expected: `rm -rf /tmp/x`, `../x`, `~/x`, `-- /tmp/x`.
- A4 lists the known limits (`"git" push`, scripts, variables assembling `git push`); an unexpanded variable in an `rm` path is not among them and is the common way an agent writes an absolute path. It fails open.
- Fix: in `bashWords`, treat a word that contains `$` or a backtick, or an unbalanced quote, as outside (held; costs one approval), and let the pattern skip other flags before the recursive one. Add the five cases to the Task 1 table. Can merge without it only if A4 is amended to say so; I would fix it.

**I4. The launchd path has no real run and no post-apply gate with expected output (evidence check 2).** Every test stubs `launchctl` (`AS_LAUNCHCTL`), which is right for tests, but then the plan needs one real run named with its expected output. "Finishing" lists five commands and "puts the four outputs in the ledger" without saying what a good output is; C1 and I1 both pass that list. Add gates G1-G3 below to the PR description and to `docs/INSTALL.md`, which today states no precondition for the heartbeat (check 7: "node >= 22.13 reachable from the plist PATH" and "the agent-board tmux server" are unstated).

**I5. `finishRuns` rescans every finished run on every tick, with an unindexed events scan each.** `engine/lib/engine/schedule.js:185-188`, also `wake.js:28-29`
- `steps` rows of kind `schedule_run` in state `done` are never retired, and for each one the tick (every 5 s in a running engine) runs `SELECT 1 FROM events WHERE kind='schedule_ran' AND json_extract(detail,'$.key')=?`; `events` has no index (`db.js:16`). Cost grows as runs x events. At five runs a day it takes months to hurt; one `every 5m` schedule adds 288 rows a day and it hurts within weeks.
- Fix: record the end on the step itself (e.g. `finish` again with `rc` in the result, or a `ran` flag) and select only rows without it. Not a merge blocker; fix before anyone adds an `every` schedule.

### Minor

- **M1. Wake holds the project's engine lock while it waits for a run, up to 120 min.** `wake.js:64-68`, A10. `engine start` in that window answers "an engine is already running" (`cli.js:458`) although none is. A queue lead starting at 03:30, 06:00 or 07:00 can hit it. Also `takeLock` is read-then-write and wake's `finally` removes the lock file unconditionally (`wake.js:74`), so in a narrow race it deletes an engine's lock. Follow-up: release the lock before waiting, or wait without it.
- **M2. `write_outside` holds a worker's Write to its scratchpad or auto-memory.** Probe: `Write /private/tmp/claude-503/…/scratchpad/a.txt` and `~/.claude/projects/…/memory/x.md` are held. This follows spec 13 as written, but Claude Code tells every session to use the scratchpad for temp files, so an unattended spec can park on a harmless write. Not a defect of this branch; raise with the user as a spec question (an allowlist for the session scratchpad and TMPDIR).
- **M3. An approval answered before the held worker has stopped resumes the same session while the old process is still alive** (`core.js:1163-1164`; nothing waits for the held job to end). Narrow (the worker stops within seconds); follow-up.
- **M4. After an engine restart a hold resume always falls back to a fresh worker** (`claude_tmux.js` `entryOf` only knows this process's handles), and the fresh brief carries the call cut to 300 characters (`hold.question`), so a long command cannot be retried "exactly" and is held again. Costs one more approval; note in docs.
- **M5. The hook's 10 s timeout fails open** (`hooks.json`): a timed-out PreToolUse hook does not block the call. `busy_timeout` 5 s plus the WAL retry stay under it; fine, but worth a line in ARCHITECTURE.
- **M6. Weekly-usage skip trusts the newest statusline tap however old** (`schedule.js:74-89`): a stale 90% reading after the weekly reset skips runs until some session refreshes the tap.
- **M7. `sched/<project>/*.log` and `.rc` files are never pruned.**
- **M8. `git --git-dir /x push` and `cd .. && rm -rf x` are not held** (probe). Same class as A4's limits; add them to the "not held" table so a change is visible.

## Deferred minors: triage

| Task | Minor | Call | Reason |
| --- | --- | --- | --- |
| 8 | `removeAct` ignores a failed bootout | **fix before merge** | I2: double runs after the real migrate, and nothing detects it. |
| 8 | `wake status` opens every DB through `dbm.open` | can wait | It runs `SCHEMA` and `migrate` (a write on an old database) but the wake itself does the same every 15 min; no new harm. |
| 8 | failed bootstrap leaves the new plist; backup untested; `would migrated`; dry-run ignores `--project`; kill test uses `kill -9 $PPID` | can wait | Cosmetic or test-shape; the bootstrap failure prints and exits 1. |
| 8 | two reinstalls in one second reuse the suffixed key; `rerunPlistRemove` has no try | can wait | Needs two reinstalls inside a second; a throw in resume surfaces as an engine error, not silent loss. |
| 3 / 1 | `ENGINE_DIR` unset with `ENGINE_JOB` set fails open | can wait (cheap to fix) | Only `tmux-ctl agent` sets them and sets all four; `bin/tmux-ctl:600` passes an empty `ENGINE_DIR` through if the caller's was empty. One line makes it deny (`ENGINE_JOB` set and `ENGINE_DIR` empty -> deny in `engine-hold.sh`); do it with I3 if hold.js is open anyway. |
| 3 | `hold_skipped` worker still told to report blocked; its job is unmarked | can wait | Needs a second hold while the spec already waits; ends in the normal retry path, and docs now say so. |
| 3 | crash cases simulated in-process | can wait | The pump's replay is covered by `rebuild --check` in each test. |
| 3 | `architectBrief` review query includes `escalated` | can wait | Needs a held reviewer job, which is itself unlikely (reviewers do not push). |
| 3 | feed text cut at 300; `hookAt` seam rebuilds output | can wait | See M4 for the one consequence. |
| 11 | held architect/reviewer gets the worker status shape (`core.js:1164`) | can wait | Architect and reviewer jobs do not make stop-class calls in practice; a wrong shape ends as an invalid report and a retry. Fold the kind list into one constant when next touched. |
| 11 | note wording ("also explains"; stale status files; `ls`/diff in prose) | can wait | Change "also explains" to "may explain" in the same commit as C1 if convenient; it is an unevidenced claim, not a wrong result. |
| 7 | two `run-now` in one second share a `source_id` | can wait | The second is the same request; printing `already queued` would be nicer. |
| 7 | `run-now` without an engine also runs other due schedules | can wait | They were due anyway. |
| 7 | test 3 sleep (fixed in Task 10); ghost-row assert; substituted mutation | can wait | Test quality only. |
| 6 | `TMUX` set to `""` not removed; failed `new-window` invisible in wake output; tmux inside the drain tx; `timeout_min` never stored | can wait | The failed window is a `step_failed` event; fold the output line into the I1 fix if cheap. |
| 6 | leak check can flake on another project's engine files | can wait | Seen once in three full runs at most; rerun alone. |
| 10 | test 3 loop leaks on an early assert; two load flakes | can wait | CI reruns; both pass alone. |
| 5 | re-add with other skip/cwd/env prints `unchanged` | can wait | A9 as decided; a hint line is polish. |
| 5 | dead code in the test; no CLI usage-error tests; `schedule_added` without `{cause, idx}` | can wait | Direct tx, correct as noted. |
| 4 | `parseRule` trims | can wait | `schedule.add` already compares trimmed text (`schedule.js:29,37`). |
| 2 | unused `nonode`; missing-node case SKIPs; new checks never RED; fake resume returns old job id; nested agent inherits `ENGINE_*` | can wait | Inheriting `ENGINE_*` is the safer direction (the nested agent is held too). |
| 1 | M1-M5 (leak check scope, `"undefined"` in `TC_ENGINE_DIR`, fixture schema, case count, sqlite-not-loaded coverage) | can wait | None changes behaviour. |

## Rulings

- **T6 may edit `engine_steps.test.js`; T2 locates by text; T6 lists `wake` in SUBS; T7 edits `wake.js`:** agree, no cost.
- **T1 bad config rule falls back to defaults (fail closed):** agree. The stderr line is invisible to the user; a `hold_config_error` event would be better, later.
- **T1 unset `ENGINE_DIR` fails open:** accept for merge, disagree as a resting state: failing closed costs one line and nothing legitimate depends on the open path.
- **T3 deny returns the spec inside the signal event:** agree; it is the better design.
- **T6 newline before `)` in the run line:** agree.
- **T10 fix the race in `db.js` rather than raise a test cap:** agree; right diagnosis, narrow fix.
- **T10 accept the suites as green without a fourth run:** agree, given CI reruns; the two later failures were different tests that pass alone.
- **T9 fix also corrects the note:** agree.
- **T11 worktree instead of a clone, push to a bare repo by path:** agree; the cost (brief text differs) is nil.
- **T11 the Task 3 minor is load-bearing, fix in scope:** agree, and it shows the limit of the ledger's "minor (deferred)" label: this one made every approved hold time out. C1 and I1 are the same kind of gap on the schedule side.

## Evidence checks

1. **Fixture origin.** Hook inputs are hand-written to the shape the plan author probed on Claude Code 2.1.331 (keys recorded in Global Constraints), and the real Haiku run confirms the shape end to end: acceptable. Migrate's plists are hand-written (`engine_migrate.test.js:44`, PATH `/h/.local/bin:/usr/bin:/bin`), with one read-only dry-run over the real `~/Library/LaunchAgents` (`:322`): acceptable; I compared the five real plists with A11 (`plutil`): commands, times, `LANG`/`PATH`/`TMPDIR` all match, `ProgramArguments[0]` is `~/.local/bin/tmux-ctl` in each.
2. **Artefact under test.** `bin/hold.js`, `engine-hold.sh` and `plutil` are the real ones. `launchctl` is stubbed in every test and never run for real: finding I4, gates G1-G3. `git rev-parse --git-common-dir` (`hold.js:109`) runs for real in the shell e2e.
3. **User-experienced check.** No UI in this diff.
4. **State.** The real run used a scratch engine dir, a scratch tmux server and an `every 1m` echo: it never met launchd's environment (C1), the live tmux socket (I1), a real migrated command inside a `-bg` window, or a run that outlasts a wake. `engine_migrate.test.js:322` reads the real HOME by design and tolerates absent plists. No new test hard-codes `~/.local/bin`.
5. **Universal claims.** "No job is ever left without a runner" (A12, INSTALL) rests on `launchctl print` exit 0 alone: disproved by C1. The Task 1 "36 bypass cases" table is not exhaustive for `rm` (I3). Leak checks compare full listings, not capped output.
6. **Overlap with `origin/main`.** `git merge-tree --write-tree origin/main HEAD` exits 0. Three files changed on both sides: `claude/plugin/hooks/hooks.json` (main adds a PostToolUse `handoff-arm` entry, this branch a PreToolUse entry: disjoint arrays; the branch's test asserts `PreToolUse[0]`, which main does not move), `tools/tests/test_plugin.zsh` (both append independent checks), `docs/ARCHITECTURE.md` (prose). I read both sides' hunks; no semantic clash. I did not run `test_plugin.zsh` on the merged tree (read-only checkout): CI does.
7. **Runbook preconditions.** `docs/INSTALL.md` "Engine wake heartbeat" names no precondition; it needs "node >= 22.13 on the heartbeat's PATH" and the tmux server it uses, each with its check command (G1, G3).
8. **Endpoint trust.** Nothing in this diff.

## Merge-gate items (for the PR description; each is run by a human or the lead on the live machine)

- [ ] **G1 (before `schedule migrate`).** After `tmux-ctl engine wake install`: `launchctl print gui/$(id -u)/com.user.agent-board-engine-wake | grep -E 'last exit code|state'`. Expected: `last exit code = 0`. Today, without the C1 fix, it prints 2. Do not migrate on anything else.
- [ ] **G2 (after `schedule migrate`).** `launchctl list | grep -E 'agent-board-(dream|discover|scout)'`. Expected: no output (count 0). Any line is a job still loaded beside its schedule row: `launchctl bootout gui/$(id -u)/<label>`.
- [ ] **G3 (after migrate).** `tmux-ctl engine schedule run-now scout-poll` is not enough (it runs from a pane, where `TMUX_DASH_TMUX_ARGS` is set). Instead add a throwaway row due in a minute (`tmux-ctl engine schedule add gate --rule "every 1m" -- 'echo gate'`), run `launchctl kickstart gui/$(id -u)/com.user.agent-board-engine-wake` after it is due, then: `tmux -L agent-board list-windows -t '=agent-board-bg:' -F '#{window_name}'` and `ls ~/.local/state/agent-board/engine/sched/agent-board/gate-*.rc`. Expected: an rc file holding `0`, and `tmux list-sessions` on the default socket shows no `agent-board-bg`. Then `tmux-ctl engine schedule rm gate`.
- [ ] **G4.** The morning after: `tmux-ctl engine events --project agent-board | grep -c schedule_ran` is at least 3 (dream 03:30, scout-poll 06:00, discover 07:00), or each is a `schedule_skipped` with a usage reason.

Migrate's safety, as asked: a failure between plists is safe (rows first; a rerun prints `already migrated` and retries the step). The three ways a job ends without a correct runner are C1 (heartbeat loaded but dead), I1 (runs on the wrong server, still runs) and I2 (runs twice). The rollback in "Finishing" is sound and I confirmed the three `… schedule install` commands exist.

## Assessment

**Ready to merge: with fixes.** C1, I1 and I2 before the Finishing step (I would fix them on the branch: each is a few lines plus a test); I3 before merge or an explicit A4 amendment; I4's gates into the PR description; I5 and the minors as follow-ups. Merging the code without running "Finishing" is harmless, since nothing installs the heartbeat by itself.

Context learned:
- `Gotchas`: `node` on this machine is only at `~/Library/Python/3.14/bin/node`; a LaunchAgent whose PATH is `~/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin` cannot run `tmux-ctl engine …` or `registry …` (files: bin/tmux-ctl, engine/lib/engine/launchd.js)
- `Gotchas`: the engine takes its tmux server only from `TMUX_DASH_TMUX_ARGS`; `tmux-ctl engine` does not export its own resolution, so an engine command started outside a pane of the live server reaches tmux's default socket (files: bin/tmux-ctl, engine/lib/engine/cli.js, engine/lib/engine/schedule.js)
- `How to run`: probe a hold rule without a database: `node -e 'const h=require("./engine/lib/engine/hold"); console.log(h.match(h.rulesFor({}),{tool_name:"Bash",tool_input:{command:"…"},cwd:process.cwd()},process.cwd()))'` (files: engine/lib/engine/hold.js)
