source "${0:A:h}/lib.zsh"
# Telegram part 1: sessions without a token must not fail. claude/plugin/scripts/telegram-mcp-launch runs the real
# server when a token exists and a do-nothing MCP stub otherwise; tg_ensure_launcher points the plugin's .mcp.json at it.
# Scratch only: a scratch CLAUDE_CONFIG_DIR, fake plugin dirs, a fake server.ts, a fake token.
TT_NOTMUX=1
tt_setup claude
if (( ! $+commands[node] )); then print "skip - no node"; tt_done; exit 0; fi
not() { ! "$@" }
D="$TT_DIR"; CFG="$D/cfg"; mkdir -p "$CFG"
LAUNCH="$TT_REPO/claude/plugin/scripts/telegram-mcp-launch"
STUBJS="$TT_REPO/claude/plugin/scripts/telegram-mcp-stub.js"

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
check "stub: initialize names a server"        test "$(print -r -- "$OUT" | jq -r 'select(.id==1) | .result.serverInfo.name')" = telegram-stub
check "stub: advertises only tools"            test "$(print -r -- "$OUT" | jq -cS 'select(.id==1) | .result.capabilities')" = '{"tools":{}}'
check "stub: tools/list is empty"              test "$(print -r -- "$OUT" | jq -c 'select(.id==2) | .result.tools')" = '[]'
check "stub: prompts/list is empty"            test "$(print -r -- "$OUT" | jq -c 'select(.id==3) | .result.prompts')" = '[]'
check "stub: resources/list is empty"          test "$(print -r -- "$OUT" | jq -c 'select(.id==4) | .result.resources')" = '[]'
check "stub: ping answered"                    test "$(print -r -- "$OUT" | jq -c 'select(.id==5) | .result')" = '{}'
check "stub: unknown method is -32601"         test "$(print -r -- "$OUT" | jq -r 'select(.id==6) | .error.code')" = -32601
check "stub: no reply to a notification"       test "$(print -r -- "$OUT" | jq -s 'length')" = 6

# --- the launcher: a fake plugin root whose server.ts only says it ran
ROOT="$D/plugin"; mkdir -p "$ROOT"
print -r -- "console.log('REAL-SERVER ' + (process.env.TELEGRAM_BOT_TOKEN ? 'token' : 'notoken'))" > "$ROOT/server.ts"
cp "$STUBJS" "$ROOT/"; cp "$LAUNCH" "$ROOT/"; chmod +x "$ROOT/telegram-mcp-launch"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}'
launch() { env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_STATE_DIR "$@" "$ROOT/telegram-mcp-launch" "$ROOT" }
SD="$D/state"; mkdir -p "$SD"
R="$(print -r -- "$INIT" | launch TELEGRAM_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: no token runs the stub"       test "$(print -r -- "$R" | jq -r .result.serverInfo.name 2>/dev/null)" = telegram-stub
print -r -- 'TELEGRAM_BOT_TOKEN=' > "$SD/.env"
R="$(print -r -- "$INIT" | launch TELEGRAM_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: an empty token runs the stub" test "$(print -r -- "$R" | jq -r .result.serverInfo.name 2>/dev/null)" = telegram-stub
print -r -- 'TELEGRAM_BOT_TOKEN=123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' > "$SD/.env"
R="$(print -r -- "$INIT" | launch TELEGRAM_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: token in the state dir runs the real server" test "$R" = "REAL-SERVER notoken"
rm -f "$SD/.env"
R="$(print -r -- "$INIT" | launch TELEGRAM_BOT_TOKEN=1:x TELEGRAM_STATE_DIR="$SD" CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: token in the environment runs the real server" test "$R" = "REAL-SERVER token"
mkdir -p "$CFG/channels/telegram"; print -r -- 'TELEGRAM_BOT_TOKEN=9:y' > "$CFG/channels/telegram/.env"
R="$(print -r -- "$INIT" | launch CLAUDE_CONFIG_DIR="$CFG")"
check "launcher: default state dir is CLAUDE_CONFIG_DIR/channels/telegram" test "$R" = "REAL-SERVER notoken"
rm -rf "$CFG/channels"

# --- --has-token <dir>: the one definition of "has a token" (the orchestrator opts a lead in with it)
rm -rf "$SD"; mkdir -p "$SD"
check "has-token: no .env"                      not "$LAUNCH" --has-token "$SD"
: > "$SD/.env";                                  check "has-token: empty .env"    not "$LAUNCH" --has-token "$SD"
print -r -- 'TELEGRAM_BOT_TOKEN=' > "$SD/.env"; check "has-token: empty value"    not "$LAUNCH" --has-token "$SD"
print -r -- '# TELEGRAM_BOT_TOKEN=1:x' > "$SD/.env"; check "has-token: commented out" not "$LAUNCH" --has-token "$SD"
print -r -- 'TELEGRAM_BOT_TOKEN=1:x' > "$SD/.env"; check "has-token: a value"      "$LAUNCH" --has-token "$SD"
check "has-token: prints nothing and starts no server" test -z "$("$LAUNCH" --has-token "$SD" 2>&1)"
rm -rf "$SD"; mkdir -p "$SD"

# --- the helper: heal every installed version's .mcp.json
source "$TT_REPO/tools/lib/telegram-launch.zsh"
P="$CFG/plugins/cache/claude-plugins-official/telegram"
for v in 0.0.7 0.0.8; do mkdir -p "$P/$v"; cp "$TT_DIR/plugin/server.ts" "$P/$v/server.ts"
  print -r -- '{"mcpServers":{"telegram":{"command":"bun","args":["run","--cwd","${CLAUDE_PLUGIN_ROOT}","--shell=bun","--silent","start"]}}}' > "$P/$v/.mcp.json"; done
mkdir -p "$CFG/plugins/cache/claude-plugins-official/other/1.0"; print -r -- '{"keep":1}' > "$CFG/plugins/cache/claude-plugins-official/other/1.0/.mcp.json"
export CLAUDE_CONFIG_DIR="$CFG"
OUT="$(tg_ensure_launcher 2>&1)"; rc=$?
check "helper: exit 0"                          test $rc = 0
check "helper: reports each version"            test "$(print -r -- "$OUT" | grep -c 'telegram: plugin launcher')" = 2
for v in 0.0.7 0.0.8; do
  check "helper $v: command is the launcher"    test "$(jq -r .mcpServers.telegram.command "$P/$v/.mcp.json")" = '${CLAUDE_PLUGIN_ROOT}/telegram-mcp-launch'
  check "helper $v: arg is the plugin root"     test "$(jq -c .mcpServers.telegram.args "$P/$v/.mcp.json")" = '["${CLAUDE_PLUGIN_ROOT}"]'
  check "helper $v: launcher copied, executable" test -x "$P/$v/telegram-mcp-launch"
  check "helper $v: stub copied"                test -f "$P/$v/telegram-mcp-stub.js"
  check "helper $v: original backed up"         grep -q '"bun"' "$CFG/plugin-backups/telegram/$v/.mcp.json.bak-$(date +%Y%m%d)"
  check "helper $v: no .next left"              not test -e "$P/$v/.mcp.json.next"
done
check "helper: another plugin untouched"        test "$(<$CFG/plugins/cache/claude-plugins-official/other/1.0/.mcp.json)" = '{"keep":1}'
OUT="$(tg_ensure_launcher 2>&1)"
check "helper: second run prints nothing"       test -z "$OUT"
print -r -- 'changed by a plugin update' > "$CFG/plugin-backups/telegram/0.0.7/.mcp.json.bak-$(date +%Y%m%d)"
print -r -- '{"mcpServers":{"telegram":{"command":"bun","args":[]}}}' > "$P/0.0.7/.mcp.json"
tg_ensure_launcher >/dev/null
check "helper: an existing backup of the day is never overwritten" test "$(<$CFG/plugin-backups/telegram/0.0.7/.mcp.json.bak-$(date +%Y%m%d))" = 'changed by a plugin update'
check "helper: a reverted .mcp.json is healed again" test "$(jq -r .mcpServers.telegram.command "$P/0.0.7/.mcp.json")" = '${CLAUDE_PLUGIN_ROOT}/telegram-mcp-launch'
# the launcher copied by the helper behaves like the repo's
R="$(print -r -- "$INIT" | env -u TELEGRAM_BOT_TOKEN TELEGRAM_STATE_DIR="$SD" "$P/0.0.8/telegram-mcp-launch" "$P/0.0.8")"
check "helper: the installed copy runs the stub without a token" test "$(print -r -- "$R" | jq -r .result.serverInfo.name)" = telegram-stub
# every failure path still exits 0
print -r -- 'not json' > "$P/0.0.8/.mcp.json"; chmod 444 "$P/0.0.8"
tg_ensure_launcher >/dev/null 2>&1; rc=$?; chmod 755 "$P/0.0.8"
check "helper: unwritable plugin dir: exit 0"   test $rc = 0
CLAUDE_CONFIG_DIR="$D/nowhere" tg_ensure_launcher >/dev/null 2>&1
check "helper: no plugin installed: exit 0"     test $? = 0
check "helper: TC_TELEGRAM_LAUNCHER=0 does nothing" test -z "$(TC_TELEGRAM_LAUNCHER=0 CLAUDE_CONFIG_DIR="$D/nowhere" tg_ensure_launcher 2>&1)"

# --- bin/claude-orchestrator heals the launcher before it execs claude, with or without a token
STUB="$D/stub"; mkdir -p "$STUB" "$D/home"
print -r -- '#!/bin/zsh
print -rl -- "$@" > '"$D"'/argv' > "$STUB/claude"; chmod +x "$STUB/claude"
print -r -- '{"mcpServers":{"telegram":{"command":"bun","args":[]}}}' > "$P/0.0.7/.mcp.json"
rm -f "$D/argv"
env HOME="$D/home" CLAUDE_CONFIG_DIR="$CFG" PATH="$STUB:$PATH" "$TT_REPO/bin/claude-orchestrator" >/dev/null 2>&1
check "orchestrator, no token: claude still started"   test -s "$D/argv"
check "orchestrator, no token: .mcp.json healed"       test "$(jq -r .mcpServers.telegram.command "$P/0.0.7/.mcp.json")" = '${CLAUDE_PLUGIN_ROOT}/telegram-mcp-launch'
print -r -- '{"mcpServers":{"telegram":{"command":"bun","args":[]}}}' > "$P/0.0.7/.mcp.json"; rm -f "$D/argv"
mkdir -p "$TC_STATE/telegram/tt"; print -r -- "TELEGRAM_BOT_TOKEN=1:x" > "$TC_STATE/telegram/tt/.env"
env HOME="$D/home" CLAUDE_CONFIG_DIR="$CFG" PATH="$STUB:$PATH" "$TT_REPO/bin/claude-orchestrator" >/dev/null 2>&1
check "orchestrator, token: .mcp.json healed"          test "$(jq -r .mcpServers.telegram.command "$P/0.0.7/.mcp.json")" = '${CLAUDE_PLUGIN_ROOT}/telegram-mcp-launch'
print -r -- '{"mcpServers":{"telegram":{"command":"bun","args":[]}}}' > "$P/0.0.7/.mcp.json"; rm -f "$D/argv"
env HOME="$D/home" CLAUDE_CONFIG_DIR="$CFG" PATH="$STUB:$PATH" TC_TELEGRAM_LAUNCHER=0 "$TT_REPO/bin/claude-orchestrator" >/dev/null 2>&1
check "orchestrator, TC_TELEGRAM_LAUNCHER=0: untouched" test "$(jq -r .mcpServers.telegram.command "$P/0.0.7/.mcp.json")" = bun
check "orchestrator, TC_TELEGRAM_LAUNCHER=0: claude still started" test -s "$D/argv"
tt_done
