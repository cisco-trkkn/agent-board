import os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); AUDIT = os.path.dirname(HERE)

GOOD = """## Findings
### F-sieve-1: Observer scan runs every session
Label: Measured
Evidence: injection_costs.json sources["hook:SessionStart"].total_chars=41210
Component · Root cause · Impact
Confidence: high · Candidate change · How to validate
"""
BAD = """### F-sieve-2: Claim with no evidence
Label: Verified
Evidence: none
"""

def run(*args):
    return subprocess.run(list(args), capture_output=True, text=True)

def tmp(text):
    fd, p = tempfile.mkstemp(suffix=".md"); os.write(fd, text.encode()); os.close(fd); return p

class Checks(unittest.TestCase):
    def test_good_passes(self):
        r = run(sys.executable, os.path.join(AUDIT, "check_findings.py"), tmp(GOOD), "--require-heading", "Findings")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("OK 1 findings", r.stdout)

    def test_verified_without_evidence_fails(self):
        r = run(sys.executable, os.path.join(AUDIT, "check_findings.py"), tmp(BAD))
        self.assertEqual(r.returncode, 1); self.assertIn("F-sieve-2", r.stdout)

    def test_missing_heading_fails(self):
        r = run(sys.executable, os.path.join(AUDIT, "check_findings.py"), tmp(GOOD), "--require-heading", "Roadmap")
        self.assertEqual(r.returncode, 1)

    def test_min_findings(self):
        r = run(sys.executable, os.path.join(AUDIT, "check_findings.py"), tmp(GOOD), "--min-findings", "2")
        self.assertEqual(r.returncode, 1)

    def test_redact_flags_key(self):
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), tmp("token glpat-" + "a" * 20 + "\n"))
        self.assertEqual(r.returncode, 1)

    def test_redact_clean(self):
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), tmp("nothing here\n"))
        self.assertEqual(r.returncode, 0); self.assertIn("redact: clean (1 files)", r.stdout)

    def test_redact_flags_json_password(self):
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), tmp('{"password": "hunter2hunter2"}\n'))
        self.assertEqual(r.returncode, 1)

    def test_redact_flags_api_key(self):
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), tmp("api_key=abcdef123456\n"))
        self.assertEqual(r.returncode, 1)

    def test_redact_flags_bearer_and_jwt(self):
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), tmp("Authorization: Bearer " + "a" * 24 + "\n"))
        self.assertEqual(r.returncode, 1)
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), tmp("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig\n"))
        self.assertEqual(r.returncode, 1)

    def test_redact_missing_file_is_error(self):
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), "/nonexistent/x.md")
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("clean", r.stdout)

    def test_redact_allows_usage_token_keys(self):
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), tmp('{"input_tokens": 2, "output_tokens": 72}\n'))
        self.assertEqual(r.returncode, 0)

if __name__ == "__main__":
    unittest.main()
