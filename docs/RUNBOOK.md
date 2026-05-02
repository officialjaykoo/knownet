# KnowNet Runbook

This runbook covers the local-first MVP operations path.

## First Install And Run

1. Build the Rust daemon from `apps/core` with `cargo build`.
2. Install API dependencies in `apps/api/.venv`.
3. Install web dependencies in `apps/web` with `npm install`.
4. Start API on `127.0.0.1:8000`.
5. Start web on `127.0.0.1:3000`.
6. Open `/health/summary` and confirm the system is not `attention_required`.

## Health Status

`/health/summary` returns `overall_status`, machine-readable `issues`, and
human-readable `issue_details`.

`attention_required` means a blocking issue is present, such as
`rust_daemon.unavailable`, `sqlite.*`, or `security.public_without_admin_token`.
Do not continue normal writes until this is fixed.

`degraded` can be expected during local operation. `backup.missing` means the
first snapshot has not been created yet. `embedding.unavailable` means semantic
embeddings are offline, but keyword search and deterministic fallbacks still
work.

## Rust Daemon Build Failure

If Windows reports `access denied` for `knownet-core.exe`, stop running
`knownet-core` processes and rebuild. The API starts the daemon, so stop the API
server before rebuilding when needed.

## Embedding Model Download Failure

Embedding unavailable is a degraded state, not a blocker. KnowNet falls back to
keyword behavior. Set `LOCAL_EMBEDDING_LOCAL_FILES_ONLY=false` only when you
intentionally want model downloads.

## knownet.db Corruption

Create a pre-restore copy if possible, then restore from the latest
`knownet-snapshot-*.tar.gz` through `POST /api/maintenance/restore`. After
restore, run `GET /api/maintenance/verify-index`.

## Stuck Maintenance Lock

List locks with `GET /api/maintenance/locks`. If a lock is older than one hour
and no restore is active, release it with
`POST /api/maintenance/locks/{lock_id}/release`.

## Graph Rebuild Failure

Run `POST /api/graph/rebuild` with `{"scope":"vault"}`. Then run
`GET /api/maintenance/verify-index` and inspect `graph_*` issue codes.

## Running Without OpenAI

Leave `OPENAI_API_KEY` unset. The draft service uses the local mock path, which
is sufficient for smoke tests and offline local use.

## verify-index Errors

`missing_page_file` means Markdown is missing. `citation_*` points at citation
source/audit problems. `graph_*` means derived graph metadata can usually be
fixed with a graph rebuild.

## Phase Migration

Before moving from Phase N to Phase N+1, create a snapshot, run migrate, then
run verify-index. Migration should be safe to run twice.

## Recovery Without Backups

If no snapshot exists but Markdown files remain, recreate `knownet.db`, run
migrate, re-index pages, rebuild citation audits, and rebuild the graph.

## Agent Token Rotation

List tokens in the Agent Access panel or with `GET /api/agents/tokens`.
Rotate a token with `POST /api/agents/tokens/{token_id}/rotate`. The new raw
token is shown once, so update the MCP or SDK environment immediately.

Revoke unused tokens with `POST /api/agents/tokens/{token_id}/revoke`. Revoked
tokens cannot call `/api/agent/*` and cannot use write gateways.

## MCP Setup

The Phase 10 MCP server runs over stdio from `apps/mcp/knownet_mcp/server.py`.
Set:

```txt
KNOWNET_BASE_URL=http://127.0.0.1:8000
KNOWNET_AGENT_TOKEN=<token shown once by the operator dashboard>
```

Use an agent token with only the scopes needed by the AI tool. The MCP server
does not expose maintenance tools.
