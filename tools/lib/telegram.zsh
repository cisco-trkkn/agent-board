# telegram.zsh — sourced by tmux-ctl for `tmux-ctl telegram token|status|forget` (spec 2026-11-09-remote-access §1).
# One bot per project: ${TC_STATE:-$HOME/.local/state/agent-board}/telegram/<project>/.env holds TELEGRAM_BOT_TOKEN=<token>.
# `tmux-ctl telegram watch --once` runs the watchdog (tools/telegram_watch.py) once; launchd does it every 60 s.
# The token is read from stdin only and is never printed. <project> = --project, else the caller's FEEDKEY (inside tmux).

_TG_TOOLS="${${(%):-%x}:A:h:h}"   # file scope: tools/
_tg_root() { print -r -- "${TC_STATE:-$HOME/.local/state/agent-board}/telegram" }
_tg_usage() { print -u2 "usage: tmux-ctl telegram token|status|forget [<project>] (outside tmux: --project <name>; the token is read from stdin)"; return 2 }

telegram_cmd() {
  local sub="$1" project="" a
  if [[ "$sub" == watch ]]; then   # the watchdog: no project, no tmux of our own (it finds the leads' panes itself)
    shift
    python3 "$_TG_TOOLS/telegram_watch.py" "${@:---once}"; return $?
  fi
  shift 2>/dev/null
  local -a pos=()
  while (( $# )); do
    case "$1" in
      --project) project="$2"; shift 2 2>/dev/null || shift ;;
      --project=*) project="${1#--project=}"; shift ;;
      *) pos+=("$1"); shift ;;
    esac
  done
  for a in "${pos[@]}"; do
    # never echo an argument that may be a token
    if [[ "$a" == <->:* || ${#pos} -gt 1 ]]; then
      print -u2 "telegram: the token is never taken from the command line; pipe it on stdin: print -r -- \"\$TOK\" | tmux-ctl telegram token"
      return 2
    fi
  done
  [[ -n "$project" ]] || project="${pos[1]:-$FEEDKEY}"
  [[ -n "$project" ]] || { _tg_usage; return 2 }
  if ! [[ "$project" =~ '^[A-Za-z0-9][A-Za-z0-9._-]*$' ]]; then   # never echo the value: it may be a token
    print -u2 "telegram: a project name uses letters, digits, '.', '_' and '-' and starts with a letter or digit"; return 2
  fi
  local dir="$(_tg_root)/$project"
  case "$sub" in
    token)  _tg_token "$project" "$dir" ;;
    status) _tg_status "$project" "$dir" ;;
    forget) _tg_forget "$project" "$dir" ;;
    *) _tg_usage ;;
  esac
}

_tg_token() {
  local project="$1" dir="$2" tok
  if [[ -t 0 ]]; then read -rs "tok?Bot token: "; print -u2; else read -r tok; fi
  if ! [[ "$tok" =~ '^[0-9]+:[A-Za-z0-9_-]{30,}$' ]]; then
    print -u2 "telegram: that does not look like a bot token"; return 2
  fi
  ( umask 077; mkdir -p -m 700 "$dir" && print -r -- "TELEGRAM_BOT_TOKEN=$tok" > "$dir/.env" ) || { print -u2 "telegram: could not write the token"; return 1 }
  chmod 700 "$dir"; chmod 600 "$dir/.env"
  print -r -- "telegram: token saved for $project (restart its lead to connect)"
}

_tg_status() {
  local project="$1" dir="$2" n pol pid line
  [[ -f "$dir/.env" ]] && print -r -- "token: set" || print -r -- "token: missing"
  n="$(jq '.allowFrom | length' "$dir/access.json" 2>/dev/null)"
  if [[ "${n:-0}" -gt 0 ]]; then print -r -- "paired: $n allowlisted"; else print -r -- "paired: none"; fi
  pol="$(jq -r '.dmPolicy // "pairing"' "$dir/access.json" 2>/dev/null)"
  print -r -- "policy: ${pol:-pairing}"
  [[ -r "$dir/bot.pid" ]] && pid="$(<"$dir/bot.pid")"; pid="${pid//[^0-9]/}"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && [[ "$(ps -o args= -p "$pid" 2>/dev/null)" == *server.ts* ]]; then
    print -r -- "poller: running (pid $pid)"
  else
    print -r -- "poller: stopped"
  fi
  if claude plugin list 2>/dev/null | grep -q 'telegram@claude-plugins-official'; then print -r -- "plugin: ok"; else print -r -- "plugin: missing"; fi
  [[ -x "$HOME/.bun/bin/bun" ]] && print -r -- "bun: ok" || print -r -- "bun: missing"
  if [[ -f "$HOME/.claude/channels/telegram/.env" ]]; then
    print -r -- "telegram: a token in ~/.claude/channels/telegram/.env makes every session poll that bot; run tmux-ctl telegram token for a project and delete that file"
  fi
  return 0
}

_tg_forget() {
  local project="$1" dir="$2"
  rm -f "$dir/.env"
  print -r -- "telegram: token removed for $project"
}
