# Report: the "Review your answers" screen was never posted (runbook #30 item 5)

## Outcome
Fixed on branch `fix/review-screen-post` (worktree `.claude/worktrees/review-screen-post`), commits a63a1d6 and 80d1c9d.

## Root cause (verified)
`paneclass.classify` calls a claude pane "waiting" only when `TC_PROMPT_RE` (`tools/lib/tc-env.zsh`) matches the last 12 rows.
The review screen has no key-hint footer and its rows are `❯ 1. Submit answers` / `2. Cancel`, so none of the alternatives
(`❯ *1\. *Yes`, `Enter to select`, ...) matched. Run on the real capture before the fix:
`classify("2.1.329", rows, False)` -> `('claude', 'ready')`. `discord_dialogs._waiting` takes only status "waiting",
so `scan` never saw the pane (state: `dialogs` empty, `last_status {"%179": "ready"}`). The lead's hypothesis was right.
Second finding: "Review your answers" itself sits above the 12-row tail in the real capture (23 lines), so my first fix
(matching that title, a63a1d6) still failed; 80d1c9d matches the option row `1\. *Submit answers` instead (no `❯`, so it
also holds when the cursor is on Cancel).

## Fix and choices
- `tools/lib/tc-env.zsh`: `|1\. *Submit answers` added to `TC_PROMPT_RE` (also read by board/tc_env.py and `tmux-ctl tell`).
- Both rows stay `permanent: true` (the Confirm step); `dialog show` already parsed the screen as kind `unknown`, and nothing in the evidence marks them otherwise.
- Fixture `tools/tests/fixtures/dialogs/question-review.txt` (real capture, no `/Users/` paths), `expect/question-review.json`, a README row.
- `tools/tests/test_ctl_dialog_show.zsh`: fixture count 9 -> 10 and FROM/TO rows 8-16 for the new fixture.

## Tests
RED: `python3 -m unittest board.tests.test_paneclass.DialogFixturesTest` failed with `('claude','ready') != ('claude','waiting')`
for `question-review.txt` (it globs `dialogs/*.txt`, so the new fixture drives it). GREEN after 80d1c9d:
`test_paneclass` + `test_tc_env` 73 tests OK; `test_ctl_dialog_show.zsh` shows the three question-review checks ok.

## Verdicts
- `zsh tools/tests/all.zsh` on 80d1c9d: `ALL PASS 172 jobs in 8m14s` (rc=4 = time budget only; 0 FAIL lines).
- `python3 -m unittest discover -s board/tests` standalone: not a clean verdict. One run overlapped my regex edits and showed 2 failures (the fixture test and `test_prompt_regex_agrees`, both caused by the edit in flight); the rerun on the final code I stopped to save time. The board tests inside the all.zsh run passed.
- Not verified: the live post to Discord (needs a real pane; not done by rule 1). Not run: the other python suites from CLAUDE.md beyond what all.zsh covers.

## Follow-up
`TC_PROMPT_RE` is a growing list of dialog strings; each new Claude Code screen without a footer will need its own entry.

Context learned:
- (Gotchas) classify only reads the last 12 rows, so a prompt marker must be near the options, not the title (files: board/paneclass.py, tools/lib/tc-env.zsh) 
- (Map) every dialogs fixture is auto-picked up by DialogFixturesTest and test_ctl_dialog_show.zsh (hard-coded count 10 and FROM/TO rows) (files: board/tests/test_paneclass.py, tools/tests/test_ctl_dialog_show.zsh)
- (Gotchas) running a board test run while editing tc-env.zsh gives false failures: tc_env parses it at import (files: board/tc_env.py)
