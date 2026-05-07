# Phase 31 Tasks: DB v2 Runtime Adoption

Status: completed
Created: 2026-05-08
Updated: 2026-05-08

Phase 29 designed and generated a clean DB v2 file. Phase 31 connects the
application runtime to that v2 schema.

Current state:

```txt
data/knownet.db has been promoted to DB v2 and passes targeted validation.
The API runtime reads/writes v2 schema table names.
Old source table names are kept only for migration input in v2_migrate.py.
```

Phase 31 is the point where KnowNet stops treating v2 as an export artifact and
starts making v2 the actual runtime schema.

Implementation status:

```txt
P31-001 v2 Schema Boot Path: implemented.
  Implemented explicit KNOWNET_DB_VERSION setting.
  Implemented v2_schema.sql init/verification helpers.
  Implemented required-table, checksum, and integrity fail-loud validation.
  Added targeted tests in tests/test_phase31_v2_boot.py.
P31-002 Collaboration Query Rewrite: core endpoint group implemented.
  Added v2 collaboration service helpers for reviews/findings/evidence/locations/decisions/tasks.
  Wired review import/list/detail, finding decisions, task creation/list/detail,
  implementation evidence, duplicate checks, and finding queue to v2 tables when
  KNOWNET_DB_VERSION=v2.
  Decision/implementation changes insert finding_decisions rows and keep
  finding_evidence immutable.
  Added targeted tests in tests/test_phase31_v2_collaboration.py.
P31-003 SARIF v2 Source: implemented.
  Export now reads findings/reviews/finding_evidence/finding_locations in v2 mode.
  finding_locations remains the primary SARIF physicalLocation source.
  implementation_records remain secondary changed-file evidence.
  Default export still filters to trusted evidence_quality and accepted/implemented statuses.
  v2 SARIF coverage added to tests/test_phase31_v2_collaboration.py.
P31-004 Packet And Snapshot Runtime Rewrite: implemented.
  Project snapshot packet creation reads v2 collaboration/task/provider/page state.
  Packet generation writes snapshots/packets/packet_sources/node_cards in v2 mode.
  Packet body remains a file artifact under data/project-snapshot-packets.
  Delta packets resolve since_packet_id from packets in v2 mode.
  Added v2 packet create/read persistence coverage to tests/test_phase31_v2_collaboration.py.
P31-005 Provider Run Runtime Rewrite: implemented.
  Model run create/list/detail/dry-run/import/cancel endpoints use provider_runs,
  provider_run_metrics, and provider_run_artifacts in v2 mode.
  Provider lifecycle state, metrics, and request/response artifacts are stored
  separately while preserving trace_id and packet_trace_id lineage.
  Provider fast-lane context now reports structured_state_pages instead of the
  removed v1 ai_state_pages cache.
  Operator provider matrix reads v2 provider summaries without loading raw
  response blobs into dashboard summaries.
  Added v2 provider runtime coverage to tests/test_phase31_v2_collaboration.py.
P31-006 Agent And Operator Summary Rewrite: implemented.
  Operator AI state quality uses v2 pages/reviews/findings summaries in v2 mode
  and returns explicit empty_state metadata for fresh installs or cleared DBs.
  Agent reviews/findings/state-summary/ai-state endpoints read v2 reviews,
  findings, pages, and graph summaries and expose structured_state_pages.
  Collaboration next-action now resolves v2 tasks, accepted findings, backlog
  counts, and packet fallback routing from v2 tables.
  Added v2 operator/agent/next-action coverage to tests/test_phase31_v2_collaboration.py.
P31-007 Maintenance And Health v2 Checks: implemented.
  Health summary reports db_version and verified v2 schema checksum/integrity
  state in v2 mode.
  Maintenance verify-index validates v2 schema, v2 relationship integrity,
  provider run artifacts/metrics, packets, packet sources, node cards, and FTS
  status without checking removed v1 collaboration tables.
  Added v2 health/verify-index coverage to tests/test_phase31_v2_collaboration.py.
P31-008 Live DB Promotion: implemented.
  Added a guarded v2 promotion module and scripts/promote_db_v2.ps1 wrapper.
  The wrapper runs targeted v2 tests before apply, rebuilds a fresh v2 candidate
  from the current live DB, verifies checksum/integrity, and only then replaces
  data/knownet.db when -Apply is explicit.
  Promoted data/knownet.db to v2 and preserved the latest previous live DB at
  data/backups/knownet-pre-v2-live-20260507T170033Z.db.
  Added promotion coverage to tests/test_phase29_db_v2_migration.py.
P31-009 Post-Promotion Runtime Cleanup: implemented.
  Kept system_pages as a v2 first-class support table because onboarding and
  page-locking runtime paths still use it.
  Audit reads now use audit_events in v2 mode instead of the removed audit_log
  table.
  Added v2 audit endpoint coverage to tests/test_phase31_v2_collaboration.py
  and verified live v2 health plus audit access against data/knownet.db.
P31-010 Remove Remaining v1 Runtime Branches: implemented.
  Startup now initializes/verifies v2 only and no longer imports legacy
  collaboration, AI state, model-run, search, or citation-title boot helpers.
  SARIF export, maintenance verify-index, model-run context, next-action, and
  project snapshot packet creation no longer keep v1 fallback SQL branches.
  Retired experiment-packet and context-bundle endpoints return 410 with the
  compact project snapshot packet replacement instead of touching removed v1
  tables.
  Removed the obsolete services/ai_state.py module.
```

## Execution Warning

This is the highest-risk KnowNet phase so far. The schema change touches many
runtime query paths and a bad promotion can lose data or leave the app unable to
start.

Execution rules:

```txt
Do not implement P31-002 through P31-006 in parallel.
Move one runtime surface at a time.
After each surface, run targeted tests before touching the next surface.
Never promote data/knownet-v2.db while any old runtime query still exists.
```

The dangerous state is a half-migrated runtime where some endpoints read v1
tables and others read v2 tables. Avoid that by completing each task fully
before starting the next.

## Fixed Rules

Project direction:

```txt
Clean structure is more important than backward compatibility.
This is an early project, so legacy tables and legacy API internals may be
discarded when v2 has a cleaner path.
If an external standard fits, use it instead of inventing a private shape.
Do not make the system heavy to solve a local-first SQLite problem.
```

Do not:

- Build compatibility views just to keep old table names alive.
- Keep dual-write or dual-read unless a test proves it is required for a short
  transition.
- Add compatibility adapters just because old names existed.
- Preserve early phase tables because they exist.
- Reintroduce `collaboration_findings`, `collaboration_reviews`,
  `project_snapshot_packets`, or `model_review_runs` as new runtime surfaces.
- Hide schema mismatch with broad `try/except` fallbacks.
- Add PostgreSQL, an ORM rewrite, or a heavy migration framework.
- Touch packet/SARIF/MCP external contracts unless their queries must move to
  v2 tables.
- Invent a custom format where SQLite, SARIF, JSON Schema, W3C Trace Context,
  MCP, or another already-adopted standard covers the need.

Do:

- Use the v2 table names directly.
- Keep SQLite.
- Keep `schema.sql` as the current-schema reference until runtime adoption is
  complete, then decide whether it becomes v2 or moves to archive.
- Keep `v2_schema.sql` as the new clean source of truth during this phase.
- Prefer small query helper modules over large compatibility layers.
- Update tests as the authority for new table names.
- Promote `data/knownet-v2.db` only after targeted API tests pass.

## Why This Phase Exists

The v2 DB file has been created, but live code still queries old names:

```txt
collaboration_reviews
collaboration_findings
finding_tasks
project_snapshot_packets
model_review_runs
ai_state_pages
experiment_packets
context_bundle_manifests
```

That means replacing `knownet.db` with `knownet-v2.db` today would break the
API. Phase 31 removes that gap.

## Target

After Phase 31:

```txt
API startup initializes v2 schema.
AI reviews use reviews/findings/finding_evidence/finding_locations/finding_decisions.
Tasks use tasks.
Packets use snapshots/packets/packet_sources/node_cards.
Provider runs use provider_runs/provider_run_metrics/provider_run_artifacts.
SARIF reads finding_locations directly.
Operator/Agent dashboards read v2 summaries.
The app can run with data/knownet-v2.db as the live SQLite DB.
```

## P31-001 v2 Schema Boot Path

Problem:

Startup currently initializes the old schema through Rust `init_db`, `schema.sql`,
and several Python `ensure_*_schema` functions.

Implementation shape:

```txt
Add an explicit v2 DB mode or v2 init command.
Use v2_schema.sql to initialize clean DBs.
Record schema_migrations checksum.
Stop adding old phase-era tables during v2 boot.
```

Explicit DB version selection:

```txt
KNOWNET_DB_VERSION=v1  # default until promotion
KNOWNET_DB_VERSION=v2  # explicit v2 runtime
```

Do not auto-detect v2 by guessing table names. Automatic detection can hide a
partially migrated database.

Required v2 tables:

```txt
reviews
findings
finding_evidence
finding_locations
finding_decisions
tasks
snapshots
packets
packet_sources
provider_runs
provider_run_metrics
provider_run_artifacts
schema_migrations
```

Checksum rule:

```txt
If schema_migrations is missing or checksum does not match v2_schema.sql,
startup must fail loudly.
Do not continue with a warning.
Do not catch and ignore schema mismatch.
```

Rules:

- Do not delete the old boot path until v2 route tests pass.
- Do not auto-promote a DB just because v2 exists.
- The v2 path should fail loudly if required v2 tables are missing.

Done when:

- A test DB can be initialized from v2 schema without old collaboration/model
  tables.
- Startup or a dedicated command can verify `schema_migrations`.
- `data/knownet-v2.db` is recognized as a valid v2 DB.
- Missing required v2 tables fail startup/validation with an actionable error.
- Checksum mismatch fails startup/validation with an actionable error.

## P31-002 Collaboration Query Rewrite

Problem:

Collaboration routes still read/write `collaboration_reviews`,
`collaboration_findings`, and `finding_tasks`.

Implementation shape:

Move runtime queries to:

```txt
reviews
findings
finding_evidence
finding_locations
finding_decisions
tasks
implementation_records
```

Rules:

- Keep endpoint paths and response shapes stable where possible.
- Do not create compatibility views with old table names.
- When an endpoint returns a finding, join only the fields it actually needs.
- Decision changes must insert `finding_decisions` rows instead of mutating
  evidence.
- Status can remain on `findings` as the current materialized state, but
  evidence text and operator decision history must stay separate.

Execution unit:

```txt
One endpoint group at a time:
  route/service query
  write path
  tests
  targeted pytest
```

Do not rewrite all of `collaboration.py` in one pass.

State transition rule:

```txt
finding_decisions = immutable decision history
findings.status   = materialized current state
finding_evidence  = original observation/evidence, not decision history
```

Accept/defer/reject/implement paths must insert a `finding_decisions` row and
then update `findings.status`.

Done when:

- Review list/detail endpoints work against v2 tables.
- Finding accept/defer/reject/implement endpoints work against v2 tables.
- Task list/update endpoints use `tasks`.
- Phase 7 collaboration tests are updated to v2 names and pass.

## P31-003 SARIF v2 Source

Problem:

SARIF currently exports from the old all-in-one finding row and still has logic
to infer location from implementation records.

Implementation shape:

Read:

```txt
findings
reviews
finding_evidence
finding_locations
implementation_records
```

Rules:

- `finding_locations` is the primary source for SARIF physical locations.
- Implementation records are secondary evidence only, not the first location
  source.
- `context_limited` still must not export by default.
- Keep SARIF schema validation.
- Do not reintroduce file-location inference as the primary path.
- Keep Phase 28 source-location validation; only swap the DB source.

Done when:

- Phase 27/28 SARIF tests pass against v2 table names.
- SARIF ready/not-ready metadata still works.

## P31-004 Packet And Snapshot Runtime Rewrite

Problem:

Packet generation still writes `project_snapshot_packets` and reads old
collaboration/model-run tables.

Implementation shape:

Write/read:

```txt
snapshots
packets
packet_sources
node_cards
provider_runs
tasks
findings + finding_evidence + finding_decisions
```

Rules:

- `snapshot` is project state.
- `packet` is context delivered to an AI/operator.
- Generated packet bodies stay as file artifacts or content paths, not large DB
  payloads.
- Do not restore `experiment_packets` unless a live workflow still requires it.
- If an old experiment packet endpoint has no live operator workflow, remove it
  instead of porting it to v2.
- Do not store large packet JSON bodies in `packets`.

Done when:

- Project packet create/list/detail/compare endpoints use v2 tables.
- Compact packet output remains under the current semantic budget rules.
- Packet tests pass without old packet tables.

## P31-005 Provider Run Runtime Rewrite

Problem:

Model run routes and dashboards still use `model_review_runs`.

Implementation shape:

Use:

```txt
provider_runs
provider_run_metrics
provider_run_artifacts
```

Rules:

- Keep provider request/response artifacts optional.
- Store metrics separately from provider lifecycle state.
- Keep `trace_id` and `packet_trace_id`.
- Do not load large raw response artifacts into dashboard summaries.
- Large raw provider payloads should become file artifacts or be dropped after
  summary extraction if no audit need exists.
- `trace_id` and `packet_trace_id` are the packet -> provider run -> SARIF
  lineage. Do not lose them during the rewrite.

Done when:

- Model run create/import/list/detail endpoints work against v2 tables.
- Provider run tests pass.
- Operator dashboard uses v2 provider summaries.

## P31-006 Agent And Operator Summary Rewrite

Problem:

Agent and operator dashboard endpoints read old collaboration and AI state
summary tables.

Implementation shape:

Rewrite summaries to v2:

```txt
pages
reviews
findings
finding_evidence
tasks
provider_runs
packets
```

AI state:

```txt
If a durable structured-state cache becomes necessary later, add it under a v2
name. Do not restore the old ai_state_pages table name.
```

Decision rule:

```txt
If a live endpoint still needs structured AI state, keep it as a rebuildable v2
cache for now.
If no live endpoint needs it, remove it from runtime instead of preserving it as
legacy.
```

Rules:

- Keep dashboards thin. They are status confirmation surfaces, not the source of
  truth.
- Empty v2 DB should produce explicit empty-state responses, not crashes.
- Summary queries must be tested against an empty v2 database.
- Do not make dashboards heavy while migrating DB tables.

Done when:

- Operator Console, Agent Dashboard, AI Reviews, and AI Packets load against v2.
- Empty DB state is shown clearly.
- No dashboard query requires old table names.

## P31-007 Maintenance And Health v2 Checks

Problem:

Maintenance verification still checks old collaboration tables and context
bundle manifests.

Implementation shape:

Update:

```txt
verify-index
health summary
schema integrity checks
backup/restore validation
```

Add a runtime old-name guard test:

```txt
The following old table names must not appear in runtime Python code after v2
adoption, except inside v2_migrate.py or migration tests:

collaboration_reviews
collaboration_findings
finding_tasks
project_snapshot_packets
model_review_runs
experiment_packets
context_bundle_manifests
```

Rules:

- Verify v2 table presence.
- Verify old runtime table names are absent after promotion.
- Keep FTS/graph/search rebuild flows explicit.
- Do not run full release_check as a daily packet dependency.

Done when:

- Maintenance verify passes against v2 DB.
- Health reports schema version/checksum.
- Backup/restore can round-trip a v2 DB.
- Old runtime table-name guard test passes.

## P31-008 Live DB Promotion

Problem:

`data/knownet-v2.db` exists, but `data/knownet.db` remains live.

Implementation shape:

```txt
1. Stop API/web processes.
2. Create a final pre-promotion backup.
3. Rebuild v2 from current knownet.db.
4. Run targeted v2 API tests against the v2 DB path.
5. Move old knownet.db to backup/knownet-pre-v2-live.db.
6. Move knownet-v2.db to knownet.db.
7. Start API/web.
8. Run health, operator dashboard, packet creation, SARIF export, provider run
   dry-run checks.
```

Promotion script safety:

```txt
Stop on first error.
Do not move DB files after a failed test.
Do not overwrite the pre-promotion backup.
Rebuild v2 from the latest knownet.db immediately before promotion.
```

Recommended test command shape:

```powershell
$env:KNOWNET_DB_VERSION='v2'
$env:SQLITE_PATH='C:\knownet\data\knownet-v2.db'
python -m pytest tests\test_phase31_v2_*.py -q
```

Rules:

- Do not promote before P31-001 through P31-007 pass.
- Do not keep old table compatibility after promotion.
- If promotion fails, restore the pre-promotion DB backup.
- If targeted v2 tests fail, leave `data/knownet.db` untouched.

Done when:

- `data/knownet.db` is v2.
- API starts cleanly.
- Web UI core views load.
- Targeted tests pass.

## P31-009 Post-Promotion Runtime Cleanup

Problem:

After live promotion, old table names must not remain on active runtime paths.

Implementation shape:

```txt
- Make v2 the default DB version in config and tests.
- Route audit reads/writes to audit_events only.
- Route provider runs to provider_runs/provider_run_metrics/provider_run_artifacts.
- Route operator/agent summaries to v2 tables.
- Keep old table names only inside v2_migrate.py and archived migration docs.
```

Rules:

- Do not add compatibility views.
- Do not add dual-read branches for old table names.
- If a v1 helper is no longer imported, delete it.
- Targeted tests are enough; do not run full release_check for this cleanup.

Done when:

- v2 boot/collaboration/migration/SARIF targeted tests pass.
- `/health/summary` reports v2 schema state.
- `/api/audit` reads `audit_events`.

## P31-010 Remove Remaining v1 Runtime Branches

Problem:

Some modules still kept v1 fallback code after v2 was promoted. That makes the code harder to reason about and risks recreating old tables by accident.

Implementation shape:

```txt
- Startup initializes/verifies v2 only.
- Model runner safe context uses v2 tables only.
- Model runner store no longer creates model_review_runs.
- SARIF export uses findings/reviews/finding_evidence/finding_locations only.
- Maintenance verify-index uses the v2 verifier only.
- Remove the obsolete ai_state service/table creator.
```

Rules:

- No new compatibility layer.
- No old table creation code on startup.
- No old audit/model-run/SARIF fallback branches.
- Migration source-table names may remain inside v2_migrate.py only.

Done when:

- Targeted Phase 31 and SARIF tests pass after cleanup.
- Runtime startup does not call v1 schema/backfill helpers.
- Removed helpers are not imported by active API modules.

## Acceptance

```txt
1. Runtime code uses v2 table names for collaboration, packets, and provider runs.
2. Old collaboration/model/packet table names no longer appear as runtime SQL
   table references outside v2_migrate.py, archived docs, or explicit
   migration tests.
3. v2 schema boot and checksum validation exist.
4. Tests run against v2 without compatibility views.
5. data/knownet-v2.db can be promoted to data/knownet.db after checks.
6. No PostgreSQL/ORM/heavy framework is introduced.
7. Empty state is explicit and non-crashing.
8. No compatibility layer exists solely to preserve old phase-era table names.
```

## Suggested Work Order

```txt
P31-001 v2 Schema Boot Path
P31-002 Collaboration Query Rewrite
P31-003 SARIF v2 Source
P31-004 Packet And Snapshot Runtime Rewrite
P31-005 Provider Run Runtime Rewrite
P31-006 Agent And Operator Summary Rewrite
P31-007 Maintenance And Health v2 Checks
P31-008 Live DB Promotion
P31-009 Post-Promotion Runtime Cleanup
P31-010 Remove Remaining v1 Runtime Branches
```

## Out Of Scope

```txt
- New product features
- PostgreSQL or external search/vector stores
- MCP protocol redesign
- SARIF upload automation
- UI redesign beyond wiring to v2 API data
- Dual-read compatibility for old table names
- Full release_check until targeted v2 paths pass
```
