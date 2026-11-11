# A stand-in for the claude TUI, enough for the telegram watchdog's e2e: an idle prompt with an input line, and a fake
# telegram server child once `/mcp reconnect plugin:telegram:telegram` is submitted. (The screens the watchdog parses are
# tested against real captures in fixtures/telegram-watch/; this only gives the typing path a process to type into.)
# Run through a symlink named claude to zsh (so ps calls it claude):  claude -f fake_claude_tui.zsh <marker> [--channels ...]
marker="$1"; buf=; last=
RULE='────────────────────────────────────────────────────────────'
child=
trap '[[ -n "$child" ]] && kill $child 2>/dev/null' EXIT HUP TERM
# FAKE_GHOST=1: an empty input line shows a dim (SGR 2) prompt suggestion after `❯` and a no-break space, as the real 2.1.322 does
draw() { local inp="❯ $buf"; [[ -z "$buf" && -n "${FAKE_GHOST:-}" ]] && inp=$'❯\u00a0\e[2mrun it with a few values\e[0m'
  print -rn -- $'\e[2J\e[H\n'"$RULE"$'\n'"$inp"$'\n'"$RULE"$'\n  auto mode on\n'"${last:+  ⎿  $last}"; }
draw
# FAKE_TICK=1: the status row under the input box redraws every 0.3 s, so tmux's window activity is always fresh (a real lead redraws on its own)
tick=""
if [[ -n "${FAKE_TICK:-}" ]]; then
  zsh -fc 'while sleep 0.3; do print -rn -- $'"'"'\e7\e[8;1H  tick '"'"'$RANDOM$'"'"'\e8'"'"'; done' ticker & tick=$!   # its own process: a forked copy would show up in ps as a second lead
  trap '[[ -n "$child" ]] && kill $child 2>/dev/null; [[ -n "$tick" ]] && kill $tick 2>/dev/null' EXIT HUP TERM
fi
while read -rsk1 c; do
  if [[ "$c" == $'\r' || "$c" == $'\n' ]]; then
    if [[ "$buf" == '/mcp reconnect plugin:telegram:telegram' ]]; then
      if [[ -z "$child" ]]; then zsh -c 'sleep 120; sleep 0' telegram/server.ts "$marker" & child=$!; fi   # a second command keeps zsh from exec-ing sleep, which would hide the marker args
      last='Successfully reconnected to plugin:telegram:telegram'
    fi
    buf=
  elif [[ "$c" == $'\x15' ]]; then buf=
  else buf+="$c"
  fi
  draw
done
