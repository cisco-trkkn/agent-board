# discord.zsh — sourced by tmux-ctl for `tmux-ctl discord token|pair|deny|policy|allow|remove|forget|status` (spec 2026-11-11 §6).
# One bot per project: ${TC_STATE:-$HOME/.local/state/agent-board}/discord/<project>/ holds .env (DISCORD_BOT_TOKEN=<token>)
# and the plugin's access.json (dmPolicy, allowFrom, groups, pending). The token is read from stdin only and never printed.
# <project> = --project, else the caller's FEEDKEY (inside tmux).

_DC_TOOLS="${${(%):-%x}:A:h:h}"   # file scope: tools/
_dc_root() { print -r -- "${TC_STATE:-$HOME/.local/state/agent-board}/discord" }
_dc_usage() { print -u2 "usage: tmux-ctl discord token|pair <code>|deny <code>|policy pairing|allowlist|disabled|allow <id>|remove <id>|forget|status [--project <name>] (the token is read from stdin)"; return 2 }
_dc_tokenish() { [[ "$1" == *.* && ${#1} -ge 50 ]] }

discord_cmd() {
  local sub="$1" project="" a
  shift 2>/dev/null
  local -a pos=()
  while (( $# )); do
    case "$1" in
      --project) project="$2"; shift 2 2>/dev/null || shift ;;
      --project=*) project="${1#--project=}"; shift ;;
      *) pos+=("$1"); shift ;;
    esac
  done
  for a in "${pos[@]}" "$project"; do
    # never echo an argument that may be a token
    if _dc_tokenish "$a"; then
      print -u2 "discord: the token is never taken from the command line; pipe it on stdin: print -r -- \"\$TOK\" | tmux-ctl discord token"
      return 2
    fi
  done
  if (( ${#pos} > 1 )); then
    print -u2 "discord: too many arguments (the token is never taken from the command line; pipe it on stdin)"; return 2
  fi
  local arg="${pos[1]}"
  case "$sub" in token|status|forget) ;; pair|deny|policy|allow|remove) [[ -n "$arg" ]] || { _dc_usage; return 2 } ;; *) _dc_usage; return 2 ;; esac
  [[ -n "$project" ]] || project="$FEEDKEY"
  [[ -n "$project" ]] || { [[ "$sub" == (token|status|forget) && -n "$arg" ]] && project="$arg" && arg=; }
  [[ -n "$project" ]] || { _dc_usage; return 2 }
  if ! [[ "$project" =~ '^[A-Za-z0-9][A-Za-z0-9._-]*$' ]]; then   # never echo the value: it may be a token
    print -u2 "discord: a project name uses letters, digits, '.', '_' and '-' and starts with a letter or digit"; return 2
  fi
  local dir="$(_dc_root)/$project"
  case "$sub" in
    token)  _dc_token "$project" "$dir" ;;
    status) _dc_status "$project" "$dir" ;;
    forget) _dc_forget "$project" "$dir" ;;
    *) (( $+commands[jq] )) || { print -u2 "discord: jq not found"; return 1 }
       case "$sub" in
         pair)   _dc_pair "$dir" "$arg" ;;
         deny)   _dc_deny "$dir" "$arg" ;;
         policy) case "$arg" in pairing|allowlist|disabled) _dc_write "$dir" '.dmPolicy = $p' --arg p "$arg" ;; *) _dc_usage ;; esac ;;
         allow)  _dc_write "$dir" '.allowFrom = ((.allowFrom // []) + [$s] | unique)' --arg s "$arg" ;;
         remove) _dc_write "$dir" '.allowFrom = ((.allowFrom // []) - [$s])' --arg s "$arg" ;;
       esac ;;
  esac
}

# _dc_write <dir> <jq filter> [jq args…]: read the live file, transform it, write .next (600), mv over it
_dc_write() {
  local dir="$1" f="$2"; shift 2
  local live="$dir/access.json"
  [[ -e "$live" ]] || { ( umask 077; mkdir -p -m 700 "$dir" && print -r -- '{"dmPolicy":"pairing","allowFrom":[],"groups":{},"pending":{}}' > "$live" ) }
  jq -e . "$live" >/dev/null 2>&1 || { print -u2 "discord: $live is not readable JSON; left as is"; return 1 }
  ( umask 077; jq --indent 2 "$@" "$f" "$live" > "$live.next" ) && chmod 600 "$live.next" && mv -f "$live.next" "$live" \
    || { rm -f "$live.next"; print -u2 "discord: could not write $live"; return 1 }
}

_dc_token() {
  local project="$1" dir="$2" tok
  if [[ -t 0 ]]; then read -rs "tok?Bot token: "; print -u2; else read -r tok; fi
  if [[ -z "$tok" || "$tok" == *[[:space:]]* ]]; then
    print -u2 "discord: that does not look like a bot token"; return 2
  fi
  (( $+commands[jq] )) || { print -u2 "discord: jq not found"; return 1 }
  ( umask 077; mkdir -p -m 700 "$dir" && print -r -- "DISCORD_BOT_TOKEN=$tok" > "$dir/.env.next" && mv -f "$dir/.env.next" "$dir/.env" ) \
    || { rm -f "$dir/.env.next"; print -u2 "discord: could not write the token"; return 1 }
  chmod 700 "$dir"; chmod 600 "$dir/.env"
  _dc_write "$dir" 'if has("ackReaction") then . else .ackReaction = "👀" end' || return 1
  print -r -- "discord: token saved for $project (restart its lead: agent-board lead --continue, or Restart orchestrator on the board)"
}

_dc_pair() {   # _dc_pair <dir> <code>
  local dir="$1" code="$2" live="$1/access.json" now sid cid
  [[ -e "$live" ]] && jq -e . "$live" >/dev/null 2>&1 || { print -u2 "discord: $live is not readable JSON; left as is"; return 1 }
  now="$(python3 -c 'import time;print(int(time.time()*1000))')"
  sid="$(jq -r --arg c "$code" --argjson n "$now" '.pending[$c] | select(. != null and .expiresAt >= $n) | .senderId' "$live")"
  cid="$(jq -r --arg c "$code" '.pending[$c].chatId // empty' "$live")"
  [[ -n "$sid" ]] || { print -u2 "discord: no pending pairing for that code (unknown or expired)"; return 1 }
  _dc_write "$dir" '.allowFrom = ((.allowFrom // []) + [$s] | unique) | del(.pending[$c])' --arg s "$sid" --arg c "$code" || return 1
  ( umask 077; mkdir -p -m 700 "$dir/approved" && print -rn -- "$cid" > "$dir/approved/$sid" ) || { print -u2 "discord: could not write the approval"; return 1 }
  print -r -- "discord: paired $sid"
}

_dc_deny() {   # _dc_deny <dir> <code>
  local dir="$1" code="$2" live="$1/access.json"
  [[ -e "$live" ]] && jq -e . "$live" >/dev/null 2>&1 || { print -u2 "discord: $live is not readable JSON; left as is"; return 1 }
  jq -e --arg c "$code" '.pending | has($c)' "$live" >/dev/null 2>&1 || { print -u2 "discord: no pending pairing for that code"; return 1 }
  _dc_write "$dir" 'del(.pending[$c])' --arg c "$code" && print -r -- "discord: denied"
}

_dc_status() {
  local project="$1" dir="$2" n pol ack cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}" d bad=0 any=0
  "$_DC_TOOLS/../claude/plugin/scripts/discord-mcp-launch" --has-token "$dir" && print -r -- "token: set" || print -r -- "token: missing"
  n="$(jq '.allowFrom | length' "$dir/access.json" 2>/dev/null)"
  if [[ "${n:-0}" -gt 0 ]]; then print -r -- "paired: $n allowlisted"; else print -r -- "paired: none"; fi
  pol="$(jq -r '.dmPolicy // "pairing"' "$dir/access.json" 2>/dev/null)"
  print -r -- "policy: ${pol:-pairing}"
  ack="$(jq -r '.ackReaction // ""' "$dir/access.json" 2>/dev/null)"
  print -r -- "ack reaction: ${ack:-off}"
  print -r -- "held by: nobody"
  if jq -e '.plugins | has("discord@claude-plugins-official")' "$cfg/plugins/installed_plugins.json" >/dev/null 2>&1; then print -r -- "plugin: ok"; else print -r -- "plugin: missing"; fi
  for d in "$cfg"/plugins/cache/claude-plugins-official/discord/*(/N); do
    any=1
    [[ "$(jq -r '.mcpServers.discord.command' "$d/.mcp.json" 2>/dev/null)" == '${CLAUDE_PLUGIN_ROOT}/discord-mcp-launch' ]] || bad=1
  done
  (( any && ! bad )) && print -r -- "launcher: ok" || print -r -- "launcher: drift"
  launchctl print "gui/$(id -u)/com.user.agent-board-discord-watch" >/dev/null 2>&1 && print -r -- "watch: loaded" || print -r -- "watch: not loaded"
  if [[ -f "$HOME/.claude/channels/discord/.env" ]]; then
    print -r -- "discord: a token in ~/.claude/channels/discord/.env makes every session connect that bot; run tmux-ctl discord token for a project and delete that file"
  fi
  return 0
}

_dc_forget() {
  local project="$1" dir="$2"
  rm -f "$dir/.env"
  print -r -- "discord: token removed for $project"
}
