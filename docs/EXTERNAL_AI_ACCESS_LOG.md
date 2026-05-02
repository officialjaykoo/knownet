# External AI Access Log

```json
{
  "schema": "knownet.external_ai_access_log.v1",
  "purpose": "Record external AI reviewer access methods during the Phase 14 MCP and agent onboarding test round.",
  "entries": [
    {
      "reviewer": "claude",
      "environment": "pc_web",
      "access_mode": "cloudflare_quick_tunnel_limited_fetch",
      "live_mcp_post": false,
      "get_discovery": false,
      "get_preview_resources": false,
      "fallback_used": true,
      "result": "Could not call live tools directly; reviewed from provided API response data."
    },
    {
      "reviewer": "chatgpt",
      "environment": "pc_web",
      "access_mode": "pc_web_with_and_without_custom_mcp_connector",
      "live_mcp_post": true,
      "get_discovery": true,
      "get_preview_resources": true,
      "fallback_used": true,
      "attempts": [
        {
          "mode": "custom_mcp_connector_cloudflare_quick_tunnel",
          "live_mcp_post": true,
          "result": "Connector worked; knownet_start_here call succeeded."
        },
        {
          "mode": "no_knownet_connector_in_web_session",
          "live_mcp_post": false,
          "result": "Could not call KnowNet tools directly; used GitHub/document fallback."
        }
      ],
      "result": "One ChatGPT PC web attempt succeeded through the custom MCP connector; another web session lacked the connector and used fallback."
    },
    {
      "reviewer": "gemini",
      "environment": "pc_web",
      "access_mode": "pc_web_gemini_fast_and_pro",
      "live_mcp_post": false,
      "get_discovery": false,
      "get_preview_resources": false,
      "fallback_used": true,
      "attempts": [
        {
          "model": "fast",
          "mode": "cloudflare_quick_tunnel_no_post",
          "result": "Could not perform JSON-RPC POST; used provided documents/static fallback."
        },
        {
          "model": "pro",
          "mode": "cloudflare_quick_tunnel_unavailable",
          "result": "Tunnel was unavailable or closed during attempt; used static fallback with stronger findings."
        }
      ],
      "result": "Gemini fast and Pro were treated as one reviewer family; Pro produced stronger findings but used the same fallback class."
    },
    {
      "reviewer": "manus",
      "environment": "pc_web",
      "access_mode": "supplied_markdown_summary",
      "live_mcp_post": false,
      "get_discovery": false,
      "get_preview_resources": false,
      "fallback_used": true,
      "result": "Reviewed from supplied Markdown summary, not direct MCP tool calls."
    },
    {
      "reviewer": "deepseek",
      "environment": "pc_web",
      "access_mode": "pc_web_multiple_attempts",
      "live_mcp_post": false,
      "get_discovery": true,
      "get_preview_resources": true,
      "fallback_used": true,
      "attempts": [
        {
          "mode": "public_search_then_mcp_discovery",
          "get_discovery": true,
          "get_preview_resources": false,
          "fallback_used": true,
          "result": "First attempt confused public search results with KnowNet; later corrected toward MCP discovery."
        },
        {
          "mode": "mcp_get_discovery_only",
          "get_discovery": true,
          "get_preview_resources": false,
          "fallback_used": false,
          "result": "Read discovery JSON; could not perform JSON-RPC POST tool calls."
        },
        {
          "mode": "mcp_get_preview_resources",
          "get_discovery": true,
          "get_preview_resources": true,
          "fallback_used": false,
          "result": "Read safe preview resources; no POST tool calls."
        }
      ],
      "result": "DeepSeek made multiple PC web attempts; the final useful path was GET discovery plus GET preview resources."
    },
    {
      "reviewer": "qwen_3_6_plus",
      "environment": "pc_web",
      "access_mode": "mcp_get_discovery_and_preview_resources",
      "live_mcp_post": false,
      "get_discovery": true,
      "get_preview_resources": true,
      "fallback_used": false,
      "result": "Reviewed from GET discovery and preview resources."
    },
    {
      "reviewer": "kimi",
      "environment": "pc_web",
      "access_mode": "mcp_get_discovery_and_preview_resources",
      "live_mcp_post": false,
      "get_discovery": true,
      "get_preview_resources": true,
      "fallback_used": false,
      "result": "Reviewed from GET discovery and preview resources."
    },
    {
      "reviewer": "minimax_agent",
      "environment": "pc_web",
      "access_mode": "mcp_get_discovery_and_preview_resources",
      "live_mcp_post": false,
      "get_discovery": true,
      "get_preview_resources": true,
      "fallback_used": false,
      "result": "Reviewed from GET discovery and preview resources; dry-run was not callable because JSON-RPC POST was unavailable."
    },
    {
      "reviewer": "glm_5_turbo",
      "environment": "pc_web",
      "access_mode": "mcp_get_discovery_and_preview_resources",
      "live_mcp_post": false,
      "get_discovery": true,
      "get_preview_resources": true,
      "fallback_used": false,
      "result": "Reviewed discovery and preview resources; reported one GET preview issue that local verification classified as false positive because resource previews returned data.payload, not discovery tools."
    }
  ],
  "access_contract": {
    "mcp_capable_clients": {
      "transport": "json_rpc_post",
      "endpoint": "/mcp",
      "can_call_tools": true
    },
    "get_only_clients": {
      "transport": "http_get_preview",
      "allowed_endpoints": [
        "/mcp",
        "/mcp?resource=agent:onboarding",
        "/mcp?resource=agent:state-summary"
      ],
      "can_call_tools": false,
      "scope": "safe_read_only_preview"
    },
    "requires_post": [
      "search",
      "fetch",
      "knownet_review_dry_run",
      "knownet_submit_review"
    ]
  }
}
```
