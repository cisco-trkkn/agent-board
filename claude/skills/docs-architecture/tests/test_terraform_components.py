import os, re, tempfile, unittest
from unittest import mock
from helpers import run, by_id, FIXTURE

try:
    import hcl2  # noqa: F401
    HCL2 = True
except ImportError:
    HCL2 = False

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
        pat = re.compile(r'^resource\s+"([a-z0-9_]+_iam_(?:member|binding))"\s+"([^"]+)"', re.M)
        found = []
        for d, _, files in os.walk(FIXTURE):
            for f in files:
                if f.endswith(".tf"):
                    with open(os.path.join(d, f)) as fh:
                        found += [m.group(1) for m in pat.finditer(fh.read())]
        self.assertGreater(len(found), 0, "fixture must contain *_iam_member/_binding blocks")
        bad = [c["id"] for c in self.inv["components"] if c["id"].split("/")[-1].split(".")[0].endswith(("_iam_member", "_iam_binding"))]
        self.assertEqual(bad, [])

    @unittest.skipUnless(HCL2, "python-hcl2 not importable")
    def test_confidence_high_when_hcl2_importable(self):
        self.assertEqual(self.inv["meta"]["confidence"], "high")
        self.assertFalse([u for u in self.inv["unknowns"] if "hcl2" in u["why"]])

    def test_confidence_low_when_hcl2_missing(self):
        with mock.patch.dict("sys.modules", {"hcl2": None}):
            code, inv, err = run([FIXTURE])
        self.assertEqual(code, 0, err)
        self.assertEqual(inv["meta"]["confidence"], "low")

    def test_project_boundary(self):
        b = by_id(self.inv["boundaries"])["infra/ledger/project:var.project_id"]
        self.assertEqual(b["kind"], "project")
        self.assertIn("infra/ledger/google_service_account.ledger", b["members"])

    def test_vpc_boundary(self):
        b = by_id(self.inv["boundaries"])["infra/ledger/google_compute_network.ledger#vpc"]
        self.assertEqual(b["kind"], "vpc")
        self.assertIn("infra/ledger/google_compute_subnetwork.ledger", b["members"])

    def test_meta_counts(self):
        tf = [c for c in self.inv["components"] if not c["id"].startswith("ci/") and "/procfile." not in c["id"]]
        self.assertEqual(self.inv["meta"]["extractors"]["terraform"], len(tf))

    def test_empty_repo_halts(self):
        with tempfile.TemporaryDirectory() as d:
            code, inv, err = run([d])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("inventory: 0 components — discovery is broken, not an empty system"), err)

if __name__ == "__main__":
    unittest.main()
