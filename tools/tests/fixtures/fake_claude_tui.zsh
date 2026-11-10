# A stand-in for the claude TUI, enough for the telegram watchdog's e2e: an idle prompt, a /mcp list with telegram, a
# telegram detail menu with Reconnect, and a fake telegram server child once Reconnect is chosen.
# Run through a symlink named claude to zsh (so ps and tmux call it claude):  claude -f fake_claude_tui.zsh <marker> [--channels ...]
marker="$1"
screen=prompt; cur=1; buf=
RULE='────────────────────────────────────────────────────────────'
rows=("claude.ai Claude Docs" "claude-artifacts" "plugin:telegram:telegram")
child=
trap '[[ -n "$child" ]] && kill $child 2>/dev/null' EXIT HUP TERM
draw() {   # builtins only: a fork per key made the fake slower than the watchdog's polling
  local i m out=$'\e[2J\e[H'
  case $screen in
    list)
      out+=$'❯ /mcp\n   Manage MCP servers\n'
      for i in {1..$#rows}; do
        if (( i == cur )); then m='   ❯ ✔ '; else m='     ✔ '; fi
        out+="$m${rows[i]}"$'\n'
      done
      out+=$'   ↑/↓ to navigate · Enter to confirm · Esc to cancel\n' ;;
    detail)
      out+=$'   Plugin:telegram:telegram MCP Server\n   Status: ✘ failed\n'
      if (( cur == 1 )); then out+=$'   ❯ 1. Reconnect\n     2. Disable\n'; else out+=$'     1. Reconnect\n   ❯ 2. Disable\n'; fi
      out+=$'   ↑/↓ to navigate · Enter to select · Esc to back\n' ;;
    *)
      out+=$'\n'"$RULE"$'\n'"❯ $buf"$'\n'"$RULE"$'\n  auto mode on\n' ;;
  esac
  print -rn -- "$out"
}
draw
while read -rsk1 c; do
  if [[ "$c" == $'\e' ]]; then
    if read -rsk1 -t 0.1 c2 && [[ "$c2" == '[' ]] && read -rsk1 -t 0.1 c3; then
      [[ "$c3" == B ]] && (( cur < ${#rows} )) && (( cur++ ))
    else
      if [[ $screen == detail ]]; then screen=list; else screen=prompt; fi; cur=1
    fi
  elif [[ "$c" == $'\r' || "$c" == $'\n' ]]; then
    if [[ $screen == prompt && "$buf" == /mcp ]]; then screen=list; cur=1; buf=
    elif [[ $screen == list && "${rows[cur]}" == plugin:telegram* ]]; then screen=detail; cur=1
    elif [[ $screen == detail ]]; then
      if (( cur == 1 )) && [[ -z "$child" ]]; then zsh -c 'sleep 120; sleep 0' telegram/server.ts "$marker" & child=$!; fi
      screen=prompt
    fi
  elif [[ "$c" == $'\x15' ]]; then buf=
  elif [[ $screen == prompt ]]; then buf+="$c"
  fi
  draw
done
