# Upstream feedback draft: superpowers Stop hooks run their full check on every Stop

Target: maintainers of the superpowers-extended-cc plugin, its two Stop guards `stop-wait-guard` and `stop-revalidate-user-gates`.
Scope: cost of the guards on ordinary sessions, and a proposed cheap pre-check for each. No code is included.

## Problem

Both guards run on every Stop, and both do their full work each time, even when their trigger condition cannot be true.

- Audit window, measured: each guard ran 2,207 times. Median run time was about 1.06 s (`stop-wait-guard`) and about 1.04 s (`stop-revalidate-user-gates`). Neither blocked a Stop in the window (0 blocks).
- `stop-wait-guard` only needs to act when a task is still `in_progress`. Probe: 12 of 122 session task dirs under `~/.claude/tasks/session-<sid8>/` hold an in-progress task, across 1,348 sessions. The other sessions pay for a full run that cannot block.
- `stop-revalidate-user-gates` rebuilds its task list from the transcript, and the task dir is emptied, so the task dir cannot be used as its signal. A plain grep of the transcript is also no signal: 199 of 200 recent transcripts contain the words `executing-plans` and `user-gate`, because the skill listing names them in every session. So a text grep would arm the guard in almost every session.

## Proposal

Each guard runs its cheapest arming check before it parses anything.

1. **`stop-wait-guard`: check its own condition 4 first.** Look for any `in_progress` task in `~/.claude/tasks/session-<sid8>/`. If there is none, exit without reading the transcript. This skips the transcript parse in the sessions that cannot block.
2. **`stop-revalidate-user-gates`: scan the tool calls, not the text.** Scan only the `TaskCreate` and `TaskUpdate` `tool_use` lines in the transcript for the gate words. If none match, exit before the rebuild. Probe over 1,495 transcripts: the guard arms on 9. The scan matched exactly those 9 (0 missed, 0 extra). The check is a line-level match on tool calls, so the skill listing does not trigger it.

Both pre-checks run before the existing logic, so when they pass the guard behaves as it does now. The existing checks stay as the authority: the pre-check only decides whether to skip the rest.

## Expected effect

Most Stops skip the transcript parse. The cost for a session with no in-progress task or no gate-marked task drops to the directory check or the tool-line scan. Blocking behaviour should not change if each pre-check is a necessary condition for the guard to block. The probe supports that for both guards in the audit window (0 blocks; the scan matched all 9 arming transcripts), but it is a sample, not a proof.

## Open question for maintainers

- Whether the `TaskCreate`/`TaskUpdate` scan should match on the task metadata fields the rebuild already reads, instead of on the gate words, so the two stay in step if the words change.

Status: draft, not submitted.
