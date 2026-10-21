variable "archive_notification_channels" {
  type        = list(string)
  description = "Existing notification channel resource names for archive failures; empty disables the policy."
  default     = []
}

resource "google_monitoring_alert_policy" "archive_failure" {
  count        = length(var.archive_notification_channels) > 0 ? 1 : 0
  project      = var.project_id
  display_name = "GA4 archive deployment or block failed"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Archive failure recorded by ledger"
    condition_matched_log {
      filter = "resource.type=\"cloud_run_revision\" AND severity>=ERROR AND (\"Archive deployment\" OR \"Archive progress\") AND \"status=failed\""
    }
  }

  notification_channels = var.archive_notification_channels
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }
}
