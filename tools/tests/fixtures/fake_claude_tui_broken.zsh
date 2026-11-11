# A stand-in for the claude TUI, enough for the telegram watchdog's e2e: an idle prompt with an input line, and a fake
# telegram server child once `/mcp reconnect plugin:telegram:telegram` is submitted. (The screens the watchdog parses are
# tested against real captures in fixtures/telegram-watch/; this only gives the typing path a process to type into.)
# Run through a symlink named claude to zsh (so ps calls it claude):  claude -f fake_claude_tui.zsh <marker> [--channels ...]
marker="$1"; buf=; last=
RULE='────────────────────────────────────────────────────────────'
child=
trap '[[ -n "$child" ]] && kill $child 2>/dev/null' EXIT HUP TERM
draw() { print -rn -- $'\e[2J\e[H\n'"$RULE"$'\n'"❯ $buf"$'\n'"$RULE"$'\n  auto mode on\n'"${last:+  ⎿  $last}"; }
draw
while read -rsk1 c; do
  if [[ "$c" == $'\r' || "$c" == $'\n' ]]; then
    if [[ "$buf" == '/mcp reconnect plugin:telegram:telegram' ]]; then
      : # broken: the reconnect never brings a server back
      last='Successfully reconnected to plugin:telegram:telegram'
    fi
    buf=
  elif [[ "$c" == $'\x15' ]]; then buf=
  else buf+="$c"
  fi
  draw
done
