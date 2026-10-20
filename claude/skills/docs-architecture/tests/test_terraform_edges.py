import unittest
from helpers import run, FIXTURE

L = "infra/ledger/"
B = "landing-zone/fast-bootstrap/"

class TerraformEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.inv, cls.err = run([FIXTURE])
        cls.edges = {(e["from"], e["to"], e["kind"]): e for e in cls.inv["edges"]}

    def edge(self, frm, to, kind):
        self.assertIn((frm, to, kind), self.edges, f"missing {kind} edge {frm} -> {to}")
        return self.edges[(frm, to, kind)]

    def test_topic_to_subscription(self):
        e = self.edge(L + "google_pubsub_topic.pipeline_events", L + "google_pubsub_subscription.pipeline_events_ledger", "async")
        self.assertEqual(e["source"], L + "pipeline-events.tf:71")

    def test_secret_accessor(self):
        e = self.edge(L + "google_service_account.ledger", L + "google_secret_manager_secret.db_password", "iam")
        self.assertEqual((e["label"], e["source"]), ("roles/secretmanager.secretAccessor", L + "main.tf:205"))

    def test_wif_trust_through_local(self):
        e = self.edge(B + "google_iam_workload_identity_pool.gitlab", B + "google_service_account.planner", "trust")
        self.assertEqual((e["label"], e["source"]), ("roles/iam.workloadIdentityUser", B + "identity.tf:67"))

    def test_iam_and_trust_edges_carry_raw_member(self):
        e = self.edge(B + "google_iam_workload_identity_pool.gitlab", B + "google_service_account.planner", "trust")
        self.assertEqual(e["member"], "${local.pool_principal}/attribute.ref_type/branch")
        e = self.edge(L + "google_service_account.ledger", L + "google_secret_manager_secret.db_password", "iam")
        self.assertEqual(e["member"], "google_service_account.ledger.member")
        for e in self.inv["edges"]:
            self.assertEqual("member" in e, e["kind"] in ("iam", "trust"), e)

    def test_variable_target_is_unknown(self):
        hits = [u for u in self.inv["unknowns"] if u["source"] == L + "applied-events.tf:1"]
        self.assertTrue(hits and "var.ledger_service_name" in hits[0]["why"], self.inv["unknowns"])

    def test_push_endpoint_unknown(self):
        hits = [u for u in self.inv["unknowns"] if u["source"] == L + "pipeline-events.tf:71" and "push endpoint" in u["why"]]
        self.assertTrue(hits, self.inv["unknowns"])

    def test_endpoints_resolve(self):
        ids = {c["id"] for c in self.inv["components"]} | {b["id"] for b in self.inv["boundaries"]}
        unknown_whats = {u["what"] for u in self.inv["unknowns"]}
        for e in self.inv["edges"]:
            for end in (e["from"], e["to"]):
                if end.startswith("principal:"):
                    self.assertIn(end, unknown_whats, e)
                else:
                    self.assertIn(end, ids, e)

class TerraformEdgeParserUnits(unittest.TestCase):
    """Unit tests of the extractor on minimal in-memory .tf text (not fixtures): the captured
    mgr fixture has no iam_binding and no IAM resource with a local.* project."""
    def extract(self, text):
        import tempfile, os
        from extractors import terraform
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "m"))
            with open(os.path.join(d, "m", "main.tf"), "w") as fh:
                fh.write(text)
            return terraform.extract(d)

    def test_iam_binding_emits_one_edge_per_member(self):
        out = self.extract('''
resource "google_service_account" "a" {
  account_id = "a"
}
resource "google_service_account" "b" {
  account_id = "b"
}
resource "google_secret_manager_secret" "s" {
  secret_id = "s"
}
resource "google_secret_manager_secret_iam_binding" "bind" {
  secret_id = google_secret_manager_secret.s.secret_id
  role      = "roles/secretmanager.secretAccessor"
  members   = [
    google_service_account.a.member,
    google_service_account.b.member,
    "user:x@example.com",
  ]
}
''')
        pairs = {(e["from"], e["to"]) for e in out["edges"]}
        self.assertEqual(pairs, {("m/google_service_account.a", "m/google_secret_manager_secret.s"),
                                 ("m/google_service_account.b", "m/google_secret_manager_secret.s"),
                                 ("principal:user:x@example.com", "m/google_secret_manager_secret.s")})
        self.assertIn("principal:user:x@example.com", {u["what"] for u in out["unknowns"]})

    def test_project_iam_with_local_project_reuses_boundary(self):
        out = self.extract('''
locals {
  p = "my-proj"
}
resource "google_service_account" "a" {
  project    = local.p
  account_id = "a"
}
resource "google_project_iam_member" "grant" {
  project = local.p
  role    = "roles/viewer"
  member  = google_service_account.a.member
}
''')
        bids = [b["id"] for b in out["boundaries"] if b["kind"] == "project"]
        self.assertEqual(bids, ["m/project:local.p"], bids)
        self.assertEqual([e["to"] for e in out["edges"]], ["m/project:local.p"])

if __name__ == "__main__":
    unittest.main()
