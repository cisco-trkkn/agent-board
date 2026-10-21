output "seed_project_id" {
  description = "Project hosting FAST bootstrap identities and Terraform state."
  value       = google_project.seed.project_id
}

output "seed_project_number" {
  value = google_project.seed.number
}

output "state_bucket" {
  description = "GCS backend bucket name."
  value       = google_storage_bucket.state.name
}

output "state_prefix" {
  description = "GCS backend prefix for this bootstrap root; use separate prefixes for each FAST stage."
  value       = local.state_prefix
}

output "backend_migration" {
  description = "Backend settings for migrating this root from local state to GCS."
  value = {
    bucket     = google_storage_bucket.state.name
    prefix     = local.state_prefix
    project_id = google_project.seed.project_id
    location   = upper(var.region)
  }
}

output "gitlab_wif_provider" {
  description = "Exact WIF provider resource name for GitLab FAST_WIF_PROVIDER."
  value       = google_iam_workload_identity_pool_provider.gitlab.name
}

output "gitlab_audience" {
  description = "Exact provider audience for the GitLab ID token aud claim / FAST_AUD."
  value       = "https://iam.googleapis.com/${google_iam_workload_identity_pool_provider.gitlab.name}"
}

output "gitlab_planner_service_account" {
  description = "Exact email for FAST_PLAN_SERVICE_ACCOUNT; trusted on branch refs."
  value       = google_service_account.planner.email
}

output "gitlab_deployer_service_account" {
  description = "Exact email for FAST_DEPLOY_SERVICE_ACCOUNT; trusted only on protected main."
  value       = google_service_account.deployer.email
}

output "gitlab_ci_settings" {
  description = "GitLab CI variables and ID-token audience values to configure."
  value = {
    FAST_WIF_PROVIDER           = google_iam_workload_identity_pool_provider.gitlab.name
    FAST_AUD                    = "https://iam.googleapis.com/${google_iam_workload_identity_pool_provider.gitlab.name}"
    FAST_PLAN_SERVICE_ACCOUNT   = google_service_account.planner.email
    FAST_DEPLOY_SERVICE_ACCOUNT = google_service_account.deployer.email
  }
}

output "planner_resource_roles" {
  description = "Read-only organization and billing roles; GCS objectUser is separately scoped to the state bucket for backend locking."
  value = {
    organization = sort(tolist([
      "roles/browser",
      "roles/iam.securityReviewer",
      "roles/orgpolicy.policyViewer",
      "roles/resourcemanager.organizationViewer",
      "roles/serviceusage.serviceUsageViewer",
      "roles/viewer",
    ]))
    billing      = ["roles/billing.viewer"]
    state_bucket = ["roles/storage.objectUser"]
  }
}

output "deployer_bootstrap_grants" {
  description = "Broad stage-deployer grants applied by this root; review the README before using the identity."
  value = {
    organization = sort(tolist([
      "roles/artifactregistry.admin",
      "roles/bigquery.admin",
      "roles/compute.networkAdmin",
      "roles/compute.orgSecurityResourceAdmin",
      "roles/compute.securityAdmin",
      "roles/compute.xpnAdmin",
      "roles/iam.serviceAccountAdmin",
      "roles/logging.configWriter",
      "roles/monitoring.notificationChannelEditor",
      "roles/orgpolicy.policyAdmin",
      "roles/resourcemanager.folderAdmin",
      "roles/resourcemanager.organizationAdmin",
      "roles/resourcemanager.projectCreator",
      "roles/resourcemanager.projectIamAdmin",
      "roles/resourcemanager.projectMover",
      "roles/run.admin",
      "roles/serviceusage.serviceUsageAdmin",
      "roles/storage.admin",
    ]))
    billing = [var.grant_billing_admin_for_stage0 ? "roles/billing.admin" : "roles/billing.user"]
  }
}
