"""Shared by the test_metrics_* files (not a test module)."""
from unittest import mock

import metrics


def cache_main_root(testcase):
    """metrics.main_root runs `git rev-parse --git-common-dir` on every call, and every metrics.append makes one: hundreds
    of git processes per test file. Answer each repo path from the real function once per test; the repo's main root
    does not change while a test runs."""
    real, seen = metrics.main_root, {}

    def cached(repo):
        key = str(repo)
        if key not in seen:
            seen[key] = real(repo)
        return seen[key]
    p = mock.patch.object(metrics, "main_root", cached)
    p.start()
    testcase.addCleanup(p.stop)
