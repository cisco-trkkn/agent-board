#!/usr/bin/env zsh
# handoff-arm.sh — PostToolUse(Write|Edit|MultiEdit): a lead that writes a handoff doc (a `.md` under the handoffs dir)
# gets the same mark `tmux-ctl handoff-mark` makes, <state>/handoff-pending/<session id>, so the Stop guard
# (lead-stop-guard.sh) blocks the end of its turn until `tmux-ctl relay` or `tmux-ctl handoff-mark --clear` removes it.
# docs/superpowers/specs/2026-11-24-run-watch-design.md §a.
# Lead = AGENT_BOARD_LEAD=1 and no --agent-name in the Claude process args (a teammate inherits AGENT_BOARD_LEAD from
# the lead; same test as teammate-remind.sh). Handoffs dir: ${TC_HANDOFFS_DIR:-~/.local/state/agent-board/handoffs},
# or the older ~/.claude/handoffs; the tool's file_path and the dirs are compared resolved (:A).
# Seam: TC_TEAMMATE_ARGS_FILE (a file holding the args line instead of `ps -o args= -p $CLAUDE_PID`).
# Not async: the mark must exist before the turn can end. Fail-open: any error exits 0 with nothing printed.
# --scoped (the plugin registration) is accepted and changes nothing.
emulate -L zsh
[[ "$AGENT_BOARD_LEAD" == 1 ]] || exit 0   # before the input is read: this runs on every Write and Edit of every session
{
  input="$(cat)"
  sid="$(print -r -- "$input" | jq -r '.session_id // empty')"
  [[ "$sid" =~ '^[A-Za-z0-9_-]+$' ]] || exit 0
  fp="$(print -r -- "$input" | jq -r '.tool_input.file_path // empty')"
  [[ "$fp" == /*.md ]] || exit 0
  fa="${fp:A}"; hit=0
  for d in "${TC_HANDOFFS_DIR:-$HOME/.local/state/agent-board/handoffs}" "$HOME/.claude/handoffs"; do
    [[ "$fa" == "${d:A}"/* ]] && { hit=1; break }
  done
  (( hit )) || exit 0
  args=
  if [[ -n "$TC_TEAMMATE_ARGS_FILE" ]]; then args="$(<$TC_TEAMMATE_ARGS_FILE)"
  elif [[ -n "$CLAUDE_PID" ]]; then args="$(ps -o args= -p "$CLAUDE_PID")"; fi
  [[ " $args " == *" --agent-name "* ]] && exit 0
  root="${${(%):-%x}:A:h:h:h:h}"
  source "$root/tools/lib/tc-env.zsh" || exit 0
  mark="$TC_STATE_DIR/handoff-pending/$sid"
  mkdir -p "${mark:h}" && : > "$mark"
} >/dev/null 2>&1
exit 0
