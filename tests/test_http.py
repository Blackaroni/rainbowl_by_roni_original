from __future__ import annotations

import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from rainbowl_app.http import build_handler


class DummyRepository:
    def dashboard(self):
        return {"status": "ok"}


class HttpCorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        handler = build_handler(
            DummyRepository(),
            Path(__file__).resolve().parent.parent / "static",
            allowed_origins=("https://rainbowl-demo.netlify.app",),
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method: str, path: str, headers: dict[str, str] | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_options_returns_cors_headers_for_allowed_origin(self) -> None:
        response, _ = self.request(
            "OPTIONS",
            "/api/health",
            headers={
                "Origin": "https://rainbowl-demo.netlify.app",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status, 204)
        self.assertEqual(
            response.getheader("Access-Control-Allow-Origin"),
            "https://rainbowl-demo.netlify.app",
        )
        self.assertIn("GET", response.getheader("Access-Control-Allow-Methods", ""))

    def test_get_returns_cors_header_for_allowed_origin(self) -> None:
        response, _ = self.request(
            "GET",
            "/api/health",
            headers={"Origin": "https://rainbowl-demo.netlify.app"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.getheader("Access-Control-Allow-Origin"),
            "https://rainbowl-demo.netlify.app",
        )

    def test_options_rejects_disallowed_origin(self) -> None:
        response, body = self.request(
            "OPTIONS",
            "/api/health",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status, 403)
        self.assertIn(b"Origin not allowed", body)
