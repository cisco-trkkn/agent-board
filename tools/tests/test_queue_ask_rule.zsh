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
tt_done
