from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


ALLOWED_TOOLS = {
    "knownet_ping",
    "knownet_me",
    "knownet_state_summary",
    "knownet_list_pages",
    "knownet_read_page",
    "knownet_list_reviews",
    "knownet_list_findings",
    "knownet_graph_summary",
    "knownet_list_citations",
    "knownet_review_dry_run",
    "knownet_submit_review",
}


@dataclass
class KnowNetHttpError(Exception):
    status: int
    payload: dict[str, Any]


@dataclass
class McpToolInputError(Exception):
    message: str


class KnowNetMcpServer:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.getenv("KNOWNET_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.token = token if token is not None else os.getenv("KNOWNET_AGENT_TOKEN")
        self.timeout = timeout if timeout is not None else float(os.getenv("KNOWNET_MCP_TIMEOUT_SECONDS", "30"))

    def tool_specs(self) -> list[dict[str, Any]]:
        return [
            {"name": "knownet_ping", "description": "Check whether KnowNet agent API is reachable.", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "knownet_me", "description": "Inspect the current agent token capabilities.", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "knownet_state_summary", "description": "Read scoped KnowNet state counts.", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "knownet_list_pages", "description": "List scoped pages.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
            {"name": "knownet_read_page", "description": "Read one scoped page.", "inputSchema": {"type": "object", "properties": {"page_id": {"type": "string"}}, "required": ["page_id"]}},
            {"name": "knownet_list_reviews", "description": "List scoped collaboration reviews.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
            {"name": "knownet_list_findings", "description": "List scoped findings.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
            {"name": "knownet_graph_summary", "description": "Read scoped graph summary.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
            {"name": "knownet_list_citations", "description": "List scoped citation audits.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
            {"name": "knownet_review_dry_run", "description": "Parse a review without creating records.", "inputSchema": {"type": "object", "properties": {"markdown": {"type": "string"}, "source_agent": {"type": "string"}, "source_model": {"type": "string"}}, "required": ["markdown"]}},
            {"name": "knownet_submit_review", "description": "Submit a structured agent review.", "inputSchema": {"type": "object", "properties": {"markdown": {"type": "string"}, "source_agent": {"type": "string"}, "source_model": {"type": "string"}}, "required": ["markdown"]}},
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            raise ValueError(f"unknown or forbidden tool: {name}")
        args = arguments or {}
        table: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "knownet_ping": lambda _: self._request("GET", "/api/agent/ping", auth=False),
            "knownet_me": lambda _: self._request("GET", "/api/agent/me"),
            "knownet_state_summary": lambda _: self._request("GET", "/api/agent/state-summary"),
            "knownet_list_pages": lambda a: self._request("GET", "/api/agent/pages", query={"limit": a.get("limit")}),
            "knownet_read_page": lambda a: self._request("GET", f"/api/agent/pages/{urllib.parse.quote(str(a['page_id']))}"),
            "knownet_list_reviews": lambda a: self._request("GET", "/api/agent/reviews", query={"limit": a.get("limit")}),
            "knownet_list_findings": lambda a: self._request("GET", "/api/agent/findings", query={"limit": a.get("limit")}),
            "knownet_graph_summary": lambda a: self._request("GET", "/api/agent/graph", query={"limit": a.get("limit")}),
            "knownet_list_citations": lambda a: self._request("GET", "/api/agent/citations", query={"limit": a.get("limit")}),
            "knownet_review_dry_run": lambda a: self._review(a, dry_run=True),
            "knownet_submit_review": lambda a: self._review(a, dry_run=False),
        }
        try:
            return table[name](args)
        except (KeyError, TypeError, McpToolInputError) as error:
            return {"ok": False, "error": {"code": "invalid_tool_input", "message": str(error) or "Invalid tool arguments."}}
        except KnowNetHttpError as error:
            return {"ok": False, "error": self._map_error(error.status, error.payload)}

    def _review(self, args: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        if not isinstance(args.get("markdown"), str) or not args["markdown"].strip():
            raise McpToolInputError("markdown is required.")
        payload = {"markdown": args["markdown"]}
        if args.get("source_agent"):
            payload["source_agent"] = args["source_agent"]
        if args.get("source_model"):
            payload["source_model"] = args["source_model"]
        path = "/api/collaboration/reviews?dry_run=true" if dry_run else "/api/collaboration/reviews"
        return self._request("POST", path, payload=payload)

    def _request(self, method: str, path: str, *, query: dict[str, Any] | None = None, payload: dict[str, Any] | None = None, auth: bool = True) -> dict[str, Any]:
        if auth and not self.token:
            raise KnowNetHttpError(401, {"detail": {"code": "agent_token_required"}})
        clean_query = {k: v for k, v in (query or {}).items() if v is not None}
        url = self.base_url + path
        if clean_query:
            url += "?" + urllib.parse.urlencode(clean_query)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                payload_data = json.loads(error.read().decode("utf-8"))
            except Exception:
                payload_data = {"detail": {"message": str(error)}}
            raise KnowNetHttpError(error.code, payload_data) from error

    def _map_error(self, status: int, payload: dict[str, Any]) -> dict[str, Any]:
        detail = payload.get("detail") or payload.get("error") or {}
        details = detail.get("details") or {}
        if status == 401:
            return {"code": "auth_failed", "message": "KnowNet agent token is missing or invalid."}
        if status == 403:
            return {"code": "scope_denied", "message": "KnowNet agent token lacks the required scope.", "missing_scope": details.get("scope")}
        if status == 413:
            return {"code": "context_too_large", "message": "Requested context is too large. Use a narrower page or context selection."}
        if status == 429:
            return {"code": "rate_limited", "message": "KnowNet rate limit reached.", "retry_after_seconds": details.get("retry_after_seconds")}
        return {"code": detail.get("code", "knownet_error"), "message": detail.get("message", "KnowNet request failed.")}

    def handle_jsonrpc(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "knownet", "version": "10.0"}, "capabilities": {"tools": {}}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tool_specs()}}
        if method == "tools/call":
            params = message.get("params") or {}
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid params"}}
            result = self.call_tool(params["name"], params.get("arguments") or {})
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "isError": not result.get("ok", False),
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                },
            }
        if method == "notifications/initialized":
            return None
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main() -> None:
    server = KnowNetMcpServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            print(json.dumps(response), flush=True)
            continue
        response = server.handle_jsonrpc(message)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
