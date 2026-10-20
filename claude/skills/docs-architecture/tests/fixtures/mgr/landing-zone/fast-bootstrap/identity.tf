locals {
  pool_principal = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.gitlab.name}"
}

resource "google_iam_workload_identity_pool" "gitlab" {
  project                   = google_project.seed.project_id
  workload_identity_pool_id = "gitlab-fast"
  display_name              = "GitLab FAST"

  depends_on = [google_project_service.bootstrap]
}

resource "google_iam_workload_identity_pool_provider" "gitlab" {
  project                            = google_project.seed.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.gitlab.workload_identity_pool_id
  workload_identity_pool_provider_id = "gitlab-com"
  display_name                       = "GitLab.com FAST"
  attribute_condition                = "assertion.project_path == \"${var.gitlab_project_path}\""

  attribute_mapping = {
    "google.subject"         = "assertion.sub"
    "attribute.project_path" = "assertion.project_path"
    "attribute.ref"          = "assertion.ref"
    "attribute.ref_type"     = "assertion.ref_type"
    "attribute.deployer"     = "(assertion.ref == '${var.gitlab_deploy_ref}' && assertion.ref_type == 'branch' && string(assertion.ref_protected) == 'true') ? 'allowed' : 'denied'"
    "attribute.ledger_stage" = "((assertion.ref == 'staging' || assertion.ref == 'dev3') && assertion.ref_type == 'branch' && string(assertion.ref_protected) == 'true') ? 'allowed' : 'denied'"
    "attribute.ledger_prod"  = "(assertion.ref == 'main' && assertion.ref_type == 'branch' && string(assertion.ref_protected) == 'true') ? 'allowed' : 'denied'"
  }

  oidc {
    issuer_uri = "https://gitlab.com"
  }

  lifecycle {
    precondition {
      condition     = can(regex("^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+){2,}$", var.gitlab_project_path))
      error_message = "The WIF provider must be restricted to a valid full GitLab project path."
    }

    precondition {
      condition     = var.gitlab_deploy_ref == "main"
      error_message = "The deployer claim must remain restricted to protected main."
    }
  }

  depends_on = [google_project_service.bootstrap]
}

resource "google_service_account" "planner" {
  project      = google_project.seed.project_id
  account_id   = "fast-plan"
  display_name = "FAST Terraform read-only planner"
  description  = "GitLab branch plans; infrastructure access is read-only, with bucket-scoped state lock access."

  depends_on = [google_project_service.bootstrap]
}

resource "google_service_account" "deployer" {
  project      = google_project.seed.project_id
  account_id   = "fast-deployer"
  display_name = "FAST Terraform protected deployer"
  description  = "GitLab protected-main apply identity for existing FAST stages."

  depends_on = [google_project_service.bootstrap]
}

resource "google_service_account_iam_member" "planner_wif" {
  service_account_id = google_service_account.planner.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.pool_principal}/attribute.ref_type/branch"
}

resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.pool_principal}/attribute.deployer/allowed"
}

resource "google_organization_iam_member" "planner" {
  for_each = toset([
    "roles/browser",
    "roles/iam.securityReviewer",
    "roles/orgpolicy.policyViewer",
    "roles/resourcemanager.organizationViewer",
    "roles/serviceusage.serviceUsageViewer",
    "roles/viewer",
  ])

  org_id = var.organization_id
  role   = each.value
  member = google_service_account.planner.member
}

resource "google_billing_account_iam_member" "planner" {
  billing_account_id = var.billing_account_id
  role               = "roles/billing.viewer"
  member             = google_service_account.planner.member
}

# These organization-level grants let the protected deployer run the existing
# FAST organization, security, networking, and project-factory stages. See the
# README for the broad organization and billing grants that this entails.
resource "google_organization_iam_member" "deployer" {
  for_each = toset([
    "roles/artifactregistry.admin",
    "roles/bigquery.admin",
    "roles/compute.networkAdmin",
    # Attach the 2-networking egress firewall policies to the tenant folders.
    "roles/compute.orgSecurityResourceAdmin",
    "roles/compute.securityAdmin",
    "roles/compute.xpnAdmin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.workloadIdentityPoolAdmin",
    "roles/logging.configWriter",
    # Tenant budget notification channels, including adopted ones.
    "roles/monitoring.notificationChannelEditor",
    "roles/orgpolicy.policyAdmin",
    "roles/resourcemanager.folderAdmin",
    "roles/resourcemanager.organizationAdmin",
    "roles/resourcemanager.projectCreator",
    "roles/resourcemanager.projectDeleter",
    "roles/resourcemanager.projectIamAdmin",
    # resourcemanager.projects.update for labels and settings on adopted tenant projects.
    "roles/resourcemanager.projectMover",
    "roles/run.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.admin",
  ])

  org_id = var.organization_id
  role   = each.value
  member = google_service_account.deployer.member
}

resource "google_billing_account_iam_member" "deployer" {
  billing_account_id = var.billing_account_id
  role               = var.grant_billing_admin_for_stage0 ? "roles/billing.admin" : "roles/billing.user"
  member             = google_service_account.deployer.member
}

# Tenant project factories attach a budget to each tenant project.
resource "google_billing_account_iam_member" "deployer_budgets" {
  billing_account_id = var.billing_account_id
  role               = "roles/billing.costsManager"
  member             = google_service_account.deployer.member
}

resource "google_storage_bucket_iam_member" "planner_state" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectUser"
  member = google_service_account.planner.member
}

resource "google_storage_bucket_iam_member" "deployer_state" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.deployer.member
}
