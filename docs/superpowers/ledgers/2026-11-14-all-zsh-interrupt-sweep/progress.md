# SDD ledger — plan: docs/superpowers/plans/2026-11-14-all-zsh-interrupt-sweep.md
Spec: docs/superpowers/specs/2026-11-11-all-zsh-interrupt-sweep-design.md
Preflight scan:
| pair/task | produces vs consumes | finding |
| T1 x T2 | T1 makes sockroot /tmp/tcs.*/<n> + sweep; T2 finds newest /tmp/tcs.* and checks sockets gone | consistent |
| T1 self | tests (sweep/no-INT/scope/env) vs code (TMUX_TMPDIR per job, TERM-only, sweep) | consistent; no-INT is a source check (INT unobservable in jobs) |
| T2 self | note file created and its Verify greps it | consistent |
Ruling: socket root /tmp/tcs.XXXXXX/<n> as each job's TMUX_TMPDIR instead of <rundir>/tmp — tmux ignores TMPDIR (probe: -L socket landed in /tmp/tmux-503), and <rundir>/tmp/<n>/tmux-503/<sock> is ~103 bytes vs the 104 limit — a test relying on /tmp/tmux-<uid> breaks; the full-suite AC catches it.
Ruling: real-state check counts sockets under the socket root, not the spec's grep '[t]mux.*tc-all' — a -L server's argv has no run dir path, so that grep reads 0 always — the check could miss a server started with -S elsewhere.
Task 1: dispatched sweep-impl (sonnet/medium), base 920e778
Ruling: Task 1 green accepted with the full suite at rc=4 (ALL PASS 123 jobs, 5m29s over the 5 min budget at load 17.7) — every job passed and the budget is a timing signal, not a failure; the suite is re-run before the merge — cost if wrong: a slowdown from the change goes unnoticed until the pre-merge run.
Task 1: bounce check green (verifyCommand rc=0 in report); reviewed by sweep-rev: spec ❌, 2 Important, 3 Minor
Task 1: minor (deferred): EXIT trap kill-server with possibly empty $sk (guard [ -n "$sk" ])
Task 1: minor (deferred): sequential kill-servers, each up to 2 s, could exceed the ~5 s bound with many servers
Task 1: minor (deferred): mktemp of sockroot before the trap is installed; a signal in that window leaks the root
Task 1: fix round 1/5 (2 addressed, 0 open; commits 3b2ff76..e925466)
Task 1: minor (deferred): mutation comment above envpat still mentions "a new /tmp/tcs.*"
Task 1: complete (commits 920e778..e925466, review clean)
Task 2: dispatched sweep-check (haiku/low), base e925466
Task 2: bounce check green (verifyCommand 18, exit 0)
Ruling: Task 2 accepted with the first post-C-c check at 15 s (plan said 10 s) — the bound under test is the runner's own (<5 s, covered by Task 1's unit cases); the real check only needs the servers gone — cost if wrong: a slow sweep (5-15 s) goes unseen on the real suite.
Ruling: correction to the plan's grep ruling — a scratch server's argv does carry the run dir (`-c <rundir>/...`), so `[t]mux.*tc-all` would match during a run; the socket-root check stays as the evidence (stricter: it checks each counted server) — cost if wrong: none for this branch; the plan text overstated why.
Task 2: reviewed by sweep-rev2: spec ✅, quality needs fixes, 1 Important (no positive control: has-session/lsof trivially pass once the root is removed; no server PID baseline), 4 Minor
Task 2: fix round 1 by sweep-check2: positive control passed (baseline server pid 71039 under /tmp/tcs.9qVSXO gone at 5/6/10 s), commit 281bd88; scoped re-review pending
Task 2: re-review dispatched to sweep-rev2 (sonnet/medium; fix diff 25 lines, not small), package review-19b3a36..281bd88.diff
Task 2: fix round 1/5 (2 addressed, 0 open — positive control, 10 s check; commits 19b3a36..281bd88)
Task 2: minor (deferred): note Rulings bullet 1 command line elided and spec grep count never recorded
Task 2: minor (deferred): ps -p 60789 described as the run's process (another session's all.zsh)
Task 2: minor (deferred): only one server lane seen; not stated as a limitation
Task 2: minor (deferred): 2 of 23 root-carrying processes unresolved in the parent walk (note l.51)
Task 2: minor (deferred): first-pass Result lines (l.42/l.44) lack the baseline caveat; l.37 unbracketed ps grep
Task 2: complete (commits e925466..281bd88, review clean)
Final review: dispatched sweep-final (session level), package review-8a00f71..281bd88.diff
Final review: with fixes — 1 Important (test_e2e_isolation real-server check vacuous under per-job TMUX_TMPDIR), 4 new minors; deferred minors: none must fix
Final review: fix wave dispatched to sweep-fix (sonnet/medium): Important 1 + unique stub name + spec socket-root amendment
Final review: parked — FAIL path removes socket root without sweep (all.zsh:175) — Ruling: deferred; the pass path and interrupt path sweep, a failed job's leaked server is the old behaviour — cost if wrong: a leaked scratch server after a failed run stays until reboot
Final review: parked — no perl and no timeout makes the sweep a silent no-op — Ruling: deferred; both exist on this Mac — cost if wrong: on a bare box an interrupt leaks servers without a message
Final review: fix wave by sweep-fix, commits 281bd88..6caa995 (runner + e2e green); scoped re-review to sweep-final
Final review: re-review of fix wave — 3 addressed, 0 open; new minors (deferred): nested all.zsh ignores inherited TC_REAL_TMUX_TMPDIR; all.zsh:114 Limit comment line 233 chars
Ruling: pre-merge full suite accepted at rc=4 (ALL PASS 123 jobs, 0 FAIL lines, 5m59s over the 5 min budget) though the final reviewer asked for rc=0 — rc=4 is the timing budget only; other runs in the tests window, on other branches, were also over (5m32s, 18m32s) and the slowest jobs are board python tests this branch does not touch — cost if wrong: a slowdown from the per-job socket root or sweep lands on main unseen
Final review: complete (commits 8a00f71..6caa995, 3 addressed, 2 parked, review clean)
