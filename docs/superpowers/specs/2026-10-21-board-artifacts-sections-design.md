# Board artifacts panel: sections by type, older plans, specs and Claude Docs

Date: 2026-10-21. Status: approved design. Planning starts after PR #1 (installability) is merged, because that branch moves the hook to `claude/plugin/scripts/artifact-register.sh`.

Ideas covered (`~/.claude/ideas/agent-board.md`): Claude Docs present and clickable from the artifacts pane; the current plan always pinned with older plans newest first; specs as their own section under plans.

## Today

- `board/artifacts.py` `summary()` returns `items` (one per path or URL, with `history`), `active_plan` (the lead's newest plan in the current epoch, falling back to its newest plan in any epoch), `epoch` and `lineage`.
- `board/index.html` `renderArtifacts()` pins `active_plan`, then shows every other item in `Session N` groups (one per epoch), sorted by last write. Kinds are mixed inside each group.
- The PostToolUse hook (`Write|Edit|MultiEdit|Artifact`) records files by `kind_of(path)` (`plan`, `spec`, `handoff`, `report`) and published Artifacts as `published` with their `claude.ai` URL. Claude Docs tools are not matched, so docs never appear. A URL item is labelled with the URL's last segment.

## Design

### Sections

The panel shows, top to bottom:

1. **Plan (pinned):** `active_plan`, rule unchanged (the lead's newest plan; carries over from earlier sessions until a newer one is written; a worker's worktree plan never takes it).
2. **Plans:** every other plan, ordered by first-registered time (`history[0].ts`), newest first.
3. **Specs:** kind `spec`, newest first by last write.
4. **Docs & pages:** kind `doc` (Claude Docs) and `published` (Artifact pages), newest first by last write; each opens its URL in a new tab.
5. **Other:** `handoff`, `report`, `other`; collapsed by default.

Empty sections are not shown. Each item shows a small session tag `S<epoch+1>` next to the agent badge. The `Session N` groups are removed; each section's open/closed choice is kept in `localStorage` per project and section, storing only choices that differ from the default (same pattern as today's group toggle).

Unchanged: moving an item to another project, the "N comments waiting for the lead" line, the "Plan done · N ideas ready" line, unread-change dots, and opening files in the doc pane.

### Data (`board/artifacts.py`)

`summary()` adds `sections`: an ordered list of `{"name": "plans"|"specs"|"docs"|"other", "items": [<key>...]}` built from `items` (excluding `active_plan`), with the ordering rules above, and each item gains `title` (from its latest entry that has one; absent → the client falls back to today's label) and `first_ts`. The existing keys stay, so an older page keeps working.

### Hook (`artifact-register.sh`)

- The matcher adds the Claude Docs tools that create or change a doc (`mcp__claude_ai_Claude_Docs__batch`, `…__create`, `…__update`; read, query, export and guide are ignored).
- From `tool_response` it takes the doc's `claude.ai` URL and title and appends `{ts, path: <url>, url, title, kind: "doc", agent, session_id, epoch}`. A response without a doc URL records nothing. A later edit of the same URL appends a new entry, which moves the doc to the top.
- The exact response shape is not known yet: the plan's first task captures one real hook payload for a doc create and one for an edit (from a real session, saved as test fixtures with their origin noted) before any parsing code is written.

### Error handling

- An unparseable or unexpected Docs response records nothing and never fails the tool call (the hook stays `async`, exit 0).
- Entries with no `title` render with today's label.

## Testing

- `board/tests`: section split and ordering (plans by first-registered time, others by last write), title fallback, `active_plan` excluded from Plans, Other collapsed by default; existing artifact tests stay green.
- Hook tests run the real `artifact-register.sh` on the captured payloads (create and edit) and on a read payload (records nothing).
- One browser check on an ephemeral board from the worktree (`TMUX_DASH_PORT=7710 python3 board/server.py`): the sections render in order, a doc item opens its URL, section toggles persist across reload.
