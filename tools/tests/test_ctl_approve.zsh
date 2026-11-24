source "${0:A:h}/approve_common.zsh"
# tmux-ctl approve: once/deny, refusals, --expect mismatch, swapped prompts (part 1; siblings test_ctl_approve_spoof, _expect, _misc).
# --- once: Bash prompts (1 Yes / 2 ... don’t ask / 3 switch / 4 No)
for f in bash-touch bash-git; do
  replay w-$f $FX/$f.txt; ap w-$f once
  # mutation: pick the first "Yes…" row instead of exactly Yes → still 1 here; see the variant tests below
  check "once $f: message"        test "$out" = "approve: w-$f: chose \"Yes\""
  check "once $f: exit 0"         test $rc -eq 0
  check "once $f: key 1 arrived"  test "$(got w-$f)" = 1
done
replay w-write $FX/write.txt; ap w-write once
check "once write: key 1"         test "$(got w-write)" = 1
# --- deny
replay d-git $FX/bash-git.txt; ap d-git deny
check "deny bash-git: chose No"   test "$out" = "approve: d-git: chose \"No\""
check "deny bash-git: key 4"      test "$(got d-git)" = 4
replay d-write $FX/write.txt; ap d-write deny
check "deny write: key 3"         test "$(got d-write)" = 3
# --- refusals: no key sent
for f in no-prompt after-yes; do
  replay n-$f $FX/$f.txt; ap n-$f once
  # mutation: drop the no-prompt check → exit-1 test fails
  check "$f: exit 1 + message"    test $rc -eq 1 -a "$out" = "approve: no permission prompt in n-$f"
  check "$f: no key sent"         test "$(got n-$f)" = NONE
done
# --expect
replay e-ok $FX/bash-git.txt; ap e-ok once --expect "git config user.name probe-user"
check "expect match: chose"       test $rc -eq 0 -a "$(got e-ok)" = 1
replay e-bad $FX/bash-git.txt; ap e-bad once --expect "rm -rf /"
# mutation: drop the --expect check → changed-prompt test sends a key
check "expect mismatch: exit 1 + message"  test $rc -eq 1 -a "$out" = "approve: the prompt in e-bad changed"
check "expect mismatch: no key"   test "$(got e-bad)" = NONE
# swap_case <win> <shown fixture> <replacement fixture>: the prompt is replaced between approve's capture and its send
# (seam TC_APPROVE_BEFORE_SEND runs after the first capture); approve must refuse and no key may arrive
swap_case() {
  replay $1 $2
  cat > $S/swap-$1.zsh <<SW
rm -f $S/ready-$1 $S/stop-$1
$TT_BIN respawn-pane -k -t '=tt:$1' "zsh $S/pane2-$1.zsh"
n=300; while [[ ! -e $S/ready-$1 ]] && (( n-- > 0 )); do sleep 0.05; done
SW
  cp $S/pane-$1.zsh $S/pane-$1.first; mkpane $1 $3; mv $S/pane-$1.zsh $S/pane2-$1.zsh; cp $S/pane-$1.first $S/pane-$1.zsh
  export TC_APPROVE_BEFORE_SEND="zsh $S/swap-$1.zsh"
  ap $1 once "${@:4}"; unset TC_APPROVE_BEFORE_SEND
}
swap_case c-swap $FX/bash-git.txt $FX/write.txt
# mutation: skip the re-capture compare → a key is sent to the new prompt
check "swap between capture and send: exit 1 + message"  test $rc -eq 1 -a "$out" = "approve: the prompt in c-swap changed"
check "swap: no key sent"         test "$(got c-swap)" = NONE
for loc in default C; do
  [[ $loc == C ]] && APENV=(LC_ALL=C) || APENV=()
  swap_case c-cmd-$loc $S/hi.txt $S/hi-swapped.txt
  # mutation: capture only the last 40 rows / build the block from the question line / match the divider with a locale-dependent regex → the command is not compared and a key is sent
  check "swapped command, dialog at the top ($loc locale): exit 1 + message"  test $rc -eq 1 -a "$out" = "approve: the prompt in c-cmd-$loc changed"
  check "swapped command ($loc locale): no key sent"  test "$(got c-cmd-$loc)" = NONE
done
APENV=()
# auto-mode countdown row (real capture, fixtures/approve/README.md): its M:SS ticks every second, so a tick between the two reads must not fail the press
CD=$FX/bash-auto-countdown.txt; CDX='│ GT=/tmp/agent-board-gate; touch $GT/x.gate; rm -f $GT/*.gate$(printf '"''"') && echo gate-tap-3-ran'
sed 's/in 1:47,/in 1:46,/' $CD > $S/cd-tick.txt
sed 's/gate-tap-3-ran/gate-tap-3-evil/' $S/cd-tick.txt > $S/cd-tick-cmd.txt
swap_case c-tick $CD $S/cd-tick.txt --expect "$CDX"
# (RED run before the fix: this case failed; no other mutation was run)
check "countdown tick between the reads: chose Yes, key 1"  test $rc -eq 0 -a "$(got c-tick)" = 1
swap_case c-tickcmd $CD $S/cd-tick-cmd.txt --expect "$CDX"
check "tick plus a changed command: exit 1 + message"  test $rc -eq 1 -a "$out" = "approve: the prompt in c-tickcmd changed"
check "tick plus a changed command: no key sent"  test "$(got c-tickcmd)" = NONE
# the phrase inside the command text (a P: line), digits changed between the reads: not the warning row, so it must not be masked
sed 's/gate-tap-3-ran/gate-tap-3-ran # block this request in 1:23/' $CD > $S/cd-quote-a.txt
sed 's/in 1:23/in 9:59/' $S/cd-quote-a.txt > $S/cd-quote-b.txt
swap_case c-quote $S/cd-quote-a.txt $S/cd-quote-b.txt --expect "${CDX} # block this request in 1:23"
check "digits changed inside the command text: exit 1 + message"  test $rc -eq 1 -a "$out" = "approve: the prompt in c-quote changed"
qgot="$(got c-quote)"
check "digits changed inside the command text: no key sent"  test "$qgot" = NONE
[[ "$qgot" == NONE ]] || { print -r -- "# c-quote: pane got '$qgot'; approve said '$out'"; tt capture-pane -p -J -t "=tt:c-quote" | tail -8 | sed 's/^/# pane: /' }
tt_done
