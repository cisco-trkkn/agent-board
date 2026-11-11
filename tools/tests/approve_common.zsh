# approve_common.zsh — shared setup of the test_ctl_approve*.zsh files: a scratch server, the replay/got/ap helpers and the fixture variants.
source "${0:A:h}/lib.zsh"
# tmux-ctl approve <win> once|deny [--expect <text>]: presses the one-time Yes / the No of a permission prompt.
# Each case replays a real captured prompt (tools/tests/fixtures/approve/*.txt) in a window of the scratch server:
# `cat fixture; read -t 3 -k1 k; print GOT:$k` shows which key arrived (GOT:NONE = nothing was sent).
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
FX="${0:A:h}/fixtures/approve"
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttap.XXXXXX"):A}"
trap 'rm -rf "$S"; tt_teardown' EXIT INT TERM
# The window reads one key in a loop of short timeouts until $S/stop-<win> exists, then prints GOT:<key>|NONE. The key
# is sent (synchronously) before approve returns, so `got` touches the stop file after it: a key that was going to
# arrive is already in the tty, and NONE needs only one more 0.05 s read instead of a fixed 3 s timeout.
# readloop <win> <ready-file-suffix>: the zsh snippet shared by replay and the swap seam
readloop() { print -r -- "touch $S/ready-$1; until [[ -e $S/stop-$1 ]]; do read -t 0.05 -k1 k && break; done; print -r -- \"GOT:\${k:-NONE}\"; sleep 600" }
# replay <win> <file>: a window showing the fixture, then waiting for one key; returns once it is waiting
replay() { rm -f $S/ready-$1 $S/stop-$1; tt new-window -d -t '=tt:' -n "$1" -c "$TT_DIR" "zsh -c 'cat $2; $(readloop $1)'"; fwait $S/ready-$1; sleep 0.05 }
# fwait <file>: poll every 0.05 s (tt_wait polls every 0.25 s) up to 10 s for the file
fwait() { local n=200; until [[ -e $1 ]] || (( n-- <= 0 )); do sleep 0.05; done }
got() { touch $S/stop-$1; local n=40 g; while (( n-- > 0 )); do g="$(tt capture-pane -p -J -t "=tt:$1" | grep -a -o 'GOT:[^ ]*' | tail -1)"; [[ -n "$g" ]] && { print -r -- "${g#GOT:}"; return }; sleep 0.1; done; print -r -- TIMEOUT }
APENV=()   # extra env for the approve call, e.g. LC_ALL=C
# --expect is mandatory: ap adds the window's own command/path text unless the call names --expect itself (NOEXP=1: never)
defexp() { case "$1" in *touch*|hi-*|c-cmd-*|s-yes|wk|c-copy) print -r -- "touch made-by-test" ;; *git*|c-swap|s-no|v-no-plain-yes|e-*|spoof-*) print -r -- "git config user.name probe-user" ;; *) print -r -- "notes.txt" ;; esac }
ap() {
  local -a ex=()
  [[ " $* " != *" --expect "* && -z "$NOEXP" && $# -ge 2 && "$2" == (once|deny) ]] && ex=(--expect "$(defexp $1)")
  out="$(env "${APENV[@]}" $C approve "$@" "${ex[@]}" 2>&1)"; rc=$?
}

# --- variants built from real fixtures with sed (not hand-written prompts)
sed 's/ 1\. Yes$/ 1. Sure/' $FX/bash-git.txt > $S/no-plain-yes.txt                                  # bash-git.txt with the plain "1. Yes" row relabelled "1. Sure"
sed 's/ 1\. Yes$/ 1. Yes, and switch to accept edits/' $FX/write.txt > $S/only-yes-and.txt     # write.txt whose plain Yes row is a "Yes, and ..." row
sed '/ 3\. No$/d' $FX/write.txt > $S/no-no.txt                                                 # write.txt with the No row deleted

# same question and options, only the command differs; dialog drawn at the top of the 50-row pane (bash-touch.txt minus its first 9 rows)
{ sed -n '10,$p' $FX/bash-touch.txt; repeat 9 print; } > $S/hi.txt
sed 's/made-by-test/evil-test/g' $S/hi.txt > $S/hi-swapped.txt
