# KnowNet Phase 3 Tasks

## Phase 3 Closure - 2026-05-02

Status: implementation closed for the Phase 3 MVP.

Phase 3 moved KnowNet from a local-owner-only AI knowledge base into a controlled
multi-actor vault system. The implementation now includes local
username/password bootstrap/login, opaque SQLite-backed sessions, actor/role
resolution, vault membership checks, anonymous submission review, recoverable
tombstones, and a minimal vault-aware UI.

Implemented coverage:

```txt
local username/password bootstrap and login
opaque bearer sessions stored in SQLite
default local-default vault migration
vault creation and membership assignment through Rust daemon commands
x-knownet-vault request scoping for session actors
FastAPI Depends() permission checks for writer/reviewer/admin paths
anonymous public messages stored as pending_review submissions without AI jobs
reviewer approve/reject flow for submissions
approved submissions queue the normal Phase 2 draft job
page delete implemented as tombstone, not hard delete
page recover endpoint restores tombstoned Markdown
audit_log entries mirrored into Phase 3 audit_events
web login/logout/bootstrap controls
web actor/role display
web vault selector and vault creation control
web review queue for anonymous submissions
```

Verified implementation coverage:

```txt
22 API tests passing
Rust core cargo build passing
web production build passing
health endpoint reports default_vault_id=local-default
```

Phase 3.1 carryovers that do not block Phase 4:

```txt
full per-vault content directory isolation beyond SQLite vault_id metadata
member invitation UI and user creation beyond owner bootstrap
audit detail screen and advanced audit filters
CSRF protection if cookie-based sessions are introduced
external OAuth/SSO adapter
real multi-user deployment hardening
```

Decision: move to Phase 4 after Phase 3 MVP, with citation audit deepening as
the next major development axis.

Phase 3 goal: turn KnowNet from a local-owner AI knowledge base into a controlled
multi-actor/team vault system while keeping Markdown as the source of truth.

Phase 2 closed the core AI knowledge base loop. Phase 3 now focuses on identity,
permissions, actor traceability, and safe collaboration.

## Phase 3 Fixed Decisions

These choices are fixed before implementation so the agent does not invent
architecture while coding.

```txt
Authentication: local username/password login with opaque bearer session tokens.
Session storage: SQLite sessions table, written only through the Rust daemon.
Stateless JWT: not used in Phase 3 because revocation/logout must stay simple.
External OAuth/SSO: out of scope, but the auth service should keep a small adapter boundary.
Default vault ID: local-default
Default vault name: Local
Existing Markdown frontmatter: do not add vault_id during migration.
Permission checks: FastAPI Depends() dependencies, not global middleware.
Write rule: all Phase 3 SQLite writes go through Rust daemon commands.
```

## Phase 3 Principles

```txt
Markdown remains the recoverable source of truth.
SQLite remains metadata, index, audit, and workflow state.
No user or AI write is untracked.
Anonymous/public submissions may be accepted, but they do not directly mutate trusted pages.
Hard delete is not the default; delete-like actions produce tombstones or recoverable revisions.
AI actors are recorded separately by provider, model, version/config, and operation.
```

## Phase 3 SQLite Schema Baseline

The exact migration may add columns conditionally, but the data model must begin
from these tables and fields.

```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer',
  created_at TEXT NOT NULL
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  actor_type TEXT NOT NULL,
  session_meta TEXT,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE ai_actors (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  config_hash TEXT,
  operation_type TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE vaults (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE vault_members (
  vault_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (vault_id, user_id)
);

CREATE TABLE submissions (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  session_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending_review',
  reviewed_by TEXT,
  review_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vault_id TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  request_id TEXT,
  meta TEXT,
  created_at TEXT NOT NULL
);
```

Required status and actor values:

```txt
actor_type: user | anonymous | ai | admin_token
submission.status: pending_review | approved | rejected | queued
page.status: active | tombstone
```

Existing Phase 2 tables that represent vault-scoped state must receive
`vault_id TEXT NOT NULL DEFAULT 'local-default'` during migration:

```txt
pages
revisions
messages
jobs
suggestions
sources
audit_log or replacement audit_events
```

## Rust Daemon Commands

Phase 3 must not add direct FastAPI SQLite writes. Add or extend Rust daemon
commands for every new mutation.

```txt
create_user
create_session
revoke_session
create_vault
assign_vault_member
record_audit_event
tombstone_page
recover_page
create_submission
update_submission_status
run_phase3_migration
```

## Completion Criteria

```txt
Users can authenticate or operate as a clearly tracked anonymous actor.
Every mutating API endpoint enforces actor and permission checks.
Team vaults can separate content, permissions, audit logs, and review queues.
Roles support owner/admin/editor/reviewer/viewer behavior.
Anonymous submissions go into a review workflow before they affect canonical Markdown.
Audit events identify human user, anonymous/session actor, or AI actor.
Security tests cover unauthorized writes, cross-vault access, role denial, and approved writes.
The UI exposes login/session state, vault selection, and review workflow basics.
```

## P3-001 Identity and Actor Model

Goal:

```txt
Define who is acting before any write reaches the page.
```

Tasks:

```txt
Add users table or equivalent identity records.
Add sessions/tokens suitable for local-first development.
Keep ADMIN_TOKEN as emergency/local bootstrap, not the long-term user model.
Represent anonymous actors with session IDs and request metadata.
Represent AI actors with provider, model, version/config, and operation type.
```

Implementation notes:

```txt
Use username/password login with password_hash storage.
Issue an opaque bearer session token stored in SQLite sessions.
Do not use stateless JWT in Phase 3.
Anonymous sessions may have user_id = NULL and actor_type = 'anonymous'.
AI operations must create or resolve an ai_actors row before writing audit events.
```

Done when:

```txt
Every write can resolve actor_type and actor_id.
Audit rows no longer need to guess whether the actor was human, anonymous, admin token, or AI.
```

## P3-002 Vault Model

Goal:

```txt
Separate personal and team knowledge spaces while preserving page storage.
```

Tasks:

```txt
Add vault records and stable vault IDs.
Associate pages, sources, suggestions, revisions, snapshots, jobs, and audit events with a vault.
Define the default local vault migration path.
Prevent cross-vault reads/writes unless the actor has access.
```

Migration strategy:

```txt
1. Run knownet migrate --phase3.
2. Create a database backup before any schema mutation.
3. Create vault record id='local-default', name='Local'.
4. Add vault_id columns to pages, revisions, messages, jobs, suggestions, sources, and audit state.
5. Backfill every existing row with vault_id='local-default'.
6. Do not add vault_id to existing Markdown frontmatter.
7. Perform migration through the Rust daemon.
8. Roll back on failure and preserve the original knownet.db backup.
```

Done when:

```txt
Existing local data migrates into one default vault.
API routes can enforce vault scope consistently.
```

## P3-003 Permissions and Roles

Goal:

```txt
Make write access explicit instead of relying only on local-only assumptions.
```

Initial roles:

```txt
owner: full vault control and recovery actions
admin: manage members/settings and run maintenance
editor: create pages, apply suggestions, import/export allowed when enabled
reviewer: review/reject/approve submissions and suggestions
viewer: read/search/export only when allowed
anonymous: submit only, no canonical writes
```

Tasks:

```txt
Add role assignments per vault.
Create a central permission check helper for API routes.
Map existing mutating routes to required permissions.
Return consistent 401/403 errors.
```

Implementation notes:

```txt
Use FastAPI Depends() dependencies for route permission checks.
Do not use global middleware for authorization decisions.
Separate vault access checks from role permission checks.
Step 1: verify the actor belongs to or can access the vault.
Step 2: verify the actor's role allows the requested action.
Attach Depends(require_owner/admin/editor/reviewer/viewer) to every mutating route.
```

Done when:

```txt
Tests prove each role can do only its intended actions.
```

## P3-004 Public Submission and Review Queue

Goal:

```txt
Allow open writing without losing traceability or canonical page control.
```

Tasks:

```txt
Route anonymous/public notes into submissions or suggestions.
Record session/IP hash/user agent summary where appropriate.
Require reviewer/editor approval before canonical Markdown changes.
Show submission status and rejection reason.
```

Message flow:

```txt
Anonymous actor POST /api/messages:
- create inbox/message record with status='pending_review'
- do not create an AI draft job
- create submissions row
- wait for reviewer approval

Reviewer approval:
- update submission status to 'approved' then 'queued'
- create the normal Phase 2 AI draft job
- record audit event for approval and queue transition

Authenticated editor/admin/owner POST /api/messages:
- keep Phase 2 behavior
- create message and AI draft job immediately
- record actor and vault in audit events
```

Done when:

```txt
Anonymous users can contribute, but cannot directly alter trusted pages.
Maintainers can trace who or what submitted each item.
```

## P3-005 Audit and Recovery Hardening

Goal:

```txt
Make destructive or high-risk operations recoverable and attributable.
```

Tasks:

```txt
Add tombstone/recover flow for page delete.
Require elevated permission for import, restore, snapshot, and delete-like actions.
Attach actor, vault, request ID, and target IDs to audit rows.
Add audit filters by vault, actor, action, and time.
```

Tombstone behavior:

```txt
Page delete is not a physical delete in Phase 3.
Set pages.status='tombstone'.
Move the Markdown file from data/pages/ to data/revisions/{slug}/tombstone-{timestamp}.md.
Recover with POST /api/pages/{slug}/recover.
Direct permanent deletion of Markdown files is not a Phase 3 operation.
```

Audit actions should use stable dotted names:

```txt
page.create
page.tombstone
page.recover
revision.restore
suggestion.apply
suggestion.reject
submission.create
submission.approve
submission.reject
vault.member.assign
maintenance.snapshot
obsidian.import
obsidian.export
```

Done when:

```txt
A mistaken or malicious write can be traced and recovered without manually editing the database.
```

## P3-006 UI Foundations

Goal:

```txt
Expose the new security model without turning the app into an admin console.
```

Tasks:

```txt
Add login/session state.
Add vault selector.
Show current actor and role in a compact header area.
Add review queue for submissions/suggestions.
Disable or hide actions the actor cannot perform.
Show audit detail for revisions and suggestions.
```

Priority:

```txt
1. Login/logout screen - required.
2. Current actor/role in the header - required.
3. Disable unauthorized actions - required.
4. Vault selector - simple single-vault UI until team vaults are active.
5. Review queue - required once anonymous submissions are enabled.
6. Audit detail - useful but can land late in Phase 3.
```

Done when:

```txt
A user can understand what vault they are in, what they can do, and what needs review.
```

## P3-007 Tests and Migration

Goal:

```txt
Protect Phase 2 behavior while adding identity and vault boundaries.
```

Tasks:

```txt
Add migration tests for existing local data.
Add unauthorized/forbidden tests for every mutating route.
Add cross-vault isolation tests.
Add anonymous submission tests.
Add AI actor audit tests.
Keep Phase 2 draft/search/citation/import/export tests passing.
```

Migration test scenario:

```txt
1. Prepare a Phase 2 knownet.db fixture.
2. Run knownet migrate --phase3.
3. Verify every existing page has vault_id='local-default'.
4. Verify revisions/messages/jobs/suggestions/sources are backfilled.
5. Verify existing API calls still work when no vault_id is supplied.
6. Simulate migration failure and confirm the original db is preserved.
7. Verify Markdown files and frontmatter were not rewritten only to add vault_id.
```

Done when:

```txt
Phase 3 can be enabled without regressing the Phase 2 AI knowledge base loop.
```

## Out of Scope

```txt
Billing and paid organization management
Real-time collaborative editing
External SSO/OAuth provider integrations beyond a small adapter boundary
Graph database migration
Full mobile app
```

## Suggested Development Order

```txt
1. P3-001 Identity and Actor Model
2. P3-002 Vault Model
3. P3-003 Permissions and Roles
4. P3-005 Audit and Recovery Hardening
5. P3-004 Public Submission and Review Queue
6. P3-006 UI Foundations
7. P3-007 Tests and Migration
```
