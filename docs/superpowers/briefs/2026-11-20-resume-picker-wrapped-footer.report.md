# Report: the resume picker is read when its footer wraps

Branch `fix/resume-wrapped-footer` (worktree `.claude/worktrees/resume-wrapped-footer`), not merged.

## Cause
`tools/lib/dialog.zsh` `resume()` required the LAST row to match both `Enter to resume` and `Esc to close$`. At 80 columns
Claude Code 2.1.329 wraps the footer onto two rows (three at 70, with `Enter to` / `resume` split), so `dialog show` printed
`dialog: none`. The 200-column fixture never wrapped. A second consumer had the same blind spot: `board/paneclass.py`
`WAITING_RE` searched single rows of the 12-row tail, so the 70-column picker classified `ready`.

## Fix
- `dialog.zsh resume()`: finds the last session's meta row (within the last 4 rows), joins the rows after it (max 3) and
  matches the footer on the join; `lines` still stops before the footer.
- `dialog.zsh plan()`: footer `ctrl+g to edit in … · <path>` may wrap onto a second one-word row.
- `board/paneclass.py`: `_waiting()` also searches the tail with adjacent text-row pairs joined by a space; blank, rule and
  box rows never join (PROMPT_PATTERN has no `^`/`$` anchors, so joining does not change meaning).
- `press --expect` still reads through `_dlg_screen` (unchanged).

## Footers checked at 80 columns
- resume: real capture wrapped, fixed. plan: footer is 78 columns with a short slug, wraps with a longer one: fixed, synthetic variant.
- trust (`Enter to confirm · Esc to cancel`, 34), permission (`Esc to cancel · Tab to amend`, 30), question
  (`Enter to select · … Esc to cancel`, up to 62): all shorter than 80 columns, so they do not wrap; left unchanged. They would only wrap below ~62 columns, not captured.
- At 60 and 50 columns Claude Code drops `Enter to resume` from the footer: not handled, not captured.

## Tests (names)
- `test_ctl_dialog_show.zsh`: resume-80 and resume-70 run through the fixture loop (FROM/TO maps, "all 12 dialogs fixtures ran"); `plan-wrapped` variant.
- `test_paneclass.DialogFixturesTest.test_dialog_fixtures_are_waiting_and_idle_ones_stay_ready` (resume-70 subtest, red before the paneclass fix).
- `test_phrase_split_across_two_adjacent_rows_is_waiting`; mutation: drop the `_wrap_joined` search → fails (verified: it and the resume-70 subtest fail).
- `test_split_phrase_across_unrelated_rows_stays_ready`; mutation: join a run of 3+ rows (or skip the row between) → `Enter to` … `resume` becomes waiting (not run as a mutation; reasoned).
- Fixtures: `resume-80.txt` (real capture), `resume-70.txt` (real capture), `expect/resume-80.json`, `expect/resume-70.json`; README rows added.

## Commits
- 69ed23f `fix(tmux-ctl): dialog show reads the resume picker and the plan footer when they wrap`
- 2a2e634 `fix(board): a key-hint phrase split over two wrapped rows still classifies as waiting`
- this report (see git log)

## Verdicts
- `python3 tools/tests/fixtures/dialogs/check.py`: `fixtures: 13 checked, 0 problems`
- `python3 -m unittest discover -s board/tests` (after the last code edit): `Ran 1901 tests in 703.494s` / `OK` / rc=0
- `zsh tools/tests/all.zsh`: `ALL PASS 172 jobs in 8m55s`, rc=4 (time budget only).
  An earlier run, concurrent with fix-relay's suite and my board run, failed `test_bg_lock` ("send returns fast"),
  `test_claude_orchestrator_dc` ("leak: no fake holder left") and `test_all_runner`; all three passed alone (rc=0) and
  the rerun was green: load flakes, unrelated to this change. (The first run before the paneclass fix had one real
  failure, resume-70 in test_paneclass, now fixed.)

## Context learned
- A new real capture under `fixtures/dialogs/` is also read by `board/tests/test_paneclass.py` (every `dialogs/*.txt` must classify waiting): add one there and the board suite is the second consumer.
- Running board unittest and all.zsh at once, next to another teammate's suite, produces timing flakes (bg_lock, orchestrator_dc leak); run all.zsh alone.
- Claude Code drops `Enter to resume` from the picker footer at 60 columns and below.
