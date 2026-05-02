import json
import socket
import sys
import time
from io import StringIO
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from knownet_mcp.http_bridge import capability_payload
from knownet_mcp.server import ALLOWED_TOOLS, KnowNetMcpServer


def test_tool_registry_is_fixed_and_excludes_maintenance():
    server = KnowNetMcpServer(token="kn_agent_test")
    names = {tool["name"] for tool in server.tool_specs()}
    assert names == ALLOWED_TOOLS
    assert {"search", "fetch"}.issubset(names)
    assert all("maintenance" not in name for name in names)


def test_read_page_calls_agent_endpoint():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")
    with patch.object(server, "_request", return_value={"ok": True}) as mocked:
        assert server.call_tool("knownet_read_page", {"page_id": "page_1"})["ok"] is True
    mocked.assert_called_once_with("GET", "/api/agent/pages/page_1")


def test_start_here_calls_onboarding_endpoint():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")
    with patch.object(server, "_request", return_value={"ok": True}) as mocked:
        assert server.call_tool("knownet_start_here")["ok"] is True
    mocked.assert_called_once_with("GET", "/api/agent/onboarding")


def test_connector_search_and_fetch_aliases():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")

    def fake_request(method, path, **kwargs):
        if path == "/api/agent/onboarding":
            return {"ok": True, "data": {"recommended_start_pages": [{"page_id": "page_start", "title": "Start", "slug": "start", "reason": "Begin here."}]}}
        if path == "/api/agent/state-summary":
            return {"ok": True, "data": {"first_agent_brief": {"current_phase": 14}}}
        if path == "/api/agent/pages":
            return {"ok": True, "data": {"pages": [{"id": "page_start", "title": "Start", "slug": "start", "updated_at": "now"}]}, "meta": {}}
        if path == "/api/agent/pages/page_start":
            return {"ok": True, "data": {"page": {"title": "Start", "content": "Page content"}}}
        raise AssertionError((method, path, kwargs))

    with patch.object(server, "_request", side_effect=fake_request):
        search = server.call_tool("search", {"query": "start"})
        fetch = server.call_tool("fetch", {"id": "page:page_start"})
    assert search["ok"] is True
    assert search["data"]["results"][0]["id"] == "agent:onboarding"
    assert fetch["ok"] is True
    assert fetch["data"]["text"] == "Page content"


def test_connector_fetch_resource_includes_payload_and_text():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")
    with patch.object(server, "_request", return_value={"ok": True, "data": {"summary": {"pages": 1}}}):
        fetch = server.call_tool("fetch", {"id": "agent:state-summary"})
    assert fetch["ok"] is True
    assert fetch["data"]["payload"]["summary"]["pages"] == 1
    assert '"pages": 1' in fetch["data"]["text"]
    assert fetch["meta"]["truncated"] is False


def test_review_dry_run_uses_existing_write_gateway():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")
    with patch.object(server, "_request", return_value={"ok": True}) as mocked:
        server.call_tool("knownet_review_dry_run", {"markdown": "### Finding"})
    mocked.assert_called_once_with("POST", "/api/collaboration/reviews?dry_run=true", payload={"markdown": "### Finding"})


def test_error_mapping():
    server = KnowNetMcpServer(token="kn_agent_test")
    assert server._map_error(401, {"detail": {}})["code"] == "auth_failed"
    assert server._map_error(403, {"detail": {"details": {"scope": "pages:read"}}})["code"] == "scope_denied"
    assert server._map_error(413, {"detail": {}})["code"] == "context_too_large"
    assert server._map_error(429, {"detail": {"details": {"retry_after_seconds": 60}}})["code"] == "rate_limited"


def test_jsonrpc_tools_list():
    server = KnowNetMcpServer(token="kn_agent_test")
    response = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response["id"] == 1
    assert {tool["name"] for tool in response["result"]["tools"]} == ALLOWED_TOOLS


def test_http_discovery_exposes_mcp_client_profiles():
    server = KnowNetMcpServer(token="kn_agent_test")
    payload = capability_payload(server)
    assert payload["transport_profiles"]["local_stdio"]["auth_location"] == "environment variable KNOWNET_AGENT_TOKEN"
    assert payload["transport_profiles"]["streamable_http_bridge"]["endpoint"] == "/mcp"
    assert set(payload["client_profiles"]) == {
        "chatgpt",
        "claude",
        "deepseek",
        "gemini",
        "glm",
        "kimi",
        "manus",
        "minimax",
        "qwen",
    }
    assert payload["client_profiles"]["claude"]["connection_modes"][0]["mode"] == "local_stdio"
    assert payload["client_profiles"]["chatgpt"]["connection_modes"][0]["mode"] == "streamable_http_bridge"
    assert payload["client_profiles"]["manus"]["connection_modes"][0]["mode"] == "protected_https_custom_mcp"
    assert payload["client_profiles"]["deepseek"]["test_status"] == "profile_only_provider_not_implemented"


def test_jsonrpc_strict_errors_and_capabilities():
    server = KnowNetMcpServer(token="kn_agent_test")
    invalid = server.handle_jsonrpc({"id": 1, "method": "tools/list"})
    assert invalid["error"]["code"] == -32600
    unknown = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "missing"})
    assert unknown["error"]["code"] == -32601
    bad_params = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {}})
    assert bad_params["error"]["code"] == -32602
    initialized = server.handle_jsonrpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert initialized is None
    with patch.object(server, "startup_diagnostics", return_value={"ok": True, "checks": []}):
        init = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 4, "method": "initialize"})
    assert set(init["result"]["capabilities"]) == {"tools", "resources", "prompts"}
    assert init["result"]["diagnostics"]["ok"] is True


def test_tool_schemas_are_strict():
    server = KnowNetMcpServer(token="kn_agent_test")
    for spec in server.tool_specs():
        schema = spec["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
    page_schema = next(spec["inputSchema"] for spec in server.tool_specs() if spec["name"] == "knownet_list_pages")
    assert page_schema["properties"]["limit"]["maximum"] == 200


def test_tool_input_validation_happens_before_http_call():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")
    with patch.object(server, "_request") as mocked:
        unknown = server.call_tool("knownet_list_pages", {"limit": 10, "extra": True})
        too_large = server.call_tool("knownet_list_pages", {"limit": 201})
        bad_enum = server.call_tool("knownet_list_findings", {"status": "closed"})
        missing = server.call_tool("knownet_read_page", {})
    assert mocked.call_count == 0
    assert unknown["error"]["code"] == "invalid_tool_input"
    assert too_large["error"]["code"] == "invalid_tool_input"
    assert bad_enum["error"]["code"] == "invalid_tool_input"
    assert missing["error"]["code"] == "invalid_tool_input"


def test_jsonrpc_invalid_tool_input_returns_tool_error():
    server = KnowNetMcpServer(token="kn_agent_test")
    response = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "knownet_review_dry_run", "arguments": {}}})
    assert response["result"]["isError"] is True
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["error"]["code"] == "invalid_tool_input"


def test_resources_and_prompts_jsonrpc():
    server = KnowNetMcpServer(token="kn_agent_test")
    resources = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    assert "knownet://agent/onboarding" in {item["uri"] for item in resources["result"]["resources"]}
    assert "knownet://agent/me" in {item["uri"] for item in resources["result"]["resources"]}

    with patch.object(server, "_request", return_value={"ok": True, "data": {"token_id": "agent_test"}, "meta": {}}):
        read = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": "knownet://agent/me"}})
    payload = json.loads(read["result"]["contents"][0]["text"])
    assert payload["ok"] is True

    prompts = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "prompts/list"})
    assert "knownet_prepare_external_review" in {item["name"] for item in prompts["result"]["prompts"]}
    prompt = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 4, "method": "prompts/get", "params": {"name": "knownet_review_page", "arguments": {"page_id": "page_1"}}})
    text = prompt["result"]["messages"][0]["content"]["text"]
    assert "### Finding" in text
    assert "knownet_start_here" in text
    assert "knownet_review_dry_run" in text
    assert "/api/" + "maintenance" not in text
    assert "kn_agent_" not in text


def test_pagination_metadata_adds_next_offset():
    server = KnowNetMcpServer(token="kn_agent_test")
    result = server._with_next_offset({"ok": True, "meta": {"truncated": True, "total_count": 12, "returned_count": 5}}, {"offset": 5})
    assert result["meta"]["next_offset"] == 10


def test_structured_logs_go_to_stderr_stream_and_redact_tokens():
    stream = StringIO()
    server = KnowNetMcpServer(token="kn_agent_secret", log_stream=stream)
    server._log("tools/call", "kn_agent_secret", "ok", duration_ms=1)
    output = stream.getvalue()
    assert "kn_agent_secret" not in output
    assert "kn_agent_[redacted]secret" in output


def test_mcp_metadata_request_id_token_warning_and_size_warning():
    server = KnowNetMcpServer(token="kn_agent_test")
    response = {"ok": True, "data": {"page": {"content": "x" * 10}}, "meta": {"content_truncated": True}}
    server._apply_response_headers(response, {"X-Token-Expires-In": str(60 * 60)})
    server._annotate_result(response, request_id="req_test")
    assert response["meta"]["request_id"] == "req_test"
    assert response["meta"]["token_warning"] == "expires_soon"
    assert response["meta"]["warning"] == "page_truncated_use_narrower_reads"


def test_mcp_pagination_warning_is_not_page_truncation():
    server = KnowNetMcpServer(token="kn_agent_test")
    response = {"ok": True, "data": {"items": [1]}, "meta": {"truncated": True}}
    server._annotate_result(response, request_id="req_page")
    assert response["meta"]["warning"] == "result_paginated_use_next_offset"


def test_scope_denied_includes_current_scope_hint():
    server = KnowNetMcpServer(token="kn_agent_test")
    server.current_scopes = ["pages:read"]
    error = server._map_error(403, {"detail": {"details": {"scope": "reviews:read"}}})
    assert error["required_scope"] == "reviews:read"
    assert error["current_scopes"] == ["pages:read"]


def test_startup_diagnostics_checks_ping_token_scopes_and_expiry():
    server = KnowNetMcpServer(token="kn_agent_test")

    def fake_request(method, path, **_):
        if path == "/api/agent/ping":
            return {"ok": True, "version": "9.0"}
        if path == "/api/agent/me":
            return {"ok": True, "data": {"token_id": "agent_test", "scopes": ["pages:read"], "expires_in_seconds": 60}}
        raise AssertionError(path)

    with patch.object(server, "_request", side_effect=fake_request):
        diagnostics = server.startup_diagnostics()
    assert diagnostics["ok"] is True
    assert any(check.get("token_warning") == "expires_soon" for check in diagnostics["checks"])


def test_mcp_roundtrip_over_http():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["path"] = self.path
            seen["authorization"] = self.headers.get("Authorization")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "data": {"token_id": "agent_test"}, "meta": {}}).encode("utf-8"))

        def log_message(self, *_):
            return

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        server = KnowNetMcpServer(base_url=f"http://127.0.0.1:{httpd.server_port}", token="kn_agent_test")
        response = server.call_tool("knownet_me")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)

    assert response["ok"] is True
    assert seen["path"] == "/api/agent/me"
    assert seen["authorization"] == "Bearer kn_agent_test"


def test_mcp_end_to_end_against_knownet_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "data" / "state.sqlite"))
    monkeypatch.setenv("PUBLIC_MODE", "false")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.setenv("CLOUDFLARE_ACCESS_REQUIRED", "false")
    sys.path.insert(0, "apps/api")
    import uvicorn
    from knownet_api.config import get_settings
    from knownet_api.main import app

    get_settings.cache_clear()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", ws="none")
    api_server = uvicorn.Server(config)
    thread = threading.Thread(target=api_server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{base_url}/api/agent/ping", timeout=1).read()
                break
            except urllib.error.URLError:
                time.sleep(0.05)
        else:
            raise AssertionError("KnowNet API test server did not start")

        create = urllib.request.Request(
            f"{base_url}/api/agents/tokens",
            data=json.dumps({
                "label": "MCP E2E",
                "agent_name": "mcp-test",
                "purpose": "phase11",
                "role": "agent_reviewer",
                "scopes": ["preset:reader", "preset:reviewer"],
                "expires_at": "2099-01-01T00:00:00Z",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        token = json.loads(urllib.request.urlopen(create, timeout=5).read().decode("utf-8"))["data"]["token"]["raw" + "_token"]
        server = KnowNetMcpServer(base_url=base_url, token=token)

        responses = [
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "knownet_me", "arguments": {}}}),
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "knownet_list_pages", "arguments": {"limit": 5}}}),
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "knownet_review_dry_run", "arguments": {"markdown": "### Finding\n\nSeverity: info\nArea: Docs\n\nEvidence:\nE2E.\n\nProposed change:\nNone."}}}),
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 6, "method": "resources/list"}),
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 7, "method": "resources/read", "params": {"uri": "knownet://agent/me"}}),
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 8, "method": "prompts/list"}),
        ]
    finally:
        api_server.should_exit = True
        thread.join(timeout=5)
        get_settings.cache_clear()

    text = json.dumps(responses)
    assert all(response and response["jsonrpc"] == "2.0" for response in responses)
    assert "token" + "_hash" not in text
    assert token not in text
