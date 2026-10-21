# Trimmed from real landing-zone/fast-bootstrap/identity.tf of master-gcp-repo@df19131acb1d1b8093fc57d10a9bc3b19c7fd3f1 (planner pool/SA/binding only).

locals {
  pool_principal = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.gitlab.name}"
}

resource "google_iam_workload_identity_pool" "gitlab" {
  project                   = google_project.seed.project_id
  workload_identity_pool_id = "gitlab-fast"
  display_name              = "GitLab FAST"

  depends_on = [google_project_service.bootstrap]
}

resource "google_service_account" "planner" {
  project      = google_project.seed.project_id
  account_id   = "fast-plan"
  display_name = "FAST Terraform read-only planner"
  description  = "GitLab branch plans; infrastructure access is read-only, with bucket-scoped state lock access."

  depends_on = [google_project_service.bootstrap]
}

resource "google_service_account_iam_member" "planner_wif" {
  service_account_id = google_service_account.planner.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.pool_principal}/attribute.ref_type/branch"
}
