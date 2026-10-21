terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0"
    }
  }

  # The first apply creates the backend bucket, so start with local state.
  # After creation, uncomment this block and migrate state as described in
  # README.md.
  # backend "gcs" {}
}

provider "google" {
  region = var.region
}
