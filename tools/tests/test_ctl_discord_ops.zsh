source "${0:A:h}/lib.zsh"
# tmux-ctl discord --ops: the ops bot's state dir (_ops), ops-channels, status --ops and bridge start|stop --ops.
# Scratch tmux server from lib.zsh; HOME and TC_STATE are temp; node is a fake on PATH recording argv.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
export TC_TMUX="$TT_BIN"
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttdco.XXXXXX"):A}"
mkdir -p "$S/bin" "$S/home" "$S/cfg" "$S/bridge"
export HOME="$S/home" CLAUDE_CONFIG_DIR="$S/cfg" TC_DISCORD_BRIDGE_DIR="$S/bridge"
cat > "$S/bin/node" <<STUB
#!/bin/sh
echo "\$@" > "$S/node.args"
exec sleep 300
STUB
chmod +x "$S/bin/node"
export PATH="$S/bin:$PATH"
tt set-environment -g PATH "$PATH"
O="$TC_STATE/discord/_ops"
A="$O/access.json"; B="$O/bridge.json"
N=0
cleanup() { rm -rf "$S" }
trap 'cleanup; tt_teardown' EXIT INT TERM
run() { (( N++ )); "$@" > "$S/out.$N" 2>&1; rc=$?; out="$(<$S/out.$N)" }
mt() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" }

# --- token / allow / policy / pair land in _ops
run $C discord token --ops < <(print -r -- opstok.value)
check "token --ops: writes <_ops>/.env mode 600" test $rc -eq 0 -a "$(mode $O/.env)" = 600 -a "$(<$O/.env)" = "DISCORD_BOT_TOKEN=opstok.value"
check "token --ops: dir mode 700, no project dir created" test "$(mode $O)" = 700 -a ! -e "$TC_STATE/discord/tt"
run $C discord policy allowlist --ops
check "policy --ops: acts on _ops access.json" test $rc -eq 0 -a "$(jq -r .dmPolicy $A)" = allowlist
run $C discord pair abc --ops
check "pair --ops: reads the _ops access.json (no pending)" test $rc -eq 1 -a -n "$(grep -i 'no pending' $S/out.$N)"
run $C discord status --ops --project x
check "--ops with --project: usage error rc 2" test $rc -eq 2 -a -n "$(grep -i usage $S/out.$N)"
run $C discord status --ops --project=x
check "--ops with --project=: usage error rc 2" test $rc -eq 2
run $C discord status --ops
check "status --ops: no channel: line, command center none, approvals none" test $rc -eq 0 -a -z "$(grep '^channel:' $S/out.$N)" -a -n "$(grep -x 'command center: none' $S/out.$N)" -a -n "$(grep -x 'approvals: none' $S/out.$N)" -a -n "$(grep -x 'token: set' $S/out.$N)"

# --- ops-channels
run $C discord ops-channels 111 222 --ops
check "ops-channels: no allowlisted user exits 1" test $rc -eq 1 -a "$out" = "discord: pair or allow a user first" -a ! -e $B
run $C discord allow 11 --ops
run $C discord ops-channels abc 222
check "ops-channels: non-numeric exits 2 (usage)" test $rc -eq 2 -a -n "$(grep -i usage $S/out.$N)"
run $C discord ops-channels 111
check "ops-channels: one argument exits 2" test $rc -eq 2
run $C discord ops-channels 111 22x
check "ops-channels: second non-numeric exits 2" test $rc -eq 2
run $C discord ops-channels 111 222 333
check "ops-channels: three arguments exits 2" test $rc -eq 2
run $C discord ops-channels 111 222
check "ops-channels: exit 0 and message" test $rc -eq 0 -a "$out" = "ops-channels: 111 222"
check "ops-channels: bridge.json content" test "$(jq -cS . $B)" = '{"approvals":"222","command_center":"111","user":"11"}'
check "ops-channels: groups entries" test "$(jq -cS '[.groups["111"],.groups["222"]]' $A)" = '[{"allowFrom":["11"],"requireMention":false},{"allowFrom":["11"],"requireMention":false}]'
check "ops-channels: modes 600, no .next" test "$(mode $A)" = 600 -a "$(mode $B)" = 600 -a ! -e $A.next -a ! -e $B.next
m1="$(mt $A)"; m2="$(mt $B)"; sleep 1.2
run $C discord ops-channels 111 222
check "ops-channels unchanged: message, rc 0, mtimes same" test $rc -eq 0 -a "$out" = "ops-channels: 111 222 (unchanged)" -a "$(mt $A)" = "$m1" -a "$(mt $B)" = "$m2"
check "ops-channels: no project dir, project bridge.json untouched" test ! -e "$TC_STATE/discord/tt"
run $C discord status --ops
check "status --ops: command center and approvals ids" test -n "$(grep -x 'command center: 111' $S/out.$N)" -a -n "$(grep -x 'approvals: 222' $S/out.$N)" -a -z "$(grep '^channel:' $S/out.$N)"
check "status --ops: bridge line, deps missing" test -n "$(grep -x 'bridge: deps missing' $S/out.$N)"
tokarg="abcdefghij.abcdefghijabcdefghijabcdefghijabcdefghijabcdefghij"
run $C discord ops-channels 111 $tokarg
check "ops-channels: tokenish argument refused, rc 2, not echoed" test $rc -eq 2 -a -z "$(grep -F $tokarg $S/out.$N)"

# --- bridge start|stop --ops
rm -f $B
run $C discord bridge start --ops
check "start --ops: no channels refuses, rc 1" test $rc -eq 1 -a -n "$(grep -i 'command_center\|channel' $S/out.$N)"
run $C discord ops-channels 111 222
run $C discord bridge start --ops
check "start --ops: deps missing refuses" test $rc -eq 1 -a -n "$(grep -i node_modules $S/out.$N)"
mkdir -p $S/bridge/node_modules
jq '.approvals = ""' $B > $S/b.tmp && cp $S/b.tmp $B
run $C discord bridge start --ops
check "start --ops: empty approvals refuses, rc 1" test $rc -eq 1
run $C discord ops-channels 111 222
mv $O/.env $O/.env.off
run $C discord bridge start --ops
check "start --ops: token missing refuses" test $rc -eq 1 -a -n "$(grep -i token $S/out.$N)"
mv $O/.env.off $O/.env
check "refusals created no _ops-bg session" test -z "$(tt list-sessions -F '#{session_name}' | grep -x _ops-bg)"
run env -u TMUX -u TMUX_PANE AGENT_BOARD_TMUX_SOCKET="$TT_SOCK_NAME" $C discord bridge start --ops
check "start --ops: window discord-ops in _ops-bg" test $rc -eq 0 -a -n "$(tt list-windows -t '=_ops-bg:' -F '#{window_name}' | grep -x discord-ops)"
for i in {1..20}; do [[ -s $S/node.args ]] && break; sleep 0.2; done
check "start --ops: node ran bridge.js <_ops dir> --ops" test "$(<$S/node.args)" = "$TT_REPO/tools/discord-bridge/bridge.js $O --ops"
run $C discord bridge stop --ops
check "stop --ops: writes <_ops>/bridge.stopped 600" test $rc -eq 0 -a -f $O/bridge.stopped -a "$(mode $O/bridge.stopped)" = 600
tt kill-window -t '=_ops-bg:=discord-ops'
rm -f $S/node.args
run $C discord bridge start --keeper --ops
check "start --keeper --ops: honours bridge.stopped" test $rc -eq 0 -a "$out" = "bridge: stopped by user (bridge.stopped)" -a -z "$(tt list-windows -t '=_ops-bg:' -F '#{window_name}' | grep -x discord-ops)"
run env -u TMUX -u TMUX_PANE AGENT_BOARD_TMUX_SOCKET="$TT_SOCK_NAME" $C discord bridge start --ops
check "start --ops (a person): clears the marker and starts" test $rc -eq 0 -a ! -e $O/bridge.stopped -a -n "$(tt list-windows -t '=_ops-bg:' -F '#{window_name}' | grep -x discord-ops)"
run $C discord status --ops
check "status --ops: stopped bridge line" test -n "$(grep -x 'bridge: stopped' $S/out.$N)"

# --- merge-request (Task 5): fixture repo in a temp dir, scratch TC_STATE; the evidence and the feed event land there
R="$S/repo"; mkdir -p $R
G() { git -C $R -c user.name=t -c user.email=t@t "$@" }
G init -q -b main; print x > $R/a; G add -A; G commit -qm base; G checkout -qb feat; print y > $R/b; G add -A; G commit -qm work
MR=(discord merge-request --project tt --task 7 --spec spec-x --branch feat --tests "12 passed" --verdict Approved --repo $R)
run $C $MR --finding "one finding"
check "merge-request: posted, rc 0" test $rc -eq 0 -a "$out" = "merge-request: posted spec-x"
check "merge-request: evidence file in <_ops>/evidence, mode 600, sha = rev-parse" test "$(mode $O/evidence/tt-7.json)" = 600 -a "$(jq -r .sha $O/evidence/tt-7.json)" = "$(G rev-parse feat)"
check "merge-request: one merge_approval decision event in the project's feed" test "$(jq -rc '[.kind,.tier,.spec,.refs.task]' $TC_STATE/feed/tt.jsonl)" = '["merge_approval","decision","spec-x","7"]'
check "merge-request: the finding is in the post text" test -n "$(jq -r .text $TC_STATE/feed/tt.jsonl | grep -x 'one finding')"
mv $B $B.off
run $C $MR
check "merge-request without ops: project channel only note, rc 0" test $rc -eq 0 -a "$out" = "merge-request: posted spec-x (ops bot not set up: project channel only)"
mv $B.off $B
rm -f $TC_STATE/feed/tt.jsonl; rm -rf $O/evidence
run $C discord merge-request --project tt --task 7 --spec s --branch '-x' --tests t --verdict v --repo $R
check "merge-request: a branch starting with - exits 2, nothing written" test $rc -eq 2 -a ! -e $TC_STATE/feed/tt.jsonl -a ! -e $O/evidence
run $C discord merge-request --project tt --task 7 --spec s --branch "feat;touch $S/PWNED" --tests t --verdict v --repo $R
check "merge-request: a shell-looking branch exits 2 and runs nothing" test $rc -eq 2 -a ! -e $S/PWNED
run $C discord merge-request --project tt --task 7
check "merge-request: missing options exit 2" test $rc -eq 2
check "leak: merge-request wrote no real feed or evidence" test ! -e "$S/home/.local/state/agent-board/feed"

# --- usage / leaks
h="$($C help)"
check "help: lists --ops and ops-channels" test -n "$(print -r -- "$h" | grep 'ops-channels')" -a -n "$(print -r -- "$h" | grep -e '--ops')"
check "help: lists merge-request" test -n "$(print -r -- "$h" | grep 'discord merge-request')"
check "help: last line intact (the metrics <sub> line)" test -n "$(print -r -- "$h" | tail -1 | grep 'metrics <sub>')"
check "leak: no discord-ops window in the main session" test -z "$(tt list-windows -t '=tt:' -F '#{window_name}' | grep -x discord-ops)"
tt_done
