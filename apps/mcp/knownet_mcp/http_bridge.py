from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .server import KnowNetMcpServer, SERVER_VERSION


def capability_payload(mcp: KnowNetMcpServer) -> dict[str, Any]:
    resources = []
    for item in mcp.resource_specs():
        enriched = dict(item)
        if item["uri"] == "knownet://agent/onboarding":
            enriched["http_get"] = "/mcp?resource=agent:onboarding"
        elif item["uri"] == "knownet://agent/state-summary":
            enriched["http_get"] = "/mcp?resource=agent:state-summary"
        resources.append(enriched)
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
        "auth": {
            "method": "bridge-held bearer token",
            "note": "Agent tokens are scoped and never returned in discovery, tool, resource, or event responses.",
        },
        "recommended_flow": [
            "search",
            "fetch agent:onboarding",
            "fetch agent:state-summary",
            "knownet_start_here",
            "knownet_me",
            "knownet_state_summary",
            "knownet_ai_state",
            "knownet_list_findings",
            "knownet_review_dry_run",
        ],
        "fallback_example": {
            "jsonrpc_search": {"query": "KnowNet current state", "expected_result_ids": ["agent:onboarding", "agent:state-summary", "page:{page_id}"]},
            "jsonrpc_fetch": {"id": "agent:onboarding", "expected_fields": ["id", "title", "payload", "text"]},
            "http_get_preview": ["/mcp?resource=agent:onboarding", "/mcp?resource=agent:state-summary"],
            "note": "GET-only clients can only use http_get_preview. search/fetch require JSON-RPC POST tools/call.",
        },
        "error_catalog": {
            "invalid_params": {"jsonrpc_code": -32602, "meaning": "Input does not match the tool schema, including maxLength limits."},
            "parse_error": {"jsonrpc_code": -32700, "meaning": "Request body is not valid JSON."},
        },
        "fallback_rule": "If knownet_* tools are not visible, use search and fetch. Do not substitute unrelated public repositories for KnowNet state.",
        "fallback_mode": "get_preview_available",
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
        "resources_get_note": "Full resource reads use JSON-RPC resources/read. GET previews expose only onboarding and state-summary for clients that cannot POST. Review dry-run is intentionally POST-only so review bodies are not placed in URLs or GET logs.",
        "resources": resources,
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
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = {}
            if query:
                from urllib.parse import parse_qs

                params = {key: values[0] for key, values in parse_qs(query).items() if values}
            mcp = self.server.knownet_mcp  # type: ignore[attr-defined]
            resource = params.get("resource")
            if resource in {"agent:onboarding", "agent:state-summary"}:
                fetch_id = "agent:onboarding" if resource == "agent:onboarding" else "agent:state-summary"
                self._send_json(200, mcp.call_tool("fetch", {"id": fetch_id}))
                return
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
