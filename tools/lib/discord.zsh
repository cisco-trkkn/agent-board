# discord.zsh — sourced by tmux-ctl for `tmux-ctl discord token|pair|deny|policy|allow|remove|forget|status` (spec 2026-11-11 §6).
# One bot per project: ${TC_STATE:-$HOME/.local/state/agent-board}/discord/<project>/ holds .env (DISCORD_BOT_TOKEN=<token>)
# and the plugin's access.json (dmPolicy, allowFrom, groups, pending). The token is read from stdin only and never printed.
# <project> = --project, else the caller's FEEDKEY (inside tmux).

_DC_TOOLS="${${(%):-%x}:A:h:h}"   # file scope: tools/
_dc_root() { print -r -- "${TC_STATE:-$HOME/.local/state/agent-board}/discord" }
_dc_ops_dir() { print -r -- "$(_dc_root)/_ops" }
_dc_usage() { print -u2 "usage: tmux-ctl discord [--ops] token|pair <code>|deny <code>|policy pairing|allowlist|disabled|allow <id>|remove <id>|forget|status|channel <id>|ops-channels <command-center id> <approvals id>|bridge install|start [--keeper]|stop|audit [--since <ISO>] [--project <name>]|merge-request --project <p> --task <id> --spec <s> --branch <b> [--target main] --tests <line> --verdict <text> [--finding <line>]…|ideas-list [<project>]|ideas-post <file|-> [--dry-run]|send [--thread <key>] [<file>…] [-m <text>]|snap [<project>] (the token is read from stdin)"; return 2 }
_dc_tokenish() { [[ "$1" == *.* && ${#1} -ge 50 ]] }

discord_cmd() {
  local sub="$1" project="" a since="" keeper=0 ops=0
  shift 2>/dev/null
  if [[ "$sub" == watch ]]; then   # the watchdog: no project, no tmux of our own (it finds the leads' panes itself)
    python3 "$_DC_TOOLS/discord_watch.py" "${@:---once}"; return $?
  fi
  [[ "$sub" == (send|snap) ]] && { _dc_send "$sub" "$@"; return $? }   # files out: paths and a message, never a token
  [[ "$sub" == merge-request ]] && { python3 -I "${_DC_TOOLS:h}/board/discord_merge.py" request "$@"; return $? }   # the queue's merge approval: free text (tests, verdict, findings) goes to Python's argv, never a token check or a shell
  [[ "$sub" == (ideas-list|ideas-post) ]] && { python3 -I "${_DC_TOOLS:h}/board/discord_ideas.py" "${sub#ideas-}" "$@"; return $? }   # /ideas: free-text argv goes to Python, never a token check
  [[ "$sub" == migrate ]] && { _dc_migrate; return 0 }   # machine cleanup: no project
  local -a pos=()
  while (( $# )); do
    case "$1" in
      --project) project="$2"; shift 2 2>/dev/null || shift ;;
      --project=*) project="${1#--project=}"; shift ;;
      --keeper) keeper=1; shift ;;
      --ops) ops=1; shift ;;
      --since) since="$2"; shift 2 2>/dev/null || shift ;;
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
  if (( ops )) && [[ -n "$project" ]]; then print -u2 "discord: --ops and --project exclude each other"; _dc_usage; return 2; fi
  if (( ${#pos} > 1 )) && ! [[ "$sub" == ops-channels && ${#pos} == 2 ]]; then
    print -u2 "discord: too many arguments (the token is never taken from the command line; pipe it on stdin)"; return 2
  fi
  local arg="${pos[1]}"
  case "$sub" in token|status|forget|audit) ;; pair|deny|policy|allow|remove|channel|bridge) [[ -n "$arg" ]] || { _dc_usage; return 2 } ;;
    ops-channels) [[ "${pos[1]}" =~ '^[0-9]+$' && "${pos[2]}" =~ '^[0-9]+$' ]] || { _dc_usage; return 2 }; ops=1 ;;
    *) _dc_usage; return 2 ;; esac
  local dir
  if (( ops )); then
    project=_ops; dir="$(_dc_ops_dir)"   # the ops bot: its own state dir; "_ops" is no valid project name, so it skips the project-name check
  else
    [[ "$sub" == ops-channels ]] && { _dc_usage; return 2 }
    [[ -n "$project" ]] || project="$FEEDKEY"
    [[ -n "$project" ]] || { [[ "$sub" == (token|status|forget) && -n "$arg" ]] && project="$arg" && arg=; }
    [[ -n "$project" ]] || { _dc_usage; return 2 }
    if ! [[ "$project" =~ '^[A-Za-z0-9][A-Za-z0-9._-]*$' ]]; then   # never echo the value: it may be a token
      print -u2 "discord: a project name uses letters, digits, '.', '_' and '-' and starts with a letter or digit"; return 2
    fi
    dir="$(_dc_root)/$project"
  fi
  case "$sub" in
    token)  _dc_token "$project" "$dir" ;;
    status) _dc_status "$project" "$dir" "$ops" ;;
    forget) _dc_forget "$project" "$dir" ;;
    audit)  _dc_audit "$dir" "$since" ;;
    bridge) _dc_bridge "$dir" "$project" "$arg" "$keeper" "$ops" ;;
    *) (( $+commands[jq] )) || { print -u2 "discord: jq not found"; return 1 }
       case "$sub" in
         channel) _dc_channel "$dir" "$arg" ;;
         ops-channels) _dc_ops_channels "$dir" "${pos[1]}" "${pos[2]}" ;;
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
  _dc_write "$dir" 'if (.ackReaction // null) == null then .ackReaction = "👀" else . end' || return 1
  print -r -- "discord: token saved for $project (restart its lead: agent-board lead --continue, or Restart orchestrator on the board)"
}

_dc_pair() {   # _dc_pair <dir> <code>
  local dir="$1" code="$2" live="$1/access.json" now sid cid
  [[ -e "$live" ]] && jq -e . "$live" >/dev/null 2>&1 || { print -u2 "discord: $live is not readable JSON; left as is"; return 1 }
  now="$(python3 -c 'import time;print(int(time.time()*1000))')"
  sid="$(jq -r --arg c "$code" --argjson n "$now" '.pending[$c] | select(. != null and .expiresAt >= $n) | .senderId' "$live")"
  cid="$(jq -r --arg c "$code" '.pending[$c].chatId // empty' "$live")"
  [[ -n "$sid" ]] || { print -u2 "discord: no pending pairing for that code (unknown or expired)"; return 1 }
  [[ "$sid" =~ '^[0-9]+$' ]] || { print -u2 "discord: pending entry has a bad senderId"; return 1 }
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
  local project="$1" dir="$2" ops="${3:-0}" n pol ack cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}" d bad=0 any=0
  "$_DC_TOOLS/../claude/plugin/scripts/discord-mcp-launch" --has-token "$dir" && print -r -- "token: set" || print -r -- "token: missing"
  n="$(jq '.allowFrom | length' "$dir/access.json" 2>/dev/null)"
  if [[ "${n:-0}" -gt 0 ]]; then print -r -- "paired: $n allowlisted"; else print -r -- "paired: none"; fi
  pol="$(jq -r '.dmPolicy // "pairing"' "$dir/access.json" 2>/dev/null)"
  print -r -- "policy: ${pol:-pairing}"
  ack="$(jq -r '.ackReaction // ""' "$dir/access.json" 2>/dev/null)"
  print -r -- "ack reaction: ${ack:-off}"
  local hold hpid hpane hname
  hold="$(dc_holder "$dir")"
  if [[ -z "$hold" ]]; then print -r -- "held by: nobody"
  else
    hpid="${hold%% *}"; hpane="${hold#* }"
    [[ "$hpane" != - ]] && {   # an unknown pane id makes display answer for the current pane: require the id to echo back
      (( $+functions[tc_tmux] )) || source "$_DC_TOOLS/../bin/_tc_bins.zsh" 2>/dev/null
      hname="$(tc_tmux display -p -t "$hpane" '#{pane_id} #{?session_group,#{session_group},#{session_name}}:#{window_name}' 2>/dev/null)"
      [[ "${hname%% *}" == "$hpane" ]] && hname="${hname#* }" || hname=
    }
    if [[ -n "$hname" ]]; then print -r -- "held by: $hname pid $hpid"; else print -r -- "held by: another process pid $hpid"; fi
  fi
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
  local ch cc ap; ch="$(jq -r '.channel // empty' "$dir/bridge.json" 2>/dev/null)"
  if (( ops )); then
    cc="$(jq -r '.command_center // empty' "$dir/bridge.json" 2>/dev/null)"; ap="$(jq -r '.approvals // empty' "$dir/bridge.json" 2>/dev/null)"
    print -r -- "command center: ${cc:-none}"; print -r -- "approvals: ${ap:-none}"
    [[ -n "$cc" && -n "$ap" ]] && ch=ok || ch=
  else
    print -r -- "channel: ${ch:-none}"
  fi
  local bdir; bdir="$(_dc_bridge_dir)"
  if [[ -z "$ch" ]]; then print -r -- "bridge: no channel"
  elif [[ ! -d "$bdir/node_modules" ]]; then print -r -- "bridge: deps missing"
  elif pid="$(_dc_bridge_pid "$dir")"; then print -r -- "bridge: running (pid $pid)"
  elif [[ -e "$dir/bridge.stopped" ]]; then print -r -- "bridge: stopped by user"
  else print -r -- "bridge: stopped"; fi
  local -a pend fail
  pend=("$dir"/outbox/*.json(N)); fail=("$dir"/outbox/failed/*.json(N))
  print -r -- "outbox: ${#pend} pending, ${#fail} failed"
  return 0
}

_dc_bridge_dir() { print -r -- "${TC_DISCORD_BRIDGE_DIR:-${_DC_TOOLS:h}/tools/discord-bridge}" }
# _dc_bridge_pid <dir>: prints the pid and succeeds when bridge.pid names a live process running bridge.js
_dc_bridge_pid() {
  local pid; [[ -r "$1/bridge.pid" ]] || return 1
  pid="$(<"$1/bridge.pid")"; pid="${pid//[[:space:]]/}"
  [[ "$pid" =~ '^[0-9]+$' ]] && kill -0 "$pid" 2>/dev/null && ps -o command= -p "$pid" 2>/dev/null | grep -q 'bridge\.js' || return 1
  print -r -- "$pid"
}

_dc_forget() {
  local project="$1" dir="$2"
  rm -f "$dir/.env"
  print -r -- "discord: token removed for $project"
}

# _dc_penv <pid>: the process's command line and environment as one space-separated line. macOS: `ps -Eww`; Linux has no -E
# (procps `ps` takes BSD `e`), so read /proc/<pid>/environ with NULs turned into spaces.
_dc_penv() {
  if [[ -r /proc/$1/environ ]]; then tr '\0' ' ' < /proc/$1/environ 2>/dev/null
  else ps -Eww -o command= -p $1 2>/dev/null; fi
}
# dc_holder <state dir>: "<claude pid> <pane id|->" when a live lead holds the discord channel for that state dir, else nothing.
# A holder is a process that is the discord server (args hold /discord/ and `bun run … start`, `bun … server.ts` or `node … server.ts`, or
# discord-mcp-launch; never the stub) with DISCORD_STATE_DIR=<dir> exactly in its `ps -E` environment, and that has a
# `claude` ancestor (argv[0] basename claude, or args starting `claude `) whose own parent is not 1 (an orphaned server
# or a detached claude is not a live holder). The pane is that claude's TMUX_PANE.
dc_holder() {
  emulate -L zsh
  local dir="$1" pid ppid args e p n c
  local -A par nm
  local -a cands
  [[ -n "$dir" ]] || return 0
  while read -r pid ppid args; do
    par[$pid]=$ppid; nm[$pid]="$args"
    [[ "$args" == *discord-mcp-stub.js* ]] && continue
    if [[ "$args" == *discord-mcp-launch* ]] || [[ "$args" == */discord/* && ( "$args" =~ 'bun run .*start' || "$args" =~ 'bun .*server\.ts' || "$args" =~ 'node .*(^| |/)server\.ts( |$)' ) ]]; then cands+=($pid); fi
  done < <(ps -A -o pid=,ppid=,args= 2>/dev/null)
  for pid in $cands; do
    e="$(_dc_penv $pid) "
    [[ "$e" == *" DISCORD_STATE_DIR=$dir "* ]] || continue
    p=$pid n=0
    while [[ -n "${par[$p]}" && $p -gt 1 && $n -lt 64 ]]; do
      (( n++ ))
      args="${nm[$p]}"
      # version-named processes (2.1.325 …) are teammates and deliberately do not count as a lead
      if [[ "${${args%% *}:t}" == claude || "$args" == "claude "* ]]; then
        [[ "${par[$p]}" == 1 ]] && break
        e="$(_dc_penv $p) "
        c="-"; [[ "$e" =~ ' TMUX_PANE=(%[0-9]+) ' ]] && c="${match[1]}"
        print -r -- "$p $c"; return 0
      fi
      p="${par[$p]}"
    done
  done
  return 0
}

# _dc_migrate: remove what the Telegram channel left on this machine (idempotent; one line per action; always exit 0)
_dc_migrate() {
  local label=com.user.agent-board-telegram-watch plist="$HOME/Library/LaunchAgents/com.user.agent-board-telegram-watch.plist" tg="${TC_STATE:-$HOME/.local/state/agent-board}/telegram"
  if launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1; then print -r -- "telegram watch: booted out"; else print -r -- "telegram watch: not loaded"; fi
  if [[ -e "$plist" ]]; then rm -f "$plist" && print -r -- "telegram watch: plist removed"; else print -r -- "telegram watch: no plist"; fi
  # only an enabled plugin is disabled: a failing `claude plugin disable` must not read as "not enabled" (the user gate checks this line)
  local rc
  if (( $+commands[jq] )) && jq -e '.enabledPlugins["telegram@claude-plugins-official"] == true' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json" >/dev/null 2>&1; then
    claude plugin disable telegram@claude-plugins-official >/dev/null 2>&1; rc=$?
    if (( rc == 0 )); then print -r -- "telegram plugin: disabled"; else print -r -- "telegram plugin: could not disable (rc $rc)"; fi
  else
    print -r -- "telegram plugin: not enabled"
  fi
  [[ -d "$tg" ]] && print -r -- "telegram: token dirs kept in $tg (delete them by hand when done)"
  return 0
}

# _dc_channel <dir> <id>: the project's home channel -> access.json groups[<id>] and bridge.json; a no-op when both already hold it
_dc_channel() {
  local dir="$1" id="$2" live="$1/access.json" user want cur
  [[ "$id" =~ '^[0-9]+$' ]] || { _dc_usage; return 2 }
  [[ -e "$live" ]] && jq -e . "$live" >/dev/null 2>&1 || { print -u2 "discord: pair or allow a user first"; return 1 }
  user="$(jq -r '.allowFrom[0] // empty' "$live")"
  [[ -n "$user" ]] || { print -u2 "discord: pair or allow a user first"; return 1 }
  local gwant gcur bwant bcur changed=0
  gwant="$(jq -cS '{requireMention: false, allowFrom: (.allowFrom // [])}' "$live")"
  gcur="$(jq -cS --arg c "$id" '.groups[$c] // empty' "$live")"
  bwant="$(jq -cnS --arg c "$id" --arg u "$user" '{channel: $c, user: $u}')"
  bcur="$(jq -cS . "$dir/bridge.json" 2>/dev/null)"
  if [[ "$gwant" != "$gcur" ]]; then
    _dc_write "$dir" '.groups[$c] = {"requireMention": false, "allowFrom": (.allowFrom // [])}' --arg c "$id" || return 1
    changed=1
  fi
  if [[ "$bwant" != "$bcur" ]]; then
    ( umask 077; print -r -- "$bwant" | jq --indent 2 . > "$dir/bridge.json.next" ) && chmod 600 "$dir/bridge.json.next" && mv -f "$dir/bridge.json.next" "$dir/bridge.json" \
      || { rm -f "$dir/bridge.json.next"; print -u2 "discord: could not write $dir/bridge.json"; return 1 }
    changed=1
  fi
  if (( changed )); then print -r -- "channel: $id"; else print -r -- "channel: $id (unchanged)"; fi
}

# _dc_ops_channels <dir> <command center id> <approvals id>: the ops bot's two channels -> access.json groups and bridge.json; a no-op when both already hold them
_dc_ops_channels() {
  local dir="$1" cc="$2" ap="$3" live="$1/access.json" user gwant bwant bcur c changed=0
  [[ -e "$live" ]] && jq -e . "$live" >/dev/null 2>&1 || { print -u2 "discord: pair or allow a user first"; return 1 }
  user="$(jq -r '.allowFrom[0] // empty' "$live")"
  [[ -n "$user" ]] || { print -u2 "discord: pair or allow a user first"; return 1 }
  gwant="$(jq -cS '{requireMention: false, allowFrom: (.allowFrom // [])}' "$live")"
  for c in "$cc" "$ap"; do
    if [[ "$gwant" != "$(jq -cS --arg c "$c" '.groups[$c] // empty' "$live")" ]]; then
      _dc_write "$dir" '.groups[$c] = {"requireMention": false, "allowFrom": (.allowFrom // [])}' --arg c "$c" || return 1
      changed=1
    fi
  done
  bwant="$(jq -cnS --arg c "$cc" --arg a "$ap" --arg u "$user" '{command_center: $c, approvals: $a, user: $u}')"
  bcur="$(jq -cS . "$dir/bridge.json" 2>/dev/null)"
  if [[ "$bwant" != "$bcur" ]]; then
    ( umask 077; print -r -- "$bwant" | jq --indent 2 . > "$dir/bridge.json.next" ) && chmod 600 "$dir/bridge.json.next" && mv -f "$dir/bridge.json.next" "$dir/bridge.json" \
      || { rm -f "$dir/bridge.json.next"; print -u2 "discord: could not write $dir/bridge.json"; return 1 }
    changed=1
  fi
  if (( changed )); then print -r -- "ops-channels: $cc $ap"; else print -r -- "ops-channels: $cc $ap (unchanged)"; fi
}

# _dc_bridge <dir> <project> install|start|stop [keeper 0|1] [ops 0|1]: stop writes bridge.stopped; start --keeper (the board) honours it, a person clears it
_dc_bridge() {
  local dir="$1" project="$2" act="$3" keeper="${4:-0}" ops="${5:-0}" bdir pid repo="${_DC_TOOLS:h}"
  bdir="$(_dc_bridge_dir)"
  case "$act" in
    install)
      ( cd "$bdir" && npm ci --omit=dev ) ;;
    stop)
      ( umask 077; : > "$dir/bridge.stopped" ) && chmod 600 "$dir/bridge.stopped"
      if pid="$(_dc_bridge_pid "$dir")"; then kill -TERM "$pid" && print -r -- "bridge: stopping (pid $pid)"
      else rm -f "$dir/bridge.pid"; print -r -- "bridge: not running"; fi ;;
    start)
      [[ "$TC_DISCORD_BRIDGE" == 0 ]] && { print -r -- "bridge: disabled (TC_DISCORD_BRIDGE=0)"; return 0 }
      if pid="$(_dc_bridge_pid "$dir")"; then print -r -- "bridge: running (pid $pid)"; return 0; fi
      if [[ -e "$dir/bridge.stopped" ]]; then
        (( keeper )) && { print -r -- "bridge: stopped by user (bridge.stopped)"; return 0 }
        rm -f "$dir/bridge.stopped"
      fi
      "$_DC_TOOLS/../claude/plugin/scripts/discord-mcp-launch" --has-token "$dir" || { print -u2 "bridge: no bot token (tmux-ctl discord token)"; return 1 }
      local win=discord opsarg=
      if (( ops )); then
        [[ -n "$(jq -r '.command_center // empty' "$dir/bridge.json" 2>/dev/null)" && -n "$(jq -r '.approvals // empty' "$dir/bridge.json" 2>/dev/null)" ]] \
          || { print -u2 "bridge: no command_center/approvals channels (tmux-ctl discord ops-channels <command center id> <approvals id>)"; return 1 }
        win=discord-ops; opsarg=" --ops"
      else
        [[ -n "$(jq -r '.channel // empty' "$dir/bridge.json" 2>/dev/null)" ]] || { print -u2 "bridge: no channel (tmux-ctl discord channel <id>)"; return 1 }
      fi
      [[ -d "$bdir/node_modules" ]] || { print -u2 "bridge: node_modules missing (tmux-ctl discord bridge install)"; return 1 }
      BG="${project}-bg"   # ops: _ops-bg; outside tmux BG is empty; the bridge window lives in the project's hidden session directly
      ensure_bg
      t kill-window -t "=${BG}:=${win}" 2>/dev/null
      t new-window -d -t "=${BG}:" -n "$win" -c "$repo" "exec node ${(q)repo}/tools/discord-bridge/bridge.js ${(q)dir}${opsarg}" || { print -u2 "bridge: could not start the window"; return 1 }
      print -r -- "bridge: started in ${BG}:${win}" ;;
    *) _dc_usage ;;
  esac
}

# _dc_audit <dir> <since>: audit.jsonl as "<ts> <user> <action> <target> <result>", ts >= since
_dc_audit() {
  local f="$1/audit.jsonl"
  [[ -s "$f" ]] || { print -r -- "audit: none"; return 0 }
  jq -r --arg s "$2" 'select($s == "" or (.ts|tostring) >= $s) | "\(.ts) \(.user) \(.action) \(.target) \(.result)"' "$f"
}

# _dc_send send|snap [--thread <key>] [-m <text>] [--project <name>] <file>…|[<project>]
# send: one post op carrying the files (absolute paths, each checked before anything is written).
# snap: headless Chrome screenshots the board into <dir>/tmp/ and sends it with delete_files (the bridge removes it after the send).
# The board URL carries the token: it only goes to Chrome's argv, never to an op, a message or a log line.
_dc_send() {
  local mode="$1" project="" thread="-" text="" f p n
  shift
  local -a files=() pos=()
  while (( $# )); do
    case "$1" in
      --project) project="$2"; shift 2 2>/dev/null || shift ;;
      --project=*) project="${1#--project=}"; shift ;;
      --thread) thread="$2"; shift 2 2>/dev/null || shift ;;
      -m) text="$2"; shift 2 2>/dev/null || shift ;;
      *) pos+=("$1"); shift ;;
    esac
  done
  if [[ "$mode" == snap ]]; then
    (( ${#pos} <= 1 )) || { _dc_usage; return 2 }
    [[ -n "$project" ]] || project="${pos[1]}"
  else
    files=("${pos[@]}")
  fi
  [[ -n "$project" ]] || project="$FEEDKEY"
  [[ -n "$project" ]] || { _dc_usage; return 2 }
  if ! [[ "$project" =~ '^[A-Za-z0-9][A-Za-z0-9._-]*$' ]]; then
    print -u2 "discord: a project name uses letters, digits, '.', '_' and '-' and starts with a letter or digit"; return 2
  fi
  local dir="$(_dc_root)/$project" delete=0
  if [[ "$mode" == snap ]]; then
    local chrome="${TC_CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}" tok url png
    [[ -x "$chrome" ]] || { print -u2 "snap: Chrome not found"; return 1 }
    tok="$(<"$HOME/.local/state/tmux-dash/token" 2>/dev/null)" || tok=
    [[ -n "$tok" ]] || { print -u2 "snap: no board token (is the board running?)"; return 1 }
    url="http://127.0.0.1:${TMUX_DASH_PORT:-7700}/$tok/"
    mkdir -p "$dir/tmp" || { print -u2 "snap: could not create $dir/tmp"; return 1 }
    png="$dir/tmp/snap-$(date +%s)-$$.png"
    perl -e 'alarm shift; exec @ARGV or exit 127' "${TC_SNAP_TIMEOUT:-60}" "$chrome" --headless=new --virtual-time-budget=5000 --window-size=1200,1600 "--screenshot=$png" "$url" >/dev/null 2>&1 </dev/null
    local crc=$?
    if (( crc == 142 )); then rm -f "$png"; print -u2 "snap: Chrome timed out"; return 1; fi   # 128+SIGALRM
    [[ -s "$png" ]] || { rm -f "$png"; print -u2 "snap: no screenshot"; return 1 }
    files=("$png"); delete=1
    [[ -n "$text" ]] || text="board snapshot $(date +%H:%M)"
  else
    (( ${#files} )) || [[ -n "$text" ]] || { _dc_usage; return 2 }
    (( ${#files} <= 10 )) || { print -u2 "send: at most 10 files"; return 2 }
    local -a abs=()
    for f in "${files[@]}"; do
      p="${f:A}"
      [[ -e "$p" ]] || { print -u2 "send: $p: not found"; return 1 }
      [[ -f "$p" ]] || { print -u2 "send: $p: not a file"; return 1 }
      [[ -r "$p" ]] || { print -u2 "send: $p: not readable"; return 1 }
      abs+=("$p")
    done
    files=("${abs[@]}")
    if [[ -z "$text" ]]; then
      local -a base=("${(@)files:t}"); text="${(j:, :)base}"
    fi
  fi
  python3 -I "${_DC_TOOLS:h}/board/discord_send.py" "$project" "$thread" "$delete" "$text" "${files[@]}" || { print -u2 "$mode: could not write the post"; return 1 }
  n=${#files}
  print -r -- "$mode: 1 post, $n file$([[ $n == 1 ]] || print s)"
}
