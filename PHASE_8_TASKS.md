# Phase 8 Tasks: AI-Centered Context Hardening

Phase 8 turns the Phase 7 collaboration workflow into a stricter AI-centered
operating layer.

Phase 7 remains the implementation phase for collaboration MVP features:
review import, finding triage, implementation records, context bundle export,
Review Inbox UI, and graph integration. Phase 8 does not replace Phase 7. It
hardens the rules around AI-to-AI handoff, context bundle safety, and project
state clarity.

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

Long-form artifact:
  Markdown.

Machine-readable state:
  SQLite rows and JSON metadata.

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
```

Done when:

```txt
Search checks confirm active docs, UI copy, and API descriptions use the current
terms above.
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

2. Reject any included file path containing:
   .env
   .db
   backups/
   inbox/
   sessions
   users

3. Reject bundle content if it contains the configured ADMIN_TOKEN value.
   Read ADMIN_TOKEN from configuration and perform a direct string match when
   the token is non-empty.

4. Reject bundle content if it contains common secret assignment patterns:
   ADMIN_TOKEN=
   OPENAI_API_KEY=
   API_KEY=
   SECRET=
   PASSWORD=

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
Split findings by "### Finding" headings.
Severity values outside the enum fall back to info.
Area values outside the enum fall back to Docs.
Missing Evidence or Proposed change marks the finding as needs_more_context.
Malformed finding text is stored in raw_text.
Maximum findings per review: 50.
Maximum review Markdown body: 256 KiB.
Maximum decision_note: 2000 characters.
```

Done when:

```txt
Parser tests cover valid findings, multiple findings, malformed findings,
unknown severity/area fallback, over-limit review body, and over-limit finding
count.
```

## P8-004 Durable Artifact Enforcement

Goal:

```txt
No collaboration state should exist only in memory or a transient chat session.
```

Rules:

```txt
Review import:
  Store the original review Markdown under data/pages/reviews/{review_id}.md or
  the current review page storage path used by Phase 7.
  Store collaboration_reviews and collaboration_findings rows.

Decision:
  Store finding status, decision_note, decided_by, and decided_at.
  Record audit action: finding.accept, finding.reject, finding.defer, or
  finding.needs_more_context.

Implementation record:
  Store commit_sha, changed_files, verification, and notes.
  Record audit action: implementation.record.

Context bundle:
  Store context_bundle_manifest with content_hash, selected_pages, and excluded
  sections.
```

Done when:

```txt
Restarting API/web does not lose imported reviews, parsed findings, decisions,
implementation records, or bundle manifests.
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
