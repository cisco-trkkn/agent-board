import os, shutil, subprocess, tempfile, unittest
from helpers import run
from extractors import gitlab_ci

try:
    import hcl2  # noqa: F401
    HCL2 = True
except ImportError:
    HCL2 = False

TF = 'resource "google_pubsub_topic" "t" {\n  name = "t"\n  project = var.project_id\n}\n'

class RepoName(unittest.TestCase):
    """M3: meta.repo is the repo name, also when scanned through a detached worktree path (real git, temp repo only)."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="repo-name-seam-")
        self.repo = os.path.join(self.tmp, "mainrepo")
        os.makedirs(self.repo)
        with open(os.path.join(self.repo, "main.tf"), "w") as fh:
            fh.write(TF)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "A")
        self.wt = os.path.join(self.tmp, "scratch-wt")
        self.git("worktree", "add", "-q", "--detach", self.wt, "HEAD")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, check=True).stdout.strip()

    def test_origin_name_through_detached_worktree(self):
        self.git("remote", "add", "origin", "git@gitlab.example.com:acme/the-real-name.git")
        code, inv, err = run([self.wt])
        self.assertEqual(code, 0, err)
        self.assertEqual(inv["meta"]["repo"], "the-real-name")

    def test_no_origin_uses_main_checkout_name_not_worktree_dir(self):
        code, inv, err = run([self.wt])
        self.assertEqual(code, 0, err)
        self.assertEqual(inv["meta"]["repo"], "mainrepo")

    def test_not_a_git_repo_uses_dir_basename(self):
        d = os.path.join(self.tmp, "plain")
        os.makedirs(d)
        with open(os.path.join(d, "main.tf"), "w") as fh:
            fh.write(TF)
        code, inv, err = run([d])
        self.assertEqual((code, inv["meta"]["repo"]), (0, "plain"))

class CiDuplicateJob(unittest.TestCase):
    """M9: one job id defined in two files → one component (later definition wins) + an unknown naming both sources."""
    def test_duplicate_job_id(self):
        with tempfile.TemporaryDirectory() as d:
            for f, stage in ((".gitlab-ci-a.yml", "one"), (".gitlab-ci-b.yml", "two")):
                with open(os.path.join(d, f), "w") as fh:
                    fh.write(f"validate:\n  stage: {stage}\n  script:\n    - echo hi\n")
            out = gitlab_ci.extract(d)
        jobs = [c for c in out["components"] if c["id"] == "ci/validate"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"], ".gitlab-ci-b.yml:1")
        unk = [u for u in out["unknowns"] if u["what"] == "ci/validate"]
        self.assertEqual(len(unk), 1)
        self.assertIn("job defined in 2 files", unk[0]["why"])
        self.assertIn(".gitlab-ci-a.yml:1", unk[0]["why"])
        self.assertIn(".gitlab-ci-b.yml:1", unk[0]["why"])

class UnparseableTf(unittest.TestCase):
    """I2 (spec:97): an unparseable .tf file lands in unknowns[], not a crash."""
    @unittest.skipUnless(HCL2, "python-hcl2 not importable")
    def test_broken_tf_is_an_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ok.tf"), "w") as fh:
                fh.write(TF)
            with open(os.path.join(d, "broken.tf"), "w") as fh:
                fh.write('resource "google_pubsub_topic" "x" {\n  name = \n')
            code, inv, err = run([d])
        self.assertEqual(code, 0, err)
        self.assertEqual(inv["meta"]["confidence"], "low")
        self.assertTrue([u for u in inv["unknowns"] if u["what"] == "broken.tf" and "could not parse" in u["why"]])

if __name__ == "__main__":
    unittest.main()
