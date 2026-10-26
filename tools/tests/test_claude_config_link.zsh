#!/usr/bin/env zsh
# Tests for bin/claude-config-link and bin/claude-config-sync. Every run uses HOME=<scratch>, never the real ~/.claude.
emulate -L zsh
repo="${0:A:h:h:h}"
LINK="$repo/bin/claude-config-link"; SYNC="$repo/bin/claude-config-sync"
TT_FAILS=0; stamp="$(date +%Y%m%d)"
ok()    { print -r -- "ok   - $1" }
fail()  { print -r -- "FAIL - $1"; (( TT_FAILS++ )) }
check() { if eval "$2"; then ok "$1"; else fail "$1"; fi }   # check <name> '<zsh condition>' (evaluated lazily)
real_before="$(ls -l ~/.claude/CLAUDE.md ~/.claude/settings.json 2>&1)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ccl.XXXXXX")"; tmp="${tmp:A}"
trap 'rm -rf "$tmp"' EXIT INT TERM
H="$tmp/h/.claude"; B="$H/backups/config-link-$stamp"   # backups go here, never beside the item
main="${$(git -C $repo rev-parse --path-format=absolute --git-common-dir):h}"   # where links must point

# scratch HOME with pre-existing regular files that the link must back up
mk_home() { rm -rf "$tmp/h"; mkdir -p "$H/hooks" "$H/skills/synced" "$H/agents"
  print old > "$H/CLAUDE.md"; print old > "$H/hooks/context-size-guard.sh"
  print '{"live":1}' > "$H/settings.json"; }

mk_home
HOME="$tmp/h" $LINK --dry-run >"$tmp/dry" 2>&1
check "dry-run prints at least 10 actions"      '(( $(wc -l < $tmp/dry) >= 10 ))'
check "dry-run changes nothing"                 '[[ ! -L $H/CLAUDE.md && ! -e $B/CLAUDE.md ]]'
check "dry-run reports the settings.json skip"  'grep -i skip $tmp/dry | grep -q settings.json'

HOME="$tmp/h" $LINK >"$tmp/out" 2>&1; rc=$?
check "real run exits 0"                        '[[ $rc == 0 ]]'
check "CLAUDE.md linked into repo"              '[[ $(readlink $H/CLAUDE.md) == $main/claude/CLAUDE.md ]]'
check "existing file backed up under backups/"  '[[ $(<$B/CLAUDE.md) == old && -z "$(print -l $H/**/*.bak-*(N))" ]]'
check "hook linked per file"                    '[[ $(readlink $H/hooks/context-size-guard.sh) == $main/claude/hooks/context-size-guard.sh ]]'
check "skill linked per directory"              '[[ $(readlink $H/skills/retro) == $main/claude/skills/retro ]]'
check "agents linked per file"                  '[[ -L $H/agents/effort-low.md ]]'
check "synced/ left alone"                      '[[ -d $H/skills/synced && ! -L $H/skills/synced ]]'
check "settings.json stays a regular file"      '[[ -f $H/settings.json && ! -L $H/settings.json ]]'
check "repo file not overwritten through link"  '[[ $(<$repo/claude/CLAUDE.md) != old ]]'

HOME="$tmp/h" $LINK >"$tmp/out2" 2>&1; rc=$?
check "rerun is a no-op and exits 0"            '[[ $rc == 0 ]] && ! grep -qE "^(link|backup)" $tmp/out2'

mk_home; rm "$H/CLAUDE.md"; ln -s /elsewhere "$H/CLAUDE.md"
HOME="$tmp/h" $LINK >"$tmp/out3" 2>&1; rc=$?
check "link pointing elsewhere is refused"      '[[ $rc == 1 && $(readlink $H/CLAUDE.md) == /elsewhere ]]'
check "other paths still linked after refusal"  '[[ -L $H/skills/retro ]]'

# existing backup is never clobbered; dir backups don't nest; dangling link refused; symlinked parent refused
mk_home; mkdir -p "$B"; print oldbak > "$B/CLAUDE.md"; mkdir -p "$H/skills/retro/x" "$B/skills/retro"; print d > "$H/skills/retro/x/f"
print keep > "$B/skills/retro/k"
HOME="$tmp/h" $LINK >"$tmp/out4" 2>&1; rc=$?
check "existing backup kept intact"             '[[ $(<$B/CLAUDE.md) == oldbak && $(<$B/CLAUDE.md.2) == old ]]'
check "dir backup gets a fresh name, not nested" '[[ $(<$B/skills/retro/k) == keep && ! -e $B/skills/retro/retro && -f $B/skills/retro.2/x/f ]]'
mk_home; mkdir -p "$B"; print oldbak > "$B/CLAUDE.md"; print b2 > "$B/CLAUDE.md.2"
HOME="$tmp/h" $LINK --dry-run >"$tmp/out5" 2>&1
check "dry-run names the free backup slot"      'grep -q "$B/CLAUDE.md.3" $tmp/out5 && [[ ! -L $H/CLAUDE.md ]]'
mk_home; rm "$H/CLAUDE.md"; ln -s /nonexistent-target "$H/CLAUDE.md"
HOME="$tmp/h" $LINK >"$tmp/out6" 2>&1; rc=$?
check "dangling link elsewhere refused, hint shown" '[[ $rc == 1 && $(readlink $H/CLAUDE.md) == /nonexistent-target ]] && grep -q "remove it" $tmp/out6'
mk_home; rm -rf "$H/hooks"; mkdir "$tmp/other"; ln -s "$tmp/other" "$H/hooks"
HOME="$tmp/h" $LINK >"$tmp/out7" 2>&1; rc=$?
check "symlinked hooks/ parent refused, nothing written through" '[[ $rc == 1 && -z "$(ls $tmp/other)" ]]'
check "other parents still linked"              '[[ -L $H/skills/retro ]]'

# sync: live settings.json -> repo copy, run from a scratch repo so the real one is untouched
mk_home; mkdir -p "$tmp/r/bin" "$tmp/r/claude"; cp "$SYNC" "$tmp/r/bin/" 2>/dev/null
HOME="$tmp/h" "$tmp/r/bin/claude-config-sync" >/dev/null 2>&1
check "sync copies live settings.json to repo"  '[[ $(<$tmp/r/claude/settings.json) == "{\"live\":1}" ]]'

check "real ~/.claude untouched"                '[[ $(ls -l ~/.claude/CLAUDE.md ~/.claude/settings.json 2>&1) == $real_before ]]'
if (( TT_FAILS == 0 )); then print "ALL PASS"; else print "$TT_FAILS FAILED"; exit 1; fi
