# Diagram set

Five diagrams make the layered reading: Layer 0 is the system context, Layer 1 one subsystem zoom per subsystem, Layer 2 the data flow, trust boundaries and deploy topology. Every drawn node and edge traces to an inventory id, an interview answer or a `file:<path>:<line>` source; the brief names the ids before the diagram is drawn, and the review step checks the trace.

Shared rules: `gcp-visual-grammar.md` for colour, icons, boundaries, edges and layout; at most 12 nodes; the title is the finding, not the topic. The **Brief** line is the one-sentence template to fill, with `<reader>` the person the section is written for, `<decision>` what they will do with it and `<finding>` what one glance should tell them. Component kinds below are the `kind` values `inventory.py` emits.

## System context

**Answers:** What is this system, who and what talks to it, and what does it depend on outside its own projects?

**Draws:** one node per subsystem (an interview-named group of components, or a project when the interview named none), every actor (`user.svg`), every external system (`external-system.svg`), the CI system as one node (`gitlab.svg`). Edges: `call` and `async` between those nodes, collapsed to one edge per pair and kind, labelled with the protocol or topic. Boundaries: project boxes; the env band when more than one env is in view.

**Omits:** `iam` and `trust` edges, topics and subscriptions, secrets, service accounts, monitoring, anything inside a subsystem.

**Split when:** more than 12 nodes. Group components by project, then by interview-named subsystem, until the count fits; every group becomes a Layer-1 zoom and the parent node's label names that section (`§Billing`; the key explains `§`). Actors and external systems are never grouped away: drop a subsystem into its neighbour before dropping an actor.

**Brief:** `<reader>` deciding `<decision>` should see at a glance that `<finding>`; draw `<N>` subsystem boxes left to right in flow order with the actors on the left and the external dependencies on the right edge.

## Subsystem zoom

**Answers:** Inside `<subsystem>`, which services do the work, what data do they hold, and what triggers them?

**Draws:** the subsystem's components of kinds `cloud_run_service`, `cloud_run_job`, `cloud_function`, `pubsub_topic` (its `pubsub_subscription` folded into the `async` edge), `bigquery_dataset`, `gcs_bucket`, `cloud_sql`, `firestore`, `scheduler_job`, and `secret` only when the interview says it matters, inside the project box `<tenant>-<env>`. Edges: `call` and `async` with their labels. The ingress (load balancer, actor or calling subsystem) on the left edge; stores on the right.

**Omits:** `iam` and `trust` edges (trust boundaries), `ci_job`, `service_account`, `alert_policy`, `log_metric`, other subsystems beyond the one node that calls in.

**Split when:** more than 12 nodes. Split by flow (ingest vs serve) or by trigger (scheduled vs event-driven), each half its own diagram under the same section heading, the ingress node repeated in both so each reads alone.

**Brief:** `<reader>` deciding `<decision>` should see at a glance that `<finding>`; draw the `<N>` services of `<subsystem>` between their trigger on the left and their `<M>` stores on the right, with the topic that joins them.

## Data flow

**Answers:** For the flow the interview ranked first, where does a record enter, what transforms it, and where does it land?

**Draws:** one flow per diagram: its source (actor, external system or `scheduler_job`), every `pubsub_topic` and compute component it passes through, and the store it lands in, in order; `call` and `async` edges numbered in their labels (`1 HTTPS`, `2 topic orders`). A swimlane per project when the flow crosses projects, a swimlane per env when the interview says envs differ.

**Omits:** components the flow does not touch, `iam` and `trust` edges, boundaries the flow does not cross, retries and error paths unless the interview named them.

**Split when:** more than one flow, or more than 12 nodes on one flow. One diagram per flow; a long flow splits at a store (the first diagram ends on it, the second starts on it).

**Brief:** `<reader>` deciding `<decision>` should see at a glance that `<finding>`; draw the `<flow>` as `<N>` numbered steps from `<source>` to `<store>`, left to right, one lane per project it crosses.

## Trust boundaries

**Answers:** Who can act as whom, across which boundary, and where does an external identity enter GCP?

**Draws:** every principal: `service_account`, `wif_pool` with its `wif_provider`, and the `ci_job` that uses it (the external principal); the components they are granted on. Edges: `iam` (dotted, label = role) and `trust` (dotted, label = provider or attribute condition). Boundaries: org/folder dashed, project boxes, the line between GCP and the outside; every crossing carries the marker.

**Omits:** `call` and `async` edges, stores and services no grant targets, `alert_policy`, `log_metric`, topics.

**Split when:** more than 12 nodes. One diagram per principal family: the deploy path (CI job → WIF → deploy service account → projects) and the runtime path (service accounts → the resources they read and write), each with its own marker crossings.

**Brief:** `<reader>` deciding `<decision>` should see at a glance that `<finding>`; draw `<N>` principals on the left crossing `<M>` marked boundaries to the resources they are granted on, roles on the edges.

## Deploy topology

**Answers:** How does a change reach each environment, and what runs where?

**Draws:** the CI system (`gitlab.svg`), one `ci_job` node per stage, `artifact_registry`, one project box per env with its env band (`DEV` → `STAGE` → `PROD` left to right), and inside each the runtime components the pipeline deploys, collapsed to one node per service. Edges: `call` labelled with the tool (`terraform apply`, `gcloud run deploy`, `docker push`); the deploy identity's `trust` edge drawn once, and it alone carries the marker; the `call` deploy edges from CI jobs ride on that crossing unmarked, and the key says so.

**Omits:** runtime data paths, topics, stores the pipeline does not create, every `iam` edge but the deploy identity's.

**Split when:** more than 12 nodes. Collapse jobs into stages first; still over, one diagram per env with the pipeline repeated at its left.

**Brief:** `<reader>` deciding `<decision>` should see at a glance that `<finding>`; draw the pipeline's `<N>` stages feeding `<M>` environments left to right, with what each stage deploys and the one trust crossing that lets it.
