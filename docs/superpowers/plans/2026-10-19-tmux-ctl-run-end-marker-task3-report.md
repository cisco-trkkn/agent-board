# Task 3 report: stress-check of the end-marker fix under load

Branch `fix/tmux-ctl-end-marker`, fix commits 8179153 and c2ab118. Each iteration is `TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/test_bg.zsh | tail -1`, run through `tmux-ctl run -t … tests`, one result line and wall time per iteration written to a file as it went.

## Load

- Load generator: `( while :; do TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/run-all.zsh >/dev/null 2>&1; done ) &`, killed by PID afterwards (loop shell plus its current `run-all.zsh` child, checked with `ps` first). `ps -p` shows all of them gone, including the scratch tmux server and `test_teammate_window.zsh` left behind by the killed run-all.
- `uptime` before the first run: `17:50 up 13 days, 15:12, load averages: 4.40 5.17 4.54`.
- `uptime` after the rerun: `01:25 up 15 days, 22:47, load averages: 6.51 6.53 6.04`.
- Per-iteration time: one unloaded run 34s, one loaded run 39s. Iterations 1-98: 34-41s each. Rerun 99-120 (load loop running, `caffeinate -dimsu -w <chunk pid>`): 34-55s each.
- Two load loops ran, because the first was stopped when iterations 99-102 stalled: loop 1 (PID 28899) covered iterations 1-102, loop 2 (PID 42354) covered the rerun of 99-120.

## Tally

Iterations 1-98 (first run) plus the rerun of 99-120, with the load loop running throughout:

```
$ cat tally-1-98 tally-rerun-99-120 | awk '{print $2,$3}' | sort | uniq -c
 120 ALL PASS
```

Iterations 1-98: `98 ALL PASS`, 34-41s. Iterations 99-120 (rerun): `22 ALL PASS`, 34-55s, no iteration needed the 300s kill cap and no non-PASS output was saved.

Iterations 99-102 of the first run did not count. The first run printed:

```
99 1 FAILED 1485s
100 ALL PASS 83s
101 4 FAILED 2530s
102 ALL PASS 1747s
```

Those four iterations lined up with machine sleep, not a slow check. `pmset -g log` for 2026-10-22:

```
18:53:30 Sleep     Entering Sleep state due to 'Clamshell Sleep' ... Using Batt (Charge:80%)
19:16:45 DarkWake  from Deep Idle ... (then Sleep 19:17:30, DarkWake 19:17:50, Sleep 19:18:36, ...)
20:01:25 DarkWake  from Deep Idle ...
20:30:32 DarkWake  from Deep Idle ...
```

Iteration 98 ended about 18:53:10 (chunk started 18:48, iterations 91-98 sum to 296s). Iteration 99 began about 20 seconds before the clamshell sleep and ended about 19:17:55; iteration 101 ran about 19:19 to 20:01:28; iteration 102 ended about 20:30:35. Between 18:53 and 20:31 the Mac was asleep with a DarkWake of about 45s every 15 min, and the run advanced only in those windows. The load average of 22.97 seen at 20:01 coincides with the 20:01:25 DarkWake, the catch-up burst after a long sleep. The failed checks of 99 and 101 were not captured, because the first chunk kept only `tail -1`. I did not reproduce a sleep-caused failure, so which check failed and why is not shown. The rerun had no sleep event: the only wake on 2026-10-25 before the rerun is 01:03:18, and none between 01:09 and 01:25.

## Verdict

120 loaded runs with zero non-sleep failures: 98 from the first run and 22 from the rerun, all `ALL PASS`, load loop running throughout both. Iterations 99-102 of the first run (2 FAILED, 2 PASS with 83-2530s wall time) are excluded because they overlapped a clamshell sleep and wake cycle (pmset lines above) and were replaced by the rerun of 99-120. The rerun was done with sleep prevented by `caffeinate` on the chunk and no sleep occurred. The fix shows no failure in 120 loaded runs. Not shown: which checks failed in the sleep-affected iterations 99 and 101. Note for later: `caffeinate` does not stop clamshell sleep on battery, so closing the lid mid-run still sleeps the Mac.
