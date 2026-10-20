# GCP visual grammar

The one visual language every diagram in an architecture doc uses: a reader learns it on the hero diagram and reads every zoom-in with it. `svg-modules.md` encodes it as copy-ready modules; the review step checks each diagram against this file.

Page background the colours were checked against: light `#FCFCFB`, dark `#151515` (`--cds-page-bg` on claude.ai, measured 2026-10-20).

## Colour

Colour means product category, nothing else. A node's icon hexagon and its border take the category colour; the box fill stays `none`. The page's `--cds-chart-categorical-*` tokens are not used for categories: four of the eight sit under 3:1 on the light page.

| category | covers | light | dark | contrast light / dark |
|---|---|---|---|---|
| compute | Cloud Run, Cloud Functions | `#1C5CAB` | `#3987E5` | 6.46 / 5.02 |
| data/analytics | BigQuery, Cloud Storage, Cloud SQL, Firestore, Pub/Sub | `#A67000` | `#EDA100` | 4.14 / 8.43 |
| networking | VPC, subnet, Cloud Load Balancing | `#7A3EE0` | `#AB9CF2` | 5.69 / 7.63 |
| security/identity | IAM, service account, Workload Identity Federation, Secret Manager | `#008300` | `#1FA81F` | 4.82 / 5.81 |
| operations | Cloud Build, Artifact Registry, Cloud Scheduler, Logging, Monitoring, CI jobs | `#1A8A8A` | `#2FB8CC` | 4.05 / 7.69 |
| neutral (no category) | people, external systems | `#52514E` | `#C3C2B7` | 7.73 / 10.19 |
| trust-crossing marker | the badge on an edge that crosses a trust boundary | `#C62828` | `#E66767` | 5.48 / 5.65 |

The marker is one red: the spec's "red-amber" is read as the hue family, amber being taken by data/analytics.

Contrast is the WCAG 2 relative-luminance ratio against the page background; the weakest value is 4.05, above the 3:1 non-text minimum. The smallest OKLab distance between any two rows is 15.1 (light) and 15.0 (dark), so no two categories read alike. Neutral equals `var(--cds-text-secondary)` in both themes.

A module writes a category colour once as `light-dark(<light>, <dark>)`; claude.ai sets `color-scheme` per theme (measured), so the browser picks the value. Should the Docs widget refuse a literal hex or `light-dark()`, fall back per category to the page tokens as they render inside the widget frame (measured on a token sheet, Task 7: light / dark): compute `--cds-chart-categorical-1` (#2A78D6 / #3987E5), data/analytics `-2` (#EB6834 / #D95926), networking `-7` (#4A3AA7 / #9085E9), security/identity `-6` (#008300 / #028301), operations `-3` (#1BAF7A / #189E70), neutral `--cds-text-secondary` (#52514E / #C3C2B7), marker `--cds-chart-status-critical` (#D03B3B), edges `--cds-text-secondary`. No two collide; `-4` (#0D366B / #9EC5F4, blue) and `-8` (#E66767, coral) are left out as they sit next to compute and the marker. Contrast is then best-effort: `-2` is 3.12:1 on the light page. Everything else stays on the page tokens: names `var(--cds-text-primary)`, edge labels and notes `var(--cds-text-secondary)`, project fill `var(--cds-chart-reference-tint)`. Edges, arrowheads and the org and VPC outlines take their own pair (Edges): the page's axis token is 1.75:1 on the light page.

Environment bands (see Boundaries) use one page token no category uses, `var(--cds-chart-categorical-5)` (magenta, `#d55181` in both themes inside the widget frame, measured in Task 7), at three strengths: dev fill 0.1 / stroke 0.45, stage 0.2 / 0.7, prod 0.32 / 1. The word carries the meaning, the strength orders it. (The frame's `categorical-4` renders blue, next to compute, so it is not used.)

## Icons

Drawn glyphs in `assets/gcp-icons/` (24×24: a hexagon in the category colour, the symbol in the page colour; not Google's files, see `SOURCE.md` there). Inline the file's SVG in the module; nothing is fetched at render time. The file carries the light values with a `#fff` symbol. For the dark theme the drawing module (`svg-modules.md`, render-checked there) swaps the hexagon fill to the dark token and every `#fff` (the symbol's `fill` and `stroke`) to `#151515`. Symbol-on-hexagon contrast then equals the hexagon-on-page contrast in the table above in dark (same colour), and sits within 0.2 of it in light (`#FFF` symbol, `#FCFCFB` page).

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

A **trust boundary** is any project outline, any org/folder outline, and the line between GCP and the outside (actors, external systems, the CI system). An edge that crosses one carries the marker (Edges).

## Edges

| meaning | inventory kind | line | label |
|---|---|---|---|
| synchronous call | `call` | solid, `strokeWidth 1.25` | protocol: `HTTPS`, `gRPC`, `SQL` |
| async (Pub/Sub, events, schedules) | `async` | dashed `6 4` | the topic or trigger: `topic orders`, `cron 02:00` |
| IAM grant | `iam` | dotted `1.5 3` | the role: `roles/run.invoker` |
| trust (WIF, impersonation) | `trust` | dotted `1.5 3` | the provider or attribute: `gitlab oidc`, `impersonate` |

Every edge ends in an arrowhead in the direction the data moves (one `<marker>` per diagram) and carries a label of at most three words beside the line, never on it.

Edge, arrowhead and org/VPC outline colour is `light-dark(#75736E, #97958D)`, chosen so a line reads on the page and on the project tint it usually crosses (the page's `--cds-chart-axis` is 1.75:1 on the light page, 1.55:1 on the dark one):

| surface | light hex | contrast | dark hex | contrast |
|---|---|---|---|---|
| page (`#FCFCFB` / `#151515`) | `#75736E` | 4.61 | `#97958D` | 6.09 |
| project tint (`#EBEAE9` / `#262625`, the reference tint at 15% over the page) | `#75736E` | 3.94 | `#97958D` | 5.05 |

A pair of nodes with several edges of one kind gets one edge labelled with the count (`3 topics`); edges of different kinds stay separate.

**Trust-boundary crossing:** where an edge crosses a trust boundary, a disc of radius 7 in the marker colour sits on the edge at the boundary line, its `!` in the page colour. The key names it ("crosses a trust boundary"); it is the only red on the page.

## Layout

- Flow runs left → right: actors and ingress on the left, compute in the middle, data on the right; operations and identity below the row they serve.
- At most 12 nodes per diagram. Over 12, split as `diagram-set.md` says for that diagram, and link the zoom from the parent node's label (`Billing → §Billing`).
- Page norms apply: `viewBox 0 0 760 H`, height grows, width does not; positions on a grid of 8 with at least 16 between boxes; node box 184 wide, 56 tall (icon 24 at the left, a 13/600 name and an 11.5 body line: 184 holds the longest product name, Artifact Registry, unabbreviated; three nodes and two gaps fit a 712-wide project box); text 15 / 13 / 11.5, names `fontWeight 600`; corners `rx 8`; strokes 1 to 1.25.
- Connectors run in the gaps, start and end on a box edge, elbow around boxes, never over a label.
- Colour only through the tokens in Colour, so light and dark both render; every `<text>` sets its fill.
- A key strip along the bottom lists the categories on the diagram and the marker when one appears; a diagram with one category has no key.

## Page frame

Every doc, in this order:

1. **Hero context diagram** — the system-context diagram, titled with the one-sentence finding.
2. **Key-numbers strip** — four counts from `inventory.json`: services, projects, environments, external dependencies.
3. **Subsystem sections** — one `##` per subsystem, each opening with its zoom diagram, then the prose that explains it.
4. **Layer-2 diagrams** — data flow, trust boundaries, deploy topology, each in its own section.
5. **Stamp** — `As built from <repo>@<sha>, <date>`, plus the hidden id-map block (section → inventory ids) that refresh mode reads.

Each diagram: title = the finding, a caption under the embed with what the picture is of, a key when colour or the marker carries meaning, and a brief written before it is drawn (`diagram-set.md`).
