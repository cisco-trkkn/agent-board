"""newproject._http verifies TLS against a CA bundle even when Python ships none (python.org builds)."""
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import newproject as np  # noqa: E402


class FakeCtx:
    def __init__(self, ca):
        self.ca = ca
        self.loaded = []

    def cert_store_stats(self):
        return {"x509_ca": self.ca}

    def load_verify_locations(self, cafile=None):
        self.loaded.append(cafile)


class SslContext(unittest.TestCase):
    def setUp(self):
        np._ssl_context.cache_clear()
        self.addCleanup(np._ssl_context.cache_clear)

    def test_http_passes_context_to_urlopen(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = io.BytesIO(b"{}")
        resp.__enter__.return_value.status = 200
        sentinel = object()
        with mock.patch.object(np, "_ssl_context", return_value=sentinel), \
                mock.patch("urllib.request.urlopen", return_value=resp) as uo:
            np._http("GET", "/gateway", "tok")
        self.assertIs(uo.call_args.kwargs.get("context"), sentinel)

    def test_empty_store_loads_ssl_cert_file(self):
        ctx = FakeCtx(0)
        with mock.patch("ssl.create_default_context", return_value=ctx), \
                mock.patch.dict(os.environ, {"SSL_CERT_FILE": "/some/bundle.pem"}), \
                mock.patch("os.path.exists", return_value=True):
            self.assertIs(np._ssl_context(), ctx)
        self.assertEqual(ctx.loaded, ["/some/bundle.pem"])

    def test_empty_store_falls_back_to_system_bundle(self):
        ctx = FakeCtx(0)
        env = {k: v for k, v in os.environ.items() if k != "SSL_CERT_FILE"}
        with mock.patch("ssl.create_default_context", return_value=ctx), \
                mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("os.path.exists", side_effect=lambda p: p == "/etc/ssl/cert.pem"):
            np._ssl_context()
        self.assertEqual(ctx.loaded, ["/etc/ssl/cert.pem"])

    def test_populated_store_is_left_alone(self):
        ctx = FakeCtx(5)
        with mock.patch("ssl.create_default_context", return_value=ctx):
            np._ssl_context()
        self.assertEqual(ctx.loaded, [])

    def test_real_context_verifies(self):
        import ssl
        ctx = np._ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)


if __name__ == "__main__":
    unittest.main()
