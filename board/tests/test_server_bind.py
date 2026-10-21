"""The board's HTTP server must bind without a reverse-DNS lookup: http.server.HTTPServer.server_bind calls
socket.getfqdn(), which hung for 30s+ on the macOS CI runner and left the server silent at startup."""
import importlib.util
import os
import socket
import unittest
from pathlib import Path
from unittest import mock

BOARD = Path(__file__).resolve().parent.parent


class ServerBindTest(unittest.TestCase):
    def test_bind_does_not_resolve_the_host_name(self):
        saved = os.environ.get("TMUX_DASH_TOKEN")
        os.environ["TMUX_DASH_TOKEN"] = "bindtesttoken"
        self.addCleanup(lambda: os.environ.__setitem__("TMUX_DASH_TOKEN", saved) if saved is not None else os.environ.pop("TMUX_DASH_TOKEN", None))
        spec = importlib.util.spec_from_file_location("tmux_dash_server_bind", BOARD / "server.py")
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        with mock.patch.object(socket, "getfqdn", side_effect=AssertionError("getfqdn called: reverse DNS can hang a CI runner")):
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.addCleanup(httpd.server_close)
        self.assertEqual(httpd.server_address[0], "127.0.0.1")
        self.assertEqual(httpd.server_port, httpd.server_address[1])


if __name__ == "__main__":
    unittest.main()
