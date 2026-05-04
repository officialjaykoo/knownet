# Phase 7 Tasks: AI Collaboration MVP

This plan describes how to turn KnowNet into an AI-centered collaboration
knowledge base without turning it into a large project-management product.

Implementation status: Phase 7 MVP implemented in the codebase. Collaboration
graph integration and multi-page context bundle selection are implemented.

Document role:

```txt
This is the Phase 7 implementation plan.
Implementable scope: P7-001 through P7-008.

Reference-only documents:
  docs/AI_CENTERED_DESIGN.md
  docs/AI_COLLABORATION_CONCEPT.md
  docs/SECURITY_PLAN.md

AI-centered hardening after the Phase 7 MVP:
  PHASE_8_TASKS.md
```

The product direction is fixed:

```txt
KnowNet is an AI-centered collaboration knowledge base.
The product shape is a local-first AI collaboration tool for reviews,
decisions, and implementation records.
```

Design reference: [AI-Centered Design](../AI_CENTERED_DESIGN.md). SQLite/JSON
records are the canonical AI collaboration state. Markdown is preserved as a
narrative attachment for source review text and long-form context.

## Fixed Decisions

```txt
Primary goal: AI-centered review and implementation workflow.
External agents: read context bundles and return structured findings with
optional Markdown narrative.
Implementation authority: local coding agent with repository access.
Canonical collaboration state: SQLite rows and JSON metadata.
Narrative attachment: Markdown review text.
Operational status: SQLite.
Default mode: local-first, single operator.
Security rule: never expose secrets, .env, DB files, or backups in context bundles.
Product boundary: not a public community and not only a generic knowledge base.
Phase 7 MVP boundary: review import, finding triage, implementation evidence,
context bundle export, and Review Inbox UI only.
Graph integration starts after the MVP workflow is stable.
Default vault: local-default for existing single-operator data.
ID format: use the existing project UUID helper; do not derive IDs from titles.
```

## Phase 1-6 Integration

Phase 7 reuses existing infrastructure rather than creating a separate product
stack.

```txt
Auth and permissions:
  Reuse Phase 3 actor/role model.
  Editor/admin/owner can import reviews.
  Admin/owner can export broad context bundles.

Audit:
  Reuse Phase 3 audit_events.
  Actions: review.import, finding.accept, finding.reject, finding.defer,
  finding.needs_more_context, implementation.record, context_bundle.create.

Graph:
  P7-008 reuses Phase 5 rebuild_graph_for_vault after collaboration nodes exist.
  Do not start graph integration until review import and triage are stable.

Operations:
  Phase 6 verify-index gains review/finding orphan checks.
  Phase 6 backup/restore automatically covers collaboration tables and review
  narrative attachments.

Write rule:
  Rust daemon remains the write owner for canonical page files, review narrative
  attachments, and core SQLite state.
  Python routes may orchestrate and validate, but must not directly create
  review narrative files or collaboration SQLite rows.
```

## Data Model

Add collaboration-oriented records without replacing page context.

```sql
CREATE TABLE collaboration_reviews (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  title TEXT NOT NULL,
  source_agent TEXT NOT NULL,
  source_model TEXT,
  review_type TEXT NOT NULL DEFAULT 'agent_review',
  status TEXT NOT NULL DEFAULT 'pending_review',
  page_id TEXT,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE collaboration_findings (
  id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  area TEXT NOT NULL,
  title TEXT NOT NULL,
  evidence TEXT,
  proposed_change TEXT,
  raw_text TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  decision_note TEXT,
  decided_by TEXT,
  decided_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE implementation_records (
  id TEXT PRIMARY KEY,
  finding_id TEXT,
  commit_sha TEXT,
  changed_files TEXT,
  verification TEXT,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE context_bundle_manifests (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  filename TEXT NOT NULL,
  path TEXT NOT NULL,
  selected_pages TEXT NOT NULL DEFAULT '[]',
  included_sections TEXT NOT NULL DEFAULT '[]',
  excluded_sections TEXT NOT NULL DEFAULT '[]',
  content_hash TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);
```

Status values:

```txt
review status:
  pending_review | triaged | implemented | archived

finding status:
  pending | accepted | rejected | deferred | needs_more_context | implemented
```

Severity values:

```txt
critical
  Data loss or security vulnerability.

high
  Core workflow breakage or serious behavioral regression.

medium
  UX, performance, correctness, or quality issue that should be fixed.

low
  Improvement suggestion or nice-to-have.

info
  Context, observation, or non-actionable note.

Parser fallback:
  Unknown severity values become info.
```

Indexes and constraints:

```txt
Indexes:
  collaboration_reviews(vault_id, status, updated_at)
  collaboration_findings(review_id, status, severity)
  implementation_records(finding_id)
  context_bundle_manifests(vault_id, created_at)

Foreign keys:
  collaboration_findings.review_id -> collaboration_reviews.id
  implementation_records.finding_id -> collaboration_findings.id

Migration:
  Add tables idempotently with CREATE TABLE IF NOT EXISTS.
  Existing Phase 1-6 data is not modified by Phase 7 migration.
  Backup before migration follows Phase 6 maintenance migration rules.
```

## Rust Commands

Phase 7 mutating operations should be implemented as Rust daemon commands.

```txt
create_collaboration_review
update_collaboration_review_status
create_collaboration_finding
update_finding_decision
create_implementation_record
create_context_bundle_manifest
```

Command payload rules:

```txt
create_collaboration_review
  Input: vault_id, title, source_agent, source_model, review_type, page_id,
  markdown_path, meta.
  Output: review row.

create_collaboration_finding
  Input: review_id, severity, area, title, evidence, proposed_change, raw_text,
  status.
  Output: finding row.

update_finding_decision
  Input: finding_id, status, decision_note, decided_by.
  Allowed status: accepted, rejected, deferred, needs_more_context.
  Output: updated finding row.

create_implementation_record
  Input: finding_id, commit_sha, changed_files, verification, notes.
  Side effect: accepted finding may move to implemented after record creation.

create_context_bundle_manifest
  Input: vault_id, filename, path, selected_pages, included_sections,
  excluded_sections, content_hash, created_by.
  Output: manifest row.
```

Review import writes:

```txt
SQLite rows:
  collaboration_reviews row created by create_collaboration_review.
  collaboration_findings rows created by create_collaboration_finding.
  These rows are the canonical review/finding state.

Review narrative attachment:
  Preserve source review prose through the Rust daemon write path when present.
  Do not require narrative prose when the import already provides complete
  structured finding data.

Python role:
  Validate request.
  Parse review input into structured records.
  Call Rust daemon commands.
  Record audit event after command success.
```

## Review Input Format

Agent reviews may arrive as Markdown prose with structured finding sections, or
as already structured finding data. SQLite/JSON rows are canonical after import.

Recommended frontmatter:

```yaml
---
type: agent_review
source_agent: claude
source_model: claude-3.7
review_area: graph_ux
status: pending_review
created_at: 2026-05-02T00:00:00Z
---
```

Recommended body:

```md
# Review: Graph UX

## Summary

Short overview.

## Findings

### Finding 1: Core node states are visually ambiguous

Severity: medium
Area: graph-ui

Evidence:
...

Proposed change:
...
```

## Review Parser Rules

The parser rules are fixed so external review format and importer behavior stay
aligned.

```txt
Frontmatter:
  Parse with python-frontmatter.
  Required defaults:
    type = agent_review
    status = pending_review
    source_agent = "unknown" when absent

Finding split:
  For Markdown narrative input, a finding begins at a heading that starts with:
    ### Finding
  The finding ends at the next "### " heading or document end.

Finding title:
  Use the heading text after "### ".
  Example: "### Finding 1: Core node states are visually ambiguous"

Severity:
  Extract from a line matching:
    Severity: {value}
  Unknown value falls back to info.

Area:
  Extract from a line matching:
    Area: {value}
  Missing value falls back to general.

Evidence:
  Starts after a line exactly matching "Evidence:".
  Ends before "Proposed change:" or the next finding heading.

Proposed change:
  Starts after a line exactly matching "Proposed change:".
  Ends at the next finding heading or document end.

Parse failure:
  Store the full finding block in raw_text.
  Set finding.status = needs_more_context.
  Record parser errors in collaboration_reviews.meta.parser_errors.
```

If no `### Finding` headings exist, import the whole body as one finding with:

```txt
severity = info
area = general
status = needs_more_context
raw_text = body
```

## API Surface

Minimal endpoints:

```txt
POST /api/collaboration/reviews
  Import review input and create canonical structured collaboration rows.
  Body:
    { "vault_id": "local-default", "markdown": "...", "source_agent": "claude" }
  Returns:
    { "review": {...}, "findings": [...] }

GET /api/collaboration/reviews
  List reviews by status/source/area.
  Query:
    vault_id required, status/source_agent/area optional, limit default 50 max 200.

GET /api/collaboration/reviews/{review_id}
  Read review with parsed findings.

POST /api/collaboration/findings/{finding_id}/decision
  Set accepted/rejected/deferred/needs_more_context with note.
  Body:
    { "status": "accepted", "decision_note": "..." }

POST /api/collaboration/findings/{finding_id}/implementation
  Attach commit/test evidence.
  Body:
    { "commit_sha": "...", "changed_files": [...], "verification": "...", "notes": "..." }

POST /api/collaboration/context-bundles
  Create a curated AI context bundle from selected pages and structured records.
  Body:
    { "vault_id": "local-default", "page_ids": [...], "include_graph_summary": true }
  Returns:
    { "manifest": {...}, "content": "..." }
```

All mutating endpoints should require editor/admin/owner permission and should
write through the Rust daemon when they mutate SQLite state.

## Context Bundle Rules

Context bundles are for external AI review. They should be useful, narrow, and
structured-record first.

Allowed content:

```txt
Selected active pages:
  slug, title, tags/frontmatter, latest page content.

Structured collaboration summary:
  review ids, finding ids, severity, status, area, decision status,
  implementation record ids.

Citation audit summary:
  citation_key, status, verifier_type, short reason.
  Raw evidence excerpts are excluded by default.

Graph summary:
  node count, edge count, core pages, weak citation page list.

Project docs:
  Explicitly selected docs only.
```

Excluded content:

```txt
.env files and API key values
knownet.db and any *.db files
data/backups/
data/inbox/ raw pending messages
data/tmp/
sessions and users table contents
audit_events IP hashes and session_meta
raw citation evidence snapshots unless explicitly added by owner/admin
```

Output format:

```txt
Default: single Markdown file containing structured JSON summary blocks plus
selected narrative context.
Archive format when multiple assets are needed: .tar.gz.
Archive format is fixed; do not introduce another archive format for KnowNet
snapshots or context bundle archives.

Filename:
  knownet-context-{yyyymmdd}-{short_id}.md

Header:
  # KnowNet Context Bundle
  generated_at: {iso_timestamp}
  pages_included: {count}
  generated_for: external AI review
  warning: Do not include secrets in this bundle.

Page section:
  ---
  ## Page: {title}
  slug: {slug}

  {latest page content}

Citation section:
  ### Citation Audit Summary
  - {citation_key}: {status} ({verifier_type}) - {short_reason}

Graph section:
  ### Graph Summary
  nodes: N
  edges: N
  weak_pages: [...]
```

The bundle manifest should be recorded by `create_context_bundle_manifest`.

Bundle storage:

```txt
Generated bundle path:
  data/context-bundles/{filename}

Write rule:
  The bundle file is created by the Rust daemon.
  API response may also return content for copy/paste convenience.

Retention:
  Bundles are safe to delete and can be regenerated.
  They are included in snapshots unless the user chooses a minimal backup mode.
```

## Error Codes

```txt
collaboration_review_not_found
collaboration_finding_not_found
collaboration_invalid_status
collaboration_parser_error
collaboration_no_findings
context_bundle_forbidden_path
context_bundle_empty_selection
context_bundle_secret_detected
context_bundle_write_failed
implementation_record_invalid_commit
```

Secret detection is a defensive scan, not the only security boundary. The
allowed/excluded content rules remain authoritative.

## UI Scope

Build this as a focused operations surface.

```txt
1. Review Inbox
   List pending agent reviews and finding counts.

2. Review Detail
   Show source review narrative, extracted findings, severity, and proposed changes.

3. Triage Controls
   Accept, reject, defer, or request more context with a short decision note.

4. Implementation Record
   Attach commit hash, changed files, and test result summary.

5. Context Bundle Builder
   Select structured records and page context to produce one context bundle for
   another AI agent.
```

Avoid chat-style UI for now. The work unit is a review/finding/decision, not a
message stream.

## Graph Integration

Represent collaboration artifacts in the graph only after the core flow works.

Potential graph nodes:

```txt
review:{review_id}
finding:{finding_id}
decision:{finding_id}
commit:{sha}
```

Potential edges:

```txt
review_contains_finding
finding_affects_page
finding_implemented_by_commit
finding_rejected_by_decision
```

This allows the map to show which parts of the knowledge base/codebase attract
the most review risk.

## Implementation Order

```txt
P7-001 Document type and review parser
  Parse agent review input into canonical review + finding records using the
  fixed parser rules above.

P7-002 SQLite schema and Rust commands
  Add collaboration_reviews, collaboration_findings, implementation_records.
  Add create/update Rust commands listed above.

P7-003 Review import API
  Import review input, preserve narrative attachment through Rust when present,
  extract findings, create canonical rows, and record audit event.

P7-004 Triage API
  Accept/reject/defer findings with decision notes.

P7-005 Review Inbox UI
  List pending reviews and allow triage.

P7-006 Implementation record API/UI
  Attach commit/test evidence after code changes.

P7-007 Context bundle export
  Generate curated AI context bundles for external agents.

P7-008 Graph integration
  Add review/finding nodes and edges after the workflow is stable.
```

## Tests

Required MVP tests:

```txt
Review parser:
  Parses multiple ### Finding sections.
  Falls back to info/general for missing severity/area.
  Stores raw_text and needs_more_context on malformed findings.

API:
  Anonymous/viewer cannot import reviews or create bundles.
  Editor can import reviews and triage findings.
  Admin/owner can create broad context bundles.
  Invalid finding status returns collaboration_invalid_status.

Rust commands:
  Create review/finding/implementation rows idempotently where applicable.
  Context bundle manifest is recorded with content_hash.

Security:
  Context bundle excludes .env, *.db, backups, sessions, users, inbox, tmp.
  Secret-like values are rejected with context_bundle_secret_detected.

UI:
  Review Inbox renders pending reviews and finding counts.
  Decision buttons update finding status without page reload.
```

## Completion Definition

Phase 7 MVP is complete when these five workflows work:

```txt
1. Review import creates canonical review/finding records.
2. Each finding can be accepted, rejected, deferred, or marked needs_more_context.
3. Accepted findings can be linked to commit hash and verification summary.
4. Context bundle generation excludes secrets and restricted data.
5. Review Inbox UI lists pending reviews and supports triage.
```

Non-MVP until the five workflows are stable:

```txt
Chat-style collaboration UI.
Remote agent execution.
Full issue tracker replacement.
```

Post-MVP boundary decisions:

```txt
Graph integration:
  Implemented for review, finding, and commit nodes.

Chat-style collaboration UI:
  Deferred by design. Reviews and findings remain durable work units; transient
  chat may be added later only if it produces review/finding records.

Remote agent execution:
  Not implemented. External agents may receive context bundles and return
  structured findings with optional narrative text, but KnowNet does not grant
  repository, shell, database, or backup access to remote agents.

Full issue tracker replacement:
  Not implemented. Phase 7 keeps review/finding/decision records only.
```

## Risks

```txt
Overbuilding into a full issue tracker.
Letting external agent advice bypass local verification.
Mixing chat messages with durable decisions.
Exporting too much sensitive context.
Creating many statuses that the user never uses.
```

Keep the first version small: import reviews, triage findings, record what was
implemented.
