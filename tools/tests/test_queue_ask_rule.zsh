#!/usr/bin/env zsh
# test_queue_ask_rule.zsh — the lead rules (claude/orchestrator.md § Queue mode) carry the `ask` integration:
# the value in metadata.queue.integration, the merge-request command, and the two [Discord] lines. Pure grep; no tmux.
source "${0:A:h}/lib.zsh"
DOC="${0:A:h:h:h}/claude/orchestrator.md"
queue="$(grep -E '^- \*\*Queue mode\.\*\*|^  [0-9]\. ' "$DOC")"
has_re() { print -r -- "$queue" | grep -qE -- "$1" }
has() { print -r -- "$queue" | grep -qF -- "$1" }
check 'integration values list "ask"' has '"merge" | "mr" | "keep" | "ask"'
check 'ask is offered as an option (approve from the phone)' has 'approve from the phone'
check 'step 2 runs tmux-ctl discord merge-request with the flags' has 'tmux-ctl discord merge-request --project <p> --task <id> --spec <spec> --branch <b> --tests "<verdict line>" --verdict "<final review verdict>" [--finding "<line>"]…'
check 'step 2 records awaiting merge approval' has 'awaiting merge approval <branch>'
check 'merge approved line is handled' has '[Discord] merge approved for <spec>'
check 'keep branch line is handled' has '[Discord] keep branch for <spec>'
check 'merge approved sets merged <sha>, keep sets kept <branch>' has_re 'merge approved for <spec>`[^.]*merged <sha>.*keep branch for <spec>`[^.]*kept <branch>'
check 'the two lines are never a push' has 'neither line is ever a push'
check 'ask records the metrics run as --outcome kept' has 'metrics record <spec> --batch <id> --outcome kept'
check 'ask stores push false' has '`ask` stores `"push": false`'
check 'morning report lists specs still awaiting merge approval' has 'lists each spec still awaiting merge approval with its branch'
# the pinned merge approval: a continuation paragraph of step 2 (not a step line), one line
pinned="$(grep -F '     **Pinned merge approval.**' "$DOC")"
pin() { print -r -- "$pinned" | grep -qF -- "$1" }
check 'pinned rule is one continuation line'               test "$(print -r -- "$pinned" | grep -c .)" -eq 1
check 'step 2 sends the merge to the pinned rule'          has 'with `merge` of the approved SHA only, as Pinned merge approval below says'
check 'pinned: the approved line carries the full sha'     pin '`[Discord] merge approved for <spec> @ <sha>`, where `<sha>` is the full SHA'
check 'pinned: the branch tip is checked against the sha'  pin 'run `git rev-parse <branch>`'
check 'pinned: the sha is merged, not the branch name'     pin '`git merge <sha>`, never the branch name'
check 'pinned: outcome records the merge sha'              pin 'record `metadata.outcome = "merged <merge sha>"`'
check 'pinned: a moved tip is re-requested, not merged'    pin 'When it differs, do not merge: run `tmux-ctl discord merge-request` again'
check 'pinned: the outcome stays awaiting merge approval'  pin 'keep `metadata.outcome = "awaiting merge approval <branch>"`'
check 'pinned: a line without the sha is not pinned'       pin 'without ` @ <sha>` (a card posted before this rule) is not pinned: re-request the same way and never merge on it'
tt_done
