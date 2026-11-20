# Review: resume-picker wrapped footer (6c6c1dd..f4e4439), reviewer rev-resume

## Verified by me
- `zsh tools/tests/test_ctl_dialog_show.zsh` in the worktree: ends `ALL PASS`, rc=0.
- `python3 -m unittest board.tests.test_paneclass`: `Ran 69 tests`, `OK`.
- `python3 tools/tests/fixtures/dialogs/check.py`: `fixtures: 13 checked, 0 problems`.
- I did not re-run the full suites, and I did not run any mutation myself. The implementer's 1901 OK and 172-job ALL PASS claims are unverified by me.

## Strengths
- The cause is right. `resume()` anchored on the last row only. It now locates the last session's meta row within the last 4 rows and joins the footer rows after it (at most 3). `lines` still ends at `f-1`, so it stops before the footer.
- The paneclass fix is correct and bounded. `_wrap_joined` joins adjacent pairs only, and blank, rule and box rows never join. `PROMPT_PATTERN` has no anchors, so joining adds no new match mechanism.
- It also fixes a second consumer that the brief did not name (the board classified the 70-column picker as `ready`).
- The negative test covers three "between" shapes (blank row, text row, rule row).
- The plan footer wrap is handled and tested, and the report states which other footers were checked and why they do not wrap.

## Issues

### Critical
None.

### Important
None.

### Minor
1. `board/paneclass.py:_wrap_joined`. Two unrelated adjacent prose rows can falsely raise "waiting".
   - Failure scenario: an assistant message wraps in the tail as `…then press Enter to` / `select the file…`. The joined row contains `Enter to select`, so a `ready` pane shows as `waiting`.
   - This is the accepted trade-off (adjacent rows only, last 12 rows). There is no test for that exact false positive; the negative test only covers non-adjacent rows. A comment saying so would be enough.
2. `board/paneclass.py` pair-join does not handle a phrase split over 3 rows. This is not needed for the captured widths. It is noted only because at roughly 50-60 columns Claude Code drops `Enter to resume` altogether, which the report already states.
3. `tools/lib/dialog.zsh` `resume()`: the meta-row search `i >= N2-3` assumes N2 is the last non-blank row. This holds for the fixtures. I did not test a footer of 4 or more rows, which would return `none`. That is acceptable, since the brief says 3.
4. `tools/tests/test_ctl_dialog_show.zsh`, `plan-wrapped` is a synthetic variant. It is labelled as synthetic in the test. See the fixture line below.

## Evidence lines
1. Fixture origin:
   - `resume-80.txt` and `resume-70.txt`: the README documents the capture (scratch tmux server `-L rsmprobe -f /dev/null`, `capture-pane -p -J`, Claude Code 2.1.329). The cell widths look like real captures, and `check.py` passes. I could not corroborate this from the evidence directory: `grep "Space to\|Enter to"` on `evidence-resume/resume-2.1.329.txt` returned no lines, probably because that file is the 200-column capture. So I take the capture claim from the README and the report, not from my own check.
   - `plan-wrapped`: hand-made, derived by a script from the real `plan.txt`, and disclosed as synthetic in the test comment. Acceptable because the capture rule is met by the README note on how the wrap was produced. It is a Minor point only, since no real capture of a wrapped plan footer exists.
   - The `test_split_phrase_across_unrelated_rows_stays_ready` rows are hand-written, but they are negative-control rows, not a UI capture.
2. Artefact under test: the zsh test drives the real `tools/lib/dialog.zsh` through `dialog show` against fixture replays. The paneclass tests call the real `paneclass.classify` with `server._rows` on the real fixture file. Nothing re-implements the code under test. No external command decides the outcome; awk and tmux replay are the existing harness.
3. User-experienced check: not applicable. There is no browser or layout probe. The fixtures are the rendered rows, and the 70 and 80 column widths are the layouts the user sees.
4. State: the fixtures are static, so state is not a factor. The report notes load flakes in an earlier concurrent run (`test_bg_lock`, `test_claude_orchestrator_dc`, `test_all_runner`, each passing alone). I did not check for hard-coded HOME paths in the new tests; the diff adds none.
5. Universal claims:
   - The report's "trust, permission and question footers do not wrap at 80 columns" rests on stated footer widths (34, 30, up to 62), not on a full listing of every footer variant. The claim is plausible, but it is a stated width, not uncapped captured output.
   - The mutation for the three-row join in `test_split_phrase_across_unrelated_rows_stays_ready` was "reasoned, not run" by the implementer (report). I did not run it either.

## Verdict
Ready to merge: yes. The Minor items are optional follow-ups, none of them blocking.
