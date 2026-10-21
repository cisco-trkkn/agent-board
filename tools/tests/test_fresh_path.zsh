# test_fresh_path.zsh — a fresh install links only ~/.local/bin/agent-board: <repo>/bin is not on PATH and
# ~/.local/bin/tmux does not exist (tmux comes from PATH, e.g. brew). The tools must still find their own helpers.
# Isolation: scratch HOME, scratch TMUX_TMPDIR, tmux servers on scratch sockets started with -f (never the user's).
source "${0:A:h}/lib.zsh"
R="$TT_REPO"; RES="$R/bin/_tc_bins.zsh"
SCR="$(mktemp -d "${TMPDIR:-/tmp}/freshp.XXXXXX")"; SCR="${SCR:A}"
H="$SCR/home"; BREW="$SCR/brewbin"; mkdir -p "$H" "$BREW"
export TMUX_TMPDIR="$SCR/tmpdir"; mkdir -p "$TMUX_TMPDIR"
REALTMUX="${TT_BIN:A}"; ln -s "$REALTMUX" "$BREW/tmux"
SOCK="fp-$$-$RANDOM"
cleanup() { "$REALTMUX" -L "$SOCK" kill-server 2>/dev/null; rm -rf "$SCR" }
trap cleanup EXIT INT TERM
unset TMUX TMUX_PANE TC_TMUX TMUX_DASH_TMUX_ARGS DEV_CLAUDE_CMD DEV_NO_ATTACH DEV_CLIENT AGENT_BOARD_REPO
CLEAN=/usr/bin:/bin     # a PATH without <repo>/bin, ~/.local/bin and the micromamba tmux
fresh() { env -u TC_TMUX HOME="$H" PATH="$BREW:$CLEAN" "$@" }

# --- finding 2: the tmux binary is TC_TMUX, else ~/.local/bin/tmux if executable, else tmux on PATH
ZRES='source "$1"; print -r -- "$TC_TMUX_CMD[1]"'
check "zsh: no ~/.local/bin/tmux → tmux from PATH" test "$(fresh zsh -f -c "$ZRES" _ "$RES")" = "$BREW/tmux"
mkdir -p "$H/.local/bin"; print -r -- '#!/bin/sh' > "$H/.local/bin/tmux"; chmod +x "$H/.local/bin/tmux"
check "zsh: executable ~/.local/bin/tmux wins over PATH" test "$(fresh zsh -f -c "$ZRES" _ "$RES")" = "$H/.local/bin/tmux"
check "zsh: TC_TMUX wins over both" test "$(env HOME="$H" PATH="$BREW:$CLEAN" TC_TMUX=/x/tmux zsh -f -c "$ZRES" _ "$RES")" = /x/tmux
rm "$H/.local/bin/tmux"
PYT='import sys; sys.path.insert(0, sys.argv[1]); import paneclass; paneclass.RESOLVER = "/nonexistent"; print(paneclass.tmux_cmd()[0])'
check "python fallback: no ~/.local/bin/tmux → tmux from PATH" test "$(fresh python3 -I -c "$PYT" "$R/board")" = "$BREW/tmux"
print -r -- '#!/bin/sh' > "$H/.local/bin/tmux"; chmod +x "$H/.local/bin/tmux"
check "python fallback: executable ~/.local/bin/tmux wins" test "$(fresh python3 -I -c "$PYT" "$R/board")" = "$H/.local/bin/tmux"
check "python fallback: TC_TMUX wins" test "$(env HOME="$H" PATH="$BREW:$CLEAN" TC_TMUX=/x/tmux python3 -I -c "$PYT" "$R/board")" = /x/tmux
rm "$H/.local/bin/tmux"

# --- finding 2, plugin scripts copied away from their repo (no resolver to source): same order, own tmux first
for scr in artifact-register bash-mirror; do
  CP="$SCR/copy-$scr/a/b/c"; mkdir -p "$CP"; cp "$R/claude/plugin/scripts/$scr.sh" "$CP/"
  LB="$SCR/lb-$scr"; mkdir -p "$LB/.local/bin" "$SCR/pb-$scr"
  for w in "$LB/.local/bin/tmux:local" "$SCR/pb-$scr/tmux:path"; do
    print -r -- "#!/bin/sh
echo ${w#*:} > $SCR/which-$scr
echo proj" > "${w%%:*}"; chmod +x "${w%%:*}"
  done
  rm -f "$SCR/which-$scr"
  print -r -- '{"tool_name":"Bash","tool_input":{"command":"true"}}' | env -u TC_TMUX HOME="$LB" PATH="$SCR/pb-$scr:$CLEAN" TMUX=/x/sock,1,0 TMUX_PANE=%1 TC_STATE="$SCR/st" zsh -f "$CP/$scr.sh" --path "$SCR/none.md" >/dev/null 2>&1
  check "$scr (copied away): ~/.local/bin/tmux beats the PATH one" test "$(cat "$SCR/which-$scr" 2>/dev/null)" = local
done

# --- finding 1: dev types the lead's launcher by absolute path
STUBD="$SCR/stub"; mkdir -p "$STUBD"
print -r -- '#!/bin/sh
echo "$@" > "$FP_MARK"' > "$BREW/claude"; chmod +x "$BREW/claude"
export FP_MARK="$SCR/claude-ran"
proj="$SCR/proj"; mkdir -p "$proj"; git -C "$proj" init -q
fresh env AGENT_BOARD_TMUX_SOCKET="$SOCK" DEV_NO_ATTACH=1 TC_LAYOUT=/usr/bin/true "$R/bin/dev" "$proj" >/dev/null 2>&1
check "dev: the lead window started claude-orchestrator (claude stub ran)" tt_wait 10 test -s "$FP_MARK"
# the typed word is not on PATH, so it must be an absolute path
"$REALTMUX" -L "$SOCK" kill-server 2>/dev/null
tt_done
