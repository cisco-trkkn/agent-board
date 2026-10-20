resource "google_cloud_run_v2_service_iam_member" "applied_event_writer" {
  for_each = var.ledger_service_name == "" ? toset([]) : var.applied_event_service_accounts
  project  = var.project_id
  location = var.region
  name     = var.ledger_service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${each.value}"
}

resource "google_cloud_run_v2_service_iam_member" "release_control_client" {
  for_each = var.ledger_service_name == "" ? toset([]) : setsubtract(
    var.release_control_service_accounts,
    var.applied_event_service_accounts,
  )
  project  = var.project_id
  location = var.region
  name     = var.ledger_service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${each.value}"
}
