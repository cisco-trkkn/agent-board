source "${0:A:h}/lib.zsh"
# The tmux server's own cwd (spec restart-recovery §4). tmux 3.8 starts new panes in a gone server cwd and ignores -c,
# so dev starts the server from $HOME, and tmux-ctl list warns, as its first line, when the server cwd is gone.
R="${0:A:h:h:h}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/tcsrv.XXXXXX")"; tmp="${tmp:A}"
dsock="tcsrvd$$"; lsock="tcsrvl$$"
TB="${TC_TMUX:-$HOME/.local/bin/tmux}"; [[ -x "$TB" ]] || TB="$(command -v tmux)"
trap '"$TB" -L "$dsock" kill-server 2>/dev/null; "$TB" -L "$lsock" kill-server 2>/dev/null; rm -rf "$tmp"' EXIT INT TERM
mkdir -p "$tmp/home" "$tmp/devstart" "$tmp/proj" "$tmp/start" "$tmp/target" "$tmp/state"
srv_cwd() { lsof -a -p "$("$TB" -L "$1" display -p '#{pid}')" -d cwd -Fn | sed -n 's/^n//p' }

# 1. dev typed in a directory that is later removed: the server it starts sits in $HOME
( cd "$tmp/devstart" && unset TMUX TMUX_PANE && HOME="$tmp/home" ZDOTDIR="$tmp/home" TC_STATE="$tmp/state" TC_TMUX="$TB" \
    TMUX_DASH_TMUX_ARGS="-L $dsock -f /dev/null" TC_LAYOUT=/usr/bin/true DEV_NO_ATTACH=1 DEV_NO_LEAD=1 \
    zsh "$R/bin/dev" "$tmp/proj" >/dev/null 2>&1 )
rmdir "$tmp/devstart"
check "dev started the server" "$TB" -L "$dsock" has-session -t "=proj"
check "dev's server cwd is \$HOME, not the directory dev was typed in" test "$(srv_cwd "$dsock")" = "$tmp/home"

# 2. a server started straight from a directory (not through tc_tmux), then that directory is removed
( cd "$tmp/start" && "$TB" -L "$lsock" -f /dev/null new-session -d -s cw -n claude -c "$tmp/target" )
export TMUX="$("$TB" -L "$lsock" display -p '#{socket_path}'),$$,0"
export TMUX_PANE="$("$TB" -L "$lsock" display -p -t '=cw:claude' '#{pane_id}')" TC_STATE="$tmp/state"
unset TMUX_DASH_TMUX_ARGS TC_SESSION
check "no warning while the server cwd exists" sh -c "! zsh '$R/bin/tmux-ctl' list 2>&1 | grep -q 'tmux server cwd is gone'"
rmdir "$tmp/start"
lsp="$("$TB" -L "$lsock" display -p '#{socket_path}')"
check "first line warns that the server cwd is gone, naming its socket" test "$(zsh "$R/bin/tmux-ctl" list 2>&1 | head -1)" = "tmux server cwd is gone ($tmp/start): new panes start there; restart the tmux server from ~ (tmux -S $lsp kill-server ends every session on it; reopen each project with agent-board dev)"
check "the window listing still follows" sh -c "zsh '$R/bin/tmux-ctl' list 2>&1 | grep -q '  claude  '"
tt_done
