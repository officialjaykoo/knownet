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

from knownet_mcp.http_bridge import McpHttpHandler
from knownet_mcp.server import ALLOWED_PROMPTS, ALLOWED_RESOURCES, ALLOWED_TOOLS, KnowNetMcpServer


def test_standard_tool_registry_only_exposes_proposal_tools():
    server = KnowNetMcpServer(token="kn_agent_test")
    names = {tool["name"] for tool in server.tool_specs()}
    assert names == ALLOWED_TOOLS
    assert names == {
        "knownet.propose_finding",
        "knownet.propose_task",
        "knownet.submit_implementation_evidence",
    }
    assert all("maintenance" not in name for name in names)


def test_standard_resources_and_prompts_only():
    server = KnowNetMcpServer(token="kn_agent_test")
    resource_uris = {item["uri"] for item in server.resource_specs()}
    prompt_names = {item["name"] for item in server.prompt_specs()}
    assert resource_uris == ALLOWED_RESOURCES
    assert resource_uris == {
        "knownet://snapshot/overview",
        "knownet://snapshot/stability",
        "knownet://snapshot/performance",
        "knownet://snapshot/security",
        "knownet://snapshot/implementation",
        "knownet://snapshot/provider_review",
        "knownet://node/{slug_or_page_id}",
        "knownet://finding/recent",
    }
    assert prompt_names == ALLOWED_PROMPTS
    assert prompt_names == {
        "knownet.compact_review",
        "knownet.implementation_candidate",
        "knownet.provider_risk_check",
    }


def test_removed_mcp_names_are_not_callable_or_readable():
    server = KnowNetMcpServer(token="kn_agent_test")
    assert server.call_tool("search", {"query": "KnowNet"})["error"]["code"] == "unknown_tool"
    assert server.call_tool("knownet_state_summary")["error"]["code"] == "unknown_tool"
    assert server.get_prompt("knownet_prepare_external_review")["error"]["code"] == "unknown_prompt"
    assert server.read_resource("knownet://agent/state-summary")["error"]["code"] == "invalid_resource"


def test_standard_mcp_resources_read_snapshot_node_and_recent_findings():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")

    def fake_request(method, path, **kwargs):
        if path == "/api/agent/state-summary":
            return {"ok": True, "data": {"health": {"status": "ok"}}, "meta": {"source": "summary"}}
        if path == "/api/agent/pages":
            return {
                "ok": True,
                "data": {"pages": [{"id": "page_start", "slug": "start-here", "title": "Start Here"}]},
                "meta": {},
            }
        if path == "/api/agent/pages/page_start":
            return {"ok": True, "data": {"page": {"id": "page_start", "title": "Start Here"}}}
        if path == "/api/agent/findings":
            assert kwargs["query"] == {"limit": 50, "offset": 0}
            return {"ok": True, "data": {"findings": []}, "meta": {"returned_count": 0, "total_count": 0}}
        raise AssertionError((method, path, kwargs))

    with patch.object(server, "_request", side_effect=fake_request):
        snapshot = server.read_resource("knownet://snapshot/overview")
        node = server.read_resource("knownet://node/start-here")
        findings = server.read_resource("knownet://finding/recent")

    assert snapshot["data"]["type"] == "snapshot_resource"
    assert snapshot["data"]["profile"] == "overview"
    assert snapshot["data"]["state_summary"]["health"]["status"] == "ok"
    assert node["data"]["page"]["id"] == "page_start"
    assert findings["ok"] is True


def test_standard_mcp_proposal_tools_are_operator_gated():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")

    with patch.object(server, "_request", return_value={"ok": True, "data": {"findings": []}, "meta": {}}) as mocked:
        finding = server.call_tool(
            "knownet.propose_finding",
            {
                "title": "Provider retry is missing",
                "severity": "medium",
                "area": "Ops",
                "evidence": "One provider run failed without retry metadata.",
                "proposed_change": "Add bounded retry logging.",
                "evidence_quality": "context_limited",
            },
        )

    assert finding["ok"] is True
    assert finding["proposal"]["operator_gated"] is True
    mocked.assert_called_once()
    method, path = mocked.call_args.args
    assert method == "POST"
    assert path == "/api/collaboration/reviews?dry_run=true"

    with patch.object(server, "_request") as mocked:
        task = server.call_tool("knownet.propose_task", {"finding_id": "finding_1", "title": "Add retry logs"})
        evidence = server.call_tool(
            "knownet.submit_implementation_evidence",
            {"finding_id": "finding_1", "implemented": True, "commit": "abc123", "note": "Added retry logs."},
        )

    assert mocked.call_count == 0
    assert task["data"]["operator_gated"] is True
    assert task["data"]["type"] == "task_proposal"
    assert evidence["data"]["operator_gated"] is True
    assert evidence["data"]["type"] == "implementation_evidence_proposal"


def test_standard_mcp_prompts_use_standard_resources_and_tools():
    server = KnowNetMcpServer(token="kn_agent_test")
    compact = server.get_prompt("knownet.compact_review", {"focus": "stability"})
    text = compact["messages"][0]["content"]["text"]
    assert "knownet://snapshot/overview" in text
    assert "knownet://finding/recent" in text
    assert "knownet.propose_finding" in text
    assert "release_check" in text

    implementation = server.get_prompt("knownet.implementation_candidate", {"finding_id": "finding_1"})
    assert "knownet.propose_task" in implementation["messages"][0]["content"]["text"]
    provider = server.get_prompt("knownet.provider_risk_check", {"provider": "glm"})
    assert "knownet://snapshot/provider_review" in provider["messages"][0]["content"]["text"]


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


def test_jsonrpc_lists_standard_surface():
    server = KnowNetMcpServer(token="kn_agent_test")
    tools = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    resources = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "resources/list"})
    prompts = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "prompts/list"})
    assert {item["name"] for item in tools["result"]["tools"]} == ALLOWED_TOOLS
    assert {item["uri"] for item in resources["result"]["resources"]} == ALLOWED_RESOURCES
    assert {item["name"] for item in prompts["result"]["prompts"]} == ALLOWED_PROMPTS


def test_tool_schemas_are_strict_and_validated_before_http_call():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")
    for spec in server.tool_specs():
        schema = spec["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
    with patch.object(server, "_request") as mocked:
        unknown = server.call_tool("knownet.propose_task", {"finding_id": "finding_1", "title": "Task", "extra": True})
        bad_enum = server.call_tool(
            "knownet.propose_finding",
            {
                "title": "T",
                "severity": "severe",
                "area": "Ops",
                "evidence": "E",
                "proposed_change": "P",
                "evidence_quality": "context_limited",
            },
        )
        bad_bool = server.call_tool(
            "knownet.submit_implementation_evidence",
            {"finding_id": "finding_1", "implemented": "yes", "note": "done"},
        )
    assert mocked.call_count == 0
    assert unknown["error"]["code"] == "invalid_tool_input"
    assert bad_enum["error"]["code"] == "invalid_tool_input"
    assert bad_bool["error"]["code"] == "invalid_tool_input"


def test_http_bridge_rejects_get_discovery():
    httpd = HTTPServer(("127.0.0.1", 0), McpHttpHandler)
    httpd.knownet_mcp = KnowNetMcpServer(token="kn_agent_test")  # type: ignore[attr-defined]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_port}"
        health = urllib.request.urlopen(base + "/health", timeout=2)
        assert health.status == 200
        for path in ("/mcp", "/mcp/tools", "/.well-known/mcp"):
            try:
                urllib.request.urlopen(base + path, timeout=2)
            except urllib.error.HTTPError as exc:
                assert exc.code == 405
                payload = json.loads(exc.read().decode("utf-8"))
                assert payload["error"] == "method_not_allowed"
            else:
                raise AssertionError(f"GET {path} should not expose discovery metadata")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_metadata_request_id_token_warning_and_size_warning():
    server = KnowNetMcpServer(token="kn_agent_test")
    response = {"ok": True, "data": {"page": {"content": "x" * 10}}, "meta": {"content_truncated": True}}
    server._apply_response_headers(response, {"X-Token-Expires-In": str(60 * 60)})
    server._annotate_result(response, request_id="req_test")
    assert response["meta"]["request_id"] == "req_test"
    assert response["meta"]["token_warning"] == "expires_soon"
    assert response["meta"]["warning"] == "page_truncated_use_narrower_reads"


def test_structured_logs_go_to_stderr_stream_and_redact_tokens():
    stream = StringIO()
    server = KnowNetMcpServer(token="kn_agent_secret", log_stream=stream)
    server._log("tools/call", "kn_agent_secret", "ok", duration_ms=1)
    output = stream.getvalue()
    assert "kn_agent_secret" not in output
    assert "kn_agent_[redacted]secret" in output


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
            self.wfile.write(json.dumps({"ok": True, "data": {"health": {"status": "ok"}}, "meta": {}}).encode("utf-8"))

        def log_message(self, *_):
            return

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        server = KnowNetMcpServer(base_url=f"http://127.0.0.1:{httpd.server_port}", token="kn_agent_test")
        response = server.read_resource("knownet://snapshot/overview")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)

    assert response["ok"] is True
    assert seen["path"] == "/api/agent/state-summary"
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
                "purpose": "phase23",
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
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "resources/list"}),
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "knownet://snapshot/overview"}}),
            server.handle_jsonrpc({"jsonrpc": "2.0", "id": 5, "method": "prompts/list"}),
            server.handle_jsonrpc({
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "knownet.propose_finding",
                    "arguments": {
                        "title": "E2E finding",
                        "severity": "info",
                        "area": "Docs",
                        "evidence": "E2E.",
                        "proposed_change": "None.",
                        "evidence_quality": "direct_access",
                    },
                },
            }),
        ]
    finally:
        api_server.should_exit = True
        thread.join(timeout=5)
        get_settings.cache_clear()

    text = json.dumps(responses)
    assert all(response and response["jsonrpc"] == "2.0" for response in responses)
    assert "knownet_state_summary" not in text
    assert "token" + "_hash" not in text
    assert token not in text
