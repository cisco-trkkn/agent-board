# _tc_bins.zsh — sourced. One resolver for the tmux command every agent-board caller runs.
#
#   tc_tmux <tmux args…>    run tmux against the resolved server
#   TC_TMUX_CMD             that command as an array: the binary, then the server arguments
#   tc_tmux_resolve         recompute both (done once when this file is sourced)
#   tc_tmux_args_str        the server arguments as one shell-quoted string, for TMUX_DASH_TMUX_ARGS
#
# The binary is $TC_TMUX, else ~/.local/bin/tmux. The server, first match wins:
#   TMUX_DASH_TMUX_ARGS   an explicit override such as "-L work"; the board, its terminals and dev all honour it
#   $TMUX                 the server this command runs inside: hooks, run-shell jobs, tmux-ctl and the tests
#                         talk to their own server, whichever it is
#   (none)                tmux's default server
# board/paneclass.py asks this file for the same answer (tmux_cmd()), so Python and zsh never disagree.
TC_REPO="${${(%):-%x}:A:h:h}"
tc_tmux_resolve() {
  emulate -L zsh
  if [[ -n "$TMUX_DASH_TMUX_ARGS" ]]; then
    TC_TMUX_ARGS=("${(Q@)${(z)TMUX_DASH_TMUX_ARGS}}")
  elif [[ -n "$TMUX" ]]; then
    TC_TMUX_ARGS=(-S "${TMUX%%,*}")
  else
    TC_TMUX_ARGS=()
  fi
  TC_TMUX_CMD=("${TC_TMUX:-$HOME/.local/bin/tmux}" "${TC_TMUX_ARGS[@]}")
}
tc_tmux() { "${TC_TMUX_CMD[@]}" "$@" }
tc_tmux_args_str() { print -r -- "${(j: :)${(q)TC_TMUX_ARGS[@]}}" }
tc_tmux_resolve
