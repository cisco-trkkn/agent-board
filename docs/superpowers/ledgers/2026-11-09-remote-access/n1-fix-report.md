# N1/N2 fix report (HEAD 375c175; commits ca3adac fix(tmux-ctl), 375c175 docs(orchestrator))

## What changed per file
- `tools/lib/approve.zsh`: header/usage text say `--expect` is every preview line, newline-separated, in order. The awk emits `P:` lines for a Bash prompt = the lines between its two `╌` rules; for other tools (Write/Edit) the path header line only (file content is no longer emitted). It emits `X:ambiguous` and no `P:` lines when a solid divider or `╌` rule at column 1 (byte-literal `index()==1`) sits above the chosen divider `s`, or when the number of `╌` rules between `s` and the question is not exactly 2. The shell compares the `P:` sequence with the `--expect` lines (each trimmed, empty lines dropped) for exact equality (count, order, text); mismatch or ambiguity -> `approve: the prompt in <win> changed`, exit 1, no key. The old any-line `found` loop is gone.
- `tools/tests/test_ctl_approve.zsh`: new N1 block built from `bash-git.txt` with sed/awk: A (extra line before approved one, one-line --expect refused, GOT:NONE), A-ok (both lines in order accepted, key 1), A wrong order refused, --expect longer than the preview refused, C once and deny (fake solid divider + " Bash command" + `╌` rule, copied from the fixture, after an evil line) refused, D (third `╌` rule hiding an evil line) refused. The two spoof tests (`s-yes`, `s-no`) now pass explicit two-line `--expect` because their preview has an extra line. Each new test has a `# mutation:` comment.
- `claude/orchestrator.md`: Approval protocol step 3: the lead re-reads with `tmux-ctl read <window>` right before pressing and compares tool and command with what it sent for `#n` (else presses nothing, asks again); `--expect` is every line between the two dashed rules, newline-separated, in order (Write/Edit: the path line).
- `docs/INSTALL.md`: N2 wording: the lead's Bash commands do not see `TELEGRAM_STATE_DIR`; hooks and other non-Bash children still inherit it; none of this repo's hooks starts `claude` from the lead.
- `tools/tests/e2e-remote-access.md`: unchanged (grep: only item 13 `--expect "trust"` on a dialog that is not a command preview; no multi-line or one-line-rule text).

## Mutations (scratch copy of HEAD under the scratchpad `mut/`, `TC_CTL` pointed at the copy; each run once)
- Deleted the awk loop `for (i = 1; i < s; i++) if (index(l[i], "──────────") == 1 || index(l[i], "╌╌╌╌╌╌╌╌╌╌") == 1) amb = 1` -> observed `FAIL - N1 C: fake divider and rule in the preview, once: exit 1 + changed, no key`, same for `deny` (2 FAILED).
- Replaced `amb = (nr != 2)` by `amb = 0` -> observed `FAIL - N1 D: a third rule in the preview: exit 1 + changed, no key` (1 FAILED).
- Replaced the sequence compare by "the first --expect line equals any P line" -> observed `FAIL - N1 A: one line approved of a two-line preview: exit 1 + changed`, `FAIL - N1 A: no key`, `FAIL - N1 A: lines in the wrong order: exit 1, no key` (3 FAILED).
- Dropping the former `grep -aq '^X:'` shell check changed no result (redundant: an ambiguous prompt has no `P:` lines), so it was removed from the code.
- First C variant (fake divider followed by a fake rule) was not caught by the above-divider mutation (it was refused for another reason), so the C fixture was changed to include the " Bash command" line; the table above is for the final tests.

## Test commands on HEAD 375c175 (rc read alone, `grep -a -c FAIL` on the output)
### `zsh tools/tests/test_ctl_approve.zsh`

```
ok   - help: approve line
ok   - help: telegram line kept
ok   - help: nothing after the header
ALL PASS
```
rc=0 (read alone); grep -c FAIL = 0

### `zsh tools/tests/test_ctl_telegram.zsh`

```
ok   - scanned output files > 0 (19)
ok   - secret hits in all output = 0
ok   - leak: no stub poller left
ALL PASS
```
rc=0 (read alone); grep -c FAIL = 0

### `zsh tools/tests/test_claude_orchestrator_tg.zsh`

```
ok   - prompt file present: positional prompt kept
ok   - no prompt file: flag after channel value
ok   - no prompt file: positional prompt kept
ALL PASS
```
rc=0 (read alone); grep -c FAIL = 0

### `bash claude/hooks/tests/test-telegram-env-scrub.sh`

```
PASS no TELEGRAM_STATE_DIR: nothing
PASS no CLAUDE_ENV_FILE: exit 0, nothing printed
PASS a shell sourcing the file sees the var unset
pass=10 fail=0
```
rc=0 (read alone); grep -c FAIL = 0

### `zsh tools/tests/test_plugin.zsh`

```
ok   - lead rules: ideas are marked when queued
ok   - lead rules: running plan is the first exceptions item
ok   - lead rules: metadata.queue.current shape names the plan
ALL PASS
```
rc=0 (read alone); grep -c FAIL = 0

### `zsh tools/tests/test_hook_gate.zsh`

```
ok   - settings.json has no absolute path
ok   - hooks.json hooks pass --scoped
ok   - hooks.json has no absolute path
ALL PASS
```
rc=0 (read alone); grep -c FAIL = 0

### `python3 -m unittest board.tests.test_telegram_badge -v`

```
----------------------------------------------------------------------
Ran 8 tests in 0.007s

OK
```
rc=0 (read alone); grep -c FAIL = 0

## Notes
- Write prompt: approved lines are the path only; scrollback dividers above the prompt make approve refuse (fails closed).
- Leak check: `tmux -L tt list-sessions` finds no scratch server after the runs.

## Fix round 2

Commits: the `test(tmux-ctl)` fixture commit and the `fix(tmux-ctl)` commit (see `git log -2`).

### R1 probe (one real run, claude 2.1.321, scratch tmux server `-L apprb -f /dev/null`, 200x50, scratch git dir, `claude --permission-mode default`; answered 4 (No) each time; server killed, scratch dir removed)
- Asked for a two-line command whose second line begins `────`: the preview is drawn ` │ echo a` / ` │ ──── echo probe`. Saved as `tools/tests/fixtures/approve/bash-multiline.txt` (+ README row).
- Second probe, second line beginning `╌╌╌╌`: drawn ` │ echo a` / ` │ ╌╌╌╌ echo probe2` (not saved).
- Result: every preview line is INDENTED (a single-line command is drawn ` cmd`). A command cannot put a divider or `╌` rule at column 1.
- Consequence: the reviewer's R1 variant (a11) draws its fake frame at column 1, which a real preview cannot produce. The Decided rule (refuse a column-1 line between r1 and r2) is implemented, but it does NOT refuse a11 (the fake rule is r1, so only the indented approved line lies between r1 and r2). No R1 test was added; asked the lead (message sent) and kept going. a11 stays accepted: unreachable with a real prompt.

### Changes
- `approve.zsh`: (O1) option match is `O:<->:"$want"`, the whole label; (R1 hardening) `amb = 1` when a line strictly between r1 and r2 starts with a non-space character.
- `test_ctl_approve.zsh`: T1 (`--expect "   "` on the fake-frame prompt), T2 (real solid divider removed, real `╌` rule above the fake frame), column-1 preview line, real `bash-multiline.txt` approvable with `$'│ echo a\n│ ──── echo probe'` (and refused with one line), O1 x3 (row 2 ending `:No` with a real No → deny key 4; no real No → "no No option"; no plain Yes, row 2 ending `:Yes` → "no one-time Yes").
- `claude/orchestrator.md`: step 3 clause now says `<lines>` are not exactly the lines of the command (reviewer m1). The m2 comment in `approve.zsh` was reworded too.

### Mutations (scratch copy of the final tree; each run once)
- `O:<->:"$want"` → `O:*:"$want"` : `FAIL - O1: row 2 ends :No, deny: key 4 (the real No)`, `FAIL - O1: no real No row, row 2 ends :No: deny refused, no key`, `FAIL - O1: no plain Yes, row 2 ends :Yes: once refused, no key` (3 FAILED).
- deleted ` || -z "$got"` : `FAIL - T1: blank --expect on the fake-frame prompt: exit 1, no key` (1 FAILED).
- deleted ` || index(l[i], "╌╌╌╌╌╌╌╌╌╌") == 1` from the above-divider loop : `FAIL - T2: only a ╌ rule above the fake divider: exit 1, no key` (1 FAILED).
- deleted the `l[i] ~ /^[^ \t]/` loop : `FAIL - column-1 preview line: exit 1, no key` (1 FAILED).
- Unmutated tree: no FAIL.

### Test commands (final tree)
### `zsh tools/tests/test_ctl_approve.zsh`

```
ok   - help: approve line
ok   - help: telegram line kept
ok   - help: nothing after the header
ALL PASS
```
rc=0 (read alone); grep -a -c FAIL = 0

### `zsh tools/tests/test_ctl_telegram.zsh`

```
ok   - scanned output files > 0 (19)
ok   - secret hits in all output = 0
ok   - leak: no stub poller left
ALL PASS
```
rc=0 (read alone); grep -a -c FAIL = 0

### `zsh tools/tests/test_claude_orchestrator_tg.zsh`

```
ok   - prompt file present: positional prompt kept
ok   - no prompt file: flag after channel value
ok   - no prompt file: positional prompt kept
ALL PASS
```
rc=0 (read alone); grep -a -c FAIL = 0

### `bash claude/hooks/tests/test-telegram-env-scrub.sh`

```
PASS no TELEGRAM_STATE_DIR: nothing
PASS no CLAUDE_ENV_FILE: exit 0, nothing printed
PASS a shell sourcing the file sees the var unset
pass=10 fail=0
```
rc=0 (read alone); grep -a -c FAIL = 0

### `zsh tools/tests/test_plugin.zsh`

```
ok   - lead rules: ideas are marked when queued
ok   - lead rules: running plan is the first exceptions item
ok   - lead rules: metadata.queue.current shape names the plan
ALL PASS
```
rc=0 (read alone); grep -a -c FAIL = 0

### `zsh tools/tests/test_hook_gate.zsh`

```
ok   - settings.json has no absolute path
ok   - hooks.json hooks pass --scoped
ok   - hooks.json has no absolute path
ALL PASS
```
rc=0 (read alone); grep -a -c FAIL = 0

### `python3 -m unittest board.tests.test_telegram_badge -v`

```
----------------------------------------------------------------------
Ran 8 tests in 0.008s

OK
```
rc=0 (read alone); grep -a -c FAIL = 0


### After the lead's reply (R1 agreed)
Added one sentence to orchestrator.md step 3 (multi-line command shows each line after a `│ ` gutter; --expect lists them as shown). Re-ran test_claude_orchestrator_tg.zsh and test_plugin.zsh: rc=0, FAIL count 0 each, ALL PASS. a11 is reported as unreachable per the probe (fixtures/approve/bash-multiline.txt).

Gutter example added to step 3 (commit above): `zsh tools/tests/test_claude_orchestrator_tg.zsh` rc=0, grep -a -c FAIL = 0, last line ALL PASS.
