# docs-compose and the doc-type skills: design

**Status:** approved in brainstorming, 2026-10-20
**Ideas:** `~/.claude/ideas/francisco_ruiz.md` 2026-10-19 23:14 (Claude Docs skills for runbooks/how-tos, project reports/handovers, client-facing explainers), following the merged `docs-architecture` skill (`docs/superpowers/specs/2026-10-20-docs-architecture-skill-design.md`).
**User framing:** "each of the new docs skills need to be created but then when I call claude docs each skill gets used as needed all within the same doc."

## Goal

Ask for any doc, and get **one Claude Doc** whose sections are each written by the skill that knows that kind of writing:

| Type | Skill | Reader | Written from |
| --- | --- | --- | --- |
| architecture | `docs-architecture` (exists; gains guest mode) | engineers | repo inventory, interview |
| runbook / how-to | `docs-runbook` (new) | an operator under pressure | repo scripts, CI, existing runbooks, Terraform outputs, interview |
| report / handover | `docs-report` (new) | whoever inherits or signs off the work | git history + MRs, agent artefacts, interview, read-only live cloud state |
| client explainer | `docs-explainer` (new) | semi-technical TRKKN stakeholders | the Doc's other sections, then interview |

The mix is **ad hoc**: the request decides which types the Doc needs. A **composer** proposes a typed outline, the user confirms it once, and each type skill fills only its own sections.

## Non-goals

- Fixed doc templates (handover pack, etc.). The outline comes from the request each time.
- Editing or forking `anthropic-skills:docs`. Every skill here loads it and follows it for the Doc mechanics.
- Writing to any cloud resource, ever. Cloud access is read-only through one script.
- Running any runbook command. Runbooks are written and reviewed, never executed by the skill.
- The Agent Board artifacts-pane ideas (clickable Docs, specs section, pinned plan): a separate spec.

## Location and files

All in `~/agent-board/claude/skills/`, tracked in git and linked into `~/.claude/skills/` by `bin/claude-config-link`.

| Path | Purpose |
| --- | --- |
| `docs-compose/SKILL.md` | Composer workflow (birth, outline, confirm, delegate, close). Short. |
| `docs-compose/references/guest-contract.md` | The guest brief and the rules every type skill follows as a guest. The single source for those rules; type skills point to it. |
| `docs-compose/references/sources.md` | The `Sources` tab schema and source kinds. |
| `docs-compose/scripts/sources_check.py` | Validates a `Sources` json block; the composer runs it before closing. Stdlib only. |
| `docs-compose/tests/` | Unit tests for `sources_check.py`. |
| `docs-runbook/SKILL.md` | Runbook workflow, shape, rules. |
| `docs-report/SKILL.md` | Report workflow, shape, rules. |
| `docs-report/references/cloud-allowlist.md` | The read-only command allowlist, human-readable, matching the script. |
| `docs-report/scripts/cloud_read.py` | The only path to the cloud: runs an allowlisted read, refuses anything else. Stdlib only. |
| `docs-report/tests/` | Unit tests for `cloud_read.py`. |
| `docs-explainer/SKILL.md` | Explainer workflow, shape, rules. |
| `docs-architecture/SKILL.md`, `references/refresh.md` | Gain guest mode and the `Sources`/`Id map` fallback. |

The trigger is a companion line in `~/.claude/CLAUDE.md`: "Whenever `anthropic-skills:docs` runs, also load `docs-compose`." `~/.claude/CLAUDE.md` is a symlink to the tracked `claude/CLAUDE.md`, so the line is a branch edit that goes live at merge. Each type skill's own description still triggers it alone for a single-type request.

## The composer (`docs-compose`)

1. **Birth.** The first Docs call creates the Doc: title, byline, one `pending` "planning the outline…" block. Loading skills may precede it; no repo read, inventory run or cloud read does.
2. **Outline.** From the request, decide the section types and replace the planning block with **typed pending blocks**, one per section, intent prefixed with its type: `[explainer] What this means for you`, `[architecture] System map`, `[runbook] Rotate the planner WIF binding`, `[report] Migration close-out, 2026-10`. Order is reader-first: an explainer leads, depth follows. A request that needs only one type gets a one-type outline; the composer then hands the whole Doc to that skill as one guest.
3. **Confirm.** One question to the user: the outline, with "go / change". The user may add, drop or reorder sections. No section is written before the yes.
4. **Interview pool.** Before delegating, collect each type skill's interview needs and ask **at most 5 questions per Doc in total**, in one round. Answers are recorded as `interview:<n>` sources available to every guest.
5. **Delegate.** One type skill at a time, in reading order of its first section, each with a **guest brief**. Explainers go last even when they read first, because they derive from the other sections.
6. **Close.** Check that every pending block is filled (none left `pending`), merge the guests' entries into the `Sources` tab, run `sources_check.py` on it, and fix what it reports. A Doc-level line under the title lists the section types and links the `Sources` tab. The composer writes no Doc-level stamp: stamps are per section group.

## The guest contract

**Guest brief** (composer → type skill): Doc id, main tab id, the pending block ids this guest owns, the Doc's audience line, the interview answers, and the current `Sources` json.

A guest:

- **never** births, renames or deletes the Doc, and never edits a block it does not own (the title, other types' sections, the `Sources` tab outside its own entries);
- writes only into its own pending blocks, one section per call;
- runs its own fresh-eyes review over its sections before stamping them;
- ends its section group with its **stamp** (below), as the last block it owns;
- returns its `Sources` entries to the composer and lists anything it could not fill (the block stays with its intent rewritten to say what is missing; never deleted).

**Standalone** (no guest brief): each type skill acts as its own composer for a single-type Doc: it births, writes its outline, confirms only if the request was ambiguous, and writes the `Sources` tab itself. `docs-architecture` standalone is unchanged from today apart from writing `Sources` instead of `Id map`.

**Shared rules** for every type:

- **Traceability.** Every fact traces to a source of an allowed kind. Nothing invented.
- **At most 5 interview questions per Doc** (pooled by the composer as a guest; the skill's own when standalone).
- **Fresh-eyes review before the stamp.** A subagent when one can be spawned; otherwise review as an outsider, tell the user, say so in the report (as in `docs-architecture`).
- **One section per call**, pending blocks first (the docs skill's watch-it-fill rule).

## The `Sources` tab

A second tab named `Sources` holding one ```json block:

```json
{"<section heading>": {"type": "runbook", "stamp": "As of master-gcp-repo@<sha>, 2026-10-20",
                       "sources": ["file:ci/ledger-layer/.gitlab-ci-ledger.yml:35", "interview:2"],
                       "diagram": "<widget id, optional>"}}
```

Source kinds: `file:<path>:<line>`, `inventory:<id>`, `interview:<n>`, `cloud:<n>` (an entry in the report's cloud log, below), `mr:<project>!<iid>`, `commit:<sha>`, `artefact:<path>[:<line>]` (plans, specs, ledgers, handoffs, review reports), `section:<heading>@rev<N>`.

`sources_check.py <file|->` exits 0 when every section has `type` in {architecture, runbook, report, explainer}, a non-empty `stamp`, a non-empty `sources` list, and every source matches one kind's pattern; otherwise exit 1 with one line per problem. `docs-architecture` entries keep today's id-map content (`ids` → `sources` as `inventory:<id>`, `interview:<n>`, `file:` entries).

## `docs-runbook`

**Shape**, one procedure per section: *When to use* (one line) · *Before you start* (access, tools, the exact permissions) · numbered *Steps* with copy-paste commands and, after every risky step, *Expected* output · *If it fails* · *Rollback* · *Verify it worked*. A decision flowchart (same SVG modules, no GCP icons needed) only when the procedure branches.

**Sources:** repo scripts, CI job definitions, existing `docs/runbooks/*`, Terraform outputs and variables, each cited `file:<path>:<line>`; interview for intent and who may run it.

**Rules:** every command in a step exists in a cited file or is a documented CLI form of a cited tool; placeholders are `<UPPER_SNAKE>` with their source named; destructive steps carry a confirm line and their rollback. The review walks every procedure cold, as an operator who has never seen the system.

**Stamp:** `As of <repo>@<sha>, <date>`. **Refresh:** when `git diff --name-only <sha> HEAD` touches a cited file, the procedure is re-checked and rewritten in place; untouched procedures keep their block revisions.

## `docs-report`

**Shape:** *Scope* (what, period, sha or date range) · *Outcome* first · *What changed* (table: MR/commit, change, why) · *What was verified, and how* · *Open risks and owners* · *Next steps*. Optional charts (via the docs skill's chart widgets) from data rows, e.g. pipeline success over the period.

**Sources:**

- git log and MRs over the range: local `git log`, `glab mr list/view` (read-only);
- agent artefacts: plans, specs, SDD ledgers (their `Ruling:` lines), handoff docs, review reports, under `docs/superpowers/` and `~/.claude/handoffs/`;
- interview: outcomes, open risks, owners, what no file records;
- **live cloud state**, read-only, only through `scripts/cloud_read.py`.

**Cloud reads.** `cloud_read.py -- <command…>` runs the command only if it matches the allowlist: `gcloud <group…> describe|list|get-iam-policy …`, `gcloud projects get-ancestors`, `bq show|ls …`, `bq query --dry_run …`, and `bq query` whose SQL is a single `SELECT`/`WITH … SELECT` (no DML/DDL, no `--destination_table`, no scripting). Anything else exits 2 with the reason. Every run appends `{n, command, timestamp, exit, output}` to the report's cloud log (a json file beside the inventory, scratch dir); each fact drawn from it cites `cloud:<n>`. The skill asks the user once per session before its first cloud read, naming the project(s) it will read.

**Stamp:** `Report as of <date>, range <a>..<b>`. **Refresh:** never rewrites a report. It may append a dated `Update <date>` subsection, with its own sources, when the user asks.

## `docs-explainer`

**Shape:** *What it is* · *Why it matters to you* · *How it works*, in plain words, with at most one simple diagram (same GCP grammar, no project ids, ≤ 6 nodes) · *What changes for you* · *Glossary* for the terms that cannot be avoided.

**Sources:** the Doc's other sections first (`section:<heading>@rev<N>`): it derives, it does not re-discover; then the interview. Standalone, it asks for a source Doc or repo and reads it; with a repo it may call `docs-architecture`'s inventory script for counts only.

**Rules:** no claim beyond what its source sections or interview say; every technical term is either translated in place or in the glossary; no internal ids, paths or shas in the body (they stay in `Sources`).

**Stamp:** `Derived from §<heading> rev <N>[, §… rev <M>], <date>`. **Refresh:** when a source section's revision has moved, the explainer says so and re-derives the affected paragraphs; otherwise untouched.

## `docs-architecture` changes

- **Guest mode:** with a guest brief, skip birth and the frame; fill the owned blocks with Layer 0–2 as today; the stamp closes its own section group; return `Sources` entries instead of writing an `Id map` tab.
- **Standalone:** writes `Sources` instead of `Id map`.
- **Refresh** reads `Sources`; when a Doc has no `Sources` tab, it reads `Id map` as today (the Task 9 Doc and any other existing Doc keep working).

## Testing

**Unit (TDD):** `sources_check.py` (valid block; each failure kind: missing type/stamp/sources, bad source pattern, unknown type); `cloud_read.py` (allowed forms; refused `create`, `delete`, `set-iam-policy`, `add-iam-policy-binding`, `bq query` with `INSERT`/`UPDATE`/`DELETE`/`MERGE`/`CREATE`/`DROP`, `--destination_table`, multiple statements; log entry shape) with the command runner behind a seam, plus **one real call** (`gcloud --version`, allowlisted as a harmless probe) per `test-driven-development-extras`.

**End-to-end, real state, user gates** (as Tasks 9/10 of the architecture plan):

1. **Mixed Doc.** One ad hoc request on master-gcp-repo producing explainer + architecture + runbook + report in one Doc. Pass when: the confirm question came before any non-pending section; a block-revision audit shows each guest wrote only its own blocks; `sources_check.py` exits 0 on the `Sources` tab; every section group ends with its own stamp; a fresh reviewer traces 10 sampled facts across all four types and walks one runbook procedure cold; the report's cloud reads ran only after the user's yes and each cites `cloud:<n>`.
2. **Refresh across types.** A real later change to a file a runbook procedure cites (scratch detached worktree, merged locally, never pushed). Pass when: only that procedure's blocks change; the explainer reports its moved source revision and re-derives only the affected paragraphs; the report's blocks keep their revisions; the architecture section changes only if its inventory diff says so.
3. **Regression.** Refresh of the existing Task 9 Doc (`Id map` tab, no `Sources`) still works.

## Delivery

Work in a worktree under `~/agent-board/.claude/worktrees/` (the live checkout is the install). After merge: `bin/claude-config-link` links the four skills; a fresh `claude -p "list your available skills by name only"` lists all four; the companion line in `claude/CLAUDE.md` is live (`grep -c docs-compose ~/.claude/CLAUDE.md` → 1).
