---
name: docs-architecture
description: Use when asked for an "architecture doc", a "system overview", or to "document how X fits together" for a GCP repo (Terraform, GitLab CI, Cloud Run, Pub/Sub, BigQuery), or to refresh one. Architecture docs only, as layered diagrams in a Claude Doc; not runbooks, reports or explainers.
---

# docs-architecture

Writes an architecture doc as a Claude Doc in which drawn diagrams carry the story, in layers (one glance first, then zoom-ins), in one GCP visual language, with every fact taken from the repo before anyone is asked. A finished doc is a snapshot with a stamp; a later change is a refresh, never a silent regeneration.

Load `anthropic-skills:docs` first and follow it for everything about the Doc itself (birth, one section per call, pending blocks, the widget contract, screenshots, guarded edits). This skill adds the five steps and the hard rules below and restates nothing else.

The first **Docs** call, before the inventory run or any repo read, births the Doc (title, byline, one `pending` "discovering the repo…" block); loading this skill and `anthropic-skills:docs` may precede it. Step 3 replaces that block with the frame. The Doc is never deleted: a halt replaces that pending block with what was found.

**Guest mode.** Handed a guest brief by `docs-compose`, follow `../docs-compose/references/guest-contract.md` and change only this: skip the birth; step 1 reuses an `inventory.json` listed under the brief's discovery artefacts; step 2 takes the brief's interview answers; step 3 lays Layer 0–2 out in the owned blocks instead of building the page frame; step 5's stamp is the last block of the architecture group, and step 5.3 returns `Sources` entries instead of writing the tab. Without a brief, the skill runs standalone as written below.

## Hard rules

- **Traceability.** Every drawn node and edge traces to an id in `inventory.json`, to an interview answer, or to a `file:<path>:<line>` the repo shows (for what the inventory lacks, such as a `gcloud run deploy` line). No invented components. The review in step 5 checks it.
- **Zero components halts.** `inventory.py` exits 2 with "0 components — discovery is broken" and the per-extractor counts. Show the counts, fix discovery (wrong path, no `.tf`/`.gitlab-ci.yml`/`Procfile`), never write a doc from nothing.
- **At most 5 interview questions**, seeded from `unknowns[]`, only for what code cannot tell.
- **One section per call** (the docs skill's watch-it-fill rule).
- **A brief before each diagram, a rendered look after it.**
- **Fresh-eyes review before the stamp.** A subagent when one can be spawned; otherwise review it yourself as a demanding outsider, tell the user, and say so in your report.
- **Stamp** `As built from <repo>@<sha>, <date>` and its `Sources` entries (step 5) close every doc.

## Workflow

### 1. Discover

    python3 <skill root>/scripts/inventory.py <repo> -o inventory.json

Before running it: the scanned path is in a git repo and its tree is clean (`git status --porcelain -- <path>` prints nothing). To scan a dirty checkout, scan a detached worktree of its HEAD instead: `git worktree add --detach <tmp> HEAD`, run there, `git worktree remove <tmp>` after. The script reads the working tree but stamps `meta.sha` = HEAD, so a dirty tree, or no repo at all (`meta.sha` null), would stamp a sha whose committed tree differs. Either way stop and ask; go on only as an **unstamped snapshot** when the user says so (step 5 then writes `As built from <repo>, <date>, unstamped` and no refresh is possible).

Read-only and offline: local git only, never `terraform`, `gcloud`, `glab` or the network. Extractors: `terraform` (resources, modules, IAM, WIF, Pub/Sub pairs), `gitlab_ci` (jobs; an environment only where a job sets one), `procfile` (service sources). CI call edges come only from `terraform -chdir=<dir>` (or `cd <dir>`) lines, so wrapper scripts yield none: take those from the interview or a `file:` source. Output: `components[]` `{id, kind, name, project, env, source}`, `edges[]` `{from, to, kind: call|async|iam|trust, label, source}`, `boundaries[]` `{id, kind: org|folder|project|vpc|env, name, members}`, `unknowns[]` `{what, source, why}`, `meta` `{repo, sha, extractors, confidence}`.

- Exit 2 and the discovery-broken message on zero components: halt (hard rule). Replace the Doc's pending block with the per-extractor counts and tell the user.
- `meta.confidence` is `low` when `python-hcl2` is not installed or a `.tf` file fails to parse; each failing file is in `unknowns[]`. Say so in the stamp sentence (step 5) and treat those files' contents as interview material.
- `unknowns[]` is the interview's seed; nothing seen is silently skipped.

### 2. Interview

Ask at most 5 questions, from `unknowns[]` first, then only what code cannot tell: intent, owners, decision rationale, which flows matter most. Each answer is a traceable source (cite it in its section's `Sources` entry as `interview:<n>`, step 5.3). No question whose answer is in the repo: cite that line as a `file:<path>:<line>` source instead.

### 3. Outline

Read `references/diagram-set.md` (which diagrams, what each draws, the 12-node split rule) and decide the subsystems from `boundaries[]` and the interview. Replace the discovering block with the page frame as `pending` blocks, in the order `references/gcp-visual-grammar.md` § Page frame gives: Layer 0 hero context diagram and key-numbers strip; Layer 1 one section per subsystem with its zoom diagram; Layer 2 data flow, trust boundaries, deploy topology; the stamp. Each pending intent names its diagram. As a guest, the same frame goes into the owned blocks (Guest mode above).

### 4. Draw

Per section, one call each, in reading order:

1. **Brief** — fill the diagram's Brief line from `references/diagram-set.md` and list the inventory ids it will draw; a node with no id and no interview answer is not drawn.
2. **Draw** — modules from `references/svg-modules.md` (prelude, icon node, edges, boundaries, bands, marker), rules from `references/gcp-visual-grammar.md` (colour = category, edge styles, boundary styles, left → right, 12 nodes, key strip). Title = the finding. Widget + embed in one batch.
3. **Look** — the screenshot `read` of the widget; fix clipping, overlaps, faint labels; look again until it reads at a glance.

The key-numbers strip is prose or a small table: services, projects, environments, external dependencies. Services, environments and projects count from `inventory.json`, projects as distinct *resolved* ids (when variable-driven, print the count with "per root module, ids variable-driven" or leave it out); external dependencies come from the interview or `file:` sources, the inventory has no external kind.

### 5. Review and stamp

1. Dispatch a fresh-eyes subagent with the Doc link and `inventory.json`. It judges each diagram (right visual for the point, readable at a glance), the structure (the layers read top-down, the page frame is complete and in order, each zoom is named in its parent node's label) and samples at least 10 nodes, tracing each to an inventory id or interview answer. No subagent available: the fallback in Hard rules. Fix what it finds; redraw and look again.
2. Stamp the last block: `As built from <repo>@<sha>, <date>` (`repo` = `meta.repo`, a name never a path; `sha` = `meta.sha`, full; add "inventory confidence low" when it was).
3. Sources: one entry per section, in the schema of `../docs-compose/references/sources.md`: `{"type": "architecture", "stamp": "<the step 5.2 stamp>", "sources": [...], "diagram": "<widget id>"}`, each inventory id as `inventory:<id>`, interview answers as `interview:<n>`, file sources as `file:<path>:<line>`. Standalone: write them as a second tab `Sources` holding one ```json block and check it with `python3 <skills dir>/docs-compose/scripts/sources_check.py <file|->` until it exits 0. Guest: return them to the composer. It is what refresh reads; keep it out of the main tab.

## Refresh

A doc that already carries a stamp is never regenerated silently; a fresh doc only when the user agrees. Follow `references/refresh.md`: it reads the `Sources` tab (an older Doc's `Id map` tab when it has no `Sources`), diffs the repo since the stamp sha and rewrites only the architecture sections the diff touches, leaving the reader's own edits in place.
