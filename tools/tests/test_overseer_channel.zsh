source "${0:A:h}/lib.zsh"
# claude-overseer and the ops bot's channel: with a token in <_ops>/.env the overseer's claude gets
# --channels plugin:discord@claude-plugins-official and DISCORD_STATE_DIR=<_ops dir>; without one argv and env are as before.
# Seam: a fake `claude` first on PATH records argv and the discord env to a file (claude-overseer's ab_path only prepends the repo bin, which has no claude).
O="${TC_OVERSEER_BIN:-$TT_REPO/bin/claude-overseer}"
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttovc.XXXXXX"):A}"
mkdir -p "$S/bin" "$S/home" "$S/state"
cat > "$S/bin/claude" <<STUB
#!/bin/sh
{ for a in "\$@"; do echo "ARG:\$a"; done; echo "DSD=\${DISCORD_STATE_DIR-UNSET}"; } > "$S/rec"
STUB
chmod +x "$S/bin/claude"
trap 'rm -rf "$S"; tt_teardown' EXIT INT TERM
export HOME="$S/home" TC_STATE="$S/state" PATH="$S/bin:$PATH"
unset DISCORD_STATE_DIR TC_DISCORD
OPS="$TC_STATE/discord/_ops"
go() { rm -f "$S/rec"; "$O" "$@" >/dev/null 2>&1; rc=$?; rec="$(<$S/rec)"; }

# no token at all
go
check "no token: claude ran, rc 0" test $rc -eq 0 -a -n "$rec"
check "no token: no --channels, DISCORD_STATE_DIR unset" test -z "$(print -r -- "$rec" | grep -x -e 'ARG:--channels')" -a "$(print -r -- "$rec" | grep '^DSD=')" = "DSD=UNSET"
base="$rec"
# a .env without a value is no token
mkdir -p $OPS; print -r -- 'DISCORD_BOT_TOKEN=' > $OPS/.env
go
check "empty token line: argv and env as without a token" test "$rec" = "$base"
# a project token alone does not count
mkdir -p "$TC_STATE/discord/proj"; print -r -- 'DISCORD_BOT_TOKEN=x.y' > "$TC_STATE/discord/proj/.env"
go
check "project token only: unchanged" test "$rec" = "$base"
# the ops token
print -r -- 'DISCORD_BOT_TOKEN=opstok.value' > $OPS/.env
go "a prompt"
check "token: --channels plugin:discord@claude-plugins-official added" test -n "$(print -r -- "$rec" | grep -x 'ARG:--channels')" -a -n "$(print -r -- "$rec" | grep -x 'ARG:plugin:discord@claude-plugins-official')"
check "token: --channels entry comes right after --channels" test "$(print -r -- "$rec" | grep -A1 -x 'ARG:--channels' | tail -1)" = "ARG:plugin:discord@claude-plugins-official"
check "token: DISCORD_STATE_DIR is the _ops dir" test "$(print -r -- "$rec" | grep '^DSD=')" = "DSD=$OPS"
check "token: the caller's prompt is still last, the overseer flags stay" test "$(print -r -- "$rec" | grep '^ARG:' | tail -1)" = "ARG:a prompt" -a -n "$(print -r -- "$rec" | grep -x 'ARG:--setting-sources')" -a -n "$(print -r -- "$rec" | grep -x 'ARG:project,local')"
check "token: argv minus the channels pair equals the no-token argv" test "$(print -r -- "$rec" | grep '^ARG:' | grep -v -x -e 'ARG:--channels' -e 'ARG:plugin:discord@claude-plugins-official' | grep -v -x 'ARG:a prompt')" = "$(print -r -- "$base" | grep '^ARG:')"
# the token never reaches argv or env of the fake
check "token: the token value is not in argv" test -z "$(grep -F opstok.value $S/rec)"
# kill switch
TC_DISCORD=0 go
check "TC_DISCORD=0: no channel even with a token" test "$rec" = "$base"
# an inherited DISCORD_STATE_DIR (a lead's) must not leak into a token-less overseer
rm -f $OPS/.env
DISCORD_STATE_DIR=/somewhere/else go
check "no token: an inherited DISCORD_STATE_DIR is dropped" test "$(print -r -- "$rec" | grep '^DSD=')" = "DSD=UNSET"
# the real state dir is never touched
check "scratch state only: no _ops dir under the real home" test ! -e "$S/home/.local/state/agent-board/discord"
# read-only rules
check "settings: the only discord allows are reply and fetch_messages (no access, react, edit, download, Bash, write)" test "$(jq -cS '[.permissions.allow[] | select(test("discord|access|Bash|Write|Edit"))] | map(select(test("^Bash\\(tmux-ctl overview|^Bash\\(git (log|status|show) ") | not)) | sort' $TT_REPO/claude/overseer-settings.json)" = '["mcp__plugin_discord_discord__fetch_messages","mcp__plugin_discord_discord__reply"]'
check "settings: enabledPlugins loads the discord plugin (the probe: it does not load under --setting-sources project,local otherwise)" test "$(jq -r '.enabledPlugins["discord@claude-plugins-official"]' $TT_REPO/claude/overseer-settings.json)" = true
check "overseer.md: names the discord reply tool, keeps the no-authority line" test -n "$(grep -iE 'discord.*reply|reply.*discord' $TT_REPO/claude/overseer.md)" -a -n "$(grep 'no authority' $TT_REPO/claude/overseer.md)"
tt_done
