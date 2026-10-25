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

if __name__ == "__main__":
    unittest.main()
