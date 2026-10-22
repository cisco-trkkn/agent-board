# GCP visual grammar

The one visual language every diagram in an architecture doc uses: a reader learns it on the hero diagram and reads every zoom-in with it. `svg-modules.md` encodes it as copy-ready modules; the review step checks each diagram against this file.

Page background the colours were checked against: light `#FCFCFB`, dark `#151515` (`--cds-page-bg` on claude.ai, measured 2026-10-20).

## Colour

Colour means product category, nothing else. A node's icon hexagon and its border take the category colour; the box fill stays `none`. Colours are page tokens only (`var(--cds-…)`: the Docs widget accepts no hex), so light and dark both render; the token per category is in the table below and in the `svg-modules.md` prelude.

| category | covers | token | in-frame light / dark | hex measured first (light / dark, contrast) |
|---|---|---|---|---|
| compute | Cloud Run, Cloud Functions | `--cds-chart-categorical-1` | #2A78D6 / #3987E5 | `#1C5CAB` / `#3987E5`, 6.46 / 5.02 |
| data/analytics | BigQuery, Cloud Storage, Cloud SQL, Firestore, Pub/Sub | `--cds-chart-categorical-2` | #EB6834 / #D95926 | `#A67000` / `#EDA100`, 4.14 / 8.43 |
| networking | VPC, subnet, Cloud Load Balancing | `--cds-chart-categorical-7` | #4A3AA7 / #9085E9 | `#7A3EE0` / `#AB9CF2`, 5.69 / 7.63 |
| security/identity | IAM, service account, Workload Identity Federation, Secret Manager | `--cds-chart-categorical-6` | #008300 / #028301 | `#008300` / `#1FA81F`, 4.82 / 5.81 |
| operations | Cloud Build, Artifact Registry, Cloud Scheduler, Logging, Monitoring, CI jobs | `--cds-chart-categorical-3` | #1BAF7A / #189E70 | `#1A8A8A` / `#2FB8CC`, 4.05 / 7.69 (a teal, not the token) |
| neutral (no category) | people, external systems | `--cds-text-secondary` | #52514E / #C3C2B7 | `#52514E` / `#C3C2B7`, 7.73 / 10.19 |
| trust-crossing marker | the badge on an edge that crosses a trust boundary | `--cds-chart-status-critical` | #D03B3B both | `#C62828` / `#E66767`, 5.48 / 5.65 |

The marker is one red: the spec's "red-amber" is read as the hue family, amber and orange being category colours (data/analytics is orange, `-2`). The token mapping is the rule; the last column keeps the hex pairs measured first, for reference only.

Contrast is best-effort with tokens. Measured on the in-frame values against the page (hexagon vs page; the symbol is the page colour, so symbol vs hexagon is the same ratio), light / dark: compute `-1` 4.30 / 5.02, data `-2` 3.12 / 4.70, networking `-7` 8.33 / 5.84, security `-6` 4.82 / 3.70, operations `-3` **2.74** / 5.36, neutral 7.73 / 10.19. Every row clears 3:1 except operations on the light page: 2.74:1, below the 3:1 non-text minimum, so a GitLab, CI job, Artifact Registry or Scheduler hexagon is best effort there and the node's border and name label carry it. No other token fixes it: `-4` (navy / pale blue, 11.64 / 10.21) clears 3:1 but is a blue next to compute, `-8` and the status tokens sit next to the marker or security, `-5` is the env bands. Neutral and edges are `var(--cds-text-secondary)`.

Everything else stays on the page tokens: names `var(--cds-text-primary)`, edge labels and notes `var(--cds-text-secondary)`, project fill `var(--cds-chart-reference-tint)`. Edges, arrowheads and the org and VPC outlines use `var(--cds-text-secondary)`, never the page's axis token (1.75:1 on the light page).

Environment bands (see Boundaries) use one page token no category uses, `var(--cds-chart-categorical-5)` (magenta, `#d55181` in both themes inside the widget frame, measured in Task 7), at three strengths: dev fill 0.1 / stroke 0.45, stage 0.2 / 0.7, prod 0.32 / 1. The word carries the meaning, the strength orders it. (The frame's `categorical-4` renders blue, next to compute, so it is not used.)

## Icons

Drawn glyphs in `assets/gcp-icons/` (24×24: a hexagon in the category colour, the symbol in the page colour; not Google's files, see `SOURCE.md` there). Inline the file's SVG in the module; nothing is fetched at render time. The file carries fixed light values with a `#fff` symbol. In the drawing module (`svg-modules.md`, render-checked there) the hexagon fill is the category token and every `#fff` (the symbol's `fill` and `stroke`) becomes `var(--cds-page-bg)`, so the symbol follows the theme.

One icon per node, 24 px at the node's left, the name to its right. A product with no glyph takes `external-system.svg` and is named in the brief as a gap.

| file | product | category | inventory kind |
|---|---|---|---|
| `cloud-run.svg` | Cloud Run | compute | `cloud_run_service`, `cloud_run_job` |
| `cloud-functions.svg` | Cloud Functions | compute | `cloud_function` |
| `bigquery.svg` | BigQuery | data/analytics | `bigquery_dataset` |
| `cloud-storage.svg` | Cloud Storage | data/analytics | `gcs_bucket` |
| `cloud-sql.svg` | Cloud SQL | data/analytics | `cloud_sql` |
| `firestore.svg` | Firestore | data/analytics | `firestore` |
| `pubsub.svg` | Pub/Sub | data/analytics | `pubsub_topic`, `pubsub_subscription` |
| `vpc.svg` | VPC | networking | `vpc`, `subnet`: the glyph sits in the VPC outline's label (Boundaries), never as a node |
| `cloud-load-balancing.svg` | Cloud Load Balancing | networking | interview answer (no extractor yet) |
| `iam.svg` | IAM | security/identity | the grantee of an `iam` edge when it is a role, not a principal |
| `service-account.svg` | Service Account | security/identity | `service_account` |
| `workload-identity-federation.svg` | Workload Identity Federation | security/identity | `wif_pool`, `wif_provider` |
| `secret-manager.svg` | Secret Manager | security/identity | `secret` |
| `cloud-build.svg` | Cloud Build | operations | interview answer (no extractor yet) |
| `artifact-registry.svg` | Artifact Registry | operations | `artifact_registry` |
| `cloud-scheduler.svg` | Cloud Scheduler | operations | `scheduler_job` |
| `cloud-logging.svg` | Cloud Logging | operations | `log_metric` |
| `cloud-monitoring.svg` | Cloud Monitoring | operations | `alert_policy` |
| `ci-job.svg` | CI job | operations | `ci_job`, `service_source` |
| `gitlab.svg` | GitLab | operations | the CI system as a whole (one node) |
| `user.svg` | User | neutral | interview answer |
| `external-system.svg` | External system | neutral | interview answer, or a product with no glyph |

`project` and `vpc` are boundaries, never nodes; `vpc.svg` marks the VPC outline's label. Names are drawn unabbreviated as in this table, with two short forms: Workload Identity Federation is drawn as `WIF pool` / `WIF provider` (its inventory kinds) and Cloud Load Balancing as `Load Balancing`. Two glyphs are single-colour (no hexagon): `user.svg` and `external-system.svg`, in the neutral colour.

## Boundaries

| boundary | inventory kind | drawing |
|---|---|---|
| organisation / folder | `org`, `folder` | dashed outline (`strokeDasharray 6 4`, `strokeWidth 1.25`) in the edge pair (Edges), no fill; name top-left |
| project | `project` | rounded box `rx 8`, fill `var(--cds-chart-reference-tint)`, no stroke; label is the project id, `<tenant>-prod` |
| VPC / subnet | `vpc` | thin solid outline (`strokeWidth 1`) in the edge pair (Edges), no fill; `vpc.svg` then the name top-left. A `subnet` component is the same thin outline nested inside its VPC, boundary kind `vpc` |
| environment | `env` | a pill behind the boundary label in the env token from Colour at that env's strength, the env word in capitals: `DEV`, `STAGE`, `PROD` |

Boundaries nest in that order: org/folder around projects, VPC inside a project. Children sit 16 in from the box sides and 16 above its foot; the name line takes 32. A boundary with one child is still drawn when a trust or project edge crosses it, and dropped otherwise.

A **trust boundary** is any project outline, any org/folder outline, and the line between GCP and the outside (actors, external systems, the CI system). An edge that crosses one carries the marker (Edges), except in the deploy topology, where only the deploy identity's `trust` edge carries it, once (`diagram-set.md`).

## Edges

| meaning | inventory kind | line | label |
|---|---|---|---|
| synchronous call | `call` | solid, `strokeWidth 1.25` | protocol: `HTTPS`, `gRPC`, `SQL` |
| async (Pub/Sub, events, schedules) | `async` | dashed `6 4` | the topic or trigger: `topic orders`, `cron 02:00` |
| IAM grant | `iam` | dotted `1.5 3` | the role: `roles/run.invoker` |
| trust (WIF, impersonation) | `trust` | dotted `1.5 3` | the provider or attribute: `gitlab oidc`, `impersonate` |

Every edge ends in an arrowhead in the direction the data moves (one `<marker>` per diagram) and carries a label of at most three words beside the line, never on it.

Edge, arrowhead and org/VPC outline colour is `var(--cds-text-secondary)`: 7.73:1 light / 10.19:1 dark on the page, so a line reads on the page and on the project tint it usually crosses. The page's `--cds-chart-axis` is too faint (1.75:1 light, 1.55:1 dark).

A pair of nodes with several edges of one kind gets one edge labelled with the count (`3 topics`); edges of different kinds stay separate.

**Trust-boundary crossing:** where an edge crosses a trust boundary, a disc of radius 7 in the marker colour sits on the edge at the boundary line, its `!` in the page colour. The key names it ("crosses a trust boundary"); the disc with its `!` is told apart by shape and placement (on an edge, at the boundary line), not by hue alone: against the data colour its luminance contrast is only 1.50:1 light / 1.24:1 dark.

## Layout

- Flow runs left → right: actors and ingress on the left, compute in the middle, data on the right; operations and identity below the row they serve.
- At most 12 nodes per diagram; a node is a drawn product, actor or subsystem box (project, org and VPC outlines and env bands do not count). Over 12, split as `diagram-set.md` says for that diagram, and name the zoom in the parent node's label (`Billing → §Billing`; widget text holds no link, the key explains `§`).
- Page norms apply: `viewBox 0 0 760 H`, height grows, width does not; positions on a grid of 8 with at least 16 between boxes; node box 184 wide, 56 tall (icon 24 at the left, a 13/600 name and an 11.5 body line: 184 holds the longest product name, Artifact Registry, unabbreviated; three nodes and two gaps fit a 712-wide project box); text 15 / 13 / 11.5, names `fontWeight 600`; corners `rx 8`; strokes 1 to 1.25.
- Connectors run in the gaps, start and end on a box edge, elbow around boxes, never over a label.
- Colour only through the tokens in Colour, so light and dark both render; every `<text>` sets its fill.
- A key strip along the bottom lists the categories on the diagram and the marker when one appears; a diagram with one category has no key.

## Page frame

Every doc, in this order:

1. **Hero context diagram** — the system-context diagram, titled with the one-sentence finding.
2. **Key-numbers strip** — four counts: services, projects, environments from `inventory.json` (projects as distinct resolved ids), external dependencies from the interview or `file:` sources.
3. **Subsystem sections** — one `##` per subsystem, each opening with its zoom diagram, then the prose that explains it.
4. **Layer-2 diagrams** — data flow, trust boundaries, deploy topology, each in its own section.
5. **Stamp** — `As built from <repo>@<sha>, <date>`, plus the `Sources` entries (SKILL.md step 5.3; section → its sources) that refresh mode reads: the `Sources` tab when standalone, entries returned to the composer as a guest.

Each diagram: title = the finding, a caption under the embed with what the picture is of, a key when colour or the marker carries meaning, and a brief written before it is drawn (`diagram-set.md`).
