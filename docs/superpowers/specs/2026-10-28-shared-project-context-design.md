# Shared project context: one curated file every agent starts with

Ideas (francisco_ruiz inbox, 2026-10-21): "teammates spend a lot of time searching for project context that should be getting reused
by any agent in a project" and "context should be reused between generations of teammates and orchestrators".

## Problem

Every teammate, worker and new orchestrator generation starts out knowing only what its brief and the repo's `CLAUDE.md` say.
They have to rediscover:
- where things live;
- how to run things and read the results;
- which tests flake and which actions the classifier refuses;
- what was decided or ruled out.

Briefs are written fresh each time, and handoff docs carry in-flight state, not durable knowledge. What a teammate learns dies with
its report.

## Decisions (user, 2026-10-28)

- Covers all three kinds of context equally: codebase map, how-to-run knowledge, decisions.
- **The lead curates.** Teammates propose; only the lead writes.
- **Location:** one per-project state file outside the repo, next to the ideas inbox. Nothing is committed.
- **Delivery:** a SessionStart hook injects it into every agent, within a size cap.
- **Approach 1:** one curated Markdown file. Each entry carries a `(files: …)` suffix, so a staleness check can be added later
  without changing the format.

## Behaviour

### The file
- **Path:** `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`. `<project>` is the same key the ideas inbox
  uses: the tmux session group, else the session name.
- **Layout:**

  ```markdown
  # <project>: shared agent context
  Last curated: YYYY-MM-DD

  ## Map
  - <fact> (files: path/a, path/b) · YYYY-MM-DD

  ## How to run
  ## Gotchas
  ## Decisions
  ```

- **Entries:** one bullet per entry. The trailing date is when the entry was last checked. `(files: …)` is optional but expected
  for Map and How-to-run entries.
- **Section order:** fixed. `add` refuses an unknown section.
- **`board/context.py`:** same shape as `board/ideas.py`, with an exclusive lock on `<file>.lock`. Exposed as
  `tmux-ctl context show | path | add <section> "<entry>"`.
  - `add` creates the file with all four headings the first time.
  - `add` appends today's date if the entry has none.
  - Pruning and rewording are ordinary edits made while holding the lock (the lead uses the Edit tool after
    `tmux-ctl context path`).
- **Board:** the file can be opened in the artifacts panel (`tmux-ctl artifact "$(tmux-ctl context path)"`).

### Delivery
- **Hook:** `claude/plugin/scripts/context-inject.sh`, registered as SessionStart in `claude/plugin/hooks/hooks.json`, with
  `--scoped` and a 5s timeout. Every agent-board lead, teammate and worker loads the plugin, so all of them get it. It fires
  again after a compaction or resume.
- **Output:** the file, injected as `additionalContext` with a one-line preface: "Shared project context, curated by the lead;
  propose additions as 'Context learned' in your report."
- **Cap:** 8 KB. Over the cap, the hook cuts at the end of the last whole entry that fits and appends
  `… truncated, full file at <path>`.
- **No file, or an empty one:** no output.
- **Off switch:** `TC_CONTEXT=0`.
- **Errors:** any error lets the session start without context, never blocks it.

### Curation
- **Teammate rules** (`claude/orchestrator.md`, the rule on reporting with evidence): the final report ends with
  `Context learned:` bullets. Each bullet is tagged with its section, cites its files, and is limited to facts that would have
  saved this teammate time searching. Teammates never write the file.
- **The lead, at each deliverable:**
  - merges durable items with `tmux-ctl context add`;
  - skips items already there;
  - re-dates entries it has checked again;
  - deletes entries a teammate showed to be wrong.
- **At `finishing-a-development-branch`:** the lead prunes entries whose cited files were removed or renamed by the branch.
- **Over the 8 KB cap:** the lead condenses the oldest entries.
- **Handoff** (`claude/plugin/skills/handoff/SKILL.md`): before relaying, the lead merges any unmerged `Context learned` items.
  The handoff doc carries one line, `Shared context: ${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`, and
  never copies the entries. The next generation gets them from the hook.

## Changes

| File | Change |
|---|---|
| `board/context.py` (new) | Path resolution, lock, `show`/`path`/`add`. |
| `bin/tmux-ctl` | `context` subcommand calling `board/context.py` with `--project "$FEEDKEY"`. |
| `claude/plugin/scripts/context-inject.sh` (new) | SessionStart injection, cap, off switch, errors let the session start. |
| `claude/plugin/hooks/hooks.json`, `claude/plugin/.claude-plugin/plugin.json` | Register and describe the hook. |
| `claude/orchestrator.md` | `Context learned` in the teammate rules; the lead's merge, prune and condense duties. |
| `claude/plugin/skills/handoff/SKILL.md` | Merge before relay; `Shared context:` line. |
| `docs/INSTALL.md`, `docs/ARCHITECTURE.md` | Name the hook, `TC_CONTEXT=0`, `TC_CONTEXT_DIR`, `tmux-ctl context`, alongside the existing hooks and subcommands (observation #102). |

## Acceptance

- **`board/tests/test_context.py`:**
  - path resolution with and without `TC_CONTEXT_DIR`;
  - the project key matches ideas.py;
  - `add` creates the four-section file and places entries under the right heading;
  - `add` dates an undated entry;
  - an unknown section is refused;
  - concurrent `add` calls under the lock both land.
- **`tools/tests/test_context_inject.zsh`:**
  - no file → no output;
  - small file → injected verbatim with the preface;
  - over the cap → cut at an entry boundary, with the truncation note and path;
  - `TC_CONTEXT=0` → no output;
  - unreadable file or garbage input → exit 0, session starts.
- **`tools/tests/test_plugin.zsh`:**
  - the hook is registered;
  - `orchestrator.md` names `Context learned`;
  - the handoff skill names `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}`.
- **E2E after merge:** a fresh scratch `dev` session with `TC_CONTEXT_DIR` set to a scratch folder.
  - A seeded entry appears in a teammate's first turn.
  - The lead merges one `Context learned` item into the scratch file.
  - The real context folder is untouched.

## Out of scope

- The staleness check that compares `(files: …)` against git history: a later change, and the format already allows it.
- Mining transcripts automatically for context.
- Context shared across projects. Group B, coordinating orchestrators, may need it.
