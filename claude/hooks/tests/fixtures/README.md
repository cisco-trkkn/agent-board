# fixtures

## taskupdate-posttooluse.json

A real PostToolUse payload of a `TaskUpdate` call, captured 2026-11-20 with Claude Code 2.1.330.

Capture: a scratch project (outside this repo) whose `.claude/settings.json` had one PostToolUse hook, matcher
`TaskUpdate`, command `cat >> <scratch>/payload.jsonl` (the hook's stdin is the payload). From that directory:

    claude -p "Use TaskCreate to create one task titled 'Plan & run: probe', then use TaskUpdate to set it to completed. Do nothing else." --allowedTools TaskCreate,TaskUpdate

The first captured line (`tool_input.status` = `completed`) was saved as one JSON object on one line. Only
`session_id`, `transcript_path` and `cwd` were replaced, by `abcdef12-0000-4000-8000-000000000000`, `/home/u/t.jsonl`
and `/home/u/p`.

Top-level keys: `session_id`, `transcript_path`, `cwd`, `prompt_id`, `permission_mode`, `effort`, `hook_event_name`,
`tool_name`, `tool_input`, `tool_response`, `tool_use_id`, `duration_ms`.

`tool_input` keys: `taskId`, `status`. (No `subject`: it is in the task file under `~/.claude/tasks/session-<id8>/`.)
