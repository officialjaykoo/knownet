# MCP Client Setup

KnowNet exposes one standard MCP surface for scoped AI-agent access. It does
not expose compatibility aliases.

The MCP server path is:

```txt
apps/mcp/knownet_mcp/server.py
```

Set these environment variables in the MCP client configuration:

```txt
KNOWNET_BASE_URL=http://127.0.0.1:8000
KNOWNET_AGENT_TOKEN=<token shown once by the operator dashboard>
KNOWNET_MCP_TIMEOUT_SECONDS=30
KNOWNET_MCP_LOG_LEVEL=info
KNOWNET_MCP_LOG_FORMAT=json
```

Use an agent token with only the scopes needed by that client. Rotate tokens
from the Agent Access panel when a client configuration changes.

## Standard Surface

The standard KnowNet MCP baseline is documented in:

```txt
docs/MCP_SCOPE.md
```

Resources:

```txt
knownet://snapshot/overview
knownet://snapshot/stability
knownet://snapshot/performance
knownet://snapshot/security
knownet://snapshot/implementation
knownet://snapshot/provider_review
knownet://node/{slug_or_page_id}
knownet://finding/recent
```

Tools:

```txt
knownet.propose_finding
knownet.propose_task
knownet.submit_implementation_evidence
```

Prompts:

```txt
knownet.compact_review
knownet.implementation_candidate
knownet.provider_risk_check
```

Do not use or document `search`, `fetch`, `knownet_*` tool aliases, or
`knownet://agent/...` resource aliases.

## Claude Desktop

Example stdio configuration:

```json
{
  "mcpServers": {
    "knownet": {
      "command": "python",
      "args": ["C:\\knownet\\apps\\mcp\\knownet_mcp\\server.py"],
      "env": {
        "KNOWNET_BASE_URL": "http://127.0.0.1:8000",
        "KNOWNET_AGENT_TOKEN": "<token shown once by the operator dashboard>",
        "KNOWNET_MCP_LOG_FORMAT": "json"
      }
    }
  }
}
```

The same example is checked into:

```txt
apps/mcp/configs/claude_desktop_config.example.json
```

Claude Desktop should use local stdio MCP first. Do not route Claude Desktop
through Cloudflare unless testing a remote connector specifically.

## Cursor

Use the same command, args, and environment values in Cursor's MCP server
configuration. Keep the token in the client environment entry and never paste it
into prompt text.

Template:

```txt
apps/mcp/configs/cursor_mcp.example.json
```

## Codex Or Local Agent

For a local stdio agent runner, start:

```powershell
$env:KNOWNET_BASE_URL="http://127.0.0.1:8000"
$env:KNOWNET_AGENT_TOKEN="<token shown once by the operator dashboard>"
python apps/mcp/knownet_mcp/server.py
```

The process speaks JSON-RPC over stdin/stdout. Logs are written to stderr.

Recommended first calls:

```txt
initialize
resources/list
resources/read knownet://snapshot/overview
resources/read knownet://finding/recent
prompts/get knownet.compact_review
tools/call knownet.propose_finding
```

To verify that a stdio client can initialize and list the standard surface:

```powershell
$env:KNOWNET_BASE_URL="http://127.0.0.1:8000"
$env:KNOWNET_AGENT_TOKEN="<token shown once by the operator dashboard>"
python apps/mcp/scripts/mcp_stdio_smoke.py
```

This smoke test does not submit reviews. It checks `initialize`, `tools/list`,
`resources/list`, and `prompts/list`.

## HTTP Bridge Test

For temporary HTTP bridge testing, run the bridge and tunnel only for the test
window. Revoke the temporary agent token immediately after the test.

```powershell
$env:KNOWNET_BASE_URL="http://127.0.0.1:8000"
$env:KNOWNET_AGENT_TOKEN="<short-lived token>"
$env:KNOWNET_MCP_HTTP_PORT="8010"
$env:PYTHONPATH="C:\knownet\apps\mcp"
python -m knownet_mcp.http_bridge
cloudflared tunnel --url http://127.0.0.1:8010
```

Register the connector URL as:

```txt
https://<quick-tunnel-host>/mcp
```

The HTTP bridge accepts real MCP traffic through JSON-RPC `POST /mcp`. GET is
limited to `/health`; `/mcp`, `/mcp/tools`, and `/.well-known/mcp` return
`method_not_allowed` so clients do not confuse discovery metadata with resource
reads.

## Troubleshooting

`auth_failed`:
The token is missing, expired, revoked, or copied incorrectly. Rotate the token
and update the MCP client environment.

`scope_denied`:
The token lacks the scope required by the requested tool or resource. Create a
narrower or broader scoped token from the Agent Access panel.

`token_warning=expires_soon`:
Rotate the token before running a long review.

`context_too_large`:
Request a narrower snapshot profile or one node resource.

`rate_limited`:
Wait before retrying. The response may include `retry_after_seconds`.

`request_id`:
Include this value when reporting a failed MCP call. It is also written to MCP
stderr logs.

`unknown_tool`, `unknown_prompt`, or `invalid_resource`:
Use the standard surface listed above. KnowNet does not provide compatibility
aliases for older MCP tool, prompt, resource, search, or fetch names.

## Public Exposure

Do not expose KnowNet publicly without `PUBLIC_MODE=true`, a long admin token,
and Cloudflare Access or equivalent protection. MCP clients should normally
connect to a local KnowNet instance.
