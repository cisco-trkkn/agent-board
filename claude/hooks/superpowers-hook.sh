#!/usr/bin/env bash
# Runs one of the superpowers-extended-cc example hooks wherever the plugin is
# installed. Install paths differ per machine: Claude Code marketplace or
# claude.ai sync under ~/.claude/plugins, or the Claude desktop app's copy under
# ~/Library/Application Support/Claude (where the folder is named plugin_<id>).
# A candidate counts only if its .claude-plugin/plugin.json names this plugin;
# the newest match wins. Exits 0 silently when none is found, so sessions
# without the plugin are unaffected. Usage: superpowers-hook.sh <script-name>.sh
# Short-circuit: the two Stop guards exit 0 before resolving the plugin when the
# session's native task dir (~/.claude/tasks/session-<sid8>, or $SUPERPOWERS_TASKS_DIR)
# shows they cannot act: wait-guard needs an in_progress task, revalidate a user-gate
# marker. The marker is the task dir, not the transcript: a probe found the gate words in
# the skill listing of 199 of 200 transcripts. An empty session_id passes through.
set -uo pipefail
name="${1:-}"
case "$name" in
  post-task-complete-revalidate.sh|stop-revalidate-user-gates.sh|stop-wait-guard.sh) ;;
  *) echo "superpowers-hook: unknown hook '$name'" >&2; exit 0 ;;
esac

input="$(cat; printf x)"; input="${input%x}"  # keeps trailing newlines: the guard gets the exact bytes
sid="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
tasks="${SUPERPOWERS_TASKS_DIR:-$HOME/.claude/tasks}/session-${sid:0:8}"
if [ -n "$sid" ]; then
  case "$name" in
    stop-wait-guard.sh)
      grep -qE '"status": *"in_progress"' "$tasks"/*.json 2>/dev/null || exit 0 ;;
    stop-revalidate-user-gates.sh)
      grep -qiE 'usergate|user-gate|user-ordered gate' "$tasks"/*.json 2>/dev/null || exit 0 ;;
  esac
fi

# Resolution order, cheapest first: $SUPERPOWERS_PLUGIN_ROOT; a glob of the known
# install dirs (no process spawned unless several versions are installed); then a
# `find` walk, which is slow and only the desktop-app copy needs it.
is_plugin() { grep -q '"name": *"superpowers-extended-cc"' "$1/.claude-plugin/plugin.json" 2>/dev/null; }

script=""
if [ -n "${SUPERPOWERS_PLUGIN_ROOT:-}" ] && [ -f "$SUPERPOWERS_PLUGIN_ROOT/hooks/examples/$name" ]; then
  script="$SUPERPOWERS_PLUGIN_ROOT/hooks/examples/$name"
fi

if [ -z "$script" ]; then
  # cache/<marketplace>/superpowers-extended-cc/<version>: the installed copy, newest version wins
  versions=""
  for root in "$HOME"/.claude/plugins/cache/*/superpowers-extended-cc/*/; do
    root="${root%/}"
    [ -f "$root/hooks/examples/$name" ] && is_plugin "$root" && versions="$versions${root##*/} $root"$'\n'
  done
  if [ -n "$versions" ]; then
    best="$(printf '%s' "$versions" | sort -V -k1,1 | tail -n 1)"
    script="${best#* }/hooks/examples/$name"
  fi
fi

if [ -z "$script" ]; then
  # marketplaces/<marketplace>: the plugin's source checkout
  for root in "$HOME"/.claude/plugins/marketplaces/*; do
    [ -f "$root/hooks/examples/$name" ] && is_plugin "$root" || continue
    if [ -z "$script" ] || [ "$root/hooks/examples/$name" -nt "$script" ]; then script="$root/hooks/examples/$name"; fi
  done
fi

if [ -z "$script" ]; then
  for base in "$HOME/.claude/plugins" "$HOME/Library/Application Support/Claude"; do
    [ -d "$base" ] || continue
    while IFS= read -r candidate; do
      root="${candidate%/hooks/examples/$name}"
      is_plugin "$root" || continue
      if [ -z "$script" ] || [ "$candidate" -nt "$script" ]; then script="$candidate"; fi
    done < <(find "$base" -path "*/hooks/examples/$name" -type f 2>/dev/null)
  done
fi
[ -n "$script" ] || exit 0
printf '%s' "$input" | exec bash "$script"
