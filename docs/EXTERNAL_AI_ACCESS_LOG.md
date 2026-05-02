# External AI Access Log

This file records practical external AI access tests for KnowNet.

It intentionally focuses on access method and observed result, not every finding
each AI produced.

## Current Test Endpoint

Temporary Cloudflare Quick Tunnel:

```txt
https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
```

Local target:

```txt
http://127.0.0.1:8010/mcp
```

Important:

```txt
This is testing-only infrastructure.
It is not a production endpoint.
```

## Access Modes

### Full MCP JSON-RPC

Clients that can POST JSON-RPC to `/mcp` can use the real KnowNet tools:

```txt
initialize
tools/list
tools/call
knownet_start_here
knownet_me
knownet_state_summary
knownet_ai_state
knownet_review_dry_run
```

This is the strongest external AI access path.

### GET Discovery / Preview

Clients that cannot POST can still read safe preview context:

```txt
GET /mcp
GET /mcp?resource=agent:onboarding
GET /mcp?resource=agent:state-summary
```

Limits:

```txt
No tool calls
No dry-run submission
No review submit
Read-only context only
```

## ChatGPT / Codex

Environment:

```txt
Codex shell
Cloudflare Quick Tunnel
KnowNet MCP HTTP bridge
```

Confirmed calls:

```txt
initialize
tools/list
knownet_start_here
knownet_me
knownet_state_summary
knownet_ai_state
knownet_review_dry_run
```

Result:

```txt
Full MCP JSON-RPC POST works.
Review dry-run works.
No real review was submitted during this test.
```

## ChatGPT PC Web

Environment:

```txt
ChatGPT PC Web
Custom MCP connector
Cloudflare Quick Tunnel
```

Configuration:

```txt
URL: https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
Authentication: none
```

Confirmed calls:

```txt
knownet_start_here
```

Result:

```txt
ChatGPT PC Web can use KnowNet when the custom MCP connector is registered.
Ordinary chats without the connector cannot see knownet_* tools.
```

## Claude

Working route:

```txt
Claude Desktop or claude.ai settings
-> Connectors / Integrations
-> Add custom MCP server
-> enter the KnowNet MCP URL directly
```

Configuration:

```txt
URL: https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
Authentication: none
```

Confirmed calls:

```txt
knownet_start_here
knownet_me
knownet_state_summary
```

Observed state:

```txt
token_id: agent_55b5a5bf6896
role: agent_reviewer
scopes: citations/read, findings/read, graph/read, pages/read, reviews/read, reviews/create
phase: 14
pages: 64
reviews: 13
findings: 59
graph_nodes: 630
release_ready: false
```

Important:

```txt
Uploading claude_desktop_config.json into a Claude chat is not the working path.
The working path is registering the MCP URL in Claude's connector/integration UI.
```

## DeepSeek Web / Desktop App

User observation:

```txt
DeepSeek web and desktop app are effectively the same for this purpose.
Differences are minor UI details such as shortcuts.
```

Free realistic route:

```txt
Use GET discovery and GET preview.
```

Useful URLs:

```txt
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:onboarding
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:state-summary
```

Result:

```txt
DeepSeek free web/app can inspect KnowNet through GET preview.
It cannot perform JSON-RPC tool calls or review dry-run directly from the free web/app UI.
```

Recommended prompt for DeepSeek free web/app:

```txt
Use these KnowNet GET preview URLs:

1. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
2. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:onboarding
3. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:state-summary

Review KnowNet as a first-time external AI contributor.
Do not submit a review.
Return findings in this format:

### Finding
Title:
Severity:
Area:
Evidence:
Proposed change:
```

Separate DeepSeek API runner status is recorded in
[MODEL_RUNS.md](MODEL_RUNS.md).

## Qwen Web

User observation:

```txt
Qwen web can use built-in web_search / web_extractor style tools.
It does not need a separate Qwen API runner for the current free web test.
```

Free realistic route:

```txt
Use GET discovery and GET preview through Qwen's extractor/search tools.
```

Useful URLs:

```txt
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:onboarding
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:state-summary
```

Result:

```txt
Qwen free web can inspect KnowNet through GET preview.
It cannot directly perform KnowNet JSON-RPC tool calls from the web UI.
It can still help generate or inspect a local MCP client script that the operator runs on this PC.
No Qwen API provider runner is needed at this stage.
```

Assisted local MCP mode:

```txt
Qwen Web
-> writes/explains local Python MCP client code
-> operator runs the script on the KnowNet PC
-> script sends JSON-RPC POST to KnowNet /mcp
-> operator gives the result back to Qwen
```

KnowNet includes a shared local client for this:

```powershell
python scripts\knownet_mcp_post_client.py --preset start-here
python scripts\knownet_mcp_post_client.py --preset state-summary
python scripts\knownet_mcp_post_client.py --preset tools
python scripts\knownet_mcp_post_client.py --preset ai-state
```

Use a tunnel URL when testing from outside the PC:

```powershell
python scripts\knownet_mcp_post_client.py --url https://dealers-spirituality-marker-compute.trycloudflare.com/mcp --preset start-here
```

Recommended prompt for Qwen free web:

```txt
Use web_extractor or equivalent browsing tools to read these KnowNet URLs:

1. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
2. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:onboarding
3. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:state-summary

Review KnowNet as a first-time external AI contributor.
Do not submit a review.
Return findings in this format:

### Finding
Title:
Severity:
Area:
Evidence:
Proposed change:
```

## Current Judgment

Confirmed:

```txt
ChatGPT/Codex: full MCP JSON-RPC works
ChatGPT PC Web: custom MCP connector works
Claude: connector/integration registration works
DeepSeek Web/Desktop free: GET discovery/preview works
Qwen Web free: GET discovery/preview works through extractor/search tools
```

Next infrastructure step:

```txt
Move from quick tunnel to named tunnel plus access control before production use.
```
