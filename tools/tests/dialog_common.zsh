# dialog_common.zsh — shared setup of the test_ctl_dialog*.zsh files: a scratch server, the replay/got/dl helpers and the JSON compare.
source "${0:A:h}/lib.zsh"
# tmux-ctl dialog <win> show: the JSON of the Claude Code dialog showing in a window or pane; read-only.
# Each case replays a real captured screen (fixtures/dialogs/*.txt, fixtures/approve/*.txt) in a window of the scratch server:
# `cat fixture; read -k1 k; print GOT:$k` shows which key arrived (GOT:NONE = nothing was sent).
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
FXD="${0:A:h}/fixtures/dialogs"
FXA="${0:A:h}/fixtures/approve"
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttdl.XXXXXX"):A}"
trap 'rm -rf "$S"; tt_teardown' EXIT INT TERM
# mkpane <win> <fixture>: writes $S/pane-<win>.zsh (cat the fixture, signal ready, read one key in a loop of short timeouts
# until $S/stop-<win> exists, print GOT:<key>|NONE). The read after the loop drains a key that was sent just as the stop
# file appeared, so a "no key" check cannot pass on a missed key.
mkpane() {
  rm -f $S/ready-$1 $S/stop-$1
  print -rl -- "cat ${(q)2}" "touch $S/ready-$1" 'until [[ -e '$S/stop-$1' ]]; do read -t 0.05 -k1 k && break; done' \
    '[[ -n $k ]] || read -t 0.05 -k1 k' 'print -r -- "GOT:${k:-NONE}"' 'sleep 600' > $S/pane-$1.zsh
}
# replay <win> <file>: a window showing the fixture, then waiting for one key; returns once it is waiting
replay() { mkpane $1 $2; tt new-window -d -t '=tt:' -n "$1" -c "$TT_DIR" "zsh $S/pane-$1.zsh"; fwait $S/ready-$1; sleep 0.05 }
# fwait <file>: poll every 0.05 s up to 10 s for the file
fwait() { local n=200; until [[ -e $1 ]] || (( n-- <= 0 )); do sleep 0.05; done }
got() { touch $S/stop-$1; local n=50 g; while (( n-- > 0 )); do g="$(tt capture-pane -p -J -t "=tt:$1" | grep -a -o 'GOT:[^ ]*' | tail -1)"; [[ -n "$g" ]] && { print -r -- "${g#GOT:}"; return }; sleep 0.1; done; print -r -- TIMEOUT }
# snap <win>: the pane text and the cursor position (what a read-only command must leave as it was)
snap() { tt capture-pane -p -J -t "=tt:$1"; tt display -p -t "=tt:$1" '#{cursor_x},#{cursor_y}'; }
DLENV=()   # extra env for the dialog call, e.g. LC_ALL=C
# dl <win|pane> <args…>: runs tmux-ctl dialog; sets out (stdout), err (stderr), rc
dl() { out="$(env "${DLENV[@]}" $C dialog "$@" 2>$S/err)"; rc=$?; err="$(<$S/err)" }
# jget <python expression over d>: a value of the JSON in $out (prints nothing and returns 1 when $out is not JSON)
jget() { print -r -- "$out" | python3 -I -c 'import json, sys
try: d = json.load(sys.stdin)
except ValueError: sys.exit(1)
print(eval(sys.argv[1]))' "$1" }
# same_as <expect.json>: $out equals the oracle on kind, question, options, multi, other (parsed JSON), has exactly those
# keys plus `lines`, and `lines` is a non-empty list of strings. Prints the differences on stderr.
same_as() { print -r -- "$out" | python3 -I -c 'import json, sys
exp = json.load(open(sys.argv[1], encoding="utf-8"))
try: got = json.load(sys.stdin)
except ValueError as x: print("  not JSON:", x, file=sys.stderr); sys.exit(1)
keys = ["kind", "question", "options", "multi", "other"]
bad = [k for k in keys if got.get(k) != exp[k]]
if set(got) != set(keys) | {"lines"}: bad.append("keys")
ls = got.get("lines")
if not (isinstance(ls, list) and ls and all(isinstance(x, str) and x == x.rstrip() and x for x in ls)): bad.append("lines")
for k in bad: print("  differs:", k, "got", json.dumps(got.get(k), ensure_ascii=False), "want", json.dumps(exp.get(k), ensure_ascii=False), file=sys.stderr)
sys.exit(1 if bad else 0)' "$1" }
