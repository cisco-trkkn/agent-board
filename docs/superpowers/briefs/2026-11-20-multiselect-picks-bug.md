# Brief: multi-select from Discord pressed the wrong set (runbook #30 item 5)

## Rules

1. Role: debugger for one bug. Deliverable: a root cause with evidence, a failing test that reproduces it, the fix,
   and the suite verdict, all on branch `fix/multiselect-picks` in worktree
   `/Users/francisco.ruiz/agent-board/.claude/worktrees/multiselect-picks` (create it from `main` at its current HEAD:
   `git -C /Users/francisco.ruiz/agent-board worktree add -b fix/multiselect-picks .claude/worktrees/multiselect-picks main`).
   You own every file in that worktree. Stage only your own paths (`git add <paths>`, never `-A` or `.`) and run no
   whole-tree git operation (`stash`, `reset`, `checkout`, `clean`, `rebase`). Never touch the main checkout
   (`/Users/francisco.ruiz/agent-board`): it is the live install. Never restart bridges, the board or any lead, and
   never send keys to a real tmux pane (the user is mid-runbook on `interiors:probe`, pane `%179`). Reading real
   panes and logs is fine.
2. Skills, by full name: `superpowers-extended-cc:systematic-debugging` first (before any fix), then
   `superpowers-extended-cc:test-driven-development` with `test-driven-development-extras`, and
   `superpowers-extended-cc:verification-before-completion` before reporting. The design is settled: do not run
   `brainstorming` and do not ask the user anything.
3. Questions and decisions go to the lead (`team-lead`) as a message. If an answer can't wait, make the reasonable
   choice, note the assumption, and keep going. The exception: when the question is about a failed acceptance
   criterion, a spec constraint your option cannot meet, a gate, or a step that changes shared state or removes
   something (a worktree, a published doc), wait for the lead's answer before that step. A user-confirm step that a
   loaded skill names is such a gate: it goes to the lead to relay, and a spec or plan never stands in for the user's
   answer. Only reversible, local work continues meanwhile. "My plan unless you say otherwise" is for choices you can
   still undo.
4. Decided: see the Decided block below.
5. Read `~/agent-board/claude/worker.md`; its common rules and teammate section apply to you.

## The bug

On the real setup (main `d05df9e`, bridges and board restarted 2026-11-20 ~01:55Z), the user answered a multi-select
AskUserQuestion from Discord. Pane `%179` (`interiors:probe`, plain `claude` 2.1.329, 80 columns) showed:

```
❯ 1. [ ] Apple
         Include Apple.
  2. [ ] Pear
         Include Pear.
  3. [ ] Plum
         Include Plum.
  4. [ ] Type something
     Submit
────────────────────────────────────────────────────────────────────────────────
  5. Chat about this
Enter to select · ↑/↓ to navigate · Esc to cancel
```

- Attempt 1 (03:10Z): the user says they selected only Pear; audit `03:10:10Z dialog ab:dlg:p179-c54827ea39058af7:submit pressed: Pear`.
  The pane then showed Claude Code's "Review your answers" screen (`→ Pear`, `1. Submit answers` / `2. Cancel`); the lead pressed Esc.
- Attempt 2 (03:11Z, the same question asked again, so the SAME dialog id `p179-c54827ea39058af7`, new Discord message
  `1573173860445192315` posted 03:11:16Z): the user tapped **Apple and Plum**, both turned green, then Submit.
  Audit `03:11:36Z … :submit pressed: Apple, Pear`. Review screen showed `→ Apple, Pear`. Expected `Apple, Plum`. The lead pressed Esc.

Evidence locations:
- Bridge: `tools/discord-bridge/bridge.js` `onDialogInteraction` (~line 491): toggles flip the button style on the
  message itself; submit builds `ev.picks` from style-3 buttons whose custom_id ends `:t<n>`. State dir
  `~/.local/state/agent-board/discord/interiors/` (`bridge.log` lines ~447-452, `audit.jsonl`, `events/`).
- Board: `board/discord_dialogs.py` (scan, message shape, click consumer), `board/server.py` wiring.
- Press: `tools/lib/dialog.zsh` (press for multi: "sets multi-select to the wanted set", ~line 344 area);
  `tools/tests/test_ctl_dialog_press.zsh`; fixtures `tools/tests/fixtures/dialogs/question-multi.txt`.
- Ledger of spec C (rulings about multi-select keys): `docs/superpowers/ledgers/2026-11-19-remote-discord-only/progress.md`.

Hypotheses to test, not conclusions: (a) the picks numbers are right but press maps them to the wrong rows (the
description lines under each option, off-by-one, or reading the cursor row); (b) the board maps picks to labels wrongly
(e.g. stale options from an earlier post with the same id); (c) the re-post with the same id leaves an older message's
buttons or state in play. Find which one with evidence from the real logs/events before writing any fix.

## Decided

- Branch/worktree as in rule 1. Commit message style: `fix(<scope>): …` with the trailer
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (from the lead's attribution).
- Tests: the RED test must reproduce the real shape (the 80-column pane above with description lines). Use the
  scratch tmux harness (`tools/tests/lib.zsh`, servers start with `-f /dev/null`), never the real server.
- Full suite before reporting: `zsh tools/tests/all.zsh` in your worktree; its verdict line is the summary
  `ALL PASS <n> jobs …` (rc 4 = time budget only).
- If the root cause is NOT a code bug (e.g. the user's taps), report that with the evidence and stop; no fix.
- Do not merge. The lead reviews and merges.

## Report

Write `docs/superpowers/briefs/2026-11-20-multiselect-picks-bug.report.md` in your worktree (root cause, evidence lines,
test name, commit SHAs, suite verdict line, `Context learned` items), commit it, then message `team-lead` with a
3-line summary and the path.
