# Brief: a multi-select's "Review your answers" screen never reaches Discord (runbook #30 item 5)

## Rules

1. Role: debugger and implementer for one bug. Deliverable: root cause with evidence, a failing test that reproduces
   it from the real capture, the fix, the suite verdict, on branch `fix/review-screen-post` in worktree
   `/Users/francisco.ruiz/agent-board/.claude/worktrees/review-screen-post` (create it from `main` at its current HEAD:
   `git -C /Users/francisco.ruiz/agent-board worktree add -b fix/review-screen-post .claude/worktrees/review-screen-post main`).
   You own every file in that worktree. Stage only your own paths (`git add <paths>`, never `-A` or `.`) and run no
   whole-tree git operation (`stash`, `reset`, `checkout`, `clean`, `rebase`). Never touch the main checkout
   (`/Users/francisco.ruiz/agent-board`): it is the live install. Never restart bridges, the board or any lead, and
   never send keys to a real tmux pane (pane `%179` in `interiors:probe` is the user's runbook window). Reading real
   panes, state files and logs is fine.
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

A multi-select AskUserQuestion answered from Discord: the bridge's Submit pressed the picks (audit
`03:32:46Z dialog ab:dlg:p179-c54827ea39058af7:submit pressed: Apple, Pear`). Claude Code 2.1.329 then shows its
"Review your answers" screen. `tools/lib/dialog.zsh:344` says that screen "is a new dialog: never pressed here", so the
design expects it to be posted to Discord as its own ❓. It never was: the bridge log has no `dialog p179-…` post after
the submit, so the user cannot finish the answer from the phone.

Evidence (saved by the lead at 03:3xZ, in the main checkout, read-only for you):
`/Users/francisco.ruiz/agent-board/docs/superpowers/briefs/evidence-2026-11-20-review/`
- `pane-review.txt`: `tmux capture-pane -p -J` of `%179` on the review screen (80 columns).
- `show-review.json`: `tmux-ctl dialog %179 show` on it: it parses (`kind: unknown`, options `1. Submit answers` /
  `2. Cancel`, both `permanent: true`).
- `_Users_…_dialogs_state.json`: the board's dialog state at that moment: `dialogs` empty and
  `last_status {"%179": "ready"}`. **Lead's lead:** the pane classifier calls the review screen `ready`, not
  `waiting`, so `board/discord_dialogs.py` `scan` never considers it (it only takes `status == "waiting"` panes, ~line 157).
  Verify this; it is a hypothesis.
- `bridge-tail.log`: the bridge log tail.

Code: `board/paneclass.py` (classify, spinner_live, the waiting detection), `board/discord_dialogs.py` (`scan`,
`_post`, ~line 157 and 426), `tools/lib/dialog.zsh`, tests `board/tests/test_paneclass.py`,
`board/tests/test_discord_dialogs.py`, fixtures `tools/tests/fixtures/dialogs/` (README lists what's captured).

## Decided

- The fix: the review screen must be posted as its own dialog (as dialog.zsh:344 assumes), with the usual lifecycle.
  Both rows stay permanent (Confirm step) unless the evidence shows the scan marks them otherwise for a reason you
  can name; report what you chose.
- Add the real capture as a fixture (`tools/tests/fixtures/dialogs/question-review.txt` plus its `expect/` json if the
  fixture checker needs one; follow the README's redaction rule) and drive the RED test from it.
- Tests: `python3 -m unittest discover -s board/tests` and the full suite `zsh tools/tests/all.zsh` in your worktree;
  its verdict is the `ALL PASS <n> jobs …` line (rc 4 = time budget only).
- Commit style `fix(board): …` with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not merge or restart anything; the lead reviews and merges.

## Report

Write `docs/superpowers/briefs/2026-11-20-review-screen-not-posted.report.md` in your worktree (root cause, evidence,
test names, SHAs, both verdict lines, `Context learned`), commit it, then message `team-lead` with a 3-line summary.
