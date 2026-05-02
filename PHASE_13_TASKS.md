# Phase 13 Tasks: Agent Dashboard UX And Operations

Phase 13 turns the simple Agent Access panel into an operator-grade dashboard
for managing external AI agents, tokens, scopes, and recent activity.

Implementation status: pending.

Phase 13 is Dashboard-only. MCP was hardened in Phase 11. The Python SDK was
hardened in Phase 12.

## Fixed Decisions

```txt
Phase 9 remains the source of truth:
  Agent tokens, scopes, roles, context budgets, and access events remain
  authoritative in the existing API.

Phase 10 remains valid:
  The dashboard uses existing /api/agents/* endpoints.
  Raw tokens are shown once after create or rotate.

Phase 11/12 remain valid:
  MCP and SDK are separate integration surfaces.
  Dashboard should help operate those surfaces, not reimplement them.

Dashboard:
  Lives in apps/web/.
  Uses existing owner/admin auth.
  Uses existing AgentAccessPanel as the starting point.
  Does not create a new token system.
```

## Do Not Change

```txt
Do not:
  Add direct database access from the web UI.
  Add new auth or token models.
  Add MCP tools from the dashboard.
  Add SDK execution from the dashboard.
  Add remote shell or agent execution.
  Add analytics-heavy charts in Phase 13.
  Expose raw tokens outside the one-time display after create/rotate.
```

## Implementation Order

```txt
1. P13-001 Dashboard Information Architecture
2. P13-002 Token List And Filters
3. P13-003 Token Detail View
4. P13-004 Create And Rotate Workflows
5. P13-005 Activity Events And Failure Triage
6. P13-006 Health And Expiry Signals
7. P13-007 UX Polish And Accessibility
8. P13-008 UI Tests
9. P13-009 Documentation And Runbook Updates
```

## P13-001 Dashboard Information Architecture

Goal:

```txt
Make Agent Access feel like an operations screen, not a small form embedded in a
busy page.
```

UI structure:

```txt
Agent Access section:
  Summary row
  Token list
  Token detail
  Create/rotate panel
  Activity/event panel
```

Summary row:

```txt
active tokens
expiring tokens
revoked tokens
recent denied events
recent rate-limited events
```

Rules:

```txt
Keep the UI dense and operational.
Do not make a marketing-style hero section.
Do not add charts unless a simple count/chip is insufficient.
```

Done when:

```txt
Owner/admin can understand token health and recent failures without scrolling
through raw event rows first.
```

## P13-002 Token List And Filters

Goal:

```txt
Make token inventory scannable and searchable.
```

Add filters:

```txt
status: all | active | expiring | expired | revoked
role: all | agent_reader | agent_reviewer | agent_contributor
scope preset or scope text
agent name text search
```

List columns:

```txt
status
label
agent_name
agent_model
role
scope count
expires_at
last_used_at
```

Rules:

```txt
Default sort: active first, then expiring, then last_used_at desc.
Revoked tokens stay visible but visually subdued.
Long labels and scopes must not break layout.
```

Done when:

```txt
Tests cover token filtering, status calculation, and stable rendering with long
labels/scopes.
```

## P13-003 Token Detail View

Goal:

```txt
Show enough token detail to debug agent access without exposing secrets.
```

Detail fields:

```txt
label
agent_name
agent_model
purpose
role
vault_id
scopes
max_pages_per_request
max_chars_per_request
expires_at
last_used_at
created_at
updated_at
revoked_at
```

Detail actions:

```txt
copy safe token id
rotate
revoke
refresh events
```

Rules:

```txt
Do not show token_hash.
Do not show raw token except immediately after create/rotate.
Confirm revoke and rotate actions.
Disable actions for revoked tokens where appropriate.
```

Done when:

```txt
Operator can inspect a token and decide whether to rotate, revoke, or change
scope without needing API docs.
```

## P13-004 Create And Rotate Workflows

Goal:

```txt
Make token creation safe and hard to misconfigure.
```

Create token form:

```txt
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
```

UX rules:

```txt
Show preset scope explanation before submit.
Validate explicit scopes before API call.
Convert datetime-local to API-safe UTC ISO.
Show raw token once in a dedicated copy panel.
Require explicit dismissal of raw token panel.
Show "store this in your MCP/SDK environment" instruction.
```

Rotate flow:

```txt
Confirm rotation.
Show new raw token once.
Explain old token has been revoked.
Do not refresh away raw token before dismissal.
```

Done when:

```txt
Tests cover create payload normalization, one-time raw token display, and rotate
confirmation behavior.
```

## P13-005 Activity Events And Failure Triage

Goal:

```txt
Make denied/rate-limited/failing agent calls easy to investigate.
```

Event view:

```txt
status
action
target_type
target_id
created_at
request_id if present
sanitized meta
```

Filters:

```txt
all
denied
rate_limited
errors
last 15 minutes
last hour
last day
```

Rules:

```txt
Sanitize token, secret, password, key, authorization, and content-like fields.
Show required/current scopes when present.
Show retry_after_seconds when present.
Do not show raw request bodies.
```

Done when:

```txt
An operator can answer "why did this agent fail?" from the dashboard.
```

## P13-006 Health And Expiry Signals

Goal:

```txt
Surface operational warnings before agents fail.
```

Signals:

```txt
token expires within 7 days
token expired
token revoked
token has no scopes
token unused for 30 days
recent scope_denied events
recent rate_limited events
```

Rules:

```txt
Warnings should be chips/badges near the token, not a separate chart.
Do not block token use from the UI; the backend remains authoritative.
```

Done when:

```txt
Expiring and failing tokens are visible without opening every token detail.
```

## P13-007 UX Polish And Accessibility

Goal:

```txt
Make the dashboard easier to use for repeated operations.
```

Polish:

```txt
Use icons for create, refresh, copy, rotate, revoke, filters, and warnings.
Use clear empty states.
Use stable table/list row heights.
Use keyboard-focus visible states.
Use aria-label for icon-only buttons.
Keep text inside buttons and chips from wrapping badly.
```

Visual rules:

```txt
Operational UI, compact and readable.
No nested cards.
No decorative background effects.
No oversized headings inside the dashboard.
```

Done when:

```txt
The dashboard is usable at desktop and narrow widths without overlapping text.
```

## P13-008 UI Tests

Goal:

```txt
Protect the dashboard workflows that can leak or lose raw token values.
```

Tests:

```txt
agentAccess helper tests:
  status calculation
  filters
  payload normalization
  event metadata sanitization
  expiry warning calculation

component-level or DOM tests if available:
  raw token appears after create
  raw token disappears after dismissal
  revoked tokens show disabled actions
  event filters work
```

Rules:

```txt
Do not add a large frontend test framework unless already needed.
If staying with node --test helper tests, extract pure helpers from the component
so behavior remains testable.
```

Done when:

```txt
npm run test:agent covers the critical dashboard behavior.
```

## P13-009 Documentation And Runbook Updates

Update:

```txt
docs/RUNBOOK.md
docs/AGENT_ACCESS_CONTRACT.md
README.md if needed
```

Document:

```txt
Token creation workflow
Raw token one-time display
Rotation workflow
Revocation workflow
How to interpret denied/rate-limited events
When to rotate expiring tokens
MCP/SDK environment update after rotate
```

Done when:

```txt
An operator can create, rotate, revoke, and troubleshoot an agent token using
the dashboard without reading source code.
```

## Required Verification

Run:

```powershell
cd apps/web; npm run test:agent
cd apps/web; npm run build
cd apps/web; npm audit --audit-level=moderate
apps/api/.venv/Scripts/python.exe -m pytest apps/api/tests -q
$env:PYTHONPATH='apps/mcp'; apps/api/.venv/Scripts/python.exe -m pytest apps/mcp/tests -q
$env:PYTHONPATH='packages/knownet-agent-py'; apps/api/.venv/Scripts/python.exe -m pytest packages/knownet-agent-py/tests -q
cd apps/core; cargo test
```

Also check:

```powershell
rg -n "token_hash|Authorization|password|secret" apps/web/components/AgentAccessPanel.tsx apps/web/lib
```

Expected result:

```txt
No dashboard-rendered field exposes token hashes, authorization headers, raw
passwords, or secrets. Raw agent tokens appear only in the one-time create/rotate
copy panel.
```

## Completion Definition

Phase 13 is complete when:

```txt
1. Agent Access dashboard has a clear operations layout.
2. Token list supports useful filters and status sorting.
3. Token detail shows safe operational metadata and actions.
4. Create/rotate flows preserve one-time raw token safety.
5. Events are sanitized and useful for failure triage.
6. Expiry/failure warnings are visible before agents fail.
7. Dashboard helper tests cover critical behavior.
8. Docs explain the dashboard workflows.
9. Existing API, MCP, SDK, Rust, and web checks still pass.
```

Phase 13 should make external AI agent operations easier for the human operator.
It must not make token secrets easier to leak.
