import glob, os, shutil, subprocess, tempfile, unittest
from helpers import run, FIXTURE

PROBE = '\nresource "google_cloud_run_v2_service" "probe" {\n  name     = "probe"\n  location = "us-central1"\n  project  = var.project_id\n}\n'
CKEY = lambda e: (e["from"], e["to"], e["kind"], e["label"])

class Since(unittest.TestCase):
    def setUp(self):
        # Leak seam: every temp dir this test (and inventory.build_at) creates lives under one dedicated dir.
        self.seam = tempfile.mkdtemp(prefix="since-seam-")
        self.old_tempdir, tempfile.tempdir = tempfile.tempdir, self.seam
        self.repo = os.path.join(self.seam, "repo")
        os.makedirs(os.path.join(self.repo, "infra"))
        shutil.copytree(os.path.join(FIXTURE, "infra", "ledger"), os.path.join(self.repo, "infra", "ledger"))
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "A")
        self.a = self.git("rev-parse", "HEAD")

    def tearDown(self):
        tempfile.tempdir = self.old_tempdir
        shutil.rmtree(self.seam)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit_b(self, cut_block=True, shift=False):
        p = os.path.join(self.repo, "infra", "ledger", "main.tf")
        with open(p) as fh:
            lines = fh.read().split("\n")
        if cut_block:
            start = next(i for i, l in enumerate(lines) if 'ledger_password_reader' in l)
            self.assertEqual(start, 204)      # main.tf:205
            del lines[start:start + 8]        # 7-line block + the blank line after
        text = "\n".join(lines)
        text = "# shifted\n" + text if shift else text + PROBE
        with open(p, "w") as fh:
            fh.write(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "B")
        return self.git("rev-parse", "HEAD")

    def test_probe_added_and_edge_removed(self):
        b = self.commit_b()
        code, out, err = run([self.repo, "--since", self.a])
        self.assertEqual(code, 0, err)
        self.assertEqual((out["since"], out["head"]), (self.a, b))
        self.assertIn("infra/ledger/google_cloud_run_v2_service.probe", [c["id"] for c in out["components"]["added"]])
        removed = [e for e in out["edges"]["removed"]
                   if (e["from"], e["to"], e["kind"]) == ("infra/ledger/google_service_account.ledger",
                                                          "infra/ledger/google_secret_manager_secret.db_password", "iam")]
        self.assertEqual([e["label"] for e in removed], ["roles/secretmanager.secretAccessor"])

    def test_line_shift_is_not_a_change(self):
        self.commit_b(cut_block=False, shift=True)
        code, out, err = run([self.repo, "--since", self.a])
        self.assertEqual(code, 0, err)
        self.assertEqual(out["components"], {"added": [], "removed": [], "changed": []})
        self.assertEqual(out["edges"], {"added": [], "removed": []})

    def test_changed_lists_kind_name_project_env_differences(self):
        p = os.path.join(self.repo, "infra", "ledger", "main.tf")
        with open(p) as fh:
            text = fh.read()
        with open(p, "w") as fh:
            fh.write(text.replace('resource "google_secret_manager_secret" "db_password" {',
                                         'resource "google_secret_manager_secret" "db_password" {\n  name = "renamed"', 1))
        self.git("add", "-A"); self.git("commit", "-q", "-m", "B")
        code, out, err = run([self.repo, "--since", self.a])
        self.assertEqual([c["id"] for c in out["components"]["changed"]],
                         ["infra/ledger/google_secret_manager_secret.db_password"])

    def test_untracked_tf_is_not_reported(self):
        b = self.commit_b()
        with open(os.path.join(self.repo, "infra", "ledger", "untracked.tf"), "w") as fh:
            fh.write('resource "google_pubsub_topic" "untracked" {\n  name = "u"\n}\n')
        code, out, err = run([self.repo, "--since", self.a])
        self.assertEqual(code, 0, err)
        self.assertEqual(out["head"], b)
        ids = [c["id"] for c in out["components"]["added"]]
        self.assertNotIn("infra/ledger/google_pubsub_topic.untracked", ids)
        self.assertIn("infra/ledger/google_cloud_run_v2_service.probe", ids)

    def test_since_resolved_to_full_sha(self):
        self.commit_b()
        for ref in (self.a[:8], "HEAD~1"):
            code, out, err = run([self.repo, "--since", ref])
            self.assertEqual((code, out["since"]), (0, self.a), ref)

    def test_unknown_sha_exits_2(self):
        code, out, err = run([self.repo, "--since", "0" * 40])
        self.assertEqual(code, 2)
        self.assertIn("inventory: unknown --since sha", err)

    def test_no_temp_leak(self):
        self.commit_b()
        run([self.repo, "--since", self.a])
        run([self.repo, "--since", "0" * 40])
        self.assertEqual(os.listdir(self.seam), ["repo"])

if __name__ == "__main__":
    unittest.main()
