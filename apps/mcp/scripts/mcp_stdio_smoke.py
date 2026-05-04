from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _read_json_line(process: subprocess.Popen[str]) -> dict[str, Any]:
    line = process.stdout.readline() if process.stdout else ""
    if not line:
        stderr = process.stderr.read() if process.stderr else ""
        raise RuntimeError(f"MCP server closed stdout before responding. stderr={stderr}")
    return json.loads(line)


def _send(process: subprocess.Popen[str], message: dict[str, Any]) -> dict[str, Any] | None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    if "id" not in message:
        return None
    return _read_json_line(process)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small stdio MCP smoke test against the KnowNet MCP server.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to start the MCP server.")
    parser.add_argument("--server", default=str(Path(__file__).resolve().parents[1] / "knownet_mcp" / "server.py"), help="Path to knownet_mcp/server.py.")
    parser.add_argument("--base-url", default=os.getenv("KNOWNET_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.getenv("KNOWNET_AGENT_TOKEN"))
    args = parser.parse_args()

    env = os.environ.copy()
    env["KNOWNET_BASE_URL"] = args.base_url
    env["KNOWNET_MCP_LOG_FORMAT"] = env.get("KNOWNET_MCP_LOG_FORMAT", "json")
    if args.token:
        env["KNOWNET_AGENT_TOKEN"] = args.token

    process = subprocess.Popen(
        [args.python, args.server],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    try:
        initialize = _send(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        tools = _send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        resources = _send(process, {"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
        prompts = _send(process, {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"})
        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        tool_names = {tool["name"] for tool in tools["result"]["tools"]}
        resource_uris = {resource["uri"] for resource in resources["result"]["resources"]}
        prompt_names = {prompt["name"] for prompt in prompts["result"]["prompts"]}
        required_tools = {
            "knownet.propose_finding",
            "knownet.propose_task",
            "knownet.submit_implementation_evidence",
        }
        required_resources = {
            "knownet://snapshot/overview",
            "knownet://snapshot/stability",
            "knownet://snapshot/performance",
            "knownet://snapshot/security",
            "knownet://snapshot/implementation",
            "knownet://snapshot/provider_review",
            "knownet://node/{slug_or_page_id}",
            "knownet://finding/recent",
        }
        required_prompts = {
            "knownet.compact_review",
            "knownet.implementation_candidate",
            "knownet.provider_risk_check",
        }

        missing = {
            "tools": sorted(required_tools - tool_names),
            "resources": sorted(required_resources - resource_uris),
            "prompts": sorted(required_prompts - prompt_names),
        }
        ok = not any(missing.values())
        report = {
            "ok": ok,
            "server": initialize["result"]["serverInfo"],
            "protocolVersion": initialize["result"]["protocolVersion"],
            "tool_count": len(tool_names),
            "resource_count": len(resource_uris),
            "prompt_count": len(prompt_names),
            "missing": missing,
            "diagnostics": initialize["result"].get("diagnostics"),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if ok else 2
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
