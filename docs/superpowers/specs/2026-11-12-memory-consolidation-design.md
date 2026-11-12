# Memory consolidation ("dreaming") and targeted recall

Date: 2026-11-12 · Decided with the user over Discord, 2026-11-12 (near-term item 2 of the "intelligence layer"
review: observe, understand, optimize)
Needs merged: `2026-11-11-discord-controls-design.md` (buttons through the bridge, audit) and
`2026-11-11-discord-files-design.md` (attachments). Runs after `2026-11-12-discord-ops-bot-design.md` in the queue.

## Problem

- The shared context files are far over the 8 KB the SessionStart hook injects
  (`claude/plugin/scripts/context-inject.sh`, `CAP = 8192`): agent-board 33 KB, interiors 39 KB on 2026-11-12. Agents
  get the first 8 KB cut at an entry boundary; most of what was learned never reaches them.
- 24 ledgers with 217 `Ruling:` lines and the morning reports are never distilled. A mistake that recurs across specs
  is noticed only if the lead happens to remember it.
- Loading everything into every agent is the wrong fix: each spec starts 10–20 agents, and re-reading long context is
  already the largest part of the lead's cost (queue metrics). More text also dilutes the entries that matter.

## Decisions (user, 2026-11-12)

- **Memory may be rewritten without asking; rules and skills are only proposed.** The job keeps the core file within
  8 KB and moves the rest to an archive (nothing deleted), posts the diff with a Revert button. Rule, skill and
  workflow changes become ideas or task-observer notes for the user.
- **A small core plus targeted recall**, not a bigger injection: core ≤ 8 KB always; archived entries matched to the
  files a task names, ≤ 4 KB; search on demand.
- Contradictions are flagged, never resolved by the job.

## Design

### 1. Files

Per project `<p>`, in `${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/`:

- `<p>.md`: the core, the same four sections and entry format as today (`- <fact> (files: a, b) · YYYY-MM-DD`),
  at most 8192 bytes.
- `<p>.archive.md`: same sections and format, no size cap; each moved entry gets ` · archived YYYY-MM-DD` and, when
  applicable, ` · stale: <path> gone`.
- `<p>.dream.json`: `{last_run, sources_digest, last_report}`, written by the job.
- Backups `backups/<p>.md.YYYYMMDD-HHMM` and `backups/<p>.archive.md.…`, taken before every run, pruned after 14 days.

`tmux-ctl context add` keeps writing the core. When an add pushes the core over 8 KB it still succeeds and prints
`context: core over 8 KB (<n>), the nightly run will condense it`.

### 2. The nightly run

- launchd job `com.user.agent-board-dream`, 03:30 local, `tmux-ctl context dream --all`;
  `tmux-ctl context dream <project> [--dry-run]` runs one. `TC_DREAM=0` or a `dream.off` file in the context dir
  turns it off.
- Skips a project whose sources digest (sha1 over the core, archive, ledger files, reports, observer log size and the
  repo's HEAD) equals the last run's. Skips the whole night when weekly usage is at or over 85% (the same numbers
  `tmux-ctl awake`/usage alerts read), logging `dream: skipped, weekly <n>%`.
- Per project, one headless run: `claude -p --model sonnet --effort medium` with the prompt in
  `claude/dream.md`, settings `claude/dream-settings.json`: tools Read, Grep, Glob, and Write/Edit limited by
  permission rules to `<context dir>/<p>.md`, `<p>.archive.md` and a scratch output dir; no Bash; `dontAsk`.
  The script around it (not the model) takes the backups, computes the digest, checks the result and posts.
- Inputs given to the model by path: core, archive, the repo's `docs/superpowers/ledgers/*/progress.md` and
  `docs/superpowers/reports/*.md` changed since `last_run`, the task-observer log entries for this project since
  `last_run` (read-only), and `git log --name-status <last_run>..HEAD` written to a scratch file by the script.
- What the model does, in `claude/dream.md`:
  1. Merge duplicate or overlapping entries, keeping the newest date and the union of `files:`.
  2. Mark an entry stale when every file it cites is gone at HEAD (from the scratch git file), and move it to the
     archive.
  3. Flag contradictions between entries in a `contradictions` list in its output; change neither.
  4. Choose the core: the entries most likely to matter to any agent in the project (How to run, the gotchas that
     cost time recently, current decisions), within 8192 bytes; move the rest to the archive.
  5. Distil: rulings or ledger problems that recur in 3+ specs become `proposals` (`{kind: idea|observer, text,
     evidence: [ledger paths and lines]}`); new durable facts from recent ledgers and reports become new entries
     (dated today, with `files:`).
  6. Write `out/report.json`: `{changed: {merged, archived, stale, added}, contradictions, proposals, summary}`.
- Checks by the script after the run, any failure restores both backups and reports `dream: <project> failed —
  <check>`:
  - core ≤ 8192 bytes, four headings present, every line a valid entry;
  - no entry lost: every entry text of the old core and archive is in the new core or archive (after merges, the
    merged entry lists the originals' first 60 characters in the report's `merged` list, which the check accepts);
  - report parses.
- Proposals are not filed by the job. `tmux-ctl context dream-file <project>` files them (ideas via `tmux-ctl idea`,
  observer notes via the task-observer's `scripts/new-observation.sh`), each once.
- The run is recorded with `tmux-ctl metrics` as kind `dream` so its cost shows next to specs.

### 3. Discord

After a run with changes, the board writes one `post` op to the project's home channel, tier `progress`:
`🌙 memory: merged <n>, archived <n>, stale <n>, added <n>; <k> proposals; <c> contradictions` plus the summary,
`files: [diff.txt]` (unified diff of core and archive), and buttons `Revert` (`ab:dream:revert:<project>:<run id>`,
restores that run's backups, audited) and `File proposals` (`ab:dream:file:<project>:<run id>`, runs `dream-file`).
Contradictions add a `decision`-tier line asking the user which entry is right, with both entries quoted.

### 4. Targeted recall

- **Core at start:** `context-inject.sh` unchanged (it injects `<p>.md`, now within the cap).
- **Matched by file at the first prompt:** a new `UserPromptSubmit` hook `context-recall.sh`, registered in
  `claude/plugin/hooks/hooks.json`, runs once per session (marker in the session's state dir): it extracts repo-relative
  paths named in the prompt (tokens that exist under the git toplevel), selects archive entries whose `files:` share a
  path or a parent directory with them, newest first, up to 4096 bytes, and returns them as additional context under
  `Archived project context matching the files in your task:`. Teammates and workers get their brief as the first
  prompt, so this covers them; a lead's first prompt is often a handoff path, which matches nothing and injects
  nothing.
- **Search:** `tmux-ctl context search <words…>` prints matching core and archive entries (all words, case-insensitive),
  each with its section. `claude/worker.md` and `claude/orchestrator.md` gain one line: before relearning something
  about a file, run `tmux-ctl context search`.

## Error handling

- The model run fails, times out (15 min) or a check fails: backups restored, `dream.json` not advanced, one Discord
  line `critical` only if it failed 3 nights running.
- The context dir is written while a lead runs `context add`: the script takes a lock file (`<p>.lock`, `flock`-style
  with `mkdir`), and `context add` waits up to 5 s for it.
- No home channel: the report stays in `out/` and `tmux-ctl context dream-report <project>` prints it.

## Testing

- Checks with fixture cores and archives: over-cap core rejected; lost entry rejected; merged entry accepted; restore
  on failure leaves both files byte-identical to the backups.
- Digest skip; usage-over-85% skip; `--dry-run` writes nothing.
- The model step is replaced in tests by a fake `claude` on PATH that writes fixture outputs (good, over-cap, entry
  lost); one real run on a copy of this project's context dir is the user-gate check.
- `context-recall.sh`: path extraction from a real teammate brief fixture, parent-dir matching, 4 KB cap, once per
  session, nothing for a prompt with no paths.
- `context search`: all-words match, both files, section labels.
- Discord: post op shape, Revert restores the run's backups, File proposals files each once, audit lines.

## Out of scope

- Rewriting rules, skills or CLAUDE.md (proposals only).
- Cross-project knowledge sharing (the federation idea).
- Execution analytics and opportunity discovery (their own specs).
