from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any


DEFAULT_URL = "http://127.0.0.1:8010/mcp"


def _json_object(text: str | None, *, label: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise SystemExit(f"{label} must be valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return value


def post_json_rpc(url: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Request failed: {error}") from error
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise SystemExit(f"Response was not JSON: {body[:500]}") from error


def tool_call(url: str, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return post_json_rpc(url, "tools/call", {"name": name, "arguments": arguments or {}})


def preset_to_request(preset: str) -> tuple[str, dict[str, Any]]:
    if preset == "initialize":
        return (
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "knownet-local-mcp-client", "version": "1.0.0"},
            },
        )
    if preset == "tools":
        return ("tools/list", {})
    if preset == "resources":
        return ("resources/list", {})
    if preset == "start-here":
        return ("resources/read", {"uri": "knownet://snapshot/overview"})
    if preset == "compact-review":
        return ("prompts/get", {"name": "knownet.compact_review", "arguments": {"focus": "overview"}})
    if preset == "recent-findings":
        return ("resources/read", {"uri": "knownet://finding/recent"})
    raise SystemExit(f"Unknown preset: {preset}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Small JSON-RPC POST client for testing KnowNet MCP from a local PC.",
    )
    parser.add_argument("--url", default=os.getenv("KNOWNET_MCP_URL", DEFAULT_URL), help="KnowNet MCP HTTP URL.")
    parser.add_argument(
        "--preset",
        choices=["initialize", "tools", "resources", "start-here", "compact-review", "recent-findings"],
        help="Run a common KnowNet MCP call.",
    )
    parser.add_argument("--method", help="Raw JSON-RPC method, for example tools/list or tools/call.")
    parser.add_argument("--params-json", help="Raw JSON-RPC params object.")
    parser.add_argument("--tool", help="Tool name for tools/call, for example knownet.propose_finding.")
    parser.add_argument("--args-json", help="Tool arguments object for --tool.")
    args = parser.parse_args()

    if args.tool:
        result = tool_call(args.url, args.tool, _json_object(args.args_json, label="--args-json"))
    else:
        if args.preset:
            method, params = preset_to_request(args.preset)
        elif args.method:
            method, params = args.method, _json_object(args.params_json, label="--params-json")
        else:
            method, params = preset_to_request("start-here")
        result = post_json_rpc(args.url, method, params)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
