from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from knownet_mcp_post_client import DEFAULT_URL, post_json_rpc


DEFAULT_OUTPUT = Path("data/tmp/qwen-review-pack.md")


def _tool_call(url: str, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return post_json_rpc(url, "tools/call", {"name": name, "arguments": arguments or {}})


def _decode_tool_payload(response: dict[str, Any]) -> Any:
    content = response.get("result", {}).get("content", [])
    if not content or not isinstance(content, list):
        return response
    text = content[0].get("text") if isinstance(content[0], dict) else None
    if not isinstance(text, str):
        return response
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _section(title: str, value: Any) -> str:
    return f"## {title}\n\n```json\n{_dump_json(value)}\n```\n"


def build_pack(url: str, *, ai_state_limit: int) -> str:
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    initialize = post_json_rpc(
        url,
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "knownet-qwen-review-pack", "version": "1.0.0"},
        },
    )
    calls = {
        "knownet_start_here": _decode_tool_payload(_tool_call(url, "knownet_start_here")),
        "knownet_me": _decode_tool_payload(_tool_call(url, "knownet_me")),
        "knownet_state_summary": _decode_tool_payload(_tool_call(url, "knownet_state_summary")),
        "tools_list": post_json_rpc(url, "tools/list", {}),
        "knownet_ai_state": _decode_tool_payload(_tool_call(url, "knownet_ai_state", {"limit": ai_state_limit})),
    }

    prompt = """You are reviewing KnowNet as a first-time external AI contributor.

Use the JSON data below as the source of truth. Do not assume access to local files,
raw database files, raw tokens, or private environment variables.

Review focus:
1. Can a new external AI understand the current project state?
2. Are security boundaries clear?
3. Are token expiry, pagination, and release blockers actionable?
4. Are the ai_state summaries useful enough without leaking local paths or secrets?
5. What should the operator fix next?

Return findings in this exact format:

### Finding
Title:
Severity: critical | high | medium | low | info
Area: API | UI | Rust | Security | Data | Ops | Docs
Evidence:
Proposed change:
"""

    parts = [
        "# KnowNet Qwen Review Pack",
        "",
        f"generated_at: {generated_at}",
        f"mcp_url: {url}",
        f"ai_state_limit: {ai_state_limit}",
        "",
        "## Prompt For Qwen",
        "",
        "```txt",
        prompt.strip(),
        "```",
        "",
        _section("Initialize Result", initialize),
    ]
    for title, value in calls.items():
        parts.append(_section(title, value))
    return "\n".join(parts).rstrip() + "\n"


def _copy_to_clipboard(text: str) -> None:
    if os.name != "nt":
        raise SystemExit("--copy is only supported on Windows in this helper")
    process = subprocess.run("clip", input=text, text=True, shell=True, check=False)
    if process.returncode != 0:
        raise SystemExit("Failed to copy review pack to clipboard")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create one paste-ready review pack for Qwen free web from live KnowNet MCP calls.",
    )
    parser.add_argument("--url", default=os.getenv("KNOWNET_MCP_URL", DEFAULT_URL), help="KnowNet MCP HTTP URL.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Markdown output path.")
    parser.add_argument("--ai-state-limit", type=int, default=10, help="Number of ai_state rows to include.")
    parser.add_argument("--copy", action="store_true", help="Copy the generated Markdown to the Windows clipboard.")
    args = parser.parse_args()

    text = build_pack(args.url, ai_state_limit=max(1, min(args.ai_state_limit, 50)))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    if args.copy:
        _copy_to_clipboard(text)
    print(f"Wrote Qwen review pack: {output}")
    if args.copy:
        print("Copied Qwen review pack to clipboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
