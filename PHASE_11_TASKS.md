# Phase 11 Tasks: MCP Hardening And Agent Runtime Compatibility

Phase 11 turns the Phase 10 MCP adapter into a stricter, easier-to-operate MCP
server for real AI clients.

Implementation status: completed in the codebase.

Implemented surface:

```txt
P11-001:
  Strict JSON-RPC handling for tools, resources, prompts, malformed requests,
  graceful shutdown, and stdio-safe parse errors.

P11-002:
  Tool input schemas with additionalProperties=false, min/max bounds, enums,
  required fields, defaults, and validation before HTTP calls.

P11-003:
  Safe resources for agent me, state summary, pages, reviews, findings, graph,
  and citations.

P11-004:
  Safe reusable prompts for page review, finding review, and external review
  preparation.

P11-005:
  limit/offset pagination support in Phase 9 agent list APIs and MCP
  next_offset metadata.

P11-006:
  Secret-safe structured logs to stderr with stdout reserved for JSON-RPC.

P11-007:
  Client setup examples in docs/MCP_CLIENTS.md.

P11-008:
  MCP end-to-end test against a real local KnowNet API server.

P11-009:
  README, agent access contract, and runbook updates.

P11 operational hardening:
  Startup diagnostics, graceful shutdown wait, token expiry warnings,
  per-call request_id metadata, result size warnings, and scope-denied hints.
```

Phase 11 is not a new product surface. It is a compatibility and reliability
phase for the MCP server only.

## Fixed Decisions

```txt
Phase 9 remains the source of truth:
  /api/agent/* is the scoped read layer.
  Existing KnowNet APIs remain the write gateway.
  Agent tokens, scopes, context budgets, and access events remain authoritative.

Phase 10 remains valid:
  Python SDK stays small.
  Dashboard stays simple.
  MCP continues to use stdio first.

MCP server:
  Lives under apps/mcp/.
  Does not read SQLite directly.
  Does not bypass scopes.
  Does not expose maintenance, backup, restore, migration, shell, or admin tools.
  Does not return raw tokens or token hashes.

Archive format:
  .tar.gz only where archives are relevant.
```

## Do Not Change

```txt
Do not:
  Add direct database access to MCP.
  Add remote agent execution.
  Add shell command execution.
  Add maintenance operations to MCP tools.
  Add another token system.
  Expand Dashboard into analytics.
  Rebuild the Python SDK as part of this phase.
  Reintroduce external note-app compatibility.
```

## Allowed MCP Capability Surface

Tools remain limited to agent-safe operations:

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

Phase 11 may add resources and prompts, but they must map to the same safe
agent-access surface.

## Implementation Order

Implement in this order:

```txt
1. P11-001 MCP Protocol Compatibility
2. P11-002 Tool Input Schemas
3. P11-005 Pagination Convenience
4. P11-003 Resources
5. P11-004 Prompts
6. P11-006 Configuration And Structured Logs
7. P11-008 End-To-End MCP Test
8. P11-007 Client Connection Examples
9. P11-009 Documentation Updates
```

Do not start prompts before tools/resources are stable. Prompts are instructions
for other AI agents, so their wording must follow the safe scoped workflow.

Allowed resources:

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

Allowed prompts:

```txt
knownet_review_page
knownet_review_findings
knownet_prepare_external_review
```

Prompt rules:

```txt
Prompts provide instructions and scoped context only.
Prompts must not ask the model to reveal secrets.
Prompts must not include raw database files, sessions, users, backups, or token
metadata.
Prompts must tell the agent to submit findings through dry-run before final
review import.
```

## P11-001 MCP Protocol Compatibility

Goal:

```txt
Make the MCP server behave predictably with common stdio MCP clients.
```

Implementation guidance:

```txt
Prefer the official MCP Python package if it can be added cleanly under
apps/mcp/. If not, keep the stdlib server but make the JSON-RPC compatibility
tests strict.

The implementation must support:
  initialize
  notifications/initialized
  tools/list
  tools/call
  resources/list
  resources/read
  prompts/list
  prompts/get
```

Process behavior:

```txt
Handle SIGTERM and SIGINT gracefully.
On shutdown, stop reading stdin, allow the current in-flight request to finish,
wait up to 10 seconds for active requests, flush stderr logs, and exit without
writing partial JSON to stdout.
EOF on stdin exits cleanly with status 0.
```

Startup diagnostics:

```txt
initialize runs an MCP self-check:
  - KnowNet API ping is reachable.
  - Agent token is present and valid.
  - Token scopes are not empty.
  - Token expiry is inspected.

If token expiry is within 7 days, diagnostics returns token_warning:
  expires_soon

Diagnostics are returned in initialize.result.diagnostics and logged to stderr.
```

Response rules:

```txt
Every JSON-RPC response includes jsonrpc="2.0".
Parse errors return -32700.
Invalid requests return -32600.
Unknown methods return -32601.
Invalid params return -32602.
Tool execution failures return a tool result with isError=true, not a malformed
JSON-RPC response.
Tool/resource results include meta.request_id for operator troubleshooting.
```

Done when:

```txt
Strict JSON-RPC tests cover malformed JSON, invalid params, unknown methods,
tool errors, resources, and prompts.
```

## P11-002 Tool Input Schemas

Goal:

```txt
Make tool contracts precise enough that AI clients can call them safely.
```

Schema rules:

```txt
All tool schemas define:
  type
  properties
  required where applicable
  additionalProperties=false

Numeric fields define minimum and maximum.
String fields define minLength and maxLength where useful.
Enum fields are explicit.
```

Tool schema specifics:

```txt
knownet_list_pages:
  limit: integer, default 20, min 1, max 200
  offset: integer, default 0, min 0

knownet_read_page:
  page_id: string, required, minLength 1, maxLength 160

knownet_list_reviews:
  limit: integer, default 50, min 1, max 200
  offset: integer, default 0, min 0

knownet_list_findings:
  limit: integer, default 100, min 1, max 200
  offset: integer, default 0, min 0
  status: optional string enum accepted | rejected | deferred | needs_more_context

knownet_graph_summary:
  limit: integer, default 200, min 1, max 1000

knownet_list_citations:
  limit: integer, default 100, min 1, max 200
  offset: integer, default 0, min 0
  status: optional string

knownet_review_dry_run / knownet_submit_review:
  markdown: string, required, minLength 1, maxLength 262144
  source_agent: optional string, maxLength 120
  source_model: optional string, maxLength 120
```

Done when:

```txt
Invalid tool inputs are rejected before HTTP calls.
Tests prove unknown properties, over-limit values, missing required values, and
bad enums fail with invalid_tool_input.
```

## P11-003 Resources

Goal:

```txt
Expose safe read-only KnowNet state as MCP resources.
```

Resource rules:

```txt
Resources call the same Phase 9 endpoints as tools.
Resources preserve truncation metadata.
Resources never include raw token values, token hashes, sessions, users,
backups, or maintenance controls.
Resource read failures return MCP-safe errors with short messages.
403 scope errors include the required scope and current known scopes when
available.
```

Resource output:

```txt
Return application/json content for structured resources.
For page content, include both page metadata and latest content in JSON.
```

Done when:

```txt
resources/list returns only allowed resources.
resources/read works for me, state-summary, pages, one page, reviews, findings,
graph, and citations.
```

## P11-004 Prompts

Goal:

```txt
Give MCP clients reusable prompt templates for external review workflows.
```

Prompts:

```txt
knownet_review_page:
  Inputs: page_id
  Purpose: review one page and return findings in the fixed finding format.

knownet_review_findings:
  Inputs: status optional
  Purpose: review existing findings and suggest accept/reject/defer decisions.

knownet_prepare_external_review:
  Inputs: focus optional, max_pages optional
  Purpose: guide an external AI through context discovery, dry-run, and final
  review submission.
```

Prompt content rules:

```txt
Always include the fixed finding format.
Always recommend knownet_review_dry_run before knownet_submit_review.
Never include secret-bearing data.
Never instruct the AI to request raw database files.
Never mention actual token values.
Never mention local database paths.
Never mention maintenance endpoints.
Never instruct the AI to submit a final review without a dry-run first.
Never ask the AI to read every page at once; use bounded list/read calls.
```

Done when:

```txt
prompts/list and prompts/get are covered by tests.
Prompt output contains the finding format and safe workflow instructions.
```

## P11-005 Pagination Convenience

Goal:

```txt
Make large reads easier for agents without increasing context risk.
```

Rules:

```txt
Do not remove Phase 9 context budgets.
Do not add unbounded reads.
Every list tool/resource supports limit and offset when the backing API
supports it.
When the backing API does not support offset yet, return a clear unsupported
metadata field and keep existing behavior.
```

Response metadata:

```json
{
  "truncated": true,
  "total_count": 120,
  "returned_count": 20,
  "next_offset": 20,
  "request_id": "req_abc123",
  "chars_returned": 60000,
  "warning": "page_truncated_use_narrower_reads"
}
```

Token expiry metadata:

```json
{
  "token_expires_in_seconds": 86400,
  "token_warning": "expires_soon"
}
```

Done when:

```txt
List responses include next_offset when more data exists.
Tests cover truncated and non-truncated responses.
```

## P11-006 Configuration And Structured Logs

Goal:

```txt
Make MCP operation easier to debug without leaking secrets.
```

Configuration:

```txt
KNOWNET_BASE_URL
KNOWNET_AGENT_TOKEN
KNOWNET_MCP_TIMEOUT_SECONDS
KNOWNET_MCP_LOG_LEVEL
KNOWNET_MCP_LOG_FORMAT=json | text
```

Logging rules:

```txt
Logs go to stderr only.
stdio JSON-RPC responses go to stdout only.
Never log Authorization headers.
Never log raw token values.
Never log full review Markdown bodies.
Log request_id, method, tool/resource/prompt name, status, duration_ms, and
error_code.
```

Done when:

```txt
Tests prove logs use stderr and redact token-looking values.
```

## P11-007 Client Connection Examples

Goal:

```txt
Document practical setup for common MCP clients.
```

Add:

```txt
docs/MCP_CLIENTS.md
```

Include:

```txt
Claude Desktop stdio example
Cursor stdio example
Codex/local agent stdio example
Environment variable setup
Token rotation note
Troubleshooting for auth_failed, scope_denied, context_too_large, rate_limited
```

Rules:

```txt
Examples must use placeholder tokens only.
Examples must not include real local secrets.
Examples must not recommend public exposure without Cloudflare Access or an
equivalent protection layer.
```

Done when:

```txt
The document lets an operator connect one local MCP client without reading the
source code.
```

## P11-008 End-To-End MCP Test

Goal:

```txt
Prove the MCP server can talk to a running KnowNet API through the real HTTP
surface.
```

Test shape:

```txt
Start FastAPI TestClient or a local test server.
Create an agent token through the existing admin API.
Start the MCP server in-process or as a subprocess.
Call initialize, tools/list, knownet_me, knownet_list_pages,
knownet_review_dry_run, resources/list, resources/read, prompts/list.
Assert no raw token or token_hash appears in MCP responses.
```

Done when:

```txt
The E2E test runs in CI/local pytest without requiring a real external MCP
client.
```

## P11-009 Documentation Updates

Update:

```txt
docs/AGENT_ACCESS_CONTRACT.md:
  Add Phase 11 MCP resources and prompts.

README.md:
  Mention that MCP is the preferred integration path for MCP-capable AI tools.

docs/RUNBOOK.md:
  Add MCP log troubleshooting and token rotation checks.
```

Completion checks:

```txt
Docs do not mention unsupported archive formats.
Docs do not mention external note-app compatibility.
Docs do not include real tokens.
```

## Required Verification

Run:

```powershell
$env:PYTHONPATH='apps/mcp'; apps/api/.venv/Scripts/python.exe -m pytest apps/mcp/tests -q
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests -q
cd apps/core; cargo test
cd ../web; npm run build
cd ../web; npm audit --audit-level=moderate
```

Also run:

```powershell
rg -n "token_hash|raw_token|/api/maintenance|knownet.db|backups" apps/mcp docs/MCP_CLIENTS.md
```

Expected result:

```txt
No MCP response path, resource, prompt, or example exposes forbidden data or
maintenance controls.
```

## Completion Definition

Phase 11 is complete when:

```txt
1. MCP JSON-RPC handling is protocol-strict enough for common stdio clients.
2. Tool input schemas are precise and validated before HTTP calls.
3. Safe resources and prompts are available.
4. Pagination metadata helps agents continue bounded reads.
5. MCP logs are structured and secret-safe.
6. Client setup docs exist for common local MCP clients.
7. An end-to-end MCP test proves real HTTP integration.
8. Existing Phase 9 and Phase 10 tests still pass.
```

Phase 11 should make MCP more dependable. It must not make KnowNet more
powerful in ways that bypass the existing scoped API model.
