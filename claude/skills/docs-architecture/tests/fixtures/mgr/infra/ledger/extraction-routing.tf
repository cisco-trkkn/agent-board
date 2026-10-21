# Extraction and transformation events -> transformation layer. Extraction jobs publish
# extraction_complete and backfill_complete, and the transform job transformation_complete,
# to the pipeline-events topic (lib/monorail_common/events.py) with an event_type attribute;
# this filtered OIDC push subscription delivers only those three to the transformation
# layer (its ETL and backfill gates, and the MLOps score start). The ledger's own subscription keeps
# receiving every event as an audit record.

locals {
  transformation_push_enabled = var.transformation_layer_service_url != "" && var.transformation_layer_service_name != ""
  transformation_region       = var.transformation_layer_region != "" ? var.transformation_layer_region : var.region
}

resource "google_service_account" "pipeline_events_transformation_push" {
  count        = local.transformation_push_enabled ? 1 : 0
  project      = local.events_project
  account_id   = "pipeline-events-transform-push"
  display_name = "Pub/Sub push identity for extraction events -> transformation layer"
}

resource "google_cloud_run_v2_service_iam_member" "pipeline_events_transformation_invoker" {
  count    = local.transformation_push_enabled ? 1 : 0
  project  = local.events_project
  location = local.transformation_region
  name     = var.transformation_layer_service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pipeline_events_transformation_push[0].email}"
}

resource "google_pubsub_subscription" "pipeline_events_transformation" {
  count   = local.transformation_push_enabled ? 1 : 0
  project = local.events_project
  name    = "${var.pipeline_events_topic_name}-transformation"
  topic   = google_pubsub_topic.pipeline_events.id
  filter  = "attributes.event_type = \"extraction_complete\" OR attributes.event_type = \"backfill_complete\" OR attributes.event_type = \"transformation_complete\""

  # The handler calls the ledger and may start a GitLab pipeline before it answers.
  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  expiration_policy {
    ttl = ""
  }

  push_config {
    push_endpoint = "${trimsuffix(var.transformation_layer_service_url, "/")}/"
    oidc_token {
      service_account_email = google_service_account.pipeline_events_transformation_push[0].email
      audience              = trimsuffix(var.transformation_layer_service_url, "/")
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
    google_cloud_run_v2_service_iam_member.pipeline_events_transformation_invoker,
  ]
}

resource "google_pubsub_subscription_iam_member" "transformation_dead_letter_subscriber" {
  count        = local.transformation_push_enabled ? 1 : 0
  project      = local.events_project
  subscription = google_pubsub_subscription.pipeline_events_transformation[0].name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.ledger.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
