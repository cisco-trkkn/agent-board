---
name: docs-architecture
description: Use when asked for an "architecture doc", a "system overview", or to "document how X fits together" for a GCP repo (Terraform, GitLab CI, Cloud Run, Pub/Sub, BigQuery), or to refresh such a doc after the repo changed. Architecture and system documentation only, written as a Claude Doc of layered diagrams; not runbooks, how-tos, reports or client explainers.
---

# docs-architecture

Writes an architecture doc as a Claude Doc in which drawn diagrams carry the story, in layers (one glance first, then zoom-ins), in one GCP visual language, with every fact taken from the repo before anyone is asked. A finished doc is a snapshot with a stamp; a later change is a refresh, never a silent regeneration.

Load `anthropic-skills:docs` first and follow it for everything about the Doc itself (birth, one section per call, pending blocks, the widget contract, screenshots, guarded edits). This skill adds the five steps and the hard rules below and restates nothing else.

The first tool call births the Doc, as the docs skill requires: the title, the byline and one `pending` block ("discovering the repo…"). Step 3 fills the frame into it. The Doc is never deleted: a halt replaces that pending block with what was found.

## Hard rules

- **Traceability.** Every drawn node and edge traces to an id in `inventory.json` or to an interview answer. No invented components. The review in step 5 checks it.
- **Zero components halts.** `inventory.py` exits 2 with "0 components — discovery is broken" and the per-extractor counts. Show the counts, fix discovery (wrong path, no `.tf`/`.gitlab-ci.yml`/`Procfile`), never write a doc from nothing.
- **At most 5 interview questions**, seeded from `unknowns[]`, only for what code cannot tell.
- **One section per call** (the docs skill's watch-it-fill rule).
- **A brief before each diagram, a rendered look after it.**
- **Fresh-eyes review before the stamp.** A subagent when one can be spawned; otherwise review it yourself as a demanding outsider, tell the user, and say so in your report.
- **Stamp** `As built from <repo>@<sha>, <date>` and an id map (step 5) close every doc.

## Workflow

### 1. Discover

    python3 <skill root>/scripts/inventory.py <repo> -o inventory.json

Before running it: the scanned path is in a git repo and its tree is clean (`git status --porcelain -- <path>` prints nothing). The script reads the working tree but stamps `meta.sha` = HEAD, so a dirty tree, or no repo at all (`meta.sha` null), would stamp a sha whose committed tree differs. Either way stop and ask; go on only as an **unstamped snapshot** when the user says so (step 5 then writes `As built from <repo>, <date>, unstamped` and no refresh is possible).

Read-only and offline: local git only, never `terraform`, `gcloud`, `glab` or the network. Extractors: `terraform` (resources, modules, IAM, WIF, Pub/Sub pairs), `gitlab_ci` (jobs, environments), `procfile` (service sources). Output: `components[]` `{id, kind, name, project, env, source}`, `edges[]` `{from, to, kind: call|async|iam|trust, label, source}`, `boundaries[]` `{id, kind: org|folder|project|vpc|env, name, members}`, `unknowns[]` `{what, source, why}`, `meta` `{repo, sha, extractors, confidence}`.

- Exit 2 and the discovery-broken message on zero components: halt (hard rule). Replace the Doc's pending block with the per-extractor counts and tell the user.
- `meta.confidence` is `low` when `python-hcl2` is not installed or a `.tf` file fails to parse; each failing file is in `unknowns[]`. Say so in the stamp sentence (step 5) and treat those files' contents as interview material.
- `unknowns[]` is the interview's seed; nothing seen is silently skipped.

### 2. Interview

Ask at most 5 questions, from `unknowns[]` first, then only what code cannot tell: intent, owners, decision rationale, which flows matter most. Each answer is a traceable source (quote it in the id map as `interview:<n>`). No question whose answer is in the repo.

### 3. Outline

Read `references/diagram-set.md` (which diagrams, what each draws, the 12-node split rule) and decide the subsystems from `boundaries[]` and the interview. Create the Doc with the page frame as `pending` blocks, in the order `references/gcp-visual-grammar.md` § Page frame gives: Layer 0 hero context diagram and key-numbers strip; Layer 1 one section per subsystem with its zoom diagram; Layer 2 data flow, trust boundaries, deploy topology; the stamp. Each pending intent names its diagram.

### 4. Draw

Per section, one call each, in reading order:

1. **Brief** — fill the diagram's Brief line from `references/diagram-set.md` and list the inventory ids it will draw; a node with no id and no interview answer is not drawn.
2. **Draw** — modules from `references/svg-modules.md` (prelude, icon node, edges, boundaries, bands, marker), rules from `references/gcp-visual-grammar.md` (colour = category, edge styles, boundary styles, left → right, 12 nodes, key strip). Title = the finding. Widget + embed in one batch.
3. **Look** — the screenshot `read` of the widget; fix clipping, overlaps, faint labels; look again until it reads at a glance.

The key-numbers strip is prose or a small table: services, projects, environments, external dependencies, counted from `inventory.json`.

### 5. Review and stamp

1. Dispatch a fresh-eyes subagent with the Doc link and `inventory.json`. It judges each diagram (right visual for the point, readable at a glance), the structure (the layers read top-down, the page frame is complete and in order, each zoom is linked from its parent) and samples at least 10 nodes, tracing each to an inventory id or interview answer. No subagent available: the fallback in Hard rules. Fix what it finds; redraw and look again.
2. Stamp the last block: `As built from <repo>@<sha>, <date>` (`repo` = the remote's repo name or the directory basename, never a local path; `sha` = `meta.sha`, full; add "inventory confidence low" when it was).
3. Id map: a second tab `Id map` holding one ```json block, `{"<section heading>": {"ids": [...], "diagram": "<widget id>"}}` for every section and diagram, interview answers as `interview:<n>`. It is what refresh reads; keep it out of the main tab.

## Refresh

A doc that already carries a stamp is never regenerated silently; a fresh doc only when the user agrees. Follow `references/refresh.md`: it diffs the repo since the stamp sha and rewrites only the sections the diff touches, leaving the reader's own edits in place.
