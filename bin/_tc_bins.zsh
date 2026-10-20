# _tc_bins.zsh — sourced. One resolver for the tmux command every agent-board caller runs.
#
#   tc_tmux <tmux args…>           run tmux against the resolved server
#   TC_TMUX_CMD                    that command as an array: the binary, then the server arguments
#   tc_tmux_resolve [dedicated]    recompute both (done once when this file is sourced). `dedicated` is for the
#                                  entry points dev and tmux-dash: agent-board's own server even when typed in a
#                                  pane of another one
#   tc_tmux_args_str               the server arguments as one shell-quoted string, for TMUX_DASH_TMUX_ARGS
#   TC_TMUX_SRV                    the server selector alone (-L name | -S path | the override), for messages
#
# The binary is $TC_TMUX, else ~/.local/bin/tmux. The server, first match wins:
#   TMUX_DASH_TMUX_ARGS   an explicit override such as "-L work"; the board, its terminals and dev all honour it
#   $TMUX                 the server this command runs inside: hooks, run-shell jobs, tmux-ctl and the tests
#                         talk to their own server, whichever it is (skipped by `dedicated`)
#   agent-board's server  -L ${AGENT_BOARD_TMUX_SOCKET:-agent-board}, with <repo>/config/tmux.conf: a server
#                         started this way loads that file instead of ~/.tmux.conf
# Except on an unmigrated install (tc_tmux_legacy): there `dedicated` means the user's own server, as before.
# board/paneclass.py asks this file for the same answer (tmux_cmd()), so Python and zsh never disagree.
TC_REPO="${${(%):-%x}:A:h:h}"
# An install from before the dedicated server still has agent-board's hook lines in ~/.tmux.conf (install.sh --migrate
# removes them) and no agent-board server running: its projects live on the user's server, so dev and tmux-dash stay
# there until the owner migrates. Reads ~/.tmux.conf only.
tc_tmux_legacy() {
  emulate -L zsh
  grep -qE 'tmux-(teammate-window|session-closed)' "$HOME/.tmux.conf" 2>/dev/null || return 1
  ! "${TC_TMUX:-$HOME/.local/bin/tmux}" -L "${AGENT_BOARD_TMUX_SOCKET:-agent-board}" list-sessions >/dev/null 2>&1
}
tc_tmux_resolve() {
  emulate -L zsh
  if [[ -n "$TMUX_DASH_TMUX_ARGS" ]]; then
    TC_TMUX_SRV=("${(Q@)${(z)TMUX_DASH_TMUX_ARGS}}"); TC_TMUX_ARGS=("${TC_TMUX_SRV[@]}")
  elif [[ "$1" != dedicated && -n "$TMUX" ]]; then
    TC_TMUX_SRV=(-S "${TMUX%%,*}"); TC_TMUX_ARGS=("${TC_TMUX_SRV[@]}")
  elif [[ "$1" == dedicated ]] && tc_tmux_legacy; then
    if [[ -n "$TMUX" ]]; then TC_TMUX_SRV=(-S "${TMUX%%,*}"); else TC_TMUX_SRV=(-L default); fi
    TC_TMUX_ARGS=("${TC_TMUX_SRV[@]}")     # -L default names tmux's own default socket, so children see a non-empty override
  else
    TC_TMUX_SRV=(-L "${AGENT_BOARD_TMUX_SOCKET:-agent-board}")
    TC_TMUX_ARGS=("${TC_TMUX_SRV[@]}" -f "$TC_REPO/config/tmux.conf")
    export AGENT_BOARD_REPO="$TC_REPO"   # config/tmux.conf names this checkout's scripts by it; a server we start inherits it
  fi
  TC_TMUX_CMD=("${TC_TMUX:-$HOME/.local/bin/tmux}" "${TC_TMUX_ARGS[@]}")
}
# tc_bin <tool> <override-var>: the path of a helper tool. The override variable's value, else the tool on PATH, else
# ~/.local/bin/<tool> (the documented legacy fallback for installs that linked their tools there).
tc_bin() {
  emulate -L zsh
  local o="${(P)2}"
  if [[ -n "$o" ]]; then print -r -- "$o"
  elif (( $+commands[$1] )); then print -r -- "$commands[$1]"
  else print -r -- "$HOME/.local/bin/$1"; fi
}
tc_tmux() { "${TC_TMUX_CMD[@]}" "$@" }
tc_tmux_args_str() { print -r -- "${(j: :)${(q)TC_TMUX_ARGS[@]}}" }
tc_tmux_resolve
