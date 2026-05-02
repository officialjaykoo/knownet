# Phase 12 Tasks: SDK Production Hardening

Phase 12 turns the Phase 10 Python SDK from a thin HTTP wrapper into a reliable
client library for external AI scripts and custom automation.

Implementation status: pending.

Phase 12 is SDK-only. MCP was hardened in Phase 11. The Agent Dashboard should
be improved later as Phase 13.

## Fixed Decisions

```txt
Phase 9 remains the source of truth:
  /api/agent/* is the scoped read layer.
  Existing KnowNet APIs remain the write gateway.
  Agent tokens, scopes, context budgets, and access events remain authoritative.

Phase 11 remains valid:
  MCP is the preferred integration path for MCP-capable clients.
  Python SDK is for custom scripts and non-MCP agents.

SDK:
  Lives under packages/knownet-agent-py/.
  Uses HTTP APIs only.
  Does not read SQLite directly.
  Does not create a new auth model.
  Does not hard-code tokens in examples.
  Does not retry writes by default.

Dashboard:
  Not part of Phase 12.
  Dashboard UX and operations can be Phase 13.
```

## Do Not Change

```txt
Do not:
  Add direct database access to the SDK.
  Add remote agent execution.
  Add shell command execution.
  Add maintenance operations to the SDK.
  Add another token system.
  Expand the Dashboard in this phase.
  Rebuild MCP in this phase.
  Reintroduce external note-app compatibility.
```

## Implementation Order

Implement in this order:

```txt
1. P12-001 Package Metadata
2. P12-002 Typed Models And Response Metadata
3. P12-003 Pagination Helpers
4. P12-004 Agent Workflow Helpers
5. P12-005 Robust Error Surface
6. P12-006 SDK End-To-End Test
7. P12-007 Examples And Documentation
8. P12-008 Regression And Release Checks
```

## P12-001 Package Metadata

Goal:

```txt
Make the SDK package installable and inspectable as a real local package.
```

Update:

```txt
packages/knownet-agent-py/pyproject.toml
```

Required metadata:

```txt
name = knownet-agent
version = 0.12.0
description
readme = README.md
requires-python >= 3.10
license
authors
keywords
classifiers
```

Package rules:

```txt
Use stdlib HTTP unless a dependency is clearly justified.
Do not add broad dependencies for simple typing or HTTP calls.
Keep package import as:
  from knownet_agent import KnowNetClient
```

Done when:

```txt
python -m pip install -e packages/knownet-agent-py works.
python -c "from knownet_agent import KnowNetClient" works.
```

## P12-002 Typed Models And Response Metadata

Goal:

```txt
Expose stable typed objects so agents do not need to parse raw dicts for common
state.
```

Add dataclasses:

```txt
KnowNetMeta:
  schema_version
  vault_id
  agent_scope
  truncated
  total_count
  returned_count
  next_offset
  generated_at
  request_id
  chars_returned
  warning
  token_expires_in_seconds
  token_warning

KnowNetPage:
  id
  slug
  title
  updated_at
  content optional

KnowNetReview:
  id
  title
  source_agent
  source_model
  status
  page_id
  created_at
  updated_at

KnowNetFinding:
  id
  review_id
  severity
  area
  title
  status
  created_at
  updated_at

KnowNetCitation:
  id
  page_id
  citation_key
  status
  verifier_type
  confidence
  reason
  updated_at
```

Response rules:

```txt
Keep KnowNetResponse.data for backwards compatibility.
Add KnowNetResponse.meta_obj for typed metadata.
Add convenience methods:
  pages()
  reviews()
  findings()
  citations()
  page()
```

Done when:

```txt
Tests cover conversion from API JSON into typed models.
Existing SDK tests still pass.
```

## P12-003 Pagination Helpers

Goal:

```txt
Make bounded list traversal easy without forcing every script to manage offset.
```

Add:

```python
iter_pages(limit=20, max_items=None)
iter_reviews(limit=50, max_items=None)
iter_findings(limit=100, status=None, max_items=None)
iter_citations(limit=100, status=None, max_items=None)
```

Rules:

```txt
Use meta.next_offset when present.
Stop when no next_offset is present.
Respect max_items.
Never request an unbounded list.
Default per-page limits match Phase 9/11 defaults.
```

Done when:

```txt
Tests cover multi-page iteration, max_items stop, and no-next-offset stop.
```

## P12-004 Agent Workflow Helpers

Goal:

```txt
Provide safe helpers for common AI review scripts.
```

Add:

```python
require_scopes(required: list[str]) -> None
token_expires_soon(within_seconds=604800) -> bool
read_context_for_review(max_pages=5) -> list[KnowNetPage]
dry_run_then_submit_review(markdown, source_agent=None, source_model=None)
```

Rules:

```txt
require_scopes calls me() and raises KnowNetScopeError with missing scopes.
token_expires_soon uses X-Token-Expires-In or response metadata.
read_context_for_review uses iter_pages and read_page, never unbounded reads.
dry_run_then_submit_review runs dry_run_review first and submits only if dry-run
returns ok and finding_count is acceptable.
```

Done when:

```txt
Tests prove submit is not called when dry-run fails.
Tests prove missing scopes are reported clearly.
```

## P12-005 Robust Error Surface

Goal:

```txt
Make SDK errors useful enough for an AI agent to report actionable failures.
```

Existing errors remain:

```txt
KnowNetAuthError
KnowNetScopeError
KnowNetRateLimitError
KnowNetPayloadTooLargeError
KnowNetServerError
```

Add properties where available:

```txt
KnowNetError.code
KnowNetError.request_id
KnowNetScopeError.required_scope
KnowNetScopeError.current_scopes
KnowNetRateLimitError.retry_after_seconds
KnowNetPayloadTooLargeError.limit_hint
```

Network behavior:

```txt
Add KnowNetConnectionError for URL/connection failures.
One retry remains allowed for idempotent GET.
Writes are not retried by default.
```

Done when:

```txt
Tests cover 401, 403, 413, 429, 500, malformed JSON, and connection failure.
```

## P12-006 SDK End-To-End Test

Goal:

```txt
Prove the SDK works against the real local KnowNet API surface.
```

Test shape:

```txt
Start a local test API server.
Create an agent token through the existing admin API.
Create at least one page.
Use KnowNetClient against the server.
Call:
  ping()
  me()
  iter_pages()
  read_page()
  dry_run_review()
  submit_review()
  require_scopes()
  token_expires_soon()
Assert:
  no raw token appears in normal response data
  pagination helpers stop correctly
  dry-run happens before submit
  scope errors include required/current scopes
```

Done when:

```txt
The E2E test runs in local pytest without requiring an external service.
```

## P12-007 Examples And Documentation

Update:

```txt
packages/knownet-agent-py/README.md
docs/AGENT_ACCESS_CONTRACT.md
README.md
```

Add:

```txt
docs/SDK_CLIENTS.md
```

Examples:

```txt
examples/read_state.py
examples/dry_run_review.py
examples/submit_review.py
examples/iterate_pages.py
examples/review_workflow.py
```

Documentation must explain:

```txt
Environment variables
Token rotation behavior
Pagination helpers
Dry-run before submit
Scope error handling
Token expiry warnings
No direct database access
```

Rules:

```txt
Examples use placeholder tokens or environment variables only.
Examples do not include real local paths or secrets.
Examples do not call maintenance/admin endpoints.
```

Done when:

```txt
A custom Python agent can read docs and submit a safe dry-run review without
reading SDK source code.
```

## P12-008 Regression And Release Checks

Run:

```powershell
$env:PYTHONPATH='packages/knownet-agent-py'; apps/api/.venv/Scripts/python.exe -m pytest packages/knownet-agent-py/tests -q
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests -q
$env:PYTHONPATH='apps/mcp'; apps/api/.venv/Scripts/python.exe -m pytest apps/mcp/tests -q
cd apps/core; cargo test
cd ../web; npm run build
cd ../web; npm audit --audit-level=moderate
```

Also run:

```powershell
rg -n "KNOWNET_AGENT_TOKEN=.*kn_agent_|token_hash|raw_token|/api/maintenance|knownet.db|backups" packages/knownet-agent-py docs/SDK_CLIENTS.md
```

Expected result:

```txt
No SDK example or doc hard-codes real-looking tokens or exposes forbidden data.
```

## Completion Definition

Phase 12 is complete when:

```txt
1. SDK package metadata is complete enough for local editable install.
2. Common response data can be consumed through typed models.
3. Pagination helpers cover pages, reviews, findings, and citations.
4. Workflow helpers guide agents through safe review behavior.
5. Error objects expose actionable scope, request, retry, and expiry details.
6. SDK E2E test proves real HTTP integration.
7. SDK docs and examples are usable without reading source code.
8. Existing API, MCP, Rust, and web checks still pass.
```

Phase 12 should make custom AI scripts easier to write. It must not make KnowNet
less safe or bypass the scoped API model.

## Next Phase Candidate

```txt
Phase 13:
  Agent Dashboard UX And Operations
```

Dashboard work is intentionally left out of Phase 12.
