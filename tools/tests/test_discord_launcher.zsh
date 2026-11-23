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
echo "bun $1" >> "'"$D"'/calls.log"
if [ "$1" = install ]; then { echo "BUN"; for a in "$@"; do echo "$a"; done; pwd; } > "'"$D"'/bun-install.argv"; echo INSTALL-STDOUT; exit ${FAKE_BUN_RC:-0}; fi
{ echo "BUN"; for a in "$@"; do echo "$a"; done; } > "'"$D"'/bun.argv"
if [ -n "$DISCORD_BOT_TOKEN" ]; then echo "REAL-SERVER token"; else echo "REAL-SERVER notoken"; fi' > "$FB/bun"; chmod +x "$FB/bun"
# a fake node (first on PATH only in the token cases): version from FAKE_NODE_VER, records argv and cwd
FN="$D/fakenode"; mkdir -p "$FN"
print -r -- '#!/bin/sh
if [ "$1" = --version ]; then echo "$FAKE_NODE_VER"; exit 0; fi
echo "node" >> "'"$D"'/calls.log"
{ echo "NODE"; for a in "$@"; do echo "$a"; done; pwd; } > "'"$D"'/node.argv"
if [ -n "$DISCORD_BOT_TOKEN" ]; then echo "NODE-SERVER token"; else echo "NODE-SERVER notoken"; fi' > "$FN/node"; chmod +x "$FN/node"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}'
launch() { env -u DISCORD_BOT_TOKEN -u DISCORD_STATE_DIR -u TC_DISCORD_RUNTIME PATH="$FB:$PATH" "$@" "$ROOT/discord-mcp-launch" "$ROOT" }
# launchn: like launch, with the fake node (version $FAKE_NODE_VER, default v22.13.1) ahead of the real one
launchn() { env -u DISCORD_BOT_TOKEN -u DISCORD_STATE_DIR -u TC_DISCORD_RUNTIME FAKE_NODE_VER="${FAKE_NODE_VER:-v22.13.1}" PATH="$FN:$FB:$PATH" "$@" "$ROOT/discord-mcp-launch" "$ROOT" }
SD="$D/state"; mkdir -p "$SD"
rm -f "$D/bun.argv"
R="$(print -r -- "$INIT" | launch DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: no token runs the stub"       test "$(print -r -- "$R" | jq -r .result.serverInfo.name 2>/dev/null)" = discord-stub
check "launcher: no token does not run bun"    not test -e "$D/bun.argv"
print -r -- 'DISCORD_BOT_TOKEN=' > "$SD/.env"
R="$(print -r -- "$INIT" | launch DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: an empty token runs the stub" test "$(print -r -- "$R" | jq -r .result.serverInfo.name 2>/dev/null)" = discord-stub
# with a token and node >= 22.6: bun install in the root (stdout kept off MCP stdio), then node runs server.ts from the root
print -r -- 'DISCORD_BOT_TOKEN=abc.def.ghi' > "$SD/.env"
rm -f "$D/bun.argv" "$D/bun-install.argv" "$D/node.argv" "$D/calls.log"
R="$(print -r -- "$INIT" | launchn DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG" 2>"$D/err")"
check "launcher: token in the state dir runs the server under node" test "$R" = "NODE-SERVER notoken"
check "launcher: node argv strips types and runs server.ts" test "$(sed '$d' "$D/node.argv" | tr '\n' ' ')" = "NODE --experimental-strip-types $ROOT/server.ts "
check "launcher: node runs with the plugin root as cwd" test "$(tail -n 1 "$D/node.argv")" = "$ROOT:A"
check "launcher: bun install --no-summary ran in the root" test "$(sed '$d' "$D/bun-install.argv" | tr '\n' ' ')" = "BUN install --no-summary "
check "launcher: bun install cwd is the plugin root" test "$(tail -n 1 "$D/bun-install.argv")" = "$ROOT:A"
check "launcher: install runs before node, and bun never runs the server" test "$(tr '\n' ',' < "$D/calls.log")" = "bun install,node,"
check "launcher: install output goes to stderr, not MCP stdout" grep -q INSTALL-STDOUT "$D/err"
rm -f "$D/bun.argv" "$D/bun-install.argv" "$D/node.argv" "$D/calls.log"
R="$(print -r -- "$INIT" | launchn DISCORD_BOT_TOKEN=1:x DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG" 2>/dev/null)"
check "launcher: token in the environment runs node" test "$R" = "NODE-SERVER token"
FAKE_NODE_VER=v22.6.0; R="$(print -r -- "$INIT" | launchn DISCORD_BOT_TOKEN=1:x DISCORD_STATE_DIR="$SD" 2>/dev/null)"
check "launcher: node 22.6.0 is the minimum and runs node" test "$R" = "NODE-SERVER token"
FAKE_NODE_VER=v24.1.0; R="$(print -r -- "$INIT" | launchn DISCORD_BOT_TOKEN=1:x DISCORD_STATE_DIR="$SD" 2>/dev/null)"
check "launcher: node 24 runs node" test "$R" = "NODE-SERVER token"
# old node: the stock bun line
for v in v22.5.9 v20.11.0 v8.0.0; do
  rm -f "$D/bun.argv" "$D/node.argv"
  FAKE_NODE_VER=$v; R="$(print -r -- "$INIT" | launchn DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG" 2>/dev/null)"
  check "launcher: node $v is too old, runs stock bun" test "$R" = "REAL-SERVER notoken"
  check "launcher: node $v: bun argv is the stock start command" test "$(tr '\n' ' ' < "$D/bun.argv")" = "BUN run --cwd $ROOT --shell=bun --silent start "
  check "launcher: node $v: node never ran the server" not test -e "$D/node.argv"
done
# a version without a minor, or garbage, is not trusted: stock bun
for v in v22 garbage; do
  rm -f "$D/bun.argv" "$D/node.argv"
  FAKE_NODE_VER=$v; R="$(print -r -- "$INIT" | launchn DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG" 2>/dev/null)"
  check "launcher: node version '$v' is not trusted, runs stock bun" test "$R" = "REAL-SERVER notoken"
  check "launcher: node version '$v': node never ran the server" not test -e "$D/node.argv"
done
unset FAKE_NODE_VER
# a failed bun install is not fatal: one stderr line, then node starts (node_modules may exist)
rm -f "$D/node.argv"
R="$(print -r -- "$INIT" | launchn FAKE_BUN_RC=7 DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG" 2>"$D/err")"
check "launcher: failed install still starts node" test "$R" = "NODE-SERVER notoken"
check "launcher: failed install says so on stderr" grep -qxF 'discord-mcp-launch: bun install failed (rc=7); starting with existing node_modules' "$D/err"
R="$(print -r -- "$INIT" | launchn DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG" 2>"$D/err")"
check "launcher: a good install prints no failure line" not grep -q 'install failed' "$D/err"
# the escape hatch
rm -f "$D/bun.argv" "$D/node.argv"
R="$(print -r -- "$INIT" | launchn TC_DISCORD_RUNTIME=bun DISCORD_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG" 2>/dev/null)"
check "launcher: TC_DISCORD_RUNTIME=bun runs stock bun" test "$R" = "REAL-SERVER notoken"
check "launcher: TC_DISCORD_RUNTIME=bun argv" test "$(tr '\n' ' ' < "$D/bun.argv")" = "BUN run --cwd $ROOT --shell=bun --silent start "
check "launcher: TC_DISCORD_RUNTIME=bun: node never ran" not test -e "$D/node.argv"
# the default state dir
rm -f "$SD/.env"
mkdir -p "$CFG/channels/discord"; print -r -- 'DISCORD_BOT_TOKEN=9:y' > "$CFG/channels/discord/.env"
R="$(print -r -- "$INIT" | launchn CLAUDE_CONFIG_DIR="$CFG" 2>/dev/null)"
check "launcher: default state dir is CLAUDE_CONFIG_DIR/channels/discord" test "$R" = "NODE-SERVER notoken"
rm -rf "$CFG/channels"
# a token but no node at all: stock bun
NB0="$D/nonode0"; mkdir -p "$NB0"; ln -sf "$(command -v grep)" "$NB0/grep"
print -r -- '#!/bin/sh
echo "BUN-ONLY $*"' > "$NB0/bun"; chmod +x "$NB0/bun"
R="$(env -u DISCORD_BOT_TOKEN -u TC_DISCORD_RUNTIME DISCORD_BOT_TOKEN=1:x PATH="$NB0" /bin/sh "$ROOT/discord-mcp-launch" "$ROOT")"
check "launcher: token, no node: bun runs the stock start" test "$R" = "BUN-ONLY run --cwd $ROOT --shell=bun --silent start"
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
