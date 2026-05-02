# KnowNet Phase 6 Tasks

Phase 6 goal: turn KnowNet from a working local AI knowledge base foundation into a
finishable, recoverable, operable product that can be run, backed up, verified,
and upgraded without the developer hand-holding every step.

Phase 1-5 built the Markdown knowledge base, AI draft pipeline,
identity/vault/security, citation audits, and graph map. Phase 6 closes the
project MVP by hardening operations, packaging, recovery, and end-to-end
verification. After Phase 6, the product direction is fixed as an AI-centered
collaboration knowledge base: a local-first AI collaboration tool for reviews,
decisions, and implementation records.

Implementation status: completed in the codebase.

Implemented surface:

```txt
Expanded health and health summary endpoints
tar.gz snapshot backups with manifest hashes and retention
Snapshot restore with pre-restore backup and rollback path
maintenance_locks and maintenance_runs operational tables
Maintenance lock middleware and stale lock release endpoints
Job processor maintenance lock skip behavior
Phase-aware migrate response with pre-migrate snapshot
Operations panel in the web UI
Smoke test and Phase 6 operations tests
Runbook and release checklist
```

## Phase 6 Fixed Decisions

These choices are fixed before implementation so the agent does not invent a
new deployment or operations architecture while coding.

```txt
Completion target: local-first MVP completion.
Deployment target: single-machine local run, not cloud multi-tenant hosting.
Packaging target: reproducible developer/local operator workflow first.
Canonical data: Markdown remains canonical; SQLite remains operational index/state.
Backup unit: data directory plus knownet.db plus config manifest.
Archive format: tar.gz through Python tarfile, with POSIX-style archive paths.
Restore rule: restore never overwrites current data without creating a pre-restore snapshot.
Health rule: one command/API response must summarize API, Rust daemon, SQLite, auth, embeddings, graph, and citations.
Upgrade rule: schema/data upgrades must be idempotent and rollback-aware.
Write rule: operational SQLite mutations continue through Rust daemon when they mutate core state.
```

## Phase 6 Principles

```txt
Prefer boring reliability over new features.
Make failure visible and recoverable.
Keep local data inspectable by humans.
Do not hide destructive operations behind one-click UI without snapshot protection.
Every operational command should be safe to run twice.
The user should be able to answer: is my page healthy, backed up, and recoverable?
```

## Phase 6 Completion Definition

KnowNet MVP is complete when:

```txt
Fresh setup can install, initialize, run API, run web, and create the first page.
Existing Phase 5 data can migrate forward without data loss.
Backup and restore are tested with real page files and SQLite data.
verify-index covers page, citations, graph, auth/vault basics, and missing files.
Health endpoint reports actionable status, not only "ok".
Web UI exposes system status and backup/restore controls for local/admin actor.
End-to-end smoke test covers message -> suggestion -> apply -> citation audit -> graph.
README contains a complete local runbook.
Release checklist exists and can be followed before tagging a build.
```

## Phase 6 Operational Model

Operational surfaces:

```txt
Health: GET /health and web status panel.
Verify: GET /api/maintenance/verify-index.
Backup: POST /api/maintenance/snapshots.
Restore: POST /api/maintenance/restore.
Export: existing Obsidian export remains available.
Migrate: POST /api/maintenance/migrate remains idempotent.
Smoke test: local command/script exercises the critical workflow.
```

Operational states:

```txt
healthy: no blocking verify-index issues, latest backup exists, daemon available
degraded: non-blocking issues such as embeddings unavailable or graph stale
attention_required: missing files, failed migration, corrupted db, auth misconfiguration
restoring: restore is in progress and writes are blocked
backing_up: snapshot is in progress and destructive operations are blocked
```

## Phase 6 Config Defaults

```txt
BACKUP_RETENTION_COUNT=10
BACKUP_MAX_BYTES=1073741824
RESTORE_REQUIRE_SNAPSHOT=true
HEALTH_BACKUP_MAX_AGE_HOURS=168
SMOKE_TEST_TIMEOUT_SECONDS=120
```

## Phase 6 Error Codes

```txt
backup_failed: snapshot creation failed
backup_too_large: snapshot exceeds BACKUP_MAX_BYTES
snapshot_not_found: requested snapshot does not exist
restore_failed: restore operation failed and pre-restore data was preserved
restore_requires_snapshot: restore blocked because pre-restore snapshot could not be created
restore_in_progress: a restore is already running
maintenance_locked: another maintenance operation is in progress
health_check_failed: one or more required health checks failed
runbook_step_failed: smoke test or setup check failed
```

## Phase 6 Backup Format

Archive format:

```txt
Format: tar.gz
Implementation: Python tarfile standard library, no extra dependency
Filename: knownet-snapshot-{yyyymmdd-hhmmss}-{short_id}.tar.gz
Create path: data/tmp/{filename}.tmp
Final path: data/backups/{filename}
Finalize: atomic rename from data/tmp to data/backups
Archive paths: always POSIX-style forward slashes, even on Windows
Rust daemon responsibility: manifest bookkeeping, maintenance locks, and audit events
FastAPI responsibility: tar.gz archive creation/extraction orchestration
```

Snapshot archive layout:

```txt
knownet-snapshot.json
data/knownet.db
data/pages/**
data/revisions/**
data/suggestions/**
data/inbox/**
data/sources/**
data/backups/manifest-only.txt  -- do not recursively include previous backup archives
```

`knownet-snapshot.json` schema:

```json
{
  "kind": "knownet.snapshot",
  "schema_version": 1,
  "created_at": "2026-05-02T00:00:00Z",
  "app_version": "0.1.0",
  "phase": 6,
  "sqlite_path": "data/knownet.db",
  "included_files": 0,
  "sha256": {
    "data/knownet.db": "..."
  }
}
```

Backup rules:

```txt
Create snapshots in data/backups.
Write to data/tmp first, then atomic rename into data/backups.
Do not include existing snapshot archives inside new snapshots.
Record snapshot creation in audit_events.
Apply retention after successful snapshot creation only.
Never delete the newest successful snapshot during retention cleanup.
```

## Phase 6 Restore Rules

Restore flow:

```txt
1. Validate snapshot exists and manifest kind/schema_version are supported.
2. Create a pre-restore snapshot unless RESTORE_REQUIRE_SNAPSHOT=false.
3. Extract snapshot into data/tmp/restore-{id}.
4. Validate expected paths and sha256 entries.
5. Stop background job processor and block mutating routes.
6. Move current data files into data/tmp/restore-backup-{id}.
7. Move restored files into place only after step 6 succeeds.
8. Reopen/reinitialize SQLite.
9. Run migrate, verify-index, citation rebuild if needed, graph rebuild.
10. If verification fails, keep restored data but report attention_required with details.
```

Restore step 6 details:

```txt
Move data/pages/, data/revisions/, data/inbox/, data/sources/, and data/suggestions/
  into data/tmp/restore-backup-{id}/ using rename, not copy.
Move data/knownet.db into data/tmp/restore-backup-{id}/knownet.db using rename.
Do not move data/backups/; backup archives must remain in place.
If a source directory does not exist, record skipped but do not fail the restore.
```

Restore step 7 details:

```txt
Move contents from data/tmp/restore-{id}/data/ into data/.
Before moving restored files into place, verify that the target data paths from step 6 are empty/missing.
If data/ still contains page/revisions/inbox/sources/suggestions/knownet.db after step 6, abort restore.
```

Restore failure recovery:

```txt
If step 7 fails after step 6 succeeded, move data/tmp/restore-backup-{id}/ contents back into data/.
Record rollback_success or rollback_failed in maintenance_runs.
If rollback also fails, set health overall_status=attention_required and return manual intervention guidance.
Never delete data/tmp/restore-backup-{id} until restore and rollback status are recorded.
```

Restore does not:

```txt
Silently overwrite without pre-restore snapshot.
Delete current data before restored data has been validated.
Restore previous backup archives recursively.
Change public/auth configuration.
```

Job processor and maintenance lock behavior:

```txt
The job processor does not need to terminate during restore.
Before each processing tick, it must check maintenance_locks for active locks.
If an active lock exists, skip the tick without claiming jobs.
After the lock is released, the next tick resumes automatically.
Mutating routes must check active maintenance_locks and return maintenance_locked during restore.
```

## Phase 6 Health Model

`GET /health` should include:

```txt
api.status
rust_daemon.status
sqlite.status
security.public_mode
security.write_auth
vault.default_vault_exists
page.page_count
citations.audit_count
citations.weak_count
graph.node_count
graph.edge_count
graph.stale
backup.latest_snapshot
backup.latest_snapshot_age_hours
embedding.status
overall_status: healthy | degraded | attention_required
```

Health rules:

```txt
Embedding unavailable is degraded, not attention_required.
No backup within HEALTH_BACKUP_MAX_AGE_HOURS is degraded.
Missing page files, missing SQLite, or daemon unavailable is attention_required.
Graph stale is degraded.
Security misconfiguration in public mode is attention_required.
```

`GET /health/summary` is the lightweight polling endpoint:

```json
{
  "overall_status": "healthy | degraded | attention_required",
  "issues": ["graph.stale", "backup.age_exceeded"],
  "checked_at": "2026-05-02T00:00:00Z"
}
```

Health polling rules:

```txt
GET /health returns the full detailed response for admin screens and initial load.
GET /health/summary returns only overall_status, blocking/degraded issues, and checked_at.
Web UI polling interval defaults to 60 seconds.
When overall_status=attention_required, web UI may poll every 30 seconds.
```

## Phase 6 Rust Daemon Commands

Phase 6 mutation commands:

```txt
create_snapshot_manifest
restore_snapshot
record_maintenance_lock
release_maintenance_lock
ensure_phase6_schema
```

FastAPI may orchestrate file archive creation, but stateful restore bookkeeping
and maintenance locks must be recorded through Rust daemon commands.

## Phase 6 SQLite Schema Baseline

```sql
CREATE TABLE maintenance_locks (
  id TEXT PRIMARY KEY,
  operation TEXT NOT NULL,
  status TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE maintenance_runs (
  id TEXT PRIMARY KEY,
  operation TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  report TEXT NOT NULL DEFAULT '{}'
);
```

Lock rules:

```txt
Only one active maintenance lock may exist at a time.
Mutating routes must return maintenance_locked while restore is active.
Stale locks older than 1 hour may be released by admin-only recovery endpoint.
```

Maintenance lock endpoints:

```txt
GET /api/maintenance/locks
  owner/admin actor only
  returns active locks ordered by created_at

POST /api/maintenance/locks/{lock_id}/release
  owner/admin actor only
  only allowed when lock created_at is older than 1 hour
  reject if an active restore process is still running
  record force_released in maintenance_runs
```

## P6-001 Health and Status

Goal:

```txt
Make the system's operational state visible.
```

Tasks:

```txt
Expand GET /health with page/citation/graph/backup/security status.
Add GET /health/summary for lightweight UI polling.
Add overall_status calculation.
Add web system status panel for local/admin actors.
Show degraded/attention_required states without blocking ordinary reading.
Add tests for healthy, degraded, and attention_required health responses.
```

Done when:

```txt
The user can open one screen/API response and know whether KnowNet is safe to use.
```

## P6-002 Snapshot Backup

Goal:

```txt
Create complete, bounded, auditable backups.
```

Tasks:

```txt
Add snapshot manifest file to backup archives.
Use tar.gz via Python tarfile.
Use filename knownet-snapshot-{yyyymmdd-hhmmss}-{short_id}.tar.gz.
Exclude previous backup archives from new snapshots.
Enforce BACKUP_MAX_BYTES.
Apply BACKUP_RETENTION_COUNT.
Record audit event with snapshot hash/count/size.
Add web backup action and latest snapshot display.
```

Done when:

```txt
A snapshot can be created repeatedly without recursive archive growth.
```

## P6-003 Restore

Goal:

```txt
Restore from snapshot without making data loss easy.
```

Tasks:

```txt
Add restore endpoint for local/admin actors.
Require pre-restore snapshot by default.
Validate manifest and sha256 before moving files into place.
Block mutating routes during restore through maintenance lock.
Implement step 7 failure rollback from data/tmp/restore-backup-{id}.
Run migrate and verify-index after restore.
Report restore status and verification issues.
Add restore tests using a real snapshot fixture.
```

Done when:

```txt
A deleted/modified page can be restored from snapshot and verified.
```

## P6-004 Migration and Upgrade Hardening

Goal:

```txt
Make upgrades safe to run across Phase 1-5 data.
```

Tasks:

```txt
Add ensure_phase6_schema command.
Make /api/maintenance/migrate report every schema phase status.
Create migration backup before schema changes.
Make migrations idempotent and test repeated migrate calls.
Add fixture tests for Phase 2/3/4/5 database shapes when feasible.
```

Migration response shape:

```json
{
  "ok": true,
  "data": {
    "phases": [
      {"phase": 1, "status": "already_applied"},
      {"phase": 2, "status": "already_applied"},
      {"phase": 6, "status": "applied"}
    ],
    "backup_created": "data/backups/pre-migrate-20260502-120000-ab12cd34.tar.gz",
    "duration_ms": 340
  }
}
```

Migration status values:

```txt
already_applied
applied
skipped
failed
```

If any phase has status=failed, the response should use ok=false and include
the failed phase report.

Done when:

```txt
Running migrate twice produces no destructive changes and no duplicate derived rows.
```

## P6-005 End-to-End Smoke Test

Goal:

```txt
Create one fast confidence check for the whole product.
```

Smoke flow:

```txt
1. Start API and web or use TestClient for API-only smoke.
2. Health is not attention_required.
3. Create or submit a message.
4. Wait for suggestion.
5. Apply suggestion.
6. Confirm page exists.
7. Confirm citation audit exists.
8. Rebuild graph.
9. Confirm page node exists.
10. Create snapshot.
11. Run verify-index.
```

Tasks:

```txt
Add scripts/smoke-test or documented pytest target.
Make failures print actionable step names.
Keep smoke data isolated from user's real data by default.
```

Smoke test data isolation:

```txt
Use a separate data directory: data/smoke-test/.
Use SQLITE_PATH=data/smoke-test/knownet.db.
Allow override with SMOKE_DATA_DIR=./data/smoke-test.
Delete data/smoke-test/ after the smoke test completes.
Add --keep option to preserve smoke data for debugging.
pytest target: pytest tests/smoke/ -m smoke.
When using TestClient, initialize FastAPI with smoke config.
Use the real Rust daemon binary, not a mock.
Use mock OpenAI client/service by default.
```

Done when:

```txt
One command can prove the core workflow still works.
```

## P6-006 Web Operations UI

Goal:

```txt
Expose operational controls without turning the app into an admin maze.
```

Tasks:

```txt
Add compact Operations section for local/admin actors.
Show health status, latest backup, verify-index issue count.
Buttons: create snapshot, run verify-index, rebuild graph, run smoke check if available.
Restore UI may be gated behind an explicit file/name confirmation.
Do not show destructive controls to anonymous/viewer actors.
```

Done when:

```txt
The local owner can operate KnowNet from the app without memorizing endpoints.
```

## P6-007 Runbook and Release Checklist

Goal:

```txt
Make the finished MVP reproducible.
```

Tasks:

```txt
Update README with install, run, backup, restore, verify, test, and troubleshooting steps.
Add docs/RUNBOOK.md.
Add docs/RELEASE_CHECKLIST.md.
Document known degraded states such as embeddings unavailable.
Document how to recover from locked maintenance state.
```

RUNBOOK.md must include these scenarios:

```txt
1. First install and run
2. Rust daemon build failure
3. Embedding model download failure
4. knownet.db corruption and snapshot restore
5. Stuck maintenance lock release
6. Graph rebuild failure
7. Running without an OpenAI API key
8. Interpreting verify-index errors
9. Phase N to Phase N+1 migration procedure
10. Recovery without backup archives by rebuilding from Markdown
```

Done when:

```txt
A future operator can run and recover KnowNet from docs alone.
```

## P6-008 Tests

Required tests:

```txt
health reports healthy/degraded/attention_required states
snapshot excludes previous backup archives
snapshot manifest includes file hashes
snapshot archive is tar.gz and uses POSIX archive paths
backup retention does not delete newest snapshot
restore requires pre-restore snapshot
restore validates manifest before replacing data
restore rolls back from restore-backup when final move fails
restore runs migrate and verify-index
maintenance lock blocks mutating routes during restore
stale maintenance lock can be listed and force released by owner/admin
migrate is idempotent
smoke test covers message -> suggestion -> apply -> citation -> graph
smoke test uses isolated SMOKE_DATA_DIR
web operations data shape renders without crashing
```

## Out of Scope

```txt
Cloud hosting
Multi-tenant SaaS deployment
Mobile app packaging
Native desktop installer
Encrypted cloud sync
Realtime collaborative editing
Enterprise SSO
```

## Suggested Development Order

```txt
1. P6-001 Health and Status
2. P6-002 Snapshot Backup
3. P6-003 Restore
4. P6-004 Migration and Upgrade Hardening
5. P6-005 End-to-End Smoke Test
6. P6-006 Web Operations UI
7. P6-007 Runbook and Release Checklist
8. P6-008 Tests
```
