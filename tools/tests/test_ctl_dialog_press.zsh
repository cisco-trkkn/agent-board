source "${0:A:h}/dialog_common.zsh"
# tmux-ctl dialog <win> press --expect <lines> (--option n… | --text t): answers the dialog with the keys of the README's
# `## Key probes` table, only when the dialog on screen equals --expect byte for byte (read twice).
# Mutations (run each, paste the failing line, restore): M1 remove the second read; M2 compare trimmed text, not bytes;
# M3 remove the copy-mode checks; M4 send the digit for every kind.
# Hex of keys: digit 1 = 31; Down = 1b5b42; Enter = 0d.
DOWN=1b5b42; ENTER=0d
# pr <win> <args…>: press with $E as --expect (dl sets out, err, rc)
pr() { local w=$1; shift; dl $w press --expect "$E" "$@" }

pshow p-git $FXA/bash-git.txt; pr p-git --option 1
check "permission by digit: rc 0, chose Yes"          test $rc -eq 0 -a "$out" = 'dialog: p-git: chose "Yes"'
check "permission by digit: the digit alone, no Enter"  test "$(gotk p-git)" = GOT:31

pshow p-perm $FXA/bash-git.txt; pr p-perm --option 2
check "permanent row: pressed, chose its label"       test $rc -eq 0 -a "$out" = 'dialog: p-perm: chose "Yes, and don’t ask again for: git config *"'
check "permanent row: digit 2"                        test "$(gotk p-perm)" = GOT:32

pshow p-single $FXD/question-single.txt; pr p-single --option 2
check "single question: chose Pear"                   test $rc -eq 0 -a "$out" = 'dialog: p-single: chose "Pear"'
check "single question: digit 2 alone"                test "$(gotk p-single)" = GOT:32

# multi-select: the cursor is on row 1 of 4 checkbox rows; toggles are digits, then Down x4 onto Submit, Enter
pshow p-multi $FXD/question-multi.txt; pr p-multi --option 1 --option 3
check "multi-select: chose Apple, Plum"               test $rc -eq 0 -a "$out" = 'dialog: p-multi: chose "Apple, Plum"'
check "multi-select: toggles, Down x4, Enter"         test "$(gotk p-multi)" = "GOT:3133${DOWN}${DOWN}${DOWN}${DOWN}${ENTER}"

pshow p-text $FXD/question-single.txt; pr p-text --text "two words"
check "Other text: chose the text"                    test $rc -eq 0 -a "$out" = 'dialog: p-text: chose "two words"'
check "Other text: digit 3, text literal, Enter"      test "$(gotk p-text)" = "GOT:33$(print -rn -- 'two words' | xxd -p | tr -d '\n')${ENTER}"

pshow p-mtext $FXD/question-multi.txt; pr p-mtext --text hi
check "multi Other text: chose the text"              test $rc -eq 0 -a "$out" = 'dialog: p-mtext: chose "hi"'
# cursor on row 1, Other is row 4: Down x3, text, Down onto Submit, Enter
check "multi Other text: Down x3, text, Down, Enter"  test "$(gotk p-mtext)" = "GOT:${DOWN}${DOWN}${DOWN}6869${DOWN}${ENTER}"

pshow p-plan $FXD/plan.txt; pr p-plan --option 2
check "plan: digit then Enter"                        test $rc -eq 0 -a "$(gotk p-plan)" = "GOT:32${ENTER}"
pshow p-plant $FXD/plan.txt; pr p-plant --text "use hi2"
check "plan text: digit 3, text, Enter"               test $rc -eq 0 -a "$(gotk p-plant)" = "GOT:33$(print -rn -- 'use hi2' | xxd -p | tr -d '\n')${ENTER}"

# the fixture wins over the brief: the cursor starts on option 1 (No, exit), so option 2 (Yes) is Down, Enter and option 1 is Enter
# mutation M4: send the digit for every kind → this fails
pshow p-trust $FXD/trust.txt; pr p-trust --option 2
check "trust: option 2 is Down, Enter (not a digit)"  test $rc -eq 0 -a "$out" = 'dialog: p-trust: chose "Yes, I trust this folder"' -a "$(gotk p-trust)" = "GOT:${DOWN}${ENTER}"
pshow p-trust1 $FXD/trust.txt; pr p-trust1 --option 1
check "trust: option 1 is Enter"                      test "$(gotk p-trust1)" = "GOT:${ENTER}"

pshow p-res $FXD/resume.txt; pr p-res --option 2
check "resume: Down x1, Enter"                        test $rc -eq 0 -a "$(gotk p-res)" = "GOT:${DOWN}${ENTER}"

# changed: --expect from another prompt
pshow p-chg $FXA/bash-git.txt; touch /dev/null
replayk p-touch $FXA/bash-touch.txt; dl p-touch show; ET="$(jget '"\n".join(d["lines"])')"
dl p-chg press --expect "$ET" --option 1
check "changed (other command): rc 1 + message"       test $rc -eq 1 -a "$err" = "dialog: the dialog in p-chg changed"
check "changed (other command): nothing sent"         test "$(gotk p-chg)" = GOT:NONE

# changed between the two reads: the seam respawns the pane with another prompt
pshow p-swap $FXA/bash-git.txt
mkpanek p-swap2 $FXA/bash-touch.txt; mv $S/pane-p-swap2.zsh $S/pane2.zsh
export TC_DIALOG_BEFORE_SEND="$TT_BIN respawn-pane -k -t '=tt:p-swap' 'zsh $S/pane2.zsh'; sleep 0.5"
pr p-swap --option 1; unset TC_DIALOG_BEFORE_SEND
# mutation M1: remove the second read → a key reaches the new prompt
check "changed between reads: rc 1 + message"         test $rc -eq 1 -a "$err" = "dialog: the dialog in p-swap changed"
touch $S/stop-p-swap2; sleep 0.5
check "changed between reads: nothing sent"           test "$(tt capture-pane -p -J -t '=tt:p-swap' | grep -a -o 'GOT:[0-9a-fNOE]*' | tail -1)" = GOT:NONE

# one byte off: a trailing space on one line
pshow p-off $FXA/bash-git.txt; nl=$'\n'; dl p-off press --expect "${E/$nl/ $nl}" --option 1   # one trailing space on the first line
# mutation M2: compare trimmed text → this passes the compare and sends
check "one byte off: rc 1 + message"                  test $rc -eq 1 -a "$err" = "dialog: the dialog in p-off changed"
check "one byte off: nothing sent"                    test "$(gotk p-off)" = GOT:NONE

# copy mode: the seam puts the pane in copy mode after the first read
pshow p-copy $FXA/bash-git.txt
export TC_DIALOG_BEFORE_SEND="$TT_BIN copy-mode -t '=tt:p-copy'"
pr p-copy --option 1; unset TC_DIALOG_BEFORE_SEND
# mutation M3: remove the copy-mode checks → the digit is sent into copy mode
check "copy mode: rc 1 + message"                     test $rc -eq 1 -a "$err" = "dialog: p-copy is in copy mode"
tt send-keys -t '=tt:p-copy' -X cancel 2>/dev/null
check "copy mode: nothing sent"                       test "$(gotk p-copy)" = GOT:NONE

pshow p-none $FXA/no-prompt.txt; replayk p-none2 $FXA/no-prompt.txt
dl p-none2 press --expect "x" --option 1
check "no dialog: rc 1 + message"                     test $rc -eq 1 -a "$err" = "dialog: none in p-none2"
check "no dialog: nothing sent"                       test "$(gotk p-none2)" = GOT:NONE

# usage errors, rc 2, nothing sent
pshow p-u $FXA/bash-git.txt
pr p-u --option 9;               check "bad option: rc 2"                 test $rc -eq 2
pr p-u --option 1 --option 4;    check "two options, not multi: rc 2"     test $rc -eq 2
pr p-u --text x;                 check "text without Other: rc 2"         test $rc -eq 2
pr p-u;                          check "neither option nor text: rc 2"    test $rc -eq 2
pr p-u --option 1 --text x;      check "both option and text: rc 2"       test $rc -eq 2
dl p-u press --option 1;         check "no --expect: rc 2"                test $rc -eq 2
pr p-u --option x;               check "non-numeric option: rc 2"         test $rc -eq 2
check "usage errors: nothing sent"                    test "$(gotk p-u)" = GOT:NONE

# pane id
pshow p-id $FXA/bash-git.txt; pid="$(tt display -p -t '=tt:p-id' '#{pane_id}')"
dl $pid press --expect "$E" --option 1
check "pane id: rc 0, chose Yes"                      test $rc -eq 0 -a "$out" = "dialog: $pid: chose \"Yes\""
check "pane id: digit 1"                              test "$(gotk p-id)" = GOT:31

tt_done
