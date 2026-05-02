# Phase 8 Tasks: AI-Centered Context Hardening

Phase 8 turns the Phase 7 collaboration workflow into a stricter AI-centered
operating layer.

Implementation status: completed in the codebase.

Implemented surface:

```txt
P8-001:
  Current terminology checks for active docs and app code.

P8-002:
  Context bundle secret/path guard with no bypass flag, ADMIN_TOKEN value
  matching, line-based assignment matching, and false-positive boundary tests.

P8-003:
  Case-insensitive finding parser, area normalization, 50-finding truncation,
  256 KiB review body limit, and 2000-character decision note limit.

P8-004:
  Collaboration review/finding/decision/implementation/context bundle state is
  persisted in existing Phase 7 tables.

P8-005:
  Collaboration read routes reuse viewer-or-higher access; mutating routes keep
  write/admin access.

P8-006:
  verify-index reports collaboration and context bundle drift.

P8-007:
  Default seed file is KnowNet AI state content, not sample/demo content.

P8-008:
  API regression tests, Rust test build, and web production build cover the
  hardening path.
```

Phase 7 remains the implementation phase for collaboration MVP features:
review import, finding triage, implementation records, context bundle export,
Review Inbox UI, and graph integration. Phase 8 does not replace Phase 7. It
hardens the rules around AI-to-AI handoff, context bundle safety, and project
state clarity.

Implementation posture:

```txt
Phase 8 is a tightening pass, not a feature expansion phase.

Prefer:
  small additive validation
  tests for existing Phase 7 behavior
  clearer terminology
  safer context export

Avoid:
  changing Phase 1-7 endpoint contracts
  new auth/token systems
  new archive formats
  broad rewrites or product expansion
```

## Document Roles

These documents have different purposes. Implementation agents must not treat
all of them as task lists.

```txt
docs/AI_CENTERED_DESIGN.md:
  Design philosophy and judgment guide. Not a direct implementation checklist.

docs/AI_COLLABORATION_CONCEPT.md:
  Product direction and collaboration model. Not a direct implementation
  checklist.

docs/SECURITY_PLAN.md:
  Phase 1-6 security baseline and implementation record. It is already marked
  Done for the covered items. Phase 8 may reuse its rules but should not
  reinterpret it as unfinished work.

PHASE_7_TASKS.md:
  Phase 7 implementation plan. P7-001 through P7-008 are the collaboration MVP
  tasks.

PHASE_8_TASKS.md:
  Phase 8 implementation plan for AI-centered hardening.
```

## Fixed Decisions

```txt
Product identity:
  AI-centered collaboration knowledge base.

Canonical collaboration state:
  SQLite rows and JSON metadata.

Narrative attachment:
  Markdown for long reasoning, source review prose, runbooks, and selected page
  context.

Page storage:
  data/pages only.

Page API:
  /api/pages only.

Archive format:
  .tar.gz for snapshots and multi-asset exports.
  Do not introduce another archive format.

Security posture:
  Context bundle secret checks are hard-coded and cannot be disabled by user
  override.

Scope:
  Harden AI collaboration and context export. Do not rebuild the whole product.
```

## Do Not Change

Phase 8 must not use "AI-centered" as a reason to rewrite working Phase 1-7
infrastructure.

```txt
Do not change:
  Phase 1-7 endpoint behavior except where Phase 8 explicitly tightens context
  bundle validation or terminology.
  Rust daemon write ownership.
  Existing SQLite tables except for additive metadata or validation fields that
  Phase 8 explicitly requires.
  Existing verify-index checks except for additive AI-centered/context-bundle
  checks.
  data/pages storage structure.
  .tar.gz snapshot behavior.
```

## P8-001 Current Terminology

Goal:

```txt
Keep active docs, UI, API descriptions, and implementation notes aligned with
the current product language.
```

Rules:

```txt
Product identity:
  AI-centered collaboration knowledge base

Content unit:
  page / pages

Page storage:
  data/pages

Page API:
  /api/pages

Archive format:
  .tar.gz

External review artifact:
  context bundle
```

Implementation rule:

```txt
New documentation and UI copy must use only the current terms above.
Only rename terms when they refer to KnowNet content units, storage, API
descriptions, or user-facing labels.

Do not rename unrelated programming terms such as DOM document, Markdown
document, JSON document, or third-party API wording when they are not KnowNet
content-unit labels.
```

Done when:

```txt
Search checks confirm active docs, UI copy, and API descriptions use the current
terms above.
The search result list is reviewed before edits so unrelated technical terms are
not renamed mechanically.
```

## P8-002 Context Bundle Secret Guard

Goal:

```txt
Prevent accidental leakage of secrets or local-only raw state to external AI
agents.
```

Hard-coded export checks:

```txt
Before a context bundle is returned or written:

1. Reject any response JSON object that contains keys matching:
   token, secret, password, key
   Match keys case-insensitively. Apply this to generated bundle metadata and
   response JSON, not to every word in page prose.

2. Reject any included file path containing:
   .env
   .db
   backups/
   inbox/
   sessions
   users

3. Reject bundle content if it contains the configured ADMIN_TOKEN value.
   Read ADMIN_TOKEN from configuration and perform a direct string match when
   the token is non-empty and at least ADMIN_TOKEN_MIN_CHARS characters long.
   Skip this direct-value check when ADMIN_TOKEN is empty or shorter than the
   configured minimum.

4. Reject bundle content if it contains common secret assignment patterns:
   ADMIN_TOKEN=
   OPENAI_API_KEY=
   API_KEY=
   SECRET=
   PASSWORD=
   Check line-by-line, case-insensitively.
   Ignore lines that start with "#".
   Match only assignments at the start of a line with optional whitespace around
   "=".
   Do not flag names such as ADMIN_TOKEN_MIN_CHARS.

5. Reject raw table exports for:
   users
   sessions
   audit_events.ip_hash
   audit_events.user_agent_hash
```

Behavior:

```txt
If any check fails:
  Stop bundle generation.
  Return context_bundle_secret_detected or context_bundle_forbidden_path.
  Record an audit event with redacted metadata.
  Do not write a partial bundle file.

No override:
  The user cannot bypass these checks through an API flag, UI option, or env
  variable.
```

Done when:

```txt
Tests prove context bundle export rejects .env, *.db, backups, inbox paths,
ADMIN_TOKEN values, and secret-like keys.
Tests prove boundary cases do not false-positive:
  empty ADMIN_TOKEN
  short ADMIN_TOKEN below ADMIN_TOKEN_MIN_CHARS
  "# ADMIN_TOKEN=example"
  "ADMIN_TOKEN_MIN_CHARS=32"
  prose such as "my_password_field"
```

## P8-003 Finding Parser Contract

Goal:

```txt
Make the Phase 7 review parser follow the AI-centered finding format exactly.
```

Supported finding format:

```md
### Finding

Severity: critical | high | medium | low | info
Area: API | UI | Rust | Security | Data | Ops | Docs

Evidence:
...

Proposed change:
...
```

Parsing rules:

```txt
Split findings by "### Finding" headings, case-insensitively.
Severity values outside the enum fall back to info.
Area values are normalized before enum comparison:
  api -> API
  ui -> UI
  rust -> Rust
  security -> Security
  data -> Data
  ops -> Ops
  docs -> Docs
Area values outside the enum fall back to Docs.
Missing Evidence or Proposed change marks the finding as needs_more_context.
Malformed finding text is stored in raw_text.
Maximum findings per review: 50.
If a review contains more than 50 findings, parse the first 50, set
review.meta.truncated_findings=true, and do not fail the whole import.
Maximum review Markdown body: 256 KiB.
Maximum decision_note: 2000 characters.
```

Done when:

```txt
Parser tests cover valid findings, multiple findings, malformed findings,
unknown severity/area fallback, over-limit review body, and over-limit finding
count.
Parser tests also cover:
  "### finding" and "### FINDING"
  lower-case area values such as api and ui
  51 findings producing 50 parsed findings plus truncated_findings=true
```

## P8-004 Durable Artifact Enforcement

Goal:

```txt
No collaboration state should exist only in memory or a transient chat session.
```

Rules:

```txt
Review import:
  Store collaboration_reviews and collaboration_findings rows as canonical
  state.
  Preserve source review prose as a narrative attachment when present.

Decision:
  Store finding status, decision_note, decided_by, and decided_at.
  Record audit action: finding.accept, finding.reject, finding.defer, or
  finding.needs_more_context.

Implementation record:
  Store commit_sha, changed_files, verification, and notes.
  Record audit action: implementation.record.

Context bundle:
  Store context_bundle_manifest with content_hash, selected_pages, included
  structured record ids, and excluded sections.
```

Done when:

```txt
Restarting API/web does not lose imported reviews, parsed findings, decisions,
implementation records, or bundle manifests.
Tests verify persistence using the existing Phase 7 collaboration tables. Do not
create replacement tables for this check.
```

## P8-005 Permission Tightening

Goal:

```txt
Make collaboration endpoints follow the existing Phase 3 security model without
creating new auth mechanisms.
```

Rules:

```txt
POST /api/collaboration/*:
  editor/admin/owner only.

GET /api/collaboration/*:
  viewer/editor/admin/owner only.
  In public mode, do not expose broad read access without the existing auth
  dependency.

Context bundle export:
  admin/owner only.

Mutating endpoints:
  Reuse existing write auth dependency.
  Record audit_events.
  Do not create a parallel token system.
  Do not add new middleware when the existing FastAPI dependency pattern already
  covers the route.
```

Done when:

```txt
Permission tests prove anonymous and viewer actors cannot mutate collaboration
state or export broad context bundles.
```

## P8-006 Verify-Index Extension

Goal:

```txt
Make operational checks catch AI-collaboration drift.
```

Add verify-index checks:

```txt
collaboration_review_missing_page:
  collaboration_reviews.page_id is set but the page is missing.

collaboration_finding_orphan:
  collaboration_findings.review_id does not exist.

implementation_record_orphan:
  implementation_records.finding_id is set but the finding is missing.

context_bundle_forbidden_reference:
  context_bundle_manifests selected_pages or included paths reference forbidden
  paths such as .env, *.db, backups, or inbox.

current_terminology_mismatch:
  Active docs, UI strings, or API descriptions do not use the current Phase 8
  terminology.
```

Done when:

```txt
GET /api/maintenance/verify-index reports the new issue codes and returns clean
on a normal local dataset.
```

## P8-007 AI State Seed Pages

Goal:

```txt
Keep the in-app pages useful for future AI agents, not just humans.
```

Required active pages:

```txt
KnowNet Overview
Current Implementation State
Architecture Boundaries
Known Risks And Review Targets
AI Review Writing Guide
Context Bundle Policy
Codex Operating Notes
Development Direction
Quality Hardening Roadmap
Operational Security And Access
Review To Code Loop
AI Agent Collaboration Flow
```

Rules:

```txt
Seed pages must live under data/pages.
Old sample or demo pages must not remain active, tombstoned, hidden in
data/revisions, or visible in graph/search.
Seed pages must describe current state, not aspirational plans.
Do not create empty placeholders.

Each seed page should include:
  Current State
  Boundaries
  Known Issues
  Review Targets

If a fact cannot be verified yet, write:
  [TBD - Codex should fill this after implementation verification]
```

Done when:

```txt
DB and filesystem checks find no active or hidden sample content.
Graph nodes contain current KnowNet pages only.
```

## P8-008 Tests And Documentation

Required checks:

```txt
API tests:
  Collaboration permission tests.
  Context bundle secret guard tests.
  Finding parser contract tests.
  Verify-index collaboration drift tests.
  Terminology search tests for app code and active docs.

Web checks:
  Review Inbox still renders.
  Context bundle UI surfaces rejection errors clearly.
  Page list and graph do not show old sample content.

Docs:
  README points to AI_CENTERED_DESIGN.md.
  AI_COLLABORATION_CONCEPT.md says it is product direction, not implementation.
  PHASE_7_TASKS.md remains Phase 7.
  PHASE_8_TASKS.md is the implementation checklist for AI-centered hardening.
```

## Completion Definition

Phase 8 is complete when:

```txt
1. Active docs and UI use current Phase 8 terminology.
2. Context bundle export has non-bypassable secret/path guards.
3. Finding parser follows the AI-centered contract.
4. Collaboration artifacts survive process restart.
5. Collaboration permissions reuse the existing auth model.
6. verify-index catches collaboration/context drift.
7. In-app seed pages describe KnowNet's current AI-centered state.
8. Tests cover the hardening rules.
```

Phase 8 should improve reliability and safety. It should not add a large new
feature surface.
