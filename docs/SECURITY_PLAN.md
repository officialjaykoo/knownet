# KnowNet Security Plan

This document defines the KnowNet security baseline for local operation and
basic public/team operation. It is not a full internet SaaS security model, but
it must be strong enough that a small team can run the app deliberately without
accidental open writes or silent data loss.
KnowNet is AI-centered, so the most important asset is not only the database,
but the integrity of AI-readable project memory: `data/pages`, `data/revisions`,
structured findings, implementation records, and the audit trail around changes.

## Security Posture

KnowNet starts from a local-first assumption.

```txt
Default mode: local-only
Public/network mode: explicit opt-in only
Write access: protected
Destructive actions: archived/trash first, never hard delete by default
AI output: reviewable draft, not trusted content
```

## 1. Basic Security Mode

KnowNet must default to local-only operation.

Requirements:

- Bind API and web development servers to localhost by default.
- Keep CORS restricted to known local web origins in local mode.
- Add an explicit `PUBLIC_MODE` or equivalent setting before allowing network access.
- In public mode, require write authentication before enabling message creation, suggestion apply, restore, import, export, or maintenance actions.
- Surface the active security mode in `/health` or an admin-only status endpoint.

Done when:

- A fresh checkout cannot accidentally expose write endpoints to the network.
- Public mode is impossible to enable without an explicit configuration change.

Implementation status:

- Done. `PUBLIC_MODE=false` is the default.
- Done. `PUBLIC_MODE=true` disables writes unless `ADMIN_TOKEN` is configured.
- Done. `PUBLIC_MODE=true` rejects weak admin tokens shorter than `ADMIN_TOKEN_MIN_CHARS`.
- Done. `/health` reports `security.public_mode` and write auth mode.
- Done. External tunnel mode can require Cloudflare Access headers with
  `CLOUDFLARE_ACCESS_REQUIRED=true`.
- Done. Same-origin web proxy support keeps browser API calls on the web origin
  and keeps port `8000` local.

## 2. Write Protection

Read-only page browsing may be public later, but writes must be protected before
Phase 2 AI features are expanded.

Protected operations:

- `POST /api/messages`
- `POST /api/suggestions/{id}/apply`
- `POST /api/pages/{slug}/revisions/{revision_id}/restore`
- `POST /api/maintenance/*`
- `/api/operator/*` administrative readiness and provider status endpoints
- Future import/export/rebuild endpoints

Requirements:

- Add a simple admin token or local admin password before multi-user auth exists.
- Require a long random `ADMIN_TOKEN` before public/team write operation.
- Reject unauthenticated write requests with a consistent error code.
- Keep the token out of Git via `.env`.
- Avoid browser cookie auth until CSRF protection is implemented.

Done when:

- All write and maintenance endpoints have a shared authorization dependency.
- Existing tests cover both allowed and rejected write requests.

Implementation status:

- Done. Mutating message, suggestion, revision, and maintenance endpoints use shared write/admin authorization.
- Done. Local-only mode allows loopback writes for development.
- Done. `ADMIN_TOKEN` gates writes when configured.
- Done. Public mode treats an `ADMIN_TOKEN` shorter than `ADMIN_TOKEN_MIN_CHARS` as `security_misconfigured`.

## 3. Delete And Overwrite Defense

Hard delete must not be part of the default product behavior.

Rules:

- Prefer `archived`, `rejected`, or `trashed` status over file deletion.
- Every apply, restore, import, or bulk edit must create a revision first.
- Existing page files must never be overwritten without preserving the previous content in `data/revisions`.
- Bulk operations must support dry-run before writing.
- Hard delete, if ever added, must require admin authentication and an explicit confirmation flag.

Current risk:

- `apply_suggestion` can overwrite the current page for a slug.
- `restore_revision` can replace the current page with an older revision.

Required Phase 2 fix:

- Treat these as controlled write operations with audit logs and revision guarantees.

Implementation status:

- Done. Suggestion apply creates the new target revision and preserves the previous page as a system `rev_pre_apply_*` backup revision when overwriting.
- Done. Revision restore preserves the current page as a system `rev_pre_restore_*` backup revision before replacing it.
- Done. No hard-delete API exists.

## 4. Audit Log

KnowNet needs an append-only audit trail for human, system, and AI actions.

Minimum fields:

```txt
id
created_at
action
actor_type: anonymous | admin | ai | system
actor_id
session_id
ip_hash
user_agent_hash
target_type
target_id
before_revision_id
after_revision_id
model_provider
model_name
model_version
prompt_version
metadata_json
```

Actions to log:

- message created
- draft generated
- suggestion applied
- suggestion rejected
- revision restored
- import/export started and completed
- index rebuilt
- embedding model loaded
- citation verification run

Privacy rule:

- Store IP and user agent as hashes by default, not raw values.

Done when:

- A page can answer: who or what changed it, from which input, using which model/prompt, and when.

Implementation status:

- Done. `audit_log` stores actor, target, revision, model, prompt, and metadata fields.
- Done. Message creation, draft generation, suggestion apply, revision restore, snapshots, and maintenance actions write audit records.
- Done. `GET /api/audit` provides admin-only audit querying.

## 5. Input Limits And Abuse Controls

Public or semi-public writing needs basic abuse controls before AI processing.

Requirements:

- Limit message body size.
- Limit slug length and title length.
- Lock out repeated failed login attempts for a short period.
- Limit requests per minute for write endpoints.
- Limit queued/running jobs per actor/session.
- Reject unsupported content types.
- Add timeouts around AI calls and embedding operations.
- Keep semantic search fallback available when embeddings fail.

Suggested initial limits:

```txt
message body: 64 KiB
title: 160 chars
slug: 96 chars
write requests: 20/min per actor or IP hash
failed logins: 5 attempts, then 15 minute lockout
queued jobs: 10 per actor/session
AI draft timeout: 60s
embedding encode timeout: 30s
```

Done when:

- A single anonymous client cannot fill disk or create unbounded AI jobs quickly.

Implementation status:

- Done. Message byte limit, title limit, slug limit, write rate limit, and queued job limit are configured.
- Done. Login failures are tracked by client IP hash and username hash, then temporarily locked after repeated failures.
- Done. AI and OpenAI draft calls use configured timeouts; local embedding failure falls back to keyword behavior.

## 6. Operations Endpoint Lockdown

Maintenance endpoints are powerful and must be admin-only.

Admin-only examples:

- `/api/maintenance/embedding/load`
- `/api/maintenance/embedding/prefetch-plan`
- `/api/maintenance/seed/dry-run`
- `/api/maintenance/verify-index`
- future import/export endpoints
- future index rebuild endpoints

Requirements:

- Use the same write/admin authorization dependency.
- Separate harmless health checks from mutating or expensive maintenance actions.
- Add audit records for maintenance actions that mutate state or consume significant resources.

Done when:

- Maintenance endpoints cannot be triggered by an unauthenticated browser or script.

Implementation status:

- Done. Maintenance endpoints that are mutating, expensive, or operational are admin-only.
- Done. Harmless embedding health remains readable.
- Done. Phase 17 operator endpoints for AI state quality, provider matrix, and
  release readiness are admin-only.

## 7. Backup And Recovery

Backups must keep narrative files and structured state together. Markdown pages
are durable human-readable source material, while SQLite/JSON records hold the
canonical collaboration state used for findings, decisions, audit, graph, and
AI-readable handoff.

Backup scope:

- `data/pages`
- `data/revisions`
- `data/suggestions`
- `data/inbox`
- `data/sources`
- `data/knownet.db`
- relevant config excluding secrets

Requirements:

- Create snapshots before import, bulk apply, restore, or rebuild operations.
- Use `.tar.gz` snapshot archives so backups are portable outside the app.
- Provide a restore procedure in docs.
- Provide a restore-plan inspection path before browser/operator restore.
- Keep `verify-index` able to detect missing files, missing frontmatter, missing sections, broken citations, and stale metadata.
- Keep Markdown/frontmatter/body recoverable into a usable database where
  possible, while preserving structured snapshot restore as the preferred path.

Done when:

- A damaged SQLite database can be regenerated from Markdown.
- A bad AI/apply/import operation can be rolled back from revisions or snapshots.

Implementation status:

- Done. `POST /api/maintenance/snapshots` creates an admin-only `.tar.gz` snapshot of Markdown data and `knownet.db`.
- Done. `GET /api/maintenance/snapshots` lists snapshots.
- Done. `GET /api/maintenance/restore-plan` inspects snapshot manifest, tar
  path safety, active locks, and pre-restore snapshot requirements without
  restoring data.
- Done. `verify-index` detects missing files, missing frontmatter, missing sections, broken citation state, and graph/index drift where available.

Restore procedure:

```txt
1. List snapshots with GET /api/maintenance/snapshots.
2. Inspect the candidate snapshot with GET /api/maintenance/restore-plan.
3. Confirm no active maintenance lock blocks restore.
4. Confirm the snapshot ends with .tar.gz and has a valid manifest.
5. Use POST /api/maintenance/restore only after operator confirmation.
6. Let the restore flow create a pre-restore snapshot when configured.
7. Run GET /api/maintenance/verify-index with admin auth.
```

Manual offline restore remains possible for emergency recovery, but the
operator path should prefer the API restore workflow because it validates tar
members, records maintenance runs, audits the restore, and rebuilds graph state
where possible.

## 8. External Model Runner And AI State Quality

KnowNet may call external model APIs from the server side. These calls are
operator-controlled review runs, not autonomous write agents.

Rules:

- API keys stay in server-side environment/config only.
- External models receive only sanitized safe context.
- External models never receive raw database files, local absolute paths,
  backups, inbox raw messages, sessions, users, raw tokens, token hashes, or
  `.env` values.
- Model output becomes `dry_run_ready` first.
- Operator import is required before model output becomes collaboration reviews
  or findings.
- Mocked provider tests never count as live provider verification.
- Provider verification levels are evidence-based:
  `mocked`, `configured`, `live_verified`, `failed`, or `unavailable`.

Implementation status:

- Done. `model_review_runs` stores sanitized run metadata, token estimates,
  dry-run output, import linkage, and sanitized errors.
- Done. Safe context builder rejects secret/path-like content before provider
  calls.
- Done. Phase 17 AI state quality endpoint checks whether canonical AI-readable
  state is useful and safe before handoff.
- Done. Phase 17 provider matrix makes mocked/configured/live verification
  explicit for operator and release review.

## 9. Release Evidence

Release evidence must be durable and safe for AI handoff.

Implementation status:

- Done. `scripts/release_check.ps1` checks AI state quality and provider matrix
  after health and verify-index.
- Done. `scripts/release_check.ps1` writes `docs/RELEASE_EVIDENCE.md` with a
  structured JSON evidence record.
- Done. Release evidence records provider verification summary without secrets
  or raw local paths.

## 10. Basic Public/Team Operations Baseline

This is the minimum security layer for operating KnowNet beyond a single local
developer process.

Requirements:

- `PUBLIC_MODE=true` requires `ADMIN_TOKEN` and the token length must be at least `ADMIN_TOKEN_MIN_CHARS`.
- Authentication sessions store hashed IP/user-agent metadata only.
- Login failures are counted by hashed client and username, with temporary lockout after repeated failures.
- Anonymous public submissions stay in `pending_review` and do not create AI jobs until approved.
- API responses include basic browser hardening headers:
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
  - `X-Frame-Options: DENY`
- `/health` and `/health/summary` report public-mode misconfiguration as action-required issues.

Default settings:

```txt
ADMIN_TOKEN_MIN_CHARS=32
AUTH_MAX_FAILED_ATTEMPTS=5
AUTH_LOCKOUT_SECONDS=900
```

Done when:

- A weak public admin token cannot authorize writes.
- A repeated password guessing attempt is slowed down without storing raw identifying metadata.
- Operators can see public-mode security problems from health checks before exposing the app.

Implementation status:

- Done. Public mode rejects weak admin tokens through shared auth dependencies.
- Done. Health reports `security.public_without_admin_token` and `security.weak_admin_token`.
- Done. Session metadata stores `ip_hash` and `user_agent_hash`, not raw IP/user-agent strings.
- Done. Login failure lockout is implemented in API process state.
- Done. Security headers are added to API responses.

## Phase 2 Security Gate

Before starting the main Phase 2 feature work, implement at least:

```txt
1. local-only default / explicit public mode
2. write/admin auth for mutating endpoints
3. revision-before-overwrite guarantee
4. audit log table and writes for apply/restore/message/draft
5. input size limits and basic job abuse limits
```

The remaining items may continue during Phase 2, but import/export and public
write access must not ship before the baseline sections are implemented.

Current gate status:

```txt
1. local-only default / explicit public mode: done
2. write/admin auth for mutating endpoints: done
3. revision-before-overwrite guarantee: done
4. audit log table and writes for apply/restore/message/draft: done
5. input size limits and basic job abuse limits: done
6. operations endpoint lockdown: done
7. backup snapshot creation and restore procedure: done
8. basic public/team operations baseline: done
```

Remaining security work for a larger deployment should focus on reverse-proxy TLS
configuration, persistent distributed rate limiting, rotated secrets, and a
separate production identity provider. Those are outside the current local-first
completion target.
