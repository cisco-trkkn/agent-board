# tmux-ctl discord send|snap: file attachments out. Scratch tmux server, HOME and TC_STATE are temp; Chrome is a fake (TC_CHROME).
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
export TC_TMUX="$TT_BIN"
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttds.XXXXXX"):A}"
mkdir -p "$S/bin" "$S/home/.local/state/tmux-dash" "$S/work/sub"
export HOME="$S/home" CLAUDE_CONFIG_DIR="$S/cfg"
cleanup() { chmod -R u+rw "$S" 2>/dev/null; rm -rf "$S" }
trap 'cleanup; tt_teardown' EXIT INT TERM
unset TC_CHROME FEEDKEY TMUX_DASH_PORT
D="$TC_STATE/discord/tt"; BOX="$D/outbox"
SECRET=SECRETTOKEN123
print -rn -- "$SECRET" > "$HOME/.local/state/tmux-dash/token"
N=0
run() { (( N++ )); "$@" > "$S/out.$N" 2>&1; rc=$?; out="$(<$S/out.$N)" }
clr() { [[ -d $BOX ]] && find $BOX -name "*.json" -delete }
ops() { local -a f; f=( $BOX/*.json(N) ); print -r -- ${#f} }
op1() { jq -c . $BOX/*.json(N[1]) }
cd "$S/work"
print a > a.txt; print b > sub/b.log
LONG="$S/work/sub/$(printf 'x%.0s' {1..60}).tar.gz"; print z > "$LONG"

# --- send
run $C discord send a.txt sub/b.log -m "here" --project tt
check "send: exit 0, stdout"            test $rc -eq 0 -a "$out" = "send: 1 post, 2 files"
check "send: one op"                    test "$(ops)" = 1
check "send: files absolute"            test "$(op1 | jq -c .files)" = "[\"$S/work/a.txt\",\"$S/work/sub/b.log\"]"
check "send: text/tier/mention"         test "$(op1 | jq -c '[.text,.tier,.mention_user,.op]')" = '["here","progress",false,"post"]'
check "send: no thread_key, no delete"  test "$(op1 | jq -c '[has("thread_key"),has("delete_files")]')" = '[false,false]'
clr
run $C discord send a.txt sub/b.log --project tt
check "send: default text = basenames"  test "$(op1 | jq -r .text)" = "a.txt, b.log"
clr
run $C discord send --thread k1 a.txt --project tt
check "send: --thread"                  test "$(op1 | jq -r .thread_key)" = k1
clr
run $C discord send "$LONG" --project tt
check "send: long dotted path accepted" test $rc -eq 0 -a "$(ops)" = 1
clr
run $C discord send nope.txt --project tt
check "send: missing"                   test $rc -eq 1 -a "$out" = "send: $S/work/nope.txt: not found" -a "$(ops)" = 0
run $C discord send sub --project tt
check "send: directory"                 test $rc -eq 1 -a "$out" = "send: $S/work/sub: not a file" -a "$(ops)" = 0
print c > secret.txt; chmod 000 secret.txt
run $C discord send a.txt secret.txt --project tt
check "send: unreadable (chmod 000), no op" test $rc -eq 1 -a "$out" = "send: $S/work/secret.txt: not readable" -a "$(ops)" = 0
run $C discord send --project tt
check "send: no files -> usage exit 2"  test $rc -eq 2 -a -n "$(grep -i usage $S/out.$N)"
files=(); for i in {1..11}; do print x > f$i; files+=(f$i); done
run $C discord send $files --project tt
check "send: 11 files exit 2"           test $rc -eq 2 -a "$out" = "send: at most 10 files" -a "$(ops)" = 0
run env -u TMUX -u TMUX_PANE $C discord send a.txt
check "send: no project exit 2"         test $rc -eq 2

# --- snap (fake chrome)
cat > $S/bin/chrome <<STUB
#!/bin/sh
printf '%s\n' "\$@" > "$S/chrome.argv"
for a in "\$@"; do case "\$a" in --screenshot=*) p="\${a#--screenshot=}";; esac; done
[ -f "$S/chrome.nopng" ] || printf '\211PNG\r\n\032\n' > "\$p"
echo "fake chrome saw \$*"; echo "fake chrome saw \$*" >&2
STUB
chmod +x $S/bin/chrome
export TC_CHROME=$S/bin/chrome
clr
run $C discord snap tt
argv="$(<$S/chrome.argv)"
check "snap: exit 0"                    test $rc -eq 0
check "snap: argv flags"                test -n "$(print -r -- $argv | grep -x -e --headless=new)" -a -n "$(print -r -- $argv | grep -x -e --virtual-time-budget=5000)" -a -n "$(print -r -- $argv | grep -x -e --window-size=1200,1600)"
check "snap: argv screenshot in tmp/"   test -n "$(print -r -- $argv | grep -E "^--screenshot=$D/tmp/snap-.*\.png$")"
check "snap: argv url"                  test -n "$(print -r -- $argv | grep -x "http://127.0.0.1:7700/$SECRET/")"
check "snap: one op, delete_files"      test "$(ops)" = 1 -a "$(op1 | jq -c '.delete_files')" = true
check "snap: files = the png"           test "$(op1 | jq -r '.files[0]')" = "$(print -r -- $argv | grep -E '^--screenshot=' | sed 's/^--screenshot=//')" -a "$(op1 | jq '.files|length')" = 1
check "snap: text"                      test -n "$(op1 | jq -r .text | grep -E '^board snapshot [0-9]{2}:[0-9]{2}$')"
sf=( $(find $D -type f) )
hits=$(grep -c -- $SECRET $sf < /dev/null | awk -F: '{n+=$NF} END{print n+0}'); print "state files scanned: ${#sf}, token hits: $hits"
check "snap: state files scanned > 0"   test ${#sf} -gt 0
check "snap: token hits in state = 0"   test "$hits" = 0
hits=$(grep -c -- $SECRET $S/out.$N); print "output token hits: $hits"
check "snap: token hits in output = 0"  test "$hits" = 0
TC_CHROME=$S/bin/nochrome run $C discord snap tt
check "snap: no chrome"                 test $rc -eq 1 -a "$out" = "snap: Chrome not found"
clr; touch $S/chrome.nopng
run $C discord snap tt
check "snap: no screenshot"             test $rc -eq 1 -a "$out" = "snap: no screenshot" -a "$(ops)" = 0
rm -f $S/chrome.nopng; clr
cat > $S/bin/slowchrome <<STUB
#!/bin/sh
for a in "\$@"; do case "\$a" in --screenshot=*) p="\${a#--screenshot=}";; esac; done
printf '\211PNG' > "\$p"
sleep 30
STUB
chmod +x $S/bin/slowchrome
before="$(ls $D/tmp)"; t0=$SECONDS
TC_CHROME=$S/bin/slowchrome TC_SNAP_TIMEOUT=1 run $C discord snap tt
check "snap: chrome timeout"            test $rc -eq 1 -a "$out" = "snap: Chrome timed out" -a "$(ops)" = 0 -a $(( SECONDS - t0 )) -lt 15
check "snap: timeout leaves no png"     test "$(ls $D/tmp)" = "$before"

# --- usage + header
run $C discord bogus --project tt
check "usage lists send"                test -n "$(grep -F 'send [--thread <key>] <file>… [-m <text>]' $S/out.$N)"
check "usage lists snap"                test -n "$(grep -F 'snap [<project>]' $S/out.$N)"
check "header lists send and snap"      test -n "$(grep -F 'send [--thread <key>] <file>… [-m <text>]' $C)" -a -n "$(grep -F 'snap [<project>]' $C)"
tt_done
