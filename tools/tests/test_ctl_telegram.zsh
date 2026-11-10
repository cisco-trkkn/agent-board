source "${0:A:h}/lib.zsh"
# tmux-ctl telegram token|status|forget: per-project bot token storage. Runs on the scratch tmux server from lib.zsh.
# HOME is a temp dir (the default-dir warning and ~/.bun/bin are controlled); `claude` is a stub on a temp PATH dir (never the real one);
# the poller is a stub process whose argv[0] reads "bun server.ts".
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
export TC_TMUX="$TT_BIN"                      # keep the tmux binary found before HOME moves
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/tttg.XXXXXX"):A}"
mkdir -p "$S/bin" "$S/home"
export HOME="$S/home"
cat > "$S/bin/claude" <<STUB
#!/bin/sh
[ "\$1 \$2" = "plugin list" ] && [ -f "$S/plugin.ok" ] && echo "  telegram@claude-plugins-official  0.0.7  enabled"
exit 0
STUB
chmod +x "$S/bin/claude"
export PATH="$S/bin:$PATH"
TOK='123456789:AAdummydummydummydummydummydummy00'
SECRET="${TOK#*:}"
D="$TC_STATE/telegram"
N=0
POLLER=
cleanup() { [[ -n "$POLLER" ]] && kill $POLLER 2>/dev/null; rm -rf "$S" }
trap 'cleanup; tt_teardown' EXIT INT TERM
# run <stdin> <cmd…>: capture stdout+stderr in $S/out.N (scanned for the secret at the end), print it, keep the exit code in $rc
run() { local in="$1"; shift; (( N++ )); print -r -- "$in" | "$@" > "$S/out.$N" 2>&1; rc=$?; out="$(<$S/out.$N)" }

# --- token
run "$TOK" $C telegram token
# mutation: print a different message → this test fails
check "token: message"                    test "$out" = "telegram: token saved for tt (restart its lead to connect)"
check "token: exit 0"                     test $rc -eq 0
check "token: .env content"               test "$(<$D/tt/.env)" = "TELEGRAM_BOT_TOKEN=$TOK"
# mutation: chmod 644 → mode test fails
check "token: .env mode 600"              test "$(mode $D/tt/.env)" = 600
# mutation: mkdir without -m 700 and drop the chmod 700 → mode test fails
check "token: dir mode 700"               test "$(mode $D/tt)" = 700

# grouped session: the key is the group
tt new-session -d -s tt2 -t tt -c "$TT_DIR"
(( N++ )); TMUX_PANE= TC_SESSION=tt2 print -r -- "$TOK" | TC_SESSION=tt2 $C telegram token > "$S/out.$N" 2>&1; rc=$?
# mutation: key on session_name instead of FEEDKEY → grouped test fails
check "grouped: key is the group, not tt2"  test ! -e "$D/tt2" -a -f "$D/tt/.env"
tt kill-session -t '=tt2' 2>/dev/null

# argv token refused
rm -rf "$D"
run "$TOK" $C telegram token tt "$TOK"   # a valid token on stdin too: only the refusal keeps it from being written
# mutation: accept "$2" as token → argv test fails
check "argv token: exit 2"                test $rc -eq 2
check "argv token: nothing written"       test ! -e "$D/tt/.env"
check "argv token: not echoed"            test "$(grep -c -- "$SECRET" $S/out.$N)" = 0
run "$TOK" $C telegram token "$TOK"
check "argv token as first arg: exit 2, nothing written"  test $rc -eq 2 -a ! -e "$D"

# --project carrying the token (valid token on stdin too: only the refusal keeps it from being used)
for form in "--project $TOK" "--project=$TOK"; do
  run "$TOK" $C telegram token ${=form}
  # mutation: apply the refusal to positionals only → this fails (token in output / a dir named after it)
  check "--project <token> (${form%%[ =]*}): exit 2, nothing created, not echoed"  test $rc -eq 2 -a ! -e "$D" -a "$(grep -c -- "$SECRET" $S/out.$N)" = 0
done
run "$TOK" $C telegram token --project 'a:b'
# mutation: drop the charset rule → a:b is accepted and saved
check "project name outside the charset: exit 2, usage names the rule, nothing written"  test $rc -eq 2 -a ! -e "$D" -a -n "$(grep -i 'letters, digits' $S/out.$N)"
run "$TOK" $C telegram token --project 'bad name'
check "project name with a space: exit 2"  test $rc -eq 2 -a ! -e "$D"

# bad shape
run "nope" $C telegram token
# mutation: drop the shape check → bad-shape test fails
check "bad shape: message"                test "$out" = "telegram: that does not look like a bot token"
check "bad shape: exit 2"                 test $rc -eq 2
check "bad shape: no .env"                test ! -e "$D/tt/.env"

# outside tmux
run "$TOK" env -u TMUX -u TMUX_PANE $C telegram token
# mutation: keep the unconditional `not inside tmux` die / drop the usage → outside test fails
check "outside tmux, no --project: exit 2 + usage"  test $rc -eq 2 -a -n "$(grep -i usage $S/out.$N)"
run "$TOK" env -u TMUX -u TMUX_PANE $C telegram token --project p1
check "outside tmux, --project p1: saved"  test $rc -eq 0 -a "$(<$D/p1/.env)" = "TELEGRAM_BOT_TOKEN=$TOK"

# --- status
rm -rf "$D"
(( N++ )); $C telegram status > "$S/out.$N" 2> "$S/err.$N"; rc=$?
# mutation: read bot.pid without the -r test → stderr carries "no such file or directory"
check "status on a fresh project: stderr empty"  test ! -s "$S/err.$N"
run "" $C telegram status
check "status: token missing"             test -n "$(grep -x 'token: missing' $S/out.$N)"
check "status: paired none"               test -n "$(grep -x 'paired: none' $S/out.$N)"
check "status: policy pairing default"    test -n "$(grep -x 'policy: pairing' $S/out.$N)"
check "status: poller stopped"            test -n "$(grep -x 'poller: stopped' $S/out.$N)"
check "status: plugin missing"            test -n "$(grep -x 'plugin: missing' $S/out.$N)"
check "status: bun missing"               test -n "$(grep -x 'bun: missing' $S/out.$N)"
check "status: no default-dir warning"    test -z "$(grep 'makes every session poll' $S/out.$N)"
run "$TOK" $C telegram token
touch "$S/plugin.ok"; mkdir -p "$HOME/.bun/bin"; print '#!/bin/sh' > "$HOME/.bun/bin/bun"; chmod +x "$HOME/.bun/bin/bun"
print -r -- '{"dmPolicy":"allowlist","allowFrom":["1","2"]}' > "$D/tt/access.json"
zsh -c 'exec -a "bun server.ts" sleep 600' & POLLER=$!
sleep 0.3
check "stub poller args contain server.ts"  test -n "$(ps -o args= -p $POLLER | grep server.ts)"
print $POLLER > "$D/tt/bot.pid"
run "" $C telegram status
check "status: token set"                 test -n "$(grep -x 'token: set' $S/out.$N)"
check "status: paired 2 allowlisted"      test -n "$(grep -x 'paired: 2 allowlisted' $S/out.$N)"
check "status: policy allowlist"          test -n "$(grep -x 'policy: allowlist' $S/out.$N)"
# mutation: skip the server.ts check → the "pid reused" test fails
check "status: poller running (pid N)"    test -n "$(grep -x "poller: running (pid $POLLER)" $S/out.$N)"
check "status: plugin ok"                 test -n "$(grep -x 'plugin: ok' $S/out.$N)"
check "status: bun ok"                    test -n "$(grep -x 'bun: ok' $S/out.$N)"
kill $POLLER; wait $POLLER 2>/dev/null
run "" $C telegram status
check "status: poller stopped after kill"  test -n "$(grep -x 'poller: stopped' $S/out.$N)"
# a live pid that is not a poller (this shell) counts as stopped
print $$ > "$D/tt/bot.pid"
run "" $C telegram status
check "status: live non-poller pid is stopped"  test -n "$(grep -x 'poller: stopped' $S/out.$N)"
# default-dir warning
mkdir -p "$HOME/.claude/channels/telegram"; print -r -- "TELEGRAM_BOT_TOKEN=$TOK" > "$HOME/.claude/channels/telegram/.env"
run "" $C telegram status
check "status: default-dir warning (exact line)"  test -n "$(grep -Fx 'telegram: a token in ~/.claude/channels/telegram/.env makes every session poll that bot; run tmux-ctl telegram token for a project and delete that file' $S/out.$N)"

# --- forget
run "" $C telegram forget
check "forget: message"                   test "$out" = "telegram: token removed for tt"
check "forget: .env gone"                 test ! -e "$D/tt/.env"
# mutation: rm -rf the dir → access.json test fails
check "forget: access.json kept"          test -f "$D/tt/access.json"

# --- help
h="$($C help)"
check "help: telegram line"               test -n "$(print -r -- "$h" | grep 'tmux-ctl telegram token|status|forget')"
# mutation: leave the sed range at 2,37 → the telegram lines are cut and these fail; 2,40 → the "send/run only type" line shows and the second fails
check "help: ends at the header's last line"  test "$(print -r -- "$h" | tail -1)" = "                                         outside tmux give --project <name>"
check "help: nothing after the header"    test -z "$(print -r -- "$h" | grep 'send/run only type')"

# --- the token never appears in any captured output
files=( $S/out.*(N) )
check "scanned output files > 0 (${#files})"  test ${#files} -gt 0
check "secret hits in all output = 0"     test "$(cat $files | grep -c -- "$SECRET")" = 0
# leak check: no poller stub left, nothing written under the real HOME state dir by this test
check "leak: no stub poller left"         test -z "$(pgrep -f '^bun server.ts')"
tt_done
