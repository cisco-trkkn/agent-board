# Claude Docs PostToolUse payload fixtures

Real payloads written by a Claude Code PostToolUse hook (not typed), scrubbed.

- Date: 2026-10-26
- Claude Code: 2.1.310
- Hook (scratch settings file passed with `--settings`; no real settings touched):
  `{"hooks":{"PostToolUse":[{"matcher":"mcp__claude_ai_Claude_Docs__.*","hooks":[{"type":"command","command":"cat >> <scratch>/payloads.jsonl"}]}]}}`
- Command (the prompt must come before `--allowedTools`, which is variadic and swallows a trailing prompt):
  `claude -p "Using the Claude Docs tools: 1) create a doc titled 'agent-board hook fixture (delete me)' containing one line of text 'hello fixture'. 2) edit that doc once (append a second line 'second line'). 3) read the doc. Do NOT delete it. Reply with the doc URL." --settings <scratch>/settings.json --allowedTools 'mcp__claude_ai_Claude_Docs__*'`
- Split: `sed -n Np payloads.jsonl | jq '.session_id="S1"|.transcript_path="/tmp/t"|.cwd="/tmp/t"'`
  for N=1 (create), 3 (update), 4 (read). Line 2 was a `__guide` call (45 KB, not kept).

Tool names seen: `__batch` (create), `__guide`, `__update`, `__read`.
Payload keys: cwd, duration_ms, effort, hook_event_name, mcp_server, permission_mode,
prompt_id, session_id, tool_input, tool_name, tool_response, tool_use_id, transcript_path.
`tool_response` is a list of `{"type":"text","text":"..."}`; `text` is a JSON string.

## Where the URL and title sit

| | tool_name | doc URL | title |
|---|---|---|---|
| create.json | `mcp__claude_ai_Claude_Docs__batch` | `tool_response[0].text` is a JSON object followed by `\n\n` and prose. Parse the first line: `jq -r '.tool_response[0].text\|split("\n")[0]\|fromjson\|.frame.url'` (same value at `.frame.artifactUrl`). The URL also appears in the prose, so a regex `https://claude\.ai/artifact/[A-Za-z0-9_-]+` on the text works. | `tool_input.container.create.name` |
| update.json | `mcp__claude_ai_Claude_Docs__update` | **none** (no claude.ai URL anywhere in the payload) | **none** (no title in input or response) |
| read.json | `mcp__claude_ai_Claude_Docs__read` | `tool_response[0].text` parsed as JSON: `.frame.url` | **none** |

What identifies the doc in update/read: `tool_input.container.id` (kind `project`) is the
doc slug (`c40c4cbb-...`), and `tool_input.ref.id` the tab node. The create response
carries the same slug at `frame.slug` (the first line's `created.minted` too), so the
URL of an update can be found by mapping slug -> URL from the create call. The slug is
not part of the claude.ai URL.

## Scrub

`session_id` -> `S1`, `transcript_path` and `cwd` -> `/tmp/t`. The doc URL, doc slug,
`prompt_id` and `tool_use_id` are kept (none identifies the account). No email present:
`grep -rE '[[:alnum:]._%+-]+@[[:alnum:].-]+\.[a-z]{2,}' tools/tests/fixtures/docs-hook/` prints nothing.

## Cleanup

The scratch doc (`agent-board hook fixture (delete me)`) was deleted afterwards with
`mcp__claude_ai_Claude_Docs__delete` (ref project `c40c4cbb-22e5-42f6-8b8d-d059bc72bc78`) -> `{"verdict":"allow"}`.
The headless session itself did not delete it (told not to).
