source "${0:A:h}/lib.zsh"
# tc_tmux starts the tmux server from $HOME. A tmux server keeps the directory it was started in for life; once that
# directory is removed, tmux 3.8 starts every new pane there and ignores -c (docs/superpowers/notes/2026-11-09-relay-gone-cwd.md).
R="${0:A:h:h:h}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/tccwd.XXXXXX")"; tmp="${tmp:A}"
sock="tccwd$$"
TB="${TC_TMUX:-$HOME/.local/bin/tmux}"; [[ -x "$TB" ]] || TB="$(command -v tmux)"
trap '"$TB" -L "$sock" kill-server 2>/dev/null; rm -rf "$tmp"' EXIT INT TERM
mkdir -p "$tmp/home" "$tmp/start" "$tmp/target"
# start the server through tc_tmux from a directory that is then removed (as a merged worktree is)
( cd "$tmp/start" && HOME="$tmp/home" TC_TMUX="$TB" TMUX_DASH_TMUX_ARGS="-L $sock -f /dev/null" zsh -c 'unset TMUX; source "$1/bin/_tc_bins.zsh"; tc_tmux new-session -d -s s -c "$2"' _ "$R" "$tmp/target" )
srvpid="$("$TB" -L "$sock" display -p '#{pid}')"
check "server cwd is \$HOME, not the caller's directory" test "$(lsof -a -p "$srvpid" -d cwd -Fn | sed -n 's/^n//p')" = "$tmp/home"
rmdir "$tmp/start"
"$TB" -L "$sock" new-window -d -t "=s:" -n w -c "$tmp/target"
sleep 1
check "new pane after the caller's directory is gone starts in its -c directory" test "$("$TB" -L "$sock" list-panes -t "=s:w" -F '#{pane_current_path}')" = "$tmp/target"
# the new-session exit status still reaches the caller: dev and tmux-overseer use it as the atomic gate
( cd "$tmp/target" && HOME="$tmp/home" TC_TMUX="$TB" TMUX_DASH_TMUX_ARGS="-L $sock -f /dev/null" zsh -c 'unset TMUX; source "$1/bin/_tc_bins.zsh"; tc_tmux new-session -d -s s -c "$2"' _ "$R" "$tmp/target" ) 2>/dev/null; rc=$?
check "a second new-session of the same name still fails (gate kept)" test "$rc" -ne 0
tt_done
