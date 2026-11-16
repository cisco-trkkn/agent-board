source "${0:A:h}/lib.zsh"
# tmux-ctl discord migrate: remove the telegram watchdog, disable the telegram plugin, point at the old token dirs.
# Fake launchctl and claude on PATH, scratch HOME and TC_STATE: nothing real is touched.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
export TC_TMUX="$TT_BIN"
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttdm.XXXXXX"):A}"
mkdir -p "$S/bin" "$S/home/Library/LaunchAgents"
export HOME="$S/home"
REAL_PLISTS="$(ls /Users/$(id -un)/Library/LaunchAgents 2>/dev/null | grep -c agent-board-telegram-watch.plist)"
cat > "$S/bin/launchctl" <<STUB
#!/bin/sh
echo "\$@" >> "$S/launchctl.argv"
[ -f "$S/watch.loaded" ]
STUB
cat > "$S/bin/claude" <<STUB
#!/bin/sh
echo "\$@" >> "$S/claude.argv"
[ -f "$S/plugin.enabled" ]
STUB
chmod +x "$S/bin/launchctl" "$S/bin/claude"
export PATH="$S/bin:$PATH"
trap 'rm -rf "$S"; tt_teardown' EXIT INT TERM
PL="$HOME/Library/LaunchAgents/com.user.agent-board-telegram-watch.plist"
run() { $C discord migrate > "$S/out" 2>&1; rc=$?; out="$(<$S/out)" }

touch "$S/watch.loaded" "$S/plugin.enabled"; print x > "$PL"; mkdir -p "$TC_STATE/telegram/p"
run
check "migrate: exit 0"                   test $rc -eq 0
check "migrate: booted out"               test -n "$(grep -Fx 'telegram watch: booted out' $S/out)"
check "migrate: bootout argv"             test -n "$(grep -Fx "bootout gui/$(id -u)/com.user.agent-board-telegram-watch" $S/launchctl.argv)"
check "migrate: plist removed (line)"     test -n "$(grep -Fx 'telegram watch: plist removed' $S/out)"
check "migrate: plist gone"               test ! -e "$PL"
check "migrate: plugin disabled (line)"   test -n "$(grep -Fx 'telegram plugin: disabled' $S/out)"
check "migrate: disable argv"             test -n "$(grep -Fx 'plugin disable telegram@claude-plugins-official' $S/claude.argv)"
check "migrate: token-dir notice"         test -n "$(grep -Fx "telegram: token dirs kept in $TC_STATE/telegram (delete them by hand when done)" $S/out)"
check "migrate: token dirs really kept"   test -d "$TC_STATE/telegram/p"
rm -f "$S/watch.loaded" "$S/plugin.enabled"; rm -rf "$TC_STATE/telegram"
run
check "second run: exit 0"                test $rc -eq 0
check "second run: not loaded"            test -n "$(grep -Fx 'telegram watch: not loaded' $S/out)"
check "second run: no plist"              test -n "$(grep -Fx 'telegram watch: no plist' $S/out)"
check "second run: plugin not enabled"    test -n "$(grep -Fx 'telegram plugin: not enabled' $S/out)"
check "second run: no token-dir notice"   test -z "$(grep 'token dirs' $S/out)"
check "second run: no error lines"        test -z "$(grep -i 'error\|not found\|usage' $S/out)"
check "migrate works outside tmux"        env -u TMUX -u TMUX_PANE $C discord migrate >/dev/null 2>&1
check "leak: real LaunchAgents unchanged" test "$(ls /Users/$(id -un)/Library/LaunchAgents 2>/dev/null | grep -c agent-board-telegram-watch.plist)" = "$REAL_PLISTS"
tt_done
