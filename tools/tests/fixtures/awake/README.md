# awake fixtures

Captured on this Mac (macOS, Darwin 25.6.0) on 2026-11-09 and served by the `pmset` stub in `test_ctl_awake.zsh`.

- `batt-battery.txt`: `pmset -g batt` taken while on battery (`Battery Power`, 80%, discharging).
- `batt-ac.txt`: the same capture with only the source line changed to `'AC Power'` and the state changed to `100%; charged` (the Mac was on battery at capture time, so a real AC capture was not possible).
- `log-sleeps.txt`: `pmset -g log | awk '$4=="Sleep"||$4=="Wake"||$4=="DarkWake"' | tail -40`. It keeps the real `Wake Requests` lines, which the exclusion test needs. Timestamps are `-0500`; the tests run with `TZ=America/New_York`.
