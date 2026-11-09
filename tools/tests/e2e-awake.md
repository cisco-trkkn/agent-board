# e2e: tmux-ctl awake on the real Mac (no stubs)

Run 2026-11-09 on this Mac (Darwin 25.6.0, on battery, Jamf Privilege Manager), by `awake9`, from the `feat/queue-keep-awake` worktree.
Scratch state: `TC_STATE=<scratchpad>/e2estate.*` so the real `awake.json` was never touched. The watched pid was a throwaway `sleep 900` (pid 47148), killed at the end.
Never run: `sudo pmset -a …`, `lid-setup` installs nothing, nothing was installed.

Pre-existing caffeinates, not mine and not touched: 2241 (the lead's hold), 15820, 39306, 46730, 46732.

## 1. Plain hold: on, assertions, off

Before (`pgrep -fl caffeinate`, 5 lines):

    15820 caffeinate -s -i -t 43200
    2241 caffeinate -i -s -w 1554
    39306 caffeinate -i -t 300
    46730 caffeinate -i -t 300
    46732 caffeinate -i -t 300

Tool call 1: `tmux-ctl awake on --pid 47148`

    awake: on battery: idle sleep is held, but a closed lid still sleeps; plug in for the night
    awake: on (pid 47176, watching 47148)
    rc=0
    {"pid": 47148, "caffeinatePid": 47176, "since": "2026-11-09T19:44:00Z"}      # awake.json

Tool call 2 (a separate, later Bash-tool call: the hold survived the call that started it): `tmux-ctl awake status`

    on (pid 47176, watching 47148, since 2026-11-09T19:44:00Z)
    lid: off
    Now drawing from 'Battery Power'
     -InternalBattery-0 (id=36634723)	76%; discharging; 7:37 remaining present: true

`pgrep -fl caffeinate` (6 lines, only 47176 is new): `47176 caffeinate -i -s -w 47148`.
`pmset -g assertions | grep 47176`: the pid in `awake.json` holds both assertions:

    pid 47176(caffeinate): [0x00002a5600019670] 00:00:04 PreventUserIdleSystemSleep named: "caffeinate command-line tool"
        Details: caffeinate asserting on behalf of Process ID 47148
    pid 47176(caffeinate): [0x00002a5600079671] 00:00:04 PreventSystemSleep named: "caffeinate command-line tool"

`tmux-ctl awake off`: `awake: off`, rc=0, `awake.json` gone.

## 2. Lid mode on a Privilege Manager Mac

`tmux-ctl awake on --lid --pid 47148` (new caffeinate 47538), rc=0:

    awake: on battery: idle sleep is held, but a closed lid still sleeps; plug in for the night
    awake: on (pid 47538, watching 47148)
    awake: lid hold unavailable (run tmux-ctl awake lid-setup)

`awake.json` has only `pid`, `caffeinatePid`, `since` (no `lid`, no `watchdogPid`). `tmux-ctl awake status` after the fallback prints the line `lid: off` after `on (pid 47538, …)`.
The rule check run for real (read-only), exit 0 with no command listed:

    $ sudo -n -l /usr/bin/pmset -a disablesleep 1
    The commands available to user francisco.ruiz are defined by Privilege Manager policies
    rc=0

`tmux-ctl awake off`: `awake: off`, rc=0.

## 3. Real `awake sleeps`

`tmux-ctl awake sleeps 2026-11-07T00:00:00Z` over this Mac's `pmset -g log`: rc=0, **181 lines**. First lines and the last six:

    2026-11-06 19:13:36 DarkWake Deep Idle
    2026-11-06 19:13:38 Sleep Sleep Service Back to Sleep
    2026-11-06 19:19:02 DarkWake Deep Idle
    2026-11-06 19:19:40 Sleep Maintenance Sleep
    2026-11-06 19:23:06 DarkWake Deep Idle
    ...
    2026-11-07 11:30:18 Sleep Maintenance Sleep
    2026-11-07 11:39:08 DarkWake Deep Idle
    2026-11-07 11:39:53 Sleep Maintenance Sleep
    2026-11-07 11:51:12 Wake Deep Idle
    2026-11-07 11:52:58 Sleep Low Power Sleep
    2026-11-09 10:30:32 Wake Hibernate

The 2026-11-07 `Sleep Low Power Sleep` line is line 180.

## 4. Nothing left behind

After `off`: `pgrep -fl caffeinate` = the same 5 pre-existing lines (5 before, 5 after; 47176 and 47538 gone); `pgrep -fl _watchdog | wc -l` = 0; `pmset -g assertions | grep -c 47176` = 0; scratch state dir holds no `awake.json`; the throwaway `sleep 900` was killed.

## Not verified here

This Mac has no admin rights, so the rule was never installed: the real output of `sudo -n -l /usr/bin/pmset -a disablesleep 1` **with** a sudoers rule installed is unverified. The code expects the exact stdout line `/usr/bin/pmset -a disablesleep 1`; `tools/tests/fixtures/awake/sudo-l-allowed.txt` is derived, not captured. Item 1 of the gate below also settles that.

## Lid user gate (the user runs it; agents never do)

- [ ] Install the rule: `tmux-ctl awake lid-setup`, then `sudo visudo -f /etc/sudoers.d/agent-board-awake` with the printed line.
- [ ] Check the rule is seen: `sudo -n -l /usr/bin/pmset -a disablesleep 1` prints a line `/usr/bin/pmset -a disablesleep 1` (the one unverified output shape).
- [ ] On AC, run `tmux-ctl awake on --lid`: it prints `awake: lid hold on: …`, `tmux-ctl awake status` says `lid: on`.
- [ ] Note the time, close the lid for 2 minutes, open it.
- [ ] `tmux-ctl awake sleeps <time before closing>`: expected no `Sleep` line.
- [ ] `tmux-ctl awake off`: prints `awake: off`.
- [ ] `pmset -g | grep SleepDisabled`: expected no output (the line only exists while it is 1), i.e. `SleepDisabled` 0.
- [ ] `pgrep -fl 'caffeinate|_watchdog'` lists none that `awake` started.
