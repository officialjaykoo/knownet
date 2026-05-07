# KnowNet Runbook

This runbook covers the local-first MVP operations path.

## Development Environment

Keep source and generated/local execution artifacts separate. Follow
`docs/LOCAL_ENVIRONMENT.md`.

Agents must not create repo-local virtual environments. API verification uses
the workstation's global Python interpreter, and missing API dependencies should
be installed globally with `python -m pip install ...`.

## First Install And Run

1. Build the Rust daemon from `apps/core` with `cargo build`.
2. Install API dependencies into global Python.
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

## Daily Operator Console Loop

Open the web app and use the Operator Console at the top of the workspace.

```txt
1. Confirm Health is not attention_required.
2. Confirm AI State Quality is pass or an understood warn state.
3. Inspect provider verification counts.
4. Start a Gemini mock run when you need an end-to-end review exercise.
5. Inspect the selected model run context counts and dry-run findings.
6. Import findings only after operator review.
7. Triage imported findings from the Review Inbox.
8. Run verify-index from the Operations panel.
9. Create a snapshot before risky operations.
```

Provider verification levels are conservative. A mocked run is never
`live_verified`. Gemini becomes `configured` when the server is enabled and a
server-side API key is present, and only becomes `live_verified` after a real
non-mock provider call succeeds through `model_review_runs`.

Useful operator endpoints:

```txt
GET /api/operator/ai-state-quality
GET /api/operator/provider-matrix
GET /api/operator/release-readiness
```

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

Before restore, inspect the snapshot from the Operations panel with Restore
plan or call `GET /api/maintenance/restore-plan?snapshot_name=<name>`. The plan
validates the tar member paths, reads the manifest, reports active locks, and
confirms whether a pre-restore snapshot is required. It does not restore data.

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

When enabled, the draft service uses OpenAI's Responses API with Structured
Outputs:

```txt
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5-mini
OPENAI_REASONING_EFFORT=low
OPENAI_MAX_OUTPUT_TOKENS=2000
OPENAI_TIMEOUT_SECONDS=60
```

Keep this path for source-to-page drafting only. Gemini, DeepSeek, and other
external reviewers use the model-runner paths instead.

## Provider API Smoke

Use the provider smoke helper to verify API key/base URL/model request shape
without touching KnowNet data:

```powershell
python scripts\provider_api_smoke.py gemini --dry-run
python scripts\provider_api_smoke.py deepseek --dry-run
python scripts\provider_api_smoke.py minimax --dry-run
python scripts\provider_api_smoke.py qwen --dry-run
python scripts\provider_api_smoke.py kimi --dry-run
python scripts\provider_api_smoke.py glm --dry-run
```

Remove `--dry-run` only when you intentionally want a live provider call. The
script prints `<configured>` for API keys and never writes to SQLite.

For provider stability triage, prefer `GET /api/operator/provider-matrix` before
rerunning a model. It exposes the latest provider failure and raises
`stability_alert` after three consecutive failed runs. Model run responses also
record `duration_ms` so slow provider calls can be separated from fast
configuration/auth failures.

## verify-index Errors

`missing_page_file` means Markdown is missing. `citation_*` points at citation
source/audit problems. `graph_*` means derived graph metadata can usually be
fixed with a graph rebuild.

`agent_token_expired_cleanup_candidate` is reported as a warning, not a
blocking index failure. Rotate or revoke expired tokens from the Agent Access
dashboard during routine maintenance.

## External AI Experiment Packets

For a broad handoff, generate a compact project state packet first:

If Gemini is configured, prefer the provider fast lane:

```txt
POST /api/model-runs/review-now
{
  "provider": "gemini",
  "prefer_live": true,
  "allow_mock_fallback": false,
  "auto_import": false,
  "max_pages": 10,
  "max_findings": 15,
  "slim_context": true
}
```

Use `auto_import: true` only when you want KnowNet to import the dry-run-ready
model response into the review inbox immediately. With `allow_mock_fallback:
false`, missing credentials fail fast instead of silently creating a mock run.
Daily fast-lane reviews should keep `slim_context: true` and small
`max_pages`/`max_findings` values so providers receive the current high-signal
state instead of re-reading the whole graph. The outbound provider packet
includes access fallback, boundary enforcement, evidence-quality, stale
suppression, and targeted-verification rules.

If provider access is unavailable, generate a compact project state packet:

```txt
POST /api/collaboration/project-snapshot-packets
{
  "target_agent": "codex",
  "profile": "implementation",
  "output_mode": "implementation_candidates",
  "focus": "Identify the next highest-leverage implementation action."
}
```

The response is copy-ready and contains health, AI state quality, provider
summary, release estimate, accepted findings, recent finding tasks, recent model
runs, and warning labels. It stores a relative packet file under
`data/project-snapshot-packets/` and intentionally omits local absolute paths.
Pass `since` with an ISO timestamp when an external AI already saw a previous
snapshot and only needs changed pages, findings, tasks, and model runs.
The snapshot builder is code-owned by
`apps/api/knownet_api/services/project_snapshot.py` for profile defaults,
target-agent compaction, important changes, and do-not-suggest rules; the API
route only assembles and stores the final packet.
Prefer profile-specific packets over generic overview packets:

```txt
overview          broad handoff
stability         health/provider/backlog risk review
performance       latency/search/model-run speed review
security          public mode, auth, evidence quality, boundary review
implementation    next Codex task selection
provider_review   Gemini/DeepSeek/Qwen/Kimi/GLM runner review
```

Packets use `contract_version: p26.v1` across copy-paste and API-key provider
flows. If `snapshot_quality.warnings` is not empty, acknowledge the warning in
the UI before sending or copying the packet; this does not block API generation
but prevents warning blindness.
Every project snapshot is compact JSON by default and includes `contract_ref`,
`limits`, compact `health`, prioritized `signals`, `packet_summary`,
`snapshot_diff_summary`, and `do_not_suggest` so smaller providers can answer
from the highest-signal state instead of rereading a large Markdown packet.
Use per-signal `required_context` to see what an external AI should ask for
before upgrading context-limited evidence. `packet_integrity` replaces the old
inline `snapshot_self_test`; detailed validation belongs outside the AI-facing
packet.

Search uses SQLite FTS5 when `search.fts` is `ready`; otherwise KnowNet falls
back to indexed LIKE plus Markdown scan. Rebuild the lightweight page index with:

```txt
POST /api/maintenance/search/rebuild-fts
```

Check compact search status with:

```txt
GET /api/maintenance/search/fts-status
```

Use the Operator Console's External AI Packet panel to generate a copy-ready
Claude/Codex prompt. The packet keeps KnowNet nodes as source material while
embedding only the selected core context into the outbound prompt.

API equivalent:

```txt
POST /api/collaboration/experiment-packets
{
  "experiment_name": "Boundary Interpretation Divergence Test",
  "task": "Decide scenarios only.",
  "target_agent": "claude",
  "scenarios": ["Can a context_limited finding be a release blocker?"]
}
```

The response includes preflight counts, selected node excerpts, scenarios, and
the parser-ready Finding contract. Run verify-index before and after importing
resulting findings when the experiment changes collaboration records.

Generated packets are saved under `data/experiment-packets/` and can be fetched
again through `GET /api/collaboration/experiment-packets/{packet_id}`. Paste an
external AI response into the Operator Console response box, or call
`POST /api/collaboration/experiment-packets/{packet_id}/responses/dry-run`, to
preview parser errors and importable findings before creating collaboration
records.

## Accepted Finding Tasks

After importing an external AI review, triage findings from the Review Inbox.
Accepted findings can be converted into Codex-readable work items with the Task
button or through:

```txt
POST /api/collaboration/findings/{finding_id}/task
```

The fast handoff endpoint for the next coding agent is:

```txt
GET /api/collaboration/next-action
```

It returns one recommended next action. It prefers an open finding task, then an
accepted finding that needs task creation. When the review backlog is noisy, it
recommends queue compression/triage before asking Gemini for another review.
Only when the queue is quiet does it recommend API-provider fast-lane review
when Gemini is configured, then pending triage, then project snapshot
generation. Each response includes `task_template`, a ready-to-call API shape
for the recommended action.

Fast Gemini models are useful for cheap, narrow passes, but they should not be
treated as the main reasoning authority. Keep Gemini packets slim and let
KnowNet reduce duplicate/stale findings before starting another live review.

To inspect duplicate finding noise:

```txt
GET /api/collaboration/finding-duplicates
```

Review import dry-runs also report `duplicate_candidates` so an operator can
decide whether to import, defer, or merge advice before it adds more queue
noise.

For the full accepted queue:

```txt
GET /api/collaboration/finding-queue?status=accepted
```

It returns accepted findings, generated task prompts, expected verification
hints, evidence quality, provenance, and whether a structured task already
exists. Use targeted tests for daily task work; reserve full release_check for
release candidates or explicit release verification.

After Codex implements a task, record evidence through:

```txt
POST /api/collaboration/findings/{finding_id}/implementation-evidence
{
  "dry_run": true,
  "changed_files": ["apps/api/knownet_api/routes/collaboration.py"],
  "verification": "targeted pytest passed"
}
```

Use `dry_run: true` first to validate the evidence payload. With
`dry_run: false`, KnowNet creates the implementation record, marks the finding
implemented through the existing core path, and marks the linked finding task
done.

For the shortest Codex closure path, use the compact evidence endpoint:

```txt
POST /api/collaboration/findings/{finding_id}/evidence
{
  "implemented": true,
  "commit": "abcdef1",
  "note": "Targeted pytest passed."
}
```

This records the same implementation evidence path with a smaller body. Use the
full implementation-evidence endpoint when you need explicit changed files,
dry-run validation, or git status collection.

## Page Revision Restore Safety

AI-assisted restore flows should pass the revision they inspected:

```txt
POST /api/pages/{slug}/revisions/{revision_id}/restore
{
  "expected_current_revision_id": "rev_current_when_reviewed"
}
```

KnowNet returns `409 page_revision_conflict` if the page changed after the AI or
operator inspected it. Manual no-body restores still work, but automation should
use the optimistic lock.

## Phase Transition

Before moving from Phase N to Phase N+1, create a snapshot, run targeted checks,
then run verify-index.

## Recovery Without Backups

If no snapshot exists but Markdown files remain, recreate `knownet.db`, re-index
pages, rebuild citation audits, and rebuild the graph.

## Agent Token Rotation

Use the Agent Access dashboard as the normal operator path. It shows token
health counts, status filters, token detail, and recent sanitized access events.
The summary row refreshes only when the page loads or the operator clicks
Refresh.

Before creating an agent token:

```txt
1. Confirm the minimum required scope.
2. Set an expiry date.
3. Fill in purpose.
4. Decide whether the token is for MCP or SDK.
5. Confirm where the token will be stored.
```

After creating or rotating:

```txt
1. Copy the raw token once from the warning panel.
2. Store it in the target MCP/SDK environment.
3. Dismiss the raw token panel only after storage is confirmed.
4. Run a small ping/me test from the target client.
```

Rotate a token from the dashboard or with
`POST /api/agents/tokens/{token_id}/rotate`. The new raw token is shown once, so
update the MCP or SDK environment immediately.

Revoke unused tokens with `POST /api/agents/tokens/{token_id}/revoke`. Revoked
tokens cannot call `/api/agent/*` and cannot use write gateways.

If an agent reports `scope_denied`, open the token events and inspect the
sanitized metadata for required/current scopes. If it reports `rate_limited`,
check recent rate-limited events and lower the client request size or frequency.
Rotate tokens that are expired or expiring soon.

## MCP Setup

The MCP server runs over stdio from `apps/mcp/src/knownet_mcp/server.py`.
Set:

```txt
KNOWNET_BASE_URL=http://127.0.0.1:8000
KNOWNET_AGENT_TOKEN=<token shown once by the operator dashboard>
KNOWNET_MCP_LOG_FORMAT=json
```

Use an agent token with only the scopes needed by the AI tool. The MCP server
does not expose maintenance tools.

Logs go to stderr and JSON-RPC responses go to stdout. If an MCP client shows
`auth_failed`, rotate the token and update the client environment. If it shows
`scope_denied`, create a token with the missing read or review scope. If it
shows `context_too_large`, lower the tool limit or read one page at a time.
If MCP `initialize` reports `token_warning=expires_soon`, rotate the token before
running a long review. Include MCP `request_id` values when investigating failed
calls; they also appear in MCP stderr logs.

See `docs/MCP_CLIENTS.md` for Claude Desktop, Cursor, and local stdio examples.
