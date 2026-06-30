from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .db import Repository


def build_handler(
    repository: Repository,
    static_dir: Path,
    *,
    allowed_origins: tuple[str, ...] = (),
) -> type[BaseHTTPRequestHandler]:
    class RainbowlRequestHandler(BaseHTTPRequestHandler):
        repo = repository
        assets_dir = static_dir
        cors_allowed_origins = allowed_origins

        def do_OPTIONS(self) -> None:  # noqa: N802
            if not urlparse(self.path).path.startswith("/api/"):
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            origin = self._resolve_allowed_origin()
            if self.headers.get("Origin") and origin is None:
                self._send_json({"error": "Origin not allowed."}, status=HTTPStatus.FORBIDDEN)
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers(origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                self.headers.get("Access-Control-Request-Headers", "Content-Type"),
            )
            self.send_header("Access-Control-Max-Age", "86400")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/api/health":
                    self._send_json({"status": "ok"})
                    return
                if path == "/api/dashboard":
                    self._send_json(self.repo.dashboard())
                    return
                if path == "/api/customers/next-id":
                    self._send_json({"next_customer_id": self.repo.next_customer_legacy_id()})
                    return
                if path == "/api/customers":
                    self._send_json(self.repo.list_customers())
                    return
                if path == "/api/products":
                    self._send_json(self.repo.list_products())
                    return
                if path.startswith("/api/products/"):
                    product_id = self._extract_resource_id(path)
                    self._send_json(self.repo.get_product(product_id))
                    return
                if path == "/api/orders":
                    self._send_json(self.repo.list_orders())
                    return
                if path.startswith("/api/orders/"):
                    order_id = self._extract_resource_id(path)
                    self._send_json(self.repo.get_order(order_id))
                    return
                if path == "/api/expenses":
                    self._send_json(self.repo.list_expenses())
                    return
                if path == "/api/account-snapshots":
                    self._send_json(self.repo.list_account_snapshots())
                    return
                if path == "/api/insights/monthly":
                    self._send_json(self.repo.monthly_insights())
                    return
                if path == "/api/sales-lines":
                    self._send_json(self.repo.list_sales_lines())
                    return
                self._serve_static(path)
            except LookupError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/api/customers":
                    self._send_json(self.repo.create_customer(self._read_json_body()), status=HTTPStatus.CREATED)
                    return
                if path == "/api/products":
                    self._send_json(self.repo.create_product(self._read_json_body()), status=HTTPStatus.CREATED)
                    return
                if path == "/api/orders":
                    self._send_json(self.repo.create_order(self._read_json_body()), status=HTTPStatus.CREATED)
                    return
                if path.startswith("/api/orders/") and path.endswith("/payments"):
                    order_id = self._extract_resource_id(path.removesuffix("/payments"))
                    self._send_json(
                        self.repo.add_payment(order_id, self._read_json_body()),
                        status=HTTPStatus.CREATED,
                    )
                    return
                if path == "/api/expenses":
                    self._send_json(self.repo.create_expense(self._read_json_body()), status=HTTPStatus.CREATED)
                    return
                if path == "/api/account-snapshots":
                    self._send_json(
                        self.repo.create_account_snapshot(self._read_json_body()),
                        status=HTTPStatus.CREATED,
                    )
                    return
                self._send_json({"error": "Route not found."}, status=HTTPStatus.NOT_FOUND)
            except LookupError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_PATCH(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path.startswith("/api/orders/"):
                    order_id = self._extract_resource_id(path)
                    self._send_json(self.repo.update_order(order_id, self._read_json_body()))
                    return
                if path.startswith("/api/customers/"):
                    customer_id = self._extract_resource_id(path)
                    self._send_json(self.repo.update_customer(customer_id, self._read_json_body()))
                    return
                if path.startswith("/api/products/"):
                    product_id = self._extract_resource_id(path)
                    self._send_json(self.repo.update_product(product_id, self._read_json_body()))
                    return
                self._send_json({"error": "Route not found."}, status=HTTPStatus.NOT_FOUND)
            except LookupError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path.startswith("/api/products/"):
                    product_id = self._extract_resource_id(path)
                    self._send_json(self.repo.delete_product(product_id))
                    return
                self._send_json({"error": "Route not found."}, status=HTTPStatus.NOT_FOUND)
            except LookupError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def _serve_static(self, path: str) -> None:
            requested = "index.html" if path in {"", "/"} else path.lstrip("/")
            if requested.startswith("api/"):
                self._send_json({"error": "Route not found."}, status=HTTPStatus.NOT_FOUND)
                return
            file_path = (self.assets_dir / requested).resolve()
            if not str(file_path).startswith(str(self.assets_dir.resolve())) or not file_path.exists():
                file_path = self.assets_dir / "index.html"
            content_type, _ = mimetypes.guess_type(file_path.name)
            data = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self._send_cors_headers(self._resolve_allowed_origin())
            self.send_header("Content-Type", content_type or "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _extract_resource_id(self, path: str) -> int:
            try:
                return int(path.rstrip("/").split("/")[-1])
            except (TypeError, ValueError) as exc:
                raise ValueError("Invalid id.") from exc

        def _read_json_body(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON body.") from exc
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object.")
            return body

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self._send_cors_headers(self._resolve_allowed_origin())
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _resolve_allowed_origin(self) -> str | None:
            origin = self.headers.get("Origin")
            if not origin or not self.cors_allowed_origins:
                return None
            if "*" in self.cors_allowed_origins:
                return "*"
            if origin in self.cors_allowed_origins:
                return origin
            return None

        def _send_cors_headers(self, origin: str | None) -> None:
            if origin is None:
                return
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return RainbowlRequestHandler


def run_server(
    repository: Repository,
    static_dir: Path,
    host: str,
    port: int,
    *,
    allowed_origins: tuple[str, ...] = (),
) -> None:
    handler = build_handler(repository, static_dir, allowed_origins=allowed_origins)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Rainbowl running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()
