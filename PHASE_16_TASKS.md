# Phase 16 Tasks: External Model Runner And Desktop MCP

Phase 16 adds a server-side Gemini API review path. Earlier external AI tests
showed that web chat products usually cannot call local MCP, send arbitrary
JSON-RPC POST requests, attach bearer headers, or reach localhost. Phase 16
therefore reverses the direction: KnowNet prepares a safe structured context,
calls Gemini through an operator-controlled API integration, and imports the
model response through the existing review/finding dry-run workflow.

Phase 16 also makes Claude Desktop a first-class local MCP client target.
Claude Desktop is different from Claude web: it can launch or connect to a
local MCP server on the user's machine. KnowNet should support that route with
clear Windows configuration, safe token handling, and an optional packaged
desktop extension path.

Phase 16 also defines the first supported Manus path. Manus should not be
treated like a localhost desktop client. It should use an HTTPS Custom MCP
Server or Custom API gateway, with a read-first permission model and an optional
Manus Skill that teaches the agent how to use KnowNet.

Phase 16 also defines a better DeepSeek path. DeepSeek web chat remains a
limited preview/fallback surface, but DeepSeek API can be used through
tool/function calling or JSON output. KnowNet should support DeepSeek through a
controlled Agent Runner that executes KnowNet tools, rather than expecting the
DeepSeek web UI to call MCP or localhost.

Phase 16 also defines a Qwen path. Qwen web chat is only a fallback, but Qwen
API, Qwen-Agent, Qwen-Agent MCP, and Qwen Code MCP are strong candidates for
KnowNet integration. Qwen should be supported through OpenAI-compatible API
tool calling first, with Qwen-Agent/MCP configuration as the higher-capability
route.

Phase 16 also defines a Kimi path. Kimi web chat is only a fallback, but Kimi
API tool calling and Kimi Code MCP are useful KnowNet targets. Kimi should use
the same Agent Runner pattern as DeepSeek/Qwen for API calls, and a Kimi Code
MCP profile for coding/developer workflows.

Phase 16 also defines a MiniMax path. MiniMax web chat is only a fallback, but
MiniMax API tool calling, Mini-Agent HTTP tools, and Mini-Agent MCP can make it
a useful KnowNet agent. The official MiniMax MCP server is mainly for exposing
MiniMax media/model capabilities to other clients; KnowNet should instead make
its own MCP/API surfaces consumable by Mini-Agent.

Phase 16 also defines a GLM/Z.AI path. GLM web chat is only a fallback. The
useful path is GLM Coding Plan or GLM-compatible coding tools such as Claude
Code, Cline, OpenCode, Cursor, or Z Code connected to KnowNet MCP. Zread MCP is
useful for public GitHub repository structure/file reading, but it is not a
substitute for KnowNet's own live state surfaces.

Implementation status: common foundation implemented for Gemini mock only.

Implemented surface as of 2026-05-03:

```txt
Done:
  - model_review_runs schema and startup schema guard
  - shared provider adapter contract in API service layer
  - safe context builder using DB-derived ai_state and collaboration records
  - secret/path guard for model context
  - structured model output normalization
  - conversion from model JSON output to existing Finding Markdown
  - Gemini mock adapter only
  - DeepSeek API adapter
  - MiniMax API adapter
  - Kimi API adapter
  - GLM/Z.AI API adapter
  - Qwen-Agent MCP config/profile
  - Manus Custom MCP config/profile
  - Manus connector URL registration smoke-tested through quick tunnel
  - operator-only /api/model-runs endpoints
  - dry-run-ready run storage
  - explicit operator import into collaboration_reviews/collaboration_findings
  - cancellation/list/detail/re-dry-run endpoints
  - tests for mock run, import, secret rejection, and active-run blocking

Not done in this step:
  - real Gemini network adapter
  - operator UI
  - provider cost accounting beyond token estimates
  - paid/API live verification
  - Qwen API runner
  - Manus live Custom MCP/API registration
```

## Fixed Decisions

```txt
Gemini web chat is not an integration target.
Gemini API is the integration target.

KnowNet calls Gemini.
Gemini does not call KnowNet.

Phase 16 is not a replacement for MCP:
  MCP remains for ChatGPT PC app, Claude Desktop, Cursor, and other clients
  that can actually call MCP tools.

Claude Desktop:
  Is an MCP-capable desktop client target.
  Uses local MCP, not Cloudflare, GET preview, or arbitrary web POST.
  Should connect to the existing KnowNet MCP server through stdio/local
  process configuration first.
  Should use a scoped agent token through environment variables.
  Must not receive direct database-file access.
  Must not receive whole-PC filesystem access.
  Should use existing knownet_* tools and resources, not a separate tool family.
  May later use a packaged .mcpb desktop extension after the plain config path
  is stable.

Manus:
  Is an HTTPS integration target, not a localhost target.
  Should use Custom MCP Server or Custom API first.
  Should start read-only.
  Should use scoped bearer tokens.
  Should not receive ADMIN_TOKEN.
  Should not receive raw database files.
  Should not receive broad write/RPC access until read-only behavior is proven.
  May use a Manus Skill as operating guidance, but the Skill is guidance only;
  API/MCP permissions remain the real security boundary.

DeepSeek:
  DeepSeek web chat is a fallback, not the primary integration path.
  DeepSeek API is the primary integration path.
  Use Function/Tool Calling or JSON Output through a KnowNet-controlled Agent
  Runner.
  DeepSeek chooses tool calls; the runner executes KnowNet calls.
  The runner must validate every tool argument before calling KnowNet.
  Start read-only.
  Do not expose maintenance, raw DB, backup, shell, or filesystem tools.
  Reuse the same safe context and review/finding import rules as Gemini.

Qwen:
  Qwen web chat is a fallback, not the primary integration path.
  Qwen API/OpenAI-compatible API is a primary integration path.
  Qwen-Agent with HTTP tools is a primary integration path.
  Qwen-Agent with MCP is a high-capability integration path.
  Qwen Code with MCP is a developer/code workflow candidate.
  Start read-only.
  Reuse knownet_* tools where possible.
  Do not create Qwen-specific finding tables or page-write paths.
  Tool calling must be validated by the KnowNet runner or Qwen-Agent wrapper.

Kimi:
  Kimi web chat is a fallback, not the primary integration path.
  Kimi API/OpenAI-compatible API is a primary integration path.
  Kimi API tool_calls can use the same Agent Runner pattern as Qwen/DeepSeek.
  Kimi Code MCP is a high-capability developer integration path.
  Start read-only.
  Reuse knownet_* tools where possible.
  Do not create Kimi-specific finding tables or page-write paths.
  Tool calling must be validated by the KnowNet runner or Kimi Code/MCP wrapper.

MiniMax:
  MiniMax web chat is a fallback, not the primary integration path.
  MiniMax API tool calling is a primary integration path.
  Mini-Agent with HTTP tools is a primary integration path.
  Mini-Agent with KnowNet MCP is a high-capability integration path.
  Official MiniMax MCP server is not the KnowNet access path; it exposes
  MiniMax generation/search/vision style capabilities to other clients.
  Start read-only.
  Reuse knownet_* tools where possible.
  Do not create MiniMax-specific finding tables or page-write paths.
  Tool calling must be validated by the KnowNet runner or Mini-Agent wrapper.

GLM/Z.AI:
  GLM web chat is a fallback, not the primary integration path.
  GLM Coding Plan through MCP-capable coding tools is a primary path.
  GLM API/compatible endpoint plus Agent Runner is a secondary path.
  Zread MCP is useful for public GitHub repo reading only.
  KnowNet MCP is required for live KnowNet state, DB-derived JSON, graph, and
  collaboration review/finding workflows.
  Start read-only.
  Reuse knownet_* tools where possible.
  Do not expose maintenance, raw DB, backup, shell, or broad filesystem tools.

Paid/best-path and free/realistic-path must be documented separately.
Do not imply that paid/API/MCP features are available in free web chat.
Every provider integration doc must say:
  best paid path
  realistic free path
  what KnowNet can test locally without paid access
  what remains unverified until the operator obtains paid/API access

If the free/current route can perform full MCP/tool calls, keep that route as
the single first-class path and do not add a second provider runner merely for
symmetry. If the free route is only GET preview, pasted packs, or GitHub
preview, keep two paths: realistic free fallback plus best paid/API/agent path.

Implementation target:
  Build the strongest plausible integration path for each provider up to
  implemented_mocked without requiring paid accounts.
  Do not wait for paid/API access to create schemas, runners, configs, docs,
  and mocked tests.
  Live verification is a later status upgrade, not a blocker for implementing
  the integration surface.

Provider implementations must share one common adapter contract.
Provider-specific files are thin profiles over shared schemas and shared
runner logic; they must not become separate products.

Phase 16 is not a replacement for GET preview:
  GET preview remains a low-friction read-only fallback for web-only AIs.

Phase 16 is not a replacement for SDK:
  SDK remains for user-owned automation scripts.

Phase 16 adds an internal external-model runner:
  It may create collaboration_reviews and collaboration_findings only through
  the existing dry-run/import path.
  It must not write pages.
  It must not apply suggestions.
  It must not execute code.
  It must not read raw DB files.
  It must not expose secrets, token hashes, raw tokens, sessions, users,
  backups, inbox raw messages, or local absolute file paths.

Gemini output must be structured JSON.
The imported review must still be converted into the existing Finding format.
Operator approval is required before durable import unless explicitly running
in a local test mode.
```

## P16-001 Model Runner Architecture

Goal:

```txt
Introduce a clear internal boundary for server-side model calls.
```

Tasks:

```txt
1. Add a model runner service boundary under the API layer.
2. Support provider = "gemini" first.
3. Keep provider interface small:
     create_review_run(context, prompt_profile, model_config)
     dry_run_review_output(run_id)
     import_review_output(run_id)
4. Do not let the model runner write pages or mutate graph data directly.
5. Store model run status separately from collaboration review status.
6. Log run lifecycle to audit_events.
```

Data model:

```sql
CREATE TABLE model_review_runs (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,              -- gemini
  model TEXT NOT NULL,
  prompt_profile TEXT NOT NULL,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  status TEXT NOT NULL,                -- queued | running | dry_run_ready | imported | failed | cancelled
  context_summary_json TEXT NOT NULL,  -- counts, selected ids, revision ids, hashes only
  request_json TEXT,                   -- sanitized request metadata, no secrets
  response_json TEXT,                  -- structured model output, no raw API headers
  input_tokens INTEGER,
  output_tokens INTEGER,
  estimated_cost_usd REAL,
  review_id TEXT,
  error_code TEXT,
  error_message TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Status rules:

```txt
queued -> running -> dry_run_ready -> imported
queued -> cancelled
running -> failed
dry_run_ready -> cancelled
dry_run_ready -> imported

Import creates collaboration_reviews/collaboration_findings through the
existing review import path.
```

Done when:

```txt
The architecture document and schema leave no ambiguity that Gemini is called
by KnowNet, not the other way around.
```

## P16-001A Provider Adapter Contract

Goal:

```txt
Keep Gemini, DeepSeek, Qwen, Kimi, MiniMax, and GLM integrations consistent.
Provider differences should live in adapters, not leak into collaboration,
finding, UI, or DB concepts.
```

Shared provider interface:

```python
class ModelProviderAdapter:
    provider_id: str

    def build_request(self, context: dict, prompt_profile: str, config: dict) -> dict: ...
    def call_model(self, request: dict) -> dict: ...
    def parse_response(self, raw_response: dict) -> dict: ...
    def token_count(self, context: dict) -> int | None: ...
    def sanitize_error(self, error: Exception | dict | str) -> dict: ...
```

Shared normalized review output:

```json
{
  "review_title": "string",
  "overall_assessment": "string",
  "findings": [
    {
      "title": "string",
      "severity": "critical | high | medium | low | info",
      "area": "API | UI | Rust | Security | Data | Ops | Docs",
      "evidence": "string",
      "proposed_change": "string",
      "confidence": 0.0
    }
  ],
  "summary": {
    "most_important_issue": "string | null",
    "immediate_fixes": ["string"],
    "dry_run_possible": true
  }
}
```

Shared tool surface:

```txt
All provider tool schemas derive from one canonical KnowNet tool registry.

Canonical read/review tools:
  knownet_discover
  knownet_start_here
  knownet_state_summary
  knownet_ai_state
  knownet_list_findings
  knownet_read_page
  knownet_review_dry_run

Provider exports:
  /tools.deepseek.json
  /tools.qwen.json
  /tools.kimi.json
  /tools.minimax.json
  /tools.glm.json

These exports may differ only in provider schema syntax, not in semantic tool
meaning.
```

Shared state model:

```txt
model_review_runs.provider identifies the provider.
No provider-specific review tables.
No provider-specific finding tables.
No provider-specific UI state machine.
No provider-specific status names.

Provider-specific data belongs in:
  request_json
  response_json
  context_summary_json
  provider_config_json if later added
```

Shared config naming:

```txt
{PROVIDER}_RUNNER_ENABLED
{PROVIDER}_API_KEY
{PROVIDER}_BASE_URL
{PROVIDER}_MODEL
{PROVIDER}_MAX_CONTEXT_TOKENS
{PROVIDER}_TIMEOUT_SECONDS
{PROVIDER}_DAILY_RUN_LIMIT
{PROVIDER}_REQUIRE_OPERATOR_IMPORT

Provider IDs:
  gemini
  deepseek
  qwen
  kimi
  minimax
  glm
```

Shared verification status:

```txt
implemented_mocked
web_preview_verified
test_live_verified
live_verified
```

Rules:

```txt
1. Add a provider by adding an adapter and a profile, not by duplicating the
   runner.
2. All providers must use the same safe context builder.
3. All providers must use the same normalized review output.
4. All providers must use the same dry-run/import path.
5. All providers must use the same secret/path guard.
6. All providers must use the same run status state machine.
7. UI must show provider as a filter/label, not as separate dashboards.
```

Done when:

```txt
Provider-specific integration docs cannot drift into separate product designs;
they are visibly profiles over a shared KnowNet model runner.
```

## P16-002 Gemini Configuration And Secrets

Goal:

```txt
Configure Gemini without leaking API keys or making cloud calls accidental.
```

Fixed config:

```txt
GEMINI_API_KEY                 required only when Gemini runner is enabled
GEMINI_MODEL                   default chosen during implementation after checking official docs
GEMINI_RUNNER_ENABLED          default false
GEMINI_MAX_CONTEXT_TOKENS      default 32000
GEMINI_MAX_CONTEXT_CHARS       fallback guard only, default 120000
GEMINI_TIMEOUT_SECONDS         default 90
GEMINI_DAILY_RUN_LIMIT         default 20
GEMINI_REQUIRE_OPERATOR_IMPORT default true
```

Tasks:

```txt
1. Do not enable Gemini calls by default.
2. Never return GEMINI_API_KEY through API, MCP, SDK, logs, dashboard, or
   context bundles.
3. Add health signal:
     gemini.configured
     gemini.disabled
     gemini.quota_limited
     gemini.last_error_code
     gemini.last_error_summary
4. If GEMINI_RUNNER_ENABLED=false, UI/API should show disabled state instead
   of failing mysteriously.
5. If API key is missing, return explicit configuration error.
6. Do not expose raw provider error bodies through health endpoints.
```

Implementation note:

```txt
Before implementation, check current official Gemini API documentation.
Gemini structured output supports JSON-shaped responses through the API/SDK,
but exact package names, model names, token-counting APIs, and schema support
can change.

Health/error sanitizing:

```txt
Provider errors are sanitized before storage or API exposure.
Mask:
  API key values
  bearer tokens
  local absolute paths
  request headers
  raw provider request bodies

Health may expose:
  error_code
  short sanitized summary
  occurred_at

Health must not expose:
  full provider traceback
  raw response body
  request payload
  API key fragments
```
```

Done when:

```txt
Gemini cannot be called accidentally, and key/config problems are visible
without exposing secret values.
```

## P16-003 Safe Context Builder

Goal:

```txt
Build the model input from existing safe agent surfaces, not from raw files or
the database file.
```

Input sources:

```txt
Allowed:
  GET /api/agent/state-summary equivalent internal service data
  ai_state rows already sanitized for external agents
  selected page summaries/content through scoped page read helpers
  current open/deferred findings
  graph summary counts and selected high-value node summaries
  citation audit summary without raw hidden evidence

Forbidden:
  knownet.db or any *.db file
  data/backups/
  .env and config secret values
  users and sessions
  token_hash and raw tokens
  audit IP/user-agent hashes
  data/inbox raw messages
  local absolute paths such as C:/knownet
```

Context shape:

```json
{
  "schema_version": 1,
  "purpose": "external_model_review",
  "project": "KnowNet AI collaboration knowledge base",
  "state_summary": {},
  "selected_ai_state_pages": [],
  "open_findings": [],
  "review_focus": [],
  "forbidden_actions": [],
  "output_contract": {}
}
```

Tasks:

```txt
1. Reuse Phase 14 onboarding policy and Phase 15 safe ai-state constraints.
2. Add deterministic context selection:
     system onboarding pages first
     managed state pages next
     open/deferred high severity findings next
     recent changed pages next
3. Add token budget:
     hard max by GEMINI_MAX_CONTEXT_TOKENS
     use Gemini token counter when available
     use conservative local estimate only as fallback
     keep GEMINI_MAX_CONTEXT_CHARS as an additional safety guard, not the
     primary budget
     include counts of omitted pages/findings
4. Add secret/path guard before any Gemini call.
5. Store context_summary_json with ids, revision_ids, counts, content hashes,
   token counts, and omitted counts, not the full prompt body.
6. Store enough snapshot metadata to explain what Gemini saw later:
     page_id
     slug
     current_revision_id at context build time
     content_hash
     included_sections count
     omitted_sections count
```

Done when:

```txt
The context builder can be tested without Gemini network access, refuses
content containing forbidden keys, forbidden paths, or local absolute paths,
and records revision_id/hash metadata for every included page.
```

## P16-004 Gemini Prompt And Output Schema

Goal:

```txt
Make Gemini produce parseable review output compatible with KnowNet findings.
```

Prompt profile:

```txt
default: gemini_external_reviewer_v1
```

Prompt requirements:

```txt
Tell Gemini:
  You are an external AI reviewer for KnowNet.
  Use only the provided context.
  Do not claim you called MCP unless tool results are included.
  Do not ask for raw database files.
  Do not ask for secrets.
  Do not propose direct filesystem edits.
  Return JSON only.
  Each finding must be actionable and grounded in provided evidence.
  If evidence is insufficient, use severity info or omit the finding.
```

Structured output schema:

```json
{
  "review_title": "string",
  "overall_assessment": "string",
  "findings": [
    {
      "title": "string",
      "severity": "critical | high | medium | low | info",
      "area": "API | UI | Rust | Security | Data | Ops | Docs",
      "evidence": "string",
      "proposed_change": "string",
      "confidence": 0.0
    }
  ],
  "summary": {
    "most_important_issue": "string | null",
    "immediate_fixes": ["string"],
    "dry_run_possible": true
  }
}
```

Validation rules:

```txt
Max findings per run: 20
Unknown severity -> info
Unknown area -> Docs
Missing title -> derive from first sentence of evidence
Empty evidence -> reject finding
Empty proposed_change -> reject finding
confidence outside 0..1 -> clamp or set null
Extra fields -> ignore, but record parser warning
Invalid JSON -> status failed, no import
```

Done when:

```txt
The Gemini response can be converted deterministically into the existing
review Markdown/Finding parser format.
```

## P16-005 Dry-Run Then Import Workflow

Goal:

```txt
Use Gemini as a reviewer, not as an automatic writer.
```

Workflow:

```txt
1. Operator creates model review run.
2. KnowNet builds safe context.
3. KnowNet calls Gemini API.
4. Gemini returns structured JSON.
5. KnowNet converts JSON to review Markdown.
6. Existing dry_run parser validates the review.
7. Operator sees dry-run result.
8. Operator imports review.
9. Imported findings enter existing triage queue.
```

API shape:

```txt
POST /api/model-runs/gemini/reviews
  Creates a run, performs the model call, and stores dry-run-ready output.
  Requires owner/admin.

GET /api/model-runs
GET /api/model-runs/{run_id}
  Read run status and sanitized output.
  Requires owner/admin.

POST /api/model-runs/{run_id}/dry-run
  Re-run parser on stored response.
  Requires owner/admin.

POST /api/model-runs/{run_id}/import
  Imports through existing collaboration review path.
  Requires owner/admin.

POST /api/model-runs/{run_id}/cancel
  Cancels queued/dry-run-ready run.
  Requires owner/admin.
```

Done when:

```txt
A Gemini run can reach dry_run_ready without creating collaboration records,
and import creates the same durable review/finding records as a human/API
review submission.
```

## P16-006 Operator UI

Goal:

```txt
Expose Gemini runs as an operator-controlled workflow, not a hidden background
automation.
```

UI location:

```txt
Agent Dashboard or Operations panel:
  "Model Reviews" tab
```

Minimum UI:

```txt
1. Gemini configured/disabled state.
2. New Gemini review run button.
3. Review focus selector:
     release hardening
     open findings
     agent onboarding
     graph/data consistency
4. Run status list.
5. Dry-run result preview.
6. Import button.
7. Cancel button.
8. Error details without secret values.
```

UI rules:

```txt
No automatic polling faster than existing dashboard conventions.
No raw prompt with secrets.
No API key display.
No auto-import.
No nested dashboard feature expansion.
```

Done when:

```txt
An operator can run Gemini review, inspect dry-run findings, and import or
discard the result without leaving the local UI.
```

## P16-007 Cost, Rate Limit, And Safety Controls

Goal:

```txt
Prevent accidental cost spikes and noisy model runs.
```

Controls:

```txt
Daily run limit.
Per-run token limit.
Per-run timeout.
No parallel Gemini runs in Phase 16.
Explicit operator action for each run.
Store input/output token counts when provider reports them.
Store approximate input/output chars only as secondary diagnostics.
Store provider latency and error code.
Add retry only for transient network/rate-limit errors, max 1 retry.
```

Concurrency lock:

```txt
Before creating a Gemini run, check for existing rows with status in
('queued', 'running').

If one exists:
  return gemini_run_already_active
  include active run_id and status
  do not call Gemini

The check and insertion must happen in one SQLite transaction.
No parallel Gemini calls are allowed in Phase 16 even if multiple operators
click the button.
```

Error codes:

```txt
gemini_disabled
gemini_api_key_missing
gemini_context_rejected
gemini_context_too_large
gemini_rate_limited
gemini_timeout
gemini_invalid_response
gemini_run_already_active
gemini_import_requires_operator
model_run_not_found
model_run_not_importable
```

Done when:

```txt
The runner can fail safely and visibly without creating partial reviews or
leaking data.
```

## P16-008 Tests

Goal:

```txt
Verify the Gemini path mostly with mocks, then support one manual live test.
```

Required automated tests:

```txt
1. Context builder excludes forbidden data and paths.
2. Context builder respects size budget and reports omissions.
2a. Context builder stores page revision_id and content_hash metadata.
2b. Token budget is enforced before Gemini call; chars are only fallback.
3. Gemini response JSON converts to valid review Markdown.
4. Invalid JSON creates failed model_review_run and no review.
5. Dry-run-ready run does not create collaboration_reviews.
6. Import creates collaboration_review and findings.
7. Import cannot run twice.
8. Disabled/missing-key states return explicit errors.
9. Admin/owner required for all model-runs endpoints.
10. Audit events are written for run create, failure, import, cancel.
11. Existing queued/running run blocks creation of a second Gemini run.
12. Provider error sanitization removes API keys, bearer tokens, and local
    absolute paths before health/API exposure.
```

Manual live test:

```txt
GEMINI_RUNNER_ENABLED=true
GEMINI_API_KEY set locally
Create one release-hardening review run
Verify dry_run_ready
Import only if result is useful
Revoke/disable API key after testing if it was temporary
Record result in docs/MODEL_RUNS.md
```

Done when:

```txt
Mocked tests pass in CI/local release check, and live Gemini test instructions
exist without requiring a live key during normal test runs.
```

## P16-009 Documentation

Goal:

```txt
Make the new direction clear so future AI agents do not keep trying to make
Gemini web chat call MCP.
```

Docs to update:

```txt
README.md
  Add integration matrix:
    MCP-capable desktop clients -> MCP
    Web chat only AIs -> GET preview or manual paste
    API-capable model providers -> server-side model runner

docs/MCP_CLIENTS.md
  Clarify that web chat products generally cannot call MCP directly.

docs/EXTERNAL_MODEL_RUNNER.md
  New doc for Gemini API flow, config, safety, and manual live test.

docs/RELEASE_HARDENING_RUN.md
  Add Phase 16 readiness note after implementation.
```

Done when:

```txt
The docs clearly say:
  Gemini web chat cannot be expected to POST to KnowNet.
  KnowNet can call Gemini API as a controlled reviewer.
```

## P16-009A Free Vs Paid Capability Matrix

Goal:

```txt
Separate the best official/paid integration path from what can realistically
be tested with free web accounts.
```

Why this exists:

```txt
Many providers advertise strong API, agent, or MCP support.
That does not mean the free web chat can:
  call localhost
  send arbitrary POST
  attach bearer headers
  perform JSON-RPC
  connect MCP servers
  run custom agent tool loops

KnowNet planning must not confuse "provider supports it somewhere" with
"the user's current free web account can test it today."
```

Provider matrix:

```txt
ChatGPT:
  Best paid/desktop path:
    ChatGPT PC app custom MCP connector, if available.
  Realistic free/web path:
    GET preview, pasted JSON/Markdown, GitHub/repo preview.
  Locally testable by KnowNet:
    MCP HTTP bridge, GET preview, API token flow.
  Unverified without account/client support:
    Actual connector tool calls from the user's ChatGPT plan/client.

Claude:
  Best paid/desktop path:
    Claude Desktop local MCP via claude_desktop_config.json.
  Realistic free/web path:
    GET preview or pasted resource JSON/Markdown.
  Locally testable by KnowNet:
    stdio MCP smoke script, config examples.
  Unverified without installing/configuring Claude Desktop:
    End-to-end Claude Desktop tool use.

Gemini:
  Best paid/API path:
    KnowNet server-side Gemini API runner.
  Realistic free/web path:
    GET preview, pasted state-summary/ai-state, manual review text.
  Locally testable by KnowNet:
    mocked Gemini runner, context builder, schema validation.
  Unverified without API key:
    Live Gemini API call, cost/latency/quota behavior.

Manus:
  Best paid/agent path:
    HTTPS Custom MCP or Custom API plus Manus Skill.
  Realistic free/web path:
    GET preview or pasted snapshot/context.
  Locally testable by KnowNet:
    HTTPS gateway smoke with local token, docs/config examples.
  Unverified without Manus integration access:
    Actual Manus Custom MCP/API registration and tool calls.

DeepSeek:
  Best paid/API path:
    DeepSeek API + function/tool calling or JSON command runner.
  Realistic free/web path:
    GET preview, GitHub/public docs, pasted context.
  Locally testable by KnowNet:
    mocked tool-call runner, schema export, JSON command validation.
  Unverified without API key:
    Live DeepSeek tool-call reliability, token/cost behavior.

Qwen:
  Best paid/API/agent path:
    Qwen API function calling, Qwen-Agent, Qwen-Agent MCP, Qwen Code MCP.
    Qwen API requires Alibaba Cloud DashScope / Model Studio signup; free usage
    may be available after signup.
  Realistic free/web path:
    Qwen web chat with GET preview, upload/paste, GitHub preview.
  Locally testable by KnowNet:
    mocked Qwen runner, Qwen-Agent config validation, MCP config smoke.
  Unverified without API/agent setup:
    Live Qwen-Agent or Qwen Code tool loop.

Kimi:
  Best paid/API/code path:
    Kimi API tool_calls or Kimi Code MCP.
  Realistic free/web path:
    Kimi web chat with GET preview, upload/paste, GitHub preview.
    Free Kimi web does not provide the API key needed for live runner tests.
  Locally testable by KnowNet:
    mocked Kimi runner, Kimi Code MCP config validation.
  Unverified without API/code access:
    Live Kimi API tool calls or Kimi Code MCP.
    Kimi API key creation requires paid/API access.

MiniMax:
  Best paid/API/agent path:
    MiniMax API tool calling or Mini-Agent with HTTP/MCP tools.
  Realistic free/web path:
    MiniMax web chat with GET preview, upload/paste, GitHub preview.
  Locally testable by KnowNet:
    mocked MiniMax runner, Mini-Agent config validation.
  Unverified without API/Mini-Agent access:
    Live MiniMax tool loop and Mini-Agent MCP behavior.

GLM/Z.AI:
  Best paid/coding-tool path:
    GLM Coding Plan in Claude Code/Cline/OpenCode/Cursor with KnowNet MCP.
  Realistic free/web path:
    GLM/Z.ai web chat with GET preview, GitHub preview, pasted context.
  Locally testable by KnowNet:
    KnowNet MCP config examples, static config validation.
  Unverified without Coding Plan/coding tool setup:
    Live GLM-backed coding tool calling KnowNet MCP.
```

Implementation rule:

```txt
Provider docs must not mark live integration complete unless the corresponding
client/API path was actually tested.

Phase 16 target status for most paid/API providers:
  implemented_mocked

Phase 16 may reach live_verified only for providers where the user already has
the required account/client/key and explicitly runs the live test.

If only mocked tests pass:
  status = "implemented_mocked"

If free web/manual preview was tested:
  status = "web_preview_verified"

If live API/MCP client was tested:
  status = "live_verified"

If a quick tunnel or temporary local bridge was live-tested but is not
production-stable:
  status = "test_live_verified"
```

Provider strength rule:

```txt
For every provider, implement the strongest feasible connection shape:
  API/tool runner if provider API is the strongest path.
  MCP config/profile if provider client supports MCP.
  HTTPS gateway docs if provider requires public HTTPS.
  GET preview/manual paste fallback if free web is the only available test.

Do not down-scope implementation just because the current user lacks a paid
plan. Down-scope only live verification status.
```

Done when:

```txt
Phase 16 docs make it obvious which integrations are actually testable for a
free user today and which require paid/API/client setup.
```

## P16-010 Claude Desktop Local MCP Support

Goal:

```txt
Make Claude Desktop a supported local MCP path for KnowNet without relying on
Cloudflare tunnels or web-chat network behavior.
```

Correct mental model:

```txt
Claude Desktop
  -> launches/connects to local KnowNet MCP server
  -> MCP server calls local KnowNet API with scoped agent token
  -> KnowNet API reads/writes through existing safe surfaces

Claude Desktop does not need to POST to the public /mcp URL.
Claude web chat remains outside this support path.
```

Supported connection modes:

```txt
Phase 16 required:
  Manual claude_desktop_config.json setup for Windows.

Phase 16 optional if time permits:
  .mcpb desktop extension package skeleton.

Later phase candidate:
  One-click packaged installer with automatic token creation.
```

Configuration requirements:

```txt
Use command + args to start the KnowNet MCP stdio server.
Pass KNOWNET_BASE_URL through env.
Pass KNOWNET_AGENT_TOKEN through env.
Do not put ADMIN_TOKEN in Claude Desktop config.
Do not put raw SQLite paths in Claude Desktop config unless they are only
used by KnowNet's own local server process and never exposed as tools.
Prefer local API URL:
  http://127.0.0.1:8000
```

Example config shape:

```json
{
  "mcpServers": {
    "knownet": {
      "command": "C:\\knownet\\apps\\api\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\knownet\\apps\\mcp\\run_stdio.py"
      ],
      "env": {
        "KNOWNET_BASE_URL": "http://127.0.0.1:8000",
        "KNOWNET_AGENT_TOKEN": "kn_agent_REPLACE_WITH_SCOPED_TOKEN"
      }
    }
  }
}
```

Tool policy:

```txt
Expose the existing Phase 10-14 MCP tools/resources.
Do not add direct filesystem tools.
Do not add raw database tools.
Do not add maintenance tools.
Do not add generic shell/code execution tools.

Claude Desktop should start with:
  knownet_start_here
  knownet_me
  knownet_state_summary
  knownet_ai_state
  knownet_list_findings
  knownet_review_dry_run
```

Security rules:

```txt
Create a dedicated Claude Desktop agent token.
Recommended role: agent_reviewer.
Recommended scopes:
  preset:reader
  preset:reviewer

Token should have an expiry.
Token should be revocable from Agent Dashboard.
Token value is shown once by KnowNet and then pasted into local config by the
operator.
MCP logs must redact token values.
Claude Desktop config examples must use placeholders only.
```

Tasks:

```txt
1. Verify apps/mcp stdio entrypoint works from a clean PowerShell command.
2. Add docs/CLAUDE_DESKTOP_MCP.md with Windows setup steps.
3. Include a known-good claude_desktop_config.json example with placeholders.
4. Add troubleshooting:
     server not visible
     tools/list fails
     knownet_start_here fails
     token revoked/expired
     KnowNet API not running
     Claude Desktop restart required
5. Add a local smoke script that runs MCP initialize/tools-list/start_here
   without launching Claude Desktop.
6. Document that Cloudflare tunnel is not needed for Claude Desktop local MCP.
7. If .mcpb is added, include only package skeleton and manifest; do not make
   it the primary supported path until manual config is stable.
```

Done when:

```txt
A user can configure Claude Desktop on Windows, restart Claude Desktop, see the
KnowNet tools, call knownet_start_here, and understand that this is local MCP
rather than public web access.
```

## P16-011 Manus HTTPS Gateway Support

Goal:

```txt
Make Manus a supported cloud-agent path through HTTPS Custom MCP/API, without
pretending it can directly access localhost like Claude Desktop.
```

Correct mental model:

```txt
Manus
  -> HTTPS Custom MCP Server or Custom API
  -> KnowNet public gateway
  -> local KnowNet API/Core through controlled tunnel or deployment

Manus does not directly read C:\knownet.
Manus does not directly call localhost.
Manus should not get broad write access during initial support.
```

Supported connection modes:

```txt
Phase 16 required:
  HTTPS read-only Custom API profile.

Phase 16 optional:
  HTTPS Custom MCP Server profile using existing knownet_* tool names.
  Manus Skill skeleton with KnowNet usage order.

Later phase candidate:
  Manus API reverse integration where KnowNet creates Manus tasks and imports
  results.
```

Gateway requirements:

```txt
HTTPS required.
Cloudflare Tunnel is acceptable for testing only.
Named tunnel or hosted gateway required before real operation.
PUBLIC_MODE must be paired with a real access gate before non-test exposure.

Read-only gateway minimum:
  GET /mcp
  GET /mcp?resource=agent:onboarding
  GET /mcp?resource=agent:state-summary
  GET /api/agent/me
  GET /api/agent/state-summary
  GET /api/agent/ai-state
  GET /api/agent/pages
  GET /api/agent/graph

Do not expose:
  maintenance endpoints
  raw DB files
  backup archives
  session/user/token internals
  shell/file tools
```

Token model:

```txt
Create a dedicated Manus read token first.
Recommended role: agent_reader.
Recommended scopes:
  preset:reader

Writable Manus token is a separate later step.
If write is enabled, use agent_reviewer or agent_contributor with short expiry.
Never reuse Claude Desktop, ChatGPT PC app, or generic external review tokens.
```

Custom MCP profile:

```txt
Use existing KnowNet MCP HTTP bridge.
Use existing knownet_* tools/resources.
Do not create a Manus-only duplicate tool family.

Preferred first tools:
  knownet_start_here
  knownet_me
  knownet_state_summary
  knownet_ai_state
  knownet_list_findings
  knownet_review_dry_run
```

Custom API profile:

```txt
Expose a small documented read API for Manus setup:
  discover current gateway
  read onboarding
  read state summary
  read ai-state page list
  read selected page
  read graph summary

If Manus Custom API cannot handle JSON-RPC MCP well, use these REST endpoints
instead of asking Manus web chat to manually POST JSON-RPC.
```

Manus Skill:

```txt
Create docs/manus-skill/SKILL.md or equivalent package skeleton.

The Skill should say:
  1. Use KnowNet Custom MCP tools if available.
  2. Use KnowNet Custom API if MCP is unavailable.
  3. Read agent:onboarding and agent:state-summary first.
  4. Use GitHub only as fallback, not as canonical state.
  5. Dry-run review before submit.
  6. Do not request raw DB, secrets, backups, local paths, or maintenance
     access.
```

Tasks:

```txt
1. Add docs/MANUS_INTEGRATION.md.
2. Document Manus Custom API registration fields:
     base URL
     bearer token
     read-only scope
     expected first calls
3. Document Manus Custom MCP registration fields if HTTP MCP works.
4. Add a read-only gateway smoke check:
     /mcp
     /mcp?resource=agent:onboarding
     /mcp?resource=agent:state-summary
     /api/agent/state-summary with Manus token
     /api/agent/ai-state with Manus token
5. Add warning that quick tunnels are testing-only.
6. Add Manus Skill skeleton if time permits.
7. Record a Manus setup attempt in docs/EXTERNAL_AI_ACCESS_LOG.md.
```

Done when:

```txt
Manus has a documented, scoped, HTTPS-based path into KnowNet that does not
depend on localhost access and does not require raw write privileges.
```

Implementation note 2026-05-03:

```txt
Implemented:
  apps/mcp/configs/manus_custom_mcp.example.json
  apps/mcp/client_profiles/manus.json
  docs/MANUS_INTEGRATION.md

The current implemented Manus surface is configuration and documentation only.
Manus connector URL registration was smoke-tested through the current quick
tunnel, and read-only MCP tool calls succeeded. Production readiness still
requires a protected HTTPS endpoint with named tunnel and access control.
```

## P16-012 DeepSeek API Agent Runner

Goal:

```txt
Support DeepSeek through API-based tool calling/JSON output, not through the
consumer web chat surface.
```

Correct mental model:

```txt
DeepSeek API
  -> returns tool/function call or JSON command
  -> KnowNet Agent Runner validates the command
  -> Runner calls KnowNet API/MCP/SDK-safe surfaces
  -> Runner returns tool results to DeepSeek if another step is needed
  -> Final review is converted to existing review/finding dry-run format

DeepSeek does not directly access localhost.
DeepSeek does not receive raw DB files.
DeepSeek does not execute KnowNet writes by itself.
```

Supported modes:

```txt
Primary:
  DeepSeek API + Function/Tool Calling.

Fallback:
  DeepSeek API + JSON Output command router.

Not primary:
  DeepSeek web chat with GitHub URL or pasted docs.
```

Configuration:

```txt
DEEPSEEK_API_KEY                 required only when DeepSeek runner is enabled
DEEPSEEK_MODEL                   default chosen during implementation after checking official docs
DEEPSEEK_RUNNER_ENABLED          default false
DEEPSEEK_MAX_CONTEXT_TOKENS      default 32000
DEEPSEEK_TIMEOUT_SECONDS         default 90
DEEPSEEK_DAILY_RUN_LIMIT         default 20
DEEPSEEK_REQUIRE_OPERATOR_IMPORT default true
```

Tool/function schema:

```txt
Expose only read/review tools to DeepSeek runner:
  knownet_discover
  knownet_start_here
  knownet_state_summary
  knownet_ai_state
  knownet_list_findings
  knownet_read_page
  knownet_review_dry_run

Do not expose:
  maintenance
  raw database
  backup
  shell/code execution
  arbitrary HTTP fetch
  direct page write
```

Strict schema rules:

```txt
Before implementation, check current official DeepSeek API docs.
DeepSeek Function Calling strict mode has JSON Schema constraints.
Use additionalProperties=false where supported/required.
All function arguments must be validated locally before execution.
Invalid function name -> reject.
Invalid args -> reject.
Repeated tool loop > configured limit -> stop and mark failed.
```

JSON command fallback schema:

```json
{
  "action": "knownet_state_summary | knownet_ai_state | knownet_list_findings | knownet_read_page | knownet_review_dry_run",
  "args": {}
}
```

Agent loop rules:

```txt
Max tool steps per run: 8
Max model calls per run: 4
No parallel DeepSeek runs in Phase 16.
Use same singleton active-run lock pattern as Gemini, scoped by provider.
Record tool calls in model_review_runs.request_json as sanitized summaries.
Do not store raw API key, raw headers, or full hidden chain/tool reasoning.
```

Output handling:

```txt
DeepSeek final review output must become the same structured review JSON used
by the Gemini runner, then the same review Markdown, then the same dry-run
parser.

No DeepSeek-specific collaboration table.
No DeepSeek-specific finding format.
Provider differences stay inside the model runner.
```

Artifacts:

```txt
docs/DEEPSEEK_AGENT_RUNNER.md
GET /tools.deepseek.json or equivalent local schema export for runner setup
GET /schemas/deepseek_command.schema.json or static schema file
```

Tests:

```txt
1. DeepSeek tool schema includes only allowed read/review tools.
2. Invalid tool name is rejected before KnowNet call.
3. Invalid args are rejected before KnowNet call.
4. JSON command fallback routes to allowed actions only.
5. Tool loop limit stops runaway calls.
6. Dry-run result creates no collaboration records until operator import.
7. DeepSeek disabled/missing-key states return explicit errors.
8. Error sanitizer removes API keys, bearer tokens, and local paths.
```

Done when:

```txt
DeepSeek has a documented API Agent Runner path that is meaningfully better
than web-chat URL preview, while preserving KnowNet's existing security and
review/finding boundaries.
```

## P16-013 Qwen API, Qwen-Agent, And MCP Profiles

Goal:

```txt
Support Qwen through the integration surfaces where it is strongest:
OpenAI-compatible API, Qwen-Agent tools, Qwen-Agent MCP, and Qwen Code MCP.
```

Correct mental model:

```txt
Qwen Web Chat
  -> fallback preview/manual paste only

Qwen API
  -> OpenAI-compatible chat/tool calling
  -> KnowNet Agent Runner validates and executes tools

Qwen-Agent HTTP Tools
  -> Qwen-Agent wraps KnowNet REST/API tools

Qwen-Agent MCP
  -> Qwen-Agent connects to KnowNet MCP server

Qwen Code MCP
  -> developer/code workflow candidate using KnowNet MCP context
```

Supported modes:

```txt
Phase 16 required:
  Qwen API/OpenAI-compatible function-calling schema profile.
  Qwen-Agent HTTP tool configuration document.

Phase 16 optional:
  Qwen-Agent MCP configuration document.
  Qwen Code MCP configuration document.

Later phase candidate:
  Local Qwen model serving through vLLM/SGLang/Ollama after GPU/runtime needs
  are understood.
```

Configuration:

```txt
QWEN_API_KEY                 required only when Qwen API runner is enabled
QWEN_BASE_URL                provider endpoint, default documented during implementation
QWEN_MODEL                   default chosen during implementation after checking official docs
QWEN_RUNNER_ENABLED          default false
QWEN_MAX_CONTEXT_TOKENS      default 32000
QWEN_TIMEOUT_SECONDS         default 90
QWEN_DAILY_RUN_LIMIT         default 20
QWEN_REQUIRE_OPERATOR_IMPORT default true
```

Tool profile:

```txt
Expose only read/review tools first:
  knownet_discover
  knownet_start_here
  knownet_state_summary
  knownet_ai_state
  knownet_list_findings
  knownet_read_page
  knownet_review_dry_run

Do not expose:
  maintenance
  raw database
  backup
  shell/code execution
  arbitrary filesystem read
  direct page write
```

Qwen-Agent HTTP profile:

```txt
Provide docs/QWEN_AGENT_INTEGRATION.md with:
  install notes
  required environment variables
  KnowNet API base URL
  scoped agent token
  tool list
  first call order
  dry-run-before-submit rule
```

Qwen-Agent MCP profile:

```txt
Provide a sample qwen-agent MCP config that points at the existing KnowNet MCP
server. Use placeholders only.

The config must not include:
  ADMIN_TOKEN
  raw DB path
  whole-PC filesystem permission
```

Qwen Code profile:

```txt
Document Qwen Code + MCP as a developer workflow candidate, not a default
operator path.

It may read KnowNet context and suggest code work.
It must not bypass Codex/local implementation review.
```

Artifacts:

```txt
docs/QWEN_AGENT_INTEGRATION.md
GET /tools.qwen.json or equivalent static schema export
docs/qwen-agent-knownet-config.example.json
docs/qwen-code-knownet-mcp.example.json
```

Tests:

```txt
1. Qwen tool schema includes only allowed read/review tools.
2. Qwen tool schema is OpenAI-compatible.
3. Invalid tool name is rejected before KnowNet call.
4. Invalid args are rejected before KnowNet call.
5. Qwen-Agent example config contains placeholders only.
6. Qwen config examples contain no ADMIN_TOKEN, raw token, DB path, or local
   absolute path unless explicitly required for local command args and not
   exposed as a tool.
7. Qwen final review output reuses the same structured review JSON and dry-run
   parser as Gemini/DeepSeek.
```

Done when:

```txt
Qwen has documented API and Qwen-Agent paths that are stronger than web-chat
preview, while preserving KnowNet's same read-first and dry-run-first safety
model.
```

Implementation note 2026-05-03:

```txt
Implemented:
  apps/mcp/configs/qwen_agent_mcp.example.json
  apps/mcp/client_profiles/qwen.json
  docs/QWEN_INTEGRATION.md

The current implemented Qwen surface follows the open-source Qwen-Agent MCP
pattern. A Qwen API provider runner remains intentionally unimplemented until
the operator chooses to test DashScope/Qwen API credentials.
Reserved environment names are documented in .env.example for future runner
work: QWEN_API_KEY, QWEN_RUNNER_ENABLED, QWEN_BASE_URL, QWEN_MODEL.
```

## P16-014 Kimi API And Kimi Code MCP Profiles

Goal:

```txt
Support Kimi through API tool_calls and Kimi Code MCP, not through web-chat URL
preview alone.
```

Correct mental model:

```txt
Kimi Web Chat
  -> fallback preview/manual paste only

Kimi API
  -> OpenAI-compatible chat/tool_calls
  -> KnowNet Agent Runner validates and executes tools

Kimi API JSON Router
  -> structured command fallback when tool_calls are not stable enough

Kimi Code MCP
  -> Kimi Code connects to KnowNet MCP server for developer/code workflows
```

Supported modes:

```txt
Phase 16 required:
  Kimi API/OpenAI-compatible tool_calls schema profile.
  Kimi JSON command fallback schema.

Phase 16 optional:
  Kimi Code MCP configuration document.

Later phase candidate:
  Kimi Code live development workflow after KnowNet's own release gate is
  stricter.
```

Configuration:

```txt
KIMI_API_KEY                 required only when Kimi runner is enabled
KIMI_BASE_URL                provider endpoint, default documented during implementation
KIMI_MODEL                   default chosen during implementation after checking official docs
KIMI_RUNNER_ENABLED          default false
KIMI_MAX_CONTEXT_TOKENS      default 32000
KIMI_TIMEOUT_SECONDS         default 90
KIMI_DAILY_RUN_LIMIT         default 20
KIMI_REQUIRE_OPERATOR_IMPORT default true
```

Tool profile:

```txt
Expose only read/review tools first:
  knownet_discover
  knownet_start_here
  knownet_state_summary
  knownet_ai_state
  knownet_list_findings
  knownet_read_page
  knownet_review_dry_run

Do not expose:
  maintenance
  raw database
  backup
  shell/code execution
  arbitrary filesystem read
  direct page write
```

Kimi Code MCP profile:

```txt
Provide a sample Kimi Code MCP config that points at the existing KnowNet MCP
server. Use placeholders only.

Document both possible modes if supported:
  HTTP MCP endpoint for hosted/tunnel gateway
  local command/stdio if Kimi Code supports the operator's environment

The config must not include:
  ADMIN_TOKEN
  raw DB path
  whole-PC filesystem permission
```

JSON command fallback schema:

```json
{
  "action": "knownet_state_summary | knownet_ai_state | knownet_list_findings | knownet_read_page | knownet_review_dry_run",
  "args": {}
}
```

Artifacts:

```txt
docs/KIMI_INTEGRATION.md
GET /tools.kimi.json or equivalent static schema export
GET /schemas/kimi_command.schema.json or static schema file
docs/kimi-code-knownet-mcp.example.json
```

Tests:

```txt
1. Kimi tool schema includes only allowed read/review tools.
2. Kimi tool schema is OpenAI-compatible.
3. Invalid tool name is rejected before KnowNet call.
4. Invalid args are rejected before KnowNet call.
5. JSON command fallback routes to allowed actions only.
6. Kimi Code MCP example config contains placeholders only.
7. Kimi config examples contain no ADMIN_TOKEN, raw token, DB path, or local
   absolute path unless explicitly required for local command args and not
   exposed as a tool.
8. Kimi final review output reuses the same structured review JSON and dry-run
   parser as Gemini/DeepSeek/Qwen.
```

Done when:

```txt
Kimi has documented API and Kimi Code MCP paths that are stronger than web-chat
preview, while preserving KnowNet's same read-first and dry-run-first safety
model.
```

Implementation note 2026-05-03:

```txt
Implemented:
  POST /api/model-runs/kimi/reviews
  Kimi mock adapter through shared MockModelReviewAdapter
  Kimi/Moonshot OpenAI-compatible REST adapter
  apps/mcp/configs/kimi_mcp.example.json
  apps/mcp/client_profiles/kimi.json
  docs/KIMI_INTEGRATION.md

The Kimi runner remains disabled by default and requires KIMI_API_KEY plus
KIMI_RUNNER_ENABLED=true for live calls.
Kimi API key creation requires paid/API access; free web can only use
GET preview or generated review packs.
```

## P16-015 MiniMax API, Mini-Agent, And MCP Profiles

Goal:

```txt
Support MiniMax through API tool calling and Mini-Agent, not through web-chat
URL preview alone.
```

Correct mental model:

```txt
MiniMax Web Chat
  -> fallback preview/manual paste only

MiniMax API
  -> tool_calls/function arguments
  -> KnowNet Agent Runner validates and executes tools

Mini-Agent HTTP Tools
  -> Mini-Agent wraps KnowNet REST/API tools

Mini-Agent MCP
  -> Mini-Agent connects to KnowNet MCP server

Official MiniMax MCP Server
  -> exposes MiniMax capabilities to other clients
  -> not the primary way for MiniMax to read KnowNet
```

Supported modes:

```txt
Phase 16 required:
  MiniMax API tool-calling schema profile.
  Mini-Agent HTTP tool configuration document.

Phase 16 optional:
  Mini-Agent MCP configuration document.

Later phase candidate:
  MiniMax live agent workflow after read-only behavior is verified.
```

Configuration:

```txt
MINIMAX_API_KEY                 required only when MiniMax runner is enabled
MINIMAX_BASE_URL                provider endpoint, default documented during implementation
MINIMAX_MODEL                   default chosen during implementation after checking official docs
MINIMAX_RUNNER_ENABLED          default false
MINIMAX_MAX_CONTEXT_TOKENS      default 32000
MINIMAX_TIMEOUT_SECONDS         default 90
MINIMAX_DAILY_RUN_LIMIT         default 20
MINIMAX_REQUIRE_OPERATOR_IMPORT default true
```

Tool profile:

```txt
Expose only read/review tools first:
  knownet_discover
  knownet_start_here
  knownet_state_summary
  knownet_ai_state
  knownet_list_findings
  knownet_read_page
  knownet_review_dry_run

Do not expose:
  maintenance
  raw database
  backup
  shell/code execution
  arbitrary filesystem read
  direct page write
```

Mini-Agent HTTP profile:

```txt
Provide docs/MINIMAX_AGENT_INTEGRATION.md with:
  install notes
  required environment variables
  KnowNet API base URL
  scoped agent token
  tool list
  first call order
  dry-run-before-submit rule
  warning that official MiniMax MCP is not KnowNet access
```

Mini-Agent MCP profile:

```txt
Provide a sample Mini-Agent MCP config that points at the existing KnowNet MCP
server. Use placeholders only.

The config must not include:
  ADMIN_TOKEN
  raw DB path
  whole-PC filesystem permission
```

Artifacts:

```txt
docs/MINIMAX_AGENT_INTEGRATION.md
GET /tools.minimax.json or equivalent static schema export
docs/minimax-agent-knownet-config.example.json
docs/minimax-agent-knownet-mcp.example.json
```

Tests:

```txt
1. MiniMax tool schema includes only allowed read/review tools.
2. Invalid tool name is rejected before KnowNet call.
3. Invalid args are rejected before KnowNet call.
4. Mini-Agent HTTP example config contains placeholders only.
5. Mini-Agent MCP example config contains placeholders only.
6. MiniMax config examples contain no ADMIN_TOKEN, raw token, DB path, or local
   absolute path unless explicitly required for local command args and not
   exposed as a tool.
7. MiniMax final review output reuses the same structured review JSON and
   dry-run parser as Gemini/DeepSeek/Qwen/Kimi.
```

Done when:

```txt
MiniMax has documented API and Mini-Agent paths that are stronger than web-chat
preview, while preserving KnowNet's same read-first and dry-run-first safety
model.
```

Implementation note:

```txt
Implemented in codebase:
  POST /api/model-runs/minimax/reviews
  MiniMax mock adapter through shared MockModelReviewAdapter
  MiniMax OpenAI-compatible REST adapter
  Read-only in-run tool schema:
    knownet_state_summary
    knownet_ai_state
    knownet_list_findings
  Default live model: MiniMax-M2.7

The MiniMax runner remains disabled by default and requires MINIMAX_API_KEY plus
MINIMAX_RUNNER_ENABLED=true for live calls.
```

## P16-016 GLM Coding Plan, MCP Coding Tools, And Zread

Goal:

```txt
Support GLM/Z.AI through coding-tool MCP workflows and optional API runner,
instead of relying on GLM web chat URL previews.
```

Correct mental model:

```txt
GLM Web Chat
  -> fallback preview/manual paste only

GLM Coding Plan + MCP-capable coding tool
  -> Claude Code / Cline / OpenCode / Cursor / Z Code uses GLM as model
  -> same coding tool connects to KnowNet MCP
  -> KnowNet MCP provides live project state

Zread MCP
  -> public GitHub repo structure/search/file reading
  -> complements KnowNet MCP
  -> does not replace KnowNet MCP

GLM API Agent Runner
  -> optional path similar to DeepSeek/Qwen/Kimi/MiniMax
```

Supported modes:

```txt
Phase 16 required:
  GLM Coding Plan + MCP-capable coding tool documentation.
  KnowNet MCP config examples for GLM-backed coding tools.
  Zread-vs-KnowNet role separation documentation.

Phase 16 optional:
  GLM API Agent Runner schema profile.

Later phase candidate:
  Live GLM coding-tool review with KnowNet MCP after release gate is stricter.
```

Configuration:

```txt
GLM_API_KEY                 required only when GLM API runner is enabled
GLM_BASE_URL                provider endpoint, default documented during implementation
GLM_MODEL                   default chosen during implementation after checking official docs
GLM_RUNNER_ENABLED          default false
GLM_MAX_CONTEXT_TOKENS      default 32000
GLM_TIMEOUT_SECONDS         default 90
GLM_DAILY_RUN_LIMIT         default 20
GLM_REQUIRE_OPERATOR_IMPORT default true
```

MCP coding-tool profile:

```txt
Provide examples for MCP-capable coding tools, not one GLM-only config.

Examples should cover:
  streamable HTTP KnowNet MCP endpoint
  local stdio KnowNet MCP command if supported by the tool
  scoped KNOWNET_AGENT_TOKEN
  placeholder-only bearer token

Do not include:
  ADMIN_TOKEN
  raw DB path
  whole-PC filesystem permission
```

Zread role:

```txt
Zread MCP may read GitHub repository structure and files.
Zread MCP is useful for:
  README/docs inspection
  repo file discovery
  static code review

Zread MCP cannot provide:
  live KnowNet SQLite state
  agent tokens
  collaboration review/finding queue
  current local data/pages not pushed to GitHub
  local health/verify-index

If both are available:
  Use KnowNet MCP for live state.
  Use Zread MCP for public repo code/document lookup.
```

Tool profile for optional GLM API runner:

```txt
Expose only read/review tools first:
  knownet_discover
  knownet_start_here
  knownet_state_summary
  knownet_ai_state
  knownet_list_findings
  knownet_read_page
  knownet_review_dry_run
```

Artifacts:

```txt
docs/GLM_INTEGRATION.md
docs/glm-coding-tool-knownet-mcp.example.json
docs/glm-zread-and-knownet-mcp.md
GET /tools.glm.json or equivalent static schema export if GLM API runner is implemented
```

Tests:

```txt
1. GLM MCP config examples contain placeholders only.
2. GLM MCP config examples contain no ADMIN_TOKEN, raw token, DB path, or
   whole-PC filesystem permission.
3. Documentation clearly separates Zread MCP from KnowNet MCP.
4. Optional GLM API tool schema includes only allowed read/review tools.
5. Optional GLM final review output reuses the same structured review JSON and
   dry-run parser as other provider runners.
```

Done when:

```txt
GLM has a documented path through MCP-capable coding tools plus KnowNet MCP,
and future agents do not confuse Zread GitHub reading with live KnowNet state.
```

Implementation note:

```txt
Implemented in codebase:
  POST /api/model-runs/glm/reviews
  GLM mock adapter through shared MockModelReviewAdapter
  GLM/Z.AI OpenAI-compatible REST adapter
  Read-only in-run tool schema:
    knownet_state_summary
    knownet_ai_state
    knownet_list_findings
  Default live model: glm-5.1
  Default base URL: https://api.z.ai/api/paas/v4

The GLM runner remains disabled by default and requires GLM_API_KEY plus
GLM_RUNNER_ENABLED=true for live calls.
```

## Completion Definition

```txt
Phase 16 is complete when:
  1. Shared model_review_runs are represented in SQLite.
  2. Shared provider adapter contract exists and is tested.
  3. Safe context builder exists, is token-budgeted, and is tested.
  4. Shared structured review output schema is validated.
  5. Dry-run then operator import works through existing review/finding path.
  6. Operator UI exposes the workflow without auto-import.
  7. Cost/rate/concurrency/safety controls are enforced.
  8. Automated tests pass without live provider keys.
  9. One manual live-test procedure is documented per live-capable provider class.
  10. Documentation clarifies MCP vs GET preview vs server-side provider APIs.
  11. Free-vs-paid provider capability matrix is documented.
  12. Claude Desktop local MCP setup is documented and smoke-tested.
  13. Manus HTTPS Custom API/MCP setup is documented and read-only smoke-tested.
  14. DeepSeek API Agent Runner path is documented, schema-limited, and tested
      with mocked API/tool calls.
  15. Qwen API/Qwen-Agent integration paths are documented, schema-limited, and
      tested with mocked tool calls or static config validation.
  16. Kimi API/Kimi Code integration paths are documented, schema-limited, and
      tested with mocked tool calls or static config validation.
  17. MiniMax API/Mini-Agent integration paths are documented, schema-limited,
      and tested with mocked tool calls or static config validation.
  18. GLM Coding Plan/MCP coding-tool path is documented, with Zread and
      KnowNet MCP roles clearly separated.
  19. Every provider has an explicit verification status:
        implemented_mocked, web_preview_verified, test_live_verified, or
        live_verified.
  20. Lack of paid/API access is recorded as a verification limitation, not as
      an implementation blocker.
```

## Suggested Implementation Order

```txt
1. P16-001 Model Runner Architecture
2. P16-001A Provider Adapter Contract
3. P16-002 Gemini Configuration And Secrets
4. P16-003 Safe Context Builder
5. P16-004 Gemini Prompt And Output Schema
6. P16-005 Dry-Run Then Import Workflow
7. P16-008 Tests
8. P16-006 Operator UI
9. P16-007 Cost, Rate Limit, And Safety Controls
10. P16-009 Documentation
11. P16-009A Free Vs Paid Capability Matrix
12. P16-010 Claude Desktop Local MCP Support
13. P16-011 Manus HTTPS Gateway Support
14. P16-012 DeepSeek API Agent Runner
15. P16-013 Qwen API, Qwen-Agent, And MCP Profiles
16. P16-014 Kimi API And Kimi Code MCP Profiles
17. P16-015 MiniMax API, Mini-Agent, And MCP Profiles
18. P16-016 GLM Coding Plan, MCP Coding Tools, And Zread
```
