# Platform pipeline-events bus. Tenant transform jobs publish transformation
# completion/failure events here, MLOps jobs publish model events, and extraction jobs publish extraction_complete
# and backfill_complete; the ledger records every event via an authenticated push
# subscription. extraction-routing.tf also pushes the extraction events to the
# transformation layer. Tenant transform SAs get topic-level publisher from
# ci/scripts/tf-utils/grant-org-access.sh.

locals {
  # Must be the org project: tenant jobs publish to
  # projects/$ORG_CLOUDSDK_CORE_PROJECT/topics/<topic>, where the ledger Cloud Run service also runs.
  events_project               = var.pipeline_events_project_id != "" ? var.pipeline_events_project_id : var.project_id
  pipeline_events_push_enabled = var.ledger_service_url != "" && var.ledger_service_name != ""
}

data "google_project" "ledger" {
  project_id = local.events_project
}

resource "google_project_service" "pubsub" {
  project            = local.events_project
  service            = "pubsub.googleapis.com"
  disable_on_destroy = false
}

resource "google_pubsub_topic" "pipeline_events" {
  project = local.events_project
  name    = var.pipeline_events_topic_name

  message_retention_duration = "604800s"

  depends_on = [google_project_service.pubsub]
}

resource "google_pubsub_topic" "pipeline_events_dead_letter" {
  project = local.events_project
  name    = "${var.pipeline_events_topic_name}-dead-letter"

  message_retention_duration = "604800s"

  depends_on = [google_project_service.pubsub]
}

# Keeps dead-lettered events inspectable (for example with `gcloud pubsub subscriptions pull`).
resource "google_pubsub_subscription" "pipeline_events_dead_letter" {
  project = local.events_project
  name    = "${var.pipeline_events_topic_name}-dead-letter"
  topic   = google_pubsub_topic.pipeline_events_dead_letter.id

  message_retention_duration = "604800s"
  expiration_policy {
    ttl = ""
  }
}

resource "google_service_account" "pipeline_events_push" {
  count        = local.pipeline_events_push_enabled ? 1 : 0
  project      = local.events_project
  account_id   = "pipeline-events-push"
  display_name = "Pub/Sub push identity for pipeline events -> ledger"
}

resource "google_cloud_run_v2_service_iam_member" "pipeline_events_push_invoker" {
  count    = local.pipeline_events_push_enabled ? 1 : 0
  project  = local.events_project
  location = var.region
  name     = var.ledger_service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pipeline_events_push[0].email}"
}

resource "google_pubsub_subscription" "pipeline_events_ledger" {
  count   = local.pipeline_events_push_enabled ? 1 : 0
  project = local.events_project
  name    = "${var.pipeline_events_topic_name}-ledger"
  topic   = google_pubsub_topic.pipeline_events.id

  ack_deadline_seconds       = 30
  message_retention_duration = "604800s"
  expiration_policy {
    ttl = ""
  }

  push_config {
    push_endpoint = "${trimsuffix(var.ledger_service_url, "/")}/events/pubsub"
    oidc_token {
      service_account_email = google_service_account.pipeline_events_push[0].email
      audience              = trimsuffix(var.ledger_service_url, "/")
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.pipeline_events_dead_letter.id
    max_delivery_attempts = 10
  }

  depends_on = [
    google_pubsub_topic_iam_member.dead_letter_publisher,
    google_cloud_run_v2_service_iam_member.pipeline_events_push_invoker,
  ]
}

# The Pub/Sub service agent forwards undeliverable messages to the dead-letter topic.
resource "google_pubsub_topic_iam_member" "dead_letter_publisher" {
  project = local.events_project
  topic   = google_pubsub_topic.pipeline_events_dead_letter.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${data.google_project.ledger.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription_iam_member" "dead_letter_subscriber" {
  count        = local.pipeline_events_push_enabled ? 1 : 0
  project      = local.events_project
  subscription = google_pubsub_subscription.pipeline_events_ledger[0].name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.ledger.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
