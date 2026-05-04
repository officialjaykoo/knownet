# KnowNet Phase 4 Tasks

## Phase 4 Closure - 2026-05-02

Status: implementation closed for the Phase 4 MVP.

Phase 4 added durable citation audit state on top of the Phase 2 citation parser
and Phase 3 vault/security model. Applied suggestions now rebuild citation audit
rows, weak citations can surface as warnings, reviewers can triage citation
audits through API/UI, and verify-index can report missing or orphaned audit
metadata.

Implemented coverage:

```txt
citation_audits, citation_evidence_snapshots, and citation_audit_events schema
Rust markdown parser emits claim_text, normalized_claim_text, and claim_hash
Rust rebuild_citation_audits_for_page command
Rust update_citation_audit_status command
deterministic keyword-overlap verifier
bounded evidence snapshots with excerpt/source hashes
suggestion apply returns citation_warnings array
GET /api/citations/audits queue API
POST /api/citations/audits/{id}/resolve
POST /api/citations/audits/{id}/needs-review
POST /api/citations/audits/{id}/verify OpenAI-mock/manual path
POST /api/citations/rebuild/page/{page_id}
verify-index reports citation_audit_missing and citation_audit_orphaned
web citation audit queue
```

Verified implementation coverage:

```txt
24 API tests passing
Rust core cargo build passing
web production build passing
```

Phase 4.1 carryovers that do not block Phase 5:

```txt
real OpenAI verifier call path beyond mock/manual status transition
semantic similarity upgrade when local embedding model is available
full vault-level citation rebuild endpoint
claim_hash_version migration if claim extraction rules ever change
dedicated citation detail screen with evidence excerpt display
more precise claim extraction for citation-only footnote lists
```

Decision: move to Phase 5 after Phase 4 MVP, with graph view and knowledge map
as the next major development axis.

Phase 4 goal: make AI citations auditable enough that KnowNet can explain why a
claim is trusted, disputed, stale, or waiting for review.

Phase 2 added basic citation verification. Phase 3 added identity, vaults,
review queues, and stronger audit trails. Phase 4 now deepens citation audit so
AI-generated knowledge can be checked, repaired, and trusted over time.

## Phase 4 Fixed Decisions

These choices are fixed before implementation so the agent does not invent the
citation model while coding.

```txt
Citation source of truth: Markdown remains canonical, SQLite stores audit/index state.
Citation identity: citation instance = page_id + revision_id + citation_key + claim_hash.
Citation status: unchecked | supported | partially_supported | unsupported | contradicted | stale | needs_review.
AI citation verifier: manual trigger first; automatic runs only after deterministic checks pass.
Evidence snapshots: store short source excerpts and hashes, not full copied source documents.
Review authority: reviewer/editor/admin/owner may resolve citation audits.
Write rule: Phase 4 SQLite writes go through Rust daemon commands when they mutate audit state.
Vault rule: all citation audit rows are vault-scoped.
```

## Claim Text and Hash Rules

This section is the most important Phase 4 stability rule. Rebuild must produce
the same `claim_hash` for the same Markdown text.

```txt
claim_text extraction:
- Use the full paragraph containing the citation_key occurrence.
- Paragraph boundary is a blank line, i.e. two or more newlines after normalization.
- Strip Markdown emphasis/link/header/bracket syntax before hashing.
- Normalize: strip -> lowercase -> collapse consecutive whitespace to one space.
- claim_hash = sha256(normalized claim_text) truncated to 24 hex chars.
- Extraction and hashing happen in Rust markdown.rs, not Python.
```

If this rule changes later, Phase 4 must introduce an explicit
`claim_hash_version`; do not silently change the hash behavior.

## Phase 4 Config Defaults

```txt
CITATION_KEYWORD_SUPPORTED_THRESHOLD=0.5
CITATION_KEYWORD_PARTIAL_THRESHOLD=0.2
CITATION_SEMANTIC_SUPPORTED_THRESHOLD=0.75
CITATION_EVIDENCE_EXCERPT_MAX_CHARS=500
CITATION_OPENAI_REASON_MAX_CHARS=300
```

## Phase 4 Error Codes

```txt
citation_audit_not_found: audit_id does not exist.
citation_source_missing: citation_key source is missing from the database or file system.
citation_verifier_schema_error: OpenAI verifier response violates schema.
citation_already_resolved: a resolved audit was resolved again.
evidence_snapshot_too_large: excerpt exceeds configured maximum.
claim_text_unextractable: citation exists but no stable claim paragraph can be extracted.
```

## Phase 4 Principles

```txt
Do not hide weak citations from users.
Do not turn a citation key into trust by itself.
Record why a verifier reached a status.
Keep deterministic checks cheap and local.
Use OpenAI only for selected high-value citation checks.
Make every status transition auditable.
Preserve enough evidence to debug bad AI output later.
```

## Phase 4 SQLite Schema Baseline

The existing `citations` table remains the lightweight parse/index table. Phase
4 adds audit tables rather than overloading the basic parser output.

```sql
CREATE TABLE citation_audits (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  page_id TEXT NOT NULL,
  revision_id TEXT,
  citation_key TEXT NOT NULL,
  claim_hash TEXT NOT NULL,
  claim_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unchecked',
  confidence REAL,
  verifier_type TEXT NOT NULL,      -- deterministic | openai | human
  verifier_id TEXT,
  reason TEXT,
  source_hash TEXT,
  evidence_snapshot_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(vault_id, page_id, revision_id, citation_key, claim_hash)
);

CREATE TABLE citation_evidence_snapshots (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  citation_key TEXT NOT NULL,
  source_type TEXT NOT NULL,        -- message | source | page | external
  source_id TEXT,
  source_path TEXT,
  excerpt TEXT NOT NULL,
  excerpt_hash TEXT NOT NULL,
  captured_at TEXT NOT NULL
);

CREATE TABLE citation_audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  citation_audit_id TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  reason TEXT,
  meta TEXT,
  created_at TEXT NOT NULL
);
```

Required indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_citation_audits_status
  ON citation_audits(vault_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_citation_audits_page
  ON citation_audits(vault_id, page_id, revision_id);

CREATE INDEX IF NOT EXISTS idx_citation_audit_events_audit
  ON citation_audit_events(citation_audit_id, created_at);
```

## Rust Daemon Commands

Phase 4 mutation commands:

```txt
create_citation_audit
update_citation_audit_status
capture_citation_evidence_snapshot
record_citation_audit_event
rebuild_citation_audits_for_page
rebuild_citation_audits_for_vault
```

FastAPI may read citation audit tables directly, but status changes and rebuilds
must go through Rust daemon commands.

## Completion Criteria

```txt
Each current page citation can produce or update a citation_audits row.
Citation audits are scoped by vault_id.
Unsupported, contradicted, stale, and needs_review citations appear in an audit queue.
Reviewer/editor/admin/owner can mark a citation as resolved or needs_review.
verify-index reports missing, unsupported, contradicted, stale, and orphaned audit rows.
Suggestion apply records citation audit rows for the applied revision.
Manual OpenAI citation verification can run for one citation or one page.
OpenAI verifier output is structured and stored with reason/confidence.
Evidence snapshots store bounded excerpts and hashes.
Tests cover deterministic, human, and OpenAI-mock audit paths.
```

## P4-001 Citation Audit Model

Goal:

```txt
Create durable audit records for individual claims tied to citations.
```

Tasks:

```txt
Add citation_audits, citation_evidence_snapshots, and citation_audit_events.
Define claim_hash as sha256(normalized claim_text) truncated to 24 chars.
Map Markdown citation usages to claim_text windows.
Create audits for page_id + revision_id + citation_key + claim_hash.
Backfill current pages into citation_audits.
```

Backfill rules:

```txt
Backfill runs through the Rust rebuild_citation_audits_for_vault command.
parse_error files are skipped and recorded in the report.
One broken file must not abort the full vault backfill.
Existing rows matching (vault_id, page_id, revision_id, citation_key, claim_hash) are skipped.
Return created, skipped, failed, and parse_errors counts.
Never write Markdown files during backfill.
```

Done when:

```txt
The audit table can answer: which claim used this citation, in which revision, and with what trust status?
```

## P4-002 Deterministic Verifier

Goal:

```txt
Improve local verification before involving OpenAI.
```

Tasks:

```txt
Extract claim windows around each citation.
Resolve citation_key to message/source/page evidence.
Compute keyword overlap and optional semantic similarity when embeddings are available.
Classify supported, partially_supported, unsupported, or stale.
Record reason strings that a human can understand.
```

MVP classification:

```txt
source missing from messages/sources/page -> stale
keyword overlap >= CITATION_KEYWORD_SUPPORTED_THRESHOLD -> supported
keyword overlap >= CITATION_KEYWORD_PARTIAL_THRESHOLD and < supported threshold -> partially_supported
keyword overlap < CITATION_KEYWORD_PARTIAL_THRESHOLD -> unsupported
embedding cosine > CITATION_SEMANTIC_SUPPORTED_THRESHOLD may upgrade partially_supported to supported
contradicted is reserved for OpenAI or human verifier output in Phase 4 MVP
```

Keyword overlap uses normalized claim_text tokens after removing stopwords and
punctuation. For MVP, "?�심 명사" means non-stopword tokens with length >= 2.

Done when:

```txt
Rule-based verifier produces stable citation_audits rows without requiring network access.
```

## P4-003 Evidence Snapshots

Goal:

```txt
Keep bounded evidence for later debugging without copying entire source documents.
```

Tasks:

```txt
Capture short excerpts around matched evidence.
Store excerpt_hash and source_hash.
Limit excerpt length to a configured maximum.
Avoid storing secrets or binary/imported attachment contents.
Refresh snapshot when source_hash changes.
Mark audit status stale when source evidence changes.
```

Snapshot rules:

```txt
Default excerpt limit: CITATION_EVIDENCE_EXCERPT_MAX_CHARS=500.
Excerpt window: 250 chars before and 250 chars after the evidence match.
If source text is under 500 chars, use the whole source text.
excerpt_hash = sha256(excerpt) full hex digest, not truncated.
source_hash = sha256(full source file content) full hex digest.
When source_hash is unchanged, do not create a new snapshot.
When source_hash changes, create a new snapshot row; never delete the old row.
```

Snapshot refresh triggers:

```txt
write_revision completed
suggestion apply completed
rebuild_citation_audits_for_page
rebuild_citation_audits_for_vault
manual citation verify request
```

Done when:

```txt
A reviewer can see what evidence was used at the time of verification.
```

## P4-004 Manual OpenAI Citation Verifier

Goal:

```txt
Use OpenAI only when deterministic checks are insufficient or a reviewer requests it.
```

Tasks:

```txt
Add structured OpenAI verifier schema.
Input: claim_text, citation_key, bounded evidence excerpt, current deterministic status.
Output: status, confidence, reason, missing_evidence, contradiction_summary.
Reject free-form verifier output that does not match schema.
Apply timeout and no auto-retry by default.
Record verifier_type='openai' and model metadata.
```

OpenAI output schema:

```json
{
  "status": "supported | partially_supported | unsupported | contradicted | needs_review",
  "confidence": 0.0,
  "reason": "string (max 300 chars)",
  "missing_evidence": "string | null",
  "contradiction_summary": "string | null"
}
```

OpenAI verifier rules:

```txt
Use response_format={"type":"json_object"}.
System prompt: "You are a citation verifier. Respond only in the specified JSON schema. Do not add extra fields."
Reject enum values outside the status list.
Reject non-numeric confidence.
Truncate reason to CITATION_OPENAI_REASON_MAX_CHARS before storage.
Return citation_verifier_schema_error for invalid output.
OpenAI verification is manual-trigger only in Phase 4 MVP.
```

Done when:

```txt
POST /api/citations/{audit_id}/verify can run an OpenAI-mock test path and store structured results.
```

## P4-005 Citation Review Queue

Goal:

```txt
Give reviewers a focused queue for weak or disputed citations.
```

Tasks:

```txt
Add GET /api/citations/audits with status/page/vault filters.
Add POST /api/citations/audits/{id}/resolve.
Add POST /api/citations/audits/{id}/needs-review.
Show unsupported, contradicted, stale, and needs_review items in the web UI.
Show claim_text, source excerpt, status, reason, and verifier type.
```

Filter API:

```txt
GET /api/citations/audits
  ?vault_id=local-default   required
  &status=unsupported,stale optional comma-separated list
  &page_id=page_x           optional
  &verifier_type=openai     optional
  &limit=50                 default 50, max 200
  &offset=0                 default 0

Default sorting: updated_at DESC.
```

Done when:

```txt
A reviewer can triage citation problems without reading raw SQLite rows.
```

## P4-006 Suggestion Apply Integration

Goal:

```txt
Audit citations as soon as AI-generated Markdown becomes canonical.
```

Tasks:

```txt
After suggestion apply, rebuild citation audits for the applied page revision.
Store citation audit summary in suggestion.apply audit metadata.
If unsupported/contradicted citations exist, keep the page active but surface warnings.
Do not block apply unless verifier detects malformed citation keys.
```

Apply response shape:

```json
{
  "ok": true,
  "data": {
    "slug": "cql-dqn",
    "revision_id": "rev_...",
    "citation_warnings": [
      {
        "citation_key": "msg-20260501-0001",
        "status": "unsupported",
        "reason": "keyword overlap below threshold"
      }
    ]
  }
}
```

`citation_warnings` is always an array. Return `[]` when there are no warnings.
The UI shows a warning banner after apply when the array is non-empty.

Done when:

```txt
Every applied AI suggestion leaves a citation audit trail.
```

## P4-007 verify-index and Rebuild

Goal:

```txt
Make citation audit state recoverable from Markdown and sources.
```

Tasks:

```txt
Extend verify-index to report orphaned citation_audits.
Report audit rows whose page/revision/citation no longer exists.
Report citations with no audit row.
Add rebuild command for one page and one vault.
Ensure rebuild does not alter Markdown frontmatter.
```

Rebuild safety rules:

```txt
Rebuild never writes Markdown files.
Rebuild never edits frontmatter.
Rebuild never creates revisions.
Rebuild only creates/updates citation_audits rows through Rust daemon commands.
Rebuild only creates citation_evidence_snapshots through Rust daemon commands.
Rebuild only records citation_audit_events through Rust daemon commands.
If rebuild fails, Markdown remains byte-for-byte unchanged.
```

Done when:

```txt
Deleting knownet.db and rebuilding from Markdown can recreate citation audit metadata.
```

## P4-008 Tests

Goal:

```txt
Keep citation trust behavior stable.
```

Required tests:

```txt
deterministic supported citation
deterministic unsupported citation
missing citation source
stale citation after source hash changes
OpenAI mock verifier schema success
OpenAI malformed verifier output rejection
manual reviewer resolve
reviewer needs_review transition
suggestion apply creates citation audits
verify-index reports missing audit rows
vault isolation for citation audits
evidence snapshot length limit
```

## Out of Scope

```txt
Fully automatic OpenAI verification for every citation
External web crawling as evidence collection
Long-term vector database migration
Legal/compliance-grade provenance
Real-time collaborative citation editing
```

## Suggested Development Order

```txt
1. P4-001 Citation Audit Model
2. P4-002 Deterministic Verifier
3. P4-003 Evidence Snapshots
4. P4-007 verify-index and Rebuild
5. P4-005 Citation Review Queue
6. P4-006 Suggestion Apply Integration
7. P4-004 Manual OpenAI Citation Verifier
8. P4-008 Tests
```
