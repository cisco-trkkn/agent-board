source "${0:A:h}/lib.zsh"
# tmux-ctl metrics schedule / weekly run without tmux (launchd); other metrics subcommands still need it.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
T="${$(mktemp -d "${TMPDIR:-/tmp}/ttmsched.XXXXXX"):A}"
real_plist="$HOME/Library/LaunchAgents/com.user.agent-board-analytics.plist"
[[ -e "$real_plist" ]] && before=yes || before=no
export HOME="$T/home" TC_STATE="$T/state"; mkdir -p "$HOME" "$TC_STATE"
unset TMUX TMUX_PANE
out="$(env -u TMUX $C metrics schedule bogus 2>&1)"; rc=$?
check "schedule bogus prints the usage line"   zsh -c '[[ $1 == *"usage: tmux-ctl metrics schedule install|status|uninstall"* ]]' _ "$out"
check "schedule bogus exits non-zero"          test $rc -ne 0
out="$(env -u TMUX $C metrics schedule 2>&1)"
check "schedule alone prints the usage line"   zsh -c '[[ $1 == *"usage: tmux-ctl metrics schedule"* ]]' _ "$out"
mkdir -p "$T/fakebin"
print -r -- '#!/bin/sh
echo "$@" >> "$FAKE_LAUNCHCTL_LOG"
exit 0' > "$T/fakebin/launchctl"; chmod +x "$T/fakebin/launchctl"
export AS_LAUNCHCTL="$T/fakebin/launchctl" FAKE_LAUNCHCTL_LOG="$T/launchctl.log"
out="$(env -u TMUX $C metrics schedule status 2>&1)"; rc=$?
if [[ "$(uname)" == Darwin ]]; then
  check "schedule status works without tmux"   test $rc -eq 0 -a "$(print -r -- "$out" | head -1)" = loaded
  check "status prints a last run line"        zsh -c '[[ $1 == *"last run: "* ]]' _ "$out"
  check "status called the fake launchctl"     test -s "$T/launchctl.log"
else
  check "off macOS prints macOS only"          test $rc -eq 2 -a "$out" = "macOS only"
fi
out="$(env -u TMUX $C metrics weekly --dry-run --since 1d 2>&1)"
check "weekly runs without tmux"               zsh -c '[[ $1 != *"not inside tmux"* ]]' _ "$out"
out="$(env -u TMUX $C metrics status 2>&1)"
check "metrics status still needs tmux"        zsh -c '[[ $1 == *"not inside tmux"* ]]' _ "$out"
check "nothing written under the temp Library" test ! -e "$T/home/Library/LaunchAgents/com.user.agent-board-analytics.plist"
[[ -e "${real_plist}" ]] && after=yes || after=no
check "the real plist is unchanged"            test "$before" = "$after"
rm -rf "$T"
tt_done
