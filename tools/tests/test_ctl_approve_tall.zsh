source "${0:A:h}/approve_common.zsh"
# approve on a prompt taller than the pane (an `↑ N more lines` row): the top of the command is off screen, so no row of it may
# become a P: line and approve refuses, whatever rule rows show. A new file: the existing approve tests are unchanged.
# mutation: drop the `U:tall` check in _dlg_approve_view (the `!tall` condition and the tag) → the VARIANT passes the --expect.
TALL=$FX/lead-tasklist-more-lines.txt
rule="$(grep -a -m1 '^╌' $FX/bash-git.txt)"
# VARIANT (c-rev4's synthetic screen): the real tall capture with two column-1 ╌ rules inserted in its preview rows
awk -v r="$rule" 'NR==3 || NR==5 { print r } { print }' $TALL > $S/tall-rules.txt

replay t-real $TALL
ap t-real show
check "real tall fixture, show: exit 1, no expect lines"   test $rc -eq 1 -a "$out" = "approve: no expect lines in t-real"
ap t-real once --expect "│ touch made-12.txt"
check "real tall fixture, once: exit 1, no expect lines"   test $rc -eq 1 -a "$out" = "approve: no expect lines in t-real"
check "real tall fixture: no key sent"                      test "$(got t-real)" = NONE

replay t-var $S/tall-rules.txt
ap t-var show
check "VARIANT two ╌ rules + more-lines row, show: refused"  test $rc -eq 1 -a "$out" = "approve: no expect lines in t-var"
ap t-var once --expect "│ touch made-12.txt"
check "VARIANT two ╌ rules + more-lines row, once: refused"  test $rc -eq 1 -a "$out" = "approve: no expect lines in t-var"
check "VARIANT: no key sent"                                 test "$(got t-var)" = NONE
tt_done
