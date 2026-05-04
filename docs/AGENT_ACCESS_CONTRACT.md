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

## Operator Dashboard

Owner/admin users manage agent tokens in the web Agent Access dashboard. The
dashboard uses the existing `/api/agents/*` endpoints and does not create a
separate token system.

Dashboard behavior:

```txt
Create:
  Choose role, scope preset, optional explicit scopes, expiry, purpose, and
  context limits.
  The raw token is shown once in a warning panel.

Rotate:
  Requires confirmation.
  Revokes the old token and shows the replacement raw token once.

Revoke:
  Requires confirmation.
  Leaves the token visible for audit and event triage.

Troubleshoot:
  Use status filters, health chips, and sanitized access events to identify
  denied, rate-limited, expired, or unused tokens.
```

Raw tokens are never returned by token list or event APIs. The dashboard labels
safe token ids as `Token ID` and labels one-time secrets as
`Raw token shown once`.

## Read Endpoints

```txt
GET /api/agent/ping
GET /api/agent/me
GET /api/agent/onboarding
GET /api/agent/context
GET /api/agent/ai-state
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

`/api/agent/onboarding` requires a valid agent token but does not require a
specific read scope. It tells first-contact agents what to read first, what is
allowed, what is forbidden, and how to submit review findings safely. It is a
recommendation, not a blocking gate: KnowNet uses prior `agent.onboarding`
access events to return `start_here_hint: "recommended"` when no recent start
has been seen and `"available"` after the token has already called the
onboarding endpoint.

Onboarding rows are protected system pages. Read APIs expose `system_kind`,
`system_tier`, and `system_locked`. Agents must treat `system_locked: true` as
read-only; locked system pages cannot be overwritten through suggestion apply,
page restore, or page deletion.

## Filesystem Boundary

External agents do not receive raw filesystem write tools. Page access uses
page ids or slugs through scoped APIs. Page writes in the local application use
slug validation and resolved paths under the configured page storage directory;
raw path parameters, parent-directory traversal, database files, backup files,
and direct filesystem access are outside the agent contract.

If an external review was produced from old static documents and reports raw
path-write risk, triage it against the current scoped API surface before
treating it as an active vulnerability.

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

Page list/read rows may include:

```json
{
  "system_kind": "onboarding",
  "system_tier": 1,
  "system_locked": true
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

Title: Short finding title
Severity: critical | high | medium | low | info
Area: API | UI | Rust | Security | Data | Ops | Docs

Evidence:
...

Proposed change:
...
```

## State Conflict Policy

SQLite structured records and generated AI state are the canonical collaboration
state. Page Markdown is durable narrative source material and must be read
through scoped APIs or MCP tools.

If page content, AI state, graph data, or citation indexes disagree, treat the
case as index drift. External agents should not guess which layer is correct and
should not request raw database or filesystem access. Report the drift as a
finding and ask an operator to run verify-index or rebuild through the
operator-controlled API.

## Context Budget

Agents receive scoped, bounded context. Large reads may return:

```json
{ "truncated": true }
```

Large writes may return HTTP `413`.

## Structured AI State

`GET /api/agent/ai-state` returns the structured JSON form of active project
pages. This is the preferred machine-readable state when an AI agent needs a
compact understanding of current KnowNet structure.

Each row includes:

```json
{
  "page_id": "page_knownet_overview",
  "slug": "knownet-overview",
  "title": "KnowNet Overview",
  "content_hash": "...",
  "state": {
    "schema_version": 1,
    "kind": "page_state",
    "summary": "string",
    "sections": [],
    "links": [],
    "source": {
      "format": "markdown",
      "path": "data/pages/knownet-overview.md"
    }
  }
}
```

Markdown remains the narrative source attachment. `ai_state_pages.state_json` is
the indexed JSON row that agents should prefer for quick state reads.

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
3. GET /api/agent/onboarding
4. GET /api/agent/state-summary
5. GET /api/agent/ai-state
6. GET /api/agent/pages only when full page text is needed
7. GET /api/agent/findings
```

## Example Review Flow

```txt
1. GET /api/agent/me
2. GET /api/agent/onboarding
3. GET /api/agent/context
4. POST /api/collaboration/reviews?dry_run=true
5. Fix format if needed
6. POST /api/collaboration/reviews
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

The MCP server exposes only these standard proposal tools:

```txt
knownet.propose_finding
knownet.propose_task
knownet.submit_implementation_evidence
```

No maintenance, admin, raw database, shell, filesystem, backup, token, user,
session, release-check, search, fetch, or `knownet_*` tool aliases are exposed.

During MCP `initialize`, the server returns diagnostics for API reachability,
agent token validity, token scopes, and token expiry. Treat diagnostics warnings
as operator action items before starting long reviews.

The MCP server exposes these standard resources:

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

The MCP server exposes these reusable prompts:

```txt
knownet.compact_review
knownet.implementation_candidate
knownet.provider_risk_check
```

Prompts instruct agents to use bounded resources and operator-gated proposal
tools. They do not include token values, database paths, or maintenance
controls.

## Python SDK

KnowNet includes a Python SDK at:

```txt
packages/knownet-agent-py/
```

Use environment variables for tokens:

```python
from knownet_agent import KnowNetClient

client = KnowNetClient.from_env()

print(client.start_here().data)
print(client.me().data)
```

Do not hard-code agent tokens in source files. The SDK reads
`KNOWNET_AGENT_TOKEN`, `KNOWNET_BASE_URL`, and optional
`KNOWNET_AGENT_TIMEOUT_SECONDS`.

Phase 12 adds typed models, bounded pagination helpers, context manager support,
safe review workflow helpers, and actionable SDK errors. Use
`dry_run_then_submit_review` for custom review scripts so parsing is checked
before final import. `AsyncKnowNetClient` is reserved for a later phase and does
not perform async HTTP yet.
