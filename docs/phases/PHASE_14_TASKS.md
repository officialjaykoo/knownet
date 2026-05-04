# Phase 14 Tasks: Agent Onboarding Contract

Phase 14 makes KnowNet understandable to a first-contact AI agent. Earlier
phases exposed pages, structured state, MCP, SDK, and dashboard surfaces. Phase
14 adds an adaptive entry path so an agent is told where to begin without being
blocked from making its own scoped decisions.

Implementation status: completed in the codebase.

Completed surface:

```txt
apps/api/knownet_api/routes/agent.py
  Adds the agent onboarding contract, exposes GET /api/agent/onboarding, and
  includes start_here_hint/start_here_status/recommended_start_pages in
  GET /api/agent/me.
  Generates allowed_actions/unavailable_actions from the current token scopes.

apps/api/knownet_api/services/system_pages.py
apps/api/knownet_api/db/schema.sql
apps/api/knownet_api/main.py
  Add the DB-owned system_pages classification, register the canonical
  onboarding pages, and expose lock helpers.

apps/api/knownet_api/routes/pages.py
apps/api/knownet_api/routes/suggestions.py
apps/api/knownet_api/routes/graph.py
  Block protected page writes with HTTP 423, expose system_kind/system_tier/
  system_locked on read surfaces, and add system metadata to graph nodes.

apps/mcp/knownet_mcp/server.py
  Adds knownet_start_here tool and knownet://agent/onboarding resource.
  Existing review prompts now tell agents to call knownet_start_here first.

packages/knownet-agent-py/knownet_agent/client.py
  Adds client.start_here() helper.

apps/web/components/GraphPanel.tsx
apps/web/app/globals.css
  Render tier 1 system nodes with soft pink and tier 2 managed nodes with soft
  green while preserving selected/pinned semantics.

apps/api/tests/test_phase9_agent_access.py
apps/mcp/tests/test_knownet_mcp.py
packages/knownet-agent-py/tests/test_client.py
  Cover the API, MCP, SDK onboarding entry points, dynamic action hints, locked
  page enforcement, read fields, and graph metadata.

docs cleanup note
  The old Phase 14 external AI access log and triage docs were consolidated
  after Phase 17. Current external-agent setup lives in docs/MCP_CLIENTS.md,
  and current release evidence lives in docs/RELEASE_EVIDENCE.md.
```

## Fixed Decisions

```txt
Onboarding is an API contract, not just prose.

GET /api/agent/me:
  Always includes start_here_hint, start_here_status, and
  recommended_start_pages.

GET /api/agent/onboarding:
  Requires a valid agent token.
  Does not require pages:read, because even a poorly scoped agent needs to know
  what it can and cannot do.
  Returns first-read pages, allowed actions, forbidden actions, review workflow,
  and current contribution priorities.

MCP:
  Exposes knownet_start_here.
  Exposes knownet://agent/onboarding resource.
  Prompts instruct agents to start there before review work.

SDK:
  Exposes client.start_here().

No persistent acknowledgement gate is added in Phase 14.
The product uses agent_access_events to infer whether the token has called the
start endpoint recently, then returns a soft hint instead of a requirement.

Page ownership tiers:
  Tier 1: system
    System-owned pages such as onboarding, policy, and contracts.
    Normal users and external agents cannot modify or delete locked tier 1
    pages.

  Tier 2: managed
    Admin/owner-managed project pages such as runbooks, architecture state, and
    curated seed pages. Phase 14 registers the twelve Phase 8 seed pages as
    managed so API and graph clients can distinguish them from ordinary pages.
    Managed pages are not locked in Phase 14.

  Tier 3: user
    Ordinary user/agent-authored pages governed by the existing permission
    model.

Onboarding pages are tier 1 system pages:
  They are not ordinary user/agent-authored pages.
  Their classification must not come from Markdown frontmatter or tags.
  External AI agents cannot create, reclassify, modify, or delete them.

Protected page classification:
  Stored in SQLite, not in page content.
  Proposed table: system_pages(page_id, kind, tier, locked, owner,
  description, registered_at_phase, created_at, updated_at).
  kind values for Phase 14 implementation: onboarding, managed.
  tier values: 1=system, 2=managed, 3=user.
  locked=true means ordinary write flows must reject mutation.

Phase 14 implementation scope:
  Implement tiers and schema now.
  Register only the five canonical onboarding pages as tier=1, kind=onboarding,
  locked=1.
  Register the twelve Phase 8 AI state seed pages as tier=2, kind=managed,
  locked=0.
  Do not lock all managed/seed/runbook pages in Phase 14.

Future candidates:
  AI Agent Access Contract may become tier=1 system later.
  Additional curated runbook/architecture pages beyond the twelve Phase 8 seed
  pages may become tier=2 managed later.
```

## Do Not Change

```txt
Do not:
  Add a new auth system.
  Add direct database access for external agents.
  Block read-only agent APIs behind an acknowledgement flag.
  Add dashboard analytics.
  Add remote agent execution.
  Add persistent onboarding acknowledgement in Phase 14.
  Treat Markdown tags or frontmatter as trusted system classification.
  Let external agent tokens create or modify protected system pages.
  Let suggestion apply overwrite protected system pages.
```

## P14-001 Onboarding Page Contract

Goal:

```txt
Define the first pages an external AI should read and return their availability
from API responses.
```

Canonical start pages:

```txt
start-here-for-external-ai-agents
what-knownet-is-and-is-not
external-ai-first-30-minutes
how-to-contribute-safely
current-priorities-for-ai-contributors
```

Each page item returns:

```txt
slug
title
required
reason
available
page_id when available
updated_at when available
```

Done when:

```txt
GET /api/agent/me and GET /api/agent/onboarding both expose the same start page
list and an adaptive start-here hint.
```

## P14-002 Agent Onboarding API

Goal:

```txt
Make first-contact guidance impossible to miss for API users.
```

Endpoint:

```txt
GET /api/agent/onboarding
```

Response includes:

```txt
start_here_hint: recommended | available
start_here_status
recommended_start_pages
allowed_actions
forbidden_actions
review_workflow
current_priorities
handoff_format
```

Rules:

```txt
Requires valid agent token.
Does not require a specific scope.
Records agent_access_event action agent.onboarding.
Uses prior agent.onboarding access events to decide whether onboarding is still
recommended as a first step.
Does not write page or review data.
```

Done when:

```txt
An agent with a valid token and no scopes can still learn what to request next.
```

## P14-003 MCP Start Tool And Resource

Goal:

```txt
Make MCP clients naturally start with onboarding.
```

Add:

```txt
tool: knownet_start_here
resource: knownet://agent/onboarding
```

Prompt rule:

```txt
Review prompts should say to call knownet_start_here before bounded page reads.
```

Done when:

```txt
tools/list and resources/list include onboarding, and knownet_start_here calls
GET /api/agent/onboarding.
```

## P14-004 SDK Start Helper

Goal:

```txt
Make script authors use the same entry point without remembering endpoint names.
```

Add:

```python
client.start_here()
```

Done when:

```txt
The SDK helper calls GET /api/agent/onboarding and returns a normal
KnowNetResponse.
```

## P14-005 Tests

Tests:

```txt
API:
  /api/agent/me includes start_here_hint and recommended_start_pages.
  /api/agent/onboarding works with a valid no-scope token.

MCP:
  knownet_start_here is registered and calls /api/agent/onboarding.
  onboarding resource reads /api/agent/onboarding.

SDK:
  client.start_here() calls /api/agent/onboarding.
```

## P14-006 System Page Classification

Goal:

```txt
Separate trusted protected page identity from editable page content.
```

Schema:

```sql
CREATE TABLE IF NOT EXISTS system_pages (
  page_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  tier INTEGER NOT NULL DEFAULT 1,
  locked INTEGER NOT NULL DEFAULT 1,
  owner TEXT NOT NULL DEFAULT 'system',
  description TEXT,
  registered_at_phase TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Rules:

```txt
Classification is DB-owned.
Do not trust Markdown tags, frontmatter, title, or slug alone.
Only owner/admin maintenance code may register or update system_pages rows.
Phase 14 registers the five canonical onboarding pages as kind='onboarding'.
Phase 14 documents tier=2 managed pages but does not enforce managed locks yet.
```

Done when:

```txt
The five onboarding page ids exist in system_pages with kind='onboarding' and
tier=1 and locked=1.
```

## P14-007 Protected System Page Writes

Goal:

```txt
Prevent accidental or agent-driven modification/deletion of core onboarding
pages.
```

Protected operations:

```txt
POST /api/pages with a protected slug
POST /api/suggestions/{id}/apply targeting a protected slug
POST /api/pages/{slug}/revisions/{revision_id}/restore for protected pages
DELETE /api/pages/{slug} for protected pages
POST /api/pages/{slug}/recover when it would affect a protected page
```

Allowed operations:

```txt
GET /api/pages/{slug}
GET /api/agent/onboarding
GET /api/agent/pages/{page_id} when scope allows
Maintenance/admin seed code that explicitly registers protected pages
```

Error:

```txt
system_page_locked:
  returned as HTTP 423 Locked with slug, page_id, kind, and tier details.
  Do not use HTTP 409 for locked system pages.
```

Done when:

```txt
Normal editor/admin/agent flows cannot overwrite, restore, tombstone, or recover
locked onboarding pages.
```

## P14-008 Read Surface Marking

Goal:

```txt
Let clients distinguish onboarding/system pages without trusting tags.
```

Read API additions:

```txt
GET /api/pages
GET /api/pages/{slug}
GET /api/agent/pages
GET /api/agent/pages/{page_id}
GET /api/agent/onboarding recommended_start_pages
```

Fields:

```txt
system_kind: onboarding | null
system_tier: 1 | 2 | 3 | null
system_locked: true | false
```

Done when:

```txt
UI, MCP, SDK, and external agents can tell that onboarding pages are protected
system pages using API fields, not Markdown tags.
```

## P14-009 Graph Visual Separation

Goal:

```txt
Make protected/managed knowledge nodes visually distinct without changing
selection or pin semantics.
```

Graph styling:

```txt
Tier 1 onboarding/system:
  soft pink node fill.

Tier 2 managed:
  soft green node fill.

Tier 3 user:
  existing normal node fill.

Selection:
  keep existing selected border.

Pin:
  keep existing pin icon.
```

Rules:

```txt
Do not use tag/frontmatter values to choose protected colors.
Use system_kind/system_tier/system_locked from API or graph node meta.
Keep colors subtle. Do not make protected colors visually louder than selected
state.
```

Done when:

```txt
Onboarding nodes are visibly distinct from normal user nodes, and selected/pinned
states remain readable.
```

## P14-010 Dynamic Agent Action Hints

Goal:

```txt
Make onboarding actions reflect the current token without creating a huge
endpoint catalog.
```

Response shape:

```txt
allowed_actions:
  small list of representative actions allowed by current scopes.

unavailable_actions:
  small list of useful actions not available, with required_scope and reason.
```

Rules:

```txt
Generate from the current token scopes.
Keep the list short and practical.
Do not include maintenance/admin actions as available for agent tokens.
Do not expose internal route lists that invite broad probing.
```

Done when:

```txt
An agent can tell whether it may read pages, read structured state, read reviews,
submit reviews, or create messages from the onboarding response.
```

## P14-011 Deferred Protection Scope

Goal:

```txt
Record what is intentionally not implemented in Phase 14 so later agents do not
guess.
```

Deferred:

```txt
AI Agent Access Contract as tier=1 system page.
Managed-page locking and admin-only editing workflow.
Deep recover-specific tests beyond the primary locked write paths.
```

Reason:

```txt
Phase 14 should protect the onboarding entry path first. Broader managed content
locking needs operator UX and migration decisions.
```

## Completion Definition

Phase 14 is complete when:

```txt
1. First-contact agent guidance is exposed through API, MCP, and SDK.
2. The guidance is available even before an agent has useful read scopes.
3. Existing agent access security remains unchanged.
4. Onboarding pages are registered as locked system pages in SQLite.
5. The twelve Phase 8 seed pages are registered as managed pages in SQLite.
6. Normal write/delete/restore/apply flows cannot mutate locked system pages.
7. Read APIs expose system_kind, system_tier, and system_locked.
8. Graph API/meta enables soft pink onboarding/system nodes and soft green
   managed nodes while preserving existing selected/pinned states.
9. Onboarding action hints are generated from current token scopes.
10. Tests cover the new entry points, lock enforcement, read fields, graph meta,
   and dynamic action hints.
```
