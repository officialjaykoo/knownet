# DB v2 Blueprint

Status: Phase 29 second-pass design plus first implementation surface

This is a target design, not an applied migration. It favors clean structure
over compatibility with early phase leftovers. SQLite remains the database and
the design must stay light enough for a local-first app.

## Target Entity Groups

| Group | Entities | Responsibility |
|---|---|---|
| `content` | `pages`, `revisions`, `sections`, `citations` | Canonical Markdown-backed knowledge and parsed content indexes. |
| `citation_audit` | `citation_audits`, `citation_evidence`, `citation_events` | Durable audit/evidence trail for claims and citations. |
| `graph` | `graph_nodes`, `graph_edges`, `graph_snapshots`, `graph_pins` | Rebuildable graph plus explicit user graph preferences. |
| `ai_context` | `snapshots`, `packets`, `packet_sources`, `node_cards` | Point-in-time state and selected context delivered to AI/operators. |
| `ai_collaboration` | `reviews`, `findings`, `finding_evidence`, `finding_locations`, `finding_decisions` | External/internal AI review results and operator decisions. |
| `implementation` | `tasks`, `implementation_records`, `verification_records` | Work items and evidence that findings were acted on. |
| `model_runs` | `provider_runs`, `provider_run_metrics`, `provider_run_artifacts` | Provider call log, latency/tokens/errors, and optional raw artifacts. |
| `ops` | `jobs`, `job_events`, `maintenance_runs`, `backup_checks`, `schema_migrations` | Operational state and maintenance history. |
| `search` | `pages_fts`, `embeddings`, `search_index_meta`, `search_events` | Rebuildable search indexes and lightweight search telemetry. |
| `security_access` | `users`, `sessions`, `vaults`, `vault_members`, `agent_tokens`, `agent_access_events`, `audit_events` | Auth, scoped agent access, and audit trails. |

## Entity Boundaries

### Snapshots vs Packets

`snapshot` means point-in-time project state.

`packet` means selected context sent to an AI/operator.

Current `project_snapshot_packets` mixes both concepts. DB v2 should split it:

| Current Responsibility | v2 Target |
|---|---|
| generated_at, project/vault state hash, state summary | `snapshots` |
| target_agent, profile, output_mode, focus, contract version, content hash | `packets` |
| selected source IDs and content hashes | `packet_sources` |
| compact node summaries included in packet | `node_cards` |
| generated packet body | file artifact or rebuildable generated content, not a large relational payload |

### Findings

`findings` should be small and stable:

```txt
id, review_id, title, area, severity, status, created_at
```

Evidence, locations, and decisions should not be overwritten into the same row.

| Entity | Responsibility |
|---|---|
| `finding_evidence` | evidence text, evidence_quality, source_agent/model, upgrade path |
| `finding_locations` | source path, line range, snippet, SARIF/code scanning readiness |
| `finding_decisions` | accept/reject/defer/implemented decisions and operator notes |
| `tasks` | implementation action generated from accepted findings |

This structure lets SARIF export read locations directly instead of inferring
from implementation records.

### Model Runs

Current `model_review_runs` mixes provider metrics, review lifecycle, trace, and
raw payloads.

| Current Responsibility | v2 Target |
|---|---|
| provider/model/status/error/timing/token counts | `provider_runs` and `provider_run_metrics` |
| trace_id, packet_trace_id | `provider_runs` |
| review_id/finding_count/import status | relation to `reviews` |
| request_json/response_json | `provider_run_artifacts` file pointer, or drop after summary if operator chooses |

Raw provider payloads are the first large-payload candidate to move out of DB.

## Current-To-v2 Mapping

| Current Table | v2 Target | Action |
|---|---|---|
| `pages` | `content.pages` | keep |
| `revisions` | `content.revisions` | keep |
| `links` | `content.links` or rebuild from Markdown | rebuild/keep derived |
| `sections` | `content.sections` | rebuild |
| `citations` | `content.citations` plus audit/enrichment fields | keep/split later only if needed |
| `citation_audits` | `citation_audit.citation_audits` | keep |
| `citation_evidence_snapshots` | `citation_audit.citation_evidence` | keep |
| `citation_audit_events` | `citation_audit.citation_events` | keep |
| `graph_nodes`, `graph_edges` | `graph.graph_nodes`, `graph.graph_edges` | rebuild |
| `graph_layout_cache` | cache or remove | rebuild/delete |
| `graph_node_pins` | `graph.graph_pins` | keep if UI pinning remains |
| `collaboration_reviews` | `ai_collaboration.reviews` | keep |
| `collaboration_findings` | `findings` + `finding_evidence` + `finding_locations` + `finding_decisions` | split |
| `implementation_records` | `implementation.implementation_records` | keep |
| `finding_tasks` | `implementation.tasks` | keep/rename |
| `project_snapshot_packets` | `snapshots` + `packets` + `packet_sources` | split |
| `ai_state_pages` | generated AI state cache | rebuild |
| `context_bundle_manifests` | `packet_sources` or delete | usage-check |
| `experiment_packets` | `packets` or delete | usage-check |
| `experiment_packet_responses` | `reviews` or delete with experiment data | usage-check |
| `model_review_runs` | `provider_runs` + `provider_run_metrics` + `provider_run_artifacts` | split |
| `embeddings` | `search.embeddings` | rebuild |
| `pages_fts` | `search.pages_fts` | rebuild |
| `search_index_meta` | `search.search_index_meta` | rebuild/keep |
| `jobs`, `job_events` | `ops.jobs`, `ops.job_events` | keep with retention |
| `maintenance_locks` | `ops.maintenance_locks` | reset-safe transient |
| `maintenance_runs` | `ops.maintenance_runs` | keep or retention |
| `users`, `sessions`, `vaults`, `vault_members` | `security_access.*` | keep; sessions can be cleared intentionally |
| `agent_tokens`, `agent_access_events`, `audit_events` | `security_access.*` | keep |
| `audit_log`, `audit_log_to_events` | migrate to `audit_events` then remove | delete legacy bridge |
| `messages`, `suggestions`, `submissions`, `ai_actors` | unresolved | usage-check; likely merge/delete if replaced |

## Simplification Candidates

Delete after usage check:

- `context_bundle_manifests`
- `experiment_packets`
- `experiment_packet_responses`
- `ai_actors`

Merge or replace:

- `audit_log` into `audit_events`
- `messages`/`suggestions`/`submissions` into either content import records or
  findings, if they still represent active workflows

Split:

- `collaboration_findings`
- `project_snapshot_packets`
- `model_review_runs`

Rebuild:

- FTS/search indexes
- AI state pages
- graph materialization
- generated packet content and quality summaries

## Reset vs Migration Decision

Recommended strategy: `guided_migration`.

Reason:

- Reset-only is clean but would discard pages, revisions, findings, reviews,
  implementation evidence, tokens, and audit events.
- Dual-read preserves compatibility but is unnecessary in this early local-first
  project.
- Guided migration preserves durable data and rebuilds derived state.

Preserve:

- content and revision data
- citation audit/evidence/events
- reviews/findings/tasks/implementation records
- access tokens/events/audit data
- model run metrics and trusted summaries

Rebuild:

- FTS and embeddings
- graph tables when derivable
- AI state cache
- packet quality/self-test summaries
- generated packet bodies when manifest/schema/source hashes are enough

Discard or operator-decide:

- old experiment packets
- context bundle manifests
- raw provider request/response JSON
- legacy import/message tables

Rollback:

1. Create a tar.gz backup containing the SQLite DB, pages, revisions, and
   manifest.
2. Apply migration to a copied DB first.
3. Run schema integrity checks and targeted API tests.
4. Promote only after checks pass.
5. Rollback means restore the pre-migration snapshot. Do not design in-place
   down migrations for DB v2.

## Migration System Policy

Use a light migration system before DB v2 table changes.

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  checksum TEXT NOT NULL
);
```

Policy:

- `schema.sql` remains the latest full schema reference.
- Migration files are append-only once applied.
- Applied migration checksums must match the file contents.
- Development may auto-apply when explicitly enabled.
- Tests run from a clean schema path.
- Operator/production mode requires an explicit migration command.
- Do not remove `schema.sql`.
- Do not add dual-read compatibility unless a real external user requires it.

Suggested migration folder:

```txt
apps/api/knownet_api/db/migrations/
  001_init.sql
  002_search_fts.sql
  003_sarif_locations.sql
```

## DB v2 Acceptance Criteria

1. A new developer can explain the entity groups in one page.
2. Findings no longer mix identity, evidence, locations, decisions, tasks, and
   export behavior in one row.
3. Packets and snapshots have distinct table meanings.
4. Derived tables are marked rebuildable.
5. Reset-safe tables are documented.
6. SARIF, packets, and MCP can read from normalized sources without ad hoc
   inference from unrelated tables.
7. Tests can create a new DB without manual `ALTER TABLE` drift.
8. DB v2 stays on SQLite.
9. Code scanning/SARIF export can use `finding_locations` directly.

## Next Implementation Step

First DB implementation surface:

```txt
apps/api/knownet_api/db/v2_schema.sql
apps/api/knownet_api/db/v2_migrate.py
apps/api/tests/test_phase29_db_v2_migration.py
```

This creates a clean v2 SQLite file from the current DB without modifying the
live DB. It implements the intended "clean reconstruction + migrate only needed
data" path:

1. create a fresh v2 DB from `v2_schema.sql`
2. preserve durable content/security/review/task/model-run records
3. split findings, packets/snapshots, and model runs into cleaner tables
4. rebuild/leave empty derived search, graph cache, and AI state tables
5. skip legacy inbox/experiment/actor tables unless later usage proves they are
   still product data

CLI:

```powershell
cd apps/api
python -m knownet_api.db.v2_migrate --source ../../data/knownet.db --target ../../data/knownet-v2.db --backup ../../data/backups/knownet-pre-v2.db
```

The current app still reads the current schema. Promoting v2 to the live DB is
a separate operator decision after targeted route tests pass against the v2
file.

Next DB implementation phase after this: runtime adoption or schema migration
command integration.

Do not start with `collaboration_findings` split. That split is valuable, but
it should happen in runtime only after the migration table/checksum flow exists.

Do not do next:

- do not split collaboration tables before migration support exists
- do not delete raw provider responses until preserve/rebuild policy is final
- do not build dual-read compatibility
- do not remove `schema.sql`
- do not combine migration system, schema split, and deletion cleanup in one
  implementation phase
