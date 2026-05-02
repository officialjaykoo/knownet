# Agent Access Contract

This document is the short contract for external AI agents that connect to
KnowNet.

## Authentication

Use:

```txt
Authorization: Bearer <agent token shown once by the operator dashboard>
```

The token is scoped. It is not an admin token and cannot access maintenance
operations.

## Read Endpoints

```txt
GET /api/agent/ping
GET /api/agent/me
GET /api/agent/context
GET /api/agent/pages
GET /api/agent/pages/{page_id}
GET /api/agent/reviews
GET /api/agent/findings
GET /api/agent/graph
GET /api/agent/citations
GET /api/agent/state-summary
```

`/api/agent/ping` needs no token and returns only:

```json
{ "ok": true, "version": "9.0" }
```

## Response Shape

Agent read responses use:

```json
{
  "ok": true,
  "data": {},
  "meta": {
    "schema_version": 1,
    "vault_id": "local-default",
    "agent_scope": ["pages:read"],
    "truncated": false,
    "total_count": 0,
    "returned_count": 0,
    "generated_at": "2026-05-02T00:00:00Z"
  }
}
```

If the token has an expiry, responses include:

```txt
X-Token-Expires-In: {seconds}
```

MCP tool and resource responses add operator-friendly metadata when available:

```json
{
  "request_id": "req_abc123",
  "token_expires_in_seconds": 86400,
  "token_warning": "expires_soon",
  "chars_returned": 60000,
  "warning": "page_truncated_use_narrower_reads"
}
```

Use `request_id` when reporting a failed or surprising MCP call. If a response
contains `token_warning`, rotate the token before it expires.

## Scopes

Common scopes:

```txt
pages:read
reviews:read
findings:read
graph:read
citations:read
messages:create
reviews:create
```

Scope presets are expanded when the token is created:

```txt
preset:reader
preset:reviewer
preset:contributor
```

Wildcard scopes are not used.

## Write Gateway

Agents never write to the database directly.

Allowed write routes depend on token role and scope:

```txt
POST /api/messages
POST /api/collaboration/reviews
POST /api/collaboration/reviews?dry_run=true
POST /api/collaboration/findings/{finding_id}/decision
POST /api/collaboration/findings/{finding_id}/implementation
```

Use dry-run before submitting a review when unsure:

```txt
POST /api/collaboration/reviews?dry_run=true
```

Dry-run parses findings but does not create review or finding records.

## Finding Format

```md
### Finding

Severity: critical | high | medium | low | info
Area: API | UI | Rust | Security | Data | Ops | Docs

Evidence:
...

Proposed change:
...
```

## Context Budget

Agents receive scoped, bounded context. Large reads may return:

```json
{ "truncated": true }
```

Large writes may return HTTP `413`.

## Forbidden Data

Agent APIs must not return:

```txt
raw database files
secret values
sessions
users
token_hash
raw tokens
backup paths
maintenance state that grants control
```

## Example Read Flow

```txt
1. GET /api/agent/ping
2. GET /api/agent/me
3. GET /api/agent/state-summary
4. GET /api/agent/pages
5. GET /api/agent/findings
```

## Example Review Flow

```txt
1. GET /api/agent/me
2. GET /api/agent/context
3. POST /api/collaboration/reviews?dry_run=true
4. Fix format if needed
5. POST /api/collaboration/reviews
```

## MCP Setup

KnowNet includes a stdio MCP server at:

```txt
apps/mcp/knownet_mcp/server.py
```

Set configuration through environment variables:

```txt
KNOWNET_BASE_URL=http://127.0.0.1:8000
KNOWNET_AGENT_TOKEN=<token shown once by the operator dashboard>
KNOWNET_MCP_TIMEOUT_SECONDS=30
```

The MCP server exposes only these tools:

```txt
knownet_ping
knownet_me
knownet_state_summary
knownet_list_pages
knownet_read_page
knownet_list_reviews
knownet_list_findings
knownet_graph_summary
knownet_list_citations
knownet_review_dry_run
knownet_submit_review
```

No maintenance or admin tools are exposed.

During MCP `initialize`, the server returns diagnostics for API reachability,
agent token validity, token scopes, and token expiry. Treat diagnostics warnings
as operator action items before starting long reviews.

Phase 11 also exposes safe read-only resources:

```txt
knownet://agent/me
knownet://agent/state-summary
knownet://agent/pages
knownet://agent/pages/{page_id}
knownet://agent/reviews
knownet://agent/findings
knownet://agent/graph
knownet://agent/citations
```

And reusable prompts:

```txt
knownet_review_page
knownet_review_findings
knownet_prepare_external_review
```

Prompts instruct agents to use bounded reads and dry-run review submission
before final import. They do not include token values, database paths, or
maintenance controls.

## Python SDK

Phase 10 includes a small Python SDK at:

```txt
packages/knownet-agent-py/
```

Use environment variables for tokens:

```python
from knownet_agent import KnowNetClient

client = KnowNetClient.from_env()

print(client.me().data)
```

Do not hard-code agent tokens in source files. The SDK reads
`KNOWNET_AGENT_TOKEN`, `KNOWNET_BASE_URL`, and optional
`KNOWNET_AGENT_TIMEOUT_SECONDS`.
