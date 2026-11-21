# Changelog

## 2.1.330

- Added sign-in to organizations managed in Anthropic's Enterprise Admin Console: after `claude auth login`, Claude Code applies the organization's settings and uses its cloud provider or gateway
- Added easel, a built-in mod that draws charts when asked and under MCP metrics results, on Pro, Max and, where available, Team and Enterprise on macOS and Linux; turn automatic charts off in `/config`
- Added `CLAUDE_CODE_FULL_SIGN_IN_LINK=1` to print the full sign-in link, if the short one shows an error or a script reads values from it
- Self-hosted runner: Added `--start-dir` / `SELF_HOSTED_RUNNER_START_DIR` to have Claude start its work in a folder of a repository, while settings and hooks load as without it
- Added a notice in cloud and self-hosted runner sessions when a plugin marketplace can't be fetched because its repository isn't one of the session's
- Self-hosted runner: Added a notice when Anthropic-managed git refuses a plugin's own repository, naming the plugin and what to do
- Added `commandPrinted` to `claude plugin install --json` results, true when the plugin's install command wrote to stderr, and `commandFailed` when it exited with an error, was killed or timed out
- Added `claude_code_self_hosted_runner_order_to_registered_seconds` to the self-hosted runner's `/metrics`: seconds from work order issued to registration accepted, on orchestrator-spawned runners
- Added `claude_code_self_hosted_runner_order_to_first_session_seconds` to the self-hosted runner's `/metrics`: seconds from work order to first session handed over, on runners started for a session
- Fixed Claude Code freezing for up to several minutes right after compacting a very long conversation
- Fixed WebFetch freezing the session for minutes on some pages, and returning an empty result for some others
- Fixed `ExitWorktree` and the worktree exit dialog deleting a worktree that another running Claude Code session was working in
- Fixed changes to user settings being lost when several Claude Code processes saved them at the same time
- Fixed `--continue` and `--resume` opening an empty session or failing when the last saved message had a missing or invalid timestamp
- Fixed the first prompt after a sleep of two minutes or more waiting three minutes on a connection that had died, on Linux and WSL
- Fixed turns failing with "JSON schema is invalid", and session files growing by many megabytes, when many MCP tools have an input schema that the API refuses
- Linux: Fixed Bash commands waiting seconds and showing no file diff for the rest of a session in slow repositories with large ignored folders such as `node_modules`
- Windows: Fixed Bash commands running slower for the rest of a session after Git Bash took 10 to 60 seconds to start, on machines with no custom start-up files
- Fixed `/rewind` sometimes restoring an older version of a file when two queued prompts, or stacked skills, ran together right after a turn that changed it
- Fixed text and images added when approving a permission prompt being dropped when the approved command or tool then failed
- Fixed MCP resources from claude.ai connectors and plugin servers not being attached when @-mentioned in the terminal's prompt box
- Fixed an MCP server that subagents declare being shut down when one of them finished, while other subagents or the session were still using it
- Fixed Claude in Chrome staying "not connected" after a brief connection problem, even though Chrome was open and signed in
- Fixed terminal sessions on Amazon Bedrock (Mantle) started with no model selected ignoring a pinned Opus model, and still calling an unavailable default model after announcing a fallback
- Fixed the rest of what you were typing being lost when a plan arrived in fullscreen mode
- Fixed claude.ai connectors with different names being dropped when they share a server URL (anthropics/claude-code#101856)
- Fixed plugins going missing from the installed list when several `claude plugin` commands ran at the same time
- Fixed task dependencies and metadata being lost when several task updates ran at the same time
- Fixed incomplete backups of `~/.claude.json` being kept, and displacing good ones, when the disk was full
- Fixed a long pause in Code Mode after code that read hundreds of files in projects with path-scoped rules or Read deny rules
- Fixed the built-in chart tool failing when Claude called it in Code Mode
- Fixed Code Mode ignoring an MCP tool's request to end the turn from a script in auto and bypass permissions modes
- Fixed Code Mode in auto mode dropping earlier thinking and rewriting the prompt cache when a mod added a note after a script loaded a skill
- Fixed Code Mode not restoring a file that a script had read after Esc and `/compact`
- Fixed `/context` undercounting system tools in Code Mode before Claude's first reply
- Fixed a stopped background subagent sometimes not staying stopped
- Fixed Claude still waiting for a background agent that was stopped just as it finished, in sessions run by an app or the SDK
- Fixed background sessions sometimes waking in their previous permission mode after approving a plan
- Remote Control: Fixed the note about background agents ended by a Stop from a phone or the web showing in the terminal as if you had typed it
- Remote Control: Fixed the mobile apps hiding the Diff and pull request buttons, or showing a stopped session as working, after turning it on mid-conversation
- Fixed environment variables written by a SessionStart hook being lost with `claude -p --continue`
- Fixed `claude -p` exiting 0 with no message when its output went to a file on a full disk: it now prints an error and exits 1, though a full NFS export may go unnoticed
- Fixed the system prompt keeping the earlier model's instructions when the model was changed after `/context` but before the first message

## 2.1.329

- Fixed `/resume` listing sessions from other projects
- Added `--print-timing` to show per-turn latency

## 2.1.328

- Fixed a crash when the terminal was resized during a tool call
