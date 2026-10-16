#!/usr/bin/env bash
# Runs one of the superpowers-extended-cc example hooks wherever the plugin is
# installed. Install paths differ per machine: Claude Code marketplace or
# claude.ai sync under ~/.claude/plugins, or the Claude desktop app's copy under
# ~/Library/Application Support/Claude (where the folder is named plugin_<id>).
# A candidate counts only if its .claude-plugin/plugin.json names this plugin;
# the newest match wins. Exits 0 silently when none is found, so sessions
# without the plugin are unaffected. Usage: superpowers-hook.sh <script-name>.sh
set -uo pipefail
name="${1:-}"
case "$name" in
  post-task-complete-revalidate.sh|stop-revalidate-user-gates.sh|stop-wait-guard.sh) ;;
  *) echo "superpowers-hook: unknown hook '$name'" >&2; exit 0 ;;
esac

script=""
if [ -n "${SUPERPOWERS_PLUGIN_ROOT:-}" ] && [ -f "$SUPERPOWERS_PLUGIN_ROOT/hooks/examples/$name" ]; then
  script="$SUPERPOWERS_PLUGIN_ROOT/hooks/examples/$name"
else
  for base in "$HOME/.claude/plugins" "$HOME/Library/Application Support/Claude"; do
    [ -d "$base" ] || continue
    while IFS= read -r candidate; do
      root="${candidate%/hooks/examples/$name}"
      grep -q '"name": *"superpowers-extended-cc"' "$root/.claude-plugin/plugin.json" 2>/dev/null || continue
      if [ -z "$script" ] || [ "$candidate" -nt "$script" ]; then script="$candidate"; fi
    done < <(find "$base" -path "*/hooks/examples/$name" -type f 2>/dev/null)
  done
fi
[ -n "$script" ] || exit 0
exec bash "$script"
