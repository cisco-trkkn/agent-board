import os, tempfile, unittest
from helpers import run, FIXTURE, by_id
from extractors import gitlab_ci, procfile

LZ = "ci/actions/landing-zone/.gitlab-ci-landing-zone.yml"

class CiProcfileFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.inv, cls.err = run([FIXTURE])
        cls.comps = by_id(cls.inv["components"])

    def test_ci_jobs(self):
        for job, line in (("landing-zone-validate", 5), ("landing-zone-deploy-stage0", 59),
                          ("landing-zone-deploy-stage2-security", 68)):
            c = self.comps["ci/" + job]
            self.assertEqual((c["kind"], c["source"]), ("ci_job", f"{LZ}:{line}"))

    def test_job_stage_in_name(self):
        self.assertEqual(self.comps["ci/landing-zone-validate"]["name"], "landing-zone-validate [validate]")
        self.assertEqual(set(self.comps["ci/landing-zone-validate"]), {"id", "kind", "name", "project", "env", "source"})

    def test_nine_ci_jobs(self):
        self.assertEqual(len([c for c in self.inv["components"] if c["kind"] == "ci_job"]), 9)

    def test_no_reserved_or_dot_keys(self):
        ci = [c["id"] for c in self.inv["components"] if c["kind"] == "ci_job"]
        for bad in ("stages", "variables", "include", "default", "workflow", "image", "services",
                    "before_script", "after_script", "cache"):
            self.assertNotIn("ci/" + bad, ci)
        self.assertFalse([i for i in ci if i.startswith("ci/.")], ci)

    def test_procfile(self):
        c = self.comps["tools/cloudrun-ledger-layer/procfile.web"]
        self.assertEqual((c["kind"], c["source"]), ("service_source", "tools/cloudrun-ledger-layer/Procfile:1"))
        self.assertIn("ledger_api", c["name"])
        self.assertTrue([u for u in self.inv["unknowns"] if u["what"] == c["id"]])

    def test_meta_extractors(self):
        self.assertTrue({"terraform", "gitlab_ci", "procfile"} <= set(self.inv["meta"]["extractors"]))

    def test_fixture_ci_jobs_reach_no_captured_tf_dir(self):
        # No captured job uses -chdir= or cd into a captured Terraform dir (they call run-fast-stage.sh),
        # so the fixture yields no CI call edge; the edge is covered by the unit test below.
        self.assertFalse([e for e in self.inv["edges"] if e["from"].startswith("ci/")])

class CiParserUnits(unittest.TestCase):
    """Unit tests of the scanners on minimal in-memory files (not fixtures)."""
    def tmp(self, files):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(d.name, rel)) or d.name, exist_ok=True)
            with open(os.path.join(d.name, rel), "w") as fh:
                fh.write(text)
        return d.name

    def test_reference_tag_does_not_crash(self):
        root = self.tmp({".gitlab-ci.yml": "job:\n  script: [!reference [.x, script]]\n  extra:\n    - !reference [.y, script]\n"})
        out = gitlab_ci.extract(root)
        self.assertEqual([c["id"] for c in out["components"]], ["ci/job"])

    def test_environment_inline_and_name(self):
        root = self.tmp({".gitlab-ci.yml": "a:\n  environment: production\n  script: [x]\nb:\n  environment:\n    name: staging\n  script: [x]\nc:\n  environment: dev\n  script: [x]\n"})
        envs = {c["id"]: c["env"] for c in gitlab_ci.extract(root)["components"]}
        self.assertEqual(envs, {"ci/a": "prod", "ci/b": "stage", "ci/c": "dev"})

    def test_odd_environment_stays_raw_with_unknown(self):
        root = self.tmp({".gitlab-ci.yml": "a:\n  environment: review/foo\n  script: [x]\n"})
        out = gitlab_ci.extract(root)
        self.assertEqual(out["components"][0]["env"], "review/foo")
        self.assertEqual([u["what"] for u in out["unknowns"]], ["ci/a"])
        self.assertIn("not one of dev/stage/prod", out["unknowns"][0]["why"])

    def test_chdir_gives_call_edge_to_project_boundary(self):
        root = self.tmp({
            "infra/x/main.tf": 'resource "google_project" "p" {\n  project_id = "p1"\n  name = "p1"\n  project = "p1"\n}\n',
            ".gitlab-ci.yml": "apply:\n  stage: deploy\n  script:\n    - terraform -chdir=infra/x apply\n"})
        out = gitlab_ci.extract(root)
        self.assertEqual([(e["from"], e["to"], e["kind"], e["label"], e["source"]) for e in out["edges"]],
                         [("ci/apply", "infra/x/project:p1", "call", "terraform", ".gitlab-ci.yml:4")])

    def test_chdir_without_boundary_is_unknown(self):
        root = self.tmp({"infra/y/main.tf": 'resource "google_pubsub_topic" "t" {\n  name = "t"\n}\n',
                         ".gitlab-ci.yml": "apply:\n  script:\n    - cd infra/y && terraform apply\n"})
        out = gitlab_ci.extract(root)
        self.assertEqual(out["edges"], [])
        self.assertTrue([u for u in out["unknowns"] if u["source"] == ".gitlab-ci.yml:3"])

if __name__ == "__main__":
    unittest.main()
