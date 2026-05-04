# Phase 9 Tasks: Agent Access Layer

Phase 9 lets external AI agents read KnowNet state safely and write back through
the existing KnowNet workflow.

Implementation status: completed in the codebase.

Implemented surface:

```txt
P9-001:
  Agent token create/list/revoke/rotate and per-token event lookup.

P9-002:
  Bearer kn_agent_ authentication, agent Actor mapping, expiry header, and
  admin endpoint rejection.

P9-003:
  /api/agent/ping, /api/agent/me, pages, reviews, findings, graph, citations,
  context, and state-summary read APIs.

P9-004:
  Explicit scope checks with preset expansion at token creation.

P9-005:
  Agent review dry-run and existing review/message write gateway reuse.

P9-006:
  Per-token request limit plus page/content budget enforcement on agent reads.

P9-007:
  Sanitized agent_access_events for reads, denied access, dry-runs, and limits.

P9-008:
  Agent tokens cannot satisfy admin/maintenance dependencies.

P9-009:
  docs/AGENT_ACCESS_CONTRACT.md.

P9-010:
  Phase 9 API regression tests plus full API/Rust/Web verification.
```

Phase 9 is not a broad product expansion. It adds a controlled access layer for
AI agents:

```txt
Fast read:
  Agent-scoped read APIs that behave like narrow database views.

Safe write:
  All writes go through existing KnowNet APIs and Rust commands.

Never expose:
  Raw database files, secrets, sessions, user records, backups, or maintenance
  controls.
```

Phase 9 includes the operational conveniences required to make the access layer
usable by real agents. Do not defer token self-inspection, review dry-run,
token expiry signaling, per-token access event lookup, scope presets, or the
minimal ping endpoint to a later phase.

## Fixed Decisions

```txt
Product identity:
  AI-centered collaboration knowledge base.

Agent access model:
  External agents never receive the SQLite database file.
  External agents read through scoped read-only APIs.
  External agents write through existing API write gateways.
  Agents can inspect their own token capability through /api/agent/me.

Canonical state:
  SQLite rows and JSON metadata remain canonical for structured collaboration
  state.

Narrative attachment:
  Markdown remains available for long reasoning, source review prose, runbooks,
  and selected page context.

Archive format:
  .tar.gz only.

External note-app compatibility:
  Do not add third-party note-app import/export compatibility.

Write rule:
  Direct database writes by agents are forbidden.
  Mutating operations must use existing KnowNet API routes and Rust commands.

Security rule:
  Public mode must not expose broad read access without an agent token or an
  existing authenticated actor.
```

## Phase Relationship

```txt
Phase 7:
  Created collaboration reviews, findings, implementation records, context
  bundles, and Review Inbox.

Phase 8:
  Hardened context export, parser rules, terminology, and seed state.

Phase 9:
  Adds the agent-facing read layer and write gateway rules needed for real
  external AI collaboration.
```

## Phase 9 Includes

```txt
Required in Phase 9, not deferred:
  GET /api/agent/me
  GET /api/agent/ping
  POST /api/collaboration/reviews?dry_run=true
  X-Token-Expires-In response header for expiring tokens
  GET /api/agents/tokens/{token_id}/events
  scope presets expanded into explicit scopes

Reason:
  Without these, external AI agents can connect but cannot reliably understand
  their own permissions, preview review imports, detect token expiry, or let the
  operator inspect what happened.
```

## Do Not Change

```txt
Do not:
  Hand out the SQLite database file.
  Allow direct database writes from an agent token.
  Create a second write workflow for reviews, findings, pages, or messages.
  Create a new admin/maintenance access path for agents.
  Change snapshot behavior.
  Add third-party note-app compatibility.
```

## Data Model

Add agent access records without replacing Phase 3 users/sessions.

```sql
CREATE TABLE agent_tokens (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  agent_model TEXT,
  purpose TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'agent_reader',
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  scopes TEXT NOT NULL DEFAULT '[]',
  max_pages_per_request INTEGER NOT NULL DEFAULT 20,
  max_chars_per_request INTEGER NOT NULL DEFAULT 60000,
  expires_at TEXT,
  revoked_at TEXT,
  last_used_at TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE agent_access_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_id TEXT,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  agent_name TEXT,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  request_id TEXT,
  status TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
```

Token storage rules:

```txt
Store only token_hash.
Show the raw token only once at creation time.
Use a long random token with at least 32 bytes of entropy.
Token prefix: kn_agent_
Hash: sha256(raw_token)
```

Allowed roles:

```txt
agent_reader:
  Read scoped agent APIs only.

agent_reviewer:
  Read scoped agent APIs.
  Submit reviews and findings through collaboration import APIs.

agent_contributor:
  Read scoped agent APIs.
  Submit messages and reviews through existing write APIs.

No agent role can:
  Access maintenance endpoints.
  Create snapshots or restore data.
  Manage users, sessions, or tokens.
  Delete pages.
```

## P9-001 Agent Token Management

Goal:

```txt
Create, revoke, rotate, and list scoped agent tokens.
```

API:

```txt
POST /api/agents/tokens
  admin/owner only.
  Creates a token and returns the raw token once.

GET /api/agents/tokens
  admin/owner only.
  Lists token metadata without token_hash.

POST /api/agents/tokens/{token_id}/revoke
  admin/owner only.
  Sets revoked_at and blocks future use.

POST /api/agents/tokens/{token_id}/rotate
  admin/owner only.
  Revokes old token and returns a new raw token once.

GET /api/agents/tokens/{token_id}/events
  admin/owner only.
  Lists sanitized access events for one token.
  Default limit 50, max 200, ordered by created_at DESC.
```

Done when:

```txt
Tokens are hashed at rest.
Revoked and expired tokens are rejected.
Token list never returns token_hash or raw token.
Audit events are recorded for create, revoke, and rotate.
Token event lookup never returns raw token, token_hash, page content, or secret
bearing request bodies.
```

## P9-002 Agent Authentication Dependency

Goal:

```txt
Authenticate external AI agents without creating a parallel user auth system.
```

Header:

```txt
Authorization: Bearer kn_agent_...
```

Rules:

```txt
Agent auth is separate from user sessions but maps to an Actor-like object:
  actor_type = ai
  actor_id = agent_tokens.id
  role = agent token role
  vault_id = agent token vault_id

Existing user auth remains unchanged.
Agent tokens cannot satisfy admin/owner dependencies.
When an authenticated agent token is close to expiry, agent responses include:
  X-Token-Expires-In: {seconds}
Only include the header when expires_at is set.
```

Done when:

```txt
Agent tokens work on /api/agent/*.
Agent tokens cannot call /api/maintenance/*.
Invalid, expired, or revoked tokens return 401.
Insufficient role or scope returns 403.
Responses include X-Token-Expires-In when the token has an expiry.
```

## P9-003 Scoped Read APIs

Goal:

```txt
Expose fast, AI-ready read APIs that are narrower than raw database access.
```

Endpoints:

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

Health endpoint:

```txt
GET /api/agent/ping
  No auth required.
  Returns only:
    { "ok": true, "version": "9.0" }
  Do not expose host paths, DB state, user state, token state, or health detail.
```

Self endpoint:

```txt
GET /api/agent/me
  Requires agent token.
  Returns:
    token_id
    label
    agent_name
    agent_model
    purpose
    role
    vault_id
    scopes
    scope_presets
    max_pages_per_request
    max_chars_per_request
    rate_limit summary
    expires_at
    expires_in_seconds
  Never returns raw token or token_hash.
```

Response shape:

```json
{
  "ok": true,
  "data": {},
  "meta": {
    "schema_version": 1,
    "vault_id": "local-default",
    "agent_scope": ["pages:read"],
    "truncated": false,
    "total_count": 12,
    "returned_count": 12,
    "generated_at": "2026-05-02T00:00:00Z"
  }
}
```

Rules:

```txt
Return JSON designed for AI parsing.
Do not include users, sessions, raw audit identity fields, backups, or local
filesystem internals.
Apply token scope before reading rows.
Apply limit and max_chars before returning content.
Return truncated=true when response is reduced.
```

Done when:

```txt
agent_reader can read scoped state.
Agent can call /api/agent/me to discover scopes and remaining limits.
Unauthenticated callers can call /api/agent/ping only.
agent_reader cannot read outside its vault or scope.
Response metadata clearly reports truncation.
The APIs do not expose forbidden tables or local secret-bearing paths.
```

## P9-004 Scope Model

Goal:

```txt
Limit each agent token to the exact context it needs.
```

Scope examples:

```txt
pages:read
pages:read:slug:knownet-overview
reviews:read
findings:read
graph:read
citations:read
messages:create
reviews:create
findings:create
```

Scope rules:

```txt
Scopes are stored as JSON array strings in agent_tokens.scopes.
An empty scope list means no access.
Scope checks are explicit per endpoint.
Wildcard scopes are not allowed in Phase 9.
Scope presets may be used at token creation time, but must be expanded into
explicit scope strings before storing the token.
```

Scope presets:

```txt
preset:reader:
  pages:read
  graph:read
  citations:read

preset:reviewer:
  reviews:read
  findings:read
  reviews:create

preset:contributor:
  reviews:read
  findings:read
  reviews:create
  messages:create
```

Done when:

```txt
Tests prove token scope limits pages, reviews, findings, graph, and write
gateway access.
Preset scopes expand to explicit scopes and do not create wildcard behavior.
Scope failures are auditable and return 403.
```

## P9-005 Write Gateway Reuse

Goal:

```txt
Let AI agents write useful artifacts without direct database writes.
```

Allowed write paths by role:

```txt
agent_reader:
  No writes.

agent_reviewer:
  POST /api/collaboration/reviews
  POST /api/collaboration/findings/{finding_id}/decision only when explicitly
  scoped.

agent_contributor:
  POST /api/messages
  POST /api/collaboration/reviews
  POST /api/collaboration/findings/{finding_id}/implementation only when
  explicitly scoped.
```

Rules:

```txt
Reuse existing validation, parser, audit, and Rust command flow.
Do not create agent-only duplicate write endpoints.
Tag agent-created records with:
  source_agent
  source_model
  token_id
  purpose
```

Dry-run:

```txt
POST /api/collaboration/reviews?dry_run=true
  Runs the Phase 7/8 review parser and validation.
  Returns parsed review metadata, finding count, parser warnings, and whether
  truncation would occur.
  Does not create collaboration_reviews, collaboration_findings, narrative
  attachments, graph nodes, or audit write-success events.
  Records a sanitized agent_access_events row with action=review.dry_run.
```

Done when:

```txt
Agent writes create normal KnowNet records.
Review dry-run previews parser output without writing canonical records.
Every agent write has an audit event.
Direct database writes are not introduced.
```

## P9-006 Context Budget And Rate Limits

Goal:

```txt
Prevent runaway agents from pulling excessive context or hammering local APIs.
```

Limits:

```txt
Per token:
  max_pages_per_request
  max_chars_per_request
  read requests per minute
  write requests per minute

Defaults:
  max_pages_per_request = 20
  max_chars_per_request = 60000
  read_requests_per_minute = 60
  write_requests_per_minute = 10
```

Behavior:

```txt
If content exceeds budget:
  Return truncated=true for reads when safe.
  Return 413 when a write body is too large.

If rate limit is exceeded:
  Return 429 with retry_after_seconds.
  Record agent_access_events with status=rate_limited.
```

Done when:

```txt
Tests cover read truncation, write body rejection, and rate limit 429.
```

## P9-007 Access Audit

Goal:

```txt
Make external AI access traceable without leaking sensitive request data.
```

Record:

```txt
agent_access_events:
  token_id
  vault_id
  agent_name
  action
  target_type
  target_id
  request_id
  status
  meta
  created_at
```

Meta rules:

```txt
Allowed:
  endpoint name
  returned_count
  truncated
  scope checks
  duration_ms

Forbidden:
  raw token
  token_hash
  secret-bearing request body
  full page content
```

Done when:

```txt
Successful reads, denied reads, writes, rate limits, and token failures produce
sanitized access events.
Admin/owner can inspect one token's access events through
GET /api/agents/tokens/{token_id}/events.
```

## P9-008 Public Mode Hardening

Goal:

```txt
Make external exposure practical without opening the whole app.
```

Rules:

```txt
PUBLIC_MODE=true:
  /api/agent/* requires a valid agent token.
  /api/pages and /api/collaboration broad reads require existing auth unless
  explicitly allowed by config.
  /api/maintenance/* remains admin/owner only and rejects agent tokens.

PUBLIC_MODE=false:
  Local user auth behavior remains unchanged.
```

Done when:

```txt
Public mode tests prove anonymous read is blocked, agent scoped read works, and
maintenance endpoints reject agent tokens.
```

## P9-009 Agent-Ready Documentation

Goal:

```txt
Give external AI agents a concise contract they can follow.
```

Create:

```txt
docs/AGENT_ACCESS_CONTRACT.md
```

Must include:

```txt
Authentication header.
Allowed endpoints.
Response schema.
Scope semantics.
Write gateway rules.
Finding format.
Context budget.
Forbidden data.
Example read flow.
Example review submission flow.
```

Done when:

```txt
The document is short enough for an AI agent to ingest quickly.
It contains no secrets, no local paths except endpoint paths, and no obsolete
product terminology.
```

## P9-010 Tests And Verification

Required tests:

```txt
API:
  Create/list/revoke/rotate agent token.
  List sanitized access events for one token.
  Raw token is shown once.
  Hashed token is never returned.
  /api/agent/ping returns only ok/version without auth.
  /api/agent/me returns token capability, scopes, limits, and expiry without
  raw token or token_hash.
  agent_reader can read scoped pages.
  agent_reader cannot write.
  agent_reviewer can submit review only with reviews:create scope.
  review dry-run returns parser output without creating records.
  preset scopes expand to explicit scopes.
  X-Token-Expires-In is present for expiring tokens.
  Scope outside page/vault returns 403.
  Public mode blocks anonymous read.
  Maintenance endpoints reject agent tokens.
  Rate limits return 429.
  Context budget returns truncated=true or 413 as appropriate.

Security:
  Agent APIs never return users, sessions, token_hash, raw token, backup paths,
  or secret-bearing fields.

Operations:
  verify-index checks agent token rows for invalid scope JSON and expired token
  cleanup candidates.
```

Completion checks:

```txt
API tests pass.
Rust tests pass.
Web build passes if UI changes are made.
Search confirms active docs do not mention removed compatibility paths or
archive formats beyond .tar.gz.
```

## Completion Definition

Phase 9 is complete when:

```txt
1. Admin/owner can create, list, revoke, and rotate scoped agent tokens.
2. External AI agents can inspect their own capabilities through
   /api/agent/me and read scoped state through /api/agent/*.
3. External AI agents cannot receive the raw database file or forbidden data.
4. Agent writes reuse existing KnowNet write APIs and Rust command flow, with
   review dry-run available before import.
5. Token scope, context budget, and rate limits are enforced.
6. Agent access is audited with sanitized metadata.
7. Admin/owner can inspect sanitized per-token access events.
8. Public mode blocks anonymous broad reads while allowing scoped agent reads.
9. Agent access contract documentation exists and matches the implemented API.
```

Phase 9 should make KnowNet usable by external AI agents without turning the
system into an open database or a second write platform.
