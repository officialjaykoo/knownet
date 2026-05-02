import json
import urllib.error
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
