# docs-architecture skill: design

**Status:** approved in brainstorming, 2026-10-19/20
**Idea:** `~/.claude/ideas/francisco_ruiz.md`, 2026-10-17 04:42 ("extend the claude docs skill … beautiful, engaging, visually immersive technical documentation")
**Follow-ups filed as an idea:** sibling skills for runbooks/how-tos, project reports/handovers and client-facing explainers. This skill is the pattern for them.

## Goal

A local skill that makes Claude write **architecture and system documentation** as Claude Docs. Three things are missing from today's output, and the skill owns all three equally:

1. **Diagrams carry the story.** Every major concept is a drawn diagram with one consistent visual language, never a bullet list.
2. **Layered reading.** A one-glance overview first, then zoom-in sections; the reader can stop at any depth.
3. **Identity.** A recognisable house style, built on **Google Cloud's architecture-diagram visual language**.

Facts come **from the repo first**, then from a short interview. Docs are **snapshots with a refresh mode**.

## Non-goals

- Runbooks, reports and client explainers (separate future skills).
- CI-driven regeneration.
- Non-GCP clouds.
- Editing or forking `anthropic-skills:docs`. This skill loads it and adds to it.

## Location and files

`~/agent-board/claude/skills/docs-architecture/`, tracked in git and linked into `~/.claude/skills/` by `bin/claude-config-link`.

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Triggers ("architecture doc", "system overview", "document how X fits together"), the 5-step workflow, hard rules. Short. Loads `anthropic-skills:docs` first. |
| `references/gcp-visual-grammar.md` | Colour, icon, shape and line semantics; layout limits; page frame. |
| `references/diagram-set.md` | The layered diagram catalogue: what each diagram is for, what goes on it, when to draw it. |
| `references/svg-modules.md` | Copy-ready `claude.Visualize` module snippets: icon node, labelled edge, boundary box, environment band, swimlane, trust-crossing marker. |
| `references/refresh.md` | Refresh-mode procedure. |
| `assets/gcp-icons/*.svg` | About 30 curated product icons, inlined by the modules. |
| `scripts/inventory.py` | Repo → `inventory.json` (read-only, offline). |
| `tests/` | `unittest` suite for the script, with fixtures captured from a real repo. |

## Workflow (each step gated)

1. **Discover.** Run `scripts/inventory.py <repo>` and read `inventory.json`. If it finds zero components, discovery is broken: halt and show the per-extractor counts.
2. **Interview.** At most 5 questions, seeded from `unknowns[]`, and only for what code cannot tell: intent, owners, decision rationale, which flows matter most.
3. **Outline.** Create the doc with its frame as `pending` blocks:
   - **Layer 0:** hero context diagram plus a key-numbers strip (services, projects, environments, external dependencies).
   - **Layer 1:** one section per subsystem, each with its own zoom diagram.
   - **Layer 2:** data flow, trust boundaries, deploy topology.
4. **Draw.** One section per call (the docs skill's watch-it-fill rule). Each diagram gets a written brief first (reader, decision, one-sentence finding, what an expert would draw). Draw from `svg-modules.md`, then do a rendered screenshot look.
5. **Review and stamp.** A fresh-eyes subagent reviews each diagram and the structure: right visual for the point, readable at a glance, traceability. Then stamp the doc: `As built from <repo>@<sha>, <date>`. A hidden id-map block records which inventory ids each section and diagram drew.

**Hard rule:** every drawn node and edge traces to an inventory entry or an interview answer. No invented components. The review step checks this.

## Visual grammar (GCP)

- **Icons.** About 30 official Google Cloud product icons, the ones these repos use: Cloud Run, Cloud Functions, Pub/Sub, BigQuery, Cloud Storage, Artifact Registry, Secret Manager, IAM, Workload Identity Federation, VPC, Cloud Load Balancing, Cloud Build, Cloud Scheduler, Firestore, Cloud SQL and similar. Add generic GitLab/CI and external-system glyphs. They are inlined as SVG, with no external fetches at render time. **Plan task 1 verifies the icons' source and licence terms before anything is committed. The fallback is drawn category glyphs in GCP colours.**
- **Node colour = product category** (GCP convention: compute, data/analytics, networking, security/identity, operations). Colour is never decorative.
- **Boundaries:**
  - organisation/folder: dashed outline
  - project: light-grey filled rounded box labelled with the project id
  - VPC/subnet: thin solid outline
  - environment (dev/stage/prod): coloured band on the boundary label
- **Edges:**
  - solid: synchronous call
  - dashed: async (Pub/Sub, events)
  - dotted: IAM grant or trust
  - every edge has an arrow head for data direction and a short label (protocol or topic)
- **Trust-boundary crossings** carry a red-amber marker.
- **Layout.** Flow runs left → right (ingress → compute → data). A diagram has at most 12 nodes; larger systems split into zoom-ins, linked from the parent node's label. Use the page's theme tokens so light and dark both work.
- **Page frame (every doc):** hero context diagram → key-numbers strip → subsystem sections with zoom diagrams → layer-2 diagrams → stamp.

## Inventory helper: `scripts/inventory.py`

- **Invocation:** `inventory.py <repo> [--since <sha>] [-o inventory.json]`.
- **Dependencies:** Python standard library. `python-hcl2` is used when it is installed; otherwise a regex scanner runs and the output is marked `"confidence": "low"`.
- **Read-only and offline.** It never runs `terraform`, `gcloud`, `glab` or any network call.
- **Output schema:**
  - `components[]`: `{id, kind, name, project, env, source: "file:line"}`
  - `edges[]`: `{from, to, kind: call|async|iam|trust, label, source}`
  - `boundaries[]`: `{id, kind: org|folder|project|vpc|env, name, members[]}`
  - `unknowns[]`: `{what, source, why}`. Anything seen but not resolved: variable-driven ids, registry modules, unparseable files. Never silently skipped.
  - `meta`: `{repo, sha, extractors: {name: count}, confidence}`
- **Extractors** (one module each, pluggable): Terraform resources/modules; `.gitlab-ci.yml` jobs and environments; Cloud Run/Functions service manifests; Pub/Sub topic↔subscription pairs; IAM/WIF bindings.
- **`--since <sha>`** emits `added/removed/changed` for components and edges between `<sha>` and HEAD.

## Refresh mode

1. Read the doc's stamp sha and the hidden id map.
2. Run `inventory.py --since <sha>`.
3. Map each diff entry to the sections and diagrams that drew it. Rewrite only those, one section per call.
4. Leave every other block untouched, including the user's own edits. A guard mismatch means their edit wins (docs-skill rule).
5. Add a `Changed since <date>` row (date · change · section) and move the stamp to the new sha.

## Testing and acceptance

- **Script unit tests** (`unittest`). The fixtures are trimmed copies of real master-gcp-repo Terraform and CI files, never hand-written ones. The tests check:
  - each extractor finds the known components and edges with the correct `file:line`
  - `--since` detects an added service and a removed IAM binding (in a scratch git repo)
  - empty input halts and unparseable input lands in `unknowns[]`, never as an empty success
- **Module render check.** Each snippet in `svg-modules.md` is rendered in a real Doc, with the screenshot read back, in light and dark.
- **End-to-end on real, aged state:**
  1. Generate an architecture doc for **master-gcp-repo at current `dev3`**. It needs a hero diagram, at least 3 subsystem sections each with a zoom diagram, a trust-boundary diagram showing the WIF/planner path, and the key-numbers strip.
  2. A fresh-eyes reviewer samples 10 nodes and traces each one to the repo (all 10 must trace), then judges each diagram's at-a-glance point.
  3. **Refresh:** in a scratch checkout, merge one security branch locally, hand-edit one untouched section of the doc, then re-run. Only the affected sections may change, and the hand-edit must survive.

## Open questions

None blocking. The icon licence and source are verified in plan task 1, with the fallback defined above.
