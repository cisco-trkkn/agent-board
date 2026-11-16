source "${0:A:h}/lib.zsh"
# tmux-ctl discord token|pair|deny|policy|allow|remove|forget|status: per-project bot token and access.json.
# Scratch tmux server from lib.zsh; HOME, CLAUDE_CONFIG_DIR and TC_STATE are temp; launchctl is a fake on PATH.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
export TC_TMUX="$TT_BIN"
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttdc.XXXXXX"):A}"
mkdir -p "$S/bin" "$S/home" "$S/cfg"
export HOME="$S/home" CLAUDE_CONFIG_DIR="$S/cfg"
cat > "$S/bin/launchctl" <<STUB
#!/bin/sh
[ -f "$S/watch.loaded" ]
STUB
chmod +x "$S/bin/launchctl"
export PATH="$S/bin:$PATH"
TOK='MTIzNDU2Nzg5MDEyMzQ1Njc4.GabcDE.dummydummydummydummydummydummydummy00'
SECRET="${TOK%%.*}"
D="$TC_STATE/discord"
N=0
cleanup() { rm -rf "$S" }
trap 'cleanup; tt_teardown' EXIT INT TERM
run() { local in="$1"; shift; (( N++ )); print -r -- "$in" | "$@" > "$S/out.$N" 2>&1; rc=$?; out="$(<$S/out.$N)" }
A="$D/tt/access.json"
now_ms() { python3 -c 'import time;print(int(time.time()*1000))' }

# --- token
run "$TOK" $C discord token
check "token: message"                    test "$out" = "discord: token saved for tt (restart its lead: agent-board lead --continue, or Restart orchestrator on the board)"
check "token: exit 0"                     test $rc -eq 0
check "token: .env content"               test "$(<$D/tt/.env)" = "DISCORD_BOT_TOKEN=$TOK"
check "token: .env mode 600"              test "$(mode $D/tt/.env)" = 600
check "token: dir mode 700"               test "$(mode $D/tt)" = 700
check "token: no .env.next left"          test ! -e "$D/tt/.env.next"
check "token: default access.json created" test "$(jq -cS . $A)" = '{"allowFrom":[],"dmPolicy":"pairing","groups":{},"pending":{},"ackReaction":"👀"}' -o "$(jq -cS 'del(.ackReaction)' $A)" = '{"allowFrom":[],"dmPolicy":"pairing","groups":{},"pending":{}}'
check "token: ackReaction set when absent" test "$(jq -r .ackReaction $A)" = "👀"
check "token: access.json mode 600"       test "$(mode $A)" = 600
jq '.ackReaction = ""' $A > $A.x && mv $A.x $A
run "$TOK" $C discord token
check "token: existing empty ackReaction kept" test "$(jq -c .ackReaction $A)" = '""'
tt new-session -d -s tt2 -t tt -c "$TT_DIR"
(( N++ )); print -r -- "$TOK" | TC_SESSION=tt2 $C discord token > "$S/out.$N" 2>&1
check "grouped: key is the group, not tt2"  test ! -e "$D/tt2" -a -f "$D/tt/.env"
tt kill-session -t '=tt2' 2>/dev/null

# --- refusals
rm -rf "$D"
run "$TOK" $C discord token tt "$TOK"
check "argv token: exit 2, nothing written, not echoed"  test $rc -eq 2 -a ! -e "$D/tt/.env" -a "$(grep -c -- "$SECRET" $S/out.$N)" = 0
run "$TOK" $C discord token "$TOK"
check "argv token as first arg: exit 2, nothing written"  test $rc -eq 2 -a ! -e "$D"
for form in "--project $TOK" "--project=$TOK"; do
  run "$TOK" $C discord token ${=form}
  check "--project <token> (${form%%[ =]*}): exit 2, nothing created, not echoed"  test $rc -eq 2 -a ! -e "$D" -a "$(grep -c -- "$SECRET" $S/out.$N)" = 0
done
run "$TOK" $C discord token --project 'a:b'
check "project name outside the charset: exit 2" test $rc -eq 2 -a ! -e "$D" -a -n "$(grep -i 'letters, digits' $S/out.$N)"
run "$TOK" $C discord token --project 'bad name'
check "project name with a space: exit 2" test $rc -eq 2 -a ! -e "$D"
run "nope" $C discord token
check "short word is not a token shape: still accepted as one line" test $rc -eq 0
rm -rf "$D"
run "has space here" $C discord token
check "bad shape (spaces): message"       test "$out" = "discord: that does not look like a bot token"
check "bad shape: exit 2, no .env"        test $rc -eq 2 -a ! -e "$D/tt/.env"
run "" $C discord token
check "empty token: exit 2"               test $rc -eq 2
run "$TOK" env -u TMUX -u TMUX_PANE $C discord token
check "outside tmux, no --project: exit 2 + usage"  test $rc -eq 2 -a -n "$(grep -i usage $S/out.$N)"
run "$TOK" env -u TMUX -u TMUX_PANE $C discord token --project p1
check "outside tmux, --project p1: saved"  test $rc -eq 0 -a "$(<$D/p1/.env)" = "DISCORD_BOT_TOKEN=$TOK"

# --- access writes (seeded with an extra key that must survive)
rm -rf "$D"; mkdir -p "$D/tt"
seed() { print -r -- "{\"dmPolicy\":\"pairing\",\"allowFrom\":[\"1\"],\"groups\":{\"g\":{\"x\":1}},\"pending\":{\"abc123\":{\"senderId\":\"42\",\"chatId\":\"900\",\"createdAt\":1,\"expiresAt\":$(( $(now_ms) + 3600000 )),\"replies\":1},\"old000\":{\"senderId\":\"43\",\"chatId\":\"901\",\"createdAt\":1,\"expiresAt\":5,\"replies\":1}}}" > $A; chmod 600 $A }
keeps() { test "$(jq -c .groups $A)" = '{"g":{"x":1}}' }
seed
run "" $C discord pair abc123
check "pair: exit 0"                      test $rc -eq 0
check "pair: sender allowlisted"          test "$(jq -c .allowFrom $A)" = '["1","42"]'
check "pair: pending code deleted"        test "$(jq 'has("pending") and (.pending|has("abc123"))' $A)" = false
check "pair: approved/<senderId> holds chatId" test "$(<$D/tt/approved/42)" = 900
check "pair: other keys kept"             keeps
check "pair: access.json mode 600, no .next" test "$(mode $A)" = 600 -a ! -e $A.next
check "pair: 2-space indent"              test -n "$(grep -E '^  "dmPolicy"' $A)"
run "" $C discord pair abc123
check "pair: second time (gone) exits 1"  test $rc -eq 1
run "" $C discord pair old000
check "pair: expired code exits 1"        test $rc -eq 1
check "pair: expired: nobody added, no approved file" test "$(jq -c .allowFrom $A)" = '["1","42"]' -a ! -e $D/tt/approved/43
run "" $C discord pair nope99
check "pair: unknown code exits 1"        test $rc -eq 1
seed; run "" $C discord pair abc123; run "" $C discord pair abc123
check "pair: dedupe allowFrom"            test "$(jq -c .allowFrom $A)" = '["1","42"]'
seed
run "" $C discord deny abc123
check "deny: exit 0, code deleted"        test $rc -eq 0 -a "$(jq '.pending|has("abc123")' $A)" = false
check "deny: nobody allowlisted"          test "$(jq -c .allowFrom $A)" = '["1"]'
check "deny: other keys kept"             keeps
run "" $C discord deny abc123
check "deny: unknown code exits 1"        test $rc -eq 1
run "" $C discord policy allowlist
check "policy allowlist"                  test $rc -eq 0 -a "$(jq -r .dmPolicy $A)" = allowlist
check "policy: other keys kept"           keeps
run "" $C discord policy disabled
check "policy disabled"                   test "$(jq -r .dmPolicy $A)" = disabled
run "" $C discord policy bogus
check "policy bogus: usage, exit 2"       test $rc -eq 2 -a -n "$(grep -i usage $S/out.$N)" -a "$(jq -r .dmPolicy $A)" = disabled
run "" $C discord allow 77
check "allow: added"                      test "$(jq -c .allowFrom $A)" = '["1","77"]' -a $rc -eq 0
check "allow: other keys kept"            keeps
run "" $C discord remove 1
check "remove: removed"                   test "$(jq -c .allowFrom $A)" = '["77"]' -a $rc -eq 0
check "remove: other keys kept"           keeps
print -r -- "DISCORD_BOT_TOKEN=$TOK" > $D/tt/.env
run "" $C discord forget
check "forget: message and .env gone"     test "$out" = "discord: token removed for tt" -a ! -e $D/tt/.env
check "forget: access.json kept"          test -f $A
# bad / missing access.json: unchanged, exit 1
print -r -- 'not json{' > $A; cp $A $S/before
run "" $C discord allow 5
check "bad access.json: exit 1, byte-identical" test $rc -eq 1 && cmp -s $A $S/before
run "" $C discord policy allowlist
check "bad access.json (policy): exit 1, unchanged" test $rc -eq 1 && cmp -s $A $S/before
check "bad access.json: no .next left"    test ! -e $A.next
# jq missing: a PATH without jq
mkdir -p $S/nojq; for t in zsh sh env cat grep mkdir chmod rm mv date tr python3 dirname ps; do p=$(command -v $t) && ln -sf $p $S/nojq/$t; done
seed; (( N++ )); print -r -- "" | env PATH="$S/nojq" ${commands[zsh]} $C discord allow 5 > $S/out.$N 2>&1; rc=$?
check "jq missing: exit 1 with message"   test $rc -eq 1 -a -n "$(grep 'discord: jq not found' $S/out.$N)"

# --- status
rm -rf "$D" "$S/cfg"/*(N); mkdir -p "$S/cfg"
run "" $C discord status
check "status fresh: token missing"       test -n "$(grep -x 'token: missing' $S/out.$N)"
check "status fresh: paired none"         test -n "$(grep -x 'paired: none' $S/out.$N)"
check "status fresh: policy pairing"      test -n "$(grep -x 'policy: pairing' $S/out.$N)"
check "status fresh: ack reaction off"    test -n "$(grep -x 'ack reaction: off' $S/out.$N)"
check "status fresh: held by nobody"      test -n "$(grep -x 'held by: nobody' $S/out.$N)"
check "status fresh: plugin missing"      test -n "$(grep -x 'plugin: missing' $S/out.$N)"
check "status fresh: launcher drift"      test -n "$(grep -x 'launcher: drift' $S/out.$N)"
check "status fresh: watch not loaded"    test -n "$(grep -x 'watch: not loaded' $S/out.$N)"
run "" $C discord status
check "status: lines in order"            test "$(sed 's/:.*//' $S/out.$N | tr '\n' ,)" = "token,paired,policy,ack reaction,held by,plugin,launcher,watch,"
run "$TOK" $C discord token
print -r -- '{"dmPolicy":"allowlist","allowFrom":["1","2"],"ackReaction":"👀"}' > $A
mkdir -p $S/cfg/plugins; print -r -- '{"version":2,"plugins":{"discord@claude-plugins-official":[{"version":"0.0.4"}]}}' > $S/cfg/plugins/installed_plugins.json
PV="$S/cfg/plugins/cache/claude-plugins-official/discord"
for v in 0.0.4 0.0.5; do mkdir -p $PV/$v; print -r -- '{"mcpServers":{"discord":{"command":"${CLAUDE_PLUGIN_ROOT}/discord-mcp-launch","args":["${CLAUDE_PLUGIN_ROOT}"]}}}' > $PV/$v/.mcp.json; done
touch $S/watch.loaded
run "" $C discord status
check "status: token set"                 test -n "$(grep -x 'token: set' $S/out.$N)"
check "status: paired 2"                  test -n "$(grep -x 'paired: 2 allowlisted' $S/out.$N)"
check "status: policy allowlist"          test -n "$(grep -x 'policy: allowlist' $S/out.$N)"
check "status: ack reaction"              test -n "$(grep -x 'ack reaction: 👀' $S/out.$N)"
check "status: plugin ok"                 test -n "$(grep -x 'plugin: ok' $S/out.$N)"
check "status: launcher ok"               test -n "$(grep -x 'launcher: ok' $S/out.$N)"
check "status: watch loaded"              test -n "$(grep -x 'watch: loaded' $S/out.$N)"
print -r -- '{"mcpServers":{"discord":{"command":"bun","args":[]}}}' > $PV/0.0.5/.mcp.json
run "" $C discord status
check "status: one drifted version -> drift" test -n "$(grep -x 'launcher: drift' $S/out.$N)"
run "" env -u TMUX -u TMUX_PANE $C discord status --project tt
check "status outside tmux with --project works" test $rc -eq 0 -a -n "$(grep -x 'token: set' $S/out.$N)"
mkdir -p "$HOME/.claude/channels/discord"; print -r -- "DISCORD_BOT_TOKEN=$TOK" > "$HOME/.claude/channels/discord/.env"
run "" $C discord status
check "status: default-dir warning"       test -n "$(grep -Fx 'discord: a token in ~/.claude/channels/discord/.env makes every session connect that bot; run tmux-ctl discord token for a project and delete that file' $S/out.$N)"

# --- watch: no project, no tmux; the watchdog runs through the fake launchctl and a scratch TC_STATE
rm -f $S/watch.loaded
run "" env -u TMUX -u TMUX_PANE $C discord watch status
check "watch status (not installed): exit 0, line from the watchdog"  test $rc -eq 0 -a "$out" = "not installed"
run "" env -u TMUX -u TMUX_PANE TC_DISCORD_WATCH=0 $C discord watch --once
check "watch --once with TC_DISCORD_WATCH=0: exit 0, silent"  test $rc -eq 0 -a -z "$out"
run "" env -u TMUX -u TMUX_PANE $C discord watch bogus
check "watch bogus: usage, exit 2"  test $rc -eq 2 -a -n "$(grep -i usage $S/out.$N)"
check "leak: no LaunchAgent written to the scratch HOME"  test -z "$(ls $HOME/Library/LaunchAgents 2>/dev/null)"

# --- help
h="$($C help)"
check "help: discord token line"          test -n "$(print -r -- "$h" | grep 'tmux-ctl discord token|pair|deny|policy|allow|remove|forget|status')"
check "help: discord watch line"          test -n "$(print -r -- "$h" | grep 'tmux-ctl discord watch --once|install|status|uninstall')"
check "help: ends at the header's last line" test "$(print -r -- "$h" | tail -1)" = "  tmux-ctl metrics <sub> …                run-log metrics (board/metrics.py)"

# --- the token never appears in any output
files=( $S/out.*(N) )
check "scanned output files > 0 (${#files})"  test ${#files} -gt 0
check "secret hits in all output = 0"     test "$(cat $files | grep -c -- "$SECRET")" = 0
tt_done
