# discord-launch.zsh — sourced by bin/claude-orchestrator. dc_ensure_launcher points every installed version of the
# discord plugin at claude/plugin/scripts/discord-mcp-launch, so a session without a token connects to a stub instead of
# failing (a failed start is cached for 15 minutes machine-wide and blocks the next lead; see docs/INSTALL.md).
#
# For each <config>/plugins/cache/claude-plugins-official/discord/<version>/ it copies the launcher and the stub in, backs
# up .mcp.json to <config>/plugin-backups/discord/<version>/.mcp.json.bak-YYYYMMDD (an existing backup of the day is kept)
# and writes the new .mcp.json through .mcp.json.next. Idempotent: a version already pointing at the launcher prints nothing,
# so a plugin update (a new version directory with the stock launcher) is healed at the next lead start.
# Never fails the launch: every error prints one line and returns 0. TC_DISCORD_LAUNCHER=0 turns it off.
_DCL_REPO="${${(%):-%x}:A:h:h:h}"

dc_ensure_launcher() {
  emulate -L zsh
  [[ "$TC_DISCORD_LAUNCHER" == 0 ]] && return 0
  local cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}" scripts="$_DCL_REPO/claude/plugin/scripts"
  local base="$cfg/plugins/cache/claude-plugins-official/discord" d ver want cur
  [[ -d "$base" ]] || return 0
  (( $+commands[jq] )) || { print -u2 "discord: jq not found; the plugin launcher was not checked"; return 0 }
  [[ -f "$scripts/discord-mcp-launch" && -f "$scripts/discord-mcp-stub.js" ]] || { print -u2 "discord: launcher files missing in $scripts"; return 0 }
  want='{"mcpServers":{"discord":{"command":"${CLAUDE_PLUGIN_ROOT}/discord-mcp-launch","args":["${CLAUDE_PLUGIN_ROOT}"]}}}'
  for d in "$base"/*(/N); do
    ver="${d:t}"
    cur="$(jq -cS .mcpServers.discord "$d/.mcp.json" 2>/dev/null)"
    if [[ "$cur" == "$(print -r -- "$want" | jq -cS .mcpServers.discord)" ]] \
       && cmp -s "$scripts/discord-mcp-launch" "$d/discord-mcp-launch" && cmp -s "$scripts/discord-mcp-stub.js" "$d/discord-mcp-stub.js"; then
      continue
    fi
    _dcl_install "$d" "$scripts" "$cfg" "$ver" "$want" 2>/dev/null && print -r -- "discord: plugin launcher installed ($ver)" \
      || { rm -f "$d"/.mcp.json.next "$d"/discord-mcp-*.next 2>/dev/null; print -u2 "discord: could not update the plugin launcher in $d" }
  done
  return 0
}

_dcl_install() {   # _dcl_install <plugin dir> <repo scripts dir> <config dir> <version> <desired .mcp.json>
  emulate -L zsh
  local d="$1" scripts="$2" cfg="$3" ver="$4" want="$5" f bak
  for f in discord-mcp-launch discord-mcp-stub.js; do
    cp "$scripts/$f" "$d/$f.next" && chmod 755 "$d/$f.next" && mv -f "$d/$f.next" "$d/$f" || return 1
  done
  if [[ -f "$d/.mcp.json" ]]; then
    bak="$cfg/plugin-backups/discord/$ver/.mcp.json.bak-$(date +%Y%m%d)"
    if [[ ! -e "$bak" ]]; then mkdir -p "${bak:h}" && cp "$d/.mcp.json" "$bak" || return 1; fi
  fi
  print -r -- "$want" | jq . > "$d/.mcp.json.next" && mv -f "$d/.mcp.json.next" "$d/.mcp.json"
}
