#!/usr/bin/env zsh
# install.sh — set up agent-board from this checkout.
#
#   ./install.sh                  link ~/.local/bin/agent-board to this checkout's bin/agent-board (the only thing it installs)
#   ./install.sh --check          list the dependencies: "ok <path>" or "MISSING <name>"; exit 1 if any is missing
#   ./install.sh --uninstall      remove ~/.local/bin/agent-board, if it links into this checkout
#   ./install.sh --migrate        install, then retire the old global setup (the author's pre-plugin install):
#                                   - the 3 hooks in ~/.claude/settings.json, the hook and rules links in ~/.claude
#                                   - the 10 old links in ~/.local/bin that point into this checkout
#                                   - the agent-board hook and 3 bindings in ~/.tmux.conf (config/tmux.conf has them)
#                                   - the global tmux-orchestrator and handoff skills and the effort-* agents, which the
#                                     plugin now ships (moved to ~/.local/state/agent-board/migrated-YYYYMMDD/)
#                                 settings.json and .tmux.conf are backed up to *.bak-YYYYMMDD first.
#
# Options: --dry-run (print the plan, change nothing), --force-relink (repoint a link into another checkout),
#          --keep-agents (with --migrate: leave ~/.claude/agents/effort-*.md), --migrate-team-settings (with --migrate:
#          also drop env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS and teammateMode), --repo DIR (treat DIR as the checkout).
# Outside --migrate nothing under ~/.claude is written.
emulate -L zsh
HERE="${0:A:h}"
REPO="$HERE"
LIB="$HERE/tools/install_lib.py"
mode=install DRY=0 FORCE=0 KEEP_AGENTS=0 TEAM=0
while (( $# )); do
  case "$1" in
    --check|--uninstall|--migrate) mode="${1#--}" ;;
    --dry-run) DRY=1 ;;
    --force-relink) FORCE=1 ;;
    --keep-agents) KEEP_AGENTS=1 ;;
    --migrate-team-settings) TEAM=1 ;;
    --repo) [[ -n "$2" ]] || { print -u2 "install.sh: --repo needs a directory"; exit 2 }; REPO="$2"; shift ;;
    -h|--help) sed -n '2,17p' "${0:A}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) print -u2 "install.sh: unknown option $1 (see --help)"; exit 2 ;;
  esac
  shift
done
REPO="${REPO:A}"
LINK="$HOME/.local/bin/agent-board"
STATE="$HOME/.local/state/agent-board"
STAMP="$(date +%Y%m%d)"
rc=0

run_or_print() { if (( DRY )); then print -r -- "  would: ${(j: :)${(q-)@}}"; else "$@"; fi }
say() { if (( DRY )); then print -r -- "would $1"; else print -r -- "$2"; fi }   # say "<plan>" "<done>"
link_target() {   # absolute, normalised target of a symlink (even a dangling one)
  local l="$1" t; t="$(readlink "$l")"; [[ "$t" == /* ]] || t="${l:h}/$t"; print -r -- "${t:A}"
}
points_into_repo() { [[ -L "$1" && "$(link_target "$1")" == "$REPO"/* ]] }

# --- --check
check_deps() {
  local miss=0 n p v
  for n in zsh tmux ttyd fzf; do
    p="$(command -v $n)" && print -r -- "ok $p" || { print "MISSING $n"; miss=1 }
  done
  if p="$(command -v python3)" && python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null
  then print -r -- "ok $p"; else print "MISSING python3 (needs >= 3.9)"; miss=1; fi
  for n in jq git; do p="$(command -v $n)" && print -r -- "ok $p" || { print "MISSING $n"; miss=1 }; done
  if p="$(command -v claude)"; then
    v="$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    local help; help="$(claude --help 2>&1)"
    local -a vv; vv=("${(@s:.:)v}")
    if [[ -n "$v" ]] && (( vv[1] * 1000000 + vv[2] * 1000 + vv[3] >= 2001303 )) \
       && [[ "$help" == *--settings* && "$help" == *--plugin-dir* ]]
    then print -r -- "ok $p"
    else print "MISSING claude (needs >= 2.1.303 with --settings and --plugin-dir; found ${v:-no version})"; miss=1; fi
  else print "MISSING claude"; miss=1; fi
  return $miss
}

# --- install / uninstall
do_install() {
  local want="$REPO/bin/agent-board" cur
  if [[ -L "$LINK" ]]; then
    cur="$(link_target "$LINK")"
    if [[ "$cur" == "$want" ]]; then print "unchanged $LINK"; return 0; fi
    if (( FORCE )); then say "repoint $LINK -> $want" "repointed $LINK -> $want"; run_or_print ln -sfn "$want" "$LINK"; return 0; fi
    print -u2 "would repoint $LINK: $cur -> $want (another checkout; run with --force-relink)"
    return 1
  elif [[ -e "$LINK" ]]; then
    print -u2 "$LINK exists and is not a link; leaving it alone"
    return 1
  fi
  run_or_print mkdir -p "${LINK:h}"
  say "link $LINK -> $want" "linked $LINK -> $want"
  run_or_print ln -s "$want" "$LINK"
  case ":$PATH:" in *":${LINK:h}:"*) ;; *) print "note: ${LINK:h} is not on your PATH" ;; esac
}
do_uninstall() {
  if [[ -L "$LINK" ]] && points_into_repo "$LINK"; then
    say "remove $LINK" "removed $LINK"; run_or_print rm "$LINK"
  elif [[ -L "$LINK" ]]; then print "leaving $LINK: it links into another checkout ($(link_target "$LINK"))"
  else print "nothing to remove: $LINK is not a link"; fi
}

# --- --migrate
backup() { [[ -e "$1.bak-$STAMP" ]] || { say "back up $1 to $1.bak-$STAMP" "backed up $1 to $1.bak-$STAMP"; run_or_print cp -p "$1" "$1.bak-$STAMP" } }
move_aside() {   # move_aside PATH: into migrated-YYYYMMDD, never deleting
  local src="$1" dest="$STATE/migrated-$STAMP" t i=1
  t="$dest/${src:t}"; while [[ -e "$t" || -L "$t" ]]; do t="$dest/${src:t}.$((i++))"; done
  say "move $src to $t" "moved $src to $t"
  run_or_print mkdir -p "$dest"; run_or_print mv "$src" "$t"
}
do_migrate() {
  local n f line S="$HOME/.claude/settings.json" T="$HOME/.tmux.conf" tmux_removed=0 effort=0 settings_ok=1 tmux_ok=1 lrc out
  local -a cmds gone old
  do_install || rc=1
  # settings.json: the agent-board hooks
  for n in bash-mirror artifact-register kill-guard; do cmds+=("~/.claude/hooks/$n.sh" "$HOME/.claude/hooks/$n.sh"); done
  if [[ -f "$S" ]]; then
    out="$(python3 "$LIB" settings "$S" ${${(M)TEAM:#1}:+--team} --dry-run "${cmds[@]}" 2>&1)"; lrc=$?
    gone=("${(@f)out}")
    if (( lrc == 3 )); then
      settings_ok=0; rc=1
      print -u2 "settings.json left as is: ${${(M)gone:#install_lib:*}[1]#install_lib: }"
      print -u2 "remove these hook entries from settings.json by hand:"
      for line in "${(@M)gone:#MANUAL *}"; do print -u2 "  ${line#MANUAL }"; done
    elif (( lrc != 0 )); then settings_ok=0; rc=1; print -u2 "settings.json left as is: ${gone[1]}"
    elif [[ -n "${gone[1]}" ]]; then
      backup "$S"
      for line in "${gone[@]}"; do say "remove from settings.json: $line" "removed from settings.json: $line"; done
      (( DRY )) || python3 "$LIB" settings "$S" ${${(M)TEAM:#1}:+--team} "${cmds[@]}" >/dev/null || { settings_ok=0; rc=1 }
    fi
  fi
  # ~/.tmux.conf: the hooks and bindings (config/tmux.conf has them for the dedicated server)
  if [[ -f "$T" ]]; then
    out="$(python3 "$LIB" tmux "$T" --dry-run 2>&1)"; lrc=$?
    gone=("${(@f)out}")
    if (( lrc != 0 )); then tmux_ok=0; rc=1; print -u2 ".tmux.conf left as is: ${gone[1]}"
    elif [[ -n "${gone[1]}" ]]; then
      backup "$T"
      for line in "${gone[@]}"; do say "remove from .tmux.conf: $line" "removed from .tmux.conf: $line"; done
      if (( DRY )); then tmux_removed=1
      elif python3 "$LIB" tmux "$T" >/dev/null; then tmux_removed=1
      else tmux_ok=0; rc=1; fi
    fi
  fi
  # links into this checkout
  for n in claude-orchestrator dev tmux-agent-cleanup tmux-ctl tmux-dash tmux-dev-layout tmux-jump tmux-session-closed tmux-teammate-window tmux-web-attach; do
    old+=("$HOME/.local/bin/$n"); done
  for n in bash-mirror artifact-register kill-guard; do old+=("$HOME/.claude/hooks/$n.sh"); done
  old+=("$HOME/.claude/orchestrator.md" "$HOME/.claude/worker.md")
  for f in "${old[@]}"; do
    if [[ "$f" == "$HOME"/.claude/hooks/* ]] && (( ! settings_ok )) && points_into_repo "$f"; then
      print "kept $f: settings.json still names it and could not be updated"
    elif [[ "$f" == "$HOME"/.local/bin/* ]] && (( ! tmux_ok )) && points_into_repo "$f"; then
      print "kept $f: .tmux.conf still calls it and could not be updated"
    elif points_into_repo "$f"; then say "remove link $f" "removed link $f"; run_or_print rm "$f"
    elif [[ -L "$f" ]]; then print "kept $f: it links outside $REPO"; fi
  done
  # what the plugin ships now
  for f in "$HOME/.claude/skills/tmux-orchestrator" "$HOME/.claude/skills/handoff"; do
    [[ -e "$f" || -L "$f" ]] || continue
    if [[ "$f" == */skills/handoff && ! -L "$f" ]]; then print "kept $f: not a link (a real directory of yours); remove it yourself if the plugin's handoff skill replaces it"
    else move_aside "$f"; fi
  done
  for f in "$HOME"/.claude/agents/effort-{low,medium,high}.md; do
    [[ -e "$f" || -L "$f" ]] || continue
    effort=1
    if (( KEEP_AGENTS )); then print "kept $f (--keep-agents)"; else move_aside "$f"; fi
  done
  (( effort )) && print "note: the effort-* agents are now provided by the agent-board plugin; plain \`claude\` sessions outside agent-board lose them once they are gone from ~/.claude/agents. $( (( KEEP_AGENTS )) && print "(kept: --keep-agents)" || print "Use --keep-agents to leave them in place.")"
  if (( tmux_removed )); then
    print "next: a running tmux server still has the old hooks and keys. Either restart tmux, or run"
    print "  tmux set-hook -gu after-split-window; tmux set-hook -gu session-closed; tmux unbind W; tmux unbind f; tmux unbind D"
    print "With the lines gone from ~/.tmux.conf, the next \`agent-board dev\` starts on agent-board's dedicated tmux server (-L agent-board)."
  fi
  (( DRY )) && print "(dry run: nothing was changed)"
}

case "$mode" in
  check)     check_deps; exit $? ;;
  install)   do_install; exit $? ;;
  uninstall) do_uninstall; exit 0 ;;
  migrate)   do_migrate; exit $rc ;;
esac
