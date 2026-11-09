# awake fixtures

Captured on this Mac (macOS, Darwin 25.6.0) on 2026-11-09 and served by the `pmset` stub in `test_ctl_awake.zsh`.

- `batt-battery.txt`: `pmset -g batt` taken while on battery (`Battery Power`, 80%, discharging).
- `batt-ac.txt`: the same capture with only the source line changed to `'AC Power'` and the state changed to `100%; charged` (the Mac was on battery at capture time, so a real AC capture was not possible).
- `log-sleeps.txt`: `pmset -g log | awk '$4=="Sleep"||$4=="Wake"||$4=="DarkWake"' | tail -40`. It keeps the real `Wake Requests` lines, which the exclusion test needs. Timestamps are `-0500`; the tests run with `TZ=America/New_York`.
- `sudo-l-privmgr.txt`: real stdout of `sudo -n -l /usr/bin/pmset -a disablesleep 1` on this Jamf Privilege Manager Mac, captured 2026-11-09; **exit code 0** although no rule lists the command. The check must read stdout, not the exit code.
- `sudo-l-allowed.txt`: **derived, not captured**: what sudo prints when a sudoers rule allows the command (the command line itself). The `sudo` stub rewrites the trailing `1` to `0` for the `disablesleep 0` query.
- `batt-battery-25.txt`, `batt-battery-10.txt`: **derived** from `batt-battery.txt` with only the percentage changed (25%, 10%).
- `batt-ac-10.txt`: **derived** from `batt-battery-10.txt`: `AC Power`, `charging` (10% on AC must not release the lid hold).
