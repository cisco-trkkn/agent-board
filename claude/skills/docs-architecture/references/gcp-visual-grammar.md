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

Contrast is the WCAG 2 relative-luminance ratio against the page background; the weakest value is 4.05, above the 3:1 non-text minimum. The smallest OKLab distance between any two rows is 15.1 (light) and 15.0 (dark), so no two categories read alike. Neutral equals `var(--cds-text-secondary)` in both themes.

A module writes a category colour once as `light-dark(<light>, <dark>)`; claude.ai sets `color-scheme` per theme (measured), so the browser picks the value. Everything else stays on the page tokens: names `var(--cds-text-primary)`, edge labels and notes `var(--cds-text-secondary)`, lines and arrowheads `var(--cds-chart-axis)`, project fill `var(--cds-chart-reference-tint)`.

Environment bands (see Boundaries) use page tokens that no category uses: dev `var(--cds-chart-categorical-3)`, stage `var(--cds-chart-categorical-4)`, prod `var(--cds-chart-categorical-5)`. A band is a fill at `fillOpacity 0.18` under a text-primary label, so the token's own contrast does not carry the word.

## Icons

Drawn glyphs in `assets/gcp-icons/` (24×24: a hexagon in the category colour, the symbol in the page colour; not Google's files, see `SOURCE.md` there). Inline the file's SVG in the module; nothing is fetched at render time. The file carries the light values with a `#fff` symbol. For the dark theme the module swaps the hexagon fill to the dark token and every `#fff` (the symbol's `fill` and `stroke`) to `#151515`; because the symbol is the page colour, symbol-on-hexagon contrast equals the hexagon-on-page contrast in the table above.

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
| `vpc.svg` | VPC | networking | `vpc`, `subnet` |
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

`project` is a boundary, never a node. Two glyphs are single-colour (no hexagon): `user.svg` and `external-system.svg`, in the neutral colour.

## Boundaries

| boundary | inventory kind | drawing |
|---|---|---|
| organisation / folder | `org`, `folder` | dashed outline (`strokeDasharray 6 4`), `--cds-chart-axis`, no fill; name top-left |
| project | `project` | rounded box `rx 8`, fill `var(--cds-chart-reference-tint)`, no stroke; label is the project id, `<tenant>-prod` |
| VPC / subnet | `vpc` | thin solid outline (`strokeWidth 1`), `--cds-chart-axis`, no fill; name top-left |
| environment | `env` | a band behind the boundary label (`fillOpacity 0.18`, the env token from Colour), the env word in capitals: `DEV`, `STAGE`, `PROD` |

Boundaries nest in that order: org/folder around projects, VPC inside a project. Children sit 16 in from the box sides and 16 above its foot; the name line takes 32. A boundary with one child is still drawn when a trust or project edge crosses it, and dropped otherwise.

A **trust boundary** is any project outline, any org/folder outline, and the line between GCP and the outside (actors, external systems, the CI system). An edge that crosses one carries the marker (Edges).

## Edges

| meaning | inventory kind | line | label |
|---|---|---|---|
| synchronous call | `call` | solid, `strokeWidth 1.25` | protocol: `HTTPS`, `gRPC`, `SQL` |
| async (Pub/Sub, events, schedules) | `async` | dashed `6 4` | the topic or trigger: `topic orders`, `cron 02:00` |
| IAM grant | `iam` | dotted `1.5 3` | the role: `roles/run.invoker` |
| trust (WIF, impersonation) | `trust` | dotted `1.5 3` | the provider or attribute: `gitlab oidc`, `impersonate` |

Every edge ends in an arrowhead in the direction the data moves (one `<marker>` per diagram, `--cds-chart-axis`) and carries a label of at most three words beside the line, never on it. A pair of nodes with several edges of one kind gets one edge labelled with the count (`3 topics`); edges of different kinds stay separate.

**Trust-boundary crossing:** where an edge crosses a trust boundary, a disc of radius 7 in the marker colour sits on the edge at the boundary line, its `!` in the page colour. The key names it ("crosses a trust boundary"); it is the only red on the page.

## Layout

- Flow runs left → right: actors and ingress on the left, compute in the middle, data on the right; operations and identity below the row they serve.
- At most 12 nodes per diagram. Over 12, split as `diagram-set.md` says for that diagram, and link the zoom from the parent node's label (`Billing → §Billing`).
- Page norms apply: `viewBox 0 0 760 H`, height grows, width does not; positions on a grid of 8 with at least 16 between boxes; node box 156 wide, 48 tall (icon 24 + name) or taller with body lines; text 15 / 13 / 11.5, names `fontWeight 600`; corners `rx 8`; strokes 1 to 1.25.
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
