# Phase 29 Tasks: DB v2 Design

Status: in progress
Created: 2026-05-07
Updated: 2026-05-08

Phase 29 is a design phase, not a schema rewrite.

Implementation status:

```txt
P29-001 Current Schema Inventory: completed in docs/db/SCHEMA_INVENTORY.md.
P29-002 Entity Boundary Design: completed in docs/db/DB_V2_BLUEPRINT.md.
P29-003 Current-To-v2 Mapping: completed in docs/db/DB_V2_BLUEPRINT.md.
P29-004 Reset vs Migration Decision: drafted in docs/db/DB_V2_BLUEPRINT.md.
P29-005 Migration System Design: drafted in docs/db/DB_V2_BLUEPRINT.md.
P29-006 Deletion And Simplification Candidates: drafted in docs/db/DB_V2_BLUEPRINT.md.
P29-007 DB v2 Acceptance Criteria: drafted in docs/db/DB_V2_BLUEPRINT.md.
P29-008 Phase 30 Recommendation: drafted in docs/db/DB_V2_BLUEPRINT.md.
Clean v2 reconstruction tool: implemented in apps/api/knownet_api/db/v2_schema.sql
and apps/api/knownet_api/db/v2_migrate.py.

No live DB schema rewrite has been applied.

Validation:
  - docs link check passed on 2026-05-08.
  - schema inventory covers 42 tables and 1 trigger from schema.sql.
```

Execution note:

```txt
Phase 30 source/docs/scripts cleanup was implemented before Phase 29 DB work.
That is intentional. Phase 30 avoided DB schema changes and reduced source-tree
risk before this DB v2 design is implemented. Phase 29 remains the active DB
design and migration-decision phase.
```

Phase 28 completed the SARIF location-quality path. At this point KnowNet has
enough real surface area to see the database shape more honestly:

```txt
content and graph
external AI packets and snapshots
AI reviews and findings
implementation tasks and evidence
model/provider runs
ops, search, backup, access, and audit state
```

The current schema works, but it grew by phases. Phase 29 decides whether and
how KnowNet should move toward a clearer DB v2 without rushing into a risky
rewrite.

## Fixed Rules

Do not:

- Rewrite the database in this phase.
- Drop user data in this phase.
- Add new product features just to justify a schema.
- Introduce PostgreSQL, pgvector, Elasticsearch, or another server database.
- Normalize every column into tiny tables.
- Design for hypothetical enterprise scale.
- Add compatibility layers for old APIs unless a real migration needs them.
- Touch compact packets, SARIF export behavior, or MCP contracts unless the DB
  boundary analysis proves they are coupled incorrectly.

Do:

- Keep SQLite as the target database.
- Treat the current schema as evidence, not as sacred.
- Separate durable product entities from derived/export/cache tables.
- Prefer local-first simplicity over perfect relational purity.
- Identify which current tables are core, support, cache, export, or legacy.
- Design for reset/migration choices explicitly.
- Keep DB v2 small enough that a new developer can explain it in one page.

## Why This Phase Exists

The current schema has been useful because it let KnowNet move fast. But several
tables are now doing more than one job:

```txt
collaboration_findings:
  review output + release evidence + task source + SARIF candidate

project_snapshot_packets:
  packet manifest + content pointer + quality state + contract metadata

model_review_runs:
  provider call log + review lifecycle + metrics trace
```

That does not mean the project is wrong. It means the real product shape has
finally emerged. Phase 29 captures that shape before more features make the DB
harder to reason about.

## Target Score

Current schema estimate:

```txt
62 / 100
```

Good DB v2 design target:

```txt
85 / 100
```

The goal is not 100. A 100-point schema would likely be too abstract and too
heavy for a local-first tool. The target is a schema that is easier to explain,
test, reset, and export.

## P29-001 Current Schema Inventory

Problem:

KnowNet has enough tables that it is no longer obvious which tables are core
product state and which are derived artifacts.

Implementation shape:

Create a DB inventory document section that groups every table into one of:

```txt
core_content
graph
ai_collaboration
ai_context
model_runs
ops
search
security_access
cache_or_export
legacy_or_questionable
```

For each table, record:

```txt
purpose
owner surface
source of truth or derived
write path
read path
safe to reset? yes/no
v2 action: keep / split / merge / delete / defer
```

Inventory rule:

```txt
Classify source-of-truth at column level when a table mixes durable metadata and
derived payloads. Do not classify an entire table as one thing when columns have
different reset/migration behavior.

reset-safe = reproducible from Markdown, files, schema, or another canonical
source.
user-data = operator-authored or AI-authored durable data that cannot be
recreated exactly.
```

Example:

```txt
project_snapshot_packets:
  manifest/contract metadata -> source of truth
  generated content          -> derived/rebuildable
  quality score              -> derived/recomputable
```

Done when:

- Every current table in `schema.sql` is classified.
- No table is left as "misc".
- Reset-safe tables are separated from user-data tables.

## P29-002 Entity Boundary Design

Problem:

Some current entities mix several responsibilities. DB v2 needs cleaner
boundaries before any migration exists.

Implementation shape:

Design the v2 entity groups:

```txt
content:
  pages, revisions, sections, citations

graph:
  graph_nodes, graph_edges, graph_snapshots

ai_context:
  snapshots, packets, packet_sources, node_cards

ai_collaboration:
  reviews, findings, finding_evidence, finding_locations, finding_decisions

implementation:
  tasks, implementation_records, verification_records

model_runs:
  provider_runs, provider_run_metrics, provider_run_artifacts

ops:
  health_events, search_events, backup_checks, schema_migrations

security_access:
  agent_tokens, agent_access_events, audit_events
```

Rules:

- `findings` should be small and stable.
- `finding_locations` should carry source/SARIF location data.
- `finding_evidence` should carry evidence quality, source, and promotion path.
- `finding_decisions` should carry accept/reject/defer/operator decisions and
  must not mutate the original evidence record.
- `packets` should point to content, not embed the full content in relational
  columns.
- `snapshots` should mean point-in-time project state.
- `packets` should mean selected context sent to an AI/operator.
- `project_snapshot_packets` is the naming smell to resolve: decide which
  fields become snapshot history and which fields become packet delivery
  records.

Done when:

- DB v2 entity diagram or table list exists.
- Each entity has a one-sentence responsibility.
- Findings/evidence/location/task boundaries are explicit.

## P29-003 Current-To-v2 Mapping

Problem:

A cleaner schema is only useful if the project knows how existing data would
map into it.

Implementation shape:

Create a mapping table:

```txt
current table.column -> v2 table.column
current table.column -> drop
current table.column -> derived/rebuild
current table.column -> unresolved question
```

Required focus areas:

- `collaboration_reviews`
- `collaboration_findings`
- `implementation_records`
- `finding_tasks`
- `model_review_runs`
- `project_snapshot_packets`
- `experiment_packets`
- `context_bundle_manifests`
- `pages_fts` and future search tables

Rules:

- Prefer `unresolved question` over a forced destination when the correct v2
  shape is not known.
- Treat `model_review_runs` as a split candidate:
  provider call log, review lifecycle, metrics trace, and raw provider response
  are different responsibilities.
- Decide whether raw provider responses stay in DB, move to files, or are
  dropped after summary extraction. They are the first large-payload candidate
  to move out of relational rows.
- Verify whether `experiment_packets` and `context_bundle_manifests` are active
  product records or deletion candidates before assigning v2 destinations.

Done when:

- No high-value current data lacks a v2 destination.
- Derived/cache/export data is marked rebuildable where appropriate.
- The mapping identifies at least five simplification opportunities.

## P29-004 Reset vs Migration Decision

Problem:

KnowNet is still early enough that a clean reset may be possible, but the
decision should be explicit rather than emotional.

Implementation shape:

Define three paths:

```txt
reset_only:
  throw away local DB and rebuild from markdown/content where possible

guided_migration:
  migrate durable content/reviews/findings and rebuild derived state

dual_read:
  temporarily read old and new schema while writing new schema
```

Default recommendation should be chosen by criteria:

```txt
if user data is disposable -> reset_only
if pages/reviews/findings matter -> guided_migration
if production users exist -> dual_read
```

Current recommended strategy:

```txt
guided_migration
```

Reason:

```txt
pages, revisions, reviews, findings, decisions, tokens, audit events, and
implementation evidence are not safely reproducible. Reset-only would discard
real user/AI collaboration data. Dual-read is unnecessary until there are real
external production users that require rolling compatibility.
```

Preserve vs rebuild draft:

```txt
preserve:
  pages, revisions, sections, citations
  collaboration_reviews, collaboration_findings
  implementation_records, finding_tasks
  agent_tokens, agent_access_events, audit_events

rebuild:
  pages_fts and future search indexes
  graph_nodes and graph_edges when derivable from pages/citations/reviews
  packet quality scores and validation summaries
  generated packet content when the source manifest and schema version are
  enough to regenerate it

decide explicitly:
  raw model/provider responses
  experiment_packets
  context_bundle_manifests
```

Rollback story:

```txt
Before guided migration, create a tar.gz snapshot containing the SQLite file,
pages, revisions, and manifest. Apply migration to a copied DB first. Promote
only after integrity checks and targeted API tests pass. Rollback means restore
the pre-migration snapshot; do not attempt in-place down migrations for v2.
```

Rules:

- Do not keep compatibility just because it feels safe.
- Do not delete data unless the operator explicitly chooses reset.
- Do not build dual-read unless there is a real external user/data constraint.

Done when:

- Phase 29 recommends one migration/reset strategy.
- The document states what data would be preserved or discarded.
- The strategy has a rollback story.

## P29-005 Migration System Design

Problem:

Before any real DB v2 implementation, KnowNet needs a migration policy that is
lighter than enterprise migration stacks but safer than scattered `ALTER TABLE`
calls.

Implementation shape:

Design the migration minimum:

```txt
schema_migrations(version, name, applied_at, checksum)
migrations/
  001_init.sql
  002_search_fts.sql
  003_sarif_locations.sql
```

Rules:

- `schema.sql` remains the latest full schema reference.
- Migration files are append-only once applied.
- Startup applies missing migrations only when explicitly enabled or in local
  development mode.
- Tests create DBs through the same migration path or compare schema parity.
- Applied migration checksums are immutable. Startup or migration validation
  must detect if an already-applied migration file was edited later.
- Environment behavior must be explicit:
  development may auto-apply missing migrations when enabled; tests run from a
  clean slate; production/operator mode requires an explicit migration command.
- `schema.sql` is the latest full schema reference; migration files are the
  append-only change history. Do not remove `schema.sql` in DB v2.

Done when:

- A migration policy is documented.
- The document chooses whether Phase 30 should implement migrations before DB
  v2 tables.
- The policy says where startup-time ALTERs are allowed and where they are not.

## P29-006 Deletion And Simplification Candidates

Problem:

Not every table or column deserves a v2 home. Some are transitional evidence
from previous phases.

Implementation shape:

Produce a candidate list:

```txt
delete
merge
split
rename
keep unchanged
rebuild from files
```

Expected candidate categories:

```txt
delete or defer after usage check:
  experiment_packets
  context_bundle_manifests

move or summarize:
  model_review_runs.raw_response

split:
  collaboration_findings -> findings + finding_evidence + finding_locations +
  finding_decisions
  project_snapshot_packets -> snapshots + packets

rebuild:
  pages_fts
  graph tables if their source graph can be regenerated

keep:
  agent_tokens, audit_events, implementation_records unless inventory proves
  otherwise
```

Questions to answer:

- Which packet/snapshot records are durable history versus reproducible files?
- Which AI review artifacts are audit records versus temporary import helpers?
- Which model-run fields are metrics versus provider response payload?
- Which SARIF fields should live in DB versus be generated at export time?
- Which docs/phase metadata should not be in the DB at all?

Done when:

- There is a concrete list of simplifications.
- Each deletion candidate has a reason and a risk.
- No deletion is performed in Phase 29.

## P29-007 DB v2 Acceptance Criteria

Problem:

Without acceptance criteria, "better schema" becomes taste.

Implementation shape:

Define measurable DB v2 criteria:

```txt
1. A new developer can explain the top-level entity groups in one page.
2. Findings no longer carry task/evidence/location/export responsibilities in
   the same row.
3. Packets and snapshots have distinct meanings and table shapes.
4. Derived tables are marked rebuildable.
5. Reset-safe tables are documented.
6. SARIF, packets, and MCP can read from the same normalized sources without
   special-case joins everywhere.
7. Tests can create a new DB without manual ALTER drift.
8. DB v2 does not require a server database.
9. Findings can export to SARIF without special-case inference from
   implementation_records; `finding_locations` directly provides path/range
   data where available.
```

Done when:

- DB v2 has a score target and acceptance checklist.
- Phase 30 can be chosen from this checklist.

## P29-008 Phase 30 Recommendation

Problem:

Phase 29 should end with a clear next step, not just a nice diagram.

Implementation shape:

Recommend one of:

```txt
Phase 30A: migration system first
Phase 30B: FTS/search reliability first
Phase 30C: collaboration schema split first
Phase 30D: reset-only DB v2 prototype
```

Default expected recommendation:

```txt
Phase 30A: migration system first
```

Updated execution note:

```txt
Phase 30 source/docs/scripts cleanup already happened before DB work. The next
DB implementation phase should be named Phase 31 or Phase 30A only if the team
chooses to keep the old label. Its scope should be migration system first, not
collaboration schema splitting.
```

Reason:

Before moving columns/tables, KnowNet should stop accumulating startup-time
schema drift.

Done when:

- The phase document names the next implementation phase.
- The next phase has a small first task.
- The document explicitly says what not to do next.

What not to do next:

```txt
- Do not split collaboration_findings before the migration system exists.
- Do not delete raw provider responses before preserve/rebuild policy is final.
- Do not build dual-read without real external user-data constraints.
- Do not remove schema.sql or switch to migration-files-only management.
- Do not combine migration system, schema split, and deletion cleanup in one
  implementation phase.
```

## Acceptance

```txt
1. Current schema inventory is complete.
2. DB v2 entity groups are defined.
3. Current-to-v2 mapping exists for major collaboration, packet, model-run, and
   content tables.
4. Reset vs migration recommendation is explicit.
5. Migration system policy is documented.
6. Deletion/simplification candidates are listed but not executed.
7. DB v2 acceptance criteria are measurable.
8. Phase 30 recommendation is concrete.
9. No code schema rewrite happens in Phase 29 unless separately approved.
```

## Suggested Work Order

```txt
P29-001 Current Schema Inventory
P29-002 Entity Boundary Design
P29-003 Current-To-v2 Mapping
P29-006 Deletion And Simplification Candidates
P29-004 Reset vs Migration Decision
P29-005 Migration System Design
P29-007 DB v2 Acceptance Criteria
P29-008 Phase 30 Recommendation
```

## Out Of Scope

```txt
- Applying DB v2
- Dropping tables
- Moving live data
- Adding PostgreSQL or external search/vector stores
- Rewriting the Rust daemon storage layer
- Rewriting packet/SARIF/MCP APIs
- Building dual-read compatibility without a concrete user-data reason
- Full release_check
```
