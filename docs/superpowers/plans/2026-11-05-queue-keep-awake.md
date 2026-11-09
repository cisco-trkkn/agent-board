# Queue keep-awake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tmux-ctl awake` holds the Mac awake while a queue runs (plain `caffeinate` hold, opt-in lid hold with a watchdog), lists the sleeps that happened, and the lead rules use it at queue start, handoff and the morning report.

**Architecture:** a new `awake` subcommand in `bin/tmux-ctl` (zsh) with state in `$TC_STATE_DIR/awake.json`; `pmset`/`caffeinate`/`sudo` are the only external commands, stubbed by PATH scripts in tests that serve captured fixture output; rule text in `claude/orchestrator.md` and the handoff skill.

**Tech Stack:** zsh, macOS `caffeinate`/`pmset`/`sudo`, the scratch tmux test harness (`tools/tests/lib.zsh`).

**Spec:** `docs/superpowers/specs/2026-11-05-queue-keep-awake-design.md`

## Global Constraints

- Command surface, messages and file fields exactly as the spec's tables (§1, §1b): `awake on [--pid N] [--lid]`, `off`, `status`, `sleeps <since>`, `lid-setup`, `_watchdog <pid>`; `awake.json` = `{"pid", "caffeinatePid", "since"}` plus `"lid": true, "watchdogPid"` in lid mode; every quoted message verbatim.
- `caffeinate -i -s -w <pid>`; default `<pid>` = nearest ancestor of the calling shell whose command name contains `claude`.
- Unsupported (no `caffeinate` or no `pmset` on PATH): every subcommand prints `awake: unsupported here`, exit 0.
- Battery thresholds: no lid hold below 30%; the watchdog releases below 15%; watchdog tick 60 s, `TC_AWAKE_TICK` overrides it (tests).
- Kill only a pid that is still the process it should be (`caffeinate`, or the watchdog's `tmux-ctl awake _watchdog`); never a reused pid.
- Probed on this Mac, 2026-11-09 (real output; fixtures must be captured the same way):
  - `pmset -g batt` on battery: `Now drawing from 'Battery Power'` then ` -InternalBattery-0 (id=…)\t81%; discharging; …`. On AC the first line says `'AC Power'` (capture it on AC for the AC fixture).
  - `pmset -g log` lines: `YYYY-MM-DD HH:MM:SS ±ZZZZ <Type padded>\t<message>`. The type is field 4 (`awk '$4=="Sleep"'`); a `Wake Requests` line also has `$4=="Wake"` and must be excluded (`$5!="Requests"`). Sleep reason = the first single-quoted string (`Entering Sleep state due to 'Low Power Sleep':…` → `Low Power Sleep`). Wake/DarkWake reason = the text after `Wake from ` / `DarkWake from ` up to ` [` (`Wake from Deep Idle [CDNVA] …` → `Deep Idle`).
  - `pmset -g` has NO `SleepDisabled` line when it is 0; it appears only when set. Absent = 0.
  - `sudo -n -l /usr/bin/pmset -a disablesleep 1` on this Jamf Privilege Manager Mac exits **0** while printing `The commands available to user … are defined by Privilege Manager policies` — the rule is present only when stdout contains the line `/usr/bin/pmset -a disablesleep 1`. Never trust the exit code alone.
- User rule: never run the full suites; run only `zsh tools/tests/test_ctl_awake.zsh` (plus `zsh tools/tests/test_plugin.zsh` if the handoff skill's tests live there).
- Commits: conventional with scope (`feat(tmux-ctl): …`, `docs(rules): …`); end with the attribution trailer your harness specifies.

**User decisions (already made):** the spec's design, approved 2026-11-05 (lid mode is the user's opt-in by installing the sudoers rule; agents never install it).

**Plan rulings (lead, queue mode):**
- Ruling: the sudoers-rule check reads stdout for the exact command line (probe above), not the exit code — costs a missed lid hold if a future sudo prints the rule differently.
- Ruling: `sleeps` excludes `Wake Requests` lines and parses reasons per the probe — costs a missing or odd reason text if pmset's wording differs on another macOS version.

---

### Task 1: `tmux-ctl awake` plain hold, status and sleeps

**Goal:** `awake on [--pid N]`, `off`, `status`, `sleeps <since>` and the unsupported path, per spec §1, with tests on stubs serving captured fixtures.

**Files:**
- Modify: `bin/tmux-ctl` (new `awake)` case; helpers in the same file or a sourced `tools/lib/awake.zsh` if the case grows past ~80 lines)
- Create: `tools/tests/test_ctl_awake.zsh`, `tools/tests/fixtures/awake/` (`batt-ac.txt`, `batt-battery.txt`, `log-sleeps.txt`, `README.md` with the capture commands)

**Acceptance Criteria:**
- [ ] `on` twice → one caffeinate, second prints `awake: already on (pid <p>, since <s>)`.
- [ ] `on` with a dead recorded pid starts a new one and rewrites `awake.json`.
- [ ] `off` kills only a pid still named `caffeinate` (a reused pid is left alone), removes the file, prints `awake: off`; with no file prints `awake: off`, exit 0.
- [ ] `status` prints `on (pid …, watching …, since …)` or `off` plus the power-source line; cleans a stale file.
- [ ] battery warning on the battery fixture, not on the AC one.
- [ ] `sleeps <since>` filters by time (ISO UTC and local `YYYY-MM-DD HH:MM`), prints `<local time> <type> <reason>`, excludes `Wake Requests`, prints nothing when none, exit 0.
- [ ] no claude ancestor and no `--pid` → `awake: no claude ancestor; pass --pid`, non-zero exit.
- [ ] without `caffeinate` on PATH, every subcommand prints `awake: unsupported here`, exit 0.
- [ ] fixtures captured from this Mac (README lists the commands); each guard test names its mutation.

**Verify:** `zsh tools/tests/test_ctl_awake.zsh; echo rc=$?` → `rc=0` and no `FAIL` line

**Steps:**
- [ ] Capture fixtures: `pmset -g batt > batt-battery.txt` (on battery) and the AC one (`batt-ac.txt`: if the Mac is on battery at capture time, take the battery capture and change only the source line to `'AC Power'` and the state word to `charged`, saying so in the README); `pmset -g log | awk '$4=="Sleep"||$4=="Wake"||$4=="DarkWake"' | tail -40 > log-sleeps.txt` (keeps real `Wake Requests` lines for the exclusion test).
- [ ] Tests first (RED), in the style of `tools/tests/test_ctl_context.zsh` (scratch harness from `lib.zsh`, temp `TC_STATE`); stub `caffeinate` (a `sleep 600` that execs as a process named caffeinate — e.g. a copy of `/bin/sleep` named `caffeinate` in the stub dir, so `ps -o comm=` shows `caffeinate`), stub `pmset` (serves the fixture chosen by `AWAKE_FIXTURE_BATT`), all on a temp PATH dir prepended.
- [ ] Implement; RED → GREEN; kill every stub process the tests started (leak check by `pgrep -f` on the stub dir: 0).
- [ ] Commit `feat(tmux-ctl): awake holds the Mac awake and lists sleeps`.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_awake.zsh", "tools/tests/fixtures/awake/"], "verifyCommand": "zsh tools/tests/test_ctl_awake.zsh; echo rc=$?", "acceptanceCriteria": ["on twice keeps one caffeinate, prints already on", "dead recorded pid replaced", "off kills only a live caffeinate pid", "status on/off with power line; stale file cleaned", "battery warning only on battery fixture", "sleeps filters by time, excludes Wake Requests, reason parsed", "no claude ancestor fails with the message", "unsupported here exit 0 without caffeinate", "fixtures captured from this Mac"], "modelTier": "standard"}
```

---

### Task 2: lid mode and watchdog

**Goal:** `awake lid-setup`, `awake on --lid`, the `_watchdog`, and the lid parts of `off`/`status`, per spec §1b, tested with `sudo` and `pmset` stubs.

**Files:**
- Modify: `bin/tmux-ctl` (or `tools/lib/awake.zsh` from Task 1)
- Modify: `tools/tests/test_ctl_awake.zsh`, `tools/tests/fixtures/awake/` (a `sudo-l-privmgr.txt` capture of the real Privilege Manager output; a `sudo-l-allowed.txt` derived one, marked derived in the README)

**Acceptance Criteria:**
- [ ] `lid-setup` prints the sudoers line `<user> ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 0, /usr/bin/pmset -a disablesleep 1` and the `sudo visudo -f /etc/sudoers.d/agent-board-awake` command; installs nothing.
- [ ] rule absent (including the real Privilege Manager output with exit 0) → plain hold plus `awake: lid hold unavailable (run tmux-ctl awake lid-setup)`, exit 0.
- [ ] rule present → `disablesleep 1` called once; a second `on --lid` does not call it again; `awake.json` gains `lid`/`watchdogPid`; the ventilation message printed.
- [ ] battery 25% → `awake: battery 25%: no lid hold below 30%`, plain hold.
- [ ] watchdog releases (`disablesleep 0`, fields removed) within one tick after the watched pid dies, and when the battery stub drops below 15% (logs `awake: lid hold released: battery <n>%` to `awake.log`).
- [ ] `off` releases the hold and kills only the recorded watchdog; `status` prints `lid: on|off`.
- [ ] stale: `SleepDisabled 1` in the `pmset -g` stub with no `awake.json` lid record → the stale warning on `status` and `on`; `off` clears it.

**Verify:** `zsh tools/tests/test_ctl_awake.zsh; echo rc=$?` → `rc=0` and no `FAIL` line

**Steps:**
- [ ] Capture `sudo -n -l /usr/bin/pmset -a disablesleep 1 > sudo-l-privmgr.txt; echo $?` (record the exit code in the README).
- [ ] Tests first; `sudo` stub logs its argv to a file the tests read and answers `-n -l …` from the fixture chosen by an env var; `TC_AWAKE_TICK=1`.
- [ ] Implement; RED → GREEN; leak check (no stub watchdog or caffeinate left: `pgrep` count 0).
- [ ] Commit `feat(tmux-ctl): awake lid mode with a battery and lead watchdog`.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_awake.zsh", "tools/tests/fixtures/awake/"], "verifyCommand": "zsh tools/tests/test_ctl_awake.zsh; echo rc=$?", "acceptanceCriteria": ["lid-setup prints the rule and visudo command only", "rule absent incl. Privilege Manager rc 0 output -> plain hold + message", "rule present -> disablesleep 1 once, idempotent", "battery 25% -> no lid hold", "watchdog releases on lead exit and battery <15% within one tick", "off releases and kills only the recorded watchdog; status lid line", "stale SleepDisabled warning and off clears it"], "modelTier": "standard"}
```

---

### Task 3: rules use `awake`

**Goal:** Queue mode step 1 and step 5, "Starting from a handoff", and the handoff skill's State of the work call `tmux-ctl awake` as spec §2 says.

**Files:**
- Modify: `claude/orchestrator.md`, `claude/plugin/skills/handoff/SKILL.md`

**Acceptance Criteria:**
- [ ] Queue mode step 1 ends with: after writing the answers, run `tmux-ctl awake on --lid`; without the sudoers rule it falls back to the plain hold, so nothing new is asked; a battery, lid or heat warning it prints is told to the user in one line, as a notice, not a question.
- [ ] Step 5 (morning report): run `tmux-ctl awake sleeps <run start>` with the earliest `answeredAt`; add a **Sleep** section listing its lines, or `none`; then `tmux-ctl awake off`.
- [ ] "Starting from a handoff": when the doc says `Queue mode: on`, run `tmux-ctl awake on --lid` first (the old lead's hold died with it).
- [ ] Handoff SKILL.md State of the work, queue mode: add an `Awake: on since <since>` line from `tmux-ctl awake status`.
- [ ] `git diff --stat` shows only these two files.

**Verify:** `grep -c 'tmux-ctl awake' claude/orchestrator.md claude/plugin/skills/handoff/SKILL.md` → orchestrator.md ≥ 3, SKILL.md ≥ 1

**Steps:**
- [ ] Edit the four places with the text above (keep each file's sentence style; no other edits).
- [ ] Run Verify; commit `docs(rules): queue mode holds the Mac awake and reports sleeps`.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/plugin/skills/handoff/SKILL.md"], "verifyCommand": "grep -c 'tmux-ctl awake' claude/orchestrator.md claude/plugin/skills/handoff/SKILL.md", "acceptanceCriteria": ["step 1 runs awake on --lid with notice-only warnings", "step 5 Sleep section from awake sleeps, then awake off", "handoff start re-arms awake on --lid in queue mode", "handoff SKILL Awake line", "only these two files changed"], "modelTier": "mechanical"}
```

---

### Task 4: real run without stubs

**Goal:** One real `awake on --pid $$` / `pmset -g assertions` / `awake off` cycle and a real `awake sleeps` over this Mac's log, recorded; the lid user gate written out for the user.

**Files:**
- Create: `tools/tests/e2e-awake.md`

**Acceptance Criteria:**
- [ ] Real run: `tmux-ctl awake on --pid $$` → `pmset -g assertions` shows the new caffeinate's `PreventUserIdleSystemSleep` (pid matches `awake.json`); `tmux-ctl awake off` → that pid's assertion is gone and `pgrep caffeinate` no longer lists it. Output pasted.
- [ ] Real `tmux-ctl awake sleeps 2026-11-07T00:00:00Z` over this Mac's log prints the 2026-11-07 `Low Power Sleep` line (read-only real state); output pasted with its line count.
- [ ] Real `tmux-ctl awake on --lid --pid $$` on this Privilege Manager Mac prints the lid-unavailable message and keeps the plain hold; then `off`.
- [ ] The lid user gate from the spec's Testing section is written as an unchecked checklist for the user (not run by agents).
- [ ] No caffeinate or watchdog started by the run remains (`pgrep -fl caffeinate` before/after, counts stated).

**Verify:** `test -s tools/tests/e2e-awake.md && grep -c 'PreventUserIdleSystemSleep' tools/tests/e2e-awake.md` → ≥ 1

**Steps:** run each command in the Mac's own shell (no stubs, real `TC_STATE`-free default state dir is fine since `awake.json` is removed by `off`); paste raw output under each command; commit `test(tmux-ctl): awake real run`.

```json:metadata
{"files": ["tools/tests/e2e-awake.md"], "verifyCommand": "test -s tools/tests/e2e-awake.md && grep -c 'PreventUserIdleSystemSleep' tools/tests/e2e-awake.md", "acceptanceCriteria": ["real on/assertions/off cycle pasted", "real sleeps over the Mac log shows the 2026-11-07 Low Power Sleep line", "real on --lid on Privilege Manager falls back with the message", "lid user gate written as an unchecked list", "no leftover caffeinate/watchdog, counts stated"], "modelTier": "standard"}
```
