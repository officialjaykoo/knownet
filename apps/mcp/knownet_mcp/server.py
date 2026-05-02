from __future__ import annotations

import json
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4


PROTOCOL_VERSION = "2024-11-05"
SERVER_VERSION = "14.0"

ALLOWED_TOOLS = {
    "search",
    "fetch",
    "knownet_ping",
    "knownet_start_here",
    "knownet_me",
    "knownet_state_summary",
    "knownet_ai_state",
    "knownet_list_pages",
    "knownet_read_page",
    "knownet_list_reviews",
    "knownet_list_findings",
    "knownet_graph_summary",
    "knownet_list_citations",
    "knownet_review_dry_run",
    "knownet_submit_review",
}

ALLOWED_RESOURCES = {
    "knownet://agent/onboarding",
    "knownet://agent/me",
    "knownet://agent/state-summary",
    "knownet://agent/ai-state",
    "knownet://agent/pages",
    "knownet://agent/reviews",
    "knownet://agent/findings",
    "knownet://agent/graph",
    "knownet://agent/citations",
}

ALLOWED_PROMPTS = {
    "knownet_review_page",
    "knownet_review_findings",
    "knownet_prepare_external_review",
}

FINDING_FORMAT = """### Finding

Severity: critical | high | medium | low | info
Area: API | UI | Rust | Security | Data | Ops | Docs

Evidence:
...

Proposed change:
...
"""


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "search": object_schema({"query": {"type": "string", "minLength": 1, "maxLength": 240}}, ["query"]),
    "fetch": object_schema({"id": {"type": "string", "minLength": 1, "maxLength": 220}}, ["id"]),
    "knownet_ping": object_schema({}),
    "knownet_start_here": object_schema({}),
    "knownet_me": object_schema({}),
    "knownet_state_summary": object_schema({}),
    "knownet_ai_state": object_schema({
        "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
        "offset": {"type": "integer", "default": 0, "minimum": 0},
    }),
    "knownet_list_pages": object_schema({
        "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
        "offset": {"type": "integer", "default": 0, "minimum": 0},
    }),
    "knownet_read_page": object_schema({"page_id": {"type": "string", "minLength": 1, "maxLength": 160}}, ["page_id"]),
    "knownet_list_reviews": object_schema({
        "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
        "offset": {"type": "integer", "default": 0, "minimum": 0},
    }),
    "knownet_list_findings": object_schema({
        "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 200},
        "offset": {"type": "integer", "default": 0, "minimum": 0},
        "status": {"type": "string", "enum": ["accepted", "rejected", "deferred", "needs_more_context"]},
    }),
    "knownet_graph_summary": object_schema({"limit": {"type": "integer", "default": 200, "minimum": 1, "maximum": 1000}}),
    "knownet_list_citations": object_schema({
        "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 200},
        "offset": {"type": "integer", "default": 0, "minimum": 0},
        "status": {"type": "string", "minLength": 1, "maxLength": 80},
    }),
    "knownet_review_dry_run": object_schema({
        "markdown": {"type": "string", "minLength": 1, "maxLength": 262144},
        "source_agent": {"type": "string", "maxLength": 120},
        "source_model": {"type": "string", "maxLength": 120},
    }, ["markdown"]),
    "knownet_submit_review": object_schema({
        "markdown": {"type": "string", "minLength": 1, "maxLength": 262144},
        "source_agent": {"type": "string", "maxLength": 120},
        "source_model": {"type": "string", "maxLength": 120},
    }, ["markdown"]),
}

PROMPT_ARGUMENTS: dict[str, dict[str, Any]] = {
    "knownet_review_page": object_schema({"page_id": {"type": "string", "minLength": 1, "maxLength": 160}}, ["page_id"]),
    "knownet_review_findings": object_schema({"status": {"type": "string", "enum": ["accepted", "rejected", "deferred", "needs_more_context"]}}),
    "knownet_prepare_external_review": object_schema({
        "focus": {"type": "string", "maxLength": 240},
        "max_pages": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
    }),
}


@dataclass
class KnowNetHttpError(Exception):
    status: int
    payload: dict[str, Any]


@dataclass
class McpInputError(Exception):
    message: str


class KnowNetMcpServer:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | None = None,
        *,
        log_stream: Any | None = None,
        log_level: str | None = None,
        log_format: str | None = None,
    ):
        self.base_url = (base_url or os.getenv("KNOWNET_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.token = token if token is not None else os.getenv("KNOWNET_AGENT_TOKEN")
        self.timeout = timeout if timeout is not None else float(os.getenv("KNOWNET_MCP_TIMEOUT_SECONDS", "30"))
        self.log_stream = log_stream if log_stream is not None else sys.stderr
        self.log_level = (log_level or os.getenv("KNOWNET_MCP_LOG_LEVEL") or "info").lower()
        self.log_format = (log_format or os.getenv("KNOWNET_MCP_LOG_FORMAT") or "json").lower()
        self.shutdown_requested = False
        self.active_requests = 0
        self.current_scopes: list[str] = []
        self.last_diagnostics: dict[str, Any] | None = None

    def request_shutdown(self, *_: Any) -> None:
        self.shutdown_requested = True
        self._log("shutdown", "signal", "ok", active_requests=self.active_requests)

    def tool_specs(self) -> list[dict[str, Any]]:
        return [
            {"name": "search", "description": "Search KnowNet state for ChatGPT connector compatibility.", "inputSchema": TOOL_SCHEMAS["search"]},
            {"name": "fetch", "description": "Fetch one KnowNet search result or state resource by id.", "inputSchema": TOOL_SCHEMAS["fetch"]},
            {"name": "knownet_ping", "description": "Check whether KnowNet agent API is reachable.", "inputSchema": TOOL_SCHEMAS["knownet_ping"]},
            {"name": "knownet_start_here", "description": "Read first-contact onboarding guidance for external AI agents.", "inputSchema": TOOL_SCHEMAS["knownet_start_here"]},
            {"name": "knownet_me", "description": "Inspect the current agent's scoped permissions and role. Raw token values are never returned.", "inputSchema": TOOL_SCHEMAS["knownet_me"]},
            {"name": "knownet_state_summary", "description": "Read scoped KnowNet state counts.", "inputSchema": TOOL_SCHEMAS["knownet_state_summary"]},
            {
                "name": "knownet_ai_state",
                "description": "Read paginated structured JSON state derived from KnowNet pages. Check meta.has_more/meta.truncated and use offset to continue.",
                "inputSchema": TOOL_SCHEMAS["knownet_ai_state"],
            },
            {"name": "knownet_list_pages", "description": "List scoped pages.", "inputSchema": TOOL_SCHEMAS["knownet_list_pages"]},
            {"name": "knownet_read_page", "description": "Read one scoped page.", "inputSchema": TOOL_SCHEMAS["knownet_read_page"]},
            {"name": "knownet_list_reviews", "description": "List scoped collaboration reviews.", "inputSchema": TOOL_SCHEMAS["knownet_list_reviews"]},
            {"name": "knownet_list_findings", "description": "List scoped findings.", "inputSchema": TOOL_SCHEMAS["knownet_list_findings"]},
            {"name": "knownet_graph_summary", "description": "Read scoped graph summary.", "inputSchema": TOOL_SCHEMAS["knownet_graph_summary"]},
            {"name": "knownet_list_citations", "description": "List scoped citation audits.", "inputSchema": TOOL_SCHEMAS["knownet_list_citations"]},
            {"name": "knownet_review_dry_run", "description": "Parse a review without creating records.", "inputSchema": TOOL_SCHEMAS["knownet_review_dry_run"]},
            {"name": "knownet_submit_review", "description": "Submit a structured agent review.", "inputSchema": TOOL_SCHEMAS["knownet_submit_review"]},
        ]

    def resource_specs(self) -> list[dict[str, Any]]:
        return [
            {"uri": "knownet://agent/onboarding", "name": "Agent onboarding", "mimeType": "application/json"},
            {"uri": "knownet://agent/me", "name": "Current agent", "mimeType": "application/json"},
            {"uri": "knownet://agent/state-summary", "name": "KnowNet state summary", "mimeType": "application/json"},
            {"uri": "knownet://agent/ai-state", "name": "Structured AI state", "mimeType": "application/json"},
            {"uri": "knownet://agent/pages", "name": "Scoped pages", "mimeType": "application/json"},
            {"uri": "knownet://agent/pages/{page_id}", "name": "One scoped page", "mimeType": "application/json"},
            {"uri": "knownet://agent/reviews", "name": "Collaboration reviews", "mimeType": "application/json"},
            {"uri": "knownet://agent/findings", "name": "Collaboration findings", "mimeType": "application/json"},
            {"uri": "knownet://agent/graph", "name": "Graph summary", "mimeType": "application/json"},
            {"uri": "knownet://agent/citations", "name": "Citation audits", "mimeType": "application/json"},
        ]

    def prompt_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "knownet_review_page",
                "description": "Review one page and return findings in the fixed format.",
                "arguments": [{"name": "page_id", "required": True, "description": "Page id to review."}],
            },
            {
                "name": "knownet_review_findings",
                "description": "Review existing findings and suggest decisions.",
                "arguments": [{"name": "status", "required": False, "description": "Optional finding status filter."}],
            },
            {
                "name": "knownet_prepare_external_review",
                "description": "Guide an external AI through bounded context discovery and review submission.",
                "arguments": [
                    {"name": "focus", "required": False, "description": "Review focus."},
                    {"name": "max_pages", "required": False, "description": "Maximum pages to inspect."},
                ],
            },
        ]

    def startup_diagnostics(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        ok = True
        try:
            ping = self._request("GET", "/api/agent/ping", auth=False, timeout=min(self.timeout, 3))
            checks.append({"name": "api_reachable", "status": "ok", "version": ping.get("version")})
        except Exception as error:
            ok = False
            checks.append({"name": "api_reachable", "status": "error", "message": str(error)})
        if not self.token:
            ok = False
            checks.append({"name": "agent_token", "status": "error", "message": "KNOWNET_AGENT_TOKEN is missing."})
        else:
            try:
                me = self._request("GET", "/api/agent/me", timeout=min(self.timeout, 3))
                data = me.get("data", {})
                scopes = data.get("scopes") or []
                self.current_scopes = list(scopes)
                expires_in = data.get("expires_in_seconds")
                checks.append({"name": "agent_token", "status": "ok", "token_id": data.get("token_id")})
                if not scopes:
                    ok = False
                    checks.append({"name": "agent_scopes", "status": "warning", "message": "Agent token has no scopes."})
                else:
                    checks.append({"name": "agent_scopes", "status": "ok", "count": len(scopes)})
                if isinstance(expires_in, int) and expires_in <= 7 * 24 * 60 * 60:
                    checks.append({"name": "token_expiry", "status": "warning", "token_warning": "expires_soon", "token_expires_in_seconds": expires_in})
            except KnowNetHttpError as error:
                ok = False
                checks.append({"name": "agent_token", "status": "error", "error": self._map_error(error.status, error.payload)})
            except Exception as error:
                ok = False
                checks.append({"name": "agent_token", "status": "error", "message": str(error)})
        diagnostics = {"ok": ok, "checks": checks}
        self.last_diagnostics = diagnostics
        self._log("startup", "diagnostics", "ok" if ok else "warning")
        return diagnostics

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None, *, request_id: str | None = None) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            return {"ok": False, "error": {"code": "unknown_tool", "message": f"Unknown or forbidden tool: {name}"}}
        if self.shutdown_requested:
            return {"ok": False, "error": {"code": "server_shutting_down", "message": "KnowNet MCP server is shutting down."}}
        started = time.perf_counter()
        self.active_requests += 1
        try:
            args = self._validate_args(name, arguments or {}, TOOL_SCHEMAS[name])
            result = self._call_validated_tool(name, args)
            result = self._with_next_offset(result, args)
            self._annotate_result(result, request_id=request_id)
            self._log("tools/call", name, "ok", duration_ms=self._duration(started), request_id=request_id)
            return result
        except McpInputError as error:
            self._log("tools/call", name, "error", duration_ms=self._duration(started), error_code="invalid_tool_input", request_id=request_id)
            return {"ok": False, "error": {"code": "invalid_tool_input", "message": error.message}}
        except KnowNetHttpError as error:
            mapped = self._map_error(error.status, error.payload)
            self._log("tools/call", name, "error", duration_ms=self._duration(started), error_code=mapped["code"], request_id=request_id)
            return {"ok": False, "error": mapped}
        finally:
            self.active_requests -= 1

    def read_resource(self, uri: str, *, request_id: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        self.active_requests += 1
        try:
            result = self._read_resource(uri)
            self._annotate_result(result, request_id=request_id)
            self._log("resources/read", uri, "ok", duration_ms=self._duration(started), request_id=request_id)
            return result
        except (McpInputError, KnowNetHttpError) as error:
            code = "invalid_resource" if isinstance(error, McpInputError) else self._map_error(error.status, error.payload)["code"]
            self._log("resources/read", uri, "error", duration_ms=self._duration(started), error_code=code, request_id=request_id)
            if isinstance(error, KnowNetHttpError):
                return {"ok": False, "error": self._map_error(error.status, error.payload)}
            return {"ok": False, "error": {"code": code, "message": error.message}}
        finally:
            self.active_requests -= 1

    def get_prompt(self, name: str, arguments: dict[str, Any] | None = None, *, request_id: str | None = None) -> dict[str, Any]:
        if name not in ALLOWED_PROMPTS:
            return {"ok": False, "error": {"code": "unknown_prompt", "message": f"Unknown prompt: {name}"}}
        try:
            args = self._validate_args(name, arguments or {}, PROMPT_ARGUMENTS[name])
            text = self._prompt_text(name, args)
            self._log("prompts/get", name, "ok", request_id=request_id)
            return {"ok": True, "description": name, "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}
        except McpInputError as error:
            self._log("prompts/get", name, "error", error_code="invalid_prompt_input", request_id=request_id)
            return {"ok": False, "error": {"code": "invalid_prompt_input", "message": error.message}}

    def _call_validated_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        table: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "search": self._connector_search,
            "fetch": self._connector_fetch,
            "knownet_ping": lambda _: self._request("GET", "/api/agent/ping", auth=False),
            "knownet_start_here": lambda _: self._request("GET", "/api/agent/onboarding"),
            "knownet_me": lambda _: self._request("GET", "/api/agent/me"),
            "knownet_state_summary": lambda _: self._request("GET", "/api/agent/state-summary"),
            "knownet_ai_state": lambda a: self._request("GET", "/api/agent/ai-state", query={"limit": a["limit"], "offset": a["offset"]}),
            "knownet_list_pages": lambda a: self._request("GET", "/api/agent/pages", query={"limit": a["limit"], "offset": a["offset"]}),
            "knownet_read_page": lambda a: self._request("GET", f"/api/agent/pages/{urllib.parse.quote(a['page_id'])}"),
            "knownet_list_reviews": lambda a: self._request("GET", "/api/agent/reviews", query={"limit": a["limit"], "offset": a["offset"]}),
            "knownet_list_findings": lambda a: self._request("GET", "/api/agent/findings", query={"limit": a["limit"], "offset": a["offset"], "status": a.get("status")}),
            "knownet_graph_summary": lambda a: self._request("GET", "/api/agent/graph", query={"limit": a["limit"]}),
            "knownet_list_citations": lambda a: self._request("GET", "/api/agent/citations", query={"limit": a["limit"], "offset": a["offset"], "status": a.get("status")}),
            "knownet_review_dry_run": lambda a: self._review(a, dry_run=True),
            "knownet_submit_review": lambda a: self._review(a, dry_run=False),
        }
        return table[name](args)

    def _connector_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args["query"]).strip().lower()
        onboarding = self._request("GET", "/api/agent/onboarding")
        summary = self._request("GET", "/api/agent/state-summary")
        pages = self._request("GET", "/api/agent/pages", query={"limit": 30, "offset": 0})
        results: list[dict[str, Any]] = [
            {
                "id": "agent:onboarding",
                "title": "KnowNet Agent Onboarding",
                "url": "knownet://agent/onboarding",
                "text": "Start here for external AI agents: workflow contract, allowed actions, forbidden actions, and review format.",
            },
            {
                "id": "agent:state-summary",
                "title": "KnowNet State Summary",
                "url": "knownet://agent/state-summary",
                "text": json.dumps(summary.get("data", {}), ensure_ascii=False)[:900],
            },
        ]
        for page in pages.get("data", {}).get("pages", []):
            haystack = f"{page.get('title', '')} {page.get('slug', '')}".lower()
            if query in haystack or any(part and part in haystack for part in query.split()):
                results.append(
                    {
                        "id": f"page:{page['id']}",
                        "title": page.get("title") or page.get("slug") or page["id"],
                        "url": f"knownet://agent/pages/{page['id']}",
                        "text": f"Page slug={page.get('slug')} updated_at={page.get('updated_at')}",
                    }
                )
        if not results[2:]:
            for item in onboarding.get("data", {}).get("recommended_start_pages", [])[:5]:
                if item.get("page_id"):
                    results.append(
                        {
                            "id": f"page:{item['page_id']}",
                            "title": item.get("title") or item["slug"],
                            "url": f"knownet://agent/pages/{item['page_id']}",
                            "text": item.get("reason") or "Recommended start page for external AI agents.",
                        }
                    )
        return {"ok": True, "data": {"results": results[:10]}}

    def _connector_fetch(self, args: dict[str, Any]) -> dict[str, Any]:
        item_id = str(args["id"]).strip()
        if item_id == "agent:onboarding":
            payload = self._request("GET", "/api/agent/onboarding")
            data = payload.get("data", {})
            return {"ok": True, "data": {"id": item_id, "title": "KnowNet Agent Onboarding", "payload": data, "text": json.dumps(data, ensure_ascii=False)}}
        if item_id == "agent:state-summary":
            payload = self._request("GET", "/api/agent/state-summary")
            data = payload.get("data", {})
            return {"ok": True, "data": {"id": item_id, "title": "KnowNet State Summary", "payload": data, "text": json.dumps(data, ensure_ascii=False)}}
        if item_id == "agent:ai-state":
            payload = self._request("GET", "/api/agent/ai-state", query={"limit": 20, "offset": 0})
            data = payload.get("data", {})
            return {"ok": True, "data": {"id": item_id, "title": "KnowNet Structured AI State", "payload": data, "text": json.dumps(data, ensure_ascii=False)}}
        if item_id.startswith("page:"):
            page_id = item_id.removeprefix("page:")
            payload = self._request("GET", f"/api/agent/pages/{urllib.parse.quote(page_id)}")
            page = payload.get("data", {}).get("page", {})
            return {"ok": True, "data": {"id": item_id, "title": page.get("title") or page_id, "text": page.get("content", ""), "url": f"knownet://agent/pages/{page_id}"}}
        raise McpInputError(f"Unknown fetch id: {item_id}")

    def _read_resource(self, uri: str) -> dict[str, Any]:
        if uri == "knownet://agent/onboarding":
            return self._request("GET", "/api/agent/onboarding")
        if uri == "knownet://agent/me":
            return self._request("GET", "/api/agent/me")
        if uri == "knownet://agent/state-summary":
            return self._request("GET", "/api/agent/state-summary")
        if uri == "knownet://agent/ai-state":
            return self._with_next_offset(self._request("GET", "/api/agent/ai-state", query={"limit": 20, "offset": 0}), {"offset": 0})
        if uri == "knownet://agent/pages":
            return self._with_next_offset(self._request("GET", "/api/agent/pages", query={"limit": 20, "offset": 0}), {"offset": 0})
        if uri.startswith("knownet://agent/pages/"):
            page_id = uri.removeprefix("knownet://agent/pages/")
            if not page_id:
                raise McpInputError("page_id is required.")
            return self._request("GET", f"/api/agent/pages/{urllib.parse.quote(page_id)}")
        if uri == "knownet://agent/reviews":
            return self._with_next_offset(self._request("GET", "/api/agent/reviews", query={"limit": 50, "offset": 0}), {"offset": 0})
        if uri == "knownet://agent/findings":
            return self._with_next_offset(self._request("GET", "/api/agent/findings", query={"limit": 100, "offset": 0}), {"offset": 0})
        if uri == "knownet://agent/graph":
            return self._request("GET", "/api/agent/graph", query={"limit": 200})
        if uri == "knownet://agent/citations":
            return self._with_next_offset(self._request("GET", "/api/agent/citations", query={"limit": 100, "offset": 0}), {"offset": 0})
        raise McpInputError(f"Unknown resource: {uri}")

    def _review(self, args: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        payload = {"markdown": args["markdown"]}
        if args.get("source_agent"):
            payload["source_agent"] = args["source_agent"]
        if args.get("source_model"):
            payload["source_model"] = args["source_model"]
        path = "/api/collaboration/reviews?dry_run=true" if dry_run else "/api/collaboration/reviews"
        return self._request("POST", path, payload=payload)

    def _request(self, method: str, path: str, *, query: dict[str, Any] | None = None, payload: dict[str, Any] | None = None, auth: bool = True, timeout: float | None = None) -> dict[str, Any]:
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
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                self._apply_response_headers(result, response.headers)
                if path == "/api/agent/me" and isinstance(result.get("data"), dict):
                    self.current_scopes = list(result["data"].get("scopes") or [])
                return result
        except urllib.error.HTTPError as error:
            try:
                payload_data = json.loads(error.read().decode("utf-8"))
            except Exception:
                payload_data = {"detail": {"message": str(error)}}
            raise KnowNetHttpError(error.code, payload_data) from error

    def _validate_args(self, name: str, args: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(args, dict):
            raise McpInputError(f"{name} arguments must be an object.")
        properties = schema.get("properties", {})
        unknown = sorted(set(args) - set(properties))
        if unknown:
            raise McpInputError(f"Unknown argument: {unknown[0]}")
        for required in schema.get("required", []):
            if required not in args:
                raise McpInputError(f"{required} is required.")
        validated: dict[str, Any] = {}
        for key, spec in properties.items():
            if key not in args:
                if "default" in spec:
                    validated[key] = spec["default"]
                continue
            value = args[key]
            expected = spec.get("type")
            if expected == "integer":
                if not isinstance(value, int) or isinstance(value, bool):
                    raise McpInputError(f"{key} must be an integer.")
                if "minimum" in spec and value < spec["minimum"]:
                    raise McpInputError(f"{key} must be >= {spec['minimum']}.")
                if "maximum" in spec and value > spec["maximum"]:
                    raise McpInputError(f"{key} must be <= {spec['maximum']}.")
            elif expected == "string":
                if not isinstance(value, str):
                    raise McpInputError(f"{key} must be a string.")
                if "minLength" in spec and len(value.strip()) < spec["minLength"]:
                    raise McpInputError(f"{key} is too short.")
                if "maxLength" in spec and len(value) > spec["maxLength"]:
                    raise McpInputError(f"{key} is too long.")
                if "enum" in spec and value not in spec["enum"]:
                    raise McpInputError(f"{key} has an invalid value.")
            if "enum" in spec and value not in spec["enum"]:
                raise McpInputError(f"{key} has an invalid value.")
            validated[key] = value
        return validated

    def _with_next_offset(self, result: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        meta = result.get("meta")
        if not isinstance(meta, dict):
            return result
        offset = args.get("offset", 0)
        returned = int(meta.get("returned_count") or 0)
        total = int(meta.get("total_count") or returned)
        if meta.get("truncated") or total > offset + returned:
            meta["next_offset"] = offset + returned
        return result

    def _map_error(self, status: int, payload: dict[str, Any]) -> dict[str, Any]:
        detail = payload.get("detail") or payload.get("error") or {}
        details = detail.get("details") or {}
        if status == 401:
            return {"code": "auth_failed", "message": "KnowNet agent token is missing or invalid."}
        if status == 403:
            return {
                "code": "scope_denied",
                "message": "KnowNet agent token lacks the required scope.",
                "missing_scope": details.get("scope"),
                "required_scope": details.get("scope"),
                "current_scopes": self.current_scopes,
            }
        if status == 413:
            return {"code": "context_too_large", "message": "Requested context is too large. Use a narrower page or context selection."}
        if status == 429:
            return {"code": "rate_limited", "message": "KnowNet rate limit reached.", "retry_after_seconds": details.get("retry_after_seconds")}
        return {"code": detail.get("code", "knownet_error"), "message": detail.get("message", "KnowNet request failed.")}

    def _prompt_text(self, name: str, args: dict[str, Any]) -> str:
        safety = (
            "Use only scoped KnowNet MCP tools and resources. Do not request database files, local paths, "
            "operator-only controls, raw tokens, sessions, users, backup archives, or secret-bearing data. Use bounded "
            "list/read calls. Start with knownet_start_here. Run knownet_review_dry_run before knownet_submit_review."
        )
        if name == "knownet_review_page":
            return (
                f"{safety}\n\nReview page_id={args['page_id']}. Read that page through knownet_read_page, then produce findings in this exact format:\n\n"
                + FINDING_FORMAT
            )
        if name == "knownet_review_findings":
            status = args.get("status") or "any"
            return (
                f"{safety}\n\nReview existing findings with status={status}. Suggest accept, reject, defer, or needs_more_context decisions. "
                "Ground every decision in scoped evidence returned by KnowNet."
            )
        max_pages = args.get("max_pages", 5)
        focus = args.get("focus") or "overall implementation quality"
        return (
            f"{safety}\n\nPrepare an external review focused on {focus}. Start with knownet_start_here, knownet_me, and knownet_state_summary, "
            f"then inspect at most {max_pages} pages via bounded list/read calls. Draft findings in this format and dry-run them before final submission:\n\n"
            + FINDING_FORMAT
        )

    def handle_jsonrpc(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self._jsonrpc_error(None if not isinstance(message, dict) else message.get("id"), -32600, "Invalid Request")
        method = message["method"]
        request_id = message.get("id")
        trace_id = f"req_{uuid4().hex[:12]}"
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": "knownet", "version": SERVER_VERSION},
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "diagnostics": self.startup_diagnostics(),
                },
            }
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tool_specs()}}
        if method == "tools/call":
            params = message.get("params")
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return self._jsonrpc_error(request_id, -32602, "Invalid params")
            result = self.call_tool(params["name"], params.get("arguments") or {}, request_id=trace_id)
            return self._tool_response(request_id, result)
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": self.resource_specs()}}
        if method == "resources/read":
            params = message.get("params")
            if not isinstance(params, dict) or not isinstance(params.get("uri"), str):
                return self._jsonrpc_error(request_id, -32602, "Invalid params")
            result = self.read_resource(params["uri"], request_id=trace_id)
            return self._resource_response(request_id, params["uri"], result)
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": self.prompt_specs()}}
        if method == "prompts/get":
            params = message.get("params")
            if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                return self._jsonrpc_error(request_id, -32602, "Invalid params")
            result = self.get_prompt(params["name"], params.get("arguments") or {}, request_id=trace_id)
            if not result.get("ok"):
                return self._jsonrpc_error(request_id, -32602, result["error"]["message"])
            return {"jsonrpc": "2.0", "id": request_id, "result": {"description": result["description"], "messages": result["messages"]}}
        return self._jsonrpc_error(request_id, -32601, f"Unknown method: {method}")

    def _tool_response(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "isError": not result.get("ok", False),
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            },
        }

    def _resource_response(self, request_id: Any, uri: str, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "contents": [{
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(result, ensure_ascii=False),
                }]
            },
        }

    def _jsonrpc_error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def _duration(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _apply_response_headers(self, result: dict[str, Any], headers: Any) -> None:
        expires = headers.get("X-Token-Expires-In") if hasattr(headers, "get") else None
        if not expires:
            return
        try:
            seconds = int(expires)
        except ValueError:
            return
        meta = result.setdefault("meta", {})
        if isinstance(meta, dict):
            meta["token_expires_in_seconds"] = seconds
            if seconds <= 7 * 24 * 60 * 60:
                meta["token_warning"] = "expires_soon"

    def _annotate_result(self, result: dict[str, Any], *, request_id: str | None) -> None:
        meta = result.setdefault("meta", {})
        if not isinstance(meta, dict):
            return
        if request_id:
            meta["request_id"] = request_id
        text = json.dumps(result.get("data", {}), ensure_ascii=False)
        meta["chars_returned"] = len(text)
        meta.setdefault("truncated", False)
        if meta.get("content_truncated"):
            meta["warning"] = "page_truncated_use_narrower_reads"
        elif meta.get("truncated"):
            meta["warning"] = "result_paginated_use_next_offset"
        elif len(text) > 50000:
            meta["warning"] = "large_result_use_pagination"
        if meta.get("warning"):
            result.setdefault("warning", meta["warning"])

    def _log(self, method: str, name: str, status: str, *, duration_ms: int | None = None, error_code: str | None = None, request_id: str | None = None, active_requests: int | None = None) -> None:
        if self.log_level == "off":
            return
        event = {
            "request_id": request_id,
            "method": method,
            "name": self._redact(name),
            "status": status,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "active_requests": active_requests,
        }
        if self.log_format == "text":
            line = " ".join(f"{key}={value}" for key, value in event.items() if value is not None)
        else:
            line = json.dumps({key: value for key, value in event.items() if value is not None}, ensure_ascii=True)
        print(line, file=self.log_stream, flush=True)

    def _redact(self, value: str) -> str:
        if "kn_agent_" in value:
            return value.replace("kn_agent_", "kn_agent_[redacted]")
        return value


def main() -> None:
    server = KnowNetMcpServer()
    signal.signal(signal.SIGTERM, server.request_shutdown)
    signal.signal(signal.SIGINT, server.request_shutdown)
    for line in sys.stdin:
        if server.shutdown_requested:
            break
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
    deadline = time.time() + 10
    while server.active_requests > 0 and time.time() < deadline:
        time.sleep(0.05)
    sys.stderr.flush()


if __name__ == "__main__":
    main()
