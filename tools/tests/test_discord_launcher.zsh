source "${0:A:h}/lib.zsh"
# Discord part 1: sessions without a token must not fail. claude/plugin/scripts/discord-mcp-launch runs the real
# server when a token exists and a do-nothing MCP stub otherwise; dc_ensure_launcher points the plugin's .mcp.json at it.
# Scratch only: a scratch CLAUDE_CONFIG_DIR, fake plugin dirs, a fake bun, a fake token.
TT_NOTMUX=1
tt_setup claude
if (( ! $+commands[node] )); then print "skip - no node"; tt_done; exit 0; fi
not() { ! "$@" }
D="$TT_DIR"; CFG="$D/cfg"; mkdir -p "$CFG"
LAUNCH="$TT_REPO/claude/plugin/scripts/discord-mcp-launch"
STUBJS="$TT_REPO/claude/plugin/scripts/discord-mcp-stub.js"

# --- the stub, over stdio
rpc() { # rpc <json-lines...>: feed lines to the stub, print its replies; stdin closing must end it
  print -r -- "${(F)@}" | node "$STUBJS"
}
OUT="$(rpc '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"prompts/list"}' \
  '{"jsonrpc":"2.0","id":4,"method":"resources/list"}' \
  '{"jsonrpc":"2.0","id":5,"method":"ping"}' \
  '{"jsonrpc":"2.0","id":6,"method":"nope/nope"}')"; rc=$?
check "stub: exits 0 when stdin closes"        test $rc = 0
check "stub: initialize echoes the protocol"   test "$(print -r -- "$OUT" | jq -r 'select(.id==1) | .result.protocolVersion')" = 2025-06-18
check "stub: initialize names a server"        test "$(print -r -- "$OUT" | jq -r 'select(.id==1) | .result.serverInfo.name')" = discord-stub
check "stub: advertises only tools"            test "$(print -r -- "$OUT" | jq -cS 'select(.id==1) | .result.capabilities')" = '{"tools":{}}'
check "stub: tools/list is empty"              test "$(print -r -- "$OUT" | jq -c 'select(.id==2) | .result.tools')" = '[]'
check "stub: prompts/list is empty"            test "$(print -r -- "$OUT" | jq -c 'select(.id==3) | .result.prompts')" = '[]'
check "stub: resources/list is empty"          test "$(print -r -- "$OUT" | jq -c 'select(.id==4) | .result.resources')" = '[]'
check "stub: ping answered"                    test "$(print -r -- "$OUT" | jq -c 'select(.id==5) | .result')" = '{}'
check "stub: unknown method is -32601"         test "$(print -r -- "$OUT" | jq -r 'select(.id==6) | .error.code')" = -32601
check "stub: no reply to a notification"       test "$(print -r -- "$OUT" | jq -s 'length')" = 6

# --- the launcher: a fake bun on PATH records its argv; the stub runs with the real node
ROOT="$D/plugin"; mkdir -p "$ROOT"
cp "$STUBJS" "$ROOT/"; cp "$LAUNCH" "$ROOT/"; chmod +x "$ROOT/discord-mcp-launch"
FB="$D/fakebin"; mkdir -p "$FB"
print -r -- '#!/bin/sh
{ echo "BUN"; for a in "$@"; do echo "$a"; done; } > "'"$D"'/bun.argv"
if [ -n "$DISCORD_BOT_TOKEN" ]; then echo "REAL-SERVER token"; else echo "REAL-SERVER notoken"; fi' > "$FB/bun"; chmod +x "$FB/bun"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}'
launch() { env -u DISCORD_BOT_TOKEN -u DISCORD_STATE_DIR PATH="$FB:$PATH" "$@" "$ROOT/discord-mcp-launch" "$ROOT" }
SD="$D/state"; mkdir -p "$SD"
rm -f "$D/bun.argv"
R="$(print -r -- "$INIT" | launch DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: no token runs the stub"       test "$(print -r -- "$R" | jq -r .result.serverInfo.name 2>/dev/null)" = discord-stub
check "launcher: no token does not run bun"    not test -e "$D/bun.argv"
print -r -- 'DISCORD_BOT_TOKEN=' > "$SD/.env"
R="$(print -r -- "$INIT" | launch DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: an empty token runs the stub" test "$(print -r -- "$R" | jq -r .result.serverInfo.name 2>/dev/null)" = discord-stub
print -r -- 'DISCORD_BOT_TOKEN=abc.def.ghi' > "$SD/.env"
R="$(print -r -- "$INIT" | launch DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: token in the state dir runs stock bun" test "$R" = "REAL-SERVER notoken"
check "launcher: bun argv is the stock start command" test "$(tr '\n' ' ' < "$D/bun.argv")" = "BUN run --cwd $ROOT --shell=bun --silent start "
rm -f "$SD/.env" "$D/bun.argv"
R="$(print -r -- "$INIT" | launch DISCORD_BOT_TOKEN=1:x DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: token in the environment runs stock bun" test "$R" = "REAL-SERVER token"
check "launcher: env token argv"               test "$(tr '\n' ' ' < "$D/bun.argv")" = "BUN run --cwd $ROOT --shell=bun --silent start "
mkdir -p "$CFG/channels/discord"; print -r -- 'DISCORD_BOT_TOKEN=9:y' > "$CFG/channels/discord/.env"
R="$(print -r -- "$INIT" | launch CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: default state dir is CLAUDE_CONFIG_DIR/channels/discord" test "$R" = "REAL-SERVER notoken"
rm -rf "$CFG/channels"
# no node: the stub runs under bun
NB="$D/nonode"; mkdir -p "$NB"; ln -sf "$(command -v grep)" "$NB/grep"
print -r -- '#!/bin/sh
echo "BUN-STUB $1"' > "$NB/bun"; chmod +x "$NB/bun"
R="$(env -u DISCORD_BOT_TOKEN DISCORD_STATE_DIR="$SD" PATH="$NB" /bin/sh "$ROOT/discord-mcp-launch" "$ROOT")"
check "launcher: no node, no token: bun runs the stub" test "$R" = "BUN-STUB $ROOT/discord-mcp-stub.js"

# --- --has-token <dir>: the one definition of "has a token" (the orchestrator opts a lead in with it)
rm -rf "$SD"; mkdir -p "$SD"
check "has-token: no .env"                      not "$LAUNCH" --has-token "$SD"
: > "$SD/.env";                                  check "has-token: empty .env"    not "$LAUNCH" --has-token "$SD"
print -r -- 'DISCORD_BOT_TOKEN=' > "$SD/.env"; check "has-token: empty value"    not "$LAUNCH" --has-token "$SD"
print -r -- '# DISCORD_BOT_TOKEN=1:x' > "$SD/.env"; check "has-token: commented out" not "$LAUNCH" --has-token "$SD"
print -r -- 'DISCORD_BOT_TOKEN=1:x' > "$SD/.env"; check "has-token: a value"      "$LAUNCH" --has-token "$SD"
check "has-token: prints nothing and starts no server" test -z "$("$LAUNCH" --has-token "$SD" 2>&1)"
rm -rf "$SD"; mkdir -p "$SD"

# --- the helper: heal every installed version's .mcp.json
source "$TT_REPO/tools/lib/discord-launch.zsh"
P="$CFG/plugins/cache/claude-plugins-official/discord"
for v in 0.0.7 0.0.8; do mkdir -p "$P/$v";
  print -r -- '{"mcpServers":{"discord":{"command":"bun","args":["run","--cwd","${CLAUDE_PLUGIN_ROOT}","--shell=bun","--silent","start"]}}}' > "$P/$v/.mcp.json"; done
mkdir -p "$CFG/plugins/cache/claude-plugins-official/other/1.0"; print -r -- '{"keep":1}' > "$CFG/plugins/cache/claude-plugins-official/other/1.0/.mcp.json"
export CLAUDE_CONFIG_DIR="$CFG"
OUT="$(dc_ensure_launcher 2>&1)"; rc=$?
check "helper: exit 0"                          test $rc = 0
check "helper: reports each version"            test "$(print -r -- "$OUT" | grep -c 'discord: plugin launcher')" = 2
for v in 0.0.7 0.0.8; do
  check "helper $v: command is the launcher"    test "$(jq -r .mcpServers.discord.command "$P/$v/.mcp.json")" = '${CLAUDE_PLUGIN_ROOT}/discord-mcp-launch'
  check "helper $v: arg is the plugin root"     test "$(jq -c .mcpServers.discord.args "$P/$v/.mcp.json")" = '["${CLAUDE_PLUGIN_ROOT}"]'
  check "helper $v: launcher copied, executable" test -x "$P/$v/discord-mcp-launch"
  check "helper $v: stub copied"                test -f "$P/$v/discord-mcp-stub.js"
  check "helper $v: original backed up"         grep -q '"bun"' "$CFG/plugin-backups/discord/$v/.mcp.json.bak-$(date +%Y%m%d)"
  check "helper $v: no .next left"              not test -e "$P/$v/.mcp.json.next"
done
check "helper: another plugin untouched"        test "$(<$CFG/plugins/cache/claude-plugins-official/other/1.0/.mcp.json)" = '{"keep":1}'
OUT="$(dc_ensure_launcher 2>&1)"
check "helper: second run prints nothing"       test -z "$OUT"
print -r -- 'changed by a plugin update' > "$CFG/plugin-backups/discord/0.0.7/.mcp.json.bak-$(date +%Y%m%d)"
print -r -- '{"mcpServers":{"discord":{"command":"bun","args":[]}}}' > "$P/0.0.7/.mcp.json"
dc_ensure_launcher >/dev/null
check "helper: an existing backup of the day is never overwritten" test "$(<$CFG/plugin-backups/discord/0.0.7/.mcp.json.bak-$(date +%Y%m%d))" = 'changed by a plugin update'
check "helper: a reverted .mcp.json is healed again" test "$(jq -r .mcpServers.discord.command "$P/0.0.7/.mcp.json")" = '${CLAUDE_PLUGIN_ROOT}/discord-mcp-launch'
# the launcher copied by the helper behaves like the repo's
R="$(print -r -- "$INIT" | env -u DISCORD_BOT_TOKEN DISCORD_STATE_DIR="$SD" "$P/0.0.8/discord-mcp-launch" "$P/0.0.8")"
check "helper: the installed copy runs the stub without a token" test "$(print -r -- "$R" | jq -r .result.serverInfo.name)" = discord-stub
# every failure path still exits 0
print -r -- 'not json' > "$P/0.0.8/.mcp.json"; chmod 444 "$P/0.0.8"
dc_ensure_launcher >/dev/null 2>&1; rc=$?; chmod 755 "$P/0.0.8"
check "helper: unwritable plugin dir: exit 0"   test $rc = 0
CLAUDE_CONFIG_DIR="$D/nowhere" dc_ensure_launcher >/dev/null 2>&1
check "helper: no plugin installed: exit 0"     test $? = 0
check "helper: TC_DISCORD_LAUNCHER=0 does nothing" test -z "$(TC_DISCORD_LAUNCHER=0 CLAUDE_CONFIG_DIR="$D/nowhere" dc_ensure_launcher 2>&1)"

tt_done
