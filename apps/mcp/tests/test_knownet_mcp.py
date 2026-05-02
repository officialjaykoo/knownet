import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from knownet_mcp.server import ALLOWED_TOOLS, KnowNetMcpServer


def test_tool_registry_is_fixed_and_excludes_maintenance():
    server = KnowNetMcpServer(token="kn_agent_test")
    names = {tool["name"] for tool in server.tool_specs()}
    assert names == ALLOWED_TOOLS
    assert all("maintenance" not in name for name in names)


def test_read_page_calls_agent_endpoint():
    server = KnowNetMcpServer(base_url="http://knownet", token="kn_agent_test")
    with patch.object(server, "_request", return_value={"ok": True}) as mocked:
        assert server.call_tool("knownet_read_page", {"page_id": "page_1"}) == {"ok": True}
    mocked.assert_called_once_with("GET", "/api/agent/pages/page_1")


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


def test_jsonrpc_invalid_tool_input_returns_tool_error():
    server = KnowNetMcpServer(token="kn_agent_test")
    response = server.handle_jsonrpc({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "knownet_review_dry_run", "arguments": {}}})
    assert response["result"]["isError"] is True
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["error"]["code"] == "invalid_tool_input"


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
