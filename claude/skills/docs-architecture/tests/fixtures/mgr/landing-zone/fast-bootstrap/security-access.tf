resource "google_folder_iam_member" "security_planner" {
  count  = var.security_stage_access == null ? 0 : 1
  folder = var.security_stage_access.folder_id
  role   = "roles/cloudkms.viewer"
  member = google_service_account.planner.member
}

resource "google_folder_iam_member" "security_deployer" {
  count  = var.security_stage_access == null ? 0 : 1
  folder = var.security_stage_access.folder_id
  role   = "roles/cloudkms.admin"
  member = google_service_account.deployer.member
  # A separate conditional binding survives stage-0's group-owned role binding.
  condition {
    title       = "fast-security-bootstrap"
    description = "Bootstrap automation within the security folder."
    expression  = "true"
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "google_storage_bucket_iam_member" "security_outputs_planner" {
  count  = var.security_stage_access == null ? 0 : 1
  bucket = var.security_stage_access.outputs_bucket
  role   = "roles/storage.objectViewer"
  member = google_service_account.planner.member
  condition {
    title      = "fast-security-contract-reader"
    expression = "resource.name.startsWith('projects/_/buckets/${var.security_stage_access.outputs_bucket}/objects/contracts/')"
  }
}

resource "google_storage_bucket_iam_member" "security_outputs_deployer" {
  count  = var.security_stage_access == null ? 0 : 1
  bucket = var.security_stage_access.outputs_bucket
  role   = "roles/storage.objectUser"
  member = google_service_account.deployer.member
  condition {
    title      = "fast-security-contract-writer"
    expression = "resource.name.startsWith('projects/_/buckets/${var.security_stage_access.outputs_bucket}/objects/contracts/')"
  }
}

resource "google_service_account_iam_member" "deployer_ledger_id_token" {
  count              = var.enable_ledger_id_tokens ? 1 : 0
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.serviceAccountOpenIdTokenCreator"
  member             = google_service_account.deployer.member
}
