output "instance_connection_name" {
  value       = google_sql_database_instance.ledger.connection_name
  description = "Use this in INSTANCE_CONNECTION_NAME for ledger Cloud Run service."
}

output "database_name" {
  value       = google_sql_database.ledger.name
  description = "Provisioned ledger database name."
}

output "db_user" {
  value       = google_sql_user.ledger_writer.name
  description = "Provisioned ledger DB user."
}

output "db_password_secret_id" {
  value       = google_secret_manager_secret.db_password.secret_id
  description = "Secret id containing ledger DB password."
}

output "ledger_runtime_service_account" {
  value       = google_service_account.ledger.email
  description = "Cloud Run service and migration job identity."
}

output "ledger_build_service_account" {
  value       = google_service_account.ledger_build.email
  description = "Explicit Cloud Build identity for source deployments."
}

output "ledger_build_source_bucket" {
  value       = google_storage_bucket.ledger_build_source.name
  description = "Private Cloud Build source and log bucket."
}

output "release_image_repository" {
  value       = var.release_image_repository_enabled ? "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.release_images[0].repository_id}" : ""
  description = "Set this exact prefix as the protected GitLab RELEASE_IMAGE_REPOSITORY variable when the central release repository is enabled."
}

output "ledger_network" {
  value       = google_compute_network.ledger.name
  description = "Private ledger VPC for Cloud Run egress and Cloud SQL peering."
}

output "ledger_subnet" {
  value       = google_compute_subnetwork.ledger.name
  description = "Direct VPC egress subnet for the ledger service and migration job."
}

output "pipeline_events_topic" {
  value       = google_pubsub_topic.pipeline_events.id
  description = "Topic for pipeline events: transform job transformation events, MLOps model events, and extraction_complete/backfill_complete from extraction jobs."
}

output "pipeline_events_push_service_account" {
  value       = local.pipeline_events_push_enabled ? google_service_account.pipeline_events_push[0].email : ""
  description = "Add to the ledger PIPELINE_EVENTS_PUSH_SERVICE_ACCOUNTS env var."
}

output "transformation_push_service_account" {
  value       = local.transformation_push_enabled ? google_service_account.pipeline_events_transformation_push[0].email : ""
  description = "Identity that pushes extraction_complete and backfill_complete to the transformation layer."
}
