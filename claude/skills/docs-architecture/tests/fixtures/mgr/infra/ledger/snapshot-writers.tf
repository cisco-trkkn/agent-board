resource "google_cloud_run_v2_service_iam_member" "snapshot_writer_client" {
  for_each = var.ledger_service_name == "" ? toset([]) : var.snapshot_writer_service_accounts
  project  = var.project_id
  location = var.region
  name     = var.ledger_service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${each.value}"
}
