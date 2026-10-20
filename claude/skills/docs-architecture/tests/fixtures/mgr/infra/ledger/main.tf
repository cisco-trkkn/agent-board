terraform {
  backend "gcs" {}
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "required_apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_sql_database_instance" "ledger" {
  name             = var.instance_name
  project          = var.project_id
  region           = var.region
  database_version = "POSTGRES_15"

  settings {
    tier                        = var.instance_tier
    availability_type           = var.availability_type
    deletion_protection_enabled = var.deletion_protection

    backup_configuration {
      enabled                        = true
      start_time                     = var.backup_start_time
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = var.transaction_log_retention_days

      backup_retention_settings {
        retained_backups = var.backup_retention_count
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.ledger.id
    }
  }

  deletion_protection = var.deletion_protection
  depends_on          = [google_service_networking_connection.ledger]
}

resource "google_sql_database" "ledger" {
  project  = var.project_id
  name     = var.db_name
  instance = google_sql_database_instance.ledger.name
}

resource "google_sql_user" "ledger_writer" {
  project  = var.project_id
  instance = google_sql_database_instance.ledger.name
  name     = var.db_user
  password = var.db_user_password
}

resource "google_secret_manager_secret" "db_password" {
  project   = var.project_id
  secret_id = var.db_password_secret_id
  replication {
    auto {}
  }
  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = var.db_user_password
}

resource "google_artifact_registry_repository" "ledger_source" {
  project       = var.project_id
  location      = var.region
  repository_id = "cloud-run-source-deploy"
  format        = "DOCKER"
  description   = "Source-deployed ledger service and migration job"
  depends_on    = [google_project_service.required_apis]
}

resource "google_artifact_registry_repository" "release_images" {
  count         = var.release_image_repository_enabled ? 1 : 0
  project       = var.project_id
  location      = var.region
  repository_id = var.release_image_repository_id
  format        = "DOCKER"
  description   = "Immutable shared MLOps release images"
  depends_on    = [google_project_service.required_apis]
}

resource "google_artifact_registry_repository_iam_member" "release_image_writer" {
  for_each   = var.release_image_repository_enabled ? var.release_image_writer_service_accounts : toset([])
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.release_images[0].name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${each.value}"
}

resource "google_artifact_registry_repository_iam_member" "release_image_access_manager" {
  for_each   = var.release_image_repository_enabled ? var.release_image_access_manager_service_accounts : toset([])
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.release_images[0].name
  role       = "roles/artifactregistry.admin"
  member     = "serviceAccount:${each.value}"
}

resource "google_secret_manager_secret" "gitlab_token" {
  project   = var.project_id
  secret_id = "mono-gitlab-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required_apis]
}

resource "google_service_account" "ledger" {
  project      = var.project_id
  account_id   = "ledger-runtime"
  display_name = "Ledger Cloud Run runtime"
  depends_on   = [google_project_service.required_apis]
}

resource "google_service_account" "ledger_build" {
  project      = var.project_id
  account_id   = "ledger-build"
  display_name = "Ledger Cloud Build source builder"
  depends_on   = [google_project_service.required_apis]
}

resource "google_project_iam_member" "ledger_builder" {
  project = var.project_id
  role    = "roles/run.builder"
  member  = google_service_account.ledger_build.member
}

resource "google_storage_bucket" "ledger_build_source" {
  project                     = var.project_id
  name                        = "${var.project_id}-ledger-build-source"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
}

resource "google_storage_bucket_iam_member" "ledger_build_source" {
  for_each = {
    deployer = "serviceAccount:${var.ci_deployer_service_account_email}"
    builder  = google_service_account.ledger_build.member
  }
  bucket = google_storage_bucket.ledger_build_source.name
  role   = "roles/storage.objectUser"
  member = each.value
}

resource "google_storage_bucket_iam_member" "ledger_build_source_metadata" {
  for_each = {
    deployer = "serviceAccount:${var.ci_deployer_service_account_email}"
    builder  = google_service_account.ledger_build.member
  }
  bucket = google_storage_bucket.ledger_build_source.name
  role   = "roles/storage.bucketViewer"
  member = each.value
}

moved {
  from = google_storage_bucket_iam_member.ledger_build_source_metadata
  to   = google_storage_bucket_iam_member.ledger_build_source_metadata["deployer"]
}

resource "google_service_account_iam_member" "ledger_ci_build_as" {
  service_account_id = google_service_account.ledger_build.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.ci_deployer_service_account_email}"
}

resource "google_project_iam_member" "ledger_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = google_service_account.ledger.member
}

resource "google_secret_manager_secret_iam_member" "ledger_password_reader" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.ledger.member
}

resource "google_secret_manager_secret_iam_member" "ledger_gitlab_token_reader" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.gitlab_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.ledger.member
}

resource "google_project_iam_member" "ledger_ci" {
  for_each = toset([
    "roles/run.admin",
    "roles/cloudbuild.builds.editor",
    "roles/artifactregistry.writer",
    "roles/serviceusage.serviceUsageConsumer",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${var.ci_deployer_service_account_email}"
}

resource "google_service_account_iam_member" "ledger_ci_act_as" {
  service_account_id = google_service_account.ledger.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.ci_deployer_service_account_email}"
}

resource "google_service_account_iam_member" "ledger_ci_id_token" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.ci_deployer_service_account_email}"
  role               = "roles/iam.serviceAccountOpenIdTokenCreator"
  member             = "serviceAccount:${var.ci_deployer_service_account_email}"
}

resource "google_compute_subnetwork_iam_member" "ledger_ci_network" {
  project    = var.project_id
  region     = var.region
  subnetwork = google_compute_subnetwork.ledger.name
  role       = "roles/compute.networkUser"
  member     = "serviceAccount:${var.ci_deployer_service_account_email}"
}
