# Pre-flight rulings (lead), binding on the named tasks

Source: `preflight-scan.md` "Findings needing a ruling". Each dispatch carries the rulings for its task. Where a ruling and the plan text disagree, the ruling wins.

- **R1 (Task 9, 15):** report layout: line 1 heading, line 2 blank, line 3 `Written by the engine (<project>).`; plan l.445 "second line" reads "third line". Task 9 adds a test for the `-queue-2` name.
- **R2 (Task 11):** engine-run match compares spec ids on the part before `#` on both sides (`feed.js specName` drops `#part-N`); a test uses a `#part-2` id.
- **R3 (Task 4):** keep the park-site table as written (site recommendations over fixed defaults; `architect_park` where no architect ran). Site recommendations are constants in `policy.js` so the policy hash covers them.
- **R4 (Task 13):** the Queue-mode block says the engine path replaces step 1's seq-sdd `batch start` and step 2's up-front `batch start` and planner `metrics start` when the engine config exists; the Task 13 test pins that sentence.
- **R5 (Tasks 10, 13):** `engine start` exits 4 when an engine for the project already runs (lock held or window exists); the rule treats 0 and 4 as success and only other non-zero codes as "run the queue as before". Task 10 tests exit 4.
- **R6 (Tasks 6, 8):** the second `metrics record` for a parked-failed spec is step kind `metrics_record_parked` with no check (never parks, in the never-park list); `metrics.py` appends the second run line and report/compare use the LAST run line per (spec, batch). Task 6 tests two run lines → last wins.
- **R7 (Task 7):** lead-run specs: `startQueued` emits `lead_turn` instead of `spec_started` for runner `lead` (no `policy_version`), and `pumpAll`, `advance`, `dispatch`, `policyCheck` skip `runner='lead'`; tested by the 25 h lead-run spec (l.388).
- **R8 (Task 5):** the unknown-cost park fires only on `job_done` and `architect_decision` ends; a failed/limit/start_failed attempt with `tokens: null` sets `lower_bound: true` and does not park.
- **R9 (Task 1):** never-park split runs before the `!s.spec` skip; `commit_report` joins the never-park kinds; test a spec-less `awake_off` at intent. (Sent to impl1.)
- **R10 (Task 3):** `db.open` migration fills an open wait with NULL kind as `kind='cannot_tell'` and the default recommendation; the aged fixture carries an open wait.
- **R11 (Task 4):** `park()` builds the signal `command` from the wait's options (no hard-coded approve/deny); tested with the budget-cap park (`approve|fail`) in Task 5's test or Task 4's.
- **R12 (Tasks 7, 12):** `status --preflight` reuses the `--unfinished` predicate plus "a new enqueue row".
- **R13 (Task 12):** `--project` takes the feed key (the tmux session group, else the session name: the ideas/context key); Task 12's test uses a project whose snapshot name and feed key differ.
- **R14 (Task 6):** keep `control_share` target as a ratio of medians, and session-id attribution (departure from the spec's "window name": session ids are what usage rows carry).
- **R15 (Task 8):** `lead.js` emits `[Engine] queue finished: <report>` only for a non-empty report string, else `[Engine] queue finished: (no report)`; asserted in Task 8.
- **R16 (Task 11):** contract `tick(project, add_line, pending, state)`; the server passes `lambda text: COMMENTS.add_line(sess, text)` and `lambda: [c["text"] for c in COMMENTS.pending(sess)]`; dedupe compares flattened text.
- **R17 (Task 7):** the core skips `metrics_start` for runner `lead` (the lead runs it); a test pins it.
- **R18 (Task 8):** a held answer closes the wait: a second `signal` for a held spec exits 2 with `no open wait`; `status --waiting` lists the spec as `answer held`. Tested.
- **R19 (Task 5):** the cost-unknown park question is `cost unknown for job <id>` (spec 8b).
- **R20 (Task 14):** acceptance adds `cd engine && npm test` green (its `# pass`/`# fail` lines in the report); the Verify line and verifyCommand stay as written; the npm line is a second criterion with its own command.
- **R21 (Task 11):** the real-state check asserts the dry run changed no file (cursor file absent or mtime unchanged) and every real feed line with `src` has `kind` and `spec`; drop `lines_seen >= 0`.
- **R22 (Tasks 5, 9):** Task 5 exports one `metrics record` argv builder (used by Task 8's parked record too); Task 9 reuses the ledger commit helper from `ledger.js`/`integrate.js` rather than a copy.
- **R23:** Task 9 depends on Tasks 7 and 8 only (native task graph already says so).
- **R24 (Task 4):** the test table lists the three row-8 sites (push not permitted, merge failed, unknown integration answer) as separate cases.
