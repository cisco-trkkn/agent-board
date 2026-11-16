#!/usr/bin/env zsh
# lead-stop-guard.sh — Stop hook: a lead does not end its turn while a teammate it asked to shut down still has its
# `✦ <name>` window (names recorded by shutdown-record.sh), or while a self-started handoff has not relayed
# (`tmux-ctl handoff-mark`). It prints {"decision":"block","reason":…}; the reason tells the lead what to run.
# docs/superpowers/specs/2026-11-10-queue-reliability-design.md §3.
# Guarded: AGENT_BOARD_LEAD=1 (exported by bin/claude-orchestrator into the lead's own process) and $TMUX set.
# Loop cap: <state>/stop-guard/<session_id> holds "<cksum of the reason> <count>"; the same reason a 4th time in a row
# is allowed, with one line in <state>/stop-guard.log (UTC time, session id, the pending reason).
# Fail-open: any error exits 0 with nothing printed. --scoped (the plugin registration) is accepted and changes nothing.
emulate -L zsh
[[ "$AGENT_BOARD_LEAD" == 1 && -n "$TMUX" ]] || { cat >/dev/null; exit 0 }
{
  input="$(cat)"
  sid="$(print -r -- "$input" | jq -r '.session_id // empty')"
  [[ "$sid" =~ '^[A-Za-z0-9_-]+$' ]] || exit 0
  root="${${(%):-%x}:A:h:h:h:h}"
  source "$root/tools/lib/tc-env.zsh" || exit 0
  source "$root/bin/_tc_bins.zsh" || exit 0
  S="$TC_STATE_DIR"
  pend="$S/shutdown-pending/$sid"; mark="$S/handoff-pending/$sid"; cnt="$S/stop-guard/$sid"
  reasons=()
  if [[ -f "$pend" ]]; then
    # exact window names in the lead's own session; a tmux error is not "no windows": fail open, keep the file
    sess="$(tc_tmux display -p -t "$TMUX_PANE" '#{session_name}')" || exit 0
    wins="$(tc_tmux list-windows -t "=$sess" -F '#{window_name}')" || exit 0
    typeset -U names; names=(${(f)"$(<$pend)"}); left=()
    for n in $names; do [[ $'\n'"$wins"$'\n' == *$'\n'"✦ $n"$'\n'* ]] && left+=("$n"); done
    if (( $#left )); then
      print -rl -- $left > "$pend.$$" && mv "$pend.$$" "$pend"
      reasons+=("teammate(s) ${(j: :)left} still shutting down: run tmux-ctl wait-gone ${(j: :)left}, then continue")
    else rm -f "$pend"; fi
  fi
  [[ -e "$mark" ]] && reasons+=("a self-started handoff has not relayed: run tmux-ctl relay <doc> --old-session $sid (handoff skill step 5)")
  if (( ! $#reasons )); then rm -f "$cnt"; exit 0; fi
  reason="${(j:; :)reasons}"
  h="$(print -rn -- "$reason" | cksum)"; h="${h%% *}"
  oh=; oc=; [[ -f "$cnt" ]] && read -r oh oc < "$cnt"
  if [[ "$oh" == "$h" && "$oc" == <-> ]]; then n=$(( oc + 1 )); else n=1; fi
  if (( n >= 4 )); then
    print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) $sid allowed after 3 blocks: $reason" >> "$S/stop-guard.log"
    rm -f "$cnt"; exit 0
  fi
  mkdir -p "${cnt:h}" && print -r -- "$h $n" > "$cnt" || exit 0
  jq -cn --arg r "$reason" '{decision:"block",reason:$r}'
} 2>/dev/null
exit 0
