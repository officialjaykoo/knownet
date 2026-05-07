# Current Schema Inventory

Status: Phase 29 first/second-pass inventory
Source: `apps/api/knownet_api/db/schema.sql`

This inventory classifies current tables by product responsibility and reset
behavior. Some tables are mixed; those are called out at column/responsibility
level instead of pretending the whole table has one lifecycle.

Definitions:

- `source`: durable state that should be migrated if the operator keeps data.
- `derived`: reproducible from Markdown, files, schema, or another source.
- `mixed`: contains both durable metadata and rebuildable/generated payload.
- `reset-safe`: can be deleted and regenerated without losing user/AI intent.
- `user-data`: operator-authored or AI-authored durable data.

## Summary

| Group | Tables |
|---|---|
| `core_content` | `pages`, `revisions`, `links`, `citations`, `citation_audits`, `citation_evidence_snapshots`, `citation_audit_events`, `sections`, `system_pages` |
| `graph` | `graph_nodes`, `graph_edges`, `graph_layout_cache`, `graph_node_pins` |
| `ai_collaboration` | `collaboration_reviews`, `collaboration_findings`, `implementation_records`, `finding_tasks`, `experiment_packet_responses` |
| `ai_context` | `project_snapshot_packets`, `ai_state_pages`, `context_bundle_manifests`, `experiment_packets` |
| `model_runs` | `model_review_runs` |
| `ops` | `jobs`, `job_events`, `maintenance_locks`, `maintenance_runs` |
| `search` | `embeddings`, `search_index_meta`, `pages_fts` |
| `security_access` | `users`, `sessions`, `vaults`, `vault_members`, `agent_tokens`, `agent_access_events`, `audit_events` |
| `legacy_or_questionable` | `messages`, `suggestions`, `submissions`, `ai_actors`, `audit_log`, `audit_log_to_events` |

## Core Content

| Table | Purpose | Owner Surface | Truth | Write Path | Read Path | Reset-safe | v2 Action |
|---|---|---|---|---|---|---|---|
| `pages` | Page registry, slug, status, current revision pointer | API/Rust content mutation | source | page create/update/tombstone | page, search, graph, packets | no | keep |
| `revisions` | Immutable page body file metadata | API/Rust page revision writes | source | page save/import | page read, snapshot, search index | no | keep |
| `links` | Parsed page links and backlinks | Markdown parser/indexer | derived | page parse/rebuild | graph/search/navigation | yes | rebuild or keep as derived index |
| `citations` | Citation references plus validation/display fields | Markdown parser and citation audit flow | mixed | page parse/audit update | citation UI, release evidence | partial | split derived citation refs from durable validation/enrichment if v2 grows |
| `citation_audits` | Claim/citation audit status | citation audit workflow | source | audit command/API | release evidence, citation UI | no | keep |
| `citation_evidence_snapshots` | Captured citation evidence excerpts | citation audit workflow | source | audit capture | evidence review | no | keep; move large payloads to files only if size becomes a problem |
| `citation_audit_events` | Audit status/event history | citation audit workflow | source | audit status changes | audit trail | no | keep |
| `sections` | Parsed headings/section index | Markdown parser/indexer | derived | page parse/rebuild | search/context bundles | yes | rebuild |
| `system_pages` | Managed page registry and lock metadata | system page seeding/indexing | mixed | seed/sync flow | AI state, docs/status | partial | keep only if locks/operator metadata are needed; rebuild generated rows |

## Graph

| Table | Purpose | Owner Surface | Truth | Write Path | Read Path | Reset-safe | v2 Action |
|---|---|---|---|---|---|---|---|
| `graph_nodes` | Materialized graph node records | graph rebuild | derived | graph rebuild | map/API/packets | yes | rebuild |
| `graph_edges` | Materialized graph edges | graph rebuild | derived | graph rebuild | map/API/packets | yes | rebuild |
| `graph_layout_cache` | Cached layout coordinates | graph/UI | cache | layout generation | map UI | yes | delete/rebuild |
| `graph_node_pins` | Operator pin preferences | UI/operator | source | map UI | map UI | no | keep as user preference if still used |

## AI Collaboration And Implementation

| Table | Purpose | Owner Surface | Truth | Write Path | Read Path | Reset-safe | v2 Action |
|---|---|---|---|---|---|---|---|
| `collaboration_reviews` | External/internal AI review records | AI review import/API | source | review import/provider run | AI Reviews UI, packets | no | keep as `reviews` |
| `collaboration_findings` | Finding identity, evidence, status, location, SARIF fields | review import/operator | mixed source | review parser/operator | findings, tasks, SARIF, release | no | split into `findings`, `finding_evidence`, `finding_locations`, `finding_decisions` |
| `implementation_records` | Evidence that a finding/task was implemented | Codex/operator | source | implementation submit | release evidence/SARIF context | no | keep |
| `finding_tasks` | Implementation task queue from findings | task bridge/operator | mixed source/derived | finding accept/task creation | task UI/API | partial | keep or merge into `tasks`; do not auto-rebuild blindly |
| `experiment_packet_responses` | AI responses to experiment packets | experiment import | source if experiments matter | response import | review comparison | no | map to `reviews` or delete with operator confirmation |

## AI Context, Snapshots, And Packets

| Table | Purpose | Owner Surface | Truth | Write Path | Read Path | Reset-safe | v2 Action |
|---|---|---|---|---|---|---|---|
| `project_snapshot_packets` | Packet delivery record plus content pointer, quality, contract metadata | packet generator | mixed | packet generation | packet API/UI | partial | split into `snapshots` and `packets`; generated content is rebuildable, manifest/contract metadata is durable |
| `ai_state_pages` | AI-readable state extracted from pages | state indexer | derived | state rebuild | packet generator, quality check | yes | rebuild/cache |
| `context_bundle_manifests` | Context bundle manifest/content hash records | earlier packet/bundle flow | questionable | bundle generation | unknown/legacy | decide | usage-check; likely delete/defer |
| `experiment_packets` | Experimental packet definitions/content | earlier external AI experiments | questionable | experiment generator | experiments/reviews | decide | usage-check; likely delete/defer or map to `packets` |

Column-level note for `project_snapshot_packets`:

| Responsibility | Lifecycle |
|---|---|
| target/profile/focus/output mode/schema/contract/hash/generated_at | source packet delivery record |
| content path/body | generated artifact; rebuildable if sources still exist |
| quality warnings/self-test summaries | derived; recompute or omit from compact packets |

## Model Runs

| Table | Purpose | Owner Surface | Truth | Write Path | Read Path | Reset-safe | v2 Action |
|---|---|---|---|---|---|---|---|
| `model_review_runs` | Provider call log, metrics, trace, request/response payload, review lifecycle link | provider runner | mixed source | provider runner | model runs UI, packet summary | no | split into `provider_runs`, `provider_run_metrics`, `provider_run_artifacts`; move/summarize raw provider payloads |

Column-level note for `model_review_runs`:

| Responsibility | Lifecycle |
|---|---|
| provider/model/status/error/duration/tokens/trace_id/packet_trace_id | source metrics/log |
| review_id/finding_count/import status | collaboration lifecycle link |
| request_json/response_json | large audit artifact; decide file move or summary retention |

## Ops

| Table | Purpose | Owner Surface | Truth | Write Path | Read Path | Reset-safe | v2 Action |
|---|---|---|---|---|---|---|---|
| `jobs` | Background/import job queue | API/worker | mixed | worker/API | ops UI/logs | partial | keep active jobs; consider pruning completed jobs |
| `job_events` | Job event history | worker/API | source | job lifecycle | ops/debug | no if history matters | keep with retention policy |
| `maintenance_locks` | Maintenance write lock state | maintenance API | transient | maintenance start/end | mutation middleware | yes | keep/clear on startup recovery |
| `maintenance_runs` | Maintenance run reports | maintenance API | source/support | maintenance tasks | ops UI | no if audit matters | keep or summarize with retention |

## Search

| Table | Purpose | Owner Surface | Truth | Write Path | Read Path | Reset-safe | v2 Action |
|---|---|---|---|---|---|---|---|
| `embeddings` | Semantic search vectors | embedding indexer | derived/cache | embedding rebuild | semantic search | yes | rebuild |
| `search_index_meta` | Search index status and rebuild metadata | search maintenance | derived/ops | rebuild/verify | health/search UI | yes | keep/rebuild |
| `pages_fts` | SQLite FTS5 full-text index | search indexer | derived | rebuild/write sync | search | yes | rebuild |

## Security And Access

| Table | Purpose | Owner Surface | Truth | Write Path | Read Path | Reset-safe | v2 Action |
|---|---|---|---|---|---|---|---|
| `users` | Local users | auth | source | auth/bootstrap | auth | no | keep |
| `sessions` | Login sessions | auth | transient source | login/logout | auth middleware | yes with logout | keep; safe to clear intentionally |
| `vaults` | Vault/container registry | auth/content | source | bootstrap/admin | auth/content | no | keep |
| `vault_members` | Vault ACL | auth/admin | source | bootstrap/admin | auth | no | keep |
| `agent_tokens` | Hashed external agent tokens/scopes/limits | agent access | source | token issue/revoke | agent auth | no | keep |
| `agent_access_events` | Agent access audit trail | agent access | source | agent API | audit/security | no | keep, possibly retention |
| `audit_events` | Canonical audit trail | API/Rust trigger | source | API/Rust/audit bridge | audit/security | no | keep |

## Legacy Or Questionable

| Table | Purpose | Owner Surface | Truth | Write Path | Read Path | Reset-safe | v2 Action |
|---|---|---|---|---|---|---|---|
| `messages` | Earlier inbox/import messages | import/inbox | source if used | import pipeline | suggestions/jobs | no if active | usage-check; delete if inactive |
| `suggestions` | Earlier generated suggestions | import/inbox | source if used | suggestion pipeline | operator review | decide | usage-check; merge with findings or delete |
| `submissions` | Earlier submission workflow | import/content | source if used | submission API | operator review | decide | usage-check; merge with content/import flow or delete |
| `ai_actors` | Earlier AI actor registry | legacy/model access | questionable | unknown/legacy | unknown | decide | usage-check; delete if replaced by provider config/agent tokens |
| `audit_log` | Older audit log table | legacy trigger source | legacy source | legacy writes | trigger to `audit_events` | no until migrated | merge into `audit_events`, then delete |
| `audit_log_to_events` | Trigger bridge from old audit table | legacy compatibility bridge | derived bridge | SQLite trigger | audit migration | yes after migration | remove in v2 after audit bridge is gone |

## Reset Classification

Reset-safe/rebuildable:

- `links`
- `sections`
- `embeddings`
- `graph_nodes`
- `graph_edges`
- `graph_layout_cache`
- `ai_state_pages`
- `search_index_meta`
- `pages_fts`
- generated packet content and quality summaries
- `maintenance_locks`

Preserve by default:

- `pages`, `revisions`
- citation audit/evidence/event tables
- `collaboration_reviews`, `collaboration_findings`
- `implementation_records`, `finding_tasks`
- users/vaults/access/audit tables
- trusted model run summaries/metrics

Decide before DB v2 implementation:

- `messages`, `suggestions`, `submissions`, `ai_actors`
- `context_bundle_manifests`, `experiment_packets`,
  `experiment_packet_responses`
- raw provider request/response JSON in `model_review_runs`
- `graph_node_pins` if UI pins are still valuable user preferences

