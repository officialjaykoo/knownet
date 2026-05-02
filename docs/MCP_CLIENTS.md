# MCP Client Setup

KnowNet exposes a local stdio MCP server for scoped AI-agent access.

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

## Claude Desktop

Example stdio configuration:

```json
{
  "mcpServers": {
    "knownet": {
      "command": "C:\\knownet\\apps\\api\\.venv\\Scripts\\python.exe",
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

## Cursor

Use the same command, args, and environment values in Cursor's MCP server
configuration. Keep the token in the client environment entry and never paste it
into prompt text.

## Codex Or Local Agent

For a local stdio agent runner, start:

```powershell
$env:KNOWNET_BASE_URL="http://127.0.0.1:8000"
$env:KNOWNET_AGENT_TOKEN="<token shown once by the operator dashboard>"
apps/api/.venv/Scripts/python.exe apps/mcp/knownet_mcp/server.py
```

The process speaks JSON-RPC over stdin/stdout. Logs are written to stderr.

## Preferred State Tool

Use `knownet_ai_state` when an AI client needs compact structured project
context. It returns JSON rows derived from active pages, including summaries,
sections, links, source paths, and content hashes. Use `knownet_read_page` only
when the agent needs the full narrative source text for a specific page.

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
Request fewer pages or read one page at a time.

`rate_limited`:
Wait before retrying. The response may include `retry_after_seconds`.

`request_id`:
Include this value when reporting a failed MCP call. It is also written to MCP
stderr logs.

## Public Exposure

Do not expose KnowNet publicly without `PUBLIC_MODE=true`, a long admin token,
and Cloudflare Access or equivalent protection. MCP clients should normally
connect to a local KnowNet instance.
