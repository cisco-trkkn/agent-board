#!/usr/bin/env bash
# SessionStart: in a dev lead that has a Telegram state dir, make the lead's Bash-tool shells forget TELEGRAM_STATE_DIR.
# bin/claude-orchestrator exports it in the lead's own process so the plugin's MCP server finds the bot; without this,
# every `claude` started from the lead's shell would start a second telegram server for the same bot and SIGTERM the
# lead's poller. Claude Code sources $CLAUDE_ENV_FILE before each Bash command (hooks reference, SessionStart), so an
# appended `unset` reaches those shells only. The lead marker AGENT_BOARD_LEAD=1 is exported only by claude-orchestrator.
# --scoped (the plugin registration) is accepted and changes nothing. Appends once. Prints nothing. Fail-open.
cat >/dev/null 2>&1
[[ "$AGENT_BOARD_LEAD" == 1 && -n "$TELEGRAM_STATE_DIR" && -n "$CLAUDE_ENV_FILE" ]] || exit 0
grep -qxF 'unset TELEGRAM_STATE_DIR' "$CLAUDE_ENV_FILE" 2>/dev/null && exit 0
printf '%s\n' 'unset TELEGRAM_STATE_DIR' >> "$CLAUDE_ENV_FILE" 2>/dev/null
exit 0
