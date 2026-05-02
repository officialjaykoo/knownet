from __future__ import annotations

from knownet_review_pack import write_pack
from knownet_mcp_post_client import DEFAULT_URL

import argparse
import os


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create one paste-ready review pack for Kimi web from live KnowNet MCP calls.",
    )
    parser.add_argument("--url", default=os.getenv("KNOWNET_MCP_URL", DEFAULT_URL), help="KnowNet MCP HTTP URL.")
    parser.add_argument("--output", help="Markdown output path.")
    parser.add_argument("--ai-state-limit", type=int, default=10, help="Number of ai_state rows to include.")
    parser.add_argument("--copy", action="store_true", help="Copy the generated Markdown to the Windows clipboard.")
    args = parser.parse_args()

    path = write_pack("kimi", args.url, args.output, args.ai_state_limit, args.copy)
    print(f"Wrote Kimi review pack: {path}")
    if args.copy:
        print("Copied Kimi review pack to clipboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
