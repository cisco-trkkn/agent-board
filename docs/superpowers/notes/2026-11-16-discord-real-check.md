# Discord real-state check (2026-11-16, branch queue/discord-replaces-telegram, HEAD f94c88a)

Read-only against this machine's real Discord state, plus the full suite. No token or `.env` content was printed;
of the servers' environments only the `DISCORD_STATE_DIR=` word was read.

## 1. Full suite

Run 1: `zsh tools/tests/all.zsh` under heavy load (slowest jobs 278-317 s, load average about 5, other `all.zsh` runs overlapping):

    FAIL 1/129: zsh/test_all_runner.zsh      (rc=1)
    FAIL - interrupt: a job ignoring INT and TERM is KILLed, runner exits 130 in under 8 s

That is a timing assertion. `zsh tools/tests/test_all_runner.zsh` alone: `ALL PASS`. Recorded as a load flake, not fixed here.

Run 2, same HEAD, quieter machine (load average 3.5):

    ALL PASS 129 jobs in 5m35s
    SLOW: 5m35s over the 5 min budget        (rc=4: SLOW only, no FAIL)

## 2. Real status, worktree `bin` first on PATH, real TC_STATE and HOME

`tmux-ctl discord status --project agent-board`:

    token: set
    paired: 1 allowlisted
    policy: allowlist
    ack reaction: off
    held by: _web-40635:claude pid 98976
    plugin: ok
    launcher: drift
    watch: not loaded

`--project interiors`: same, with `held by: interiors:claude pid 98971`.

Cross-check with `ps -Eww -o command= -p <bun server pid>`, only the `DISCORD_STATE_DIR=` word:

- pid 99134 (child of claude 98976): `DISCORD_STATE_DIR=/Users/francisco.ruiz/.local/state/agent-board/discord/agent-board`
- pid 99301 (child of claude 98971): `DISCORD_STATE_DIR=/Users/francisco.ruiz/.local/state/agent-board/discord/interiors`

`launcher: drift` and `watch: not loaded` are expected before the merge: the live plugin still has the stock `.mcp.json`, and no Discord watchdog is installed yet.

## 3. claude-orchestrator in a real pane

Started with `tmux-ctl send shell "zsh <script>"` (the `shell` window, session `agent-board-bg`). The script runs
`bin/claude-orchestrator` from the worktree, with a fake `claude` first on PATH that writes its argv, `TC_DISCORD_LAUNCHER=0`, and real TC_STATE and HOME.

Context: `pane=%10 session=agent-board-bg group=[] bg=[1]`. `@tc_bg` is set, so the project resolved to `agent-board` (the `-bg` suffix is stripped).

stderr, exactly one line:

    discord: agent-board's bot is held by the lead in _web-40635:claude (pid 98976); this lead starts without it

Recorded argv (no `--channels`), and `DISCORD_STATE_DIR` was `UNSET` in the fake claude:

    --model opus --settings <worktree>/claude/session-settings.json --plugin-dir <worktree>/claude/plugin
    --append-system-prompt-file <worktree>/claude/orchestrator.md

Side effect found and undone: the orchestrator copies `AGENT_BOARD_REPO` and `PATH` into the tmux session environment. This run set them on `agent-board-bg` (repo = the worktree, PATH with the worktree `bin` and my scratch dir). I removed those two PATH entries and unset `AGENT_BOARD_REPO` there; `show-environment` confirms neither remains. The variable was unset in the live lead's session `_web-40635`, so unset was taken as the earlier state; the exact earlier `PATH` in `agent-board-bg` is unknown.

## 4. dc_ensure_launcher on a copy of the real plugin (Task 1 review carry-over)

Copy of `~/.claude/plugins/cache/claude-plugins-official/discord/0.0.4` in a scratch `CLAUDE_CONFIG_DIR`; the real dir was never touched (its `.mcp.json` is still the stock one and has no `discord-mcp-launch`).

    before: {"mcpServers":{"discord":{"command":"bun","args":["run","--cwd","${CLAUDE_PLUGIN_ROOT}","--shell=bun","--silent","start"]}}}
    run:    discord: plugin launcher installed (0.0.4)      rc=0
    after:  command "${CLAUDE_PLUGIN_ROOT}/discord-mcp-launch", args ["${CLAUDE_PLUGIN_ROOT}"]
    backup: <scratch>/plugin-backups/discord/0.0.4/.mcp.json.bak-20261116   (holds the stock file)
    second run: prints nothing, rc=0

The copied launcher with no token in env and `DISCORD_STATE_DIR` at an empty scratch dir, fed `initialize` and `tools/list`:

    {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{"name":"discord-stub","version":"0"}}}
    {"jsonrpc":"2.0","id":2,"result":{"tools":[]}}      rc=0

REAL CHECK PASS
