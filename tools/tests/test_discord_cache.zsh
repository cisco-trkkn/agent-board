source "${0:A:h}/lib.zsh"
# Discord failure-cache clear: tools/discord_cache.py drops plugin:discord:discord from the MCP failure cache.
# Scratch CLAUDE_CONFIG_DIR and HOME only.
tt_setup claude
RT="$TT_DIR/home"; mkdir -p "$RT"
CFG="$TT_DIR/cfg"; mkdir -p "$CFG"
not() { ! "$@" }
CACHE="$CFG/mcp-needs-auth-cache.json"
HELPER="$TT_REPO/tools/discord_cache.py"
KEY='plugin:discord:discord'
seed() { print -r -- '{"plugin:gitlab:gitlab":{"timestamp":1},"plugin:discord:discord":{"timestamp":2,"id":"abc"}}' > "$CACHE" }
haskey() { jq -e --arg k "$1" 'has($k)' "$CACHE" >/dev/null 2>&1 }
# --- part 2a: the helper
seed
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear; rc=$?
check "helper: exit 0"                     test $rc = 0
check "helper: discord key removed"       not haskey "$KEY"
check "helper: other key kept"             haskey plugin:gitlab:gitlab
check "helper: other key value intact"     test "$(jq -c '.["plugin:gitlab:gitlab"]' "$CACHE")" = '{"timestamp":1}'
check "helper: no temp file left"          test "$(ls -A $CFG | grep -c tmp)" = 0
rm -f "$CACHE"
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear; rc=$?
check "helper: missing file: exit 0"       test $rc = 0
check "helper: missing file: not created"  not test -e "$CACHE"
print -r -- 'not json{' > "$CACHE"
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear; rc=$?
check "helper: bad JSON: exit 0"           test $rc = 0
check "helper: bad JSON: file untouched"   test "$(<$CACHE)" = 'not json{'
print -r -- '[1,2]' > "$CACHE"
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear; rc=$?
check "helper: non-object JSON: exit 0"    test $rc = 0
check "helper: non-object JSON untouched"  test "$(<$CACHE)" = '[1,2]'
print -r -- '{"plugin:gitlab:gitlab":{"timestamp":1}}' > "$CACHE"; touch -t 202001010000 "$CACHE"
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear
check "helper: key absent: file not rewritten" test "$(stat -c %Y "$CACHE" 2>/dev/null || stat -f %m "$CACHE")" -lt 1600000000
# default dir: HOME/.claude when CLAUDE_CONFIG_DIR is unset
mkdir -p "$RT/.claude"; print -r -- '{"plugin:discord:discord":{"timestamp":2}}' > "$RT/.claude/mcp-needs-auth-cache.json"
env -u CLAUDE_CONFIG_DIR HOME="$RT" python3 "$HELPER" clear
check "helper: default dir is HOME/.claude" test "$(<$RT/.claude/mcp-needs-auth-cache.json)" = '{}'

tt_done
