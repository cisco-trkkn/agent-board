# Org release identities read tenant factory contracts (tenant identity and
# Shared VPC subnet) from the stage-0 outputs bucket, one factory prefix each.
resource "google_storage_bucket_iam_member" "tenant_contract_reader" {
  for_each = var.security_stage_access == null ? {} : var.tenant_contract_readers
  bucket   = var.security_stage_access.outputs_bucket
  role     = "roles/storage.objectViewer"
  member   = each.value
  condition {
    title      = "${each.key}-tenant-contract-reader"
    expression = "resource.name.startsWith('projects/_/buckets/${var.security_stage_access.outputs_bucket}/objects/contracts/${each.key}/')"
  }
}
