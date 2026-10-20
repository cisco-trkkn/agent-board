variable "project_id" {
  type        = string
  description = "Project hosting the dedicated ledger Cloud SQL instance."
}

variable "ci_deployer_service_account_email" {
  type        = string
  description = "Existing stage-0 ledger-deployer identity for this environment."
}

variable "region" {
  type        = string
  description = "Region for the Cloud SQL instance."
}

variable "instance_name" {
  type        = string
  description = "Cloud SQL instance name."
}

variable "instance_tier" {
  type        = string
  description = "Cloud SQL machine tier."
  default     = "db-custom-2-7680"
}

variable "availability_type" {
  type        = string
  description = "Cloud SQL availability type."
  default     = "REGIONAL"
}

variable "deletion_protection" {
  type        = bool
  description = "Protect Cloud SQL instance from accidental deletion."
  default     = true
}

variable "backup_start_time" {
  type        = string
  description = "UTC daily Cloud SQL automated-backup start time in HH:MM format."
  default     = "03:00"

  validation {
    condition     = can(regex("^([01][0-9]|2[0-3]):[0-5][0-9]$", var.backup_start_time))
    error_message = "backup_start_time must use 24-hour HH:MM format."
  }
}

variable "backup_retention_count" {
  type        = number
  description = "Number of daily automated Cloud SQL backups to retain."
  default     = 7

  validation {
    condition     = var.backup_retention_count >= 1 && var.backup_retention_count <= 365
    error_message = "backup_retention_count must be between 1 and 365."
  }
}

variable "transaction_log_retention_days" {
  type        = number
  description = "Days of PostgreSQL transaction logs retained for point-in-time recovery."
  default     = 7

  validation {
    condition     = var.transaction_log_retention_days >= 1 && var.transaction_log_retention_days <= 7
    error_message = "transaction_log_retention_days must be between 1 and 7."
  }
}

variable "ledger_subnet_cidr" {
  type        = string
  description = "Non-overlapping /26 or larger subnet for Cloud Run Direct VPC egress."
}

variable "db_name" {
  type        = string
  description = "Ledger database name."
  default     = "ledger"
}

variable "db_user" {
  type        = string
  description = "Ledger writer username."
  default     = "ledger_writer"
}

variable "db_user_password" {
  type        = string
  description = "Ledger writer password."
  sensitive   = true
}

variable "db_password_secret_id" {
  type        = string
  description = "Secret Manager secret id where DB password is stored."
  default     = "ledger-db-password"
}

variable "pipeline_events_project_id" {
  type        = string
  description = "Org project that hosts the pipeline-events topic and the ledger Cloud Run service. Defaults to project_id."
  default     = ""
}

variable "pipeline_events_topic_name" {
  type        = string
  description = "Pipeline events topic name: pipeline-events-staging or pipeline-events-prod (must match the topic ci/scripts/tf-utils/grant-org-access.sh and deploy-mlops.sh derive)."
}

variable "ledger_service_name" {
  type        = string
  description = "Ledger Cloud Run service name (org-ledger-service-staging|prod). Empty skips the push subscription."
  default     = ""
}

variable "ledger_service_url" {
  type        = string
  description = "Ledger Cloud Run service URL, used as the push endpoint base and OIDC audience. Must equal the ledger's LEDGER_SERVICE_URL. Empty skips the push subscription."
  default     = ""
}

variable "release_control_service_accounts" {
  description = "Reviewed CI service accounts allowed to invoke this ledger as the central release-control API."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([
      for email in var.release_control_service_accounts :
      can(regex("^[a-z][a-z0-9-]*@[a-z][a-z0-9-]*\\.iam\\.gserviceaccount\\.com$", email))
    ])
    error_message = "Release-control callers must be service-account emails."
  }
}

variable "release_image_repository_id" {
  type        = string
  description = "Artifact Registry repository ID for immutable shared release images."
  default     = "shared-release-images"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,62}$", var.release_image_repository_id))
    error_message = "release_image_repository_id must be a valid Artifact Registry repository ID."
  }
}

variable "release_image_repository_enabled" {
  type        = bool
  description = "Create the shared release-image repository. Enable only for the central production release-control ledger."
  default     = false
}

variable "release_image_writer_service_accounts" {
  description = "Reviewed CI service accounts allowed to build immutable shared release images."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([
      for email in var.release_image_writer_service_accounts :
      can(regex("^[a-z][a-z0-9-]*@[a-z][a-z0-9-]*\\.iam\\.gserviceaccount\\.com$", email))
    ])
    error_message = "Release image writers must be service-account emails."
  }
}

variable "release_image_access_manager_service_accounts" {
  description = "Reviewed CI service accounts allowed to manage repository IAM and grant tenant Cloud Run service agents reader access to release images."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([
      for email in var.release_image_access_manager_service_accounts :
      can(regex("^[a-z][a-z0-9-]*@[a-z][a-z0-9-]*\\.iam\\.gserviceaccount\\.com$", email))
    ])
    error_message = "Release image access managers must be service-account emails."
  }
}

variable "applied_event_service_accounts" {
  description = "Reviewed applied-event writers (including the FAST deployer). Granted invoker on this ledger service only."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([
      for email in var.applied_event_service_accounts :
      can(regex("^[a-z][a-z0-9-]*@[a-z][a-z0-9-]*\\.iam\\.gserviceaccount\\.com$", email))
    ])
    error_message = "Applied-event writers must be service-account emails."
  }
}

variable "transformation_layer_service_name" {
  type        = string
  description = "Transformation layer Cloud Run service name (ORG_TRANSFORM_FUNCTION_STAGING|PROD), in the pipeline-events project. Empty skips the extraction-event push subscription."
  default     = ""
}

variable "transformation_layer_service_url" {
  type        = string
  description = "Transformation layer Cloud Run service URL: push endpoint and OIDC audience. Empty skips the extraction-event push subscription."
  default     = ""
}

variable "transformation_layer_region" {
  type        = string
  description = "Region of the transformation layer service (ORG_TRANSFORM_REGION). Defaults to region."
  default     = ""
}

variable "snapshot_writer_service_accounts" {
  description = "Service accounts allowed to POST /snapshots/consumer on this ledger: the consumer snapshot projector, plus the CI identity that already writes snapshots (ORG_SERVICE_ACCOUNT_STAGING, used by the stage-cohort backfill on the operational ledger and by sync-release-snapshots on the central release ledger). Omitting a CI writer makes its job fail with 403. Also set them in the ORG_SNAPSHOT_WRITER_SERVICE_ACCOUNTS_<ENV> CI variable, which the ledger deploy writes to SNAPSHOT_WRITER_SERVICE_ACCOUNTS."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([
      for email in var.snapshot_writer_service_accounts :
      can(regex("^[a-z][a-z0-9-]*@[a-z][a-z0-9-]*\\.iam\\.gserviceaccount\\.com$", email))
    ])
    error_message = "Snapshot writers must be service-account emails."
  }
}
