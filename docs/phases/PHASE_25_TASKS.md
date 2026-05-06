# Phase 25 Tasks: Verification, Ignore Policy, And Agent Contract

Status: implemented
Created: 2026-05-06
Implemented: 2026-05-06

Phase 25 does not redesign the database. The database was reset during early
development, so the current job is to keep the existing SQLite shape stable and
observable as it grows. This phase adds thin verification, shared blocking
policy, and contract consistency around the Phase 24 FTS and AI handoff work.

## Fixed Rules

Do not:

- Replace the current SQLite schema with a new database design.
- Add Alembic, PostgreSQL, or a migration framework in this phase.
- Add chunk search, hybrid ranking, or a search analytics product.
- Store raw secrets, raw prompts, raw database files, backups, sessions, users,
  or token material in packets or index verification output.
- Make daily work depend on full release checks.

Do:

- Keep checks narrow, fast, and operator-readable.
- Reuse the existing maintenance, agent, packet, and snapshot surfaces.
- Centralize shared forbidden path/secret policy where practical.
- Prefer contract metadata and smoke validation over new dashboards.

Implemented surface:

```txt
- GET /api/maintenance/search/verify-fts
- verify-index includes FTS missing/orphaned row issues
- shared ignore_policy helpers for path, text, and JSON-key blocking
- /api/agent/onboarding exposes knownet.agent.v1
- project snapshot packets include source_manifest
- GET /api/maintenance/snapshots/{snapshot_name}/verify
```

## P25-001 Verify FTS

Implemented a narrow FTS verification endpoint:

```txt
GET /api/maintenance/search/verify-fts
```

It should compare active pages with `pages_fts`, report missing/orphaned page
ids, include compact FTS status, and never scan raw secrets or unrelated files.

Done when:

- Missing indexed pages are reported as `fts_page_missing`.
- Orphaned FTS rows are reported as `fts_page_orphaned`.
- `verify-index` includes the same issue codes.

## P25-002 Shared Ignore And Secret Policy

Create a small shared policy module for path and text blocking used by packet,
model context, provenance, and future exports.

Done when:

- `.env`, `.env.*`, `*.db`, `knownet.db`, backups, sessions, users,
  `node_modules`, `.git`, `.local`, `.next`, `__pycache__`, and key/cert files
  are classified consistently.
- Existing model context and packet checks use the shared helpers.
- Tests cover path and secret assignment detection.

## P25-003 Agent Access Contract v1

Added a compact agent contract object to `/api/agent/onboarding`.

Required shape:

```json
{
  "contract_version": "knownet.agent.v1",
  "access_mode": "snapshot",
  "limits": {
    "max_pages": 20,
    "max_chars": 60000
  },
  "sources": [],
  "forbidden": []
}
```

Done when:

- Agent onboarding includes the contract.
- The contract uses standard packet/MCP names where applicable.
- The contract contains no raw local file paths or secrets.

## P25-004 Snapshot And Packet Manifest Consistency

Keep the distinction explicit:

```txt
Snapshot = point-in-time KnowNet data archive
Packet = bounded AI handoff context
Manifest = included source list and hashes
```

Done when:

- Project snapshot packet JSON includes a compact `source_manifest`.
- Snapshot archive manifest uses a stable `kind` and `schema_version`.
- Packet/source manifest fields use `id`, `type`, `content_hash`,
  `generated_at`, `updated_at`, and `links` consistently where available.

## P25-005 Backup Integrity Smoke

Added a lightweight snapshot verification endpoint:

```txt
GET /api/maintenance/snapshots/{snapshot_name}/verify
```

It should inspect the tar manifest, validate recorded hashes, run SQLite
`PRAGMA integrity_check` against a temporary extracted DB copy, and compare
manifest page files with archive members.

Done when:

- Valid snapshots return `status: valid`.
- Corrupt hashes, missing DB, or failed SQLite integrity checks return
  `status: invalid` with compact issue codes.
- No restore is performed by the verification endpoint.

## Acceptance

```txt
1. FTS can be rebuilt and verified independently.
2. Shared ignore policy blocks obvious secret/raw/local artifacts.
3. External agents receive one compact `knownet.agent.v1` contract.
4. Project packets expose a compact source manifest.
5. Snapshot archives can be integrity-smoke-checked without restore.
6. Targeted tests pass without full release_check.
```
