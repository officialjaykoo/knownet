from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .client_profiles import load_client_profiles
from .server import KnowNetMcpServer, SERVER_VERSION


def capability_payload(mcp: KnowNetMcpServer) -> dict[str, Any]:
    return {
        "ok": True,
        "name": "knownet-mcp-http",
        "version": SERVER_VERSION,
        "project": "KnowNet AI collaboration knowledge base",
        "transport": {
            "jsonrpc_endpoint": "/mcp",
            "method": "POST",
            "content_type": "application/json",
            "note": "Use JSON-RPC initialize, tools/list, and tools/call. GET only returns safe discovery metadata.",
        },
        "transport_profiles": {
            "local_stdio": {
                "recommended_for": ["Claude Desktop", "Cursor", "local agent runners"],
                "command_pattern": "python apps/mcp/knownet_mcp/server.py",
                "auth_location": "environment variable KNOWNET_AGENT_TOKEN",
                "note": "Preferred for desktop clients because the MCP host starts a local process and no public tunnel is required.",
            },
            "streamable_http_bridge": {
                "recommended_for": ["ChatGPT custom connector tests", "HTTPS Custom MCP clients", "temporary external reviews"],
                "endpoint": "/mcp",
                "methods": ["GET discovery", "POST JSON-RPC"],
                "auth_location": "bridge-held environment variable KNOWNET_AGENT_TOKEN",
                "note": "Use only behind a trusted local network or protected HTTPS gateway. Quick tunnels are testing-only.",
            },
        },
        "client_profiles": load_client_profiles(),
        "auth": {
            "method": "bridge-held bearer token",
            "note": "Agent tokens are scoped and never returned in discovery, tool, resource, or event responses.",
        },
        "recommended_flow": [
            "initialize",
            "resources/list",
            "resources/read knownet://snapshot/overview",
            "resources/read knownet://finding/recent",
            "tools/call knownet.propose_finding",
        ],
        "error_catalog": {
            "invalid_params": {"jsonrpc_code": -32602, "meaning": "Input does not match the tool schema, including maxLength limits."},
            "parse_error": {"jsonrpc_code": -32700, "meaning": "Request body is not valid JSON."},
        },
        "fallback_rule": "No compatibility fallback is exposed. Use MCP resources, tools, and prompts.",
        "fallback_mode": "none",
        "release_status": {
            "release_ready": False,
            "blockers": [
                "Quick tunnel access is for testing only; a named tunnel with access controls is required for operational external access.",
                "External AI review findings are still being triaged and hardened before a release-ready claim.",
            ],
        },
        "infrastructure_notice": {
            "tunnel_type": "temporary_quick_tunnel",
            "production_ready": False,
            "recommended_use": "testing_only",
            "note": "Use a named tunnel with access controls before treating external connector access as operational.",
        },
        "tools": [{"name": item["name"], "description": item["description"], "inputSchema": item["inputSchema"]} for item in mcp.tool_specs()],
        "resources_get_note": "Resource reads use JSON-RPC resources/read. GET discovery is metadata-only.",
        "resources": mcp.resource_specs(),
    }


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
            mcp = self.server.knownet_mcp  # type: ignore[attr-defined]
            self._send_json(200, capability_payload(mcp))
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
