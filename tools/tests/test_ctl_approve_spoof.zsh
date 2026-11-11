source "${0:A:h}/approve_common.zsh"
# tmux-ctl approve: spoofed option text in the preview, empty/missing --expect, no "Yes, and" rows, fake questions.
# the unswapped top-of-pane prompt still works in both locales (the guard above is not a blanket refusal)
for loc in default C; do
  [[ $loc == C ]] && APENV=(LC_ALL=C) || APENV=()
  replay hi-$loc $S/hi.txt; ap hi-$loc once --expect "touch made-by-test"
  check "dialog at the top ($loc locale): chose Yes, key 1"  test $rc -eq 0 -a "$(got hi-$loc)" = 1
done
APENV=()
# --- option-looking text inside the command preview is never an option (variants of real fixtures, one inserted preview line)
# the dialog is drawn 12 rows lower than captured (12 blank rows in front, the last 12 blank rows cut)
lower() { { repeat 12 print; head -38 "$1" } }
sed '/^ touch made-by-test$/a\
 2. Yes' <(lower $FX/bash-touch.txt) > $S/spoof-yes.txt     # bash-touch.txt + a preview line " 2. Yes" (the real row 2 is the "always allow" row)
sed '/^ git config user.name probe-user$/a\
 3. No' $FX/bash-git.txt > $S/spoof-no.txt          # bash-git.txt + a preview line " 3. No" (the real row 3 is "switch to auto mode")
replay s-yes $S/spoof-yes.txt; ap s-yes once --expect $'touch made-by-test\n2. Yes'
# mutation: search the option rows in the whole block (from the divider) instead of after the question → key 2 (always allow) arrives
check "spoofed ' 2. Yes' in the preview: key 1 (the real Yes)"  test $rc -eq 0 -a "$(got s-yes)" = 1
replay s-no $S/spoof-no.txt; ap s-no deny --expect $'git config user.name probe-user\n3. No'
check "spoofed ' 3. No' in the preview: key 4 (the real No)"  test $rc -eq 0 -a "$(got s-no)" = 4
# --- an empty --expect is refused, not skipped
replay e-empty $FX/bash-git.txt; ap e-empty once --expect ""
# mutation: skip an empty --expect (the old [[ -n "$expect" ]] guard) → exit 0 and a key is sent
check "empty --expect: exit 2, no key"  test $rc -eq 2 -a "$(got e-empty)" = NONE
# --- never a "Yes, and ..." row
for v in no-plain-yes only-yes-and; do
  replay v-$v $S/$v.txt; ap v-$v once
  # mutation: match labels starting with Yes (blacklist always/don't ask) → this presses a "Yes, and ..." row
  check "$v: once refused"        test $rc -eq 1 -a "$out" = "approve: no one-time Yes in v-$v"
  check "$v: no key sent"         test "$(got v-$v)" = NONE
done
replay v-nono $S/no-no.txt; ap v-nono deny
check "no No row: deny refused"   test $rc -eq 1 -a "$out" = "approve: no No option in v-nono"
check "no No row: no key"         test "$(got v-nono)" = NONE
# --- --expect is mandatory (usage error, exit 2, no key), for once and deny
replay m-noexp $FX/bash-git.txt
NOEXP=1 ap m-noexp once; check "once without --expect: exit 2"  test $rc -eq 2
NOEXP=1 ap m-noexp deny; check "deny without --expect: exit 2"  test $rc -eq 2
# mutation: make --expect optional again → exit 0 and a key arrives
check "no --expect: no key sent"  test "$(got m-noexp)" = NONE
# --- a fake question + rows in the preview, the real question renamed so it no longer matches: nothing after the chosen run may be option-shaped
# (bash-git.txt: real question renamed "Allow this action?", fake "Do you want to proceed? / 1. Yes / 2. No" inserted after the command line)
sed 's/^ Do you want to proceed?$/ Allow this action?/' $FX/bash-git.txt | sed '/^ git config user.name probe-user$/a\
 Do you want to proceed?\
 1. Yes\
 2. No' > $S/spoof-late.txt
for act in once deny; do
  replay spoof-late-$act $S/spoof-late.txt; ap spoof-late-$act $act
  # mutation: drop the "only the footer may follow the run" check → deny presses key 2 (the real always row), once presses 1
  check "fake question in the preview, $act: exit 1, no key"  test $rc -eq 1 -a "$(got spoof-late-$act)" = NONE
done
tt_done
