#!/usr/bin/env zsh
# test_superpowers_hook.zsh — superpowers-hook.sh resolves the plugin without `find`
# when it can, and still falls back to `find` otherwise. Runs in a scratch $HOME
# with a `find` shim first on PATH; touches nothing outside the temp dir.
emulate -L zsh
source "${0:A:h}/lib.zsh"
HOOK="${0:A:h:h:h}/claude/hooks/superpowers-hook.sh"
NAME=stop-wait-guard.sh
REAL_FIND="$(command -v find)"

T="$(mktemp -d "${TMPDIR:-/tmp}/sphook.XXXXXX")"; T="${T:A}"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/shim"
cat > "$T/shim/find" <<SH
#!/bin/sh
echo "find \$*" >> "\$SHIM_LOG"
[ "\${SHIM_MODE:-deny}" = pass ] && exec "$REAL_FIND" "\$@"
exit 99
SH
chmod +x "$T/shim/find"

# mkplugin <root> <marker> [plugin-name]: a fake plugin whose hook prints <marker>
mkplugin() {
  mkdir -p "$1/hooks/examples" "$1/.claude-plugin"
  print -r -- "{\"name\": \"${3:-superpowers-extended-cc}\", \"version\": \"x\"}" > "$1/.claude-plugin/plugin.json"
  print -r -- "#!/usr/bin/env bash"$'\n'"echo $2" > "$1/hooks/examples/$NAME"
}
# run_hook <home> [mode]: prints hook stdout; find calls land in $T/find.log
run_hook() {
  : > "$T/find.log"
  HOME="$1" SHIM_LOG="$T/find.log" SHIM_MODE="${2:-deny}" PATH="$T/shim:$PATH" \
    SUPERPOWERS_PLUGIN_ROOT="${3:-}" bash "$HOOK" "$NAME" </dev/null 2>/dev/null
}
no_find() { [[ ! -s "$T/find.log" ]] }
did_find() { [[ -s "$T/find.log" ]] }

# 1. cache install, several versions: newest by version order wins, no find
H1="$T/h1"; C="$H1/.claude/plugins/cache/mk/superpowers-extended-cc"
mkplugin "$C/1.9.0" v1.9.0; mkplugin "$C/1.10.0" v1.10.0; mkplugin "$C/6.5.3-dev" v6.5.3-dev
out="$(run_hook $H1)"
check "cache: newest version is run"            [ "$out" = v6.5.3-dev ]
check "cache: find not called"                  no_find
H1b="$T/h1b"; C="$H1b/.claude/plugins/cache/mk/superpowers-extended-cc"
mkplugin "$C/1.9.0" v1.9.0; mkplugin "$C/1.10.0" v1.10.0
check "cache: 1.10.0 beats 1.9.0 (version order, not text)" [ "$(run_hook $H1b)" = v1.10.0 ]

# 2. marketplace checkout only
H2="$T/h2"; mkplugin "$H2/.claude/plugins/marketplaces/mk" vmarket
check "marketplace: hook is run"                [ "$(run_hook $H2)" = vmarket ]
check "marketplace: find not called"            no_find

# 3. env var wins, no find
H3="$T/h3"; mkplugin "$T/envroot" venv; mkplugin "$H3/.claude/plugins/marketplaces/mk" vmarket
check "env var: hook is run"                    [ "$(run_hook $H3 deny $T/envroot)" = venv ]
check "env var: find not called"                no_find

# 4. a glob hit that names another plugin is rejected; fallback finds the right one
H4="$T/h4"; mkplugin "$H4/.claude/plugins/marketplaces/other" vwrong other-plugin
mkplugin "$H4/Library/Application Support/Claude/plugin_abc" vdesktop
check "fallback: wrong-name glob hit skipped, find locates desktop copy" [ "$(run_hook $H4 pass)" = vdesktop ]
check "fallback: find was called"               did_find

# 5. nothing installed: silent exit 0
H5="$T/h5"; mkdir -p "$H5"
out="$(run_hook $H5 pass)"; rc=$?
check "none installed: no output, exit 0"       [ -z "$out" -a $rc -eq 0 ]

tt_done
