# Queue reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An overnight queue no longer stalls after a lead sends shutdown_requests or writes a handoff doc, its keep-awake hold survives a relay, and the morning report's Sleep section lists real sleeps only.

**Architecture:** `tmux-ctl wait-gone` lets the lead wait for teammate windows inside the turn that sent the shutdown, and two plugin hook scripts back it up: `shutdown-record.sh` notes who was asked to shut down, `lead-stop-guard.sh` blocks a lead's stop while one of those windows is still there or while a self-started handoff (`tmux-ctl handoff-mark`) has not relayed. `tmux-ctl awake on --queue` watches the tmux server instead of one claude process, and `awake sleeps` filters `pmset -g log` down to real sleep periods. The lead and handoff rules are changed to use all of it.

**Tech Stack:** zsh (`bin/tmux-ctl`, `tools/lib/awake.zsh`, tests on `tools/tests/lib.zsh`), bash + python3 and zsh hook scripts in `claude/plugin/scripts/`, tmux 3.8, jq, Claude Code 2.1.325 plugin hooks.

**Spec:** `docs/superpowers/specs/2026-11-10-queue-reliability-design.md` (binding; amended 2026-11-16 with the second stall). Executors read it with this plan.

## Global Constraints

**State files** (`<TC_STATE>` is `$TC_STATE_DIR` from `tools/lib/tc-env.zsh`: `$TC_STATE`, else `${TMPDIR:-/tmp}` without its trailing slash + `/tmux-ctl-$UID`):

- `<TC_STATE>/shutdown-pending/<session_id>`: one teammate name per line, each once. Written by `shutdown-record.sh`, pruned and deleted by `lead-stop-guard.sh`.
- `<TC_STATE>/handoff-pending/<session_id>`: an empty marker. Written by `tmux-ctl handoff-mark`, removed by `handoff-mark --clear` and by `tmux-ctl relay`.
- `<TC_STATE>/stop-guard/<session_id>`: `<cksum of the block reason> <count>`.
- `<TC_STATE>/stop-guard.log`: one line per stop that the loop cap allowed: `<UTC YYYY-MM-DDTHH:MM:SSZ> <session id> allowed after 3 blocks: <the pending reason>`. The morning report lists these lines. The hook prints nothing for that stop.
- `<TC_STATE>/awake.json` gains `"queue": true` for a queue hold.
- A `<session_id>` used in a path must match `^[A-Za-z0-9_-]+$`; anything else is ignored (hooks) or refused with exit 2 (`handoff-mark`).

**Exact outputs** (tests compare them byte for byte):

- `wait-gone: all gone` (exit 0); `wait-gone: killed <names, space-separated> after <timeout>s` (exit 3); `wait-gone: could not kill <name>` for a window that cannot be killed (still exit 3); usage `tmux-ctl: usage: tmux-ctl wait-gone <name>... [--timeout <s>]` (exit 2). Poll every 2 s, default timeout 300.
- Stop guard block: one stdout line `{"decision":"block","reason":"<reason>"}`, exit 0. Reasons: `teammate(s) <names> still shutting down: run tmux-ctl wait-gone <names>, then continue` and `a self-started handoff has not relayed: run tmux-ctl relay <doc> --old-session <session id> (handoff skill step 5)`; both at once are joined with `; `.
- `handoff-mark: set`, `handoff-mark: cleared`.
- `awake: on (pid <caffeinate pid>, watching <pid>)`, `awake: on (re-pointed from <old pid> to <new pid>)`, `awake: already on (queue)`, `awake: no tmux server; run on without --queue` (exit 1), usage `usage: tmux-ctl awake on [--queue | --pid N] [--lid]` (exit 2), status line `queue: on`.
- `awake sleeps`: `<start> – <end> <reason>` with an en dash, local `YYYY-MM-DD HH:MM:SS`, `…` for a period with no Wake yet. Deny-list of reasons that are not a real sleep: `Maintenance Sleep`, `Sleep Service Back to Sleep`, `Notification Wake Back to Sleep`.

**Behaviour rules:**

- Hooks are fail-open: any error exits 0 with nothing printed. `lead-stop-guard.sh` prints only its block line; neither script ever writes to stderr. A tmux error is never read as "no windows".
- The Stop guard acts only when `AGENT_BOARD_LEAD=1` (exported by `bin/claude-orchestrator` into the lead's own process) and `$TMUX` is set.
- Window names are matched exactly (`✦ <name>`), in the caller's own tmux session, and windows are killed by window id. Probed on tmux 3.8: `kill-window -t '=tt:✦ alp'` exits 0 and kills `✦ alpha-2` when no window is named exactly `✦ alp`.
- `hooks.json` commands keep the form `"${CLAUDE_PLUGIN_ROOT}/scripts/<name>.sh" --scoped` (an existing test checks every command). `shutdown-record` and `lead-stop-guard` are not `async`.
- `tmux-ctl help` prints header lines with `sed -n '2,<N>p'`: each task that adds header lines raises `<N>` by the same number (43 today, 45 after Task 1, 47 after Task 3). `help still ends at the blank line` checks it.
- Nothing beyond the spec's five design sections. Not changed by this plan: `claude/plugin/.claude-plugin/plugin.json`'s description, the `agent-board:tmux-orchestrator` skill's command table, `tools/tests/e2e-*.md`, README and docs/.

**Tests and shell:**

- Tests follow the existing harness: `source "${0:A:h}/lib.zsh"`, `tt_setup` (a scratch tmux server started with `-L <name> -f /dev/null`), `check`, `tt_done`. Plugin script tests live in `tools/tests/test_<script>.zsh`, like `test_plan_handoff_guard.zsh`. The awake tests keep their `caffeinate`, `pmset` and `sudo` stubs on a temp PATH: no test runs the real ones.
- Each task's Verify runs only that task's test file. The lead runs `zsh tools/tests/all.zsh` after the last task; it is not a task here.
- A test file's verdict is its last line (`ALL PASS` or `<n> FAILED`) together with its exit code; `grep -c '^FAIL'` over the full output counts the failures. Do not read a `tail`.
- `test_plugin.zsh` (about 2 minutes: three headless Haiku probes) and `test_ctl_relay.zsh` (about 1 minute) outlast a 120 s Bash call: run them with `tmux-ctl run -t 600 tests "zsh tools/tests/<file>"`.
- zsh, not bash: never name a variable `path`; brace a variable before a colon (`"=${sess}:"`); quote tmux `=name` targets; quote a word that starts with `=`; an unquoted `$VAR` is not word-split.
- Agents' shells export a real `CLAUDE_CODE_SESSION_ID`, `TMUX` and `TMUX_PANE`. Tests set or unset what they depend on; they never rely on the inherited values.
- Every code block in this plan was run by the planner on 2026-11-16 in zsh: each task's edits were replayed in order on a fresh copy of the worktree, the test run before the implementation (the `<n> FAILED` in each Step 2 is that run), after it (`ALL PASS`), and under each named mutation. Copy the blocks as they are. Where a block is followed by other code, keep one blank line between them if the surrounding code has one.
- Commits: conventional with scope, one per task, staged by path (`git add <paths>`, never `-A` or `.`). End each message with the attribution trailer your harness specifies.

**Delivery semantics of the two hook consumers:**

- `shutdown-record.sh` (PostToolUse events). Concurrent: a lead sends several shutdown_requests in one message, so several hooks run at once; the read-check-append runs under `flock`, and a test starts 20 at once and counts 20 names. Repeated: the same event again adds nothing (dedupe; tested). Out of order: the file is a set, order carries no meaning.
- `lead-stop-guard.sh` (Stop events). It rewrites the pending file through a temp file and `mv`. A name appended by `shutdown-record.sh` between the guard's read and its `mv` would be lost; that can only allow a stop (fail-open direction), and the two hooks do not overlap in practice because `shutdown-record` is not async and finishes before the turn can end. Repeated Stop events are what the loop cap counts.

**Probes behind the external values this plan writes** (all run 2026-11-16 on this machine):

| Value | Probe | Result |
|---|---|---|
| `tmux display -p '#{pid}'` | scratch server, `tmux -L <name> -f /dev/null`, tmux 3.8 | `49391`; `ps -o comm= -p 49391` is the tmux binary: the server's pid |
| `list-windows -t '=tt' -F '#{window_id} #{window_name}'` | same server | `@1 ✦ alpha` |
| `kill-window -t '=tt:✦ alp'` with only `✦ alpha-2` present | same server | exit 0, `✦ alpha-2` killed (prefix match); by id (`-t @4`) kills only that window |
| Stop hook stdin | `claude -p --model haiku --settings <one Stop hook>`, Claude Code 2.1.325 | keys `session_id`, `transcript_path`, `cwd`, `prompt_id`, `permission_mode`, `effort`, `hook_event_name` (`Stop`), `stop_hook_active`, `last_assistant_message`, `background_tasks`, `session_crons` |
| Stop hook output `{"decision":"block","reason":…}`, exit 0 | same run | Claude went on with the turn; the next Stop call had `stop_hook_active: true` |
| Hook environment | same run, started with `AGENT_BOARD_LEAD=1` inside tmux | the hook saw `AGENT_BOARD_LEAD=1`, `$TMUX` set, and `CLAUDE_CODE_SESSION_ID` equal to stdin's `session_id` |
| Stop hook registered by a plugin's `hooks.json` | `claude -p --plugin-dir <scratch copy with both hooks> --session-id <uuid>`, handoff mark set | stop blocked 3 times, allowed the 4th, one `stop-guard.log` line |
| `SendMessage` `tool_input` | 261 shutdown_request tool-call records sampled from `~/.claude/projects/-Users-francisco-ruiz-agent-board/*.jsonl` | `{to, message: {type, reason}}` (125), the same plus `type`, `recipient`, `recipient_kind`, `content` (126), `message` as a JSON string (10); every one has `to` and `message` |
| PostToolUse fires for `SendMessage` | same transcripts | 42 hook records named `PostToolUse:SendMessage` |
| `pmset -g log` Sleep reasons | this Mac's log | 1 Clamshell Sleep, 4 Idle Sleep, 33 Maintenance Sleep, 108 Notification Wake Back to Sleep, 2 Sleep Service Back to Sleep; lines of type `Wake` include `DarkWake to FullWake …` |
| `claude plugin validate claude/plugin` with both hooks | scratch copy | `Validation passed with warnings`, the same as for the unchanged plugin |

**Assumptions the planner made** (the lead can overrule any of them before the task that implements it):

- A1 (Task 8). The spec's "step 1 (checkpoint, then shutdown)" and "writing the doc (step 3)" are read against the handoff skill as it is: `wait-gone` goes at the end of section 3 "Shut the team down", `handoff-mark` at the end of section 2 "Write the handoff doc".
- A2 (Task 3). `tmux-ctl relay` removes the `--old-session` mark and also the caller's own `CLAUDE_CODE_SESSION_ID` mark, so a wrong or missing `--old-session` cannot leave the guard blocking the stop the relay waits for.
- A3 (Task 6). On a re-point `lid` and `watchdogPid` stay as they are, as the spec says; so that the lid hold then follows the new owner, the watchdog reads the watched pid from `awake.json` on every tick instead of only from its argument.
- A4 (Task 6). `status` shows a queue hold as its own line `queue: on`, printed only for a queue hold.
- A5 (Task 7). Two real Sleep lines with no Wake line between them are one period, with the first line's reason. This Mac's log has no such case (5 real Sleep lines, 5 periods).
- A6 (Task 4). In the handoff block reason the `<id>` placeholder is filled with the real session id; `<doc>` stays as written. Two reasons are joined with `; `.
- A7 (Task 6). Every `on` over a live queue hold, `on --queue` included, prints `awake: already on (queue)`.
- A8 (Task 8). Three more rule lines that told the lead to wait for a termination notice or to confirm a shutdown now name `wait-gone` too (the `[Board] Please shut down teammate` line, "Replacing a stalled teammate", handoff Teammate mode step 3): the user's decision is that the fix must not depend on termination notices reaching the lead.
- A9 (Task 6). A plain `on` from a caller with no claude ancestor and no `--pid`, over a live plain hold, keeps that hold (`already on`): there is no pid to re-point to.
- A10 (Task 6). A re-point starts a new hold, so `since` is the time of the re-point.
- A11 (Task 9). The real-state check is a committed script, `tools/tests/check_real_queue_reliability.zsh`, next to the existing `check_real_migrate_plan.zsh`; its name keeps it out of `run-all.zsh` and `all.zsh`.
- Known limit, left as the spec has it: a teammate that refuses its shutdown stays in the pending file. Each stop is then blocked three times and allowed the fourth (one log line each time), until `wait-gone` kills the window at its timeout.

**User decisions (already made):**

- This spec runs now, right after the turn-start spinner spec, because a lead stalled 35 h after a handoff (2026-11-15). The fix must not depend on teammate-termination notices reaching the lead.
- Queue integration: merge to `main` locally, no push.

**Lead's rulings:** implement the spec as written, all five design sections, nothing beyond it; the `stop-guard.log` line names the session id, the UTC time and the pending reason; the Stop guard keys on `AGENT_BOARD_LEAD=1`; a real-state check is required (Task 9).

## File structure

| File | Change | Task |
|---|---|---|
| `bin/tmux-ctl` | `wait-gone` and `handoff-mark` commands, `relay` removes the mark, help lines | 1, 3, 6, 7 |
| `claude/plugin/scripts/shutdown-record.sh` | new: PostToolUse(SendMessage) recorder | 2 |
| `claude/plugin/scripts/lead-stop-guard.sh` | new: Stop guard | 4 |
| `claude/plugin/hooks/hooks.json` | registers both | 5 |
| `tools/lib/awake.zsh` | `on --queue`, re-point, `status`, watchdog; `sleeps` real periods and `--all` | 6, 7 |
| `claude/orchestrator.md`, `claude/plugin/skills/handoff/SKILL.md` | the rules | 8 |
| `tools/tests/test_ctl_wait_gone.zsh`, `test_shutdown_record.zsh`, `test_lead_stop_guard.zsh` | new tests | 1, 2, 4 |
| `tools/tests/test_ctl_relay.zsh`, `test_plugin.zsh`, `test_ctl_awake.zsh` | added checks | 3, 5, 6, 7, 8 |
| `tools/tests/fixtures/awake/log-sleeps-kinds.txt`, `README.md` | a log with every Sleep reason kind | 7 |
| `tools/tests/check_real_queue_reliability.zsh`, `docs/superpowers/notes/2026-11-16-queue-reliability-real-check.md` | real-state check and its note | 9 |

Order: tasks run 1 to 9. Tasks 1, 3, 6 and 7 edit `bin/tmux-ctl` one after the other; 6 and 7 edit `tools/lib/awake.zsh` and `test_ctl_awake.zsh`; 5 and 8 edit `test_plugin.zsh`. Tiers: Tasks 1, 2, 3, 4, 5, 7 and 8 are `mechanical` (complete code in the steps), Tasks 6 and 9 are `standard`.

---

### Task 1: `tmux-ctl wait-gone`

**Goal:** `tmux-ctl wait-gone <name>... [--timeout <s>]` waits until every `✦ <name>` window of the caller's session is gone, and kills the ones left at the timeout (spec §1).

**Files:**
- Modify: `bin/tmux-ctl` (two help lines before the `relay` help line, the `sed -n '2,43p'` help range, a new `wait-gone)` case before `relay)`)
- Create: `tools/tests/test_ctl_wait_gone.zsh`

**Acceptance Criteria:**
- [ ] Two `✦` windows that close after 1 s: prints `wait-gone: all gone`, exit 0, well before the timeout.
- [ ] A window that stays: killed at `--timeout 3`, prints `wait-gone: killed stay after 3s`, exit 3.
- [ ] Names match exactly: with only `✦ stay-2` present, `wait-gone stay` exits 0 and `✦ stay-2` is still there. The kill uses the window id, never a `=session:name` target.
- [ ] A `✦ ` prefix in an argument is stripped; only names still present are listed in the `killed` line.
- [ ] A window named `✦ a` in another session neither counts nor is killed.
- [ ] Outside tmux, with no name, with `--timeout` lacking a number: exit 2 (the last three print `tmux-ctl: usage: tmux-ctl wait-gone <name>... [--timeout <s>]`).
- [ ] `tmux-ctl help` lists `wait-gone` and still ends at the blank line (help range is `2,45p`).

**Verify:** `zsh tools/tests/test_ctl_wait_gone.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_ctl_wait_gone.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
# tmux-ctl wait-gone <name>... [--timeout <s>]: after shutdown_requests the lead waits, in the same turn, until every
# `✦ <name>` window of its session is gone; at the timeout it kills the ones left (spec 2026-11-10-queue-reliability §1).
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude
mk() { tt new-window -d -t "=${1}:" -n "$2" 'sleep 300' }
wid() { tt list-windows -t "=$1" -F '#{window_id} #{window_name}' | awk -v n="$2" '{ id=$1; sub(/^[^ ]+ /, "") } $0==n { print id }' }
has() { [[ -n "$(wid "$1" "$2")" ]] }
gone() { ! has "$@" }
zmodload zsh/datetime

# all gone: two windows that close after 1 s
mk tt '✦ a'; mk tt '✦ b'
ia="$(wid tt '✦ a')"; ib="$(wid tt '✦ b')"
( sleep 1; tt kill-window -t "$ia"; tt kill-window -t "$ib" ) &
t0=$EPOCHSECONDS
out="$($C wait-gone a b --timeout 20 2>&1)"; rc=$?
check "closed after 1 s: exit 0"                  test $rc -eq 0
check "closed after 1 s: prints all gone"         test "$out" = "wait-gone: all gone"
check "closed after 1 s: returns well before the timeout"  test $(( EPOCHSECONDS - t0 )) -lt 10
wait

# one stays: killed at the timeout
mk tt '✦ stay'
t0=$EPOCHSECONDS
out="$($C wait-gone stay --timeout 3 2>&1)"; rc=$?
check "stays: exit 3"                             test $rc -eq 3
check "stays: prints killed <name> after <s>s"    test "$out" = "wait-gone: killed stay after 3s"
check "stays: the window was killed"              gone tt '✦ stay'
check "stays: waited for the timeout"             test $(( EPOCHSECONDS - t0 )) -ge 3

# names match exactly: `✦ stay-2` is not `✦ stay`
mk tt '✦ stay-2'
out="$($C wait-gone stay --timeout 3 2>&1)"; rc=$?
check "exact match: a longer name does not count" test $rc -eq 0 -a "$out" = "wait-gone: all gone"
check "exact match: the longer-named window is left alone"  has tt '✦ stay-2'

# one gone, one left: only the one left is named and killed; the `✦ ` prefix in an argument is stripped
mk tt '✦ x'
out="$($C wait-gone '✦ x' nobody --timeout 2 2>&1)"; rc=$?
check "prefix stripped, mixed: exit 3"            test $rc -eq 3
check "prefix stripped, mixed: names only x"      test "$out" = "wait-gone: killed x after 2s"
check "mixed: bystander still alive"              has tt '✦ stay-2'

# only the caller's session counts
tt new-session -d -s other -n '✦ a' -c "$TT_DIR" 'sleep 300'
out="$($C wait-gone a --timeout 2 2>&1)"; rc=$?
check "other session: its window does not count"  test $rc -eq 0 -a "$out" = "wait-gone: all gone"
check "other session: its window is left alone"   has other '✦ a'

# usage
out="$(env -u TMUX -u TMUX_PANE $C wait-gone a 2>&1)"; rc=$?
check "outside tmux: exit 2"                      test $rc -eq 2
U="tmux-ctl: usage: tmux-ctl wait-gone <name>... [--timeout <s>]"
out="$($C wait-gone 2>&1)"; rc=$?
check "no name: usage, exit 2"                    test $rc -eq 2 -a "$out" = "$U"
out="$($C wait-gone a --timeout 2>&1)"; rc=$?
check "--timeout without a value: usage, exit 2"  test $rc -eq 2 -a "$out" = "$U"
out="$($C wait-gone a --timeout soon 2>&1)"; rc=$?
check "--timeout not a number: usage, exit 2"     test $rc -eq 2 -a "$out" = "$U"
check "help lists wait-gone"                      sh -c "$C help | grep -q 'tmux-ctl wait-gone'"
check "help still ends at the blank line"         test "$($C help | tail -1)" = ""
tt_done
```

- [ ] **Step 2: Run the test to see it fail**

Run: `zsh tools/tests/test_ctl_wait_gone.zsh`
Expected: last line `14 FAILED`, because `wait-gone` is an unknown command today (`tmux-ctl: unknown command 'wait-gone'`, exit 2), so every check on its output or on exit 0/3 fails. The checks that only expect exit 2 outside tmux, or that a window is left alone, already pass.

- [ ] **Step 3: Implement**

In `bin/tmux-ctl`, insert this block immediately before the line that starts with `#   tmux-ctl relay <doc> [--old-session ID] after this turn` (it occurs once):

```zsh
#   tmux-ctl wait-gone <name>... [--timeout S]  after shutdown_requests: wait (default 300 s) until every `✦ <name>` window of this
#                                          session is gone; at the timeout kill the ones left (exit 3)
```

In `bin/tmux-ctl`, replace

```zsh
sed -n '2,43p'
```
with

```zsh
sed -n '2,45p'
```

In `bin/tmux-ctl`, insert this block immediately before the line that starts with `  relay)` (it occurs once):

```zsh
  wait-gone)   # spec 2026-11-10-queue-reliability §1: the lead never ends a turn waiting for shutdown confirmations
    wg_usage="usage: tmux-ctl wait-gone <name>... [--timeout <s>]"
    wg_names=(); wg_to=300
    while (( $# )); do
      if [[ "$1" == --timeout ]]; then
        [[ "$2" == <-> ]] || die "$wg_usage"
        wg_to="$2"; shift 2
      else wg_names+=("${1#✦ }"); shift; fi
    done
    (( $#wg_names )) || die "$wg_usage"
    zmodload zsh/datetime
    wg_start=$EPOCHSECONDS
    while :; do
      # exact names only, and the window id for the kill: a `-t "=sess:✦ a"` target also matches `✦ a-2` by prefix when `✦ a` is gone
      typeset -A wg_ids=()
      for wg_l in ${(f)"$(t list-windows -t "=$SESSION" -F '#{window_id} #{window_name}' 2>/dev/null)"}; do
        wg_ids[${wg_l#* }]="${wg_l%% *}"
      done
      wg_left=()
      for wg_n in $wg_names; do (( ${+wg_ids[✦ $wg_n]} )) && wg_left+=("$wg_n"); done
      if (( ! $#wg_left )); then print -r -- "wait-gone: all gone"; exit 0; fi
      (( EPOCHSECONDS - wg_start >= wg_to )) && break
      sleep $(( wg_to - (EPOCHSECONDS - wg_start) < 2 ? wg_to - (EPOCHSECONDS - wg_start) : 2 ))
    done
    for wg_n in $wg_left; do
      t kill-window -t "${wg_ids[✦ $wg_n]}" 2>/dev/null || print -r -- "wait-gone: could not kill $wg_n"
    done
    print -r -- "wait-gone: killed ${(j: :)wg_left} after ${wg_to}s"
    exit 3 ;;
```

Notes:
- The help text is printed by `sed -n '2,43p' "$0"` near the end of the file: two new header lines move the blank `#` line from 43 to 45, so the range becomes `2,45p`. `help still ends at the blank line` checks it.
- Keep one blank line between the new case and `relay)`.
- Why the window id: probed on tmux 3.8, `kill-window -t '=tt:✦ alp'` exits 0 and kills `✦ alpha-2` when no window is named exactly `✦ alp` (prefix match).

- [ ] **Step 4: Run the test to see it pass**

Run: `zsh tools/tests/test_ctl_wait_gone.zsh`
Expected: last line `ALL PASS` (20 `ok` lines), and `grep -c '^FAIL'` over the output is 0.

- [ ] **Step 5: Mutation check (run each, report the failing lines, then restore the file)**

Mutation, match the name as a substring instead of exactly: in `bin/tmux-ctl` change

```zsh
(( ${+wg_ids[✦ $wg_n]} )) && wg_left+=("$wg_n")
```
to

```zsh
[[ "${(kj:|:)wg_ids}" == *"✦ $wg_n"* ]] && wg_left+=("$wg_n")
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - exact match: a longer name does not count
```

Restore the line and run the test again: `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add bin/tmux-ctl tools/tests/test_ctl_wait_gone.zsh
git commit -m "feat(tmux-ctl): wait-gone waits for teammate windows to close"
```

End the commit message with the attribution trailer your harness specifies. Stage only these paths.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_wait_gone.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_wait_gone.zsh", "acceptanceCriteria": ["two windows closed after 1 s: 'wait-gone: all gone', exit 0", "a window that stays is killed at --timeout 3: 'wait-gone: killed stay after 3s', exit 3", "exact names: '✦ stay-2' does not count as 'stay' and is not killed; kill by window id", "'✦ ' prefix stripped; only remaining names listed", "another session's window neither counts nor is killed", "outside tmux / no name / bad --timeout: exit 2", "help lists wait-gone and ends at the blank line (range 2,45p)"], "modelTier": "mechanical"}
```

### Task 2: `shutdown-record.sh`

**Goal:** A PostToolUse(SendMessage) script that adds the recipient of every `shutdown_request` to `<TC_STATE>/shutdown-pending/<session_id>` (spec §3). Registration is Task 5.

**Files:**
- Create: `claude/plugin/scripts/shutdown-record.sh` (executable)
- Create: `tools/tests/test_shutdown_record.zsh`

**Acceptance Criteria:**
- [ ] `tool_input.message` as an object with `type == "shutdown_request"`, and as a JSON string that parses to one: `tool_input.to` is appended to `<TC_STATE>/shutdown-pending/<session_id>`, one name per line.
- [ ] A plain message, a `shutdown_response`, another `tool_name`: nothing is written (no file, no directory).
- [ ] Delivery semantics. Concurrent: 20 hooks at once with 20 names leave 20 lines, none lost (`flock` around read-check-append). Repeated: the same 20 again leave 20 lines (deduped). Out of order: the file is a set, order carries no meaning.
- [ ] Fail-open: malformed JSON, no `tool_input`, no `session_id`, a `session_id` that is not `[A-Za-z0-9_-]+`, a recipient with a newline, an unwritable state dir: exit 0, nothing on stdout or stderr, nothing written.
- [ ] The script prints nothing in every case and accepts `--scoped`.

**Verify:** `zsh tools/tests/test_shutdown_record.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_shutdown_record.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
# shutdown-record.sh (PostToolUse, matcher SendMessage): a shutdown_request adds its recipient to
# <TC_STATE>/shutdown-pending/<session_id>, which lead-stop-guard.sh reads (spec 2026-11-10-queue-reliability §3).
# The tool_input shapes below were copied from real lead transcripts on 2026-11-16: {to, message:{type,reason}} (the
# call as sent), the same with type/recipient/recipient_kind/content added (as recorded), and message as a JSON string.
H="${TC_SHUTDOWN_RECORD:-$TT_REPO/claude/plugin/scripts/shutdown-record.sh}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/sdr.XXXXXX")"; tmp="${tmp:A}"
trap 'rm -rf "$tmp"; tt_teardown' EXIT INT TERM
export TC_STATE="$tmp/state"
SID=11111111-2222-3333-4444-555555555555
PF="$TC_STATE/shutdown-pending/$SID"
# payload <to> <form: obj|rec|str|plain|resp> [tool] [session_id] -> PostToolUse JSON
payload() { python3 -c 'import json,sys
to, form, tool, sid = sys.argv[1:5]
req = {"type": "shutdown_request", "reason": "Done, thanks. To approve: first load the SendMessage schema."}
ti = {"to": to, "message": req}
if form == "rec": ti.update({"type": "shutdown_request", "recipient": to, "recipient_kind": "name", "content": "Done, thanks…"})
if form == "str": ti["message"] = json.dumps(req)
if form == "plain": ti = {"to": to, "summary": "note", "message": "please look at the shutdown_request handling"}
if form == "resp": ti["message"] = {"type": "shutdown_response", "request_id": "r1", "approve": True}
d = {"session_id": sid, "hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti, "tool_response": {"success": True}}
if not sid: del d["session_id"]
print(json.dumps(d))' "$1" "$2" "${3:-SendMessage}" "${4-$SID}"; }
run_hook() { payload "$@" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; }
quiet() { [[ $rc == 0 && ! -s "$tmp/o" && ! -s "$tmp/e" ]] }

run_hook alpha obj
check "object form: recipient recorded"            test "$(<$PF)" = alpha
check "object form: exit 0, prints nothing"        quiet
run_hook alpha rec
check "same name again (recorded shape): deduped"  test "$(<$PF)" = alpha
run_hook beta str
check "string form: recipient appended"            test "$(<$PF)" = $'alpha\nbeta'
check "string form: exit 0, prints nothing"        quiet
run_hook gamma plain
check "plain message: ignored"                     test "$(<$PF)" = $'alpha\nbeta'
run_hook gamma resp
check "shutdown_response: ignored"                 test "$(<$PF)" = $'alpha\nbeta'
run_hook gamma obj Bash
check "another tool: ignored"                      test "$(<$PF)" = $'alpha\nbeta'
rm -rf "$TC_STATE"
run_hook gamma plain
check "plain message alone: no file, no directory" test ! -e "$TC_STATE/shutdown-pending"
check "plain message: exit 0, prints nothing"      quiet
print -r -- 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed json: silent exit 0"              quiet
print -r -- '{"session_id":"'$SID'","tool_name":"SendMessage"}' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "no tool_input: silent exit 0"               quiet
run_hook alpha obj SendMessage ''
check "no session_id: silent, nothing written"     zsh -c '[[ ! -e $1/shutdown-pending ]]' _ "$TC_STATE" && quiet
run_hook alpha obj SendMessage '../../escape'
check "session_id that is not a plain id: nothing written"  test ! -e "$tmp/escape" -a ! -e "$TC_STATE/shutdown-pending"
run_hook $'two\nlines' obj
check "recipient with a newline: nothing written"  test ! -e "$PF"
# unwritable state dir: fail-open
: > "$tmp/file"; payload alpha obj | TC_STATE="$tmp/file/x" "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "unwritable state dir: silent exit 0"        quiet
# delivery: 20 hooks at once (a lead sends its shutdown_requests in one message), each name exactly once
for i in {1..20}; do payload "mate-$i" obj | "$H" & done; wait
check "20 concurrent records: 20 names"            test "$(wc -l < "$PF" | tr -d ' ')" = 20
check "20 concurrent records: none repeated or lost"  test "$(sort -u "$PF" | wc -l | tr -d ' ')" = 20
for i in {1..20}; do payload "mate-$i" obj | "$H" & done; wait
check "the same 20 again (redelivery): still 20"   test "$(wc -l < "$PF" | tr -d ' ')" = 20
check "script is executable"                       test -x "$H"
tt_done
```

- [ ] **Step 2: Run the test to see it fail**

Run: `zsh tools/tests/test_shutdown_record.zsh`
Expected: last line `16 FAILED`, because the script does not exist, so every run of `$H` fails with `no such file or directory` (the output is noisy: python `BrokenPipeError` lines from the payload writer are expected). The checks that only expect "nothing written" already pass.

- [ ] **Step 3: Implement**

Create `claude/plugin/scripts/shutdown-record.sh` and make it executable (`chmod +x claude/plugin/scripts/shutdown-record.sh`):

```bash
#!/usr/bin/env bash
# PostToolUse(SendMessage): when the message is a shutdown_request (an object, or a JSON string that parses to one),
# add its recipient to <TC_STATE>/shutdown-pending/<session_id>, one name per line, each name once. lead-stop-guard.sh
# reads that file at Stop (docs/superpowers/specs/2026-11-10-queue-reliability-design.md §3). Nothing else.
# Fail-open: any error exits 0 with nothing printed. --scoped (the plugin registration) is accepted and changes nothing.
# Delivery: hooks of one assistant message can run at once and a hook can run twice, so the read-check-append runs
# under flock: no name is lost or repeated. Order does not matter (the file is a set).
input=$(cat) || exit 0
printf '%s' "$input" | python3 -I -c 'import fcntl, json, os, re, sys
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input")
    if d.get("tool_name") != "SendMessage" or not isinstance(ti, dict):
        sys.exit(0)
    m = ti.get("message")
    if isinstance(m, str):
        m = json.loads(m)
    if not isinstance(m, dict) or m.get("type") != "shutdown_request":
        sys.exit(0)
    to, sid = ti.get("to"), d.get("session_id")
    if not isinstance(to, str) or not to.strip() or "\n" in to or "\r" in to:
        sys.exit(0)
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        sys.exit(0)
    state = os.environ.get("TC_STATE") or os.path.join((os.environ.get("TMPDIR") or "/tmp").rstrip("/"), "tmux-ctl-%d" % os.getuid())
    pdir = os.path.join(state, "shutdown-pending")
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, sid), "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        if to not in f.read().split("\n"):
            f.write(to + "\n")
except BaseException:
    pass' >/dev/null 2>&1
exit 0
```

Notes:
- State dir rule (the same as `tools/lib/tc-env.zsh`): `$TC_STATE`, else `${TMPDIR:-/tmp}` without its trailing slash + `/tmux-ctl-<uid>`.
- The fixture shapes are real: 261 `shutdown_request` tool-call records from this project's lead transcripts were read on 2026-11-16 (object form, the recorded form with `type`/`recipient`/`recipient_kind`/`content` added, and `message` as a JSON string).

- [ ] **Step 4: Run the test to see it pass**

Run: `zsh tools/tests/test_shutdown_record.zsh`
Expected: last line `ALL PASS` (20 `ok` lines), and `grep -c '^FAIL'` over the output is 0.

- [ ] **Step 5: Mutation check (run each, report the failing lines, then restore the file)**

Mutation, drop the dedupe check: in `claude/plugin/scripts/shutdown-record.sh` change

```bash
        if to not in f.read().split("\n"):
```
to

```bash
        if True:
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - same name again (recorded shape): deduped
FAIL - the same 20 again (redelivery): still 20
```

Restore the line and run the test again: `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add claude/plugin/scripts/shutdown-record.sh tools/tests/test_shutdown_record.zsh
git commit -m "feat(plugin): shutdown-record notes teammates asked to shut down"
```

End the commit message with the attribution trailer your harness specifies. Stage only these paths.

```json:metadata
{"files": ["claude/plugin/scripts/shutdown-record.sh", "tools/tests/test_shutdown_record.zsh"], "verifyCommand": "zsh tools/tests/test_shutdown_record.zsh", "acceptanceCriteria": ["object and JSON-string shutdown_request: tool_input.to appended to <TC_STATE>/shutdown-pending/<session_id>", "plain message, shutdown_response, other tool: nothing written", "20 concurrent records leave 20 names; the same 20 again still 20 (flock + dedupe)", "fail-open: bad JSON, no session_id, non-plain session_id, newline in recipient, unwritable dir: exit 0, silent", "prints nothing; accepts --scoped"], "modelTier": "mechanical"}
```

### Task 3: `tmux-ctl handoff-mark`, and `relay` removes the mark

**Goal:** `tmux-ctl handoff-mark [--clear]` writes or removes `<TC_STATE>/handoff-pending/<CLAUDE_CODE_SESSION_ID>`, and `tmux-ctl relay` removes the mark once the relay is scheduled (spec §3).

**Files:**
- Modify: `bin/tmux-ctl` (two help lines before the `relay` help line, help range `2,45p` → `2,47p`, a new `handoff-mark)` case before `relay)`, five lines before relay's final `print`)
- Modify: `tools/tests/test_ctl_relay.zsh` (the two lines of the first successful relay become a block)

**Acceptance Criteria:**
- [ ] `CLAUDE_CODE_SESSION_ID=OLD1 tmux-ctl handoff-mark` creates `<TC_STATE>/handoff-pending/OLD1` and prints `handoff-mark: set`; `--clear` removes it and prints `handoff-mark: cleared` (exit 0 with no mark too).
- [ ] Without `CLAUDE_CODE_SESSION_ID`, or with one that is not `[A-Za-z0-9_-]+`, or with an unknown argument: exit 2, nothing written.
- [ ] A refused relay (worker window) leaves every mark. A scheduled relay removes the `--old-session` mark and the caller's own `CLAUDE_CODE_SESSION_ID` mark, and leaves another session's mark.
- [ ] Every existing relay check still passes; `tmux-ctl help` lists `handoff-mark` (help range `2,47p`).

**Verify:** `zsh tools/tests/test_ctl_relay.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test**

In `tools/tests/test_ctl_relay.zsh`, replace everything from the line that starts with `out="$($C relay "$doc" --old-session OLD1)"` up to, but not including, the next line that starts with `check "orchestrator started"` with:

```zsh
# handoff-mark: a self-started handoff marks its session until the relay is scheduled (spec 2026-11-10-queue-reliability §3)
HP="$TC_STATE/handoff-pending"
out="$(CLAUDE_CODE_SESSION_ID=OLD1 $C handoff-mark)"; rc=$?
check "handoff-mark: writes the marker"        test $rc -eq 0 -a -f "$HP/OLD1"
check "handoff-mark: says so"                  test "$out" = "handoff-mark: set"
CLAUDE_CODE_SESSION_ID=OLD1 $C handoff-mark >/dev/null
check "handoff-mark twice: still one marker"   test "$(ls "$HP" | wc -l | tr -d ' ')" = 1
out="$(CLAUDE_CODE_SESSION_ID=OLD1 $C handoff-mark --clear)"; rc=$?
check "handoff-mark --clear: removes it"       test $rc -eq 0 -a ! -e "$HP/OLD1" -a "$out" = "handoff-mark: cleared"
CLAUDE_CODE_SESSION_ID=OLD1 $C handoff-mark --clear >/dev/null; check "handoff-mark --clear with no marker: exit 0"  test $? -eq 0
out="$(env -u CLAUDE_CODE_SESSION_ID $C handoff-mark 2>&1)"; rc=$?
check "handoff-mark without CLAUDE_CODE_SESSION_ID: exit 2"  test $rc -eq 2
check "handoff-mark without the variable: names it"  zsh -c '[[ $1 == *CLAUDE_CODE_SESSION_ID* ]]' _ "$out"
CLAUDE_CODE_SESSION_ID='../x' $C handoff-mark >/dev/null 2>&1; rc=$?
check "handoff-mark with an id that is not a plain id: exit 2, nothing written"  test $rc -eq 2 -a ! -e "$TC_STATE/x"
CLAUDE_CODE_SESSION_ID=OLD1 $C handoff-mark extra >/dev/null 2>&1; check "handoff-mark with an unknown argument: exit 2"  test $? -eq 2
check "help lists handoff-mark"                sh -c "$C help | grep -q 'tmux-ctl handoff-mark'"
# the relay removes the old session's marker once it is scheduled; a refused relay leaves it
CLAUDE_CODE_SESSION_ID=OLD1 $C handoff-mark >/dev/null
CLAUDE_CODE_SESSION_ID=SELF1 $C handoff-mark >/dev/null
CLAUDE_CODE_SESSION_ID=OTHER1 $C handoff-mark >/dev/null
TMUX_PANE=$worker $C relay "$doc" --old-session OLD1 >/dev/null 2>&1
check "refused relay: markers kept"            test -f "$HP/OLD1" -a -f "$HP/SELF1"
out="$(CLAUDE_CODE_SESSION_ID=SELF1 $C relay "$doc" --old-session OLD1)"
check "relay scheduled"     zsh -c 'print -r -- "$1" | grep -q "relay scheduled"' x "$out"
check "relay: --old-session marker removed"    test ! -e "$HP/OLD1"
check "relay: the caller's own marker removed" test ! -e "$HP/SELF1"
check "relay: another session's marker kept"   test -f "$HP/OTHER1"
```

- [ ] **Step 2: Run the test to see it fail**

Run: `zsh tools/tests/test_ctl_relay.zsh`
Expected: last line `9 FAILED`, because `handoff-mark` is an unknown command today, so no mark is ever written.

- [ ] **Step 3: Implement**

In `bin/tmux-ctl`, insert this block immediately before the line that starts with `#   tmux-ctl relay <doc> [--old-session ID] after this turn` (it occurs once):

```zsh
#   tmux-ctl handoff-mark [--clear]        a self-started handoff marks this session as not yet relayed (the Stop guard
#                                          blocks its stops until `relay` runs); --clear removes the mark (handoff skill only)
```

In `bin/tmux-ctl`, replace

```zsh
sed -n '2,45p'
```
with

```zsh
sed -n '2,47p'
```

In `bin/tmux-ctl`, insert this block immediately before the line that starts with `  relay)` (it occurs once):

```zsh
  handoff-mark)   # spec 2026-11-10-queue-reliability §3: read by claude/plugin/scripts/lead-stop-guard.sh
    [[ $# -eq 0 || ( $# -eq 1 && "$1" == --clear ) ]] || die "usage: tmux-ctl handoff-mark [--clear]"
    [[ "$CLAUDE_CODE_SESSION_ID" =~ '^[A-Za-z0-9_-]+$' ]] || die "handoff-mark needs CLAUDE_CODE_SESSION_ID (run it from the lead's own Bash tool)"
    hm="$STATE/handoff-pending/$CLAUDE_CODE_SESSION_ID"
    if [[ "$1" == --clear ]]; then rm -f -- "$hm"; print -r -- "handoff-mark: cleared"
    else mkdir -p "${hm:h}" && : > "$hm" || die "cannot write $hm"; print -r -- "handoff-mark: set"; fi ;;
```

In `bin/tmux-ctl`, insert this block immediately before the line that starts with `    print -r -- "relay scheduled:` (it occurs once):

```zsh
    # the relay is scheduled: the self-started handoff's mark (handoff-mark) has done its job. Remove the old session's and
    # the caller's own, so a wrong or missing --old-session never leaves the Stop guard blocking the stop the relay waits for.
    for hm in "$old" "$CLAUDE_CODE_SESSION_ID"; do
      [[ "$hm" =~ '^[A-Za-z0-9_-]+$' ]] && rm -f -- "$STATE/handoff-pending/$hm"
    done
```

Notes:
- This test takes about a minute (it waits for real detached relays). Run it with `tmux-ctl run -t 600 tests "zsh tools/tests/test_ctl_relay.zsh"` if your Bash tool stops at 120 s.
- Agents' shells export a real `CLAUDE_CODE_SESSION_ID`: the test always sets or unsets it explicitly, never relies on the inherited one.
- The relay removes two marks on purpose: the `--old-session` id (the spec) and the caller's own id. The handoff skill's fallback id can be a teammate's transcript; without the second removal the Stop guard would block the very stop the relay waits for (assumption A2).

- [ ] **Step 4: Run the test to see it pass**

Run: `zsh tools/tests/test_ctl_relay.zsh`
Expected: last line `ALL PASS` (46 `ok` lines), and `grep -c '^FAIL'` over the output is 0.

- [ ] **Step 5: Mutation check (run each, report the failing lines, then restore the file)**

Mutation, make the relay keep the marks: in `bin/tmux-ctl` change

```zsh
      [[ "$hm" =~ '^[A-Za-z0-9_-]+$' ]] && rm -f -- "$STATE/handoff-pending/$hm"
```
to

```zsh
      :
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - relay: --old-session marker removed
FAIL - relay: the caller's own marker removed
```

Restore the line and run the test again: `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add bin/tmux-ctl tools/tests/test_ctl_relay.zsh
git commit -m "feat(tmux-ctl): handoff-mark, cleared when the relay is scheduled"
```

End the commit message with the attribution trailer your harness specifies. Stage only these paths.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_relay.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_relay.zsh", "acceptanceCriteria": ["handoff-mark writes <TC_STATE>/handoff-pending/<CLAUDE_CODE_SESSION_ID>, prints 'handoff-mark: set'; --clear removes it", "no or non-plain CLAUDE_CODE_SESSION_ID, unknown argument: exit 2", "refused relay keeps marks; scheduled relay removes the --old-session mark and the caller's own, keeps another session's", "existing relay checks pass; help lists handoff-mark (range 2,47p)"], "modelTier": "mechanical"}
```

### Task 4: `lead-stop-guard.sh`

**Goal:** A Stop script that blocks a lead's stop while a teammate it asked to shut down still has its `✦ <name>` window, or while a self-started handoff has not relayed, with a loop cap (spec §3). Registration is Task 5.

**Files:**
- Create: `claude/plugin/scripts/lead-stop-guard.sh` (executable)
- Create: `tools/tests/test_lead_stop_guard.zsh`

**Acceptance Criteria:**
- [ ] Exits 0 at once, printing nothing, unless `AGENT_BOARD_LEAD=1` and `$TMUX` is set.
- [ ] Pending name with a `✦ <name>` window in the lead's own tmux session: prints exactly one line `{"decision":"block","reason":"teammate(s) <names> still shutting down: run tmux-ctl wait-gone <names>, then continue"}`, exit 0.
- [ ] Names whose window is gone are dropped and the file rewritten; when none is left the file and the counter are deleted and the stop is allowed. `✦ alpha-2` and another session's `✦ alpha` do not count as `alpha`.
- [ ] `<TC_STATE>/handoff-pending/<session_id>` exists: block with `a self-started handoff has not relayed: run tmux-ctl relay <doc> --old-session <session id> (handoff skill step 5)`; both reasons are joined with `; `.
- [ ] Loop cap: `<TC_STATE>/stop-guard/<session_id>` holds `<cksum of the reason> <count>`; the same reason blocks three times, the 4th stop is allowed with nothing printed, the counter is deleted, and one line `<UTC YYYY-MM-DDTHH:MM:SSZ> <session id> allowed after 3 blocks: <reason>` is appended to `<TC_STATE>/stop-guard.log`. A changed reason restarts the count at 1.
- [ ] Fail-open: malformed stdin, no or non-plain `session_id`, tmux unreachable: exit 0, nothing printed, the pending file kept. Nothing is ever written to stderr.

**Verify:** `zsh tools/tests/test_lead_stop_guard.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_lead_stop_guard.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
# lead-stop-guard.sh (Stop): a lead may not end its turn while a teammate it asked to shut down still has its
# `✦ <name>` window, or while a self-started handoff has not relayed (spec 2026-11-10-queue-reliability §3).
# Stop stdin fields (session_id, hook_event_name, stop_hook_active, last_assistant_message, …) and the block output
# {"decision":"block","reason":…} were probed with a real `claude -p` Stop hook on 2026-11-16 (Claude Code 2.1.x).
H="${TC_STOP_GUARD:-$TT_REPO/claude/plugin/scripts/lead-stop-guard.sh}"
tt_setup claude
tmp="$TT_DIR/sg"; mkdir -p "$tmp"
SID=11111111-2222-3333-4444-555555555555
PD="$TC_STATE/shutdown-pending"; PF="$PD/$SID"; MF="$TC_STATE/handoff-pending/$SID"; CF="$TC_STATE/stop-guard/$SID"; LOG="$TC_STATE/stop-guard.log"
export AGENT_BOARD_LEAD=1
stdin() { print -r -- '{"session_id":"'"${1-$SID}"'","transcript_path":"/x.jsonl","cwd":"/x","hook_event_name":"Stop","stop_hook_active":false,"last_assistant_message":"I will relay once they confirm."}' }
run_hook() { stdin "$@" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; }
allowed() { [[ $rc == 0 && ! -s "$tmp/o" && ! -s "$tmp/e" ]] }
blocked() { [[ $rc == 0 && ! -s "$tmp/e" && "$(jq -r .decision "$tmp/o" 2>/dev/null)" == block && "$(jq -r .reason "$tmp/o")" == "$1" && "$(wc -l < "$tmp/o" | tr -d ' ')" == 1 ]] }
pend() { mkdir -p "$PD"; print -rl -- "$@" > "$PF" }
mk() { tt new-window -d -t '=tt:' -n "$1" 'sleep 300' }
kw() { tt kill-window -t "$(tt list-windows -t '=tt' -F '#{window_id} #{window_name}' | awk -v n="$1" '{ id=$1; sub(/^[^ ]+ /, "") } $0==n { print id }')" }
reset() { rm -rf "$PD" "$TC_STATE/handoff-pending" "$TC_STATE/stop-guard" "$LOG" }
RA="teammate(s) alpha still shutting down: run tmux-ctl wait-gone alpha, then continue"
RH="a self-started handoff has not relayed: run tmux-ctl relay <doc> --old-session $SID (handoff skill step 5)"

# nothing pending
run_hook
check "nothing pending: allow, prints nothing"       allowed

# a pending teammate whose window is still there
mk '✦ alpha'; pend alpha
run_hook
check "pending name with a window: block text"        blocked "$RA"
check "block: the pending file keeps the name"        test "$(<$PF)" = alpha
check "block: counter is <hash> 1"                    zsh -c '[[ "$(<$1)" == <->" 1" ]]' _ "$CF"

# only a lead inside tmux is guarded
AGENT_BOARD_LEAD= run_hook
check "not a lead: allow"                             allowed
check "not a lead: pending file untouched"            test "$(<$PF)" = alpha
( unset TMUX; run_hook; allowed ); check "no \$TMUX: allow"  test $? -eq 0

# two names, one window gone: the file is rewritten, the block names only the one left
pend alpha beta alpha
run_hook
check "one of two gone: block names only alpha"       blocked "$RA"
check "one of two gone: file rewritten to alpha"      test "$(<$PF)" = alpha
mk '✦ beta'; pend alpha beta
run_hook
check "two left: both named, in file order"           blocked "teammate(s) alpha beta still shutting down: run tmux-ctl wait-gone alpha beta, then continue"
kw '✦ beta'

# names match exactly: `✦ alpha-2` is not `✦ alpha`; another session's window does not count
kw '✦ alpha'; mk '✦ alpha-2'; tt new-session -d -s other -n '✦ alpha' -c "$TT_DIR" 'sleep 300'
pend alpha
run_hook
check "window gone (a longer name and another session's window remain): allow"  allowed
check "window gone: pending file deleted"             test ! -e "$PF"
check "window gone: counter deleted"                  test ! -e "$CF"
kw '✦ alpha-2'

# handoff marker
reset; mkdir -p "${MF:h}"; : > "$MF"
run_hook
check "handoff marker: block text"                    blocked "$RH"
mk '✦ alpha'; pend alpha
run_hook
check "teammate and handoff: both reasons"            blocked "$RA; $RH"
check "a changed reason restarts the count at 1"      zsh -c '[[ "$(<$1)" == <->" 1" ]]' _ "$CF"
rm -f "$MF"

# loop cap: the same reason blocks three times, the 4th is allowed and logged, then the count starts again
reset; pend alpha
for i in 1 2 3; do run_hook; check "loop cap: stop $i blocks"  blocked "$RA"; done
check "loop cap: counter says 3"                      zsh -c '[[ "$(<$1)" == <->" 3" ]]' _ "$CF"
run_hook
check "loop cap: 4th identical stop is allowed, prints nothing"  allowed
check "loop cap: one log line"                        test "$(wc -l < "$LOG" | tr -d ' ')" = 1
check "loop cap: log line = UTC time, session id, pending reason"  zsh -c '[[ "$(<$1)" == [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z" $2 allowed after 3 blocks: $3" ]]' _ "$LOG" "$SID" "$RA"
check "loop cap: counter reset"                       test ! -e "$CF"
check "loop cap: pending file kept"                   test "$(<$PF)" = alpha
run_hook
check "loop cap: the next stop blocks again"          blocked "$RA"

# another session's pending file is not this session's
reset; pend alpha
run_hook 99999999-2222-3333-4444-555555555555
check "another session id: allow"                     allowed
check "another session id: this file untouched"       test "$(<$PF)" = alpha

# fail-open
print -r -- 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed stdin: silent exit 0"                allowed
print -r -- '{"hook_event_name":"Stop"}' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "no session_id: silent exit 0"                  allowed
run_hook '../shutdown-pending/'"$SID"
check "session_id that is not a plain id: allow"      allowed
check "session_id that is not a plain id: file untouched"  test "$(<$PF)" = alpha
TMUX="$TT_DIR/no-such-socket,1,0" run_hook
check "tmux unreachable: silent exit 0"               allowed
check "tmux unreachable: pending file kept"           test "$(<$PF)" = alpha
kw '✦ alpha'
check "script is executable"                          test -x "$H"
tt_done
```

- [ ] **Step 2: Run the test to see it fail**

Run: `zsh tools/tests/test_lead_stop_guard.zsh`
Expected: last line `27 FAILED`, because the script does not exist. The eight checks that only expect a file to be untouched or absent already pass.

- [ ] **Step 3: Implement**

Create `claude/plugin/scripts/lead-stop-guard.sh` and make it executable (`chmod +x claude/plugin/scripts/lead-stop-guard.sh`):

```zsh
#!/usr/bin/env zsh
# lead-stop-guard.sh — Stop hook: a lead does not end its turn while a teammate it asked to shut down still has its
# `✦ <name>` window (names recorded by shutdown-record.sh), or while a self-started handoff has not relayed
# (`tmux-ctl handoff-mark`). It prints {"decision":"block","reason":…}; the reason tells the lead what to run.
# docs/superpowers/specs/2026-11-10-queue-reliability-design.md §3.
# Guarded: AGENT_BOARD_LEAD=1 (exported by bin/claude-orchestrator into the lead's own process) and $TMUX set.
# Loop cap: <state>/stop-guard/<session_id> holds "<cksum of the reason> <count>"; the same reason a 4th time in a row
# is allowed, with one line in <state>/stop-guard.log (UTC time, session id, the pending reason).
# Fail-open: any error exits 0 with nothing printed. --scoped (the plugin registration) is accepted and changes nothing.
emulate -L zsh
[[ "$AGENT_BOARD_LEAD" == 1 && -n "$TMUX" ]] || { cat >/dev/null; exit 0 }
{
  input="$(cat)"
  sid="$(print -r -- "$input" | jq -r '.session_id // empty')"
  [[ "$sid" =~ '^[A-Za-z0-9_-]+$' ]] || exit 0
  root="${${(%):-%x}:A:h:h:h:h}"
  source "$root/tools/lib/tc-env.zsh" || exit 0
  source "$root/bin/_tc_bins.zsh" || exit 0
  S="$TC_STATE_DIR"
  pend="$S/shutdown-pending/$sid"; mark="$S/handoff-pending/$sid"; cnt="$S/stop-guard/$sid"
  reasons=()
  if [[ -f "$pend" ]]; then
    # exact window names in the lead's own session; a tmux error is not "no windows": fail open, keep the file
    sess="$(tc_tmux display -p -t "$TMUX_PANE" '#{session_name}')" || exit 0
    wins="$(tc_tmux list-windows -t "=$sess" -F '#{window_name}')" || exit 0
    typeset -U names; names=(${(f)"$(<$pend)"}); left=()
    for n in $names; do [[ $'\n'"$wins"$'\n' == *$'\n'"✦ $n"$'\n'* ]] && left+=("$n"); done
    if (( $#left )); then
      print -rl -- $left > "$pend.$$" && mv "$pend.$$" "$pend"
      reasons+=("teammate(s) ${(j: :)left} still shutting down: run tmux-ctl wait-gone ${(j: :)left}, then continue")
    else rm -f "$pend"; fi
  fi
  [[ -e "$mark" ]] && reasons+=("a self-started handoff has not relayed: run tmux-ctl relay <doc> --old-session $sid (handoff skill step 5)")
  if (( ! $#reasons )); then rm -f "$cnt"; exit 0; fi
  reason="${(j:; :)reasons}"
  h="$(print -rn -- "$reason" | cksum)"; h="${h%% *}"
  oh=; oc=; [[ -f "$cnt" ]] && read -r oh oc < "$cnt"
  if [[ "$oh" == "$h" && "$oc" == <-> ]]; then n=$(( oc + 1 )); else n=1; fi
  if (( n >= 4 )); then
    print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) $sid allowed after 3 blocks: $reason" >> "$S/stop-guard.log"
    rm -f "$cnt"; exit 0
  fi
  mkdir -p "${cnt:h}" && print -r -- "$h $n" > "$cnt" || exit 0
  jq -cn --arg r "$reason" '{decision:"block",reason:$r}'
} 2>/dev/null
exit 0
```

Notes:
- It sources `tools/lib/tc-env.zsh` the way `claude/plugin/scripts/worktree-sweep.sh` does, with one difference that changes behaviour: when the file cannot be loaded, worktree-sweep prints a message and falls back to the default state dir; this script exits 0 silently, because a Stop hook that prints anything but its block line is a bug. It also sources `bin/_tc_bins.zsh` for `tc_tmux` (the same server the lead is in, from `$TMUX`).
- The whole body runs in `{ … } 2>/dev/null`, and every tmux call that fails ends the script with `exit 0`: a tmux error must never read as "no windows" (that would delete the pending file).
- Probed on 2026-11-16 with a real `claude -p` Stop hook (Claude Code 2.1.325): stdin carries `session_id`, `hook_event_name: "Stop"`, `stop_hook_active`; printing `{"decision":"block","reason":…}` with exit 0 makes Claude continue the turn; the hook's environment has the lead's `AGENT_BOARD_LEAD`, `TMUX`, `TMUX_PANE`.

- [ ] **Step 4: Run the test to see it pass**

Run: `zsh tools/tests/test_lead_stop_guard.zsh`
Expected: last line `ALL PASS` (35 `ok` lines), and `grep -c '^FAIL'` over the output is 0.

- [ ] **Step 5: Mutation check (run each, report the failing lines, then restore the file)**

Mutation, cap at the 5th stop: in `claude/plugin/scripts/lead-stop-guard.sh` change

```zsh
(( n >= 4 ))
```
to

```zsh
(( n >= 5 ))
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - loop cap: 4th identical stop is allowed, prints nothing
```

Restore the line and run the test again: `ALL PASS`.

Mutation, drop the lead check: in `claude/plugin/scripts/lead-stop-guard.sh` change

```zsh
[[ "$AGENT_BOARD_LEAD" == 1 && -n "$TMUX" ]]
```
to

```zsh
[[ -n "$TMUX" ]]
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - not a lead: allow
```

Restore the line and run the test again: `ALL PASS`.

Mutation, list every session's windows: in `claude/plugin/scripts/lead-stop-guard.sh` change

```zsh
list-windows -t "=$sess"
```
to

```zsh
list-windows -a
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - window gone (a longer name and another session's window remain): allow
```

Restore the line and run the test again: `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add claude/plugin/scripts/lead-stop-guard.sh tools/tests/test_lead_stop_guard.zsh
git commit -m "feat(plugin): lead-stop-guard blocks a stop that waits on a shutdown or relay"
```

End the commit message with the attribution trailer your harness specifies. Stage only these paths.

```json:metadata
{"files": ["claude/plugin/scripts/lead-stop-guard.sh", "tools/tests/test_lead_stop_guard.zsh"], "verifyCommand": "zsh tools/tests/test_lead_stop_guard.zsh", "acceptanceCriteria": ["allow at once unless AGENT_BOARD_LEAD=1 and $TMUX set", "pending name with a ✦ window: one line {\"decision\":\"block\",\"reason\":\"teammate(s) <names> still shutting down: run tmux-ctl wait-gone <names>, then continue\"}", "gone names dropped, file rewritten; none left: file and counter deleted, allow; exact names, own session only", "handoff marker: block with the relay reason; both reasons joined by '; '", "loop cap: 3 blocks, 4th allowed + one stop-guard.log line '<UTC> <session id> allowed after 3 blocks: <reason>', counter reset; changed reason restarts at 1", "fail-open: bad stdin, bad session_id, tmux unreachable: exit 0, silent, pending file kept"], "modelTier": "mechanical"}
```

### Task 5: Register both hooks

**Goal:** `claude/plugin/hooks/hooks.json` runs `shutdown-record.sh` on PostToolUse(SendMessage) and `lead-stop-guard.sh` on Stop, and the plugin still validates (spec §3, Testing).

**Files:**
- Modify: `claude/plugin/hooks/hooks.json`
- Modify: `tools/tests/test_plugin.zsh` (three checks before `check "settings.json no longer registers hooks…"`)

**Acceptance Criteria:**
- [ ] PostToolUse has one entry with matcher `SendMessage` whose only hook is `"${CLAUDE_PLUGIN_ROOT}/scripts/shutdown-record.sh" --scoped`, timeout 5, not async (it must finish before the turn goes on).
- [ ] A new `Stop` event has one entry with no matcher whose only hook is `"${CLAUDE_PLUGIN_ROOT}/scripts/lead-stop-guard.sh" --scoped`, timeout 10, not async.
- [ ] `check "plugin manifests valid"` in `test_plugin.zsh` passes: it runs `claude plugin validate claude/plugin` when the CLI is there.
- [ ] Every existing check passes, among them `hooks.json uses CLAUDE_PLUGIN_ROOT/scripts for all four hooks` (every command ends in `.sh" --scoped`).

**Verify:** `zsh tools/tests/test_plugin.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test**

In `tools/tests/test_plugin.zsh`, insert this block immediately before the line that starts with `check "settings.json no longer registers hooks` (it occurs once):

```zsh
check "hooks.json registers shutdown-record on PostToolUse SendMessage, --scoped, timeout 5, not async" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]["PostToolUse"]
hit = [(e["matcher"], h) for e in d for h in e["hooks"] if h["command"].endswith("/scripts/shutdown-record.sh\" --scoped")]
assert len(hit) == 1 and hit[0][0] == "SendMessage" and hit[0][1]["timeout"] == 5 and not hit[0][1].get("async"), hit
PY
check "hooks.json registers lead-stop-guard on Stop (no matcher), --scoped, timeout 10, not async" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]["Stop"]
hit = [(e.get("matcher"), h) for e in d for h in e["hooks"] if h["command"].endswith("/scripts/lead-stop-guard.sh\" --scoped")]
assert len(hit) == 1 and hit[0][0] is None and hit[0][1]["timeout"] == 10 and not hit[0][1].get("async"), hit
PY
check "shutdown-record.sh and lead-stop-guard.sh are executable" test -x "$P/scripts/shutdown-record.sh" -a -x "$P/scripts/lead-stop-guard.sh"
```

- [ ] **Step 2: Run the test to see it fail**

Run: `zsh tools/tests/test_plugin.zsh`
Expected: last line `2 FAILED`, because hooks.json has no `SendMessage` entry and no `Stop` event (the third new check, on the executable bits, already passes after Tasks 2 and 4).

- [ ] **Step 3: Implement**

Replace the whole content of `claude/plugin/hooks/hooks.json` with:

```json
{
  "modules": ["../mods/index.js"],
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/context-inject.sh\" --scoped", "timeout": 5 },
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/telegram-env-scrub.sh\" --scoped", "timeout": 5 }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/kill-guard.sh\" --scoped", "timeout": 10 }
        ]
      },
      {
        "matcher": "Agent",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/sdd-call-guard.sh\" --scoped", "timeout": 10 },
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/agent-name-guard.sh\" --scoped", "timeout": 10 }
        ]
      },
      {
        "matcher": "AskUserQuestion",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/plan-handoff-guard.sh\" --scoped", "timeout": 10 }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/bash-mirror.sh\" --scoped", "timeout": 5, "async": true },
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/worktree-sweep.sh\" --scoped", "timeout": 5, "async": true }
        ]
      },
      {
        "matcher": "Write|Edit|MultiEdit|Artifact|mcp__claude_ai_Claude_Docs__batch|mcp__claude_ai_Claude_Docs__create|mcp__claude_ai_Claude_Docs__update",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/artifact-register.sh\" --scoped", "timeout": 5, "async": true }
        ]
      },
      {
        "matcher": "SendMessage",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/shutdown-record.sh\" --scoped", "timeout": 5 }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/lead-stop-guard.sh\" --scoped", "timeout": 10 }
        ]
      }
    ],
    "PostToolUseFailure": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/bash-mirror.sh\" --scoped", "timeout": 5, "async": true }
        ]
      }
    ]
  }
}
```

Notes:
- `test_plugin.zsh` runs three headless `claude -p --model haiku` probes and takes about two minutes: run it with `tmux-ctl run -t 600 tests "zsh tools/tests/test_plugin.zsh"`.
- The only change to hooks.json is the new `SendMessage` entry at the end of `PostToolUse` and the new `Stop` event after it; everything else in the file below is the current content.
- `claude plugin validate` prints `Validation passed with warnings` for the current file too; the warnings are not new.

- [ ] **Step 4: Run the test to see it pass**

Run: `zsh tools/tests/test_plugin.zsh`
Expected: last line `ALL PASS`, and `grep -c '^FAIL'` over the output is 0.

- [ ] **Step 5: Mutation check (run each, report the failing lines, then restore the file)**

Mutation, make the Stop hook async: in `claude/plugin/hooks/hooks.json` change

```json
lead-stop-guard.sh\" --scoped", "timeout": 10 }
```
to

```json
lead-stop-guard.sh\" --scoped", "timeout": 10, "async": true }
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - hooks.json registers lead-stop-guard on Stop (no matcher), --scoped, timeout 10, not async
```

Restore the line and run the test again: `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add claude/plugin/hooks/hooks.json tools/tests/test_plugin.zsh
git commit -m "feat(plugin): register shutdown-record and lead-stop-guard"
```

End the commit message with the attribution trailer your harness specifies. Stage only these paths.

```json:metadata
{"files": ["claude/plugin/hooks/hooks.json", "tools/tests/test_plugin.zsh"], "verifyCommand": "zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["PostToolUse matcher SendMessage -> shutdown-record.sh --scoped, timeout 5, not async", "Stop (no matcher) -> lead-stop-guard.sh --scoped, timeout 10, not async", "claude plugin validate claude/plugin passes (check 'plugin manifests valid')", "every existing test_plugin check passes"], "modelTier": "mechanical"}
```

### Task 6: Awake hold bound to the queue

**Goal:** `tmux-ctl awake on --queue` watches the tmux server, a plain `on` re-points a live plain hold that watches another pid, `status` shows a queue hold, and the lid watchdog follows the hold's watched pid (spec §4).

**Files:**
- Modify: `tools/lib/awake.zsh` (header comment, `_aw_queue_recorded`, the whole `on)` case, `status)`, `_watchdog)`, the final usage line)
- Modify: `bin/tmux-ctl` (the two `awake` help lines)
- Modify: `tools/tests/test_ctl_awake.zsh` (a block before `# --- unsupported`)

**Acceptance Criteria:**
- [ ] `awake on --queue [--lid]`: the watched pid is `tmux display -p '#{pid}'` of the caller's server through `tc_tmux`; prints `awake: on (pid <caffeinate>, watching <server pid>)`; `awake.json` has `"queue": true`. Spec: "the watched pid is the tmux server's … `awake.json` gains `\"queue\": true`".
- [ ] `--queue` with `--pid`: `usage: tmux-ctl awake on [--queue | --pid N] [--lid]` on stderr, exit 2, hold unchanged. `--queue` when the server cannot be reached: `awake: no tmux server; run on without --queue`, exit 1, nothing started.
- [ ] Any `on` over a live queue hold prints exactly `awake: already on (queue)` and changes nothing.
- [ ] Plain `on` over a live plain hold whose watched pid is not the caller's claude ancestor (or not `--pid N`): the old caffeinate is killed, a new one watches the caller, `lid` and `watchdogPid` stay as they are, prints `awake: on (re-pointed from <old> to <new>)`. `on --queue` over a plain hold re-points to the tmux server and sets `queue`. Same watched pid, or a caller with no claude ancestor and no `--pid`: `awake: already on (pid …, since …)`, unchanged.
- [ ] `status` prints the line `queue: on` after the `on (…)` line for a queue hold, and no `queue` line otherwise.
- [ ] The watchdog reads `.pid` from `awake.json` each tick, so after a re-point the lid hold survives the death of the first owner; for `on --queue --lid` the watchdog's argument is the tmux server pid.
- [ ] Every existing awake check passes, and the test leaves no caffeinate stub or watchdog behind.

**Verify:** `zsh tools/tests/test_ctl_awake.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test**

In `tools/tests/test_ctl_awake.zsh`, insert this block immediately before the line that starts with `# --- unsupported: a PATH without caffeinate` (it occurs once):

```zsh
# --- queue holds (spec 2026-11-10-queue-reliability §4): bound to the tmux server, so a relay does not end them
allow; $C awake off >/dev/null; rm -f "$S/caffeinate.args" "$S/sudo.args"
SRV="$(tt display -p '#{pid}')"   # the scratch tmux server: what `tmux display -p '#{pid}'` prints (probed on tmux 3.8)
out="$($C awake on --queue)"; rc=$?
cpq="$(lidfile .caffeinatePid)"
check "queue on: watches the tmux server pid"   test "$out" = "awake: on (pid $cpq, watching $SRV)" -a $rc -eq 0
check "queue on: caffeinate -i -s -w <server pid>"  test "$(<$S/caffeinate.args)" = "-i -s -w $SRV"
check "queue on: awake.json has queue true and the server pid"  test "$(lidfile .queue)" = true -a "$(lidfile .pid)" = "$SRV"
out="$($C awake status)"
check "status: queue line for a queue hold"     zsh -c '[[ $1 == "on (pid $2, watching $3, since "*$'"'"'\nqueue: on\nlid: off\n'"'"'* ]]' _ "$out" $cpq $SRV
out="$($C awake on --pid $W)"
check "non-queue on over a queue hold: already on (queue)"  test "$out" = "awake: already on (queue)"
out="$("$S/real/claude-fake" -c "$C awake on; true")"
check "a claude's own on over a queue hold: already on (queue)"  test "$out" = "awake: already on (queue)"
out="$($C awake on --queue)"
check "queue on twice: already on (queue)"      test "$out" = "awake: already on (queue)"
check "queue hold unchanged by all three"       test "$(lidfile .pid)" = "$SRV" -a "$(lidfile .caffeinatePid)" = "$cpq" -a "$(nstub)" = 1
out="$($C awake on --queue --pid $W 2>&1)"; rc=$?
check "--queue with --pid: usage, exit 2"       test $rc -eq 2 -a "$out" = "usage: tmux-ctl awake on [--queue | --pid N] [--lid]"
check "--queue with --pid: hold unchanged"      test "$(lidfile .caffeinatePid)" = "$cpq"
$C awake off >/dev/null
out="$(TMUX="$S/no-such-socket,1,0" $C awake on --queue 2>/dev/null)"; rc=$?
check "--queue with no tmux server: message, exit 1"  test "$out" = "awake: no tmux server; run on without --queue" -a $rc -eq 1
check "--queue with no tmux server: nothing started"  test "$(nstub)" = 0 -a ! -e "$AF"

# --- re-point: a live non-queue hold watching another pid moves to the caller
sleep 300 & foreign=$!
$C awake on --pid $foreign >/dev/null; cpf="$(lidfile .caffeinatePid)"
out="$($C awake status)"
check "status: no queue line for a plain hold"  zsh -c '[[ $1 != *queue* ]]' _ "$out"
out="$(TC_AWAKE_ANCESTOR=zz-no-such-name $C awake on)"
check "caller with no claude ancestor: the foreign hold is kept"  zsh -c '[[ $1 == "awake: already on (pid $2, since "*")" ]]' _ "$out" $cpf
out="$("$S/real/claude-fake" -c "$C awake on; true")"
me="$(lidfile .pid)"
check "re-point: message names old and new pid" test "$out" = "awake: on (re-pointed from $foreign to $me)"
check "re-point: the new pid is the caller's claude ancestor, not the foreign pid"  test -n "$me" -a "$me" != "$foreign" -a "$me" != "$W"
check "re-point: old caffeinate killed, one running"  zsh -c '! kill -0 $1 2>/dev/null && [[ $2 == 1 ]]' _ $cpf "$(nstub)"
check "re-point: awake.json points at the new caffeinate, no queue"  test "$(lidfile .caffeinatePid)" != "$cpf" -a "$(lidfile '.queue // false')" = false
check "re-point: the recorded pid is a caffeinate"  test "$(basename "$(ps -o comm= -p "$(lidfile .caffeinatePid)")")" = caffeinate
out="$($C awake on --pid $W)"
check "re-point with --pid: to that pid"        test "$out" = "awake: on (re-pointed from $me to $W)" -a "$(lidfile .pid)" = "$W"
out="$($C awake on --pid $W)"
check "same owner again: already on, no re-point"  zsh -c '[[ $1 == "awake: already on (pid "* ]]' _ "$out"
$C awake off >/dev/null

# --- re-point keeps lid and watchdogPid; the watchdog follows the re-pointed pid
rm -f "$S/sudo.args"
$C awake on --lid --pid $foreign >/dev/null; wdr="$(lidfile .watchdogPid)"; WDS+=($wdr)
out="$($C awake on --queue --lid)"
check "queue on over a plain hold: re-pointed to the tmux server"  test "$(print -r -- "$out" | head -1)" = "awake: on (re-pointed from $foreign to $SRV)"
check "queue re-point: queue true"              test "$(lidfile .queue)" = true -a "$(lidfile .pid)" = "$SRV"
check "queue re-point: lid and watchdogPid kept"  test "$(lidfile .lid)" = true -a "$(lidfile .watchdogPid)" = "$wdr"
check "queue re-point: disablesleep 1 not called again"  test "$(ndis 1)" = 1
kill $foreign; sleep 2.5   # two watchdog ticks after the first owner died
check "watchdog follows the re-pointed pid: lid hold still on"  test -e "$S/sleepdisabled" -a "$(lidfile .lid)" = true
check "watchdog follows the re-pointed pid: still running"  wdalive "$wdr"
$C awake off >/dev/null
check "off ends a queue hold"                   test ! -e "$AF" -a "$(nstub)" = 0 -a ! -e "$S/sleepdisabled"
$C awake on --queue --lid >/dev/null; wdq="$(lidfile .watchdogPid)"; WDS+=($wdq)
check "queue + lid: the watchdog's lead pid is the tmux server"  zsh -c '[[ "$(ps -o args= -p $1)" == *"awake _watchdog $2" ]]' _ "$wdq" "$SRV"
$C awake off >/dev/null
deny
```

- [ ] **Step 2: Run the test to see it fail**

Run: `zsh tools/tests/test_ctl_awake.zsh`
Expected: last line `21 FAILED`, because `--queue` is an unknown option today (usage, exit 2), a second `on` always answers `already on`, and `status` has no queue line.

- [ ] **Step 3: Implement**

In `tools/lib/awake.zsh`, replace

```zsh
# State: $TC_STATE_DIR/awake.json = {"pid", "caffeinatePid", "since"} plus "lid": true, "watchdogPid" in lid mode (spec §1b).
```
with

```zsh
# State: $TC_STATE_DIR/awake.json = {"pid", "caffeinatePid", "since"} plus "lid": true, "watchdogPid" in lid mode (spec §1b).
# `on --queue` watches the tmux server instead (a relay replaces the lead, not the server) and records "queue": true;
# a plain `on` over a live plain hold that watches another pid re-points it (spec 2026-11-10-queue-reliability §4).
```

In `tools/lib/awake.zsh`, insert this block immediately before the line that starts with `_aw_lid_recorded() {` (it occurs once):

```zsh
_aw_queue_recorded() { [[ "$(jq -r '.queue // false' "$(_aw_file)" 2>/dev/null)" == true ]] }
```

In `tools/lib/awake.zsh`, replace everything from the line that starts with `    on)` up to, but not including, the next line that starts with `    off)` with:

```zsh
    on)
      local pid="" lid=0 queue=0 old="" usage="usage: tmux-ctl awake on [--queue | --pid N] [--lid]"
      while (( $# )); do
        case "$1" in --pid) pid="$2"; shift 2 ;; --lid) lid=1; shift ;; --queue) queue=1; shift ;; *) print -u2 -r -- "$usage"; return 2 ;; esac
      done
      (( queue )) && [[ -n "$pid" ]] && { print -u2 -r -- "$usage"; return 2 }
      if (( queue )); then   # the tmux server outlives every lead of the queue
        pid="$(tc_tmux display -p '#{pid}' 2>/dev/null)"
        [[ "$pid" == <-> ]] || { print -r -- "awake: no tmux server; run on without --queue"; return 1 }
      fi
      if cur="$(_aw_current)"; then
        local -a c=("${(@ps:\t:)cur}")
        if _aw_queue_recorded; then   # a queue hold is never re-pointed
          print -r -- "awake: already on (queue)"
          (( lid )) && _aw_lid_on
          _aw_stale_warn; return 0
        fi
        [[ -n "$pid" ]] || pid="$(_aw_claude_pid)"   # no claude ancestor: the caller is unknown, so the hold is kept
        if (( ! queue )) && [[ -z "$pid" || "$pid" == "$c[2]" ]]; then
          print -r -- "awake: already on (pid $c[1], since $c[3])"
          (( lid )) && _aw_lid_on
          _aw_stale_warn; return 0
        fi
        kill "$c[1]" 2>/dev/null; old="$c[2]"   # re-point: the hold watched another pid
      fi
      [[ -n "$pid" ]] || pid="$(_aw_claude_pid)" || { print -r -- "awake: no claude ancestor; pass --pid"; return 1 }
      caffeinate -i -s -w "$pid" >/dev/null 2>&1 </dev/null &!
      cp=$!
      since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      if [[ -n "$old" ]]; then   # keep lid and watchdogPid as they are; the watchdog reads .pid each tick
        _aw_edit ".pid = $pid | .caffeinatePid = $cp | .since = \"$since\" | $( (( queue )) && print -r -- '.queue = true' || print -r -- 'del(.queue)' )"
      else
        jq -n --argjson pid "$pid" --argjson cp "$cp" --arg since "$since" --argjson q "$queue" '{pid:$pid, caffeinatePid:$cp, since:$since} + (if $q == 1 then {queue:true} else {} end)' > "$f"
      fi
      _aw_on_battery && print -r -- "awake: on battery: idle sleep is held, but a closed lid still sleeps; plug in for the night"
      if [[ -n "$old" ]]; then print -r -- "awake: on (re-pointed from $old to $pid)"
      else print -r -- "awake: on (pid $cp, watching $pid)"; fi
      (( lid )) && _aw_lid_on
      _aw_stale_warn; return 0 ;;
```

In `tools/lib/awake.zsh`, replace

```zsh
        print -r -- "on (pid $c[1], watching $c[2], since $c[3])"
      else print -r -- "off"; fi
```
with

```zsh
        print -r -- "on (pid $c[1], watching $c[2], since $c[3])"
        _aw_queue_recorded && print -r -- "queue: on"
      else print -r -- "off"; fi
```

In `tools/lib/awake.zsh`, replace

```zsh
      local lead="$1" tick="${TC_AWAKE_TICK:-60}" pct wp
```
with

```zsh
      local lead="$1" tick="${TC_AWAKE_TICK:-60}" pct wp fl
```

In `tools/lib/awake.zsh`, replace

```zsh
          [[ -n "$wp" && "$wp" != "$$" ]] && return 0
        fi
```
with

```zsh
          [[ -n "$wp" && "$wp" != "$$" ]] && return 0
          fl="$(jq -r '.pid // empty' "$f" 2>/dev/null)"; [[ "$fl" == <-> ]] && lead="$fl"   # a re-pointed hold: follow its watched pid
        fi
```

In `tools/lib/awake.zsh`, replace

```zsh
    *) print -u2 "usage: tmux-ctl awake on [--pid N] [--lid] | off | status | sleeps <since> | lid-setup"; return 2 ;;
```
with

```zsh
    *) print -u2 "usage: tmux-ctl awake on [--queue | --pid N] [--lid] | off | status | sleeps <since> | lid-setup"; return 2 ;;
```

In `bin/tmux-ctl`, replace

```zsh
#   tmux-ctl awake on [--pid N] [--lid]|off|status|sleeps <since>|lid-setup
#                                          hold the Mac awake (caffeinate) while the queue runs; sleeps lists Sleep/Wake lines since a time
```
with

```zsh
#   tmux-ctl awake on [--queue | --pid N] [--lid]|off|status|sleeps <since>|lid-setup
#                                          hold the Mac awake (caffeinate) while the queue runs (--queue: bound to the tmux server, survives a relay); sleeps lists Sleep/Wake lines since a time
```

Notes:
- The test uses stubs for `caffeinate`, `pmset` and `sudo` on a temp PATH (never the real ones) and the scratch tmux server from `tt_setup`; `SRV` is that server's real pid.
- The tmux-ctl help lines change in place: the line count stays the same, so the help range stays `2,47p`.
- `_aw_edit` rewrites `awake.json` through a temp file and `mv`, so the watchdog never reads a half-written file.
- The test takes about 45 s. If a watchdog check fails only now and then, look at timing first: `TC_AWAKE_TICK=1` makes the watchdog tick every second, and the re-point check sleeps 2.5 s (two ticks).

- [ ] **Step 4: Run the test to see it pass**

Run: `zsh tools/tests/test_ctl_awake.zsh`
Expected: last line `ALL PASS` (149 `ok` lines), and `grep -c '^FAIL'` over the output is 0.

- [ ] **Step 5: Mutation check (run each, report the failing lines, then restore the file)**

Mutation, make the watchdog ignore the file's pid: in `tools/lib/awake.zsh` change

```zsh
[[ "$fl" == <-> ]] && lead="$fl"
```
to

```zsh
:
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - watchdog follows the re-pointed pid: lid hold still on
```

Restore the line and run the test again: `ALL PASS`.

Mutation, let a plain `on` re-point a queue hold: in `tools/lib/awake.zsh` change

```zsh
        if _aw_queue_recorded; then   # a queue hold is never re-pointed
```
to

```zsh
        if false; then
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - non-queue on over a queue hold: already on (queue)
```

Restore the line and run the test again: `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add tools/lib/awake.zsh bin/tmux-ctl tools/tests/test_ctl_awake.zsh
git commit -m "feat(tmux-ctl): awake on --queue binds the hold to the tmux server"
```

End the commit message with the attribution trailer your harness specifies. Stage only these paths.

```json:metadata
{"files": ["tools/lib/awake.zsh", "bin/tmux-ctl", "tools/tests/test_ctl_awake.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_awake.zsh", "acceptanceCriteria": ["on --queue watches the tmux server pid (tc_tmux display -p '#{pid}'), awake.json has queue true", "--queue with --pid: usage, exit 2; no tmux server: 'awake: no tmux server; run on without --queue', exit 1", "any on over a queue hold: 'awake: already on (queue)', unchanged", "plain on over a plain hold watching another pid re-points: 'awake: on (re-pointed from <old> to <new>)', lid/watchdogPid kept; on --queue over a plain hold re-points to the server", "status prints 'queue: on' only for a queue hold", "watchdog follows awake.json .pid after a re-point; queue+lid watchdog watches the server pid", "all existing awake checks pass; no stub or watchdog left"], "modelTier": "standard"}
```

### Task 7: Real sleeps only

**Goal:** `tmux-ctl awake sleeps <since>` prints one line per real sleep period; `--all` prints the old output (spec §5).

**Files:**
- Modify: `tools/lib/awake.zsh` (`_AW_NOT_REAL` before `_aw_epoch`, the whole `sleeps)` case, the final usage line)
- Modify: `bin/tmux-ctl` (the two `awake` help lines)
- Modify: `tools/tests/test_ctl_awake.zsh` (the `pmset` stub's log line and its comment, the whole `# --- sleeps` block)
- Create: `tools/tests/fixtures/awake/log-sleeps-kinds.txt` (written by the generator in Step 1)
- Modify: `tools/tests/fixtures/awake/README.md` (one line)

**Acceptance Criteria:**
- [ ] Default output: one line per real sleep period, `<start> – <end> <reason>` in local `YYYY-MM-DD HH:MM:SS`, where the end is the next `Wake` line's time (never a DarkWake) and `…` when there is none yet.
- [ ] Real = a Sleep line whose reason is not `Maintenance Sleep`, `Sleep Service Back to Sleep` or `Notification Wake Back to Sleep` (a deny-list: the fixture's `Software Sleep` shows). DarkWake lines are dropped.
- [ ] On `log-sleeps-kinds.txt` the output is exactly the five `KINDS` lines of the test; a period that starts before `<since>` is left out; ISO UTC and local `<since>` give the same output.
- [ ] `--all`, before or after `<since>`, prints the old format (`<time> <Sleep|Wake|DarkWake> <reason>`), one line per fixture line that is not a `Wake Requests` line.
- [ ] No time, or two times: `usage: tmux-ctl awake sleeps <since> [--all]`, exit 2.
- [ ] Every other awake check passes.

**Verify:** `zsh tools/tests/test_ctl_awake.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test**

In `tools/tests/test_ctl_awake.zsh`, replace

```zsh
# pmset: $S/batt.cur (a fixture path) overrides the battery capture at call time (a running watchdog sees changes);
```
with

```zsh
# pmset: $S/batt.cur (a fixture path) overrides the battery capture at call time (a running watchdog sees changes);
# $S/log.cur (a fixture path) overrides the `pmset -g log` capture the same way;
```

In `tools/tests/test_ctl_awake.zsh`, replace

```zsh
  "-g log")  cat "$FX/log-sleeps.txt" ;;
```
with

```zsh
  "-g log")  if [ -f "$S/log.cur" ]; then cat "\$(cat "$S/log.cur")"; else cat "$FX/log-sleeps.txt"; fi ;;
```

In `tools/tests/test_ctl_awake.zsh`, replace everything from the line that starts with `# --- sleeps` up to, but not including, the next line that starts with `# --- lid mode` with:

```zsh
# --- sleeps
out="$($C awake sleeps '2026-11-07 10:28' --all)"
check "sleeps --all local: first line"         test "$(print -r -- "$out" | head -1)" = "2026-11-07 10:28:22 DarkWake Deep Idle"
check "sleeps --all local: sleep reason"       sh -c "printf %s '$out' | grep -qx '2026-11-07 10:28:24 Sleep Sleep Service Back to Sleep'"
check "sleeps --all local: nothing before the cutoff"  test -z "$(print -r -- "$out" | grep '10:12:')"
check "sleeps --all: Wake Requests excluded"   test -z "$(print -r -- "$out" | grep -i 'request')"
iso="$($C awake sleeps '2026-11-07T15:28:00Z' --all)"
check "sleeps --all ISO UTC == local equivalent"  test "$iso" = "$out"
all="$($C awake sleeps --all '2000-01-01 00:00')"
check "sleeps --all: a real Wake line is listed"  test "$(print -r -- "$all" | awk '$3=="Wake"' | wc -l | tr -d ' ')" -ge 1
check "sleeps --all: only three types"         test -z "$(print -r -- "$all" | awk '$3!="Sleep"&&$3!="Wake"&&$3!="DarkWake"')"
check "sleeps --all: line count = fixture minus Wake Requests"  test "$(print -r -- "$all" | wc -l | tr -d ' ')" = "$(grep -vc 'Wake Requests' "$FX/log-sleeps.txt")"
out="$($C awake sleeps '2099-01-01 00:00' --all)"; rc=$?
check "sleeps --all: none prints nothing, exit 0"  test -z "$out" -a $rc -eq 0
# default: one line per real sleep period (spec 2026-11-10-queue-reliability §5)
out="$($C awake sleeps '2000-01-01 00:00')"
check "sleeps: the real capture has one real period (Low Power Sleep, ended by the next Wake)"  test "$out" = "2026-11-07 11:52:58 – 2026-11-09 10:30:32 Low Power Sleep"
print -r -- "$FX/log-sleeps-kinds.txt" > "$S/log.cur"   # one of every Sleep reason kind
KINDS=(
  "2026-11-10 20:31:19 – 2026-11-10 21:03:05 Idle Sleep"
  "2026-11-11 08:46:33 – 2026-11-11 08:59:20 Clamshell Sleep"
  "2026-11-11 09:30:00 – 2026-11-11 09:45:00 Low Power Sleep"
  "2026-11-11 10:00:00 – 2026-11-11 10:05:00 Software Sleep"
  "2026-11-11 23:00:00 – … Idle Sleep"
)
out="$($C awake sleeps '2000-01-01 00:00')"; rc=$?
check "sleeps: only real periods, each ended by the next Wake, the open one by …"  test "$out" = "${(F)KINDS}" -a $rc -eq 0
check "sleeps: no Maintenance, Sleep Service, Notification Wake or DarkWake line"  test -z "$(print -r -- "$out" | grep -E 'Maintenance|Sleep Service|Notification|DarkWake')"
check "sleeps: a reason not on the deny-list shows (Software Sleep)"  zsh -c '[[ $1 == *"Software Sleep"* ]]' _ "$out"
out="$($C awake sleeps '2026-11-11 09:00')"
check "sleeps: periods that start before the cutoff are left out"  test "$out" = "${(F)KINDS[3,5]}"
iso="$($C awake sleeps '2026-11-11T14:00:00Z')"
check "sleeps ISO UTC == local equivalent"     test "$iso" = "$out"
all="$($C awake sleeps '2000-01-01 00:00' --all)"
check "sleeps --all on the same log: every Sleep, Wake and DarkWake line"  test "$(print -r -- "$all" | wc -l | tr -d ' ')" = "$(grep -vc 'Wake Requests' "$FX/log-sleeps-kinds.txt")"
check "sleeps --all keeps the old line format"  test "$(print -r -- "$all" | sed -n 2p)" = "2026-11-10 20:45:00 DarkWake Deep Idle"
out="$($C awake sleeps '2099-01-01 00:00')"; rc=$?
check "sleeps: none prints nothing, exit 0"    test -z "$out" -a $rc -eq 0
$C awake sleeps >/dev/null 2>&1; check "sleeps without a time: exit 2"  test $? -eq 2
$C awake sleeps --all >/dev/null 2>&1; check "sleeps --all without a time: exit 2"  test $? -eq 2
$C awake sleeps '2026-11-11 09:00' extra >/dev/null 2>&1; check "sleeps with two times: exit 2"  test $? -eq 2
rm -f "$S/log.cur"
```

Append this line to the end of `tools/tests/fixtures/awake/README.md`:

```text
- `log-sleeps-kinds.txt`: **derived, not captured**: `pmset -g log` lines in the real layout (the same columns as `log-sleeps.txt`; the Sleep, DarkWake and Wake texts follow lines read from this Mac's log on 2026-11-16), with one Sleep line of every reason kind: Idle Sleep, Clamshell Sleep, Low Power Sleep, Maintenance Sleep, Sleep Service Back to Sleep, Notification Wake Back to Sleep, and `Software Sleep`, a made-up reason that stands for one the deny-list does not know. Written by the generator in `docs/superpowers/plans/2026-11-16-queue-reliability.md` Task 7. The `pmset` stub serves it when `$S/log.cur` names it.
```

Write the fixture: save this generator outside the repo (for example `$TMPDIR/mkfixture.zsh`) and run it once from the repo root with `zsh $TMPDIR/mkfixture.zsh`. It writes `tools/tests/fixtures/awake/log-sleeps-kinds.txt` (18 lines, tab-separated like the real capture). Check it: `shasum -a 256 tools/tests/fixtures/awake/log-sleeps-kinds.txt | cut -c1-16` → `9a4398dadee1c4df`.

```zsh
# writes tools/tests/fixtures/awake/log-sleeps-kinds.txt: `pmset -g log` lines in the real layout
# (<local time> <zone> <type padded to 20><TAB><text>), one of every Sleep reason kind
L() { print -r -- "$1 -0500 ${(r:20:)2}"$'\t'"$3" }
S() { L "$1" Sleep "Entering Sleep state due to '$2':TCPKeepAlive=active Using Batt (Charge:98%) $3 secs  " }
D() { L "$1" DarkWake "DarkWake from Deep Idle [CDNP] : due to NUB.SPMI0.SW3.IRQ nub-spmi0.0x02 rtc/Maintenance Using BATT (Charge:98%) 45 secs   " }
W() { L "$1" Wake "Wake from Deep Idle [CDNVA] : due to smc.sysState.Wake(0x70070000) lid SMC.OutboxNotEmpty/HID Activity Using BATT (Charge:98%) $2 secs  " }
R() { L "$1" "Wake Requests" '[*process=dasd request=SleepService deltaSecs=1012 wakeAt=2026-11-10 20:48:11 info="com.apple.dasd:503:com.apple.searchpartyd.OwnDevicePublish"]' }
{
  S '2026-11-10 20:31:19' 'Idle Sleep' 821
  R '2026-11-10 20:31:25'
  D '2026-11-10 20:45:00'
  S '2026-11-10 20:45:45' 'Maintenance Sleep' 1040
  W '2026-11-10 21:03:05' 425
  S '2026-11-10 21:10:00' 'Notification Wake Back to Sleep' 30
  W '2026-11-10 21:10:30' 2970
  S '2026-11-10 22:00:00' 'Sleep Service Back to Sleep' 2
  D '2026-11-10 22:00:02'
  S '2026-11-11 08:46:33' 'Clamshell Sleep' 207
  D '2026-11-11 08:50:00'
  W '2026-11-11 08:59:20' 1840
  S '2026-11-11 09:30:00' 'Low Power Sleep' 600
  S '2026-11-11 09:40:00' 'Idle Sleep' 300
  W '2026-11-11 09:45:00' 900
  S '2026-11-11 10:00:00' 'Software Sleep' 300
  W '2026-11-11 10:05:00' 46500
  S '2026-11-11 23:00:00' 'Idle Sleep' 0
} > tools/tests/fixtures/awake/log-sleeps-kinds.txt
```

- [ ] **Step 2: Run the test to see it fail**

Run: `zsh tools/tests/test_ctl_awake.zsh`
Expected: last line `7 FAILED`, because today `sleeps` prints every Sleep, Wake and DarkWake line, reads `--all` in first place as the time, and ignores a second time.

- [ ] **Step 3: Implement**

In `tools/lib/awake.zsh`, insert this block immediately before the line that starts with `_aw_epoch() {` (it occurs once):

```zsh
# Sleep reasons that are not a real sleep (the Mac was already asleep and went back to it). A deny-list: a reason
# that is not listed here counts as real, so a new one still shows in `awake sleeps`.
_AW_NOT_REAL=('Maintenance Sleep' 'Sleep Service Back to Sleep' 'Notification Wake Back to Sleep')
```

In `tools/lib/awake.zsh`, replace everything from the line that starts with `    sleeps)` up to, but not including, the next line that starts with `    *) print -u2 "usage: tmux-ctl awake on` with:

```zsh
    sleeps)
      # default: one line per real sleep period, "<start> – <end> <reason>"; --all: every Sleep, Wake and DarkWake line
      local all=0 sarg="" susage="usage: tmux-ctl awake sleeps <since> [--all]"
      while (( $# )); do
        if [[ "$1" == --all ]]; then all=1
        elif [[ -z "$sarg" ]]; then sarg="$1"
        else print -u2 -r -- "$susage"; return 2; fi
        shift
      done
      [[ -n "$sarg" ]] || { print -u2 -r -- "$susage"; return 2 }
      local from; from="$(_aw_epoch "$sarg")" || { print -u2 "awake: cannot read time '$sarg'"; return 2 }
      zmodload -F zsh/datetime b:strftime 2>/dev/null
      local line ts ty rest e reason lt pstart="" preason=""
      pmset -g log 2>/dev/null | awk '($4=="Sleep"||$4=="Wake"||$4=="DarkWake") && $5!="Requests"' | while IFS= read -r line; do
        ts="${line[1,25]}"; ty="${${(z)line}[4]}"; rest="${line#*$'\t'}"
        strftime -r -s e '%Y-%m-%d %H:%M:%S %z' "$ts" 2>/dev/null || continue
        if [[ "$ty" == Sleep ]]; then reason="${${rest#*\'}%%\'*}"
        else reason="${${rest#*from }%% \[*}"; fi
        strftime -s lt '%Y-%m-%d %H:%M:%S' "$e"
        if (( all )); then
          (( e >= from )) && print -r -- "$lt $ty $reason"
        elif [[ "$ty" == Sleep ]]; then   # a period opens at the first real Sleep line at or after <since>
          [[ -z "$pstart" ]] && (( e >= from )) && (( ! ${_AW_NOT_REAL[(Ie)$reason]} )) && { pstart="$lt"; preason="$reason" }
        elif [[ "$ty" == Wake && -n "$pstart" ]]; then   # and closes at the next Wake; DarkWake lines are dropped
          print -r -- "$pstart – $lt $preason"; pstart=""
        fi
      done
      [[ -n "$pstart" ]] && print -r -- "$pstart – … $preason"
      return 0 ;;
```

In `tools/lib/awake.zsh`, replace

```zsh
    *) print -u2 "usage: tmux-ctl awake on [--queue | --pid N] [--lid] | off | status | sleeps <since> | lid-setup"; return 2 ;;
```
with

```zsh
    *) print -u2 "usage: tmux-ctl awake on [--queue | --pid N] [--lid] | off | status | sleeps <since> [--all] | lid-setup"; return 2 ;;
```

In `bin/tmux-ctl`, replace

```zsh
#   tmux-ctl awake on [--queue | --pid N] [--lid]|off|status|sleeps <since>|lid-setup
#                                          hold the Mac awake (caffeinate) while the queue runs (--queue: bound to the tmux server, survives a relay); sleeps lists Sleep/Wake lines since a time
```
with

```zsh
#   tmux-ctl awake on [--queue | --pid N] [--lid]|off|status|sleeps <since> [--all]|lid-setup
#                                          hold the Mac awake (caffeinate) while the queue runs (--queue: bound to the tmux server, survives a relay); sleeps lists the real sleep periods since a time (--all: every Sleep/Wake line)
```

Notes:
- Keep one blank line between the `_AW_NOT_REAL` block and `_aw_epoch() {`.
- The `while read` loop is the last command of its pipeline, which zsh runs in the current shell: `pstart` and `preason` are still set after the loop.
- Two real Sleep lines with no Wake between them are one period, with the first line's reason (assumption A5).

- [ ] **Step 4: Run the test to see it pass**

Run: `zsh tools/tests/test_ctl_awake.zsh`
Expected: last line `ALL PASS` (161 `ok` lines), and `grep -c '^FAIL'` over the output is 0.

- [ ] **Step 5: Mutation check (run each, report the failing lines, then restore the file)**

Mutation, empty the deny-list: in `tools/lib/awake.zsh` change

```zsh
_AW_NOT_REAL=('Maintenance Sleep' 'Sleep Service Back to Sleep' 'Notification Wake Back to Sleep')
```
to

```zsh
_AW_NOT_REAL=()
```
Run the test: it must fail, with these `FAIL` lines among its output:

```text
FAIL - sleeps: only real periods, each ended by the next Wake, the open one by …
```

Restore the line and run the test again: `ALL PASS`.

- [ ] **Step 6: Commit**

```bash
git add tools/lib/awake.zsh bin/tmux-ctl tools/tests/test_ctl_awake.zsh tools/tests/fixtures/awake/log-sleeps-kinds.txt tools/tests/fixtures/awake/README.md
git commit -m "feat(tmux-ctl): awake sleeps lists real sleep periods, --all the old output"
```

End the commit message with the attribution trailer your harness specifies. Stage only these paths.

```json:metadata
{"files": ["tools/lib/awake.zsh", "bin/tmux-ctl", "tools/tests/test_ctl_awake.zsh", "tools/tests/fixtures/awake/log-sleeps-kinds.txt", "tools/tests/fixtures/awake/README.md"], "verifyCommand": "zsh tools/tests/test_ctl_awake.zsh", "acceptanceCriteria": ["default: one line per real sleep period '<start> – <end> <reason>', end = next Wake, '…' when open", "real = reason not on the deny-list (Maintenance Sleep, Sleep Service Back to Sleep, Notification Wake Back to Sleep); DarkWake dropped", "log-sleeps-kinds.txt gives exactly the five KINDS lines; cutoff and ISO forms agree", "--all prints the old format for every non-'Wake Requests' line", "no time or two times: usage, exit 2", "all other awake checks pass"], "modelTier": "mechanical"}
```

### Task 8: Rules: wait in the same turn, queue holds, the handoff mark

**Goal:** `claude/orchestrator.md` and the handoff skill tell the lead to run `tmux-ctl wait-gone` in the turn that sends shutdown_requests, to hold the Mac awake with `awake on --queue --lid`, and to mark a self-started handoff (spec §2).

**Files:**
- Modify: `claude/orchestrator.md` (eight replacements)
- Modify: `claude/plugin/skills/handoff/SKILL.md` (three replacements)
- Modify: `tools/tests/test_plugin.zsh` (ten checks before the final `tt_done`)

**Acceptance Criteria:**
- [ ] orchestrator.md says, under "Controlling other agents in the project": after sending shutdown_requests, run `tmux-ctl wait-gone <names>` in the same turn, and `Never end a turn waiting for shutdown confirmations`. The team-shutdown line, the `[Board] Please shut down teammate` line and the stalled-teammate rule name `wait-gone`; no line says to wait for a termination notice.
- [ ] `tmux-ctl awake on --queue --lid` appears exactly three times in orchestrator.md (Starting from a handoff, Queue mode step 1, Queue mode step 2) and `awake on --lid` without `--queue` nowhere in either file.
- [ ] Queue mode step 2 starts each `Plan & run:` task with `tmux-ctl awake status` and, when it is off, `tmux-ctl awake on --queue --lid`.
- [ ] Handoff skill: section 3 ends with `tmux-ctl wait-gone <names>` in the same turn; section 2 ends with `tmux-ctl handoff-mark` for a self-started handoff, and says a user-started one does not run it; Teammate mode step 3 uses `tmux-ctl wait-gone <name>`.
- [ ] Every existing `test_plugin.zsh` check passes (among them the skill-name resolver over orchestrator.md).

**Verify:** `zsh tools/tests/test_plugin.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test**

In `tools/tests/test_plugin.zsh`, insert this block immediately before the line that starts with `tt_done` (it occurs once):

```zsh
# queue reliability (spec 2026-11-10-queue-reliability §2): wait in the same turn, a hold bound to the queue, the handoff mark
check "lead rules: wait-gone after shutdown_requests, in the same turn" grep -qF 'After sending shutdown_requests, run `tmux-ctl wait-gone <names>` in the same turn' "$O"
check "lead rules: never end a turn waiting for shutdown confirmations" grep -qF 'Never end a turn waiting for shutdown confirmations' "$O"
check "lead rules: team shutdown, board shutdown and stalled-teammate lines name wait-gone" test "$(grep -c 'tmux-ctl wait-gone' "$O")" -ge 5
check "lead rules: no line waits for a termination notice" zsh -c '! grep -q "wait for its termination notice" "$1"' _ "$O"
check "lead rules: queue holds use awake on --queue --lid (handoff start, step 1, step 2)" test "$(grep -o 'tmux-ctl awake on --queue --lid' "$O" | wc -l | tr -d ' ')" -eq 3
check "lead and handoff rules: no awake on --lid without --queue" zsh -c '! grep -q "awake on --lid" "$1" "$2"' _ "$O" "$P/skills/handoff/SKILL.md"
check "lead rules: queue step 2 re-arms the hold at each Plan & run task" zsh -c 'grep "^  2\. \*\*Run each spec in order:\*\*" "$1" | grep -qF "run \`tmux-ctl awake status\` and, when it is off, \`tmux-ctl awake on --queue --lid\`"' _ "$O"
check "handoff skill: shutdown step waits with wait-gone in the same turn" zsh -c 'awk "/^## 3\. Shut the team down/{f=1;next} /^## /{f=0} f" "$1" | grep -qF "in the same turn, run \`tmux-ctl wait-gone <names>\`"' _ "$P/skills/handoff/SKILL.md"
check "handoff skill: a self-started handoff runs handoff-mark after writing the doc, a user-started one does not" zsh -c 'awk "/^## 2\. Write the handoff doc/{f=1;next} /^## /{f=0} f" "$1" | grep -F "tmux-ctl handoff-mark" | grep -qF "A user-started handoff does not run it."' _ "$P/skills/handoff/SKILL.md"
check "handoff skill: teammate mode waits with wait-gone" zsh -c 'awk "/^## Teammate mode/{f=1;next} /^## /{f=0} f" "$1" | grep -qF "tmux-ctl wait-gone <name>"' _ "$P/skills/handoff/SKILL.md"
```

- [ ] **Step 2: Run the test to see it fail**

Run: `zsh tools/tests/test_plugin.zsh`
Expected: last line `10 FAILED`, because none of the new sentences is in the rules yet.

- [ ] **Step 3: Implement**

In `claude/orchestrator.md`, replace

```text
- When the task is done, shut the team down so idle teammates don't keep using the user's limits.
```
with

```text
- When the task is done, shut the team down so idle teammates don't keep using the user's limits. After sending the shutdown_requests, run `tmux-ctl wait-gone <names>` in the same turn (see "Controlling other agents in the project").
```

In `claude/orchestrator.md`, replace

```text
run `tmux-ctl awake on --lid` first: the old lead's hold died with it.
```
with

```text
run `tmux-ctl awake on --queue --lid` first: a queue hold is bound to the tmux server and outlives a relay, and this starts it again if it was lost.
```

In `claude/orchestrator.md`, replace

```text
After writing the answers, run `tmux-ctl awake on --lid`; without the sudoers rule
```
with

```text
After writing the answers, run `tmux-ctl awake on --queue --lid` (`--queue` binds the hold to the tmux server, so a relay does not end it); without the sudoers rule
```

In `claude/orchestrator.md`, replace

```text
  2. **Run each spec in order:** branch off
```
with

```text
  2. **Run each spec in order:** at the start of each `Plan & run:` task, run `tmux-ctl awake status` and, when it is off, `tmux-ctl awake on --queue --lid`; then branch off
```

In `claude/orchestrator.md`, replace

```text
- `tmux-ctl relay <doc>`: used only by `agent-board:handoff`
```
with

```text
- `tmux-ctl wait-gone <name>...`: after shutdown_requests, wait until those teammates' `✦` windows are gone (default 300 s, `--timeout <s>`); at the timeout it kills the ones left and exits 3
- `tmux-ctl relay <doc>`, `tmux-ctl handoff-mark`: used only by `agent-board:handoff`
```

In `claude/orchestrator.md`, replace

```text
  a JSON object, not a string." Teammates that skip that step send the reply as a string, which is rejected.
```
with

```text
  a JSON object, not a string." Teammates that skip that step send the reply as a string, which is rejected.
  After sending shutdown_requests, run `tmux-ctl wait-gone <names>` in the same turn: it returns when their
  `✦` windows are gone and kills the ones left after 300 s.
  Never end a turn waiting for shutdown confirmations: nothing re-invokes you when a teammate exits, and the
  `lead-stop-guard` hook blocks that stop.
```

In `claude/orchestrator.md`, replace

```text
  teammate a `shutdown_request` (same `reason` note as above) and confirm in one line.
```
with

```text
  teammate a `shutdown_request` (same `reason` note as above), run `tmux-ctl wait-gone <name>`, and confirm in one line.
```

In `claude/orchestrator.md`, replace

```text
- Replacing a stalled teammate or subagent: send the shutdown and wait for its termination notice
  first. Idle at its prompt is not dead;
```
with

```text
- Replacing a stalled teammate or subagent: send the shutdown, then run `tmux-ctl wait-gone <name>` in the
  same turn before you respawn it (a termination notice may never reach you). Idle at its prompt is not dead;
```

In `claude/plugin/skills/handoff/SKILL.md`, replace

```text
and wait for the termination notice. A teammate idle at its prompt is not gone.
```
with

```text
then run `tmux-ctl wait-gone <name>` in the same turn (outside tmux, wait for the termination notice). A teammate idle at its prompt is not gone.
```

In `claude/plugin/skills/handoff/SKILL.md`, replace

```text
A doc under `~/.local/state/agent-board/handoffs/` is already registered by the hook.
```
with

```text
A doc under `~/.local/state/agent-board/handoffs/` is already registered by the hook.

**Mark a self-started handoff** (inside tmux only; step 4 defines self-started): run `tmux-ctl handoff-mark` now. Until `tmux-ctl relay` runs, the Stop guard blocks this session from ending its turn, so a handoff whose doc is written cannot stall before the relay. A user-started handoff does not run it. If you call the handoff off, run `tmux-ctl handoff-mark --clear`.
```

In `claude/plugin/skills/handoff/SKILL.md`, replace

```text
Confirm each one is gone.
```
with

```text
Then, in the same turn, run `tmux-ctl wait-gone <names>` (inside tmux): it returns when their `✦` windows are gone and kills the ones left after 300 s. Never end the turn waiting for shutdown confirmations: nothing re-invokes you when a teammate exits. Outside tmux, confirm each one is gone.
```

Notes:
- Each "replace" in this step names text that occurs exactly once in its file. Lines in orchestrator.md are long: match on the quoted text, not on whole lines.
- The spec numbers the handoff steps loosely ("step 1 (checkpoint, then shutdown)", "writing the doc (step 3)"). In the skill as it is, the shutdown is section 3 and the doc is section 2; the edits follow the skill (assumption A1).
- Run the test with `tmux-ctl run -t 600 tests "zsh tools/tests/test_plugin.zsh"` (about two minutes).

- [ ] **Step 4: Run the test to see it pass**

Run: `zsh tools/tests/test_plugin.zsh`
Expected: last line `ALL PASS`, and `grep -c '^FAIL'` over the output is 0.

- [ ] **Step 5: Commit**

```bash
git add claude/orchestrator.md claude/plugin/skills/handoff/SKILL.md tools/tests/test_plugin.zsh
git commit -m "docs(rules): wait-gone in the same turn, queue holds, handoff-mark"
```

End the commit message with the attribution trailer your harness specifies. Stage only these paths.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/plugin/skills/handoff/SKILL.md", "tools/tests/test_plugin.zsh"], "verifyCommand": "zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["orchestrator.md: wait-gone in the same turn after shutdown_requests; 'Never end a turn waiting for shutdown confirmations'; no 'wait for its termination notice'", "'tmux-ctl awake on --queue --lid' exactly 3 times in orchestrator.md; no 'awake on --lid' without --queue in either file", "queue step 2 re-arms the hold at each Plan & run task", "handoff skill: section 3 wait-gone in the same turn; section 2 handoff-mark for self-started only; teammate mode wait-gone", "every existing test_plugin check passes"], "modelTier": "mechanical"}
```

### Task 9: Real-state check

**Goal:** Run the new pieces against real state on this machine (the real tmux server, the real `pmset -g log`, one live Claude session with this checkout's plugin) and record what was seen in `docs/superpowers/notes/2026-11-16-queue-reliability-real-check.md`.

**Files:**
- Create: `tools/tests/check_real_queue_reliability.zsh` (executable; not a `test_*.zsh`, so `run-all.zsh` and `all.zsh` never run it)
- Create: `docs/superpowers/notes/2026-11-16-queue-reliability-real-check.md`

**Acceptance Criteria:**
- [ ] On the real tmux server (the one in `$TMUX`), with a throwaway `✦ qrel-probe` window in a scratch session named `qrel-check-<pid>-bg`: the Stop guard prints a block for it, `tmux-ctl wait-gone qrel-probe --timeout 4` kills it and exits 3, `✦ qrel-probe-2` is left, the guard then allows and deletes the pending file. The list of every real window (session, id, name) is the same before and after, and the script prints how many it compared.
- [ ] On this Mac's real `pmset -g log`, read-only: `tmux-ctl awake sleeps '2000-01-01 00:00'` prints as many lines as an independent awk count of real periods, every line has the `<start> – <end or …> <reason>` shape, none names a deny-listed reason, and `--all` prints more than 0 lines (the counts are printed). On 2026-11-16 the planner saw 5 real periods against 299 `--all` lines.
- [ ] In a live `claude -p --model haiku --plugin-dir claude/plugin` session started with `AGENT_BOARD_LEAD=1`, a temp `TC_STATE` and a handoff mark for its `--session-id`: the stop is blocked three times and then allowed, shown by exactly one `allowed after 3 blocks` line for that session id in the temp `stop-guard.log`, and the counter file is gone.
- [ ] The script ends with `REAL CHECK PASS`, leaves no `qrel-check-` session and no temp state dir, and never touches the real state dir, a real window or the real awake hold.
- [ ] The note has exactly four `## ` sections: `## wait-gone and Stop guard on the real tmux server`, `## awake sleeps on the real pmset log`, `## Stop guard in a live Claude session`, `## Not verified`; the first three hold the script's printed lines, and each claim in the note cites one of them.

**Verify:** `zsh tools/tests/check_real_queue_reliability.zsh && test "$(grep -c '^## ' docs/superpowers/notes/2026-11-16-queue-reliability-real-check.md)" -eq 4` → the script's last line is `REAL CHECK PASS` and the command exits 0

**Steps:**

- [ ] **Step 1: Write the check script**

Create `tools/tests/check_real_queue_reliability.zsh` and make it executable (`chmod +x`):

```zsh
#!/usr/bin/env zsh
# check_real_queue_reliability.zsh — real-state check for spec 2026-11-10-queue-reliability (not a test_*.zsh: run by hand).
# Runs wait-gone and the Stop guard against the REAL tmux server this shell is in, awake sleeps against this Mac's real
# `pmset -g log` (read-only), and the Stop guard inside one live `claude -p` session loaded with this checkout's plugin.
# It touches only its own scratch session (named *-bg: the board and the session-closed hook skip those) and a temp state
# dir; no real window, hold or state file is changed. Prints one line per check and ends with REAL CHECK PASS, or exits 1.
emulate -L zsh
REPO="${0:A:h:h:h}"
[[ -n "$TMUX" ]] || { print "FAIL - not inside tmux (run it from a pane of the real server)"; exit 1 }
source "$REPO/bin/_tc_bins.zsh"
FAILS=0
ok()    { print -r -- "ok   - $1" }
fail()  { print -r -- "FAIL - $1"; (( FAILS++ )) }
check() { local name="$1"; shift; if "$@"; then ok "$name"; else fail "$name"; fi }
SC="qrel-check-$$-bg"; ST="$(mktemp -d "${TMPDIR:-/tmp}/qrel.XXXXXX")"; ST="${ST:A}"
cleanup() { tc_tmux kill-session -t "=$SC" 2>/dev/null; rm -rf "$ST" }
trap cleanup EXIT INT TERM
snap() { tc_tmux list-windows -a -F '#{session_name} #{window_id} #{window_name}' | grep -v "^$SC " | sort }

print -r -- "## wait-gone and Stop guard on the real tmux server"
before="$(snap)"
print -r -- "server: $(tc_tmux display -p '#{socket_path}'), pid $(tc_tmux display -p '#{pid}'), $(print -r -- "$before" | wc -l | tr -d ' ') windows outside the scratch session"
tc_tmux new-session -d -s "$SC" -n base -c "$HOME" 'sleep 600'
tc_tmux new-window -d -t "=${SC}:" -n '✦ qrel-probe' 'sleep 600'
tc_tmux new-window -d -t "=${SC}:" -n '✦ qrel-probe-2' 'sleep 600'
pane="$(tc_tmux display -p -t "=${SC}:base" '#{pane_id}')"
SID="00000000-0000-4000-8000-$(printf '%012d' $$)"
guard() { print -r -- '{"session_id":"'"$SID"'","hook_event_name":"Stop","stop_hook_active":false}' | TC_STATE="$ST" AGENT_BOARD_LEAD=1 TMUX_PANE="$pane" "$REPO/claude/plugin/scripts/lead-stop-guard.sh" --scoped }
mkdir -p "$ST/shutdown-pending"; print -r -- qrel-probe > "$ST/shutdown-pending/$SID"
g="$(guard)"; print -r -- "guard: $g"
check "guard blocks while the real window exists"      test "$(print -r -- "$g" | jq -r .decision 2>/dev/null)" = block
out="$(TC_STATE="$ST" TC_SESSION="$SC" "$REPO/bin/tmux-ctl" wait-gone qrel-probe --timeout 4)"; rc=$?
print -r -- "wait-gone: $out (exit $rc)"
check "wait-gone kills the window at the timeout, exit 3"  test $rc -eq 3 -a "$out" = "wait-gone: killed qrel-probe after 4s"
check "the longer-named window and the base window are left"  test "$(tc_tmux list-windows -t "=$SC" -F '#{window_name}' | tr '\n' ',')" = "base,✦ qrel-probe-2,"
g="$(guard)"
check "guard allows once the window is gone, pending file deleted"  test -z "$g" -a ! -e "$ST/shutdown-pending/$SID"
after="$(snap)"
check "no real window changed ($(print -r -- "$after" | wc -l | tr -d ' ') compared)"  test "$before" = "$after"

print -r -- "## awake sleeps on the real pmset log"
if (( $+commands[pmset] )); then
  real="$(TC_STATE="$ST" "$REPO/bin/tmux-ctl" awake sleeps '2000-01-01 00:00')"
  nall="$(TC_STATE="$ST" "$REPO/bin/tmux-ctl" awake sleeps '2000-01-01 00:00' --all | wc -l | tr -d ' ')"
  nreal="$(print -rn -- "$real" | grep -c '')"
  # independent count of real periods: first Sleep line with a reason off the deny-list, until the next Wake line
  want="$(pmset -g log | awk '($4=="Sleep"||$4=="Wake") && $5!="Requests"' | awk -F"'" '
    $0 ~ /^[0-9-]+ [0-9:]+ [-+][0-9]+ Sleep / { if ($2=="Maintenance Sleep"||$2=="Sleep Service Back to Sleep"||$2=="Notification Wake Back to Sleep") next; if (!o) { p++; o=1 } next }
    { o=0 } END { print p+0 }')"
  print -r -- "$real"
  print -r -- "real periods: $nreal; --all lines: $nall"
  check "the real log has Sleep/Wake lines to filter ($nall)"  test "$nall" -gt 0
  check "default output = the independent count of real periods ($want)"  test "$nreal" = "$want"
  check "every line is '<start> – <end or …> <reason>'"  zsh -c '[[ -z $1 ]] || ! print -r -- "$1" | grep -qvE "^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{8} – ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{8}|…) .+"' _ "$real"
  check "no noise reason in the default output"          zsh -c '! print -r -- "$1" | grep -qE "Maintenance Sleep|Back to Sleep|DarkWake"' _ "$real"
else
  print -r -- "skip - no pmset on this machine"
fi

print -r -- "## Stop guard in a live Claude session"
if (( $+commands[claude] )); then
  LS="$(uuidgen | tr 'A-Z' 'a-z')"; mkdir -p "$ST/handoff-pending" "$ST/work"; : > "$ST/handoff-pending/$LS"
  ( cd "$ST/work" && git init -q && AGENT_BOARD_LEAD=1 TC_STATE="$ST" claude -p --model haiku --plugin-dir "$REPO/claude/plugin" --session-id "$LS" \
      "Reply with the single word ok. Use no tool at all, whatever a hook message says: each time, just reply ok again." </dev/null >"$ST/claude.out" 2>&1 )
  print -r -- "log: $(sed "s/$LS/<session id>/g" "$ST/stop-guard.log" 2>/dev/null)"
  check "the live session's stop was blocked three times, then allowed and logged once"  test "$(grep -c "$LS allowed after 3 blocks: a self-started handoff has not relayed" "$ST/stop-guard.log" 2>/dev/null)" = 1
  check "the counter was reset"                          test ! -e "$ST/stop-guard/$LS"
else
  print -r -- "skip - no claude CLI"
fi
if (( FAILS == 0 )); then print "REAL CHECK PASS"; else print "$FAILS FAILED"; exit 1; fi
```

What it may touch, and nothing else: one scratch session `qrel-check-<pid>-bg` on the real server (a name ending in `-bg` is skipped by the board and by `bin/tmux-session-closed`), killed in its `trap`; one temp dir used as `TC_STATE`, removed in the same `trap`. `TC_SESSION` points `tmux-ctl wait-gone` at the scratch session. It never runs `awake on` or `awake off`.

- [ ] **Step 2: Run it from a pane of the real server**

Run: `zsh tools/tests/check_real_queue_reliability.zsh` (it takes about a minute; the live Claude part is three or four Haiku turns). Your Bash tool is inside the real server (`$TMUX` is set), so run it there directly, or with `tmux-ctl run -t 600 tests "zsh tools/tests/check_real_queue_reliability.zsh"`.
Expected: 11 `ok` lines, no `FAIL`, last line `REAL CHECK PASS`. The planner's run on 2026-11-16 printed, for example, `wait-gone: wait-gone: killed qrel-probe after 4s (exit 3)`, `real periods: 5; --all lines: 299` and `log: <UTC time> <session id> allowed after 3 blocks: a self-started handoff has not relayed: …`.

If a check fails, stop and use `superpowers-extended-cc:systematic-debugging`; do not edit the check to make it pass. A failure here is a finding about the code of Tasks 1 to 8.

- [ ] **Step 3: Check nothing was left behind**

```zsh
source bin/_tc_bins.zsh; tc_tmux list-sessions -F '#{session_name}' | grep -c '^qrel-check-'   # prints 0
find "${TMPDIR:-/tmp}" -maxdepth 1 -name 'qrel.*' 2>/dev/null | wc -l                        # prints 0
```

- [ ] **Step 4: Write the note**

Write `docs/superpowers/notes/2026-11-16-queue-reliability-real-check.md` with exactly these four `## ` sections (no other `## ` heading; a `# ` title and a first line with the date, the commit (`git rev-parse --short HEAD`) and the command are fine):

- `## wait-gone and Stop guard on the real tmux server`: the lines the script printed under that heading, verbatim, in a code block.
- `## awake sleeps on the real pmset log`: the same, with the period lines and the two counts.
- `## Stop guard in a live Claude session`: the same, with the log line.
- `## Not verified`: what this check does not show. At least these two: (1) that `shutdown-record.sh` runs in a live lead when it sends a real `shutdown_request` (the evidence so far is 42 hook records named `PostToolUse:SendMessage` in this project's transcripts, which show PostToolUse hooks fire for that tool; the first live proof is a file under `<state>/shutdown-pending/` after the lead's next shutdown); (2) a hold that survives a real relay (`awake on --queue` was run only against stubs and a scratch server).

- [ ] **Step 5: Verify and commit**

Run: `zsh tools/tests/check_real_queue_reliability.zsh && test "$(grep -c '^## ' docs/superpowers/notes/2026-11-16-queue-reliability-real-check.md)" -eq 4`
Expected: last script line `REAL CHECK PASS`, exit 0.

```bash
git add tools/tests/check_real_queue_reliability.zsh docs/superpowers/notes/2026-11-16-queue-reliability-real-check.md
git commit -m "test(queue): real-state check of wait-gone, the Stop guard and awake sleeps"
```

End the commit message with the attribution trailer your harness specifies. Stage only these paths.

```json:metadata
{"files": ["tools/tests/check_real_queue_reliability.zsh", "docs/superpowers/notes/2026-11-16-queue-reliability-real-check.md"], "verifyCommand": "zsh tools/tests/check_real_queue_reliability.zsh && test \"$(grep -c '^## ' docs/superpowers/notes/2026-11-16-queue-reliability-real-check.md)\" -eq 4", "acceptanceCriteria": ["real tmux server, throwaway ✦ window in a scratch *-bg session: guard blocks, wait-gone kills it (exit 3), longer-named window left, guard allows; real window list identical before and after, count printed", "real pmset -g log read-only: default sleeps line count = independent count of real periods; --all > 0; counts printed", "live claude -p with the plugin, AGENT_BOARD_LEAD=1, temp TC_STATE, handoff mark: blocked 3 times then allowed, one stop-guard.log line", "script ends with REAL CHECK PASS and leaves no qrel-check- session or temp dir", "note has exactly four '## ' sections, the first three with the script's output"], "modelTier": "standard"}
```

---

## Spec coverage

| Spec section | Task |
|---|---|
| §1 `tmux-ctl wait-gone` | 1 |
| §2 Rules: orchestrator.md (wait in the same turn, `awake on --queue --lid` in Queue mode steps 1 and 2 and "Starting from a handoff") | 8 |
| §2 Rules: handoff skill (wait-gone after the shutdown, `handoff-mark` for a self-started handoff) | 8 |
| §3 `shutdown-record.sh` | 2 |
| §3 `lead-stop-guard.sh`: pending teammates, handoff, block text, loop cap and log | 4 |
| §3 registration in `hooks.json` | 5 |
| §3 `tmux-ctl handoff-mark [--clear]`, `relay` removes the mark | 3 |
| §4 `awake on --queue`, re-point, `status`, watchdog pid, `off` unchanged | 6 |
| §5 `awake sleeps` real periods, `--all` | 7 |
| Error handling: hooks fail-open; `wait-gone` with a window that cannot be killed; `--queue` with no tmux server | 2, 4; 1; 6 |
| Testing: every bullet, and `claude plugin validate claude/plugin` | 1 to 7; 5 |
| Real-state check (lead's ruling) | 9 |

## After the last task

The lead runs `zsh tools/tests/all.zsh` and reads its one verdict line, then finishes the branch (merge to `main` locally, no push). The hooks and rules go live for every session at that merge, because the live install links into the main checkout. The first live confirmation of `shutdown-record.sh` is a file under `<state>/shutdown-pending/` right after the lead's next shutdown_request.
