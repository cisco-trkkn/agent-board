locals {
  state_prefix = "fast-bootstrap"

  labels = merge(var.labels, {
    managed_by = "fast-bootstrap"
    purpose    = "terraform-state"
  })
}

resource "google_project" "seed" {
  project_id          = var.project_id
  name                = var.project_id
  org_id              = var.organization_id
  billing_account     = var.billing_account_id
  auto_create_network = false
  deletion_policy     = "PREVENT"
  labels              = local.labels

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
      error_message = "The seed project ID must meet Google Cloud project ID requirements."
    }
  }
}

resource "google_project_service" "bootstrap" {
  for_each = toset([
    # Quota project for the tenant budgets the deployer manages; the Billing
    # Budgets API bills calls to the caller's project.
    "billingbudgets.googleapis.com",
    # Tenant factories manage each tenant's registry and read its BigQuery service
    # identity through this project.
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "cloudbilling.googleapis.com",
    "cloudkms.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    # Tenant budget notification channels are Monitoring resources, billed here too.
    "monitoring.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
  ])

  project            = google_project.seed.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "state" {
  project                     = google_project.seed.project_id
  name                        = var.state_bucket_name
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  versioning {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true

    precondition {
      condition = (
        length(var.state_bucket_name) >= 3 &&
        length(var.state_bucket_name) <= 63 &&
        can(regex("^[a-z0-9][a-z0-9._-]*[a-z0-9]$", var.state_bucket_name)) &&
        !strcontains(var.state_bucket_name, "..") &&
        !startswith(var.state_bucket_name, "goog") && !strcontains(var.state_bucket_name, "google") &&
        !can(regex("^[0-9]+(\\.[0-9]+){3}$", var.state_bucket_name))
      )
      error_message = "The state bucket name must meet Google Cloud Storage naming requirements."
    }
  }

  depends_on = [google_project_service.bootstrap]
}
