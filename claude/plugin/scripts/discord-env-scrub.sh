#!/usr/bin/env bash
# SessionStart: in a dev lead that has a Discord state dir, make the lead's Bash-tool shells forget DISCORD_STATE_DIR and
# DISCORD_BOT_TOKEN. bin/claude-orchestrator exports the state dir in the lead's own process so the plugin's MCP server finds
# the bot; without this, a `claude` started from the lead's shell would open a second gateway session on the same bot.
# Claude Code sources $CLAUDE_ENV_FILE before each Bash command, so an appended `unset` reaches those shells only.
# --scoped (the plugin registration) is accepted and changes nothing. Appends once. Prints nothing. Fail-open.
cat >/dev/null 2>&1
[[ "$AGENT_BOARD_LEAD" == 1 && -n "$DISCORD_STATE_DIR" && -n "$CLAUDE_ENV_FILE" ]] || exit 0
line='unset DISCORD_STATE_DIR DISCORD_BOT_TOKEN'
grep -qxF "$line" "$CLAUDE_ENV_FILE" 2>/dev/null && exit 0
printf '%s\n' "$line" >> "$CLAUDE_ENV_FILE" 2>/dev/null
exit 0
