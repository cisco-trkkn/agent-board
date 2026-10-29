source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
# first use of the hidden bg session with a slow-starting shell (the .zshrc sleeps 1 s, as a loaded machine does):
# the new pane is not at a prompt yet when the run starts, but it must not be called busy: no lane window.
d="$(mktemp -d "${TMPDIR:-/tmp}/tcslow.XXXXXX")"
tt_zdot "$d/zdot"; print -r -- 'sleep 1' >> "$d/zdot/.zshrc"
tt_setup claude shell
err="$d/err"
out="$($C run tests 'echo hi' 2>"$err" | head -1)"
check "slow first use: output"     test "$out" = hi
check "slow first use: no lane msg" sh -c "! grep -q busy '$err'"
check "slow first use: windows"    test "$(tt list-windows -t '=tt-bg' -F '#{window_name}' | sort | tr '\n' ' ')" = "shell tests "
rm -rf "$d"
tt_done
