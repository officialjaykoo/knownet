from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .server import KnowNetMcpServer, SERVER_VERSION


class McpHttpHandler(BaseHTTPRequestHandler):
    server_version = f"KnowNetMcpHttp/{SERVER_VERSION}"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in {"/", "/health"}:
            self._send_json(200, {"ok": True, "name": "knownet-mcp-http", "version": SERVER_VERSION})
            return
        if path in {"/mcp", "/mcp/tools", "/.well-known/mcp"}:
            self._send_json(405, {"ok": False, "error": "method_not_allowed", "message": "Use JSON-RPC POST /mcp."})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path.split("?", 1)[0].rstrip("/") != "/mcp":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        try:
            length = int(self.headers.get("content-length") or "0")
        except ValueError:
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            return
        if length <= 0 or length > 1024 * 1024:
            self._send_json(413, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            return
        try:
            message = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            return

        response = self.server.knownet_mcp.handle_jsonrpc(message)  # type: ignore[attr-defined]
        if response is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send_json(200, response)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    host = os.getenv("KNOWNET_MCP_HTTP_HOST", "127.0.0.1")
    port = int(os.getenv("KNOWNET_MCP_HTTP_PORT", "8010"))
    httpd = ThreadingHTTPServer((host, port), McpHttpHandler)
    httpd.knownet_mcp = KnowNetMcpServer()  # type: ignore[attr-defined]
    print(f"KnowNet MCP HTTP bridge listening on http://{host}:{port}/mcp", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
