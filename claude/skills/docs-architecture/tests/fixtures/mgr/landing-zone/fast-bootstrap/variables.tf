variable "organization_id" {
  type        = string
  description = "Numeric GCP organization ID."
  default     = "538041208947"

  validation {
    condition     = can(regex("^[0-9]+$", var.organization_id))
    error_message = "organization_id must be numeric."
  }
}

variable "billing_account_id" {
  type        = string
  description = "Billing account to attach to the seed project."
  default     = "01139E-339843-4A49C3"

  validation {
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account_id))
    error_message = "billing_account_id must look like XXXXXX-XXXXXX-XXXXXX."
  }
}

variable "project_id" {
  type        = string
  description = "Globally unique project ID for the FAST bootstrap seed."
  default     = "trk-fast-bootstrap-0"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be 6-30 lowercase letters, digits, or hyphens, and start/end with a letter or digit."
  }
}

variable "state_bucket_name" {
  type        = string
  description = "Globally unique GCS bucket name for FAST Terraform state."
  default     = "trk-fast-bootstrap-0-tfstate"

  validation {
    condition = (
      length(var.state_bucket_name) >= 3 &&
      length(var.state_bucket_name) <= 63 &&
      can(regex("^[a-z0-9][a-z0-9._-]*[a-z0-9]$", var.state_bucket_name)) &&
      !strcontains(var.state_bucket_name, "..") &&
      !startswith(var.state_bucket_name, "goog") && !strcontains(var.state_bucket_name, "google") &&
      !can(regex("^[0-9]+(\\.[0-9]+){3}$", var.state_bucket_name))
    )
    error_message = "state_bucket_name must meet GCS naming rules: 3-63 valid lowercase characters, no consecutive periods, reserved Google names, or IP-address form."
  }
}

variable "gitlab_project_path" {
  type        = string
  description = "GitLab.com namespace/project path allowed to exchange tokens."
  default     = "trkkn/trkkn-na/master-gcp-repo"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+){2,}$", var.gitlab_project_path))
    error_message = "gitlab_project_path must be a full GitLab namespace/project path with at least three components."
  }
}

variable "gitlab_deploy_ref" {
  type        = string
  description = "Protected GitLab branch permitted to use the deployer identity. This root intentionally supports main only."
  default     = "main"

  validation {
    condition     = var.gitlab_deploy_ref == "main"
    error_message = "The deployer identity is restricted to the protected main branch."
  }
}

variable "grant_billing_admin_for_stage0" {
  type        = bool
  description = "Grant billing.admin so FAST stage 0 can manage billing-account IAM; set false to grant billing.user instead."
  default     = true
}

variable "region" {
  type        = string
  description = "Location used by the Google provider and state bucket."
  default     = "us"
}

variable "labels" {
  type        = map(string)
  description = "Additional labels applied to the seed project and state bucket."
  default     = {}
}

variable "security_stage_access" {
  description = "Accepted stage-0 security folder and outputs bucket. Null leaves post-bootstrap access unconfigured."
  type = object({
    folder_id      = string
    outputs_bucket = string
  })
  default = null
  validation {
    condition = var.security_stage_access == null ? true : (
      can(regex("^folders/[0-9]+$", var.security_stage_access.folder_id)) &&
      can(regex("^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$", var.security_stage_access.outputs_bucket))
    )
    error_message = "Use the actual stage-0 security folder resource name and outputs bucket name."
  }
}

variable "enable_ledger_id_tokens" {
  description = "Allow the bootstrap deployer to mint its own audience-bound ledger ID token, without access-token impersonation grants."
  type        = bool
  default     = false
}

variable "tenant_contract_readers" {
  description = "Tenant factory stage => org release identity that reads its tenant contracts (dev3 and staging deploy as the staging identity, main as prod)."
  type        = map(string)
  default = {
    "2-project-factory-dev"   = "serviceAccount:ledger-deployer@trk-org-staging-0.iam.gserviceaccount.com"
    "2-project-factory-stage" = "serviceAccount:ledger-deployer@trk-org-staging-0.iam.gserviceaccount.com"
    "2-project-factory-prod"  = "serviceAccount:ledger-deployer@trk-org-prod-0.iam.gserviceaccount.com"
  }
}
