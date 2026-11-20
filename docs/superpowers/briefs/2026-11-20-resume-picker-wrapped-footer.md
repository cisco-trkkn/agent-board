# Brief: the resume picker is not read when its footer wraps (runbook #30 item 11)

## Rules

1. Role: implementer for one bug. Deliverable: a failing test from the real capture, the fix, both verdict lines, on
   branch `fix/resume-wrapped-footer` in worktree `/Users/francisco.ruiz/agent-board/.claude/worktrees/resume-wrapped-footer`
   (create it from `main` at its current HEAD:
   `git -C /Users/francisco.ruiz/agent-board worktree add -b fix/resume-wrapped-footer .claude/worktrees/resume-wrapped-footer main`).
   You own every file in that worktree. Stage only your own paths (`git add <paths>`, never `-A` or `.`) and run no
   whole-tree git operation (`stash`, `reset`, `checkout`, `clean`, `rebase`). Never touch the main checkout
   (`/Users/francisco.ruiz/agent-board`): it is the live install. Never restart bridges, the board or any lead, and
   never send keys to a real tmux pane (`interiors:resume` `%216` holds the real picker; reading it is fine).
2. Skills, by full name: `superpowers-extended-cc:systematic-debugging` (confirm the cause below before fixing), then
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

Claude Code 2.1.329, `claude --resume` in an 80-column pane. The footer wraps onto two rows:

```
  Ctrl+A to show all projects · Ctrl+B to only show current branch · Space to
  preview · Ctrl+R to rename · Type to search · Enter to resume · Esc to close
```

(in the capture the second row may itself end before `close`; check). `tmux-ctl dialog %216 show` prints
`dialog: none in %216` (exit 1), so the board posts the picker only as an idle "waiting for your reply" item.
Likely cause: `tools/lib/dialog.zsh:204`, `resume()` needs the LAST row to match both `Enter to resume` and
`Esc to close$`. The fixture `tools/tests/fixtures/dialogs/resume.txt` is 200 columns wide (one-row footer), so the
tests never saw a wrapped one.

Evidence (read-only): `/private/tmp/claude-503/-Users-francisco-ruiz-agent-board/33dc2ec3-6b11-4560-b5b6-a9d75f97b11f/scratchpad/evidence-resume/`
(`resume-2.1.329.txt` = `tmux capture-pane -p -J` of `%216`; `show.txt` = the `dialog show` output).

## Decided

- Fix: accept a footer wrapped over up to 3 trailing rows for `resume` (join the trailing rows, then match), and check
  the same wrap for the other footers that `dialog.zsh` anchors on one row (trust, plan, question, permission): fix any
  that break the same way at 80 columns, and say in the report which you checked and how. `lines` must still stop at
  the footer, and press `--expect` must still read through `_dlg_screen` (unchanged rows).
- Add the real capture as fixture `tools/tests/fixtures/dialogs/resume-80.txt` with its `expect/resume-80.json`
  (follow `fixtures/dialogs/README.md`, redaction rule included; the session titles Alpha/Beta are safe), and update
  the fixture counts in `tools/tests/test_ctl_dialog_show.zsh` (FROM/TO maps and the "all N dialogs fixtures ran" check).
- Tests: `zsh tools/tests/test_ctl_dialog_show.zsh`, `python3 -m unittest discover -s board/tests`, then the full
  suite `zsh tools/tests/all.zsh`; its verdict is the `ALL PASS <n> jobs …` line (rc 4 = time budget only). Run the
  board tests only after your last edit.
- Commit style `fix(tmux-ctl): …`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Do not merge or restart anything.

## Report

Write `docs/superpowers/briefs/2026-11-20-resume-picker-wrapped-footer.report.md` in your worktree (cause, test
names, SHAs, the verdict lines, which footers you checked, `Context learned`), commit it, then message `team-lead`
with a 3-line summary.
