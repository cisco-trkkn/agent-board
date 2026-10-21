resource "google_compute_network" "ledger" {
  project                 = var.project_id
  name                    = "ledger"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required_apis]
}

resource "google_compute_subnetwork" "ledger" {
  project                  = var.project_id
  name                     = "ledger-${var.region}"
  region                   = var.region
  network                  = google_compute_network.ledger.id
  ip_cidr_range            = var.ledger_subnet_cidr
  private_ip_google_access = true
}

resource "google_compute_global_address" "ledger_services" {
  project       = var.project_id
  name          = "ledger-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.ledger.id
}

resource "google_service_networking_connection" "ledger" {
  network                 = google_compute_network.ledger.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.ledger_services.name]
  depends_on              = [google_project_service.required_apis]
}
