# Shared project context: end-to-end report

Run on 2026-10-29 from the worktree `.claude/worktrees/shared-project-context` (branch `feat/shared-project-context`), command `zsh tools/tests/e2e-context.zsh`, exit 0, final line `ALL PASS`. The script printed six `ok` lines (checks 1, 2, 2, 3, 3, 4), all passing.

## Setup

    scratch socket: tctest-75912-22458 · TC_CONTEXT_DIR=/private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tctest.wcjGtN/ctx · TC_STATE=/private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tctest.wcjGtN/state

Models: `claude -p --model haiku` (first turn), `claude -p --model sonnet` (lead merge), claude 2.1.312. Tmux: scratch server `-L tctest-… -f /dev/null` via `lib.zsh`; all writes under the scratch `$TT_DIR`, removed by `tt_done`. Load average at start about 11.

## 1. First turn

```
added under ## Map: - the board server is board/server.py and the codeword for this run is QUARTZ-75912 (files: board/server.py) · 2026-10-29
--- seeded file (/private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tctest.wcjGtN/ctx/tt.md):
# tt: shared agent context
Last curated: 2026-10-29

## Map
- the board server is board/server.py and the codeword for this run is QUARTZ-75912 (files: board/server.py) · 2026-10-29

## How to run

## Gotchas

## Decisions
--- first-turn reply (haiku): QUARTZ-75912
ok   - 1. seeded entry reached a fresh agent's first turn
```

## 2. Lead merge

```
--- lead reply (sonnet): done
--- file after the merge:
# tt: shared agent context
Last curated: 2026-10-29

## Map
- the board server is board/server.py and the codeword for this run is QUARTZ-75912 (files: board/server.py) · 2026-10-29

## How to run

## Gotchas
- test_ctl_busy.zsh needs an idle tests window first (files: tools/tests/test_ctl_busy.zsh) · 2026-10-29

## Decisions
ok   - 2. the lead merged the item under Gotchas
ok   - 2. Map entry still there (no rewrite of other sections)
```

## 3. Real aged file

```
--- real aged file: /Users/francisco.ruiz/.local/state/agent-board/ideas/agent-board.md,    17231 bytes, dates 2026-10-16 2026-11-04 
ok   - 3. hook exit 0, nothing on stderr
kept 30 of 63 lines, 7973 bytes; last kept line: - [x] 2026-10-16 15:23 · each agent window should say its role, model and effort
ok   - 3. cut at an entry boundary, body <= 8192 bytes, note names the path
```

The real ideas file was only copied (`cp` into the scratch dir). Its mtime (Oct 29 01:14:03, 17231 bytes) is earlier than the e2e run, so the run did not write it.

## 4. Real state

```
--- real context folder before: ls: /Users/francisco.ruiz/.local/state/agent-board/context: No such file or directory
ok   - 4. real context folder unchanged
--- real context folder after: ls: /Users/francisco.ruiz/.local/state/agent-board/context: No such file or directory
```

## Suites

```
python3 -m unittest discover -s board/tests   ->  rc=0, "Ran 566 tests in 243.241s", "OK"   (baseline 549 + 17 new; lead's criterion 566)
tmux-ctl run -t 2400 tests 'zsh tools/tests/run-all.zsh > /private/tmp/runall.e2e.log 2>&1; echo rc=$?; grep -c "^FAIL" /private/tmp/runall.e2e.log'
    -> rc=0, 0   (the wrapper itself exits 1 only because grep -c prints 0 and returns 1)
Log: 37 "### test_*.zsh" headers, 37 "ALL PASS", 0 lines starting FAIL;
     "### test_context_inject.zsh" and "### test_ctl_context.zsh" are both listed.
```
(The brief's `Ran 482 tests` is stale; the lead set the criterion to 566.)

## Bugs found

none.
