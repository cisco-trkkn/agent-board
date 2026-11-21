# Worker context probe (2026-11-20)

Measures what a fresh teammate's context holds before it does any work, to decide E4 (trimming MCP tool schemas from workers).

## Setup

- Claude Code version: 2.1.330.
- Model: Sonnet 5.5 (`claude-sonnet-5-5`), context window 1M tokens.
- Tier: standard (agent type `effort-medium`, model `sonnet`).
- Started by the lead the normal way: the Agent tool with a team name, in this project's `dev` tmux session, teammate `ctx-probe`. Its only prompt was "wait for instructions; do nothing; reply ready", so it never read `worker.md` and had done no work. It replied "ready".
- The lead then typed `/context` into its pane (`tmux send-keys -t <pane> -l '/context'` plus Enter). The implementer typed nothing into the window.
- Read command (read-only, run by the lead): `tmux capture-pane -p -S -200 -t <pane>`. The capture is kept at `.superpowers/sdd/2026-11-20-efficiency-now/ctx-probe-capture.txt` (not committed; `.superpowers/` is gitignored).
- The teammate has since been shut down.
- Second probe: the lead started a second fresh teammate, `ctx-probe`, the same way, with the same tier (agent type `effort-medium`, model `sonnet`) and the same Claude Code version (2.1.330), and typed `/context all` into its pane. The lead captured it read-only with `tmux capture-pane -p -S -200 -t <pane>`; the capture is kept at `.superpowers/sdd/2026-11-20-efficiency-now/ctx-probe-capture-all.txt` (not committed). Its category rows repeat the first probe (MCP tools 7.9k, Messages 4.6k because that probe had replied "ready"). Version 2.1.330 and the tier are now on record from the lead, not only from the implementer's reading.

## Breakdown

Tokens and percent of the 1M window are copied from the screen. Share of used context = tokens divided by the sum of the non-free rows. The autocompact buffer (33k, 3%) is reserved space, not used context, so it is excluded from the sum. Used = 32.5k, which matches the screen's header (`32.5k/1m tokens (3%)`).

| Category | Tokens | % of window | Share of used |
|---|---|---|---|
| System prompt | 1.8k | 0.2% | 5.5% |
| System tools | 6.6k | 0.7% | 20.3% |
| MCP tools | 7.9k | 0.8% | 24.3% |
| MCP server instructions | 1.3k | 0.1% | 4.0% |
| Custom agents | 1.2k | 0.1% | 3.7% |
| Memory files | 2.4k | 0.2% | 7.4% |
| Skills | 6.3k | 0.6% | 19.4% |
| Messages | 5k | 0.5% | 15.4% |
| **Used (sum of the rows above)** | **32.5k** | **3%** | **100%** |
| Free space | 934.5k | 93% | not counted |
| Autocompact buffer (reserved) | 33k | 3% | not counted |

Detail lines on screen: MCP tools 69 tools (loaded on-demand per `/mcp`); custom agents 14; memory files 3; skills 60.

## MCP share

- MCP tool schemas: 7.9k of 32.5k used = 24.3% of the fresh worker's used context (0.8% of the window).
- Counting the MCP server instructions as well (1.3k): 9.2k = 28.3% of used context.
- Servers: plain `/context` shows only the aggregate (69 tools, 7.9k tokens). `/context all` splits the "MCP tools (loaded on-demand)" list into Loaded and Available. Loaded is 7 tools, all from the `claude-artifacts` server, with these counts: `edit_version` 1.2k, `get_artifact` 238, `guide` 1.2k, `list_artifacts` 604, `publish_files` 2.5k, `publish_version` 1.4k, `read_artifact` 704. They sum to about 7.85k, which is the 7.9k MCP tools figure. Available is the other 62 tools (claude_ai_Claude_Docs, the rest of claude-artifacts, claude-in-chrome, plugin_gitlab), listed with no token count: they are deferred and are not in the 7.9k.
- Per turn or not: the Loaded schemas are the tool definitions sent with every request, so the 7.9k is a per-turn cost, not an on-demand one. The 1.3k MCP server instructions is system-prompt text, also sent every turn. The Available tools cost nothing until they are loaded.
- Connector results: the capture shows none. The Messages row (5k) is the teammate's startup message and its "ready" reply.

## Verdict for E4

go: MCP tool schemas are 24.3% of one fresh Sonnet teammate's used context (7.9k of 32.5k tokens), above the spec's 5% line ("If MCP schemas are under 5% of a fresh worker's context, E4 is a no-go."); the spec does not define the denominator, this verdict uses the plan's reading (used context), and the window reading (0.8% of the 1M window) would flip it to no-go; scope is one fresh teammate of one tier (standard) on one day (2026-11-20).
