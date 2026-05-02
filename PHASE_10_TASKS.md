# Phase 10 Tasks: Agent Tooling And Operations

Phase 10 turns the Phase 9 Agent Access Layer into practical tooling for real
AI agents and the operator.

Implementation status: completed in the codebase.

Implemented surface:

```txt
P10-001:
  stdio MCP server with the fixed allowed tool list and HTTP wrapper over Phase
  9 endpoints.

P10-002:
  Small Python SDK with typed errors, response metadata, examples, and tests.

P10-003:
  Simple Agent Access dashboard for token list/create/revoke/rotate and
  sanitized recent events.

P10-004:
  MCP, SDK, API regression, Rust, and web build checks.

P10-005:
  Agent access contract, README, and runbook updates.
```

Phase 10 has exactly three product goals:

```txt
1. MCP server:
   Let MCP-capable AI tools use KnowNet as a tool provider.

2. Python Agent SDK:
   Let custom agent scripts call KnowNet safely without hand-writing REST
   boilerplate.

3. Per-agent dashboard UI:
   Let the operator see tokens, scopes, activity, and recent failures.
```

Phase 10 should not add direct AI execution, sandboxing, remote shell access, or
a second write model. It wraps and observes the Phase 9 API surface.

## Fixed Decisions

```txt
Phase 9 remains the source of truth:
  /api/agent/* is the read layer.
  Existing KnowNet APIs are the write gateway.
  Agent tokens, scopes, context budgets, and access events remain authoritative.

MCP server:
  Wraps Phase 9 APIs.
  Does not read the SQLite database directly.
  Does not bypass scopes.
  Does not create admin or maintenance tools.

Python SDK:
  Wraps HTTP calls to Phase 9 APIs.
  Does not embed secrets in code examples.
  Does not implement its own auth model.

Dashboard UI:
  Uses existing admin/owner APIs.
  Displays token metadata and sanitized access events only.
  Never displays raw token after creation.

Archive format:
  .tar.gz only where archives are relevant.
```

## Do Not Change

```txt
Do not:
  Add direct database access for MCP or SDK.
  Add remote agent execution.
  Add shell command execution.
  Add maintenance operations to MCP tools.
  Add another token system.
  Reintroduce external note-app compatibility.
```

## P10-001 MCP Server

Goal:

```txt
Expose KnowNet Agent Access Layer as MCP tools for AI clients.
```

Location:

```txt
apps/mcp/
```

Transport:

```txt
stdio first.
HTTP transport can be added later only if needed.
```

Configuration:

```txt
KNOWNET_BASE_URL=http://127.0.0.1:8000
KNOWNET_AGENT_TOKEN=<token shown once by the operator dashboard>
KNOWNET_MCP_TIMEOUT_SECONDS=30
```

Tools:

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

Tool rules:

```txt
All read tools call /api/agent/*.
Review tools call /api/collaboration/reviews with the agent token.
Tool responses preserve Phase 9 response metadata, including truncated.
No tool may call /api/maintenance/*.
No tool may return raw token or token_hash.
```

Error behavior:

```txt
401:
  Return auth_failed with a short operator-facing message.

403:
  Return scope_denied and include the missing scope if the API provides it.

413:
  Return context_too_large and suggest narrower page/context selection.

429:
  Return rate_limited and include retry_after_seconds.
```

Done when:

```txt
An MCP-capable client can call ping, me, list pages, read one page, dry-run a
review, and submit a review.
MCP tests mock KnowNet HTTP responses and prove forbidden endpoints are not
registered as tools.
```

## P10-002 Python Agent SDK

Goal:

```txt
Provide a small Python client for custom agent scripts.
```

Location:

```txt
packages/knownet-agent-py/
```

Client:

```python
from knownet_agent import KnowNetClient
import os

client = KnowNetClient(
    base_url="http://127.0.0.1:8000",
    token=os.environ["KNOWNET_AGENT_TOKEN"],
)
```

Methods:

```txt
ping()
me()
state_summary()
list_pages(limit=20)
read_page(page_id)
list_reviews(limit=50)
list_findings(limit=100)
graph_summary(limit=200)
list_citations(limit=100)
get_context()
dry_run_review(markdown, source_agent=None, source_model=None)
submit_review(markdown, source_agent=None, source_model=None)
submit_message(content)
```

SDK behavior:

```txt
Raise typed exceptions:
  KnowNetAuthError
  KnowNetScopeError
  KnowNetRateLimitError
  KnowNetPayloadTooLargeError
  KnowNetServerError

Expose response metadata:
  truncated
  total_count
  returned_count
  expires_in_seconds

Default timeout:
  30 seconds.

No retries by default for writes.
One retry for idempotent reads when connection fails.
```

Examples:

```txt
examples/read_state.py
examples/dry_run_review.py
examples/submit_review.py
```

Done when:

```txt
SDK tests cover auth header, error mapping, dry-run, submit review, and
truncated metadata.
Examples run against a local KnowNet instance when KNOWNET_AGENT_TOKEN is set.
```

## P10-003 Per-Agent Dashboard UI

Goal:

```txt
Give the operator a clear page for managing agent access and inspecting
activity.
```

UI surface:

```txt
Operations panel or Agent Access tab.
```

Required views:

```txt
Token list:
  label
  agent_name
  agent_model
  role
  scopes
  expires_at
  revoked_at
  last_used_at

Token detail:
  scope list
  context budget
  recent access events
  recent denied events
  revoke action
  rotate action

Create token modal:
  label
  agent_name
  agent_model
  purpose
  role
  scope preset
  explicit scopes
  expires_at
  max_pages_per_request
  max_chars_per_request

Raw token display:
  show once after creation
  never show again after modal is dismissed
```

Visual rules:

```txt
Use clear status chips for active, expiring, expired, revoked.
Use icons for create, revoke, rotate, refresh, and copy.
Do not expose raw token in token list or token detail.
Make denied/rate-limited events easy to scan.
```

Done when:

```txt
Admin/owner can create, revoke, rotate, and inspect agent activity from the UI.
Viewer/editor cannot access the dashboard.
The UI handles token creation raw-token one-time display safely.
```

## P10-004 Integration Tests

Required checks:

```txt
MCP:
  Tool registry contains only allowed tools.
  Tools call the expected Phase 9 endpoints.
  Error mapping handles 401, 403, 413, and 429.

SDK:
  Auth header is sent.
  Typed errors map from KnowNet error responses.
  Metadata is preserved.
  Write methods do not retry by default.

UI:
  Agent dashboard renders token list.
  Create token flow shows raw token once.
  Revoke and rotate actions call correct endpoints.
  Access events render sanitized metadata only.

Regression:
  Existing Phase 9 API tests still pass.
  No new route exposes raw database files, token_hash, sessions, users, backups,
  or maintenance controls.
```

## P10-005 Documentation

Update:

```txt
docs/AGENT_ACCESS_CONTRACT.md:
  Add MCP and SDK usage sections.

README.md:
  Add short "Agent tooling" section.

docs/RUNBOOK.md:
  Add agent token rotation and MCP setup notes if RUNBOOK.md exists.
```

Completion checks:

```txt
Docs explain MCP setup without exposing a real token.
SDK examples use environment variables for tokens.
Dashboard docs explain raw token is shown once.
```

## Completion Definition

Phase 10 is complete when:

```txt
1. MCP server exposes allowed KnowNet agent tools.
2. Python SDK supports core read and review workflows.
3. Per-agent dashboard UI manages tokens and shows sanitized activity.
4. MCP, SDK, UI, and Phase 9 regression tests pass.
5. Documentation explains how an external AI tool or custom script connects.
```

Phase 10 should make KnowNet easier for agents to use. It must not make KnowNet
less safe.
