# MCP Client Setup

KnowNet exposes a local stdio MCP server for scoped AI-agent access.

The compatibility reference is in:

```txt
docs/MCP_COMPATIBILITY_REFERENCES.md
```

Use that document when deciding how a new AI client should connect. Keep this
file focused on concrete setup commands.

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

The same example is checked into:

```txt
apps/mcp/configs/claude_desktop_config.example.json
```

Claude Desktop should use this local stdio path first. Do not route Claude
Desktop through Cloudflare unless testing a remote connector specifically.

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
apps/api/.venv/Scripts/python.exe apps/mcp/knownet_mcp/server.py
```

The process speaks JSON-RPC over stdin/stdout. Logs are written to stderr.

To verify that a stdio client can at least initialize and list tools/resources:

```powershell
$env:KNOWNET_BASE_URL="http://127.0.0.1:8000"
$env:KNOWNET_AGENT_TOKEN="<token shown once by the operator dashboard>"
apps/api/.venv/Scripts/python.exe apps/mcp/scripts/mcp_stdio_smoke.py
```

This smoke test does not submit reviews. It checks `initialize`,
`tools/list`, `resources/list`, and `prompts/list`.

## ChatGPT Quick Tunnel Test

ChatGPT custom connectors can run in two modes. Full developer-mode connectors
may expose every `knownet_*` tool. Some connector surfaces only expose
`search` and `fetch`. KnowNet supports both:

```txt
search  -> returns onboarding, state summary, and matching page results
fetch   -> fetches one result by id
```

If `knownet_*` tools are not visible in the client, do not substitute a GitHub
repository read for KnowNet state. Use `search` for `KnowNet current state`,
then `fetch` the returned `agent:onboarding`, `agent:state-summary`, or
`page:*` ids. If the client supports full tools, prefer this order:

```txt
knownet_start_here
knownet_me
knownet_state_summary
knownet_ai_state
knownet_review_dry_run
```

`knownet_state_summary` and `agent:state-summary` expose the same state through
different MCP surfaces. Use the tool when the client can call JSON-RPC tools.
Use the resource or `fetch agent:state-summary` when the client works better
with resource reads. GET preview clients can only read the safe HTTP preview at
`/mcp?resource=agent:state-summary`.

For temporary quick-tunnel testing, run the HTTP bridge and tunnel only for the
test window. Revoke the temporary agent token immediately after the test.

```powershell
$env:KNOWNET_BASE_URL="http://127.0.0.1:8000"
$env:KNOWNET_AGENT_TOKEN="<short-lived token>"
$env:KNOWNET_MCP_HTTP_PORT="8010"
apps/api/.venv/Scripts/python.exe -m knownet_mcp.http_bridge
cloudflared tunnel --url http://127.0.0.1:8010
```

Register the connector URL as:

```txt
https://<quick-tunnel-host>/mcp
```

The HTTP discovery response now includes `transport_profiles` and
`client_profiles` so connector-capable clients can see whether they are using
local stdio, HTTP bridge, or GET preview fallback.

Templates:

```txt
apps/mcp/configs/http_bridge.env.example
apps/mcp/configs/chatgpt_custom_connector.example.json
```

## Preferred State Tool

Use `knownet_ai_state` when an AI client needs compact structured project
context. It returns JSON rows derived from active pages, including summaries,
sections, links, source references, and content hashes. Use
`knownet_read_page` only when the agent needs the full narrative source text for
a specific page.

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

`knownet_* tools are not visible`:
Confirm the client is using full MCP developer mode. If it is not, use the
connector-compatible `search` and `fetch` tools. Also check the connector URL,
`KNOWNET_BASE_URL`, `KNOWNET_AGENT_TOKEN`, token scopes, and the MCP bridge
stderr log.

`client cannot use the MCP URL`:
Some web AI products cannot attach arbitrary MCP connectors even when the
quick-tunnel URL is reachable. In that case, ask the operator for captured
`search`, `fetch`, or `knownet_*` JSON responses. Mark the review as
`static-spec fallback` if it relies on repository documents instead of live
KnowNet state.

`GET /mcp works but tool calls do not`:
`GET /mcp`, `GET /mcp/tools`, and `GET /.well-known/mcp` expose only safe
discovery metadata for web clients and reviewers. Real MCP calls still use
JSON-RPC `POST /mcp`. A successful GET discovery response is not proof that a
web product can call tools.

For clients that cannot POST JSON-RPC, these read-only previews are available:

```txt
GET /mcp?resource=agent:onboarding
GET /mcp?resource=agent:state-summary
```

These previews are intentionally limited. Review submission and dry-run remain
JSON-RPC POST operations so review bodies are not placed in URLs or GET logs.

## Public Exposure

Do not expose KnowNet publicly without `PUBLIC_MODE=true`, a long admin token,
and Cloudflare Access or equivalent protection. MCP clients should normally
connect to a local KnowNet instance.
