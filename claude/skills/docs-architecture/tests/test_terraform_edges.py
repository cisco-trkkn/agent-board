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

if __name__ == "__main__":
    unittest.main()
