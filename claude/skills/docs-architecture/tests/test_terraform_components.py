import tempfile, unittest
from helpers import run, by_id, FIXTURE

class TerraformComponents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.inv, cls.err = run([FIXTURE])

    def test_exit_ok(self):
        self.assertEqual(self.code, 0, self.err)

    def test_topic(self):
        c = by_id(self.inv["components"])["infra/ledger/google_pubsub_topic.pipeline_events"]
        self.assertEqual((c["kind"], c["source"]), ("pubsub_topic", "infra/ledger/pipeline-events.tf:25"))

    def test_service_account(self):
        c = by_id(self.inv["components"])["infra/ledger/google_service_account.ledger"]
        self.assertEqual((c["kind"], c["source"], c["project"]),
                         ("service_account", "infra/ledger/main.tf:140", "var.project_id"))

    def test_iam_members_are_not_components(self):
        self.assertFalse([c for c in self.inv["components"] if c["id"].split("/")[-1].split(".")[0].endswith(("_iam_member", "_iam_binding"))])

    def test_meta_counts(self):
        tf = [c for c in self.inv["components"] if not c["id"].startswith("ci/") and ".procfile." not in c["id"]]
        self.assertEqual(self.inv["meta"]["extractors"]["terraform"], len(tf))

    def test_empty_repo_halts(self):
        with tempfile.TemporaryDirectory() as d:
            code, inv, err = run([d])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("inventory: 0 components — discovery is broken, not an empty system"), err)

if __name__ == "__main__":
    unittest.main()
