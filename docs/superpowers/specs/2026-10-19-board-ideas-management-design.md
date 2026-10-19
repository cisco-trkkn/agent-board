# Board ideas management: drop, edit, move — design

Date: 2026-10-19 · Ideas group A (from `~/.claude/ideas/agent-board.md`):
- there should be a way to delete ideas I no longer find relevant besides just editing them
- I should be able to edit submitted ideas, both the main part and the details
- there should be an option to move plan documents or ideas from one project to another

## Goal

From the Agent Board, the user can drop (and restore), edit, and move ideas, and move plan or spec
documents to another open project, without opening the ideas file or the repo by hand.

## Decisions

- **Delete = drop.** The board's delete marks the idea `- [-]`. Nothing is ever removed from the
  ideas file; the rule "never delete an idea" stands. Dropped ideas can be restored.
- **Moving a plan moves the files and does not commit.** Both repos are left with uncommitted
  changes for the user or a lead to commit.
- **Move targets are the projects open on the board** (live tmux project sessions, `_web-*`
  excluded). The target's repo is that session's `path` as computed for `/api/state`.

## Ideas operations — `board/ideas.py`

**Identity.** An idea is addressed by its key: the first line without the checkbox,
`YYYY-MM-DD HH:MM · text`, exactly as `load()` returns it (`ts` + ` · ` + `text`). Every operation
takes the exclusive lock on `<file>.lock` (as `add` does), re-reads the file, and finds the lines
whose key matches. Zero or more than one match raises `Stale("the idea changed since you loaded it")`.
The rewrite goes to a temp file next to the ideas file, then `os.replace`.

| Function | Applies to | Effect |
| --- | --- | --- |
| `edit(project, key, text, detail)` | open ideas | Replaces the text after `· ` (keeps the timestamp and checkbox) and replaces the idea's indented detail lines. Text is whitespace-collapsed and must be non-empty, as in `add`. Returns the new key. |
| `set_status(project, key, status)` | `status` is `dropped` (from open) or `open` (from dropped) | Flips `[ ]` ↔ `[-]`. A dropped idea whose line carries `→ moved to <p>` cannot be restored (raises `ValueError`). Taken `[x]` ideas are never changed. |
| `move(project, key, target)` | open ideas, `target != project` | 1. Appends the idea to the target's file with its original timestamp and detail (under the target's lock; header written if the file is new). 2. Rewrites the source line to `- [-] ts · text → moved to <target>`. Append first: a failure between the two steps leaves a duplicate, never a lost idea. |

`load()` gains a `"moved_to"` field (the target, or `""`) parsed from a trailing ` → moved to <p>`
on a dropped line. The CLI (`ideas.py`) gets no new subcommands.

## Moving artifacts — `board/artifacts.py`

`move(project, path, target, target_repo, source_repo)`:

- Allowed only for paths in the project's manifest that are inside `source_repo/docs/superpowers/plans/`
  or `.../specs/` and not under any `/.claude/worktrees/`. Eligibility is by path, not by the manifest
  `kind`: `tmux-ctl artifact` registers plans as `other`.
- The new path is `target_repo / <path relative to source_repo>`. Refuses (`ValueError`) if it
  exists, or if `<path>.tasks.json` exists and its target exists.
- Creates parent dirs, moves the file, and moves `<path>.tasks.json` if present (plain rename;
  `shutil.move` if across filesystems). No git commands.
- Registers the new path in the target's manifest: `artifact-register.sh --path <new> --agent you
  --project <target>`.
- Appends `{"ts": now, "path": <old>, "moved_to": <new>, "agent": "you"}` to the source manifest.
  `summary()` skips items whose latest entry has `moved_to`; `read()` refuses a moved path.
  Manifests stay append-only.

## Server — `board/server.py`

New `action`s in the POST handler, each validating `session` and `target` with `NAME_RE`
(and rejecting `_web-*`):

- `idea_edit` {key, text, detail} → `ideas.edit`
- `idea_status` {key, status} → `ideas.set_status`
- `idea_move` {key, target} → `ideas.move`; `target` must be an open project
- `artifact_move` {path, target} → `artifacts.move` with both projects' repo paths from the current
  state; `target` must be an open project with a repo path.

`ideas.Stale` and `ValueError` map to a 409 / 400 with the message, shown on the board's error line.
`api/ideas` already returns every idea; the UI does the filtering.

## UI — `board/index.html`

- **Idea rows** get the existing right-click / long-press menu (the `bindAgentMenu` pattern):
  *Edit*, *Drop*, *Move to… ▸ <open projects other than this one>*.
- *Edit* turns the row into the same input + textarea as the add form, pre-filled; Enter or *Save*
  posts `idea_edit`, Escape cancels. The 2 s poll does not rebuild a row while it is being edited.
- A *Show dropped* toggle under the list shows dropped ideas (dimmed, newest first, moved ones
  labelled `→ <project>`); their menu has *Restore* (not for moved ones).
- **Rows under `docs/superpowers/plans|specs/`** in the artifacts panel get a menu with *Move to… ▸ <open projects>*.
  After a move, the row disappears from this project and appears under the target.

## Testing

- `board/tests/test_ideas.py` (temp `TC_IDEAS_DIR`): edit keeps the timestamp and replaces details;
  stale key refused; duplicate key refused; drop/restore round trip; taken ideas untouched;
  moved ideas cannot be restored; move appends to target with original timestamp and detail and
  marks the source; move to a new target file writes the header; `add` still works after edits.
- `board/tests/test_artifacts.py` (temp `TC_STATE`, two temp dirs as repos): plan move carries the
  `.tasks.json`; refuses an existing target; refuses a path outside `docs/superpowers/` or in a
  worktree; source summary hides the item, target summary shows it; no git commit made in either repo.
- A server-action test for the four actions, including name validation and the 409 mapping.
- Live check on the restarted board against a scratch project: drop, restore, edit, move an idea,
  move a plan, then confirm the files on disk.

## Out of scope

Committing moved files; moving ideas or plans to closed projects; bulk operations; a CLI for the
new operations; changing the lead's "never delete an idea" rule.
